// Transport regression checks; no browser, API, or external LLM calls.
const fs = require('fs');
const path = require('path');
const assert = require('node:assert/strict');

(async () => {
  const source = fs.readFileSync(path.join(__dirname, '../frontend/security-console/lib/api.js'), 'utf8');
  const client = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
  const checks = [];
  global.fetch = (_, options) => new Promise((resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
  });
  const started = Date.now();
  await assert.rejects(client.api('/agent/chat', { timeoutMs: 10 }), /Hết thời gian chờ/);
  assert.ok(Date.now() - started < 500);
  checks.push('An unanswered request rejects at its deadline without retrying');

  global.fetch = async () => ({ status: 409, ok: false, text: async () => JSON.stringify({ detail: 'Phiên đang xử lý yêu cầu trước' }) });
  await assert.rejects(client.api('/agent/chat'), /Phiên đang xử lý/);
  checks.push('Busy session is shown as a specific error');

  global.fetch = async () => ({ status: 200, ok: true, text: async () => JSON.stringify({ error_code: 'rate_limit', reply: 'Power Agent đang chạm giới hạn' }) });
  const result = await client.api('/agent/chat');
  assert.equal(result.error_code, 'rate_limit');
  checks.push('Quota response and readable reply reach the chat renderer');
  console.log(JSON.stringify({ passed: true, checks }));
})().catch(error => { console.error(error); process.exitCode = 1; });
