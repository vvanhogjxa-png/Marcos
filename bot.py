import os
import re
import logging
import gdown
import zipfile
import shutil
import json
import time
import threading
from datetime import datetime
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
# INDEX
# ============================================================
SEARCH_INDEX = defaultdict(list)
INDEX_BUILT = False
INDEX_BUILDING = False
INDEX_TOTAL_LINES = 0
INDEX_LOCK = threading.Lock()


def build_search_index():
    global SEARCH_INDEX, INDEX_BUILT, INDEX_BUILDING, INDEX_TOTAL_LINES

    with INDEX_LOCK:
        if INDEX_BUILDING:
            logging.warning("⚠️ Index build already in progress – skipping.")
            return
        INDEX_BUILDING = True
        INDEX_BUILT = False
        SEARCH_INDEX = defaultdict(list)
        INDEX_TOTAL_LINES = 0

    txt_files = list(Path(DATA_DIR).rglob("*.txt"))

    if not txt_files:
        with INDEX_LOCK:
            INDEX_BUILT = True
            INDEX_BUILDING = False
        logging.info("📭 لا يوجد ملفات TXT للفهرسة.")
        return

    start_time = time.time()
    logging.info(f"🔄 بناء Index بطريقة عادية لـ {len(txt_files)} ملف...")

    try:
        for i, txt_file in enumerate(txt_files):
            try:
                with open(txt_file, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            INDEX_TOTAL_LINES += 1
                            parts = set(re.split(r'[\s:@|]+', line.lower()))
                            for part in parts:
                                if len(part) >= 2:
                                    SEARCH_INDEX[part].append(line)
            except Exception as e:
                logging.error(f"❌ خطأ في الملف {txt_file}: {e}")
                continue

            logging.info(f"✅ {i+1}/{len(txt_files)} - {txt_file.name}")

    finally:
        elapsed = time.time() - start_time
        with INDEX_LOCK:
            INDEX_BUILT = True
            INDEX_BUILDING = False
        logging.info(
            f"✅ Index built: {INDEX_TOTAL_LINES:,} lines, "
            f"{len(SEARCH_INDEX):,} keys in {elapsed:.1f}s"
        )


def fast_search(keyword):
    keyword_lower = keyword.lower()
    results = set()
    with INDEX_LOCK:
        if keyword_lower in SEARCH_INDEX:
            for line in SEARCH_INDEX[keyword_lower]:
                results.add(line)
        for key in SEARCH_INDEX:
            if keyword_lower in key or key in keyword_lower:
                for line in SEARCH_INDEX[key]:
                    results.add(line)
    return list(results)


# ============================================================
# DRIVE LINKS MANAGEMENT
# ============================================================
def save_drive_link(link):
    links = []
    if os.path.exists(DRIVE_LINKS_FILE):
        try:
            with open(DRIVE_LINKS_FILE) as f:
                links = json.load(f)
        except Exception:
            links = []
    if link and link not in links:
        links.append(link)
    with open(DRIVE_LINKS_FILE, "w") as f:
        json.dump(links, f)


def get_saved_drive_links():
    if not os.path.exists(DRIVE_LINKS_FILE):
        return []
    try:
        with open(DRIVE_LINKS_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def delete_drive_link(link):
    links = get_saved_drive_links()
    if link in links:
        links.remove(link)
    with open(DRIVE_LINKS_FILE, "w") as f:
        json.dump(links, f)


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


# ============================================================
# AUTO LOAD ON STARTUP
# ============================================================
def auto_load_on_startup():
    if not os.path.exists(DRIVE_LINKS_FILE):
        if os.path.exists(DATA_DIR) and list(Path(DATA_DIR).rglob("*.txt")):
            logging.info("🔄 بناء Index من الملفات الموجودة...")
            build_search_index()
        return

    try:
        with open(DRIVE_LINKS_FILE) as f:
            links = json.load(f)
    except Exception:
        return

    if not links:
        if os.path.exists(DATA_DIR) and list(Path(DATA_DIR).rglob("*.txt")):
            logging.info("🔄 بناء Index من الملفات الموجودة...")
            build_search_index()
        return

    last_link = links[-1]
    logging.info(f"🔄 تحميل تلقائي من: {last_link}")

    try:
        file_id = extract_drive_id(last_link)
        if not file_id:
            logging.error("❌ رابط غير صحيح في saved_drives.json")
            return

        url = f"https://drive.google.com/uc?id={file_id}"
        gdown.download(url, ZIP_FILE, quiet=True, fuzzy=True)

        if not os.path.exists(ZIP_FILE) or os.path.getsize(ZIP_FILE) == 0:
            logging.error("❌ فشل التحميل التلقائي – الملف فارغ أو غير موجود")
            return

        if os.path.exists(DATA_DIR):
            shutil.rmtree(DATA_DIR)
        os.makedirs(DATA_DIR, exist_ok=True)

        with zipfile.ZipFile(ZIP_FILE, 'r') as z:
            z.extractall(DATA_DIR)

        logging.info("⚡ بناء الـ Index...")
        build_search_index()
        logging.info(f"✅ Auto-loaded: {INDEX_TOTAL_LINES:,} lines ready")

    except Exception as e:
        logging.error(f"❌ خطأ في التحميل التلقائي: {e}")


# ============================================================
# DATA MANAGEMENT
# ============================================================
def load_all_data():
    global ACCESS_CODES, USERS_DB, STATS
    if os.path.exists(CODES_FILE):
        try:
            with open(CODES_FILE, "r") as f:
                ACCESS_CODES = json.load(f)
        except Exception:
            ACCESS_CODES = {}
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r") as f:
                USERS_DB = json.load(f)
        except Exception:
            USERS_DB = {}
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, "r") as f:
                STATS = json.load(f)
        except Exception:
            STATS = {}


def save_all_data():
    with open(CODES_FILE, "w") as f:
        json.dump(ACCESS_CODES, f)
    with open(USERS_FILE, "w") as f:
        json.dump(USERS_DB, f)
    with open(STATS_FILE, "w") as f:
        json.dump(STATS, f)


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
    except Exception:
        return None


# ============================================================
# MENUS
# ============================================================
def get_main_menu(is_admin=False):
    keyboard = [
        [InlineKeyboardButton("🔍 البحث السريع", callback_data="search")],
        [InlineKeyboardButton("🔄 Combo Converter", callback_data="converter")],
        [InlineKeyboardButton("📊 الإحصائيات", callback_data="stats")],
        [InlineKeyboardButton("⚙️ الإعدادات", callback_data="settings")],
        [InlineKeyboardButton("❓ المساعدة", callback_data="help")],
    ]
    if is_admin:
        keyboard.insert(2, [InlineKeyboardButton("☁️ Google Drive", callback_data="drive_menu")])
    return InlineKeyboardMarkup(keyboard)


def get_drive_menu(links):
    keyboard = []
    if links:
        keyboard.append([InlineKeyboardButton(f"📋 الروابط المحفوظة ({len(links)})", callback_data="drive_list")])
        keyboard.append([InlineKeyboardButton("🔄 إعادة تحميل آخر رابط", callback_data="drive_reload")])
    keyboard.append([InlineKeyboardButton("➕ رفع رابط جديد", callback_data="drive_new")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back")])
    return InlineKeyboardMarkup(keyboard)


def get_drive_links_menu(links):
    keyboard = []
    for i, link in enumerate(links):
        short = link[:35] + "..." if len(link) > 35 else link
        keyboard.append([
            InlineKeyboardButton(f"📥 {short}", callback_data=f"drive_load_{i}"),
            InlineKeyboardButton("🗑️", callback_data=f"drive_delete_{i}")
        ])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="drive_menu")])
    return InlineKeyboardMarkup(keyboard)


# ============================================================
# CORE DRIVE DOWNLOAD LOGIC
# ============================================================
async def download_and_index_drive(link, msg, context):
    file_id = extract_drive_id(link)
    if not file_id:
        await msg.edit_text(
            "❌ *رابط غير صحيح!*\n\n"
            "تأكد أن الرابط من Google Drive وفيه `/file/d/` أو `?id=`",
            parse_mode="Markdown"
        )
        return False

    await msg.edit_text(
        "☁️ *جاري التحميل من Google Drive...*\n\n"
        "⏳ قد يستغرق بعض الوقت حسب حجم الملف",
        parse_mode="Markdown"
    )

    try:
        url = f"https://drive.google.com/uc?id={file_id}"
        start_dl = time.time()
        gdown.download(url, ZIP_FILE, quiet=True, fuzzy=True)
        dl_time = time.time() - start_dl

        if not os.path.exists(ZIP_FILE) or os.path.getsize(ZIP_FILE) == 0:
            await msg.edit_text(
                "❌ *فشل التحميل!*\n\n"
                "تأكد أن:\n"
                "• الرابط صحيح ✅\n"
                "• الملف مشارك للعموم 🌐\n"
                "• الملف ZIP 📦",
                parse_mode="Markdown"
            )
            return False

        file_size_mb = os.path.getsize(ZIP_FILE) / (1024 * 1024)

    except Exception as e:
        await msg.edit_text(
            f"❌ *خطأ في التحميل:*\n\n`{str(e)[:200]}`",
            parse_mode="Markdown"
        )
        return False

    await msg.edit_text(
        f"📦 *تم التحميل!* ({file_size_mb:.1f} MB في {dl_time:.1f}s)\n\n"
        "🔄 جاري فك الضغط...",
        parse_mode="Markdown"
    )

    try:
        if os.path.exists(DATA_DIR):
            shutil.rmtree(DATA_DIR)
        os.makedirs(DATA_DIR, exist_ok=True)

        with zipfile.ZipFile(ZIP_FILE, 'r') as z:
            z.extractall(DATA_DIR)

        txt_files = list(Path(DATA_DIR).rglob("*.txt"))
        if not txt_files:
            await msg.edit_text(
                "⚠️ *لا يوجد ملفات TXT داخل الـ ZIP!*\n\n"
                "تأكد أن الملف يحتوي على ملفات `.txt`",
                parse_mode="Markdown"
            )
            return False

    except zipfile.BadZipFile:
        await msg.edit_text(
            "❌ *الملف ليس ZIP صحيح!*\n\n"
            "تأكد أن الملف بصيغة `.zip`",
            parse_mode="Markdown"
        )
        return False
    except Exception as e:
        await msg.edit_text(
            f"❌ *خطأ في فك الضغط:*\n\n`{str(e)[:200]}`",
            parse_mode="Markdown"
        )
        return False

    await msg.edit_text(
        f"⚡ *جاري بناء الـ Index...*\n\n"
        f"📄 {len(txt_files)} ملف TXT",
        parse_mode="Markdown"
    )

    build_search_index()
    save_drive_link(link)

    await msg.edit_text(
        f"✅ *تم بنجاح!*\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📦 الحجم: `{file_size_mb:.1f} MB`\n"
        f"📄 الملفات: `{len(txt_files)}`\n"
        f"⚡ الأسطر: `{INDEX_TOTAL_LINES:,}`\n"
        f"🗝️ Keywords: `{len(SEARCH_INDEX):,}`\n"
        f"⏱️ وقت التحميل: `{dl_time:.1f}s`\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"🔍 البوت جاهز للبحث!",
        parse_mode="Markdown",
        reply_markup=get_main_menu(is_admin=True)
    )
    return True


# ============================================================
# HANDLERS
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    load_all_data()
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name
    is_admin = user_id in ADMIN_IDS

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
        f"║   🚀 بوت البحث السريع v7.1 ⚡   ║\n"
        f"║                                   ║\n"
        f"║        مرحباً {first_name} 👋         ║\n"
        f"╚═══════════════════════════════════╝\n\n"
        f"{index_status}\n\n"
        f"🎯 اختر من الخيارات أدناه!"
    )

    await update.message.reply_text(welcome_text, reply_markup=get_main_menu(is_admin=is_admin))


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    is_admin = user_id in ADMIN_IDS
    data = query.data

    # ─────────── DRIVE MENU ───────────
    if data == "drive_menu":
        if not is_admin:
            await query.answer("❌ ما عندكش صلاحية!", show_alert=True)
            return
        links = get_saved_drive_links()
        await query.edit_message_text(
            text=(
                "☁️ *Google Drive*\n\n"
                f"🔗 الروابط المحفوظة: `{len(links)}`\n"
                f"⚡ الأسطر الحالية: `{INDEX_TOTAL_LINES:,}`\n\n"
                "اختر العملية:"
            ),
            parse_mode="Markdown",
            reply_markup=get_drive_menu(links)
        )

    elif data == "drive_new":
        if not is_admin:
            await query.answer("❌ ما عندكش صلاحية!", show_alert=True)
            return
        context.user_data["mode"] = "drive_link"
        await query.edit_message_text(
            text=(
                "☁️ *رفع من Google Drive*\n\n"
                "📤 أرسل رابط Google Drive للملف ZIP\n\n"
                "📌 *مثال:*\n"
                "`https://drive.google.com/file/d/XXXXX/view`\n\n"
                "⚠️ تأكد أن الملف:\n"
                "• مشارك للعموم 🌐\n"
                "• بصيغة ZIP 📦\n"
                "• يحتوي ملفات TXT 📄"
            ),
            parse_mode="Markdown"
        )

    elif data == "drive_list":
        if not is_admin:
            await query.answer("❌ ما عندكش صلاحية!", show_alert=True)
            return
        links = get_saved_drive_links()
        if not links:
            await query.answer("لا يوجد روابط محفوظة!", show_alert=True)
            return
        await query.edit_message_text(
            text="📋 *الروابط المحفوظة:*\n\nاختر رابط للتحميل أو 🗑️ للحذف:",
            parse_mode="Markdown",
            reply_markup=get_drive_links_menu(links)
        )

    elif data == "drive_reload":
        if not is_admin:
            await query.answer("❌ ما عندكش صلاحية!", show_alert=True)
            return
        links = get_saved_drive_links()
        if not links:
            await query.answer("لا يوجد روابط محفوظة!", show_alert=True)
            return
        last_link = links[-1]
        msg = await query.edit_message_text(
            f"🔄 *إعادة تحميل:*\n`{last_link[:50]}...`",
            parse_mode="Markdown"
        )
        await download_and_index_drive(last_link, msg, context)

    elif data.startswith("drive_load_"):
        if not is_admin:
            await query.answer("❌ ما عندكش صلاحية!", show_alert=True)
            return
        idx = int(data.replace("drive_load_", ""))
        links = get_saved_drive_links()
        if idx >= len(links):
            await query.answer("رابط غير موجود!", show_alert=True)
            return
        link = links[idx]
        msg = await query.edit_message_text(
            f"☁️ *جاري تحميل:*\n`{link[:60]}...`",
            parse_mode="Markdown"
        )
        await download_and_index_drive(link, msg, context)

    elif data.startswith("drive_delete_"):
        if not is_admin:
            await query.answer("❌ ما عندكش صلاحية!", show_alert=True)
            return
        idx = int(data.replace("drive_delete_", ""))
        links = get_saved_drive_links()
        if idx >= len(links):
            await query.answer("رابط غير موجود!", show_alert=True)
            return
        deleted = links[idx]
        delete_drive_link(deleted)
        await query.answer("🗑️ تم الحذف!", show_alert=True)
        links = get_saved_drive_links()
        if links:
            await query.edit_message_text(
                text="📋 *الروابط المحفوظة:*",
                parse_mode="Markdown",
                reply_markup=get_drive_links_menu(links)
            )
        else:
            await query.edit_message_text(
                text="☁️ *Google Drive*\n\nلا يوجد روابط محفوظة.",
                parse_mode="Markdown",
                reply_markup=get_drive_menu([])
            )

    # ─────────── SEARCH ───────────
    elif data == "search":
        await query.edit_message_text(
            text=(
                f"🔍 *وضع البحث السريع*\n\n"
                f"⚡ {INDEX_TOTAL_LINES:,} سطر جاهز\n\n"
                f"📝 أرسل كلمة للبحث"
            ),
            parse_mode="Markdown"
        )
        context.user_data["mode"] = "search"

    # ─────────── CONVERTER ───────────
    elif data == "converter":
        await query.edit_message_text(
            text="🔄 *محول URL إلى Combo*\n\n📤 أرسل ملف TXT يحتوي على URLs",
            parse_mode="Markdown"
        )
        context.user_data["mode"] = "converter"

    # ─────────── STATS ───────────
    elif data == "stats":
        links = get_saved_drive_links()
        await query.edit_message_text(
            text=(
                f"📊 *الإحصائيات*\n\n"
                f"⚡ Indexed Lines: `{INDEX_TOTAL_LINES:,}`\n"
                f"🗝️ Keywords: `{len(SEARCH_INDEX):,}`\n"
                f"🔗 Drive Links: `{len(links)}`\n"
                f"👥 Users: `{len(USERS_DB)}`"
            ),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back")]])
        )

    # ─────────── SETTINGS ───────────
    elif data == "settings":
        keyboard = [
            [InlineKeyboardButton("🔄 إعادة بناء Index", callback_data="rebuild")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back")]
        ]
        await query.edit_message_text(
            text="⚙️ *الإعدادات*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data == "rebuild":
        if INDEX_BUILDING:
            await query.answer("⚠️ الـ Index قيد البناء بالفعل!", show_alert=True)
            return
        await query.edit_message_text("🔄 جاري إعادة بناء الـ Index...")
        build_search_index()
        await query.edit_message_text(
            f"✅ تم!\n\n⚡ `{INDEX_TOTAL_LINES:,}` سطر",
            parse_mode="Markdown",
            reply_markup=get_main_menu(is_admin=is_admin)
        )

    # ─────────── HELP ───────────
    elif data == "help":
        help_text = (
            "❓ *المساعدة*\n\n"
            "🔍 *البحث:* أرسل كلمة بعد الضغط على البحث\n"
            "🔄 *التحويل:* أرسل ملف TXT فيه URLs\n"
            "📤 *ZIP مباشر:* أرسل ملف ZIP في أي وقت\n"
        )
        if is_admin:
            help_text += "☁️ *Drive:* أدمن فقط - رفع من Google Drive\n"
        await query.edit_message_text(
            text=help_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back")]])
        )

    # ─────────── BACK ───────────
    elif data == "back":
        await query.edit_message_text(
            text="🏠 *القائمة الرئيسية*",
            parse_mode="Markdown",
            reply_markup=get_main_menu(is_admin=is_admin)
        )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    file_name = document.file_name.lower()
    mode = context.user_data.get("mode", "normal")
    is_admin = update.effective_user.id in ADMIN_IDS

    # ── Combo Converter ──
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
            if total > 0 and (i + 1) % max(1, total // 10) == 0:
                elapsed = time.time() - start_time
                await status_msg.edit_text(
                    f"⏳ جاري المعالجة...\n"
                    f"📊 {((i+1)/total*100):.0f}%\n"
                    f"✅ Combos: {len(combos):,}\n"
                    f"⚡ {elapsed:.1f}s"
                )

        output_file = "combos_converted.txt"
        with open(output_file, "w", encoding="utf-8") as f:
            for combo in combos:
                f.write(combo + "\n")

        await status_msg.edit_text(
            f"✅ تم!\n\n📊 Combos: {len(combos):,}\n⚡ {time.time()-start_time:.1f}s"
        )
        await update.message.reply_document(
            document=open(output_file, "rb"),
            filename="combos_converted.txt",
            caption=f"📥 ({len(combos):,})"
        )
        if os.path.exists("temp_file.txt"):
            os.remove("temp_file.txt")
        return

    # ── ZIP Upload ──
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
        await msg.edit_text(f"⚡ بناء Index لـ {len(txt_files)} ملف...")
        build_search_index()

        await msg.edit_text(
            f"✅ تم!\n\n"
            f"📄 Files: `{len(txt_files)}`\n"
            f"⚡ Lines: `{INDEX_TOTAL_LINES:,}`",
            parse_mode="Markdown",
            reply_markup=get_main_menu(is_admin=is_admin)
        )
        return


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    load_all_data()
    text = update.message.text.strip()
    mode = context.user_data.get("mode", "normal")
    is_admin = update.effective_user.id in ADMIN_IDS

    # ── Google Drive Link Mode ──
    if mode == "drive_link":
        if not is_admin:
            await update.message.reply_text("❌ ما عندكش صلاحية!")
            return

        if "drive.google.com" not in text and "id=" not in text:
            await update.message.reply_text(
                "❌ *هذا مو رابط Google Drive!*\n\n"
                "أرسل رابط من النوع:\n"
                "`https://drive.google.com/file/d/XXXXX/view`",
                parse_mode="Markdown"
            )
            return

        context.user_data["mode"] = "normal"
        msg = await update.message.reply_text(
            "☁️ *جاري التحضير...*",
            parse_mode="Markdown"
        )
        await download_and_index_drive(text, msg, context)
        return

    # ── Search Mode ──
    if mode == "search":
        if not INDEX_BUILT:
            await update.message.reply_text("❌ لا يوجد ملفات!")
            return

        start_time = time.time()
        search_msg = await update.message.reply_text(
            f"⚡ *جاري البحث*\n\n🔍 عن: `{text}`",
            parse_mode="Markdown"
        )

        results = fast_search(text)
        elapsed = time.time() - start_time

        if not results:
            await search_msg.edit_text(f"😕 لم نجد نتائج لـ `{text}`", parse_mode="Markdown")
            return

        result_file = "resultat.txt"
        with open(result_file, "w", encoding="utf-8") as f:
            for i, line in enumerate(results[:5000], 1):
                f.write(f"{i}. {line}\n")

        await search_msg.edit_text(
            f"✅ تم!\n\n📊 `{len(results):,}` نتيجة\n⚡ `{elapsed:.2f}s`",
            parse_mode="Markdown",
            reply_markup=get_main_menu(is_admin=is_admin)
        )
        await update.message.reply_document(
            document=open(result_file, "rb"),
            filename="results.txt",
            caption=f"🔍 {len(results):,} | ⚡ {elapsed:.2f}s"
        )


# ============================================================
# MAIN
# ============================================================
def main():
    load_all_data()
    auto_load_on_startup()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("🚀 بوت البحث السريع v7.1 شغال! ✅")
    app.run_polling()


if __name__ == "__main__":
    main()
