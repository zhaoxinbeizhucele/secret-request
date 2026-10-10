"""Install a skill's isolated runtime and optionally import protected device configuration."""
import argparse
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile


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


def install_configuration(source, destination, python, scripts):
    with source.open('rb') as file:
        content = file.read(65537)
    if len(content) > 65536:
        raise ValueError('Configuration file exceeds 64 KiB')
    if destination.exists():
        if destination.read_bytes() != content:
            raise ValueError('Configuration already exists; it was not overwritten')
        return False
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
            raise ValueError('Invalid client configuration; nothing was imported')
        try:
            # Publish without replacing a file created concurrently by another installer.
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
    parser.add_argument('--config-file', type=Path, help='Import a device JSON file; never overwrite existing configuration')
    parser.add_argument('--config-directory', type=Path, help='Configuration directory; defaults to ~/.config/secret-request')
    args = parser.parse_args()
    if sys.version_info < (3,12):
        parser.error('Python 3.12 or newer is required')
    scripts = Path(__file__).resolve().parent
    application = args.application_directory or (Path(os.environ['LOCALAPPDATA'])/'Programs/SecretRequest'
                    if os.name == 'nt' else Path.home()/'.local/share/secret-request')
    application = application.resolve()
    config_file = (args.config_directory or Path.home()/'.config/secret-request').resolve()/'client.json'
    application.mkdir(parents=True, exist_ok=True)
    runtime = application/'runtime'
    python = runtime/('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not python.exists():
        subprocess.run([sys._base_executable,'-I','-m','venv',str(runtime)], check=True)
    subprocess.run([str(python),'-I','-m','pip','--disable-pip-version-check','install','--require-virtualenv',
                    '-r',str(scripts/'requirements.txt')], check=True)
    if args.build_notifier:
        subprocess.run([str(python),'-I',str(scripts/'build_native.py')], check=True)
    if args.config_file:
        imported = install_configuration(args.config_file.resolve(), config_file, python, scripts)
        print('Device configuration imported.' if imported else 'Existing device configuration retained.')
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
    if not config_file.exists():
        print('Before use, import your device configuration with --config-file <path>.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        # Subprocess/config contents can include capabilities; report only controlled failures.
        message = str(error) if isinstance(error, ValueError) else 'Client installation failed.'
        print(message, file=sys.stderr)
        raise SystemExit(1)
