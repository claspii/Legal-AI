"""
Script phân tích trainer_state.json và vẽ các đồ thị trực quan hóa quá trình huấn luyện
sử dụng style thiết kế công nghệ cao cấp (Dark Mode Slate/Neon).
"""

import json
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np

# Đường dẫn file
BASE_DIR = Path(__file__).parent.parent
TRAINER_STATE_PATH = BASE_DIR / "trainer_state.json"
OUTPUT_DIR = BASE_DIR / "docs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
IMG_OUTPUT_PATH = OUTPUT_DIR / "training_progress.png"

# Đường dẫn copy sang Artifacts directory (để render lên chat UI)
ARTIFACT_DIR = Path(r"C:\Users\congl\.gemini\antigravity-ide\brain\58435586-d6ca-4e83-bc8b-60b5ba9a7dec")
ARTIFACT_IMG_PATH = ARTIFACT_DIR / "training_progress.png"

def load_trainer_state(file_path: Path) -> dict:
    if not file_path.exists():
        raise FileNotFoundError(f"Không tìm thấy file: {file_path}")
    with file_path.open("r", encoding="utf-8") as f:
        return json.load(f)

def parse_history(state: dict):
    history = state.get("log_history", [])
    
    # Dữ liệu huấn luyện (Training steps)
    train_steps = []
    train_loss = []
    learning_rates = []
    grad_norms = []
    epochs = []
    
    # Dữ liệu đánh giá (Evaluation steps)
    eval_steps = []
    eval_loss = []
    eval_runtime = []
    eval_samples_per_sec = []
    eval_epochs = []
    
    for log in history:
        step = log.get("step")
        epoch = log.get("epoch")
        
        # Nhận diện dòng log training (thường có loss & learning_rate)
        if "loss" in log:
            train_steps.append(step)
            train_loss.append(log["loss"])
            epochs.append(epoch)
            if "learning_rate" in log:
                learning_rates.append(log["learning_rate"])
            if "grad_norm" in log:
                grad_norms.append(log["grad_norm"])
                
        # Nhận diện dòng log evaluation (có eval_loss)
        elif "eval_loss" in log:
            eval_steps.append(step)
            eval_loss.append(log["eval_loss"])
            eval_epochs.append(epoch)
            if "eval_runtime" in log:
                eval_runtime.append(log["eval_runtime"])
            if "eval_samples_per_second" in log:
                eval_samples_per_sec.append(log["eval_samples_per_second"])
                
    return {
        "train": {
            "step": np.array(train_steps),
            "loss": np.array(train_loss),
            "lr": np.array(learning_rates),
            "grad_norm": np.array(grad_norms),
            "epoch": np.array(epochs)
        },
        "eval": {
            "step": np.array(eval_steps),
            "loss": np.array(eval_loss),
            "runtime": np.array(eval_runtime),
            "samples_per_sec": np.array(eval_samples_per_sec),
            "epoch": np.array(eval_epochs)
        },
        "best_step": state.get("best_global_step"),
        "best_metric": state.get("best_metric")
    }

def main():
    print("Đang đọc và phân tích trainer_state.json...")
    try:
        state = load_trainer_state(TRAINER_STATE_PATH)
        data = parse_history(state)
    except Exception as e:
        print(f"Lỗi đọc file: {e}")
        return

    # Thiết lập cấu hình Style Đồ thị - Premium Dark Mode Theme
    plt.rcParams.update({
        "figure.facecolor": "#0f172a",      # Nền ngoài Slate 900
        "axes.facecolor": "#1e293b",        # Nền trong Slate 800
        "axes.edgecolor": "#475569",        # Đường viền Slate 600
        "axes.grid": True,
        "grid.color": "#334155",            # Lưới Slate 700
        "grid.linestyle": ":",
        "text.color": "#f8fafc",            # Màu chữ sáng Slate 50
        "axes.labelcolor": "#cbd5e1",       # Màu nhãn nhạt Slate 300
        "xtick.color": "#94a3b8",           # Màu trục X Slate 400
        "ytick.color": "#94a3b8",           # Màu trục Y Slate 400
        "font.family": "sans-serif",
        "font.size": 10
    })

    fig, axs = plt.subplots(2, 2, figsize=(16, 11), dpi=150)
    fig.suptitle("⚡ BÁO CÁO TIẾN TRÌNH HUẤN LUYỆN LORA - QWEN 3.5 SFT ⚡", 
                 fontsize=18, fontweight="bold", color="#38bdf8", y=0.96)

    t_data = data["train"]
    e_data = data["eval"]
    best_step = data["best_step"]
    best_loss = data["best_metric"]

    # -------------------------------------------------------------------------
    # Đồ thị 1: Biểu đồ Loss (Training vs Evaluation)
    # -------------------------------------------------------------------------
    ax1 = axs[0, 0]
    ax1.set_title("📉 Đồ thị So sánh Loss Curves", fontsize=12, fontweight="bold", color="#38bdf8", pad=10)
    
    # Vẽ đường training loss mịn (đường trung bình trượt để dễ nhìn)
    if len(t_data["loss"]) > 0:
        ax1.plot(t_data["step"], t_data["loss"], color="#0ea5e9", alpha=0.3, label="Train Loss (Raw)")
        # Trơn hóa đường loss bằng sliding window
        window = min(15, len(t_data["loss"]))
        if window > 1:
            smoothed = np.convolve(t_data["loss"], np.ones(window)/window, mode='valid')
            smooth_steps = t_data["step"][window-1:]
            ax1.plot(smooth_steps, smoothed, color="#06b6d4", linewidth=2.5, label="Train Loss (Smoothed)")
            
    # Vẽ eval loss (đường đứt nét + các markers tròn nổi bật)
    if len(e_data["loss"]) > 0:
        ax1.plot(e_data["step"], e_data["loss"], color="#f43f5e", linestyle="--", marker="o", 
                 linewidth=2, markersize=6, label="Validation Loss", zorder=5)
        
    # Đánh dấu checkpoint tốt nhất
    if best_step is not None and best_step in e_data["step"]:
        ax1.axvline(x=best_step, color="#fbbf24", linestyle=":", linewidth=2, 
                    label=f"Best Checkpoint (Step {best_step})")
        ax1.scatter([best_step], [best_loss], color="#fbbf24", s=120, edgecolors="#0f172a", 
                    linewidths=2, zorder=6, label=f"Min Val Loss: {best_loss:.4f}")
        
    ax1.set_xlabel("Steps (Số bước lặp)", fontsize=9)
    ax1.set_ylabel("Loss (Giá trị mất mát)", fontsize=9)
    ax1.legend(facecolor="#1e293b", edgecolor="#475569", loc="upper right")
    
    # -------------------------------------------------------------------------
    # Đồ thị 2: Biểu đồ Learning Rate
    # -------------------------------------------------------------------------
    ax2 = axs[0, 1]
    ax2.set_title("📈 Biểu đồ Lịch trình Học tập (Learning Rate Schedule)", fontsize=12, fontweight="bold", color="#38bdf8", pad=10)
    
    if len(t_data["lr"]) > 0:
        ax2.plot(t_data["step"], t_data["lr"], color="#10b981", linewidth=2.5, label="Learning Rate")
        # Điểm kết thúc Warmup
        warmup_end_idx = np.argmax(t_data["lr"])
        warmup_end_step = t_data["step"][warmup_end_idx]
        warmup_end_lr = t_data["lr"][warmup_end_idx]
        ax2.scatter([warmup_end_step], [warmup_end_lr], color="#a7f3d0", s=60, zorder=5,
                    label=f"Peak LR: {warmup_end_lr:.1e}")
        
    ax2.set_xlabel("Steps (Số bước lặp)", fontsize=9)
    ax2.set_ylabel("Learning Rate", fontsize=9)
    ax2.ticklabel_format(axis='y', style='sci', scilimits=(0,0))
    ax2.legend(facecolor="#1e293b", edgecolor="#475569", loc="upper right")

    # -------------------------------------------------------------------------
    # Đồ thị 3: Gradient Norm (Độ ổn định huấn luyện)
    # -------------------------------------------------------------------------
    ax3 = axs[1, 0]
    ax3.set_title("🛡️ Đồ thị Độ ổn định Gradient (Grad Norm)", fontsize=12, fontweight="bold", color="#38bdf8", pad=10)
    
    if len(t_data["grad_norm"]) > 0:
        ax3.plot(t_data["step"], t_data["grad_norm"], color="#a78bfa", alpha=0.4, label="Grad Norm (Raw)")
        window = min(20, len(t_data["grad_norm"]))
        if window > 1:
            smoothed_grad = np.convolve(t_data["grad_norm"], np.ones(window)/window, mode='valid')
            smooth_steps_g = t_data["step"][window-1:]
            ax3.plot(smooth_steps_g, smoothed_grad, color="#8b5cf6", linewidth=2.0, label="Grad Norm (Smoothed)")
            
    ax3.set_xlabel("Steps (Số bước lặp)", fontsize=9)
    ax3.set_ylabel("Gradient Norm", fontsize=9)
    ax3.legend(facecolor="#1e293b", edgecolor="#475569", loc="upper right")

    # -------------------------------------------------------------------------
    # Đồ thị 4: Đánh giá Hiệu năng Validation (Runtime & Throughput)
    # -------------------------------------------------------------------------
    ax4 = axs[1, 1]
    ax4.set_title("⚡ Hiệu năng Đánh giá (Validation Performance)", fontsize=12, fontweight="bold", color="#38bdf8", pad=10)
    
    if len(e_data["step"]) > 0:
        # Sử dụng 2 trục Y
        color1 = "#fb7185"
        ax4.set_xlabel("Steps (Số bước lặp)", fontsize=9)
        ax4.set_ylabel("Eval Runtime (giây)", color=color1, fontsize=9)
        ln1 = ax4.plot(e_data["step"], e_data["runtime"], color=color1, linestyle="-", marker="s", 
                 linewidth=1.5, label="Eval Runtime (s)")
        ax4.tick_params(axis='y', labelcolor=color1)
        
        ax4_2 = ax4.twinx()
        color2 = "#34d399"
        ax4_2.set_ylabel("Tốc độ xử lý (samples/s)", color=color2, fontsize=9)
        ln2 = ax4_2.plot(e_data["step"], e_data["samples_per_sec"], color=color2, linestyle="-", marker="^",
                 linewidth=1.5, label="Samples/sec")
        ax4_2.tick_params(axis='y', labelcolor=color2)
        ax4_2.grid(False) # Tắt lưới trục Y thứ 2 tránh rối mắt
        
        # Gộp legend của cả 2 trục
        lns = ln1 + ln2
        labs = [l.get_label() for l in lns]
        ax4.legend(lns, labs, facecolor="#1e293b", edgecolor="#475569", loc="upper left")

    plt.tight_layout(rect=[0, 0, 1, 0.94])
    
    # Lưu đồ thị cục bộ
    fig.savefig(str(IMG_OUTPUT_PATH), facecolor=fig.get_facecolor(), edgecolor='none')
    print(f"Đã lưu đồ thị thành công tại: {IMG_OUTPUT_PATH}")
    
    # Copy sang thư mục Artifacts của chat UI để hiển thị trực tiếp
    try:
        import shutil
        shutil.copy2(IMG_OUTPUT_PATH, ARTIFACT_IMG_PATH)
        print(f"Đã copy đồ thị sang thư mục Artifacts: {ARTIFACT_IMG_PATH}")
    except Exception as e:
        print(f"Không thể copy sang Artifacts: {e}")

if __name__ == "__main__":
    main()
