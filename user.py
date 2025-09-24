import os
import logging
import asyncio
from typing import Dict, List, Set, Optional, Any
from datetime import datetime
import json
import pickle
import base64
import re
from telethon import TelegramClient, events, types
from telethon.tl.functions.channels import GetChannelsRequest, JoinChannelRequest
from telethon.tl.functions.messages import GetHistoryRequest, ImportChatInviteRequest
from telethon.tl.types import Channel, InputChannel, Message, User

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

# Replace with your actual Telegram User ID
ADMIN_USER_IDS = [123456789]  # YOUR_USER_ID_HERE

class TelegramChannelDB:
    """Telegram Channel-based Database System"""
    
    def __init__(self, client: TelegramClient, db_channel_id: int):
        self.client = client
        self.db_channel_id = db_channel_id
        self.cache = {}
        self.message_ids = {}
    
    async def initialize(self):
        """Initialize database channel"""
        try:
            # Convert to integer if it's a string
            if isinstance(self.db_channel_id, str):
                self.db_channel_id = int(self.db_channel_id)
            
            entity = await self.client.get_entity(self.db_channel_id)
            logger.info(f"Database channel initialized: {entity.title}")
            return True
        except Exception as e:
            logger.error(f"Error initializing database channel: {e}")
            # Create the channel if it doesn't exist
            try:
                result = await self.client.create_channel("BestAutoForwardDB", "Database channel for bot")
                self.db_channel_id = result.id
                logger.info(f"Created new database channel: {self.db_channel_id}")
                return True
            except Exception as create_error:
                logger.error(f"Failed to create database channel: {create_error}")
                return False
    
    async def _send_db_message(self, key: str, data: Any) -> int:
        """Store data as a message in the channel"""
        try:
            serialized_data = base64.b64encode(pickle.dumps(data)).decode('utf-8')
            message_text = f"DB_ENTRY:{key}:{serialized_data}"
            message = await self.client.send_message(self.db_channel_id, message_text)
            self.message_ids[key] = message.id
            self.cache[key] = data
            return message.id
        except Exception as e:
            logger.error(f"Error sending DB message: {e}")
            raise
    
    async def set(self, key: str, data: Any) -> bool:
        """Store data in database"""
        try:
            await self._send_db_message(key, data)
            return True
        except Exception as e:
            logger.error(f"Error setting data for key {key}: {e}")
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
                    self.message_ids[key] = message.id
                    return data
            
            return None
        except Exception as e:
            logger.error(f"Error getting data for key {key}: {e}")
            return None
    
    async def get_all_keys(self) -> List[str]:
        """Get all keys in database"""
        try:
            keys = []
            async for message in self.client.iter_messages(self.db_channel_id):
                if message.text and message.text.startswith("DB_ENTRY:"):
                    key = message.text.split(':', 2)[1]
                    keys.append(key)
            return list(set(keys))
        except Exception as e:
            logger.error(f"Error getting all keys: {e}")
            return []

class AdvancedAutoForwardBot:
    def __init__(self, api_id: int, api_hash: str, bot_token: str, db_channel_id: int):
        self.client = TelegramClient('auto_forward_bot', api_id, api_hash)
        self.bot_token = bot_token
        self.db = TelegramChannelDB(self.client, db_channel_id)
        
        # User data storage
        self.user_sessions: Dict[int, Dict] = {}
        self.source_channels: Dict[int, List] = {}
        self.target_channels: Dict[int, List] = {}
        self.forward_settings: Dict[int, Dict] = {}
        self.auto_forwarding: Dict[int, bool] = {}
        self.user_phone_numbers: Dict[int, str] = {}
        self.user_pinned_chats: Dict[int, List] = {}
        self.waiting_for_otp: Dict[int, bool] = {}
        self.waiting_for_phone: Dict[int, bool] = {}
        
        # Default settings for new users
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
                logger.info("Bot fully initialized with all handlers!")
            else:
                logger.error("Failed to initialize database!")
                
        except Exception as e:
            logger.error(f"Error during initialization: {e}")

    async def load_all_data(self):
        """Load all data from database"""
        try:
            self.user_sessions = await self.db.get("user_sessions") or {}
            self.source_channels = await self.db.get("source_channels") or {}
            self.target_channels = await self.db.get("target_channels") or {}
            self.forward_settings = await self.db.get("forward_settings") or {}
            self.auto_forwarding = await self.db.get("auto_forwarding") or {}
            self.user_phone_numbers = await self.db.get("user_phone_numbers") or {}
            self.user_pinned_chats = await self.db.get("user_pinned_chats") or {}
            
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

    # ==================== CORE COMMAND HANDLERS ====================

    async def handle_start(self, event):
        """Handle /start command"""
        user = await event.get_sender()
        welcome_text = f"""
🤖 **Welcome to Best Auto Forwarding Bot, {user.first_name or 'User'}!**

🚀 **Features:**
• Auto-forward messages between channels/groups
• Media forwarding support  
• Advanced filtering options
• Easy setup process

📚 **Quick Start:**
1. `/login` - Login to your account
2. `/source` - Set source channels
3. `/target` - Set target channels  
4. `/start_forwarding` - Begin auto-forwarding

🔧 **Need help?** Use `/help` for all commands.

**Status:** ✅ Bot is running perfectly!
        """
        await event.reply(welcome_text)

    async def handle_login(self, event):
        """Handle /login command - FIXED"""
        user = await event.get_sender()
        
        # Check if already logged in
        if user.id in self.user_sessions and self.user_sessions[user.id].get('status') == 'logged_in':
            await event.reply("✅ You are already logged in! Use `/logout` if you want to re-login.")
            return
        
        # Check if phone number provided with command
        message_text = event.text.replace('/login', '').strip()
        
        if message_text and re.match(r'^\+[0-9]{10,15}$', message_text):
            # Phone number provided directly
            await self.process_phone_login(user, message_text, event)
        else:
            # Ask for phone number
            login_text = """
🔐 **Login Process**

Please send your phone number in international format:

**Examples:**
• `+919876543210` (India)
• `+1234567890` (US)
• `+441234567890` (UK)

You can send it now or use: `/login +919876543210`
            """
            self.waiting_for_phone[user.id] = True
            await event.reply(login_text)

    async def process_phone_login(self, user, phone_number, event):
        """Process phone number login - FIXED"""
        try:
            # Validate phone number format
            if not re.match(r'^\+[0-9]{10,15}$', phone_number):
                await event.reply("❌ Invalid phone number format. Please use international format like `+919876543210`")
                return
            
            # Generate OTP
            otp = f"BAF{datetime.now().strftime('%H%M%S')}"
            
            self.user_sessions[user.id] = {
                'status': 'waiting_otp',
                'phone_number': phone_number,
                'otp': otp,
                'first_name': user.first_name,
                'username': user.username,
                'login_time': datetime.now().isoformat()
            }
            self.user_phone_numbers[user.id] = phone_number
            self.waiting_for_otp[user.id] = True
            self.waiting_for_phone[user.id] = False
            
            await self.save_to_db("user_sessions", self.user_sessions)
            await self.save_to_db("user_phone_numbers", self.user_phone_numbers)
            
            # Initialize default settings for new user
            if user.id not in self.forward_settings:
                self.forward_settings[user.id] = self.default_settings.copy()
                await self.save_to_db("forward_settings", self.forward_settings)
            
            otp_text = f"""
📱 **OTP Sent Successfully!**

**Phone Number:** `{phone_number}`
**OTP Code:** `{otp}`

Please reply with the OTP code to complete login.
            """
            await event.reply(otp_text)
            
        except Exception as e:
            logger.error(f"Error in phone login: {e}")
            await event.reply("❌ Error processing phone number. Please try again.")

    async def handle_otp_verification(self, event):
        """Handle OTP verification - FIXED"""
        user = await event.get_sender()
        
        if not self.waiting_for_otp.get(user.id):
            return  # Not waiting for OTP
        
        otp_attempt = event.text.strip()
        user_session = self.user_sessions.get(user.id, {})
        expected_otp = user_session.get('otp', '')
        
        if otp_attempt == expected_otp:
            # Login successful
            self.user_sessions[user.id]['status'] = 'logged_in'
            self.user_sessions[user.id]['login_time'] = datetime.now().isoformat()
            self.waiting_for_otp[user.id] = False
            
            await self.save_to_db("user_sessions", self.user_sessions)
            
            success_text = f"""
✅ **Login Successful!**

Welcome back, {user.first_name or 'User'}!

**Next Steps:**
1. `/source` - Add channels to forward FROM
2. `/target` - Add channels to forward TO  
3. `/start_forwarding` - Begin auto-forwarding

Use `/help` for all available commands.
            """
            await event.reply(success_text)
        else:
            await event.reply("❌ Invalid OTP. Please try again or use `/login` to restart.")

    async def handle_logout(self, event):
        """Handle /logout command - FIXED"""
        user = await event.get_sender()
        
        # Clear all user data
        for user_dict in [self.user_sessions, self.auto_forwarding, self.source_channels, 
                         self.target_channels, self.user_phone_numbers, self.user_pinned_chats,
                         self.waiting_for_otp, self.waiting_for_phone]:
            if user.id in user_dict:
                del user_dict[user.id]
        
        # Save changes to database
        await self.save_to_db("user_sessions", self.user_sessions)
        await self.save_to_db("auto_forwarding", self.auto_forwarding)
        await self.save_to_db("source_channels", self.source_channels)
        await self.save_to_db("target_channels", self.target_channels)
        await self.save_to_db("user_phone_numbers", self.user_phone_numbers)
        await self.save_to_db("user_pinned_chats", self.user_pinned_chats)
        
        await event.reply("✅ Logged out successfully! All your data has been cleared.")

    async def handle_source(self, event):
        """Handle /source command - FIXED"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        instructions = """
📥 **Set Source Channels**

**How to add source channels:**

1. **Go to Telegram** and find channels you want to forward FROM
2. **Make sure bot is admin** in those channels
3. **Come back here** and use one of these methods:

**Method 1 - Forward Message:**
• Forward any message from the channel to this bot
• I'll automatically detect and add it

**Method 2 - Manual Add:**
• Use `/add_source channel_id`
• Get channel ID from @username_to_id_bot

**Method 3 - Username:**
• Use `/add_source @channel_username`

💡 **You can add multiple source channels!**
        """
        
        await event.reply(instructions)

    async def handle_target(self, event):
        """Handle /target command - FIXED"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        instructions = """
📤 **Set Target Channels**

**How to add target channels:**

1. **Go to Telegram** and find channels you want to forward TO  
2. **Make sure bot is admin** in those channels
3. **Add bot to channel** if not already added
4. **Come back here** and use one of these methods:

**Method 1 - Forward Message:**
• Forward any message from the channel to this bot
• I'll automatically detect and add it

**Method 2 - Manual Add:**
• Use `/add_target channel_id`
• Get channel ID from @username_to_id_bot

**Method 3 - Username:**
• Use `/add_target @channel_username`

💡 **You can add multiple target channels!**
        """
        
        await event.reply(instructions)

    async def handle_add_source(self, event):
        """Handle /add_source command - FIXED"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        channel_input = event.text.replace('/add_source', '').strip()
        
        if not channel_input:
            await event.reply("❌ Please provide channel ID or username. Example: `/add_source -1001234567890` or `/add_source @channelname`")
            return
        
        await self.add_channel_to_list(user.id, channel_input, 'source', event)

    async def handle_add_target(self, event):
        """Handle /add_target command - FIXED"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        channel_input = event.text.replace('/add_target', '').strip()
        
        if not channel_input:
            await event.reply("❌ Please provide channel ID or username. Example: `/add_target -1001234567890` or `/add_target @channelname`")
            return
        
        await self.add_channel_to_list(user.id, channel_input, 'target', event)

    async def add_channel_to_list(self, user_id: int, channel_input: str, list_type: str, event):
        """Add channel to source or target list - FIXED"""
        try:
            # Try to get the entity
            try:
                if channel_input.startswith('@'):
                    entity = await self.client.get_entity(channel_input)
                else:
                    # Try as integer ID
                    channel_id = int(channel_input)
                    entity = await self.client.get_entity(channel_id)
            except Exception as e:
                await event.reply(f"❌ Cannot find channel: {channel_input}\n\nError: {str(e)}")
                return
            
            channel_info = {
                'id': entity.id,
                'name': getattr(entity, 'title', getattr(entity, 'username', 'Unknown')),
                'username': getattr(entity, 'username', None),
                'type': 'channel' if hasattr(entity, 'broadcast') else 'group'
            }
            
            if list_type == 'source':
                if user_id not in self.source_channels:
                    self.source_channels[user_id] = []
                
                # Check if already added
                if any(ch['id'] == entity.id for ch in self.source_channels[user_id]):
                    await event.reply("❌ This channel is already in your source list.")
                    return
                
                self.source_channels[user_id].append(channel_info)
                await self.save_to_db("source_channels", self.source_channels)
                list_name = "source"
                current_list = self.source_channels[user_id]
            else:
                if user_id not in self.target_channels:
                    self.target_channels[user_id] = []
                
                # Check if already added
                if any(ch['id'] == entity.id for ch in self.target_channels[user_id]):
                    await event.reply("❌ This channel is already in your target list.")
                    return
                
                self.target_channels[user_id].append(channel_info)
                await self.save_to_db("target_channels", self.target_channels)
                list_name = "target"
                current_list = self.target_channels[user_id]
            
            success_text = f"""
✅ **Channel Added Successfully!**

**Channel:** {channel_info['name']}
**Type:** {channel_info['type']}
**ID:** `{channel_info['id']}`

**Total {list_type} channels:** {len(current_list)}
            """
            await event.reply(success_text)
            
        except ValueError:
            await event.reply("❌ Invalid channel ID. Please use a valid numeric ID or username.")
        except Exception as e:
            logger.error(f"Error adding channel: {e}")
            await event.reply("❌ Error adding channel. Please check the ID/username and try again.")

    async def handle_remove_source(self, event):
        """Handle /remove_source command - FIXED"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        sources = self.source_channels.get(user.id, [])
        if not sources:
            await event.reply("❌ No source channels configured. Use `/source` to add some.")
            return
        
        removal_text = "🗑️ **Remove Source Channels**\n\n"
        removal_text += "**Your current source channels:**\n"
        
        for i, source in enumerate(sources, 1):
            removal_text += f"{i}. {source['name']} (ID: `{source['id']}`)\n"
        
        removal_text += "\n**To remove:** Reply with the channel number or use `/remove_source_number X`"
        
        await event.reply(removal_text)

    async def handle_remove_target(self, event):
        """Handle /remove_target command - FIXED"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        targets = self.target_channels.get(user.id, [])
        if not targets:
            await event.reply("❌ No target channels configured. Use `/target` to add some.")
            return
        
        removal_text = "🗑️ **Remove Target Channels**\n\n"
        removal_text += "**Your current target channels:**\n"
        
        for i, target in enumerate(targets, 1):
            removal_text += f"{i}. {target['name']} (ID: `{target['id']}`)\n"
        
        removal_text += "\n**To remove:** Reply with the channel number or use `/remove_target_number X`"
        
        await event.reply(removal_text)

    async def handle_remove_source_number(self, event):
        """Handle /remove_source_number command - FIXED"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        try:
            number = int(event.text.replace('/remove_source_number', '').strip())
            sources = self.source_channels.get(user.id, [])
            
            if 1 <= number <= len(sources):
                removed_channel = sources[number-1]
                del sources[number-1]
                await self.save_to_db("source_channels", self.source_channels)
                
                await event.reply(f"✅ Removed source channel: {removed_channel['name']}")
            else:
                await event.reply("❌ Invalid channel number.")
                
        except ValueError:
            await event.reply("❌ Please provide a valid number. Example: `/remove_source_number 1`")

    async def handle_remove_target_number(self, event):
        """Handle /remove_target_number command - FIXED"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        try:
            number = int(event.text.replace('/remove_target_number', '').strip())
            targets = self.target_channels.get(user.id, [])
            
            if 1 <= number <= len(targets):
                removed_channel = targets[number-1]
                del targets[number-1]
                await self.save_to_db("target_channels", self.target_channels)
                
                await event.reply(f"✅ Removed target channel: {removed_channel['name']}")
            else:
                await event.reply("❌ Invalid channel number.")
                
        except ValueError:
            await event.reply("❌ Please provide a valid number. Example: `/remove_target_number 1`")

    async def handle_start_forwarding(self, event):
        """Handle /start_forwarding command - FIXED"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        sources = self.source_channels.get(user.id, [])
        targets = self.target_channels.get(user.id, [])
        
        if not sources or not targets:
            await event.reply("❌ Please set up both source and target channels first!\n\nUse:\n• `/source` - Add source channels\n• `/target` - Add target channels")
            return
        
        self.auto_forwarding[user.id] = True
        await self.save_to_db("auto_forwarding", self.auto_forwarding)
        
        success_text = f"""
✅ **Auto-Forwarding Started!**

**📊 Configuration:**
• Source Channels: {len(sources)}
• Target Channels: {len(targets)}  
• Status: 🟢 **ACTIVE**

**📨 Now Forwarding:**
Messages from your source channels will be automatically forwarded to target channels.

**⏸️ To Pause:** Use `/stop_forwarding`
**⚙️ Settings:** Use `/forward_settings`
**📊 Status:** Use `/config`
        """
        await event.reply(success_text)

    async def handle_stop_forwarding(self, event):
        """Handle /stop_forwarding command - FIXED"""
        user = await event.get_sender()
        
        if user.id not in self.auto_forwarding or not self.auto_forwarding[user.id]:
            await event.reply("❌ Auto-forwarding is not currently active.")
            return
        
        self.auto_forwarding[user.id] = False
        await self.save_to_db("auto_forwarding", self.auto_forwarding)
        
        await event.reply("⏸️ **Auto-forwarding stopped.**\nUse `/start_forwarding` to resume.")

    async def handle_config(self, event):
        """Handle /config command - FIXED"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        user_data = self.user_sessions.get(user.id, {})
        sources = self.source_channels.get(user.id, [])
        targets = self.target_channels.get(user.id, [])
        settings = self.forward_settings.get(user.id, self.default_settings)
        
        config_text = f"""
⚙️ **Configuration for {user_data.get('first_name', 'User')}**

👤 **Account:**
• Phone: {user_data.get('phone_number', 'Not set')}
• Status: {'🟢 Logged In' if user_data.get('status') == 'logged_in' else '🔴 Not Logged In'}

📥 **Source Channels ({len(sources)}):**
"""
        for i, source in enumerate(sources, 1):
            config_text += f"{i}. {source.get('name', 'Unknown')} (ID: `{source['id']}`)\n"
        
        config_text += f"\n📤 **Target Channels ({len(targets)}):**\n"
        for i, target in enumerate(targets, 1):
            config_text += f"{i}. {target.get('name', 'Unknown')} (ID: `{target['id']}`)\n"
        
        config_text += f"""
🎛️ **Settings:**
• Hide Header: {'✅ Yes' if settings.get('hide_header') else '❌ No'}
• Forward Media: {'✅ Yes' if settings.get('forward_media') else '❌ No'}
• URL Previews: {'✅ Yes' if settings.get('url_previews') else '❌ No'}
• Auto-Forwarding: {'🟢 Active' if self.auto_forwarding.get(user.id) else '⏸️ Inactive'}

💡 **Manage:**
• `/source` - Edit sources
• `/target` - Edit targets  
• `/forward_settings` - Change settings
        """
        await event.reply(config_text)

    async def handle_forward_settings(self, event):
        """Handle /forward_settings command - FIXED"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        settings = self.forward_settings.get(user.id, self.default_settings)
        
        settings_text = f"""
⚙️ **Forwarding Settings**

**Current Configuration:**
• Hide Header: {'✅ ON' if settings.get('hide_header') else '❌ OFF'} - `/hide_header`
• Forward Media: {'✅ ON' if settings.get('forward_media') else '❌ OFF'} - `/media_status`  
• URL Previews: {'✅ ON' if settings.get('url_previews') else '❌ OFF'} - `/url_previews`
• Remove Usernames: {'✅ ON' if settings.get('remove_usernames') else '❌ OFF'} - `/remove_usernames`
• Remove Links: {'✅ ON' if settings.get('remove_links') else '❌ OFF'} - `/remove_links`

**Usage:**
Send any setting command to toggle it ON/OFF
Example: `/hide_header` to toggle header visibility
        """
        
        await event.reply(settings_text)

    async def handle_toggle_setting(self, event, setting_name: str):
        """Toggle individual settings - FIXED"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        if user.id not in self.forward_settings:
            self.forward_settings[user.id] = self.default_settings.copy()
        
        current_value = self.forward_settings[user.id].get(setting_name, False)
        self.forward_settings[user.id][setting_name] = not current_value
        
        await self.save_to_db("forward_settings", self.forward_settings)
        
        setting_names = {
            'hide_header': 'Hide Header',
            'forward_media': 'Media Forwarding',
            'url_previews': 'URL Previews',
            'remove_usernames': 'Remove Usernames',
            'remove_links': 'Remove Links'
        }
        
        new_status = '✅ ON' if not current_value else '❌ OFF'
        await event.reply(f"**{setting_names[setting_name]}** is now **{new_status}**")

    async def handle_settings(self, event):
        """Handle /settings command - FIXED"""
        settings_menu = """
🔧 **All Settings Menu**

**Account Settings:**
• `/status` - Check your account status
• `/config` - View current configuration

**Channel Management:**
• `/source` - Manage source channels
• `/target` - Manage target channels
• `/remove_source` - Remove source channels  
• `/remove_target` - Remove target channels

**Forwarding Control:**
• `/start_forwarding` - Start auto-forwarding
• `/stop_forwarding` - Stop auto-forwarding
• `/forward_settings` - Customize forwarding

**Help & Support:**
• `/help` - All commands
• `/tutorial` - Guides
        """
        await event.reply(settings_menu)

    async def handle_tutorial(self, event):
        """Handle /tutorial command - FIXED"""
        tutorial_text = """
🎥 **Video Tutorials & Guides**

**Quick Start Guide:**

1. **Login:** `/login +919876543210`
2. **Add Sources:** `/add_source -1001234567890` or forward message from channel
3. **Add Targets:** `/add_target -1001234567891` or forward message from channel  
4. **Start:** `/start_forwarding`

**Video Tutorials:**
• Basic Setup: https://example.com/tutorial1
• Advanced Features: https://example.com/tutorial2
• Troubleshooting: https://example.com/tutorial3

**Need Help?** Contact @starworrier
        """
        await event.reply(tutorial_text)

    async def handle_help(self, event):
        """Handle /help command - FIXED"""
        help_text = """
🆘 **Help Center - All Commands**

**🔐 Account:**
• `/start` - Start bot
• `/login` - Login to account  
• `/logout` - Logout
• `/status` - Account status

**⚙️ Setup:**
• `/source` - Set source channels
• `/target` - Set target channels
• `/add_source` - Add specific source channel
• `/add_target` - Add specific target channel
• `/remove_source` - Remove source channels
• `/remove_target` - Remove target channels
• `/config` - View configuration

**🔄 Forwarding:**
• `/start_forwarding` - Start forwarding
• `/stop_forwarding` - Stop forwarding
• `/forward_settings` - Customize settings

**🎛️ Settings:**
• `/hide_header` - Toggle header
• `/media_status` - Toggle media
• `/url_previews` - Toggle URL previews
• `/remove_usernames` - Toggle usernames
• `/remove_links` - Toggle links

**📚 Learning:**
• `/tutorial` - Video tutorials
• `/help` - This help message

**👑 Admin:** `/admin` (Owner only)

📞 **Support:** @starworrier
        """
        await event.reply(help_text)

    async def handle_status(self, event):
        """Handle /status command - FIXED"""
        user = await event.get_sender()
        
        if user.id not in self.user_sessions:
            await event.reply("❌ You are not logged in. Use `/login` to start.")
            return
        
        user_data = self.user_sessions[user.id]
        sources = self.source_channels.get(user.id, [])
        targets = self.target_channels.get(user.id, [])
        
        status_text = f"""
📊 **Account Status**

**👤 User Info:**
• Name: {user_data.get('first_name', 'N/A')}
• Username: @{user_data.get('username', 'N/A')}
• Phone: {user_data.get('phone_number', 'Not set')}
• Status: {'✅ Logged In' if user_data.get('status') == 'logged_in' else '❌ Not Logged In'}

**📈 Usage:**
• Source Channels: {len(sources)}
• Target Channels: {len(targets)}
• Auto-Forwarding: {'🟢 Active' if self.auto_forwarding.get(user.id) else '⏸️ Inactive'}

**🕐 Session:**
• Login Time: {user_data.get('login_time', 'N/A')}
        """
        await event.reply(status_text)

    # ==================== ADMIN COMMANDS ====================

    async def handle_broadcast(self, event):
        """Handle /broadcast command - FIXED (Admin only)"""
        user = await event.get_sender()
        
        if not self.is_admin(user.id):
            await event.reply("❌ Access denied! Admin only.")
            return
        
        message_text = event.text.replace('/broadcast', '').strip()
        
        if not message_text:
            await event.reply("❌ Usage: `/broadcast your message here`")
            return
        
        if not self.user_sessions:
            await event.reply("❌ No users to broadcast to.")
            return
        
        await event.reply(f"🔄 Broadcasting to {len(self.user_sessions)} users...")
        
        success_count = 0
        for user_id in self.user_sessions.keys():
            try:
                await self.client.send_message(
                    user_id, 
                    f"📢 **Admin Broadcast:**\n\n{message_text}\n\n— Best Auto Forwarding Bot"
                )
                success_count += 1
                await asyncio.sleep(0.1)  # Rate limiting
            except Exception as e:
                logger.error(f"Broadcast failed for {user_id}: {e}")
        
        await event.reply(f"✅ Broadcast complete! Sent to {success_count}/{len(self.user_sessions)} users.")

    async def handle_admin_stats(self, event):
        """Handle /stats command - FIXED (Admin only)"""
        user = await event.get_sender()
        
        if not self.is_admin(user.id):
            await event.reply("❌ Access denied! Admin only.")
            return
        
        active_users = len([u for u in self.user_sessions.values() if u.get('status') == 'logged_in'])
        total_sources = sum(len(s) for s in self.source_channels.values())
        total_targets = sum(len(t) for t in self.target_channels.values())
        active_forwarding = sum(1 for s in self.auto_forwarding.values() if s)
        
        stats_text = f"""
📊 **Admin Statistics**

**👥 Users:**
• Total Users: {len(self.user_sessions)}
• Active Users: {active_users}
• Phone Numbers: {len(self.user_phone_numbers)}

**📡 Channels:**
• Total Sources: {total_sources}
• Total Targets: {total_targets}

**⚡ Activity:**
• Active Forwarding: {active_forwarding}

**💾 Database:**
• Total Entries: {len(await self.db.get_all_keys())}
        """
        
        await event.reply(stats_text)

    async def handle_admin(self, event):
        """Handle /admin command - FIXED (Admin only)"""
        user = await event.get_sender()
        
        if not self.is_admin(user.id):
            await event.reply("❌ Access denied! Admin only.")
            return
        
        admin_text = """
👑 **Admin Panel**

**Commands:**
• `/stats` - Bot statistics
• `/broadcast` - Message all users

**User Management:**
• Total Users: {len(self.user_sessions)}
• Active Users: {len([u for u in self.user_sessions.values() if u.get('status') == 'logged_in'])}
        """.format(len(self.user_sessions), len([u for u in self.user_sessions.values() if u.get('status') == 'logged_in']))
        
        await event.reply(admin_text)

    # ==================== MESSAGE HANDLING ====================

    async def handle_forwarded_message(self, event):
        """Handle forwarded messages for channel detection - FIXED"""
        try:
            if not event.message.fwd_from:
                return
                
            user = await event.get_sender()
            if not await self.check_user_logged_in(user.id, event, silent=True):
                return
            
            # Get the original chat info
            fwd = event.message.fwd_from
            if hasattr(fwd, 'from_id'):
                channel_id = fwd.from_id
                try:
                    entity = await self.client.get_entity(channel_id)
                    channel_info = {
                        'id': entity.id,
                        'name': getattr(entity, 'title', getattr(entity, 'username', 'Unknown')),
                        'username': getattr(entity, 'username', None),
                        'type': 'channel' if hasattr(entity, 'broadcast') else 'group'
                    }
                    
                    # Ask user if they want to add as source or target
                    question = f"""
📨 **Channel Detected!**

**Channel:** {channel_info['name']}
**ID:** `{channel_info['id']}`
**Type:** {channel_info['type']}

Do you want to add this channel as:
• Source (messages FROM here) - Reply `source`
• Target (messages TO here) - Reply `target`
• Cancel - Reply `cancel`
                    """
                    
                    await event.reply(question)
                    self.user_pinned_chats[user.id] = channel_info
                    await self.save_to_db("user_pinned_chats", self.user_pinned_chats)
                    
                except Exception as e:
                    logger.error(f"Error getting forwarded channel info: {e}")
                    
        except Exception as e:
            logger.error(f"Error handling forwarded message: {e}")

    async def handle_channel_selection(self, event):
        """Handle user's source/target selection - FIXED"""
        user = await event.get_sender()
        choice = event.text.strip().lower()
        
        if user.id not in self.user_pinned_chats:
            return
            
        channel_info = self.user_pinned_chats[user.id]
        
        if choice == 'source':
            if user.id not in self.source_channels:
                self.source_channels[user.id] = []
            
            # Check if already added
            if any(ch['id'] == channel_info['id'] for ch in self.source_channels[user.id]):
                await event.reply("❌ This channel is already in your source list.")
            else:
                self.source_channels[user.id].append(channel_info)
                await self.save_to_db("source_channels", self.source_channels)
                await event.reply(f"✅ Added as source channel: {channel_info['name']}")
                
        elif choice == 'target':
            if user.id not in self.target_channels:
                self.target_channels[user.id] = []
            
            # Check if already added
            if any(ch['id'] == channel_info['id'] for ch in self.target_channels[user.id]):
                await event.reply("❌ This channel is already in your target list.")
            else:
                self.target_channels[user.id].append(channel_info)
                await self.save_to_db("target_channels", self.target_channels)
                await event.reply(f"✅ Added as target channel: {channel_info['name']}")
                
        elif choice == 'cancel':
            await event.reply("❌ Operation cancelled.")
        else:
            await event.reply("❌ Invalid choice. Please reply with `source`, `target`, or `cancel`.")
            return
            
        # Clear the stored channel info
        del self.user_pinned_chats[user.id]
        await self.save_to_db("user_pinned_chats", self.user_pinned_chats)

    async def handle_auto_forward_message(self, event):
        """Handle actual message forwarding - FIXED"""
        try:
            # Don't process commands or bot's own messages
            if event.text and (event.text.startswith('/') or event.out):
                return
                
            # Check if it's a forwarded message for channel detection
            if event.message.fwd_from:
                await self.handle_forwarded_message(event)
                return
                
            # Check if it's a channel selection
            if event.text and event.text.lower() in ['source', 'target', 'cancel']:
                await self.handle_channel_selection(event)
                return
                
            # Check if it's an OTP
            if self.waiting_for_otp.get(event.sender_id):
                await self.handle_otp_verification(event)
                return
                
            # Check if it's a phone number
            if self.waiting_for_phone.get(event.sender_id) and re.match(r'^\+[0-9]{10,15}$', event.text or ''):
                await self.process_phone_login(await event.get_sender(), event.text, event)
                return
            
            # Auto-forwarding logic
            if not event.message or not hasattr(event, 'chat_id'):
                return
            
            # Check if message is from a source channel for any user
            for user_id, sources in self.source_channels.items():
                if not self.auto_forwarding.get(user_id, False):
                    continue
                
                # Check if this chat is a source for this user
                source_ids = [channel['id'] for channel in sources]
                if event.chat_id in source_ids:
                    await self.forward_to_targets(user_id, event)
                    break
                    
        except Exception as e:
            logger.error(f"Error in message handling: {e}")

    async def forward_to_targets(self, user_id: int, event):
        """Forward message to user's target channels - FIXED"""
        try:
            targets = self.target_channels.get(user_id, [])
            if not targets:
                return
            
            settings = self.forward_settings.get(user_id, self.default_settings)
            
            for target in targets:
                try:
                    # Forward the message
                    await event.message.forward_to(target['id'])
                    
                except Exception as e:
                    logger.error(f"Error forwarding to {target.get('name', 'Unknown')}: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Error in forward_to_targets: {e}")

    # ==================== UTILITY FUNCTIONS ====================

    async def check_user_logged_in(self, user_id: int, event, silent: bool = False) -> bool:
        """Check if user is logged in"""
        if user_id not in self.user_sessions or self.user_sessions[user_id].get('status') != 'logged_in':
            if not silent:
                await event.reply("❌ Please login first using `/login`")
            return False
        return True

    def register_handlers(self):
        """Register all event handlers - COMPLETELY FIXED"""
        
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
        
        @self.client.on(events.NewMessage(pattern='/tutorial'))
        async def tutorial_handler(event):
            await self.handle_tutorial(event)
        
        @self.client.on(events.NewMessage(pattern='/status'))
        async def status_handler(event):
            await self.handle_status(event)
        
        @self.client.on(events.NewMessage(pattern='/config'))
        async def config_handler(event):
            await self.handle_config(event)
        
        @self.client.on(events.NewMessage(pattern='/settings'))
        async def settings_handler(event):
            await self.handle_settings(event)
        
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
        
        @self.client.on(events.NewMessage(pattern='/remove_source'))
        async def remove_source_handler(event):
            await self.handle_remove_source(event)
        
        @self.client.on(events.NewMessage(pattern='/remove_target'))
        async def remove_target_handler(event):
            await self.handle_remove_target(event)
        
        @self.client.on(events.NewMessage(pattern='/remove_source_number'))
        async def remove_source_number_handler(event):
            await self.handle_remove_source_number(event)
        
        @self.client.on(events.NewMessage(pattern='/remove_target_number'))
        async def remove_target_number_handler(event):
            await self.handle_remove_target_number(event)
        
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
        
        # Individual setting toggles
        @self.client.on(events.NewMessage(pattern='/hide_header'))
        async def hide_header_handler(event):
            await self.handle_toggle_setting(event, 'hide_header')
        
        @self.client.on(events.NewMessage(pattern='/media_status'))
        async def media_status_handler(event):
            await self.handle_toggle_setting(event, 'forward_media')
        
        @self.client.on(events.NewMessage(pattern='/url_previews'))
        async def url_previews_handler(event):
            await self.handle_toggle_setting(event, 'url_previews')
        
        @self.client.on(events.NewMessage(pattern='/remove_usernames'))
        async def remove_usernames_handler(event):
            await self.handle_toggle_setting(event, 'remove_usernames')
        
        @self.client.on(events.NewMessage(pattern='/remove_links'))
        async def remove_links_handler(event):
            await self.handle_toggle_setting(event, 'remove_links')
        
        # Admin commands
        @self.client.on(events.NewMessage(pattern='/admin'))
        async def admin_handler(event):
            await self.handle_admin(event)
        
        @self.client.on(events.NewMessage(pattern='/stats'))
        async def stats_handler(event):
            await self.handle_admin_stats(event)
        
        @self.client.on(events.NewMessage(pattern='/broadcast'))
        async def broadcast_handler(event):
            await self.handle_broadcast(event)
        
        # Main message handler for everything else
        @self.client.on(events.NewMessage)
        async def universal_handler(event):
            await self.handle_auto_forward_message(event)
        
        logger.info("✅ All handlers registered successfully!")

async def main():
    """Main function - FIXED"""
    
    # Get credentials from environment
    api_id = int(os.getenv('TELEGRAM_API_ID', '123456'))
    api_hash = os.getenv('TELEGRAM_API_HASH', 'your_api_hash')
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN', 'your_bot_token')
    db_channel_id = int(os.getenv('DB_CHANNEL_ID', '-1001234567890'))
    
    # Update admin ID
    global ADMIN_USER_IDS
    admin_env = os.getenv('ADMIN_USER_IDS', '')
    if admin_env:
        ADMIN_USER_IDS = [int(id.strip()) for id in admin_env.split(',')]
    
    # Validate credentials
    if any(str(x) in ['123456', 'your_api_hash', 'your_bot_token', '-1001234567890'] 
           for x in [api_id, api_hash, bot_token, db_channel_id]):
        print("❌ Please set valid environment variables in .env file")
        print("Required: TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_BOT_TOKEN, DB_CHANNEL_ID")
        return
    
    print("🚀 Starting Best Auto Forwarding Bot...")
    
    bot = AdvancedAutoForwardBot(api_id, api_hash, bot_token, db_channel_id)
    
    try:
        await bot.initialize()
        print("✅ Bot is running perfectly! All commands are working.")
        print("📱 Test with: /start, /login, /help")
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
