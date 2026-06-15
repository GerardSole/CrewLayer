'use strict';

const {
  app, BrowserWindow, BrowserView, Tray, Menu,
  nativeImage, ipcMain, dialog, shell, clipboard, Notification,
} = require('electron');
const { autoUpdater } = require('electron-updater');
const path  = require('path');
const fs    = require('fs');
const { spawn } = require('child_process');
const http  = require('http');
const crypto = require('crypto');

// ── Constants ──────────────────────────────────────────────────────────────

const TOOLBAR_H  = 48;
const PG_PORT    = 5433;
const REDIS_PORT = 6380;

// ── State ──────────────────────────────────────────────────────────────────

let mainWin    = null;
let splashWin  = null;
let onboardWin = null;
let settingsWin = null;
let tray       = null;
let dashView   = null;
let pgInstance = null;
let redisProc  = null;
let backendProc = null;
let settings   = {};
let isQuitting = false;

const svcStatus = { api: false, postgres: false, redis: false };

// ── Paths ──────────────────────────────────────────────────────────────────

const userData     = app.getPath('userData');
const dataDir      = path.join(userData, 'data');
const settingsFile = path.join(userData, 'settings.json');
const pgDataDir    = path.join(dataDir, 'postgres');
const rendererDir  = path.join(__dirname, 'renderer');

const resPath = (...p) => path.join(
  app.isPackaged ? process.resourcesPath : path.join(__dirname, '..', '..', 'resources'),
  ...p,
);

const redisBin = () => {
  if (process.platform === 'win32')  return resPath('redis', 'win-x64', 'redis-server.exe');
  if (process.platform === 'darwin') return resPath('redis', process.arch === 'arm64' ? 'mac-arm64' : 'mac-x64', 'redis-server');
  return resPath('redis', 'linux-x64', 'redis-server');
};

const backendBin = () =>
  resPath('backend', `crewlayer-backend${process.platform === 'win32' ? '.exe' : ''}`);

// ── Settings ───────────────────────────────────────────────────────────────

function loadSettings() {
  let saved = {};
  try {
    if (fs.existsSync(settingsFile)) saved = JSON.parse(fs.readFileSync(settingsFile, 'utf8'));
  } catch (_) {}

  settings = {
    apiPort: 8000,
    onboardingDone: false,
    apiKey: `crwl_${crypto.randomBytes(24).toString('hex')}`,
    tenantId: crypto.randomUUID(),
    secretKey: crypto.randomBytes(32).toString('hex'),
    anthropicApiKey: '',
    useDocker: false,
    ...saved,
  };
  persistSettings();
}

function persistSettings(patch = {}) {
  Object.assign(settings, patch);
  fs.mkdirSync(path.dirname(settingsFile), { recursive: true });
  fs.writeFileSync(settingsFile, JSON.stringify(settings, null, 2));
}

// ── Progress ───────────────────────────────────────────────────────────────

function progress(message, percent, step = '') {
  if (splashWin && !splashWin.isDestroyed())
    splashWin.webContents.send('startup-progress', { message, percent, step });
}

// ── Windows ────────────────────────────────────────────────────────────────

function preloadOpts() {
  return {
    preload: path.join(__dirname, 'preload.js'),
    contextIsolation: true,
    nodeIntegration: false,
  };
}

function createSplashWindow() {
  splashWin = new BrowserWindow({
    width: 480, height: 300,
    frame: false, transparent: true,
    resizable: false, center: true,
    alwaysOnTop: true,
    webPreferences: preloadOpts(),
  });
  splashWin.loadFile(path.join(rendererDir, 'index.html'));
}

function createMainWindow() {
  const isMac = process.platform === 'darwin';
  mainWin = new BrowserWindow({
    width: 1280, height: 820,
    minWidth: 900, minHeight: 600,
    frame: isMac,
    titleBarStyle: isMac ? 'hiddenInset' : 'hidden',
    trafficLightPosition: isMac ? { x: 16, y: 16 } : undefined,
    show: false,
    webPreferences: preloadOpts(),
  });
  mainWin.loadFile(path.join(rendererDir, 'app.html'));

  // BrowserView hosts the FastAPI dashboard
  dashView = new BrowserView({ webPreferences: { contextIsolation: true } });
  mainWin.addBrowserView(dashView);
  resizeDash();
  dashView.webContents.loadURL(`http://localhost:${settings.apiPort}/dashboard`);

  mainWin.on('resize', resizeDash);
  mainWin.on('close', e => {
    if (!isQuitting) { e.preventDefault(); mainWin.hide(); }
  });
  mainWin.once('ready-to-show', () => mainWin.show());
}

function resizeDash() {
  if (!dashView || !mainWin || mainWin.isDestroyed()) return;
  const [w, h] = mainWin.getContentSize();
  dashView.setBounds({ x: 0, y: TOOLBAR_H, width: w, height: h - TOOLBAR_H });
}

function createOnboardWin() {
  onboardWin = new BrowserWindow({
    width: 620, height: 520,
    frame: false, resizable: false, center: true,
    webPreferences: preloadOpts(),
  });
  onboardWin.loadFile(path.join(rendererDir, 'onboarding.html'));
  onboardWin.on('closed', () => { onboardWin = null; });
}

function createSettingsWin() {
  if (settingsWin && !settingsWin.isDestroyed()) { settingsWin.focus(); return; }
  settingsWin = new BrowserWindow({
    width: 520, height: 680,
    frame: false, resizable: false,
    parent: mainWin || undefined,
    webPreferences: preloadOpts(),
  });
  settingsWin.loadFile(path.join(rendererDir, 'settings.html'));
  settingsWin.on('closed', () => { settingsWin = null; });
}

// ── Tray ───────────────────────────────────────────────────────────────────

function createTray() {
  const iconFile = path.join(__dirname, '..', 'assets', 'tray-icon.png');
  const icon = fs.existsSync(iconFile)
    ? nativeImage.createFromPath(iconFile).resize({ width: 16 })
    : nativeImage.createEmpty();
  tray = new Tray(icon);
  tray.setToolTip('CrewLayer');
  rebuildTrayMenu();
  tray.on('click', () => { mainWin?.show(); mainWin?.focus(); });
}

function rebuildTrayMenu() {
  if (!tray) return;
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Open Dashboard', click: () => { mainWin?.show(); mainWin?.focus(); } },
    { label: `API: http://localhost:${settings.apiPort}`, enabled: false },
    { type: 'separator' },
    { label: 'Restart Services', click: restartServices },
    { label: 'Settings…',        click: createSettingsWin },
    { type: 'separator' },
    { label: 'Quit', click: () => { isQuitting = true; app.quit(); } },
  ]));
}

// ── Service status ─────────────────────────────────────────────────────────

function broadcastStatus() {
  const payload = { ...svcStatus };
  for (const w of [mainWin, settingsWin]) {
    if (w && !w.isDestroyed()) w.webContents.send('service-status', payload);
  }
}

function startHealthMonitor() {
  setInterval(async () => {
    const was = svcStatus.api;
    svcStatus.api = await ping(settings.apiPort);
    if (was !== svcStatus.api) broadcastStatus();
  }, 5000);
}

// ── Services ───────────────────────────────────────────────────────────────

async function startPostgres() {
  const { EmbeddedPostgres } = require('embedded-postgres');
  fs.mkdirSync(pgDataDir, { recursive: true });
  pgInstance = new EmbeddedPostgres({
    databaseDir: pgDataDir,
    user: 'crewlayer',
    password: 'crewlayer',
    port: PG_PORT,
    persistent: true,
  });
  await pgInstance.initialise();
  await pgInstance.start();
  try { await pgInstance.createDatabase('crewlayer'); } catch (_) { /* already exists */ }
  svcStatus.postgres = true;
}

async function startRedis() {
  const bin = redisBin();
  if (!fs.existsSync(bin)) {
    if (!app.isPackaged) { svcStatus.redis = true; return; }
    throw new Error(`Redis binary not found at:\n${bin}\n\nRun: npm run download-redis`);
  }
  if (process.platform !== 'win32') fs.chmodSync(bin, 0o755);
  const dir = path.join(dataDir, 'redis');
  fs.mkdirSync(dir, { recursive: true });

  return new Promise((resolve, reject) => {
    redisProc = spawn(bin, [
      '--port', String(REDIS_PORT),
      '--dir', dir,
      '--loglevel', 'warning',
    ], { stdio: 'pipe' });

    let resolved = false;
    const ok = () => { if (!resolved) { resolved = true; svcStatus.redis = true; resolve(); } };

    redisProc.stdout.on('data', d => { if (d.toString().includes('Ready to accept')) ok(); });
    redisProc.on('error', e => { if (!resolved) { resolved = true; reject(e); } });
    setTimeout(ok, 3500); // fallback — redis may not log that line on every OS
  });
}

async function startBackend() {
  if (!app.isPackaged) {
    // Dev mode: assume the Python server is started separately
    svcStatus.api = await ping(settings.apiPort);
    return;
  }
  const bin = backendBin();
  if (!fs.existsSync(bin)) throw new Error(`Backend binary not found at:\n${bin}\n\nRun: npm run build-backend`);
  if (process.platform !== 'win32') fs.chmodSync(bin, 0o755);

  const env = {
    ...process.env,
    DATABASE_URL:      `postgresql+asyncpg://crewlayer:crewlayer@localhost:${PG_PORT}/crewlayer`,
    REDIS_URL:         `redis://localhost:${REDIS_PORT}`,
    SECRET_KEY:        settings.secretKey,
    ANTHROPIC_API_KEY: settings.anthropicApiKey || '',
    PORT:              String(settings.apiPort),
    CREWLAYER_DATA_DIR: dataDir,
  };
  backendProc = spawn(bin, [], { env, stdio: 'pipe' });
  backendProc.on('exit', code => {
    if (!isQuitting && code !== 0) { svcStatus.api = false; broadcastStatus(); }
  });
}

function ping(port) {
  return new Promise(resolve => {
    const req = http.get(
      { hostname: 'localhost', port, path: '/health', timeout: 2000 },
      res => { resolve(res.statusCode === 200); res.resume(); }
    );
    req.on('error',   () => resolve(false));
    req.on('timeout', () => { req.destroy(); resolve(false); });
  });
}

async function restartServices() {
  backendProc?.kill(); backendProc = null;
  redisProc?.kill();   redisProc   = null;
  svcStatus.api = svcStatus.redis = false;
  broadcastStatus();
  try {
    await startRedis();
    await startBackend();
    const port = settings.apiPort;
    const t = Date.now();
    while (!(await ping(port))) {
      if (Date.now() - t > 60000) throw new Error('Timeout waiting for API');
      await new Promise(r => setTimeout(r, 500));
    }
    svcStatus.api = true;
    broadcastStatus();
    dashView?.webContents.reload();
  } catch (e) {
    dialog.showErrorBox('Restart failed', e.message);
  }
}

// ── Startup sequence ───────────────────────────────────────────────────────

async function startup() {
  try {
    progress('Starting PostgreSQL…', 10, 'postgres');
    await startPostgres();
    progress('PostgreSQL ready', 30, 'postgres');

    progress('Starting Redis…', 35, 'redis');
    await startRedis();
    progress('Redis ready', 50, 'redis');

    progress('Starting CrewLayer API…', 55, 'backend');
    await startBackend();
    progress('Waiting for API to be ready…', 65, 'backend');

    let pct = 65;
    const t0 = Date.now();
    while (!(await ping(settings.apiPort))) {
      if (Date.now() - t0 > 60000) throw new Error('API did not start within 60 seconds.');
      pct = Math.min(pct + 0.4, 94);
      progress('Waiting for API to be ready…', pct, 'backend');
      await new Promise(r => setTimeout(r, 500));
    }
    svcStatus.api = true;
    progress('CrewLayer is ready!', 100, 'done');
    await new Promise(r => setTimeout(r, 700));

    splashWin?.close(); splashWin = null;

    if (!settings.onboardingDone) {
      createOnboardWin();
    } else {
      createMainWindow();
    }

    createTray();
    startHealthMonitor();
    if (app.isPackaged) autoUpdater.checkForUpdatesAndNotify();

  } catch (err) {
    dialog.showErrorBox('CrewLayer failed to start', err.message);
    app.quit();
  }
}

// ── IPC handlers ───────────────────────────────────────────────────────────

ipcMain.handle('get-settings', () => {
  const { secretKey, ...safe } = settings;
  return { ...safe, version: app.getVersion(), platform: process.platform };
});

ipcMain.handle('save-settings', (_, patch) => {
  persistSettings(patch);
  rebuildTrayMenu();
  return { ok: true };
});

ipcMain.handle('copy-text',        (_, text) => clipboard.writeText(text));
ipcMain.handle('open-external',    (_, url)  => shell.openExternal(url));
ipcMain.handle('open-settings',    ()        => createSettingsWin());
ipcMain.handle('minimize-to-tray', ()        => mainWin?.hide());
ipcMain.handle('restart-services', ()        => restartServices());
ipcMain.handle('service-status',   ()        => ({ ...svcStatus }));
ipcMain.handle('check-updates',    ()        => { if (app.isPackaged) autoUpdater.checkForUpdates(); return true; });

ipcMain.handle('close-window', e => {
  BrowserWindow.fromWebContents(e.sender)?.close();
});

ipcMain.handle('open-dashboard', () => {
  onboardWin?.close();
  persistSettings({ onboardingDone: true });
  createMainWindow();
});

ipcMain.handle('reset-data', async () => {
  const { response } = await dialog.showMessageBox({
    type: 'warning',
    buttons: ['Cancel', 'Reset All Data'],
    defaultId: 0, cancelId: 0,
    title: 'Reset All Data',
    message: 'Delete all agents, memories, and actions?',
    detail: 'This action cannot be undone.',
  });
  if (response !== 1) return { ok: false };

  backendProc?.kill();
  redisProc?.kill();
  try { await Promise.race([pgInstance?.stop?.(), new Promise(r => setTimeout(r, 4000))]); } catch (_) {}
  fs.rmSync(dataDir, { recursive: true, force: true });
  persistSettings({ onboardingDone: false });
  app.relaunch();
  app.quit();
  return { ok: true };
});

// ── Auto-updater ───────────────────────────────────────────────────────────

autoUpdater.on('update-available', ({ version }) => {
  mainWin?.webContents.send('update-available', { version });
});

autoUpdater.on('update-downloaded', () => {
  const n = new Notification({
    title: 'CrewLayer update ready',
    body: 'A new version has been downloaded. Click to restart and install.',
  });
  n.on('click', () => autoUpdater.quitAndInstall());
  n.show();
});

// ── App lifecycle ──────────────────────────────────────────────────────────

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => { mainWin?.show(); mainWin?.focus(); });

  app.whenReady().then(async () => {
    loadSettings();
    fs.mkdirSync(dataDir, { recursive: true });
    createSplashWindow();
    await new Promise(r => setTimeout(r, 350)); // let splash render
    startup();
  });
}

app.on('window-all-closed', () => { /* keep alive via tray */ });
app.on('activate',          () => mainWin?.show());
app.on('before-quit',       () => { isQuitting = true; });

app.on('will-quit', async e => {
  e.preventDefault();
  backendProc?.kill();
  redisProc?.kill();
  try {
    await Promise.race([
      pgInstance?.stop?.(),
      new Promise(r => setTimeout(r, 4000)),
    ]);
  } catch (_) {}
  app.exit(0);
});
