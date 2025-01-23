#!/usr/bin/env python3

# pylint: disable=W0603,W0602,W1203,W0702
import json
import subprocess
import time
import plistlib
import argparse
import zlib
import base64
import xml
import signal
import sys
import uuid
import os
import os.path
import stat
import urllib.request
import configparser
import sqlite3
import http
import threading
import logging
import select
import math

from datetime import timezone
from pathlib import Path

from libs import caribou

VERSION = '0.6'

LOG_LEVELS = ['debug', 'info', 'warning', 'error', 'critical']

# Shared variable to signal the thread to stop
stop_signal = threading.Event()

class SharedTime:
    def __init__(self):
        self._time = time.time()
        self._lock = threading.Lock()

    def set_tick(self):
        with self._lock:
            self._time = time.time()

    def get_tick(self):
        with self._lock:
            return self._time



APP_NAME = 'io.green-coding.hogger'
APP_SUPPORT_PATH = Path(f"/Library/Application Support/{APP_NAME}")
APP_SUPPORT_PATH.mkdir(parents=True, exist_ok=True)

DATABASE_FILE = APP_SUPPORT_PATH / 'db.db'

stats = {
    'combined_energy': 0,
    'cpu_energy': 0,
    'gpu_energy': 0,
    'ane_energy': 0,
    'energy_impact': 0,
}

MIGRATIONS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'migrations')

global_settings = {}

machine_uuid = None

conn = sqlite3.connect(DATABASE_FILE)
c = conn.cursor()

def kill_program():
    # We set the stop_signal for everything to shut down in an orderly fashion
    global stop_signal
    stop_signal.set()
    logging.info('Stopping program due to an inconsistent state of the program. Probably the upload blocking')
    time.sleep(5) # Give everything some time to shutdown
    # Now we need to exit the program as the upload thread is not responding and needs to be killed
    os._exit(5)

def sigint_handler(_, __):
    global stop_signal
    if stop_signal.is_set():
        # If you press CTR-C the second time we bail
        sys.exit(2)

    stop_signal.set()
    logging.info('Terminating all processes. Please be patient, this might take a few seconds.')

def siginfo_handler(_, __):
    print(global_settings)
    print(stats)
    logging.info(f"System stats:\n{stats}\n{global_settings}")

signal.signal(signal.SIGINT, sigint_handler)
signal.signal(signal.SIGTERM, sigint_handler)

signal.signal(signal.SIGINFO, siginfo_handler)



# This is a replacement for time.sleep as we need to check periodically if we need to exit
# We choose a max exit time of one second as we don't want to wake up too often.
def sleeper(stop_event, duration):
    end_time = time.time() + duration
    while time.time() < end_time:
        if stop_event.is_set():
            return
        time.sleep(1)


def run_powermetrics(local_stop_signal, filename: str = None):
    buffer = []

    def process_line(line):
        line = line.strip().replace('&', '&amp;')
        buffer.append(line)

        if line == '</plist>':
            logging.debug('Parsing new input')
            parse_powermetrics_output(''.join(buffer))
            buffer.clear()

            logging.info(stats)

    if filename:
        logging.info(f"Reading file {filename}")
        with open(filename, 'r', encoding='utf-8') as file:
            for line in file.readlines():
                process_line(line)

    else:
        cmd = ['powermetrics',
               '--show-all',
               '-i', str(global_settings['powermetrics']),
               '-f', 'plist']

        logging.info(f"Starting powermetrics process: {' '.join(cmd)}")

        with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True) as process:

            os.set_blocking(process.stdout.fileno(), False)

            partial_buffer = ''
            while not local_stop_signal.is_set():
                # Make sure that the timeout is greater than the output is coming in
                rlist, _, _ = select.select([process.stdout], [], [], int(global_settings['powermetrics'] / 1_000 * 2 ))
                if rlist:
                    # This is a little hacky. The problem is that select just reads data and doesn't respect the lines
                    # so it happens that we read in the middle of a line.
                    data = rlist[0].read()
                    data = partial_buffer + data
                    lines = data.splitlines()
                    try:
                        if not data.endswith('\n'):
                            partial_buffer = lines.pop()
                        else:
                            partial_buffer = ''

                        for line in lines:
                            process_line(line)
                    except IndexError:
                        # This happens when the process is killed before we exit here so stop_signal should be set. If not
                        # there is a problem with powermetrics and we should report and exit.
                        if not local_stop_signal.is_set():
                            logging.error('The pipe to powermetrics has been closed. Exiting')
                            local_stop_signal.set()


def upload_data_to_endpoint(local_stop_signal):
    thread_conn = sqlite3.connect(DATABASE_FILE)
    tc = thread_conn.cursor()

    while not local_stop_signal.is_set():
        # We need to limit the amount of data here as otherwise the payload becomes to big
        tc.execute('SELECT id, time, data FROM measurements WHERE uploaded = 0 LIMIT 10;')
        rows = tc.fetchall()

        # When everything is uploaded we sleep
        if not rows:
            sleeper(local_stop_signal, global_settings['upload_delta'])
            continue

        payload = []
        for row in rows:
            row_id, time_val, data_val = row

            settings_upload = global_settings.copy()
            # We don't need this in the DB on the server
            del settings_upload['api_url']
            del settings_upload['gmt_auth_token']
            del settings_upload['electricitymaps_token']

            settings_upload['client_version'] = VERSION

            payload.append({
                'time': time_val,
                'data': data_val,
                'settings': json.dumps(settings_upload),
                'machine_uuid': machine_uuid,
                'row_id': row_id
            })

        request_data = json.dumps(payload).encode('utf-8')
        headers = {'content-type': 'application/json'}
        if global_settings['gmt_auth_token']:
            headers['X-Authentication'] = global_settings['gmt_auth_token']

        req = urllib.request.Request(url=global_settings['api_url'],
                                        data=request_data,
                                        headers=headers,
                                        method='POST')

        logging.info(f"Uploading {len(payload)} rows to: {global_settings['api_url']}")

        # As sometimes the urllib waits for ever ignoring the timeout we set a signal for 30 seconds and if it hasn't
        # been canceled we kill everything
        kill_timer = threading.Timer(60.0, kill_program)
        kill_timer.start()

        try:
            start_time = time.time()
            with urllib.request.urlopen(req, timeout=30) as response:
                if response.status == 204:
                    for p in payload:
                        tc.execute('DELETE FROM measurements WHERE id = ?;', (p['row_id'],))
                    thread_conn.commit()
                    upload_delta = time.time() - start_time
                    logging.debug(f"Uploaded. Took {upload_delta:.2f} seconds")
                else:
                    logging.info(f"Failed to upload data: {payload}\n HTTP status: {response.status}")
                    sleeper(local_stop_signal, global_settings['upload_delta']) # Sleep if there is an error
                kill_timer.cancel()
        except (urllib.error.HTTPError,
                ConnectionRefusedError,
                urllib.error.URLError,
                http.client.RemoteDisconnected,
                ConnectionResetError) as exc:
            logging.debug(f"Upload exception: {exc}")
            kill_timer.cancel()
            sleeper(local_stop_signal, global_settings['upload_delta']) # Sleep if there is an error
    thread_conn.close()




def find_top_processes(data: list, elapsed_ns:int):
    # As iterm2 will probably show up as it spawns the processes called from the shell we look at the tasks
    # new_data = []
    # for coalition in data:
    #     if coalition['name'].lower() in global_settings['resolve_coalitions'] or coalition['name'].strip() == '':
    #         new_data.extend(coalition['tasks'])
    #     else:
    #         new_data.append(coalition)
    output = []
    for p in sorted(data, key=lambda k: k['energy_impact'], reverse=True)[:15]:
        output.append({
            'name': p['name'],
            # Energy_impact and cputime are broken so we need to use the per_s and convert them
            # Check the https://www.green-coding.io/blog/ for details
            'energy_impact': round((p['energy_impact_per_s'] / 1_000_000_000) * elapsed_ns),
            'cputime_ms': p['cputime_ms_per_s'] * (elapsed_ns / 1_000_000_000),
        })
    return output


class RemoveNaNEncoder(json.JSONEncoder):
    def encode(self, obj):
        def remove_nan(o):
            if isinstance(o, dict):
                return {remove_nan(k): remove_nan(v) for k, v in o.items()
                        if not ((isinstance(k, float) and math.isnan(k)) or
                                (isinstance(v, float) and math.isnan(v)))}
            elif isinstance(o, list):
                return [remove_nan(v) for v in o
                        if not (isinstance(v, float) and math.isnan(v))]
            else:
                return o
        cleaned_obj = remove_nan(obj)
        return super(RemoveNaNEncoder, self).encode(cleaned_obj)


def get_cmdline_shell_ps(pid):
    try:
        result = subprocess.run(
            ['ps', '-p', str(pid), '-o', 'command='],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None

def resolve_names(data):
    updated_coalitions = []

    for coalition in data['coalitions']:
        name = coalition['name'].strip().lower()
        if name in global_settings['resolve_coalitions'] or not name:
            tasks = coalition.get('tasks', [])
            updated_coalitions.extend(tasks if isinstance(tasks, list) else [coalition])
        else:
            updated_coalitions.append(coalition)

    for i, coalition in enumerate(updated_coalitions):
        if coalition['name'].lower().strip() in global_settings['resolve_process']:
            if cmd := get_cmdline_shell_ps(coalition['pid']):
                updated_coalitions[i]['name'] = cmd

    data['coalitions'] = updated_coalitions

    return data

get_grid_intensity_cache = {'value': None, 'timestamp': 0}

def get_grid_intensity():
    global get_grid_intensity_cache

    if not global_settings.get('electricitymaps_token'):
        return None

    if time.time() - get_grid_intensity_cache['timestamp'] < 900:
        return get_grid_intensity_cache['value']

    url = 'https://api.electricitymap.org/v3/carbon-intensity/latest'
    headers = {'auth-token': global_settings['electricitymaps_token']}

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as response:
            response_data = json.loads(response.read().decode())
            get_grid_intensity_cache = {
                'value': response_data['carbonIntensity'],
                'timestamp': time.time()
            }
    except (urllib.error.HTTPError,
            ConnectionRefusedError,
            urllib.error.URLError,
            http.client.RemoteDisconnected,
            ConnectionResetError) as exc:
        logging.error(f"Failed to fetch grid intensity: {exc}")
    finally:
        return get_grid_intensity_cache['value']  # Return last cached value on error

def parse_powermetrics_output(output: str):
    global stats

    for data in output.encode('utf-8').split(b'\x00'):
        if data:
            grid_intensity = get_grid_intensity()

            if data == b'powermetrics must be invoked as the superuser\n':
                raise PermissionError('You need to run this script as root!')

            try:
                data = plistlib.loads(data)
                data = resolve_names(data)
                # Sql can not handle timestamps so we convert them to milliseconds
                data['timestamp'] = int(data['timestamp'].replace(tzinfo=timezone.utc).timestamp() * 1e3)
            except xml.parsers.expat.ExpatError as exc:
                logging.error(f"XML Error:\n{data}")
                raise exc


            cpu_energy_data = {}
            energy_impact = round(data['all_tasks'].get('energy_impact_per_s') * data['elapsed_ns'] / 1_000_000_000)
            if 'ane_energy' in data['processor']:
                cpu_energy_data = {
                    'combined_energy': round(data['processor'].get('combined_power', 0) * data['elapsed_ns'] / 1_000_000_000.0),
                    'cpu_energy': round(data['processor'].get('cpu_energy', 0)),
                    'gpu_energy': round(data['processor'].get('gpu_energy', 0)),
                    'ane_energy': round(data['processor'].get('ane_energy', 0)),
                    'energy_impact': energy_impact,
                }
            elif 'package_joules' in data['processor']:
                # Intel processors report in joules/ watts and not mJ
                cpu_energy_data = {
                    'combined_energy': round(data['processor'].get('package_joules', 0) * 1_000),
                    'cpu_energy': round(data['processor'].get('cpu_joules', 0) * 1_000),
                    'gpu_energy': round(data['processor'].get('igpu_watts', 0) * data['elapsed_ns'] / 1_000_000_000.0 * 1_000),
                    'ane_energy': 0,
                    'energy_impact': energy_impact,
                }

            if grid_intensity:
                co2eq = cpu_energy_data['combined_energy'] * grid_intensity / 3_600_000_000 # We need to convert to kWh from mJ
            else:
                co2eq = None


            c.execute('''INSERT INTO power_measurements
                      (time, combined_energy, cpu_energy, gpu_energy, ane_energy, energy_impact, co2eq ) VALUES
                      (?, ?, ?, ?, ?, ?, ?)''',
                    (data['timestamp'],
                     cpu_energy_data['combined_energy'],
                     cpu_energy_data['cpu_energy'],
                     cpu_energy_data['gpu_energy'],
                     cpu_energy_data['ane_energy'],
                     cpu_energy_data['energy_impact'],
                     co2eq))

            for key in stats:
                stats[key] += cpu_energy_data[key]

            top_processes = find_top_processes(data['coalitions'], data['elapsed_ns'])
            for process in top_processes:
                c.execute('INSERT INTO top_processes (time, name, energy_impact, cputime_per) VALUES (?, ?, ?, ?)',
                    (data['timestamp'], process['name'], process['energy_impact'], process['energy_impact']))


            # Create the new upload data structure
            upload_data = {
                'machine_uuid': machine_uuid,
                'timestamp': data['timestamp'],
                'top_processes': top_processes,
                'timestamp': data['timestamp'],
                'timezone': f"{time.tzname[0]}/{time.tzname[1]}",
                'grid_intensity': grid_intensity,
                'combined_energy': cpu_energy_data['combined_energy'],
                'cpu_energy': cpu_energy_data['cpu_energy'],
                'gpu_energy': cpu_energy_data['gpu_energy'],
                'ane_energy': cpu_energy_data['ane_energy'],
                'energy_impact': cpu_energy_data['energy_impact'],
                'co2eq': co2eq,
                'hw_model': data['hw_model'],
                'elapsed_ns': data['elapsed_ns'],
                'thermal_pressure': data['thermal_pressure'],
            }

            compressed_data = zlib.compress(str(json.dumps(upload_data, cls=RemoveNaNEncoder)).encode())
            compressed_data_str = base64.b64encode(compressed_data).decode()

            c.execute('INSERT INTO measurements (time, data, uploaded) VALUES (?, ?, 0)',
                    (data['timestamp'], compressed_data_str))

            conn.commit()
            logging.debug('Data added to the DB')

def save_settings():
    global machine_uuid

    c.execute('SELECT machine_uuid, powermetrics, api_url, upload_delta, upload_data FROM settings ORDER BY time DESC LIMIT 1;')
    result = c.fetchone()

    if result:
        machine_uuid, last_powermetrics, last_api_url, last_upload_delta, last_upload_data = result

        if (last_powermetrics == global_settings['powermetrics'] and
            last_api_url.strip() == global_settings['api_url'].strip() and
            last_upload_delta == global_settings['upload_delta'] and
            last_upload_data == global_settings['upload_data']):
            return False
    else:
        machine_uuid = str(uuid.uuid1())

    c.execute('''INSERT INTO settings
            (time, machine_uuid, powermetrics, api_url, upload_delta, upload_data) VALUES
            (?, ?, ?, ?, ?, ?)''', (
                int(time.time()),
                machine_uuid,
                global_settings['powermetrics'],
                global_settings['api_url'].strip(),
                global_settings['upload_delta'],
                global_settings['upload_data'],
            ))

    conn.commit()
    logging.debug(f"Saved Settings:\n{global_settings}")

    return True

def is_powermetrics_running():
    try:
        output = subprocess.check_output('pgrep powermetrics', shell=True).decode()
        return bool(output.strip())
    except:
        return False

def check_DB(local_stop_signal, stime: SharedTime):
    # The powermetrics script should return ever global_settings['powermetrics'] ms but because of the way we batch things
    # we will not get values every n ms so we have quite a big value here.
    # powermetrics = 5000 ms in production and 1000 in dev mode

    interval_sec = global_settings['powermetrics'] * 20  / 1_000

    # We first sleep for quite some time to give the program some time to add data to the DB
    sleeper(local_stop_signal, interval_sec)

    thread_conn = sqlite3.connect(DATABASE_FILE)
    tc = thread_conn.cursor()

    while not local_stop_signal.is_set():
        logging.debug('DB Check')

        n_ago = int((stime.get_tick() - interval_sec) * 1_000)

        tc.execute('SELECT MAX(time) FROM measurements')
        result = tc.fetchone()

        if result and result[0]:
            if result[0] < n_ago:
                logging.error('No new data in DB. Exiting to be restarted by the os')
                local_stop_signal.set()
        else:
            logging.error('We are not getting values from the DB for checker thread.')

        logging.debug('Power metrics running check')
        if not is_powermetrics_running():
            logging.error('Powermetrics is not running. Stopping!')
            local_stop_signal.set()

        sleeper(local_stop_signal, interval_sec)


    thread_conn.close()


def optimize_DB(local_stop_signal):
    while not local_stop_signal.is_set():

        logging.debug("Starting DB optimization for power_measurements")

        thread_conn = sqlite3.connect(DATABASE_FILE)
        tc = thread_conn.cursor()

        # This is for legacy systems. We just make sure that there are no values left
        tc.execute('DELETE FROM measurements WHERE data IS NULL;')

        one_week_ago = int(time.time() * 1000) - 7 * 24 * 60 * 60 * 1000  # Adjusted for milliseconds

        aggregate_query = """
        SELECT
            strftime('%s', date(time / 1000, 'unixepoch')) * 1000 AS day_epoch,
            SUM(combined_energy),
            SUM(cpu_energy),
            SUM(gpu_energy),
            SUM(ane_energy),
            SUM(energy_impact),
            SUM(co2eq)
        FROM
            power_measurements
        WHERE
            time < ?
        GROUP BY
            day_epoch;
        """
        tc.execute(aggregate_query, (one_week_ago,))
        aggregated_data = tc.fetchall()

        tc.execute("""
            CREATE TEMPORARY TABLE temp_power_measurements (
                time INT,
                combined_energy INT,
                cpu_energy INT,
                gpu_energy INT,
                ane_energy INT,
                energy_impact INT,
                co2eq FLOAT
            );
        """)

        insert_temp_query = """
            INSERT INTO temp_power_measurements (time, combined_energy, cpu_energy, gpu_energy, ane_energy, energy_impact, co2eq)
            VALUES (?, ?, ?, ?, ?, ?, ?);
        """
        tc.executemany(insert_temp_query, aggregated_data)

        delete_query = """
            DELETE FROM power_measurements WHERE time < ?;
        """
        tc.execute(delete_query, (one_week_ago,))

        insert_back_query = """
            INSERT INTO power_measurements (time, combined_energy, cpu_energy, gpu_energy, ane_energy, energy_impact, co2eq)
            SELECT * FROM temp_power_measurements;
        """
        tc.execute(insert_back_query)

        tc.execute("DROP TABLE temp_power_measurements;")

        logging.debug("Starting DB optimization for top_processes")

        # Do the same with processes
        aggregate_query = """
            SELECT
                name,
                SUM(energy_impact) AS total_energy_impact,
                AVG(cputime_per) AS average_cputime_per
            FROM
                top_processes
            WHERE
                time < ?
            GROUP BY
                name;
        """
        tc.execute(aggregate_query, (one_week_ago,))
        aggregated_data = tc.fetchall()

        tc.execute("""
            CREATE TEMPORARY TABLE temp_top_processes (
                name STRING,
                total_energy_impact INT,
                average_cputime_per INT
            );
        """)

        insert_temp_query = """
            INSERT INTO temp_top_processes (name, total_energy_impact, average_cputime_per)
            VALUES (?, ?, ?);
        """
        tc.executemany(insert_temp_query, aggregated_data)

        tc.execute("DELETE FROM top_processes WHERE time < ?;", (one_week_ago,))

        insert_back_query = """
            INSERT INTO top_processes (time, name, energy_impact, cputime_per)
            SELECT ?, name, total_energy_impact, average_cputime_per FROM temp_top_processes;
        """
        tc.execute(insert_back_query, (one_week_ago,))

        # Drop the temporary table
        tc.execute("DROP TABLE temp_top_processes;")

        thread_conn.commit()

        # We vacuum to actually reduce the file size. We probably don't need to vacuum this often but I would rather
        # do it here then have another thread.
        tc.execute("VACUUM;")

        logging.debug("Ending DB optimization")

        sleeper(local_stop_signal, 3600) # We only need to optimize every hour

        thread_conn.close()


def is_power_logger_running():
    try:
        subprocess.check_output(['pgrep', '-f', sys.argv[0]])
        logging.error(f"There is already a {sys.argv[0]} process running! Maybe check launchctl?")
        sys.exit(4)
    except subprocess.CalledProcessError:
        return False

def set_tick(local_stop_signal, stime):
    while not local_stop_signal.is_set():
        stime.set_tick()
        sleeper(local_stop_signal, 1)


def get_settings(debug = False):
    if debug:
        return {
            'powermetrics' : 1000,
            'upload_delta': 5,
            'api_url': 'http://api.green-coding.internal:9142/v2/hog/add',
            'upload_data': True,
            'resolve_coalitions': ['com.googlecode.iterm2', 'com.apple.terminal', 'com.vix.cron', 'org.alacritty'],
            'resolve_process': ['python',],
            'gmt_auth_token': None,
            'electricitymaps_token': None,
        }


    default_settings = {
        'powermetrics': 5000,
        'upload_delta': 300,
        'api_url': 'https://api.green-coding.io/v2/hog/add',
        'upload_data': True,
        'resolve_coalitions': 'com.googlecode.iterm2,com.apple.Terminal,com.vix.cron,org.alacritty',
        'resolve_process': ['python',],
        'gmt_auth_token': None,
        'electricitymaps_token': None,
    }

    script_dir = os.path.dirname(os.path.realpath(__file__))

    if os.path.exists('/etc/hogger_settings.ini'):
        config_path = '/etc/hogger_settings.ini'
    elif os.path.exists(os.path.join(script_dir, 'settings.ini')):
        config_path = os.path.join(script_dir, 'settings.ini')
    else:
        config_path = None

    config = configparser.ConfigParser()

    ret_settings = {}

    if config_path:
        config.read(config_path)
        logging.debug(f"Using {config_path} as settings file.")
        ret_settings = {
            'powermetrics': int(config['DEFAULT'].get('powermetrics', default_settings['powermetrics'])),
            'upload_delta': int(config['DEFAULT'].get('upload_delta', default_settings['upload_delta'])),
            'api_url': config['DEFAULT'].get('api_url', default_settings['api_url']),
            'upload_data': bool(config['DEFAULT'].getboolean('upload_data', default_settings['upload_data'])),
            'resolve_coalitions': config['DEFAULT'].get('resolve_coalitions', default_settings['resolve_coalitions']),
            'resolve_process': config['DEFAULT'].get('resolve_process', default_settings['resolve_process']),
            'gmt_auth_token': config['DEFAULT'].get('gmt_auth_token', default_settings['gmt_auth_token']),
            'electricitymaps_token': config['DEFAULT'].get('electricitymaps_token', default_settings['electricitymaps_token']),
        }
    else:
        ret_settings = default_settings

    if not isinstance(ret_settings['resolve_coalitions'], list):
        ret_settings['resolve_coalitions'] = [x.strip().lower() for x in ret_settings['resolve_coalitions'].split(',')]

    if not isinstance(ret_settings['resolve_process'], list):
        ret_settings['resolve_process'] = [x.strip().lower() for x in ret_settings['resolve_process'].split(',')]

    return ret_settings


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=
                                     '''
                                     A power collection script that records a multitude of metrics and saves them to
                                     a database. Also uploads the data to a server.
                                     Exit codes:
                                        1 - run as root
                                        2 - force quit
                                        3 - db not updated
                                        4 - already a power_logger process is running
                                        5 - program was forced killed because of network deadlock
                                     ''')
    parser.add_argument('-d', '--dev', action='store_true', help='Enable development mode api endpoints and log level.')
    parser.add_argument('-w', '--website', action='store_true', help='Shows the website URL')
    parser.add_argument('-f', '--file', type=str, help='Path to the input file')
    parser.add_argument('-v', '--log-level', choices=LOG_LEVELS, default='info', help='Logging level')
    parser.add_argument('-o', '--output-file', type=str, help='Path to the output log file.')

    args = parser.parse_args()

    if args.dev:
        args.log_level = 'debug'

    log_level = getattr(logging, args.log_level.upper())

    if args.output_file:
        logging.basicConfig(filename=args.output_file, level=log_level, format='[%(levelname)s] %(asctime)s - %(message)s')
    else:
        logging.basicConfig(level=log_level, format='[%(levelname)s] %(asctime)s - %(message)s')

    logging.debug('Program started.')
    logging.debug(f"Using db: {DATABASE_FILE}")

    global_settings = get_settings(args.dev)

    if os.geteuid() != 0:
        logging.error('The script needs to be run as root!')
        sys.exit(1)

    is_power_logger_running()

    # Make sure that everyone can write to the DB
    os.chmod(DATABASE_FILE, stat.S_IRUSR | stat.S_IWUSR |
                stat.S_IRGRP | stat.S_IWGRP |
                stat.S_IROTH | stat.S_IWOTH)


    # Make sure the DB is migrated
    caribou.upgrade(DATABASE_FILE, MIGRATIONS_PATH)

    if not save_settings():
        logging.debug(f"Setting: {global_settings}")


    if args.website:
        print('This has been discontinued. You now need to log in to the Green Metrics Tool to see the data.')
        sys.exit(0)

    # We need to introduce a a time holding obj as otherwise the times don't sync when the computer sleeps.
    shared_time = SharedTime()

    if global_settings['upload_data']:
        upload_thread = threading.Thread(target=upload_data_to_endpoint, args=(stop_signal,))
        upload_thread.start()
        logging.debug('Upload thread started')

    db_checker_thread = threading.Thread(target=check_DB, args=(stop_signal, shared_time), daemon=True)
    db_checker_thread.start()
    logging.debug('DB checker thread started')

    ticker_thread = threading.Thread(target=set_tick, args=(stop_signal, shared_time), daemon=True)
    ticker_thread.start()
    logging.debug('Ticker thread started')

    db_checker_thread = threading.Thread(target=optimize_DB, args=(stop_signal,), daemon=True)
    db_checker_thread.start()
    logging.debug('DB optimizer thread started')


    run_powermetrics(stop_signal, args.file)

    c.close()
