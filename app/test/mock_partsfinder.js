// Fake backend for scripts/ui_screenshots.py: the app's window.partsfinder with fixed test data, so every screen
// can be rendered in a plain browser without the API, Claude or the real library.
(() => {
  const svg = (body) => 'data:image/svg+xml;utf8,' + encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">${body}</svg>`);
  const bolt = svg('<rect x="38" y="14" width="24" height="12" fill="#5b8fd6"/><rect x="44" y="26" width="12" height="60" fill="#4a7cc4"/>');
  const plate = svg('<rect x="12" y="38" width="76" height="24" rx="3" fill="#5b8fd6"/><circle cx="24" cy="50" r="5" fill="#12161c"/><circle cx="76" cy="50" r="5" fill="#12161c"/>');
  const rod = svg('<rect x="44" y="10" width="12" height="80" fill="#4a7cc4"/>');
  const ok = (data) => Promise.resolve({ ok: true, data });
  const check = (label, requested, found, status = 'match') => ({ spec: label.toLowerCase(), label, requested, found, status });
  const part = (o) => ({ files: [{ format: 'step', is_primary: true, url: '/f' }], highlights: [], spec_checks: [], properties: {},
    standards: [], category_path: 'fasteners/bolts', mesh_url: null, datasheet_url: '/d', ...o });
  const parts = [
    part({ id: 'hex-bolt-m8x30', name: 'Hex bolt fully threaded M8x30 ISO 4017', library: 'global', source: 'partsfinder-engineering', verdict: 'fits',
      engineering: [{ key: 'mass_g', label: 'Mass', text: '≈ 17.4 g', source: 'estimate: volume from the CAD file × density of the material' },
        { key: 'yield_strength_mpa', label: 'Yield strength', text: '≥ 640 MPa', source: 'minimum per ISO 898-1, property class 8.8' },
        { key: 'tensile_strength_mpa', label: 'Tensile strength', text: '≥ 800 MPa', source: 'minimum per ISO 898-1, property class 8.8' }],
      summary: 'Hex bolt fully threaded M8x30 mm according to ISO 4017, metric thread M8x1.25.', dims_mm: [14.38, 13, 35.3], thumbnail_url: bolt,
      description: 'Hex bolt fully threaded M8x30 mm according to ISO 4017, metric thread M8x1.25.', standards: ['ISO 4017'], material: 'steel 8.8',
      highlights: [{ label: 'Thread', value: 'M8' }, { label: 'Length', value: '30 mm' }, { label: 'Pitch', value: '1.25 mm' }],
      spec_checks: [check('Thread', 'M8', 'M8'), check('Length', '30 mm', '30 mm'), check('Property class', '8.8', '8.8')] }),
    part({ id: 'acme-plate', name: 'Mounting plate 120x80 (Janssen)', library: 'company', company_id: 'janssen-engineering', source: 'generated', verdict: 'fits',
      summary: 'Own mounting plate with two M8 clearance holes.', dims_mm: [120, 80, 6], thumbnail_url: plate, category_path: 'connections/plate',
      highlights: [{ label: 'Holes', value: '2 × Ø9 mm' }, { label: 'Material', value: 'S235' }], spec_checks: [check('Hole', 'Ø9', 'Ø9')] }),
    part({ id: 'threaded-rod-m10x1000', name: 'Threaded rod M10x1000 DIN 976', library: 'global', source: 'FreeCAD-library', verdict: 'close',
      summary: 'Threaded rod M10 x 1000 mm, DIN 976-1.', dims_mm: [25.4, 25.4, 1000], thumbnail_url: rod, category_path: 'fasteners/rods',
      highlights: [{ label: 'Thread', value: 'M10' }, { label: 'Length', value: '1000 mm' }],
      spec_checks: [check('Length', '500 mm', '1000 mm', 'mismatch')] }),
  ];
  const found = { status: 'found', message: '2 parts meet every requirement.', results: parts, ai_used: false, seconds: 0.043, cached: false,
    interpreted_requirements: {}, need: [], decided: true };
  window.partsfinder = {
    // accounts (window.__signin): not signed in = the general library; anna / correct-horse = company Janssen Engineering
    config: () => Promise.resolve({ apiUrl: '', backend: { state: 'ready' } }),
    who: () => Promise.resolve(window.__who || { role: window.__signin ? 'public' : 'local', company_id: null, groups: [] }),
    authInfo: () => Promise.resolve({ accounts: Boolean(window.__signin), setup_needed: false, keys_required: false }),
    login: (user, pw) => {
      if (pw !== 'correct-horse') return Promise.resolve({ ok: false, error: 'Wrong username or password.' });
      window.__who = user === 'drilon' ? { role: 'admin', username: 'drilon', company_id: null, groups: [] }
        : { role: 'company', username: user, company_id: 'janssen-engineering', groups: ['nuclear'] };
      setTimeout(() => window.__state && window.__state({ state: 'ready', message: 'Connected' }), 0);
      return Promise.resolve({ ok: true, data: { ...window.__who, remembered: true } });
    },
    setup: () => Promise.resolve({ ok: false, error: 'There is an account already: sign in' }),
    signIn: () => Promise.resolve({ ok: false, error: 'This key is not accepted.' }),
    signOut: () => { window.__who = null; window.__state && window.__state({ state: 'ready', message: 'Signed out.' }); return Promise.resolve({ ok: true }); },
    library: () => ok({ company_id: 'janssen-engineering', name: 'Janssen Engineering', exists: true, confidential: false, parts: 128, restricted_parts: 14, other_parts: 0,
      folders: [{ name: 'Main CAD', parts: 114, updated_at: '2026-11-10T18:25', access: 'company', tree: [
          { path: '', depth: 0, parts: 114, own: null, access: 'company', inherited: 'company' },
          { path: 'brackets', depth: 1, parts: 60, own: null, access: 'company', inherited: 'company' },
          { path: 'reactor', depth: 1, parts: 14, own: 'aero,nuclear', access: 'aero,nuclear', inherited: 'company' },
          { path: 'reactor/internals', depth: 2, parts: 6, own: null, access: 'aero,nuclear', inherited: 'aero,nuclear' }] },
        { name: 'Customer X', parts: 14, updated_at: '2026-11-09T07:02', access: 'company', tree: [
          { path: '', depth: 0, parts: 14, own: null, access: 'company', inherited: 'company' }] }],
      groups: ['aero', 'nuclear'],
      my_groups: window.__who && window.__who.role === 'company' ? window.__who.groups : null,
      coverage: { description: 82, material: 64, dimensions: 100, properties: 31, preview_image: 100 }, upload_extensions: ['step'], max_file_mb: 500 }),
    uploadFolder: () => Promise.resolve({ ok: true, data: { name: 'Main CAD', report: { added: ['a'], updated: ['b', 'c'], skipped: Array(111).fill('x'),
      removed: [], failed: [] }, sent: 120, excluded: 3, skipped: [] } }),
    removeFolder: () => ok({ removed: [], total: 0 }),
    users: () => ok([{ username: 'drilon', role: 'admin', company_id: null, groups: [], disabled: false, last_login: '2026-11-10T17:25:00+00:00' },
      { username: 'anna', role: 'company', company_id: 'janssen-engineering', groups: [], disabled: false, last_login: null },
      { username: 'bert', role: 'company', company_id: 'janssen-engineering', groups: ['nuclear'], disabled: true, last_login: '2026-11-09T08:00:00+00:00' }]),
    userCreate: (b) => ok({ ...b, disabled: false, last_login: null }),
    userUpdate: (u) => ok({ username: u }),
    userDelete: (u) => ok({ removed: u }),
    companyConfidential: () => ok({}),
    companyDelete: () => ok({ removed_parts: 40, removed_accounts: 1 }),
    folderAccess: () => ok({ added: [], updated: [], skipped: [], removed: [], failed: [] }),
    companyCreate: (b) => ok({ id: 'janssen-engineering', name: b.name, parts: 0, restricted_parts: 0, confidential: false, people: 0 }),
    onUploadProgress: () => {},
    appInfo: () => Promise.resolve({ version: '1.0.0', electron: '39.0.0' }),
    aiSettings: () => ok({ may_set: true, saved: false, encrypted: true, ai_available: false, ai_model: null,
      ai_note: 'No API key: add your own Anthropic API key in Settings (or ANTHROPIC_API_KEY in backend/.env)' }),
    setAiKey: (key) => ok({ ai_available: Boolean(key), ai_model: 'claude-haiku-5-5', stored: 'stored' }),
    packs: () => ok({ installed: [
      { name: 'standard-parts', title: 'Standard parts (ISO, DIN, ASME)', license: 'Apache-2.0', version: '2026-11-13', parts: 6213, installed_parts: 6213 },
      { name: 'kicad-3d', title: 'KiCad 3D models (electronic components)', license: 'CC-BY-SA-4.0 WITH KiCad-libraries-exception', version: '2026-11-13', parts: 6189, installed_parts: 6189 }] }),
    packInstall: () => ok({ name: 'freecad-library', title: 'FreeCAD parts library', added: 2497, updated: 0 }),
    packRemove: (name) => ok({ name, removed: 6189 }),
    onPackProgress: () => {},
    health: () => ok({ ai_available: true, image_search_available: true, parts: 1809,
      ai_model: 'claude-haiku-5-5' }),
    companies: () => ok([{ id: 'janssen-engineering', name: 'Janssen Engineering', parts: 128, restricted_parts: 14, confidential: false, people: 2, groups: ['nuclear'] }, { id: 'verhoeven-machinebouw', name: 'Verhoeven Machinebouw', parts: 40, restricted_parts: 0, confidential: true, people: 1, groups: [] }]),
    search: (b) => {
      window.__lastSearch = b;
      if (!b.query) return ok({ ...found, browse: true, status: 'found', message: '2 parts meet the filters.', results: parts.slice(0, 2).map((p) => ({ ...p, spec_checks: [], verdict: 'close' })) });
      if (/ and /.test(b.query)) {
        const g1 = { request: 'M8 bolt', quantity: 1, status: 'found', message: '1 model meets every requirement.', decided: true, need: [], ai_used: false,
          results: parts.slice(0, 1).map((p) => ({ ...p, spec_checks: [check('Thread', 'M8', 'M8')] })) };
        const g2 = { request: 'arduino', quantity: 1, status: 'none', message: 'No existing model found: no part in the library is an arduino.', decided: true, need: [], ai_used: false, results: [] };
        return ok({ ...found, status: 'partial', message: '2 parts asked for', results: g1.results, groups: [g1, g2] });
      }
      if (/shelf/.test(b.query)) return ok({ ...found, status: 'partial', decided: false, message: 'Best search results.',
        results: parts.slice(1, 2).map((p) => ({ ...p, spec_checks: [] })) });
      if (/nothing/.test(b.query)) return ok({ ...found, status: 'none', results: [], seconds: 0.031, decided: false,
        message: 'No existing model in the library fits this request.' });
      if (/broken/.test(b.query)) return Promise.resolve({ ok: false, error: 'The library API did not answer (connection refused).' });
      if (/^a bolt$/.test(b.query)) return ok({ ...found, status: 'partial', results: parts.slice(0, 1).map((p) => ({ ...p, spec_checks: [] })),
        message: 'Which thread? The library has M6, M8, M10, M12. Choose one so only parts that fit are shown.',
        need: [{ spec: 'thread', label: 'thread', choices: ['M6', 'M8', 'M10', 'M12'] },
               { spec: 'length_mm', label: 'length', choices: ['20 mm', '30 mm', '40 mm'] }] });
      if (/green bolt$/.test(b.query)) return ok({ ...found, status: 'partial', results: parts.slice(0, 1).map((p) => ({ ...p, spec_checks: [], verdict: 'close', mismatch_reasons: ['green: not stated'] })),
        message: 'No bolt in the library is stated as green; the closest are shown. Which thread? The library has M6, M8, M10, M12. Choose one so only parts that fit are shown.',
        need: [{ spec: 'thread', label: 'thread', choices: ['M6', 'M8', 'M10', 'M12'] }] });
      return ok(found);
    },
    part: (id) => ok({ components: [], used_in: id === 'hex-bolt-m8x30' ? [{ id: 'frame', name: 'Machine frame 2000', quantity: 24 }, { id: 'gate', name: 'Safety gate', quantity: 8 }] : [] }),
    filters: (_c, category) => ok({ total: category ? 412 : 1809,
      categories: [{ value: 'fasteners', count: 640 }, { value: 'fasteners/bolts', count: 412 }, { value: 'fasteners/nuts', count: 120 }, { value: 'bearings', count: 96 }],
      materials: [{ value: 'steel 8.8', count: 220 }, { value: 'stainless steel A2', count: 90 }, { value: 'steel 8.8 galvanized', count: 64 },
        { value: 'steel 10.9', count: 52 }, { value: 'aluminium 6082-T6', count: 40 }, { value: 'stainless steel A4', count: 38 }, { value: 'brass', count: 20 },
        { value: 'POM', count: 14 }, { value: 'steel S235', count: 12 }, { value: 'steel 8.8 black', count: 9 }],
      colors: [{ value: 'black', count: 12 }], standards: [{ value: 'ISO 4017', count: 60 }, { value: 'ISO 4762', count: 58 }],
      kinds: [{ value: 'part', count: 1715 }, { value: 'assembly', count: 94 }], max_dims_mm: [400, 600, 2000],
      engineering: [{ key: 'mass_g', label: 'Mass', unit: 'g', type: 'number', count: 1500 }, { key: 'tensile_strength_mpa', label: 'Tensile strength', unit: 'MPa', type: 'number', count: 400 },
        { key: 'max_load_kg', label: 'Maximum load', unit: 'kg', type: 'number', count: 12 }, { key: 'tolerance', label: 'Tolerance', unit: '', type: 'text', count: 4 }],
      properties: [{ key: 'thread', count: 410, type: 'text', values: ['M6', 'M8', 'M10', 'M12'] }, { key: 'length_mm', count: 400, type: 'number', min: 8, max: 200 },
        { key: 'property_class', count: 380, type: 'text', values: ['8.8', '10.9', '12.9'] }, { key: 'galvanized', count: 90, type: 'boolean', values: ['true', 'false'] }] }),
    searchShape: () => ok({ measured: { dims_mm: [13, 13, 38], volume_mm3: 2210 }, results: parts.slice(0, 2).map((p, i) => ({ ...p, spec_checks: [], verdict: undefined, similarity: 0.94 - i * 0.2 })) }),
    similar: () => ok({ results: parts.map((p, i) => ({ ...p, spec_checks: [], similarity: 0.9 - i * 0.08 })) }),
    mesh: () => Promise.resolve({ ok: false, error: '3D is not part of the screenshot test' }),
    feedback: () => ok({}), saveFile: () => ok({ canceled: true }), openDatasheet: () => ok({}),
    quality: () => ok({}),
    duplicates: () => ok({ total: 2, groups: [{ size: 2, bbox_mm: [120, 80, 6], parts: [{ id: 'a', name: 'Mounting plate 120x80' }, { id: 'b', name: 'Plate 120x80 copy' }] },
      { size: 3, bbox_mm: [13, 13, 38], parts: [{ id: 'c', name: 'Bolt M8x30' }, { id: 'd', name: 'Hex bolt M8x30 old' }, { id: 'e', name: 'M8x30 bolt (customer X)' }] }] }), searchImage: () => ok(found), pickAndIngest: () => ok({ canceled: true }),
    onBackendState: (cb) => { window.__state = cb; }, onIngestProgress: () => {}, onIngestStarted: () => {},
  };
})();
