import React, { useMemo, useState } from 'react';
import { Card, DecisionBadge, LayerBadge } from './ui';
import { timeAgo, shortReason } from '../lib/layers';

const DECISION_FILTERS = ['BLOCK', 'REVIEW', 'SANITIZE'];

export default function IncidentLog({ incidents, selectedId, onSelect, limit, title = 'Nhật ký sự cố' }) {
  const [decision, setDecision] = useState(null);
  const [layer, setLayer] = useState(null);

  const rows = useMemo(() => {
    const filtered = incidents.filter(
      (i) => (!decision || (i.decision || 'BLOCK') === decision) && (!layer || i.blocked_by_layer === layer)
    );
    return limit ? filtered.slice(0, limit) : filtered;
  }, [incidents, decision, layer, limit]);

  return (
    <Card
      title={title}
      right={
        !limit && (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {DECISION_FILTERS.map((d) => (
              <span key={d} className={`chip ${decision === d ? 'on' : ''}`} onClick={() => setDecision(decision === d ? null : d)}>{d}</span>
            ))}
            <span style={{ width: 8 }} />
            {[1, 2, 3, 4, 5].map((n) => (
              <span key={n} className={`chip ${layer === n ? 'on' : ''}`} onClick={() => setLayer(layer === n ? null : n)}>L{n}</span>
            ))}
          </div>
        )
      }
    >
      <div className="table-wrap">
        {rows.length === 0 ? (
          <div className="empty">Chưa có sự cố nào. Vào “Phòng thử tấn công” và bấm Chạy.</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Khi nào</th>
                <th>Quyết định</th>
                <th>Layer</th>
                <th>Nội dung</th>
                {!limit && <th>Lý do</th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((inc) => (
                <tr key={inc.id} className={selectedId === inc.id ? 'selected' : ''} onClick={() => onSelect(inc)}>
                  <td className="small" style={{ whiteSpace: 'nowrap' }}>{timeAgo(inc.timestamp)}</td>
                  <td><DecisionBadge decision={inc.decision || 'BLOCK'} /></td>
                  <td><LayerBadge layer={inc.blocked_by_layer} /></td>
                  <td><div className="row-text">{inc.input_text}</div></td>
                  {!limit && <td className="mono small" title={inc.reason}>{shortReason(inc.reason)}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </Card>
  );
}
