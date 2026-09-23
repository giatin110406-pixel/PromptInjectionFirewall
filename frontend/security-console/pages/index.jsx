import React, { useState, useEffect } from 'react';
import IncidentLog from '../components/IncidentLog';
import CallGraph from '../components/CallGraph';

export default function SecurityConsole() {
  const [incidents, setIncidents] = useState([]);
  const [selectedIncident, setSelectedIncident] = useState(null);
  const [stats, setStats] = useState({ total_incidents: 0, avg_latency_ms: 0 });

  const fetchSecurityData = async () => {
    try {
      const [incRes, statsRes] = await Promise.all([
        fetch('http://127.0.0.1:8000/console/incidents'),
        fetch('http://127.0.0.1:8000/console/stats')
      ]);
      const incData = await incRes.json();
      const statsData = await statsRes.json();
      setIncidents(incData);
      setStats(statsData);
      if (incData.length && !selectedIncident) {
        setSelectedIncident(incData[0]);
      }
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    fetchSecurityData();
    const interval = setInterval(fetchSecurityData, 2000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div style={{ minHeight: '100vh', background: '#020617', color: '#f8fafc', fontFamily: 'sans-serif' }}>
      <header style={{ padding: '16px 24px', background: '#0f172a', borderBottom: '1px solid #1e293b', display: 'flex', justifyContent: 'space-between' }}>
        <h1 style={{ fontSize: '18px', fontWeight: 700 }}>Security Operations Center (SOC) Console</h1>
        <div style={{ fontSize: '14px', color: '#38bdf8' }}>Live Threat Monitoring</div>
      </header>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '16px', padding: '20px' }}>
        <div style={{ background: '#0f172a', padding: '16px', borderRadius: '8px', border: '1px solid #1e293b' }}>
          <div style={{ fontSize: '12px', color: '#94a3b8' }}>TOTAL ATTACKS INTERCEPTED</div>
          <div style={{ fontSize: '24px', fontWeight: 'bold', color: '#f43f5e' }}>{stats.total_incidents}</div>
        </div>
        <div style={{ background: '#0f172a', padding: '16px', borderRadius: '8px', border: '1px solid #1e293b' }}>
          <div style={{ fontSize: '12px', color: '#94a3b8' }}>AVERAGE INSPECTION LATENCY</div>
          <div style={{ fontSize: '24px', fontWeight: 'bold', color: '#38bdf8' }}>{stats.avg_latency_ms}ms</div>
        </div>
        <div style={{ background: '#0f172a', padding: '16px', borderRadius: '8px', border: '1px solid #1e293b' }}>
          <div style={{ fontSize: '12px', color: '#94a3b8' }}>LAYER 1 FAST-PATH RATIO</div>
          <div style={{ fontSize: '24px', fontWeight: 'bold', color: '#10b981' }}>
            {stats.total_incidents ? Math.round(((stats.by_layer?.['1'] || 0) / stats.total_incidents) * 100) : 0}%
          </div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: '20px', padding: '0 20px 20px 20px' }}>
        <div style={{ background: '#0f172a', borderRadius: '8px', border: '1px solid #1e293b', padding: '16px' }}>
          <h2 style={{ fontSize: '15px', marginBottom: '12px' }}>Real-time Incident Feed</h2>
          <IncidentLog incidents={incidents} onSelectIncident={setSelectedIncident} />
        </div>
        <div style={{ background: '#0f172a', borderRadius: '8px', border: '1px solid #1e293b', padding: '16px' }}>
          <h2 style={{ fontSize: '15px', marginBottom: '12px' }}>Defense Pipeline Inspector</h2>
          <CallGraph incident={selectedIncident} />
        </div>
      </div>
    </div>
  );
}
