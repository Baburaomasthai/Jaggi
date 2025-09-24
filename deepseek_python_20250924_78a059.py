from flask import Flask
import threading
import os

app = Flask(__name__)

@app.route('/')
def home():
    return "✅ 𝑇𝑟𝑦𝑖𝑛𝑔 𝑇𝑜 𝑇𝑎𝑐𝑘𝑙𝑒 𝑆𝑒𝑡𝑏𝑎𝑐𝑘 𝑇𝐺 - https://t.me/MrJaggiX!"

def run_flask():
    port = int(os.environ.get("PORT", 5000))  
    app.run(host="0.0.0.0", port=port)

# Flask ko background thread me start karo
threading.Thread(target=run_flask).start()

import json
import os
from typing import Dict, Any, List
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =================== CONFIG ===================

TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("ADMIN_ID"))
DATA_FILE = "materials.json"
BACKUP_CHANNEL_ID = os.getenv("BACKUP_CHANNEL_ID")  # Set this environment variable

# =================== DATA MODEL ===================

DEFAULT_STRUCTURE: Dict[str, Any] = {
    "_meta": {"admins": [OWNER_ID], "users": []},
    "IIT JEE": {
        "Physics": {},
        "Chemistry": {},
        "Math": {},
    },
    "NEET": {
        "Physics": {},
        "Chemistry": {},
        "Biology": {},
    },
}

async def backup_data_to_channel(bot):
    """Backup data to Telegram channel"""
    try:
        if not BACKUP_CHANNEL_ID:
            print("BACKUP_CHANNEL_ID not set, skipping backup")
            return
            
        data_str = json.dumps(MATERIALS, ensure_ascii=False, indent=2)
        
        # If data is too large, split it
        if len(data_str) > 4000:
            # Split into chunks
            chunks = [data_str[i:i+4000] for i in range(0, len(data_str), 4000)]
            for i, chunk in enumerate(chunks):
                message = f"#BACKUP_PART_{i+1}\n```json\n{chunk}\n```"
                await bot.send_message(
                    chat_id=BACKUP_CHANNEL_ID, 
                    text=message,
                    parse_mode="Markdown"
                )
        else:
            message = f"#BACKUP\n```json\n{data_str}\n```"
            await bot.send_message(
                chat_id=BACKUP_CHANNEL_ID, 
                text=message,
                parse_mode="Markdown"
            )
        print("Data backed up to channel successfully")
    except Exception as e:
        print(f"Error backing up data to channel: {e}")

async def load_data_from_channel(bot):
    """Load data from Telegram channel backup"""
    try:
        if not BACKUP_CHANNEL_ID:
            print("BACKUP_CHANNEL_ID not set, skipping channel load")
            return None
            
        # Get messages from channel
        messages = []
        async for message in bot.get_chat_history(chat_id=BACKUP_CHANNEL_ID, limit=10):
            if message.text and ("#BACKUP" in message.text or "#BACKUP_PART" in message.text):
                messages.append(message)
        
        if not messages:
            print("No backup messages found in channel")
            return None
        
        # Sort messages: full backup first, then parts in order
        full_backup = [m for m in messages if "#BACKUP\n" in m.text]
        part_backups = [m for m in messages if "#BACKUP_PART" in m.text]
        part_backups.sort(key=lambda x: int(x.text.split("_PART_")[1].split("\n")[0]))
        
        # Use full backup if available, otherwise combine parts
        if full_backup:
            backup_msg = full_backup[0]
            data_str = backup_msg.text.split("```json\n")[1].split("\n```")[0]
        else:
            # Combine parts
            data_str = ""
            for msg in part_backups:
                part_data = msg.text.split("```json\n")[1].split("\n```")[0]
                data_str += part_data
        
        data = json.loads(data_str)
        print("Data loaded from channel backup successfully")
        return data
    except Exception as e:
        print(f"Error loading data from channel: {e}")
        return None

def load_materials() -> Dict[str, Any]:
    try:
        # First try to load from local file
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                print("Data loaded from local file")
        else:
            data = DEFAULT_STRUCTURE.copy()
            print("Using default structure")
            
        # ensure _meta
        data.setdefault("_meta", {"admins": [OWNER_ID], "users": []})
        
        # ensure top-level exams and subjects from default
        for exam, subjects in DEFAULT_STRUCTURE.items():
            if exam == "_meta":
                continue
            data.setdefault(exam, {})
            for subject, pubs in subjects.items():
                if isinstance(data[exam], dict):
                    data[exam].setdefault(subject, {})
                
        return data
    except Exception as e:
        print(f"Error loading materials: {e}")
        return DEFAULT_STRUCTURE.copy()

def save_materials() -> None:
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(MATERIALS, f, ensure_ascii=False, indent=2)
        print("Data saved to local file")
    except Exception as e:
        print(f"Error saving materials: {e}")

MATERIALS: Dict[str, Any] = load_materials()

# user_state keeps temporary interaction states
user_state: Dict[int, Dict[str, Any]] = {}

# =================== KEYBOARDS ===================

def kb(rows: List[List[str]]):
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def main_menu_kb():
    return kb([["📘 IIT JEE", "📗 NEET"], ["👥 Community", "ℹ️ Credits"]])

def exams_from_data() -> List[str]:
    return [k for k in MATERIALS.keys() if k != "_meta" and isinstance(MATERIALS[k], dict)]

def subjects_for_exam(exam: str) -> List[str]:
    exam_data = MATERIALS.get(exam, {})
    if isinstance(exam_data, dict):
        return sorted(list(exam_data.keys()))
    return []

def publishers_for(exam: str, subject: str) -> List[str]:
    exam_data = MATERIALS.get(exam, {})
    if isinstance(exam_data, dict):
        subject_data = exam_data.get(subject, {})
        if isinstance(subject_data, dict):
            # Return only publishers (not sub-folders)
            return sorted([k for k in subject_data.keys() if not k.startswith("_folder:")])
    return []

def subfolders_for(exam: str, subject: str, publisher: str) -> List[str]:
    exam_data = MATERIALS.get(exam, {})
    if isinstance(exam_data, dict):
        subject_data = exam_data.get(subject, {})
        if isinstance(subject_data, dict):
            publisher_data = subject_data.get(publisher, {})
            if isinstance(publisher_data, dict):
                # Return only sub-folders
                return sorted([k.replace("_folder:", "") for k in publisher_data.keys() if k.startswith("_folder:")])
    return []

def chunk(lst: List[str], n: int) -> List[List[str]]:
    return [lst[i:i+n] for i in range(0, len(lst), n)]

def subjects_kb(exam: str):
    items = subjects_for_exam(exam)
    rows = chunk(items, 3)
    rows.append(["⬅️ Back", "🏠 Menu"])
    return kb(rows)

def publishers_kb(exam: str, subject: str, include_add: bool = False, include_folder: bool = False):
    items = publishers_for(exam, subject)
    if include_add:
        items = ["➕ Add New Publisher"] + items
    if include_folder:
        items = ["📁 Add Sub-Folder"] + items
    rows = chunk(items, 3)
    rows.append(["⬅️ Back", "🏠 Menu"])
    return kb(rows)

def subfolders_kb(exam: str, subject: str, publisher: str, include_add: bool = False):
    items = subfolders_for(exam, subject, publisher)
    if include_add:
        items = ["➕ Add New Sub-Folder"] + items
    items = ["📁 Upload Directly"] + items  # Add option to upload directly to publisher
    rows = chunk(items, 3)
    rows.append(["⬅️ Back", "🏠 Menu"])
    return kb(rows)

# =================== HELPERS ===================

def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID

def is_admin(user_id: int) -> bool:
    admins = MATERIALS.get("_meta", {}).get("admins", [])
    return user_id in admins

def add_user_to_meta(user_id: int):
    users = MATERIALS.setdefault("_meta", {}).setdefault("users", [])
    if user_id not in users:
        users.append(user_id)
        save_materials()

def reset_state(user_id: int):
    user_state[user_id] = {
        "mode": None,
        "step": None,
        "exam": None,
        "subject": None,
        "publisher": None,
        "subfolder": None,
        "awaiting_new_publisher_name": False,
        "awaiting_new_subfolder_name": False,
        "upload_active": False,
        "awaiting_text": False,
    }

def ensure_publisher(exam: str, subject: str, publisher: str):
    if exam not in MATERIALS:
        MATERIALS[exam] = {}
    if subject not in MATERIALS[exam]:
        MATERIALS[exam][subject] = {}
    if publisher not in MATERIALS[exam][subject]:
        MATERIALS[exam][subject][publisher] = []

def ensure_subject(exam: str, subject: str):
    if exam not in MATERIALS:
        MATERIALS[exam] = {}
    if subject not in MATERIALS[exam]:
        MATERIALS[exam][subject] = {}

def ensure_exam(exam: str):
    if exam not in MATERIALS:
        MATERIALS[exam] = {}

def ensure_subfolder(exam: str, subject: str, publisher: str, subfolder: str):
    ensure_publisher(exam, subject, publisher)
    folder_key = f"_folder:{subfolder}"
    if folder_key not in MATERIALS[exam][subject][publisher]:
        MATERIALS[exam][subject][publisher][folder_key] = []

# =================== COMMANDS ===================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in user_state:
        reset_state(uid)
    add_user_to_meta(uid)
    await update.message.reply_text(
        "Welcome! Choose an option 👇",
        reply_markup=main_menu_kb()
    )

async def cmd_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manual backup command"""
    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text("❌ You are not authorized.")
        return
        
    await update.message.reply_text("🔄 Creating backup...")
    await backup_data_to_channel(context.bot)
    await update.message.reply_text("✅ Backup completed successfully!")

async def cmd_restore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manual restore command"""
    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text("❌ You are not authorized.")
        return
        
    await update.message.reply_text("🔄 Restoring from backup...")
    data = await load_data_from_channel(context.bot)
    
    if data:
        global MATERIALS
        MATERIALS = data
        save_materials()  # Save to local file as well
        await update.message.reply_text("✅ Data restored successfully from channel backup!")
    else:
        await update.message.reply_text("❌ No backup found or error restoring data.")

async def cmd_addmaterial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text("❌ You are not authorized.")
        return
        
    reset_state(uid)
    st = user_state[uid]
    st["mode"] = "add"
    st["step"] = "choose_exam"

    exams = exams_from_data()
    if not exams:
        await update.message.reply_text("No exams found. Admin can add exams using /addsubject with an exam name and subject.")
        return
        
    rows = chunk(exams, 2)
    rows.append(["🏠 Menu"])
    await update.message.reply_text("Select Exam:", reply_markup=kb(rows))

async def cmd_deletefile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text("❌ You are not authorized.")
        return
        
    reset_state(uid)
    st = user_state[uid]
    st["mode"] = "delete_file"
    st["step"] = "choose_exam"

    exams = exams_from_data()
    rows = chunk(exams, 2)
    rows.append(["🏠 Menu"])
    await update.message.reply_text("🗑️ Delete File → Select Exam:", reply_markup=kb(rows))

async def cmd_deletepublisher(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text("❌ You are not authorized.")
        return
        
    reset_state(uid)
    st = user_state[uid]
    st["mode"] = "delete_publisher"
    st["step"] = "choose_exam"

    exams = exams_from_data()
    rows = chunk(exams, 2)
    rows.append(["🏠 Menu"])
    await update.message.reply_text("🗑️ Delete Publisher → Select Exam:", reply_markup=kb(rows))

async def cmd_addsubject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text("❌ Only admins can add subjects.")
        return
        
    text = " ".join(context.args) if context.args else ""
    if ">" in text:
        parts = [p.strip() for p in text.split(">")]
        if len(parts) >= 2:
            exam = parts[0]
            subject = parts[1]
            ensure_subject(exam, subject)
            save_materials()
            await update.message.reply_text(f"✅ Subject '{subject}' added under exam '{exam}'.")
            return
            
    reset_state(uid)
    st = user_state[uid]
    st["mode"] = "add_subject"
    st["step"] = "ask_exam"
    await update.message.reply_text("Send exam name (existing or new) for which you want to add a subject:")

async def cmd_deletesubject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text("❌ Only admins can delete subjects.")
        return
        
    reset_state(uid)
    st = user_state[uid]
    st["mode"] = "delete_subject"
    st["step"] = "choose_exam"

    exams = exams_from_data()
    rows = chunk(exams, 2)
    rows.append(["🏠 Menu"])
    await update.message.reply_text("Select Exam to delete a subject from:", reply_markup=kb(rows))

async def cmd_addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("❌ Only bot owner can add admins.")
        return
        
    if not context.args:
        await update.message.reply_text("Usage: /addadmin <telegram_user_id>")
        return
        
    try:
        new_admin = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Provide a numeric Telegram user id.")
        return
        
    admins = MATERIALS.setdefault("_meta", {}).setdefault("admins", [])
    if new_admin in admins:
        await update.message.reply_text("⚠️ This user is already an admin.")
        return
        
    admins.append(new_admin)
    save_materials()
    await update.message.reply_text(f"✅ Added admin: {new_admin}")

async def cmd_removeadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("❌ Only bot owner can remove admins.")
        return
        
    if not context.args:
        await update.message.reply_text("Usage: /removeadmin <telegram_user_id>")
        return
        
    try:
        rem = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Provide a numeric Telegram user id.")
        return
        
    admins = MATERIALS.setdefault("_meta", {}).setdefault("admins", [])
    if rem not in admins:
        await update.message.reply_text("⚠️ This user is not an admin.")
        return
        
    admins.remove(rem)
    save_materials()
    await update.message.reply_text(f"✅ Removed admin: {rem}")

async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("❌ Only bot owner can broadcast messages.")
        return
        
    reset_state(uid)
    st = user_state[uid]
    st["mode"] = "broadcast"
    st["step"] = "await_text"
    st["awaiting_text"] = True
    await update.message.reply_text("✉️ Send the message you want to broadcast to all users. It can be text only.")

async def cmd_addsubfolder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text("❌ Only admins can add sub-folders.")
        return
        
    reset_state(uid)
    st = user_state[uid]
    st["mode"] = "add_subfolder"
    st["step"] = "choose_exam"

    exams = exams_from_data()
    rows = chunk(exams, 2)
    rows.append(["🏠 Menu"])
    await update.message.reply_text("Select Exam to add sub-folder:", reply_markup=kb(rows))

async def cmd_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    st = user_state.get(uid)
    if not st:
        await update.message.reply_text("ℹ️ Nothing to finish.")
        return
        
    if st.get("mode") == "add" and st.get("upload_active"):
        st["upload_active"] = False
        # Auto-backup after upload completion
        await backup_data_to_channel(context.bot)
        if st.get("subfolder"):
            await update.message.reply_text(f"✅ Upload finished for {st['exam']} > {st['subject']} > {st['publisher']} > {st['subfolder']}")
        else:
            await update.message.reply_text(f"✅ Upload finished for {st['exam']} > {st['subject']} > {st['publisher']}")
        return
        
    await update.message.reply_text("✅ Done.")

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    reset_state(uid)
    await update.message.reply_text("❎ Cancelled.", reply_markup=main_menu_kb())

# =================== FILE HANDLER (UPLOAD) ===================

async def handle_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    st = user_state.get(uid)
    
    if not st or st.get("mode") != "add" or not st.get("upload_active"):
        return
        
    exam = st["exam"]
    subject = st["subject"]
    publisher = st["publisher"]
    subfolder = st.get("subfolder")
    
    file_id = None
    ftype = None
    fname = None
    
    if update.message.document:
        file_id = update.message.document.file_id
        ftype = "document"
        fname = update.message.document.file_name
    elif update.message.photo:
        file_id = update.message.photo[-1].file_id
        ftype = "photo"
        fname = "photo.jpg"
    elif update.message.video:
        file_id = update.message.video.file_id
        ftype = "video"
        fname = getattr(update.message.video, "file_name", "video.mp4")
        
    if file_id:
        if subfolder:
            ensure_subfolder(exam, subject, publisher, subfolder)
            folder_key = f"_folder:{subfolder}"
            MATERIALS[exam][subject][publisher][folder_key].append({
                "id": file_id,
                "type": ftype,
                "name": fname or ftype,
                "caption": update.message.caption or "",
            })
        else:
            ensure_publisher(exam, subject, publisher)
            MATERIALS[exam][subject][publisher].append({
                "id": file_id,
                "type": ftype,
                "name": fname or ftype,
                "caption": update.message.caption or "",
            })
        save_materials()
        
        if subfolder:
            await update.message.reply_text(f"✅ Saved to {exam} > {subject} > {publisher} > {subfolder}")
        else:
            await update.message.reply_text(f"✅ Saved to {exam} > {subject} > {publisher}")
    else:
        await update.message.reply_text("❌ Only PDF/Image/Video allowed.")

# =================== TEXT HANDLER (STATE MACHINE + PUBLIC BROWSING) ===================

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    txt = (update.message.text or "").strip()
    
    if uid not in user_state:
        reset_state(uid)
        
    st = user_state[uid]

    add_user_to_meta(uid)

    # Handle Menu and Back buttons properly
    if txt in ("🏠 Menu", "/menu"):
        reset_state(uid)
        await update.message.reply_text("Main Menu:", reply_markup=main_menu_kb())
        return
        
    if txt == "⬅️ Back":
        # Handle back navigation based on current step
        current_step = st.get("step")
        
        if current_step == "choose_subject":
            st["step"] = "choose_exam"
            st["exam"] = None
            exams = exams_from_data()
            rows = chunk(exams, 2)
            rows.append(["🏠 Menu"])
            await update.message.reply_text("Select Exam:", reply_markup=kb(rows))
            return
            
        elif current_step == "choose_publisher":
            st["step"] = "choose_subject"
            st["publisher"] = None
            await update.message.reply_text(f"{st['exam']} – Select Subject:", reply_markup=subjects_kb(st["exam"]))
            return
            
        elif current_step == "choose_subfolder":
            st["step"] = "choose_publisher"
            st["subfolder"] = None
            await update.message.reply_text(
                f"{st['exam']} > {st['subject']} – Select Publisher:",
                reply_markup=publishers_kb(st["exam"], st["subject"], include_add=(st["mode"]=="add"), include_folder=True)
            )
            return
            
        elif current_step == "choose_file":
            if st.get("subfolder"):
                st["step"] = "choose_subfolder"
                st["subfolder"] = None
                await update.message.reply_text(
                    f"{st['exam']} > {st['subject']} > {st['publisher']} – Select Sub-Folder:",
                    reply_markup=subfolders_kb(st["exam"], st["subject"], st["publisher"], include_add=True)
                )
            else:
                st["step"] = "choose_publisher"
                st["publisher"] = None
                await update.message.reply_text(
                    f"{st['exam']} > {st['subject']} – Select Publisher:",
                    reply_markup=publishers_kb(st["exam"], st["subject"], include_add=(st["mode"]=="add"), include_folder=True)
                )
            return
            
        elif current_step in ["choose_subfolder_delete", "choose_file"]:
            st["step"] = "choose_publisher"
            st["publisher"] = None
            st["subfolder"] = None
            await update.message.reply_text(
                f"{st['exam']} > {st['subject']} – Select Publisher:",
                reply_markup=publishers_kb(st["exam"], st["subject"], include_add=False)
            )
            return
            
        elif current_step in ["choose_subject_to_delete", "choose_publisher"]:
            st["step"] = "choose_exam"
            st["exam"] = None
            st["subject"] = None
            exams = exams_from_data()
            rows = chunk(exams, 2)
            rows.append(["🏠 Menu"])
            await update.message.reply_text("Select Exam:", reply_markup=kb(rows))
            return
            
        elif current_step in ["ask_exam", "ask_subject", "ask_subfolder_name", "await_text"]:
            reset_state(uid)
            await update.message.reply_text("Main Menu:", reply_markup=main_menu_kb())
            return
            
        # Default back behavior
        reset_state(uid)
        await update.message.reply_text("Main Menu:", reply_markup=main_menu_kb())
        return

    if st.get("mode") == "add":
        if st.get("awaiting_new_publisher_name"):
            new_pub = txt
            if new_pub in publishers_for(st["exam"], st["subject"]):
                await update.message.reply_text("⚠️ Publisher already exists. Choose another name.")
                return
                
            ensure_publisher(st["exam"], st["subject"], new_pub)
            save_materials()
            st["publisher"] = new_pub
            st["awaiting_new_publisher_name"] = False
            st["upload_active"] = True
            st["step"] = "choose_file"
            await update.message.reply_text(
                f"✅ Publisher \"{new_pub}\" created. Now send files (PDF/Image/Video).\n\nSend /done when finished.", 
                reply_markup=kb([["⬅️ Back", "🏠 Menu"]])
            )
            return
            
        if st.get("awaiting_new_subfolder_name"):
            new_folder = txt
            folder_key = f"_folder:{new_folder}"
            if folder_key in MATERIALS[st["exam"]][st["subject"]][st["publisher"]]:
                await update.message.reply_text("⚠️ Sub-folder already exists. Choose another name.")
                return
                
            ensure_subfolder(st["exam"], st["subject"], st["publisher"], new_folder)
            save_materials()
            st["subfolder"] = new_folder
            st["awaiting_new_subfolder_name"] = False
            st["upload_active"] = True
            st["step"] = "choose_file"
            await update.message.reply_text(
                f"✅ Sub-folder \"{new_folder}\" created. Now send files (PDF/Image/Video).\n\nSend /done when finished.", 
                reply_markup=kb([["⬅️ Back", "🏠 Menu"]])
            )
            return
            
        if st["step"] == "choose_exam":
            if txt not in exams_from_data():
                await update.message.reply_text("❌ Invalid exam. Choose from buttons.")
                return
                
            st["exam"] = txt
            st["step"] = "choose_subject"
            await update.message.reply_text(f"{st['exam']} – Select Subject:", reply_markup=subjects_kb(st["exam"]))
            return
            
        if st["step"] == "choose_subject":
            if txt not in subjects_for_exam(st["exam"]):
                await update.message.reply_text("❌ Invalid subject. Choose from buttons.")
                return
                
            st["subject"] = txt
            st["step"] = "choose_publisher"
            await update.message.reply_text(
                f"{st['exam']} > {st['subject']} – Select Publisher or add new:",
                reply_markup=publishers_kb(st["exam"], st["subject"], include_add=True, include_folder=True)
            )
            return
            
        if st["step"] == "choose_publisher":
            if txt == "➕ Add New Publisher":
                st["awaiting_new_publisher_name"] = True
                await update.message.reply_text("✍️ Send the new publisher name:", reply_markup=kb([["⬅️ Back", "🏠 Menu"]]))
                return
            elif txt == "📁 Add Sub-Folder":
                if not st.get("publisher"):
                    await update.message.reply_text("❌ First select a publisher to add sub-folder to.")
                    return
                st["awaiting_new_subfolder_name"] = True
                await update.message.reply_text("✍️ Send the new sub-folder name:", reply_markup=kb([["⬅️ Back", "🏠 Menu"]]))
                return
                
            if txt not in publishers_for(st["exam"], st["subject"]):
                await update.message.reply_text("❌ Invalid publisher. Choose from buttons or add new.")
                return
                
            st["publisher"] = txt
            st["step"] = "choose_subfolder"
            await update.message.reply_text(
                f"{st['exam']} > {st['subject']} > {st['publisher']} – Select Sub-Folder or upload directly:",
                reply_markup=subfolders_kb(st["exam"], st["subject"], st["publisher"], include_add=True)
            )
            return
            
        if st["step"] == "choose_subfolder":
            if txt == "➕ Add New Sub-Folder":
                st["awaiting_new_subfolder_name"] = True
                await update.message.reply_text("✍️ Send the new sub-folder name:", reply_markup=kb([["⬅️ Back", "🏠 Menu"]]))
                return
            elif txt == "📁 Upload Directly":
                st["upload_active"] = True
                st["step"] = "choose_file"
                await update.message.reply_text(
                    f"📤 Upload mode ON for {st['exam']} > {st['subject']} > {st['publisher']}\nSend files now. Use /done when finished.", 
                    reply_markup=kb([["⬅️ Back", "🏠 Menu"]])
                )
                return
                
            if txt not in subfolders_for(st["exam"], st["subject"], st["publisher"]):
                await update.message.reply_text("❌ Invalid sub-folder. Choose from buttons or add new.")
                return
                
            st["subfolder"] = txt
            st["upload_active"] = True
            st["step"] = "choose_file"
            await update.message.reply_text(
                f"📤 Upload mode ON for {st['exam']} > {st['subject']} > {st['publisher']} > {st['subfolder']}\nSend files now. Use /done when finished.", 
                reply_markup=kb([["⬅️ Back", "🏠 Menu"]])
            )
            return
            
        if st["step"] == "choose_file":
            await update.message.reply_text("ℹ️ Send PDF/Image/Video files. Use /done when finished.")
            return

    if st.get("mode") == "delete_publisher":
        if st["step"] == "choose_exam":
            if txt not in exams_from_data():
                await update.message.reply_text("❌ Invalid exam. Choose from buttons.")
                return
                
            st["exam"] = txt
            st["step"] = "choose_subject"
            await update.message.reply_text(f"{st['exam']} – Select Subject:", reply_markup=subjects_kb(st["exam"]))
            return
            
        if st["step"] == "choose_subject":
            if txt not in subjects_for_exam(st["exam"]):
                await update.message.reply_text("❌ Invalid subject. Choose from buttons.")
                return
                
            st["subject"] = txt
            st["step"] = "choose_publisher"
            await update.message.reply_text(f"{st['exam']} > {st['subject']} – Select Publisher to DELETE:", reply_markup=publishers_kb(st["exam"], st["subject"], include_add=False))
            return
            
        if st["step"] == "choose_publisher":
            if txt not in publishers_for(st["exam"], st["subject"]):
                await update.message.reply_text("❌ Invalid publisher. Choose from buttons.")
                return
                
            del MATERIALS[st["exam"]][st["subject"]][txt]
            save_materials()
            await backup_data_to_channel(context.bot)
            await update.message.reply_text(f"✅ Deleted publisher \"{txt}\" from {st['exam']} > {st['subject']}", reply_markup=main_menu_kb())
            reset_state(uid)
            return

    if st.get("mode") == "delete_file":
        if st["step"] == "choose_exam":
            if txt not in exams_from_data():
                await update.message.reply_text("❌ Invalid exam. Choose from buttons.")
                return
                
            st["exam"] = txt
            st["step"] = "choose_subject"
            await update.message.reply_text(f"{st['exam']} – Select Subject:", reply_markup=subjects_kb(st["exam"]))
            return
            
        if st["step"] == "choose_subject":
            if txt not in subjects_for_exam(st["exam"]):
                await update.message.reply_text("❌ Invalid subject. Choose from buttons.")
                return
                
            st["subject"] = txt
            st["step"] = "choose_publisher"
            await update.message.reply_text(f"{st['exam']} > {st['subject']} – Select Publisher:", reply_markup=publishers_kb(st["exam"], st["subject"], include_add=False))
            return
            
        if st["step"] == "choose_publisher":
            if txt not in publishers_for(st["exam"], st["subject"]):
                await update.message.reply_text("❌ Invalid publisher. Choose from buttons.")
                return
                
            st["publisher"] = txt
            st["step"] = "choose_subfolder_delete"
            subfolders = subfolders_for(st["exam"], st["subject"], st["publisher"])
            if subfolders:
                await update.message.reply_text(f"{st['exam']} > {st['subject']} > {st['publisher']} – Select Sub-Folder:", reply_markup=subfolders_kb(st["exam"], st["subject"], st["publisher"], include_add=False))
            else:
                st["step"] = "choose_file"
                items = MATERIALS.get(st["exam"], {}).get(st["subject"], {}).get(st["publisher"], [])
                if not items:
                    await update.message.reply_text("⚠️ No files in this publisher.")
                    return
                    
                lines = ["Select file number to DELETE:"]
                for i, it in enumerate(items, start=1):
                    label = it.get("name") or it.get("type") or "file"
                    lines.append(f"{i}. {label}")
                    
                await update.message.reply_text("\n".join(lines), reply_markup=kb([["⬅️ Back", "🏠 Menu"]]))
            return
            
        if st["step"] == "choose_subfolder_delete":
            if txt == "📁 Upload Directly":
                st["step"] = "choose_file"
                items = MATERIALS.get(st["exam"], {}).get(st["subject"], {}).get(st["publisher"], [])
                if not items:
                    await update.message.reply_text("⚠️ No files in this publisher.")
                    return
                    
                lines = ["Select file number to DELETE:"]
                for i, it in enumerate(items, start=1):
                    label = it.get("name") or it.get("type") or "file"
                    lines.append(f"{i}. {label}")
                    
                await update.message.reply_text("\n".join(lines), reply_markup=kb([["⬅️ Back", "🏠 Menu"]]))
                return
                
            if txt not in subfolders_for(st["exam"], st["subject"], st["publisher"]):
                await update.message.reply_text("❌ Invalid sub-folder. Choose from buttons.")
                return
                
            st["subfolder"] = txt
            st["step"] = "choose_file"
            folder_key = f"_folder:{st['subfolder']}"
            items = MATERIALS.get(st["exam"], {}).get(st["subject"], {}).get(st["publisher"], {}).get(folder_key, [])
            if not items:
                await update.message.reply_text("⚠️ No files in this sub-folder.")
                return
                
            lines = ["Select file number to DELETE:"]
            for i, it in enumerate(items, start=1):
                label = it.get("name") or it.get("type") or "file"
                lines.append(f"{i}. {label}")
                
            await update.message.reply_text("\n".join(lines), reply_markup=kb([["⬅️ Back", "🏠 Menu"]]))
            return
            
        if st["step"] == "choose_file":
            try:
                num = int(txt)
            except ValueError:
                await update.message.reply_text("❌ Send a valid file number.")
                return
                
            if st.get("subfolder"):
                folder_key = f"_folder:{st['subfolder']}"
                items = MATERIALS.get(st["exam"], {}).get(st["subject"], {}).get(st["publisher"], {}).get(folder_key, [])
            else:
                items = MATERIALS.get(st["exam"], {}).get(st["subject"], {}).get(st["publisher"], [])
                
            if num < 1 or num > len(items):
                await update.message.reply_text("❌ Invalid file number.")
                return
                
            deleted = items.pop(num - 1)
            save_materials()
            await backup_data_to_channel(context.bot)
            await update.message.reply_text(f"✅ Deleted file: {deleted.get('name', 'file')}", reply_markup=main_menu_kb())
            reset_state(uid)
            return

    if st.get("mode") == "add_subject":
        if st["step"] == "ask_exam":
            st["exam"] = txt
            st["step"] = "ask_subject"
            await update.message.reply_text("Now send the subject name to add:")
            return
            
        if st["step"] == "ask_subject":
            subject = txt
            ensure_subject(st["exam"], subject)
            save_materials()
            await update.message.reply_text(f"✅ Added subject '{subject}' to exam '{st['exam']}'.", reply_markup=main_menu_kb())
            reset_state(uid)
            return

    if st.get("mode") == "delete_subject":
        if st["step"] == "choose_exam":
            if txt not in exams_from_data():
                await update.message.reply_text("❌ Invalid exam. Choose from buttons.")
                return
                
            st["exam"] = txt
            st["step"] = "choose_subject_to_delete"
            await update.message.reply_text(f"{st['exam']} – Select Subject to DELETE:", reply_markup=subjects_kb(st["exam"]))
            return
            
        if st["step"] == "choose_subject_to_delete":
            if txt not in subjects_for_exam(st["exam"]):
                await update.message.reply_text("❌ Invalid subject. Choose from buttons.")
                return
                
            del MATERIALS[st["exam"]][txt]
            save_materials()
            await backup_data_to_channel(context.bot)
            await update.message.reply_text(f"✅ Deleted subject \"{txt}\" from {st['exam']}", reply_markup=main_menu_kb())
            reset_state(uid)
            return

    if st.get("mode") == "broadcast" and st.get("awaiting_text"):
        users = MATERIALS.get("_meta", {}).get("users", [])
        sent = 0
        failed = 0
        for user_id in users:
            try:
                await context.bot.send_message(user_id, txt)
                sent += 1
            except Exception as e:
                failed += 1
                
        await update.message.reply_text(f"📤 Broadcast result: Sent={sent}, Failed={failed}", reply_markup=main_menu_kb())
        reset_state(uid)
        return

    if st.get("mode") == "add_subfolder":
        if st["step"] == "choose_exam":
            if txt not in exams_from_data():
                await update.message.reply_text("❌ Invalid exam. Choose from buttons.")
                return
                
            st["exam"] = txt
            st["step"] = "choose_subject"
            await update.message.reply_text(f"{st['exam']} – Select Subject:", reply_markup=subjects_kb(st["exam"]))
            return
            
        if st["step"] == "choose_subject":
            if txt not in subjects_for_exam(st["exam"]):
                await update.message.reply_text("❌ Invalid subject. Choose from buttons.")
                return
                
            st["subject"] = txt
            st["step"] = "choose_publisher"
            await update.message.reply_text(f"{st['exam']} > {st['subject']} – Select Publisher:", reply_markup=publishers_kb(st["exam"], st["subject"], include_add=False))
            return
            
        if st["step"] == "choose_publisher":
            if txt not in publishers_for(st["exam"], st["subject"]):
                await update.message.reply_text("❌ Invalid publisher. Choose from buttons.")
                return
                
            st["publisher"] = txt
            st["step"] = "ask_subfolder_name"
            await update.message.reply_text("✍️ Send the new sub-folder name:", reply_markup=kb([["⬅️ Back", "🏠 Menu"]]))
            return
            
        if st["step"] == "ask_subfolder_name":
            new_folder = txt
            folder_key = f"_folder:{new_folder}"
            if folder_key in MATERIALS[st["exam"]][st["subject"]][st["publisher"]]:
                await update.message.reply_text("⚠️ Sub-folder already exists. Choose another name.")
                return
                
            ensure_subfolder(st["exam"], st["subject"], st["publisher"], new_folder)
            save_materials()
            await update.message.reply_text(f"✅ Sub-folder \"{new_folder}\" created under {st['exam']} > {st['subject']} > {st['publisher']}", reply_markup=main_menu_kb())
            reset_state(uid)
            return

    # =================== PUBLIC BROWSING ===================

    if txt == "📘 IIT JEE":
        st["exam"] = "IIT JEE"
        st["step"] = "choose_subject"
        await update.message.reply_text(f"{st['exam']} – Select Subject:", reply_markup=subjects_kb(st["exam"]))
        return
        
    if txt == "📗 NEET":
        st["exam"] = "NEET"
        st["step"] = "choose_subject"
        await update.message.reply_text(f"{st['exam']} – Select Subject:", reply_markup=subjects_kb(st["exam"]))
        return
        
    if txt == "👥 Community":
        await update.message.reply_text("Join our community: https://t.me/+wJN3YpJ4c3U4YzI9")
        return
        
    if txt == "ℹ️ Credits":
        await update.message.reply_text("Bot by @MrJaggiX\nFor queries/suggestions, contact @MrJaggiX")
        return

    # Handle subject selection for browsing
    if st.get("step") == "choose_subject" and st.get("exam"):
        if txt not in subjects_for_exam(st["exam"]):
            await update.message.reply_text("❌ Invalid subject. Choose from buttons.")
            return
            
        st["subject"] = txt
        st["step"] = "choose_publisher"
        await update.message.reply_text(f"{st['exam']} > {st['subject']} – Select Publisher:", reply_markup=publishers_kb(st["exam"], st["subject"], include_add=False))
        return

    # Handle publisher selection for browsing
    if st.get("step") == "choose_publisher" and st.get("exam") and st.get("subject"):
        if txt not in publishers_for(st["exam"], st["subject"]):
            await update.message.reply_text("❌ Invalid publisher. Choose from buttons.")
            return
            
        st["publisher"] = txt
        st["step"] = "choose_subfolder"
        await update.message.reply_text(
            f"{st['exam']} > {st['subject']} > {st['publisher']} – Select Sub-Folder:",
            reply_markup=subfolders_kb(st["exam"], st["subject"], st["publisher"], include_add=False)
        )
        return

    # Handle sub-folder selection for browsing
    if st.get("step") == "choose_subfolder" and st.get("exam") and st.get("subject") and st.get("publisher"):
        if txt == "📁 Upload Directly":
            st["step"] = "browse_files"
            items = MATERIALS.get(st["exam"], {}).get(st["subject"], {}).get(st["publisher"], [])
            if not items:
                await update.message.reply_text("⚠️ No files in this publisher.")
                return
                
            await send_file_list(update, items, 0)
            return
            
        if txt not in subfolders_for(st["exam"], st["subject"], st["publisher"]):
            await update.message.reply_text("❌ Invalid sub-folder. Choose from buttons.")
            return
            
        st["subfolder"] = txt
        st["step"] = "browse_files"
        folder_key = f"_folder:{st['subfolder']}"
        items = MATERIALS.get(st["exam"], {}).get(st["subject"], {}).get(st["publisher"], {}).get(folder_key, [])
        if not items:
            await update.message.reply_text("⚠️ No files in this sub-folder.")
            return
            
        await send_file_list(update, items, 0)
        return

    # Handle file browsing navigation
    if st.get("step") == "browse_files":
        if txt.isdigit():
            # File selection
            if st.get("subfolder"):
                folder_key = f"_folder:{st['subfolder']}"
                items = MATERIALS.get(st["exam"], {}).get(st["subject"], {}).get(st["publisher"], {}).get(folder_key, [])
            else:
                items = MATERIALS.get(st["exam"], {}).get(st["subject"], {}).get(st["publisher"], [])
                
            num = int(txt) - 1
            if num < 0 or num >= len(items):
                await update.message.reply_text("❌ Invalid file number.")
                return
                
            file_info = items[num]
            file_id = file_info["id"]
            ftype = file_info["type"]
            caption = file_info.get("caption", "")
            
            if ftype == "document":
                await update.message.reply_document(file_id, caption=caption)
            elif ftype == "photo":
                await update.message.reply_photo(file_id, caption=caption)
            elif ftype == "video":
                await update.message.reply_video(file_id, caption=caption)
            return
            
        elif txt in ["Next ➡️", "⬅️ Previous"]:
            # Navigation
            current_page = st.get("browse_page", 0)
            if st.get("subfolder"):
                folder_key = f"_folder:{st['subfolder']}"
                items = MATERIALS.get(st["exam"], {}).get(st["subject"], {}).get(st["publisher"], {}).get(folder_key, [])
            else:
                items = MATERIALS.get(st["exam"], {}).get(st["subject"], {}).get(st["publisher"], [])
                
            total_pages = (len(items) + 9) // 10
            
            if txt == "Next ➡️":
                current_page = (current_page + 1) % total_pages
            else:
                current_page = (current_page - 1) % total_pages
                
            st["browse_page"] = current_page
            await send_file_list(update, items, current_page)
            return

    # If no special mode, show main menu
    await update.message.reply_text("Choose an option 👇", reply_markup=main_menu_kb())

async def send_file_list(update, items, page):
    start_idx = page * 10
    end_idx = start_idx + 10
    page_items = items[start_idx:end_idx]
    
    lines = [f"📁 Files ({page+1}/{(len(items)+9)//10}):"]
    for i, it in enumerate(page_items, start=start_idx+1):
        label = it.get("name") or it.get("type") or "file"
        lines.append(f"{i}. {label}")
        
    lines.append("\nSend file number to download.")
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append("⬅️ Previous")
    if end_idx < len(items):
        nav_buttons.append("Next ➡️")
        
    if nav_buttons:
        lines.append("Use buttons to navigate.")
        keyboard = [nav_buttons, ["⬅️ Back", "🏠 Menu"]]
    else:
        keyboard = [["⬅️ Back", "🏠 Menu"]]
        
    await update.message.reply_text("\n".join(lines), reply_markup=kb(keyboard))

# =================== BOT SETUP ===================

async def post_init(application):
    """Load data from channel backup on bot startup"""
    print("Bot started, checking for channel backup...")
    data = await load_data_from_channel(application.bot)
    if data:
        global MATERIALS
        MATERIALS = data
        save_materials()  # Save to local file as well
        print("Data loaded from channel backup on startup")
    else:
        print("Using existing data on startup")

def main():
    if not TOKEN:
        print("❌ BOT_TOKEN not set in environment.")
        return
        
    app = Application.builder().token(TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", start))
    app.add_handler(CommandHandler("addmaterial", cmd_addmaterial))
    app.add_handler(CommandHandler("deletefile", cmd_deletefile))
    app.add_handler(CommandHandler("deletepublisher", cmd_deletepublisher))
    app.add_handler(CommandHandler("addsubject", cmd_addsubject))
    app.add_handler(CommandHandler("deletesubject", cmd_deletesubject))
    app.add_handler(CommandHandler("addadmin", cmd_addadmin))
    app.add_handler(CommandHandler("removeadmin", cmd_removeadmin))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CommandHandler("addsubfolder", cmd_addsubfolder))
    app.add_handler(CommandHandler("done", cmd_done))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("backup", cmd_backup))
    app.add_handler(CommandHandler("restore", cmd_restore))

    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO | filters.VIDEO, handle_files))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()