'use strict';
(() => {
  const lip = window.lip;
  const $ = (id) => document.getElementById(id);
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const round1 = (v) => Math.round(v * 10) / 10;
  const round2 = (v) => Math.round(v * 100) / 100;
  const round3 = (v) => Math.round(v * 1000) / 1000;
  const round4 = (v) => Math.round(v * 10000) / 10000;

  const S = {
    imagePath: null, audioPath: null, dur: 0, start: 0, end: 0, next: 'start',
    opts: null, aspect: null, model: null, isolate: false, multi: false,
    peaks: null, player: null, audioTicket: 0, jobs: new Map(), resultPath: null,
    rings: [], unison: true, tracks: [], singAlong: false,
  };
  const maxSingers = () => (S.opts && S.opts.max_singers) || 4;
  const RING_COLORS = [
    { ring: '#ff2bd6', text: '#ff6fe6' }, { ring: '#19e6ff', text: '#6fefff' },
    { ring: '#8b5cff', text: '#b9a3ff' }, { ring: '#ffb000', text: '#ffd36b' },
  ];

  // ---------- backend ----------
  async function call(p, o = {}) {
    let res;
    try {
      res = await fetch(lip.api + p, {
        method: o.method || 'GET',
        headers: Object.assign({ 'X-Lip-Token': lip.token }, o.body ? { 'Content-Type': 'application/json' } : {}),
        body: o.body ? JSON.stringify(o.body) : undefined,
      });
    } catch (e) { throw new Error('Cannot reach the Lip Service backend.'); }
    if (!res.ok) {
      let msg = 'The backend said no (' + res.status + ').';
      try { const j = await res.json(); if (j && j.error) msg = j.error; } catch (e) { /* keep default */ }
      throw new Error(msg);
    }
    return res;
  }
  const getJson = async (p, o) => (await call(p, o)).json();

  // ---------- helpers ----------
  function fmt(t) {
    // Tenths normally (0:05.1). A typed time with hundredths keeps them (0:09.24) so the box shows what is sent.
    const hund = Math.max(0, Math.round(t * 100));
    const two = hund % 10 !== 0;
    const per = two ? 100 : 10, unit = two ? hund : hund / 10;
    const m = Math.floor(unit / (60 * per)), rem = unit - m * 60 * per;
    const s = Math.floor(rem / per), frac = rem % per;
    return m + ':' + (s < 10 ? '0' : '') + s + '.' + (two ? (frac < 10 ? '0' : '') + frac : frac);
  }
  function parseTime(text) {
    const m = /^\s*(?:(\d+):)?(\d+(?:\.\d+)?)\s*$/.exec(text);
    if (!m) return null;
    return (m[1] ? Number(m[1]) * 60 : 0) + Number(m[2]);
  }
  function fileUrl(p) {
    const parts = p.replace(/\\/g, '/').split('/');
    return 'file:///' + parts.map((s, i) => (i === 0 && /^[A-Za-z]:$/.test(s)) ? s : encodeURIComponent(s)).join('/');
  }
  function baseName(p) { return p.slice(Math.max(p.lastIndexOf('\\'), p.lastIndexOf('/')) + 1); }
  function stem(p) { const b = baseName(p); const i = b.lastIndexOf('.'); return i > 0 ? b.slice(0, i) : b; }
  function showLine(el, text) { el.textContent = text || ''; el.hidden = !text; }
  function ext(name) { const i = name.lastIndexOf('.'); return i < 0 ? '' : name.slice(i + 1).toLowerCase(); }
  const IMAGE_EXT = ['png', 'jpg', 'jpeg', 'webp', 'bmp'];
  const AUDIO_EXT = ['wav', 'mp3', 'flac', 'm4a', 'ogg', 'aac'];
  const AUDIO_ACCEPT = '.wav,.mp3,.flac,.m4a,.ogg,.aac';

  // ---------- window buttons and status light ----------
  $('wMin').addEventListener('click', () => lip.windowControl('minimize'));
  $('wMax').addEventListener('click', () => lip.windowControl('maximize'));
  $('wClose').addEventListener('click', () => lip.windowControl('close'));

  function setLight(kind, text) {
    $('light').className = 'light' + (kind ? ' ' + kind : '');
    $('lightText').textContent = text;
  }
  async function pollStatus() {
    try {
      const s = await getJson('/status');
      S.ram = { free: s.ram_free_gb, needed: s.ram_needed_gb, ok: s.ram_ok }; updateRamWarn();
      if (s.restarting) setLight('pink', 'Restarting ComfyUI');
      else if (s.comfyui) setLight('', 'ComfyUI connected');
      else setLight('grey', 'ComfyUI not running');
    } catch (e) { setLight('grey', 'ComfyUI not running'); }
    if (!S.opts) loadOptions();
  }

  // ---------- drag and drop ----------
  const IMG_PROMPT = 'Drop an image here, or click to choose one';
  const AUD_PROMPT = 'Drop an audio file here, or click to choose one';
  // Drag and drop (unchanged from phase 1).
  function wireDrop(el, onFile) {
    let depth = 0;
    el.addEventListener('dragenter', (e) => { e.preventDefault(); depth++; el.classList.add('over'); });
    el.addEventListener('dragover', (e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; });
    el.addEventListener('dragleave', () => { depth = Math.max(0, depth - 1); if (!depth) el.classList.remove('over'); });
    el.addEventListener('drop', (e) => {
      e.preventDefault(); depth = 0; el.classList.remove('over');
      const f = e.dataTransfer.files && e.dataTransfer.files[0];
      if (f) onFile(f);
    });
  }
  // Click to choose a file: a hidden file input, opened from the zone, its Change file link, or Enter and Space.
  // The chosen file goes through exactly the same function as a dropped one.
  function wirePick(zone, input, onFile, shouldOpen) {
    const open = () => { input.value = ''; input.click(); };
    input.addEventListener('change', () => { const f = input.files && input.files[0]; input.value = ''; if (f) onFile(f); });
    zone.addEventListener('click', (e) => { if (e.target.closest('input')) return; if (shouldOpen(e)) open(); });
    zone.addEventListener('keydown', (e) => {
      if (e.target !== zone || (e.key !== 'Enter' && e.key !== ' ')) return;
      e.preventDefault(); open();
    });
    return open;
  }
  // A file dropped outside a zone must never navigate the window.
  document.addEventListener('dragover', (e) => e.preventDefault());
  document.addEventListener('drop', (e) => e.preventDefault());

  // ---------- 1. image ----------
  const img = $('imageImg');
  img.addEventListener('error', () => {
    showLine($('imageErr'), 'That image could not be opened.');
    img.hidden = true; $('imageName').hidden = true; $('imageChange').hidden = true; $('imageEmpty').hidden = false; S.imagePath = null;
  });
  function loadImageFile(file) {
    const p = lip.pathFor(file);
    if (!p) { showLine($('imageErr'), 'Could not read the path of that file.'); return; }
    if (!IMAGE_EXT.includes(ext(file.name))) { showLine($('imageErr'), 'That is not an image file. Use png, jpg, webp or bmp.'); return; }
    showLine($('imageErr'), '');
    S.imagePath = p;
    S.rings = []; S.tracks = []; renderTracks();
    img.src = fileUrl(p);
    img.hidden = false; $('imageEmpty').hidden = true;
    $('imageName').textContent = file.name; $('imageName').hidden = false;
    $('imageChange').hidden = false; $('imageZone').setAttribute('aria-label', 'Image: ' + file.name + '. Click to change.');
  }
  wireDrop($('imageZone'), loadImageFile);
  // In Multiple mode a click on a loaded picture places a ring, so the Change file link opens the picker there.
  const openImage = wirePick($('imageZone'), $('fileImage'), loadImageFile, (e) => !(S.multi && S.imagePath) && !e.target.closest('button'));
  $('imageChange').addEventListener('click', (e) => { e.stopPropagation(); openImage(); });

  // ---------- 2. audio and waveform ----------
  const wave = $('wave'), canvas = $('waveCanvas'), selBox = $('selBox');

  function drawWave() {
    const w = wave.clientWidth, h = wave.clientHeight, dpr = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.round(w * dpr)); canvas.height = Math.max(1, Math.round(h * dpr));
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    if (!S.peaks) return;
    const g = ctx.createLinearGradient(0, 0, w, 0);
    g.addColorStop(0, '#ff2bd6'); g.addColorStop(0.55, '#8b5cff'); g.addColorStop(1, '#19e6ff');
    ctx.fillStyle = g;
    const step = 3, bars = Math.floor(w / step), n = S.peaks.length;
    for (let i = 0; i < bars; i++) {
      const a = Math.floor(i / bars * n), b = Math.max(a + 1, Math.floor((i + 1) / bars * n));
      let m = 0;
      for (let k = a; k < b && k < n; k++) m = Math.max(m, S.peaks[k]);
      const bh = Math.max(2, m * h * 0.9);
      ctx.fillRect(i * step, (h - bh) / 2, 2, bh);
    }
  }
  new ResizeObserver(drawWave).observe(wave);

  function selError() {
    if (!S.audioPath || !S.dur) return null;
    return S.end > S.start ? null : 'End must be after start.';
  }
  function updateSel(skip) {
    const has = !!S.audioPath && S.dur > 0;
    selBox.hidden = !has;
    if (has) {
      const l = clamp(S.start / S.dur, 0, 1) * 100, r = clamp(S.end / S.dur, 0, 1) * 100;
      selBox.style.left = l + '%'; selBox.style.width = Math.max(0, r - l) + '%';
    }
    if (skip !== 'start') $('tStart').value = fmt(S.start);
    if (skip !== 'end') $('tEnd').value = fmt(S.end);
    const err = selError();
    $('tStart').classList.toggle('bad', !!err); $('tEnd').classList.toggle('bad', !!err);
    showLine($('timeErr'), err);
    updateWarn();
  }
  function setSel(start, end, skip) {
    stopPlay();
    S.start = round2(clamp(start, 0, S.dur)); S.end = round2(clamp(end, 0, S.dur));
    updateSel(skip);
  }
  function updateWarn() {
    const len = S.end - S.start;
    const limit = S.opts && S.opts.limits ? S.opts.limits.warn_seconds : Infinity;
    const show = !!S.audioPath && len > limit;
    $('warn').hidden = !show;
    if (show) $('warnText').textContent = 'This selection is ' + len.toFixed(1) + ' s. It is longer than one render can handle for now, so it may fail or take very long. Pick a shorter part until stitching is built.';
  }

  async function loadAudioFile(file) {
    const p = lip.pathFor(file);
    if (!p) { showLine($('audioErr'), 'Could not read the path of that file.'); return; }
    if (!AUDIO_EXT.includes(ext(file.name))) { showLine($('audioErr'), 'That is not an audio file. Use wav, mp3, flac, m4a, ogg or aac.'); return; }
    showLine($('audioErr'), '');
    const ticket = ++S.audioTicket;
    stopPlay();
    $('audioName').textContent = file.name; $('audioDur').textContent = '';
    try {
      const info = await getJson('/audio/info', { method: 'POST', body: { path: p } });
      if (ticket !== S.audioTicket) return;
      S.audioPath = p; S.dur = info.duration; S.peaks = info.peaks; S.next = 'start';
      $('audioDur').textContent = fmt(S.dur);
      $('waveEmpty').hidden = true; $('audioChange').hidden = false; $('audioZone').classList.add('loaded');
      drawWave();
      setSel(0, S.dur);
    } catch (e) {
      if (ticket !== S.audioTicket) return;
      showLine($('audioErr'), 'Could not read that audio. ' + e.message);
      if (!S.audioPath) $('audioName').textContent = AUD_PROMPT;
      else $('audioName').textContent = baseName(S.audioPath);
    }
  }
  wireDrop($('audioZone'), loadAudioFile);
  // Empty card: a click anywhere opens the picker. Loaded: only Change file does (the waveform sets start and end).
  const openAudio = wirePick($('audioZone'), $('fileAudio'), loadAudioFile, (e) => !S.audioPath && !e.target.closest('button'));
  $('audioChange').addEventListener('click', (e) => { e.stopPropagation(); openAudio(); });

  function timeAt(clientX) {
    const r = wave.getBoundingClientRect();
    return round1(clamp((clientX - r.left) / r.width, 0, 1) * S.dur);
  }
  // Click the waveform: first click sets the start, the next sets the end, and so on.
  wave.addEventListener('click', (e) => {
    if (!S.audioPath) return;
    const t = timeAt(e.clientX);
    if (S.next === 'start') {
      setSel(t, S.end > t ? S.end : S.dur);
      S.next = 'end';
    } else {
      if (t >= S.start) setSel(S.start, t); else setSel(t, S.start);
      S.next = 'start';
    }
  });
  function dragHandle(el, which) {
    el.addEventListener('click', (e) => e.stopPropagation());
    el.addEventListener('pointerdown', (e) => {
      e.preventDefault(); e.stopPropagation();
      el.setPointerCapture(e.pointerId);
      const move = (ev) => {
        const t = timeAt(ev.clientX);
        if (which === 'start') setSel(Math.min(t, S.end - 0.1), S.end);
        else setSel(S.start, Math.max(t, S.start + 0.1));
      };
      const up = () => { el.removeEventListener('pointermove', move); el.removeEventListener('pointerup', up); el.removeEventListener('pointercancel', up); };
      el.addEventListener('pointermove', move); el.addEventListener('pointerup', up); el.addEventListener('pointercancel', up);
    });
  }
  dragHandle($('hStart'), 'start'); dragHandle($('hEnd'), 'end');

  function wireTime(input, which) {
    const apply = () => {
      if (!S.audioPath) { input.value = '0:00.0'; return; }
      const t = parseTime(input.value);
      if (t === null) { showLine($('timeErr'), 'Type the time like 0:05.1'); input.classList.add('bad'); return; }
      if (which === 'start') setSel(t, S.end); else setSel(S.start, t);
    };
    input.addEventListener('change', apply);
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { apply(); input.blur(); } });
    input.addEventListener('focus', () => input.select());
  }
  wireTime($('tStart'), 'start'); wireTime($('tEnd'), 'end');

  // Play selection / stop
  function setPlayLabel(playing) { $('btnPlay').textContent = playing ? '■ Stop' : '▶ Play selection'; }
  function stopPlay() {
    const pl = S.player;
    if (!pl) return;
    S.player = null; pl.cancelled = true;
    if (pl.audio) { pl.audio.pause(); pl.audio.removeAttribute('src'); }
    if (pl.url) URL.revokeObjectURL(pl.url);
    setPlayLabel(false);
  }
  $('btnPlay').addEventListener('click', async () => {
    if (S.player) { stopPlay(); return; }
    if (!S.audioPath) { showLine($('audioErr'), 'Add audio first.'); return; }
    if (selError()) return;
    showLine($('audioErr'), '');
    const pl = { cancelled: false, audio: null, url: null };
    S.player = pl; setPlayLabel(true);
    try {
      const q = '?path=' + encodeURIComponent(S.audioPath) + '&start=' + S.start + '&end=' + S.end;
      const blob = await (await call('/audio/segment' + q)).blob();
      if (pl.cancelled) return;
      pl.url = URL.createObjectURL(blob);
      pl.audio = new Audio(pl.url);
      pl.audio.addEventListener('ended', () => { if (S.player === pl) stopPlay(); });
      pl.audio.addEventListener('error', () => { if (S.player === pl) stopPlay(); });
      await pl.audio.play();
    } catch (e) {
      if (S.player === pl) { stopPlay(); if (e && e.message) showLine($('audioErr'), e.message); }
    }
  });

  // Unmarked people sing along (Multiple mode only)
  $('swSingAlong').addEventListener('click', () => {
    S.singAlong = !S.singAlong;
    $('swSingAlong').classList.toggle('on', S.singAlong); $('swSingAlong').classList.toggle('off', !S.singAlong);
    $('swSingAlong').setAttribute('aria-checked', String(S.singAlong));
  });

  // Isolate the vocal switch
  $('swIsolate').addEventListener('click', () => {
    S.isolate = !S.isolate;
    $('swIsolate').classList.toggle('on', S.isolate); $('swIsolate').classList.toggle('off', !S.isolate);
    $('swIsolate').setAttribute('aria-checked', String(S.isolate));
    $('isoState').textContent = (S.isolate ? 'On' : 'Off') + '. For full mixes or noisy audio.';
  });

  // ---------- 4. singers: rings on the image ----------
  // Rings are stored as fractions of the ORIGINAL image (x of width, y of height, r of width)
  // and drawn over the displayed image, which sits inside the zone with object-fit: contain.
  function imgRect() {
    const z = $('imageZone'), nw = img.naturalWidth, nh = img.naturalHeight;
    if (!S.imagePath || !nw || !nh) return null;
    const s = Math.min(z.clientWidth / nw, z.clientHeight / nh), w = nw * s, h = nh * s;
    return { x: (z.clientWidth - w) / 2, y: (z.clientHeight - h) / 2, w, h };
  }
  function layoutRings() {
    const box = $('rings'); box.textContent = '';
    box.hidden = !S.multi;
    const R = imgRect();
    if (!S.multi || !R) return;
    S.rings.forEach((g, i) => {
      const c = RING_COLORS[i % RING_COLORS.length], dia = 2 * g.r * R.w;
      const d = document.createElement('div');
      d.className = 'ring'; d.textContent = String(i + 1);
      d.style.cssText = 'left:' + (R.x + g.x * R.w - dia / 2) + 'px;top:' + (R.y + g.y * R.h - dia / 2) + 'px;width:' + dia + 'px;height:' + dia + 'px;border-color:' + c.ring + ';color:' + c.text;
      d.dataset.x = g.x; d.dataset.y = g.y; d.dataset.r = g.r.toFixed(3);
      d.title = 'Click to remove. Scroll to resize.';
      d.addEventListener('click', (e) => { e.stopPropagation(); removeRing(i); });
      d.addEventListener('wheel', (e) => {
        e.preventDefault(); e.stopPropagation();
        g.r = clamp(round3(g.r + (e.deltaY < 0 ? 0.005 : -0.005)), 0.01, 0.15);
        layoutRings();
      }, { passive: false });
      box.appendChild(d);
    });
  }
  function removeRing(i) {
    S.rings.splice(i, 1);
    if (i >= 1) S.tracks.splice(i - 1, 1);
    showLine($('imageErr'), '');
    layoutRings(); renderTracks();
  }
  $('imageZone').addEventListener('click', (e) => {
    if (!S.multi) return;
    const R = imgRect(); if (!R) return;
    const z = $('imageZone'), b = z.getBoundingClientRect();
    const px = e.clientX - b.left - z.clientLeft - R.x, py = e.clientY - b.top - z.clientTop - R.y;
    if (px < 0 || py < 0 || px > R.w || py > R.h) return;
    if (S.rings.length >= maxSingers()) { showLine($('imageErr'), 'The most singers in one shot is ' + maxSingers() + '.'); return; }
    showLine($('imageErr'), '');
    S.rings.push({ x: round4(px / R.w), y: round4(py / R.h), r: 0.03 });
    layoutRings(); renderTracks();
  });
  img.addEventListener('load', layoutRings);
  new ResizeObserver(layoutRings).observe($('imageZone'));

  // ---------- 4. singers: single or multiple, unison or separate ----------
  function setMulti(on) {
    S.multi = on;
    $('btnSingle').classList.toggle('sel', !on); $('btnMulti').classList.toggle('sel', on);
    $('multiHint').hidden = !on; $('unisonRow').hidden = !on;
    $('multiHint').textContent = 'Multiple is on: click each face to mark a singer. Up to ' + maxSingers() + '. Click a ring to remove it.';
    showLine($('imageErr'), '');
    layoutRings(); renderTracks();
  }
  function setUnison(on) {
    S.unison = on;
    $('btnSame').classList.toggle('sel', on); $('btnSeparate').classList.toggle('sel', !on);
    renderTracks();
  }
  // One small drop zone per ring after the first (the main audio is Singer 1).
  function renderTracks() {
    const box = $('extraTracks'), on = S.multi && !S.unison;
    box.textContent = ''; box.hidden = !on; $('s1note').hidden = !on;
    if (!on) return;
    S.tracks.length = Math.min(S.tracks.length, Math.max(0, S.rings.length - 1));
    for (let k = 0; k < S.rings.length - 1; k++) {
      const t = S.tracks[k];
      const z = document.createElement('div'); z.className = 'track zone pick'; z.dataset.singer = String(k + 2);
      const n = document.createElement('span'); n.className = 'tn'; n.textContent = 'Singer ' + (k + 2) + ' track';
      const f = document.createElement('span'); f.className = 'tf' + (t ? ' has' : ''); f.textContent = t ? t.name : AUD_PROMPT;
      z.tabIndex = 0; z.setAttribute('role', 'button'); z.setAttribute('aria-label', 'Singer ' + (k + 2) + ' track');
      const inp = document.createElement('input'); inp.type = 'file'; inp.hidden = true; inp.dataset.pick = 'track-' + (k + 2);
      inp.accept = AUDIO_ACCEPT;
      z.append(n, f, inp);
      if (t) {
        const x = document.createElement('button'); x.type = 'button'; x.className = 'qx'; x.textContent = '×'; x.setAttribute('aria-label', 'Clear Singer ' + (k + 2) + ' track');
        x.addEventListener('click', (e) => { e.stopPropagation(); S.tracks[k] = null; renderTracks(); });
        z.appendChild(x);
      }
      const loadTrack = (file) => {
        const p = lip.pathFor(file);
        if (!p) { f.textContent = 'Could not read the path of that file.'; f.className = 'tf bad'; return; }
        if (!AUDIO_EXT.includes(ext(file.name))) { f.textContent = 'That is not an audio file.'; f.className = 'tf bad'; return; }
        S.tracks[k] = { path: p, name: file.name }; renderTracks();
      };
      wireDrop(z, loadTrack);
      wirePick(z, inp, loadTrack, (e) => !e.target.closest('button'));
      box.appendChild(z);
    }
  }
  $('btnSingle').addEventListener('click', () => setMulti(false));
  $('btnMulti').addEventListener('click', () => setMulti(true));
  $('btnSame').addEventListener('click', () => setUnison(true));
  $('btnSeparate').addEventListener('click', () => setUnison(false));

  // ---------- options: quality, aspect, model ----------
  async function loadOptions() {
    if (S.loadingOpts) return;
    S.loadingOpts = true;
    try {
      const o = await getJson('/options');
      S.opts = o;
      buildQuality(o.quality);

      const box = $('aspects'); box.textContent = '';
      const def = o.aspects.find((a) => a.default && a.enabled) || o.aspects.find((a) => a.enabled);
      S.aspect = def ? def.id : null;
      for (const a of o.aspects) {
        const b = document.createElement('button');
        b.type = 'button'; b.className = 'btn' + (a.id === S.aspect ? ' sel' : ''); b.textContent = a.label; b.dataset.id = a.id;
        if (!a.enabled) { b.setAttribute('aria-disabled', 'true'); b.title = a.note || ''; }
        b.addEventListener('click', () => {
          if (!a.enabled) return;
          S.aspect = a.id;
          for (const x of box.children) x.classList.toggle('sel', x === b);
        });
        box.appendChild(b);
      }

      const dm = o.models.find((m) => m.default) || o.models[0];
      S.model = dm ? dm.id : null;
      buildModels();
      updateWarn();
    } catch (e) { /* the 3 second status poll tries again */ }
    S.loadingOpts = false;
  }
  // Quality: a snapping slider with one stop per entry of quality.positions (index based: 0, 1, 2).
  // A position that is not enabled is dimmed with its note and the slider never rests on it.
  function buildQuality(spec) {
    const q = $('quality'), box = $('qlabels'), pos = (spec && spec.positions) || [];
    box.textContent = '';
    S.qpos = pos;
    if (!pos.length) { q.disabled = true; return; }
    q.min = '0'; q.max = String(pos.length - 1); q.step = '1'; q.disabled = false;
    const nearestEnabled = (i) => {
      let best = -1;
      pos.forEach((p, k) => { if (p.enabled !== false && (best < 0 || Math.abs(k - i) < Math.abs(best - i))) best = k; });
      return best;
    };
    let start = pos.findIndex((p) => p.value === spec.default);
    if (start < 0 || pos[start].enabled === false) start = nearestEnabled(1);
    S.qidx = Math.max(0, start);
    pos.forEach((p, k) => {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'ql'; b.textContent = p.label; b.dataset.pos = p.id; b.tabIndex = -1;
      if (p.enabled === false) { b.setAttribute('aria-disabled', 'true'); b.title = p.note || ''; }
      b.addEventListener('click', () => { if (p.enabled !== false) setQuality(k); });
      box.appendChild(b);
    });
    q.addEventListener('input', () => {
      const k = Number(q.value);
      if (pos[k] && pos[k].enabled === false) { q.value = String(S.qidx); return; }
      setQuality(k);
    });
    setQuality(S.qidx);
  }
  function setQuality(k) {
    const q = $('quality'), pos = S.qpos;
    if (!pos || !pos[k] || pos[k].enabled === false) return;
    S.qidx = k; q.value = String(k);
    q.style.setProperty('--pct', (pos.length > 1 ? k / (pos.length - 1) * 100 : 0) + '%');
    q.setAttribute('aria-valuetext', pos[k].label);
    for (const b of $('qlabels').children) b.classList.toggle('cur', b.dataset.pos === pos[k].id);
    updateRamWarn();
  }
  const qualityValue = () => (S.qpos && S.qpos[S.qidx] ? S.qpos[S.qidx].value : 0.5);
  // A render peaks near ram_needed_gb + 4 GB of memory in every quality position. When the PC is short
  // of free memory this is a notice only: it never blocks, dims or changes a render.
  function updateRamWarn() {
    const st = S.ram;
    const show = !!st && st.ok === false;
    $('ramNotice').hidden = !show;
    if (show) $('ramNoticeText').textContent = 'Notice: your PC has ' + (Math.round(st.free * 10) / 10) + ' GB of memory free right now and a render peaks near ' + (st.needed + 4) + ' GB. It should still work. Closing other programs first makes it safer.';
  }
  function modelText(m) { return m.label + (m.default ? ' (default)' : ''); }
  function buildModels() {
    const list = $('modelList'); list.textContent = '';
    const models = S.opts.models;
    if (!models.length) { $('modelLabel').textContent = 'No models found'; return; }
    for (const m of models) {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'mi' + (m.id === S.model ? ' cur' : ''); b.textContent = modelText(m);
      b.setAttribute('role', 'option');
      b.addEventListener('click', () => { S.model = m.id; buildModels(); closeMenu(); });
      list.appendChild(b);
    }
    const cur = models.find((m) => m.id === S.model);
    $('modelLabel').textContent = cur ? modelText(cur) : '';
  }
  function closeMenu() { $('modelList').hidden = true; $('modelBtn').setAttribute('aria-expanded', 'false'); }
  $('modelBtn').addEventListener('click', (e) => {
    e.stopPropagation();
    if (!S.opts || !S.opts.models.length) return;
    const open = $('modelList').hidden;
    $('modelList').hidden = !open; $('modelBtn').setAttribute('aria-expanded', String(open));
  });
  document.addEventListener('click', (e) => { if (!$('modelList').contains(e.target)) closeMenu(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeMenu(); });

  // ---------- render ----------
  function validate() {
    if (!S.imagePath) return 'Add an image first.';
    if (!S.audioPath) return 'Add audio first.';
    if (selError()) return 'End must be after start.';
    if (S.multi) {
      if (!S.rings.length) return "Click each singer's face on the image first.";
      if (!S.unison) for (let n = 2; n <= S.rings.length; n++) if (!S.tracks[n - 2]) return 'Add a track for singer ' + n + '.';
    }
    if (!S.opts || !S.model || !S.aspect) return 'Options are still loading. Try again in a moment.';
    return null;
  }
  $('btnRender').addEventListener('click', async () => {
    const bad = validate();
    showLine($('formError'), bad);
    if (bad) return;
    const btn = $('btnRender'); btn.disabled = true;
    try {
      await getJson('/jobs', { method: 'POST', body: {
        shot: S.imagePath, audio: S.audioPath, start: S.start, end: S.end >= S.dur - 0.05 ? 0 : S.end,
        prompt: $('prompt').value, negative_prompt: '', isolate_vocals: S.isolate,
        singers: S.multi ? S.rings.map((g) => ({ x: g.x, y: g.y, r: g.r })) : [],
        unison: S.multi ? S.unison : true,
        sing_along: S.multi ? S.singAlong : false,
        singer_audios: S.multi && !S.unison ? [S.audioPath].concat(S.tracks.map((t) => t.path)) : [],
        quality: qualityValue(), aspect: S.aspect, model: S.model,
      } });
      pollJobs();
    } catch (e) { showLine($('formError'), e.message); }
    btn.disabled = false;
  });

  // ---------- 8. queue and result ----------
  const STATUS_TEXT = { queued: 'Queued', running: 'Running', done: 'Done', failed: 'Failed', cancelled: 'Cancelled' };
  function mmss(sec) { const s = Math.max(0, Math.floor(sec)); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); }

  function makeRow(id) {
    const row = document.createElement('div'); row.className = 'qr'; row.dataset.id = id;
    row.innerHTML = '<span class="dot"></span><span class="qtxt"><div class="qname"></div><div class="qnote"></div></span><span class="qst"></span>';
    return row;
  }
  function updateRow(row, j) {
    const restarting = /restarting comfyui/i.test(j.note || '') && (j.status === 'running' || j.status === 'queued');
    row.className = 'qr ' + j.status + (restarting ? ' restarting' : '');
    row.querySelector('.qname').textContent = stem(j.shot) + ', ' + Number(j.seconds).toFixed(1) + ' s';
    const note = row.querySelector('.qnote');
    note.textContent = j.status === 'done' ? '' : (j.note || ''); note.hidden = !note.textContent;
    row.querySelector('.qst').textContent = STATUS_TEXT[j.status] + (j.status === 'running' ? ' ' + mmss(j.elapsed) : '');
    // Every row except a running one gets an x that removes it from the list (no video file is deleted).
    let x = row.querySelector('.qx');
    if (j.status === 'running') { if (x) x.remove(); return; }
    if (!x) {
      x = document.createElement('button'); x.type = 'button'; x.className = 'qx'; x.textContent = '×';
      x.addEventListener('click', async () => {
        try { await getJson('/jobs/' + encodeURIComponent(row.dataset.id) + '/remove', { method: 'POST' }); } catch (e) { /* the refresh shows the real state */ }
        refreshJobs();
      });
      row.appendChild(x);
    }
    const tip = j.status === 'queued' ? 'Cancel and remove' : 'Remove from the list';
    x.title = tip; x.setAttribute('aria-label', tip);
  }
  function renderJobs(jobs) {
    const q = $('queue');
    const ids = new Set(jobs.map((j) => j.id));
    for (const [id, row] of S.jobs) if (!ids.has(id)) { row.remove(); S.jobs.delete(id); }
    const empty = q.querySelector('.q-empty');
    if (jobs.length && empty) empty.remove();
    if (!jobs.length && !empty) q.innerHTML = '<div class="q-empty">Nothing in the queue yet</div>';
    jobs.forEach((j, i) => {
      let row = S.jobs.get(j.id);
      if (!row) { row = makeRow(j.id); S.jobs.set(j.id, row); }
      updateRow(row, j);
      if (q.children[i] !== row) q.insertBefore(row, q.children[i] || null);
    });
    const canClear = jobs.some((j) => j.status === 'done' || j.status === 'failed' || j.status === 'cancelled');
    $('btnClear').setAttribute('aria-disabled', String(!canClear));
    // A removed row never blanks the player: it keeps its video until a newer finished job exists.
    const newest = jobs.find((j) => j.status === 'done' && j.result);
    if (newest && (!S.resultPath || newest.added > S.resultAdded)) { S.resultAdded = newest.added; showResult(newest.result); }
  }
  function showResult(p) {
    if (p === S.resultPath) return;
    S.resultPath = p;
    const v = $('resultVideo');
    $('resultPath').textContent = p || ''; $('resultPath').title = p || '';
    if (p) { v.src = fileUrl(p); v.hidden = false; $('resultEmpty').hidden = true; }
    else { v.removeAttribute('src'); v.hidden = true; $('resultEmpty').hidden = false; }
  }
  let jobsBusy = false;
  async function pollJobs() {
    if (jobsBusy) return;
    jobsBusy = true;
    try { renderJobs((await getJson('/jobs')).jobs); } catch (e) { /* backend not up yet */ }
    jobsBusy = false;
  }
  // Refresh at once, even if a timed poll is in flight.
  async function refreshJobs() {
    try { renderJobs((await getJson('/jobs')).jobs); } catch (e) { /* backend not up yet */ }
  }
  $('btnClear').addEventListener('click', async () => {
    if ($('btnClear').getAttribute('aria-disabled') === 'true') return;
    try { await getJson('/jobs/clear', { method: 'POST' }); } catch (e) { /* the refresh shows the real state */ }
    refreshJobs();
  });
  $('btnFolder').addEventListener('click', async () => {
    if (!S.resultPath) return;
    try { await getJson('/open-folder', { method: 'POST', body: { path: S.resultPath.slice(0, Math.max(S.resultPath.lastIndexOf('\\'), S.resultPath.lastIndexOf('/'))) } }); }
    catch (e) { showLine($('formError'), e.message); }
  });

  // ---------- go ----------
  pollStatus(); pollJobs();
  setInterval(pollStatus, 3000);
  setInterval(pollJobs, 2000);
})();
