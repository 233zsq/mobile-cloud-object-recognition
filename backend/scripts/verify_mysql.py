"""Run tests and HTTP checks on an isolated local MySQL instance.

Uses an existing mysqld binary, never its default configuration/data directory.
All generated databases and files are owned by this verification run.
"""

import argparse
from datetime import datetime, timedelta, timezone
from importlib.metadata import version
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4
import xml.etree.ElementTree as ET

import pymysql


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def available_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def command(args, **kwargs):
    result = subprocess.run(args, cwd=BACKEND, creationflags=FLAGS, capture_output=True, text=True, encoding="utf-8", errors="replace", **kwargs)
    print(result.stdout, end="", flush=True)
    if result.returncode:
        print(result.stderr, end="", flush=True)
    result.check_returncode()
    return result


def stop(process):
    if process is not None:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def request_json(address, body=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = Request(address, data=data, headers={"Content-Type": "application/json"})
    try:
        response = urlopen(req, timeout=3)
    except HTTPError as error:
        response = error
    with response:
        payload = json.load(response)
        assert response.headers["X-Request-ID"]
        if "error" in payload:
            assert payload["request_id"] == response.headers["X-Request-ID"]
        return response.status, payload


def start_http(env, log):
    process = subprocess.Popen(
        [sys.executable, "-m", "app"], cwd=BACKEND, env=env,
        stdout=log, stderr=subprocess.STDOUT, creationflags=FLAGS,
    )
    address = "http://127.0.0.1:" + env["SERVER_PORT"]
    deadline = time.monotonic() + 30
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Flask exited during startup")
            try:
                assert request_json(address + "/api/health")[0] == 200
                return process, address
            except (URLError, TimeoutError):
                time.sleep(0.2)
        raise RuntimeError("Flask startup timed out")
    except Exception:
        stop(process)
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mysqld", type=Path, required=True)
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    binary = args.mysqld.resolve(strict=True)
    runtime_root = (ROOT / "tmp").resolve()
    runtime_root.mkdir(exist_ok=True)
    runtime = Path(tempfile.mkdtemp(prefix="mysql-records-", dir=runtime_root)).resolve()
    if not runtime.is_relative_to(runtime_root):
        raise RuntimeError("Verification directory escaped the workspace")
    mysql = http = None
    port = None
    try:
        data = runtime / "data"
        data.mkdir()
        base = [str(binary), "--no-defaults", f"--basedir={binary.parent.parent}", f"--datadir={data}"]
        print("Initializing a private MySQL data directory...", flush=True)
        command(base + ["--initialize-insecure", f"--log-error={runtime / 'initialize.log'}"], timeout=90)
        port = available_port()
        with (runtime / "mysql-console.log").open("w", encoding="utf-8") as mysql_log, (runtime / "http.log").open("w", encoding="utf-8") as http_log:
            mysql = subprocess.Popen(
                base + (["--no-monitor"] if sys.platform == "win32" else []) + [f"--port={port}", "--bind-address=127.0.0.1", "--mysqlx=OFF", "--skip-log-bin", f"--pid-file={runtime / 'mysqld.pid'}", f"--log-error={runtime / 'server.log'}"],
                cwd=runtime, stdout=mysql_log, stderr=subprocess.STDOUT, creationflags=FLAGS,
            )
            deadline = time.monotonic() + 45
            while True:
                if mysql.poll() is not None:
                    raise RuntimeError("Private MySQL exited during startup")
                try:
                    admin = pymysql.connect(host="127.0.0.1", port=port, user="root", password="", charset="utf8mb4", autocommit=True, connect_timeout=1)
                    break
                except pymysql.MySQLError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.2)
            with admin:
                with admin.cursor() as cursor:
                    cursor.execute("SELECT VERSION()")
                    mysql_version = cursor.fetchone()[0]
                print(f"Running tests against MySQL {mysql_version}...", flush=True)
                env = dict(os.environ, PYTHONIOENCODING="utf-8", TEST_MYSQL_ADMIN_URL=f"mysql+pymysql://root@127.0.0.1:{port}/?charset=utf8mb4")
                junit = runtime / "tests.xml"
                command([sys.executable, "-m", "pytest", "-q", f"--junitxml={junit}"], env=env, timeout=180)
                suite = ET.parse(junit).getroot().find("testsuite")
                test_result = {key: int(suite.attrib[key]) for key in ("tests", "failures", "errors", "skipped")}
                test_result["passed"] = test_result["tests"] - test_result["failures"] - test_result["errors"] - test_result["skipped"]
                name = "test_recognition_smoke_" + uuid4().hex
                with admin.cursor() as cursor:
                    cursor.execute(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin")
                    cursor.execute(f"USE `{name}`")
                    sql = (ROOT / "database/schema/001_initial.sql").read_text(encoding="utf-8")
                    sql = "\n".join(line for line in sql.splitlines() if not line.startswith("--"))
                    for statement in sql.split(";"):
                        if statement.strip():
                            cursor.execute(statement)
                env.update(DB_HOST="127.0.0.1", DB_PORT=str(port), DB_NAME=name, DB_USER="root", DB_PASSWORD="", SERVER_HOST="127.0.0.1", SERVER_PORT=str(available_port()), APP_DEBUG="false")
                for arguments in (["db-init"], ["db-seed"], ["register-model", "--metadata", str(ROOT / "database/seeds/expanded-cpu-v1.metadata.json")]):
                    command([sys.executable, "-m", "flask", "--app", "app:create_app", *arguments], env=env, timeout=30)
                http, address = start_http(env, http_log)
                upload = dict(record_id=str(uuid4()), client_id=str(uuid4()), inference_source="device", model_version="expanded-cpu-v1", predicted_id=0, confidence=0.874, latency_ms=123, captured_at="2026-10-08T16:30:00.123+08:00")
                statuses = []
                for payload in (upload, upload, {**upload, "predicted_id": 1}):
                    statuses.append(request_json(address + "/api/records", payload)[0])
                assert statuses == [201, 200, 409], statuses
                stop(http)
                http = None
                http, address = start_http(env, http_log)
                restart_status, persisted = request_json(address + "/api/records", upload)
                assert restart_status == 200 and persisted["created"] is False
                with admin.cursor() as cursor:
                    cursor.execute("SELECT COUNT(*) FROM inference_record")
                    assert cursor.fetchone()[0] == 1
                    cursor.execute("SHOW TABLES")
                    tables = sorted(row[0] for row in cursor.fetchall())
                evidence = {
                    "date": datetime.now(timezone(timedelta(hours=8))).date().isoformat(),
                    "timezone": "Asia/Shanghai", "mysql": mysql_version,
                    "python": sys.version.split()[0],
                    "dependencies": {name: version(name) for name in ("Flask", "Flask-SQLAlchemy", "SQLAlchemy", "PyMySQL")},
                    "environment": "Isolated local MySQL data directory; no existing databases or Windows services modified",
                    "tests": test_result, "tables": tables,
                    "sql_snapshot_executed": True, "cli_initialization_and_seeding": True,
                    "http": {"first_upload": 201, "same_content_retry": 200, "different_content": 409, "retry_after_app_restart": 200, "persisted_rows": 1},
                    "mysql_concurrent_requests": "4 simultaneous first uploads: one creation, same-content retries succeed; different-content uploads conflict",
                    "model_registration": "metadata only; inference model remains unloaded",
                    "database_failure": "503 response; health endpoint stays available",
                    "services_stopped_and_temporary_directory_removed": True,
                }
                stop(http)
                http = None
                # Shutdown only the server started by this verification process.
                with admin.cursor() as cursor:
                    cursor.execute("SHUTDOWN")
                mysql.wait(timeout=20)
    except Exception:
        for filename in ("initialize.log", "server.log", "mysql-console.log", "http.log"):
            path = runtime / filename
            if path.exists():
                print(path.read_text(encoding="utf-8", errors="replace")[-4000:], flush=True)
        raise
    finally:
        stop(http)
        if port is not None:
            try:
                with pymysql.connect(host="127.0.0.1", port=port, user="root", password="", autocommit=True, connect_timeout=1) as cleanup:
                    with cleanup.cursor() as cursor:
                        cursor.execute("SELECT @@datadir")
                        if Path(cursor.fetchone()[0]).resolve() != (runtime / "data").resolve():
                            raise RuntimeError("Refusing shutdown of an unrelated MySQL server")
                        cursor.execute("SHUTDOWN")
                mysql.wait(timeout=20)
            except pymysql.MySQLError:
                pass
        stop(mysql)
        # Check the resolved target again immediately before recursive cleanup.
        if runtime.resolve().is_relative_to(runtime_root) and runtime != runtime_root:
            shutil.rmtree(runtime)
        else:
            raise RuntimeError("Refusing cleanup outside the verification directory")
    if args.evidence:
        args.evidence.resolve().write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
