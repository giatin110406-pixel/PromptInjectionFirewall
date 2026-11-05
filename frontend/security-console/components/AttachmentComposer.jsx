import React, { useState } from 'react';

export default function AttachmentComposer({ busy, onFiles, onLink, onText, onClose }) {
  const [tab, setTab] = useState('files');
  const [files, setFiles] = useState([]);
  const [url, setUrl] = useState('');
  const [text, setText] = useState('');
  const [channel, setChannel] = useState('document');
  return <div className="attachment-composer">
    <div className="card-head"><strong>Đính kèm dữ liệu cho Agent</strong><button type="button" className="pipeline-chip" disabled={busy} onClick={onClose}>Đóng</button></div>
    <div className="backend-tabs">{[['files', 'Tải file'], ['link', 'Link web'], ['text', 'Dán nội dung']].map(([id, label]) =>
      <button type="button" disabled={busy} key={id} className={`pipeline-chip ${tab === id ? 'chosen' : ''}`} onClick={() => setTab(id)}>{label}</button>)}</div>
    {tab === 'files' && <div className="attachment-inputs">
      <label className="attachment-drop" onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); if (!busy) setFiles(Array.from(e.dataTransfer.files)); }}>
        <strong>Chọn hoặc kéo thả file vào đây</strong><span>PDF · DOCX · TXT/MD · CSV/JSON · HTML · EML</span>
        <input type="file" multiple disabled={busy} accept=".pdf,.docx,.txt,.md,.csv,.json,.html,.htm,.eml" onChange={(e) => setFiles(Array.from(e.target.files || []))} /></label>
      <div className="small muted">Tối đa 5 file/lần, 5 MB/file, 10 MB/lần. Mỗi tài liệu tối đa 20.000 ký tự. PDF scan/ảnh cần OCR trước.</div>
      <div className="small">Tải file mẫu để xem/sửa rồi đính kèm:
        <div className="backend-tabs">{[['invoice-clean.txt', 'TXT sạch'], ['order-data.json', 'JSON dữ liệu'], ['invoice-hidden.html', 'HTML ghi chú ẩn'],
          ['invoice-hidden.eml', 'Email có injection'], ['invoice-hidden.docx', 'DOCX text ẩn'], ['invoice-annotation.pdf', 'PDF annotation']].map(([file, title]) =>
          <a key={file} className="pipeline-chip" href={`/attachment-samples/${file}`} download>{title}</a>)}</div>
        <span className="muted">Mẫu tổng hợp từ kịch bản Shop Mây có sẵn; dùng trong demo local.</span></div>
      {files.map((f, i) => <div className="attachment-selected" key={`${f.name}-${i}`}><span>{f.name} · {(f.size / 1024).toFixed(1)} KB</span>
        <button type="button" className="pipeline-chip" disabled={busy} onClick={() => setFiles((list) => list.filter((_, n) => n !== i))}>Bỏ</button></div>)}
      <button type="button" className="btn cyan sm" disabled={busy || !files.length} onClick={async () => { if (await onFiles(files)) setFiles([]); }}>Đính kèm {files.length || ''} file</button>
    </div>}
    {tab === 'link' && <div className="attachment-inputs"><label htmlFor="attachment-url">Địa chỉ tài liệu hoặc trang web</label>
      <input id="attachment-url" type="url" disabled={busy} value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://..." />
      <div className="small muted">Server tải nội dung thật của URL công khai. Không chạy JavaScript; file/trang local có thể tải trực tiếp bằng tab Tải file.</div>
      <button type="button" className="btn cyan sm" disabled={busy || !url.trim()} onClick={async () => { if (await onLink(url.trim())) setUrl(''); }}>Tải và đính kèm link</button></div>}
    {tab === 'text' && <div className="attachment-inputs"><label>Nguồn nội dung<select value={channel} disabled={busy} onChange={(e) => setChannel(e.target.value)}>
      <option value="document">Tài liệu</option><option value="email">Email</option><option value="web">Trang web / HTML</option><option value="tool_json">Kết quả công cụ / JSON</option></select></label>
      <textarea aria-label="Nội dung tài liệu" rows={5} maxLength={20000} disabled={busy} value={text} onChange={(e) => setText(e.target.value)} placeholder="Dán nội dung nguyên bản, kể cả HTML comment hoặc chỉ thị muốn thử…" />
      <button type="button" className="btn cyan sm" disabled={busy || !text.trim()} onClick={async () => { if (await onText(text, channel)) setText(''); }}>Đính kèm nội dung</button></div>}
    <div className="small">Đính kèm giữ nguyên phiên và lịch sử giao dịch. Sau đó gửi câu hỏi trong chat để Agent đọc qua firewall.</div>
  </div>;
}
