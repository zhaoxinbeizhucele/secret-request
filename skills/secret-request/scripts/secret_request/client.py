"""Request, decrypt in memory and run. Never expose a 'print secret' command."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

import httpx

from .crypto import decrypt, new_key, public_jwk
from .fields import validate_agent, validate_fields, validate_values
from .notifications import input_url, notify, validate_notifications


def load_config(path: Path, allow_local_http=False) -> dict:
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict) or set(config) - {"url", "request_token", "notifications"}:
        raise ValueError("invalid client configuration")
    parts = urlsplit(config["url"])
    local = parts.hostname in {"localhost", "127.0.0.1", "::1", "testserver"}
    if parts.scheme != "https" and not (allow_local_http and local):
        raise ValueError("HTTPS required")
    if not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or parts.path not in {"", "/"}:
        raise ValueError("invalid service URL")
    if not isinstance(config["request_token"], str) or len(config["request_token"]) < 32:
        raise ValueError("invalid request access")
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


def execute(command: list[str], secret: str, env_name: str | None, timeout: float,
            *, cwd=None, cancelled=None) -> int:
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
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
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


def run(args, client=None, on_created=None) -> int:
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
        response = client.post(base + "/api/requests", headers={"Authorization": "Bearer " + config["request_token"]},
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
            response = client.get(base + f"/api/requests/{rid}/status", headers=headers)
            response.raise_for_status()
            state = response.json()["state"]
            if state == "submitted":
                response = client.post(base + f"/api/requests/{rid}/consume", headers=headers, json={})
                response.raise_for_status()
                consumed = True
                delivery.close()
                secret = decrypt(key, rid, response.json()["envelope"])
                try:
                    validate_values(secret, fields)
                    if session_ttl:
                        from .session import start_session
                        session = start_session(secret, args.env, session_ttl)
                        emit(status="session_ready", request_id=rid, **session)
                        secret = None
                        return use_session(session["session"], command, args.execution_timeout)
                    exit_code = execute(command, secret, args.env, args.execution_timeout)
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


def use_session(handle, command, timeout):
    from .session import request
    import uuid
    execution_id = uuid.uuid4().hex
    emit(status="execution_requested", execution_id=execution_id)
    result = request(handle, "run", command=command, timeout=timeout, execution_id=execution_id)
    emit(**result)
    if result["status"] == "completed":
        code = result["exit_code"]
        return code if 0 <= code <= 125 else 1
    return 3 if result["status"] == "execution_timeout" else 2


def main():
    parser = argparse.ArgumentParser(description="通知本人输入机密，并在本机内存中交给程序使用；不返回机密。")
    parser.add_argument("--config", type=Path, default=Path.home() / ".config/secret-request/client.json")
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
    if handle:
        if args.name or args.purpose or args.env or args.one_shot or args.agent_name or args.fields_file or args.show_link:
            parser.error("session operations reuse the original purpose, directory and input channel")
        if args.use_session and not command:
            parser.error("--use-session requires a command")
        if not args.use_session and command:
            parser.error("status/revoke do not accept a command")
    elif not args.name or not args.purpose:
        parser.error("new requests require --name and --purpose")
    if args.one_shot:
        args.session_ttl = 0
    try:
        if handle:
            from .session import request
            if args.use_session:
                return use_session(handle, command, args.execution_timeout)
            result = request(handle, "status" if args.session_status else "revoke")
            emit(**result)
            return 0 if result["status"] in {"active", "revoked"} else 2
        return run(args)
    except KeyboardInterrupt:
        emit(status="cancelled")
        return 130
    except subprocess.TimeoutExpired:
        emit(status="execution_timeout")
        return 3
    except Exception:
        # Never echo arguments, configuration, HTTP responses or secret-bearing exceptions.
        emit(status="failed", message="请求或执行失败，请检查服务、网络和程序配置。")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
