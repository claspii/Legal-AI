/**
 * Settings store — LLM configuration persisted to localStorage.
 * Now uses selected_model_id from admin-managed pool instead of manual provider config.
 */

import { create } from 'zustand';

const DEFAULT_SETTINGS = {
  provider: 'gemini',               // Set by pool selection
  selected_model_id: '',            // ID from model pool
  api_url: '',                       // Set by pool selection
  model_name: '',                    // Set by pool selection
  temperature: 0.7,
  max_tokens: 2048,
  top_p: 0.95,
  top_k: 5,                          // RAG top-k
  use_graph: true,
  reasoning_effort: 'off',           // 'off' | 'low' | 'medium' | 'high' | 'max'
  gemini_model: 'gemini-2.5-flash',
};

const STORAGE_KEY = 'legal_rag_settings';

function loadSettings() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) return { ...DEFAULT_SETTINGS, ...JSON.parse(stored) };
  } catch {}
  return DEFAULT_SETTINGS;
}

export const useSettingsStore = create((set, get) => ({
  ...loadSettings(),
  settingsPanelOpen: false,

  updateSetting: (key, value) => {
    set({ [key]: value });
    // Persist
    const state = get();
    const toSave = {};
    for (const k of Object.keys(DEFAULT_SETTINGS)) toSave[k] = state[k];
    toSave[key] = value;
    localStorage.setItem(STORAGE_KEY, JSON.stringify(toSave));
  },

  toggleSettingsPanel: () => set(s => ({ settingsPanelOpen: !s.settingsPanelOpen })),
  closeSettingsPanel: () => set({ settingsPanelOpen: false }),

  getQuerySettings() {
    const s = get();
    return {
      provider: s.provider,
      top_k: s.top_k,
      use_graph: s.use_graph,
      settings: {
        selected_model_id: s.selected_model_id,
        api_url: s.api_url,
        model_name: s.model_name,
        temperature: s.temperature,
        max_tokens: s.max_tokens,
        top_p: s.top_p,
        reasoning_effort: s.reasoning_effort,
        gemini_model: s.gemini_model,
      },
    };
  },
}));
