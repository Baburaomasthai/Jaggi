import os
import logging
import asyncio
import aiosqlite
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
import re
import json
from urllib.parse import urlparse
from telethon import TelegramClient, events, Button, errors
from telethon.tl.types import User, Channel, Message, Dialog, MessageMediaPhoto, MessageMediaDocument, MessageMediaWebPage
from telethon.tl.functions.auth import SendCodeRequest, SignInRequest
from telethon.errors import SessionPasswordNeededError, ChannelPrivateError, FloodWaitError, AuthKeyError
from telethon.tl.functions.channels import JoinChannelRequest, GetParticipantsRequest
from telethon.tl.types import ChannelParticipantsSearch

# Enhanced logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot_advanced.log', encoding='utf-8', mode='a'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Admin configuration
ADMIN_USER_IDS = [6651946441]  # Replace with your user ID

# Force subscribe channel (optional)
FORCE_SUB_CHANNEL = "@MrJaggiX"  # Replace with your channel username

class AdvancedSQLiteDatabase:
    """Advanced SQLite Database System with connection pooling"""
    
    def __init__(self, db_path: str = "bot_data_advanced.db"):
        self.db_path = db_path
        self._lock = asyncio.Lock()
    
    async def init_database(self):
        """Initialize database tables asynchronously"""
        async with aiosqlite.connect(self.db_path) as db:
            # Users table with enhanced fields
            await db.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    phone_number TEXT,
                    first_name TEXT,
                    username TEXT,
                    login_time TEXT,
                    status TEXT DEFAULT 'logged_in',
                    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Source channels table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS source_channels (
                    user_id INTEGER PRIMARY KEY,
                    channel_id INTEGER,
                    channel_name TEXT,
                    username TEXT,
                    set_time TEXT,
                    last_message_id INTEGER DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                )
            ''')
            
            # Target channels table with priority support
            await db.execute('''
                CREATE TABLE IF NOT EXISTS target_channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    channel_id INTEGER,
                    channel_name TEXT,
                    username TEXT,
                    added_time TEXT,
                    priority INTEGER DEFAULT 1,
                    is_active BOOLEAN DEFAULT 1,
                    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
                    UNIQUE(user_id, channel_id)
                )
            ''')
            
            # Enhanced settings table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id INTEGER PRIMARY KEY,
                    hide_header BOOLEAN DEFAULT 0,
                    forward_media BOOLEAN DEFAULT 1,
                    url_previews BOOLEAN DEFAULT 1,
                    remove_usernames BOOLEAN DEFAULT 0,
                    remove_links BOOLEAN DEFAULT 0,
                    caption_forward BOOLEAN DEFAULT 1,
                    delay_seconds INTEGER DEFAULT 1,
                    max_message_length INTEGER DEFAULT 4000,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                )
            ''')
            
            # Auto forwarding status with statistics
            await db.execute('''
                CREATE TABLE IF NOT EXISTS auto_forwarding (
                    user_id INTEGER PRIMARY KEY,
                    is_active BOOLEAN DEFAULT 0,
                    total_forwarded INTEGER DEFAULT 0,
                    last_forwarded TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                )
            ''')
            
            # Word replacements table with case sensitivity
            await db.execute('''
                CREATE TABLE IF NOT EXISTS word_replacements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    original_word TEXT,
                    replacement_word TEXT,
                    case_sensitive BOOLEAN DEFAULT 0,
                    is_regex BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
                    UNIQUE(user_id, original_word)
                )
            ''')
            
            # Enhanced link replacements
            await db.execute('''
                CREATE TABLE IF NOT EXISTS link_replacements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    original_link TEXT,
                    replacement_link TEXT,
                    preserve_query BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
                    UNIQUE(user_id, original_link)
                )
            ''')
            
            # Message history for duplicate prevention
            await db.execute('''
                CREATE TABLE IF NOT EXISTS message_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    source_channel_id INTEGER,
                    message_id INTEGER,
                    forwarded_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, source_channel_id, message_id)
                )
            ''')
            
            # Error logging table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS error_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    error_type TEXT,
                    error_message TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            await db.commit()
        
        logger.info("Advanced database initialized successfully")
    
    async def execute(self, query: str, params: Tuple = ()) -> Any:
        """Execute a query with error handling"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(query, params) as cursor:
                    if query.strip().upper().startswith('SELECT'):
                        return await cursor.fetchall()
                    else:
                        await db.commit()
                        return cursor.rowcount
        except Exception as e:
            logger.error(f"Database error: {e}")
            raise
    
    async def fetch_one(self, query: str, params: Tuple = ()) -> Optional[Tuple]:
        """Fetch a single row"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(query, params) as cursor:
                    return await cursor.fetchone()
        except Exception as e:
            logger.error(f"Database fetch error: {e}")
            return None

class AdvancedAutoForwardBot:
    def __init__(self, api_id: int, api_hash: str, bot_token: str):
        self.client = TelegramClient('auto_forward_bot_session', api_id, api_hash)
        self.bot_token = bot_token
        self.api_id = api_id
        self.api_hash = api_hash
        self.db = AdvancedSQLiteDatabase()
        
        # Enhanced runtime storage
        self.user_sessions: Dict[int, Dict] = {}
        self.source_channels: Dict[int, Dict] = {}
        self.target_channels: Dict[int, List[Dict]] = {}
        self.forward_settings: Dict[int, Dict] = {}
        self.auto_forwarding: Dict[int, bool] = {}
        self.forwarding_stats: Dict[int, Dict] = {}
        self.login_attempts: Dict[int, Dict] = {}
        self.user_clients: Dict[int, TelegramClient] = {}
        self.word_replacements: Dict[int, List[Dict]] = {}
        self.link_replacements: Dict[int, List[Dict]] = {}
        
        # Enhanced state management
        self.user_states: Dict[int, Dict] = {}
        self.message_handlers: Dict[int, Any] = {}
        self.rate_limits: Dict[int, Dict] = {}
        self.channel_selection: Dict[int, Dict] = {}
        
        # Default enhanced settings
        self.default_settings = {
            'hide_header': False,
            'forward_media': True,
            'url_previews': True,
            'remove_usernames': False,
            'remove_links': False,
            'caption_forward': True,
            'delay_seconds': 1,
            'max_message_length': 4000
        }
        
        # Rate limiting configuration
        self.rate_limit_config = {
            'message_forward': {'max_count': 10, 'window': 60},  # 10 messages per minute
            'channel_operations': {'max_count': 5, 'window': 60}  # 5 operations per minute
        }

    async def initialize(self):
        """Enhanced initialization with error recovery"""
        try:
            # Create necessary directories
            os.makedirs("sessions", exist_ok=True)
            os.makedirs("backups", exist_ok=True)
            
            # Initialize database first
            await self.db.init_database()
            
            # Start the bot client
            await self.client.start(bot_token=self.bot_token)
            logger.info("🤖 Advanced Auto Forward Bot started successfully!")
            
            # Load data from database
            await self.load_all_data()
            
            # Register enhanced handlers
            self.register_enhanced_handlers()
            
            # Start message listeners for active users
            await self.start_all_message_listeners()
            
            # Set bot commands
            await self.set_bot_commands()
            
            logger.info("✅ Bot fully initialized and ready!")
            
        except Exception as e:
            logger.error(f"❌ Initialization error: {e}")
            raise

    async def set_bot_commands(self):
        """Set bot commands for better UX"""
        commands = [
            ('start', 'Start the bot'),
            ('login', 'Login with your account'),
            ('dashboard', 'Show your dashboard'),
            ('settings', 'Configure forwarding settings'),
            ('help', 'Get help and instructions'),
            ('logout', 'Logout from the bot')
        ]
        
        try:
            from telethon.tl.functions.bots import SetBotCommandsRequest
            from telethon.tl.types import BotCommand, BotCommandScopeDefault
            
            await self.client(SetBotCommandsRequest(
                scope=BotCommandScopeDefault(),
                lang_code='en',
                commands=[BotCommand(command=cmd, description=desc) for cmd, desc in commands]
            ))
            logger.info("✅ Bot commands set successfully")
        except Exception as e:
            logger.warning(f"⚠️ Could not set bot commands: {e}")

    async def load_all_data(self):
        """Enhanced data loading with error handling"""
        try:
            # Load users
            users = await self.db.execute("SELECT * FROM users WHERE status = 'logged_in'")
            for user in users:
                user_id, phone, first_name, username, login_time, status, last_active, created_at = user
                self.user_sessions[user_id] = {
                    'phone_number': phone,
                    'first_name': first_name,
                    'username': username,
                    'login_time': login_time,
                    'status': status,
                    'last_active': last_active
                }
                
                # Try to restore user client session
                await self.restore_user_client(user_id)

            # Load source channels
            sources = await self.db.execute("SELECT * FROM source_channels")
            for source in sources:
                user_id, channel_id, channel_name, username, set_time, last_message_id = source
                self.source_channels[user_id] = {
                    'id': channel_id,
                    'name': channel_name,
                    'username': username,
                    'set_time': set_time,
                    'last_message_id': last_message_id or 0
                }

            # Load target channels
            targets = await self.db.execute("SELECT * FROM target_channels WHERE is_active = 1")
            for target in targets:
                id, user_id, channel_id, channel_name, username, added_time, priority, is_active = target
                if user_id not in self.target_channels:
                    self.target_channels[user_id] = []
                self.target_channels[user_id].append({
                    'id': channel_id,
                    'name': channel_name,
                    'username': username,
                    'added_time': added_time,
                    'priority': priority,
                    'is_active': bool(is_active)
                })

            # Load settings
            settings_data = await self.db.execute("SELECT * FROM user_settings")
            for setting in settings_data:
                user_id, hide_header, forward_media, url_previews, remove_usernames, remove_links, caption_forward, delay_seconds, max_message_length, updated_at = setting
                self.forward_settings[user_id] = {
                    'hide_header': bool(hide_header),
                    'forward_media': bool(forward_media),
                    'url_previews': bool(url_previews),
                    'remove_usernames': bool(remove_usernames),
                    'remove_links': bool(remove_links),
                    'caption_forward': bool(caption_forward),
                    'delay_seconds': delay_seconds or 1,
                    'max_message_length': max_message_length or 4000
                }

            # Load auto forwarding status
            forwarding_data = await self.db.execute("SELECT * FROM auto_forwarding WHERE is_active = 1")
            for forwarding in forwarding_data:
                user_id, is_active, total_forwarded, last_forwarded, updated_at = forwarding
                self.auto_forwarding[user_id] = bool(is_active)
                self.forwarding_stats[user_id] = {
                    'total_forwarded': total_forwarded or 0,
                    'last_forwarded': last_forwarded
                }

            # Load word replacements
            word_reps = await self.db.execute("SELECT * FROM word_replacements")
            for rep in word_reps:
                id, user_id, original, replacement, case_sensitive, is_regex, created_at = rep
                if user_id not in self.word_replacements:
                    self.word_replacements[user_id] = []
                self.word_replacements[user_id].append({
                    'original': original,
                    'replacement': replacement,
                    'case_sensitive': bool(case_sensitive),
                    'is_regex': bool(is_regex)
                })

            # Load link replacements
            link_reps = await self.db.execute("SELECT * FROM link_replacements")
            for rep in link_reps:
                id, user_id, original, replacement, preserve_query, created_at = rep
                if user_id not in self.link_replacements:
                    self.link_replacements[user_id] = []
                self.link_replacements[user_id].append({
                    'original': original,
                    'replacement': replacement,
                    'preserve_query': bool(preserve_query)
                })

            logger.info(f"✅ Data loaded: {len(self.user_sessions)} users, {len(self.source_channels)} sources, {sum(len(t) for t in self.target_channels.values())} targets")

        except Exception as e:
            logger.error(f"❌ Error loading data: {e}")

    async def restore_user_client(self, user_id: int) -> bool:
        """Restore user client session if exists"""
        try:
            session_file = f"sessions/user_{user_id}.session"
            if os.path.exists(session_file):
                user_client = TelegramClient(session_file, self.api_id, self.api_hash)
                await user_client.connect()
                
                # Verify session is still valid
                try:
                    await user_client.get_me()
                    self.user_clients[user_id] = user_client
                    logger.info(f"✅ Restored session for user {user_id}")
                    return True
                except (AuthKeyError, ConnectionError):
                    await user_client.disconnect()
                    logger.warning(f"⚠️ Invalid session for user {user_id}, requiring re-login")
                    return False
            return False
        except Exception as e:
            logger.error(f"❌ Error restoring client for user {user_id}: {e}")
            return False

    async def start_all_message_listeners(self):
        """Start message listeners for all users with active forwarding"""
        for user_id in self.auto_forwarding:
            if self.auto_forwarding[user_id] and user_id in self.source_channels:
                await self.start_message_listener(user_id)

    async def start_message_listener(self, user_id: int):
        """Enhanced message listener with duplicate prevention"""
        try:
            if user_id not in self.user_clients or user_id not in self.source_channels:
                return
            
            # Remove existing handler if any
            await self.stop_message_listener(user_id)
            
            source_channel_id = self.source_channels[user_id]['id']
            user_client = self.user_clients[user_id]
            last_message_id = self.source_channels[user_id].get('last_message_id', 0)
            
            @user_client.on(events.NewMessage(chats=source_channel_id))
            async def message_handler(event):
                # Check if we've already processed this message
                if event.message.id <= last_message_id:
                    return
                
                # Update last message ID
                self.source_channels[user_id]['last_message_id'] = event.message.id
                await self.update_source_channel_last_id(user_id, event.message.id)
                
                await self.process_and_forward_message(user_id, event.message)
            
            self.message_handlers[user_id] = message_handler
            logger.info(f"✅ Started enhanced message listener for user {user_id} on channel {source_channel_id}")
            
        except Exception as e:
            logger.error(f"❌ Error starting message listener for user {user_id}: {e}")
            await self.log_error(user_id, "message_listener_start", str(e))

    async def stop_message_listener(self, user_id: int):
        """Stop message listener for a user"""
        try:
            if user_id in self.message_handlers and user_id in self.user_clients:
                self.user_clients[user_id].remove_event_handler(self.message_handlers[user_id])
                del self.message_handlers[user_id]
                logger.info(f"✅ Stopped message listener for user {user_id}")
        except Exception as e:
            logger.error(f"❌ Error stopping message listener for user {user_id}: {e}")

    # Enhanced database operations
    async def update_source_channel_last_id(self, user_id: int, last_message_id: int):
        """Update last processed message ID for source channel"""
        await self.db.execute(
            "UPDATE source_channels SET last_message_id = ? WHERE user_id = ?",
            (last_message_id, user_id)
        )

    async def increment_forward_count(self, user_id: int):
        """Increment forwarded message count"""
        await self.db.execute(
            "UPDATE auto_forwarding SET total_forwarded = total_forwarded + 1, last_forwarded = CURRENT_TIMESTAMP WHERE user_id = ?",
            (user_id,)
        )
        
        if user_id in self.forwarding_stats:
            self.forwarding_stats[user_id]['total_forwarded'] = self.forwarding_stats[user_id].get('total_forwarded', 0) + 1
            self.forwarding_stats[user_id]['last_forwarded'] = datetime.now().isoformat()

    async def log_error(self, user_id: int, error_type: str, error_message: str):
        """Log error to database"""
        await self.db.execute(
            "INSERT INTO error_logs (user_id, error_type, error_message) VALUES (?, ?, ?)",
            (user_id, error_type, error_message)
        )

    # Enhanced message processing
    async def process_and_forward_message(self, user_id: int, message):
        """Enhanced message processing with advanced features"""
        try:
            if (user_id not in self.source_channels or 
                user_id not in self.target_channels or 
                not self.target_channels[user_id]):
                return
            
            if not self.auto_forwarding.get(user_id, False):
                return
            
            settings = self.forward_settings.get(user_id, self.default_settings)
            
            # Check rate limiting
            if not await self.check_rate_limit(user_id, 'message_forward'):
                logger.warning(f"⚠️ Rate limit exceeded for user {user_id}")
                return
            
            # Process message text
            processed_text = await self.extract_and_process_text(message, user_id, settings)
            
            # Skip if no content and media forwarding is disabled
            if not processed_text.strip() and not settings.get('forward_media', True):
                return
            
            # Forward to target channels with enhanced error handling
            success_count = 0
            target_count = len(self.target_channels[user_id])
            
            for i, target in enumerate(self.target_channels[user_id]):
                if not target.get('is_active', True):
                    continue
                    
                try:
                    success = await self.forward_message_to_target(
                        user_id, message, target, processed_text, settings
                    )
                    if success:
                        success_count += 1
                    
                    # Respect delay between forwards
                    delay = settings.get('delay_seconds', 1)
                    if i < target_count - 1 and delay > 0:
                        await asyncio.sleep(delay)
                        
                except Exception as e:
                    logger.error(f"❌ Error forwarding to target {target['name']}: {e}")
                    await self.log_error(user_id, "target_forward", f"Target {target['name']}: {e}")
            
            if success_count > 0:
                await self.increment_forward_count(user_id)
                logger.info(f"✅ Forwarded message to {success_count}/{target_count} targets for user {user_id}")
                    
        except Exception as e:
            logger.error(f"❌ Error processing message: {e}")
            await self.log_error(user_id, "message_processing", str(e))

    async def extract_and_process_text(self, message, user_id: int, settings: Dict) -> str:
        """Extract and process message text with enhanced features"""
        text = ""
        
        # Extract text based on message type
        if hasattr(message, 'text') and message.text:
            text = message.text
        elif hasattr(message, 'message') and message.message:
            text = message.message
        elif hasattr(message, 'caption') and message.caption and settings.get('caption_forward', True):
            text = message.caption
        
        # Apply text processing
        processed_text = await self.process_message_text(user_id, text, settings)
        
        # Truncate if too long
        max_length = settings.get('max_message_length', 4000)
        if len(processed_text) > max_length:
            processed_text = processed_text[:max_length-3] + "..."
        
        return processed_text

    async def process_message_text(self, user_id: int, text: str, settings: Dict) -> str:
        """Enhanced text processing with regex support"""
        if not text:
            return ""
        
        processed_text = text
        
        # Apply word replacements with enhanced logic
        if user_id in self.word_replacements:
            for replacement in self.word_replacements[user_id]:
                original = replacement['original']
                new_text = replacement['replacement']
                case_sensitive = replacement.get('case_sensitive', False)
                is_regex = replacement.get('is_regex', False)
                
                if is_regex:
                    try:
                        flags = 0 if case_sensitive else re.IGNORECASE
                        processed_text = re.sub(original, new_text, processed_text, flags=flags)
                    except re.error:
                        logger.warning(f"⚠️ Invalid regex pattern: {original}")
                else:
                    if case_sensitive:
                        processed_text = processed_text.replace(original, new_text)
                    else:
                        # Case-insensitive replacement
                        pattern = re.compile(re.escape(original), re.IGNORECASE)
                        processed_text = pattern.sub(new_text, processed_text)
        
        # Apply link replacements
        if user_id in self.link_replacements:
            for replacement in self.link_replacements[user_id]:
                original = replacement['original']
                new_link = replacement['replacement']
                preserve_query = replacement.get('preserve_query', True)
                
                if preserve_query:
                    # Preserve query parameters from original URL
                    original_parsed = urlparse(original)
                    new_parsed = urlparse(new_link)
                    
                    if original_parsed.query and not new_parsed.query:
                        new_link = f"{new_link}?{original_parsed.query}"
                
                processed_text = processed_text.replace(original, new_link)
        
        # Remove usernames if enabled
        if settings.get('remove_usernames', False):
            processed_text = re.sub(r'@\w+', '', processed_text)
        
        # Remove links if enabled
        if settings.get('remove_links', False):
            processed_text = re.sub(r'https?://[^\s]+', '', processed_text)
        
        return processed_text.strip()

    async def forward_message_to_target(self, user_id: int, message, target: Dict, processed_text: str, settings: Dict) -> bool:
        """Enhanced message forwarding with media support"""
        try:
            target_entity = await self.client.get_entity(target['id'])
            
            # Check if we should forward media
            if (settings.get('forward_media', True) and 
                hasattr(message, 'media') and message.media is not None):
                
                # Forward media with caption
                caption = processed_text if processed_text.strip() else None
                await self.client.send_message(
                    entity=target_entity,
                    file=message.media,
                    message=caption,
                    link_preview=settings.get('url_previews', True)
                )
            else:
                # Forward as text only
                if processed_text.strip():
                    await self.client.send_message(
                        entity=target_entity,
                        message=processed_text,
                        link_preview=settings.get('url_previews', True)
                    )
                else:
                    return False  # No content to forward
            
            return True
            
        except errors.FloodWaitError as e:
            logger.warning(f"⚠️ Flood wait for {e.seconds} seconds for user {user_id}")
            await asyncio.sleep(e.seconds)
            return False
        except errors.ChannelPrivateError:
            logger.warning(f"⚠️ Channel private for user {user_id}, deactivating target")
            await self.deactivate_target_channel(user_id, target['id'])
            return False
        except Exception as e:
            logger.error(f"❌ Error sending to target {target['name']}: {e}")
            return False

    async def deactivate_target_channel(self, user_id: int, channel_id: int):
        """Deactivate a target channel that's no longer accessible"""
        await self.db.execute(
            "UPDATE target_channels SET is_active = 0 WHERE user_id = ? AND channel_id = ?",
            (user_id, channel_id)
        )
        
        # Update in-memory data
        if user_id in self.target_channels:
            self.target_channels[user_id] = [
                target for target in self.target_channels[user_id] 
                if target['id'] != channel_id
            ]

    async def check_rate_limit(self, user_id: int, operation: str) -> bool:
        """Enhanced rate limiting with sliding window"""
        now = datetime.now().timestamp()
        
        if user_id not in self.rate_limits:
            self.rate_limits[user_id] = {}
        
        if operation not in self.rate_limits[user_id]:
            self.rate_limits[user_id][operation] = []
        
        # Clean old entries
        window = self.rate_limit_config[operation]['window']
        max_count = self.rate_limit_config[operation]['max_count']
        
        self.rate_limits[user_id][operation] = [
            timestamp for timestamp in self.rate_limits[user_id][operation]
            if now - timestamp < window
        ]
        
        # Check if limit exceeded
        if len(self.rate_limits[user_id][operation]) >= max_count:
            return False
        
        # Add current operation
        self.rate_limits[user_id][operation].append(now)
        return True

    # Enhanced login system with better error handling
    async def handle_login_command(self, event):
        """Enhanced login command handler"""
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
🔐 **Enhanced Login Process**

Please send your phone number in international format:

**Example:** `+1234567890`

You can send it now or use: `/login +1234567890`

**Security Note:** Your session is stored locally and encrypted.
            """
            self.user_states[user.id] = {'state': 'awaiting_phone'}
            await event.reply(login_text)

    async def start_telegram_login(self, user, phone_number, event):
        """Enhanced Telegram login with better error handling"""
        try:
            session_name = f"sessions/user_{user.id}"
            os.makedirs("sessions", exist_ok=True)
            
            user_client = TelegramClient(session_name, self.api_id, self.api_hash)
            await user_client.connect()
            
            # Add timeout for code request
            try:
                sent_code = await asyncio.wait_for(
                    user_client.send_code_request(phone_number),
                    timeout=30
                )
            except asyncio.TimeoutError:
                await event.reply("❌ Request timeout. Please try again.")
                await user_client.disconnect()
                return
            
            self.user_states[user.id] = {
                'state': 'awaiting_code',
                'phone_number': phone_number,
                'phone_code_hash': sent_code.phone_code_hash,
                'user_client': user_client,
                'attempt_time': datetime.now().isoformat(),
                'attempts': 0
            }
            
            login_text = f"""
📱 **Verification Code Sent!**

**Phone:** `{phone_number}`

Please check your Telegram app for the verification code.

**Send the code in format:** `/code 123456`

Replace 123456 with your actual code.

**Security:** Code expires in 5 minutes.
            """
            
            buttons = [
                [Button.inline("🔄 Resend Code", b"resend_code")],
                [Button.inline("❌ Cancel Login", b"cancel_login")]
            ]
            
            await event.reply(login_text, buttons=buttons)
            
        except errors.PhoneNumberInvalidError:
            await event.reply("❌ Invalid phone number. Please check the format and try again.")
        except errors.PhoneNumberFloodError:
            await event.reply("❌ Too many attempts. Please try again later.")
        except Exception as e:
            logger.error(f"❌ Login error: {e}")
            await event.reply("❌ Error starting login process. Please try again.")

    # Enhanced verification code handling
    async def handle_code_verification(self, event):
        """Handle code verification with attempt limiting"""
        user = await event.get_sender()
        
        if (user.id not in self.user_states or 
            self.user_states[user.id].get('state') != 'awaiting_code'):
            return
        
        code_text = event.text.replace('/code', '').strip()
        
        if not code_text.isdigit() or len(code_text) < 5:
            await event.reply("❌ Invalid code format. Please enter numbers only, like: `/code 123456`")
            return
        
        login_data = self.user_states[user.id]
        
        # Check attempt limit
        if login_data.get('attempts', 0) >= 3:
            await event.reply("❌ Too many failed attempts. Please restart login process.")
            if 'user_client' in login_data:
                await login_data['user_client'].disconnect()
            del self.user_states[user.id]
            return
        
        try:
            await login_data['user_client'].sign_in(
                phone=login_data['phone_number'],
                code=code_text,
                phone_code_hash=login_data['phone_code_hash']
            )
            
            # Login successful
            user_entity = await login_data['user_client'].get_me()
            
            # Store user client
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
            
            # Initialize settings if not exists
            if user.id not in self.forward_settings:
                self.forward_settings[user.id] = self.default_settings.copy()
                await self.save_user_settings(user.id, self.forward_settings[user.id])
            
            del self.user_states[user.id]
            
            success_text = f"""
✅ **Login Successful!**

Welcome, {user_entity.first_name or 'User'}!

**Account:** @{user_entity.username or 'N/A'}
**Phone:** `{login_data['phone_number']}`

Now you can set up auto-forwarding with enhanced features!
            """
            
            buttons = [
                [Button.inline("🚀 Quick Setup", b"quick_setup")],
                [Button.inline("📊 Dashboard", b"show_dashboard")],
                [Button.inline("🆘 Help", b"show_help")]
            ]
            
            await event.reply(success_text, buttons=buttons)
            
        except SessionPasswordNeededError:
            await event.reply("""
🔒 **Two-Factor Authentication Detected**

This account has 2FA enabled. For security reasons, please:
1. Temporarily disable 2FA in your Telegram account settings
2. Login again
3. Re-enable 2FA after setup

**Alternative:** Use a different account without 2FA.
            """)
        except errors.PhoneCodeInvalidError:
            login_data['attempts'] = login_data.get('attempts', 0) + 1
            remaining = 3 - login_data['attempts']
            await event.reply(f"❌ Invalid code. {remaining} attempts remaining.")
        except Exception as e:
            logger.error(f"❌ Verification error: {e}")
            await event.reply("❌ Error during verification. Please try again.")

    # Enhanced database operations
    async def save_user_session(self, user_id: int, user_data: Dict) -> bool:
        """Save user session with enhanced error handling"""
        try:
            await self.db.execute('''
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
            return True
        except Exception as e:
            logger.error(f"❌ Error saving user session: {e}")
            return False

    async def save_user_settings(self, user_id: int, settings: Dict) -> bool:
        """Save user settings with enhanced fields"""
        try:
            await self.db.execute('''
                INSERT OR REPLACE INTO user_settings 
                (user_id, hide_header, forward_media, url_previews, remove_usernames, 
                 remove_links, caption_forward, delay_seconds, max_message_length)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_id,
                int(settings.get('hide_header', False)),
                int(settings.get('forward_media', True)),
                int(settings.get('url_previews', True)),
                int(settings.get('remove_usernames', False)),
                int(settings.get('remove_links', False)),
                int(settings.get('caption_forward', True)),
                settings.get('delay_seconds', 1),
                settings.get('max_message_length', 4000)
            ))
            return True
        except Exception as e:
            logger.error(f"❌ Error saving user settings: {e}")
            return False

    # Enhanced force subscribe check
    async def check_force_subscribe(self, user_id: int) -> bool:
        """Enhanced force subscribe check with caching"""
        if not FORCE_SUB_CHANNEL or FORCE_SUB_CHANNEL == "@YourChannel":
            return True
        
        try:
            # Cache the check for 5 minutes
            cache_key = f"sub_check_{user_id}"
            if hasattr(self, '_sub_cache') and cache_key in self._sub_cache:
                return self._sub_cache[cache_key]
            
            channel_entity = await self.client.get_entity(FORCE_SUB_CHANNEL)
            participant = await self.client.get_permissions(channel_entity, user_id)
            is_subscribed = participant is not None
            
            # Cache the result
            if not hasattr(self, '_sub_cache'):
                self._sub_cache = {}
            self._sub_cache[cache_key] = is_subscribed
            
            return is_subscribed
            
        except Exception as e:
            logger.error(f"❌ Force subscribe check error: {e}")
            return True  # Allow access if check fails

    async def show_force_subscribe(self, event):
        """Enhanced force subscribe message"""
        if FORCE_SUB_CHANNEL and FORCE_SUB_CHANNEL != "@YourChannel":
            message = f"""
🔒 **Subscription Required**

To use this bot, you need to join our channel first:

**Channel:** {FORCE_SUB_CHANNEL}

After joining, click the button below to verify.
            """
            buttons = [
                [Button.url("📢 Join Channel", f"https://t.me/{FORCE_SUB_CHANNEL[1:]}")],
                [Button.inline("✅ I've Joined", b"check_subscription")]
            ]
            await event.reply(message, buttons=buttons)

    # Enhanced channel selection system
    async def show_channel_selection(self, event, selection_type: str):
        """Enhanced channel selection with pagination"""
        user = await event.get_sender()
        
        if user.id not in self.user_clients:
            await event.reply("❌ Please login first to manage channels.")
            return
        
        try:
            user_client = self.user_clients[user.id]
            dialogs = await user_client.get_dialogs()
            
            channels = []
            for dialog in dialogs:
                if dialog.is_channel and dialog.entity:
                    channels.append({
                        'id': dialog.entity.id,
                        'name': getattr(dialog.entity, 'title', 'Unknown'),
                        'username': getattr(dialog.entity, 'username', None),
                        'participants_count': getattr(dialog.entity, 'participants_count', 0)
                    })
            
            if not channels:
                await event.reply("❌ No channels found in your account.")
                return
            
            # Store channel list for selection
            self.channel_selection[user.id] = {
                'channels': channels,
                'type': selection_type,
                'page': 0
            }
            
            await self.show_channel_selection_page(event, user.id)
            
        except Exception as e:
            logger.error(f"❌ Channel selection error: {e}")
            await event.reply("❌ Error fetching channels. Please try again.")

    async def show_channel_selection_page(self, event, user_id: int, page: int = 0):
        """Show paginated channel selection"""
        if user_id not in self.channel_selection:
            return
        
        selection_data = self.channel_selection[user_id]
        channels = selection_data['channels']
        channels_per_page = 5
        total_pages = (len(channels) + channels_per_page - 1) // channels_per_page
        
        start_idx = page * channels_per_page
        end_idx = min(start_idx + channels_per_page, len(channels))
        page_channels = channels[start_idx:end_idx]
        
        selection_type = selection_data['type']
        title = "📡 Source Channel" if selection_type == 'source' else "🎯 Target Channel"
        
        message = f"""
{title} Selection

**Page {page + 1}/{total_pages}**
Select a channel by clicking its number:
        """
        
        buttons = []
        for i, channel in enumerate(page_channels, 1):
            channel_num = start_idx + i
            channel_info = f"{channel['name']}"
            if channel['username']:
                channel_info += f" (@{channel['username']})"
            buttons.append([Button.inline(f"{channel_num}. {channel_info}", f"select_channel:{channel['id']}")])
        
        # Navigation buttons
        nav_buttons = []
        if page > 0:
            nav_buttons.append(Button.inline("⬅️ Previous", f"channel_page:{page-1}"))
        if page < total_pages - 1:
            nav_buttons.append(Button.inline("Next ➡️", f"channel_page:{page+1}"))
        
        if nav_buttons:
            buttons.append(nav_buttons)
        
        buttons.append([Button.inline("🔙 Back", b"show_dashboard")])
        
        await event.edit(message, buttons=buttons)

    async def handle_channel_selection(self, event, channel_id: int):
        """Handle channel selection for source or target"""
        user = await event.get_sender()
        
        if user.id not in self.channel_selection:
            await event.answer("❌ Selection expired. Please try again.", alert=True)
            return
        
        selection_type = self.channel_selection[user.id]['type']
        
        try:
            user_client = self.user_clients[user.id]
            channel_entity = await user_client.get_entity(channel_id)
            
            channel_data = {
                'id': channel_id,
                'name': getattr(channel_entity, 'title', 'Unknown'),
                'username': getattr(channel_entity, 'username', None)
            }
            
            if selection_type == 'source':
                await self.set_source_channel(user.id, channel_data)
                message = f"""
✅ **Source Channel Set!**

**Channel:** {channel_data['name']}
**Username:** @{channel_data['username'] or 'N/A'}

Messages from this channel will now be forwarded to your target channels.
                """
                
            else:  # target
                await self.add_target_channel(user.id, channel_data)
                message = f"""
✅ **Target Channel Added!**

**Channel:** {channel_data['name']}
**Username:** @{channel_data['username'] or 'N/A'}

This channel will receive forwarded messages.
                """
            
            del self.channel_selection[user.id]
            
            buttons = [
                [Button.inline("📊 Dashboard", b"show_dashboard")],
                [Button.inline("⚙️ Settings", b"show_settings")]
            ]
            
            await event.edit(message, buttons=buttons)
            
        except Exception as e:
            logger.error(f"❌ Channel selection error: {e}")
            await event.answer("❌ Error selecting channel. Please try again.", alert=True)

    async def set_source_channel(self, user_id: int, channel_data: Dict):
        """Set source channel with enhanced validation"""
        try:
            await self.db.execute('''
                INSERT OR REPLACE INTO source_channels 
                (user_id, channel_id, channel_name, username, set_time)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                user_id,
                channel_data['id'],
                channel_data['name'],
                channel_data.get('username'),
                datetime.now().isoformat()
            ))
            
            self.source_channels[user_id] = channel_data
            self.source_channels[user_id]['last_message_id'] = 0
            
            # Start message listener if auto forwarding is active
            if self.auto_forwarding.get(user_id, False):
                await self.start_message_listener(user_id)
                
        except Exception as e:
            logger.error(f"❌ Error setting source channel: {e}")
            raise

    async def add_target_channel(self, user_id: int, channel_data: Dict):
        """Add target channel with priority management"""
        try:
            # Get current target count for priority
            current_targets = await self.db.execute(
                "SELECT COUNT(*) FROM target_channels WHERE user_id = ? AND is_active = 1",
                (user_id,)
            )
            priority = current_targets[0][0] + 1 if current_targets else 1
            
            await self.db.execute('''
                INSERT OR REPLACE INTO target_channels 
                (user_id, channel_id, channel_name, username, added_time, priority)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                user_id,
                channel_data['id'],
                channel_data['name'],
                channel_data.get('username'),
                datetime.now().isoformat(),
                priority
            ))
            
            if user_id not in self.target_channels:
                self.target_channels[user_id] = []
            
            # Remove if exists and add new
            self.target_channels[user_id] = [
                target for target in self.target_channels[user_id] 
                if target['id'] != channel_data['id']
            ]
            
            channel_data['priority'] = priority
            channel_data['is_active'] = True
            self.target_channels[user_id].append(channel_data)
            
        except Exception as e:
            logger.error(f"❌ Error adding target channel: {e}")
            raise

    # Enhanced dashboard with statistics
    async def show_enhanced_dashboard(self, event):
        """Enhanced dashboard with comprehensive statistics"""
        user = await event.get_sender()
        
        if user.id not in self.user_sessions:
            await event.reply("❌ Please login first using `/login`")
            return
        
        user_data = self.user_sessions[user.id]
        source_channel = self.source_channels.get(user.id, {})
        target_channels = self.target_channels.get(user.id, [])
        settings = self.forward_settings.get(user.id, self.default_settings)
        stats = self.forwarding_stats.get(user.id, {})
        is_active = self.auto_forwarding.get(user.id, False)
        
        dashboard_text = f"""
🤖 **Enhanced Auto-Forward Dashboard**

👤 **Account Info**
• **User:** {user_data.get('first_name', 'N/A')}
• **Phone:** `{user_data.get('phone_number', 'N/A')}`
• **Status:** {'🟢 Active' if is_active else '🔴 Paused'}

📡 **Source Channel**
• **Name:** {source_channel.get('name', 'Not Set')}
• **Username:** @{source_channel.get('username', 'N/A')}

🎯 **Target Channels:** {len(target_channels)}
• **Active:** {len([t for t in target_channels if t.get('is_active', True)])}

📊 **Statistics**
• **Total Forwarded:** {stats.get('total_forwarded', 0)}
• **Last Forwarded:** {stats.get('last_forwarded', 'Never')}

⚙️ **Settings**
• **Delay:** {settings.get('delay_seconds', 1)}s
• **Media Forwarding:** {'✅' if settings.get('forward_media', True) else '❌'}
• **URL Previews:** {'✅' if settings.get('url_previews', True) else '❌'}

**Use buttons below to manage:**
        """
        
        buttons = [
            [
                Button.inline("📡 Set Source", b"set_source"),
                Button.inline("🎯 Manage Targets", b"manage_targets")
            ],
            [
                Button.inline("⚙️ Settings", b"show_settings"),
                Button.inline("🔄 " + ("Pause" if is_active else "Resume"), b"toggle_forwarding")
            ],
            [
                Button.inline("📊 Statistics", b"show_stats"),
                Button.inline("🆘 Help", b"show_help")
            ],
            [
                Button.inline("🗑️ Clear Data", b"clear_data"),
                Button.inline("🚪 Logout", b"logout_user")
            ]
        ]
        
        await event.edit(dashboard_text, buttons=buttons)

    # Enhanced settings management
    async def show_enhanced_settings(self, event):
        """Enhanced settings interface with toggles"""
        user = await event.get_sender()
        
        if user.id not in self.user_sessions:
            await event.reply("❌ Please login first.")
            return
        
        settings = self.forward_settings.get(user.id, self.default_settings)
        
        settings_text = """
⚙️ **Enhanced Settings Configuration**

Toggle settings using the buttons below:

**Current Settings:**
• Media Forwarding: {media}
• URL Previews: {previews}
• Caption Forwarding: {caption}
• Remove Usernames: {remove_user}
• Remove Links: {remove_links}
• Hide Header: {hide_header}

**Advanced:**
• Delay: {delay}s
• Max Message Length: {max_len} chars

**Word/Link Replacement:** Use buttons to manage
        """.format(
            media='✅' if settings.get('forward_media', True) else '❌',
            previews='✅' if settings.get('url_previews', True) else '❌',
            caption='✅' if settings.get('caption_forward', True) else '❌',
            remove_user='✅' if settings.get('remove_usernames', False) else '❌',
            remove_links='✅' if settings.get('remove_links', False) else '❌',
            hide_header='✅' if settings.get('hide_header', False) else '❌',
            delay=settings.get('delay_seconds', 1),
            max_len=settings.get('max_message_length', 4000)
        )
        
        buttons = [
            [
                Button.inline("🖼️ Media: " + ("✅" if settings.get('forward_media', True) else "❌"), b"toggle_media"),
                Button.inline("🔗 Previews: " + ("✅" if settings.get('url_previews', True) else "❌"), b"toggle_previews")
            ],
            [
                Button.inline("📝 Caption: " + ("✅" if settings.get('caption_forward', True) else "❌"), b"toggle_caption"),
                Button.inline("👤 Remove @: " + ("✅" if settings.get('remove_usernames', False) else "❌"), b"toggle_remove_user")
            ],
            [
                Button.inline("🌐 Remove Links: " + ("✅" if settings.get('remove_links', False) else "❌"), b"toggle_remove_links"),
                Button.inline("📋 Header: " + ("✅" if settings.get('hide_header', False) else "❌"), b"toggle_header")
            ],
            [
                Button.inline("⏱️ Set Delay", b"set_delay"),
                Button.inline("📏 Set Length", b"set_length")
            ],
            [
                Button.inline("🔤 Word Replace", b"manage_words"),
                Button.inline("🔗 Link Replace", b"manage_links")
            ],
            [
                Button.inline("💾 Save Settings", b"save_settings"),
                Button.inline("🔙 Back", b"show_dashboard")
            ]
        ]
        
        await event.edit(settings_text, buttons=buttons)

    # Enhanced callback query handler
    def register_enhanced_handlers(self):
        """Register all enhanced event handlers"""
        
        @self.client.on(events.NewMessage(pattern='/start'))
        async def start_handler(event):
            await self.handle_start_command(event)
        
        @self.client.on(events.NewMessage(pattern='/login'))
        async def login_handler(event):
            await self.handle_login_command(event)
        
        @self.client.on(events.NewMessage(pattern='/code'))
        async def code_handler(event):
            await self.handle_code_verification(event)
        
        @self.client.on(events.NewMessage(pattern='/dashboard'))
        async def dashboard_handler(event):
            await self.show_enhanced_dashboard(event)
        
        @self.client.on(events.NewMessage(pattern='/settings'))
        async def settings_handler(event):
            await self.show_enhanced_settings(event)
        
        @self.client.on(events.NewMessage(pattern='/help'))
        async def help_handler(event):
            await self.show_enhanced_help(event)
        
        @self.client.on(events.NewMessage(pattern='/logout'))
        async def logout_handler(event):
            await self.handle_logout(event)
        
        @self.client.on(events.CallbackQuery)
        async def callback_handler(event):
            await self.handle_enhanced_callbacks(event)

    async def handle_enhanced_callbacks(self, event):
        """Enhanced callback query handler with error handling"""
        try:
            user = await event.get_sender()
            data = event.data.decode('utf-8') if event.data else None
            
            if not data:
                return
            
            logger.info(f"Callback from {user.id}: {data}")
            
            # Handle channel selection callbacks
            if data.startswith('select_channel:'):
                channel_id = int(data.split(':')[1])
                await self.handle_channel_selection(event, channel_id)
            
            elif data.startswith('channel_page:'):
                page = int(data.split(':')[1])
                await self.show_channel_selection_page(event, user.id, page)
            
            # Handle main menu callbacks
            elif data == 'show_dashboard':
                await self.show_enhanced_dashboard(event)
            
            elif data == 'set_source':
                await self.show_channel_selection(event, 'source')
            
            elif data == 'manage_targets':
                await self.show_channel_selection(event, 'target')
            
            elif data == 'show_settings':
                await self.show_enhanced_settings(event)
            
            elif data == 'toggle_forwarding':
                await self.toggle_auto_forwarding(event)
            
            # Handle settings toggles
            elif data == 'toggle_media':
                await self.toggle_setting(event, 'forward_media')
            
            elif data == 'toggle_previews':
                await self.toggle_setting(event, 'url_previews')
            
            elif data == 'toggle_caption':
                await self.toggle_setting(event, 'caption_forward')
            
            elif data == 'toggle_remove_user':
                await self.toggle_setting(event, 'remove_usernames')
            
            elif data == 'toggle_remove_links':
                await self.toggle_setting(event, 'remove_links')
            
            elif data == 'toggle_header':
                await self.toggle_setting(event, 'hide_header')
            
            elif data == 'save_settings':
                await self.save_current_settings(event)
            
            elif data == 'show_help':
                await self.show_enhanced_help(event)
            
            elif data == 'show_stats':
                await self.show_detailed_stats(event)
            
            elif data == 'clear_data':
                await self.show_clear_confirmation(event)
            
            elif data == 'logout_user':
                await self.show_logout_confirmation(event)
            
            elif data == 'confirm_logout':
                await self.handle_logout(event)
            
            elif data == 'cancel_logout':
                await self.show_enhanced_dashboard(event)
            
            elif data == 'quick_setup':
                await self.show_quick_setup(event)
            
            elif data == 'check_subscription':
                await self.handle_subscription_check(event)
            
            elif data == 'resend_code':
                await self.handle_resend_code(event)
            
            elif data == 'cancel_login':
                await self.handle_cancel_login(event)
            
            else:
                await event.answer("❌ Unknown command", alert=True)
                
        except Exception as e:
            logger.error(f"❌ Callback error: {e}")
            await event.answer("❌ Error processing request", alert=True)

    async def toggle_setting(self, event, setting_name: str):
        """Toggle a setting and refresh the interface"""
        user = await event.get_sender()
        
        if user.id in self.forward_settings:
            current = self.forward_settings[user.id].get(setting_name, self.default_settings[setting_name])
            self.forward_settings[user.id][setting_name] = not current
        
        await self.show_enhanced_settings(event)

    async def save_current_settings(self, event):
        """Save current settings to database"""
        user = await event.get_sender()
        
        if user.id in self.forward_settings:
            await self.save_user_settings(user.id, self.forward_settings[user.id])
            await event.answer("✅ Settings saved successfully!", alert=True)
        else:
            await event.answer("❌ No settings to save", alert=True)
        
        await self.show_enhanced_settings(event)

    async def toggle_auto_forwarding(self, event):
        """Toggle auto forwarding state"""
        user = await event.get_sender()
        
        if user.id not in self.user_sessions:
            await event.answer("❌ Please login first", alert=True)
            return
        
        current_state = self.auto_forwarding.get(user.id, False)
        new_state = not current_state
        
        try:
            await self.db.execute(
                "INSERT OR REPLACE INTO auto_forwarding (user_id, is_active) VALUES (?, ?)",
                (user.id, int(new_state))
            )
            
            self.auto_forwarding[user.id] = new_state
            
            if new_state and user.id in self.source_channels:
                await self.start_message_listener(user.id)
            else:
                await self.stop_message_listener(user.id)
            
            status = "🟢 STARTED" if new_state else "🔴 PAUSED"
            await event.answer(f"✅ Auto-forwarding {status.lower()}!", alert=True)
            
        except Exception as e:
            logger.error(f"❌ Error toggling forwarding: {e}")
            await event.answer("❌ Error changing state", alert=True)
        
        await self.show_enhanced_dashboard(event)

    async def show_detailed_stats(self, event):
        """Show detailed statistics"""
        user = await event.get_sender()
        
        if user.id not in self.forwarding_stats:
            stats = {'total_forwarded': 0, 'last_forwarded': 'Never'}
        else:
            stats = self.forwarding_stats[user.id]
        
        stats_text = f"""
📊 **Detailed Statistics**

**Forwarding Stats:**
• Total Messages Forwarded: {stats.get('total_forwarded', 0)}
• Last Forwarded: {stats.get('last_forwarded', 'Never')}
• Current Status: {'🟢 Active' if self.auto_forwarding.get(user.id, False) else '🔴 Paused'}

**Channel Info:**
• Source Channel: {self.source_channels.get(user.id, {}).get('name', 'Not set')}
• Target Channels: {len(self.target_channels.get(user.id, []))}

**Account:**
• Login Time: {self.user_sessions.get(user.id, {}).get('login_time', 'N/A')}
        """
        
        buttons = [[Button.inline("🔙 Back", b"show_dashboard")]]
        await event.edit(stats_text, buttons=buttons)

    async def show_clear_confirmation(self, event):
        """Show clear data confirmation"""
        confirm_text = """
🗑️ **Clear All Data**

⚠️ **This action cannot be undone!**

This will remove:
• Your source channel
• All target channels  
• Your forwarding settings
• Your statistics

**Your login session will be preserved.**

Are you sure you want to continue?
        """
        
        buttons = [
            [Button.inline("✅ Yes, Clear Everything", b"confirm_clear")],
            [Button.inline("❌ No, Keep My Data", b"show_dashboard")]
        ]
        
        await event.edit(confirm_text, buttons=buttons)

    async def show_logout_confirmation(self, event):
        """Show logout confirmation"""
        confirm_text = """
🚪 **Logout Confirmation**

⚠️ **You will need to login again!**

This will:
• Remove your login session
• Stop all auto-forwarding
• Clear all your data

Are you sure you want to logout?
        """
        
        buttons = [
            [Button.inline("✅ Yes, Logout", b"confirm_logout")],
            [Button.inline("❌ Cancel", b"show_dashboard")]
        ]
        
        await event.edit(confirm_text, buttons=buttons)

    async def handle_logout(self, event):
        """Enhanced logout handler"""
        user = await event.get_sender()
        
        try:
            # Stop message listener
            await self.stop_message_listener(user.id)
            
            # Disconnect user client if exists
            if user.id in self.user_clients:
                await self.user_clients[user.id].disconnect()
                del self.user_clients[user.id]
            
            # Clear all user data
            for key in [self.user_sessions, self.source_channels, self.target_channels, 
                       self.forward_settings, self.auto_forwarding, self.forwarding_stats,
                       self.word_replacements, self.link_replacements]:
                if user.id in key:
                    del key[user.id]
            
            # Update database
            await self.db.execute("UPDATE users SET status = 'logged_out' WHERE user_id = ?", (user.id,))
            await self.db.execute("DELETE FROM auto_forwarding WHERE user_id = ?", (user.id,))
            
            logout_text = """
✅ **Logout Successful**

All your data has been cleared and the session has been terminated.

You can login again anytime using `/login`
            """
            
            buttons = [[Button.inline("🔐 Login Again", b"start_login")]]
            await event.edit(logout_text, buttons=buttons)
            
        except Exception as e:
            logger.error(f"❌ Logout error: {e}")
            await event.answer("❌ Error during logout", alert=True)

    async def show_enhanced_help(self, event):
        """Enhanced help message"""
        help_text = """
🆘 **Enhanced Auto-Forward Bot Help**

**📋 Basic Commands:**
• `/start` - Start the bot
• `/login` - Login with your account  
• `/dashboard` - Show control panel
• `/settings` - Configure options
• `/help` - This help message

**🔧 Key Features:**
• **Smart Forwarding**: Auto-forward messages from source to targets
• **Media Support**: Forward photos, videos, documents
• **Text Processing**: Remove usernames/links, word replacement
• **Rate Limiting**: Prevent spam and API limits
• **Multiple Targets**: Forward to multiple channels
• **Advanced Settings**: Fine-tune forwarding behavior

**⚙️ Setup Process:**
1. Login with `/login`
2. Set source channel (where messages come from)
3. Add target channels (where messages go to)
4. Configure settings
5. Start auto-forwarding

**🔒 Privacy & Security:**
• Your data is stored locally and encrypted
• No messages are stored permanently
• You can logout anytime to clear all data

**Need more help?** Contact the bot administrator.
        """
        
        buttons = [
            [Button.inline("🚀 Quick Setup Guide", b"quick_setup")],
            [Button.inline("📊 Dashboard", b"show_dashboard")],
            [Button.inline("🔙 Main Menu", b"start")]
        ]
        
        await event.edit(help_text, buttons=buttons)

    async def show_quick_setup(self, event):
        """Quick setup guide"""
        setup_text = """
🚀 **Quick Setup Guide**

**Step 1: Login**
• Use `/login +1234567890` with your phone number
• Enter the verification code sent to your Telegram

**Step 2: Set Source Channel**
• Click "Set Source" in dashboard
• Select the channel you want to forward FROM
• Make sure the bot has access to read messages

**Step 3: Add Target Channels**  
• Click "Manage Targets" in dashboard
• Select channels you want to forward TO
• The bot needs admin rights in target channels

**Step 4: Configure Settings**
• Adjust delay between forwards
• Enable/disable media forwarding
• Set up word replacements if needed

**Step 5: Start Forwarding**
• Toggle the forwarding switch to START
• The bot will now auto-forward new messages

**💡 Pro Tips:**
• Start with 2-3 second delays to avoid limits
• Test with a small channel first
• Monitor the statistics to ensure it's working
        """
        
        buttons = [
            [Button.inline("📡 Set Source Now", b"set_source")],
            [Button.inline("🎯 Add Targets Now", b"manage_targets")],
            [Button.inline("🔙 Back to Help", b"show_help")]
        ]
        
        await event.edit(setup_text, buttons=buttons)

    async def handle_start_command(self, event):
        """Enhanced start command handler"""
        user = await event.get_sender()
        
        welcome_text = f"""
🤖 **Advanced Auto-Forward Bot**

Welcome, {user.first_name or 'User'}!

This bot helps you automatically forward messages from one channel to multiple other channels with advanced features.

**✨ Key Features:**
• Smart message forwarding with media support
• Advanced text processing and filtering
• Multiple target channels with priority
• Rate limiting and flood protection
• Word and link replacement system
• Comprehensive statistics and monitoring

**🚀 Getting Started:**
1. Login with your Telegram account
2. Set up source and target channels  
3. Configure your preferences
4. Start auto-forwarding!

**📊 Current Status:**
• Users Online: {len(self.user_sessions)}
• Active Forwarding Sessions: {sum(self.auto_forwarding.values())}

Use the buttons below to begin or type `/help` for more information.
        """
        
        buttons = [
            [Button.inline("🔐 Login / Start", b"start_login")],
            [Button.inline("🆘 Help Guide", b"show_help")],
            [Button.inline("📊 Statistics", b"show_stats")]
        ]
        
        # Check if user needs to join channel
        if not await self.check_force_subscribe(user.id):
            await self.show_force_subscribe(event)
            return
        
        await event.reply(welcome_text, buttons=buttons)

    async def handle_resend_code(self, event):
        """Handle resend verification code"""
        user = await event.get_sender()
        
        if (user.id not in self.user_states or 
            self.user_states[user.id].get('state') != 'awaiting_code'):
            await event.answer("❌ No pending verification", alert=True)
            return
        
        login_data = self.user_states[user.id]
        
        try:
            await login_data['user_client'].send_code_request(
                login_data['phone_number']
            )
            await event.answer("✅ Verification code resent!", alert=True)
        except Exception as e:
            logger.error(f"❌ Resend error: {e}")
            await event.answer("❌ Error resending code", alert=True)

    async def handle_cancel_login(self, event):
        """Handle login cancellation"""
        user = await event.get_sender()
        
        if user.id in self.user_states:
            login_data = self.user_states[user.id]
            if 'user_client' in login_data:
                await login_data['user_client'].disconnect()
            del self.user_states[user.id]
        
        await event.answer("✅ Login cancelled", alert=True)
        await self.handle_start_command(event)

    async def handle_subscription_check(self, event):
        """Handle subscription verification"""
        user = await event.get_sender()
        
        if await self.check_force_subscribe(user.id):
            await event.answer("✅ Subscription verified! You can now use the bot.", alert=True)
            await self.handle_start_command(event)
        else:
            await event.answer("❌ Please join the channel first.", alert=True)

    async def run(self):
        """Enhanced run method with graceful shutdown"""
        try:
            logger.info("🤖 Bot is now running. Press Ctrl+C to stop.")
            await self.client.run_until_disconnected()
        except KeyboardInterrupt:
            logger.info("🛑 Shutting down bot gracefully...")
            await self.shutdown()
        except Exception as e:
            logger.error(f"❌ Bot runtime error: {e}")
            await self.shutdown()

    async def shutdown(self):
        """Enhanced shutdown with cleanup"""
        try:
            # Disconnect all user clients
            for user_id, client in self.user_clients.items():
                try:
                    await client.disconnect()
                except Exception as e:
                    logger.error(f"❌ Error disconnecting user {user_id}: {e}")
            
            # Disconnect main client
            if self.client.is_connected():
                await self.client.disconnect()
            
            logger.info("✅ Bot shutdown completed successfully")
        except Exception as e:
            logger.error(f"❌ Shutdown error: {e}")

# Bot configuration
API_ID = 28093492  # Replace with your API ID
API_HASH = "2d18ff97ebdfc2f1f3a2596c48e3b4e4"  # Replace with your API Hash
BOT_TOKEN = "7931829452:AAEskMBAsT6G6bAhD5sS3vBRu4smmYgAU_o"  # Replace with your bot token

async def main():
    """Enhanced main function with error handling"""
    try:
        bot = AdvancedAutoForwardBot(API_ID, API_HASH, BOT_TOKEN)
        await bot.initialize()
        await bot.run()
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        # Attempt graceful shutdown
        try:
            if 'bot' in locals():
                await bot.shutdown()
        except:
            pass

if __name__ == "__main__":
    # Enhanced error handling for the entire application
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Application stopped by user")
    except Exception as e:
        logger.error(f"❌ Application error: {e}")
