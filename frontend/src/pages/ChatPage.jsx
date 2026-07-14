/**
 * Chat Page — main chat interface with sidebar, settings, enhanced input.
 */

import { useEffect, useRef, useCallback, useState } from 'react';
import { Link } from 'react-router-dom';
import { useChatStore } from '../stores/chatStore.jsx';
import { useAuthStore } from '../stores/authStore';
import { useTheme } from '../hooks/useTheme';
import { useSettingsStore } from '../stores/settingsStore';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import ChatInput from '../components/chat/ChatInput';
import SettingsPanel from '../components/chat/SettingsPanel';
import SourcesPanel from '../components/chat/SourcesPanel';
import ThinkingBlock from '../components/chat/ThinkingBlock';
import DraftingPanel from '../components/chat/DraftingPanel';
import {
  Plus, MessageSquare, Trash2, LogOut, Scale, Bot, User as UserIcon,
  ChevronLeft, ChevronRight, LayoutDashboard, Cpu, Sparkles, BookOpen, Shield, HelpCircle,
  Search, Download, Volume2, VolumeX, ThumbsUp, ThumbsDown, FileText
} from 'lucide-react';
import toast from 'react-hot-toast';
import '../styles/components/chat.css';

const SUGGESTIONS = [
  'Hợp đồng lao động có mấy loại theo BLLĐ 2019?',
  'Tội phạm được phân loại theo mức độ nguy hiểm như thế nào?',
  'Quy định về ly hôn có con chung trong Luật HNGĐ?',
  'Bồi thường thiệt hại ngoài hợp đồng theo BLDS 2015?',
];

export default function ChatPage() {
  const { user, logout } = useAuthStore();
  const [theme, setTheme] = useTheme();
  const {
    sessions, activeSessionId, messages, isStreaming, streamingContent,
    streamingThinking, streamingPhase, streamingSources,
    fetchSessions, createSession, deleteSession, setActiveSession, clearSession,
    sendMessage, sendFile, sendImage, isLoadingSessions, isLoadingMessages,
    draftingIntent, clearDraftingIntent,
  } = useChatStore();

  const { getQuerySettings, settingsPanelOpen, toggleSettingsPanel } = useSettingsStore();

  // Validate settings before any send
  const validateSettings = useCallback(() => {
    const s = getQuerySettings();
    if (!s.provider) {
      toast.error(
        '⚙️ Chưa chọn Model!\nVào Settings → chọn model từ danh sách.',
        { duration: 4000, icon: null }
      );
      toggleSettingsPanel();
      return false;
    }
    return true;
  }, [getQuerySettings, toggleSettingsPanel]);

  const messagesEndRef = useRef(null);
  const [sidebarOpen, setSidebarOpen] = useSidebarState(true);
  const [isProfileDropdownOpen, setIsProfileDropdownOpen] = useState(false);
  const [sessionSearchQuery, setSessionSearchQuery] = useState('');
  const [activeTtsMessageId, setActiveTtsMessageId] = useState(null);
  const synthRef = useRef(window.speechSynthesis);
  const [isDraftingOpen, setIsDraftingOpen] = useState(false);
  const [draftingPrefill, setDraftingPrefill] = useState(null);

  // Auto-open DraftingPanel when intent is detected by chatStore
  useEffect(() => {
    if (draftingIntent) {
      setDraftingPrefill(draftingIntent);
      setIsDraftingOpen(true);
      clearDraftingIntent();
    }
  }, [draftingIntent, clearDraftingIntent]);

  useEffect(() => {
    return () => {
      if (synthRef.current) synthRef.current.cancel();
    };
  }, []);

  const handleTts = (msg) => {
    if (!synthRef.current) {
      toast.error('Trình duyệt của bạn không hỗ trợ Text-to-Speech.');
      return;
    }

    if (activeTtsMessageId === msg.id) {
      synthRef.current.cancel();
      setActiveTtsMessageId(null);
      return;
    }

    synthRef.current.cancel();
    const textToRead = msg.content.replace(/[\*\#\`\-\_\>\n]/g, ' ').trim();
    if (!textToRead) return;

    const utterance = new SpeechSynthesisUtterance(textToRead);
    utterance.lang = 'vi-VN';
    const voices = synthRef.current.getVoices();
    const viVoice = voices.find(v => v.lang.includes('vi') || v.lang.includes('VI'));
    if (viVoice) utterance.voice = viVoice;

    utterance.onend = () => setActiveTtsMessageId(null);
    utterance.onerror = () => setActiveTtsMessageId(null);

    setActiveTtsMessageId(msg.id);
    synthRef.current.speak(utterance);
  };

  const handleMessageFeedback = async (messageId, rating) => {
    const currentMsg = messages.find(m => m.id === messageId);
    const nextRating = currentMsg?.metadata?.rating === rating ? 0 : rating;
    await useChatStore.getState().rateMessage(messageId, nextRating);
  };

  const exportChatToMarkdown = () => {
    if (messages.length === 0) {
      toast.error('Không có nội dung trò chuyện để xuất.');
      return;
    }

    const sessionTitle = sessions.find(s => s.id === activeSessionId)?.title || 'chat-export';
    let md = `# ${sessionTitle}\n\n`;
    
    messages.forEach((msg, idx) => {
      const roleName = msg.role === 'user' ? 'Người dùng' : 'Trợ lý AI';
      md += `### ${idx + 1}. ${roleName}:\n\n`;
      if (msg.thinking) {
        md += `> **Suy luận:**\n> ${msg.thinking.split('\n').join('\n> ')}\n\n`;
      }
      md += `${msg.content}\n\n`;
      if (msg.sources) {
        md += `*Nguồn tham khảo:*\n`;
        if (typeof msg.sources === 'string') {
          md += `${msg.sources}\n\n`;
        } else if (Array.isArray(msg.sources)) {
          msg.sources.forEach(src => {
            md += `- **${src.source || 'Văn bản'}**: ${src.content || src.preview || ''}\n`;
          });
          md += `\n`;
        } else if (typeof msg.sources === 'object' && msg.sources.items) {
          msg.sources.items.forEach(src => {
            md += `- **${src.source || 'Văn bản'}**: ${src.content || src.preview || ''}\n`;
          });
          md += `\n`;
        }
      }
      md += `---\n\n`;
    });

    const blob = new Blob([md], { type: 'text/markdown;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', `${sessionTitle.replace(/[^a-zA-Z0-9À-ỹ\s-_]/g, '')}.md`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    toast.success('Đã xuất lịch sử chat!');
  };

  const filteredSessions = sessions.filter(s =>
    (s.title || '').toLowerCase().includes(sessionSearchQuery.toLowerCase())
  );

  // Handle clicking outside to close the profile dropdown popover
  useEffect(() => {
    const handleOutsideClick = () => {
      setIsProfileDropdownOpen(false);
    };
    window.addEventListener('click', handleOutsideClick);
    return () => {
      window.removeEventListener('click', handleOutsideClick);
    };
  }, []);

  useEffect(() => { fetchSessions(); }, []);

  useEffect(() => {
    const initialPrompt = localStorage.getItem('initial_chat_prompt');
    if (initialPrompt) {
      localStorage.removeItem('initial_chat_prompt');
      const triggerInitial = async () => {
        clearSession();
        const sess = await createSession();
        if (sess) {
          sendMessage(initialPrompt, getQuerySettings());
        }
      };
      triggerInitial();
    }
  }, [clearSession, createSession, sendMessage, getQuerySettings]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingContent]);

  const handleSend = useCallback(async (text) => {
    if (!text.trim() || isStreaming) return;
    if (!validateSettings()) return;
    await sendMessage(text, getQuerySettings());
  }, [isStreaming, sendMessage, getQuerySettings, validateSettings]);

  const handleSendFile = useCallback(async (file, question) => {
    if (!validateSettings()) return;
    await sendFile(file, question, getQuerySettings());
  }, [sendFile, getQuerySettings, validateSettings]);

  const handleSendImage = useCallback(async (imageFile, question) => {
    if (!validateSettings()) return;
    await sendImage(imageFile, question, getQuerySettings());
  }, [sendImage, getQuerySettings, validateSettings]);

  const handleNewChat = () => {
    clearSession();
    toast.success('Cuộc trò chuyện mới', { icon: '💬', duration: 1500 });
  };

  const handleDeleteSession = (e, id) => {
    e.stopPropagation();
    deleteSession(id);
    toast.success('Đã xóa phiên chat', { duration: 1500 });
  };

  const allMessages = messages;
  const isWelcome = allMessages.length === 0;

  return (
    <div className="chat-layout">

      {/* ===== Sidebar ===== */}
      <aside className={`chat-sidebar ${sidebarOpen ? 'open' : 'collapsed'}`}>
        {/* Sidebar header */}
        <div className="sidebar-header">
          {sidebarOpen && (
            <Link 
              to="/home" 
              className="sidebar-logo" 
              style={{ textDecoration: 'none', color: 'inherit', display: 'flex', alignItems: 'center', gap: '8px' }}
              title="Về trang chủ"
            >
              <Scale size={18} color="var(--color-primary)" />
              <span>Legal RAG</span>
            </Link>
          )}
          <button
            className="btn btn-ghost btn-icon btn-sm sidebar-toggle-btn"
            onClick={() => setSidebarOpen(!sidebarOpen)}
            title={sidebarOpen ? 'Thu gọn' : 'Mở rộng'}
          >
            {sidebarOpen ? <ChevronLeft size={16} /> : <ChevronRight size={16} />}
          </button>
        </div>

        {/* New chat button */}
        <div className="sidebar-new-chat-wrap">
          <button
            className="btn btn-primary sidebar-new-chat"
            onClick={handleNewChat}
            title="Cuộc trò chuyện mới"
          >
            <Plus size={16} />
            {sidebarOpen && <span>Cuộc trò chuyện mới</span>}
          </button>
        </div>

        {/* Sessions list */}
        {sidebarOpen && (
          <div className="sidebar-search-wrap">
            <Search size={13} className="search-icon" />
            <input
              type="text"
              placeholder="Tìm cuộc trò chuyện..."
              value={sessionSearchQuery}
              onChange={e => setSessionSearchQuery(e.target.value)}
              className="sidebar-search-input"
            />
            {sessionSearchQuery && (
              <button className="search-clear-btn" onClick={() => setSessionSearchQuery('')}>×</button>
            )}
          </div>
        )}

        <div className="sidebar-sessions">
          {isLoadingSessions ? (
            <div className="sidebar-loading">
              {[1,2,3].map(i => (
                <div key={i} className="skeleton" style={{ height: 40, marginBottom: 6 }} />
              ))}
            </div>
          ) : filteredSessions.length === 0 ? (
            sidebarOpen && <p className="sidebar-empty">Không tìm thấy phiên chat</p>
          ) : (
            filteredSessions.map(s => (
              <div
                key={s.id}
                className={`sidebar-session-item ${s.id === activeSessionId ? 'active' : ''}`}
                onClick={() => setActiveSession(s.id)}
                title={s.title}
              >
                <MessageSquare size={14} className="session-icon" />
                {sidebarOpen && (
                  <>
                    <span className="session-title">{s.title}</span>
                    <button
                      className="session-delete"
                      onClick={e => handleDeleteSession(e, s.id)}
                      title="Xóa phiên chat"
                    >
                      <Trash2 size={12} />
                    </button>
                  </>
                )}
              </div>
            ))
          )}
        </div>

        {/* Sidebar footer */}
        <div className="sidebar-footer" style={{ position: 'relative' }}>
          <div 
            className="sidebar-user"
            onClick={(e) => {
              e.stopPropagation();
              setIsProfileDropdownOpen(!isProfileDropdownOpen);
            }}
            style={{ cursor: 'pointer' }}
            title={user?.username}
          >
            <div className="user-avatar">{user?.username?.[0]?.toUpperCase() || 'U'}</div>
            {sidebarOpen && (
              <div className="user-info">
                <span className="user-name">{user?.username}</span>
                <span className="user-role badge badge-primary" style={{ fontSize: '10px', padding: '1px 6px' }}>
                  {user?.role}
                </span>
              </div>
            )}
          </div>

          {/* User Options Popover Dropdown Menu (OpenAI style) */}
          {isProfileDropdownOpen && (
            <div className="profile-popover-menu" onClick={(e) => e.stopPropagation()}>
              <div className="popover-user-email">{user?.email || 'user@legalrag.vn'}</div>
              
              {/* Theme toggles */}
              <div className="popover-theme-toggle">
                <button 
                  className={`theme-toggle-btn ${theme === 'light' ? 'active' : ''}`} 
                  onClick={() => setTheme('light')} 
                  title="Giao diện Sáng"
                >
                  <Sparkles size={14} />
                  <span>Sáng</span>
                </button>
                <button 
                  className={`theme-toggle-btn ${theme === 'dark' ? 'active' : ''}`} 
                  onClick={() => setTheme('dark')} 
                  title="Giao diện Tối"
                >
                  <Scale size={14} />
                  <span>Tối</span>
                </button>
              </div>

              <hr className="popover-divider-line" />

              <button className="popover-action-btn" onClick={() => { setIsProfileDropdownOpen(false); alert("Tài liệu API và hướng dẫn tích hợp RAG nằm trong thư mục docs/ của dự án."); }}>
                <BookOpen size={14} style={{ marginRight: '8px' }} />
                <span>Developer docs</span>
              </button>
              
              <button className="popover-action-btn" onClick={() => { setIsProfileDropdownOpen(false); alert("Tuân thủ các điều khoản bảo mật dữ liệu và luật an ninh mạng."); }}>
                <Shield size={14} style={{ marginRight: '8px' }} />
                <span>Terms & policies</span>
              </button>

              <button className="popover-action-btn" onClick={() => { setIsProfileDropdownOpen(false); alert("Mọi câu hỏi hỗ trợ xin gửi về: support@legalrag.vn"); }}>
                <HelpCircle size={14} style={{ marginRight: '8px' }} />
                <span>Help</span>
              </button>

              <hr className="popover-divider-line" />

              <button className="popover-action-btn logout-action" onClick={() => { setIsProfileDropdownOpen(false); logout(); }}>
                <LogOut size={14} style={{ marginRight: '8px' }} />
                <span>Log out</span>
              </button>
            </div>
          )}
        </div>
      </aside>

      {/* ===== Main Area ===== */}
      <main className="chat-main">
        {/* Chat header bar */}
        <div className="chat-header-bar">
          <div className="chat-header-title">
            {activeSessionId 
              ? (sessions.find(s => s.id === activeSessionId)?.title || 'Cuộc trò chuyện') 
              : 'Cuộc trò chuyện mới'
            }
          </div>
          <div className="chat-header-actions" style={{ display: 'flex', gap: '8px' }}>
            <button 
              className={`chat-export-btn ${isDraftingOpen ? 'active' : ''}`}
              onClick={() => setIsDraftingOpen(!isDraftingOpen)}
              title="Mở trình soạn thảo văn bản pháp lý"
            >
              <FileText size={15} style={{ marginRight: '6px' }} />
              <span>{isDraftingOpen ? 'Đóng Soạn thảo' : 'Soạn thảo văn bản'}</span>
            </button>

            {activeSessionId && messages.length > 0 && (
              <button 
                className="chat-export-btn" 
                onClick={exportChatToMarkdown} 
                title="Xuất lịch sử chat (.md)"
              >
                <Download size={15} style={{ marginRight: '6px' }} />
                <span>Xuất (.md)</span>
              </button>
            )}
          </div>
        </div>

        {/* Welcome screen */}
        {isWelcome && (
          <div className="chat-welcome animate-fade-in">
            <div className="welcome-icon">
              <Scale size={44} />
            </div>
            <h2>Trợ lý Pháp luật Việt Nam</h2>
            <p>
              Hỏi đáp chuyên sâu về Bộ luật Dân sự, Hình sự, Lao động và Hôn nhân Gia đình<br />
              Hỗ trợ ghi âm giọng nói, upload file và phân tích hình ảnh
            </p>
            <div className="welcome-suggestions">
              {SUGGESTIONS.map((q, i) => (
                <button key={i} className="welcome-suggestion" onClick={() => handleSend(q)}>
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Messages area */}
        {!isWelcome && (
          <div className="chat-messages">
            {isLoadingMessages ? (
              <div style={{ padding: '2rem', display: 'flex', flexDirection: 'column', gap: 16 }}>
                {[1,2,3].map(i => (
                  <div key={i} className="skeleton" style={{ height: 60, borderRadius: 12 }} />
                ))}
              </div>
            ) : (
              allMessages.map(msg => (
                <div key={msg.id} className={`chat-msg ${msg.role} animate-fade-in${(msg.isDraftingAck || msg.metadata?.is_drafting_ack) ? ' drafting-ack-msg' : ''}`}>
                  <div className="msg-avatar">
                    {msg.role === 'user' ? <UserIcon size={15} /> : <Bot size={15} />}
                  </div>
                  <div className="msg-bubble">
                    {/* Image preview (for image messages) */}
                    {msg.imagePreview && (
                      <img
                        src={msg.imagePreview}
                        alt="Attached"
                        className="msg-image-preview"
                      />
                    )}
                    {msg.role === 'assistant' ? (
                      <div className="msg-content">
                        {msg.thinking && <ThinkingBlock content={msg.thinking} isStreaming={false} />}
                        {(msg.isDraftingAck || msg.metadata?.is_drafting_ack) && (
                          <div className="drafting-ack-badge">
                            <FileText size={13} />
                            <span>Soạn thảo văn bản</span>
                          </div>
                        )}
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {msg.content}
                        </ReactMarkdown>
                        {msg.sources && <SourcesPanel sources={msg.sources} />}

                        {/* Assistant Actions Footer */}
                        {(msg.isDraftingAck || msg.metadata?.is_drafting_ack) ? (
                          <div className="msg-actions">
                            <button
                              className="msg-action-btn drafting-open-btn"
                              onClick={() => setIsDraftingOpen(true)}
                              title="Mở bảng soạn thảo"
                            >
                              <FileText size={12} />
                              <span style={{ marginLeft: 4 }}>Mở bảng soạn thảo</span>
                            </button>
                          </div>
                        ) : (
                          <div className="msg-actions">
                            <button
                              className={`msg-action-btn tts-btn ${activeTtsMessageId === msg.id ? 'active' : ''}`}
                              onClick={() => handleTts(msg)}
                              title={activeTtsMessageId === msg.id ? 'Dừng đọc' : 'Đọc thành tiếng'}
                            >
                              {activeTtsMessageId === msg.id ? <VolumeX size={12} /> : <Volume2 size={12} />}
                            </button>
                            <span className="actions-divider">|</span>
                            <button
                              className={`msg-action-btn vote-btn ${msg.metadata?.rating === 1 ? 'active up' : ''}`}
                              onClick={() => handleMessageFeedback(msg.id, 1)}
                              title="Hữu ích"
                            >
                              <ThumbsUp size={12} />
                            </button>
                            <button
                              className={`msg-action-btn vote-btn ${msg.metadata?.rating === -1 ? 'active down' : ''}`}
                              onClick={() => handleMessageFeedback(msg.id, -1)}
                              title="Không hữu ích"
                            >
                              <ThumbsDown size={12} />
                            </button>
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="msg-content">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {msg.content}
                        </ReactMarkdown>
                      </div>
                    )}
                  </div>
                </div>
              ))
            )}

            {/* Streaming message */}
            {isStreaming && (
              <div className="chat-msg assistant animate-fade-in">
                <div className="msg-avatar"><Bot size={15} /></div>
                <div className="msg-bubble streaming">
                  <div className="msg-content">
                    {/* ThinkingBlock: stream khi phase=thinking, collapse khi phase=answering/idle */}
                    {streamingThinking && (
                      <ThinkingBlock
                        content={streamingThinking}
                        isStreaming={streamingPhase === 'thinking'}
                      />
                    )}

                    {/* Answer text streaming */}
                    {streamingContent ? (
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {streamingContent}
                      </ReactMarkdown>
                    ) : streamingPhase !== 'thinking' ? (
                      // Chỉ hiện typing dots khi KHÔNG đang trong thinking phase
                      <div className="typing-indicator">
                        <span /><span /><span />
                      </div>
                    ) : null /* đang think → không hiện typing dots */}
                  </div>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        )}

        {/* Chat input area */}
        <div className="chat-input-area-wrapper">
          <ChatInput
            onSend={handleSend}
            onSendFile={handleSendFile}
            onSendImage={handleSendImage}
            isStreaming={isStreaming}
          />
          <p className="chat-hint">
            Enter để gửi · Shift+Enter xuống dòng · Ctrl+V dán ảnh
          </p>
        </div>
      </main>

      {/* ===== Drafting Workspace Panel ===== */}
      <DraftingPanel 
        isOpen={isDraftingOpen} 
        onClose={() => setIsDraftingOpen(false)} 
        sessionId={activeSessionId}
        prefillData={draftingPrefill}
        onPrefillConsumed={() => setDraftingPrefill(null)}
      />

      {/* Settings panel (overlay) */}
      <SettingsPanel />
    </div>
  );
}

// Custom hook for sidebar state with localStorage
function useSidebarState(defaultOpen) {
  const key = 'sidebar_open';
  const [open, setOpen] = useState(() => {
    try { return JSON.parse(localStorage.getItem(key) ?? String(defaultOpen)); }
    catch { return defaultOpen; }
  });
  const setValue = (val) => {
    setOpen(val);
    localStorage.setItem(key, JSON.stringify(val));
  };
  return [open, setValue];
}
