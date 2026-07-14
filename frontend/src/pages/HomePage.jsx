import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../stores/authStore';
import { useTheme } from '../hooks/useTheme';
import api from '../services/api';
import { 
  Scale, LogOut, MessageSquare, Database, Key, Cpu,
  Copy, Check, Trash2, Plus, Sparkles, FileText, User,
  PanelLeftClose, PanelLeft, BookOpen, Shield, HelpCircle, LayoutDashboard, BarChart2,
  Search, RefreshCw, ToggleLeft, ToggleRight, Eye, ChevronLeft, ChevronRight, X,
  Filter
} from 'lucide-react';
import toast from 'react-hot-toast';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import SourcesPanel from '../components/chat/SourcesPanel';
import { useSettingsStore } from '../stores/settingsStore';
import { authStorage } from '../utils/authStorage';
import './HomePage.css';

export default function HomePage() {
  const navigate = useNavigate();
  const { user, logout, isAuthenticated } = useAuthStore();
  const [theme, setTheme] = useTheme();
  
  // Collapse sidebar states (persistent in localStorage)
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(
    localStorage.getItem('sidebar_collapsed') === 'true'
  );

  const [isProfileDropdownOpen, setIsProfileDropdownOpen] = useState(false);

  // Active sub-page tab: 'overview' | 'api_keys' | 'documents' | 'usage'
  const [activeTab, setActiveTab] = useState('overview');

  // Document sub-tabs & filtering
  const [docSubTab, setDocSubTab] = useState('list'); // 'list' | 'compare'
  const [docSearchQuery, setDocSearchQuery] = useState('');
  const [docTypeFilter, setDocTypeFilter] = useState('all'); // 'all' | 'pdf' | 'doc' | 'txt'
  
  // Private user document check states
  const [userDocs, setUserDocs] = useState([]);
  const [selectedUserDoc, setSelectedUserDoc] = useState(null);
  const [userDocChunks, setUserDocChunks] = useState([]);
  
  // System-indexed document check states
  const [selectedSystemDoc, setSelectedSystemDoc] = useState(null);
  const [systemDocChunks, setSystemDocChunks] = useState([]);
  const [systemChunksPage, setSystemChunksPage] = useState(1);
  const [selectedDetailChunk, setSelectedDetailChunk] = useState(null);

  const [isUploadingUserDoc, setIsUploadingUserDoc] = useState(false);
  const [checkingChunkId, setCheckingChunkId] = useState(null);
  const [legalityAnalysis, setLegalityAnalysis] = useState('');
  const [legalitySources, setLegalitySources] = useState('');
  const [isCheckingLegality, setIsCheckingLegality] = useState(false);
  const [showAnalysisPanel, setShowAnalysisPanel] = useState(false);
  const abortControllerRef = useRef(null);
  


  // SVG Chart hover
  const [hoveredBarIndex, setHoveredBarIndex] = useState(null);

  const [stats, setStats] = useState({
    total_sessions: 0,
    total_messages: 0,
    total_documents: 0,
    total_api_keys: 0
  });

  const [tokenUsage, setTokenUsage] = useState({
    prompt_tokens: 0,
    completion_tokens: 0,
    total_tokens: 0,
    limit: 1000000,
    history: []
  });

  const [documents, setDocuments] = useState([]);
  const [apiKeys, setApiKeys] = useState([]);
  const [newKeyName, setNewKeyName] = useState('');
  const [createdKey, setCreatedKey] = useState(null);
  const [copied, setCopied] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  // Usage history state
  const [usageHistory, setUsageHistory] = useState([]);
  const [usagePage, setUsagePage] = useState(1);
  const [usageTotalPages, setUsageTotalPages] = useState(1);
  const [usageTotal, setUsageTotal] = useState(0);
  const [usageSource, setUsageSource] = useState('');
  const [usageSummary, setUsageSummary] = useState(null);
  const [usageDetailItem, setUsageDetailItem] = useState(null);
  const [usageLoading, setUsageLoading] = useState(false);
  const [usageDailyData, setUsageDailyData] = useState(null);

  const getDailyUsageData = () => {
    if (!tokenUsage.history || tokenUsage.history.length === 0) return [];
    const groups = {};
    tokenUsage.history.forEach(item => {
      const d = new Date(item.created_at);
      const dateStr = `${d.getDate().toString().padStart(2, '0')}/${(d.getMonth() + 1).toString().padStart(2, '0')}`;
      if (!groups[dateStr]) {
        groups[dateStr] = { date: dateStr, prompt: 0, completion: 0, total: 0 };
      }
      groups[dateStr].prompt += item.prompt_tokens || 0;
      groups[dateStr].completion += item.completion_tokens || 0;
      groups[dateStr].total += item.total_tokens || 0;
    });
    return Object.values(groups).sort((a, b) => {
      const [dayA, monthA] = a.date.split('/').map(Number);
      const [dayB, monthB] = b.date.split('/').map(Number);
      return monthA !== monthB ? monthA - monthB : dayA - dayB;
    }).slice(-7);
  };

  const filteredDocsList = documents.filter(doc => {
    const name = (doc.original_name || doc.filename || '').toLowerCase();
    const query = docSearchQuery.toLowerCase();
    const matchesSearch = name.includes(query);
    
    if (docTypeFilter === 'all') return matchesSearch;
    const fileType = (doc.file_type || '').toLowerCase();
    if (docTypeFilter === 'doc') {
      return matchesSearch && (fileType === 'doc' || fileType === 'docx');
    }
    return matchesSearch && fileType === docTypeFilter;
  });

  useEffect(() => {
    if (isAuthenticated) {
      fetchDashboardData();
    }
  }, [isAuthenticated]);

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

  const toggleSidebar = () => {
    const nextState = !isSidebarCollapsed;
    setIsSidebarCollapsed(nextState);
    localStorage.setItem('sidebar_collapsed', nextState ? 'true' : 'false');
  };

  const fetchDashboardData = async () => {
    setIsLoading(true);
    try {
      // Fetch stats
      const statsRes = await api.get('/dashboard/stats');
      setStats(statsRes.data.stats);
      setTokenUsage(statsRes.data.token_usage);

      // Fetch documents
      const docsRes = await api.get('/documents');
      setDocuments(docsRes.data.documents || []);

      // Fetch API Keys
      const keysRes = await api.get('/api-keys');
      setApiKeys(keysRes.data || []);
    } catch (err) {
      console.error("Lỗi khi tải dữ liệu dashboard", err);
    } finally {
      setIsLoading(false);
    }
  };

  const handleCreateKey = async (e) => {
    e.preventDefault();
    if (!newKeyName.trim()) return;

    try {
      const res = await api.post('/api-keys', { name: newKeyName });
      setCreatedKey(res.data);
      setNewKeyName('');
      // Refresh key list
      const keysRes = await api.get('/api-keys');
      setApiKeys(keysRes.data || []);
      // Refresh stats
      const statsRes = await api.get('/dashboard/stats');
      setStats(statsRes.data.stats);
    } catch (err) {
      console.error("Lỗi khi tạo API Key", err);
      alert(err.response?.data?.detail || "Không thể tạo API Key");
    }
  };

  const handleDeleteKey = async (id) => {
    if (!confirm("Bạn có chắc chắn muốn thu hồi API Key này? Tất cả các dịch vụ đang dùng key này sẽ bị gián đoạn.")) return;

    try {
      await api.delete(`/api-keys/${id}`);
      setApiKeys(prev => prev.filter(k => k.id !== id));
      const statsRes = await api.get('/dashboard/stats');
      setStats(statsRes.data.stats);
    } catch (err) {
      console.error("Lỗi khi xóa API Key", err);
      toast.error("Không thể xóa API Key");
    }
  };

  const handleRegenerateKey = async (id) => {
    if (!confirm("Làm mới API Key? Key cũ sẽ bị vô hiệu hóa ngay lập tức.")) return;
    try {
      const res = await api.post(`/api-keys/${id}/regenerate`);
      setCreatedKey(res.data);
      const keysRes = await api.get('/api-keys');
      setApiKeys(keysRes.data || []);
      toast.success('API Key đã được làm mới!');
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Không thể làm mới API Key');
    }
  };

  const handleToggleKey = async (id) => {
    try {
      const res = await api.patch(`/api-keys/${id}/toggle`);
      setApiKeys(prev => prev.map(k => k.id === id ? { ...k, is_active: res.data.is_active } : k));
      toast.success(res.data.is_active ? 'API Key đã kích hoạt' : 'API Key đã vô hiệu hóa');
    } catch (err) {
      toast.error('Không thể thay đổi trạng thái API Key');
    }
  };

  const fetchUsageHistory = async (page = 1, source = '') => {
    setUsageLoading(true);
    try {
      const params = { page, per_page: 15 };
      if (source) params.source = source;
      const res = await api.get('/dashboard/usage-history', { params });
      setUsageHistory(res.data.items || []);
      setUsageTotalPages(res.data.pages || 1);
      setUsageTotal(res.data.total || 0);
      setUsagePage(res.data.page || 1);
    } catch (err) {
      console.error('Error fetching usage history', err);
    } finally {
      setUsageLoading(false);
    }
  };

  const fetchUsageSummary = async () => {
    try {
      const res = await api.get('/dashboard/usage-summary');
      setUsageSummary(res.data);
    } catch (err) {
      console.error('Error fetching usage summary', err);
    }
  };

  const fetchUsageDaily = async () => {
    try {
      const res = await api.get('/dashboard/usage-daily', { params: { days: 14 } });
      setUsageDailyData(res.data);
    } catch (err) {
      console.error('Error fetching usage daily', err);
    }
  };

  const fetchUserDocuments = async () => {
    try {
      const res = await api.get('/documents/user-documents');
      setUserDocs(res.data || []);
    } catch (err) {
      console.error("Lỗi khi tải danh sách tài liệu cá nhân", err);
      toast.error("Không thể tải danh sách tài liệu cá nhân");
    }
  };

  const handleDeleteUserDoc = async (docId, event) => {
    if (event) event.stopPropagation();
    if (!confirm("Bạn có chắc chắn muốn xóa tài liệu cá nhân này cùng tất cả phân mảnh của nó?")) return;

    const deleteToastId = toast.loading("Đang xóa tài liệu...");
    try {
      await api.delete(`/documents/user-documents/${docId}`);
      toast.success("Xóa tài liệu cá nhân thành công!", { id: deleteToastId });
      fetchUserDocuments();
      if (selectedUserDoc && selectedUserDoc.id === docId) {
        setSelectedUserDoc(null);
        setUserDocChunks([]);
      }
    } catch (err) {
      console.error("Lỗi khi xóa tài liệu cá nhân", err);
      toast.error(err.response?.data?.detail || "Không thể xóa tài liệu cá nhân", { id: deleteToastId });
    }
  };


  const handleUserDocUpload = async (file) => {
    if (!file) return;
    
    const ext = '.' + file.name.split('.').pop().toLowerCase();
    if (!['.txt', '.pdf', '.doc', '.docx'].includes(ext)) {
      toast.error("Định dạng file không được hỗ trợ! Chỉ cho phép .txt, .pdf, .doc, .docx");
      return;
    }

    const formData = new FormData();
    formData.append('file', file);
    
    setIsUploadingUserDoc(true);
    const uploadToastId = toast.loading(`Đang tải lên và phân mảnh: ${file.name}...`);
    
    try {
      await api.post('/documents/user-upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      toast.success("Tải lên và phân mảnh tài liệu thành công!", { id: uploadToastId });
      fetchUserDocuments();
    } catch (err) {
      console.error("Lỗi tải lên tài liệu cá nhân", err);
      toast.error(err.response?.data?.detail || "Lỗi tải lên tài liệu cá nhân", { id: uploadToastId });
    } finally {
      setIsUploadingUserDoc(false);
    }
  };

  const handleSelectUserDoc = async (doc) => {
    setSelectedUserDoc(doc);
    setUserDocChunks([]);
    const loadingToastId = toast.loading("Đang tải các phân mảnh...");
    try {
      const res = await api.get(`/documents/user-documents/${doc.id}/chunks`);
      setUserDocChunks(res.data || []);
      toast.dismiss(loadingToastId);
    } catch (err) {
      console.error("Lỗi tải phân mảnh tài liệu", err);
      toast.error("Không thể tải các phân mảnh tài liệu", { id: loadingToastId });
      setSelectedUserDoc(null);
    }
  };

  const handleSelectSystemDoc = async (doc) => {
    setSelectedSystemDoc(doc);
    setSystemDocChunks([]);
    setSystemChunksPage(1);
    const loadingToastId = toast.loading("Đang tải các phân mảnh tài liệu hệ thống...");
    try {
      const res = await api.get(`/documents/system-chunks?filename=${encodeURIComponent(doc.filename)}`);
      setSystemDocChunks(res.data || []);
      toast.dismiss(loadingToastId);
    } catch (err) {
      console.error("Lỗi tải phân mảnh tài liệu hệ thống", err);
      toast.error("Không thể tải các phân mảnh tài liệu hệ thống", { id: loadingToastId });
      setSelectedSystemDoc(null);
    }
  };

  const handleCancelLegalityCheck = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsCheckingLegality(false);
    setCheckingChunkId(null);
  };

  const handleCheckChunkLegality = async (chunk) => {
    // Hủy request cũ nếu có
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const controller = new AbortController();
    abortControllerRef.current = controller;

    setCheckingChunkId(chunk.id);
    setLegalityAnalysis('');
    setLegalitySources('');
    setIsCheckingLegality(true);
    setShowAnalysisPanel(true);

    const s = useSettingsStore.getState().getQuerySettings();
    const token = authStorage.getAccessToken();

    const form = new FormData();
    form.append('provider', s.provider || 'custom_trained');
    form.append('api_url', s.settings?.api_url || '');
    form.append('model_name', s.settings?.model_name || '');
    form.append('temperature', s.settings?.temperature ?? 0.7);
    form.append('max_tokens', s.settings?.max_tokens ?? 2048);

    try {
      const response = await fetch(`/api/v1/documents/chunks/${chunk.id}/check-legality`, {
        method: 'POST',
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {})
        },
        body: form,
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
                setLegalityAnalysis(prev => prev + data.content);
              } else if (currentEvent === 'sources') {
                setLegalitySources(data.content || '');
              } else if (currentEvent === 'error') {
                toast.error(data.message || 'Lỗi phân tích pháp lý');
              }
            } catch (err) {
              // Bỏ qua lỗi parse dòng dở dang
            }
          }
        }
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        console.log('Phân tích pháp lý bị hủy bởi người dùng.');
      } else {
        console.error("SSE stream error", err);
        toast.error("Đã xảy ra lỗi trong quá trình kiểm tra tính pháp lý.");
      }
    } finally {
      if (abortControllerRef.current === controller) {
        abortControllerRef.current = null;
      }
      setIsCheckingLegality(false);
      setCheckingChunkId(null);
    }
  };

  useEffect(() => {
    if (isAuthenticated && docSubTab === 'user-docs') {
      fetchUserDocuments();
    }
  }, [isAuthenticated, docSubTab]);

  useEffect(() => {
    if (isAuthenticated && activeTab === 'usage') {
      fetchUsageHistory(1, usageSource);
      fetchUsageSummary();
      fetchUsageDaily();
    }
  }, [isAuthenticated, activeTab]);

  const copyToClipboard = (text) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleLogout = () => {
    logout();
    navigate('/');
  };

  const formatBytes = (bytes) => {
    if (bytes === 0 || !bytes) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  const formatNumber = (num) => {
    return new Intl.NumberFormat().format(num || 0);
  };

  const tokenPercentage = Math.min(100, Math.round((tokenUsage.total_tokens / tokenUsage.limit) * 100));

  // Checklist states
  const hasApiKey = apiKeys.length > 0;
  const hasDocuments = documents.length > 0;

  return (
    <div className="home-layout-container">
      
      {/* Collapsible Left Sidebar (OpenAI style) */}
      <aside className={`home-sidebar ${isSidebarCollapsed ? 'collapsed' : ''}`}>
        
        {/* Top Branding and Collapse Toggle Button */}
        <div className="sidebar-brand-area">
          {!isSidebarCollapsed ? (
            <>
              <div 
                className="sidebar-project-selector"
                onClick={() => setActiveTab('overview')}
                style={{ cursor: 'pointer' }}
                title="Về trang chủ"
              >
                <Scale size={18} color="#818cf8" />
                <span className="project-title" title="Legal RAG Project">Default project</span>
                <span className="project-caret">↕</span>
              </div>
              <button 
                className="sidebar-collapse-toggle"
                onClick={toggleSidebar}
                title="Thu gọn menu"
              >
                <PanelLeftClose size={16} />
              </button>
            </>
          ) : (
            <button 
              className="sidebar-collapse-toggle collapsed-toggle"
              onClick={toggleSidebar}
              title="Mở rộng menu"
            >
              <PanelLeft size={16} />
            </button>
          )}
        </div>

        {/* Navigation Menu Links */}
        <nav className="sidebar-navigation">
          <button className={`nav-menu-btn ${activeTab === 'overview' ? 'active' : ''}`} onClick={() => setActiveTab('overview')}>
            <LayoutDashboard size={16} />
            {!isSidebarCollapsed && <span>Home</span>}
          </button>
          
          <button className="nav-menu-btn" onClick={() => navigate('/chat')}>
            <MessageSquare size={16} />
            {!isSidebarCollapsed && <span>Chat</span>}
          </button>

          <button className={`nav-menu-btn ${activeTab === 'api_keys' ? 'active' : ''}`} onClick={() => setActiveTab('api_keys')}>
            <Key size={16} />
            {!isSidebarCollapsed && <span>API Keys</span>}
          </button>

          <button className={`nav-menu-btn ${activeTab === 'documents' ? 'active' : ''}`} onClick={() => setActiveTab('documents')}>
            <FileText size={16} />
            {!isSidebarCollapsed && <span>Documents</span>}
          </button>

          <button className={`nav-menu-btn ${activeTab === 'usage' ? 'active' : ''}`} onClick={() => setActiveTab('usage')}>
            <BarChart2 size={16} />
            {!isSidebarCollapsed && <span>Usage</span>}
          </button>
          
          {user?.role === 'admin' && (
            <button className="nav-menu-btn admin-link" onClick={() => navigate('/admin')}>
              <Scale size={16} />
              {!isSidebarCollapsed && <span>Admin Panel</span>}
            </button>
          )}
        </nav>

        {/* Bottom User Avatar Trigger & Popover */}
        <div className="sidebar-user-footer">
          <div 
            className="sidebar-user-avatar-trigger"
            onClick={(e) => {
              e.stopPropagation();
              setIsProfileDropdownOpen(!isProfileDropdownOpen);
            }}
            title={user?.username}
          >
            <div className="avatar-circle">
              {user?.username?.[0]?.toUpperCase() || 'U'}
            </div>
            {!isSidebarCollapsed && (
              <div className="avatar-details">
                <span className="avatar-name">{user?.username || 'User'}</span>
                <span className="avatar-org">Personal</span>
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

              {user?.role === 'admin' && (
                <button className="popover-action-btn" onClick={() => { setIsProfileDropdownOpen(false); navigate('/admin'); }}>
                  <Scale size={14} style={{ marginRight: '8px' }} />
                  <span>Organization settings</span>
                </button>
              )}

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

              <button className="popover-action-btn logout-action" onClick={handleLogout}>
                <LogOut size={14} style={{ marginRight: '8px' }} />
                <span>Log out</span>
              </button>
            </div>
          )}
        </div>
      </aside>

      {/* Main Dashboard Content Area */}
      <main className="home-dashboard-content">
        <div className="home-dashboard-inner">
          
          {/* TAB 1: OVERVIEW */}
          {activeTab === 'overview' && (
            <div className="tab-pane animate-fade-in">
              <div className="dashboard-intro-area">
                <h1>Home</h1>
                <p>Chào mừng quay trở lại, {user?.username}. Quản lý tài nguyên và kiểm tra sử dụng.</p>
              </div>

              {/* OpenAI-Style "Get started" Banner Checklist */}
              <div className="dashboard-section get-started-banner">
                <h3>Get started</h3>
                <div className="get-started-list">
                  <div className={`get-started-item ${hasApiKey ? 'completed' : ''}`}>
                    <div className="checklist-bullet">
                      {hasApiKey ? <Check size={12} color="#10b981" /> : "1"}
                    </div>
                    <div className="get-started-text">
                      <strong>Create an API key</strong>
                      <p>Tạo khóa API của riêng bạn để tích hợp vào ứng dụng ngoài.</p>
                    </div>
                    <button className="checklist-action-btn" onClick={() => setActiveTab('api_keys')}>
                      {hasApiKey ? "Xem danh sách" : "Tạo ngay"}
                    </button>
                  </div>

                  <div className={`get-started-item ${hasDocuments ? 'completed' : ''}`}>
                    <div className="checklist-bullet">
                      {hasDocuments ? <Check size={12} color="#10b981" /> : "2"}
                    </div>
                    <div className="get-started-text">
                      <strong>Upload documents</strong>
                      <p>Index tài liệu luật mới để bổ cung cơ sở tri thức cho chatbot.</p>
                    </div>
                    {user?.role === 'admin' ? (
                      <button className="checklist-action-btn" onClick={() => setActiveTab('documents')}>
                        {hasDocuments ? "Xem văn bản" : "Upload ngay"}
                      </button>
                    ) : (
                      <span className="checklist-hint-text">Cần quyền Admin để upload</span>
                    )}
                  </div>

                  <div className="get-started-item">
                    <div className="checklist-bullet">3</div>
                    <div className="get-started-text">
                      <strong>Build a prompt</strong>
                      <p>Bắt đầu đặt câu hỏi pháp lý và thử nghiệm luồng suy luận của AI.</p>
                    </div>
                    <button className="checklist-action-btn highlight" onClick={() => navigate('/chat')}>
                      Chat ngay
                    </button>
                  </div>
                </div>
              </div>

              {/* Quick Metrics Grid */}
              <section className="metrics-grid">
                <div className="metric-card" onClick={() => setActiveTab('usage')} style={{ cursor: 'pointer' }}>
                  <div className="metric-card-inner">
                    <div className="metric-icon-box blue">
                      <Cpu size={20} />
                    </div>
                    <div className="metric-details">
                      <h4>Total tokens used</h4>
                      <div className="metric-number">{formatNumber(tokenUsage.total_tokens)}</div>
                    </div>
                  </div>
                </div>

                <div className="metric-card" onClick={() => navigate('/chat')} style={{ cursor: 'pointer' }}>
                  <div className="metric-card-inner">
                    <div className="metric-icon-box purple">
                      <MessageSquare size={20} />
                    </div>
                    <div className="metric-details">
                      <h4>Total chat sessions</h4>
                      <div className="metric-number">{formatNumber(stats.total_sessions)}</div>
                    </div>
                  </div>
                </div>

                <div className="metric-card" onClick={() => setActiveTab('api_keys')} style={{ cursor: 'pointer' }}>
                  <div className="metric-card-inner">
                    <div className="metric-icon-box orange">
                      <Key size={20} />
                    </div>
                    <div className="metric-details">
                      <h4>API keys active</h4>
                      <div className="metric-number">{formatNumber(stats.total_api_keys)}</div>
                    </div>
                  </div>
                </div>

                <div className="metric-card" onClick={() => setActiveTab('documents')} style={{ cursor: 'pointer' }}>
                  <div className="metric-card-inner">
                    <div className="metric-icon-box green">
                      <Database size={20} />
                    </div>
                    <div className="metric-details">
                      <h4>Total indexed docs</h4>
                      <div className="metric-number">{formatNumber(stats.total_documents)}</div>
                    </div>
                  </div>
                </div>
              </section>

              {/* Chat Quick Start Card */}
              <div className="chat-cta-card" style={{ maxWidth: '600px', margin: '0 auto' }}>
                <div style={{ background: 'rgba(99, 102, 241, 0.1)', color: '#818cf8', padding: '0.75rem', borderRadius: '50%', marginBottom: '1rem' }}>
                  <Sparkles size={32} />
                </div>
                <h3>Trò chuyện Pháp luật AI</h3>
                <p>Hỏi đáp trực tiếp và phân tích cấu trúc điều khoản luật tiếng Việt với RAG lai ghép thông minh.</p>
                <button className="btn-glowing-chat" onClick={() => navigate('/chat')}>
                  Bắt đầu Trò chuyện
                </button>
              </div>
            </div>
          )}

          {/* TAB 2: API KEYS */}
          {activeTab === 'api_keys' && (
            <div className="tab-pane animate-fade-in">
              <div className="dashboard-intro-area">
                <h1>API Keys</h1>
                <p style={{ maxWidth: '800px' }}>
                  Sử dụng API Key để xác thực các yêu cầu gửi đến Legal RAG API từ ứng dụng hoặc dịch vụ của bên thứ ba. 
                  Hãy bảo mật API Key của bạn và không chia sẻ nó công khai.
                </p>
              </div>

              <div className="dashboard-section full-width">
                <div className="section-head-row">
                  <h2>Tạo API Key mới</h2>
                </div>

                <form onSubmit={handleCreateKey} className="api-key-form-inline" style={{ maxWidth: '600px' }}>
                  <input 
                    type="text" 
                    placeholder="Tên API Key mới (ví dụ: Production Server)" 
                    value={newKeyName}
                    onChange={(e) => setNewKeyName(e.target.value)}
                    maxLength={50}
                    required
                  />
                  <button type="submit" className="btn-create-key">
                    Tạo Key mới
                  </button>
                </form>

                <div className="dashboard-table-wrapper">
                  {apiKeys.length === 0 ? (
                    <div className="empty-state">Bạn chưa tạo API Key nào. Tạo một key ở trên để bắt đầu tích hợp.</div>
                  ) : (
                    <table className="dashboard-table">
                      <thead>
                        <tr>
                          <th>Tên API Key</th>
                          <th>Khóa API</th>
                          <th>Trạng thái</th>
                          <th>Ngày tạo</th>
                          <th style={{ textAlign: 'right' }}>Hành động</th>
                        </tr>
                      </thead>
                      <tbody>
                        {apiKeys.map(k => (
                          <tr key={k.id} style={{ opacity: k.is_active === false ? 0.5 : 1 }}>
                            <td>{k.name}</td>
                            <td><span className="key-code">{k.key}</span></td>
                            <td>
                              <span style={{
                                padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 600,
                                background: k.is_active !== false ? 'rgba(16,185,129,0.15)' : 'rgba(239,68,68,0.15)',
                                color: k.is_active !== false ? '#10b981' : '#ef4444'
                              }}>
                                {k.is_active !== false ? 'Active' : 'Inactive'}
                              </span>
                            </td>
                            <td>{new Date(k.created_at).toLocaleDateString('vi-VN')} {new Date(k.created_at).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })}</td>
                            <td style={{ textAlign: 'right', display: 'flex', gap: 4, justifyContent: 'flex-end' }}>
                              <button className="action-icon-btn" onClick={() => handleToggleKey(k.id)} title={k.is_active !== false ? 'Vô hiệu hóa' : 'Kích hoạt'} style={{ color: k.is_active !== false ? '#f59e0b' : '#10b981' }}>
                                {k.is_active !== false ? <ToggleRight size={16} /> : <ToggleLeft size={16} />}
                              </button>
                              <button className="action-icon-btn" onClick={() => handleRegenerateKey(k.id)} title="Làm mới Key" style={{ color: '#3b82f6' }}>
                                <RefreshCw size={16} />
                              </button>
                              <button className="action-icon-btn delete" onClick={() => handleDeleteKey(k.id)} title="Xóa API Key">
                                <Trash2 size={16} />
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* TAB 3: DOCUMENTS */}
          {activeTab === 'documents' && (
            <div className="tab-pane animate-fade-in">
              <div className="dashboard-intro-area">
                <h1>Documents Index</h1>
                <p>Danh sách các văn bản pháp luật, quy định đã được trích xuất ngữ nghĩa, phân mảnh (chunking) và lập chỉ mục trong kho tri thức RAG.</p>
              </div>

              {/* Sub-tab Selection */}
              <div className="doc-sub-tabs">
                <button 
                  className={`doc-sub-tab-btn ${docSubTab === 'list' ? 'active' : ''}`}
                  onClick={() => { setDocSubTab('list'); setSelectedUserDoc(null); setSelectedSystemDoc(null); }}
                >
                  <Database size={14} />
                  <span>Danh sách tài liệu</span>
                </button>
                <button 
                  className={`doc-sub-tab-btn ${docSubTab === 'user-docs' ? 'active' : ''}`}
                  onClick={() => { setDocSubTab('user-docs'); setSelectedUserDoc(null); setSelectedSystemDoc(null); }}
                >
                  <User size={14} />
                  <span>Tài liệu cá nhân</span>
                </button>

              </div>

              {docSubTab === 'list' && (
                <div className="dashboard-section full-width animate-fade-in">
                  {!selectedSystemDoc ? (
                    <>
                      <div className="section-head-row">
                        <h2>Văn bản luật đã Index</h2>
                        {user?.role === 'admin' && (
                          <button className="checklist-action-btn highlight" onClick={() => navigate('/admin')}>
                            Upload văn bản mới
                          </button>
                        )}
                      </div>

                      {/* Search and Filters */}
                      <div className="doc-filters-row">
                        <div className="doc-search-input-wrap">
                          <Search size={16} className="doc-search-icon" />
                          <input 
                            type="text" 
                            placeholder="Tìm kiếm theo tên văn bản..." 
                            value={docSearchQuery}
                            onChange={e => setDocSearchQuery(e.target.value)}
                          />
                          {docSearchQuery && (
                            <button 
                              className="search-clear-btn" 
                              onClick={() => setDocSearchQuery('')}
                              style={{ right: '12px' }}
                            >
                              ×
                            </button>
                          )}
                        </div>
                        
                        <select 
                          className="doc-filter-select"
                          value={docTypeFilter}
                          onChange={e => setDocTypeFilter(e.target.value)}
                        >
                          <option value="all">Tất cả định dạng</option>
                          <option value="pdf">PDF</option>
                          <option value="doc">Word (.doc/.docx)</option>
                          <option value="txt">Text (.txt)</option>
                        </select>
                      </div>

                      <div className="dashboard-table-wrapper">
                        {filteredDocsList.length === 0 ? (
                          <div className="empty-state">
                            {documents.length === 0 
                              ? "Không tìm thấy tài liệu nào được lập chỉ mục trong hệ thống."
                              : "Không tìm thấy tài liệu nào phù hợp với bộ lọc."
                            }
                          </div>
                        ) : (
                          <table className="dashboard-table">
                            <thead>
                              <tr>
                                <th>Tên văn bản</th>
                                <th>Định dạng</th>
                                <th>Dung lượng</th>
                                <th>Số Chunks</th>
                                <th>Trạng thái</th>
                                <th>Ngày Index</th>
                                <th style={{ textAlign: 'right' }}>Hành động</th>
                              </tr>
                            </thead>
                            <tbody>
                              {filteredDocsList.map(doc => (
                                <tr key={doc.id}>
                                  <td 
                                    style={{ maxWidth: '400px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontWeight: '600', color: 'var(--color-primary)', cursor: 'pointer' }} 
                                    title={doc.original_name || doc.filename}
                                    onClick={() => handleSelectSystemDoc(doc)}
                                  >
                                    📖 {doc.original_name || doc.filename}
                                  </td>
                                  <td><span className="key-code" style={{ color: '#fbbf24' }}>{doc.file_type?.toUpperCase() || '.TXT'}</span></td>
                                  <td>{doc.file_size ? formatBytes(doc.file_size) : '--'}</td>
                                  <td><strong>{doc.chunks_count !== null && doc.chunks_count !== undefined ? doc.chunks_count : '--'}</strong> chunks</td>
                                  <td>
                                    <span className={`status-pill ${doc.status || 'pending'}`}>
                                      {doc.status === 'indexed' ? 'Đã index' : doc.status === 'pending' ? 'Đang xử lý' : 'Lỗi'}
                                    </span>
                                  </td>
                                  <td>{new Date(doc.created_at || Date.now()).toLocaleDateString('vi-VN')}</td>
                                  <td style={{ textAlign: 'right' }}>
                                    <button 
                                      className="action-icon-btn" 
                                      onClick={() => handleSelectSystemDoc(doc)} 
                                      title="Xem chi tiết các phân mảnh" 
                                      style={{ color: 'var(--color-primary)', padding: '0.35rem' }}
                                    >
                                      <Search size={16} />
                                    </button>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        )}
                      </div>
                    </>
                  ) : (
                    <>
                      {/* Chunks View for System Document */}
                      <div className="selected-doc-header" style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', borderBottom: '1px solid var(--color-border-subtle)', paddingBottom: '1.25rem' }}>
                        <button 
                          className="action-icon-btn" 
                          onClick={() => { setSelectedSystemDoc(null); setSystemDocChunks([]); }} 
                          style={{ alignSelf: 'flex-start', padding: '0.5rem 1rem', border: '1px solid var(--color-border)', borderRadius: '8px', gap: '0.5rem', display: 'flex', alignItems: 'center' }}
                        >
                          ← Quay lại danh sách
                        </button>
                        <div className="selected-doc-meta" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%', flexWrap: 'wrap', gap: '1rem', marginTop: '0.5rem' }}>
                          <div>
                            <h2 style={{ fontSize: '1.25rem', fontWeight: '700', color: 'var(--color-text)' }}>{selectedSystemDoc.original_name || selectedSystemDoc.filename}</h2>
                            <p style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)', marginTop: '2px' }}>Chi tiết các phân mảnh (chunks) trong kho tri thức RAG.</p>
                          </div>
                          <div className="selected-doc-badges" style={{ display: 'flex', gap: '0.5rem' }}>
                            <span className="key-code" style={{ color: '#fbbf24' }}>{selectedSystemDoc.file_type?.toUpperCase()}</span>
                            <span className="key-code">{selectedSystemDoc.file_size ? formatBytes(selectedSystemDoc.file_size) : '--'}</span>
                            <span className="key-code" style={{ color: '#34d399' }}>{systemDocChunks.length} chunks</span>
                          </div>
                        </div>
                      </div>

                      <div className="doc-chunks-container" style={{ marginTop: '1.5rem' }}>
                        {systemDocChunks.length === 0 ? (
                          <div className="empty-state" style={{ padding: '2rem', textAlign: 'center', color: 'var(--color-text-secondary)' }}>Tài liệu không có phân mảnh nào hoặc đang tải...</div>
                        ) : (
                          <>
                            <div className="doc-chunks-grid">
                              {systemDocChunks
                                .slice((systemChunksPage - 1) * 10, systemChunksPage * 10)
                                .map(chunk => {
                                  const meta = chunk.metadata || {};
                                  return (
                                    <div 
                                      className="chunk-card" 
                                      key={chunk.id} 
                                      onClick={() => setSelectedDetailChunk(chunk)}
                                      style={{ cursor: 'pointer', transition: 'all 0.2s ease', position: 'relative' }}
                                    >
                                      <div className="chunk-card-header" style={{ display: 'flex', flexWrap: 'wrap', gap: '0.35rem', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid var(--color-border-subtle)', paddingBottom: '0.5rem', marginBottom: '0.75rem' }}>
                                        <span className="chunk-index" style={{ fontWeight: '700', fontSize: '0.8rem' }}>Phân đoạn #{chunk.chunk_index + 1}</span>
                                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.25rem' }} onClick={e => e.stopPropagation()}>
                                          {selectedSystemDoc.filename && (
                                            <span 
                                              className="chunk-meta-tag tag-book" 
                                              style={{ fontSize: '0.7rem', padding: '0.15rem 0.35rem', borderRadius: '4px', background: 'rgba(59, 130, 246, 0.15)', color: '#3b82f6', fontWeight: '600', cursor: 'pointer' }}
                                              onClick={() => setSelectedDetailChunk(chunk)}
                                            >
                                              {meta.doc_title || selectedSystemDoc.filename.replace('.txt', '')}
                                            </span>
                                          )}
                                          {meta.chapter_num && (
                                            <span 
                                              className="chunk-meta-tag tag-chapter" 
                                              style={{ fontSize: '0.7rem', padding: '0.15rem 0.35rem', borderRadius: '4px', background: 'rgba(139, 92, 246, 0.15)', color: '#8b5cf6', fontWeight: '600', cursor: 'pointer' }}
                                              onClick={() => setSelectedDetailChunk(chunk)}
                                            >
                                              Chương {meta.chapter_num}
                                            </span>
                                          )}
                                          {meta.article_num && (
                                            <span 
                                              className="chunk-meta-tag tag-article" 
                                              style={{ fontSize: '0.7rem', padding: '0.15rem 0.35rem', borderRadius: '4px', background: 'rgba(245, 158, 11, 0.15)', color: '#f59e0b', fontWeight: '600', cursor: 'pointer' }}
                                              onClick={() => setSelectedDetailChunk(chunk)}
                                            >
                                              Điều {meta.article_num}
                                            </span>
                                          )}
                                          {meta.clause_num && (
                                            <span 
                                              className="chunk-meta-tag tag-clause" 
                                              style={{ fontSize: '0.7rem', padding: '0.15rem 0.35rem', borderRadius: '4px', background: 'rgba(16, 185, 129, 0.15)', color: '#10b981', fontWeight: '600', cursor: 'pointer' }}
                                              onClick={() => setSelectedDetailChunk(chunk)}
                                            >
                                              Khoản {meta.clause_num}
                                            </span>
                                          )}
                                        </div>
                                      </div>
                                      <div className="chunk-card-body" style={{ maxHeight: '120px', overflow: 'hidden', textOverflow: 'ellipsis', display: '-webkit-box', WebkitLineClamp: 4, WebkitBoxOrient: 'vertical' }}>
                                        <p style={{ fontSize: '0.85rem', lineHeight: '1.4', color: 'var(--color-text)' }}>{chunk.content}</p>
                                      </div>
                                      <div className="chunk-card-footer-tip" style={{ marginTop: 'auto', paddingTop: '0.5rem', textAlign: 'right', fontSize: '0.7rem', color: 'var(--color-text-secondary)', fontStyle: 'italic' }}>
                                        Nhấp để xem chi tiết
                                      </div>
                                    </div>
                                  );
                                })}
                            </div>

                            {/* Pagination Controls */}
                            {systemDocChunks.length > 10 && (
                              <div className="chunks-pagination" style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '0.5rem', marginTop: '2rem', flexWrap: 'wrap' }}>
                                <button 
                                  className="action-icon-btn" 
                                  disabled={systemChunksPage === 1}
                                  onClick={() => setSystemChunksPage(prev => Math.max(1, prev - 1))}
                                  style={{ padding: '0.4rem 0.8rem', border: '1px solid var(--color-border)', borderRadius: '6px', cursor: systemChunksPage === 1 ? 'not-allowed' : 'pointer', opacity: systemChunksPage === 1 ? 0.5 : 1 }}
                                >
                                  Trước
                                </button>
                                
                                <div style={{ display: 'flex', gap: '0.25rem', alignItems: 'center' }}>
                                  {Array.from({ length: Math.ceil(systemDocChunks.length / 10) }).map((_, idx) => {
                                    const pageNum = idx + 1;
                                    const totalP = Math.ceil(systemDocChunks.length / 10);
                                    
                                    // Render logic to show only relevant pages around active page
                                    if (totalP > 7) {
                                      if (pageNum !== 1 && pageNum !== totalP && Math.abs(pageNum - systemChunksPage) > 1) {
                                        if (pageNum === 2 && systemChunksPage > 3) return <span key="ellipsis-start" style={{ padding: '0 0.25rem' }}>...</span>;
                                        if (pageNum === totalP - 1 && systemChunksPage < totalP - 2) return <span key="ellipsis-end" style={{ padding: '0 0.25rem' }}>...</span>;
                                        return null;
                                      }
                                    }
                                    
                                    return (
                                      <button
                                        key={pageNum}
                                        onClick={() => setSystemChunksPage(pageNum)}
                                        style={{
                                          padding: '0.3rem 0.6rem',
                                          minWidth: '30px',
                                          borderRadius: '4px',
                                          border: '1px solid',
                                          borderColor: systemChunksPage === pageNum ? 'var(--color-primary)' : 'var(--color-border)',
                                          background: systemChunksPage === pageNum ? 'var(--color-primary)' : 'transparent',
                                          color: systemChunksPage === pageNum ? '#fff' : 'var(--color-text)',
                                          cursor: 'pointer',
                                          fontWeight: systemChunksPage === pageNum ? 'bold' : 'normal'
                                        }}
                                      >
                                        {pageNum}
                                      </button>
                                    );
                                  })}
                                </div>

                                <button 
                                  className="action-icon-btn" 
                                  disabled={systemChunksPage >= Math.ceil(systemDocChunks.length / 10)}
                                  onClick={() => setSystemChunksPage(prev => Math.min(Math.ceil(systemDocChunks.length / 10), prev + 1))}
                                  style={{ padding: '0.4rem 0.8rem', border: '1px solid var(--color-border)', borderRadius: '6px', cursor: systemChunksPage >= Math.ceil(systemDocChunks.length / 10) ? 'not-allowed' : 'pointer', opacity: systemChunksPage >= Math.ceil(systemDocChunks.length / 10) ? 0.5 : 1 }}
                                >
                                  Sau
                                </button>
                              </div>
                            )}
                          </>
                        )}
                      </div>
                    </>
                  )}
                </div>
              )}

              {docSubTab === 'user-docs' && (
                <div className="dashboard-section full-width animate-fade-in">
                  {!selectedUserDoc ? (
                    <>
                      <div className="section-head-row">
                        <div>
                          <h2>Tài liệu cá nhân</h2>
                          <p className="doc-section-subtitle" style={{ color: 'var(--color-text-secondary)', fontSize: '0.875rem', marginTop: '4px' }}>
                            Tải lên tài liệu riêng tư (không index RAG chung) để trích xuất phân mảnh và kiểm tra pháp lý.
                          </p>
                        </div>
                      </div>

                      {/* Dropzone Upload Section */}
                      <div className="user-upload-area" style={{ margin: '1.5rem 0' }}>
                        <div className="upload-dropzone" style={{ border: '2px dashed var(--color-border)', borderRadius: '16px', padding: '2.5rem 1.5rem', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '1rem', background: 'var(--color-surface-2)', transition: 'all 0.3s ease' }}>
                          <Plus size={36} style={{ color: 'var(--color-primary)' }} />
                          <div className="upload-zone-text" style={{ textAlign: 'center' }}>
                            <strong style={{ display: 'block', fontSize: '1rem', color: 'var(--color-text)', marginBottom: '0.25rem' }}>Chọn hoặc kéo tệp vào đây để tải lên</strong>
                            <span style={{ fontSize: '0.8rem', color: 'var(--color-text-secondary)' }}>Hỗ trợ: .txt, .pdf, .doc, .docx (Tối đa 10MB)</span>
                          </div>
                          <input 
                            type="file" 
                            id="user-file-upload-input" 
                            onChange={(e) => {
                              if (e.target.files && e.target.files[0]) {
                                handleUserDocUpload(e.target.files[0]);
                                e.target.value = ''; // Clear value
                              }
                            }}
                            accept=".txt,.pdf,.doc,.docx"
                            disabled={isUploadingUserDoc}
                            style={{ display: 'none' }}
                          />
                          <button 
                            className="btn-create-key" 
                            onClick={() => document.getElementById('user-file-upload-input').click()}
                            disabled={isUploadingUserDoc}
                          >
                            {isUploadingUserDoc ? 'Đang xử lý...' : 'Chọn tệp'}
                          </button>
                        </div>
                      </div>

                      {/* Private Documents Table */}
                      <div className="dashboard-table-wrapper">
                        {userDocs.length === 0 ? (
                          <div className="empty-state" style={{ padding: '2rem', textAlign: 'center', color: 'var(--color-text-secondary)' }}>
                            Chưa có tài liệu cá nhân nào được tải lên.
                          </div>
                        ) : (
                          <table className="dashboard-table">
                            <thead>
                              <tr>
                                <th>Tên văn bản</th>
                                <th>Định dạng</th>
                                <th>Dung lượng</th>
                                <th>Số Chunks</th>
                                <th>Ngày tải lên</th>
                                <th style={{ textAlign: 'right' }}>Hành động</th>
                              </tr>
                            </thead>
                            <tbody>
                              {userDocs.map(doc => (
                                <tr key={doc.id}>
                                  <td 
                                    style={{ maxWidth: '300px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontWeight: '600', color: 'var(--color-primary)', cursor: 'pointer' }} 
                                    title={doc.filename}
                                    onClick={() => handleSelectUserDoc(doc)}
                                  >
                                    📎 {doc.filename}
                                  </td>
                                  <td><span className="key-code" style={{ color: '#fbbf24' }}>{doc.file_type?.toUpperCase() || '.TXT'}</span></td>
                                  <td>{formatBytes(doc.file_size)}</td>
                                  <td><strong>{doc.chunks_count || 0}</strong> chunks</td>
                                  <td>{new Date(doc.created_at || Date.now()).toLocaleDateString('vi-VN')}</td>
                                  <td style={{ textAlign: 'right' }}>
                                    <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
                                      <button className="action-icon-btn" onClick={() => handleSelectUserDoc(doc)} title="Xem chi tiết các phân mảnh" style={{ color: 'var(--color-primary)', padding: '0.35rem' }}>
                                        <Search size={16} />
                                      </button>
                                      <button className="action-icon-btn delete" onClick={(e) => handleDeleteUserDoc(doc.id, e)} title="Xóa tài liệu cá nhân" style={{ padding: '0.35rem' }}>
                                        <Trash2 size={16} />
                                      </button>
                                    </div>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        )}
                      </div>
                    </>
                  ) : (
                    <>
                      {/* Chunks View */}
                      <div className="selected-doc-header" style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', borderBottom: '1px solid var(--color-border-subtle)', paddingBottom: '1.25rem' }}>
                        <button 
                          className="action-icon-btn" 
                          onClick={() => setSelectedUserDoc(null)} 
                          style={{ alignSelf: 'flex-start', padding: '0.5rem 1rem', border: '1px solid var(--color-border)', borderRadius: '8px', gap: '0.5rem', display: 'flex', alignItems: 'center' }}
                        >
                          ← Quay lại danh sách
                        </button>
                        <div className="selected-doc-meta" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%', flexWrap: 'wrap', gap: '1rem', marginTop: '0.5rem' }}>
                          <div>
                            <h2 style={{ fontSize: '1.25rem', fontWeight: '700', color: 'var(--color-text)' }}>{selectedUserDoc.filename}</h2>
                            <p style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)', marginTop: '2px' }}>Danh sách các phân mảnh văn bản trích xuất tự động.</p>
                          </div>
                          <div className="selected-doc-badges" style={{ display: 'flex', gap: '0.5rem' }}>
                            <span className="key-code" style={{ color: '#60a5fa' }}>{selectedUserDoc.file_type?.toUpperCase()}</span>
                            <span className="key-code">{formatBytes(selectedUserDoc.file_size)}</span>
                            <span className="key-code" style={{ color: '#34d399' }}>{userDocChunks.length} chunks</span>
                          </div>
                        </div>
                      </div>

                      <div className="doc-chunks-container" style={{ marginTop: '1.5rem' }}>
                        {userDocChunks.length === 0 ? (
                          <div className="empty-state" style={{ padding: '2rem', textAlign: 'center', color: 'var(--color-text-secondary)' }}>Tài liệu không có phân mảnh nào hoặc đang tải...</div>
                        ) : (
                          <div className="doc-chunks-grid">
                            {userDocChunks.map(chunk => (
                              <div className="chunk-card" key={chunk.id}>
                                <div className="chunk-card-header">
                                  <span className="chunk-index">Phân đoạn #{chunk.chunk_index + 1}</span>
                                </div>
                                <div className="chunk-card-body">
                                  <p>{chunk.content}</p>
                                </div>
                                <div className="chunk-card-actions">
                                  <button 
                                    className={`btn-check-chunk ${checkingChunkId === chunk.id ? 'checking' : ''}`}
                                    onClick={() => handleCheckChunkLegality(chunk)}
                                    disabled={isCheckingLegality}
                                  >
                                    <Shield size={13} />
                                    <span>{checkingChunkId === chunk.id ? 'Đang phân tích...' : 'Kiểm tra tính pháp lý'}</span>
                                  </button>
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </>
                  )}
                </div>
              )}


            </div>
          )}

          {/* TAB 4: USAGE */}
          {activeTab === 'usage' && (
            <div className="tab-pane animate-fade-in">
              <div className="dashboard-intro-area">
                <h1>Usage</h1>
                <p>Theo dõi chi tiết lịch sử sử dụng Chatbot và API, bao gồm token, chi phí và nội dung prompt.</p>
              </div>

              {/* Summary Cards */}
              {usageSummary && (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 24 }}>
                  {['chatbot', 'api'].map(src => {
                    const d = usageSummary[src] || {};
                    return (
                      <div key={src} className="dashboard-section" style={{ margin: 0 }}>
                        <h2 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          {src === 'chatbot' ? '💬' : '🔌'} {src === 'chatbot' ? 'Chatbot' : 'API'}
                        </h2>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12, marginTop: 12 }}>
                          <div className="breakdown-box">
                            <label>Requests</label>
                            <span>{formatNumber(d.total_requests || 0)}</span>
                          </div>
                          <div className="breakdown-box">
                            <label>Tokens</label>
                            <span>{formatNumber(d.total_tokens || 0)}</span>
                          </div>
                          <div className="breakdown-box">
                            <label>Chi phí</label>
                            <span>${(d.total_cost || 0).toFixed(4)}</span>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
              {/* Dual Charts */}
              {usageDailyData && (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 24 }}>
                  {[
                    { key: 'chatbot', label: '💬 Chatbot', color1: '#10b981', color2: '#34d399' },
                    { key: 'api', label: '🔌 API', color1: '#3b82f6', color2: '#60a5fa' },
                  ].map(chart => {
                    const data = usageDailyData[chart.key] || [];
                    if (data.length === 0) {
                      return (
                        <div key={chart.key} className="dashboard-section" style={{ margin: 0 }}>
                          <h3 style={{ fontSize: 14, marginBottom: 8 }}>{chart.label} — Token hàng ngày</h3>
                          <div className="empty-chart" style={{ padding: 24, textAlign: 'center', opacity: 0.5 }}>Chưa có dữ liệu</div>
                        </div>
                      );
                    }
                    const maxVal = Math.max(...data.map(d => d.total_tokens), 100) * 1.15;
                    const cW = 500, cH = 180, pL = 45, pR = 10, pT = 15, pB = 28;
                    const gW = cW - pL - pR, gH = cH - pT - pB;
                    const step = gW / data.length;
                    const bW = Math.min(step * 0.65, 28);

                    return (
                      <div key={chart.key} className="dashboard-section" style={{ margin: 0 }}>
                        <h3 style={{ fontSize: 14, marginBottom: 8 }}>{chart.label} — Token hàng ngày</h3>
                        <div style={{ position: 'relative' }}>
                          <svg viewBox={`0 0 ${cW} ${cH}`} width="100%" height="170" style={{ overflow: 'visible' }}>
                            {/* Grid */}
                            {[0, 0.25, 0.5, 0.75, 1].map((r, i) => {
                              const y = pT + gH * (1 - r);
                              return (
                                <g key={i}>
                                  <line x1={pL} y1={y} x2={cW - pR} y2={y} stroke="var(--color-border-subtle)" strokeDasharray="3 3" />
                                  <text x={pL - 6} y={y + 3} textAnchor="end" fontSize="8" fill="var(--color-text-secondary)">
                                    {formatNumber(Math.round(r * maxVal))}
                                  </text>
                                </g>
                              );
                            })}
                            {/* Bars */}
                            {data.map((item, idx) => {
                              const x = pL + idx * step + (step - bW) / 2;
                              const pH = (item.prompt_tokens / maxVal) * gH;
                              const cHt = (item.completion_tokens / maxVal) * gH;
                              const yP = pT + gH - pH;
                              const yC = yP - cHt;
                              const dateLabel = item.date.slice(5); // MM-DD
                              return (
                                <g key={idx}>
                                  <rect x={x} y={yP} width={bW} height={pH} fill={chart.color1} opacity="0.85" rx="2" />
                                  <rect x={x} y={yC} width={bW} height={cHt} fill={chart.color2} opacity="0.7" rx="2" />
                                  <text x={x + bW / 2} y={cH - 6} textAnchor="middle" fontSize="8" fill="var(--color-text-secondary)">
                                    {dateLabel}
                                  </text>
                                  <title>{`${item.date}\nPrompt: ${formatNumber(item.prompt_tokens)}\nCompletion: ${formatNumber(item.completion_tokens)}\nTotal: ${formatNumber(item.total_tokens)}\nCost: $${item.cost}`}</title>
                                </g>
                              );
                            })}
                          </svg>
                        </div>
                        <div style={{ display: 'flex', gap: 16, justifyContent: 'center', marginTop: 6 }}>
                          <span style={{ fontSize: 11, display: 'flex', alignItems: 'center', gap: 4 }}>
                            <span style={{ width: 10, height: 10, borderRadius: 2, background: chart.color1, display: 'inline-block' }} /> Prompt
                          </span>
                          <span style={{ fontSize: 11, display: 'flex', alignItems: 'center', gap: 4 }}>
                            <span style={{ width: 10, height: 10, borderRadius: 2, background: chart.color2, display: 'inline-block' }} /> Completion
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Filter + Table */}
              <div className="dashboard-section">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                  <h2>Nhật ký sử dụng ({usageTotal} bản ghi)</h2>
                  <div style={{ display: 'flex', gap: 6 }}>
                    {[{v:'', l:'Tất cả'}, {v:'chatbot', l:'💬 Chatbot'}, {v:'api', l:'🔌 API'}].map(f => (
                      <button
                        key={f.v}
                        className={`btn btn-sm ${usageSource === f.v ? 'btn-primary' : 'btn-ghost'}`}
                        onClick={() => { setUsageSource(f.v); fetchUsageHistory(1, f.v); }}
                        style={{ fontSize: 12, padding: '4px 12px' }}
                      >{f.l}</button>
                    ))}
                    <button className="btn btn-sm btn-ghost" onClick={() => { fetchUsageHistory(usagePage, usageSource); fetchUsageSummary(); fetchUsageDaily(); }}>
                      <RefreshCw size={13} />
                    </button>
                  </div>
                </div>

                <div className="dashboard-table-wrapper">
                  {usageLoading ? (
                    <div className="empty-state">Đang tải...</div>
                  ) : usageHistory.length === 0 ? (
                    <div className="empty-state">Chưa có dữ liệu sử dụng.</div>
                  ) : (
                    <table className="dashboard-table">
                      <thead>
                        <tr>
                          <th>Thời gian</th>
                          <th>Nguồn</th>
                          <th>Model</th>
                          <th>Prompt</th>
                          <th>Completion</th>
                          <th>Chi phí</th>
                          <th style={{ textAlign: 'center' }}>Chi tiết</th>
                        </tr>
                      </thead>
                      <tbody>
                        {usageHistory.map(h => (
                          <tr key={h.id}>
                            <td style={{ whiteSpace: 'nowrap', fontSize: 12 }}>
                              {new Date(h.created_at).toLocaleDateString('vi-VN')} {new Date(h.created_at).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })}
                            </td>
                            <td>
                              <span style={{
                                padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 600,
                                background: h.source === 'api' ? 'rgba(59,130,246,0.15)' : 'rgba(16,185,129,0.15)',
                                color: h.source === 'api' ? '#3b82f6' : '#10b981'
                              }}>
                                {h.source === 'api' ? 'API' : 'Chatbot'}
                              </span>
                            </td>
                            <td style={{ maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 12 }} title={h.model_name}>
                              {h.model_name || '—'}
                            </td>
                            <td style={{ fontSize: 12 }}>{formatNumber(h.prompt_tokens)}</td>
                            <td style={{ fontSize: 12 }}>{formatNumber(h.completion_tokens)}</td>
                            <td style={{ fontSize: 12, color: '#f59e0b' }}>${(h.cost || 0).toFixed(6)}</td>
                            <td style={{ textAlign: 'center' }}>
                              <button
                                className="action-icon-btn"
                                onClick={() => setUsageDetailItem(h)}
                                title="Xem chi tiết"
                                style={{ color: '#60a5fa' }}
                              >
                                <Eye size={15} />
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>

                {/* Pagination */}
                {usageTotalPages > 1 && (
                  <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 12, marginTop: 16 }}>
                    <button
                      className="btn btn-sm btn-ghost"
                      disabled={usagePage <= 1}
                      onClick={() => { setUsagePage(p => p - 1); fetchUsageHistory(usagePage - 1, usageSource); }}
                    ><ChevronLeft size={16} /></button>
                    <span style={{ fontSize: 13, color: 'var(--color-text-secondary)' }}>
                      Trang {usagePage} / {usageTotalPages}
                    </span>
                    <button
                      className="btn btn-sm btn-ghost"
                      disabled={usagePage >= usageTotalPages}
                      onClick={() => { setUsagePage(p => p + 1); fetchUsageHistory(usagePage + 1, usageSource); }}
                    ><ChevronRight size={16} /></button>
                  </div>
                )}
              </div>

              {/* Detail Modal */}
              {usageDetailItem && (
                <>
                  <div className="modal-backdrop" onClick={() => setUsageDetailItem(null)} />
                  <div className="model-selector-modal" style={{ maxWidth: 700 }}>
                    <div className="modal-header">
                      <h3>Chi tiết sử dụng</h3>
                      <button className="btn btn-ghost btn-icon btn-sm" onClick={() => setUsageDetailItem(null)}><X size={16} /></button>
                    </div>
                    <div className="modal-body" style={{ padding: '16px 20px', maxHeight: '70vh', overflowY: 'auto' }}>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 }}>
                        <div><strong>Nguồn:</strong> {usageDetailItem.source === 'api' ? '🔌 API' : '💬 Chatbot'}</div>
                        <div><strong>Model:</strong> {usageDetailItem.model_name || '—'}</div>
                        <div><strong>Thời gian:</strong> {new Date(usageDetailItem.created_at).toLocaleString('vi-VN')}</div>
                        <div><strong>Chi phí:</strong> <span style={{ color: '#f59e0b' }}>${(usageDetailItem.cost || 0).toFixed(6)}</span></div>
                        <div><strong>Prompt tokens:</strong> {formatNumber(usageDetailItem.prompt_tokens)}</div>
                        <div><strong>Completion tokens:</strong> {formatNumber(usageDetailItem.completion_tokens)}</div>
                      </div>

                      {usageDetailItem.system_prompt && (
                        <div style={{ marginBottom: 16 }}>
                          <h4 style={{ marginBottom: 6, fontSize: 13, color: 'var(--color-text-secondary)' }}>System Prompt</h4>
                          <div style={{ background: 'var(--color-bg-secondary)', padding: 12, borderRadius: 8, fontSize: 13, whiteSpace: 'pre-wrap', maxHeight: 150, overflowY: 'auto', border: '1px solid var(--color-border)' }}>
                            {usageDetailItem.system_prompt}
                          </div>
                        </div>
                      )}

                      {usageDetailItem.user_prompt && (
                        <div style={{ marginBottom: 16 }}>
                          <h4 style={{ marginBottom: 6, fontSize: 13, color: 'var(--color-text-secondary)' }}>User Prompt</h4>
                          <div style={{ background: 'var(--color-bg-secondary)', padding: 12, borderRadius: 8, fontSize: 13, whiteSpace: 'pre-wrap', maxHeight: 200, overflowY: 'auto', border: '1px solid var(--color-border)' }}>
                            {usageDetailItem.user_prompt}
                          </div>
                        </div>
                      )}

                      {usageDetailItem.response_preview && (
                        <div>
                          <h4 style={{ marginBottom: 6, fontSize: 13, color: 'var(--color-text-secondary)' }}>Response (preview)</h4>
                          <div style={{ background: 'var(--color-bg-secondary)', padding: 12, borderRadius: 8, fontSize: 13, whiteSpace: 'pre-wrap', maxHeight: 200, overflowY: 'auto', border: '1px solid var(--color-border)' }}>
                            {usageDetailItem.response_preview}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                </>
              )}
            </div>
          )}

        </div>
      </main>

      {/* Slide-out Side Drawer for Legality Analysis */}
      <div className={`analysis-drawer-overlay ${showAnalysisPanel ? 'visible' : ''}`} onClick={handleCancelLegalityCheck}>
        <div className="analysis-drawer-content" onClick={(e) => e.stopPropagation()}>
          <div className="drawer-header">
            <div className="drawer-header-title">
              <Shield size={20} className="drawer-header-icon" />
              <h3>Phân tích tính pháp lý</h3>
            </div>
            <button className="btn-close-drawer" onClick={handleCancelLegalityCheck} title="Đóng bảng phân tích">
              ✕
            </button>
          </div>

          <div className="drawer-body">
            {/* Show currently checking chunk content */}
            {checkingChunkId && (
              <div className="drawer-chunk-preview">
                <h4>Nội dung phân đoạn đang kiểm tra:</h4>
                <div className="chunk-preview-box">
                  <p>{userDocChunks.find(c => c.id === checkingChunkId)?.content || ""}</p>
                </div>
              </div>
            )}

            {/* Analysis streaming markdown block */}
            <div className="drawer-analysis-section">
              <h4>Kết quả đối chiếu RAG:</h4>
              <div className="analysis-result-markdown">
                {legalityAnalysis ? (
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {legalityAnalysis}
                  </ReactMarkdown>
                ) : (
                  isCheckingLegality && (
                    <div className="analysis-loading-state">
                      <div className="analysis-spinner"></div>
                      <span>Đang trích xuất cơ sở pháp lý và phân tích điều khoản...</span>
                    </div>
                  )
                )}

                {/* If checking and content is streaming, show flashing cursor */}
                {isCheckingLegality && legalityAnalysis && (
                  <span className="streaming-cursor">█</span>
                )}
              </div>
            </div>

            {/* Sources section if available */}
            {legalitySources && (
              <div className="drawer-sources-section animate-fade-in" style={{ marginTop: '1rem' }}>
                <SourcesPanel sources={legalitySources} />
              </div>
            )}
          </div>

          <div className="drawer-footer">
            {isCheckingLegality ? (
              <button className="btn-drawer-cancel" onClick={handleCancelLegalityCheck}>
                Dừng phân tích
              </button>
            ) : (
              <button className="btn-drawer-close-bottom" onClick={() => setShowAnalysisPanel(false)}>
                Đóng
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Modal showing generated API Key */}
      {createdKey && (
        <div className="modal-overlay">
          <div className="modal-card">
            <div style={{ background: 'rgba(16, 185, 129, 0.1)', color: '#34d399', width: '3.5rem', height: '3.5rem', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 1.5rem' }}>
              <Check size={28} />
            </div>
            <h3>Tạo API Key thành công!</h3>
            <p>Vui lòng sao chép API Key này. Vì lý do bảo mật, bạn sẽ không thể nhìn thấy lại nó sau khi đóng hộp thoại này.</p>
            
            <div className="modal-key-display">
              <input type="text" value={createdKey.key} readOnly />
              <button className="action-icon-btn" onClick={() => copyToClipboard(createdKey.key)} title="Copy key">
                {copied ? <Check size={18} color="#10b981" /> : <Copy size={18} />}
              </button>
            </div>

            <button className="modal-close-btn" onClick={() => setCreatedKey(null)}>
              Tôi đã lưu, đóng lại
            </button>
          </div>
        </div>
      )}

      {/* Detailed Chunk Modal */}
      {selectedDetailChunk && (
        <div 
          className="modal-overlay" 
          onClick={() => setSelectedDetailChunk(null)} 
          style={{ 
            position: 'fixed', 
            top: 0, 
            left: 0, 
            right: 0, 
            bottom: 0, 
            background: 'rgba(0, 0, 0, 0.65)', 
            backdropFilter: 'blur(8px)', 
            display: 'flex', 
            alignItems: 'center', 
            justifyContent: 'center', 
            zIndex: 9999, 
            padding: '1rem'
          }}
        >
          <div 
            className="modal-card animate-slide-up" 
            onClick={e => e.stopPropagation()} 
            style={{ 
              background: 'var(--color-surface)', 
              border: '1px solid var(--color-border)', 
              borderRadius: '20px', 
              width: '100%', 
              maxWidth: '700px', 
              maxHeight: '85vh', 
              display: 'flex', 
              flexDirection: 'column', 
              padding: 0,
              boxShadow: 'var(--shadow-2xl)', 
              overflow: 'hidden' 
            }}
          >
            {/* Header */}
            <div 
              style={{ 
                padding: '1.25rem 1.5rem', 
                borderBottom: '1px solid var(--color-border-subtle)', 
                display: 'flex', 
                justifyContent: 'space-between', 
                alignItems: 'center',
                background: 'var(--color-surface-2)'
              }}
            >
              <div>
                <h3 style={{ fontSize: '1.1rem', fontWeight: '700', color: 'var(--color-text)', margin: 0 }}>
                  Chi tiết Phân đoạn #{selectedDetailChunk.chunk_index + 1}
                </h3>
                {selectedSystemDoc && (
                  <p style={{ fontSize: '0.8rem', color: 'var(--color-text-secondary)', marginTop: '4px', marginBottom: 0 }}>
                    Nguồn: {selectedSystemDoc.original_name || selectedSystemDoc.filename}
                  </p>
                )}
              </div>
              <button 
                onClick={() => setSelectedDetailChunk(null)}
                style={{ 
                  background: 'transparent', 
                  border: 'none', 
                  fontSize: '1.5rem', 
                  color: 'var(--color-text-secondary)', 
                  cursor: 'pointer',
                  padding: '0 0.5rem',
                  lineHeight: 1
                }}
              >
                ×
              </button>
            </div>

            {/* Tags / Metadata */}
            <div 
              style={{ 
                padding: '0.75rem 1.5rem', 
                background: 'var(--color-surface)', 
                display: 'flex', 
                flexWrap: 'wrap', 
                gap: '0.75rem', 
                borderBottom: '1px solid var(--color-border-subtle)' 
              }}
            >
              {selectedDetailChunk.metadata?.doc_title && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                  <span style={{ fontSize: '0.65rem', color: 'var(--color-text-secondary)', fontWeight: '600', textTransform: 'uppercase' }}>Bộ luật</span>
                  <span className="key-code tag-book" style={{ background: 'rgba(59, 130, 246, 0.15)', color: '#3b82f6', fontWeight: '600', padding: '0.2rem 0.45rem', borderRadius: '6px' }}>
                    {selectedDetailChunk.metadata.doc_title}
                  </span>
                </div>
              )}
              {selectedDetailChunk.metadata?.chapter_title && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                  <span style={{ fontSize: '0.65rem', color: 'var(--color-text-secondary)', fontWeight: '600', textTransform: 'uppercase' }}>Chương</span>
                  <span className="key-code tag-chapter" style={{ background: 'rgba(139, 92, 246, 0.15)', color: '#8b5cf6', fontWeight: '600', padding: '0.2rem 0.45rem', borderRadius: '6px' }}>
                    {selectedDetailChunk.metadata.chapter_title}
                  </span>
                </div>
              )}
              {selectedDetailChunk.metadata?.article_num && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                  <span style={{ fontSize: '0.65rem', color: 'var(--color-text-secondary)', fontWeight: '600', textTransform: 'uppercase' }}>Điều số</span>
                  <span className="key-code tag-article" style={{ background: 'rgba(245, 158, 11, 0.15)', color: '#f59e0b', fontWeight: '600', padding: '0.2rem 0.45rem', borderRadius: '6px' }}>
                    Điều {selectedDetailChunk.metadata.article_num} {selectedDetailChunk.metadata.article_title ? `(${selectedDetailChunk.metadata.article_title})` : ''}
                  </span>
                </div>
              )}
              {selectedDetailChunk.metadata?.clause_num && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                  <span style={{ fontSize: '0.65rem', color: 'var(--color-text-secondary)', fontWeight: '600', textTransform: 'uppercase' }}>Khoản số</span>
                  <span className="key-code tag-clause" style={{ background: 'rgba(16, 185, 129, 0.15)', color: '#10b981', fontWeight: '600', padding: '0.2rem 0.45rem', borderRadius: '6px' }}>
                    Khoản {selectedDetailChunk.metadata.clause_num}
                  </span>
                </div>
              )}
            </div>

            {/* Content Body */}
            <div 
              style={{ 
                padding: '1.5rem', 
                overflowY: 'auto', 
                background: 'var(--color-surface)', 
                flex: 1, 
                lineHeight: '1.6', 
                fontSize: '0.925rem',
                color: 'var(--color-text)'
              }}
            >
              <div style={{ whiteSpace: 'pre-wrap', background: 'var(--color-surface-2)', padding: '1.25rem', borderRadius: '12px', border: '1px solid var(--color-border-subtle)', margin: 0, fontFamily: 'var(--font-family)' }}>
                {selectedDetailChunk.content}
              </div>
            </div>

            {/* Footer */}
            <div 
              style={{ 
                padding: '1rem 1.5rem', 
                borderTop: '1px solid var(--color-border-subtle)', 
                display: 'flex', 
                justifyContent: 'flex-end',
                background: 'var(--color-surface-2)' 
              }}
            >
              <button 
                className="btn-create-key" 
                onClick={() => setSelectedDetailChunk(null)}
                style={{ padding: '0.5rem 1.5rem' }}
              >
                Đóng
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
