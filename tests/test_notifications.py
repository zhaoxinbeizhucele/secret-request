import json
import pytest
import httpx
from secret_request import notifications as n


def message():
    return {'id':'a'*24, 'title':'Agent · 申请', 'body':'用于本次测试',
            'url':'https://relay.test/input/'+'a'*24+'#'+'b'*43, 'expires_in_seconds':600}


def test_native_and_hook_receive_only_this_input_link(monkeypatch):
    seen = []
    monkeypatch.setattr(n, 'local_notification', lambda m: (seen.append(m.copy()) or 'sent', None))
    def transport(request):
        data = json.loads(request.content)
        assert data['event'] == 'secret-request.created' and data['input_url'] == message()['url']
        assert 'receive_token' not in data and 'public_key' not in data
        return httpx.Response(204)
    config = {'url':'https://relay.test', 'notifications':{'local':True,
              'webhook':{'type':'generic', 'url':'https://hook.test/', 'headers':{}}}}
    created = {'id':'a'*24,'input_url':message()['url'],'remaining_seconds':600,'receive_token':'PRIVATE-RECEIVE'}
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        result = n.notify(config, created, '申请', '用于本次测试', 'Agent', hook_client=client)
        assert result == {'local':'sent','webhook':'sent'}
        result.close()
        result.close()
    assert seen == [message()]


def test_delivery_retry_keeps_request_and_never_follows_redirects():
    attempts = []
    def transport(request):
        attempts.append(json.loads(request.content))
        return httpx.Response(500 if len(attempts)==1 else 200, json={'errcode':0})
    hook = {'type':'wecom','url':'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=FAKE','headers':{}}
    with httpx.Client(transport=httpx.MockTransport(transport), follow_redirects=False) as client:
        assert n.webhook_notification(hook, message(), client) == 'sent'
    assert len(attempts)==2 and attempts[0]==attempts[1]
    assert message()['url'] in attempts[0]['text']['content']


@pytest.mark.parametrize('response', [httpx.Response(200,json={'errcode':45009}), httpx.Response(200,json=[]),
    httpx.Response(302,headers={'location':'https://evil.test'}), httpx.Response(401)])
def test_rejected_webhook_is_failed_without_exposing_content(response):
    hook = {'type':'wecom','url':'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=FAKE','headers':{}}
    with httpx.Client(transport=httpx.MockTransport(lambda _: response), follow_redirects=False) as client:
        assert n.webhook_notification(hook, message(), client)=='failed'


@pytest.mark.parametrize('value', [[], {'local':'yes'}, {'webhook':{'type':'unknown','url':'https://hook.test'}},
    {'webhook':{'type':'generic','url':'http://hook.test'}},
    {'webhook':{'type':'generic','url':'https://user:password@hook.test'}},
    {'webhook':{'type':'generic','url':'https://hook.test','headers':{'Authorization':'x\r\ny'}}},
    {'webhook':{'type':'wecom','url':'https://hook.test'}}])
def test_invalid_notification_configuration(value):
    with pytest.raises(ValueError): n.validate_notifications(value)


def test_webhook_url_can_come_from_environment(monkeypatch):
    monkeypatch.setenv('TEST_WEBHOOK','https://hook.test/FAKE')
    assert n.validate_notifications({'local':False,'webhook':{'type':'generic','url_env':'TEST_WEBHOOK'}})['webhook']['url']=='https://hook.test/FAKE'


def test_bad_relay_url_is_never_notified(monkeypatch):
    monkeypatch.setattr(n, 'local_notification', lambda _: pytest.fail('must not notify'))
    with pytest.raises(ValueError):
        n.notify({'url':'https://relay.test','notifications':{'local':True}},
                 {'id':'a'*24,'input_url':'https://evil.test/input/'+'a'*24+'#'+'b'*43,'remaining_seconds':600}, 'name','purpose','Agent')


def test_interrupted_webhook_retires_native_notification(monkeypatch):
    closed = []
    monkeypatch.setattr(n, 'local_notification', lambda _: ('sent', None))
    monkeypatch.setattr(n.Delivery, 'close', lambda self: closed.append(self.message['id']))
    def interrupted(*args): raise KeyboardInterrupt()
    monkeypatch.setattr(n, 'webhook_notification', interrupted)
    with pytest.raises(KeyboardInterrupt):
        n.notify({'url':'https://relay.test','notifications':{'local':True,'webhook':{}}},
                 {'id':'a'*24,'input_url':message()['url'],'remaining_seconds':600}, 'name','purpose','Agent')
    assert closed == ['a'*24]
