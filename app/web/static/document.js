const metadataForm = document.getElementById('metadata-form');
if (metadataForm) metadataForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = metadataForm.querySelector('button');
  const status = document.getElementById('metadata-status');
  button.disabled = true;
  status.textContent = '正在保存…';
  try {
    const payload = Object.fromEntries(new FormData(metadataForm));
    // Preserve a source's precise timestamp if its displayed date is unchanged.
    if (payload.published_at === metadataForm.elements.published_at.defaultValue) delete payload.published_at;
    if (payload.stock_codes === metadataForm.elements.stock_codes.defaultValue) delete payload.stock_codes;
    const response = await fetch(`/api/v1/documents/${metadataForm.dataset.documentId}/metadata`, {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error((await response.json()).detail || '保存失败');
    window.location.reload();
  } catch (error) {
    status.textContent = error.message;
    button.disabled = false;
  }
});
