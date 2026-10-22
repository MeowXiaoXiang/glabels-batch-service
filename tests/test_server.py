import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def test_launcher_exits_after_store_fault_and_preserves_terminal_jobs(tmp_path):
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "demo.glabels").write_text("opaque fixture")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    root = Path(__file__).resolve().parents[1]
    env = os.environ | {"PYTHONPATH": str(root)}

    def request(path, data=None):
        message = Request(
            f"http://127.0.0.1:{port}{path}",
            data=None if data is None else json.dumps(data).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(message, timeout=5) as response:  # nosec B310
            return json.load(response)

    with (tmp_path / "server.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                str(root / "tests/fixtures/failing_server.py"),
                str(tmp_path),
                str(port),
            ],
            cwd=root,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 20
            while True:
                try:
                    assert request("/ready")["ready"]
                    break
                except URLError, TimeoutError:
                    assert process.poll() is None
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Fault-test server did not start")
                    time.sleep(0.05)
            payload = {"template_name": "demo.glabels", "data": [{"ITEM": "A"}]}
            identifiers = [
                request("/labels/print", payload)["job_id"] for _ in range(3)
            ]
            assert request("/test/write-fault", {}) == {"armed": True}
            try:
                request("/labels/print", payload)
            except HTTPError as exc:
                assert exc.code == 500
                exc.close()
            else:
                raise AssertionError("Store failure was not injected")
            assert process.wait(timeout=20) == 1
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
    # The service has exited; inspect only its now-closed local database.
    with closing(sqlite3.connect(tmp_path / "state/jobs.sqlite3")) as connection:
        rows = dict(
            connection.execute(
                "SELECT job_id,error_code FROM jobs WHERE status='failed'"
            )
        )
        assert rows[identifiers[0]] == "shutdown_cancelled"
        assert all(
            rows[identifier] == "execution_unavailable"
            for identifier in identifiers[1:]
        )
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
