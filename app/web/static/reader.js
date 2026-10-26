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
  const blocks = () => Array.from(body.children).filter(el => el.getBoundingClientRect().height > 0);
  const marker = () => Math.max(12, bar.getBoundingClientRect().bottom + 12);
  const capture = () => {
    const items = blocks(), y = marker();
    const index = items.findIndex(el => el.getBoundingClientRect().bottom > y);
    if (index < 0) return items.length ? {version:2,index:items.length-1,offset:1} : null;
    const rect = items[index].getBoundingClientRect();
    if (index === 0 && rect.top > y) return {version:2,index:0,offset:0,intro:true,top:scrollY};
    return {version:2,index,offset:Math.min(1,Math.max(0,(y-rect.top)/rect.height))};
  };
  const restore = saved => {
    if (!saved || saved.version !== 2 || !Number.isInteger(saved.index) || !Number.isFinite(saved.offset)) return;
    if (saved.intro && Number.isFinite(saved.top)) { window.scrollTo({top:Math.max(0,saved.top),behavior:'instant'}); return; }
    const item = blocks()[saved.index]; if (!item) return;
    const rect = item.getBoundingClientRect();
    window.scrollTo({top:Math.max(0,scrollY+rect.top+rect.height*Math.min(1,Math.max(0,saved.offset))-marker()),behavior:'instant'});
  };
  const preserve = action => { const anchor = capture(); action(); requestAnimationFrame(() => { restore(anchor); update(); }); };
  const setFont = () => { body.style.fontSize = `${font}px`; store('researchdock:reader-font', font); };
  button('A−', () => { preserve(() => { font = Math.max(16, font - 2); setFont(); }); }).setAttribute('aria-label', '减小正文字号');
  button('A＋', () => { preserve(() => { font = Math.min(24, font + 2); setFont(); }); }).setAttribute('aria-label', '增大正文字号');
  const focus = button('专注阅读', () => preserve(() => { const enabled = document.body.classList.toggle('reader-focus'); focus.textContent = enabled ? '退出专注' : '专注阅读'; focus.setAttribute('aria-pressed', String(enabled)); })); focus.setAttribute('aria-pressed','false');
  const position = document.createElement('span'); position.className = 'hint'; bar.append(position);
  let old = null; try { old = JSON.parse(load(key)); } catch (_) {}
  if (old && old.version === 2 && Number.isInteger(old.index) && (!old.intro || old.top > 20)) button('继续上次阅读', () => restore(old));
  else if (typeof old === 'number' && old > .02 && old < .98) button('继续上次阅读', () => window.scrollTo({top: old * Math.max(0, document.documentElement.scrollHeight - innerHeight), behavior: 'smooth'}));
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
  const update = () => { scheduled = false; const rect = body.getBoundingClientRect(); const span = Math.max(1,rect.height-innerHeight+marker()); const ratio = Math.min(1,Math.max(0,(marker()-rect.top)/span)); position.textContent = `已读 ${Math.round(ratio*100)}%`; };
  const save = () => { const anchor = capture(); if (anchor) store(key,JSON.stringify(anchor)); };
  addEventListener('scroll', () => { if (!scheduled) { scheduled = true; requestAnimationFrame(update); } }, {passive:true});
  addEventListener('pagehide', save); document.addEventListener('visibilitychange', () => { if (document.hidden) save(); });
  const back = document.querySelector('[data-reader-back]');
  if (back && document.referrer) { try { const previous = new URL(document.referrer); if (previous.origin === location.origin && previous.pathname !== location.pathname) back.addEventListener('click', e => { if(history.length>1){ e.preventDefault(); history.back(); } }); } catch (_) {} }
  update();
})();
