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
