import React, { useState } from 'react';
import { Card, Json } from './ui';
import { api } from '../lib/api';
import { timeAgo } from '../lib/layers';

function PendingItem({ item, onDone }) {
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const decide = async (approve) => {
    setBusy(true);
    setError('');
    try {
      await api(`/chat/review/${item.id}/decision`, { method: 'POST', body: { approve, note: note || null } });
      onDone();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="review-card" tint={item.tainted ? 'pink' : undefined}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <h3>{item.action_type}</h3>
        <span className="small muted">{timeAgo(item.created_at)} · phiên {item.session_id}</span>
      </div>
      <div>
        <span className="badge" style={{ background: 'var(--orange)' }}>REVIEW</span>{' '}
        {item.tainted && <span className="badge" style={{ background: 'var(--red)' }}>PHIÊN BỊ TAINT</span>}
      </div>
      <div className="small"><strong>Vì sao cần duyệt:</strong> <span className="mono">{item.reason}</span></div>
      <Json value={item.payload} />
      <input placeholder="Ghi chú (tùy chọn)" value={note} onChange={(e) => setNote(e.target.value)} />
      {error && <div className="alert">{error}</div>}
      <div style={{ display: 'flex', gap: 10 }}>
        <button className="btn green" disabled={busy} onClick={() => decide(true)}>Duyệt</button>
        <button className="btn red" disabled={busy} onClick={() => decide(false)}>Từ chối</button>
      </div>
    </Card>
  );
}

export default function ReviewQueue({ pending, history, onChanged }) {
  return (
    <div className="grid two">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        <h2>Đang chờ duyệt ({pending.length})</h2>
        {pending.length === 0 && (
          <div className="card tint-green"><strong>Không có hành động nào chờ duyệt.</strong>
            <div className="small">Thử “Hoàn tiền lớn hợp lệ” hoặc “Đổi vai trò” trong Phòng thử tấn công.</div>
          </div>
        )}
        {pending.map((item) => <PendingItem key={item.id} item={item} onDone={onChanged} />)}
      </div>

      <Card title="Đã quyết định">
        {history.length === 0 && <div className="muted">Chưa có quyết định nào.</div>}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {history.map((item) => (
            <div key={item.id} className="step-result" style={{ background: item.status === 'approved' ? 'var(--green)' : 'var(--red)' }}>
              <strong>{item.action_type}</strong> · {item.status === 'approved' ? 'đã duyệt' : 'đã từ chối'} bởi {item.reviewer}
              {item.note && <div className="small">“{item.note}”</div>}
              <div className="small muted">{timeAgo(item.decided_at)}</div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
