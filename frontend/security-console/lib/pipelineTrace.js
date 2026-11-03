export const PIPELINE_STAGES = [
  { id: 'L0', title: 'Chuẩn hóa', role: 'Chuẩn bị văn bản', how: 'Chuẩn hóa Unicode, ký tự ẩn và các cách viết để lớp sau kiểm tra cùng một nội dung.' },
  { id: 'L1', title: 'Chữ ký', role: 'Regex + ngữ nghĩa', how: 'So mẫu tấn công và độ tương đồng. Chữ ký cứng có thể dừng request; cảnh báo ngữ nghĩa được đánh giá tiếp.' },
  { id: 'L2', title: 'Phân loại', role: 'mDeBERTa', how: 'Chấm điểm injection trên các cửa sổ văn bản. Điểm cao là tín hiệu nghi ngờ, chưa chắc là tấn công thật.' },
  { id: 'L3', title: 'Judge', role: 'LLM đánh giá lại', how: 'Đọc lại ca bị nghi ngờ. Lành tính → đi tiếp; tấn công → chặn; chưa chắc hoặc lỗi → giữ để kiểm tra.' },
  { id: 'AGENT', title: 'Power Agent', role: 'Trả lời / chọn tool', how: 'Nhận nội dung đã kiểm tra rồi trả lời hoặc đề xuất gọi tool. Tool đọc quay lại L0–L3; tool hành động đi qua L4.' },
  { id: 'L4', title: 'Cổng hành động', role: 'Quyền + nguồn gốc', how: 'Kiểm quyền, OTP, hạn mức, nguồn của người nhận và điều kiện duyệt trước khi backend thực hiện lệnh.' },
  { id: 'L5', title: 'Kiểm đầu ra', role: 'Chưa nối vào Agent', how: 'Output Guard đã có trong engine nhưng câu trả lời cuối của vòng lặp Agent chưa đi qua lớp này.' },
];

export function eventsFromResult(result) {
  if (!result) return [];
  if (result.progress?.events?.length) return result.progress.events;
  const events = [];
  const add = (stage, phase, data) => events.push({ id: events.length + 1, stage, phase, state: 'done', ...data });
  for (const step of result.steps || []) {
    if (step.kind === 'firewall_input') {
      for (const layer of step.trace || []) add(`L${layer.layer}`, 'input', { ...layer, ...layer.details });
      if (!step.trace?.length) add(`L${step.layer}`, 'input', { decision: step.decision, reason: step.reason, latency_ms: step.ms });
    } else if (step.kind === 'llm') {
      add('AGENT', 'agent', { decision: step.tool_calls?.length ? 'TOOL_CALL' : 'REPLY', tools: step.tool_calls,
        preview: step.text, latency_ms: step.ms, model: result.model });
    } else if (step.kind === 'tool_read') {
      for (const check of step.firewall?.judge_checks || []) add('L3', 'context', {
        ...check.judge, decision: check.decision, reason: check.reason, tool: step.tool });
      add('CONTEXT', 'context', { tool: step.tool, decision: step.firewall?.decision || 'BYPASSED',
        session_level: step.firewall?.session_level });
    } else if (step.kind === 'tool_action') add('L4', 'action', { ...step, latency_ms: step.ms });
  }
  if (result.error) add('AGENT', 'agent', { state: 'error', decision: 'ERROR', message: result.reply,
    error_code: result.error_code || (/429|rate limit/i.test(result.error) ? 'rate_limit' : 'provider_error') });
  return events;
}

export function playbackFrames(events) {
  return events.filter((e) => PIPELINE_STAGES.some((s) => s.id === e.stage) && e.state !== 'running' && e.state !== 'finished');
}

export function stageState(id, events, result, busy) {
  const history = events.filter((e) => e.stage === id && e.state !== 'finished');
  const last = history[history.length - 1];
  if (last) return { history, last };
  let label = busy ? 'Chưa tới' : 'Chưa có request';
  if (id === 'L5') label = 'Chưa tích hợp';
  else if (result?.mode === 'off' && id.startsWith('L')) label = 'Đã tắt';
  else if (id === 'L0' && events.some((e) => e.stage === 'L1')) label = 'Nằm trong L1';
  else if (result) label = id === 'L4' ? 'Không có lệnh' : id === 'L3' ? 'Không cần gọi' : 'Không chạy';
  return { history, last: null, label };
}

export function eventBadge(event, stage) {
  if (!event) return { tone: 'idle', text: 'Chưa chạy' };
  if (event.state === 'error' || event.decision === 'ERROR') return { tone: 'error', text: event.error_code === 'rate_limit' ? 'Chạm quota' : 'Lỗi dịch vụ' };
  if (event.state === 'running') return { tone: 'running', text: 'Đang xử lý' };
  if (event.degraded) return { tone: 'review', text: 'Cần kiểm tra' };
  if (event.decision === 'BLOCK') return stage === 'L2' || (stage === 'L1' && !event.reason?.startsWith('regex_match'))
    ? { tone: 'alert', text: 'Nghi ngờ' } : { tone: 'block', text: 'Chặn' };
  if (event.decision === 'REVIEW') return { tone: 'review', text: 'Chờ duyệt' };
  if (event.decision === 'ESCALATE') return { tone: 'alert', text: stage === 'L1' ? 'Chuyển L2' : 'Chuyển Judge' };
  if (event.decision === 'TOOL_CALL') return { tone: 'running', text: 'Đề xuất tool' };
  if (event.decision === 'REPLY') return { tone: 'allow', text: 'Đã trả lời' };
  if (event.decision === 'NORMALIZED') return { tone: 'allow', text: 'Đã chuẩn hóa' };
  return { tone: 'allow', text: 'Cho qua' };
}

export function phaseLabel(event) {
  return event?.phase === 'context' ? `Nội dung ngoài${event.tool ? ` · ${event.tool}` : ''}`
    : event?.phase === 'action' ? `Hành động${event.tool ? ` · ${event.tool}` : ''}`
      : event?.phase === 'agent' ? 'Suy luận Agent' : 'Tin nhắn người dùng';
}
