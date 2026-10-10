"""Package project deployment files, excluding credentials and test-only endpoints."""
from pathlib import Path
import tarfile

def source_permissions(member):
    # Include directory entries explicitly: implicit parents inherit the
    # extractor's umask and can otherwise become inaccessible to container users.
    member.mode = 0o755 if member.isdir() else 0o644
    member.uid = member.gid = 0
    member.uname = member.gname = ""
    return member


def package(root, output):
    with tarfile.open(output, "w:gz") as archive:
        for name in ("secret_request", "deploy", "requirements.txt", "constraints.txt", ".dockerignore"):
            path = root / name
            candidates = [path, *sorted(path.rglob("*"))] if path.is_dir() else [path]
            for child in candidates:
                relative = child.relative_to(root)
                if "__pycache__" in relative.parts or "native" in relative.parts:
                    continue
                if child.is_symlink():
                    raise ValueError("Deployment source must not contain symlinks")
                if child.is_file() or child.is_dir():
                    archive.add(child, arcname=relative.as_posix(), recursive=False,
                                filter=source_permissions)


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    artifacts = root / "artifacts"
    artifacts.mkdir(exist_ok=True)
    package(root, artifacts / "server.tar.gz")
    print("Server deployment archive ready.")
