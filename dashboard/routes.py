from __future__ import annotations

import base64
import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from math import ceil
from typing import Optional, Dict, List
from pathlib import Path

from flask import (
    Blueprint,
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
    session,
    current_app,
)
from langchain_openai import ChatOpenAI
from db import DEFAULT_TKA_PRESET_KEY, DEFAULT_TKA_COMPOSITE_DURATION, DEFAULT_TKA_GRADE_LEVEL, TKA_SECTION_TEMPLATES
from werkzeug.datastructures import MultiDict

from .auth import current_user, login_required, role_required
from utils import current_jakarta_time, to_jakarta
from .queries import (
    BULLYING_STATUSES,
    PSYCH_STATUSES,
    CORRUPTION_STATUSES,
    ChatFilters,
    fetch_all_chat_users,
    fetch_bullying_reports,
    fetch_bullying_summary,
    fetch_bullying_report_detail,
    fetch_bullying_report_basic,
    fetch_chat_logs,
    fetch_conversation_thread,
    fetch_daily_activity,
    fetch_overview_metrics,
    fetch_recent_questions,
    fetch_top_keywords,
    fetch_top_users,
    update_bullying_report_status,
    bulk_update_bullying_report_status,
    fetch_psych_reports,
    fetch_psych_summary,
    fetch_psych_group_reports,
    update_psych_report_status,
    bulk_update_psych_report_status,
    fetch_corruption_reports,
    fetch_corruption_summary,
    fetch_corruption_report_detail,
    bulk_update_corruption_report_status,
    update_corruption_report_status,
    fetch_twitter_overview,
    fetch_twitter_activity,
    fetch_twitter_top_users,
    chat_topic_available,
    fetch_twitter_worker_logs,
    update_no_tester_preference,
    fetch_tka_subjects,
    fetch_tka_questions,
    create_tka_subject,
    create_tka_questions,
    delete_tka_question,
    fetch_tka_subject,
    fetch_tka_attempts,
    update_tka_question,
    update_tka_subject_difficulty,
    has_tka_question_with_prompt,
    update_tka_subject_sections,
    fetch_tka_tests,
    delete_tka_test,
    create_tka_test,
    fetch_tka_test,
    fetch_tka_test_subjects,
    fetch_tka_test_subject,
    create_tka_test_subject,
    delete_tka_test_subject,
    update_tka_test_subject_topics,
    fetch_tka_mapel,
    fetch_tka_mapel_list,
    create_tka_mapel,
    delete_tka_mapel,
    ensure_tka_subject_from_mapel,
    fetch_tka_stimulus_list,
    fetch_tka_stimulus,
    create_tka_stimulus,
    update_tka_stimulus,
    delete_tka_stimulus,
    set_tka_test_grade_level,
)

main_bp = Blueprint("main", __name__)
PAGE_SIZE = 50
REPORT_PAGE_SIZE = 25
TWITTER_PAGE_SIZE = 25
PROJECT_ROOT = Path(__file__).resolve().parent.parent
_TKA_AI_CHAIN = None
_TKA_AI_CHAIN_FAILED = False
TKA_PRESET_LABELS = {
    "mudah": "Mudah",
    "sedang": "Sedang",
    "susah": "Susah",
    "custom": "Kustom",
}
GRADE_LABELS = {
    "sd6": "Kelas 6 SD",
    "smp3": "Kelas 3 SMP",
    "sma": "SMA",
}
GRADE_LEVEL_HINTS = {
    "sd6": "siswa kelas 6 SD",
    "smp3": "siswa kelas 3 SMP",
    "sma": "siswa SMA",
}
VALID_GRADE_LEVELS = set(GRADE_LABELS.keys())


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _env_flag(name: str, default: str = "false") -> bool:
    value = os.getenv(name, default)
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_runtime_path(value: Optional[str], default: str) -> Path:
    path = Path(value or default)
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    return path


def _load_twitter_runtime() -> dict:
    """Kumpulkan info real-time worker Twitter dari env, state file, dan autopost list."""
    state_path = _resolve_runtime_path(os.getenv("TWITTER_STATE_PATH"), "twitter_state.json")
    autopost_path = _resolve_runtime_path(os.getenv("TWITTER_AUTOPOST_MESSAGES_PATH"), "twitter_posts.txt")
    raw_bot_user_id = os.getenv("TWITTER_USER_ID")
    bot_user_id: Optional[int]
    if raw_bot_user_id:
        try:
            bot_user_id = int(str(raw_bot_user_id).strip())
        except (TypeError, ValueError):
            bot_user_id = None
    else:
        bot_user_id = None
    raw_bot_username = (os.getenv("TWITTER_USERNAME") or "").strip()
    if raw_bot_username.startswith("@"):
        raw_bot_username = raw_bot_username[1:]
    bot_username = raw_bot_username or None

    runtime: dict = {
        "state_path": str(state_path),
        "autopost_path": str(autopost_path),
        "state_exists": state_path.exists(),
        "autopost_exists": autopost_path.exists(),
        "state_error": None,
        "autopost_error": None,
        "state": {},
        "last_seen_id": None,
        "autopost_state": {},
        "last_autopost": None,
        "autopost_entries": [],
        "autopost_total": 0,
        "autopost_rag_total": 0,
        "autopost_preview": [],
        "bot_user_id": bot_user_id,
        "bot_username": bot_username,
        "settings": {
            "mentions_enabled": _env_flag("TWITTER_MENTIONS_ENABLED", "true"),
            "autopost_enabled": _env_flag("TWITTER_AUTOPOST_ENABLED", "false"),
            "poll_interval": int(os.getenv("TWITTER_POLL_INTERVAL", "180") or 180),
            "mentions_cooldown": int(os.getenv("TWITTER_MENTIONS_COOLDOWN", "180") or 180),
            "mentions_max_results": int(os.getenv("TWITTER_MENTIONS_MAX_RESULTS", "5") or 5),
            "autopost_interval": int(os.getenv("TWITTER_AUTOPOST_INTERVAL", "3600") or 3600),
            "autopost_recent_limit": int(os.getenv("TWITTER_AUTOPOST_RECENT_LIMIT", "8") or 8),
            "max_tweet_len": int(os.getenv("TWITTER_MAX_TWEET_LEN", "280") or 280),
        },
    }

    if runtime["state_exists"]:
        try:
            with state_path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
            if isinstance(payload, dict):
                runtime["state"] = payload
                runtime["last_seen_id"] = payload.get("last_seen_id")
                autopost_state = payload.get("autopost")
                if isinstance(autopost_state, dict):
                    runtime["autopost_state"] = autopost_state
                    last_ts = autopost_state.get("last_timestamp")
                    if isinstance(last_ts, (int, float)) and last_ts > 0:
                        runtime["last_autopost"] = datetime.fromtimestamp(last_ts, tz=timezone.utc)
            else:
                runtime["state_error"] = "Format state file tidak dikenal."
        except Exception as exc:
            runtime["state_error"] = str(exc)
    else:
        runtime["state_error"] = "File state belum dibuat oleh worker."

    entries: list[dict] = []
    if runtime["autopost_exists"]:
        try:
            text = autopost_path.read_text(encoding="utf-8")
            for raw_line in text.splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                is_rag = line.upper().startswith("RAG:")
                display = line[4:].strip() if is_rag else line
                entry = {
                    "raw": line,
                    "display": display,
                    "is_rag": is_rag,
                    "has_placeholders": "{{" in line and "}}" in line,
                }
                entries.append(entry)
        except Exception as exc:
            runtime["autopost_error"] = str(exc)
    else:
        runtime["autopost_error"] = "File daftar autopost belum tersedia."

    runtime["autopost_entries"] = entries
    runtime["autopost_total"] = len(entries)
    runtime["autopost_rag_total"] = sum(1 for item in entries if item.get("is_rag"))
    runtime["autopost_preview"] = entries[:8]
    if runtime.get("last_autopost"):
        runtime["last_autopost_local"] = to_jakarta(runtime["last_autopost"])
    else:
        runtime["last_autopost_local"] = None

    return runtime


def _get_tka_ai_chain():
    """Lazy-load LLM khusus generator soal dengan temperatur fleksibel."""
    global _TKA_AI_CHAIN, _TKA_AI_CHAIN_FAILED
    if _TKA_AI_CHAIN_FAILED:
        return None
    if _TKA_AI_CHAIN is None:
        try:
            api_key = os.getenv("ASKA_TKA_GENERATOR_API_KEY") or os.getenv("GROQ_API_KEY") or os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise RuntimeError("API key untuk generator TKA belum disetel.")

            api_base = (
                os.getenv("ASKA_TKA_GENERATOR_API_BASE")
                or os.getenv("ASKA_OPENAI_API_BASE")
                or os.getenv("OPENAI_API_BASE")
                or os.getenv("ASKA_GROQ_API_BASE")
                or "https://api.groq.com/openai/v1"
            )
            model_name = os.getenv("ASKA_TKA_GENERATOR_MODEL") or os.getenv("ASKA_QA_MODEL", "llama-3.1-8b-instant")
            temperature = float(os.getenv("ASKA_TKA_GENERATOR_TEMPERATURE", os.getenv("ASKA_QA_TEMPERATURE", "0.7")))
            max_tokens = int(os.getenv("ASKA_TKA_GENERATOR_MAX_TOKENS", "600"))

            _TKA_AI_CHAIN = ChatOpenAI(
                temperature=temperature,
                model=model_name,
                openai_api_key=api_key,
                openai_api_base=api_base,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            current_app.logger.error("Gagal menyiapkan model AI untuk Latihan TKA: %s", exc)
            _TKA_AI_CHAIN_FAILED = True
            return None
    return _TKA_AI_CHAIN


def _strip_code_fences(text: str) -> str:
    cleaned = (text or "").strip()
    delimiter = "```"
    if delimiter in cleaned:
        parts = cleaned.split(delimiter)
        if len(parts) >= 3:
            cleaned = parts[1].strip()
        else:
            cleaned = cleaned.replace(delimiter, "").strip()
    cleaned_lower = cleaned.lower()
    if cleaned_lower.startswith("json"):
        cleaned = cleaned[4:].strip()
        cleaned_lower = cleaned.lower()
    idx_json = cleaned_lower.find("\njson")
    if idx_json != -1:
        cleaned = cleaned[idx_json + 5 :].strip()
    cleaned = _extract_json_payload(cleaned)
    return cleaned


def _extract_json_payload(text: str) -> str:
    """Ambil substring JSON dari teks bebas, mendukung objek atau array."""
    if not text:
        return text
    start = None
    opening = None
    for idx, ch in enumerate(text):
        if ch in "{[":
            start = idx
            opening = ch
            break
    if start is None:
        return text
    closing = "}" if opening == "{" else "]"
    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == opening:
            depth += 1
        elif ch == closing:
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    return text[start:]


def _normalize_jsonish_text(text: str) -> str:
    replacements = {
        "\u201c": '"',
        "\u201d": '"',
        "\u2018": "'",
        "\u2019": "'",
    }
    for key, value in replacements.items():
        text = text.replace(key, value)
    return _escape_json_newlines(text)


def _escape_json_newlines(text: str) -> str:
    if not text:
        return text
    result: list[str] = []
    in_string = False
    escape = False
    for ch in text:
        if escape:
            result.append(ch)
            escape = False
            continue
        if ch == "\\":
            result.append(ch)
            escape = True
            continue
        if ch == '"':
            result.append(ch)
            in_string = not in_string
            continue
        if ch == "\n" and in_string:
            result.append("\\n")
            continue
        if ch == "\r" and in_string:
            continue
        result.append(ch)
    return "".join(result)


def _enforce_min_paragraphs(text: str, target: int) -> str:
    """
    Bantu memastikan jumlah paragraf minimal sesuai permintaan user.
    Membelah dengan newline ganda dulu, lalu fallback ke pemecahan kalimat.
    """
    if not text:
        return text
    if target <= 1:
        return text.strip()
    clean_text = text.strip()
    paragraphs = [p.strip() for p in re.split(r"\n{2,}|\r?\n", clean_text) if p.strip()]
    if len(paragraphs) >= target:
        return "\n\n".join(paragraphs[:target])
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", clean_text) if s.strip()]
    if not sentences:
        return clean_text
    if len(sentences) <= target:
        return "\n\n".join(sentences)
    group_size = ceil(len(sentences) / target)
    grouped: list[str] = []
    for idx in range(0, len(sentences), group_size):
        chunk = " ".join(sentences[idx : idx + group_size]).strip()
        if chunk:
            grouped.append(chunk)
    if len(grouped) >= target:
        grouped = grouped[:target]
    return "\n\n".join(grouped) if grouped else clean_text


def _repair_bare_fields(text: str) -> str:
    """
    Tambal beberapa pola umum yang sering keluar tanpa tanda kutip agar JSON bisa diparse.
    Contoh: image_prompt: Taman Sekolah -> "image_prompt":"Taman Sekolah"
    """
    if not text:
        return text
    try:
        text = re.sub(
            r'\bimage_prompt\s*:\s*([^\n\r",][^\n\r]*)',
            lambda m: f'"image_prompt":"{m.group(1).strip()}"',
            text,
        )
        text = re.sub(r'\bquestions\s*:\s*\[', '"questions":[', text)
        # Sisipkan koma yang hilang antar field umum (narrative -> image_prompt -> questions)
        text = re.sub(
            r'("narrative"\s*:\s*"[^"]*")\s*("image_prompt"\s*:\s*")',
            r'\1,\2',
            text,
        )
        text = re.sub(
            r'("image_prompt"\s*:\s*"[^"]*")\s*("questions"\s*:\s*\[)',
            r'\1,\2',
            text,
        )
    except Exception:
        return text
    return text


def _repair_split_question_arrays(text: str) -> str:
    if not text:
        return text
    text = re.sub(r"}\s*],\s*\[{", "},{", text)
    text = re.sub(r"]\s*,\s*\[{", ",{", text)
    return text


def _close_unbalanced_json(text: str) -> str:
    if not text:
        return text
    # Hapus koma menggantung di akhir teks supaya penutupan otomatis tidak menghasilkan `,}` atau `,]`
    trimmed = text.rstrip()
    while trimmed.endswith(","):
        trimmed = trimmed[:-1].rstrip()
    text = trimmed
    stack: list[str] = []
    in_string = False
    escape = False
    for ch in text:
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()
    closing = ""
    for opener in reversed(stack):
        closing += '}' if opener == '{' else ']'
    return text + closing


def _repair_trailing_commas(text: str) -> str:
    if not text:
        return text
    return re.sub(r",(?=\s*[}\]])", "", text)


def _repair_unterminated_strings(text: str) -> str:
    """
    Tutup string yang terpotong di akhir respons (misal \"Mengunj |\" tanpa tanda kutip penutup).
    """
    if not text:
        return text
    text = re.sub(r'"text":"([^"]*)$', r'"text":"\1"', text)
    text = re.sub(r'"prompt":"([^"]*)$', r'"prompt":"\1"', text)
    text = re.sub(r'"explanation":"([^"]*)$', r'"explanation":"\1"', text)
    # Pastikan jumlah kutip ganda tidak ganjil.
    unescaped_quotes = 0
    escape = False
    for ch in text:
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            unescaped_quotes += 1
    if unescaped_quotes % 2 != 0:
        text += '"'
    return text


def _salvage_questions_from_text(text: str) -> list[dict]:
    """
    Ambil sebanyak mungkin objek pertanyaan dari teks JSON yang terpotong.
    Mengabaikan entri terakhir yang belum lengkap agar parsing tetap berhasil.
    """
    if not text:
        return []
    anchor = text.find('"questions"')
    if anchor == -1:
        return []
    start = text.find("[", anchor)
    if start == -1:
        return []
    items: list[str] = []
    in_string = False
    escape = False
    depth = 0
    obj_start = None
    for idx in range(start, len(text)):
        ch = text[idx]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
            if depth == 1:
                obj_start = idx
        elif ch == "}":
            if depth == 1 and obj_start is not None:
                items.append(text[obj_start : idx + 1])
                obj_start = None
            if depth > 0:
                depth -= 1
        elif ch == "]" and depth == 0:
            break
    recovered: list[dict] = []
    for raw in items:
        normalized = _close_unbalanced_json(
            _repair_trailing_commas(_repair_unterminated_strings(_normalize_jsonish_text(raw)))
        )
        try:
            parsed = json.loads(normalized)
            if isinstance(parsed, dict):
                recovered.append(parsed)
        except Exception:
            continue
    return recovered


def _salvage_stimulus_from_text(text: str) -> Optional[dict]:
    """
    Ambil data stimulus pertama tanpa daftar questions agar bisa dipakai menyelamatkan output terpotong.
    """
    if not text:
        return None
    anchor = text.find('"stimulus"')
    if anchor == -1:
        return None
    obj_start = text.find("{", anchor)
    if obj_start == -1:
        return None
    questions_anchor = text.find('"questions"', obj_start)
    block = text[obj_start : questions_anchor if questions_anchor != -1 else None]
    block = block.rstrip()
    if block.endswith(","):
        block = block[:-1]
    normalized = _close_unbalanced_json(
        _repair_trailing_commas(_repair_unterminated_strings(_normalize_jsonish_text(block)))
    )
    try:
        parsed = json.loads(normalized)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


MIN_GENERATED_CHILDREN = 3
MAX_GENERATED_CHILDREN = 5


def _infer_stimulus_type(has_text: bool, has_image: bool) -> str:
    if has_text and has_image:
        return "mixed"
    if has_image:
        return "image"
    return "text"


def _build_stimulus_meta(raw: Optional[dict], fallback_title: str, *, forced_key: Optional[str] = None) -> Optional[dict]:
    if not raw or not isinstance(raw, dict):
        return None
    title = (raw.get("title") or raw.get("name") or fallback_title).strip()
    narrative = (
        raw.get("narrative")
        or raw.get("story")
        or raw.get("text")
        or raw.get("narasi")
        or ""
    ).strip()
    image_value = (
        raw.get("image_data")
        or raw.get("image_url")
        or raw.get("image")
        or raw.get("gambar")
    )
    image_data: Optional[str] = None
    image_url: Optional[str] = None
    if isinstance(image_value, dict):
        image_url = image_value.get("url") or image_value.get("image_url")
        image_data = image_value.get("data") or image_value.get("image_data")
    elif isinstance(image_value, str):
        if image_value.startswith("http"):
            image_url = image_value
        else:
            image_data = image_value
    bundle_key = forced_key or raw.get("bundle_key") or f"stim-{secrets.token_hex(4)}"
    stimulus_meta = {
        "bundle_key": bundle_key,
        "title": title or fallback_title,
        "narrative": narrative,
        "image_prompt": raw.get("image_prompt") or raw.get("imagePrompt") or "",
        "type": raw.get("type") or _infer_stimulus_type(bool(narrative), bool(image_data or image_url)),
    }
    if image_data:
        stimulus_meta["image_data"] = image_data
    if image_url:
        stimulus_meta["image_url"] = image_url
    raw_metadata = raw.get("metadata")
    if isinstance(raw_metadata, dict) and raw_metadata:
        stimulus_meta["metadata"] = raw_metadata
    return stimulus_meta


def _build_generated_question(
    item: dict,
    fallback_topic: str,
    fallback_difficulty: str,
    generator_mode: str,
) -> Optional[dict]:
    if not isinstance(item, dict):
        return None
    prompt = (item.get("prompt") or item.get("question") or "").strip()
    if not prompt:
        return None
    topic = (fallback_topic or item.get("topic") or "").strip()
    difficulty = (item.get("difficulty") or fallback_difficulty).strip().lower()
    if difficulty not in {"easy", "medium", "hard"}:
        difficulty = fallback_difficulty
    options_raw = item.get("options") or item.get("choices") or item.get("opsi")
    options: list[dict] = []
    if isinstance(options_raw, dict):
        for key, value in options_raw.items():
            options.append({"key": str(key).strip().upper(), "text": str(value).strip()})
    elif isinstance(options_raw, list):
        for idx, option in enumerate(options_raw):
            if isinstance(option, dict):
                key = option.get("key") or option.get("label") or option.get("huruf") or (
                    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[idx] if idx < 26 else f"OP{idx+1}"
                )
                text = option.get("text") or option.get("value") or option.get("content") or ""
            else:
                key = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[idx] if idx < 26 else f"OP{idx+1}"
                text = str(option)
            options.append({"key": str(key).strip().upper(), "text": text.strip()})
    answer = (
        item.get("answer")
        or item.get("correct_answer")
        or item.get("kunci")
        or item.get("jawaban")
        or (options[0]["key"] if options else "A")
    )
    answer_key = str(answer).strip().upper()
    raw_metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    metadata = dict(raw_metadata) if raw_metadata else {}
    explanation = (
        item.get("explanation")
        or item.get("explanations")
        or item.get("explaination")
        or item.get("pembahasan")
        or metadata.get("explanation")
        or ""
    )
    explanation = explanation.strip()
    image_prompt_value = (
        item.get("image_prompt")
        or item.get("imagePrompt")
        or metadata.get("image_prompt")
        or metadata.get("imagePrompt")
    )
    if image_prompt_value:
        metadata["image_prompt"] = str(image_prompt_value).strip()
    statements_raw = item.get("statements") or item.get("pernyataan") or metadata.get("true_false_statements")
    tf_entries: list[dict] = []
    if isinstance(statements_raw, list):
        for entry in statements_raw:
            if isinstance(entry, dict):
                text_value = (entry.get("text") or entry.get("statement") or "").strip()
                if not text_value:
                    continue
                answer_value = (entry.get("answer") or entry.get("value") or "").strip().lower()
                if answer_value in {"benar", "true"}:
                    tf_entries.append({"text": text_value, "answer": "benar"})
                elif answer_value in {"salah", "false"}:
                    tf_entries.append({"text": text_value, "answer": "salah"})
    if tf_entries:
        metadata["true_false_statements"] = tf_entries
    raw_mode = (item.get("generator_mode") or item.get("question_mode") or item.get("question_type") or "").strip().lower()
    if raw_mode in {"truefalse", "true_false", "tf"} or tf_entries:
        resolved_mode = "truefalse"
    elif raw_mode in {"image", "gambar"}:
        resolved_mode = "image"
    elif raw_mode:
        resolved_mode = raw_mode
    else:
        resolved_mode = generator_mode
    if tf_entries and len(options) < 2:
        # Lengkapi opsi default agar backend tidak menolak true/false tanpa pilihan
        options = [
            {"key": "A", "text": "Pernyataan benar"},
            {"key": "B", "text": "Pernyataan salah"},
        ]
    if len(options) < 2:
        return None
    if answer_key not in {opt["key"] for opt in options}:
        answer_key = options[0]["key"]
    question_payload: dict = {
        "prompt": prompt,
        "topic": topic,
        "difficulty": difficulty,
        "options": options,
        "correct_key": answer_key,
        "explanation": explanation,
        "generator_mode": resolved_mode,
    }
    if metadata:
        metadata.setdefault("generator_mode", resolved_mode)
        question_payload["metadata"] = metadata
    inline_stimulus = item.get("stimulus")
    inline_meta = None
    if isinstance(inline_stimulus, dict):
        inline_meta = _build_stimulus_meta(
            inline_stimulus,
            fallback_title=inline_stimulus.get("title") or f"Stimulus {secrets.token_hex(2)}",
            forced_key=inline_stimulus.get("bundle_key"),
        )
    if inline_meta:
        question_payload["stimulus"] = inline_meta
    return question_payload


def _normalize_generated_questions(
    payload,
    fallback_topic: str,
    fallback_difficulty: str,
    generator_mode: str = "normal",
    target_children: Optional[int] = None,
) -> list[dict]:
    questions: list[dict] = []
    if isinstance(payload, dict):
        stimulus_payload = payload.get("stimulus")
        raw_items = payload.get("questions") or payload.get("soal") or []
    elif isinstance(payload, list):
        stimulus_payload = None
        raw_items = payload
    else:
        stimulus_payload = None
        raw_items = payload
    fallback_topic = (fallback_topic or "").strip()
    fallback_difficulty = (fallback_difficulty or "easy").strip().lower()
    child_target = target_children or MAX_GENERATED_CHILDREN
    child_target = max(MIN_GENERATED_CHILDREN, min(child_target, MAX_GENERATED_CHILDREN))
    if isinstance(stimulus_payload, list) and stimulus_payload:
        for idx, stim in enumerate(stimulus_payload, start=1):
            stim_meta = _build_stimulus_meta(stim, fallback_title=f"Stimulus {idx}", forced_key=stim.get("bundle_key"))
            rows = stim.get("questions") or stim.get("items") or []
            normalized_rows: list[dict] = []
            for row in rows:
                normalized = _build_generated_question(row, fallback_topic, fallback_difficulty, generator_mode)
                if normalized:
                    normalized_rows.append(normalized)
            if len(normalized_rows) < MIN_GENERATED_CHILDREN:
                continue
            normalized_rows = normalized_rows[: max(child_target, MIN_GENERATED_CHILDREN)]
            for question in normalized_rows:
                if stim_meta:
                    question["stimulus"] = stim_meta
                questions.append(question)
        return questions
    if not isinstance(raw_items, list):
        return questions
    for item in raw_items:
        normalized = _build_generated_question(item, fallback_topic, fallback_difficulty, generator_mode)
        if normalized:
            questions.append(normalized)
    return questions


def _encode_uploaded_image(file_storage) -> Optional[str]:
    if not file_storage or not getattr(file_storage, "filename", None):
        return None
    try:
        data = file_storage.read()
    except Exception:
        return None
    if not data:
        return None
    mimetype = getattr(file_storage, "mimetype", None) or "application/octet-stream"
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mimetype};base64,{encoded}"


@main_bp.before_request
def restrict_teacher_access():
    user = current_user()
    if user and user.get("role") == "staff":
        return redirect(url_for("attendance.dashboard"))


@main_bp.route("/profile/no-tester", methods=["POST"])
@login_required
def toggle_no_tester() -> Response:
    user = current_user()
    if not user:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    payload = request.get_json(silent=True) or {}
    raw_enabled = payload.get("enabled")
    if isinstance(raw_enabled, str):
        enabled = raw_enabled.strip().lower() in {"1", "true", "yes", "on"}
    else:
        enabled = bool(raw_enabled)

    try:
        success = update_no_tester_preference(user["id"], enabled)
    except Exception as exc:  # pragma: no cover - surfaces to UI
        return jsonify({"success": False, "message": str(exc)}), 500

    if not success:
        return jsonify({"success": False, "message": "User preference not updated"}), 400

    session_user = session.get("user") or {}
    session_user["no_tester_enabled"] = enabled
    session["user"] = session_user

    return jsonify({"success": True, "enabled": enabled})


@main_bp.route("/")
@login_required
def dashboard() -> Response:
    metrics = fetch_overview_metrics(window_days=7)
    chart_default_days = 30
    activity_default = fetch_daily_activity(days=chart_default_days)
    activity_long = fetch_daily_activity(days=365)
    incoming_activity_long = fetch_daily_activity(days=365, role="user")
    recent_questions = fetch_recent_questions(limit=8)
    top_users = fetch_top_users(limit=5)
    top_keywords = fetch_top_keywords(limit=10, days=30)

    chart_days: list[str] = []
    chart_values: list[int] = []
    for row in activity_default:
        day = row.get("day")
        if hasattr(day, "isoformat"):
            day_str = day.isoformat()
        else:
            day_str = str(day)
        chart_days.append(day_str)
        chart_values.append(int(row.get("messages") or 0))
    keyword_labels = [item["keyword"] for item in top_keywords]
    keyword_counts = [item["count"] for item in top_keywords]

    today_date = current_jakarta_time().date()

    def sum_period(activity_data, days: int) -> int:
        if not activity_data:
            return 0
        cutoff = today_date - timedelta(days=days - 1) if days > 1 else today_date
        total = 0
        for row in activity_data:
            day_value = row.get("day")
            if isinstance(day_value, datetime):
                day_value = day_value.date()
            elif isinstance(day_value, str):
                try:
                    day_value = datetime.fromisoformat(day_value).date()
                except ValueError:
                    continue
            if day_value and day_value >= cutoff:
                total += int(row.get("messages") or 0)
        return total

    messages_counts = {
        "today": sum_period(activity_long, 1),
        "week": sum_period(activity_long, 7),
        "month": sum_period(activity_long, 30),
        "year": sum_period(activity_long, 365),
        "all": metrics["total_messages"],
    }

    requests_counts = {
        "today": sum_period(incoming_activity_long, 1),
        "week": sum_period(incoming_activity_long, 7),
        "month": sum_period(incoming_activity_long, 30),
        "year": sum_period(incoming_activity_long, 365),
        "all": metrics["total_incoming_messages"],
    }

    aska_links = {
        "tele": os.getenv("ASKA_TELEGRAM_URL", "https://t.me/tanyaaska_bot"),
        "web": os.getenv("ASKA_WEB_URL", "https://aska.sdnsembar01.sch.id/"),
        "twitter": os.getenv("ASKA_TWITTER_URL", "https://twitter.com/tanyaaska_ai"),
    }

    return render_template(
        "dashboard.html",
        generated_at=current_jakarta_time(),
        metrics=metrics,
        recent_questions=recent_questions,
        top_users=top_users,
        chart_days=chart_days,
        chart_values=chart_values,
        chart_default_days=chart_default_days,
        keyword_labels=keyword_labels,
        keyword_counts=keyword_counts,
        requests_counts=requests_counts,
        messages_counts=messages_counts,
        aska_links=aska_links,
    )


@main_bp.route("/twitter/logs")
@login_required
def twitter_logs() -> Response:
    args: MultiDict = request.args
    page = max(1, int(args.get("page", 1)))
    range_key = args.get("range")

    start = _parse_date(args.get("start"))
    end = _parse_date(args.get("end"))
    now = current_jakarta_time()

    if range_key:
        key = range_key.lower()
        if key == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = now
        elif key == "24h":
            start = now - timedelta(hours=24)
            end = now
        elif key == "7d":
            start = now - timedelta(days=7)
            end = now
        elif key == "30d":
            start = now - timedelta(days=30)
            end = now
        elif key == "90d":
            start = now - timedelta(days=90)
            end = now
        elif key == "all":
            start = None
            end = None

    role = args.get("role") or None
    if role not in {"user", "aska"}:
        role = None
    search = args.get("search") or None
    user_id = args.get("user_id")
    user_id = int(user_id) if user_id else None

    filters = ChatFilters(
        start=start,
        end=end,
        role=role,
        search=search,
        user_id=user_id,
        topic="twitter",
    )

    topic_supported = chat_topic_available()

    offset = (page - 1) * TWITTER_PAGE_SIZE
    if topic_supported:
        records, total = fetch_chat_logs(filters=filters, limit=TWITTER_PAGE_SIZE, offset=offset)
    else:
        records, total = [], 0
    total_pages = max(1, ceil(total / TWITTER_PAGE_SIZE)) if total else 1

    runtime = _load_twitter_runtime()
    bot_user_id = runtime.get("bot_user_id")
    overview = fetch_twitter_overview(window_days=7, bot_user_id=bot_user_id)
    activity_rows = fetch_twitter_activity(days=45)
    activity_days: list[str] = []
    activity_mentions: list[int] = []
    activity_replies: list[int] = []
    for row in activity_rows:
        day_value = row.get("day")
        if isinstance(day_value, datetime):
            label = day_value.date().isoformat()
        elif hasattr(day_value, "isoformat"):
            label = day_value.isoformat()
        else:
            label = str(day_value)
        activity_days.append(label)
        activity_mentions.append(int(row.get("mentions") or 0))
        activity_replies.append(int(row.get("replies") or 0))

    top_users = fetch_twitter_top_users(limit=8)
    worker_logs = fetch_twitter_worker_logs(limit=120)

    autopost_page_total = 0
    for row in records:
        is_autopost = bool(bot_user_id and row.get("role") == "aska" and row.get("user_id") == bot_user_id)
        row["is_autopost"] = is_autopost
        row["is_reply"] = row.get("role") == "aska" and not is_autopost
        row["is_mention"] = row.get("role") == "user"
        if is_autopost:
            autopost_page_total += 1

    export_url = None
    if topic_supported:
        export_params: dict = {"topic": "twitter"}
        if start:
            try:
                export_params["start"] = start.strftime("%Y-%m-%d")
            except Exception:
                export_params["start"] = str(start)
        if end:
            try:
                export_params["end"] = end.strftime("%Y-%m-%d")
            except Exception:
                export_params["end"] = str(end)
        if role:
            export_params["role"] = role
        if search:
            export_params["search"] = search
        if user_id:
            export_params["user_id"] = user_id
        export_url = url_for("main.export_chats", **export_params)

    if not range_key and not start and not end:
        range_key = "all"

    return render_template(
        "twitter_logs.html",
        overview=overview,
        records=records,
        total=total,
        page=page,
        total_pages=total_pages,
        filters=filters,
        selected_range=range_key,
        activity_days=activity_days,
        activity_mentions=activity_mentions,
        activity_replies=activity_replies,
        top_users=top_users,
        runtime=runtime,
        export_url=export_url,
        topic_supported=topic_supported,
        worker_logs=worker_logs,
        page_autopost_total=autopost_page_total,
    )


@main_bp.route("/chats")
@login_required
def chats() -> Response:
    args: MultiDict = request.args
    page = max(1, int(args.get("page", 1)))
    start = _parse_date(args.get("start"))
    end = _parse_date(args.get("end"))
    role = args.get("role") or None
    search = args.get("search") or None
    user_id = args.get("user_id")
    user_id = int(user_id) if user_id else None

    filters = ChatFilters(start=start, end=end, role=role, search=search, user_id=user_id)
    offset = (page - 1) * PAGE_SIZE

    records, total = fetch_chat_logs(filters=filters, limit=PAGE_SIZE, offset=offset)
    total_pages = max(1, ceil(total / PAGE_SIZE))

    export_params = {}
    if start:
        export_params["start"] = start.strftime("%Y-%m-%d")
    if end:
        export_params["end"] = end.strftime("%Y-%m-%d")
    if role:
        export_params["role"] = role
    if search:
        export_params["search"] = search
    if user_id:
        export_params["user_id"] = user_id

    export_url = url_for("main.export_chats", **export_params)

    return render_template(
        "chats.html",
        records=records,
        total=total,
        page=page,
        total_pages=total_pages,
        filters=filters,
        export_url=export_url,
    )


@main_bp.route("/chats/thread/")
@login_required
def chat_thread_empty() -> Response:
    users_list = fetch_all_chat_users()
    if users_list:
        return redirect(url_for("main.chat_thread", user_id=users_list[0]["user_id"]))
    flash("No chats found.", "info")
    return redirect(url_for("main.chats"))


@main_bp.route("/chats/thread/<user_id>")
@login_required
def chat_thread(user_id: str) -> Response:
    try:
        user_id_int = int(user_id)
    except ValueError:
        flash("User ID tidak valid.", "danger")
        return redirect(url_for("main.chats"))

    messages = fetch_conversation_thread(user_id=user_id_int, limit=400)
    users_list = fetch_all_chat_users()

    # If user has no messages, but other chats exist, redirect to the first user
    if not messages and users_list:
        flash("Pengguna ini belum memiliki riwayat percakapan.", "info")
        return redirect(url_for("main.chat_thread", user_id=users_list[0]["user_id"]))
    
    # If no messages and no other users, redirect to chat list
    if not messages:
        return redirect(url_for("main.chats"))

    user = {
        "user_id": user_id_int,
        "username": messages[0].get("username") or "Unknown",
    }
    return render_template(
        "chat_thread.html", messages=messages, user=user, users_list=users_list
    )



@main_bp.route("/bullying-reports")
@login_required
def bullying_reports() -> Response:
    args: MultiDict = request.args
    raw_status = (args.get("status") or "").strip().lower() or None
    if raw_status and raw_status not in BULLYING_STATUSES:
        flash("Status filter tidak dikenal.", "warning")
        return redirect(url_for("main.bullying_reports"))

    highlight_param = args.get("highlight")
    highlight_id = None
    if highlight_param:
        try:
            highlight_id = int(highlight_param)
        except ValueError:
            highlight_id = None

    page = max(1, int(args.get("page", 1)))
    limit = REPORT_PAGE_SIZE
    offset = (page - 1) * limit

    try:
        records, total = fetch_bullying_reports(status=raw_status, limit=limit, offset=offset)
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("main.bullying_reports"))

    summary = fetch_bullying_summary()
    total_pages = max(1, ceil(total / limit))

    return render_template(
        "bullying_reports.html",
        records=records,
        summary=summary,
        filter_status=raw_status,
        page=page,
        total_pages=total_pages,
        total=total,
        per_page=limit,
        highlight_id=highlight_id,
    )


@main_bp.route("/bullying-reports/<int:report_id>")
@login_required
def bullying_report_detail(report_id: int) -> Response:
    report = fetch_bullying_report_detail(report_id)
    if not report:
        flash("Laporan tidak ditemukan.", "warning")
        return redirect(url_for("main.bullying_reports"))
    return render_template("bullying_report_detail.html", report=report)


@main_bp.route("/bullying-reports/bulk-status", methods=["POST"])
@role_required("admin", "staff")
def bulk_update_bullying_status() -> Response:
    data = request.get_json()
    report_ids = data.get("report_ids")
    status = data.get("status")
    user = current_user()
    updated_by = user.get("full_name") or user.get("email") if user else None

    if not report_ids or not isinstance(report_ids, list):
        return jsonify({"success": False, "message": "Invalid report IDs"}), 400

    if status not in BULLYING_STATUSES and status != "undo":
        return jsonify({"success": False, "message": "Invalid status"}), 400

    try:
        if status == "undo":
            bulk_update_bullying_report_status(report_ids, "pending", updated_by)
        else:
            bulk_update_bullying_report_status(report_ids, status, updated_by)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@main_bp.route("/bullying-reports/<int:report_id>/status", methods=["POST"])
@role_required("admin", "staff")
def update_bullying_status(report_id: int) -> Response:
    action = (request.form.get("action") or "save").strip().lower()
    status_value = request.form.get("status")
    notes = request.form.get("notes") or ""
    assigned_to = request.form.get("assigned_to")
    due_at_raw = request.form.get("due_at")
    escalate_values = request.form.getlist("escalate")
    next_url = request.form.get("next") or url_for("main.bullying_reports")

    user = current_user()
    updated_by = None
    if user:
        updated_by = user.get("full_name") or user.get("email")

    existing = fetch_bullying_report_basic(report_id)
    if not existing:
        flash("Laporan tidak ditemukan atau sudah dihapus.", "warning")
        return redirect(next_url)

    if action == "reopen":
        status_value = "pending"
    elif status_value:
        status_value = status_value.strip().lower()

    escalated_param = None
    if escalate_values:
        escalated_param = escalate_values[-1].lower() in {"on", "1", "true"}

    due_at_param = due_at_raw if due_at_raw is not None else None

    if status_value == "spam":
        escalated_param = False
        due_at_param = ""
        assigned_to = ""

    try:
        updated = update_bullying_report_status(
            report_id,
            status=status_value,
            notes=notes,
            updated_by=updated_by,
            assigned_to=assigned_to,
            due_at=due_at_param,
            escalated=escalated_param,
        )
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(next_url)

    if updated:
        message = "Status laporan berhasil diperbarui."
        if action == "reopen":
            message = "Laporan dibuka kembali dan siap ditindaklanjuti."
        flash(message, "success")
    else:
        flash("Tidak ada perubahan yang disimpan.", "info")

    return redirect(next_url)


@main_bp.route("/corruption-reports")
@login_required
def corruption_reports() -> Response:
    args: MultiDict = request.args
    raw_status = (args.get("status") or "").strip().lower() or None
    if raw_status and raw_status not in CORRUPTION_STATUSES:
        flash("Status filter tidak dikenal.", "warning")
        return redirect(url_for("main.corruption_reports"))

    page = max(1, int(args.get("page", 1)))
    limit = REPORT_PAGE_SIZE
    offset = (page - 1) * limit

    try:
        records, total = fetch_corruption_reports(status=raw_status, limit=limit, offset=offset)
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("main.corruption_reports"))

    summary = fetch_corruption_summary()
    total_pages = max(1, ceil(total / limit))

    return render_template(
        "corruption_reports.html",
        records=records,
        summary=summary,
        filter_status=raw_status,
        page=page,
        total_pages=total_pages,
        total=total,
        per_page=limit,
    )


@main_bp.route("/corruption-reports/<int:report_id>")
@login_required
def corruption_report_detail(report_id: int) -> Response:
    report = fetch_corruption_report_detail(report_id)
    if not report:
        flash("Laporan korupsi tidak ditemukan.", "warning")
        return redirect(url_for("main.corruption_reports"))
    return render_template("corruption_report_detail.html", report=report)


@main_bp.route("/corruption-reports/bulk-status", methods=["POST"])
@role_required("admin", "staff")
def bulk_update_corruption_status() -> Response:
    data = request.get_json()
    report_ids = data.get("report_ids")
    status = data.get("status")
    user = current_user()
    updated_by = user.get("full_name") or user.get("email") if user else None

    if not report_ids or not isinstance(report_ids, list):
        return jsonify({"success": False, "message": "Invalid report IDs"}), 400

    if status not in CORRUPTION_STATUSES and status != "undo":
        return jsonify({"success": False, "message": "Invalid status"}), 400

    try:
        if status == "undo":
            bulk_update_corruption_report_status(report_ids, "open", updated_by)
        else:
            bulk_update_corruption_report_status(report_ids, status, updated_by)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@main_bp.route("/corruption-reports/<int:report_id>/status", methods=["POST"])
@role_required("admin", "staff")
def update_corruption_status(report_id: int) -> Response:
    action = (request.form.get("action") or "save").strip().lower()
    status_value = request.form.get("status")
    next_url = request.form.get("next") or url_for("main.corruption_reports")

    user = current_user()
    updated_by = user.get("full_name") or user.get("email") if user else None

    if action == "reopen":
        status_value = "open"
    
    if not status_value:
        flash("Tidak ada status yang dipilih.", "warning")
        return redirect(next_url)

    try:
        updated = update_corruption_report_status(
            report_id,
            status=status_value,
            updated_by=updated_by,
        )
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(next_url)

    if updated:
        flash("Status laporan korupsi berhasil diperbarui.", "success")
    else:
        flash("Gagal memperbarui status laporan korupsi.", "danger")

    return redirect(next_url)


@main_bp.route("/psych-reports")
@login_required
def psych_reports() -> Response:
    args: MultiDict = request.args
    raw_status = (args.get("status") or "").strip().lower() or None
    raw_severity = (args.get("severity") or "").strip().lower() or None

    if raw_status and raw_status not in PSYCH_STATUSES:
        flash("Status filter tidak dikenal.", "warning")
        return redirect(url_for("main.psych_reports"))

    if raw_severity and raw_severity not in ('general', 'elevated', 'critical'):
        flash("Severity filter tidak dikenal.", "warning")
        return redirect(url_for("main.psych_reports"))

    page = max(1, int(args.get("page", 1)))
    limit = REPORT_PAGE_SIZE
    offset = (page - 1) * limit

    try:
        records, total = fetch_psych_reports(
            status=raw_status,
            severity=raw_severity,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("main.psych_reports"))

    summary = fetch_psych_summary()
    total_pages = max(1, ceil(total / limit))
    severity_counts = summary.get("severity", {})

    return render_template(
        "psych_reports.html",
        records=records,
        summary=summary,
        severity_counts=severity_counts,
        filter_status=raw_status,
        filter_severity=raw_severity,
        page=page,
        total_pages=total_pages,
        total=total,
        per_page=limit,
    )


@main_bp.route("/psych-reports/user/<int:user_id>")
@login_required
def psych_report_user_detail(user_id: int) -> Response:
    records = fetch_psych_group_reports(user_id=user_id)
    if not records:
        flash("Tidak ada laporan konseling yang ditemukan untuk siswa ini.", "warning")
        return redirect(url_for("main.psych_reports"))

    return render_template(
        "psych_report_detail.html",
        records=records,
        user={
            "user_id": user_id,
            "username": records[0].get("username") or "Anon",
        },
    )


@main_bp.route("/psych-reports/report/<int:report_id>")
@login_required
def psych_report_single_detail(report_id: int) -> Response:
    records = fetch_psych_group_reports(report_id=report_id)
    if not records:
        flash("Laporan konseling tidak ditemukan atau sudah dihapus.", "warning")
        return redirect(url_for("main.psych_reports"))

    user_id = records[0].get("user_id")
    if user_id:
        return redirect(url_for("main.psych_report_user_detail", user_id=user_id))

    return render_template(
        "psych_report_detail.html",
        records=records,
        user={
            "user_id": None,
            "username": records[0].get("username") or "Anon",
        },
    )


@main_bp.route("/psych-reports/bulk-status", methods=["POST"])
@role_required("admin", "editor")
def bulk_update_psych_status() -> Response:
    data = request.get_json()
    report_ids = data.get("report_ids")
    status = data.get("status")
    user = current_user()
    updated_by = user.get("full_name") or user.get("email") if user else None

    if not report_ids or not isinstance(report_ids, list):
        return jsonify({"success": False, "message": "Invalid report IDs"}), 400

    if status not in PSYCH_STATUSES and status != "undo":
        return jsonify({"success": False, "message": "Invalid status"}), 400

    try:
        if status == "undo":
            bulk_update_psych_report_status(report_ids, "open", updated_by)
        else:
            bulk_update_psych_report_status(report_ids, status, updated_by)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@main_bp.route("/psych-reports/<int:report_id>/status", methods=["POST"])
@role_required("admin", "editor")
def update_psych_status(report_id: int) -> Response:
    status_value = (request.form.get("status") or "").strip().lower()
    next_url = request.form.get("next") or url_for("main.psych_reports")

    if status_value not in PSYCH_STATUSES:
        flash("Status laporan konseling tidak dikenal.", "warning")
        return redirect(next_url)

    user = current_user()
    updated_by = None
    if user:
        updated_by = user.get("full_name") or user.get("email")

    try:
        updated = update_psych_report_status(
            report_id,
            status_value,
            updated_by=updated_by,
        )
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(next_url)

    if updated:
        flash("Status laporan konseling berhasil diubah.", "success")
    else:
        flash("Laporan konseling tidak ditemukan atau tidak ada perubahan.", "info")

    return redirect(next_url)


@main_bp.route("/api/activity")
@login_required
def activity_api() -> Response:
    days = int(request.args.get("days", 14))
    activity = fetch_daily_activity(days=days)
    payload = [
        {
            "day": (row["day"].isoformat() if hasattr(row.get("day"), "isoformat") else str(row.get("day"))),
            "messages": int(row.get("messages") or 0),
        }
        for row in activity
    ]
    return jsonify(payload)


@main_bp.route("/chats/export")
@login_required
def export_chats() -> Response:
    args: MultiDict = request.args
    start = _parse_date(args.get("start"))
    end = _parse_date(args.get("end"))
    role = args.get("role") or None
    search = args.get("search") or None
    user_id = args.get("user_id")
    user_id = int(user_id) if user_id else None
    topic = args.get("topic") or None

    filters = ChatFilters(start=start, end=end, role=role, search=search, user_id=user_id, topic=topic)

    records, _ = fetch_chat_logs(filters=filters, limit=5000, offset=0)

    from io import StringIO
    import csv

    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "created_at", "user_id", "username", "role", "topic", "response_time_ms", "text"])
    for row in records:
        created_at = row.get("created_at")
        if created_at:
            created_at = to_jakarta(created_at)
            try:
                created_at = created_at.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                created_at = str(created_at)
        writer.writerow(
            [
                row.get("id"),
                created_at,
                row.get("user_id"),
                row.get("username"),
                row.get("role"),
                row.get("topic"),
                row.get("response_time_ms"),
                (row.get("text") or "").replace("\n", " "),
            ]
        )

    buffer.seek(0)
    filename = f"chat_logs_export_{current_jakarta_time():%Y%m%d_%H%M%S}.csv"
    response = Response(buffer.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response


# --- Latihan TKA admin routes -----------------------------------------------


@main_bp.route("/latihan-tka")
@login_required
@role_required("admin")
def latihan_tka_bank():
    subjects = fetch_tka_subjects(include_inactive=True)
    return render_template(
        "latihan_tka.html",
        subjects=subjects,
        grade_labels=GRADE_LABELS,
        section_templates=TKA_SECTION_TEMPLATES,
        default_duration=DEFAULT_TKA_COMPOSITE_DURATION,
    )


@main_bp.route("/latihan-tka/buat-soal")
@login_required
@role_required("admin")
def latihan_tka_manual():
    subjects = fetch_tka_subjects(include_inactive=True)
    tests = fetch_tka_tests()
    return render_template(
        "latihan_tka_manual.html",
        subjects=subjects,
        tests=tests,
        grade_labels=GRADE_LABELS,
        section_templates=TKA_SECTION_TEMPLATES,
        default_duration=DEFAULT_TKA_COMPOSITE_DURATION,
    )


@main_bp.route("/latihan-tka/tests-ui", methods=["GET", "POST"])
@login_required
@role_required("admin")
def latihan_tka_tests():
    test_message = None
    test_message_tone = "info"
    mapel_message = None
    mapel_message_tone = "muted"
    selected_test_id = request.args.get("test_id", type=int)
    if request.method == "POST":
        delete_test_id = request.form.get("delete_test_id", type=int)
        if delete_test_id:
            try:
                if delete_tka_test(delete_test_id):
                    flash("Tes berhasil dihapus.", "success")
                else:
                    flash("Tes tidak ditemukan.", "danger")
            except Exception as exc:
                current_app.logger.error("Gagal menghapus tes TKA %s: %s", delete_test_id, exc)
                flash("Gagal menghapus tes.", "danger")
            return redirect(url_for("main.latihan_tka_tests"))
        delete_mapel_id = request.form.get("delete_mapel_id", type=int)
        if delete_mapel_id:
            try:
                if delete_tka_mapel(delete_mapel_id):
                    flash("Mapel berhasil dihapus.", "success")
                else:
                    flash("Mapel belum tersedia.", "danger")
            except Exception as exc:
                current_app.logger.error("Gagal menghapus mapel %s: %s", delete_mapel_id, exc)
                flash("Gagal menghapus mapel.", "danger")
            return redirect(url_for("main.latihan_tka_tests"))
        delete_test_subject_id = request.form.get("delete_test_subject_id", type=int)
        if delete_test_subject_id:
            form_test_id = request.form.get("delete_test_subject_test_id", type=int)
            redirect_args = {}
            if form_test_id:
                redirect_args["test_id"] = form_test_id
            if not form_test_id or not delete_test_subject_id:
                flash("Pilih tes terlebih dahulu sebelum menghapus mapel.", "danger")
                return redirect(url_for("main.latihan_tka_tests", **redirect_args))
            try:
                if delete_tka_test_subject(form_test_id, delete_test_subject_id):
                    flash("Mapel dihapus dari tes.", "success")
                else:
                    flash("Mapel tes tidak ditemukan.", "danger")
            except Exception as exc:
                current_app.logger.error("Gagal menghapus mapel tes %s/%s: %s", form_test_id, delete_test_subject_id, exc)
                flash("Gagal menghapus mapel tes.", "danger")
            return redirect(url_for("main.latihan_tka_tests", **redirect_args))
        elif request.form.get("add_subject_form"):
            form_test_id = request.form.get("form_test_id", type=int)
            form_mapel_id = request.form.get("form_mapel_id", type=int)
            total_questions = request.form.get("form_total", type=int)
            pg_count = request.form.get("form_pg", type=int) or 0
            tf_count = request.form.get("form_tf", type=int) or 0
            topics_raw = (request.form.get("form_topics") or "").strip()
            redirect_args = {}
            if form_test_id:
                redirect_args["test_id"] = form_test_id
            if not form_test_id or not form_mapel_id:
                flash("Pilih tes dan mapel terlebih dahulu.", "danger")
                return redirect(url_for("main.latihan_tka_tests", **redirect_args))
            if not total_questions or total_questions <= 0:
                flash("Target soal mapel harus lebih dari 0.", "danger")
                return redirect(url_for("main.latihan_tka_tests", **redirect_args))
            topic_entries = []
            if topics_raw:
                for chunk in topics_raw.split(","):
                    part = chunk.strip()
                    if not part:
                        continue
                    match = re.match(r"^(.*)\((\d+)\)$", part)
                    if match:
                        topic_entries.append({"name": match.group(1).strip(), "count": int(match.group(2))})
                    else:
                        topic_entries.append({"name": part, "count": 0})
            try:
                mapel_record = fetch_tka_mapel(form_mapel_id)
                if not mapel_record:
                    flash("Mapel belum tersedia.", "danger")
                    return redirect(url_for("main.latihan_tka_tests", **redirect_args))
                test_record = fetch_tka_test(form_test_id)
                if not test_record:
                    flash("Tes tidak ditemukan.", "danger")
                    return redirect(url_for("main.latihan_tka_tests"))
                mapel_grade = (mapel_record.get("grade_level") or "").strip().lower() or None
                test_grade = (test_record.get("grade_level") or "").strip().lower() or None
                if not mapel_grade:
                    flash("Mapel belum memiliki jenjang.", "danger")
                    return redirect(url_for("main.latihan_tka_tests", **redirect_args))
                if test_grade and test_grade != mapel_grade:
                    label_mapel = GRADE_LABELS.get(mapel_grade, mapel_grade.upper())
                    label_test = GRADE_LABELS.get(test_grade, test_grade.upper())
                    flash(f"Tes ini khusus jenjang {label_test}. Mapel yang dipilih berjenjang {label_mapel}.", "danger")
                    return redirect(url_for("main.latihan_tka_tests", **redirect_args))
                if not test_grade:
                    set_tka_test_grade_level(form_test_id, mapel_grade)
                formats_payload = [
                    {"question_type": "multiple_choice", "question_count_target": max(0, pg_count)},
                    {"question_type": "true_false", "question_count_target": max(0, tf_count)},
                ]
                create_tka_test_subject(
                    test_id=form_test_id,
                    total=total_questions,
                    mapel_id=form_mapel_id,
                    formats=formats_payload,
                    topics=topic_entries,
                )
            except ValueError as exc:
                flash(str(exc), "danger")
                return redirect(url_for("main.latihan_tka_tests", **redirect_args))
            except Exception as exc:
                current_app.logger.error("Gagal menambah mapel ke tes melalui form: %s", exc)
                flash("Gagal menambahkan mapel ke tes.", "danger")
                return redirect(url_for("main.latihan_tka_tests", **redirect_args))
            flash("Mapel berhasil disimpan ke tes.", "success")
            return redirect(url_for("main.latihan_tka_tests", **redirect_args))
        elif request.form.get("mapel_form"):
            name = (request.form.get("mapel_name") or "").strip()
            grade_level = (request.form.get("mapel_grade_level") or "").strip().lower()
            description = (request.form.get("mapel_description") or "").strip()
            is_active = bool(request.form.get("mapel_is_active"))
            if not name:
                mapel_message = "Nama mapel wajib diisi."
                mapel_message_tone = "danger"
            else:
                try:
                    create_tka_mapel(
                        name=name,
                        grade_level=grade_level or DEFAULT_TKA_GRADE_LEVEL,
                        description=description or None,
                        is_active=is_active,
                    )
                except ValueError as exc:
                    mapel_message = str(exc)
                    mapel_message_tone = "danger"
                except Exception as exc:
                    current_app.logger.error("Gagal menyimpan mapel TKA: %s", exc)
                    mapel_message = "Gagal menyimpan mapel."
                    mapel_message_tone = "danger"
                else:
                    flash("Mapel berhasil disimpan.", "success")
                    return redirect(url_for("main.latihan_tka_tests"))
        else:
            name = (request.form.get("name") or "").strip()
            grade_level = (request.form.get("grade_level") or "").strip().lower()
            duration_raw = request.form.get("duration_minutes")
            is_active = bool(request.form.get("is_active"))
            try:
                duration_minutes = int(duration_raw)
            except (TypeError, ValueError):
                duration_minutes = DEFAULT_TKA_COMPOSITE_DURATION
            if not name:
                test_message = "Nama tes wajib diisi."
                test_message_tone = "danger"
            else:
                try:
                    create_tka_test(name=name, grade_level=grade_level or DEFAULT_TKA_GRADE_LEVEL, duration_minutes=duration_minutes, is_active=is_active)
                    flash("Tes berhasil disimpan.", "success")
                    return redirect(url_for("main.latihan_tka_tests"))
                except ValueError as exc:
                    test_message = str(exc)
                    test_message_tone = "danger"
                except Exception as exc:
                    current_app.logger.error("Gagal menyimpan tes TKA: %s", exc)
                    test_message = "Gagal menyimpan tes. Coba lagi."
                    test_message_tone = "danger"
    mapel_list = fetch_tka_mapel_list()
    raw_tests = fetch_tka_tests()
    tests = []
    selected_test = None
    test_subjects_map: Dict[int, List[Dict[str, Any]]] = {}
    for test in raw_tests:
        record = dict(test)
        for key in ("created_at", "updated_at"):
            value = record.get(key)
            if hasattr(value, "isoformat"):
                record[key] = value.isoformat()
        if selected_test_id and record.get("id") == selected_test_id:
            selected_test = record
        try:
            test_subjects_map[record["id"]] = fetch_tka_test_subjects(record["id"])
        except Exception as exc:
            current_app.logger.error("Gagal memuat mapel tes %s: %s", record["id"], exc)
            test_subjects_map[record["id"]] = []
        tests.append(record)
    if tests and not selected_test_id:
        selected_test_id = tests[0]["id"]
    if selected_test_id and not selected_test:
        selected_test = next((item for item in tests if item.get("id") == selected_test_id), None)
    selected_subjects = test_subjects_map.get(selected_test_id, []) if selected_test_id else []
    return render_template(
        "latihan_tka_tests.html",
        tests=tests,
        mapel_list=mapel_list,
        test_message=test_message,
        test_message_tone=test_message_tone,
        mapel_message=mapel_message,
        mapel_message_tone=mapel_message_tone,
        selected_test_id=selected_test_id,
        selected_test=selected_test,
        grade_labels=GRADE_LABELS,
        initial_test_subjects=test_subjects_map,
        selected_subjects=selected_subjects,
    )


@main_bp.route("/latihan-tka/generator", defaults={"mode": "lite"})
@main_bp.route("/latihan-tka/generator/<string:mode>")
@login_required
@role_required("admin")
def latihan_tka_generator_page(mode: str):
    normalized_mode = (mode or "lite").strip().lower()
    if normalized_mode not in {"lite", "pro"}:
        normalized_mode = "lite"
    template_name = (
        "latihan_tka_generator_pro.html"
        if normalized_mode == "pro"
        else "latihan_tka_generator_lite.html"
    )
    return render_template(
        template_name,
        grade_labels=GRADE_LABELS,
        section_templates=TKA_SECTION_TEMPLATES,
        default_duration=DEFAULT_TKA_COMPOSITE_DURATION,
        generator_mode=normalized_mode,
    )


@main_bp.route("/latihan-tka/hasil")
@login_required
@role_required("admin")
def latihan_tka_results():
    subjects = fetch_tka_subjects(include_inactive=True)
    return render_template("latihan_tka_results.html", subjects=subjects, grade_labels=GRADE_LABELS)


@main_bp.route("/latihan-tka/subjects", methods=["POST"])
@login_required
@role_required("admin")
def latihan_tka_create_subject():
    payload = request.get_json(silent=True) or {}
    try:
        subject = create_tka_subject(
            name=payload.get("name"),
            description=payload.get("description"),
            time_limit_minutes=int(payload.get("time_limit_minutes") or 15),
            difficulty_mix=payload.get("difficulty_mix"),
            is_active=bool(payload.get("is_active", True)),
            grade_level=payload.get("grade_level"),
        )
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as exc:
        main_bp.logger.error("Gagal membuat mapel TKA: %s", exc)
        return jsonify({"success": False, "message": "Gagal menyimpan mapel."}), 500
    return jsonify({"success": True, "subject": subject})


@main_bp.route("/latihan-tka/questions")
@login_required
@role_required("admin")
def latihan_tka_questions():
    subject_id = request.args.get("subject_id", type=int)
    test_subject_id = request.args.get("test_subject_id", type=int)
    mapel_id = request.args.get("mapel_id", type=int)
    test_id = request.args.get("test_id", type=int)
    if not subject_id and not test_subject_id and not mapel_id and not test_id:
        return jsonify({"success": False, "message": "Pilih tes atau mapel terlebih dahulu."}), 400
    difficulty = request.args.get("difficulty") or None
    topic = request.args.get("topic") or None
    questions = fetch_tka_questions(
        subject_id=subject_id,
        test_subject_id=test_subject_id,
        test_id=test_id,
        mapel_id=mapel_id,
        difficulty=difficulty or None,
        topic=topic or None,
    )
    return jsonify({"success": True, "questions": questions})


@main_bp.route("/latihan-tka/stimulus")
@login_required
@role_required("admin")
def latihan_tka_stimulus():
    mapel_id = request.args.get("mapel_id", type=int)
    test_id = request.args.get("test_id", type=int)
    if not mapel_id and not test_id:
        return jsonify({"success": False, "message": "mapel_id atau test_id wajib diisi."}), 400
    stimulus = fetch_tka_stimulus_list(mapel_id=mapel_id, test_id=test_id)
    return jsonify({"success": True, "stimulus": stimulus})


@main_bp.route("/latihan-tka/stimulus/create", methods=["POST"])
@login_required
@role_required("admin")
def latihan_tka_create_stimulus():
    data = request.get_json(silent=True) or {}
    subject_id = data.get("subject_id")
    mapel_id = data.get("mapel_id")
    test_id = data.get("test_id", 22)
    try:
        subject_id = int(subject_id)
    except (TypeError, ValueError):
        subject_id = None
    try:
        mapel_id = int(mapel_id)
    except (TypeError, ValueError):
        mapel_id = None
    try:
        test_id = int(test_id)
    except (TypeError, ValueError):
        test_id = 22
    if not mapel_id:
        return jsonify({"success": False, "message": "mapel_id wajib diisi."}), 400
    title = (data.get("title") or "").strip()
    narrative = (data.get("narrative") or "").strip()
    image_prompt = (data.get("image_prompt") or "").strip() or None
    image_data = data.get("image_data") or data.get("image_url")
    user = current_user() or {}
    created_by = user.get("id")
    try:
        stimulus = create_tka_stimulus(
            mapel_id=mapel_id,
            test_id=test_id,
            subject_id=subject_id,
            title=title,
            narrative=narrative or None,
            image_data=image_data or None,
            image_prompt=image_prompt,
            created_by=created_by,
        )
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as exc:
        current_app.logger.error("Gagal menyimpan stimulus TKA: %s", exc)
        return jsonify({"success": False, "message": "Gagal menyimpan stimulus."}), 500
    return jsonify({"success": True, "stimulus": stimulus})


@main_bp.route("/latihan-tka/stimulus/generate", methods=["POST"])
@login_required
@role_required("admin")
def latihan_tka_generate_stimulus():
    data = request.get_json(silent=True) or {}
    subject_id = data.get("subject_id")
    mapel_id = data.get("mapel_id")
    test_id = data.get("test_id", 22)
    try:
        subject_id = int(subject_id)
    except (TypeError, ValueError):
        subject_id = None
    try:
        mapel_id = int(mapel_id)
    except (TypeError, ValueError):
        mapel_id = None
    try:
        test_id = int(test_id)
    except (TypeError, ValueError):
        test_id = 22
    if not subject_id and mapel_id:
        try:
            subject_id = ensure_tka_subject_from_mapel(mapel_id)
        except Exception:
            subject_id = None
    topic = (data.get("topic") or "").strip()
    tone = (data.get("tone") or "narasi").strip().lower()
    include_image = bool(data.get("include_image"))
    subject = fetch_tka_subject(subject_id)
    if not subject:
        current_app.logger.warning(
            "[TKA][generate] subjek tidak ditemukan | subject_id=%s test_id=%s test_subject_id=%s payload=%s",
            subject_id,
            test_id,
            test_subject_id,
            {
                "topic": topic,
                "difficulty": difficulty,
                "generator_mode": generator_mode,
            },
        )
        return jsonify({"success": False, "message": "Mapel belum tersedia."}), 404
    if not topic:
        return jsonify({"success": False, "message": "Topik stimulus wajib diisi."}), 400
    chain = _get_tka_ai_chain()
    if chain is None:
        return jsonify({"success": False, "message": "Model ASKA belum siap. Coba sebentar lagi."}), 503
    grade_descriptor = GRADE_LEVEL_HINTS.get(subject.get("grade_level"))
    grade_clause = f" Sesuaikan konteks dengan {grade_descriptor}." if grade_descriptor else ""
    image_clause = (
        " Sertakan field `image_prompt` yang mendeskripsikan ilustrasi sederhana terkait cerita."
        if include_image
        else " Field `image_prompt` boleh dikosongkan jika tidak diperlukan."
    )
    prompt = (
        f"Buat 1 stimulus bacaan dengan judul singkat dan narasi beberapa paragraf untuk mapel {subject['name']}. "
        f"Topik utama: {topic}.{grade_clause} Narasi harus runtut, menarik, dan memberikan konteks untuk 3-5 pertanyaan turunan."
        f" Gaya penulisan: {tone}. {image_clause} "
        "Gunakan bahasa Indonesia formal yang ringan. Format keluaran hanya JSON:\n"
        '{"title":"...","narrative":"...","image_prompt":"..."}'
    )
    try:
        result = chain.invoke(prompt)
        if hasattr(result, "content"):
            raw_output = result.content
        elif isinstance(result, dict) and "answer" in result:
            raw_output = result["answer"]
        else:
            raw_output = str(result)
        cleaned = _strip_code_fences(str(raw_output))
        cleaned = _repair_bare_fields(cleaned)
        normalized = _repair_trailing_commas(
            _close_unbalanced_json(
                _repair_trailing_commas(_repair_unterminated_strings(_normalize_jsonish_text(cleaned)))
            )
        )
        parsed = json.loads(normalized)
    except json.JSONDecodeError:
        try:
            fallback_payload = _extract_json_payload(cleaned)
            normalized = _repair_trailing_commas(
                _close_unbalanced_json(
                    _repair_trailing_commas(_repair_unterminated_strings(_normalize_jsonish_text(fallback_payload)))
                )
            )
            parsed = json.loads(normalized)
        except Exception as exc:
            preview = cleaned.strip().replace("```", "")[:300]
            current_app.logger.error("Stimulus generator output tidak valid: %s | error=%s", cleaned, exc)
            return jsonify({"success": False, "message": f"ASKA mengirim format tidak dikenal. Cuplikan: {preview}"}), 422
    except Exception as exc:
        current_app.logger.error("Generator stimulus error: %s", exc)
        return jsonify({"success": False, "message": "ASKA gagal menulis stimulus."}), 500
    if isinstance(parsed, list):
        parsed = parsed[0] if parsed else {}
    if not isinstance(parsed, dict):
        return jsonify({"success": False, "message": "ASKA belum menghasilkan stimulus valid."}), 422
    stimulus = {
        "title": (parsed.get("title") or "").strip(),
        "narrative": (parsed.get("narrative") or parsed.get("story") or "").strip(),
        "image_prompt": (parsed.get("image_prompt") or parsed.get("imagePrompt") or "").strip(),
    }
    if not stimulus["title"] or not stimulus["narrative"]:
        return jsonify({"success": False, "message": "Stimulus dari ASKA belum lengkap."}), 422
    return jsonify({"success": True, "stimulus": stimulus, "prompt": prompt})


@main_bp.route("/latihan-tka/stimulus/<int:stimulus_id>", methods=["PUT"])
@login_required
@role_required("admin")
def latihan_tka_update_stimulus(stimulus_id: int):
    data = request.get_json(silent=True) or {}
    mapel_id = data.get("mapel_id")
    test_id = data.get("test_id")
    title = data.get("title")
    narrative = data.get("narrative")
    image_prompt = data.get("image_prompt")
    image_data = data.get("image_data")
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else None
    try:
        mapel_id = int(mapel_id) if mapel_id is not None else None
    except (TypeError, ValueError):
        mapel_id = None
    try:
        test_id = int(test_id) if test_id is not None else None
    except (TypeError, ValueError):
        test_id = None
    try:
        stimulus = update_tka_stimulus(
            stimulus_id,
            mapel_id=mapel_id,
            test_id=test_id,
            title=title,
            narrative=narrative,
            image_data=image_data,
            image_prompt=image_prompt,
            metadata=metadata,
        )
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as exc:
        current_app.logger.error("Gagal memperbarui stimulus %s: %s", stimulus_id, exc)
        return jsonify({"success": False, "message": "Gagal memperbarui stimulus."}), 500
    if not stimulus:
        return jsonify({"success": False, "message": "Stimulus tidak ditemukan."}), 404
    return jsonify({"success": True, "stimulus": stimulus})


@main_bp.route("/latihan-tka/stimulus/<int:stimulus_id>", methods=["DELETE"])
@login_required
@role_required("admin")
def latihan_tka_delete_stimulus(stimulus_id: int):
    try:
        success = delete_tka_stimulus(stimulus_id)
    except Exception as exc:
        current_app.logger.error("Gagal menghapus stimulus %s: %s", stimulus_id, exc)
        return jsonify({"success": False, "message": "Gagal menghapus stimulus."}), 500
    if not success:
        return jsonify({"success": False, "message": "Stimulus tidak ditemukan."}), 404
    return jsonify({"success": True})


@main_bp.route("/latihan-tka/questions", methods=["POST"])
@login_required
@role_required("admin")
def latihan_tka_store_questions():
    payload = request.get_json(silent=True) or {}
    subject_id = payload.get("subject_id")
    test_id = payload.get("test_id")
    test_subject_id = payload.get("test_subject_id")
    raw_mapel_id = payload.get("mapel_id")
    try:
        mapel_id = int(raw_mapel_id) if raw_mapel_id is not None else None
    except (TypeError, ValueError):
        mapel_id = None
    questions = payload.get("questions")
    user = current_user() or {}
    created_by = user.get("id")
    if not questions:
        return jsonify({"success": False, "message": "Payload soal belum lengkap."}), 400
    current_app.logger.info(
        "[TKA][questions][store] incoming payload | test_id=%s test_subject_id=%s mapel_id=%s subject_id=%s count=%s sample_prompt=%s",
        test_id,
        test_subject_id,
        raw_mapel_id,
        subject_id,
        len(questions) if isinstance(questions, list) else "n/a",
        (questions[0].get("prompt")[:80] if isinstance(questions, list) and questions and questions[0].get("prompt") else ""),
    )
    ensured_subject_id = None
    if mapel_id:
        try:
            ensured_subject_id = ensure_tka_subject_from_mapel(mapel_id)
        except Exception:
            ensured_subject_id = None
    if not ensured_subject_id and test_subject_id:
        ts_payload = fetch_tka_test_subject(test_subject_id)
        if ts_payload:
            try:
                ensured_subject_id = ensure_tka_subject_from_mapel(ts_payload.get("mapel_id"))
            except Exception:
                ensured_subject_id = None
    subject_id = subject_id or ensured_subject_id or None
    if not (subject_id or mapel_id or test_subject_id):
        return jsonify({"success": False, "message": "Mapel belum diketahui. Pilih mapel pada tes terlebih dahulu."}), 400
    try:
        inserted = create_tka_questions(
            subject_id,
            questions,
            created_by=created_by,
            test_id=test_id,
            test_subject_id=test_subject_id,
            mapel_id=mapel_id,
        )
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as exc:
        current_app.logger.error("Gagal menyimpan soal TKA: %s", exc)
        return jsonify({
            "success": False,
            "message": f"Terjadi kesalahan saat menyimpan soal: {exc}",
        }), 500
    return jsonify({"success": True, "inserted": inserted})


@main_bp.route("/latihan-tka/questions/<int:question_id>", methods=["DELETE"])
@login_required
@role_required("admin")
def latihan_tka_delete_question(question_id: int):
    try:
        success = delete_tka_question(question_id)
    except Exception as exc:
        main_bp.logger.error("Gagal menghapus soal %s: %s", question_id, exc)
        return jsonify({"success": False, "message": "Gagal menghapus soal."}), 500
    if not success:
        return jsonify({"success": False, "message": "Soal tidak ditemukan."}), 404
    return jsonify({"success": True})


@main_bp.route("/latihan-tka/questions/<int:question_id>", methods=["PUT"])
@login_required
@role_required("admin")
def latihan_tka_update_question(question_id: int):
    payload = request.get_json(silent=True) or {}
    try:
        updated = update_tka_question(question_id, payload)
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as exc:
        current_app.logger.error("Gagal memperbarui soal %s: %s", question_id, exc)
        return jsonify({"success": False, "message": "Gagal memperbarui soal."}), 500
    if not updated:
        return jsonify({"success": False, "message": "Soal tidak ditemukan."}), 404
    return jsonify({"success": True})


@main_bp.route("/latihan-tka/questions/check-duplicate", methods=["POST"])
@login_required
@role_required("admin")
def latihan_tka_check_duplicate():
    payload = request.get_json(silent=True) or {}
    raw_subject_id = payload.get("subject_id")
    raw_test_subject_id = payload.get("test_subject_id")
    raw_mapel_id = payload.get("mapel_id")
    prompt = (payload.get("prompt") or "").strip()
    try:
        subject_id = int(raw_subject_id)
    except (TypeError, ValueError):
        subject_id = None
    try:
        test_subject_id = int(raw_test_subject_id)
    except (TypeError, ValueError):
        test_subject_id = None
    try:
        mapel_id = int(raw_mapel_id)
    except (TypeError, ValueError):
        mapel_id = None
    if not prompt:
        return jsonify({"success": False, "message": "Prompt wajib diisi."}), 400
    resolved_subject_id = subject_id
    if not resolved_subject_id and mapel_id:
        try:
            resolved_subject_id = ensure_tka_subject_from_mapel(mapel_id)
        except Exception:
            resolved_subject_id = None
    if not resolved_subject_id and not test_subject_id:
        return jsonify({"success": False, "message": "Pilih mapel pada tes sebelum cek duplikat."}), 400
    try:
        exists = has_tka_question_with_prompt(resolved_subject_id, prompt, test_subject_id=test_subject_id)
    except Exception as exc:
        current_app.logger.error("Gagal mengecek duplikat soal: %s", exc)
        return jsonify({"success": False, "message": "Gagal mengecek duplikat."}), 500
    return jsonify({"success": True, "exists": exists})


@main_bp.route("/latihan-tka/subjects/<int:subject_id>/difficulty", methods=["POST"])
@login_required
@role_required("admin")
def latihan_tka_update_subject_difficulty(subject_id: int):
    payload = request.get_json(silent=True) or {}
    preset = payload.get("preset") or DEFAULT_TKA_PRESET_KEY
    custom_mix = payload.get("custom") if isinstance(payload.get("custom"), dict) else None
    try:
        subject = update_tka_subject_difficulty(subject_id, preset, custom_mix=custom_mix)
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as exc:
        current_app.logger.error("Gagal memperbarui preset TKA %s: %s", subject_id, exc)
        return jsonify({"success": False, "message": "Gagal menyimpan pengaturan komposisi."}), 500
    if not subject:
        return jsonify({"success": False, "message": "Mapel belum tersedia."}), 404
    return jsonify({"success": True, "subject": subject})


@main_bp.route("/latihan-tka/subjects/<int:subject_id>/sections", methods=["POST"])
@login_required
@role_required("admin")
def latihan_tka_update_sections(subject_id: int):
    payload = request.get_json(silent=True) or {}
    sections = payload.get("sections") if isinstance(payload.get("sections"), list) else []
    try:
        duration = int(payload.get("duration_minutes") or DEFAULT_TKA_COMPOSITE_DURATION)
    except (TypeError, ValueError):
        duration = DEFAULT_TKA_COMPOSITE_DURATION
    try:
        subject = update_tka_subject_sections(
            subject_id,
            duration_minutes=duration,
            sections=sections,
        )
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as exc:
        current_app.logger.error("Gagal memperbarui komposisi seksi TKA %s: %s", subject_id, exc)
        return jsonify({"success": False, "message": "Gagal menyimpan komposisi mapel."}), 500
    if not subject:
        return jsonify({"success": False, "message": "Mapel belum tersedia."}), 404
    return jsonify({"success": True, "subject": subject})


@main_bp.route("/latihan-tka/generate", methods=["POST"])
@login_required
@role_required("admin")
def latihan_tka_generate():
    return _handle_tka_generate_request(return_stimulus=True)


@main_bp.route("/latihan-tka/generate_soal_new", methods=["POST"])
@login_required
@role_required("admin")
def latihan_tka_generate_new():
    return _handle_tka_generate_request(return_stimulus=False)


def _handle_tka_generate_request(return_stimulus: bool = True):
    is_multipart = request.mimetype and "multipart/form-data" in request.mimetype
    if is_multipart:
        form_payload = request.form if isinstance(request.form, MultiDict) else MultiDict()
        data = {key: form_payload.get(key) for key in form_payload}
    else:
        data = request.get_json(silent=True) or {}
    preview_flag = data.get("preview_only")
    if preview_flag is None and not is_multipart:
        preview_flag = request.args.get("preview_only")
    if isinstance(preview_flag, str):
        preview_only = preview_flag.strip().lower() in {"1", "true", "yes", "preview", "prompt", "prompt_only"}
    else:
        preview_only = bool(preview_flag)
    raw_subject_id = data.get("subject_id") or (request.form.get("subject_id") if is_multipart else None)
    try:
        subject_id = int(raw_subject_id)
    except (TypeError, ValueError):
        subject_id = None
    raw_test_id = data.get("test_id")
    try:
        test_id = int(raw_test_id) if raw_test_id is not None else None
    except (TypeError, ValueError):
        test_id = None
    raw_test_subject_id = data.get("test_subject_id")
    try:
        test_subject_id = int(raw_test_subject_id) if raw_test_subject_id is not None else None
    except (TypeError, ValueError):
        test_subject_id = None
    raw_mapel_id = data.get("mapel_id")
    try:
        mapel_id = int(raw_mapel_id) if raw_mapel_id is not None else None
    except (TypeError, ValueError):
        mapel_id = None
    topic = (data.get("topic") or "").strip()
    style_example = (data.get("example") or data.get("style_example") or "").strip()
    difficulty = (data.get("difficulty") or "easy").strip().lower()
    grade_level = (data.get("grade_level") or "").strip().lower()
    question_type = (data.get("question_type") or "story").strip().lower()
    answer_mode = (data.get("answer_mode") or "mix").strip().lower()
    style_similarity = (data.get("style_similarity") or "50").strip()
    raw_generator_mode = (data.get("generator_mode") or "lite").strip().lower()
    if raw_generator_mode in {"pro"}:
        generator_mode = "pro"
    elif raw_generator_mode in {"bundle", "bundled", "stimulus", "paket"}:
        generator_mode = "bundle"
    elif raw_generator_mode in {"image", "gambar"}:
        generator_mode = "image"
    elif raw_generator_mode in {"truefalse", "benarsalah", "true_false"}:
        generator_mode = "truefalse"
    elif raw_generator_mode in {"normal", "lite"}:
        generator_mode = "lite"
    else:
        generator_mode = "lite"
    section_key = (data.get("section_key") or "").strip().lower() or "matematika"
    bundle_size_raw = data.get("bundle_size") or data.get("children_per_stimulus") or 4
    try:
        bundle_size = int(bundle_size_raw)
    except (TypeError, ValueError):
        bundle_size = 4
    amount = data.get("amount") or data.get("stimulus_count") or 1
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        amount = 1
    manual_example = (data.get("manual_example") or data.get("manual_sample") or "").strip()
    image_description = (data.get("image_description") or data.get("stimulus_image_desc") or "").strip()
    stimulus_style = (data.get("stimulus_style") or data.get("stimulus_format") or "story").strip().lower()
    if stimulus_style not in {"story", "table"}:
        stimulus_style = "story"
    raw_story_paragraphs = data.get("story_paragraphs") or data.get("story_paragraph_length")
    try:
        story_paragraphs = int(raw_story_paragraphs)
    except (TypeError, ValueError):
        story_paragraphs = 2
    if story_paragraphs < 2:
        story_paragraphs = 2
    elif story_paragraphs > 8:
        story_paragraphs = 8
    raw_selected_stimulus = data.get("stimulus_id") or data.get("existing_stimulus_id")
    try:
        selected_stimulus_id = int(raw_selected_stimulus) if raw_selected_stimulus else None
    except (TypeError, ValueError):
        selected_stimulus_id = None
    selected_stimulus = None
    reference_image_data = None
    if is_multipart:
        reference_image_data = _encode_uploaded_image(request.files.get("reference_image"))
    else:
        image_field = data.get("reference_image")
        if isinstance(image_field, str) and image_field.strip():
            reference_image_data = image_field.strip()

    test_payload = fetch_tka_test(test_id) if test_id else None
    subject_label_hint = (data.get("subject_hint") or "").strip()
    test_subject_payload = None
    mapel_record = fetch_tka_mapel(mapel_id) if mapel_id else None
    if test_payload and not grade_level:
        grade_level = (test_payload.get("grade_level") or "").strip().lower()
    if test_subject_id:
        test_subject_payload = fetch_tka_test_subject(test_subject_id)
        if not test_subject_payload:
            return jsonify({"success": False, "message": "Mapel pada tes tidak ditemukan."}), 404
        if test_id and test_subject_payload.get("test_id") != test_id:
            return jsonify({"success": False, "message": "Mapel tidak termasuk tes ini."}), 400
        mapel_id = test_subject_payload.get("mapel_id") or mapel_id
        subject_label_hint = test_subject_payload.get("mapel_name") or subject_label_hint
    if mapel_id and not mapel_record:
        mapel_record = fetch_tka_mapel(mapel_id)
    if mapel_record and not subject_label_hint:
        subject_label_hint = (mapel_record.get("name") or "").strip()
    if mapel_record and not grade_level:
        grade_level = (mapel_record.get("grade_level") or "").strip().lower()
    if test_subject_payload and not grade_level:
        grade_level = (test_subject_payload.get("grade_level") or test_subject_payload.get("mapel_grade_level") or "").strip().lower()
    grade_level = (grade_level or "").strip().lower()
    if grade_level not in VALID_GRADE_LEVELS:
        grade_level = DEFAULT_TKA_GRADE_LEVEL
    ensured_subject_id = None
    if not subject_id and mapel_id:
        try:
            ensured_subject_id = ensure_tka_subject_from_mapel(mapel_id)
        except Exception:
            ensured_subject_id = None
        subject_id = ensured_subject_id or subject_id
    subject = fetch_tka_subject(subject_id) if subject_id else None
    subject_name_hint = (
        subject_label_hint
        or (mapel_record and mapel_record.get("name"))
        or (test_payload and test_payload.get("name"))
        or f"Mapel #{mapel_id or subject_id or '-'}"
    )
    if not subject:
        current_app.logger.warning(
            "[TKA][generate] mapel tidak ditemukan | subject_id=%s test_id=%s test_subject_id=%s payload=%s",
            subject_id,
            test_id,
            test_subject_id,
            {
                "topic": topic,
                "difficulty": difficulty,
                "generator_mode": generator_mode,
            },
        )
        if mapel_id and not ensured_subject_id:
            try:
                ensured_subject_id = ensure_tka_subject_from_mapel(mapel_id)
            except Exception:
                ensured_subject_id = None
            if ensured_subject_id:
                subject_id = ensured_subject_id
                subject = fetch_tka_subject(subject_id)
    if not subject:
        if not return_stimulus or generator_mode in {"lite", "bundle"}:
            subject = {
                "id": subject_id,
                "name": subject_name_hint,
                "grade_level": grade_level or (test_payload and test_payload.get("grade_level")) or DEFAULT_TKA_GRADE_LEVEL,
            }
        else:
            return jsonify({"success": False, "message": "Mapel belum tersedia."}), 404
    else:
        subject["name"] = subject_name_hint or subject.get("name") or f"Mapel #{mapel_id or subject.get('id') or '-'}"
        subject["grade_level"] = grade_level or (subject.get("grade_level") or DEFAULT_TKA_GRADE_LEVEL)

    if not topic:
        return jsonify({"success": False, "message": "Topik wajib diisi untuk generator."}), 400
    if difficulty not in {"easy", "medium", "hard"}:
        difficulty = "easy"
    if question_type not in {"story", "direct"}:
        question_type = "story"
    if generator_mode == "pro":
        if not selected_stimulus_id:
            return jsonify({"success": False, "message": "Pilih stimulus terlebih dahulu sebelum menjalankan Mode Pro."}), 400
        selected_stimulus = fetch_tka_stimulus(selected_stimulus_id)
        if not selected_stimulus or selected_stimulus.get("subject_id") != subject_id:
            return jsonify({"success": False, "message": "Stimulus tidak ditemukan untuk mapel ini."}), 404
        amount = 1
    elif question_type == "direct":
        # Mode ringkas: abaikan bundle stimulus, fokus ke soal tunggal per entri
        bundle_size = 1
    section_template = next((tpl for tpl in TKA_SECTION_TEMPLATES if tpl["key"] == section_key), TKA_SECTION_TEMPLATES[0])
    section_label = section_template.get("label") or section_key.title()
    if section_template.get("subject_area") == "bahasa_indonesia":
        section_label = "Bahasa Indonesia"

    difficulty_label = {"easy": "mudah", "medium": "sedang", "hard": "susah"}[difficulty]
    grade_descriptor = GRADE_LEVEL_HINTS.get(grade_level)
    if grade_descriptor:
        if section_template.get("subject_area") == "bahasa_indonesia":
            grade_clause = f" Teks harus relevan untuk {grade_descriptor}; gunakan kosakata dan isi bacaan yang sesuai tingkat tersebut."
        else:
            grade_clause = f" Soal harus relevan untuk {grade_descriptor}; gunakan konteks dan angka yang sesuai tingkat tersebut."
    else:
        grade_clause = ""
    if section_template.get("subject_area") == "bahasa_indonesia":
        question_style_clause = ""
    elif question_type == "direct":
        question_style_clause = (
            "Setiap soal HARUS berupa pernyataan matematika ringkas tanpa cerita atau tokoh (contoh: 'Hitung 2/4 + 1/2 = ...'). "
            "Gunakan ekspresi pecahan, persentase, aljabar sederhana, atau perbandingan secara langsung dan to the point. "
            "JANGAN menambahkan narasi panjang—cukup jelaskan operasi matematikanya, lalu sediakan 4 opsi jawaban dan pembahasan singkat."
        )
    else:
        question_style_clause = (
            "Setiap soal harus berupa cerita pendek atau situasi nyata yang melibatkan penalaran multi-langkah, bukan sekedar 'berapa hasil 2 + 5'. "
        )
    uniqueness_hint = secrets.token_hex(8)
    style_block = ""
    if style_example:
        try:
            similarity_value = int(style_similarity)
        except ValueError:
            similarity_value = 50
        similarity_value = max(10, min(similarity_value, 100))
        style_block = (
            "\nContoh gaya/struktur soal:\n"
            f"{style_example.strip()}\n"
            f"Tingkat kemiripan yang diinginkan: sekitar {similarity_value}%. Sesuaikan instruksi ini, jangan menyalin mentah.\n"
        )
    story_paragraph_clause = f"{story_paragraphs} paragraf (wajib, pisahkan setiap paragraf dengan baris baru)"
    if generator_mode == "image":
        mode_clause = (
            "Setiap stimulus WAJIB memerlukan ilustrasi. Sertakan field `image_prompt` yang menjelaskan visual utama secara singkat. "
            "Jangan bocorkan jawaban saat mendeskripsikan gambar."
        )
    elif generator_mode == "truefalse":
        mode_clause = (
            "Pastikan setiap stimulus memiliki minimal satu soal dengan format Benar/Salah yang berisi 3 pernyataan unik."
        )
    elif generator_mode == "pro":
        mode_clause = (
            "Jangan buat stimulus baru. Semua soal harus langsung merujuk pada stimulus yang telah diberikan dan bisa menyebutkan detail paragraf atau gambar terkait."
        )
    elif generator_mode == "bundle":
        if stimulus_style == "table":
            mode_clause = (
                "Fokus pada paket stimulus lengkap berbasis tabel: setiap stimulus harus diawali ringkasan 1 paragraf lalu menampilkan tabel teks (mis. Markdown) dengan kolom dan 3-5 baris data yang relevan."
                " Sertakan field `type\":\"table\"`, taruh tabel di field `narrative`, dan gunakan data tabel tersebut untuk semua soal di paketnya. Jangan menyebut diagram/gambar."
            )
        else:
            mode_clause = (
                f"Fokus pada paket stimulus lengkap berbentuk narasi: setiap stimulus harus memiliki judul, narasi {story_paragraph_clause}, serta deskripsi gambar (field `image_prompt`). "
                "Sertakan field `type\":\"text\"` dan gunakan stimulus tersebut untuk menulis seluruh soal dalam paketnya."
            )
    else:
        mode_clause = ""
    manual_clause = ""
    if manual_example:
        manual_clause = (
            "\nContoh soal manual yang perlu dijadikan referensi gaya (jangan disalin mentah):\n"
            f"{manual_example}\n"
        )
    image_clause = ""
    if image_description and stimulus_style != "table":
        image_clause = (
            f"\nGuru mendeskripsikan gambar stimulus sebagai berikut: {image_description}. Gunakan deskripsi ini untuk field `image_prompt` pada stimulus yang relevan."
        )
    if reference_image_data:
        image_clause += " Sistem akan menambahkan file gambar secara otomatis, jadi cukup pastikan field `image_data` ada namun boleh dikosongkan."
    if generator_mode == "pro" and selected_stimulus:
        stimulus_title = (selected_stimulus.get("title") or f"Stimulus #{selected_stimulus_id}").strip()
        stimulus_story = (selected_stimulus.get("narrative") or "").strip() or "Narasi belum tersedia. Gunakan deskripsi gambar atau konteks umum."
        stimulus_image_prompt = (selected_stimulus.get("image_prompt") or "").strip()
        if answer_mode in {"multiple_choice", "pg", "pg_only"}:
            answer_clause = "Gunakan format pilihan ganda untuk SEMUA soal (4 opsi A-D + pembahasan singkat). Jangan buat soal benar/salah."
        elif answer_mode in {"true_false", "tf", "truefalse", "benar_salah"}:
            answer_clause = "Gunakan format Benar/Salah untuk SEMUA soal. Setiap soal memakai `question_type\":\"true_false\"` dan `statements` berisi 3 pernyataan {\"text\",\"answer\"}. Opsi A-D boleh dikosongkan."
        else:
            answer_clause = "Boleh campuran: sebagian soal pilihan ganda (4 opsi A-D) dan sebagian soal Benar/Salah (`question_type\":\"true_false\"` + 3 pernyataan). Satu soal hanya satu format."
        prompt_rows = [
            f"Anda adalah ASKA, guru kreatif yang menulis soal untuk mapel {subject['name']}. "
            "Gunakan stimulus berikut sebagai satu-satunya konteks cerita.",
            f"Judul stimulus: {stimulus_title}",
            f"Narasi stimulus:\n{stimulus_story}",
        ]
        if stimulus_image_prompt:
            prompt_rows.append(f"Deskripsi gambar stimulus: {stimulus_image_prompt}.")
        pg_clause = "Untuk soal pilihan ganda, sertakan 4 opsi jawaban (A-D) dan pembahasan singkat yang logis."
        tf_clause = "Untuk soal Benar/Salah, sertakan field `question_type\":\"true_false\"` dan `statements` berupa tiga objek {\"text\":\"...\",\"answer\":\"benar|salah\"}; opsi A-D boleh dikosongkan."
        extra_format_clause = ""
        if answer_mode in {"multiple_choice", "pg", "pg_only"}:
            extra_format_clause = pg_clause
        elif answer_mode in {"true_false", "tf", "truefalse", "benar_salah"}:
            extra_format_clause = tf_clause
        else:
            extra_format_clause = f"{pg_clause} {tf_clause}"
        prompt_rows.append(
            f"Tulislah {bundle_size} soal bertopik {topic} dengan tingkat kesulitan {difficulty_label}.{grade_clause} "
            f"{question_style_clause}{mode_clause} "
            f"{answer_clause} {extra_format_clause}"
        )
        prompt_rows.append(f"{style_block}{manual_clause}")
        prompt_rows.append(f"Akhiri pembahasan setiap soal dengan kalimat \\\"Kode: {uniqueness_hint}\\\" agar mudah dilacak.")
        prompt_rows.append(
            "Format keluaran harus berupa JSON valid (tanpa teks lain) mengikuti contoh berikut:\n"
            '{"questions":[{"prompt":"...", "topic":"...", "difficulty":"easy|medium|hard", "question_type":"multiple_choice|true_false", '
            '"options":[{"key":"A","text":"..."},...], "answer":"A", "explanation":"...", '
            '"statements":[{"text":"...", "answer":"benar"}]}]}]'
        )
        prompt = "\n".join(prompt_rows)
    elif generator_mode == "lite":
        pg_clause = "Format PG: 4 opsi A-D dan pembahasan singkat."
        tf_clause = "Format BS: `question_type\":\"true_false\"` dengan 3 pernyataan unik di `statements`."
        if answer_mode in {"multiple_choice", "pg", "pg_only"}:
            answer_clause = f"Semua soal wajib pilihan ganda. {pg_clause}"
        elif answer_mode in {"true_false", "tf", "truefalse", "benar_salah"}:
            answer_clause = f"Semua soal wajib Benar/Salah. {tf_clause} Opsi A-D boleh dikosongkan."
        else:
            answer_clause = f"Campuran: buat beberapa soal PG dan beberapa BS. {pg_clause} {tf_clause} Untuk BS, opsi A-D boleh kosong."
        prompt = (
            f"Buat {amount} soal mapel {subject['name']} topik {topic} tingkat {difficulty_label}.{grade_clause} "
            f"{answer_clause} {question_style_clause}{mode_clause} "
            "Gunakan bahasa Indonesia formal sesuai jenjang. "
            f"{style_block}{manual_clause}{image_clause}"
            f"Tutup setiap pembahasan dengan kalimat \\\"Kode: {uniqueness_hint}\\\".\n"
            "Keluaran hanya JSON valid:\n"
            '{"questions":[{"prompt":"...", "topic":"...", "difficulty":"easy|medium|hard", "question_type":"multiple_choice|true_false", '
            '"options":[{"key":"A","text":"..."},...], "answer":"A", "explanation":"...", '
            '"statements":[{"text":"...", "answer":"benar"}]}]}'
        )
    else:
        pg_clause = "Format PG: sertakan 4 opsi A-D dan pembahasan singkat."
        tf_clause = "Format BS: gunakan `question_type\":\"true_false\"` dengan 3 pernyataan di `statements`."
        if answer_mode in {"multiple_choice", "pg", "pg_only"}:
            answer_clause = f"Semua soal wajib pilihan ganda. {pg_clause}"
        elif answer_mode in {"true_false", "tf", "truefalse", "benar_salah"}:
            answer_clause = f"Semua soal wajib Benar/Salah. {tf_clause} Opsi A-D boleh dikosongkan."
        else:
            answer_clause = f"Campuran: buat beberapa soal PG dan beberapa BS. {pg_clause} {tf_clause} Untuk BS, opsi A-D boleh kosong."
        if stimulus_style == "table":
            stimulus_structure_clause = (
                "Setiap stimulus harus menampilkan tabel teks rapi (boleh Markdown) dengan minimal dua kolom dan 3-5 baris data yang relevan, boleh diawali ringkasan singkat."
            )
        else:
            stimulus_structure_clause = (
                f"Stimulus harus berupa narasi {story_paragraph_clause} yang runtut dan jelas. "
                "Jangan gabungkan semua kalimat dalam satu paragraf panjang; pastikan jumlah paragraf sesuai permintaan."
            )
        prompt = (
            f"Buat {amount} stimulus baru bertopik {topic} untuk mapel {subject['name']} dengan tingkat kesulitan {difficulty_label}.{grade_clause} "
            f"{stimulus_structure_clause} Setiap stimulus ini memiliki {bundle_size} pertanyaan. "
            f"{answer_clause} "
            f"{question_style_clause}{mode_clause} "
            "Gunakan bahasa Indonesia formal yang sesuai tingkatnya. "
            f"{style_block}{manual_clause}{image_clause}"
            f"Pastikan setiap stimulus unik dan akhiri pembahasan setiap soal dengan kalimat \\\"Kode: {uniqueness_hint}\\\" agar mudah dilacak.\n"
            "Format keluaran harus berupa JSON valid (tanpa teks lain) mengikuti contoh berikut:\n"
            '{"stimulus":[{"title":"Judul Stimulus","narrative":"...", "image_prompt":"...", '
            '"questions":[{"prompt":"...", "topic":"...", "difficulty":"easy|medium|hard", "question_type":"multiple_choice|true_false", '
            '"options":[{"key":"A","text":"..."},...], "answer":"A", "explanation":"...", '
            '"statements":[{"text":"...", "answer":"benar"}]}]}]}'
        )
    if preview_only:
        return jsonify({"success": True, "prompt": prompt})

    chain = _get_tka_ai_chain()
    if chain is None:
        return jsonify({"success": False, "message": "Model ASKA belum siap. Coba sebentar lagi."}), 503

    try:
        result = chain.invoke(prompt)
        if hasattr(result, "content"):
            raw_output = result.content
        elif isinstance(result, dict) and "answer" in result:
            raw_output = result["answer"]
        else:
            raw_output = str(result)
        cleaned = _strip_code_fences(str(raw_output))
        cleaned = _repair_bare_fields(cleaned)
        normalized = _repair_trailing_commas(
            _close_unbalanced_json(
                _repair_split_question_arrays(
                    _repair_trailing_commas(_repair_unterminated_strings(_normalize_jsonish_text(cleaned)))
                )
            )
        )
        parsed = json.loads(normalized)
    except json.JSONDecodeError:
        try:
            fallback_payload = _extract_json_payload(cleaned)
            normalized = _repair_trailing_commas(
                _close_unbalanced_json(
                    _repair_split_question_arrays(
                        _repair_trailing_commas(_repair_unterminated_strings(_normalize_jsonish_text(fallback_payload)))
                    )
                )
            )
            parsed = json.loads(normalized)
        except Exception as exc:
            salvaged_questions = _salvage_questions_from_text(cleaned)
            salvaged_stimulus = _salvage_stimulus_from_text(cleaned)
            if salvaged_questions or salvaged_stimulus:
                parsed = {"questions": salvaged_questions or []}
                if salvaged_stimulus:
                    parsed["stimulus"] = [salvaged_stimulus]
                current_app.logger.warning(
                    "ASKA generator diparse parsial; stimulus_ok=%s, soal=%s.",
                    bool(salvaged_stimulus),
                    len(salvaged_questions or []),
                )
            else:
                preview = cleaned.strip().replace("```", "")[:300]
                current_app.logger.error("ASKA generator output tidak dapat diparse: %s | error=%s", cleaned, exc)
                return jsonify({
                    "success": False,
                    "message": f"ASKA mengirim format yang belum bisa dipahami. Cuplikan: {preview}"
                }), 422
    except Exception as exc:
        error_text = str(exc) or ""
        lower = error_text.lower()
        if "rate limit" in lower or "limit reached" in lower or "exceeded" in lower:
            current_app.logger.error("Generator TKA rate-limit: %s", exc)
            return jsonify({
                "success": False,
                "message": "ASKA kena rate limit model. Coba ulang beberapa detik lagi; jika sering terjadi, cek billing/kuota.",
            }), 429
        current_app.logger.error("Generator TKA error: %s", exc)
        return jsonify({"success": False, "message": "ASKA gagal menghasilkan soal."}), 500

    if isinstance(parsed, list):
        parsed = {"questions": parsed}
    questions = _normalize_generated_questions(
        parsed,
        topic,
        difficulty,
        generator_mode=generator_mode,
        target_children=bundle_size,
    )
    if generator_mode == "bundle":
        forced_type = "table" if stimulus_style == "table" else "text"
        for question in questions:
            stimulus = question.get("stimulus")
            if isinstance(stimulus, dict) and not stimulus.get("type"):
                stimulus["type"] = forced_type
    if stimulus_style == "story" and story_paragraphs:
        for question in questions:
            stimulus = question.get("stimulus")
            if not isinstance(stimulus, dict):
                continue
            if stimulus.get("type") == "table":
                continue
            narrative_value = stimulus.get("narrative") or ""
            if not narrative_value:
                continue
            enforced = _enforce_min_paragraphs(narrative_value, story_paragraphs)
            if enforced:
                stimulus["narrative"] = enforced
    if selected_stimulus:
        fixed_stimulus_payload = {
            "id": selected_stimulus_id,
            "title": selected_stimulus.get("title"),
            "narrative": selected_stimulus.get("narrative"),
            "image_prompt": selected_stimulus.get("image_prompt"),
            "image_url": selected_stimulus.get("image_url"),
            "type": selected_stimulus.get("type"),
            "bundle_key": f"existing-{selected_stimulus_id}",
        }
        for question in questions:
            if not question.get("stimulus"):
                question["stimulus"] = dict(fixed_stimulus_payload)
    elif questions and (reference_image_data or image_description):
        patched = set()
        for question in questions:
            stimulus_meta = question.get("stimulus")
            if not stimulus_meta:
                continue
            stim_key = stimulus_meta.get("bundle_key") or stimulus_meta.get("title")
            if stim_key in patched:
                continue
            if image_description and not stimulus_meta.get("image_prompt"):
                stimulus_meta["image_prompt"] = image_description
            if reference_image_data and not stimulus_meta.get("image_data"):
                stimulus_meta["image_data"] = reference_image_data
            patched.add(stim_key)
            break
    if not questions:
        return jsonify({"success": False, "message": "ASKA belum menghasilkan soal valid."}), 422

    # Log payload penuh untuk inspeksi manual di terminal/log
    try:
        log_payload = {
            "stimulus": parsed.get("stimulus") if isinstance(parsed, dict) else None,
            "questions": questions,
        }
        current_app.logger.info("[TKA][generate] output OK | payload=%s", json.dumps(log_payload, ensure_ascii=False))
    except Exception:
        pass

    if not return_stimulus:
        return jsonify({"success": True, "prompt": prompt})

    return jsonify({"success": True, "questions": questions, "prompt": prompt})


@main_bp.route("/latihan-tka/results/data")
@login_required
@role_required("admin")
def latihan_tka_results_data():
    subject_id = request.args.get("subject_id", type=int)
    status = request.args.get("status")
    search = request.args.get("search")
    attempts = fetch_tka_attempts(
        subject_id=subject_id,
        status=status,
        search=search,
        limit=200,
    )
    for attempt in attempts:
        for field in ("started_at", "completed_at", "updated_at", "analysis_sent_at"):
            value = attempt.get(field)
            if hasattr(value, "isoformat"):
                attempt[field] = value.isoformat()
        breakdown = attempt.get("difficulty_breakdown")
        if isinstance(breakdown, dict):
            attempt["difficulty_breakdown"] = breakdown
        else:
            attempt["difficulty_breakdown"] = {}
        preset_value = attempt.get("difficulty_preset")
        if preset_value:
            preset_key = str(preset_value).strip().lower()
            attempt["difficulty_preset_label"] = TKA_PRESET_LABELS.get(preset_key, preset_value.title())
        else:
            attempt["difficulty_preset_label"] = "-"
        grade_value = attempt.get("grade_level")
        attempt["grade_label"] = GRADE_LABELS.get((grade_value or "").strip().lower(), GRADE_LABELS["sd6"])
    return jsonify({"success": True, "attempts": attempts})


# --- API Tes TKA (tes -> mapel -> topik/format) ----------------------------


@main_bp.route("/latihan-tka/tests", methods=["GET"])
@login_required
@role_required("admin")
def latihan_tka_list_tests():
    tests = fetch_tka_tests()
    return jsonify({"success": True, "tests": tests})


@main_bp.route("/latihan-tka/tests/<int:test_id>", methods=["DELETE"])
@login_required
@role_required("admin")
def latihan_tka_delete_test_api(test_id: int):
    try:
        success = delete_tka_test(test_id)
    except Exception as exc:
        current_app.logger.error("Gagal menghapus tes %s: %s", test_id, exc)
        return jsonify({"success": False, "message": "Gagal menghapus tes."}), 500
    if not success:
        return jsonify({"success": False, "message": "Tes tidak ditemukan."}), 404
    return jsonify({"success": True})


@main_bp.route("/latihan-tka/tests", methods=["POST"])
@login_required
@role_required("admin")
def latihan_tka_create_test():
    payload = request.get_json(silent=True) or {}
    try:
        test = create_tka_test(
            name=payload.get("name"),
            grade_level=payload.get("grade_level"),
            duration_minutes=payload.get("duration_minutes"),
            is_active=bool(payload.get("is_active", True)),
        )
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as exc:
        current_app.logger.error("Gagal membuat tes TKA: %s", exc)
        return jsonify({"success": False, "message": "Gagal menyimpan tes."}), 500
    return jsonify({"success": True, "test": test})


@main_bp.route("/latihan-tka/tests/<int:test_id>/subjects", methods=["GET"])
@login_required
@role_required("admin")
def latihan_tka_test_subjects(test_id: int):
    try:
        subjects = fetch_tka_test_subjects(test_id)
    except Exception as exc:
        current_app.logger.error("Gagal memuat mapel tes %s: %s", test_id, exc)
        return jsonify({"success": False, "message": "Gagal memuat mapel tes."}), 500
    return jsonify({"success": True, "subjects": subjects})


@main_bp.route("/latihan-tka/tests/<int:test_id>/subjects", methods=["POST"])
@login_required
@role_required("admin")
def latihan_tka_add_test_subject(test_id: int):
    payload = request.get_json(silent=True) or {}
    mapel_id = payload.get("mapel_id")
    try:
        if not mapel_id:
            return jsonify({"success": False, "message": "mapel_id wajib diisi."}), 400
        mapel_record = fetch_tka_mapel(mapel_id)
        if not mapel_record:
            return jsonify({"success": False, "message": "Mapel belum tersedia."}), 404
        test_record = fetch_tka_test(test_id)
        if not test_record:
            return jsonify({"success": False, "message": "Tes tidak ditemukan."}), 404
        test_grade = (test_record.get("grade_level") or "").strip().lower() or None
        mapel_grade = (mapel_record.get("grade_level") or "").strip().lower() or None
        if not mapel_grade:
            return jsonify({"success": False, "message": "Mapel tidak memiliki jenjang."}), 400
        if test_grade and test_grade != mapel_grade:
            label_mapel = GRADE_LABELS.get(mapel_grade, mapel_grade.upper())
            label_test = GRADE_LABELS.get(test_grade, test_grade.upper())
            return jsonify({"success": False, "message": f"Tes ini khusus jenjang {label_test}. Mapel yang dipilih berjenjang {label_mapel}."}), 400
        if not test_grade:
            updated = set_tka_test_grade_level(test_id, mapel_grade)
            if updated:
                test_record = updated
        subject = create_tka_test_subject(
            test_id=test_id,
            total=payload.get("question_count_target") or payload.get("total"),
            mapel_id=mapel_id,
            formats=payload.get("formats"),
            topics=payload.get("topics"),
        )
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as exc:
        current_app.logger.error("Gagal menambah mapel tes %s: %s", test_id, exc)
        return jsonify({"success": False, "message": "Gagal menambahkan mapel ke tes."}), 500
    return jsonify({"success": True, "subject": subject})


@main_bp.route("/latihan-tka/tests/<int:test_id>/subjects/<int:test_subject_id>", methods=["DELETE"])
@login_required
@role_required("admin")
def latihan_tka_delete_test_subject(test_id: int, test_subject_id: int):
    try:
        success = delete_tka_test_subject(test_id, test_subject_id)
    except Exception as exc:
        current_app.logger.error("Gagal menghapus mapel tes %s/%s: %s", test_id, test_subject_id, exc)
        return jsonify({"success": False, "message": "Gagal menghapus mapel tes."}), 500
    if not success:
        return jsonify({"success": False, "message": "Mapel tes tidak ditemukan."}), 404
    return jsonify({"success": True})


@main_bp.route("/latihan-tka/tests/<int:test_id>/subjects/<int:test_subject_id>/topics", methods=["PUT"])
@login_required
@role_required("admin")
def latihan_tka_update_test_subject_topics(test_id: int, test_subject_id: int):
    payload = request.get_json(silent=True) or {}
    topics = payload.get("topics")
    if topics is not None and not isinstance(topics, list):
        return jsonify({"success": False, "message": "Format topik tidak dikenal."}), 400
    try:
        subject = fetch_tka_test_subject(test_subject_id)
        if not subject or subject.get("test_id") != test_id:
            return jsonify({"success": False, "message": "Mapel tes tidak ditemukan."}), 404
        updated = update_tka_test_subject_topics(test_subject_id, topics)
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as exc:
        current_app.logger.error("Gagal memperbarui topik mapel tes %s/%s: %s", test_id, test_subject_id, exc)
        return jsonify({"success": False, "message": "Gagal memperbarui topik mapel tes."}), 500
    return jsonify({"success": True, "subject": updated})


@main_bp.route("/latihan-tka/mapel", methods=["GET"])
@login_required
@role_required("admin")
def latihan_tka_list_mapel():
    data = fetch_tka_mapel_list()
    return jsonify({"success": True, "mapel": data})


@main_bp.route("/latihan-tka/mapel", methods=["POST"])
@login_required
@role_required("admin")
def latihan_tka_create_mapel():
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    grade_level = (payload.get("grade_level") or "").strip().lower()
    is_active = bool(payload.get("is_active", True))
    description = payload.get("description")
    formats = payload.get("formats") if isinstance(payload.get("formats"), list) else None
    topics = payload.get("topics") if isinstance(payload.get("topics"), list) else None
    try:
        record = create_tka_mapel(
            name=name,
            grade_level=grade_level,
            description=description,
            is_active=is_active,
            formats=formats,
            topics=topics,
        )
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as exc:
        current_app.logger.error("Gagal membuat mapel TKA: %s", exc)
        return jsonify({"success": False, "message": "Gagal menyimpan mapel."}), 500
    return jsonify({"success": True, "mapel": record})


@main_bp.route("/latihan-tka/mapel/<int:mapel_id>", methods=["DELETE"])
@login_required
@role_required("admin")
def latihan_tka_delete_mapel(mapel_id: int):
    try:
        success = delete_tka_mapel(mapel_id)
    except Exception as exc:
        current_app.logger.error("Gagal menghapus mapel %s: %s", mapel_id, exc)
        return jsonify({"success": False, "message": "Gagal menghapus mapel."}), 500
    if not success:
        return jsonify({"success": False, "message": "Mapel belum tersedia."}), 404
    return jsonify({"success": True})
