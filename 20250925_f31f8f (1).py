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

# Admin configuration
ADMIN_USER_IDS = [123456789]  # YOUR_USER_ID_HERE

# Force subscribe channel
FORCE_SUB_CHANNEL = "@YourChannel"  # YOUR_CHANNEL_USERNAME_HERE

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
        self.client = TelegramClient('auto_forward_bot', api_id, api_hash)
        self.bot_token = bot_token
        self.db = SQLiteDatabase()
        
        # Runtime storage for performance
        self.user_sessions: Dict[int, Dict] = {}
        self.source_channel: Dict[int, Dict] = {}
        self.target_channels: Dict[int, List] = {}
        self.forward_settings: Dict[int, Dict] = {}
        self.auto_forwarding: Dict[int, bool] = {}
        self.login_attempts: Dict[int, Dict] = {}
        self.user_clients: Dict[int, TelegramClient] = {}
        self.word_replacements: Dict[int, Dict] = {}
        self.link_replacements: Dict[int, Dict] = {}
        
        # Channel selection state
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
            
            # Load data from database
            await self.load_all_data()
            
            # Register handlers
            self.register_handlers()
            
            logger.info("Bot fully initialized!")
                
        except Exception as e:
            logger.error(f"Error during initialization: {e}")

    async def load_all_data(self):
        """Load all data from database"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            # Load users
            cursor.execute("SELECT * FROM users WHERE status = 'logged_in'")
            users = cursor.fetchall()
            for user in users:
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
            sources = cursor.fetchall()
            for source in sources:
                user_id, channel_id, channel_name, username, set_time = source
                self.source_channel[user_id] = {
                    'id': channel_id,
                    'name': channel_name,
                    'username': username,
                    'set_time': set_time
                }
            
            # Load target channels
            cursor.execute("SELECT * FROM target_channels")
            targets = cursor.fetchall()
            for target in targets:
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
            settings = cursor.fetchall()
            for setting in settings:
                user_id, hide_header, forward_media, url_previews, remove_usernames, remove_links = setting
                self.forward_settings[user_id] = {
                    'hide_header': bool(hide_header),
                    'forward_media': bool(forward_media),
                    'url_previews': bool(url_previews),
                    'remove_usernames': bool(remove_usernames),
                    'remove_links': bool(remove_links)
                }
            
            # Load auto forwarding status
            cursor.execute("SELECT * FROM auto_forwarding WHERE is_active = 1")
            active_forwarding = cursor.fetchall()
            for forwarding in active_forwarding:
                user_id, is_active, updated_at = forwarding
                self.auto_forwarding[user_id] = bool(is_active)
            
            # Load word replacements
            cursor.execute("SELECT * FROM word_replacements")
            word_reps = cursor.fetchall()
            for rep in word_reps:
                id, user_id, original, replacement, created_at = rep
                if user_id not in self.word_replacements:
                    self.word_replacements[user_id] = {}
                self.word_replacements[user_id][original] = replacement
            
            # Load link replacements
            cursor.execute("SELECT * FROM link_replacements")
            link_reps = cursor.fetchall()
            for rep in link_reps:
                id, user_id, original, replacement, created_at = rep
                if user_id not in self.link_replacements:
                    self.link_replacements[user_id] = {}
                self.link_replacements[user_id][original] = replacement
            
            conn.close()
            logger.info(f"Data loaded: {len(self.user_sessions)} users, {len(self.source_channel)} sources, {sum(len(t) for t in self.target_channels.values())} targets")
            
        except Exception as e:
            logger.error(f"Error loading data: {e}")

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

    async def delete_word_replacement(self, user_id: int, original: str):
        """Delete word replacement from database"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                DELETE FROM word_replacements 
                WHERE user_id = ? AND original_word = ?
            ''', (user_id, original))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Error deleting word replacement: {e}")
            return False

    async def delete_link_replacement(self, user_id: int, original: str):
        """Delete link replacement from database"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                DELETE FROM link_replacements 
                WHERE user_id = ? AND original_link = ?
            ''', (user_id, original))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Error deleting link replacement: {e}")
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
            return True  # Temporary allow if check fails

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
            
            user_client = TelegramClient(session_name, self.client.api_id, self.client.api_hash)
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
                'user_id': user_entity.id,
                'login_time': datetime.now().isoformat(),
                'status': 'logged_in'
            }
            
            self.user_sessions[user.id] = user_data
            await self.save_user_session(user.id, user_data)
            
            if user.id not in self.forward_settings:
                self.forward_settings[user.id] = self.default_settings.copy()
                await self.save_user_settings(user.id, self.forward_settings[user.id])
            
            # Don't disconnect - keep client active for channel access
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
        """Get user's channels/groups - FIXED VERSION"""
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
                        # Check if it's a channel or supergroup
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
            
            return channels[:10]  # Return top 10 channels
            
        except Exception as e:
            logger.error(f"Error getting user channels: {e}")
            return []

    async def show_channels_source(self, event):
        """Show channels for source selection - FIXED"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        # Try to get user client first
        if user.id not in self.user_clients:
            try:
                session_name = f"sessions/user_{user.id}"
                if os.path.exists(session_name + ".session"):
                    user_client = TelegramClient(session_name, self.client.api_id, self.client.api_hash)
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
            await event.edit("❌ No channels/groups found in your account. Please make sure you have channels or groups.")
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
        
        # Store channel data for selection
        self.awaiting_channel_selection[user.id] = {
            'type': 'source',
            'channels': channels
        }
        
        await event.edit(selection_text, buttons=buttons)

    async def show_channels_target(self, event):
        """Show channels for target selection - FIXED"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        if user.id not in self.user_clients:
            try:
                session_name = f"sessions/user_{user.id}"
                if os.path.exists(session_name + ".session"):
                    user_client = TelegramClient(session_name, self.client.api_id, self.client.api_hash)
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
            await event.edit("❌ No channels/groups found in your account. Please make sure you have channels or groups.")
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
        
        # Store channel data for selection
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
            
            # Check for duplicates
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

    # ==================== WORD/LINK REPLACEMENT SYSTEM ====================

    async def show_word_replacements(self, event):
        """Show word replacements management"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        user_replacements = self.word_replacements.get(user.id, {})
        
        replacements_text = "🔤 **Word Replacements**\n\n"
        
        if user_replacements:
            replacements_text += "**Current Replacements:**\n"
            for original, replacement in user_replacements.items():
                replacements_text += f"• `{original}` → `{replacement}`\n"
        else:
            replacements_text += "No word replacements set.\n"
        
        replacements_text += "\nManage your word replacements:"
        
        buttons = [
            [Button.inline("➕ Add Word Replacement", b"add_word_replacement")],
            [Button.inline("🗑️ Remove Word Replacement", b"remove_word_replacement")] if user_replacements else [],
            [Button.inline("🔙 Back to Settings", b"show_settings")]
        ]
        
        await event.edit(replacements_text, buttons=buttons)

    async def show_link_replacements(self, event):
        """Show link replacements management"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        user_replacements = self.link_replacements.get(user.id, {})
        
        replacements_text = "🔗 **Link Replacements**\n\n"
        
        if user_replacements:
            replacements_text += "**Current Replacements:**\n"
            for original, replacement in user_replacements.items():
                replacements_text += f"• `{original}` → `{replacement}`\n"
        else:
            replacements_text += "No link replacements set.\n"
        
        replacements_text += "\nManage your link replacements:"
        
        buttons = [
            [Button.inline("➕ Add Link Replacement", b"add_link_replacement")],
            [Button.inline("🗑️ Remove Link Replacement", b"remove_link_replacement")] if user_replacements else [],
            [Button.inline("🔙 Back to Settings", b"show_settings")]
        ]
        
        await event.edit(replacements_text, buttons=buttons)

    async def add_word_replacement(self, event):
        """Add word replacement"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        self.awaiting_word_replacement[user.id] = {'step': 'waiting_original'}
        
        await event.edit("🔤 **Add Word Replacement**\n\nPlease send the original word you want to replace:\n\nExample: `hello`")

    async def add_link_replacement(self, event):
        """Add link replacement"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        self.awaiting_link_replacement[user.id] = {'step': 'waiting_original'}
        
        await event.edit("🔗 **Add Link Replacement**\n\nPlease send the original link you want to replace:\n\nExample: `https://old-link.com`")

    async def handle_word_replacement_input(self, event, step: str, text: str):
        """Handle word replacement input"""
        user = await event.get_sender()
        
        if user.id not in self.awaiting_word_replacement:
            return
        
        if step == 'waiting_original':
            self.awaiting_word_replacement[user.id] = {
                'step': 'waiting_replacement',
                'original': text.strip()
            }
            await event.reply("Now send the replacement word:\n\nExample: `hi`")
        
        elif step == 'waiting_replacement':
            original = self.awaiting_word_replacement[user.id]['original']
            replacement = text.strip()
            
            if user.id not in self.word_replacements:
                self.word_replacements[user.id] = {}
            
            self.word_replacements[user.id][original] = replacement
            await self.save_word_replacement(user.id, original, replacement)
            
            del self.awaiting_word_replacement[user.id]
            
            await event.reply(f"✅ Word replacement added!\n\n`{original}` → `{replacement}`")

    async def handle_link_replacement_input(self, event, step: str, text: str):
        """Handle link replacement input"""
        user = await event.get_sender()
        
        if user.id not in self.awaiting_link_replacement:
            return
        
        if step == 'waiting_original':
            self.awaiting_link_replacement[user.id] = {
                'step': 'waiting_replacement',
                'original': text.strip()
            }
            await event.reply("Now send the replacement link:\n\nExample: `https://new-link.com`")
        
        elif step == 'waiting_replacement':
            original = self.awaiting_link_replacement[user.id]['original']
            replacement = text.strip()
            
            if user.id not in self.link_replacements:
                self.link_replacements[user.id] = {}
            
            self.link_replacements[user.id][original] = replacement
            await self.save_link_replacement(user.id, original, replacement)
            
            del self.awaiting_link_replacement[user.id]
            
            await event.reply(f"✅ Link replacement added!\n\n`{original}` → `{replacement}`")

    async def remove_word_replacement(self, event):
        """Remove word replacement"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        user_replacements = self.word_replacements.get(user.id, {})
        
        if not user_replacements:
            await event.edit("❌ No word replacements to remove.")
            return
        
        buttons = []
        for original in user_replacements.keys():
            buttons.append([Button.inline(f"🗑️ {original}", f"remove_word_{hash(original)}")])
        
        buttons.append([Button.inline("🔙 Back", b"show_word_replacements")])
        
        await event.edit("🗑️ **Remove Word Replacement**\n\nSelect the word replacement to remove:", buttons=buttons)

    async def remove_link_replacement(self, event):
        """Remove link replacement"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        user_replacements = self.link_replacements.get(user.id, {})
        
        if not user_replacements:
            await event.edit("❌ No link replacements to remove.")
            return
        
        buttons = []
        for original in user_replacements.keys():
            # Truncate long URLs for button display
            display_text = original[:20] + "..." if len(original) > 20 else original
            buttons.append([Button.inline(f"🗑️ {display_text}", f"remove_link_{hash(original)}")])
        
        buttons.append([Button.inline("🔙 Back", b"show_link_replacements")])
        
        await event.edit("🗑️ **Remove Link Replacement**\n\nSelect the link replacement to remove:", buttons=buttons)

    # ==================== FORWARDING SYSTEM ====================

    async def start_auto_forwarding(self, user_id: int):
        """Start auto forwarding for user"""
        try:
            if user_id not in self.source_channel:
                return False, "❌ Please set a source channel first."
            
            if user_id not in self.target_channels or not self.target_channels[user_id]:
                return False, "❌ Please add at least one target channel."
            
            self.auto_forwarding[user_id] = True
            await self.save_auto_forwarding(user_id, True)
            
            return True, "✅ Auto forwarding started successfully!"
            
        except Exception as e:
            logger.error(f"Error starting auto forwarding: {e}")
            return False, "❌ Error starting auto forwarding."

    async def stop_auto_forwarding(self, user_id: int):
        """Stop auto forwarding for user"""
        try:
            self.auto_forwarding[user_id] = False
            await self.save_auto_forwarding(user_id, False)
            
            return True, "✅ Auto forwarding stopped successfully!"
            
        except Exception as e:
            logger.error(f"Error stopping auto forwarding: {e}")
            return False, "❌ Error stopping auto forwarding."

    async def process_and_forward_message(self, user_id: int, message):
        """Process and forward message with replacements"""
        try:
            if user_id not in self.source_channel or user_id not in self.target_channels:
                return
            
            if not self.auto_forwarding.get(user_id, False):
                return
            
            # Get user settings
            settings = self.forward_settings.get(user_id, self.default_settings)
            
            # Process message text
            text = message.text or message.caption or ""
            processed_text = text
            
            # Apply word replacements
            word_replacements = self.word_replacements.get(user_id, {})
            for original, replacement in word_replacements.items():
                processed_text = processed_text.replace(original, replacement)
            
            # Apply link replacements
            link_replacements = self.link_replacements.get(user_id, {})
            for original, replacement in link_replacements.items():
                processed_text = processed_text.replace(original, replacement)
            
            # Apply other settings
            if settings.get('remove_usernames', False):
                processed_text = re.sub(r'@\w+', '', processed_text)
            
            if settings.get('remove_links', False):
                processed_text = re.sub(r'https?://\S+', '', processed_text)
            
            # Forward to all target channels
            user_client = self.user_clients.get(user_id)
            if not user_client:
                return
            
            for target in self.target_channels[user_id]:
                try:
                    if message.media and settings.get('forward_media', True):
                        # Forward media with processed caption
                        await user_client.send_file(
                            target['id'],
                            message.media,
                            caption=processed_text if processed_text != text else None,
                            parse_mode='html'
                        )
                    elif processed_text:
                        # Forward text message
                        await user_client.send_message(
                            target['id'],
                            processed_text,
                            parse_mode='html'
                        )
                    
                    logger.info(f"Forwarded message to {target['name']}")
                    
                except Exception as e:
                    logger.error(f"Error forwarding to {target['name']}: {e}")
            
        except Exception as e:
            logger.error(f"Error processing message: {e}")

    # ==================== UTILITY FUNCTIONS ====================

    async def check_user_logged_in(self, user_id: int, event) -> bool:
        """Check if user is logged in"""
        if user_id not in self.user_sessions:
            await event.edit("❌ Please login first using /login")
            return False
        return True

    async def show_force_subscribe(self, event):
        """Show force subscribe message"""
        message = f"""
🔒 **Subscription Required**

You need to join our channel to use this bot:

📢 **Channel:** {FORCE_SUB_CHANNEL}

After joining, click the button below to verify.
        """
        
        buttons = [
            [Button.url("📢 Join Channel", f"https://t.me/{FORCE_SUB_CHANNEL[1:]}")],
            [Button.inline("✅ I've Joined", b"check_subscription")]
        ]
        
        await event.reply(message, buttons=buttons)

    async def show_dashboard(self, event):
        """Show user dashboard"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        user_data = self.user_sessions[user.id]
        source_info = self.source_channel.get(user.id, {})
        targets = self.target_channels.get(user.id, [])
        settings = self.forward_settings.get(user.id, self.default_settings)
        is_active = self.auto_forwarding.get(user.id, False)
        
        dashboard_text = f"""
📊 **Dashboard**

👤 **User:** {user_data.get('first_name', 'User')}
📱 **Phone:** `{user_data.get('phone_number', 'N/A')}`
🕒 **Login Time:** {user_data.get('login_time', 'N/A')}

📥 **Source Channel:** {source_info.get('name', 'Not set')}
📤 **Target Channels:** {len(targets)}
🚀 **Auto Forwarding:** {'🟢 ACTIVE' if is_active else '🔴 INACTIVE'}

⚙️ **Settings:**
• Hide Header: {'✅' if settings.get('hide_header') else '❌'}
• Forward Media: {'✅' if settings.get('forward_media') else '❌'}
• URL Previews: {'✅' if settings.get('url_previews') else '❌'}
• Remove Usernames: {'✅' if settings.get('remove_usernames') else '❌'}
• Remove Links: {'✅' if settings.get('remove_links') else '❌'}

🔤 **Word Replacements:** {len(self.word_replacements.get(user.id, {}))}
🔗 **Link Replacements:** {len(self.link_replacements.get(user.id, {}))}
        """
        
        buttons = [
            [Button.inline("📥 Set Source", b"show_channels_source"),
             Button.inline("📤 Manage Targets", b"view_targets")],
            [Button.inline("⚙️ Settings", b"show_settings"),
             Button.inline("🔄 " + ("Stop" if is_active else "Start"), b="stop_forwarding" if is_active else "start_forwarding")],
            [Button.inline("📋 Quick Commands", b"quick_start_guide")]
        ]
        
        await event.edit(dashboard_text, buttons=buttons)

    async def view_targets(self, event):
        """View all target channels"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        targets = self.target_channels.get(user.id, [])
        
        if not targets:
            await event.edit("❌ No target channels added yet.")
            return
        
        targets_text = "📋 **Target Channels**\n\n"
        
        for i, target in enumerate(targets, 1):
            targets_text += f"{i}. **{target['name']}**\n"
        
        targets_text += f"\n**Total:** {len(targets)} channels"
        
        buttons = [
            [Button.inline("➕ Add More", b"show_channels_target"),
             Button.inline("🗑️ Remove Target", b"remove_target_channel")],
            [Button.inline("🔙 Back", b"show_dashboard")]
        ]
        
        await event.edit(targets_text, buttons=buttons)

    async def show_settings(self, event):
        """Show settings menu"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        settings = self.forward_settings.get(user.id, self.default_settings)
        
        settings_text = """
⚙️ **Settings**

Toggle the options below:
        """
        
        buttons = [
            [Button.inline(f"📝 Header: {'✅ Show' if not settings.get('hide_header') else '❌ Hide'}", b"toggle_header")],
            [Button.inline(f"🖼️ Media: {'✅ Forward' if settings.get('forward_media') else '❌ Skip'}", b"toggle_media")],
            [Button.inline(f"🔗 Previews: {'✅ Show' if settings.get('url_previews') else '❌ Hide'}", b"toggle_previews")],
            [Button.inline(f"👤 Usernames: {'✅ Keep' if not settings.get('remove_usernames') else '❌ Remove'}", b"toggle_usernames")],
            [Button.inline(f"🌐 Links: {'✅ Keep' if not settings.get('remove_links') else '❌ Remove'}", b"toggle_links")],
            [Button.inline("🔤 Word Replacements", b"show_word_replacements")],
            [Button.inline("🔗 Link Replacements", b"show_link_replacements")],
            [Button.inline("🔙 Back", b"show_dashboard")]
        ]
        
        await event.edit(settings_text, buttons=buttons)

    async def quick_start_guide(self, event):
        """Show quick start guide"""
        guide_text = """
🚀 **Quick Start Guide**

1. **Login** - Use `/login +919876543210`
2. **Set Source** - Choose your source channel
3. **Add Targets** - Add one or more target channels
4. **Configure** - Adjust settings as needed
5. **Start** - Begin auto forwarding!

📋 **Commands:**
• `/login` - Login with phone number
• `/dashboard` - View your dashboard
• `/settings` - Configure forwarding options
• `/logout` - Logout and clear data

⚙️ **Features:**
• Word & Link replacements
• Media forwarding control
• URL preview management
• Username/link removal
• Multiple target channels
        """
        
        buttons = [
            [Button.inline("📥 Set Source", b"show_channels_source"),
             Button.inline("📤 Add Target", b"show_channels_target")],
            [Button.inline("⚙️ Settings", b"show_settings"),
             Button.inline("📊 Dashboard", b"show_dashboard")],
            [Button.inline("🔙 Main Menu", b"main_menu")]
        ]
        
        await event.edit(guide_text, buttons=buttons)

    # ==================== EVENT HANDLERS ====================

    def register_handlers(self):
        """Register all event handlers"""
        
        @self.client.on(events.NewMessage(pattern='/start'))
        async def start_handler(event):
            user = await event.get_sender()
            
            welcome_text = f"""
🤖 **Advanced Auto Forward Bot**

Welcome, {user.first_name}!

This bot helps you automatically forward messages from one channel to multiple channels with advanced features.

🔧 **Features:**
• Multiple target channels
• Word & link replacements
• Media forwarding control
• Customizable settings
• Real-time processing

Use the buttons below to get started!
            """
            
            buttons = [
                [Button.inline("🔐 Login", b"show_login"),
                 Button.inline("🚀 Quick Start", b"quick_start_guide")],
                [Button.inline("📊 Dashboard", b"show_dashboard"),
                 Button.inline("⚙️ Settings", b"show_settings")],
                [Button.inline("📋 Commands", b"show_commands")]
            ]
            
            await event.reply(welcome_text, buttons=buttons)

        @self.client.on(events.NewMessage(pattern='/login'))
        async def login_handler(event):
            await self.handle_login(event)

        @self.client.on(events.NewMessage(pattern='/dashboard'))
        async def dashboard_handler(event):
            await self.show_dashboard(event)

        @self.client.on(events.NewMessage(pattern='/settings'))
        async def settings_handler(event):
            await self.show_settings(event)

        @self.client.on(events.NewMessage(pattern='/logout'))
        async def logout_handler(event):
            user = await event.get_sender()
            
            if user.id not in self.user_sessions:
                await event.reply("❌ You are not logged in.")
                return
            
            # Disconnect user client if exists
            if user.id in self.user_clients:
                try:
                    await self.user_clients[user.id].disconnect()
                    del self.user_clients[user.id]
                except:
                    pass
            
            # Clear all user data
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
            if user.id in self.word_replacements:
                del self.word_replacements[user.id]
            if user.id in self.link_replacements:
                del self.link_replacements[user.id]
            
            # Clear database data
            await self.delete_user_data(user.id)
            
            await event.reply("✅ Logged out successfully. All your data has been cleared.")

        @self.client.on(events.NewMessage(pattern='/help'))
        async def help_handler(event):
            await self.quick_start_guide(event)

        @self.client.on(events.NewMessage(pattern='/commands'))
        async def commands_handler(event):
            commands_text = """
📋 **Available Commands**

**Basic Commands:**
• `/start` - Start the bot
• `/login` - Login with phone number
• `/dashboard` - View your dashboard
• `/settings` - Configure settings
• `/logout` - Logout and clear data
• `/help` - Show help guide

**Channel Management:**
• Use buttons in dashboard to set channels
• Source channel: Where messages come from
• Target channels: Where messages are forwarded

**Advanced Features:**
• Word replacements (in settings)
• Link replacements (in settings)
• Media forwarding control
• Message filtering options
            """
            await event.reply(commands_text)

        # Handle verification codes with AUTOX prefix
        @self.client.on(events.NewMessage(pattern=r'^AUTOX\d+', func=lambda e: e.is_private))
        async def code_handler(event):
            await self.handle_code_verification(event)

        # Handle word/link replacement inputs
        @self.client.on(events.NewMessage(func=lambda e: e.is_private))
        async def text_handler(event):
            user = await event.get_sender()
            text = event.text.strip()
            
            # Handle word replacement
            if user.id in self.awaiting_word_replacement:
                step = self.awaiting_word_replacement[user.id]['step']
                await self.handle_word_replacement_input(event, step, text)
                return
            
            # Handle link replacement
            if user.id in self.awaiting_link_replacement:
                step = self.awaiting_link_replacement[user.id]['step']
                await self.handle_link_replacement_input(event, step, text)
                return
            
            # Handle phone number input for login
            if user.id in self.login_attempts and self.login_attempts[user.id].get('step') == 'waiting_phone':
                if re.match(r'^\+[0-9]{10,15}$', text):
                    await self.start_telegram_login(user, text, event)
                else:
                    await event.reply("❌ Invalid phone number format. Please use international format: `+919876543210`")

        # Button callbacks
        @self.client.on(events.CallbackQuery)
        async def callback_handler(event):
            user = await event.get_sender()
            data = event.data.decode('utf-8')
            
            try:
                # Login related
                if data == "show_login":
                    await self.handle_login(event)
                elif data == "resend_code":
                    await self.resend_code(event)
                elif data == "cancel_login":
                    if user.id in self.login_attempts:
                        if 'user_client' in self.login_attempts[user.id]:
                            await self.login_attempts[user.id]['user_client'].disconnect()
                        del self.login_attempts[user.id]
                    await event.edit("❌ Login cancelled.")
                
                # Channel selection
                elif data.startswith("set_source_"):
                    channel_index = int(data.split('_')[-1])
                    await self.handle_channel_selection(event, 'source', channel_index)
                elif data.startswith("add_target_"):
                    channel_index = int(data.split('_')[-1])
                    await self.handle_channel_selection(event, 'target', channel_index)
                
                # Dashboard and navigation
                elif data == "main_menu":
                    await event.delete()
                    await self.client.send_message(user.id, "🏠 **Main Menu** - Use buttons to navigate:", 
                                                  buttons=[[Button.inline("📊 Dashboard", b"show_dashboard")]])
                elif data == "show_dashboard":
                    await self.show_dashboard(event)
                elif data == "show_channels_source":
                    await self.show_channels_source(event)
                elif data == "show_channels_target":
                    await self.show_channels_target(event)
                elif data == "view_targets":
                    await self.view_targets(event)
                elif data == "quick_start_guide":
                    await self.quick_start_guide(event)
                elif data == "show_commands":
                    await commands_handler(event)
                
                # Settings toggles
                elif data == "show_settings":
                    await self.show_settings(event)
                elif data == "toggle_header":
                    if user.id in self.forward_settings:
                        self.forward_settings[user.id]['hide_header'] = not self.forward_settings[user.id]['hide_header']
                        await self.save_user_settings(user.id, self.forward_settings[user.id])
                    await self.show_settings(event)
                elif data == "toggle_media":
                    if user.id in self.forward_settings:
                        self.forward_settings[user.id]['forward_media'] = not self.forward_settings[user.id]['forward_media']
                        await self.save_user_settings(user.id, self.forward_settings[user.id])
                    await self.show_settings(event)
                elif data == "toggle_previews":
                    if user.id in self.forward_settings:
                        self.forward_settings[user.id]['url_previews'] = not self.forward_settings[user.id]['url_previews']
                        await self.save_user_settings(user.id, self.forward_settings[user.id])
                    await self.show_settings(event)
                elif data == "toggle_usernames":
                    if user.id in self.forward_settings:
                        self.forward_settings[user.id]['remove_usernames'] = not self.forward_settings[user.id]['remove_usernames']
                        await self.save_user_settings(user.id, self.forward_settings[user.id])
                    await self.show_settings(event)
                elif data == "toggle_links":
                    if user.id in self.forward_settings:
                        self.forward_settings[user.id]['remove_links'] = not self.forward_settings[user.id]['remove_links']
                        await self.save_user_settings(user.id, self.forward_settings[user.id])
                    await self.show_settings(event)
                
                # Word/Link replacements
                elif data == "show_word_replacements":
                    await self.show_word_replacements(event)
                elif data == "show_link_replacements":
                    await self.show_link_replacements(event)
                elif data == "add_word_replacement":
                    await self.add_word_replacement(event)
                elif data == "add_link_replacement":
                    await self.add_link_replacement(event)
                elif data == "remove_word_replacement":
                    await self.remove_word_replacement(event)
                elif data == "remove_link_replacement":
                    await self.remove_link_replacement(event)
                elif data.startswith("remove_word_"):
                    # Handle word removal by hash
                    await event.answer("Feature coming soon!", alert=True)
                elif data.startswith("remove_link_"):
                    # Handle link removal by hash
                    await event.answer("Feature coming soon!", alert=True)
                
                # Forwarding control
                elif data == "start_forwarding":
                    success, message = await self.start_auto_forwarding(user.id)
                    await event.edit(message)
                elif data == "stop_forwarding":
                    success, message = await self.stop_auto_forwarding(user.id)
                    await event.edit(message)
                
                # Force subscribe
                elif data == "check_subscription":
                    if await self.check_force_subscribe(user.id):
                        await event.edit("✅ Thank you for subscribing! You can now use the bot.")
                    else:
                        await event.edit("❌ You haven't joined the channel yet. Please join and try again.")
                
                await event.answer()
                
            except Exception as e:
                logger.error(f"Error in callback handler: {e}")
                await event.answer("❌ An error occurred. Please try again.", alert=True)

    async def run(self):
        """Run the bot"""
        await self.initialize()
        await self.client.run_until_disconnected()

# Main execution
if __name__ == "__main__":
    # Configuration - REPLACE WITH YOUR ACTUAL VALUES
    API_ID = 12345678  # YOUR_API_ID_HERE
    API_HASH = "your_api_hash_here"  # YOUR_API_HASH_HERE
    BOT_TOKEN = "your_bot_token_here"  # YOUR_BOT_TOKEN_HERE
    
    # Create and run bot
    bot = AdvancedAutoForwardBot(API_ID, API_HASH, BOT_TOKEN)
    
    print("🤖 Starting Advanced Auto Forward Bot...")
    asyncio.run(bot.run())