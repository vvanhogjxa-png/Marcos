import os
import logging
import requests
import zipfile
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ParseMode

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATA_FILE = "data.txt"
INDEX_FILE = "search_index.txt"

ADMIN_IDS = list(map(int, os.environ.get("ADMIN_IDS", "123456789").split(",")))  # يمكن إضافة أكثر من Admin ID مفصول بفاصلة
REDEEM_CODES = set()

SUPPORTED_LINKS = [
    "gofile.io",
    "drive.google.com",
    "mega.nz",
    "mediafire.com",
    "dropbox.com",
]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سلام! 👋\n\n"
        "📎 بعثلي رابط الملف أو TXT/ZIP مباشرة\n"
        "⬇️ أنا نحملو أوتوماتيك\n"
        "🔍 بعدها بعثلي أي كلمة نبحث ليك فيها\n\n"
        "جرب دابا!"
    )


def extract_zip_if_needed(file_path):
    if not file_path.lower().endswith(".zip"):
        return file_path

    extract_folder = "extracted_files"
    os.makedirs(extract_folder, exist_ok=True)

    with zipfile.ZipFile(file_path, "r") as zip_ref:
        zip_ref.extractall(extract_folder)

    merged_file = DATA_FILE

    with open(merged_file, "w", encoding="utf-8", errors="ignore") as outfile:
        for root, _, files in os.walk(extract_folder):
            for file in files:
                if file.lower().endswith(".txt"):
                    txt_path = os.path.join(root, file)
                    try:
                        with open(txt_path, "r", encoding="utf-8", errors="ignore") as infile:
                            outfile.write(f"\n===== {file} =====\n")
                            outfile.write(infile.read())
                            outfile.write("\n")
                    except Exception:
                        pass

    return merged_file


def build_search_index():
    if not os.path.exists(DATA_FILE):
        return

    unique_lines = set()

    with open(DATA_FILE, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            clean_line = line.strip()
            if clean_line:
                unique_lines.add(clean_line.lower() + "|||" + clean_line)

    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        for item in unique_lines:
            f.write(item + "\n")


def download_file(url, output_path):
    response = requests.get(url, stream=True, timeout=60)
    response.raise_for_status()

    with open(output_path, "wb") as file:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                file.write(chunk)


async def process_loaded_file(update: Update):
    build_search_index()

    with open(DATA_FILE, "r", encoding="utf-8", errors="ignore") as f:
        line_count = sum(1 for _ in f)

    await update.message.reply_text(
        f"✅ الفايل تحمل بنجاح!\n"
        f"📊 عدد الأسطر: {line_count:,}\n\n"
        f"🔍 دابا بعثلي الكلمة اللي بغيتي تبحث عليها"
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if any(link in text for link in SUPPORTED_LINKS):
        await update.message.reply_text(
            "⬇️ جاري تحميل الملف...\n⏳ المرجو الانتظار"
        )

        try:
            temp_file = "downloaded_file"
            download_file(text, temp_file)

            final_file = extract_zip_if_needed(temp_file)

            if final_file != DATA_FILE:
                if os.path.exists(DATA_FILE):
                    os.remove(DATA_FILE)
                os.rename(final_file, DATA_FILE)

            await process_loaded_file(update)

        except Exception as e:
            error_text = str(e)

            if "Too many users have viewed or downloaded this file recently" in error_text:
                await update.message.reply_text(
                    "❌ Google Drive رفض التحميل حالياً

"
                    "السبب: الملف تجاوز حد التحميل اليومي من Google Drive.

"
                    "الحلول:
"
                    "1. انتظر عدة ساعات ثم جرّب مرة أخرى
"
                    "2. انسخ الملف إلى Drive آخر جديد
"
                    "3. استعمل رابط Gofile بدل Google Drive (أفضل وأسرع)"
                )
            else:
                await update.message.reply_text(
                    f"❌ مشكل في التحميل:
{error_text}"
                )
        return

    if not os.path.exists(INDEX_FILE):
        await update.message.reply_text(
            "❌ ما عندي فايل محفوظ أولاً. بعثلي ملف أو رابط أولاً."
        )
        return

    keyword = text
    await run_search(update, keyword)


async def run_search(update: Update, keyword: str):
    progress_msg = await update.message.reply_text(
        "🔍 بدء البحث...\n\n📊 Progress: 0%"
    )

    results = []

    try:
        with open(INDEX_FILE, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        total_lines = len(lines)

        for i, line in enumerate(lines, start=1):
            parts = line.rstrip("\n").split("|||", 1)
            if len(parts) != 2:
                continue

            searchable, original = parts

            if keyword.lower() in searchable:
                results.append(original)

            if i % max(1, total_lines // 10) == 0:
                percentage = (i / max(total_lines, 1)) * 100
                filled = int(20 * percentage / 100)
                bar = "█" * filled + "░" * (20 - filled)

                await progress_msg.edit_text(
                    f"🔍 جاري البحث...\n\n"
                    f"[{bar}] {percentage:.1f}%\n"
                    f"📄 الأسطر: {i}/{total_lines}\n"
                    f"🎯 النتائج الحالية: {len(results)}\n"
                    f"⚡ Fast Indexed Search"
                )

    except Exception as e:
        await update.message.reply_text(f"❌ خطأ أثناء البحث: {e}")
        return

    if not results:
        await progress_msg.edit_text(
            f"😕 ما لقيت والو على '{keyword}'."
        )
        return

    result_file = "resultat.txt"
    with open(result_file, "w", encoding="utf-8") as f:
        f.write(f"نتائج البحث على: {keyword}\n")
        f.write(f"عدد النتائج: {len(results):,}\n")
        f.write("=" * 50 + "\n\n")

        for line in results[:5000]:
            f.write(line + "\n")

    await progress_msg.edit_text(
        f"✅ البحث اكتمل!\n\n🎯 عدد النتائج: {len(results):,}"
    )

    await update.message.reply_document(
        document=open(result_file, "rb"),
        filename="resultat.txt",
        caption=f"✅ لقيت *{len(results):,}* نتيجة على '{keyword}'",
        parse_mode=ParseMode.MARKDOWN,
    )


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "استعمل هكذا:\n/search keyword"
        )
        return

    keyword = " ".join(context.args)

    if not os.path.exists(INDEX_FILE):
        await update.message.reply_text(
            "❌ ما عندي ملف محفوظ أولاً."
        )
        return

    await run_search(update, keyword)


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⛔ تم إيقاف العملية الحالية.")


async def redeem_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "استعمل هكذا:\n/redeem CODE"
        )
        return

    code = context.args[0]

    if code in REDEEM_CODES:
        REDEEM_CODES.remove(code)
        await update.message.reply_text("✅ تم تفعيل الكود بنجاح!")
    else:
        await update.message.reply_text(
            "❌ الكود غير صحيح أو مستعمل من قبل."
        )


async def gkey_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ هذا الأمر فقط للمالك.")
        return

    import random
    import string

    code = "".join(
        random.choices(string.ascii_uppercase + string.digits, k=10)
    )
    REDEEM_CODES.add(code)

    await update.message.reply_text(
        f"🔑 الكود الجديد:\n`{code}`",
        parse_mode=ParseMode.MARKDOWN,
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document

    if not document:
        await update.message.reply_text("❌ ما توصلت بأي ملف.")
        return

    file_name = document.file_name.lower()

    if not (file_name.endswith(".txt") or file_name.endswith(".zip")):
        await update.message.reply_text(
            "❌ فقط ملفات TXT أو ZIP مسموحة."
        )
        return

    progress_msg = await update.message.reply_text(
        "⬇️ جاري تحميل الملف من Telegram...\n\n📊 Progress: 0%"
    )

    telegram_file = await context.bot.get_file(document.file_id)
    temp_path = f"uploaded_{document.file_name}"

    await telegram_file.download_to_drive(temp_path)

    await progress_msg.edit_text(
        "🔄 جاري تجهيز الملف...\n⚡ Fast Mode"
    )

    final_file = extract_zip_if_needed(temp_path)

    if final_file != DATA_FILE:
        if os.path.exists(DATA_FILE):
            os.remove(DATA_FILE)
        os.rename(final_file, DATA_FILE)

    build_search_index()

    with open(DATA_FILE, "r", encoding="utf-8", errors="ignore") as f:
        line_count = sum(1 for _ in f)

    await progress_msg.edit_text(
        f"✅ تم رفع الملف بنجاح!\n\n"
        f"📄 عدد الأسطر: {line_count:,}\n"
        f"⚡ Fast Indexed Search جاهز"
    


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(CommandHandler("redeem", redeem_command))
    app.add_handler(CommandHandler("gkey", gkey_command))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("البوت شغال! ✅")
    app.run_polling()


if __name__ == "__main__":
    main()
