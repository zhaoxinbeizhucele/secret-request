"""Extract a trusted project release with explicit directory permissions.

Python's data filter deliberately discards directory modes. Reapply only the
known public-source mode while retaining its path/link safety checks.
"""
import argparse
from pathlib import Path
import tarfile


def source_filter(member, destination):
    member = tarfile.data_filter(member, destination)
    if not (member.isfile() or member.isdir()):
        raise ValueError('Only regular source files and directories are allowed')
    return member.replace(mode=0o755 if member.isdir() else 0o644)


def extract(archive_path, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    with tarfile.open(archive_path) as archive:
        archive.extractall(destination, filter=source_filter)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('archive', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    extract(args.archive, args.destination)
