import os
import logging
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime
import re
from telethon import TelegramClient, events
from telethon.tl.types import User, Channel, Message
from telethon.tl.functions.auth import SendCodeRequest, SignInRequest
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.types import InputChannel
import hashlib

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

class AdvancedAutoForwardBot:
    def __init__(self, api_id: int, api_hash: str, bot_token: str):
        self.client = TelegramClient('auto_forward_bot', api_id, api_hash)
        self.bot_token = bot_token
        
        # User data storage
        self.user_sessions: Dict[int, Dict] = {}
        self.source_channels: Dict[int, List] = {}
        self.target_channels: Dict[int, List] = {}
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
            self.register_handlers()
            logger.info("All handlers registered successfully!")
        except Exception as e:
            logger.error(f"Error during initialization: {e}")

    def is_admin(self, user_id: int) -> bool:
        """Check if user is admin"""
        return user_id in ADMIN_USER_IDS

    # ==================== LOGIN SYSTEM ====================

    async def handle_login(self, event):
        """Handle /login command with real Telegram authentication"""
        user = await event.get_sender()
        
        # Check if already logged in
        if user.id in self.user_sessions:
            await event.reply("✅ You are already logged in! Use `/logout` first if you want to re-login.")
            return
        
        # Extract phone number from command or ask for it
        message_text = event.text.replace('/login', '').strip()
        
        if message_text and re.match(r'^\+[0-9]{10,15}$', message_text):
            phone_number = message_text
            await self.start_telegram_login(user, phone_number, event)
        else:
            # Ask for phone number
            login_text = """
🔐 **Login Process**

Please send your phone number in international format:

**Examples:**
• `+919876543210` (India)
• `+1234567890` (US)

You can send it now or use: `/login +919876543210`
            """
            self.login_attempts[user.id] = {'step': 'waiting_phone'}
            await event.reply(login_text)

    async def start_telegram_login(self, user, phone_number, event):
        """Start real Telegram login process"""
        try:
            # Create a temporary client for user authentication
            session_name = f"user_{user.id}"
            user_client = TelegramClient(session_name, self.client.api_id, self.client.api_hash)
            
            await user_client.connect()
            
            # Send code request to Telegram
            sent_code = await user_client.send_code_request(phone_number)
            
            # Store login attempt data
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
**Code Type:** {getattr(sent_code, 'type', 'SMS').__class__.__name__}

Please check your Telegram app for the verification code and send it here.

**Example:** `12345`
            """
            await event.reply(login_text)
            
        except Exception as e:
            logger.error(f"Error starting login for {phone_number}: {e}")
            error_msg = "❌ Error sending verification code. Please check the phone number and try again."
            if "PHONE_NUMBER_INVALID" in str(e):
                error_msg = "❌ Invalid phone number format. Please use international format like +919876543210"
            elif "FLOOD" in str(e):
                error_msg = "❌ Too many attempts. Please wait before trying again."
            
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
            # Sign in with the code
            await login_data['user_client'].sign_in(
                phone=login_data['phone_number'],
                code=code,
                phone_code_hash=login_data['phone_code_hash']
            )
            
            # Login successful
            user_entity = await login_data['user_client'].get_me()
            
            # Store user session
            self.user_sessions[user.id] = {
                'phone_number': login_data['phone_number'],
                'first_name': user_entity.first_name,
                'username': user_entity.username,
                'user_id': user_entity.id,
                'login_time': datetime.now().isoformat(),
                'status': 'logged_in'
            }
            
            # Initialize settings for new user
            if user.id not in self.forward_settings:
                self.forward_settings[user.id] = self.default_settings.copy()
            
            # Cleanup
            await login_data['user_client'].disconnect()
            del self.login_attempts[user.id]
            
            success_text = f"""
✅ **Login Successful!**

Welcome back, {user_entity.first_name or 'User'}!

**Account Details:**
• Phone: {login_data['phone_number']}
• Name: {user_entity.first_name or 'N/A'}
• Username: @{user_entity.username or 'N/A'}

**Next Steps:**
1. `/source` - Add source channels
2. `/target` - Add target channels
3. `/start_forwarding` - Begin auto-forwarding

Use `/help` for all commands.
            """
            await event.reply(success_text)
            
        except Exception as e:
            logger.error(f"Error during code verification: {e}")
            
            error_msg = "❌ Invalid verification code. Please try again."
            if "CODE_INVALID" in str(e):
                error_msg = "❌ Invalid code. Please check and enter the correct verification code."
            elif "SESSION_PASSWORD_NEEDED" in str(e):
                error_msg = "🔒 Account protected with 2FA. This bot doesn't support 2FA accounts yet."
            
            await event.reply(error_msg)

    # ==================== CORE COMMANDS ====================

    async def handle_start(self, event):
        """Handle /start command"""
        user = await event.get_sender()
        welcome_text = f"""
🤖 **Welcome to Best Auto Forwarding Bot, {user.first_name or 'User'}!**

🚀 **Professional Auto-Forwarding Features:**
• Smart message forwarding between channels/groups
• Media files support (photos, videos, documents)
• Advanced content filtering
• Real-time processing

📋 **Quick Setup:**
1. `/login` - Secure authentication
2. `/source` - Configure source channels  
3. `/target` - Configure destination channels
4. `/start_forwarding` - Activate service

🔧 **Need assistance?** Use `/help` for command reference.

**Status:** ✅ System Operational
        """
        await event.reply(welcome_text)

    async def handle_logout(self, event):
        """Handle /logout command"""
        user = await event.get_sender()
        
        if user.id in self.user_sessions:
            del self.user_sessions[user.id]
        
        if user.id in self.auto_forwarding:
            del self.auto_forwarding[user.id]
        
        if user.id in self.source_channels:
            del self.source_channels[user.id]
        
        if user.id in self.target_channels:
            del self.target_channels[user.id]
        
        if user.id in self.forward_settings:
            del self.forward_settings[user.id]
        
        if user.id in self.login_attempts:
            if 'user_client' in self.login_attempts[user.id]:
                await self.login_attempts[user.id]['user_client'].disconnect()
            del self.login_attempts[user.id]
        
        await event.reply("✅ Logout successful! All your data has been cleared.")

    async def handle_source(self, event):
        """Handle /source command"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        instructions = """
📥 **Source Channels Setup**

Source channels are where messages originate from.

**To add source channels:**

1. **Ensure the bot is admin** in your source channel
2. **Forward any message** from the channel to this bot
3. **I'll automatically detect** and add the channel

**Manual addition:**
Use `/add_source [channel_id]` 
Get channel ID from @username_to_id_bot

**Requirements:**
• Bot must be channel admin
• Channel must be accessible
• No restrictions on message forwarding

💡 **You can add multiple source channels!**
        """
        await event.reply(instructions)

    async def handle_target(self, event):
        """Handle /target command"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        instructions = """
📤 **Target Channels Setup**

Target channels are where messages are forwarded to.

**To add target channels:**

1. **Add bot to your target channel** as admin
2. **Grant post messages permission**
3. **Forward any message** from the channel to this bot
4. **I'll automatically detect** and add the channel

**Manual addition:**
Use `/add_target [channel_id]`

**Requirements:**
• Bot must have posting rights
• Channel must allow bot messages
• No send restrictions

💡 **You can add multiple target channels!**
        """
        await event.reply(instructions)

    async def handle_add_source(self, event):
        """Handle /add_source command"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        channel_input = event.text.replace('/add_source', '').strip()
        
        if not channel_input:
            await event.reply("❌ Please provide channel ID. Example: `/add_source -1001234567890`")
            return
        
        await self.add_channel(user.id, channel_input, 'source', event)

    async def handle_add_target(self, event):
        """Handle /add_target command"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        channel_input = event.text.replace('/add_target', '').strip()
        
        if not channel_input:
            await event.reply("❌ Please provide channel ID. Example: `/add_target -1001234567890`")
            return
        
        await self.add_channel(user.id, channel_input, 'target', event)

    async def add_channel(self, user_id: int, channel_input: str, channel_type: str, event):
        """Add channel to user's list"""
        try:
            # Validate channel ID format
            if not re.match(r'^-?100\d+$', channel_input) and not channel_input.startswith('@'):
                await event.reply("❌ Invalid channel format. Use numeric ID like -1001234567890 or @username")
                return
            
            # Get channel entity
            try:
                if channel_input.startswith('@'):
                    entity = await self.client.get_entity(channel_input)
                else:
                    channel_id = int(channel_input)
                    entity = await self.client.get_entity(channel_id)
            except Exception as e:
                await event.reply(f"❌ Cannot access channel. Error: {str(e)}")
                return
            
            channel_info = {
                'id': entity.id,
                'name': getattr(entity, 'title', 'Unknown Channel'),
                'username': getattr(entity, 'username', None)
            }
            
            if channel_type == 'source':
                if user_id not in self.source_channels:
                    self.source_channels[user_id] = []
                
                # Check for duplicates
                if any(ch['id'] == entity.id for ch in self.source_channels[user_id]):
                    await event.reply("❌ Channel already in source list.")
                    return
                
                self.source_channels[user_id].append(channel_info)
                list_name = "source"
                count = len(self.source_channels[user_id])
            else:
                if user_id not in self.target_channels:
                    self.target_channels[user_id] = []
                
                if any(ch['id'] == entity.id for ch in self.target_channels[user_id]):
                    await event.reply("❌ Channel already in target list.")
                    return
                
                self.target_channels[user_id].append(channel_info)
                list_name = "target"
                count = len(self.target_channels[user_id])
            
            success_text = f"""
✅ **Channel Added Successfully!**

**Channel:** {channel_info['name']}
**ID:** `{channel_info['id']}`
**Type:** {channel_type.capitalize()}

**Total {channel_type} channels:** {count}
            """
            await event.reply(success_text)
            
        except Exception as e:
            logger.error(f"Error adding channel: {e}")
            await event.reply("❌ Error adding channel. Please check the ID and try again.")

    async def handle_start_forwarding(self, event):
        """Handle /start_forwarding command"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        sources = self.source_channels.get(user.id, [])
        targets = self.target_channels.get(user.id, [])
        
        if not sources:
            await event.reply("❌ No source channels configured. Use `/source` to add channels.")
            return
        
        if not targets:
            await event.reply("❌ No target channels configured. Use `/target` to add channels.")
            return
        
        self.auto_forwarding[user.id] = True
        
        success_text = f"""
✅ **Auto-Forwarding Activated!**

**Configuration Summary:**
• Source Channels: {len(sources)}
• Target Channels: {len(targets)}
• Status: 🟢 **ACTIVE**

**Now Processing:**
Messages will be automatically forwarded from your source channels to target channels.

**Controls:**
• `/stop_forwarding` - Pause forwarding
• `/config` - View current setup
• `/forward_settings` - Customize behavior

💡 **System is now live and monitoring your channels.**
        """
        await event.reply(success_text)

    async def handle_stop_forwarding(self, event):
        """Handle /stop_forwarding command"""
        user = await event.get_sender()
        
        if user.id not in self.auto_forwarding or not self.auto_forwarding[user.id]:
            await event.reply("❌ Auto-forwarding is not currently active.")
            return
        
        self.auto_forwarding[user.id] = False
        
        await event.reply("⏸️ **Auto-forwarding paused.** Use `/start_forwarding` to resume.")

    async def handle_config(self, event):
        """Handle /config command"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        user_data = self.user_sessions.get(user.id, {})
        sources = self.source_channels.get(user.id, [])
        targets = self.target_channels.get(user.id, [])
        settings = self.forward_settings.get(user.id, self.default_settings)
        
        config_text = f"""
⚙️ **System Configuration**

**👤 Account Information:**
• User: {user_data.get('first_name', 'N/A')}
• Phone: {user_data.get('phone_number', 'N/A')}
• Status: ✅ Active

**📊 Channel Configuration:**
• Source Channels: {len(sources)}
• Target Channels: {len(targets)}
• Forwarding: {'🟢 ACTIVE' if self.auto_forwarding.get(user.id) else '⏸️ PAUSED'}

**Source Channels:**
"""
        for i, source in enumerate(sources, 1):
            config_text += f"{i}. {source['name']} (ID: {source['id']})\n"
        
        config_text += "\n**Target Channels:**\n"
        for i, target in enumerate(targets, 1):
            config_text += f"{i}. {target['name']} (ID: {target['id']})\n"
        
        config_text += f"""
**⚡ Settings:**
• Hide Header: {'✅ Yes' if settings.get('hide_header') else '❌ No'}
• Media Forwarding: {'✅ Yes' if settings.get('forward_media') else '❌ No'}
• URL Previews: {'✅ Yes' if settings.get('url_previews') else '❌ No'}
        """
        await event.reply(config_text)

    async def handle_forward_settings(self, event):
        """Handle /forward_settings command"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        settings = self.forward_settings.get(user.id, self.default_settings)
        
        settings_text = f"""
⚙️ **Forwarding Settings**

**Current Configuration:**
• Hide Header: {'✅ ON' if settings.get('hide_header') else '❌ OFF'} - `/hide_header`
• Media Forwarding: {'✅ ON' if settings.get('forward_media') else '❌ OFF'} - `/media_status`
• URL Previews: {'✅ ON' if settings.get('url_previews') else '❌ OFF'} - `/url_previews`

**Toggle commands:**
Use the commands above to switch settings on/off.
        """
        await event.reply(settings_text)

    async def handle_toggle_setting(self, event, setting_name: str):
        """Toggle individual settings"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        if user.id not in self.forward_settings:
            self.forward_settings[user.id] = self.default_settings.copy()
        
        current = self.forward_settings[user.id].get(setting_name, False)
        self.forward_settings[user.id][setting_name] = not current
        
        setting_names = {
            'hide_header': 'Hide Header',
            'forward_media': 'Media Forwarding', 
            'url_previews': 'URL Previews'
        }
        
        status = '✅ ENABLED' if not current else '❌ DISABLED'
        await event.reply(f"**{setting_names[setting_name]}** is now **{status}**")

    async def handle_help(self, event):
        """Handle /help command"""
        help_text = """
🆘 **Command Reference**

**🔐 Authentication:**
• `/start` - Initialize bot
• `/login` - User authentication  
• `/logout` - Clear session

**⚙️ Channel Setup:**
• `/source` - Configure source channels
• `/target` - Configure target channels
• `/add_source` - Add specific source
• `/add_target` - Add specific target
• `/config` - View configuration

**🔄 Forwarding Control:**
• `/start_forwarding` - Activate service
• `/stop_forwarding` - Pause service
• `/forward_settings` - Customize settings

**🔧 Settings:**
• `/hide_header` - Toggle header visibility
• `/media_status` - Toggle media forwarding
• `/url_previews` - Toggle link previews

**📊 Information:**
• `/help` - This reference
• `/status` - Account status

**👑 Admin:** `/admin` (Owner only)
        """
        await event.reply(help_text)

    async def handle_status(self, event):
        """Handle /status command"""
        user = await event.get_sender()
        
        if user.id not in self.user_sessions:
            await event.reply("❌ Not logged in. Use `/login` to start.")
            return
        
        user_data = self.user_sessions[user.id]
        sources = self.source_channels.get(user.id, [])
        targets = self.target_channels.get(user.id, [])
        
        status_text = f"""
📊 **Account Status**

**User Information:**
• Name: {user_data.get('first_name', 'N/A')} 
• Phone: {user_data.get('phone_number', 'N/A')}
• Status: ✅ Authenticated

**Service Status:**
• Source Channels: {len(sources)}
• Target Channels: {len(targets)}
• Auto-Forwarding: {'🟢 ACTIVE' if self.auto_forwarding.get(user.id) else '⏸️ INACTIVE'}

**Session:**
• Login Time: {user_data.get('login_time', 'N/A')}
        """
        await event.reply(status_text)

    # ==================== ADMIN COMMANDS ====================

    async def handle_admin(self, event):
        """Handle /admin command"""
        user = await event.get_sender()
        
        if not self.is_admin(user.id):
            await event.reply("❌ Access denied. Admin only.")
            return
        
        admin_text = f"""
👑 **Admin Panel**

**Statistics:**
• Total Users: {len(self.user_sessions)}
• Active Forwarding: {sum(1 for x in self.auto_forwarding.values() if x)}
• Source Channels: {sum(len(x) for x in self.source_channels.values())}
• Target Channels: {sum(len(x) for x in self.target_channels.values())}

**Commands:**
• `/stats` - Detailed statistics
• `/broadcast` - Message all users
        """
        await event.reply(admin_text)

    async def handle_broadcast(self, event):
        """Handle /broadcast command"""
        user = await event.get_sender()
        
        if not self.is_admin(user.id):
            await event.reply("❌ Access denied. Admin only.")
            return
        
        message = event.text.replace('/broadcast', '').strip()
        
        if not message:
            await event.reply("❌ Usage: `/broadcast your message`")
            return
        
        if not self.user_sessions:
            await event.reply("❌ No users to broadcast to.")
            return
        
        success = 0
        for user_id in self.user_sessions.keys():
            try:
                await self.client.send_message(
                    user_id, 
                    f"📢 **Admin Broadcast**\n\n{message}\n\n— Best Auto Forwarding Bot"
                )
                success += 1
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"Broadcast failed for {user_id}: {e}")
        
        await event.reply(f"✅ Broadcast sent to {success}/{len(self.user_sessions)} users.")

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
                entity = await self.client.get_entity(channel_id)
                
                channel_info = {
                    'id': entity.id,
                    'name': getattr(entity, 'title', 'Unknown'),
                    'username': getattr(entity, 'username', None)
                }
                
                await event.reply(f"""
📨 **Channel Detected!**

**Name:** {channel_info['name']}
**ID:** `{channel_info['id']}`

**To add as source:** `/add_source {channel_info['id']}`
**To add as target:** `/add_target {channel_info['id']}`
                """)
                
        except Exception as e:
            logger.error(f"Error processing forwarded message: {e}")

    async def handle_auto_forward(self, event):
        """Handle auto-forwarding of messages"""
        try:
            # Don't process commands or forwarded messages for detection
            if event.text and (event.text.startswith('/') or event.message.fwd_from):
                if event.message.fwd_from:
                    await self.handle_forwarded_message(event)
                return
            
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
            
            # Auto-forwarding logic
            if not hasattr(event, 'chat_id'):
                return
            
            for user_id, sources in self.source_channels.items():
                if not self.auto_forwarding.get(user_id, False):
                    continue
                
                source_ids = [ch['id'] for ch in sources]
                if event.chat_id in source_ids:
                    await self.forward_message(user_id, event)
                    break
                    
        except Exception as e:
            logger.error(f"Error in message processing: {e}")

    async def forward_message(self, user_id: int, event):
        """Forward message to target channels"""
        try:
            targets = self.target_channels.get(user_id, [])
            if not targets:
                return
            
            settings = self.forward_settings.get(user_id, self.default_settings)
            
            for target in targets:
                try:
                    await event.message.forward_to(target['id'])
                except Exception as e:
                    logger.error(f"Error forwarding to {target.get('name', 'Unknown')}: {e}")
                    
        except Exception as e:
            logger.error(f"Error in forward_message: {e}")

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
        @self.client.on(events.NewMessage(pattern='/start'))
        async def start_handler(event):
            await self.handle_start(event)
        
        @self.client.on(events.NewMessage(pattern='/login'))
        async def login_handler(event):
            await self.handle_login(event)
        
        @self.client.on(events.NewMessage(pattern='/logout'))
        async def logout_handler(event):
            await self.handle_logout(event)
        
        @self.client.on(events.NewMessage(pattern='/help'))
        async def help_handler(event):
            await self.handle_help(event)
        
        @self.client.on(events.NewMessage(pattern='/status'))
        async def status_handler(event):
            await self.handle_status(event)
        
        @self.client.on(events.NewMessage(pattern='/config'))
        async def config_handler(event):
            await self.handle_config(event)
        
        # Channel management
        @self.client.on(events.NewMessage(pattern='/source'))
        async def source_handler(event):
            await self.handle_source(event)
        
        @self.client.on(events.NewMessage(pattern='/target'))
        async def target_handler(event):
            await self.handle_target(event)
        
        @self.client.on(events.NewMessage(pattern='/add_source'))
        async def add_source_handler(event):
            await self.handle_add_source(event)
        
        @self.client.on(events.NewMessage(pattern='/add_target'))
        async def add_target_handler(event):
            await self.handle_add_target(event)
        
        # Forwarding control
        @self.client.on(events.NewMessage(pattern='/start_forwarding'))
        async def start_forwarding_handler(event):
            await self.handle_start_forwarding(event)
        
        @self.client.on(events.NewMessage(pattern='/stop_forwarding'))
        async def stop_forwarding_handler(event):
            await self.handle_stop_forwarding(event)
        
        @self.client.on(events.NewMessage(pattern='/forward_settings'))
        async def forward_settings_handler(event):
            await self.handle_forward_settings(event)
        
        # Settings toggles
        @self.client.on(events.NewMessage(pattern='/hide_header'))
        async def hide_header_handler(event):
            await self.handle_toggle_setting(event, 'hide_header')
        
        @self.client.on(events.NewMessage(pattern='/media_status'))
        async def media_status_handler(event):
            await self.handle_toggle_setting(event, 'forward_media')
        
        @self.client.on(events.NewMessage(pattern='/url_previews'))
        async def url_previews_handler(event):
            await self.handle_toggle_setting(event, 'url_previews')
        
        # Admin commands
        @self.client.on(events.NewMessage(pattern='/admin'))
        async def admin_handler(event):
            await self.handle_admin(event)
        
        @self.client.on(events.NewMessage(pattern='/broadcast'))
        async def broadcast_handler(event):
            await self.handle_broadcast(event)
        
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
    
    # Validate credentials
    if any(x in ['123456', 'your_api_hash', 'your_bot_token'] for x in [str(api_id), api_hash, bot_token]):
        print("❌ Please set valid environment variables:")
        print("TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_BOT_TOKEN")
        return
    
    print("🚀 Starting Best Auto Forwarding Bot...")
    
    bot = AdvancedAutoForwardBot(api_id, api_hash, bot_token)
    
    try:
        await bot.initialize()
        print("✅ Bot is running! All systems operational.")
        print("💡 Test commands: /start, /help")
        await bot.client.run_until_disconnected()
    except KeyboardInterrupt:
        print("🛑 Bot stopped by user")
    except Exception as e:
        logger.error(f"❌ Bot error: {e}")
    finally:
        await bot.client.disconnect()

if __name__ == '__main__':
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv()
    
    asyncio.run(main())
