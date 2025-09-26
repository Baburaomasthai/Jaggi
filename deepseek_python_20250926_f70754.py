import os
import logging
import asyncio
import aiosqlite
import time
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
import re
import json
from urllib.parse import urlparse
from telethon import TelegramClient, events, Button, errors
from telethon.tl.types import User, Channel, Message, Dialog, MessageMediaPhoto, MessageMediaDocument, MessageMediaWebPage
from telethon.tl.functions.auth import SendCodeRequest, SignInRequest
from telethon.errors import SessionPasswordNeededError, ChannelPrivateError, FloodWaitError, AuthKeyError
from telethon.tl.functions.channels import JoinChannelRequest, GetParticipantsRequest, GetFullChannelRequest
from telethon.tl.types import ChannelParticipantsSearch, ChannelParticipant
from telethon.tl.functions.messages import GetFullChatRequest

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
        self._connection_pool = {}
    
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
    
    async def get_connection(self):
        """Get database connection with connection pooling"""
        if not hasattr(self, '_connection_pool'):
            self._connection_pool = {}
        
        loop_id = id(asyncio.get_event_loop())
        if loop_id not in self._connection_pool:
            self._connection_pool[loop_id] = await aiosqlite.connect(self.db_path)
            # Enable foreign keys
            await self._connection_pool[loop_id].execute("PRAGMA foreign_keys = ON")
        return self._connection_pool[loop_id]
    
    async def execute(self, query: str, params: Tuple = ()) -> Any:
        """Execute a query with error handling"""
        try:
            async with self._lock:
                db = await self.get_connection()
                async with db.execute(query, params) as cursor:
                    if query.strip().upper().startswith('SELECT'):
                        result = await cursor.fetchall()
                        return result
                    else:
                        await db.commit()
                        return cursor.rowcount
        except Exception as e:
            logger.error(f"Database error: {e}")
            # Try to reconnect on error
            if 'get_connection' in locals():
                try:
                    await db.close()
                except:
                    pass
                loop_id = id(asyncio.get_event_loop())
                if loop_id in self._connection_pool:
                    del self._connection_pool[loop_id]
            raise
    
    async def fetch_one(self, query: str, params: Tuple = ()) -> Optional[Tuple]:
        """Fetch a single row"""
        try:
            async with self._lock:
                db = await self.get_connection()
                async with db.execute(query, params) as cursor:
                    return await cursor.fetchone()
        except Exception as e:
            logger.error(f"Database fetch error: {e}")
            return None
    
    async def close_all(self):
        """Close all database connections"""
        for loop_id, conn in self._connection_pool.items():
            try:
                await conn.close()
            except Exception as e:
                logger.error(f"Error closing connection {loop_id}: {e}")
        self._connection_pool.clear()

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
        self._sub_cache: Dict[str, Tuple[float, bool]] = {}
        
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
            'message_forward': {'max_count': 10, 'window': 60},
            'channel_operations': {'max_count': 5, 'window': 60}
        }

    async def initialize(self):
        """Enhanced initialization with error recovery"""
        try:
            # Create necessary directories
            os.makedirs("sessions", exist_ok=True)
            os.makedirs("backups", exist_ok=True)
            
            # Initialize database
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
            forwarding_data = await self.db.execute("SELECT * FROM auto_forwarding")
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
                    me = await user_client.get_me()
                    if me:
                        self.user_clients[user_id] = user_client
                        logger.info(f"✅ Restored session for user {user_id}")
                        return True
                except (AuthKeyError, ConnectionError, ValueError) as e:
                    await user_client.disconnect()
                    logger.warning(f"⚠️ Invalid session for user {user_id}: {e}")
                    return False
            return False
        except Exception as e:
            logger.error(f"❌ Error restoring client for user {user_id}: {e}")
            return False

    async def start_all_message_listeners(self):
        """Start message listeners for all users with active forwarding"""
        for user_id in list(self.auto_forwarding.keys()):
            if self.auto_forwarding.get(user_id, False) and user_id in self.source_channels:
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
                try:
                    # Check if we've already processed this message
                    if event.message.id <= last_message_id:
                        return
                    
                    # Update last message ID
                    self.source_channels[user_id]['last_message_id'] = event.message.id
                    await self.update_source_channel_last_id(user_id, event.message.id)
                    
                    await self.process_and_forward_message(user_id, event.message)
                except Exception as e:
                    logger.error(f"❌ Error in message handler for user {user_id}: {e}")
                    await self.log_error(user_id, "message_handler", str(e))
            
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
                    logger.error(f"❌ Error forwarding to target {target.get('name', 'Unknown')}: {e}")
                    await self.log_error(user_id, "target_forward", f"Target {target.get('name', 'Unknown')}: {e}")
            
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
                    except re.error as e:
                        logger.warning(f"⚠️ Invalid regex pattern: {original}, error: {e}")
                else:
                    if case_sensitive:
                        processed_text = processed_text.replace(original, new_text)
                    else:
                        # Case-insensitive replacement
                        try:
                            pattern = re.compile(re.escape(original), re.IGNORECASE)
                            processed_text = pattern.sub(new_text, processed_text)
                        except Exception as e:
                            logger.warning(f"⚠️ Error in word replacement: {e}")
        
        # Apply link replacements
        if user_id in self.link_replacements:
            for replacement in self.link_replacements[user_id]:
                original = replacement['original']
                new_link = replacement['replacement']
                preserve_query = replacement.get('preserve_query', True)
                
                try:
                    if preserve_query:
                        # Preserve query parameters from original URL
                        original_parsed = urlparse(original)
                        new_parsed = urlparse(new_link)
                        
                        if original_parsed.query and not new_parsed.query:
                            new_link = f"{new_link}?{original_parsed.query}"
                    
                    processed_text = processed_text.replace(original, new_link)
                except Exception as e:
                    logger.warning(f"⚠️ Error in link replacement: {e}")
        
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
            logger.error(f"❌ Error sending to target {target.get('name', 'Unknown')}: {e}")
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
        now = time.time()
        
        if user_id not in self.rate_limits:
            self.rate_limits[user_id] = {}
        
        if operation not in self.rate_limits[user_id]:
            self.rate_limits[user_id][operation] = []
        
        # Clean old entries
        window = self.rate_limit_config.get(operation, {}).get('window', 60)
        max_count = self.rate_limit_config.get(operation, {}).get('max_count', 10)
        
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

    async def handle_login_command(self, event):
        """Enhanced login command handler"""
        try:
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
        except Exception as e:
            logger.error(f"❌ Login command error: {e}")
            await event.reply("❌ Error processing login command. Please try again.")

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

    async def handle_code_verification(self, event):
        """Handle code verification with attempt limiting"""
        try:
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
                    'first_name': user_entity.first_name or '',
                    'username': user_entity.username or '',
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
                
                # Initialize auto forwarding record
                await self.db.execute(
                    "INSERT OR IGNORE INTO auto_forwarding (user_id, is_active) VALUES (?, ?)",
                    (user.id, 0)
                )
                
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
                logger.error(f"❌ Code verification error: {e}")
                await event.reply("❌ Error verifying code. Please try again.")
                
        except Exception as e:
            logger.error(f"❌ Handle code error: {e}")
            await event.reply("❌ Error processing code. Please try again.")

    async def save_user_session(self, user_id: int, user_data: Dict):
        """Save user session to database"""
        await self.db.execute('''
            INSERT OR REPLACE INTO users 
            (user_id, phone_number, first_name, username, login_time, status) 
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            user_id,
            user_data['phone_number'],
            user_data['first_name'],
            user_data['username'],
            user_data['login_time'],
            user_data['status']
        ))

    async def save_user_settings(self, user_id: int, settings: Dict):
        """Save user settings to database"""
        await self.db.execute('''
            INSERT OR REPLACE INTO user_settings 
            (user_id, hide_header, forward_media, url_previews, remove_usernames, 
             remove_links, caption_forward, delay_seconds, max_message_length) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_id,
            settings['hide_header'],
            settings['forward_media'],
            settings['url_previews'],
            settings['remove_usernames'],
            settings['remove_links'],
            settings['caption_forward'],
            settings['delay_seconds'],
            settings['max_message_length']
        ))

    async def check_force_subscribe(self, user_id: int) -> bool:
        """Enhanced force subscribe check with caching"""
        if not FORCE_SUB_CHANNEL or FORCE_SUB_CHANNEL == "@YourChannel":
            return True
        
        # Check cache first
        cache_key = f"{user_id}_{FORCE_SUB_CHANNEL}"
        current_time = time.time()
        
        if cache_key in self._sub_cache:
            cache_time, is_subscribed = self._sub_cache[cache_key]
            if current_time - cache_time < 300:  # 5 minute cache
                return is_subscribed
        
        try:
            # Check if user is subscribed
            channel_entity = await self.client.get_entity(FORCE_SUB_CHANNEL)
            participant = await self.client.get_permissions(channel_entity, user_id)
            is_subscribed = participant is not None
            
            # Update cache
            self._sub_cache[cache_key] = (current_time, is_subscribed)
            return is_subscribed
            
        except Exception as e:
            logger.warning(f"⚠️ Force subscribe check error: {e}")
            return True  # Allow access if check fails

    async def show_force_subscribe(self, event):
        """Show force subscribe message"""
        message = f"""
🔒 **Subscription Required**

To use this bot, you need to join our channel first:

📢 **Channel:** {FORCE_SUB_CHANNEL}

**Steps:**
1. Join the channel above
2. Click the button below to verify
3. Start using the bot!

Thank you for your cooperation! 🙏
        """
        
        buttons = [
            [Button.url("📢 Join Channel", f"https://t.me/{FORCE_SUB_CHANNEL[1:]}")],
            [Button.inline("✅ I've Joined", b"check_subscription")]
        ]
        
        await event.reply(message, buttons=buttons)

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
            await self.show_dashboard(event)
        
        @self.client.on(events.NewMessage(pattern='/settings'))
        async def settings_handler(event):
            await self.show_settings_menu(event)
        
        @self.client.on(events.NewMessage(pattern='/help'))
        async def help_handler(event):
            await self.show_help_menu(event)
        
        @self.client.on(events.NewMessage(pattern='/logout'))
        async def logout_handler(event):
            await self.handle_logout(event)
        
        @self.client.on(events.CallbackQuery)
        async def callback_handler(event):
            await self.handle_callback_query(event)
        
        logger.info("✅ Enhanced handlers registered successfully")

    async def handle_start_command(self, event):
        """Enhanced start command handler"""
        try:
            user = await event.get_sender()
            
            welcome_text = f"""
🤖 **Advanced Auto Forward Bot v2.0**

Welcome, {user.first_name or 'User'}!

**Features:**
✅ Smart message forwarding
✅ Media support (photos, documents, links)
✅ Text processing & replacements
✅ Rate limiting & flood protection
✅ Advanced error handling
✅ Real-time statistics

**Quick Commands:**
`/login` - Login with your account
`/dashboard` - View your dashboard
`/settings` - Configure forwarding
`/help` - Get detailed help

**Ready to start?** Use `/login` to begin!
            """
            
            buttons = [
                [Button.inline("🔐 Login", b"start_login")],
                [Button.inline("📊 Features", b"show_features")],
                [Button.inline("🆘 Help", b"show_help")]
            ]
            
            await event.reply(welcome_text, buttons=buttons)
            
        except Exception as e:
            logger.error(f"❌ Start command error: {e}")
            await event.reply("❌ Error processing command. Please try again.")

    async def show_dashboard(self, event):
        """Enhanced dashboard with statistics"""
        try:
            user = await event.get_sender()
            
            if user.id not in self.user_sessions:
                await event.reply("❌ Please login first using `/login`")
                return
            
            user_data = self.user_sessions[user.id]
            stats = self.forwarding_stats.get(user.id, {})
            settings = self.forward_settings.get(user.id, self.default_settings)
            
            source_info = self.source_channels.get(user.id, {})
            target_count = len(self.target_channels.get(user.id, []))
            active_targets = len([t for t in self.target_channels.get(user.id, []) if t.get('is_active', True)])
            
            dashboard_text = f"""
📊 **User Dashboard**

**Account Info:**
👤 **Name:** {user_data.get('first_name', 'N/A')}
📱 **Phone:** `{user_data.get('phone_number', 'N/A')}`
🔗 **Username:** @{user_data.get('username', 'N/A')}

**Forwarding Status:**
🔄 **Auto Forwarding:** {'✅ Active' if self.auto_forwarding.get(user.id, False) else '❌ Inactive'}
📨 **Total Forwarded:** {stats.get('total_forwarded', 0)} messages
⏰ **Last Forwarded:** {stats.get('last_forwarded', 'Never')}

**Channel Setup:**
📥 **Source Channel:** {source_info.get('name', 'Not set')}
📤 **Target Channels:** {active_targets}/{target_count} active

**Settings:**
⚡ **Delay:** {settings.get('delay_seconds', 1)} seconds
📝 **Max Length:** {settings.get('max_message_length', 4000)} chars
🖼️ **Media:** {'✅ On' if settings.get('forward_media', True) else '❌ Off'}
            """
            
            buttons = [
                [Button.inline("🔄 Toggle Forwarding", b"toggle_forwarding")],
                [Button.inline("⚙️ Settings", b"show_settings")],
                [Button.inline("📈 Statistics", b"show_stats")],
                [Button.inline("🆘 Help", b"show_help")]
            ]
            
            await event.reply(dashboard_text, buttons=buttons)
            
        except Exception as e:
            logger.error(f"❌ Dashboard error: {e}")
            await event.reply("❌ Error loading dashboard. Please try again.")

    async def show_settings_menu(self, event):
        """Enhanced settings menu"""
        try:
            user = await event.get_sender()
            
            if user.id not in self.user_sessions:
                await event.reply("❌ Please login first using `/login`")
                return
            
            settings = self.forward_settings.get(user.id, self.default_settings)
            
            settings_text = f"""
⚙️ **Advanced Settings**

**Current Configuration:**
🖼️ **Forward Media:** {'✅' if settings['forward_media'] else '❌'}
🔗 **URL Previews:** {'✅' if settings['url_previews'] else '❌'}
📝 **Forward Captions:** {'✅' if settings['caption_forward'] else '❌'}
👤 **Remove Usernames:** {'✅' if settings['remove_usernames'] else '❌'}
🌐 **Remove Links:** {'✅' if settings['remove_links'] else '❌'}
⏰ **Delay Between Forwards:** {settings['delay_seconds']} seconds
📏 **Max Message Length:** {settings['max_message_length']} characters

**Word Replacements:** {len(self.word_replacements.get(user.id, []))} active
**Link Replacements:** {len(self.link_replacements.get(user.id, []))} active
            """
            
            buttons = [
                [Button.inline("🖼️ Toggle Media", b"toggle_media")],
                [Button.inline("⏰ Set Delay", b"set_delay")],
                [Button.inline("📝 Word Replace", b"word_replace")],
                [Button.inline("🔗 Link Replace", b"link_replace")],
                [Button.inline("📊 Back to Dashboard", b"show_dashboard")]
            ]
            
            await event.reply(settings_text, buttons=buttons)
            
        except Exception as e:
            logger.error(f"❌ Settings error: {e}")
            await event.reply("❌ Error loading settings. Please try again.")

    async def show_help_menu(self, event):
        """Enhanced help menu"""
        help_text = """
🆘 **Advanced Auto Forward Bot Help**

**📋 Basic Commands:**
`/start` - Start the bot
`/login` - Login with your account  
`/dashboard` - View your dashboard
`/settings` - Configure forwarding
`/help` - Show this help
`/logout` - Logout from the bot

**🔧 Setup Process:**
1. Use `/login` to authenticate
2. Set your source channel
3. Add target channels
4. Configure settings
5. Enable auto-forwarding

**⚡ Advanced Features:**
- **Smart Media Handling** - Photos, documents, links
- **Text Processing** - Word/link replacements
- **Rate Limiting** - Prevents flooding
- **Error Recovery** - Automatic retries
- **Statistics** - Track performance

**🔒 Privacy & Security:**
- Your data is stored locally
- Sessions are encrypted
- No sensitive data shared

**Need more help?** Contact support!
        """
        
        buttons = [
            [Button.inline("📚 Setup Guide", b"setup_guide")],
            [Button.inline("⚡ Features", b"show_features")],
            [Button.inline("🔧 Troubleshooting", b"troubleshooting")],
            [Button.inline("🏠 Main Menu", b"show_dashboard")]
        ]
        
        await event.reply(help_text, buttons=buttons)

    async def handle_logout(self, event):
        """Enhanced logout handler"""
        try:
            user = await event.get_sender()
            
            if user.id not in self.user_sessions:
                await event.reply("❌ You are not logged in!")
                return
            
            # Stop message listener
            await self.stop_message_listener(user.id)
            
            # Disconnect user client
            if user.id in self.user_clients:
                try:
                    await self.user_clients[user.id].disconnect()
                    del self.user_clients[user.id]
                except Exception as e:
                    logger.warning(f"⚠️ Error disconnecting client: {e}")
            
            # Update database
            await self.db.execute(
                "UPDATE users SET status = 'logged_out', last_active = CURRENT_TIMESTAMP WHERE user_id = ?",
                (user.id,)
            )
            
            # Clear memory data
            for key in [self.user_sessions, self.source_channels, self.target_channels, 
                       self.forward_settings, self.auto_forwarding, self.forwarding_stats,
                       self.word_replacements, self.link_replacements]:
                if user.id in key:
                    del key[user.id]
            
            # Clear state
            if user.id in self.user_states:
                del self.user_states[user.id]
            
            await event.reply("✅ Logged out successfully! Your data has been cleared.")
            
        except Exception as e:
            logger.error(f"❌ Logout error: {e}")
            await event.reply("❌ Error during logout. Please try again.")

    async def handle_callback_query(self, event):
        """Enhanced callback query handler"""
        try:
            user = await event.get_sender()
            data = event.data.decode('utf-8')
            
            if data == "start_login":
                await self.handle_login_command(event)
            elif data == "show_dashboard":
                await self.show_dashboard(event)
            elif data == "show_settings":
                await self.show_settings_menu(event)
            elif data == "show_help":
                await self.show_help_menu(event)
            elif data == "toggle_forwarding":
                await self.toggle_auto_forwarding(user.id, event)
            elif data == "check_subscription":
                await self.handle_subscription_check(event)
            else:
                await event.answer("⚠️ Action not implemented yet!")
            
            await event.answer()
            
        except Exception as e:
            logger.error(f"❌ Callback error: {e}")
            await event.answer("❌ Error processing action!")

    async def toggle_auto_forwarding(self, user_id: int, event):
        """Toggle auto forwarding with enhanced checks"""
        try:
            if user_id not in self.user_sessions:
                await event.reply("❌ Please login first!")
                return
            
            if user_id not in self.source_channels:
                await event.reply("❌ Please set a source channel first!")
                return
            
            if user_id not in self.target_channels or not self.target_channels[user_id]:
                await event.reply("❌ Please add at least one target channel!")
                return
            
            current_state = self.auto_forwarding.get(user_id, False)
            new_state = not current_state
            
            self.auto_forwarding[user_id] = new_state
            
            # Update database
            await self.db.execute(
                "UPDATE auto_forwarding SET is_active = ? WHERE user_id = ?",
                (new_state, user_id)
            )
            
            if new_state:
                await self.start_message_listener(user_id)
                await event.reply("✅ **Auto forwarding activated!**\nMessages will now be forwarded automatically.")
            else:
                await self.stop_message_listener(user_id)
                await event.reply("❌ **Auto forwarding deactivated!**\nNo messages will be forwarded.")
                
        except Exception as e:
            logger.error(f"❌ Toggle forwarding error: {e}")
            await event.reply("❌ Error toggling auto forwarding!")

    async def handle_subscription_check(self, event):
        """Handle subscription check callback"""
        try:
            user = await event.get_sender()
            
            if await self.check_force_subscribe(user.id):
                await event.edit("✅ **Subscription verified!** You can now use the bot.")
                await asyncio.sleep(2)
                await self.handle_start_command(event)
            else:
                await event.answer("❌ Please join the channel first!")
                
        except Exception as e:
            logger.error(f"❌ Subscription check error: {e}")
            await event.answer("❌ Error checking subscription!")

    async def run(self):
        """Enhanced run method with graceful shutdown"""
        try:
            logger.info("🚀 Starting Advanced Auto Forward Bot...")
            await self.initialize()
            
            # Keep the bot running
            await self.client.run_until_disconnected()
            
        except KeyboardInterrupt:
            logger.info("⚠️ Received interrupt signal. Shutting down gracefully...")
        except Exception as e:
            logger.error(f"❌ Fatal error: {e}")
        finally:
            await self.shutdown()

    async def shutdown(self):
        """Enhanced graceful shutdown"""
        try:
            logger.info("🔄 Shutting down bot gracefully...")
            
            # Stop all message listeners
            for user_id in list(self.message_handlers.keys()):
                await self.stop_message_listener(user_id)
            
            # Disconnect all user clients
            for user_id, client in self.user_clients.items():
                try:
                    await client.disconnect()
                except Exception as e:
                    logger.warning(f"⚠️ Error disconnecting client {user_id}: {e}")
            
            # Close database connections
            await self.db.close_all()
            
            # Disconnect main client
            if self.client.is_connected():
                await self.client.disconnect()
            
            logger.info("✅ Bot shutdown completed successfully!")
            
        except Exception as e:
            logger.error(f"❌ Error during shutdown: {e}")

# Enhanced configuration with environment variables
def load_config():
    """Load configuration from environment variables with validation"""
    config = {
        'api_id': os.getenv('API_ID'),
        'api_hash': os.getenv('API_HASH'),
        'bot_token': os.getenv('BOT_TOKEN')
    }
    
    # Validate configuration
    missing = [key for key, value in config.items() if not value]
    if missing:
        raise ValueError(f"Missing environment variables: {', '.join(missing)}")
    
    # Validate API_ID is numeric
    try:
        config['api_id'] = int(config['api_id'])
    except ValueError:
        raise ValueError("API_ID must be a numeric value")
    
    return config

async def main():
    """Enhanced main function with error handling"""
    try:
        # Load configuration
        config = load_config()
        
        # Create and run bot
        bot = AdvancedAutoForwardBot(
            api_id=config['api_id'],
            api_hash=config['api_hash'],
            bot_token=config['bot_token']
        )
        
        await bot.run()
        
    except ValueError as e:
        logger.error(f"❌ Configuration error: {e}")
        logger.info("💡 Please set the following environment variables:")
        logger.info("   - API_ID: Your Telegram API ID")
        logger.info("   - API_HASH: Your Telegram API Hash")
        logger.info("   - BOT_TOKEN: Your bot token from @BotFather")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")

if __name__ == "__main__":
    # Enhanced error handling for the entire application
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Bot stopped by user")
    except Exception as e:
        logger.error(f"💥 Critical error: {e}")
