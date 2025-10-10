# bot_sekolah.py
import logging
import os

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters

from handlers import handle_message, handle_voice, start

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("ASKA AKTIF...")
app.run_polling()