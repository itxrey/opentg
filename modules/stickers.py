#  Moon-Userbot - telegram userbot
#  Copyright (C) 2020-present Moon Userbot Organization
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.

#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.

import os
from io import BytesIO

from pyrogram import Client, filters, types, enums

from utils.misc import modules_help, prefix
from utils.scripts import (
    with_reply,
    interact_with,
    interact_with_to_delete,
    format_exc,
    resize_image,
)


@Client.on_message(filters.command("kang", prefix) & filters.me)
@with_reply
async def kang(client: Client, message: types.Message):
    await message.edit("<b>Please wait...</b>", parse_mode=enums.ParseMode.HTML)

    if len(message.command) < 2:
        await message.edit(
                    "<b>No arguments provided\n"
                    f"Usage: <code>{prefix}kang [pack]* [emoji]</code></b>",
                    parse_mode=enums.ParseMode.HTML
                )
        return

    pack = message.command[1]
    if len(message.command) >= 3:
        emoji = message.command[2]
    else:
        emoji = "✨"

    await client.unblock_user("@stickers")
    await interact_with(await client.send_message("@stickers", "/cancel", parse_mode=enums.ParseMode.MARKDOWN))
    await interact_with(await client.send_message("@stickers", "/addsticker", parse_mode=enums.ParseMode.MARKDOWN))

    result = await interact_with(await client.send_message("@stickers", pack, parse_mode=enums.ParseMode.MARKDOWN))
    if ".TGS" in result.text:
        await message.edit("<b>Animated packs aren't supported</b>", parse_mode=enums.ParseMode.HTML)
        return
    if "StickerExample.psd" not in result.text:
        await message.edit(
                    "<b>Stickerpack doesn't exitst. Create it using @Stickers bot (via /newpack command)</b>",
                    parse_mode=enums.ParseMode.HTML
                )
        return

    try:
        path = await message.reply_to_message.download()
    except ValueError:
        await message.edit(
                    "<b>Replied message doesn't contain any downloadable media</b>",
                    parse_mode=enums.ParseMode.HTML
                )
        return

    resized = resize_image(path)
    os.remove(path)

    await interact_with(await client.send_document("@stickers", resized, parse_mode=enums.ParseMode.MARKDOWN))
    response = await interact_with(await client.send_message("@stickers", emoji, parse_mode=enums.ParseMode.MARKDOWN))
    if "/done" in response.text:
        # ok
        await interact_with(await client.send_message("@stickers", "/done", parse_mode=enums.ParseMode.MARKDOWN))
        await client.delete_messages("@stickers", interact_with_to_delete)
        await message.edit(
                    f"<b>Sticker added to <a href=https://t.me/addstickers/{pack}>pack</a></b>",
                    parse_mode=enums.ParseMode.HTML
                )
    else:
        await message.edit("<b>Something went wrong. Check history with @stickers</b>", parse_mode=enums.ParseMode.HTML)
    interact_with_to_delete.clear()


@Client.on_message(filters.command(["stp", "s2p", "stick2png"], prefix) & filters.me)
@with_reply
async def stick2png(client: Client, message: types.Message):
    try:
        await message.edit("<b>Downloading...</b>", parse_mode=enums.ParseMode.HTML)

        path = await message.reply_to_message.download()
        with open(path, "rb") as f:
            content = f.read()
        os.remove(path)

        file_io = BytesIO(content)
        file_io.name = "sticker.png"

        await client.send_document(message.chat.id, file_io, parse_mode=enums.ParseMode.MARKDOWN)
    except Exception as e:
        await message.edit(format_exc(e), parse_mode=enums.ParseMode.HTML)
    else:
        await message.delete()


@Client.on_message(filters.command(["resize"], prefix) & filters.me)
@with_reply
async def resize_cmd(client: Client, message: types.Message):
    try:
        await message.edit("<b>Downloading...</b>", parse_mode=enums.ParseMode.HTML)

        path = await message.reply_to_message.download()
        resized = resize_image(path)
        resized.name = "image.png"
        os.remove(path)

        await client.send_document(message.chat.id, resized, parse_mode=enums.ParseMode.MARKDOWN)
    except Exception as e:
        await message.edit(format_exc(e), parse_mode=enums.ParseMode.HTML)
    else:
        await message.delete()


modules_help["stickers"] = {
    "kang [reply]* [pack]* [emoji]": "Add sticker to defined pack",
    "stp [reply]*": "Convert replied sticker to PNG",
    "resize [reply]*": "Resize replied image to 512xN format",
}
