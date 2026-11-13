// End-to-end test of the Electron app: the real app window, the real main process and a real search engine.
//
//   cd app && npm run test:e2e
//       the app from the source, against a small test library (test/e2e_backend.py, needs backend/.venv)
//   cd app && node test/e2e.js --packaged <path to Partsfinder.exe or the Linux binary>
//       the installed app as built by electron-builder: it starts its own bundled search engine and model
//
// On Linux without a screen: xvfb-run -a npm run test:e2e
// A failing step leaves a screenshot in app/test-results/.
'use strict';

const { _electron: electron } = require('playwright-core');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const APP_DIR = path.resolve(__dirname, '..');
const ROOT = path.resolve(APP_DIR, '..');
const args = process.argv.slice(2);
const packagedExe = args[0] === '--packaged' ? path.resolve(args[1] || '') : null;
const PORT = 8000 + Math.floor(Math.random() * 900) + 50;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'partsfinder-e2e-'));
const results = path.join(APP_DIR, 'test-results');

let backend = null;
let app = null;
let page = null;
let passed = 0;

function python() {
  const venv = path.join(ROOT, 'backend', '.venv');
  const own = process.platform === 'win32' ? path.join(venv, 'Scripts', 'python.exe') : path.join(venv, 'bin', 'python');
  return process.env.PARTSFINDER_PYTHON || (fs.existsSync(own) ? own : 'python3');
}

async function waitFor(what, fn, timeoutMs) {
  const end = Date.now() + timeoutMs;
  let last;
  while (Date.now() < end) {
    try { last = await fn(); if (last) return last; } catch (err) { last = err; }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`timed out waiting for ${what}${last instanceof Error ? `: ${last.message}` : ''}`);
}

async function step(name, fn) {
  try {
    await fn();
    passed += 1;
    console.log(`  ok  ${name}`);
  } catch (err) {
    console.log(`  FAIL ${name}\n       ${err.message}`);
    if (page) {
      fs.mkdirSync(results, { recursive: true });
      await page.screenshot({ path: path.join(results, 'e2e-failure.png') }).catch(() => {});
    }
    throw err;
  }
}

async function startBackend() {
  backend = spawn(python(), [path.join(__dirname, 'e2e_backend.py'), path.join(tmp, 'engine'), String(PORT)], {
    cwd: ROOT, env: { ...process.env, PYTHONUTF8: '1' }, stdio: ['ignore', 'pipe', 'pipe'],
  });
  let log = '';
  backend.stdout.on('data', (d) => { log += d; });
  backend.stderr.on('data', (d) => { log += d; });
  await waitFor('the test search engine', async () => {
    if (backend.exitCode !== null) throw new Error(`it stopped: ${log.slice(-500)}`);
    const r = await fetch(`http://127.0.0.1:${PORT}/health`).catch(() => null);
    return r && r.ok;
  }, 60000);
}

async function health(api) {
  const r = await fetch(`${api}/health`);
  return r.json();
}

async function main() {
  console.log(packagedExe ? `Partsfinder e2e (installed app: ${packagedExe})` : 'Partsfinder e2e (app from the source)');
  const env = { ...process.env, PARTSFINDER_USER_DATA: path.join(tmp, 'user-data') };
  delete env.ANTHROPIC_API_KEY;
  // as root (containers, CI) Chromium only starts without its sandbox
  const extra = process.getuid && process.getuid() === 0 ? ['--no-sandbox'] : [];
  let api;
  if (packagedExe) {
    api = 'http://127.0.0.1:8731';
    app = await electron.launch({ executablePath: packagedExe, args: extra, env, timeout: 60000 });
  } else {
    await startBackend();
    api = `http://127.0.0.1:${PORT}`;
    Object.assign(env, { PARTSFINDER_API_URL: api, PARTSFINDER_NO_SPAWN: '1' });
    app = await electron.launch({ args: [...extra, APP_DIR], cwd: APP_DIR, env, timeout: 60000 });
  }
  page = await app.firstWindow();

  await step('the window opens with the Partsfinder brand', async () => {
    await page.waitForSelector('#brand', { timeout: 30000 });
    const title = await page.title();
    if (!/Partsfinder/.test(title)) throw new Error(`window title is "${title}"`);
  });

  await step('the app connects to the search engine', async () => {
    // installed: the bundled engine loads the model first (the first start can take a minute)
    // "limited" = connected, AI off (no key yet)
    await page.waitForSelector('#status[data-state="ready"], #status[data-state="limited"]', { timeout: packagedExe ? 240000 : 30000 });
    const h = await health(api);
    if (h.status !== 'ok') throw new Error(JSON.stringify(h));
    if (packagedExe && !process.env.PARTSFINDER_DB_PATH && h.embedder === 'hashing') throw new Error('the installed app uses the test embedder');
  });

  if (!packagedExe) {
    await step('a question finds the right part', async () => {
      await page.fill('#query', 'hex bolt M8');
      await page.press('#query', 'Enter');
      await page.waitForSelector('.card-name >> text=Hex bolt M8x30', { timeout: 30000 });
      const q = await page.inputValue('#query');
      if (q !== '') throw new Error(`the search bar was not emptied ("${q}")`);
    });
  } else {
    await step('a question on the empty library gets an answer', async () => {
      await page.fill('#query', 'hex bolt M8');
      await page.press('#query', 'Enter');
      await waitFor('an answer', () => page.evaluate(() => document.querySelectorAll('#feed .turn, #feed article, #feed .answer').length > 0
        || !document.querySelector('#empty') || document.querySelector('#empty').hidden), 60000);
      const state = await page.getAttribute('#status', 'data-state');
      if (!['ready', 'limited'].includes(state)) throw new Error(`status is ${state}`);
    });
  }

  await step('no sign-in needed on this pc', async () => {
    if (await page.isVisible('#signin-btn')) throw new Error('a Sign in button is shown without any accounts');
  });

  await step('settings: the AI is off without a key', async () => {
    await page.click('#settings-btn');
    await page.waitForSelector('#settings[open] .ai-state[data-on="false"]', { timeout: 10000 });
  });

  await step('settings: your own key switches the AI on', async () => {
    await page.fill('#ai-key', 'sk-ant-e2e-not-a-real-key');
    await page.click('#settings .ai-form button[type="submit"]');
    await page.waitForSelector('#settings[open] .ai-state[data-on="true"]', { timeout: 15000 });
    const h = await health(api);
    if (!h.ai_available) throw new Error('the search engine did not get the key');
    const keyFile = path.join(tmp, 'user-data', 'anthropic-key.bin');
    if (fs.existsSync(keyFile) && fs.readFileSync(keyFile).includes('sk-ant-e2e')) throw new Error('the key is stored as plain text');
  });

  await step('settings: removing the key switches the AI off', async () => {
    await page.click('#settings .ai-form .btn-danger');
    await page.waitForSelector('#settings[open] .ai-state[data-on="false"]', { timeout: 15000 });
    const h = await health(api);
    if (h.ai_available) throw new Error('the search engine still has the key');
    await page.click('#settings .panel-head button');
  });

  await step('about: version and licence', async () => {
    await page.click('#brand');
    await page.waitForSelector('#settings[open] #about', { timeout: 10000 });
    const text = await page.textContent('#about');
    const version = require(path.join(APP_DIR, 'package.json')).version;
    if (!text.includes(`Version ${version}`) || !text.includes('AGPL')) throw new Error(text);
  });

  await step('settings: the data packs section and the optional accounts', async () => {
    const text = await page.textContent('#settings[open] #packs');
    if (!text.includes('Data packs') || !text.includes('Install a data pack')) throw new Error(text);
    const acc = await page.textContent('#settings[open] #accounts');
    if (!acc.includes('no default password')) throw new Error(acc);
  });

  console.log(`\n${passed} steps passed.`);
}

main()
  .then(() => 0, () => 1)
  .then(async (code) => {
    if (app) await app.close().catch(() => {});
    if (backend) backend.kill();
    fs.rmSync(tmp, { recursive: true, force: true, maxRetries: 5, retryDelay: 500 });
    process.exit(code);
  });
