"""Explicit release inputs. Unknown files never enter an archive."""
from pathlib import Path

MODULES = ('__init__.py', 'client.py', 'crypto.py', 'fields.py', 'notifications.py',
           'session.py', 'windows_job.py', 'relay.py', 'server.py')
WEB_FILES = ('index.html', 'app.js', 'crypto.js', 'style.css', 'home.html', 'home.css', 'home.js')


def checked(root, names):
    root = root.resolve()
    for name in names:
        path = root/name
        relative = Path(name)
        if any((root/parent).is_symlink() for parent in (relative, *relative.parents)):
            raise ValueError('Distribution inputs must not contain symlinks')
        if not path.is_file() or not path.resolve().is_relative_to(root):
            raise ValueError('Missing or unsafe distribution input: ' + name)
        yield path


def server_files(root):
    names = ['secret_request/'+name for name in MODULES]
    names += ['secret_request/web/'+name for name in WEB_FILES]
    names += ['deploy/'+name for name in ('Dockerfile', 'compose.yaml', 'compose.public.yaml', 'compose.proxy.yaml', 'Caddyfile', 'nginx.conf.example', 'public.env.example')]
    names += ['requirements.txt', 'constraints.txt', '.dockerignore']
    return checked(root, names)


def client_files(root):
    names = ['SKILL.md', 'references/setup.md', 'references/troubleshooting.md',
             'scripts/install.py', 'scripts/install.ps1', 'scripts/setup_wecom.py', 'scripts/build_native.py', 'scripts/secret_request_cli.py',
             'scripts/secret_request_server.py', 'scripts/requirements.txt', 'scripts/constraints.txt']
    names += ['scripts/secret_request/'+name for name in MODULES]
    names += ['scripts/secret_request/web/'+name for name in WEB_FILES]
    names += ['scripts/native-source/windows/'+name for name in ('Program.cs', 'SecretRequest.Notify.csproj', 'app.manifest')]
    names += ['scripts/native-source/macos/'+name for name in ('Notification.swift', 'Info.plist')]
    for name in ('scripts/secret_request/native/windows/SecretRequest.Notify.exe',
                 'scripts/secret_request/native/macos/SecretRequestNotify.app/Contents/Info.plist',
                 'scripts/secret_request/native/macos/SecretRequestNotify.app/Contents/MacOS/SecretRequestNotify'):
        if (root/name).exists():
            names.append(name)
    return checked(root, names)
