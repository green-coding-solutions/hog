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
import copy
import contextlib
import datetime
import glob
import os.path
import sqlite3
import traceback
import importlib.util
import http

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

# So this is a little weird that we have this block, but it is down to having everything in one file
# and not having any dependencies. As this will make things a lot more complicated when doing the single line
# install. And I would have to add release zips etc ..  This will come in the future but for version one this
# is the only dependency we need/ want so KISS!

"""
Code is copied from https://raw.githubusercontent.com/clutchski/caribou/master/caribou.py

Caribou is a simple SQLite database migrations library, built
to manage the evoluton of client side databases over multiple releases
of an application.
"""

VERSION_TABLE = 'migration_version'
UTC_LENGTH = 14

# errors

class Error(Exception):
    """ Base class for all Caribou errors. """
    pass

class InvalidMigrationError(Error):
    """ Thrown when a client migration contains an error. """
    pass

class InvalidNameError(Error):
    """ Thrown when a client migration has an invalid filename. """

    def __init__(self, filename):
        msg = 'Migration filenames must start with a UTC timestamp. ' \
            'The following file has an invalid name: %s' % filename
        super(InvalidNameError, self).__init__(msg)

# code

@contextlib.contextmanager
def execute(conn, sql, params=None):
    params = [] if params is None else params
    cursor = conn.execute(sql, params)
    try:
        yield cursor
    finally:
        cursor.close()

@contextlib.contextmanager
def transaction(conn):
    try:
        yield
        conn.commit()
    except:
        conn.rollback()
        msg = "Error in transaction: %s" % traceback.format_exc()
        raise Error(msg)

def has_method(an_object, method_name):
    return hasattr(an_object, method_name) and \
                    callable(getattr(an_object, method_name))

def is_directory(path):
    return os.path.exists(path) and os.path.isdir(path)

class Migration(object):
    """ This class represents a migration version. """

    def __init__(self, path):
        self.path = path
        self.filename = os.path.basename(path)
        self.module_name, _ = os.path.splitext(self.filename)
        self.get_version() # will assert the filename is valid
        self.name = self.module_name[UTC_LENGTH:]
        while self.name.startswith('_'):
            self.name = self.name[1:]
        try:
            spec = importlib.util.spec_from_file_location(self.module_name, path)
            self.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.module)
        except:
            msg = "Invalid migration %s: %s" % (path, traceback.format_exc())
            raise InvalidMigrationError(msg)
        # assert the migration has the needed methods
        missing = [m for m in ['upgrade', 'downgrade']
                    if not has_method(self.module, m)]
        if missing:
            msg = 'Migration %s is missing required methods: %s.' % (
                    self.path, ', '.join(missing))
            raise InvalidMigrationError(msg)

    def get_version(self):
        if len(self.filename) < UTC_LENGTH:
            raise InvalidNameError(self.filename)
        timestamp = self.filename[:UTC_LENGTH]
        #FIXME: is this test sufficient?
        if not timestamp.isdigit():
            raise InvalidNameError(self.filename)
        return timestamp

    def upgrade(self, conn):
        self.module.upgrade(conn)

    def downgrade(self, conn):
        self.module.downgrade(conn)

    def __repr__(self):
        return 'Migration(%s)' % self.filename

class Database(object):

    def __init__(self, db_url):
        self.db_url = db_url
        self.conn = sqlite3.connect(db_url)

    def close(self):
        self.conn.close()

    def is_version_controlled(self):
        sql = """select *
                from sqlite_master
                where type = 'table'
                    and name = :1"""
        with execute(self.conn, sql, [VERSION_TABLE]) as cursor:
            return bool(cursor.fetchall())

    def upgrade(self, migrations, target_version=None):
        if target_version:
            _assert_migration_exists(migrations, target_version)

        migrations.sort(key=lambda x: x.get_version())
        database_version = self.get_version()

        for migration in migrations:
            current_version = migration.get_version()
            if current_version <= database_version:
                continue
            if target_version and current_version > target_version:
                break
            migration.upgrade(self.conn)
            new_version = migration.get_version()
            self.update_version(new_version)

    def downgrade(self, migrations, target_version):
        if target_version not in (0, '0'):
            _assert_migration_exists(migrations, target_version)

        migrations.sort(key=lambda x: x.get_version(), reverse=True)
        database_version = self.get_version()

        for i, migration in enumerate(migrations):
            current_version = migration.get_version()
            if current_version > database_version:
                continue
            if current_version <= target_version:
                break
            migration.downgrade(self.conn)
            next_version = 0
            # if an earlier migration exists, set the db version to
            # its version number
            if i < len(migrations) - 1:
                next_migration = migrations[i + 1]
                next_version = next_migration.get_version()
            self.update_version(next_version)

    def get_version(self):
        """ Return the database's version, or None if it is not under version
            control.
        """
        if not self.is_version_controlled():
            return None
        sql = 'select version from %s' % VERSION_TABLE
        with execute(self.conn, sql) as cursor:
            result = cursor.fetchall()
            return result[0][0] if result else 0

    def update_version(self, version):
        sql = 'update %s set version = :1' % VERSION_TABLE
        with transaction(self.conn):
            self.conn.execute(sql, [version])

    def initialize_version_control(self):
        sql = """ create table if not exists %s
                ( version text ) """ % VERSION_TABLE
        with transaction(self.conn):
            self.conn.execute(sql)
            self.conn.execute('insert into %s values (0)' % VERSION_TABLE)

    def __repr__(self):
        return 'Database("%s")' % self.db_url

def _assert_migration_exists(migrations, version):
    if version not in (m.get_version() for m in migrations):
        raise Error('No migration with version %s exists.' % version)

def load_migrations(directory):
    """ Return the migrations contained in the given directory. """
    if not is_directory(directory):
        msg = "%s is not a directory." % directory
        raise Error(msg)
    wildcard = os.path.join(directory, '*.py')
    migration_files = glob.glob(wildcard)
    return [Migration(f) for f in migration_files]

def upgrade(db_url, migration_dir, version=None):
    """ Upgrade the given database with the migrations contained in the
        migrations directory. If a version is not specified, upgrade
        to the most recent version.
    """
    with contextlib.closing(Database(db_url)) as db:
        db = Database(db_url)
        if not db.is_version_controlled():
            db.initialize_version_control()
        migrations = load_migrations(migration_dir)
        db.upgrade(migrations, version)

def downgrade(db_url, migration_dir, version):
    """ Downgrade the database to the given version with the migrations
        contained in the given migration directory.
    """
    with contextlib.closing(Database(db_url)) as db:
        if not db.is_version_controlled():
            msg = "The database %s is not version controlled." % (db_url)
            raise Error(msg)
        migrations = load_migrations(migration_dir)
        db.downgrade(migrations, version)

def get_version(db_url):
    """ Return the migration version of the given database. """
    with contextlib.closing(Database(db_url)) as db:
        return db.get_version()

def create_migration(name, directory=None):
    """ Create a migration with the given name. If no directory is specified,
        the current working directory will be used.
    """
    directory = directory if directory else '.'
    if not is_directory(directory):
        msg = '%s is not a directory.' % directory
        raise Error(msg)

    now = datetime.datetime.now()
    version = now.strftime("%Y%m%d%H%M%S")

    contents = MIGRATION_TEMPLATE % {'name':name, 'version':version}

    name = name.replace(' ', '_')
    filename = "%s_%s.py" % (version, name)
    path = os.path.join(directory, filename)
    with open(path, 'w') as migration_file:
        migration_file.write(contents)
    return path

MIGRATION_TEMPLATE = """\
\"\"\"
This module contains a Caribou migration.

Migration Name: %(name)s
Migration Version: %(version)s
\"\"\"

def upgrade(connection):
    # add your upgrade step here
    pass

def downgrade(connection):
    # add your downgrade step here
    pass
"""

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
    upgrade(DATABASE_FILE, MIGRATIONS_PATH)

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


