"""
Script sinh dữ liệu chưng cất (data distillation) thực tế, chi tiết, đa cấp độ (Dễ, Vừa, Khó) tự do.
Hỗ trợ sinh tình huống và câu hỏi tự do mà không cần đưa đơn vị luật mẫu (seed unit) vào trước.
Sử dụng đa luồng (multi-threading) để song song hóa cuộc gọi API Gemini và RAG nhằm tăng tốc độ sinh.
Đầu ra tương thích với định dạng chưng cất trước đây (chứa thẻ <think>...</think> ở đầu hoặc lưu riêng).
"""

import os
import sys
import json
import random
import time
import argparse
import hashlib
import threading
import queue
from pathlib import Path
from loguru import logger

# Add project root to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from src import config
from src.document_processor import process_all_documents
from src.graph_extractor import extract_structural
from src.rag_engine import RAGEngine, _build_context_vector_only
from training.generate_training_data import _seed_id, _qhash, _dedupe_fused_by_article, _fetch_seed_chunks_from_chroma, _retrieve_only

# Lock dùng để đồng bộ hóa ghi file, cập nhật biến số câu hỏi đã sinh
file_lock = threading.Lock()
state_lock = threading.Lock()

# Cấu hình timeout mặc định cho API (giây)
API_TIMEOUT = 300.0

# ---------------------------------------------------------------------------
# Gemini Client Helper
# ---------------------------------------------------------------------------
def _gemini_client():
    from google import genai
    from google.genai.types import HttpOptions

    # Chuyển đổi từ giây sang mili-giây cho HttpOptions
    timeout_ms = int(API_TIMEOUT * 1000)

    if config.GEMINI_USE_VERTEXAI:
        return genai.Client(http_options=HttpOptions(api_version="v1", timeout=timeout_ms))
    return genai.Client(
        api_key=config.GOOGLE_API_KEY,
        http_options=HttpOptions(api_version="v1", timeout=timeout_ms),
    )

# ---------------------------------------------------------------------------
# Prompts & Schemas
# ---------------------------------------------------------------------------
SCENARIO_PROMPT = """Bạn là một chuyên gia soạn thảo tình huống pháp lý thực tế tại Việt Nam.
Nhiệm vụ của bạn là hãy tự do tạo ra {n} tình huống (scenarios) pháp lý đa dạng về chủ đề và mức độ khó, chi tiết và dài như một vụ án/tranh chấp thực tế.

Mỗi kịch bản phải chứa đầy đủ thông tin, hành vi, các bên tham gia (VD: Công ty A, Anh B, Chị C) và tình huống phức tạp có tranh chấp, lỗi lầm từ nhiều phía, hoặc điều khoản miễn trừ trách nhiệm.

Phạm vi luật của kịch bản:
- Bắt buộc tình huống phải liên quan trực tiếp đến các vấn đề pháp lý được điều chỉnh bởi 4 bộ luật sau:
   - Bộ luật Dân sự 2015 (91/2015/QH13)
   - Bộ luật Hình sự 2015 (100/2015/QH13)
   - Luật Hôn nhân và Gia đình 2014 (52/2014/QH13)
   - Bộ luật Lao động 2019 (45/2019/QH14)
- KHÔNG tạo tình huống liên quan đến các văn bản luật nằm ngoài 4 luật này.

Yêu cầu cụ thể:
1. Tạo ra các kịch bản tình huống pháp lý khác nhau theo 3 mức độ khó:
   - Dễ (Easy): Tình huống đơn giản trực quan, dễ áp dụng luật để tìm câu trả lời.
   - Vừa (Medium): Tình huống phức tạp hơn, đòi hỏi phân tích hành vi của nhiều bên.
   - Khó (Hard): Tình huống cực kỳ chi tiết, nhiều tình tiết đan xen, lỗi hỗn hợp, tranh chấp đa chiều (như ví dụ về ô tô tự lái đâm xe máy vượt tốc độ, lỗi phần mềm, điều khoản miễn trừ trong hợp đồng).
2. Với mỗi kịch bản, hãy soạn thảo từ 2-4 câu hỏi chi tiết xoáy sâu vào các vấn đề pháp lý phát sinh trong kịch bản. Các câu hỏi này phải giải quyết được hoàn toàn dựa trên 4 bộ luật nêu trên.
3. Trong kết quả JSON trả về, trường is_rag_related bắt buộc phải luôn luôn bằng true.

Hãy trả về kết quả định dạng JSON khớp chính xác với JSON Schema được yêu cầu."""

SCENARIO_SCHEMA = {
    "type": "object",
    "properties": {
        "scenarios": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "level": {"type": "string", "enum": ["easy", "medium", "hard"]},
                    "is_rag_related": {"type": "boolean"},
                    "scenario_text": {"type": "string"},
                    "questions": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                },
                "required": ["level", "is_rag_related", "scenario_text", "questions"]
            }
        }
    },
    "required": ["scenarios"]
}

DISTILL_PROMPT = """Bạn là một Thẩm phán và chuyên gia phân tích pháp luật Việt Nam xuất sắc.
Hãy trả lời các câu hỏi dựa trên Tình huống pháp lý thực tế và Ngữ cảnh tài liệu tham khảo (RAG Context) được cung cấp dưới đây.

--- Tình huống pháp lý ---
{scenario_text}

--- Tài liệu tham khảo (RAG Context) ---
{context}

--- Câu hỏi cần trả lời ---
{question}

Yêu cầu trả về JSON có cấu trúc gồm 2 trường:
1. reasoning: trình bày chi tiết và cặn kẽ quá trình lập luận từng bước bằng tiếng Việt.
   - Phải xác định rõ vấn đề pháp lý mấu chốt.
   - Phải trích dẫn cụ thể các Điều/Khoản luật có trong phần Tài liệu tham khảo (RAG Context) được cung cấp.
   - Tuyệt đối KHÔNG được sử dụng, viện dẫn, hay suy luận dựa trên bất kỳ kiến thức pháp lý, điều luật, văn bản luật hay dữ liệu nào nằm ngoài các tài liệu được cung cấp ở phần RAG Context này. Nếu RAG Context không chứa điều luật liên quan, bạn không được tự ý bịa ra hoặc sử dụng luật ngoài.
   - Phân tích chi tiết lỗi, trách nhiệm pháp lý dân sự/hình sự của các chủ thể liên quan trong tình huống.
   - Tự kiểm tra (recheck) lại lập luận của mình tối thiểu 2 lần ngay trong nội dung reasoning để phát hiện mâu thuẫn trước khi chốt kết luận.
   - Định dạng bắt buộc: Mỗi bước lập luận phải viết trên một dòng riêng biệt, bắt đầu bằng số thứ tự và dấu chấm (VD: "1. ...\n2. ...").
2. answer: câu trả lời cuối cùng bằng tiếng Việt thật cặn kẽ, đầy đủ, cấu trúc rõ ràng, chuyên nghiệp, trích dẫn chi tiết cơ sở pháp lý và số hiệu văn bản luật có trong RAG Context. Tránh lặp lại nguyên văn từng dòng của phần reasoning nhưng phải khớp kết luận. Câu trả lời cũng tuyệt đối KHÔNG được viện dẫn bất kỳ kiến thức hay dữ liệu luật nào ngoài phạm vi tài liệu tham khảo (RAG Context) được cung cấp."""

DISTILL_SCHEMA = {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string"},
        "answer": {"type": "string"}
    },
    "required": ["reasoning", "answer"]
}

# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------
def _read_scenarios_done(path: Path) -> set[str]:
    done = set()
    if not path.exists():
        return done
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            qhash = rec.get("meta", {}).get("question_hash")
            if qhash:
                done.add(qhash)
        except Exception:
            continue
    return done

def gen_scenarios(n: int = 1, max_retries: int = 5) -> list[dict]:
    from google.genai import types

    prompt = SCENARIO_PROMPT.format(n=n)

    for attempt in range(1, max_retries + 1):
        try:
            client = _gemini_client()
            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=SCENARIO_SCHEMA,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            data = json.loads(resp.text or "{}")
            return data.get("scenarios", []) or []
        except Exception as e:
            from training.generate_training_data import _is_retryable
            if attempt < max_retries and _is_retryable(e):
                delay = 2.0 * attempt + random.uniform(0.1, 0.9)
                logger.warning(f"gen_scenarios retry {attempt}/{max_retries}. Sleep {delay:.1f}s")
                time.sleep(delay)
                continue
            logger.warning(f"gen_scenarios failed: {e}")
            return []
    return []

def distill_qa_pair(scenario_text: str, question: str, context: str, thinking_budget: int = -1, max_retries: int = 5) -> tuple[str, str]:
    from google.genai import types

    prompt = DISTILL_PROMPT.format(
        scenario_text=scenario_text,
        context=context,
        question=question
    )

    for attempt in range(1, max_retries + 1):
        try:
            client = _gemini_client()
            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=DISTILL_SCHEMA,
                    thinking_config=types.ThinkingConfig(thinking_budget=thinking_budget),
                ),
            )
            data = json.loads(resp.text or "{}")
            reasoning = str(data.get("reasoning") or "").strip()
            answer = str(data.get("answer") or "").strip()
            return reasoning, answer
        except Exception as e:
            from training.generate_training_data import _is_retryable
            if attempt < max_retries and _is_retryable(e):
                delay = 2.0 * attempt + random.uniform(0.1, 0.9)
                logger.warning(f"distill retry {attempt}/{max_retries}: {e}. Sleep {delay:.1f}s")
                time.sleep(delay)
                continue
            logger.warning(f"distill Gemini failed: {e}")
            return "", ""
    return "", ""

# ---------------------------------------------------------------------------
# Main Execution Flow
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Distill advanced legal QA pairs using gemini-2.5-flash.")
    parser.add_argument("--batch-size", type=int, default=2, help="Số lượng kịch bản sinh ra mỗi lần gọi API.")
    parser.add_argument("--output", default="data_gen/distill_advanced_data.jsonl", help="Đường dẫn file lưu dữ liệu nâng cao.")
    parser.add_argument("--format", choices=["sft", "rag_sft", "chatml"], default="rag_sft")
    parser.add_argument("--reasoning-style", choices=["tag", "separate"], default="tag")
    parser.add_argument("--target-size", type=int, default=6000, help="Số lượng cặp QA đích mong muốn (khoảng 1/3 đến 1/2 của 17.3K).")
    parser.add_argument("--num-threads", type=int, default=1, help="Số lượng luồng song song chạy đồng thời.")
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument("--sleep", type=float, default=2.0, help="Sleep nhẹ giữa các lần gọi để tránh spam API.")
    parser.add_argument("--thinking-budget", type=int, default=-1, help="Thinking budget cho Gemini 2.5 Flash (-1: auto/unlimited, 0: tắt).")
    parser.add_argument("--timeout", type=float, default=300.0, help="Timeout cho gọi API Gemini (giây).")
    args = parser.parse_args()

    global API_TIMEOUT
    API_TIMEOUT = args.timeout

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Đọc danh sách câu hỏi đã xử lý để tránh trùng lặp
    done_questions = _read_scenarios_done(out_path) if args.resume else set()
    
    logger.info(f"Bắt đầu sinh câu hỏi tự do (Mô hình Producer-Consumer). Luồng Consumer: {args.num_threads}. Đã hoàn thành trước đó: {len(done_questions)} câu hỏi.")

    engine = RAGEngine()
    
    # Biến trạng thái toàn cục được bảo vệ bởi state_lock
    state = {
        "q_count": len(done_questions),
        "target_size": args.target_size
    }

    task_queue = queue.Queue(maxsize=100)
    stop_event = threading.Event()

    def producer_loop():
        logger.info("[Producer] Khởi chạy luồng sinh kịch bản...")
        batch_idx = 1
        
        while not stop_event.is_set():
            with state_lock:
                if state["q_count"] + task_queue.qsize() >= args.target_size:
                    logger.info("[Producer] Đã đạt hoặc xếp hàng đủ số lượng mục tiêu. Dừng sinh kịch bản mới.")
                    break
            
            logger.info(f"[Producer] Đang gọi API tạo Batch #{batch_idx}")
            scenarios = gen_scenarios(n=args.batch_size)
            if not scenarios:
                logger.warning(f"[Producer] Không sinh được kịch bản ở Batch #{batch_idx}. Thử lại sau 2 giây...")
                time.sleep(2.0)
                continue
                
            batch_idx += 1
            
            for sc in scenarios:
                scenario_text = sc.get("scenario_text", "")
                questions = sc.get("questions", [])
                level = sc.get("level", "medium")
                is_rag_related = True  # Luôn luôn là True để chỉ sử dụng tài liệu RAG
                
                if not scenario_text or not questions:
                    continue
                    
                for q in questions:
                    qhash = _qhash(q)
                    
                    with state_lock:
                        if qhash in done_questions:
                            continue
                        done_questions.add(qhash)
                        
                        if state["q_count"] + task_queue.qsize() >= args.target_size:
                            logger.info("[Producer] Hàng đợi và câu hỏi đã ghi đủ target_size. Dừng thêm câu hỏi mới.")
                            return
                            
                    task = (scenario_text, q, level, is_rag_related, qhash)
                    task_queue.put(task)
                    
            if args.sleep > 0:
                time.sleep(args.sleep)

    def consumer_loop(worker_id):
        client_name = f"Consumer-{worker_id}"
        logger.info(f"[{client_name}] Khởi chạy...")
        
        while not stop_event.is_set():
            try:
                task = task_queue.get(timeout=2.0)
            except queue.Empty:
                if not producer.is_alive() and task_queue.empty():
                    break
                continue
                
            scenario_text, q, level, is_rag_related, qhash = task
            
            # Thu nhập ngữ cảnh tài liệu (RAG)
            context_text = ""
            sources = []
            mode = "none"
            if is_rag_related:
                try:
                    context_text, sources, mode = _retrieve_only(
                        engine, q,
                        seed_law=None,
                        seed_article=None,
                        seed_clause=None
                    )
                except Exception as e:
                    logger.warning(f"[{client_name}] RAG Retrieval lỗi cho câu hỏi '{q[:30]}': {e}")
                    context_text = "Không thể truy xuất tài liệu do lỗi hệ thống."
            else:
                context_text = "Câu hỏi này nằm ngoài phạm vi của tài liệu tham khảo RAG được cung cấp."
                mode = "non-rag"
                
            # Gọi Gemini chưng cất reasoning + answer
            logger.info(f"[{client_name}] Đang chưng cất QA cho câu hỏi: '{q[:50]}...'")
            reasoning, answer = distill_qa_pair(scenario_text, q, context_text, thinking_budget=args.thinking_budget)
            
            if not reasoning or not answer:
                logger.warning(f"[{client_name}] Chưng cất thất bại cho câu hỏi: '{q[:30]}'. Bỏ qua.")
                with state_lock:
                    done_questions.discard(qhash)
                task_queue.task_done()
                continue
                
            # Tạo bản ghi hoàn chỉnh
            record = {
                "seed_id": "free_form",
                "level": level,
                "is_rag_related": is_rag_related,
                "question": q,
                "question_hash": qhash,
                "reasoning": reasoning,
                "answer": answer,
                "context": f"TÌNH HUỐNG:\n{scenario_text}\n\nTÀI LIỆU THAM KHẢO:\n{context_text}" if is_rag_related else f"TÌNH HUỐNG:\n{scenario_text}",
                "sources": sources,
                "retrieval_mode": mode
            }
            
            formatted_item = _format_record(record, args.format, args.reasoning_style)
            
            # Ghi file đồng bộ an toàn qua file_lock
            with file_lock:
                with state_lock:
                    if state["q_count"] >= state["target_size"]:
                        task_queue.task_done()
                        break
                    state["q_count"] += 1
                    current_total = state["q_count"]
                
                with out_path.open("a", encoding="utf-8") as f_out:
                    f_out.write(json.dumps(formatted_item, ensure_ascii=False) + "\n")
                    f_out.flush()
                
                logger.info(f"💾 [{client_name}] [Thành công] Đã ghi câu hỏi #{current_total} vào {args.output}")
            
            task_queue.task_done()
            
            if args.sleep > 0:
                logger.info(f"[{client_name}] Nghỉ {args.sleep}s để tránh spam API...")
                time.sleep(args.sleep)
                
        logger.info(f"[{client_name}] Đã dừng.")

    # Khởi chạy luồng Producer
    producer = threading.Thread(target=producer_loop, name="Producer")
    producer.daemon = True
    producer.start()
    
    # Khởi chạy các luồng Consumer
    consumers = []
    for i in range(1, args.num_threads + 1):
        t = threading.Thread(target=consumer_loop, args=(i,), name=f"Consumer-{i}")
        t.daemon = True
        t.start()
        consumers.append(t)
        
    try:
        # Chờ producer hoàn thành
        while producer.is_alive():
            producer.join(timeout=1.0)
            
        # Chờ hàng đợi được xử lý hết
        task_queue.join()
        
        # Báo hiệu dừng cho các consumer
        stop_event.set()
        for t in consumers:
            t.join()
            
    except KeyboardInterrupt:
        logger.warning("Nhận tín hiệu dừng từ bàn phím. Đang dừng các luồng...")
        stop_event.set()
        while not task_queue.empty():
            try:
                task_queue.get_nowait()
                task_queue.task_done()
            except queue.Empty:
                break
        for t in consumers:
            t.join()

def _format_record(record: dict, fmt: str, reasoning_style: str = "tag") -> dict:
    meta = {
        "seed_id": record.get("seed_id"),
        "level": record.get("level"),
        "is_rag_related": record.get("is_rag_related"),
        "retrieval_mode": record.get("retrieval_mode"),
        "sources": record.get("sources", []),
        "question_hash": record.get("question_hash")
    }
    reasoning = (record.get("reasoning") or "").strip()
    answer = (record.get("answer") or "").strip()

    if reasoning and reasoning_style == "tag":
        output_text = f"<think>\n{reasoning}\n</think>\n\n{answer}"
    else:
        output_text = answer
        meta["reasoning"] = reasoning

    if fmt == "rag_sft":
        return {
            "instruction": record["question"],
            "input": record.get("context", ""),
            "output": output_text,
            "meta": meta
        }
    elif fmt == "sft":
        return {
            "instruction": f"Tình huống:\n{record.get('context', '')}\n\nCâu hỏi:\n{record['question']}",
            "input": "",
            "output": output_text,
            "meta": meta
        }
    elif fmt == "chatml":
        return {
            "messages": [
                {"role": "system", "content": config.SYSTEM_PROMPT},
                {"role": "user", "content": f"Dựa trên tình huống sau để trả lời:\n{record.get('context', '')}\n\nCâu hỏi:\n{record['question']}"},
                {"role": "assistant", "content": output_text}
            ],
            "meta": meta
        }
    raise ValueError(f"Định dạng không hỗ trợ: {fmt}")

if __name__ == "__main__":
    main()
