import os
import argparse
from pathlib import Path
from dotenv import load_dotenv
from huggingface_hub import HfApi

def main():
    # Load .env file from the root directory
    project_root = Path(__file__).resolve().parent.parent
    load_dotenv(project_root / ".env")

    parser = argparse.ArgumentParser(description="Upload a local LoRA adapter folder to Hugging Face Hub (Private)")
    parser.add_argument(
        "--folder", 
        type=str, 
        required=True, 
        help="Đường dẫn đến thư mục LoRA adapter (ví dụ: ./legal_qwen35_lora hoặc checkpoint-1800)"
    )
    parser.add_argument(
        "--repo", 
        type=str, 
        required=True, 
        help="Tên repository trên HF Hub dưới dạng 'username/repo-name' (ví dụ: 'congl/legal_qwen35_lora')"
    )
    args = parser.parse_args()

    # Get token from environment
    hf_token = os.getenv("HF_TOKEN")
    if not hf_token:
        print("❌ LỖI: Không tìm thấy HF_TOKEN trong file .env hoặc biến môi trường!")
        print("Hãy kiểm tra lại file .env của bạn.")
        return

    folder_path = Path(args.folder)
    if not folder_path.exists() or not folder_path.is_dir():
        print(f"❌ LỖI: Thư mục không tồn tại: {args.folder}")
        return

    print(f"🔄 Đang khởi tạo kết nối với Hugging Face Hub...")
    api = HfApi(token=hf_token)

    # 1. Tạo repository private nếu chưa tồn tại
    try:
        print(f"📦 Đang kiểm tra/tạo repository private: '{args.repo}'...")
        api.create_repo(
            repo_id=args.repo,
            repo_type="model",
            private=True,
            exist_ok=True
        )
        print("✅ Đã xác nhận repository tồn tại (và là Private).")
    except Exception as e:
        print(f"❌ LỖI khi tạo repository: {e}")
        return

    # 2. Upload thư mục
    try:
        print(f"📤 Đang upload toàn bộ file trong thư mục '{args.folder}' lên Hugging Face Hub...")
        api.upload_folder(
            folder_path=str(folder_path),
            repo_id=args.repo,
            repo_type="model"
        )
        print("=" * 60)
        print(f"🎉 THÀNH CÔNG! LoRA adapter của bạn đã được upload lên Hugging Face.")
        print(f"🔗 Link repo: https://huggingface.co/{args.repo}")
        print("=" * 60)
    except Exception as e:
        print(f"❌ LỖI trong quá trình upload: {e}")

if __name__ == "__main__":
    main()
