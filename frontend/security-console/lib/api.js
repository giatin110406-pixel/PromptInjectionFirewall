// Calls to the firewall API with a bearer token. The API needs a login for every route (IAM), so the console
// signs in first; the token lives in sessionStorage (closed with the tab).
const DEFAULT_API_BASE = process.env.NEXT_PUBLIC_DEMO_READ_ONLY === '1' ? '' : 'http://127.0.0.1:8000';
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? DEFAULT_API_BASE;

export class AuthError extends Error {}

async function requestJson(path, options, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_BASE}${path}`, { ...options, signal: controller.signal });
    const text = await res.text();
    let data = {};
    try { data = text ? JSON.parse(text) : {}; } catch (_) { /* keep the HTTP status for non-JSON failures */ }
    return { res, data };
  } catch (e) {
    if (controller.signal.aborted) {
      throw new Error('Hết thời gian chờ phản hồi. Hãy kiểm tra trạng thái tác vụ trước khi gửi lại.');
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

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
  const { res, data } = await requestJson('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  }, 10000);
  if (!res.ok) throw new AuthError('Sai tên đăng nhập hoặc mật khẩu');
  return data;
}

export async function api(path, { method = 'GET', body, token, timeoutMs } = {}) {
  const bearer = token || adminToken;
  const isForm = typeof FormData !== 'undefined' && body instanceof FormData;
  const { res, data } = await requestJson(path, {
    method,
    headers: { ...(!isForm ? { 'Content-Type': 'application/json' } : {}), ...(bearer ? { Authorization: `Bearer ${bearer}` } : {}) },
    body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
  }, timeoutMs ?? (path === '/agent/chat' ? 50000 : 20000));
  if (res.status === 401) throw new AuthError('Phiên đăng nhập hết hạn');
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
