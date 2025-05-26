import os
import json
import logging
import discord
from discord.ext import commands
from dotenv import load_dotenv
import google.generativeai as genai

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='translation-bot.log',
    encoding='utf-8',
    filemode='a',
)
logger = logging.getLogger('translation-bot')

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

# Configure Gemini API
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.0-flash')

# Setup bot with command prefix
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Language preferences file
LANG_FILE = 'user_langs.json'
CHANNEL_FILE = 'channel_settings.json'
MESSAGE_PAIRS_FILE = 'message_pairs.json'

# Load user language preferences
def load_user_langs():
    try:
        if os.path.exists(LANG_FILE):
            with open(LANG_FILE, 'r') as f:
                return json.load(f)
        else:
            return {}
    except Exception as e:
        logger.error(f"Error loading language preferences: {e}")
        return {}

# Load channel settings
def load_channel_settings():
    try:
        if os.path.exists(CHANNEL_FILE):
            with open(CHANNEL_FILE, 'r') as f:
                return json.load(f)
        else:
            return {}
    except Exception as e:
        logger.error(f"Error loading channel settings: {e}")
        return {}

# Load message pairs (original_msg_id -> translated_msg_id)
def load_message_pairs():
    try:
        if os.path.exists(MESSAGE_PAIRS_FILE):
            with open(MESSAGE_PAIRS_FILE, 'r') as f:
                return json.load(f)
        else:
            return {}
    except Exception as e:
        logger.error(f"Error loading message pairs: {e}")
        return {}

# Save user language preferences
def save_user_langs(user_langs):
    try:
        with open(LANG_FILE, 'w') as f:
            json.dump(user_langs, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving language preferences: {e}")

# Save channel settings
def save_channel_settings(channel_settings):
    try:
        with open(CHANNEL_FILE, 'w') as f:
            json.dump(channel_settings, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving channel settings: {e}")

# Save message pairs
def save_message_pairs(message_pairs):
    try:
        with open(MESSAGE_PAIRS_FILE, 'w') as f:
            json.dump(message_pairs, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving message pairs: {e}")

# User language preferences
user_langs = load_user_langs()
# Channel translation settings (channel_id -> enabled status)
channel_settings = load_channel_settings()
# Message pairs for tracking edits/deletes (original_msg_id -> translated_msg_id)
message_pairs = load_message_pairs()

@bot.event
async def on_ready():
    logger.info(f"{bot.user.name} has connected to Discord!")

@bot.command(name='setlang')
@commands.has_permissions(administrator=True)
async def set_language(ctx, member: discord.Member, from_lang: str, to_lang: str):
    """Set the language translation preferences for a user (Admin/Mod only)
    
    Args:
        member: The user to set language for
        from_lang: Source language code (e.g., 'en', 'ja', 'es')
        to_lang: Target language code (e.g., 'en', 'ja', 'es')
    """
    try:
        user_id = str(member.id)
        
        # Create or update user preferences
        if user_id not in user_langs:
            user_langs[user_id] = {
                "from_lang": from_lang,
                "to_lang": to_lang,
                "enabled": True
            }
        else:
            user_langs[user_id]["from_lang"] = from_lang
            user_langs[user_id]["to_lang"] = to_lang
            
        save_user_langs(user_langs)
        await ctx.send(f"Language preference for {member.display_name} set to translate from {from_lang} to {to_lang}")
        logger.info(f"Set language for user {user_id} from {from_lang} to {to_lang}")
    except Exception as e:
        await ctx.send(f"Failed to set language: {str(e)}")
        logger.error(f"Error setting language: {e}")

@bot.command(name='mylang')
async def my_language(ctx):
    """Check your current language preference"""
    user_id = str(ctx.author.id)
    user_prefs = user_langs.get(user_id, {})
    
    if user_prefs:
        from_lang = user_prefs.get("from_lang", None)
        to_lang = user_prefs.get("to_lang", None)
        enabled = user_prefs.get("enabled", False)
        status = "enabled" if enabled else "disabled"
        await ctx.send(f"Your language translation is set from {from_lang} to {to_lang} (Translation is {status})")
    else:
        await ctx.send("You don't have a language preference set.")

@bot.command(name='translate', aliases=['tl'])
async def translate_command(ctx, state: str, target: str = None):
    """Turn translation on or off for a user, channel, or all users
    
    Examples:
    !translate on - Turn on translation for yourself
    !translate off - Turn off translation for yourself
    !translate on @user - Turn on translation for the mentioned user (Admin/Mod only)
    !translate off @user - Turn off translation for the mentioned user (Admin/Mod only)
    !translate on #channel - Turn on translation for the mentioned channel (Admin/Mod only)
    !translate off #channel - Turn off translation for the mentioned channel (Admin/Mod only)
    !translate on ALL - Turn on translation for all users (Admin/Mod only)
    !translate off ALL - Turn off translation for all users (Admin/Mod only)
    !translate help - Show help information about commands
    """
    # Special case for help command
    if state.lower() == "help":
        await send_help_embed(ctx)
        return
        
    state = state.lower()
    if state not in ["on", "off"]:
        await ctx.send("Invalid state. Use 'on' or 'off' or 'help'.")
        return
    
    enabled = state == "on"
    message = ""
    
    # Self toggle (no target specified)
    if target is None:
        user_id = str(ctx.author.id)
        if user_id in user_langs:
            user_langs[user_id]["enabled"] = enabled
            message = f"Translation turned {state} for yourself."
            logger.info(f"Translation {state} for user {ctx.author.display_name}")
        else:
            await ctx.send("You need to set a language preference first with !setlang")
            return
    
    # Admin/Mod operations (target is specified)
    elif ctx.author.guild_permissions.administrator or ctx.author.guild_permissions.manage_messages:
        if target.upper() == "ALL":
            # Toggle for all users
            for user_id in user_langs:
                user_langs[user_id]["enabled"] = enabled
            message = f"Translation turned {state} for all users."
            logger.info(f"Translation {state} for ALL users by {ctx.author.display_name}")
        
        # Channel mention
        elif target.startswith('<#') and target.endswith('>'):
            channel_id = str(target[2:-1])
            channel_settings[channel_id] = enabled
            save_channel_settings(channel_settings)
            
            # Get channel name for the message
            try:
                channel = await bot.fetch_channel(int(channel_id))
                channel_name = channel.name if channel else channel_id
                message = f"Translation turned {state} for channel #{channel_name}."
                logger.info(f"Translation {state} for channel #{channel_name} by {ctx.author.display_name}")
            except Exception as e:
                message = f"Translation turned {state} for the specified channel."
                logger.error(f"Error fetching channel name: {e}")
            
        # User mention
        elif target.startswith('<@') and target.endswith('>'):
            try:
                # Extract user ID from mention
                target_id = str(target[2:-1].replace('!', ''))
                if target_id in user_langs:
                    user_langs[target_id]["enabled"] = enabled
                    user = await bot.fetch_user(int(target_id))
                    user_name = user.display_name if user else target_id
                    message = f"Translation turned {state} for {user_name}."
                    logger.info(f"Translation {state} for user {user_name} by {ctx.author.display_name}")
                else:
                    await ctx.send(f"User has no language preference set. Use !setlang first.")
                    return
            except Exception as e:
                await ctx.send(f"Error processing user mention: {str(e)}")
                logger.error(f"Error processing mention: {e}")
                return
        else:
            await ctx.send("Invalid target. Use @username, #channel, or ALL.")
            return
    else:
        await ctx.send("You need administrator permissions to change translation settings for others.")
        return
    
    save_user_langs(user_langs)
    await ctx.send(message)

@bot.command(name='bothelp', aliases=['bh'])
async def help_command(ctx):
    """Show help information about the bot commands"""
    await send_help_embed(ctx)

# Function to send help in both English and Japanese using markdown
async def send_help_embed(ctx):
    """Send help information in both English and Japanese"""
    help_text = """# Translation Bot Help

## User Commands

**!mylang**
Check your current language preferences

**!translate on/off**
Turn translation on or off for yourself

**!translate help**
Show this help message in English and Japanese

**!bothelp**
Alternative command to show this help message

## Admin Commands

**!setlang @user from_lang to_lang**
Set a user's translation languages (Admin/Mod only)
Example: `!setlang @User en ja` - Translates from English to Japanese
Use `auto` for source language to auto-detect

**!translate on/off @user**
Turn translation on or off for a specified user

**!translate on/off #channel**
Turn translation on or off for a specified channel

**!translate on/off ALL**
Turn translation on or off for all users

## Inline Translation

Use `#TL` prefix for manual translation:
```
#TL en ja
Your message here
```

Use `#noTL` prefix to skip translation for a specific message.

## Features
- Automatic translation based on user preferences
- Manual translation with `#TL` prefix
- Skip translation with `#noTL` prefix
- Translation statistics tracking
- Smart handling of edited and deleted messages
- Preserves markdown, emojis, and user mentions
- Appropriate formality levels for Asian languages (敬語, 존댓말, 敬语)
- Ignores empty messages (image-only posts, etc.)
- Automatic text length limits for API safety
- Robust error handling and message validation

## Language Codes
- `en` - English
- `ja` - Japanese
- `ko` - Korean
- `zh` - Chinese
- `es` - Spanish
- `fr` - French
- `de` - German
- `it` - Italian
- `pt` - Portuguese
- `ru` - Russian
"""

    jp_help_text = """# 翻訳ボット ヘルプ

## ユーザーコマンド

**!mylang**
現在の言語設定を確認します

**!translate on/off**
自分の翻訳機能をオン/オフにします

**!translate help**
このヘルプメッセージを英語と日本語で表示します

**!bothelp**
このヘルプメッセージを表示する代替コマンド

## 管理者コマンド

**!setlang @ユーザー from_lang to_lang**
ユーザーの翻訳言語を設定します（管理者/モデレーターのみ）
例: `!setlang @ユーザー en ja` - 英語から日本語に翻訳
ソース言語を自動検出するには `auto` を使用してください

**!translate on/off @ユーザー**
指定したユーザーの翻訳機能をオン/オフにします

**!translate on/off #チャンネル**
指定したチャンネルの翻訳機能をオン/オフにします

**!translate on/off ALL**
すべてのユーザーの翻訳機能をオン/オフにします

## インライン翻訳

`#TL` プレフィックスで手動翻訳:
```
#TL en ja
メッセージをここに
```

`#noTL` プレフィックスで特定のメッセージの翻訳をスキップ。

## 機能
- ユーザー設定に基づく自動翻訳
- `#TL` プレフィックスによる手動翻訳
- `#noTL` プレフィックスによる翻訳スキップ
- 翻訳統計の追跡
- 編集・削除されたメッセージのスマート処理
- マークダウン、絵文字、メンションの保持
- アジア言語の適切な敬語レベル（敬語、존댓말、敬语）
- 空のメッセージを無視（画像のみの投稿など）
- APIの安全性のための自動テキスト長さの制限
- 堅牢なエラー処理とメッセージの検証

## 言語コード
- `en` - 英語
- `ja` - 日本語
- `ko` - 韓国語
- `zh` - 中国語
- `es` - スペイン語
- `fr` - フランス語
- `de` - ドイツ語
- `it` - イタリア語
- `pt` - ポルトガル語
- `ru` - ロシア語
"""

    # Send English help
    await ctx.send(help_text)
    # Send Japanese help
    await ctx.send(jp_help_text)

@set_language.error
async def set_language_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You need administrator permissions to use this command.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Usage: !setlang @user from_lang to_lang")
    else:
        await ctx.send(f"An error occurred: {str(error)}")
        logger.error(f"Command error: {error}")

@translate_command.error
async def translate_command_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Usage: !translate on/off [@user, #channel, or ALL] or !translate help")
    else:
        await ctx.send(f"An error occurred: {str(error)}")
        logger.error(f"Command error: {error}")

@bot.event
async def on_message(message):
    # Process commands first
    await bot.process_commands(message)
    
    # Skip if message is from a bot
    if message.author.bot:
        return
    
    # Only process messages in text channels
    if not isinstance(message.channel, discord.TextChannel):
        return
    
    # Skip if message content is empty or only whitespace (e.g., image-only messages)
    content = message.content.strip()
    if not content:
        return
    
    # Check for #noTL prefix to skip translation
    if content.startswith('#noTL'):
        return
    
    # Check for manual translation request with #TL prefix
    if content.startswith('#TL '):
        try:
            # Check if the command is reasonable length to prevent abuse
            if len(content) > 8000:  # Reasonable limit for Discord messages
                await message.reply("Message too long for translation. Please break it into smaller parts.")
                return
            
            # Try to parse the language pattern
            first_line = content.split('\n', 1)[0]  # Get first line
            rest_of_message = content[len(first_line):].strip() if '\n' in content else ''
            
            # Parse language codes - format: #TL from_lang to_lang
            parts = first_line[4:].strip().split()  # Skip the #TL prefix
            if len(parts) >= 2:
                from_lang = parts[0]
                to_lang = parts[1]
                
                # Basic validation for language codes (should be 2-5 characters, letters only)
                if not (2 <= len(from_lang) <= 5 and from_lang.replace('-', '').isalpha()):
                    await message.reply("Invalid source language code. Use standard language codes like 'en', 'ja', 'zh-CN', etc.")
                    return
                if not (2 <= len(to_lang) <= 5 and to_lang.replace('-', '').isalpha()):
                    await message.reply("Invalid target language code. Use standard language codes like 'en', 'ja', 'zh-CN', etc.")
                    return
                
                # Use the rest of the message after the first line, or if no newline, skip translation
                if rest_of_message or '\n' in content:
                    # Translate the message
                    await translate_and_send(message, from_lang, to_lang, rest_of_message)
                else:
                    await message.reply("Please provide text to translate after the language codes on a new line.")
                # Skip regular translation since we've done manual translation
                return
            else:
                await message.reply("Please provide both source and target language codes. Format: `#TL from_lang to_lang\\nyour message here`")
                return
        
        except Exception as e:
            logger.error(f"Error processing manual translation pattern: {e}")
            await message.reply("Sorry, I couldn't process your translation request. Format: `#TL from_lang to_lang\\nyour message here`")
            return
    
    # Skip if message is a command
    if message.content.startswith('!'):
        return
    
    # Check if channel has translation disabled
    channel_id = str(message.channel.id)
    if channel_id in channel_settings and not channel_settings[channel_id]:
        return
    
    # Check if user has language preference and translation is enabled
    user_id = str(message.author.id)
    user_name = message.author.display_name
    user_prefs = user_langs.get(user_id, {})
    
    if user_prefs and user_prefs.get("enabled", False):
        from_lang = user_prefs.get("from_lang")
        to_lang = user_prefs.get("to_lang")
        
        if from_lang and to_lang:
            await translate_and_send(message, from_lang, to_lang, message.content)

# Helper function to translate text and send response
async def translate_and_send(message, from_lang, to_lang, text):
    try:
        # Skip if text is empty or only whitespace
        if not text or not text.strip():
            logger.warning(f"Empty text provided for translation by user {message.author.display_name}")
            return
        
        # Truncate very long messages to avoid API limits
        text = text.strip()
        if len(text) > 4000:  # Keep reasonable limit for API and Discord embeds
            text = text[:4000] + "..."
            logger.info(f"Truncated long message for translation by user {message.author.display_name}")
        
        # Call Gemini API for translation
        prompt = f"""Translate the following text from {from_lang} to {to_lang}.
Context: This is a Discord message, so preserve all markdown formatting, emojis, and user mentions.
Requirements:
- Output ONLY the translation text
- No explanations or quotation marks
- No prefixes like 'the translation is'
- Preserve all markdown formatting
- Keep all emojis and user mentions intact
- Maintain the same tone and formality level as the original
- For Japanese translations, use appropriate Keigo (敬語) when translating to Japanese
- For Korean translations, use appropriate 존댓말 when translating to Korean
- For Chinese translations, use appropriate 敬语 when translating to Chinese

Message to translate:
{text}"""
        response = model.generate_content(prompt)
        
        # Get translated message
        translated_text = response.text.strip() if response.text else ""
        if translated_text:
            # Ensure the translated text fits in Discord embed (max 4096 characters for description)
            if len(translated_text) > 4096:
                translated_text = translated_text[:4093] + "..."
            
            # Create an embed for the translation
            embed = discord.Embed(
                description=translated_text,
                color=discord.Color.blue()
            )
            
            # Set the author with user's name and avatar
            embed.set_author(
                name=message.author.display_name,
                icon_url=message.author.display_avatar.url
            )
            
            # Add language information to the footer
            embed.set_footer(text=f"Translated from {from_lang} to {to_lang}")
            
            sent_message = None
            # Check if original message is a reply to another message
            if message.reference and message.reference.message_id:
                try:
                    # Try to fetch the message that was being replied to
                    referenced_message = await message.channel.fetch_message(message.reference.message_id)
                    # Reply to the same message as the original
                    sent_message = await referenced_message.reply(embed=embed)
                except Exception as e:
                    # If fetching the referenced message fails, send a regular message
                    logger.error(f"Error fetching referenced message: {e}")
                    sent_message = await message.channel.send(embed=embed)
            else:
                # Not a reply, so send a regular message to the channel (not a reply)
                sent_message = await message.channel.send(embed=embed)
            
            # Store the message pair for tracking edits/deletes
            if sent_message:
                message_pairs[str(message.id)] = str(sent_message.id)
                save_message_pairs(message_pairs)
            
            logger.info(f"Translated message for user {message.author.display_name} from {from_lang} to {to_lang}")
            #also log the original message and the translated message
            logger.info(f"Original message: {text}")
            logger.info(f"Translated message: {translated_text}")
        else:
            logger.warning(f"Empty translation result for user {message.author.display_name}")
    except Exception as e:
        logger.error(f"Translation error: {e}")
        # Only send error message if it's not due to empty text
        if text and text.strip():
            await message.channel.send("Sorry, I couldn't translate that message.")

@bot.event
async def on_message_edit(before, after):
    """Handler for message edit events - updates translations if the original message was edited"""
    # Skip if message is from a bot
    if after.author.bot:
        return
    
    # Skip if message content is empty or only whitespace
    if not after.content or not after.content.strip():
        return
    
    # Check if this was a message we previously translated
    if str(after.id) in message_pairs:
        # This is a message that we've translated before
        try:
            # Get the channel and message where our translation is
            channel = after.channel
            translated_msg_id = int(message_pairs[str(after.id)])
            
            try:
                # Try to fetch our translation message
                translated_msg = await channel.fetch_message(translated_msg_id)
                
                # Check if message content actually changed
                if before.content != after.content:
                    # Get user's translation settings if this is an automatic translation
                    user_id = str(after.author.id)
                    user_name = after.author.display_name
                    user_prefs = user_langs.get(user_id, {})
                    
                    # Check if content starts with #TL for manual translation
                    content = after.content.strip()
                    if content.startswith('#TL '):
                        try:
                            # Parse the language pattern - same logic as on_message
                            first_line = content.split('\n', 1)[0]
                            rest_of_message = content[len(first_line):].strip() if '\n' in content else ''
                            
                            # Parse language codes - format: #TL from_lang to_lang
                            parts = first_line[4:].strip().split()
                            if len(parts) >= 2:
                                from_lang = parts[0]
                                to_lang = parts[1]
                                
                                # Use the rest of the message after the first line
                                if rest_of_message or '\n' in content:
                                    # Update the translation
                                    await update_translation(after, translated_msg, from_lang, to_lang, rest_of_message)
                        except Exception as e:
                            logger.error(f"Error processing edited manual translation: {e}")
                    
                    # Check for automatic translation based on user settings
                    elif user_prefs and user_prefs.get("enabled", False):
                        from_lang = user_prefs.get("from_lang")
                        to_lang = user_prefs.get("to_lang")
                        
                        if from_lang and to_lang:
                            # Update the translation
                            await update_translation(after, translated_msg, from_lang, to_lang, after.content)
            
            except discord.NotFound:
                # Message was deleted or otherwise not found
                logger.warning(f"Translated message not found for update: {translated_msg_id}")
                # Remove the entry from our tracking
                del message_pairs[str(after.id)]
                save_message_pairs(message_pairs)
        
        except Exception as e:
            logger.error(f"Error handling message edit: {e}")

@bot.event
async def on_message_delete(message):
    """Handler for message delete events - deletes translations if the original message was deleted"""
    # Check if this was a message we previously translated
    if str(message.id) in message_pairs:
        try:
            # Get the channel and message where our translation is
            channel = message.channel
            translated_msg_id = int(message_pairs[str(message.id)])
            
            try:
                # Try to fetch and delete our translation
                translated_msg = await channel.fetch_message(translated_msg_id)
                await translated_msg.delete()
                logger.info(f"Deleted translation for deleted message {message.id}")
            except discord.NotFound:
                logger.warning(f"Translated message already deleted: {translated_msg_id}")
            finally:
                # Remove the entry from our tracking
                del message_pairs[str(message.id)]
                save_message_pairs(message_pairs)
        
        except Exception as e:
            logger.error(f"Error handling message delete: {e}")

# Helper function to update translation for edited messages
async def update_translation(message, translated_msg, from_lang, to_lang, text):
    try:
        # Skip if text is empty or only whitespace
        if not text or not text.strip():
            logger.warning(f"Empty text provided for translation update by user {message.author.display_name}")
            return
        
        # Truncate very long messages to avoid API limits
        text = text.strip()
        if len(text) > 4000:  # Keep reasonable limit for API and Discord embeds
            text = text[:4000] + "..."
            logger.info(f"Truncated long message for translation update by user {message.author.display_name}")
        
        # Call Gemini API for translation
        prompt = f"""Translate the following text from {from_lang} to {to_lang}.
Context: This is a Discord message, so preserve all markdown formatting, emojis, and user mentions.
Requirements:
- Output ONLY the translation text
- No explanations or quotation marks
- No prefixes like 'the translation is'
- Preserve all markdown formatting
- Keep all emojis and user mentions intact
- Maintain the same tone and formality level as the original
- For Japanese translations, use appropriate Keigo (敬語) when translating to Japanese
- For Korean translations, use appropriate 존댓말 when translating to Korean
- For Chinese translations, use appropriate 敬语 when translating to Chinese

Message to translate:
{text}"""
        response = model.generate_content(prompt)
        
        # Get translated message
        translated_text = response.text.strip() if response.text else ""
        if translated_text:
            # Ensure the translated text fits in Discord embed (max 4096 characters for description)
            if len(translated_text) > 4096:
                translated_text = translated_text[:4093] + "..."
            
            # Update the embed with new translation
            updated_embed = discord.Embed(
                description=translated_text,
                color=discord.Color.blue()
            )
            
            # Set the author with user's name and avatar
            updated_embed.set_author(
                name=message.author.display_name,
                icon_url=message.author.display_avatar.url
            )
            
            # Add language information to the footer (consistent with translate_and_send)
            updated_embed.set_footer(text=f"Translated from {from_lang} to {to_lang}")
            
            # Edit the message with the updated translation
            await translated_msg.edit(embed=updated_embed)
            
            logger.info(f"Updated translation for edited message {message.id}")
            logger.info(f"New original message: {text}")
            logger.info(f"New translated message: {translated_text}")
        else:
            logger.warning(f"Empty translation result for edited message {message.id}")
    except Exception as e:
        logger.error(f"Error updating translation: {e}")


# Run the bot
if __name__ == "__main__":
    if not DISCORD_TOKEN or not GEMINI_API_KEY:
        logger.error("Missing environment variables. Please check your .env file")
        exit(1)
    
    # Migrate old format to new format if needed
    for user_id, value in list(user_langs.items()):
        if isinstance(value, str):
            user_langs[user_id] = {"from_lang": "auto", "to_lang": value, "enabled": True}
        elif isinstance(value, dict) and "lang" in value:
            # Migrate from single lang to from_lang/to_lang
            user_langs[user_id] = {
                "from_lang": "auto", 
                "to_lang": value["lang"],
                "enabled": value.get("enabled", True)
            }
    save_user_langs(user_langs)
    
    bot.run(DISCORD_TOKEN) 