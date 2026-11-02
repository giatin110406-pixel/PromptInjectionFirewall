import React, { useCallback, useEffect, useRef, useState } from 'react';
import Head from 'next/head';
import SCENARIOS from '../lib/demo_scenarios.json';
import { MANUAL_CASES } from '../lib/manualCases';
import { api, asRole } from '../lib/api';
import { DecisionBadge } from '../components/ui';
import ProvenanceChain, { LevelBadge, ReviewByBadge, actionLabel, vnd } from '../components/ProvenanceChain';

// Chat demo for the pitch: one firewall, three settings. Scenarios come from lib/demo_scenarios.json.
// The "agent" is scripted (no LLM): it does what the scenario says, or naively follows the first destination it finds
// in a document the viewer pastes. Every step goes through the real API unless the shield is switched off.

const PASSWORDS = { support_agent: 'support_agent_123', khach_hang: 'khach_hang_123', nhan_vien: 'nhan_vien_123' };
const BASE_PAYLOAD = {
  shop: { user_id: 'cus_may_01' },
  bank: { user_id: 'demo_customer', from_account: '0071000555666', otp_verified: true },
  work: { user_id: 'emp_001' },
};
const KIND = { attack: { text: 'Tấn công', color: 'var(--red)' }, value: { text: 'Đổi người nhận', color: 'var(--orange)' }, legit: { text: 'Hợp lệ', color: 'var(--green)' } };

const ORDER_RE = /\b(?:DH|ORD|OD)-?\d{4,}\b|#\d{4,}/i;
const ACCOUNT_RE = /\b\d{6,16}\b/;
const EMAIL_RE = /[\w.+-]+@[\w-]+(?:\.[\w-]+)+/;

function parseVnd(text) {
  const t = text.toLowerCase();
  const m = t.match(/(\d+(?:[.,]\d+)?)\s*(triệu|tr|củ|k|nghìn|ngàn)\b/);
  if (m) return Math.round(parseFloat(m[1].replace(',', '.')) * ({ triệu: 1e6, tr: 1e6, củ: 1e6, k: 1e3, nghìn: 1e3, ngàn: 1e3 }[m[2]]));
  const d = t.match(/(\d{1,3}(?:\.\d{3})+)\s*(?:đ|đồng|vnd)/);
  return d ? parseInt(d[1].replace(/\./g, ''), 10) : null;
}

// What a naive agent would do with a text: the domain's main action, aimed at the first destination it finds.
function guessAction(domain, text) {
  if (domain === 'shop') {
    const order = (text.match(ORDER_RE) || [])[0];
    return order ? { type: 'refund', payload: { order_id: order.replace('#', ''), amount: 45, order_value: 60, reason: 'Theo yêu cầu' } } : null;
  }
  if (domain === 'bank') {
    const account = (text.replace(/(\d)[ .](?=\d{3})/g, '$1').match(ACCOUNT_RE) || [])[0];
    return account ? { type: 'transfer_money', payload: { to_account: account, bank_code: 'VCB', amount: Math.min(parseVnd(text) || 1000000, 50000000) } } : null;
  }
  const email = (text.match(EMAIL_RE) || [])[0];
  return email ? { type: 'data_access', payload: { resource: 'customer_list', query_scope: 'all', deliver_to: email } } : null;
}

function describe(action) {
  const p = action.payload;
  if (action.type === 'refund') return `hoàn ${p.amount}$ cho đơn ${p.order_id}`;
  if (action.type === 'transfer_money' || action.type === 'transfer') return `chuyển ${vnd(p.amount)} tới tài khoản ${p.to_account}`;
  if (action.type === 'data_access') return `truy xuất "${p.resource}" (phạm vi ${p.query_scope})${p.deliver_to ? ` và gửi tới ${p.deliver_to}` : ''}`;
  return actionLabel(action.type);
}

const newSession = (domain) => `demo-${domain}-${Math.random().toString(36).slice(2, 7)}`;

function Message({ m, onDecide }) {
  if (m.type === 'confirm') {
    const r = m.result;
    const mine = r.review_by === 'user';
    return (
      <div className="confirm-card">
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <strong>Lệnh đang chờ xác nhận</strong> <DecisionBadge decision="REVIEW" /> <ReviewByBadge by={r.review_by} />
        </div>
        <div className="small">Phiên này vừa đọc nội dung từ bên ngoài, nên firewall không để agent tự {describe(m.action)}.</div>
        <ProvenanceChain provenance={r.provenance} values={r.value_provenance} action={m.action.type} payload={m.action.payload} />
        {m.status === 'pending' && mine && (
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <button className="btn green" onClick={() => onDecide(m, true)}>Đúng, tôi xác nhận</button>
            <button className="btn red" onClick={() => onDecide(m, false)}>Không phải tôi, hủy lệnh</button>
          </div>
        )}
        {m.status === 'pending' && !mine && <div className="small alert info">Đang chờ nhân viên duyệt trên Security Console (tab Hàng chờ duyệt).</div>}
        {m.status === 'approved' && <div className="msg ok sys">Đã xác nhận: lệnh được thực hiện.</div>}
        {m.status === 'rejected' && <div className="msg bad sys">Đã hủy: lệnh không được thực hiện.</div>}
      </div>
    );
  }
  return (
    <div className={`msg ${m.role} ${m.tone || ''}`}>
      {m.tag && <div className="msg-tag">{m.tag}</div>}
      {m.text}
    </div>
  );
}

export default function Demo() {
  const [domain, setDomain] = useState('bank');
  const [session, setSession] = useState(() => newSession('bank'));
  const [shield, setShield] = useState(true);
  const [messages, setMessages] = useState([]);
  const [timeline, setTimeline] = useState([]);
  const [level, setLevel] = useState('clean');
  const [input, setInput] = useState('');
  const [paste, setPaste] = useState('');
  const [showPaste, setShowPaste] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const bodyRef = useRef(null);
  const sessionRef = useRef(session);
  const conf = SCENARIOS.domains[domain];

  const push = (m) => setMessages((list) => [...list, { key: Math.random(), ...m }]);
  const log = (call, decision, detail, ms) => setTimeline((list) => [{ key: Math.random(), call, decision, detail, ms }, ...list].slice(0, 30));

  const reset = useCallback((d = domain) => {
    const sid = newSession(d);
    sessionRef.current = sid;
    setSession(sid);
    setMessages([{ key: 'hello', role: 'bot', tag: SCENARIOS.domains[d].bot, text: SCENARIOS.domains[d].hello }]);
    setTimeline([]);
    setLevel('clean');
    setError('');
  }, [domain]);

  useEffect(() => { reset(domain); }, [domain]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { bodyRef.current?.scrollTo(0, bodyRef.current.scrollHeight); }, [messages]);

  const token = () => asRole(conf.login, PASSWORDS[conf.login]);

  // Staff reviews are decided on the console: poll them so the chat shows the outcome.
  useEffect(() => {
    const waiting = messages.filter((m) => m.type === 'confirm' && m.status === 'pending' && m.result.review_by !== 'user');
    if (!waiting.length) return undefined;
    const id = setInterval(async () => {
      try {
        const items = await api('/chat/review?status=all', { token: await token() });
        setMessages((list) => list.map((m) => {
          const found = m.type === 'confirm' && items.find((i) => i.id === m.result.review_id);
          return found && found.status !== 'pending' ? { ...m, status: found.status } : m;
        }));
      } catch (e) { /* keep polling */ }
    }, 3000);
    return () => clearInterval(id);
  }, [messages]); // eslint-disable-line react-hooks/exhaustive-deps

  async function sendUser(text) {
    push({ role: 'user', text });
    if (!shield) return true;
    const r = await api('/chat/message', { method: 'POST', token: await token(), body: { text, session_id: sessionRef.current } });
    log('Tin nhắn khách', r.decision, r.final_reason, r.total_latency_ms);
    if (r.decision === 'BLOCK' || r.decision === 'REVIEW') {
      push({ role: 'sys', tone: r.decision === 'BLOCK' ? 'bad' : 'warn', tag: `Firewall · L${r.stopped_at_layer}`,
        text: r.decision === 'BLOCK' ? 'Tin nhắn bị chặn trước khi tới agent.' : 'Tin nhắn bị giữ lại để kiểm tra; agent chưa nhận được.' });
      return false;
    }
    return true;
  }

  async function readDoc(d) {
    push({ role: 'attach', tag: `Agent đọc: ${d.source} "${d.id}"`, text: d.text.length > 420 ? `${d.text.slice(0, 420)}…` : d.text });
    if (!shield) return;
    const r = await api('/chat/context', { method: 'POST', token: await token(), body: { session_id: sessionRef.current, chunks: [{ id: d.id, source: d.source, text: d.text }] } });
    setLevel(r.session_level);
    const removed = (r.chunks || []).reduce((n, c) => n + ((c.removed_segments || []).length) + (c.decision === 'BLOCK' && !c.partial ? 1 : 0), 0);
    log(`Đọc ${d.source} "${d.id}"`, r.decision, r.session_tainted ? 'phát hiện chỉ thị: phiên bị TAINT' : 'không phát hiện gì: phiên chuyển sang "đã đọc nội dung ngoài"', r.total_latency_ms);
    if (r.session_tainted) push({ role: 'sys', tone: 'bad', tag: 'Firewall · Spotlighting', text: `Phát hiện chỉ thị gửi cho trợ lý trong tài liệu${removed ? `, đã cắt ${removed} đoạn` : ''}. Phiên bị đánh dấu TAINT.` });
  }

  async function runAction(action, says) {
    const full = { type: action.type, payload: { ...BASE_PAYLOAD[domain], ...action.payload } };
    push({ role: 'bot', tag: conf.bot, text: says || `Mình sẽ ${describe(full)}.` });
    if (!shield) {
      push({ role: 'sys', tone: 'bad', tag: 'Không có firewall', text: `Agent đã ${describe(full)}. Không ai được hỏi lại.` });
      return;
    }
    const r = await api('/chat/action', { method: 'POST', token: await token(), body: { action_type: full.type, payload: full.payload, session_id: sessionRef.current } });
    setLevel(r.session_level);
    log(`Hành động ${actionLabel(full.type)}`, r.decision, r.reason, r.latency_ms);
    if (r.decision === 'ALLOW') push({ role: 'sys', tone: 'ok', tag: 'Firewall · L4', text: `Đã thực hiện: ${describe(full)}.` });
    else if (r.decision === 'BLOCK') push({ role: 'sys', tone: 'bad', tag: 'Firewall · L4', text: `Đã chặn: ${r.check === 'taint' ? 'phiên vừa đọc tài liệu mang chỉ thị, lệnh nhạy cảm không được chạy.' : r.reason}` });
    else push({ type: 'confirm', action: full, result: r, status: 'pending' });
  }

  const guard = (fn) => async (...args) => {
    setBusy(true);
    setError('');
    try { await fn(...args); } catch (e) { setError(e.message || String(e)); } finally { setBusy(false); }
  };

  // Each scenario starts a fresh session, so a taint left by the previous one cannot change its outcome.
  const runCase = guard(async (c) => {
    reset();
    push({ role: 'sys', tag: 'Kịch bản', text: c.title });
    if (c.user && !(await sendUser(c.user))) return;
    const fx = c.fixture && MANUAL_CASES.find((x) => x.id === c.fixture);
    const d = c.doc || (fx && { id: fx.id, source: fx.source || 'email', text: fx.text });
    if (d) await readDoc(d);
    if (c.action) await runAction(c.action, c.agent_says);
  });

  const sendFree = guard(async () => {
    const text = input.trim();
    if (!text) return;
    setInput('');
    if (!(await sendUser(text))) return;
    const action = guessAction(domain, text);
    if (action) await runAction(action);
    else push({ role: 'bot', tag: conf.bot, text: 'Mình đã ghi nhận. Bạn có thể nhờ mình hoàn tiền, chuyển tiền hoặc tra cứu, hoặc đưa tài liệu để mình đọc.' });
  });

  const sendPaste = guard(async () => {
    const text = paste.trim();
    if (!text) return;
    setPaste('');
    setShowPaste(false);
    await readDoc({ id: 'tai-lieu-khan-gia', source: 'document', text });
    const action = guessAction(domain, text);
    if (action) await runAction(action, `Tài liệu có nhắc tới việc cần làm. Mình sẽ ${describe({ ...action, payload: { ...BASE_PAYLOAD[domain], ...action.payload } })}.`);
    else push({ role: 'bot', tag: conf.bot, text: 'Mình đã đọc tài liệu, không thấy việc gì cần làm.' });
  });

  const decide = guard(async (m, approve) => {
    await api(`/chat/review/${m.result.review_id}/decision`, { method: 'POST', token: await token(), body: { approve, note: approve ? 'khách xác nhận trong chat' : 'khách hủy trong chat' } });
    log('Khách quyết định', approve ? 'ALLOW' : 'BLOCK', approve ? 'xác nhận' : 'hủy lệnh', null);
    setMessages((list) => list.map((x) => (x.key === m.key ? { ...x, status: approve ? 'approved' : 'rejected' } : x)));
  });

  return (
    <>
      <Head><title>AI Firewall Demo</title></Head>
      <header className="topbar">
        <div className="brand">
          <div className="brand-logo">F</div>
          <div><div className="brand-name">AI Firewall</div><div className="brand-sub">Demo: một firewall, nhiều loại agent</div></div>
        </div>
        <nav className="tabs">
          {Object.entries(SCENARIOS.domains).map(([id, d]) => (
            <button key={id} className={`tab ${domain === id ? 'active' : ''}`} onClick={() => setDomain(id)}>{d.name}</button>
          ))}
        </nav>
        <a className="btn sm white" href="/" target="_blank" rel="noreferrer">Mở Security Console</a>
      </header>

      <main className="page">
        {error && <div className="alert">Lỗi: {error}. API ở cổng 8000 đã chạy chưa?</div>}
        <div className="demo-grid">
          <section className={`card chat ${shield ? '' : 'shield-off'}`}>
            <div className="chat-head">
              <strong>{conf.bot}</strong>
              <span className="small">đăng nhập: <span className="mono">{conf.login}</span></span>
            </div>
            <div className="chat-body" ref={bodyRef}>
              {messages.map((m) => <Message key={m.key} m={m} onDecide={decide} />)}
              {busy && <div className="small muted">Đang xử lý…</div>}
            </div>
            {showPaste && (
              <div style={{ padding: 12, borderTop: 'var(--border)', display: 'flex', flexDirection: 'column', gap: 8, background: 'var(--pink)' }}>
                <label>Dán một tài liệu (email, tin nhắn, trang web) cho agent đọc</label>
                <textarea rows={4} value={paste} onChange={(e) => setPaste(e.target.value)} placeholder="Agent sẽ ngây thơ làm theo số tài khoản / mã đơn / email đầu tiên nó thấy trong tài liệu." />
                <div style={{ display: 'flex', gap: 8 }}>
                  <button className="btn" disabled={busy} onClick={sendPaste}>Cho agent đọc</button>
                  <button className="btn white" onClick={() => setShowPaste(false)}>Đóng</button>
                </div>
              </div>
            )}
            <form className="chat-foot" onSubmit={(e) => { e.preventDefault(); sendFree(); }}>
              <button type="button" className="btn pink sm" onClick={() => setShowPaste((v) => !v)} title="Đưa tài liệu cho agent đọc">+ Tài liệu</button>
              <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Nhắn cho trợ lý…" />
              <button className="btn green" disabled={busy}>Gửi</button>
            </form>
          </section>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
            <section className="card">
              <div className="card-head">
                <h2>Kịch bản</h2>
                <button className={`btn sm ${shield ? 'green' : 'red'}`} onClick={() => setShield((s) => !s)}>{shield ? 'Firewall: BẬT' : 'Firewall: TẮT'}</button>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {conf.cases.map((c) => (
                  <div key={c.id} className="step-result" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                      <strong>{c.title}</strong>
                      <span className="badge" style={{ background: (KIND[c.kind] || {}).color }}>{(KIND[c.kind] || {}).text || c.kind}</span>
                    </div>
                    {c.explain && <div className="small">{c.explain}</div>}
                    <button className="btn sm cyan" disabled={busy} onClick={() => runCase(c)}>Chạy ca này</button>
                  </div>
                ))}
                {conf.cases.length < 3 && <div className="small muted">Các ca tấn công của bối cảnh này chưa có (xem docs/handoff_noi_dung_tan_cong_vi.md, H1). Có thể thử bằng nút “+ Tài liệu”.</div>}
              </div>
            </section>

            <section className="card tint-cyan">
              <div className="card-head">
                <h2>Firewall đang thấy gì</h2>
                <button className="btn sm white" onClick={() => reset()}>Phiên mới</button>
              </div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 10 }}>
                <span className="mono small">{session}</span> <LevelBadge level={level} />
              </div>
              <div className="timeline">
                {timeline.length === 0 && <div className="small">Chưa có gì. Chạy một kịch bản hoặc nhắn cho trợ lý.</div>}
                {timeline.map((t) => (
                  <div key={t.key} className="step-result" style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                    <DecisionBadge decision={t.decision} /> <strong>{t.call}</strong>
                    {t.ms !== null && t.ms !== undefined && <span className="small muted">{Math.round(t.ms)} ms</span>}
                    {t.detail && <div className="small mono" style={{ width: '100%' }}>{String(t.detail).slice(0, 120)}</div>}
                  </div>
                ))}
              </div>
            </section>
          </div>
        </div>
      </main>
    </>
  );
}
