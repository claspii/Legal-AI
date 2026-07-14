import { useState, useEffect, useRef } from 'react';
import api from '../../services/api';
import { authStorage } from '../../utils/authStorage';
import { useSettingsStore } from '../../stores/settingsStore';
import { useChatStore } from '../../stores/chatStore';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { 
  FileText, Upload, Download, Copy, Check, Edit3, Eye, 
  Settings, Loader, Sparkles, AlertCircle, X, ChevronRight, HelpCircle
} from 'lucide-react';
import toast from 'react-hot-toast';
import './DraftingPanel.css';

export default function DraftingPanel({ isOpen, onClose, sessionId, prefillData, onPrefillConsumed }) {
  const { getQuerySettings } = useSettingsStore();

  const [templates, setTemplates] = useState([]);
  const [selectedTemplate, setSelectedTemplate] = useState(null);
  const [inputs, setInputs] = useState({});
  const [customInstructions, setCustomInstructions] = useState('');
  
  // Style Guide state
  const [styleGuide, setStyleGuide] = useState({
    font_name: "Times New Roman",
    font_size_body: "12pt",
    alignment: "justify",
    line_spacing: "1.15"
  });
  
  const [referenceName, setReferenceName] = useState('');
  const [isAnalyzingRef, setIsAnalyzingRef] = useState(false);
  
  // Editor State
  const [documentContent, setDocumentContent] = useState('');
  const [editMode, setEditMode] = useState('preview'); // 'edit' | 'preview'
  const [isGenerating, setIsGenerating] = useState(false);
  const [copied, setCopied] = useState(false);
  
  const abortControllerRef = useRef(null);
  const fileInputRef = useRef(null);
  const generateRef = useRef(null); // ref to trigger generate from prefill
  const selectRef = useRef(null);    // ref to the template <select>

  // Intent banner state (shown when chatbot auto-triggers the panel)
  const [intentBanner, setIntentBanner] = useState(null); // string | null

  // Auto-prefill form when chatbot detects drafting intent
  useEffect(() => {
    if (!prefillData || !isOpen || templates.length === 0) return;

    const { document_type, template_hint, template_name, extracted_inputs, short_response } = prefillData;

    // Show an informational banner
    setIntentBanner(
      document_type
        ? `✨ Đã phát hiện ý định soạn thảo "${document_type}". Dữ liệu đã được điền sẵn — hãy kiểm tra và chỉnh sửa nếu cần.`
        : '✨ Đã phát hiện ý định soạn thảo văn bản pháp lý. Vui lòng chọn mẫu và kiểm tra thông tin.'
    );

    // Remove Vietnamese accents/diacritics for clean string matching
    const removeDiacritics = (str) => {
      if (!str) return '';
      return str
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .replace(/đ/g, 'd')
        .replace(/Đ/g, 'D');
    };

    // Try to match template: 1) by exact name, 2) by normalized name/hint
    let matchedTemplate = null;
    if (template_name) {
      // Exact name match first (most precise)
      const normTemplateName = removeDiacritics(template_name).toLowerCase();
      matchedTemplate = templates.find(t =>
        removeDiacritics(t.name || '').toLowerCase() === normTemplateName
      );
    }
    if (!matchedTemplate && template_hint) {
      // Fuzzy match by normalized hint against template names/categories
      const hintNorm = removeDiacritics(template_hint).toLowerCase().replace(/_/g, ' ');
      matchedTemplate = templates.find(t => {
        const nameNorm = removeDiacritics(t.name || '').toLowerCase();
        const catNorm = removeDiacritics(t.category || '').toLowerCase();
        return nameNorm.includes(hintNorm) || hintNorm.includes(nameNorm.split(' ').slice(0, 3).join(' '));
      });
    }

    if (matchedTemplate) {
      setSelectedTemplate(matchedTemplate);

      // Merge extracted inputs with template defaults
      const mergedInputs = {};
      if (matchedTemplate.placeholders) {
        matchedTemplate.placeholders.forEach(p => {
          mergedInputs[p.key] = extracted_inputs?.[p.key] || p.default || '';
        });
      }
      // Also apply any extra extracted keys not in placeholders
      if (extracted_inputs) {
        Object.keys(extracted_inputs).forEach(k => {
          if (extracted_inputs[k]) {
            mergedInputs[k] = extracted_inputs[k];
          }
        });
      }
      setInputs(mergedInputs);

      // Update live preview
      if (matchedTemplate.content) {
        let content = matchedTemplate.content;
        Object.keys(mergedInputs).forEach(k => {
          content = content.replace(new RegExp(`\\{\\{${k}\\}\\}`, 'g'), mergedInputs[k]);
        });
        setDocumentContent(content);
      }

      // Auto-trigger generation after a short delay
      setTimeout(() => {
        if (generateRef.current) {
          generateRef.current();
        }
      }, 600);
    } else if (extracted_inputs && Object.keys(extracted_inputs).length > 0) {
      // No template matched, but we have some inputs — set them as custom instructions
      const extractedSummary = Object.entries(extracted_inputs)
        .map(([k, v]) => `${k}: ${v}`)
        .join(', ');
      setCustomInstructions(prev => {
        const suffix = `\n[Dữ liệu trích xuất: ${extractedSummary}]`;
        return prev + suffix;
      });
    }

    // Clear prefill so it doesn't re-run
    if (onPrefillConsumed) onPrefillConsumed();

    // Auto-dismiss banner after 6 seconds
    const timer = setTimeout(() => setIntentBanner(null), 6000);
    return () => clearTimeout(timer);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefillData, isOpen, templates]);

  // Fetch templates
  useEffect(() => {
    if (isOpen) {
      fetchTemplates();
    }
  }, [isOpen]);

  const fetchTemplates = async () => {
    try {
      const res = await api.get('/drafting/templates');
      setTemplates(res.data || []);
    } catch (err) {
      console.error("Lỗi khi tải mẫu soạn thảo", err);
      toast.error("Không thể tải danh sách mẫu văn bản.");
    }
  };

  const handleTemplateChange = (e) => {
    const templateId = e.target.value;
    if (!templateId) {
      setSelectedTemplate(null);
      setInputs({});
      setDocumentContent('');
      return;
    }
    
    const template = templates.find(t => t.id === templateId);
    setSelectedTemplate(template);
    
    // Set default values for inputs
    const initialInputs = {};
    if (template?.placeholders) {
      template.placeholders.forEach(p => {
        initialInputs[p.key] = p.default || '';
      });
    }
    setInputs(initialInputs);
    
    // Apply template content immediately to preview
    let content = template?.content || '';
    Object.keys(initialInputs).forEach(key => {
      content = content.replace(new RegExp(`\\{\\{${key}\\}\\}`, 'g'), initialInputs[key]);
    });
    setDocumentContent(content);
  };

  const handleInputChange = (key, value) => {
    const nextInputs = { ...inputs, [key]: value };
    setInputs(nextInputs);
    
    // Update live content if we have a template
    if (selectedTemplate) {
      let content = selectedTemplate.content;
      Object.keys(nextInputs).forEach(k => {
        content = content.replace(new RegExp(`\\{\\{${k}\\}\\}`, 'g'), nextInputs[k]);
      });
      setDocumentContent(content);
    }
  };

  const handleFileUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    
    const ext = '.' + file.name.split('.').pop().toLowerCase();
    if (!['.docx', '.pdf'].includes(ext)) {
      toast.error("Vui lòng tải lên file định dạng .docx hoặc .pdf");
      return;
    }

    const formData = new FormData();
    formData.append('file', file);
    
    setIsAnalyzingRef(true);
    setReferenceName(file.name);
    const toastId = toast.loading(`Đang phân tích cấu trúc: ${file.name}...`);
    
    try {
      const res = await api.post('/drafting/analyze-reference', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      
      if (res.data.success && res.data.style_guide) {
        setStyleGuide(res.data.style_guide);
        toast.success("Đã trích xuất phong cách và căn lề thành công!", { id: toastId });
      }
    } catch (err) {
      console.error("Lỗi phân tích file", err);
      toast.error(err.response?.data?.detail || "Không thể phân tích file mẫu", { id: toastId });
      setReferenceName('');
    } finally {
      setIsAnalyzingRef(false);
    }
  };

  const handleGenerateDraft = async () => {
    if (isGenerating) {
      // Abort active stream
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      setIsGenerating(false);
      return;
    }

    const s = getQuerySettings();
    if (!s.provider) {
      toast.error("Vui lòng cấu hình Model ở phần Settings chat trước khi soạn thảo!");
      return;
    }

    // Prepare SSE connection
    const controller = new AbortController();
    abortControllerRef.current = controller;
    
    setIsGenerating(true);
    setEditMode('preview'); // Show content as it loads
    setDocumentContent('');
    
    const token = authStorage.getAccessToken();
    // Resolve model name: Gemini uses gemini_model, custom/openai use model_name
    const resolvedModelName = s.provider === 'gemini'
      ? (s.settings?.gemini_model || 'gemini-2.5-flash')
      : (s.settings?.model_name || '');

    const payload = {
      template_id: selectedTemplate?.id || null,
      reference_style_guide: referenceName ? styleGuide : null,
      user_inputs: inputs,
      custom_instructions: customInstructions,
      session_id: sessionId || null,
      provider: s.provider,
      api_url: s.settings?.api_url || '',
      model_name: resolvedModelName,
      selected_model_id: s.settings?.selected_model_id || null,
      temperature: s.settings?.temperature ?? 0.7,
      max_tokens: s.settings?.max_tokens ?? 3000,
      use_rag: true
    };

    try {
      const response = await fetch('/api/v1/drafting/generate', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {})
        },
        body: JSON.stringify(payload),
        signal: controller.signal
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

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
              if (currentEvent === 'answer' && data.content !== undefined) {
                setDocumentContent(data.content);
              } else if (currentEvent === 'done') {
                toast.success("Đã hoàn tất soạn thảo văn bản!");
                setEditMode('preview');
                if (sessionId) {
                  useChatStore.getState().setActiveSession(sessionId);
                }
              } else if (currentEvent === 'error') {
                toast.error(data.message || 'Lỗi soạn thảo');
              }
            } catch (err) {
              // Ignore partial JSON parsing errors
            }
          }
        }
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        toast.info("Đã dừng soạn thảo.");
      } else {
        console.error("SSE stream error", err);
        toast.error("Lỗi trong quá trình kết nối với AI soạn thảo.");
      }
    } finally {
      setIsGenerating(false);
      abortControllerRef.current = null;
    }
  };

  // Keep generateRef always pointing to latest handleGenerateDraft
  useEffect(() => {
    generateRef.current = handleGenerateDraft;
  });

  const handleExport = async (format) => {
    if (!documentContent.trim()) {
      toast.error("Nội dung văn bản trống!");
      return;
    }

    const toastId = toast.loading(`Đang kết xuất tệp ${format.toUpperCase()}...`);
    try {
      const res = await api.post('/drafting/export', {
        markdown: documentContent,
        format: format,
        style_guide: styleGuide
      }, { responseType: 'blob' });
      
      const blob = new Blob([res.data], {
        type: format === 'pdf' ? 'application/pdf' : 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
      });
      
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `van_ban_phap_ly.${format}`);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      
      toast.success(`Tải tệp ${format.toUpperCase()} thành công!`, { id: toastId });
    } catch (err) {
      console.error(`Export ${format} failed`, err);
      toast.error(`Không thể kết xuất tệp ${format.toUpperCase()}. Vui lòng thử lại.`, { id: toastId });
    }
  };

  const handleCopyMarkdown = () => {
    navigator.clipboard.writeText(documentContent);
    setCopied(true);
    toast.success("Đã sao chép Markdown vào clipboard!");
    setTimeout(() => setCopied(false), 2000);
  };

  if (!isOpen) return null;

  return (
    <div className="drafting-panel-container">
      {/* Configuration Column */}
      <div className="drafting-sidebar-options">
        <div className="drafting-sidebar-header">
          <FileText size={18} className="header-icon" />
          <h3>Cấu hình Soạn thảo</h3>
          <button className="close-btn" onClick={onClose} title="Đóng bảng">
            <X size={18} />
          </button>
        </div>

        <div className="drafting-sidebar-content">
          {/* Intent detection banner */}
          {intentBanner && (
            <div className="intent-banner animate-fade-in">
              <span className="intent-banner-text">{intentBanner}</span>
              <button className="intent-banner-close" onClick={() => setIntentBanner(null)}>×</button>
            </div>
          )}

          {/* Step 1: Chọn mẫu */}
          <div className="option-section">
            <label className="section-label">1. Chọn mẫu văn bản</label>
            <select 
              ref={selectRef} 
              className="form-select" 
              onChange={handleTemplateChange} 
              value={selectedTemplate?.id || ""}
            >
              <option value="">-- Tự soạn thảo tự do --</option>
              {templates.map(t => (
                <option key={t.id} value={t.id}>{t.name} ({t.category})</option>
              ))}
            </select>
            {selectedTemplate && (
              <p className="template-desc">{selectedTemplate.description}</p>
            )}
          </div>

          {/* Dynamic Inputs for Placeholders */}
          {selectedTemplate && selectedTemplate.placeholders && selectedTemplate.placeholders.length > 0 && (
            <div className="option-section animate-fade-in">
              <label className="section-label">Thông tin mẫu văn bản</label>
              <div className="placeholders-form-grid">
                {selectedTemplate.placeholders.map(p => (
                  <div key={p.key} className="form-group">
                    <label>{p.label}</label>
                    <input
                      type={p.type === 'number' ? 'number' : p.type === 'date' ? 'date' : 'text'}
                      value={inputs[p.key] || ''}
                      onChange={(e) => handleInputChange(p.key, e.target.value)}
                      placeholder={p.default || ''}
                      className="form-input"
                    />
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Step 2: Upload Reference Style */}
          <div className="option-section">
            <label className="section-label">2. Tài liệu căn lề tham khảo (Tùy chọn)</label>
            <div 
              className="style-upload-area" 
              onClick={() => fileInputRef.current?.click()}
            >
              <Upload size={20} className="upload-icon" />
              {isAnalyzingRef ? (
                <div className="upload-loading">
                  <Loader size={16} className="spinner" />
                  <span>Đang trích xuất style...</span>
                </div>
              ) : referenceName ? (
                <div className="upload-success">
                  <span className="file-name">{referenceName}</span>
                  <span className="file-hint">Bấm để thay đổi</span>
                </div>
              ) : (
                <div className="upload-placeholder">
                  <span>Tải lên file .docx hoặc .pdf mẫu</span>
                  <span className="file-hint">AI sẽ trích xuất phong cách và font chữ</span>
                </div>
              )}
            </div>
            <input 
              type="file" 
              ref={fileInputRef} 
              onChange={handleFileUpload} 
              accept=".docx,.pdf" 
              style={{ display: 'none' }} 
            />

            {referenceName && styleGuide && (
              <div className="extracted-style-guide">
                <h5>Định dạng trích xuất:</h5>
                <ul>
                  <li><strong>Font:</strong> {styleGuide.font_name}</li>
                  <li><strong>Cỡ chữ:</strong> {styleGuide.font_size_body}</li>
                  <li><strong>Căn lề:</strong> {styleGuide.alignment}</li>
                </ul>
              </div>
            )}
          </div>

          {/* Step 3: Custom Instruction */}
          <div className="option-section">
            <label className="section-label">3. Yêu cầu tùy chỉnh bổ sung</label>
            <textarea
              className="form-textarea"
              placeholder="Ví dụ: Bổ sung điều khoản phạt vi phạm 10% giá trị hợp đồng nếu giao hàng chậm trễ, miễn trừ trách nhiệm do thiên tai..."
              value={customInstructions}
              onChange={(e) => setCustomInstructions(e.target.value)}
              rows={4}
            />
          </div>

          {/* Step 4: Action button */}
          <button 
            className={`btn-generate-document ${isGenerating ? 'cancel-btn' : ''}`}
            onClick={handleGenerateDraft}
          >
            {isGenerating ? (
              <>
                <Loader size={16} className="spinner" />
                <span>Dừng Soạn thảo</span>
              </>
            ) : (
              <>
                <Sparkles size={16} />
                <span>Bắt đầu AI Soạn thảo</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Editor & Preview Canvas Column */}
      <div className="drafting-canvas-workspace">
        <div className="canvas-header-toolbar">
          {/* Toggle edit vs preview */}
          <div className="view-mode-toggles">
            <button 
              className={`toggle-btn ${editMode === 'preview' ? 'active' : ''}`}
              onClick={() => setEditMode('preview')}
            >
              <Eye size={14} />
              <span>Xem trước</span>
            </button>
            <button 
              className={`toggle-btn ${editMode === 'edit' ? 'active' : ''}`}
              onClick={() => setEditMode('edit')}
            >
              <Edit3 size={14} />
              <span>Biên tập</span>
            </button>
          </div>

          {/* Document export triggers */}
          <div className="export-actions-group">
            <button className="toolbar-action-btn" onClick={handleCopyMarkdown} title="Sao chép Markdown">
              {copied ? <Check size={14} color="#10b981" /> : <Copy size={14} />}
              <span>Copy</span>
            </button>
            <button className="toolbar-action-btn" onClick={() => handleExport('docx')} title="Tải file Word">
              <Download size={14} />
              <span>Word (.docx)</span>
            </button>
          </div>
        </div>

        {/* Paper Canvas */}
        <div className="canvas-scroller-box">
          {editMode === 'edit' ? (
            <textarea
              className="paper-canvas editor-textarea"
              value={documentContent}
              onChange={(e) => setDocumentContent(e.target.value)}
              placeholder="# CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM..."
              style={{
                fontFamily: styleGuide.font_name === 'Times New Roman' ? '"Times New Roman", Times, serif' : styleGuide.font_name,
                textAlign: styleGuide.alignment
              }}
            />
          ) : (
            <div 
              className="paper-canvas preview-container markdown-body"
              style={{
                fontFamily: styleGuide.font_name === 'Times New Roman' ? '"Times New Roman", Times, serif' : styleGuide.font_name,
                textAlign: styleGuide.alignment
              }}
            >
              {documentContent.trim() ? (
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {documentContent}
                </ReactMarkdown>
              ) : (
                <div className="canvas-empty-state">
                  <FileText size={48} className="empty-icon" />
                  <h4>Văn bản pháp lý</h4>
                  <p>Cấu hình các thông số bên trái và bấm <strong>Bắt đầu AI Soạn thảo</strong> để khởi tạo văn bản.</p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
