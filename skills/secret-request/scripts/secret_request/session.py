"""Per-task, loopback-only broker. Secrets and session state are never persisted."""
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import socket
import socketserver
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

from .client import ExecutionCancelled, execute

MAX_MESSAGE = 512 * 1024  # Room for JSON escaping a 64 KiB credential.
MAX_EXECUTIONS = 256
MAX_SESSIONS = 16


def read_message(stream):
    raw = stream.readline(MAX_MESSAGE + 1)
    if len(raw) > MAX_MESSAGE or not raw.endswith(b"\n"):
        raise ValueError("invalid message")
    message = json.loads(raw)
    if not isinstance(message, dict):
        raise ValueError("invalid message")
    return message


def write_message(stream, message):
    stream.write(json.dumps(message, ensure_ascii=True).encode("ascii") + b"\n")
    stream.flush()


def request(handle, action, **payload):
    match = re.fullmatch(r"sr1\.(\d{1,5})\.([A-Za-z0-9_-]{43})", handle)
    if not match or not 1 <= int(match[1]) <= 65535:
        return {"status": "invalid_session"}
    try:
        with socket.create_connection(("127.0.0.1", int(match[1])), timeout=3) as conn:
            conn.settimeout(payload.get("timeout", 0) + 15)
            with conn.makefile("rwb") as stream:
                write_message(stream, dict(payload, action=action, token=match[2]))
                return read_message(stream)
    except ConnectionRefusedError:
        return {"status": "session_unavailable"}
    except (OSError, ValueError):
        # A disconnected run might have executed. Never retry it automatically.
        return {"status": "result_unknown", "message": "查询会话状态及业务结果后再决定是否重试。"}


class Session:
    def __init__(self, secret, env, ttl, cwd):
        self.secret = secret
        self.env = env
        self.cwd = str(Path(cwd).resolve(strict=True))
        self.ttl = ttl
        self.refresh_idle()
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.idle = threading.Event()
        self.idle.set()
        self.running = None
        self.last_result = None
        self.seen = set()

    def refresh_idle(self):
        self.deadline = time.monotonic() + self.ttl
        self.expires_at = datetime.fromtimestamp(time.time() + self.ttl, timezone.utc).isoformat()

    def expire_idle(self):
        # Caller holds self.lock. Running tasks have their own execution timeout.
        if self.running is None and time.monotonic() >= self.deadline:
            self.secret = None
            self.stopped.set()
        return self.stopped.is_set()

    def available(self):
        with self.lock:
            return not self.expire_idle()

    def close(self):
        with self.lock:
            self.secret = None
            self.stopped.set()

    def dispatch(self, message):
        token = message.get("token")
        if not isinstance(token, str) or not hmac.compare_digest(token, self.token):
            return {"status": "unauthorized"}
        action = message.get("action")
        if action == "revoke":
            self.close()
            self.idle.wait(10)
            return {"status": "revoked" if self.idle.is_set() else "revoking"}
        with self.lock:
            if self.expire_idle():
                return {"status": "session_unavailable"}
            if action == "status":
                return {"status": "active", "idle_timeout_seconds": self.ttl,
                        "remaining_seconds": None if self.running else max(0, int(self.deadline - time.monotonic())),
                        "expires_at": None if self.running else self.expires_at, "running": self.running,
                        "last_result": self.last_result}
            if action != "run":
                return {"status": "invalid_request"}
            command, timeout, execution_id = (message.get(k) for k in ("command", "timeout", "execution_id"))
            if (not isinstance(command, list) or not command or
                    not all(isinstance(arg, str) and "\0" not in arg for arg in command) or
                    type(timeout) is not int or not 1 <= timeout <= 3600 or
                    not isinstance(execution_id, str) or not re.fullmatch(r"[a-f0-9]{32}", execution_id)):
                return {"status": "invalid_request"}
            if execution_id in self.seen:
                return {"status": "duplicate_execution", "execution_id": execution_id}
            if self.running:
                return {"status": "busy", "execution_id": self.running}
            if len(self.seen) >= MAX_EXECUTIONS:
                return {"status": "session_limit", "message": "本会话执行次数已达上限，请停止并检查重试逻辑。"}
            self.seen.add(execution_id)
            self.running = execution_id
            self.refresh_idle()
            self.idle.clear()
            secret = self.secret
        result = {"execution_id": execution_id}
        try:
            result.update(status="completed", exit_code=execute(
                command, secret, self.env, timeout,
                cwd=self.cwd, cancelled=self.stopped))
        except ExecutionCancelled:
            result.update(status="cancelled")
        except subprocess.TimeoutExpired:
            result.update(status="execution_timeout")
        except Exception:
            result.update(status="execution_failed")
        finally:
            secret = None
            with self.lock:
                self.running = None
                self.last_result = result.copy()
                if not self.stopped.is_set():
                    self.refresh_idle()
                self.idle.set()
        return result


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(3)
        try:
            result = self.server.session.dispatch(read_message(self.rfile))
            write_message(self.wfile, result)
        except Exception:
            # No traceback: it could contain credential-bearing data.
            pass


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = False
    daemon_threads = False

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        pass


class SessionSlot:
    """OS locks bound per-user broker count; no secrets, handles or PIDs on disk."""
    def __enter__(self):
        root = Path.home() / ".config/secret-request/session-slots"
        root.mkdir(parents=True, exist_ok=True)
        self.file = None
        for slot in range(MAX_SESSIONS):
            candidate = (root / str(slot)).open("a+b")
            candidate.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(candidate.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(candidate.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.file = candidate
                return self
            except OSError:
                candidate.close()
        raise RuntimeError("local session limit reached")

    def __exit__(self, *args):
        if self.file:
            # Explicit unlock is required by Windows byte-range locking.
            if os.name == "nt":
                import msvcrt
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            self.file.close()


def serve(bootstrap):
    with SessionSlot():
        serve_session(bootstrap)


def serve_session(bootstrap):
    session = Session(**bootstrap)
    bootstrap.clear()
    try:
        with Server(("127.0.0.1", 0), Handler) as server:
            server.session = session
            server.timeout = 0.2
            write_message(sys.stdout.buffer, {
                "session": f"sr1.{server.server_address[1]}.{session.token}",
                "expires_at": session.expires_at, "idle_timeout_seconds": session.ttl})
            sys.stdout.close()
            while session.available():
                server.handle_request()
            session.close()
    finally:
        session.close()


def start_session(secret, env, ttl):
    # Anonymous pipes only: no credential/handle files, environment or command arguments.
    # Pin the broker to this installed copy, independent of cwd/PYTHONPATH and
    # without requiring an editable installation of the development checkout.
    bootstrap_code = "import runpy,sys; sys.path.insert(0,sys.argv.pop(1)); runpy.run_module('secret_request.session',run_name='__main__')"
    process = subprocess.Popen([sys.executable, "-I", "-X", "utf8", "-c", bootstrap_code,
                                str(Path(__file__).resolve().parent.parent)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        creationflags=(subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0,
        start_new_session=os.name != "nt")
    try:
        write_message(process.stdin, {"secret": secret, "env": env, "ttl": ttl, "cwd": os.getcwd()})
        process.stdin.close()
        # Bound startup without exposing bootstrap data through errors.
        result = []
        def read_ready():
            try:
                result.append(read_message(process.stdout))
            except Exception:
                pass
        reader = threading.Thread(target=read_ready, daemon=True)
        reader.start()
        reader.join(10)
        if not result:
            raise RuntimeError("session startup failed")
        process.stdout.close()
        return result[0]
    except BaseException:
        process.kill()
        process.wait(timeout=5)
        raise
    finally:
        if process.stdin and not process.stdin.closed:
            process.stdin.close()
        if process.poll() is not None and process.stdout:
            process.stdout.close()


if __name__ == "__main__":
    try:
        bootstrap = read_message(sys.stdin.buffer)
        sys.stdin.close()
        serve(bootstrap)
    except BaseException:
        raise SystemExit(1)
