import React from 'react';
import { Card } from './ui';

// Engine v2 workflow in three lanes. `activeLayer` lights the layer that decided the selected incident;
// `health` (from /console/health) shows whether each layer is ok, degraded or disabled; `counts` are incidents per layer.
const LANES = [
  {
    title: '① Tin nhắn người dùng',
    nodes: [
      { id: 'user', title: 'Người dùng', sub: 'nhập prompt' },
      { id: 'l0', title: 'L0 Chuẩn hóa', sub: '7 góc nhìn' },
      { id: 'l1', layer: 1, title: 'L1 Chữ ký', sub: 'regex + chỉ mục', health: 'layer1' },
      { id: 'l2', layer: 2, title: 'L2 Phân loại', sub: 'mDeBERTa', health: 'layer2' },
      { id: 'l3', layer: 3, title: 'L3 LLM judge', sub: 'ca chưa chắc', health: 'layer3' },
      { id: 'decision', title: 'Quyết định', sub: 'ALLOW · SANITIZE · REVIEW · BLOCK' },
      { id: 'agent', title: 'Agent LLM', sub: 'trả lời' },
      { id: 'l5', layer: 5, title: 'L5 Đầu ra', sub: 'canary · PII · rò rỉ', health: 'layer5' },
    ],
  },
  {
    title: '② Nội dung không tin cậy (email, web, RAG)',
    nodes: [
      { id: 'src', title: 'Nội dung ngoài', sub: 'email · web · RAG' },
      { id: 'clean', title: 'Làm sạch', sub: 'gỡ nội dung ẩn' },
      { id: 'scan', title: 'Quét từng đoạn', sub: 'dùng L0 + L1 + L2 (+L3)' },
      { id: 'taint', title: 'Độc: loại + TAINT', sub: 'gắn cờ phiên' },
      { id: 'mark', title: 'Sạch: bọc + datamark', sub: 'spotlighting' },
    ],
  },
  {
    title: '③ Hành động của agent',
    nodes: [
      { id: 'call', title: 'Agent đề xuất', sub: 'hoàn tiền, chuyển tiền...' },
      { id: 'l4a', layer: 4, title: 'L4 Luật cứng', sub: 'vai trò, hạn mức, OTP', health: 'layer4' },
      { id: 'l4b', layer: 4, title: 'L4 Taint?', sub: 'phiên có bị nhiễm' },
      { id: 'l4c', layer: 4, title: 'L4 Chính sách', sub: 'ngưỡng, tần suất' },
      { id: 'out', title: 'ALLOW / REVIEW / BLOCK', sub: 'REVIEW vào hàng chờ' },
    ],
  },
];

const LAYER_COLORS = { 1: 'var(--pink)', 2: 'var(--yellow)', 3: 'var(--violet)', 4: 'var(--orange)', 5: 'var(--cyan)' };

export default function PipelineFlow({ activeLayer = null, counts = {}, health = null }) {
  return (
    <Card
      title="Luồng xử lý của engine"
      right={<span className="small muted">Ô sáng viền xanh = layer đã quyết định sự cố đang chọn · số trên góc = số sự cố của layer</span>}
    >
      {LANES.map((lane) => (
        <div className="lane" key={lane.title}>
          <div className="lane-title">{lane.title}</div>
          <div className="lane-row">
            {lane.nodes.map((node, i) => {
              const h = node.health && health?.layers?.[node.health];
              const status = h?.status;
              const lit = node.layer && activeLayer === node.layer;
              return (
                <React.Fragment key={node.id}>
                  <div
                    className={`node ${lit ? 'lit' : ''} ${status === 'degraded' ? 'degraded' : ''} ${status === 'disabled' ? 'disabled' : ''}`}
                    style={{ background: node.layer ? LAYER_COLORS[node.layer] : 'var(--white)' }}
                  >
                    {node.layer && node.id !== 'l4b' && node.id !== 'l4c' && counts[node.layer] > 0 && (
                      <span className="n-count">{counts[node.layer]}</span>
                    )}
                    <div className="n-title">{node.title}</div>
                    <div className="n-sub">{node.sub}</div>
                    {status && <div className="n-health">{status === 'ok' ? 'sẵn sàng' : status === 'disabled' ? 'chưa bật' : 'lỗi'}</div>}
                  </div>
                  {i < lane.nodes.length - 1 && <span className="arrow">→</span>}
                </React.Fragment>
              );
            })}
          </div>
        </div>
      ))}
    </Card>
  );
}
