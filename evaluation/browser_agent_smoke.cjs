// Run against a locally running API (:8000) and console (:3001).
// Set PLAYWRIGHT_MODULE to the installed playwright package path when it is outside node_modules.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('fs');
const path = require('path');
const assert = require('node:assert/strict');
const scenarios = require('../frontend/security-console/lib/demo_scenarios.json');

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
  const errors = [];
  const checks = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    // Model loading can take a minute on the first API startup.
    let ready = false;
    for (let attempt = 0; attempt < 120; attempt++) {
      try {
        const health = await fetch('http://127.0.0.1:8000/health');
        if (health.ok) { ready = true; break; }
      } catch (_) { /* server still loading */ }
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    assert.ok(ready, 'API failed to start');
    await page.goto('http://127.0.0.1:3001/demo');
    await page.getByRole('button', { name: 'Agent thật', exact: true }).click();
    await page.locator('select').selectOption('scripted');

    async function runCase(domain, kind) {
      const conf = scenarios.domains[domain];
      await page.getByRole('button', { name: conf.name, exact: true }).click();
      const item = conf.cases.find(c => c.kind === kind);
      const request = page.waitForResponse(r => r.url().endsWith('/agent/chat') && r.request().method() === 'POST');
      await page.locator('.step-result').filter({ has: page.getByText(item.title, { exact: true }) })
        .getByRole('button', { name: 'Chạy ca này' }).click();
      const response = await request;
      assert.equal(response.status(), 200);
      const result = await response.json();
      await page.getByText('Đang xử lý…', { exact: true }).waitFor({ state: 'hidden' });
      assert.equal(await page.locator('.alert').filter({ hasText: 'Lỗi:' }).count(), 0);
      return result;
    }

    const legit = await runCase('bank', 'legit');
    assert.equal(legit.backend_state.balances['0071000555666'], 198000000);
    checks.push('bank legitimate transfer changes balance');

    await page.getByRole('button', { name: 'Firewall: BẬT', exact: true }).click();
    const off = await runCase('bank', 'attack');
    assert.equal(off.backend_state.external_received['000088041003'], 2400000);
    checks.push('bank attack without firewall transfers 2.4m');

    await page.getByRole('button', { name: 'Firewall: TẮT', exact: true }).click();
    const blocked = await runCase('bank', 'attack');
    assert.deepEqual(blocked.backend_state.external_received, {});
    assert.equal(blocked.backend_state.balances['0071000555666'], 200000000);
    checks.push('bank attack with firewall preserves balance');

    await runCase('bank', 'value');
    let response = page.waitForResponse(r => r.url().endsWith('/agent/confirm'));
    await page.getByRole('button', { name: 'Không phải tôi, hủy lệnh' }).click();
    assert.equal((await (await response).json()).executed, false);
    await page.getByText('Đang xử lý…', { exact: true }).waitFor({ state: 'hidden' });
    checks.push('customer cancellation executes nothing');

    await runCase('bank', 'value');
    response = page.waitForResponse(r => r.url().endsWith('/agent/confirm'));
    await page.getByRole('button', { name: 'Đúng, tôi xác nhận' }).click();
    assert.equal((await (await response).json()).executed, true);
    await page.getByText('Đang xử lý…', { exact: true }).waitFor({ state: 'hidden' });
    checks.push('customer approval executes held transfer');

    const shopHeld = await runCase('shop', 'value');
    assert.equal(shopHeld.pending_review.review_by, 'staff');
    const login = await page.request.post('http://127.0.0.1:8000/auth/login', {
      data: { username: 'finance_lead', password: 'finance_lead_123' },
    });
    const auth = await login.json();
    const decision = await page.request.post(`http://127.0.0.1:8000/chat/review/${shopHeld.pending_review.review_id}/decision`, {
      headers: { Authorization: `Bearer ${auth.access_token}` }, data: { approve: true, note: 'browser smoke' },
    });
    assert.equal(decision.status(), 200);
    await page.getByText('Đã xác nhận: lệnh được thực hiện.', { exact: true }).waitFor();
    await page.getByText('Hành động đã thực hiện:').filter({ hasText: '1' }).waitFor();
    checks.push('staff approval refreshes backend panel');

    for (const [domain, conf] of Object.entries(scenarios.domains)) {
      for (const item of conf.cases) {
        const result = await runCase(domain, item.kind);
        assert.equal(result.error, null);
        if (item.kind === 'legit') assert.ok(result.executed.length > 0);
        else assert.equal(result.executed.length, 0);
        checks.push(`${item.id} with firewall`);
      }
    }
    // Free text exercises the original Vietnamese L2 false positive through the UI.
    await page.getByRole('button', { name: scenarios.domains.bank.name, exact: true }).click();
    await page.getByRole('button', { name: 'Phiên mới', exact: true }).click();
    await page.getByPlaceholder('Nhắn cho trợ lý…').fill('Bạn xem giúp email mới nhất và xử lý giúp mình');
    response = page.waitForResponse(r => r.url().endsWith('/agent/chat'));
    await page.getByRole('button', { name: 'Gửi', exact: true }).click();
    const free = await (await response).json();
    assert.equal(free.steps.find(s => s.kind === 'firewall_input').decision, 'ALLOW');
    checks.push('plain Vietnamese read request passes through browser');

    assert.deepEqual(errors, []);
    const directory = path.resolve(__dirname, 'results');
    await page.screenshot({ path: path.join(directory, 'agent_browser_smoke.png'), fullPage: true });
    fs.writeFileSync(path.join(directory, 'agent_browser_smoke.json'), JSON.stringify({ checks, page_errors: errors }, null, 2));
    console.log(JSON.stringify({ passed: checks.length, page_errors: errors }));
  } catch (error) {
    await page.screenshot({ path: path.resolve(__dirname, '../artifacts/agent_browser_failure.png'), fullPage: true });
    throw error;
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
