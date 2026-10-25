'use strict';
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
