"""Manual theme switch: light / dark / system, shared and persisted across both pages."""
import httpx
import playwright.sync_api as playwright

from .test_browser_flow import browser_system, create

STORAGE_KEY = 'secret-request-theme'


def pages(base):
    return {'home': base + '/', 'input': create(base)['url']}


def theme(page):
    return page.evaluate('document.documentElement.getAttribute("data-theme")')


def background(page):
    return page.evaluate('getComputedStyle(document.body).backgroundColor')


def option(page, name):
    return page.get_by_role('radiogroup', name='界面主题').get_by_role('radio', name=name, exact=True)


def test_switch_persists_and_follows_system_on_both_pages(browser_system):
    browser, base = browser_system
    for name, url in pages(base).items():
        context = browser.new_context(color_scheme='light')
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(url)
        group = page.get_by_role('radiogroup', name='界面主题')
        playwright.expect(group).to_be_visible()
        # Default: follow the system, no override attribute.
        assert theme(page) is None
        playwright.expect(option(page, '跟随系统')).to_have_attribute('aria-checked', 'true')
        light_bg = background(page)

        option(page, '暗色').click()
        assert theme(page) == 'dark'
        playwright.expect(option(page, '暗色')).to_have_attribute('aria-checked', 'true')
        playwright.expect(option(page, '跟随系统')).to_have_attribute('aria-checked', 'false')
        dark_bg = background(page)
        assert dark_bg != light_bg
        assert page.evaluate(f'localStorage.getItem("{STORAGE_KEY}")') == 'dark'

        # Persisted, and applied while the system still prefers light.
        page.reload()
        assert theme(page) == 'dark' and background(page) == dark_bg
        playwright.expect(option(page, '暗色')).to_have_attribute('aria-checked', 'true')

        # Forced light wins over a dark system preference.
        option(page, '亮色').click()
        page.emulate_media(color_scheme='dark')
        assert theme(page) == 'light' and background(page) == light_bg

        # System removes the override, follows the OS live and clears storage.
        option(page, '跟随系统').click()
        assert theme(page) is None
        assert page.evaluate(f'localStorage.getItem("{STORAGE_KEY}")') is None
        assert background(page) == dark_bg
        page.emulate_media(color_scheme='light')
        assert background(page) == light_bg
        assert not errors, (name, errors)
        context.close()


def test_choice_is_shared_and_keyboard_operable(browser_system):
    browser, base = browser_system
    urls = pages(base)
    context = browser.new_context(color_scheme='light')
    page = context.new_page()
    page.goto(urls['home'])
    option(page, '跟随系统').focus()
    page.keyboard.press('Home')  # first option: light
    assert theme(page) == 'light'
    page.keyboard.press('ArrowRight')
    assert theme(page) == 'dark'
    focused = page.evaluate('document.activeElement.getAttribute("data-theme-choice")')
    assert focused == 'dark'
    # Roving tabindex: only the checked option is in the tab order.
    assert page.evaluate('[...document.querySelectorAll("[data-theme-choice]")].map(b => b.tabIndex)') == [-1, 0, -1]
    # Same key on the input page.
    page.goto(urls['input'])
    assert theme(page) == 'dark'
    playwright.expect(option(page, '暗色')).to_have_attribute('aria-checked', 'true')
    page.locator('#field-password').wait_for(state='visible')
    context.close()


def test_theme_applies_before_paint_without_loosening_csp(browser_system):
    browser, base = browser_system
    for url in pages(base).values():
        response = httpx.get(url, trust_env=False)
        assert "script-src 'self';" in response.headers['content-security-policy']
        assert "'unsafe-inline'" not in response.headers['content-security-policy']
        context = browser.new_context(color_scheme='light')
        context.add_init_script(f'localStorage.setItem("{STORAGE_KEY}", "dark")')
        # Record the attribute as soon as <body> exists, i.e. before first paint.
        context.add_init_script("""
            new MutationObserver((_, observer) => {
              if (document.body) { window.themeAtBody = document.documentElement.getAttribute('data-theme'); observer.disconnect(); }
            }).observe(document, {childList: true, subtree: true});""")
        page = context.new_page()
        page.goto(url)
        assert page.evaluate('window.themeAtBody') == 'dark'
        script = page.locator('head script[src="/assets/theme.js"]')
        assert script.count() == 1
        assert page.evaluate('''(() => { const s = document.querySelector('head script[src="/assets/theme.js"]');
            return !s.async && !s.defer && s.type === ''; })()''')
        context.close()


def test_storage_unavailable_falls_back_gracefully(browser_system):
    browser, base = browser_system
    for url in pages(base).values():
        context = browser.new_context(color_scheme='dark')
        context.add_init_script("""Object.defineProperty(window, 'localStorage', {get() { throw new Error('denied'); }});""")
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(url)
        assert theme(page) is None
        option(page, '亮色').click()
        assert theme(page) == 'light'
        assert not errors
        context.close()
