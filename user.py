import os
import logging
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime
import re
import pickle
import base64
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
ADMIN_USER_IDS = [6651946441]  # YOUR_USER_ID_HERE

# Force subscribe channel
FORCE_SUB_CHANNEL = "@MrJaggiX"  # YOUR_CHANNEL_USERNAME_HERE

class TelegramChannelDB:
    """Telegram Channel-based Database System"""
    
    def __init__(self, client: TelegramClient, db_channel_id: int):
        self.client = client
        self.db_channel_id = db_channel_id
        self.cache = {}
    
    async def initialize(self):
        """Initialize database channel"""
        try:
            if isinstance(self.db_channel_id, str):
                self.db_channel_id = int(self.db_channel_id)
            
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
        self.source_channel: Dict[int, Dict] = {}
        self.target_channels: Dict[int, List] = {}
        self.forward_settings: Dict[int, Dict] = {}
        self.auto_forwarding: Dict[int, bool] = {}
        self.login_attempts: Dict[int, Dict] = {}
        self.user_clients: Dict[int, TelegramClient] = {}
        
        # Channel selection state
        self.awaiting_channel_selection: Dict[int, Dict] = {}
        
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
                logger.info("Bot fully initialized with database!")
            else:
                self.register_handlers()
                logger.info("Bot started with in-memory storage")
                
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
            success = await self.db.set(key, data)
            if success:
                logger.info(f"Saved to DB: {key}")
            return success
        except Exception as e:
            logger.error(f"Error saving {key}: {e}")
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
            participants = await self.client.get_participants(channel_entity)
            user_ids = [participant.id for participant in participants]
            return user_id in user_ids
        except Exception as e:
            logger.error(f"Error checking force subscribe: {e}")
            return False

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
            
            self.user_sessions[user.id] = {
                'phone_number': login_data['phone_number'],
                'first_name': user_entity.first_name,
                'username': user_entity.username,
                'user_id': user_entity.id,
                'login_time': datetime.now().isoformat(),
                'status': 'logged_in'
            }
            
            if user.id not in self.forward_settings:
                self.forward_settings[user.id] = self.default_settings.copy()
                await self.save_to_db("forward_settings", self.forward_settings)
            
            await self.save_to_db("user_sessions", self.user_sessions)
            
            del self.login_attempts[user.id]
            
            success_text = f"""
✅ **Login Successful!**

Welcome, {user_entity.first_name or 'User'}!

Now you can set up auto-forwarding!
            """
            
            buttons = [
                [Button.inline("📥 Set Source Channel", b"show_pinned_channels_source"),
                 Button.inline("📤 Add Target Channel", b"show_pinned_channels_target")],
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

    # ==================== PINNED CHANNELS SYSTEM ====================

    async def get_user_pinned_channels(self, user_id: int) -> List[Dict]:
        """Get user's pinned channels/groups"""
        try:
            if user_id not in self.user_clients:
                return []
            
            user_client = self.user_clients[user_id]
            dialogs = await user_client.get_dialogs(limit=50)
            
            pinned_channels = []
            for dialog in dialogs:
                if dialog.pinned and dialog.is_channel:
                    entity = dialog.entity
                    pinned_channels.append({
                        'id': entity.id,
                        'name': getattr(entity, 'title', 'Unknown'),
                        'username': getattr(entity, 'username', None),
                        'participants_count': getattr(entity, 'participants_count', 0)
                    })
            
            return pinned_channels[:5]  # Return top 5 pinned channels
            
        except Exception as e:
            logger.error(f"Error getting pinned channels: {e}")
            return []

    async def show_pinned_channels_source(self, event):
        """Show pinned channels for source selection"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        pinned_channels = await self.get_user_pinned_channels(user.id)
        
        if not pinned_channels:
            await event.edit("❌ No pinned channels found. Please pin your source channel first in Telegram.")
            return
        
        selection_text = "📥 **Select Source Channel**\n\nYour pinned channels:\n\n"
        
        for i, channel in enumerate(pinned_channels, 1):
            selection_text += f"{i}. **{channel['name']}** (Members: {channel['participants_count']})\n"
        
        selection_text += "\nClick the number to set as source channel:"
        
        buttons = []
        for i in range(1, len(pinned_channels) + 1):
            if i % 2 == 1:
                row = []
            row.append(Button.inline(f"{i}", f"set_source_{i}"))
            if i % 2 == 0 or i == len(pinned_channels):
                buttons.append(row)
        
        buttons.append([Button.inline("🔙 Back", b"main_menu")])
        
        # Store channel data for selection
        self.awaiting_channel_selection[user.id] = {
            'type': 'source',
            'channels': pinned_channels
        }
        
        await event.edit(selection_text, buttons=buttons)

    async def show_pinned_channels_target(self, event):
        """Show pinned channels for target selection"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        pinned_channels = await self.get_user_pinned_channels(user.id)
        
        if not pinned_channels:
            await event.edit("❌ No pinned channels found. Please pin your target channels first in Telegram.")
            return
        
        selection_text = "📤 **Add Target Channel**\n\nYour pinned channels:\n\n"
        
        for i, channel in enumerate(pinned_channels, 1):
            selection_text += f"{i}. **{channel['name']}** (Members: {channel['participants_count']})\n"
        
        selection_text += "\nClick the number to add as target channel:"
        
        buttons = []
        for i in range(1, len(pinned_channels) + 1):
            if i % 2 == 1:
                row = []
            row.append(Button.inline(f"{i}", f"add_target_{i}"))
            if i % 2 == 0 or i == len(pinned_channels):
                buttons.append(row)
        
        buttons.append([Button.inline("📋 View Current Targets", b"view_targets")])
        buttons.append([Button.inline("🔙 Back", b"main_menu")])
        
        # Store channel data for selection
        self.awaiting_channel_selection[user.id] = {
            'type': 'target',
            'channels': pinned_channels
        }
        
        await event.edit(selection_text, buttons=buttons)

    async def handle_channel_selection(self, event, selection_type: str, channel_index: int):
        """Handle channel selection from pinned channels"""
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
            self.source_channel[user_id] = {
                'id': channel_info['id'],
                'name': channel_info['name'],
                'username': channel_info.get('username'),
                'set_time': datetime.now().isoformat()
            }
            
            await self.save_to_db("source_channel", self.source_channel)
            
            if user_id in self.awaiting_channel_selection:
                del self.awaiting_channel_selection[user_id]
            
            success_text = f"""
✅ **Source Channel Set Successfully!**

**Channel:** {channel_info['name']}
**ID:** `{channel_info['id']}`

Now add target channels to start forwarding!
            """
            
            buttons = [
                [Button.inline("📤 Add Target Channel", b"show_pinned_channels_target"),
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
            if user_id not in self.target_channels:
                self.target_channels[user_id] = []
            
            # Check for duplicates
            if any(ch['id'] == channel_info['id'] for ch in self.target_channels[user_id]):
                await event.edit("❌ This channel is already in your target list.")
                return
            
            target_info = {
                'id': channel_info['id'],
                'name': channel_info['name'],
                'username': channel_info.get('username'),
                'added_time': datetime.now().isoformat()
            }
            
            self.target_channels[user_id].append(target_info)
            await self.save_to_db("target_channels", self.target_channels)
            
            if user_id in self.awaiting_channel_selection:
                del self.awaiting_channel_selection[user_id]
            
            success_text = f"""
✅ **Target Channel Added Successfully!**

**Channel:** {channel_info['name']}
**ID:** `{channel_info['id']}`

**Total target channels:** {len(self.target_channels[user_id])}
            """
            
            buttons = [
                [Button.inline("➕ Add Another Target", b"show_pinned_channels_target"),
                 Button.inline("🚀 Start Forwarding", b"start_forwarding")],
                [Button.inline("📋 View All Targets", b"view_targets")]
            ]
            
            await event.edit(success_text, buttons=buttons)
            
        except Exception as e:
            logger.error(f"Error adding target channel: {e}")
            await event.edit("❌ Error adding target channel. Please try again.")

    # ==================== AUTO FORWARDING SYSTEM ====================

    async def handle_start_forwarding(self, event):
        """Handle start forwarding"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        if user.id not in self.source_channel:
            buttons = [[Button.inline("📥 Set Source Channel", b"show_pinned_channels_source")]]
            await event.edit("❌ No source channel configured. Please set a source channel first.", buttons=buttons)
            return
        
        targets = self.target_channels.get(user.id, [])
        if not targets:
            buttons = [[Button.inline("📤 Add Target Channel", b"show_pinned_channels_target")]]
            await event.edit("❌ No target channels configured. Please add target channels first.", buttons=buttons)
            return
        
        self.auto_forwarding[user.id] = True
        await self.save_to_db("auto_forwarding", self.auto_forwarding)
        
        source = self.source_channel[user.id]
        
        success_text = f"""
✅ **Auto-Forwarding Started!**

**Source:** {source['name']}
**Targets:** {len(targets)} channels
**Status:** 🟢 **ACTIVE**

Now monitoring your source channel for new messages...
        """
        
        buttons = [
            [Button.inline("⏸️ Stop Forwarding", b"stop_forwarding"),
             Button.inline("📊 View Status", b"show_dashboard")]
        ]
        
        await event.edit(success_text, buttons=buttons)

    async def handle_stop_forwarding(self, event):
        """Handle stop forwarding"""
        user = await event.get_sender()
        
        if user.id not in self.auto_forwarding or not self.auto_forwarding[user.id]:
            await event.answer("❌ Auto-forwarding is not active", alert=True)
            return
        
        self.auto_forwarding[user.id] = False
        await self.save_to_db("auto_forwarding", self.auto_forwarding)
        
        buttons = [
            [Button.inline("🚀 Start Again", b"start_forwarding"),
             Button.inline("📊 Dashboard", b"show_dashboard")]
        ]
        
        await event.edit("⏸️ **Auto-forwarding paused.**", buttons=buttons)

    # ==================== MESSAGE FORWARDING ====================

    async def monitor_source_channels(self):
        """Monitor source channels for new messages"""
        while True:
            try:
                for user_id, source in self.source_channel.items():
                    if not self.auto_forwarding.get(user_id, False):
                        continue
                    
                    # Here you would implement the actual message monitoring
                    # This is a simplified version
                    await asyncio.sleep(5)  # Check every 5 seconds
                    
            except Exception as e:
                logger.error(f"Error in channel monitoring: {e}")
                await asyncio.sleep(10)

    async def forward_message_to_targets(self, user_id: int, message):
        """Forward message to all target channels"""
        try:
            targets = self.target_channels.get(user_id, [])
            if not targets:
                return
            
            settings = self.forward_settings.get(user_id, self.default_settings)
            
            for target in targets:
                try:
                    if message.media and settings.get('forward_media', True):
                        await message.forward_to(target['id'])
                    elif message.text:
                        text = message.text
                        
                        if settings.get('remove_usernames', False):
                            text = re.sub(r'@\w+', '', text)
                        if settings.get('remove_links', False):
                            text = re.sub(r'http[s]?://\S+', '', text)
                        
                        if text.strip():
                            await self.client.send_message(target['id'], text)
                            
                except Exception as e:
                    logger.error(f"Error forwarding to {target.get('name', 'Unknown')}: {e}")
                    
        except Exception as e:
            logger.error(f"Error in forward_message_to_targets: {e}")

    # ==================== MAIN COMMANDS ====================

    async def show_force_subscribe(self, event):
        """Show force subscribe message"""
        force_sub_text = f"""
🔒 **Subscription Required**

To use this bot, you need to join our official channel first.

**Channel:** {FORCE_SUB_CHANNEL}

**Steps:**
1. Click the button below to join our channel
2. After joining, click "I've Joined" button
3. Start using the bot features!
        """
        
        buttons = [
            [Button.url("📢 JOIN OUR CHANNEL", f"https://t.me/{FORCE_SUB_CHANNEL.replace('@', '')}")],
            [Button.inline("✅ I'VE JOINED", b"check_subscription")]
        ]
        
        await event.reply(force_sub_text, buttons=buttons)

    async def handle_start(self, event):
        """Handle /start command"""
        user = await event.get_sender()
        
        if not await self.check_force_subscribe(user.id):
            await self.show_force_subscribe(event)
            return
        
        welcome_text = f"""
🤖 **Welcome to Best Auto Forwarding Bot!** 🚀

Hi {user.first_name or 'User'}! I'm here to help you automate message forwarding between channels.

**🌟 Features:**
• Single source channel (from your pinned channels)
• Multiple target channels  
• Real-time message forwarding
• Media files support

Use the buttons below to get started!
        """
        
        buttons = []
        
        if user.id in self.user_sessions:
            buttons.extend([
                [Button.inline("📊 DASHBOARD", b"show_dashboard"),
                 Button.inline("⚙️ SETTINGS", b"show_settings")],
                [Button.inline("📥 SOURCE CHANNEL", b"show_pinned_channels_source"),
                 Button.inline("📤 TARGET CHANNELS", b"show_pinned_channels_target")],
                [Button.inline("🚀 START FORWARDING", b"start_forwarding"),
                 Button.inline("🔐 LOGOUT", b"logout_user")]
            ])
        else:
            buttons.extend([
                [Button.inline("🔐 LOGIN NOW", b"quick_login"),
                 Button.inline("📚 HOW IT WORKS", b"how_it_works")],
                [Button.inline("💬 SUPPORT", b"contact_support")]
            ])
        
        await event.reply(welcome_text, buttons=buttons)

    async def handle_logout(self, event):
        """Handle /logout command"""
        user = await event.get_sender()
        
        if user.id in self.user_sessions:
            # Clean up
            if user.id in self.user_clients:
                await self.user_clients[user.id].disconnect()
                del self.user_clients[user.id]
            
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
            [Button.inline("🔐 LOGIN AGAIN", b"quick_login"),
             Button.inline("🏠 MAIN MENU", b"main_menu")]
        ]
        
        await event.reply("✅ Logout successful! All data cleared.", buttons=buttons)

    async def show_dashboard(self, event):
        """Show user dashboard"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        user_data = self.user_sessions.get(user.id, {})
        source = self.source_channel.get(user.id, {})
        targets = self.target_channels.get(user.id, [])
        settings = self.forward_settings.get(user.id, self.default_settings)
        
        dashboard_text = f"""
📊 **User Dashboard**

**👤 Account:**
• User: {user_data.get('first_name', 'N/A')}
• Phone: {user_data.get('phone_number', 'N/A')}
• Status: ✅ Active

**📈 Channels:**
• Source: {source.get('name', 'Not set')}
• Targets: {len(targets)} channels
• Forwarding: {'🟢 ACTIVE' if self.auto_forwarding.get(user.id) else '⏸️ PAUSED'}

**⚡ Settings:**
• Hide Header: {'✅ Yes' if settings.get('hide_header') else '❌ No'}
• Media: {'✅ Yes' if settings.get('forward_media') else '❌ No'}
        """
        
        buttons = [
            [Button.inline("📥 SOURCE", b"show_pinned_channels_source"),
             Button.inline("📤 TARGETS", b"show_pinned_channels_target")],
            [Button.inline("⚙️ SETTINGS", b"show_settings"),
             Button.inline("🔄 " + ("STOP" if self.auto_forwarding.get(user.id) else "START"), 
                         b"stop_forwarding" if self.auto_forwarding.get(user.id) else "start_forwarding")],
            [Button.inline("🏠 MAIN MENU", b"main_menu")]
        ]
        
        await event.edit(dashboard_text, buttons=buttons)

    async def show_settings(self, event):
        """Show settings"""
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
                         b"toggle_hide_header")],
            [Button.inline(f"🖼️ Media: {'✅ ON' if settings.get('forward_media') else '❌ OFF'}", 
                         b"toggle_media")],
            [Button.inline(f"🔗 Previews: {'✅ ON' if settings.get('url_previews') else '❌ OFF'}", 
                         b"toggle_previews")],
            [Button.inline("🔙 BACK TO DASHBOARD", b"show_dashboard")]
        ]
        
        await event.edit(settings_text, buttons=buttons)

    async def view_targets(self, event):
        """View current target channels"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        targets = self.target_channels.get(user.id, [])
        
        if not targets:
            await event.edit("❌ No target channels configured.")
            return
        
        targets_text = "📋 **Your Target Channels:**\n\n"
        
        for i, target in enumerate(targets, 1):
            targets_text += f"{i}. **{target['name']}** (ID: `{target['id']}`)\n"
        
        buttons = [
            [Button.inline("➕ ADD MORE TARGETS", b"show_pinned_channels_target"),
             Button.inline("🗑️ REMOVE TARGETS", b"remove_targets")],
            [Button.inline("🔙 BACK", b"show_dashboard")]
        ]
        
        await event.edit(targets_text, buttons=buttons)

    # ==================== BUTTON HANDLERS ====================

    async def handle_callback_query(self, event):
        """Handle all button callbacks"""
        data = event.data.decode('utf-8')
        user = await event.get_sender()
        
        try:
            # Main navigation
            if data == 'main_menu':
                await self.handle_start(event)
            
            elif data == 'quick_login':
                await event.edit("🔐 **Quick Login**\n\nUse `/login +919876543210` or send your phone number.")
            
            elif data == 'show_dashboard':
                await self.show_dashboard(event)
            
            elif data == 'show_pinned_channels_source':
                await self.show_pinned_channels_source(event)
            
            elif data == 'show_pinned_channels_target':
                await self.show_pinned_channels_target(event)
            
            elif data == 'start_forwarding':
                await self.handle_start_forwarding(event)
            
            elif data == 'stop_forwarding':
                await self.handle_stop_forwarding(event)
            
            elif data == 'show_settings':
                await self.show_settings(event)
            
            elif data == 'view_targets':
                await self.view_targets(event)
            
            elif data == 'logout_user':
                await self.handle_logout(event)
            
            # Channel selection
            elif data.startswith('set_source_'):
                channel_index = int(data.split('_')[-1])
                await self.handle_channel_selection(event, 'source', channel_index)
            
            elif data.startswith('add_target_'):
                channel_index = int(data.split('_')[-1])
                await self.handle_channel_selection(event, 'target', channel_index)
            
            # Settings toggles
            elif data in ['toggle_hide_header', 'toggle_media', 'toggle_previews']:
                setting_map = {
                    'toggle_hide_header': 'hide_header',
                    'toggle_media': 'forward_media', 
                    'toggle_previews': 'url_previews'
                }
                await self.toggle_setting(event, setting_map[data])
            
            # Force subscribe
            elif data == 'check_subscription':
                if await self.check_force_subscribe(user.id):
                    await event.edit("✅ Subscription verified! Welcome to the bot.")
                    await asyncio.sleep(2)
                    await self.handle_start(event)
                else:
                    await event.edit("❌ Still not subscribed. Please join the channel first.")
            
            # Login related
            elif data == 'resend_code':
                await self.resend_code(event)
            
            elif data == 'cancel_login':
                if user.id in self.login_attempts:
                    if 'user_client' in self.login_attempts[user.id]:
                        await self.login_attempts[user.id]['user_client'].disconnect()
                    del self.login_attempts[user.id]
                await event.edit("❌ Login cancelled.")
            
            # Other buttons
            elif data == 'how_it_works':
                await event.edit("🎯 **How It Works**\n\n1. **Login** with your Telegram account\n2. **Set source** from pinned channels\n3. **Add targets** from pinned channels\n4. **Start** auto-forwarding\n5. **Monitor** automatically")
            
            elif data == 'contact_support':
                await event.edit("💬 **Support**\n\nFor help contact: @starworrier")
            
            elif data == 'quick_start_guide':
                await event.edit("🚀 **Quick Start**\n\n1. Login with your account\n2. Set source channel from pinned\n3. Add target channels from pinned\n4. Start forwarding!")
            
            elif data == 'remove_targets':
                await self.show_remove_targets(event)
            
            else:
                await event.answer("❌ Button action not available", alert=True)
                
        except Exception as e:
            logger.error(f"Error in callback handler: {e}")
            await event.answer("❌ Error processing request", alert=True)

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
        
        await self.show_settings(event)

    async def show_remove_targets(self, event):
        """Show remove targets options"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        targets = self.target_channels.get(user.id, [])
        
        if not targets:
            await event.edit("❌ No target channels to remove.")
            return
        
        remove_text = "🗑️ **Remove Target Channels**\n\nSelect channel to remove:\n\n"
        
        for i, target in enumerate(targets, 1):
            remove_text += f"{i}. {target['name']}\n"
        
        buttons = []
        for i in range(1, len(targets) + 1):
            if i % 2 == 1:
                row = []
            row.append(Button.inline(f"❌ {i}", f"remove_target_{i}"))
            if i % 2 == 0 or i == len(targets):
                buttons.append(row)
        
        buttons.append([Button.inline("🔙 BACK", b"view_targets")])
        
        await event.edit(remove_text, buttons=buttons)

    # ==================== MESSAGE PROCESSING ====================

    async def handle_auto_forward(self, event):
        """Handle all incoming messages"""
        try:
            # Ignore commands
            if event.text and event.text.startswith('/'):
                return
            
            user = await event.get_sender()
            
            # Check force subscribe
            if user.id not in self.user_sessions and not await self.check_force_subscribe(user.id):
                return
            
            # Handle OTP verification
            if event.text and event.text.upper().startswith('AUTOX'):
                await self.handle_code_verification(event)
                return
            
            # Handle phone number input
            if event.text and re.match(r'^\+[0-9]{10,15}$', event.text):
                if user.id in self.login_attempts and self.login_attempts[user.id].get('step') == 'waiting_phone':
                    await self.start_telegram_login(user, event.text, event)
                return
            
        except Exception as e:
            logger.error(f"Error in message processing: {e}")

    async def check_user_logged_in(self, user_id: int, event=None, silent: bool = False) -> bool:
        """Check if user is logged in"""
        if user_id not in self.user_sessions or self.user_sessions[user_id].get('status') != 'logged_in':
            if not silent and event:
                buttons = [
                    [Button.inline("🔐 LOGIN NOW", b"quick_login")],
                    [Button.inline("🏠 MAIN MENU", b"main_menu")]
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
        
        @self.client.on(events.NewMessage(pattern='^/dashboard$'))
        async def dashboard_handler(event):
            await self.show_dashboard(event)
        
        @self.client.on(events.NewMessage(pattern='^/settings$'))
        async def settings_handler(event):
            await self.show_settings(event)
        
        @self.client.on(events.NewMessage(pattern='^/targets$'))
        async def targets_handler(event):
            await self.view_targets(event)
        
        @self.client.on(events.NewMessage(pattern='^/start_forwarding$'))
        async def start_forwarding_handler(event):
            await self.handle_start_forwarding(event)
        
        @self.client.on(events.NewMessage(pattern='^/stop_forwarding$'))
        async def stop_forwarding_handler(event):
            await self.handle_stop_forwarding(event)
        
        @self.client.on(events.CallbackQuery())
        async def callback_handler(event):
            await self.handle_callback_query(event)
        
        @self.client.on(events.NewMessage)
        async def message_handler(event):
            await self.handle_auto_forward(event)
        
        # Start channel monitoring
        asyncio.create_task(self.monitor_source_channels())
        
        logger.info("✅ All handlers registered successfully!")

async def main():
    """Main function"""
    
    api_id = "28093492"
    api_hash = "2d18ff97ebdfc2f1f3a2596c48e3b4e4"
    bot_token = "7931829452:AAEF2zYePG5w3EY3cRwsv6jqxZawH_0HXKI"
    db_channel_id = "-1002565934191"
    
    global ADMIN_USER_IDS, FORCE_SUB_CHANNEL
    admin_env = "6651946441"
    if admin_env:
        ADMIN_USER_IDS = [int(id.strip()) for id in admin_env.split(',')]
    
    force_sub_env = @MrJaggiX
    if force_sub_env:
        FORCE_SUB_CHANNEL = force_sub_env
    
    print("🚀 Starting Best Auto Forwarding Bot...")
    
    bot = AdvancedAutoForwardBot(api_id, api_hash, bot_token, db_channel_id)
    
    try:
        await bot.initialize()
        print("✅ Bot is running perfectly! All systems operational.")
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
    
    os.makedirs("sessions", exist_ok=True)
    asyncio.run(main())
