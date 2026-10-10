"""Create fresh device credentials. Never overwrite or print credentials."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
from urllib.parse import urlsplit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', required=True)
    parser.add_argument('--device', action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    url = urlsplit(args.url)
    if (url.scheme != 'https' or not url.hostname or url.username or url.password
            or url.query or url.fragment or url.path not in {'','/'}):
        parser.error('An HTTPS origin is required')
    if len(set(args.device)) != len(args.device) or any(not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', d) for d in args.device):
        parser.error('Device names must be unique letters, numbers, underscore or hyphen')
    output = args.output.resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    if os.name == 'nt':
        subprocess.run(['icacls',str(output),'/inheritance:r','/grant:r',
                        os.environ['USERDOMAIN']+'\\'+os.environ['USERNAME']+':(OI)(CI)F',
                        'SYSTEM:(OI)(CI)F'], check=True, stdout=subprocess.DEVNULL)
    base = args.url.rstrip('/')
    clients = {name:{'token':secrets.token_urlsafe(32)} for name in args.device}
    def write(path, value):
        with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w',encoding='utf-8') as file:
            json.dump(value,file,ensure_ascii=False,indent=2)
    write(output/'relay.json', {'base_url':base, 'clients':clients})
    for name, client in clients.items():
        folder = output/name
        folder.mkdir(mode=0o700)
        write(folder/'client.json', {'url':base,'request_token':client['token'],'notifications':{'local':True}})
    print('Fresh configuration generated. Distribute only each device\'s own client.json securely.')


if __name__ == '__main__':
    main()
