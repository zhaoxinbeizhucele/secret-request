"""First-use configuration needs no pre-existing webhook or notification channel."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from secret_request.crypto import aad, encode, validate_jwk

SCRIPTS = Path(__file__).resolve().parents[1]/'skills/secret-request/scripts'
spec = importlib.util.spec_from_file_location('wecom_setup', SCRIPTS/'setup_wecom.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)
FAKE = 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=FAKE-PRIVATE-SETUP'


def initial(tmp_path):
    config = tmp_path/'private/client.json'
    setup.configure_client('https://custom.example',config,sys.executable,SCRIPTS,local=True)
    return config


def submit(created, value):
    base = created['input_url'].split('/input/')[0]
    headers = {'Authorization':'Bearer '+created['input_url'].split('#')[1]}
    rid = created['id']
    with httpx.Client(trust_env=False,timeout=5) as client:
        details = client.get(base+'/api/requests/'+rid,headers=headers).json()
        raw, nonce = os.urandom(32), os.urandom(12)
        envelope = {'v':1,'wrapped_key':encode(validate_jwk(details['public_key']).encrypt(raw,padding.OAEP(
            mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))),
            'nonce':encode(nonce),'ciphertext':encode(AESGCM(raw).encrypt(nonce,json.dumps({'webhook':value}).encode(),aad(rid)))}
        client.post(base+'/api/requests/'+rid+'/submit',headers=headers,json=envelope).raise_for_status()


def test_local_encrypted_setup_saves_privately_and_preserves_service(tmp_path,capsys,monkeypatch):
    config = initial(tmp_path)
    monkeypatch.setattr(setup.webbrowser,'open',lambda *_: pytest.fail('test must not open user browser'))
    assert setup.setup(config,wait=10,open_browser=False,on_created=lambda c:submit(c,FAKE)) == 0
    value = json.loads(config.read_text())
    assert value['url']=='https://custom.example' and value['notifications']['local'] is True
    assert value['notifications']['webhook']=={'type':'wecom','url':FAKE}
    assert FAKE not in ''.join(capsys.readouterr())
    if os.name != 'nt':
        assert config.stat().st_mode & 0o777 == 0o600


def test_decline_keeps_existing_configuration(tmp_path,capsys):
    config = initial(tmp_path)
    before = config.read_bytes()
    def decline(created):
        base = created['input_url'].split('/input/')[0]
        httpx.post(base+'/api/requests/'+created['id']+'/decline',trust_env=False,
                   headers={'Authorization':'Bearer '+created['input_url'].split('#')[1]},json={}).raise_for_status()
    assert setup.setup(config,wait=10,open_browser=False,on_created=decline) == 2
    assert config.read_bytes() == before
    assert 'wecom_setup_not_saved' in capsys.readouterr().out


@pytest.mark.parametrize('value',[None,'https://untrusted.example/FAKE-PRIVATE','https://qyapi.weixin.qq.com/cgi-bin/webhook/send'])
def test_invalid_webhook_consumer_keeps_file_and_does_not_echo(tmp_path,value):
    config = initial(tmp_path)
    before = config.read_bytes()
    result = subprocess.run([sys.executable,'-I',str(SCRIPTS/'setup_wecom.py'),'--receive','--config',str(config)],
                            input=json.dumps({'webhook':value}).encode(),capture_output=True,timeout=10)
    assert result.returncode == 1
    assert result.stdout == result.stderr == b''
    assert config.read_bytes() == before


def test_actual_setup_entry_exposes_only_filling_capability(tmp_path):
    config = initial(tmp_path)
    process = subprocess.Popen([sys.executable,'-I',str(SCRIPTS/'setup_wecom.py'),
        '--config',str(config),'--wait','15','--no-open','--local'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    observed = []
    try:
        while True:
            line = process.stdout.readline()
            assert line, 'setup exited without a filling page'
            event = json.loads(line)
            observed.append(event)
            if event['status']=='wecom_setup_page':
                assert event['browser_opened'] is False and 'receive_token' not in event
                submit({'id':event['input_url'].split('/input/')[1].split('#')[0], 'input_url':event['input_url']},FAKE)
                break
        output, errors = process.communicate(timeout=15)
        assert process.returncode == 0 and b'wecom_configured' in output
        assert FAKE.encode() not in output+errors+json.dumps(observed).encode()
    finally:
        if process.poll() is None:
            process.terminate()
            process.communicate(timeout=5)


def test_interrupted_result_does_not_claim_a_committed_configuration_was_unsaved(tmp_path,monkeypatch,capsys):
    config = initial(tmp_path)
    def interrupted_after_write(*args, **kwargs):
        setup.configure_client(None,config,sys.executable,SCRIPTS,webhook_url=FAKE)
        return 130
    monkeypatch.setattr(setup,'run',interrupted_after_write)
    assert setup.setup(config,service_url='https://custom.example',open_browser=False) == 130
    assert json.loads(config.read_text())['notifications']['webhook']['url']==FAKE
    output = capsys.readouterr().out
    assert 'wecom_setup_interrupted' in output
    assert 'wecom_setup_not_saved' not in output and FAKE not in output
