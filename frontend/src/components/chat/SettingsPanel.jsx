/**
 * LLM Settings Panel — slide-in panel for selecting model from admin pool + tuning params.
 * Model selection via popup modal (similar to scoring tab).
 */

import { useState, useEffect } from 'react';
import { useSettingsStore } from '../../stores/settingsStore';
import { X, Settings, Brain, Sliders, Cpu, ChevronDown, Search, Check } from 'lucide-react';
import api from '../../services/api';
import './SettingsPanel.css';

// Reasoning effort levels
const REASONING_EFFORTS = [
  { value: 'off',    label: 'Off',    hint: 'Không suy luận',    budget: 0 },
  { value: 'low',    label: 'Low',    hint: 'Max 512 tokens',    budget: 512 },
  { value: 'medium', label: 'Medium', hint: 'Max 2,048 tokens',  budget: 2048 },
  { value: 'high',   label: 'High',   hint: 'Max 8,192 tokens',  budget: 8192 },
  { value: 'max',    label: 'Max',    hint: 'Unlimited',         budget: -1 },
];

const PROVIDER_ICONS = {
  gemini: '✨',
  openrouter: '🌐',
  custom_trained: '🤖',
};

export default function SettingsPanel() {
  const store = useSettingsStore();
  const [availableModels, setAvailableModels] = useState([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [showModelPicker, setShowModelPicker] = useState(false);
  const [modelSearch, setModelSearch] = useState('');

  // Fetch models from pool when panel opens
  useEffect(() => {
    if (store.settingsPanelOpen) {
      setLoadingModels(true);
      api.get('/chat/available-models')
        .then(res => setAvailableModels(res.data.models || []))
        .catch(() => {})
        .finally(() => setLoadingModels(false));
    }
  }, [store.settingsPanelOpen]);

  if (!store.settingsPanelOpen) return null;

  const update = store.updateSetting;
  const selectedModel = availableModels.find(m => m.id === store.selected_model_id);

  const handleSelectModel = (model) => {
    update('selected_model_id', model.id);
    update('provider', model.provider);
    update('api_url', model.api_url || '');
    update('model_name', model.model_name || '');
    if (model.provider === 'gemini') {
      update('gemini_model', model.model_id || 'gemini-2.5-flash');
    }
    setShowModelPicker(false);
    setModelSearch('');
  };

  const filteredModels = availableModels.filter(m =>
    (m.display_name || m.model_id || '').toLowerCase().includes(modelSearch.toLowerCase())
  );

  // Group by provider
  const grouped = {};
  filteredModels.forEach(m => {
    const g = m.provider || 'other';
    if (!grouped[g]) grouped[g] = [];
    grouped[g].push(m);
  });

  const providerGroupLabel = (p) => {
    if (p === 'gemini') return '✨ Gemini';
    if (p === 'openrouter') return '🌐 OpenRouter';
    if (p === 'custom_trained') return '🤖 Custom Model';
    return p;
  };

  return (
    <>
      {/* Backdrop */}
      <div className="settings-backdrop" onClick={store.closeSettingsPanel} />

      {/* Panel */}
      <div className="settings-panel">
        <div className="settings-header">
          <div className="settings-title">
            <Settings size={18} />
            <span>Cài đặt Model</span>
          </div>
          <button className="btn btn-ghost btn-icon btn-sm" onClick={store.closeSettingsPanel}>
            <X size={16} />
          </button>
        </div>

        <div className="settings-body">

          {/* Model Selection */}
          <div className="settings-section">
            <h4 className="settings-section-title">
              <Cpu size={14} /> Model đang dùng
            </h4>

            {loadingModels ? (
              <div className="model-picker-loading">Đang tải...</div>
            ) : (
              <button
                className="model-picker-trigger"
                onClick={() => setShowModelPicker(true)}
              >
                {selectedModel ? (
                  <div className="model-picker-selected">
                    <span className="model-picker-icon">{PROVIDER_ICONS[selectedModel.provider] || '⚙️'}</span>
                    <div className="model-picker-info">
                      <span className="model-picker-name">{selectedModel.display_name}</span>
                      <span className="model-picker-detail">
                        {selectedModel.provider === 'gemini' ? selectedModel.model_id : selectedModel.model_name || selectedModel.provider}
                      </span>
                    </div>
                  </div>
                ) : (
                  <div className="model-picker-placeholder">
                    <Cpu size={16} />
                    <span>Chọn model...</span>
                  </div>
                )}
                <ChevronDown size={14} className="model-picker-chevron" />
              </button>
            )}

            {availableModels.length === 0 && !loadingModels && (
              <div className="model-picker-empty">
                Admin cần thêm model qua Admin Panel → Model Pool.
              </div>
            )}
          </div>

          {/* Generation Parameters */}
          <div className="settings-section">
            <h4 className="settings-section-title">
              <Sliders size={14} /> Tham số sinh văn bản
            </h4>

            <div className="settings-field">
              <label>Temperature <span className="setting-value">{store.temperature}</span></label>
              <input
                type="range" min="0" max="2" step="0.05"
                value={store.temperature}
                onChange={e => update('temperature', parseFloat(e.target.value))}
                className="range-slider"
              />
              <div className="range-labels"><span>0</span><span>1</span><span>2</span></div>
            </div>

            <div className="settings-field">
              <label>Max Tokens <span className="setting-value">{store.max_tokens}</span></label>
              <input
                type="range" min="256" max="8192" step="256"
                value={store.max_tokens}
                onChange={e => update('max_tokens', parseInt(e.target.value))}
                className="range-slider"
              />
              <div className="range-labels"><span>256</span><span>4096</span><span>8192</span></div>
            </div>

            <div className="settings-field">
              <label>Top-P <span className="setting-value">{store.top_p}</span></label>
              <input
                type="range" min="0" max="1" step="0.05"
                value={store.top_p}
                onChange={e => update('top_p', parseFloat(e.target.value))}
                className="range-slider"
              />
            </div>
          </div>

          {/* RAG Settings */}
          <div className="settings-section">
            <h4 className="settings-section-title">
              <Brain size={14} /> RAG Settings
            </h4>
            <div className="settings-field">
              <label>Top-K Documents <span className="setting-value">{store.top_k}</span></label>
              <input
                type="range" min="1" max="20" step="1"
                value={store.top_k}
                onChange={e => update('top_k', parseInt(e.target.value))}
                className="range-slider"
              />
              <div className="range-labels"><span>1</span><span>10</span><span>20</span></div>
            </div>
            <div className="settings-field">
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={store.use_graph}
                  onChange={e => update('use_graph', e.target.checked)}
                />
                <span>Use Knowledge Graph</span>
              </label>
            </div>
          </div>

        </div>

        <div className="settings-footer">
          <span className="settings-note">Cài đặt được lưu tự động</span>
        </div>
      </div>

      {/* Model Picker Modal */}
      {showModelPicker && (
        <>
          <div className="model-picker-overlay" onClick={() => { setShowModelPicker(false); setModelSearch(''); }} />
          <div className="model-picker-modal">
            <div className="model-picker-modal-header">
              <h3>Chọn Model</h3>
              <button className="btn btn-ghost btn-icon btn-sm" onClick={() => { setShowModelPicker(false); setModelSearch(''); }}>
                <X size={16} />
              </button>
            </div>

            {/* Search */}
            <div className="model-picker-search">
              <Search size={14} />
              <input
                type="text"
                placeholder="Tìm model..."
                value={modelSearch}
                onChange={e => setModelSearch(e.target.value)}
                autoFocus
              />
            </div>

            {/* Model list */}
            <div className="model-picker-list">
              {filteredModels.length === 0 ? (
                <div className="model-picker-no-results">Không tìm thấy model phù hợp.</div>
              ) : (
                Object.entries(grouped).map(([provider, models]) => (
                  <div key={provider}>
                    <div className="model-picker-group-label">{providerGroupLabel(provider)}</div>
                    {models.map(m => (
                      <button
                        key={m.id}
                        className={`model-picker-item ${store.selected_model_id === m.id ? 'active' : ''}`}
                        onClick={() => handleSelectModel(m)}
                      >
                        <div className="model-picker-item-left">
                          <span className="model-picker-item-icon">{PROVIDER_ICONS[m.provider] || '⚙️'}</span>
                          <div>
                            <div className="model-picker-item-name">{m.display_name}</div>
                            <div className="model-picker-item-desc">
                              {m.provider === 'gemini' ? m.model_id : m.model_name || m.model_id || m.provider}
                            </div>
                          </div>
                        </div>
                        {store.selected_model_id === m.id && (
                          <Check size={16} className="model-picker-item-check" />
                        )}
                      </button>
                    ))}
                  </div>
                ))
              )}
            </div>
          </div>
        </>
      )}
    </>
  );
}
