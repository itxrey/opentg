import asyncio
from datetime import datetime, timedelta
from pyrogram import Client, filters
from pyrogram.types import Message
from utils.db import db

# Constants
FOLLOW_UP_TIMEOUT = timedelta(seconds=60)  # Change to 60 seconds for testing

async def send_follow_up_message(client: Client, user_id: int, custom_message: str = None):
    """Send a follow-up message to the user."""
    message = custom_message or "Hey, it's been a while since we last chatted! How can I assist you today?"
    await client.send_message(user_id, message)

async def check_inactive_users():
    """Check for inactive users and send follow-up messages if needed."""
    while True:
        await asyncio.sleep(60)  # Check every 60 seconds for testing
        current_time = datetime.now()
        users = db.get_collection("core.follow_up")  # Get all users from the database

        for user_id, last_message_time in users.items():
            last_message_time = datetime.fromisoformat(last_message_time)
            if current_time - last_message_time > FOLLOW_UP_TIMEOUT:
                disabled_users = db.get("core.follow_up", "disabled_users", default=[])
                if user_id not in disabled_users:
                    await send_follow_up_message(client, user_id)
                    db.remove("core.follow_up", f"user_{user_id}")  # Remove user after follow-up

@Client.on_message(filters.private)
async def handle_new_message(client: Client, message: Message):
    """Handle new messages and update the user's last message timestamp."""
    user_id = message.from_user.id
    db.set("core.follow_up", f"user_{user_id}", datetime.now().isoformat())  # Store timestamp

@Client.on_message(filters.command("fp") & filters.private)
async def follow_up_command(client: Client, message: Message):
    """Handle follow-up commands for users."""
    command = message.command[1] if len(message.command) > 1 else None
    user_id = message.from_user.id

    if command == "on":
        custom_message = message.command[2] if len(message.command) > 2 else None
        db.set("core.follow_up", f"user_{user_id}", datetime.now().isoformat())
        await send_follow_up_message(client, user_id, custom_message)
        await message.reply("Follow-up messages are now enabled for you.")

    elif command == "off":
        db.remove("core.follow_up", f"user_{user_id}")
        await message.reply("Follow-up messages are now disabled for you.")

    elif command == "all":
        global follow_up_enabled
        follow_up_enabled = not follow_up_enabled
        status = "enabled" if follow_up_enabled else "disabled"
        await message.reply(f"Global follow-up messages are now {status}.")

    elif command == "status":
        disabled_users = db.get("core.follow_up", "disabled_users", default=[])
        if user_id in disabled_users:
            await message.reply("Follow-up messages are currently disabled for you.")
        else:
            await message.reply("Follow-up messages are currently enabled for you.")

    elif command == "help":
        help_text = (
            "<b>Follow-Up Module Help:</b>\n"
            "/fp on [<custom message>] - Enable follow-up for yourself with an optional custom message.\n"
            "/fp off - Disable follow-up for yourself.\n"
            "/fp all - Toggle global follow-up for all users.\n"
            "/fp status - Check your follow-up status.\n"
            "/fp help - Show this help message."
        )
        await message.reply(help_text)

# Start the background task for checking inactive users
async def main(client: Client):
    await check_inactive_users()

# Register the main function to run when the bot starts
@Client.on_startup
async def on_startup(client: Client):
    asyncio.create_task(main(client))
