(() => {
  const article = document.querySelector('[data-reader-document]');
  if (!article) return;
  const key = `researchdock:position:${article.dataset.readerDocument}:${article.dataset.readerRevision}`;
  const load = (k) => { try { return localStorage.getItem(k); } catch (_) { return null; } };
  const store = (k, v) => { try { localStorage.setItem(k, String(v)); } catch (_) {} };
  const body = article.querySelector('.body');
  const bar = document.createElement('nav'); bar.className = 'reader-bar'; bar.setAttribute('aria-label', '阅读工具');
  const button = (name, action) => { const b = document.createElement('button'); b.type = 'button'; b.className = 'btn'; b.textContent = name; b.addEventListener('click', action); bar.append(b); return b; };
  const fontValue = Number(load('researchdock:reader-font'));
  let font = [16,18,20,22,24].includes(fontValue) ? fontValue : 18;
  const setFont = () => { body.style.fontSize = `${font}px`; store('researchdock:reader-font', font); };
  button('A−', () => { font = Math.max(16, font - 2); setFont(); }).setAttribute('aria-label', '减小正文字号');
  button('A＋', () => { font = Math.min(24, font + 2); setFont(); }).setAttribute('aria-label', '增大正文字号');
  const focus = button('专注阅读', () => { const enabled = document.body.classList.toggle('reader-focus'); focus.textContent = enabled ? '退出专注' : '专注阅读'; focus.setAttribute('aria-pressed', String(enabled)); }); focus.setAttribute('aria-pressed','false');
  const position = document.createElement('span'); position.className = 'hint'; bar.append(position);
  const old = Number(load(key));
  if (old > .02 && old < .98) button('继续上次阅读', () => window.scrollTo({top: old * Math.max(0, document.documentElement.scrollHeight - innerHeight), behavior: 'smooth'}));
  const toc = document.createElement('details'); toc.className = 'reader-toc';
  const caption = document.createElement('summary'); caption.textContent = '章节目录'; toc.append(caption);
  const links = document.createElement('div');
  article.querySelectorAll('h2,h3').forEach((heading, index) => {
    if (heading.closest('details')) return;
    if (!heading.id) heading.id = `reader-section-${index}`;
    const a = document.createElement('a'); a.textContent = heading.textContent; a.href = `#${heading.id}`; a.addEventListener('click', () => { toc.open = false; }); links.append(a);
  });
  if (links.childElementCount) { toc.append(links); bar.append(toc); }
  article.prepend(bar); setFont();
  let scheduled = false;
  const update = () => { scheduled = false; const max = Math.max(0, document.documentElement.scrollHeight-innerHeight); const ratio = max > 0 ? Math.min(1,Math.max(0,scrollY/max)) : 0; position.textContent = `已读 ${Math.round(ratio*100)}%`; };
  const save = () => { const max = Math.max(0, document.documentElement.scrollHeight-innerHeight); if (max > 0) store(key, Math.min(1,Math.max(0,scrollY/max))); };
  addEventListener('scroll', () => { if (!scheduled) { scheduled = true; requestAnimationFrame(update); } }, {passive:true});
  addEventListener('pagehide', save); document.addEventListener('visibilitychange', () => { if (document.hidden) save(); });
  const back = document.querySelector('[data-reader-back]');
  if (back && document.referrer) { try { const previous = new URL(document.referrer); if (previous.origin === location.origin && previous.pathname !== location.pathname) back.addEventListener('click', e => { if(history.length>1){ e.preventDefault(); history.back(); } }); } catch (_) {} }
  update();
})();
