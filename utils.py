# utils.py
import re
from datetime import datetime
from langchain_core.messages import HumanMessage, AIMessage

# ⬇️ Regex untuk mendeteksi markdown gambar ![](url)
IMG_MD = re.compile(r'!\[[^\]]*\]\((https?://[^\s)]+)\)')



def normalize_input(text):
    if not isinstance(text, str):
        text = str(text)
    text = text.lower()
    replacements = {
        "umur pendaftar": "umur",
        "usia pendaftar": "umur",
        "usia siswa": "umur",
        "umur siswa": "umur",
        "pendaftar termuda": "umur terendah",
        "pendaftar tertua": "umur tertinggi",
        "usia paling muda": "umur terendah",
        "usia paling tua": "umur tertinggi",
        "ranking": "urutan",
        "anbk untuk sd kapan": "anbk untuk sd jadwalnya kapan",
        "kapan anbk sd": "jadwal anbk sd",
        "anbk sd kapan": "jadwal anbk sd",
        "jadwal anbk": "jadwal anbk sd",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def strip_markdown(text):
    if not isinstance(text, str):
        text = str(text or "")
    try:
        text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
        text = re.sub(r"#+\s*", "", text)
        return text
    except Exception:
        return str(text)


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def format_history_for_chain(history):
    """Ubah (role, text) dari DB menjadi list of LangChain Message."""
    messages = []
    for role, text in history:
        if role == "user":
            messages.append(HumanMessage(content=text))
        else:
            messages.append(AIMessage(content=text))
    return messages


def coerce_to_text(result_obj):
    if result_obj is None:
        return ""
    if isinstance(result_obj, str):
        return result_obj
    if hasattr(result_obj, "content") and isinstance(result_obj.content, str):
        return result_obj.content
    if isinstance(result_obj, dict):
        for key in ("answer", "output_text", "result", "text"):
            if key in result_obj and isinstance(result_obj[key], str):
                return result_obj[key]
    return str(result_obj)


