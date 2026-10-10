"""Bundle the client-only runtime into the distributable skill. No config files."""
from pathlib import Path
import shutil

CLIENT_MODULES = ("__init__.py", "client.py", "crypto.py", "fields.py", "notifications.py", "session.py", "windows_job.py")


def build(root):
    target = root / "skills/secret-request/scripts/secret_request"
    target.mkdir(parents=True, exist_ok=True)
    for name in CLIENT_MODULES:
        shutil.copyfile(root / "secret_request" / name, target / name)
    for name in ("windows", "macos"):
        source = root/name
        destination = target.parent/'native-source'/name
        destination.mkdir(parents=True, exist_ok=True)
        names = ('Program.cs','SecretRequest.Notify.csproj','app.manifest') if name == 'windows' else ('Notification.swift','Info.plist')
        for file in names:
            shutil.copyfile(source/file, destination/file)
    shutil.copyfile(root/'scripts/build_native.py', target.parent/'build_native.py')
    if (root/'secret_request/native').is_dir():
        shutil.copytree(root/'secret_request/native', target/'native', dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('*.pdb','*.dSYM','__pycache__'))


if __name__ == "__main__":
    build(Path(__file__).resolve().parents[1])
    print("Client runtime bundled into skill scripts; no credentials included.")
