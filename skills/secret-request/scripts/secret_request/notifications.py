"""Client-owned delivery. Never send receive capabilities or plaintext to a notifier."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

import httpx

NATIVE = Path(__file__).resolve().parent / "native"


def validate_notifications(value, allow_local_http=False):
    if value is None:
        return {"local": True}
    if not isinstance(value, dict) or set(value) - {"local", "webhook"}:
        raise ValueError("invalid notifications")
    if type(value.get("local", True)) is not bool:
        raise ValueError("invalid local notification setting")
    result = {"local": value.get("local", True)}
    hook = value.get("webhook")
    if hook is not None:
        if (not isinstance(hook, dict) or set(hook) - {"type", "url", "url_env", "headers"}
                or hook.get("type") not in {"wecom", "generic"}
                or bool(hook.get("url")) == bool(hook.get("url_env"))):
            raise ValueError("invalid webhook")
        url = hook.get("url")
        if hook.get("url_env"):
            if not isinstance(hook["url_env"], str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", hook["url_env"]):
                raise ValueError("invalid webhook environment")
            url = os.environ.get(hook["url_env"])
        if not isinstance(url, str):
            raise ValueError("webhook URL required")
        parts = urlsplit(url)
        local = parts.hostname in {"127.0.0.1", "localhost", "::1", "testserver"}
        if (not parts.hostname or parts.username or parts.password or parts.fragment
                or any(ord(c) <= 32 for c in url)
                or not (parts.scheme == "https" or (allow_local_http and local and parts.scheme == "http"))):
            raise ValueError("invalid webhook URL")
        headers = hook.get("headers", {})
        if (not isinstance(headers, dict) or len(headers) > 16
                or any(not isinstance(k, str) or not isinstance(v, str) or
                       not re.fullmatch(r"[A-Za-z0-9-]{1,64}", k) or any(c in v for c in "\r\n") or
                       k.lower() in {"host", "content-length", "content-type"} for k, v in headers.items())):
            raise ValueError("invalid webhook headers")
        if hook["type"] == "wecom" and (parts.hostname != "qyapi.weixin.qq.com" or parts.path != "/cgi-bin/webhook/send"):
            raise ValueError("invalid WeCom webhook")
        result["webhook"] = {"type": hook["type"], "url": url, "headers": headers}
    return result


def input_url(base, created):
    """A relay response must not turn a notification into an arbitrary URL launcher."""
    rid, url = created["id"], created["input_url"]
    target, origin = urlsplit(url), urlsplit(base)
    if (not re.fullmatch(r"[A-Za-z0-9_-]{24}", rid)
            or (target.scheme, target.hostname, target.port) != (origin.scheme, origin.hostname, origin.port)
            or target.username or target.password or target.path != "/input/" + rid or target.query
            or not re.fullmatch(r"[A-Za-z0-9_-]{43}", target.fragment)):
        raise ValueError("invalid input link")
    return url


def local_notification(message):
    if sys.platform == "win32":
        command = [str(NATIVE / "windows/SecretRequest.Notify.exe")]
    elif sys.platform == "darwin":
        command = [str(NATIVE / "macos/SecretRequestNotify.app/Contents/MacOS/SecretRequestNotify")]
    else:
        return "unsupported", None
    if sys.platform == "darwin":
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            process.stdin.write(json.dumps(message, ensure_ascii=False).encode("utf-8"))
            process.stdin.close()
            result = []
            reader = threading.Thread(target=lambda: result.append(process.stdout.readline(16)), daemon=True)
            reader.start()
            reader.join(30)  # First launch can require user notification permission.
            if result != [b"sent\n"]:
                raise OSError("notification unavailable")
            process.stdout.close()
            return "sent", process
        except BaseException:
            process.kill()
            process.wait(timeout=5)
            if process.stdout:
                process.stdout.close()
            raise
    result = subprocess.run(command, input=json.dumps(message, ensure_ascii=False).encode("utf-8"),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    return ("sent" if result.returncode == 0 else "failed"), None


class Delivery(dict):
    """Own only this request's native notification, and retire it with the request."""
    def __init__(self, message):
        super().__init__()
        self.message, self.process, self.local_attempted = message, None, False

    def close(self):
        if self.message is None:
            return
        try:
            if self.process:
                if self.process.poll() is None:
                    self.process.terminate()
                    self.process.wait(timeout=5)
            elif sys.platform == "win32" and self.local_attempted:
                subprocess.run([str(NATIVE / "windows/SecretRequest.Notify.exe"), "--clear"],
                               input=json.dumps(self.message).encode("utf-8"), timeout=5,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            if self.process and self.process.poll() is None:
                self.process.kill()
                self.process.wait(timeout=5)
        finally:
            self.message = None


def webhook_notification(hook, message, client=None):
    if hook["type"] == "wecom":
        # Plain text avoids user-provided labels becoming Markdown links.
        payload = {"msgtype": "text", "text": {"content": message["title"] + "\n" + message["body"] + "\n" + message["url"]}}
    else:
        payload = {"event": "secret-request.created", "request_id": message["id"],
                   "title": message["title"], "message": message["body"],
                   "input_url": message["url"], "expires_in_seconds": message["expires_in_seconds"]}
    owned = client is None
    client = client or httpx.Client(timeout=8, trust_env=False, follow_redirects=False)
    try:
        # Delivery retries reuse the SAME request and link. They never create another request.
        for attempt in range(2):
            try:
                response = client.post(hook["url"], json=payload, headers=hook["headers"])
                response.raise_for_status()
                if hook["type"] == "wecom":
                    result = response.json()
                    if not isinstance(result, dict) or type(result.get("errcode")) is not int or result["errcode"] != 0:
                        raise ValueError("webhook rejected")
                return "sent"
            except (httpx.HTTPError, ValueError):
                if not attempt:
                    time.sleep(0.25)
        return "failed"
    finally:
        if owned:
            client.close()


def notify(config, created, name, purpose, agent, *, hook_client=None):
    url = input_url(config["url"], created)
    message = {"id": created["id"], "title": agent + " · " + name,
               "body": purpose, "url": url, "expires_in_seconds": created["remaining_seconds"]}
    results = Delivery(message)
    settings = config["notifications"]
    try:
        if settings["local"]:
            results.local_attempted = True
            try:
                results["local"], results.process = local_notification(message)
            except (OSError, subprocess.SubprocessError):
                results["local"] = "failed"
        if "webhook" in settings:
            results["webhook"] = webhook_notification(settings["webhook"], message, hook_client)
        return results
    except BaseException:
        results.close()
        raise
