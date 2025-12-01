from __future__ import annotations

import base64
import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from datetime import datetime, timedelta, timezone
from math import ceil
from typing import Any, Dict, List, Optional
from typing import Any, Dict, List, Optional

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from dashboard.auth import current_user, login_required, role_required
from langchain_openai import ChatOpenAI
from werkzeug.datastructures import MultiDict
from utils import (
    current_jakarta_time,
    to_jakarta,
)
from db import (
    DEFAULT_TKA_COMPOSITE_DURATION,
    DEFAULT_TKA_GRADE_LEVEL,
    DEFAULT_TKA_PRESET_KEY,
    GRADE_LABELS,
    TKA_PRESET_LABELS,
    TKA_PRESET_LABELS,
    TKA_SECTION_TEMPLATES,
    VALID_TKA_GRADE_LEVELS,
)
from .queries import (
    create_tka_mapel,
    fetch_tka_attempts,
    create_tka_questions,
    create_tka_stimulus,
    create_tka_test,
    create_tka_test_subject,
    delete_tka_mapel,
    delete_tka_test,
    delete_tka_test_subject,
    fetch_tka_mapel,
    fetch_tka_mapel_list,
    fetch_tka_questions,
    fetch_tka_stimulus,
    fetch_tka_stimulus_list,
    fetch_tka_test,
    fetch_tka_test_subject,
    fetch_tka_test_subjects,
    fetch_tka_tests,
    set_tka_test_grade_level,
    update_tka_test_subject_topics,
    delete_tka_question,
    update_tka_stimulus,
    delete_tka_stimulus,
    update_tka_question,
)
from . import tka_bp

_TKA_AI_CHAIN = None
_TKA_AI_CHAIN_FAILED = False

GRADE_LEVEL_HINTS = {
    "sd6": "siswa kelas 6 SD",
    "smp3": "siswa kelas 3 SMP",
    "sma": "siswa SMA",
}

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



# --- Latihan TKA admin routes -----------------------------------------------


@tka_bp.route("/latihan-tka")
@login_required
@role_required("admin")
def latihan_tka_bank():
    subjects = fetch_tka_mapel_list(include_inactive=True)
    return render_template(
        "TKA/latihan_tka.html",
        subjects=subjects,
        grade_labels=GRADE_LABELS,
        section_templates=TKA_SECTION_TEMPLATES,
        default_duration=DEFAULT_TKA_COMPOSITE_DURATION,
    )


@tka_bp.route("/latihan-tka/buat-soal")
@login_required
@role_required("admin")
def latihan_tka_manual():
    subjects = fetch_tka_mapel_list(include_inactive=True)
    tests = fetch_tka_tests()
    return render_template(
        "TKA/latihan_tka_manual.html",
        subjects=subjects,
        tests=tests,
        grade_labels=GRADE_LABELS,
        section_templates=TKA_SECTION_TEMPLATES,
        default_duration=DEFAULT_TKA_COMPOSITE_DURATION,
    )


@tka_bp.route("/latihan-tka/tests-ui", methods=["GET", "POST"])
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
            return redirect(url_for("tka.latihan_tka_tests"))
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
            return redirect(url_for("tka.latihan_tka_tests"))
        delete_test_subject_id = request.form.get("delete_test_subject_id", type=int)
        if delete_test_subject_id:
            form_test_id = request.form.get("delete_test_subject_test_id", type=int)
            redirect_args = {}
            if form_test_id:
                redirect_args["test_id"] = form_test_id
            if not form_test_id or not delete_test_subject_id:
                flash("Pilih tes terlebih dahulu sebelum menghapus mapel.", "danger")
                return redirect(url_for("tka.latihan_tka_tests", **redirect_args))
            try:
                if delete_tka_test_subject(form_test_id, delete_test_subject_id):
                    flash("Mapel dihapus dari tes.", "success")
                else:
                    flash("Mapel tes tidak ditemukan.", "danger")
            except Exception as exc:
                current_app.logger.error("Gagal menghapus mapel tes %s/%s: %s", form_test_id, delete_test_subject_id, exc)
                flash("Gagal menghapus mapel tes.", "danger")
            return redirect(url_for("tka.latihan_tka_tests", **redirect_args))
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
                return redirect(url_for("tka.latihan_tka_tests", **redirect_args))
            if not total_questions or total_questions <= 0:
                flash("Target soal mapel harus lebih dari 0.", "danger")
                return redirect(url_for("tka.latihan_tka_tests", **redirect_args))
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
                    return redirect(url_for("tka.latihan_tka_tests", **redirect_args))
                test_record = fetch_tka_test(form_test_id)
                if not test_record:
                    flash("Tes tidak ditemukan.", "danger")
                    return redirect(url_for("tka.latihan_tka_tests"))
                mapel_grade = (mapel_record.get("grade_level") or "").strip().lower() or None
                test_grade = (test_record.get("grade_level") or "").strip().lower() or None
                if not mapel_grade:
                    flash("Mapel belum memiliki jenjang.", "danger")
                    return redirect(url_for("tka.latihan_tka_tests", **redirect_args))
                if test_grade and test_grade != mapel_grade:
                    label_mapel = GRADE_LABELS.get(mapel_grade, mapel_grade.upper())
                    label_test = GRADE_LABELS.get(test_grade, test_grade.upper())
                    flash(f"Tes ini khusus jenjang {label_test}. Mapel yang dipilih berjenjang {label_mapel}.", "danger")
                    return redirect(url_for("tka.latihan_tka_tests", **redirect_args))
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
                return redirect(url_for("tka.latihan_tka_tests", **redirect_args))
            except Exception as exc:
                current_app.logger.error("Gagal menambah mapel ke tes melalui form: %s", exc)
                flash("Gagal menambahkan mapel ke tes.", "danger")
                return redirect(url_for("tka.latihan_tka_tests", **redirect_args))
            flash("Mapel berhasil disimpan ke tes.", "success")
            return redirect(url_for("tka.latihan_tka_tests", **redirect_args))
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
                    return redirect(url_for("tka.latihan_tka_tests"))
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
                    return redirect(url_for("tka.latihan_tka_tests"))
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
        "TKA/latihan_tka_tests.html",
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


@tka_bp.route("/latihan-tka/generator", defaults={"mode": "lite"})
@tka_bp.route("/latihan-tka/generator/<string:mode>")
@login_required
@role_required("admin")
def latihan_tka_generator_page(mode: str):
    normalized_mode = (mode or "lite").strip().lower()
    if normalized_mode not in {"lite", "pro"}:
        normalized_mode = "lite"
    template_name = (
        "TKA/latihan_tka_generator_pro.html"
        if normalized_mode == "pro"
        else "TKA/latihan_tka_generator_lite.html"
    )
    return render_template(
        template_name,
        grade_labels=GRADE_LABELS,
        section_templates=TKA_SECTION_TEMPLATES,
        default_duration=DEFAULT_TKA_COMPOSITE_DURATION,
        generator_mode=normalized_mode,
    )


@tka_bp.route("/latihan-tka/hasil")
@login_required
@role_required("admin")
def latihan_tka_results():
    subjects = fetch_tka_mapel_list(include_inactive=True)
    return render_template("TKA/latihan_tka_results.html", subjects=subjects, grade_labels=GRADE_LABELS)


@tka_bp.route("/latihan-tka/questions")
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


@tka_bp.route("/latihan-tka/questions/<int:question_id>/preview")
@login_required
@role_required("admin")
def latihan_tka_preview_question(question_id: int):
    records = fetch_tka_questions(question_id=question_id, limit=1)
    if not records:
        flash("Soal tidak ditemukan atau sudah dihapus.", "warning")
        return redirect(url_for("tka.latihan_tka_bank"))
    question = records[0]
    metadata = question.get("metadata") or {}
    answer_format = (question.get("answer_format") or metadata.get("answer_format") or "multiple_choice").lower()
    tf_statements = metadata.get("true_false_statements") or metadata.get("true_false") or []
    section_label = metadata.get("section_label") or question.get("mapel_name") or "Latihan TKA"
    image_url = metadata.get("image_url") or question.get("image_url") or (question.get("stimulus") or {}).get("image_url")
    stimulus = question.get("stimulus") or {}
    if "narrative" in stimulus and "text" not in stimulus:
        stimulus["text"] = stimulus["narrative"]
    if image_url and not stimulus.get("image_url"):
        stimulus = {**stimulus, "image_url": image_url}
    question_payload = {
        "id": question.get("id"),
        "global_index": 1,
        "difficulty": question.get("difficulty") or "easy",
        "topic": question.get("topic"),
        "section_label": section_label,
        "answer_format": answer_format,
        "true_false_statements": tf_statements,
        "options": question.get("options") or [],
        "prompt": question.get("prompt") or "",
        "image_url": None if stimulus.get("image_url") else image_url,
    }
    package = {"stimulus": stimulus, "questions": [question_payload]}
    now = datetime.now(timezone.utc)
    deadline = now + timedelta(minutes=15)
    grade_value = (metadata.get("grade_level") or question.get("grade_level") or "").lower()
    grade_label = GRADE_LABELS.get(grade_value) if grade_value else None
    attempt_stub = {"id": f"preview-{question_id}"}
    user_info = current_user() or {"full_name": "Admin"}
    return render_template(
        "TKA/latihan_tka_session.html",
        user=user_info,
        attempt=attempt_stub,
        questions=[question_payload],
        question_packages=[package],
        question_total=1,
        deadline_iso=deadline.isoformat(),
        server_time=now.isoformat(),
        repeat_label=None,
        preset_label="Preview",
        grade_label=grade_label or grade_value,
        sections=[],
    )


@tka_bp.route("/latihan-tka/stimulus")
@login_required
@role_required("admin")
def latihan_tka_stimulus():
    mapel_id = request.args.get("mapel_id", type=int)
    test_id = request.args.get("test_id", type=int)
    if not mapel_id and not test_id:
        return jsonify({"success": False, "message": "mapel_id atau test_id wajib diisi."}), 400
    stimulus = fetch_tka_stimulus_list(mapel_id=mapel_id, test_id=test_id)
    return jsonify({"success": True, "stimulus": stimulus})


@tka_bp.route("/latihan-tka/stimulus/create", methods=["POST"])
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


@tka_bp.route("/latihan-tka/stimulus/generate", methods=["POST"])
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


@tka_bp.route("/latihan-tka/stimulus/<int:stimulus_id>", methods=["PUT"])
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


@tka_bp.route("/latihan-tka/stimulus/<int:stimulus_id>", methods=["DELETE"])
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


@tka_bp.route("/latihan-tka/questions", methods=["POST"])
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
        inserted_count = create_tka_questions(
            questions=questions,
            created_by=created_by,
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
    return jsonify({"success": True, "inserted": inserted_count})


@tka_bp.route("/latihan-tka/questions/<int:question_id>", methods=["DELETE"])
@login_required
@role_required("admin")
def latihan_tka_delete_question(question_id: int):
    try:
        success = delete_tka_question(question_id)
    except Exception as exc:
        current_app.logger.error("Gagal menghapus soal %s: %s", question_id, exc)
        return jsonify({"success": False, "message": "Gagal menghapus soal."}), 500
    if not success:
        return jsonify({"success": False, "message": "Soal tidak ditemukan."}), 404
    return jsonify({"success": True})


@tka_bp.route("/latihan-tka/questions/<int:question_id>", methods=["PUT"])
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


@tka_bp.route("/latihan-tka/questions/check-duplicate", methods=["POST"])
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
        exists = has_tka_question_with_prompt(prompt, test_subject_id=test_subject_id)
    except Exception as exc:
        current_app.logger.error("Gagal mengecek duplikat soal: %s", exc)
        return jsonify({"success": False, "message": "Gagal mengecek duplikat."}), 500
    return jsonify({"success": True, "exists": exists})


@tka_bp.route("/latihan-tka/subjects/<int:subject_id>/difficulty", methods=["POST"])
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


@tka_bp.route("/latihan-tka/subjects/<int:subject_id>/sections", methods=["POST"])
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


@tka_bp.route("/latihan-tka/generate", methods=["POST"])
@login_required
@role_required("admin")
def latihan_tka_generate():
    return _handle_tka_generate_request(return_stimulus=True)


@tka_bp.route("/latihan-tka/generate_soal_new", methods=["POST"])
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
    if grade_level not in VALID_TKA_GRADE_LEVELS:
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


@tka_bp.route("/latihan-tka/results/data")
@login_required
@role_required("admin")
def latihan_tka_results_data():
    mapel_id = request.args.get("subject_id", type=int)  # Frontend still sends subject_id for now
    status = request.args.get("status")
    search = request.args.get("search")
    attempts = fetch_tka_attempts(
        mapel_id=mapel_id,
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


@tka_bp.route("/latihan-tka/tests", methods=["GET"])
@login_required
@role_required("admin")
def latihan_tka_list_tests():
    tests = fetch_tka_tests()
    return jsonify({"success": True, "tests": tests})


@tka_bp.route("/latihan-tka/tests/<int:test_id>", methods=["DELETE"])
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


@tka_bp.route("/latihan-tka/tests", methods=["POST"])
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


@tka_bp.route("/latihan-tka/tests/<int:test_id>/subjects", methods=["GET"])
@login_required
@role_required("admin")
def latihan_tka_test_subjects(test_id: int):
    try:
        subjects = fetch_tka_test_subjects(test_id)
    except Exception as exc:
        current_app.logger.error("Gagal memuat mapel tes %s: %s", test_id, exc)
        return jsonify({"success": False, "message": "Gagal memuat mapel tes."}), 500
    return jsonify({"success": True, "subjects": subjects})


@tka_bp.route("/latihan-tka/tests/<int:test_id>/subjects", methods=["POST"])
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


@tka_bp.route("/latihan-tka/tests/<int:test_id>/subjects/<int:test_subject_id>", methods=["DELETE"])
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


@tka_bp.route("/latihan-tka/tests/<int:test_id>/subjects/<int:test_subject_id>/topics", methods=["PUT"])
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


@tka_bp.route("/latihan-tka/mapel", methods=["GET"])
@login_required
@role_required("admin")
def latihan_tka_list_mapel():
    data = fetch_tka_mapel_list()
    return jsonify({"success": True, "mapel": data})


@tka_bp.route("/latihan-tka/mapel", methods=["POST"])
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


@tka_bp.route("/latihan-tka/mapel/<int:mapel_id>", methods=["DELETE"])
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
