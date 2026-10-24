const sourceStatus = document.getElementById('source-status');
async function sourceRequest(url, payload) {
  const response = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || '操作失败');
  return data;
}
document.getElementById('source-form').addEventListener('submit', async event => {
  event.preventDefault();
  try {
    await sourceRequest('/api/v1/sources/zsxq', Object.fromEntries(new FormData(event.target)));
    location.reload();
  } catch (error) { sourceStatus.textContent = error.message; }
});
document.querySelectorAll('.source-sync').forEach(button => button.addEventListener('click', async () => {
  button.disabled = true;
  try {
    await sourceRequest(`/api/v1/sources/zsxq/${button.dataset.group}/sync?mode=${button.dataset.mode}`, {});
    location.reload();
  } catch (error) { sourceStatus.textContent = error.message; button.disabled = false; }
}));
async function watchSources() {
  try {
    const response = await fetch('/api/v1/sources');
    if (!response.ok) return;
    const {sources} = await response.json();
    const active = sources.some(s => ['queued', 'running'].includes(s.status));
    if (!active && document.querySelector('.source-sync:disabled') && !document.getElementById('source-form').elements.group_id.value) {
      // A completed history button is disabled too; compare current status labels.
      if (Array.from(document.querySelectorAll('.badge')).some(e => ['queued','running'].includes(e.textContent))) location.reload();
    }
    if (active) setTimeout(watchSources, 2000);
  } catch (_) { sourceStatus.textContent = '暂时无法获取同步状态，请刷新查看。'; }
}
watchSources();
