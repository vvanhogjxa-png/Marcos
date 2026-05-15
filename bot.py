import os
import re
import logging
import gdown
import zipfile
import shutil
import json
from datetime import datetime, timedelta
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
DATA_DIR = "extracted_files"
ZIP_FILE = "data.zip"
CODES_FILE = "access_codes.json"
USERS_FILE = "users_db.json"
STATS_FILE = "stats.json"

ACCESS_CODES = {}
USERS_DB = {}
STATS = {}

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
    """تحويل URL إلى combo"""
    try:
        # البحث عن النمط: :username:password أو :email:password
        match = re.search(r':([^/:]+:[^/]+)$', url)
        if match:
            return match.group(1).strip()
        
        # إذا كان الرابط يحتوي على : في النهاية
        if ':' in url:
            parts = url.split(':')
            if len(parts) >= 2:
                return ':'.join(parts[-2:])
        
        return None
    except:
        return None

def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("🔍 البحث", callback_data="search"), InlineKeyboardButton("📁 الملفات", callback_data="files")],
        [InlineKeyboardButton("🔄 Combo Converter", callback_data="converter"), InlineKeyboardButton("📊 الإحصائيات", callback_data="stats")],
        [InlineKeyboardButton("💳 الاشتراك", callback_data="subscription"), InlineKeyboardButton("⚙️ الإعدادات", callback_data="settings")],
        [InlineKeyboardButton("❓ المساعدة", callback_data="help"), InlineKeyboardButton("🆔 معلوماتي", callback_data="myinfo")],
    ]
    return InlineKeyboardMarkup(keyboard)

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
    
    welcome_text = (
        f"╔═══════════════════════════════════╗\n"
        f"║   🤖 بوت البحث والتحويل v5.0 ⚡  ║\n"
        f"║                                   ║\n"
        f"║        مرحباً {first_name} 👋         ║\n"
        f"╚═══════════════════════════════════╝\n\n"
        f"🎯 اختر من الخيارات أدناه للبدء!"
    )
    
    await update.message.reply_text(welcome_text, reply_markup=get_main_menu())

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "search":
        await query.edit_message_text(
            text="🔍 *وضع البحث*\n\n"
            "📝 أرسل الكلمة التي تريد البحث عنها",
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
        await query.edit_message_text(
            text=f"📊 *إحصائياتك*\n\n"
            f"🔍 عدد البحثيات: {user_data.get('searches', 0)}\n"
            f"🔄 عدد التحويلات: {user_data.get('conversions', 0)}\n"
            f"⭐ النقاط: {(user_data.get('searches', 0) + user_data.get('conversions', 0)) * 10}"
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
            [InlineKeyboardButton("🔙 رجوع", callback_data="back")]
        ]
        await query.edit_message_text(
            text="⚙️ *الإعدادات*",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif query.data == "enter_code":
        await query.edit_message_text(text="🎟️ أرسل الكود:")
        context.user_data["mode"] = "redeem"
    
    elif query.data == "help":
        await query.edit_message_text(
            text="❓ *المساعدة*\n\n"
            "🔍 البحث: ابحث في الملفات\n"
            "🔄 التحويل: حول URLs إلى combos\n\n"
            "💬 للتواصل: @support"
        )
    
    elif query.data == "myinfo":
        user = update.effective_user
        await query.edit_message_text(
            text=f"🆔 *معلوماتك*\n\n"
            f"👤 الاسم: {user.first_name}\n"
            f"📱 ID: `{user.id}`"
        )
    
    elif query.data == "back":
        await query.edit_message_text(
            text="🏠 *القائمة الرئيسية*",
            reply_markup=get_main_menu()
        )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة ملفات TXT"""
    load_all_data()
    user_id = str(update.effective_user.id)
    
    document = update.message.document
    
    if not document.file_name.endswith('.txt'):
        await update.message.reply_text("❌ الرجاء إرسال ملف TXT فقط")
        return
    
    file = await context.bot.get_file(document.file_id)
    await file.download_to_drive("temp_file.txt")
    
    combos = []
    with open("temp_file.txt", "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    
    total = len(lines)
    processed = 0
    
    status_msg = await update.message.reply_text(
        "⏳ جاري المعالجة...\n\n"
        "📊 Progress: 0%"
    )
    
    for i, line in enumerate(lines):
        line = line.strip()
        if line:
            combo = await convert_url_to_combo(line)
            if combo:
                combos.append(combo)
        
        processed += 1
        percentage = (processed / total) * 100
        
        if processed % max(1, total // 10) == 0:
            bar_length = 20
            filled = int(bar_length * percentage / 100)
            bar = "█" * filled + "░" * (bar_length - filled)
            
            await status_msg.edit_text(
                f"⏳ جاري المعالجة...\n\n"
                f"[{bar}] {percentage:.1f}%\n"
                f"✅ تم: {processed}/{total}\n"
                f"🎯 Combos: {len(combos)}"
            )
    
    if not combos:
        await status_msg.edit_text("❌ لم يتم العثور على أي combos")
        os.remove("temp_file.txt")
        return
    
    output_file = "combos_converted.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        for combo in combos:
            f.write(combo + "\n")
    
    # تحديث الإحصائيات
    USERS_DB[user_id]["conversions"] += 1
    save_all_data()
    
    success_percentage = (len(combos) / total) * 100
    
    await status_msg.edit_text(
        f"✅ تم بنجاح! 🎉\n\n"
        f"📊 URLs: {total}\n"
        f"✅ Combos: {len(combos)}\n"
        f"⚡ النسبة: {success_percentage:.1f}%"
    )
    
    await update.message.reply_document(
        document=open(output_file, "rb"),
        filename="combos_converted.txt",
        caption=f"📥 Combos ({len(combos)})"
    )
    
    os.remove("temp_file.txt")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    load_all_data()
    user_id = update.effective_user.id
    text = update.message.text.strip()
    mode = context.user_data.get("mode", "normal")
    
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
    
    if "drive.google.com" in text:
        file_id = extract_drive_id(text)
        if not file_id:
            await update.message.reply_text("❌ رابط غير صحيح")
            return
        
        msg = await update.message.reply_text("⬇️ جاري تحميل...")
        
        try:
            url = f"https://drive.google.com/uc?id={file_id}"
            gdown.download(url, ZIP_FILE, quiet=False, fuzzy=True)
            
            await msg.edit_text("🔄 جاري استخراج...")
            
            if os.path.exists(DATA_DIR):
                shutil.rmtree(DATA_DIR)
            os.makedirs(DATA_DIR, exist_ok=True)
            
            with zipfile.ZipFile(ZIP_FILE, 'r') as zip_ref:
                zip_ref.extractall(DATA_DIR)
            
            txt_files = list(Path(DATA_DIR).rglob("*.txt"))
            context.user_data["files_loaded"] = True
            
            await msg.edit_text(f"✅ تم التحميل!\n\n📄 الملفات: {len(txt_files)}")
        except Exception as e:
            await msg.edit_text(f"❌ خطأ: {str(e)[:50]}")
        return
    
    if mode == "search" and context.user_data.get("files_loaded"):
        keyword = text
        search_msg = await update.message.reply_text(f"🔍 بحث...\n⏳ جاري...")
        
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
        except:
            pass
        
        if not results:
            await search_msg.edit_text(f"😕 لم نجد نتائج")
            return
        
        USERS_DB[str(user_id)]["searches"] += 1
        save_all_data()
        
        result_file = "resultat.txt"
        with open(result_file, "w", encoding="utf-8") as f:
            for i, line in enumerate(results, 1):
                f.write(f"{i}. {line}\n")
        
        await search_msg.edit_text(f"✅ تم! النتائج: {len(results)}")
        
        await update.message.reply_document(
            document=open(result_file, "rb"),
            filename="results.txt"
        )

async def addcode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    load_all_data()
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Admin only")
        return
    
    if len(context.args) < 3:
        await update.message.reply_text("/addcode <code> <uses> <expiry>")
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
    
    await update.message.reply_text(f"✅ تم: {code}")

def main():
    load_all_data()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addcode", addcode_cmd))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("🚀 بوت البحث والتحويل شغال! ✅")
    app.run_polling()

if __name__ == "__main__":
    main()
