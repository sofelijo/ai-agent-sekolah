# bot_sekolah.py
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
from telegram import Update
from telegram.ext import ContextTypes

from ai_core import build_qa_chain
from db import save_chat, get_chat_history
from utils import (
    normalize_input,
    strip_markdown,
    now_str,
    format_history_for_chain,
    coerce_to_text,
    IMG_MD,
)
from responses import (
    ASKA_NO_DATA_RESPONSE,
    ASKA_TECHNICAL_ISSUE_RESPONSE,
    get_acknowledgement_response,
    get_farewell_response,
    get_greeting_response,
    get_self_intro_response,
    get_status_response,
    get_thank_you_response,
    is_acknowledgement_message,
    is_farewell_message,
    is_greeting_message,
    is_self_intro_message,
    is_status_message,
    is_thank_you_message,
)

import os
import time
import asyncio
import tempfile
from openai import OpenAI
from dotenv import load_dotenv
from thinking_messages import get_random_thinking_message

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
qa_chain = build_qa_chain()
audio_client = OpenAI()
STT_MODELS = []
_env_model = os.getenv("OPENAI_STT_MODEL")
if _env_model:
    STT_MODELS.append(_env_model)
if "gpt-4o-mini-transcribe" not in STT_MODELS:
    STT_MODELS.append("gpt-4o-mini-transcribe")
if "whisper-1" not in STT_MODELS:
    STT_MODELS.append("whisper-1")


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


async def send_thinking_bubble(update: Update):
    message_text = get_random_thinking_message()
    message = await update.message.reply_text(message_text)
    print(f"[{now_str()}] {message_text}")
    return message


def _transcribe_audio(path: str) -> str:
    last_error = None
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


async def handle_user_query(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_input: str,
    *,
    source: str = "text",
):
    try:
        raw_input = user_input or ""
        normalized_input = normalize_input(raw_input)
        user_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.first_name or "anon"

        print(
            f"[{now_str()}] HANDLER CALLED ({source.upper()}) - FROM {username}: {normalized_input}"
        )

        processed_messages = context.user_data.setdefault("processed_messages", set())
        if normalized_input in processed_messages:
            print(f"[{now_str()}] DUPLICATE MESSAGE DETECTED - SKIPPING")
            return
        processed_messages.add(normalized_input)

        print(f"[{now_str()}] SAVING USER MESSAGE")
        topic = source if source != "text" else None
        save_chat(user_id, username, normalized_input, role="user", topic=topic)

        if is_greeting_message(normalized_input):
            await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
            response = get_greeting_response()
            await update.message.reply_text(response, parse_mode="Markdown")
            save_chat(user_id, "ASKA", response, role="aska")
            return

        if is_thank_you_message(normalized_input):
            await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
            response = get_thank_you_response()
            await update.message.reply_text(response, parse_mode="Markdown")
            save_chat(user_id, "ASKA", response, role="aska")
            return

        if is_acknowledgement_message(normalized_input):
            await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
            response = get_acknowledgement_response()
            await update.message.reply_text(response)
            save_chat(user_id, "ASKA", response, role="aska")
            return

        if is_farewell_message(normalized_input):
            await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
            response = get_farewell_response()
            await update.message.reply_text(response)
            save_chat(user_id, "ASKA", response, role="aska")
            return

        if is_self_intro_message(normalized_input):
            await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
            response = get_self_intro_response()
            await update.message.reply_text(response)
            save_chat(user_id, "ASKA", response, role="aska")
            return

        if is_status_message(normalized_input):
            await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
            response = get_status_response()
            await update.message.reply_text(response)
            save_chat(user_id, "ASKA", response, role="aska")
            return

        await send_typing_once(context.bot, update.effective_chat.id, delay=0)
        print(f"[{now_str()}] ASKA sedang mengetik...")

        history_from_db = get_chat_history(user_id, limit=5)
        chat_history = format_history_for_chain(history_from_db)

        start_time = time.perf_counter()

        typing_task = asyncio.create_task(
            keep_typing_indicator(context.bot, update.effective_chat.id)
        )

        try:
            thinking_message = await send_thinking_bubble(update)
            await asyncio.sleep(1.0)
            result = qa_chain.invoke({"input": normalized_input, "chat_history": chat_history})
        finally:
            typing_task.cancel()

        print(f"[{now_str()}] \U0001F4DA ASKA AMBIL {len(result['context'])} KONTEN:")
        for i, doc in enumerate(result["context"], 1):
            print(f"  {i}. {doc.page_content[:200]}...")

        response = coerce_to_text(result)

        if not response.strip():
            response = ASKA_NO_DATA_RESPONSE

        try:
            await thinking_message.delete()
            print(f"[{now_str()}] Thinking bubble deleted")
        except Exception as e:
            print(f"[{now_str()}] Failed to delete thinking bubble: {e}")

        match = IMG_MD.search(response)
        if match:
            img_url = match.group(1)
            caption = IMG_MD.sub("", response).strip()[:1024]
            caption = strip_markdown(caption)
            await update.message.reply_photo(photo=img_url, caption=caption)
        else:
            clean_response = strip_markdown(response)
            await update.message.reply_text(clean_response)

        duration_ms = (time.perf_counter() - start_time) * 1000
        print(f"[{now_str()}] ASKA : {response} ⏱️ {duration_ms:.2f} ms")
        save_chat(
            user_id,
            "ASKA",
            strip_markdown(response),
            role="aska",
            topic=source if source != "text" else None,
            response_time_ms=int(duration_ms),
        )

    except Exception as e:
        print(f"[{now_str()}] [ERROR] {e}")

        try:
            if "thinking_message" in locals():
                await thinking_message.delete()
        except Exception:
            pass

        await update.message.reply_text(
            ASKA_TECHNICAL_ISSUE_RESPONSE,
            parse_mode="Markdown",
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_typing_once(context.bot, update.effective_chat.id)

    user = update.effective_user
    name = user.first_name or user.username or "bestie"
    response = (
        f"Yoo, {name}! 🫶\n"
        f"Aku *ASKA*, bestie AI kamu 🤖✨\n"
        f"Mau tanya apa aja soal sekolah? Gaskeun~ 🚀"
    )
    await update.message.reply_text(response, parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_user_query(update, context, update.message.text or "", source="text")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    voice = update.message.voice or update.message.audio
    if not voice:
        await update.message.reply_text("Oops, suaranya belum kebaca. Coba kirim ulang ya! 🎤")
        return

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp_file:
        temp_path = tmp_file.name

    try:
        telegram_file = await context.bot.get_file(voice.file_id)
        await telegram_file.download_to_drive(custom_path=temp_path)
        transcription = await asyncio.to_thread(_transcribe_audio, temp_path)
    except Exception as exc:
        print(f"[{now_str()}] [VOICE ERROR] {exc}")
        await update.message.reply_text(
            "ASKA belum bisa dengerin pesan suara kamu nih. Boleh dicoba lagi atau ketik aja ya!"
        )
        return
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass

    if not transcription or not transcription.strip():
        await update.message.reply_text(
            "ASKA nggak nangkep isi pesan suaranya. Coba rekam ulang dengan suara lebih jelas ya!"
        )
        return

    await handle_user_query(update, context, transcription.strip(), source="voice")


app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("ASKA AKTIF...")
app.run_polling()
