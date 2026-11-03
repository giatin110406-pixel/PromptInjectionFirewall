import React, { useCallback, useEffect, useRef, useState } from 'react';
import Head from 'next/head';
import SCENARIOS from '../lib/demo_scenarios.json';
import { MANUAL_CASES } from '../lib/manualCases';
import { api, asRole } from '../lib/api';
import { DecisionBadge } from '../components/ui';
import ProvenanceChain, { LevelBadge, ReviewByBadge, actionLabel, vnd } from '../components/ProvenanceChain';
import AgentPipeline from '../components/AgentPipeline';

// Chat demo for the pitch: one firewall, three settings. Scenarios come from lib/demo_scenarios.json.
// Two modes (the toggle in the header). "Kịch bản": the agent is scripted in the browser (no LLM): it does what the scenario
// says, or naively follows the first destination it finds in a document the viewer pastes; every step goes through the real
// API unless the shield is switched off. "Agent thật": the chat goes to /agent/chat, where a tool-calling agent (a free-tier LLM,
// or its scripted stand-in) runs behind the same firewall, on a mock backend whose balances are shown on the right.

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

const CHANNEL = { email: 'email', web: 'web', document: 'document', review: 'review', tool_json: 'tool_json' };
const PROVIDERS = [['', 'Mặc định của server'], ['scripted', 'scripted (không mạng)'], ['groq', 'Groq (free tier)'], ['gemini', 'Gemini (free tier)'], ['local', 'Model cục bộ']];
const NEUTRAL_DOC_REQUEST = 'Mình vừa nhận được một tài liệu, bạn đọc rồi giúp mình xử lý nhé.';
const READ_ONLY_DEMO = process.env.NEXT_PUBLIC_DEMO_READ_ONLY === '1';

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
  // SSR and the first client render must agree. reset() generates the real unique ID after mount.
  const [session, setSession] = useState('demo-bank-initial');
  const [shield, setShield] = useState(true);
  const [messages, setMessages] = useState([]);
  const [timeline, setTimeline] = useState([]);
  const [level, setLevel] = useState('clean');
  const [input, setInput] = useState('');
  const [paste, setPaste] = useState('');
  const [showPaste, setShowPaste] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [real, setReal] = useState(!READ_ONLY_DEMO); // Hosted archive mode never calls the local Agent API.
  const [provider, setProvider] = useState('groq');
  const [backend, setBackend] = useState(null);
  const [agentResult, setAgentResult] = useState(null);
  const [agentProgress, setAgentProgress] = useState(null);
  const [requestText, setRequestText] = useState('');
  const progressPoll = useRef(null);
  const bodyRef = useRef(null);
  const sessionRef = useRef(session);
  const conf = SCENARIOS.domains[domain];

  const push = (m) => setMessages((list) => [...list, { key: Math.random(), ...m }]);
  const log = (call, decision, detail, ms) => setTimeline((list) => [{ key: Math.random(), call, decision, detail, ms }, ...list].slice(0, 30));

  const reset = useCallback((d = domain) => {
    if (progressPoll.current) {
      progressPoll.current.stopped = true;
      clearTimeout(progressPoll.current.timer);
      progressPoll.current = null;
    }
    const sid = newSession(d);
    sessionRef.current = sid;
    setSession(sid);
    setMessages([{ key: 'hello', role: 'bot', tag: SCENARIOS.domains[d].bot, text: SCENARIOS.domains[d].hello }]);
    setTimeline([]);
    setLevel('clean');
    setError('');
    setBackend(null);
    setAgentResult(null);
    setAgentProgress(null);
    setRequestText('');
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
        const sid = sessionRef.current;
        if (real) {
          const state = await api(`/agent/state/${sid}`, { token: await token() });
          if (sid !== sessionRef.current) return;
          setBackend(state.backend_state);
        }
        const items = await api('/chat/review?status=all', { token: await token() });
        if (sid !== sessionRef.current) return;
        setMessages((list) => list.map((m) => {
          const found = m.type === 'confirm' && items.find((i) => i.id === m.result.review_id);
          return found && found.status !== 'pending' ? { ...m, status: found.status } : m;
        }));
      } catch (e) { /* keep polling */ }
    }, 3000);
    return () => clearInterval(id);
  }, [messages]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---- "Agent thật": one customer message goes to /agent/chat; the steps it returns fill the same chat and timeline.
  async function agentReset(contents = []) {
    const out = await api('/agent/reset', { method: 'POST', token: await token(), body: { session_id: sessionRef.current, domain, contents } });
    setBackend(out.backend_state);
  }

  function showAgentResult(out) {
    for (const st of out.steps) {
      if (st.kind === 'firewall_input') {
        log('Tin nhắn khách', st.decision, st.reason, st.ms);
        if (st.judge) {
          const judgeStep = (st.trace || []).find((s) => s.layer === 3);
          log('Judge đánh giá lại đầu vào', st.decision,
            `${st.judge.model || st.judge.provider || 'Judge'}: ${st.judge.verdict || st.reason}`, judgeStep?.latency_ms);
        }
        if (st.decision === 'BLOCK' || st.decision === 'REVIEW') {
          push({ role: 'sys', tone: st.decision === 'BLOCK' ? 'bad' : 'warn', tag: `Firewall · L${st.layer}`,
            text: st.decision === 'BLOCK' ? 'Tin nhắn bị chặn trước khi tới agent.' : 'Tin nhắn bị giữ lại để kiểm tra; agent chưa nhận được.' });
        }
      } else if (st.kind === 'llm') {
        if (st.text) push({ role: 'bot', tag: conf.bot, text: st.text });
      } else if (st.kind === 'tool_read') {
        const fw = st.firewall;
        push({ role: 'attach', tag: `Agent đọc: ${st.tool}`, text: fw ? (fw.tainted ? 'Phát hiện chỉ thị trong nội dung: đã cắt khỏi phần agent nhận, phiên bị TAINT.' : 'Nội dung đã được đánh dấu là dữ liệu (datamark) trước khi tới agent.') : 'Không qua firewall.' });
        if (fw) { log(`Đọc ${st.tool}`, fw.decision, fw.tainted ? 'phát hiện chỉ thị: phiên bị TAINT' : 'phiên chuyển sang "đã đọc nội dung ngoài"', fw.ms); setLevel(fw.session_level); }
      } else if (st.kind === 'tool_action') {
        const action = { type: st.tool, payload: st.payload };
        push({ role: 'bot', tag: `${conf.bot} · gọi tool`, text: `${actionLabel(st.tool)}: ${describe(action)}` });
        if (st.check === 'firewall_off') {
          push({ role: 'sys', tone: 'bad', tag: 'Không có firewall', text: `Agent đã ${describe(action)}. Không ai được hỏi lại.` });
          continue;
        }
        setLevel(st.session_level || 'clean');
        log(`Hành động ${actionLabel(st.tool)}`, st.decision, st.reason, st.ms);
        if (st.decision === 'ALLOW') push({ role: 'sys', tone: 'ok', tag: 'Firewall · L4', text: `Đã thực hiện: ${describe(action)}.` });
        else if (st.decision === 'BLOCK') push({ role: 'sys', tone: 'bad', tag: 'Firewall · L4', text: `Đã chặn: ${st.check === 'taint' ? 'phiên vừa đọc tài liệu mang chỉ thị, lệnh nhạy cảm không được chạy.' : st.reason}` });
        else push({ type: 'confirm', action, result: { review_id: st.review_id, review_by: st.review_by, provenance: st.provenance, value_provenance: st.value_provenance }, status: 'pending' });
      } else if (st.kind === 'agent_error') {
        log(`Agent gọi sai: ${st.tool}`, 'SKIPPED', st.error, null);
        push({ role: 'sys', tone: 'warn', tag: 'Agent', text: `Agent gọi tool sai (${st.tool}): ${st.error}. Không liên quan tới firewall.` });
      }
    }
    if (out.error) {
      const message = out.reply || 'Dịch vụ LLM tạm thời không hoàn tất được yêu cầu.';
      setError(message);
      push({ role: 'sys', tone: 'warn', tag: out.error_code === 'rate_limit' ? 'Giới hạn LLM' : 'Yêu cầu chưa hoàn tất', text: message });
    }
    if (out.stopped === 'max_steps') push({ role: 'sys', tone: 'warn', tag: 'Agent', text: out.reply });
    setBackend(out.backend_state);
  }

  async function agentSend(text) {
    const sid = sessionRef.current;
    const bearer = await token();
    setRequestText(text);
    setAgentResult(null);
    setAgentProgress({ running: true, cursor: 0, events: [] });
    const poll = { stopped: false, cursor: 0, timer: null, events: [], runId: null };
    progressPoll.current = poll;
    const readProgress = async () => {
      if (poll.stopped || sessionRef.current !== sid) return;
      try {
        const update = await api(`/agent/progress/${encodeURIComponent(sid)}?after=${poll.cursor}`, { token: bearer, timeoutMs: 2500 });
        if (poll.stopped || sessionRef.current !== sid) return;
        if (poll.runId !== update.run_id) { poll.runId = update.run_id; poll.events = []; poll.cursor = 0; }
        poll.cursor = update.cursor || poll.cursor;
        poll.events = update.truncated ? update.events : [...poll.events, ...(update.events || [])];
        setAgentProgress({ ...update, events: poll.events.slice(-240) });
        if (update.running) poll.timer = setTimeout(readProgress, 450);
      } catch (_) {
        if (!poll.stopped && sessionRef.current === sid) poll.timer = setTimeout(readProgress, 700);
      }
    };
    poll.timer = setTimeout(readProgress, 300);
    try {
      const out = await api('/agent/chat', { method: 'POST', token: bearer,
        body: { session_id: sid, text, domain, mode: shield ? 'provenance' : 'off', provider: provider || null } });
      setAgentResult(out);
      setAgentProgress(out.progress || { running: false, cursor: 0, events: [] });
      showAgentResult(out);
    } catch (e) {
      setAgentResult({ error: e.message, error_code: 'provider_error', reply: e.message });
      throw e;
    } finally {
      poll.stopped = true;
      clearTimeout(poll.timer);
      if (progressPoll.current === poll) progressPoll.current = null;
    }
  }

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
    try { await fn(...args); } catch (e) {
      const message = e.message || String(e);
      setError(message);
      push({ role: 'sys', tone: 'warn', tag: 'Yêu cầu chưa hoàn tất', text: message });
    } finally { setBusy(false); }
  };

  // Each scenario starts a fresh session, so a taint left by the previous one cannot change its outcome.
  const runCase = guard(async (c) => {
    reset();
    push({ role: 'sys', tag: 'Kịch bản', text: c.title });
    const fx = c.fixture && MANUAL_CASES.find((x) => x.id === c.fixture);
    const d = c.doc || (fx && { id: fx.id, source: fx.source || 'email', text: fx.text });
    if (real) {            // the agent decides what to read and do; only the customer's message is scripted
      await agentReset(d ? [{ channel: CHANNEL[d.source] || 'document', text: d.text }] : []);
      push({ role: 'user', text: c.user });
      await agentSend(c.user);
      return;
    }
    if (c.user && !(await sendUser(c.user))) return;
    if (d) await readDoc(d);
    if (c.action) await runAction(c.action, c.agent_says);
  });

  const sendFree = guard(async () => {
    const text = input.trim();
    if (!text) return;
    setInput('');
    if (real) { push({ role: 'user', text }); await agentSend(text); return; }
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
    if (real) {
      await agentReset([{ channel: 'document', text }]);
      push({ role: 'attach', tag: 'Tài liệu đưa cho agent', text: text.length > 420 ? `${text.slice(0, 420)}…` : text });
      push({ role: 'user', text: NEUTRAL_DOC_REQUEST });
      await agentSend(NEUTRAL_DOC_REQUEST);
      return;
    }
    await readDoc({ id: 'tai-lieu-khan-gia', source: 'document', text });
    const action = guessAction(domain, text);
    if (action) await runAction(action, `Tài liệu có nhắc tới việc cần làm. Mình sẽ ${describe({ ...action, payload: { ...BASE_PAYLOAD[domain], ...action.payload } })}.`);
    else push({ role: 'bot', tag: conf.bot, text: 'Mình đã đọc tài liệu, không thấy việc gì cần làm.' });
  });

  const decide = guard(async (m, approve) => {
    if (real) {
      const out = await api('/agent/confirm', { method: 'POST', token: await token(), body: { session_id: sessionRef.current, review_id: m.result.review_id, approve } });
      log('Khách quyết định', approve ? 'ALLOW' : 'BLOCK', out.message, null);
      setBackend(out.backend_state);
      setMessages((list) => list.map((x) => (x.key === m.key ? { ...x, status: approve ? 'approved' : 'rejected' } : x)));
      return;
    }
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
        <button key={id} disabled={busy || READ_ONLY_DEMO} className={`tab ${domain === id ? 'active' : ''}`} onClick={() => setDomain(id)}>{d.name}</button>
          ))}
        </nav>
        <div className="tabs" role="group" aria-label="Chế độ agent">
          <button disabled={busy || READ_ONLY_DEMO} className={`tab ${!real ? 'active' : ''}`} onClick={() => { setReal(false); reset(); }}>Kịch bản</button>
          <button disabled={busy || READ_ONLY_DEMO} className={`tab ${real ? 'active' : ''}`} onClick={() => { setReal(true); reset(); }}>Agent thật</button>
        </div>
        {!READ_ONLY_DEMO && <a className="btn sm white" href="/" target="_blank" rel="noreferrer">Mở Security Console</a>}
      </header>

      <main className="page">
        {error && <div className="alert" role="alert">{error}</div>}
        {READ_ONLY_DEMO && <div className="readonly-notice"><strong>Bản demo phát lại</strong><span>Đang xem trace đã lưu từ firewall thật. Không gọi LLM, không gửi dữ liệu và không thực hiện giao dịch. Chat trực tiếp cần backend HTTPS riêng.</span></div>}
        {real && <AgentPipeline result={agentResult} progress={agentProgress} busy={busy} requestText={requestText} readOnly={READ_ONLY_DEMO} />}
        {!READ_ONLY_DEMO && <div className="demo-grid">
          <section className={`card chat ${shield ? '' : 'shield-off'}`}>
            <div className="chat-head">
              <strong>{conf.bot}</strong>
              <span className="small">đăng nhập: <span className="mono">{conf.login}</span>{real && ' · agent gọi tool qua /agent/chat'}</span>
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
                <button disabled={busy} className={`btn sm ${shield ? 'green' : 'red'}`} onClick={() => { setShield((s) => !s); reset(); }}>{shield ? 'Firewall: BẬT' : 'Firewall: TẮT'}</button>
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

            {real && (
              <section className="card">
                <div className="card-head"><h2>Agent thật</h2></div>
                <label className="small">Nhà cung cấp LLM</label>
                <select disabled={busy} value={provider} onChange={(e) => { setProvider(e.target.value); reset(); }}>
                  {PROVIDERS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
                </select>
                <div className="small" style={{ margin: '8px 0' }}>
                  Agent tự chọn tool. Hết lượt free tier thì chọn "scripted" hoặc chuyển về chế độ Kịch bản.
                </div>
                <h3>Backend giả lập</h3>
                {!backend && <div className="small muted">Chưa có phiên. Chạy một ca hoặc nhắn cho agent.</div>}
                {backend && (
                  <div className="small" style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                    {Object.entries(backend.balances || {}).map(([a, v]) => <div key={a}>Tài khoản <span className="mono">{a}</span>: <strong>{vnd(v)}</strong></div>)}
                    {Object.entries(backend.external_received || {}).map(([a, v]) => <div key={a} style={{ color: 'var(--red)' }}>Tiền đã tới <span className="mono">{a}</span>: <strong>{vnd(v)}</strong></div>)}
                    {Object.entries(backend.orders || {}).filter(([, o]) => o.refunded > 0).map(([id, o]) => <div key={id}>Đơn <span className="mono">{id}</span> đã hoàn <strong>{o.refunded}$</strong></div>)}
                    <div>Hành động đã thực hiện: <strong>{(backend.executed || []).length}</strong></div>
                    {(backend.executed || []).map((e, i) => <div key={i} className="mono">{actionLabel(e.type)}: {describe(e)}</div>)}
                  </div>
                )}
              </section>
            )}

            <section className="card tint-cyan">
              <div className="card-head">
                <h2>Firewall đang thấy gì</h2>
                <button disabled={busy} className="btn sm white" onClick={() => reset()}>Phiên mới</button>
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
        </div>}
      </main>
    </>
  );
}
