"""Verify Linux/MySQL and the actual TLS service; leave production data intact."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import gzip
from importlib.metadata import version
import json
import os
from pathlib import Path
import secrets
import ssl
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

from sqlalchemy import URL


ROOT = Path(__file__).resolve().parents[2]
BASE = Path('/home/gongyi/apps/mobile-cloud-backend')
OUTPUT = BASE / 'shared/server-verification.json'


def sql(query):
    result = subprocess.run(['sudo', '-n', 'mysql', '--protocol=socket', '--batch', '--skip-column-names'],
                            input=query, text=True, capture_output=True, check=True)
    return result.stdout.strip()


def save(data):
    OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def tests(data):
    username = 'cloud_verify_' + uuid4().hex[:8]
    password = secrets.token_hex(24)
    account = f"'{username}'@'127.0.0.1'"
    sql(f"CREATE USER {account} IDENTIFIED BY '{password}';\n"
        f"GRANT ALL PRIVILEGES ON `test\\_recognition\\_%`.* TO {account};")
    report = BASE / 'shared/pytest-server.xml'
    env = dict(os.environ)
    env['TEST_MYSQL_ADMIN_URL'] = URL.create('mysql+pymysql', username=username, password=password,
                                            host='127.0.0.1', query={'charset': 'utf8mb4'}).render_as_string(hide_password=False)
    try:
        result = subprocess.run([sys.executable, '-m', 'pytest', '-q', '--junitxml=' + str(report)],
                                cwd=ROOT / 'backend', env=env, text=True, capture_output=True)
        print((result.stdout + result.stderr).replace(password, '[REDACTED]'), flush=True)
        result.check_returncode()
    finally:
        sql(f'DROP USER {account};')
    cases = list(ET.parse(report).getroot().iter('testcase'))
    skipped = sum(case.find('skipped') is not None for case in cases)
    data['tests'] = {'tests': len(cases), 'passed': len(cases) - skipped, 'skipped': skipped,
                     'failures': 0, 'errors': 0, 'mysql_cases_executed': True}
    name = 'test_recognition_' + uuid4().hex
    try:
        sql(f'CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;\n'
            f'USE `{name}`;\n' + (ROOT / 'database/schema/001_initial.sql').read_text())
        tables = sql(f'SHOW TABLES FROM `{name}`;').splitlines()
        assert sorted(tables) == ['category', 'inference_record', 'model_version', 'sample']
        data['sql_snapshot_executed'] = True
    finally:
        assert name.startswith('test_recognition_') and len(name) == 49
        sql(f'DROP DATABASE IF EXISTS `{name}`;')


def http(data):
    values = dict(line.split('=', 1) for line in (ROOT / '.env').read_text().splitlines() if line and not line.startswith('#'))
    token = values['API_TOKEN']
    context = ssl.create_default_context(cafile=str(BASE / 'shared/server.crt'))

    def call(path, body=None, bearer=None, method=None):
        headers = {'Content-Type': 'application/json'}
        if bearer is not None:
            headers['Authorization'] = 'Bearer ' + bearer
        request = Request('https://127.0.0.1' + path,
                          data=None if body is None else json.dumps(body).encode(), headers=headers, method=method)
        try:
            response = urlopen(request, context=context, timeout=15)
        except HTTPError as error:
            response = error
        with response:
            content = response.read()
            value = json.loads(content) if content and response.headers.get_content_type() == 'application/json' else None
            return response.status, value

    def wait_ready():
        for attempt in range(30):
            try:
                if call('/api/health')[0] == 200:
                    return
            except Exception:
                pass
            time.sleep(0.5)
        raise RuntimeError('Service did not become healthy after restart.')

    wait_ready()
    status, health = call('/api/health')
    assert status == 200
    if values.get('INFERENCE_SOCKET'):
        assert health['model_loaded'] is True and health['model_version'] == values['INFERENCE_MODEL_VERSION']
    else:
        assert health['model_loaded'] is False
    data['health'] = health
    missing = call('/api/records', {}, method='POST')[0]
    wrong_case = call('/api/records', {}, bearer=token.upper(), method='POST')[0]
    assert missing == wrong_case == 401
    client = str(uuid4())
    identifiers = [str(uuid4()), str(uuid4())]
    body = {'record_id': identifiers[0], 'client_id': client, 'inference_source': 'device',
            'model_version': 'expanded-cpu-v1', 'predicted_id': 0, 'confidence': 0.874, 'latency_ms': 123,
            'captured_at': datetime.now(ZoneInfo('UTC')).isoformat(timespec='milliseconds')}
    try:
        first = call('/api/records', body, token)
        repeat = call('/api/records', body, token)
        conflict = call('/api/records', dict(body, confidence=0.5), token)
        assert (first[0], repeat[0], conflict[0]) == (201, 200, 409)
        assert first[1]['created'] is True and repeat[1]['created'] is False
        concurrent_body = dict(body, record_id=identifiers[1])
        with ThreadPoolExecutor(max_workers=4) as executor:
            responses = list(executor.map(lambda _: call('/api/records', concurrent_body, token)[0], range(4)))
        assert sorted(responses) == [200, 200, 200, 201]
        old_pid = subprocess.check_output(['systemctl', 'show', 'mobile-cloud-backend', '-p', 'MainPID', '--value'], text=True).strip()
        subprocess.run(['sudo', '-n', 'systemctl', 'restart', 'mobile-cloud-backend'], check=True)
        wait_ready()
        new_pid = subprocess.check_output(['systemctl', 'show', 'mobile-cloud-backend', '-p', 'MainPID', '--value'], text=True).strip()
        assert new_pid != old_pid and int(new_pid) > 0
        restarted = call('/api/records', body, token)
        assert restarted[0] == 200
        counts = sql("SELECT record_id,COUNT(*) FROM object_recognition.inference_record "
                     f"WHERE client_id='{client}' GROUP BY record_id;")
        assert len(counts.splitlines()) == 2 and all(line.endswith('\t1') for line in counts.splitlines())
        backup = subprocess.run(['sudo', '-n', 'python3', '-B', '/usr/local/lib/mobile-cloud-backend/backup_database.py'],
                                text=True, capture_output=True, check=True)
        information = json.loads(backup.stdout)
        dumped = subprocess.run(['sudo', '-n', 'cat', information['backup']], capture_output=True, check=True).stdout
        restore_name = 'test_recognition_' + uuid4().hex
        try:
            sql(f'CREATE DATABASE `{restore_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;\n'
                f'USE `{restore_name}`;\n' + gzip.decompress(dumped).decode('utf-8'))
            restored = sql(f"SELECT COUNT(*) FROM `{restore_name}`.inference_record WHERE client_id='{client}';")
            assert restored == '2'
            assert sql(f'SELECT COUNT(*) FROM `{restore_name}`.category;') == '10'
        finally:
            assert restore_name.startswith('test_recognition_') and len(restore_name) == 49
            sql(f'DROP DATABASE IF EXISTS `{restore_name}`;')
        data['https'] = {'certificate_validated': True, 'missing_token': missing,
                         'case_changed_token': wrong_case, 'health': status}
        data['http'] = {'first_upload': first[0], 'same_content_retry': repeat[0], 'different_content': conflict[0],
                        'concurrent_first_uploads': sorted(responses), 'retry_after_service_restart': restarted[0],
                        'persisted_rows_for_each_uuid': 1, 'service_pid_changed': True}
        data['backup_restore'] = {'verified': True, 'restored_test_records': 2, 'restored_categories': 10,
                                  'backup_sha256': information['sha256'], 'restored_to_isolated_database': True}
    finally:
        sql("DELETE FROM object_recognition.inference_record "
            f"WHERE client_id='{client}' AND record_id IN ('{identifiers[0]}','{identifiers[1]}');")
        assert sql(f"SELECT COUNT(*) FROM object_recognition.inference_record WHERE client_id='{client}';") == '0'
    data['production_test_rows_removed'] = True
    subprocess.run(['sudo', '-n', 'systemctl', 'start', 'mobile-cloud-backend-backup.service'], check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['tests', 'http'])
    args = parser.parse_args()
    if ROOT.parent != BASE / 'releases':
        raise RuntimeError('Run only from the managed release using its virtual environment.')
    data = json.loads(OUTPUT.read_text()) if OUTPUT.exists() else {}
    data.update({'checked_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds'),
                 'timezone': 'Asia/Shanghai', 'source_commit': (ROOT / 'SOURCE_REVISION').read_text().strip(),
                 'release': str(ROOT), 'python': sys.version.split()[0],
                 'mysql': sql('SELECT VERSION();'),
                 'dependencies': {package: version(package) for package in ['Flask','Flask-SQLAlchemy','SQLAlchemy','PyMySQL','gunicorn']}})
    globals()[args.phase](data)
    save(data)
    print(json.dumps(data, ensure_ascii=True), flush=True)


if __name__ == '__main__':
    main()
