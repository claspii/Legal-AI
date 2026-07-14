/**
 * Auth store — Zustand state management for authentication.
 */

import { create } from 'zustand';
import { authService } from '../services/authService';
import { authStorage } from '../utils/authStorage';

export const useAuthStore = create((set, get) => ({
  user: authStorage.getUser(),
  isAuthenticated: !!authStorage.getAccessToken(),
  isLoading: false,
  error: null,

  login: async (email, password, rememberMe = false) => {
    set({ isLoading: true, error: null });
    try {
      const data = await authService.login(email, password);
      authStorage.setTokens(data.access_token, data.refresh_token, rememberMe);
      authStorage.saveUser(data.user);
      set({ user: data.user, isAuthenticated: true, isLoading: false });
      return data;
    } catch (err) {
      const message = err.response?.data?.detail || 'Đăng nhập thất bại.';
      set({ error: message, isLoading: false });
      throw new Error(message);
    }
  },

  register: async (email, username, password) => {
    set({ isLoading: true, error: null });
    try {
      const data = await authService.register(email, username, password);
      set({ isLoading: false });
      return data;
    } catch (err) {
      const message = err.response?.data?.detail || 'Đăng ký thất bại.';
      set({ error: message, isLoading: false });
      throw new Error(message);
    }
  },

  logout: () => {
    authStorage.clear();
    set({ user: null, isAuthenticated: false, error: null });
  },

  fetchMe: async () => {
    try {
      const user = await authService.getMe();
      authStorage.saveUser(user);
      set({ user, isAuthenticated: true });
    } catch {
      get().logout();
    }
  },

  clearError: () => set({ error: null }),
}));
