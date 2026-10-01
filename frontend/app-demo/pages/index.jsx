import React from 'react';
import ChatBox from '../components/ChatBox';

export default function Home() {
  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', background: '#06090e' }}>
      <header style={{ padding: '14px 24px', background: '#0b1017', borderBottom: '1px solid rgba(255,255,255,0.07)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div style={{ width: '32px', height: '32px', borderRadius: '8px', background: 'linear-gradient(135deg, #0284c7, #2563eb)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontWeight: 800 }}>
            AF
          </div>
          <h1 style={{ fontSize: '15px', fontWeight: 700, color: '#f8fafc', letterSpacing: '-0.01em' }}>
            Conversational Agent Client <span style={{ fontSize: '11px', color: '#38bdf8', fontWeight: 600, background: 'rgba(56,189,248,0.1)', padding: '2px 8px', borderRadius: '999px', marginLeft: '6px' }}>Protected by AI Firewall</span>
          </h1>
        </div>
        <div style={{ fontSize: '12px', color: '#94a3b8' }}>
          Security Posture: <span style={{ color: '#34d399', fontWeight: 600 }}>Active Filtering</span>
        </div>
      </header>
      <div style={{ flex: 1, overflow: 'hidden' }}>
        <ChatBox />
      </div>
    </div>
  );
}
