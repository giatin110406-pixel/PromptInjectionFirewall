// One place that names the layers, so every component agrees on labels and colours.
export const LAYERS = {
  1: { key: 'L1', name: 'L1 Chữ ký', short: 'Regex + chỉ mục', color: 'var(--pink)' },
  2: { key: 'L2', name: 'L2 Phân loại', short: 'mDeBERTa', color: 'var(--yellow)' },
  3: { key: 'L3', name: 'L3 LLM judge', short: 'Phán xử ca chưa chắc', color: 'var(--violet)' },
  4: { key: 'L4', name: 'L4 Hành động', short: 'Chính sách + taint', color: 'var(--orange)' },
  5: { key: 'L5', name: 'L5 Đầu ra', short: 'Canary, PII, rò rỉ', color: 'var(--cyan)' },
};

export const DECISIONS = {
  ALLOW: { label: 'ALLOW', color: 'var(--green)' },
  SANITIZE: { label: 'SANITIZE', color: 'var(--yellow)' },
  REVIEW: { label: 'REVIEW', color: 'var(--orange)' },
  BLOCK: { label: 'BLOCK', color: 'var(--red)' },
  SKIPPED: { label: 'TẮT', color: '#d9d9d9' },
};

export const layerOf = (n) => LAYERS[n] || { key: `L${n}`, name: `Layer ${n}`, short: '', color: 'var(--white)' };

export function timeAgo(iso) {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return `${Math.floor(seconds)} giây trước`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} phút trước`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} giờ trước`;
  return new Date(iso).toLocaleString('vi-VN');
}

// Reasons can carry a whole regex ("regex_match:(?:bỏ\s+qua|...") or a long message: show the head, keep the rest in a tooltip.
export function shortReason(reason, max = 90) {
  const text = String(reason || '');
  if (text.startsWith('regex_match:')) return 'regex_match';
  if (text.includes('content:regex_match:')) return 'content:regex_match';
  return text.length > max ? `${text.slice(0, max)}…` : text;
}
