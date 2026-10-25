"""The distributed local relay works without Docker or a repository import."""
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_copied_local_server_and_real_client_health(tmp_path):
    bundle = tmp_path/'copied skill'
    shutil.copytree(ROOT/'skills/secret-request', bundle, ignore=shutil.ignore_patterns('__pycache__'))
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    script = bundle/'scripts/secret_request_server.py'
    process = subprocess.Popen([sys.executable, '-I', str(script), '--local', '--port', str(port)],
                               cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        with httpx.Client(trust_env=False, timeout=1) as client:
            for _ in range(100):
                try:
                    if client.get(base+'/health').status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.1)
            else:
                pytest.fail('Copied local relay did not become healthy')
            assert '让机密走' in client.get(base).text
            assert client.get(base+'/assets/home.css').status_code == 200
            assert 'field-password' not in client.get(base).text
            assert client.get(base+'/input/fake').status_code == 200
            short_page = client.get(base+'/i')
            assert short_page.status_code == 200 and 'id="secret"' in short_page.text
            assert '/api/input' in client.get(base+'/assets/app.js').text
            assert "location.replace('/i'" in client.get(base+'/assets/home.js').text
            config = tmp_path/'client.json'
            config.write_text('{"url":"'+base+'","notifications":{"local":false}}')
            checked = subprocess.run([sys.executable, '-I', str(bundle/'scripts/secret_request_cli.py'),
                                      '--config', str(config), '--check-service'], capture_output=True, timeout=10)
            assert checked.returncode == 0 and b'ready' in checked.stdout
            duplicate = subprocess.run([sys.executable, '-I', str(script), '--local', '--port', str(port)], capture_output=True, timeout=10)
            assert duplicate.returncode != 0 and b'port unavailable' in duplicate.stderr
    finally:
        process.terminate()
        process.communicate(timeout=10)
