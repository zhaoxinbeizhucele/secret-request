"""Real client + real WebCrypto page against an isolated local Wrangler only.

No notifications, user profile, real credentials or remote Cloudflare operations.
Only non-sensitive aggregate outcomes are printed, including on failure.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import httpx
from playwright.sync_api import sync_playwright
from secret_request.client import run
from secret_request.crypto import new_key, public_jwk


def launch(p):
    for options in ({}, {'channel':'msedge'}, {'channel':'chrome'}):
        try:
            return p.chromium.launch(headless=True, **options)
        except Exception:
            pass
    raise RuntimeError('Headless Chromium unavailable')


def main():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    with tempfile.TemporaryDirectory(prefix='secret-request-worker-e2e-') as folder:
        temp = Path(folder)
        environment = {k:v for k,v in os.environ.items() if k not in {'CLOUDFLARE_API_TOKEN','CLOUDFLARE_ACCOUNT_ID','CLOUDFLARE_API_KEY','CLOUDFLARE_EMAIL'}}
        environment['WRANGLER_SEND_METRICS'] = 'false'
        environment['CI'] = 'true'
        job = None
        if os.name == 'nt':
            from secret_request.windows_job import Job
            job = Job()
        process = subprocess.Popen(['node', str(ROOT/'node_modules/wrangler/bin/wrangler.js'),
            'dev', '--local', '--config', str(ROOT/'wrangler.local.jsonc'), '--port', str(port),
            '--var', 'BASE_URL:'+base, '--persist-to', str(temp/'state')],
            cwd=ROOT, env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=0x08000004 if os.name == 'nt' else 0, start_new_session=os.name != 'nt')
        try:
            if job:
                job.start(process)
            with httpx.Client(base_url=base, trust_env=False, timeout=3) as http:
                deadline = time.monotonic()+60
                while time.monotonic()<deadline:
                    if process.poll() is not None:
                        raise RuntimeError('Local Wrangler stopped')
                    try:
                        if http.get('/health').status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(.2)
                else:
                    raise RuntimeError('Local Wrangler not ready')
                with sync_playwright() as p:
                    browser = launch(p)
                    try:
                        context = browser.new_context()
                        page = context.new_page()
                        page.add_init_script('window.close = () => {};')
                        errors = []
                        page.on('pageerror', lambda _: errors.append(True))
                        config = temp/'client.json'
                        config.write_text(json.dumps({'url':base,'notifications':{'local':False}}), encoding='utf-8')
                        fields = temp/'fields.json'
                        fields.write_text(json.dumps([{'id':'password','label':'Password','type':'password'}]), encoding='utf-8')
                        marker = temp/'consumer-ok'
                        code = "import json,sys,pathlib; v=json.loads(sys.stdin.read()); assert v=={'password':'FAKE-WORKER-E2E'}; pathlib.Path(sys.argv[1]).write_text('ok')"
                        args = SimpleNamespace(config=config, allow_local_http=False, command=[sys.executable,'-I','-c',code,str(marker)],
                            env=None, name='Synthetic E2E', purpose='Local test only', agent_name='E2E', fields_file=fields,
                            wait=30, execution_timeout=10, session_ttl=0, one_shot=True, show_link=False)
                        created = []
                        def submit(c):
                            created.append(c)
                            page.goto(c['input_url'])
                            page.locator('#field-password').fill('FAKE-WORKER-E2E')
                            page.locator('#submit').click()
                            page.locator('#close-hint').wait_for(state='visible')
                        with contextlib.redirect_stdout(io.StringIO()):
                            result = run(args, on_created=submit)
                        assert result == 0 and marker.read_text() == 'ok' and not errors
                        c = created[0]
                        receive = {'Authorization':'Bearer '+c['receive_token']}
                        assert http.post(f"/api/requests/{c['id']}/consume",headers=receive,json={}).status_code == 409
                        assert http.get(f"/api/requests/{c['id']}/status",headers=receive).json()['state'] == 'consumed'
                        def new_request(ttl):
                            r = http.post('/api/requests', json={'name':'Synthetic','purpose':'Local only','public_key':public_jwk(new_key()),'ttl_seconds':ttl})
                            assert r.status_code == 201
                            return r.json()
                        # Real page submission followed by cancellation must make
                        # the ciphertext irretrievable to the receive capability.
                        c = new_request(60)
                        page.goto(c['input_url']); page.locator('#secret').fill('FAKE-CANCEL-E2E')
                        page.locator('#submit').click(); page.locator('#close-hint').wait_for(state='visible')
                        receive = {'Authorization':'Bearer '+c['receive_token']}
                        assert http.post(f"/api/requests/{c['id']}/cancel",headers=receive,json={}).json()['state'] == 'cancelled'
                        assert http.post(f"/api/requests/{c['id']}/consume",headers=receive,json={}).status_code == 409
                        c = new_request(10)
                        page.goto(c['input_url']); page.locator('#secret').fill('FAKE-EXPIRE-E2E')
                        page.locator('#submit').click(); page.locator('#close-hint').wait_for(state='visible')
                        time.sleep(10.1)
                        receive = {'Authorization':'Bearer '+c['receive_token']}
                        assert http.get(f"/api/requests/{c['id']}/status",headers=receive).json()['state'] == 'expired'
                        assert http.post(f"/api/requests/{c['id']}/consume",headers=receive,json={}).status_code == 409
                        assert not errors
                        context.close()
                    finally:
                        browser.close()
        finally:
            if job:
                job.close()
            else:
                import signal
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            process.wait(timeout=15)
            # Windows releases workerd's SQLite handles asynchronously on exit.
            time.sleep(.5)
    print(json.dumps({'status':'passed','browser_webcrypto_flows':3,'client_decrypt_consumer':1,'duplicate_consume_rejected':1,'cancel_rejected_consume':1,'expiry_rejected_consume':1}))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # Never print browser/HTTP exception strings: they may contain fragments.
        print(json.dumps({'status':'failed','message':'Local Worker E2E failed; no capabilities logged.'}))
        raise SystemExit(1)
