"""Bundle explicit runtime files, for the Cloudflare client."""
from pathlib import Path
import shutil

CLIENT_MODULES = ("__init__.py", "client.py", "crypto.py", "fields.py", "notifications.py", "session.py", "windows_job.py")


def build(root):
    target = root / "skills/secret-request/scripts/secret_request"
    target.mkdir(parents=True, exist_ok=True)
    for name in CLIENT_MODULES:
        shutil.copyfile(root / "secret_request" / name, target / name)
    shutil.copyfile(root/'requirements.txt', target.parent/'requirements.txt')
    shutil.copyfile(root/'constraints.txt', target.parent/'constraints.txt')
    for name in ("windows", "macos"):
        source = root/name
        destination = target.parent/'native-source'/name
        destination.mkdir(parents=True, exist_ok=True)
        names = ('Program.cs','SecretRequest.Notify.csproj','app.manifest') if name == 'windows' else ('Notification.swift','Info.plist')
        for file in names:
            shutil.copyfile(source/file, destination/file)
    shutil.copyfile(root/'scripts/build_native.py', target.parent/'build_native.py')
    for name in ('windows/SecretRequest.Notify.exe',
                 'macos/SecretRequestNotify.app/Contents/Info.plist',
                 'macos/SecretRequestNotify.app/Contents/MacOS/SecretRequestNotify'):
        source = root/'secret_request/native'/name
        if source.is_file() and not source.is_symlink():
            destination = target/'native'/name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)


if __name__ == "__main__":
    build(Path(__file__).resolve().parents[1])
    print("Client runtime bundled into skill scripts; no credentials included.")
