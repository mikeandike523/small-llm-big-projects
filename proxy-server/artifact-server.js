const fs = require('node:fs');
const fsp = require('node:fs/promises');
const http = require('node:http');
const path = require('node:path');
const crypto = require('node:crypto');
const { URL } = require('node:url');

const PORT = Number(process.env.ARTIFACT_PORT || 0);
const CONTROL_PORT = Number(process.env.ARTIFACT_CONTROL_PORT || 0);
const SECRET = process.env.ARTIFACT_SECRET || '';
const ARTIFACT_ORIGIN = process.env.ARTIFACT_ORIGIN || 'http://artifact.localhost';
const HOST_SUFFIX = new URL(ARTIFACT_ORIGIN).hostname.toLowerCase().replace(/^\.+|\.+$/g, '');
const STATE_FILE = process.env.ARTIFACT_STATE_FILE || path.join(process.cwd(), '.slbp-artifacts.json');
const MAX_FILE_BYTES = positiveInteger(process.env.ARTIFACT_MAX_FILE_BYTES, 100 * 1024 * 1024);
const MAX_DIRECTORY_ENTRIES = positiveInteger(process.env.ARTIFACT_MAX_DIRECTORY_ENTRIES, 10000);
const SERVE_TIMEOUT_MS = positiveInteger(process.env.ARTIFACT_SERVE_TIMEOUT_MS, 5000);
const ALLOWED_REWRITE_RULES = new Set(['SPA_INDEX']);

let records = new Map();
let active = new Map();

function positiveInteger(raw, fallback) {
  const value = Number(raw);
  return Number.isSafeInteger(value) && value > 0 ? value : fallback;
}

function json(res, status, value) {
  const body = JSON.stringify(value);
  res.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'content-length': Buffer.byteLength(body) });
  res.end(body);
}

async function saveState() {
  const data = JSON.stringify({ artifacts: [...records.values()] }, null, 2);
  const temp = `${STATE_FILE}.${process.pid}.tmp`;
  await fsp.writeFile(temp, data, 'utf8');
  await fsp.rename(temp, STATE_FILE);
}

async function loadState() {
  try {
    const parsed = JSON.parse(await fsp.readFile(STATE_FILE, 'utf8'));
    for (const item of parsed.artifacts || []) {
      if (item && typeof item.id === 'string') records.set(item.id, item);
    }
  } catch (error) {
    if (error.code !== 'ENOENT') console.error(`[artifacts] state load failed: ${error.message}`);
  }
  for (const item of records.values()) {
    if (item.status === 'active' && typeof item.directory === 'string') active.set(item.id, item);
  }
}

function authorized(req) {
  return SECRET && req.headers.authorization === `Bearer ${SECRET}`;
}

function validId(id) {
  return /^[a-z0-9]{20,64}$/.test(id);
}

function artifactIdFromHost(host) {
  const hostname = String(host || '').split(':')[0].toLowerCase().replace(/\.$/, '');
  const suffix = `.${HOST_SUFFIX.replace(/^\.+|\.+$/g, '')}`;
  if (!hostname.endsWith(suffix)) return null;
  const id = hostname.slice(0, -suffix.length);
  return validId(id) ? id : null;
}

function contentType(file) {
  const ext = path.extname(file).toLowerCase();
  return ({ '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.json': 'application/json; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif', '.ico': 'image/x-icon', '.txt': 'text/plain; charset=utf-8', '.wasm': 'application/wasm' })[ext] || 'application/octet-stream';
}

function htmlEscape(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
}

function metadataTag(stat) {
  // Deliberately metadata-based: serving an artifact must never hash an
  // arbitrarily large file just to create a cache validator.
  const size = stat.size.toString();
  const modified = typeof stat.mtimeNs === 'bigint' ? stat.mtimeNs.toString() : String(Math.trunc(stat.mtimeMs * 1e6));
  return `W/"${modified}-${size}"`;
}

function lastModified(stat) {
  return new Date(Number(stat.mtimeMs)).toUTCString();
}

function hasMatchingEtag(req, etag) {
  const header = req.headers['if-none-match'];
  if (!header) return false;
  const normalized = etag.replace(/^W\//, '');
  return header.split(',').some((candidate) => {
    const value = candidate.trim();
    return value === '*' || value.replace(/^W\//, '') === normalized;
  });
}

function sendNotModified(res, etag, modified) {
  res.writeHead(304, {
    etag,
    'last-modified': modified,
    'cache-control': 'no-cache',
  });
  res.end();
}

async function serveDirectoryListing(req, res, directory, requestPath) {
  const entries = [];
  const handle = await fsp.opendir(directory);
  try {
    for await (const entry of handle) {
      entries.push(entry);
      if (entries.length > MAX_DIRECTORY_ENTRIES) {
        return json(res, 413, { error: 'directory_listing_too_large', max_entries: MAX_DIRECTORY_ENTRIES });
      }
    }
  } finally {
    await handle.close().catch(() => {});
  }
  entries.sort((a, b) => a.name.localeCompare(b.name));
  const prefix = requestPath.endsWith('/') ? requestPath : `${requestPath}/`;
  const rows = entries.map((entry) => {
    const name = `${entry.name}${entry.isDirectory() ? '/' : ''}`;
    const href = `${prefix}${encodeURIComponent(entry.name)}${entry.isDirectory() ? '/' : ''}`;
    return `<li><a href="${href}">${htmlEscape(name)}</a></li>`;
  }).join('');
  const body = `<!doctype html><meta charset="utf-8"><title>Index of ${htmlEscape(requestPath)}</title><h1>Index of ${htmlEscape(requestPath)}</h1><ul>${rows}</ul>`;
  const stat = await fsp.stat(directory, { bigint: true });
  const etag = metadataTag(stat);
  const modified = lastModified(stat);
  if (hasMatchingEtag(req, etag)) return sendNotModified(res, etag, modified);
  res.writeHead(200, { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-cache', etag, 'last-modified': modified, 'content-length': Buffer.byteLength(body) });
  if (req.method === 'HEAD') return res.end();
  res.end(body);
}

async function serveArtifact(req, res) {
  if (req.method !== 'GET' && req.method !== 'HEAD') return json(res, 405, { error: 'method_not_allowed' });
  if (req.headers.upgrade) return json(res, 501, { error: 'websockets_not_supported' });
  const id = artifactIdFromHost(req.headers.host);
  if (!id) return json(res, 404, { error: 'artifact_not_found' });
  const record = records.get(id);
  if (!record || record.status === 'stopped') return json(res, 410, { error: 'artifact_gone' });
  if (!active.has(id)) return json(res, 410, { error: 'artifact_gone' });

  let pathname;
  try { pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname); } catch { return json(res, 400, { error: 'invalid_path' }); }
  const root = await fsp.realpath(record.directory).catch(() => null);
  if (!root) return json(res, 410, { error: 'artifact_directory_missing' });
  const candidate = path.resolve(root, `.${pathname}`);
  if (candidate !== root && !candidate.startsWith(`${root}${path.sep}`)) return json(res, 403, { error: 'path_forbidden' });
  let stat = await fsp.stat(candidate, { bigint: true }).catch(() => null);
  if (!stat && record.rewrite_rule === 'SPA_INDEX') {
    const index = path.join(root, 'index.html');
    stat = await fsp.stat(index, { bigint: true }).catch(() => null);
    if (stat?.isFile()) return sendFile(req, res, index, req.method);
    return json(res, 404, { error: 'not_found' });
  }
  if (!stat) return json(res, 404, { error: 'not_found' });
  if (stat.isDirectory()) {
    const index = path.join(candidate, 'index.html');
    if (fs.existsSync(index) && (await fsp.stat(index)).isFile()) return sendFile(req, res, index, req.method);
    if (record.rewrite_rule === 'SPA_INDEX') {
      const rootIndex = path.join(root, 'index.html');
      const rootIndexStat = await fsp.stat(rootIndex, { bigint: true }).catch(() => null);
      if (rootIndexStat?.isFile()) return sendFile(req, res, rootIndex, req.method);
    }
    try { return await serveDirectoryListing(req, res, candidate, pathname); } catch { return json(res, 404, { error: 'not_found' }); }
  }
  return sendFile(req, res, candidate, req.method);
}

async function sendFile(req, res, file, method) {
  const stat = await fsp.stat(file, { bigint: true });
  if (stat.size > BigInt(MAX_FILE_BYTES)) {
    return json(res, 413, { error: 'file_too_large', max_bytes: MAX_FILE_BYTES });
  }
  const etag = metadataTag(stat);
  const modified = lastModified(stat);
  if (hasMatchingEtag(req, etag)) return sendNotModified(res, etag, modified);
  res.writeHead(200, { 'content-type': contentType(file), 'content-length': stat.size.toString(), 'cache-control': 'no-cache', etag, 'last-modified': modified });
  if (method === 'HEAD') return res.end();
  fs.createReadStream(file).on('error', () => res.destroy()).pipe(res);
}

function handleArtifactRequest(req, res) {
  const timer = setTimeout(() => {
    if (!res.headersSent) {
      json(res, 504, { error: 'artifact_request_timeout' });
    } else {
      res.destroy();
    }
  }, SERVE_TIMEOUT_MS);
  void serveArtifact(req, res)
    .catch((error) => {
      console.error(error);
      if (!res.headersSent) json(res, 500, { error: 'internal_error' });
    })
    .finally(() => clearTimeout(timer));
}

async function control(req, res) {
  if (!authorized(req)) return json(res, 401, { error: 'unauthorized' });
  const url = new URL(req.url, 'http://localhost');
  if (req.method === 'GET' && url.pathname === '/health') return json(res, 200, { ok: true });
  if (req.method === 'GET' && url.pathname === '/artifacts') return json(res, 200, [...records.values()]);
  if (req.method === 'POST' && url.pathname === '/artifacts') {
    let body = '';
    for await (const chunk of req) body += chunk;
    let payload;
    try { payload = JSON.parse(body || '{}'); } catch { return json(res, 400, { error: 'invalid_json' }); }
    if (typeof payload.directory !== 'string' || typeof payload.session_id !== 'string') return json(res, 400, { error: 'directory_and_session_id_required' });
    if (payload.rewrite_rule !== undefined && payload.rewrite_rule !== null && (!Array.from(ALLOWED_REWRITE_RULES).includes(payload.rewrite_rule))) {
      return json(res, 400, { error: 'rewrite_rule_not_allowed', allowed_rewrite_rules: Array.from(ALLOWED_REWRITE_RULES) });
    }
    const directory = await fsp.realpath(payload.directory).catch(() => null);
    if (!directory || !(await fsp.stat(directory).catch(() => null))?.isDirectory()) return json(res, 400, { error: 'directory_not_found' });
    let id;
    do { id = crypto.randomBytes(15).toString('base64').replace(/[+/=]/g, '').toLowerCase(); } while (records.has(id));
    const record = { id, session_id: payload.session_id, directory, rewrite_rule: payload.rewrite_rule || null, status: 'active', created_at: new Date().toISOString() };
    records.set(id, record); active.set(id, record);
    await saveState();
    return json(res, 201, record);
  }
  const match = url.pathname.match(/^\/artifacts\/([a-z0-9]{20,64})$/);
  if (match && req.method === 'DELETE') {
    const record = records.get(match[1]);
    if (!record) return json(res, 404, { error: 'artifact_not_found' });
    record.status = 'stopped'; record.stopped_at = new Date().toISOString(); active.delete(record.id);
    await saveState();
    return json(res, 200, record);
  }
  return json(res, 404, { error: 'not_found' });
}

async function main() {
  await loadState();
  const publicServer = http.createServer(handleArtifactRequest);
  const controlServer = http.createServer((req, res) => void control(req, res).catch((error) => { console.error(error); if (!res.headersSent) json(res, 500, { error: 'internal_error' }); }));
  publicServer.listen(PORT, '127.0.0.1', () => console.log(`[artifacts] Public server listening on http://127.0.0.1:${publicServer.address().port}`));
  controlServer.listen(CONTROL_PORT, '127.0.0.1', () => console.log(`[artifacts] Control server listening on http://127.0.0.1:${controlServer.address().port}`));
}

void main();
