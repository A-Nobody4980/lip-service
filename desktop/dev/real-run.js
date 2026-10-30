'use strict';
// Real-backend run, started by:  electron.exe . --real
// Does NOT start the mock. Uses LIPSERVICE_TOKEN and the real backend on 127.0.0.1:8780.
// Drives the real page through one single-singer render:
//   drops inputs\shot_01.webp and inputs\RingTheBell.wav, sets start 6.0 and end 9.24, clicks Render shot,
//   waits until that queue row says Done (25 minutes at most), prints the result path and PASS or FAIL.
const fs = require('fs');

const IMAGE = 'D:\\Project_lip_service\\inputs\\shot_01.webp';
const AUDIO = 'D:\\Project_lip_service\\inputs\\RingTheBell.wav';
const START = '0:06.0';
const END = '0:09.24';
const TIMEOUT_MS = 25 * 60 * 1000;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function run({ win, seen, blocked }) {
  const wc = win.webContents;
  let fails = 0;
  const check = (name, ok, detail) => {
    if (ok) console.log('PASS ' + name);
    else { fails++; console.log('FAIL ' + name + (detail ? ': ' + detail : '')); }
  };
  const consoleErrors = [];
  wc.on('console-message', (...a) => {
    const d = a[0] && a[0].message !== undefined ? a[0] : { level: a[1], message: a[2] };
    if (d.level === 'error' || d.level === 3) consoleErrors.push(d.message);
  });

  for (const f of [IMAGE, AUDIO]) if (!fs.existsSync(f)) { console.log('FAIL missing input file ' + f); return 1; }

  const ev = (js) => wc.executeJavaScript(js, true);
  const waitFor = async (js, ms) => {
    const t0 = Date.now();
    while (Date.now() - t0 < ms) { try { if (await ev(js)) return true; } catch (e) { /* retry */ } await sleep(250); }
    return false;
  };
  wc.debugger.attach('1.3');
  const cdp = (m, p) => wc.debugger.sendCommand(m, p);
  const rectOf = (sel) => ev(`(()=>{const e=document.querySelector(${JSON.stringify(sel)});if(!e)return null;e.scrollIntoView({block:"center"});const r=e.getBoundingClientRect();return {x:r.left,y:r.top,w:r.width,h:r.height}})()`);
  const click = async (x, y) => {
    await cdp('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y });
    await cdp('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', buttons: 1, clickCount: 1 });
    await cdp('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', buttons: 0, clickCount: 1 });
  };
  const clickSel = async (sel) => { const r = await rectOf(sel); await click(r.x + r.w / 2, r.y + r.h / 2); };
  const drop = async (sel, file) => {
    const r = await rectOf(sel); const x = r.x + r.w / 2, y = r.y + r.h / 2;
    const data = { items: [], files: [file], dragOperationsMask: 1 };
    for (const type of ['dragEnter', 'dragOver', 'drop']) await cdp('Input.dispatchDragEvent', { type, x, y, data });
  };
  const typeTime = async (id, t) => {
    await ev(`document.getElementById(${JSON.stringify(id)}).focus()`);
    await cdp('Input.dispatchKeyEvent', { type: 'keyDown', key: 'a', modifiers: 2, windowsVirtualKeyCode: 65 });
    await cdp('Input.insertText', { text: t });
    await cdp('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 });
  };

  await new Promise((resolve) => { if (!wc.isLoading()) return resolve(); wc.once('did-finish-load', resolve); });
  check('backend reachable (status light says ComfyUI connected or restarting)',
    await waitFor('/^(ComfyUI connected|Restarting ComfyUI)$/.test(document.getElementById("lightText").textContent)', 20000),
    await ev('document.getElementById("lightText").textContent'));
  check('options loaded (model picker has a model)', await waitFor('!/^(Loading models|No models found)/.test(document.getElementById("modelLabel").textContent)', 20000));

  await drop('#imageZone', IMAGE);
  check('image shown', await waitFor('(()=>{const i=document.getElementById("imageImg");return !i.hidden&&i.complete&&i.naturalWidth>0})()', 10000), await ev('document.getElementById("imageErr").textContent'));
  await drop('#audioZone', AUDIO);
  check('audio read by the backend', await waitFor('document.getElementById("audioDur").textContent!==""&&document.getElementById("tEnd").value!=="0:00.0"', 30000), await ev('document.getElementById("audioErr").textContent'));
  await typeTime('tStart', START);
  await typeTime('tEnd', END);
  const times = await ev('document.getElementById("tStart").value+" to "+document.getElementById("tEnd").value');
  check('start and end set (' + START + ' to ' + END + ')', times === START + ' to ' + END, times);

  const before = await ev('[...document.querySelectorAll("#queue .qr")].map(r=>r.dataset.id)');
  await clickSel('#btnRender');
  const fe = await ev('document.getElementById("formError").hidden?"":document.getElementById("formError").textContent');
  check('Render accepted without an inline error', fe === '', fe);
  if (fe) { console.log('FAIL real render did not start'); return 1; }
  const idOfNew = `(()=>{const b=${JSON.stringify(before)};const r=[...document.querySelectorAll("#queue .qr")].find(x=>!b.includes(x.dataset.id));return r?r.dataset.id:""})()`;
  check('new job row appeared in the queue', await waitFor(idOfNew + '!==""', 30000));
  const id = await ev(idOfNew);
  const rowState = `(()=>{const r=document.querySelector('#queue .qr[data-id="${id}"]');return r?r.className.replace("qr ","").split(" ")[0]:""})()`;

  const t0 = Date.now();
  let last = '', lastLog = 0, state = '';
  while (Date.now() - t0 < TIMEOUT_MS) {
    state = await ev(rowState);
    if (['done', 'failed', 'cancelled'].includes(state)) break;
    if (Date.now() - lastLog > 60000) {
      lastLog = Date.now();
      const txt = await ev(`(()=>{const r=document.querySelector('#queue .qr[data-id="${id}"]');return r?r.querySelector(".qst").textContent+" | "+r.querySelector(".qnote").textContent:""})()`);
      if (txt !== last) { console.log('INFO ' + Math.round((Date.now() - t0) / 1000) + ' s: ' + txt); last = txt; }
    }
    await sleep(2000);
  }
  const note = await ev(`(()=>{const r=document.querySelector('#queue .qr[data-id="${id}"]');return r?r.querySelector(".qnote").textContent:""})()`);
  check('queue row says Done within 25 minutes', state === 'done', 'state "' + state + '" ' + note);
  if (state === 'done') {
    await sleep(600);
    const result = await ev('document.getElementById("resultPath").textContent');
    console.log('RESULT ' + result);
    check('result path shown and on disk', !!result && fs.existsSync(result), result);
    const vs = await ev('new Promise(r=>{const v=document.getElementById("resultVideo");if(v.readyState>=1)return r("ok:"+v.videoWidth+"x"+v.videoHeight+" "+v.duration.toFixed(2)+" s");v.addEventListener("loadedmetadata",()=>r("ok:"+v.videoWidth+"x"+v.videoHeight+" "+v.duration.toFixed(2)+" s"));v.addEventListener("error",()=>r("error"));setTimeout(()=>r("timeout"),8000)})');
    check('result video loads in the player', vs.startsWith('ok'), vs);
    console.log('INFO result video: ' + vs);
  }
  const stray = seen.filter((u) => /^https?:/i.test(u) && !u.startsWith('http://127.0.0.1:8780/'));
  check('page only reached 127.0.0.1:8780', stray.length === 0, stray.join(' '));
  check('no request was blocked', blocked.length === 0, blocked.join(' '));
  check('no console errors', consoleErrors.length === 0, consoleErrors.join(' | '));
  console.log(fails === 0 ? 'REAL PASS' : 'REAL FAIL (' + fails + ')');
  return fails === 0 ? 0 : 1;
}

module.exports = { run };
