"""A fresh deployment produces relay settings, never user enrollment files."""
import json
import os
from pathlib import Path
import subprocess
import sys

SCRIPT = Path(__file__).resolve().parents[1]/'scripts/provision.py'


def test_fresh_relay_needs_only_url(tmp_path):
    folder = tmp_path/'fresh relay'
    result = subprocess.run([sys.executable,'-I',str(SCRIPT),'--url','https://relay.example/',
                             '--output',str(folder)],capture_output=True)
    assert result.returncode == 0, result.stderr
    assert [path.name for path in folder.iterdir()] == ['relay.json']
    config = folder/'relay.json'
    assert json.loads(config.read_text()) == {'base_url':'https://relay.example'}
    if os.name != 'nt':
        assert config.stat().st_mode & 0o777 == 0o644


def test_provision_does_not_replace_existing_settings(tmp_path):
    config = tmp_path/'relay.json'
    config.write_text('{"base_url":"https://existing.example"}')
    before = config.read_bytes()
    result = subprocess.run([sys.executable,'-I',str(SCRIPT),'--url','https://other.example',
                             '--output',str(tmp_path)],capture_output=True)
    assert result.returncode != 0 and config.read_bytes() == before
