import React, { useState } from 'react';
import { actionLabel, vnd } from './ProvenanceChain';

const STATUS = {
  executed: ['Đã thực thi', 'green'], failed: ['Thực thi lỗi', 'red'],
  blocked: ['Đã chặn', 'red'], pending: ['Chờ duyệt', 'orange'],
  cancelled: ['Đã hủy', 'white'], approved: ['Đã xác nhận', 'cyan'],
};
const money = (value, unit) => unit === 'VND' ? vnd(value) : unit === 'USD' ? `${Number(value).toLocaleString('vi-VN')} USD` : value;

export default function BackendDashboard({ backend, busy, onRefresh, onReadAttachment }) {
  const [tab, setTab] = useState('state');
  const [selected, setSelected] = useState(null);
  const [texts, setTexts] = useState({});
  const [reading, setReading] = useState(null);
  const [readError, setReadError] = useState('');
  const transactions = backend?.transactions || [];
  const attachments = backend?.attachments || [];
  const latest = [...transactions].reverse();
  const receipt = transactions.find((t) => t.id === selected) || latest[0];
  return <section className="card backend-dashboard" aria-label="Trạng thái backend và biên nhận">
    <div className="card-head"><div><div className="pipeline-eyebrow">KẾT QUẢ THỰC TẾ CỦA PHIÊN DEMO</div><h2>Backend & giao dịch</h2></div>
      <button className="btn sm white" disabled={busy} onClick={onRefresh}>{backend ? 'Làm mới' : 'Khởi tạo'}</button></div>
    <p className="small muted">Dữ liệu thử trong bộ nhớ. Biên nhận chỉ ghi “đã thực thi” khi backend trả thành công.</p>
    <div className="backend-metrics">
      <div><strong>{backend?.executed?.length || 0}</strong><span>Đã thực thi</span></div>
      <div><strong>{transactions.filter((t) => t.status === 'pending').length}</strong><span>Chờ duyệt</span></div>
      <div><strong>{transactions.filter((t) => t.status === 'blocked').length}</strong><span>Đã chặn</span></div>
      <div><strong>{transactions.filter((t) => t.status === 'failed').length}</strong><span>Thực thi lỗi</span></div>
    </div>
    <div className="backend-tabs" role="group" aria-label="Xem dữ liệu backend">
      {[['state', 'Tài khoản / đơn'], ['ledger', `Nhật ký (${transactions.length})`], ['files', `Tài liệu (${attachments.length})`]].map(([id, label]) =>
        <button key={id} className={`pipeline-chip ${tab === id ? 'chosen' : ''}`} onClick={() => setTab(id)}>{label}</button>)}
    </div>
    {!backend && <div className="backend-empty">Khởi tạo phiên, gửi một yêu cầu hoặc đính kèm tài liệu để xem dữ liệu backend.</div>}
    {backend && tab === 'state' && <div className="backend-state">
      {Object.entries(backend.balances || {}).map(([id, balance]) => {
        const initial = backend.initial_state?.balances?.[id] ?? balance;
        return <div className="backend-account" key={id}><div className="small">Tài khoản <span className="mono">{id}</span></div><strong>{vnd(balance)}</strong>
          <div className="small muted">Đầu phiên: {vnd(initial)} · Thay đổi: {balance > initial ? '+' : ''}{vnd(balance - initial)}</div></div>;
      })}
      {Object.entries(backend.external_received || {}).map(([id, value]) => <div className="backend-account external" key={id}>
        <div className="small">Tài khoản ngoài <span className="mono">{id}</span></div><strong>Đã nhận {vnd(value)}</strong></div>)}
      {Object.entries(backend.orders || {}).map(([id, order]) => <div className="backend-order" key={id}>
        <div><strong className="mono">{id}</strong><span className="pipeline-badge tone-allow">{order.refunded ? 'Đã hoàn một phần / toàn bộ' : 'Chưa hoàn tiền'}</span></div>
        <div className="backend-order-values"><span>Giá trị đơn <b>{money(order.value, 'USD')}</b></span><span>Đã hoàn <b>{money(order.refunded, 'USD')}</b></span>
          <span>Còn có thể hoàn <b>{money(Math.max(0, order.value - order.refunded), 'USD')}</b></span></div>
        <div className="small muted">Trạng thái giao hàng: {order.status}</div></div>)}
      {backend.domain === 'work' && <div className="backend-order-values"><span>Email đã gửi <b>{backend.sent_emails || 0}</b></span>
        <span>File đã chia sẻ <b>{backend.shared_files?.length || 0}</b></span><span>Tin đã đăng <b>{backend.messages?.length || 0}</b></span></div>}
      {!transactions.length && <div className="small muted">Chưa có lệnh nào được thực thi. Số dư và đơn hàng vẫn ở trạng thái đầu phiên.</div>}
      {receipt && <div className="backend-latest"><span className={`badge ${STATUS[receipt.status]?.[1] || 'white'}`}>{STATUS[receipt.status]?.[0] || receipt.status}</span>
        <strong>{actionLabel(receipt.action)}</strong><div className="small">{receipt.message}</div>
        <button className="pipeline-chip" onClick={() => setTab('ledger')}>Xem biên nhận {receipt.id}</button></div>}
    </div>}
    {backend && tab === 'ledger' && <div className="backend-ledger">
      {!latest.length && <div className="backend-empty">Chưa có giao dịch. L4 ALLOW mới là cho phép; biên nhận thực thi sẽ xuất hiện sau khi backend xử lý.</div>}
      <div className="backend-receipt-list">{latest.map((tx) => <button key={tx.id} className={`backend-tx ${receipt?.id === tx.id ? 'selected' : ''}`} onClick={() => setSelected(tx.id)}>
        <span className={`badge ${STATUS[tx.status]?.[1] || 'white'}`}>{STATUS[tx.status]?.[0] || tx.status}</span>
        <strong>{actionLabel(tx.action)}</strong><span className="small mono">{tx.id}</span>
        <span className="small">{new Date(tx.at).toLocaleTimeString('vi-VN')}</span></button>)}</div>
      {receipt && <article className="backend-receipt"><strong>Biên nhận {receipt.id}</strong><p>{receipt.message}</p>
        {(receipt.changes || []).map((c, i) => <div className="backend-change" key={i}><span className="mono">{c.label}</span>
          <span>{money(c.before, c.unit)} <b>→</b> <strong>{money(c.after, c.unit)}</strong></span></div>)}
        {!receipt.changes?.length && <div className="small muted">Không có thay đổi số dư/đơn hàng trong bản ghi này.</div>}
        <details><summary>Payload thực tế</summary><pre className="box">{JSON.stringify(receipt.payload, null, 2)}</pre></details></article>}
    </div>}
    {backend && tab === 'files' && <div className="backend-files">
      {!attachments.length && <div className="backend-empty">Chọn “+ Tài liệu” trong khung chat để tải file, nhập link hoặc dán nội dung.</div>}
      {attachments.map((a, i) => <details className="backend-file" key={`${a.id}-${i}`}><summary><strong>{a.name}</strong> <span className="small">{a.read ? 'Đã được tool đọc' : 'Đã nạp · chưa đọc'}</span></summary>
        <div className="small mono">{a.id} · {a.format?.toUpperCase()} · {a.chars.toLocaleString('vi-VN')} ký tự · {a.bytes.toLocaleString('vi-VN')} byte</div>
        {a.url && <div className="small">Nguồn: {a.url}</div>}{a.notes?.map((note) => <div className="small muted" key={note}>{note}</div>)}
        <div className="small mono">SHA-256: {a.sha256}</div><pre className="box">{texts[a.id] || a.preview}</pre>
        {!texts[a.id] && <button className="pipeline-chip" disabled={busy || reading === a.id} onClick={async () => {
          setReading(a.id); setReadError('');
          try { const out = await onReadAttachment(a.id); setTexts((old) => ({ ...old, [a.id]: out.text })); }
          catch (e) { setReadError(e.message); } finally { setReading(null); }
        }}>{reading === a.id ? 'Đang mở…' : 'Xem toàn bộ văn bản trích xuất'}</button>}
        {readError && <div role="alert" className="small">{readError}</div>}
        <div className="small">Nội dung ngoài được firewall kiểm tra khi Agent gọi tool đọc. Việc đính kèm chưa phải kết quả ALLOW.</div></details>)}
    </div>}
  </section>;
}
