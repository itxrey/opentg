import asyncio
import time
from typing import Dict, Optional, Set
from pyrogram import Client, filters, enums
from pyrogram.types import Message
from utils.db import db

MODULE = "core.followup"
DEFAULT_MESSAGE = "Hi! You haven't messaged in a while. Need any help?"
FOLLOWUP_INTERVAL = 70  # 24 hours in seconds
CHECK_INTERVAL = 60      # 1 hour in seconds

class FollowUpManager:
    def __init__(self):
        self._cache: Dict[int, int] = {}
        self._enabled_users: Set[int] = set()
        self._disabled_users: Set[int] = set()
        self._global_followup = False
        self._load_initial_state()

    def _load_initial_state(self):
        """Load initial state from database"""
        self._global_followup = db.get(MODULE, "followup_all", default=False)
        self._enabled_users = set(db.get(MODULE, "enabled_users", default=[]))
        self._disabled_users = set(db.get(MODULE, "disabled_users", default=[]))
        
        # Pre-cache last message times
        collection = db.get_collection(MODULE)
        self._cache = {
            int(key.split(".")[1]): value
            for key, value in collection.items()
            if key.startswith("last_message.")
        }

    def update_last_message(self, user_id: int):
        """Update last message timestamp for a user"""
        current_time = int(time.time())
        self._cache[user_id] = current_time
        db.set(MODULE, f"last_message.{user_id}", current_time)

    def get_last_message(self, user_id: int) -> int:
        """Get last message timestamp for a user"""
        return self._cache.get(user_id, 0)

    def toggle_user(self, user_id: int, enable: bool):
        """Toggle follow-up state for individual user"""
        if enable:
            self._disabled_users.discard(user_id)
            self._enabled_users.add(user_id)
        else:
            self._enabled_users.discard(user_id)
            self._disabled_users.add(user_id)
        
        self._persist_users()

    def toggle_global(self, state: bool):
        """Toggle global follow-up state"""
        self._global_followup = state
        db.set(MODULE, "followup_all", state)

    def set_custom_message(self, user_id: int, message: str):
        """Set custom follow-up message for a user"""
        db.set(MODULE, f"followup_msg.{user_id}", message)

    def get_custom_message(self, user_id: int) -> str:
        """Get follow-up message for a user"""
        return db.get(MODULE, f"followup_msg.{user_id}", default=DEFAULT_MESSAGE)

    def _persist_users(self):
        """Persist user lists to database"""
        db.set(MODULE, "enabled_users", list(self._enabled_users))
        db.set(MODULE, "disabled_users", list(self._disabled_users))

    def get_recipients(self) -> Set[int]:
        """Get current valid recipients based on settings"""
        if self._global_followup:
            return (set(self._cache.keys()) - self._disabled_users) | self._enabled_users
        return self._enabled_users - self._disabled_users

manager = FollowUpManager()

# ---------------------------
# Message tracking handler
@Client.on_message(filters.text & filters.private & ~filters.me & ~filters.bot)
async def track_user_activity(client: Client, message: Message):
    user_id = message.from_user.id
    manager.update_last_message(user_id)
    
    if manager._global_followup and user_id not in manager._disabled_users:
        manager._enabled_users.add(user_id)
        manager._persist_users()

# ---------------------------
# Background checker
async def followup_checker(client: Client):
    while True:
        try:
            current_time = int(time.time())
            recipients = manager.get_recipients()
            
            for user_id in recipients:
                last_time = manager.get_last_message(user_id)
                if current_time - last_time >= FOLLOWUP_INTERVAL:
                    try:
                        await client.send_message(
                            chat_id=user_id,
                            text=manager.get_custom_message(user_id),
                            parse_mode=enums.ParseMode.MARKDOWN
                        )
                        manager.update_last_message(user_id)
                    except Exception as e:
                        await client.send_message(
                            "me",
                            f"⚠️ Failed to message {user_id}: {str(e)}"
                        )
            
            await asyncio.sleep(CHECK_INTERVAL)
        except Exception as e:
            await client.send_message("me", f"🚨 Checker error: {str(e)}")
            await asyncio.sleep(CHECK_INTERVAL)

# ---------------------------
# Command handlers
@Client.on_message(filters.command(["fp", "followup"], prefixes=[".", "/"]) & filters.me)
async def manage_followup(client: Client, message: Message):
    args = message.text.split(maxsplit=2)
    cmd = args[1].lower() if len(args) > 1 else "help"

    handlers = {
        "on": handle_enable,
        "off": handle_disable,
        "all": handle_global,
        "status": handle_status,
        "help": handle_help
    }

    handler = handlers.get(cmd, handle_help)
    await handler(client, message, args)

# Command handlers implementation
async def handle_enable(client: Client, message: Message, args: list):
    if len(args) < 3:
        return await message.reply("🚫 Usage: `.fp on <user_id> [custom message]`")
    
    try:
        user_id = int(args[2].strip())
        custom_msg = args[3] if len(args) > 3 else DEFAULT_MESSAGE
        manager.toggle_user(user_id, True)
        manager.set_custom_message(user_id, custom_msg)
        await message.reply(f"✅ Follow-ups enabled for {user_id}\nCustom message: {custom_msg}")
    except (ValueError, IndexError):
        await message.reply("❌ Invalid user ID or message format")

async def handle_disable(client: Client, message: Message, args: list):
    if len(args) < 3:
        return await message.reply("🚫 Usage: `.fp off <user_id>`")
    
    try:
        user_id = int(args[2].strip())
        manager.toggle_user(user_id, False)
        await message.reply(f"✅ Follow-ups disabled for {user_id}")
    except ValueError:
        await message.reply("❌ Invalid user ID")

async def handle_global(client: Client, message: Message, args: list):
    new_state = not manager._global_followup
    manager.toggle_global(new_state)
    status = "ENABLED" if new_state else "DISABLED"
    await message.reply(f"🌍 Global follow-ups: {status}\n(Excluded users: {len(manager._disabled_users)})")

async def handle_status(client: Client, message: Message, args: list):
    if len(args) > 2:
        try:
            user_id = int(args[2].strip())
            last_time = manager.get_last_message(user_id)
            status = "ACTIVE" if user_id in manager.get_recipients() else "INACTIVE"
            response = (
                f"👤 User {user_id}\n"
                f"🕒 Last activity: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(last_time))}\n"
                f"📝 Custom message: {manager.get_custom_message(user_id)}\n"
                f"🔔 Status: {status}"
            )
        except ValueError:
            response = "❌ Invalid user ID"
    else:
        response = (
            f"🌍 Global: {'ON' if manager._global_followup else 'OFF'}\n"
            f"✅ Enabled: {len(manager._enabled_users)}\n"
            f"🚫 Disabled: {len(manager._disabled_users)}\n"
            f"👥 Tracking: {len(manager._cache)} users"
        )
    
    await message.reply(response)

async def handle_help(client: Client, message: Message, args: list):
    help_text = (
        "**Follow-Up Module Help**\n\n"
        "`.fp on <user_id> [message]` - Enable with optional custom message\n"
        "`.fp off <user_id>` - Disable for user\n"
        "`.fp all` - Toggle global mode\n"
        "`.fp status [user_id]` - Show statistics\n"
        "`.fp help` - Show this message"
    )
    await message.reply(help_text)

# ---------------------------
# Initialization
async def start_followup_task(client: Client):
    asyncio.create_task(followup_checker(client))
