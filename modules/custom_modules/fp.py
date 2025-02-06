import asyncio
import time
from datetime import datetime, timedelta
from pyrogram import Client, filters
from pyrogram.types import Message
from utils.db import db
 # Assuming you have a database module

# Collection names
FOLLOWUP_COLLECTION = "followup_settings"
TIMESTAMP_COLLECTION = "user_last_message"

# Default follow-up message
DEFAULT_FOLLOWUP_MSG = "Hi! Haven't heard from you in a while. How are you?"

# Track follow-up settings
followup_enabled_users = db.get(FOLLOWUP_COLLECTION, "enabled_users") or {}
followup_disabled_users = db.get(FOLLOWUP_COLLECTION, "disabled_users") or set()
followup_all_enabled = db.get(FOLLOWUP_COLLECTION, "followup_all") or False


@Client.on_message(filters.text & filters.private & ~filters.me & ~filters.bot)
async def track_user_message(client: Client, message: Message):
    """ Track user messages & update timestamp """
    user_id = str(message.from_user.id)

    # Save/Update timestamp
    db.set(TIMESTAMP_COLLECTION, user_id, time.time())

    # If manually disabled, do not enable follow-up on fp all
    if followup_all_enabled and user_id not in followup_disabled_users:
        followup_enabled_users[user_id] = DEFAULT_FOLLOWUP_MSG
        db.set(FOLLOWUP_COLLECTION, "enabled_users", followup_enabled_users)


async def followup_checker(client: Client):
    """ Background task to check inactive users & send follow-up messages """
    while True:
        await asyncio.sleep(60)  # Run every hour

        now = time.time()
        for user_id, followup_msg in followup_enabled_users.items():
            last_msg_time = db.get(TIMESTAMP_COLLECTION, user_id)

            if last_msg_time and now - last_msg_time >= 60:  # 24 hours
                try:
                    await client.send_message(int(user_id), followup_msg)
                    db.set(TIMESTAMP_COLLECTION, user_id, now)  # Update timestamp after sending
                except Exception as e:
                    print(f"Error sending follow-up to {user_id}: {e}")


@Client.on_message(filters.command("fp") & filters.private & filters.user("me"))
async def followup_command(client: Client, message: Message):
    """ Command to turn follow-up on/off for users """
    global followup_all_enabled

    args = message.text.split(maxsplit=3)
    if len(args) < 2:
        return await message.reply("Usage:\n/fp on <user_id> <message>\n/fp off <user_id>\n/fp all\n/fp status")

    action = args[1].lower()

    if action == "on":
        if len(args) < 4:
            return await message.reply("Usage: /fp on <user_id> <message>")

        user_id = args[2]
        followup_msg = args[3]
        followup_enabled_users[user_id] = followup_msg
        followup_disabled_users.discard(user_id)
        db.set(FOLLOWUP_COLLECTION, "enabled_users", followup_enabled_users)
        db.set(FOLLOWUP_COLLECTION, "disabled_users", followup_disabled_users)
        return await message.reply(f"Follow-up enabled for {user_id} with message: {followup_msg}")

    elif action == "off":
        if len(args) < 3:
            return await message.reply("Usage: /fp off <user_id>")

        user_id = args[2]
        followup_enabled_users.pop(user_id, None)
        followup_disabled_users.add(user_id)
        db.set(FOLLOWUP_COLLECTION, "enabled_users", followup_enabled_users)
        db.set(FOLLOWUP_COLLECTION, "disabled_users", followup_disabled_users)
        return await message.reply(f"Follow-up disabled for {user_id}")

    elif action == "all":
        followup_all_enabled = not followup_all_enabled
        db.set(FOLLOWUP_COLLECTION, "followup_all", followup_all_enabled)
        return await message.reply(f"Follow-up for all is now {'enabled' if followup_all_enabled else 'disabled'}")

    elif action == "status":
        status_msg = f"📊 **Follow-up Status**\n\n"
        status_msg += f"🔹 Follow-up All: {'Enabled' if followup_all_enabled else 'Disabled'}\n"
        status_msg += f"🔹 Enabled Users: {', '.join(followup_enabled_users.keys()) or 'None'}\n"
        status_msg += f"🔹 Manually Disabled Users: {', '.join(followup_disabled_users) or 'None'}\n"
        return await message.reply(status_msg)

    else:
        return await message.reply("Invalid command. Use /fp status to check follow-up settings.")


async def start_followup_task(client: Client):
    """ Start follow-up background task on startup """
    await asyncio.sleep(5)  # Wait for bot to fully start
    asyncio.create_task(followup_checker(client))


def help_section():
    """ Help text for module """
    return """🔹 **Follow-up Module Help** 🔹
    
👤 **User-based Follow-ups**
- `/fp on <user_id> <message>` → Enable follow-up for a specific user
- `/fp off <user_id>` → Disable follow-up for a specific user

🌍 **Global Follow-ups**
- `/fp all` → Toggle follow-up for all users (except manually disabled ones)

📊 **Check Status**
- `/fp status` → Show current follow-up settings

ℹ️ The bot will check inactivity every hour and send a follow-up message if no response in 24 hours.
"""

@Client.on_message(filters.command(["bt", "help"]) & filters.private)
async def help_command(client: Client, message: Message):
    """ Help command for follow-up module """
    args = message.text.split()
    
    if len(args) == 3 and args[1] == "help" and args[2] == "fp":
        return await message.reply(help_section())

    await message.reply("Use `.bt help fp` for follow-up help.")
