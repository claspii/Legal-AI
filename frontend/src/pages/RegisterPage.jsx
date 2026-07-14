/**
 * Register Page component.
 */

import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuthStore } from '../stores/authStore';
import { Scale, User, Mail, Lock } from 'lucide-react';
import toast from 'react-hot-toast';
import '../styles/components/auth.css';

export default function RegisterPage() {
  const navigate = useNavigate();
  const { register, isLoading, error, clearError } = useAuthStore();
  const [email, setEmail] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();

    if (password !== confirmPassword) {
      toast.error('Mật khẩu xác nhận không khớp.');
      return;
    }

    try {
      await register(email, username, password);
      toast.success('Đăng ký thành công! Vui lòng đăng nhập.');
      navigate('/login');
    } catch {
      // Error in store
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
              <h1>Tạo tài khoản</h1>
              <p>Trợ lý Pháp luật Việt Nam</p>
            </div>

            {error && (
              <div className="auth-error" role="alert">
                {error}
              </div>
            )}

            <form className="auth-form" onSubmit={handleSubmit}>
              <div className="form-group">
                <label htmlFor="reg-email">Email</label>
                <div style={{ position: 'relative' }}>
                  <Mail size={16} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--color-text-muted)' }} />
                  <input id="reg-email" type="email" className="input" style={{ paddingLeft: 38 }} placeholder="email@example.com" value={email} onChange={e => { setEmail(e.target.value); clearError(); }} required autoFocus />
                </div>
              </div>

              <div className="form-group">
                <label htmlFor="reg-username">Tên người dùng</label>
                <div style={{ position: 'relative' }}>
                  <User size={16} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--color-text-muted)' }} />
                  <input id="reg-username" type="text" className="input" style={{ paddingLeft: 38 }} placeholder="nguyenvana" value={username} onChange={e => { setUsername(e.target.value); clearError(); }} required minLength={2} />
                </div>
              </div>

              <div className="form-group">
                <label htmlFor="reg-password">Mật khẩu</label>
                <div style={{ position: 'relative' }}>
                  <Lock size={16} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--color-text-muted)' }} />
                  <input id="reg-password" type="password" className="input" style={{ paddingLeft: 38 }} placeholder="Ít nhất 6 ký tự" value={password} onChange={e => setPassword(e.target.value)} required minLength={6} />
                </div>
              </div>

              <div className="form-group">
                <label htmlFor="reg-confirm">Xác nhận mật khẩu</label>
                <div style={{ position: 'relative' }}>
                  <Lock size={16} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--color-text-muted)' }} />
                  <input id="reg-confirm" type="password" className="input" style={{ paddingLeft: 38 }} placeholder="Nhập lại mật khẩu" value={confirmPassword} onChange={e => setConfirmPassword(e.target.value)} required minLength={6} />
                </div>
              </div>

              <button type="submit" className="btn btn-primary auth-submit" disabled={isLoading || !email || !username || !password || !confirmPassword}>
                {isLoading ? '⏳' : 'Đăng ký'}
              </button>
            </form>

            <div className="auth-footer">
              Đã có tài khoản?{' '}
              <Link to="/login">Đăng nhập</Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
