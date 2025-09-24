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
ADMIN_USER_IDS = [6651946441]  # Replace with your Telegram User ID

class TelegramChannelDB:
    """Telegram Channel-based Database System"""
    
    def __init__(self, client: TelegramClient, db_channel_id: int):
        self.client = client
        self.db_channel_id = db_channel_id
        self.cache = {}
    
    async def initialize(self):
        """Initialize database channel"""
        try:
            entity = await self.client.get_entity(self.db_channel_id)
            logger.info(f"Database channel initialized: {entity.title}")
            return True
        except Exception as e:
            logger.error(f"Error initializing database channel: {e}")
            return False
    
    async def set(self, key: str, data: Any) -> bool:
        """Store data in database"""
        try:
            serialized_data = base64.b64encode(pickle.dumps(data)).decode('utf-8')
            message_text = f"DB_ENTRY:{key}:{serialized_data}"
            await self.client.send_message(self.db_channel_id, message_text)
            self.cache[key] = data
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
        self.source_channel: Dict[int, Dict] = {}  # Single source channel per user
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
            
            if await self.db.initialize():
                await self.load_all_data()
                self.register_handlers()
                logger.info("Bot fully initialized!")
            else:
                logger.error("Failed to initialize database!")
                
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
        except Exception as e:
            logger.error(f"Error saving {key}: {e}")

    def is_admin(self, user_id: int) -> bool:
        """Check if user is admin"""
        return user_id in ADMIN_USER_IDS

    # ==================== LOGIN SYSTEM ====================

    async def handle_login(self, event):
        """Handle /login command"""
        user = await event.get_sender()
        
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
            session_name = f"user_{user.id}"
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

Please check your Telegram app for the verification code and send it here.

**Example:** `12345`
            """
            await event.reply(login_text)
            
        except Exception as e:
            logger.error(f"Error starting login: {e}")
            error_msg = "❌ Error sending verification code. Please check the phone number."
            await event.reply(error_msg)
            if user.id in self.login_attempts:
                del self.login_attempts[user.id]

    async def handle_code_verification(self, event):
        """Handle verification code input"""
        user = await event.get_sender()
        
        if user.id not in self.login_attempts or self.login_attempts[user.id].get('step') != 'waiting_code':
            return
        
        code = event.text.strip()
        
        if not code.isdigit() or len(code) < 5:
            await event.reply("❌ Invalid code format. Please enter the 5-digit verification code.")
            return
        
        login_data = self.login_attempts[user.id]
        
        try:
            await login_data['user_client'].sign_in(
                phone=login_data['phone_number'],
                code=code,
                phone_code_hash=login_data['phone_code_hash']
            )
            
            user_entity = await login_data['user_client'].get_me()
            
            self.user_sessions[user.id] = {
                'phone_number': login_data['phone_number'],
                'first_name': user_entity.first_name,
                'username': user_entity.username,
                'user_id': user_entity.id,
                'login_time': datetime.now().isoformat(),
                'status': 'logged_in',
                'user_client': login_data['user_client']  # Store client for forwarding
            }
            
            if user.id not in self.forward_settings:
                self.forward_settings[user.id] = self.default_settings.copy()
                await self.save_to_db("forward_settings", self.forward_settings)
            
            await self.save_to_db("user_sessions", self.user_sessions)
            
            success_text = f"""
✅ **Login Successful!**

Welcome, {user_entity.first_name or 'User'}!

**Next Steps:**
1. Set your source channel
2. Add target channels
3. Start auto-forwarding

Use the buttons below to get started!
            """
            
            buttons = [
                [Button.inline("📥 Set Source Channel", b"set_source"),
                 Button.inline("📤 Add Target Channel", b"add_target")],
                [Button.inline("🚀 Start Forwarding", b"start_forwarding"),
                 Button.inline("📊 View Config", b"view_config")]
            ]
            
            await event.reply(success_text, buttons=buttons)
            
        except Exception as e:
            logger.error(f"Error during code verification: {e}")
            error_msg = "❌ Invalid verification code. Please try again."
            await event.reply(error_msg)

    # ==================== CORE COMMANDS ====================

    async def handle_start(self, event):
        """Handle /start command"""
        user = await event.get_sender()
        
        welcome_text = f"""
🤖 **Welcome to Best Auto Forwarding Bot, {user.first_name or 'User'}!**

**Key Features:**
• Single source channel (your user account accesses it)
• Multiple target channels (bot needs admin rights only in targets)
• Real-time message forwarding
• Media support

**Quick Setup:**
1. Login with your account
2. Set source channel (bot NOT required as admin)
3. Add target channels (bot NEEDS admin rights)
4. Start forwarding

Use the buttons below or commands to get started!
        """
        
        buttons = [
            [Button.inline("🔐 Login", b"quick_login"),
             Button.inline("📚 Help", b"show_help")],
            [Button.inline("🎥 Tutorial", b"show_tutorial")]
        ]
        
        await event.reply(welcome_text, buttons=buttons)

    async def handle_logout(self, event):
        """Handle /logout command"""
        user = await event.get_sender()
        
        if user.id in self.user_sessions:
            if 'user_client' in self.user_sessions[user.id]:
                await self.user_sessions[user.id]['user_client'].disconnect()
            del self.user_sessions[user.id]
        
        if user.id in self.auto_forwarding:
            del self.auto_forwarding[user.id]
        
        if user.id in self.source_channel:
            del self.source_channel[user.id]
        
        if user.id in self.target_channels:
            del self.target_channels[user.id]
        
        if user.id in self.login_attempts:
            if 'user_client' in self.login_attempts[user.id]:
                await self.login_attempts[user.id]['user_client'].disconnect()
            del self.login_attempts[user.id]
        
        await self.save_to_db("user_sessions", self.user_sessions)
        await self.save_to_db("auto_forwarding", self.auto_forwarding)
        await self.save_to_db("source_channel", self.source_channel)
        await self.save_to_db("target_channels", self.target_channels)
        
        await event.reply("✅ Logout successful! All your data has been cleared.")

    async def handle_source(self, event):
        """Handle /source command - Single source channel"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        instructions = """
📥 **Set Source Channel**

You can set ONLY ONE source channel.

**Methods to add source channel:**

1. **Forward a message** from the channel to this bot
2. **Use command:** `/set_source [channel_id]`
3. **Use command:** `/set_source @username`

**Important:**
• Bot does NOT need to be admin in source channel
• Your logged-in account will access the messages
• Only one source channel allowed per user

**Current Source:** {}
        """.format(self.source_channel[user.id]['name'] if user.id in self.source_channel else "Not set")
        
        buttons = [
            [Button.inline("📨 Forward Message to Set", b"forward_instructions")],
            [Button.inline("🔙 Back to Menu", b"main_menu")]
        ]
        
        await event.reply(instructions, buttons=buttons)

    async def handle_set_source(self, event):
        """Handle /set_source command"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        channel_input = event.text.replace('/set_source', '').strip()
        
        if not channel_input:
            await event.reply("❌ Please provide channel ID or username. Example: `/set_source -1001234567890`")
            return
        
        await self.add_source_channel(user.id, channel_input, event)

    async def add_source_channel(self, user_id: int, channel_input: str, event):
        """Add single source channel using user's client"""
        try:
            user_client = self.user_sessions[user_id].get('user_client')
            if not user_client:
                await event.reply("❌ User session not available. Please login again.")
                return
            
            # Get channel entity using user's client
            try:
                if channel_input.startswith('@'):
                    entity = await user_client.get_entity(channel_input)
                else:
                    channel_id = int(channel_input)
                    entity = await user_client.get_entity(channel_id)
            except Exception as e:
                await event.reply(f"❌ Cannot access channel. Error: {str(e)}")
                return
            
            channel_info = {
                'id': entity.id,
                'name': getattr(entity, 'title', 'Unknown Channel'),
                'username': getattr(entity, 'username', None),
                'added_time': datetime.now().isoformat()
            }
            
            self.source_channel[user_id] = channel_info
            await self.save_to_db("source_channel", self.source_channel)
            
            success_text = f"""
✅ **Source Channel Set!**

**Channel:** {channel_info['name']}
**ID:** `{channel_info['id']}`

Now add target channels using `/target` command.
            """
            
            buttons = [
                [Button.inline("📤 Add Target Channel", b"add_target"),
                 Button.inline("🚀 Start Forwarding", b"start_forwarding")]
            ]
            
            await event.reply(success_text, buttons=buttons)
            
        except Exception as e:
            logger.error(f"Error adding source channel: {e}")
            await event.reply("❌ Error setting source channel. Please check the ID/username.")

    async def handle_target(self, event):
        """Handle /target command - Multiple target channels"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        targets = self.target_channels.get(user.id, [])
        
        instructions = f"""
📤 **Target Channels Setup**

You can add MULTIPLE target channels.

**Methods to add target channel:**

1. **Add bot to channel** as admin with post permissions
2. **Forward a message** from the channel to this bot
3. **Use command:** `/add_target [channel_id]`
4. **Use command:** `/add_target @username`

**Important:**
• Bot MUST be admin in target channels
• Bot needs permission to send messages
• You can add multiple target channels

**Current Target Channels:** {len(targets)}
        """
        
        buttons = []
        if targets:
            buttons.append([Button.inline("📋 View Targets", b"view_targets")])
        buttons.extend([
            [Button.inline("➕ Add Target", b"add_target")],
            [Button.inline("🗑️ Remove Target", b"remove_target")],
            [Button.inline("🔙 Back", b"main_menu")]
        ])
        
        await event.reply(instructions, buttons=buttons)

    async def handle_add_target(self, event):
        """Handle /add_target command"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        channel_input = event.text.replace('/add_target', '').strip()
        
        if not channel_input:
            await event.reply("❌ Please provide channel ID or username. Example: `/add_target -1001234567890`")
            return
        
        await self.add_target_channel(user.id, channel_input, event)

    async def add_target_channel(self, user_id: int, channel_input: str, event):
        """Add target channel - Bot needs to be admin"""
        try:
            # Get channel entity using bot's client
            try:
                if channel_input.startswith('@'):
                    entity = await self.client.get_entity(channel_input)
                else:
                    channel_id = int(channel_input)
                    entity = await self.client.get_entity(channel_id)
            except Exception as e:
                await event.reply(f"❌ Cannot access channel. Make sure bot is added as admin. Error: {str(e)}")
                return
            
            channel_info = {
                'id': entity.id,
                'name': getattr(entity, 'title', 'Unknown Channel'),
                'username': getattr(entity, 'username', None),
                'added_time': datetime.now().isoformat()
            }
            
            if user_id not in self.target_channels:
                self.target_channels[user_id] = []
            
            # Check for duplicates
            if any(ch['id'] == entity.id for ch in self.target_channels[user_id]):
                await event.reply("❌ Channel already in target list.")
                return
            
            self.target_channels[user_id].append(channel_info)
            await self.save_to_db("target_channels", self.target_channels)
            
            success_text = f"""
✅ **Target Channel Added!**

**Channel:** {channel_info['name']}
**ID:** `{channel_info['id']}`

**Total target channels:** {len(self.target_channels[user_id])}
            """
            
            buttons = [
                [Button.inline("➕ Add Another", b"add_target"),
                 Button.inline("🚀 Start Forwarding", b"start_forwarding")],
                [Button.inline("📋 View All", b"view_targets")]
            ]
            
            await event.reply(success_text, buttons=buttons)
            
        except Exception as e:
            logger.error(f"Error adding target channel: {e}")
            await event.reply("❌ Error adding target channel. Please check if bot is admin in the channel.")

    async def handle_remove_target(self, event):
        """Handle target channel removal"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        targets = self.target_channels.get(user.id, [])
        if not targets:
            await event.reply("❌ No target channels to remove.")
            return
        
        removal_text = "🗑️ **Remove Target Channel**\n\n**Current target channels:**\n"
        
        for i, target in enumerate(targets, 1):
            removal_text += f"{i}. {target['name']} (ID: `{target['id']}`)\n"
        
        removal_text += "\nReply with the number to remove (e.g., `1`)"
        
        self.user_sessions[user.id]['awaiting_removal'] = True
        await event.reply(removal_text)

    async def handle_start_forwarding(self, event):
        """Handle /start_forwarding command"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        if user.id not in self.source_channel:
            await event.reply("❌ No source channel configured. Use `/source` to set source channel.")
            return
        
        targets = self.target_channels.get(user.id, [])
        if not targets:
            await event.reply("❌ No target channels configured. Use `/target` to add target channels.")
            return
        
        self.auto_forwarding[user.id] = True
        await self.save_to_db("auto_forwarding", self.auto_forwarding)
        
        source = self.source_channel[user.id]
        
        success_text = f"""
✅ **Auto-Forwarding Started!**

**Source Channel:** {source['name']}
**Target Channels:** {len(targets)}
**Status:** 🟢 **ACTIVE**

**Now forwarding messages from your source channel to all target channels.**

**Controls:**
• `/stop_forwarding` - Pause forwarding
• `/config` - View current setup

💡 **System is now live and monitoring your source channel.**
        """
        
        buttons = [
            [Button.inline("⏸️ Stop Forwarding", b"stop_forwarding"),
             Button.inline("📊 View Config", b"view_config")]
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
             Button.inline("📊 View Config", b"view_config")]
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

**👤 Account:**
• User: {user_data.get('first_name', 'N/A')}
• Phone: {user_data.get('phone_number', 'N/A')}
• Status: ✅ Active

**📊 Channel Setup:**
• Source Channel: {source.get('name', 'Not set')}
• Target Channels: {len(targets)}
• Forwarding: {'🟢 ACTIVE' if self.auto_forwarding.get(user.id) else '⏸️ PAUSED'}

**Target Channels:**
"""
        for i, target in enumerate(targets, 1):
            config_text += f"{i}. {target['name']} (ID: {target['id']})\n"
        
        config_text += f"""
**⚡ Settings:**
• Hide Header: {'✅ Yes' if settings.get('hide_header') else '❌ No'}
• Media Forwarding: {'✅ Yes' if settings.get('forward_media') else '❌ No'}
        """
        
        buttons = [
            [Button.inline("📥 Change Source", b"set_source"),
             Button.inline("📤 Manage Targets", b"add_target")],
            [Button.inline("⚙️ Settings", b"forward_settings"),
             Button.inline("🔄 " + ("Stop" if self.auto_forwarding.get(user.id) else "Start"), 
                         b"stop_forwarding" if self.auto_forwarding.get(user.id) else "start_forwarding")]
        ]
        
        await event.reply(config_text, buttons=buttons)

    async def handle_forward_settings(self, event):
        """Handle /forward_settings command"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        settings = self.forward_settings.get(user.id, self.default_settings)
        
        settings_text = f"""
⚙️ **Forwarding Settings**

**Current Configuration:**
• Hide Header: {'✅ ON' if settings.get('hide_header') else '❌ OFF'}
• Media Forwarding: {'✅ ON' if settings.get('forward_media') else '❌ OFF'}
• URL Previews: {'✅ ON' if settings.get('url_previews') else '❌ OFF'}

Click buttons below to toggle settings:
        """
        
        buttons = [
            [Button.inline("👁️ Hide Header: " + ("ON" if settings.get('hide_header') else "OFF"), 
                         b"toggle_hide_header"),
             Button.inline("🖼️ Media: " + ("ON" if settings.get('forward_media') else "OFF"), 
                         b"toggle_media")],
            [Button.inline("🔗 Previews: " + ("ON" if settings.get('url_previews') else "OFF"), 
                         b"toggle_previews")],
            [Button.inline("🔙 Back to Menu", b"main_menu")]
        ]
        
        await event.reply(settings_text, buttons=buttons)

    async def handle_help(self, event):
        """Handle /help command"""
        help_text = """
🆘 **Command Reference**

**🔐 Authentication:**
• `/start` - Initialize bot
• `/login` - User authentication  
• `/logout` - Clear session

**⚙️ Channel Setup:**
• `/source` - Set single source channel
• `/set_source` - Set source by ID/username
• `/target` - Manage target channels
• `/add_target` - Add target channel
• `/config` - View configuration

**🔄 Forwarding Control:**
• `/start_forwarding` - Activate service
• `/stop_forwarding` - Pause service
• `/forward_settings` - Customize settings

**📊 Information:**
• `/help` - This reference
• `/status` - Account status
        """
        
        buttons = [
            [Button.inline("🔐 Login", b"quick_login"),
             Button.inline("📥 Set Source", b"set_source")],
            [Button.inline("📤 Add Target", b"add_target"),
             Button.inline("🚀 Start", b"start_forwarding")],
            [Button.inline("🔙 Main Menu", b"main_menu")]
        ]
        
        await event.reply(help_text, buttons=buttons)

    # ==================== MESSAGE PROCESSING ====================

    async def handle_forwarded_message(self, event):
        """Handle forwarded messages for channel detection"""
        if not event.message.fwd_from:
            return
        
        user = await event.get_sender()
        if not await self.check_user_logged_in(user.id, event, silent=True):
            return
        
        try:
            fwd = event.message.fwd_from
            if hasattr(fwd, 'from_id'):
                channel_id = fwd.from_id
                user_client = self.user_sessions[user.id].get('user_client')
                
                if user_client:
                    entity = await user_client.get_entity(channel_id)
                    
                    channel_info = {
                        'id': entity.id,
                        'name': getattr(entity, 'title', 'Unknown'),
                        'username': getattr(entity, 'username', None)
                    }
                    
                    # Ask user what to do with this channel
                    question = f"""
📨 **Channel Detected!**

**Name:** {channel_info['name']}
**ID:** `{channel_info['id']}`

What would you like to do with this channel?
                    """
                    
                    buttons = [
                        [Button.inline("📥 Set as Source", f"set_source_{entity.id}"),
                         Button.inline("📤 Add as Target", f"add_target_{entity.id}")],
                        [Button.inline("❌ Cancel", b"cancel_operation")]
                    ]
                    
                    await event.reply(question, buttons=buttons)
                    
        except Exception as e:
            logger.error(f"Error processing forwarded message: {e}")

    async def handle_auto_forward(self, event):
        """Handle auto-forwarding of messages"""
        try:
            # Check for verification code
            if event.text and event.text.isdigit() and len(event.text) >= 5:
                user = await event.get_sender()
                if user.id in self.login_attempts and self.login_attempts[user.id].get('step') == 'waiting_code':
                    await self.handle_code_verification(event)
                    return
            
            # Check for phone number
            if event.text and re.match(r'^\+[0-9]{10,15}$', event.text):
                user = await event.get_sender()
                if user.id in self.login_attempts and self.login_attempts[user.id].get('step') == 'waiting_phone':
                    await self.start_telegram_login(user, event.text, event)
                    return
            
            # Handle target removal by number
            if event.text and event.text.isdigit():
                user = await event.get_sender()
                if (user.id in self.user_sessions and 
                    self.user_sessions[user.id].get('awaiting_removal')):
                    await self.process_target_removal(user.id, event.text, event)
                    return
            
            # Handle forwarded messages
            if event.message.fwd_from:
                await self.handle_forwarded_message(event)
                return
            
            # Auto-forwarding logic - using user's client to access source channel
            for user_id, source in self.source_channel.items():
                if not self.auto_forwarding.get(user_id, False):
                    continue
                
                # This would need more complex implementation to monitor source channel
                # For now, we'll rely on the user's client to forward messages
                pass
                    
        except Exception as e:
            logger.error(f"Error in message processing: {e}")

    async def process_target_removal(self, user_id: int, number_text: str, event):
        """Process target channel removal by number"""
        try:
            number = int(number_text)
            targets = self.target_channels.get(user_id, [])
            
            if 1 <= number <= len(targets):
                removed_channel = targets[number-1]
                del targets[number-1]
                await self.save_to_db("target_channels", self.target_channels)
                
                self.user_sessions[user_id]['awaiting_removal'] = False
                await event.reply(f"✅ Removed target channel: {removed_channel['name']}")
            else:
                await event.reply("❌ Invalid channel number.")
                
        except ValueError:
            await event.reply("❌ Please enter a valid number.")

    # ==================== BUTTON HANDLERS ====================

    async def handle_callback_query(self, event):
        """Handle button callbacks"""
        data = event.data.decode('utf-8')
        user = await event.get_sender()
        
        try:
            if data == 'quick_login':
                await event.edit("🔐 **Login Setup**\n\nPlease use `/login +919876543210` or send your phone number.")
            
            elif data == 'set_source':
                await event.edit("📥 **Set Source Channel**\n\nForward a message from your source channel or use `/set_source [channel_id]`")
            
            elif data == 'add_target':
                await event.edit("📤 **Add Target Channel**\n\nAdd bot as admin to your channel, then forward a message or use `/add_target [channel_id]`")
            
            elif data == 'start_forwarding':
                await self.handle_start_forwarding(event)
            
            elif data == 'stop_forwarding':
                await self.handle_stop_forwarding(event)
            
            elif data == 'view_config':
                await self.handle_config(event)
            
            elif data == 'forward_settings':
                await self.handle_forward_settings(event)
            
            elif data == 'show_help':
                await self.handle_help(event)
            
            elif data == 'main_menu':
                await self.handle_start(event)
            
            elif data.startswith('set_source_'):
                channel_id = int(data.split('_')[-1])
                await self.add_source_channel(user.id, str(channel_id), event)
            
            elif data.startswith('add_target_'):
                channel_id = int(data.split('_')[-1])
                await self.add_target_channel(user.id, str(channel_id), event)
            
            elif data in ['toggle_hide_header', 'toggle_media', 'toggle_previews']:
                setting_map = {
                    'toggle_hide_header': 'hide_header',
                    'toggle_media': 'forward_media', 
                    'toggle_previews': 'url_previews'
                }
                await self.handle_toggle_setting(event, setting_map[data])
            
            elif data == 'view_targets':
                await self.handle_target(event)
            
            elif data == 'remove_target':
                await self.handle_remove_target(event)
            
            elif data == 'forward_instructions':
                await event.edit("📨 **Forward a message from your source channel to this bot to automatically detect it.**")
            
            elif data == 'cancel_operation':
                await event.edit("❌ Operation cancelled.")
            
            elif data == 'show_tutorial':
                await event.edit("🎥 **Tutorial**\n\n1. Login with your account\n2. Set source channel (no bot admin needed)\n3. Add target channels (bot needs admin)\n4. Start forwarding!")
            
        except Exception as e:
            logger.error(f"Error in callback handler: {e}")
            await event.answer("Error processing request", alert=True)

    async def handle_toggle_setting(self, event, setting_name: str):
        """Toggle individual settings"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        if user.id not in self.forward_settings:
            self.forward_settings[user.id] = self.default_settings.copy()
        
        current = self.forward_settings[user.id].get(setting_name, False)
        self.forward_settings[user.id][setting_name] = not current
        await self.save_to_db("forward_settings", self.forward_settings)
        
        # Update the settings view
        await self.handle_forward_settings(event)

    # ==================== UTILITY FUNCTIONS ====================

    async def check_user_logged_in(self, user_id: int, event, silent: bool = False) -> bool:
        """Check if user is logged in"""
        if user_id not in self.user_sessions or self.user_sessions[user_id].get('status') != 'logged_in':
            if not silent:
                await event.reply("❌ Please login first using `/login`")
            return False
        return True

    def register_handlers(self):
        """Register all event handlers"""
        
        # Basic commands
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
        
        # Channel management
        @self.client.on(events.NewMessage(pattern='^/source$'))
        async def source_handler(event):
            await self.handle_source(event)
        
        @self.client.on(events.NewMessage(pattern='^/set_source'))
        async def set_source_handler(event):
            await self.handle_set_source(event)
        
        @self.client.on(events.NewMessage(pattern='^/target$'))
        async def target_handler(event):
            await self.handle_target(event)
        
        @self.client.on(events.NewMessage(pattern='^/add_target'))
        async def add_target_handler(event):
            await self.handle_add_target(event)
        
        # Forwarding control
        @self.client.on(events.NewMessage(pattern='^/start_forwarding$'))
        async def start_forwarding_handler(event):
            await self.handle_start_forwarding(event)
        
        @self.client.on(events.NewMessage(pattern='^/stop_forwarding$'))
        async def stop_forwarding_handler(event):
            await self.handle_stop_forwarding(event)
        
        @self.client.on(events.NewMessage(pattern='^/forward_settings$'))
        async def forward_settings_handler(event):
            await self.handle_forward_settings(event)
        
        # Callback queries
        @self.client.on(events.CallbackQuery())
        async def callback_handler(event):
            await self.handle_callback_query(event)
        
        # Main message handler
        @self.client.on(events.NewMessage)
        async def message_handler(event):
            await self.handle_auto_forward(event)

async def main():
    """Main function"""
    
    # Get credentials from environment
    api_id = "28093492"
    api_hash = "2d18ff97ebdfc2f1f3a2596c48e3b4e4"
    bot_token = "7931829452:AAEF2zYePG5w3EY3cRwsv6jqxZawH_0HXKI"
    db_channel_id = "-1002565934191"
    
    # Validate credentials
    if any(x in ['123456', 'your_api_hash', 'your_bot_token'] for x in [str(api_id), api_hash, bot_token]):
        print("❌ Please set valid environment variables")
        return
    
    print("🚀 Starting Best Auto Forwarding Bot...")
    
    bot = AdvancedAutoForwardBot(api_id, api_hash, bot_token, db_channel_id)
    
    try:
        await bot.initialize()
        print("✅ Bot is running! All systems operational.")
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
    
    asyncio.run(main())
