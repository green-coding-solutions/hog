#!/usr/bin/env python3

import sqlite3
import plistlib
import xml
import time
import base64
import zlib
import json
from datetime import timezone

plistfile = 'powermetrics_test_output.plist'

conn = sqlite3.connect("/tmp/power_hog_test.db")
c = conn.cursor()

buffer = []

cpu_energy_data = {
    'combined_energy': 0,
    'cpu_energy': 0,
    'gpu_energy': 0,
    'ane_energy': 0,
    'energy_impact': 0,
}

cpu_energy_data_first = {
    'combined_energy': 0,
    'cpu_energy': 0,
    'gpu_energy': 0,
    'ane_energy': 0,
    'energy_impact': 0,
}


def parse_powermetrics_output(output):
    for data in output.encode('utf-8').split(b'\x00'):
        if data:
            try:
                data = plistlib.loads(data)
                data['timestamp'] = int(data['timestamp'].replace(tzinfo=timezone.utc).timestamp() * 1e3)

                if cpu_energy_data_first['combined_energy'] == 0:
                    cpu_energy_data_first['combined_energy'] = round(data['processor'].get('combined_power', 0) * data['elapsed_ns'] / 1_000_000_000.0)
                    cpu_energy_data_first['cpu_energy'] = round(data['processor'].get('cpu_energy', 0))
                    cpu_energy_data_first['gpu_energy'] = round(data['processor'].get('gpu_energy', 0))
                    cpu_energy_data_first['ane_energy'] = round(data['processor'].get('ane_energy', 0))
                    cpu_energy_data_first['energy_impact'] = round(data['all_tasks'].get('energy_impact_per_s') * data['elapsed_ns'] / 1_000_000_000)

                cpu_energy_data['combined_energy'] += round(data['processor'].get('combined_power', 0) * data['elapsed_ns'] / 1_000_000_000.0)
                cpu_energy_data['cpu_energy'] += round(data['processor'].get('cpu_energy', 0))
                cpu_energy_data['gpu_energy'] += round(data['processor'].get('gpu_energy', 0))
                cpu_energy_data['ane_energy'] += round(data['processor'].get('ane_energy', 0))
                cpu_energy_data['energy_impact'] += round(data['all_tasks'].get('energy_impact_per_s') * data['elapsed_ns'] / 1_000_000_000)

            except xml.parsers.expat.ExpatError as exc:
                logging.error(f"XML Error:\n{data}")
                raise exc

def process_line(line):
    line = line.strip().replace('&', '&amp;')
    buffer.append(line)

    if line == '</plist>':
        parse_powermetrics_output(''.join(buffer))
        buffer.clear()

print(f"Reading file {plistfile}")
with open(plistfile, 'r', encoding='utf-8') as file:
    for line in file.readlines():
        process_line(line)

print("Checking /tmp/power_hog_test.db")
print("")

q = """
    SELECT
        SUM(combined_energy),
        SUM(cpu_energy),
        SUM(gpu_energy),
        SUM(ane_energy),
        SUM(energy_impact),
        SUM(co2eq)
    FROM
        power_measurements;
    """
c.execute(q)
rows = c.fetchall()

if rows[0][0] == cpu_energy_data['combined_energy'] and \
    rows[0][1] == cpu_energy_data['cpu_energy'] and \
    rows[0][2] == cpu_energy_data['gpu_energy'] and \
    rows[0][3] == cpu_energy_data['ane_energy'] and \
    rows[0][4] == cpu_energy_data['energy_impact'] and \
    rows[0][5] >= 0 and rows[0][5] <= 1:
    print("[PASS] Energy values match!")
else:
    print("[ERROR] Energy values don't match!")
    raise SystemExit()

q = """
    SELECT
        *
    FROM
        measurements
    ORDER BY
        time;
    """
c.execute(q)
rows = c.fetchall()

compressed_data = base64.b64decode(str(rows[0][2]))
decompressed_data = zlib.decompress(compressed_data)
decoded_data = json.loads(decompressed_data.decode())

if decoded_data['grid_intensity_cog'] == 100 and \
    decoded_data['combined_energy_mj'] == cpu_energy_data_first['combined_energy'] and \
    decoded_data['cpu_energy_mj'] == cpu_energy_data_first['cpu_energy'] and \
    decoded_data['gpu_energy_mj'] == cpu_energy_data_first['gpu_energy'] and \
    decoded_data['ane_energy_mj'] == cpu_energy_data_first['ane_energy'] and \
    decoded_data['energy_impact'] == cpu_energy_data_first['energy_impact'] and \
    decoded_data['operational_carbon_g'] >= 0 and decoded_data['operational_carbon_g'] <= 1 and \
    decoded_data['embodied_carbon_g'] >= 0 and decoded_data['embodied_carbon_g'] <= 1:
    print("[PASS] Upload values match!")
else:
    print("[ERROR] Upload values don't match!")
    raise SystemExit()

conn.close()