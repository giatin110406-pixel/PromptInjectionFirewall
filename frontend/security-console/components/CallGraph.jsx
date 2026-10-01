import React from 'react';
import PipelineFlow from './PipelineFlow';

export default function CallGraph({ incident, onSelectLayer }) {
  if (!incident) {
    return <PipelineFlow activeLayer={null} isBlocked={false} onSelectLayer={onSelectLayer} />;
  }

  return (
    <PipelineFlow 
      activeLayer={incident.blocked_by_layer} 
      isBlocked={true} 
      onSelectLayer={onSelectLayer} 
    />
  );
}
