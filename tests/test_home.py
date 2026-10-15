"""Public introduction stays separate from input and works on small screens."""
from pathlib import Path

from .test_browser_flow import browser_system


def test_home_navigation_copy_and_responsive_layout(browser_system):
    browser, base = browser_system
    context = browser.new_context(permissions=['clipboard-read', 'clipboard-write'])
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    artifacts = Path(__file__).resolve().parents[1]/'artifacts/public-service'
    artifacts.mkdir(parents=True, exist_ok=True)
    try:
        for width, height, name in ((1280, 900, 'home-desktop'), (390, 844, 'home-mobile'), (320, 700, 'home-small')):
            page.set_viewport_size({'width': width, 'height': height})
            page.goto(base)
            assert page.title() == 'Secret Request · 让机密走自己的通道'
            assert page.locator('#fields').count() == 0
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(artifacts/(name+'.png')), full_page=True)
        page.get_by_role('link', name='添加到你的 Agent').click()
        assert page.url.endswith('#start')
        page.get_by_role('button', name='复制安装命令').click()
        page.get_by_role('status').get_by_text('安装命令已复制。').wait_for()
        assert page.evaluate('navigator.clipboard.readText()') == 'npx skills add zhaoxinbeizhucele/secret-request -g'
        page.evaluate("Object.defineProperty(navigator, 'clipboard', {value: {writeText: async () => {throw new Error('denied')}}})")
        page.get_by_role('button', name='复制安装命令').click()
        page.get_by_role('status').get_by_text('无法访问剪贴板，请选中上方命令手动复制。').wait_for()
        page.emulate_media(color_scheme='dark')
        page.screenshot(path=str(artifacts/'home-dark.png'), full_page=True)
        assert not errors
    finally:
        context.close()
