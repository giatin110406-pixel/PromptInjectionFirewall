import React from 'react';

export default function Navbar({ onSimulate, onClearLogs, isOnline }) {
  return (
    <header className="soc-navbar">
      <div className="brand-section">
        <div className="brand-shield">
          <svg viewBox="0 0 24 24">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
          </svg>
        </div>
        <div>
          <div className="brand-title">
            <span className="app-name">AEGIS SECURITY CONSOLE</span>
            <span className="posture-badge">
              <span className="pulse-dot"></span>
              ACTIVE SURVEILLANCE
            </span>
          </div>
        </div>
      </div>

      <div className="header-actions">
        <div className="sync-status">
          <span>POLL:</span>
          <span style={{ color: 'var(--cyan-400)' }}>2.0s</span>
          <span>|</span>
          <span style={{ color: isOnline ? 'var(--emerald-400)' : 'var(--rose-400)' }}>
            {isOnline ? 'ONLINE' : 'OFFLINE'}
          </span>
        </div>
        <button className="btn-tactical" onClick={onSimulate} title="Fire simulated security probe">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
          </svg>
          Simulate Probe
        </button>
        <button className="btn-tactical btn-danger-subtle" onClick={onClearLogs} title="Purge incident telemetry store">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="3 6 5 6 21 6"></polyline>
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
          </svg>
          Purge Log
        </button>
      </div>
    </header>
  );
}
