# === main.py ===
import os
import logging
import tempfile

from telegram import Update, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, filters
)
from telegram.constants import ChatAction

from openai import OpenAI
from dotenv import load_dotenv

# === Завантаження змінних середовища ===
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ASSISTANT_ID = os.getenv("ASSISTANT_ID")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

# === Логування ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === OpenAI клієнт ===
client = OpenAI(api_key=OPENAI_API_KEY)

# === Стани для форми зворотного зв'язку ===
TOPIC, NAME, CONTACT = range(3)
user_form_data = {}

# === Старт команди /start з постійною кнопкою ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[KeyboardButton("Залишити контакт")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
    await update.message.reply_text(
        "Я - асистент організації Brama-UA. Надсилай питання текстом, голосом або фото.",
        reply_markup=reply_markup
    )

# === Обробка кнопки «Залишити контакт» ===
async def contact_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Яка тема вашого звернення?")
    return TOPIC

# === Крок 1: користувач вводить тему звернення ===
async def topic_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_form_data[update.effective_user.id] = {"topic": update.message.text}
    await update.message.reply_text("Ваше ім'я:")
    return NAME

# === Крок 2: користувач вводить ім'я ===
async def name_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_form_data[update.effective_user.id]["name"] = update.message.text
    await update.message.reply_text("Контактні дані (телефон, email):")
    return CONTACT

# === Крок 3: контактні дані і надсилання адміну ===
async def contact_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = user_form_data.pop(update.effective_user.id)
    data["contact"] = update.message.text

    text = (
        "📢 <b>Нова заявка:</b>\n"
        f"<b>Тема:</b> {data['topic']}\n"
        f"<b>Ім'я:</b> {data['name']}\n"
        f"<b>Контакт:</b> {data['contact']}"
    )
    await context.bot.send_message(chat_id=ADMIN_ID, text=text, parse_mode="HTML")
    await update.message.reply_text("Дякуємо! Ми зв'яжемося з вами найближчим часом.")
    return ConversationHandler.END

# === Вихід з форми ===
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Скасовано.")
    return ConversationHandler.END

# === Обробка тексту через Assistant API ===
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE, custom_text: str = None):
    await update.message.chat.send_action(action=ChatAction.TYPING)
    thread = client.beta.threads.create()
    user_input = custom_text if custom_text is not None else (update.message.text or "")

    if not user_input.strip():
        await update.message.reply_text("Текст повідомлення порожній. Спробуйте ще раз.")
        return

    client.beta.threads.messages.create(thread.id, role="user", content=user_input)
    run = client.beta.threads.runs.create(thread_id=thread.id, assistant_id=ASSISTANT_ID)

    while run.status != "completed":
        run = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)

    messages = client.beta.threads.messages.list(thread_id=thread.id)
    for m in reversed(messages.data):
        if m.role == "assistant":
            await update.message.reply_text(m.content[0].text.value)
            return

# === Обробка голосових повідомлень ===
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.chat.send_action(action=ChatAction.TYPING)
    file = await context.bot.get_file(update.message.voice.file_id)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as tmp:
        await file.download_to_drive(tmp.name)
        audio_file = open(tmp.name, "rb")

        transcript = client.audio.transcriptions.create(model="whisper-1", file=audio_file)

        if not transcript.text or not transcript.text.strip():
            await update.message.reply_text("Не вдалося розпізнати мову. Спробуйте ще раз.")
            return

        await handle_text(update, context, custom_text=transcript.text)

# === Обробка фото ===
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.chat.send_action(action=ChatAction.UPLOAD_PHOTO)
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
        await file.download_to_drive(tmp.name)
        image_file = open(tmp.name, "rb")

        uploaded_file = client.files.create(file=image_file, purpose="assistants")

        thread = client.beta.threads.create()
        client.beta.threads.messages.create(
            thread.id,
            role="user",
            content=[{
                "type": "image_file",
                "image_file": {
                    "file_id": uploaded_file.id
                }
            }]
        )

        run = client.beta.threads.runs.create(thread_id=thread.id, assistant_id=ASSISTANT_ID)
        while run.status != "completed":
            run = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)

        messages = client.beta.threads.messages.list(thread_id=thread.id)
        for m in reversed(messages.data):
            if m.role == "assistant":
                await update.message.reply_text(m.content[0].text.value)
                return

# === Запуск програми ===
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    form_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^(Залишити контакт)$"), contact_command)],
        states={
            TOPIC: [MessageHandler(filters.TEXT & ~filters.COMMAND, topic_step)],
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, name_step)],
            CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, contact_step)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(form_conv)
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.run_polling()
    logger.info("Бот запущено.")
