"""Fitur mode guru: memberi soal dan menilai jawaban siswa kelas 4-6."""

from __future__ import annotations

import json
import os
import random
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - import guard untuk lingkungan tanpa OpenAI SDK
    OpenAI = None  # type: ignore[misc,assignment]


@dataclass(frozen=True)
class PracticeQuestion:
    question: str
    answer: str
    subject: str
    grade_min: int
    grade_max: int
    explanation: str
    answer_keywords: tuple[str, ...] = ()
    choices: tuple[str, ...] = ()
    source: str = "static"

    def matches_grade(self, grade_hint: Optional[int]) -> bool:
        if grade_hint is None:
            return True
        return self.grade_min <= grade_hint <= self.grade_max


_SUBJECT_KEYWORDS: Dict[str, tuple[str, ...]] = {
    "Matematika": ("matematika", "mtk", "berhitung", "pecahan", "bangun", "geometri", "angka", "mat", "aljabar"),
    "IPA": ("ipa", "sains", "ilmu pengetahuan alam", "tumbuhan", "hewan", "energi", "perubahan wujud", "biologi", "fisika"),
    "IPS": ("ips", "sejarah", "geografi", "ekonomi", "sosial", "kewilayahan", "peta", "kerajaan"),
    "Bahasa Indonesia": ("bahasa indonesia", "b indonesia", "bi", "kalimat", "antonim", "sinonim", "tata bahasa", "puisi", "paragraf"),
    "PPKN": ("ppkn", "pkn", "pancasila", "semboyan", "hukum", "warga negara", "aturan", "norma"),
    "Agama": ("agama", "akhlak", "ibadah", "kitab suci", "nabi", "alquran", "quran", "al-quran"),
    "SBdP": ("seni budaya", "sbdp", "musik", "gambar", "tari", "lagu daerah"),
}

_DEFAULT_SUBJECT = "Campuran"


_LLM_MODEL = os.getenv("ASKA_TEACHER_MODEL") or os.getenv("ASKA_QA_MODEL") or "llama-3.1-8b-instant"
_LLM_TEMPERATURE = float(os.getenv("ASKA_TEACHER_TEMPERATURE", "0.6"))
_LLM_MAX_OUTPUT_TOKENS = int(os.getenv("ASKA_TEACHER_MAX_TOKENS", "600"))
_llm_client: Optional[OpenAI] = None
_llm_client_failed = False
_LLM_API_BASE = (
    os.getenv("ASKA_TEACHER_API_BASE")
    or os.getenv("ASKA_OPENAI_API_BASE")
    or os.getenv("OPENAI_API_BASE")
    or os.getenv("ASKA_GROQ_API_BASE")
    or "https://api.groq.com/openai/v1"
)


def _get_llm_client() -> Optional[OpenAI]:
    global _llm_client, _llm_client_failed
    if _llm_client_failed:
        return None
    if OpenAI is None:
        return None
    if _llm_client is None:
        api_key = (
            os.getenv("ASKA_TEACHER_API_KEY")
            or os.getenv("GROQ_API_KEY")
            or os.getenv("OPENAI_API_KEY")
        )
        if not api_key:
            print("[TEACHER] GROQ_API_KEY atau OPENAI_API_KEY belum di-set; mode guru dinonaktifkan.")
            _llm_client_failed = True
            return None
        try:
            _llm_client = OpenAI(api_key=api_key, base_url=_LLM_API_BASE)
        except Exception as exc:  # pragma: no cover - kegagalan koneksi/API
            print(f"[TEACHER] Gagal inisialisasi klien Groq/OpenAI-compatible: {exc}")
            _llm_client_failed = True
            return None
    return _llm_client


def extract_subject_hint(text: str) -> Optional[str]:
    if not text:
        return None
    lowered = text.lower()
    for subject, keywords in _SUBJECT_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return subject
    return None


def _normalize_subject(subject: Optional[str]) -> Optional[str]:
    if not subject:
        return None
    subject_lower = subject.lower()
    for canonical, keywords in _SUBJECT_KEYWORDS.items():
        if subject_lower == canonical.lower() or any(subject_lower == keyword for keyword in keywords):
            return canonical
    return subject.title()


def _sanitize_topic_hint(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"[\n\r]+", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


_DISCUSSION_KEYWORDS: tuple[str, ...] = (
    "jelasin",
    "jelaskan",
    "kenapa",
    "mengapa",
    "bagaimana",
    "tolong bantu",
    "nggak paham",
    "ga paham",
    "gak paham",
    "bingung",
    "contoh lain",
    "langkahnya",
    ### PENAMBAHAN GEN Z ###
    "gimana caranya",
    "maksudnya apa",
    "jelasin lagi",
    "kok bisa gitu",
)

_MAX_CONVERSATION_TURNS = 10


_QUESTIONS: tuple[PracticeQuestion, ...] = (
    PracticeQuestion(
        subject="Matematika",
        grade_min=4,
        grade_max=5,
        question="Hasil dari 84 : 7 adalah berapa?",
        answer="12",
        explanation="84 dibagi 7 sama dengan 12 karena 7 × 12 = 84.",
    ),
    PracticeQuestion(
        subject="Matematika",
        grade_min=4,
        grade_max=6,
        question="Sebuah persegi punya keliling 24 cm. Berapa panjang tiap sisinya?",
        answer="6",
        explanation="Keliling persegi = 4 × sisi. Jadi sisi = 24 : 4 = 6 cm.",
    ),
    PracticeQuestion(
        subject="Matematika",
        grade_min=5,
        grade_max=6,
        question="Hasil dari 3/4 + 1/8 adalah?",
        answer="7/8",
        explanation="Samakan penyebut menjadi 8: 3/4 = 6/8, lalu 6/8 + 1/8 = 7/8.",
        answer_keywords=("tujuh per delapan",),
    ),
    PracticeQuestion(
        subject="IPA",
        grade_min=4,
        grade_max=5,
        question="Bagian tumbuhan yang berfungsi menyerap air dan mineral dari tanah adalah?",
        answer="akar",
        explanation="Akar menyerap air dan mineral sekaligus menegakkan tumbuhan.",
    ),
    PracticeQuestion(
        subject="IPA",
        grade_min=5,
        grade_max=6,
        question="Perubahan wujud benda dari gas menjadi cair disebut apa?",
        answer="mengembun",
        explanation="Perubahan gas menjadi cair disebut mengembun.",
        answer_keywords=("kondensasi",),
    ),
    PracticeQuestion(
        subject="IPS",
        grade_min=4,
        grade_max=5,
        question="Pulau terbesar di Indonesia adalah pulau apa?",
        answer="Kalimantan",
        explanation="Pulau terbesar di Indonesia adalah Kalimantan.",
        answer_keywords=("borneo",),
    ),
    PracticeQuestion(
        subject="IPS",
        grade_min=5,
        grade_max=6,
        question="Proklamasi kemerdekaan Indonesia dibacakan pada tanggal berapa?",
        answer="17 Agustus 1945",
        explanation="Proklamasi kemerdekaan dibacakan 17 Agustus 1945.",
        answer_keywords=("17 agustus", "17-08-1945", "17/08/1945"),
    ),
    PracticeQuestion(
        subject="Bahasa Indonesia",
        grade_min=4,
        grade_max=5,
        question="Antonim dari kata 'tinggi' adalah apa?",
        answer="rendah",
        explanation="Lawan kata 'tinggi' adalah 'rendah'.",
    ),
    PracticeQuestion(
        subject="Bahasa Indonesia",
        grade_min=5,
        grade_max=6,
        question="Sebutkan jenis kalimat yang menyatakan perintah!",
        answer="kalimat imperatif",
        explanation="Kalimat yang berisi perintah disebut kalimat imperatif.",
        answer_keywords=("imperatif",),
    ),
    PracticeQuestion(
        subject="PPKN",
        grade_min=4,
        grade_max=6,
        question="Apa semboyan negara Indonesia yang tercantum pada lambang Garuda?",
        answer="Bhinneka Tunggal Ika",
        explanation="Semboyan Indonesia adalah 'Bhinneka Tunggal Ika'.",
        answer_keywords=("bhineka tunggal ika",),
    ),
)

_START_KEYWORDS: tuple[str, ...] = (
    "kasih soal",
    "minta soal",
    "latihan dong",
    "aku mau belajar",
    "jadi guru",
    "mode guru",
    "tes dong",
    "quiz dong",
    "kuis dong",
    "beri soal",
    "latihan belajar",
    ### PENAMBAHAN GEN Z ###
    "ayo belajar",
    "ajarin dong",
    "kasih kuis",
    "guru mode on",
)

_STOP_KEYWORDS: tuple[str, ...] = (
    "selesai",
    "stop",
    "cukup",
    "sudah",
    "terima kasih gurunya",
    "keluar mode guru",
    ### PENAMBAHAN GEN Z ###
    "udahan",
    "udah dulu",
    "makasih guru",
    "selesai belajar",
    "done",
)

_NEXT_KEYWORDS: tuple[str, ...] = (
    "soal berikut",
    "lanjut soal",
    "lanjut dong",
    "next",
    "skip",
    "ganti soal",
    ### PENAMBAHAN GEN Z ###
    "soal lagi",
    "lagi dong",
    "ganti",
    "lanjut",
)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _normalize_answer(text: str) -> str:
    text = _normalize_text(text)
    text = text.replace(",", "").replace(".", "")
    text = re.sub(r"[^a-z0-9/ ]", "", text)
    return text.strip()


def _call_llm_chat(
    messages: Sequence[Dict[str, str]],
    *,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> Optional[str]:
    client = _get_llm_client()
    if client is None:
        return None
    try:
        response = client.chat.completions.create(
            model=_LLM_MODEL,
            messages=list(messages),
            temperature=temperature if temperature is not None else _LLM_TEMPERATURE,
            max_tokens=max_tokens or _LLM_MAX_OUTPUT_TOKENS,
        )
    except Exception as exc:  # pragma: no cover - kegagalan jaringan/API
        print(f"[TEACHER] Gagal memanggil OpenAI chat: {exc}")
        return None
    choice = response.choices[0] if response.choices else None
    if not choice or not getattr(choice, "message", None):
        return None
    return choice.message.content


def _parse_llm_json(raw: Optional[str]) -> Optional[Dict[str, object]]:
    if not raw:
        return None
    candidate = raw.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?", "", candidate, flags=re.IGNORECASE).strip()
        if candidate.endswith("```"):
            candidate = candidate[:-3].strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", candidate, flags=re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
    return None


def extract_grade_hint(text: str) -> Optional[int]:
    if not text:
        return None
    lowered = text.lower()
    match = re.search(r"kelas\s*(?:ke\s*)?(\d)", lowered)
    if not match:
        return None
    try:
        grade = int(match.group(1))
    except ValueError:
        return None
    if 1 <= grade <= 12:
        return grade
    return None


def is_teacher_start(text: str) -> bool:
    if not text:
        return False
    lowered = _normalize_text(text)
    return any(keyword in lowered for keyword in _START_KEYWORDS)


def is_teacher_stop(text: str) -> bool:
    if not text:
        return False
    lowered = _normalize_text(text)
    return any(keyword in lowered for keyword in _STOP_KEYWORDS)


def is_teacher_next(text: str) -> bool:
    if not text:
        return False
    lowered = _normalize_text(text)
    return any(keyword in lowered for keyword in _NEXT_KEYWORDS)


def is_teacher_discussion_request(text: str) -> bool:
    if not text:
        return False
    if "?" in text:
        return True
    lowered = text.lower()
    return any(keyword in lowered for keyword in _DISCUSSION_KEYWORDS)


def _grade_range_text(grade_hint: Optional[int]) -> str:
    if grade_hint is None:
        return "kelas 4 sampai 6"
    return f"kelas {grade_hint}"


def _generate_llm_question(
    grade_hint: Optional[int],
    subject_hint: Optional[str],
    topic_hint: str,
) -> Optional[PracticeQuestion]:
    client = _get_llm_client()
    if client is None:
        return None

    grade_text = _grade_range_text(grade_hint)
    subject_text = subject_hint or _DEFAULT_SUBJECT
    topic_text = topic_hint or "materi kurikulum sekolah dasar"

    system_prompt = (
        "Kamu adalah guru SD kelas 4-6 yang super seru ala Gen Z. "
        "Buat soal latihan singkat yang ramah anak, tetap sesuai kurikulum Indonesia, dan gunakan bahasa santai, positif, penuh semangat. "
        "Selipkan emoji yang relevan dan pastikan soal serta penjelasan mudah dipahami. "
        "Sertakan jawaban singkat, penjelasan ringkas, serta beberapa kata kunci jawaban."
    )
    user_prompt = (
        "Buat satu soal latihan untuk {grade_text} dengan mata pelajaran {subject_text}. "
        "Materi yang diminta pengguna: {topic_text}. "
        "Formatkan jawabanmu dalam JSON berikut tanpa teks tambahan:\n"
        "{{\n"
        '  "subject": "Matematika",\n'
        '  "grade_min": 4,\n'
        '  "grade_max": 4,\n'
        '  "question": "....",\n'
        '  "answer": "....",\n'
        '  "explanation": "....",\n'
        '  "answer_keywords": ["..."],\n'
        '  "choices": ["...","..."]\n'
        "}}\n"
        "Jika bukan pilihan ganda, kosongkan daftar choices."
    ).format(grade_text=grade_text, subject_text=subject_text, topic_text=topic_text)

    raw = _call_llm_chat(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
        max_tokens=_LLM_MAX_OUTPUT_TOKENS,
    )
    data = _parse_llm_json(raw)
    if not data:
        return None

    question_text = str(data.get("question", "")).strip()
    answer_text = str(data.get("answer", "")).strip()
    explanation_text = str(data.get("explanation", "")).strip()
    if not question_text or not answer_text or not explanation_text:
        return None

    try:
        grade_min = int(data.get("grade_min") or grade_hint or 4)
        grade_max = int(data.get("grade_max") or grade_hint or grade_min)
    except Exception:
        grade_min = grade_hint or 4
        grade_max = grade_hint or max(grade_min, 6)
    grade_min = max(1, min(6, grade_min))
    grade_max = max(grade_min, min(6, grade_max))

    subject_value = str(data.get("subject") or subject_hint or subject_text).strip()
    subject_canonical = _normalize_subject(subject_value) or subject_value or _DEFAULT_SUBJECT

    keywords_raw = data.get("answer_keywords") or ()
    if isinstance(keywords_raw, str):
        keywords = tuple(_normalize_answer(keyword) for keyword in keywords_raw.split(",") if keyword.strip())
    elif isinstance(keywords_raw, Sequence):
        keywords = tuple(_normalize_answer(str(keyword)) for keyword in keywords_raw if str(keyword).strip())
    else:
        keywords = ()
    keywords = tuple(filter(None, keywords))

    choices_raw = data.get("choices") or ()
    if isinstance(choices_raw, Sequence) and not isinstance(choices_raw, (str, bytes)):
        choices = tuple(str(choice).strip() for choice in choices_raw if str(choice).strip())
    else:
        choices = ()

    return PracticeQuestion(
        subject=subject_canonical,
        grade_min=grade_min,
        grade_max=grade_max,
        question=question_text,
        answer=answer_text,
        explanation=explanation_text,
        answer_keywords=keywords,
        choices=choices,
        source="llm",
    )


def pick_question(
    grade_hint: Optional[int] = None,
    subject_hint: Optional[str] = None,
    topic_hint: Optional[str] = None,
) -> PracticeQuestion:
    subject_canonical = _normalize_subject(subject_hint)
    topic_text = _sanitize_topic_hint(topic_hint or "")

    generated = _generate_llm_question(grade_hint, subject_canonical, topic_text)
    if generated:
        return generated

    candidates = [q for q in _QUESTIONS if q.matches_grade(grade_hint)]
    if subject_canonical:
        subject_lower = subject_canonical.lower()
        subject_filtered = [q for q in candidates if q.subject.lower() == subject_lower]
        if subject_filtered:
            candidates = subject_filtered
    if not candidates:
        candidates = list(_QUESTIONS)
    return random.choice(candidates)


def grade_response(question: PracticeQuestion, user_answer: str) -> tuple[bool, str]:
    if not user_answer:
        return False, "Coba jawab dulu ya, nanti ASKA koreksi."

    normalized = _normalize_answer(user_answer)
    expected = _normalize_answer(question.answer)

    possible_answers: list[str] = [expected]
    possible_answers.extend(_normalize_answer(opt) for opt in question.answer_keywords)

    if normalized in possible_answers:
        message = (
            "Mantap, jawaban kamu benar! "
            f"Penjelasan: {question.explanation}"
        )
        return True, message

    if question.source == "llm":
        evaluation = _evaluate_answer_with_llm(question, user_answer)
        if evaluation:
            return evaluation

    feedback = (
        "Belum tepat nih. "
        f"Jawaban yang benar: {question.answer}. "
        f"Penjelasan: {question.explanation}"
    )
    return False, feedback


def _evaluate_answer_with_llm(
    question: PracticeQuestion,
    user_answer: str,
) -> Optional[tuple[bool, str]]:
    client = _get_llm_client()
    if client is None:
        return None

    payload = {
        "question": question.question,
        "expected_answer": question.answer,
        "answer_keywords": list(question.answer_keywords),
        "teacher_explanation": question.explanation,
        "student_answer": user_answer,
    }
    system_prompt = (
        "Kamu adalah guru SD kelas 4-6 bergaya Gen Z yang suportif. "
        "Nilailah jawaban siswa secara positif, tentukan benar/salah, lalu beri umpan balik singkat dengan bahasa santai dan emoji seperlunya. "
        "Jelaskan alasannya secara ringkas agar siswa paham. Balas hanya dalam format JSON."
    )
    user_prompt = json.dumps(payload, ensure_ascii=False)

    raw = _call_llm_chat(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=350,
    )
    data = _parse_llm_json(raw)
    if not data:
        return None

    is_correct = bool(data.get("is_correct"))
    feedback = str(data.get("feedback") or "").strip()

    if not feedback:
        feedback = (
            "Jawaban kamu sudah tepat! Penjelasan: "
            f"{question.explanation}"
            if is_correct
            else f"Belum tepat. Jawaban yang benar: {question.answer}. Penjelasan: {question.explanation}"
        )

    return is_correct, feedback


def generate_discussion_reply(
    question: PracticeQuestion,
    history: Sequence[Dict[str, str]],
    user_message: str,
) -> str:
    client = _get_llm_client()
    if client is None:
        return (
            "Penjelasan singkatnya begini: "
            f"{question.explanation}"
        )

    system_prompt = (
        "Kamu adalah guru SD kelas 4-6 yang sabar, suportif, dan vibes Gen Z. "
        "Bantu siswa memahami soal berikut dengan bahasa Indonesia santai, penuh semangat, dan sisipkan emoji yang relevan. "
        "Berikan contoh sederhana bila perlu, ajak siswa berpikir langkah demi langkah, dan jangan buat mereka minder.\n\n"
        f"Soal: {question.question}\n"
        f"Jawaban benar: {question.answer}\n"
        f"Penjelasan inti: {question.explanation}"
    )

    messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]

    if history:
        for turn in history[-_MAX_CONVERSATION_TURNS:]:
            role = turn.get("role")
            content = turn.get("content")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": user_message})

    response_text = _call_llm_chat(
        messages,
        temperature=0.7,
        max_tokens=_LLM_MAX_OUTPUT_TOKENS,
    )
    if not response_text:
        return (
            "Intinya: "
            f"{question.explanation}"
        )
    return response_text.strip()


def format_question_intro(question: PracticeQuestion, attempt_number: int = 1) -> str:
    prefix = (
        "Halo! ASKA lagi jadi gurumu, yuk kita latihan 😎📚\n"
        if attempt_number == 1
        else ""
    )
    grade_label = (
        f"kelas {question.grade_min}"
        if question.grade_min == question.grade_max
        else f"kelas {question.grade_min} - {question.grade_max}"
    )
    choices_text = ""
    if question.choices:
        options = "\n".join(f"- {choice}" for choice in question.choices)
        choices_text = f"\nPilih salah satu jawaban berikut:\n{options}"

    source_note = (
        "\n(Soal ini dibuat otomatis oleh guru AI ASKA.)"
        if question.source == "llm"
        else ""
    )

    return (
        f"{prefix}"
        f"Soal {question.subject} ({grade_label}):\n"
        f"{question.question}"
        f"{choices_text}\n\n"
        "Tulis jawabanmu di sini ya! Kalau bingung, tinggal tanya atau minta penjelasan. "
        "Ketik 'skip' buat ganti soal, atau 'stop' kalau mau selesai. Semangat! ✨"
        f"{source_note}"
    )
