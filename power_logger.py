#!/usr/bin/env python3

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
import stat
import urllib.request
import configparser
import os.path
import sqlite3
import http

import libs.caribou as caribou

from datetime import timezone
from pathlib import Path

# Shared variable to signal the thread to stop
stop_signal = False

stats = {
    'combined_power':0
}

def sigint_handler(_, __):
    global stop_signal
    if stop_signal:
        # If you press CTR-C the second time we bail
        sys.exit()

    stop_signal = True
    print("Received stop signal. Terminating all processes.")

def siginfo_handler(_, __):
    print(stats)

signal.signal(signal.SIGINT, sigint_handler)
signal.signal(signal.SIGTERM, sigint_handler)

signal.signal(signal.SIGINFO, siginfo_handler)


APP_NAME = "berlin.green-coding.hog"
app_support_path = Path(f"/Library/Application Support/{APP_NAME}")
app_support_path.mkdir(parents=True, exist_ok=True)

DATABASE_FILE = app_support_path / 'db.db'

MIGRATIONS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations")

config = configparser.ConfigParser()
config.read('settings.ini')

default_settings = {
    'powermetrics': 5000,
    'upload_delta': 300,
    'api_url': 'https://api.green-coding.berlin/v1/hog/add',
    'upload_data': True,
}


SETTINGS = {
    'powermetrics': config['DEFAULT'].get('powermetrics', default_settings['powermetrics']),
    'upload_delta': config['DEFAULT'].get('upload_delta', default_settings['upload_delta']),
    'api_url': config['DEFAULT'].get('api_url', default_settings['api_url']),
    'upload_data': config['DEFAULT'].getboolean('upload_data', default_settings['upload_data']),
}

machine_id = None

conn = sqlite3.connect(DATABASE_FILE)
c = conn.cursor()


def run_powermetrics(debug: bool):

    # We ignore stderr here as powermetrics is quite verbose on stderr and the buffer fills up quite fast
    cmd = ['powermetrics',
           '--show-all',
           '-i', str(SETTINGS['powermetrics']),
           '-f', 'plist']

    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)

    buffer = []
    last_upload_time = time.time()

    for line in process.stdout:
        line = line.strip().replace("&", "&amp;")

        buffer.append(line)
        if line == '</plist>':
            # We only add the data to the queue once it is complete to avoid race conditions
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
            process.terminate()
            break


def upload_data_to_endpoint():
    while True:

        # We need to limit the amount of data here as otherwise the payload becomes to big
        c.execute("SELECT id, time, data, settings FROM measurements WHERE uploaded = 0 LIMIT 10;")
        rows = c.fetchall()

        if not rows:
            break

        payload = []
        for row in rows:
            row_id, time_val, data_val, settings_val = row

            settings_upload = json.loads(settings_val)
            del settings_upload['api_url'] # We don't need this in the DB on the server

            payload.append({
                'time': time_val,
                'data': data_val,
                'settings': json.dumps(settings_upload),
                'machine_id': machine_id,
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
                        c.execute("UPDATE measurements SET uploaded = ?, data = NULL WHERE id = ?;", (int(time.time()), p['row_id']))
                    conn.commit()
                else:
                    print(f"Failed to upload data: {payload}\n HTTP status: {response.status}")
        except urllib.error.HTTPError as e:
            print(f"HTTP error occurred while uploading: {payload}\n {e.reason}")
        except ConnectionRefusedError:
            pass
        except urllib.error.URLError:
            pass
        except http.client.RemoteDisconnected:
            pass
        except ConnectionResetError:
            pass



###### END IMPORT BLOCK #######


def find_top_processes(data: list):
    # As iterm2 will probably show up as it spawns the processes called from the shell we look at the tasks
    new_data = []
    for coalition in data:
        if coalition['name'] == 'com.googlecode.iterm2' or coalition['name'].strip() == '':
            new_data.extend(coalition["tasks"])
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
            except xml.parsers.expat.ExpatError:
                print(data)
                raise xml.parsers.expat.ExpatError

            compressed_data = zlib.compress(str(json.dumps(data)).encode())
            compressed_data_str = base64.b64encode(compressed_data).decode()

            c.execute("INSERT INTO measurements (time, data, settings, uploaded) VALUES (?, ?, ?, 0)",
                    (data['timestamp'], compressed_data_str, json.dumps(SETTINGS)))

            c.execute("""INSERT INTO power_measurements
                      (time, combined_energy, cpu_energy, gpu_energy, ane_energy, energy_impact) VALUES
                      (?, ?, ?, ?, ?, ?)""",
                    (data['timestamp'],
                     int(data['processor'].get('combined_power', 0) * data['elapsed_ns'] / 1_000_000_000.0),
                     int(data['processor'].get('cpu_energy', 0)),
                     int(data['processor'].get('gpu_energy', 0)),
                     int(data['processor'].get('ane_energy', 0)),
                     data['all_tasks'].get('energy_impact'),
                     ))

            stats['combined_power'] += data['processor'].get('combined_power', 0) * data['elapsed_ns'] / 1_000_000_000.0

            for process in find_top_processes(data['coalitions']):
                c.execute("INSERT INTO top_processes (time, name, energy_impact, cputime_ns) VALUES (?, ?, ?, ?)",
                    (data['timestamp'], process['name'], process['energy_impact'], process['cputime_ns']))

            conn.commit()



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=
                                     """A powermetrics wrapper that does simple parsing and writes to a file.""")
    parser.add_argument('-d', '--debug', action='store_true', help='Enable debug mode')
    args = parser.parse_args()

    if args.debug:
        SETTINGS = {
            'powermetrics' : 1000,
            'upload_delta': 5,
            'api_url': "http://api.green-coding.internal:9142/v1/hog/add",
            'upload_data': True,
        }

    if os.geteuid() != 0:
        print("The script needs to be run as root!")
        sys.exit()

    # Make sure that everyone can write to the DB
    os.chmod(DATABASE_FILE, stat.S_IRUSR | stat.S_IWUSR |
                stat.S_IRGRP | stat.S_IWGRP |
                stat.S_IROTH | stat.S_IWOTH)


    # Make sure the DB is migrated
    caribou.upgrade(DATABASE_FILE, MIGRATIONS_PATH)

    c.execute("SELECT machine_id FROM settings LIMIT 1")
    result = c.fetchone()

    if result:
        machine_id = result[0]
    else:
        machine_id = str(uuid.uuid1())
        c.execute("INSERT INTO settings (machine_id) VALUES (?)", (machine_id,))
        conn.commit()

    run_powermetrics(args.debug)

    c.close()


