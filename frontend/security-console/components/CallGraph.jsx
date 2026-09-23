import React from 'react';

export default function CallGraph({ incident }) {
  if (!incident) {
    return <div style={{ color: '#64748b', padding: '20px' }}>Select an incident to view layer execution call graph.</div>;
  }

  const layers = [
    { id: 1, name: 'Layer 1: Regex & Vector Prefilter' },
    { id: 2, name: 'Layer 2: XGBoost Feature Classifier' },
    { id: 3, name: 'Layer 3: DistilBERT Deep Classifier' },
    { id: 4, name: 'Layer 4: Pydantic Policy Validator' },
  ];

  return (
    <div style={{ padding: '16px', background: '#0f172a', borderRadius: '8px', color: '#f8fafc' }}>
      <h3 style={{ fontSize: '14px', marginBottom: '12px', color: '#38bdf8' }}>Execution Trace: {incident.id}</h3>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {layers.map((l) => {
          const isBlocked = incident.blocked_by_layer === l.id;
          const isPassed = incident.blocked_by_layer > l.id;
          const isSkipped = incident.blocked_by_layer < l.id;

          let badgeColor = '#475569';
          let statusText = 'SKIPPED';
          if (isBlocked) {
            badgeColor = '#ef4444';
            statusText = 'BLOCKED INTERCEPT';
          } else if (isPassed) {
            badgeColor = '#10b981';
            statusText = 'ESCALATED / PASSED';
          }

          return (
            <div key={l.id} style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              padding: '10px 14px',
              borderRadius: '6px',
              background: '#1e293b',
              borderLeft: `4px solid ${badgeColor}`
            }}>
              <div>
                <div style={{ fontWeight: 600, fontSize: '13px' }}>{l.name}</div>
                {isBlocked && <div style={{ fontSize: '11px', color: '#fca5a5' }}>{incident.reason}</div>}
              </div>
              <span style={{ fontSize: '11px', fontWeight: 'bold', color: badgeColor }}>{statusText}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
