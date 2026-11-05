// Browser smoke against local demo. The only Agent call uses scripted + firewall off (no external LLM).
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const scenarios = require('../frontend/security-console/lib/demo_scenarios.json');
const dir = path.resolve('artifacts/attachment_ui_2026-11-05');
fs.mkdirSync(dir, { recursive: true });
const delay = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  const target = await (await fetch('http://127.0.0.1:9225/json/new?about:blank', { method: 'PUT' })).json();
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  const pending = new Map(); let seq = 0;
  const errors = [], agentRequests = [], checks = [];
  ws.onmessage = ({ data }) => {
    const event = JSON.parse(data);
    if (event.id && pending.has(event.id)) {
      const p = pending.get(event.id); pending.delete(event.id);
      event.error ? p.reject(new Error(event.error.message)) : p.resolve(event.result);
    }
    if (event.method === 'Runtime.exceptionThrown') errors.push(event.params.exceptionDetails.text);
    if (event.method === 'Network.requestWillBeSent' && event.params.request.method === 'POST' && event.params.request.url.endsWith('/agent/chat')) {
      const body = JSON.parse(event.params.request.postData || '{}');
      agentRequests.push({ provider: body.provider, mode: body.mode });
    }
  };
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++seq; pending.set(id, { resolve, reject }); ws.send(JSON.stringify({ id, method, params }));
  });
  const run = async expression => {
    const out = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (out.exceptionDetails) throw new Error(out.exceptionDetails.text);
    return out.result?.value;
  };
  const wait = async (expression, timeout = 20000) => {
    const start = Date.now();
    while (Date.now() - start < timeout) { if (await run(`Boolean(${expression})`)) return; await delay(200); }
    throw new Error('Timed out: ' + expression);
  };
  const click = async text => run(`(() => { const b = [...document.querySelectorAll('button')].find(x => x.textContent.trim() === ${JSON.stringify(text)}); if (!b) throw Error('Missing button'); b.click(); })()`);
  const fill = async (selector, value) => run(`(() => { const input = document.querySelector(${JSON.stringify(selector)}); const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; setter.call(input, ${JSON.stringify(value)}); input.dispatchEvent(new Event('input', {bubbles:true})); })()`);
  try {
    await send('Page.enable'); await send('Runtime.enable'); await send('Network.enable');
    await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });
    await send('Page.navigate', { url: 'http://127.0.0.1:3001/demo/' });
    await wait(`document.querySelector('.chat-body .msg.bot') && document.querySelector('.backend-dashboard')`);
    await click(scenarios.domains.shop.name);
    await wait(`document.querySelector('.chat-head strong')?.textContent === ${JSON.stringify(scenarios.domains.shop.bot)}`);
    await run(`(() => { const select = [...document.querySelectorAll('select')].find(s => [...s.options].some(o => o.value === 'scripted')); select.value = 'scripted'; select.dispatchEvent(new Event('change', {bubbles:true})); })()`);
    await delay(300);
    await click('Firewall: BẬT');
    await wait(`[...document.querySelectorAll('button')].some(b => b.textContent.trim() === 'Firewall: TẮT')`);
    assert.ok(await run(`[...document.querySelectorAll('select')].some(s => s.value === 'scripted')`));
    await fill('input[aria-label="Tin nhắn cho Agent"]', 'Hoàn tiền cho đơn DH20261031');
    await click('Gửi');
    await wait(`document.querySelector('.backend-dashboard')?.innerText.includes('45 USD') && document.querySelector('.chat-body')?.innerText.includes('Biên nhận TX-')`);
    checks.push('scripted refund has a successful backend receipt and 0 -> 45 USD state change');
    await click('+ Tài liệu');
    await wait(`document.querySelector('input[type=file]')`);
    const doc = await send('DOM.getDocument');
    const input = await send('DOM.querySelector', { nodeId: doc.root.nodeId, selector: 'input[type=file]' });
    await send('DOM.setFileInputFiles', { nodeId: input.nodeId, files: [path.resolve('frontend/security-console/public/attachment-samples/invoice-hidden.html')] });
    await wait(`document.querySelector('.attachment-selected')?.innerText.includes('invoice-hidden.html')`);
    await run(`[...document.querySelectorAll('button')].find(b => b.textContent.trim().startsWith('Đính kèm 1')).click()`);
    await wait(`document.querySelector('.attached-strip')?.innerText.includes('doc-1')`);
    assert.ok(await run(`document.querySelector('.backend-dashboard').innerText.includes('45 USD')`));
    checks.push('real HTML file upload preserves previous refund and session state');
    await click('Tài liệu (1)');
    await run(`document.querySelector('details.backend-file').open = true`);
    await click('Xem toàn bộ văn bản trích xuất');
    await wait(`document.querySelector('.backend-file pre')?.textContent.includes('ignore previous instructions')`);
    checks.push('full extracted HTML preserves the actual hidden injection comment');
    await click('Link web');
    await fill('#attachment-url', 'https://giatin110406-pixel.github.io/PromptInjectionFirewall/data/text-comparison.json');
    await click('Tải và đính kèm link');
    await wait(`document.querySelector('.attached-strip')?.innerText.includes('web-1')`, 18000);
    checks.push('public URL downloads actual JSON and is added as an untrusted web resource');
    assert.ok(agentRequests.length === 1 && agentRequests.every(r => r.provider === 'scripted' && r.mode === 'off'));
    assert.deepEqual(errors, []);
    await click('Đóng');
    const metrics = await send('Page.getLayoutMetrics');
    const png = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true,
      clip: { x: 0, y: 0, width: 1440, height: Math.min(metrics.cssContentSize.height, 2400), scale: 1 } });
    fs.writeFileSync(path.join(dir, 'desktop.png'), Buffer.from(png.data, 'base64'));
    await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
    await run('window.scrollTo(0,0)'); await delay(300);
    assert.ok(await run('document.documentElement.scrollWidth <= 392'), 'mobile layout overflows');
    const mobile = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.join(dir, 'mobile.png'), Buffer.from(mobile.data, 'base64'));
    checks.push('mobile layout has no horizontal body overflow');
    const report = { passed: true, checks, errors, agentRequests };
    fs.writeFileSync(path.join(dir, 'checks.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report, null, 2));
  } finally {
    try { await send('Browser.close'); } catch (_) { ws.close(); }
  }
})().catch(e => { console.error(e.message); process.exitCode = 1; });
