import os
import re
import logging
import gdown
import zipfile
import shutil
from pathlib import Path
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATA_DIR = "extracted_files"
ZIP_FILE = "data.zip"

def extract_drive_id(url):
    """استخرج ID من رابط Google Drive"""
    patterns = [
        r"/file/d/([a-zA-Z0-9_-]+)",
        r"id=([a-zA-Z0-9_-]+)",
        r"/open\?id=([a-zA-Z0-9_-]+)"
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سلام! 👋\n\n"
        "📦 بعثلي رابط Google Drive ديال ZIP file\n"
        "⬇️ أنا نحملو ونستخرج الـ TXT files\n"
        "🔍 بعدها بعثلي أي كلمة نبحث ليك فيها\n\n"
        "جرب دابا!"
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # إذا كان رابط Google Drive
    if "drive.google.com" in text:
        file_id = extract_drive_id(text)
        if not file_id:
            await update.message.reply_text("❌ الرابط ما صحيحش. تحقق منو وعاود.")
            return

        await update.message.reply_text("⬇️ بدات نحمل الـ ZIP... هاد العملية تاخد وقت (3GB كبيرة).")

        try:
            # حمل الـ ZIP
            url = f"https://drive.google.com/uc?id={file_id}"
            gdown.download(url, ZIP_FILE, quiet=False, fuzzy=True)

            # تنظيف الفولدر القديم
            if os.path.exists(DATA_DIR):
                shutil.rmtree(DATA_DIR)
            os.makedirs(DATA_DIR, exist_ok=True)

            # استخرج الـ ZIP
            await update.message.reply_text("⏳ كنستخرج الـ TXT files... صبر شوية.")
            with zipfile.ZipFile(ZIP_FILE, 'r') as zip_ref:
                zip_ref.extractall(DATA_DIR)

            # عد الـ TXT files
            txt_files = list(Path(DATA_DIR).rglob("*.txt"))
            total_lines = 0
            for txt_file in txt_files:
                try:
                    with open(txt_file, "r", encoding="utf-8", errors="ignore") as f:
                        total_lines += sum(1 for _ in f)
                except:
                    pass

            await update.message.reply_text(
                f"✅ الـ ZIP استخرج بنجاح!\n"
                f"📄 عدد الـ TXT files: {len(txt_files)}\n"
                f"📊 عدد الليني: {total_lines:,}\n\n"
                f"دابا بعثلي الكلمة اللي بغيتي تبحث عليها 🔍"
            )

        except Exception as e:
            await update.message.reply_text(
                f"❌ مشكل:\n{str(e)[:100]}\n\n"
                "تحقق أن الفايل ZIP وأنو shared"
            )
        return

    # إذا كانت كلمة للبحث
    if not os.path.exists(DATA_DIR):
        await update.message.reply_text("❌ ما عندي ZIP محفوظ. بعثلي رابط Google Drive أولاً.")
        return

    keyword = text
    await update.message.reply_text(f"🔍 كنبحث على: *{keyword}*...", parse_mode="Markdown")

    results = []
    try:
        txt_files = list(Path(DATA_DIR).rglob("*.txt"))
        for txt_file in txt_files:
            try:
                with open(txt_file, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if keyword.lower() in line.lower():
                            results.append(line.rstrip("\n"))
            except:
                pass
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")
        return

    if not results:
        await update.message.reply_text(f"😕 ما لقيت والو على '{keyword}'.")
        return

    # كتب النتائج
    result_file = "resultat.txt"
    with open(result_file, "w", encoding="utf-8") as f:
        f.write(f"نتائج البحث على: {keyword}\n")
        f.write(f"عدد النتائج: {len(results):,}\n")
        f.write("=" * 50 + "\n\n")
        for line in results[:5000]:  # أول 5000 نتيجة
            f.write(line + "\n")
        if len(results) > 5000:
            f.write(f"\n... و {len(results) - 5000:,} نتيجة أخرى")

    await update.message.reply_document(
        document=open(result_file, "rb"),
        filename="resultat.txt",
        caption=f"✅ لقيت *{len(results):,}* نتيجة على '{keyword}'",
        parse_mode="Markdown"
    )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚠️ بعثلي رابط Google Drive مباشرة في الرسالة."
    )

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("البوت شغال! ✅")
    app.run_polling()

if __name__ == "__main__":
    main()
