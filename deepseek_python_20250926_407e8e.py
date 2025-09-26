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
        self.init_database()
    
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
            await self.client(
                self.client.functions.bots.SetBotCommandsRequest(
                    scope=self.client.types.BotCommandScopeDefault(),
                    lang_code='en',
                    commands=[self.client.types.BotCommand(command=cmd, description=desc) 
                             for cmd, desc in commands]
                )
            )
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
                cache_time, result = self._sub_cache[cache_key]
                if (datetime.now().timestamp() - cache_time) < 300:  # 5 minutes
                    return result
            
            channel_entity = await self.client.get_entity(FORCE_SUB_CHANNEL)
            participant = await self.client.get_permissions(channel_entity, user_id)
            result = participant is not None
            
            if not hasattr(self, '_sub_cache'):
                self._sub_cache = {}
            self._sub_cache[cache_key] = (datetime.now().timestamp(), result)
            
            return result
        except Exception as e:
            logger.error(f"❌ Force subscribe check error: {e}")
            return True  # Allow access if check fails

    async def show_force_subscribe(self, event):
        """Enhanced force subscribe message"""
        force_sub_text = f"""
🔔 **Subscription Required**

To use this bot, you need to join our channel first:

**Channel:** {FORCE_SUB_CHANNEL}

Please join the channel and then try again.

After joining, click the button below to verify.
        """
        
        buttons = [
            [Button.url("📢 Join Channel", f"https://t.me/{FORCE_SUB_CHANNEL.replace('@', '')}")],
            [Button.inline("✅ I've Joined", b"check_subscription")]
        ]
        
        await event.reply(force_sub_text, buttons=buttons)

    # Enhanced dashboard with statistics
    async def show_dashboard(self, event):
        """Enhanced dashboard with comprehensive statistics"""
        user = await event.get_sender()
        
        if user.id not in self.user_sessions:
            await event.reply("❌ Please login first using `/login`")
            return
        
        user_data = self.user_sessions[user.id]
        source_channel = self.source_channels.get(user.id, {})
        target_channels = self.target_channels.get(user.id, [])
        forwarding_status = self.auto_forwarding.get(user.id, False)
        stats = self.forwarding_stats.get(user.id, {})
        settings = self.forward_settings.get(user.id, self.default_settings)
        
        # Calculate active targets
        active_targets = len([t for t in target_channels if t.get('is_active', True)])
        
        dashboard_text = f"""
📊 **Enhanced Dashboard**

👤 **Account Info:**
   • Name: {user_data.get('first_name', 'N/A')}
   • Username: @{user_data.get('username', 'N/A')}
   • Phone: `{user_data.get('phone_number', 'N/A')}`
   • Login: {user_data.get('login_time', 'N/A')}

📡 **Source Channel:**
   • {source_channel.get('name', 'Not set')}
   • Last ID: {source_channel.get('last_message_id', 0)}

🎯 **Target Channels:** {active_targets}/{len(target_channels)} active

🔄 **Auto Forwarding:** {'✅ Active' if forwarding_status else '❌ Inactive'}

📈 **Statistics:**
   • Total Forwarded: {stats.get('total_forwarded', 0)}
   • Last Forwarded: {stats.get('last_forwarded', 'Never')}

⚙️ **Settings:**
   • Delay: {settings.get('delay_seconds', 1)}s
   • Media: {'✅' if settings.get('forward_media', True) else '❌'}
   • URL Previews: {'✅' if settings.get('url_previews', True) else '❌'}
   • Max Length: {settings.get('max_message_length', 4000)} chars
        """
        
        buttons = [
            [Button.inline("🔄 Toggle Forwarding", b"toggle_forwarding"),
             Button.inline("⚙️ Settings", b"show_settings")],
            [Button.inline("📡 Set Source", b"set_source"),
             Button.inline("🎯 Manage Targets", b"manage_targets")],
            [Button.inline("🔄 Word Replace", b"word_replacements"),
             Button.inline("🔗 Link Replace", b"link_replacements")],
            [Button.inline("📊 Advanced Stats", b"advanced_stats"),
             Button.inline("🆘 Help", b"show_help")]
        ]
        
        await event.reply(dashboard_text, buttons=buttons)

    # Enhanced settings management
    async def show_settings(self, event):
        """Enhanced settings interface"""
        user = await event.get_sender()
        
        if user.id not in self.user_sessions:
            return
        
        settings = self.forward_settings.get(user.id, self.default_settings)
        
        settings_text = f"""
⚙️ **Enhanced Settings**

Current configuration:

1. **Hide Header:** {'✅' if settings.get('hide_header') else '❌'}
2. **Forward Media:** {'✅' if settings.get('forward_media', True) else '❌'}
3. **URL Previews:** {'✅' if settings.get('url_previews', True) else '❌'}
4. **Remove Usernames:** {'✅' if settings.get('remove_usernames') else '❌'}
5. **Remove Links:** {'✅' if settings.get('remove_links') else '❌'}
6. **Forward Captions:** {'✅' if settings.get('caption_forward', True) else '❌'}
7. **Delay Between Forwards:** {settings.get('delay_seconds', 1)} seconds
8. **Max Message Length:** {settings.get('max_message_length', 4000)} characters

Click a button below to toggle settings.
        """
        
        buttons = [
            [Button.inline("1️⃣ Hide Header", b"toggle_hide_header"),
             Button.inline("2️⃣ Forward Media", b"toggle_forward_media")],
            [Button.inline("3️⃣ URL Previews", b"toggle_url_previews"),
             Button.inline("4️⃣ Remove Usernames", b"toggle_remove_usernames")],
            [Button.inline("5️⃣ Remove Links", b"toggle_remove_links"),
             Button.inline("6️⃣ Forward Captions", b"toggle_caption_forward")],
            [Button.inline("7️⃣ Set Delay", b"set_delay"),
             Button.inline("8️⃣ Set Max Length", b"set_max_length")],
            [Button.inline("💾 Save Settings", b"save_settings"),
             Button.inline("📊 Dashboard", b"show_dashboard")]
        ]
        
        await event.reply(settings_text, buttons=buttons)

    # Enhanced word replacement management
    async def show_word_replacements(self, event):
        """Enhanced word replacement interface"""
        user = await event.get_sender()
        
        if user.id not in self.user_sessions:
            return
        
        replacements = self.word_replacements.get(user.id, [])
        
        if not replacements:
            replacements_text = "No word replacements configured."
        else:
            replacements_text = "**Current Word Replacements:**\n\n"
            for i, rep in enumerate(replacements, 1):
                case_text = " (case-sensitive)" if rep.get('case_sensitive') else ""
                regex_text = " (regex)" if rep.get('is_regex') else ""
                replacements_text += f"{i}. `{rep['original']}` → `{rep['replacement']}`{case_text}{regex_text}\n"
        
        text = f"""
🔄 **Enhanced Word Replacements**

{replacements_text}

**Add new replacement:**
Format: `/addword original -> replacement`

**Options:**
- Add `case` for case-sensitive: `/addword hello -> hi case`
- Add `regex` for regex: `/addword h.*o -> hello regex`

**Examples:**
- `/addword hello -> hi`
- `/addword HELLO -> HI case`
- `/addword h.*o -> hello regex`
        """
        
        buttons = [
            [Button.inline("➕ Add Replacement", b"add_word_replacement"),
             Button.inline("🗑️ Remove All", b"clear_word_replacements")],
            [Button.inline("📊 Dashboard", b"show_dashboard")]
        ]
        
        await event.reply(text, buttons=buttons)

    # Enhanced link replacement management
    async def show_link_replacements(self, event):
        """Enhanced link replacement interface"""
        user = await event.get_sender()
        
        if user.id not in self.user_sessions:
            return
        
        replacements = self.link_replacements.get(user.id, [])
        
        if not replacements:
            replacements_text = "No link replacements configured."
        else:
            replacements_text = "**Current Link Replacements:**\n\n"
            for i, rep in enumerate(replacements, 1):
                query_text = " (preserve query)" if rep.get('preserve_query', True) else ""
                replacements_text += f"{i}. `{rep['original']}` → `{rep['replacement']}`{query_text}\n"
        
        text = f"""
🔗 **Enhanced Link Replacements**

{replacements_text}

**Add new replacement:**
Format: `/addlink original_url -> new_url`

**Options:**
- Add `noquery` to not preserve query parameters

**Examples:**
- `/addlink https://old.com -> https://new.com`
- `/addlink https://old.com -> https://new.com noquery`
        """
        
        buttons = [
            [Button.inline("➕ Add Link Replacement", b"add_link_replacement"),
             Button.inline("🗑️ Remove All", b"clear_link_replacements")],
            [Button.inline("📊 Dashboard", b"show_dashboard")]
        ]
        
        await event.reply(text, buttons=buttons)

    # Enhanced logout with cleanup
    async def handle_logout(self, event):
        """Enhanced logout with proper cleanup"""
        user = await event.get_sender()
        
        if user.id not in self.user_sessions:
            await event.reply("❌ You are not logged in.")
            return
        
        try:
            # Stop message listener
            await self.stop_message_listener(user.id)
            
            # Disconnect user client
            if user.id in self.user_clients:
                await self.user_clients[user.id].disconnect()
                del self.user_clients[user.id]
            
            # Clear all user data
            if user.id in self.user_sessions:
                del self.user_sessions[user.id]
            
            if user.id in self.source_channels:
                del self.source_channels[user.id]
            
            if user.id in self.target_channels:
                del self.target_channels[user.id]
            
            if user.id in self.forward_settings:
                del self.forward_settings[user.id]
            
            if user.id in self.auto_forwarding:
                del self.auto_forwarding[user.id]
            
            if user.id in self.forwarding_stats:
                del self.forwarding_stats[user.id]
            
            if user.id in self.word_replacements:
                del self.word_replacements[user.id]
            
            if user.id in self.link_replacements:
                del self.link_replacements[user.id]
            
            # Update database
            await self.db.execute(
                "UPDATE users SET status = 'logged_out', last_active = CURRENT_TIMESTAMP WHERE user_id = ?",
                (user.id,)
            )
            
            # Clear message history
            await self.db.execute("DELETE FROM message_history WHERE user_id = ?", (user.id,))
            
            # Remove session file
            session_file = f"sessions/user_{user.id}.session"
            if os.path.exists(session_file):
                os.remove(session_file)
            
            await event.reply("✅ Logout successful! All data has been cleared.")
            
        except Exception as e:
            logger.error(f"❌ Logout error: {e}")
            await event.reply("❌ Error during logout. Some data may not have been cleared.")

    # Enhanced help system
    async def show_help(self, event):
        """Enhanced help system with comprehensive information"""
        help_text = """
🤖 **Advanced Auto-Forward Bot Help**

**📋 Available Commands:**
- `/start` - Start the bot
- `/login` - Login with your account  
- `/dashboard` - Show your dashboard
- `/settings` - Configure settings
- `/logout` - Logout from the bot
- `/help` - Show this help message

**🔧 Enhanced Features:**
1. **Word Replacement** - Replace specific words in messages
2. **Link Replacement** - Replace URLs with your own links
3. **Media Forwarding** - Forward images, videos, documents
4. **Text Processing** - Remove usernames, links, customize messages
5. **Rate Limiting** - Prevent spam and API limits
6. **Duplicate Prevention** - Avoid forwarding same messages
7. **Priority System** - Set priority for target channels
8. **Statistics** - Track your forwarding activity

**⚙️ Settings Explained:**
- **Hide Header**: Remove original message header
- **Forward Media**: Forward images/videos/documents
- **URL Previews**: Show link previews
- **Remove Usernames**: Remove @mentions from messages  
- **Remove Links**: Remove all URLs from messages
- **Forward Captions**: Forward captions with media
- **Delay**: Seconds between forwarding to different targets
- **Max Length**: Maximum message length (characters)

**🛠️ Advanced Usage:**
- Use regex for complex word replacements
- Preserve query parameters in link replacements  
- Case-sensitive word matching
- Priority-based target channel management

**⚠️ Important Notes:**
- Keep your session file safe
- Monitor your forwarding activity
- Respect Telegram's terms of service
- Use appropriate delays to avoid limits

Need more help? Contact the bot administrator.
        """
        
        buttons = [
            [Button.inline("📊 Dashboard", b"show_dashboard"),
             Button.inline("⚙️ Settings", b"show_settings")],
            [Button.inline("🔄 Word Replace", b"word_replacements"),
             Button.inline("🔗 Link Replace", b"link_replacements")],
            [Button.inline("🚀 Quick Start", b"quick_setup")]
        ]
        
        await event.reply(help_text, buttons=buttons)

    # Enhanced button handler
    def register_enhanced_handlers(self):
        """Register all enhanced event handlers"""
        
        @self.client.on(events.NewMessage(pattern='/start'))
        async def start_handler(event):
            """Enhanced start handler"""
            user = await event.get_sender()
            
            if not await self.check_force_subscribe(user.id):
                await self.show_force_subscribe(event)
                return
            
            welcome_text = """
🚀 **Advanced Auto-Forward Bot**

Welcome to the most advanced Telegram auto-forwarding solution!

**🌟 Key Features:**
- ✅ Smart message forwarding with filters
- 🔄 Word & link replacement system  
- 📊 Comprehensive statistics & analytics
- ⚙️ Highly customizable settings
- 🔒 Secure session management
- 📱 Media forwarding support
- 🛡️ Rate limiting & duplicate prevention

**Quick Start:**
1. Login with `/login`
2. Set source channel
3. Add target channels  
4. Configure settings
5. Start forwarding!

Use `/help` for detailed instructions.
            """
            
            buttons = [
                [Button.inline("🔐 Login", b"start_login"),
                 Button.inline("🆘 Help", b"show_help")],
                [Button.inline("📊 Demo", b"show_demo"),
                 Button.inline("⚡ Features", b"show_features")]
            ]
            
            await event.reply(welcome_text, buttons=buttons)

        @self.client.on(events.NewMessage(pattern='/login'))
        async def login_command_handler(event):
            await self.handle_login_command(event)

        @self.client.on(events.NewMessage(pattern='/code'))
        async def code_handler(event):
            await self.handle_code_verification(event)

        @self.client.on(events.NewMessage(pattern='/dashboard'))
        async def dashboard_handler(event):
            await self.show_dashboard(event)

        @self.client.on(events.NewMessage(pattern='/settings'))
        async def settings_handler(event):
            await self.show_settings(event)

        @self.client.on(events.NewMessage(pattern='/help'))
        async def help_handler(event):
            await self.show_help(event)

        @self.client.on(events.NewMessage(pattern='/logout'))
        async def logout_handler(event):
            await self.handle_logout(event)

        @self.client.on(events.CallbackQuery)
        async def callback_handler(event):
            """Enhanced callback query handler"""
            user = await event.get_sender()
            data = event.data.decode('utf-8')
            
            try:
                if data == "start_login":
                    await self.handle_login_command(event)
                
                elif data == "show_dashboard":
                    await self.show_dashboard(event)
                
                elif data == "show_settings":
                    await self.show_settings(event)
                
                elif data == "show_help":
                    await self.show_help(event)
                
                elif data == "word_replacements":
                    await self.show_word_replacements(event)
                
                elif data == "link_replacements":
                    await self.show_link_replacements(event)
                
                elif data == "toggle_forwarding":
                    await self.toggle_auto_forwarding(user.id, event)
                
                # Add more callback handlers as needed
                
                await event.answer()
                
            except Exception as e:
                logger.error(f"❌ Callback error: {e}")
                await event.answer("❌ Error processing request", alert=True)

    async def toggle_auto_forwarding(self, user_id: int, event):
        """Enhanced auto forwarding toggle"""
        if user_id not in self.user_sessions:
            await event.reply("❌ Please login first.")
            return
        
        if user_id not in self.source_channels:
            await event.reply("❌ Please set a source channel first.")
            return
        
        if user_id not in self.target_channels or not self.target_channels[user_id]:
            await event.reply("❌ Please add target channels first.")
            return
        
        current_status = self.auto_forwarding.get(user_id, False)
        new_status = not current_status
        
        self.auto_forwarding[user_id] = new_status
        
        # Update database
        await self.db.execute('''
            INSERT OR REPLACE INTO auto_forwarding (user_id, is_active, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        ''', (user_id, int(new_status)))
        
        if new_status:
            await self.start_message_listener(user_id)
            await event.reply("✅ Auto forwarding started!")
        else:
            await self.stop_message_listener(user_id)
            await event.reply("❌ Auto forwarding stopped!")
        
        await self.show_dashboard(event)

    async def run(self):
        """Enhanced run method with graceful shutdown"""
        try:
            await self.initialize()
            logger.info("🤖 Bot is now running. Press Ctrl+C to stop.")
            await self.client.run_until_disconnected()
        except KeyboardInterrupt:
            logger.info("🛑 Bot stopped by user")
        except Exception as e:
            logger.error(f"❌ Bot crashed: {e}")
        finally:
            await self.cleanup()

    async def cleanup(self):
        """Enhanced cleanup with proper resource management"""
        logger.info("🧹 Cleaning up resources...")
        
        # Disconnect all user clients
        for user_id, client in self.user_clients.items():
            try:
                await client.disconnect()
            except Exception as e:
                logger.error(f"❌ Error disconnecting client for user {user_id}: {e}")
        
        # Disconnect main client
        try:
            await self.client.disconnect()
        except Exception as e:
            logger.error(f"❌ Error disconnecting main client: {e}")
        
        logger.info("✅ Cleanup completed")

# Enhanced configuration loading
def load_config():
    """Load configuration from environment variables with fallbacks"""
    config = {
        'api_id': int(os.getenv('API_ID', '29463837')),
        'api_hash': os.getenv('API_HASH', 'b0b6b14a6c5d5d4d6d6d6d6d6d6d6d6d'),
        'bot_token': os.getenv('BOT_TOKEN', ''),
        'admin_ids': [int(x) for x in os.getenv('ADMIN_IDS', '6651946441').split(',')]
    }
    
    # Validate required configuration
    if not config['bot_token']:
        raise ValueError("BOT_TOKEN environment variable is required")
    
    return config

# Enhanced main function
async def main():
    """Enhanced main function with error handling"""
    try:
        # Load configuration
        config = load_config()
        
        # Update global admin list
        global ADMIN_USER_IDS
        ADMIN_USER_IDS = config['admin_ids']
        
        # Create and run bot
        bot = AdvancedAutoForwardBot(
            api_id=config['api_id'],
            api_hash=config['api_hash'],
            bot_token=config['bot_token']
        )
        
        await bot.run()
        
    except ValueError as e:
        logger.error(f"❌ Configuration error: {e}")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")

if __name__ == '__main__':
    # Enhanced startup with proper event loop handling
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Bot stopped by user")
    except Exception as e:
        logger.error(f"💥 Fatal startup error: {e}")
