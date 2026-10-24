const uploadForm = document.getElementById('upload-form');
const statusLine = document.getElementById('upload-status');
let uploading = false;
uploadForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  uploading = true;
  const button = uploadForm.querySelector('button');
  button.disabled = true;
  try {
    for (const file of document.getElementById('upload-files').files) {
      statusLine.textContent = `正在上传：${file.name}`;
      const response = await fetch(`/api/v1/imports/upload?filename=${encodeURIComponent(file.name)}`, {
        method: 'POST', headers: {'Content-Type': 'application/octet-stream'}, body: file,
      });
      if (!response.ok) {
        const error = await response.json();
        throw new Error(`${file.name}：${error.detail || '上传失败'}`);
      }
    }
    window.location.reload();
  } catch (error) {
    statusLine.textContent = error.message;
    uploading = false;
    button.disabled = false;
  }
});

async function watchJobs() {
  try {
    const response = await fetch('/api/v1/imports/jobs');
    if (!response.ok) return;
    const {jobs} = await response.json();
    const active = jobs.some(job => ['queued', 'running'].includes(job.status));
    if (!active && watchJobs.sawActive && !uploading && !document.getElementById('upload-files').files.length) {
      window.location.reload();
      return;
    }
    watchJobs.sawActive ||= active;
    if (active) window.setTimeout(watchJobs, 2000);
  } catch (_) {
    statusLine.textContent = '暂时无法获取任务状态，可以刷新页面查看。';
  }
}
watchJobs.sawActive = !!document.querySelector('[data-active-jobs]');
watchJobs();
