"""
Script đánh giá hiệu năng (evaluation) mô hình trên tập dữ liệu test.
Chạy so sánh 3 mô hình (Base Pretrained, Custom Trained, Gemini 2.5 Flash)
và được chấm điểm tự động bằng Gemini 3.5 Flash làm giám khảo (Judge).
Kết quả và điểm số chi tiết được ghi ra file Excel (.xlsx).

Cách chạy:
  python training/evaluate_data.py --input data_gen/advanced_test.jsonl --output data_gen/evaluation_results.xlsx --limit 10
"""

import os
import sys
import json
import time
import re
import random
import argparse
import requests
import concurrent.futures
from pathlib import Path
from loguru import logger

# Add project root to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from src import config

# Đảm bảo cài đặt các thư viện cần thiết cho ghi file Excel
try:
    import pandas as pd
except ImportError:
    logger.error("Thiếu thư viện pandas hoặc openpyxl. Vui lòng chạy lệnh: pip install pandas openpyxl")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Judge Schema & Prompt
# ---------------------------------------------------------------------------
JUDGE_PROMPT = """Bạn là một giám khảo chấm điểm câu trả lời pháp luật khách quan và nghiêm ngặt tại Việt Nam.
Nhiệm vụ của bạn là đánh giá câu trả lời của một mô hình AI so với "Câu trả lời chuẩn" (Gold Standard) dựa trên Tình huống và Tài liệu tham khảo (RAG Context) được cung cấp.

TÌNH HUỐNG VÀ TÀI LIỆU THAM KHẢO:
{context}

CÂU HỎI:
{question}

CÂU TRẢ LỜI CHUẨN (Gold Standard):
{gold_answer}

CÂU TRẢ LỜI CỦA MODEL CẦN ĐÁNH GIÁ:
{model_answer}

Quy tắc chấm điểm (Thang điểm 10):
1. Tính chính xác pháp lý (Tối đa 4.0 điểm):
   - Câu trả lời có đúng về mặt pháp lý không? Có áp dụng đúng các điều luật trong Tài liệu tham khảo không?
   - Có bị rò rỉ hoặc tự ý sử dụng kiến thức luật ngoài RAG không? (Bị trừ điểm rất nặng nếu đưa vào các điều luật, quy định hay kiến thức luật không có trong RAG Context).
2. Độ đầy đủ và chi tiết (Tối đa 3.0 điểm):
   - Có trả lời đầy đủ các câu hỏi phụ phát sinh không?
   - Có phân tích chi tiết lỗi, trách nhiệm pháp lý của các bên liên quan không?
3. Tính logic và lập luận (Tối đa 3.0 điểm):
   - Quá trình suy luận và lập luận từng bước có chặt chẽ, rõ ràng và mạch lạc không?

Hãy chấm điểm và trả về kết quả dưới dạng JSON có cấu trúc sau:
{{
  "accuracy_score": <điểm_số_thực_từ_0.0_đến_4.0>,
  "completeness_score": <điểm_số_thực_từ_0.0_đến_3.0>,
  "logic_score": <điểm_số_thực_từ_0.0_đến_3.0>,
  "total_score": <tổng_điểm_thực_từ_0.0_đến_10.0 - bằng tổng của 3 điểm trên>,
  "feedback": "<nhận_xét_ngắn_gọn_bằng_tiếng_Việt_về_ưu_và_nhược_điểm_của_câu_trả_lời>"
}}
"""

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "accuracy_score": {"type": "number"},
        "completeness_score": {"type": "number"},
        "logic_score": {"type": "number"},
        "total_score": {"type": "number"},
        "feedback": {"type": "string"},
    },
    "required": ["accuracy_score", "completeness_score", "logic_score", "total_score", "feedback"]
}


# ---------------------------------------------------------------------------
# API clients & Inference Functions
# ---------------------------------------------------------------------------
def _gemini_client():
    from google import genai
    from google.genai.types import HttpOptions

    # Cấu hình timeout mặc định 300 giây (300000 ms) để tránh ngắt kết nối giữa chừng
    timeout_ms = 300000

    if config.GEMINI_USE_VERTEXAI:
        return genai.Client(http_options=HttpOptions(api_version="v1", timeout=timeout_ms))
    return genai.Client(
        api_key=config.GOOGLE_API_KEY,
        http_options=HttpOptions(api_version="v1", timeout=timeout_ms),
    )


def is_retryable_exception(e: Exception) -> bool:
    err_str = str(e).lower()
    return any(x in err_str for x in [
        "429", "resource_exhausted", "rate limit", "rate_limit", "quota",
        "503", "service unavailable", "500", "internal error", 
        "timeout", "connection"
    ])


def clean_illegal_chars(val):
    if not isinstance(val, str):
        return val
    # Regex loại bỏ các ký tự điều khiển không hợp lệ trong XML/Excel (ASCII 0-31 loại trừ tab, newline, carriage return)
    illegal_chars_re = re.compile(r"[\000-\010]|[\013-\014]|[\016-\037]")
    return illegal_chars_re.sub("", val)


def clean_df(df):
    if hasattr(df, "map"):
        return df.map(clean_illegal_chars)
    return df.applymap(clean_illegal_chars)


def call_openai_compatible(api_url, model_name, system_prompt, user_content, temperature=0.3, max_tokens=8192):
    url = api_url
    if not url.endswith("/chat/completions"):
        if url.endswith("/v1") or url.endswith("/v1/"):
            url = url.rstrip("/") + "/chat/completions"
        elif "/v1/chat/completions" not in url:
            url = url.rstrip("/") + "/v1/chat/completions"
            
    headers = {
        "Content-Type": "application/json"
    }
    
    data = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": True}
    }
    
    resp = requests.post(url, json=data, headers=headers, timeout=180)
    resp.raise_for_status()
    resp_json = resp.json()
    
    choice = resp_json["choices"][0]
    message = choice["message"]
    
    reasoning = message.get("reasoning_content", "") or ""
    content = message.get("content", "") or ""
    
    # Parse thẻ <think> trong trường hợp endpoint trả về think trực tiếp trong content
    if not reasoning:
        if "<think>" in content:
            if "</think>" in content:
                parts = content.split("</think>", 1)
                reasoning = parts[0].replace("<think>", "").strip()
                content = parts[1].strip()
            else:
                parts = content.split("<think>", 1)
                content = parts[0].strip()
                reasoning = parts[1].strip()
                
    return reasoning.strip(), content.strip()


def call_openai_compatible_with_retry(api_url, model_name, system_prompt, user_content, temperature=0.3, max_tokens=2048, max_retries=5):
    for attempt in range(1, max_retries + 1):
        try:
            return call_openai_compatible(api_url, model_name, system_prompt, user_content, temperature, max_tokens)
        except Exception as e:
            if attempt < max_retries and is_retryable_exception(e):
                err_str = str(e).lower()
                if any(x in err_str for x in ["429", "resource_exhausted", "rate limit", "rate_limit", "quota"]):
                    delay = 30.0 + random.uniform(2.0, 5.0)
                    logger.warning(f"Chạm giới hạn Rate Limit (429) của {model_name}. Nghỉ {delay:.1f}s trước khi thử lại...")
                else:
                    delay = 2.0 * attempt + random.uniform(0.1, 0.9)
                    logger.warning(f"Lỗi gọi {model_name} (Thử lại {attempt}/{max_retries}): {e}. Nghỉ {delay:.1f}s...")
                time.sleep(delay)
                continue
            raise e


def call_gemini_2_5_flash(client, system_prompt, user_content, temperature=0.3, max_tokens=8192):
    from google.genai import types
    
    prompt = f"{system_prompt}\n\n{user_content}\n\n--- Trả lời ---"
    
    resp = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(
                include_thoughts=True,
                thinking_budget=8192
            ),
            temperature=temperature,
            max_output_tokens=max_tokens,
        ),
    )
    
    reasoning = ""
    answer = ""
    
    if resp.candidates:
        candidate = resp.candidates[0]
        if candidate.content and candidate.content.parts:
            for part in candidate.content.parts:
                is_thought = getattr(part, 'thought', False)
                text = getattr(part, 'text', '') or ''
                if text:
                    if is_thought:
                        reasoning += text
                    else:
                        answer += text
                        
    return reasoning.strip(), answer.strip()


def call_gemini_2_5_flash_with_retry(client, system_prompt, user_content, temperature=0.3, max_tokens=2048, max_retries=5):
    for attempt in range(1, max_retries + 1):
        try:
            return call_gemini_2_5_flash(client, system_prompt, user_content, temperature, max_tokens)
        except Exception as e:
            if attempt < max_retries and is_retryable_exception(e):
                err_str = str(e).lower()
                if any(x in err_str for x in ["429", "resource_exhausted", "rate limit", "rate_limit", "quota"]):
                    delay = 30.0 + random.uniform(2.0, 5.0)
                    logger.warning(f"Chạm giới hạn Rate Limit (429) của Gemini 2.5. Nghỉ {delay:.1f}s trước khi thử lại...")
                else:
                    delay = 2.0 * attempt + random.uniform(0.1, 0.9)
                    logger.warning(f"Lỗi gọi Gemini 2.5 (Thử lại {attempt}/{max_retries}): {e}. Nghỉ {delay:.1f}s...")
                time.sleep(delay)
                continue
            raise e


def call_gemini_judge(client, context, question, gold_answer, model_answer, judge_model="gemini-3.5-flash"):
    from google.genai import types
    
    prompt = JUDGE_PROMPT.format(
        context=context,
        question=question,
        gold_answer=gold_answer,
        model_answer=model_answer
    )
    
    resp = client.models.generate_content(
        model=judge_model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=JUDGE_SCHEMA,
            temperature=0.1,
            max_output_tokens=16384,
        ),
    )
    
    try:
        text = resp.text or ""
        # Trích xuất JSON từ khối mã ```json ... ``` nếu model có trả về markdown
        match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            text = match.group(1)
            
        try:
            data = json.loads(text.strip() or "{}")
        except Exception as json_err:
            logger.warning(f"Lỗi phân tích JSON trực tiếp ({json_err}). Tiến hành trích xuất bằng regex...")
            data = {}
            for key in ["accuracy_score", "completeness_score", "logic_score", "total_score"]:
                pattern = rf'"{key}"\s*:\s*([0-9.]+)'
                m = re.search(pattern, text, re.IGNORECASE)
                if not m:
                    pattern = rf'{key}\s*:\s*([0-9.]+)'
                    m = re.search(pattern, text, re.IGNORECASE)
                if m:
                    try:
                        data[key] = float(m.group(1))
                    except ValueError:
                        pass
            
            # Trích xuất feedback
            fb_pattern = r'"feedback"\s*:\s*"(.*?)"'
            m_fb = re.search(fb_pattern, text, re.DOTALL | re.IGNORECASE)
            if not m_fb:
                fb_pattern = r'feedback\s*:\s*"(.*?)"'
                m_fb = re.search(fb_pattern, text, re.DOTALL | re.IGNORECASE)
            if not m_fb:
                fb_pattern = r'"feedback"\s*:\s*\'(.*?)\''
                m_fb = re.search(fb_pattern, text, re.DOTALL | re.IGNORECASE)
            if m_fb:
                data["feedback"] = m_fb.group(1).strip()
            else:
                # Tìm phần chữ sau feedback:
                fb_pattern = r'"feedback"\s*:\s*(.+)'
                m_fb = re.search(fb_pattern, text, re.IGNORECASE)
                if m_fb:
                    data["feedback"] = m_fb.group(1).strip().strip(',').strip('}').strip('"').strip("'")
                else:
                    data["feedback"] = f"Trích xuất bằng regex (JSON gốc lỗi). Phản hồi gốc: {text[:250]}"
        
        # Đảm bảo các trường điểm số tồn tại và có kiểu dữ liệu phù hợp
        required_keys = {
            "accuracy_score": 0.0,
            "completeness_score": 0.0,
            "logic_score": 0.0,
            "total_score": 0.0,
            "feedback": "Không có nhận xét."
        }
        
        for k, default_val in required_keys.items():
            if k not in data:
                # Thử tìm các biến thể viết hoa/thường/dấu gạch dưới
                found = False
                for dict_k in list(data.keys()):
                    if dict_k.lower().replace("_", "") == k.lower().replace("_", ""):
                        data[k] = data[dict_k]
                        found = True
                        break
                if not found:
                    data[k] = default_val
            
            # Ép kiểu điểm số về float
            if k != "feedback":
                try:
                    data[k] = float(data[k])
                except (ValueError, TypeError):
                    data[k] = 0.0
                    
        return data
    except Exception as e:
        logger.error(f"Lỗi phân tích JSON kết quả giám khảo: {e}. Text: {resp.text}")
        return {
            "accuracy_score": 0.0,
            "completeness_score": 0.0,
            "logic_score": 0.0,
            "total_score": 0.0,
            "feedback": f"Lỗi phân tích JSON (ngoại lệ lớn): {e}. Raw response: {resp.text}"
        }


def call_gemini_judge_with_retry(client, context, question, gold_answer, model_answer, judge_model="gemini-3.5-flash", max_retries=5):
    for attempt in range(1, max_retries + 1):
        try:
            return call_gemini_judge(client, context, question, gold_answer, model_answer, judge_model=judge_model)
        except Exception as e:
            if attempt < max_retries and is_retryable_exception(e):
                err_str = str(e).lower()
                if any(x in err_str for x in ["429", "resource_exhausted", "rate limit", "rate_limit", "quota"]):
                    delay = 30.0 + random.uniform(2.0, 5.0)
                    logger.warning(f"Chạm giới hạn Rate Limit (429) của {judge_model} làm giám khảo. Nghỉ {delay:.1f}s trước khi thử lại...")
                else:
                    delay = 2.0 * attempt + random.uniform(0.1, 0.9)
                    logger.warning(f"Lỗi gọi {judge_model} làm giám khảo (Thử lại {attempt}/{max_retries}): {e}. Nghỉ {delay:.1f}s...")
                time.sleep(delay)
                continue
            raise e


# ---------------------------------------------------------------------------
# Evaluation pipeline
# ---------------------------------------------------------------------------
def evaluate_sample(client, sample, base_url, base_name, custom_url, custom_name, temperature, max_tokens, 
                    eval_base=True, eval_custom=True, eval_gemini=True, judge_model="gemini-3.5-flash"):
    question = sample["instruction"]
    context = sample["input"]
    gold_answer = sample["output"]
    
    results = {}
    
    # Định nghĩa các task xử lý song song cho các model cần đánh giá
    def run_base():
        if not eval_base:
            return "base", None, None, None
        try:
            r, a = call_openai_compatible_with_retry(
                base_url, base_name, config.SYSTEM_PROMPT, 
                f"{context}\n\nCâu hỏi: {question}", temperature, max_tokens
            )
            return "base", r, a, None
        except Exception as e:
            logger.error(f"Lỗi mô hình Base: {e}")
            return "base", "", "", str(e)
            
    def run_custom():
        if not eval_custom:
            return "custom", None, None, None
        try:
            r, a = call_openai_compatible_with_retry(
                custom_url, custom_name, config.SYSTEM_PROMPT, 
                f"{context}\n\nCâu hỏi: {question}", temperature, max_tokens
            )
            return "custom", r, a, None
        except Exception as e:
            logger.error(f"Lỗi mô hình Custom: {e}")
            return "custom", "", "", str(e)
            
    def run_gemini():
        if not eval_gemini:
            return "gemini_2.5", None, None, None
        try:
            r, a = call_gemini_2_5_flash_with_retry(
                client, config.SYSTEM_PROMPT, 
                f"{context}\n\n--- Câu hỏi ---\n{question}", temperature, max_tokens
            )
            return "gemini_2.5", r, a, None
        except Exception as e:
            logger.error(f"Lỗi mô hình Gemini 2.5: {e}")
            return "gemini_2.5", "", "", str(e)
            
    # Chạy đồng thời các model cần chạy trên ThreadPoolExecutor
    workers_needed = sum([eval_base, eval_custom, eval_gemini])
    if workers_needed > 0:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers_needed) as executor:
            tasks = []
            if eval_base:
                tasks.append(executor.submit(run_base))
            if eval_custom:
                tasks.append(executor.submit(run_custom))
            if eval_gemini:
                tasks.append(executor.submit(run_gemini))
                
            for future in concurrent.futures.as_completed(tasks):
                model_key, r, a, err = future.result()
                if err:
                    # Ném exception lên để hàm ngoài bắt được và tiến hành retry test case này
                    raise RuntimeError(f"Lỗi inference trên model {model_key}: {err}")
                results[model_key] = {
                    "reasoning": r,
                    "answer": a,
                    "error": None
                }
            
    # Chấm điểm kết quả của từng model bằng Gemini 3.5 Flash (chỉ chấm model được đánh giá)
    for model_key in ["base", "custom", "gemini_2.5"]:
        if model_key not in results:
            # Model này đã được giữ nguyên (không đánh giá lại)
            continue
            
        res = results[model_key]
        logger.info(f"Đang chấm điểm câu trả lời của mô hình {model_key}...")
        # Định dạng output để giám khảo chấm đầy đủ reasoning
        model_output = f"LẬP LUẬN:\n{res['reasoning']}\n\nCÂU TRẢ LỜI:\n{res['answer']}" if res["reasoning"] else res["answer"]
        
        try:
            res["scores"] = call_gemini_judge_with_retry(client, context, question, gold_answer, model_output, judge_model=judge_model)
        except Exception as e:
            logger.error(f"Thất bại khi chấm điểm {model_key}: {e}")
            raise RuntimeError(f"Lỗi chấm điểm model {model_key} qua giám khảo: {e}")
                
    return results


def get_sample_hash(sample: dict) -> str:
    question_hash = sample.get("meta", {}).get("question_hash")
    if question_hash:
        return question_hash
    import hashlib
    return hashlib.md5(sample["instruction"].encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Main Execution
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Evaluate 3 models on test dataset using Gemini as judge.")
    parser.add_argument("--input", default="data_gen/advanced_test.jsonl", help="Đường dẫn file dữ liệu test (JSONL).")
    parser.add_argument("--output", default="data_gen/evaluation_results.xlsx", help="Đường dẫn file kết quả Excel đầu ra.")
    parser.add_argument("--base-url", default="https://game-powerful-kit.ngrok-free.app", help="URL API của mô hình Base.")
    parser.add_argument("--base-name", default="unsloth/Qwen3.5-35B-A3B-GGUF", help="Tên mô hình Base.")
    parser.add_argument("--custom-url", default="https://nonrequirable-sherril-undescriptively.ngrok-free.dev/v1/chat/completions", help="URL API của mô hình Custom.")
    parser.add_argument("--custom-name", default="claspi2509/legal-AI-advanced-v2-qwen3.5-q8-gguf", help="Tên mô hình Custom.")
    parser.add_argument("--judge-model", default="gemini-3.5-flash", help="Tên mô hình làm giám khảo chấm điểm.")
    parser.add_argument("--temp", type=float, default=0.3, help="Temperature cho sinh câu trả lời (mặc định: 0.3).")
    parser.add_argument("--max-tokens", type=int, default=8192, help="Token output tối đa cho câu trả lời.")
    parser.add_argument("--sleep", type=float, default=15.0, help="Thời gian nghỉ (giây) giữa các câu hỏi test.")
    parser.add_argument("--limit", type=int, default=None, help="Giới hạn số lượng câu hỏi cần đánh giá (None: toàn bộ).")
    parser.add_argument("--resume", action="store_true", default=True, help="Tiếp tục tiến trình cũ từ file tạm nếu bị gián đoạn.")
    parser.add_argument("--no-resume", action="store_false", dest="resume")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        logger.error(f"Không tìm thấy file test đầu vào: {input_path}")
        sys.exit(1)

    # Đọc tệp test
    samples = []
    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                samples.append(json.loads(line))

    if args.limit:
        samples = samples[:args.limit]
        logger.info(f"Giới hạn đánh giá trên {args.limit} câu hỏi đầu tiên.")
    else:
        logger.info(f"Tổng số câu hỏi sẽ đánh giá: {len(samples)} câu hỏi.")

    # Xác định đường dẫn file log tạm thời (.jsonl) phục vụ resume
    excel_path = Path(args.output)
    excel_path.parent.mkdir(parents=True, exist_ok=True)
    temp_jsonl = excel_path.with_suffix(".jsonl")

    evaluated_ids = set()
    rows_data = []

    evaluated_rows = {}  # mapping hash -> row dict
    evaluated_ids = set()

    # Tải lại tiến trình cũ nếu có
    if args.resume:
        if temp_jsonl.exists():
            logger.info(f"Phát hiện tiến trình cũ từ file tạm: {temp_jsonl}, đang tải...")
            with open(temp_jsonl, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        h = data["hash"]
                        evaluated_rows[h] = data
                        evaluated_ids.add(h)
                    except Exception as e:
                        logger.warning(f"Bỏ qua dòng lỗi trong file tạm: {e}")
            logger.info(f"Đã khôi phục thành công {len(evaluated_rows)} câu hỏi từ file tạm.")
        elif excel_path.exists():
            logger.info(f"Phát hiện file Excel kết quả đã tồn tại: {excel_path}, đang tải tiến trình...")
            try:
                df = pd.read_excel(excel_path)
                # Thay thế các giá trị NaN/NaT thành None để tránh lỗi json
                df = df.where(pd.notnull(df), None)
                for _, row_series in df.iterrows():
                    row_dict = row_series.to_dict()
                    h = row_dict.get("hash")
                    if h:
                        evaluated_rows[h] = row_dict
                        evaluated_ids.add(h)
                logger.info(f"Đã khôi phục thành công {len(evaluated_rows)} câu hỏi từ file Excel.")
            except Exception as e:
                logger.error(f"Lỗi khi đọc file Excel kết quả để resume: {e}")

    # Khởi tạo gemini client
    try:
        gemini_client = _gemini_client()
    except Exception as e:
        logger.error(f"Không thể khởi tạo Gemini Client. Đảm bảo cấu hình GOOGLE_API_KEY chính xác: {e}")
        sys.exit(1)

    logger.info("=== Bắt đầu tiến trình Đánh giá ===")
    
    rows_data = []
    
    for idx, sample in enumerate(samples):
        sample_hash = get_sample_hash(sample)
        
        # Kiểm tra xem case này đã có trong log chưa, và có model nào thiếu điểm/lỗi không
        has_base = False
        has_custom = False
        has_gemini = False
        existing_row = None
        
        if sample_hash in evaluated_ids:
            existing_row = evaluated_rows[sample_hash]
            
            # Đánh giá xem model có điểm hợp lệ không
            # Nếu điểm <= 0.0 hoặc feedback chứa thông báo lỗi/thất bại thì coi như chưa hoàn thành
            def is_valid_score(score, feedback):
                if score is None or score <= 0.0:
                    return False
                feedback_str = str(feedback).lower() if feedback else ""
                # Nếu có lỗi hệ thống hoặc lỗi phân tích trong feedback
                if any(x in feedback_str for x in ["thất bại", "lỗi inference", "lỗi phân tích json", "error", "404", "exception", "failed", "not_found"]):
                    return False
                return True

            has_base = is_valid_score(existing_row.get("Base Total Score"), existing_row.get("Base Feedback"))
            has_custom = is_valid_score(existing_row.get("Custom Total Score"), existing_row.get("Custom Feedback"))
            has_gemini = is_valid_score(existing_row.get("Gemini 2.5 Total Score"), existing_row.get("Gemini 2.5 Feedback"))
            
        eval_base = not has_base
        eval_custom = not has_custom
        eval_gemini = not has_gemini
        
        # Nếu đã có đủ cả 3 model thì bỏ qua
        if not eval_base and not eval_custom and not eval_gemini:
            rows_data.append(existing_row)
            continue

        # Tiến hành chạy đánh giá và recheck/retry đến khi thành công
        logger.info(f"\n[Câu hỏi {idx + 1} / {len(samples)}]")
        logger.info(f"Q: {sample['instruction']}")
        if existing_row:
            logger.info(f"Đánh giá bổ sung: Base={eval_base}, Custom={eval_custom}, Gemini={eval_gemini}")
            
        start_time = time.time()
        
        attempt = 1
        while True:
            try:
                # Gọi song song các model còn thiếu và chấm điểm
                results = evaluate_sample(
                    gemini_client, sample,
                    args.base_url, args.base_name,
                    args.custom_url, args.custom_name,
                    args.temp, args.max_tokens,
                    eval_base=eval_base,
                    eval_custom=eval_custom,
                    eval_gemini=eval_gemini,
                    judge_model=args.judge_model
                )
                
                # Kiểm tra xem kết quả chấm điểm mới chạy có lỗi hay không, nếu lỗi thì ném ngoại lệ để retry ngay lập tức
                def check_score(model_key):
                    res = results.get(model_key)
                    if not res:
                        return
                    score = res.get("scores", {}).get("total_score")
                    feedback = res.get("scores", {}).get("feedback")
                    feedback_str = str(feedback).lower() if feedback else ""
                    
                    # Chỉ retry nếu cuộc gọi bị lỗi (feedback chứa lỗi hệ thống/phân tích) hoặc không có điểm số
                    if any(x in feedback_str for x in ["thất bại", "lỗi inference", "lỗi phân tích json", "error", "404", "exception", "failed", "not_found"]):
                        raise RuntimeError(f"Chấm điểm mô hình {model_key} có lỗi hệ thống hoặc lỗi phân tích: {feedback}")
                    if score is None:
                        raise RuntimeError(f"Chấm điểm mô hình {model_key} không có kết quả điểm số")
                    # Nếu score <= 0.0 nhưng không có lỗi hệ thống và có feedback giải thích đầy đủ, thì chấp nhận và KHÔNG ném lỗi để retry

                if eval_base:
                    check_score("base")
                if eval_custom:
                    check_score("custom")
                if eval_gemini:
                    check_score("gemini_2.5")
                
                # Cập nhật kết quả vào row
                new_row = {
                    "STT": idx + 1,
                    "hash": sample_hash,
                    "Question": sample["instruction"],
                    "Context": sample["input"],
                    "Gold Answer": sample["output"]
                }
                
                # Base model
                if eval_base:
                    new_row["Base Answer"] = results["base"]["answer"]
                    new_row["Base Reasoning"] = results["base"]["reasoning"]
                    new_row["Base Accuracy Score"] = results["base"]["scores"]["accuracy_score"]
                    new_row["Base Completeness Score"] = results["base"]["scores"]["completeness_score"]
                    new_row["Base Logic Score"] = results["base"]["scores"]["logic_score"]
                    new_row["Base Total Score"] = results["base"]["scores"]["total_score"]
                    new_row["Base Feedback"] = results["base"]["scores"]["feedback"]
                else:
                    new_row["Base Answer"] = existing_row["Base Answer"]
                    new_row["Base Reasoning"] = existing_row["Base Reasoning"]
                    new_row["Base Accuracy Score"] = existing_row["Base Accuracy Score"]
                    new_row["Base Completeness Score"] = existing_row["Base Completeness Score"]
                    new_row["Base Logic Score"] = existing_row["Base Logic Score"]
                    new_row["Base Total Score"] = existing_row["Base Total Score"]
                    new_row["Base Feedback"] = existing_row["Base Feedback"]
                    
                # Custom model
                if eval_custom:
                    new_row["Custom Answer"] = results["custom"]["answer"]
                    new_row["Custom Reasoning"] = results["custom"]["reasoning"]
                    new_row["Custom Accuracy Score"] = results["custom"]["scores"]["accuracy_score"]
                    new_row["Custom Completeness Score"] = results["custom"]["scores"]["completeness_score"]
                    new_row["Custom Logic Score"] = results["custom"]["scores"]["logic_score"]
                    new_row["Custom Total Score"] = results["custom"]["scores"]["total_score"]
                    new_row["Custom Feedback"] = results["custom"]["scores"]["feedback"]
                else:
                    new_row["Custom Answer"] = existing_row["Custom Answer"]
                    new_row["Custom Reasoning"] = existing_row["Custom Reasoning"]
                    new_row["Custom Accuracy Score"] = existing_row["Custom Accuracy Score"]
                    new_row["Custom Completeness Score"] = existing_row["Custom Completeness Score"]
                    new_row["Custom Logic Score"] = existing_row["Custom Logic Score"]
                    new_row["Custom Total Score"] = existing_row["Custom Total Score"]
                    new_row["Custom Feedback"] = existing_row["Custom Feedback"]
                    
                # Gemini 2.5 Flash
                if eval_gemini:
                    new_row["Gemini 2.5 Answer"] = results["gemini_2.5"]["answer"]
                    new_row["Gemini 2.5 Reasoning"] = results["gemini_2.5"]["reasoning"]
                    new_row["Gemini 2.5 Accuracy Score"] = results["gemini_2.5"]["scores"]["accuracy_score"]
                    new_row["Gemini 2.5 Completeness Score"] = results["gemini_2.5"]["scores"]["completeness_score"]
                    new_row["Gemini 2.5 Logic Score"] = results["gemini_2.5"]["scores"]["logic_score"]
                    new_row["Gemini 2.5 Total Score"] = results["gemini_2.5"]["scores"]["total_score"]
                    new_row["Gemini 2.5 Feedback"] = results["gemini_2.5"]["scores"]["feedback"]
                else:
                    new_row["Gemini 2.5 Answer"] = existing_row["Gemini 2.5 Answer"]
                    new_row["Gemini 2.5 Reasoning"] = existing_row["Gemini 2.5 Reasoning"]
                    new_row["Gemini 2.5 Accuracy Score"] = existing_row["Gemini 2.5 Accuracy Score"]
                    new_row["Gemini 2.5 Completeness Score"] = existing_row["Gemini 2.5 Completeness Score"]
                    new_row["Gemini 2.5 Logic Score"] = existing_row["Gemini 2.5 Logic Score"]
                    new_row["Gemini 2.5 Total Score"] = existing_row["Gemini 2.5 Total Score"]
                    new_row["Gemini 2.5 Feedback"] = existing_row["Gemini 2.5 Feedback"]
                    
                row = new_row
                break
                
            except KeyboardInterrupt:
                logger.info("Nhận tín hiệu ngắt từ bàn phím. Đang lưu tiến trình và dừng lại.")
                sys.exit(0)
            except Exception as e:
                # Nếu bị lỗi (mất kết nối, API block hoặc rate limit), tiến hành retry
                delay = 30.0 + random.uniform(2.0, 5.0)
                logger.warning(f"Lỗi khi đánh giá mẫu thử (Thử lại {attempt}): {e}. Nghỉ {delay:.1f}s trước khi chạy lại...")
                time.sleep(delay)
                attempt += 1

        # Cập nhật evaluated_rows và evaluated_ids
        evaluated_rows[sample_hash] = row
        evaluated_ids.add(sample_hash)
        rows_data.append(row)
        
        # Ghi lại toàn bộ dữ liệu file log tạm thời JSONL để đồng bộ hóa (overwrite để cập nhật dòng cũ)
        try:
            with open(temp_jsonl, "w", encoding="utf-8") as f_out:
                for h in evaluated_ids:
                    f_out.write(json.dumps(evaluated_rows[h], ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"Lỗi ghi file log tạm JSONL: {e}")

        # Xuất kết quả ra Excel
        try:
            df = pd.DataFrame(rows_data)
            # Dọn dẹp các ký tự không hợp lệ trong Excel
            df = clean_df(df)
            df.to_excel(excel_path, index=False)
            logger.info(f"✓ Đã ghi kết quả cập nhật vào {excel_path} (Thời gian xử lý: {time.time() - start_time:.1f}s)")
        except Exception as e:
            logger.error(f"Lỗi lưu file Excel: {e}")

        # Nghỉ giữa mỗi câu hỏi test để tránh chạm rate limit
        if idx < len(samples) - 1:
            logger.info(f"Nghỉ {args.sleep}s để tránh spam API...")
            try:
                time.sleep(args.sleep)
            except KeyboardInterrupt:
                logger.info("Nhận tín hiệu ngắt từ bàn phím. Đang lưu tiến trình và dừng lại.")
                break

    # Dọn dẹp file JSONL tạm nếu đã hoàn thành 100%
    if len(rows_data) == len(samples):
        try:
            temp_jsonl.unlink(missing_ok=True)
            logger.info("🎉 Hoàn tất đánh giá toàn bộ tệp test! File tạm đã được xóa.")
        except OSError as e:
            logger.warning(f"Không thể xóa file tạm: {e}")
            
    logger.info("=== Kết thúc tiến trình ===")


if __name__ == "__main__":
    main()
