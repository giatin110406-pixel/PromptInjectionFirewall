import React from 'react';
import PipelineFlow from './PipelineFlow';

// Kept for older imports: the call graph is the pipeline map, lit at the layer that decided the incident.
export default function CallGraph({ incident, counts, health }) {
  return <PipelineFlow activeLayer={incident ? incident.blocked_by_layer : null} counts={counts} health={health} />;
}
