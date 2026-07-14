/**
 * Chat service — sessions, messages, streaming, file/image upload.
 */

import api from './api';
import { authStorage } from '../utils/authStorage';

const getAuthHeader = () => {
  const token = authStorage.getAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
};

export const chatService = {
  getSessions: () =>
    api.get('/chat/sessions').then(r => r.data),

  createSession: (title) =>
    api.post('/chat/sessions', { title }).then(r => r.data),

  deleteSession: (id) =>
    api.delete(`/chat/sessions/${id}`),

  getMessages: (sessionId) =>
    api.get(`/chat/sessions/${sessionId}/messages`).then(r => r.data),

  rateMessage: (messageId, rating) =>
    api.put(`/chat/messages/${messageId}/feedback`, { rating }).then(r => r.data),

  /**
   * Stream text chat via SSE.
   */
  streamChat: (data) =>
    fetch('/api/v1/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...getAuthHeader() },
      body: JSON.stringify(data),
    }),

  /**
   * Upload a document file and stream legal analysis.
   */
  streamUploadCheck: (file, question, settings = {}) => {
    const form = new FormData();
    form.append('file', file);
    form.append('question', question || 'Phân tích tài liệu này có vi phạm pháp luật không?');
    if (settings.session_id) form.append('session_id', settings.session_id);
    form.append('top_k', settings.top_k ?? 5);
    form.append('use_graph', settings.use_graph !== false ? 'true' : 'false');
    form.append('provider', settings.provider ?? 'custom_trained');
    form.append('api_url', settings.api_url ?? '');
    form.append('model_name', settings.model_name ?? '');
    form.append('temperature', settings.temperature ?? 0.7);
    form.append('max_tokens', settings.max_tokens ?? 2048);
    form.append('enable_thinking', settings.enable_thinking ? 'true' : 'false');

    return fetch('/api/v1/chat/upload-check', {
      method: 'POST',
      headers: getAuthHeader(),
      body: form,
    });
  },

  /**
   * Send an image + question and stream multimodal analysis.
   */
  streamImageQuery: (imageFile, question, settings = {}) => {
    const form = new FormData();
    form.append('image', imageFile);
    form.append('question', question || 'Hình ảnh này liên quan đến luật gì?');
    if (settings.session_id) form.append('session_id', settings.session_id);
    form.append('top_k', settings.top_k ?? 5);
    form.append('use_graph', settings.use_graph !== false ? 'true' : 'false');
    form.append('provider', settings.provider ?? 'custom_trained');
    form.append('api_url', settings.api_url ?? '');
    form.append('model_name', settings.model_name ?? '');
    form.append('temperature', settings.temperature ?? 0.7);
    form.append('max_tokens', settings.max_tokens ?? 2048);
    form.append('enable_thinking', settings.enable_thinking ? 'true' : 'false');

    return fetch('/api/v1/chat/query-with-image', {
      method: 'POST',
      headers: getAuthHeader(),
      body: form,
    });
  },
};
