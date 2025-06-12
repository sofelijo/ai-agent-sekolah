import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

from ai_core import build_qa_chain

# Load token dari .env
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Siapkan AI Agent
qa_chain = build_qa_chain()

# Handle perintah /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Halo! Saya *AI SDN Semper Barat 01*. Silakan ketik pertanyaan.",
        parse_mode="Markdown"
    )

# Handle pesan biasa
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text
    response = qa_chain.run(user_input)
    await update.message.reply_text(response)

# Jalankan bot
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("Bot Telegram jalan...")
app.run_polling()
