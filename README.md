# Discord Translation Bot

A Discord bot that automatically translates messages using the Google Gemini API.

## Features

- Automatically translates messages based on user language preferences
- Admin/moderator command to set language preferences for users
- Users can check their current language setting
- Translation can be turned on/off for specific users, channels, or all users
- Inline translation using the `#TL` tag for on-demand translations
- Bilingual help command with both English and Japanese instructions
- Smart tracking of edited and deleted messages:
  - Translations are updated when original messages are edited
  - Translations are deleted when original messages are deleted
- Uses Google's Gemini API for high-quality translations

## Setup

1. Clone this repository
2. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Create a `.env` file based on `.env.example`:
   ```
   cp .env.example .env
   ```
4. Add your Discord bot token and Gemini API key to the `.env` file:
   ```
   DISCORD_TOKEN=your_discord_token_here
   GEMINI_API_KEY=your_gemini_api_key_here
   ```
5. Run the bot:
   ```
   python main.py
   ```

## Commands

- `!setlang @user from_lang to_lang` - Set a user's translation languages (Admin/Mod only)
  - Example: `!setlang @John en ja` translates John's messages from English to Japanese
  - Use language code `auto` for source language to auto-detect the language
- `!mylang` - Check your current language preferences
- `!translate on/off [@user or #channel or ALL]` - Control the translation feature
  - `!translate on` - Turn on translation for yourself
  - `!translate off` - Turn off translation for yourself
  - `!translate on @user` - Turn on translation for mentioned user (Admin/Mod only)
  - `!translate off @user` - Turn off translation for mentioned user (Admin/Mod only)
  - `!translate on #channel` - Turn on translation for the mentioned channel (Admin/Mod only)
  - `!translate off #channel` - Turn off translation for the mentioned channel (Admin/Mod only)
  - `!translate on ALL` - Turn on translation for all users (Admin/Mod only)
  - `!translate off ALL` - Turn off translation for all users (Admin/Mod only)
- `!translate help` - Display help information in both English and Japanese
- `!bothelp` - Alternative command to display help information

## Inline Translation

You can use the `#TL` tag at the beginning of a message to translate it on-demand, regardless of your user settings:

```
#TL from_lang to_lang
Your message to translate goes here
```

Example:
```
#TL en to ja
Hello, how are you today?
```

This will translate the message from English to Japanese, regardless of user settings or channel configuration.

## Message Tracking

The bot automatically tracks relationships between original messages and their translations:

- When you edit a message that's been translated, the translation will be automatically updated
- When you delete a message that's been translated, the translation will be automatically deleted
- This applies to both automatic translations and manual `#TL` translations

These relationships persist even if the bot restarts.

## Language Codes

Use standard language codes when setting preferences:
- English: `en`
- Japanese: `ja`
- Spanish: `es`
- French: `fr`
- German: `de`
- Chinese (Simplified): `zh-CN`
- Russian: `ru`
- etc.

## Note

The bot will only translate messages for users who have language preferences set and have translation enabled. It also respects channel-specific settings, so translation can be disabled for specific channels. The bot ignores messages from bots and commands. 