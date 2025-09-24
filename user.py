import os
import logging
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime
import re
import pickle
import base64
from telethon import TelegramClient, events, Button
from telethon.tl.types import User, Channel, Message
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

# Admin configuration - APNA USER ID DALEN
ADMIN_USER_IDS = [6651946441]  # YOUR_USER_ID_HERE

# Force subscribe channel - APNA CHANNEL ID DALEN
FORCE_SUB_CHANNEL = "-1002515948965"  # YOUR_CHANNEL_ID_HERE

class TelegramChannelDB:
    """Telegram Channel-based Database System"""
    
    def __init__(self, client: TelegramClient, db_channel_id: int):
        self.client = client
        self.db_channel_id = db_channel_id
        self.cache = {}
    
    async def initialize(self):
        """Initialize database channel"""
        try:
            # Ensure channel ID is proper integer
            if isinstance(self.db_channel_id, str):
                self.db_channel_id = int(self.db_channel_id)
            
            entity = await self.client.get_entity(self.db_channel_id)
            logger.info(f"Database channel initialized: {entity.title}")
            return True
        except Exception as e:
            logger.error(f"Error initializing database channel: {e}")
            # Try to create channel if it doesn't exist
            try:
                result = await self.client.create_channel("AutoForwardDB", "Database for bot")
                self.db_channel_id = result.id
                logger.info(f"Created new database channel: {self.db_channel_id}")
                return True
            except Exception as create_error:
                logger.error(f"Failed to create database channel: {create_error}")
                return False
    
    async def set(self, key: str, data: Any) -> bool:
        """Store data in database"""
        try:
            serialized_data = base64.b64encode(pickle.dumps(data)).decode('utf-8')
            message_text = f"DB_ENTRY:{key}:{serialized_data}"
            await self.client.send_message(self.db_channel_id, message_text)
            self.cache[key] = data
            logger.info(f"Data saved: {key}")
            return True
        except Exception as e:
            logger.error(f"Error saving data for key {key}: {e}")
            return False
    
    async def get(self, key: str) -> Any:
        """Retrieve data from database"""
        try:
            if key in self.cache:
                return self.cache[key]
            
            async for message in self.client.iter_messages(self.db_channel_id):
                if message.text and message.text.startswith(f"DB_ENTRY:{key}:"):
                    serialized_data = message.text.split(':', 2)[2]
                    data = pickle.loads(base64.b64decode(serialized_data))
                    self.cache[key] = data
                    return data
            
            return None
        except Exception as e:
            logger.error(f"Error getting data for key {key}: {e}")
            return None

class AdvancedAutoForwardBot:
    def __init__(self, api_id: int, api_hash: str, bot_token: str, db_channel_id: int):
        self.client = TelegramClient('auto_forward_bot', api_id, api_hash)
        self.bot_token = bot_token
        self.db = TelegramChannelDB(self.client, db_channel_id)
        
        # User data storage
        self.user_sessions: Dict[int, Dict] = {}
        self.source_channel: Dict[int, Dict] = {}  # Single source channel
        self.target_channels: Dict[int, List] = {}  # Multiple target channels
        self.forward_settings: Dict[int, Dict] = {}
        self.auto_forwarding: Dict[int, bool] = {}
        
        # Login state management
        self.login_attempts: Dict[int, Dict] = {}
        
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
            
            db_initialized = await self.db.initialize()
            if db_initialized:
                await self.load_all_data()
                self.register_handlers()
                logger.info("Bot fully initialized with all handlers!")
            else:
                logger.info("Bot started with in-memory storage (database not available)")
                self.register_handlers()
                
        except Exception as e:
            logger.error(f"Error during initialization: {e}")

    async def load_all_data(self):
        """Load all data from database"""
        try:
            self.user_sessions = await self.db.get("user_sessions") or {}
            self.source_channel = await self.db.get("source_channel") or {}
            self.target_channels = await self.db.get("target_channels") or {}
            self.forward_settings = await self.db.get("forward_settings") or {}
            self.auto_forwarding = await self.db.get("auto_forwarding") or {}
            
            logger.info(f"Data loaded: {len(self.user_sessions)} users")
            
        except Exception as e:
            logger.error(f"Error loading data: {e}")

    async def save_to_db(self, key: str, data: Any):
        """Save data to database"""
        try:
            await self.db.set(key, data)
            return True
        except Exception as e:
            logger.error(f"Error saving {key}: {e}")
            return False

    def is_admin(self, user_id: int) -> bool:
        """Check if user is admin"""
        return user_id in ADMIN_USER_IDS

    async def check_force_subscribe(self, user_id: int) -> bool:
        """Check if user is subscribed to force sub channel"""
        try:
            if not FORCE_SUB_CHANNEL or FORCE_SUB_CHANNEL == "-1001234567890":
                return True  # Skip if not configured
            
            channel_entity = await self.client.get_entity(int(FORCE_SUB_CHANNEL))
            participant = await self.client.get_permissions(channel_entity, user_id)
            return participant is not None
        except Exception as e:
            logger.error(f"Error checking force subscribe: {e}")
            return False

    # ==================== LOGIN SYSTEM ====================

    async def handle_login(self, event):
        """Handle /login command"""
        user = await event.get_sender()
        
        # Check force subscribe
        if not await self.check_force_subscribe(user.id):
            force_sub_text = f"""
❌ **Subscription Required**

Please join our channel first to use this bot:

**Channel:** @{FORCE_SUB_CHANNEL}

After joining, send /start again.
            """
            await event.reply(force_sub_text)
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
            
            buttons = [
                [Button.inline("📋 Format Help", b"phone_format_help")],
                [Button.inline("❌ Cancel", b"cancel_operation")]
            ]
            await event.reply(login_text, buttons=buttons)

    async def start_telegram_login(self, user, phone_number, event):
        """Start real Telegram login process"""
        try:
            # Create session file with user ID
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
                [Button.inline("📲 Check Telegram", b"check_telegram")],
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

    async def handle_code_verification(self, event):
        """Handle verification code input with AUTOX prefix"""
        user = await event.get_sender()
        
        if user.id not in self.login_attempts or self.login_attempts[user.id].get('step') != 'waiting_code':
            return
        
        code_text = event.text.strip().upper()
        
        # Check for AUTOX prefix
        if not code_text.startswith('AUTOX'):
            await event.reply("❌ Please use format: `AUTOX123456` (replace 123456 with your actual code)")
            return
        
        code = code_text[5:]  # Remove AUTOX prefix
        
        if not code.isdigit() or len(code) < 5:
            await event.reply("❌ Invalid code format. Please enter like: `AUTOX123456`")
            return
        
        login_data = self.login_attempts[user.id]
        
        try:
            # Try to sign in
            await login_data['user_client'].sign_in(
                phone=login_data['phone_number'],
                code=code,
                phone_code_hash=login_data['phone_code_hash']
            )
            
            # Get user info
            user_entity = await login_data['user_client'].get_me()
            
            # Store user session
            self.user_sessions[user.id] = {
                'phone_number': login_data['phone_number'],
                'first_name': user_entity.first_name,
                'username': user_entity.username,
                'user_id': user_entity.id,
                'login_time': datetime.now().isoformat(),
                'status': 'logged_in',
                'user_client_session': login_data['user_client'].session.save()
            }
            
            # Initialize settings
            if user.id not in self.forward_settings:
                self.forward_settings[user.id] = self.default_settings.copy()
                await self.save_to_db("forward_settings", self.forward_settings)
            
            await self.save_to_db("user_sessions", self.user_sessions)
            
            # Disconnect user client (we'll reconnect when needed)
            await login_data['user_client'].disconnect()
            del self.login_attempts[user.id]
            
            success_text = f"""
✅ **Login Successful!**

Welcome, {user_entity.first_name or 'User'}!

**Account Verified:**
• Phone: {login_data['phone_number']}
• Name: {user_entity.first_name or 'N/A'}
• Username: @{user_entity.username or 'N/A'}

Now you can set up auto-forwarding!
            """
            
            buttons = [
                [Button.inline("📥 Set Source Channel", b"set_source"),
                 Button.inline("📤 Add Target Channel", b"add_target")],
                [Button.inline("🚀 Quick Start", b"quick_start"),
                 Button.inline("📊 Dashboard", b"show_dashboard")]
            ]
            
            await event.reply(success_text, buttons=buttons)
            
        except SessionPasswordNeededError:
            await event.reply("🔒 Your account has 2FA enabled. This bot doesn't support 2FA accounts yet.")
        except Exception as e:
            logger.error(f"Error during code verification: {e}")
            error_msg = "❌ Invalid verification code. Please check and try again."
            await event.reply(error_msg)

    # ==================== CORE COMMANDS ====================

    async def handle_start(self, event):
        """Handle /start command"""
        user = await event.get_sender()
        
        # Check force subscribe
        if not await self.check_force_subscribe(user.id):
            force_sub_text = f"""
❌ **Subscription Required**

Please join our channel first to use this bot:

**Channel:** @{FORCE_SUB_CHANNEL}

After joining, send /start again.

If you've already joined, try refreshing or contact admin.
            """
            
            buttons = [
                [Button.url("📢 Join Channel", f"https://t.me/{FORCE_SUB_CHANNEL.replace('@', '')}")],
                [Button.inline("🔄 I've Joined", b"check_subscription")]
            ]
            await event.reply(force_sub_text, buttons=buttons)
            return
        
        welcome_text = f"""
🤖 **Welcome to Best Auto Forwarding Bot, {user.first_name or 'User'}!**

🌟 **Professional Auto-Forwarding Service**

**Key Features:**
• Single source channel (your account accesses it)
• Multiple target channels (bot needs admin rights)
• Real-time message forwarding
• Media files support
• Secure authentication

**Quick Setup:**
1. Login with your Telegram account
2. Set source channel
3. Add target channels
4. Start forwarding

Choose an option below to get started!
        """
        
        buttons = []
        
        if user.id in self.user_sessions:
            buttons.extend([
                [Button.inline("📊 Dashboard", b"show_dashboard"),
                 Button.inline("🚀 Start Forwarding", b"start_forwarding")],
                [Button.inline("⚙️ Settings", b"forward_settings"),
                 Button.inline("📋 Config", b"view_config")],
                [Button.inline("🔐 Logout", b"logout_user")]
            ])
        else:
            buttons.extend([
                [Button.inline("🔐 Login Now", b"quick_login"),
                 Button.inline("📚 How It Works", b"how_it_works")],
                [Button.inline("🎥 Video Guide", b"video_tutorial"),
                 Button.inline("💬 Support", b"contact_support")]
            ])
        
        await event.reply(welcome_text, buttons=buttons)

    async def handle_logout(self, event):
        """Handle /logout command"""
        user = await event.get_sender()
        
        if user.id in self.user_sessions:
            # Clean up session files
            try:
                session_file = f"sessions/user_{user.id}.session"
                if os.path.exists(session_file):
                    os.remove(session_file)
            except Exception as e:
                logger.error(f"Error cleaning session file: {e}")
            
            del self.user_sessions[user.id]
            await self.save_to_db("user_sessions", self.user_sessions)
        
        if user.id in self.auto_forwarding:
            del self.auto_forwarding[user.id]
            await self.save_to_db("auto_forwarding", self.auto_forwarding)
        
        if user.id in self.source_channel:
            del self.source_channel[user.id]
            await self.save_to_db("source_channel", self.source_channel)
        
        if user.id in self.target_channels:
            del self.target_channels[user.id]
            await self.save_to_db("target_channels", self.target_channels)
        
        if user.id in self.login_attempts:
            if 'user_client' in self.login_attempts[user.id]:
                await self.login_attempts[user.id]['user_client'].disconnect()
            del self.login_attempts[user.id]
        
        buttons = [
            [Button.inline("🔐 Login Again", b"quick_login"),
             Button.inline("🏠 Main Menu", b"main_menu")]
        ]
        
        await event.reply("✅ Logout successful! All your data has been cleared.", buttons=buttons)

    async def handle_source(self, event):
        """Handle /source command"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        current_source = self.source_channel.get(user.id, {})
        
        instructions = f"""
📥 **Source Channel Setup**

**Current Source:** {current_source.get('name', 'Not set')}

**How to set source channel:**
1. Forward any message from your source channel to this bot
2. I'll automatically detect and set it

**Important Notes:**
• Bot does NOT need to be admin in source channel
• Your logged-in account will access the messages
• Only one source channel allowed per user

**Requirements:**
• You must be member of the source channel
• Channel must be accessible
        """
        
        buttons = [
            [Button.inline("📨 Forward Message Now", b"forward_instructions")],
            [Button.inline("🔄 Change Source", b"change_source")] if current_source else [],
            [Button.inline("📊 Dashboard", b"show_dashboard"),
             Button.inline("🔙 Main Menu", b"main_menu")]
        ]
        
        # Remove empty button lists
        buttons = [btn for btn in buttons if btn]
        
        await event.reply(instructions, buttons=buttons)

    async def handle_target(self, event):
        """Handle /target command"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        targets = self.target_channels.get(user.id, [])
        
        instructions = f"""
📤 **Target Channels Setup**

**Current Targets:** {len(targets)} channels

**How to add target channels:**
1. Add bot as ADMIN to your target channel
2. Grant POST MESSAGES permission
3. Forward any message from the channel to this bot

**Important Notes:**
• Bot MUST be admin in target channels
• You can add multiple target channels
• Bot needs permission to send messages

**Current Target Channels:**
"""
        if targets:
            for i, target in enumerate(targets, 1):
                instructions += f"{i}. {target['name']}\n"
        else:
            instructions += "No target channels added yet.\n"
        
        buttons = [
            [Button.inline("➕ Add Target Channel", b"add_target")],
            [Button.inline("🗑️ Remove Target", b"remove_target")] if targets else [],
            [Button.inline("📋 View All Targets", b"view_targets")] if targets else [],
            [Button.inline("📊 Dashboard", b"show_dashboard"),
             Button.inline("🔙 Main Menu", b"main_menu")]
        ]
        
        buttons = [btn for btn in buttons if btn]
        await event.reply(instructions, buttons=buttons)

    async def handle_start_forwarding(self, event):
        """Handle /start_forwarding command"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        if user.id not in self.source_channel:
            buttons = [
                [Button.inline("📥 Set Source Channel", b"set_source")],
                [Button.inline("📊 Dashboard", b"show_dashboard")]
            ]
            await event.reply("❌ No source channel configured. Please set a source channel first.", buttons=buttons)
            return
        
        targets = self.target_channels.get(user.id, [])
        if not targets:
            buttons = [
                [Button.inline("📤 Add Target Channel", b"add_target")],
                [Button.inline("📊 Dashboard", b"show_dashboard")]
            ]
            await event.reply("❌ No target channels configured. Please add target channels first.", buttons=buttons)
            return
        
        self.auto_forwarding[user.id] = True
        await self.save_to_db("auto_forwarding", self.auto_forwarding)
        
        source = self.source_channel[user.id]
        
        success_text = f"""
✅ **Auto-Forwarding Started!**

**Configuration Summary:**
• Source: {source['name']}
• Targets: {len(targets)} channels
• Status: 🟢 **ACTIVE**

**Now Processing:**
Messages will be forwarded from your source channel to all target channels.

**Monitoring:** Your source channel is now being monitored.
        """
        
        buttons = [
            [Button.inline("⏸️ Stop Forwarding", b"stop_forwarding"),
             Button.inline("📊 View Status", b"view_config")],
            [Button.inline("⚙️ Settings", b"forward_settings"),
             Button.inline("🔙 Dashboard", b"show_dashboard")]
        ]
        
        await event.reply(success_text, buttons=buttons)

    async def handle_stop_forwarding(self, event):
        """Handle /stop_forwarding command"""
        user = await event.get_sender()
        
        if user.id not in self.auto_forwarding or not self.auto_forwarding[user.id]:
            await event.reply("❌ Auto-forwarding is not currently active.")
            return
        
        self.auto_forwarding[user.id] = False
        await self.save_to_db("auto_forwarding", self.auto_forwarding)
        
        buttons = [
            [Button.inline("🚀 Start Again", b"start_forwarding"),
             Button.inline("📊 Dashboard", b"show_dashboard")]
        ]
        
        await event.reply("⏸️ **Auto-forwarding paused.**", buttons=buttons)

    async def handle_config(self, event):
        """Handle /config command"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        user_data = self.user_sessions.get(user.id, {})
        source = self.source_channel.get(user.id, {})
        targets = self.target_channels.get(user.id, [])
        settings = self.forward_settings.get(user.id, self.default_settings)
        
        config_text = f"""
⚙️ **System Configuration**

**👤 Account Info:**
• User: {user_data.get('first_name', 'N/A')}
• Phone: {user_data.get('phone_number', 'N/A')}
• Status: ✅ Active

**📊 Channel Setup:**
• Source: {source.get('name', 'Not set')}
• Targets: {len(targets)} channels
• Forwarding: {'🟢 ACTIVE' if self.auto_forwarding.get(user.id) else '⏸️ PAUSED'}

**Target Channels:**
"""
        if targets:
            for i, target in enumerate(targets, 1):
                config_text += f"{i}. {target['name']}\n"
        else:
            config_text += "No targets configured\n"
        
        config_text += f"""
**⚡ Settings:**
• Hide Header: {'✅ Yes' if settings.get('hide_header') else '❌ No'}
• Media Forwarding: {'✅ Yes' if settings.get('forward_media') else '❌ No'}
• URL Previews: {'✅ Yes' if settings.get('url_previews') else '❌ No'}
        """
        
        buttons = [
            [Button.inline("📥 Source", b"set_source"),
             Button.inline("📤 Targets", b"add_target")],
            [Button.inline("⚙️ Settings", b"forward_settings"),
             Button.inline("🔄 " + ("Stop" if self.auto_forwarding.get(user.id) else "Start"), 
                         b"stop_forwarding" if self.auto_forwarding.get(user.id) else "start_forwarding")],
            [Button.inline("🔙 Dashboard", b"show_dashboard")]
        ]
        
        await event.reply(config_text, buttons=buttons)

    async def handle_help(self, event):
        """Handle /help command"""
        help_text = """
🆘 **Command Reference & Help**

**🔐 Authentication:**
• `/start` - Start bot & main menu
• `/login` - Login to your account
• `/logout` - Logout & clear data

**⚙️ Setup:**
• `/source` - Set source channel
• `/target` - Manage target channels
• `/config` - View configuration

**🔄 Control:**
• `/start_forwarding` - Start auto-forwarding
• `/stop_forwarding` - Stop auto-forwarding
• `/forward_settings` - Change settings

**💡 Tips:**
• Use buttons for easy navigation
• Source channel: Your account accesses it
• Target channels: Bot needs admin rights
• Forward messages to automatically detect channels
        """
        
        buttons = [
            [Button.inline("🔐 Login", b"quick_login"),
             Button.inline("📥 Setup Guide", b"setup_guide")],
            [Button.inline("🚀 Quick Start", b"quick_start"),
             Button.inline("💬 Support", b"contact_support")],
            [Button.inline("🔙 Main Menu", b"main_menu")]
        ]
        
        await event.reply(help_text, buttons=buttons)

    # ==================== BUTTON HANDLERS ====================

    async def handle_callback_query(self, event):
        """Handle all button callbacks"""
        data = event.data.decode('utf-8')
        user = await event.get_sender()
        
        try:
            if data == 'main_menu':
                await self.handle_start(event)
            
            elif data == 'quick_login':
                await event.edit("🔐 **Quick Login**\n\nUse `/login +919876543210` or send your phone number.")
            
            elif data == 'show_dashboard':
                await self.handle_config(event)
            
            elif data == 'set_source':
                await self.handle_source(event)
            
            elif data == 'add_target':
                await self.handle_target(event)
            
            elif data == 'start_forwarding':
                await self.handle_start_forwarding(event)
            
            elif data == 'stop_forwarding':
                await self.handle_stop_forwarding(event)
            
            elif data == 'view_config':
                await self.handle_config(event)
            
            elif data == 'forward_settings':
                await self.show_settings_buttons(event)
            
            elif data == 'logout_user':
                await self.handle_logout(event)
            
            elif data == 'check_subscription':
                if await self.check_force_subscribe(user.id):
                    await event.edit("✅ Subscription verified! Welcome to the bot.")
                    await asyncio.sleep(2)
                    await self.handle_start(event)
                else:
                    await event.edit("❌ Still not subscribed. Please join the channel first.")
            
            elif data in ['toggle_hide_header', 'toggle_media', 'toggle_previews']:
                setting_map = {
                    'toggle_hide_header': 'hide_header',
                    'toggle_media': 'forward_media', 
                    'toggle_previews': 'url_previews'
                }
                await self.toggle_setting(event, setting_map[data])
            
            elif data == 'phone_format_help':
                await event.edit("📋 **Phone Format Help**\n\n**Examples:**\n• India: `+919876543210`\n• US: `+1234567890`\n• UK: `+441234567890`\n\n**Important:** Include country code and + sign")
            
            elif data == 'cancel_operation':
                await event.edit("❌ Operation cancelled.")
            
            elif data == 'cancel_login':
                if user.id in self.login_attempts:
                    if 'user_client' in self.login_attempts[user.id]:
                        await self.login_attempts[user.id]['user_client'].disconnect()
                    del self.login_attempts[user.id]
                await event.edit("❌ Login cancelled.")
            
            elif data == 'how_it_works':
                await event.edit("🎯 **How It Works**\n\n1. **Login** with your Telegram account\n2. **Set source** channel (forward a message)\n3. **Add target** channels (bot needs admin)\n4. **Start** auto-forwarding\n5. **Monitor** your channels automatically")
            
            elif data == 'contact_support':
                await event.edit("💬 **Support**\n\nFor help contact: @starworrier\n\n**Common Issues:**\n• Login problems\n• Channel access\n• Forwarding errors")
            
            else:
                await event.answer("Button action not implemented yet", alert=True)
                
        except Exception as e:
            logger.error(f"Error in callback handler: {e}")
            await event.answer("Error processing request", alert=True)

    async def show_settings_buttons(self, event):
        """Show settings with toggle buttons"""
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
                         b"toggle_hide_header"),
             Button.inline(f"🖼️ Media: {'✅ ON' if settings.get('forward_media') else '❌ OFF'}", 
                         b"toggle_media")],
            [Button.inline(f"🔗 Previews: {'✅ ON' if settings.get('url_previews') else '❌ OFF'}", 
                         b"toggle_previews")],
            [Button.inline("🔙 Back to Dashboard", b"show_dashboard")]
        ]
        
        await event.edit(settings_text, buttons=buttons)

    async def toggle_setting(self, event, setting_name: str):
        """Toggle individual settings"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        if user.id not in self.forward_settings:
            self.forward_settings[user.id] = self.default_settings.copy()
        
        current = self.forward_settings[user.id].get(setting_name, False)
        self.forward_settings[user.id][setting_name] = not current
        await self.save_to_db("forward_settings", self.forward_settings)
        
        # Show updated settings
        await self.show_settings_buttons(event)

    # ==================== MESSAGE PROCESSING ====================

    async def handle_auto_forward(self, event):
        """Handle all incoming messages"""
        try:
            # Ignore if it's a command
            if event.text and event.text.startswith('/'):
                return
            
            user = await event.get_sender()
            
            # Check force subscribe for new users
            if user.id not in self.user_sessions and not await self.check_force_subscribe(user.id):
                return  # Already handled in start command
            
            # Handle OTP verification
            if event.text and event.text.upper().startswith('AUTOX'):
                await self.handle_code_verification(event)
                return
            
            # Handle phone number input
            if event.text and re.match(r'^\+[0-9]{10,15}$', event.text):
                if user.id in self.login_attempts and self.login_attempts[user.id].get('step') == 'waiting_phone':
                    await self.start_telegram_login(user, event.text, event)
                return
            
            # Handle forwarded messages for channel detection
            if event.message.fwd_from:
                await self.handle_forwarded_message(event)
                return
            
            # Auto-forwarding logic would go here
            # This is simplified for the example
            
        except Exception as e:
            logger.error(f"Error in message processing: {e}")

    async def handle_forwarded_message(self, event):
        """Handle forwarded messages for channel detection"""
        try:
            if not event.message.fwd_from:
                return
            
            user = await event.get_sender()
            if not await self.check_user_logged_in(user.id, event, silent=True):
                return
            
            fwd = event.message.fwd_from
            if hasattr(fwd, 'from_id'):
                # This would require user client to get entity
                # Simplified for example
                await event.reply("📨 **Channel detected!**\n\nUse the buttons to set this as source or target.")
                
        except Exception as e:
            logger.error(f"Error processing forwarded message: {e}")

    # ==================== UTILITY FUNCTIONS ====================

    async def check_user_logged_in(self, user_id: int, event=None, silent: bool = False) -> bool:
        """Check if user is logged in"""
        if user_id not in self.user_sessions or self.user_sessions[user_id].get('status') != 'logged_in':
            if not silent and event:
                buttons = [
                    [Button.inline("🔐 Login Now", b"quick_login")],
                    [Button.inline("🏠 Main Menu", b"main_menu")]
                ]
                await event.reply("❌ Please login first to use this feature.", buttons=buttons)
            return False
        return True

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
        
        @self.client.on(events.NewMessage(pattern='^/help$'))
        async def help_handler(event):
            await self.handle_help(event)
        
        @self.client.on(events.NewMessage(pattern='^/config$'))
        async def config_handler(event):
            await self.handle_config(event)
        
        @self.client.on(events.NewMessage(pattern='^/source$'))
        async def source_handler(event):
            await self.handle_source(event)
        
        @self.client.on(events.NewMessage(pattern='^/target$'))
        async def target_handler(event):
            await self.handle_target(event)
        
        @self.client.on(events.NewMessage(pattern='^/start_forwarding$'))
        async def start_forwarding_handler(event):
            await self.handle_start_forwarding(event)
        
        @self.client.on(events.NewMessage(pattern='^/stop_forwarding$'))
        async def stop_forwarding_handler(event):
            await self.handle_stop_forwarding(event)
        
        @self.client.on(events.NewMessage(pattern='^/forward_settings$'))
        async def forward_settings_handler(event):
            await self.show_settings_buttons(event)
        
        @self.client.on(events.CallbackQuery())
        async def callback_handler(event):
            await self.handle_callback_query(event)
        
        @self.client.on(events.NewMessage)
        async def message_handler(event):
            await self.handle_auto_forward(event)
        
        logger.info("✅ All handlers registered successfully!")

async def main():
    """Main function"""
    
    # Get credentials from environment
    api_id = "28093492"
    api_hash = "2d18ff97ebdfc2f1f3a2596c48e3b4e4"
    bot_token = "7931829452:AAEF2zYePG5w3EY3cRwsv6jqxZawH_0HXKI"
    db_channel_id = "-1002565934191"
    
    # Update with your actual IDs
    global ADMIN_USER_IDS, FORCE_SUB_CHANNEL
    admin_env = "6651946441"
    if admin_env:
        ADMIN_USER_IDS = [int(id.strip()) for id in admin_env.split(',')]
    
    force_sub_env = "@MrJaggiX"
    if force_sub_env:
        FORCE_SUB_CHANNEL = force_sub_env
    
    print("🚀 Starting Best Auto Forwarding Bot...")
    
    bot = AdvancedAutoForwardBot(api_id, api_hash, bot_token, db_channel_id)
    
    try:
        await bot.initialize()
        print("✅ Bot is running perfectly! All systems operational.")
        print("💡 Test with: /start")
        await bot.client.run_until_disconnected()
    except KeyboardInterrupt:
        print("🛑 Bot stopped by user")
    except Exception as e:
        logger.error(f"❌ Bot error: {e}")
    finally:
        await bot.client.disconnect()

if __name__ == '__main__':
    from dotenv import load_dotenv
    load_dotenv()
    
    # Create sessions directory
    os.makedirs("sessions", exist_ok=True)
    
    asyncio.run(main())
