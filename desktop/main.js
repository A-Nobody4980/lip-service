const { app, BrowserWindow, session, ipcMain, Menu } = require('electron');
const path = require('path');
const menus = require('./menus.js');

const SMOKE = process.argv.includes('--smoke');
const REAL = process.argv.includes('--real'); // scripted run against the real backend, no mock
const FS_ONLY = process.argv.includes('--smoke-fs'); // fullscreen check only: no mock backend, page traffic cancelled
const HIDDEN = SMOKE || REAL || FS_ONLY;

// Every Electron path stays inside the project (nothing on the C drive). Set before the app is ready.
const DATA = path.join(__dirname, '..', 'state', 'electron');
for (const [name, dir] of [
  ['appData', DATA], ['userData', path.join(DATA, 'user')], ['sessionData', path.join(DATA, 'session')],
  ['crashDumps', path.join(DATA, 'crashes')], ['logs', path.join(DATA, 'logs')], ['temp', path.join(DATA, 'temp')],
]) app.setPath(name, dir);
app.commandLine.appendSwitch('disk-cache-dir', path.join(DATA, 'cache'));

// No Chromium background networking. No crashReporter.start(). No autoUpdater calls anywhere.
app.commandLine.appendSwitch('disable-background-networking');
// The window must not touch the GPU while a render owns the 12 GB card.
app.disableHardwareAcceleration();

// The smoke test runs against the mock backend with its own throwaway token.
if (SMOKE && !process.env.LIPSERVICE_TOKEN) process.env.LIPSERVICE_TOKEN = 'smoke-' + Math.random().toString(16).slice(2);

const seen = []; // every request URL the page made (smoke test reads this)
const blocked = [];

// Smoke test on another port (LIP_TEST_PORT): load a throwaway copy of the page whose CSP names that port.
function pagePath() {
  const port = process.env.LIP_TEST_PORT;
  if (!SMOKE || !/^\d{4,5}$/.test(port || '')) return path.join(__dirname, 'index.html');
  const fs = require('fs');
  const dir = path.join(DATA, 'temp', 'smoke-page');
  fs.mkdirSync(dir, { recursive: true });
  for (const f of ['app.js', 'styles.css', 'icon-small.png', 'icon.png']) { try { fs.copyFileSync(path.join(__dirname, f), path.join(dir, f)); } catch (e) { /* optional files */ } }
  fs.writeFileSync(path.join(dir, 'index.html'), fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8').split('http://127.0.0.1:8780').join('http://127.0.0.1:' + port));
  return path.join(dir, 'index.html');
}

function createWindow() {
  const win = new BrowserWindow({
    width: 960, height: 900, minWidth: 560, minHeight: 480,
    frame: false, autoHideMenuBar: true, backgroundColor: '#07070b', title: 'Lip Service', show: !HIDDEN,
    icon: path.join(__dirname, 'icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      sandbox: true, contextIsolation: true, nodeIntegration: false, spellcheck: false,
      backgroundThrottling: !HIDDEN,
    },
  });
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.webContents.on('will-navigate', (e) => e.preventDefault());
  win.setMenuBarVisibility(false);
  // Right-click menu for text boxes and selected text (Cut, Copy, Paste, Select all).
  win.webContents.on('context-menu', (e, params) => {
    const t = menus.contextTemplate(params);
    if (t) Menu.buildFromTemplate(t).popup({ window: win });
  });
  win.loadFile(pagePath());
  return win;
}

app.whenReady().then(async () => {
  // Edit-only menu (never shown): keeps Ctrl+Z/Y/X/C/V/A working. See menus.js.
  Menu.setApplicationMenu(Menu.buildFromTemplate(menus.editMenuTemplate()));
  const ses = session.defaultSession;
  ses.setSpellCheckerEnabled(false);
  // Everything is denied except fullscreen (the Result video's fullscreen button), and only for our own page.
  const ownPage = (url) => { try { return new URL(url).protocol === 'file:'; } catch (e) { return false; } };
  ses.setPermissionRequestHandler((wc, permission, cb, details) => cb(permission === 'fullscreen' && ownPage((details && details.requestingUrl) || wc.getURL())));
  ses.setPermissionCheckHandler((wc, permission, origin, details) => permission === 'fullscreen' && ownPage((details && details.requestingUrl) || origin || (wc && wc.getURL())));
  // Local only: cancel anything not on this PC and log what was cancelled.
  ses.webRequest.onBeforeRequest((details, callback) => {
    const u = new URL(details.url);
    const local = ['file:', 'devtools:', 'data:', 'blob:'].includes(u.protocol) || ['127.0.0.1', 'localhost'].includes(u.hostname);
    if (FS_ONLY && /^https?:/i.test(details.url)) return callback({ cancel: true });
    seen.push(details.url);
    if (!local) { blocked.push(details.url); console.log('request BLOCKED ' + details.url); }
    callback({ cancel: !local });
  });

  let mock = null;
  if (SMOKE) {
    try { mock = await require('./dev/mock-server.js').start({ token: process.env.LIPSERVICE_TOKEN, runSeconds: 8 }); }
    catch (e) {
      console.log(e.code === 'EADDRINUSE' ? 'BLOCKED: port 8780 is busy, smoke test not run' : 'FAIL mock server: ' + e.message);
      app.exit(2); return;
    }
  }

  if (REAL && !process.env.LIPSERVICE_TOKEN) { console.log('FAIL LIPSERVICE_TOKEN is not set'); app.exit(2); return; }
  const win = createWindow();
  ipcMain.handle('lip:window', (e, action) => {
    if (e.sender !== win.webContents) return;
    if (action === 'minimize') win.minimize();
    else if (action === 'maximize') { if (win.isMaximized()) win.unmaximize(); else win.maximize(); }
    else if (action === 'close') win.close();
  });

  if (FS_ONLY) setTimeout(() => { console.log('FAIL smoke-fs timed out'); app.exit(3); }, 90000);
  if (SMOKE || FS_ONLY) {
    const arg = process.argv.find((a) => a.startsWith('--shot='));
    require('./dev/smoke.js').run({ win, mock, seen, blocked, fsOnly: FS_ONLY, shotBase: arg ? arg.slice(7) : null })
      .then((code) => app.exit(code), (e) => { console.log('FAIL smoke crashed: ' + e.stack); app.exit(1); });
  }
  if (REAL) {
    require('./dev/real-run.js').run({ win, seen, blocked })
      .then((code) => app.exit(code), (e) => { console.log('FAIL real run crashed: ' + e.stack); app.exit(1); });
  }
});

app.on('window-all-closed', () => { if (!HIDDEN) app.quit(); });
