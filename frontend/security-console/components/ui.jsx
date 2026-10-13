import React from 'react';
import { DECISIONS, layerOf } from '../lib/layers';

export function DecisionBadge({ decision }) {
  const meta = DECISIONS[decision] || { label: decision || '?', color: 'var(--white)' };
  return (
    <span className="badge" style={{ background: meta.color }}>
      {meta.label}
    </span>
  );
}

export function LayerBadge({ layer }) {
  const meta = layerOf(layer);
  return (
    <span className="badge" style={{ background: meta.color }}>
      {meta.key}
    </span>
  );
}

export function Card({ title, right, tint, children, className = '' }) {
  return (
    <section className={`card ${tint ? `tint-${tint}` : ''} ${className}`}>
      {(title || right) && (
        <div className="card-head">
          <h2>{title}</h2>
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

export function Json({ value }) {
  return <pre className="box mono">{JSON.stringify(value, null, 2)}</pre>;
}
