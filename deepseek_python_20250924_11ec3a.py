import os
import logging
import asyncio
from typing import Dict, List, Set, Optional
from datetime import datetime
import sqlite3
import re

from telethon import TelegramClient, events, types
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.types import (
    Message, User, Channel, Chat, InputPeerChannel, 
    InputPeerChat, InputPeerUser
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AdvancedAutoForwardBot:
    def __init__(self, api_id: int, api_hash: str, bot_token: str, db_path: str = "bot_data.db"):
        self.client = TelegramClient('auto_forward_bot', api_id, api_hash)
        self.bot_token = bot_token
        self.db_path = db_path
        
        # User data storage
        self.user_sessions: Dict[int, Dict] = {}
        self.source_channels: Dict[int, List] = {}
        self.target_channels: Dict[int, List] = {}
        self.forward_settings: Dict[int, Dict] = {}
        self.auto_forwarding: Dict[int, bool] = {}
        
        # Initialize database
        self.init_database()
        
    def init_database(self):
        """Initialize SQLite database for persistent storage"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                phone_number TEXT,
                username TEXT,
                first_name TEXT,
                session_string TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Source channels table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS source_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                channel_id INTEGER,
                channel_name TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Target channels table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS target_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                channel_id INTEGER,
                channel_name TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Settings table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                hide_header BOOLEAN DEFAULT FALSE,
                forward_media BOOLEAN DEFAULT TRUE,
                url_previews BOOLEAN DEFAULT TRUE,
                remove_usernames BOOLEAN DEFAULT FALSE,
                remove_links BOOLEAN DEFAULT FALSE,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Blacklist/Whitelist tables
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS blacklist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                keyword TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS whitelist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                keyword TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Username/Link replacement tables
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS username_replacements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                original_username TEXT,
                replacement TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS link_replacements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                original_link TEXT,
                replacement TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
    
    async def start(self):
        """Start the bot"""
        await self.client.start(bot_token=self.bot_token)
        logger.info("Bot started successfully!")
        
        # Load data from database
        await self.load_user_data()
        
        # Register event handlers
        self.register_handlers()
        
        # Run until disconnected
        await self.client.run_until_disconnected()
    
    async def load_user_data(self):
        """Load user data from database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Load user settings
        cursor.execute("SELECT * FROM user_settings")
        for row in cursor.fetchall():
            user_id = row[0]
            self.forward_settings[user_id] = {
                'hide_header': bool(row[1]),
                'forward_media': bool(row[2]),
                'url_previews': bool(row[3]),
                'remove_usernames': bool(row[4]),
                'remove_links': bool(row[5])
            }
        
        # Load source channels
        cursor.execute("SELECT user_id, channel_id, channel_name FROM source_channels")
        for row in cursor.fetchall():
            user_id, channel_id, channel_name = row
            if user_id not in self.source_channels:
                self.source_channels[user_id] = []
            self.source_channels[user_id].append({
                'id': channel_id,
                'name': channel_name
            })
        
        # Load target channels
        cursor.execute("SELECT user_id, channel_id, channel_name FROM target_channels")
        for row in cursor.fetchall():
            user_id, channel_id, channel_name = row
            if user_id not in self.target_channels:
                self.target_channels[user_id] = []
            self.target_channels[user_id].append({
                'id': channel_id,
                'name': channel_name
            })
        
        conn.close()
    
    def register_handlers(self):
        """Register all event handlers"""
        
        # Start command
        @self.client.on(events.NewMessage(pattern='/start'))
        async def start_handler(event):
            await self.handle_start(event)
        
        # Login command
        @self.client.on(events.NewMessage(pattern='/login'))
        async def login_handler(event):
            await self.handle_login(event)
        
        # Config command
        @self.client.on(events.NewMessage(pattern='/config'))
        async def config_handler(event):
            await self.handle_config(event)
        
        # Source channels command
        @self.client.on(events.NewMessage(pattern='/source'))
        async def source_handler(event):
            await self.handle_source(event)
        
        # Target channels command
        @self.client.on(events.NewMessage(pattern='/target'))
        async def target_handler(event):
            await self.handle_target(event)
        
        # Remove source channels
        @self.client.on(events.NewMessage(pattern='/remove_source'))
        async def remove_source_handler(event):
            await self.handle_remove_source(event)
        
        # Remove target channels
        @self.client.on(events.NewMessage(pattern='/remove_target'))
        async def remove_target_handler(event):
            await self.handle_remove_target(event)
        
        # Start forwarding
        @self.client.on(events.NewMessage(pattern='/start_forwarding'))
        async def start_forwarding_handler(event):
            await self.handle_start_forwarding(event)
        
        # Stop forwarding
        @self.client.on(events.NewMessage(pattern='/stop_forwarding'))
        async def stop_forwarding_handler(event):
            await self.handle_stop_forwarding(event)
        
        # Forward settings
        @self.client.on(events.NewMessage(pattern='/forward_settings'))
        async def forward_settings_handler(event):
            await self.handle_forward_settings(event)
        
        # Settings command
        @self.client.on(events.NewMessage(pattern='/settings'))
        async def settings_handler(event):
            await self.handle_settings(event)
        
        # Tutorial command
        @self.client.on(events.NewMessage(pattern='/tutorial'))
        async def tutorial_handler(event):
            await self.handle_tutorial(event)
        
        # Help command
        @self.client.on(events.NewMessage(pattern='/help'))
        async def help_handler(event):
            await self.handle_help(event)
        
        # Logout command
        @self.client.on(events.NewMessage(pattern='/logout'))
        async def logout_handler(event):
            await self.handle_logout(event)
        
        # Message handler for auto-forwarding
        @self.client.on(events.NewMessage)
        async def message_handler(event):
            await self.handle_auto_forward(event)
    
    async def handle_start(self, event):
        """Handle /start command"""
        user = await event.get_sender()
        welcome_text = f"""
Hi {user.first_name}, Welcome to Best Auto Forwarding Bot!

Use /login to get started and explore all features!
        """
        await event.reply(welcome_text)
    
    async def handle_login(self, event):
        """Handle /login command"""
        user = await event.get_sender()
        
        # Check if user is already logged in
        if user.id in self.user_sessions:
            await event.reply("You are already logged in! Use /logout first if you want to re-login.")
            return
        
        # Ask for phone number
        login_text = """
**Login**

Note: Include the + and country code to avoid login issues.

Enter your phone number with country code. For example: +9179746XXXX1 (India).
        """
        await event.reply(login_text)
        
        # Store that we're waiting for phone number
        self.user_sessions[user.id] = {'step': 'waiting_phone'}
    
    async def handle_config(self, event):
        """Handle /config command - Show current configuration"""
        user = await event.get_sender()
        
        if user.id not in self.user_sessions:
            await event.reply("Please login first using /login")
            return
        
        config_text = "**Current Configuration:**\n\n"
        
        # Source channels
        source_channels = self.source_channels.get(user.id, [])
        config_text += f"**Source Channels ({len(source_channels)}):**\n"
        for i, channel in enumerate(source_channels, 1):
            config_text += f"{i}. {channel['name']} (ID: {channel['id']})\n"
        
        # Target channels
        target_channels = self.target_channels.get(user.id, [])
        config_text += f"\n**Target Channels ({len(target_channels)}):**\n"
        for i, channel in enumerate(target_channels, 1):
            config_text += f"{i}. {channel['name']} (ID: {channel['id']})\n"
        
        # Settings
        settings = self.forward_settings.get(user.id, {})
        config_text += f"\n**Settings:**\n"
        config_text += f"Hide Header: {'Yes' if settings.get('hide_header') else 'No'}\n"
        config_text += f"Forward Media: {'Yes' if settings.get('forward_media') else 'No'}\n"
        config_text += f"Auto-Forwarding: {'Active' if self.auto_forwarding.get(user.id) else 'Inactive'}\n"
        
        await event.reply(config_text)
    
    async def handle_source(self, event):
        """Handle /source command - Set source channels"""
        user = await event.get_sender()
        
        if user.id not in self.user_sessions:
            await event.reply("Please login first using /login")
            return
        
        instructions = """
**Follow these steps:**

1. Go to the chats from which you want to copy messages.
2. Press and hold the chats
3. Tap on the pin icon to pin it at the top

Then press the button below.
        """
        
        # Create a button for confirmation
        from telethon.tl.types import KeyboardButtonCallback
        from telethon import Button
        
        buttons = [[Button.inline("I have pinned the chats", b"source_pinned")]]
        await event.reply(instructions, buttons=buttons)
    
    async def handle_target(self, event):
        """Handle /target command - Set target channels"""
        user = await event.get_sender()
        
        if user.id not in self.user_sessions:
            await event.reply("Please login first using /login")
            return
        
        instructions = """
**Follow these steps to select destination chats:**
1. Go to the Target Channel/Group where you want to forward messages.
2. Press and hold the chat.
3. Tap on the pin icon to pin it at the top.

Then press the button below.
        """
        
        from telethon import Button
        buttons = [[Button.inline("I have pinned the chats", b"target_pinned")]]
        await event.reply(instructions, buttons=buttons)
    
    async def handle_remove_source(self, event):
        """Handle /remove_source command"""
        user = await event.get_sender()
        
        if user.id not in self.source_channels or not self.source_channels[user.id]:
            await event.reply("No source channels configured.")
            return
        
        channels = self.source_channels[user.id]
        message = "**Select source channel to remove:**\n\n"
        
        from telethon import Button
        buttons = []
        for i, channel in enumerate(channels, 1):
            buttons.append([Button.inline(f"{i}. {channel['name']}", f"remove_source_{channel['id']}")])
        
        buttons.append([Button.inline("Cancel", b"cancel_remove")])
        await event.reply(message, buttons=buttons)
    
    async def handle_remove_target(self, event):
        """Handle /remove_target command"""
        user = await event.get_sender()
        
        if user.id not in self.target_channels or not self.target_channels[user.id]:
            await event.reply("No target channels configured.")
            return
        
        channels = self.target_channels[user.id]
        message = "**Select target channel to remove:**\n\n"
        
        from telethon import Button
        buttons = []
        for i, channel in enumerate(channels, 1):
            buttons.append([Button.inline(f"{i}. {channel['name']}", f"remove_target_{channel['id']}")])
        
        buttons.append([Button.inline("Cancel", b"cancel_remove")])
        await event.reply(message, buttons=buttons)
    
    async def handle_start_forwarding(self, event):
        """Handle /start_forwarding command"""
        user = await event.get_sender()
        
        if user.id not in self.user_sessions:
            await event.reply("Please login first using /login")
            return
        
        if not self.source_channels.get(user.id) or not self.target_channels.get(user.id):
            await event.reply("Please configure both source and target channels first.")
            return
        
        self.auto_forwarding[user.id] = True
        await event.reply("✅ Auto-forwarding started successfully!")
    
    async def handle_stop_forwarding(self, event):
        """Handle /stop_forwarding command"""
        user = await event.get_sender()
        
        if user.id not in self.auto_forwarding or not self.auto_forwarding[user.id]:
            await event.reply("Auto-forwarding is not active.")
            return
        
        self.auto_forwarding[user.id] = False
        await event.reply("❌ Auto-forwarding stopped.")
    
    async def handle_forward_settings(self, event):
        """Handle /forward_settings command"""
        settings_menu = """
**Customize Your Bot Forwarding Settings:**

• /hide_header – Show/Hide 'Forward From' Header
• /media_status – Forward All Media ON/OFF
• /url_previews - URL Preview ON/OFF
• /remove_usernames - Usernames ON/OFF
• /remove_links - Filter Links ON/OFF

• /blacklist - Add Blacklist Keywords
• /remove_blacklist - Remove Blacklist Keywords

• /whitelist - Add Whitelist Keywords
• /remove_whitelist - Remove Whitelist Keywords

• /replace_username - Add Usernames in List
• /delete_username - Delete Usernames List

• /replace_links - Add Links in List
• /delete_links - Delete Links in List

More forwarding options coming soon...
        """
        await event.reply(settings_menu)
    
    async def handle_settings(self, event):
        """Handle /settings command"""
        settings_menu = """
**All Settings Menu:**

• /status - Check Your Account Status
• /forward_settings - Message Forwarding Settings
• /config - Current Configuration

More settings coming soon...
        """
        await event.reply(settings_menu)
    
    async def handle_tutorial(self, event):
        """Handle /tutorial command"""
        tutorial_text = """
**Choose your preferred language to watch tutorials?**

Please select your language:
        """
        
        from telethon import Button
        buttons = [
            [Button.inline("English", b"tutorial_en"), 
             Button.inline("Hindi", b"tutorial_hi")]
        ]
        await event.reply(tutorial_text, buttons=buttons)
    
    async def handle_help(self, event):
        """Handle /help command"""
        help_text = """
**Need help or have a question?** 
Feel free to reach out to our admin at @starworrier — we're here to assist you!
        """
        await event.reply(help_text)
    
    async def handle_logout(self, event):
        """Handle /logout command"""
        user = await event.get_sender()
        
        if user.id in self.user_sessions:
            del self.user_sessions[user.id]
        if user.id in self.auto_forwarding:
            del self.auto_forwarding[user.id]
        
        # Clear from database
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM source_channels WHERE user_id = ?", (user.id,))
        cursor.execute("DELETE FROM target_channels WHERE user_id = ?", (user.id,))
        cursor.execute("DELETE FROM user_settings WHERE user_id = ?", (user.id,))
        conn.commit()
        conn.close()
        
        await event.reply("✅ Logged out successfully!")
    
    async def handle_auto_forward(self, event):
        """Handle auto-forwarding of messages"""
        if not event.message:
            return
        
        # Check if message is from a source channel for any user
        for user_id, sources in self.source_channels.items():
            if not self.auto_forwarding.get(user_id):
                continue
            
            chat_id = event.chat_id
            source_ids = [channel['id'] for channel in sources]
            
            if chat_id in source_ids:
                await self.forward_message(event, user_id)
    
    async def forward_message(self, event, user_id):
        """Forward a message with applied settings"""
        try:
            targets = self.target_channels.get(user_id, [])
            settings = self.forward_settings.get(user_id, {})
            
            if not targets:
                return
            
            message = event.message
            modified_text = message.text or message.caption or ""
            
            # Apply text modifications based on settings
            if settings.get('remove_usernames'):
                modified_text = re.sub(r'@\w+', '', modified_text)
            
            if settings.get('remove_links'):
                modified_text = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', modified_text)
            
            # Apply username/link replacements from database
            modified_text = await self.apply_replacements(user_id, modified_text)
            
            # Check blacklist/whitelist
            if not await self.passes_filters(user_id, modified_text):
                return
            
            # Forward to all target channels
            for target in targets:
                try:
                    if message.media and settings.get('forward_media', True):
                        # Forward media with modified caption
                        if modified_text and modified_text != (message.text or message.caption or ""):
                            await self.client.send_file(
                                target['id'],
                                message.media,
                                caption=modified_text,
                                link_preview=settings.get('url_previews', True)
                            )
                        else:
                            await message.forward_to(target['id'])
                    else:
                        # Forward text only or media without forwarding
                        if modified_text:
                            await self.client.send_message(
                                target['id'],
                                modified_text,
                                link_preview=settings.get('url_previews', True)
                            )
                
                except Exception as e:
                    logger.error(f"Error forwarding to {target['name']}: {e}")
        
        except Exception as e:
            logger.error(f"Error in forward_message: {e}")
    
    async def apply_replacements(self, user_id: int, text: str) -> str:
        """Apply username and link replacements"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Apply username replacements
        cursor.execute("SELECT original_username, replacement FROM username_replacements WHERE user_id = ?", (user_id,))
        for original, replacement in cursor.fetchall():
            text = text.replace(original, replacement)
        
        # Apply link replacements
        cursor.execute("SELECT original_link, replacement FROM link_replacements WHERE user_id = ?", (user_id,))
        for original, replacement in cursor.fetchall():
            text = text.replace(original, replacement)
        
        conn.close()
        return text
    
    async def passes_filters(self, user_id: int, text: str) -> bool:
        """Check if message passes blacklist/whitelist filters"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Check blacklist
        cursor.execute("SELECT keyword FROM blacklist WHERE user_id = ?", (user_id,))
        blacklist_keywords = [row[0] for row in cursor.fetchall()]
        
        for keyword in blacklist_keywords:
            if keyword.lower() in text.lower():
                conn.close()
                return False
        
        # Check whitelist (if any whitelist exists, message must match at least one)
        cursor.execute("SELECT keyword FROM whitelist WHERE user_id = ?", (user_id,))
        whitelist_keywords = [row[0] for row in cursor.fetchall()]
        
        if whitelist_keywords:
            matches_whitelist = any(keyword.lower() in text.lower() for keyword in whitelist_keywords)
            if not matches_whitelist:
                conn.close()
                return False
        
        conn.close()
        return True

# Additional command handlers for settings
async def register_additional_handlers(bot):
    """Register additional setting-specific handlers"""
    
    @bot.client.on(events.NewMessage(pattern='/hide_header'))
    async def hide_header_handler(event):
        user = await event.get_sender()
        if user.id not in bot.forward_settings:
            bot.forward_settings[user.id] = {}
        
        current = bot.forward_settings[user.id].get('hide_header', False)
        bot.forward_settings[user.id]['hide_header'] = not current
        
        status = "enabled" if not current else "disabled"
        await event.reply(f"✅ Hide header {status}!")
        
        # Save to database
        conn = sqlite3.connect(bot.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO user_settings 
            (user_id, hide_header, updated_at) 
            VALUES (?, ?, CURRENT_TIMESTAMP)
        ''', (user.id, not current))
        conn.commit()
        conn.close()
    
    # Similar handlers for other settings...
    # /media_status, /url_previews, /remove_usernames, /remove_links etc.

# Main function to run the bot
async def main():
    # Get credentials from environment variables
    api_id = int(os.getenv('TELEGRAM_API_ID', '123456'))
    api_hash = os.getenv('TELEGRAM_API_HASH', 'your_api_hash')
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN', 'your_bot_token')
    
    if api_id == '123456' or api_hash == 'your_api_hash' or bot_token == 'your_bot_token':
        print("Please set TELEGRAM_API_ID, TELEGRAM_API_HASH, and TELEGRAM_BOT_TOKEN environment variables")
        return
    
    # Create and start bot
    bot = AdvancedAutoForwardBot(api_id, api_hash, bot_token)
    await bot.start()

if __name__ == '__main__':
    asyncio.run(main())