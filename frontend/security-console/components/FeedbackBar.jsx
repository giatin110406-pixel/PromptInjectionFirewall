import React, { useState } from 'react';
import { api } from '../lib/api';

// "This block was wrong" / "this attack got through". The report is saved for the next training round and for a regression
// check; it never lets the text through automatically.
export function incidentToReport(incident) {
  const raw = String(incident.input_text || '');
  let mode = 'message';
  let text = raw;
  if (raw.startsWith('[context')) { mode = 'context'; text = raw.replace(/^\[context:[^\]]*\]\s*/, ''); }
  else if (raw.startsWith('[output]')) { mode = 'output'; text = raw.replace(/^\[output\]\s*/, ''); }
  else if (raw.startsWith('Action:')) { mode = 'action'; }
  return { text, mode, decision: incident.decision || 'BLOCK', layer: incident.blocked_by_layer, reason: incident.reason, session_id: incident.session_id };
}

export default function FeedbackBar({ report, onSent }) {
  const [note, setNote] = useState('');
  const [state, setState] = useState('');
  const wasAllowed = report.decision === 'ALLOW';
  const kind = wasAllowed ? 'missed_attack' : 'false_positive';

  const send = async () => {
    setState('...');
    try {
      const res = await api('/console/feedback', { method: 'POST', body: { ...report, kind, note } });
      setState(res.duplicate ? 'Đã có báo cáo này từ trước' : 'Đã ghi nhận, cảm ơn');
      onSent && onSent();
    } catch (e) {
      setState(`Lỗi: ${e.message}`);
    }
  };

  if (!report.text) return null;
  return (
    <div className="step-result" style={{ background: 'var(--paper)' }}>
      <div style={{ fontWeight: 800, marginBottom: 6 }}>{wasAllowed ? 'Kết quả này sai? Câu này là tấn công nhưng được cho qua.' : 'Kết quả này sai? Câu này hợp lệ nhưng bị chặn hoặc giữ lại.'}</div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <input style={{ flex: 1, minWidth: 180 }} placeholder="Ghi chú (tùy chọn)" value={note} onChange={(e) => setNote(e.target.value)} />
        <button className="btn sm pink" onClick={send}>{wasAllowed ? 'Đánh dấu bị lọt' : 'Đánh dấu chặn nhầm'}</button>
      </div>
      {state && <div className="small" style={{ marginTop: 6 }}>{state}</div>}
      <div className="small muted" style={{ marginTop: 4 }}>Chỉ để cải thiện dữ liệu huấn luyện; câu này không được tự động cho qua.</div>
    </div>
  );
}
