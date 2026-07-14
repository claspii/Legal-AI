"""
Chia dataset distill_data.jsonl thành các tập train, validation và test.

Cách dùng:
  python split_dataset.py --input data_gen/distill_data.jsonl --train 0.8 --val 0.1 --test 0.1 --seed 42
"""

import argparse
import json
import random
from pathlib import Path
from loguru import logger

def main():
    parser = argparse.ArgumentParser(description="Split dataset into train, val, and test sets.")
    parser.add_argument("--input", default="data_gen/distill_data.jsonl", help="Đường dẫn file dataset đầu vào (JSONL)")
    parser.add_argument("--train", type=float, default=0.8, help="Tỷ lệ tập train (mặc định: 0.8)")
    parser.add_argument("--val", type=float, default=0.1, help="Tỷ lệ tập validation (mặc định: 0.1)")
    parser.add_argument("--test", type=float, default=0.1, help="Tỷ lệ tập test (mặc định: 0.1)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed để kết quả ổn định và tái bản được")
    parser.add_argument("--output-dir", default="data_gen", help="Thư mục lưu các tập dữ liệu sau khi chia")
    parser.add_argument("--prefix", default="", help="Prefix cho tên file đầu ra (ví dụ: 'advanced_')")
    args = parser.parse_args()

    # Kiểm tra tỷ lệ chia
    total_ratio = args.train + args.val + args.test
    if not (0.99 <= total_ratio <= 1.01):
        logger.error(f"Tổng tỷ lệ train ({args.train}) + val ({args.val}) + test ({args.test}) = {total_ratio:.2f} phải bằng 1.0!")
        return

    input_path = Path(args.input)
    if not input_path.exists():
        logger.error(f"Không tìm thấy file đầu vào: {input_path}")
        return

    logger.info(f"Đang đọc dữ liệu từ {input_path}...")
    records = []
    with open(input_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                logger.warning(f"Bỏ qua dòng {i+1} lỗi định dạng JSON: {e}")

    total_records = len(records)
    logger.info(f"Đọc thành công {total_records} bản ghi.")

    # Shuffle dữ liệu với seed cố định
    random.seed(args.seed)
    random.shuffle(records)

    # Tính toán số lượng bản ghi cho mỗi tập
    n_train = int(total_records * args.train)
    n_val = int(total_records * args.val)
    n_test = total_records - n_train - n_val

    # Đảm bảo phân chia chính xác các slice
    train_records = records[:n_train]
    val_records = records[n_train:n_train + n_val]
    test_records = records[n_train + n_val:]

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    splits = {
        "train": train_records,
        "val": val_records,
        "test": test_records
    }

    logger.info("=== Bắt đầu chia dataset ===")
    for name, dataset in splits.items():
        out_file = output_dir / f"{args.prefix}{name}.jsonl"
        logger.info(f"Đang ghi tập {name} ({len(dataset)} bản ghi, tỷ lệ {len(dataset)/total_records:.2%}) ra {out_file}...")
        with open(out_file, "w", encoding="utf-8") as f:
            for item in dataset:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
    
    logger.info("🎉 Chia dataset hoàn tất thành công!")

if __name__ == "__main__":
    main()
