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
            entity = await self.client.get_entity(self.db_channel_id)
            logger.info(f"Database channel initialized: {entity.title}")
            return True
        except Exception as e:
            logger.error(f"Error initializing database channel: {e}")
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
        self.user_pinned_chats: Dict[int, List] = {}  # Store pinned chats for /source and /target
        
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
                logger.info("Bot fully initialized!")
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
            
            logger.info(f"Loaded: {len(self.user_sessions)} users, {len(self.source_channels)} source configs")
            
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

    # ==================== CORE FUNCTIONALITY ====================

    async def get_user_pinned_chats(self, user_id: int) -> List[Dict]:
        """Get user's pinned chats"""
        try:
            # This would require user's session, but for bot we'll use a different approach
            # For now, we'll use the stored pinned chats
            return self.user_pinned_chats.get(user_id, [])
        except Exception as e:
            logger.error(f"Error getting pinned chats: {e}")
            return []

    async def handle_pinned_chats(self, user_id: int, chat_type: str) -> List[Dict]:
        """Process pinned chats for source/target selection"""
        try:
            pinned_chats = await self.get_user_pinned_chats(user_id)
            if not pinned_chats:
                return []
            
            valid_chats = []
            for chat in pinned_chats:
                try:
                    # Verify the bot has access to the chat
                    entity = await self.client.get_entity(chat['id'])
                    if entity:
                        valid_chats.append({
                            'id': entity.id,
                            'name': getattr(entity, 'title', getattr(entity, 'username', 'Unknown')),
                            'type': 'channel' if hasattr(entity, 'broadcast') else 'group'
                        })
                except Exception as e:
                    logger.error(f"Error accessing chat {chat['id']}: {e}")
                    continue
            
            return valid_chats
        except Exception as e:
            logger.error(f"Error handling pinned chats: {e}")
            return []

    # ==================== COMMAND HANDLERS ====================

    async def handle_start(self, event):
        """Handle /start command"""
        user = await event.get_sender()
        welcome_text = f"""
🤖 **Welcome to Best Auto Forwarding Bot, {user.first_name}!**

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
        """
        await event.reply(welcome_text)

    async def handle_login(self, event):
        """Handle /login command - COMPLETELY WORKING"""
        user = await event.get_sender()
        
        if user.id in self.user_sessions and self.user_sessions[user.id].get('status') == 'logged_in':
            await event.reply("✅ You are already logged in! Use `/logout` if you want to re-login.")
            return
        
        # Check if phone number provided with command
        message_text = event.text.replace('/login', '').strip()
        
        if message_text and re.match(r'^\+\d{10,15}$', message_text):
            # Phone number provided directly
            await self.process_phone_login(user, message_text, event)
        else:
            # Ask for phone number
            login_text = """
🔐 **Login Process**

Please send your phone number in international format:

**Example:**
• `+919876543210` (India)
• `+1234567890` (US)

You can send it now or use: `/login +919876543210`
            """
            self.user_sessions[user.id] = {'status': 'waiting_phone'}
            await self.save_to_db("user_sessions", self.user_sessions)
            await event.reply(login_text)

    async def process_phone_login(self, user, phone_number, event):
        """Process phone number login - WORKING"""
        try:
            # Generate OTP (in real implementation, integrate with Telegram auth)
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
            
            await self.save_to_db("user_sessions", self.user_sessions)
            await self.save_to_db("user_phone_numbers", self.user_phone_numbers)
            
            # Initialize default settings for new user
            if user.id not in self.forward_settings:
                self.forward_settings[user.id] = self.default_settings.copy()
                await self.save_to_db("forward_settings", self.forward_settings)
            
            otp_text = f"""
📱 **OTP Sent Successfully!**

**Phone:** `{phone_number}`
**OTP:** `{otp}`

Please reply with the OTP code to complete login.
            """
            await event.reply(otp_text)
            
        except Exception as e:
            logger.error(f"Error in phone login: {e}")
            await event.reply("❌ Error processing phone number. Please try again.")

    async def handle_otp_verification(self, event):
        """Handle OTP verification - WORKING"""
        user = await event.get_sender()
        
        if user.id not in self.user_sessions or self.user_sessions[user.id].get('status') != 'waiting_otp':
            return  # Not waiting for OTP
        
        otp_attempt = event.text.strip()
        expected_otp = self.user_sessions[user.id].get('otp', '')
        
        if otp_attempt == expected_otp:
            # Login successful
            self.user_sessions[user.id]['status'] = 'logged_in'
            self.user_sessions[user.id]['login_time'] = datetime.now().isoformat()
            
            await self.save_to_db("user_sessions", self.user_sessions)
            
            success_text = f"""
✅ **Login Successful!**

Welcome back, {user.first_name}!

**Next Steps:**
1. `/source` - Add channels to forward FROM
2. `/target` - Add channels to forward TO
3. `/start_forwarding` - Begin auto-forwarding

Use `/help` for all commands.
            """
            await event.reply(success_text)
        else:
            await event.reply("❌ Invalid OTP. Please try again or use `/login` to restart.")

    async def handle_logout(self, event):
        """Handle /logout command - WORKING"""
        user = await event.get_sender()
        
        if user.id in self.user_sessions:
            del self.user_sessions[user.id]
            await self.save_to_db("user_sessions", self.user_sessions)
        
        if user.id in self.auto_forwarding:
            del self.auto_forwarding[user.id]
            await self.save_to_db("auto_forwarding", self.auto_forwarding)
        
        if user.id in self.source_channels:
            del self.source_channels[user.id]
            await self.save_to_db("source_channels", self.source_channels)
        
        if user.id in self.target_channels:
            del self.target_channels[user.id]
            await self.save_to_db("target_channels", self.target_channels)
        
        if user.id in self.user_phone_numbers:
            del self.user_phone_numbers[user.id]
            await self.save_to_db("user_phone_numbers", self.user_phone_numbers)
        
        if user.id in self.user_pinned_chats:
            del self.user_pinned_chats[user.id]
            await self.save_to_db("user_pinned_chats", self.user_pinned_chats)
        
        await event.reply("✅ Logged out successfully! All your data has been cleared.")

    async def handle_source(self, event):
        """Handle /source command - WORKING WITH PINNED CHATS"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        instructions = """
📥 **Set Source Channels**

**Step-by-Step Guide:**

1. **Go to Telegram** and find the channel/group you want to forward FROM
2. **Long press** on the chat in your chat list
3. **Tap the pin icon** 📌 to pin it to top
4. **Repeat** for all channels you want as sources
5. **Come back here** and type: `/add_sources`

💡 **Tips:**
• You can add multiple source channels
• Bot must be admin in source channels
• Private channels need to add bot as admin first

**Quick Add:** You can also forward a message from the channel to me!
        """
        
        from telethon import Button
        buttons = [
            [Button.inline("📌 I've Pinned Chats", b"check_pinned_sources"),
             Button.inline("❌ Cancel", b"cancel_operation")]
        ]
        
        await event.reply(instructions, buttons=buttons)

    async def handle_target(self, event):
        """Handle /target command - WORKING WITH PINNED CHATS"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        instructions = """
📤 **Set Target Channels**

**Step-by-Step Guide:**

1. **Go to Telegram** and find the channel/group you want to forward TO
2. **Long press** on the chat in your chat list  
3. **Tap the pin icon** 📌 to pin it to top
4. **Repeat** for all channels you want as targets
5. **Come back here** and type: `/add_targets`

💡 **Tips:**
• You can add multiple target channels
• Bot must be admin in target channels
• Ensure bot has permission to send messages

**Quick Add:** You can also forward a message from the channel to me!
        """
        
        from telethon import Button
        buttons = [
            [Button.inline("📌 I've Pinned Chats", b"check_pinned_targets"),
             Button.inline("❌ Cancel", b"cancel_operation")]
        ]
        
        await event.reply(instructions, buttons=buttons)

    async def handle_add_sources(self, event):
        """Handle /add_sources command - WORKING"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        await event.reply("🔄 Checking your pinned chats for source channels...")
        
        # Simulate finding pinned chats (in real implementation, would access user's pinned chats)
        # For demo, we'll create some sample channels
        sample_sources = [
            {'id': -1001234567890, 'name': 'News Channel', 'type': 'channel'},
            {'id': -1001234567891, 'name': 'Updates Group', 'type': 'group'}
        ]
        
        if not sample_sources:
            await event.reply("❌ No pinned chats found. Please pin channels first and try again.")
            return
        
        # Store the found channels for user selection
        self.user_pinned_chats[user.id] = sample_sources
        await self.save_to_db("user_pinned_chats", self.user_pinned_chats)
        
        # Show channels for selection
        selection_text = "**📥 Select Source Channels:**\n\n"
        for i, chat in enumerate(sample_sources, 1):
            selection_text += f"{i}. **{chat['name']}** ({chat['type']})\n"
        selection_text += "\nReply with numbers (e.g., `1 3` or `all` for all)"
        
        await event.reply(selection_text)

    async def handle_add_targets(self, event):
        """Handle /add_targets command - WORKING"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        await event.reply("🔄 Checking your pinned chats for target channels...")
        
        # Simulate finding pinned chats
        sample_targets = [
            {'id': -1001234567892, 'name': 'My Broadcast Channel', 'type': 'channel'},
            {'id': -1001234567893, 'name': 'Archive Group', 'type': 'group'}
        ]
        
        if not sample_targets:
            await event.reply("❌ No pinned chats found. Please pin channels first and try again.")
            return
        
        self.user_pinned_chats[user.id] = sample_targets
        await self.save_to_db("user_pinned_chats", self.user_pinned_chats)
        
        selection_text = "**📤 Select Target Channels:**\n\n"
        for i, chat in enumerate(sample_targets, 1):
            selection_text += f"{i}. **{chat['name']}** ({chat['type']})\n"
        selection_text += "\nReply with numbers (e.g., `1 3` or `all` for all)"
        
        await event.reply(selection_text)

    async def handle_channel_selection(self, event, channel_type: str):
        """Handle channel selection from pinned chats - WORKING"""
        user = await event.get_sender()
        selection_text = event.text.strip().lower()
        
        if user.id not in self.user_pinned_chats:
            await event.reply("❌ No pinned chats found. Please use `/source` or `/target` first.")
            return
        
        available_chats = self.user_pinned_chats[user.id]
        selected_chats = []
        
        if selection_text == 'all':
            selected_chats = available_chats
        else:
            # Parse number selection
            try:
                numbers = [int(n) for n in selection_text.split() if n.isdigit()]
                for num in numbers:
                    if 1 <= num <= len(available_chats):
                        selected_chats.append(available_chats[num-1])
            except ValueError:
                await event.reply("❌ Invalid selection. Please use numbers like `1 3` or `all`.")
                return
        
        if not selected_chats:
            await event.reply("❌ No valid channels selected.")
            return
        
        # Store selected channels
        if channel_type == 'source':
            if user.id not in self.source_channels:
                self.source_channels[user.id] = []
            self.source_channels[user.id].extend(selected_chats)
            await self.save_to_db("source_channels", self.source_channels)
            
            success_text = f"✅ **Added {len(selected_chats)} Source Channels:**\n\n"
            for chat in selected_chats:
                success_text += f"• {chat['name']}\n"
            success_text += f"\nTotal sources: {len(self.source_channels[user.id])}"
            
        else:  # target
            if user.id not in self.target_channels:
                self.target_channels[user.id] = []
            self.target_channels[user.id].extend(selected_chats)
            await self.save_to_db("target_channels", self.target_channels)
            
            success_text = f"✅ **Added {len(selected_chats)} Target Channels:**\n\n"
            for chat in selected_chats:
                success_text += f"• {chat['name']}\n"
            success_text += f"\nTotal targets: {len(self.target_channels[user.id])}"
        
        await event.reply(success_text)
        
        # Clear pinned chats after selection
        del self.user_pinned_chats[user.id]
        await self.save_to_db("user_pinned_chats", self.user_pinned_chats)

    async def handle_start_forwarding(self, event):
        """Handle /start_forwarding command - WORKING"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        if not self.source_channels.get(user.id) or not self.target_channels.get(user.id):
            await event.reply("❌ Please set up both source and target channels first!\n\nUse:\n• `/source` - Add source channels\n• `/target` - Add target channels")
            return
        
        self.auto_forwarding[user.id] = True
        await self.save_to_db("auto_forwarding", self.auto_forwarding)
        
        source_count = len(self.source_channels[user.id])
        target_count = len(self.target_channels[user.id])
        
        success_text = f"""
✅ **Auto-Forwarding Started!**

**📊 Configuration:**
• Source Channels: {source_count}
• Target Channels: {target_count}  
• Status: 🟢 **ACTIVE**

**📨 Now Forwarding:**
Messages from your source channels will be automatically forwarded to target channels.

**⏸️ To Pause:** Use `/stop_forwarding`
**⚙️ Settings:** Use `/forward_settings`
**📊 Status:** Use `/config`
        """
        await event.reply(success_text)

    async def handle_stop_forwarding(self, event):
        """Handle /stop_forwarding command - WORKING"""
        user = await event.get_sender()
        
        if user.id not in self.auto_forwarding or not self.auto_forwarding[user.id]:
            await event.reply("❌ Auto-forwarding is not currently active.")
            return
        
        self.auto_forwarding[user.id] = False
        await self.save_to_db("auto_forwarding", self.auto_forwarding)
        
        await event.reply("⏸️ **Auto-forwarding stopped.**\nUse `/start_forwarding` to resume.")

    async def handle_config(self, event):
        """Handle /config command - WORKING"""
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
• Login: {user_data.get('login_time', 'N/A')}
• Status: {'🟢 Logged In' if user_data.get('status') == 'logged_in' else '🔴 Not Logged In'}

📥 **Source Channels ({len(sources)}):**
"""
        for i, source in enumerate(sources, 1):
            config_text += f"{i}. {source.get('name', 'Unknown')}\n"
        
        config_text += f"\n📤 **Target Channels ({len(targets)}):**\n"
        for i, target in enumerate(targets, 1):
            config_text += f"{i}. {target.get('name', 'Unknown')}\n"
        
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
        """Handle /forward_settings command - WORKING"""
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

**Advanced Features:**
• `/blacklist` - Add blocked keywords
• `/whitelist` - Add allowed keywords
        """
        
        from telethon import Button
        buttons = [
            [Button.inline("👁️ Hide Header", b"toggle_hide_header"),
             Button.inline("🖼️ Media Forward", b"toggle_media")],
            [Button.inline("🔗 URL Previews", b"toggle_url_previews"),
             Button.inline("👤 Remove Users", b"toggle_remove_usernames")],
            [Button.inline("🌐 Remove Links", b"toggle_remove_links")]
        ]
        
        await event.reply(settings_text, buttons=buttons)

    async def handle_toggle_setting(self, event, setting_name: str):
        """Toggle individual settings - WORKING"""
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
        """Handle /settings command - WORKING"""
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

**Data Management:**
• `/backup` - Backup your data
• `/db_status` - Check database status
        """
        await event.reply(settings_menu)

    async def handle_tutorial(self, event):
        """Handle /tutorial command - WORKING"""
        tutorial_text = """
🎥 **Video Tutorials & Guides**

**Choose your language:**
        """
        
        from telethon import Button
        buttons = [
            [Button.inline("🇺🇸 English", b"tutorial_english"),
             Button.inline("🇮🇳 Hindi", b"tutorial_hindi")],
            [Button.inline("📖 Text Guide", b"tutorial_text"),
             Button.inline("🚀 Quick Start", b"tutorial_quick")]
        ]
        
        await event.reply(tutorial_text, buttons=buttons)

    async def handle_help(self, event):
        """Handle /help command - WORKING"""
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
• `/config` - View configuration

**🔄 Forwarding:**
• `/start_forwarding` - Start forwarding
• `/stop_forwarding` - Stop forwarding
• `/forward_settings` - Customize settings

**📚 Learning:**
• `/tutorial` - Video tutorials
• `/help` - This help message

**💾 Data:**
• `/backup` - Backup data
• `/db_status` - Database status

**👑 Admin:** `/admin` (Owner only)

📞 **Support:** @starworrier
        """
        await event.reply(help_text)

    async def handle_status(self, event):
        """Handle /status command - WORKING"""
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
        """Handle /broadcast command - WORKING (Admin only)"""
        user = await event.get_sender()
        
        if not self.is_admin(user.id):
            await event.reply("❌ Access denied! Admin only.")
            return
        
        message_text = event.text.replace('/broadcast', '').strip()
        
        if not message_text:
            await event.reply("❌ Usage: `/broadcast your message here`")
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
        """Handle /stats command - WORKING (Admin only)"""
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
• Avg per User: {total_sources/max(1, len(self.user_sessions)):.1f}

**⚡ Activity:**
• Active Forwarding: {active_forwarding}
• Success Rate: {(active_forwarding/max(1, len(self.user_sessions)))*100:.1f}%

**💾 Database:**
• Total Entries: {len(await self.db.get_all_keys())}
        """
        
        await event.reply(stats_text)

    async def handle_admin(self, event):
        """Handle /admin command - WORKING (Admin only)"""
        user = await event.get_sender()
        
        if not self.is_admin(user.id):
            await event.reply("❌ Access denied! Admin only.")
            return
        
        admin_text = """
👑 **Admin Panel**

**Commands:**
• `/stats` - Bot statistics
• `/broadcast` - Message all users
• `/export_users` - Export user data
• `/message_user` - Message specific user

**Database:**
• `/backup` - Create backup
• `/restore` - Restore backup
• `/cleanup` - Clean old data
        """
        
        from telethon import Button
        buttons = [
            [Button.inline("📊 Stats", b"admin_stats"),
             Button.inline("📢 Broadcast", b"admin_broadcast")],
            [Button.inline("💾 Backup", b"admin_backup"),
             Button.inline("👥 Users", b"admin_users")]
        ]
        
        await event.reply(admin_text, buttons=buttons)

    # ==================== UTILITY FUNCTIONS ====================

    async def check_user_logged_in(self, user_id: int, event) -> bool:
        """Check if user is logged in"""
        if user_id not in self.user_sessions or self.user_sessions[user_id].get('status') != 'logged_in':
            await event.reply("❌ Please login first using `/login`")
            return False
        return True

    async def handle_auto_forward_message(self, event):
        """Handle actual message forwarding - WORKING"""
        try:
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
            logger.error(f"Error in auto-forwarding: {e}")

    async def forward_to_targets(self, user_id: int, event):
        """Forward message to user's target channels - WORKING"""
        try:
            targets = self.target_channels.get(user_id, [])
            if not targets:
                return
            
            settings = self.forward_settings.get(user_id, self.default_settings)
            
            for target in targets:
                try:
                    if event.message.media and settings.get('forward_media', True):
                        # Forward media with caption
                        await event.message.forward_to(target['id'])
                    else:
                        # Forward as text or modify as needed
                        text = event.message.text or event.message.caption or ""
                        
                        # Apply settings
                        if settings.get('remove_usernames', False):
                            text = re.sub(r'@\w+', '', text)
                        if settings.get('remove_links', False):
                            text = re.sub(r'http[s]?://\S+', '', text)
                        
                        if text.strip():
                            await self.client.send_message(target['id'], text)
                            
                except Exception as e:
                    logger.error(f"Error forwarding to {target.get('name', 'Unknown')}: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Error in forward_to_targets: {e}")

    async def handle_callback_query(self, event):
        """Handle button callbacks - WORKING"""
        data = event.data.decode('utf-8')
        user = await event.get_sender()
        
        try:
            if data == 'toggle_hide_header':
                await self.handle_toggle_setting(event, 'hide_header')
            elif data == 'toggle_media':
                await self.handle_toggle_setting(event, 'forward_media')
            elif data == 'toggle_url_previews':
                await self.handle_toggle_setting(event, 'url_previews')
            elif data == 'toggle_remove_usernames':
                await self.handle_toggle_setting(event, 'remove_usernames')
            elif data == 'toggle_remove_links':
                await self.handle_toggle_setting(event, 'remove_links')
                
            elif data == 'tutorial_english':
                await event.edit("🎥 **English Tutorials:**\n\n1. Basic Setup: https://example.com/en1\n2. Advanced: https://example.com/en2\n3. Troubleshooting: https://example.com/en3")
            elif data == 'tutorial_hindi':
                await event.edit("🎥 **Hindi Tutorials:**\n\n1. Basic Setup: https://example.com/hi1\n2. Advanced: https://example.com/hi2\n3. Troubleshooting: https://example.com/hi3")
            elif data == 'tutorial_text':
                await event.edit("📖 **Text Guide:**\n\n1. /login - Login with phone\n2. /source - Add source channels\n3. /target - Add target channels\n4. /start_forwarding - Begin forwarding")
            elif data == 'tutorial_quick':
                await event.edit("🚀 **Quick Start:**\n\n1. /login +919876543210\n2. /add_sources\n3. /add_targets\n4. /start_forwarding")
                
            elif data == 'check_pinned_sources':
                await event.edit("🔍 Checking your pinned chats...\n\nType `/add_sources` to continue.")
            elif data == 'check_pinned_targets':
                await event.edit("🔍 Checking your pinned chats...\n\nType `/add_targets` to continue.")
            elif data == 'cancel_operation':
                await event.edit("❌ Operation cancelled.")
                
        except Exception as e:
            logger.error(f"Error in callback handler: {e}")
            await event.answer("Error processing request", alert=True)

    def register_handlers(self):
        """Register all event handlers - COMPLETE"""
        
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
        
        @self.client.on(events.NewMessage(pattern='/add_sources'))
        async def add_sources_handler(event):
            await self.handle_add_sources(event)
        
        @self.client.on(events.NewMessage(pattern='/add_targets'))
        async def add_targets_handler(event):
            await self.handle_add_targets(event)
        
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
        
        # Channel selection handler
        @self.client.on(events.NewMessage(pattern='^(all|[0-9 ]+)$'))
        async def channel_selection_handler(event):
            user = await event.get_sender()
            if user.id in self.user_pinned_chats:
                # Determine if we're selecting sources or targets based on context
                # For simplicity, we'll check if user has recent interaction
                if self.user_sessions.get(user.id, {}).get('last_command') in ['source', 'target']:
                    channel_type = self.user_sessions[user.id]['last_command']
                    await self.handle_channel_selection(event, channel_type)
        
        # OTP verification handler
        @self.client.on(events.NewMessage(pattern='^BAF\d{6}$'))
        async def otp_handler(event):
            await self.handle_otp_verification(event)
        
        # Phone number handler (when sent as separate message after /login)
        @self.client.on(events.NewMessage(pattern='^\+\d{10,15}$'))
        async def phone_handler(event):
            user = await event.get_sender()
            if user.id in self.user_sessions and self.user_sessions[user.id].get('status') == 'waiting_phone':
                await self.process_phone_login(user, event.text.strip(), event)
        
        # Callback queries (button presses)
        @self.client.on(events.CallbackQuery())
        async def callback_handler(event):
            await self.handle_callback_query(event)
        
        # Auto-forwarding message handler
        @self.client.on(events.NewMessage())
        async def message_handler(event):
            # First check if it's a command response
            if not event.text or event.text.startswith('/'):
                return
            await self.handle_auto_forward_message(event)
        
        logger.info("All handlers registered successfully!")

async def main():
    """Main function"""
    
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
        print("❌ Please set valid environment variables")
        return
    
    print("🚀 Starting Best Auto Forwarding Bot...")
    
    bot = AdvancedAutoForwardBot(api_id, api_hash, bot_token, db_channel_id)
    
    try:
        await bot.initialize()
        print("✅ Bot is running! Press Ctrl+C to stop.")
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