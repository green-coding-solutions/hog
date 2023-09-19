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
            settings STRING,
            uploaded INT)'''
    connection.execute(tbl_measurements)

    tbl_power_measurements = '''CREATE TABLE IF NOT EXISTS power_measurements
                (time INT,
                combined_energy INT,
                cpu_energy INT,
                gpu_energy INT,
                ane_energy INT,
                energy_impact REAL)'''
    connection.execute(tbl_power_measurements)

    tbl_top_processes = '''CREATE TABLE IF NOT EXISTS top_processes
                (time INT, name STRING, energy_impact REAL, cputime_ns INT)'''
    connection.execute(tbl_top_processes)

    tbl_settings = '''CREATE TABLE IF NOT EXISTS settings
                (machine_id TEXT)'''
    connection.execute(tbl_settings)

    connection.commit()


def downgrade(connection):
    connection.execute('DROP TABLE measurements')
    connection.execute('DROP TABLE power_measurements')
    connection.execute('DROP TABLE top_processes')
    connection.execute('DROP TABLE settings')
