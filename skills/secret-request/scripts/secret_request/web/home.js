'use strict';
// The server never sees the fragment. A token-shaped fragment at / is the short
// form served from the site root; the input page itself lives at /i.
function redirectTokenFragment() {
  const fragment = location.hash.slice(1);
  if (location.pathname === '/' && /^(?:[A-Za-z0-9_-]{22}|[A-Za-z0-9_-]{43})$/.test(fragment)) {
    location.replace('/i' + location.hash);
  }
}
redirectTokenFragment();
addEventListener('hashchange', redirectTokenFragment);
const copy = document.querySelector('#copy-command');
const status = document.querySelector('#copy-status');
copy.addEventListener('click', async () => {
  copy.disabled = true;
  try {
    await navigator.clipboard.writeText(document.querySelector('#install-command').textContent);
    status.textContent = '安装命令已复制。';
  } catch {
    status.textContent = '无法访问剪贴板，请选中上方命令手动复制。';
  } finally {
    copy.disabled = false;
  }
});
