import React, { useRef, useEffect, useState } from 'react';

// Theme-aligned palette for different Neo4j node labels
export const NODE_THEMES = {
  Law: { color: '#F59E0B', radius: 26, label: 'Luật' },
  Chapter: { color: '#F97316', radius: 22, label: 'Chương' },
  Article: { color: '#3B82F6', radius: 18, label: 'Điều' },
  Clause: { color: '#06B6D4', radius: 14, label: 'Khoản' },
  Concept: { color: '#8B5CF6', radius: 12, label: 'Khái niệm' },
  Actor: { color: '#EC4899', radius: 12, label: 'Chủ thể' },
  Action: { color: '#10B981', radius: 12, label: 'Hành vi' },
  Default: { color: '#94A3B8', radius: 12, label: 'Nút' }
};

export default function GraphVisualizer({
  nodes = [],
  edges = [],
  selectedNode = null,
  onNodeSelect,
  onNodeDoubleClick,
}) {
  const canvasRef = useRef(null);
  const containerRef = useRef(null);
  const localNodesRef = useRef([]);
  const localEdgesRef = useRef([]);
  
  // Viewport transformation state
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [hoveredNode, setHoveredNode] = useState(null);

  // Refs for tracking interaction state in canvas listeners
  const zoomRef = useRef(1);
  const panRef = useRef({ x: 0, y: 0 });
  const draggedNodeRef = useRef(null);
  const isPanningRef = useRef(false);
  const panStartRef = useRef({ x: 0, y: 0 });
  const lastClickTimeRef = useRef(0);

  // Sync state with refs for mouse handler accessibility
  useEffect(() => {
    zoomRef.current = zoom;
  }, [zoom]);

  useEffect(() => {
    panRef.current = pan;
  }, [pan]);

  // Synchronize incoming props to the local physical simulation
  useEffect(() => {
    const center = {
      x: containerRef.current ? containerRef.current.clientWidth / 2 : 300,
      y: containerRef.current ? containerRef.current.clientHeight / 2 : 250,
    };

    const oldNodesMap = new Map(localNodesRef.current.map(n => [n.id, n]));
    
    // Map new nodes, preserving position & velocity if they existed,
    // or spawning them near their parent/center to make transition smooth.
    const nextNodes = nodes.map(n => {
      const existing = oldNodesMap.get(n.id);
      if (existing) {
        return {
          ...n,
          x: existing.x,
          y: existing.y,
          vx: existing.vx,
          vy: existing.vy,
        };
      }

      // Check if we can find a connected parent that already has a position
      const connectedEdge = edges.find(e => 
        (e.source === n.id && oldNodesMap.has(e.target)) ||
        (e.target === n.id && oldNodesMap.has(e.source))
      );

      let px = center.x - panRef.current.x;
      let py = center.y - panRef.current.y;
      
      if (connectedEdge) {
        const parentId = oldNodesMap.has(connectedEdge.source) ? connectedEdge.source : connectedEdge.target;
        const parentNode = oldNodesMap.get(parentId);
        if (parentNode) {
          px = parentNode.x;
          py = parentNode.y;
        }
      }

      return {
        ...n,
        x: px + (Math.random() - 0.5) * 350,
        y: py + (Math.random() - 0.5) * 350,
        vx: 0,
        vy: 0,
      };
    });

    localNodesRef.current = nextNodes;

    // Resolve edge endpoints to actual node objects for high-performance tick loop
    localEdgesRef.current = edges.map(e => {
      const sourceNode = nextNodes.find(n => n.id === e.source);
      const targetNode = nextNodes.find(n => n.id === e.target);
      return {
        ...e,
        sourceNode,
        targetNode,
      };
    }).filter(e => e.sourceNode && e.targetNode);

  }, [nodes, edges]);

  // Node helper function to get style/dimensions
  const getNodeStyle = (node) => {
    if (!node || !node.labels) return NODE_THEMES.Default;
    for (const label of node.labels) {
      if (NODE_THEMES[label]) return NODE_THEMES[label];
    }
    return NODE_THEMES.Default;
  };

  const getNodeText = (node) => {
    const props = node.properties || {};
    if (props.title) return props.title;
    if (props.name) return props.name;
    if (props.number) return `${node.labels?.[0] || 'Node'} ${props.number}`;
    if (props.text) {
      return props.text.length > 30 ? props.text.substring(0, 30) + '...' : props.text;
    }
    return `${node.labels?.[0] || 'Node'} (${node.id.substring(0, 6)})`;
  };

  const getShortLabel = (node) => {
    const props = node.properties || {};
    if (props.number) return props.number;
    if (node.labels?.includes('Law')) return 'Luật';
    if (node.labels?.includes('Chapter')) return 'Ch. ' + (props.number || '');
    if (node.labels?.includes('Article')) return 'Đ. ' + (props.number || '');
    if (node.labels?.includes('Clause')) return 'K. ' + (props.number || '');
    return node.labels?.[0]?.substring(0, 3) || 'N';
  };

  // Setup simulation and drawing loop
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    let animationFrameId;

    // Adjust canvas resolution dynamically according to DPI
    const resizeCanvas = () => {
      const rect = canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      ctx.resetTransform();
      ctx.scale(dpr, dpr);
    };

    resizeCanvas();
    window.addEventListener('resize', resizeCanvas);

    // Physical simulation step
    const runPhysicsTick = () => {
      const nodesList = localNodesRef.current;
      const edgesList = localEdgesRef.current;
      const draggedNode = draggedNodeRef.current;
      
      if (!nodesList || nodesList.length === 0) return;

      // 1. Repulsion (Coulomb's Law) - increased to push nodes farther apart
      const kRepulsion = 3500;
      for (let i = 0; i < nodesList.length; i++) {
        const u = nodesList[i];
        for (let j = i + 1; j < nodesList.length; j++) {
          const v = nodesList[j];
          const dx = v.x - u.x;
          const dy = v.y - u.y;
          const distSq = dx * dx + dy * dy;
          const dist = Math.sqrt(distSq) + 0.1;
          
          if (dist < 1000) {
            const force = kRepulsion / (dist * dist);
            const fx = (dx / dist) * force;
            const fy = (dy / dist) * force;
            u.vx -= fx;
            u.vy -= fy;
            v.vx += fx;
            v.vy += fy;
          }
        }
      }

      // 2. Attraction along relationships (Hooke's Law) - gentler pull and longer rest length
      const kAttraction = 0.02;
      const restLength = 240;
      for (let i = 0; i < edgesList.length; i++) {
        const edge = edgesList[i];
        const u = edge.sourceNode;
        const v = edge.targetNode;
        const dx = v.x - u.x;
        const dy = v.y - u.y;
        const dist = Math.sqrt(dx * dx + dy * dy) + 0.1;

        const displacement = dist - restLength;
        const force = displacement * kAttraction;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        
        u.vx += fx;
        u.vy += fy;
        v.vx -= fx;
        v.vy -= fy;
      }

      // 3. Gravity pulling towards local center - reduced significantly to allow clusters to branch out freely
      const center = {
        x: canvas.clientWidth / 2,
        y: canvas.clientHeight / 2
      };
      const kGravity = 0.001;
      for (let i = 0; i < nodesList.length; i++) {
        const u = nodesList[i];
        u.vx -= (u.x - center.x) * kGravity;
        u.vy -= (u.y - center.y) * kGravity;
      }

      // 4. Update coordinates & apply frictional damping - reduced damping to allow longer, more fluid movement
      const damping = 0.88;
      for (let i = 0; i < nodesList.length; i++) {
        const u = nodesList[i];
        if (u === draggedNode) {
          u.vx = 0;
          u.vy = 0;
        } else {
          u.vx *= damping;
          u.vy *= damping;
          u.x += u.vx;
          u.y += u.vy;
        }
      }
    };

    // Rendering step
    const draw = () => {
      ctx.clearRect(0, 0, canvas.clientWidth, canvas.clientHeight);

      // Draw modern technical grid background
      ctx.strokeStyle = '#1e293b';
      ctx.lineWidth = 0.5;
      const gridSize = 40;
      const offsetGridX = panRef.current.x % (gridSize * zoomRef.current);
      const offsetGridY = panRef.current.y % (gridSize * zoomRef.current);
      
      if (zoomRef.current > 0.4) {
        ctx.beginPath();
        for (let x = offsetGridX; x < canvas.clientWidth; x += gridSize * zoomRef.current) {
          ctx.moveTo(x, 0);
          ctx.lineTo(x, canvas.clientHeight);
        }
        for (let y = offsetGridY; y < canvas.clientHeight; y += gridSize * zoomRef.current) {
          ctx.moveTo(0, y);
          ctx.lineTo(canvas.clientWidth, y);
        }
        ctx.stroke();
      }

      // Apply viewport matrix (translation & scaling)
      ctx.save();
      ctx.translate(panRef.current.x, panRef.current.y);
      ctx.scale(zoomRef.current, zoomRef.current);

      const nodesList = localNodesRef.current;
      const edgesList = localEdgesRef.current;

      // 1. Draw relationships (edges)
      edgesList.forEach(edge => {
        const u = edge.sourceNode;
        const v = edge.targetNode;
        const styleU = getNodeStyle(u);
        const styleV = getNodeStyle(v);

        // Highlight edges connected to active hovered/selected nodes
        const isHighlighted = (hoveredNode && (hoveredNode.id === u.id || hoveredNode.id === v.id)) ||
                            (selectedNode && (selectedNode.id === u.id || selectedNode.id === v.id));

        ctx.strokeStyle = isHighlighted ? 'rgba(59, 130, 246, 0.7)' : 'rgba(71, 85, 105, 0.35)';
        ctx.lineWidth = isHighlighted ? 2.5 : 1.2;

        // Draw relationship path
        ctx.beginPath();
        ctx.moveTo(u.x, u.y);
        ctx.lineTo(v.x, v.y);
        ctx.stroke();

        // Calculate arrowhead placement on target node edge
        const dx = v.x - u.x;
        const dy = v.y - u.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const arrowLength = 8;
        const arrowAngle = Math.PI / 6;

        // Position arrowhead exactly at target node perimeter
        const targetRadius = styleV.radius;
        const arrowX = v.x - (dx / dist) * targetRadius;
        const arrowY = v.y - (dy / dist) * targetRadius;

        const angle = Math.atan2(dy, dx);
        
        ctx.fillStyle = isHighlighted ? '#3B82F6' : 'rgba(71, 85, 105, 0.5)';
        ctx.beginPath();
        ctx.moveTo(arrowX, arrowY);
        ctx.lineTo(
          arrowX - arrowLength * Math.cos(angle - arrowAngle),
          arrowY - arrowLength * Math.sin(angle - arrowAngle)
        );
        ctx.lineTo(
          arrowX - arrowLength * Math.cos(angle + arrowAngle),
          arrowY - arrowLength * Math.sin(angle + arrowAngle)
        );
        ctx.closePath();
        ctx.fill();

        // Draw edge relationship label when zoomed in
        if (zoomRef.current > 0.75 && edge.type) {
          const midX = (u.x + v.x) / 2;
          const midY = (u.y + v.y) / 2;
          
          let textAngle = angle;
          // Keep label upright
          if (textAngle > Math.PI / 2 || textAngle < -Math.PI / 2) {
            textAngle += Math.PI;
          }

          ctx.save();
          ctx.translate(midX, midY);
          ctx.rotate(textAngle);
          ctx.font = '8px "Outfit", "Inter", sans-serif';
          ctx.fillStyle = isHighlighted ? '#93C5FD' : '#64748B';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'bottom';
          // Draw subtle background plate under text
          const width = ctx.measureText(edge.type).width + 6;
          ctx.fillStyle = 'rgba(11, 15, 25, 0.85)';
          ctx.fillRect(-width / 2, -10, width, 10);
          ctx.fillStyle = isHighlighted ? '#93C5FD' : '#94A3B8';
          ctx.fillText(edge.type, 0, -2);
          ctx.restore();
        }
      });

      // 2. Draw nodes
      nodesList.forEach(node => {
        const theme = getNodeStyle(node);
        const isHovered = hoveredNode && hoveredNode.id === node.id;
        const isSelected = selectedNode && selectedNode.id === node.id;

        ctx.save();
        ctx.shadowBlur = (isHovered || isSelected) ? 15 : 0;
        ctx.shadowColor = theme.color;

        // Radial glowing gradient for nodes
        const grad = ctx.createRadialGradient(
          node.x - theme.radius * 0.15,
          node.y - theme.radius * 0.15,
          2,
          node.x,
          node.y,
          theme.radius
        );
        grad.addColorStop(0, '#ffffff');
        grad.addColorStop(0.2, theme.color);
        grad.addColorStop(1, adjustColorBrightness(theme.color, -30));

        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.arc(node.x, node.y, theme.radius, 0, 2 * Math.PI);
        ctx.fill();

        // White border ring for chosen or hovered nodes
        ctx.shadowBlur = 0; // Disable shadow for stroke border
        if (isSelected) {
          ctx.strokeStyle = '#FFFFFF';
          ctx.lineWidth = 3;
          ctx.stroke();
        } else if (isHovered) {
          ctx.strokeStyle = 'rgba(255, 255, 255, 0.8)';
          ctx.lineWidth = 2;
          ctx.stroke();
        } else {
          ctx.strokeStyle = 'rgba(11, 15, 25, 0.5)';
          ctx.lineWidth = 1;
          ctx.stroke();
        }

        // Draw inner index label (e.g. "L", "12")
        ctx.fillStyle = '#FFFFFF';
        ctx.font = `bold ${Math.max(10, theme.radius * 0.55)}px "Outfit", "Inter", sans-serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(getShortLabel(node), node.x, node.y + 0.5);

        // Draw secondary detail text tag below node when zoomed in
        if (zoomRef.current > 0.55) {
          const detailText = getNodeText(node);
          ctx.font = '10px "Inter", sans-serif';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'top';

          // Safe truncate long text
          const displayStr = detailText.length > 22 ? detailText.substring(0, 20) + '...' : detailText;

          // Draw dark backplate stroke under label to ensure readability
          ctx.strokeStyle = 'rgba(11, 15, 25, 0.9)';
          ctx.lineWidth = 4;
          ctx.strokeText(displayStr, node.x, node.y + theme.radius + 6);
          ctx.fillStyle = isHovered ? '#FFFFFF' : '#E2E8F0';
          ctx.fillText(displayStr, node.x, node.y + theme.radius + 6);
        }

        ctx.restore();
      });

      ctx.restore();
    };

    // Master render loop
    const frame = () => {
      runPhysicsTick();
      draw();
      animationFrameId = requestAnimationFrame(frame);
    };

    frame();

    return () => {
      cancelAnimationFrame(animationFrameId);
      window.removeEventListener('resize', resizeCanvas);
    };
  }, [selectedNode, hoveredNode]);

  // Utility: Hex Color Brightness Adjuster for gradient shading
  function adjustColorBrightness(hex, percent) {
    let R = parseInt(hex.substring(1, 3), 16);
    let G = parseInt(hex.substring(3, 5), 16);
    let B = parseInt(hex.substring(5, 7), 16);

    R = parseInt((R * (100 + percent)) / 100);
    G = parseInt((G * (100 + percent)) / 100);
    B = parseInt((B * (100 + percent)) / 100);

    R = R < 255 ? R : 255;
    G = G < 255 ? G : 255;
    B = B < 255 ? B : 255;

    R = R > 0 ? R : 0;
    G = G > 0 ? G : 0;
    B = B > 0 ? B : 0;

    const rHex = R.toString(16).padStart(2, '0');
    const gHex = G.toString(16).padStart(2, '0');
    const bHex = B.toString(16).padStart(2, '0');

    return `#${rHex}${gHex}${bHex}`;
  }

  // Translate screen client coordinates to simulation world coordinates
  const screenToWorld = (clientX, clientY) => {
    const rect = canvasRef.current.getBoundingClientRect();
    const x = (clientX - rect.left - panRef.current.x) / zoomRef.current;
    const y = (clientY - rect.top - panRef.current.y) / zoomRef.current;
    return { x, y };
  };

  // Locate the node containing a coordinate
  const getNodeAtCoord = (x, y) => {
    const nodesList = localNodesRef.current;
    for (let i = nodesList.length - 1; i >= 0; i--) {
      const node = nodesList[i];
      const theme = getNodeStyle(node);
      const dx = node.x - x;
      const dy = node.y - y;
      if (dx * dx + dy * dy <= theme.radius * theme.radius) {
        return node;
      }
    }
    return null;
  };

  // Mouse interactivity handlers
  const handleMouseDown = (e) => {
    const worldPos = screenToWorld(e.clientX, e.clientY);
    const clickedNode = getNodeAtCoord(worldPos.x, worldPos.y);

    if (clickedNode) {
      draggedNodeRef.current = clickedNode;
      onNodeSelect(clickedNode);

      // Handle double click check
      const now = Date.now();
      if (now - lastClickTimeRef.current < 280) {
        if (onNodeDoubleClick) {
          onNodeDoubleClick(clickedNode);
        }
      }
      lastClickTimeRef.current = now;
    } else {
      isPanningRef.current = true;
      panStartRef.current = {
        x: e.clientX - panRef.current.x,
        y: e.clientY - panRef.current.y
      };
    }
  };

  const handleMouseMove = (e) => {
    const worldPos = screenToWorld(e.clientX, e.clientY);
    
    // Manage hover trigger
    const overNode = getNodeAtCoord(worldPos.x, worldPos.y);
    setHoveredNode(overNode);

    if (draggedNodeRef.current) {
      // Pin dragged node position to pointer
      draggedNodeRef.current.x = worldPos.x;
      draggedNodeRef.current.y = worldPos.y;
      draggedNodeRef.current.vx = 0;
      draggedNodeRef.current.vy = 0;
    } else if (isPanningRef.current) {
      // Pan viewport
      setPan({
        x: e.clientX - panStartRef.current.x,
        y: e.clientY - panStartRef.current.y
      });
    }
  };

  const handleMouseUp = () => {
    draggedNodeRef.current = null;
    isPanningRef.current = false;
  };

  const handleWheel = (e) => {
    e.preventDefault();
    const zoomIntensity = 0.08;
    const rect = canvasRef.current.getBoundingClientRect();
    
    // Zoom centering relative to pointer
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    const mouseWorldX = (mouseX - panRef.current.x) / zoomRef.current;
    const mouseWorldY = (mouseY - panRef.current.y) / zoomRef.current;

    const zoomFactor = e.deltaY < 0 ? (1 + zoomIntensity) : (1 - zoomIntensity);
    const nextZoom = Math.max(0.15, Math.min(4, zoomRef.current * zoomFactor));

    setZoom(nextZoom);
    setPan({
      x: mouseX - mouseWorldX * nextZoom,
      y: mouseY - mouseWorldY * nextZoom
    });
  };

  // Navigation Control Actions
  const handleResetViewport = () => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
    
    // Re-center all node layout positions
    const canvas = canvasRef.current;
    if (canvas && localNodesRef.current.length > 0) {
      const centerX = canvas.clientWidth / 2;
      const centerY = canvas.clientHeight / 2;
      localNodesRef.current.forEach(node => {
        node.x = centerX + (Math.random() - 0.5) * 400;
        node.y = centerY + (Math.random() - 0.5) * 400;
        node.vx = 0;
        node.vy = 0;
      });
    }
  };

  const handleFitViewport = () => {
    const nodesList = localNodesRef.current;
    const canvas = canvasRef.current;
    if (!nodesList || nodesList.length === 0 || !canvas) return;

    // Calculate boundary boxes of active simulation space
    let minX = Infinity, maxX = -Infinity;
    let minY = Infinity, maxY = -Infinity;

    nodesList.forEach(n => {
      if (n.x < minX) minX = n.x;
      if (n.x > maxX) maxX = n.x;
      if (n.y < minY) minY = n.y;
      if (n.y > maxY) maxY = n.y;
    });

    const graphWidth = (maxX - minX) || 1;
    const graphHeight = (maxY - minY) || 1;
    const padding = 60;

    const scaleX = (canvas.clientWidth - padding * 2) / graphWidth;
    const scaleY = (canvas.clientHeight - padding * 2) / graphHeight;
    const nextZoom = Math.max(0.2, Math.min(2.5, Math.min(scaleX, scaleY)));

    const graphCenterX = (minX + maxX) / 2;
    const graphCenterY = (minY + maxY) / 2;

    setZoom(nextZoom);
    setPan({
      x: canvas.clientWidth / 2 - graphCenterX * nextZoom,
      y: canvas.clientHeight / 2 - graphCenterY * nextZoom
    });
  };

  return (
    <div 
      ref={containerRef} 
      className="graph-canvas-container"
      style={{
        position: 'relative',
        width: '100%',
        height: '100%',
        minHeight: '450px',
        backgroundColor: '#0b0f19',
        borderRadius: 'var(--radius-lg)',
        border: '1px solid var(--color-border)',
        overflow: 'hidden',
        userSelect: 'none'
      }}
    >
      <canvas
        ref={canvasRef}
        style={{
          display: 'block',
          width: '100%',
          height: '100%',
          cursor: hoveredNode ? 'pointer' : draggedNodeRef.current ? 'grabbing' : 'grab'
        }}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        onWheel={handleWheel}
      />

      {/* Floating Viewport Navigation Toolbar */}
      <div 
        className="graph-controls" 
        style={{
          position: 'absolute',
          top: '12px',
          left: '12px',
          display: 'flex',
          gap: '8px',
          zIndex: 10,
          background: 'rgba(15, 23, 42, 0.75)',
          backdropFilter: 'blur(8px)',
          padding: '4px 8px',
          borderRadius: '20px',
          border: '1px solid rgba(255,255,255,0.08)'
        }}
      >
        <button 
          className="btn btn-ghost btn-xs" 
          onClick={() => setZoom(prev => Math.min(4, prev * 1.15))}
          style={{ color: '#E2E8F0', padding: '2px 8px', minWidth: '24px' }}
          title="Zoom In"
        >
          ＋
        </button>
        <button 
          className="btn btn-ghost btn-xs" 
          onClick={() => setZoom(prev => Math.max(0.15, prev / 1.15))}
          style={{ color: '#E2E8F0', padding: '2px 8px', minWidth: '24px' }}
          title="Zoom Out"
        >
          －
        </button>
        <button 
          className="btn btn-ghost btn-xs" 
          onClick={handleFitViewport}
          style={{ color: '#E2E8F0', padding: '2px 8px', fontSize: '11px' }}
          title="Fit Graph to Window"
        >
          Fit Screen
        </button>
        <button 
          className="btn btn-ghost btn-xs" 
          onClick={handleResetViewport}
          style={{ color: '#E2E8F0', padding: '2px 8px', fontSize: '11px' }}
          title="Recenter Layout and Positons"
        >
          Reset
        </button>
        <span 
          style={{ 
            color: '#64748B', 
            fontSize: '10px', 
            alignSelf: 'center', 
            paddingLeft: '4px',
            borderLeft: '1px solid rgba(255,255,255,0.1)'
          }}
        >
          {(zoom * 100).toFixed(0)}%
        </span>
      </div>

      {/* Legend overlays */}
      <div 
        className="graph-legend" 
        style={{
          position: 'absolute',
          top: '12px',
          right: '12px',
          background: 'rgba(15, 23, 42, 0.75)',
          backdropFilter: 'blur(8px)',
          padding: '10px 14px',
          borderRadius: 'var(--radius-md)',
          border: '1px solid rgba(255,255,255,0.08)',
          fontSize: '11px',
          display: 'flex',
          flexDirection: 'column',
          gap: '6px',
          maxHeight: '180px',
          overflowY: 'auto',
          color: '#94A3B8'
        }}
      >
        <strong style={{ color: '#F8FAFC', marginBottom: '2px' }}>Chú thích nút</strong>
        {Object.entries(NODE_THEMES).map(([key, item]) => {
          if (key === 'Default') return null;
          return (
            <div key={key} style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span 
                style={{ 
                  display: 'inline-block', 
                  width: '10px', 
                  height: '10px', 
                  borderRadius: '50%', 
                  backgroundColor: item.color 
                }} 
              />
              <span>{item.label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
