import asyncio
import time
import random
from pyrogram import Client, filters, enums
from pyrogram.types import Message
from utils.db import db  # use your existing database module

# Use a dedicated module namespace for follow-up settings
MODULE = "core.followup"

# Key names in the database:
# "enabled_users": list of user IDs explicitly enabled for follow-up (via .fp on)
# "disabled_users": list of user IDs explicitly disabled (via .fp off)
# "followup_all": boolean indicating if global follow-up is active (affects users not in disabled_users)
# Individual user last message timestamps are stored with key: "last_message.<user_id>"

# Default follow-up message
DEFAULT_MESSAGE = "Hi! You haven't sent a message in a while. Hope you're doing well!"

# For testing, you can change this to 60 (seconds) instead of 86400 (24 hours)
FOLLOWUP_INTERVAL = 60

# Utility functions to get/set follow-up settings in the DB
def get_enabled_users():
    return db.get(MODULE, "enabled_users", default=[])  # list of user IDs (as int)

def set_enabled_users(lst):
    db.set(MODULE, "enabled_users", lst)

def get_disabled_users():
    return db.get(MODULE, "disabled_users", default=[])

def set_disabled_users(lst):
    db.set(MODULE, "disabled_users", lst)

def get_global_followup():
    return db.get(MODULE, "followup_all", default=False)

def set_global_followup(state: bool):
    db.set(MODULE, "followup_all", state)

def update_last_message(user_id: int):
    # Store the current timestamp for this user
    key = f"last_message.{user_id}"
    db.set(MODULE, key, int(time.time()))

def get_last_message(user_id: int):
    key = f"last_message.{user_id}"
    return db.get(MODULE, key, default=0)

# ---------------------------------------------------------------------------
# Message tracking: Update timestamp on every incoming private message.
@Client.on_message(filters.text & filters.private & ~filters.me & ~filters.bot)
async def track_user_activity(client: Client, message: Message):
    user_id = message.from_user.id
    update_last_message(user_id)
    # If global follow-up is on and user is not manually disabled, add user to enabled list.
    global_state = get_global_followup()
    disabled = get_disabled_users()
    if global_state and user_id not in disabled:
        enabled = get_enabled_users()
        if user_id not in enabled:
            enabled.append(user_id)
            set_enabled_users(enabled)
    # (For users manually enabled via .fp on, they will already be in enabled_users.)

# ---------------------------------------------------------------------------
# Background task: Check every hour for users inactive for 24 hours.
async def followup_checker(client: Client):
    while True:
        try:
            current_time = int(time.time())
            # Get the lists from the DB
            enabled_users = get_enabled_users()  # explicit enables via .fp on
            global_state = get_global_followup()
            disabled_users = get_disabled_users()
            # For global follow-up, we want to check all users who are not disabled.
            # Merge the two sets: (explicitly enabled) union (all users if global is on and not disabled)
            # Since we only know about users who have sent messages, we can query them via our DB.
            # For simplicity, here we assume that any user with a stored timestamp is a candidate.
            # (You might later optimize this by iterating over a dedicated list.)
            cursor = db.get_collection(MODULE)  # Returns dict of all keys for this module
            # Filter keys starting with "last_message." to get user IDs
            user_ids = []
            for key in cursor.keys():
                if key.startswith("last_message."):
                    try:
                        uid = int(key.split(".")[1])
                        user_ids.append(uid)
                    except (IndexError, ValueError):
                        continue

            # Create a set of candidate users:
            candidates = set(enabled_users)
            if global_state:
                # Add any user with a stored timestamp, except those explicitly disabled.
                candidates |= set(user_ids) - set(disabled_users)

            # Now, for each candidate, check inactivity.
            for user_id in candidates:
                last_time = get_last_message(user_id)
                if current_time - last_time >= FOLLOWUP_INTERVAL:
                    # Get a custom message if set via .fp on; otherwise, use default.
                    # Here we store custom messages in the enabled_users list as a dict.
                    # For simplicity, we assume enabled_users is a list of ints.
                    # You can expand this to a dict if needed.
                    followup_msg = DEFAULT_MESSAGE
                    try:
                        await client.send_message(user_id, followup_msg)
                        # Update the timestamp so that the follow-up is not re-sent immediately.
                        update_last_message(user_id)
                    except Exception as e:
                        print(f"Error sending follow-up to {user_id}: {e}")
            await asyncio.sleep(3600)  # Check every hour
        except Exception as ex:
            print(f"Error in followup_checker: {ex}")
            await asyncio.sleep(60)

# ---------------------------------------------------------------------------
# Command handlers for follow-up control.
# These commands use the prefix .fp (or /fp)

@Client.on_message(filters.command(["fp", ".fp"], prefixes=[".", "/"]) & filters.me)
async def manage_followup(client: Client, message: Message):
    args = message.text.split()
    if len(args) < 2:
        return await message.reply_text("Usage: .fp help")

    cmd = args[1].lower()
    if cmd == "help":
        help_text = (
            "**Follow-Up Module Help**\n\n"
            ".fp on <user_id> [<message>] - Enable follow-up for a user with an optional custom message.\n"
            ".fp off <user_id> - Disable follow-up for a user (will not be re-enabled by global settings).\n"
            ".fp all - Toggle global follow-up for all users (except those manually disabled).\n"
            ".fp status [<user_id>] - Show follow-up status; if user_id is given, show that user's last message time.\n"
            ".fp help - Show this help message."
        )
        return await message.reply_text(help_text)

    elif cmd == "on" and len(args) >= 3:
        try:
            user_id = int(args[2])
        except ValueError:
            return await message.reply_text("Invalid user ID.")
        custom_msg = " ".join(args[3:]) if len(args) > 3 else DEFAULT_MESSAGE
        # In our simple design, enabling a user means adding them to enabled_users and
        # (optionally) storing the custom message.
        enabled = get_enabled_users()
        if user_id not in enabled:
            enabled.append(user_id)
            set_enabled_users(enabled)
        # For simplicity, we store the custom message in a separate key.
        db.set(MODULE, f"followup_msg.{user_id}", custom_msg)
        # Also, remove the user from disabled_users if present.
        disabled = get_disabled_users()
        if user_id in disabled:
            disabled.remove(user_id)
            set_disabled_users(disabled)
        await message.reply_text(f"Follow-up enabled for user {user_id} with message: {custom_msg}")

    elif cmd == "off" and len(args) >= 3:
        try:
            user_id = int(args[2])
        except ValueError:
            return await message.reply_text("Invalid user ID.")
        # Remove from enabled_users and add to disabled_users.
        enabled = get_enabled_users()
        if user_id in enabled:
            enabled.remove(user_id)
            set_enabled_users(enabled)
        disabled = get_disabled_users()
        if user_id not in disabled:
            disabled.append(user_id)
            set_disabled_users(disabled)
        await message.reply_text(f"Follow-up disabled for user {user_id}")

    elif cmd == "all":
        # Toggle global follow-up
        current_state = get_global_followup()
        new_state = not current_state
        set_global_followup(new_state)
        state_text = "enabled" if new_state else "disabled"
        await message.reply_text(f"Global follow-up is now {state_text}. (Manually disabled users remain off.)")

    elif cmd == "status":
        if len(args) >= 3:
            try:
                user_id = int(args[2])
            except ValueError:
                return await message.reply_text("Invalid user ID.")
            last_time = get_last_message(user_id)
            followup_msg = db.get(MODULE, f"followup_msg.{user_id}", default=DEFAULT_MESSAGE)
            diff = int(time.time()) - last_time
            await message.reply_text(
                f"User {user_id} last messaged {diff} seconds ago.\nFollow-up message: {followup_msg}"
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
            await message.reply_text(status_text)
    else:
        await message.reply_text("Invalid command. Use .fp help for usage.")

# ---------------------------------------------------------------------------
# Function to start the background follow-up task.
async def start_followup_task(client: Client):
    asyncio.create_task(followup_checker(client))
