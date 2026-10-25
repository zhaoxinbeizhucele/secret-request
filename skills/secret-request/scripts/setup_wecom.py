"""Bootstrap WeCom using the selected Cloudflare Worker encrypted form."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import webbrowser

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from install import configure_client
from secret_request.client import emit, run
from secret_request.notifications import validate_notifications


def receive(config):
    """Consumer process: secret arrives only on stdin, never in argv/output."""
    try:
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            return 1
        value = json.loads(raw.decode('utf-8'))
        if not isinstance(value, dict) or set(value) != {'webhook'} or not isinstance(value['webhook'], str):
            return 1
        validate_notifications({'local':False,'webhook':{'type':'wecom','url':value['webhook']}})
        configure_client(None, config, sys.executable, SCRIPTS,
                         webhook_url=value['webhook'], webhook_type='wecom')
        return 0
    except Exception:
        # Validation and OS errors must not echo a webhook or raw input.
        return 1


def setup(config, *, wait=600, open_browser=True, on_created=None, service_url=None):
    if not config.is_file():
        raise ValueError('Initialize the client before configuring WeCom')
    base = service_url or json.loads(config.read_text(encoding='utf-8-sig'))['url']
    with tempfile.TemporaryDirectory(prefix='secret-request-setup-') as folder:
        root = Path(folder)
        relay_config = root/'client.json'
        relay_config.write_text(json.dumps({'url':base,'notifications':{'local':False}}),encoding='utf-8')
        fields = root/'fields.json'
        fields.write_text(json.dumps([{'id':'webhook','label':'企微机器人 Webhook 地址',
                                      'type':'password','required':True}],ensure_ascii=False),encoding='utf-8')
        options = SimpleNamespace(config=relay_config, allow_local_http=False,
            command=[sys.executable,'-I','-X','utf8',str(Path(__file__).resolve()),'--receive','--config',str(config)],
            env=None, agent_name='Secret Request · 本机配置', name='配置企微机器人',
            purpose='仅将机器人 Webhook 地址保存到发起电脑受保护的客户端配置，不发送群消息。完整地址不要发进聊天。',
            wait=wait, execution_timeout=30, session_ttl=0, one_shot=True, fields_file=fields, show_link=False)
        def opened(created):
            if on_created is not None:
                on_created(created)
                return
            launched = False
            if open_browser:
                try:
                    launched = bool(webbrowser.open(created['input_url']))
                except webbrowser.Error:
                    pass
            # Only the one-time filling capability, never a receive token.
            emit(status='wecom_setup_page', input_url=created['input_url'], browser_opened=launched)
        result = run(options, on_created=opened)
        if result == 130:
            emit(status='wecom_setup_interrupted', message='配置过程已中断；如果已经提交，请先核对配置，不能据此认定未保存。')
        else:
            emit(status='wecom_configured' if result == 0 else 'wecom_setup_not_saved',
                 message='机器人地址已保存到本机配置。' if result == 0 else '机器人地址未保存。拒绝或过期不会修改配置；提交失败时请检查地址格式及文件权限。')
        return result

def main():
    parser = argparse.ArgumentParser(description='Configure a WeCom webhook without putting it in chat or command arguments')
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--wait', type=int, default=600)
    parser.add_argument('--no-open', action='store_true', help='Show the filling link instead of opening a browser')
    parser.add_argument('--receive', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 10 <= args.wait <= 1800:
        parser.error('Wait must be between 10 and 1800 seconds')
    if args.receive:
        return receive(args.config)
    service = json.loads(args.config.read_text(encoding='utf-8-sig'))['url']
    return setup(args.config.resolve(), wait=args.wait, open_browser=not args.no_open, service_url=service)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        emit(status='wecom_setup_interrupted', message='如果已经提交，请先核对配置，不能据此认定未保存。')
        raise SystemExit(130)
    except Exception:
        emit(status='wecom_setup_failed')
        raise SystemExit(1)
