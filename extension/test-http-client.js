const assert = require('node:assert/strict');
const http = require('node:http');
const test = require('node:test');

const { requestJson } = require('./out/services/httpClient');

test('requestJson posts JSON without relying on global fetch', async () => {
  const originalFetch = globalThis.fetch;
  delete globalThis.fetch;

  const server = http.createServer((req, res) => {
    let body = '';
    req.setEncoding('utf8');
    req.on('data', chunk => {
      body += chunk;
    });
    req.on('end', () => {
      assert.equal(req.method, 'POST');
      assert.equal(req.headers.authorization, 'Bearer test-key');
      assert.deepEqual(JSON.parse(body), { message: 'hello' });
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ ok: true }));
    });
  });

  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));

  try {
    const address = server.address();
    const response = await requestJson(`http://127.0.0.1:${address.port}/v1/chat/completions`, {
      method: 'POST',
      headers: {
        authorization: 'Bearer test-key',
      },
      body: { message: 'hello' },
      timeoutMs: 1000,
    });

    assert.equal(response.ok, true);
    assert.equal(response.status, 200);
    assert.deepEqual(response.data, { ok: true });
  } finally {
    globalThis.fetch = originalFetch;
    await new Promise(resolve => server.close(resolve));
  }
});

test('requestJson resolves http://localhost via 127.0.0.1', async () => {
  const server = http.createServer((req, res) => {
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ ping: 1 }));
  });

  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));

  try {
    const address = server.address();
    const response = await requestJson(`http://localhost:${address.port}/health`, {
      method: 'GET',
      timeoutMs: 2000,
    });
    assert.equal(response.ok, true);
    assert.deepEqual(response.data, { ping: 1 });
  } finally {
    await new Promise(resolve => server.close(resolve));
  }
});
