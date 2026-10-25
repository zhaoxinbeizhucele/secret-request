'use strict';
// The relay only issues /i#<22-char token>. A credential fragment left on the
// homepage is the same token, so send it to that page. Other hashes stay here.
function redirectTokenFragment() {
  const fragment = location.hash.slice(1);
  if (location.pathname === '/' && /^[A-Za-z0-9_-]{22}$/.test(fragment)) {
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
