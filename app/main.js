// Partsfinder - main process of the Electron app.
//
// - Looks for the Python API at http://127.0.0.1:8000. If it is not running, the app starts
//   it itself (backend/.venv) and stops it again on exit.
// - Installed (app.isPackaged): the search engine is the bundled resources/backend/partsfinder-backend(.exe)
//   on port 8731, with the library, uploads and settings in the user's own data folder
//   (%APPDATA%\Partsfinder on Windows) and the bundled embedding model (resources/model), so it works offline.
// - All HTTP traffic goes through this main process (IPC); the window itself has no access
//   to Node or the file system.
//
// Settings via environment variables (mainly for tests):
//   PARTSFINDER_API_URL   other API, e.g. http://127.0.0.1:8765
//   PARTSFINDER_NO_SPAWN  1 = never start a server yourself
//   PARTSFINDER_API_KEY   key to sign in with (otherwise the app asks when the search engine needs one)
//   PARTSFINDER_USER_DATA other folder for the app's own data (saved keys, and when installed the library)
//
// The AI runs on the user's own Anthropic API key (Settings). The app keeps it encrypted by the OS
// (safeStorage, anthropic-key.bin in the app's data folder), never as plain text, and hands it to the
// search engine on this pc only (POST /settings/ai); the search engine keeps it in memory.
//
// Signing in (docs/10_COMPANY_LIBRARIES.md): with a name and password (accounts), or with an API key
// (PARTSFINDER_API_KEYS). Either gives a token that stays in this main process: every request gets
// "Authorization: Bearer <token>", also the previews (<img>) and the datasheet window, via the session
// (onBeforeSendHeaders), so the window never sees or holds it. "Remember" stores it encrypted by Windows
// (safeStorage), never as plain text. A company uploads a folder from this pc to its own library; the folder
// rules (.partsfinderignore, .partsfinderaccess) are applied here first, so an excluded file is never even read (rules.js).

const { app, BrowserWindow, ipcMain, dialog, shell, session, safeStorage } = require('electron');
const { spawn } = require('node:child_process');
const rules = require('./rules');
const fs = require('node:fs');
const path = require('node:path');

const PACKAGED = app.isPackaged;
if (process.env.PARTSFINDER_USER_DATA) app.setPath('userData', path.resolve(process.env.PARTSFINDER_USER_DATA));
const API = (process.env.PARTSFINDER_API_URL || `http://127.0.0.1:${PACKAGED ? 8731 : 8000}`).replace(/\/$/, '');
const BACKEND = path.resolve(__dirname, '..', 'backend');
const PYTHON = process.platform === 'win32'
  ? path.join(BACKEND, '.venv', 'Scripts', 'python.exe')
  : path.join(BACKEND, '.venv', 'bin', 'python');
const START_HINT = PACKAGED ? 'Close every Partsfinder window and start Partsfinder again.'
  : 'Close api.bat (or every Partsfinder window) and start app.bat again.';

// How to start the search engine: the bundled program when installed, backend/.venv when run from the source.
function backendCommand(port) {
  if (!PACKAGED) {
    return { cmd: PYTHON, args: ['-m', 'partsfinder.api', '--port', port], cwd: BACKEND, env: {},
             missing: 'Python environment not found. Run setup_windows.bat first.' };
  }
  const res = process.resourcesPath;
  const data = app.getPath('userData');
  const env = {
    PARTSFINDER_HOME: process.env.PARTSFINDER_HOME || data,
    PARTSFINDER_DB_PATH: process.env.PARTSFINDER_DB_PATH || path.join(data, 'partsfinder.db'),
    PARTSFINDER_DATA_DIR: process.env.PARTSFINDER_DATA_DIR || path.join(data, 'data'),
    HF_HOME: process.env.HF_HOME || path.join(data, 'models'),
  };
  // the name keeps "e5": the search engine adds the prefixes that e5 models expect
  const model = path.join(res, 'model', 'multilingual-e5-small');
  if (!process.env.PARTSFINDER_EMBEDDING_MODEL && fs.existsSync(path.join(model, 'config.json'))) {
    env.PARTSFINDER_EMBEDDING_MODEL = model;
    env.HF_HUB_OFFLINE = '1';
  }
  const exe = path.join(res, 'backend', process.platform === 'win32' ? 'partsfinder-backend.exe' : 'partsfinder-backend');
  return { cmd: exe, args: ['--port', port], cwd: data, env,
           missing: 'The search engine is missing from this installation. Reinstall Partsfinder.' };
}

let win = null;
let server = null;          // the Python process, if we started it
let serverLog = '';
let backendState = { state: 'starting', message: 'Looking for the search engine...' };
let apiKey = (process.env.PARTSFINDER_API_KEY || '').trim() || null;
let who = null;             // GET /me for the current token: role, username, company_id, groups
let authInfo = { accounts: false, setup_needed: false, keys_required: false };

// ---- the key ----------------------------------------------------------------------------------
function keyFile() { return path.join(app.getPath('userData'), 'api-key.bin'); }

function loadSavedKey() {
  try {
    if (!safeStorage.isEncryptionAvailable()) return null;
    return safeStorage.decryptString(fs.readFileSync(keyFile())).trim() || null;
  } catch { return null; }
}

function saveKey(key) {
  try {
    if (!key) { fs.rmSync(keyFile(), { force: true }); return true; }
    if (!safeStorage.isEncryptionAvailable()) return false;      // never write the key as plain text
    fs.writeFileSync(keyFile(), safeStorage.encryptString(key), { mode: 0o600 });
    return true;
  } catch { return false; }
}

// ---- the user's own AI key (Anthropic) --------------------------------------------------------
function aiKeyFile() { return path.join(app.getPath('userData'), 'anthropic-key.bin'); }
let aiKeyThisSession = null;     // only when the OS cannot encrypt: used until the app closes, never written

function loadAiKey() {
  if (aiKeyThisSession) return aiKeyThisSession;
  try {
    if (!safeStorage.isEncryptionAvailable()) return null;
    return safeStorage.decryptString(fs.readFileSync(aiKeyFile())).trim() || null;
  } catch { return null; }
}

function storeAiKey(key) {
  aiKeyThisSession = null;
  if (!key) { try { fs.rmSync(aiKeyFile(), { force: true }); } catch { /* gone */ } return 'removed'; }
  if (!safeStorage.isEncryptionAvailable()) { aiKeyThisSession = key; return 'session'; }
  fs.writeFileSync(aiKeyFile(), safeStorage.encryptString(key), { mode: 0o600 });
  return 'stored';
}

function maySetAi() { return Boolean(who && (who.role === 'local' || who.role === 'admin')); }

// after connecting: give the search engine the saved key (a key in backend/.env also works without the app)
async function pushAiKey() {
  const key = loadAiKey();
  if (key && maySetAi()) await api('POST', '/settings/ai', { api_key: key });
}

function authHeaders(extra = {}) {
  return apiKey ? { ...extra, authorization: `Bearer ${apiKey}` } : extra;
}

// only for the search engine itself, never for another site
function isApiUrl(url) {
  return url === API || url.startsWith(API + '/') || url.startsWith(API + '?');
}

function setState(state, message) {
  backendState = { state, message };
  if (win && !win.isDestroyed()) win.webContents.send('backend-state', backendState);
}

async function api(method, route, body, { timeoutMs = 180000 } = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(API + route, {
      method,
      headers: authHeaders(body ? { 'content-type': 'application/json' } : {}),
      body: body ? JSON.stringify(body) : undefined,
      signal: ctrl.signal,
    });
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch { data = text; }
    if (!res.ok) {
      const detail = data && data.detail ? (typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)) : res.statusText;
      if (res.status === 404 && detail === 'Not Found') {
        // the route itself does not exist: an older search engine is still running (e.g. api.bat from before an update)
        return { ok: false, status: 404, error: 'The running search engine is an older version and does not know this yet. '
          + START_HINT };
      }
      if (res.status === 401 && !['/me', '/login', '/setup'].includes(route)) signedOut('Your sign-in has expired. Sign in again.');
      return { ok: false, status: res.status, error: detail };
    }
    return { ok: true, data };
  } catch (err) {
    const msg = err.name === 'AbortError' ? 'The search engine did not answer in time.' : 'The search engine is not reachable.';
    return { ok: false, status: 0, error: msg };
  } finally {
    clearTimeout(timer);
  }
}

async function isUp() {
  const r = await api('GET', '/health', null, { timeoutMs: 3000 });
  return r.ok ? r.data : null;
}

// The search engine is up: does it need a key, and is ours good?
async function connected(health) {
  authInfo = { accounts: Boolean(health.accounts), setup_needed: Boolean(health.setup_needed),
               keys_required: Boolean(health.keys_required) };
  if (!apiKey) apiKey = loadSavedKey();
  if (!health.keys_required && !health.accounts) {
    apiKey = null;                                   // nobody signs in on this library (one pc)
    who = { role: 'local', company_id: null, groups: [] };
    await pushAiKey();
    setState('ready', 'Connected');
    return;
  }
  if (apiKey) {
    const me = await api('GET', '/me');
    if (me.ok) { who = me.data; await pushAiKey(); setState('ready', 'Connected'); return; }
    if (me.status !== 401) { setState('error', me.error); return; }
    saveKey(null);
    apiKey = null;
  }
  if (health.keys_required) { signedOut('This library needs you to sign in.'); return; }
  who = { role: 'public', company_id: null, groups: [] };     // the general library, without signing in
  setState('ready', 'Connected');
}

function signedOut(message) {
  apiKey = null;
  if (authInfo.keys_required || !authInfo.accounts) {
    who = null;
    setState('signin', message);
  } else {
    who = { role: 'public', company_id: null, groups: [] };
    setState('ready', message);
  }
}

async function ensureBackend() {
  const up = await isUp();
  if (up) { await connected(up); return; }
  if (process.env.PARTSFINDER_NO_SPAWN === '1') {
    setState('error', `No search engine at ${API}. Start api.bat first.`);
    return;
  }
  const port = new URL(API).port || '8000';
  const run = backendCommand(port);
  if (!fs.existsSync(run.cmd)) {
    setState('error', run.missing);
    return;
  }
  setState('starting', 'Starting the search engine and loading the AI model, this takes about 15 seconds...');
  try { fs.mkdirSync(run.cwd, { recursive: true }); } catch { /* spawn reports it */ }
  server = spawn(run.cmd, run.args, {
    cwd: run.cwd,
    env: { ...process.env, ...run.env, PYTHONUTF8: '1', HF_HUB_DISABLE_SYMLINKS_WARNING: '1',
           TRANSFORMERS_VERBOSITY: 'error', HF_HUB_DISABLE_PROGRESS_BARS: '1' },
    windowsHide: true,
  });
  server.on('error', (err) => { server = null; setState('error', `The search engine could not start: ${err.message}`); });
  // only the last lines are ever shown (when it stops): keep the tail, not hours of output
  const keep = (d) => { serverLog = (serverLog + d).slice(-8000); };
  server.stdout.on('data', keep);
  server.stderr.on('data', keep);
  server.on('exit', (code) => {
    server = null;
    if (backendState.state !== 'ready') {
      const last = serverLog.trim().split('\n').slice(-3).join(' ');
      setState('error', `The search engine stopped right away (code ${code}). ${last}`);
    } else {
      setState('error', 'The search engine has stopped. Restart the app.');
    }
  });
  for (let i = 0; i < 180; i++) {          // max. 3 minutes (the first time loading the model can take a while)
    await new Promise((r) => setTimeout(r, 1000));
    if (!server) return;                   // process already stopped, error message is set
    const h = await isUp();
    if (h) { await connected(h); return; }
  }
  setState('error', 'The search engine did not start within 3 minutes.');
}

function createWindow() {
  win = new BrowserWindow({
    width: 1180,
    height: 860,
    minWidth: 720,
    minHeight: 560,
    title: 'Partsfinder',
    icon: path.join(__dirname, 'build', 'icon.ico'),
    backgroundColor: '#0B1624',           // same as the app's navy theme: no light flash at start
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));
  // open external links in the normal browser, never in the app
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//.test(url)) shell.openExternal(url);
    return { action: 'deny' };
  });
  win.webContents.on('will-navigate', (e) => e.preventDefault());
}

// ---- IPC: what the window may ask --------------------------------------------------
ipcMain.handle('config', () => ({ apiUrl: API, backend: backendState, who, auth: authInfo }));
ipcMain.handle('who', () => who);

// sign in with a key: checked with GET /me before it is used (or remembered)
ipcMain.handle('sign-in', async (_e, key, remember) => {
  key = typeof key === 'string' ? key.trim() : '';
  if (!key || key.length > 500 || /\s/.test(key)) return { ok: false, error: 'Enter the key you were given.' };
  const before = apiKey;
  apiKey = key;
  const me = await api('GET', '/me');
  if (!me.ok) {
    apiKey = before;
    return { ok: false, error: me.status === 401 ? 'This key is not accepted.' : me.error };
  }
  who = me.data;
  const saved = remember ? saveKey(key) : (saveKey(null), false);
  setState('ready', 'Connected');
  return { ok: true, data: { ...who, remembered: saved } };
});

// sign in with a name and password (or make the first admin account, on this pc only)
async function signInWith(route, username, password, remember) {
  if (typeof username !== 'string' || typeof password !== 'string') return { ok: false, error: 'Fill in both fields.' };
  const before = apiKey;
  apiKey = null;
  const r = await api('POST', route, { username: username.trim(), password, remember: Boolean(remember) });
  if (!r.ok) {
    apiKey = before;
    return { ok: false, error: r.status === 401 ? 'Wrong username or password.' : r.error };
  }
  apiKey = r.data.token;
  who = r.data.me;
  authInfo = { ...authInfo, accounts: true, setup_needed: false };
  const saved = remember ? saveKey(apiKey) : (saveKey(null), false);
  setState('ready', 'Connected');
  return { ok: true, data: { ...who, remembered: saved } };
}
ipcMain.handle('login', (_e, username, password, remember) => signInWith('/login', username, password, remember));
ipcMain.handle('setup', (_e, username, password, remember) => signInWith('/setup', username, password, remember));
ipcMain.handle('auth-info', async () => {
  const h = await api('GET', '/health', null, { timeoutMs: 5000 });
  if (h.ok) authInfo = { accounts: Boolean(h.data.accounts), setup_needed: Boolean(h.data.setup_needed),
                         keys_required: Boolean(h.data.keys_required) };
  return authInfo;
});

ipcMain.handle('sign-out', async () => {
  if (apiKey && who && who.username) await api('POST', '/logout');
  saveKey(null);
  signedOut('Signed out.');
  return { ok: true };
});

// ---- the admin: people and companies ------------------------------------------------------------
const okName = (u) => typeof u === 'string' && /^[A-Za-z0-9][A-Za-z0-9._-]{2,39}$/.test(u);
ipcMain.handle('users', () => api('GET', '/users'));
ipcMain.handle('user-create', (_e, body) => api('POST', '/users', body));
ipcMain.handle('user-update', (_e, username, body) => (okName(username)
  ? api('PATCH', `/users/${encodeURIComponent(username)}`, body) : { ok: false, error: 'Unknown user' }));
ipcMain.handle('user-delete', (_e, username) => (okName(username)
  ? api('DELETE', `/users/${encodeURIComponent(username)}`) : { ok: false, error: 'Unknown user' }));
ipcMain.handle('company-create', (_e, body) => api('POST', '/companies', body));
ipcMain.handle('company-delete', (_e, companyId) => (typeof companyId === 'string' && companyId
  ? api('DELETE', `/companies/${encodeURIComponent(companyId)}`) : { ok: false, error: 'Unknown company' }));

// who may see an uploaded folder (admin): set it, then wait for the library to apply it to the parts
ipcMain.handle('folder-access', async (_e, companyId, name, folderPath, access) => {
  if (typeof name !== 'string' || typeof folderPath !== 'string' || typeof access !== 'string') return { ok: false, error: 'Invalid' };
  const q = `?company_id=${encodeURIComponent(companyId || '')}`;
  const r = await api('PUT', `/uploads/${encodeURIComponent(name)}/access${q}`, { path: folderPath, access });
  if (!r.ok) return r;
  for (let i = 0; i < 600; i++) {
    await new Promise((res) => setTimeout(res, 700));
    const st = await api('GET', `/ingest/${r.data.job_id}${q}`);
    if (!st.ok) return st;
    if (st.data.status === 'done') return { ok: true, data: st.data.report };
    if (st.data.status === 'error') return { ok: false, error: st.data.error };
  }
  return { ok: false, error: 'Applying the setting takes too long.' };
});
ipcMain.handle('company-confidential', (_e, companyId, on) => (typeof companyId === 'string'
  ? api('POST', `/companies/${encodeURIComponent(companyId)}/settings`, { confidential: Boolean(on) }) : { ok: false }));

// ---- a company's own library: folders uploaded from this pc ---------------------------------------
const companyQuery = (companyId) => (companyId ? `?company_id=${encodeURIComponent(companyId)}` : '');
ipcMain.handle('library', (_e, companyId) => api('GET', `/library${companyQuery(companyId)}`));

// where each uploaded folder lives on this pc, so "Update" sends the same folder again
function folderMapFile() { return path.join(app.getPath('userData'), 'uploaded-folders.json'); }
function folderMap() { try { return JSON.parse(fs.readFileSync(folderMapFile(), 'utf8')); } catch { return {}; } }
function rememberFolder(key, dir) {
  const map = folderMap();
  map[key] = dir;
  try { fs.writeFileSync(folderMapFile(), JSON.stringify(map, null, 1)); } catch { /* not critical */ }
}

function uploadName(dir) {
  const name = path.basename(dir).replace(/[^A-Za-z0-9 _.()-]/g, '_').replace(/^[^A-Za-z0-9]+/, '').slice(0, 80).replace(/[. ]+$/, '');
  return name || 'Folder';
}

let uploading = false;
ipcMain.handle('upload-folder', async (_e, companyId, existingName, access) => {
  if (uploading) return { ok: false, error: 'An upload is already running.' };
  const info = await api('GET', `/library${companyQuery(companyId)}`);
  if (!info.ok) return info;
  const company = info.data.company_id;
  const key = `${API}|${company}|${existingName || ''}`;
  let dir = existingName ? folderMap()[key] : null;
  if (!dir || !fs.existsSync(dir)) {
    const pick = await dialog.showOpenDialog(win, {
      title: existingName ? `Choose the folder "${existingName}" again` : `Choose a folder with CAD files for ${company}`,
      properties: ['openDirectory'],
    });
    if (pick.canceled || !pick.filePaths.length) return { ok: false, canceled: true };
    dir = pick.filePaths[0];
  }
  const name = existingName || uploadName(dir);
  const send = (p) => { if (win && !win.isDestroyed()) win.webContents.send('upload-progress', { name, ...p }); };
  uploading = true;
  try {
    send({ phase: 'reading', text: 'Reading the folder and its rules...' });
    const found = rules.walk(dir, info.data.upload_extensions || ['step', 'stp', 'stl', 'json']);
    const files = found.files.slice();
    // a group set ABOVE the chosen folder goes along as the folder's own rule
    if (found.inherited !== undefined && !files.some((f) => f.rel.toLowerCase() === '.partsfinderaccess')) {
      files.push({ rel: '.partsfinderaccess', data: Buffer.from(`${found.inherited || 'company'}
`) });
    }
    const cad = files.filter((f) => f.abs && !/\.json$/i.test(f.rel) && !path.posix.basename(f.rel).startsWith('.'));
    if (!cad.length) {
      const why = found.skipped.length ? ' Some folders were skipped because a setting file in them could not be read.' : '';
      return { ok: false, error: `No CAD files to upload in this folder.${why}` };
    }
    const limit = (info.data.max_file_mb || 500) * 1024 * 1024;
    const tooBig = cad.filter((f) => f.abs && fs.statSync(f.abs).size > limit);
    if (tooBig.length) return { ok: false, error: `${path.basename(tooBig[0].abs)} is larger than ${info.data.max_file_mb} MB.` };

    const q = companyQuery(companyId);
    const start = await api('POST', `/uploads/${encodeURIComponent(name)}/start${q}`);
    if (!start.ok) return start;
    const uid = start.data.upload_id;
    const extra = companyId ? `&company_id=${encodeURIComponent(companyId)}` : '';
    for (let i = 0; i < files.length; i++) {
      const f = files[i];
      send({ phase: 'upload', done: i, total: files.length, text: `Uploading ${i + 1} of ${files.length}: ${f.rel}` });
      const url = `${API}/uploads/${encodeURIComponent(name)}/files?upload_id=${uid}&path=${encodeURIComponent(f.rel)}${extra}`;
      let res;
      try {
        res = await fetch(url, { method: 'PUT', headers: authHeaders({ 'content-type': 'application/octet-stream' }),
                                 body: f.data || await fs.promises.readFile(f.abs) });
      } catch { return { ok: false, error: 'The search engine is not reachable.' }; }
      if (!res.ok) {
        let msg = `Upload of ${f.rel} failed (${res.status}).`;
        try { const d = await res.json(); if (typeof d.detail === 'string') msg = d.detail; } catch { /* keep */ }
        return { ok: false, error: msg };
      }
    }
    send({ phase: 'import', text: 'Importing: measuring, previews and search entries...' });
    // who sees the new folder, when chosen in the app ('company' or groups); otherwise it stays as it was
    const chosen = typeof access === 'string' && /^[a-z0-9,_-]{1,400}$/.test(access) ? access : null;
    const fin = await api('POST', `/uploads/${encodeURIComponent(name)}/finish`,
      { upload_id: uid, company_id: companyId || null, ...(chosen ? { access: chosen } : {}) });
    if (!fin.ok) return fin;
    rememberFolder(`${API}|${company}|${name}`, dir);
    const deadline = Date.now() + 6 * 60 * 60 * 1000;
    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 1200));
      const st = await api('GET', `/ingest/${fin.data.job_id}${q}`);
      if (!st.ok) return st;
      if (st.data.status === 'done') {
        return { ok: true, data: { name, report: st.data.report, sent: files.length, excluded: found.excluded, skipped: found.skipped } };
      }
      if (st.data.status === 'error') return { ok: false, error: st.data.error };
      send({ phase: 'import', text: `Importing... ${st.data.lines} steps. ${st.data.log_tail.slice(-1)[0] || ''}` });
    }
    return { ok: false, error: 'The import takes too long (more than 6 hours).' };
  } catch (err) {
    return { ok: false, error: err instanceof rules.RuleError ? err.message : `Upload failed: ${err.message}` };
  } finally {
    uploading = false;
  }
});

ipcMain.handle('remove-folder', (_e, companyId, name) => (typeof name === 'string' && name
  ? api('DELETE', `/uploads/${encodeURIComponent(name)}${companyQuery(companyId)}`) : { ok: false, error: 'Unknown folder' }));
ipcMain.handle('health', () => api('GET', '/health'));
ipcMain.handle('app-info', () => ({ version: app.getVersion(), electron: process.versions.electron }));
ipcMain.handle('ai-settings', async () => {
  const h = await api('GET', '/health');
  return { ok: true, data: { may_set: maySetAi(), saved: Boolean(loadAiKey()), encrypted: safeStorage.isEncryptionAvailable(),
    ai_available: Boolean(h.ok && h.data.ai_available), ai_model: h.ok ? h.data.ai_model : null, ai_note: h.ok ? h.data.ai_note : h.error } };
});
ipcMain.handle('ai-key-set', async (_e, key) => {
  if (!maySetAi()) return { ok: false, error: 'Only the administrator can set the AI key.' };
  const k = typeof key === 'string' ? key.trim() : '';
  if (k.length > 300 || /\s/.test(k)) return { ok: false, error: 'That does not look like an API key.' };
  const r = await api('POST', '/settings/ai', { api_key: k || null });
  if (!r.ok) return r;
  let stored;
  try { stored = storeAiKey(k); } catch { return { ok: false, error: 'The key works, but it could not be saved on this pc.' }; }
  return { ok: true, data: { ...r.data, stored } };
});
ipcMain.handle('companies', () => api('GET', '/companies'));
ipcMain.handle('search', (_e, body) => api('POST', '/search', body));
ipcMain.handle('part', (_e, id, companyId) => {
  const q = companyId ? `?company_id=${encodeURIComponent(companyId)}` : '';
  return api('GET', `/parts/${encodeURIComponent(id)}${q}`);
});

ipcMain.handle('quality', (_e, companyId) => {
  const q = companyId ? `?company_id=${encodeURIComponent(companyId)}` : '';
  return api('GET', `/quality${q}`);
});

ipcMain.handle('duplicates', (_e, companyId, limit) => {
  const n = Number.isInteger(limit) && limit > 0 && limit <= 500 ? limit : 5;
  const q = companyId ? `?company_id=${encodeURIComponent(companyId)}&limit=${n}` : `?limit=${n}`;
  return api('GET', `/duplicates${q}`);
});

// what the Filters panel can offer (categories, materials, properties, ... of the parts this company may see)
ipcMain.handle('filters', (_e, companyId, category) => {
  const q = new URLSearchParams();
  if (companyId) q.set('company_id', companyId);
  if (typeof category === 'string' && category) q.set('category', category);
  const qs = q.toString();
  return api('GET', `/filters${qs ? `?${qs}` : ''}`);
});

// search with your own CAD file: the bytes go to the search engine, which measures them and keeps nothing
const SHAPE_MAX = 50 * 1024 * 1024;
ipcMain.handle('search-shape', async (_e, bytes, filename, companyId) => {
  const ext = typeof filename === 'string' ? path.extname(filename).toLowerCase() : '';
  if (!['.step', '.stp', '.stl'].includes(ext)) return { ok: false, error: 'Use a STEP or STL file.' };
  const data = bytes instanceof Uint8Array ? bytes : (bytes instanceof ArrayBuffer ? new Uint8Array(bytes) : null);
  if (!data || !data.length) return { ok: false, error: 'The file is empty.' };
  if (data.length > SHAPE_MAX) return { ok: false, error: 'The file is larger than 50 MB.' };
  const q = new URLSearchParams({ filename: `model${ext}`, limit: '8' });
  if (companyId) q.set('company_id', companyId);
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 120000);
  try {
    const res = await fetch(`${API}/search/shape?${q}`, { method: 'POST', body: data, signal: ctrl.signal,
      headers: authHeaders({ 'content-type': 'application/octet-stream' }) });
    const text = await res.text();
    let out = null;
    try { out = text ? JSON.parse(text) : null; } catch { out = text; }
    if (!res.ok) {
      if (res.status === 401) signedOut('Your sign-in has expired. Sign in again.');
      const detail = out && out.detail ? (typeof out.detail === 'string' ? out.detail : JSON.stringify(out.detail)) : res.statusText;
      return { ok: false, status: res.status, error: detail };
    }
    return { ok: true, data: out };
  } catch (err) {
    return { ok: false, status: 0, error: err.name === 'AbortError' ? 'Measuring the file took too long.' : 'The search engine is not reachable.' };
  } finally {
    clearTimeout(timer);
  }
});

ipcMain.handle('feedback', (_e, body) => api('POST', '/feedback', body));

// search with a photo or drawing (Claude identifies the part, then the normal search runs)
ipcMain.handle('search-image', (_e, body) => api('POST', '/search/image', body, { timeoutMs: 240000 }));

// links the window may ask for: one part's file, mesh or datasheet; never another route of the search engine
// (no "..", no second path, no fragment)
const partLink = (url, what) => typeof url === 'string'
  && new RegExp(`^/parts/[A-Za-z0-9][A-Za-z0-9._~%-]*/${what}(\\?[^#]*)?$`).test(url) && !url.includes('..');

// 3D mesh (binary STL) for the viewer in the window
ipcMain.handle('mesh', async (_e, url) => {
  if (!partLink(url, 'mesh')) return { ok: false, error: 'Invalid link' };
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 120000);      // the first time a large STEP is converted
  try {
    const res = await fetch(API + url, { signal: ctrl.signal, headers: authHeaders() });
    if (!res.ok) {
      let msg = `The 3D model could not be loaded (${res.status}).`;
      try { const d = await res.json(); if (d && typeof d.detail === 'string') msg = d.detail; } catch { /* keep msg */ }
      return { ok: false, error: msg };
    }
    return { ok: true, data: new Uint8Array(await res.arrayBuffer()) };
  } catch (err) {
    return { ok: false, error: err.name === 'AbortError' ? 'Preparing the 3D model takes too long.' : 'The search engine is not reachable.' };
  } finally {
    clearTimeout(timer);
  }
});

// datasheet in its own window (print -> Save as PDF works there)
ipcMain.handle('open-datasheet', (_e, url, title) => {
  if (!partLink(url, 'datasheet')) return { ok: false, error: 'Invalid link' };
  const sheet = new BrowserWindow({
    width: 900, height: 1000, parent: win, title: title ? `Datasheet - ${title}` : 'Datasheet',
    backgroundColor: '#E9EDF0', autoHideMenuBar: true,
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  sheet.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  sheet.webContents.on('will-navigate', (e) => e.preventDefault());
  sheet.loadURL(API + url);
  return { ok: true };
});

ipcMain.handle('similar', (_e, id, companyId) => {
  const q = companyId ? `&company_id=${encodeURIComponent(companyId)}` : '';
  return api('GET', `/parts/${encodeURIComponent(id)}/similar?limit=4${q}`);
});

ipcMain.handle('save-file', async (_e, url, suggestedName) => {
  if (!partLink(url, 'file')) return { ok: false, error: 'Invalid link' };
  let res;
  try { res = await fetch(API + url, { headers: authHeaders() }); } catch { return { ok: false, error: 'The search engine is not reachable.' }; }
  if (res.status === 401) signedOut('Your sign-in has expired. Sign in again.');
  if (!res.ok) {
    const msg = res.status === 410 ? 'The file is no longer at the stored location.' : `Download failed (${res.status}).`;
    return { ok: false, error: msg };
  }
  const header = res.headers.get('content-disposition') || '';
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(header);
  let name = suggestedName || 'model.step';
  if (match) {
    try { name = decodeURIComponent(match[1]); } catch { name = match[1]; }   // a stray % in the name must not crash
  }
  name = path.basename(name.replace(/\\/g, '/')) || 'model.step';              // never a path, only a file name
  const { canceled, filePath } = await dialog.showSaveDialog(win, {
    title: 'Save CAD file',
    defaultPath: path.join(app.getPath('downloads'), name),
  });
  if (canceled || !filePath) return { ok: false, canceled: true };
  try {
    await fs.promises.writeFile(filePath, Buffer.from(await res.arrayBuffer()));
  } catch (err) {
    // a read-only folder, a file that is open in another program, a full disk, the connection dropping
    return { ok: false, error: `The file could not be saved: ${err.code || err.message}.` };
  }
  shell.showItemInFolder(filePath);
  return { ok: true, path: filePath };
});

ipcMain.handle('pick-and-ingest', async (_e, companyId) => {
  const { canceled, filePaths } = await dialog.showOpenDialog(win, {
    title: 'Choose a folder with CAD files',
    properties: ['openDirectory'],
  });
  if (canceled || !filePaths.length) return { ok: false, canceled: true };
  if (win && !win.isDestroyed()) win.webContents.send('ingest-started', filePaths[0]);
  // in the background: search keeps working during the import; we poll the progress every 1.5 s
  const start = await api('POST', '/ingest', { folder: filePaths[0], company_id: companyId || null, background: true });
  if (!start.ok || !start.data.job_id) return start;     // error, or finished right away (without database file)
  const jobId = start.data.job_id;
  const deadline = Date.now() + 6 * 60 * 60 * 1000;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 1500));
    const st = await api('GET', `/ingest/${jobId}`);
    if (!st.ok) return st;
    if (st.data.status === 'done') return { ok: true, data: st.data.report };
    if (st.data.status === 'error') return { ok: false, status: 500, error: st.data.error };
    if (win && !win.isDestroyed()) win.webContents.send('ingest-progress', { lines: st.data.lines, last: st.data.log_tail.slice(-1)[0] || '' });
  }
  return { ok: false, status: 0, error: 'The import takes too long (more than 6 hours).' };
});

// ---- data packs: openly licensed libraries (admin, on the pc of the search engine) ---------------
ipcMain.handle('packs', () => api('GET', '/packs'));
ipcMain.handle('pack-remove', (_e, name) => (typeof name === 'string' && /^[a-z0-9][a-z0-9-]{1,60}$/.test(name)
  ? api('POST', `/packs/${name}/remove`) : { ok: false, error: 'Invalid pack name.' }));
ipcMain.handle('pack-install', async () => {
  if (!maySetAi()) return { ok: false, error: 'Only the administrator of this library can install data packs.' };
  const { canceled, filePaths } = await dialog.showOpenDialog(win, {
    title: 'Choose a Partsfinder data pack (.zip)',
    filters: [{ name: 'Partsfinder data pack', extensions: ['zip'] }],
    properties: ['openFile'],
  });
  if (canceled || !filePaths.length) return { ok: false, canceled: true };
  const start = await api('POST', '/packs/install', { path: filePaths[0] });
  if (!start.ok) return start;
  const send = (p) => { if (win && !win.isDestroyed()) win.webContents.send('pack-progress', p); };
  const deadline = Date.now() + 6 * 60 * 60 * 1000;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 1500));
    const st = await api('GET', `/ingest/${start.data.job_id}`);
    if (!st.ok) return st;
    if (st.data.status === 'done') return { ok: true, data: st.data.report };
    if (st.data.status === 'error') return { ok: false, status: 500, error: st.data.error };
    send({ ...(st.data.progress || {}), last: st.data.log_tail.slice(-1)[0] || '' });
  }
  return { ok: false, status: 0, error: 'Installing takes too long (more than 6 hours).' };
});

// ---- lifecycle ----------------------------------------------------------------------
// One app at a time: a second one would share the first one's search engine and lose it when the first closes.
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (win && !win.isDestroyed()) { if (win.isMinimized()) win.restore(); win.focus(); }
  });
}

app.whenReady().then(async () => {
  // previews may have been redone since the last start: never show an old copy from the cache
  try { await session.defaultSession.clearCache(); } catch { /* not critical */ }
  // previews (<img>) and the datasheet window load straight from the search engine: add the key there
  session.defaultSession.webRequest.onBeforeSendHeaders((details, done) => {
    const headers = details.requestHeaders;
    if (apiKey && isApiUrl(details.url)) headers.Authorization = `Bearer ${apiKey}`;
    done({ requestHeaders: headers });
  });
  createWindow();
  win.webContents.once('did-finish-load', () => setState(backendState.state, backendState.message));
  ensureBackend();
});

app.on('window-all-closed', () => app.quit());
app.on('before-quit', () => { if (server) server.kill(); });
