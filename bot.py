import os
import re
import logging
import gdown
import zipfile
import shutil
import json
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
DATA_DIR = "extracted_files"
ZIP_FILE = "data.zip"
CODES_FILE = "access_codes.json"

ACCESS_CODES = {}

# Emoji animations
LOADING_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

def load_codes():
    """حمل الأكواد من الملف"""
    global ACCESS_CODES
    if os.path.exists(CODES_FILE):
        try:
            with open(CODES_FILE, "r") as f:
                ACCESS_CODES = json.load(f)
        except:
            ACCESS_CODES = {}

def save_codes():
    """حفظ الأكواد في الملف"""
    with open(CODES_FILE, "w") as f:
        json.dump(ACCESS_CODES, f)

def is_code_valid(user_id, code):
    """تحقق من صحة الكود"""
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
    load_codes()
    user_id = update.effective_user.id
    user_code = context.user_data.get("access_code")
    first_name = update.effective_user.first_name
    
    if user_code:
        valid, msg = is_code_valid(user_id, user_code)
        status = "✅ مصرح" if valid else f"❌ {msg}"
        status_emoji = "🟢" if valid else "🔴"
    else:
        status = "⚠️ محتاج كود"
        status_emoji = "🟡"
    
    welcome_msg = (
        f"╔══════════════════════════╗\n"
        f"║  سلام يا {first_name}! 👋      ║\n"
        f"╚══════════════════════════╝\n\n"
        f"{status_emoji} الحالة: {status}\n\n"
        f"🤖 بوت البحث المتقدم v2.0\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 الأوامر الرئيسية:\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎟️  /redeem <كود>\n"
        f"📁 /files\n"
        f"🔍 /search <كلمة>\n"
        f"⏹️  /stop\n"
        f"🗑️  /reset\n"
        f"❓ /help\n"
        f"🆔 /myid\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📎 ابعثلي رابط Google Drive\n"
    )
    
    await update.message.reply_text(welcome_msg, parse_mode="HTML")

async def redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استخدم كود الوصول"""
    load_codes()
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text("❌ استعمل: /redeem <الكود>")
        return
    
    code = context.args[0]
    
    status_msg = await update.message.reply_text("⏳ كنتحقق من الكود...")
    
    await asyncio.sleep(0.5)
    
    valid, msg = is_code_valid(user_id, code)
    
    if not valid:
        await status_msg.edit_text(f"❌ {msg}")
        return
    
    context.user_data["access_code"] = code
    ACCESS_CODES[code]["used_count"] += 1
    save_codes()
    
    if ADMIN_ID:
        remaining = ACCESS_CODES[code]["max_uses"] - ACCESS_CODES[code]["used_count"]
        remaining_text = f"({remaining} مرات متبقية)" if remaining > 0 else "(استنفذ الحد الأقصى)"
        await context.bot.send_message(
            ADMIN_ID,
            f"🔓 كود جديد دخل!\n\n"
            f"👤 المستخدم: {update.effective_user.mention_html()}\n"
            f"🎟️  الكود: <code>{code}</code>\n"
            f"⏰ الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"📊 الاستخدامات: {remaining_text}",
            parse_mode="HTML"
        )
    
    success_msg = (
        f"╔══════════════════════════╗\n"
        f"║     ✅ نجح! 🎉          ║\n"
        f"╚══════════════════════════╝\n\n"
        f"🎟️  الكود: <code>{code}</code>\n"
        f"📊 الحالة: مفعل\n"
        f"🟢 جاهز للبحث!\n\n"
        f"اكتب /search <كلمة> باش تبدا"
    )
    
    await status_msg.edit_text(success_msg, parse_mode="HTML")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """التعامل مع الرسائل النصية"""
    load_codes()
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    user_code = context.user_data.get("access_code")
    if not user_code:
        await update.message.reply_text(
            "⚠️  محتاج تدخل كود أولاً\n\n"
            "استعمل: /redeem <الكود>"
        )
        return
    
    valid, msg = is_code_valid(user_id, user_code)
    if not valid:
        await update.message.reply_text(msg)
        context.user_data.pop("access_code", None)
        return
    
    if "drive.google.com" in text:
        file_id = extract_drive_id(text)
        if not file_id:
            await update.message.reply_text("❌ الرابط ما صحيحش. تحقق منو وعاود.")
            return

        progress_msg = await update.message.reply_text(
            "⬇️  بدات نحمل الـ ZIP...\n"
            "هاد العملية تاخد وقت (3GB كبيرة)\n\n"
            "صبر شوية... ⏳"
        )

        try:
            url = f"https://drive.google.com/uc?id={file_id}"
            gdown.download(url, ZIP_FILE, quiet=False, fuzzy=True)

            await progress_msg.edit_text(
                "🔄 كنستخرج الـ TXT files...\n"
                "صبر شوية..."
            )

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
            
            success_msg = (
                f"╔══════════════════════════╗\n"
                f"║   ✅ تحمل بنجاح! 🎉    ║\n"
                f"╚══════════════════════════╝\n\n"
                f"📄 عدد الـ TXT files: {len(txt_files)}\n"
                f"📊 عدد الليني: {total_lines:,}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔍 بعثلي الكلمة اللي بغيتي\n"
                f"تبحث عليها الآن"
            )
            
            await progress_msg.edit_text(success_msg)

        except Exception as e:
            await progress_msg.edit_text(
                f"❌ مشكل:\n<code>{str(e)[:100]}</code>\n\n"
                "تحقق أن الفايل ZIP وأنو shared",
                parse_mode="HTML"
            )
        return

    if not context.user_data.get("files_loaded"):
        await update.message.reply_text(
            "❌ ما عندي ZIP محفوظ.\n\n"
            "بعثلي رابط Google Drive أولاً"
        )
        return

    keyword = text
    search_msg = await update.message.reply_text(
        f"🔍 كنبحث عن: <code>{keyword}</code>\n\n"
        f"صبر شوية... {LOADING_FRAMES[0]}",
        parse_mode="HTML"
    )

    results = []
    try:
        txt_files = list(Path(DATA_DIR).rglob("*.txt"))
        for i, txt_file in enumerate(txt_files):
            try:
                with open(txt_file, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if keyword.lower() in line.lower():
                            results.append(line.rstrip("\n"))
            except:
                pass
            
            if i % 5 == 0:
                frame = LOADING_FRAMES[i % len(LOADING_FRAMES)]
                await search_msg.edit_text(
                    f"🔍 كنبحث عن: <code>{keyword}</code>\n\n"
                    f"صبر شوية... {frame}",
                    parse_mode="HTML"
                )
    except Exception as e:
        await search_msg.edit_text(f"❌ خطأ: {e}")
        return

    if not results:
        await search_msg.edit_text(
            f"😕 ما لقيت والو على:\n"
            f"<code>{keyword}</code>",
            parse_mode="HTML"
        )
        return

    result_file = "resultat.txt"
    with open(result_file, "w", encoding="utf-8") as f:
        f.write(f"{'='*50}\n")
        f.write(f"نتائج البحث عن: {keyword}\n")
        f.write(f"{'='*50}\n")
        f.write(f"عدد النتائج: {len(results):,}\n")
        f.write(f"تاريخ البحث: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"{'='*50}\n\n")
        for i, line in enumerate(results[:5000], 1):
            f.write(f"{i}. {line}\n")
        if len(results) > 5000:
            f.write(f"\n... و {len(results) - 5000:,} نتيجة أخرى")

    result_msg = (
        f"╔══════════════════════════╗\n"
        f"║   ✅ تم البحث بنجاح! 🎉  ║\n"
        f"╚══════════════════════════╝\n\n"
        f"🔍 الكلمة: <code>{keyword}</code>\n"
        f"📊 عدد النتائج: <b>{len(results):,}</b>\n"
        f"📅 الوقت: {datetime.now().strftime('%H:%M:%S')}"
    )
    
    await search_msg.edit_text(result_msg, parse_mode="HTML")
    
    await update.message.reply_document(
        document=open(result_file, "rb"),
        filename=f"results_{keyword.replace(' ', '_')}.txt",
        caption=f"✅ النتائج ({len(results):,}):"
    )

async def files_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض الفايلات"""
    if not context.user_data.get("files_loaded"):
        await update.message.reply_text(
            "❌ ما كاين فايلات محملة\n\n"
            "بعثلي رابط Google Drive أولاً"
        )
        return
    
    txt_files = list(Path(DATA_DIR).rglob("*.txt"))
    files_list = "\n".join([f"📄 {f.name}" for f in txt_files[:20]])
    
    msg = (
        f"╔══════════════════════════╗\n"
        f"║   📁 الفايلات المحملة    ║\n"
        f"╚══════════════════════════╝\n\n"
        f"📊 عدد الـ TXT files: {len(txt_files)}\n\n"
        f"📋 قائمة الفايلات:\n"
        f"{files_list}"
    )
    
    if len(txt_files) > 20:
        msg += f"\n\n... و {len(txt_files) - 20} فايلات أخرى"
    
    await update.message.reply_text(msg)

async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إيقاف العملية"""
    await update.message.reply_text("⏹️  تم إيقاف العملية ✅")

async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إعادة تعيين"""
    context.user_data.pop("files_loaded", None)
    await update.message.reply_text("🗑️  تم مسح النتائج المؤقتة ✅")

async def myid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض ID ديالك"""
    user_id = update.effective_user.id
    msg = (
        f"╔══════════════════════════╗\n"
        f"║    🔑 معرفك الفريد      ║\n"
        f"╚══════════════════════════╝\n\n"
        f"ID: <code>{user_id}</code>\n\n"
        f"نسخ الرقم واستعمله في ADMIN_ID"
    )
    await update.message.reply_text(msg, parse_mode="HTML")

async def addcode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إضافة كود جديد (Admin فقط)"""
    load_codes()
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ هاد الأمر للـ Admin فقط")
        return
    
    if len(context.args) < 3:
        await update.message.reply_text(
            "❌ الاستخدام الصحيح:\n\n"
            "<code>/addcode <الكود> <عدد_المرات> <تاريخ_الانتهاء></code>\n\n"
            "أمثلة:\n"
            "<code>/addcode CODE123 10 2026-12-31</code>\n"
            "<code>/addcode UNLOCK 5 2026-06-30</code>",
            parse_mode="HTML"
        )
        return
    
    code = context.args[0]
    try:
        max_uses = int(context.args[1])
    except:
        await update.message.reply_text("❌ عدد المرات محتاج يكون رقم")
        return
    
    try:
        expiry_date = context.args[2]
        datetime.strptime(expiry_date, "%Y-%m-%d")
        expires_at = f"{expiry_date}T23:59:59"
    except:
        await update.message.reply_text("❌ التاريخ محتاج يكون بالشكل: YYYY-MM-DD")
        return
    
    if code in ACCESS_CODES:
        await update.message.reply_text(f"❌ الكود '{code}' موجود دابا")
        return
    
    ACCESS_CODES[code] = {
        "max_uses": max_uses,
        "used_count": 0,
        "expires_at": expires_at
    }
    save_codes()
    
    msg = (
        f"╔══════════════════════════╗\n"
        f"║   ✅ كود جديد تم إنشاؤه  ║\n"
        f"╚══════════════════════════╝\n\n"
        f"🎟️  الكود: <code>{code}</code>\n"
        f"📊 عدد المرات: {max_uses}\n"
        f"📅 ينتهي: {expiry_date}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"المستخدمون يقدرو يدخلو بـ:\n"
        f"<code>/redeem {code}</code>"
    )
    
    await update.message.reply_text(msg, parse_mode="HTML")

async def codes_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض جميع الأكواس (Admin فقط)"""
    load_codes()
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ هاد الأمر للـ Admin فقط")
        return
    
    if not ACCESS_CODES:
        await update.message.reply_text("❌ ما كاين أكواس")
        return
    
    msg = (
        f"╔══════════════════════════╗\n"
        f"║    📋 جميع الأكواس      ║\n"
        f"╚══════════════════════════╝\n\n"
    )
    
    for code, data in ACCESS_CODES.items():
        remaining = data["max_uses"] - data["used_count"]
        expires = data["expires_at"][:10] if data["expires_at"] else "∞"
        status = "🟢" if remaining > 0 else "🔴"
        
        msg += (
            f"{status} <code>{code}</code>\n"
            f"   📊 الاستخدام: {data['used_count']}/{data['max_uses']}\n"
            f"   📈 المتبقي: {remaining}\n"
            f"   📅 ينتهي: {expires}\n\n"
        )
    
    await update.message.reply_text(msg, parse_mode="HTML")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض جميع الأوامر"""
    user_id = update.effective_user.id
    is_admin = user_id == ADMIN_ID
    
    help_text = (
        f"╔══════════════════════════╗\n"
        f"║   📖 قائمة الأوامر      ║\n"
        f"╚══════════════════════════╝\n\n"
        
        f"🟢 <b>أوامر عامة:</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• /start — ابدأ من هنا\n"
        f"• /myid — اعرض ID ديالك\n"
        f"• /redeem &lt;كود&gt; — استخدم كود\n"
        f"• /search &lt;كلمة&gt; — ابحث\n"
        f"• /files — الفايلات\n"
        f"• /reset — مسح النتائج\n"
        f"• /stop — إيقاف\n"
        f"• /help — هاد الرسالة\n\n"
    )
    
    if is_admin:
        help_text += (
            f"🔴 <b>أوامر Admin:</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• /addcode &lt;كود&gt; &lt;مرات&gt; &lt;تاريخ&gt;\n"
            f"• /codes — عرض جميع الأكواس\n\n"
        )
    
    help_text += (
        f"📖 <b>كيفاش تستعمل:</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"1️⃣  /redeem CODE\n"
        f"2️⃣  بعت رابط ZIP من Drive\n"
        f"3️⃣  /search كلمة\n"
        f"4️⃣  حصل على النتائج ✅"
    )
    
    await update.message.reply_text(help_text, parse_mode="HTML")

def main():
    load_codes()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("redeem", redeem))
    app.add_handler(CommandHandler("files", files_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CommandHandler("myid", myid_cmd))
    app.add_handler(CommandHandler("addcode", addcode_cmd))
    app.add_handler(CommandHandler("codes", codes_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("🚀 البوت شغال! ✅")
    app.run_polling()

if __name__ == "__main__":
    main()
