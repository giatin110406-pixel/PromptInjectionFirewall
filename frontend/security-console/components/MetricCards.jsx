import React from 'react';

export default function MetricCards({ stats }) {
  const total = stats.total_incidents || 0;
  const byLayer = stats.by_layer || {};
  const l1 = byLayer['1'] || 0;
  const l2 = byLayer['2'] || 0;
  const l3 = byLayer['3'] || 0;
  const l4 = byLayer['4'] || 0;
  const avgLat = stats.avg_latency_ms || 0;

  const l1Ratio = total > 0 ? Math.round((l1 / total) * 100) : 0;

  let postureText = 'NOMINAL';
  let postureColor = 'var(--emerald-400)';
  if (total > 15) {
    postureText = 'DEFCON 3';
    postureColor = 'var(--rose-400)';
  } else if (total > 0) {
    postureText = 'ELEVATED';
    postureColor = 'var(--amber-400)';
  }

  return (
    <section className="kpi-row">
      <div className="kpi-card">
        <div className="kpi-header">
          <span className="kpi-title">Attacks Intercepted</span>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--rose-400)" strokeWidth="2">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
          </svg>
        </div>
        <div className="kpi-value" style={{ color: 'var(--rose-400)' }}>{total}</div>
        <div className="kpi-subtext">Total malicious queries caught</div>
        <div className="kpi-spark-bar">
          <div className="kpi-spark-fill" style={{ width: '100%', background: 'var(--rose-500)' }}></div>
        </div>
      </div>

      <div className="kpi-card">
        <div className="kpi-header">
          <span class="kpi-title">Layer 1 Offload</span>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--emerald-400)" strokeWidth="2">
            <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
          </svg>
        </div>
        <div className="kpi-value" style={{ color: 'var(--emerald-400)' }}>{l1Ratio}%</div>
        <div className="kpi-subtext">Fast-path regex & vector prefilter</div>
        <div className="kpi-spark-bar">
          <div className="kpi-spark-fill" style={{ width: `${l1Ratio}%`, background: 'var(--emerald-500)' }}></div>
        </div>
      </div>

      <div className="kpi-card">
        <div className="kpi-header">
          <span className="kpi-title">Mean Latency</span>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--cyan-400)" strokeWidth="2">
            <circle cx="12" cy="12" r="10"></circle>
            <polyline points="12 6 12 12 16 14"></polyline>
          </svg>
        </div>
        <div className="kpi-value" style={{ color: 'var(--cyan-400)' }}>{avgLat.toFixed(2)}ms</div>
        <div className="kpi-subtext">Multi-layer evaluation speed</div>
        <div className="kpi-spark-bar">
          <div className="kpi-spark-fill" style={{ width: '85%', background: 'var(--cyan-500)' }}></div>
        </div>
      </div>

      <div className="kpi-card">
        <div className="kpi-header">
          <span className="kpi-title">Defense Posture</span>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={postureColor} strokeWidth="2">
            <circle cx="12" cy="12" r="2"></circle>
            <path d="M16.24 7.76a6 6 0 0 1 0 8.49m-8.48-.01a6 6 0 0 1 0-8.49m11.31-2.82a10 10 0 0 1 0 14.14m-14.14 0a10 10 0 0 1 0-14.14"></path>
          </svg>
        </div>
        <div className="kpi-value" style={{ fontSize: '1.25rem', color: postureColor, marginTop: '6px' }}>
          {postureText}
        </div>
        <div className="kpi-subtext">4 defense tiers active</div>
        <div className="kpi-spark-bar">
          <div className="kpi-spark-fill" style={{ width: '100%', background: postureColor }}></div>
        </div>
      </div>

      <div className="kpi-card">
        <div className="kpi-header">
          <span className="kpi-title">Layer Distribution</span>
          <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', fontFamily: 'JetBrains Mono' }}>
            L1 / L2 / L3 / L4
          </span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '4px', fontFamily: 'JetBrains Mono', fontSize: '0.8rem' }}>
          <span style={{ color: 'var(--rose-400)' }}>L1: <b>{l1}</b></span>
          <span style={{ color: 'var(--amber-400)' }}>L2: <b>{l2}</b></span>
          <span style={{ color: 'var(--violet-400)' }}>L3: <b>{l3}</b></span>
          <span style={{ color: 'var(--cyan-400)' }}>L4: <b>{l4}</b></span>
        </div>
        <div style={{ height: '8px', display: 'flex', borderRadius: '4px', overflow: 'hidden', marginTop: '14px', background: 'rgba(255,255,255,0.06)' }}>
          <div style={{ width: total ? `${(l1/total)*100}%` : '25%', background: 'var(--rose-500)', transition: 'width 0.4s' }}></div>
          <div style={{ width: total ? `${(l2/total)*100}%` : '25%', background: 'var(--amber-500)', transition: 'width 0.4s' }}></div>
          <div style={{ width: total ? `${(l3/total)*100}%` : '25%', background: 'var(--violet-500)', transition: 'width 0.4s' }}></div>
          <div style={{ width: total ? `${(l4/total)*100}%` : '25%', background: 'var(--cyan-500)', transition: 'width 0.4s' }}></div>
        </div>
        <div className="kpi-subtext" style={{ marginTop: '8px' }}>Cascading interception breakdown</div>
      </div>
    </section>
  );
}
