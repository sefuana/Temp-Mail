"""
Telegram Temporary Email Bot
Owner: @ax | Developer: @axSaaFe
"""

import asyncio
import logging
import os
import random
import re
import string
import time
from abc import ABC, abstractmethod
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
INBOX_POLL_INTERVAL: int = 20  # seconds
BOT_START_TIME: float = time.time()

# ─── In-Memory Storage ────────────────────────────────────────────────────────
user_data: dict[int, dict] = {}
seen_messages: dict[int, set] = {}


# ─── Mail Provider Abstraction ────────────────────────────────────────────────
#
# To switch providers in the future:
#   1. Create a new class that inherits MailProvider
#   2. Implement all abstract methods
#   3. Change ACTIVE_PROVIDER at the bottom of this section
#
# Domain reputation ranking:
#   Domains are scored 1–10. Higher = better deliverability on major platforms.
#   The provider's get_best_domain() method uses this to pick automatically.
#
# Known domain reputation tiers (as of mid-2026):
#   Tier A (score 8-10): Relatively new/unblocked — best for Instagram, Discord, etc.
#   Tier B (score 5-7):  Often works but occasionally blocked by stricter platforms.
#   Tier C (score 1-4):  Frequently blocklisted on major social platforms.

DOMAIN_REPUTATION: dict[str, int] = {
    # Tier A — prefer these
    "rfcdrive.com": 9,
    "gustr.com": 9,
    "txcct.com": 8,
    "harakirimail.com": 8,
    "spamgourmet.com": 8,
    # Tier B — acceptable fallback
    "mail.tm": 6,
    "bugfoo.com": 6,
    "dcctb.com": 5,
    # Tier C — avoid if possible
    "guerrillamail.com": 3,
    "guerrillamailblock.com": 2,
    "mailnull.com": 4,
}

def score_domain(domain: str) -> int:
    """Return reputation score for a domain. Unknown domains get a neutral score of 5."""
    return DOMAIN_REPUTATION.get(domain.lower(), 5)


class MailProvider(ABC):
    """Abstract base class for temporary email providers."""

    @abstractmethod
    async def get_domains(self, session: aiohttp.ClientSession) -> list[str]:
        """Return all available domains from the provider."""

    @abstractmethod
    async def create_account(
        self, session: aiohttp.ClientSession, email: str, password: str
    ) -> Optional[dict]:
        """Create a new email account. Return account info dict or None on failure."""

    @abstractmethod
    async def get_token(
        self, session: aiohttp.ClientSession, email: str, password: str
    ) -> Optional[str]:
        """Authenticate and return a session token, or None on failure."""

    @abstractmethod
    async def get_messages(
        self, session: aiohttp.ClientSession, token: str
    ) -> list[dict]:
        """Return list of message summary dicts for the authenticated account."""

    @abstractmethod
    async def get_message(
        self, session: aiohttp.ClientSession, token: str, msg_id: str
    ) -> Optional[dict]:
        """Return full message detail dict, or None if not found."""

    async def get_best_domain(self, session: aiohttp.ClientSession) -> Optional[str]:
        """
        Fetch available domains and return the one with the highest reputation score.
        Falls back to the first available domain if none are scored.
        """
        domains = await self.get_domains(session)
        if not domains:
            return None
        ranked = sorted(domains, key=score_domain, reverse=True)
        best = ranked[0]
        logger.info(f"[Provider] Best domain selected: {best} (score={score_domain(best)})")
        return best


# ─── mail.tm Provider ─────────────────────────────────────────────────────────
#
# mail.tm is the default provider. It offers a free REST API, multiple domains,
# and reasonable deliverability. API docs: [docs.mail.tm](https://docs.mail.tm)
#
# To switch to a different provider later, implement a new MailProvider subclass
# and update ACTIVE_PROVIDER below. No other code changes needed.

class MailTmProvider(MailProvider):
    BASE_URL = "[api.mail.tm](https://api.mail.tm)"

    async def get_domains(self, session: aiohttp.ClientSession) -> list[str]:
        try:
            async with session.get(
                f"{self.BASE_URL}/domains", timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    return [d["domain"] for d in data.get("hydra:member", [])]
        except Exception as e:
            logger.warning(f"[MailTm] get_domains error: {e}")
        return []

    async def create_account(
        self, session: aiohttp.ClientSession, email: str, password: str
    ) -> Optional[dict]:
        try:
            async with session.post(
                f"{self.BASE_URL}/accounts",
                json={"address": email, "password": password},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                if r.status == 201:
                    return await r.json()
                body = await r.text()
                logger.warning(f"[MailTm] create_account failed {r.status}: {body[:200]}")
        except Exception as e:
            logger.warning(f"[MailTm] create_account error: {e}")
        return None

    async def get_token(
        self, session: aiohttp.ClientSession, email: str, password: str
    ) -> Optional[str]:
        try:
            async with session.post(
                f"{self.BASE_URL}/token",
                json={"address": email, "password": password},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    return data.get("token")
                body = await r.text()
                logger.warning(f"[MailTm] get_token failed {r.status}: {body[:200]}")
        except Exception as e:
            logger.warning(f"[MailTm] get_token error: {e}")
        return None

    async def get_messages(
        self, session: aiohttp.ClientSession, token: str
    ) -> list[dict]:
        try:
            async with session.get(
                f"{self.BASE_URL}/messages",
                headers={"Authorization": f"Bearer {token}"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    return data.get("hydra:member", [])
        except Exception as e:
            logger.warning(f"[MailTm] get_messages error: {e}")
        return []

    async def get_message(
        self, session: aiohttp.ClientSession, token: str, msg_id: str
    ) -> Optional[dict]:
        try:
            async with session.get(
                f"{self.BASE_URL}/messages/{msg_id}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status == 200:
                    return await r.json()
        except Exception as e:
            logger.warning(f"[MailTm] get_message error: {e}")
        return None


# ─── Active Provider ──────────────────────────────────────────────────────────
# Change this line to switch providers. Everything else adapts automatically.
ACTIVE_PROVIDER: MailProvider = MailTmProvider()


# ─── Translations ─────────────────────────────────────────────────────────────
T: dict[str, dict[str, str]] = {
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
        "language_set_bn": "✅ ভাষা *বাংলা* সেট হয়েছে।",
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
        "no_active_email": (
            "⚠️ You don't have an active email yet.\n"
            "Press 📧 Get Mail to generate one."
        ),
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
        "language_set": "✅ Language set to *English*.",
        "language_set_bn": "✅ ভাষা *বাংলা* সেট হয়েছে।",
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
    tmpl = T.get(lang, T["en"]).get(key) or T["en"].get(key, key)
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


def truncate(text: str, max_len: int = 200) -> str:
    return text[:max_len] + "…" if len(text) > max_len else text


def strip_html(text: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s{3,}", "\n\n", text)
    return text.strip()


# ─── Email Creation ───────────────────────────────────────────────────────────

async def create_temp_email(uid: int, session: aiohttp.ClientSession) -> Optional[str]:
    """
    Create a new temporary email for a user using the active provider.
    Automatically picks the domain with the highest reputation score.
    """
    user = get_user(uid)

    domain = await ACTIVE_PROVIDER.get_best_domain(session)
    if not domain:
        logger.error("[Email] No domains available from provider.")
        return None

    local = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
    email = f"{local}@{domain}"
    password = generate_password()

    account = await ACTIVE_PROVIDER.create_account(session, email, password)
    if not account:
        return None

    token = await ACTIVE_PROVIDER.get_token(session, email, password)
    if not token:
        return None

    user["email"] = email
    user["password"] = password
    user["token"] = token
    user["account_id"] = account.get("id")
    user["total_generated"] = user.get("total_generated", 0) + 1
    seen_messages[uid] = set()

    logger.info(f"[Email] Created {email} for uid={uid} (domain score={score_domain(domain)})")
    return email


# ─── Keyboards ────────────────────────────────────────────────────────────────

def main_keyboard(uid: int) -> ReplyKeyboardMarkup:
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
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("↩️ Refresh", callback_data="inbox_refresh")]]
    )


def get_mail_inline(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("📮 Open Inbox", callback_data="open_inbox")]]
    )


# ─── Inbox Rendering ──────────────────────────────────────────────────────────

async def render_inbox(
    uid: int, session: aiohttp.ClientSession
) -> tuple[str, InlineKeyboardMarkup]:
    user = get_user(uid)
    token = user.get("token")
    email = user.get("email")

    if not token or not email:
        return t(uid, "no_active_email"), InlineKeyboardMarkup([])

    messages = await ACTIVE_PROVIDER.get_messages(session, token)

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
        buttons.append(
            [InlineKeyboardButton(f"📩 Open #{i}", callback_data=f"read_{msg['id']}")]
        )

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
            f"👤 <b>New User Alert!</b>\n\n"
            f"📛 Name: {user['name']}\n"
            f"👤 Username: {user['username']}\n"
            f"🆔 User ID: <code>{uid}</code>\n"
            f"🌐 Language: {lang_name}\n"
            f"🕐 Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )
        try:
            await ctx.bot.send_message(ADMIN_ID, notif, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.warning(f"[Admin] Could not notify admin: {e}")


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
        t(uid, "stats",
          total_users=total_users,
          active_emails=active_emails,
          total_gen=total_gen,
          uptime=uptime),
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
        await update.message.reply_text(
            t(uid, "no_active_email"), parse_mode=ParseMode.MARKDOWN
        )
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
        T["en"]["language_set"],
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_keyboard(uid),
    )


async def handle_set_bangla(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    get_user(uid)["lang"] = "bn"
    await update.message.reply_text(
        T["bn"]["language_set_bn"],
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
            await query.edit_message_text(
                t(uid, "no_active_email"), parse_mode=ParseMode.MARKDOWN
            )
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
            pass  # Message unchanged — silently ignore Telegram's "not modified" error

    elif data.startswith("read_"):
        msg_id = data[5:]
        user = get_user(uid)
        token = user.get("token")

        if not token:
            await query.edit_message_text(
                t(uid, "no_active_email"), parse_mode=ParseMode.MARKDOWN
            )
            return

        async with aiohttp.ClientSession() as session:
            msg = await ACTIVE_PROVIDER.get_message(session, token, msg_id)

        if not msg:
            await query.edit_message_text(
                t(uid, "not_found"), parse_mode=ParseMode.MARKDOWN
            )
            return

        sender = msg.get("from", {}).get("address", "unknown")
        to_addr = ", ".join(a.get("address", "") for a in msg.get("to", []))
        subject = msg.get("subject", "(No Subject)")
        date = fmt_date(msg.get("createdAt", ""))

        raw_body = msg.get("text") or msg.get("html") or "(Empty)"
        body = strip_html(raw_body)
        body = truncate(body, 3000)

        detail = t(
            uid, "msg_detail",
            sender=sender, to=to_addr, subject=subject, date=date, body=body
        )

        back_btn = InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Back to Inbox", callback_data="inbox_refresh")]]
        )

        try:
            await query.edit_message_text(
                detail,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=back_btn,
            )
        except Exception:
            # Fallback: send a new message if editing fails (e.g. content too long)
            await ctx.bot.send_message(
                uid, detail,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=back_btn,
            )


# ─── Background Inbox Poller ──────────────────────────────────────────────────

async def inbox_poller(app: Application) -> None:
    """
    Polls every active user's inbox at INBOX_POLL_INTERVAL seconds
    and sends a Telegram notification for each new message.
    Uses the ACTIVE_PROVIDER — no changes needed here when switching providers.
    """
    logger.info("[Poller] Inbox poller started.")
    while True:
        await asyncio.sleep(INBOX_POLL_INTERVAL)

        active_users = [
            (uid, u)
            for uid, u in user_data.items()
            if u.get("token") and u.get("email")
        ]
        if not active_users:
            continue

        async with aiohttp.ClientSession() as session:
            for uid, user in active_users:
                try:
                    messages = await ACTIVE_PROVIDER.get_messages(session, user["token"])
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
                                logger.warning(f"[Notify] Failed uid={uid}: {e}")
                except Exception as e:
                    logger.warning(f"[Poller] Error for uid={uid}: {e}")


# ─── App Setup ────────────────────────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

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
        logger.info("[Bot] Started successfully.")

    app.post_init = post_init

    logger.info("[Bot] Starting in polling mode...")
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )


if __name__ == "__main__":
    main()
