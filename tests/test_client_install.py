"""Device configuration import must remain private and never replace existing credentials."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


BUNDLE = Path(__file__).resolve().parents[1]/'skills/secret-request'
SCRIPTS = BUNDLE/'scripts'
spec = importlib.util.spec_from_file_location('client_installer', SCRIPTS/'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def configuration(token='FAKE-DEVICE-ONLY-'+'a'*32):
    return {'url':'https://relay.example', 'request_token':token, 'notifications':{'local':False}}


def write_config(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')
    return path


def test_import_and_repeat_preserve_exact_device_config(tmp_path):
    source = write_config(tmp_path/'device.json', configuration())
    target = tmp_path/'private configuration/client.json'
    assert installer.install_configuration(source, target, sys.executable, SCRIPTS)
    assert target.read_bytes() == source.read_bytes()
    assert not installer.install_configuration(source, target, sys.executable, SCRIPTS)
    assert not list(target.parent.glob('.client-*'))
    if os.name != 'nt':
        assert target.stat().st_mode & 0o777 == 0o600
        assert target.parent.stat().st_mode & 0o777 == 0o700


def test_import_never_overwrites_another_device(tmp_path):
    source = write_config(tmp_path/'device.json', configuration())
    target = write_config(tmp_path/'client.json', configuration('FAKE-EXISTING-'+'b'*32))
    before = target.read_bytes()
    with pytest.raises(ValueError, match='not overwritten'):
        installer.install_configuration(source, target, sys.executable, SCRIPTS)
    assert target.read_bytes() == before


@pytest.mark.parametrize('value', [
    {'url':'http://relay.example','request_token':'FAKE-DEVICE-'+'a'*32},
    {'url':'https://relay.example','request_token':'short'},
    {'url':'https://relay.example','request_token':'FAKE-DEVICE-'+'a'*32,'reviewer_token':'FAKE-LEGACY'},
    ['FAKE-PRIVATE-INPUT'],
])
def test_invalid_config_is_not_published_or_disclosed(tmp_path, value, capsys):
    source = write_config(tmp_path/'device.json', value)
    target = tmp_path/'private/client.json'
    with pytest.raises(ValueError, match='Invalid client configuration') as error:
        installer.install_configuration(source, target, sys.executable, SCRIPTS)
    assert 'FAKE' not in str(error.value)
    assert capsys.readouterr() == ('','')
    assert not target.exists()
    assert not list(target.parent.glob('.client-*'))


def test_config_import_is_bounded(tmp_path):
    source = tmp_path/'large.json'
    source.write_bytes(b'a'*65537)
    target = tmp_path/'private/client.json'
    with pytest.raises(ValueError, match='64 KiB'):
        installer.install_configuration(source, target, sys.executable, SCRIPTS)
    assert not target.parent.exists()


def test_concurrent_import_keeps_one_whole_configuration(tmp_path):
    sources = [write_config(tmp_path/(str(index)+'.json'), configuration('FAKE-'+str(index)+'-'+'x'*32))
               for index in range(2)]
    target = tmp_path/'private/client.json'
    target.parent.mkdir()
    code = ('import importlib.util,sys; from pathlib import Path; '
            's=importlib.util.spec_from_file_location("installer",sys.argv[1]); '
            'm=importlib.util.module_from_spec(s); s.loader.exec_module(m); '
            'm.install_configuration(Path(sys.argv[2]),Path(sys.argv[3]),sys.executable,Path(sys.argv[4]))')
    processes = [subprocess.Popen([sys.executable,'-I','-c',code,str(SCRIPTS/'install.py'),
                                  str(source),str(target),str(SCRIPTS)],
                                 stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                 for source in sources]
    results = [process.communicate(timeout=30) for process in processes]
    assert sorted(process.returncode for process in processes) == [0,1]
    assert target.read_bytes() in [source.read_bytes() for source in sources]
    assert all(b'FAKE-' not in output+errors for output, errors in results)
    assert not list(target.parent.glob('.client-*'))
