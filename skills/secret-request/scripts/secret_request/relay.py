"""Single-worker, memory-only relay with independent per-request capabilities."""
import asyncio
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parent
from .crypto import validate_envelope, validate_jwk
from .fields import validate_agent, validate_fields

HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"}
# Submit tokens are unpadded base64url: 32 bytes (256 bits, 43 chars) or 16 bytes (128 bits, 22 chars).
_TOKEN = re.compile(r"[A-Za-z0-9_-]{22}|[A-Za-z0-9_-]{43}")


@dataclass
class Settings:
    base_url: str
    max_requests: int = 128
    max_requests_per_ip: int = 8
    requests_per_minute: int = 20
    global_requests_per_minute: int = 120
    input_lookups_per_minute: int = 120
    allow_local_http: bool = False

    def __post_init__(self):
        parsed = urlsplit(self.base_url)
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1", "testserver"}
        if parsed.scheme != "https" and not (self.allow_local_http and local and parsed.scheme == "http"):
            raise ValueError("HTTPS required")
        if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
            raise ValueError("invalid service URL")
        self.base_url = self.base_url.rstrip("/")
        if any(type(v) is not int or not 1 <= v <= 1024 for v in
               (self.max_requests, self.max_requests_per_ip, self.requests_per_minute,
                self.global_requests_per_minute, self.input_lookups_per_minute)):
            raise ValueError("invalid request limit")


class CreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    purpose: str = Field(min_length=1, max_length=500)
    ttl_seconds: int = Field(default=600, ge=10, le=1800, strict=True)
    public_key: dict
    agent: str = "未注明 Agent"
    fields: list[dict] | None = None


@dataclass
class Entry:
    id: str
    source: str
    name: str
    purpose: str
    public_key: dict
    submit_hash: str
    receive_hash: str
    deadline: float
    expires_at: str
    agent: str
    fields: list[dict] | None
    created_at: str
    state: str = "pending"
    envelope: dict | None = None


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def bearer(request):
    value = request.headers.get("authorization", "")
    return value[7:] if value.startswith("Bearer ") else ""


def create_app(settings: Settings, clock=time.monotonic):
    entries, submit_index = {}, {}
    rates, input_rates, global_rate = {}, {}, deque()
    source_salt = secrets.token_bytes(32)
    lock = asyncio.Lock()
    # Input-lookup counters are independent of request purge/lookup so a malformed
    # or over-limit bearer never waits on the shared request lock.
    input_lock = threading.Lock()

    def expire_input_rates(now):
        for source, recent in list(input_rates.items()):
            while recent and recent[0] <= now - 60:
                recent.popleft()
            if not recent:
                input_rates.pop(source, None)

    def purge():
        now = clock()
        for source, recent in list(rates.items()):
            while recent and recent[0] <= now - 60:
                recent.popleft()
            if not recent:
                rates.pop(source, None)
        while global_rate and global_rate[0] <= now - 60:
            global_rate.popleft()
        for entry in list(entries.values()):
            if now >= entry.deadline and entry.state in {"pending", "submitted"}:
                entry.state, entry.envelope = "expired", None
            if now >= entry.deadline + 600:
                entries.pop(entry.id, None)
                if submit_index.get(entry.submit_hash) == entry.id:
                    submit_index.pop(entry.submit_hash, None)

    async def sweep():
        while True:
            await asyncio.sleep(5)
            with input_lock:
                expire_input_rates(clock())
            async with lock:
                purge()

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(sweep())
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            entries.clear()
            submit_index.clear()
            with input_lock:
                input_rates.clear()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.entries = entries
    app.state.submit_index = submit_index
    app.state.request_lock = lock

    @app.middleware("http")
    async def boundaries(request, call_next):
        response = None
        origin = request.headers.get("origin")
        if origin and origin != settings.base_url:
            response = JSONResponse({"error": "origin_not_allowed"}, status_code=403)
        elif request.method in {"POST", "PUT", "PATCH"}:
            if request.headers.get("content-type", "").split(";")[0] != "application/json":
                response = JSONResponse({"error": "json_required"}, status_code=415)
            else:
                chunks, size = [], 0
                try:
                    async with asyncio.timeout(15):
                        async for chunk in request.stream():
                            size += len(chunk)
                            if size > 100000:
                                response = JSONResponse({"error": "request_too_large"}, status_code=413)
                                break
                            chunks.append(chunk)
                except TimeoutError:
                    response = JSONResponse({"error": "request_timeout"}, status_code=408)
                if response is None:
                    request._body = b"".join(chunks)
        response = response if response is not None else await call_next(request)
        response.headers.update(HEADERS)
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, exc):
        return JSONResponse({"error": "invalid_request"}, status_code=422)

    def presented_token(request):
        token = bearer(request)
        # Reject before hashing so a huge Authorization header cannot be used as a work factor.
        if len(token) not in (22, 43) or _TOKEN.fullmatch(token) is None:
            return None
        return token

    def find(rid, request, role):
        purge()
        token = presented_token(request)
        entry = entries.get(rid)
        if token is None or entry is None or not hmac.compare_digest(digest(token), getattr(entry, role + "_hash")):
            raise HTTPException(404, "request_not_found")
        return entry

    def client_source(request):
        peer = request.client.host if request.client else "unknown"
        return hmac.new(source_salt, peer.encode(), hashlib.sha256).hexdigest()

    def allow_input_lookup(request):
        now = clock()
        source = client_source(request)
        with input_lock:
            expire_input_rates(now)
            recent = input_rates.get(source)
            if recent is None:
                if len(input_rates) >= settings.max_requests * 4:
                    raise HTTPException(429, "request_limit")
                recent = deque()
                input_rates[source] = recent
            if len(recent) >= settings.input_lookups_per_minute:
                raise HTTPException(429, "request_limit")
            recent.append(now)

    def lookup_submit(token):
        purge()
        hashed = digest(token)
        entry = entries.get(submit_index.get(hashed, ""))
        if entry is None or not hmac.compare_digest(hashed, entry.submit_hash):
            raise HTTPException(404, "request_not_found")
        return entry

    def public(entry):
        return {"id": entry.id, "name": entry.name, "purpose": entry.purpose,
                "expires_at": entry.expires_at, "remaining_seconds": max(0, entry.deadline - clock()),
                "state": entry.state, "public_key": entry.public_key, "agent": entry.agent,
                "fields": entry.fields, "created_at": entry.created_at}

    @app.get("/health")
    async def health():
        return {"status": "ok", "version": "0.3.0", "access": "anonymous"}

    @app.post("/api/requests", status_code=201)
    async def create(body: CreateBody, request: Request):
        # Use the actual ASGI peer, never an untrusted Forwarded/X-Forwarded-For header.
        peer = request.client.host if request.client else "unknown"
        source = hmac.new(source_salt, peer.encode(), hashlib.sha256).hexdigest()
        if not body.name.strip() or not body.purpose.strip() or any(ord(c) < 32 for c in body.name):
            raise HTTPException(422, "invalid_request")
        try:
            validate_jwk(body.public_key)
            agent, fields = validate_agent(body.agent), validate_fields(body.fields)
        except (ValueError, TypeError, KeyError):
            raise HTTPException(422, "invalid_request") from None
        async with lock:
            purge()
            active = [e for e in entries.values() if e.state in {"pending", "submitted"}]
            recent = rates.get(source, deque())
            if (len(active) >= settings.max_requests or len(entries) >= settings.max_requests * 4
                    or sum(e.source == source for e in active) >= settings.max_requests_per_ip
                    or len(recent) >= settings.requests_per_minute
                    or len(global_rate) >= settings.global_requests_per_minute
                    or (source not in rates and len(rates) >= settings.max_requests * 4)):
                raise HTTPException(429, "request_limit")
            # Deployed clients accept only /input/<id>#<43-char token>. The short form
            # is emitted only when the caller sends X-Secret-Request-Link: short.
            short = request.headers.get("x-secret-request-link") == "short"
            rid = submit = receive = submit_hash = None
            for _ in range(8):
                candidate_rid = secrets.token_urlsafe(18)
                # 16 bytes is 128 bits and encodes to 22 unpadded base64url characters.
                candidate_submit = secrets.token_urlsafe(16 if short else 32)
                candidate_receive = secrets.token_urlsafe(32)
                candidate_hash = digest(candidate_submit)
                if (candidate_rid not in entries and candidate_hash not in submit_index
                        and candidate_submit != candidate_receive
                        and candidate_hash != digest(candidate_receive)):
                    rid, submit, receive, submit_hash = (
                        candidate_rid, candidate_submit, candidate_receive, candidate_hash)
                    break
            if rid is None:
                raise HTTPException(503, "unavailable")
            entry = Entry(rid, source, body.name.strip(), body.purpose.strip(), body.public_key,
                          submit_hash, digest(receive), clock() + body.ttl_seconds,
                          datetime.fromtimestamp(time.time() + body.ttl_seconds, timezone.utc).isoformat(),
                          agent, fields, datetime.now(timezone.utc).isoformat())
            entries[rid] = entry
            submit_index[submit_hash] = rid
            rates[source] = recent
            recent.append(clock())
            global_rate.append(clock())
            link = settings.base_url + ("/i#" + submit if short else "/input/" + rid + "#" + submit)
            return {"id": rid, "receive_token": receive, "state": "pending",
                    "input_url": link, "remaining_seconds": body.ttl_seconds}

    @app.get("/api/input")
    async def input_session(request: Request):
        # Rate-limit and reject a malformed bearer before taking the request lock,
        # so neither waits behind purge or a lookup already in progress.
        token = presented_token(request)
        allow_input_lookup(request)
        if token is None:
            raise HTTPException(404, "request_not_found")
        async with lock:
            return public(lookup_submit(token))

    @app.get("/api/requests/{rid}")
    async def details(rid: str, request: Request):
        async with lock:
            return public(find(rid, request, "submit"))

    @app.get("/api/requests/{rid}/status")
    async def status(rid: str, request: Request):
        async with lock:
            return {"state": find(rid, request, "receive").state}

    @app.post("/api/requests/{rid}/submit")
    async def submit(rid: str, request: Request):
        try:
            envelope = validate_envelope(await request.json())
        except (ValueError, TypeError, KeyError):
            raise HTTPException(422, "invalid_envelope") from None
        async with lock:
            entry = find(rid, request, "submit")
            if entry.state != "pending":
                raise HTTPException(409, "request_unavailable")
            entry.state, entry.envelope = "submitted", envelope
            return {"state": entry.state}

    @app.post("/api/requests/{rid}/decline")
    async def decline(rid: str, request: Request):
        async with lock:
            entry = find(rid, request, "submit")
            if entry.state != "pending":
                raise HTTPException(409, "request_unavailable")
            entry.state = "declined"
            return {"state": entry.state}

    @app.post("/api/requests/{rid}/cancel")
    async def cancel(rid: str, request: Request):
        async with lock:
            entry = find(rid, request, "receive")
            if entry.state not in {"pending", "submitted"}:
                raise HTTPException(409, "request_unavailable")
            entry.state, entry.envelope = "cancelled", None
            return {"state": entry.state}

    @app.post("/api/requests/{rid}/consume")
    async def consume(rid: str, request: Request):
        async with lock:
            entry = find(rid, request, "receive")
            if entry.state != "submitted":
                raise HTTPException(409, "request_unavailable")
            entry.state = "consumed"
            envelope, entry.envelope = entry.envelope, None
            return {"envelope": envelope}

    @app.get("/")
    async def home():
        return FileResponse(ROOT / "web/home.html")

    @app.get("/i")
    async def short_page():
        return FileResponse(ROOT / "web/index.html")

    @app.get("/input/{rid}")
    async def page(rid: str = ""):
        return FileResponse(ROOT / "web/index.html")

    @app.get("/assets/{name}")
    async def asset(name: str):
        if name not in {"app.js", "style.css", "crypto.js", "home.css", "home.js", "theme.js"}:
            raise HTTPException(404)
        return FileResponse(ROOT / "web" / name)

    return app


def from_environment():
    if os.environ.get("SECRET_REQUEST_BASE_URL"):
        config = {"base_url": os.environ["SECRET_REQUEST_BASE_URL"]}
        for name in ("max_requests", "max_requests_per_ip", "requests_per_minute",
                     "global_requests_per_minute", "input_lookups_per_minute"):
            value = os.environ.get("SECRET_REQUEST_" + name.upper())
            if value is not None:
                config[name] = int(value)
    else:
        config = json.loads(Path(os.environ["SECRET_REQUEST_CONFIG"]).read_text(encoding="utf-8-sig"))
    return create_app(Settings(**config))
