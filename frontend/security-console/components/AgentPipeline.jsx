import React, { useEffect, useMemo, useState } from 'react';
import { PIPELINE_STAGES, eventBadge, eventsFromResult, phaseLabel, playbackFrames, stageState } from '../lib/pipelineTrace';
import SAMPLES from '../lib/pipeline_samples.json';

const seconds = (ms) => `${(Number(ms || 0) / 1000).toFixed(1)}s`;

function outcome(result) {
  if (!result) return 'Gửi một tin nhắn hoặc mở bản ghi mẫu để bắt đầu.';
  if (result.error_code === 'rate_limit' || /429|rate limit/i.test(result.error || '')) return 'Power Agent chạm quota · đây là lỗi dịch vụ LLM, không phải firewall chặn.';
  if (result.error) return result.reply || 'Yêu cầu chưa hoàn tất.';
  if (result.pending_review) return 'Lệnh đang chờ xác nhận · backend chưa thực hiện.';
  if (result.stopped === 'input_block') return 'Đầu vào bị chặn · Power Agent chưa được gọi.';
  if (result.stopped === 'input_review') return 'Đầu vào đang được giữ để kiểm tra.';
  if (result.executed?.length) return `${result.executed.length} hành động đã được backend mô phỏng thực hiện.`;
  return 'Đã trả kết quả · không có hành động nghiệp vụ được thực hiện.';
}

export default function AgentPipeline({ result, progress, busy, requestText, readOnly = false }) {
  const [sample, setSample] = useState(readOnly ? SAMPLES[0] : null);
  const [replay, setReplay] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [cursor, setCursor] = useState(0);
  const [selected, setSelected] = useState(null);
  const [historyId, setHistoryId] = useState(null);
  const [elapsed, setElapsed] = useState(0);
  const shown = sample?.result || result;
  const events = useMemo(() => sample ? eventsFromResult(sample.result)
    : (progress?.events?.length ? progress.events : eventsFromResult(result)), [sample, progress, result]);
  const frames = useMemo(() => playbackFrames(events), [events]);
  const live = busy && !sample;
  const boundary = replay && frames.length ? frames[Math.min(cursor, frames.length - 1)].id : Infinity;
  const visible = events.filter((e) => e.id <= boundary);
  const current = replay ? frames[Math.min(cursor, frames.length - 1)]
    : [...visible].reverse().find((e) => PIPELINE_STAGES.some((s) => s.id === e.stage) && e.state !== 'finished');
  const selectedId = selected || current?.stage || 'L3';
  const definition = PIPELINE_STAGES.find((s) => s.id === selectedId) || PIPELINE_STAGES[3];
  const detail = stageState(selectedId, visible, shown, live);
  const event = detail.history.find((e) => e.id === historyId) || detail.last;
  const badge = event ? eventBadge(event, selectedId) : { tone: 'idle', text: detail.label };
  const text = sample?.request || requestText;

  useEffect(() => {
    if (busy) { setSample(null); setReplay(false); setPlaying(false); setSelected(null); setHistoryId(null); }
  }, [busy]);
  useEffect(() => {
    if (!busy) return undefined;
    const started = Date.now();
    setElapsed(0);
    const timer = setInterval(() => setElapsed(Date.now() - started), 250);
    return () => clearInterval(timer);
  }, [busy]);
  useEffect(() => {
    if (!playing || !frames.length) return undefined;
    const timer = setInterval(() => setCursor((x) => Math.min(x + 1, frames.length - 1)), 650);
    return () => clearInterval(timer);
  }, [playing, frames.length]);
  useEffect(() => { if (cursor >= frames.length - 1) setPlaying(false); }, [cursor, frames.length]);

  const startReplay = () => { setReplay(true); setCursor(0); setPlaying(true); setSelected(null); setHistoryId(null); };
  const pickSample = (item) => { setSample(item); setReplay(true); setCursor(0); setPlaying(true); setSelected(null); setHistoryId(null); };
  const move = (delta) => { setReplay(true); setPlaying(false); setSelected(null); setHistoryId(null); setCursor((x) => Math.max(0, Math.min(x + delta, frames.length - 1))); };

  return (
    <section className="card pipeline" aria-label="Sơ đồ xử lý request">
      <div className="pipeline-heading">
        <div><div className="pipeline-eyebrow">THEO DÕI REQUEST</div><h2>Request đi qua firewall như thế nào?</h2></div>
        <span className={`pipeline-status ${live ? 'is-live' : ''}`}>{live ? `● Trực tiếp · ${seconds(elapsed)}` : sample ? 'Bản ghi kiểm thử' : shown ? 'Kết quả request' : 'Sẵn sàng'}</span>
      </div>
      <div className="pipeline-toolbar">
        <div className="pipeline-samples"><span className="small">Xem mẫu:</span>{SAMPLES.map((item) => <button key={item.id} disabled={busy}
          className={`pipeline-chip ${sample?.id === item.id ? 'chosen' : ''}`} onClick={() => pickSample(item)}>{item.label}</button>)}</div>
        <div className="pipeline-player">
          <button className="btn sm white" disabled={busy || !frames.length} onClick={startReplay}>↻ Phát lại chậm</button>
          {replay && <><button className="pipeline-chip" aria-label="Bước trước" onClick={() => move(-1)} disabled={!cursor}>←</button>
            <button className="pipeline-chip" onClick={() => setPlaying((x) => !x)}>{playing ? 'Tạm dừng' : 'Tiếp tục'}</button>
            <button className="pipeline-chip" aria-label="Bước sau" onClick={() => move(1)} disabled={cursor >= frames.length - 1}>→</button></>}
          {sample && !readOnly && <button className="pipeline-chip" onClick={() => { setSample(null); setReplay(false); setPlaying(false); setSelected(null); }}>Về request thật</button>}
        </div>
      </div>
      <div className="pipeline-caption" aria-live="polite">
        {replay ? `Phát lại bước ${Math.min(cursor + 1, frames.length)}/${frames.length} · ${phaseLabel(current)}`
          : live ? `${current?.stage || 'Máy chủ'} đang xử lý · ${phaseLabel(current)}` : outcome(shown)}
        {sample && <span className="small muted"> · Trace đã lưu, không gọi LLM và không thực hiện giao dịch.</span>}
      </div>
      {text && <div className="pipeline-request"><strong>REQ</strong><span>{text}</span></div>}
      <div className="pipeline-scroll">
        <div className="pipeline-stages">
          {PIPELINE_STAGES.map((stage, i) => {
            const state = stageState(stage.id, visible, shown, live);
            const status = state.last ? eventBadge(state.last, stage.id) : { tone: 'idle', text: state.label };
            const atCursor = current?.stage === stage.id;
            return <React.Fragment key={stage.id}>
              {i > 0 && <span className={`pipeline-arrow ${atCursor ? 'cursor-arrow' : ''}`} aria-hidden="true">→</span>}
              <button className={`pipeline-stage tone-${status.tone} ${atCursor ? 'at-cursor' : ''} ${selectedId === stage.id ? 'selected' : ''}`}
                aria-pressed={selectedId === stage.id} onClick={() => { setSelected(stage.id); setHistoryId(null); }}>
                <span className="pipeline-stage-id">{stage.id === 'AGENT' ? 'LLM' : stage.id}</span>
                <strong>{stage.title}</strong><span className="pipeline-stage-role">{stage.role}</span>
                <span className={`pipeline-badge tone-${status.tone}`}>{status.text}</span>
                {state.last?.latency_ms != null && <span className="pipeline-time">{Math.round(state.last.latency_ms)} ms</span>}
                {atCursor && <span className="request-dot" aria-label={replay ? 'Request ở bước phát lại này' : 'Vị trí request'} />}
              </button>
            </React.Fragment>;
          })}
        </div>
      </div>
      <div className="pipeline-detail">
        <div><div className="pipeline-detail-title"><strong>{definition.id} · {definition.title}</strong><span className={`pipeline-badge tone-${badge.tone}`}>{badge.text}</span></div>
          <p>{definition.how}</p>
          {detail.history.filter((e) => e.state !== 'running').length > 1 && <div className="pipeline-history">{detail.history.filter((e) => e.state !== 'running').slice(-5).map((item, i) =>
            <button key={item.id} className={`pipeline-chip ${event?.id === item.id ? 'chosen' : ''}`} onClick={() => setHistoryId(item.id)}>{i + 1}. {phaseLabel(item)}</button>)}</div>}
        </div>
        <div className="pipeline-evidence">
          {!event && <span className="muted small">{selectedId === 'L5' ? 'L5 chưa được gọi trong vòng lặp Agent hiện tại.' : detail.label === 'Nằm trong L1' ? 'Bản ghi này chưa tách mốc L0; chuẩn hóa nằm bên trong L1.' : 'Chọn bản ghi mẫu hoặc gửi request để xem dữ liệu thực tế của lớp này.'}</span>}
          {event && <>
            <div className="small muted">{phaseLabel(event)}</div>
            {selectedId === 'L2' && <div>Điểm injection: <strong>{Number(event.max_window_score ?? (event.decision === 'ALLOW' ? 1 - (event.confidence || 0) : event.confidence || 0)).toFixed(3)}</strong>{event.threshold != null && <span className="small"> · ngưỡng {Number(event.threshold).toFixed(3)}</span>}</div>}
            {selectedId === 'L1' && event.top_attack_similarity != null && <div>Độ tương đồng với mẫu tấn công: <strong>{Number(event.top_attack_similarity).toFixed(3)}</strong></div>}
            {selectedId === 'L3' && <div>Judge: <strong>{event.verdict || event.decision}</strong>{event.confidence != null && ` · độ tin cậy ${(event.confidence * 100).toFixed(0)}%`}</div>}
            {event.model && <div className="small mono">{event.model}</div>}
            {event.variants != null && <div>{event.chars} ký tự → {event.variants} biến thể kiểm tra</div>}
            {event.tools?.length > 0 && <div>Tool đề xuất: <strong>{event.tools.join(', ')}</strong></div>}
            {event.tool && <div>Tool: <strong className="mono">{event.tool}</strong></div>}
            <div className="pipeline-reason">{event.message || event.reason || event.preview || (event.state === 'running' ? 'Đang chờ lớp này trả kết quả…' : 'Bước này đã xử lý xong.')}</div>
            {event.payload && <details><summary>Payload và nguồn giá trị</summary><pre>{JSON.stringify({ payload: event.payload, provenance: event.value_provenance || event.provenance }, null, 2)}</pre></details>}
          </>}
        </div>
      </div>
      <div className="pipeline-foot"><span><i className="legend-dot green" /> Cho qua</span><span><i className="legend-dot orange" /> Nghi ngờ / chờ duyệt</span><span><i className="legend-dot red" /> Chặn / lỗi</span><span>Tool đọc ↶ L0–L3 · Tool hành động → L4</span></div>
    </section>
  );
}
