/**
 * SourcesPanel — collapsible, beautifully formatted retrieved document sources.
 * Parses both structured JSON payload (new) and legacy markdown string (old).
 */

import { useState } from 'react';
import {
  BookOpen, ChevronDown, FileText, Hash,
  Layers, GitBranch, BookMarked,
} from 'lucide-react';
import './SourcesPanel.css';

// ─── Helpers ──────────────────────────────────────────────────────────────────

/**
 * Parse sources — accepts:
 *   - structured payload: { items: [...], fusion: {...} }
 *   - raw array of source objects
 *   - legacy markdown string (fallback)
 */
function parseSources(raw) {
  if (!raw) return { items: [], fusion: null };

  // Structured payload from backend
  if (typeof raw === 'object' && !Array.isArray(raw) && raw.items) {
    return { items: raw.items || [], fusion: raw.fusion || null };
  }

  // Plain array
  if (Array.isArray(raw)) {
    return { items: raw, fusion: null };
  }

  // Legacy: markdown string — extract minimal info from lines
  if (typeof raw === 'string') {
    const lines = raw.split('\n').filter(l => l.trim() && !l.startsWith('---') && !l.startsWith('#') && !l.startsWith('*Mode'));
    const items = lines.map((l, i) => ({
      source: l.replace(/^\*\*\d+\.\s*/, '').replace(/\*\*.*/, '').trim() || `Nguồn ${i + 1}`,
      preview: '',
    }));
    return { items, fusion: null };
  }

  return { items: [], fusion: null };
}

/** Retrieval source badge colour */
function tagColor(tag) {
  if (!tag) return 'var(--color-primary)';
  if (tag.includes('graph')) return 'hsl(280, 60%, 60%)';
  if (tag.includes('vector')) return 'hsl(210, 70%, 55%)';
  return 'hsl(155, 55%, 50%)';
}

// ─── Sub-component: one source card ───────────────────────────────────────────

function SourceCard({ item, index }) {
  const [expanded, setExpanded] = useState(false);

  const tags = item.retrieval_sources || [];
  const fullContent = (item.content || item.preview || '').trim();
  const hasContent = fullContent.length > 0;
  const relevancePct = typeof item.relevance_pct === 'number' ? item.relevance_pct : null;
  const relevanceColor = relevancePct === null ? null
    : relevancePct >= 80 ? 'hsl(145, 60%, 50%)'
    : relevancePct >= 60 ? 'hsl(45, 85%, 55%)'
    : 'hsl(25, 80%, 55%)';

  const refs = [
    item.doc_number && `Số hiệu: ${item.doc_number}`,
    item.chapter,
    item.article && `Điều ${item.article}`,
    item.clause && `Khoản ${item.clause}`,
  ].filter(Boolean);

  return (
    <div className={`source-card ${expanded ? 'source-card--open' : ''}`}>
      {/* Card header */}
      <button
        className="source-card-header"
        onClick={() => hasContent && setExpanded(v => !v)}
        disabled={!hasContent}
      >
        <span className="source-card-index">{index}</span>

        <div className="source-card-info">
          <span className="source-card-name">
            <FileText size={11} />
            {item.source || 'Không rõ nguồn'}
          </span>

          {refs.length > 0 && (
            <span className="source-card-ref">
              {refs.map((r, i) => (
                <span key={i} className="source-card-ref-chip">{r}</span>
              ))}
            </span>
          )}
        </div>

        <div className="source-card-meta">
          {tags.map(t => (
            <span
              key={t}
              className="source-tag"
              style={{ '--tag-color': tagColor(t) }}
            >
              {t.includes('graph') ? <GitBranch size={9} /> : <Layers size={9} />}
              {t}
            </span>
          ))}
          {relevancePct !== null && (
            <span
              className="source-relevance"
              style={{ '--rel-color': relevanceColor }}
              title={`Độ liên quan: ${relevancePct}%`}
            >
              {relevancePct}%
            </span>
          )}
          {hasContent && (
            <ChevronDown
              size={12}
              className="source-expand-icon"
              style={{ transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)' }}
            />
          )}
        </div>
      </button>

      {/* Expanded: full content */}
      {expanded && hasContent && (
        <div className="source-card-content">
          <pre className="source-card-content-text">{fullContent}</pre>
        </div>
      )}
    </div>
  );
}

// ─── Main component ────────────────────────────────────────────────────────────

export default function SourcesPanel({ sources }) {
  const [isOpen, setIsOpen] = useState(false);

  const { items, fusion } = parseSources(sources);
  if (items.length === 0) return null;

  return (
    <div className="sources-panel">
      {/* Toggle header */}
      <button
        className="sources-toggle"
        onClick={() => setIsOpen(v => !v)}
        aria-expanded={isOpen}
      >
        <div className="sources-toggle-left">
          <BookOpen size={13} />
          <span>Nguồn tham khảo</span>
          <span className="sources-count">{items.length}</span>
        </div>

        <div className="sources-toggle-right">
          {fusion && (
            <span className="sources-fusion-info">
              <BookMarked size={10} />
              {fusion.mode} · v{fusion.vector_count} g{fusion.graph_count}→{fusion.fused_count}
            </span>
          )}
          <ChevronDown
            size={13}
            className="sources-chevron"
            style={{ transform: isOpen ? 'rotate(180deg)' : 'rotate(0deg)' }}
          />
        </div>
      </button>

      {/* Sources list */}
      {isOpen && (
        <div className="sources-body">
          {items.map((item, i) => (
            <SourceCard key={i} item={item} index={i + 1} />
          ))}
        </div>
      )}
    </div>
  );
}
