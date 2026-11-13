// Folder rules for uploading a company folder from this pc, the same as the library's own import
// (backend/partsfinder/ingest/rules.py, docs/10_COMPANY_LIBRARIES.md):
// - .partsfinderignore: files and folders that are NEVER read, not even here; excluded folders are not entered;
// - .partsfinderaccess: the restricted group of a folder (sent along; the library applies it);
// - rules in the folders ABOVE the chosen folder count too; a rule that cannot be used skips its folder;
// - links are never followed.
'use strict';

const fs = require('node:fs');
const path = require('node:path');

const IGNORE = '.partsfinderignore';
const ACCESS = '.partsfinderaccess';
const GROUP_RE = /^[a-z0-9][a-z0-9_-]{0,39}$/;

class RuleError extends Error {}

// fnmatch.fnmatchcase: * any text (also '/'), ? one character, [abc] / [!abc] a set
function globToRegExp(pattern) {
  let re = '';
  for (let i = 0; i < pattern.length; i++) {
    const c = pattern[i];
    if (c === '*') re += '.*';
    else if (c === '?') re += '.';
    else if (c === '[') {
      const end = pattern.indexOf(']', i + 2);
      if (end === -1) { re += '\\['; continue; }
      let set = pattern.slice(i + 1, end).replace(/\\/g, '\\\\');
      if (set[0] === '!') set = '^' + set.slice(1);
      re += `[${set}]`;
      i = end;
    } else re += c.replace(/[.+^${}()|\\/]/g, '\\$&');
  }
  return new RegExp(`^${re}$`, 's');
}

function lines(file) {
  let text;
  try { text = fs.readFileSync(file, 'utf8').replace(/^﻿/, ''); } catch (e) {
    throw new RuleError(`${path.basename(file)} cannot be read (${e.code || e.message})`);
  }
  return text.split(/\r?\n/).map((l) => l.trim()).filter((l) => l && !l.startsWith('#'));
}

// patterns of one .partsfinderignore; base = its folder relative to the walk root ('' = root)
function parseIgnore(file, base) {
  return lines(file).map((line) => {
    if (line.startsWith('!')) throw new RuleError(`${path.basename(file)}: exceptions ('${line}') are not supported`);
    line = line.replace(/\\/g, '/');
    const dirOnly = line.endsWith('/');
    const pat = line.replace(/^\/+|\/+$/g, '').toLowerCase();
    return pat ? { base, re: globToRegExp(pat), anchored: pat.includes('/'), dirOnly } : null;
  }).filter(Boolean);
}

function parseAccess(file) {
  const ls = lines(file);
  if (!ls.length) throw new RuleError(`${path.basename(file)} is empty: write a group name (or 'company')`);
  const first = ls[0].toLowerCase();
  if (first === 'company') return null;
  // several groups on one line ("nuclear, aero"): people with any of them see the folder
  const names = [...new Set(first.split(/[,;]/).map((g) => g.trim()).filter(Boolean))].sort();
  const bad = names.find((g) => !GROUP_RE.test(g));
  if (!names.length || bad) throw new RuleError(`${path.basename(file)}: '${bad || ls[0]}' is not a valid group name`);
  return names.join(',');
}

function matches(p, rel, isDir) {                 // rel: posix path relative to the walk root
  if (p.dirOnly && !isDir) return false;
  let below = rel;
  if (p.base) {
    if (rel !== p.base && !rel.startsWith(p.base + '/')) return false;
    below = rel.slice(p.base.length + 1);
  }
  const text = below.toLowerCase();
  return p.anchored ? p.re.test(text) : p.re.test(text.split('/').pop());
}

function isFile(f) { try { return fs.statSync(f).isFile(); } catch { return false; } }

// rules above the chosen folder: [excluded, inherited group or undefined]
function ancestorRules(root) {
  const chain = [];
  for (let d = path.dirname(root); ; d = path.dirname(d)) {
    chain.unshift(d);
    if (path.dirname(d) === d) break;
  }
  let group;
  for (const anc of chain) {
    if (isFile(path.join(anc, ACCESS))) group = parseAccess(path.join(anc, ACCESS));
    if (isFile(path.join(anc, IGNORE))) {
      const pats = parseIgnore(path.join(anc, IGNORE), '');
      const parts = path.relative(anc, root).split(path.sep);
      for (let i = 1; i <= parts.length; i++) {
        if (pats.some((p) => matches(p, parts.slice(0, i).join('/'), true))) return [true, group];
      }
    }
  }
  return [false, group];
}

// Everything to upload: CAD files, a JSON next to a CAD file, and the rule files. Excluded files are never
// opened here: only their names are compared.
function walk(root, extensions) {
  const exts = new Set(extensions);
  const out = { files: [], skipped: [], excluded: 0, inherited: undefined };
  let above;
  try { above = ancestorRules(root); } catch (e) {
    if (!(e instanceof RuleError)) throw e;
    out.skipped.push(['.', `rule above this folder: ${e.message}`]);
    return out;
  }
  if (above[0]) { out.skipped.push(['.', 'this folder is excluded by an .partsfinderignore in a folder above it']); return out; }
  out.inherited = above[1];

  const visit = (dir, rel, inherited) => {
    let entries;
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch (e) {
      out.skipped.push([rel || '.', `cannot be read (${e.code || e.message})`]);
      return;
    }
    const names = new Set(entries.map((e) => e.name));
    let own = [];
    try {
      if (names.has(IGNORE)) own = parseIgnore(path.join(dir, IGNORE), rel);
      if (names.has(ACCESS)) parseAccess(path.join(dir, ACCESS));      // checked here, applied by the library
    } catch (e) {
      if (!(e instanceof RuleError)) throw e;
      out.skipped.push([rel || '.', e.message]);
      return;                                                           // the whole folder, as the library does
    }
    const patterns = inherited.concat(own);
    const ignored = (name, isDir) => patterns.some((p) => matches(p, rel ? `${rel}/${name}` : name, isDir));
    const sorted = entries.slice().sort((a, b) => a.name.localeCompare(b.name));
    const cadStems = new Set(sorted.filter((e) => e.isFile() && exts.has(path.extname(e.name).slice(1).toLowerCase())
      && path.extname(e.name).toLowerCase() !== '.json').map((e) => path.parse(e.name).name));
    for (const e of sorted) {
      const r = rel ? `${rel}/${e.name}` : e.name;
      if (e.isSymbolicLink()) { out.excluded++; continue; }              // never followed
      if (e.isDirectory()) {
        if (e.name.startsWith('.') || ignored(e.name, true)) { out.excluded++; continue; }
        visit(path.join(dir, e.name), r, patterns);
        continue;
      }
      if (!e.isFile()) continue;
      const lower = e.name.toLowerCase();
      if (lower === IGNORE || lower === ACCESS) { out.files.push({ abs: path.join(dir, e.name), rel: r }); continue; }
      if (e.name.startsWith('.')) continue;
      if (ignored(e.name, false)) { out.excluded++; continue; }
      const ext = path.extname(e.name).slice(1).toLowerCase();
      if (ext === 'json' ? cadStems.has(path.parse(e.name).name) : exts.has(ext)) {
        out.files.push({ abs: path.join(dir, e.name), rel: r });
      }
    }
  };
  visit(root, '', []);
  return out;
}

module.exports = { walk, RuleError };
