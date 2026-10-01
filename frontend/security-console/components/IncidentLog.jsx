import React, { useState } from 'react';

export default function IncidentLog({ 
  incidents = [], 
  selectedIncident = null, 
  onSelectIncident,
  filterLayer = null 
}) {
  const [search, setSearch] = useState('');
  const [activeFilter, setActiveFilter] = useState(filterLayer ? `L${filterLayer}` : 'ALL');

  const filtered = incidents.filter((inc) => {
    if (activeFilter === 'L1' && inc.blocked_by_layer !== 1) return false;
    if (activeFilter === 'L2' && inc.blocked_by_layer !== 2) return false;
    if (activeFilter === 'L3' && inc.blocked_by_layer !== 3) return false;
    if (activeFilter === 'L4' && inc.blocked_by_layer !== 4) return false;

    if (search.trim()) {
      const q = search.toLowerCase();
      const matchId = (inc.id || '').toLowerCase().includes(q);
      const matchText = (inc.input_text || '').toLowerCase().includes(q);
      const matchReason = (inc.reason || '').toLowerCase().includes(q);
      if (!matchId && !matchText && !matchReason) return false;
    }
    return true;
  });

  const getLayerName = (l) => {
    switch (l) {
      case 1: return 'Prefilter';
      case 2: return 'XGBoost';
      case 3: return 'DistilBERT';
      case 4: return 'Policy';
      default: return 'Firewall';
    }
  };

  return (
    <section className="incidents-panel">
      <div className="incidents-control-bar">
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div className="section-title">
            <svg viewBox="0 0 24 24" fill="none" strokeWidth="2" stroke="var(--cyan-400)" width="14" height="14">
              <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline>
            </svg>
            Live Threat Interceptions
          </div>
          <span style={{ background: 'rgba(255,255,255,0.08)', fontFamily: 'JetBrains Mono', fontSize: '0.7rem', padding: '2px 7px', borderRadius: '999px', color: 'var(--text-secondary)' }}>
            {filtered.length} EVENTS
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <input
            type="text"
            className="search-box"
            placeholder="Search prompts, reasons, IDs..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />

          <div className="filter-pill-group">
            {['ALL', 'L1', 'L2', 'L3', 'L4'].map((pill) => (
              <button
                key={pill}
                className={`filter-pill ${activeFilter === pill ? 'active' : ''}`}
                onClick={() => setActiveFilter(pill)}
              >
                {pill === 'ALL' ? 'ALL' : `${pill} ${pill === 'L1' ? 'Regex' : pill === 'L2' ? 'ML' : pill === 'L3' ? 'BERT' : 'Policy'}`}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="table-container">
        <table className="soc-table">
          <thead>
            <tr>
              <th style={{ width: '100px' }}>EVENT ID</th>
              <th style={{ width: '80px' }}>TIMESTAMP</th>
              <th style={{ width: '110px' }}>DEFENSE TIER</th>
              <th style={{ width: '170px' }}>TRIGGER VECTOR</th>
              <th style={{ width: '80px' }}>LATENCY</th>
              <th>INSPECTED PAYLOAD</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan="6">
                  <div style={{ textAlign: 'center', padding: '50px 20px', color: 'var(--text-muted)', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px' }}>
                    <div style={{ width: '48px', height: '48px', borderRadius: '50%', border: '1px dashed rgba(255,255,255,0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--cyan-400)' }}>
                      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <circle cx="12" cy="12" r="10"></circle>
                        <path d="m4.93 4.93 4.24 4.24"></path>
                        <path d="m14.83 9.17 4.24-4.24"></path>
                        <path d="m14.83 14.83 4.24 4.24"></path>
                        <path d="m9.17 14.83-4.24 4.24"></path>
                      </svg>
                    </div>
                    <div>Awaiting incoming network traffic. Use the simulator or chat API.</div>
                  </div>
                </td>
              </tr>
            ) : (
              filtered.map((inc) => {
                const timeStr = inc.timestamp ? inc.timestamp.split('T')[1]?.substring(0, 8) : '--:--:--';
                const layerClass = `layer-badge-l${inc.blocked_by_layer || 1}`;
                const isSelected = selectedIncident && selectedIncident.id === inc.id;

                return (
                  <tr
                    key={inc.id}
                    className={isSelected ? 'selected-row' : ''}
                    onClick={() => onSelectIncident && onSelectIncident(inc)}
                  >
                    <td className="col-id">{inc.id}</td>
                    <td className="col-time">{timeStr}</td>
                    <td>
                      <span className={`layer-badge ${layerClass}`}>
                        L{inc.blocked_by_layer} · {getLayerName(inc.blocked_by_layer)}
                      </span>
                    </td>
                    <td style={{ color: 'var(--text-secondary)', fontFamily: 'JetBrains Mono', fontSize: '0.73rem', maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={inc.reason}>
                      {inc.reason}
                    </td>
                    <td style={{ fontFamily: 'JetBrains Mono', fontSize: '0.72rem', color: 'var(--emerald-400)', whiteSpace: 'nowrap' }}>
                      {inc.total_latency_ms}ms
                    </td>
                    <td style={{ fontFamily: 'JetBrains Mono', color: 'var(--text-primary)', fontSize: '0.75rem', maxWidth: '320px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={inc.input_text}>
                      {inc.input_text}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
