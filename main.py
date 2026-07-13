# main.py — axCodeReceiver Bot
# Author: Sefuax | Channel: [t.me](https://t.me/ax_method)

import os
import re
import logging
import asyncio
import httpx
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ─────────────────────────────────────────────
# 1. LOGGING & ENV
# ─────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is not set!")

CHANNEL_USERNAME = "@ax_method"
CHANNEL_URL = "https://t.me/ax_method"
BASE_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ─────────────────────────────────────────────
# 2. CONVERSATION STATES
# ─────────────────────────────────────────────
WAITING_TOKEN = 1

# ─────────────────────────────────────────────
# 3. RAW BOT API HELPER (for style field support)
# ─────────────────────────────────────────────
async def raw_send_message(
    chat_id: int,
    text: str,
    reply_markup: dict = None,
    parse_mode: str = "HTML",
) -> dict:
    """Send message via raw Bot API to support button style field (Bot API 9.4+)."""
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(f"{BASE_API}/sendMessage", json=payload)
        resp.raise_for_status()
        return resp.json()


async def raw_delete_message(chat_id: int, message_id: int) -> None:
    """Delete a message via raw Bot API."""
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(
            f"{BASE_API}/deleteMessage",
            json={"chat_id": chat_id, "message_id": message_id},
        )


async def raw_answer_callback(callback_query_id: str, text: str, show_alert: bool = True) -> None:
    """Answer a callback query via raw Bot API."""
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(
            f"{BASE_API}/answerCallbackQuery",
            json={
                "callback_query_id": callback_query_id,
                "text": text,
                "show_alert": show_alert,
            },
        )


async def raw_send_message_with_reply_keyboard(
    chat_id: int,
    text: str,
    keyboard_buttons: list,
    parse_mode: str = "HTML",
    resize_keyboard: bool = True,
) -> dict:
    """
    Send message with ReplyKeyboardMarkup via raw Bot API.
    keyboard_buttons: list of rows, each row is a list of button dicts.
    """
    reply_markup = {
        "keyboard": keyboard_buttons,
        "resize_keyboard": resize_keyboard,
        "one_time_keyboard": False,
    }
    return await raw_send_message(chat_id, text, reply_markup, parse_mode)


# ─────────────────────────────────────────────
# 4. KEYBOARD BUILDERS
# ─────────────────────────────────────────────

def build_start_inline_keyboard() -> dict:
    """Inline keyboard for /start: Join Now (danger) + Check (success)."""
    return {
        "inline_keyboard": [
            [
                {
                    "text": "❗ 𝐉𝐨𝐢𝐧 𝐍𝐨𝐰",
                    "url": CHANNEL_URL,
                    "style": "danger",
                }
            ],
            [
                {
                    "text": "✔️ 𝐂𝐡𝐞𝐜𝐤",
                    "callback_data": "check_join",
                    "style": "success",
                }
            ],
        ]
    }


def build_main_reply_keyboard() -> list:
    """
    Main menu ReplyKeyboard rows (raw button dicts with style).
    Row 1: Get Code (primary/blue)
    Row 2: Settings (danger/red), Profile (success/green)
    """
    return [
        [{"text": "📨 𝐆𝐞𝐭 𝐂𝐨𝐝𝐞", "style": "primary"}],
        [
            {"text": "⚙️ 𝐒𝐞𝐭𝐭𝐢𝐧𝐠𝐬", "style": "danger"},
            {"text": "👤 𝐏𝐫𝐨𝐟𝐢𝐥𝐞", "style": "success"},
        ],
    ]


def build_back_reply_keyboard() -> list:
    """Back button keyboard (no style) — only in Get Code flow."""
    return [
        [{"text": "🔙 𝐁𝐚𝐜𝐤"}],
    ]


# Button text constants (must match exactly what's in keyboards)
BTN_GET_CODE  = "📨 𝐆𝐞𝐭 𝐂𝐨𝐝𝐞"
BTN_SETTINGS  = "⚙️ 𝐒𝐞𝐭𝐭𝐢𝐧𝐠𝐬"
BTN_PROFILE   = "👤 𝐏𝐫𝐨𝐟𝐢𝐥𝐞"
BTN_BACK      = "🔙 𝐁𝐚𝐜𝐤"

FOOTER = "\n\n𝘊𝘳𝘦𝘢𝘵𝘦𝘥 𝘉𝘺 𝘚𝘦𝘧𝘶𝘢𝘹 ⁉️"

# ─────────────────────────────────────────────
# 5. fetch_code() — dongvanfb.net
# ─────────────────────────────────────────────
async def fetch_code(token: str) -> dict:
    """
    Fetch OTP/messages from dongvanfb.net mailbox.
    Returns: {"code": str|None, "message": str}
    """
    url = "https://dongvanfb.net/read_mail_box/"
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; axCodeReceiverBot/1.0)",
        "Accept": "application/json, text/html, */*",
    }
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            # Try POST with form data first
            resp = await client.post(
                url,
                data={"token": token},
                headers=headers,
            )
            resp.raise_for_status()
            raw = resp.text.strip()

        # Try JSON parse
        try:
            import json
            data = json.loads(raw)
            # Extract message string from common JSON structures
            if isinstance(data, dict):
                message_text = (
                    data.get("message")
                    or data.get("msg")
                    or data.get("content")
                    or data.get("data")
                    or str(data)
                )
                if isinstance(message_text, dict):
                    message_text = str(message_text)
            else:
                message_text = str(data)
        except Exception:
            message_text = raw

        if not message_text:
            return {"code": None, "message": "⚠️ Empty response from server."}

        # Detect OTP: 4–8 digit standalone number
        match = re.search(r'\b(\d{4,8})\b', message_text)
        code = match.group(1) if match else None

        return {"code": code, "message": message_text}

    except httpx.TimeoutException:
        return {"code": None, "message": "⏱️ Request timed out. Server took too long to respond."}
    except httpx.HTTPStatusError as e:
        return {"code": None, "message": f"🚫 Server returned error {e.response.status_code}."}
    except httpx.RequestError as e:
        return {"code": None, "message": f"🌐 Connection error: {str(e)}"}
    except Exception as e:
        logger.exception("Unexpected error in fetch_code")
        return {"code": None, "message": f"❌ Unexpected error: {str(e)}"}


# ─────────────────────────────────────────────
# 6. MEMBERSHIP CHECK HELPER
# ─────────────────────────────────────────────
async def is_member(bot, user_id: int) -> bool:
    """Check if user is a member of the required channel."""
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status not in ("left", "kicked")
    except Exception as e:
        logger.warning(f"Membership check failed for user {user_id}: {e}")
        return False


async def enforce_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Returns True if user is a member.
    If not, sends the join prompt and returns False.
    """
    user = update.effective_user
    chat_id = update.effective_chat.id

    if await is_member(context.bot, user.id):
        return True

    # Not a member — send inline keyboard via raw API
    text = (
        "👋 𝗪𝗲𝗹𝗰𝗼𝗺𝗲 𝗧𝗼 𝒂𝒙𝑪𝒐𝒅𝒆𝑹𝒆𝒄𝒊𝒗𝒆𝒓 𝗕𝗼𝘁!\n\n"
        "I'm here to help you receive your OTP & messages instantly. 🛠️\n\n"
        "✨ 𝗪𝗵𝗮𝘁 𝗰𝗮𝗻 𝗜 𝗱𝗼?\n"
        "🔍 Read your mailbox messages\n"
        "✅ Extract OTP & codes automatically\n"
        "💡 Deliver results fast & clean\n\n"
        "➡️ First, join our channel to unlock the bot!"
        + FOOTER
    )
    await raw_send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=build_start_inline_keyboard(),
    )
    return False


# ─────────────────────────────────────────────
# 7. /start HANDLER
# ─────────────────────────────────────────────
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id

    # Remove any existing reply keyboard first
    await context.bot.send_message(
        chat_id=chat_id,
        text=".",
        reply_markup=ReplyKeyboardRemove(),
    )
    # Delete that helper message immediately
    try:
        sent = await context.bot.send_message(chat_id=chat_id, text="​")  # zero-width space
        await context.bot.delete_message(chat_id=chat_id, message_id=sent.message_id)
    except Exception:
        pass

    text = (
        "👋 𝗪𝗲𝗹𝗰𝗼𝗺𝗲 𝗧𝗼 𝒂𝒙𝑪𝒐𝒅𝒆𝑹𝒆𝒄𝒊𝒗𝒆𝒓 𝗕𝗼𝘁!\n\n"
        "I'm here to help you receive your OTP & messages instantly. 🛠️\n\n"
        "✨ 𝗪𝗵𝗮𝘁 𝗰𝗮𝗻 𝗜 𝗱𝗼?\n"
        "🔍 Read your mailbox messages\n"
        "✅ Extract OTP & codes automatically\n"
        "💡 Deliver results fast & clean\n\n"
        "➡️ First, join our channel to unlock the bot!"
        + FOOTER
    )
    result = await raw_send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=build_start_inline_keyboard(),
    )
    # Store welcome message ID so we can delete it later
    context.user_data["welcome_msg_id"] = result.get("result", {}).get("message_id")


# ─────────────────────────────────────────────
# 8. check_join CALLBACK HANDLER
# ─────────────────────────────────────────────
async def check_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    chat_id = update.effective_chat.id

    member_status = await is_member(context.bot, user.id)

    if not member_status:
        await raw_answer_callback(
            callback_query_id=query.id,
            text="❌ You haven't joined yet! Please join first then click Check ✔️",
            show_alert=True,
        )
        return

    # Acknowledge callback silently
    await raw_answer_callback(query.id, "✅ Verified!", show_alert=False)

    # Delete welcome message
    welcome_msg_id = context.user_data.get("welcome_msg_id")
    if welcome_msg_id:
        await raw_delete_message(chat_id, welcome_msg_id)
        context.user_data.pop("welcome_msg_id", None)

    # Also try deleting current message
    try:
        await raw_delete_message(chat_id, query.message.message_id)
    except Exception:
        pass

    # Send verified message with main reply keyboard (raw API for style support)
    text = (
        "✅ 𝗩𝗲𝗿𝗶𝗳𝗶𝗲𝗱! 𝗪𝗲𝗹𝗰𝗼𝗺𝗲 𝗮𝗯𝗼𝗮𝗿𝗱! 🎉\n\n"
        "You now have full access to 𝒂𝒙𝑪𝒐𝒅𝒆𝑹𝒆𝒄𝒊𝒗𝒆𝒓 𝗕𝗼𝘁!\n"
        "Use the menu below to get started 👇"
        + FOOTER
    )
    await raw_send_message_with_reply_keyboard(
        chat_id=chat_id,
        text=text,
        keyboard_buttons=build_main_reply_keyboard(),
    )


# ─────────────────────────────────────────────
# 9. GET CODE — ConversationHandler
# ─────────────────────────────────────────────
async def get_code_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point: user pressed 📨 Get Code."""
    chat_id = update.effective_chat.id

    if not await enforce_membership(update, context):
        return ConversationHandler.END

    text = (
        "🔑 𝗘𝗻𝘁𝗲𝗿 𝗬𝗼𝘂𝗿 𝗧𝗼𝗸𝗲𝗻\n\n"
        "Please send your token/session key so I can fetch your messages 🔐"
        + FOOTER
    )
    await raw_send_message_with_reply_keyboard(
        chat_id=chat_id,
        text=text,
        keyboard_buttons=build_back_reply_keyboard(),
    )
    return WAITING_TOKEN


async def receive_token(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User sent a token — fetch from dongvanfb.net."""
    chat_id = update.effective_chat.id
    token = update.message.text.strip()

    if not await enforce_membership(update, context):
        return ConversationHandler.END

    # Show "please wait" message
    wait_text = (
        "⏳ 𝗣𝗹𝗲𝗮𝘀𝗲 𝗪𝗮𝗶𝘁...\n\n"
        "Fetching your messages from the server 🌐\n"
        "This may take a few seconds ⚡"
        + FOOTER
    )
    await raw_send_message_with_reply_keyboard(
        chat_id=chat_id,
        text=wait_text,
        keyboard_buttons=build_back_reply_keyboard(),
    )

    # Fetch code
    result = await fetch_code(token)
    code = result.get("code")
    message = result.get("message", "No message received.")

    if code:
        response_text = (
            "✅ 𝗖𝗼𝗱𝗲 𝗙𝗼𝘂𝗻𝗱! 🎯\n\n"
            "Your OTP / Code:\n"
            f"<code>{code}</code>\n\n"
            "━━━━━━━━━━━━━━━\n"
            f"<code>{message}</code>"
            + FOOTER
        )
    else:
        response_text = (
            "📩 𝗠𝗲𝘀𝘀𝗮𝗴𝗲 𝗥𝗲𝗰𝗲𝗶𝘃𝗲𝗱!\n\n"
            f"<code>{message}</code>"
            + FOOTER
        )

    await raw_send_message_with_reply_keyboard(
        chat_id=chat_id,
        text=response_text,
        keyboard_buttons=build_back_reply_keyboard(),
    )
    return WAITING_TOKEN  # Stay in state so user can send another token or press Back


async def back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Back button pressed — return to main menu."""
    chat_id = update.effective_chat.id

    if not await enforce_membership(update, context):
        return ConversationHandler.END

    text = (
        "🏠 𝗠𝗮𝗶𝗻 𝗠𝗲𝗻𝘂\n\n"
        "Choose an option below 👇"
        + FOOTER
    )
    await raw_send_message_with_reply_keyboard(
        chat_id=chat_id,
        text=text,
        keyboard_buttons=build_main_reply_keyboard(),
    )
    return ConversationHandler.END


# ─────────────────────────────────────────────
# 10. SETTINGS HANDLER
# ─────────────────────────────────────────────
async def settings_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id

    if not await enforce_membership(update, context):
        return

    text = (
        "⚙️ 𝗦𝗲𝘁𝘁𝗶𝗻𝗴𝘀\n\n"
        "🚧 This section is under construction!\n"
        "More options coming soon... 🛠️"
        + FOOTER
    )
    await raw_send_message_with_reply_keyboard(
        chat_id=chat_id,
        text=text,
        keyboard_buttons=build_main_reply_keyboard(),
    )


# ─────────────────────────────────────────────
# 11. PROFILE HANDLER
# ─────────────────────────────────────────────
async def profile_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user = update.effective_user

    if not await enforce_membership(update, context):
        return

    username = f"@{user.username}" if user.username else "N/A"
    text = (
        "👤 𝗬𝗼𝘂𝗿 𝗣𝗿𝗼𝗳𝗶𝗹𝗲\n\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"👋 Name: {user.first_name}\n"
        f"🔗 Username: {username}\n"
        "🟢 Status: Active Member ✅"
        + FOOTER
    )
    await raw_send_message_with_reply_keyboard(
        chat_id=chat_id,
        text=text,
        keyboard_buttons=build_main_reply_keyboard(),
    )


# ─────────────────────────────────────────────
# 12. FALLBACK: unknown text outside conversation
# ─────────────────────────────────────────────
async def unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id

    if not await enforce_membership(update, context):
        return

    text = (
        "🤔 𝗨𝗻𝗸𝗻𝗼𝘄𝗻 𝗖𝗼𝗺𝗺𝗮𝗻𝗱\n\n"
        "Please use the menu buttons below to navigate 👇"
        + FOOTER
    )
    await raw_send_message_with_reply_keyboard(
        chat_id=chat_id,
        text=text,
        keyboard_buttons=build_main_reply_keyboard(),
    )


# ─────────────────────────────────────────────
# 13. main()
# ─────────────────────────────────────────────
def main() -> None:
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # ConversationHandler for Get Code flow
    get_code_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(f"^{re.escape(BTN_GET_CODE)}$"), get_code_entry)
        ],
        states={
            WAITING_TOKEN: [
                MessageHandler(filters.Regex(f"^{re.escape(BTN_BACK)}$"), back_to_main),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_token),
            ],
        },
        fallbacks=[
            CommandHandler("start", start_handler),
            MessageHandler(filters.Regex(f"^{re.escape(BTN_BACK)}$"), back_to_main),
        ],
        allow_reentry=True,
    )

    # Register handlers (order matters)
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CallbackQueryHandler(check_join_callback, pattern="^check_join$"))
    app.add_handler(get_code_conv)
    app.add_handler(MessageHandler(filters.Regex(f"^{re.escape(BTN_SETTINGS)}$"), settings_handler))
    app.add_handler(MessageHandler(filters.Regex(f"^{re.escape(BTN_PROFILE)}$"), profile_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_message))

    logger.info("🤖 axCodeReceiver Bot is starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
