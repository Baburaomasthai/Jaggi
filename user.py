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
from telethon.errors import SessionPasswordNeededError, ChannelPrivateError
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument, MessageMediaWebPage

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
ADMIN_USER_IDS = [6651946441]  # YOUR_USER_ID_HERE

# Force subscribe channel
FORCE_SUB_CHANNEL = "@MrJaggiX"  # YOUR_CHANNEL_USERNAME_HERE

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
        
        # Message handlers for each user's source channel
        self.message_handlers: Dict[int, Any] = {}
        
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
            
            # Start message listeners for active users
            await self.start_all_message_listeners()
            
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

    async def start_all_message_listeners(self):
        """Start message listeners for all users with active forwarding"""
        for user_id in self.auto_forwarding:
            if self.auto_forwarding[user_id] and user_id in self.source_channel:
                await self.start_message_listener(user_id)

    async def start_message_listener(self, user_id: int):
        """Start listening to messages from source channel for a user"""
        try:
            if user_id not in self.user_clients or user_id not in self.source_channel:
                return
            
            # Remove existing handler if any
            if user_id in self.message_handlers:
                try:
                    self.user_clients[user_id].remove_event_handler(self.message_handlers[user_id])
                except:
                    pass
                del self.message_handlers[user_id]
            
            source_channel_id = self.source_channel[user_id]['id']
            user_client = self.user_clients[user_id]
            
            @user_client.on(events.NewMessage(chats=source_channel_id))
            async def message_handler(event):
                await self.process_and_forward_message(user_id, event.message)
            
            self.message_handlers[user_id] = message_handler
            logger.info(f"Started message listener for user {user_id} on channel {source_channel_id}")
            
        except Exception as e:
            logger.error(f"Error starting message listener for user {user_id}: {e}")

    async def stop_message_listener(self, user_id: int):
        """Stop listening to messages from source channel for a user"""
        try:
            if user_id in self.message_handlers and user_id in self.user_clients:
                try:
                    self.user_clients[user_id].remove_event_handler(self.message_handlers[user_id])
                except:
                    pass
                del self.message_handlers[user_id]
                logger.info(f"Stopped message listener for user {user_id}")
        except Exception as e:
            logger.error(f"Error stopping message listener for user {user_id}: {e}")

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
            
            await event.answer("✅ Verification code resent! Please check your Telegram app.", alert=True)
        except Exception as e:
            logger.error(f"Error resending code: {e}")
            await event.answer("❌ Error resending code. Please try again.", alert=True)

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

**Important Notes:**
📥 **Source Channel:** Your user account will read messages (no admin rights needed)
📤 **Target Channel:** Bot needs to be admin to send messages
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
        
        selection_text += "\n**Important:** Your user account will read messages from this channel (admin rights NOT required)"
        
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
        
        selection_text += "\n**Important:** Bot must be admin in target channels to send messages"
        
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

**Note:** Your user account will read messages from this channel. No admin rights required.

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

**Important:** Make sure the bot is added as admin in this channel with post messages permission.

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

    # ==================== MESSAGE PROCESSING ====================

    async def process_and_forward_message(self, user_id: int, message):
        """Process and forward message with formatting preserved"""
        try:
            if (user_id not in self.source_channel or 
                user_id not in self.target_channels or 
                not self.target_channels[user_id]):
                return
            
            if not self.auto_forwarding.get(user_id, False):
                return
            
            settings = self.forward_settings.get(user_id, self.default_settings)
            
            # Get message text
            text = ""
            if hasattr(message, 'text') and message.text:
                text = message.text
            elif hasattr(message, 'message') and message.message:
                text = message.message
            elif hasattr(message, 'caption') and message.caption:
                text = message.caption
            
            # Process text with replacements
            processed_text = await self.process_message_text(user_id, text)
            
            # Forward to all target channels
            for target in self.target_channels[user_id]:
                try:
                    await self.forward_message_to_target(
                        user_id, message, target, processed_text, settings
                    )
                    await asyncio.sleep(1)  # Rate limiting
                except Exception as e:
                    logger.error(f"Error forwarding to target {target['name']}: {e}")
                    
        except Exception as e:
            logger.error(f"Error processing message: {e}")

    async def process_message_text(self, user_id: int, text: str) -> str:
        """Process message text with replacements"""
        if not text:
            return text
        
        processed_text = text
        
        # Apply word replacements
        if user_id in self.word_replacements:
            for original, replacement in self.word_replacements[user_id].items():
                processed_text = processed_text.replace(original, replacement)
        
        # Apply link replacements
        if user_id in self.link_replacements:
            for original, replacement in self.link_replacements[user_id].items():
                processed_text = processed_text.replace(original, replacement)
        
        # Apply settings
        settings = self.forward_settings.get(user_id, self.default_settings)
        
        if settings.get('remove_usernames', False):
            processed_text = re.sub(r'@\w+', '', processed_text)
        
        if settings.get('remove_links', False):
            processed_text = re.sub(r'https?://\S+', '', processed_text)
        
        return processed_text.strip()

    async def forward_message_to_target(self, user_id: int, message, target: Dict, text: str, settings: Dict):
        """Forward message to target channel with proper formatting"""
        try:
            if user_id not in self.user_clients:
                return
            
            user_client = self.user_clients[user_id]
            
            # Check if message has media
            has_media = message.media and not isinstance(message.media, type(None))
            
            if has_media and settings.get('forward_media', True):
                # Forward media with caption - preserving formatting
                if text:
                    await user_client.send_file(
                        target['id'],
                        message.media,
                        caption=text,
                        parse_mode='html'  # This preserves formatting
                    )
                else:
                    await user_client.send_file(
                        target['id'],
                        message.media
                    )
            else:
                # Send only text - preserving formatting
                if text:
                    await user_client.send_message(
                        target['id'],
                        text,
                        parse_mode='html'  # This preserves formatting
                    )
            
            logger.info(f"Message forwarded to {target['name']}")
            
        except Exception as e:
            logger.error(f"Error forwarding message to {target['name']}: {e}")
            # Try fallback method
            try:
                await user_client.forward_messages(target['id'], message)
                logger.info(f"Fallback forwarding successful to {target['name']}")
            except Exception as fallback_error:
                logger.error(f"Fallback forwarding also failed: {fallback_error}")

    # ==================== BOT COMMANDS AND HANDLERS ====================

    def register_handlers(self):
        """Register all bot handlers"""
        
        @self.client.on(events.NewMessage(pattern='/start'))
        async def start_handler(event):
            await self.handle_start(event)
        
        @self.client.on(events.NewMessage(pattern='/login'))
        async def login_handler(event):
            await self.handle_login(event)
        
        @self.client.on(events.NewMessage(pattern='/logout'))
        async def logout_handler(event):
            await self.handle_logout(event)
        
        @self.client.on(events.NewMessage(pattern='/dashboard'))
        async def dashboard_handler(event):
            await self.show_dashboard(event)
        
        @self.client.on(events.NewMessage(pattern='/settings'))
        async def settings_handler(event):
            await self.show_settings(event)
        
        @self.client.on(events.NewMessage(pattern='/help'))
        async def help_handler(event):
            await self.show_help(event)
        
        # Handle verification codes with AUTOX prefix
        @self.client.on(events.NewMessage(pattern=r'^AUTOX\d+', func=lambda e: e.is_private))
        async def code_handler(event):
            await self.handle_code_verification(event)
        
        # Handle phone number input
        @self.client.on(events.NewMessage(pattern=r'^\+\d{10,15}$', func=lambda e: e.is_private))
        async def phone_handler(event):
            user = await event.get_sender()
            if user.id in self.login_attempts and self.login_attempts[user.id].get('step') == 'waiting_phone':
                await self.start_telegram_login(user, event.text.strip(), event)
        
        # Inline button callbacks
        @self.client.on(events.CallbackQuery)
        async def callback_handler(event):
            await self.handle_callbacks(event)

    async def handle_callbacks(self, event):
        """Handle all inline button callbacks"""
        try:
            data = event.data.decode('utf-8')
            user = await event.get_sender()
            
            logger.info(f"Callback from {user.id}: {data}")
            
            # Handle login-related callbacks
            if data == "resend_code":
                await self.resend_code(event)
            elif data == "cancel_login":
                await self.cancel_login(event)
            
            # Handle main menu callbacks
            elif data == "main_menu":
                await self.show_main_menu(event)
            elif data == "show_dashboard":
                await self.show_dashboard(event)
            elif data == "show_settings":
                await self.show_settings(event)
            elif data == "quick_start_guide":
                await self.show_quick_start(event)
            elif data == "show_help":
                await self.show_help(event)
            
            # Handle channel selection callbacks
            elif data == "show_channels_source":
                await self.show_channels_source(event)
            elif data == "show_channels_target":
                await self.show_channels_target(event)
            elif data == "view_targets":
                await self.view_target_channels(event)
            
            # Handle forwarding control callbacks
            elif data == "start_forwarding":
                await self.start_auto_forwarding(user.id, event)
            elif data == "stop_forwarding":
                await self.stop_auto_forwarding(user.id, event)
            
            # Handle settings callbacks
            elif data == "toggle_hide_header":
                await self.toggle_setting(user.id, 'hide_header', event)
            elif data == "toggle_forward_media":
                await self.toggle_setting(user.id, 'forward_media', event)
            elif data == "toggle_url_previews":
                await self.toggle_setting(user.id, 'url_previews', event)
            elif data == "toggle_remove_usernames":
                await self.toggle_setting(user.id, 'remove_usernames', event)
            elif data == "toggle_remove_links":
                await self.toggle_setting(user.id, 'remove_links', event)
            
            # Handle channel number selections
            elif data.startswith("set_source_"):
                channel_index = int(data.split("_")[2])
                await self.handle_channel_selection(event, 'source', channel_index)
            elif data.startswith("add_target_"):
                channel_index = int(data.split("_")[2])
                await self.handle_channel_selection(event, 'target', channel_index)
            
            else:
                await event.answer("❌ Unknown command", alert=True)
                
        except Exception as e:
            logger.error(f"Error handling callback: {e}")
            await event.answer("❌ Error processing request", alert=True)

    async def handle_start(self, event):
        """Handle /start command"""
        user = await event.get_sender()
        
        if not await self.check_force_subscribe(user.id):
            await self.show_force_subscribe(event)
            return
        
        welcome_text = """
🤖 **Advanced Auto-Forward Bot**

Welcome! I can automatically forward messages from one channel to multiple channels while preserving formatting.

**How it works:**
📥 **Source Channel:** Your user account reads messages (NO admin rights needed)
📤 **Target Channel:** Bot sends messages (Bot needs admin rights)

**Main Features:**
✅ Preserve text formatting (bold, italic, links)
✅ Word and link replacement system  
✅ Multiple target channels
✅ Customizable settings
✅ Media forwarding support

Use the buttons below to get started!
        """
        
        buttons = []
        
        if user.id in self.user_sessions:
            buttons.extend([
                [Button.inline("📊 Dashboard", b"show_dashboard"),
                 Button.inline("⚙️ Settings", b"show_settings")],
                [Button.inline("🚀 Quick Start", b"quick_start_guide")]
            ])
        else:
            buttons.append([Button.inline("🔐 Login", b"main_menu")])
        
        buttons.append([Button.inline("📖 Help", b"show_help")])
        
        await event.reply(welcome_text, buttons=buttons)

    async def show_main_menu(self, event):
        """Show main menu"""
        user = await event.get_sender()
        
        if not await self.check_force_subscribe(user.id):
            await self.show_force_subscribe(event)
            return
        
        menu_text = "🏠 **Main Menu**\n\nSend /login command & for more click on 📖 Help guide:"
        
        buttons = []
        
        if user.id in self.user_sessions:
            buttons.extend([
                [Button.inline("📥 Set Source Channel", b"show_channels_source"),
                 Button.inline("📤 Add Target Channel", b"show_channels_target")],
                [Button.inline("📊 Dashboard", b"show_dashboard"),
                 Button.inline("⚙️ Settings", b"show_settings")],
                [Button.inline("🔄 Start/Stop Forwarding", b"show_dashboard")]
            ])
        else:
            # buttons.append([Button.inline("🔐 Login with Phone", b"show_login_options")])
        
        buttons.append([Button.inline("📖 Help Guide", b"show_help")])
        
        await event.edit(menu_text, buttons=buttons)

    async def show_dashboard(self, event):
        """Show user dashboard"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        dashboard_text = "📊 **Dashboard**\n\n"
        
        # User info
        user_data = self.user_sessions[user.id]
        dashboard_text += f"👤 **User:** {user_data.get('first_name', 'Unknown')}\n"
        dashboard_text += f"📱 **Phone:** `{user_data.get('phone_number', 'Unknown')}`\n\n"
        
        # Source channel info
        if user.id in self.source_channel:
            source = self.source_channel[user.id]
            dashboard_text += f"📥 **Source:** {source['name']}\n"
            if source.get('username'):
                dashboard_text += f"🌐 **Username:** @{source['username']}\n"
        else:
            dashboard_text += "📥 **Source:** Not set\n"
        
        dashboard_text += "\n"
        
        # Target channels info
        if user.id in self.target_channels and self.target_channels[user.id]:
            targets = self.target_channels[user.id]
            dashboard_text += f"📤 **Targets:** {len(targets)} channels\n"
            for i, target in enumerate(targets[:3], 1):
                dashboard_text += f"  {i}. {target['name']}\n"
            if len(targets) > 3:
                dashboard_text += f"  ... and {len(targets) - 3} more\n"
        else:
            dashboard_text += "📤 **Targets:** No channels added\n"
        
        dashboard_text += "\n"
        
        # Auto-forwarding status
        status = "🟢 **ACTIVE**" if self.auto_forwarding.get(user.id, False) else "🔴 **INACTIVE**"
        dashboard_text += f"🔄 **Auto-Forwarding:** {status}\n\n"
        
        # Important notes
        dashboard_text += "**Important Notes:**\n"
        dashboard_text += "• Source: User account reads (no admin needed)\n"
        dashboard_text += "• Target: Bot must be admin to send messages\n"
        
        buttons = []
        
        # Control buttons based on setup
        if user.id in self.source_channel and user.id in self.target_channels and self.target_channels[user.id]:
            if self.auto_forwarding.get(user.id, False):
                buttons.append([Button.inline("⏹️ Stop Forwarding", b"stop_forwarding")])
            else:
                buttons.append([Button.inline("🚀 Start Forwarding", b"start_forwarding")])
        
        buttons.extend([
            [Button.inline("📥 Manage Source", b"show_channels_source"),
             Button.inline("📤 Manage Targets", b"view_targets")],
            [Button.inline("⚙️ Settings", b"show_settings"),
             Button.inline("🔄 Refresh", b"show_dashboard")],
            [Button.inline("🔙 Main Menu", b"main_menu")]
        ])
        
        await event.edit(dashboard_text, buttons=buttons)

    async def show_settings(self, event):
        """Show user settings"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        settings = self.forward_settings.get(user.id, self.default_settings)
        
        settings_text = "⚙️ **Settings**\n\n"
        
        settings_text += "**Current Settings:**\n"
        settings_text += f"📰 Hide Header: {'✅ ON' if settings['hide_header'] else '❌ OFF'}\n"
        settings_text += f"🖼️ Forward Media: {'✅ ON' if settings['forward_media'] else '❌ OFF'}\n"
        settings_text += f"🔗 URL Previews: {'✅ ON' if settings['url_previews'] else '❌ OFF'}\n"
        settings_text += f"👤 Remove Usernames: {'✅ ON' if settings['remove_usernames'] else '❌ OFF'}\n"
        settings_text += f"🌐 Remove Links: {'✅ ON' if settings['remove_links'] else '❌ OFF'}\n"
        
        buttons = [
            [Button.inline(f"{'❌' if settings['hide_header'] else '✅'} Hide Header", b"toggle_hide_header"),
             Button.inline(f"{'❌' if settings['forward_media'] else '✅'} Forward Media", b"toggle_forward_media")],
            [Button.inline(f"{'❌' if settings['url_previews'] else '✅'} URL Previews", b"toggle_url_previews"),
             Button.inline(f"{'❌' if settings['remove_usernames'] else '✅'} Remove Usernames", b"toggle_remove_usernames")],
            [Button.inline(f"{'❌' if settings['remove_links'] else '✅'} Remove Links", b"toggle_remove_links")],
            [Button.inline("🔙 Back", b"show_dashboard")]
        ]
        
        await event.edit(settings_text, buttons=buttons)

    async def toggle_setting(self, user_id: int, setting_name: str, event):
        """Toggle user setting"""
        if user_id not in self.forward_settings:
            self.forward_settings[user_id] = self.default_settings.copy()
        
        self.forward_settings[user_id][setting_name] = not self.forward_settings[user_id][setting_name]
        await self.save_user_settings(user_id, self.forward_settings[user_id])
        
        await self.show_settings(event)

    async def view_target_channels(self, event):
        """View all target channels"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        if user.id not in self.target_channels or not self.target_channels[user.id]:
            await event.edit("❌ No target channels added yet.")
            return
        
        targets = self.target_channels[user.id]
        targets_text = "📤 **Target Channels**\n\n"
        
        for i, target in enumerate(targets, 1):
            targets_text += f"{i}. **{target['name']}**\n"
            if target.get('username'):
                targets_text += f"   @{target['username']}\n"
            targets_text += f"   Added: {target['added_time'][:10]}\n\n"
        
        targets_text += "**Remember:** Bot must be admin in these channels!"
        
        buttons = [
            [Button.inline("➕ Add More Targets", b"show_channels_target")],
            [Button.inline("🔙 Back", b"show_dashboard")]
        ]
        
        await event.edit(targets_text, buttons=buttons)

    async def start_auto_forwarding(self, user_id: int, event):
        """Start auto forwarding"""
        try:
            if user_id not in self.source_channel:
                await event.edit("❌ Please set a source channel first.")
                return
            
            if user_id not in self.target_channels or not self.target_channels[user_id]:
                await event.edit("❌ Please add at least one target channel.")
                return
            
            self.auto_forwarding[user_id] = True
            await self.save_auto_forwarding(user_id, True)
            
            # Start message listener
            await self.start_message_listener(user_id)
            
            success_text = """
✅ **Auto-forwarding started!**

Messages will now be automatically forwarded from source to target channels.

**How it works:**
📥 Source: Your user account reads messages
📤 Target: Bot sends messages (must be admin)
🔄 Start Forwarding: Everything Auto Forwarded
            """
            
            await event.edit(success_text)
            
        except Exception as e:
            logger.error(f"Error starting auto forwarding: {e}")
            await event.edit("❌ Error starting auto-forwarding. Please try again.")

    async def stop_auto_forwarding(self, user_id: int, event):
        """Stop auto forwarding"""
        try:
            self.auto_forwarding[user_id] = False
            await self.save_auto_forwarding(user_id, False)
            
            # Stop message listener
            await self.stop_message_listener(user_id)
            
            await event.edit("⏹️ **Auto-forwarding stopped!**\n\nNo new messages will be forwarded.")
            
        except Exception as e:
            logger.error(f"Error stopping auto forwarding: {e}")
            await event.edit("❌ Error stopping auto-forwarding. Please try again.")

    async def handle_logout(self, event):
        """Handle user logout"""
        user = await event.get_sender()
        
        if user.id not in self.user_sessions:
            await event.reply("❌ You are not logged in.")
            return
        
        try:
            # Stop forwarding
            if user.id in self.auto_forwarding and self.auto_forwarding[user.id]:
                await self.stop_auto_forwarding(user.id, event)
            
            # Close user client
            if user.id in self.user_clients:
                try:
                    await self.user_clients[user.id].disconnect()
                except:
                    pass
                del self.user_clients[user.id]
            
            # Remove message handler
            if user.id in self.message_handlers:
                try:
                    self.user_clients[user.id].remove_event_handler(self.message_handlers[user.id])
                except:
                    pass
                del self.message_handlers[user.id]
            
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
                del self.auto_forwarding[user_id]
            if user.id in self.word_replacements:
                del self.word_replacements[user.id]
            if user.id in self.link_replacements:
                del self.link_replacements[user.id]
            
            # Clear any pending states
            for state_dict in [self.login_attempts, self.awaiting_channel_selection]:
                if user.id in state_dict:
                    del state_dict[user.id]
            
            # Delete from database
            await self.delete_user_data(user.id)
            
            await event.reply("✅ Logout successful! All your data has been removed.")
            
        except Exception as e:
            logger.error(f"Error during logout: {e}")
            await event.reply("❌ Error during logout. Please try again.")

    async def show_quick_start(self, event):
        """Show quick start guide"""
        guide_text = """
🚀 **Quick Start Guide**

**Step 1: Login**
- Use `/login` with your phone number
- Enter verification code with `AUTOX123456` format

**Step 2: Set Source Channel**
- Click "Set Source Channel"
- Select from your channels/groups
- ✅ **No admin rights required** for source

**Step 3: Add Target Channels**  
- Click "Add Target Channel"
- Select one or more target channels
- ⚠️ **Bot must be admin** in target channels

**Step 4: Start Forwarding**
- Click "Start Forwarding" on dashboard
- Messages will auto-forward with formatting preserved!

**Key Points:**
✅ Source: User reads (no admin needed)
✅ Target: Bot sends (must be admin)  
✅ Formatting: Bold, italic, links preserved
✅ Media: Photos, documents supported
        """
        
        buttons = [
            [Button.inline("🔐 Login Now", b"main_menu")],
            [Button.inline("📖 Detailed Help", b"show_help")]
        ]
        
        if hasattr(event, 'edit'):
            await event.edit(guide_text, buttons=buttons)
        else:
            await event.reply(guide_text, buttons=buttons)

    async def show_help(self, event):
        """Show detailed help"""
        help_text = """
📖 **Advanced Auto-Forward Bot Help**

**How It Works:**
📥 **Source Channel:** Your user account reads messages (NO admin rights needed)
📤 **Target Channel:** Bot sends messages (Bot MUST be admin with post permission)

**Basic Commands:**
`/start` - Start the bot
`/login` - Login with phone number  
`/logout` - Logout and clear data
`/dashboard` - View status dashboard
`/settings` - Configure settings
`/help` - Show this help

**Setup Requirements:**
1. **User Account:** Must be member of source channel
2. **Bot Account:** Must be admin in target channels
3. **Permissions:** Post messages permission in targets

**Text Formatting:**
All text formatting is automatically preserved:
- **Bold**, *Italic*, __Underline__
- `Monospace` and code formatting  
- Links and mentions
- Custom emojis and symbols

**Troubleshooting:**
- Bot not sending? Check admin rights in target
- Messages not forwarding? Verify source channel
- Formatting lost? Ensure proper channel permissions
- Media not forwarding? Check "Forward Media" setting

**Support:**
Contact admin if you need assistance with setup.
        """
        
        buttons = [[Button.inline("🔙 Back", b"main_menu")]]
        
        if hasattr(event, 'edit'):
            await event.edit(help_text, buttons=buttons)
        else:
            await event.reply(help_text, buttons=buttons)

    async def show_force_subscribe(self, event):
        """Show force subscribe message"""
        force_sub_text = f"""
📢 **Subscription Required**

To use this bot, you need to join our channel first!

**Channel:** {FORCE_SUB_CHANNEL}

Please join the channel and then try again.

After joining, send `/start` to continue.
        """
        
        await event.reply(force_sub_text)

    async def cancel_login(self, event):
        """Cancel login process"""
        user = await event.get_sender()
        
        if user.id in self.login_attempts:
            login_data = self.login_attempts[user.id]
            if 'user_client' in login_data:
                try:
                    await login_data['user_client'].disconnect()
                except:
                    pass
            del self.login_attempts[user.id]
        
        await event.edit("❌ Login cancelled.")

    async def check_user_logged_in(self, user_id: int, event) -> bool:
        """Check if user is logged in"""
        if user_id not in self.user_sessions:
            if hasattr(event, 'edit'):
                await event.edit("❌ Please login first using `/login`")
            else:
                await event.reply("❌ Please login first using `/login`")
            return False
        return True

    async def run(self):
        """Run the bot"""
        await self.initialize()
        await self.client.run_until_disconnected()

# Bot configuration
API_ID = 28093492  # YOUR_API_ID_HERE
API_HASH = '2d18ff97ebdfc2f1f3a2596c48e3b4e4'  # YOUR_API_HASH_HERE
BOT_TOKEN = '7931829452:AAEskMBAsT6G6bAhD5sS3vBRu4smmYgAU_o'  # YOUR_BOT_TOKEN_HERE

if __name__ == "__main__":
    # Create necessary directories
    os.makedirs("sessions", exist_ok=True)
    
    # Initialize and run bot
    bot = AdvancedAutoForwardBot(API_ID, API_HASH, BOT_TOKEN)
    
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot error: {e}")
