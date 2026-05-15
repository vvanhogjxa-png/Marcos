import os
import re
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

# متغيرات عامة
current_combos = []
current_combos_text = ""

def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("🔄 Combo Converter", callback_data="converter")],
        [InlineKeyboardButton("🔍 Search Combos", callback_data="search_mode")],
        [InlineKeyboardButton("📊 Statistics", callback_data="stats")],
        [InlineKeyboardButton("❓ Help", callback_data="help")],
    ]
    return InlineKeyboardMarkup(keyboard)

def extract_combos_from_url(url):
    """استخراج جميع أنواع combos من URL"""
    try:
        url = url.strip()
        combos_found = []
        
        # Pattern: :email@domain.com:password
        email_match = re.search(r':([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}):[^/:]+', url)
        if email_match:
            email = email_match.group(1)
            # استخرج password بعد الـ email
            pass_match = re.search(rf':{re.escape(email)}:([^/:]+)', url)
            if pass_match:
                password = pass_match.group(1)
                combos_found.append(f"{email}:{password}")
        
        # Pattern: :username:password (كلمات بدون @)
        # النمط: :word:word أو :word:word123
        matches = re.findall(r':([a-zA-Z0-9._-]+):([a-zA-Z0-9!*@#$%-]+)', url)
        for match in matches:
            username, password = match
            # تأكد أنه ليس جزء من الرابط (مثل http://)
            if username not in ['http', 'https', 'ftp'] and len(username) > 1:
                combo = f"{username}:{password}"
                if combo not in combos_found:
                    combos_found.append(combo)
        
        # Pattern: :number:password (رقم: password)
        # مثل :+201206971267:password أو :1234567890:password
        number_pattern = r':(\+?[0-9]{7,}):([^/:]+)'
        number_matches = re.findall(number_pattern, url)
        for match in number_matches:
            number, password = match
            combo = f"{number}:{password}"
            if combo not in combos_found:
                combos_found.append(combo)
        
        return combos_found if combos_found else None
    except:
        return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "╔═════════════════════════════════╗\n"
        "║  🤖 Combo Converter & Search    ║\n"
        "║          v1.0 ⚡               ║\n"
        "╚═════════════════════════════════╝\n\n"
        "👋 مرحباً! اختر من الخيارات:"
    )
    
    await update.message.reply_text(welcome_text, reply_markup=get_main_menu())

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "converter":
        await query.edit_message_text(
            text="🔄 *Combo Converter*\n\n"
            "📤 أرسل ملف TXT يحتوي على URLs\n\n"
            "سيتم استخراج:\n"
            "✅ email:password\n"
            "✅ username:password\n"
            "✅ number:password",
            parse_mode="Markdown"
        )
        context.user_data["mode"] = "converter"
    
    elif query.data == "search_mode":
        await query.edit_message_text(
            text="🔍 *Search Combos*\n\n"
            "حمل combos أولاً باستخدام Converter\n"
            "ثم ابحث فيها",
            parse_mode="Markdown"
        )
        context.user_data["mode"] = "search"
    
    elif query.data == "stats":
        await query.edit_message_text(
            text=f"📊 *الإحصائيات*\n\n"
            f"💾 Combos محملة: {len(current_combos)}\n"
            f"⏰ التاريخ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
    
    elif query.data == "help":
        await query.edit_message_text(
            text="❓ *المساعدة*\n\n"
            "1️⃣ اختر Converter\n"
            "2️⃣ أرسل ملف TXT\n"
            "3️⃣ حصل على combos\n"
            "4️⃣ ابحث فيها باستخدام Search",
            parse_mode="Markdown"
        )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة ملفات TXT"""
    global current_combos, current_combos_text
    
    document = update.message.document
    
    if not document.file_name.endswith('.txt'):
        await update.message.reply_text("❌ أرسل ملف TXT فقط")
        return
    
    # تحميل الملف
    file = await context.bot.get_file(document.file_id)
    await file.download_to_drive("temp_input.txt")
    
    # قراءة الملف
    combos_found = []
    failed_lines = 0
    
    with open("temp_input.txt", "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    
    total = len(lines)
    status_msg = await update.message.reply_text(
        f"⏳ جاري المعالجة...\n\n"
        f"Progress: 0%"
    )
    
    for i, line in enumerate(lines):
        line = line.strip()
        if line:
            combos = extract_combos_from_url(line)
            if combos:
                combos_found.extend(combos)
            else:
                failed_lines += 1
        
        # تحديث Progress
        percentage = ((i + 1) / total) * 100
        if (i + 1) % max(1, total // 10) == 0:
            bar_length = 20
            filled = int(bar_length * percentage / 100)
            bar = "█" * filled + "░" * (bar_length - filled)
            
            await status_msg.edit_text(
                f"⏳ جاري المعالجة...\n\n"
                f"[{bar}] {percentage:.1f}%\n"
                f"✅ Combos: {len(combos_found)}\n"
                f"⚠️ فشل: {failed_lines}"
            )
    
    if not combos_found:
        await status_msg.edit_text("❌ لم يتم العثور على أي combos")
        os.remove("temp_input.txt")
        return
    
    # إزالة التكرارات
    unique_combos = list(dict.fromkeys(combos_found))
    
    # حفظ النتائج
    output_file = "combos_output.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        for combo in unique_combos:
            f.write(combo + "\n")
    
    # حفظ في الذاكرة للبحث
    current_combos = unique_combos
    with open(output_file, "r") as f:
        current_combos_text = f.read()
    
    success_rate = (len(unique_combos) / total) * 100
    
    # الرسالة النهائية
    await status_msg.edit_text(
        f"✅ تم بنجاح! 🎉\n\n"
        f"📊 إجمالي URLs: {total}\n"
        f"✅ Combos: {len(unique_combos)}\n"
        f"⚠️ فشل: {failed_lines}\n"
        f"⚡ النسبة: {success_rate:.1f}%"
    )
    
    # إرسال الملف
    await update.message.reply_document(
        document=open(output_file, "rb"),
        filename="combos_output.txt",
        caption=f"📥 Combos ({len(unique_combos)})"
    )
    
    os.remove("temp_input.txt")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الرسائل النصية"""
    global current_combos
    
    text = update.message.text.strip()
    mode = context.user_data.get("mode", "normal")
    
    if mode == "search":
        # ✅ تحقق من الكود أولاً
        access_code = context.user_data.get("access_code")
        if not access_code:
            await update.message.reply_text(
                "⚠️ محتاج تدخل كود وصول أولاً!\n\n"
                "🔐 استخدم الإعدادات لإدخال الكود"
            )
            return
        
        if not current_combos:
            await update.message.reply_text(
                "❌ لا توجد combos محملة\n\n"
                "استخدم Converter أولاً"
            )
            return
        
        # البحث
        keyword = text.lower()
        results = [c for c in current_combos if keyword in c.lower()]
        
        if not results:
            await update.message.reply_text(f"😕 لم نجد نتائج عن: {text}")
            return
        
        # حفظ النتائج (كل النتائج بدون قص)
        search_results_file = "search_results.txt"
        with open(search_results_file, "w", encoding="utf-8") as f:
            f.write(f"Search Results for: {text}\n")
            f.write(f"Found: {len(results)}\n")
            f.write("=" * 50 + "\n\n")
            for i, combo in enumerate(results, 1):  # ✅ بدون [:5000]
                f.write(f"{i}. {combo}\n")
        
        search_msg = await update.message.reply_text(
            f"✅ تم البحث! 🎉\n\n"
            f"🔍 البحث عن: {text}\n"
            f"📊 النتائج: {len(results)}"
        )
        
        await update.message.reply_document(
            document=open(search_results_file, "rb"),
            filename=f"search_{text}.txt",
            caption=f"📥 النتائج ({len(results)})"
        )

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("🚀 Combo Bot شغال! ✅")
    app.run_polling()

if __name__ == "__main__":
    main()
