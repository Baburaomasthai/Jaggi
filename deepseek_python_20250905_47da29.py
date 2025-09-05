import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
import sqlite3
import uuid
import re
from datetime import datetime, timedelta
import asyncio
import aiohttp

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot token from BotFather
TOKEN = "8379945498:AAGtfGofVnPnoN8K_ayirg4-ifdeBgooLSk"

# Add your user ID as moderator (replace with your actual user ID)
MODERATOR_IDS = [6651946441]  # Add your user ID here

# Database setup
def init_db():
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        is_banned INTEGER DEFAULT 0,
        joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Messages table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS messages (
        message_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        message_type TEXT,
        content TEXT,
        file_id TEXT,
        file_name TEXT,
        file_size INTEGER,
        link_code TEXT UNIQUE,
        protect_content INTEGER DEFAULT 0,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )
    ''')
    
    # Folders table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS folders (
        folder_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        folder_code TEXT UNIQUE,
        protect_content INTEGER DEFAULT 0,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )
    ''')
    
    # Folder items table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS folder_items (
        item_id INTEGER PRIMARY KEY AUTOINCREMENT,
        folder_id INTEGER,
        message_type TEXT,
        content TEXT,
        file_id TEXT,
        file_name TEXT,
        file_size INTEGER,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (folder_id) REFERENCES folders (folder_id)
    )
    ''')
    
    # Settings table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS settings (
        user_id INTEGER PRIMARY KEY,
        custom_caption TEXT DEFAULT '',
        protect_content INTEGER DEFAULT 0,
        auto_delete INTEGER DEFAULT 0,
        auto_delete_time INTEGER DEFAULT 15,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )
    ''')
    
    # Force sub channels table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS force_sub (
        channel_id INTEGER PRIMARY KEY,
        channel_username TEXT,
        added_by INTEGER,
        added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (added_by) REFERENCES users (user_id)
    )
    ''')
    
    # Add moderators
    for mod_id in MODERATOR_IDS:
        cursor.execute('INSERT OR IGNORE INTO users (user_id) VALUES (?)', (mod_id,))
        cursor.execute('INSERT OR IGNORE INTO settings (user_id) VALUES (?)', (mod_id,))
    
    conn.commit()
    conn.close()

# Add user to database
def add_user(user_id, username, first_name, last_name):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute(
        'INSERT OR IGNORE INTO users (user_id, username, first_name, last_name) VALUES (?, ?, ?, ?)',
        (user_id, username, first_name, last_name)
    )
    # Initialize settings for new user
    cursor.execute(
        'INSERT OR IGNORE INTO settings (user_id) VALUES (?)',
        (user_id,)
    )
    conn.commit()
    conn.close()

# Check if user is moderator
def is_moderator(user_id):
    return user_id in MODERATOR_IDS

# Check if user is banned
def is_banned(user_id):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('SELECT is_banned FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result and result[0] == 1

# Get user settings
def get_user_settings(user_id):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('SELECT custom_caption, protect_content, auto_delete, auto_delete_time FROM settings WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return {
            'custom_caption': result[0] or '',
            'protect_content': result[1],
            'auto_delete': result[2],
            'auto_delete_time': result[3]
        }
    return None

# Update user settings
def update_user_settings(user_id, setting, value):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute(f'UPDATE settings SET {setting} = ? WHERE user_id = ?', (value, user_id))
    conn.commit()
    conn.close()

# Get force sub channels
def get_force_sub_channels():
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('SELECT channel_id, channel_username FROM force_sub')
    result = cursor.fetchall()
    conn.close()
    return result

# Add force sub channel
def add_force_sub_channel(channel_id, channel_username, added_by):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute(
        'INSERT OR REPLACE INTO force_sub (channel_id, channel_username, added_by) VALUES (?, ?, ?)',
        (channel_id, channel_username, added_by)
    )
    conn.commit()
    conn.close()

# Remove force sub channel
def remove_force_sub_channel(channel_id):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM force_sub WHERE channel_id = ?', (channel_id,))
    conn.commit()
    conn.close()

# Shorten URL using TinyURL API
async def shorten_url(url):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f'http://tinyurl.com/api-create.php?url={url}') as response:
                if response.status == 200:
                    return await response.text()
                else:
                    return None
    except Exception as e:
        logger.error(f"Error shortening URL: {e}")
        return None

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username, user.first_name, user.last_name)
    
    # Check if user has joined all force sub channels
    force_sub_channels = get_force_sub_channels()
    if force_sub_channels:
        not_joined = []
        for channel_id, channel_username in force_sub_channels:
            try:
                member = await context.bot.get_chat_member(channel_id, user.id)
                if member.status in ['left', 'kicked']:
                    not_joined.append(f"@{channel_username}")
            except Exception as e:
                logger.error(f"Error checking channel membership: {e}")
                not_joined.append(f"@{channel_username}")
        
        if not_joined:
            channels_text = "\n".join([f"• {channel}" for channel in not_joined])
            keyboard = [[InlineKeyboardButton("Join Channel", url=f"https://t.me/{channel_username}")] for _, channel_username in force_sub_channels]
            keyboard.append([InlineKeyboardButton("✅ I've Joined", callback_data="check_force_sub")])
            
            await update.message.reply_text(
                f"⚠️ Please join our channels to use this bot:\n{channels_text}\n\n"
                "After joining, click the button below:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
    
    keyboard = [
        ["Create Folder Link", "Shorten Link"],
        ["Settings", "Check Status"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    welcome_text = (
        f"Hello {user.first_name}! 👋\n\n"
        "I'm a powerful file storage bot with these features:\n\n"
        "• Create folder links from multiple files\n"
        "• Shorten URLs with /shortener\n"
        "• Customize settings with /settings\n"
    )
    
    if is_moderator(user.id):
        welcome_text += "\nModerator commands:\n• /broadcast\n• /ban\n• /unban"
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=reply_markup
    )

# Check force sub callback
async def check_force_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    force_sub_channels = get_force_sub_channels()
    
    if force_sub_channels:
        not_joined = []
        for channel_id, channel_username in force_sub_channels:
            try:
                member = await context.bot.get_chat_member(channel_id, user.id)
                if member.status in ['left', 'kicked']:
                    not_joined.append(f"@{channel_username}")
            except Exception as e:
                logger.error(f"Error checking channel membership: {e}")
                not_joined.append(f"@{channel_username}")
        
        if not_joined:
            channels_text = "\n".join([f"• {channel}" for channel in not_joined])
            keyboard = [[InlineKeyboardButton("Join Channel", url=f"https://t.me/{channel_username}")] for _, channel_username in force_sub_channels]
            keyboard.append([InlineKeyboardButton("✅ I've Joined", callback_data="check_force_sub")])
            
            await query.edit_message_text(
                f"❌ You haven't joined all channels yet:\n{channels_text}\n\n"
                "Please join all channels and try again:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
    
    # User has joined all channels
    keyboard = [
        ["Create Folder Link", "Shorten Link"],
        ["Settings", "Check Status"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await query.edit_message_text(
        "✅ Thanks for joining! You can now use all bot features.",
        reply_markup=reply_markup
    )

# Help command
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "Available commands:\n\n"
        "/start - Start the bot and show main menu\n"
        "/pdftolink - Store multiple files and generate a folder link\n"
        "/shortener - Shorten any shareable link\n"
        "/settings - Customize your settings\n"
    )
    
    if is_moderator(update.effective_user.id):
        help_text += (
            "\nModerator commands:\n"
            "/broadcast - Send a message to all users\n"
            "/ban - Ban a user from the bot\n"
            "/unban - Unban a user\n"
        )
    
    await update.message.reply_text(help_text)

# Create folder link (multiple files in a folder)
async def pdftolink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_banned(update.effective_user.id):
        await update.message.reply_text("You are banned from using this bot.")
        return
    
    user_id = update.effective_user.id
    
    # Check if user has joined all force sub channels
    force_sub_channels = get_force_sub_channels()
    if force_sub_channels:
        not_joined = []
        for channel_id, channel_username in force_sub_channels:
            try:
                member = await context.bot.get_chat_member(channel_id, user_id)
                if member.status in ['left', 'kicked']:
                    not_joined.append(f"@{channel_username}")
            except Exception as e:
                logger.error(f"Error checking channel membership: {e}")
                not_joined.append(f"@{channel_username}")
        
        if not_joined:
            channels_text = "\n".join([f"• {channel}" for channel in not_joined])
            keyboard = [[InlineKeyboardButton("Join Channel", url=f"https://t.me/{channel_username}")] for _, channel_username in force_sub_channels]
            keyboard.append([InlineKeyboardButton("✅ I've Joined", callback_data="check_force_sub")])
            
            await update.message.reply_text(
                f"⚠️ Please join our channels to use this feature:\n{channels_text}\n\n"
                "After joining, click the button below:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
    
    # Check if user is in the process of creating a folder
    if 'creating_folder' not in context.user_data:
        context.user_data['creating_folder'] = True
        context.user_data['folder_items'] = []
        
        await update.message.reply_text(
            "Send me the files you want to add to your folder. When you're done, use /done to generate the link."
        )
        return
    
    # If already in creation mode, inform the user
    await update.message.reply_text(
        "You're already creating a folder. Send me files or use /done when finished."
    )

# Handle incoming files for folder creation
async def handle_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_banned(update.effective_user.id):
        return
    
    if 'creating_folder' in context.user_data and context.user_data['creating_folder']:
        user_id = update.effective_user.id
        message = update.message
        
        # Get user settings
        settings = get_user_settings(user_id)
        
        # Determine message type and extract content
        item = {
            "message_type": "",
            "content": message.caption or "",
            "file_id": None,
            "file_name": "",
            "file_size": 0
        }
        
        if message.document:
            item["message_type"] = "document"
            item["file_id"] = message.document.file_id
            item["file_name"] = message.document.file_name or "Document"
            item["file_size"] = message.document.file_size or 0
        elif message.photo:
            item["message_type"] = "photo"
            item["file_id"] = message.photo[-1].file_id  # Highest resolution
            item["file_name"] = "Photo"
            item["file_size"] = 0  # Photo size not directly available
        elif message.video:
            item["message_type"] = "video"
            item["file_id"] = message.video.file_id
            item["file_name"] = message.video.file_name or "Video"
            item["file_size"] = message.video.file_size or 0
        elif message.audio:
            item["message_type"] = "audio"
            item["file_id"] = message.audio.file_id
            item["file_name"] = message.audio.file_name or "Audio"
            item["file_size"] = message.audio.file_size or 0
        else:
            # Not a supported file type
            return
        
        # Apply custom caption if set
        if settings and settings['custom_caption']:
            # If there's an original caption, append the custom caption
            if message.caption:
                item["content"] = f"{message.caption}\n\n{settings['custom_caption']}"
            else:
                item["content"] = settings['custom_caption']
        
        context.user_data['folder_items'].append(item)
        await message.reply_text(f"File added! Added {len(context.user_data['folder_items'])} files so far. Send more or use /done when finished.")

# Finish folder creation
async def done_folder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'creating_folder' in context.user_data and context.user_data['creating_folder']:
        if len(context.user_data['folder_items']) == 0:
            await update.message.reply_text("No files were added to the folder. Process cancelled.")
            context.user_data.pop('creating_folder', None)
            context.user_data.pop('folder_items', None)
            return
        
        user_id = update.effective_user.id
        folder_code = str(uuid.uuid4())[:8]
        
        # Get user settings
        settings = get_user_settings(user_id)
        protect_content = settings['protect_content'] if settings else 0
        
        # Store folder in database
        conn = sqlite3.connect('bot_data.db')
        cursor = conn.cursor()
        
        # Create folder entry
        cursor.execute(
            'INSERT INTO folders (user_id, folder_code, protect_content) VALUES (?, ?, ?)',
            (user_id, folder_code, protect_content)
        )
        folder_id = cursor.lastrowid
        
        # Add folder items
        for item in context.user_data['folder_items']:
            cursor.execute(
                'INSERT INTO folder_items (folder_id, message_type, content, file_id, file_name, file_size) VALUES (?, ?, ?, ?, ?, ?)',
                (folder_id, item["message_type"], item["content"], item["file_id"], item["file_name"], item["file_size"])
            )
        
        conn.commit()
        conn.close()
        
        # Generate the folder link
        bot_username = context.bot.username
        link = f"https://t.me/{bot_username}?start={folder_code}"
        
        await update.message.reply_text(
            f"Folder created with {len(context.user_data['folder_items'])} items!\n"
            f"Here's your shareable link:\n{link}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Share Link", url=f"tg://share?url={link}")]
            ])
        )
        
        # Clean up
        context.user_data.pop('creating_folder', None)
        context.user_data.pop('folder_items', None)
    else:
        await update.message.reply_text("You're not currently creating a folder. Use /pdftolink to start.")

# Start handler for shared links
async def start_with_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) > 0:
        link_code = context.args[0]
        
        # Check if it's a folder
        conn = sqlite3.connect('bot_data.db')
        cursor = conn.cursor()
        cursor.execute(
            'SELECT folder_id, protect_content FROM folders WHERE folder_code = ?',
            (link_code,)
        )
        folder_result = cursor.fetchone()
        
        if folder_result:
            folder_id, protect_content = folder_result
            
            # Get folder items
            cursor.execute(
                'SELECT message_type, content, file_id FROM folder_items WHERE folder_id = ? ORDER BY item_id',
                (folder_id,)
            )
            items = cursor.fetchall()
            conn.close()
            
            if items:
                for item in items:
                    message_type, content, file_id = item
                    
                    if message_type == "text":
                        msg = await update.message.reply_text(
                            content,
                            protect_content=bool(protect_content)
                        )
                    elif message_type == "document":
                        msg = await update.message.reply_document(
                            file_id, 
                            caption=content if content else None,
                            protect_content=bool(protect_content)
                        )
                    elif message_type == "photo":
                        msg = await update.message.reply_photo(
                            file_id, 
                            caption=content if content else None,
                            protect_content=bool(protect_content)
                        )
                    elif message_type == "video":
                        msg = await update.message.reply_video(
                            file_id, 
                            caption=content if content else None,
                            protect_content=bool(protect_content)
                        )
                    elif message_type == "audio":
                        msg = await update.message.reply_audio(
                            file_id, 
                            caption=content if content else None,
                            protect_content=bool(protect_content)
                        )
                    
                    # Auto delete if enabled for the current user
                    settings = get_user_settings(update.effective_user.id)
                    if settings and settings['auto_delete']:
                        auto_delete_time = settings['auto_delete_time'] * 60  # Convert minutes to seconds
                        await asyncio.sleep(auto_delete_time)
                        try:
                            await msg.delete()
                        except Exception as e:
                            logger.error(f"Error deleting message: {e}")
            else:
                await update.message.reply_text("This folder is empty.")
        else:
            # Check if it's a single message
            cursor.execute(
                'SELECT message_type, content, file_id, protect_content FROM messages WHERE link_code = ?',
                (link_code,)
            )
            message_result = cursor.fetchone()
            conn.close()
            
            if message_result:
                message_type, content, file_id, protect_content = message_result
                
                if message_type == "text":
                    msg = await update.message.reply_text(
                        content,
                        protect_content=bool(protect_content)
                    )
                elif message_type == "document":
                    msg = await update.message.reply_document(
                        file_id, 
                        caption=content if content else None,
                        protect_content=bool(protect_content)
                    )
                elif message_type == "photo":
                    msg = await update.message.reply_photo(
                        file_id, 
                        caption=content if content else None,
                        protect_content=bool(protect_content)
                    )
                elif message_type == "video":
                    msg = await update.message.reply_video(
                        file_id, 
                        caption=content if content else None,
                        protect_content=bool(protect_content)
                    )
                elif message_type == "audio":
                    msg = await update.message.reply_audio(
                        file_id, 
                        caption=content if content else None,
                        protect_content=bool(protect_content)
                    )
                
                # Auto delete if enabled for the current user
                settings = get_user_settings(update.effective_user.id)
                if settings and settings['auto_delete']:
                    auto_delete_time = settings['auto_delete_time'] * 60  # Convert minutes to seconds
                    await asyncio.sleep(auto_delete_time)
                    try:
                        await msg.delete()
                    except Exception as e:
                        logger.error(f"Error deleting message: {e}")
            else:
                await update.message.reply_text("This link is invalid or has expired.")
    else:
        await start(update, context)

# Shorten URL
async def shortener(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_banned(update.effective_user.id):
        await update.message.reply_text("You are banned from using this bot.")
        return
    
    if not context.args:
        await update.message.reply_text("Please provide a URL to shorten. Example: /shortener https://example.com")
        return
    
    url = context.args[0]
    
    # Validate URL
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    # Shorten URL using TinyURL API
    short_url = await shorten_url(url)
    
    if short_url:
        await update.message.reply_text(
            f"Shortened URL:\n{short_url}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Visit URL", url=short_url)],
                [InlineKeyboardButton("Share", url=f"tg://share?url={short_url}")]
            ])
        )
    else:
        await update.message.reply_text("Sorry, I couldn't shorten that URL. Please try again later.")

# Settings command
async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    settings = get_user_settings(user_id)
    
    keyboard = [
        [InlineKeyboardButton("Custom Caption", callback_data="setting_caption")],
        [InlineKeyboardButton("Protect Content", callback_data="setting_protect")],
        [InlineKeyboardButton("Force Sub Channels", callback_data="setting_force_sub")],
        [InlineKeyboardButton("Auto Delete", callback_data="setting_auto_delete")],
        [InlineKeyboardButton("Close", callback_data="setting_close")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    status_text = (
        "⚙️ Bot Settings:\n\n"
        f"• Custom Caption: {'Set' if settings and settings['custom_caption'] else 'Not Set'}\n"
        f"• Protect Content: {'Enabled' if settings and settings['protect_content'] else 'Disabled'}\n"
        f"• Force Sub: {len(get_force_sub_channels())} channels\n"
        f"• Auto Delete: {'Enabled' if settings and settings['auto_delete'] else 'Disabled'}"
    )
    
    if settings and settings['auto_delete']:
        status_text += f" ({settings['auto_delete_time']} minutes)"
    
    status_text += "\n\nChoose an option to configure:"
    
    await update.message.reply_text(status_text, reply_markup=reply_markup)

# Settings callback handler
async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    settings = get_user_settings(user_id)
    
    if query.data == "setting_caption":
        current_caption = settings['custom_caption'] if settings and settings['custom_caption'] else "Not set"
        await query.edit_message_text(
            f"📝 Custom Caption Settings:\n\nCurrent: {current_caption}\n\n"
            "Send me your custom text that will appear below files:\n\n"
            "Example: `Download from our channel @example`\n\n"
            "Send /cancel to keep the current setting.",
            parse_mode="Markdown"
        )
        context.user_data['awaiting_caption'] = True
        
    elif query.data == "setting_protect":
        current = settings['protect_content'] if settings else 0
        new_value = 0 if current else 1
        
        update_user_settings(user_id, 'protect_content', new_value)
        status = "enabled" if new_value else "disabled"
        
        await query.edit_message_text(f"✅ Protect Content has been {status}.")
        
    elif query.data == "setting_force_sub":
        if not is_moderator(user_id):
            await query.edit_message_text("❌ Only moderators can manage force sub channels.")
            return
            
        channels = get_force_sub_channels()
        keyboard = []
        
        for channel_id, channel_username in channels:
            keyboard.append([InlineKeyboardButton(f"Remove @{channel_username}", callback_data=f"remove_channel_{channel_id}")])
        
        keyboard.append([InlineKeyboardButton("➕ Add Channel", callback_data="add_channel")])
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="settings_back")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        channels_text = "\n".join([f"• @{username}" for _, username in channels]) if channels else "No channels added"
        
        await query.edit_message_text(
            f"📢 Force Sub Channels:\n\n{channels_text}\n\n"
            "Manage channels:",
            reply_markup=reply_markup
        )
        
    elif query.data.startswith("remove_channel_"):
        channel_id = int(query.data.split("_")[2])
        remove_force_sub_channel(channel_id)
        
        await query.edit_message_text("✅ Channel removed successfully.")
        
    elif query.data == "add_channel":
        await query.edit_message_text(
            "Send me the channel ID or username to add. For channels, you must add the bot as an admin first.\n\n"
            "Send /cancel to abort."
        )
        context.user_data['awaiting_channel'] = True
        
    elif query.data == "setting_auto_delete":
        current = settings['auto_delete'] if settings else 0
        new_value = 0 if current else 1
        
        update_user_settings(user_id, 'auto_delete', new_value)
        status = "enabled" if new_value else "disabled"
        
        time_text = f" (current: {settings['auto_delete_time']} minutes)" if settings and settings['auto_delete_time'] else ""
        
        await query.edit_message_text(
            f"✅ Auto Delete has been {status}.\n\n"
            f"To change the auto delete time{time_text}, send me the number of minutes (e.g., 15).\n"
            "Send /cancel to keep the current time."
        )
        context.user_data['awaiting_auto_delete_time'] = True
        
    elif query.data == "setting_close":
        await query.delete_message()
        
    elif query.data == "settings_back":
        await settings_callback_back(query, context)
        
    elif query.data == "check_force_sub":
        await check_force_sub(update, context)

async def settings_callback_back(query, context):
    user_id = query.from_user.id
    settings = get_user_settings(user_id)
    
    keyboard = [
        [InlineKeyboardButton("Custom Caption", callback_data="setting_caption")],
        [InlineKeyboardButton("Protect Content", callback_data="setting_protect")],
        [InlineKeyboardButton("Force Sub Channels", callback_data="setting_force_sub")],
        [InlineKeyboardButton("Auto Delete", callback_data="setting_auto_delete")],
        [InlineKeyboardButton("Close", callback_data="setting_close")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    status_text = (
        "⚙️ Bot Settings:\n\n"
        f"• Custom Caption: {'Set' if settings and settings['custom_caption'] else 'Not Set'}\n"
        f"• Protect Content: {'Enabled' if settings and settings['protect_content'] else 'Disabled'}\n"
        f"• Force Sub: {len(get_force_sub_channels())} channels\n"
        f"• Auto Delete: {'Enabled' if settings and settings['auto_delete'] else 'Disabled'}"
    )
    
    if settings and settings['auto_delete']:
        status_text += f" ({settings['auto_delete_time']} minutes)"
    
    status_text += "\n\nChoose an option to configure:"
    
    await query.edit_message_text(status_text, reply_markup=reply_markup)

# Handle text messages for settings
async def handle_settings_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    
    # Check if user is in any setting mode
    if 'awaiting_caption' in context.user_data:
        if text == '/cancel':
            await update.message.reply_text("❌ Caption setting unchanged.")
            context.user_data.pop('awaiting_caption', None)
            return
        else:
            update_user_settings(user_id, 'custom_caption', text)
            await update.message.reply_text("✅ Custom caption has been set!")
            context.user_data.pop('awaiting_caption', None)
            return
        
    elif 'awaiting_channel' in context.user_data:
        if text == '/cancel':
            await update.message.reply_text("❌ Channel addition cancelled.")
            context.user_data.pop('awaiting_channel', None)
            return
        else:
            # Try to extract channel ID from text
            channel_input = text.strip()
            channel_id = None
            channel_username = None
            
            if channel_input.startswith('@'):
                channel_username = channel_input[1:]
                try:
                    chat = await context.bot.get_chat(channel_input)
                    channel_id = chat.id
                    channel_username = chat.username
                except Exception as e:
                    await update.message.reply_text(f"❌ Error: Could not find channel {channel_input}")
                    context.user_data.pop('awaiting_channel', None)
                    return
            else:
                try:
                    channel_id = int(channel_input)
                    chat = await context.bot.get_chat(channel_id)
                    channel_username = chat.username
                except (ValueError, Exception):
                    await update.message.reply_text("❌ Please provide a valid channel ID or username.")
                    context.user_data.pop('awaiting_channel', None)
                    return
            
            add_force_sub_channel(channel_id, channel_username, user_id)
            await update.message.reply_text(f"✅ Channel @{channel_username} has been added to force sub.")
            context.user_data.pop('awaiting_channel', None)
            return
        
    elif 'awaiting_auto_delete_time' in context.user_data:
        if text == '/cancel':
            await update.message.reply_text("❌ Auto delete time unchanged.")
            context.user_data.pop('awaiting_auto_delete_time', None)
            return
        else:
            try:
                time = int(text)
                if time < 1:
                    await update.message.reply_text("❌ Please enter a positive number.")
                    return
                
                update_user_settings(user_id, 'auto_delete_time', time)
                await update.message.reply_text(f"✅ Auto delete time has been set to {time} minutes!")
                context.user_data.pop('awaiting_auto_delete_time', None)
                return
            except ValueError:
                await update.message.reply_text("❌ Please enter a valid number.")
                return
    
    # If not in any setting mode, handle as menu command
    await handle_menu(update, context)
      
# Broadcast command (moderators only)
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_moderator(user_id):
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    if not context.args:
        await update.message.reply_text("Please provide a message to broadcast. Example: /broadcast Hello everyone!")
        return
    
    message = " ".join(context.args)
    
    # Get all users
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM users WHERE is_banned = 0')
    users = cursor.fetchall()
    conn.close()
    
    success = 0
    failed = 0
    
    broadcast_msg = await update.message.reply_text("📢 Broadcasting started...")
    
    for (user_id,) in users:
        try:
            await context.bot.send_message(chat_id=user_id, text=f"📢 Broadcast:\n\n{message}")
            success += 1
        except Exception as e:
            logger.error(f"Failed to send broadcast to {user_id}: {e}")
            failed += 1
        
        # Update progress every 10 messages
        if (success + failed) % 10 == 0:
            await broadcast_msg.edit_text(f"📢 Broadcasting...\nSuccess: {success}, Failed: {failed}")
    
    await broadcast_msg.edit_text(f"✅ Broadcast completed:\n• Success: {success}\n• Failed: {failed}")

# Ban command (moderators only)
async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_moderator(user_id):
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    if not context.args:
        await update.message.reply_text("Please provide a user ID to ban. Example: /ban 123456789")
        return
    
    try:
        target_id = int(context.args[0])
        
        conn = sqlite3.connect('bot_data.db')
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE users SET is_banned = 1 WHERE user_id = ?',
            (target_id,)
        )
        conn.commit()
        conn.close()
        
        await update.message.reply_text(f"✅ User {target_id} has been banned.")
    except ValueError:
        await update.message.reply_text("❌ Please provide a valid user ID.")

# Unban command (moderators only)
async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_moderator(user_id):
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    if not context.args:
        await update.message.reply_text("Please provide a user ID to unban. Example: /unban 123456789")
        return
    
    try:
        target_id = int(context.args[0])
        
        conn = sqlite3.connect('bot_data.db')
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE users SET is_banned = 0 WHERE user_id = ?',
            (target_id,)
        )
        conn.commit()
        conn.close()
        
        await update.message.reply_text(f"✅ User {target_id} has been unbanned.")
    except ValueError:
        await update.message.reply_text("❌ Please provide a valid user ID.")

# Check status command
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Get user stats
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    
    # Count user's folders
    cursor.execute('SELECT COUNT(*) FROM folders WHERE user_id = ?', (user_id,))
    folder_count = cursor.fetchone()[0]
    
    # Count total users
    cursor.execute('SELECT COUNT(*) FROM users WHERE is_banned = 0')
    user_count = cursor.fetchone()[0]
    
    # Count total files
    cursor.execute('SELECT COUNT(*) FROM folder_items')
    file_count = cursor.fetchone()[0]
    
    conn.close()
    
    status_text = (
        "🤖 Bot Status: Online\n\n"
        f"📊 Your Usage:\n"
        f"• Folders created: {folder_count}\n\n"
        f"📈 Statistics:\n"
        f"• Total Users: {user_count}\n"
        f"• Total Files: {file_count}\n\n"
        "✅ All systems operational!"
    )
    
    await update.message.reply_text(status_text)

# Handle text messages for the menu
async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if text == "Create Folder Link":
        await pdftolink(update, context)
    elif text == "Shorten Link":
        await update.message.reply_text(
            "To shorten a URL, use /shortener followed by the URL\nExample: /shortener https://example.com"
        )
    elif text == "Settings":
        await settings(update, context)
    elif text == "Check Status":
        await status(update, context)

# Error handler
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

# Main function
def main():
    # Initialize database
    init_db()
    
    # Create Application
    application = Application.builder().token(TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_with_link))
    application.add_handler(CommandHandler("pdftolink", pdftolink))
    application.add_handler(CommandHandler("shortener", shortener))
    application.add_handler(CommandHandler("settings", settings))
    application.add_handler(CommandHandler("done", done_folder))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("ban", ban))
    application.add_handler(CommandHandler("unban", unban))
    application.add_handler(CommandHandler("status", status))
    
    application.add_handler(CallbackQueryHandler(settings_callback, pattern="^setting_|^remove_channel_|^add_channel|^settings_back|^check_force_sub$"))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_settings_input))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_files))
    
    application.add_error_handler(error_handler)
    
    # Start the Bot
    print("Bot is running...")
    application.run_polling()

if __name__ == '__main__':
    main()