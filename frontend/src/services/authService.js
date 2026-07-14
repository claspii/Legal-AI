/**
 * Auth service — login, register, profile.
 */

import api from './api';

export const authService = {
  login: (email, password) =>
    api.post('/auth/login', { email, password }).then(r => r.data),

  register: (email, username, password) =>
    api.post('/auth/register', { email, username, password }).then(r => r.data),

  getMe: () =>
    api.get('/auth/me').then(r => r.data),

  updateMe: (data) =>
    api.put('/auth/me', data).then(r => r.data),

  refresh: (refreshToken) =>
    api.post('/auth/refresh', { refresh_token: refreshToken }).then(r => r.data),
};
