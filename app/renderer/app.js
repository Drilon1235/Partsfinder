// Partsfinder - the window. Talks to the search engine only via window.partsfinder (preload.js).
'use strict';

const $ = (sel) => document.querySelector(sel);
const feed = $('#feed');
const empty = $('#empty');
const form = $('#ask');
const input = $('#query');
const sendBtn = $('#send');
const companySel = $('#company');
const statusBox = $('#status');
const statusText = $('#status-text');

let apiUrl = 'http://127.0.0.1:8000';
let ready = false;
let busy = false;
let importToast = null;         // the running import's notification (at most one import at a time)
let importTarget = null;
let lastQuery = '';             // the last question (for the feedback)
const picked = new Map();       // parts you put side by side: id -> data
const shown = new Map();        // every part on screen: id -> data (for the detail panel)
let attached = null;            // image to search with: { dataUrl, base64, mediaType, name }
let who = { role: 'local', company_id: null, groups: [] };    // GET /me: who the key belongs to


const STATUS_LABEL = {
  found: 'Found',
  partial: 'Close match',
  none: 'Not in the library',
  plain: 'Results',
  error: 'Something went wrong',
};

// ---- small helpers ---------------------------------------------------------------------
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') node.className = v;
    else if (k === 'text') node.textContent = v;
    else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat()) if (c !== null && c !== undefined && c !== false) node.append(c);
  return node;
}

// parts that contain the words of the question, but whose data cannot confirm it
function notJudgedText() {
  return aiOn ? 'Not judged yet: check whether these parts fit.'
    : 'Not checked: their data cannot confirm what you asked. Check them yourself, or add your own AI key in Settings to have them judged.';
}

// in-app confirmation (instead of the browser's confirm box): resolves true for the red button
function askConfirm(title, text, okLabel) {
  const dlg = $('#confirm');
  $('#confirm-title').textContent = title;
  $('#confirm-text').textContent = text;
  $('#confirm-ok').textContent = okLabel;
  dlg.returnValue = '';
  dlg.showModal();
  $('#confirm-ok').focus();
  return new Promise((resolve) => dlg.addEventListener('close', () => resolve(dlg.returnValue === 'ok'), { once: true }));
}

function mm(n) {
  // 30 -> "30", 35.27 -> "35.3"; small values keep two decimals (thread pitch 1.25, not 1.3)
  if (n === null || n === undefined) return '-';
  if (Math.abs(n - Math.round(n)) < 0.005) return String(Math.round(n));
  return String(Number(n.toFixed(Math.abs(n) < 10 ? 2 : 1)));
}

function secondsText(sec) {
  // 0.043 -> "43 ms", 2.4 -> "2.4 s"
  if (sec === undefined || sec === null) return '';
  return sec < 1 ? `${Math.max(1, Math.round(sec * 1000))} ms` : `${sec.toFixed(1)} s`;
}

function modelName(id) {
  // claude-haiku-5-5 -> Claude Haiku 5.5
  const m = /^claude-([a-z]+)-(\d+)(?:-(\d+))?/.exec(id || '');
  if (!m) return id;
  return `Claude ${m[1][0].toUpperCase()}${m[1].slice(1)} ${m[2]}${m[3] ? '.' + m[3] : ''}`;
}

function companyId() {
  return companySel.value || null;
}


// ---- status of the search engine --------------------------------------------------------------
let auth = { accounts: false, setup_needed: false, keys_required: false };

// who is using the app: when that changes (signing out, another account, a session that ended), the
// conversation of the one before is cleared, so the next person never sees it
const identity = (w) => (w ? `${w.role}|${w.username || ''}|${w.company_id || ''}|${(w.groups || []).join(',')}` : '');
let shownFor = null;

function clearConversation() {
  feed.querySelectorAll('.view').forEach((t) => t.remove());
  empty.hidden = false;

  picked.clear();
  shown.clear();
  renderCompare();
  for (const dlg of [detail, $('#compare'), libraryDlg, manageDlg]) if (dlg && dlg.open) { libraryBack = null; dlg.close(); }
  attached = null;
  showAttachment();
  input.value = '';
  lastQuery = '';
  // filters belong to who was signed in (their library, their categories)
  filt = FILTER_NONE();
  facetCache = new Map();
  if (filtersDlg.open) filtersDlg.close();
  updateFilterButton();
}

function clearSignInFields() {
  for (const id of ['#signin-user', '#signin-pass', '#signin-pass2', '#signin-key']) $(id).value = '';
  $('#signin-remember').checked = false;
  $('#signin-error').hidden = true;
}

function newPerson(w) {
  const now = identity(w);
  if (shownFor !== null && now !== shownFor) { clearConversation(); clearSignInFields(); }
  shownFor = now;
}

function showBackend(s) {
  statusBox.dataset.state = s.state;
  ready = s.state === 'ready';
  if (s.state === 'signin') { newPerson(null); showSignIn('account', s.message); }
  if (ready) {
    Promise.all([window.partsfinder.who(), window.partsfinder.authInfo()]).then(([w, a]) => {
      who = w || { role: 'local', company_id: null, groups: [] };
      auth = a || auth;
      newPerson(who);
      applyRole();
      refreshHealth();
      loadCompanies().then(refreshScope);
      updateSend();
    });
  } else {
    statusText.textContent = s.state === 'signin' ? 'Not signed in' : s.message;
    if (s.state === 'signin') applyRole();
  }
  updateSend();
}

// ---- signing in: a company account or the administrator (or making the first administrator) -----------
const signinDlg = $('#signin');
let signinTab = 'company';
let signinMode = 'account';          // 'account', 'setup' (first administrator), 'none' (no accounts yet) or 'key'

const SIGNIN_TEXT = {
  company: 'Sign in with the username and password your administrator gave you. You then see your company’s own parts next to the general library, and you manage your company’s folders under “My library”.',
  admin: 'Sign in as the administrator to manage companies, people and the general library.',
  setup: 'There is no administrator yet. Make the first account here: it manages companies, people and the general library. This only works on the pc that runs the library.',
  none: 'There are no company accounts yet. The administrator makes them under “Companies and people” and gives you a username and password.',
  key: 'Sign in with the API key you were given.',
};

function showSignIn(tab, why) {
  signinTab = tab === 'admin' ? 'admin' : 'company';
  const noAccounts = auth.setup_needed && !auth.accounts;
  signinMode = tab === 'key' ? 'key' : (noAccounts ? (signinTab === 'admin' ? 'setup' : 'none') : 'account');
  const mode = signinMode;
  $('#tab-company').setAttribute('aria-selected', String(signinTab === 'company' && mode !== 'key'));
  $('#tab-admin').setAttribute('aria-selected', String(signinTab === 'admin' && mode !== 'key'));
  $('#signin-title').textContent = mode === 'setup' ? 'Create the administrator account' : 'Sign in';
  $('#signin-why').textContent = why && mode !== 'none' && mode !== 'setup' ? why
    : SIGNIN_TEXT[mode === 'account' ? signinTab : mode];
  $('#signin-account').hidden = mode === 'key' || mode === 'none';
  $('#signin-key-row').hidden = mode !== 'key';
  $('#signin-pass2-row').hidden = mode !== 'setup';
  $('#signin-pass').autocomplete = mode === 'setup' ? 'new-password' : 'current-password';
  $('#signin-user').placeholder = signinTab === 'admin' ? '' : 'e.g. anna.peeters';
  $('#signin-remember').closest('label').hidden = mode === 'none';
  // an API key only when this library uses them (another program's connection does; people normally do not)
  $('#signin-alt').hidden = !auth.keys_required || mode === 'setup' || mode === 'none';
  $('#signin-alt').textContent = mode === 'key' ? 'Sign in with a username instead' : 'Use an API key instead';
  $('#signin-go').hidden = mode === 'none';
  $('#signin-go').textContent = mode === 'setup' ? 'Create and sign in' : 'Sign in';
  $('#signin-note').textContent = mode === 'setup'
    ? 'Choose a password of at least 8 characters. Only a scrambled form of it is stored.'
    : mode === 'account' && signinTab === 'company' ? 'Forgot your password? The administrator gives you a new one.' : '';
  $('#signin-note').hidden = !$('#signin-note').textContent;
  $('#signin-close').hidden = auth.keys_required && !ready;        // a library that needs it: no way around
  $('#signin-error').hidden = true;
  // nothing of a previous person stays in the form; switching tabs keeps what you just typed
  const opening = !signinDlg.open;
  if (opening) clearSignInFields();
  else for (const id of ['#signin-pass', '#signin-pass2', '#signin-key']) $(id).value = '';
  if (opening) signinDlg.showModal();
  const first = mode === 'key' ? $('#signin-key') : mode === 'none' ? $('#tab-admin')
    : ($('#signin-user').value ? $('#signin-pass') : $('#signin-user'));
  first.focus();
}

signinDlg.addEventListener('cancel', (e) => { if (auth.keys_required && !ready) e.preventDefault(); });
$('#signin-close').addEventListener('click', () => signinDlg.close());
$('#signin-alt').addEventListener('click', () => showSignIn(signinMode === 'key' ? signinTab : 'key'));
$('#tab-company').addEventListener('click', () => showSignIn('company'));
$('#tab-admin').addEventListener('click', () => showSignIn('admin'));
$('#signin-btn').addEventListener('click', () => showSignIn(auth.setup_needed && !auth.accounts ? 'admin' : 'company'));

$('#signin-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const go = $('#signin-go');
  const err = $('#signin-error');
  const fail = (text, field) => { err.textContent = text; err.hidden = false; if (field) $(field).focus(); };
  err.hidden = true;
  const remember = $('#signin-remember').checked;
  let r;
  if (signinMode === 'none') return;
  if (signinMode === 'key') {
    if (!$('#signin-key').value.trim()) return fail('Enter the key you were given.', '#signin-key');
  } else {
    if (!$('#signin-user').value.trim()) return fail('Enter your username.', '#signin-user');
    if (!$('#signin-pass').value) return fail('Enter your password.', '#signin-pass');
    if (signinMode === 'setup') {
      if ($('#signin-pass').value.length < 8) return fail('Choose a password of at least 8 characters.', '#signin-pass');
      if ($('#signin-pass').value !== $('#signin-pass2').value) return fail('The two passwords are not the same.', '#signin-pass2');
    }
  }
  const label = go.textContent;
  go.disabled = true;
  go.textContent = 'Checking...';
  if (signinMode === 'key') r = await window.partsfinder.signIn($('#signin-key').value, remember);
  else if (signinMode === 'setup') r = await window.partsfinder.setup($('#signin-user').value, $('#signin-pass').value, remember);
  else r = await window.partsfinder.login($('#signin-user').value, $('#signin-pass').value, remember);
  go.disabled = false;
  go.textContent = label;
  if (!r.ok) {
    fail(r.error, signinMode === 'key' ? '#signin-key' : '#signin-pass');
    if (signinMode !== 'key') $('#signin-pass').select();
    return;
  }
  clearSignInFields();
  signinDlg.close();
  toast(`Signed in as ${r.data.username || whoText(r.data)}${r.data.role === 'admin' ? ' (administrator)' : ''}.`);
  if (!r.data.remembered && remember) toast('Signed in. It could not be stored safely, so you sign in again next time.', false);
});

function whoText(w) {
  if (w.username) return w.username;
  if (w.role === 'admin') return 'Admin';
  const groups = w.groups.length ? ` · ${w.groups.join(', ')}` : '';
  return `${w.company_id}${groups}`;
}

function roleText(w) {
  if (w.role === 'admin') return 'Admin: every company and every restricted group';
  const groups = w.groups.length ? `, restricted groups ${w.groups.join(', ')}` : '';
  return `${w.company_id}${groups}`;
}

// what this person sees: the library picker, importing, the sign-in button and the account menu
function applyRole() {
  const role = who.role;
  const signedIn = ready && (role === 'admin' || role === 'company');
  // without accounts this pc needs no sign-in at all: accounts are made under Settings, for sharing the library
  const canSignIn = auth.accounts || auth.keys_required;
  $('#signin-btn').hidden = signedIn || !canSignIn;
  const btn = $('#account');
  btn.hidden = !signedIn;
  if (signedIn) {
    btn.dataset.role = role;
    $('#account-text').textContent = whoText(who);
    $('#account-avatar').textContent = whoText(who).replace(/[^A-Za-z0-9]/g, '').slice(0, 2);
    btn.title = `Signed in: ${roleText(who)}`;
  }
  closeMenu();
}

// ---- the account menu ------------------------------------------------------------------------------
const menu = $('#account-menu');

function closeMenu() {
  menu.hidden = true;
  $('#account').setAttribute('aria-expanded', 'false');
}

function openMenu() {
  const items = [el('div', { class: 'menu-head' },
    el('strong', { text: whoText(who) }), el('span', { text: roleText(who) }))];
  if (who.role === 'company') items.push(menuItem('My library', () => openLibrary(who.company_id, null)));
  if (who.role === 'admin') items.push(menuItem('Companies and people', openManage));
  items.push(menuItem('Sign out', async () => {
    await window.partsfinder.signOut();
    clearConversation();
    clearSignInFields();
    toast('Signed out.');
  }));
  menu.replaceChildren(...items);
  menu.hidden = false;
  $('#account').setAttribute('aria-expanded', 'true');
  menu.querySelector('button')?.focus();
}

function menuItem(text, action) {
  return el('button', { class: 'menu-item', type: 'button', role: 'menuitem', text,
    onclick: () => { closeMenu(); action(); } });
}

$('#account').addEventListener('click', (e) => {
  e.stopPropagation();
  if (busy) return;
  if (menu.hidden) openMenu(); else closeMenu();
});
document.addEventListener('click', (e) => { if (!menu.hidden && !menu.contains(e.target)) closeMenu(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !menu.hidden) { closeMenu(); $('#account').focus(); } });

// ---- a company's own library: upload folders from this pc, update or remove them -------------------
const libraryDlg = $('#library');
libraryDlg.addEventListener('close', () => {
  const back = libraryBack;
  libraryBack = null;
  if (back) back();
});
let libraryCompany = null;
let uploadLine = null;

const COVERAGE_LABEL = { description: 'description', material: 'material', dimensions: 'dimensions', properties: 'properties',
  preview_image: 'preview' };

let libraryBack = null;          // where closing the library returns to (the admin panel it was opened from)

async function openLibrary(companyId, back) {
  if (back !== undefined) libraryBack = back;     // a refresh (no second argument) keeps it
  libraryCompany = companyId;
  if (!libraryDlg.open) libraryDlg.showModal();
  libraryDlg.replaceChildren(panelHead('library-title', `${companyId}`, 'Your own library', () => libraryDlg.close()),
    el('p', { class: 'thinking panel-body', text: 'Loading' }));
  const r = await window.partsfinder.library(who.role === 'admin' ? companyId : null);
  if (!r.ok) {
    libraryDlg.replaceChildren(panelHead('library-title', companyId, 'Your own library', () => libraryDlg.close()),
      el('p', { class: 'panel-body signin-error', text: r.error }));
    return;
  }
  renderLibrary(r.data);
}

const groupList = (a) => (a || '').split(',').filter(Boolean);
const quoted = (gs) => gs.map((g) => `“${g}”`).join(' or ');

function accessText(a, company) {
  if (a === 'company') return `Everyone at ${company}`;
  if (a === 'invalid') return 'Not readable: this folder is skipped';
  return `Only people with ${quoted(groupList(a))}`;
}

// which groups this person can choose in "who sees it": the administrator every group of the company (and new
// ones), a company account only the groups it has itself
const choosable = (d) => (d.my_groups == null ? (d.groups || []) : d.my_groups);

// can this person change who sees the folder? The administrator always; a company account when it has a group
// and the folder is open to everyone at the company now, or only to groups it has itself
function mayEdit(d, access) {
  if (d.my_groups == null) return true;
  if (!d.my_groups.length || access === 'invalid') return false;
  return access === 'company' || groupList(access).every((g) => d.my_groups.includes(g));
}

// the choice itself: [same as above,] everyone at the company, or only one or more restricted groups
function accessPicker(d, { name, current, company, inherited }) {
  const mode = current === 'inherit' || current === 'company' ? current : 'groups';
  const radio = (value, text) => el('label', { class: 'signin-check' },
    el('input', { type: 'radio', name, value, checked: mode === value }), el('span', { text }));
  const chosen = new Set(groupList(mode === 'groups' ? current : ''));
  const all = [...new Set([...choosable(d), ...chosen])].sort();
  const boxes = el('div', { class: 'group-checks' }, all.map((g) => el('label', { class: 'signin-check' },
    el('input', { type: 'checkbox', value: g, checked: chosen.has(g) }), el('span', { text: g }))));
  const canAdd = d.my_groups == null;
  const newGroup = canAdd ? el('input', { type: 'text', class: 'group-inline', placeholder: 'new group, e.g. nuclear', 'aria-label': 'New restricted group' }) : null;
  const node = el('div', { class: 'access-choice' },
    inherited !== undefined ? radio('inherit', `Same as the folder above (${inherited === 'company' ? 'everyone' : `only ${quoted(groupList(inherited))}`})`) : null,
    radio('company', `Everyone at ${company}`),
    radio('groups', canAdd ? 'Only people with one of these restricted groups:' : 'Only people with one of your restricted groups:'),
    el('div', { class: 'access-groups' }, all.length ? boxes : null, newGroup));
  // ticking a group or typing one means "only these groups"
  const pickGroups = () => { node.querySelector('input[value="groups"]').checked = true; };
  boxes.addEventListener('change', pickGroups);
  if (newGroup) newGroup.addEventListener('input', pickGroups);
  // the chosen value ('inherit', 'company' or "aero,nuclear"), or { error, field }
  const read = () => {
    const pick = node.querySelector('input[type=radio]:checked')?.value || 'company';
    if (pick !== 'groups') return { value: pick };
    const gs = [...boxes.querySelectorAll('input:checked')].map((x) => x.value);
    const typed = newGroup ? newGroup.value.trim().toLowerCase() : '';
    if (typed && !/^[a-z0-9][a-z0-9_-]{0,39}$/.test(typed)) {
      return { error: 'A group is one word: letters, digits, - or _ (for example nuclear).', field: newGroup };
    }
    if (typed) gs.push(typed);
    if (!gs.length) return { error: canAdd ? 'Tick a group, or type a new one.' : 'Tick a group.', field: boxes.querySelector('input') };
    return { value: [...new Set(gs)].join(',') };
  };
  return { node, read };
}

// one folder inside an uploaded folder: who sees it. A label, or a button that opens the choice for whoever
// may change it.
function subfolderRow(d, f, t) {
  const company = d.name || d.company_id;
  const name = t.path ? t.path.split('/').pop() : 'The whole folder';
  const restricted = t.access !== 'company';
  const tag = el('span', { class: 'access-tag', 'data-restricted': String(restricted), text: accessText(t.access, company) });
  const li = el('li', { class: 'subfolder' },
    el('span', { class: 'sub-name', text: name, title: t.path || f.name }),
    el('span', { class: 'sub-count', text: `${t.parts} part${t.parts === 1 ? '' : 's'}` }),
    mayEdit(d, t.access)
      ? el('button', { class: 'access-btn', type: 'button', 'data-path': t.path, 'data-restricted': String(restricted),
          title: 'Choose who sees this folder', onclick: () => editAccess(li, d, f, t) },
          el('span', { text: accessText(t.access, company) + (t.own ? '' : t.path ? ' (as above)' : '') }),
          el('span', { class: 'chev-txt', 'aria-hidden': 'true', text: '▾' }))
      : tag);
  li.style.setProperty('--depth', String(t.depth));          // via the CSSOM: the page allows no inline styles
  return li;
}

function editAccess(li, d, f, t) {
  libraryDlg.querySelectorAll('.access-editor').forEach((x) => x.remove());
  const company = d.name || d.company_id;
  const current = t.own && t.own !== 'invalid' ? t.own : (t.path ? 'inherit' : 'company');
  const picker = accessPicker(d, { name: `acc-${t.path}`, current, company, inherited: t.path ? t.inherited : undefined });
  const note = el('p', { class: 'form-msg', hidden: true });
  const editor = el('li', { class: 'access-editor' },
    el('p', { class: 'access-q', text: `Who sees “${t.path || f.name}”?` }),
    picker.node,
    el('p', { class: 'muted-note', text: d.my_groups == null
      ? 'Then tick the same group for the right people under Companies and people.'
      : 'You can choose the groups you have yourself. For another group, ask the administrator.' }),
    note,
    el('div', { class: 'access-actions' },
      el('button', { class: 'btn btn-light btn-small', type: 'button', text: 'Save', onclick: () => {
        const r = picker.read();
        if (r.error) { note.textContent = r.error; note.hidden = false; r.field?.focus(); return; }
        applyAccess(f.name, t.path, r.value);
      } }),
      el('button', { class: 'btn btn-ghost btn-small', type: 'button', text: 'Cancel', onclick: () => editor.remove() })));
  li.after(editor);
  (editor.querySelector('input:checked') || editor.querySelector('input')).focus();
}

async function applyAccess(name, folderPath, access) {
  libraryDlg.querySelectorAll('select, .btn').forEach((x) => { x.disabled = true; });
  if (uploadLine) { uploadLine.hidden = false; uploadLine.dataset.state = 'busy'; uploadLine.textContent = 'Applying who may see this folder...'; }
  const r = await window.partsfinder.folderAccess(libraryCompany, name, folderPath, access);
  await openLibrary(libraryCompany);
  if (!r.ok) { uploadLine.hidden = false; uploadLine.dataset.state = 'error'; uploadLine.textContent = r.error; return; }
  const where = folderPath ? `"${folderPath}"` : `"${name}"`;
  refreshScope();
  toast(access === 'inherit' ? `${where} now follows the folder above it.`
    : access === 'company' ? `${where}: everyone at the company sees it.` : `${where}: only people with ${quoted(groupList(access))} see it.`);
}

function folderIcon() {
  const svg = svgEl('svg', { class: 'folder-icon', viewBox: '0 0 24 24', 'aria-hidden': 'true' });
  svg.append(svgEl('path', { d: 'M3 7.5A1.5 1.5 0 0 1 4.5 6h4.2l1.8 2h9a1.5 1.5 0 0 1 1.5 1.5v8A1.5 1.5 0 0 1 19.5 19h-15A1.5 1.5 0 0 1 3 17.5z' }));
  return svg;
}

function panelHead(id, title, sub, onClose) {
  return el('div', { class: 'panel-head' },
    el('div', {}, el('p', { class: 'panel-kicker', text: sub }), el('h2', { id, text: title })),
    el('button', { class: 'detail-close', type: 'button', 'aria-label': 'Close', text: '×', onclick: onClose }));
}

function stat(value, label) {
  return el('div', { class: 'stat' }, el('span', { class: 'stat-value', text: String(value) }), el('span', { class: 'stat-label', text: label }));
}

function renderLibrary(d) {
  const asAdmin = who.role === 'admin';
  const importBtn = el('button', { class: 'btn btn-primary', type: 'button', text: 'Upload a folder',
    onclick: () => (choosable(d).length ? chooseUpload(d) : uploadFolder(null, null)) });
  uploadLine = el('p', { class: 'upload-line', role: 'status', hidden: true });
  const rows = d.folders.map((f) => el('li', { class: 'folder-block' },
    el('div', { class: 'folder' },
      folderIcon(),
      el('div', { class: 'folder-main' },
        el('span', { class: 'folder-name', text: f.name }),
        el('span', { class: 'folder-meta', text: `${f.parts} part${f.parts === 1 ? '' : 's'} \u00b7 updated ${f.updated_at.replace('T', ' ')}` })),
      el('div', { class: 'folder-actions' },
        el('button', { class: 'btn btn-small', type: 'button', text: 'Update', title: 'Send this folder again: new and changed files are imported, removed files leave the library',
          onclick: () => uploadFolder(f.name, null) }),
        el('button', { class: 'btn btn-small btn-danger', type: 'button', text: 'Remove',
          onclick: () => removeFolder(f.name, f.parts) }))),
    (f.tree || []).length ? el('ul', { class: 'subfolders' }, f.tree.map((t) => subfolderRow(d, f, t))) : null));
  const coverage = Object.entries(COVERAGE_LABEL).filter(([k]) => k in d.coverage)
    .map(([k, label]) => el('span', { class: 'cov', 'data-low': String(d.coverage[k] < 50) }, `${label} `, el('b', { text: `${d.coverage[k]}%` })));
  libraryDlg.replaceChildren(
    panelHead('library-title', d.name || d.company_id, asAdmin ? 'Company library' : 'Your own library', () => libraryDlg.close()),
    el('div', { class: 'panel-body' },
      el('div', { class: 'stats' }, stat(d.parts, 'parts'), stat(d.restricted_parts, 'restricted'), stat(d.folders.length, 'folders')),
      d.confidential ? el('p', { class: 'panel-note', text: 'Confidential: no part of this library is ever sent to an outside AI.' }) : null,
      el('div', { class: 'panel-section-head' }, el('h3', { text: 'Folders' }), importBtn),
      el('p', { class: 'panel-note', text: asAdmin
        ? 'Per folder you choose who sees its parts: everyone at the company, or only the people you give a restricted group (under Companies and people). The choice stays when the company sends the folder again.'
        : d.my_groups && d.my_groups.length
          ? `Everyone at your company sees these folders, unless a folder is for a restricted group. You can keep a folder for people with your group${d.my_groups.length === 1 ? '' : 's'} (${quoted(d.my_groups)}): choose it when you upload, or click who sees a folder.`
          : 'Everyone at your company sees these folders, except folders the administrator restricted to a few people.' }),
      uploadChoice = el('div', { class: 'upload-choice', hidden: true }),
      uploadLine,
      rows.length ? el('ul', { class: 'folders' }, rows)
        : el('p', { class: 'panel-empty', text: 'No folders yet. Upload a folder with CAD files (STEP, STL, SolidWorks, ...) from this pc. Only you and your company see them.' }),
      d.other_parts > 0 ? el('p', { class: 'panel-note', text: `${d.other_parts} more part${d.other_parts === 1 ? ' was' : 's were'} imported by the administrator.` }) : null,
      coverage.length && d.parts ? el('div', { class: 'coverage' }, el('h3', { text: 'How complete is the data' }),
        el('p', { class: 'panel-note', text: 'Partsfinder can only check a requirement (size, material, thread, ...) when the part\u2019s data has it. Low numbers mean many parts are found by their name only.' }),
        el('div', { class: 'cov-row' }, coverage)) : null,
      d.parts ? duplicatesBlock(asAdmin ? d.company_id : null) : null,
      el('details', { class: 'rules' },
        el('summary', { text: 'Keep files out, or for a few people only' }),
        el('p', { text: 'Only what is in the folder you upload reaches the library. To keep files out, leave them out of that folder (or move them to a folder you do not upload).' }),
        el('p', { text: asAdmin || (d.my_groups && d.my_groups.length)
          ? 'To let only a few people see a folder, click \u201cEveryone at \u2026\u201d next to it and choose a restricted group.'
          : 'To let only a few people see a folder, ask the administrator to restrict it.' }))));
}

// Possible duplicates in the own library: parts of the same kind with (nearly) the same outer size and volume.
// A hint to check before drawing or uploading yet another copy, not proof.
function duplicatesBlock(company) {
  const box = el('div', { class: 'duplicates', hidden: true });
  window.partsfinder.duplicates(company, 50).then((r) => {
    if (!r.ok || !r.data.total || !libraryDlg.open) return;
    box.hidden = false;
    const groups = r.data.groups;
    box.replaceChildren(
      el('div', { class: 'panel-section-head' }, el('h3', { text: `Possible duplicates (${r.data.total})` })),
      el('p', { class: 'panel-note', text: 'Parts of the same kind with the same outer size and volume. Check them: keeping one model saves searching and drawing twice. Equal sizes do not always mean the same part.' }),
      el('ul', { class: 'dup-list' }, groups.map((g) => el('li', { class: 'dup-group' },
        el('span', { class: 'dup-size', text: `${sizeOf(g.bbox_mm) || ''}` }),
        el('span', { class: 'dup-names' }, g.parts.map((p, i) => [i ? el('span', { class: 'dup-eq', text: ' = ' }) : null,
          el('span', { class: 'dup-name', text: p.name })]).flat().filter(Boolean)),
        el('span', { class: 'dup-count', text: `${g.size} parts` })))));
  });
  return box;
}

// a new folder for a restricted group: choose who sees it before choosing the folder
let uploadChoice = null;
function chooseUpload(d) {
  const company = d.name || d.company_id;
  const picker = accessPicker(d, { name: 'acc-upload', current: 'company', company });
  const note = el('p', { class: 'form-msg', hidden: true });
  uploadChoice.replaceChildren(
    el('p', { class: 'access-q', text: 'Who sees the folder you upload?' }),
    picker.node, note,
    el('div', { class: 'access-actions' },
      el('button', { class: 'btn btn-light btn-small', type: 'button', text: 'Choose the folder...', onclick: () => {
        const r = picker.read();
        if (r.error) { note.textContent = r.error; note.hidden = false; r.field?.focus(); return; }
        uploadChoice.hidden = true;
        uploadFolder(null, r.value === 'company' ? null : r.value);
      } }),
      el('button', { class: 'btn btn-ghost btn-small', type: 'button', text: 'Cancel', onclick: () => { uploadChoice.hidden = true; } })));
  uploadChoice.hidden = false;
  (uploadChoice.querySelector('input:checked') || uploadChoice.querySelector('input')).focus();
}

async function uploadFolder(existing, access) {
  if (busy) return;
  busy = true;
  updateSend();
  libraryDlg.querySelectorAll('.btn').forEach((b) => { b.disabled = true; });
  if (uploadLine) { uploadLine.hidden = false; uploadLine.dataset.state = 'busy'; uploadLine.textContent = existing ? `Choose the folder "${existing}"...` : 'Choose a folder...'; }
  const r = await window.partsfinder.uploadFolder(who.role === 'admin' ? libraryCompany : null, existing || null, access || null);
  busy = false;
  updateSend();
  if (r.canceled) { await openLibrary(libraryCompany); return; }
  await openLibrary(libraryCompany);
  if (!r.ok) {
    uploadLine.hidden = false;
    uploadLine.dataset.state = 'error';
    uploadLine.textContent = r.error;
    return;
  }
  const rep = r.data.report;
  const parts = [`${rep.added.length} new`, `${rep.updated.length} updated`, `${rep.skipped.length} unchanged`];
  if (rep.removed.length) parts.push(`${rep.removed.length} removed`);
  if (rep.failed.length) parts.push(`${rep.failed.length} failed`);
  uploadLine.hidden = false;
  uploadLine.dataset.state = rep.failed.length ? 'warn' : 'ok';
  refreshScope();
  uploadLine.textContent = `"${r.data.name}": ${parts.join(', ')}.` + (r.data.excluded ? ` ${r.data.excluded} file${r.data.excluded === 1 ? ' was' : 's were'} left out on purpose and never read.` : '')
    + (r.data.skipped.length ? ` Skipped: ${r.data.skipped.map((x) => x[0] === '.' ? 'the folder' : `\u201c${x[0]}\u201d`).join(', ')} (a setting file in it could not be read).` : '');
  refreshHealth();
}

window.partsfinder.onUploadProgress((p) => {
  if (!uploadLine) return;
  uploadLine.hidden = false;
  uploadLine.dataset.state = 'busy';
  uploadLine.textContent = p.text;
});

async function removeFolder(name, n) {
  if (busy) return;
  if (!await askConfirm(`Remove "${name}"?`, `Its ${n} part${n === 1 ? '' : 's'} and everything stored about them are deleted from the library. The files on your pc stay.`, 'Remove')) return;
  const r = await window.partsfinder.removeFolder(who.role === 'admin' ? libraryCompany : null, name);
  await openLibrary(libraryCompany);
  if (!r.ok) { uploadLine.hidden = false; uploadLine.dataset.state = 'error'; uploadLine.textContent = r.error; return; }
  toast(`Removed "${name}": ${r.data.total} part${r.data.total === 1 ? '' : 's'}.`);
  refreshHealth();
}

// ---- the admin: companies and people ------------------------------------------------------------------
const manageDlg = $('#manage');

async function openManage() {
  if (!manageDlg.open) {
    manageDlg.replaceChildren(panelHead('manage-title', 'Companies and people', 'Administrator', () => manageDlg.close()),
      el('p', { class: 'thinking panel-body', text: 'Loading' }));
    manageDlg.showModal();
  }
  const [u, c] = await Promise.all([window.partsfinder.users(), window.partsfinder.companies()]);
  if (!u.ok || !c.ok) {
    manageDlg.replaceChildren(panelHead('manage-title', 'Companies and people', 'Administrator', () => manageDlg.close()),
      el('p', { class: 'panel-body signin-error', text: (u.ok ? c : u).error }));
    return;
  }
  renderManage(u.data, c.data);
}

function renderManage(users, companies) {
  // every message right under what it is about (a message at the top of a long panel looks like nothing happened)
  const msg = () => el('p', { class: 'form-msg', role: 'alert', hidden: true });
  const coErr = msg();
  const personErr = msg();
  const tableErr = msg();
  const peopleErr = msg();
  const shower = (box) => (text, ok = false) => {
    box.textContent = text;
    box.hidden = !text;
    box.dataset.ok = String(ok);
    if (text) box.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  };
  const sayCo = shower(coErr);
  const sayPerson = shower(personErr);
  const say = shower(tableErr);
  const sayPeople = shower(peopleErr);
  const label = (c) => (c.name && c.name !== c.id ? `${c.name} (${c.id})` : c.id);

  // ---- companies: each has its own library, only its own people and the administrator see it
  const coName = el('input', { type: 'text', placeholder: 'e.g. Janssen Engineering', autocomplete: 'off',
    'aria-label': 'New company name', maxlength: '80' });
  const addCo = el('form', { class: 'inline-form', novalidate: true }, coName,
    el('button', { class: 'btn btn-primary', type: 'submit', text: 'Add company' }));
  addCo.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!coName.value.trim()) { sayCo('Type the company\u2019s name first.'); coName.focus(); return; }
    const r = await window.partsfinder.companyCreate({ name: coName.value.trim() });
    if (!r.ok) { sayCo(r.error); coName.focus(); return; }
    toast(`Added ${r.data.name}. Now add its people below, or upload its first folder with “Library”.`);
    loadCompanies();
    openManage();
  });
  const companyRows = companies.map((c) => el('tr', {},
    el('td', {}, el('strong', { text: c.name || c.id }), c.name && c.name !== c.id ? el('span', { class: 'sub-id', text: c.id }) : null),
    el('td', { class: 'num', text: String(c.people ?? 0) }),
    el('td', { class: 'num', text: String(c.parts) }),
    el('td', { class: 'num', text: String(c.restricted_parts) }),
    el('td', {}, el('label', { class: 'signin-check', title: 'When ticked, nothing of this company is ever sent to Claude: its searches are answered by the library’s own checks only, and photo search is off for it.' },
      el('input', { type: 'checkbox', checked: c.confidential, 'aria-label': `Keep ${c.id} away from AI`, onchange: async (e) => {
        const r = await window.partsfinder.companyConfidential(c.id, e.target.checked);
        if (!r.ok) { say(r.error); e.target.checked = !e.target.checked; return; }
        toast(e.target.checked ? `${label(c)}: nothing is sent to AI any more.` : `${label(c)}: AI may help judge its searches again.`);
      } }), el('span', { text: 'no AI' }))),
    el('td', { class: 'row-actions' },
      el('button', { class: 'btn btn-small', type: 'button', text: 'Library',
        onclick: () => { manageDlg.close(); openLibrary(c.id, openManage); } }),
      el('button', { class: 'btn btn-small btn-danger', type: 'button', text: 'Delete', onclick: async () => {
        const what = `${c.parts} part${c.parts === 1 ? '' : 's'} and ${c.people ?? 0} account${c.people === 1 ? '' : 's'}`;
        if (!await askConfirm(`Delete ${label(c)}?`, `Its ${what}, its uploaded folders and its settings are removed for good. This cannot be undone.`, 'Delete')) return;
        const r = await window.partsfinder.companyDelete(c.id);
        if (!r.ok) { say(r.error); return; }
        toast(`Deleted ${label(c)}: ${r.data.removed_parts} parts, ${r.data.removed_accounts} accounts.`);
        if (companySel.value === c.id) companySel.value = '';
        loadCompanies();
        openManage();
      } }))));

  // ---- people: who may sign in, and for which company
  const f = {
    user: el('input', { type: 'text', placeholder: 'e.g. anna.peeters', autocomplete: 'off', spellcheck: 'false', 'aria-label': 'Username' }),
    pass: el('input', { type: 'password', placeholder: 'at least 8 characters', autocomplete: 'new-password', 'aria-label': 'Password' }),
    role: el('select', { 'aria-label': 'Role' }, el('option', { value: 'company', text: 'Company' }), el('option', { value: 'admin', text: 'Administrator' })),
    company: el('select', { 'aria-label': 'Company' },
      el('option', { value: '', text: companies.length ? 'Choose a company' : 'Add a company first' }),
      companies.map((c) => el('option', { value: c.id, text: label(c) }))),
    groups: el('div', { class: 'group-checks', role: 'group', 'aria-label': 'Restricted folders' }),
  };
  const groupsOf = (id) => (companies.find((c) => c.id === id) || {}).groups || [];
  const showGroups = () => {
    const co = f.role.value === 'company';
    f.company.disabled = !co;
    const gs = co ? groupsOf(f.company.value) : [];
    f.groups.replaceChildren(...(gs.length ? gs.map((g) => el('label', { class: 'signin-check' },
      el('input', { type: 'checkbox', value: g }), el('span', { text: g })))
      : [el('span', { class: 'muted-note', text: !co ? 'An administrator sees everything.' : !f.company.value ? 'Choose the company first.'
        : 'None yet. Restrict a folder in this company\u2019s Library first; most people need none.' })]));
  };
  f.role.addEventListener('change', showGroups);
  f.company.addEventListener('change', showGroups);
  showGroups();
  const add = el('form', { class: 'add-user', novalidate: true },
    field('Username', f.user), field('Password', f.pass), field('Role', f.role), field('Company', f.company),
    field('Also sees restricted folders', f.groups),
    el('button', { class: 'btn btn-primary', type: 'submit', text: 'Add person' }));
  add.addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = { username: f.user.value.trim(), password: f.pass.value, role: f.role.value,
      company_id: f.role.value === 'company' ? f.company.value : null,
      groups: f.role.value === 'company' ? [...f.groups.querySelectorAll('input:checked')].map((x) => x.value) : [] };
    if (!body.username) { sayPerson('Type a username, for example anna.peeters.'); f.user.focus(); return; }
    if (body.password.length < 8) { sayPerson('Type a password of at least 8 characters.'); f.pass.focus(); return; }
    if (body.role === 'company' && !body.company_id) {
      sayPerson(companies.length ? 'Choose the company this person works for.' : 'Add the company first (above).');
      (companies.length ? f.company : coName).focus();
      return;
    }
    const r = await window.partsfinder.userCreate(body);
    if (!r.ok) { sayPerson(r.error); f.user.focus(); return; }
    toast(`Added ${r.data.username}. Give them their username and password; they sign in on the Company tab.`);
    openManage();
  });

  const pill = (text, tone) => el('span', { class: 'pill', 'data-tone': tone, text });
  const userRows = users.map((u) => el('tr', { class: u.disabled ? 'is-off' : '' },
    el('td', {}, el('strong', { text: u.username }), u.username === who.username ? el('span', { class: 'you' }, pill('you', 'accent')) : null,
      el('span', { class: 'sub-id', text: u.last_login ? `signed in ${localTime(u.last_login)}` : 'never signed in' })),
    el('td', {}, u.role === 'admin' ? pill('Administrator', 'warn') : pill('Company', '')),
    el('td', { class: 'nowrap', text: u.role === 'admin' ? 'All companies' : ((companies.find((c) => c.id === u.company_id) || {}).name || u.company_id) }),
    el('td', {}, u.role === 'company' ? el('button', { class: 'groups-edit', type: 'button',
      title: 'Change which restricted folders this person sees',
      onclick: (e) => editGroups(e.currentTarget.closest('td'), u, groupsOf(u.company_id), sayPeople) },
    u.groups.length ? u.groups.map((g) => pill(g, 'warn')) : pill('none', 'muted')) : pill('all', 'muted')),
    el('td', {}, u.disabled ? pill('Disabled', 'muted') : pill('Active', 'ok')),
    el('td', { class: 'row-actions' },
      el('button', { class: 'btn btn-small', type: 'button', text: 'New password',
        onclick: (e) => newPassword(e.target.closest('td'), u.username, sayPeople) }),
      el('button', { class: 'btn btn-small', type: 'button', text: u.disabled ? 'Enable' : 'Disable', onclick: async () => {
        const r = await window.partsfinder.userUpdate(u.username, { disabled: !u.disabled });
        if (!r.ok) sayPeople(r.error); else openManage();
      } }),
      el('button', { class: 'btn btn-small btn-danger', type: 'button', text: 'Remove', onclick: async () => {
        if (!await askConfirm(`Remove the account ${u.username}?`, 'The company\u2019s parts stay.', 'Remove')) return;
        const r = await window.partsfinder.userDelete(u.username);
        if (!r.ok) sayPeople(r.error); else openManage();
      } }))));

  manageDlg.replaceChildren(
    panelHead('manage-title', 'Companies and people', 'Administrator', () => manageDlg.close()),
    el('div', { class: 'panel-body' },
      el('div', { class: 'panel-section-head' }, el('h3', { text: 'Companies' }), addCo),
      coErr,
      el('p', { class: 'panel-note', text: 'Each company has its own library that only its own people and you can see. "Library" uploads, updates and removes its folders.' }),
      companies.length ? el('div', { class: 'table-wrap' }, el('table', { class: 'grid', id: 'companies-table' },
        el('thead', {}, el('tr', {}, [['Company'], ['People', 'num'], ['Parts', 'num'], ['Restricted', 'num'], ['AI'], ['']].map(([t, c]) => el('th', { scope: 'col', class: c || null, text: t })))),
        el('tbody', {}, companyRows)))
        : el('p', { class: 'panel-empty', text: 'No companies yet. Add one with its name above.' }),
      tableErr,
      el('details', { class: 'rules' },
        el('summary', { text: 'What do “restricted” and “no AI” mean?' }),
        el('p', { text: 'Restricted: in a company\u2019s Library you choose per folder who sees it: everyone at the company, or only a restricted group (for example \u201cnuclear\u201d). Then tick that group for the people who may see it, here under People. Their colleagues do not see those parts at all.' }),
        el('p', { text: 'No AI: some searches send part names and descriptions to Claude (Anthropic’s AI) to judge which parts fit. With “no AI” ticked, nothing of that company ever leaves this pc: its searches are answered by the library’s own checks, and photo search is off for it. For customers with secret designs.' })),
      el('div', { class: 'panel-section-head' }, el('h3', { text: 'People' })),
      el('p', { class: 'panel-note', text: 'One account per person. A company account sees the general library plus its own company; an administrator manages everything. Give people their username and password yourself.' }),
      add, personErr,
      el('div', { class: 'table-wrap' }, el('table', { class: 'grid', id: 'people-table' },
        el('thead', {}, el('tr', {}, ['Username', 'Role', 'Company', 'Restricted', 'Status', ''].map((t) => el('th', { scope: 'col', text: t })))),
        el('tbody', {}, userRows))),
      peopleErr,
      el('div', { class: 'panel-section-head' }, el('h3', { text: 'General library' }),
        el('button', { class: 'btn btn-primary', type: 'button', text: 'Import a folder', onclick: () => {
          manageDlg.close();
          importFolder(null);
        } })),
      el('p', { class: 'panel-note', text: 'Standard parts that everyone sees, also without signing in (bolts, bearings, profiles, ...). The import runs in the background; its progress shows in a notification at the bottom right.' })));
  (companies.length ? f.user : coName).focus();
}

// which restricted folders a person sees: ticked in the row itself
function editGroups(cell, u, groups, say) {
  const keep = [...cell.childNodes];
  const all = [...new Set([...groups, ...u.groups])].sort();
  if (!all.length) { say(`This company has no restricted folders yet: restrict a folder in its Library first.`); return; }
  const boxes = all.map((g) => el('label', { class: 'signin-check' },
    el('input', { type: 'checkbox', value: g, checked: u.groups.includes(g) }), el('span', { text: g })));
  const save = async () => {
    const r = await window.partsfinder.userUpdate(u.username, { groups: boxes.map((b) => b.querySelector('input')).filter((x) => x.checked).map((x) => x.value) });
    if (!r.ok) { say(r.error); return; }
    toast(`${u.username} now sees: ${r.data.groups.length ? r.data.groups.join(', ') : 'no restricted folders'}.`);
    openManage();
  };
  cell.replaceChildren(el('span', { class: 'group-checks inline' }, boxes),
    el('button', { class: 'btn btn-light btn-small', type: 'button', text: 'Save', onclick: save }),
    el('button', { class: 'btn btn-ghost btn-small', type: 'button', text: 'Cancel', onclick: () => cell.replaceChildren(...keep) }));
}

// "2026-11-10T17:25:00+00:00" -> "2026-11-10 18:25" in this pc's time
function localTime(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

// a new password, typed in the row itself (window.prompt does not exist in the app)
function newPassword(cell, username, say) {
  const keep = [...cell.childNodes];
  const input = el('input', { type: 'password', placeholder: 'new password (8+)', autocomplete: 'new-password',
    'aria-label': `New password for ${username}`, class: 'pw-inline' });
  const save = async () => {
    if (input.value.length < 8) { say('A password needs at least 8 characters.'); input.focus(); return; }
    const r = await window.partsfinder.userUpdate(username, { password: input.value });
    if (!r.ok) { say(r.error); return; }
    say('');
    cell.replaceChildren(...keep);
    toast(`New password for ${username}. They are signed out everywhere and sign in with the new one.`);
  };
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); save(); }
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); cell.replaceChildren(...keep); }
  });
  cell.replaceChildren(input,
    el('button', { class: 'btn btn-light btn-small', type: 'button', text: 'Save', onclick: save }),
    el('button', { class: 'btn btn-ghost btn-small', type: 'button', text: 'Cancel', onclick: () => cell.replaceChildren(...keep) }));
  input.focus();
}

function field(label, input) {
  return el('label', { class: 'mini-field' }, el('span', { text: label }), input);
}

let aiOn = false;
let imageOk = false;

async function refreshHealth() {
  const r = await window.partsfinder.health();
  if (!r.ok) { statusText.textContent = r.error; return; }
  const h = r.data;
  aiOn = Boolean(h.ai_available);
  imageOk = Boolean(h.image_search_available);
  $('#image-btn').title = imageOk ? 'Search with a photo or drawing (or paste / drop an image)'
    : `Search by image needs the AI: ${h.ai_note || 'not available'}`;
  statusText.textContent = `${h.parts.toLocaleString('en')} parts`;
  statusBox.title = h.ai_available ? `Search AI: ${modelName(h.ai_model)} on your API key`
    : `Search AI off: ${h.ai_note || 'unknown reason'}. The library's own checks answer every question.`;
  statusBox.dataset.state = h.ai_available ? 'ready' : 'limited';
}

async function loadCompanies() {
  if (who.role === 'public') {
    // not signed in on a library with accounts: the general library only
    companySel.replaceChildren(el('option', { value: '', text: 'General library' }));
    companySel.value = '';
    companySel.disabled = true;
    return;
  }
  if (who.role === 'company') {
    // a company key always searches its own company (plus the general library); /companies is admin only
    companySel.replaceChildren(el('option', { value: who.company_id, text: `${who.company_id} + general` }));
    companySel.value = who.company_id;
    companySel.disabled = true;
    return;
  }
  companySel.disabled = false;
  const keep = companySel.value;
  const r = await window.partsfinder.companies();
  const ids = new Set(r.ok ? r.data.map((c) => c.id) : []);
  companySel.replaceChildren(
    el('option', { value: '', text: 'General library' }),
    ...[...ids].sort().map((id) => {
      const c = r.ok ? r.data.find((x) => x.id === id) : null;
      return el('option', { value: id, text: c ? `${c.name && c.name !== id ? c.name : id} (${c.parts} own)` : id });
    }),
  );
  companySel.value = ids.has(keep) ? keep : '';
}

function updateSend() {
  sendBtn.disabled = !ready || busy;
  form.classList.toggle('is-busy', busy);
  $('#image-btn').disabled = !ready || busy;
  $('#cad-btn').disabled = !ready || busy;
  $('#filter-btn').disabled = !ready;
}

// ---- which folders to search (top bar) ---------------------------------------------------------------
// Signed in for a company (or the administrator with a company chosen): the general library, each folder the
// company uploaded, and its other parts can each be switched on or off. Remembered per company on this pc.
const scopeWrap = $('#scope-wrap');
const scopeMenu = $('#scope-menu');
let scopeInfo = null;          // GET /library of the chosen company
let scope = null;              // { general, other, folders: null (all) | [names] }

function scopeKey(company) { return `partsfinder-scope-${company}`; }

function loadScope(company) {
  try { const v = JSON.parse(localStorage.getItem(scopeKey(company)) || 'null'); if (v && typeof v === 'object') return v; } catch { /* none */ }
  return { general: true, other: true, folders: null };
}

function saveScope() {
  if (!scopeInfo) return;
  try { localStorage.setItem(scopeKey(scopeInfo.company_id), JSON.stringify(scope)); } catch { /* not kept: fine */ }
}

function scopeAll() {
  if (!scope || !scopeInfo) return true;
  const allFolders = scope.folders === null || scopeInfo.folders.every((f) => scope.folders.includes(f.name));
  return scope.general && (scope.other || !scopeInfo.other_parts) && allFolders;
}

// the part of a search request that says where to search (nothing = everything)
function withinBody() {
  if (!companyId() || scopeAll()) return {};
  const known = new Set(scopeInfo.folders.map((f) => f.name));
  return { within: { general: scope.general, other: scope.other,
    folders: scope.folders === null ? null : scope.folders.filter((n) => known.has(n)) } };
}

function scopeText() {
  if (scopeAll()) return 'All folders';
  const n = scope.folders === null ? scopeInfo.folders.length : scope.folders.filter((x) => scopeInfo.folders.some((f) => f.name === x)).length;
  const bits = [];
  if (scope.general) bits.push('general');
  if (n) bits.push(n === 1 ? (scope.folders || [scopeInfo.folders[0].name]).find((x) => scopeInfo.folders.some((f) => f.name === x)) : `${n} folders`);
  if (scope.other && scopeInfo.other_parts) bits.push('other parts');
  return bits.length ? bits.join(' + ') : 'Nothing chosen';
}

async function refreshScope() {
  const company = companyId();
  closeScope();
  if (!company || !ready || who.role === 'public') { scopeWrap.hidden = true; scopeInfo = null; return; }
  const r = await window.partsfinder.library(who.role === 'admin' ? company : null);
  if (!r.ok || companyId() !== company) { scopeWrap.hidden = true; return; }
  scopeInfo = r.data;
  scope = loadScope(company);
  if (who.role === 'company' && companySel.options[0]) companySel.options[0].text = `${scopeInfo.name || company} + general`;
  scopeWrap.hidden = !(scopeInfo.folders.length || scopeInfo.other_parts);
  $('#scope-text').textContent = scopeText();
  scopeWrap.dataset.narrow = String(!scopeAll());
}

function closeScope() {
  scopeMenu.hidden = true;
  $('#scope-btn').setAttribute('aria-expanded', 'false');
}

function openScope() {
  const name = scopeInfo.name || scopeInfo.company_id;
  const box = (checked, text, sub, onchange) => el('label', { class: 'scope-item' },
    el('input', { type: 'checkbox', checked, onchange: (e) => { onchange(e.target.checked); changed(); } }),
    el('span', { class: 'scope-label' }, el('span', { text }), sub ? el('small', { text: sub }) : null));
  const changed = () => { saveScope(); $('#scope-text').textContent = scopeText(); scopeWrap.dataset.narrow = String(!scopeAll()); };
  const folderOn = (n) => scope.folders === null || scope.folders.includes(n);
  const setFolder = (n, on) => {
    const cur = scope.folders === null ? scopeInfo.folders.map((f) => f.name) : scope.folders.slice();
    scope.folders = on ? [...new Set([...cur, n])] : cur.filter((x) => x !== n);
  };
  const quick = (text, fn) => el('button', { class: 'linkish', type: 'button', text, onclick: () => { fn(); changed(); openScope(); } });
  scopeMenu.replaceChildren(...[
    el('div', { class: 'menu-head' }, el('strong', { text: 'Search in' }), el('span', { text: 'Tick what your questions look through.' })),
    box(scope.general, 'General library', 'standard parts, for everyone', (v) => { scope.general = v; }),
    el('p', { class: 'scope-group', text: name }),
    scopeInfo.folders.map((f) => box(folderOn(f.name), f.name,
      `${f.parts} part${f.parts === 1 ? '' : 's'}${f.access !== 'company' ? ' \u00b7 partly restricted' : ''}`, (v) => setFolder(f.name, v))),
    scopeInfo.other_parts ? box(scope.other, `Other ${name} parts`, `${scopeInfo.other_parts} imported by the administrator`, (v) => { scope.other = v; }) : null,
    el('div', { class: 'scope-quick' },
      quick('Everything', () => { scope = { general: true, other: true, folders: null }; }),
      quick(`Only ${name}`, () => { scope = { general: false, other: true, folders: null }; }),
      quick('Only the general library', () => { scope = { general: true, other: false, folders: [] }; }))].flat().filter(Boolean));
  scopeMenu.hidden = false;
  $('#scope-btn').setAttribute('aria-expanded', 'true');
}

$('#scope-btn').addEventListener('click', (e) => {
  e.stopPropagation();
  if (!scopeInfo) return;
  if (scopeMenu.hidden) openScope(); else closeScope();
});
document.addEventListener('click', (e) => { if (!scopeMenu.hidden && !scopeMenu.contains(e.target) && e.target !== $('#scope-btn')) closeScope(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !scopeMenu.hidden) { closeScope(); $('#scope-btn').focus(); } });
companySel.addEventListener('change', () => {
  refreshScope();
  if (!companyId() && filt.library === 'company') { filt.library = 'all'; updateFilterButton(); }
});

// ---- SVG elements (icons) ---------------------------------------------------------------
const SVG = 'http://www.w3.org/2000/svg';
function svgEl(tag, attrs) {
  const n = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  return n;
}

// ---- technical properties on the card ----------------------------------------------
// Provenance data says nothing about the part itself and does not belong on the card.
const HIDDEN_PROPS = new Set(['needs_review', 'ai_metadata', 'original_name', 'folder_in_freecad_library']);
// engineering values the part states itself: shown once in Specifications (with where they come from), not twice
const ENGINEERING_PROPS = new Set(['yield_strength_mpa', 'yield_mpa', 'rp02_mpa', 're_mpa', 'tensile_strength_mpa', 'tensile_mpa',
  'rm_mpa', 'uts_mpa', 'max_load_kg', 'load_capacity_kg', 'working_load_kg', 'working_load_limit_kg', 'max_load_n',
  'load_capacity_n', 'max_load_kn', 'load_rating_kn', 'dynamic_load_rating_kn', 'c_kn', 'dynamic_load_rating_n',
  'static_load_rating_kn', 'c0_kn', 'static_load_rating_n', 'max_torque_nm', 'rated_torque_nm', 'max_pressure_bar',
  'max_pressure_mpa', 'tolerance', 'general_tolerance', 'tolerance_class', 'hardness', 'hardness_hrc', 'hardness_hv', 'hardness_hb']);
const PROP_UNITS = { mm: ' mm', cm: ' cm', kg: ' kg', g: ' g', deg: '\u00b0' };
const MAX_CARD_PROPS = 6;

function propLine(key, value) {
  // length_mm: 300 -> ["Length", "300 mm"]; stackable: false -> ["Stackable", "no"]
  const m = /^(.*)_(mm|cm|kg|g|deg)$/.exec(key);
  const base = (m ? m[1] : key).replace(/_/g, ' ');
  const label = base.charAt(0).toUpperCase() + base.slice(1);
  if (typeof value === 'boolean') return [label, value ? 'yes' : 'no', false];
  if (typeof value === 'number') return [label, mm(value) + (m ? PROP_UNITS[m[2]] : ''), true];
  return [label, String(value), false];
}

// ---- one result: a compact card ------------------------------------------------------------
// The card shows only what you need to decide whether to look closer: picture, name, one short
// sentence and the defining values. Everything else is behind "Read more".
const VERDICT_LABEL = { fits: 'Fits', close: 'Close', open: 'Not judged' };

function verdictOf(res, aiUsed) {
  // without AI nothing is judged, unless the question had exact specs that the library checked itself
  const checks = res.spec_checks || [];
  return (aiUsed || checks.length) ? res.verdict : 'open';
}

function checkLine(checks, verdict, reasons) {
  // one line about the requirements of the question: "3 of 3 requirements met" or the first deviation
  if (!checks.length) {
    // a word of the question the part does not have ("green: not stated")
    const lacking = (reasons || []).filter((r) => /: not stated$/.test(r || ''));
    return lacking.length ? el('p', { class: 'card-check unknown' }, el('span', { class: 'mark', text: '?' }), lacking.join(', ')) : null;
  }
  const bad = checks.filter((c) => c.status === 'mismatch');
  const unknown = checks.filter((c) => c.status === 'unknown');
  const ok = checks.length - bad.length - unknown.length;
  if (bad.length) {
    return el('p', { class: 'card-check bad' }, el('span', { class: 'mark', text: '✗' }),
      (bad[0].spec === 'excluded' ? `Not allowed: ${bad[0].found}` : `${bad[0].label}: ${bad[0].found || 'other'} instead of ${bad[0].requested}`)
      + (bad.length > 1 ? ` (+${bad.length - 1} more)` : ''));
  }
  if (unknown.length) {
    return el('p', { class: 'card-check unknown' }, el('span', { class: 'mark', text: '?' }),
      `${ok} of ${checks.length} requirements confirmed; ${unknown.map((c) => c.label.toLowerCase()).join(', ')} not stated`);
  }
  // every spec met but still "close": say why (e.g. "galvanized: not stated"), never a green tick
  const why = verdict === 'close' && (reasons || []).find((r) => r && r !== 'not judged by AI');
  if (why) return el('p', { class: 'card-check unknown' }, el('span', { class: 'mark', text: '?' }), why);
  return el('p', { class: 'card-check ok' }, el('span', { class: 'mark', text: '✓' }),
    checks.length === 1 ? 'Meets the requirement' : `Meets all ${checks.length} requirements`);
}

function thumb(res, cls) {
  const sheet = el('div', { class: `sheet ${cls || ''}` });
  if (res.thumbnail_url) {
    const img = el('img', { alt: `Preview of ${res.name}`, loading: 'lazy', src: apiUrl + res.thumbnail_url });
    img.addEventListener('error', () => img.replaceWith(el('span', { class: 'no-thumb', text: 'no preview' })));
    sheet.append(img);
  } else {
    sheet.append(el('span', { class: 'no-thumb', text: 'no preview' }));
  }
  return sheet;
}

function isLong(dims) {
  // matches the shortened previews of profiles, shafts and tubes (ingest/thumbnail.py)
  if (!dims) return false;
  const d = [...dims].sort((a, b) => a - b);
  return d[1] > 0 && d[2] / d[1] > 6;
}

// outer envelope, largest first (L × W × H): the same on cards, in Read more and in Compare
function sizeOf(dims) {
  return dims ? `${[...dims].sort((a, b) => b - a).map(mm).join(' \u00d7 ')} mm` : null;
}

function sizeText(dims) {
  return dims ? el('span', { class: 'card-size', title: 'Outer envelope in mm, largest first', text: sizeOf(dims) }) : null;
}

function cardMeta(res) {
  const [key, text, title] = originOf(res);
  return el('div', { class: 'card-meta' }, el('span', { class: 'card-origin', 'data-origin': key, text, title }), sizeText(res.dims_mm));
}

// where the model comes from: the company's own library first, then the standard parts
function originOf(res) {
  if (res.access_group) {
    const gs = res.access_group.split(',');
    return ['restricted', `Restricted: ${gs.join(', ')}`,
      `Only people with ${gs.map((g) => `"${g}"`).join(' or ')} see this part. It is never sent to an outside AI.`];
  }
  if (res.library === 'company') return ['company', 'Your company', `Your company's own library (${res.company_id})`];
  const pack = OPEN_SOURCES[res.source];
  if (pack) return [pack[0], pack[1], `General library, from ${pack[2]}`];
  return ['standard', 'Standard', 'General library of standard parts'];
}

// the open libraries of the general library (data packs): badge, short name, where it comes from
const OPEN_SOURCES = {
  'FreeCAD-library': ['freecad', 'FreeCAD', 'the FreeCAD parts library (CC-BY 3.0)'],
  'freecad-library': ['freecad', 'FreeCAD', 'the FreeCAD parts library (CC-BY 3.0)'],
  'kicad-3d': ['kicad', 'KiCad', 'the KiCad 3D model library (CC-BY-SA 4.0)'],
  'adafruit-cad-parts': ['adafruit', 'Adafruit', 'the Adafruit CAD parts (MIT)'],
};

function primaryFile(res) {
  return [...(res.files || [])].sort((a, b) => Number(b.is_primary) - Number(a.is_primary))[0] || null;
}

async function downloadPart(res, btn) {
  const f = primaryFile(res);
  if (!f) return;
  if (btn) btn.disabled = true;
  const r = await window.partsfinder.saveFile(f.url, `${res.id}.${f.format}`);
  if (btn) btn.disabled = false;
  if (!r.canceled) toast(r.ok ? `Saved ${f.format.toUpperCase()} to ${r.path}` : r.error, r.ok);
}

function renderCard(res, askedAs, aiUsed) {
  shown.set(res.id, { res, askedAs, aiUsed });
  const verdict = verdictOf(res, aiUsed);
  const open = () => openDetail(res.id);

  const highlights = (res.highlights || []).slice(0, 3);
  const dims = highlights.length
    ? el('dl', { class: 'card-dims' }, highlights.flatMap((h) => [el('dt', { text: h.label }), el('dd', { text: h.value })]))
    : null;
  const file = primaryFile(res);
  const dl = el('button', { class: 'btn btn-small card-download', type: 'button', disabled: !file,
    title: file ? `Save the ${file.format.toUpperCase()} file` : 'No CAD file stored for this part' },
  downloadIcon(), file ? `Download ${file.format.toUpperCase()}` : 'No file');
  dl.addEventListener('click', () => downloadPart(res, dl));

  return el('article', { class: 'card', 'data-verdict': verdict },
    el('div', { class: 'card-figure' },
      el('button', { class: 'card-open', type: 'button', onclick: open, 'aria-label': `Read more about ${res.name}` }, thumb(res)),
      isLong(res.dims_mm) ? el('span', { class: 'short-tag', text: 'Preview shortened',
        title: 'The preview shows a short piece; the real length is in the size below' }) : null,
      verdict !== 'open' ? el('span', { class: 'verdict', 'data-v': verdict, text: VERDICT_LABEL[verdict] })
        : res.similarity != null ? el('span', { class: 'verdict', 'data-v': 'open', text: `${Math.round(res.similarity * 100)}% similar` }) : null,
      pickButton(res, true)),
    el('div', { class: 'card-body' },
      el('h3', { class: 'card-name' }, el('button', { class: 'card-title', type: 'button', text: res.name, title: res.name, onclick: open })),
      el('p', { class: 'card-summary', text: res.summary || res.description || '' }),
      dims,
      checkLine(res.spec_checks || [], verdict, res.mismatch_reasons)),
    el('div', { class: 'card-foot' },
      cardMeta(res),
      el('div', { class: 'card-actions' },
        dl,
        el('button', { class: 'btn btn-small btn-ghost', type: 'button', text: 'Details', onclick: open }))));
}

function downloadIcon() {
  const svg = svgEl('svg', { class: 'dl-icon', viewBox: '0 0 24 24', 'aria-hidden': 'true' });
  svg.append(svgEl('path', { d: 'M12 4v11m0 0-4.5-4.5M12 15l4.5-4.5M5 19.5h14' }));
  return svg;
}

// notifications, bottom right. kind: 'ok', 'info', 'warn', 'error' or 'busy' (true / false = ok / warn).
// Returns { update(text), close() }; a sticky one stays until closed.
const TOAST_MARK = { ok: '\u2713', info: 'i', warn: '!', error: '\u00d7', busy: '' };
function toast(text, kind = true, { title = '', detail = '', sticky = false } = {}) {
  const k = kind === true ? 'ok' : kind === false ? 'warn' : kind;
  const box = $('#toasts');
  const body = el('span', { class: 'toast-text', text });
  const t = el('div', { class: 'toast', 'data-kind': k, role: k === 'error' ? 'alert' : 'status' },
    el('span', { class: 'toast-icon', 'aria-hidden': 'true', text: TOAST_MARK[k] }),
    el('div', { class: 'toast-body' }, title ? el('strong', { class: 'toast-title', text: title }) : null, body,
      detail ? el('span', { class: 'toast-detail', text: detail }) : null),
    el('button', { class: 'toast-close', type: 'button', 'aria-label': 'Dismiss', text: '\u00d7', onclick: () => close() }));
  let timer = 0;
  const close = () => {
    clearTimeout(timer);
    t.classList.add('leaving');
    setTimeout(() => t.remove(), 200);
  };
  box.append(t);
  while (box.children.length > 4) box.firstElementChild.remove();
  // only a running import stays until it is done; a result stays a little longer when it says more
  if (!sticky) timer = setTimeout(close, k === 'error' ? 8000 : 4500);
  else if (k !== 'busy') timer = setTimeout(close, 15000);
  return { close, update: (x) => { body.textContent = x; } };
}

function resultsGrid(results, askedAs, aiUsed) {
  return el('div', { class: 'results' }, results.map((r) => renderCard(r, askedAs, aiUsed)));
}

function pickButton(res, chip = false) {
  const b = el('button', { class: chip ? 'pick pick-chip' : 'pick', type: 'button', 'data-id': res.id, 'aria-pressed': String(picked.has(res.id)),
    title: 'Add to the comparison (2 to 4 parts)' },
  el('span', { class: 'pick-box', 'aria-hidden': 'true' }), 'Compare');
  b.addEventListener('click', () => togglePick(res));
  return b;
}

function togglePick(res) {
  if (picked.has(res.id)) {
    picked.delete(res.id);
  } else {
    if (picked.size >= MAX_COMPARE) { nudgeTray(); return; }
    picked.set(res.id, res);
  }
  document.querySelectorAll(`.pick[data-id="${CSS.escape(res.id)}"]`)
    .forEach((b) => b.setAttribute('aria-pressed', String(picked.has(res.id))));
  renderCompare();
}

// ---- detail panel ("Read more") -----------------------------------------------------------
const detail = $('#detail');
let viewer = null;               // the running 3D viewer, if any

function closeDetail() {
  if (viewer) { viewer.destroy(); viewer = null; }
  if (detail.open) detail.close();
}
detail.addEventListener('close', () => { if (viewer) { viewer.destroy(); viewer = null; } });
detail.addEventListener('click', (e) => { if (e.target === detail) closeDetail(); });   // click on the backdrop

function specsList(res) {
  const specs = el('dl', { class: 'specs' });
  const add = (label, value, num = false) => {
    if (!value) return;
    specs.append(el('dt', { text: label }), el('dd', { class: num ? 'num' : null, text: value }));
  };
  if (res.dims_mm) add('Size (largest first)', sizeOf(res.dims_mm), true);
  if (res.volume_mm3 > 0) add('Volume', `${mm(Math.round(res.volume_mm3 / 100) / 10)} cm³`, true);
  add('Material', res.material);
  add('Standards', (res.standards || []).join(', '));
  // strength, load, tolerance, hardness and mass, each with where the value comes from
  (res.engineering || []).forEach((v) => specs.append(el('dt', { text: v.label }),
    el('dd', { class: 'num' }, v.text,
      el('span', { class: 'spec-source', text: v.source === 'part data' ? 'stated by the part' : v.source }))));
  Object.entries(res.properties || {})
    .filter(([k, v]) => !HIDDEN_PROPS.has(k) && !ENGINEERING_PROPS.has(k.toLowerCase()) && v !== null && v !== '')
    .forEach(([k, v]) => { const [label, text, num] = propLine(k, Array.isArray(v) ? v.join(', ') : v); add(label, text, num); });
  add('Colour', res.color);
  add('Category', res.category_path.split('/').join(' / '));
  add('Library', originOf(res)[2]);
  if (res.kind === 'assembly') add('Kind', 'assembly');
  if (res.needs_review) add('Note', 'data still to be reviewed');
  return specs;
}

function specTable(checks) {
  const table = el('table', { class: 'spec-check' });
  table.append(el('tr', {}, ['Requirement', 'Requested', 'This part', ''].map((t) => el('th', { text: t }))));
  checks.forEach((c) => table.append(el('tr', { class: c.status },
    el('td', { text: c.label }), el('td', { class: 'num', text: c.requested }),
    el('td', { class: 'num', text: c.found || 'not stated' }),
    el('td', { class: 'mark', text: { match: '✓', mismatch: '✗', unknown: '?' }[c.status] }))));
  return table;
}

function picture(res) {
  // the preview with the model's outer size along its own axes (the preview is a 3D view, so the
  // sizes are named, not drawn against the picture)
  const fig = el('div', { class: 'part-figure' }, thumb(res));
  if (res.dims_mm) {
    const [x, y, z] = res.dims_mm;
    fig.append(el('p', { class: 'axes', title: 'Outer size along the model’s X, Y and Z axis' },
      [['X', x], ['Y', y], ['Z', z]].map(([axis, v]) => el('span', { class: 'axis', 'data-axis': axis },
        el('b', { text: axis }), ` ${mm(v)} mm`))));
  }
  return fig;
}

function openDetail(id) {
  const item = shown.get(id);
  if (!item) return;
  const { res, askedAs, aiUsed } = item;
  const verdict = verdictOf(res, aiUsed);
  closeDetail();

  const note = el('p', { class: 'note', hidden: true });
  const say = (ok, text) => { note.hidden = false; note.className = ok ? 'note ok' : 'note err'; note.textContent = text; };

  // left: picture or 3D
  const stage = el('div', { class: 'stage' }, picture(res));
  const stageNote = el('p', { class: 'stage-note', hidden: true });

  // ---- the three main actions --------------------------------------------------------
  const view3d = el('button', { class: 'btn btn-action', type: 'button', disabled: !res.mesh_url,
    title: res.mesh_url ? 'Rotate: drag. Pan: right-drag. Zoom: wheel. Reset: double-click.'
      : 'Only STEP and STL files can be shown in 3D',
    text: 'View 3D model' });
  view3d.addEventListener('click', async () => {
    if (viewer) {                                   // back to the picture
      viewer.destroy(); viewer = null;
      stage.replaceChildren(picture(res));
      stageNote.hidden = true;
      view3d.textContent = 'View 3D model';
      return;
    }
    view3d.disabled = true;
    stage.replaceChildren(el('p', { class: 'thinking', text: 'Preparing the 3D model...' }));
    const r = await window.partsfinder.mesh(res.mesh_url);
    // the dialog was closed or replaced by another part while the mesh was loading: drop the result
    if (!detail.open || !stage.isConnected) return;
    view3d.disabled = false;
    if (!r.ok) { stage.replaceChildren(picture(res)); say(false, r.error); return; }
    const canvas = el('canvas', { class: 'viewer', 'aria-label': `3D model of ${res.name}` });
    stage.replaceChildren(canvas);
    try {
      viewer = window.PartsViewer.createViewer(canvas, r.data.buffer.slice(r.data.byteOffset, r.data.byteOffset + r.data.byteLength));
      stageNote.hidden = false;
      stageNote.textContent = `Drag to rotate, right-drag to pan, scroll to zoom, double-click to reset. ${viewer.triangles.toLocaleString('en')} triangles.`;
      view3d.textContent = 'Show picture';
    } catch (err) {
      stage.replaceChildren(picture(res));
      say(false, err.message);
    }
  });

  const sheetBtn = el('button', { class: 'btn btn-action', type: 'button', text: 'Datasheet',
    onclick: async () => { const r = await window.partsfinder.openDatasheet(res.datasheet_url, res.name); if (!r.ok) say(false, r.error); } });

  const files = [...res.files].sort((a, b) => Number(b.is_primary) - Number(a.is_primary));
  const fmt = files.length > 1
    ? el('select', { class: 'fmt', 'aria-label': 'File format' }, files.map((f, i) => el('option', { value: String(i), text: f.format.toUpperCase() })))
    : null;
  const download = el('button', { class: 'btn btn-action btn-primary', type: 'button', disabled: !files.length,
    text: files.length ? `Download ${files.length === 1 ? files[0].format.toUpperCase() : ''}`.trim() : 'No file' });
  download.addEventListener('click', async () => {
    const f = files[fmt ? Number(fmt.value) : 0];
    download.disabled = true;
    const r = await window.partsfinder.saveFile(f.url, `${res.id}.${f.format}`);
    download.disabled = false;
    if (!r.canceled) say(r.ok, r.ok ? `Saved to ${r.path}` : r.error);
  });

  // ---- right: the information ----------------------------------------------------------
  const info = el('div', { class: 'detail-info' });
  info.append(el('p', { class: 'detail-desc', text: res.description || res.summary || 'No description.' }));
  const checks = res.spec_checks || [];
  if (checks.length) info.append(el('h3', { text: 'Requirements from your question' }), specTable(checks));
  const reasons = el('ul', { class: 'reasons' });
  if (aiUsed) {
    (res.match_reasons || []).forEach((t) => reasons.append(el('li', { class: 'plus', text: t })));
    (res.mismatch_reasons || []).forEach((t) => reasons.append(el('li', { class: 'min', text: t })));
  }
  if (reasons.children.length) info.append(el('h3', { text: 'Assessment' }), reasons);
  info.append(el('h3', { text: 'Specifications' }), specsList(res));
  const parts = res.kind === 'assembly' ? el('div', {}, el('p', { class: 'note', text: 'Loading the components...' })) : null;
  if (parts) info.append(el('h3', { text: 'Consists of' }), parts);
  // where used: the assemblies this part is already in, so it can be reused with confidence
  const usedIn = el('div', { class: 'used-in', hidden: true });
  info.append(usedIn);
  window.partsfinder.part(res.id, askedAs).then((r) => {
    if (parts) {
      const comps = r.ok ? (r.data.components || []) : [];
      parts.replaceChildren(comps.length
        ? el('ul', { class: 'plain' }, comps.map((c) => el('li', { text: `${c.quantity} × ${c.name}` })))
        : el('p', { class: 'note', text: r.ok ? 'No components recorded.' : r.error }));
    }
    const uses = r.ok ? (r.data.used_in || []) : [];
    if (uses.length) {
      usedIn.hidden = false;
      usedIn.replaceChildren(el('h3', { text: `Used in ${uses.length} assembl${uses.length === 1 ? 'y' : 'ies'}` }),
        el('ul', { class: 'plain' }, uses.map((u) => el('li', { text: `${u.name} (${u.quantity} ×)` }))));
    }
  });
  if (res.license) {
    const origin = /^https:\/\//.test(res.source_ref || '')
      ? el('a', { href: res.source_ref, target: '_blank', rel: 'noopener', text: 'original file' }) : null;
    info.append(el('p', { class: 'note' }, `License: ${res.license}`, ...(origin ? [' · ', origin] : [])));
  }

  // ---- secondary: compare, feedback, similar ------------------------------------------------
  const pick = pickButton(res);
  const fb = (rating, text) => el('button', { class: 'btn btn-ghost btn-small', type: 'button', text,
    onclick: async (e) => {
      e.currentTarget.disabled = true;
      const r = await window.partsfinder.feedback({ part_id: res.id, rating, company_id: askedAs || null, query: lastQuery });
      say(r.ok, r.ok ? 'Thanks, noted (stays on this computer).' : r.error);
    } });
  const similar = el('div', { class: 'similar', hidden: true });
  const similarBtn = el('button', { class: 'btn btn-ghost btn-small', type: 'button', text: 'Similar shapes' });
  similarBtn.addEventListener('click', async () => {
    similar.hidden = !similar.hidden;
    if (similar.hidden || similar.dataset.loaded) return;
    similar.dataset.loaded = '1';
    similar.replaceChildren(el('p', { class: 'note', text: 'Searching...' }));
    const r = await window.partsfinder.similar(res.id, askedAs);
    if (!r.ok) { similar.replaceChildren(el('p', { class: 'note err', text: r.error })); return; }
    const list = r.data.results;
    similar.replaceChildren(
      el('h3', { text: 'Similar shape (outer size and volume only)' }),
      list.length ? resultsGrid(list, askedAs, false) : el('p', { class: 'note', text: 'No part with a similar shape.' }));
  });

  detail.replaceChildren(
    el('div', { class: 'detail-head' },
      el('div', {},
        verdict === 'open' ? null : el('span', { class: 'verdict', 'data-v': verdict, text: VERDICT_LABEL[verdict] }),
        el('h2', { id: 'detail-name', class: 'detail-name', text: res.name }),
        el('p', { class: 'part-cat', text: res.category_path.split('/').join(' / ') }),
        cardMeta(res)),
      el('button', { class: 'detail-close', type: 'button', 'aria-label': 'Close', text: '×', onclick: closeDetail })),
    el('div', { class: 'detail-actions' }, view3d, sheetBtn, el('span', { class: 'download' }, download, fmt)),
    note,
    el('div', { class: 'detail-main' }, el('div', { class: 'detail-left' }, stage, stageNote), info),
    el('div', { class: 'detail-foot' }, pick, fb('up', 'Good suggestion'), fb('down', 'Does not fit'), similarBtn),
    similar);
  detail.showModal();
  detail.scrollTop = 0;
  view3d.focus();
}

// ---- comparing -------------------------------------------------------------------------
const MAX_COMPARE = 4;

const NONE = '—';

function compareRows(list) {
  // [group, label, cells]; rows where no part has a value are left out
  const val = (v) => (v === undefined || v === null || v === '' || (Array.isArray(v) && !v.length) ? NONE : v);
  const rows = [
    ['Geometry', 'Size (largest first)', list.map((p) => sizeOf(p.dims_mm) || NONE)],
    ['Geometry', 'Volume', list.map((p) => (p.volume_mm3 > 0 ? `${mm(Math.round(p.volume_mm3 / 100) / 10)} cm³` : NONE))],
    ['Specification', 'Material', list.map((p) => val(p.material))],
    ['Specification', 'Standards', list.map((p) => val((p.standards || []).join(', ')))],
  ];
  const engKeys = [];
  list.forEach((p) => (p.engineering || []).forEach((v) => { if (!engKeys.includes(v.key)) engKeys.push(v.key); }));
  engKeys.forEach((key) => {
    const label = list.map((p) => (p.engineering || []).find((v) => v.key === key)).find(Boolean).label;
    rows.push(['Specification', label, list.map((p) => ((p.engineering || []).find((v) => v.key === key) || {}).text || NONE)]);
  });
  const keys = [];
  list.forEach((p) => Object.keys(p.properties || {})
    .filter((k) => !HIDDEN_PROPS.has(k) && !ENGINEERING_PROPS.has(k.toLowerCase()) && !keys.includes(k)).forEach((k) => keys.push(k)));
  keys.slice(0, 14).forEach((k) => {
    rows.push(['Specification', propLine(k, 0)[0], list.map((p) => {
      const v = val((p.properties || {})[k]);
      return v === NONE ? NONE : propLine(k, Array.isArray(v) ? v.join(', ') : v)[1];
    })]);
  });
  rows.push(['Source', 'Colour', list.map((p) => val(p.color))]);
  rows.push(['Source', 'Library', list.map((p) => originOf(p)[1])]);
  return rows.filter(([, , cells]) => cells.some((c) => c !== NONE));
}

// the tray above the input: thumbnails of the picked parts and the Compare button
function renderCompare() {
  const list = [...picked.values()];
  const tray = $('#compare-tray');
  tray.hidden = list.length === 0;
  $('#compare-thumbs').replaceChildren(...list.map((p) => el('button', {
    class: 'tray-thumb', type: 'button', title: `Remove ${p.name}`, 'aria-label': `Remove ${p.name} from the comparison`,
    onclick: () => togglePick(p) }, thumb(p, 'mini'))));
  $('#compare-count').textContent = list.length < 2
    ? 'Pick one more part to compare'
    : `${list.length} parts selected`;
  $('#compare-open').disabled = list.length < 2;
  if (compareDlg.open) list.length < 2 ? compareDlg.close() : openCompare();
}

function nudgeTray() {
  const tray = $('#compare-tray');
  $('#compare-count').textContent = `At most ${MAX_COMPARE} parts; remove one first`;
  tray.classList.remove('nudge');
  void tray.offsetWidth;                 // restart the animation
  tray.classList.add('nudge');
}

const compareDlg = $('#compare');
let onlyDiff = false;

function openCompare() {
  const list = [...picked.values()];
  if (list.length < 2) return;
  const rows = compareRows(list);
  // same: every part states the value and it is equal; diff: parts state different values;
  // open: a part does not state it, so nothing can be said (never counted as a difference)
  const rowState = (cells) => {
    const present = cells.filter((c) => c !== NONE);
    if (new Set(present).size > 1) return 'diff';
    return present.length === cells.length ? 'same' : 'open';
  };
  const count = (state) => rows.filter(([, , c]) => rowState(c) === state).length;

  const table = el('table', { class: 'cmp', 'data-cols': String(list.length) });
  table.append(el('colgroup', {}, el('col', { class: 'cmp-label-col' }), list.map(() => el('col'))));
  table.append(el('thead', {}, el('tr', {}, el('th', { class: 'cmp-corner' }),
    list.map((p) => el('th', { scope: 'col' },
      el('div', { class: 'cmp-part' },
        thumb(p, 'cmp-thumb'),
        el('button', { class: 'linkish cmp-name', type: 'button', text: p.name, onclick: () => { compareDlg.close(); openDetail(p.id); } }),
        el('button', { class: 'cmp-remove', type: 'button', 'aria-label': `Remove ${p.name}`, text: '×', onclick: () => togglePick(p) })))))));
  const body = el('tbody');
  let group = '';
  rows.forEach(([g, label, cells]) => {
    const state = rowState(cells);
    if (onlyDiff && state !== 'diff') return;
    if (g !== group) {
      group = g;
      body.append(el('tr', { class: 'cmp-group' }, el('th', { colspan: String(list.length + 1), text: g })));
    }
    body.append(el('tr', { class: state },
      el('th', { scope: 'row' }, el('span', { class: 'cmp-flag', 'aria-hidden': 'true' }), label,
        el('span', { class: 'sr-only', text: { same: ' (same for all)', diff: ' (differs)', open: ' (not stated by every part)' }[state] })),
      // per value: green when another part has the same value, amber when it differs from the others
      cells.map((c) => el('td', {
        class: c === NONE ? 'missing' : state === 'open' ? null : (cells.filter((x) => x === c).length > 1 ? 'is-same' : 'is-diff'),
        text: c === NONE ? 'not stated' : c }))));
  });

  table.append(body);
  const toggle = el('button', { class: 'switch', type: 'button', role: 'switch', 'aria-checked': String(onlyDiff),
    onclick: () => { onlyDiff = !onlyDiff; openCompare(); } }, el('span', { class: 'switch-track', 'aria-hidden': 'true' }), 'Only differences');

  compareDlg.replaceChildren(
    el('div', { class: 'cmp-head' },
      el('div', {},
        el('h2', { id: 'compare-title', text: 'Compare' }),
        el('p', { class: 'cmp-summary' },
          el('span', { class: 'key key-same', text: `${count('same')} the same` }),
          el('span', { class: 'key key-diff', text: `${count('diff')} different` }),
          count('open') ? el('span', { class: 'key key-open', text: `${count('open')} not stated by every part` }) : null)),
      el('div', { class: 'cmp-tools' }, toggle,
        el('button', { class: 'detail-close', type: 'button', 'aria-label': 'Close', text: '×', onclick: () => compareDlg.close() }))),
    el('div', { class: 'cmp-scroll' }, table));
  if (!compareDlg.open) compareDlg.showModal();
}
compareDlg.addEventListener('click', (e) => { if (e.target === compareDlg) compareDlg.close(); });

// ---- one search = one view: a header with the question and the verdict, then the parts -----------------
const STATUS_ICON = {
  none: 'M10.5 4a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13zM15.5 15.5l5 5M8 10.5h5',
  error: 'M12 8v5m0 3.5v.01M10.3 3.9 2.6 17.5A2 2 0 0 0 4.3 20.5h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z',
};

function iconSvg(d) {
  const svg = svgEl('svg', { viewBox: '0 0 24 24', 'aria-hidden': 'true' });
  svg.append(svgEl('path', { d }));
  return svg;
}

// nothing to show: say what happened and what to do next
function emptyState(kind, title, text) {
  return el('div', { class: 'empty-state', 'data-kind': kind, role: kind === 'error' ? 'alert' : null },
    el('span', { class: 'empty-icon' }, iconSvg(STATUS_ICON[kind] || STATUS_ICON.none)),
    el('h2', { text: title }),
    text ? el('p', { text }) : null);
}

// the verdict of a search in the view's header: a status pill and one sentence
function setHead(turn, status, label, message) {
  const pill = el('span', { class: 'answer-status', 'data-status': status, text: label });
  turn.sub.replaceChildren(...[pill, message ? el('p', { class: 'answer-msg', text: message }) : null, turn.meta].filter(Boolean));
}

// grid or list, remembered on this pc
let viewMode = 'grid';
try { if (localStorage.getItem('partsfinder-view') === 'list') viewMode = 'list'; } catch { /* grid */ }

const VIEW_ICONS = {
  grid: 'M4 4h6.5v6.5H4zM13.5 4H20v6.5h-6.5zM4 13.5h6.5V20H4zM13.5 13.5H20V20h-6.5z',
  list: 'M4 6h16M4 12h16M4 18h16',
};

function viewToggle() {
  const btn = (mode, label) => el('button', { type: 'button', 'data-mode': mode, 'aria-pressed': String(viewMode === mode),
    'aria-label': label, title: label, onclick: () => setViewMode(mode) }, iconSvg(VIEW_ICONS[mode]));
  return el('div', { class: 'segmented', role: 'group', 'aria-label': 'Show results as' }, btn('grid', 'Grid'), btn('list', 'List'));
}

function setViewMode(mode) {
  viewMode = mode;
  try { localStorage.setItem('partsfinder-view', mode); } catch { /* not kept */ }
  document.querySelectorAll('.segmented button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.mode === mode)));
  feed.querySelectorAll('.results-slot').forEach((slot) => slot.replaceChildren(renderResults(slot.data)));
}

function renderResults({ results, askedAs, aiUsed }) {
  if (viewMode === 'grid') return resultsGrid(results, askedAs, aiUsed);
  return el('div', { class: 'results-list' }, el('table', {},
    el('thead', {}, el('tr', {},
      el('th', { scope: 'col' }, el('span', { class: 'sr-only', text: 'Preview' })),
      el('th', { scope: 'col', text: 'Part' }), el('th', { scope: 'col', class: 'row-origin', text: 'Source' }),
      el('th', { scope: 'col', text: 'Size' }), el('th', { scope: 'col', text: 'Match' }),
      el('th', { scope: 'col', class: 'row-check', text: 'Requirements' }),
      el('th', { scope: 'col' }, el('span', { class: 'sr-only', text: 'Actions' })))),
    el('tbody', {}, results.map((r) => renderRow(r, askedAs, aiUsed)))));
}

// the parts of a search, in the chosen layout
function resultsBlock(results, askedAs, aiUsed) {
  const slot = el('div', { class: 'results-slot' });
  slot.data = { results, askedAs, aiUsed };
  slot.append(renderResults(slot.data));
  return slot;
}

// one part as a table row (the list layout)
function renderRow(res, askedAs, aiUsed) {
  shown.set(res.id, { res, askedAs, aiUsed });
  const verdict = verdictOf(res, aiUsed);
  const open = () => openDetail(res.id);
  const [key, text, title] = originOf(res);
  const file = primaryFile(res);
  const dl = el('button', { class: 'btn btn-small card-download', type: 'button', disabled: !file,
    title: file ? `Save the ${file.format.toUpperCase()} file` : 'No CAD file stored for this part' },
  downloadIcon(), file ? file.format.toUpperCase() : 'No file');
  dl.addEventListener('click', () => downloadPart(res, dl));
  return el('tr', { class: 'result-row' },
    el('td', { class: 'row-thumb' }, el('button', { class: 'card-open', type: 'button', onclick: open, 'aria-label': `Details of ${res.name}` }, thumb(res, 'mini'))),
    el('td', { class: 'row-name' }, el('button', { class: 'card-title', type: 'button', text: res.name, onclick: open }),
      el('p', { text: res.summary || res.description || '' })),
    el('td', { class: 'row-origin' }, el('span', { class: 'card-origin', 'data-origin': key, text, title })),
    el('td', { class: 'nowrap', text: sizeOf(res.dims_mm) || '-' }),
    el('td', {}, verdict !== 'open' ? el('span', { class: 'verdict', 'data-v': verdict, text: VERDICT_LABEL[verdict] })
      : el('span', { class: 'verdict', 'data-v': 'open', text: res.similarity != null ? `${Math.round(res.similarity * 100)}% similar` : 'Not judged' })),
    el('td', { class: 'row-check' }, checkLine(res.spec_checks || [], verdict, res.mismatch_reasons)),
    el('td', { class: 'row-actions' }, pickButton(res), dl));
}

function showError(turn, text) {
  setHead(turn, 'error', STATUS_LABEL.error, '');
  turn.append(emptyState('error', 'The search did not finish', text));
}

function startTurn(title, sub, img) {
  busy = true;
  updateSend();
  empty.hidden = true;
  feed.querySelectorAll('.view').forEach((v) => v.remove());
  for (const id of [...shown.keys()]) if (!picked.has(id)) shown.delete(id);
  const meta = el('span', { class: 'reply-meta', text: sub || '' });
  const subRow = el('div', { class: 'view-sub' }, meta);
  const turn = el('section', { class: 'view', 'aria-label': 'Search results' },
    el('div', { class: 'view-head' },
      el('div', { class: 'view-title' },
        el('h1', {}, img || null, title || 'Photo search'),
        subRow),
      el('div', { class: 'view-tools' }, viewToggle())));
  turn.meta = meta;
  turn.sub = subRow;
  feed.append(turn);
  feed.scrollTop = 0;
  return turn;
}

function endTurn() {
  busy = false;
  updateSend();
}

// Everything between startTurn and endTurn: whatever goes wrong while searching or showing the answer, the
// view says so and the search bar works again (never stuck on "busy").
async function inTurn(turn, work) {
  try {
    await work();
  } catch (err) {
    console.error(err);
    turn.querySelectorAll('.loading').forEach((x) => x.remove());
    showError(turn, 'Something went wrong while showing the answer. Try again.');
  } finally {
    endTurn();
  }
}

// while searching: a line saying what happens, over the grid it is about to fill
function thinkingLine(turn, text) {
  const t = el('div', { class: 'loading' }, el('p', { class: 'thinking', text }),
    el('div', { class: 'skeleton', 'aria-hidden': 'true' }, [1, 2, 3, 4].map(() => el('span'))));
  turn.append(t);
  return t;
}


// ---- filters: one button in the search bar, one large panel -----------------------------------------
// Hard requirements on top of the question (or without one: the parts that meet them, by name). The search
// engine applies them in its own checks; a part that does not state a filtered value drops out.
const filtersDlg = $('#filters');
const FILTER_NONE = () => ({ library: 'all', kind: null, category: null, material: null, color: null, standards: [],
  max_dims_mm: null, min_dims_mm: null, properties: {}, engineering: {} });
let filt = FILTER_NONE();
let facetCache = new Map();          // `${company}|${category}` -> GET /filters

function filterBody(f = filt) {
  const out = {};
  if (f.library !== 'all') out.library = f.library;
  ['kind', 'category', 'material', 'color'].forEach((k) => { if (f[k]) out[k] = f[k]; });
  if (f.standards.length) out.standards = f.standards;
  if (f.max_dims_mm) out.max_dims_mm = f.max_dims_mm;
  if (f.min_dims_mm) out.min_dims_mm = f.min_dims_mm;
  if (Object.keys(f.properties).length) out.properties = f.properties;
  if (Object.keys(f.engineering).length) out.engineering = f.engineering;
  return out;
}
const filtersOn = () => Object.keys(filterBody()).length > 0;

function rangeText(c, unit) {
  const u = unit ? ` ${unit}` : '';
  if (c.min != null && c.max != null) return c.min === c.max ? `${c.min}${u}` : `${c.min}–${c.max}${u}`;
  return c.min != null ? `≥ ${c.min}${u}` : `≤ ${c.max}${u}`;
}

// every active filter as [label, remove()]
function filterChipsData() {
  const out = [];
  const drop = (fn) => () => { fn(); applyFilters(); };
  if (filt.library !== 'all') out.push([filt.library === 'global' ? 'General library only' : 'Own library only', drop(() => { filt.library = 'all'; })]);
  if (filt.kind) out.push([filt.kind === 'assembly' ? 'Assemblies only' : 'Single parts only', drop(() => { filt.kind = null; })]);
  if (filt.category) out.push([`Category: ${filt.category.split('/').join(' / ')}`, drop(() => { filt.category = null; })]);
  if (filt.material) out.push([`Material: ${filt.material}`, drop(() => { filt.material = null; })]);
  if (filt.color) out.push([`Colour: ${filt.color}`, drop(() => { filt.color = null; })]);
  filt.standards.forEach((s) => out.push([`Standard: ${s}`, drop(() => { filt.standards = filt.standards.filter((x) => x !== s); })]));
  if (filt.max_dims_mm) out.push([`Fits in ${filt.max_dims_mm.join(' × ')} mm`, drop(() => { filt.max_dims_mm = null; })]);
  if (filt.min_dims_mm) out.push([`At least ${filt.min_dims_mm.join(' × ')} mm`, drop(() => { filt.min_dims_mm = null; })]);
  Object.entries(filt.properties).forEach(([k, c]) => {
    const [label] = propLine(k, 0);
    const unit = (/_(mm|cm|kg|g|deg)$/.exec(k) || [])[1];
    const text = typeof c === 'object' ? rangeText(c, unit === 'deg' ? '°' : unit) : typeof c === 'boolean' ? (c ? 'yes' : 'no') : c;
    out.push([`${label}: ${text}`, drop(() => { delete filt.properties[k]; })]);
  });
  Object.entries(filt.engineering).forEach(([k, c]) => {
    const meta = ENG_FILTER_META[k] || { label: k, unit: '' };
    out.push([`${meta.label}: ${typeof c === 'object' ? rangeText(c, meta.unit) : `contains “${c}”`}`, drop(() => { delete filt.engineering[k]; })]);
  });
  return out;
}

// labels of the engineering filters (also known before the panel was ever opened)
const ENG_FILTER_META = {
  mass_g: { label: 'Mass', unit: 'g' }, yield_strength_mpa: { label: 'Yield strength', unit: 'MPa' },
  tensile_strength_mpa: { label: 'Tensile strength', unit: 'MPa' }, max_load_kg: { label: 'Maximum load', unit: 'kg' },
  load_rating_kn: { label: 'Dynamic load rating C', unit: 'kN' }, static_load_rating_kn: { label: 'Static load rating C0', unit: 'kN' },
  max_torque_nm: { label: 'Maximum torque', unit: 'Nm' }, max_pressure_bar: { label: 'Maximum pressure', unit: 'bar' },
  hardness_hrc: { label: 'Hardness', unit: 'HRC' }, tolerance: { label: 'Tolerance', unit: '' },
};

function updateFilterButton() {
  const n = filterChipsData().length;
  const badge = $('#filter-count');
  badge.hidden = !n;
  badge.textContent = String(n);
  $('#filter-btn').classList.toggle('is-on', n > 0);
  $('#filter-btn').setAttribute('aria-label', n ? `Filters, ${n} active` : 'Filters');
}

// the active filters above the results, each removable
function filterChips() {
  const data = filterChipsData();
  if (!data.length) return null;
  return el('div', { class: 'filter-chips', role: 'group', 'aria-label': 'Active filters' },
    el('span', { class: 'need-label', text: 'Filters' }),
    data.map(([label, remove]) => el('button', { class: 'chip chip-on', type: 'button', title: 'Remove this filter',
      onclick: remove }, label, el('span', { class: 'chip-x', 'aria-hidden': 'true', text: '×' }))),
    el('button', { class: 'linkish filter-clear', type: 'button', text: 'Clear all', onclick: () => { filt = FILTER_NONE(); applyFilters(); } }));
}

// after a change: the button, and the last search again with the new filters
function applyFilters() {
  updateFilterButton();
  if (!ready || busy) return;
  if (lastQuery || filtersOn()) ask(lastQuery);
}

async function loadFacets(category) {
  const key = `${companyId() || ''}|${category || ''}`;
  if (facetCache.has(key)) return facetCache.get(key);
  const r = await window.partsfinder.filters(companyId(), category || null);
  if (r.ok) facetCache.set(key, r);
  return r;
}

async function openFilters() {
  if (!ready) return;
  const draft = JSON.parse(JSON.stringify(filt));
  filtersDlg.replaceChildren(panelHead('filters-title', 'Filters', 'For every search', () => filtersDlg.close()),
    el('div', { class: 'panel-body' }, el('p', { class: 'note', text: 'Loading what this library contains...' })));
  if (!filtersDlg.open) filtersDlg.showModal();
  await renderFilters(draft);
}

// A field you can type in, with the list narrowing to what matches (for long lists: hundreds of materials or
// standards). options: [{ value, label, hint }]. free: any typed text is a valid value (material: "steel" finds
// every steel); otherwise the typed text must be (or narrow down to) one of the options.
let comboSeq = 0;
function combo({ label, value, options, onchange, placeholder, free = false }) {
  const id = `combo-${++comboSeq}`;
  const labelOf = (v) => (options.find((o) => o.value === v) || {}).label || v || '';
  let current = value || null;
  let active = -1;
  let shown = [];
  const input = el('input', { type: 'text', id, role: 'combobox', autocomplete: 'off', spellcheck: 'false',
    'aria-autocomplete': 'list', 'aria-expanded': 'false', 'aria-controls': `${id}-list`, 'aria-label': label,
    placeholder, value: labelOf(current) });
  const list = el('ul', { class: 'combo-list', id: `${id}-list`, role: 'listbox', hidden: true });
  const clear = el('button', { class: 'combo-clear', type: 'button', 'aria-label': `Clear ${label}`, title: 'Clear', text: '×',
    hidden: !current });
  const words = (t) => t.toLowerCase().replace(/[/_-]/g, ' ').split(/\s+/).filter(Boolean);
  const matches = (o, typed) => {
    const hay = `${o.label} ${o.value}`.toLowerCase().replace(/[/_-]/g, ' ');
    return typed.every((w) => hay.includes(w));
  };
  const close = () => { list.hidden = true; input.setAttribute('aria-expanded', 'false'); input.removeAttribute('aria-activedescendant'); active = -1; };
  const setActive = (i) => {
    active = i;
    [...list.children].forEach((li, k) => li.setAttribute('aria-selected', String(k === i)));
    const li = list.children[i];
    if (li && li.id) { input.setAttribute('aria-activedescendant', li.id); li.scrollIntoView({ block: 'nearest' }); }
  };
  const choose = (v) => {
    current = v || null;
    input.value = labelOf(current);
    clear.hidden = !current;
    close();
    onchange(current);
  };
  const render = () => {
    const typed = input.value === labelOf(current) ? [] : words(input.value);
    shown = options.filter((o) => matches(o, typed)).slice(0, 60);
    const items = shown.map((o, i) => {
      const li = el('li', { id: `${id}-o${i}`, role: 'option', 'aria-selected': 'false', class: o.value === current ? 'is-current' : null },
        el('span', { class: 'combo-label', text: o.label }), o.hint ? el('span', { class: 'combo-hint', text: o.hint }) : null);
      li.addEventListener('mousedown', (e) => { e.preventDefault(); choose(o.value); });
      return li;
    });
    if (free && input.value.trim() && !shown.some((o) => o.value.toLowerCase() === input.value.trim().toLowerCase())) {
      const text = input.value.trim();
      const li = el('li', { id: `${id}-free`, role: 'option', 'aria-selected': 'false', class: 'combo-free' },
        el('span', { class: 'combo-label', text: `Every ${label.toLowerCase()} with “${text}”` }));
      li.addEventListener('mousedown', (e) => { e.preventDefault(); choose(text); });
      items.unshift(li);
      shown.unshift({ value: text, label: text });
    }
    if (!items.length) items.push(el('li', { class: 'combo-none', text: 'Nothing matches' }));
    list.replaceChildren(...items);
    list.hidden = false;
    input.setAttribute('aria-expanded', 'true');
    setActive(input.value.trim() && shown.length ? 0 : -1);
  };
  // leaving the field: the typed text becomes the value when it can, else the field shows the value again
  const commit = () => {
    const text = input.value.trim();
    if (!text) { if (current) choose(null); else close(); return; }
    if (text === labelOf(current)) { close(); return; }
    const exact = options.find((o) => o.value.toLowerCase() === text.toLowerCase() || o.label.toLowerCase() === text.toLowerCase());
    if (exact) { choose(exact.value); return; }
    if (free) { choose(text); return; }
    const hits = options.filter((o) => matches(o, words(text)));
    if (hits.length) { choose(hits[0].value); return; }
    input.value = labelOf(current);
    close();
  };
  input.addEventListener('focus', () => { input.select(); render(); });
  input.addEventListener('input', render);
  input.addEventListener('blur', commit);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); if (list.hidden) render(); setActive(Math.min(active + 1, shown.length - 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(Math.max(active - 1, 0)); }
    else if (e.key === 'Enter') {
      e.preventDefault();
      if (!list.hidden && active >= 0 && shown[active]) choose(shown[active].value); else commit();
    } else if (e.key === 'Escape' && !list.hidden) {
      e.preventDefault();
      e.stopPropagation();                 // close the list, not the panel
      input.value = labelOf(current);
      close();
    }
  });
  clear.addEventListener('click', () => { input.value = ''; choose(null); input.focus(); });
  return el('div', { class: 'filter-field' }, el('label', { for: id, text: label }),
    el('div', { class: 'combo' }, input, clear, list));
}

async function renderFilters(draft) {
  const r = await loadFacets(draft.category);
  if (!filtersDlg.open) return;
  if (!r.ok) {
    filtersDlg.querySelector('.panel-body').replaceChildren(el('p', { class: 'note err', text: r.error }));
    return;
  }
  const f = r.data;
  const body = el('div', { class: 'panel-body filters-body' });
  const num = (placeholder, value, onchange, label) => {
    const inp = el('input', { type: 'number', inputmode: 'decimal', step: 'any', min: '0', placeholder, value: value ?? '', 'aria-label': label });
    inp.addEventListener('input', () => onchange(inp.value === '' ? null : Number(inp.value)));
    return inp;
  };
  const segmented = (label, value, options, onchange) => el('div', { class: 'tabs filter-tabs', role: 'radiogroup', 'aria-label': label },
    options.map(([v, text]) => {
      const b = el('button', { class: 'tab', type: 'button', role: 'radio', 'aria-checked': String(value === v), text });
      b.addEventListener('click', () => {
        onchange(v);
        b.parentElement.querySelectorAll('.tab').forEach((t) => t.setAttribute('aria-checked', String(t === b)));
      });
      return b;
    }));

  // the filters people use most: which library, category, material, standard and outer size
  const libOpts = [['all', 'Everything'], ['global', 'General library']];
  if (companyId()) libOpts.push(['company', 'Own library']);
  const catOpts = f.categories.map((c) => ({ value: c.value, label: c.value.split('/').join(' / ').replace(/-/g, ' '), hint: String(c.count) }));
  if (draft.category && !catOpts.some((o) => o.value === draft.category)) catOpts.unshift({ value: draft.category, label: draft.category.split('/').join(' / ') });
  const valueOpts = (list) => list.map((m) => ({ value: m.value, label: m.value, hint: String(m.count) }));
  const cur = draft.max_dims_mm || [null, null, null];
  const setDim = (i) => (v) => {
    const next = [...(draft.max_dims_mm || [null, null, null])];
    next[i] = v;
    draft.max_dims_mm = next.some((x) => x != null) ? next : null;
  };
  body.append(
    el('div', { class: 'filter-field' }, el('span', { text: 'Library' }),
      segmented('Library', draft.library, libOpts, (v) => { draft.library = v; })),
    el('div', { class: 'filter-grid' },
      // materials and standards differ per category: the lists follow the chosen category
      combo({ label: 'Category', value: draft.category, options: catOpts, placeholder: 'Every category',
        onchange: async (v) => { if (v === draft.category) return; draft.category = v; await renderFilters(draft); } }),
      combo({ label: 'Material', value: draft.material, options: valueOpts(f.materials), placeholder: 'Any material',
        free: true, onchange: (v) => { draft.material = v; } }),
      combo({ label: 'Standard', value: draft.standards[0] || null, options: valueOpts(f.standards), placeholder: 'Any standard',
        onchange: (v) => { draft.standards = v ? [v] : []; } })),
    el('div', { class: 'filter-field filter-dims' }, el('span', { text: 'Fits within (any orientation)' }),
      el('div', { class: 'dims-inputs' }, num('L', cur[0], setDim(0), 'Fits within: length'), el('span', { class: 'x', text: '×' }),
        num('W', cur[1], setDim(1), 'Fits within: width'), el('span', { class: 'x', text: '×' }),
        num('H', cur[2], setDim(2), 'Fits within: height'), el('span', { class: 'unit', text: 'mm' }))));

  const foot = el('div', { class: 'filters-foot' },
    el('span', { class: 'filter-note', text: `${f.total} parts in ${draft.category ? 'this category' : 'this library'}` }),
    el('div', { class: 'filters-actions' },
      el('button', { class: 'btn btn-ghost', type: 'button', text: 'Clear all', onclick: () => renderFilters(FILTER_NONE()) }),
      el('button', { class: 'btn btn-primary', type: 'submit', text: 'Show parts' })));
  const dimsErr = el('p', { class: 'form-msg', role: 'alert', hidden: true });
  body.append(dimsErr);
  const form = el('form', { class: 'filters-form', novalidate: true }, body, foot);
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    // a size needs all three numbers: say so, never drop what was typed
    if (draft.max_dims_mm && !draft.max_dims_mm.every((x) => x != null && x > 0)) {
      dimsErr.textContent = 'Fits within needs all three sizes (length, width and height), each above 0.';
      dimsErr.hidden = false;
      const inputs = [...form.querySelectorAll('.dims-inputs input')];
      (inputs.find((x, i) => !(draft.max_dims_mm[i] > 0)) || inputs[0]).focus();
      return;
    }
    filt = draft;
    filtersDlg.close();
    applyFilters();
  });
  body.prepend(el('p', { class: 'filter-note', text: 'Only parts that meet every filter are shown, also without a question.' }));
  filtersDlg.replaceChildren(panelHead('filters-title', 'Filters', 'For every search', () => filtersDlg.close()), form);
}

$('#filter-btn').addEventListener('click', openFilters);
filtersDlg.addEventListener('click', (e) => { if (e.target === filtersDlg) filtersDlg.close(); });

// no question, only filters: the parts that meet them
async function browse() {
  const askedAs = companyId();
  const turn = startTurn('Filtered parts', '');
  await inTurn(turn, async () => {
    const thinking = thinkingLine(turn, 'Finding the parts that meet the filters');
    const r = await window.partsfinder.search({ query: '', company_id: askedAs, limit: 20, filters: filterBody(), ...withinBody() });
    thinking.remove();
    if (!r.ok) showError(turn, r.error);
    else showSearch(turn, r.data, '', askedAs);
  });
}

// ---- searching -----------------------------------------------------------------------------
async function search(query) {
  const askedAs = companyId();
  const turn = startTurn(query, '');
  await inTurn(turn, () => searchInto(turn, query, askedAs));
}

// with filters: the library's own checks first (~40 ms); when they do not settle it, the AI judges the
// candidates that meet the filters (the filters themselves are never relaxed)
async function searchFiltered(query) {
  const askedAs = companyId();
  const turn = startTurn(query, '');
  await inTurn(turn, async () => {
    const thinking = thinkingLine(turn, 'Checking every requirement and filter');
    const body = { query, company_id: askedAs, limit: 6, filters: filterBody(), ...withinBody() };
    let r = await window.partsfinder.search({ ...body, use_ai: false });
    if (r.ok && !r.data.decided && aiOn) {
      thinking.querySelector('.thinking').textContent = 'Judging the parts that meet the filters';
      const judged = await window.partsfinder.search(body);
      if (judged.ok) r = judged;
    }
    thinking.remove();
    if (!r.ok) showError(turn, r.error);
    else showSearch(turn, r.data, query, askedAs);
  });
}

// the search: the library's own checks first, then the AI when it is on and needed
async function searchInto(turn, query, askedAs) {
  const thinking = thinkingLine(turn, 'Searching and checking every requirement');
  const r = await window.partsfinder.search({ query, company_id: askedAs, limit: 6, ...withinBody() });
  thinking.remove();
  if (!r.ok) { showError(turn, r.error); return; }
  showSearch(turn, r.data, query, askedAs);
}

function howText(d) {
  if (d.cached) return 'From memory';
  return `${d.ai_used ? 'Judged by AI' : 'Checked by the library'} in ${secondsText(d.seconds)}`;
}

// several parts asked for at once ("an M8 bolt and an Arduino"): one section per requested part, each with
// its own verdict, its open value and its parts
function showGroups(turn, d, askedAs) {
  turn.meta.textContent = howText(d);
  const chips = filterChips();
  if (chips) turn.append(chips);
  const found = d.groups.filter((g) => g.status === 'found').length;
  setHead(turn, d.status, STATUS_LABEL[d.status],
    `${d.groups.length} parts asked for; ${found} with a model that meets every requirement.`);
  // choosing an open value ("M8") asks the whole question again, with that value added to its own part
  const asked = (g) => `${g.quantity ? `${g.quantity}x ` : ''}${g.request}`;
  d.groups.forEach((g) => turn.append(groupSection(g.request, g.quantity, g, askedAs, d.ai_used,
    (choice) => d.groups.map((x) => (x === g ? `${asked(x)} ${choice}` : asked(x))).join(' and '))));
}

function groupSection(request, quantity, g, askedAs, aiUsed, withChoice) {
  const count = (g.results || []).length;
  let message = (g.message || '').split(/\s*Which [^?]+\?/)[0].trim();
  if (/not judged/i.test(message)) message = notJudgedText();
  const head = el('div', { class: 'group-head' },
    el('h2', { class: 'group-title' }, request.charAt(0).toUpperCase() + request.slice(1), quantity ? el('span', { class: 'group-qty', text: `× ${quantity}` }) : null),
    g.status ? el('span', { class: 'answer-status', 'data-status': g.status, text: STATUS_LABEL[g.status] || g.status }) : null,
    message ? el('p', { class: 'answer-msg', text: message }) : null);
  const section = el('section', { class: 'result-group', 'aria-label': request }, head);
  const need = (g.need || [])[0];
  if (need) section.append(needChips(need, request, withChoice));
  section.append(count ? resultsBlock(g.results, askedAs, aiUsed)
    : el('p', { class: 'group-none', text: 'No existing model found for this part.' }));
  return section;
}

// a search answer: status, the open value (if any) and the parts
function showSearch(turn, d, query, askedAs) {
  if ((d.groups || []).length > 1) { showGroups(turn, d, askedAs); return; }
  turn.meta.textContent = howText(d);
  let status = d.status;
  const need = (d.need || [])[0];
  // what the library says, without the "Which thread? ..." part: the buttons under the header ask that
  let message = (d.message || '').split(/\s*Which [^?]+\?/)[0].trim();
  const asking = need && need.choices.length && status !== 'found';
  if (!d.ai_used && d.results.length && !d.results.some((x) => (x.spec_checks || []).length)) {
    status = 'plain';                      // nothing could be checked: never call these a close match
    // a defining value is still open ("a bolt": which thread?): ask for it, the parts below are examples
    if (!message || /not judged/i.test(message)) message = asking ? '' : notJudgedText();
  }
  if (asking && !message) message = `Choose the ${need.label} to see only the parts that fit.`;
  const count = d.results.length;
  const label = status === 'plain' ? `${count} result${count === 1 ? '' : 's'}` : STATUS_LABEL[status];
  if (!count) {
    setHead(turn, status, label, '');
    const why = (message || '').replace(/^No existing model found:?\s*/i, '');
    turn.append(emptyState('none', 'No existing model found', why ? why.charAt(0).toUpperCase() + why.slice(1) : 'Try other words, or fewer requirements.'));
  } else {
    setHead(turn, status, label, message);
  }
  if (need) turn.querySelector('.view-head').after(needChips(need, query));
  const chips = filterChips();
  if (chips) turn.querySelector('.view-head').after(chips);
  if (count) turn.append(resultsBlock(d.results, askedAs, d.ai_used));
  if (d.ai_used) refreshHealth();
}

// The question leaves a defining value open ("a bolt": which thread?): the values that exist in the
// library as buttons; one click searches again with that value added.
function needChips(need, query, withChoice = (c) => `${query} ${c}`) {
  return el('div', { class: 'need', role: 'group', 'aria-label': `Choose the ${need.label}` },
    el('span', { class: 'need-label', text: need.choices.length ? `Which ${need.label}?` : `Which ${need.label}? Add it to your search.` }),
    need.choices.map((c) => el('button', { class: 'chip', type: 'button', text: c, onclick: () => ask(withChoice(c)) })));
}


// ---- searching with an image -------------------------------------------------------------
const MAX_IMAGE_SIDE = 1600;

function readImage(file) {
  // scale large photos down (keeps the request small and fast); PNG/JPEG/WebP/GIF only
  return new Promise((resolve, reject) => {
    if (!/^image\/(png|jpeg|webp|gif)$/.test(file.type)) { reject(new Error('Use a PNG, JPEG, WebP or GIF image.')); return; }
    if (file.size > 25 * 1024 * 1024) { reject(new Error('The image is larger than 25 MB.')); return; }
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('The image could not be read.'));
    reader.onload = () => {
      const img = new Image();
      img.onerror = () => reject(new Error('The image could not be opened.'));
      img.onload = () => {
        const scale = Math.min(1, MAX_IMAGE_SIDE / Math.max(img.width, img.height));
        let dataUrl = reader.result;
        if (scale < 1 || file.size > 4 * 1024 * 1024) {
          const c = document.createElement('canvas');
          c.width = Math.round(img.width * scale);
          c.height = Math.round(img.height * scale);
          const ctx = c.getContext('2d');
          ctx.fillStyle = '#fff';
          ctx.fillRect(0, 0, c.width, c.height);
          ctx.drawImage(img, 0, 0, c.width, c.height);
          dataUrl = c.toDataURL('image/jpeg', 0.9);
        }
        const m = /^data:(image\/[a-z]+);base64,(.*)$/.exec(dataUrl);
        if (!m) { reject(new Error('The image could not be read.')); return; }
        resolve({ dataUrl, mediaType: m[1], base64: m[2], name: file.name || 'pasted image' });
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  });
}

const PLACEHOLDER = 'Search parts by name, size or standard, e.g. bearing 6205-2RS';
function showAttachment() {
  const box = $('#attachment');
  box.hidden = !attached;
  form.classList.toggle('has-image', Boolean(attached));
  if (!attached) {
    input.placeholder = PLACEHOLDER;
    return;
  }
  $('#attachment-img').src = attached.dataUrl;
  $('#attachment-name').textContent = attached.name;
  input.placeholder = 'Optional: add requirements, e.g. M8, 40 mm long, stainless';
}

async function attach(file) {
  if (!file) return;
  if (!imageOk) { toast('Search by image needs the AI, which is not available right now.', 'warn'); return; }
  try {
    attached = await readImage(file);
    showAttachment();
    input.focus();
  } catch (err) {
    toast(err.message, 'error');
  }
}

async function searchImage(note) {
  const img = attached;
  attached = null;
  showAttachment();
  const askedAs = companyId();
  const turn = startTurn(note || '', 'Photo search', el('img', { class: 'view-img', src: img.dataUrl, alt: 'Image that was searched with' }));
  await inTurn(turn, async () => {
    const thinking = thinkingLine(turn, 'Identifying the part in the image');
    const r = await window.partsfinder.searchImage({ image_base64: img.base64, media_type: img.mediaType, note, company_id: askedAs, limit: 6,
      ...(filtersOn() ? { filters: filterBody() } : {}), ...withinBody() });
    thinking.remove();
    if (!r.ok) { showError(turn, r.error); return; }
    const d = r.data;
    const id = d.identified || {};
    const facts = [];
    if (id.markings && id.markings.length) facts.push(`markings ${id.markings.join(', ')}`);
    if (id.visible_features && id.visible_features.length) facts.push(id.visible_features.join(', '));
    lastQuery = d.query || note || '';               // feedback on these parts is about what was searched for
    showSearch(turn, d, lastQuery, askedAs);
    turn.querySelector('.view-head').after(el('p', { class: 'identified' },
      el('span', { class: 'identified-label', text: 'Identified as' }),
      el('span', {}, el('strong', { text: id.part_type || 'unknown' }), ` (${id.confidence || 'low'} confidence)${facts.length ? `; ${facts.join('; ')}` : ''}.`,
        d.query ? ` Searched for “${d.query}”. Sizes are only used when they are readable on the part or given in your note.` : '')));
    refreshHealth();
  });
}

// ---- searching with your own CAD file -------------------------------------------------------------
// The file is measured by the search engine (outer size and volume) and thrown away; parts of about the same
// shape come back. A first selection: holes and threads are not compared.
const CAD_EXT = /\.(step|stp|stl)$/i;
const CAD_MAX = 50 * 1024 * 1024;

async function searchCad(file) {
  if (!file || !ready || busy) return;
  if (!CAD_EXT.test(file.name || '')) { toast('Use a STEP or STL file.', 'error'); return; }
  if (file.size > CAD_MAX) { toast('The file is larger than 50 MB.', 'error'); return; }
  const askedAs = companyId();
  lastQuery = '';
  const turn = startTurn(file.name, 'Search by CAD file');
  await inTurn(turn, async () => {
    const thinking = thinkingLine(turn, 'Measuring your file and looking for parts with the same shape');
    let r;
    try {
      r = await window.partsfinder.searchShape(new Uint8Array(await file.arrayBuffer()), file.name, askedAs);
    } catch {
      r = { ok: false, error: 'The file could not be read.' };
    }
    thinking.remove();
    if (!r.ok) { showError(turn, r.error); return; }
    const d = r.data;
    const size = sizeOf(d.measured.dims_mm);
    const vol = d.measured.volume_mm3 > 0 ? `, volume ${mm(Math.round(d.measured.volume_mm3 / 100) / 10)} cm³` : '';
    const n = d.results.length;
    turn.meta.textContent = 'Compared by outer size and volume';
    setHead(turn, n ? 'found' : 'none', n ? `${n} similar` : STATUS_LABEL.none,
      n ? 'Parts with about the same outer size and volume, most similar first. Holes and threads are not compared.' : '');
    turn.querySelector('.view-head').after(el('p', { class: 'identified' },
      el('span', { class: 'identified-label', text: 'Your file' }),
      el('span', {}, el('strong', { text: size || 'no size' }), `${vol}. Nothing of it is kept.`)));
    turn.append(n ? resultsBlock(d.results, askedAs, false)
      : emptyState('none', 'No part with a similar shape', 'No part in this library has about the same outer size and volume.'));
  });
}

// ---- asking a question --------------------------------------------------------------------
async function ask(text) {
  const query = text.trim();
  if (!ready || busy) return;
  if (attached) { lastQuery = query; await searchImage(query); return; }
  if (!query) {
    lastQuery = '';
    if (filtersOn()) await browse(); else input.focus();
    return;
  }
  lastQuery = query;
  // the library's own checks first (~40 ms); the AI (your own API key) only judges what they do not settle
  if (filtersOn()) { await searchFiltered(query); return; }
  await search(query);
}


// ---- importing into the general library: progress and result as notifications ------------------
let importing = false;            // an import into the general library is running (one at a time)
let picking = false;              // its folder is being chosen: only then the search bar waits
async function importFolder(target) {
  if (!ready || busy) return;
  if (importing) { toast('An import is already running; wait until it is done.', 'warn'); return; }
  importing = true;
  picking = true;
  busy = true;
  updateSend();
  importTarget = target || null;
  let r;
  try {
    r = await window.partsfinder.pickAndIngest(importTarget);
  } catch {
    r = { ok: false, error: 'The import could not be started.' };
  } finally {
    importing = false;
    if (picking) { picking = false; busy = false; updateSend(); }     // cancelled or failed before it started
  }
  if (r.canceled) return;
  if (importToast) { importToast.close(); importToast = null; }
  if (!r.ok) { toast(r.error, 'error', { title: 'Import failed', sticky: true }); return; }
  const d = r.data;
  const parts = [`${d.added.length} new`, `${d.updated.length} updated`, `${d.skipped.length} already present`];
  if (d.failed.length) parts.push(`${d.failed.length} failed`);
  const detail = [
    d.needs_review.length ? `${d.needs_review.length} parts have no description and are marked for review.` : '',
    ...d.failed.slice(0, 5).map((f) => `${f.file}: ${f.error}`),
  ].filter(Boolean).join('\n');
  toast(`${parts.join(', ')} in ${d.seconds} s.`, d.failed.length ? 'warn' : 'ok', { title: 'Import finished', detail, sticky: true });
  refreshHealth();
  loadCompanies();
  showQuality(importTarget);
}

// after an import: how complete is the data? The library can only check requirements that are in it.
const QUALITY_LABEL = { description: 'description', material: 'material', dimensions: 'dimensions', volume: 'volume',
  properties: 'properties', preview_image: 'preview', reviewed: 'reviewed' };

async function showQuality(company) {
  const r = await window.partsfinder.quality(company || null);
  if (!r.ok || !r.data.total) return;
  const cov = Object.entries(r.data.coverage).filter(([, pct]) => pct < 100)
    .map(([k, pct]) => `${QUALITY_LABEL[k] || k} ${pct}%`);
  const d = await window.partsfinder.duplicates(company || null);
  const dup = d.ok && d.data.total
    ? `Possible duplicates (same dimensions and volume): ${d.data.groups.slice(0, 3).map((g) => g.parts.map((p) => p.name).join(' = ')).join('; ')}${d.data.total > 3 ? '; ...' : ''}.`
    : '';
  toast(cov.length ? `Of ${r.data.total} parts: ${cov.join(', ')}. The more complete, the better every requirement can be checked.`
    : `All data of the ${r.data.total} parts is complete.`, 'info', { title: 'How complete is the data', detail: dup, sticky: Boolean(dup) });
}

// ---- settings: your own AI key, and about Partsfinder -------------------------------------
const settingsDlg = $('#settings');
const GITHUB = 'https://github.com/Drilon1235/Partsfinder';

async function openSettings(focusAbout = false) {
  const [r, info] = await Promise.all([window.partsfinder.aiSettings(), window.partsfinder.appInfo()]);
  const d = r.ok ? r.data : { may_set: false, saved: false, ai_available: false, ai_note: r.error };
  const msg = el('p', { class: 'form-msg', role: 'alert', hidden: true });
  const say = (text, ok = false) => { msg.textContent = text; msg.hidden = !text; msg.dataset.ok = String(ok); };
  const key = el('input', { id: 'ai-key', type: 'password', autocomplete: 'off', spellcheck: 'false', maxlength: '300',
    placeholder: d.saved ? 'A key is saved (hidden)' : 'sk-ant-...', 'aria-label': 'Anthropic API key' });
  const state = d.ai_available
    ? el('p', { class: 'ai-state', 'data-on': 'true', text: `AI on: ${modelName(d.ai_model)} on your own key.` })
    : el('p', { class: 'ai-state', 'data-on': 'false', text: `AI off. ${d.ai_note || ''}`.trim() });
  const save = async (value) => {
    say('');
    const res = await window.partsfinder.setAiKey(value);
    if (!res.ok) { say(res.error); return; }
    key.value = '';
    await refreshHealth();
    await openSettings();
    const done = value ? (res.data.stored === 'session'
      ? 'The key works. This pc cannot encrypt it, so it is used until you close the app.'
      : 'The key works and is saved, encrypted by your operating system.') : 'The key is removed. The AI is off.';
    toast(done, true);
  };
  const aiForm = el('form', { class: 'inline-form ai-form', novalidate: true, onsubmit: (e) => { e.preventDefault(); if (key.value.trim()) save(key.value); } },
    key, el('button', { class: 'btn btn-primary', type: 'submit', text: 'Save key' }),
    d.saved ? el('button', { class: 'btn btn-danger', type: 'button', text: 'Remove', onclick: () => save('') }) : null);
  const ai = el('section', { class: 'settings-section' },
    el('h3', { text: 'AI with your own key' }),
    el('p', { class: 'panel-note', text: 'Partsfinder answers every question with its own checks first. With your own Anthropic API key it also understands vague questions, judges the parts its checks cannot settle, and searches with a photo. Anthropic bills your own account; a search costs about a tenth of a cent.' }),
    state,
    d.may_set ? aiForm : el('p', { class: 'panel-note', text: 'The AI key is set on the pc that runs this library, by the person who uses that pc (not with a company account).' }),
    msg,
    el('p', { class: 'panel-note', text: 'Get a key at console.anthropic.com. The key is stored encrypted by your operating system and only handed to the search engine on this pc. Parts of companies marked “no AI” are never sent to the AI.' }));
  const packs = d.may_set ? await packsSection() : null;
  const accounts = d.may_set ? await accountsSection() : null;
  const about = el('section', { class: 'settings-section about', id: 'about' },
    el('div', { class: 'about-head' },
      el('img', { src: 'img/partsfinder-icon.svg', alt: '', width: '56', height: '56' }),
      el('div', {}, el('h3', { text: 'Partsfinder' }), el('p', { class: 'panel-note', text: `Version ${info.version}` }))),
    el('p', { text: 'Find an existing CAD part before you draw a new one.' }),
    el('p', { class: 'about-by' }, el('img', { src: 'img/dz-mark-white.svg', alt: '', height: '18' }),
      el('span', {}, 'Made by ', el('a', { href: 'https://dzitservices.be', target: '_blank', rel: 'noopener', text: 'DZ IT Services' }))),
    el('p', { class: 'panel-note' }, 'Open source under the GNU AGPL-3.0. Source code: ',
      el('a', { href: GITHUB, target: '_blank', rel: 'noopener', text: 'github.com/Drilon1235/Partsfinder' }), '.'),
    el('p', { class: 'panel-note', text: 'The names and logos of Partsfinder and DZ IT Services are not covered by that licence.' }));
  settingsDlg.replaceChildren(panelHead('settings-title', 'Settings', 'Partsfinder', () => settingsDlg.close()),
    el('div', { class: 'panel-body' }, ai, packs, accounts, about));
  if (!settingsDlg.open) settingsDlg.showModal();
  if (focusAbout) about.scrollIntoView({ block: 'start' });
  else if (d.may_set) key.focus();
}
// accounts: optional, for sharing the library; made and repaired on the pc that runs it
async function accountsSection() {
  const intro = el('p', { class: 'panel-note', text: 'On your own pc you need no account: everything works without signing in. Accounts are for sharing this library with other people on your network, each with their own company library and groups.' });
  if (!auth.accounts) {
    return el('section', { class: 'settings-section', id: 'accounts' },
      el('h3', { text: 'Accounts (optional)' }), intro,
      el('p', { class: 'panel-note', text: 'The first account is the administrator. You choose its name and password; there is no default password. The accounts are stored only in the library on this pc.' }),
      el('div', { class: 'inline-form' }, el('button', { class: 'btn', type: 'button', text: 'Create the administrator account',
        onclick: () => { settingsDlg.close(); showSignIn('admin'); } })));
  }
  const r = await window.partsfinder.admins();
  const admins = r.ok ? r.data.admins : [];
  const names = admins.map((a) => a.username + (a.disabled ? ' (disabled)' : ''));
  const signedInAdmin = who.role === 'admin';
  const msg = el('p', { class: 'form-msg', role: 'alert', hidden: true });
  const say = (text, ok = false) => { msg.textContent = text; msg.hidden = !text; msg.dataset.ok = String(ok); };
  const user = admins.length > 1
    ? el('select', { 'aria-label': 'Administrator account' }, admins.map((a) => el('option', { value: a.username, text: a.username })))
    : el('input', { type: 'text', value: admins[0]?.username || '', readonly: true, 'aria-label': 'Administrator account' });
  const pass = el('input', { type: 'password', autocomplete: 'new-password', placeholder: 'New password', 'aria-label': 'New password' });
  const pass2 = el('input', { type: 'password', autocomplete: 'new-password', placeholder: 'Repeat it', 'aria-label': 'Repeat the new password' });
  const reset = el('form', { class: 'reset-form', novalidate: true, onsubmit: async (e) => {
    e.preventDefault();
    if (pass.value.length < 8) { say('Choose a password of at least 8 characters.'); pass.focus(); return; }
    if (pass.value !== pass2.value) { say('The two passwords are not the same.'); pass2.focus(); return; }
    const res = await window.partsfinder.adminReset(user.value, pass.value, false);
    if (!res.ok) { say(res.error); return; }
    toast(`New password set. You are signed in as ${user.value}.`, true);
    await new Promise((done) => setTimeout(done, 300));       // the app picks up the new sign-in first
    await openSettings();
  } }, user, pass, pass2, el('button', { class: 'btn', type: 'submit', text: 'Set the new password' }));
  return el('section', { class: 'settings-section', id: 'accounts' },
    el('h3', { text: 'Accounts' }), intro,
    el('p', { class: 'panel-note', text: admins.length
      ? `There already is an administrator account: ${names.join(', ')}. Only one person makes the first account; more administrators are added under “Companies and people”.`
      : 'There already are accounts in this library.' }),
    signedInAdmin ? null : el('div', { class: 'inline-form' }, el('button', { class: 'btn', type: 'button', text: 'Sign in',
      onclick: () => { settingsDlg.close(); showSignIn('admin'); } })),
    admins.length ? el('details', { class: 'reset' },
      el('summary', { text: 'Forgot the administrator password?' }),
      el('p', { class: 'panel-note', text: 'On the pc that runs the library you can give an administrator account a new password (8 characters or more). It works only here, never from another pc; the account is signed out everywhere else.' }),
      reset, msg) : null);
}

let packSay = null;
let packProgressBound = false;
// data packs: thousands of openly licensed parts (KiCad, FreeCAD, standard parts, ...) in the general library
async function packsSection() {
  const r = await window.partsfinder.packs();
  const list = r.ok ? r.data.installed : [];
  const msg = el('p', { class: 'form-msg', role: 'status', hidden: true });
  const say = (text, ok = false) => { msg.textContent = text; msg.hidden = !text; msg.dataset.ok = String(ok); };
  const rows = list.length
    ? el('ul', { class: 'plain pack-list' }, list.map((p) => el('li', { class: 'pack-row' },
      el('div', {},
        el('strong', { text: p.title || p.name }),
        el('span', { class: 'panel-note', text: ` ${Number(p.installed_parts ?? p.parts).toLocaleString('en')} parts · ${p.license} · version ${p.version}` })),
      el('button', { class: 'btn btn-ghost btn-small', type: 'button', text: 'Remove',
        onclick: async (e) => {
          if (!await askConfirm(`Remove ${p.title || p.name}?`, `This removes its ${Number(p.installed_parts ?? p.parts).toLocaleString('en')} parts from the general library. You can install the pack again later.`, 'Remove')) return;
          e.target.disabled = true;
          const res = await window.partsfinder.packRemove(p.name);
          if (!res.ok) { say(res.error); e.target.disabled = false; return; }
          toast(`${res.data.removed.toLocaleString('en')} parts removed.`, true);
          await refreshHealth();
          await openSettings();
        } }))))
    : el('p', { class: 'panel-note', text: r.ok ? 'No data packs installed yet.' : r.error });
  const install = el('button', { class: 'btn btn-primary', type: 'button', text: 'Install a data pack…',
    onclick: async () => {
      install.disabled = true;
      say('Installing… the search keeps working meanwhile.', true);
      const res = await window.partsfinder.packInstall();
      install.disabled = false;
      if (res.canceled) { say(''); return; }
      if (!res.ok) { say(res.error); return; }
      const d = res.data;
      toast(`${d.title || d.name}: ${d.added.toLocaleString('en')} parts added, ${d.updated.toLocaleString('en')} updated.`, true);
      await refreshHealth();
      await openSettings();
    } });
  packSay = say;
  if (!packProgressBound) {
    packProgressBound = true;
    window.partsfinder.onPackProgress?.((p) => {
      if (p.total && packSay) packSay(`Installing… ${p.done.toLocaleString('en')} of ${p.total.toLocaleString('en')} parts.`, true);
    });
  }
  return el('section', { class: 'settings-section', id: 'packs' },
    el('h3', { text: 'Data packs' }),
    el('p', { class: 'panel-note', text: 'Open libraries of ready-made parts for the general library: standard parts, electronic components and more, each under its own open licence. Every part shows its licence and links to its original file.' }),
    rows, el('div', { class: 'inline-form' }, install), msg);
}

$('#settings-btn').addEventListener('click', () => openSettings());
$('#brand').addEventListener('click', () => openSettings(true));

// ---- start-up ----------------------------------------------------------------------------
form.addEventListener('submit', (e) => {
  e.preventDefault();
  const q = input.value;
  if (!ready || busy) return;
  input.value = '';               // an empty bar for the next question; the question stays above its answer
  ask(q);
});

// Ctrl+K or / jumps to the search field
document.addEventListener('keydown', (e) => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || '');
  if ((e.key === 'k' && (e.ctrlKey || e.metaKey)) || (e.key === '/' && !typing && !document.querySelector('dialog[open]'))) {
    e.preventDefault();
    input.focus();
    input.select();
  }
});

$('#compare-clear').addEventListener('click', () => {
  picked.clear();
  document.querySelectorAll('.pick').forEach((b) => b.setAttribute('aria-pressed', 'false'));
  renderCompare();
});
$('#compare-open').addEventListener('click', openCompare);

// image search: button, paste (Ctrl+V) and drag-and-drop
$('#image-btn').addEventListener('click', () => $('#image-file').click());
$('#image-file').addEventListener('change', (e) => { attach(e.target.files[0]); e.target.value = ''; });
$('#attachment-remove').addEventListener('click', () => { attached = null; showAttachment(); input.focus(); });
document.addEventListener('paste', (e) => {
  const item = [...(e.clipboardData?.items || [])].find((i) => i.kind === 'file' && i.type.startsWith('image/'));
  if (!item || !ready || busy || document.querySelector('dialog[open]')) return;
  e.preventDefault();
  attach(item.getAsFile());
});
const drop = $('#drop');
let dragDepth = 0;
// an image or a CAD file (a STEP file has no type while it is dragged, so any file opens the drop zone)
const hasFile = (e) => [...(e.dataTransfer?.items || [])].some((i) => i.kind === 'file');
document.addEventListener('dragenter', (e) => { if (!hasFile(e) || !ready || busy) return; dragDepth++; drop.hidden = false; });
document.addEventListener('dragleave', () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) drop.hidden = true; });
document.addEventListener('dragover', (e) => { if (hasFile(e)) e.preventDefault(); });
document.addEventListener('drop', (e) => {
  e.preventDefault();
  dragDepth = 0;
  drop.hidden = true;
  if (!ready || busy) return;
  const files = [...(e.dataTransfer?.files || [])];
  const cad = files.find((f) => CAD_EXT.test(f.name || ''));
  const image = files.find((f) => f.type.startsWith('image/'));
  if (cad) searchCad(cad);
  else if (image) attach(image);
  else if (files.length) toast('Drop an image (PNG, JPEG, WebP, GIF) or a CAD file (STEP, STL).', 'warn');
});
$('#cad-btn').addEventListener('click', () => $('#cad-file').click());
$('#cad-file').addEventListener('change', (e) => { searchCad(e.target.files[0]); e.target.value = ''; });

window.partsfinder.onIngestStarted((folder) => {
  // the folder is chosen: searching works again while the import runs in the background
  if (picking) { picking = false; busy = false; updateSend(); }
  if (importToast) importToast.close();
  importToast = toast('Reading files, measuring and making previews...', 'busy',
    { title: `Importing ${folder} into ${importTarget ? importTarget : 'the general library'}`, sticky: true });
});

window.partsfinder.onIngestProgress((p) => {
  if (importToast) importToast.update(`${p.lines} steps done. ${p.last}`);
});

window.partsfinder.onBackendState(showBackend);
window.partsfinder.config().then((c) => { apiUrl = c.apiUrl; if (c.who) who = c.who; if (c.auth) auth = c.auth; showBackend(c.backend); });
input.focus();
