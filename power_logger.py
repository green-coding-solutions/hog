#!/usr/bin/env python3

# pylint: disable=W0603,W0602
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

from datetime import timezone
from pathlib import Path

from libs import caribou

VERSION = '0.3'

LOG_LEVELS = ['debug', 'info', 'warning', 'error', 'critical']

# Shared variable to signal the thread to stop
stop_signal = threading.Event()

stats = {
    'combined_energy': 0,
    'cpu_energy': 0,
    'gpu_energy': 0,
    'ane_energy': 0,
    'energy_impact': 0,
}

def sigint_handler(_, __):
    global stop_signal
    if stop_signal.is_set():
        # If you press CTR-C the second time we bail
        sys.exit(2)

    stop_signal.set()
    logging.info('Terminating all processes. Please be patient, this might take a few seconds.')

def siginfo_handler(_, __):
    print(SETTINGS)
    print(stats)
    logging.info(f"System stats:\n{stats}\n{SETTINGS}")

signal.signal(signal.SIGINT, sigint_handler)
signal.signal(signal.SIGTERM, sigint_handler)

signal.signal(signal.SIGINFO, siginfo_handler)


APP_NAME = 'berlin.green-coding.hog'
app_support_path = Path(f"/Library/Application Support/{APP_NAME}")
app_support_path.mkdir(parents=True, exist_ok=True)

DATABASE_FILE = app_support_path / 'db.db'

MIGRATIONS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'migrations')

default_settings = {
    'powermetrics': 5000,
    'upload_delta': 300,
    'api_url': 'https://api.green-coding.berlin/v1/hog/add',
    'web_url': 'https://metrics.green-coding.berlin/hog-details.html?machine_uuid=',
    'upload_data': True,
    'resolve_coalitions': ['com.googlecode.iterm2,com.apple.Terminal,com.vix.cron']
}

script_dir = os.path.dirname(os.path.realpath(__file__))

if os.path.exists('/etc/hog_settings.ini'):
    config_path = '/etc/hog_settings.ini'
elif os.path.exists(os.path.join(script_dir, 'settings.ini')):
    config_path = os.path.join(script_dir, 'settings.ini')
else:
    config_path = None

config = configparser.ConfigParser()

SETTINGS = {}
if config_path:
    config.read(config_path)
    SETTINGS = {
        'powermetrics': int(config['DEFAULT'].get('powermetrics', default_settings['powermetrics'])),
        'upload_delta': int(config['DEFAULT'].get('upload_delta', default_settings['upload_delta'])),
        'api_url': config['DEFAULT'].get('api_url', default_settings['api_url']),
        'web_url': config['DEFAULT'].get('web_url', default_settings['web_url']),
        'upload_data': bool(config['DEFAULT'].getboolean('upload_data', default_settings['upload_data'])),
        'resolve_coalitions': config['DEFAULT'].get('resolve_coalitions', default_settings['resolve_coalitions']),
    }
    SETTINGS['resolve_coalitions'] = [x.strip().lower() for x in SETTINGS['resolve_coalitions'].split(',')]
else:
    SETTINGS = default_settings

machine_uuid = None

conn = sqlite3.connect(DATABASE_FILE)
c = conn.cursor()

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

    def process_line(line, buffer):
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
                process_line(line, buffer)

    else:
        cmd = ['powermetrics',
               '--show-all',
               '-i', str(SETTINGS['powermetrics']),
               '-f', 'plist']

        logging.info(f"Starting powermetrics process: {' '.join(cmd)}")

        with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True) as process:

            os.set_blocking(process.stdout.fileno(), False)

            partial_buffer = ''
            while not local_stop_signal.is_set():
                # Make sure that the timeout is greater than the output is coming in
                rlist, _, _ = select.select([process.stdout], [], [], int(SETTINGS['powermetrics'] / 1_000 * 2 ))
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
                            process_line(line, buffer)
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
            sleeper(local_stop_signal, SETTINGS['upload_delta'])
            continue

        payload = []
        for row in rows:
            row_id, time_val, data_val = row

            settings_upload = SETTINGS.copy()
            # We don't need this in the DB on the server
            del settings_upload['api_url']
            del settings_upload['web_url']
            settings_upload['client_version'] = VERSION

            payload.append({
                'time': time_val,
                'data': data_val,
                'settings': json.dumps(settings_upload),
                'machine_uuid': machine_uuid,
                'row_id': row_id
            })

        request_data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url=SETTINGS['api_url'],
                                        data=request_data,
                                        headers={'content-type': 'application/json'},
                                        method='POST')

        logging.info(f"Uploading {len(payload)} rows to: {SETTINGS['api_url']}")

        try:
            with urllib.request.urlopen(req) as response:
                if response.status == 204:
                    for p in payload:
                        tc.execute('UPDATE measurements SET uploaded = ?, data = NULL WHERE id = ?;', (int(time.time()), p['row_id']))
                    thread_conn.commit()
                    logging.debug('Uploaded.')
                else:
                    logging.info(f"Failed to upload data: {payload}\n HTTP status: {response.status}")
                    sleeper(local_stop_signal, SETTINGS['upload_delta']) # Sleep if there is an error

        except (urllib.error.HTTPError,
                ConnectionRefusedError,
                urllib.error.URLError,
                http.client.RemoteDisconnected,
                ConnectionResetError) as exc:
            logging.debug(f"Upload exception: {exc}")
            sleeper(local_stop_signal, SETTINGS['upload_delta']) # Sleep if there is an error

    thread_conn.close()




def find_top_processes(data: list, elapsed_ns:int):
    # As iterm2 will probably show up as it spawns the processes called from the shell we look at the tasks
    new_data = []
    for coalition in data:
        if coalition['name'].lower() in SETTINGS['resolve_coalitions'] or coalition['name'].strip() == '':
            new_data.extend(coalition['tasks'])
        else:
            new_data.append(coalition)

    for p in sorted(new_data, key=lambda k: k['energy_impact'], reverse=True)[:10]:
        yield{
            'name': p['name'],
            # Energy_impact and cputime are broken so we need to use the per_s and convert them
            # Check the https://www.green-coding.berlin/blog/ for details
            'energy_impact': round((p['energy_impact_per_s'] / 1_000_000_000) * elapsed_ns),
            'cputime_ns': ((p['cputime_ms_per_s'] * 1_000_000)  / 1_000_000_000) * elapsed_ns,
        }


def parse_powermetrics_output(output: str):
    global stats

    for data in output.encode('utf-8').split(b'\x00'):
        if data:

            if data == b'powermetrics must be invoked as the superuser\n':
                raise PermissionError('You need to run this script as root!')

            try:
                data=plistlib.loads(data)
                data['timezone'] = time.tzname
                data['timestamp'] = int(data['timestamp'].replace(tzinfo=timezone.utc).timestamp() * 1e3)
            except xml.parsers.expat.ExpatError as exc:
                logging.error(f"XML Error:\n{data}")
                raise exc

            compressed_data = zlib.compress(str(json.dumps(data)).encode())
            compressed_data_str = base64.b64encode(compressed_data).decode()

            c.execute('INSERT INTO measurements (time, data, uploaded) VALUES (?, ?, 0)',
                    (data['timestamp'], compressed_data_str))

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

            c.execute('''INSERT INTO power_measurements
                      (time, combined_energy, cpu_energy, gpu_energy, ane_energy, energy_impact) VALUES
                      (?, ?, ?, ?, ?, ?)''',
                    (data['timestamp'],
                     cpu_energy_data['combined_energy'],
                     cpu_energy_data['cpu_energy'],
                     cpu_energy_data['gpu_energy'],
                     cpu_energy_data['ane_energy'],
                     cpu_energy_data['energy_impact']))

            for key in stats:
                stats[key] += cpu_energy_data[key]


            for process in find_top_processes(data['coalitions'], data['elapsed_ns']):
                cpu_per = int(process['cputime_ns'] / data['elapsed_ns'] * 100)
                c.execute('INSERT INTO top_processes (time, name, energy_impact, cputime_per) VALUES (?, ?, ?, ?)',
                    (data['timestamp'], process['name'], process['energy_impact'], cpu_per))

            conn.commit()
            logging.debug('Data added to the DB')

def save_settings():
    global machine_uuid

    c.execute('SELECT machine_uuid, powermetrics, api_url, web_url, upload_delta, upload_data FROM settings ORDER BY time DESC LIMIT 1;')
    result = c.fetchone()

    if result:
        machine_uuid, last_powermetrics, last_api_url, last_web_url, last_upload_delta, last_upload_data = result

        if (last_powermetrics == SETTINGS['powermetrics'] and
            last_api_url.strip() == SETTINGS['api_url'].strip() and
            last_web_url.strip() == SETTINGS['web_url'].strip() and
            last_upload_delta == SETTINGS['upload_delta'] and
            last_upload_data == SETTINGS['upload_data']):
            return False
    else:
        machine_uuid = str(uuid.uuid1())

    c.execute('''INSERT INTO settings
            (time, machine_uuid, powermetrics, api_url, web_url, upload_delta, upload_data) VALUES
            (?, ?, ?, ?, ?, ?, ?)''', (
                int(time.time()),
                machine_uuid,
                SETTINGS['powermetrics'],
                SETTINGS['api_url'].strip(),
                SETTINGS['web_url'].strip(),
                SETTINGS['upload_delta'],
                SETTINGS['upload_data'],
            ))

    conn.commit()
    logging.debug(f"Saved Settings:\n{SETTINGS}")

    return True


def check_DB(local_stop_signal):
    # The powermetrics script should return ever SETTINGS['powermetrics'] ms but because of the way we batch things
    # we will not get values every n ms so we have quite a big value here.
    # powermetrics = 5000 ms in production and 1000 in dev mode

    interval_sec = SETTINGS['powermetrics'] * 20  / 1_000

    # We first sleep for quite some time to give the program some time to add data to the DB
    sleeper(local_stop_signal, interval_sec)

    thread_conn = sqlite3.connect(DATABASE_FILE)
    tc = thread_conn.cursor()

    while not local_stop_signal.is_set():
        n_ago = int((time.time() - interval_sec) * 1_000)

        tc.execute('SELECT MAX(time) FROM measurements')
        result = tc.fetchone()

        if result and result[0]:
            if result[0] < n_ago:
                logging.error('No new data in DB. Exiting to be restarted by the os')
                local_stop_signal.set()
        else:
            logging.error('We are not getting values from the DB for checker thread.')

        logging.debug('DB Check')
        sleeper(local_stop_signal, interval_sec)

    thread_conn.close()


def is_power_logger_running():
    try:
        subprocess.check_output(['pgrep', '-f', sys.argv[0]])
        logging.error(f"There is already a {sys.argv[0]} process running! Maybe check launchctl?")
        sys.exit(4)
    except subprocess.CalledProcessError:
        return False


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
                                     ''')
    parser.add_argument('-d', '--dev', action='store_true', help='Enable development mode api endpoints and log level.')
    parser.add_argument('-w', '--website', action='store_true', help='Shows the website URL')
    parser.add_argument('-f', '--file', type=str, help='Path to the input file')
    parser.add_argument('-v', '--log-level', choices=LOG_LEVELS, default='info', help='Logging level (debug, info, warning, error, critical)')
    parser.add_argument('-o', '--output-file', type=str, help='Path to the output log file.')

    args = parser.parse_args()

    if args.dev:
        SETTINGS = {
            'powermetrics' : 1000,
            'upload_delta': 5,
            'api_url': 'http://api.green-coding.internal:9142/v1/hog/add',
            'web_url': 'http://metrics.green-coding.internal:9142/hog-details.html?machine_uuid=',
            'upload_data': True,
        }
        args.log_level = 'debug'

    log_level = getattr(logging, args.log_level.upper())

    if args.output_file:
        logging.basicConfig(filename=args.output_file, level=log_level, format='[%(levelname)s] %(asctime)s - %(message)s')
    else:
        logging.basicConfig(level=log_level, format='[%(levelname)s] %(asctime)s - %(message)s')

    logging.debug('Program started.')
    logging.debug(f"Using db: {DATABASE_FILE}")


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
        logging.debug(f"Setting: {SETTINGS}")


    if args.website:
        print('Please visit this url for detailed analytics:')
        print(f"{SETTINGS['web_url']}{machine_uuid}")
        sys.exit(0)

    if SETTINGS['upload_data']:
        upload_thread = threading.Thread(target=upload_data_to_endpoint, args=(stop_signal,))
        upload_thread.start()
        logging.debug('Upload thread started')

    db_checker_thread = threading.Thread(target=check_DB, args=(stop_signal,), daemon=True)
    db_checker_thread.start()
    logging.debug('DB checker thread started')

    run_powermetrics(stop_signal, args.file)

    c.close()
