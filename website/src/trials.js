const english = document.documentElement.lang === 'en';
document.querySelectorAll('[data-copy-trial]').forEach(button => {
  button.hidden = false;
  button.addEventListener('click', async () => {
    const card = button.closest('.trial-card');
    const status = card.querySelector('[data-copy-status]');
    const message = document.getElementById(button.dataset.copyTrial);
    try {
      await navigator.clipboard.writeText(message.textContent);
      status.textContent = english ? 'Copied. You can paste these instructions into your message.' : '已复制，可直接粘贴转发给测试者。';
    } catch {
      card.querySelector('details').open = true;
      status.textContent = english ? 'Clipboard unavailable. Download the TXT file or select the text below to copy.' : '当前无法访问剪贴板，请下载 TXT 转发，或选择下方文字手动复制。';
    }
  });
});

function openLinkedVariant() {
  const id = location.hash.slice(1);
  if (!/^(sqn|sqc|sqw)100-[1-5]$/.test(id)) return;
  const card = document.getElementById(id);
  const details = card?.querySelector('details');
  if (details) details.open = true;
}
openLinkedVariant();
window.addEventListener('hashchange', openLinkedVariant);
