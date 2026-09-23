import React from 'react';

export default function IncidentLog({ incidents = [], onSelectIncident }) {
  if (!incidents.length) {
    return <div style={{ color: '#94a3b8', padding: '24px', textAlign: 'center' }}>No threat incidents detected.</div>;
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', color: '#e2e8f0', fontSize: '13px' }}>
        <thead>
          <tr style={{ background: '#1e293b', borderBottom: '1px solid #334155', textAlign: 'left' }}>
            <th style={{ padding: '10px' }}>ID</th>
            <th style={{ padding: '10px' }}>Time</th>
            <th style={{ padding: '10px' }}>Layer</th>
            <th style={{ padding: '10px' }}>Reason</th>
            <th style={{ padding: '10px' }}>Latency</th>
            <th style={{ padding: '10px' }}>Input</th>
          </tr>
        </thead>
        <tbody>
          {incidents.map((inc) => (
            <tr
              key={inc.id}
              onClick={() => onSelectIncident && onSelectIncident(inc)}
              style={{ borderBottom: '1px solid #334155', cursor: 'pointer', hover: { background: '#1e293b' } }}
            >
              <td style={{ padding: '10px', color: '#38bdf8' }}>{inc.id}</td>
              <td style={{ padding: '10px' }}>{inc.timestamp.slice(11, 19)}</td>
              <td style={{ padding: '10px' }}>
                <span style={{
                  padding: '2px 6px',
                  borderRadius: '4px',
                  fontSize: '11px',
                  fontWeight: 'bold',
                  background: inc.blocked_by_layer === 1 ? '#e11d48' : '#d97706'
                }}>
                  L{inc.blocked_by_layer}
                </span>
              </td>
              <td style={{ padding: '10px', color: '#f87171' }}>{inc.reason}</td>
              <td style={{ padding: '10px' }}>{inc.total_latency_ms}ms</td>
              <td style={{ padding: '10px', maxWidth: '240px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {inc.input_text}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
