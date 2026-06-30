"""
Telegram Temporary Email Bot
Owner: @ax | Developer: @axSaaFe
"""

import asyncio
import logging
import os
import random
import string
import time
from datetime import datetime, timezone
from typing import Optional

import aiohttp
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("TempMailBot")

# ─── Config ───────────────────────────────────────────────────────────────────
BOT_TOKEN: str = os.environ["BOT_TOKEN"]
ADMIN_ID: int = int(os.environ["ADMIN_ID"])
MAIL_TM_BASE = "https://api.mail.tm"
INBOX_POLL_INTERVAL = 20  # seconds
BOT_START_TIME = time.time()

# ─── In-Memory Storage ────────────────────────────────────────────────────────
# user_id -> dict
user_data: dict[int, dict] = {}
# user_id -> set of seen message IDs
seen_messages: dict[int, set] = {}

# ─── Translations ─────────────────────────────────────────────────────────────
T = {
    "en": {
        "welcome": (
            "👋 *Welcome to Temp Mail Bot!*\n\n"
            "Get instant disposable email addresses right here in Telegram.\n\n"
            "Use the menu below to get started."
        ),
        "get_mail": "📧 *Your Temporary Email*\n\n`{email}`\n\n_Tap to copy your email address._",
        "already_have": "📧 *Your Temporary Email*\n\n`{email}`\n\n_This is your active email address._",
        "generating": "⏳ Generating your temporary email...",
        "generate_fail": "❌ Failed to generate email. Please try again.",
        "inbox_empty": "📭 *Inbox Empty*\n\nNo messages received yet.\nWaiting for emails...",
        "inbox_header": "📮 *Inbox* — {email}\n\n",
        "inbox_msg": "📩 *#{num}*\n👤 From: `{sender}`\n📌 Subject: {subject}\n🕐 {date}\n",
        "open_prompt": "Tap a message number to read it.",
        "msg_detail": (
            "📨 *Message Details*\n\n"
            "👤 *From:* `{sender}`\n"
            "📬 *To:* `{to}`\n"
            "📌 *Subject:* {subject}\n"
            "🕐 *Date:* {date}\n\n"
            "─────────────────\n"
            "{body}"
        ),
        "new_email_notify": (
            "🔔 *New Email Received!*\n\n"
            "👤 *From:* `{sender}`\n"
            "📌 *Subject:* {subject}\n\n"
            "_Open Inbox to read the full message._"
        ),
        "developer": "👥 *Developer*\n\nUsername: @axSaaFe",
        "language_prompt": "🌐 *Select Language*\n\nChoose your preferred language:",
        "language_set": "✅ Language set to *English*.",
        "profile": (
            "👤 *Your Profile*\n\n"
            "🆔 User ID: `{uid}`\n"
            "👤 Username: {uname}\n"
            "🌐 Language: {lang}\n"
            "📧 Email: {email}"
        ),
        "no_email": "_None — press 📧 Get Mail_",
        "stats": (
            "📊 *Bot Statistics*\n\n"
            "👥 Total Users: *{total_users}*\n"
            "📧 Active Emails: *{active_emails}*\n"
            "📨 Total Generated: *{total_gen}*\n"
            "⏱ Uptime: *{uptime}*"
        ),
        "admin_only": "⛔ This command is for admins only.",
        "refreshed": "🔄 Inbox refreshed.",
        "back_to_menu": "🏠 Main Menu",
        "not_found": "❌ Message not found.",
        "no_active_email": "⚠️ You don't have an active email yet.\nPress 📧 Get Mail to generate one.",
    },
    "bn": {
        "welcome": (
            "👋 *টেম্প মেইল বটে স্বাগতম!*\n\n"
            "এখানে সরাসরি Telegram-এ ডিসপোজেবল ইমেইল পান।\n\n"
            "শুরু করতে নিচের মেনু ব্যবহার করুন।"
        ),
        "get_mail": "📧 *আপনার অস্থায়ী ইমেইল*\n\n`{email}`\n\n_কপি করতে ট্যাপ করুন।_",
        "already_have": "📧 *আপনার অস্থায়ী ইমেইল*\n\n`{email}`\n\n_এটি আপনার সক্রিয় ইমেইল ঠিকানা।_",
        "generating": "⏳ অস্থায়ী ইমেইল তৈরি হচ্ছে...",
        "generate_fail": "❌ ইমেইল তৈরি করতে ব্যর্থ। আবার চেষ্টা করুন।",
        "inbox_empty": "📭 *ইনবক্স খালি*\n\nএখনো কোনো বার্তা আসেনি।\nইমেইলের অপেক্ষায়...",
        "inbox_header": "📮 *ইনবক্স* — {email}\n\n",
        "inbox_msg": "📩 *#{num}*\n👤 প্রেরক: `{sender}`\n📌 বিষয়: {subject}\n🕐 {date}\n",
        "open_prompt": "পড়তে বার্তা নম্বরে ট্যাপ করুন।",
        "msg_detail": (
            "📨 *বার্তার বিবরণ*\n\n"
            "👤 *প্রেরক:* `{sender}`\n"
            "📬 *প্রাপক:* `{to}`\n"
            "📌 *বিষয়:* {subject}\n"
            "🕐 *তারিখ:* {date}\n\n"
            "─────────────────\n"
            "{body}"
        ),
        "new_email_notify": (
            "🔔 *নতুন ইমেইল এসেছে!*\n\n"
            "👤 *প্রেরক:* `{sender}`\n"
            "📌 *বিষয়:* {subject}\n\n"
            "_সম্পূর্ণ বার্তা পড়তে ইনবক্স খুলুন।_"
        ),
        "developer": "👥 *ডেভেলপার*\n\nইউজারনেম: @axSaaFe",
        "language_prompt": "🌐 *ভাষা নির্বাচন করুন*\n\nআপনার পছন্দের ভাষা বেছে নিন:",
        "language_set": "✅ ভাষা *বাংলা* সেট হয়েছে।",
        "profile": (
            "👤 *আপনার প্রোফাইল*\n\n"
            "🆔 ইউজার আইডি: `{uid}`\n"
            "👤 ইউজারনেম: {uname}\n"
            "🌐 ভাষা: {lang}\n"
            "📧 ইমেইল: {email}"
        ),
        "no_email": "_নেই — 📧 Get Mail চাপুন_",
        "stats": (
            "📊 *বট পরিসংখ্যান*\n\n"
            "👥 মোট ব্যবহারকারী: *{total_users}*\n"
            "📧 সক্রিয় ইমেইল: *{active_emails}*\n"
            "📨 মোট তৈরি: *{total_gen}*\n"
            "⏱ আপটাইম: *{uptime}*"
        ),
        "admin_only": "⛔ এই কমান্ড শুধু অ্যাডমিনের জন্য।",
        "refreshed": "🔄 ইনবক্স রিফ্রেশ হয়েছে।",
        "back_to_menu": "🏠 মূল মেনু",
        "not_found": "❌ বার্তা পাওয়া যায়নি।",
        "no_active_email": "⚠️ আপনার এখনো কোনো সক্রিয় ইমেইল নেই।\n📧 Get Mail চাপুন।",
    },
}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def t(uid: int, key: str, **kwargs) -> str:
    lang = user_data.get(uid, {}).get("lang", "en")
    tmpl = T.get(lang, T["en"]).get(key, T["en"].get(key, key))
    return tmpl.format(**kwargs) if kwargs else tmpl


def get_user(uid: int) -> dict:
    if uid not in user_data:
        user_data[uid] = {
            "lang": "en",
            "email": None,
            "password": None,
            "token": None,
            "account_id": None,
            "total_generated": 0,
            "joined": datetime.now(timezone.utc).isoformat(),
            "name": "",
            "username": "",
        }
    return user_data[uid]


def fmt_uptime(seconds: float) -> str:
    seconds = int(seconds)
    days, r = divmod(seconds, 86400)
    hours, r = divmod(r, 3600)
    mins, secs = divmod(r, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if mins:
        parts.append(f"{mins}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


def generate_password(length: int = 16) -> str:
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(random.choices(chars, k=length))


def fmt_date(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return iso


def escape_md(text: str) -> str:
    """Escape special chars for MarkdownV2 — we use Markdown (v1) so minimal escaping."""
    return text


def truncate(text: str, max_len: int = 200) -> str:
    return text[:max_len] + "…" if len(text) > max_len else text


# ─── Keyboards ────────────────────────────────────────────────────────────────

def main_keyboard(uid: int) -> ReplyKeyboardMarkup:
    lang = user_data.get(uid, {}).get("lang", "en")
    if lang == "bn":
        rows = [
            [KeyboardButton("📧 Get Mail"), KeyboardButton("📮 Inbox")],
            [KeyboardButton("👥 Developer")],
            [KeyboardButton("🌐 Language"), KeyboardButton("👤 Profile")],
        ]
    else:
        rows = [
            [KeyboardButton("📧 Get Mail"), KeyboardButton("📮 Inbox")],
            [KeyboardButton("👥 Developer")],
            [KeyboardButton("🌐 Language"), KeyboardButton("👤 Profile")],
        ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True)


def back_keyboard(uid: int) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton("🔙 Back")]],
        resize_keyboard=True,
        is_persistent=True,
    )


def language_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🇧🇩 Bangla"), KeyboardButton("🇺🇸 English")],
            [KeyboardButton("🔙 Back")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def inbox_inline(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Refresh", callback_data="inbox_refresh")]])


def get_mail_inline(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("📮 Inbox", callback_data="open_inbox")]])


# ─── mail.tm API ──────────────────────────────────────────────────────────────

async def mailtm_get_domains(session: aiohttp.ClientSession) -> list[str]:
    async with session.get(f"{MAIL_TM_BASE}/domains") as r:
        if r.status == 200:
            data = await r.json()
            return [d["domain"] for d in data.get("hydra:member", [])]
    return []


async def mailtm_create_account(
    session: aiohttp.ClientSession, email: str, password: str
) -> Optional[dict]:
    payload = {"address": email, "password": password}
    async with session.post(f"{MAIL_TM_BASE}/accounts", json=payload) as r:
        if r.status == 201:
            return await r.json()
    return None


async def mailtm_get_token(
    session: aiohttp.ClientSession, email: str, password: str
) -> Optional[str]:
    payload = {"address": email, "password": password}
    async with session.post(f"{MAIL_TM_BASE}/token", json=payload) as r:
        if r.status == 200:
            data = await r.json()
            return data.get("token")
    return None


async def mailtm_get_messages(
    session: aiohttp.ClientSession, token: str
) -> list[dict]:
    headers = {"Authorization": f"Bearer {token}"}
    async with session.get(f"{MAIL_TM_BASE}/messages", headers=headers) as r:
        if r.status == 200:
            data = await r.json()
            return data.get("hydra:member", [])
    return []


async def mailtm_get_message(
    session: aiohttp.ClientSession, token: str, msg_id: str
) -> Optional[dict]:
    headers = {"Authorization": f"Bearer {token}"}
    async with session.get(f"{MAIL_TM_BASE}/messages/{msg_id}", headers=headers) as r:
        if r.status == 200:
            return await r.json()
    return None


async def create_temp_email(uid: int, session: aiohttp.ClientSession) -> Optional[str]:
    user = get_user(uid)
    domains = await mailtm_get_domains(session)
    if not domains:
        return None

    domain = domains[0]
    local = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
    email = f"{local}@{domain}"
    password = generate_password()

    account = await mailtm_create_account(session, email, password)
    if not account:
        return None

    token = await mailtm_get_token(session, email, password)
    if not token:
        return None

    user["email"] = email
    user["password"] = password
    user["token"] = token
    user["account_id"] = account.get("id")
    user["total_generated"] = user.get("total_generated", 0) + 1
    seen_messages[uid] = set()

    logger.info(f"[Email] Created {email} for uid={uid}")
    return email


# ─── Inbox Rendering ──────────────────────────────────────────────────────────

async def render_inbox(uid: int, session: aiohttp.ClientSession) -> tuple[str, InlineKeyboardMarkup]:
    user = get_user(uid)
    token = user.get("token")
    email = user.get("email")

    if not token or not email:
        return t(uid, "no_active_email"), InlineKeyboardMarkup([])

    messages = await mailtm_get_messages(session, token)

    if not messages:
        return t(uid, "inbox_empty"), inbox_inline(uid)

    text = t(uid, "inbox_header", email=email)
    buttons = []
    for i, msg in enumerate(messages[:10], 1):
        sender = msg.get("from", {}).get("address", "unknown")
        subject = truncate(msg.get("subject", "(No Subject)"), 50)
        date = fmt_date(msg.get("createdAt", ""))
        text += t(uid, "inbox_msg", num=i, sender=sender, subject=subject, date=date)
        text += "\n"
        buttons.append([InlineKeyboardButton(f"📩 Open #{i}", callback_data=f"read_{msg['id']}")])

    buttons.append([InlineKeyboardButton("↩️ Refresh", callback_data="inbox_refresh")])
    return text, InlineKeyboardMarkup(buttons)


# ─── Handlers ─────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    user = get_user(uid)
    is_new = not user.get("name")

    tguser = update.effective_user
    user["name"] = tguser.full_name or ""
    user["username"] = f"@{tguser.username}" if tguser.username else "N/A"

    await update.message.reply_text(
        t(uid, "welcome"),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_keyboard(uid),
    )

    if is_new:
        lang_name = "English" if user.get("lang", "en") == "en" else "বাংলা"
        notif = (
            f"👤 *New User Alert!*\n\n"
            f"📛 Name: {user['name']}\n"
            f"👤 Username: {user['username']}\n"
            f"🆔 User ID: <code>{uid}</code>\n"
            f"🌐 Language: {lang_name}\n"
            f"🕐 Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )
        try:
            await ctx.bot.send_message(
                ADMIN_ID,
                notif,
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logger.warning(f"Could not notify admin: {e}")


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    if uid != ADMIN_ID:
        await update.message.reply_text(t(uid, "admin_only"))
        return

    total_users = len(user_data)
    active_emails = sum(1 for u in user_data.values() if u.get("email"))
    total_gen = sum(u.get("total_generated", 0) for u in user_data.values())
    uptime = fmt_uptime(time.time() - BOT_START_TIME)

    await update.message.reply_text(
        t(uid, "stats", total_users=total_users, active_emails=active_emails,
          total_gen=total_gen, uptime=uptime),
        parse_mode=ParseMode.MARKDOWN,
    )


async def handle_get_mail(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    user = get_user(uid)

    if user.get("email") and user.get("token"):
        await update.message.reply_text(
            t(uid, "already_have", email=user["email"]),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_mail_inline(uid),
        )
        return

    msg = await update.message.reply_text(t(uid, "generating"))

    async with aiohttp.ClientSession() as session:
        email = await create_temp_email(uid, session)

    if not email:
        await msg.edit_text(t(uid, "generate_fail"))
        return

    await msg.edit_text(
        t(uid, "get_mail", email=email),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_mail_inline(uid),
    )


async def handle_inbox(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    user = get_user(uid)

    if not user.get("email"):
        await update.message.reply_text(t(uid, "no_active_email"), parse_mode=ParseMode.MARKDOWN)
        return

    async with aiohttp.ClientSession() as session:
        text, markup = await render_inbox(uid, session)

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=markup,
    )


async def handle_developer(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    await update.message.reply_text(
        t(uid, "developer"),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=back_keyboard(uid),
    )


async def handle_language(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    await update.message.reply_text(
        t(uid, "language_prompt"),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=language_keyboard(),
    )


async def handle_set_english(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    get_user(uid)["lang"] = "en"
    await update.message.reply_text(
        t(uid, "language_set"),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_keyboard(uid),
    )


async def handle_set_bangla(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    get_user(uid)["lang"] = "bn"
    await update.message.reply_text(
        t(uid, "language_set"),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_keyboard(uid),
    )


async def handle_profile(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    user = get_user(uid)
    tguser = update.effective_user
    uname = f"@{tguser.username}" if tguser.username else "N/A"
    lang_name = "English 🇺🇸" if user.get("lang", "en") == "en" else "বাংলা 🇧🇩"
    email_display = f"`{user['email']}`" if user.get("email") else t(uid, "no_email")

    await update.message.reply_text(
        t(uid, "profile", uid=uid, uname=uname, lang=lang_name, email=email_display),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=back_keyboard(uid),
    )


async def handle_back(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    await update.message.reply_text(
        t(uid, "back_to_menu"),
        reply_markup=main_keyboard(uid),
    )


# ─── Callback Queries ─────────────────────────────────────────────────────────

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    data = query.data

    if data in ("open_inbox", "inbox_refresh"):
        user = get_user(uid)
        if not user.get("email"):
            await query.edit_message_text(t(uid, "no_active_email"), parse_mode=ParseMode.MARKDOWN)
            return

        async with aiohttp.ClientSession() as session:
            text, markup = await render_inbox(uid, session)

        try:
            await query.edit_message_text(
                text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=markup,
            )
        except Exception:
            pass

    elif data.startswith("read_"):
        msg_id = data[5:]
        user = get_user(uid)
        token = user.get("token")
        if not token:
            await query.edit_message_text(t(uid, "no_active_email"), parse_mode=ParseMode.MARKDOWN)
            return

        async with aiohttp.ClientSession() as session:
            msg = await mailtm_get_message(session, token, msg_id)

        if not msg:
            await query.edit_message_text(t(uid, "not_found"), parse_mode=ParseMode.MARKDOWN)
            return

        sender = msg.get("from", {}).get("address", "unknown")
        to_addr = ", ".join(a.get("address", "") for a in msg.get("to", []))
        subject = msg.get("subject", "(No Subject)")
        date = fmt_date(msg.get("createdAt", ""))
        body = msg.get("text") or msg.get("html") or "(Empty)"
        # Strip HTML tags simply
        import re
        body = re.sub(r"<[^>]+>", "", body)
        body = truncate(body, 3000)

        detail = t(uid, "msg_detail", sender=sender, to=to_addr, subject=subject, date=date, body=body)

        back_btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back to Inbox", callback_data="inbox_refresh")]
        ])
        try:
            await query.edit_message_text(
                detail,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=back_btn,
            )
        except Exception:
            await ctx.bot.send_message(uid, detail, parse_mode=ParseMode.MARKDOWN, reply_markup=back_btn)


# ─── Background Inbox Poller ──────────────────────────────────────────────────

async def inbox_poller(app: Application) -> None:
    """Poll every active user's inbox and notify on new messages."""
    logger.info("Inbox poller started.")
    while True:
        await asyncio.sleep(INBOX_POLL_INTERVAL)
        active_users = [(uid, u) for uid, u in user_data.items() if u.get("token") and u.get("email")]
        if not active_users:
            continue

        async with aiohttp.ClientSession() as session:
            for uid, user in active_users:
                try:
                    messages = await mailtm_get_messages(session, user["token"])
                    if not messages:
                        continue

                    if uid not in seen_messages:
                        seen_messages[uid] = set()

                    for msg in messages:
                        mid = msg.get("id")
                        if mid and mid not in seen_messages[uid]:
                            seen_messages[uid].add(mid)
                            sender = msg.get("from", {}).get("address", "unknown")
                            subject = truncate(msg.get("subject", "(No Subject)"), 80)
                            notif = t(uid, "new_email_notify", sender=sender, subject=subject)
                            try:
                                await app.bot.send_message(
                                    uid,
                                    notif,
                                    parse_mode=ParseMode.MARKDOWN,
                                    reply_markup=inbox_inline(uid),
                                )
                                logger.info(f"[Notify] New email for uid={uid} from {sender}")
                            except Exception as e:
                                logger.warning(f"[Notify] Failed to notify uid={uid}: {e}")
                except Exception as e:
                    logger.warning(f"[Poller] Error for uid={uid}: {e}")


# ─── App Setup ────────────────────────────────────────────────────────────────

def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set.")

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("stats", cmd_stats))

    # Reply keyboard buttons
    app.add_handler(MessageHandler(filters.Regex(r"^📧 Get Mail$"), handle_get_mail))
    app.add_handler(MessageHandler(filters.Regex(r"^📮 Inbox$"), handle_inbox))
    app.add_handler(MessageHandler(filters.Regex(r"^👥 Developer$"), handle_developer))
    app.add_handler(MessageHandler(filters.Regex(r"^🌐 Language$"), handle_language))
    app.add_handler(MessageHandler(filters.Regex(r"^👤 Profile$"), handle_profile))
    app.add_handler(MessageHandler(filters.Regex(r"^🇺🇸 English$"), handle_set_english))
    app.add_handler(MessageHandler(filters.Regex(r"^🇧🇩 Bangla$"), handle_set_bangla))
    app.add_handler(MessageHandler(filters.Regex(r"^🔙 Back$"), handle_back))

    # Inline callbacks
    app.add_handler(CallbackQueryHandler(handle_callback))

    async def post_init(application: Application) -> None:
        asyncio.create_task(inbox_poller(application))
        logger.info("Bot started successfully.")

    app.post_init = post_init

    logger.info("Starting bot in polling mode...")
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )


if __name__ == "__main__":
    main()
