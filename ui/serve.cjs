const http = require('http');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, './dist');
const PORT = 5173;

function setNoCacheHeaders(res) {
  res.setHeader(
    'Cache-Control',
    'no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0'
  );
  res.setHeader('Pragma', 'no-cache');
  res.setHeader('Expires', '0');
  res.setHeader('Surrogate-Control', 'no-store');

  // Disable conditional caching
  res.removeHeader('ETag');
  res.removeHeader('Last-Modified');
}

function getContentType(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  const types = {
    '.html': 'text/html',
    '.js': 'application/javascript',
    '.mjs': 'application/javascript',
    '.css': 'text/css',
    '.json': 'application/json',
    '.svg': 'image/svg+xml',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.webp': 'image/webp',
    '.ico': 'image/x-icon',
    '.map': 'application/json',
    '.txt': 'text/plain'
  };
  return types[ext] || 'application/octet-stream';
}

const server = http.createServer((req, res) => {
  setNoCacheHeaders(res);

  let filePath = path.join(ROOT, req.url.split('?')[0]);

  // Prevent directory traversal
  if (!filePath.startsWith(ROOT)) {
    res.writeHead(403);
    return res.end('Forbidden');
  }

  // Default to index.html
  if (req.url === '/' || req.url === '') {
    filePath = path.join(ROOT, 'index.html');
  }

  fs.stat(filePath, (err, stats) => {
    if (err || !stats.isFile()) {
      res.writeHead(404);
      return res.end('Not Found');
    }

    res.writeHead(200, {
      'Content-Type': getContentType(filePath)
    });

    fs.createReadStream(filePath).pipe(res);
  });
});

server.listen(PORT, () => {
  console.log(`Serving ${ROOT}`);
  console.log(`No caching enabled`);
  console.log(`http://localhost:${PORT}`);
});