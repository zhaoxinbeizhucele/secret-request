"""Single-process relay entrypoints for local use and container deployment."""
import argparse
import os
import socket

import uvicorn

from .relay import Settings, create_app, from_environment


def main():
    parser = argparse.ArgumentParser(description="Start a memory-only Secret Request relay")
    parser.add_argument('--local', action='store_true', help='Loopback only; no Docker, domain or TLS needed')
    parser.add_argument('--port', type=int, default=8787)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('Port must be between 1 and 65535')
    host = '127.0.0.1' if args.local else '0.0.0.0'
    app = (create_app(Settings(f'http://127.0.0.1:{args.port}', allow_local_http=True))
           if args.local else from_environment())
    # Bind before announcing readiness, so an occupied port never looks successful.
    sock = socket.socket()
    try:
        sock.bind((host, args.port))
        sock.listen(128)
    except OSError:
        sock.close()
        parser.exit(1, 'Relay port unavailable; choose another --port.\n')
    if args.local:
        print(f'Local relay: http://127.0.0.1:{args.port} (this computer only; Ctrl+C stops it)', flush=True)
    # Proxy trust is opt-in; the public Compose relay has no published port and
    # receives only the sanitizing proxy on its dedicated network.
    trusted = '' if args.local else os.environ.get('FORWARDED_ALLOW_IPS', '')
    config = uvicorn.Config(app, host=host, port=args.port, workers=1,
                            proxy_headers=bool(trusted), forwarded_allow_ips=trusted,
                            access_log=False, log_level='warning', limit_concurrency=128,
                            timeout_keep_alive=5, timeout_graceful_shutdown=10)
    try:
        uvicorn.Server(config).run(sockets=[sock])
    finally:
        sock.close()


if __name__ == '__main__':
    main()
