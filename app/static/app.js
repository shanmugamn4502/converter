const MAX_FILES = 20;
const MAX_BYTES = 25 * 1024 * 1024;

// Plain-language hints so non-technical visitors know which one to pick.
const FORMATS = [
  { id: 'jpg', what: 'Photos. Small files, works everywhere.' },
  { id: 'png', what: 'Screenshots and graphics. Keeps transparency.' },
  { id: 'pdf', what: 'Combine images into one document.' },
  { id: 'webp', what: 'Smallest size for websites.' },
  { id: 'gif', what: 'Simple graphics, old apps.' },
  { id: 'bmp', what: 'Uncompressed, for older software.' },
  { id: 'tiff', what: 'Printing and scanning.' },
  { id: 'ico', what: 'Website and app icons.' },
];

const $ = (id) => document.getElementById(id);
const tray = $('tray');
const picker = $('picker');
const list = $('files');
const convertBtn = $('convert');
const statusEl = $('status');

let files = [];
let target = 'jpg';
let busy = false;

const isPdf = (f) => f.type === 'application/pdf' || /\.pdf$/i.test(f.name);
const extOf = (f) => (f.name.split('.').pop() || 'file').slice(0, 4).toUpperCase();

function humanSize(bytes) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function setStatus(text, kind = '') {
  statusEl.className = `status ${kind}`;
  statusEl.textContent = text;
}

/* ---------- tickets ---------- */
function renderTickets() {
  const tickets = $('tickets');
  tickets.innerHTML = '';
  const hasPdf = files.some(isPdf);
  for (const f of FORMATS) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'ticket';
    b.setAttribute('role', 'radio');
    b.setAttribute('aria-checked', String(f.id === target));
    b.disabled = f.id === 'pdf' && hasPdf;
    b.title = b.disabled ? 'Your files already include a PDF' : '';
    b.innerHTML = `<span class="ext">${f.id.toUpperCase()}</span><span class="what">${f.what}</span>`;
    b.addEventListener('click', () => { target = f.id; refresh(); });
    tickets.appendChild(b);
  }
}

/* ---------- file list ---------- */
function renderFiles() {
  list.innerHTML = '';
  for (const [i, f] of files.entries()) {
    const li = document.createElement('li');
    li.className = 'file';

    let thumb;
    if (f.type.startsWith('image/') && !/hei[cf]/i.test(f.type)) {
      thumb = document.createElement('img');
      thumb.className = 'thumb';
      thumb.alt = '';
      thumb.src = f._url ||= URL.createObjectURL(f);
    } else {
      thumb = document.createElement('div');
      thumb.className = 'thumb thumb-doc';
      thumb.textContent = extOf(f);
    }

    const name = document.createElement('div');
    name.className = 'file-name';
    name.innerHTML = '<strong></strong><span></span>';
    name.firstChild.textContent = f.name;
    name.lastChild.textContent = humanSize(f.size);

    const rm = document.createElement('button');
    rm.type = 'button';
    rm.className = 'remove';
    rm.setAttribute('aria-label', `Remove ${f.name}`);
    rm.textContent = '×';
    rm.addEventListener('click', () => {
      if (f._url) URL.revokeObjectURL(f._url);
      files.splice(i, 1);
      refresh();
    });

    li.append(thumb, name, rm);
    list.appendChild(li);
  }
  const has = files.length > 0;
  list.hidden = !has;
  $('trayActions').hidden = !has;
  $('trayEmpty').hidden = has;
}

/* ---------- options + button ---------- */
function refresh() {
  if (target === 'pdf' && files.some(isPdf)) target = 'png';
  renderFiles();
  renderTickets();

  $('qualityOpt').hidden = !['jpg', 'webp'].includes(target);
  $('dpiOpt').hidden = !(files.some(isPdf) || target === 'pdf');

  const n = files.length;
  convertBtn.disabled = busy || n === 0;
  if (!busy) {
    convertBtn.textContent = n === 0
      ? 'Add files to start'
      : target === 'pdf'
        ? `Combine ${n === 1 ? '1 image' : `${n} images`} into a PDF`
        : `Convert ${n === 1 ? '1 file' : `${n} files`} to ${target.toUpperCase()}`;
  }
}

function addFiles(incoming) {
  const rejected = [];
  for (const f of incoming) {
    const ok = f.type.startsWith('image/') || isPdf(f) || /\.(heic|heif)$/i.test(f.name);
    if (!ok) { rejected.push(`${f.name} isn't an image or PDF`); continue; }
    if (f.size > MAX_BYTES) { rejected.push(`${f.name} is over 25 MB`); continue; }
    if (files.length >= MAX_FILES) { rejected.push(`only ${MAX_FILES} files fit at once`); break; }
    files.push(f);
  }
  setStatus(rejected.length ? `Skipped: ${rejected.join('; ')}.` : '', rejected.length ? 'err' : '');
  refresh();
}

/* ---------- convert ---------- */
function filenameFrom(res) {
  const cd = res.headers.get('Content-Disposition') || '';
  const m = cd.match(/filename\*=UTF-8''([^;]+)/);
  return m ? decodeURIComponent(m[1]) : 'converted';
}

async function run() {
  if (busy || !files.length) return;
  busy = true;
  convertBtn.classList.add('is-busy');
  convertBtn.disabled = true;
  convertBtn.textContent = 'Converting…';
  setStatus('');

  const body = new FormData();
  files.forEach((f) => body.append('files', f, f.name));
  body.append('target', target);
  body.append('quality', $('quality').value);
  body.append('dpi', $('dpi').value);

  try {
    const res = await fetch('/api/convert', { method: 'POST', body });
    if (!res.ok) {
      let msg = 'Conversion failed. Try again.';
      if (res.status === 413) msg = 'That upload is too large. Keep each file under 25 MB.';
      try { msg = (await res.json()).detail || msg; } catch {}
      throw new Error(msg);
    }
    const blob = await res.blob();
    const name = filenameFrom(res);
    const url = URL.createObjectURL(blob);

    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    a.click();

    statusEl.className = 'status ok';
    statusEl.innerHTML = 'Converted. Download started. <a></a>';
    const again = statusEl.querySelector('a');
    again.href = url;
    again.download = name;
    again.textContent = `Download ${name} again`;
  } catch (e) {
    setStatus(e.message === 'Failed to fetch' ? "Couldn't reach the converter. Check your connection and try again." : e.message, 'err');
  } finally {
    busy = false;
    convertBtn.classList.remove('is-busy');
    refresh();
  }
}

/* ---------- wiring ---------- */
$('choose').addEventListener('click', (e) => { e.stopPropagation(); picker.click(); });
$('trayEmpty').addEventListener('click', () => picker.click());
$('addMore').addEventListener('click', () => picker.click());
$('clearAll').addEventListener('click', () => {
  files.forEach((f) => f._url && URL.revokeObjectURL(f._url));
  files = [];
  setStatus('');
  refresh();
});
picker.addEventListener('change', () => { addFiles([...picker.files]); picker.value = ''; });
$('quality').addEventListener('input', (e) => { $('qualityOut').textContent = e.target.value; });
convertBtn.addEventListener('click', run);

// Drag-and-drop anywhere on the page lands in the tray.
let depth = 0;
window.addEventListener('dragenter', (e) => { e.preventDefault(); depth++; tray.classList.add('is-over'); });
window.addEventListener('dragleave', () => { if (--depth <= 0) { depth = 0; tray.classList.remove('is-over'); } });
window.addEventListener('dragover', (e) => e.preventDefault());
window.addEventListener('drop', (e) => {
  e.preventDefault();
  depth = 0;
  tray.classList.remove('is-over');
  addFiles([...e.dataTransfer.files]);
});

refresh();
