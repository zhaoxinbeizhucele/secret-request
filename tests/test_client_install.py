"""First use needs a URL, not a pre-existing credential or configuration file."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]/'skills/secret-request/scripts'
spec = importlib.util.spec_from_file_location('client_installer', SCRIPTS/'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def configure(url, target, **options):
    return installer.configure_client(url, target, sys.executable, SCRIPTS, **options)


def test_new_user_initializes_with_only_url(tmp_path):
    target = tmp_path/'private configuration/client.json'
    assert configure('https://relay.example/', target)
    assert json.loads(target.read_text()) == {'url':'https://relay.example','notifications':{'local':True}}
    before = target.read_bytes()
    assert not configure(None, target)
    assert target.read_bytes() == before
    assert not list(target.parent.glob('.client-*'))
    if os.name != 'nt':
        assert target.stat().st_mode & 0o777 == 0o600
        assert target.parent.stat().st_mode & 0o777 == 0o700


def test_legacy_upgrade_preserves_notifications_and_removes_token(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('TEST_SECRET_REQUEST_HOOK','https://notify.example/hook')
    target = tmp_path/'client.json'
    notifications = {'local':False,'webhook':{'type':'generic','url_env':'TEST_SECRET_REQUEST_HOOK'}}
    target.write_text(json.dumps({'url':'https://relay.example','request_token':'FAKE-OLD-PRIVATE',
                                 'notifications':notifications}))
    assert configure(None, target)
    assert json.loads(target.read_text()) == {'url':'https://relay.example','notifications':notifications}
    assert capsys.readouterr() == ('','')


def test_another_service_is_not_overwritten(tmp_path):
    target = tmp_path/'client.json'
    configure('https://first.example', target)
    before = target.read_bytes()
    with pytest.raises(ValueError, match='not overwritten'):
        configure('https://other.example', target)
    assert target.read_bytes() == before


@pytest.mark.parametrize('url',['http://relay.example','https://user:FAKE-PRIVATE@relay.example',
                              'https://relay.example/path','https://relay.example/#FAKE-PRIVATE'])
def test_invalid_url_not_saved_or_disclosed(tmp_path, url, capsys):
    target = tmp_path/'private/client.json'
    with pytest.raises(ValueError, match='Invalid service URL') as error:
        configure(url, target)
    assert 'FAKE' not in str(error.value)
    assert capsys.readouterr() == ('','')
    assert not target.exists()
    assert not list(target.parent.glob('.client-*'))


def test_new_user_defaults_to_public_and_updates_preserve_service(tmp_path):
    target = tmp_path/'client.json'
    configure(None, target)
    assert json.loads(target.read_text())['url'] == installer.PUBLIC_URL
    assert installer.select_url(None, None, 8787, True) is None
    assert installer.select_url(None, None, 8787, False) == installer.PUBLIC_URL
    assert installer.select_url('local', None, 9876, False) == 'http://127.0.0.1:9876'
    with pytest.raises(ValueError):
        installer.select_url('custom', None, 8787, False)
    with pytest.raises(ValueError):
        installer.select_url('local', 'https://other.example', 8787, False)


def test_local_configuration_needs_no_test_override(tmp_path):
    target = tmp_path/'client.json'
    configure('http://127.0.0.1:9876', target)
    from secret_request.client import load_config
    assert load_config(target)['url'] == 'http://127.0.0.1:9876'


@pytest.mark.parametrize(('local','enabled'), [(None,True),(False,False),(True,True)])
def test_webhook_initialization_uses_existing_environment(tmp_path, monkeypatch, local, enabled):
    monkeypatch.setenv('TEST_SECRET_REQUEST_HOOK','https://notify.example/hook?key=FAKE-PRIVATE')
    target = tmp_path/'client.json'
    configure('https://relay.example',target,local=local,webhook_type='generic',webhook_env='TEST_SECRET_REQUEST_HOOK')
    assert json.loads(target.read_text())['notifications'] == {
        'local':enabled,'webhook':{'type':'generic','url_env':'TEST_SECRET_REQUEST_HOOK'}}
    assert 'FAKE-PRIVATE' not in target.read_text()


@pytest.mark.parametrize('enabled', [True,False])
def test_configuring_webhook_and_updating_preserves_local_choice(tmp_path, monkeypatch, enabled):
    monkeypatch.setenv('TEST_SECRET_REQUEST_HOOK','https://notify.example/hook')
    target = tmp_path/'client.json'
    configure(None,target,local=enabled)
    configure(None,target,webhook_type='generic',webhook_env='TEST_SECRET_REQUEST_HOOK')
    expected = json.loads(target.read_text())
    assert expected['notifications'] == {
        'local':enabled,'webhook':{'type':'generic','url_env':'TEST_SECRET_REQUEST_HOOK'}}
    assert not configure(None,target)
    assert json.loads(target.read_text()) == expected
    configure(None,target,local=not enabled)
    updated = json.loads(target.read_text())['notifications']
    assert updated['local'] is not enabled
    assert updated['webhook'] == expected['notifications']['webhook']


def test_oversized_existing_config_is_preserved(tmp_path):
    target = tmp_path/'client.json'
    target.write_bytes(b'a'*65537)
    with pytest.raises(ValueError, match='64 KiB'):
        configure('https://relay.example',target)
    assert target.stat().st_size == 65537


def test_concurrent_initialization_keeps_one_whole_configuration(tmp_path):
    target = tmp_path/'client.json'
    code = ('import importlib.util,sys; from pathlib import Path; '
            's=importlib.util.spec_from_file_location("installer",sys.argv[1]); '
            'm=importlib.util.module_from_spec(s); s.loader.exec_module(m); '
            'm.configure_client(sys.argv[2],Path(sys.argv[3]),sys.executable,Path(sys.argv[4]))')
    urls = ['https://first.example','https://second.example']
    processes = [subprocess.Popen([sys.executable,'-I','-c',code,str(SCRIPTS/'install.py'),
                                  url,str(target),str(SCRIPTS)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                 for url in urls]
    for process in processes:
        process.communicate(timeout=30)
    assert sorted(process.returncode for process in processes) == [0,1]
    assert json.loads(target.read_text())['url'] in urls
    assert not list(tmp_path.glob('.client-*'))


def test_concurrent_updates_preserve_both_notification_choices(tmp_path, monkeypatch):
    target = tmp_path/'client.json'
    configure('https://relay.example',target)
    monkeypatch.setenv('TEST_SECRET_REQUEST_HOOK','https://notify.example/hook')
    code = ('import importlib.util,json,sys; from pathlib import Path; '
            's=importlib.util.spec_from_file_location("installer",sys.argv[1]); '
            'm=importlib.util.module_from_spec(s); s.loader.exec_module(m); '
            'm.configure_client(None,Path(sys.argv[2]),sys.executable,Path(sys.argv[3]),**json.loads(sys.argv[4]))')
    choices = [{'local':False},{'webhook_type':'generic','webhook_env':'TEST_SECRET_REQUEST_HOOK'}]
    processes = [subprocess.Popen([sys.executable,'-I','-c',code,str(SCRIPTS/'install.py'),
                                  str(target),str(SCRIPTS),json.dumps(choice)],
                                 stdout=subprocess.PIPE,stderr=subprocess.PIPE) for choice in choices]
    for process in processes:
        process.communicate(timeout=30)
    assert [process.returncode for process in processes] == [0,0]
    assert json.loads(target.read_text())['notifications'] == {
        'local':False,'webhook':{'type':'generic','url_env':'TEST_SECRET_REQUEST_HOOK'}}
