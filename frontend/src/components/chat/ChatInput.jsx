/**
 * ChatInput — enhanced input with STT, file upload, image paste, settings.
 */

import { useState, useRef, useEffect, useCallback } from 'react';
import {
  Send, Mic, MicOff, Paperclip, Image, X, FileText, Settings,
  Loader2, Lightbulb
} from 'lucide-react';
import { useSettingsStore } from '../../stores/settingsStore';
import toast from 'react-hot-toast';
import './ChatInput.css';

// Reasoning effort options (matching the screenshot)
const REASONING_EFFORTS = [
  { value: 'off',    label: 'Off',    hint: null },
  { value: 'low',    label: 'Low',    hint: 'Max 512 tokens' },
  { value: 'medium', label: 'Medium', hint: 'Max 2,048 tokens' },
  { value: 'high',   label: 'High',   hint: 'Max 8,192 tokens' },
  { value: 'max',    label: 'Max',    hint: 'Unlimited' },
];

export default function ChatInput({ onSend, onSendFile, onSendImage, isStreaming }) {
  const [text, setText] = useState('');
  const [isRecording, setIsRecording] = useState(false);
  const [attachedFile, setAttachedFile] = useState(null);   // { file, type: 'doc' | 'image' }
  const [imagePreview, setImagePreview] = useState(null);   // data URL
  const [showReasoningMenu, setShowReasoningMenu] = useState(false);

  const textareaRef = useRef(null);
  const fileInputRef = useRef(null);
  const imageInputRef = useRef(null);
  const recognitionRef = useRef(null);
  const reasoningMenuRef = useRef(null);

  const { toggleSettingsPanel, reasoning_effort, updateSetting } = useSettingsStore();
  const isReasoningOn = reasoning_effort && reasoning_effort !== 'off';

  // Close reasoning menu when clicking outside
  useEffect(() => {
    function handleClickOutside(e) {
      if (reasoningMenuRef.current && !reasoningMenuRef.current.contains(e.target)) {
        setShowReasoningMenu(false);
      }
    }
    if (showReasoningMenu) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [showReasoningMenu]);

  // Auto-resize textarea
  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 200) + 'px';
  }, [text]);

  // Paste handler for images
  useEffect(() => {
    const handlePaste = (e) => {
      const items = e.clipboardData?.items;
      if (!items) return;
      for (const item of items) {
        if (item.type.startsWith('image/')) {
          e.preventDefault();
          const file = item.getAsFile();
          attachImage(file);
          return;
        }
      }
    };
    window.addEventListener('paste', handlePaste);
    return () => window.removeEventListener('paste', handlePaste);
  }, []);

  // Drag-and-drop
  const handleDragOver = (e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; };
  const handleDrop = useCallback((e) => {
    e.preventDefault();
    const file = e.dataTransfer.files?.[0];
    if (!file) return;
    if (file.type.startsWith('image/')) { attachImage(file); return; }
    const ext = file.name.split('.').pop()?.toLowerCase();
    if (['doc', 'docx', 'pdf', 'txt'].includes(ext)) { attachDoc(file); return; }
    toast.error('File không hỗ trợ. Dùng ảnh hoặc .doc/.docx/.pdf/.txt');
  }, []);

  function attachImage(file) {
    if (file.size > 10 * 1024 * 1024) { toast.error('Ảnh quá lớn (tối đa 10MB)'); return; }
    const reader = new FileReader();
    reader.onload = (e) => setImagePreview(e.target.result);
    reader.readAsDataURL(file);
    setAttachedFile({ file, type: 'image' });
  }

  function attachDoc(file) {
    if (file.size > 10 * 1024 * 1024) { toast.error('File quá lớn (tối đa 10MB)'); return; }
    setAttachedFile({ file, type: 'doc' });
    setImagePreview(null);
  }

  function clearAttachment() {
    setAttachedFile(null);
    setImagePreview(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
    if (imageInputRef.current) imageInputRef.current.value = '';
  }

  // Speech-to-text
  function toggleRecording() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      toast.error('Trình duyệt không hỗ trợ Speech-to-Text. Hãy dùng Chrome hoặc Edge.');
      return;
    }

    if (isRecording) {
      recognitionRef.current?.stop();
      setIsRecording(false);
      return;
    }

    const recognition = new SpeechRecognition();
    recognitionRef.current = recognition;
    recognition.lang = 'vi-VN';
    recognition.continuous = false;
    recognition.interimResults = true;

    recognition.onstart = () => setIsRecording(true);
    recognition.onresult = (e) => {
      const transcript = Array.from(e.results)
        .map(r => r[0].transcript)
        .join('');
      setText(transcript);
    };
    recognition.onerror = (e) => {
      toast.error(`Lỗi nhận dạng giọng nói: ${e.error}`);
      setIsRecording(false);
    };
    recognition.onend = () => setIsRecording(false);
    recognition.start();
  }

  // Send logic
  function handleSend() {
    if (isStreaming) return;
    const msg = text.trim();

    if (attachedFile) {
      if (attachedFile.type === 'image') {
        onSendImage?.(attachedFile.file, msg);
      } else {
        onSendFile?.(attachedFile.file, msg);
      }
      clearAttachment();
      setText('');
      return;
    }

    if (!msg) return;
    onSend?.(msg);
    setText('');
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  const canSend = !isStreaming && (text.trim() || attachedFile);
  const currentEffort = REASONING_EFFORTS.find(e => e.value === (reasoning_effort || 'off'));

  return (
    <div
      className="chat-input-wrapper"
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {/* Attachment preview */}
      {attachedFile && (
        <div className="attachment-preview">
          {imagePreview ? (
            <div className="attachment-image-preview">
              <img src={imagePreview} alt="Preview" />
              <button className="attachment-remove" onClick={clearAttachment} title="Xóa">
                <X size={14} />
              </button>
            </div>
          ) : (
            <div className="attachment-doc-preview">
              <FileText size={18} />
              <div className="attachment-doc-info">
                <span className="attachment-doc-name">{attachedFile.file.name}</span>
                <span className="attachment-doc-size">
                  {(attachedFile.file.size / 1024).toFixed(0)} KB
                </span>
              </div>
              <button className="attachment-remove" onClick={clearAttachment} title="Xóa">
                <X size={14} />
              </button>
            </div>
          )}
        </div>
      )}

      <div className="chat-input-row">
        {/* Left actions */}
        <div className="input-left-actions">
          <button
            className={`btn btn-ghost btn-icon btn-sm action-btn ${isRecording ? 'recording' : ''}`}
            onClick={toggleRecording}
            title={isRecording ? 'Dừng ghi âm' : 'Ghi âm (vi-VN)'}
          >
            {isRecording ? <MicOff size={16} /> : <Mic size={16} />}
          </button>

          <button
            className="btn btn-ghost btn-icon btn-sm action-btn"
            onClick={() => fileInputRef.current?.click()}
            title="Đính kèm file (.doc/.pdf/.txt)"
          >
            <Paperclip size={16} />
          </button>

          <button
            className="btn btn-ghost btn-icon btn-sm action-btn"
            onClick={() => imageInputRef.current?.click()}
            title="Đính kèm / dán hình ảnh (Ctrl+V)"
          >
            <Image size={16} />
          </button>
        </div>

        {/* Textarea */}
        <div className="input-text-area">
          {isRecording && (
            <div className="recording-indicator">
              <div className="voice-wave-bars">
                <span className="bar bar-1"></span>
                <span className="bar bar-2"></span>
                <span className="bar bar-3"></span>
                <span className="bar bar-4"></span>
                <span className="bar bar-5"></span>
              </div>
              <span>Đang nghe...</span>
            </div>
          )}
          <textarea
            ref={textareaRef}
            className="chat-textarea"
            placeholder={
              attachedFile
                ? `Nhập câu hỏi về ${attachedFile.type === 'image' ? 'hình ảnh' : 'file'} này...`
                : 'Nhập câu hỏi pháp luật... (Ctrl+V để dán ảnh)'
            }
            value={text}
            onChange={e => setText(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isStreaming}
            rows={1}
          />
        </div>

        {/* Right actions */}
        <div className="input-right-actions">
          <button
            className="btn btn-ghost btn-icon btn-sm action-btn"
            onClick={toggleSettingsPanel}
            title="Cài đặt model"
          >
            <Settings size={16} />
          </button>

          {/* ── Reasoning Effort Bulb ── */}
          <div className="reasoning-bulb-wrap" ref={reasoningMenuRef}>
            <button
              className={`btn btn-ghost btn-icon btn-sm action-btn reasoning-bulb-btn ${isReasoningOn ? 'reasoning-on' : 'reasoning-off'}`}
              onClick={() => setShowReasoningMenu(v => !v)}
              title={`Reasoning: ${currentEffort?.label ?? 'Off'}`}
            >
              <Lightbulb size={16} />
            </button>

            {/* Dropdown menu */}
            {showReasoningMenu && (
              <div className="reasoning-dropdown reasoning-dropdown--right">
                <div className="reasoning-dropdown-title">Reasoning effort</div>
                {REASONING_EFFORTS.map(eff => (
                  <button
                    key={eff.value}
                    className={`reasoning-dropdown-item ${(reasoning_effort || 'off') === eff.value ? 'active' : ''}`}
                    onClick={() => {
                      updateSetting('reasoning_effort', eff.value);
                      setShowReasoningMenu(false);
                    }}
                  >
                    <span className="rdi-check">
                      {(reasoning_effort || 'off') === eff.value ? '✓' : ''}
                    </span>
                    <span className="rdi-label">{eff.label}</span>
                    {eff.hint && <span className="rdi-hint">{eff.hint}</span>}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        <button
          className={`send-btn ${canSend ? 'active' : ''}`}
          onClick={handleSend}
          disabled={!canSend}
          title="Gửi (Enter)"
        >
          {isStreaming
            ? <Loader2 size={16} className="animate-spin" />
            : <Send size={16} />
          }
        </button>
      </div>

      {/* Hidden file inputs */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".doc,.docx,.pdf,.txt"
        style={{ display: 'none' }}
        onChange={e => { const f = e.target.files?.[0]; if (f) attachDoc(f); }}
      />
      <input
        ref={imageInputRef}
        type="file"
        accept="image/*"
        style={{ display: 'none' }}
        onChange={e => { const f = e.target.files?.[0]; if (f) attachImage(f); }}
      />
    </div>
  );
}
