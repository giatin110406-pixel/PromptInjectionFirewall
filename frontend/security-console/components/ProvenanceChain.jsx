import React from 'react';

// Where an action's arguments came from: untrusted sources read by the session -> each destination value -> the action.
// Used by the review queue (staff) and the chat demo (the customer confirms their own transfer).

const SOURCE_LABEL = { email: 'Email', rag: 'Tài liệu', web: 'Trang web', tool: 'Kết quả tool', document: 'Tài liệu', file: 'Tệp',
  conversation: 'Hội thoại rủi ro' };
const FIELD_LABEL = { to_account: 'Tài khoản nhận', order_id: 'Mã đơn', target_account: 'Tài khoản đích', amount: 'Số tiền',
  to: 'Người nhận', cc: 'CC', url: 'Địa chỉ gọi tới', target: 'Kênh nhận', share_with: 'Chia sẻ với', voucher_code: 'Mã voucher' };
const ACTION_LABEL = { transfer_money: 'Chuyển tiền', transfer: 'Chuyển tiền', refund: 'Hoàn tiền', account_recovery: 'Khôi phục tài khoản',
  password_reset: 'Đặt lại mật khẩu', role_escalation: 'Nâng quyền', access_control: 'Đổi quyền truy cập', data_access: 'Truy cập dữ liệu',
  send_email: 'Gửi email', http_request: 'Gọi URL', post_message: 'Gửi tin nhắn', share_file: 'Chia sẻ tệp',
  voucher_apply: 'Áp voucher', coupon_apply: 'Áp mã giảm giá' };

export const sourceLabel = (s) => SOURCE_LABEL[s] || s;
export const actionLabel = (a) => ACTION_LABEL[a] || a;
export const vnd = (n) => (n === undefined || n === null || n === '' ? '' : `${Number(n).toLocaleString('vi-VN')}đ`);

const where = (ref) => `${sourceLabel(ref.source)}${ref.chunk_id ? ` "${ref.chunk_id}"` : ''}`;

export function originText(v) {
  const first = (v.seen_in || [])[0];
  if (v.origin === 'trusted') {
    if (first?.source === 'trusted_book') return 'người nhận đã lưu trước đó';
    if (first?.source === 'egress_allowlist') return 'địa chỉ nội bộ được phép';
    return 'do chính khách hàng gõ';
  }
  if (v.origin === 'untrusted') return `chỉ xuất hiện trong ${(v.seen_in || []).map(where).join(', ')}`;
  if (v.note === 'too_short_to_trust') return 'quá ngắn để đối chiếu';
  return 'không thấy ở đâu trong phiên (agent tự đặt ra?)';
}

const ORIGIN_TONE = { trusted: 'var(--green)', untrusted: 'var(--red)', unknown: 'var(--orange)' };

export default function ProvenanceChain({ provenance = [], values = [], action, payload = {} }) {
  const deciding = values.filter((v) => v.decides);
  const amount = values.find((v) => v.field === 'amount');
  return (
    <div className="chain">
      <div className="chain-node" style={{ background: 'var(--cyan)' }}>
        <div className="chain-label">Phiên đã đọc</div>
        {provenance.length === 0 && <div className="small">Không có nội dung ngoài</div>}
        {provenance.slice(-3).map((p, i) => <div key={i} className="mono small">{where(p)}</div>)}
        {provenance.length > 3 && <div className="small muted">+{provenance.length - 3} nguồn khác</div>}
      </div>
      {deciding.map((v, i) => (
        <React.Fragment key={i}>
          <div className="chain-arrow">→</div>
          <div className="chain-node" style={{ background: ORIGIN_TONE[v.origin] || 'var(--white)' }}>
            <div className="chain-label">{FIELD_LABEL[v.field] || v.field}</div>
            <div className="mono"><strong>{String(v.value)}</strong></div>
            <div className="small">{originText(v)}</div>
          </div>
        </React.Fragment>
      ))}
      <div className="chain-arrow">→</div>
      <div className="chain-node" style={{ background: 'var(--yellow)' }}>
        <div className="chain-label">Lệnh</div>
        <div><strong>{actionLabel(action)}</strong></div>
        {payload.amount !== undefined && <div className="mono">{vnd(payload.amount)}</div>}
        {amount && amount.origin === 'untrusted' && <div className="small">số tiền cũng có trong {(amount.seen_in || []).map(where).join(', ')}</div>}
      </div>
    </div>
  );
}

export function LevelBadge({ level }) {
  const meta = {
    clean: { text: 'SẠCH', color: 'var(--green)' },
    exposed: { text: 'ĐÃ ĐỌC NỘI DUNG NGOÀI', color: 'var(--orange)' },
    tainted: { text: 'BỊ TAINT', color: 'var(--red)' },
  }[level] || { text: level, color: 'var(--white)' };
  return <span className="badge" style={{ background: meta.color }}>{meta.text}</span>;
}

export function ReviewByBadge({ by }) {
  if (!by) return null;
  return by === 'user'
    ? <span className="badge" style={{ background: 'var(--cyan)' }}>KHÁCH TỰ XÁC NHẬN</span>
    : <span className="badge" style={{ background: 'var(--violet)' }}>NHÂN VIÊN DUYỆT</span>;
}
