"""Package project deployment files, excluding credentials and test-only endpoints."""
from pathlib import Path
import tarfile
import sys
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from .distribution import server_files
except ImportError:
    from distribution import server_files

def source_permissions(member):
    # Include directory entries explicitly: implicit parents inherit the
    # extractor's umask and can otherwise become inaccessible to container users.
    member.mode = 0o755 if member.isdir() else 0o644
    member.uid = member.gid = 0
    member.uname = member.gname = ""
    return member


def package(root, output):
    with tarfile.open(output, "w:gz") as archive:
        paths = list(server_files(root))
        parents = {p for path in paths for p in path.relative_to(root).parents if p != Path('.')}
        for relative in sorted(parents, key=lambda p: (len(p.parts), str(p))):
            archive.add(root/relative, arcname=relative.as_posix(), recursive=False, filter=source_permissions)
        for path in paths:
            archive.add(path, arcname=path.relative_to(root).as_posix(), recursive=False, filter=source_permissions)


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    artifacts = root / "artifacts"
    artifacts.mkdir(exist_ok=True)
    package(root, artifacts / "server.tar.gz")
    print("Server deployment archive ready.")
