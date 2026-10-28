const $ = (id) => document.getElementById(id);
const el = (tag, props = {}, ...kids) => {
  const n = Object.assign(document.createElement(tag), props);
  n.append(...kids.filter((k) => k != null));
  return n;
};

const tray = $('tray');
const picker = $('picker');
const list = $('files');
const runBtn = $('run');
const statusEl = $('status');
const resultEl = $('result');

const byId = Object.fromEntries(TOOLS.map((t) => [t.id, t]));
const values = {}; // tool id -> { option name -> value }, so choices survive switching tools

let tool = null;
let files = [];
let busy = false;
let optionNodes = [];

const extOf = (name) => (name.split('.').pop() || '').toLowerCase();
const isPdf = (f) => f.type === 'application/pdf' || extOf(f.name) === 'pdf';
const fits = (f, t) => t.exts.includes(extOf(f.name)) || (t.exts.includes('png') && f.type.startsWith('image/'));

function humanSize(bytes) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function setStatus(text, kind = '') {
  statusEl.className = `status ${kind}`;
  statusEl.textContent = text;
}

const state = () => ({ count: files.length, hasPdf: files.some(isPdf) });
const v = () => values[tool.id];

/* ---------------------------------------------------------------- menu */

function buildMenu() {
  const menu = $('menu');
  let group = null;
  let ul = null;
  for (const t of TOOLS) {
    if (t.group !== group) {
      group = t.group;
      ul = el('ul');
      menu.append(el('div', { className: 'menu-group' }, el('p', { textContent: group }), ul));
    }
    ul.append(el('li', {}, el('a', { href: `#${t.id}`, textContent: t.nav, className: 'menu-item', id: `nav-${t.id}` })));
  }
}

/* ---------------------------------------------------------------- options */

function optionNode(o) {
  const val = v();
  const wrap = el('div', { className: `opt opt-${o.type}` });
  const label = el('span', { className: 'opt-name', textContent: o.label });
  let control;
  const set = (x, rerender = true) => { val[o.name] = x; if (rerender) sync(); };

  if (o.type === 'tickets') {
    wrap.classList.add('opt-wide');
    control = el('div', {
      className: `tickets${o.big ? ' big' : ''}${o.compact ? ' compact' : ''}`,
      role: 'radiogroup',
    });
    control.setAttribute('aria-label', o.label);
    for (const item of o.items) {
      const b = el('button', { type: 'button', className: 'ticket' },
        el('span', { className: 'ext', textContent: item.title }),
        item.note ? el('span', { className: 'what', textContent: item.note }) : null);
      b.setAttribute('role', 'radio');
      b.dataset.value = item.value;
      b.addEventListener('click', () => set(item.value));
      control.append(b);
    }
    wrap.append(label, control);
  } else if (o.type === 'range') {
    const out = el('output');
    const input = el('input', { type: 'range', min: o.min, max: o.max, step: o.step, value: val[o.name] });
    const show = () => { out.textContent = `${input.value}${o.suffix || ''}`; };
    input.addEventListener('input', () => { show(); set(input.value, false); });
    show();
    label.append(' ', out);
    control = input;
    wrap.append(el('label', {}, label, input));
  } else if (o.type === 'select') {
    control = el('select');
    for (const [value, text] of o.items) control.append(el('option', { value, textContent: text }));
    control.value = val[o.name];
    control.addEventListener('change', () => set(control.value));
    wrap.append(el('label', {}, label, control));
  } else if (o.type === 'color') {
    control = el('input', { type: 'color', value: val[o.name] });
    control.addEventListener('input', () => set(control.value, false));
    wrap.append(el('label', {}, label, control));
  } else {
    const tag = o.type === 'textarea' ? 'textarea' : 'input';
    control = el(tag, { value: val[o.name] ?? '', placeholder: o.placeholder || '' });
    if (tag === 'input') {
      control.type = o.type === 'number' ? 'number' : 'text';
      if (o.type === 'number') Object.assign(control, { min: o.min, max: o.max, inputMode: 'numeric' });
      if (o.inputmode) control.inputMode = o.inputmode;
    } else {
      control.rows = 4;
    }
    control.addEventListener('input', () => set(control.value, false));
    control.addEventListener('change', () => sync());
    const field = o.suffix ? el('span', { className: 'with-suffix' }, control, el('span', { textContent: o.suffix })) : control;
    wrap.append(el('label', {}, label, field));

    if (o.quick) {
      const chips = el('div', { className: 'quick' });
      for (const q of o.quick) {
        const c = el('button', { type: 'button', className: 'chip', textContent: q >= 1024 && q % 1024 === 0 ? `${q / 1024} MB` : `${q} KB` });
        c.addEventListener('click', () => { control.value = q; set(String(q)); });
        chips.append(c);
      }
      wrap.append(chips);
    }
  }

  if (o.help) wrap.append(el('span', { className: 'opt-help', textContent: o.help }));
  return { o, wrap, control };
}

function buildOptions() {
  const form = $('opts');
  form.innerHTML = '';
  optionNodes = tool.options.map(optionNode);
  form.append(...optionNodes.map((n) => n.wrap));
  form.hidden = optionNodes.length === 0;
}

/* ---------------------------------------------------------------- files */

function renderFiles() {
  list.innerHTML = '';
  files.forEach((f, i) => {
    let thumb;
    if (f.type.startsWith('image/') && !/hei[cf]|tiff/i.test(f.type)) {
      thumb = el('img', { className: 'thumb', alt: '', src: (f._url ||= URL.createObjectURL(f)) });
    } else {
      thumb = el('div', { className: 'thumb thumb-doc', textContent: extOf(f.name).slice(0, 4).toUpperCase() || 'FILE' });
    }
    const name = el('div', { className: 'file-name' },
      el('strong', { textContent: f.name }), el('span', { textContent: humanSize(f.size) }));
    const controls = el('div', { className: 'file-controls' });

    if (tool.ordered && files.length > 1) {
      const move = (d) => { [files[i], files[i + d]] = [files[i + d], files[i]]; refresh(); };
      const up = el('button', { type: 'button', className: 'icon-btn', textContent: '↑', disabled: i === 0 });
      const down = el('button', { type: 'button', className: 'icon-btn', textContent: '↓', disabled: i === files.length - 1 });
      up.setAttribute('aria-label', `Move ${f.name} up`);
      down.setAttribute('aria-label', `Move ${f.name} down`);
      up.addEventListener('click', () => move(-1));
      down.addEventListener('click', () => move(1));
      controls.append(up, down);
    }
    const rm = el('button', { type: 'button', className: 'icon-btn', textContent: '×' });
    rm.setAttribute('aria-label', `Remove ${f.name}`);
    rm.addEventListener('click', () => { if (f._url) URL.revokeObjectURL(f._url); files.splice(i, 1); setStatus(''); refresh(); });
    controls.append(rm);

    list.append(el('li', { className: 'file' }, el('span', { className: 'order', textContent: tool.ordered ? i + 1 : '' }), thumb, name, controls));
  });

  const has = files.length > 0;
  list.hidden = !has;
  list.classList.toggle('is-ordered', !!tool.ordered);
  $('trayActions').hidden = !has;
  $('addMore').hidden = !tool.multiple || files.length >= tool.maxFiles;
  $('trayEmpty').hidden = has;
}

function addFiles(incoming) {
  if (tool.noFiles) return;
  const skipped = [];
  for (const f of incoming) {
    if (!fits(f, tool)) { skipped.push(`${f.name} doesn't work with this tool`); continue; }
    if (f.size > tool.maxMB * 1024 * 1024) { skipped.push(`${f.name} is over ${tool.maxMB} MB`); continue; }
    if (!tool.multiple) { files.forEach((x) => x._url && URL.revokeObjectURL(x._url)); files = [f]; continue; }
    if (files.length >= tool.maxFiles) { skipped.push(`only ${tool.maxFiles} files fit at once`); break; }
    files.push(f);
  }
  setStatus(skipped.length ? `Skipped: ${skipped.join('; ')}.` : '', skipped.length ? 'err' : '');
  resultEl.hidden = true;
  refresh();
}

/* ---------------------------------------------------------------- sync */

function sync() {
  const val = v();
  const s = state();

  for (const { o, wrap } of optionNodes) {
    wrap.hidden = o.show ? !o.show(val, s) : false;
    if (o.type !== 'tickets') continue;
    const disabledNow = (item) => item.disabled && item.disabled(val, s);
    if (o.items.some((it) => it.value === val[o.name] && disabledNow(it))) {
      val[o.name] = o.items.find((it) => !disabledNow(it)).value;
    }
    for (const b of wrap.querySelectorAll('.ticket')) {
      const item = o.items.find((it) => it.value === b.dataset.value);
      b.setAttribute('aria-checked', String(item.value === val[o.name]));
      b.disabled = !!disabledNow(item);
    }
  }

  let label;
  let ok = !busy;
  if (!tool.noFiles && s.count === 0) {
    label = tool.multiple ? 'Add files to start' : 'Add a file to start';
    ok = false;
  } else if (tool.minFiles && s.count < tool.minFiles) {
    label = tool.action(val, s);
    ok = false;
  } else if (tool.ready && !tool.ready(val, s)) {
    label = tool.notReady;
    ok = false;
  } else {
    label = tool.action(val, s);
  }
  if (!busy) runBtn.textContent = label;
  runBtn.disabled = !ok;
}

function refresh() {
  renderFiles();
  sync();
}

/* ---------------------------------------------------------------- switch tool */

function selectTool(id, focus) {
  const next = byId[id] || TOOLS[0];
  if (tool === next) return;
  tool = next;

  if (!values[tool.id]) values[tool.id] = Object.fromEntries(tool.options.map((o) => [o.name, String(o.value ?? '')]));
  // Keep files that also work with the new tool, so you can convert then compress.
  files = tool.noFiles ? [] : files.filter((f) => fits(f, tool)).slice(0, tool.multiple ? tool.maxFiles : 1);

  for (const a of document.querySelectorAll('.menu-item')) a.removeAttribute('aria-current');
  const link = $(`nav-${tool.id}`);
  link.setAttribute('aria-current', 'page');
  link.scrollIntoView({ block: 'nearest', inline: 'nearest' });

  $('toolTitle').textContent = tool.title;
  $('toolBlurb').textContent = tool.blurb;
  document.title = `${tool.title} | Converter`;

  tray.hidden = !!tool.noFiles;
  $('trayTitle').textContent = tool.multiple ? 'Drop files here' : 'Drop a file here';
  $('trayHint').textContent = tool.hint || '';
  picker.multiple = !!tool.multiple;
  picker.accept = (tool.exts || []).map((e) => `.${e}`).join(',');

  resultEl.hidden = true;
  resultEl.innerHTML = '';
  setStatus('');
  buildOptions();
  refresh();
  if (focus) $('toolTitle').focus({ preventScroll: true });
}

/* ---------------------------------------------------------------- run */

function filenameFrom(res) {
  const m = (res.headers.get('Content-Disposition') || '').match(/filename\*=UTF-8''([^;]+)/);
  return m ? decodeURIComponent(m[1]) : 'download';
}

function visibleFields() {
  const val = v();
  const s = state();
  const out = {};
  for (const { o } of optionNodes) if (!o.show || o.show(val, s)) out[o.name] = val[o.name];
  return out;
}

function download(url, name) {
  el('a', { href: url, download: name }).click();
}

function showSavings(res, name, url) {
  const before = Number(res.headers.get('X-Original-Size'));
  const after = Number(res.headers.get('X-Result-Size'));
  const removed = res.headers.get('X-Removed');

  let text = 'Done. Your download has started.';
  if (before && after) {
    const pct = Math.round((1 - after / before) * 100);
    text = pct > 0
      ? `Done: ${humanSize(before)} down to ${humanSize(after)}, ${pct}% smaller.`
      : 'Done. This file was already well compressed, so the size barely changed.';
  }
  if (removed) {
    text = removed === 'none'
      ? 'Done. No location or camera details were found, and your copy is clean.'
      : `Done. Removed: ${removed}.`;
  }
  statusEl.className = 'status ok';
  statusEl.textContent = `${text} `;
  statusEl.append(el('a', { href: url, download: name, textContent: `Download ${name} again` }));
}

function showText(text) {
  const area = el('textarea', { className: 'result-text', value: text || '', rows: 12 });
  area.setAttribute('aria-label', 'Text found in your file');
  const copy = el('button', { type: 'button', className: 'ghost', textContent: 'Copy text' });
  copy.addEventListener('click', async () => {
    await navigator.clipboard.writeText(area.value);
    copy.textContent = 'Copied';
    setTimeout(() => { copy.textContent = 'Copy text'; }, 1600);
  });
  const save = el('button', { type: 'button', className: 'ghost', textContent: 'Download as .txt' });
  save.addEventListener('click', () => download(URL.createObjectURL(new Blob([area.value], { type: 'text/plain' })), 'text.txt'));

  resultEl.innerHTML = '';
  resultEl.append(area, el('div', { className: 'result-actions' }, copy, save));
  resultEl.hidden = false;
  setStatus(text ? 'Done. Check the text below; you can edit it before copying.' : 'No text was found. Try a sharper photo or another language.', text ? 'ok' : 'err');
}

function showQr(url, name) {
  const dl = el('a', { href: url, download: name, className: 'convert as-link', textContent: `Download ${name.split('.').pop().toUpperCase()}` });
  resultEl.innerHTML = '';
  resultEl.append(el('div', { className: 'qr-preview' }, el('img', { src: url, alt: 'Your QR code' })), dl);
  resultEl.hidden = false;
  setStatus('Done. Scan it with your phone camera to test it before you print or share.', 'ok');
}

async function run() {
  if (busy || runBtn.disabled) return;
  const started = tool;
  busy = true;
  runBtn.disabled = true;
  runBtn.classList.add('is-busy');
  runBtn.textContent = tool.heavy ? 'Working… this can take a minute' : 'Working…';
  setStatus('');
  resultEl.hidden = true;

  const body = new FormData();
  files.forEach((f) => body.append('files', f, f.name));
  const fields = { ...(tool.fields ? tool.fields(v()) : visibleFields()), ...(tool.fixed || {}) };
  for (const [k, x] of Object.entries(fields)) body.append(k, x);

  try {
    const res = await fetch(tool.endpoint, { method: 'POST', body });
    if (!res.ok) {
      let msg = 'Something went wrong. Try again.';
      if (res.status === 413) msg = `That upload is too large. Keep it under ${tool.maxMB} MB.`;
      try { msg = (await res.json()).detail || msg; } catch {}
      throw new Error(msg);
    }
    if (started.result === 'text') {
      const { text } = await res.json();
      if (tool === started) showText(text);
      return;
    }
    const url = URL.createObjectURL(await res.blob());
    const name = filenameFrom(res);
    if (started.result === 'qr') {
      if (tool === started) showQr(url, name);
      return;
    }
    download(url, name);
    if (tool === started) showSavings(res, name, url);
  } catch (e) {
    if (tool === started) {
      setStatus(e.message === 'Failed to fetch' ? "Couldn't reach the server. Check your connection and try again." : e.message, 'err');
    }
  } finally {
    busy = false;
    runBtn.classList.remove('is-busy');
    sync();
  }
}

/* ---------------------------------------------------------------- wiring */

$('choose').addEventListener('click', (e) => { e.stopPropagation(); picker.click(); });
$('trayEmpty').addEventListener('click', () => picker.click());
$('addMore').addEventListener('click', () => picker.click());
$('clearAll').addEventListener('click', () => {
  files.forEach((f) => f._url && URL.revokeObjectURL(f._url));
  files = [];
  setStatus('');
  resultEl.hidden = true;
  refresh();
});
picker.addEventListener('change', () => { addFiles([...picker.files]); picker.value = ''; });
runBtn.addEventListener('click', run);
$('opts').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && e.target.tagName === 'INPUT') { e.preventDefault(); sync(); run(); }
});

let depth = 0;
window.addEventListener('dragenter', (e) => { e.preventDefault(); if (tool.noFiles) return; depth++; tray.classList.add('is-over'); });
window.addEventListener('dragleave', () => { if (--depth <= 0) { depth = 0; tray.classList.remove('is-over'); } });
window.addEventListener('dragover', (e) => e.preventDefault());
window.addEventListener('drop', (e) => {
  e.preventDefault();
  depth = 0;
  tray.classList.remove('is-over');
  addFiles([...e.dataTransfer.files]);
});

window.addEventListener('hashchange', () => selectTool(location.hash.slice(1), true));

buildMenu();
selectTool(location.hash.slice(1) || 'convert', false);
