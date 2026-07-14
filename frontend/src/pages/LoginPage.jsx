/**
 * Login Page component.
 */

import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuthStore } from '../stores/authStore';
import { Scale, Eye, EyeOff, Mail, Lock } from 'lucide-react';
import '../styles/components/auth.css';

export default function LoginPage() {
  const navigate = useNavigate();
  const { login, isLoading, error, clearError } = useAuthStore();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);

  const [rememberMe, setRememberMe] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      await login(email, password, rememberMe);
      navigate('/home');
    } catch {
      // Error already set in store
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-container">
        <div className="auth-card">
          <div className="auth-card-inner">
            <div className="auth-logo">
              <div className="auth-logo-icon">
                <Scale size={28} color="white" />
              </div>
              <h1>Legal RAG</h1>
              <p>Trợ lý Pháp luật Việt Nam</p>
            </div>

            {error && (
              <div className="auth-error" role="alert">
                {error}
              </div>
            )}

            <form className="auth-form" onSubmit={handleSubmit}>
              <div className="form-group">
                <label htmlFor="login-email">Email</label>
                <div style={{ position: 'relative' }}>
                  <Mail
                    size={16}
                    style={{
                      position: 'absolute', left: 12, top: '50%',
                      transform: 'translateY(-50%)', color: 'var(--color-text-muted)',
                    }}
                  />
                  <input
                    id="login-email"
                    type="email"
                    className="input"
                    style={{ paddingLeft: 38 }}
                    placeholder="admin@legalrag.vn"
                    value={email}
                    onChange={(e) => { setEmail(e.target.value); clearError(); }}
                    required
                    autoFocus
                  />
                </div>
              </div>

              <div className="form-group">
                <label htmlFor="login-password">Mật khẩu</label>
                <div style={{ position: 'relative' }}>
                  <Lock
                    size={16}
                    style={{
                      position: 'absolute', left: 12, top: '50%',
                      transform: 'translateY(-50%)', color: 'var(--color-text-muted)',
                    }}
                  />
                  <input
                    id="login-password"
                    type={showPassword ? 'text' : 'password'}
                    className="input"
                    style={{ paddingLeft: 38, paddingRight: 38 }}
                    placeholder="••••••••"
                    value={password}
                    onChange={(e) => { setPassword(e.target.value); clearError(); }}
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    style={{
                      position: 'absolute', right: 8, top: '50%',
                      transform: 'translateY(-50%)', background: 'none',
                      border: 'none', cursor: 'pointer', color: 'var(--color-text-muted)',
                      padding: 4,
                    }}
                  >
                    {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>

              <div className="form-group remember-me-group" style={{ display: 'flex', alignItems: 'center', margin: '16px 0', gap: '8px' }}>
                <input
                  id="remember-me"
                  type="checkbox"
                  checked={rememberMe}
                  onChange={(e) => setRememberMe(e.target.checked)}
                  style={{ cursor: 'pointer', width: '16px', height: '16px', accentColor: 'var(--color-primary)' }}
                />
                <label htmlFor="remember-me" style={{ cursor: 'pointer', userSelect: 'none', fontSize: '14px', color: 'var(--color-text-secondary)', marginBottom: 0 }}>
                  Nhớ đăng nhập
                </label>
              </div>

              <button
                type="submit"
                className="btn btn-primary auth-submit"
                disabled={isLoading || !email || !password}
              >
                {isLoading ? (
                  <span className="animate-spin" style={{ display: 'inline-block' }}>⏳</span>
                ) : (
                  'Đăng nhập'
                )}
              </button>
            </form>

            <div className="auth-footer">
              Chưa có tài khoản?{' '}
              <Link to="/register">Đăng ký ngay</Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
