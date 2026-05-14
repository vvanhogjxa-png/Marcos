import os
import re
import logging
import gdown
import zipfile
import shutil
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
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
# ✅ FAST INDEX
# ============================================================
SEARCH_INDEX = defaultdict(list)
INDEX_BUILT = False
INDEX_TOTAL_LINES = 0

def build_search_index():
    global SEARCH_INDEX, INDEX_BUILT, INDEX_TOTAL_LINES
    SEARCH_INDEX = defaultdict(list)
    INDEX_TOTAL_LINES = 0

    txt_files = list(Path(DATA_DIR).rglob("*.txt"))
    for txt_file in txt_files:
        try:
            with open(txt_file, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        INDEX_TOTAL_LINES += 1
                        parts = re.split(r'[\s:@|]+', line.lower())
                        unique_parts = set(parts)
                        for part in unique_parts:
                            if len(part) >= 2:
                                SEARCH_INDEX[part].append(line)
        except:
            pass

    INDEX_BUILT = True
    logging.info(f"✅ Index built: {INDEX_TOTAL_LINES} lines, {len(SEARCH_INDEX)} keys")

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
# ✅ AUTO LOAD ON STARTUP
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
            logging.info("🔄 Building index from existing files...")
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
    logging.info(f"🔄 Auto-loading from Drive: {last_link}")

    try:
        file_id = extract_drive_id(last_link)
        if not file_id:
            logging.error("❌ Invalid Drive link saved")
            return

        url = f"https://drive.google.com/uc?id={file_id}"
        gdown.download(url, ZIP_FILE, quiet=True, fuzzy=True)

        if os.path.exists(DATA_DIR):
            shutil.rmtree(DATA_DIR)
        os.makedirs(DATA_DIR, exist_ok=True)

        with zipfile.ZipFile(ZIP_FILE, 'r') as z:
            z.extractall(DATA_DIR)

        build_search_index()
        logging.info(f"✅ Auto-loaded: {INDEX_TOTAL_LINES:,} lines ready")
    except Exception as e:
        logging.error(f"❌ Auto-load failed: {e}")

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
        return False, f"❌ تم استخدام الكود الحد الأقصى ({code_data['max_uses']} مرات)"
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
        [InlineKeyboardButton("🔍 البحث", callback_data="search"), InlineKeyboardButton("📁 الملفات", callback_data="files")],
        [InlineKeyboardButton("🔄 Combo Converter", callback_data="converter"), InlineKeyboardButton("📊 الإحصائيات", callback_data="stats")],
        [InlineKeyboardButton("💳 الاشتراك", callback_data="subscription"), InlineKeyboardButton("⚙️ الإعدادات", callback_data="settings")],
        [InlineKeyboardButton("❓ المساعدة", callback_data="help"), InlineKeyboardButton("🆔 معلوماتي", callback_data="myinfo")],
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
            "status": "free",
            "searches": 0,
            "conversions": 0,
            "access_code": None
        }
        save_all_data()

    index_status = f"⚡ Index: {INDEX_TOTAL_LINES:,} سطر جاهز" if INDEX_BUILT else "📭 لا يوجد ملفات محملة"

    welcome_text = (
        f"╔═══════════════════════════════════╗\n"
        f"║   🤖 بوت البحث والتحويل v6.0 ⚡  ║\n"
        f"║                                   ║\n"
        f"║        مرحباً {first_name} 👋         ║\n"
        f"╚═══════════════════════════════════╝\n\n"
        f"🗄️ {index_status}\n\n"
        f"🎯 اختر من الخيارات أدناه للبدء!"
    )

    await update.message.reply_text(welcome_text, reply_markup=get_main_menu())


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "search":
        index_info = f"⚡ Fast Index: {INDEX_TOTAL_LINES:,} سطر" if INDEX_BUILT else "⚠️ لا يوجد index"
        await query.edit_message_text(
            text=f"🔍 *وضع البحث السريع*\n\n"
                 f"{index_info}\n\n"
                 f"📝 أرسل الكلمة التي تريد البحث عنها",
            parse_mode="Markdown"
        )
        context.user_data["mode"] = "search"

    elif query.data == "converter":
        await query.edit_message_text(
            text="🔄 *محول URL إلى Combo*\n\n"
                 "📤 أرسل ملف TXT يحتوي على URLs\n"
                 "⏳ سأقوم بتحويلها إلى combos\n\n"
                 "📌 مثال URL:\n"
                 "https://my.tod.tv/....:+201206971267:Ah*01062697647\n\n"
                 "📌 سيصبح:\n"
                 "+201206971267:Ah*01062697647"
        )
        context.user_data["mode"] = "converter"

    elif query.data == "stats":
        load_all_data()
        user_id = str(update.effective_user.id)
        user_data = USERS_DB.get(user_id, {})
        index_info = f"⚡ {INDEX_TOTAL_LINES:,} سطر في الـ Index" if INDEX_BUILT else "📭 Index فارغ"

        drive_info = "❌ لا يوجد"
        if os.path.exists(DRIVE_LINKS_FILE):
            try:
                with open(DRIVE_LINKS_FILE) as f:
                    links = json.load(f)
                if links:
                    drive_info = f"✅ {len(links)} رابط محفوظ"
            except:
                pass

        await query.edit_message_text(
            text=f"📊 *إحصائياتك*\n\n"
                 f"🔍 عدد البحثيات: {user_data.get('searches', 0)}\n"
                 f"🔄 عدد التحويلات: {user_data.get('conversions', 0)}\n"
                 f"⭐ النقاط: {(user_data.get('searches', 0) + user_data.get('conversions', 0)) * 10}\n\n"
                 f"🗄️ {index_info}\n"
                 f"🌐 Drive: {drive_info}",
            parse_mode="Markdown"
        )

    elif query.data == "subscription":
        keyboard = [
            [InlineKeyboardButton("🎁 مجاني", callback_data="plan_free"), InlineKeyboardButton("⭐ بريميوم", callback_data="plan_premium")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back")]
        ]
        await query.edit_message_text(
            text="💳 *الخطط*\n\n"
                 "🎁 *مجاني*: بحث أساسي\n"
                 "⭐ *بريميوم*: بحث متقدم + تحويل غير محدود",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data == "settings":
        keyboard = [
            [InlineKeyboardButton("🎟️ إدخال كود", callback_data="enter_code")],
            [InlineKeyboardButton("🔄 إعادة بناء Index", callback_data="rebuild_index")],
            [InlineKeyboardButton("🗑️ حذف Drive المحفوظ", callback_data="clear_drive")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back")]
        ]
        await query.edit_message_text(
            text="⚙️ *الإعدادات*",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif query.data == "rebuild_index":
        if not os.path.exists(DATA_DIR):
            await query.edit_message_text("❌ لا يوجد ملفات محملة بعد")
            return
        await query.edit_message_text("🔄 جاري بناء الـ Index...")
        build_search_index()
        await query.edit_message_text(
            f"✅ تم بناء الـ Index!\n\n"
            f"📊 إجمالي الأسطر: {INDEX_TOTAL_LINES:,}\n"
            f"🗝️ إجمالي الكلمات: {len(SEARCH_INDEX):,}",
            reply_markup=get_main_menu()
        )

    elif query.data == "clear_drive":
        if os.path.exists(DRIVE_LINKS_FILE):
            os.remove(DRIVE_LINKS_FILE)
        await query.edit_message_text(
            "🗑️ تم حذف الـ Drive المحفوظ!\n\n"
            "في المرة القادمة لن يتم التحميل تلقائياً.",
            reply_markup=get_main_menu()
        )

    elif query.data == "enter_code":
        await query.edit_message_text(text="🎟️ أرسل الكود:")
        context.user_data["mode"] = "redeem"

    elif query.data == "help":
        await query.edit_message_text(
            text="❓ *المساعدة*\n\n"
                 "🔍 *البحث السريع*: يستخدم Index لبحث فوري\n"
                 "🔄 *التحويل*: حول URLs إلى combos\n"
                 "📁 *رفع ملفات*: TXT أو ZIP مباشرة\n"
                 "🌐 *Google Drive*: أرسل رابط Drive\n"
                 "💾 *Auto Load*: البوت يحفظ رابط Drive ويحمل تلقائياً\n\n"
                 "💬 للتواصل: @support",
            parse_mode="Markdown"
        )

    elif query.data == "myinfo":
        user = update.effective_user
        await query.edit_message_text(
            text=f"🆔 *معلوماتك*\n\n"
                 f"👤 الاسم: {user.first_name}\n"
                 f"📱 ID: `{user.id}`",
            parse_mode="Markdown"
        )

    elif query.data == "back":
        await query.edit_message_text(
            text="🏠 *القائمة الرئيسية*",
            reply_markup=get_main_menu(),
            parse_mode="Markdown"
        )


# ============================================================
# DOCUMENT HANDLER
# ============================================================
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global INDEX_BUILT
    load_all_data()
    user_id = str(update.effective_user.id)
    document = update.message.document
    file_name = document.file_name.lower()
    mode = context.user_data.get("mode", "normal")

    if document.file_size > 20 * 1024 * 1024:
        await update.message.reply_text(
            "❌ الملف كبير بزاف!\n\n"
            "📏 الحد الأقصى: 20MB\n"
            "💡 الحل: ارفعه على Google Drive وأرسل الرابط"
        )
        return

    # ---- وضع converter ----
    if mode == "converter" and file_name.endswith('.txt'):
        file = await context.bot.get_file(document.file_id)
        await file.download_to_drive("temp_file.txt")

        combos = []
        with open("temp_file.txt", "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        total = len(lines)
        processed = 0
        start_time = time.time()

        status_msg = await update.message.reply_text("⏳ جاري المعالجة...\n\n📊 Progress: 0%")

        for i, line in enumerate(lines):
            line = line.strip()
            if line:
                combo = await convert_url_to_combo(line)
                if combo:
                    combos.append(combo)

            processed += 1
            percentage = (processed / total) * 100

            if processed % max(1, total // 10) == 0:
                elapsed = time.time() - start_time
                speed = processed / elapsed if elapsed > 0 else 0
                remaining = (total - processed) / speed if speed > 0 else 0
                eta_str = f"{int(remaining)}s" if remaining < 60 else f"{int(remaining/60)}m"

                bar_length = 20
                filled = int(bar_length * percentage / 100)
                bar = "█" * filled + "░" * (bar_length - filled)

                await status_msg.edit_text(
                    f"⏳ جاري المعالجة...\n\n"
                    f"[{bar}] {percentage:.1f}%\n"
                    f"✅ تم: {processed:,}/{total:,}\n"
                    f"🎯 Combos: {len(combos):,}\n"
                    f"⚡ السرعة: {speed:.0f} line/s\n"
                    f"⏱️ ETA: {eta_str}"
                )

        if not combos:
            await status_msg.edit_text("❌ لم يتم العثور على أي combos")
            os.remove("temp_file.txt")
            return

        output_file = "combos_converted.txt"
        with open(output_file, "w", encoding="utf-8") as f:
            for combo in combos:
                f.write(combo + "\n")

        USERS_DB[user_id]["conversions"] += 1
        save_all_data()

        total_time = time.time() - start_time
        success_percentage = (len(combos) / total) * 100

        await status_msg.edit_text(
            f"🏆 *اكتمل التحويل!*\n\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📊 URLs المُعالجة: {total:,}\n"
            f"✅ Combos ناجحة: {len(combos):,}\n"
            f"⚡ نسبة النجاح: {success_percentage:.1f}%\n"
            f"⏱️ الوقت: {total_time:.1f}s\n"
            f"━━━━━━━━━━━━━━━━━━━",
            parse_mode="Markdown"
        )

        await update.message.reply_document(
            document=open(output_file, "rb"),
            filename="combos_converted.txt",
            caption=f"📥 Combos ({len(combos):,})"
        )
        os.remove("temp_file.txt")
        return

    # ---- رفع TXT للبحث ----
    if file_name.endswith('.txt'):
        msg = await update.message.reply_text("📥 جاري رفع الملف...")
        file = await context.bot.get_file(document.file_id)

        os.makedirs(DATA_DIR, exist_ok=True)
        dest = os.path.join(DATA_DIR, document.file_name)
        await file.download_to_drive(dest)

        await msg.edit_text("🔄 جاري بناء الـ Index السريع...")
        build_search_index()

        context.user_data["files_loaded"] = True
        await msg.edit_text(
            f"✅ تم رفع الملف!\n\n"
            f"⚡ Fast Index جاهز\n"
            f"📊 الأسطر: {INDEX_TOTAL_LINES:,}\n"
            f"🔍 ابحث الآن بأي كلمة!",
            reply_markup=get_main_menu()
        )
        return

    # ---- رفع ZIP ----
    if file_name.endswith('.zip'):
        msg = await update.message.reply_text("📥 جاري رفع الـ ZIP...")
        file = await context.bot.get_file(document.file_id)
        await file.download_to_drive(ZIP_FILE)

        await msg.edit_text("🔄 جاري الاستخراج...")

        if os.path.exists(DATA_DIR):
            shutil.rmtree(DATA_DIR)
        os.makedirs(DATA_DIR, exist_ok=True)

        with zipfile.ZipFile(ZIP_FILE, 'r') as zip_ref:
            zip_ref.extractall(DATA_DIR)

        txt_files = list(Path(DATA_DIR).rglob("*.txt"))

        await msg.edit_text(f"🔄 بناء الـ Index لـ {len(txt_files)} ملف...")
        build_search_index()

        context.user_data["files_loaded"] = True
        await msg.edit_text(
            f"✅ تم استخراج الـ ZIP!\n\n"
            f"📄 الملفات: {len(txt_files)}\n"
            f"⚡ Fast Index جاهز\n"
            f"📊 الأسطر: {INDEX_TOTAL_LINES:,}",
            reply_markup=get_main_menu()
        )
        return

    await update.message.reply_text("❌ الرجاء إرسال ملف TXT أو ZIP فقط")


# ============================================================
# TEXT HANDLER
# ============================================================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global INDEX_BUILT
    load_all_data()
    user_id = update.effective_user.id
    text = update.message.text.strip()
    mode = context.user_data.get("mode", "normal")

    # ---- redeem code ----
    if mode == "redeem":
        valid, msg = is_code_valid(user_id, text)
        if not valid:
            await update.message.reply_text(f"❌ {msg}")
            return

        context.user_data["access_code"] = text
        ACCESS_CODES[text]["used_count"] += 1
        save_all_data()

        await update.message.reply_text(
            f"✅ تم تفعيل الكود!\n\n"
            f"🎟️ الكود: {text}",
            reply_markup=get_main_menu()
        )
        context.user_data["mode"] = "normal"
        return

    # ---- Google Drive link ----
    if "drive.google.com" in text:
        file_id = extract_drive_id(text)
        if not file_id:
            await update.message.reply_text("❌ رابط غير صحيح")
            return

        msg = await update.message.reply_text("⬇️ جاري تحميل من Google Drive...")

        try:
            url = f"https://drive.google.com/uc?id={file_id}"
            gdown.download(url, ZIP_FILE, quiet=False, fuzzy=True)

            await msg.edit_text("🔄 جاري استخراج الملفات...")

            if os.path.exists(DATA_DIR):
                shutil.rmtree(DATA_DIR)
            os.makedirs(DATA_DIR, exist_ok=True)

            with zipfile.ZipFile(ZIP_FILE, 'r') as zip_ref:
                zip_ref.extractall(DATA_DIR)

            txt_files = list(Path(DATA_DIR).rglob("*.txt"))

            await msg.edit_text(f"🔄 بناء الـ Fast Index لـ {len(txt_files)} ملف...")
            build_search_index()

            context.user_data["files_loaded"] = True

            # ✅ حفظ الرابط تلقائياً
            save_drive_link(text)

            await msg.edit_text(
                f"✅ تم التحميل من Google Drive!\n\n"
                f"📄 الملفات: {len(txt_files)}\n"
                f"⚡ Fast Index جاهز\n"
                f"📊 الأسطر: {INDEX_TOTAL_LINES:,}\n"
                f"💾 تم حفظ الرابط - سيتم التحميل تلقائياً ✅\n\n"
                f"🔍 ابحث الآن!",
                reply_markup=get_main_menu()
            )
        except Exception as e:
            await msg.edit_text(f"❌ خطأ: {str(e)[:80]}")
        return

    # ---- FAST SEARCH ----
    if mode == "search":
        if not INDEX_BUILT and not context.user_data.get("files_loaded"):
            await update.message.reply_text(
                "⚠️ لا يوجد ملفات محملة!\n\n"
                "📤 أرسل ملف TXT أو ZIP\n"
                "🌐 أو أرسل رابط Google Drive"
            )
            return

        keyword = text
        search_msg = await update.message.reply_text(
            f"⚡ *Fast Search Mode*\n\n"
            f"🔍 البحث عن: `{keyword}`\n"
            f"📊 الأسطر: {INDEX_TOTAL_LINES:,}\n"
            f"⏳ جاري...",
            parse_mode="Markdown"
        )

        start_time = time.time()

        if INDEX_BUILT:
            results = fast_search(keyword)
        else:
            results = []
            txt_files = list(Path(DATA_DIR).rglob("*.txt"))
            total_files = len(txt_files)

            for i, txt_file in enumerate(txt_files):
                try:
                    with open(txt_file, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            if keyword.lower() in line.lower():
                                results.append(line.strip())
                except:
                    pass

                percentage = ((i + 1) / total_files) * 100
                bar_length = 20
                filled = int(bar_length * percentage / 100)
                bar = "█" * filled + "░" * (bar_length - filled)

                if i % max(1, total_files // 5) == 0:
                    await search_msg.edit_text(
                        f"🔍 *جاري البحث...*\n\n"
                        f"[{bar}] {percentage:.0f}%\n"
                        f"📂 الملفات: {i+1}/{total_files}\n"
                        f"✅ النتائج: {len(results):,}",
                        parse_mode="Markdown"
                    )

        elapsed = time.time() - start_time

        if not results:
            await search_msg.edit_text(f"😕 لم نجد نتائج لـ `{keyword}`", parse_mode="Markdown")
            return

        USERS_DB[str(user_id)]["searches"] += 1
        save_all_data()

        unique_results = list(dict.fromkeys(results))

        result_file = "resultat.txt"
        with open(result_file, "w", encoding="utf-8") as f:
            for i, line in enumerate(unique_results[:5000], 1):
                f.write(f"{i}. {line}\n")

        await search_msg.edit_text(
            f"🏆 *Search Finished!*\n\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🔍 الكلمة: `{keyword}`\n"
            f"✅ النتائج: {len(unique_results):,}\n"
            f"🗑️ مكرر محذوف: {len(results) - len(unique_results):,}\n"
            f"⚡ الوقت: {elapsed:.2f}s\n"
            f"━━━━━━━━━━━━━━━━━━━",
            parse_mode="Markdown"
        )

        await update.message.reply_document(
            document=open(result_file, "rb"),
            filename=f"results_{keyword}.txt",
            caption=f"🔍 نتائج: {len(unique_results):,} | ⚡ {elapsed:.2f}s"
        )
        return

    await update.message.reply_text(
        "🏠 اختر من القائمة:",
        reply_markup=get_main_menu()
    )


# ============================================================
# ADMIN COMMANDS
# ============================================================
async def addcode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    load_all_data()
    user_id = update.effective_user.id

    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin only")
        return

    if len(context.args) < 3:
        await update.message.reply_text("/addcode <code> <uses> <expiry YYYY-MM-DD>")
        return

    code = context.args[0]
    max_uses = int(context.args[1])
    expiry_date = context.args[2]

    ACCESS_CODES[code] = {
        "max_uses": max_uses,
        "used_count": 0,
        "expires_at": f"{expiry_date}T23:59:59"
    }
    save_all_data()
    await update.message.reply_text(f"✅ تم إضافة الكود: `{code}`", parse_mode="Markdown")


async def indexinfo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if INDEX_BUILT:
        await update.message.reply_text(
            f"⚡ *Fast Index Info*\n\n"
            f"📊 الأسطر: {INDEX_TOTAL_LINES:,}\n"
            f"🗝️ الكلمات: {len(SEARCH_INDEX):,}\n"
            f"✅ الحالة: جاهز",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("📭 الـ Index فارغ - أرسل ملفات أولاً")


async def setdrive_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر للأدمين لتغيير رابط Drive المحفوظ"""
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin only")
        return

    if not context.args:
        await update.message.reply_text("/setdrive <google_drive_link>")
        return

    link = context.args[0]
    if "drive.google.com" not in link:
        await update.message.reply_text("❌ الرابط غير صحيح")
        return

    save_drive_link(link)
    await update.message.reply_text(
        f"✅ تم حفظ الرابط!\n\n"
        f"🔄 سيتم التحميل تلقائياً عند إعادة تشغيل البوت",
        parse_mode="Markdown"
    )


# ============================================================
# MAIN
# ============================================================
def main():
    load_all_data()
    auto_load_on_startup()  # ✅ تحميل تلقائي عند البدء

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addcode", addcode_cmd))
    app.add_handler(CommandHandler("indexinfo", indexinfo_cmd))
    app.add_handler(CommandHandler("setdrive", setdrive_cmd))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("🚀 بوت البحث والتحويل v6.0 شغال! ✅")
    app.run_polling()


if __name__ == "__main__":
    main()
