import React from 'react';

function Kpi({ label, value, hint, tint }) {
  return (
    <div className={`card kpi tint-${tint}`}>
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {hint && <div className="hint">{hint}</div>}
    </div>
  );
}

export default function MetricCards({ stats }) {
  const by = stats.by_decision || {};
  return (
    <div className="grid kpis">
      <Kpi label="Tổng sự cố" value={stats.total_incidents ?? 0} hint="BLOCK + REVIEW + SANITIZE" tint="yellow" />
      <Kpi label="Đã chặn" value={by.BLOCK ?? 0} hint="BLOCK" tint="pink" />
      <Kpi label="Chờ người duyệt" value={stats.pending_reviews ?? 0} hint="REVIEW chưa quyết" tint="violet" />
      <Kpi label="Đã làm sạch" value={by.SANITIZE ?? 0} hint="SANITIZE" tint="green" />
      <Kpi label="Phiên bị TAINT" value={stats.tainted_sessions ?? 0} hint="đã đọc nội dung có chỉ thị" tint="cyan" />
      <Kpi label="Phản hồi đã gửi" value={(stats.feedback?.false_positive ?? 0) + (stats.feedback?.missed_attack ?? 0)} hint={`${stats.feedback?.false_positive ?? 0} chặn nhầm · ${stats.feedback?.missed_attack ?? 0} bị lọt`} tint="pink" />
      <Kpi label="Độ trễ trung bình" value={`${stats.avg_latency_ms ?? 0} ms`} hint="trên các sự cố đã ghi" tint="white" />
    </div>
  );
}
