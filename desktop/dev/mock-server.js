'use strict';
// Fake Lip Service backend for testing the screen. Plain Node, no packages.
// Run alone:  node dev\mock-server.js      (needs LIPSERVICE_TOKEN in the environment)
// Or used by main.js --smoke through start().
// Implements every endpoint in docs\api.md on 127.0.0.1:8780 with fake data and fake job progress.
// Extra mock-only helpers (not part of the contract): GET /_mock/log, GET /_mock/set?restarting=1
const http = require('http');
const fs = require('fs');
const path = require('path');

const PORT = Number(process.env.LIP_TEST_PORT) || 8780; // 8780 unless a test asks for another port
const OUTPUTS = 'D:\\Project_lip_service\\outputs';

function newestMp4() {
  try {
    const files = fs.readdirSync(OUTPUTS).filter(f => f.toLowerCase().endsWith('.mp4'))
      .map(f => ({ f, t: fs.statSync(path.join(OUTPUTS, f)).mtimeMs })).sort((a, b) => b.t - a.t);
    if (files.length) return OUTPUTS + '\\' + files[0].f;
  } catch (e) { /* no outputs folder: use a fake name */ }
  return OUTPUTS + '\\mock-result.mp4';
}

function start(opts = {}) {
  const token = opts.token || process.env.LIPSERVICE_TOKEN || '';
  const runSeconds = Number(opts.runSeconds || process.env.MOCK_RUN_SECONDS || 6);
  const warnSeconds = Number(opts.warnSeconds || process.env.MOCK_WARN_SECONDS || 5);
  const log = [];
  const state = { restarting: false, bestEnabled: true, ramOk: true, hold: false, _holdAt: 0 }; // hold: freeze the running job (tests)
  const now = () => Date.now() / 1000;
  let counter = 0;
  const jobs = [];

  jobs.push({ id: '20261028-161257-1dbe', status: 'done', added: now() - 3600, shot: 'D:\\pics\\choir.png',
    audio: 'D:\\audio\\hear-ye.wav', seconds: 3.2, note: 'finished', result: newestMp4(), elapsed: 780, _t0: 0 });
  jobs.push({ id: '20261028-150000-77aa', status: 'failed', added: now() - 7200, shot: 'D:\\pics\\witch.png',
    audio: 'D:\\audio\\witch.wav', seconds: 3.1, note: 'ComfyUI ran out of memory. Try a shorter part.', result: null, elapsed: 95, _t0: 0 });

  function tick() {
    const running = jobs.find(j => j.status === 'running');
    if (running && state.hold) {
      // Frozen: stays running, progress stops until released (so tests do not depend on timing).
      if (!state._holdAt) state._holdAt = now();
      running.elapsed = state._holdAt - running._t0;
      if (running.note === 'starting' || running.note === 'waiting') running.note = 'restarting ComfyUI to free memory';
      return;
    }
    if (state._holdAt) { for (const j of jobs) if (j.status === 'running') j._t0 += now() - state._holdAt; state._holdAt = 0; }
    if (running) {
      const el = now() - running._t0;
      running.elapsed = el;
      if (running.prompt && running.prompt.includes('fail') && el > runSeconds / 2) {
        running.status = 'failed'; running.note = 'Mock failure on purpose.'; return;
      }
      const f = el / runSeconds;
      if (f >= 1) { running.status = 'done'; running.note = 'finished'; running.result = newestMp4(); return; }
      running.note = f < 0.5 ? 'restarting ComfyUI to free memory' : f < 0.6 ? 'loading models' : `sampling step ${Math.min(6, 1 + Math.floor((f - 0.6) / 0.4 * 6))} of 6`;
      return;
    }
    const next = jobs.filter(j => j.status === 'queued').sort((a, b) => a.added - b.added)[0];
    if (next) { next.status = 'running'; next._t0 = now(); next.note = 'starting'; }
  }
  const timer = setInterval(tick, 500);

  function send(res, code, body, type) {
    const buf = Buffer.isBuffer(body) ? body : Buffer.from(typeof body === 'string' ? body : JSON.stringify(body));
    res.writeHead(code, {
      'Content-Type': type || 'application/json; charset=utf-8',
      'Access-Control-Allow-Origin': 'null',
      'Access-Control-Allow-Headers': 'X-Lip-Token, Content-Type',
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Content-Length': buf.length,
    });
    res.end(buf);
  }
  const err = (res, code, msg) => send(res, code, { error: msg });

  function durationFor(p) { return /long/i.test(p) ? 30.0 : 6.0; }

  function peaks() {
    const out = [];
    for (let i = 0; i < 500; i++) {
      const t = i / 500;
      const pause = (t > 0.30 && t < 0.37) || (t > 0.68 && t < 0.74);
      let v = pause ? 0.02 : 0.25 + 0.6 * Math.abs(Math.sin(i * 0.37)) * (0.6 + 0.4 * Math.sin(i * 0.05));
      out.push(Math.round(Math.max(0, Math.min(1, v)) * 1000) / 1000);
    }
    return out;
  }

  function wav(seconds) {
    const rate = 22050, n = Math.max(1, Math.floor(Math.min(seconds, 30) * rate));
    const buf = Buffer.alloc(44 + n * 2);
    buf.write('RIFF', 0); buf.writeUInt32LE(36 + n * 2, 4); buf.write('WAVEfmt ', 8);
    buf.writeUInt32LE(16, 16); buf.writeUInt16LE(1, 20); buf.writeUInt16LE(1, 22);
    buf.writeUInt32LE(rate, 24); buf.writeUInt32LE(rate * 2, 28); buf.writeUInt16LE(2, 32); buf.writeUInt16LE(16, 34);
    buf.write('data', 36); buf.writeUInt32LE(n * 2, 40);
    for (let i = 0; i < n; i++) {
      const t = i / rate;
      const s = 0.12 * Math.sin(2 * Math.PI * 330 * t) * (0.6 + 0.4 * Math.sin(2 * Math.PI * 3 * t));
      buf.writeInt16LE(Math.round(s * 32767), 44 + i * 2);
    }
    return buf;
  }

  const server = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://127.0.0.1:' + PORT);
    if (req.method === 'OPTIONS') { send(res, 204, ''); return; }
    if (req.headers['x-lip-token'] !== token || !token) { err(res, 401, 'bad token'); return; }
    let raw = '';
    req.on('data', c => { raw += c; if (raw.length > 1e6) req.destroy(); });
    req.on('end', () => {
      let body = {};
      if (raw) { try { body = JSON.parse(raw); } catch (e) { err(res, 400, 'bad json'); return; } }
      log.push({ method: req.method, path: url.pathname, query: Object.fromEntries(url.searchParams), body });
      const p = url.pathname;

      if (req.method === 'GET' && p === '/status') {
        send(res, 200, { comfyui: true, proxy: true, restarting: state.restarting, busy: jobs.some(j => j.status === 'running'),
          ram_free_gb: state.ramOk ? 30.2 : 9.14, ram_needed_gb: 22, ram_ok: state.ramOk });
      } else if (req.method === 'GET' && p === '/options') {
        send(res, 200, {
          models: [
            { id: 'WanVideo\\wan2.1-i2v-14b-480p-Q4_K_M.gguf', label: 'Wan 2.1 I2V 14B 480p Q4_K_M', default: true },
            { id: 'WanVideo\\my-other-model.gguf', label: 'My other model' },
          ],
          aspects: [
            { id: '16:9', label: '16:9', width: 832, height: 480, enabled: true, default: true },
            { id: '9:16', label: '9:16', width: 480, height: 832, enabled: false, note: 'Not tested yet' },
            { id: '1:1', label: '1:1', width: 640, height: 640, enabled: false, note: 'Not tested yet' },
            { id: '4:3', label: '4:3', width: 640, height: 480, enabled: false, note: 'Not tested yet' },
          ],
          quality: { default: 0.5, enabled: true, positions: [
            { id: 'fast', value: 0.0, label: 'Fast draft', enabled: true },
            { id: 'default', value: 0.5, label: 'Default', enabled: true },
            state.bestEnabled ? { id: 'best', value: 1.0, label: 'Best', enabled: true }
              : { id: 'best', value: 1.0, label: 'Best', enabled: false, note: 'The Q6_K model file is missing' },
          ] },
          limits: { warn_seconds: warnSeconds },
          max_singers: 4,
        });
      } else if (req.method === 'POST' && p === '/audio/info') {
        if (typeof body.path !== 'string' || !body.path) { err(res, 400, 'path is required'); return; }
        send(res, 200, { duration: durationFor(body.path), peaks: peaks() });
      } else if (req.method === 'GET' && p === '/audio/segment') {
        const start = Number(url.searchParams.get('start') || 0), end = Number(url.searchParams.get('end') || 0);
        if (!url.searchParams.get('path')) { err(res, 400, 'path is required'); return; }
        send(res, 200, wav((end > start ? end : durationFor(url.searchParams.get('path'))) - start), 'audio/wav');
      } else if (req.method === 'POST' && p === '/jobs') {
        if (typeof body.shot !== 'string' || !body.shot || typeof body.audio !== 'string' || !body.audio) { err(res, 400, 'shot and audio are required'); return; }
        const singers = body.singers === undefined ? [] : body.singers;
        if (!Array.isArray(singers) || singers.length > 4) { err(res, 400, 'singers must be a list of up to 4'); return; }
        for (const g of singers) {
          if (!g || [g.x, g.y, g.r].some(v => typeof v !== 'number' || !(v > 0 && v <= 1))) { err(res, 400, 'each singer needs x, y and r between 0 and 1'); return; }
        }
        if (singers.length && body.unison === false && (!Array.isArray(body.singer_audios) || body.singer_audios.length !== singers.length
            || body.singer_audios.some(a => typeof a !== 'string' || !a))) { err(res, 400, 'singer_audios needs one path per singer'); return; }
        if (body.sing_along !== undefined && typeof body.sing_along !== 'boolean') { err(res, 400, 'sing_along must be true or false'); return; }
        const dur = durationFor(body.audio);
        const seconds = Math.round(((body.end > 0 ? body.end : dur) - (body.start || 0)) * 10) / 10;
        const id = '20261029-' + String(100000 + (++counter)) + '-' + Math.random().toString(16).slice(2, 6);
        jobs.push({ id, status: 'queued', added: now(), shot: body.shot, audio: body.audio, seconds, note: 'waiting',
          result: null, elapsed: 0, _t0: 0, prompt: body.prompt || '' });
        send(res, 200, { id });
      } else if (req.method === 'GET' && p === '/jobs') {
        const list = jobs.slice().sort((a, b) => b.added - a.added).map(j => {
          const { _t0, prompt, ...rest } = j; return rest;
        });
        send(res, 200, { jobs: list });
      } else if (req.method === 'POST' && p === '/jobs/clear') {
        let n = 0;
        for (let i = jobs.length - 1; i >= 0; i--) if (['done', 'failed', 'cancelled'].includes(jobs[i].status)) { jobs.splice(i, 1); n++; }
        send(res, 200, { removed: n });
      } else if (req.method === 'POST' && /^\/jobs\/[^/]+\/remove$/.test(p)) {
        const i = jobs.findIndex(x => x.id === p.split('/')[2]);
        if (i < 0) { err(res, 404, 'no such job'); return; }
        if (jobs[i].status === 'running') { err(res, 409, 'a running job cannot be removed'); return; }
        jobs.splice(i, 1);
        send(res, 200, { ok: true });
      } else if (req.method === 'POST' && /^\/jobs\/[^/]+\/cancel$/.test(p)) {
        const j = jobs.find(x => x.id === p.split('/')[2]);
        if (!j) { err(res, 404, 'no such job'); return; }
        if (j.status !== 'queued') { err(res, 409, 'only queued jobs can be cancelled'); return; }
        j.status = 'cancelled'; j.note = 'cancelled';
        send(res, 200, { ok: true });
      } else if (req.method === 'POST' && p === '/open-folder') {
        if (typeof body.path !== 'string' || !body.path) { err(res, 400, 'path is required'); return; }
        send(res, 200, { ok: true });
      } else if (req.method === 'POST' && p === '/_mock/seed') {
        jobs.push({ id: 'seed-' + (++counter), status: body.status, added: now() + (body.offset || 0), shot: body.shot || 'D:\\pics\\seed.png', audio: 'D:\\audio\\seed.wav',
          seconds: 2.0, note: body.note || '', result: body.status === 'done' ? (body.result || newestMp4()) : null, elapsed: 0, _t0: 0, prompt: '' });
        send(res, 200, { ok: true });
      } else if (req.method === 'GET' && p === '/_mock/log') {
        send(res, 200, log);
      } else if (req.method === 'GET' && p === '/_mock/set') {
        const sp = url.searchParams;
        if (sp.has('restarting')) state.restarting = sp.get('restarting') === '1';
        if (sp.has('hold')) state.hold = sp.get('hold') === '1';
        if (sp.has('best_enabled')) state.bestEnabled = sp.get('best_enabled') === '1';
        if (sp.has('ram_ok')) state.ramOk = sp.get('ram_ok') === '1';
        send(res, 200, { ok: true });
      } else {
        err(res, 404, 'not found');
      }
    });
  });

  return new Promise((resolve, reject) => {
    server.once('error', e => { clearInterval(timer); reject(e); });
    server.listen(PORT, '127.0.0.1', () => resolve({
      port: PORT, token, log, state, close: () => { clearInterval(timer); server.close(); },
    }));
  });
}

module.exports = { start };

if (require.main === module) {
  if (!process.env.LIPSERVICE_TOKEN) { console.error('Set LIPSERVICE_TOKEN first.'); process.exit(1); }
  start().then(s => console.log('mock backend on http://127.0.0.1:' + s.port))
    .catch(e => { console.error(e.code === 'EADDRINUSE' ? 'BLOCKED: port 8780 is busy' : e.message); process.exit(2); });
}
