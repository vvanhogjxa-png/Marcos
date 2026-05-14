import os
import re
import logging
import gdown
import zipfile
import shutil
import json
import time
import threading
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_IDS = list(map(int, os.environ.get("ADMIN_IDS", "0").split(",")))
DATA_DIR = "extracted_files"
ZIP_FILE = "data.zip"
CODES_FILE = "access_codes.json"
USERS_FILE = "users_db.json"
STATS_FILE = "stats.json"
DRIVE_LINKS_FILE = "saved_drives.json"

ACCESS_CODES = {}
USERS_DB = {}
STATS = {}

# ============================================================
# ⚡ FAST INDEX WITH THREADING
# ============================================================
SEARCH_INDEX = defaultdict(list)
INDEX_BUILT = False
INDEX_TOTAL_LINES = 0
INDEX_LOCK = threading.Lock()

def index_file(txt_file):
    """معالجة ملف واحد بشكل متوازي"""
    local_index = defaultdict(list)
    line_count = 0
    
    try:
        with open(txt_file, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line:
                    line_count += 1
                    parts = re.split(r'[\s:@|]+', line.lower())
                    unique_parts = set(parts)
                    for part in unique_parts:
                        if len(part) >= 2:
                            local_index[part].append(line)
    except:
        pass
    
    return local_index, line_count

def build_search_index():
    global SEARCH_INDEX, INDEX_BUILT, INDEX_TOTAL_LINES
    
    with INDEX_LOCK:
        SEARCH_INDEX = defaultdict(list)
        INDEX_TOTAL_LINES = 0

    txt_files = list(Path(DATA_DIR).rglob("*.txt"))
    
    if not txt_files:
        INDEX_BUILT = True
        return
    
    start_time = time.time()
    max_workers = min(8, len(txt_files))
    
    logging.info(f"🔄 بناء Index بـ {max_workers} threads للـ {len(txt_files)} ملف...")
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(index_file, f): f for f in txt_files}
        
        for i, future in enumerate(as_completed(futures)):
            try:
                local_index, line_count = future.result()
                
                with INDEX_LOCK:
                    INDEX_TOTAL_LINES += line_count
                    for key, lines in local_index.items():
                        SEARCH_INDEX[key].extend(lines)
                
                percentage = ((i + 1) / len(txt_files)) * 100
                logging.info(f"✅ {i+1}/{len(txt_files)} ({percentage:.0f}%) - {line_count:,} سطر")
            except Exception as e:
                logging.error(f"❌ خطأ: {e}")
    
    elapsed = time.time() - start_time
    INDEX_BUILT = True
    logging.info(f"✅ Index built: {INDEX_TOTAL_LINES:,} lines, {len(SEARCH_INDEX):,} keys in {elapsed:.1f}s")

def fast_search(keyword):
    keyword_lower = keyword.lower()
    results = set()
    
    if keyword_lower in SEARCH_INDEX:
        for line in SEARCH_INDEX[keyword_lower]:
            results.add(line)
    
    for key in SEARCH_INDEX:
        if keyword_lower in key or key in keyword_lower:
            for line in SEARCH_INDEX[key]:
                results.add(line)
    
    return list(results)

# ============================================================
# AUTO LOAD
# ============================================================
def save_drive_link(link):
    links = []
    if os.path.exists(DRIVE_LINKS_FILE):
        try:
            with open(DRIVE_LINKS_FILE) as f:
                links = json.load(f)
        except:
            links = []
    if link not in links:
        links.append(link)
    with open(DRIVE_LINKS_FILE, "w") as f:
        json.dump(links, f)

def auto_load_on_startup():
    global INDEX_BUILT
    
    if not os.path.exists(DRIVE_LINKS_FILE):
        if os.path.exists(DATA_DIR) and list(Path(DATA_DIR).rglob("*.txt")):
            logging.info("🔄 بناء Index من الملفات الموجودة...")
            build_search_index()
        return

    try:
        with open(DRIVE_LINKS_FILE) as f:
            links = json.load(f)
    except:
        return

    if not links:
        return

    last_link = links[-1]
    logging.info(f"🔄 تحميل تلقائي من: {last_link}")

    try:
        file_id = extract_drive_id(last_link)
        if not file_id:
            logging.error("❌ رابط غير صحيح")
            return

        url = f"https://drive.google.com/uc?id={file_id}"
        gdown.download(url, ZIP_FILE, quiet=True, fuzzy=True)

        if os.path.exists(DATA_DIR):
            shutil.rmtree(DATA_DIR)
        os.makedirs(DATA_DIR, exist_ok=True)

        with zipfile.ZipFile(ZIP_FILE, 'r') as z:
            z.extractall(DATA_DIR)

        logging.info("⚡ بناء الـ Index بسرعة...")
        build_search_index()
        logging.info(f"✅ Auto-loaded: {INDEX_TOTAL_LINES:,} lines ready")
    except Exception as e:
        logging.error(f"❌ خطأ: {e}")

# ============================================================
# DATA MANAGEMENT
# ============================================================
def load_all_data():
    global ACCESS_CODES, USERS_DB, STATS
    if os.path.exists(CODES_FILE):
        try:
            with open(CODES_FILE, "r") as f:
                ACCESS_CODES = json.load(f)
        except:
            ACCESS_CODES = {}
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r") as f:
                USERS_DB = json.load(f)
        except:
            USERS_DB = {}
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, "r") as f:
                STATS = json.load(f)
        except:
            STATS = {}

def save_all_data():
    with open(CODES_FILE, "w") as f:
        json.dump(ACCESS_CODES, f)
    with open(USERS_FILE, "w") as f:
        json.dump(USERS_DB, f)
    with open(STATS_FILE, "w") as f:
        json.dump(STATS, f)

def is_code_valid(user_id, code):
    if code not in ACCESS_CODES:
        return False, "❌ الكود غير موجود"
    code_data = ACCESS_CODES[code]
    if code_data["expires_at"]:
        expires = datetime.fromisoformat(code_data["expires_at"])
        if datetime.now() > expires:
            return False, "⏰ الكود انتهت صلاحيته"
    if code_data["max_uses"] > 0 and code_data["used_count"] >= code_data["max_uses"]:
        return False, f"❌ تم استخدام الكود الحد الأقصى"
    return True, "✅ كود صحيح"

def extract_drive_id(url):
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

async def convert_url_to_combo(url):
    try:
        url = url.strip()
        match = re.search(r':([^/:]+:[^/:]+)$', url)
        if match:
            combo = match.group(1).strip()
            if ':' in combo and not combo.startswith(':'):
                return combo
        if url.count(':') >= 3:
            if '/' in url:
                last_part = url.split('/')[-1]
            else:
                last_part = url
            parts = last_part.split(':')
            if len(parts) >= 2:
                combo = ':'.join(parts[-2:]).strip()
                if combo and not combo.startswith(':'):
                    return combo
        return None
    except:
        return None

# ============================================================
# MENUS
# ============================================================
def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("🔍 البحث السريع", callback_data="search")],
        [InlineKeyboardButton("🔄 Combo Converter", callback_data="converter")],
        [InlineKeyboardButton("📊 الإحصائيات", callback_data="stats")],
        [InlineKeyboardButton("⚙️ الإعدادات", callback_data="settings")],
        [InlineKeyboardButton("❓ المساعدة", callback_data="help")],
    ]
    return InlineKeyboardMarkup(keyboard)

# ============================================================
# HANDLERS
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    load_all_data()
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name

    if str(user_id) not in USERS_DB:
        USERS_DB[str(user_id)] = {
            "first_name": first_name,
            "joined": datetime.now().isoformat(),
            "searches": 0,
            "conversions": 0
        }
        save_all_data()

    index_status = f"⚡ Index: {INDEX_TOTAL_LINES:,} سطر جاهز" if INDEX_BUILT else "📭 لا يوجد ملفات"

    welcome_text = (
        f"╔═══════════════════════════════════╗\n"
        f"║   🚀 بوت البحث السريع v7.0 ⚡   ║\n"
        f"║                                   ║\n"
        f"║        مرحباً {first_name} 👋         ║\n"
        f"╚═══════════════════════════════════╝\n\n"
        f"{index_status}\n\n"
        f"🎯 اختر من الخيارات أدناه!"
    )

    await update.message.reply_text(welcome_text, reply_markup=get_main_menu())

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "search":
        await query.edit_message_text(
            text=f"🔍 *وضع البحث السريع*\n\n"
                 f"⚡ {INDEX_TOTAL_LINES:,} سطر جاهز\n\n"
                 f"📝 أرسل كلمة للبحث",
            parse_mode="Markdown"
        )
        context.user_data["mode"] = "search"

    elif query.data == "converter":
        await query.edit_message_text(
            text="🔄 *محول URL إلى Combo*\n\n"
                 "📤 أرسل ملف TXT يحتوي على URLs"
        )
        context.user_data["mode"] = "converter"

    elif query.data == "stats":
        await query.edit_message_text(
            text=f"📊 *الإحصائيات*\n\n"
                 f"⚡ Indexed Lines: {INDEX_TOTAL_LINES:,}\n"
                 f"🗝️ Keywords: {len(SEARCH_INDEX):,}"
        )

    elif query.data == "settings":
        keyboard = [
            [InlineKeyboardButton("🔄 إعادة بناء Index", callback_data="rebuild")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back")]
        ]
        await query.edit_message_text(
            text="⚙️ *الإعدادات*",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data == "rebuild":
        await query.edit_message_text("🔄 جاري إعادة بناء الـ Index...")
        build_search_index()
        await query.edit_message_text(
            f"✅ تم!\n\n⚡ {INDEX_TOTAL_LINES:,} سطر",
            reply_markup=get_main_menu()
        )

    elif query.data == "help":
        await query.edit_message_text(
            text="❓ *المساعدة*\n\n"
                 "🔍 البحث: سريع جداً\n"
                 "🔄 التحويل: URLs لـ combos\n"
                 "📤 الملفات: TXT أو ZIP"
        )

    elif query.data == "back":
        await query.edit_message_text(
            text="🏠 *القائمة الرئيسية*",
            reply_markup=get_main_menu()
        )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global INDEX_BUILT
    
    document = update.message.document
    file_name = document.file_name.lower()
    mode = context.user_data.get("mode", "normal")

    if mode == "converter" and file_name.endswith('.txt'):
        file = await context.bot.get_file(document.file_id)
        await file.download_to_drive("temp_file.txt")

        combos = []
        with open("temp_file.txt", "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        total = len(lines)
        start_time = time.time()
        status_msg = await update.message.reply_text("⏳ جاري المعالجة...\n📊 0%")

        for i, line in enumerate(lines):
            line = line.strip()
            if line:
                combo = await convert_url_to_combo(line)
                if combo:
                    combos.append(combo)

            percentage = ((i + 1) / total) * 100
            if (i + 1) % max(1, total // 10) == 0:
                elapsed = time.time() - start_time
                await status_msg.edit_text(
                    f"⏳ جاري المعالجة...\n"
                    f"📊 {percentage:.0f}%\n"
                    f"✅ Combos: {len(combos):,}\n"
                    f"⚡ {elapsed:.1f}s"
                )

        output_file = "combos_converted.txt"
        with open(output_file, "w", encoding="utf-8") as f:
            for combo in combos:
                f.write(combo + "\n")

        await status_msg.edit_text(
            f"✅ تم!\n\n"
            f"📊 Combos: {len(combos):,}\n"
            f"⚡ {time.time() - start_time:.1f}s"
        )

        await update.message.reply_document(
            document=open(output_file, "rb"),
            filename="combos_converted.txt",
            caption=f"📥 ({len(combos):,})"
        )
        os.remove("temp_file.txt")
        return

    if file_name.endswith('.zip'):
        msg = await update.message.reply_text("📥 جاري رفع...")
        file = await context.bot.get_file(document.file_id)
        await file.download_to_drive(ZIP_FILE)

        await msg.edit_text("🔄 جاري الاستخراج...")

        if os.path.exists(DATA_DIR):
            shutil.rmtree(DATA_DIR)
        os.makedirs(DATA_DIR, exist_ok=True)

        with zipfile.ZipFile(ZIP_FILE, 'r') as z:
            z.extractall(DATA_DIR)

        txt_files = list(Path(DATA_DIR).rglob("*.txt"))
        await msg.edit_text(f"⚡ بناء Index سريع لـ {len(txt_files)} ملف...")

        build_search_index()

        save_drive_link("")  # احفظ أن الـ files موجودة

        await msg.edit_text(
            f"✅ تم!\n\n"
            f"📄 Files: {len(txt_files)}\n"
            f"⚡ Lines: {INDEX_TOTAL_LINES:,}",
            reply_markup=get_main_menu()
        )
        return

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global INDEX_BUILT
    
    load_all_data()
    text = update.message.text.strip()
    mode = context.user_data.get("mode", "normal")

    if mode == "search":
        if not INDEX_BUILT:
            await update.message.reply_text("❌ لا يوجد ملفات!")
            return

        start_time = time.time()
        search_msg = await update.message.reply_text(
            f"⚡ *جاري البحث*\n\n"
            f"🔍 عن: `{text}`",
            parse_mode="Markdown"
        )

        results = fast_search(text)
        elapsed = time.time() - start_time

        if not results:
            await search_msg.edit_text(f"😕 لم نجد نتائج")
            return

        result_file = "resultat.txt"
        with open(result_file, "w", encoding="utf-8") as f:
            for i, line in enumerate(results[:5000], 1):
                f.write(f"{i}. {line}\n")

        await search_msg.edit_text(
            f"✅ تم!\n\n"
            f"📊 {len(results):,} نتيجة\n"
            f"⚡ {elapsed:.2f}s",
            reply_markup=get_main_menu()
        )

        await update.message.reply_document(
            document=open(result_file, "rb"),
            filename=f"results.txt",
            caption=f"🔍 {len(results):,} | ⚡ {elapsed:.2f}s"
        )

def main():
    load_all_data()
    auto_load_on_startup()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("🚀 بوت البحث السريع v7.0 شغال! ✅")
    app.run_polling()

if __name__ == "__main__":
    main()
