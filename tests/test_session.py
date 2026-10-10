"""Only synthetic credentials. Exercise real local brokers and child processes."""
import hashlib
import json
import os
import socket
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

import pytest

from secret_request.session import request, start_session


@pytest.fixture
def sessions():
    handles = []
    def create(secret="FAKE-测试\nonly", env="REQUEST_TEST_SECRET", ttl=30):
        ready = start_session(secret, env, ttl)
        handles.append(ready["session"])
        return ready["session"]
    yield create
    for handle in handles:
        request(handle, "revoke")


def run(handle, code, *args, timeout=10, execution_id=None):
    return request(handle, "run", command=[sys.executable, "-c", code, *map(str, args)],
                   timeout=timeout, execution_id=execution_id or uuid.uuid4().hex)


@pytest.mark.parametrize("env", ["REQUEST_TEST_SECRET", None])
def test_failed_script_can_be_fixed_without_resubmission(sessions, tmp_path, capfd, env):
    secret = "FAKE-测试\nonly"
    handle = sessions(secret=secret, env=env)
    expiry = request(handle, "status")["expires_at"]
    script = tmp_path / "task.py"
    script.write_text("raise SystemExit(7)")
    first = request(handle, "run", command=[sys.executable, str(script)], timeout=10, execution_id=uuid.uuid4().hex)
    assert first["exit_code"] == 7
    read = "os.environ['REQUEST_TEST_SECRET'].encode()" if env else "sys.stdin.buffer.read()"
    script.write_text(f"import os,sys,hashlib,pathlib; v={read}; print(v); print(v,file=sys.stderr); pathlib.Path(sys.argv[1]).write_text(hashlib.sha256(v).hexdigest())")
    output = tmp_path / "digest.txt"
    second = request(handle, "run", command=[sys.executable, str(script), str(output)], timeout=10, execution_id=uuid.uuid4().hex)
    assert second["exit_code"] == 0
    assert output.read_text() == hashlib.sha256(secret.encode()).hexdigest()
    state = request(handle, "status")
    assert state["expires_at"] > expiry and state["last_result"] == second
    assert "FAKE" not in "".join(capfd.readouterr())
    assert "REQUEST_TEST_SECRET" not in os.environ


def test_scope_cwd_auth_and_duplicate_execution(sessions, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    handle = sessions()
    monkeypatch.chdir(tmp_path.parent)
    other = handle[:-1] + ("A" if handle[-1] != "A" else "B")
    assert request(other, "status")["status"] == "unauthorized"
    execution_id = uuid.uuid4().hex
    assert run(handle, "from pathlib import Path; Path('ran').write_text('yes')", execution_id=execution_id)["exit_code"] == 0
    assert (tmp_path / "ran").read_text() == "yes"
    assert run(handle, "raise SystemExit(99)", execution_id=execution_id)["status"] == "duplicate_execution"
    assert request(handle, "revoke")["status"] == "revoked"
    assert run(handle, "pass")["status"] == "session_unavailable"


def test_idle_expiry(sessions):
    handle = sessions(ttl=0.5)
    time.sleep(0.8)
    assert request(handle, "status")["status"] == "session_unavailable"


def test_execution_crosses_old_expiry_then_starts_fresh_idle_period(sessions):
    handle = sessions(ttl=0.8)
    results = []
    thread = threading.Thread(target=lambda: results.append(run(handle, 'import time; time.sleep(1.1)')))
    thread.start()
    time.sleep(0.9)
    state = request(handle, 'status')
    assert state['running'] and state['expires_at'] is None and state['remaining_seconds'] is None
    thread.join(5)
    assert results[0]['exit_code'] == 0
    assert request(handle, 'status')['status'] == 'active'
    time.sleep(1)
    assert request(handle, 'status')['status'] == 'session_unavailable'


def test_queries_and_rejected_runs_do_not_renew(tmp_path, monkeypatch):
    from secret_request import session
    from types import SimpleNamespace
    now = [0.0]
    monkeypatch.setattr(session, 'time', SimpleNamespace(monotonic=lambda: now[0], time=time.time))
    broker = session.Session('FAKE', None, 300, tmp_path)
    message = {'token': broker.token, 'action': 'run', 'command': [sys.executable, '-c', 'pass'],
               'timeout': 5, 'execution_id': uuid.uuid4().hex}
    try:
        initial = broker.deadline
        now[0] = 200
        assert broker.dispatch({'token':broker.token, 'action':'status'})['status'] == 'active'
        assert broker.dispatch({**message, 'token':'wrong'})['status'] == 'unauthorized'
        assert broker.dispatch({**message, 'timeout':False})['status'] == 'invalid_request'
        assert broker.deadline == initial
        monkeypatch.setattr(session, 'execute', lambda *args, **kw: 0)
        assert broker.dispatch(message)['exit_code'] == 0
        assert broker.deadline == 500
        now[0] = 450
        assert broker.dispatch(message)['status'] == 'duplicate_execution'
        assert broker.deadline == 500
        now[0] = 500
        assert not broker.available() and broker.secret is None
    finally:
        broker.close()


def test_session_slot_limit_and_release(tmp_path, monkeypatch):
    from secret_request import session
    monkeypatch.setattr(session.Path, 'home', lambda: tmp_path)
    monkeypatch.setattr(session, 'MAX_SESSIONS', 1)
    with session.SessionSlot():
        with pytest.raises(RuntimeError):
            with session.SessionSlot():
                pass
    with session.SessionSlot():
        pass
    assert all(p.stat().st_size == 0 for p in (tmp_path/'.config/secret-request/session-slots').iterdir())


@pytest.mark.parametrize('stop', ['close', 'kill'])
def test_session_slot_limit_across_processes_and_crash_release(tmp_path, stop):
    # Exercise the same OS locks with a smaller limit in an isolated home directory.
    code = "import sys; from pathlib import Path; from secret_request import session; Path.home=lambda:Path(sys.argv[1]); session.MAX_SESSIONS=2; slot=session.SessionSlot(); slot.__enter__(); print('ready',flush=True); sys.stdin.readline(); slot.__exit__()"
    processes = []
    def start():
        process = subprocess.Popen([sys.executable,'-c',code,str(tmp_path)],stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        processes.append(process)
        return process
    try:
        first, second = start(), start()
        assert first.stdout.readline() == b'ready\r\n' if os.name == 'nt' else first.stdout.readline() == b'ready\n'
        assert second.stdout.readline().strip() == b'ready'
        refused = start()
        assert refused.wait(timeout=10) != 0
        if stop == 'kill': first.kill()
        else: first.stdin.close()
        first.wait(timeout=10)
        replacement = start()
        assert replacement.stdout.readline().strip() == b'ready'
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)
            if process.stdin and not process.stdin.closed: process.stdin.close()
            if process.stdout: process.stdout.close()


def test_large_stdin_ignored_still_times_out(sessions):
    handle = sessions(secret="\x01" * 65536, env=None)
    result = run(handle, "import time; time.sleep(60)", timeout=1)
    assert result["status"] == "execution_timeout"
    assert run(handle, "import sys; assert len(sys.stdin.buffer.read()) == 65536")["exit_code"] == 0


def assert_dead(pid):
    if os.name == "nt":
        output = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
        assert f'"{pid}"' not in output
    else:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


@pytest.mark.parametrize("stop", ["revoke", "timeout"])
def test_running_process_tree_is_stopped(sessions, tmp_path, stop):
    handle = sessions(ttl=30)
    pids = tmp_path / "pids.json"
    code = "import os,sys,subprocess,pathlib,time,json; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); pathlib.Path(sys.argv[1]).write_text(json.dumps([os.getpid(),p.pid])); time.sleep(60)"
    results = []
    thread = threading.Thread(target=lambda: results.append(run(handle, code, pids, timeout=2 if stop == "timeout" else 10)))
    thread.start()
    deadline = time.monotonic() + 5
    while not pids.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert pids.exists()
    state = request(handle, "status")
    assert state["running"]
    assert run(handle, "pass")["status"] == "busy"
    if stop == "revoke":
        assert request(handle, "revoke")["status"] == "revoked"
    thread.join(12)
    assert not thread.is_alive()
    assert results[0]["status"] in {"cancelled", "execution_timeout"}
    for pid in json.loads(pids.read_text()):
        assert_dead(pid)
    if stop == "timeout":
        assert run(handle, "pass")["exit_code"] == 0
    else:
        assert request(handle, "status")["status"] == "session_unavailable"


def test_session_survives_creating_cli_exit(tmp_path):
    code = "from secret_request.session import start_session; import json; print(json.dumps(start_session('FAKE-ONLY','REQUEST_TEST_SECRET',30)))"
    child = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=15)
    assert child.returncode == 0, child.stderr
    handle = json.loads(child.stdout)["session"]
    try:
        assert run(handle, "import os; assert os.environ['REQUEST_TEST_SECRET']=='FAKE-ONLY'")["exit_code"] == 0
        result = subprocess.run([sys.executable, "-m", "secret_request.client", "--session-status", handle], capture_output=True, text=True, timeout=10)
        assert result.returncode == 0 and json.loads(result.stdout)["status"] == "active"
        result = subprocess.run([sys.executable, "-m", "secret_request.client", "--use-session", handle, "--", sys.executable, "-c", "raise SystemExit(7)"], capture_output=True, text=True, timeout=10)
        assert result.returncode == 7 and "FAKE-ONLY" not in result.stdout + result.stderr
    finally:
        request(handle, "revoke")


def test_lost_response_can_be_checked_without_reexecution(sessions, tmp_path):
    handle = sessions()
    _, port, token = handle.split(".")
    execution_id = uuid.uuid4().hex
    output = tmp_path / "count"
    code = "import pathlib,sys,time; p=pathlib.Path(sys.argv[1]); p.write_text(str(int(p.read_text())+1) if p.exists() else '1'); time.sleep(.3)"
    message = dict(token=token, action="run", command=[sys.executable, "-c", code, str(output)], timeout=5, execution_id=execution_id)
    with socket.create_connection(("127.0.0.1", int(port)), timeout=3) as conn:
        conn.sendall(json.dumps(message).encode() + b"\n")
        # Drop the response deliberately after sending the complete command.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        state = request(handle, "status")
        if state.get("last_result"):
            break
        time.sleep(0.05)
    assert state["last_result"] == dict(status="completed", exit_code=0, execution_id=execution_id)
    assert run(handle, code, output, execution_id=execution_id)["status"] == "duplicate_execution"
    assert output.read_text() == "1"


def test_execution_history_is_bounded(tmp_path, monkeypatch):
    from secret_request import session
    monkeypatch.setattr(session, "MAX_EXECUTIONS", 1)
    broker = session.Session("fake", None, 30, tmp_path)
    try:
        message = dict(token=broker.token, action="run", command=[sys.executable, "-c", "pass"], timeout=5, execution_id=uuid.uuid4().hex)
        assert broker.dispatch(message)["exit_code"] == 0
        message["execution_id"] = uuid.uuid4().hex
        assert broker.dispatch(message)["status"] == "session_limit"
        assert len(broker.seen) == 1
    finally:
        broker.close()
