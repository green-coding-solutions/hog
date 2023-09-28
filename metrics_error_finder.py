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



SETTINGS = {
    'powermetrics': 5000,
}


def run_powermetrics():

    cmd = ['powermetrics',
            '--show-all',
            '-i', str(SETTINGS['powermetrics']),
            '-f', 'plist']

    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True) as process:
        buffer = []
        for line in process.stdout:
            line = line.strip().replace('&', '&amp;')
            buffer.append(line)
            if line == '</plist>':
                parse_powermetrics_output(''.join(buffer))
                buffer = []

            if stop_signal:
                break

        if stop_signal:
            process.terminate()

def find_top_processes(data: list):
    # As iterm2 will probably show up as it spawns the processes called from the shell we look at the tasks
    new_data = []
    for coalition in data:
        if coalition['name'] == 'com.googlecode.iterm2' or coalition['name'].strip() == '':
            new_data.extend(coalition['tasks'])
        else:
            new_data.append(coalition)

    return new_data

def is_difference_more_than_5_percent(x, y):
    if x == 0 and y == 0:
        return False  # If both values are 0, the percentage difference is undefined.

    if x == 0 or y == 0:
        return True  # If one of the values is 0 and the other is not, they differ by more than 5%.

    percent_difference = abs(x - y) / ((x + y) / 2) * 100

    return percent_difference > 5


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

            for process in find_top_processes(data['coalitions']):

                cpu_ns_dirty = process['cputime_ns']
                cpu_ns_clean = ((process['cputime_ms_per_s'] * 1_000_000)  / 1_000_000_000) * data['elapsed_ns']

                ei_dirty = process['energy_impact']
                ei_clean =  process['energy_impact_per_s'] * data['elapsed_ns'] / 1_000_000_000

                if is_difference_more_than_5_percent(cpu_ns_dirty, cpu_ns_clean) or \
                    is_difference_more_than_5_percent(ei_dirty, ei_clean):

                    print(f"Name       : {process['name']}")
                    print(f"Elapsed ns : {data['elapsed_ns']}")
                    print('')
                    print(f"CPU Time ns       : {process['cputime_ns']}")
                    print(f"CPU Time ns / con : {cpu_ns_clean}")
                    print(f"cputime_ms_per_s  : {process['cputime_ms_per_s']}")
                    print('')
                    print(f"energy_impact       : {process['energy_impact']}")
                    print(f"energy_impact con   : {ei_clean}")
                    print(f"energy_impact_per_s : {process['energy_impact_per_s']}")
                    print('')
                    print(f"diskio_bytesread      : {process['diskio_bytesread']}")
                    print(f"diskio_bytesread_per_s: {process['diskio_bytesread_per_s']}")
                    print('')
                    print(process)
                    print('------------')

if __name__ == '__main__':
    run_powermetrics()
