import React from 'react';
import { Card, DecisionBadge } from './ui';
import { LevelBadge, sourceLabel } from './ProvenanceChain';
import { timeAgo, shortReason } from '../lib/layers';

const at = (seconds) => timeAgo(new Date(seconds * 1000).toISOString());

function SessionCard({ s }) {
  const untrusted = Object.entries(s.values?.untrusted || {});
  const trusted = s.values?.trusted || [];
  return (
    <Card className="review-card" tint={s.level === 'tainted' ? 'pink' : undefined}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <h3 className="mono">{s.session_id}</h3>
        <LevelBadge level={s.level} />
      </div>

      <div>
        <div className="chain-label">Nội dung ngoài đã đọc ({(s.exposure_events || []).length})</div>
        <div className="timeline">
          {(s.exposure_events || []).slice(-5).map((e, i) => (
            <div key={i} className="step-result" style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <span>{sourceLabel(e.source)}{e.chunk_id ? <span className="mono"> “{e.chunk_id}”</span> : null}</span>
              {e.decision && <DecisionBadge decision={e.decision} />}
              <span className="small muted">{at(e.at)}</span>
            </div>
          ))}
        </div>
      </div>

      {s.tainted && (
        <div>
          <div className="chain-label">Vì sao bị TAINT</div>
          {(s.events || []).slice(-3).map((e, i) => (
            <div key={i} className="small mono" title={e.reason}>{sourceLabel(e.source)} · {shortReason(e.reason, 80)}</div>
          ))}
        </div>
      )}

      {s.session_risk && s.session_risk.turns > 0 && (
        <div className="small">
          <div className="chain-label">Rủi ro hội thoại ({s.session_risk.turns} lượt chat)</div>
          <div>
            Điểm trượt <span className="mono">{s.session_risk.turn_risk.toFixed(2)}</span> (giữ từ 0,70) · lượt lưng chừng liên tiếp{' '}
            <span className="mono">{s.session_risk.borderline_streak}</span> (giữ từ 3)
            {s.session_risk.review && <> · <DecisionBadge decision="REVIEW" /></>}
          </div>
        </div>
      )}

      {(untrusted.length > 0 || trusted.length > 0) && (
        <div className="small">
          <div className="chain-label">Giá trị đã ghi nhận</div>
          {trusted.length > 0 && <div>Khách tự gõ: <span className="mono">{trusted.slice(0, 6).join(', ')}</span></div>}
          {untrusted.length > 0 && (
            <div>Chỉ thấy trong nội dung ngoài: <span className="mono">{untrusted.slice(0, 6).map(([k]) => k).join(', ')}</span>
              {untrusted.length > 6 && ` +${untrusted.length - 6}`}</div>
          )}
        </div>
      )}
    </Card>
  );
}

export function SessionSummary({ sessions }) {
  const tainted = sessions.filter((s) => s.level === 'tainted');
  const exposed = sessions.filter((s) => s.level === 'exposed');
  return (
    <Card title="Phiên đang theo dõi" tint="cyan">
      {sessions.length === 0 && <div className="small">Chưa có phiên nào đọc nội dung ngoài. Khi một phiên đọc email, tài liệu hay trang web, lệnh nhạy cảm sau đó phải được xác nhận, dù nội dung có bị phát hiện là tấn công hay không.</div>}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 10 }}>
        <span className="badge" style={{ background: 'var(--red)' }}>{tainted.length} bị TAINT</span>
        <span className="badge" style={{ background: 'var(--orange)' }}>{exposed.length} đã đọc nội dung ngoài</span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {[...tainted, ...exposed].slice(0, 5).map((s) => (
          <div className="step-result" key={s.session_id} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
            <strong className="mono">{s.session_id}</strong>
            <LevelBadge level={s.level} />
          </div>
        ))}
      </div>
    </Card>
  );
}

export default function SessionList({ sessions }) {
  const order = { tainted: 0, exposed: 1, clean: 2 };
  const sorted = [...sessions].sort((a, b) => (order[a.level] ?? 3) - (order[b.level] ?? 3));
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <div className="card tint-yellow small">
        <strong>Ba mức của một phiên.</strong> <LevelBadge level="clean" /> chưa đọc nội dung ngoài: lệnh chạy theo luật thường.{' '}
        <LevelBadge level="exposed" /> đã đọc email, tài liệu hoặc trang web: lệnh tiền bạc, danh tính, quyền phải được xác nhận, trừ khi người nhận do khách tự gõ hoặc đã lưu trước.{' '}
        <LevelBadge level="tainted" /> nội dung đã đọc bị phát hiện mang chỉ thị: lệnh nhạy cảm bị chặn.
      </div>
      {sorted.length === 0 && <div className="card"><strong>Chưa có phiên nào.</strong> <span className="small">Mở trang <a href="/demo">Demo chatbot</a> và gửi một hóa đơn để thấy phiên chuyển mức.</span></div>}
      <div className="grid two">
        {sorted.map((s) => <SessionCard key={s.session_id} s={s} />)}
      </div>
    </div>
  );
}
