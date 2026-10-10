"""Build only the current platform's short-lived notification helper."""
from pathlib import Path
import shutil
import subprocess
import sys


def build(source, target):
    source, target = Path(source), Path(target)
    if sys.platform == 'win32':
        subprocess.run(['dotnet', 'publish', str(source/'windows/SecretRequest.Notify.csproj'),
                        '-c','Release','-r','win-x64','--self-contained','true',
                        '-p:PublishSingleFile=true','-p:EnableCompressionInSingleFile=true',
                        '-o',str(target/'windows')], check=True)
    elif sys.platform == 'darwin':
        bundle = target/'macos/SecretRequestNotify.app/Contents'
        (bundle/'MacOS').mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source/'macos/Info.plist', bundle/'Info.plist')
        subprocess.run(['swiftc', '-O', '-framework','AppKit','-framework','UserNotifications',
                        str(source/'macos/Notification.swift'), '-o',str(bundle/'MacOS/SecretRequestNotify')], check=True)
        subprocess.run(['codesign','--force','--sign','-',str(bundle.parent)], check=True)
    else:
        raise SystemExit('Native notifications support Windows and macOS. Use webhook on this platform.')


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    source = Path(__file__).resolve().parent/'native-source'
    build(source if source.is_dir() else root, root/'secret_request/native' if not source.is_dir()
          else Path(__file__).resolve().parent/'secret_request/native')
