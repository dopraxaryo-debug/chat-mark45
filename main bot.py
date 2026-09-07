import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
import db

logging.basicConfig(level=logging.INFO)

TOKEN = os.environ.get("BOT_TOKEN")
BOT_USERNAME = os.environ.get("BOT_USERNAME")  # بدون @ - مثلا MyAnonBot
ADMIN_IDS = {int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()}

# آیدی یا یوزرنیم کانال‌های اجباری - با @ یا به شکل عددی (-100...)
REQUIRED_CHANNELS = [
    c.strip() for c in os.environ.get("REQUIRED_CHANNELS", "").split(",") if c.strip()
]

MAIN_MENU = ReplyKeyboardMarkup(
    [["🔗 لینک من"], ["🚫 لیست مسدودی‌ها", "🆘 پشتیبانی"]],
    resize_keyboard=True,
)


def is_admin(user_id):
    return user_id in ADMIN_IDS


async def get_not_joined_channels(context, user_id):
    """کانال‌هایی که کاربر هنوز عضوشون نشده رو برمی‌گردونه."""
    not_joined = []
    for channel in REQUIRED_CHANNELS:
        try:
            member = await context.bot.get_chat_member(channel, user_id)
            if member.status in ("left", "kicked"):
                not_joined.append(channel)
        except Exception:
            # اگه بات نتونه چک کنه (مثلا ادمین اون کانال نیست)، به‌جای بلاک کردن کاربر، رد می‌شیم
            logging.warning("نمی‌تونم عضویت کانال %s رو چک کنم", channel)
    return not_joined


def join_keyboard(not_joined):
    rows = []
    for channel in not_joined:
        handle = channel.lstrip("@")
        rows.append([InlineKeyboardButton(f"عضویت در {channel}", url=f"https://t.me/{handle}")])
    rows.append([InlineKeyboardButton("✅ عضو شدم", callback_data="checkjoin")])
    return InlineKeyboardMarkup(rows)


async def require_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اگه کاربر عضو کانال‌های اجباری نباشه، پیام عضویت رو می‌فرسته و True برمی‌گردونه."""
    tg_user = update.effective_user
    if is_admin(tg_user.id) or not REQUIRED_CHANNELS:
        return False

    not_joined = await get_not_joined_channels(context, tg_user.id)
    if not_joined:
        await update.effective_message.reply_text(
            "برای استفاده از بات، اول باید عضو کانال‌های زیر بشی:",
            reply_markup=join_keyboard(not_joined),
        )
        return True
    return False


# ---------- بخش کاربر عادی ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_user = update.effective_user

    if await require_join(update, context):
        # قبل از چک عضویت، پارامتر لینک (اگه بود) رو نگه می‌داریم تا بعد از عضویت گم نشه
        if context.args:
            context.user_data["pending_start_token"] = context.args[0]
        return

    await process_start(update.message.reply_text, context, tg_user, context.args[0] if context.args else None)


async def process_start(reply_func, context, tg_user, token):
    user = db.get_or_create_user(tg_user.id, tg_user.username, tg_user.first_name)

    if user["is_banned"]:
        await reply_func("متاسفانه دسترسی شما مسدود شده.")
        return

    if token:
        target = db.get_user_by_token(token)
        if not target:
            await reply_func("این لینک معتبر نیست.")
            return
        if target["id"] == tg_user.id:
            await reply_func("این لینک خودته! نمی‌تونی برای خودت پیام ناشناس بفرستی 😄")
            return
        if target["is_banned"]:
            await reply_func("این کاربر در دسترس نیست.")
            return

        context.user_data["compose_target"] = target["id"]
        context.user_data.pop("reply_to", None)
        context.user_data.pop("support_mode", None)
        await reply_func("پیامتو بنویس، کاملاً ناشناس براش ارسال می‌شه 🙊")
        return

    await reply_func(
        "سلام! 👋 با این بات می‌تونی لینک اختصاصی خودتو بسازی و پیام‌های ناشناس بگیری.\n\n"
        "از دکمه‌های پایین استفاده کن.",
        reply_markup=MAIN_MENU,
    )


async def show_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await require_join(update, context):
        return
    tg_user = update.effective_user
    user = db.get_or_create_user(tg_user.id, tg_user.username, tg_user.first_name)
    link = f"https://t.me/{BOT_USERNAME}?start={user['link_token']}"
    await update.message.reply_text(f"این لینک اختصاصی توئه، هرجا خواستی به اشتراک بذار:\n\n{link}")


async def show_blocked(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await require_join(update, context):
        return
    owner_id = update.effective_user.id
    blocked = db.list_blocked(owner_id)
    if not blocked:
        await update.message.reply_text("لیست مسدودی‌هات خالیه.")
        return

    for row in blocked:
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("✅ آزاد کردن", callback_data=f"unblock:{row['sender_id']}")]]
        )
        await update.message.reply_text(f"🚫 ناشناس #{row['anon_number']}", reply_markup=kb)


async def start_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await require_join(update, context):
        return
    context.user_data["support_mode"] = True
    context.user_data.pop("compose_target", None)
    context.user_data.pop("reply_to", None)
    await update.message.reply_text(
        "پیامتو برای پشتیبانی بنویس. (این پیام ناشناس نیست، پشتیبانی می‌تونه بهت جواب بده)"
    )


def extract_content(msg):
    if msg.text:
        return "text", msg.text, None
    if msg.photo:
        return "photo", msg.caption, msg.photo[-1].file_id
    if msg.video:
        return "video", msg.caption, msg.video.file_id
    if msg.voice:
        return "voice", msg.caption, msg.voice.file_id
    if msg.sticker:
        return "sticker", None, msg.sticker.file_id
    return "other", msg.caption, None


async def copy_content(context, chat_id, msg):
    await context.bot.copy_message(chat_id=chat_id, from_chat_id=msg.chat_id, message_id=msg.message_id)


async def relay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_user = update.effective_user

    if not is_admin(tg_user.id) and await require_join(update, context):
        return

    user = db.get_or_create_user(tg_user.id, tg_user.username, tg_user.first_name)

    if user["is_banned"]:
        await update.message.reply_text("دسترسی شما مسدود شده.")
        return

    msg = update.message
    content_type, text_content, file_id = extract_content(msg)

    # حالت پاسخ به یه پیام ناشناس خاص
    if context.user_data.get("reply_to"):
        sender_id = context.user_data.pop("reply_to")
        try:
            await context.bot.send_message(sender_id, "↩️ پاسخ به پیامت:")
            await copy_content(context, sender_id, msg)
            db.log_message(tg_user.id, sender_id, "to_sender", content_type, text_content, file_id)
            await update.message.reply_text("پاسخت ارسال شد ✅")
        except Exception:
            await update.message.reply_text("ارسال پاسخ ممکن نشد.")
        return

    # حالت پشتیبانی
    if context.user_data.get("support_mode"):
        context.user_data["support_mode"] = False
        db.create_ticket(tg_user.id, text_content or f"[{content_type}]")
        await update.message.reply_text("پیامت برای پشتیبانی ارسال شد. منتظر پاسخ باش 🙏")
        return

    # حالت پاسخ ادمین به یه تیکت پشتیبانی خاص
    if is_admin(tg_user.id) and context.user_data.get("admin_reply_ticket"):
        ticket_id = context.user_data.pop("admin_reply_ticket")
        ticket = db.get_ticket(ticket_id)
        if not ticket:
            await update.message.reply_text("این تیکت پیدا نشد.")
            return
        try:
            await context.bot.send_message(ticket["user_id"], f"🆘 پاسخ پشتیبانی:\n\n{text_content}")
            db.reply_ticket(ticket_id, text_content)
            db.mark_ticket_delivered(ticket_id)
            await update.message.reply_text("پاسخ برای کاربر ارسال شد ✅")
        except Exception:
            await update.message.reply_text("ارسال پاسخ ممکن نشد (شاید کاربر بات رو بلاک کرده).")
        return

    # حالت ارسال پیام ناشناس به یه نفر (بعد از باز کردن لینک اون شخص)
    target_id = context.user_data.pop("compose_target", None)
    if target_id:
        if db.is_blocked(target_id, tg_user.id):
            await update.message.reply_text("امکان ارسال پیام به این کاربر وجود نداره.")
            return
        anon_num = db.get_anon_number(target_id, tg_user.id)
        try:
            await context.bot.send_message(target_id, f"📩 پیام ناشناس #{anon_num}:")
            await copy_content(context, target_id, msg)
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ پاسخ", callback_data=f"reply:{tg_user.id}"),
                InlineKeyboardButton("🚫 مسدود کردن", callback_data=f"block:{tg_user.id}"),
            ], [
                InlineKeyboardButton("🚨 گزارش تخلف", callback_data=f"report:{tg_user.id}"),
            ]])
            await context.bot.send_message(target_id, "برای پاسخ، مسدود کردن یا گزارش:", reply_markup=kb)
            db.log_message(target_id, tg_user.id, "to_owner", content_type, text_content, file_id)
            await update.message.reply_text("پیامت ناشناس ارسال شد ✅")
        except Exception:
            await update.message.reply_text("این کاربر در دسترس نیست.")
        return

    await update.message.reply_text(
        "برای ارسال پیام ناشناس، از لینک یه نفر استفاده کن. برای گرفتن لینک خودت «🔗 لینک من» رو بزن.",
        reply_markup=MAIN_MENU,
    )


async def checkjoin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    tg_user = query.from_user

    not_joined = await get_not_joined_channels(context, tg_user.id)
    if not_joined:
        await query.answer("هنوز عضو همه‌ی کانال‌ها نشدی!", show_alert=True)
        return

    await query.answer("عضویت تایید شد ✅")
    await query.edit_message_text("عضویت تایید شد ✅")

    token = context.user_data.pop("pending_start_token", None)
    await process_start(
        lambda *a, **k: context.bot.send_message(tg_user.id, *a, **k),
        context,
        tg_user,
        token,
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    owner_id = query.from_user.id
    action, raw_id = query.data.split(":")
    other_id = int(raw_id)

    if action == "reply":
        context.user_data["reply_to"] = other_id
        context.user_data.pop("compose_target", None)
        context.user_data.pop("support_mode", None)
        await query.message.reply_text("پاسخت رو بنویس:")

    elif action == "block":
        db.block_user(owner_id, other_id)
        await query.edit_message_text("🚫 این کاربر مسدود شد.")

    elif action == "unblock":
        db.unblock_user(owner_id, other_id)
        await query.edit_message_text("✅ این کاربر آزاد شد.")

    elif action == "report":
        sender_id = other_id
        last_msg = db.get_last_message(owner_id, sender_id)
        content_type = last_msg["content_type"] if last_msg else "text"
        text_content = last_msg["text_content"] if last_msg else None
        file_id = last_msg["file_id"] if last_msg else None

        db.create_report(owner_id, sender_id, content_type, text_content, file_id)
        sender = db.get_user_by_id(sender_id) or {}
        body = text_content or f"[{content_type}]"

        report_text = (
            "🚨 گزارش تخلف جدید\n\n"
            f"فرستنده: {sender.get('first_name') or '-'} "
            f"(@{sender.get('username') or '-'}) — آیدی: {sender_id}\n"
            f"گزارش‌دهنده: {owner_id}\n\n"
            f"متن پیام:\n{body}"
        )
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(admin_id, report_text)
                if file_id:
                    if content_type == "photo":
                        await context.bot.send_photo(admin_id, file_id, caption="پیوست پیام گزارش‌شده")
                    elif content_type == "video":
                        await context.bot.send_video(admin_id, file_id, caption="پیوست پیام گزارش‌شده")
                    elif content_type == "voice":
                        await context.bot.send_voice(admin_id, file_id, caption="پیوست پیام گزارش‌شده")
                    elif content_type == "sticker":
                        await context.bot.send_sticker(admin_id, file_id)
            except Exception:
                logging.exception("خطا در ارسال گزارش به ادمین %s", admin_id)

        await query.edit_message_text("گزارشت برای بررسی ارسال شد. ممنون که خبر دادی 🙏")


# ---------- بخش ادمین ----------

def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_admin(update.effective_user.id):
            await update.message.reply_text("دسترسی نداری.")
            return
        return await func(update, context)

    return wrapper


@admin_only
async def admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "پنل ادمین 🛠\n\n"
        "/stats — آمار کلی\n"
        "/users [صفحه] — لیست کاربرها\n"
        "/search <آیدی یا یوزرنیم>\n"
        "/ban <آیدی>\n"
        "/unban <آیدی>\n"
        "/tickets — تیکت‌های در انتظار\n"
        "/reply <شماره تیکت> <متن> — پاسخ سریع\n"
        "/reports — گزارش‌های تخلف در انتظار\n"
        "/resolvereport <شماره گزارش> — بستن گزارش\n"
        "/history <آیدی کاربر> — تاریخچه پیام‌ها"
    )


@admin_only
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = db.get_stats()
    await update.message.reply_text(
        f"👥 کاربرها: {s['users']}\n"
        f"✉️ پیام‌ها: {s['messages']}\n"
        f"🚫 مسدودی‌ها: {s['blocks']}\n"
        f"🆘 تیکت‌های در انتظار: {s['pending_tickets']}\n"
        f"🚨 گزارش‌های در انتظار: {s['pending_reports']}"
    )


@admin_only
async def users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    page = int(context.args[0]) if context.args else 0
    rows = db.list_users(offset=page * 10, limit=10)
    if not rows:
        await update.message.reply_text("موردی نیست.")
        return
    lines = [
        f"{'🔴' if r['is_banned'] else '🟢'} {r['id']} — {r.get('first_name') or '-'} — @{r['username'] or '-'}"
        for r in rows
    ]
    await update.message.reply_text("\n".join(lines))


@admin_only
async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("استفاده: /search <آیدی یا یوزرنیم>")
        return
    rows = db.search_user(context.args[0])
    if not rows:
        await update.message.reply_text("پیدا نشد.")
        return
    lines = [
        f"{'🔴' if r['is_banned'] else '🟢'} {r['id']} — {r.get('first_name') or '-'} — "
        f"@{r['username'] or '-'} — {r['created_at']}"
        for r in rows
    ]
    await update.message.reply_text("\n".join(lines))


@admin_only
async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("استفاده: /ban <آیدی>")
        return
    db.ban_user(int(context.args[0]))
    await update.message.reply_text("مسدود شد.")


@admin_only
async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("استفاده: /unban <آیدی>")
        return
    db.unban_user(int(context.args[0]))
    await update.message.reply_text("رفع مسدودیت شد.")


@admin_only
async def tickets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db.get_pending_tickets()
    if not rows:
        await update.message.reply_text("تیکت در انتظاری نیست.")
        return
    for t in rows:
        sender = db.get_user_by_id(t["user_id"])
        name = sender.get("first_name") if sender else None
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("↩️ پاسخ به این تیکت", callback_data=f"tkreply:{t['id']}")]]
        )
        await update.message.reply_text(
            f"🆘 تیکت #{t['id']} از {name or '-'} ({t['user_id']}):\n{t['message']}",
            reply_markup=kb,
        )


@admin_only
async def reply_ticket_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("استفاده: /reply <شماره تیکت> <متن>")
        return
    ticket_id = int(context.args[0])
    text = " ".join(context.args[1:])
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        await update.message.reply_text("این تیکت پیدا نشد.")
        return
    try:
        await context.bot.send_message(ticket["user_id"], f"🆘 پاسخ پشتیبانی:\n\n{text}")
        db.reply_ticket(ticket_id, text)
        db.mark_ticket_delivered(ticket_id)
        await update.message.reply_text("پاسخ ارسال شد ✅")
    except Exception:
        await update.message.reply_text("ارسال پاسخ ممکن نشد (شاید کاربر بات رو بلاک کرده).")


@admin_only
async def reports_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db.get_pending_reports()
    if not rows:
        await update.message.reply_text("گزارش در انتظاری نیست.")
        return
    for r in rows:
        sender = db.get_user_by_id(r["sender_id"]) or {}
        body = r["message_text"] or f"[{r['content_type']}]"
        await update.message.reply_text(
            f"🚨 گزارش #{r['id']}\n"
            f"فرستنده: {sender.get('first_name') or '-'} (@{sender.get('username') or '-'}) — {r['sender_id']}\n"
            f"گزارش‌دهنده: {r['owner_id']}\n"
            f"زمان: {r['created_at']}\n\n"
            f"متن: {body}\n\n"
            f"برای بستن: /resolvereport {r['id']}\n"
            f"برای مسدود کردن فرستنده: /ban {r['sender_id']}"
        )


@admin_only
async def resolve_report_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("استفاده: /resolvereport <شماره گزارش>")
        return
    db.resolve_report(int(context.args[0]))
    await update.message.reply_text("گزارش بسته شد.")


@admin_only
async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("استفاده: /history <آیدی کاربر>")
        return
    user_id = int(context.args[0])
    rows = db.get_user_messages(user_id)
    if not rows:
        await update.message.reply_text("پیامی ثبت نشده.")
        return
    lines = [
        f"[{r['created_at']}] owner={r['owner_id']} sender={r['sender_id']} "
        f"({r['direction']}, {r['content_type']}): {r['text_content'] or ''}"
        for r in rows
    ]
    await update.message.reply_text("\n".join(lines)[:4000])


async def admin_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    action, raw_id = query.data.split(":")
    if action == "tkreply":
        context.user_data["admin_reply_ticket"] = int(raw_id)
        context.user_data.pop("reply_to", None)
        context.user_data.pop("compose_target", None)
        context.user_data.pop("support_mode", None)
        await query.message.reply_text("متن پاسخ رو بنویس:")


def main():
    if not TOKEN or not BOT_USERNAME:
        raise RuntimeError("متغیرهای BOT_TOKEN و BOT_USERNAME باید تنظیم شده باشن.")

    db.init_db()

    app = ApplicationBuilder().token(TOKEN).build()

    # کاربر عادی
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex("^🔗 لینک من$"), show_link))
    app.add_handler(MessageHandler(filters.Regex("^🚫 لیست مسدودی‌ها$"), show_blocked))
    app.add_handler(MessageHandler(filters.Regex("^🆘 پشتیبانی$"), start_support))

    # ادمین
    app.add_handler(CommandHandler("admin", admin_help))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("users", users_list))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("unban", unban))
    app.add_handler(CommandHandler("tickets", tickets))
    app.add_handler(CommandHandler("reply", reply_ticket_cmd))
    app.add_handler(CommandHandler("reports", reports_cmd))
    app.add_handler(CommandHandler("resolvereport", resolve_report_cmd))
    app.add_handler(CommandHandler("history", history))

    app.add_handler(CallbackQueryHandler(checkjoin_handler, pattern="^checkjoin$"))
    app.add_handler(CallbackQueryHandler(admin_button_handler, pattern="^tkreply:"))
    app.add_handler(CallbackQueryHandler(button_handler))

    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, relay))

    app.run_polling()


if __name__ == "__main__":
    main()
