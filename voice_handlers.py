import os
import tempfile
import asyncio
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI
from telegram import Update
from telegram.ext import ContextTypes

from utils import now_str, should_respond


load_dotenv()

# Configure STT dengan endpoint OpenAI-compatible (default ke OpenAI Whisper)
_STT_API_KEY = os.getenv("ASKA_STT_API_KEY") or os.getenv("OPENAI_API_KEY")
_STT_API_BASE = os.getenv("ASKA_STT_API_BASE") or "https://api.openai.com/v1"

try:
    audio_client: Optional[OpenAI]
    if _STT_API_KEY:
        audio_client = OpenAI(api_key=_STT_API_KEY, base_url=_STT_API_BASE)
    else:
        audio_client = None
except Exception as exc:
    print(f"[VOICE] Gagal inisialisasi klien STT OpenAI-compatible: {exc}")
    audio_client = None

STT_MODELS: list[str] = []
_env_model = os.getenv("OPENAI_STT_MODEL")
if _env_model:
    STT_MODELS.append(_env_model)
if "gpt-4o-mini-transcribe" not in STT_MODELS:
    STT_MODELS.append("gpt-4o-mini-transcribe")
if "whisper-1" not in STT_MODELS:
    STT_MODELS.append("whisper-1")


def transcribe_audio(path: str) -> str:
    if audio_client is None:
        raise RuntimeError(
            "Speech-to-text belum aktif. Set ASKA_STT_API_KEY atau OPENAI_API_KEY agar STT berjalan."
        )

    last_error: Optional[Exception] = None
    for model in STT_MODELS:
        try:
            with open(path, "rb") as audio_file:
                result = audio_client.audio.transcriptions.create(
                    model=model,
                    file=audio_file,
                    response_format="text",
                )
            if isinstance(result, str):
                text = result
            else:
                text = getattr(result, "text", None)
                if text is None and isinstance(result, dict):
                    text = result.get("text")
            if text:
                return text
        except Exception as exc:  # pragma: no cover - network / API errors
            last_error = exc
            continue
    if last_error:
        raise last_error
    return ""


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return
    if not should_respond(update, context.bot):
        return
    voice = message.voice or message.audio
    if not voice:
        await message.reply_text("Oops, suaranya belum kebaca. Coba kirim ulang ya! ??")
        return

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp_file:
        temp_path = tmp_file.name

    try:
        telegram_file = await context.bot.get_file(voice.file_id)
        await telegram_file.download_to_drive(custom_path=temp_path)
        transcription = await asyncio.to_thread(transcribe_audio, temp_path)
    except Exception as exc:
        print(f"[{now_str()}] [VOICE ERROR] {exc}")
        await message.reply_text(
            "ASKA belum bisa dengerin pesan suara kamu nih. Boleh dicoba lagi atau ketik aja ya!"
        )
        return
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass

    if not transcription or not transcription.strip():
        await message.reply_text(
            "ASKA nggak nangkep isi pesan suaranya. Coba rekam ulang dengan suara lebih jelas ya!"
        )
        return

    # Reuse text handler
    from handlers import handle_user_query  # local import to avoid circular import

    await handle_user_query(
        update,
        context,
        transcription.strip(),
        source="voice",
        reply_target=message,
        target_user=getattr(message, "from_user", None),
    )
