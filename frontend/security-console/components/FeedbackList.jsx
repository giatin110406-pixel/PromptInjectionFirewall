import React from 'react';
import { Card, DecisionBadge } from './ui';
import { timeAgo } from '../lib/layers';

export default function FeedbackList({ items }) {
  return (
    <Card title="Phản hồi đã gửi" tint="pink" right={<span className="small">Dùng làm dữ liệu cho vòng huấn luyện sau: <code>python data/scripts/feedback_report.py --export</code></span>}>
      {items.length === 0 ? (
        <div className="small">Chưa có phản hồi. Mở một sự cố, hoặc dùng tab “Thử prompt”, rồi bấm “Đánh dấu chặn nhầm” hoặc “Đánh dấu bị lọt”.</div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Khi nào</th><th>Loại</th><th>Quyết định lúc đó</th><th>Nội dung</th><th>Ghi chú</th></tr></thead>
            <tbody>
              {items.map((f) => (
                <tr key={f.id} style={{ cursor: 'default' }}>
                  <td className="small" style={{ whiteSpace: 'nowrap' }}>{timeAgo(f.created_at)}</td>
                  <td><span className="badge" style={{ background: f.kind === 'false_positive' ? 'var(--green)' : 'var(--red)' }}>{f.kind === 'false_positive' ? 'chặn nhầm' : 'bị lọt'}</span></td>
                  <td><DecisionBadge decision={f.decision || '?'} /></td>
                  <td><div className="row-text">{f.text}</div></td>
                  <td className="small">{f.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
