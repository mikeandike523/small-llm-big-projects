const fs = require('node:fs');
const fsp = require('node:fs/promises');
const http = require('node:http');
const path = require('node:path');
const crypto = require('node:crypto');
const { URL } = require('node:url');

const PORT = Number(process.env.ARTIFACT_PORT || 0);
const CONTROL_PORT = Number(process.env.ARTIFACT_CONTROL_PORT || 0);
const SECRET = process.env.ARTIFACT_SECRET || '';
const HOST_SUFFIX = (process.env.ARTIFACT_HOST || 'artifact.localhost').toLowerCase().replace(/^\.+|\.+$/g, '');
const STATE_FILE = process.env.ARTIFACT_STATE_FILE || path.join(process.cwd(), '.slbp-artifacts.json');

let records = new Map();
let active = new Map();

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

async function serveDirectoryListing(res, directory, requestPath) {
  const entries = (await fsp.readdir(directory, { withFileTypes: true })).sort((a, b) => a.name.localeCompare(b.name));
  const prefix = requestPath.endsWith('/') ? requestPath : `${requestPath}/`;
  const rows = entries.map((entry) => {
    const name = `${entry.name}${entry.isDirectory() ? '/' : ''}`;
    const href = `${prefix}${encodeURIComponent(entry.name)}${entry.isDirectory() ? '/' : ''}`;
    return `<li><a href="${href}">${htmlEscape(name)}</a></li>`;
  }).join('');
  const body = `<!doctype html><meta charset="utf-8"><title>Index of ${htmlEscape(requestPath)}</title><h1>Index of ${htmlEscape(requestPath)}</h1><ul>${rows}</ul>`;
  res.writeHead(200, { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' });
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
  const stat = await fsp.stat(candidate).catch(() => null);
  if (!stat) return json(res, 404, { error: 'not_found' });
  if (stat.isDirectory()) {
    const index = path.join(candidate, 'index.html');
    if (fs.existsSync(index) && (await fsp.stat(index)).isFile()) return sendFile(res, index, req.method);
    try { return await serveDirectoryListing(res, candidate, pathname); } catch { return json(res, 404, { error: 'not_found' }); }
  }
  return sendFile(res, candidate, req.method);
}

async function sendFile(res, file, method) {
  const stat = await fsp.stat(file);
  res.writeHead(200, { 'content-type': contentType(file), 'content-length': stat.size, 'cache-control': 'no-store' });
  if (method === 'HEAD') return res.end();
  fs.createReadStream(file).on('error', () => res.destroy()).pipe(res);
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
    const directory = await fsp.realpath(payload.directory).catch(() => null);
    if (!directory || !(await fsp.stat(directory).catch(() => null))?.isDirectory()) return json(res, 400, { error: 'directory_not_found' });
    let id;
    do { id = crypto.randomBytes(15).toString('base64').replace(/[+/=]/g, '').toLowerCase(); } while (records.has(id));
    const record = { id, session_id: payload.session_id, directory, status: 'active', created_at: new Date().toISOString() };
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
  const publicServer = http.createServer((req, res) => void serveArtifact(req, res).catch((error) => { console.error(error); if (!res.headersSent) json(res, 500, { error: 'internal_error' }); }));
  const controlServer = http.createServer((req, res) => void control(req, res).catch((error) => { console.error(error); if (!res.headersSent) json(res, 500, { error: 'internal_error' }); }));
  publicServer.listen(PORT, '127.0.0.1', () => console.log(`[artifacts] Public server listening on http://127.0.0.1:${publicServer.address().port}`));
  controlServer.listen(CONTROL_PORT, '127.0.0.1', () => console.log(`[artifacts] Control server listening on http://127.0.0.1:${controlServer.address().port}`));
}

void main();
