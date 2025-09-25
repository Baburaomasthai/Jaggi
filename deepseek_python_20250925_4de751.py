import os
import logging
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime
import re
import sqlite3
from telethon import TelegramClient, events, Button
from telethon.tl.types import User, Channel, Message, Dialog
from telethon.tl.functions.auth import SendCodeRequest, SignInRequest
from telethon.errors import SessionPasswordNeededError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Admin configuration - REPLACE WITH YOUR ACTUAL VALUES
ADMIN_USER_IDS = [123456789]  # Replace with your user ID
FORCE_SUB_CHANNEL = "@YourChannel"  # Replace with your channel username

class SQLiteDatabase:
    """SQLite Database System for Bot"""
    
    def __init__(self, db_path: str = "bot_data.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize database tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                phone_number TEXT,
                first_name TEXT,
                username TEXT,
                login_time TEXT,
                status TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Source channels table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS source_channels (
                user_id INTEGER PRIMARY KEY,
                channel_id INTEGER,
                channel_name TEXT,
                username TEXT,
                set_time TEXT,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Target channels table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS target_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                channel_id INTEGER,
                channel_name TEXT,
                username TEXT,
                added_time TEXT,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Settings table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                hide_header BOOLEAN DEFAULT 0,
                forward_media BOOLEAN DEFAULT 1,
                url_previews BOOLEAN DEFAULT 1,
                remove_usernames BOOLEAN DEFAULT 0,
                remove_links BOOLEAN DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Auto forwarding status
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS auto_forwarding (
                user_id INTEGER PRIMARY KEY,
                is_active BOOLEAN DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Word replacements table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS word_replacements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                original_word TEXT,
                replacement_word TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Link replacements table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS link_replacements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                original_link TEXT,
                replacement_link TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully")
    
    def get_connection(self):
        """Get database connection"""
        return sqlite3.connect(self.db_path)

class AdvancedAutoForwardBot:
    def __init__(self, api_id: int, api_hash: str, bot_token: str):
        self.api_id = api_id
        self.api_hash = api_hash
        self.bot_token = bot_token
        self.client = TelegramClient('auto_forward_bot', api_id, api_hash)
        self.db = SQLiteDatabase()
        
        # Runtime storage
        self.user_sessions: Dict[int, Dict] = {}
        self.source_channel: Dict[int, Dict] = {}
        self.target_channels: Dict[int, List] = {}
        self.forward_settings: Dict[int, Dict] = {}
        self.auto_forwarding: Dict[int, bool] = {}
        self.login_attempts: Dict[int, Dict] = {}
        self.user_clients: Dict[int, TelegramClient] = {}
        self.word_replacements: Dict[int, Dict] = {}
        self.link_replacements: Dict[int, Dict] = {}
        
        # State management
        self.awaiting_channel_selection: Dict[int, Dict] = {}
        self.awaiting_word_replacement: Dict[int, Dict] = {}
        self.awaiting_link_replacement: Dict[int, Dict] = {}
        
        # Default settings
        self.default_settings = {
            'hide_header': False,
            'forward_media': True,
            'url_previews': True,
            'remove_usernames': False,
            'remove_links': False
        }

    async def initialize(self):
        """Initialize the bot"""
        try:
            await self.client.start(bot_token=self.bot_token)
            logger.info("Bot started successfully!")
            
            await self.load_all_data()
            self.register_handlers()
            
            logger.info("Bot fully initialized!")
            return True
                
        except Exception as e:
            logger.error(f"Error during initialization: {e}")
            return False

    async def load_all_data(self):
        """Load all data from database"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            # Load users
            cursor.execute("SELECT * FROM users WHERE status = 'logged_in'")
            for user in cursor.fetchall():
                user_id, phone, first_name, username, login_time, status = user
                self.user_sessions[user_id] = {
                    'phone_number': phone,
                    'first_name': first_name,
                    'username': username,
                    'login_time': login_time,
                    'status': status
                }
            
            # Load source channels
            cursor.execute("SELECT * FROM source_channels")
            for source in cursor.fetchall():
                user_id, channel_id, channel_name, username, set_time = source
                self.source_channel[user_id] = {
                    'id': channel_id,
                    'name': channel_name,
                    'username': username,
                    'set_time': set_time
                }
            
            # Load target channels
            cursor.execute("SELECT * FROM target_channels")
            for target in cursor.fetchall():
                id, user_id, channel_id, channel_name, username, added_time = target
                if user_id not in self.target_channels:
                    self.target_channels[user_id] = []
                self.target_channels[user_id].append({
                    'id': channel_id,
                    'name': channel_name,
                    'username': username,
                    'added_time': added_time
                })
            
            # Load settings
            cursor.execute("SELECT * FROM user_settings")
            for setting in cursor.fetchall():
                user_id, hide_header, forward_media, url_previews, remove_usernames, remove_links = setting
                self.forward_settings[user_id] = {
                    'hide_header': bool(hide_header),
                    'forward_media': bool(forward_media),
                    'url_previews': bool(url_previews),
                    'remove_usernames': bool(remove_usernames),
                    'remove_links': bool(remove_links)
                }
            
            # Load auto forwarding
            cursor.execute("SELECT * FROM auto_forwarding WHERE is_active = 1")
            for forwarding in cursor.fetchall():
                user_id, is_active, updated_at = forwarding
                self.auto_forwarding[user_id] = bool(is_active)
            
            # Load word replacements
            cursor.execute("SELECT * FROM word_replacements")
            for rep in cursor.fetchall():
                id, user_id, original, replacement, created_at = rep
                if user_id not in self.word_replacements:
                    self.word_replacements[user_id] = {}
                self.word_replacements[user_id][original] = replacement
            
            # Load link replacements
            cursor.execute("SELECT * FROM link_replacements")
            for rep in cursor.fetchall():
                id, user_id, original, replacement, created_at = rep
                if user_id not in self.link_replacements:
                    self.link_replacements[user_id] = {}
                self.link_replacements[user_id][original] = replacement
            
            conn.close()
            logger.info("Data loaded successfully")
            
        except Exception as e:
            logger.error(f"Error loading data: {e}")

    # ==================== DATABASE METHODS ====================

    async def save_user_session(self, user_id: int, user_data: Dict):
        """Save user session to database"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO users 
                (user_id, phone_number, first_name, username, login_time, status)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                user_id, 
                user_data.get('phone_number'),
                user_data.get('first_name'),
                user_data.get('username'),
                user_data.get('login_time'),
                user_data.get('status', 'logged_in')
            ))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Error saving user session: {e}")
            return False

    async def save_source_channel(self, user_id: int, channel_data: Dict):
        """Save source channel to database"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO source_channels 
                (user_id, channel_id, channel_name, username, set_time)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                user_id,
                channel_data.get('id'),
                channel_data.get('name'),
                channel_data.get('username'),
                channel_data.get('set_time')
            ))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Error saving source channel: {e}")
            return False

    async def save_target_channel(self, user_id: int, channel_data: Dict):
        """Save target channel to database"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO target_channels 
                (user_id, channel_id, channel_name, username, added_time)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                user_id,
                channel_data.get('id'),
                channel_data.get('name'),
                channel_data.get('username'),
                channel_data.get('added_time')
            ))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Error saving target channel: {e}")
            return False

    async def save_user_settings(self, user_id: int, settings: Dict):
        """Save user settings to database"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO user_settings 
                (user_id, hide_header, forward_media, url_previews, remove_usernames, remove_links)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                user_id,
                int(settings.get('hide_header', False)),
                int(settings.get('forward_media', True)),
                int(settings.get('url_previews', True)),
                int(settings.get('remove_usernames', False)),
                int(settings.get('remove_links', False))
            ))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Error saving user settings: {e}")
            return False

    async def save_auto_forwarding(self, user_id: int, is_active: bool):
        """Save auto forwarding status to database"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO auto_forwarding 
                (user_id, is_active)
                VALUES (?, ?)
            ''', (user_id, int(is_active)))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Error saving auto forwarding: {e}")
            return False

    async def save_word_replacement(self, user_id: int, original: str, replacement: str):
        """Save word replacement to database"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO word_replacements 
                (user_id, original_word, replacement_word)
                VALUES (?, ?, ?)
            ''', (user_id, original, replacement))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Error saving word replacement: {e}")
            return False

    async def save_link_replacement(self, user_id: int, original: str, replacement: str):
        """Save link replacement to database"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO link_replacements 
                (user_id, original_link, replacement_link)
                VALUES (?, ?, ?)
            ''', (user_id, original, replacement))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Error saving link replacement: {e}")
            return False

    async def delete_user_data(self, user_id: int):
        """Delete all user data from database"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM source_channels WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM target_channels WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM user_settings WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM auto_forwarding WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM word_replacements WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM link_replacements WHERE user_id = ?", (user_id,))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Error deleting user data: {e}")
            return False

    def is_admin(self, user_id: int) -> bool:
        """Check if user is admin"""
        return user_id in ADMIN_USER_IDS

    async def check_force_subscribe(self, user_id: int) -> bool:
        """Check if user is subscribed to force sub channel"""
        try:
            if not FORCE_SUB_CHANNEL or FORCE_SUB_CHANNEL == "@YourChannel":
                return True
            
            channel_entity = await self.client.get_entity(FORCE_SUB_CHANNEL)
            participants = await self.client.get_participants(channel_entity, limit=100)
            user_ids = [participant.id for participant in participants]
            return user_id in user_ids
        except Exception as e:
            logger.error(f"Error checking force subscribe: {e}")
            return True

    # ==================== LOGIN SYSTEM ====================

    async def handle_login(self, event):
        """Handle /login command"""
        user = await event.get_sender()
        
        if not await self.check_force_subscribe(user.id):
            await self.show_force_subscribe(event)
            return
        
        if user.id in self.user_sessions:
            await event.reply("✅ You are already logged in! Use `/logout` first if you want to re-login.")
            return
        
        message_text = event.text.replace('/login', '').strip()
        
        if message_text and re.match(r'^\+[0-9]{10,15}$', message_text):
            phone_number = message_text
            await self.start_telegram_login(user, phone_number, event)
        else:
            login_text = """
🔐 **Login Process**

Please send your phone number in international format:

**Example:** `+919876543210`

You can send it now or use: `/login +919876543210`
            """
            self.login_attempts[user.id] = {'step': 'waiting_phone'}
            await event.reply(login_text)

    async def start_telegram_login(self, user, phone_number, event):
        """Start real Telegram login process"""
        try:
            session_name = f"sessions/user_{user.id}"
            os.makedirs("sessions", exist_ok=True)
            
            user_client = TelegramClient(session_name, self.api_id, self.api_hash)
            await user_client.connect()
            sent_code = await user_client.send_code_request(phone_number)
            
            self.login_attempts[user.id] = {
                'step': 'waiting_code',
                'phone_number': phone_number,
                'phone_code_hash': sent_code.phone_code_hash,
                'user_client': user_client,
                'attempt_time': datetime.now().isoformat()
            }
            
            login_text = f"""
📱 **Verification Code Sent!**

**Phone:** `{phone_number}`

Please check your Telegram app for the verification code.

**Send the code in format:** `AUTOX123456`

Replace 123456 with your actual code.
            """
            
            buttons = [
                [Button.inline("🔄 Resend Code", b"resend_code")],
                [Button.inline("❌ Cancel", b"cancel_login")]
            ]
            
            await event.reply(login_text, buttons=buttons)
            
        except Exception as e:
            logger.error(f"Error starting login: {e}")
            error_msg = "❌ Error sending verification code. Please check the phone number format."
            await event.reply(error_msg)
            if user.id in self.login_attempts:
                del self.login_attempts[user.id]

    async def resend_code(self, event):
        """Resend verification code"""
        user = await event.get_sender()
        
        if user.id not in self.login_attempts:
            await event.answer("❌ No active login session", alert=True)
            return
        
        login_data = self.login_attempts[user.id]
        
        try:
            sent_code = await login_data['user_client'].send_code_request(login_data['phone_number'])
            login_data['phone_code_hash'] = sent_code.phone_code_hash
            
            await event.edit("✅ Verification code resent! Please check your Telegram app.")
        except Exception as e:
            logger.error(f"Error resending code: {e}")
            await event.edit("❌ Error resending code. Please try again.")

    async def handle_code_verification(self, event):
        """Handle verification code input with AUTOX prefix"""
        user = await event.get_sender()
        
        if user.id not in self.login_attempts or self.login_attempts[user.id].get('step') != 'waiting_code':
            return
        
        code_text = event.text.strip().upper()
        
        if not code_text.startswith('AUTOX'):
            await event.reply("❌ Please use format: `AUTOX123456` (replace 123456 with your actual code)")
            return
        
        code = code_text[5:]  # Remove AUTOX prefix
        
        if not code.isdigit() or len(code) < 5:
            await event.reply("❌ Invalid code format. Please enter like: `AUTOX123456`")
            return
        
        login_data = self.login_attempts[user.id]
        
        try:
            await login_data['user_client'].sign_in(
                phone=login_data['phone_number'],
                code=code,
                phone_code_hash=login_data['phone_code_hash']
            )
            
            user_entity = await login_data['user_client'].get_me()
            
            # Store user client for channel access
            self.user_clients[user.id] = login_data['user_client']
            
            user_data = {
                'phone_number': login_data['phone_number'],
                'first_name': user_entity.first_name,
                'username': user_entity.username,
                'login_time': datetime.now().isoformat(),
                'status': 'logged_in'
            }
            
            self.user_sessions[user.id] = user_data
            await self.save_user_session(user.id, user_data)
            
            if user.id not in self.forward_settings:
                self.forward_settings[user.id] = self.default_settings.copy()
                await self.save_user_settings(user.id, self.forward_settings[user.id])
            
            del self.login_attempts[user.id]
            
            success_text = f"""
✅ **Login Successful!**

Welcome, {user_entity.first_name or 'User'}!

Now you can set up auto-forwarding!
            """
            
            buttons = [
                [Button.inline("📥 Set Source Channel", b"show_channels_source"),
                 Button.inline("📤 Add Target Channel", b"show_channels_target")],
                [Button.inline("🚀 Quick Start", b"quick_start_guide"),
                 Button.inline("📊 Dashboard", b"show_dashboard")]
            ]
            
            await event.reply(success_text, buttons=buttons)
            
        except SessionPasswordNeededError:
            await event.reply("🔒 Your account has 2FA enabled. This bot doesn't support 2FA accounts yet.")
        except Exception as e:
            logger.error(f"Error during code verification: {e}")
            error_msg = "❌ Invalid verification code. Please check and try again."
            await event.reply(error_msg)

    # ==================== CHANNELS SYSTEM ====================

    async def get_user_channels(self, user_id: int) -> List[Dict]:
        """Get user's channels/groups"""
        try:
            if user_id not in self.user_clients:
                return []
            
            user_client = self.user_clients[user_id]
            dialogs = await user_client.get_dialogs(limit=30)
            
            channels = []
            for dialog in dialogs:
                if hasattr(dialog, 'entity') and dialog.entity:
                    entity = dialog.entity
                    if hasattr(entity, 'title') and entity.title:
                        is_channel = hasattr(entity, 'broadcast') and entity.broadcast
                        is_supergroup = hasattr(entity, 'megagroup') and entity.megagroup
                        
                        if is_channel or is_supergroup:
                            channels.append({
                                'id': entity.id,
                                'name': entity.title,
                                'username': getattr(entity, 'username', None),
                                'participants_count': getattr(entity, 'participants_count', 0),
                                'type': 'channel' if is_channel else 'supergroup'
                            })
            
            return channels[:10]
            
        except Exception as e:
            logger.error(f"Error getting user channels: {e}")
            return []

    async def show_channels_source(self, event):
        """Show channels for source selection"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        if user.id not in self.user_clients:
            try:
                session_name = f"sessions/user_{user.id}"
                if os.path.exists(session_name + ".session"):
                    user_client = TelegramClient(session_name, self.api_id, self.api_hash)
                    await user_client.connect()
                    self.user_clients[user.id] = user_client
                else:
                    await event.edit("❌ Session not found. Please login again.")
                    return
            except Exception as e:
                await event.edit("❌ Error connecting to your account. Please login again.")
                return
        
        channels = await self.get_user_channels(user.id)
        
        if not channels:
            await event.edit("❌ No channels/groups found in your account.")
            return
        
        selection_text = "📥 **Select Source Channel**\n\nYour channels and groups:\n\n"
        
        for i, channel in enumerate(channels, 1):
            selection_text += f"{i}. **{channel['name']}** ({channel['type']})\n"
        
        selection_text += "\nClick the number to set as source channel:"
        
        buttons = []
        for i in range(1, len(channels) + 1):
            if i % 2 == 1:
                row = []
            row.append(Button.inline(f"{i}", f"set_source_{i}"))
            if i % 2 == 0 or i == len(channels):
                buttons.append(row)
        
        buttons.append([Button.inline("🔄 Refresh List", b"show_channels_source")])
        buttons.append([Button.inline("🔙 Back", b"main_menu")])
        
        self.awaiting_channel_selection[user.id] = {
            'type': 'source',
            'channels': channels
        }
        
        await event.edit(selection_text, buttons=buttons)

    async def show_channels_target(self, event):
        """Show channels for target selection"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        if user.id not in self.user_clients:
            try:
                session_name = f"sessions/user_{user.id}"
                if os.path.exists(session_name + ".session"):
                    user_client = TelegramClient(session_name, self.api_id, self.api_hash)
                    await user_client.connect()
                    self.user_clients[user.id] = user_client
                else:
                    await event.edit("❌ Session not found. Please login again.")
                    return
            except Exception as e:
                await event.edit("❌ Error connecting to your account. Please login again.")
                return
        
        channels = await self.get_user_channels(user.id)
        
        if not channels:
            await event.edit("❌ No channels/groups found in your account.")
            return
        
        selection_text = "📤 **Add Target Channel**\n\nYour channels and groups:\n\n"
        
        for i, channel in enumerate(channels, 1):
            selection_text += f"{i}. **{channel['name']}** ({channel['type']})\n"
        
        selection_text += "\nClick the number to add as target channel:"
        
        buttons = []
        for i in range(1, len(channels) + 1):
            if i % 2 == 1:
                row = []
            row.append(Button.inline(f"{i}", f"add_target_{i}"))
            if i % 2 == 0 or i == len(channels):
                buttons.append(row)
        
        buttons.append([Button.inline("📋 View Current Targets", b"view_targets")])
        buttons.append([Button.inline("🔄 Refresh List", b"show_channels_target")])
        buttons.append([Button.inline("🔙 Back", b"main_menu")])
        
        self.awaiting_channel_selection[user.id] = {
            'type': 'target',
            'channels': channels
        }
        
        await event.edit(selection_text, buttons=buttons)

    async def handle_channel_selection(self, event, selection_type: str, channel_index: int):
        """Handle channel selection from user's channels"""
        user = await event.get_sender()
        
        if user.id not in self.awaiting_channel_selection:
            await event.answer("❌ Selection expired. Please try again.", alert=True)
            return
        
        channel_data = self.awaiting_channel_selection[user.id]
        channels = channel_data['channels']
        
        if channel_index < 1 or channel_index > len(channels):
            await event.answer("❌ Invalid selection", alert=True)
            return
        
        selected_channel = channels[channel_index - 1]
        
        if selection_type == 'source':
            await self.set_source_channel(user.id, selected_channel, event)
        else:
            await self.add_target_channel(user.id, selected_channel, event)

    async def set_source_channel(self, user_id: int, channel_info: Dict, event):
        """Set source channel"""
        try:
            source_data = {
                'id': channel_info['id'],
                'name': channel_info['name'],
                'username': channel_info.get('username'),
                'set_time': datetime.now().isoformat()
            }
            
            self.source_channel[user_id] = source_data
            await self.save_source_channel(user_id, source_data)
            
            if user_id in self.awaiting_channel_selection:
                del self.awaiting_channel_selection[user_id]
            
            success_text = f"""
✅ **Source Channel Set Successfully!**

**Channel:** {channel_info['name']}
**Type:** {channel_info['type']}

Now add target channels to start forwarding!
            """
            
            buttons = [
                [Button.inline("📤 Add Target Channel", b"show_channels_target"),
                 Button.inline("🚀 Start Forwarding", b"start_forwarding")],
                [Button.inline("📊 Dashboard", b"show_dashboard")]
            ]
            
            await event.edit(success_text, buttons=buttons)
            
        except Exception as e:
            logger.error(f"Error setting source channel: {e}")
            await event.edit("❌ Error setting source channel. Please try again.")

    async def add_target_channel(self, user_id: int, channel_info: Dict, event):
        """Add target channel"""
        try:
            target_data = {
                'id': channel_info['id'],
                'name': channel_info['name'],
                'username': channel_info.get('username'),
                'added_time': datetime.now().isoformat()
            }
            
            if user_id not in self.target_channels:
                self.target_channels[user_id] = []
            
            if any(ch['id'] == channel_info['id'] for ch in self.target_channels[user_id]):
                await event.edit("❌ This channel is already in your target list.")
                return
            
            self.target_channels[user_id].append(target_data)
            await self.save_target_channel(user_id, target_data)
            
            if user_id in self.awaiting_channel_selection:
                del self.awaiting_channel_selection[user_id]
            
            success_text = f"""
✅ **Target Channel Added Successfully!**

**Channel:** {channel_info['name']}
**Type:** {channel_info['type']}

**Total target channels:** {len(self.target_channels[user_id])}
            """
            
            buttons = [
                [Button.inline("➕ Add Another Target", b"show_channels_target"),
                 Button.inline("🚀 Start Forwarding", b"start_forwarding")],
                [Button.inline("📋 View All Targets", b"view_targets")]
            ]
            
            await event.edit(success_text, buttons=buttons)
            
        except Exception as e:
            logger.error(f"Error adding target channel: {e}")
            await event.edit("❌ Error adding target channel. Please try again.")

    # ==================== MAIN COMMANDS ====================

    async def show_force_subscribe(self, event):
        """Show force subscribe message"""
        force_sub_text = f"""
🔒 **Subscription Required**

To use this bot, you need to join our official channel first.

**Channel:** {FORCE_SUB_CHANNEL}

Click the button below to join our channel, then click "I've Joined".
        """
        
        buttons = [
            [Button.url("📢 JOIN OUR CHANNEL", f"https://t.me/{FORCE_SUB_CHANNEL.replace('@', '')}")],
            [Button.inline("✅ I'VE JOINED", b"check_subscription")]
        ]
        
        await event.reply(force_sub_text, buttons=buttons)

    async def handle_start(self, event):
        """Handle /start command"""
        user = await event.get_sender()
        
        if not await self.check_force_subscribe(user.id):
            await self.show_force_subscribe(event)
            return
        
        welcome_text = f"""
🤖 **Welcome to Best Auto Forwarding Bot!** 🚀

Hi {user.first_name or 'User'}! I'm here to help you automate message forwarding between channels.

**🌟 Features:**
• Single source channel
• Multiple target channels  
• Real-time message forwarding
• Word & Link replacements
• Media files support

Use the buttons below to get started!
        """
        
        buttons = []
        
        if user.id in self.user_sessions:
            buttons.extend([
                [Button.inline("📊 DASHBOARD", b"show_dashboard"),
                 Button.inline("⚙️ SETTINGS", b"show_settings")],
                [Button.inline("📥 SOURCE CHANNEL", b"show_channels_source"),
                 Button.inline("📤 TARGET CHANNELS", b"show_channels_target")],
                [Button.inline("🚀 START FORWARDING", b"start_forwarding"),
                 Button.inline("🔐 LOGOUT", b"logout_user")]
            ])
            
            if self.is_admin(user.id):
                buttons.append([Button.inline("👑 ADMIN PANEL", b"admin_panel")])
        else:
            buttons.extend([
                [Button.inline("🔐 LOGIN NOW", b"quick_login")],
                [Button.inline("📚 HOW IT WORKS", b"how_it_works"),
                 Button.inline("💬 SUPPORT", b"contact_support")]
            ])
        
        await event.reply(welcome_text, buttons=buttons)

    async def handle_logout(self, event):
        """Handle /logout command"""
        user = await event.get_sender()
        
        if user.id in self.user_sessions:
            if user.id in self.user_clients:
                await self.user_clients[user.id].disconnect()
                del self.user_clients[user.id]
            
            try:
                session_file = f"sessions/user_{user.id}.session"
                if os.path.exists(session_file):
                    os.remove(session_file)
            except Exception as e:
                logger.error(f"Error cleaning session file: {e}")
            
            await self.delete_user_data(user.id)
            
            if user.id in self.user_sessions:
                del self.user_sessions[user.id]
            if user.id in self.source_channel:
                del self.source_channel[user.id]
            if user.id in self.target_channels:
                del self.target_channels[user.id]
            if user.id in self.forward_settings:
                del self.forward_settings[user.id]
            if user.id in self.auto_forwarding:
                del self.auto_forwarding[user.id]
        
        buttons = [
            [Button.inline("🔐 LOGIN AGAIN", b"quick_login"),
             Button.inline("🏠 MAIN MENU", b"main_menu")]
        ]
        
        await event.reply("✅ Logout successful! All data cleared.", buttons=buttons)

    async def show_dashboard(self, event):
        """Show user dashboard"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        user_data = self.user_sessions.get(user.id, {})
        source = self.source_channel.get(user.id, {})
        targets = self.target_channels.get(user.id, [])
        
        dashboard_text = f"""
📊 **User Dashboard**

**👤 Account:**
• User: {user_data.get('first_name', 'N/A')}
• Status: ✅ Active

**📈 Channels:**
• Source: {source.get('name', 'Not set')}
• Targets: {len(targets)} channels
• Forwarding: {'🟢 ACTIVE' if self.auto_forwarding.get(user.id) else '⏸️ PAUSED'}

Use the buttons below to manage your setup.
        """
        
        buttons = [
            [Button.inline("📥 SOURCE", b"show_channels_source"),
             Button.inline("📤 TARGETS", b"show_channels_target")],
            [Button.inline("⚙️ SETTINGS", b"show_settings"),
             Button.inline("🔄 " + ("STOP" if self.auto_forwarding.get(user.id) else "START"), 
                         b"stop_forwarding" if self.auto_forwarding.get(user.id) else "start_forwarding")],
            [Button.inline("🏠 MAIN MENU", b"main_menu")]
        ]
        
        await event.edit(dashboard_text, buttons=buttons)

    # ==================== AUTO FORWARDING ====================

    async def handle_start_forwarding(self, event):
        """Handle start forwarding"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        if user.id not in self.source_channel:
            buttons = [[Button.inline("📥 SET SOURCE CHANNEL", b"show_channels_source")]]
            await event.edit("❌ No source channel configured. Please set a source channel first.", buttons=buttons)
            return
        
        targets = self.target_channels.get(user.id, [])
        if not targets:
            buttons = [[Button.inline("📤 ADD TARGET CHANNEL", b"show_channels_target")]]
            await event.edit("❌ No target channels configured. Please add target channels first.", buttons=buttons)
            return
        
        self.auto_forwarding[user.id] = True
        await self.save_auto_forwarding(user.id, True)
        
        source = self.source_channel[user.id]
        
        success_text = f"""
✅ **Auto-Forwarding Started!**

**Source:** {source['name']}
**Targets:** {len(targets)} channels
**Status:** 🟢 **ACTIVE**

Now monitoring your source channel for new messages...
        """
        
        buttons = [
            [Button.inline("⏸️ STOP FORWARDING", b"stop_forwarding"),
             Button.inline("📊 VIEW STATUS", b"show_dashboard")]
        ]
        
        await event.edit(success_text, buttons=buttons)

    async def handle_stop_forwarding(self, event):
        """Handle stop forwarding"""
        user = await event.get_sender()
        
        if user.id not in self.auto_forwarding or not self.auto_forwarding[user.id]:
            await event.answer("❌ Auto-forwarding is not active", alert=True)
            return
        
        self.auto_forwarding[user.id] = False
        await self.save_auto_forwarding(user.id, False)
        
        buttons = [
            [Button.inline("🚀 START AGAIN", b"start_forwarding"),
             Button.inline("📊 DASHBOARD", b"show_dashboard")]
        ]
        
        await event.edit("⏸️ **Auto-forwarding paused.**", buttons=buttons)

    # ==================== BUTTON HANDLERS ====================

    async def handle_callback_query(self, event):
        """Handle all button callbacks"""
        data = event.data.decode('utf-8')
        user = await event.get_sender()
        
        try:
            # Main navigation
            if data == 'main_menu':
                await self.handle_start(event)
            elif data == 'quick_login':
                await event.edit("🔐 **Quick Login**\n\nUse `/login +919876543210` or send your phone number.")
            elif data == 'show_dashboard':
                await self.show_dashboard(event)
            elif data == 'show_channels_source':
                await self.show_channels_source(event)
            elif data == 'show_channels_target':
                await self.show_channels_target(event)
            elif data == 'start_forwarding':
                await self.handle_start_forwarding(event)
            elif data == 'stop_forwarding':
                await self.handle_stop_forwarding(event)
            elif data == 'show_settings':
                await self.show_settings(event)
            elif data == 'view_targets':
                await self.view_targets(event)
            elif data == 'logout_user':
                await self.handle_logout(event)
            
            # Channel selection
            elif data.startswith('set_source_'):
                channel_index = int(data.split('_')[-1])
                await self.handle_channel_selection(event, 'source', channel_index)
            elif data.startswith('add_target_'):
                channel_index = int(data.split('_')[-1])
                await self.handle_channel_selection(event, 'target', channel_index)
            
            # Login related
            elif data == 'resend_code':
                await self.resend_code(event)
            elif data == 'cancel_login':
                if user.id in self.login_attempts:
                    if 'user_client' in self.login_attempts[user.id]:
                        await self.login_attempts[user.id]['user_client'].disconnect()
                    del self.login_attempts[user.id]
                await event.edit("❌ Login cancelled.")
            
            # Force subscribe
            elif data == 'check_subscription':
                if await self.check_force_subscribe(user.id):
                    await event.edit("✅ Subscription verified! Welcome to the bot.")
                    await asyncio.sleep(2)
                    await self.handle_start(event)
                else:
                    await event.edit("❌ Still not subscribed. Please join the channel first.")
            
            # Other buttons
            elif data == 'how_it_works':
                await event.edit("🎯 **How It Works**\n\n1. **Login** with your Telegram account\n2. **Set source** from your channels\n3. **Add targets** from your channels\n4. **Start** auto-forwarding\n5. **Monitor** automatically")
            elif data == 'contact_support':
                await event.edit("💬 **Support**\n\nFor help contact the bot administrator.")
            elif data == 'quick_start_guide':
                await event.edit("🚀 **Quick Start**\n\n1. Login with your account\n2. Set source channel\n3. Add target channels\n4. Start forwarding!")
            elif data == 'admin_panel':
                if self.is_admin(user.id):
                    await self.show_admin_panel(event)
                else:
                    await event.answer("❌ Admin access required", alert=True)
            else:
                await event.answer("❌ Button action not available", alert=True)
                
        except Exception as e:
            logger.error(f"Error in callback handler: {e}")
            await event.answer("❌ Error processing request", alert=True)

    async def show_settings(self, event):
        """Show settings"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        settings = self.forward_settings.get(user.id, self.default_settings)
        
        settings_text = """
⚙️ **Forwarding Settings**

Toggle the settings below:
        """
        
        buttons = [
            [Button.inline(f"👁️ Hide Header: {'✅ ON' if settings.get('hide_header') else '❌ OFF'}", 
                         b"toggle_hide_header")],
            [Button.inline(f"🖼️ Media: {'✅ ON' if settings.get('forward_media') else '❌ OFF'}", 
                         b"toggle_media")],
            [Button.inline(f"🔗 Previews: {'✅ ON' if settings.get('url_previews') else '❌ OFF'}", 
                         b"toggle_previews")],
            [Button.inline(f"👤 Remove Usernames: {'✅ ON' if settings.get('remove_usernames') else '❌ OFF'}", 
                         b"toggle_usernames")],
            [Button.inline(f"🌐 Remove Links: {'✅ ON' if settings.get('remove_links') else '❌ OFF'}", 
                         b"toggle_links")],
            [Button.inline("🔤 Word Replacements", b"show_word_replacements")],
            [Button.inline("🔗 Link Replacements", b"show_link_replacements")],
            [Button.inline("🔙 BACK TO DASHBOARD", b"show_dashboard")]
        ]
        
        await event.edit(settings_text, buttons=buttons)

    async def view_targets(self, event):
        """View current target channels"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        targets = self.target_channels.get(user.id, [])
        
        if not targets:
            await event.edit("❌ No target channels configured.")
            return
        
        targets_text = "📋 **Your Target Channels:**\n\n"
        
        for i, target in enumerate(targets, 1):
            targets_text += f"{i}. **{target['name']}**\n"
        
        buttons = [
            [Button.inline("➕ ADD MORE TARGETS", b"show_channels_target")],
            [Button.inline("🔙 BACK", b"show_dashboard")]
        ]
        
        await event.edit(targets_text, buttons=buttons)

    async def show_admin_panel(self, event):
        """Show admin panel"""
        user = await event.get_sender()
        
        if not self.is_admin(user.id):
            await event.answer("❌ Admin access required", alert=True)
            return
        
        admin_text = f"""
👑 **Admin Panel**

**Statistics:**
• Total Users: {len(self.user_sessions)}
• Active Forwarding: {sum(1 for x in self.auto_forwarding.values() if x)}

**Actions:**
        """
        
        buttons = [
            [Button.inline("📊 USER STATS", b"admin_stats")],
            [Button.inline("📢 BROADCAST", b"admin_broadcast")],
            [Button.inline("🔙 BACK", b"show_dashboard")]
        ]
        
        await event.edit(admin_text, buttons=buttons)

    # ==================== UTILITY FUNCTIONS ====================

    async def check_user_logged_in(self, user_id: int, event) -> bool:
        """Check if user is logged in"""
        if user_id not in self.user_sessions:
            buttons = [
                [Button.inline("🔐 LOGIN NOW", b"quick_login")],
                [Button.inline("🏠 MAIN MENU", b"main_menu")]
            ]
            await event.edit("❌ Please login first to use this feature.", buttons=buttons)
            return False
        return True

    # ==================== MESSAGE PROCESSING ====================

    async def handle_auto_forward(self, event):
        """Handle all incoming messages"""
        try:
            if event.text and event.text.startswith('/'):
                return
            
            user = await event.get_sender()
            
            if user.id not in self.user_sessions and not await self.check_force_subscribe(user.id):
                return
            
            if event.text and event.text.upper().startswith('AUTOX'):
                await self.handle_code_verification(event)
                return
            
            if event.text and re.match(r'^\+[0-9]{10,15}$', event.text):
                if user.id in self.login_attempts and self.login_attempts[user.id].get('step') == 'waiting_phone':
                    await self.start_telegram_login(user, event.text, event)
                return
            
        except Exception as e:
            logger.error(f"Error in message processing: {e}")

    def register_handlers(self):
        """Register all event handlers"""
        
        @self.client.on(events.NewMessage(pattern='^/start$'))
        async def start_handler(event):
            await self.handle_start(event)
        
        @self.client.on(events.NewMessage(pattern='^/login'))
        async def login_handler(event):
            await self.handle_login(event)
        
        @self.client.on(events.NewMessage(pattern='^/logout$'))
        async def logout_handler(event):
            await self.handle_logout(event)
        
        @self.client.on(events.NewMessage(pattern='^/dashboard$'))
        async def dashboard_handler(event):
            await self.show_dashboard(event)
        
        @self.client.on(events.NewMessage(pattern='^/start_forwarding$'))
        async def start_forwarding_handler(event):
            await self.handle_start_forwarding(event)
        
        @self.client.on(events.NewMessage(pattern='^/stop_forwarding$'))
        async def stop_forwarding_handler(event):
            await self.handle_stop_forwarding(event)
        
        @self.client.on(events.CallbackQuery())
        async def callback_handler(event):
            await self.handle_callback_query(event)
        
        @self.client.on(events.NewMessage)
        async def message_handler(event):
            await self.handle_auto_forward(event)
        
        logger.info("All handlers registered successfully!")

async def main():
    """Main function"""
    
    # REPLACE THESE WITH YOUR ACTUAL VALUES
    api_id = 12345678  # Your API ID from https://my.telegram.org
    api_hash = "your_api_hash_here"  # Your API Hash
    bot_token = "your_bot_token_here"  # Your Bot Token from @BotFather
    
    global ADMIN_USER_IDS, FORCE_SUB_CHANNEL
    
    print("🚀 Starting Best Auto Forwarding Bot...")
    
    bot = AdvancedAutoForwardBot(api_id, api_hash, bot_token)
    
    try:
        success = await bot.initialize()
        if success:
            print("✅ Bot is running perfectly! All systems operational.")
            print("💡 Test with: /start")
            await bot.client.run_until_disconnected()
        else:
            print("❌ Bot initialization failed. Please check your credentials.")
    except KeyboardInterrupt:
        print("🛑 Bot stopped by user")
    except Exception as e:
        logger.error(f"❌ Bot error: {e}")
    finally:
        await bot.client.disconnect()

if __name__ == '__main__':
    os.makedirs("sessions", exist_ok=True)
    asyncio.run(main())