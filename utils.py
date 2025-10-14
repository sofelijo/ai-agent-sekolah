# utils.py
import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

from telegram import Message, Update
from langchain_core.messages import HumanMessage, AIMessage

from thinking_messages import get_random_thinking_message

try:
    from zoneinfo import ZoneInfo
except (ImportError, ModuleNotFoundError):
    ZoneInfo = None

if ZoneInfo is not None:
    try:
        JAKARTA_TZ = ZoneInfo("Asia/Jakarta")
    except Exception:
        JAKARTA_TZ = None
    try:
        UTC_TZ = ZoneInfo("UTC")
    except Exception:
        UTC_TZ = timezone.utc
else:
    JAKARTA_TZ = None
    UTC_TZ = timezone.utc


# Regex untuk mendeteksi markdown gambar ![](url)
IMG_MD = re.compile(r'!\\\\[^\\]*?\\]\((https?://[^\s)]+)\)')

KNOWN_BOT_HANDLES = {"@ss01ju_bot", "@tanyaaska_bot"}

INDONESIAN_DAY_NAMES = {
    0: "Senin",
    1: "Selasa",
    2: "Rabu",
    3: "Kamis",
    4: "Jumat",
    5: "Sabtu",
    6: "Minggu",
}

INDONESIAN_MONTH_NAMES = {
    1: "Januari",
    2: "Februari",
    3: "Maret",
    4: "April",
    5: "Mei",
    6: "Juni",
    7: "Juli",
    8: "Agustus",
    9: "September",
    10: "Oktober",
    11: "November",
    12: "Desember",
}


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
        text = re.sub(r"#+\\s*", "", text)
        return text
    except Exception:
        return str(text)


_SIGNATURE_RE = re.compile(r"(?:\s*\n)?[-–—]\s*ASKA\s*$", re.IGNORECASE)


def remove_trailing_signature(text: Optional[str]) -> str:
    """Remove trailing '- ASKA' style signatures from model output."""
    if not isinstance(text, str):
        text = str(text or "")
    cleaned = _SIGNATURE_RE.sub("", text)
    return cleaned.rstrip()


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def format_history_for_chain(history: List[Dict[str, Any]]) -> list:
    """Ubah list of dict dari DB menjadi list of LangChain Message."""
    messages = []
    # The new DB function returns newest first, but the chain needs oldest first.
    for row in reversed(history):
        role = row.get('role')
        text = row.get('text')
        if role == "user":
            messages.append(HumanMessage(content=text))
        elif role:
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


def current_jakarta_time() -> datetime:
    if JAKARTA_TZ is not None:
        try:
            return datetime.now(JAKARTA_TZ)
        except Exception:
            pass
    return datetime.now()


def to_jakarta(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if not isinstance(dt, datetime):
        return dt
    if JAKARTA_TZ is None:
        return dt
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC_TZ)
        return dt.astimezone(JAKARTA_TZ)
    except Exception:
        return dt

def format_indonesian_date(dt: datetime) -> str:
    month_name = INDONESIAN_MONTH_NAMES.get(dt.month, dt.strftime("%B"))
    return f"{dt.day} {month_name} {dt.year}"

def detect_class_code(text: str) -> Optional[str]:
    if not text:
        return None
    if re.search(r"(?:kelas\\s*)?(?:5|v)[\\s-]*a", text):
        return "5a"
    return None

def rewrite_schedule_query(text: str) -> str:
    if not text:
        return text
    lowered = text.lower()
    if "jadwal" not in lowered:
        return text
    if not any(keyword in lowered for keyword in ("besok", "besoknya", "esok")):
        return text
    class_code = detect_class_code(lowered)
    if not class_code:
        return text
    now = current_jakarta_time()
    target = now + timedelta(days=1)
    day_name = INDONESIAN_DAY_NAMES.get(target.weekday(), target.strftime("%A"))
    date_label = format_indonesian_date(target)
    replacements = {
        "besoknya": f"hari {day_name} ({date_label})",
        "besok": f"hari {day_name} ({date_label})",
        "esok": f"hari {day_name} ({date_label})",
    }
    updated = text
    for key, value in replacements.items():
        updated = re.sub(rf"\\b{key}\\b", value, updated)
    note = f"(menanyakan jadwal kelas {class_code.upper()} hari {day_name} {date_label})"
    if note not in updated:
        updated = f"{updated} {note}".strip()
    return updated

def iter_message_texts_and_entities(message: Optional[Message]):
    if message is None:
        return
    if message.text:
        yield message.text, message.entities or []
    if message.caption:
        yield message.caption, message.caption_entities or []

def replace_bot_mentions(text: Optional[str], bot_username: Optional[str] = None) -> Optional[str]:
    if not text:
        return text
    handles = {alias.lower() for alias in KNOWN_BOT_HANDLES}
    if bot_username:
        handles.add(f"@{bot_username.lower()}")

    pattern = re.compile(r"@[\\w_]+")

    def repl(match):
        mention = match.group(0)
        if mention.lower() in handles:
            return "ASKA"
        return mention

    return pattern.sub(repl, text)

def is_substantive_text(text: Optional[str]) -> bool:
    if not text:
        return False
    cleaned = text.strip()
    if not cleaned:
        return False
    lowered = cleaned.lower()
    trivial_phrases = {"aska", "hai aska", "halo aska", "jawab aska", "tolong aska"}
    if lowered in trivial_phrases:
        return False
    tokens = re.findall(r"\\w+", lowered)
    if not tokens:
        return False
    question_words = {"apa", "siapa", "mengapa", "kenapa", "bagaimana", "dimana", "kapan", "kok"}
    if '?' in cleaned or question_words.intersection(tokens):
        return True
    filler_tokens = {"aska", "dong", "ya", "yah", "pls", "please", "tolong", "jawab", "deh", "donglah"}
    meaningful_tokens = [tok for tok in tokens if tok not in filler_tokens]
    return len(meaningful_tokens) >= 2

def is_group_chat(update: Update) -> bool:
    chat = update.effective_chat
    return chat is not None and chat.type in ("group", "supergroup")

def is_reply_to_bot(message: Message, bot_id):
    reply = getattr(message, "reply_to_message", None)
    return bool(reply and reply.from_user and reply.from_user.id == bot_id)

def has_bot_mention(message: Optional[Message], bot_username: Optional[str], bot_id):
    if not message:
        return False
    mention_token = f"@{bot_username.lower()}" if bot_username else None
    texts_and_entities = list(iter_message_texts_and_entities(message))
    if not texts_and_entities:
        return False
    for text, entities in texts_and_entities:
        lower_text = text.lower()
        for entity in entities:
            if entity.type == "text_mention" and entity.user and entity.user.id == bot_id:
                return True
            if entity.type == "mention" and mention_token:
                entity_text = text[entity.offset: entity.offset + entity.length]
                if entity_text.lower() == mention_token:
                    return True
        if mention_token and mention_token in lower_text:
            return True
    return False

def extract_message_text(message: Optional[Message]) -> Optional[str]:
    if message is None:
        return None
    if message.text:
        return message.text
    if message.caption:
        return message.caption
    return None

def should_respond(update: Update, bot) -> bool:
    if not is_group_chat(update):
        return True
    message = update.effective_message
    if not message:
        return False
    bot_id = getattr(bot, "id", None)
    bot_username = getattr(bot, "username", None)
    return is_reply_to_bot(message, bot_id) or has_bot_mention(message, bot_username, bot_id)

def resolve_target_message(update: Update, bot):
    message = update.effective_message
    if not message:
        return None, None
    target_message = message
    if is_group_chat(update):
        reply = getattr(message, "reply_to_message", None)
        bot_id = getattr(bot, "id", None)
        bot_username = getattr(bot, "username", None)
        if (
            reply
            and not getattr(getattr(reply, "from_user", None), "is_bot", False)
            and has_bot_mention(message, bot_username, bot_id)
            and extract_message_text(reply)
        ):
            target_message = reply
    return message, target_message

def prepare_group_query(
    trigger_message: Optional[Message],
    target_message: Optional[Message],
    bot_username: Optional[str],
):
    primary = target_message or trigger_message
    if trigger_message is None and primary is None:
        return None, None, None, None

    trigger_text_raw = extract_message_text(trigger_message) if trigger_message else None
    target_text_raw = extract_message_text(target_message) if target_message else None
    trigger_text = replace_bot_mentions(trigger_text_raw, bot_username) if trigger_text_raw else None
    target_text = replace_bot_mentions(target_text_raw, bot_username) if target_text_raw else None

    use_trigger = (
        trigger_message is not None
        and target_message is not None
        and trigger_message != target_message
        and is_substantive_text(trigger_text)
    )

    if use_trigger:
        parts = []
        if target_text:
            parts.append(target_text.strip())
        if trigger_text:
            parts.append(trigger_text.strip())
        combined = "\n\n".join(part for part in parts if part)
        reply_target = trigger_message
        target_user = getattr(trigger_message, "from_user", None)
        responded_key = getattr(trigger_message, "message_id", None)
        return combined or trigger_text or target_text, reply_target, target_user, responded_key

    reply_target = primary
    target_user = getattr(primary, "from_user", None) if primary else None
    responded_key = getattr(primary, "message_id", None) if primary else None
    text_to_use = target_text or trigger_text
    return text_to_use, reply_target, target_user, responded_key


async def send_typing_once(bot, chat_id, delay: float = 0.5):
    await bot.send_chat_action(chat_id=chat_id, action="typing")
    if delay:
        await asyncio.sleep(delay)


async def keep_typing_indicator(bot, chat_id, interval: float = 2.0):
    while True:
        try:
            await bot.send_chat_action(chat_id=chat_id, action="typing")
            await asyncio.sleep(interval)
        except Exception:
            break


async def send_thinking_bubble(target_message: Optional[Message]):
    if target_message is None:
        return None
    message_text = get_random_thinking_message()
    message = await target_message.reply_text(message_text)
    print(f"[{now_str()}] {message_text}")
    return message


async def send_and_update_thinking_bubble(target_message: Optional[Message], stop_event: asyncio.Event):
    if target_message is None:
        return None
    
    message = None
    loop_count = 0
    try:
        while not stop_event.is_set() and loop_count < 3: # Limit to 3 updates (15 seconds)
            thinking_message = get_random_thinking_message()
            if message is None:
                message = await target_message.reply_text(thinking_message)
                print(f"[{now_str()}] {thinking_message}")
            else:
                await message.edit_text(thinking_message)
                print(f"[{now_str()}] {thinking_message}")
            
            loop_count += 1
            
            try:
                # Wait for 5 seconds or until the stop event is set
                await asyncio.wait_for(stop_event.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass # Continue the loop
    except Exception as e:
        print(f"[{now_str()}] Error in thinking bubble: {e}")
    
    return message


async def reply_with_markdown(target_message: Optional[Message], text: Optional[str]) -> None:
    if target_message is None:
        return
    if text is None:
        text = ''
    try:
        await target_message.reply_text(text, parse_mode='Markdown')
    except Exception as exc:
        print(f"[{now_str()}] Failed to send Markdown message: {exc}")
        fallback = strip_markdown(text) if text else ''
        await target_message.reply_text(fallback)
