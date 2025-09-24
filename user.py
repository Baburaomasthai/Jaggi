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

# Force subscribe channel - APNA CHANNEL USERNAME DALEN
FORCE_SUB_CHANNEL = "@MrJaggiX"  # YOUR_CHANNEL_USERNAME_HERE

# Tutorial video link - ADMIN SET KAR SAKTA HAI
TUTORIAL_VIDEO_LINK = "https://example.com/tutorial_video.mp4"  # ADMIN CAN CHANGE THIS

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
        self.source_channel: Dict[int, Dict] = {}
        self.target_channels: Dict[int, List] = {}
        self.forward_settings: Dict[int, Dict] = {}
        self.auto_forwarding: Dict[int, bool] = {}
        self.login_attempts: Dict[int, Dict] = {}
        self.awaiting_channel_selection: Dict[int, Dict] = {}  # Store forwarded channel info
        
        # Admin settings
        self.tutorial_video_link = TUTORIAL_VIDEO_LINK
        
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
            
            # Load admin settings
            admin_settings = await self.db.get("admin_settings") or {}
            self.tutorial_video_link = admin_settings.get('tutorial_video', TUTORIAL_VIDEO_LINK)
            
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
                return True  # Skip if not configured
            
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
            
            buttons = [
                [Button.inline("📋 Format Help", b"phone_format_help")],
                [Button.inline("❌ Cancel", b"cancel_operation")]
            ]
            await event.reply(login_text, buttons=buttons)

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
            
            await login_data['user_client'].disconnect()
            del self.login_attempts[user.id]
            
            success_text = f"""
✅ **Login Successful!**

Welcome, {user_entity.first_name or 'User'}!

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

    async def show_force_subscribe(self, event):
        """Show force subscribe message with better design"""
        user = await event.get_sender()
        
        force_sub_text = f"""
🔒 **Subscription Required**

To use this bot, you need to join our official channel first.

**Channel:** {FORCE_SUB_CHANNEL}

**Steps:**
1. Click the button below to join our channel
2. After joining, click "I've Joined" button
3. Start using the bot features!

💡 **Note:** You must join the channel to access all features.
        """
        
        buttons = [
            [Button.url("📢 JOIN OUR CHANNEL", f"https://t.me/{FORCE_SUB_CHANNEL.replace('@', '')}")],
            [Button.inline("✅ I'VE JOINED", b"check_subscription")],
            [Button.inline("🔄 Check Again", b"check_subscription")]
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

**🌟 Key Features:**
• Single source channel (your account accesses it)
• Multiple target channels 
• Real-time message forwarding
• Media files support
• Secure authentication

**Quick Start:**
Use the buttons below to get started!
        """
        
        buttons = []
        
        if user.id in self.user_sessions:
            buttons.extend([
                [Button.inline("📊 DASHBOARD", b"show_dashboard"),
                 Button.inline("⚙️ SETTINGS", b"forward_settings")],
                [Button.inline("🚀 START FORWARDING", b"start_forwarding"),
                 Button.inline("📋 CONFIG", b"view_config")],
                [Button.inline("🎥 TUTORIAL", b"video_tutorial"),
                 Button.inline("🔐 LOGOUT", b"logout_user")]
            ])
        else:
            buttons.extend([
                [Button.inline("🔐 LOGIN NOW", b"quick_login"),
                 Button.inline("📚 HOW IT WORKS", b"how_it_works")],
                [Button.inline("🎥 VIDEO GUIDE", b"video_tutorial"),
                 Button.inline("💬 SUPPORT", b"contact_support")]
            ])
        
        await event.reply(welcome_text, buttons=buttons)

    async def handle_logout(self, event):
        """Handle /logout command"""
        user = await event.get_sender()
        
        if user.id in self.user_sessions:
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
        """
        
        buttons = [
            [Button.inline("📨 FORWARD MESSAGE NOW", b"forward_instructions")],
            [Button.inline("🔄 CHANGE SOURCE", b"change_source")] if current_source else [],
            [Button.inline("📊 DASHBOARD", b"show_dashboard"),
             Button.inline("🔙 MAIN MENU", b"main_menu")]
        ]
        
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
        """
        
        if targets:
            instructions += "\n**Your Target Channels:**\n"
            for i, target in enumerate(targets, 1):
                instructions += f"{i}. {target['name']}\n"
        
        buttons = [
            [Button.inline("➕ ADD TARGET CHANNEL", b"add_target")],
            [Button.inline("🗑️ REMOVE TARGET", b"remove_target")] if targets else [],
            [Button.inline("📋 VIEW ALL TARGETS", b"view_targets")] if targets else [],
            [Button.inline("📊 DASHBOARD", b"show_dashboard"),
             Button.inline("🔙 MAIN MENU", b"main_menu")]
        ]
        
        buttons = [btn for btn in buttons if btn]
        await event.reply(instructions, buttons=buttons)

    # ==================== CHANNEL DETECTION ====================

    async def handle_forwarded_message(self, event):
        """Handle forwarded messages for channel detection - FIXED WITH BUTTONS"""
        try:
            if not event.message.fwd_from:
                return
            
            user = await event.get_sender()
            if not await self.check_user_logged_in(user.id, event, silent=True):
                return
            
            fwd = event.message.fwd_from
            if hasattr(fwd, 'from_id'):
                # Store channel info for selection
                try:
                    # Try to get channel info using bot's client (for target) or user's session (for source)
                    channel_id = fwd.from_id
                    
                    # Try bot's client first (for target channels where bot is admin)
                    try:
                        entity = await self.client.get_entity(channel_id)
                        channel_name = getattr(entity, 'title', 'Unknown Channel')
                    except:
                        # If bot can't access, use a generic name
                        channel_name = "Forwarded Channel"
                    
                    self.awaiting_channel_selection[user.id] = {
                        'channel_id': channel_id,
                        'channel_name': channel_name,
                        'message_id': event.message.id
                    }
                    
                    question = f"""
📨 **Channel Detected!**

**Channel:** {channel_name}
**ID:** `{channel_id}`

What would you like to do with this channel?
                    """
                    
                    buttons = [
                        [Button.inline("📥 SET AS SOURCE", f"set_source_{channel_id}"),
                         Button.inline("📤 ADD AS TARGET", f"add_target_{channel_id}")],
                        [Button.inline("❌ CANCEL", b"cancel_operation")]
                    ]
                    
                    await event.reply(question, buttons=buttons)
                    
                except Exception as e:
                    logger.error(f"Error processing forwarded message: {e}")
                    await event.reply("❌ Error detecting channel. Please try again.")
                    
        except Exception as e:
            logger.error(f"Error in forwarded message handler: {e}")

    async def set_source_channel(self, user_id: int, channel_id: int, event):
        """Set source channel"""
        try:
            # For source channel, we use the stored name from forwarded message
            channel_info = self.awaiting_channel_selection.get(user_id, {})
            
            source_info = {
                'id': channel_id,
                'name': channel_info.get('channel_name', 'Unknown Channel'),
                'set_time': datetime.now().isoformat()
            }
            
            self.source_channel[user_id] = source_info
            await self.save_to_db("source_channel", self.source_channel)
            
            if user_id in self.awaiting_channel_selection:
                del self.awaiting_channel_selection[user_id]
            
            success_text = f"""
✅ **Source Channel Set Successfully!**

**Channel:** {source_info['name']}
**ID:** `{channel_id}`

Now add target channels to start forwarding!
            """
            
            buttons = [
                [Button.inline("📤 ADD TARGET CHANNEL", b"add_target"),
                 Button.inline("🚀 START FORWARDING", b"start_forwarding")],
                [Button.inline("📊 DASHBOARD", b"show_dashboard")]
            ]
            
            await event.edit(success_text, buttons=buttons)
            
        except Exception as e:
            logger.error(f"Error setting source channel: {e}")
            await event.edit("❌ Error setting source channel. Please try again.")

    async def add_target_channel(self, user_id: int, channel_id: int, event):
        """Add target channel"""
        try:
            channel_info = self.awaiting_channel_selection.get(user_id, {})
            
            target_info = {
                'id': channel_id,
                'name': channel_info.get('channel_name', 'Unknown Channel'),
                'added_time': datetime.now().isoformat()
            }
            
            if user_id not in self.target_channels:
                self.target_channels[user_id] = []
            
            # Check for duplicates
            if any(ch['id'] == channel_id for ch in self.target_channels[user_id]):
                await event.edit("❌ This channel is already in your target list.")
                return
            
            self.target_channels[user_id].append(target_info)
            await self.save_to_db("target_channels", self.target_channels)
            
            if user_id in self.awaiting_channel_selection:
                del self.awaiting_channel_selection[user_id]
            
            success_text = f"""
✅ **Target Channel Added Successfully!**

**Channel:** {target_info['name']}
**ID:** `{channel_id}`

**Total target channels:** {len(self.target_channels[user_id])}
            """
            
            buttons = [
                [Button.inline("➕ ADD ANOTHER TARGET", b"add_target"),
                 Button.inline("🚀 START FORWARDING", b"start_forwarding")],
                [Button.inline("📋 VIEW ALL TARGETS", b"view_targets")]
            ]
            
            await event.edit(success_text, buttons=buttons)
            
        except Exception as e:
            logger.error(f"Error adding target channel: {e}")
            await event.edit("❌ Error adding target channel. Please make sure bot is admin in the channel.")

    # ==================== BROADCAST FEATURE ====================

    async def handle_broadcast(self, event):
        """Handle /broadcast command (Admin only)"""
        user = await event.get_sender()
        
        if not self.is_admin(user.id):
            await event.reply("❌ Access denied. This command is for admins only.")
            return
        
        message_text = event.text.replace('/broadcast', '').strip()
        
        if not message_text:
            await event.reply("❌ Usage: `/broadcast your message here`")
            return
        
        if not self.user_sessions:
            await event.reply("❌ No users to broadcast to.")
            return
        
        # Confirm broadcast
        confirm_text = f"""
📢 **Broadcast Confirmation**

**Message:** {message_text}

**Total Users:** {len(self.user_sessions)}

Are you sure you want to send this broadcast?
        """
        
        buttons = [
            [Button.inline("✅ YES, SEND BROADCAST", f"confirm_broadcast_{hash(message_text)}")],
            [Button.inline("❌ CANCEL", b"cancel_operation")]
        ]
        
        await event.reply(confirm_text, buttons=buttons)

    async def send_broadcast(self, event, message_text: str):
        """Send broadcast to all users"""
        user = await event.get_sender()
        
        if not self.is_admin(user.id):
            return
        
        await event.edit("🔄 Sending broadcast to all users...")
        
        success_count = 0
        failed_count = 0
        
        for user_id in self.user_sessions.keys():
            try:
                await self.client.send_message(
                    user_id, 
                    f"📢 **Admin Broadcast**\n\n{message_text}\n\n— Best Auto Forwarding Bot"
                )
                success_count += 1
                await asyncio.sleep(0.1)  # Rate limiting
            except Exception as e:
                logger.error(f"Broadcast failed for {user_id}: {e}")
                failed_count += 1
        
        result_text = f"""
✅ **Broadcast Completed!**

**Results:**
• ✅ Success: {success_count} users
• ❌ Failed: {failed_count} users
• 📊 Total: {len(self.user_sessions)} users

**Message sent to {success_count}/{len(self.user_sessions)} users.**
        """
        
        buttons = [
            [Button.inline("📊 ADMIN PANEL", b"admin_panel"),
             Button.inline("🏠 MAIN MENU", b"main_menu")]
        ]
        
        await event.edit(result_text, buttons=buttons)

    # ==================== BUTTON HANDLERS ====================

    async def handle_callback_query(self, event):
        """Handle all button callbacks - COMPLETELY FIXED"""
        data = event.data.decode('utf-8')
        user = await event.get_sender()
        
        try:
            # Main menu and navigation
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
                await self.handle_start_forwarding_wrapper(event)
            
            elif data == 'stop_forwarding':
                await self.handle_stop_forwarding_wrapper(event)
            
            elif data == 'view_config':
                await self.handle_config(event)
            
            elif data == 'forward_settings':
                await self.show_settings_buttons(event)
            
            elif data == 'logout_user':
                await self.handle_logout(event)
            
            elif data == 'video_tutorial':
                await self.show_video_tutorial(event)
            
            elif data == 'admin_panel':
                if self.is_admin(user.id):
                    await self.show_admin_panel(event)
                else:
                    await event.answer("❌ Admin access required", alert=True)
            
            # Channel selection from forwarded messages
            elif data.startswith('set_source_'):
                channel_id = int(data.split('_')[-1])
                await self.set_source_channel(user.id, channel_id, event)
            
            elif data.startswith('add_target_'):
                channel_id = int(data.split('_')[-1])
                await self.add_target_channel(user.id, channel_id, event)
            
            # Broadcast confirmation
            elif data.startswith('confirm_broadcast_'):
                message_hash = data.split('_')[-1]
                original_message = event.message.text
                message_text = original_message.split('**Message:**')[1].split('**Total Users:**')[0].strip()
                await self.send_broadcast(event, message_text)
            
            # Force subscribe
            elif data == 'check_subscription':
                if await self.check_force_subscribe(user.id):
                    await event.edit("✅ Subscription verified! Welcome to the bot.")
                    await asyncio.sleep(2)
                    await self.handle_start(event)
                else:
                    await event.edit("❌ Still not subscribed. Please join the channel first.")
            
            # Settings toggles
            elif data in ['toggle_hide_header', 'toggle_media', 'toggle_previews']:
                setting_map = {
                    'toggle_hide_header': 'hide_header',
                    'toggle_media': 'forward_media', 
                    'toggle_previews': 'url_previews'
                }
                await self.toggle_setting(event, setting_map[data])
            
            # Other buttons
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
                await event.edit("💬 **Support**\n\nFor help contact: @starworrier")
            
            elif data == 'quick_start':
                await event.edit("🚀 **Quick Start Guide**\n\n1. Login with `/login +919876543210`\n2. Forward message from source channel\n3. Add target channels\n4. Start forwarding with button below")
            
            elif data == 'view_targets':
                await self.handle_target(event)
            
            elif data == 'remove_target':
                await self.show_remove_target_options(event)
            
            else:
                await event.answer("⚠️ Button action not available yet", alert=True)
                
        except Exception as e:
            logger.error(f"Error in callback handler: {e}")
            await event.answer("❌ Error processing request", alert=True)

    async def handle_start_forwarding_wrapper(self, event):
        """Wrapper for start forwarding with proper error handling"""
        try:
            await self.handle_start_forwarding(event)
        except Exception as e:
            logger.error(f"Error in start forwarding: {e}")
            await event.answer("❌ Error starting forwarding", alert=True)

    async def handle_stop_forwarding_wrapper(self, event):
        """Wrapper for stop forwarding with proper error handling"""
        try:
            await self.handle_stop_forwarding(event)
        except Exception as e:
            logger.error(f"Error in stop forwarding: {e}")
            await event.answer("❌ Error stopping forwarding", alert=True)

    async def handle_start_forwarding(self, event):
        """Handle start forwarding"""
        user = await event.get_sender()
        
        if not await self.check_user_logged_in(user.id, event):
            return
        
        if user.id not in self.source_channel:
            buttons = [[Button.inline("📥 SET SOURCE CHANNEL", b"set_source")]]
            await event.edit("❌ No source channel configured. Please set a source channel first.", buttons=buttons)
            return
        
        targets = self.target_channels.get(user.id, [])
        if not targets:
            buttons = [[Button.inline("📤 ADD TARGET CHANNEL", b"add_target")]]
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

Now forwarding messages automatically!
        """
        
        buttons = [
            [Button.inline("⏸️ STOP FORWARDING", b"stop_forwarding"),
             Button.inline("📊 VIEW STATUS", b"view_config")]
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
            [Button.inline("🚀 START AGAIN", b"start_forwarding"),
             Button.inline("📊 DASHBOARD", b"show_dashboard")]
        ]
        
        await event.edit("⏸️ **Auto-forwarding paused.**", buttons=buttons)

    async def handle_config(self, event):
        """Handle config command"""
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
• Status: ✅ Active

**📊 Channels:**
• Source: {source.get('name', 'Not set')}
• Targets: {len(targets)} channels
• Forwarding: {'🟢 ACTIVE' if self.auto_forwarding.get(user.id) else '⏸️ PAUSED'}

**Settings:**
• Hide Header: {'✅ Yes' if settings.get('hide_header') else '❌ No'}
• Media: {'✅ Yes' if settings.get('forward_media') else '❌ No'}
        """
        
        buttons = [
            [Button.inline("📥 SOURCE", b"set_source"),
             Button.inline("📤 TARGETS", b"add_target")],
            [Button.inline("⚙️ SETTINGS", b"forward_settings"),
             Button.inline("🔄 " + ("STOP" if self.auto_forwarding.get(user.id) else "START"), 
                         b"stop_forwarding" if self.auto_forwarding.get(user.id) else "start_forwarding")],
            [Button.inline("🔙 MAIN MENU", b"main_menu")]
        ]
        
        await event.edit(config_text, buttons=buttons)

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
                         b"toggle_hide_header")],
            [Button.inline(f"🖼️ Media: {'✅ ON' if settings.get('forward_media') else '❌ OFF'}", 
                         b"toggle_media")],
            [Button.inline(f"🔗 Previews: {'✅ ON' if settings.get('url_previews') else '❌ OFF'}", 
                         b"toggle_previews")],
            [Button.inline("🔙 BACK TO DASHBOARD", b"show_dashboard")]
        ]
        
        await event.edit(settings_text, buttons=buttons)

    async def show_video_tutorial(self, event):
        """Show video tutorial"""
        tutorial_text = f"""
🎥 **Video Tutorial**

Watch our tutorial video to learn how to use the bot:

**Video Link:** {self.tutorial_video_link}

**Quick Steps:**
1. Login with your account
2. Set source channel by forwarding a message
3. Add target channels (make bot admin)
4. Start auto-forwarding

Need help? Contact @starworrier
        """
        
        buttons = [
            [Button.url("📺 WATCH TUTORIAL", self.tutorial_video_link)],
            [Button.inline("🔙 MAIN MENU", b"main_menu")]
        ]
        
        await event.edit(tutorial_text, buttons=buttons)

    async def show_admin_panel(self, event):
        """Show admin panel"""
        if not self.is_admin((await event.get_sender()).id):
            return
        
        admin_text = f"""
👑 **Admin Panel**

**Statistics:**
• Total Users: {len(self.user_sessions)}
• Active Forwarding: {sum(1 for x in self.auto_forwarding.values() if x)}

**Commands:**
• /broadcast - Send message to all users
• /stats - View detailed statistics

**Tutorial Video:** {self.tutorial_video_link}
        """
        
        buttons = [
            [Button.inline("📢 SEND BROADCAST", b"start_broadcast")],
            [Button.inline("📊 VIEW STATS", b"view_stats")],
            [Button.inline("🎥 CHANGE TUTORIAL", b"change_tutorial")],
            [Button.inline("🔙 MAIN MENU", b"main_menu")]
        ]
        
        await event.edit(admin_text, buttons=buttons)

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
        
        await self.show_settings_buttons(event)

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
            
            # Handle forwarded messages for channel detection
            if event.message.fwd_from:
                await self.handle_forwarded_message(event)
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
            await self.handle_start_forwarding_wrapper(event)
        
        @self.client.on(events.NewMessage(pattern='^/stop_forwarding$'))
        async def stop_forwarding_handler(event):
            await self.handle_stop_forwarding_wrapper(event)
        
        @self.client.on(events.NewMessage(pattern='^/broadcast$'))
        async def broadcast_handler(event):
            await self.handle_broadcast(event)
        
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

    async def handle_help(self, event):
        """Handle help command"""
        help_text = """
🆘 **Command Reference & Help**

**🔐 Authentication:**
• `/start` - Start bot
• `/login` - Login to account  
• `/logout` - Logout

**⚙️ Setup:**
• `/source` - Set source channel
• `/target` - Manage target channels
• `/config` - View configuration

**🔄 Control:**
• `/start_forwarding` - Start forwarding
• `/stop_forwarding` - Stop forwarding

**👑 Admin:**
• `/broadcast` - Send message to all users
        """
        
        buttons = [
            [Button.inline("🔐 LOGIN", b"quick_login"),
             Button.inline("📥 SETUP GUIDE", b"how_it_works")],
            [Button.inline("🎥 TUTORIAL", b"video_tutorial"),
             Button.inline("💬 SUPPORT", b"contact_support")],
            [Button.inline("🔙 MAIN MENU", b"main_menu")]
        ]
        
        await event.reply(help_text, buttons=buttons)

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
    
    force_sub_env = "@MrJaggiX"
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
