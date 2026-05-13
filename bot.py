import os
import re
import logging
import gdown
import zipfile
import shutil
import json
from datetime import datetime, timedelta
from pathlib import Path
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))  # ضع رقم ID ديالك
DATA_DIR = "extracted_files"
ZIP_FILE = "data.zip"
CODES_FILE = "access_codes.json"

# قاموس مؤقت للكود الصحيح
ACCESS_CODES = {}

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
    
    # تحقق من انتهاء الصلاحية
    if code_data["expires_at"]:
        expires = datetime.fromisoformat(code_data["expires_at"])
        if datetime.now() > expires:
            return False, "⏰ الكود انتهت صلاحيته"
    
    # تحقق من عدد المرات
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
    
    if user_code:
        valid, msg = is_code_valid(user_id, user_code)
        status = "✅ مصرح" if valid else f"❌ {msg}"
    else:
        status = "⚠️ محتاج كود"
    
    await update.message.reply_text(
        f"سلام! 👋\n\n"
        f"أنا بوت البحث ديالك 🔍\n"
        f"الحالة: {status}\n\n"
        f"📋 الأوامر المتاحة:\n"
        f"🎟️ /redeem <كود> — استخدم كود الوصول\n"
        f"📁 /files — عرض الفايلات المحملة\n"
        f"🔍 /search <كلمة> — ابحث في الفايلات\n"
        f"⏹️ /stop — إيقاف العملية\n"
        f"🗑️ /reset — مسح النتائج\n\n"
        f"📎 ابعثلي رابط Google Drive باش نحمل ZIP"
    )

async def redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استخدم كود الوصول"""
    load_codes()
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text("❌ استعمل: /redeem <الكود>")
        return
    
    code = context.args[0]
    valid, msg = is_code_valid(user_id, code)
    
    if not valid:
        await update.message.reply_text(msg)
        return
    
    # حفظ الكود
    context.user_data["access_code"] = code
    
    # زيد عدد الاستعمال
    ACCESS_CODES[code]["used_count"] += 1
    save_codes()
    
    # أبلغ الـ admin
    if ADMIN_ID:
        remaining = ACCESS_CODES[code]["max_uses"] - ACCESS_CODES[code]["used_count"]
        remaining_text = f"({remaining} مرات متبقية)" if remaining > 0 else "(استنفذ الحد الأقصى)"
        await context.bot.send_message(
            ADMIN_ID,
            f"🔓 كود دخل!\n"
            f"👤 المستخدم: {update.effective_user.mention_html()}\n"
            f"🎟️ الكود: {code}\n"
            f"📊 الاستخدامات: {remaining_text}",
            parse_mode="HTML"
        )
    
    await update.message.reply_text(
        f"✅ الكود قبول!\n"
        f"دابا متقدر تبحث في الفايلات 🔍"
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """التعامل مع الرسائل النصية"""
    load_codes()
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # تحقق من الكود
    user_code = context.user_data.get("access_code")
    if not user_code:
        await update.message.reply_text("⚠️ محتاج تدخل كود أولاً\nاستعمل: /redeem <الكود>")
        return
    
    valid, msg = is_code_valid(user_id, user_code)
    if not valid:
        await update.message.reply_text(msg)
        context.user_data.pop("access_code", None)
        return
    
    # إذا كان رابط Google Drive
    if "drive.google.com" in text:
        file_id = extract_drive_id(text)
        if not file_id:
            await update.message.reply_text("❌ الرابط ما صحيحش. تحقق منو وعاود.")
            return

        await update.message.reply_text("⬇️ بدات نحمل الـ ZIP... هاد العملية تاخد وقت (3GB كبيرة).")

        try:
            url = f"https://drive.google.com/uc?id={file_id}"
            gdown.download(url, ZIP_FILE, quiet=False, fuzzy=True)

            if os.path.exists(DATA_DIR):
                shutil.rmtree(DATA_DIR)
            os.makedirs(DATA_DIR, exist_ok=True)

            await update.message.reply_text("⏳ كنستخرج الـ TXT files... صبر شوية.")
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

    # البحث العادي
    if not context.user_data.get("files_loaded"):
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

    result_file = "resultat.txt"
    with open(result_file, "w", encoding="utf-8") as f:
        f.write(f"نتائج البحث على: {keyword}\n")
        f.write(f"عدد النتائج: {len(results):,}\n")
        f.write("=" * 50 + "\n\n")
        for line in results[:5000]:
            f.write(line + "\n")
        if len(results) > 5000:
            f.write(f"\n... و {len(results) - 5000:,} نتيجة أخرى")

    await update.message.reply_document(
        document=open(result_file, "rb"),
        filename="resultat.txt",
        caption=f"✅ لقيت *{len(results):,}* نتيجة على '{keyword}'",
        parse_mode="Markdown"
    )

async def files_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض الفايلات"""
    if not context.user_data.get("files_loaded"):
        await update.message.reply_text("❌ ما كاين فايلات محملة")
        return
    
    txt_files = list(Path(DATA_DIR).rglob("*.txt"))
    await update.message.reply_text(
        f"📁 الفايلات المحملة:\n\n"
        f"📄 عدد الـ TXT files: {len(txt_files)}"
    )

async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إيقاف العملية"""
    await update.message.reply_text("⏹️ تم إيقاف العملية")

async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إعادة تعيين"""
    context.user_data.pop("files_loaded", None)
    await update.message.reply_text("🗑️ تم مسح النتائج المؤقتة")

async def myid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض ID ديالك"""
    user_id = update.effective_user.id
    await update.message.reply_text(
        f"🔑 ID ديالك:\n`{user_id}`\n\n"
        f"استعمل هاد الرقم في ADMIN_ID",
        parse_mode="Markdown"
    )

async def addcode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إضافة كود جديد (Admin فقط)"""
    load_codes()
    user_id = update.effective_user.id
    
    # تحقق أنو Admin
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ هاد الأمر للـ Admin فقط")
        return
    
    # تحقق من الحجج
    if len(context.args) < 3:
        await update.message.reply_text(
            "❌ استعمال:\n"
            "/addcode <الكود> <عدد_المرات> <تاريخ_الانتهاء>\n\n"
            "مثال:\n"
            "/addcode CODE123 10 2026-12-31\n"
            "/addcode UNLOCK 5 2026-06-30"
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
    
    # تحقق أن الكود ما موجود
    if code in ACCESS_CODES:
        await update.message.reply_text(f"❌ الكود '{code}' موجود دابا")
        return
    
    # أضيف الكود
    ACCESS_CODES[code] = {
        "max_uses": max_uses,
        "used_count": 0,
        "expires_at": expires_at
    }
    save_codes()
    
    await update.message.reply_text(
        f"✅ كود جديد تم إنشاؤه!\n\n"
        f"🎟️ الكود: `{code}`\n"
        f"📊 عدد المرات: {max_uses}\n"
        f"📅 ينتهي: {expiry_date}\n\n"
        f"المستخدمين يقدرو يدخلو بـ:\n"
        f"/redeem {code}",
        parse_mode="Markdown"
    )

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
    
    msg = "📋 جميع الأكواس:\n\n"
    for code, data in ACCESS_CODES.items():
        remaining = data["max_uses"] - data["used_count"]
        expires = data["expires_at"][:10] if data["expires_at"] else "∞"
        msg += f"🎟️ {code}\n"
        msg += f"   استخدام: {data['used_count']}/{data['max_uses']}\n"
        msg += f"   متبقي: {remaining}\n"
        msg += f"   ينتهي: {expires}\n\n"
    
    await update.message.reply_text(msg)

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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("البوت شغال! ✅")
    app.run_polling()

if __name__ == "__main__":
    main()
