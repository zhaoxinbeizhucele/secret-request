"""Initialize an anonymous client from a service URL; no enrollment credentials."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

PUBLIC_URL = 'https://secret-request.eicai.cc'


def select_url(mode, url, port, exists):
    if mode == 'local':
        if url:
            raise ValueError('--mode local cannot be combined with --url')
        if not 1 <= port <= 65535:
            raise ValueError('Port must be between 1 and 65535')
        return f'http://127.0.0.1:{port}'
    if mode == 'public':
        if url:
            raise ValueError('--mode public cannot be combined with --url')
        return PUBLIC_URL
    if mode == 'custom' and not url:
        raise ValueError('--mode custom requires --url')
    return url or (None if exists else PUBLIC_URL)


def restrict_access(path):
    if os.name == 'nt':
        account = os.environ['USERDOMAIN'] + '\\' + os.environ['USERNAME']
        rights = ':(OI)(CI)F' if path.is_dir() else ':F'
        result = subprocess.run(['icacls', str(path), '/inheritance:r', '/grant:r',
                                 account + rights, '*S-1-5-18' + rights],
                                capture_output=True)
        if result.returncode:
            raise ValueError('Could not protect the configuration file')
    else:
        path.chmod(0o700 if path.is_dir() else 0o600)


@contextmanager
def configuration_lock(directory):
    if not directory.exists():
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        restrict_access(directory)
    # The empty lock file is persistent; the OS releases its lock even after a crash.
    path = directory/'.init.lock'
    with path.open('a+b') as handle:
        restrict_access(path)
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b'\0')
            handle.flush()
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def configure_client(url, destination, python, scripts, local=None, webhook_type='wecom', webhook_env=None):
    with configuration_lock(destination.parent):
        return _configure_client(url, destination, python, scripts, local, webhook_type, webhook_env)


def _configure_client(url, destination, python, scripts, local, webhook_type, webhook_env):
    previous = None
    config = {}
    if destination.exists():
        with destination.open('rb') as file:
            previous = file.read(65537)
        if len(previous) > 65536:
            raise ValueError('Configuration file exceeds 64 KiB')
        try:
            config = json.loads(previous.decode('utf-8-sig'))
        except (ValueError, UnicodeError):
            raise ValueError('Invalid existing client configuration') from None
        if not isinstance(config, dict) or set(config) - {'url', 'notifications', 'request_token'}:
            raise ValueError('Invalid existing client configuration')
        if not isinstance(config.get('url'), str):
            raise ValueError('Invalid existing service URL')
        if url and config.get('url', '').rstrip('/') != url.rstrip('/'):
            raise ValueError('Another service is configured; it was not overwritten')
        # Upgrade 0.2 without retaining or sending its obsolete enrollment credential.
        config.pop('request_token', None)
    if url:
        config['url'] = url.rstrip('/')
    if not config.get('url'):
        config['url'] = PUBLIC_URL
    notifications = config.setdefault('notifications', {'local': False})
    if not isinstance(notifications, dict):
        raise ValueError('Invalid existing notification configuration')
    if local is not None:
        notifications['local'] = local
    if webhook_env:
        notifications['webhook'] = {'type': webhook_type, 'url_env': webhook_env}
    content = json.dumps(config, ensure_ascii=False, indent=2).encode('utf-8')
    if not destination.parent.exists():
        destination.parent.mkdir(parents=True, mode=0o700)
        restrict_access(destination.parent)
    descriptor, name = tempfile.mkstemp(prefix='.client-', suffix='.json', dir=destination.parent)
    temporary = Path(name)
    try:
        os.close(descriptor)
        restrict_access(temporary)
        temporary.write_bytes(content)
        code = ('import sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); '
                'from secret_request.client import load_config; load_config(Path(sys.argv[2]))')
        result = subprocess.run([str(python), '-I', '-X', 'utf8', '-c', code,
                                 str(scripts), str(temporary)], capture_output=True)
        if result.returncode:
            raise ValueError('Invalid service URL or notification settings; configuration unchanged')
        if previous is not None:
            if destination.read_bytes() != previous:
                raise ValueError('Configuration changed during initialization; retry')
            if json.loads(previous.decode('utf-8-sig')) == config:
                return False
            os.replace(temporary, destination)
        else:
            try:
                os.link(temporary, destination)
            except FileExistsError:
                raise ValueError('Configuration already exists; it was not overwritten') from None
        return True
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--application-directory', type=Path)
    parser.add_argument('--build-notifier', action='store_true')
    parser.add_argument('--mode', choices=('public', 'local', 'custom'), help='Default: public for new installs, preserve existing service on updates')
    parser.add_argument('--url', help='Self-hosted HTTPS origin; loopback HTTP is allowed on this computer only')
    parser.add_argument('--port', type=int, default=8787, help='Local relay port for --mode local')
    parser.add_argument('--config-directory', type=Path, help='Configuration directory; defaults to ~/.config/secret-request')
    local = parser.add_mutually_exclusive_group()
    local.add_argument('--local-notification', dest='local', action='store_true', default=None)
    local.add_argument('--no-local-notification', dest='local', action='store_false')
    parser.add_argument('--webhook-type', choices=('wecom', 'generic'), default='wecom')
    parser.add_argument('--webhook-env', help='Name of an existing environment variable containing the webhook URL')
    args = parser.parse_args()
    if sys.version_info < (3,12):
        parser.error('Python 3.12 or newer is required')
    scripts = Path(__file__).resolve().parent
    application = args.application_directory or (Path(os.environ['LOCALAPPDATA'])/'Programs/SecretRequest'
                    if os.name == 'nt' else Path.home()/'.local/share/secret-request')
    application = application.resolve()
    config_file = (args.config_directory or Path.home()/'.config/secret-request').resolve()/'client.json'
    url = select_url(args.mode, args.url, args.port, config_file.exists())
    application.mkdir(parents=True, exist_ok=True)
    runtime = application/'runtime'
    python = runtime/('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not python.exists():
        subprocess.run([sys._base_executable,'-I','-m','venv',str(runtime)], check=True)
    subprocess.run([str(python),'-I','-m','pip','--disable-pip-version-check','install','--require-virtualenv',
                    '-r',str(scripts/'requirements.txt')], check=True)
    if args.build_notifier:
        subprocess.run([str(python),'-I',str(scripts/'build_native.py')], check=True)
    webhook_env = args.webhook_env
    if not webhook_env and not config_file.exists() and os.environ.get('SECRET_REQUEST_WEBHOOK'):
        webhook_env = 'SECRET_REQUEST_WEBHOOK'
    configured = configure_client(url, config_file, python, scripts, args.local,
                                  args.webhook_type, webhook_env)
    print('Client configuration saved.' if configured else 'Existing client configuration retained.')
    subprocess.run([str(python),'-I','-X','utf8',str(scripts/'secret_request_cli.py'),'--help'],
                   check=True, stdout=subprocess.DEVNULL)
    if os.name == 'nt':
        wrapper = application/'secret-request.cmd'
        command = '"'+str(python)+'" -I -X utf8 "'+str(scripts/'secret_request_cli.py')+'" --config "'+str(config_file)+'"'
        wrapper.write_text('@echo off\n'+command.replace('%','%%')+' %*\n',
                           encoding='utf-8')
    else:
        wrapper = application/'secret-request'
        wrapper.write_text('#!/bin/sh\nexec '+shlex.quote(str(python))+' -I -X utf8 '+
                           shlex.quote(str(scripts/'secret_request_cli.py'))+' --config '+shlex.quote(str(config_file))+' "$@"\n',encoding='utf-8')
        wrapper.chmod(0o700)
    print('Client installed: '+str(wrapper))
    if os.name == 'nt':
        server = application/'secret-request-server.cmd'
        command = '"'+str(python)+'" -I -X utf8 "'+str(scripts/'secret_request_server.py')+'" --local'
        server.write_text('@echo off\n'+command.replace('%','%%')+' %*\n', encoding='utf-8')
    else:
        server = application/'secret-request-server'
        server.write_text('#!/bin/sh\nexec '+shlex.quote(str(python))+' -I -X utf8 '+
                          shlex.quote(str(scripts/'secret_request_server.py'))+' --local "$@"\n', encoding='utf-8')
        server.chmod(0o700)
    if url and url.startswith('http://127.0.0.1:'):
        print('Start the local relay in a background tool session: '+str(server)+' --port '+str(args.port))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        # Subprocess/config contents can include capabilities; report only controlled failures.
        message = str(error) if isinstance(error, ValueError) else 'Client installation failed.'
        print(message, file=sys.stderr)
        raise SystemExit(1)
