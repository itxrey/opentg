import os
import httpx
import subprocess
from pyrogram import Client, filters, enums
from pyrogram.types import Message
from utils.misc import modules_help, prefix
from utils.db import db

DEFAULT_PARAMS = {
    "voice_id": "21m00Tcm4TlvDq8ikWAM",
    "stability": 0.3,
    "similarity_boost": 0.9,
}

def process_audio(input_path: str, output_path: str, speed: float, volume: float):

    subprocess.run(
        [
            "ffmpeg",
            "-i", input_path,
            "-filter:a",
            f"atempo={speed},volume={volume},acompressor=threshold=-20dB:ratio=2.5:attack=5:release=50",
            "-vn",  # No video
            output_path,
        ],
        check=True
    )

async def generate_elevenlabs_audio(text: str):

    api_keys = db.get("custom.elevenlabs", "api_keys", [])
    current_key_index = db.get("custom.elevenlabs", "current_key_index", 0)
    
    if not api_keys:
        raise ValueError(f"No API keys configured! Use {prefix}set_el add_key <key>")

    params = {key: db.get("custom.elevenlabs", key, DEFAULT_PARAMS[key]) for key in DEFAULT_PARAMS}
    
    for attempt in range(len(api_keys)):
        api_key = api_keys[current_key_index]
        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json",
        }
        data = {
            "text": text,
            "voice_settings": {
                "stability": params["stability"],
                "similarity_boost": params["similarity_boost"],
            },
        }

        voice_id = params["voice_id"]
        original_audio_path = "elevenlabs_voice.mp3"

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                    headers=headers,
                    json=data,
                )

                if response.status_code == 200:
                    with open(original_audio_path, "wb") as f:
                        f.write(response.content)
                    return original_audio_path
                
                error_data = response.json()
                error_status = error_data.get("detail", {}).get("status", "")
                
                if error_status in ["quota_exceeded", "invalid_api_key", "too_many_concurrent_requests"]:
                    current_key_index = (current_key_index + 1) % len(api_keys)
                    db.set("custom.elevenlabs", "current_key_index", current_key_index)
                else:
                    raise ValueError(f"API Error: {error_data.get('detail', {}).get('message', 'Unknown error')}")

        except Exception as e:
            current_key_index = (current_key_index + 1) % len(api_keys)
            db.set("custom.elevenlabs", "current_key_index", current_key_index)

    raise ValueError("All API keys failed. Please add more keys or check existing ones.")

@Client.on_message(filters.command(["elevenlabs", "el"], prefix & filter.me)
async def elevenlabs_command(client: Client, message: Message):
    """
    Handle the ElevenLabs text-to-speech command.
    """
    original_audio_path = None
    processed_audio_path = None
    try:
        if len(message.command) < 2:
            await message.edit_text(
                f"**Usage:** `{prefix}elevenlabs [text]`",
                parse_mode=enums.ParseMode.MARKDOWN
            )
            return

        text = " ".join(message.command[1:]).strip()
        await message.delete()

        original_audio_path = await generate_elevenlabs_audio(text)
        processed_audio_path = "elevenlabs_voice_processed.mp3"
        
        #  audio processing f
        process_audio(original_audio_path, processed_audio_path, speed=0.9, volume=0.9)

        await client.send_voice(chat_id=message.chat.id, voice=processed_audio_path)

    except Exception as e:
        await client.send_message(
            message.chat.id,
            f"**Error:**\n`{e}`",
            parse_mode=enums.ParseMode.MARKDOWN
        )
    finally:
        for path in [original_audio_path, processed_audio_path]:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception as cleanup_error:
                    print(f"Cleanup error: {cleanup_error}")

@Client.on_message(filters.command(["set_elevenlabs", "set_el"], prefix) & filters.me)
async def set_elevenlabs_config(_, message: Message):
    """
    Configure ElevenLabs settings.
    """
    args = message.command
    if len(args) == 1:
        current_values = {key: db.get("custom.elevenlabs", key, DEFAULT_PARAMS[key]) for key in DEFAULT_PARAMS}
        api_keys = db.get("custom.elevenlabs", "api_keys", [])
        current_key_index = db.get("custom.elevenlabs", "current_key_index", 0)
        
        response = (
            "**ElevenLabs Configuration**\n\n"
            f"🔑 **API Keys ({len(api_keys)})**:\n"
            + "\n".join([f"{i+1}. `{key}`{' (current)' if i == current_key_index else ''}" for i, key in enumerate(api_keys)])
            + "\n\n⚙️ **Parameters**:\n"
            + "\n".join([f"• `{key}`: `{value}`" for key, value in current_values.items()])
            + "\n\n**Commands**:\n"
            f"`{prefix}set_el add_key <key>` - Add API key\n"
            f"`{prefix}set_el del_key <num>` - Delete key\n"
            f"`{prefix}set_el set_key <num>` - Set active key\n"
            f"`{prefix}set_el <param> <value>` - Voice_Id, speed"
        )
        return await message.edit_text(response, parse_mode=enums.ParseMode.MARKDOWN)

    action = args[1].lower()

    # Add key
    if action == "add_key" and len(args) >= 3:
        new_key = " ".join(args[2:])
        api_keys = db.get("custom.elevenlabs", "api_keys", [])
        if new_key not in api_keys:
            api_keys.append(new_key)
            db.set("custom.elevenlabs", "api_keys", api_keys)
            return await message.edit_text(f"✅ Added new key (Total: {len(api_keys)})")
        return await message.edit_text("⚠️ Key already exists")

    # Delete key
    if action == "del_key" and len(args) >= 3:
        try:
            index = int(args[2]) - 1
            api_keys = db.get("custom.elevenlabs", "api_keys", [])
            if 0 <= index < len(api_keys):
                deleted = api_keys.pop(index)
                db.set("custom.elevenlabs", "api_keys", api_keys)
                # Adjust current index if needed
                current_index = db.get("custom.elevenlabs", "current_key_index", 0)
                if current_index >= len(api_keys):
                    db.set("custom.elevenlabs", "current_key_index", max(0, len(api_keys)-1))
                return await message.edit_text(f"✅ Deleted key: `{deleted}`")
            return await message.edit_text("❌ Invalid key number")
        except ValueError:
            return await message.edit_text("❌ Invalid key number")

    # Set active key
    if action == "set_key" and len(args) >= 3:
        try:
            index = int(args[2]) - 1
            api_keys = db.get("custom.elevenlabs", "api_keys", [])
            if 0 <= index < len(api_keys):
                db.set("custom.elevenlabs", "current_key_index", index)
                return await message.edit_text(f"✅ Active key set to #{index+1}")
            return await message.edit_text("❌ Invalid key number")
        except ValueError:
            return await message.edit_text("❌ Invalid key number")

    # Original parameter handling
    if len(args) < 3:
        return await message.edit_text("❌ Invalid command format")

    key = args[1].lower()
    value = " ".join(args[2:])
    
    if key not in ["api_key", *DEFAULT_PARAMS.keys()]:
        return await message.edit_text("❌ Invalid parameter")

    if key in ["stability", "similarity_boost"]:
        try:
            value = float(value)
        except ValueError:
            return await message.edit_text("❌ Value must be a number")

    db.set("custom.elevenlabs", key, value)
    await message.edit_text(f"✅ Updated `{key}` to `{value}`")

modules_help["elevenlabs"] = {
    "el [text]*": "Generate voice message using ElevenLabs",
    "set_el": "Show configuration",
    "set_el add_key <key>": "Add new API key",
    "set_el del_key <num>": "Delete API key by number",
    "set_el set_key <num>": "Set active API key",
    "set_el voice_id <id>": "Set voice_id",
        "set_el stability <value>": "Set stability(0.1 - 1)",
                    }
