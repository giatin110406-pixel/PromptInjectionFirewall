import React from 'react';
import { DecisionBadge, LayerBadge } from './ui';
import FeedbackBar, { incidentToReport } from './FeedbackBar';
import { layerOf, DECISIONS } from '../lib/layers';

// Fields shown as key/value for a trace step, in this order, when present.
const FIELDS = ['reason', 'confidence', 'latency_ms', 'degraded', 'matched_view', 'matched_pattern', 'top_attack_similarity',
  'margin', 'check', 'tainted', 'review_id'];

function details(step) {
  const out = [];
  FIELDS.forEach((k) => {
    if (step[k] !== undefined && step[k] !== null && step[k] !== '') out.push([k, String(step[k])]);
  });
  const nested = step.details || {};
  // Layer 2 puts its scores in `details`; Layer 3 puts the judge's answer there; Layer 5 puts its findings there.
  ['max_window_score', 'threshold', 'windows', 'side', 'verdict', 'provider', 'category', 'cached'].forEach((k) => {
    if (nested[k] !== undefined && nested[k] !== null) out.push([k, String(nested[k])]);
  });
  if (nested.reason) out.push(['judge_reason', nested.reason]);
  if (step.findings && step.findings.length) out.push(['findings', step.findings.map((f) => f.type + (f.kind ? `:${f.kind}` : '')).join(', ')]);
  return out;
}

// The layers a request went through, in order. A layer that did not run (an earlier one decided) is simply absent.
export function TraceSteps({ trace = [] }) {
  if (trace.length === 0) return <div className="alert info">Không có dữ liệu từng bước.</div>;
  return (
    <>
      {trace.map((step, i) => {
        const meta = layerOf(Number(step.layer));
        return (
          <div className="trace-step" key={i} style={{ borderLeft: `14px solid ${meta.color}` }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center' }}>
              <strong style={{ fontFamily: 'var(--font-head)' }}>{meta.name}</strong>
              <DecisionBadge decision={step.decision in DECISIONS ? step.decision : step.decision === 'PASS' ? 'ALLOW' : step.decision} />
            </div>
            {typeof step.confidence === 'number' && (
              <div className="bar" style={{ marginTop: 8 }}><span style={{ width: `${Math.min(100, step.confidence * 100)}%` }} /></div>
            )}
            <dl className="kv">
              {details(step).map(([k, v]) => (<React.Fragment key={k}><dt>{k}</dt><dd>{v}</dd></React.Fragment>))}
            </dl>
          </div>
        );
      })}
    </>
  );
}

export default function ForensicModal({ incident, onClose }) {
  if (!incident) return null;
  const trace = incident.trace || [];
  return (
    <div className="overlay" onClick={onClose}>
      <aside className="drawer" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
          <h2>Chi tiết sự cố</h2>
          <button className="btn sm white" onClick={onClose}>Đóng ✕</button>
        </div>

        <div className="card">
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 10 }}>
            <DecisionBadge decision={incident.decision || 'BLOCK'} />
            <LayerBadge layer={incident.blocked_by_layer} />
            <span className="small muted">{incident.timestamp}</span>
          </div>
          <div className="small" style={{ fontWeight: 800 }}>Nội dung</div>
          <pre className="box mono">{incident.input_text}</pre>
          <dl className="kv">
            <dt>Lý do</dt><dd>{incident.reason}</dd>
            <dt>Phiên</dt><dd>{incident.session_id}</dd>
            <dt>Người dùng</dt><dd>{incident.user_id}</dd>
            <dt>Tổng độ trễ</dt><dd>{incident.total_latency_ms} ms</dd>
          </dl>
        </div>

        <FeedbackBar report={incidentToReport(incident)} />

        <h3>Đường đi qua các layer</h3>
        <TraceSteps trace={trace} />
      </aside>
    </div>
  );
}
