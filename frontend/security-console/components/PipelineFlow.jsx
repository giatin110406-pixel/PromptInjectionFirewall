import React from 'react';

export default function PipelineFlow({ activeLayer = null, isBlocked = false, onSelectLayer }) {
  return (
    <section className="pipeline-card">
      <div className="pipeline-header">
        <div className="section-title">
          <svg viewBox="0 0 24 24" fill="none" strokeWidth="2" stroke="var(--cyan-400)" width="14" height="14">
            <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline>
          </svg>
          Active Defense Cascading Pipeline Architecture
        </div>
        <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontFamily: 'JetBrains Mono' }}>
          Multi-Tier Gatekeeper
        </span>
      </div>

      <div className="pipeline-nodes-container">
        {/* Stage 0 */}
        <div className="pipe-node" style={{ textAlign: 'center' }}>
          <span className="pipe-node-tag" style={{ color: 'var(--text-muted)' }}>STAGE 0</span>
          <span className="pipe-node-title">Client Ingress</span>
          <span className="pipe-node-desc">Raw Prompt</span>
        </div>

        <div className="pipe-arrow">➔</div>

        {/* Layer 1 */}
        <div 
          className={`pipe-node ${activeLayer === 1 ? (isBlocked ? 'active-intercept' : 'active-pass') : ''}`}
          onClick={() => onSelectLayer && onSelectLayer(1)}
        >
          <span className="pipe-node-tag" style={{ color: 'var(--rose-400)' }}>LAYER 1 · PREFILTER</span>
          <span className="pipe-node-title">Regex & Vector Sim</span>
          <span className="pipe-node-desc">ChromaDB · &lt;1.0ms</span>
        </div>

        <div className="pipe-arrow">➔</div>

        {/* Layer 2 */}
        <div 
          className={`pipe-node ${activeLayer === 2 ? (isBlocked ? 'active-intercept' : 'active-pass') : ''}`}
          onClick={() => onSelectLayer && onSelectLayer(2)}
        >
          <span className="pipe-node-tag" style={{ color: 'var(--amber-400)' }}>LAYER 2 · STATISTICAL</span>
          <span className="pipe-node-title">XGBoost Feature ML</span>
          <span className="pipe-node-desc">14 Heuristic Vector · ~2ms</span>
        </div>

        <div className="pipe-arrow">➔</div>

        {/* Layer 3 */}
        <div 
          className={`pipe-node ${activeLayer === 3 ? (isBlocked ? 'active-intercept' : 'active-pass') : ''}`}
          onClick={() => onSelectLayer && onSelectLayer(3)}
        >
          <span className="pipe-node-tag" style={{ color: 'var(--violet-400)' }}>LAYER 3 · NEURAL</span>
          <span className="pipe-node-title">DistilBERT Transformer</span>
          <span className="pipe-node-desc">Contextual Deep Classif.</span>
        </div>

        <div className="pipe-arrow">➔</div>

        {/* Layer 4 */}
        <div 
          className={`pipe-node ${activeLayer === 4 ? (isBlocked ? 'active-intercept' : 'active-pass') : ''}`}
          onClick={() => onSelectLayer && onSelectLayer(4)}
        >
          <span className="pipe-node-tag" style={{ color: 'var(--cyan-400)' }}>LAYER 4 · POLICY</span>
          <span className="pipe-node-title">Pydantic Validator</span>
          <span className="pipe-node-desc">Action & Tool Bounds</span>
        </div>

        <div className="pipe-arrow">➔</div>

        {/* Stage Core */}
        <div className="pipe-node" style={{ textAlign: 'center', borderColor: 'rgba(16, 185, 129, 0.3)' }}>
          <span className="pipe-node-tag" style={{ color: 'var(--emerald-400)' }}>SECURE CORE</span>
          <span className="pipe-node-title">LLM Agent</span>
          <span className="pipe-node-desc">Clean Context</span>
        </div>
      </div>
    </section>
  );
}
