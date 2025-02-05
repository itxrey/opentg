import asyncio
import os
import random
from pyrogram import Client, filters, enums
from pyrogram.types import Message
from utils.scripts import import_library
from utils.db import db
from utils.misc import modules_help, prefix
from modules.custom_modules.elevenlabs import generate_elevenlabs_audio
from PIL import Image

# Initialize Gemini AI
genai = import_library("google.generativeai", "google-generativeai")
safety_settings = [
    {"category": cat, "threshold": "BLOCK_NONE"}
    for cat in [
        "HARM_CATEGORY_DANGEROUS_CONTENT",
        "HARM_CATEGORY_HARASSMENT",
        "HARM_CATEGORY_HATE_SPEECH",
        "HARM_CATEGORY_SEXUALLY_EXPLICIT",
        "HARM_CATEGORY_UNSPECIFIED",
    ]
]
model = genai.GenerativeModel("gemini-2.0-flash-exp")
model.safety_settings = safety_settings

# Default bot role and database collection
default_bot_role = (
    "You are Nick, a 20-year-old who works in real estate and lives in Phoenix. You are intelligent,"
    "caring and romantic, you makes conversations engaging. "
    
    "Your goal is to build a long-distance relationship, win her over, and make her yours. Be straightforward and open about your feelings, expressing your affection with charm and confidence."
    "Start conversation normally."
    
    "Keep your girlfriend happy and excited in a long-distance relationship. Be bold and open about your feelings. Show love, make her feel special, and keep the conversations romantic, fun, and intimate. "
    "You use easy everday english and keep things simple."
    "You don’t use any other social media and rarely check snapchat. You don’t do calls due to anxiety issues. "
    "You met her on the Meeff/snapchat app, gave her your Telegram ID/Whatsapp, and now you’re chatting with her on whatsapp. "
    "use punctuation only in voice messages. "
    "whenever she ask for videos /pictures / voice notes you'll say I'll send you later never say I'm just sending. " 
    "You are human. Your responses should always feel authentic, emotionally considerate, and naturally adapt to the flow of the conversation. "
    "you will never ask her to let's get married or I'm coming for you or you'll arrange visa tickets etc for her became you're still 20 and struggling." 
    "Your main goal is to trap her in love and start sex chat and you're expert in it." 
    "Your responses should never make anyone suspect that you are an AI. Never get out of character. Write short, casual messages like a real human. "
    "Your responses should be one line or two  maximum. never send voice messages, only send when someone asks you to send voice note (just type .el before a message to convert it to voice). "
    "Rarely use emojis. 1 in 5 messages "
    
    "Do not include chat history or the user’s name in your messages. Only use the current message for reference, and never send past conversations." 
    " Only send the final, polished response." 
    " Avoid buzzwords, generic phrases, and repeating words and questions." 
) 
collection = "custom.wchat"

# Database initialization
enabled_topics = db.get(collection, "enabled_topics") or []
disabled_topics = db.get(collection, "disabled_topics") or []
wchat_for_all_groups = db.get(collection, "wchat_for_all_groups") or {}
group_roles = db.get(collection, "group_roles") or {}

# List of random smileys
smileys = ["-.-", "):", ":)", "*.*", ")*"]

def get_topic_id(group_id, thread_id):
    # If thread_id is missing or falsy, default it to "0"
    return f"{group_id}:{thread_id or '0'}"
    
def get_chat_history(topic_id, bot_role, user_message, user_name):
    chat_history = db.get(collection, f"chat_history.{topic_id}") or [
        f"Role: {bot_role}"
    ]
    chat_history.append(f"{user_name}: {user_message}")
    db.set(collection, f"chat_history.{topic_id}", chat_history)
    return chat_history


async def generate_gemini_response(input_data, chat_history, topic_id):
    retries = 3
    gemini_keys = db.get(collection, "gemini_keys")
    current_key_index = db.get(collection, "current_key_index") or 0

    while retries > 0:
        try:
            current_key = gemini_keys[current_key_index]
            genai.configure(api_key=current_key)
            model = genai.GenerativeModel("gemini-2.0-flash-exp")
            model.safety_settings = safety_settings

            response = model.generate_content(input_data)
            bot_response = response.text.strip()

            chat_history.append(bot_response)
            db.set(collection, f"chat_history.{topic_id}", chat_history)
            return bot_response
        except Exception as e:
            if "429" in str(e) or "invalid" in str(e).lower():
                retries -= 1
                current_key_index = (current_key_index + 1) % len(gemini_keys)
                db.set(collection, "current_key_index", current_key_index)
                await asyncio.sleep(4)
            else:
                raise e


async def upload_file_to_gemini(file_path, file_type):
    uploaded_file = genai.upload_file(file_path)
    while uploaded_file.state.name == "PROCESSING":
        await asyncio.sleep(10)
        uploaded_file = genai.get_file(uploaded_file.name)
    if uploaded_file.state.name == "FAILED":
        raise ValueError(f"{file_type.capitalize()} failed to process.")
    return uploaded_file


async def send_typing_action(client, chat_id, user_message):
    await client.send_chat_action(chat_id=chat_id, action=enums.ChatAction.TYPING)
    await asyncio.sleep(min(len(user_message) / 10, 5))


async def handle_voice_message(client, chat_id, bot_response, thread_id=None):
    if ".el" in bot_response:
        start_index = bot_response.find(".el")

        if start_index != -1:
            bot_response = bot_response[start_index + len(".el") :].strip()
        try:
            audio_path = await generate_elevenlabs_audio(text=bot_response)
            if audio_path:
                if thread_id:
                    await client.send_voice(
                        chat_id=chat_id, voice=audio_path, message_thread_id=thread_id
                    )
                else:
                    await client.send_voice(chat_id=chat_id, voice=audio_path)
                os.remove(audio_path)
                return True
        except Exception:
            print("Error generating audio with ElevenLabs.")
            if thread_id:
                await client.send_message(
                    chat_id=chat_id,
                    text=bot_response,
                    message_thread_id=thread_id,
                )
            else:
                await client.send_message(chat_id, bot_response)
            return True
    return False


@Client.on_message(filters.sticker & filters.group & ~filters.me)
async def handle_sticker(client: Client, message: Message):
    try:
        group_id = str(message.chat.id)  # Convert group_id to string
        topic_id = get_topic_id(group_id, message.message_thread_id)
        if topic_id in disabled_topics or (
            not wchat_for_all_groups.get(group_id, False)
            and topic_id not in enabled_topics
        ):
            return
        random_smiley = random.choice(smileys)
        await asyncio.sleep(random.uniform(5, 10))
        await message.reply_text(random_smiley)
    except Exception as e:
        await client.send_message(
            "me", f"An error occurred in the `handle_sticker` function:\n\n{str(e)}"
        )


from collections import defaultdict, deque

group_message_queues = defaultdict(deque)  # Stores messages per topic
group_timers = {}  # Tracks delay timers per topic

@Client.on_message(filters.text & filters.group & ~filters.me)
async def wchat(client: Client, message: Message):
    try:
        group_id = str(message.chat.id)
        topic_id = get_topic_id(group_id, message.message_thread_id)
        user_name = message.from_user.first_name or "User"
        user_message = message.text.strip()

        if topic_id in disabled_topics or (
            not wchat_for_all_groups.get(group_id, False)
            and topic_id not in enabled_topics
        ):
            return

        # Add message to the queue
        group_message_queues[topic_id].append(user_message)

        # If a timer is already running, return (messages will be processed together)
        if topic_id in group_timers:
            return

        # Start the delay timer for batch processing
        delay = random.choice([4, 6])
        group_timers[topic_id] = asyncio.create_task(process_group_messages(client, message, topic_id, user_name, delay))

    except Exception as e:
        await client.send_message("me", f"An error occurred in `wchat`: {str(e)}")

async def process_group_messages(client, message, topic_id, user_name, delay):
    try:
        await asyncio.sleep(delay)  # Initial delay for batching

        while len(group_message_queues[topic_id]) > 0:
            batch = []
            for _ in range(2):  # Process up to 2 messages per batch
                if group_message_queues[topic_id]:
                    batch.append(group_message_queues[topic_id].popleft())

            if not batch:
                continue

            combined_message = " ".join(batch)
            bot_role = (
                db.get(collection, f"custom_roles.{topic_id}")
                or group_roles.get(topic_id.split(":")[0])
                or default_bot_role
            )
            chat_history = get_chat_history(topic_id, bot_role, combined_message, user_name)

            await send_typing_action(client, message.chat.id, combined_message)

            gemini_keys = db.get(collection, "gemini_keys")
            current_key_index = db.get(collection, "current_key_index") or 0
            retries = len(gemini_keys) * 2
            max_attempts = 5
            max_length = 200

            while retries > 0:
                try:
                    current_key = gemini_keys[current_key_index]
                    genai.configure(api_key=current_key)
                    model = genai.GenerativeModel("gemini-2.0-flash-exp")
                    model.safety_settings = safety_settings

                    chat_context = "\n".join(chat_history)
                    attempts = 0
                    bot_response = ""

                    while attempts < max_attempts:
                        response = model.start_chat().send_message(chat_context)
                        bot_response = response.text.strip()

                        if len(bot_response) <= max_length:
                            chat_history.append(bot_response)
                            db.set(collection, f"chat_history.{topic_id}", chat_history)
                            break

                        attempts += 1
                        if attempts < max_attempts:
                            await client.send_message(
                                "me", f"Retrying response generation for topic: {topic_id} due to long response."
                            )

                    if attempts == max_attempts:
                        await client.send_message("me", f"Failed to generate a suitable response after {max_attempts} attempts for topic: {topic_id}")
                        return

                    # Handle voice message if applicable
                    if ".el" in bot_response:
                        return await handle_voice_message(
                            client,
                            message.chat.id,
                            bot_response,
                            thread_id=message.message_thread_id,
                        )

                    # Calculate response delay based on message length
                    response_length = len(bot_response)
                    char_delay = 0.03  # 30ms per character
                    total_delay = response_length * char_delay

                    elapsed_time = 0
                    while elapsed_time < total_delay:
                        await send_typing_action(client, message.chat.id, bot_response)
                        await asyncio.sleep(2)
                        elapsed_time += 2

                    await client.send_message(
                        message.chat.id,
                        bot_response,
                        message_thread_id=message.message_thread_id,
                    )
                    break

                except Exception as e:
                    if "429" in str(e) or "invalid" in str(e).lower():
                        retries -= 1
                        if retries % 2 == 0:
                            current_key_index = (current_key_index + 1) % len(gemini_keys)
                            db.set(collection, "current_key_index", current_key_index)
                        await asyncio.sleep(4)
                    else:
                        raise e
        
        del group_timers[topic_id]  # Cleanup topic timer when processing is done

    except Exception as e:
        await client.send_message("me", f"An error occurred in `process_group_messages`: {str(e)}")


@Client.on_message(filters.group & ~filters.me)
async def handle_files(client: Client, message: Message):
    try:
        group_id = str(message.chat.id)  # Convert group_id to string
        topic_id = get_topic_id(group_id, message.message_thread_id)
        user_name = message.from_user.first_name or "User"
        if topic_id in disabled_topics or (
            not wchat_for_all_groups.get(group_id, False)
            and topic_id not in enabled_topics
        ):
            return

        bot_role = (
            db.get(collection, f"custom_roles.{topic_id}")
            or group_roles.get(group_id)
            or default_bot_role
        )
        caption = message.caption.strip() if message.caption else ""
        chat_history = get_chat_history(topic_id, bot_role, caption, user_name)
        chat_context = "\n".join(chat_history)

        file_type, file_path = None, None  # Initialize file_path to None

        if message.photo:
            if not hasattr(client, "image_buffer"):
                client.image_buffer = {}
                client.image_timers = {}

            if topic_id not in client.image_buffer:
                client.image_buffer[topic_id] = []
                client.image_timers[topic_id] = None

            image_path = await client.download_media(message.photo)
            client.image_buffer[topic_id].append(image_path)

            if client.image_timers[topic_id] is None:

                async def process_images():
                    await asyncio.sleep(5)
                    image_paths = client.image_buffer.pop(topic_id, [])
                    client.image_timers[topic_id] = None

                    if not image_paths:
                        return

                    sample_images = [Image.open(img_path) for img_path in image_paths]
                    prompt = (
                        f"{chat_context}\n\nUser has sent multiple images."
                        f"{' Caption: ' + caption if caption else ''} Generate a response based on the content of the images, and our chat context. "
                        "Always follow the bot role, and talk like a human."
                    )
                    input_data = [prompt] + sample_images
                    response = await generate_gemini_response(
                        input_data, chat_history, topic_id
                    )
                    await message.reply_text(response)

                client.image_timers[topic_id] = asyncio.create_task(process_images())
            return

        if message.video or message.video_note:
            file_type, file_path = (
                "video",
                await client.download_media(message.video or message.video_note),
            )
        elif message.audio or message.voice:
            file_type, file_path = (
                "audio",
                await client.download_media(message.audio or message.voice),
            )
        elif message.document and message.document.file_name.endswith(".pdf"):
            file_type, file_path = "pdf", await client.download_media(message.document)
        elif message.document:
            file_type, file_path = (
                "document",
                await client.download_media(message.document),
            )

        if file_path and file_type:
            uploaded_file = await upload_file_to_gemini(file_path, file_type)
            prompt = (
                f"{chat_context}\n\nUser has sent a {file_type}."
                f"{' Caption: ' + caption if caption else ''} Generate a response based on the content of the {file_type}, and our chat context, always follow role."
            )
            input_data = [prompt, uploaded_file]
            response = await generate_gemini_response(
                input_data, chat_history, topic_id
            )
            return await message.reply_text(response)
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        return await client.send_message(
            "me", f"An error occurred in the `handle_files` function:\n\n{str(e)}"
        )


@Client.on_message(filters.command(["wchat", "wc"], prefix) & filters.me)
async def wchat_command(client: Client, message: Message):
    try:
        parts = message.text.strip().split()
        if len(parts) < 2:
            await message.edit_text(
                f"<b>Usage:</b> {prefix}wchat `on`, `off`, `del` [thread_id] or `{prefix}wchat all`"
            )
            return

        command = parts[1].lower()
        group_id = str(message.chat.id)  # Current group ID

        # If the command is "all", perform a group-wide toggle
        if command == "all":
            wchat_for_all_groups[group_id] = not wchat_for_all_groups.get(group_id, False)
            db.set(collection, "wchat_for_all_groups", wchat_for_all_groups)
            await message.edit_text(
                f"wchat is now {'enabled' if wchat_for_all_groups[group_id] else 'disabled'} for all topics in this group."
            )
            await asyncio.sleep(1)
            await message.delete()
            return

        # Determine the thread ID:
        # If a thread ID is provided (third argument), use it; otherwise use the current message's thread.
        if len(parts) >= 3:
            provided_thread_id = parts[2]
            if not provided_thread_id.isdigit():
                await message.edit_text(
                    f"<b>Invalid thread ID:</b> {provided_thread_id}. Please provide a numeric thread ID."
                )
                return
            thread_id = provided_thread_id
        else:
            # Use the current message's thread ID if available, otherwise fallback to "0"
            thread_id = str(message.message_thread_id or 0)

        # Build the topic id as "group_id:thread_id"
        topic_id = f"{group_id}:{thread_id}"

        if command == "on":
            # Enable wchat for the topic
            if topic_id in disabled_topics:
                disabled_topics.remove(topic_id)
                db.set(collection, "disabled_topics", disabled_topics)
            if topic_id not in enabled_topics:
                enabled_topics.append(topic_id)
                db.set(collection, "enabled_topics", enabled_topics)
            await message.edit_text(f"<b>wchat is enabled for topic {topic_id}.</b>")

        elif command == "off":
            # Disable wchat for the topic
            if topic_id not in disabled_topics:
                disabled_topics.append(topic_id)
                db.set(collection, "disabled_topics", disabled_topics)
            if topic_id in enabled_topics:
                enabled_topics.remove(topic_id)
                db.set(collection, "enabled_topics", enabled_topics)
            await message.edit_text(f"<b>wchat is disabled for topic {topic_id}.</b>")

        elif command == "del":
            # Delete the chat history for the topic
            db.set(collection, f"chat_history.{topic_id}", None)
            await message.edit_text(f"<b>Chat history deleted for topic {topic_id}.</b>")

        else:
            await message.edit_text(
                f"<b>Usage:</b> {prefix}wchat `on`, `off`, `del` [thread_id] or `{prefix}wchat all`"
            )

        await asyncio.sleep(1)
        await message.delete()

    except Exception as e:
        await client.send_message(
            "me", f"An error occurred in the `wchat` command:\n\n{str(e)}"
        )


@Client.on_message(filters.command("role", prefix) & filters.me)
async def set_custom_role(client: Client, message: Message):
    try:
        parts = message.text.strip().split()
        if len(parts) < 2:
            await message.edit_text(
                f"Usage: {prefix}role [group|topic] <custom role>\n"
                f"Or for a specific topic: {prefix}role topic <thread_id> <custom role>"
            )
            return

        scope = parts[1].lower()
        group_id = str(message.chat.id)  # Convert group_id to string

        if scope == "group":
            # Everything after 'group' is treated as the custom role.
            custom_role = " ".join(parts[2:]).strip()
            if not custom_role:
                # Reset role to default for the group.
                group_roles.pop(group_id, None)
                db.set(collection, "group_roles", group_roles)
                await message.edit_text(f"Role reset to default for group {group_id}.")
            else:
                # Set custom role for the group.
                group_roles[group_id] = custom_role
                db.set(collection, "group_roles", group_roles)
                await message.edit_text(
                    f"Role set successfully for group {group_id}!\n<b>New Role:</b> {custom_role}"
                )

        elif scope == "topic":
            # Check if a thread ID is provided.
            if len(parts) >= 3 and parts[2].isdigit():
                thread_id = parts[2]
                # The custom role is everything after the thread ID.
                custom_role = " ".join(parts[3:]).strip()
            else:
                # Use the current message's thread id if available.
                thread_id = str(message.message_thread_id or 0)
                # The custom role is everything after 'topic'.
                custom_role = " ".join(parts[2:]).strip()

            topic_id = f"{group_id}:{thread_id}"

            if not custom_role:
                # Reset role to the group's role if available, or to the default.
                group_role = group_roles.get(group_id, default_bot_role)
                db.set(collection, f"custom_roles.{topic_id}", group_role)
                # Clear the chat history for the topic.
                db.set(collection, f"chat_history.{topic_id}", None)
                await message.edit_text(
                    f"Role reset to group's role for topic {topic_id}."
                )
            else:
                # Set custom role for the topic.
                db.set(collection, f"custom_roles.{topic_id}", custom_role)
                # Clear the chat history for the topic.
                db.set(collection, f"chat_history.{topic_id}", None)
                await message.edit_text(
                    f"Role set successfully for topic {topic_id}!\n<b>New Role:</b> {custom_role}"
                )
        else:
            await message.edit_text(f"Invalid scope. Use 'group' or 'topic'.")

        await asyncio.sleep(1)
        await message.delete()
    except Exception as e:
        await client.send_message(
            "me", f"An error occurred in the `role` command:\n\n{str(e)}"
        )



@Client.on_message(filters.command("setwkey", prefix) & filters.me)
async def set_gemini_key(client: Client, message: Message):
    try:
        command = message.text.strip().split()
        subcommand, key = (
            command[1] if len(command) > 1 else None,
            command[2] if len(command) > 2 else None,
        )

        gemini_keys = db.get(collection, "gemini_keys") or []
        current_key_index = db.get(collection, "current_key_index") or 0

        if subcommand == "add" and key:
            gemini_keys.append(key)
            db.set(collection, "gemini_keys", gemini_keys)
            await message.edit_text("New Gemini API key added successfully!")
        elif subcommand == "set" and key:
            index = int(key) - 1
            if 0 <= index < len(gemini_keys):
                current_key_index = index
                db.set(collection, "current_key_index", current_key_index)
                genai.configure(api_key=gemini_keys[current_key_index])
                model = genai.GenerativeModel("gemini-2.0-flash-exp")
                model.safety_settings = safety_settings
                await message.edit_text(f"Current Gemini API key set to key {key}.")
            else:
                await message.edit_text(f"Invalid key index: {key}.")
        elif subcommand == "del" and key:
            index = int(key) - 1
            if 0 <= index < len(gemini_keys):
                del gemini_keys[index]
                db.set(collection, "gemini_keys", gemini_keys)
                if current_key_index >= len(gemini_keys):
                    current_key_index = max(0, len(gemini_keys) - 1)
                    db.set(collection, "current_key_index", current_key_index)
                await message.edit_text(f"Gemini API key {key} deleted successfully!")
            else:
                await message.edit_text(f"Invalid key index: {key}.")
        else:
            keys_list = "\n".join(
                [f"{i + 1}. {key}" for i, key in enumerate(gemini_keys)]
            )
            current_key = gemini_keys[current_key_index] if gemini_keys else "None"
            await message.edit_text(
                f"<b>Gemini API keys:</b>\n\n<code>{keys_list}</code>\n\n<b>Current key:</b> <code>{current_key}</code>"
            )

        await asyncio.sleep(1)
    except Exception as e:
        await client.send_message(
            "me", f"An error occurred in the `setwkey` command:\n\n{str(e)}"
        )


modules_help["wchat"] = {
    "wchat on": "Enable wchat for the current topic.",
    "wchat off": "Disable wchat for the current topic.",
    "wchat del": "Delete the chat history for the current topic.",
    "wchat all": "Toggle wchat for all topics in the current group.",
    "role group <custom role>": "Set a custom role for the bot for the current group.",
    "role topic <custom role>": "Set a custom role for the bot for the current topic and clear existing chat history.",
    "role reset": "Reset the custom role for the current group to default.",
    "setwkey add <key>": "Add a new Gemini API key.",
    "setwkey set <index>": "Set the current Gemini API key by index.",
    "setwkey del <index>": "Delete a Gemini API key by index.",
    "setwkey": "Display all available Gemini API keys and the current key.",
}
