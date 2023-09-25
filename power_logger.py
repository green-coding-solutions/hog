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
from datetime import timezone
from pathlib import Path

from libs import caribou


# Shared variable to signal the thread to stop
stop_signal = False

stats = {
    'combined_power': 0,
    'cpu_energy': 0,
    'gpu_energy': 0,
    'ane_energy': 0,
    'energy_impact': 0,
}

def sigint_handler(_, __):
    global stop_signal
    if stop_signal:
        # If you press CTR-C the second time we bail
        sys.exit()

    stop_signal = True
    print('Received stop signal. Terminating all processes.')

def siginfo_handler(_, __):
    print(SETTINGS)
    print(stats)

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
    'web_url': 'http://metrics.green-coding.berlin/hog-details.html?machine_uuid=',
    'upload_data': True,
}

home_dir = os.path.expanduser('~')
script_dir = os.path.dirname(os.path.realpath(__file__))

if os.path.exists(os.path.join(home_dir, '.hog_settings.ini')):
    config_path = os.path.join(home_dir, '.hog_settings.ini')
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
    }
else:
    SETTINGS = default_settings



machine_uuid = None

conn = sqlite3.connect(DATABASE_FILE)
c = conn.cursor()


def run_powermetrics(debug: bool, filename: str = None):

    def process_lines(lines, debug):
        buffer = []
        last_upload_time = time.time()
        for line in lines:
            line = line.strip().replace('&', '&amp;')
            buffer.append(line)
            if line == '</plist>':
                parse_powermetrics_output(''.join(buffer))

                if debug:
                    print(stats)
                    sys.stdout.flush()

                buffer = []

                if SETTINGS['upload_data']:
                    current_time = time.time()
                    if current_time - last_upload_time >= SETTINGS['upload_delta']:
                        upload_data_to_endpoint()
                        last_upload_time = current_time

            if stop_signal:
                break

    if filename:
        with open(filename, 'r', encoding='utf-8') as file:
            lines = file.readlines()
            process_lines(lines, debug)
    else:
        cmd = ['powermetrics',
               '--show-all',
               '-i', str(SETTINGS['powermetrics']),
               '-f', 'plist']

        with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True) as process:
            process_lines(process.stdout, debug)

            if stop_signal:
                process.terminate()

    # Make sure that all data has been uploaded when exiting
    upload_data_to_endpoint()

def upload_data_to_endpoint():
    retry_counter = 0
    while True:
        retry_counter  += 1
        # We need to limit the amount of data here as otherwise the payload becomes to big
        c.execute('SELECT id, time, data FROM measurements WHERE uploaded = 0 LIMIT 10;')
        rows = c.fetchall()

        if not rows or retry_counter > 3:
            retry_counter = 0
            break

        payload = []
        for row in rows:
            row_id, time_val, data_val = row

            settings_upload = SETTINGS.copy()
            # We don't need this in the DB on the server
            del settings_upload['api_url']
            del settings_upload['web_url']

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
        try:
            with urllib.request.urlopen(req) as response:
                if response.status == 200:
                    for p in payload:
                        c.execute('UPDATE measurements SET uploaded = ?, data = NULL WHERE id = ?;', (int(time.time()), p['row_id']))
                    conn.commit()
                else:
                    print(f"Failed to upload data: {payload}\n HTTP status: {response.status}")
        except (urllib.error.HTTPError,
                ConnectionRefusedError,
                urllib.error.URLError,
                http.client.RemoteDisconnected,
                ConnectionResetError):
                break


def find_top_processes(data: list):
    # As iterm2 will probably show up as it spawns the processes called from the shell we look at the tasks
    new_data = []
    for coalition in data:
        if coalition['name'] == 'com.googlecode.iterm2' or coalition['name'].strip() == '':
            new_data.extend(coalition['tasks'])
        else:
            new_data.append(coalition)

    for p in sorted(new_data, key=lambda k: k['energy_impact'], reverse=True)[:10]:
        yield{
            'name': p['name'],
            'energy_impact': p['energy_impact'],
            'cputime_ns': p['cputime_ns']
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
                print(data)
                raise exc

            compressed_data = zlib.compress(str(json.dumps(data)).encode())
            compressed_data_str = base64.b64encode(compressed_data).decode()

            c.execute('INSERT INTO measurements (time, data, uploaded) VALUES (?, ?, 0)',
                    (data['timestamp'], compressed_data_str))

            cpu_energy_data = {}
            if 'ane_energy' in data['processor']:
                cpu_energy_data = {
                    'combined_power': int(data['processor'].get('combined_power', 0) * data['elapsed_ns'] / 1_000_000_000.0),
                    'cpu_energy': int(data['processor'].get('cpu_energy', 0)),
                    'gpu_energy': int(data['processor'].get('gpu_energy', 0)),
                    'ane_energy': int(data['processor'].get('ane_energy', 0)),
                    'energy_impact': data['all_tasks'].get('energy_impact'),
                }
            elif 'package_joules' in data['processor']:
                # Intel processors report in joules/ watts and not mJ
                cpu_energy_data = {
                    'combined_power': int(data['processor'].get('package_joules', 0) * 1_000),
                    'cpu_energy': int(data['processor'].get('cpu_joules', 0) * 1_000),
                    'gpu_energy': int(data['processor'].get('igpu_watts', 0) * data['elapsed_ns'] / 1_000_000_000.0 * 1_000),
                    'ane_energy': 0,
                    'energy_impact': data['all_tasks'].get('energy_impact'),
                }

            c.execute('''INSERT INTO power_measurements
                      (time, combined_energy, cpu_energy, gpu_energy, ane_energy, energy_impact) VALUES
                      (?, ?, ?, ?, ?, ?)''',
                    (data['timestamp'],
                     cpu_energy_data['combined_power'],
                     cpu_energy_data['cpu_energy'],
                     cpu_energy_data['gpu_energy'],
                     cpu_energy_data['ane_energy'],
                     cpu_energy_data['energy_impact']))

            for key in stats:
                stats[key] += cpu_energy_data[key]


            for process in find_top_processes(data['coalitions']):
                cpu_per = int(process['cputime_ns'] / data['elapsed_ns'] * 100)
                c.execute('INSERT INTO top_processes (time, name, energy_impact, cputime_per) VALUES (?, ?, ?, ?)',
                    (data['timestamp'], process['name'], process['energy_impact'], cpu_per))

            conn.commit()

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
            return
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



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=
                                     '''A powermetrics wrapper that does simple parsing and writes to a file.''')
    parser.add_argument('-d', '--debug', action='store_true', help='Enable debug/ development mode')
    parser.add_argument('-w', '--website', action='store_true', help='Shows the website URL')
    parser.add_argument('-f', '--file', type=str, help='Path to the input file')

    args = parser.parse_args()

    if args.debug:
        SETTINGS = {
            'powermetrics' : 1000,
            'upload_delta': 5,
            'api_url': 'http://api.green-coding.internal:9142/v1/hog/add',
            'web_url': 'http://metrics.green-coding.internal:9142/hog-details.html?machine_uuid=',
            'upload_data': True,
        }

    if os.geteuid() != 0:
        print('The script needs to be run as root!')
        sys.exit(1)

    # Make sure that everyone can write to the DB
    os.chmod(DATABASE_FILE, stat.S_IRUSR | stat.S_IWUSR |
                stat.S_IRGRP | stat.S_IWGRP |
                stat.S_IROTH | stat.S_IWOTH)


    # Make sure the DB is migrated
    caribou.upgrade(DATABASE_FILE, MIGRATIONS_PATH)

    save_settings()

    if args.website:
        print('Please visit this url for detailed analytics:')
        print(f"{SETTINGS['web_url']}{machine_uuid}")
        sys.exit()

    run_powermetrics(args.debug, args.file)

    c.close()
