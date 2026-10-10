"""Loopback-only browser acceptance with synthetic credentials and an isolated Edge."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import httpx
import pytest

playwright = pytest.importorskip('playwright.sync_api')
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def browser_system():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    env = {**os.environ, 'SECRET_REQUEST_TEST_PORT': str(port)}
    server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'tests.browser_server:app',
        '--host', '127.0.0.1', '--port', str(port), '--no-access-log', '--log-level', 'warning'],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                if httpx.get(base + '/health', trust_env=False).status_code == 200: break
            except httpx.HTTPError: pass
            time.sleep(.1)
        else: pytest.fail('Fixture service did not start')
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(channel='msedge', headless=True)
            try: yield browser, base
            finally: browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)


def create(base, multiple=True):
    return httpx.get(base + '/test/create', params={'multiple': str(multiple).lower()}, trust_env=False).json()


def fill(page):
    page.locator('#field-username').fill(' FAKE-用户 ')
    page.locator('#field-password').fill('FAKE-ONLY-TEST')
    page.locator('#field-key').fill('line1\nline2\n')


def check(base, rid):
    assert httpx.get(base + '/test/check/' + rid, trust_env=False).json() == {'state': 'consumed', 'matches': True}


def test_multi_fields_fallback_and_layout(browser_system):
    browser, base = browser_system
    context = browser.new_context(viewport={'width': 1280, 'height': 1000})
    page = context.new_page()
    errors = []; page.on('pageerror', lambda e: errors.append(str(e)))
    page.add_init_script('window.close = () => { window.closeAttempts = (window.closeAttempts || 0) + 1; };')
    created = create(base)
    page.goto(created['url'])
    page.locator('#field-password').wait_for(state='visible')
    assert page.locator('#agent').inner_text() == '测试 Agent（自行声明）'
    assert page.get_by_text('申请 Agent', exact=True).is_visible()
    assert page.locator('#device').count() == 0
    assert page.locator('#field-password').get_attribute('type') == 'password'
    page.locator('#submit').click()  # required fields, no request yet
    assert page.evaluate('window.closeAttempts || 0') == 0
    page.get_by_role('button', name='显示密码', exact=True).click()
    assert page.locator('#field-password').get_attribute('type') == 'text'
    page.get_by_role('button', name='隐藏密码', exact=True).click()
    artifacts = ROOT / 'artifacts/mvp'; artifacts.mkdir(exist_ok=True)
    page.screenshot(path=str(artifacts/'form-desktop.png'), full_page=True)
    page.set_viewport_size({'width': 390, 'height': 844})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path=str(artifacts/'form-narrow.png'), full_page=True)
    page.emulate_media(color_scheme='dark')
    page.screenshot(path=str(artifacts/'form-dark.png'), full_page=True)
    fill(page)
    sent = []
    page.on('request', lambda r: sent.append(r.post_data) if r.url.endswith('/submit') else None)
    page.locator('#submit').click()
    page.locator('#close-hint').wait_for(state='visible')
    assert page.evaluate('window.closeAttempts') == 1
    assert all(page.locator('#field-' + field).input_value() == '' for field in ['username', 'password', 'key'])
    assert len(sent) == 1 and 'FAKE-ONLY-TEST' not in sent[0]
    check(base, created['id'])
    assert not errors
    context.close()


def test_script_opened_page_closes_on_submit(browser_system):
    browser, base = browser_system
    context = browser.new_context()
    opener = context.new_page(); opener.goto(base)
    created = create(base)
    with opener.expect_popup() as popup:
        opener.evaluate('(url) => window.open(url)', created['url'])
    page = popup.value
    fill(page)
    with page.expect_event('close'):
        page.locator('#submit').click()
    check(base, created['id'])
    context.close()


def test_retry_keeps_encrypted_fields_after_network_failure(browser_system):
    browser, base = browser_system
    context = browser.new_context()
    page = context.new_page()
    page.add_init_script('window.close = () => { window.didClose = true; };')
    created = create(base); page.goto(created['url']); fill(page)
    attempts = []
    def submit(route):
        attempts.append(route.request.post_data)
        if len(attempts) == 1: route.abort()
        else: route.continue_()
    page.route('**/submit', submit)
    page.locator('#submit').click()
    page.locator('#error').wait_for(state='visible')
    assert page.locator('#field-password').input_value() == ''
    assert not page.evaluate('window.didClose || false')
    page.locator('#submit').click()
    page.locator('#close-hint').wait_for(state='visible')
    assert len(attempts) == 2 and attempts[0] == attempts[1]
    check(base, created['id'])
    context.close()


def test_legacy_and_decline(browser_system):
    browser, base = browser_system
    context = browser.new_context()
    page = context.new_page(); page.add_init_script('window.close = () => {};')
    created = create(base, multiple=False); page.goto(created['url'])
    page.locator('#secret').fill('FAKE-ONLY-TEST'); page.locator('#submit').click()
    page.locator('#close-hint').wait_for(state='visible'); check(base, created['id'])
    declined = create(base); page.goto(declined['url'])
    page.locator('#decline').click()
    playwright.expect(page.locator('#status')).to_have_text('你已拒绝这次请求。')
    assert page.locator('#form').is_hidden() and page.locator('#close-hint').is_visible()
    assert '已拒绝并清空输入' in page.locator('#close-hint').inner_text()
    context.close()


def test_script_opened_page_closes_on_decline(browser_system):
    browser, base = browser_system
    context = browser.new_context()
    opener = context.new_page(); opener.goto(base)
    created = create(base)
    with opener.expect_popup() as popup:
        opener.evaluate('(url) => window.open(url)', created['url'])
    page = popup.value
    fill(page)
    with page.expect_event('close'):
        page.locator('#decline').click()
    # Reopening a completed link displays its state without closing the page.
    page = context.new_page(); page.goto(created['url'])
    playwright.expect(page.locator('#status')).to_have_text('你已拒绝这次请求。')
    assert page.locator('#form').is_hidden() and page.locator('#close-hint').is_hidden()
    context.close()


@pytest.mark.parametrize('lost_response', [False, True])
def test_decline_closes_only_after_confirmed_success(browser_system, lost_response):
    browser, base = browser_system
    context = browser.new_context()
    page = context.new_page()
    page.add_init_script('window.close = () => { window.closeAttempts = (window.closeAttempts || 0) + 1; };')
    created = create(base); page.goto(created['url']); fill(page)
    def interrupt(route):
        if lost_response:
            assert route.fetch().status == 200
        route.abort()
    page.route('**/decline', interrupt)
    page.locator('#decline').click()
    if not lost_response:
        page.locator('#error').wait_for(state='visible')
        assert page.evaluate('window.closeAttempts || 0') == 0
        assert page.locator('#form').is_visible()
        assert page.locator('#field-password').input_value() == 'FAKE-ONLY-TEST'
        page.unroute('**/decline', interrupt)
        page.locator('#decline').click()
    page.locator('#close-hint').wait_for(state='visible')
    assert page.evaluate('window.closeAttempts') == 1
    assert page.locator('#form').is_hidden()
    assert all(page.locator('#field-' + field).input_value() == '' for field in ['username', 'password', 'key'])
    assert '未提供机密' in page.locator('#close-hint').inner_text()
    context.close()

