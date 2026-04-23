import os
import asyncio
import base64
import json
import logging
from datetime import datetime
import discord
import platform
from discord import ui
from discord.ext import commands
from dotenv import load_dotenv
from google import genai
from google.genai import types as genai_types
from io import BytesIO

# Load locales
locales = {}
try:
    if os.path.exists("locales"):
        for filename in os.listdir("locales"):
            if filename.endswith(".json"):
                lang_code = filename[:-5]
                with open(os.path.join("locales", filename), "r", encoding="utf-8") as f:
                    locales[lang_code] = json.load(f)
except Exception as e:
    print(f"Error loading locales: {e}")

def get_locale_text(lang, key, default=""):
    if lang in locales and key in locales[lang]:
        return locales[lang][key]
    if "en" in locales and key in locales["en"]:
        return locales["en"][key]
    return default


# Configure logging (console + daily file with date in filename)
logger = logging.getLogger('translation-bot')
if not logger.handlers:
    logger.setLevel(logging.INFO)
    log_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(log_format)
    logger.addHandler(console_handler)

    # File handler with date in filename
    date_str = datetime.now().strftime('%Y-%m-%d')
    file_handler = logging.FileHandler(f'translation-bot-{date_str}.log', encoding='utf-8', mode='a')
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(log_format)
    logger.addHandler(file_handler)

    logger.propagate = False

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

# New config file for bot settings
CONFIG_FILE = 'settings/bot_config.json'

def load_bot_config():
    """Load bot configuration from JSON file."""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                if 'model_name' not in config:
                    # A reasonable default based on what was hardcoded before
                    config['model_name'] = 'gemini-2.0-flash'
                if 'model_status_channel_id' not in config:
                    config['model_status_channel_id'] = 1417437633956544582
                return config
        else:
            return {'model_name': 'gemini-2.0-flash'}
    except Exception as e:
        logger.error(f"Error loading bot config: {e}")
        return {'model_name': 'gemini-2.0-flash'}

def save_bot_config(config):
    """Save bot configuration to JSON file."""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving bot config: {e}")

bot_config = load_bot_config()

# Configure Gemini API client
client = genai.Client(api_key=GEMINI_API_KEY)
logger.info(f"Initialized with model: {bot_config['model_name']}")

# --- Helpers for AI content generation (text and images) ---
async def generate_ai_content(model_id: str, prompt: str):
    """Generate content using the Google GenAI client. Returns (texts, images).

    texts: list[str]
    images: list[tuple[bytes, str]]  # (data, mime_type)
    """
    try:
        logger.info(
            f"generate_ai_content: model_id={model_id}, "
            f"prompt_len={len(prompt) if isinstance(prompt, str) else 'n/a'}, is_image_model={'image' in (model_id or '')}"
        )
    except Exception:
        pass

    try:
        resp = await client.aio.models.generate_content(
            model=model_id,
            contents=[prompt],
        )

        out_texts = []
        out_images = []

        def _add_image_from_inline(inline_obj):
            try:
                data = inline_obj.get('data') if isinstance(inline_obj, dict) else getattr(inline_obj, 'data', None)
                if data is None:
                    return
                if isinstance(data, str):
                    try:
                        data = base64.b64decode(data)
                    except Exception:
                        return
                mime = inline_obj.get('mime_type') if isinstance(inline_obj, dict) else getattr(inline_obj, 'mime_type', 'image/png')
                out_images.append((data, mime or 'image/png'))
            except Exception:
                return

        def _walk(obj):
            if obj is None:
                return
            if isinstance(obj, dict):
                text_val = obj.get('text')
                if isinstance(text_val, str):
                    out_texts.append(text_val)
                if 'inline_data' in obj and isinstance(obj['inline_data'], (dict,)):
                    _add_image_from_inline(obj['inline_data'])
                for v in obj.values():
                    _walk(v)
            elif isinstance(obj, (list, tuple)):
                for item in obj:
                    _walk(item)
            else:
                try:
                    if hasattr(obj, 'text') and isinstance(obj.text, str):
                        out_texts.append(obj.text)
                    inline = getattr(obj, 'inline_data', None)
                    if inline is not None:
                        if isinstance(inline, dict):
                            _add_image_from_inline(inline)
                        else:
                            _add_image_from_inline({'data': getattr(inline, 'data', None), 'mime_type': getattr(inline, 'mime_type', 'image/png')})
                except Exception:
                    pass

        try:
            if hasattr(resp, 'model_dump'):
                _walk(resp.model_dump())
            elif hasattr(resp, 'to_dict'):
                _walk(resp.to_dict())
            else:
                _walk(resp)
        except Exception:
            _walk(resp)

        try:
            logger.info(f"generate_ai_content parsed: texts={len(out_texts)}, images={len(out_images)}")
            for i, (data, mime) in enumerate(out_images[:3]):
                logger.info(f"image[{i}]: bytes={len(data) if isinstance(data, (bytes,bytearray)) else 'n/a'}, mime={mime}")
        except Exception:
            pass

        return out_texts, out_images

    except Exception as e:
        logger.error(f"Content generation failed: {e}")
        return [], []

# Setup bot with command prefix
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Language preferences file
LANG_FILE = 'settings/user_langs.json'
CHANNEL_FILE = 'settings/channel_settings.json'
MESSAGE_PAIRS_FILE = 'settings/message_pairs.json'

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

# A dictionary of supported languages for the UI select menu
LANGUAGES = {
    "en": "English",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "ru": "Russian",
    "ar": "Arabic",
    "hi": "Hindi"
}

# --- UI Views for Commands ---

class LanguageSelect(ui.Select):
    """A select menu for choosing a language."""
    def __init__(self, placeholder: str, custom_id: str):
        options = [
            discord.SelectOption(label=name, value=code) for code, name in LANGUAGES.items()
        ]
        super().__init__(placeholder=placeholder, custom_id=custom_id, options=options)

class SetLangView(ui.View):
    def __init__(self, member, author):
        super().__init__(timeout=180)
        self.member = member
        self.author = author
        self.from_lang = None
        self.to_lang = None

        async def from_lang_callback(interaction: discord.Interaction):
            if interaction.user.id != self.author.id:
                await interaction.response.send_message("This is not for you!", ephemeral=True)
                return
            self.from_lang = interaction.data['values'][0]
            await interaction.response.defer()

        async def to_lang_callback(interaction: discord.Interaction):
            if interaction.user.id != self.author.id:
                await interaction.response.send_message("This is not for you!", ephemeral=True)
                return
            self.to_lang = interaction.data['values'][0]
            await interaction.response.defer()
        
        from_select = LanguageSelect(placeholder="Select source language...", custom_id="from_lang")
        to_select = LanguageSelect(placeholder="Select target language...", custom_id="to_lang")
        
        from_select.callback = from_lang_callback
        to_select.callback = to_lang_callback
        
        self.add_item(from_select)
        self.add_item(to_select)

    @ui.button(label="Save", style=discord.ButtonStyle.primary, row=2)
    async def save(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("This is not for you!", ephemeral=True)
            return

        if not self.from_lang or not self.to_lang:
            await interaction.response.send_message("Please select both a source and target language.", ephemeral=True)
            return

        user_id = str(self.member.id)
        if user_id not in user_langs:
            user_langs[user_id] = {
                "from_lang": self.from_lang,
                "to_lang": self.to_lang,
                "enabled": True
            }
        else:
            user_langs[user_id]["from_lang"] = self.from_lang
            user_langs[user_id]["to_lang"] = self.to_lang
        
        save_user_langs(user_langs)
        
        embed = discord.Embed(
            description=f"Language preference for **{self.member.display_name}** set to translate from `{self.from_lang}` to `{self.to_lang}`.",
            color=discord.Color.green()
        )
        await interaction.response.edit_message(embed=embed, view=None)
        logger.info(f"Set language for user {user_id} from {self.from_lang} to {self.to_lang} by {self.author.display_name}")

class AIPromptModal(ui.Modal):
    def __init__(self, model_id: str):
        super().__init__(title='Enter your prompt', timeout=None)
        self.model_id = model_id
        
        text_style_cls = getattr(discord, 'TextStyle', None)
        input_text_style_cls = getattr(discord, 'InputTextStyle', None)
        style_value = None
        if text_style_cls is not None:
            style_value = getattr(text_style_cls, 'paragraph', getattr(text_style_cls, 'long', None))
        if style_value is None and input_text_style_cls is not None:
            style_value = getattr(input_text_style_cls, 'paragraph', getattr(input_text_style_cls, 'long', None))
        
        if style_value is not None:
            self.prompt_input = ui.InputText(
                label="Prompt",
                style=style_value,
                placeholder="Enter your prompt here..."
            )
        else:
            self.prompt_input = ui.InputText(
                label="Prompt",
                placeholder="Enter your prompt here..."
            )
        self.add_item(self.prompt_input)

    async def _handle_submit(self, interaction: discord.Interaction):
        prompt = self.prompt_input.value
        # Acknowledge the modal submission: try sending a placeholder message first, fallback to defer
        try:
            await interaction.response.send_message(f"⌛ Running prompt with `{self.model_id}`...")
        except Exception as e:
            logger.warning(f"Could not send initial modal response: {e}")
            try:
                await interaction.response.defer()
            except Exception as e2:
                logger.warning(f"Could not defer modal interaction: {e2}")

        try:
            texts, images = await generate_ai_content(self.model_id, prompt)
            try:
                logger.info(f"modal submit: got texts={len(texts)}, images={len(images)} for model={self.model_id}")
            except Exception:
                pass

            # Prepare cleaned text output
            combined_text = "\n\n".join([t for t in texts if t]) if texts else ""
            cleaned_text = combined_text.replace("(continued)", "").replace("\n(continued)\n", "\n").strip()

            header = (
                f"**Model:** `{self.model_id}`\n\n"
                f"**Prompt:**\n```\n{prompt[:1020]}\n```\n\n"
            )

            # Send text first (if any)
            if cleaned_text:
                text_payload = f"{header}{cleaned_text}"
                if len(text_payload) <= 2000:
                    await interaction.followup.send(content=text_payload)
                else:
                    await interaction.followup.send(content=header)
                    for i in range(0, len(cleaned_text), 2000):
                        chunk = cleaned_text[i:i+2000]
                        await interaction.followup.send(content=chunk)
            else:
                # If no text, still send the header to show context
                await interaction.followup.send(content=header)

            # Send images (if any)
            for idx, (data, mime) in enumerate(images):
                # Default filename based on mime
                ext = 'png'
                if mime and '/' in mime:
                    ext = mime.split('/')[-1]
                filename = f"generated_image_{idx + 1}.{ext}"
                await interaction.followup.send(file=discord.File(fp=BytesIO(data), filename=filename))

        except Exception as e:
            logger.error(f"Error running AI prompt: {e}")
            try:
                await interaction.followup.send(content="Sorry, an error occurred while running the prompt.")
            except Exception as send_err:
                logger.error(f"Also failed to send error followup: {send_err}")

    # Use only one handler to avoid double responses; py-cord uses callback
    async def callback(self, interaction: discord.Interaction):
        await self._handle_submit(interaction)


class AIModelSelect(ui.Select):
    """A select menu for choosing a model for the AI command."""
    def __init__(self, models):
        options = [
            discord.SelectOption(
                label=model['display_name'],
                value=model['id'],
                description=model['description']
            ) for model in models
        ]
        if not options:
            options.append(discord.SelectOption(label="No models found", value="no_models", description="Could not fetch models."))
        super().__init__(placeholder="Choose a model...", options=options)

    async def callback(self, interaction: discord.Interaction):
        selected_model_id = self.values[0]
        if selected_model_id == "no_models":
            await interaction.response.send_message("No models available.", ephemeral=True)
            return
        await interaction.response.send_modal(AIPromptModal(model_id=selected_model_id))


class AIView(ui.View):
    def __init__(self, models, author_id):
        super().__init__(timeout=180)
        self.add_item(AIModelSelect(models))
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This is not for you!", ephemeral=True)
            return False
        return True

class MyLangView(ui.View):
    def __init__(self, author_id):
        super().__init__(timeout=180)
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This is not for you!", ephemeral=True)
            return False
        return True

    async def _update_embed(self, interaction: discord.Interaction, enabled: bool):
        user_id = str(self.author_id)
        user_langs[user_id]["enabled"] = enabled
        save_user_langs(user_langs)
        
        user_prefs = user_langs.get(user_id, {})
        from_lang = user_prefs.get("from_lang", "Not set")
        to_lang = user_prefs.get("to_lang", "Not set")
        status = "✅ Enabled" if enabled else "❌ Disabled"
        
        embed = discord.Embed(
            title="Your Language Settings",
            color=discord.Color.green() if enabled else discord.Color.orange()
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.add_field(name="Source Language", value=f"`{from_lang}`", inline=True)
        embed.add_field(name="Target Language", value=f"`{to_lang}`", inline=True)
        embed.add_field(name="Status", value=status, inline=False)

        await interaction.response.edit_message(embed=embed, view=self)

    @ui.button(label="Enable Translation", style=discord.ButtonStyle.green)
    async def turn_on(self, interaction: discord.Interaction, button: ui.Button):
        await self._update_embed(interaction, True)

    @ui.button(label="Disable Translation", style=discord.ButtonStyle.red)
    async def turn_off(self, interaction: discord.Interaction, button: ui.Button):
        await self._update_embed(interaction, False)

class TranslateSelfView(ui.View):
    def __init__(self, author_id):
        super().__init__(timeout=180)
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This is not for you!", ephemeral=True)
            return False
        return True

    @ui.button(label="Turn On", style=discord.ButtonStyle.green)
    async def turn_on(self, interaction: discord.Interaction, button: ui.Button):
        user_id = str(self.author_id)
        if user_id in user_langs:
            user_langs[user_id]["enabled"] = True
            save_user_langs(user_langs)
            embed = discord.Embed(description="✅ Translation turned **on** for yourself.", color=discord.Color.green())
            await interaction.response.edit_message(embed=embed, view=None)
        else:
            embed = discord.Embed(description="You need to set a language preference first. Use `!setlang` (admin).", color=discord.Color.red())
            await interaction.response.edit_message(embed=embed, view=None)

    @ui.button(label="Turn Off", style=discord.ButtonStyle.red)
    async def turn_off(self, interaction: discord.Interaction, button: ui.Button):
        user_id = str(self.author_id)
        if user_id in user_langs:
            user_langs[user_id]["enabled"] = False
            save_user_langs(user_langs)
            embed = discord.Embed(description="❌ Translation turned **off** for yourself.", color=discord.Color.orange())
            await interaction.response.edit_message(embed=embed, view=None)
        else:
            embed = discord.Embed(description="You need to set a language preference first. Use `!setlang` (admin).", color=discord.Color.red())
            await interaction.response.edit_message(embed=embed, view=None)

async def update_model_status_channel():
    """Updates the name of the configured voice channel to reflect the current model."""
    channel_id = bot_config.get('model_status_channel_id')
    if channel_id:
        try:
            channel = bot.get_channel(int(channel_id))
            if channel and isinstance(channel, discord.VoiceChannel):
                model_name = bot_config.get('model_name', 'N/A')
                prefix = "🤖 "
                # Truncate model name if the total channel name would exceed 100 chars
                if len(prefix) + len(model_name) > 100:
                    max_len = 100 - len(prefix) - 3  # Account for "..."
                    model_name = model_name[:max_len] + "..."
                new_name = f"{prefix}{model_name}"

                await channel.edit(name=new_name)
                logger.info(f"Updated status channel '{channel.name}' to '{new_name}'")
            elif channel:
                logger.warning(f"Channel {channel_id} is not a voice channel.")
            else:
                logger.warning(f"Status channel with ID {channel_id} not found.")
        except discord.Forbidden:
            logger.error(f"Bot lacks permissions to edit channel {channel_id}.")
        except Exception as e:
            logger.error(f"Failed to update status channel {channel_id}: {e}")

@bot.event
async def on_ready():
    logger.info(f"{bot.user.name} has connected to Discord!")
    await update_model_status_channel()

    # Send startup message
    try:
        channel_id = 1417488482548580445
        channel = bot.get_channel(channel_id)
        if channel:
            device_name = platform.node()
            await channel.send(f"Bot is online and running on **{device_name}**.")
            logger.info(f"Sent startup message to channel {channel_id}")
        else:
            logger.warning(f"Could not find channel {channel_id} to send startup message.")
    except Exception as e:
        logger.error(f"Failed to send startup message: {e}")

@bot.command(name='setlang')
@commands.has_permissions(administrator=True)
async def set_language(ctx, member: discord.Member, from_lang: str = None, to_lang: str = None):
    """Set the language translation preferences for a user (Admin/Mod only)"""
    
    # Existing logic for command-line usage
    if from_lang and to_lang:
        try:
            user_id = str(member.id)
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
            embed = discord.Embed(
                description=f"Language preference for **{member.display_name}** set to translate from `{from_lang}` to `{to_lang}`.",
                color=discord.Color.green()
            )
            await ctx.send(embed=embed)
            logger.info(f"Set language for user {user_id} from {from_lang} to {to_lang}")
        except Exception as e:
            embed = discord.Embed(
                title="Error",
                description=f"Failed to set language: {str(e)}",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            logger.error(f"Error setting language: {e}")
            return

    # New UI-based logic
    embed = discord.Embed(
        title=f"Set Language for {member.display_name}",
        description="Select the source and target languages below.",
        color=discord.Color.blue()
    )
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
    await ctx.send(embed=embed, view=SetLangView(member, ctx.author))

@set_language.error
async def set_language_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(description="You need administrator permissions to use this command.", color=discord.Color.red())
        await ctx.send(embed=embed)
    elif isinstance(error, commands.MissingRequiredArgument):
        embed = discord.Embed(description="Usage: `!setlang @user [from_lang] [to_lang]`\nOr use `!setlang @user` to open the interactive menu.", color=discord.Color.red())
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(title="Error", description=f"An error occurred: {str(error)}", color=discord.Color.red())
        await ctx.send(embed=embed)
        logger.error(f"Command error: {error}")

@bot.command(name='mylang')
async def my_language(ctx):
    """Check your current language preference"""
    user_id = str(ctx.author.id)
    user_prefs = user_langs.get(user_id, {})

    if user_prefs:
        from_lang = user_prefs.get("from_lang", "Not set")
        to_lang = user_prefs.get("to_lang", "Not set")
        enabled = user_prefs.get("enabled", False)
        status = "✅ Enabled" if enabled else "❌ Disabled"
        
        embed = discord.Embed(
            title="Your Language Settings",
            color=discord.Color.blue()
        )
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
        embed.add_field(name="Source Language", value=f"`{from_lang}`", inline=True)
        embed.add_field(name="Target Language", value=f"`{to_lang}`", inline=True)
        embed.add_field(name="Status", value=status, inline=False)
        await ctx.send(embed=embed, view=MyLangView(ctx.author.id))
    else:
        embed = discord.Embed(
            description="You don't have a language preference set. Use `!setlang` (admin) to get started.",
            color=discord.Color.orange()
        )
        await ctx.send(embed=embed)

@bot.command(name='translate', aliases=['tl'])
async def translate_command(ctx, state: str = None, target: str = None):
    """Turn translation on or off for a user, channel, or all users"""

    # UI for self-toggle
    if state is None and target is None:
        user_id = str(ctx.author.id)
        if user_id not in user_langs:
            embed = discord.Embed(
                description="You don't have a language preference set. Use `!setlang` (admin) to get started.",
                color=discord.Color.orange()
            )
            await ctx.send(embed=embed)
            return
        
        current_status = user_langs[user_id].get("enabled", False)
        status_text = "enabled" if current_status else "disabled"
        
        embed = discord.Embed(
            title="Manage Your Translation",
            description=f"Your translation is currently **{status_text}**.",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed, view=TranslateSelfView(ctx.author.id))
        return

    # Special case for help command
    if state and state.lower() == "help":
        await send_help_embed(ctx)
        return

    # Existing command logic
    state = state.lower() if state else ''
    if state not in ["on", "off"]:
        embed = discord.Embed(description="Invalid state. Use `on` or `off` or `help`.", color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    enabled = state == "on"
    status_text = "on" if enabled else "off"
    color = discord.Color.green() if enabled else discord.Color.orange()
    embed = discord.Embed(color=color)

    # Self toggle (no target specified)
    if target is None:
        user_id = str(ctx.author.id)
        if user_id in user_langs:
            user_langs[user_id]["enabled"] = enabled
            embed.description = f"Translation turned **{status_text}** for yourself."
            logger.info(f"Translation {status_text} for user {ctx.author.display_name}")
        else:
            embed.description = "You need to set a language preference first with `!setlang`."
            embed.color = discord.Color.red()
            await ctx.send(embed=embed)
            return

    # Admin/Mod operations (target is specified)
    elif ctx.author.guild_permissions.administrator or ctx.author.guild_permissions.manage_messages:
        if target.upper() == "ALL":
            # Toggle for all users
            for user_id in user_langs:
                user_langs[user_id]["enabled"] = enabled
            embed.description = f"Translation turned **{status_text}** for all users."
            logger.info(f"Translation {status_text} for ALL users by {ctx.author.display_name}")

        # Channel mention
        elif target.startswith('<#') and target.endswith('>'):
            channel_id = str(target[2:-1])
            channel_settings[channel_id] = enabled
            save_channel_settings(channel_settings)

            # Get channel name for the message
            try:
                channel = await bot.fetch_channel(int(channel_id))
                channel_name = channel.name if channel else channel_id
                embed.description = f"Translation turned **{status_text}** for channel **#{channel_name}**."
                logger.info(f"Translation {status_text} for channel #{channel_name} by {ctx.author.display_name}")
            except Exception as e:
                embed.description = f"Translation turned **{status_text}** for the specified channel."
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
                    embed.description = f"Translation turned **{status_text}** for **{user_name}**."
                    logger.info(f"Translation {status_text} for user {user_name} by {ctx.author.display_name}")
                else:
                    embed.description = "User has no language preference set. Use `!setlang` first."
                    embed.color = discord.Color.red()
                    await ctx.send(embed=embed)
                    return
            except Exception as e:
                embed.title = "Error"
                embed.description = f"Error processing user mention: {str(e)}"
                embed.color = discord.Color.red()
                await ctx.send(embed=embed)
                logger.error(f"Error processing mention: {e}")
                return
        else:
            embed.description = "Invalid target. Use `@username`, `#channel`, or `ALL`."
            embed.color = discord.Color.red()
            await ctx.send(embed=embed)
            return
    else:
        embed.description = "You need administrator permissions to change translation settings for others."
        embed.color = discord.Color.red()
        await ctx.send(embed=embed)
        return

    save_user_langs(user_langs)
    await ctx.send(embed=embed)

@bot.command(name='bothelp', aliases=['bh'])
async def help_command(ctx):
    """Show help information about the bot commands"""
    await send_help_embed(ctx)

# Function to send help in all available languages
async def send_help_embed(ctx):
    """Send help information in available languages"""
    # Send help for each loaded locale
    if locales:
        for lang, data in locales.items():
            if "help_text" in data:
                await ctx.send(data["help_text"])
    else:
        # Fallback if locales didn't load
        await ctx.send("Error: Help text not found. Please check locales folder.")

# Helper function to get suitable models from the Gemini API
def get_models():
    """Fetches and filters compatible text generation models from the Gemini API."""
    models_list = []
    try:
        for m in client.models.list():
            if 'generateContent' in (m.supported_generation_methods or []):
                # Apply filters from test.py to get stable, non-experimental models
                if "gemini" not in m.name:
                    continue
                if "exp" in m.name:
                    continue
                if "tts" in m.name:
                    continue
                if "preview" in m.name and not "image" in m.name: #include image model
                    continue
                if "001" in m.name:
                    continue
                if "002" in m.name:
                    continue
                if "latest" in m.name:
                    continue

                model_id_for_api = m.name.replace("models/", "")

                models_list.append({
                    'id': model_id_for_api,
                    'display_name': m.display_name,
                    # Truncate description to fit in select option
                    'description': m.description[:100]
                })
    except Exception as e:
        logger.error(f"Could not fetch models from Gemini API: {e}")
    return models_list

# --- UI Classes for Model Selection ---

class ModelSelect(ui.Select):
    """A select menu for choosing a Gemini model."""
    def __init__(self, models):
        options = [
            discord.SelectOption(
                label=model['display_name'],
                value=model['id'],
                description=model['description']
            ) for model in models
        ]
        if not options:
            options.append(discord.SelectOption(
                label="No models found",
                value="no_models",
                description="Could not fetch any compatible models."
            ))

        super().__init__(placeholder="Choose a translation model...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        global bot_config
        selected_model_id = self.values[0]

        if selected_model_id == "no_models":
            await interaction.response.send_message("No models available to select.", ephemeral=True)
            return

        try:
            bot_config['model_name'] = selected_model_id
            save_bot_config(bot_config)

            # Acknowledge the change with an ephemeral message, keeping the view intact
            await interaction.response.send_message(content=f"✅ Translation model updated to `{selected_model_id}`.", ephemeral=True)

            logger.info(f"Model updated to {selected_model_id} by {interaction.user.display_name}")

            # Update the voice channel status
            await update_model_status_channel()

        except Exception as e:
            logger.error(f"Failed to update model to {selected_model_id}: {e}")
            await interaction.response.send_message(f"❌ Sorry, I couldn't switch to that model. Please check the logs.", ephemeral=True)

class ConfigView(ui.View):
    """A view that contains the model selection dropdown."""
    def __init__(self, models):
        super().__init__(timeout=180) # View times out after 3 minutes
        self.add_item(ModelSelect(models))

# --- Bot Configuration Command ---

@bot.command(name='config')
@commands.has_permissions(administrator=True)
async def config(ctx):
    """Configure the translation bot (Admin only)."""
    await ctx.message.delete()
    models = get_models()
    view = ConfigView(models)
    await ctx.send("Please select the Gemini model to use for translations:", view=view)

@config.error
async def config_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You need administrator permissions to use this command.")
    else:
        await ctx.send(f"An error occurred: {str(error)}")
        logger.error(f"Config command error: {error}")

@bot.command(name='setstatuschannel')
@commands.has_permissions(administrator=True)
async def set_status_channel(ctx, channel: discord.VoiceChannel = None):
    """Sets or clears the voice channel for displaying the current model.

    Args:
        channel: The voice channel to use (mention or ID), or none to clear.
    """
    if channel:
        bot_config['model_status_channel_id'] = str(channel.id)
        save_bot_config(bot_config)
        await ctx.send(f"✅ Status channel set to `{channel.name}`.")
        logger.info(f"Status channel set to {channel.id} by {ctx.author.display_name}")
        await update_model_status_channel()  # Update immediately
    else:
        if 'model_status_channel_id' in bot_config:
            old_channel_id = bot_config.pop('model_status_channel_id')
            save_bot_config(bot_config)
            await ctx.send("✅ Status channel configuration has been cleared.")
            logger.info(f"Status channel cleared by {ctx.author.display_name}")
            # Try to reset channel name to something generic
            try:
                old_channel = bot.get_channel(int(old_channel_id))
                if old_channel and isinstance(old_channel, discord.VoiceChannel):
                    await old_channel.edit(name="model-status")  # Reset name
            except Exception as e:
                logger.warning(f"Could not reset name for old status channel {old_channel_id}: {e}")
        else:
            await ctx.send("No status channel is currently set.")

@set_status_channel.error
async def set_status_channel_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You need administrator permissions to use this command.")
    elif isinstance(error, commands.ChannelNotFound):
        await ctx.send("Could not find that voice channel. Please provide a valid voice channel ID or mention.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("Invalid channel provided. Please mention a voice channel or provide its ID.")
    else:
        await ctx.send(f"An error occurred: {str(error)}")
        logger.error(f"Set status channel command error: {error}")

@bot.command(name='status')
@commands.has_permissions(administrator=True)
async def status(ctx):
    """Displays an overview of the bot's translation settings."""
    await ctx.defer()

    embed = discord.Embed(
        title="Translation Bot Status",
        description="Current configuration for members and channels.",
        color=discord.Color.blue()
    )
    embed.set_footer(text=f"Model: {bot_config.get('model_name', 'N/A')}")

    # Member Status
    member_statuses = []
    if user_langs:
        for user_id, settings in user_langs.items():
            member = ctx.guild.get_member(int(user_id))
            name = member.display_name if member else f"User ID: {user_id}"
            from_lang = settings.get('from_lang', 'N/A')
            to_lang = settings.get('to_lang', 'N/A')
            status = "✅" if settings.get('enabled', False) else "❌"
            member_statuses.append(f"**{name}**: `{from_lang}` → `{to_lang}` {status}")
        
        # Split into multiple fields if too long
        member_text = "\n".join(member_statuses)
        if len(member_text) > 1024:
            for i in range(0, len(member_text), 1024):
                chunk = member_text[i:i+1024]
                embed.add_field(name=f"Member Settings (part {i//1024 + 1})", value=chunk, inline=False)
        else:
            embed.add_field(name="Member Settings", value=member_text, inline=False)
    else:
        embed.add_field(name="Member Settings", value="No users configured.", inline=False)

    # Channel Status (sorted by category)
    channel_statuses_by_cat = {}
    if channel_settings:
        for channel_id, enabled in channel_settings.items():
            channel = ctx.guild.get_channel(int(channel_id))
            if channel:
                category = channel.category.name if channel.category else "No Category"
                if category not in channel_statuses_by_cat:
                    channel_statuses_by_cat[category] = []
                
                status = "✅" if enabled else "❌"
                channel_statuses_by_cat[category].append(f"{channel.mention} {status}")

    if channel_statuses_by_cat:
        # Sort categories alphabetically
        sorted_categories = sorted(channel_statuses_by_cat.keys())
        for category in sorted_categories:
            channels = channel_statuses_by_cat[category]
            channel_text = "\n".join(channels)
            embed.add_field(name=f"Category: {category}", value=channel_text, inline=False)
    else:
        embed.add_field(name="Channel Settings", value="No channels configured.", inline=False)
        
    await ctx.send(embed=embed)

@status.error
async def status_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You need administrator permissions to use this command.")
    else:
        await ctx.send(f"An error occurred: {str(error)}")
        logger.error(f"Status command error: {error}")

@bot.command(name='ai')
async def ai_command(ctx):
    """Interactive AI prompt command."""
    await ctx.message.delete()
    models = get_models()
    if not models:
        embed = discord.Embed(
            title="AI Prompt Error",
            description="Could not fetch any AI models at the moment. Please try again later.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    view = AIView(models, ctx.author.id)
    embed = discord.Embed(
        title="AI Prompt",
        description="Please select a model to use for your prompt.",
        color=discord.Color.purple()
    )
    await ctx.send(embed=embed, view=view)


@ai_command.error
async def ai_command_error(ctx, error):
    await ctx.send(f"An error occurred with the AI command: {str(error)}", delete_after=10)
    logger.error(f"AI command error: {error}")

@bot.event
async def on_message(message):
    logger.info(f"Received message from {message.author}: {message.content[:50]}")
    # Process commands first
    await bot.process_commands(message)

    # Skip if message is from a bot
    if message.author.bot:
        logger.info("Skipping message: Author is a bot")
        return

    # Only process messages in text channels
    if not isinstance(message.channel, discord.TextChannel):
        logger.info("Skipping message: Not a text channel")
        return

    # Skip if message content is empty or only whitespace (e.g., image-only messages)
    content = message.content.strip()
    if not content:
        logger.info("Skipping message: Empty content")
        return

    # Check for #noTL prefix to skip translation
    if content.startswith('#noTL'):
        logger.info("Skipping message: Starts with #noTL")
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

    # Reply-only shortcut: "!TL" translates the replied message using user prefs
    if content.upper() == '!TL':
        if not message.reference or not message.reference.message_id:
            await message.reply("Please reply to a message with `!TL` to translate it.")
            return
        try:
            referenced_message = await message.channel.fetch_message(message.reference.message_id)
        except Exception as e:
            logger.error(f"Failed to fetch referenced message for !TL: {e}")
            await message.reply("Sorry, I couldn't find the replied message to translate.")
            return

        if referenced_message.author.bot:
            await message.reply("I can't translate bot messages.")
            return

        referenced_text = referenced_message.content.strip() if referenced_message.content else ""
        if not referenced_text:
            await message.reply("That message doesn't contain any text to translate.")
            return

        user_id = str(message.author.id)
        user_prefs = user_langs.get(user_id, {})
        from_lang = user_prefs.get("from_lang")
        to_lang = user_prefs.get("to_lang")
        if not (from_lang and to_lang):
            await message.reply("You need to set a language preference first with `!setlang`.")
            return

        await translate_and_send(
            message,
            from_lang,
            to_lang,
            referenced_text,
            display_author=referenced_message.author,
            track_pair=False
        )
        try:
            await message.delete()
        except Exception as e:
            logger.warning(f"Failed to delete !TL reply message: {e}")
        return

    # Skip if message is a command
    if message.content.startswith('!'):
        logger.info("Skipping message: Starts with '!' (command)")
        return

    # Check if channel has translation disabled
    channel_id = str(message.channel.id)
    if channel_id in channel_settings and not channel_settings[channel_id]:
        logger.info(f"Skipping message: Channel {channel_id} has translation disabled")
        return

    # Check if user has language preference and translation is enabled
    user_id = str(message.author.id)
    user_name = message.author.display_name
    user_prefs = user_langs.get(user_id, {})
    
    logger.info(f"User {user_name} ({user_id}) prefs: {user_prefs}")

    if user_prefs and user_prefs.get("enabled", False):
        from_lang = user_prefs.get("from_lang")
        to_lang = user_prefs.get("to_lang")

        if from_lang and to_lang:
            logger.info(f"Auto-translating message for {user_name} from {from_lang} to {to_lang}")
            await translate_and_send(message, from_lang, to_lang, message.content)
        else:
            logger.info(f"Skipping auto-translation: Missing from_lang or to_lang for user {user_name}")
    else:
        logger.info(f"Skipping auto-translation: User {user_name} has translation disabled or no prefs")

# Helper function to translate text and send response
async def translate_and_send(message, from_lang, to_lang, text, display_author=None, track_pair=True):
    thinking_message = None
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

        # Send a "thinking" message immediately
        author_for_display = display_author or message.author
        target_language_name = LANGUAGES.get(to_lang, to_lang.upper())
        thinking_embed = discord.Embed(
            description=f"```\n{text}\n```",
            color=discord.Color.light_grey()
        )
        thinking_embed.set_author(
            name=f"⌛ Translating to {target_language_name}...",
            icon_url=author_for_display.display_avatar.url if author_for_display.display_avatar else None
        )
        try:
            is_reply = message.reference and message.reference.message_id
            if is_reply:
                referenced_message = await message.channel.fetch_message(message.reference.message_id)
                thinking_message = await referenced_message.reply(embed=thinking_embed)
            else:
                thinking_message = await message.channel.send(embed=thinking_embed)
        except Exception as e:
            logger.error(f"Failed to send thinking message: {e}")
            # Fallback to sending in the same channel without replying
            thinking_message = await message.channel.send(embed=thinking_embed)

        # Call Gemini API for translation with typing indicator
        async with message.channel.typing():
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
            response = await client.aio.models.generate_content(
                model=bot_config['model_name'], contents=prompt
            )

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
                name=author_for_display.display_name,
                icon_url=author_for_display.display_avatar.url
            )

            # Add language information to the footer
            #embed.set_footer(text=f"*Translated using {bot_config['model_name']}")

            # Edit the thinking message with the final translation
            if thinking_message:
                await thinking_message.edit(content=None, embed=embed)
                # Store the message pair for tracking edits/deletes
                if track_pair:
                    message_pairs[str(message.id)] = str(thinking_message.id)
                    save_message_pairs(message_pairs)
            else:
                # This is a fallback in case the thinking message failed to send
                sent_message = await message.channel.send(embed=embed)
                if track_pair:
                    message_pairs[str(message.id)] = str(sent_message.id)
                    save_message_pairs(message_pairs)

            logger.info(f"Translated message for user {message.author.display_name} from {from_lang} to {to_lang}")
            #also log the original message and the translated message
            logger.info(f"Original message: {text}")
            logger.info(f"Translated message: {translated_text}")
        else:
            if thinking_message:
                await thinking_message.delete()
            logger.warning(f"Empty translation result for user {message.author.display_name}")
    except Exception as e:
        logger.error(f"Translation error: {e}")
        error_content = f"Sorry, I couldn't translate that message. Error: {str(e)}"
        # If rate limited due to quota on current model, try switching models and retrying
        try:
            err_text = str(e)
        except Exception:
            err_text = ""
        if "429" in err_text and "You exceeded your current quota" in err_text:
            try:
                # Build candidate list of text-capable models excluding image/live variants
                candidates = [m['id'] for m in get_models() if 'image' not in m['id'] and 'live' not in m['id']]
                current_model_id = bot_config.get('model_name')
                # Remove current model from candidates while preserving order
                candidates = [mid for mid in candidates if mid != current_model_id]
                last_err = None
                for next_model_id in candidates:
                    try:
                        bot_config['model_name'] = next_model_id
                        save_bot_config(bot_config)
                        await update_model_status_channel()
                        if 'prompt' not in locals():
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
                        response = await client.aio.models.generate_content(
                            model=next_model_id, contents=prompt
                        )
                        translated_text = response.text.strip() if getattr(response, 'text', None) else ""
                        if translated_text:
                            if len(translated_text) > 4096:
                                translated_text = translated_text[:4093] + "..."
                            embed = discord.Embed(
                                description=translated_text,
                                color=discord.Color.blue()
                            )
                            embed.set_author(
                                name=message.author.display_name,
                                icon_url=message.author.display_avatar.url
                            )
                            if thinking_message:
                                await thinking_message.edit(content=None, embed=embed)
                                message_pairs[str(message.id)] = str(thinking_message.id)
                                save_message_pairs(message_pairs)
                            else:
                                sent_message = await message.channel.send(embed=embed)
                                message_pairs[str(message.id)] = str(sent_message.id)
                                save_message_pairs(message_pairs)
                            logger.info(f"Quota error fallback succeeded by switching to model {next_model_id}")
                            return
                        else:
                            last_err = "Empty translation result after switching model"
                            continue
                    except Exception as retry_err:
                        last_err = retry_err
                        continue
                logger.error(f"All fallback models failed after quota error. Last error: {last_err}")
            except Exception as switch_err:
                logger.error(f"Model switching on quota error failed: {switch_err}")

        if thinking_message:
            await thinking_message.edit(content=error_content, embed=None)
        elif text and text.strip():
            await message.channel.send(error_content)

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
    original_embed = translated_msg.embeds[0] if translated_msg.embeds else None
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

        # Show an indicator on the translated message that it's being updated
        target_language_name = LANGUAGES.get(to_lang, to_lang.upper())
        thinking_embed = discord.Embed(
            description=f"```\n{text}\n```",
            color=discord.Color.light_grey()
        )
        thinking_embed.set_author(
            name=f"⌛ Updating translation to {target_language_name}...",
            icon_url=message.author.display_avatar.url if message.author.display_avatar else None
        )
        await translated_msg.edit(content=None, embed=thinking_embed)

        # Call Gemini API for translation with typing indicator
        async with message.channel.typing():
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
            response = await client.aio.models.generate_content(
                model=bot_config['model_name'], contents=prompt
            )

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
            #updated_embed.set_footer(text=f"*Translated using {bot_config['model_name']}")

            # Edit the message with the updated translation
            await translated_msg.edit(content=None, embed=updated_embed)

            logger.info(f"Updated translation for edited message {message.id}")
            logger.info(f"New original message: {text}")
            logger.info(f"New translated message: {translated_text}")
        else:
            logger.warning(f"Empty translation result for edited message {message.id}")
    except Exception as e:
        logger.error(f"Error updating translation: {e}")
        # Restore the original embed if the update fails
        if original_embed:
            await translated_msg.edit(content="Sorry, the translation could not be updated.", embed=original_embed)
        else:
            await translated_msg.edit(content="Sorry, the translation could not be updated.", embed=None)


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