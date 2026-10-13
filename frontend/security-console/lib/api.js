// Calls to the firewall API with a bearer token. The API needs a login for every route (IAM), so the console
// signs in first; the token lives in sessionStorage (closed with the tab).
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'http://127.0.0.1:8000';

export class AuthError extends Error {}

let adminToken = null;
const roleTokens = {};

export function loadToken() {
  try {
    adminToken = sessionStorage.getItem('fw_token');
  } catch (e) {
    adminToken = null;
  }
  return adminToken;
}

export function saveToken(token) {
  adminToken = token;
  try {
    token ? sessionStorage.setItem('fw_token', token) : sessionStorage.removeItem('fw_token');
  } catch (e) {
    /* storage blocked: the token stays in memory */
  }
}

export async function login(username, password) {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) throw new AuthError('Sai tên đăng nhập hoặc mật khẩu');
  return res.json();
}

export async function api(path, { method = 'GET', body, token } = {}) {
  const bearer = token || adminToken;
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json', ...(bearer ? { Authorization: `Bearer ${bearer}` } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (res.status === 401) throw new AuthError('Phiên đăng nhập hết hạn');
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

// The attack lab acts as other demo users (a finance lead may refund, a normal user may transfer).
export async function asRole(username, password) {
  if (!roleTokens[username]) {
    roleTokens[username] = (await login(username, password)).access_token;
  }
  return roleTokens[username];
}
