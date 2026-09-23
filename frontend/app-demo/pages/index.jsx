import React from 'react';
import ChatBox from '../components/ChatBox';

export default function Home() {
  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
      <header style={{ padding: '16px', background: '#020617', color: '#fff', borderBottom: '1px solid #1e293b' }}>
        <h1 style={{ fontSize: '18px', fontWeight: 600 }}>Conversational Agent Client (Protected by AI Firewall)</h1>
      </header>
      <div style={{ flex: 1 }}>
        <ChatBox />
      </div>
    </div>
  );
}
