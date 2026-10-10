"""Package project deployment files, excluding credentials and test-only endpoints."""
from pathlib import Path
import tarfile

root=Path(__file__).resolve().parents[1]
artifacts=root/"artifacts";artifacts.mkdir(exist_ok=True)
with tarfile.open(artifacts/"server.tar.gz","w:gz") as archive:
    for name in ("secret_request","deploy","requirements.txt","constraints.txt",".dockerignore"):
        path=root/name
        if path.is_file():archive.add(path,arcname=name)
        else:
            for child in path.rglob("*"):
                if child.is_file() and "__pycache__" not in child.parts and "native" not in child.parts:archive.add(child,arcname=str(child.relative_to(root)))
print("Server deployment archive ready.")
