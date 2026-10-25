"""Request, decrypt in memory and run. Never expose a 'print secret' command."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

import httpx

from .crypto import decrypt, new_key, public_jwk
from .fields import validate_agent, validate_fields, validate_values
from .notifications import input_url, notify, use_short_input_link, validate_notifications


def load_config(path: Path, allow_local_http=False) -> dict:
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict) or set(config) - {"url", "notifications"}:
        raise ValueError("invalid client configuration")
    parts = urlsplit(config["url"])
    local = parts.hostname in {"localhost", "127.0.0.1", "::1", "testserver"}
    loopback = parts.hostname in {"localhost", "127.0.0.1", "::1"}
    if parts.scheme != "https" and not (parts.scheme == "http" and (loopback or (allow_local_http and local))):
        raise ValueError("HTTPS required")
    if not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or parts.path not in {"", "/"}:
        raise ValueError("invalid service URL")
    config["url"] = config["url"].rstrip("/")
    config["notifications"] = validate_notifications(config.get("notifications"), allow_local_http)
    return config


def emit(**value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def stop_process(process):
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        except subprocess.TimeoutExpired:
            pass
    else:
        import signal
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.kill()
    process.wait(timeout=10)


class ExecutionCancelled(Exception):
    pass


TERMINAL_EXECUTIONS = {"completed", "cancelled", "execution_timeout", "execution_failed"}


def execute(command: list[str], secret: str, env_name: str | None, timeout: float,
            *, cwd=None, cancelled=None) -> int:
    if cancelled is not None and cancelled.is_set():
        raise ExecutionCancelled()
    environment = os.environ.copy()
    if env_name:
        environment[env_name] = secret
    # stdout/stderr are deliberately NOT sent to the agent. A child can encode,
    # split or transform a secret, so text redaction is not a confidentiality boundary.
    job, process, writer = None, None, None
    if os.name == "nt":
        from .windows_job import Job
        job = Job()
    try:
        process = subprocess.Popen(command, env=environment, shell=False, cwd=cwd,
            stdin=subprocess.PIPE if not env_name else subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=os.name != "nt",
            creationflags=0x08000004 if os.name == "nt" else 0)
        if job: job.start(process)
        if not env_name:
            # Writing to an unread stdin can block on Windows; keep cancellation
            # and the execution deadline in the supervising thread.
            def feed():
                try:
                    process.stdin.write(secret.encode("utf-8"))
                    process.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass
                finally:
                    try:
                        process.stdin.close()
                    except OSError:
                        pass
            writer = threading.Thread(target=feed, daemon=True)
            writer.start()
        deadline = time.monotonic() + timeout
        while True:
            # Preserve a completed process result even if cancellation arrived next.
            if process.poll() is not None:
                return process.returncode
            if cancelled is not None and cancelled.is_set():
                raise ExecutionCancelled()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout)
            try:
                process.wait(timeout=min(0.2, remaining))
                break
            except subprocess.TimeoutExpired:
                pass
        return process.returncode
    except ExecutionCancelled:
        if process and process.poll() is not None:
            return process.returncode
        if process: stop_process(process)
        raise
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        if process and process.poll() is not None:
            return process.returncode
        if process: stop_process(process)
        raise
    except Exception:
        if process and process.poll() is None: stop_process(process)
        raise
    finally:
        if job: job.close()
        elif process:
            import signal
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
        if writer:
            writer.join(timeout=2)


class Interrupts:
    """Record SIGINT without throwing across a broker-handle ownership handoff."""
    def __init__(self):
        self.requested = threading.Event()
        self.previous = signal.getsignal(signal.SIGINT)
        self.handle = self.execution_id = self.known = None
        self.settled = False
        signal.signal(signal.SIGINT, lambda *_: self.requested.set())

    def remember(self, result):
        if result.get("status") in TERMINAL_EXECUTIONS and result.get("execution_id") == self.execution_id:
            self.known = result

    def restore(self):
        signal.signal(signal.SIGINT, self.previous)


def recovery(handle, execution_id):
    return {"query_args": ["--session-status", handle, "--execution-id", execution_id],
            "revoke_args": ["--revoke-session", handle, "--execution-id", execution_id]}


def session_state(response):
    if "session_state" in response:
        return response["session_state"]
    return {"active": "active", "revoked": "revoked", "revoking": "revoking",
            "session_unavailable": "unavailable"}.get(response.get("status"), "unknown")


def report_execution(execution, state, handle, execution_id, *, interrupted=False):
    status = execution["status"]
    unknown = status in {"unknown", "running"}
    event = {"status": "result_unknown" if unknown else
             ("interrupted" if interrupted else execution.get("reason", "not_started")) if status == "not_started" else status,
             "execution_id": execution_id, "execution": execution, "session_state": state}
    if interrupted:
        event["interruption_requested"] = True
    if unknown or state in {"unknown", "revoking"}:
        event["recovery"] = recovery(handle, execution_id)
    if status == "cancelled":
        event["message"] = "本次执行已中止；已发生的业务副作用未回滚。"
    if status == "completed":
        event["exit_code"] = execution["exit_code"]
    emit(**event)
    if status == "completed":
        code = execution["exit_code"]
        return code if 0 <= code <= 125 else 1
    return 3 if status == "execution_timeout" else 130 if interrupted and not unknown else 2


def interrupt_session(handle, execution_id, known=None, interrupt=None):
    from .session import request
    response = request(handle, "revoke", execution_id=execution_id)
    execution = response.get("execution", {"status": "unknown", "execution_id": execution_id})
    # The run worker may have confirmed a terminal result while revoke waited.
    if interrupt is not None and interrupt.known is not None:
        known = interrupt.known
    if known and known.get("status") in TERMINAL_EXECUTIONS:
        execution = known
    code = report_execution(execution, session_state(response), handle, execution_id, interrupted=True)
    if interrupt is not None:
        interrupt.settled = True
    return code


def run(args, client=None, on_created=None, interrupt=None) -> int:
    config = load_config(args.config, args.allow_local_http)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        raise ValueError("command required")
    if not shutil.which(command[0]):
        raise ValueError("executable not found")
    if args.env and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", args.env):
        raise ValueError("invalid environment variable")
    agent = validate_agent(getattr(args, "agent_name", None) or "未注明 Agent")
    fields_path = getattr(args, "fields_file", None)
    fields = None
    if fields_path:
        if fields_path.stat().st_size > 16384:
            raise ValueError("field definition too large")
        fields = validate_fields(json.loads(fields_path.read_text(encoding="utf-8-sig")))
        if fields is None:
            raise ValueError("field definitions required")
    session_ttl = getattr(args, "session_ttl", 0)
    purpose = args.purpose
    if session_ttl:
        purpose += f"（本机同一任务内复用；执行结束后空闲 {session_ttl} 秒自动清除）"
    if not 1 <= len(purpose) <= 500:
        raise ValueError("purpose too long")
    key, rid, receive, consumed, delivery = new_key(), None, None, False, None
    owned_client = client is None
    client = client or httpx.Client(timeout=12, trust_env=False, follow_redirects=False)
    base = config["url"]
    try:
        # Relays that do not recognize this header ignore it and return a legacy link.
        # A native helper that fails --supports-short-links still only opens the legacy URL.
        headers = {"X-Secret-Request-Link": "short"} if use_short_input_link(config["notifications"]) else None
        response = client.post(base + "/api/requests", headers=headers,
            json={"name": args.name, "purpose": purpose, "ttl_seconds": args.wait, "public_key": public_jwk(key),
                  "agent": agent, "fields": fields})
        response.raise_for_status()
        created = response.json()
        rid, receive = created["id"], created["receive_token"]
        # Validate before passing a capability link to any external notifier.
        link = input_url(base, created)
        delivery = notify(config, created, args.name, purpose, agent)
        emit(status="waiting", request_id=rid, notifications=delivery,
             **({"input_url": link} if getattr(args, "show_link", False) else {}))
        if on_created:
            on_created(created)
        headers = {"Authorization": "Bearer " + receive}
        deadline = time.monotonic() + args.wait
        while time.monotonic() < deadline:
            if interrupt is not None and interrupt.requested.is_set():
                emit(status="interrupted", execution={"status": "not_started"}, session_state="not_created")
                return 130
            response = client.get(base + f"/api/requests/{rid}/status", headers=headers)
            response.raise_for_status()
            state = response.json()["state"]
            if state == "submitted":
                if interrupt is not None and interrupt.requested.is_set():
                    emit(status="interrupted", execution={"status": "not_started"}, session_state="not_created")
                    return 130
                response = client.post(base + f"/api/requests/{rid}/consume", headers=headers, json={})
                response.raise_for_status()
                consumed = True
                delivery.close()
                secret = decrypt(key, rid, response.json()["envelope"])
                try:
                    validate_values(secret, fields)
                    if interrupt is not None and interrupt.requested.is_set():
                        emit(status="interrupted", execution={"status": "not_started"}, session_state="not_created")
                        return 130
                    if session_ttl:
                        from .session import start_session
                        session = start_session(secret, args.env, session_ttl)
                        if interrupt is not None:
                            import uuid
                            interrupt.handle = session["session"]
                            interrupt.execution_id = uuid.uuid4().hex
                        emit(status="session_ready", request_id=rid, **session)
                        secret = None
                        return use_session(session["session"], command, args.execution_timeout, interrupt)
                    try:
                        exit_code = execute(command, secret, args.env, args.execution_timeout,
                                            cancelled=interrupt.requested if interrupt else None)
                    except ExecutionCancelled:
                        emit(status="cancelled", execution={"status": "cancelled"}, session_state="not_created",
                             message="本次执行已中止；已发生的业务副作用未回滚。")
                        return 130
                finally:
                    secret = None
                emit(status="completed", request_id=rid, exit_code=exit_code)
                return exit_code if 0 <= exit_code <= 125 else 1
            if state != "pending":
                emit(status=state, request_id=rid)
                return 2
            time.sleep(0.5)
        emit(status="expired", request_id=rid)
        return 2
    finally:
        if delivery is not None:
            delivery.close()
        if rid and not consumed:
            try:
                client.post(base + f"/api/requests/{rid}/cancel", headers={"Authorization": "Bearer " + receive}, json={})
            except Exception:
                pass
        key, receive = None, None
        if owned_client:
            client.close()


def use_session(handle, command, timeout, interrupt=None):
    from .session import request
    import uuid
    execution_id = (interrupt.execution_id if interrupt is not None else None) or uuid.uuid4().hex
    if interrupt is not None:
        interrupt.handle, interrupt.execution_id = handle, execution_id
    emit(status="execution_requested", execution_id=execution_id)
    if interrupt is not None and interrupt.requested.is_set():
        return interrupt_session(handle, execution_id, interrupt=interrupt)
    results = []
    def receive():
        try:
            result = request(handle, "run", command=command, timeout=timeout, execution_id=execution_id)
        except Exception:
            result = {"status": "result_unknown"}
        if interrupt is not None:
            interrupt.remember(result)
        results.append(result)
    worker = threading.Thread(target=receive, daemon=True)
    worker.start()
    while worker.is_alive():
        worker.join(.05)
        if interrupt is not None and interrupt.requested.is_set():
            return interrupt_session(handle, execution_id, results[0] if results else None, interrupt)
    result = results[0]
    if interrupt is not None and interrupt.requested.is_set():
        return interrupt_session(handle, execution_id, result, interrupt)
    state = request(handle, "status", execution_id=execution_id)
    if interrupt is not None:
        interrupt.remember(state.get("execution", {}))
    if interrupt is not None and interrupt.requested.is_set():
        return interrupt_session(handle, execution_id, result, interrupt)
    if result["status"] in TERMINAL_EXECUTIONS:
        execution = result
    elif result["status"] in {"busy", "invalid_request", "session_limit", "invalid_session", "unauthorized"}:
        execution = {"status": "not_started", "execution_id": execution_id, "reason": result["status"]}
    else:
        execution = state.get("execution", {"status": "unknown", "execution_id": execution_id})
        if execution["status"] == "not_started" and session_state(state) == "active":
            # A disconnected run handler can still accept the ID after this query.
            execution = {"status": "unknown", "execution_id": execution_id}
    return report_execution(execution, session_state(state), handle, execution_id)


def invoke(args, handle, command, interrupt):
    if args.check_service:
        config = load_config(args.config, args.allow_local_http)
        with httpx.Client(timeout=12, trust_env=False, follow_redirects=False) as client:
            response = client.get(config['url'] + '/health')
            response.raise_for_status()
            health = response.json()
        if health.get('status') != 'ok' or health.get('access') != 'anonymous':
            emit(status='incompatible_service', message='服务未启用匿名接入，请联系部署者升级服务。')
            return 2
        emit(status='ready', access='anonymous')
        return 0
    if handle:
        from .session import request
        if args.use_session:
            return use_session(handle, command, args.execution_timeout, interrupt)
        result = request(handle, "status" if args.session_status else "revoke",
                         **({"execution_id": args.execution_id} if args.execution_id else {}))
        emit(**result)
        return 0 if result["status"] in {"active", "revoked"} or (
            "execution" in result and session_state(result) in {"revoked", "revoking"}) else 2
    return run(args, interrupt=interrupt)


def main():
    parser = argparse.ArgumentParser(description="通知本人输入机密，并在本机内存中交给程序使用；不返回机密。")
    parser.add_argument("--config", type=Path, default=Path.home() / ".config/secret-request/client.json")
    parser.add_argument("--check-service", action="store_true", help="检查匿名中转服务连接，不创建申请或发送通知")
    parser.add_argument("--name", help="所需机密的名称，不要填写机密本身")
    parser.add_argument("--purpose", help="本次用途")
    parser.add_argument("--agent-name", help="申请 Agent 的显示名称（自行声明）")
    parser.add_argument("--fields-file", type=Path, help="非敏感 JSON 字段定义；提供后将整份字段值 JSON 交给程序")
    parser.add_argument("--env", help="传入子进程的环境变量名；不指定时通过标准输入传入原始 UTF-8 字节")
    parser.add_argument("--wait", type=int, default=600, choices=range(10, 1801), metavar="10..1800")
    parser.add_argument("--execution-timeout", type=int, default=300)
    parser.add_argument("--allow-local-http", action="store_true", help="仅用于 loopback 测试")
    parser.add_argument("--show-link", action="store_true", help="输出本次填写链接作为通知备用入口；链接持有者可填写或拒绝")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--use-session", metavar="HANDLE", help="复用本机任务会话，不再请求输入")
    mode.add_argument("--session-status", metavar="HANDLE", help="查看剩余时间和最近执行结果")
    mode.add_argument("--revoke-session", metavar="HANDLE", help="清除会话并停止仍在运行的程序")
    parser.add_argument("--execution-id", help="状态查询或撤销时关联指定执行，不使用此前结果替代")
    retention = parser.add_mutually_exclusive_group()
    retention.add_argument("--session-ttl", type=int, default=300, metavar="10..1800", help="会话空闲超时，默认300秒；执行结束后重新计时，状态查询不续期")
    retention.add_argument("--one-shot", action="store_true", help="一次性使用，不保留复用会话")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="-- 后跟已获授权的可执行程序和参数")
    args = parser.parse_args()
    if not 1 <= args.execution_timeout <= 3600:
        parser.error("execution timeout must be between 1 and 3600 seconds")
    if not 10 <= args.session_ttl <= 1800:
        parser.error("session ttl must be between 10 and 1800 seconds")
    handle = args.use_session or args.session_status or args.revoke_session
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if args.execution_id is not None and (not (args.session_status or args.revoke_session) or
            not re.fullmatch(r"[a-f0-9]{32}", args.execution_id)):
        parser.error("--execution-id requires status/revoke and a 32-character execution ID")
    if handle:
        if args.check_service or args.name or args.purpose or args.env or args.one_shot or args.agent_name or args.fields_file or args.show_link:
            parser.error("session operations reuse the original purpose, directory and input channel")
        if args.use_session and not command:
            parser.error("--use-session requires a command")
        if not args.use_session and command:
            parser.error("status/revoke do not accept a command")
    elif args.check_service:
        if command or args.name or args.purpose:
            parser.error("--check-service does not create or execute a request")
    elif not args.name or not args.purpose:
        parser.error("new requests require --name and --purpose")
    if args.one_shot:
        args.session_ttl = 0
    interrupt = Interrupts()
    try:
        code = invoke(args, handle, command, interrupt)
    except KeyboardInterrupt:
        interrupt.requested.set()
        if interrupt.handle:
            code = interrupt_session(interrupt.handle, interrupt.execution_id, interrupt.known, interrupt)
        else:
            emit(status="interrupted", execution={"status": "not_started"}, session_state="not_created")
            code = 130
    except subprocess.TimeoutExpired:
        emit(status="execution_timeout")
        code = 3
    except Exception:
        # Never echo arguments, configuration, HTTP responses or secret-bearing exceptions.
        emit(status="failed", message="请求或执行失败，请检查服务、网络和程序配置。")
        code = 1
    finally:
        try:
            if interrupt.requested.is_set() and interrupt.handle and not interrupt.settled:
                code = interrupt_session(interrupt.handle, interrupt.execution_id, interrupt.known, interrupt)
        finally:
            interrupt.restore()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
