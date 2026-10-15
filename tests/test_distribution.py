"""Configuration-shaped and arbitrary files never enter either distribution."""
from pathlib import Path
import shutil
import tarfile
import zipfile

import pytest

from scripts.package_deploy import package as server_package
from scripts.package_client import package as client_package
from scripts.extract_deploy import extract

ROOT = Path(__file__).resolve().parents[1]


def test_release_allowlists_exclude_unexpected_files(tmp_path):
    root = tmp_path/'checkout'
    shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns('.git', '.venv', 'artifacts', 'runtime', '__pycache__', '.pytest_cache', '.impeccable'))
    for name in ('secret_request/.env', 'secret_request/private.json', 'deploy/private.key',
                 'skills/secret-request/scripts/secret_request/.env', 'skills/secret-request/scripts/unexpected.py'):
        (root/name).write_text('FAKE-CONFIG-DO-NOT-SHIP')
    server, client = tmp_path/'server.tar.gz', tmp_path/'client.zip'
    server_package(root, server)
    client_package(root, client)
    with tarfile.open(server) as archive:
        assert not any(b'FAKE-CONFIG' in archive.extractfile(m).read() for m in archive if m.isfile())
    with zipfile.ZipFile(client) as archive:
        assert not any(b'FAKE-CONFIG' in archive.read(name) for name in archive.namelist())


def test_extractor_rejects_paths_links_and_existing_destination(tmp_path):
    archive = tmp_path/'malicious.tar'
    with tarfile.open(archive, 'w') as output:
        item = tarfile.TarInfo('../outside')
        output.addfile(item)
    with pytest.raises(tarfile.FilterError):
        extract(archive, tmp_path/'out')
    assert not (tmp_path/'outside').exists()
    with pytest.raises(FileExistsError):
        extract(archive, tmp_path/'out')
