/**
 * Admin Page — Dashboard, Documents, Users management, Model Scoring Arena.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  LayoutDashboard, FileText, Users, Scale, LogOut, Upload,
  Trash2, RefreshCw, CheckCircle, Clock, AlertCircle,
  MessageSquare, Database, GitBranch, Shield, Home, Sparkles, Cpu, Brain,
  Plus, X, Search, ChevronDown, ChevronUp, Eye, EyeOff, Star, Zap
} from 'lucide-react';
import { useAuthStore } from '../stores/authStore';
import api from '../services/api';
import toast from 'react-hot-toast';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import ThinkingBlock from '../components/chat/ThinkingBlock';
import SourcesPanel from '../components/chat/SourcesPanel';
import { authStorage } from '../utils/authStorage';
import '../styles/components/admin.css';
import GraphVisualizer, { NODE_THEMES } from '../components/admin/GraphVisualizer';

const NAV_ITEMS = [
  { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { id: 'documents', label: 'Tài liệu', icon: FileText },
  { id: 'users', label: 'Người dùng', icon: Users },
  { id: 'graph', label: 'Biểu đồ Tri thức', icon: GitBranch },
  { id: 'models', label: 'Model Pool', icon: Cpu },
  { id: 'scoring', label: 'Chấm điểm Model', icon: Scale },
];

export default function AdminPage() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const { user, logout } = useAuthStore();
  const navigate = useNavigate();

  // Redirect non-admins
  useEffect(() => {
    if (user && user.role !== 'admin') navigate('/chat');
  }, [user]);

  return (
    <div className="admin-layout">
      {/* Topbar */}
      <header className="admin-topbar">
        <div className="admin-topbar-left">
          <Link to="/home" title="Về trang chủ Home" style={{ display: 'inline-flex', alignItems: 'center', marginRight: '6px' }}>
            <Scale size={20} color="var(--color-primary)" />
          </Link>
          <span className="admin-topbar-title">Admin Panel</span>
          <span className="badge badge-primary">Legal RAG v2</span>
        </div>
        <div className="admin-topbar-right">
          <button className="btn btn-ghost btn-icon btn-sm" onClick={logout} title="Đăng xuất">
            <LogOut size={16} />
          </button>
        </div>
      </header>

      <div className="admin-body">
        {/* Side nav */}
        <nav className="admin-nav">
          {NAV_ITEMS.map(item => (
            <button
              key={item.id}
              className={`admin-nav-item ${activeTab === item.id ? 'active' : ''}`}
              onClick={() => setActiveTab(item.id)}
            >
              <item.icon size={16} />
              {item.label}
            </button>
          ))}
        </nav>

        {/* Content */}
        <div className="admin-content">
          {activeTab === 'dashboard' && <DashboardTab />}
          {activeTab === 'documents' && <DocumentsTab />}
          {activeTab === 'users' && <UsersTab />}
          {activeTab === 'graph' && <GraphTab />}
          {activeTab === 'models' && <ModelPoolTab />}
          {activeTab === 'scoring' && <ModelScoringTab />}
        </div>
      </div>
    </div>
  );
}

/* ---- Dashboard Tab ---- */
function DashboardTab() {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get('/admin/stats')
      .then(r => setStats(r.data))
      .catch(() => toast.error('Không thể tải thống kê'))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <LoadingCards />;
  if (!stats) return null;

  const cards = [
    { icon: Users, color: 'blue', value: stats.users.total, label: 'Tổng người dùng', sub: `${stats.users.active} đang hoạt động` },
    { icon: MessageSquare, color: 'green', value: stats.chat.total_sessions, label: 'Phiên chat', sub: `${stats.chat.total_messages} tin nhắn` },
    { icon: Database, color: 'purple', value: stats.documents.total_chunks || 0, label: 'Chunks Vector DB', sub: `${stats.documents.indexed} tài liệu` },
    { icon: GitBranch, color: 'orange', value: stats.graph.enabled ? 'On' : 'Off', label: 'Knowledge Graph', sub: stats.graph.enabled ? 'Đang hoạt động' : 'Chưa kết nối' },
  ];

  return (
    <>
      <div>
        <h1 style={{ fontSize: 'var(--font-size-2xl)', fontWeight: 700, marginBottom: 'var(--space-2)' }}>Dashboard</h1>
        <p style={{ color: 'var(--color-text-muted)', fontSize: 'var(--font-size-sm)' }}>Tổng quan hệ thống Legal RAG</p>
      </div>

      <div className="stat-grid">
        {cards.map((c, i) => (
          <div key={i} className="stat-card">
            <div className={`stat-card-icon ${c.color}`}>
              <c.icon size={20} />
            </div>
            <div className="stat-value">{c.value}</div>
            <div className="stat-label">{c.label}</div>
            <div style={{ fontSize: 'var(--font-size-xs)', color: 'var(--color-text-muted)' }}>{c.sub}</div>
          </div>
        ))}
      </div>

      {/* Embedding model info */}
      {stats.documents.embedding_model && stats.documents.embedding_model !== 'N/A' && (
        <div className="admin-section">
          <div className="admin-section-header">
            <span className="admin-section-title"><Database size={16} /> Embedding Model</span>
          </div>
          <div className="admin-section-body">
            <code style={{ color: 'var(--color-primary)' }}>{stats.documents.embedding_model}</code>
          </div>
        </div>
      )}
    </>
  );
}

/* ---- Documents Tab ---- */
function DocumentsTab() {
  const [docs, setDocs] = useState([]);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 10;
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [deletingIds, setDeletingIds] = useState(new Set());
  const [deleteTarget, setDeleteTarget] = useState(null);
  const fileInputRef = useRef(null);
  const pollRef = useRef(null);

  const fetchDocs = useCallback((pg) => {
    setLoading(true);
    api.get(`/documents/?page=${pg}&page_size=${PAGE_SIZE}`)
      .then(r => {
        setDocs(r.data.documents || []);
        setTotal(r.data.total || 0);
        setTotalPages(r.data.total_pages || 1);
      })
      .catch(() => toast.error('Không thể tải danh sách tài liệu'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { fetchDocs(page); }, [page, fetchDocs]);

  // Auto-refresh every 5s if any docs are pending/processing
  useEffect(() => {
    const hasPending = docs.some(d => d.status === 'pending' || d.status === 'processing');
    if (hasPending) {
      pollRef.current = setInterval(() => fetchDocs(page), 5000);
    }
    return () => clearInterval(pollRef.current);
  }, [docs, page, fetchDocs]);

  const handleUpload = async (file) => {
    if (!file) return;
    setUploading(true);
    const form = new FormData();
    form.append('file', file);
    form.append('auto_index', 'true');
    try {
      await api.post('/documents/upload', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      toast.success(`Đã upload: ${file.name}`);
      fetchDocs(1);
      setPage(1);
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Upload thất bại');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleDelete = async (id, filename) => {
    setDeleteTarget(null);
    setDeletingIds(prev => new Set(prev).add(id));
    try {
      await api.delete(`/documents/${encodeURIComponent(id)}`);
      toast.success(`Đã xóa "${filename}" khỏi hệ thống`);
      fetchDocs(page);
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Không thể xóa tài liệu');
    } finally {
      setDeletingIds(prev => { const s = new Set(prev); s.delete(id); return s; });
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    const file = e.dataTransfer.files?.[0];
    if (file) handleUpload(file);
  };

  return (
    <>
      <div>
        <h1 style={{ fontSize: 'var(--font-size-2xl)', fontWeight: 700, marginBottom: 'var(--space-2)' }}>Quản lý Tài liệu</h1>
        <p style={{ color: 'var(--color-text-muted)', fontSize: 'var(--font-size-sm)' }}>Upload và quản lý tài liệu pháp luật trong hệ thống</p>
      </div>

      {/* Upload zone */}
      <div
        className={`upload-zone ${uploading ? 'dragging' : ''}`}
        onClick={() => fileInputRef.current?.click()}
        onDragOver={e => e.preventDefault()}
        onDrop={handleDrop}
      >
        <div className="upload-zone-icon">
          {uploading
            ? <RefreshCw size={36} className="animate-spin" />
            : <Upload size={36} />
          }
        </div>
        <h4>{uploading ? 'Đang upload và index...' : 'Kéo thả hoặc click để upload'}</h4>
        <p>Hỗ trợ: .txt, .doc, .docx, .pdf (tối đa 10MB)</p>
        <p style={{ marginTop: 8, color: 'var(--color-primary)', fontSize: 'var(--font-size-xs)' }}>
          File .txt sẽ được tự động index vào VectorDB + Knowledge Graph
        </p>
      </div>

      <input
        ref={fileInputRef}
        type="file"
        accept=".txt,.doc,.docx,.pdf"
        style={{ display: 'none' }}
        onChange={e => { const f = e.target.files?.[0]; if (f) handleUpload(f); }}
      />

      {/* Documents table */}
      <div className="admin-section">
        <div className="admin-section-header">
          <span className="admin-section-title">
            <FileText size={16} /> Tài liệu đã index
            {total > 0 && <span className="badge badge-primary" style={{ marginLeft: 8 }}>{total}</span>}
          </span>
          <button className="btn btn-ghost btn-sm" onClick={() => fetchDocs(page)}>
            <RefreshCw size={14} /> Làm mới
          </button>
        </div>
        {loading ? (
          <div className="admin-section-body"><LoadingTable /></div>
        ) : docs.length === 0 ? (
          <div className="admin-section-body" style={{ textAlign: 'center', color: 'var(--color-text-muted)', padding: 'var(--space-10)' }}>
            Chưa có tài liệu nào. Upload file đầu tiên!
          </div>
        ) : (
          <>
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Tên file</th>
                  <th>Loại</th>
                  <th>Kích thước</th>
                  <th>Chunks</th>
                  <th>Trạng thái</th>
                  <th style={{ width: 60 }}></th>
                </tr>
              </thead>
              <tbody>
                {docs.map(doc => (
                  <tr key={doc.id} style={{ opacity: deletingIds.has(doc.id) ? 0.5 : 1 }}>
                    <td style={{ fontWeight: 500 }}>{doc.original_name || doc.filename}</td>
                    <td><span className="badge">{doc.file_type}</span></td>
                    <td style={{ color: 'var(--color-text-muted)' }}>
                      {doc.file_size ? `${(doc.file_size / 1024).toFixed(0)} KB` : '—'}
                    </td>
                    <td>{doc.chunks_count || 0}</td>
                    <td>
                      <StatusBadge status={doc.status} />
                    </td>
                    <td>
                      <button
                        className="btn btn-ghost btn-icon btn-sm"
                        onClick={() => setDeleteTarget({ id: doc.id, filename: doc.filename })}
                        style={{ color: 'var(--color-error)' }}
                        title={`Xóa "${doc.filename}" (bao gồm index + graph nodes)`}
                        disabled={deletingIds.has(doc.id)}
                      >
                        {deletingIds.has(doc.id)
                          ? <RefreshCw size={14} className="animate-spin" />
                          : <Trash2 size={14} />
                        }
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {/* Pagination */}
            {totalPages > 1 && (
              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                gap: 'var(--space-2)', padding: 'var(--space-4)',
                borderTop: '1px solid var(--color-border)',
              }}>
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page <= 1}
                >
                  ‹ Trước
                </button>
                {Array.from({ length: totalPages }, (_, i) => i + 1).map(p => (
                  <button
                    key={p}
                    className={`btn btn-sm ${p === page ? 'btn-primary' : 'btn-ghost'}`}
                    onClick={() => setPage(p)}
                    style={{ minWidth: 36 }}
                  >
                    {p}
                  </button>
                ))}
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages}
                >
                  Sau ›
                </button>
                <span style={{ color: 'var(--color-text-muted)', fontSize: 'var(--font-size-xs)', marginLeft: 8 }}>
                  {total} tài liệu
                </span>
              </div>
            )}
          </>
        )}
      </div>

      <ConfirmDeleteModal
        isOpen={deleteTarget !== null}
        onClose={() => setDeleteTarget(null)}
        onConfirm={() => deleteTarget && handleDelete(deleteTarget.id, deleteTarget.filename)}
        filename={deleteTarget?.filename}
      />
    </>
  );
}


/* ---- Users Tab ---- */
function UsersTab() {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchUsers = () => {
    setLoading(true);
    api.get('/admin/users')
      .then(r => setUsers(r.data.users || []))
      .catch(() => toast.error('Không thể tải danh sách users'))
      .finally(() => setLoading(false));
  };

  useEffect(() => { fetchUsers(); }, []);

  const toggleRole = async (u) => {
    const newRole = u.role === 'admin' ? 'user' : 'admin';
    if (!confirm(`Đổi role của "${u.username}" thành ${newRole}?`)) return;
    try {
      await api.put(`/admin/users/${u.id}/role?role=${newRole}`);
      toast.success(`Đã đổi role → ${newRole}`);
      fetchUsers();
    } catch { toast.error('Không thể đổi role'); }
  };

  const toggleStatus = async (u) => {
    const newStatus = !u.is_active;
    try {
      await api.put(`/admin/users/${u.id}/status?is_active=${newStatus}`);
      toast.success(newStatus ? 'Đã kích hoạt tài khoản' : 'Đã vô hiệu hóa tài khoản');
      fetchUsers();
    } catch (err) { toast.error(err.response?.data?.detail || 'Lỗi'); }
  };

  return (
    <>
      <div>
        <h1 style={{ fontSize: 'var(--font-size-2xl)', fontWeight: 700, marginBottom: 'var(--space-2)' }}>Quản lý Người dùng</h1>
        <p style={{ color: 'var(--color-text-muted)', fontSize: 'var(--font-size-sm)' }}>Xem và quản lý tài khoản trong hệ thống</p>
      </div>

      <div className="admin-section">
        <div className="admin-section-header">
          <span className="admin-section-title"><Users size={16} /> Danh sách người dùng</span>
          <button className="btn btn-ghost btn-sm" onClick={fetchUsers}>
            <RefreshCw size={14} /> Làm mới
          </button>
        </div>
        {loading ? (
          <div className="admin-section-body"><LoadingTable /></div>
        ) : (
          <table className="admin-table">
            <thead>
              <tr>
                <th>Username</th>
                <th>Email</th>
                <th>Role</th>
                <th>Trạng thái</th>
                <th>Ngày tạo</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map(u => (
                <tr key={u.id}>
                  <td style={{ fontWeight: 500 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <div style={{
                        width: 28, height: 28, borderRadius: '50%',
                        background: 'linear-gradient(135deg, var(--color-primary), var(--color-accent))',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        color: 'white', fontSize: 12, fontWeight: 700, flexShrink: 0,
                      }}>
                        {u.username[0].toUpperCase()}
                      </div>
                      {u.username}
                    </div>
                  </td>
                  <td style={{ color: 'var(--color-text-muted)' }}>{u.email}</td>
                  <td>
                    <span className={`badge ${u.role === 'admin' ? 'badge-primary' : ''}`}>
                      {u.role === 'admin' ? <Shield size={10} style={{ marginRight: 3 }} /> : null}
                      {u.role}
                    </span>
                  </td>
                  <td>
                    <span className={`badge ${u.is_active ? 'badge-success' : 'badge-error'}`}>
                      {u.is_active ? '● Active' : '○ Inactive'}
                    </span>
                  </td>
                  <td style={{ color: 'var(--color-text-muted)', fontSize: 'var(--font-size-xs)' }}>
                    {new Date(u.created_at).toLocaleDateString('vi-VN')}
                  </td>
                  <td>
                    <div style={{ display: 'flex', gap: 4 }}>
                      <button className="btn btn-ghost btn-sm" style={{ fontSize: '11px' }}
                        onClick={() => toggleRole(u)}>
                        {u.role === 'admin' ? '→ User' : '→ Admin'}
                      </button>
                      <button
                        className={`btn btn-sm ${u.is_active ? 'btn-ghost' : 'btn-primary'}`}
                        style={{ fontSize: '11px' }}
                        onClick={() => toggleStatus(u)}
                      >
                        {u.is_active ? 'Vô hiệu hóa' : 'Kích hoạt'}
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
  );
}

/* ---- Helpers ---- */
function StatusBadge({ status }) {
  const map = {
    indexed: { cls: 'indexed', icon: <CheckCircle size={11} />, label: 'Indexed' },
    pending: { cls: 'pending', icon: <Clock size={11} />, label: 'Pending' },
    error: { cls: 'error', icon: <AlertCircle size={11} />, label: 'Error' },
  };
  const s = map[status] || map.pending;
  return <span className={`status-badge ${s.cls}`}>{s.icon} {s.label}</span>;
}

function LoadingCards() {
  return (
    <div className="stat-grid">
      {[1,2,3,4].map(i => (
        <div key={i} className="skeleton" style={{ height: 130, borderRadius: 14 }} />
      ))}
    </div>
  );
}

function LoadingTable() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: 16 }}>
      {[1,2,3].map(i => <div key={i} className="skeleton" style={{ height: 40 }} />)}
    </div>
  );
}

function parseThinking(text) {
  if (!text) return { thinking: '', answer: '', phase: 'idle' };
  const OPEN = '<think>';
  const CLOSE = '</think>';
  const start = text.indexOf(OPEN);
  const end = text.indexOf(CLOSE);

  if (start !== -1 && end > start) {
    const thinking = text.slice(start + OPEN.length, end).trim();
    const answer = text.slice(end + CLOSE.length).trim();
    return { thinking, answer, phase: answer ? 'answering' : 'idle' };
  }
  if (start !== -1 && end === -1) {
    return { thinking: text.slice(start + OPEN.length), answer: '', phase: 'thinking' };
  }
  return { thinking: '', answer: text, phase: 'answering' };
}

/* ---- Built-in models list ---- */
const BUILTIN_MODELS = [
  { id: 'base_pretrained', provider: 'custom_trained', name: 'Base Pretrained Model', desc: 'Mô hình gốc chưa fine-tune', needsUrl: true },
  { id: 'custom_sft', provider: 'custom_trained', name: 'Custom SFT Model', desc: 'Mô hình đã fine-tune cho pháp luật', needsUrl: true },
  { id: 'gemini-2.5-flash', provider: 'gemini', name: 'Gemini 2.5 Flash', desc: 'Google Gemini 2.5 Flash' },
  { id: 'gemini-3.5-flash', provider: 'gemini', name: 'Gemini 3.5 Flash', desc: 'Google Gemini 3.5 Flash (mới nhất)' },
];

/* ---- Model Selector Modal ---- */
function ModelSelectorModal({ isOpen, onClose, onSelect, title = 'Chọn Model' }) {
  const [search, setSearch] = useState('');
  const [openrouterModels, setOpenrouterModels] = useState([]);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (isOpen && !loaded) {
      setLoading(true);
      api.get('/admin/openrouter-models')
        .then(r => {
          setOpenrouterModels(r.data.models || []);
          setLoaded(true);
        })
        .catch(() => toast.error('Không thể tải danh sách OpenRouter models'))
        .finally(() => setLoading(false));
    }
  }, [isOpen, loaded]);

  if (!isOpen) return null;

  const filteredBuiltin = BUILTIN_MODELS.filter(m =>
    m.name.toLowerCase().includes(search.toLowerCase())
  );

  const filteredOR = openrouterModels.filter(m =>
    m.name.toLowerCase().includes(search.toLowerCase()) ||
    m.id.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="ms-modal-overlay" onClick={onClose}>
      <div className="ms-modal" onClick={e => e.stopPropagation()}>
        <div className="ms-modal-header">
          <h3>{title}</h3>
          <button className="btn btn-ghost btn-icon btn-sm" onClick={onClose}><X size={18} /></button>
        </div>
        <div className="ms-search-bar">
          <Search size={16} />
          <input
            type="text"
            placeholder="Tìm kiếm model..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            autoFocus
          />
        </div>
        <div className="ms-modal-body">
          {/* Built-in models */}
          <div className="ms-group-label">Built-in Models</div>
          {filteredBuiltin.map(m => (
            <button key={m.id} className="ms-model-item" onClick={() => onSelect({ ...m, model_id: m.id })}>
              <div className="ms-model-item-left">
                <Cpu size={16} className="ms-model-icon builtin" />
                <div>
                  <div className="ms-model-name">{m.name}</div>
                  <div className="ms-model-desc">{m.desc}</div>
                </div>
              </div>
              {m.needsUrl && <span className="ms-tag url">URL Required</span>}
            </button>
          ))}

          {/* OpenRouter models */}
          <div className="ms-group-label" style={{ marginTop: 12 }}>
            OpenRouter Models
            {loading && <RefreshCw size={12} className="animate-spin" style={{ marginLeft: 8 }} />}
          </div>
          {filteredOR.length === 0 && !loading && (
            <div className="ms-empty">Không tìm thấy model nào.</div>
          )}
          {filteredOR.map(m => (
            <button
              key={m.id}
              className={`ms-model-item ${m.is_free ? 'free' : ''}`}
              onClick={() => onSelect({ id: m.id, model_id: m.id, provider: 'openrouter', name: m.name, desc: m.description, is_free: m.is_free, context_length: m.context_length })}
            >
              <div className="ms-model-item-left">
                <Zap size={16} className="ms-model-icon openrouter" />
                <div>
                  <div className="ms-model-name">
                    {m.name}
                    {m.is_free && <span className="ms-tag free">🆓 Free</span>}
                  </div>
                  <div className="ms-model-desc">{m.id}</div>
                </div>
              </div>
              {m.context_length > 0 && (
                <span className="ms-model-ctx">{(m.context_length / 1024).toFixed(0)}K ctx</span>
              )}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ---- Score Bar ---- */
function ScoreBar({ label, score, maxScore, color }) {
  const pct = maxScore > 0 ? Math.min((score / maxScore) * 100, 100) : 0;
  return (
    <div className="score-bar-container">
      <div className="score-bar-label">
        <span>{label}</span>
        <span className="score-bar-value" style={{ color }}>{score.toFixed(1)}/{maxScore}</span>
      </div>
      <div className="score-bar-track">
        <div className="score-bar-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
    </div>
  );
}

/* ---- Model Scoring Tab ---- */
function ModelScoringTab() {
  // Candidates (up to 4)
  const [candidates, setCandidates] = useState([null, null]);
  const [candidateUrls, setCandidateUrls] = useState({});
  const [candidateNames, setCandidateNames] = useState({});

  // Judge
  const [judge, setJudge] = useState({ id: 'gemini-3.5-flash', model_id: 'gemini-3.5-flash', provider: 'gemini', name: 'Gemini 3.5 Flash' });
  const [judgeUrl, setJudgeUrl] = useState('');
  const [judgeName, setJudgeName] = useState('');

  // Inputs
  const [question, setQuestion] = useState('');
  const [temperature, setTemperature] = useState(0.3);
  const [maxTokens, setMaxTokens] = useState(8192);
  const [topK, setTopK] = useState(5);
  const [useGraph, setUseGraph] = useState(true);

  // Modal
  const [modalOpen, setModalOpen] = useState(false);
  const [modalTarget, setModalTarget] = useState(null); // 'candidate:0', 'candidate:1', 'judge'

  // Running state
  const [isRunning, setIsRunning] = useState(false);

  // Per-candidate results
  const [candidateOutputs, setCandidateOutputs] = useState({});
  const [candidatePhases, setCandidatePhases] = useState({});
  const [candidateTimes, setCandidateTimes] = useState({});
  const [candidateErrors, setCandidateErrors] = useState({});

  // Per-candidate judge results
  const [judgeOutputs, setJudgeOutputs] = useState({});
  const [judgePhases, setJudgePhases] = useState({});
  const [judgeScores, setJudgeScores] = useState({});

  // Reasoning toggles
  const [showReasoning, setShowReasoning] = useState({});
  const [showJudgeReasoning, setShowJudgeReasoning] = useState({});

  const openModelSelector = (target) => {
    setModalTarget(target);
    setModalOpen(true);
  };

  const handleModelSelect = (model) => {
    setModalOpen(false);
    if (modalTarget === 'judge') {
      setJudge(model);
      setJudgeUrl('');
      setJudgeName('');
    } else if (modalTarget?.startsWith('candidate:')) {
      const idx = parseInt(modalTarget.split(':')[1]);
      setCandidates(prev => {
        const next = [...prev];
        next[idx] = model;
        return next;
      });
      // Clear URLs/names
      setCandidateUrls(prev => ({ ...prev, [idx]: '' }));
      setCandidateNames(prev => ({ ...prev, [idx]: '' }));
    }
  };

  const removeCandidate = (idx) => {
    setCandidates(prev => {
      const next = [...prev];
      next[idx] = null;
      return next;
    });
  };

  const addCandidateSlot = () => {
    if (candidates.length < 4) {
      setCandidates(prev => [...prev, null]);
    }
  };

  const removeCandidateSlot = (idx) => {
    if (candidates.length > 2) {
      setCandidates(prev => prev.filter((_, i) => i !== idx));
    } else {
      setCandidates(prev => {
        const next = [...prev];
        next[idx] = null;
        return next;
      });
    }
  };

  const activeCount = candidates.filter(c => c !== null).length;

  const tryParseScores = (text) => {
    try {
      // Strip <think>...</think>
      const clean = text.replace(/<think>[\s\S]*?<\/think>/g, '').trim();
      // Try to find JSON in the text
      const jsonMatch = clean.match(/\{[\s\S]*"accuracy_score"[\s\S]*\}/);
      if (jsonMatch) {
        return JSON.parse(jsonMatch[0]);
      }
      // Try parsing the whole clean text
      return JSON.parse(clean);
    } catch {
      // Regex fallback
      const scores = {};
      for (const key of ['accuracy_score', 'completeness_score', 'logic_score', 'total_score']) {
        const m = text.match(new RegExp(`"${key}"\\s*:\\s*([0-9.]+)`));
        if (m) scores[key] = parseFloat(m[1]);
      }
      const fbMatch = text.match(/"feedback"\s*:\s*"([\s\S]*?)"/);
      if (fbMatch) scores.feedback = fbMatch[1];
      if (Object.keys(scores).length > 0) return scores;
      return null;
    }
  };

  const startScoring = async () => {
    const activeCandidates = candidates.map((c, i) => {
      if (!c) return null;
      return {
        provider: c.provider,
        model_id: c.model_id || c.id,
        api_url: candidateUrls[i] || '',
        model_name: candidateNames[i] || '',
      };
    }).filter(Boolean);

    if (activeCandidates.length === 0) {
      toast.error('Vui lòng chọn ít nhất 1 model candidate.');
      return;
    }
    if (!question.trim()) {
      toast.error('Vui lòng nhập câu hỏi kiểm thử.');
      return;
    }


    setIsRunning(true);
    setCandidateOutputs({});
    setCandidatePhases({});
    setCandidateTimes({});
    setCandidateErrors({});
    setJudgeOutputs({});
    setJudgePhases({});
    setJudgeScores({});
    setShowReasoning({});
    setShowJudgeReasoning({});

    const token = authStorage.getAccessToken();
    const headers = {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    };

    const startTimes = {};

    try {
      const res = await fetch('/api/v1/admin/score-stream', {
        method: 'POST',
        headers,
        body: JSON.stringify({
          question,
          context: '',
          candidates: activeCandidates,
          judge: {
            provider: judge.provider,
            model_id: judge.model_id || judge.id,
            api_url: judge.needsUrl ? judgeUrl : '',
            model_name: judge.needsUrl ? judgeName : '',
          },
          top_k: topK,
          use_graph: useGraph,
          settings: {
            temperature,
            max_tokens: maxTokens,
            thinking_budget: 8192,
          },
        }),
      });

      if (!res.ok) throw new Error(`HTTP error ${res.status}`);

      const reader = res.body.getReader();
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

              if (currentEvent === 'candidate_start') {
                startTimes[data.index] = performance.now();
                setCandidatePhases(prev => ({ ...prev, [data.index]: 'starting' }));
              } else if (currentEvent === 'candidate_stream') {
                const parsed = parseThinking(data.content);
                setCandidateOutputs(prev => ({ ...prev, [data.index]: data.content }));
                setCandidatePhases(prev => ({ ...prev, [data.index]: parsed.phase }));
              } else if (currentEvent === 'candidate_done') {
                const elapsed = startTimes[data.index] ? Math.round(performance.now() - startTimes[data.index]) : null;
                setCandidateTimes(prev => ({ ...prev, [data.index]: elapsed }));
                setCandidatePhases(prev => ({ ...prev, [data.index]: 'done' }));
              } else if (currentEvent === 'candidate_error') {
                setCandidateErrors(prev => ({ ...prev, [data.index]: data.message }));
                setCandidatePhases(prev => ({ ...prev, [data.index]: 'error' }));
              } else if (currentEvent === 'judge_start') {
                setJudgePhases(prev => ({ ...prev, [data.index]: 'starting' }));
              } else if (currentEvent === 'judge_stream') {
                setJudgeOutputs(prev => ({ ...prev, [data.index]: data.content }));
                const parsed = parseThinking(data.content);
                setJudgePhases(prev => ({ ...prev, [data.index]: parsed.phase || 'answering' }));
              } else if (currentEvent === 'judge_done') {
                setJudgePhases(prev => ({ ...prev, [data.index]: 'done' }));
                // Prefer pre-parsed scores from backend (same logic as evaluate_data.py)
                const scores = data.scores || tryParseScores(data.content || '');
                if (scores) {
                  setJudgeScores(prev => ({ ...prev, [data.index]: scores }));
                }
              } else if (currentEvent === 'judge_error') {
                setJudgePhases(prev => ({ ...prev, [data.index]: 'error' }));
                setJudgeOutputs(prev => ({ ...prev, [data.index]: `Lỗi: ${data.message}` }));
              }
            } catch { /* ignore */ }
          }
        }
      }
    } catch (err) {
      toast.error(err.message || 'Lỗi kết nối');
    }

    setIsRunning(false);
    toast.success('Hoàn thành chấm điểm!');
  };

  const getScoreColor = (score) => {
    if (score >= 7) return '#22c55e';
    if (score >= 4) return '#eab308';
    return '#ef4444';
  };

  // Map active candidates index to data index (for SSE events)
  const activeCandidateIndexMap = candidates.reduce((acc, c, i) => {
    if (c) acc.push(i);
    return acc;
  }, []);

  return (
    <div className="scoring-container">
      <div>
        <h1 style={{ fontSize: 'var(--font-size-2xl)', fontWeight: 700, marginBottom: 'var(--space-2)' }}>
          <Scale size={24} style={{ verticalAlign: 'middle', marginRight: 8 }} />
          Model Scoring Arena
        </h1>
        <p style={{ color: 'var(--color-text-muted)', fontSize: 'var(--font-size-sm)', marginBottom: 'var(--space-6)' }}>
          Chọn các model candidate, nhập câu hỏi và câu trả lời chuẩn, chạy đánh giá và chấm điểm tự động.
        </p>
      </div>

      {/* Candidate Cards Grid */}
      <div className="scoring-section-label"><Cpu size={14} /> Model Candidates</div>
      <div className="scoring-candidates-grid">
        {candidates.map((c, idx) => (
          <div key={idx} className={`scoring-candidate-card ${c ? 'selected' : 'empty'}`}>
            {c ? (
              <>
                <div className="scoring-card-header">
                  <div className="scoring-card-model-name">
                    {c.is_free && <span className="ms-tag free" style={{ marginRight: 4 }}>🆓</span>}
                    {c.name}
                  </div>
                  <div className="scoring-card-actions">
                    <button className="btn btn-ghost btn-icon btn-xs" onClick={() => openModelSelector(`candidate:${idx}`)} title="Thay đổi"><RefreshCw size={12} /></button>
                    <button className="btn btn-ghost btn-icon btn-xs" onClick={() => removeCandidateSlot(idx)} title="Xóa"><X size={12} /></button>
                  </div>
                </div>
                <div className="scoring-card-provider">{c.provider === 'openrouter' ? c.model_id : c.provider}</div>
                {c.needsUrl && (
                  <div className="scoring-card-inputs">
                    <input type="text" placeholder="API URL (ngrok)" value={candidateUrls[idx] || ''} onChange={e => setCandidateUrls(prev => ({ ...prev, [idx]: e.target.value }))} disabled={isRunning} />
                    <input type="text" placeholder="Model Name" value={candidateNames[idx] || ''} onChange={e => setCandidateNames(prev => ({ ...prev, [idx]: e.target.value }))} disabled={isRunning} />
                  </div>
                )}
              </>
            ) : (
              <button className="scoring-card-add-btn" onClick={() => openModelSelector(`candidate:${idx}`)} disabled={isRunning}>
                <Plus size={18} />
                <span>Select a model</span>
              </button>
            )}
          </div>
        ))}

        {/* Add more button */}
        {candidates.length < 4 && (
          <button className="scoring-candidate-card empty add-more" onClick={addCandidateSlot} disabled={isRunning}>
            <Plus size={18} />
            <span>Thêm model</span>
          </button>
        )}
      </div>

      {/* Judge Model Selector */}
      <div className="scoring-section-label" style={{ marginTop: 'var(--space-6)' }}><Star size={14} /> Model Giám khảo (Judge)</div>
      <div className="scoring-judge-card">
        <div className="scoring-card-header">
          <div className="scoring-card-model-name">
            <Star size={14} style={{ color: 'var(--color-warning)', marginRight: 4 }} />
            {judge.name}
          </div>
          <button className="btn btn-ghost btn-sm" onClick={() => openModelSelector('judge')} disabled={isRunning}>
            <RefreshCw size={12} /> Thay đổi
          </button>
        </div>
        <div className="scoring-card-provider">{judge.provider === 'openrouter' ? (judge.model_id || judge.id) : judge.provider}</div>
        {judge.needsUrl && (
          <div className="scoring-card-inputs">
            <input type="text" placeholder="API URL (ngrok)" value={judgeUrl} onChange={e => setJudgeUrl(e.target.value)} disabled={isRunning} />
            <input type="text" placeholder="Model Name" value={judgeName} onChange={e => setJudgeName(e.target.value)} disabled={isRunning} />
          </div>
        )}
      </div>

      {/* Input Area */}
      <div className="scoring-config-card" style={{ marginTop: 'var(--space-6)' }}>
        <div className="scoring-config-inner">
          <div className="scoring-prompt-area">
            <label className="scoring-label">Câu hỏi kiểm thử</label>
            <textarea className="scoring-textarea" placeholder="Nhập câu hỏi pháp luật..." value={question} onChange={e => setQuestion(e.target.value)} disabled={isRunning} rows={8} />
          </div>
          <div className="scoring-params-area">
            <div className="compare-param-field">
              <label>Temperature: <strong>{temperature}</strong></label>
              <input type="range" min="0" max="1.5" step="0.1" value={temperature} onChange={e => setTemperature(parseFloat(e.target.value))} disabled={isRunning} />
            </div>
            <div className="compare-param-field">
              <label>Max Tokens: <strong>{maxTokens}</strong></label>
              <input type="range" min="512" max="16384" step="512" value={maxTokens} onChange={e => setMaxTokens(parseInt(e.target.value))} disabled={isRunning} />
            </div>
            <div className="compare-param-field">
              <label>Top-K Documents: <strong>{topK}</strong></label>
              <input type="range" min="1" max="15" step="1" value={topK} onChange={e => setTopK(parseInt(e.target.value))} disabled={isRunning} />
            </div>
            <div className="compare-param-checkbox">
              <label>
                <input type="checkbox" checked={useGraph} onChange={e => setUseGraph(e.target.checked)} disabled={isRunning} />
                <span>Sử dụng Knowledge Graph</span>
              </label>
            </div>
          </div>
        </div>
        <div className="compare-action-row">
          <button className={`btn btn-primary btn-compare ${isRunning ? 'loading' : ''}`} onClick={startScoring} disabled={isRunning || activeCount === 0 || !question.trim()}>
            {isRunning ? 'Đang chạy đánh giá...' : `Bắt đầu Chấm điểm (${activeCount} models)`}
          </button>
        </div>
      </div>

      {/* Results */}
      {(Object.keys(candidateOutputs).length > 0 || isRunning) && (
        <div className="scoring-results-section">
          <div className="scoring-section-label"><Sparkles size={14} /> Kết quả</div>
          <div className="scoring-results-grid" style={{ gridTemplateColumns: `repeat(${Math.min(activeCandidateIndexMap.length, 4)}, 1fr)` }}>
            {activeCandidateIndexMap.map((origIdx, dataIdx) => {
              const c = candidates[origIdx];
              if (!c) return null;
              const output = candidateOutputs[dataIdx] || '';
              const phase = candidatePhases[dataIdx] || 'idle';
              const error = candidateErrors[dataIdx];
              const elapsed = candidateTimes[dataIdx];
              const { thinking, answer } = parseThinking(output);
              const jOutput = judgeOutputs[dataIdx] || '';
              const jPhase = judgePhases[dataIdx] || 'idle';
              const jScores = judgeScores[dataIdx];
              const { thinking: jThinking, answer: jAnswer } = parseThinking(jOutput);
              const showR = showReasoning[dataIdx] ?? true;
              const showJR = showJudgeReasoning[dataIdx] ?? false;

              return (
                <div key={origIdx} className="scoring-result-column">
                  {/* Header */}
                  <div className="scoring-result-header">
                    <div className="scoring-result-model-name">{c.name}</div>
                    <div className="scoring-result-status">
                      {error ? (
                        <span className="compare-badge error">❌ Lỗi</span>
                      ) : phase === 'done' && elapsed ? (
                        <span className="compare-badge success">⏱️ {elapsed}ms</span>
                      ) : phase === 'thinking' ? (
                        <span className="compare-badge thinking">🧠 Suy luận...</span>
                      ) : phase === 'answering' ? (
                        <span className="compare-badge answering">⚡ Trả lời...</span>
                      ) : phase === 'starting' ? (
                        <span className="compare-badge thinking">⏳ Khởi chạy...</span>
                      ) : (
                        <span className="compare-badge idle">Chờ...</span>
                      )}
                    </div>
                  </div>

                  {/* Candidate Output */}
                  <div className="scoring-result-body">
                    {error && <div className="scoring-error-msg">{error}</div>}

                    {/* Reasoning toggle */}
                    {thinking && (
                      <div className="scoring-reasoning-section">
                        <button className="scoring-reasoning-toggle" onClick={() => setShowReasoning(prev => ({ ...prev, [dataIdx]: !showR }))}>
                          {showR ? <EyeOff size={12} /> : <Eye size={12} />}
                          {showR ? 'Ẩn Reasoning' : 'Hiện Reasoning'}
                        </button>
                        {showR && (
                          <div className="compare-thinking-wrap">
                            <ThinkingBlock content={thinking} isStreaming={phase === 'thinking'} />
                          </div>
                        )}
                      </div>
                    )}

                    {/* Answer */}
                    <div className="compare-markdown-content">
                      {answer ? (
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{answer}</ReactMarkdown>
                      ) : !error && phase !== 'idle' ? (
                        <p className="compare-empty-placeholder">Đang xử lý...</p>
                      ) : (
                        <p className="compare-empty-placeholder">Chưa có kết quả.</p>
                      )}
                    </div>
                  </div>

                  {/* Judge Scoring */}
                  {(jPhase !== 'idle' || jScores) && (
                    <div className="scoring-judge-section">
                      <div className="scoring-judge-header">
                        <Star size={14} style={{ color: 'var(--color-warning)' }} />
                        <span>Chấm điểm bởi {judge.name}</span>
                        {jPhase === 'done' || jPhase === 'error' ? null : (
                          <RefreshCw size={12} className="animate-spin" />
                        )}
                      </div>

                      {/* Judge reasoning toggle */}
                      {jThinking && (
                        <div className="scoring-reasoning-section">
                          <button className="scoring-reasoning-toggle" onClick={() => setShowJudgeReasoning(prev => ({ ...prev, [dataIdx]: !showJR }))}>
                            {showJR ? <EyeOff size={12} /> : <Eye size={12} />}
                            {showJR ? 'Ẩn Judge Reasoning' : 'Hiện Judge Reasoning'}
                          </button>
                          {showJR && (
                            <div className="compare-thinking-wrap">
                              <ThinkingBlock content={jThinking} isStreaming={jPhase === 'thinking'} />
                            </div>
                          )}
                        </div>
                      )}

                      {/* Scores */}
                      {jScores && (
                        <div className="scoring-scores-panel">
                          <ScoreBar label="Chính xác pháp lý" score={jScores.accuracy_score || 0} maxScore={4} color="#3b82f6" />
                          <ScoreBar label="Đầy đủ & chi tiết" score={jScores.completeness_score || 0} maxScore={3} color="#8b5cf6" />
                          <ScoreBar label="Logic & lập luận" score={jScores.logic_score || 0} maxScore={3} color="#06b6d4" />
                          <div className="scoring-total-score" style={{ borderColor: getScoreColor(jScores.total_score || 0) }}>
                            <span className="scoring-total-label">Tổng điểm</span>
                            <span className="scoring-total-value" style={{ color: getScoreColor(jScores.total_score || 0) }}>
                              {(jScores.total_score || 0).toFixed(1)}/10
                            </span>
                          </div>
                          {jScores.feedback && (
                            <div className="scoring-feedback">
                              <strong>Nhận xét:</strong>
                              <p>{jScores.feedback}</p>
                            </div>
                          )}
                        </div>
                      )}

                      {/* Raw judge answer if no scores parsed yet */}
                      {!jScores && jAnswer && (
                        <div className="compare-markdown-content" style={{ fontSize: 'var(--font-size-sm)' }}>
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>{jAnswer}</ReactMarkdown>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Model Selector Modal */}
      <ModelSelectorModal
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        onSelect={handleModelSelect}
        title={modalTarget === 'judge' ? 'Chọn Model Giám khảo' : 'Chọn Model Candidate'}
      />
    </div>
  );
}

/* ---- Model Pool Management Tab ---- */
function ModelPoolTab() {
  const [pool, setPool] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showAddForm, setShowAddForm] = useState(false);
  const [addProvider, setAddProvider] = useState('gemini');
  const [addDisplayName, setAddDisplayName] = useState('');
  const [addModelId, setAddModelId] = useState('gemini-2.5-flash');
  const [addApiUrl, setAddApiUrl] = useState('');
  const [addModelName, setAddModelName] = useState('');
  const [orModels, setOrModels] = useState([]);
  const [orSearch, setOrSearch] = useState('');
  const [orLoading, setOrLoading] = useState(false);
  const [addPricePrompt, setAddPricePrompt] = useState('');
  const [addPriceCompletion, setAddPriceCompletion] = useState('');
  const [editModel, setEditModel] = useState(null);
  const [editPricePrompt, setEditPricePrompt] = useState('');
  const [editPriceCompletion, setEditPriceCompletion] = useState('');

  const fetchPool = async () => {
    setLoading(true);
    try {
      const res = await api.get('/admin/model-pool');
      setPool(res.data.models || []);
    } catch (err) {
      toast.error('Không thể tải danh sách model pool');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchPool(); }, []);

  const fetchOrModels = async () => {
    setOrLoading(true);
    try {
      const res = await api.get('/admin/openrouter-models');
      setOrModels(res.data.models || []);
    } catch { toast.error('Không thể tải model OpenRouter'); }
    finally { setOrLoading(false); }
  };

  const handleAdd = async () => {
    if (!addDisplayName.trim()) {
      toast.error('Vui lòng nhập tên hiển thị cho model.');
      return;
    }
    const entry = {
      provider: addProvider,
      display_name: addDisplayName,
      model_id: addProvider === 'gemini' ? addModelId : (addProvider === 'openrouter' ? addModelId : ''),
      model_name: addProvider === 'custom_trained' ? addModelName : '',
      api_url: addProvider === 'custom_trained' ? addApiUrl : '',
      price_prompt: parseFloat(addPricePrompt) || 0,
      price_completion: parseFloat(addPriceCompletion) || 0,
    };
    try {
      await api.post('/admin/model-pool', entry);
      toast.success('Đã thêm model vào pool!');
      setShowAddForm(false);
      setAddDisplayName('');
      setAddApiUrl('');
      setAddModelName('');
      setAddModelId('gemini-2.5-flash');
      setAddPricePrompt('');
      setAddPriceCompletion('');
      fetchPool();
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Lỗi thêm model');
    }
  };

  const handleDelete = async (id) => {
    if (!confirm('Xóa model này khỏi pool?')) return;
    try {
      await api.delete(`/admin/model-pool/${id}`);
      toast.success('Đã xóa model khỏi pool');
      fetchPool();
    } catch { toast.error('Lỗi xóa model'); }
  };

  const openEditPricing = (m) => {
    setEditModel(m);
    setEditPricePrompt(String(m.price_prompt || 0));
    setEditPriceCompletion(String(m.price_completion || 0));
  };

  const handleUpdatePricing = async () => {
    if (!editModel) return;
    try {
      await api.patch(`/admin/model-pool/${editModel.id}`, {
        price_prompt: parseFloat(editPricePrompt) || 0,
        price_completion: parseFloat(editPriceCompletion) || 0,
      });
      toast.success('Cập nhật giá thành công!');
      setEditModel(null);
      fetchPool();
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Lỗi cập nhật giá');
    }
  };

  const providerLabel = (p) => {
    if (p === 'gemini') return '✨ Gemini';
    if (p === 'openrouter') return '🌐 OpenRouter';
    if (p === 'custom_trained') return '🤖 Custom';
    return p;
  };

  const filteredOrModels = orModels.filter(m =>
    (m.name || m.id || '').toLowerCase().includes(orSearch.toLowerCase())
  );

  return (
    <div className="admin-tab-pane animate-fade-in">
      <div className="admin-section-header">
        <h2>🧩 Quản lý Model Pool</h2>
        <p>Thêm / xóa model được phép sử dụng trong Chatbot. Cả Admin và User chỉ chọn model từ pool này.</p>
      </div>

      <div style={{ marginBottom: 16, display: 'flex', gap: 10 }}>
        <button className="btn btn-primary" onClick={() => { setShowAddForm(true); setAddProvider('gemini'); }}>
          <Plus size={14} /> Thêm Model
        </button>
        <button className="btn btn-ghost" onClick={fetchPool}>
          <RefreshCw size={14} /> Làm mới
        </button>
      </div>

      {/* Add Form Modal */}
      {showAddForm && (
        <>
          <div className="modal-backdrop" onClick={() => setShowAddForm(false)} />
          <div className="model-selector-modal">
            <div className="modal-header">
              <h3>Thêm Model vào Pool</h3>
              <button className="btn btn-ghost btn-icon btn-sm" onClick={() => setShowAddForm(false)}><X size={16} /></button>
            </div>
            <div className="modal-body" style={{ padding: '16px 20px' }}>
              {/* Provider */}
              <div className="settings-field" style={{ marginBottom: 12 }}>
                <label style={{ fontWeight: 600, marginBottom: 6, display: 'block' }}>Provider</label>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  {[
                    { v: 'custom_trained', l: '🤖 Custom Model' },
                    { v: 'gemini', l: '✨ Gemini' },
                    { v: 'openrouter', l: '🌐 OpenRouter' },
                  ].map(p => (
                    <button
                      key={p.v}
                      className={`provider-option ${addProvider === p.v ? 'active' : ''}`}
                      onClick={() => {
                        setAddProvider(p.v);
                        if (p.v === 'openrouter' && orModels.length === 0) fetchOrModels();
                        if (p.v === 'gemini') setAddModelId('gemini-2.5-flash');
                      }}
                      style={{ padding: '8px 14px', fontSize: 13 }}
                    >
                      {p.l}
                    </button>
                  ))}
                </div>
              </div>

              {/* Display Name */}
              <div className="settings-field" style={{ marginBottom: 12 }}>
                <label style={{ fontWeight: 600, marginBottom: 4, display: 'block' }}>Tên hiển thị</label>
                <input className="input" placeholder="VD: Legal SFT v3, Gemini Flash..." value={addDisplayName} onChange={e => setAddDisplayName(e.target.value)} />
              </div>

              {/* Gemini variant */}
              {addProvider === 'gemini' && (
                <div className="settings-field" style={{ marginBottom: 12 }}>
                  <label style={{ fontWeight: 600, marginBottom: 4, display: 'block' }}>Gemini Model</label>
                  <select className="input" value={addModelId} onChange={e => setAddModelId(e.target.value)}>
                    <option value="gemini-2.5-flash">Gemini 2.5 Flash</option>
                    <option value="gemini-3.5-flash">Gemini 3.5 Flash</option>
                  </select>
                </div>
              )}

              {/* Custom model fields */}
              {addProvider === 'custom_trained' && (
                <>
                  <div className="settings-field" style={{ marginBottom: 12 }}>
                    <label style={{ fontWeight: 600, marginBottom: 4, display: 'block' }}>API URL (ngrok)</label>
                    <input className="input" placeholder="https://xxxx.ngrok-free.app" value={addApiUrl} onChange={e => setAddApiUrl(e.target.value)} />
                  </div>
                  <div className="settings-field" style={{ marginBottom: 12 }}>
                    <label style={{ fontWeight: 600, marginBottom: 4, display: 'block' }}>Model Name</label>
                    <input className="input" placeholder="claspi2509/legal-AI-qwen3.5..." value={addModelName} onChange={e => setAddModelName(e.target.value)} />
                  </div>
                </>
              )}

              {/* OpenRouter model list */}
              {addProvider === 'openrouter' && (
                <div className="settings-field" style={{ marginBottom: 12 }}>
                  <label style={{ fontWeight: 600, marginBottom: 4, display: 'block' }}>Chọn Model OpenRouter</label>
                  <div style={{ position: 'relative', marginBottom: 8 }}>
                    <Search size={14} style={{ position: 'absolute', left: 10, top: 10, opacity: 0.5 }} />
                    <input className="input" placeholder="Tìm model..." value={orSearch} onChange={e => setOrSearch(e.target.value)} style={{ paddingLeft: 30 }} />
                  </div>
                  {orLoading ? (
                    <div style={{ padding: 16, textAlign: 'center', opacity: 0.6 }}>Đang tải...</div>
                  ) : (
                    <div style={{ maxHeight: 200, overflow: 'auto', border: '1px solid var(--color-border)', borderRadius: 8 }}>
                      {filteredOrModels.slice(0, 50).map(m => (
                        <div
                          key={m.id}
                          className={`model-list-item ${addModelId === m.id ? 'selected' : ''}`}
                          onClick={() => { setAddModelId(m.id); if (!addDisplayName) setAddDisplayName(m.name || m.id); }}
                          style={{ padding: '8px 12px', cursor: 'pointer', borderBottom: '1px solid var(--color-border)', display: 'flex', alignItems: 'center', gap: 8, background: addModelId === m.id ? 'var(--color-primary-alpha)' : 'transparent' }}
                        >
                          {m.is_free && <span style={{ fontSize: 11, background: '#10b981', color: '#fff', padding: '1px 6px', borderRadius: 4 }}>FREE</span>}
                          <span style={{ fontSize: 13 }}>{m.name || m.id}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Pricing */}
              <div style={{ marginBottom: 12, display: 'flex', gap: 10 }}>
                <div className="settings-field" style={{ flex: 1 }}>
                  <label style={{ fontWeight: 600, marginBottom: 4, display: 'block', fontSize: 13 }}>$ / 1M prompt tokens</label>
                  <input className="input" type="number" step="0.01" min="0" placeholder="0.00" value={addPricePrompt} onChange={e => setAddPricePrompt(e.target.value)} />
                </div>
                <div className="settings-field" style={{ flex: 1 }}>
                  <label style={{ fontWeight: 600, marginBottom: 4, display: 'block', fontSize: 13 }}>$ / 1M completion tokens</label>
                  <input className="input" type="number" step="0.01" min="0" placeholder="0.00" value={addPriceCompletion} onChange={e => setAddPriceCompletion(e.target.value)} />
                </div>
              </div>

              <button className="btn btn-primary" onClick={handleAdd} style={{ marginTop: 8, width: '100%' }}>
                Thêm vào Pool
              </button>
            </div>
          </div>
        </>
      )}

      {/* Pool Table */}
      {loading ? (
        <div className="admin-loading-state">
          {[1,2,3].map(i => <div key={i} className="skeleton" style={{ height: 48, marginBottom: 8 }} />)}
        </div>
      ) : pool.length === 0 ? (
        <div className="admin-empty-state">
          <Cpu size={40} style={{ opacity: 0.3, marginBottom: 12 }} />
          <p>Chưa có model nào trong pool. Thêm model để user có thể sử dụng chatbot.</p>
        </div>
      ) : (
        <table className="admin-table">
          <thead>
            <tr>
              <th>Tên hiển thị</th>
              <th>Provider</th>
              <th>Model ID / Name</th>
              <th>Giá ($/1M)</th>
              <th>Trạng thái</th>
              <th style={{ textAlign: 'right' }}>Hành động</th>
            </tr>
          </thead>
          <tbody>
            {pool.map(m => (
              <tr key={m.id}>
                <td style={{ fontWeight: 600 }}>{m.display_name || m.model_id || m.id}</td>
                <td><span className="badge badge-primary" style={{ fontSize: 11 }}>{providerLabel(m.provider)}</span></td>
                <td style={{ fontSize: 12, opacity: 0.7 }}>{m.model_id || m.model_name || '—'}</td>
                <td style={{ fontSize: 12 }}>
                  <div>P: ${(m.price_prompt || 0).toFixed(2)}</div>
                  <div>C: ${(m.price_completion || 0).toFixed(2)}</div>
                </td>
                <td>
                  <span className={`status-badge ${m.is_active ? 'active' : 'inactive'}`}>
                    {m.is_active ? '✅ Active' : '⏸ Inactive'}
                  </span>
                </td>
                <td style={{ textAlign: 'right', display: 'flex', gap: 4, justifyContent: 'flex-end' }}>
                  <button className="btn btn-ghost btn-sm" onClick={() => openEditPricing(m)} title="Sửa giá" style={{ color: '#3b82f6', fontSize: 12 }}>
                    ✏️
                  </button>
                  <button className="btn btn-ghost btn-sm" onClick={() => handleDelete(m.id)} title="Xóa khỏi pool" style={{ color: '#ef4444' }}>
                    <Trash2 size={14} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* Edit Pricing Modal */}
      {editModel && (
        <>
          <div className="modal-backdrop" onClick={() => setEditModel(null)} />
          <div className="model-selector-modal" style={{ maxWidth: 420 }}>
            <div className="modal-header">
              <h3>Sửa giá - {editModel.display_name}</h3>
              <button className="btn btn-ghost btn-icon btn-sm" onClick={() => setEditModel(null)}><X size={16} /></button>
            </div>
            <div className="modal-body" style={{ padding: '16px 20px' }}>
              <div style={{ marginBottom: 12, display: 'flex', gap: 10 }}>
                <div className="settings-field" style={{ flex: 1 }}>
                  <label style={{ fontWeight: 600, marginBottom: 4, display: 'block', fontSize: 13 }}>$ / 1M prompt tokens</label>
                  <input className="input" type="number" step="0.01" min="0" value={editPricePrompt} onChange={e => setEditPricePrompt(e.target.value)} />
                </div>
                <div className="settings-field" style={{ flex: 1 }}>
                  <label style={{ fontWeight: 600, marginBottom: 4, display: 'block', fontSize: 13 }}>$ / 1M completion tokens</label>
                  <input className="input" type="number" step="0.01" min="0" value={editPriceCompletion} onChange={e => setEditPriceCompletion(e.target.value)} />
                </div>
              </div>
              <button className="btn btn-primary" onClick={handleUpdatePricing} style={{ width: '100%' }}>
                Cập nhật giá
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

/* ---- Graph Tab ---- */
function GraphTab() {
  const [stats, setStats] = useState(null);
  const [loadingStats, setLoadingStats] = useState(true);
  const [nodes, setNodes] = useState([]);
  const [edges, setEdges] = useState([]);
  const [loadingGraph, setLoadingGraph] = useState(false);
  const [selectedNode, setSelectedNode] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');
  
  // Filters & limits
  const [selectedLabels, setSelectedLabels] = useState(['Law', 'Chapter', 'Article']);
  const [limit, setLimit] = useState(150);

  // Cypher Console
  const [cypher, setCypher] = useState('MATCH (n) RETURN n LIMIT 50');
  const [isRunningCypher, setIsRunningCypher] = useState(false);
  const [cypherResultMode, setCypherResultMode] = useState('graph'); // 'graph' or 'table'
  const [cypherRows, setCypherRows] = useState([]);

  // Load stats
  const fetchStats = () => {
    setLoadingStats(true);
    api.get('/admin/graph/stats')
      .then(r => setStats(r.data))
      .catch(() => toast.error('Không thể kết nối Neo4j hoặc tải thống kê'))
      .finally(() => setLoadingStats(false));
  };

  // Load initial graph data
  const fetchGraphData = (labelsOverride, limitOverride) => {
    setLoadingGraph(true);
    const activeLabels = labelsOverride !== undefined ? labelsOverride : selectedLabels;
    const activeLimit = limitOverride !== undefined ? limitOverride : limit;
    api.post('/admin/graph/data', { limit: activeLimit, labels: activeLabels })
      .then(r => {
        const rawNodes = r.data.nodes || [];
        const rawEdges = r.data.edges || [];
        
        // Filter out isolated nodes to keep the graph beautifully connected and structured
        const connectedIds = new Set();
        rawEdges.forEach(e => {
          connectedIds.add(e.source);
          connectedIds.add(e.target);
        });
        
        // Keep node if it has connections OR if there are no edges at all
        const filteredNodes = rawEdges.length > 0 
          ? rawNodes.filter(n => connectedIds.has(n.id)) 
          : rawNodes;
          
        setNodes(filteredNodes);
        setEdges(rawEdges);
        setCypherRows([]);
        setSelectedNode(null);
      })
      .catch((err) => toast.error('Lỗi khi tải dữ liệu đồ thị: ' + (err.response?.data?.detail || err.message)))
      .finally(() => setLoadingGraph(false));
  };

  useEffect(() => {
    fetchStats();
    fetchGraphData();
  }, []);

  // Filter handlers
  const handleLabelToggle = (label) => {
    let nextLabels;
    if (selectedLabels.includes(label)) {
      nextLabels = selectedLabels.filter(l => l !== label);
    } else {
      nextLabels = [...selectedLabels, label];
    }
    setSelectedLabels(nextLabels);
    // Fetch data immediately when labels filter changes
    fetchGraphData(nextLabels);
  };

  // Neighbor loading
  const loadNeighbors = (node) => {
    if (!node) return;
    toast.promise(
      api.post('/admin/graph/neighbors', { 
        node_id: node.id,
        existing_node_ids: nodes.map(n => n.id)
      })
        .then(r => {
          const newNodes = r.data.nodes || [];
          const newEdges = r.data.edges || [];

          if (newNodes.length === 0) {
            toast('Nút này không có thêm liên kết nào khác', { icon: 'ℹ️' });
            return;
          }

          setNodes(prevNodes => {
            const existingIds = new Set(prevNodes.map(n => n.id));
            const merged = [...prevNodes];
            newNodes.forEach(n => {
              if (!existingIds.has(n.id)) {
                merged.push(n);
              }
            });
            return merged;
          });

          setEdges(prevEdges => {
            const existingIds = new Set(prevEdges.map(e => e.id));
            const merged = [...prevEdges];
            newEdges.forEach(e => {
              if (!existingIds.has(e.id)) {
                merged.push(e);
              }
            });
            return merged;
          });

          if (selectedNode && selectedNode.id === node.id) {
            const updated = newNodes.find(n => n.id === node.id) || node;
            setSelectedNode(updated);
          }

          toast.success(`Đã tải thêm ${newNodes.length} nút lân cận`);
        }),
      {
        loading: 'Đang tải liên kết lân cận...',
        success: 'Hoàn thành!',
        error: 'Lỗi tải liên kết lân cận',
      }
    );
  };

  // Run custom cypher query
  const runCypherQuery = () => {
    if (!cypher.trim()) {
      toast.error('Nhập câu lệnh Cypher trước khi chạy.');
      return;
    }

    setIsRunningCypher(true);
    api.post('/admin/graph/query', { cypher })
      .then(r => {
        const queryNodes = r.data.nodes || [];
        const queryEdges = r.data.edges || [];
        const queryRows = r.data.rows || [];

        setNodes(queryNodes);
        setEdges(queryEdges);
        setCypherRows(queryRows);
        setSelectedNode(null);

        if (queryRows.length === 0 && queryNodes.length === 0) {
          toast('Truy vấn không trả về kết quả nào', { icon: 'ℹ️' });
        } else {
          toast.success(`Thành công! Trả về ${queryRows.length} dòng dữ liệu.`);
          if (queryNodes.length > 0) {
            setCypherResultMode('graph');
          } else {
            setCypherResultMode('table');
          }
        }
      })
      .catch(err => {
        toast.error(err.response?.data?.detail || err.message || 'Lỗi cú pháp Cypher');
      })
      .finally(() => setIsRunningCypher(false));
  };

  // Search input selection
  const handleSearchSelect = (e) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;
    const found = nodes.find(n => {
      const name = (n.properties?.title || n.properties?.name || '').toLowerCase();
      return name.includes(searchQuery.toLowerCase());
    });
    if (found) {
      setSelectedNode(found);
      toast.success(`Đã chọn nút: ${found.properties?.title || found.properties?.name || found.id}`);
    } else {
      toast.error('Không tìm thấy nút phù hợp trong đồ thị đang hiển thị.');
    }
  };

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 style={{ fontSize: 'var(--font-size-2xl)', fontWeight: 700, marginBottom: 'var(--space-2)' }}>Đồ thị Tri thức (Knowledge Graph)</h1>
          <p style={{ color: 'var(--color-text-muted)', fontSize: 'var(--font-size-sm)' }}>
            Biểu diễn và truy vấn cơ sở tri thức pháp luật trên Neo4j
          </p>
        </div>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button className="btn btn-ghost btn-sm" onClick={fetchStats} disabled={loadingStats}>
            <RefreshCw size={14} className={loadingStats ? 'animate-spin' : ''} /> Cập nhật thống kê
          </button>
        </div>
      </div>

      {/* Mini stats indicators */}
      <div className="graph-stats-grid">
        <div className="graph-stat-card">
          <div className="graph-stat-num">{stats?.total_nodes ?? '—'}</div>
          <div className="graph-stat-lbl">Tổng số nút</div>
        </div>
        <div className="graph-stat-card">
          <div className="graph-stat-num">{stats?.total_relationships ?? '—'}</div>
          <div className="graph-stat-lbl">Tổng liên kết</div>
        </div>
        <div className="graph-stat-card">
          <div className="graph-stat-num" style={{ fontSize: '12px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {stats?.labels ? Object.keys(stats.labels).length : '—'} loại nút
          </div>
          <div className="graph-stat-lbl">Đa dạng nhãn</div>
        </div>
      </div>

      <div className="graph-layout-grid">
        {/* Left Side: Visualizer and filters */}
        <div className="graph-main-panel">
          <div className="graph-toolbar">
            <div className="graph-toolbar-filters">
              <span style={{ fontSize: '11px', fontWeight: 600, color: 'var(--color-text-muted)', textTransform: 'uppercase' }}>
                Lọc nhãn ban đầu:
              </span>
              {['Law', 'Chapter', 'Article', 'Clause', 'Concept', 'Actor', 'Action'].map(lbl => (
                <label key={lbl} className="graph-filter-checkbox">
                  <input
                    type="checkbox"
                    checked={selectedLabels.includes(lbl)}
                    onChange={() => handleLabelToggle(lbl)}
                    disabled={loadingGraph}
                  />
                  <span>{lbl}</span>
                </label>
              ))}
              
              <span style={{ fontSize: '11px', fontWeight: 600, color: 'var(--color-text-muted)', textTransform: 'uppercase', marginLeft: '16px', borderLeft: '1px solid var(--color-border)', paddingLeft: '16px' }}>
                Số nút tối đa:
              </span>
              <select
                value={limit}
                onChange={(e) => {
                  const nextLimit = parseInt(e.target.value);
                  setLimit(nextLimit);
                  fetchGraphData(undefined, nextLimit);
                }}
                disabled={loadingGraph}
                style={{
                  background: 'var(--color-surface-2)',
                  border: '1px solid var(--color-border)',
                  color: 'var(--color-text)',
                  borderRadius: 'var(--radius-sm)',
                  padding: '2px 8px',
                  fontSize: '11px',
                  cursor: 'pointer',
                  outline: 'none',
                }}
              >
                <option value={50}>50</option>
                <option value={100}>100</option>
                <option value={150}>150</option>
                <option value={200}>200</option>
                <option value={300}>300</option>
                <option value={500}>500</option>
              </select>
            </div>

            {/* Quick search inside active graph */}
            <form onSubmit={handleSearchSelect} className="graph-search-input-wrap">
              <Search size={14} />
              <input
                type="text"
                placeholder="Tìm nút trong đồ thị..."
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
              />
            </form>
          </div>

          {/* Interactive Graph view vs Table view */}
          {cypherResultMode === 'table' && cypherRows.length > 0 ? (
            <div className="query-table-wrap">
              <div className="cypher-console-header" style={{ borderBottom: '1px solid var(--color-border)' }}>
                <span className="cypher-console-title">Bảng kết quả Cypher ({cypherRows.length} hàng)</span>
                <button className="btn btn-ghost btn-xs" onClick={() => setCypherResultMode('graph')}>
                  Quay lại đồ thị
                </button>
              </div>
              <table className="query-results-table">
                <thead>
                  <tr>
                    {Object.keys(cypherRows[0] || {}).map(k => (
                      <th key={k}>{k}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {cypherRows.map((row, idx) => (
                    <tr key={idx}>
                      {Object.values(row).map((v, i) => (
                        <td key={i}>{typeof v === 'object' ? JSON.stringify(v) : String(v)}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="graph-canvas-wrap">
              {loadingGraph && (
                <div style={{
                  position: 'absolute',
                  inset: 0,
                  background: 'rgba(11, 15, 25, 0.6)',
                  zIndex: 20,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  backdropFilter: 'blur(2px)',
                  borderRadius: 'var(--radius-lg)'
                }}>
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10 }}>
                    <RefreshCw size={28} className="animate-spin" color="var(--color-primary)" />
                    <span style={{ fontSize: '13px', color: '#fff', fontWeight: 500 }}>Đang tải đồ thị...</span>
                  </div>
                </div>
              )}
              <GraphVisualizer
                nodes={nodes}
                edges={edges}
                selectedNode={selectedNode}
                onNodeSelect={setSelectedNode}
                onNodeDoubleClick={loadNeighbors}
              />
            </div>
          )}
        </div>

        {/* Right Side: Cypher console & details sidebar */}
        <div className="graph-sidebar-panel">
          {/* Cypher console */}
          <div className="cypher-console">
            <div className="cypher-console-header">
              <div className="cypher-console-title">
                <Brain size={14} style={{ color: 'var(--color-primary)' }} />
                Cypher Console
              </div>
            </div>
            <div className="cypher-textarea-wrap">
              <textarea
                className="cypher-textarea"
                rows={4}
                value={cypher}
                onChange={e => setCypher(e.target.value)}
                placeholder="MATCH (n) RETURN n LIMIT 25"
                disabled={isRunningCypher}
              />
            </div>
            <div className="cypher-actions">
              <span style={{ fontSize: 10, color: 'var(--color-text-muted)' }}>
                * Chỉ hỗ trợ đọc (read-only)
              </span>
              <div style={{ display: 'flex', gap: 6 }}>
                {cypherRows.length > 0 && (
                  <button
                    className="btn btn-ghost btn-sm"
                    onClick={() => setCypherResultMode(prev => prev === 'graph' ? 'table' : 'graph')}
                    style={{ fontSize: 11 }}
                  >
                    {cypherResultMode === 'graph' ? 'Xem Bảng' : 'Xem Đồ thị'}
                  </button>
                )}
                <button
                  className={`btn btn-primary btn-sm ${isRunningCypher ? 'loading' : ''}`}
                  onClick={runCypherQuery}
                  disabled={isRunningCypher}
                  style={{ fontSize: 11, padding: '4px 12px' }}
                >
                  {isRunningCypher ? 'Đang chạy...' : 'Chạy lệnh'}
                </button>
              </div>
            </div>
          </div>

          {/* Selected Node Details */}
          <div className="graph-details-card">
            <div className="graph-details-header">
              <Database size={14} style={{ color: 'var(--color-accent)' }} />
              <strong style={{ fontSize: 13, color: 'var(--color-text)' }}>Thông tin chi tiết nút</strong>
            </div>
            <div className="graph-details-body">
              {selectedNode ? (
                <>
                  <div className="node-meta-pills">
                    {selectedNode.labels?.map(lbl => {
                      const color = NODE_THEMES[lbl]?.color || '#94A3B8';
                      return (
                        <span
                          key={lbl}
                          className="node-meta-pill"
                          style={{ backgroundColor: color + '22', color }}
                        >
                          {NODE_THEMES[lbl]?.label || lbl}
                        </span>
                      );
                    })}
                    <span className="node-meta-pill" style={{ backgroundColor: 'rgba(255,255,255,0.06)', color: 'var(--color-text-muted)' }}>
                      ID: {selectedNode.id}
                    </span>
                  </div>

                  <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: 12, color: 'var(--color-text)' }}>
                    {selectedNode.properties?.title || selectedNode.properties?.name || 'Không có tên hiển thị'}
                  </h3>

                  <div className="properties-list">
                    {Object.entries(selectedNode.properties || {}).map(([k, v]) => {
                      if (k === 'title' || k === 'name') return null; // Already shown
                      return (
                        <div key={k} className="property-item">
                          <span className="property-key">{k}</span>
                          <span className="property-val">{String(v)}</span>
                        </div>
                      );
                    })}
                  </div>

                  {/* Connected Relationships List */}
                  <div style={{ marginTop: '16px', borderTop: '1px solid var(--color-border)', paddingTop: '16px', marginBottom: '16px' }}>
                    <h4 style={{ fontSize: '11px', fontWeight: 600, color: 'var(--color-text-muted)', textTransform: 'uppercase', marginBottom: '8px' }}>
                      Các liên kết ({edges.filter(e => e.source === selectedNode.id || e.target === selectedNode.id).length})
                    </h4>
                    {edges.filter(e => e.source === selectedNode.id || e.target === selectedNode.id).length === 0 ? (
                      <span style={{ fontSize: '11px', color: 'var(--color-text-muted)', fontStyle: 'italic' }}>Không có liên kết nào hiển thị</span>
                    ) : (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', maxHeight: '180px', overflowY: 'auto', marginBottom: '12px' }}>
                        {edges.filter(e => e.source === selectedNode.id || e.target === selectedNode.id).map(edge => {
                          const isOutgoing = edge.source === selectedNode.id;
                          const neighborId = isOutgoing ? edge.target : edge.source;
                          const neighborNode = nodes.find(n => n.id === neighborId);
                          const neighborTitle = neighborNode ? (neighborNode.properties?.title || neighborNode.properties?.name || neighborId) : neighborId;
                          const neighborLabel = neighborNode ? (neighborNode.labels?.[0] || 'Node') : 'Node';
                          const theme = NODE_THEMES[neighborLabel] || NODE_THEMES.Default;
                          
                          return (
                            <div 
                              key={edge.id} 
                              onClick={() => neighborNode && setSelectedNode(neighborNode)}
                              style={{ 
                                display: 'flex', 
                                alignItems: 'center', 
                                justifyContent: 'space-between',
                                background: 'var(--color-surface-2)', 
                                padding: '6px 10px', 
                                borderRadius: 'var(--radius-sm)',
                                fontSize: '11px',
                                cursor: neighborNode ? 'pointer' : 'default',
                                transition: 'all var(--transition-fast)',
                                border: '1px solid transparent'
                              }}
                              onMouseEnter={(e) => { if (neighborNode) e.currentTarget.style.borderColor = 'var(--color-primary)'; }}
                              onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'transparent'; }}
                            >
                              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '70%' }}>
                                <span style={{ 
                                  display: 'inline-block', 
                                  width: '6px', 
                                  height: '6px', 
                                  borderRadius: '50%', 
                                  backgroundColor: theme.color ,
                                  flexShrink: 0
                                }} />
                                <span style={{ fontWeight: 500 }} title={neighborTitle}>{neighborTitle}</span>
                              </div>
                              <span style={{ 
                                fontSize: '9px', 
                                fontWeight: 700, 
                                color: isOutgoing ? 'var(--color-primary)' : 'var(--color-success)',
                                textTransform: 'uppercase'
                              }}>
                                {isOutgoing ? `→ ${edge.type}` : `← ${edge.type}`}
                              </span>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    <button className="btn btn-primary btn-sm" style={{ width: '100%', fontSize: 12 }} onClick={() => loadNeighbors(selectedNode)}>
                      Mở rộng các nút liên kết
                    </button>
                    <button className="btn btn-ghost btn-sm" style={{ width: '100%', fontSize: 11 }} onClick={() => setSelectedNode(null)}>
                      Bỏ chọn
                    </button>
                  </div>
                </>
              ) : (
                <div style={{ textAlign: 'center', color: 'var(--color-text-muted)', padding: '24px 0', fontSize: 'var(--font-size-sm)' }}>
                  <p style={{ fontStyle: 'italic' }}>Chưa chọn nút nào.</p>
                  <p style={{ fontSize: 11, marginTop: 6, opacity: 0.8 }}>
                    Click vào một nút trên đồ thị để xem chi tiết, hoặc click đúp để mở rộng các liên kết của nó.
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

/* ---- Confirm Delete Modal ---- */
function ConfirmDeleteModal({ isOpen, onClose, onConfirm, filename }) {
  if (!isOpen) return null;

  return (
    <div className="ms-modal-overlay" onClick={onClose}>
      <div className="ms-modal" style={{ width: 440 }} onClick={e => e.stopPropagation()}>
        <div className="ms-modal-header" style={{ borderBottom: 'none', paddingBottom: 0 }}>
          <h3>Xác nhận xóa tài liệu</h3>
          <button className="btn btn-ghost btn-icon btn-sm" onClick={onClose}><X size={18} /></button>
        </div>
        <div className="ms-modal-body" style={{ padding: '20px 24px' }}>
          <p style={{ marginBottom: 16, fontSize: '14px', lineHeight: 1.5 }}>
            Bạn có chắc chắn muốn xóa tài liệu <strong style={{ color: 'var(--color-primary)' }}>{filename}</strong> không?
          </p>
          <div style={{
            background: 'hsla(0, 72%, 55%, 0.08)',
            border: '1px solid hsla(0, 72%, 55%, 0.2)',
            borderRadius: 8,
            padding: '12px 16px',
            fontSize: '12px',
            color: 'var(--color-error)',
            lineHeight: 1.5,
            marginBottom: 20
          }}>
            <p style={{ fontWeight: 600, marginBottom: 4 }}>Thao tác này sẽ xóa vĩnh viễn:</p>
            <ul style={{ paddingLeft: 16, margin: 0 }}>
              <li>File vật lý lưu trữ trên server</li>
              <li>Toàn bộ index vector trong ChromaDB</li>
              <li>Toàn bộ các nodes và quan hệ trong Knowledge Graph</li>
            </ul>
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 12 }}>
            <button className="btn btn-ghost" onClick={onClose}>Hủy</button>
            <button className="btn btn-primary" style={{ backgroundColor: 'var(--color-error)', borderColor: 'var(--color-error)' }} onClick={onConfirm}>Xác nhận xóa</button>
          </div>
        </div>
      </div>
    </div>
  );
}
