"""Synthetic tasks, isolated profiles, real Windows CTRL_C_EVENT / POSIX SIGINT."""
import json
import os
from pathlib import Path
import queue
import signal
import socket
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from urllib.parse import urlsplit
import uuid

import httpx
import pytest

from secret_request import client, session
from secret_request.crypto import validate_jwk
from .test_crypto import encrypt

ROOT = Path(__file__).resolve().parents[1]
FAKE = "FAKE-INTERRUPT-ONLY"


def until(predicate, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.02)
    pytest.fail("Timed out waiting for synthetic test state")


def isolated_env(tmp_path):
    keep = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "PROGRAMFILES",
            "PROGRAMFILES(X86)", "PROGRAMW6432", "USERDOMAIN", "USERNAME",
            "ALLUSERSPROFILE", "PROGRAMDATA"}
    env = {k: v for k, v in os.environ.items() if k.upper() in keep}
    home = tmp_path / "profile"
    for name in ("AppData/Local", "AppData/Roaming", "tmp"):
        (home / name).mkdir(parents=True, exist_ok=True)
    env.update(HOME=str(home), USERPROFILE=str(home), LOCALAPPDATA=str(home / "AppData/Local"),
               APPDATA=str(home / "AppData/Roaming"), TEMP=str(home / "tmp"), TMP=str(home / "tmp"),
               PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PIP_CONFIG_FILE=os.devnull)
    return env


def start_cli(arguments, env, bootstrap=None, phase="normal", folder=None):
    code = bootstrap or "import sys;sys.path.insert(0,sys.argv.pop(1));from secret_request.client import main;raise SystemExit(main())"
    if os.name == "nt":
        # The automation host may inherit Win32's ignore-Ctrl+C attribute.
        # Restore interactive console semantics only in this isolated target.
        code = "import ctypes;assert ctypes.WinDLL('kernel32').SetConsoleCtrlHandler(None,False);" + code
    argv = [sys.executable, "-I", "-X", "utf8", "-c", code, str(ROOT)]
    if bootstrap:
        argv += [str(folder), phase]
    argv += arguments
    options = dict(env=env, cwd=ROOT, stdin=subprocess.DEVNULL,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
    if os.name == "nt":
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        options.update(startupinfo=startup, creationflags=subprocess.CREATE_NEW_CONSOLE)
    else:
        options["start_new_session"] = True
    return subprocess.Popen(argv, **options)


def send_ctrl_c(process, env):
    if os.name == "nt":
        # This helper alone attaches to the target's hidden, dedicated console.
        # CTRL_C_EVENT cannot target a nonzero process-group ID.
        code = ("import ctypes,sys,time; k=ctypes.WinDLL('kernel32',use_last_error=True); "
                "k.FreeConsole(); assert k.AttachConsole(int(sys.argv[1])),ctypes.get_last_error(); "
                "assert k.SetConsoleCtrlHandler(None,True); "
                "assert k.GenerateConsoleCtrlEvent(0,0); time.sleep(.3); k.FreeConsole()")
        subprocess.run([sys.executable, "-I", "-c", code, str(process.pid)], env=env,
                       creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True, check=True, timeout=5)
    else:
        os.killpg(process.pid, signal.SIGINT)


class Events:
    def __init__(self, process):
        self.process, self.items, self.lines = process, queue.Queue(), []
        def read():
            for line in process.stdout:
                self.lines.append(line)
                self.items.put(json.loads(line))
        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()

    def get(self, status):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                event = self.items.get(timeout=.1)
            except queue.Empty:
                continue
            if event["status"] == status:
                return event
        pytest.fail("Missing controlled CLI event: " + status)

    def finish(self):
        self.process.wait(timeout=15)
        self.reader.join(3)
        stderr = self.process.stderr.read()
        assert FAKE not in "".join(self.lines) + stderr
        assert "Traceback" not in stderr
        return [json.loads(line) for line in self.lines]


# Test-only barriers around actual handoff/RPC operations. Signals are delivered
# by the OS; these hooks do not throw KeyboardInterrupt or fabricate results.
BOOTSTRAP = """
import sys,time,json
from pathlib import Path
sys.path.insert(0,sys.argv.pop(1))
folder=Path(sys.argv.pop(1)); phase=sys.argv.pop(1)
from secret_request import session,client
def barrier(data):
    (folder/'barrier').write_text(json.dumps(data))
    deadline=time.monotonic()+12
    while not (folder/'release').exists() and time.monotonic()<deadline: time.sleep(.02)
if phase in ('submitted_response','consume_response'):
    import httpx
    method='get' if phase=='submitted_response' else 'post'
    original=getattr(httpx.Client,method)
    def http(self,url,*args,**kwargs):
        result=original(self,url,*args,**kwargs)
        if (phase=='submitted_response' and url.endswith('/status') and result.json().get('state')=='submitted') or (phase=='consume_response' and url.endswith('/consume')):
            barrier({'phase':phase})
        return result
    setattr(httpx.Client,method,http)
if phase=='startup_before':
    original=session.write_message
    def write(stream,message):
        if 'secret' in message: barrier({'phase':phase})
        return original(stream,message)
    session.write_message=write
if phase=='startup_after':
    original=session.start_session
    def start(*args):
        ready=original(*args); barrier({'session':ready['session']}); return ready
    session.start_session=start
if phase in ('completed_response','completed_read','lost_revoke'):
    original=session.request
    def request(handle,action,**payload):
        result=original(handle,action,**payload)
        if action=='run' and phase in ('completed_response','lost_revoke'):
            barrier({'execution_id':payload['execution_id']})
        elif action=='status' and phase=='completed_read':
            barrier({'execution_id':payload['execution_id']})
        elif action=='revoke' and phase=='lost_revoke':
            return {'status':'result_unknown'}  # Drop the successful revoke response only.
        return result
    session.request=request
if phase in ('unknown_emit','known_query_lost_revoke','late_run_known'):
    original=session.request
    def request(handle,action,**payload):
        result=original(handle,action,**payload)
        if phase=='late_run_known':
            if action=='run': barrier({'execution_id':payload['execution_id']})
            if action=='revoke':
                (folder/'revoke_started').touch()
                deadline=time.monotonic()+5
                while not (folder/'remembered').exists() and time.monotonic()<deadline: time.sleep(.02)
                assert (folder/'remembered').exists()
                return {'status':'result_unknown'}
            return result
        return {'status':'result_unknown'} if (action=='run' or (phase=='unknown_emit' and action=='status') or (phase=='known_query_lost_revoke' and action=='revoke')) else result
    session.request=request
if phase=='late_run_known':
    original_remember=client.Interrupts.remember
    def remember(self,result):
        original_remember(self,result)
        if self.known: (folder/'remembered').touch()
    client.Interrupts.remember=remember
if phase in ('completed_emit','unknown_emit','known_query_lost_revoke'):
    original_emit=client.emit
    def emit(**value):
        if value['status']==('result_unknown' if phase=='unknown_emit' else 'completed'):
            barrier({'execution_id':value['execution_id']})
        original_emit(**value)
    client.emit=emit
if phase=='disconnect_before_accept':
    import socket
    original=session.request
    def request(handle,action,**payload):
        if action!='run': return original(handle,action,**payload)
        _,port,token=handle.split('.')
        with socket.create_connection(('127.0.0.1',int(port)),timeout=3) as conn:
            conn.sendall(json.dumps(dict(payload,action=action,token=token)).encode()+b'\\n')
            deadline=time.monotonic()+10
            while not (folder/'barrier').exists() and time.monotonic()<deadline: time.sleep(.02)
        return {'status':'result_unknown'}
    session.request=request
raise SystemExit(client.main())
"""


@pytest.fixture
def relay(tmp_path):
    env = isolated_env(tmp_path)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env["SECRET_REQUEST_TEST_PORT"] = str(port)
    base = f"http://127.0.0.1:{port}"
    process = subprocess.Popen([sys.executable, "-m", "uvicorn", "tests.browser_server:app",
        "--host", "127.0.0.1", "--port", str(port), "--no-access-log", "--log-level", "warning"],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    def ready():
        try:
            return httpx.get(base + "/health", trust_env=False).status_code == 200
        except httpx.HTTPError:
            return False
    try:
        until(ready)
        yield base, env
    finally:
        process.terminate()
        process.wait(timeout=10)


def approve(waiting):
    parts = urlsplit(waiting["input_url"])
    path = f"{parts.scheme}://{parts.netloc}/api/requests/" + waiting["request_id"]
    headers = {"Authorization": "Bearer " + parts.fragment}
    with httpx.Client(trust_env=False) as http:
        details = http.get(path, headers=headers).json()
        key = SimpleNamespace(public_key=lambda: validate_jwk(details["public_key"]))
        response = http.post(path + "/submit", headers=headers,
                             json=encrypt(key, waiting["request_id"], FAKE))
        assert response.status_code == 200


def consumer(tmp_path, long=True):
    if not long:
        return [sys.executable, "-c", "import sys; print(sys.stdin.read()); raise SystemExit(7)"]
    code = ("import os,sys,pathlib,subprocess,time,json; value=sys.stdin.read(); "
            "print(value); print(value,file=sys.stderr); "
            "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
            "pathlib.Path(sys.argv[1]).write_text(json.dumps([os.getpid(),p.pid])); time.sleep(30)")
    return [sys.executable, "-c", code, str(tmp_path / "pids")]


def assert_dead(pid):
    if os.name == "nt":
        # Exit code polling avoids locale-sensitive tasklist output.
        import ctypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        handle = kernel.OpenProcess(0x1000, False, pid)
        if handle:
            try:
                code = ctypes.c_ulong()
                assert kernel.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code))
                assert code.value != 259
            finally:
                kernel.CloseHandle(ctypes.c_void_p(handle))
    else:
        # Containers/WSL may briefly retain reparented zombies after SIGKILL.
        stat = Path(f"/proc/{pid}/stat")
        if stat.exists() and stat.read_text().split(") ", 1)[1].startswith("Z"):
            return
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


@pytest.mark.parametrize("phase", ["waiting", "submitted_response", "consume_response", "startup_before",
                                  "startup_after", "running", "completed_response", "completed_read"])
def test_real_interrupt_default_request(relay, tmp_path, phase):
    base, env = relay
    config = tmp_path / "client.json"
    config.write_text(json.dumps({"url": base, "notifications": {"local": False}}))
    completed = phase.startswith("completed")
    arguments = ["--config", str(config), "--allow-local-http", "--show-link",
                 "--name", "fictional test", "--purpose", "isolated interrupt test", "--",
                 *consumer(tmp_path, not completed)]
    process = start_cli(arguments, env, BOOTSTRAP, phase, tmp_path)
    events = Events(process)
    handle = None
    try:
        waiting = events.get("waiting")
        if phase != "waiting":
            approve(waiting)
        if phase in {"submitted_response", "consume_response", "startup_before", "startup_after",
                     "completed_response", "completed_read"}:
            until(lambda: (tmp_path / "barrier").exists())
            if phase == "startup_after":
                handle = json.loads((tmp_path / "barrier").read_text())["session"]
        elif phase == "running":
            handle = events.get("session_ready")["session"]
            until(lambda: (tmp_path / "pids").exists())
        send_ctrl_c(process, env)
        # A second real signal must not interrupt cleanup / handle handoff.
        if phase in {"startup_before", "startup_after"}:
            send_ctrl_c(process, env)
        (tmp_path / "release").touch()
        output = events.finish()
        ready = next((event for event in output if event["status"] == "session_ready"), None)
        handle = handle or (ready["session"] if ready else None)
        final = output[-1]
        assert process.returncode == (7 if completed else 130)
        assert final["session_state"] == ("not_created" if phase in {"waiting", "submitted_response", "consume_response"} else "revoked")
        assert final["execution"]["status"] == ("completed" if completed else
                                                  "cancelled" if phase == "running" else "not_started")
        if completed:
            assert final["exit_code"] == final["execution"]["exit_code"] == 7
        if phase in {"waiting", "submitted_response", "consume_response"}:
            parts = urlsplit(waiting["input_url"])
            path = f"{parts.scheme}://{parts.netloc}/api/requests/" + waiting["request_id"]
            state = httpx.get(path, headers={"Authorization": "Bearer " + parts.fragment}, trust_env=False).json()
            assert state["state"] == ("consumed" if phase == "consume_response" else "cancelled")
        if handle:
            state = session.request(handle, "status", execution_id=final["execution_id"])
            assert state["session_state"] == "revoked"
            assert state["execution"] == final["execution"]
            assert session.request(handle, "run", command=consumer(tmp_path), timeout=5,
                                   execution_id=uuid.uuid4().hex)["status"] == "session_unavailable"
        if phase == "running":
            for pid in json.loads((tmp_path / "pids").read_text()):
                assert_dead(pid)
        elif not completed:
            assert not (tmp_path / "pids").exists()
    finally:
        (tmp_path / "release").touch()
        if handle:
            session.request(handle, "revoke")
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        process.stdout.close()
        process.stderr.close()


def broker(tmp_path, profile=None, receipt_seconds=None, limit=None, delay_run=None):
    # Bootstrap through anonymous pipes, with an explicit disposable home.
    code = ("import sys,runpy; from pathlib import Path; "
            "sys.path.insert(0,sys.argv.pop(1)); profile=Path(sys.argv.pop(1)); "
            "Path.home=lambda:profile; from secret_request import session; ")
    if receipt_seconds is not None:
        code += f"session.RECEIPT_SECONDS={receipt_seconds}; "
    if limit is not None:
        code += f"session.MAX_SESSIONS={limit}; "
    if delay_run is not None:
        code += "\n" + f"""
import time
folder=Path({str(delay_run)!r})
original=session.Session.dispatch
def dispatch(self,message):
    if message.get('action')=='run':
        (folder/'barrier').touch()
        deadline=time.monotonic()+12
        while not (folder/'release').exists() and time.monotonic()<deadline: time.sleep(.02)
    return original(self,message)
session.Session.dispatch=dispatch
"""
    code += "\nsession.serve(session.read_message(sys.stdin.buffer))"
    process = subprocess.Popen([sys.executable, "-I", "-X", "utf8", "-c", code,
                                str(ROOT), str(profile or tmp_path / "broker-profile")],
        cwd=ROOT, env=isolated_env(tmp_path), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL)
    session.write_message(process.stdin, {"secret": FAKE, "env": None, "ttl": 30, "cwd": str(ROOT)})
    process.stdin.close()
    handle = session.read_message(process.stdout)["session"]
    process.stdout.close()
    return process, handle


@pytest.mark.parametrize("phase", ["running", "completed_response", "completed_read", "completed_emit",
                                  "unknown_emit", "known_query_lost_revoke", "late_run_known", "lost_revoke"])
def test_real_interrupt_use_session_and_other_session_survives(tmp_path, phase):
    owned, handle = broker(tmp_path / "a")
    other, other_handle = broker(tmp_path / "b")
    env = isolated_env(tmp_path)
    completed = phase != "running"
    process = start_cli(["--use-session", handle, "--", *consumer(tmp_path, not completed)],
                        env, BOOTSTRAP, phase, tmp_path)
    events = Events(process)
    try:
        requested = events.get("execution_requested")
        if phase == "running":
            until(lambda: (tmp_path / "pids").exists())
        else:
            until(lambda: (tmp_path / "barrier").exists())
        send_ctrl_c(process, env)
        if phase == "late_run_known":
            until(lambda: (tmp_path / "revoke_started").exists())
        if phase in {"completed_read", "completed_emit", "unknown_emit", "known_query_lost_revoke", "late_run_known"}:
            (tmp_path / "release").touch()
        output = events.finish()
        final = output[-1]
        assert final["execution_id"] == requested["execution_id"]
        if phase in {"lost_revoke", "known_query_lost_revoke", "late_run_known"}:
            assert final["session_state"] == "unknown"
            if phase == "lost_revoke":
                assert final["status"] == "result_unknown" and final["execution"]["status"] == "unknown"
                assert process.returncode == 2
            else:
                assert final["status"] == "completed" and final["execution"]["exit_code"] == 7
                assert process.returncode == 7
            # Execute the emitted query arguments, not an invented recovery path.
            queried = subprocess.run([sys.executable, "-m", "secret_request.client",
                                      *final["recovery"]["query_args"]],
                cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=10)
            receipt = json.loads(queried.stdout)
            assert queried.returncode == 0 and FAKE not in queried.stdout + queried.stderr
            assert receipt["session_state"] == "revoked"
            assert receipt["execution"]["execution_id"] == requested["execution_id"]
            assert receipt["execution"]["status"] == "completed" and receipt["execution"]["exit_code"] == 7
            revoked = subprocess.run([sys.executable, "-m", "secret_request.client",
                                      *final["recovery"]["revoke_args"]],
                cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=10)
            assert revoked.returncode == 0 and FAKE not in revoked.stdout + revoked.stderr
            assert json.loads(revoked.stdout)["execution"] == receipt["execution"]
        else:
            assert final["session_state"] == "revoked"
            assert final["execution"]["status"] == ("completed" if completed else "cancelled")
            assert process.returncode == (7 if completed else 130)
        assert session.request(other_handle, "status")["status"] == "active"
        result = session.request(other_handle, "run", command=[sys.executable, "-c", "raise SystemExit(9)"],
                                 timeout=5, execution_id=uuid.uuid4().hex)
        assert result["exit_code"] == 9
        if phase == "running":
            for pid in json.loads((tmp_path / "pids").read_text()):
                assert_dead(pid)
    finally:
        (tmp_path / "release").touch()
        for proc, token in ((owned, handle), (other, other_handle)):
            session.request(token, "revoke")
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=10)
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        process.stdout.close()
        process.stderr.close()


def test_exact_id_query_survives_later_execution_and_never_renews(tmp_path):
    process, handle = broker(tmp_path)
    first, second = uuid.uuid4().hex, uuid.uuid4().hex
    marker = tmp_path / "count"
    code = "import pathlib,sys; p=pathlib.Path(sys.argv[1]); p.write_text(str(int(p.read_text())+1) if p.exists() else '1')"
    try:
        _, port, token = handle.split(".")
        with socket.create_connection(("127.0.0.1", int(port)), timeout=3) as conn:
            conn.sendall(json.dumps({"token": token, "action": "run", "execution_id": first,
                "command": [sys.executable, "-c", code, str(marker)], "timeout": 5}).encode() + b"\n")
        until(lambda: session.request(handle, "status", execution_id=first)["execution"]["status"] == "completed")
        session.request(handle, "run", command=[sys.executable, "-c", "raise SystemExit(7)"], timeout=5, execution_id=second)
        before = session.request(handle, "status")["expires_at"]
        queried = session.request(handle, "status", execution_id=first)
        assert queried["execution"] == {"status": "completed", "exit_code": 0, "execution_id": first}
        assert queried["last_result"]["execution_id"] == second
        assert session.request(handle, "status")["expires_at"] == before
        assert session.request(handle, "run", command=[sys.executable, "-c", code, str(marker)],
                               timeout=5, execution_id=first)["status"] == "duplicate_execution"
        assert marker.read_text() == "1"
        revoked = session.request(handle, "revoke", execution_id=first)
        assert revoked["execution"] == queried["execution"] and revoked["session_state"] == "revoked"
    finally:
        session.request(handle, "revoke")
        process.kill()
        process.wait(timeout=10)


def test_completed_process_wins_over_cancellation_after_launch(tmp_path):
    stopped = threading.Event()
    # A deterministic poll boundary, not a fake OS-signal acceptance test.
    class Finished:
        returncode = 7
        pid = 1
        def poll(self): return 7
        def wait(self, **_): return 7
    from unittest.mock import patch
    def launched(*_, **__):
        stopped.set()
        return Finished()
    with patch.object(client.subprocess, "Popen", side_effect=launched), \
         patch.object(client, "os", SimpleNamespace(name="posix", environ={}, killpg=lambda *_: None)), \
         patch.object(signal, "SIGKILL", 9, create=True), \
         patch.object(client.threading, "Thread"):
        assert client.execute(["fictional"], FAKE, "FAKE_ENV", 5, cancelled=stopped) == 7


def test_cancellation_known_before_launch_does_not_start_program(tmp_path):
    stopped = threading.Event()
    stopped.set()
    marker = tmp_path / "unexpected"
    with pytest.raises(client.ExecutionCancelled):
        client.execute([sys.executable, "-c", "import pathlib,sys; pathlib.Path(sys.argv[1]).touch()",
                        str(marker)], FAKE, None, 5, cancelled=stopped)
    assert not marker.exists()


def test_disconnected_run_not_yet_accepted_stays_unknown_and_is_not_repeated(tmp_path):
    owned, handle = broker(tmp_path / "a", delay_run=tmp_path)
    marker = tmp_path / "count"
    code = "import pathlib,sys; p=pathlib.Path(sys.argv[1]); p.write_text(str(int(p.read_text())+1) if p.exists() else '1')"
    env = isolated_env(tmp_path)
    process = start_cli(["--use-session", handle, "--", sys.executable, "-c", code, str(marker)],
                        env, BOOTSTRAP, "disconnect_before_accept", tmp_path)
    events = Events(process)
    try:
        requested = events.get("execution_requested")
        final = events.finish()[-1]
        assert final["status"] == "result_unknown" and final["execution"]["status"] == "unknown"
        assert final["session_state"] == "active" and not marker.exists()
        assert final["execution_id"] == requested["execution_id"]
        (tmp_path / "release").touch()
        until(marker.exists)
        until(lambda: session.request(handle, "status", execution_id=requested["execution_id"])["execution"]["status"] == "completed")
        queried = subprocess.run([sys.executable, "-m", "secret_request.client", *final["recovery"]["query_args"]],
            cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=10)
        assert queried.returncode == 0 and FAKE not in queried.stdout + queried.stderr
        assert json.loads(queried.stdout)["execution"] == {
            "status": "completed", "exit_code": 0, "execution_id": requested["execution_id"]}
        assert marker.read_text() == "1"
        assert session.request(handle, "status")["status"] == "active"
    finally:
        (tmp_path / "release").touch()
        session.request(handle, "revoke")
        if owned.poll() is None: owned.kill()
        owned.wait(timeout=10)
        if process.poll() is None: process.kill()
        process.wait(timeout=10)
        process.stdout.close()
        process.stderr.close()


def test_real_interrupt_does_not_stop_other_running_session(tmp_path):
    owned, handle = broker(tmp_path / "a")
    other, other_handle = broker(tmp_path / "b")
    marker = tmp_path / "other-started"
    code = "import pathlib,sys,time; pathlib.Path(sys.argv[1]).touch(); time.sleep(2); raise SystemExit(9)"
    result = []
    other_id = uuid.uuid4().hex
    thread = threading.Thread(target=lambda: result.append(session.request(other_handle, "run",
        command=[sys.executable, "-c", code, str(marker)], timeout=10, execution_id=other_id)))
    process = None
    try:
        thread.start()
        until(marker.exists)
        env = isolated_env(tmp_path)
        process = start_cli(["--use-session", handle, "--", *consumer(tmp_path)], env)
        events = Events(process)
        events.get("execution_requested")
        until(lambda: (tmp_path / "pids").exists())
        assert session.request(other_handle, "status", execution_id=other_id)["execution"]["status"] == "running"
        send_ctrl_c(process, env)
        final = events.finish()[-1]
        assert final["execution"]["status"] == "cancelled" and final["session_state"] == "revoked"
        thread.join(10)
        assert result == [{"status": "completed", "exit_code": 9, "execution_id": other_id}]
        assert session.request(other_handle, "status")["status"] == "active"
    finally:
        for proc, token in ((owned, handle), (other, other_handle)):
            session.request(token, "revoke")
            if proc.poll() is None: proc.kill()
            proc.wait(timeout=10)
        thread.join(10)
        if process:
            if process.poll() is None: process.kill()
            process.wait(timeout=10)
            process.stdout.close()
            process.stderr.close()


def test_revoked_receipt_releases_secret_slot_and_expires_without_renewal(tmp_path):
    profile = tmp_path / "shared-profile"
    first, handle = broker(tmp_path / "a", profile=profile, receipt_seconds=2, limit=1)
    replacement = None
    execution_id = uuid.uuid4().hex
    try:
        result = session.request(handle, "run", command=[sys.executable, "-c", "pass"],
                                 timeout=5, execution_id=execution_id)
        assert result["exit_code"] == 0
        assert session.request(handle, "revoke", execution_id=execution_id)["execution"] == result
        # A live receipt contains no reusable secret and must free its OS lock.
        time.sleep(.25)
        replacement, other_handle = broker(tmp_path / "b", profile=profile, limit=1)
        assert first.poll() is None
        assert session.request(other_handle, "status")["status"] == "active"
        end = time.monotonic() + 4
        while first.poll() is None and time.monotonic() < end:
            state = session.request(handle, "revoke", execution_id=execution_id)
            if "execution" in state:
                assert state["execution"] == result
            time.sleep(.1)
        first.wait(timeout=1)  # Repeated revoke/status cannot keep the receipt alive.
        assert session.request(handle, "status", execution_id=execution_id)["status"] == "session_unavailable"
    finally:
        if replacement:
            session.request(other_handle, "revoke")
            if replacement.poll() is None: replacement.kill()
            replacement.wait(timeout=10)
        if first.poll() is None: first.kill()
        first.wait(timeout=10)
