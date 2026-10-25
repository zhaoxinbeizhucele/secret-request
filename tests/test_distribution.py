"""Configuration-shaped and arbitrary files never enter the client distribution."""
from pathlib import Path
import shutil
import zipfile

import pytest

from scripts.package_client import package as client_package

ROOT = Path(__file__).resolve().parents[1]


def test_release_allowlists_exclude_unexpected_files(tmp_path):
    root = tmp_path/'checkout'
    shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns('.git', '.venv', 'node_modules', '.wrangler', '.worker-build', '.e2e', 'artifacts', 'runtime', '__pycache__', '.pytest_cache', '.impeccable'))
    for name in ('secret_request/.env', 'secret_request/private.json',
                 'skills/secret-request/scripts/secret_request/.env', 'skills/secret-request/scripts/unexpected.py'):
        (root/name).write_text('FAKE-CONFIG-DO-NOT-SHIP')
    client = tmp_path/'client.zip'
    client_package(root, client)
    with zipfile.ZipFile(client) as archive:
        assert not any(b'FAKE-CONFIG' in archive.read(name) for name in archive.namelist())
