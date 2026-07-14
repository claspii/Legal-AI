import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../stores/authStore';
import { useTheme } from '../hooks/useTheme';
import { Scale, ArrowRight, Share2, Cpu, Key, Database, Sun, Moon } from 'lucide-react';
import './LandingPage.css';

export default function LandingPage() {
  const navigate = useNavigate();
  const { isAuthenticated } = useAuthStore();
  const [theme, setTheme] = useTheme();

  const handleStart = () => {
    if (isAuthenticated) {
      navigate('/home');
    } else {
      navigate('/login');
    }
  };

  return (
    <div className="landing-page">
      {/* Background decorations */}
      <div className="ambient-glow glow-1"></div>
      <div className="ambient-glow glow-2"></div>
      <div className="noise-overlay"></div>

      <div className="landing-container">
        {/* Header */}
        <header className="landing-header">
          <div className="landing-logo">
            <div className="logo-icon">
              <Scale size={20} color="white" />
            </div>
            <span className="logo-text">Scale Legal RAG</span>
          </div>
          <div className="header-actions">
            <button 
              className="theme-toggle-icon-btn" 
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
              title={theme === 'dark' ? 'Chuyển sang giao diện Sáng' : 'Chuyển sang giao diện Tối'}
            >
              {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
            </button>
            <button className="landing-nav-btn" onClick={handleStart}>
              {isAuthenticated ? 'Vào Dashboard' : 'Đăng nhập'}
            </button>
          </div>
        </header>

        {/* Hero Section - Split Screen layout */}
        <section className="landing-hero-split">
          <div className="hero-content-left animate-fade-in">
            <div className="hero-badge-pill">Phiên Bản Lai Ghép v2.5</div>
            <h1 className="hero-title">
              Trợ lý Pháp Luật AI <span>Đột Phá Kỷ Nguyên</span>
            </h1>
            <p className="hero-subtitle">
              Sự kết hợp hoàn hảo giữa Mô hình Ngôn ngữ Lớn chuyên biệt, cơ sở dữ liệu đồ thị tri thức Neo4j và tìm kiếm vector ngữ nghĩa ChromaDB để mang lại câu trả lời pháp lý chính xác 100%, có nguồn tham chiếu rõ ràng.
            </p>
            <div className="hero-ctas">
              <button className="cta-primary-pill" onClick={handleStart}>
                <span>Bắt đầu miễn phí</span>
                <span className="arrow-circle">
                  <ArrowRight size={16} />
                </span>
              </button>
              <button className="cta-secondary-pill" onClick={() => navigate('/login')}>
                Trải nghiệm Chatbot
              </button>
            </div>
          </div>

          {/* Faux OS Mockup Preview Card */}
          <div className="hero-preview-right animate-slide-in-right">
            <div className="macbook-frame-outer">
              <div className="macbook-frame-inner">
                {/* macOS control dots */}
                <div className="window-header">
                  <div className="window-dots">
                    <span className="dot dot-close"></span>
                    <span className="dot dot-minimize"></span>
                    <span className="dot dot-expand"></span>
                  </div>
                  <div className="window-title">Scale Legal RAG — Interactive Workspace</div>
                </div>
                {/* Simulated Chat App Interface */}
                <div className="simulated-chat-app">
                  <div className="sim-sidebar">
                    <div className="sim-new-chat">New session</div>
                    <div className="sim-nav-item active">Điều 8 Luật Hôn nhân...</div>
                    <div className="sim-nav-item">Tội phạm kinh tế...</div>
                    <div className="sim-nav-item">Hợp đồng lao động...</div>
                  </div>
                  <div className="sim-chat-area">
                    <div className="sim-chat-header">
                      <Scale size={12} color="var(--color-primary)" />
                      <span>Hỏi đáp Pháp lý</span>
                    </div>
                    <div className="sim-messages">
                      <div className="sim-msg user">
                        <span className="sim-avatar">U</span>
                        <div className="sim-bubble">Thế còn độ tuổi kết hôn của nam giới thì sao?</div>
                      </div>
                      <div className="sim-msg bot">
                        <span className="sim-avatar bot-av"><Scale size={10} color="white" /></span>
                        <div className="sim-bubble">
                          <div className="sim-think">
                            <span>Thinking Process</span>
                            <p>Truy xuất Điều 8 Luật Hôn nhân & Gia đình 2014...</p>
                          </div>
                          <p>Theo quy định tại điểm a khoản 1 Điều 8 Luật Hôn nhân và gia đình năm 2014, một trong các điều kiện kết hôn là: Nam từ đủ 20 tuổi trở lên.</p>
                          <div className="sim-source">Nguồn: Luật Hôn nhân và gia đình 2014 | Điều 8</div>
                        </div>
                      </div>
                    </div>
                    <div className="sim-input-bar">
                      <span>Nhập câu hỏi pháp lý của bạn...</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* Features Section - Asymmetrical Bento Grid */}
        <section className="landing-features">
          <div className="section-header">
            <div className="eyebrow-label">Tính Năng Tối Tân</div>
            <h2 className="section-title">Hệ Thống Kiến Trúc RAG Lai Ghép</h2>
            <p className="section-subtitle">
              Sản phẩm được tối ưu hóa sâu sắc cho luật pháp Việt Nam với các cấu phần công nghệ hàng đầu thế giới.
            </p>
          </div>

          <div className="features-bento-grid">
            <div className="bento-card col-span-2">
              <div className="bento-card-inner">
                <div className="feature-icon-wrapper">
                  <Share2 size={22} />
                </div>
                <h3>Graph RAG (Đồ thị Tri thức Neo4j)</h3>
                <p>
                  Phân tích cấu trúc phân cấp phức tạp từ Luật, Nghị định đến Thông tư. Thiết lập mối quan hệ ngữ nghĩa chặt chẽ giữa các điều khoản pháp lý để trả lời chính xác, giải quyết triệt để hiện tượng ảo tưởng thông tin của AI.
                </p>
              </div>
            </div>

            <div className="bento-card">
              <div className="bento-card-inner">
                <div className="feature-icon-wrapper">
                  <Database size={22} />
                </div>
                <h3>Cơ sở dữ liệu Vector ChromaDB</h3>
                <p>
                  Tìm kiếm ngữ nghĩa dày đặc với các mô hình nhúng tiếng Việt tiên tiến, truy xuất nhanh các phân mảnh tài liệu có độ tương đồng cao chỉ trong mili giây.
                </p>
              </div>
            </div>

            <div className="bento-card">
              <div className="bento-card-inner">
                <div className="feature-icon-wrapper">
                  <Cpu size={22} />
                </div>
                <h3>Hiển thị luồng suy nghĩ</h3>
                <p>
                  Trực quan hóa quy trình suy luận (thinking reasoning stream) chi tiết từng bước, giúp người dùng nắm bắt lập luận logic đằng sau mỗi nhận định pháp lý.
                </p>
              </div>
            </div>

            <div className="bento-card col-span-2">
              <div className="bento-card-inner">
                <div className="feature-icon-wrapper">
                  <Key size={22} />
                </div>
                <h3>Cổng API & Tích hợp dành cho Nhà Phát Triển</h3>
                <p>
                  Cung cấp các endpoints chuẩn hóa, tài liệu phong phú và khả năng quản lý API key bảo mật cấp doanh nghiệp. Tích hợp nhanh trợ lý RAG vào bất kỳ nền tảng quản trị doanh nghiệp, tòa án hoặc dịch vụ tư vấn pháp lý.
                </p>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
