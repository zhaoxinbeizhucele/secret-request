"""Synthetic end-to-end check against a configured relay; no real business writes."""
import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from secret_request.client import load_config, run
from secret_request.crypto import aad, encode, validate_jwk
from secret_request.session import request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, default=Path.home()/'.config/secret-request/client.json')
    args = parser.parse_args()
    config = load_config(args.config)
    if 'webhook' in config['notifications']:
        raise ValueError('This check must not send messages to a shared webhook')
    handle = None
    value = json.dumps({'username':' FAKE-用户 ', 'password':'FAKE-MVP-ONLY'}, ensure_ascii=False)
    with tempfile.TemporaryDirectory(prefix='secret-request-test-') as folder, httpx.Client(timeout=12,trust_env=False) as http:
        root = Path(folder)
        fields = root/'fields.json'
        fields.write_text(json.dumps([{'id':'username','label':'用户名','type':'text'},
                                     {'id':'password','label':'密码','type':'password'}]),encoding='utf-8')
        output = root/'digest'
        code = "import sys,pathlib,hashlib; data=sys.stdin.buffer.read(); pathlib.Path(sys.argv[1]).write_text(hashlib.sha256(data).hexdigest())"
        options = SimpleNamespace(config=args.config,allow_local_http=False,
            command=[sys.executable,'-c',code,str(output)],env=None,name='新版虚构申请验收',
            purpose='自动验收：仅使用虚构值，无需用户填写。',wait=30,execution_timeout=10,
            session_ttl=300,agent_name='Codex · 自动验收',fields_file=fields,show_link=False)
        def submit(created):
            rid = created['id']
            link = urlsplit(created['input_url'])
            token = link.fragment
            # Check the page the relay actually issued, plus every static dependency:
            # a healthy relay can still have unreadable packaged web files.
            for path, content_type in (
                (link.path or '/', 'text/html'),
                ('/assets/app.js', 'javascript'),
                ('/assets/crypto.js', 'javascript'),
                ('/assets/style.css', 'text/css'),
            ):
                resource = http.get(config['url'] + path)
                resource.raise_for_status()
                assert content_type in resource.headers['content-type'] and resource.content
            headers = {'Authorization':'Bearer '+token}
            details = http.get(config['url']+'/api/requests/'+rid,headers=headers)
            details.raise_for_status()
            public = validate_jwk(details.json()['public_key'])
            raw, nonce = os.urandom(32), os.urandom(12)
            envelope = {'v':1,'wrapped_key':encode(public.encrypt(raw,padding.OAEP(
                mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))),
                'nonce':encode(nonce),'ciphertext':encode(AESGCM(raw).encrypt(nonce,value.encode(),aad(rid)))}
            response = http.post(config['url']+'/api/requests/'+rid+'/submit',headers=headers,json=envelope)
            response.raise_for_status()
        capture = io.StringIO()
        try:
            with contextlib.redirect_stdout(capture):
                code = run(options, on_created=submit)
            events = [json.loads(line) for line in capture.getvalue().splitlines()]
            ready = next(e for e in events if e['status']=='session_ready')
            handle = ready['session']
            state = request(handle,'status')
            assert code == 0 and output.read_text() == hashlib.sha256(value.encode()).hexdigest()
            assert state['idle_timeout_seconds'] == 300 and state['last_result']['exit_code'] == 0
            assert request(handle,'revoke')['status']=='revoked'
            assert request(handle,'status')['status']=='session_unavailable'
            print(json.dumps({'success':True,'input_page_and_assets':True,'multi_field_decrypt_and_execution':True,
                'idle_timeout_seconds':300,'revoke_and_process_exit':True,
                'notifications':events[0]['notifications']},ensure_ascii=False))
        finally:
            if handle: request(handle,'revoke')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('{"success":false}')
        raise SystemExit(1)
