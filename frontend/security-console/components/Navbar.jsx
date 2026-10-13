import React from 'react';

const TABS = [
  { id: 'overview', label: 'Tổng quan' },
  { id: 'incidents', label: 'Sự cố' },
  { id: 'review', label: 'Hàng chờ duyệt' },
  { id: 'try', label: 'Thử prompt' },
  { id: 'lab', label: 'Phòng thử tấn công' },
];

export default function Navbar({ tab, onTab, isOnline, health, pending, user, onLogout, onClear }) {
  const degraded = health?.degraded_layers?.length || 0;
  const state = !isOnline ? 'off' : degraded ? 'warn' : 'ok';
  const text = !isOnline ? 'MẤT KẾT NỐI' : degraded ? `${degraded} LAYER LỖI` : 'HOẠT ĐỘNG';
  return (
    <header className="topbar">
      <div className="brand">
        <div className="brand-logo">F</div>
        <div>
          <div className="brand-name">AI Firewall</div>
          <div className="brand-sub">Security Console v2</div>
        </div>
      </div>

      <nav className="tabs">
        {TABS.map((t) => (
          <button key={t.id} className={`tab ${tab === t.id ? 'active' : ''}`} onClick={() => onTab(t.id)}>
            {t.label}
            {t.id === 'review' && pending > 0 && <span className="count">{pending}</span>}
          </button>
        ))}
      </nav>

      <div style={{ display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap' }}>
        <span className="status-pill">
          <span className={`dot ${state === 'ok' ? '' : state}`} />
          {text}
        </span>
        <span className="small" style={{ fontWeight: 700 }}>{user}</span>
        <button className="btn sm red" onClick={onClear} title="Xóa nhật ký sự cố (cho lần demo mới)">Xóa nhật ký</button>
        <button className="btn sm white" onClick={onLogout}>Đăng xuất</button>
      </div>
    </header>
  );
}
