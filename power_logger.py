#!/usr/bin/env python3

import json
import subprocess
import time
import threading
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


from datetime import timezone
from queue import Queue
from pathlib import Path

import sqlite3

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

SETTINGS = {
    'powermetrics' : 5000,
}

conn = sqlite3.connect(DATABASE_FILE)
c = conn.cursor()

c.execute('''CREATE TABLE IF NOT EXISTS measurements
             (time INT, data STRING, settings STRING)''')

c.execute('''CREATE TABLE IF NOT EXISTS power_measurements
             (time INT, combined_energy REAL, cpu_energy REAL, gpu_energy REAL, ane_energy REAL)''')

c.execute('''CREATE TABLE IF NOT EXISTS top_processes
             (time INT, name STRING, energy_impact REAL, cputime_ns INT)''')

c.execute('''CREATE TABLE IF NOT EXISTS settings
             (machine_id TEXT)''')


conn.commit()


def run_powermetrics(debug: bool):

    # We ignore stderr here as powermetrics is quite verbose on stderr and the buffer fills up quite fast
    cmd = ['powermetrics',
           '--show-all',
           '-i', str(SETTINGS['powermetrics']),
           '-f', 'plist']

    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)

    buffer = []
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

        if stop_signal:
            process.terminate()  # or process.kill()
            break

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
            except xml.parsers.expat.ExpatError:
                print(data)
                raise xml.parsers.expat.ExpatError

            compressed_data = zlib.compress(str(data).encode())
            compressed_data_str = base64.b64encode(compressed_data).decode()

            epoch_time = int(data['timestamp'].replace(tzinfo=timezone.utc).timestamp() * 1e3)

            c.execute("INSERT INTO measurements (time, data, settings) VALUES (?, ?, ?)",
                    (epoch_time, compressed_data_str, json.dumps(SETTINGS)))

            c.execute("INSERT INTO power_measurements (time, combined_energy, cpu_energy, gpu_energy, ane_energy) VALUES (?, ?, ?, ?, ?)",
                    (epoch_time,
                     data['processor'].get('combined_power', 0) * data['elapsed_ns'] / 1_000_000_000.0,
                     data['processor'].get('cpu_energy', 0),
                     data['processor'].get('gpu_energy', 0),
                     data['processor'].get('ane_energy', 0),
                     ))

            stats['combined_power'] += data['processor'].get('combined_power', 0) * data['elapsed_ns'] / 1_000_000_000.0

            for process in find_top_processes(data['coalitions']):
                c.execute("INSERT INTO top_processes (time, name, energy_impact, cputime_ns) VALUES (?, ?, ?, ?)",
                    (epoch_time, process['name'], process['energy_impact'], process['cputime_ns']))

            conn.commit()



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=
                                     """A powermetrics wrapper that does simple parsing and writes to a file.""")
    parser.add_argument('-d', '--debug', action='store_true', help='Enable debug mode')
    args = parser.parse_args()

    if args.debug:
        SETTINGS = { 'powermetrics' : 1000 }

    if os.geteuid() != 0:
        print("The script needs to be run as root!")
        sys.exit()

    # Make sure that everyone can write to the DB
    os.chmod(DATABASE_FILE, stat.S_IRUSR | stat.S_IWUSR |
                stat.S_IRGRP | stat.S_IWGRP |
                stat.S_IROTH | stat.S_IWOTH)


    c.execute("SELECT machine_id FROM settings LIMIT 1")
    result = c.fetchone()

    if not result:
        c.execute("INSERT INTO settings (machine_id) VALUES (?)", (str(uuid.uuid1()),))
        conn.commit()

    run_powermetrics(args.debug)

    c.close()
