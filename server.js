// Minimal "no-framework" dashboard server.
// Mirrors what the video describes: server.js + dashboard/index.html.
//
// It reads from the project SQLite DB via the `sqlite3` CLI in JSON mode
// (no npm dependencies required).

const http = require('http');
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const PORT = process.env.PORT ? parseInt(process.env.PORT, 10) : 3456;
const DB_PATH = process.env.CLAWDBOT_DB_PATH || path.join(__dirname, 'data', 'clawdbot.sqlite');
const DASH_DIR = path.join(__dirname, 'dashboard');
const KEYWORDS_PATH = process.env.KEYWORDS_PATH || path.join(__dirname, 'config', 'keywords.txt');
const KEYWORD_GROUPS_PATH = process.env.KEYWORD_GROUPS_PATH || path.join(__dirname, 'config', 'keyword_groups.json');
const SCREENSHOTS_DIR = path.join(__dirname, 'data', 'screenshots');

function send(res, code, body, headers = {}) {
  res.writeHead(code, { 'content-type': 'text/plain; charset=utf-8', ...headers });
  res.end(body);
}

function sendJson(res, obj) {
  res.writeHead(200, { 'content-type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(obj));
}

function readFileSafe(p) {
  try { return fs.readFileSync(p); } catch (e) { return null; }
}

function contentType(p) {
  if (p.endsWith('.html')) return 'text/html; charset=utf-8';
  if (p.endsWith('.js')) return 'text/javascript; charset=utf-8';
  if (p.endsWith('.css')) return 'text/css; charset=utf-8';
  if (p.endsWith('.png')) return 'image/png';
  if (p.endsWith('.jpg') || p.endsWith('.jpeg')) return 'image/jpeg';
  if (p.endsWith('.webp')) return 'image/webp';
  return 'application/octet-stream';
}

function querySignals(minScore) {
  // Use sqlite3 CLI: `-json` outputs an array of objects.
  // NOTE: Keep query simple; fields match our schema.
  const sql = `
    SELECT item_id, source, url, title, text, metrics_json, score, created_at, fetched_at
    FROM items
    WHERE score IS NOT NULL AND score >= ${Number(minScore || 0)}
    ORDER BY score DESC, fetched_at DESC
    LIMIT 200;
  `;

  const out = execFileSync('sqlite3', ['-json', DB_PATH, sql], { encoding: 'utf-8' });
  let items = [];
  try { items = JSON.parse(out || '[]'); } catch (e) { items = []; }
  return items;
}

function queryItem(itemId) {
  const id = String(itemId || '').trim().toLowerCase();
  if (!/^[0-9a-f]{24}$/i.test(id)) return null;

  // Primary: direct SQL fetch
  const sql = `SELECT item_id, source, url, title, text, metrics_json, score, created_at, fetched_at FROM items WHERE item_id = '${id}' LIMIT 1;`;
  let out = '';
  try {
    out = execFileSync('sqlite3', ['-json', DB_PATH, sql], { encoding: 'utf-8' }) || '';
  } catch (e) {
    out = '';
  }

  try {
    const rows = JSON.parse(out || '[]');
    if (rows && rows[0]) return rows[0];
  } catch (e) {}

  // Fallback: query top items and find by id (works even if sqlite3 returns empty for some reason)
  try {
    const all = querySignals(0.0);
    const found = all.find(r => String(r.item_id || '').toLowerCase() === id);
    return found || null;
  } catch (e) {
    return null;
  }
}

const server = http.createServer((req, res) => {
  const u = new URL(req.url, `http://${req.headers.host}`);

  if (u.pathname === '/api/signals') {
    try {
      const minScore = parseFloat(u.searchParams.get('min_score') || '0');
      const items = querySignals(minScore);
      return sendJson(res, { from: 'sqlite', db_path: DB_PATH, items });
    } catch (e) {
      return sendJson(res, { from: 'sqlite', db_path: DB_PATH, items: [], error: String(e) });
    }
  }

  if (u.pathname === '/api/item') {
    try {
      const id = u.searchParams.get('id') || '';
      const item = queryItem(id);
      if (!item) return sendJson(res, { ok: false, error: 'not found' });

      let metrics = {};
      try { metrics = JSON.parse(item.metrics_json || '{}'); } catch (e) { metrics = {}; }
      const screenshots = Array.isArray(metrics.screenshots) ? metrics.screenshots : [];

      // Provide convenient URLs for rendering.
      const screenshot_urls = screenshots
        .map(p => String(p || ''))
        .filter(Boolean)
        // stored like data/screenshots/<id>/frame_01.png
        .map(p => p.replace(/^\.?\/?data\/?screenshots\//, ''))
        .map(p => `/screenshots/${p}`);

      return sendJson(res, { ok: true, item: { ...item, metrics, screenshots, screenshot_urls } });
    } catch (e) {
      return sendJson(res, { ok: false, error: String(e) });
    }
  }

  // Serve screenshot files from ./data/screenshots/<item_id>/frame_XX.png
  if (u.pathname.startsWith('/screenshots/')) {
    const rel = u.pathname.replace(/^\/screenshots\//, '').replace(/\.\.+/g, '.');
    const abs = path.join(SCREENSHOTS_DIR, rel);
    if (!abs.startsWith(SCREENSHOTS_DIR)) return send(res, 403, 'forbidden');

    const buf = readFileSafe(abs);
    if (!buf) return send(res, 404, 'not found');

    res.writeHead(200, { 'content-type': contentType(abs), 'cache-control': 'public, max-age=3600' });
    res.end(buf);
    return;
  }

  if (u.pathname === '/api/keywords' && req.method === 'GET') {
    const buf = readFileSafe(KEYWORDS_PATH);
    const text = buf ? buf.toString('utf-8') : '';
    return sendJson(res, { path: KEYWORDS_PATH, text });
  }

  if (u.pathname === '/api/keywords' && req.method === 'POST') {
    let body = '';
    req.on('data', (chunk) => { body += chunk; });
    req.on('end', () => {
      try {
        const j = JSON.parse(body || '{}');
        const text = String(j.text || '');
        // basic normalization: keep unix newlines, trim trailing spaces
        const normalized = text.split(/\r?\n/).map(l => l.replace(/\s+$/g,'')).join('\n').trim() + '\n';
        fs.mkdirSync(path.dirname(KEYWORDS_PATH), { recursive: true });
        fs.writeFileSync(KEYWORDS_PATH, normalized, 'utf-8');
        return sendJson(res, { ok: true, path: KEYWORDS_PATH, bytes: Buffer.byteLength(normalized, 'utf-8') });
      } catch (e) {
        return sendJson(res, { ok: false, error: String(e) });
      }
    });
    return;
  }

  // Keyword groups (preferred): { active: string, groups: { name: [keywords...] } }
  if (u.pathname === '/api/keyword-groups' && req.method === 'GET') {
    const buf = readFileSafe(KEYWORD_GROUPS_PATH);
    if (!buf) return sendJson(res, { ok: true, path: KEYWORD_GROUPS_PATH, active: 'default', groups: {} });
    try {
      const j = JSON.parse(buf.toString('utf-8') || '{}');
      return sendJson(res, { ok: true, path: KEYWORD_GROUPS_PATH, ...(j || {}) });
    } catch (e) {
      return sendJson(res, { ok: false, error: String(e), path: KEYWORD_GROUPS_PATH });
    }
  }

  if (u.pathname === '/api/keyword-groups' && req.method === 'POST') {
    let body = '';
    req.on('data', (chunk) => { body += chunk; });
    req.on('end', () => {
      try {
        const j = JSON.parse(body || '{}');
        const active = String(j.active || 'default').trim() || 'default';
        const groupsIn = (j.groups && typeof j.groups === 'object') ? j.groups : {};
        const groups = {};
        for (const [k, v] of Object.entries(groupsIn)) {
          const name = String(k).trim();
          if (!name) continue;
          const arr = Array.isArray(v) ? v : String(v || '').split(/\r?\n/);
          const kws = arr.map(x => String(x||'').trim()).filter(x => x && !x.startsWith('#'));
          groups[name] = kws;
        }
        const payload = { active, groups };
        fs.mkdirSync(path.dirname(KEYWORD_GROUPS_PATH), { recursive: true });
        fs.writeFileSync(KEYWORD_GROUPS_PATH, JSON.stringify(payload, null, 2) + '\n', 'utf-8');
        return sendJson(res, { ok: true, path: KEYWORD_GROUPS_PATH, active, group_count: Object.keys(groups).length });
      } catch (e) {
        return sendJson(res, { ok: false, error: String(e), path: KEYWORD_GROUPS_PATH });
      }
    });
    return;
  }

  // Static: / -> index.html
  let rel = u.pathname === '/' ? '/index.html' : u.pathname;
  rel = rel.replace(/\.\.+/g, '.');
  const abs = path.join(DASH_DIR, rel);

  if (!abs.startsWith(DASH_DIR)) return send(res, 403, 'forbidden');

  const buf = readFileSafe(abs);
  if (!buf) return send(res, 404, 'not found');

  res.writeHead(200, { 'content-type': contentType(abs) });
  res.end(buf);
});

server.listen(PORT, () => {
  console.log(`Dashboard: http://localhost:${PORT}`);
  console.log(`DB: ${DB_PATH}`);
});
