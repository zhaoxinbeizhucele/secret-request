import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import pytest
from secret_request.client import execute, run
from .conftest import auth
from .test_crypto import encrypt


@pytest.mark.parametrize('health,exit_code,status', [
    ({'status':'ok','access':'anonymous','version':'0.3.0'},0,'ready'),
    ({'status':'ok','version':'0.2.0'},2,'incompatible_service'),
])
def test_check_service_requires_anonymous_access_without_creating_requests(tmp_path,monkeypatch,capsys,health,exit_code,status):
    import httpx
    from secret_request import client as module
    config = tmp_path/'client.json'
    config.write_text(json.dumps({'url':'https://relay.example','notifications':{'local':False}}))
    calls = []
    def handle(request):
        calls.append((request.method,request.url.path))
        assert 'authorization' not in request.headers
        return httpx.Response(200,json=health)
    actual_client = httpx.Client
    monkeypatch.setattr(module.httpx,'Client',lambda **kwargs: actual_client(transport=httpx.MockTransport(handle),**kwargs))
    monkeypatch.setattr(sys,'argv',['secret-request','--config',str(config),'--check-service'])
    assert module.main() == exit_code
    assert json.loads(capsys.readouterr().out)['status'] == status
    assert calls == [('GET','/health')]

@pytest.mark.parametrize("channel", ["env", "stdin"])
def test_child_exact_value_and_no_output(tmp_path, capfd, channel):
    secret = " FAKE-测试🔒\nsecond line  "
    result = tmp_path/"digest.txt"
    code = "import os,sys,hashlib,pathlib; v=" + ("os.environ['REQUEST_TEST_SECRET'].encode('utf-8')" if channel=="env" else "sys.stdin.buffer.read()") + "; print(v); print(v,file=sys.stderr); pathlib.Path(sys.argv[1]).write_text(hashlib.sha256(v).hexdigest())"
    assert execute([sys.executable,"-c",code,str(result)], secret, "REQUEST_TEST_SECRET" if channel=="env" else None, 10) == 0
    assert result.read_text() == hashlib.sha256(secret.encode()).hexdigest()
    assert "REQUEST_TEST_SECRET" not in os.environ
    assert "FAKE" not in "".join(capfd.readouterr())

def test_timeout_kills_child_tree(tmp_path):
    child_pid = tmp_path/"pid.txt"
    code = "import subprocess,sys,time,pathlib; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)']); pathlib.Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(120)"
    with pytest.raises(subprocess.TimeoutExpired): execute([sys.executable,"-c",code,str(child_pid)],"fake",None,2)
    pid=int(child_pid.read_text())
    if os.name == "nt":
        result=subprocess.run(["tasklist","/FI",f"PID eq {pid}","/FO","CSV","/NH"],capture_output=True,text=True)
        assert f'"{pid}"' not in result.stdout
    else:
        with pytest.raises(ProcessLookupError): os.kill(pid,0)

def args(tmp_path, tokens, command):
    config=tmp_path/"client.json"; config.write_text(json.dumps({"url":"http://testserver","notifications":{"local":False}}))
    return argparse.Namespace(config=config, allow_local_http=True, command=command, env="REQUEST_TEST_SECRET", name="fake", purpose="test", wait=10, execution_timeout=10)

@pytest.mark.parametrize("session_ttl", [0, 30])
@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("channel", ["env", "stdin"])
def test_request_to_child_end_to_end(system,key,tmp_path,capfd,session_ttl,structured,channel):
    client,app,tokens,now=system
    output=tmp_path/"hash.txt"; secret="FAKE-ONLY-TEST"
    if structured: secret=json.dumps({"username":" FAKE-用户 ", "password":" fake🔒 ", "key":"first\nsecond\n"},ensure_ascii=False)
    code="import os,sys,pathlib,hashlib; v=" + ("os.environ['REQUEST_TEST_SECRET']" if channel=="env" else "sys.stdin.buffer.read().decode('utf-8')") + "; print(v.encode('utf-8')); pathlib.Path(sys.argv[1]).write_text(hashlib.sha256(v.encode()).hexdigest())"
    arguments=args(tmp_path,tokens,[sys.executable,"-c",code,str(output)])
    arguments.session_ttl = session_ttl
    arguments.env = "REQUEST_TEST_SECRET" if channel=="env" else None
    if structured:
        from .test_fields import FIELDS
        arguments.fields_file = tmp_path/'fields.json'
        arguments.fields_file.write_text(json.dumps(FIELDS), encoding='utf-8')
        arguments.agent_name = '测试 Agent'
    def approve(created):
        rid=created["id"]; entry=app.state.entries[rid]
        assert (entry.fields is not None) == structured
        if structured: assert entry.agent == '测试 Agent'
        assert ("空闲 30 秒" in entry.purpose) == bool(session_ttl)
        # The runner's generated key differs from the fixture: use its transmitted JWK.
        from secret_request.crypto import validate_jwk,encode,aad
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives import hashes
        raw=os.urandom(32); nonce=os.urandom(12)
        envelope={"v":1,"wrapped_key":encode(validate_jwk(entry.public_key).encrypt(raw,padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))),"nonce":encode(nonce),"ciphertext":encode(AESGCM(raw).encrypt(nonce,secret.encode(),aad(rid)))}
        assert client.post(f"/api/requests/{rid}/submit",json=envelope,headers=auth(created['input_url'].split('#')[1])).status_code==200
    assert run(arguments,client=client,on_created=approve)==0
    assert output.read_text()==hashlib.sha256(secret.encode()).hexdigest()
    captured="".join(capfd.readouterr()); assert secret not in captured and "completed" in captured
    if session_ttl:
        from secret_request.session import request
        ready = next(json.loads(line) for line in captured.splitlines() if '"session_ready"' in line)
        try:
            assert request(ready["session"], "status")["last_result"]["exit_code"] == 0
            assert len(app.state.entries) == 1
            assert all(entry.state == "consumed" and entry.envelope is None for entry in app.state.entries.values())
        finally:
            request(ready["session"], "revoke")

def test_decline_does_not_run_child(system,key,tmp_path):
    client,app,tokens,now=system
    output=tmp_path/"never"
    arguments=args(tmp_path,tokens,[sys.executable,"-c","import pathlib,sys; pathlib.Path(sys.argv[1]).touch()",str(output)])
    def decline(created):
        entry=app.state.entries[created["id"]]
        client.post(f"/api/requests/{entry.id}/decline",json={},headers=auth(created['input_url'].split('#')[1]))
    assert run(arguments,client=client,on_created=decline)==2
    assert not output.exists()

def test_failure_after_create_cancels_request(system,key,tmp_path):
    client,app,tokens,now=system
    def fail(created): raise RuntimeError("fake")
    with pytest.raises(RuntimeError): run(args(tmp_path,tokens,[sys.executable,"-c","pass"]),client=client,on_created=fail)
    assert all(entry.state=="cancelled" for entry in app.state.entries.values())

def test_missing_executable_does_not_prompt(system,key,tmp_path):
    client,app,tokens,now=system
    with pytest.raises(ValueError): run(args(tmp_path,tokens,["this-program-does-not-exist-123"]),client=client)
    assert not app.state.entries


def test_invalid_fields_do_not_prompt(system, tmp_path):
    client, app, tokens, now = system
    arguments = args(tmp_path, tokens, [sys.executable, '-c', 'pass'])
    arguments.fields_file = tmp_path/'fields.json'
    arguments.fields_file.write_text('[{"id":"password","label":"Password","type":"file"}]')
    with pytest.raises(ValueError): run(arguments, client=client)
    assert not app.state.entries


@pytest.mark.parametrize('value', ['{"username":"FAKE","password":"FAKE"}',
                                 '{"username":"FAKE","password":12,"key":""}'])
def test_malformed_values_never_start_consumer(system, tmp_path, capfd, value):
    from types import SimpleNamespace
    from secret_request.crypto import validate_jwk
    from .test_fields import FIELDS
    client, app, tokens, now = system
    marker = tmp_path/'must-not-run'
    arguments = args(tmp_path, tokens, [sys.executable, '-c', 'import pathlib,sys; pathlib.Path(sys.argv[1]).touch()', str(marker)])
    arguments.fields_file = tmp_path/'fields.json'
    arguments.fields_file.write_text(json.dumps(FIELDS))
    def approve(created):
        entry = app.state.entries[created['id']]
        key = SimpleNamespace(public_key=lambda: validate_jwk(entry.public_key))
        client.post(f'/api/requests/{entry.id}/submit', headers=auth(created['input_url'].split('#')[1]), json=encrypt(key, entry.id, value))
    with pytest.raises(ValueError): run(arguments, client=client, on_created=approve)
    assert not marker.exists() and 'FAKE' not in ''.join(capfd.readouterr())

def test_nonzero_child_result():
    assert execute([sys.executable,"-c","raise SystemExit(7)"],"fake",None,10)==7

def test_normal_exit_also_kills_background_descendants(tmp_path):
    pid_file=tmp_path/"background.pid"
    code="import subprocess,sys,pathlib; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); pathlib.Path(sys.argv[1]).write_text(str(p.pid))"
    assert execute([sys.executable,"-c",code,str(pid_file)],"fake","REQUEST_TEST_SECRET",10)==0
    pid=int(pid_file.read_text())
    time.sleep(.2)
    if os.name=="nt":
        result=subprocess.run(["tasklist","/FI",f"PID eq {pid}","/FO","CSV","/NH"],capture_output=True,text=True)
        assert f'"{pid}"' not in result.stdout
    else:
        with pytest.raises(ProcessLookupError):os.kill(pid,0)
