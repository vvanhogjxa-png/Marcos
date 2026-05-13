import os
import re
import logging
import gdown
import zipfile
import shutil
import json
from datetime import datetime, timedelta
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
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

def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("🔍 البحث", callback_data="search"), InlineKeyboardButton("📁 الملفات", callback_data="files")],
        [InlineKeyboardButton("📊 الإحصائيات", callback_data="stats"), InlineKeyboardButton("📜 السجل", callback_data="history")],
        [InlineKeyboardButton("💳 الاشتراك", callback_data="subscription"), InlineKeyboardButton("⚙️ الإعدادات", callback_data="settings")],
        [InlineKeyboardButton("❓ المساعدة", callback_data="help"), InlineKeyboardButton("🆔 معلوماتي", callback_data="myinfo")],
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    load_all_data()
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name
    
    # إضافة المستخدم للقاعدة
    if str(user_id) not in USERS_DB:
        USERS_DB[str(user_id)] = {
            "first_name": first_name,
            "joined": datetime.now().isoformat(),
            "status": "free",
            "searches": 0,
            "access_code": None
        }
        save_all_data()
    
    user_data = USERS_DB[str(user_id)]
    access_code = context.user_data.get("access_code")
    
    if access_code:
        valid, msg = is_code_valid(user_id, access_code)
        status_emoji = "🟢 مصرح" if valid else f"🔴 {msg}"
    else:
        status_emoji = "🟡 بحاجة لكود"
    
    welcome_text = (
        f"╔═══════════════════════════════════╗\n"
        f"║   🤖 بوت البحث المتقدم v4.0 ⚡   ║\n"
        f"║                                   ║\n"
        f"║        مرحباً {first_name} 👋         ║\n"
        f"╚═══════════════════════════════════╝\n\n"
        f"📊 حالتك: {status_emoji}\n"
        f"🔎 عدد البحثيات: {user_data['searches']}\n"
        f"📅 تاريخ الانضمام: {user_data['joined'][:10]}\n\n"
        f"🎯 اختر من الخيارات أدناه للبدء!"
    )
    
    await update.message.reply_text(welcome_text, reply_markup=get_main_menu())

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "search":
        await query.edit_message_text(
            text="🔍 *وضع البحث*\n\n"
            "📝 أرسل الكلمة التي تريد البحث عنها:\n\n"
            "💡 نصيحة: يمكنك البحث في عدة كلمات بفاصل عنقود",
            parse_mode="Markdown"
        )
        context.user_data["mode"] = "search"
    
    elif query.data == "files":
        if not context.user_data.get("files_loaded"):
            await query.edit_message_text(
                text="📁 *إدارة الملفات*\n\n"
                "❌ لم تحمل أي ملفات حتى الآن\n\n"
                "📎 أرسل رابط Google Drive لتحميل ZIP file"
            )
        else:
            txt_files = list(Path(DATA_DIR).rglob("*.txt"))
            await query.edit_message_text(
                text=f"📁 *الملفات المحملة*\n\n"
                f"📊 عدد الملفات: {len(txt_files)}\n\n"
                f"✅ جاهز للبحث!"
            )
    
    elif query.data == "stats":
        load_all_data()
        user_id = str(update.effective_user.id)
        user_data = USERS_DB.get(user_id, {})
        await query.edit_message_text(
            text=f"📊 *إحصائياتك*\n\n"
            f"🔍 عدد البحثيات: {user_data.get('searches', 0)}\n"
            f"📅 في المنصة: {user_data.get('joined', 'N/A')[:10]}\n"
            f"💾 حجم البيانات: N/A\n"
            f"⭐ النقاط: {user_data.get('searches', 0) * 10}"
        )
    
    elif query.data == "history":
        await query.edit_message_text(
            text="📜 *سجل البحث*\n\n"
            "📝 آخر 10 بحثيات:\n\n"
            "لا توجد بحثيات سابقة"
        )
    
    elif query.data == "subscription":
        keyboard = [
            [InlineKeyboardButton("🎁 خطة مجانية", callback_data="plan_free"), InlineKeyboardButton("⭐ خطة بريميوم", callback_data="plan_premium")],
            [InlineKeyboardButton("👑 خطة Pro", callback_data="plan_pro")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back")]
        ]
        await query.edit_message_text(
            text="💳 *الاشتراكات والخطط*\n\n"
            "🎁 *خطة مجانية*\n"
            "  ✓ بحث أساسي\n"
            "  ✓ ملف واحد فقط\n\n"
            "⭐ *خطة بريميوم* ($4.99/شهر)\n"
            "  ✓ بحث متقدم\n"
            "  ✓ 5 ملفات\n"
            "  ✓ تصدير النتائج\n\n"
            "👑 *خطة Pro* ($9.99/شهر)\n"
            "  ✓ بحث ذكي\n"
            "  ✓ ملفات غير محدودة\n"
            "  ✓ أولوية دعم",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif query.data == "settings":
        keyboard = [
            [InlineKeyboardButton("🎟️ إدخال كود", callback_data="enter_code"), InlineKeyboardButton("🗣️ اللغة", callback_data="language")],
            [InlineKeyboardButton("🔔 التنبيهات", callback_data="notifications")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back")]
        ]
        await query.edit_message_text(
            text="⚙️ *الإعدادات*\n\n"
            "🎛️ اختر الإعداد الذي تريد تغييره:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif query.data == "enter_code":
        await query.edit_message_text(
            text="🎟️ *إدخال كود الوصول*\n\n"
            "📝 أرسل الكود الخاص بك:"
        )
        context.user_data["mode"] = "redeem"
    
    elif query.data == "help":
        await query.edit_message_text(
            text="❓ *المساعدة والدعم*\n\n"
            "📖 الأوامر الرئيسية:\n"
            "/start - البدء\n"
            "/search - البحث\n"
            "/files - الملفات\n"
            "/redeem - إدخال كود\n\n"
            "💬 للتواصل: @support"
        )
    
    elif query.data == "myinfo":
        user = update.effective_user
        await query.edit_message_text(
            text=f"🆔 *معلوماتك*\n\n"
            f"👤 الاسم: {user.first_name}\n"
            f"📱 ID: `{user.id}`\n"
            f"⭐ الحالة: عضو نشط\n"
            f"📊 الرصيد: 0"
        )
    
    elif query.data == "back":
        await query.edit_message_text(
            text="🏠 *القائمة الرئيسية*",
            reply_markup=get_main_menu()
        )

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
            f"🎟️ الكود: {text}\n"
            f"🟢 جاهز للبحث الآن",
            reply_markup=get_main_menu()
        )
        context.user_data["mode"] = "normal"
        return
    
    if "drive.google.com" in text:
        file_id = extract_drive_id(text)
        if not file_id:
            await update.message.reply_text("❌ رابط غير صحيح")
            return
        
        msg = await update.message.reply_text("⬇️ جاري تحميل الملف...\n⏳ قد يستغرق بعض الوقت")
        
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
            total_lines = 0
            for txt_file in txt_files:
                try:
                    with open(txt_file, "r", encoding="utf-8", errors="ignore") as f:
                        total_lines += sum(1 for _ in f)
                except:
                    pass
            
            context.user_data["files_loaded"] = True
            
            await msg.edit_text(
                f"✅ تم التحميل بنجاح! 🎉\n\n"
                f"📄 عدد الملفات: {len(txt_files)}\n"
                f"📊 عدد السطور: {total_lines:,}\n\n"
                f"🔍 جاهز للبحث!"
            )
        except Exception as e:
            await msg.edit_text(f"❌ خطأ: {str(e)[:50]}")
        return
    
    if mode == "search" or context.user_data.get("files_loaded"):
        if not context.user_data.get("files_loaded"):
            await update.message.reply_text("❌ لم تحمل ملفات حتى الآن")
            return
        
        keyword = text
        search_msg = await update.message.reply_text(f"🔍 بحث عن: *{keyword}*\n⏳ جاري البحث...")
        
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
            await search_msg.edit_text(f"❌ خطأ: {e}")
            return
        
        if not results:
            await search_msg.edit_text(f"😕 لم نجد نتائج عن: *{keyword}*")
            return
        
        # حفظ في قاعدة البيانات
        user_data = USERS_DB[str(user_id)]
        user_data["searches"] += 1
        save_all_data()
        
        result_file = "resultat.txt"
        with open(result_file, "w", encoding="utf-8") as f:
            f.write(f"{'='*60}\n")
            f.write(f"نتائج البحث عن: {keyword}\n")
            f.write(f"عدد النتائج: {len(results):,}\n")
            f.write(f"التاريخ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"{'='*60}\n\n")
            for i, line in enumerate(results[:5000], 1):
                f.write(f"{i}. {line}\n")
            if len(results) > 5000:
                f.write(f"\n... و {len(results) - 5000:,} نتيجة أخرى")
        
        await search_msg.edit_text(
            f"✅ تم البحث بنجاح! 🎉\n\n"
            f"🔍 البحث عن: *{keyword}*\n"
            f"📊 النتائج: *{len(results):,}*\n"
            f"⏱️ الوقت: {datetime.now().strftime('%H:%M:%S')}"
        )
        
        await update.message.reply_document(
            document=open(result_file, "rb"),
            filename=f"results_{keyword}.txt",
            caption=f"📥 النتائج ({len(results):,})"
        )

async def myid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(
        f"🔑 معرفك الفريد:\n\n`{user_id}`"
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
    try:
        max_uses = int(context.args[1])
    except:
        await update.message.reply_text("❌ عدد المرات يجب أن يكون رقم")
        return
    
    expiry_date = context.args[2]
    expires_at = f"{expiry_date}T23:59:59"
    
    if code in ACCESS_CODES:
        await update.message.reply_text(f"❌ الكود موجود")
        return
    
    ACCESS_CODES[code] = {
        "max_uses": max_uses,
        "used_count": 0,
        "expires_at": expires_at
    }
    save_all_data()
    
    await update.message.reply_text(
        f"✅ تم إنشاء كود جديد\n\n"
        f"🎟️ الكود: {code}\n"
        f"📊 المرات: {max_uses}\n"
        f"📅 انتهاء: {expiry_date}"
    )

def main():
    load_all_data()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", myid_cmd))
    app.add_handler(CommandHandler("addcode", addcode_cmd))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("🚀 بوت البحث شغال! ✅")
    app.run_polling()

if __name__ == "__main__":
    main()
