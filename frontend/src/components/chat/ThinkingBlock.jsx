/**
 * ThinkingBlock — collapsible CoT / reasoning display.
 * - Khi isStreaming=true: auto-expand, hiển thị text đang stream với cursor ▋
 * - Khi isStreaming đổi false: auto-collapse sau 800ms
 * - Sau đó: user click để toggle
 */

import { useState, useRef, useEffect } from 'react';
import { Brain, ChevronDown, Sparkles } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './ThinkingBlock.css';

export default function ThinkingBlock({ content, isStreaming = false }) {
  // Auto-open khi đang stream, auto-close khi xong
  const [isOpen, setIsOpen] = useState(isStreaming);
  const contentRef = useRef(null);
  const [contentHeight, setContentHeight] = useState(0);
  const wasStreamingRef = useRef(isStreaming);

  // Khi bắt đầu stream → mở
  useEffect(() => {
    if (isStreaming && !isOpen) {
      setIsOpen(true);
    }
  }, [isStreaming]);

  // Khi stream kết thúc → đóng sau 800ms
  useEffect(() => {
    if (wasStreamingRef.current && !isStreaming) {
      const timer = setTimeout(() => setIsOpen(false), 800);
      return () => clearTimeout(timer);
    }
    wasStreamingRef.current = isStreaming;
  }, [isStreaming]);

  // Update height khi content thay đổi
  useEffect(() => {
    if (contentRef.current) {
      setContentHeight(contentRef.current.scrollHeight);
    }
  }, [content, isOpen]);

  if (!content || !content.trim()) return null;

  const wordCount = content.trim().split(/\s+/).length;
  const charCount = content.trim().length;
  const readTime = Math.max(1, Math.round(wordCount / 200));

  return (
    <div className={`thinking-block ${isOpen ? 'thinking-block--open' : ''} ${isStreaming ? 'thinking-block--streaming' : ''}`}>
      {/* Toggle header */}
      <button
        className="thinking-toggle"
        onClick={() => setIsOpen(v => !v)}
        aria-expanded={isOpen}
      >
        {/* Left: icon + label */}
        <div className="thinking-toggle-left">
          <div className={`thinking-icon ${isStreaming ? 'thinking-icon--pulse' : ''}`}>
            {isStreaming ? <Sparkles size={12} /> : <Brain size={12} />}
          </div>
          <span className="thinking-label">
            {isStreaming ? 'Đang suy luận…' : 'Quá trình suy luận'}
          </span>
        </div>

        {/* Right: stats + chevron */}
        <div className="thinking-toggle-right">
          {!isStreaming && (
            <>
              <span className="thinking-stat">{wordCount.toLocaleString()} từ</span>
              <span className="thinking-dot" />
              <span className="thinking-stat">~{readTime} phút đọc</span>
            </>
          )}
          {isStreaming && (
            <span className="thinking-stat thinking-stat--live">
              {charCount.toLocaleString()} ký tự…
            </span>
          )}
          <ChevronDown
            size={13}
            className="thinking-chevron"
            style={{ transform: isOpen ? 'rotate(180deg)' : 'rotate(0deg)' }}
          />
        </div>
      </button>

      {/* Animated content */}
      <div
        className="thinking-collapse"
        style={{
          maxHeight: isOpen ? `${Math.max(contentHeight + 40, 200)}px` : '0px',
        }}
      >
        <div ref={contentRef} className="thinking-content">
          <div className="thinking-content-inner">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {content}
            </ReactMarkdown>
            {/* Blinking cursor khi đang stream */}
            {isStreaming && <span className="thinking-cursor">▋</span>}
          </div>
        </div>
      </div>
    </div>
  );
}
