import React, { useState } from 'react';
import { login } from '../lib/api';

export default function Login({ onLoggedIn }) {
  const [username, setUsername] = useState('security_admin');
  const [password, setPassword] = useState('security_admin_123');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      const data = await login(username, password);
      if (!(data.user.roles || []).includes('security_admin')) {
        throw new Error('Console cần tài khoản security_admin');
      }
      onLoggedIn(data.access_token, data.user.username);
    } catch (err) {
      setError(err.message || 'Không đăng nhập được. API đã chạy ở cổng 8000 chưa?');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-wrap">
      <form className="card login-card" onSubmit={submit}>
        <div className="brand">
          <div className="brand-logo">F</div>
          <div>
            <div className="brand-name">AI Firewall</div>
            <div className="brand-sub">Security Console v2</div>
          </div>
        </div>
        <div>
          <label>Tên đăng nhập</label>
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
        </div>
        <div>
          <label>Mật khẩu</label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
        </div>
        {error && <div className="alert">{error}</div>}
        <button className="btn green" disabled={busy}>{busy ? 'Đang đăng nhập...' : 'Đăng nhập'}</button>
        <div className="small muted">Tài khoản demo đã điền sẵn (security_admin). Đổi trong <code>api/dependencies/auth.py</code>.</div>
      </form>
    </div>
  );
}
