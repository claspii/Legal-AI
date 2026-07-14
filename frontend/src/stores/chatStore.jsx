/**
 * Chat store — sessions, messages, SSE streaming.
 * Supports text, file upload, and image queries.
 */

import { create } from 'zustand';
import { chatService } from '../services/chatService';
import api from '../services/api';
import toast from 'react-hot-toast';


/**
 * Parses <think>...</think> blocks out of model output.
 * Returns { thinking, answer, phase: 'thinking' | 'answering' | 'idle' }
 */
function parseThinking(text) {
  if (!text) return { thinking: '', answer: '', phase: 'idle' };
  const OPEN = '<think>';
  const CLOSE = '</think>';
  const start = text.indexOf(OPEN);
  const end = text.indexOf(CLOSE);

  // <think>...</think>answer
  if (start !== -1 && end > start) {
    const thinking = text.slice(start + OPEN.length, end).trim();
    const answer = text.slice(end + CLOSE.length).trim();
    return { thinking, answer, phase: answer ? 'answering' : 'idle' };
  }
  // <think>... (no closing tag yet — still thinking)
  if (start !== -1 && end === -1) {
    return { thinking: text.slice(start + OPEN.length), answer: '', phase: 'thinking' };
  }
  // No <think> at all — plain answer
  return { thinking: '', answer: text, phase: 'answering' };
}


function mapMessages(messages) {
  if (!messages) return [];
  return messages.map(msg => {
    let thinking = msg.thinking || msg.reasoning || '';
    let content = msg.content || '';
    if (content.includes('<think>')) {
      const parsed = parseThinking(content);
      if (parsed.thinking) {
        thinking = parsed.thinking;
        content = parsed.answer;
      }
    }
    return {
      ...msg,
      content,
      thinking
    };
  });
}



export const useChatStore = create((set, get) => ({
  sessions: [],
  activeSessionId: null,
  messages: [],
  isStreaming: false,
  streamingContent: '',
  streamingThinking: '',
  streamingPhase: 'idle', // 'thinking' | 'answering' | 'idle'
  streamingSources: null,
  isLoadingSessions: false,
  isLoadingMessages: false,
  // Drafting intent — set when chatbot detects user wants to draft a document
  draftingIntent: null, // null | { document_type, template_hint, extracted_inputs, short_response }

  clearDraftingIntent: () => set({ draftingIntent: null }),

  // ---- Sessions ----
  fetchSessions: async () => {
    set({ isLoadingSessions: true });
    try {
      const data = await chatService.getSessions();
      set({ sessions: data.sessions, isLoadingSessions: false });
    } catch {
      set({ isLoadingSessions: false });
    }
  },

  createSession: async (title) => {
    try {
      const session = await chatService.createSession(title);
      set(s => ({
        sessions: [session, ...s.sessions],
        activeSessionId: session.id,
        messages: [],
      }));
      return session;
    } catch (err) {
      console.error('Failed to create session:', err);
    }
  },

  deleteSession: async (id) => {
    try {
      await chatService.deleteSession(id);
      set(s => ({
        sessions: s.sessions.filter(x => x.id !== id),
        activeSessionId: s.activeSessionId === id ? null : s.activeSessionId,
        messages: s.activeSessionId === id ? [] : s.messages,
      }));
    } catch (err) {
      console.error('Failed to delete session:', err);
    }
  },

  setActiveSession: async (id) => {
    set({ activeSessionId: id, isLoadingMessages: true, messages: [] });
    try {
      const data = await chatService.getMessages(id);
      set({ messages: mapMessages(data.messages), isLoadingMessages: false });
    } catch {
      set({ isLoadingMessages: false });
    }
  },

  clearSession: () => set({ activeSessionId: null, messages: [] }),

  // ---- Shared SSE reader ----
  _readSSEStream: async (response) => {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let fullAnswer = '';
    let sessionId = get().activeSessionId;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      let currentEvent = null;
      for (const line of lines) {
        if (line.startsWith('event: ')) {
          currentEvent = line.slice(7).trim();
        } else if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6));
            if (currentEvent === 'session' && data.session_id) {
              sessionId = data.session_id;
              set({ activeSessionId: sessionId });
              get().fetchSessions();
            } else if (currentEvent === 'answer' && data.content !== undefined) {
              fullAnswer = data.content;
              const { thinking, answer, phase } = parseThinking(fullAnswer);
              set({ streamingContent: answer, streamingThinking: thinking, streamingPhase: phase });
            } else if (currentEvent === 'sources') {
              set({ streamingSources: data.content });
            } else if (currentEvent === 'error') {
              const msg = data.message || 'Lỗi không xác định';
              console.error('Stream error:', msg);
              // Show toast instead of polluting chat
              toast.error(msg, { duration: 6000 });
              fullAnswer = ''; // no message added to chat
              set({ streamingContent: '', streamingThinking: '' });
            }
          } catch { /* skip malformed */ }
        }
      }
    }

    return { fullAnswer, sessionId };
  },

  _resetStreaming: () => set({
    isStreaming: false,
    streamingContent: '',
    streamingThinking: '',
    streamingPhase: 'idle',
    streamingSources: null,
  }),

  // ---- Text chat ----
  sendMessage: async (question, querySettings = {}) => {
    const state = get();
    const userMsg = {
      id: `u-${Date.now()}`,
      role: 'user',
      content: question,
      created_at: new Date().toISOString(),
    };
    set(s => ({ messages: [...s.messages, userMsg] }));

    // 1. Check for drafting intent first (non-blocking, fast regex on backend)
    try {
      const intentRes = await api.post('/drafting/detect-intent', {
        message: question,
        session_id: state.activeSessionId || null
      });
      const intent = intentRes.data;
      if (intent.is_drafting_intent && intent.confidence >= 0.7) {
        if (intent.session_id) {
          // Load the session messages from DB (which includes the persisted user + ack messages)
          set({ activeSessionId: intent.session_id });
          get().fetchSessions();
          // Load messages for this session from DB
          try {
            const data = await chatService.getMessages(intent.session_id);
            set({ messages: mapMessages(data.messages), isLoadingMessages: false });
          } catch {
            // If we can't load from DB, keep the optimistic messages
            const ackMsg = {
              id: `a-${Date.now()}`,
              role: 'assistant',
              content: intent.short_response || 'Tôi sẽ giúp bạn soạn thảo văn bản pháp lý. Vui lòng kiểm tra bảng soạn thảo bên phải.',
              created_at: new Date().toISOString(),
              isDraftingAck: true,
            };
            set(s => ({ messages: [...s.messages, ackMsg] }));
          }
        } else {
          // Same session — add ack optimistically
          const ackMsg = {
            id: `a-${Date.now()}`,
            role: 'assistant',
            content: intent.short_response || 'Tôi sẽ giúp bạn soạn thảo văn bản pháp lý. Vui lòng kiểm tra bảng soạn thảo bên phải.',
            created_at: new Date().toISOString(),
            isDraftingAck: true,
          };
          set(s => ({ messages: [...s.messages, ackMsg] }));
        }
        // Trigger DraftingPanel auto-open with pre-filled data
        set({ draftingIntent: intent });
        return; // Don't proceed with RAG query — the panel handles the rest
      }
    } catch (intentErr) {
      // Silently ignore intent detection errors — proceed with normal flow
      console.debug('Intent detection skipped:', intentErr);
    }

    // 2. Normal RAG chat streaming
    set({ isStreaming: true, streamingContent: '', streamingThinking: '', streamingSources: null });

    try {
      const response = await chatService.streamChat({
        question,
        session_id: state.activeSessionId,
        top_k: querySettings.top_k ?? 5,
        use_graph: querySettings.use_graph !== false,
        provider: querySettings.provider ?? 'custom_trained',
        // Pass ALL settings as-is — backend maps reasoning_effort → thinking_budget
        settings: {
          ...(querySettings.settings ?? {}),
        },
      });

      const { fullAnswer } = await get()._readSSEStream(response);
      if (fullAnswer) {
        const { thinking, answer } = parseThinking(fullAnswer);
        set(s => ({
          messages: [...s.messages, {
            id: `a-${Date.now()}`, role: 'assistant',
            content: answer, thinking,
            sources: get().streamingSources,
            created_at: new Date().toISOString(),
          }],
        }));
      }
    } catch (err) {
      console.error('Chat stream error:', err);
    } finally {
      get()._resetStreaming();
    }
  },

  // ---- File upload legal check ----
  sendFile: async (file, question, querySettings = {}) => {
    const userMsg = {
      id: `u-${Date.now()}`,
      role: 'user',
      content: `📎 **${file.name}**\n\n${question}`,
      created_at: new Date().toISOString(),
    };
    set(s => ({ messages: [...s.messages, userMsg] }));
    set({ isStreaming: true, streamingContent: '', streamingThinking: '', streamingSources: null });

    try {
      const response = await chatService.streamUploadCheck(file, question, {
        session_id: get().activeSessionId,
        ...querySettings,
        ...querySettings.settings,
      });

      const { fullAnswer } = await get()._readSSEStream(response);
      if (fullAnswer) {
        const { thinking, answer } = parseThinking(fullAnswer);
        set(s => ({
          messages: [...s.messages, {
            id: `a-${Date.now()}`, role: 'assistant',
            content: answer, thinking, sources: get().streamingSources,
            created_at: new Date().toISOString(),
          }],
        }));
      }
    } catch (err) {
      console.error('File upload error:', err);
    } finally {
      get()._resetStreaming();
    }
  },

  // ---- Image query ----
  sendImage: async (imageFile, question, querySettings = {}) => {
    const userMsg = {
      id: `u-${Date.now()}`,
      role: 'user',
      content: `🖼️ **${imageFile.name}**\n\n${question}`,
      created_at: new Date().toISOString(),
      imagePreview: URL.createObjectURL(imageFile),
    };
    set(s => ({ messages: [...s.messages, userMsg] }));
    set({ isStreaming: true, streamingContent: '', streamingThinking: '', streamingSources: null });

    try {
      const response = await chatService.streamImageQuery(imageFile, question, {
        session_id: get().activeSessionId,
        ...querySettings,
        ...querySettings.settings,
      });

      const { fullAnswer } = await get()._readSSEStream(response);
      if (fullAnswer) {
        const { thinking, answer } = parseThinking(fullAnswer);
        set(s => ({
          messages: [...s.messages, {
            id: `a-${Date.now()}`, role: 'assistant',
            content: answer, thinking, sources: get().streamingSources,
            created_at: new Date().toISOString(),
          }],
        }));
      }
    } catch (err) {
      console.error('Image query error:', err);
    } finally {
      get()._resetStreaming();
    }
  },

  rateMessage: async (messageId, rating) => {
    try {
      await chatService.rateMessage(messageId, rating);
      set(state => ({
        messages: state.messages.map(m => 
          m.id === messageId 
            ? { ...m, metadata: { ...(m.metadata || {}), rating } } 
            : m
        )
      }));
      toast.success(rating === 1 ? '👍 Đã thích câu trả lời' : rating === -1 ? '👎 Đã phản hồi chất lượng kém' : 'Đã xóa đánh giá');
      return true;
    } catch (err) {
      console.error('Failed to rate message:', err);
      toast.error('Không thể lưu đánh giá');
      return false;
    }
  },
}));
