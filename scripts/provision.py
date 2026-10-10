"""Create anonymous relay settings. Clients need only the service URL."""
import argparse
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlsplit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    url = urlsplit(args.url)
    if (url.scheme != 'https' or not url.hostname or url.username or url.password
            or url.query or url.fragment or url.path not in {'','/'}):
        parser.error('An HTTPS origin is required')
    output = args.output.resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    if os.name == 'nt':
        subprocess.run(['icacls',str(output),'/inheritance:r','/grant:r',
                        os.environ['USERDOMAIN']+'\\'+os.environ['USERNAME']+':(OI)(CI)F',
                        'SYSTEM:(OI)(CI)F'], check=True, stdout=subprocess.DEVNULL)
    base = args.url.rstrip('/')
    def write(path, value):
        # The relay settings contain only the public URL and limits. The non-root
        # container user must be able to read a root-created bind-mounted file.
        with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o644),'w',encoding='utf-8') as file:
            json.dump(value,file,ensure_ascii=False,indent=2)
        if os.name != 'nt':
            path.chmod(0o644)
    write(output/'relay.json', {'base_url':base})
    print('Anonymous relay configuration generated. Share the service URL with users.')


if __name__ == '__main__':
    main()
