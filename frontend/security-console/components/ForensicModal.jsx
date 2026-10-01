import React, { useState } from 'react';

export default function ForensicModal({ incident, onClose }) {
  const [copied, setCopied] = useState(false);

  if (!incident) return null;

  const handleCopy = () => {
    navigator.clipboard.writeText(incident.input_text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const getLayerName = (l) => {
    switch (l) {
      case 1: return 'Prefilter';
      case 2: return 'XGBoost';
      case 3: return 'DistilBERT';
      case 4: return 'Policy';
      default: return 'Firewall';
    }
  };

  const traceList = incident.trace || [];

  return (
    <div className="forensic-modal-backdrop" onClick={onClose}>
      <div className="forensic-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '0.92rem', fontWeight: 700 }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--cyan-400)" strokeWidth="2">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
            </svg>
            Forensic Incident Investigation: <span style={{ color: 'var(--cyan-400)', fontFamily: 'JetBrains Mono' }}>{incident.id}</span>
          </div>
          <button 
            onClick={onClose}
            style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', fontSize: '1.4rem', cursor: 'pointer', lineHeight: 1 }}
          >
            &times;
          </button>
        </div>

        <div className="modal-body">
          <div className="forensic-grid">
            <div className="forensic-metric-box">
              <div style={{ fontSize: '0.65rem', textTransform: 'uppercase', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '4px' }}>
                INTERCEPTING LAYER
              </div>
              <div style={{ fontFamily: 'JetBrains Mono', fontSize: '0.88rem', fontWeight: 700, color: 'var(--rose-400)' }}>
                Layer {incident.blocked_by_layer} ({getLayerName(incident.blocked_by_layer)})
              </div>
            </div>

            <div className="forensic-metric-box">
              <div style={{ fontSize: '0.65rem', textTransform: 'uppercase', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '4px' }}>
                INSPECTION TIME
              </div>
              <div style={{ fontFamily: 'JetBrains Mono', fontSize: '0.88rem', fontWeight: 700, color: 'var(--cyan-400)' }}>
                {incident.total_latency_ms}ms
              </div>
            </div>

            <div className="forensic-metric-box">
              <div style={{ fontSize: '0.65rem', textTransform: 'uppercase', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '4px' }}>
                CONFIDENCE SCORE
              </div>
              <div style={{ fontFamily: 'JetBrains Mono', fontSize: '0.88rem', fontWeight: 700, color: 'var(--amber-400)' }}>
                {incident.confidence !== undefined ? incident.confidence : '1.000'}
              </div>
            </div>

            <div className="forensic-metric-box">
              <div style={{ fontSize: '0.65rem', textTransform: 'uppercase', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '4px' }}>
                SESSION & USER
              </div>
              <div style={{ fontFamily: 'JetBrains Mono', fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-muted)' }}>
                {incident.session_id} // {incident.user_id}
              </div>
            </div>
          </div>

          <div>
            <div className="sandbox-label">Raw Intercepted Prompt</div>
            <div className="raw-payload-box" style={{ position: 'relative' }}>
              <button 
                onClick={handleCopy}
                style={{
                  position: 'absolute',
                  top: '8px',
                  right: '8px',
                  background: 'rgba(255,255,255,0.08)',
                  border: '1px solid var(--border-subtle)',
                  color: 'var(--text-muted)',
                  fontSize: '0.68rem',
                  padding: '3px 8px',
                  borderRadius: '4px',
                  cursor: 'pointer'
                }}
              >
                {copied ? 'Copied!' : 'Copy'}
              </button>
              {incident.input_text}
            </div>
          </div>

          <div>
            <div className="sandbox-label">Cascading Defense Trace Execution</div>
            <div>
              {traceList.length === 0 ? (
                <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>No granular step trace preserved.</div>
              ) : (
                traceList.map((step, idx) => {
                  const isStop = step.decision === 'BLOCK';
                  const badgeColor = isStop ? 'var(--rose-400)' : 'var(--emerald-400)';
                  return (
                    <div 
                      key={idx} 
                      className="trace-step-item"
                      style={{ borderLeft: `3px solid ${badgeColor}` }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                        <div style={{ width: '22px', height: '22px', borderRadius: '50%', background: 'rgba(255,255,255,0.08)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.68rem', fontWeight: 700 }}>
                          {idx + 1}
                        </div>
                        <div>
                          <div style={{ fontSize: '0.78rem', fontWeight: 700 }}>Defense Tier {step.layer || (idx + 1)}</div>
                          <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', fontFamily: 'JetBrains Mono' }}>
                            {step.reason || (isStop ? incident.reason : 'Evaluated - Passed')}
                          </div>
                        </div>
                      </div>

                      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', fontFamily: 'JetBrains Mono', fontSize: '0.72rem' }}>
                        <span style={{ color: badgeColor, fontWeight: 700 }}>{step.decision || 'BLOCK'}</span>
                        <span style={{ color: 'var(--text-muted)' }}>{step.latency_ms ? `${step.latency_ms}ms` : ''}</span>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
