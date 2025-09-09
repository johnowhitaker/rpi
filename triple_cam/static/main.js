async function fetchJSON(url, opts = {}) {
  const res = await fetch(url, opts);
  if (!res.ok) throw new Error(await res.text());
  return await res.json();
}

function el(tag, attrs = {}, children = []) {
  const e = document.createElement(tag);
  Object.assign(e, attrs);
  for (const c of children) e.appendChild(c);
  return e;
}

function buildStream(cam) {
  const wrap = el('div', { className: 'stream' });
  const title = el('h3');
  title.textContent = `${cam.label} (ID ${cam.id})`;
  const frame = el('div', { className: 'frame' });
  const img = el('img', { src: `/stream/${cam.id}.mjpg`, alt: cam.label });
  frame.appendChild(img);
  wrap.appendChild(title);
  wrap.appendChild(frame);
  return wrap;
}

async function initPiStreams() {
  try {
    const data = await fetchJSON('/api/cameras');
    const cams = data.cameras || [];
    const root = document.getElementById('pi-streams');
    root.innerHTML = '';
    for (const cam of cams) {
      root.appendChild(buildStream(cam));
    }
  } catch (e) {
    console.error('Failed to init streams', e);
  }
}

let currentStream;
function polyfillGetUserMedia() {
  if (!navigator.mediaDevices) navigator.mediaDevices = {};
  if (!navigator.mediaDevices.getUserMedia) {
    const legacy = navigator.getUserMedia || navigator.webkitGetUserMedia || navigator.mozGetUserMedia;
    if (legacy) {
      navigator.mediaDevices.getUserMedia = (constraints) => new Promise((resolve, reject) => legacy.call(navigator, constraints, resolve, reject));
    }
  }
}

function isSecure() {
  const proto = location.protocol;
  const host = location.hostname;
  return proto === 'https:' || host === 'localhost' || host === '127.0.0.1';
}

async function startPhoneCamera(useFront = false) {
  const video = document.getElementById('phoneVideo');
  const status = document.getElementById('status');
  if (currentStream) {
    for (const t of currentStream.getTracks()) t.stop();
  }
  polyfillGetUserMedia();
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    status.textContent = 'Camera access not available. Use HTTPS (required on iOS/Android).';
    return;
  }
  const constraints = {
    video: {
      facingMode: useFront ? 'user' : 'environment',
      width: { ideal: 1920 },
      height: { ideal: 1440 }
    },
    audio: false,
  };
  try {
    currentStream = await navigator.mediaDevices.getUserMedia(constraints);
    video.srcObject = currentStream;
  } catch (e) {
    status.textContent = 'Camera access failed: ' + e + (isSecure() ? '' : ' (tip: open over HTTPS)');
    throw e;
  }
}

async function snapTriple() {
  const status = document.getElementById('status');
  const video = document.getElementById('phoneVideo');
  if (!video.srcObject) {
    status.textContent = 'Phone camera not started';
    return;
  }
  status.textContent = 'Capturing...';
  const btn = document.getElementById('snapBtn');
  btn.disabled = true;
  try {
    // Draw current phone frame to canvas and encode JPEG
    const track = video.srcObject.getVideoTracks()[0];
    const settings = track.getSettings() || {};
    const w = video.videoWidth || settings.width || 1280;
    const h = video.videoHeight || settings.height || 960;
    const canvas = document.createElement('canvas');
    canvas.width = w; canvas.height = h;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(video, 0, 0, w, h);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.95));

    const form = new FormData();
    form.append('phone', blob, 'phone.jpg');
    const res = await fetchJSON('/api/triple_snap', { method: 'POST', body: form });
    status.textContent = 'Saved.';
    showLatest(res);
  } catch (e) {
    console.error(e);
    status.textContent = 'Capture failed: ' + e;
  } finally {
    btn.disabled = false;
  }
}

function showLatest(res) {
  const latest = document.getElementById('latest');
  latest.innerHTML = '';
  const links = el('div', { className: 'links' });

  const thumbs = el('div', { className: 'thumbs' });
  const mk = (title, url) => el('div', {}, [
    el('a', { href: url, target: '_blank', textContent: title }),
    el('img', { src: url, alt: title })
  ]);

  thumbs.appendChild(mk('Phone', res.phone.url));
  for (const p of res.pi) {
    thumbs.appendChild(mk(`Pi ${p.cam_id}`, p.url));
  }
  latest.appendChild(thumbs);
}

function wireUI() {
  const btn = document.getElementById('snapBtn');
  btn.addEventListener('click', snapTriple);
  const chk = document.getElementById('useFront');
  chk.addEventListener('change', () => startPhoneCamera(chk.checked));
}

async function init() {
  await initPiStreams();
  wireUI();
  await startPhoneCamera(false);
  await loadHistory();
}

init();

// History and ZIP downloads
async function loadHistory() {
  try {
    const data = await fetchJSON('/api/history');
    renderHistory(data);
  } catch (e) {
    console.error('Failed to load history', e);
  }
}

function renderHistory(data) {
  const container = document.getElementById('history');
  if (!container) return;
  const wrap = document.createElement('div');
  const hdr = document.createElement('div');
  hdr.style.display = 'flex';
  hdr.style.gap = '8px';
  const btnAll = document.createElement('a');
  btnAll.href = '/api/zip_all';
  btnAll.textContent = 'Download all as ZIP';
  btnAll.className = 'zipAll';
  const btnReload = document.createElement('button');
  btnReload.textContent = 'Refresh history';
  btnReload.onclick = loadHistory;
  hdr.appendChild(btnAll);
  hdr.appendChild(btnReload);

  const list = document.createElement('div');
  list.className = 'history-list';
  for (const g of (data.groups || [])) {
    const sec = document.createElement('section');
    sec.className = 'hist-set';
    const h = document.createElement('h3');
    h.textContent = g.timestamp;
    const zip = document.createElement('a');
    zip.href = `/api/zip_set/${encodeURIComponent(g.timestamp)}`;
    zip.textContent = 'ZIP';
    zip.className = 'ziplink';
    const bar = document.createElement('div');
    bar.style.display = 'flex';
    bar.style.justifyContent = 'space-between';
    bar.appendChild(h);
    bar.appendChild(zip);
    sec.appendChild(bar);
    const thumbs = document.createElement('div');
    thumbs.className = 'thumbs';
    for (const f of g.files) {
      const d = document.createElement('div');
      const a = document.createElement('a');
      a.href = f.url; a.target = '_blank'; a.textContent = f.name;
      const img = document.createElement('img'); img.src = f.url; img.alt = f.name;
      d.appendChild(a); d.appendChild(img);
      thumbs.appendChild(d);
    }
    sec.appendChild(thumbs);
    list.appendChild(sec);
  }

  container.innerHTML = '';
  container.appendChild(hdr);
  container.appendChild(list);
}
