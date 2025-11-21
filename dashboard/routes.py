from __future__ import annotations

import base64
import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from math import ceil
from typing import Optional
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
from db import DEFAULT_TKA_PRESET_KEY, DEFAULT_TKA_COMPOSITE_DURATION, TKA_SECTION_TEMPLATES
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
    fetch_tka_stimulus_list,
    fetch_tka_stimulus,
    create_tka_stimulus,
    update_tka_stimulus,
    delete_tka_stimulus,
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
    topic = (item.get("topic") or fallback_topic).strip()
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
    if len(options) < 2:
        return None
    answer = (
        item.get("answer")
        or item.get("correct_answer")
        or item.get("kunci")
        or item.get("jawaban")
        or options[0]["key"]
    )
    answer_key = str(answer).strip().upper()
    if answer_key not in {opt["key"] for opt in options}:
        answer_key = options[0]["key"]
    explanation = (item.get("explanation") or item.get("rationale") or item.get("pembahasan") or "").strip()
    raw_metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    metadata = dict(raw_metadata) if raw_metadata else {}
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
    return render_template(
        "latihan_tka_manual.html",
        subjects=subjects,
        grade_labels=GRADE_LABELS,
        section_templates=TKA_SECTION_TEMPLATES,
        default_duration=DEFAULT_TKA_COMPOSITE_DURATION,
    )


@main_bp.route("/latihan-tka/generator", defaults={"mode": "lite"})
@main_bp.route("/latihan-tka/generator/<string:mode>")
@login_required
@role_required("admin")
def latihan_tka_generator_page(mode: str):
    subjects = fetch_tka_subjects(include_inactive=True)
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
        subjects=subjects,
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
    if not subject_id:
        return jsonify({"success": False, "message": "subject_id wajib diisi."}), 400
    difficulty = request.args.get("difficulty") or None
    topic = request.args.get("topic") or None
    questions = fetch_tka_questions(
        subject_id,
        difficulty=difficulty or None,
        topic=topic or None,
    )
    return jsonify({"success": True, "questions": questions})


@main_bp.route("/latihan-tka/stimulus")
@login_required
@role_required("admin")
def latihan_tka_stimulus():
    subject_id = request.args.get("subject_id", type=int)
    if not subject_id:
        return jsonify({"success": False, "message": "subject_id wajib diisi."}), 400
    stimulus = fetch_tka_stimulus_list(subject_id)
    return jsonify({"success": True, "stimulus": stimulus})


@main_bp.route("/latihan-tka/stimulus/create", methods=["POST"])
@login_required
@role_required("admin")
def latihan_tka_create_stimulus():
    data = request.get_json(silent=True) or {}
    subject_id = data.get("subject_id")
    try:
        subject_id = int(subject_id)
    except (TypeError, ValueError):
        subject_id = None
    if not subject_id:
        return jsonify({"success": False, "message": "subject_id wajib diisi."}), 400
    title = (data.get("title") or "").strip()
    narrative = (data.get("narrative") or "").strip()
    image_prompt = (data.get("image_prompt") or "").strip() or None
    image_data = data.get("image_data") or data.get("image_url")
    user = current_user() or {}
    created_by = user.get("id")
    try:
        stimulus = create_tka_stimulus(
            subject_id,
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
    try:
        subject_id = int(subject_id)
    except (TypeError, ValueError):
        subject_id = None
    topic = (data.get("topic") or "").strip()
    tone = (data.get("tone") or "narasi").strip().lower()
    include_image = bool(data.get("include_image"))
    subject = fetch_tka_subject(subject_id)
    if not subject:
        return jsonify({"success": False, "message": "Mapel tidak ditemukan."}), 404
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
        f"Anda adalah ASKA, guru Bahasa Indonesia yang menulis stimulus bacaan. Buat 1 stimulus dengan judul singkat dan narasi 2-3 paragraf untuk mapel {subject['name']}. "
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
    title = data.get("title")
    narrative = data.get("narrative")
    image_prompt = data.get("image_prompt")
    image_data = data.get("image_data")
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else None
    try:
        stimulus = update_tka_stimulus(
            stimulus_id,
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
    questions = payload.get("questions")
    user = current_user() or {}
    created_by = user.get("id")
    if not subject_id or not questions:
        return jsonify({"success": False, "message": "Payload soal belum lengkap."}), 400
    try:
        inserted = create_tka_questions(subject_id, questions, created_by=created_by)
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as exc:
        current_app.logger.error("Gagal menyimpan soal TKA: %s", exc)
        return jsonify({"success": False, "message": "Terjadi kesalahan saat menyimpan soal."}), 500
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
    subject_id = payload.get("subject_id")
    prompt = (payload.get("prompt") or "").strip()
    if not subject_id or not prompt:
        return jsonify({"success": False, "message": "subject_id dan prompt wajib diisi."}), 400
    try:
        exists = has_tka_question_with_prompt(subject_id, prompt)
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
        return jsonify({"success": False, "message": "Mapel tidak ditemukan."}), 404
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
        return jsonify({"success": False, "message": "Mapel tidak ditemukan."}), 404
    return jsonify({"success": True, "subject": subject})


@main_bp.route("/latihan-tka/generate", methods=["POST"])
@login_required
@role_required("admin")
def latihan_tka_generate():
    is_multipart = request.mimetype and "multipart/form-data" in request.mimetype
    if is_multipart:
        form_payload = request.form if isinstance(request.form, MultiDict) else MultiDict()
        data = {key: form_payload.get(key) for key in form_payload}
    else:
        data = request.get_json(silent=True) or {}
    raw_subject_id = data.get("subject_id") or (request.form.get("subject_id") if is_multipart else None)
    try:
        subject_id = int(raw_subject_id)
    except (TypeError, ValueError):
        subject_id = None
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
    elif raw_generator_mode in {"image", "gambar"}:
        generator_mode = "image"
    elif raw_generator_mode in {"truefalse", "benarsalah", "true_false"}:
        generator_mode = "truefalse"
    elif raw_generator_mode in {"normal", "lite"}:
        generator_mode = "lite"
    else:
        generator_mode = "lite"
    section_key = (data.get("section_key") or "").strip().lower() or "matematika"
    bundle_size = data.get("bundle_size") or data.get("children_per_stimulus") or 4
    try:
        bundle_size = max(MIN_GENERATED_CHILDREN, min(int(bundle_size), MAX_GENERATED_CHILDREN))
    except (TypeError, ValueError):
        bundle_size = 4
    amount = data.get("amount") or data.get("stimulus_count") or 1
    try:
        amount = max(1, min(int(amount), 6))
    except (TypeError, ValueError):
        amount = 1
    manual_example = (data.get("manual_example") or data.get("manual_sample") or "").strip()
    image_description = (data.get("image_description") or data.get("stimulus_image_desc") or "").strip()
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

    subject = fetch_tka_subject(subject_id)
    if not subject:
        return jsonify({"success": False, "message": "Mapel tidak ditemukan."}), 404

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

    chain = _get_tka_ai_chain()
    if chain is None:
        return jsonify({"success": False, "message": "Model ASKA belum siap. Coba sebentar lagi."}), 503

    difficulty_label = {"easy": "mudah", "medium": "sedang", "hard": "susah"}[difficulty]
    grade_descriptor = GRADE_LEVEL_HINTS.get(grade_level)
    grade_clause = f" Soal harus relevan untuk {grade_descriptor}, gunakan konteks dan angka yang sesuai tingkat tersebut." if grade_descriptor else ""
    if question_type == "direct":
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
            "\nContoh gaya/struktur rujukan:\n"
            f"{style_example.strip()}\n"
            f"Tingkat kemiripan yang diinginkan: sekitar {similarity_value}%. Sesuaikan instruksi ini, jangan menyalin mentah.\n"
        )
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
    else:
        mode_clause = ""
    manual_clause = ""
    if manual_example:
        manual_clause = (
            "\nContoh soal manual yang perlu dijadikan referensi gaya (jangan disalin mentah):\n"
            f"{manual_example}\n"
        )
    image_clause = ""
    if image_description:
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
            answer_clause = "Semua soal menggunakan format pilihan ganda saja; jangan buat soal benar/salah."
        elif answer_mode in {"true_false", "tf", "truefalse", "benar_salah"}:
            answer_clause = "Semua soal menggunakan format benar/salah saja; sertakan field `question_type\":\"true_false\"` dan `statements` tiga objek {\"text\",\"answer\"}. Opsi A-D boleh dikosongkan jika tidak relevan."
        else:
            answer_clause = "Boleh campuran soal pilihan ganda dan benar/salah, tetapi setiap soal hanya satu format (tidak digabung)."
        prompt_rows = [
            f"Anda adalah ASKA, guru kreatif yang menulis soal untuk mapel {subject['name']} kategori {section_label}. "
            "Gunakan stimulus berikut sebagai satu-satunya konteks cerita.",
            f"Judul stimulus: {stimulus_title}",
            f"Narasi stimulus:\n{stimulus_story}",
        ]
        if stimulus_image_prompt:
            prompt_rows.append(f"Deskripsi gambar stimulus: {stimulus_image_prompt}.")
        prompt_rows.append(
            f"Tulislah {bundle_size} soal bertopik {topic} dengan tingkat kesulitan {difficulty_label}.{grade_clause} "
            f"{question_style_clause}{mode_clause} "
            f"{answer_clause} "
            "Untuk soal pilihan ganda, sertakan 4 opsi jawaban (A-D) dan pembahasan singkat yang logis. "
            "Untuk soal Benar/Salah, sertakan field `statements` berupa tiga objek {\"text\":\"...\",\"answer\":\"benar|salah\"}; opsi A-D boleh dikosongkan jika Anda tidak membuat kombinasi jawaban."
        )
        prompt_rows.append(f"{style_block}{manual_clause}")
        prompt_rows.append(f"Akhiri pembahasan setiap soal dengan kalimat \\\"Kode: {uniqueness_hint}\\\" agar mudah dilacak.")
        prompt_rows.append(
            "Format keluaran HANYA berupa JSON valid tanpa teks tambahan:\n"
            '{"questions":[{"prompt":"...", "topic":"...", "difficulty":"easy|medium|hard", "question_type":"multiple_choice|true_false", '
            '"options":[{"key":"A","text":"..."},...], "answer":"A", "explanation":"...", '
            '"statements":[{"text":"...", "answer":"benar"}]}]}]'
        )
        prompt = "\n".join(prompt_rows)
    else:
        if question_type == "direct":
            answer_clause = ""
            if answer_mode in {"multiple_choice", "pg", "pg_only"}:
                answer_clause = "Semua soal menggunakan format pilihan ganda, tidak ada soal benar/salah."
            elif answer_mode in {"true_false", "tf", "truefalse", "benar_salah"}:
                answer_clause = "Semua soal menggunakan format benar/salah saja; jangan buat pilihan ganda."
            else:
                answer_clause = "Boleh campuran soal pilihan ganda dan benar/salah, tapi tiap soal hanya satu format."
            prompt = (
                f"Anda adalah ASKA, guru kreatif yang menulis soal untuk mapel {subject['name']} kategori {section_label}. "
                f"Buat {amount} soal ringkas bertopik {topic} dengan tingkat kesulitan {difficulty_label}.{grade_clause} "
                "Semua soal HARUS berupa pernyataan atau ekspresi matematika singkat tanpa cerita atau tokoh, tidak perlu stimulus. "
                f"{answer_clause} "
                "Jika memilih pilihan ganda, berikan 4 opsi jawaban (A-D) dan pembahasan singkat. "
                "Jika memilih Benar/Salah, sertakan field `question_type\":\"true_false\"` dan `statements` berisi tiga objek {\"text\":\"...\",\"answer\":\"benar|salah\"}; opsi A-D boleh kosong atau diabaikan. "
                f"{question_style_clause}{mode_clause}{style_block}{manual_clause}"
                f"Pastikan setiap soal unik dan akhiri pembahasan setiap soal dengan kalimat \\\"Kode: {uniqueness_hint}\\\" agar mudah dilacak.\n"
                "Format keluaran HANYA berupa JSON valid tanpa teks tambahan:\n"
                '{"questions":[{"prompt":"...", "topic":"...", "difficulty":"easy|medium|hard", "question_type":"multiple_choice|true_false", '
                '"options":[{"key":"A","text":"..."},...], "answer":"A", "explanation":"...", '
                '"statements":[{"text":"...", "answer":"benar"}]}]}'
            )
        else:
            if answer_mode in {"multiple_choice", "pg", "pg_only"}:
                answer_clause = "Semua soal dalam setiap stimulus menggunakan format pilihan ganda saja."
            elif answer_mode in {"true_false", "tf", "truefalse", "benar_salah"}:
                answer_clause = "Semua soal dalam setiap stimulus menggunakan format benar/salah saja; jangan buat pilihan ganda."
            else:
                answer_clause = "Boleh campuran soal pilihan ganda dan benar/salah, tetapi setiap soal hanya satu format (tidak digabung)."
            prompt = (
                f"Anda adalah ASKA, guru kreatif yang menulis soal untuk mapel {subject['name']} kategori {section_label}. "
                f"Buat {amount} stimulus baru bertopik {topic} dengan tingkat kesulitan {difficulty_label}.{grade_clause} "
                f"Setiap stimulus harus berupa narasi 2-3 paragraf dan memiliki {bundle_size} pertanyaan (minimal 3 dan maksimal 5). "
                f"{answer_clause} "
                f"{question_style_clause}{mode_clause} "
                "Gunakan bahasa Indonesia formal yang tetap ringan, konteks sehari-hari, serta nama tokoh yang variatif. "
                "Untuk soal pilihan ganda, sertakan 4 opsi jawaban (A-D) dan pembahasan ringkas. "
                "Untuk soal Benar/Salah, sertakan field `question_type\":\"true_false\"` dan `statements` berupa array tiga objek {\"text\":\"...\",\"answer\":\"benar|salah\"}; opsi A-D boleh kosong atau diabaikan. "
                f"{style_block}{manual_clause}{image_clause}"
                f"Pastikan setiap stimulus unik dan akhiri pembahasan setiap soal dengan kalimat \\\"Kode: {uniqueness_hint}\\\" agar mudah dilacak.\n"
                "Format keluaran HANYA berupa JSON valid tanpa teks tambahan:\n"
                '{"stimulus":[{"title":"Judul Stimulus","narrative":"...", "image_prompt":"...", '
                '"questions":[{"prompt":"...", "topic":"...", "difficulty":"easy|medium|hard", "question_type":"multiple_choice|true_false", '
                '"options":[{"key":"A","text":"..."},...], "answer":"A", "explanation":"...", '
                '"statements":[{"text":"...", "answer":"benar"}]}]}]}'
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
