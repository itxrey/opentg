import asyncio
import time
import random
from pyrogram import Client, filters, enums
from pyrogram.types import Message
from utils.db import db  # your existing DB module

# Namespace for DB keys used by this module
MODULE = "core.followup"

# Default follow-up message if none is set
DEFAULT_MESSAGE = "Hi! You haven't sent a message in a while. Hope you're doing well!"

# Inactivity interval (seconds); set to 86400 for 24 hours; for testing, you might use 60
FOLLOWUP_INTERVAL = 86400  # Change to 60 for testing

# ---------------------------
# Database utility functions

def get_enabled_users() -> list:
    return db.get(MODULE, "enabled_users", default=[])

def set_enabled_users(users: list):
    db.set(MODULE, "enabled_users", users)

def get_disabled_users() -> list:
    return db.get(MODULE, "disabled_users", default=[])

def set_disabled_users(users: list):
    db.set(MODULE, "disabled_users", users)

def get_global_followup() -> bool:
    return db.get(MODULE, "followup_all", default=False)

def set_global_followup(state: bool):
    db.set(MODULE, "followup_all", state)

def update_last_message(user_id: int):
    key = f"last_message.{user_id}"
    db.set(MODULE, key, int(time.time()))

def get_last_message(user_id: int) -> int:
    key = f"last_message.{user_id}"
    return db.get(MODULE, key, default=0)

def set_custom_followup_message(user_id: int, message: str):
    db.set(MODULE, f"followup_msg.{user_id}", message)

def get_custom_followup_message(user_id: int) -> str:
    return db.get(MODULE, f"followup_msg.{user_id}", default=DEFAULT_MESSAGE)

# ---------------------------
# Message tracking: update timestamp on every incoming private text message.
@Client.on_message(filters.text & filters.private & ~filters.me & ~filters.bot)
async def track_user_activity(client: Client, message: Message):
    user_id = message.from_user.id
    update_last_message(user_id)
    # If global follow-up is active and the user is not manually disabled, add the user to enabled list.
    if get_global_followup():
        disabled = get_disabled_users()
        if user_id not in disabled:
            enabled = get_enabled_users()
            if user_id not in enabled:
                enabled.append(user_id)
                set_enabled_users(enabled)

# ---------------------------
# Background task: check inactive users and send follow-up messages.
async def followup_checker(client: Client):
    while True:
        try:
            current_time = int(time.time())
            # Get all keys for this module to find candidate users (keys starting with "last_message.")
            collection = db.get_collection(MODULE)  # returns a dict of all keys under MODULE
            candidate_users = []
            for key in collection.keys():
                if key.startswith("last_message."):
                    try:
                        candidate_users.append(int(key.split(".")[1]))
                    except Exception:
                        continue

            enabled_users = set(get_enabled_users())
            global_on = get_global_followup()
            disabled_users = set(get_disabled_users())

            # Candidates: explicitly enabled users plus (if global follow-up is on) all users not disabled.
            recipients = set(enabled_users)
            if global_on:
                recipients |= (set(candidate_users) - disabled_users)

            for user_id in recipients:
                last_time = get_last_message(user_id)
                if current_time - last_time >= FOLLOWUP_INTERVAL:
                    followup_msg = get_custom_followup_message(user_id)
                    try:
                        await client.send_message(user_id, followup_msg)
                        update_last_message(user_id)
                    except Exception as e:
                        # Send error message to saved messages ("me")
                        await client.send_message("me", f"Error sending follow-up to {user_id}: {e}")
            await asyncio.sleep(3600)  # Check every hour
        except Exception as ex:
            # In case of an exception, send an error message to "me" and continue.
            await client.send_message("me", f"Error in followup_checker: {ex}")
            await asyncio.sleep(3600)

# ---------------------------
# Command handlers for follow-up control.
@Client.on_message(filters.command(["fp", ".fp"], prefixes=[".", "/"]) & filters.me)
async def manage_followup(client: Client, message: Message):
    args = message.text.split()
    if len(args) < 2:
        return await message.reply_text("Usage: .fp help")
    cmd = args[1].lower()

    if cmd == "help":
        help_text = (
            "**Follow-Up Module Help**\n\n"
            ".fp on <user_id> [<custom message>] - Enable follow-up for a user (with optional custom message).\n"
            ".fp off <user_id> - Disable follow-up for a user (won't be re-enabled by global settings).\n"
            ".fp all - Toggle global follow-up for all users (except manually disabled ones).\n"
            ".fp status [<user_id>] - Show follow-up status; if user_id provided, show that user's last message time and custom message.\n"
            ".fp help - Show this help message."
        )
        return await message.reply_text(help_text)

    elif cmd == "on":
        if len(args) < 3:
            return await message.reply_text("Usage: .fp on <user_id> [<custom message>]")
        try:
            user_id = int(args[2])
        except ValueError:
            return await message.reply_text("Invalid user ID.")
        custom_msg = " ".join(args[3:]) if len(args) > 3 else DEFAULT_MESSAGE
        enabled = get_enabled_users()
        if user_id not in enabled:
            enabled.append(user_id)
            set_enabled_users(enabled)
        set_custom_followup_message(user_id, custom_msg)
        # Remove from disabled list if present.
        disabled = get_disabled_users()
        if user_id in disabled:
            disabled.remove(user_id)
            set_disabled_users(list(disabled))
        return await message.reply_text(f"Follow-up enabled for user {user_id} with message: {custom_msg}")

    elif cmd == "off":
        if len(args) < 3:
            return await message.reply_text("Usage: .fp off <user_id>")
        try:
            user_id = int(args[2])
        except ValueError:
            return await message.reply_text("Invalid user ID.")
        enabled = get_enabled_users()
        if user_id in enabled:
            enabled.remove(user_id)
            set_enabled_users(enabled)
        disabled = get_disabled_users()
        if user_id not in disabled:
            disabled.append(user_id)
            set_disabled_users(disabled)
        return await message.reply_text(f"Follow-up disabled for user {user_id}")

    elif cmd == "all":
        state = not get_global_followup()
        set_global_followup(state)
        state_text = "enabled" if state else "disabled"
        return await message.reply_text(f"Global follow-up is now {state_text}. (Manually disabled users remain off.)")

    elif cmd == "status":
        if len(args) >= 3:
            try:
                user_id = int(args[2])
            except ValueError:
                return await message.reply_text("Invalid user ID.")
            last_time = get_last_message(user_id)
            custom_msg = get_custom_followup_message(user_id)
            diff = int(time.time()) - last_time
            return await message.reply_text(
                f"User {user_id} last messaged {diff} seconds ago.\nFollow-up message: {custom_msg}"
            )
        else:
            global_state = get_global_followup()
            enabled = get_enabled_users()
            disabled = get_disabled_users()
            status_text = (
                f"**Global Follow-Up:** {'Enabled' if global_state else 'Disabled'}\n"
                f"**Enabled Users:** {', '.join(str(uid) for uid in enabled) if enabled else 'None'}\n"
                f"**Manually Disabled Users:** {', '.join(str(uid) for uid in disabled) if disabled else 'None'}"
            )
            return await message.reply_text(status_text)
    else:
        return await message.reply_text("Invalid command. Use .fp help for usage.")

# ---------------------------
# Function to start the background follow-up checker.
async def start_followup_task(client: Client):
    asyncio.create_task(followup_checker(client))

# ---------------------------
# Optional: Module help command to integrate into your main help menu.
@Client.on_message(filters.command("help", prefixes=[".", "/"]) & filters.me)
async def module_help(client: Client, message: Message):
    args = message.text.split()
    if len(args) >= 3 and args[1].lower() == "fp":
        await message.reply_text(
            "**Follow-Up Module Help**\n\n"
            ".fp on <user_id> [<custom message>] - Enable follow-up for a user.\n"
            ".fp off <user_id> - Disable follow-up for a user.\n"
            ".fp all - Toggle global follow-up for all users (except manually disabled ones).\n"
            ".fp status [<user_id>] - Show follow-up status.\n"
            ".fp help - Show this help message."
        )
