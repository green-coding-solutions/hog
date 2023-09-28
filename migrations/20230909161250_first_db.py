"""
This migration adds all the fields you need

Migration Name: add_upload_fields
Migration Version: 20230909161253
"""

def upgrade(connection):
    tbl_measurements = '''CREATE TABLE IF NOT EXISTS measurements
            (id INTEGER PRIMARY KEY,
            time INT,
            data STRING,
            uploaded INT)'''
    connection.execute(tbl_measurements)

    tbl_power_measurements = '''CREATE TABLE IF NOT EXISTS power_measurements
                (time INT,
                combined_energy INT,
                cpu_energy INT,
                gpu_energy INT,
                ane_energy INT,
                energy_impact INT)'''
    connection.execute(tbl_power_measurements)

    tbl_top_processes = '''CREATE TABLE IF NOT EXISTS top_processes
                (time INT, name STRING, energy_impact INT, cputime_per INT)'''
    connection.execute(tbl_top_processes)

    tbl_settings = '''CREATE TABLE IF NOT EXISTS settings
                (time INT,
                machine_uuid TEXT,
                powermetrics INT,
                api_url STRING,
                web_url STRING,
                upload_delta INT,
                upload_data NUMERIC)'''
    connection.execute(tbl_settings)

    connection.commit()


def downgrade(connection):
    connection.execute('DROP TABLE measurements')
    connection.execute('DROP TABLE power_measurements')
    connection.execute('DROP TABLE top_processes')
    connection.execute('DROP TABLE settings')
