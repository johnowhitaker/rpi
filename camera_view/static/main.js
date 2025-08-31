async function fetchJSON(url, opts = {}) {
  const res = await fetch(url, Object.assign({ headers: { 'Content-Type': 'application/json' } }, opts));
  if (!res.ok) throw new Error(await res.text());
  return await res.json();
}

function makeRange(id, label, min, max, step, value, oninput) {
  const wrap = document.createElement('div');
  wrap.className = 'control';
  const l = document.createElement('label');
  l.htmlFor = id;
  l.textContent = `${label}: `;
  const span = document.createElement('span');
  span.className = 'val';
  span.textContent = value;
  const input = document.createElement('input');
  input.type = 'range';
  input.min = min;
  input.max = max;
  input.step = step;
  input.value = value;
  input.id = id;
  input.oninput = (e) => {
    span.textContent = e.target.value;
    oninput(parseFloat(e.target.value));
  };
  l.appendChild(span);
  wrap.appendChild(l);
  wrap.appendChild(input);
  return wrap;
}

function makeCheckbox(id, label, checked, onchange) {
  const wrap = document.createElement('div');
  wrap.className = 'control';
  const l = document.createElement('label');
  const input = document.createElement('input');
  input.type = 'checkbox';
  input.checked = checked;
  input.id = id;
  input.onchange = (e) => onchange(!!e.target.checked);
  l.appendChild(input);
  l.appendChild(document.createTextNode(' ' + label));
  wrap.appendChild(l);
  return wrap;
}

function makeSelect(id, label, options, value, onchange) {
  const wrap = document.createElement('div');
  wrap.className = 'control';
  const l = document.createElement('label');
  l.htmlFor = id;
  l.textContent = label + ': ';
  const sel = document.createElement('select');
  sel.id = id;
  for (const [val, text] of options) {
    const opt = document.createElement('option');
    opt.value = val;
    opt.textContent = text;
    if (val === value) opt.selected = true;
    sel.appendChild(opt);
  }
  sel.onchange = (e) => onchange(e.target.value);
  wrap.appendChild(l);
  wrap.appendChild(sel);
  return wrap;
}

async function buildCamera(cam) {
  const container = document.createElement('section');
  container.className = 'cam';
  const title = document.createElement('h2');
  title.textContent = `${cam.label} (ID ${cam.id})`;
  container.appendChild(title);

  const row = document.createElement('div');
  row.className = 'row';
  const preview = document.createElement('div');
  preview.className = 'preview';
  const img = document.createElement('img');
  img.src = `/stream/${cam.id}.mjpg`;
  img.alt = `Preview ${cam.label}`;
  preview.appendChild(img);
  row.appendChild(preview);

  const controls = document.createElement('div');
  controls.className = 'controls';

  // Controls
  controls.appendChild(makeCheckbox(`ae_${cam.id}`, 'Auto Exposure', false, async (v) => {
    await fetchJSON(`/api/${cam.id}/controls`, { method: 'POST', body: JSON.stringify({ ae_enable: v }) });
  }));

  controls.appendChild(makeRange(`exp_${cam.id}`, 'Exposure (us)', 100, 200000, 100, 2000, async (v) => {
    await fetchJSON(`/api/${cam.id}/controls`, { method: 'POST', body: JSON.stringify({ exposure_time: v }) });
  }));

  controls.appendChild(makeRange(`gain_${cam.id}`, 'Analogue Gain', 1.0, 16.0, 0.1, 1.0, async (v) => {
    await fetchJSON(`/api/${cam.id}/controls`, { method: 'POST', body: JSON.stringify({ analogue_gain: v }) });
  }));

  controls.appendChild(makeCheckbox(`awb_${cam.id}`, 'Auto White Balance', false, async (v) => {
    await fetchJSON(`/api/${cam.id}/controls`, { method: 'POST', body: JSON.stringify({ awb_enable: v }) });
  }));

  controls.appendChild(makeRange(`ev_${cam.id}`, 'Exposure Compensation (EV)', -4.0, 4.0, 0.1, 0.0, async (v) => {
    await fetchJSON(`/api/${cam.id}/controls`, { method: 'POST', body: JSON.stringify({ ev: v }) });
  }));

  controls.appendChild(makeSelect(`afm_${cam.id}`, 'AF Mode', [
    ['auto', 'Auto'],
    ['continuous', 'Continuous'],
    ['manual', 'Manual']
  ], 'auto', async (v) => {
    await fetchJSON(`/api/${cam.id}/controls`, { method: 'POST', body: JSON.stringify({ af_mode: v }) });
  }));

  controls.appendChild(makeRange(`lens_${cam.id}`, 'Lens Position', 0.0, 10.0, 0.05, 1.0, async (v) => {
    await fetchJSON(`/api/${cam.id}/controls`, { method: 'POST', body: JSON.stringify({ lens_position: v }) });
  }));

  const afBtns = document.createElement('div');
  afBtns.className = 'btns';
  const afStart = document.createElement('button');
  afStart.textContent = 'AF Start';
  afStart.onclick = async () => { await fetchJSON(`/api/${cam.id}/af_trigger`, { method: 'POST', body: JSON.stringify({ trigger: 'start' }) }); };
  const afCancel = document.createElement('button');
  afCancel.textContent = 'AF Cancel';
  afCancel.onclick = async () => { await fetchJSON(`/api/${cam.id}/af_trigger`, { method: 'POST', body: JSON.stringify({ trigger: 'cancel' }) }); };
  afBtns.appendChild(afStart);
  afBtns.appendChild(afCancel);
  controls.appendChild(afBtns);

  const toneRow = document.createElement('div');
  toneRow.className = 'group';
  toneRow.appendChild(makeRange(`bright_${cam.id}`, 'Brightness', -1.0, 1.0, 0.05, 0.0, async (v) => {
    await fetchJSON(`/api/${cam.id}/controls`, { method: 'POST', body: JSON.stringify({ brightness: v }) });
  }));
  toneRow.appendChild(makeRange(`contrast_${cam.id}`, 'Contrast', 0.0, 2.5, 0.05, 1.0, async (v) => {
    await fetchJSON(`/api/${cam.id}/controls`, { method: 'POST', body: JSON.stringify({ contrast: v }) });
  }));
  toneRow.appendChild(makeRange(`saturation_${cam.id}`, 'Saturation', 0.0, 2.5, 0.05, 1.0, async (v) => {
    await fetchJSON(`/api/${cam.id}/controls`, { method: 'POST', body: JSON.stringify({ saturation: v }) });
  }));
  toneRow.appendChild(makeRange(`sharpness_${cam.id}`, 'Sharpness', 0.0, 5.0, 0.1, 1.0, async (v) => {
    await fetchJSON(`/api/${cam.id}/controls`, { method: 'POST', body: JSON.stringify({ sharpness: v }) });
  }));
  controls.appendChild(toneRow);

  const capRow = document.createElement('div');
  capRow.className = 'btns';
  const capBtn = document.createElement('button');
  capBtn.textContent = 'Capture Still';
  const capLink = document.createElement('a');
  capLink.className = 'caplink';
  capLink.target = '_blank';
  capBtn.onclick = async () => {
    capBtn.disabled = true;
    try {
      const res = await fetchJSON(`/api/${cam.id}/capture`, { method: 'POST' });
      capLink.href = res.url;
      capLink.textContent = res.filename;
    } catch (e) {
      alert('Capture failed: ' + e);
    } finally {
      capBtn.disabled = false;
    }
  };
  capRow.appendChild(capBtn);
  capRow.appendChild(capLink);
  controls.appendChild(capRow);

  row.appendChild(controls);
  container.appendChild(row);
  return container;
}

async function init() {
  try {
    const data = await fetchJSON('/api/cameras');
    const cams = data.cameras || [];
    const root = document.getElementById('cameras');
    for (const cam of cams) {
      const el = await buildCamera(cam);
      root.appendChild(el);
    }
  } catch (e) {
    document.getElementById('cameras').innerHTML = `<p class="err">Failed to load cameras: ${e}</p>`;
  }
}

init();

