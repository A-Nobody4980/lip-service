'use strict';
// Smoke test, started by:  electron.exe . --smoke [--shot=D:\path\base]
// Loads the real page against the mock backend in a hidden window, drives it with real input events
// (Chrome DevTools protocol drag, mouse and keyboard), prints PASS or FAIL lines, and returns an exit code.
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');
const { app, clipboard, Menu } = require('electron');
const menus = require('../menus.js');

function crc32(buf) {
  let c, crc = 0xffffffff;
  for (let n = 0; n < buf.length; n++) {
    c = (crc ^ buf[n]) & 0xff;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    crc = (crc >>> 8) ^ c;
  }
  return (crc ^ 0xffffffff) >>> 0;
}
function png(w, h) {
  const chunk = (type, data) => {
    const len = Buffer.alloc(4); len.writeUInt32BE(data.length);
    const td = Buffer.concat([Buffer.from(type), data]);
    const crc = Buffer.alloc(4); crc.writeUInt32BE(crc32(td));
    return Buffer.concat([len, td, crc]);
  };
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4); ihdr[8] = 8; ihdr[9] = 2;
  const raw = Buffer.alloc((w * 3 + 1) * h);
  for (let y = 0; y < h; y++) {
    raw[y * (w * 3 + 1)] = 0;
    for (let x = 0; x < w; x++) { const o = y * (w * 3 + 1) + 1 + x * 3; raw[o] = x * 255 / w; raw[o + 1] = y * 255 / h; raw[o + 2] = 200; }
  }
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr), chunk('IDAT', zlib.deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function run({ win, mock, seen, blocked, shotBase, fsOnly }) {
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
  wc.on('render-process-gone', (e, d) => { fails++; console.log('FAIL renderer gone: ' + d.reason); });

  const dir = path.join(app.getPath('temp'), 'smoke');
  fs.mkdirSync(dir, { recursive: true });
  const imgPath = path.join(dir, 'smoke shot.png');
  const audPath = path.join(dir, 'smoke-song.wav');
  const aud2Path = path.join(dir, 'singer2.wav');
  const aud3Path = path.join(dir, 'singer3.wav');
  const img2Path = path.join(dir, 'smoke shot 2.png');
  fs.writeFileSync(imgPath, png(96, 64));
  fs.writeFileSync(img2Path, png(64, 64));
  fs.writeFileSync(audPath, Buffer.from('RIFF$\0\0\0WAVEfmt \x10\0\0\0\x01\0\x01\0\x44\xac\0\0\x88\x58\x01\0\x02\0\x10\0data\0\0\0\0', 'latin1'));
  fs.writeFileSync(aud2Path, Buffer.from('RIFF$\0\0\0WAVEfmt \x10\0\0\0\x01\0\x01\0\x44\xac\0\0\x88\x58\x01\0\x02\0\x10\0data\0\0\0\0', 'latin1'));
  fs.writeFileSync(aud3Path, Buffer.from('RIFF$\0\0\0WAVEfmt \x10\0\0\0\x01\0\x01\0\x44\xac\0\0\x88\x58\x01\0\x02\0\x10\0data\0\0\0\0', 'latin1'));

  const ev = (js) => wc.executeJavaScript(js, true);
  const waitFor = async (js, ms = 4000) => {
    const t0 = Date.now();
    while (Date.now() - t0 < ms) { try { if (await ev(js)) return true; } catch (e) { /* retry */ } await sleep(80); }
    return false;
  };
  const rectOf = (sel, scroll = true) => ev(`(()=>{const e=document.querySelector(${JSON.stringify(sel)});if(!e)return null;${scroll ? 'e.scrollIntoView({block:"center"});' : ''}const r=e.getBoundingClientRect();return {x:r.left,y:r.top,w:r.width,h:r.height}})()`);
  wc.debugger.attach('1.3');
  const cdp = (m, p) => wc.debugger.sendCommand(m, p);
  const mouse = async (type, x, y) => cdp('Input.dispatchMouseEvent', { type, x, y, button: 'left', buttons: type === 'mouseReleased' ? 0 : 1, clickCount: 1 });
  const click = async (x, y) => { await cdp('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y }); await mouse('mousePressed', x, y); await mouse('mouseReleased', x, y); };
  const clickSel = async (sel) => { const r = await rectOf(sel); await click(r.x + r.w / 2, r.y + r.h / 2); };
  const drop = async (sel, file) => {
    const r = await rectOf(sel); const x = r.x + r.w / 2, y = r.y + r.h / 2;
    const data = { items: [], files: [file], dragOperationsMask: 1 };
    for (const type of ['dragEnter', 'dragOver', 'drop']) await cdp('Input.dispatchDragEvent', { type, x, y, data });
  };
  const dropAt = async (x, y, file) => {
    const data = { items: [], files: [file], dragOperationsMask: 1 };
    for (const type of ['dragEnter', 'dragOver', 'drop']) await cdp('Input.dispatchDragEvent', { type, x, y, data });
  };
  const dragOnly = async (x, y, file) => {
    const data = { items: [], files: [file], dragOperationsMask: 1 };
    for (const type of ['dragEnter', 'dragOver']) await cdp('Input.dispatchDragEvent', { type, x, y, data });
  };
  const at = (r, fx, fy) => [r.x + r.w * fx, r.y + r.h * fy];
  const setFile = async (sel, file) => {
    await cdp('DOM.enable');
    const { root } = await cdp('DOM.getDocument', { depth: 0 });
    const { nodeId } = await cdp('DOM.querySelector', { nodeId: root.nodeId, selector: sel });
    await cdp('DOM.setFileInputFiles', { files: [file], nodeId });
  };
  // Spy on the native file picker so the test never opens a real Windows dialog.
  await ev('window.__picks=[];(()=>{const o=HTMLInputElement.prototype.click;HTMLInputElement.prototype.click=function(){if(this.type==="file"){window.__picks.push(this.id||this.dataset.pick);return}return o.call(this)}})()');
  const picks = () => ev('window.__picks.slice()');
  const clearPicks = () => ev('window.__picks.length=0');
  const key = async (keyCode, mods = []) => {
    wc.sendInputEvent({ type: 'keyDown', keyCode, modifiers: mods });
    wc.sendInputEvent({ type: 'keyUp', keyCode, modifiers: mods });
    await sleep(150);
  };
  const ctrl = (k) => key(k, ['control']);
  const text = (sel) => ev(`document.querySelector(${JSON.stringify(sel)}).textContent`);
  const val = (sel) => ev(`document.querySelector(${JSON.stringify(sel)}).value`);
  const shown = (sel) => ev(`!document.querySelector(${JSON.stringify(sel)}).hidden`);
  const mockLog = () => mock.log;
  const secs = async (sel) => { const m = /^(\d+):(\d+\.\d)$/.exec(await val(sel)); return m ? Number(m[1]) * 60 + Number(m[2]) : NaN; };
  const near = (a, b) => Math.abs(a - b) <= 0.15;
  const shot = async (suffix) => {
    if (!shotBase) return;
    const img = await wc.capturePage();
    fs.writeFileSync(shotBase + suffix + '.png', img.toPNG());
  };

  // ---- phase 6: fullscreen on the Result video ----
  async function fullscreenChecks() {

    // Shown for a couple of seconds only (a hidden window cannot enter fullscreen), then hidden again.
    await ev('document.querySelector(".body").scrollTop=0');
    const fsEl = () => ev('document.fullscreenElement?document.fullscreenElement.id:""');
    const waitFs = async (want, ms = 3000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if ((await fsEl()) === (want ? 'resultVideo' : '') && win.isFullScreen() === want) return true; await sleep(100); } return false; };
    const fsTest = async (label) => {
      // 1. the video's own fullscreen button (real mouse), else requestFullscreen with a user gesture
      const vr = await rectOf('#resultVideo');
      await cdp('Input.dispatchMouseEvent', { type: 'mouseMoved', x: vr.x + vr.w / 2, y: vr.y + vr.h / 2 });
      await sleep(400);
      await click(vr.x + vr.w - 56, vr.y + vr.h - 48);
      let how = 'its own button', fsErr = '';
      if (!(await waitFs(true, 1500))) {
        how = 'requestFullscreen with a user gesture';
        await cdp('Runtime.evaluate', { expression: 'window.__fsRes="pending";document.getElementById("resultVideo").requestFullscreen().then(()=>{window.__fsRes="ok"},e=>{window.__fsRes=String(e)})', userGesture: true, awaitPromise: false });
        await sleep(800);
        fsErr = await ev('window.__fsRes');
      }
      const inFs = await waitFs(true, 3000);
      check(label + ': video enters fullscreen (' + how + '), BrowserWindow is full screen', inFs, 'element=' + (await fsEl()) + ' win=' + win.isFullScreen() + ' requestFullscreen result=' + fsErr);
      if (!inFs) return false;
      // A real key event through the browser's input pipeline (CDP key events skip the browser-side Esc handling).
      wc.sendInputEvent({ type: 'keyDown', keyCode: 'Escape' });
      wc.sendInputEvent({ type: 'keyUp', keyCode: 'Escape' });
      check(label + ': Escape leaves fullscreen (page and window)', await waitFs(false, 3000), 'element=' + (await fsEl()) + ' win=' + win.isFullScreen());
      return true;
    };
    win.show();
    await sleep(500);
    const normalBounds = JSON.stringify(win.getBounds());
    await fsTest('normal window');
    await sleep(300);
    check('window is exactly as before after fullscreen (same bounds, not maximized, frameless)', JSON.stringify(win.getBounds()) === normalBounds && !win.isMaximized(), normalBounds + ' vs ' + JSON.stringify(win.getBounds()));
    win.maximize();
    await sleep(600);
    check('window is maximized before the second fullscreen test', win.isMaximized());
    const maxBounds = JSON.stringify(win.getBounds());
    await fsTest('maximized window');
    await sleep(300);
    check('a maximized window is maximized again, same bounds, after fullscreen', win.isMaximized() && JSON.stringify(win.getBounds()) === maxBounds, maxBounds + ' vs ' + JSON.stringify(win.getBounds()) + ' max=' + win.isMaximized());
    win.unmaximize();
    await sleep(500);
    win.hide();
  }

  // ---- load ----
  await new Promise((resolve) => {
    if (!wc.isLoading()) return resolve();
    wc.once('did-finish-load', resolve);
    wc.once('did-fail-load', (e, code, desc) => { fails++; console.log('FAIL page load: ' + desc); resolve(); });
  });
  await sleep(300);

  if (fsOnly) {
    // Fullscreen only: no mock backend, no page traffic. Point the Result player at a real video and test.
    const mp4 = (() => { try { const d = 'D:\\Project_lip_service\\outputs'; const f = fs.readdirSync(d).filter((x) => x.toLowerCase().endsWith('.mp4')); return f.length ? d + '\\' + f[0] : ''; } catch (e) { return ''; } })();
    check('a video exists in outputs to play', !!mp4);
    await ev(`(()=>{const v=document.getElementById("resultVideo");v.src=${JSON.stringify('file:///' + mp4.replace(/\\/g, '/'))};v.hidden=false;document.getElementById("resultEmpty").hidden=true})()`);
    check('video metadata loads', await waitFor('document.getElementById("resultVideo").readyState>=1', 5000));
    await fullscreenChecks();
    check('no console errors', consoleErrors.filter((m) => !/127\.0\.0\.1:8780|ERR_FAILED|Failed to fetch/.test(m)).length === 0, consoleErrors.join(' | '));
    wc.debugger.detach();
    console.log(fails === 0 ? 'SMOKE-FS PASS' : 'SMOKE-FS FAIL (' + fails + ')');
    return fails === 0 ? 0 : 1;
  }

  // ---- structure ----
  const lipKeys = await ev('Object.keys(window.lip||{}).sort().join(",")');
  check('window.lip exposes api, token, pathFor, windowControl', lipKeys === 'api,pathFor,token,windowControl', lipKeys);
  check('window.lip.token comes from LIPSERVICE_TOKEN', (await ev('window.lip.token')) === process.env.LIPSERVICE_TOKEN);
  const ids = ['wMin', 'wMax', 'wClose', 'light', 'imageZone', 'audioZone', 'wave', 'tStart', 'tEnd', 'btnPlay', 'swIsolate', 'prompt',
    'btnSingle', 'btnMulti', 'quality', 'aspects', 'modelBtn', 'warn', 'btnRender', 'queue', 'resultBox', 'btnFolder'];
  const missing = [];
  for (const id of ids) if (!(await ev(`!!document.getElementById(${JSON.stringify(id)})`))) missing.push(id);
  check('all key elements exist', missing.length === 0, missing.join(','));
  check('exactly one primary pink button', (await ev('document.querySelectorAll(".render").length')) === 1);
  check('hidden phase 2 placeholders exist and are hidden',
    await ev('["rings","multiHint","unisonRow"].every(i=>{const e=document.getElementById(i);return e&&e.hidden})'));
  check('page has no em dash or exclamation mark in visible text', !(await ev('/[\\u2014!]/.test(document.body.innerText)')));

  // ---- header status light ----
  check('status light cyan "ComfyUI connected"', await waitFor('document.getElementById("lightText").textContent==="ComfyUI connected" && document.getElementById("light").className==="light"'));
  await ev('fetch(window.lip.api+"/_mock/set?restarting=1",{headers:{"X-Lip-Token":window.lip.token}})');
  check('status light pink "Restarting ComfyUI"', await waitFor('document.getElementById("lightText").textContent==="Restarting ComfyUI" && document.getElementById("light").className==="light pink"', 5000));
  await ev('fetch(window.lip.api+"/_mock/set?restarting=0",{headers:{"X-Lip-Token":window.lip.token}})');
  check('status light back to cyan', await waitFor('document.getElementById("lightText").textContent==="ComfyUI connected"', 5000));

  // ---- options ----
  check('model picker default selected', await waitFor('document.getElementById("modelLabel").textContent.includes("Wan 2.1 I2V 14B 480p Q4_K_M (default)")'));
  await clickSel('#modelBtn');
  check('model list opens with 2 models', (await ev('document.querySelectorAll("#modelList .mi").length')) === 2);
  await clickSel('#modelList .mi:nth-child(2)');
  check('picking another model changes the label and closes the list',
    (await text('#modelLabel')) === 'My other model' && !(await ev('document.getElementById("modelList").hidden === false')));
  await clickSel('#modelBtn'); await clickSel('#modelList .mi:nth-child(1)');
  check('aspect buttons: 4 shown, 1 selected, 3 dimmed with notes',
    await ev('(()=>{const b=[...document.querySelectorAll("#aspects .btn")];return b.length===4&&b.filter(x=>x.classList.contains("sel")).length===1&&b.filter(x=>x.getAttribute("aria-disabled")==="true"&&x.title==="Not tested yet").length===3})()'));
  await clickSel('#aspects .btn:nth-child(2)');
  check('dimmed aspect cannot be chosen', await ev('document.querySelector("#aspects .btn.sel").textContent==="16:9"'));
  check('quality slider: 3 stops, enabled, Default (middle) selected on load, labels Fast draft, Default, Best',
    await waitFor('(()=>{const q=document.getElementById("quality"),l=[...document.querySelectorAll("#qlabels .ql")];return !q.disabled&&q.min==="0"&&q.max==="2"&&q.step==="1"&&q.value==="1"&&l.map(x=>x.textContent).join("|")==="Fast draft|Default|Best"&&l[1].classList.contains("cur")&&!l[0].classList.contains("cur")&&!l[2].classList.contains("cur")&&q.style.getPropertyValue("--pct")==="50%"})()', 4000));

  // ---- validation, no pop-ups ----
  await clickSel('#btnRender');
  check('Render with nothing shows inline "Add an image first."', (await text('#formError')) === 'Add an image first.');

  // ---- 1. image ----
  check('app menu has the Edit roles (undo, redo, cut, copy, paste, selectAll)',
    JSON.stringify(Menu.getApplicationMenu().items[0].submenu.items.filter((i) => i.role).map((i) => i.role.toLowerCase())) === '["undo","redo","cut","copy","paste","selectall"]',
    JSON.stringify(Menu.getApplicationMenu().items.map((i) => i.label)));
  check('right-click menu: editable field gets Cut, Copy, Paste, Select all; plain selection gets Copy; nothing otherwise',
    menus.contextTemplate({ isEditable: true, editFlags: { canCut: true, canCopy: true, canPaste: true, canSelectAll: true } }).filter((i) => i.role).map((i) => i.role).join() === 'undo,redo,cut,copy,paste,selectAll'
    && menus.contextTemplate({ isEditable: false, selectionText: 'x' }).map((i) => i.role).filter(Boolean).join() === 'copy,selectAll'
    && menus.contextTemplate({ isEditable: false, selectionText: '' }) === null);
  check('the window listens for the right-click (context-menu) event', wc.listenerCount('context-menu') >= 1);
  check('title bar is the only -webkit-app-region: drag area',
    await ev('(()=>{const v=(e)=>getComputedStyle(e).getPropertyValue("-webkit-app-region");return v(document.querySelector(".bar"))==="drag"&&[...document.querySelectorAll("*")].filter(e=>v(e)==="drag"&&!e.closest(".bar")).length===0})()'));
  check('image zone is keyboard reachable with a pointer cursor and an image-only picker',
    await ev('(()=>{const z=document.getElementById("imageZone");return z.tabIndex===0&&getComputedStyle(z).cursor==="pointer"&&document.getElementById("fileImage").accept===".png,.jpg,.jpeg,.webp,.bmp"})()'));
  await clearPicks();
  await clickSel('#imageZone');
  check('clicking the empty Image zone opens the file picker', JSON.stringify(await picks()) === '["fileImage"]', JSON.stringify(await picks()));
  await setFile('#fileImage', imgPath);
  check('choosing a file in the picker loads it like a drop (picture and file name)', await waitFor('(()=>{const i=document.getElementById("imageImg");return !i.hidden&&i.complete&&i.naturalWidth===96&&document.getElementById("imageName").textContent==="smoke shot.png"&&!document.getElementById("imageChange").hidden})()'));
  await clearPicks();
  let zr = await rectOf('#imageZone');
  await click(...at(zr, 0.5, 0.45));
  check('with a picture loaded (Single mode) a click anywhere on the zone still opens the picker', JSON.stringify(await picks()) === '["fileImage"]');
  await clearPicks();
  await clickSel('#imageChange');
  check('the Change file link opens the picker', JSON.stringify(await picks()) === '["fileImage"]');
  await clearPicks();
  await ev('document.getElementById("imageZone").focus()');
  await key('Enter');
  const enterPick = JSON.stringify(await picks());
  await key('Space');
  check('Enter and Space on the focused Image zone open the picker', enterPick === '["fileImage"]' && JSON.stringify(await picks()) === '["fileImage","fileImage"]', enterPick + ' ' + JSON.stringify(await picks()));
  await drop('#imageZone', imgPath);
  check('image drop shows the picture and file name', await waitFor('(()=>{const i=document.getElementById("imageImg");return !i.hidden&&i.complete&&i.naturalWidth===96&&document.getElementById("imageName").textContent==="smoke shot.png"})()'));
  await drop('#imageZone', audPath);
  check('wrong file type on image zone gives inline error and keeps the image',
    (await text('#imageErr')).startsWith('That is not an image file') && (await text('#imageName')) === 'smoke shot.png');
  await drop('#imageZone', imgPath);
  check('valid drop clears the image error', !(await shown('#imageErr')));
  zr = await rectOf('#imageZone');
  const imgPts = [[0.5, 0.5, 'on top of the picture'], [0.5, 0.97, 'on the file name bar'], [0.04, 0.08, 'letterbox corner'], [0.95, 0.9, 'right letterbox'], [0.9, 0.08, 'on the Change file link']];
  let imgOk = true, imgDetail = '';
  for (const [fx, fy, label] of imgPts) {
    const [x, y] = at(zr, fx, fy);
    const inside = await ev(`!!document.elementFromPoint(${x},${y}).closest("#imageZone")`);
    await dropAt(x, y, img2Path);
    const a = await waitFor('document.getElementById("imageName").textContent==="smoke shot 2.png"', 2000);
    await dropAt(x, y, imgPath);
    const b = await waitFor('document.getElementById("imageName").textContent==="smoke shot.png"', 2000);
    if (!(inside && a && b)) { imgOk = false; imgDetail += label + ' '; }
  }
  check('dropping a file replaces the image at every point of the Image box (picture, name bar, letterbox, link)', imgOk, imgDetail);
  {
    const [x, y] = at(zr, 0.5, 0.5);
    await dragOnly(x, y, imgPath);
    const over = await ev('document.getElementById("imageZone").classList.contains("over")');
    await dropAt(x, y, imgPath);
    check('the drop highlight shows while dragging over the picture and clears after the drop', over && !(await ev('document.getElementById("imageZone").classList.contains("over")')));
  }

  await clickSel('#btnRender');
  check('Render without audio shows inline "Add audio first."', (await text('#formError')) === 'Add audio first.');

  // ---- 2. audio ----
  check('audio card is keyboard reachable, pointer cursor while empty, audio-only picker',
    await ev('(()=>{const z=document.getElementById("audioZone");return z.tabIndex===0&&getComputedStyle(z).cursor==="pointer"&&document.getElementById("fileAudio").accept===".wav,.mp3,.flac,.m4a,.ogg,.aac"&&document.getElementById("audioChange").hidden})()'));
  await clearPicks();
  await clickSel('#waveEmpty');
  check('clicking the empty Audio card (even on the "No audio yet" waveform) opens the picker', JSON.stringify(await picks()) === '["fileAudio"]', JSON.stringify(await picks()));
  await setFile('#fileAudio', aud2Path);
  check('choosing a file in the picker loads the audio like a drop', await waitFor('document.getElementById("audioName").textContent==="singer2.wav" && document.getElementById("audioDur").textContent==="0:06.0" && !document.getElementById("audioChange").hidden'));
  await drop('#audioZone', audPath);
  check('audio drop shows name and duration 0:06.0', await waitFor('document.getElementById("audioName").textContent==="smoke-song.wav" && document.getElementById("audioDur").textContent==="0:06.0"'));
  check('start and end boxes read 0:00.0 and 0:06.0', (await val('#tStart')) === '0:00.0' && (await val('#tEnd')) === '0:06.0');
  const inked = await ev('(()=>{const c=document.getElementById("waveCanvas");const d=c.getContext("2d").getImageData(0,0,c.width,c.height).data;let n=0;for(let i=3;i<d.length;i+=4)if(d[i]>0)n++;return n})()');
  check('waveform is drawn from the peaks', inked > 200, 'inked pixels ' + inked);
  check('warning shows for a 6.0 s selection (mock limit 5 s) with the real length',
    (await shown('#warn')) && (await text('#warnText')).startsWith('This selection is 6.0 s.'));
  await shot('-audio');
  {
    // already loaded: only Change file opens the picker; the waveform and the rest of the card do not
    await clearPicks();
    await clickSel('#audioName');
    await clickSel('#audioZone .lab');
    check('with audio loaded, clicking the card or file name does not open the picker', (await picks()).length === 0, JSON.stringify(await picks()));
    const wr0 = await rectOf('#wave');
    await click(wr0.x + wr0.w * 0.3, wr0.y + wr0.h / 2);
    check('with audio loaded, clicking the waveform sets the start and does not open the picker', (await picks()).length === 0 && (await val('#tStart')) !== '0:00.0', await val('#tStart'));
    check('loaded audio card shows the normal cursor', await ev('getComputedStyle(document.getElementById("audioZone")).cursor==="default"'));
    await clickSel('#audioChange');
    check('the Change file link opens the picker', JSON.stringify(await picks()) === '["fileAudio"]');
    await clearPicks();
    await ev('document.getElementById("audioZone").focus()');
    await key('Enter');
    check('Enter on the focused Audio card opens the picker', JSON.stringify(await picks()) === '["fileAudio"]');
    const ar = await rectOf('#audioZone');
    const audPts = [['#wave', 0.5, 0.5, 'waveform'], ['#audioName', 0.2, 0.5, 'file name'], ['#waveCanvas', 0.9, 0.2, 'canvas'], ['#tStart', 0.5, 0.5, 'time box'], ['#swIsolate', 0.5, 0.5, 'isolate switch'], ['#audioZone .lab', 0.5, 0.5, 'section label'], ['#btnPlay', 0.5, 0.5, 'Play selection button']];
    let audOk = true, audDetail = '', flip = 0;
    for (const [sel, fx, fy, label] of audPts) {
      const r = await rectOf(sel);
      const [x, y] = at(r, fx, fy);
      const inside = await ev(`!!document.elementFromPoint(${x},${y}).closest("#audioZone")`);
      const file = flip++ % 2 === 0 ? aud2Path : audPath;
      const name = file === aud2Path ? 'singer2.wav' : 'smoke-song.wav';
      await dropAt(x, y, file);
      if (!(inside && await waitFor(`document.getElementById("audioName").textContent===${JSON.stringify(name)}`, 3000))) { audOk = false; audDetail += label + ' '; }
    }
    check('dropping a file onto any part of the loaded Audio card replaces the audio (waveform, name, canvas, time box, switch, label, button)', audOk, audDetail);
    const [hx, hy] = at(ar, 0.5, 0.5);
    await dragOnly(hx, hy, audPath);
    const over = await ev('document.getElementById("audioZone").classList.contains("over")');
    await dropAt(hx, hy, audPath);
    check('the drop highlight shows on the Audio card and clears after the drop', over && !(await ev('document.getElementById("audioZone").classList.contains("over")')));
    check('a non-audio file dropped on loaded audio is refused and the audio stays', await (async () => { await dropAt(hx, hy, imgPath); await sleep(200); return (await text('#audioErr')).startsWith('That is not an audio file') && (await text('#audioName')) === 'smoke-song.wav'; })());
    await dropAt(hx, hy, audPath);
    await waitFor('document.getElementById("audioName").textContent==="smoke-song.wav" && document.getElementById("audioErr").hidden && document.getElementById("tStart").value==="0:00.0" && document.getElementById("tEnd").value==="0:06.0"', 3000);
  }

  // click start then end
  const wr = await rectOf('#wave');
  await click(wr.x + wr.w * 0.5, wr.y + wr.h / 2);
  check('first waveform click sets the start (0:03.0)', (await val('#tStart')) === '0:03.0' && (await val('#tEnd')) === '0:06.0');
  await click(wr.x + wr.w * 0.9, wr.y + wr.h / 2);
  check('second waveform click sets the end (about 0:05.4)', near(await secs('#tEnd'), 5.4) && (await val('#tStart')) === '0:03.0', await val('#tEnd'));
  check('selection box matches 3.0 to about 5.4 of 6.0', await ev('(()=>{const s=document.getElementById("selBox").style;return Math.abs(parseFloat(s.left)-50)<0.1&&Math.abs(parseFloat(s.width)-40)<2})()'));
  check('warning hidden for a 2.4 s selection', !(await shown('#warn')));
  // drag the end handle
  const he = await rectOf('#hEnd', false);
  await cdp('Input.dispatchMouseEvent', { type: 'mouseMoved', x: he.x + he.w / 2, y: he.y + he.h / 2 });
  await mouse('mousePressed', he.x + he.w / 2, he.y + he.h / 2);
  await cdp('Input.dispatchMouseEvent', { type: 'mouseMoved', x: wr.x + wr.w * 0.75, y: he.y + he.h / 2, button: 'left', buttons: 1 });
  await mouse('mouseReleased', wr.x + wr.w * 0.75, he.y + he.h / 2);
  check('dragging the end handle updates the End box (about 0:04.5)', await waitFor('Math.abs(parseFloat(document.getElementById("tEnd").value.split(":")[1])-4.5)<0.2', 1000), await val('#tEnd'));
  // drag the start handle
  const hs = await rectOf('#hStart', false);
  await mouse('mousePressed', hs.x + hs.w / 2, hs.y + hs.h / 2);
  await cdp('Input.dispatchMouseEvent', { type: 'mouseMoved', x: wr.x + wr.w * 0.25, y: hs.y + hs.h / 2, button: 'left', buttons: 1 });
  await mouse('mouseReleased', wr.x + wr.w * 0.25, hs.y + hs.h / 2);
  check('dragging the start handle updates the Start box (about 0:01.5)', await waitFor('Math.abs(parseFloat(document.getElementById("tStart").value.split(":")[1])-1.5)<0.2', 1000), await val('#tStart'));
  // typed times move the handles
  await ev('document.getElementById("tStart").focus()');
  await cdp('Input.dispatchKeyEvent', { type: 'keyDown', key: 'a', modifiers: 2, windowsVirtualKeyCode: 65 });
  await cdp('Input.insertText', { text: '0:01.0' });
  await cdp('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 });
  check('typing Start 0:01.0 moves the handle to 16.7 percent', await waitFor('Math.abs(parseFloat(document.getElementById("selBox").style.left)-16.667)<0.1', 1000), await ev('document.getElementById("selBox").style.left'));
  await ev('document.getElementById("tEnd").focus()');
  await cdp('Input.dispatchKeyEvent', { type: 'keyDown', key: 'a', modifiers: 2, windowsVirtualKeyCode: 65 });
  await cdp('Input.insertText', { text: '0:00.5' });
  await cdp('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 });
  check('End before Start shows inline error', await waitFor('document.getElementById("timeErr").textContent==="End must be after start."', 1000));
  await clickSel('#btnRender');
  check('Render with End before Start is refused inline', (await text('#formError')) === 'End must be after start.');
  await ev('document.getElementById("tEnd").focus()');
  await cdp('Input.dispatchKeyEvent', { type: 'keyDown', key: 'a', modifiers: 2, windowsVirtualKeyCode: 65 });
  await cdp('Input.insertText', { text: '0:02.5' });
  await cdp('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 });
  check('typing End 0:02.5 fixes it and moves the handle', await waitFor('document.getElementById("tEnd").value==="0:02.5" && !document.getElementById("timeErr").textContent', 1000));

  // ---- copy and paste with real key events ----
  {
    const clip = () => clipboard.readText();
    clipboard.writeText('pasted prompt text');
    await clickSel('#prompt');
    await ctrl('V');
    check('Ctrl+V pastes into the prompt box', (await val('#prompt')) === 'pasted prompt text', await val('#prompt'));
    clipboard.writeText('something else');
    await ctrl('A');
    check('Ctrl+A selects all text in the prompt box', await ev('(()=>{const t=document.getElementById("prompt");return t.selectionStart===0&&t.selectionEnd===t.value.length&&t.value.length>0})()'));
    await ctrl('C');
    check('Ctrl+C copies the selection to the clipboard', (await clip()) === 'pasted prompt text', JSON.stringify(await clip()));
    clipboard.writeText('zzz');
    await ctrl('X');
    check('Ctrl+X cuts (box empty, text on the clipboard)', (await val('#prompt')) === '' && (await clip()) === 'pasted prompt text', (await val('#prompt')) + ' | ' + (await clip()));
    await ctrl('Z');
    check('Ctrl+Z undoes the cut', (await val('#prompt')) === 'pasted prompt text', await val('#prompt'));
    await ctrl('A'); await ctrl('X');
    check('prompt box emptied again for the next test', (await val('#prompt')) === '');
    // a time box
    clipboard.writeText('0:01.5');
    await clickSel('#tStart');
    await ctrl('A'); await ctrl('V');
    await key('Enter');
    check('Ctrl+V pastes into a time box and Enter applies it (Start 0:01.5)', (await val('#tStart')) === '0:01.5', await val('#tStart'));
    await clickSel('#tStart');
    await ctrl('A');
    clipboard.writeText('none');
    await ctrl('C');
    check('Ctrl+C copies from a time box', (await clip()) === '0:01.5', JSON.stringify(await clip()));
    clipboard.writeText('0:01.0');
    await ctrl('A'); await ctrl('V');
    await key('Enter');
    check('Start put back to 0:01.0 by pasting', (await val('#tStart')) === '0:01.0', await val('#tStart'));
  }

  // play selection
  const before = mockLog().length;
  await clickSel('#btnPlay');
  const seg = await waitFor('true', 10) && await (async () => { for (let i = 0; i < 40; i++) { if (mockLog().slice(before).some((l) => l.path === '/audio/segment')) return true; await sleep(50); } return false; })();
  const segReq = mockLog().slice(before).find((l) => l.path === '/audio/segment');
  check('Play selection fetches /audio/segment for 1.0 to 2.5', seg && segReq.query.start === '1' && segReq.query.end === '2.5', JSON.stringify(segReq && segReq.query));
  check('button says Stop while playing', (await text('#btnPlay')).includes('Stop'));
  await clickSel('#btnPlay');
  check('pressing it again stops and restores the label', (await text('#btnPlay')).includes('Play selection'));

  // isolate switch
  check('isolate switch is off by default', await ev('document.getElementById("swIsolate").getAttribute("aria-checked")==="false"'));

  // ---- 3, 4. prompt and singers ----
  await clickSel('#prompt');
  await cdp('Input.insertText', { text: 'a woman sings with raw emotion' });
  check('prompt box takes text', (await val('#prompt')) === 'a woman sings with raw emotion');

  // ---- render ----
  await clickSel('#swIsolate');
  check('isolate switch turns on', await ev('document.getElementById("swIsolate").getAttribute("aria-checked")==="true"'));
  await clickSel('#swIsolate');
  mock.state.hold = true; // the fake running job stays running until released, so the queue checks do not race
  const b2 = mockLog().length;
  await clickSel('#btnRender');
  await waitFor('document.querySelectorAll("#queue .qr").length>=3', 4000);
  const post = mockLog().slice(b2).find((l) => l.method === 'POST' && l.path === '/jobs');
  const body = post && post.body;
  check('Render sends POST /jobs as in the contract', !!body && body.shot === imgPath && body.audio === audPath && body.start === 1 && body.end === 2.5
    && body.prompt === 'a woman sings with raw emotion' && body.negative_prompt === '' && body.isolate_vocals === false
    && Array.isArray(body.singers) && body.singers.length === 0 && body.unison === true && body.sing_along === false && Array.isArray(body.singer_audios) && body.singer_audios.length === 0
    && body.quality === 0.5 && body.aspect === '16:9' && body.model === 'WanVideo\\wan2.1-i2v-14b-480p-Q4_K_M.gguf', JSON.stringify(body));
  check('form error cleared after a good render', !(await shown('#formError')));
  check('queue shows the new job named "smoke shot, 1.5 s"', await waitFor('[...document.querySelectorAll("#queue .qname")].some(e=>e.textContent==="smoke shot, 1.5 s")'));
  check('"restarting ComfyUI" note gives the row the cyan glowing dot', await waitFor('(()=>{const r=document.querySelector("#queue .qr.restarting");if(!r)return false;const c=getComputedStyle(r.querySelector(".dot"));return c.backgroundColor==="rgb(25, 230, 255)"&&c.boxShadow!=="none"})()', 5000));
  check('queue also shows the seeded done and failed jobs', await ev('document.querySelectorAll("#queue .qr.done").length>=1&&document.querySelectorAll("#queue .qr.failed").length>=1'));
  await clickSel('#btnRender');
  check('second job waits as Queued with a cancel x', await waitFor('document.querySelectorAll("#queue .qr.queued .qx").length===1', 4000));
  await shot('-queue');
  await clickSel('#queue .qr.queued .qx');
  check('x on a queued row removes it (queued count back to 0, no cancelled row left)', await waitFor('document.querySelectorAll("#queue .qr.queued").length===0&&document.querySelectorAll("#queue .qr.cancelled").length===0', 4000));
  check('that x called /jobs/{id}/remove, not /cancel', mockLog().some((l) => /^\/jobs\/[^/]+\/remove$/.test(l.path)) && !mockLog().some((l) => /\/cancel$/.test(l.path)));
  check('running row shows cyan status with elapsed time and the note', await waitFor('(()=>{const r=document.querySelector("#queue .qr.running");return !!r&&/^Running \\d+:\\d\\d$/.test(r.querySelector(".qst").textContent)&&r.querySelector(".qnote").textContent.length>0})()', 4000));
  mock.state.hold = false;
  check('first job finishes (Done)', await waitFor('[...document.querySelectorAll("#queue .qr.done .qname")].some(e=>e.textContent==="smoke shot, 1.5 s")', 12000));
  check('result path shown and video points at a file:/// URL', await waitFor('(()=>{const v=document.getElementById("resultVideo");return !v.hidden&&v.src.startsWith("file:///")&&document.getElementById("resultPath").textContent.endsWith(".mp4")})()', 4000));
  const vstate = await ev('new Promise(r=>{const v=document.getElementById("resultVideo");if(v.readyState>=1)return r("ok:"+v.videoWidth);v.addEventListener("loadedmetadata",()=>r("ok:"+v.videoWidth));v.addEventListener("error",()=>r("error"));setTimeout(()=>r("timeout"),4000)})');
  console.log('INFO result video element: ' + vstate + ' (needs a real mp4 in outputs to say ok)');
  const b3 = mockLog().length;
  await clickSel('#btnFolder');
  await sleep(300);
  const of = mockLog().slice(b3).find((l) => l.path === '/open-folder');
  check('Open folder posts the folder of the result', !!of && of.body.path === 'D:\\Project_lip_service\\outputs', JSON.stringify(of && of.body));
  // ---- phase 2: multiple singers ----
  await ev('document.querySelector(".body").scrollTop=0');
  check('single mode: hint, unison buttons and rings are hidden', !(await shown('#multiHint')) && !(await shown('#unisonRow')) && !(await shown('#rings')));
  check('sing-along switch is hidden in Single mode', await ev('document.getElementById("swSingAlong").offsetParent===null'));
  await clickSel('#btnMulti');
  check('Multiple shows the hint (Up to 4), the unison buttons and the rings layer',
    (await shown('#multiHint')) && (await text('#multiHint')).includes('Up to 4.') && (await shown('#unisonRow')) && (await shown('#rings')));
  check('Multiple button is selected, Single is not', await ev('document.getElementById("btnMulti").classList.contains("sel")&&!document.getElementById("btnSingle").classList.contains("sel")'));
  check('"Same vocal for all" is the default', await ev('document.getElementById("btnSame").classList.contains("sel")&&!document.getElementById("btnSeparate").classList.contains("sel")'));
  check('sing-along switch shows in Multiple mode, directly under the unison buttons, default off, with its hint',
    await ev('(()=>{const s=document.getElementById("swSingAlong"),b=document.getElementById("btnSame").getBoundingClientRect(),r=s.getBoundingClientRect();return s.offsetParent!==null&&s.getAttribute("aria-checked")==="false"&&s.classList.contains("off")&&r.top>b.bottom&&r.top-b.bottom<30&&s.parentElement.textContent.includes("Unmarked people sing along")&&document.getElementById("singAlongHint").textContent==="Off: only marked singers sing. On: everyone sings with the nearest singer."})()'));
  await clickSel('#btnRender');
  check('Multiple with no rings is refused inline', (await text('#formError')) === "Click each singer's face on the image first.");
  const disp = () => ev('(()=>{const z=document.getElementById("imageZone"),b=z.getBoundingClientRect(),i=document.getElementById("imageImg");const s=Math.min(z.clientWidth/i.naturalWidth,z.clientHeight/i.naturalHeight),w=i.naturalWidth*s,h=i.naturalHeight*s;return {x:b.left+z.clientLeft+(z.clientWidth-w)/2,y:b.top+z.clientTop+(z.clientHeight-h)/2,w,h}})()');
  const ringsInfo = () => ev('[...document.querySelectorAll("#rings .ring")].map(r=>({t:r.textContent,x:+r.dataset.x,y:+r.dataset.y,r:+r.dataset.r,c:r.style.borderColor,rect:(b=>({cx:b.left+b.width/2,cy:b.top+b.height/2,w:b.width}))(r.getBoundingClientRect())}))');
  await rectOf('#imageZone');
  let d = await disp();
  await click(d.x - 12, d.y + d.h / 2);
  check('click in the letterbox (outside the picture) adds no ring', (await ringsInfo()).length === 0);
  const spots = [[0.5, 0.5], [0.25, 0.3], [0.75, 0.3], [0.5, 0.85]];
  for (const [fx, fy] of spots) await click(d.x + d.w * fx, d.y + d.h * fy);
  let rs = await ringsInfo();
  check('4 clicks add 4 numbered rings at the clicked spots (fractions of the picture)',
    rs.length === 4 && rs.every((g, i) => g.t === String(i + 1) && Math.abs(g.x - spots[i][0]) < 0.02 && Math.abs(g.y - spots[i][1]) < 0.02 && g.r === 0.03), JSON.stringify(rs));
  check('ring colours in order pink, cyan, purple, amber', rs.map((g) => g.c).join('|') === 'rgb(255, 43, 214)|rgb(25, 230, 255)|rgb(139, 92, 255)|rgb(255, 176, 0)', rs.map((g) => g.c).join('|'));
  await click(d.x + d.w * 0.1, d.y + d.h * 0.1);
  check('a 5th click is refused (max_singers 4) with an inline note', (await ringsInfo()).length === 4 && (await text('#imageErr')) === 'The most singers in one shot is 4.');
  const wheel = (x, y, dy) => cdp('Input.dispatchMouseEvent', { type: 'mouseWheel', x, y, deltaX: 0, deltaY: dy });
  await wheel(rs[0].rect.cx, rs[0].rect.cy, -100);
  check('wheel up over ring 1 grows it (0.030 to 0.035)', (await ringsInfo())[0].r === 0.035, String((await ringsInfo())[0].r));
  for (let n = 0; n < 40; n++) await wheel(rs[0].rect.cx, rs[0].rect.cy, -100);
  check('radius stops at 0.15', (await ringsInfo())[0].r === 0.15);
  for (let n = 0; n < 60; n++) await wheel(rs[0].rect.cx, rs[0].rect.cy, 100);
  check('radius stops at 0.01', (await ringsInfo())[0].r === 0.01);
  for (let n = 0; n < 4; n++) await wheel(rs[0].rect.cx, rs[0].rect.cy, -100);
  check('radius back to 0.03', (await ringsInfo())[0].r === 0.03);
  rs = await ringsInfo();
  await click(rs[1].rect.cx, rs[1].rect.cy);
  rs = await ringsInfo();
  check('clicking ring 2 removes it and renumbers the rest', rs.length === 3 && rs.map((g) => g.t).join('') === '123' && Math.abs(rs[1].x - 0.75) < 0.02, JSON.stringify(rs.map((g) => [g.t, g.x])));
  check('removing a ring clears the "most singers" note', !(await shown('#imageErr')));
  win.setSize(640, 760);
  await sleep(500);
  await wc.capturePage();
  d = await disp();
  rs = await ringsInfo();
  const okPos = rs.every((g) => Math.abs((g.rect.cx - d.x) / d.w - g.x) < 0.02 && Math.abs((g.rect.cy - d.y) / d.h - g.y) < 0.02 && Math.abs(g.rect.w / 2 / d.w - g.r) < 0.01);
  check('after resizing the window the rings still sit on the same spots of the picture', okPos, JSON.stringify(rs.map((g) => [(g.rect.cx - d.x) / d.w, g.x])));
  win.setSize(960, 900);
  await sleep(500);
  await wc.capturePage();
  await sleep(200);
  check('no extra track zones in unison mode', !(await shown('#extraTracks')) && !(await shown('#s1note')));
  await clickSel('#btnSeparate');
  check('Separate shows one extra zone per additional ring (2 for 3 rings) and the Singer 1 note',
    (await shown('#extraTracks')) && (await ev('[...document.querySelectorAll("#extraTracks .track .tn")].map(e=>e.textContent).join("|")')) === 'Singer 2 track|Singer 3 track' && (await shown('#s1note')), consoleErrors.join(' | ') + ' sep.sel=' + (await ev('document.getElementById("btnSeparate").className')) + ' rings=' + (await ev('document.querySelectorAll("#rings .ring").length')) + ' tracks=' + (await ev('document.getElementById("extraTracks").innerHTML.length')));
  await clickSel('#btnRender');
  check('Separate with a missing track is refused ("Add a track for singer 2.")', (await text('#formError')) === 'Add a track for singer 2.');
  await drop('#extraTracks .track[data-singer="2"]', aud2Path);
  check('dropping a file on the Singer 2 zone shows its name and a clear x', (await text('#extraTracks .track[data-singer="2"] .tf')) === 'singer2.wav' && !!(await rectOf('#extraTracks .track[data-singer="2"] .qx', false)));
  await clickSel('#btnRender');
  check('then it asks for singer 3', (await text('#formError')) === 'Add a track for singer 3.');
  await drop('#extraTracks .track[data-singer="3"]', imgPath);
  check('a non-audio file on a track zone is refused inline', (await text('#extraTracks .track[data-singer="3"] .tf')) === 'That is not an audio file.');
  await clickSel('#extraTracks .track[data-singer="2"] .qx');
  check('the x clears the Singer 2 track', (await text('#extraTracks .track[data-singer="2"] .tf')) === 'Drop an audio file here, or click to choose one');
  await drop('#extraTracks .track[data-singer="2"]', aud2Path);
  await drop('#extraTracks .track[data-singer="3"]', aud3Path);
  check('track zones are keyboard reachable with a pointer cursor and an audio-only picker',
    await ev('[...document.querySelectorAll("#extraTracks .track")].every(z=>z.tabIndex===0&&getComputedStyle(z).cursor==="pointer"&&z.querySelector("input[type=file]").accept===".wav,.mp3,.flac,.m4a,.ogg,.aac")'));
  await clearPicks();
  await clickSel('#extraTracks .track[data-singer="2"] .tf');
  check('clicking a Singer 2 track zone opens its picker', JSON.stringify(await picks()) === '["track-2"]', JSON.stringify(await picks()));
  await setFile('#extraTracks .track[data-singer="2"] input[type=file]', aud3Path);
  check('choosing a file for the Singer 2 track loads it', await waitFor('document.querySelector("#extraTracks .track[data-singer=\\"2\\"] .tf").textContent==="singer3.wav"'));
  await clearPicks();
  await ev('document.querySelector("#extraTracks .track[data-singer=\\"3\\"]").focus()');
  await key('Enter');
  check('Enter on a focused track zone opens its picker', JSON.stringify(await picks()) === '["track-3"]', JSON.stringify(await picks()));
  await clearPicks();
  await clickSel('#extraTracks .track[data-singer="2"] .qx');
  check('the track clear x does not open the picker', (await picks()).length === 0 && (await text('#extraTracks .track[data-singer="2"] .tf')).startsWith('Drop an audio file here'));
  {
    const tr = await rectOf('#extraTracks .track[data-singer="2"]');
    let ok = true;
    for (const [fx, fy] of [[0.05, 0.5], [0.4, 0.5], [0.95, 0.5]]) {
      const [x, y] = at(tr, fx, fy);
      await dropAt(x, y, aud2Path);
      if (!(await waitFor('document.querySelector("#extraTracks .track[data-singer=\\"2\\"] .tf").textContent==="singer2.wav"', 2000))) ok = false;
      await ev('document.querySelector("#extraTracks .track[data-singer=\\"2\\"] .qx").click()');
    }
    await dropAt(...at(tr, 0.5, 0.5), aud2Path);
    check('dropping on the label, the middle or the edge of a track zone loads the file', ok && await waitFor('document.querySelector("#extraTracks .track[data-singer=\\"2\\"] .tf").textContent==="singer2.wav"', 2000));
  }
  const nextJobPost = async (from) => {
    for (let n = 0; n < 60; n++) { const m = mockLog().slice(from).find((l) => l.method === 'POST' && l.path === '/jobs'); if (m) return m; await sleep(50); }
    return null;
  };
  const b4 = mockLog().length;
  await clickSel('#btnRender');
  const mp = await nextJobPost(b4);
  const mb = mp && mp.body;
  check('Separate render body: singers x/y/r, unison false, singer_audios in order, audio is Singer 1',
    !!mb && mb.singers.length === 3 && mb.singers.every((g) => typeof g.x === 'number' && typeof g.y === 'number' && g.r === 0.03) && mb.unison === false
    && JSON.stringify(mb.singer_audios) === JSON.stringify([audPath, aud2Path, aud3Path]) && mb.audio === audPath && mb.start === 1 && mb.end === 2.5 && mb.sing_along === false, JSON.stringify(mb));
  check('no form error after a good multiple render', !(await shown('#formError')));
  await clickSel('#btnSame');
  const b5 = mockLog().length;
  await clickSel('#btnRender');
  const mp2 = await nextJobPost(b5);
  const mb2 = mp2 && mp2.body;
  check('Unison render body: 3 singers, unison true, singer_audios empty', !!mb2 && mb2.singers.length === 3 && mb2.unison === true && mb2.sing_along === false && Array.isArray(mb2.singer_audios) && mb2.singer_audios.length === 0, JSON.stringify(mb2));
  await clickSel('#swSingAlong');
  check('sing-along switch turns on', await ev('document.getElementById("swSingAlong").getAttribute("aria-checked")==="true"&&document.getElementById("swSingAlong").classList.contains("on")'));
  const b7 = mockLog().length;
  await clickSel('#btnRender');
  const mp4 = await nextJobPost(b7);
  check('Render with the switch on sends sing_along true', !!mp4 && mp4.body.sing_along === true && mp4.body.singers.length === 3, JSON.stringify(mp4 && mp4.body.sing_along));
  const bad = await ev('fetch(window.lip.api+"/jobs",{method:"POST",headers:{"X-Lip-Token":window.lip.token,"Content-Type":"application/json"},body:JSON.stringify({shot:"a",audio:"b",unison:false,singers:[{x:.5,y:.5,r:.03},{x:.2,y:.2,r:.03}],singer_audios:["b"]})}).then(r=>r.status)');
  check('mock rejects unison false with the wrong number of tracks (400)', bad === 400, String(bad));
  await clickSel('#btnSeparate');
  rs = await ringsInfo();
  await click(rs[1].rect.cx, rs[1].rect.cy);
  check('removing ring 2 leaves one extra zone, holding the old Singer 3 file as Singer 2',
    (await ev('document.querySelectorAll("#extraTracks .track").length')) === 1 && (await text('#extraTracks .track[data-singer="2"] .tf')) === 'singer3.wav');
  await clickSel('#btnSingle');
  check('back to Single hides hint, unison buttons, rings and track zones', !(await shown('#multiHint')) && !(await shown('#unisonRow')) && !(await shown('#rings')) && !(await shown('#extraTracks')));
  const b6 = mockLog().length;
  await clickSel('#btnRender');
  const mp3 = await nextJobPost(b6);
  check('Single mode again sends singers [], unison true and sing_along false (switch still on)', !!mp3 && mp3.body.singers.length === 0 && mp3.body.unison === true && mp3.body.sing_along === false && mp3.body.singer_audios.length === 0, JSON.stringify(mp3 && mp3.body));
  await ev('document.querySelector(".body").scrollTop=0');
  await ev('window.scrollTo(0,0);document.querySelector(".body").scrollTop=0');
  await shot('-final');

  // ---- phase 7: quality slider (three positions) ----
  {
    await ev('document.querySelector(".body").scrollTop=0');
    const qIdx = () => ev('document.getElementById("quality").value');
    const qCur = () => ev('[...document.querySelectorAll("#qlabels .ql")].findIndex(x=>x.classList.contains("cur"))');
    const thumbX = async (i) => { const r = await rectOf('#quality'); return [r.x + 9 + (r.w - 18) * (i / 2), r.y + r.h / 2, r]; };
    const dragTo = async (from, to) => {
      const [x0, y] = await thumbX(from); const [x1] = await thumbX(to);
      const r = await rectOf('#quality');
      await cdp('Input.dispatchMouseEvent', { type: 'mouseMoved', x: x0, y });
      await mouse('mousePressed', x0, y);
      await cdp('Input.dispatchMouseEvent', { type: 'mouseMoved', x: (x0 + x1) / 2, y, button: 'left', buttons: 1 });
      await cdp('Input.dispatchMouseEvent', { type: 'mouseMoved', x: to === 2 ? r.x + r.w + 20 : to === 0 ? r.x - 20 : x1, y, button: 'left', buttons: 1 });
      await mouse('mouseReleased', x1, y);
      await sleep(150);
    };
    const renderBody = async () => {
      const b = mockLog().length;
      await clickSel('#btnRender');
      for (let n = 0; n < 60; n++) { const m = mockLog().slice(b).find((l) => l.method === 'POST' && l.path === '/jobs'); if (m) return m.body; await sleep(50); }
      return null;
    };
    const pct = () => ev('document.getElementById("quality").style.getPropertyValue("--pct")');
    check('Default is selected and the Single/Multiple state is Single for the quality tests', (await qIdx()) === '1' && (await qCur()) === 1 && await ev('document.getElementById("btnSingle").classList.contains("sel")'));
    await dragTo(1, 0);
    check('dragging the knob left snaps to Fast draft (label pink, fill 0%)', (await qIdx()) === '0' && (await qCur()) === 0 && (await pct()) === '0%', (await qIdx()) + ' ' + (await pct()));
    check('Fast draft sends quality 0', (await renderBody()).quality === 0);
    await dragTo(0, 2);
    check('dragging the knob right snaps to Best (label pink, fill 100%)', (await qIdx()) === '2' && (await qCur()) === 2 && (await pct()) === '100%', (await qIdx()) + ' ' + (await pct()));
    check('Best sends quality 1', (await renderBody()).quality === 1);
    await clickSel('#qlabels .ql[data-pos="fast"]');
    check('clicking the label Fast draft moves the slider', (await qIdx()) === '0' && (await qCur()) === 0);
    await clickSel('#qlabels .ql[data-pos="default"]');
    check('clicking the label Default moves the slider', (await qIdx()) === '1' && (await qCur()) === 1 && (await pct()) === '50%');
    await clickSel('#qlabels .ql[data-pos="best"]');
    check('clicking the label Best moves the slider', (await qIdx()) === '2' && (await qCur()) === 2);
    await ev('document.getElementById("quality").focus()');
    await key('Left');
    check('arrow key Left from Best goes to Default', (await qIdx()) === '1' && (await qCur()) === 1);
    check('Default sends quality 0.5', (await renderBody()).quality === 0.5);
    await ev('document.getElementById("quality").focus()');
    await key('Left');
    check('arrow key Left goes to Fast draft', (await qIdx()) === '0' && (await qCur()) === 0);
    await key('Right'); await key('Right');
    check('arrow key Right twice goes to Best', (await qIdx()) === '2' && (await qCur()) === 2);
    await key('Home');
    check('Home goes to Fast draft', (await qIdx()) === '0');
    await key('End');
    check('End goes to Best', (await qIdx()) === '2');
    await clickSel('#qlabels .ql[data-pos="default"]');

    // memory notice: every position, notice only, never blocks
    const NOTICE = 'Notice: your PC has 9.1 GB of memory free right now and a render peaks near 26 GB. It should still work. Closing other programs first makes it safer.';
    const typeTime = async (sel, t) => { await clickSel(sel); await ctrl('A'); await cdp('Input.insertText', { text: t }); await key('Enter'); };
    check('no notice while memory is fine', !(await shown('#ramNotice')));
    mock.state.ramOk = false;
    for (const [pos, expect] of [['fast', 0], ['default', 0.5], ['best', 1]]) {
      await clickSel('#qlabels .ql[data-pos="' + pos + '"]');
      check('notice shows for ' + pos + ' with the real numbers (9.1 free, near 26 GB)', await waitFor('!document.getElementById("ramNotice").hidden&&document.getElementById("ramNoticeText").textContent===' + JSON.stringify(NOTICE), 6000), await text('#ramNoticeText'));
      const bd = await renderBody();
      check('notice at ' + pos + ' does not block Render: quality ' + expect + ' still sent, no error shown', !!bd && bd.quality === expect && !(await shown('#formError')), JSON.stringify(bd && bd.quality));
      await waitFor('!document.getElementById("btnRender").disabled', 3000);
      check('Render button is not disabled or dimmed at ' + pos, await ev('(()=>{const b=document.getElementById("btnRender");return !b.disabled&&getComputedStyle(b).opacity==="1"})()'));
    }
    check('the notice is cyan and softer than the pink warning, above the Render button',
      await ev('(()=>{const n=document.getElementById("ramNotice"),c=getComputedStyle(n),b=document.getElementById("btnRender");return !n.classList.contains("warn")&&c.borderTopColor==="rgb(25, 230, 255)"&&c.backgroundColor==="rgb(6, 34, 43)"&&n.getBoundingClientRect().bottom<=b.getBoundingClientRect().top})()'));
    // the pink long-selection warning still works and can show together with the notice
    await typeTime('#tStart', '0:00.0'); await typeTime('#tEnd', '0:06.0');
    check('the long-selection warning shows together with the notice and keeps its pink style', await ev('(()=>{const w=document.getElementById("warn"),n=document.getElementById("ramNotice");return !w.hidden&&!n.hidden&&getComputedStyle(w).borderTopColor==="rgb(255, 43, 214)"&&w.getBoundingClientRect().bottom<=n.getBoundingClientRect().top+1})()'));
    await typeTime('#tStart', '0:01.0'); await typeTime('#tEnd', '0:02.5');
    check('long-selection warning hides again for a short selection, notice stays', !(await shown('#warn')) && (await shown('#ramNotice')));
    mock.state.ramOk = true;
    check('the notice hides when memory is ok again (status poll)', await waitFor('document.getElementById("ramNotice").hidden', 6000));
    await clickSel('#qlabels .ql[data-pos="best"]');
    check('no notice for Best when memory is ok', !(await shown('#ramNotice')));
    await clickSel('#qlabels .ql[data-pos="default"]');
  }

  // ---- phase 5: remove one row, Clear queue ----
  {
    await ev('document.querySelector(".body").scrollTop=0');
    const post = (pth, body) => ev(`fetch(window.lip.api+${JSON.stringify(pth)},{method:"POST",headers:{"X-Lip-Token":window.lip.token,"Content-Type":"application/json"},body:${JSON.stringify(JSON.stringify(body || {}))}}).then(async r=>({s:r.status,j:await r.json()}))`);
    const rows = (sel) => ev(`document.querySelectorAll("#queue .qr${sel}").length`);
    // Freeze a running job and make sure waiting jobs exist, so nothing below depends on timing.
    mock.state.hold = true;
    await post('/_mock/seed', { status: 'queued', offset: 0 });
    await post('/_mock/seed', { status: 'queued', offset: 1 });
    check('a running row and a waiting row exist (held)', await waitFor('document.querySelector("#queue .qr.running")&&document.querySelector("#queue .qr.queued")', 8000));
    check('running rows have no x; every other row has one with a tooltip and aria-label',
      await ev('(()=>{const r=[...document.querySelectorAll("#queue .qr")];return r.length>3&&r.every(x=>{const b=x.querySelector(".qx");return x.classList.contains("running")?!b:(!!b&&b.title===(x.classList.contains("queued")?"Cancel and remove":"Remove from the list")&&b.getAttribute("aria-label")===b.title)})})()'));
    check('Clear queue button sits on the label line, has its tooltip and is live (done and failed rows exist)',
      await ev('(()=>{const b=document.getElementById("btnClear"),l=document.querySelector(".lab-row .lab");return b.parentElement===l.parentElement&&b.title==="Removes finished and failed rows. Running and waiting jobs stay."&&b.getAttribute("aria-disabled")==="false"&&b.textContent==="Clear queue"})()'));
    const shownPath = await text('#resultPath');
    // x on a failed row
    const failedBefore = await rows('.failed');
    await clickSel('#queue .qr.failed .qx');
    check('x removes a failed row', await waitFor(`document.querySelectorAll("#queue .qr.failed").length===${failedBefore - 1}`, 3000));
    // x on the row that holds the video shown in the Result player
    const doneBefore = await rows('.done');
    await clickSel('#queue .qr.done .qx');
    check('x removes a done row', await waitFor(`document.querySelectorAll("#queue .qr.done").length===${doneBefore - 1}`, 3000));
    // x on a queued row
    const qBefore = await rows('.queued');
    if (qBefore > 0) {
      const b = mockLog().length;
      await clickSel('#queue .qr.queued .qx');
      check('x removes a queued row (and calls /remove)', await waitFor(`document.querySelectorAll("#queue .qr.queued").length<=${qBefore - 1}`, 3000) && mockLog().slice(b).some((l) => /\/remove$/.test(l.path)));
    } else check('x removes a queued row (and calls /remove)', false, 'no queued row left to test');
    // 409 on a running row
    await waitFor('document.querySelector("#queue .qr.running")', 6000);
    const runId = await ev('(document.querySelector("#queue .qr.running")||{dataset:{}}).dataset.id||""');
    const r409 = runId ? await post('/jobs/' + runId + '/remove') : { s: 0 };
    check('mock refuses to remove a running job (409)', r409.s === 409, JSON.stringify(r409));
    // the player was not blanked by any of that
    check('Result player still shows its video after rows were removed', await ev('(()=>{const v=document.getElementById("resultVideo");return !v.hidden&&v.src.startsWith("file:///")})()') && (await text('#resultPath')) === shownPath, await text('#resultPath'));
    // Clear queue
    for (const st of ['done', 'failed', 'cancelled']) await post('/_mock/seed', { status: st, offset: -5000 });
    check('seeded done, failed and cancelled rows appear', await waitFor('["done","failed","cancelled"].every(s=>document.querySelector("#queue .qr."+s))', 4000));
    check('Clear queue is live while finished rows exist', await ev('document.getElementById("btnClear").getAttribute("aria-disabled")==="false"'));
    const keep = await ev('[...document.querySelectorAll("#queue .qr.queued,#queue .qr.running")].map(r=>r.dataset.id)');
    const b2 = mockLog().length;
    await clickSel('#btnClear');
    check('Clear queue removes every done, failed and cancelled row', await waitFor('!document.querySelector("#queue .qr.done,#queue .qr.failed,#queue .qr.cancelled")', 3000));
    const left = await ev('[...document.querySelectorAll("#queue .qr")].map(r=>r.dataset.id)');
    check('Clear queue leaves queued and running rows alone', keep.length > 0 && keep.every((id) => left.includes(id)), JSON.stringify({ keep, left }));
    check('Clear queue called /jobs/clear', mockLog().slice(b2).some((l) => l.path === '/jobs/clear'));
    check('Result player still not blanked after Clear queue', await ev('(()=>{const v=document.getElementById("resultVideo");return !v.hidden&&v.src.startsWith("file:///")})()') && (await text('#resultPath')) === shownPath);
    // dimmed when nothing is finished (a job may have just finished meanwhile: clear once more if so)
    for (let n = 0; n < 3 && (await ev('document.getElementById("btnClear").getAttribute("aria-disabled")')) === 'false'; n++) { await clickSel('#btnClear'); await sleep(500); }
    check('Clear queue is dimmed when there is nothing to clear', await waitFor('document.getElementById("btnClear").getAttribute("aria-disabled")==="true"&&getComputedStyle(document.getElementById("btnClear")).opacity==="0.4"', 3000));
    const b3c = mockLog().length;
    await clickSel('#btnClear');
    await sleep(300);
    check('the dimmed Clear queue button does nothing (no /jobs/clear call)', !mockLog().slice(b3c).some((l) => l.path === '/jobs/clear'));
    mock.state.hold = false;
    // a newer finished job replaces the video
    await post('/_mock/seed', { status: 'done', offset: 5000, result: 'D:\\Project_lip_service\\outputs\\newer-shot.mp4' });
    check('a newer finished job replaces the video in the Result player', await waitFor('document.getElementById("resultPath").textContent.endsWith("newer-shot.mp4")', 4000));
  }

  await fullscreenChecks();

  // ---- phase 7b: Best not available (model file missing). Reloads the page, so this runs last. ----
  {
    mock.state.bestEnabled = false;
    wc.reload();
    await new Promise((r) => wc.once('did-finish-load', r));
    check('Best disabled: the label is dimmed with the note as tooltip', await waitFor('(()=>{const b=document.querySelector("#qlabels .ql[data-pos=\\"best\\"]");return !!b&&b.getAttribute("aria-disabled")==="true"&&b.title==="The Q6_K model file is missing"&&getComputedStyle(b).opacity==="0.4"})()', 5000));
    check('Best disabled: Default is still selected on load', await ev('document.getElementById("quality").value==="1"&&document.querySelectorAll("#qlabels .ql")[1].classList.contains("cur")'));
    await clickSel('#qlabels .ql[data-pos="best"]');
    check('Best disabled: clicking its label does nothing', (await ev('document.getElementById("quality").value')) === '1');
    await ev('document.getElementById("quality").focus()');
    await key('End');
    check('Best disabled: End key does not rest on Best', (await ev('document.getElementById("quality").value')) === '1' && (await ev('document.querySelectorAll("#qlabels .ql")[1].classList.contains("cur")')));
    const rr = await rectOf('#quality');
    await cdp('Input.dispatchMouseEvent', { type: 'mouseMoved', x: rr.x + rr.w / 2, y: rr.y + rr.h / 2 });
    await mouse('mousePressed', rr.x + rr.w / 2, rr.y + rr.h / 2);
    await cdp('Input.dispatchMouseEvent', { type: 'mouseMoved', x: rr.x + rr.w + 20, y: rr.y + rr.h / 2, button: 'left', buttons: 1 });
    await mouse('mouseReleased', rr.x + rr.w + 20, rr.y + rr.h / 2);
    await sleep(150);
    check('Best disabled: dragging to the right end snaps back, not onto Best', (await ev('document.getElementById("quality").value')) !== '2' && !(await shown('#ramNotice')));
    await clickSel('#qlabels .ql[data-pos="fast"]');
    check('Best disabled: the other two positions still work', (await ev('document.getElementById("quality").value')) === '0');
    mock.state.bestEnabled = true;
  }

  // ---- window buttons ----
  await clickSel('#wMax');
  await sleep(400);
  check('maximize button maximizes', win.isMaximized());
  await clickSel('#wMax');
  await sleep(400);
  check('maximize button again restores', !win.isMaximized());
  await clickSel('#wMin');
  await sleep(400);
  check('minimize button minimizes', win.isMinimized());
  win.restore();
  await sleep(200);

  // ---- network and console ----
  const httpSeen = seen.filter((u) => /^https?:/i.test(u));
  const tport = process.env.LIP_TEST_PORT || '8780';
  const stray = httpSeen.filter((u) => !u.startsWith('http://127.0.0.1:' + tport + '/'));
  check('page only reached 127.0.0.1:' + tport + ' (' + httpSeen.length + ' requests)', stray.length === 0, stray.join(' '));
  check('no request was blocked', blocked.length === 0, blocked.join(' '));
  check('every other request is file:, data: or blob:', seen.filter((u) => !/^https?:/i.test(u)).every((u) => /^(file|data|blob|devtools):/i.test(u)));
  check('no console errors', consoleErrors.length === 0, consoleErrors.join(' | '));

  // ---- close button last ----
  const closed = new Promise((r) => win.once('closed', () => r(true)));
  wc.debugger.detach();
  await ev('document.getElementById("wClose").click()').catch(() => {});
  check('close button closes the window', await Promise.race([closed, sleep(3000).then(() => false)]));
  mock.close();
  console.log(fails === 0 ? 'SMOKE PASS' : 'SMOKE FAIL (' + fails + ')');
  return fails === 0 ? 0 : 1;
}

module.exports = { run };
