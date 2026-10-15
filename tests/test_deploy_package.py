"""Packaged sources must remain readable under restrictive deployment umasks."""
import os
from pathlib import Path
import stat
import tarfile

from scripts.package_deploy import package
from scripts.extract_deploy import source_filter


def test_archive_has_readable_files_and_explicit_traversable_parents(tmp_path):
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "server.tar.gz"
    package(root, output)
    with tarfile.open(output) as archive:
        members = {member.name: member for member in archive.getmembers()}
        assert "secret_request/web/index.html" in members
        assert not any("native" in Path(name).parts or "__pycache__" in Path(name).parts
                       for name in members)
        for name, member in members.items():
            assert member.mode == (0o755 if member.isdir() else 0o644)
            for parent in Path(name).parents:
                if parent != Path("."):
                    assert members[parent.as_posix()].isdir()
        if os.name != "nt":
            destination = tmp_path / "extracted"
            previous = os.umask(0o077)
            try:
                archive.extractall(destination, filter=source_filter)
            finally:
                os.umask(previous)
            for name, member in members.items():
                mode = stat.S_IMODE((destination / name).stat().st_mode)
                assert mode & 0o005 == (0o005 if member.isdir() else 0o004)
