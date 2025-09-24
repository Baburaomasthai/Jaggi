import json
import os
import asyncio
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

TOKEN = "7931829452:AAEF2zYePG5w3EY3cRwsv6jqxZawH_0HXKI"
OWNER_ID = "6651946441"
DATA_FILE = "materials.json"
BACKUP_CHANNEL_ID = "-1002565934191"  # Channel ID for backups

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

def load_materials() -> Dict[str, Any]:
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = DEFAULT_STRUCTURE.copy()
            
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
    except Exception as e:
        print(f"Error saving materials: {e}")

MATERIALS: Dict[str, Any] = load_materials()

# user_state keeps temporary interaction states
user_state: Dict[int, Dict[str, Any]] = {}

# =================== BACKUP/RESTORE SYSTEM ===================

async def backup_data(context: ContextTypes.DEFAULT_TYPE):
    """Backup data to Telegram channel"""
    if not BACKUP_CHANNEL_ID:
        return
        
    try:
        data_str = json.dumps(MATERIALS, ensure_ascii=False, indent=2)
        # Create backup message with metadata
        backup_msg = f"🔰 STUDY BOT BACKUP 🔰\nTimestamp: {context.bot_data.get('backup_timestamp', 'N/A')}\n\n"
        
        # Send as document if too large, otherwise as text
        if len(data_str) > 4000:
            # Save to file and send as document
            with open("backup.json", "w", encoding="utf-8") as f:
                f.write(data_str)
            with open("backup.json", "rb") as f:
                await context.bot.send_document(
                    chat_id=BACKUP_CHANNEL_ID,
                    document=f,
                    filename=f"studybot_backup.json",
                    caption=backup_msg
                )
            os.remove("backup.json")
        else:
            await context.bot.send_message(
                chat_id=BACKUP_CHANNEL_ID,
                text=backup_msg + f"```json\n{data_str}\n```",
                parse_mode="Markdown"
            )
        print("✅ Backup completed successfully")
    except Exception as e:
        print(f"❌ Backup error: {e}")

async def restore_data(context: ContextTypes.DEFAULT_TYPE):
    """Restore data from latest backup in Telegram channel"""
    if not BACKUP_CHANNEL_ID:
        return False
        
    try:
        # Get latest message from backup channel
        messages = await context.bot.get_chat_history(chat_id=BACKUP_CHANNEL_ID, limit=10)
        
        for message in messages:
            # Check if message contains backup data
            if message.document and "backup" in (message.document.file_name or "").lower():
                # Download and restore from document
                file = await message.document.get_file()
                await file.download_to_drive("restore_backup.json")
                
                with open("restore_backup.json", "r", encoding="utf-8") as f:
                    restored_data = json.load(f)
                
                # Update global MATERIALS
                global MATERIALS
                MATERIALS.update(restored_data)
                save_materials()
                
                os.remove("restore_backup.json")
                print("✅ Data restored from backup")
                return True
                
            elif message.text and "STUDY BOT BACKUP" in message.text:
                # Extract JSON from text message
                import re
                json_match = re.search(r'```json\n(.*?)\n```', message.text, re.DOTALL)
                if json_match:
                    restored_data = json.loads(json_match.group(1))
                    global MATERIALS
                    MATERIALS.update(restored_data)
                    save_materials()
                    print("✅ Data restored from backup")
                    return True
                    
        print("❌ No valid backup found")
        return False
    except Exception as e:
        print(f"❌ Restore error: {e}")
        return False

async def scheduled_backup(context: ContextTypes.DEFAULT_TYPE):
    """Scheduled backup task"""
    context.bot_data['backup_timestamp'] = str(asyncio.get_event_loop().time())
    await backup_data(context)

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
    """Manual backup command - Owner only"""
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("❌ Only bot owner can backup data.")
        return
        
    await update.message.reply_text("🔄 Creating backup...")
    await backup_data(context)
    await update.message.reply_text("✅ Backup completed!")

async def cmd_restore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manual restore command - Owner only"""
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("❌ Only bot owner can restore data.")
        return
        
    await update.message.reply_text("🔄 Restoring from backup...")
    success = await restore_data(context)
    if success:
        await update.message.reply_text("✅ Data restored successfully!")
    else:
        await update.message.reply_text("❌ Failed to restore data. No backup found.")

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

    if txt in ("🏠 Menu", "/menu"):
        reset_state(uid)
        await update.message.reply_text("Main Menu:", reply_markup=main_menu_kb())
        return
        
    if txt == "⬅️ Back":
        if st["step"] == "choose_subject":
            st["step"] = "choose_exam"
            st["exam"] = None
            exams = exams_from_data()
            rows = chunk(exams, 2)
            rows.append(["🏠 Menu"])
            await update.message.reply_text("Select Exam:", reply_markup=kb(rows))
            return
        elif st["step"] == "choose_publisher":
            st["step"] = "choose_subject"
            st["subject"] = None
            st["publisher"] = None
            await update.message.reply_text(f"{st['exam']} – Select Subject:", reply_markup=subjects_kb(st["exam"]))
            return
        elif st["step"] == "choose_subfolder":
            st["step"] = "choose_publisher"
            st["publisher"] = None
            st["subfolder"] = None
            await update.message.reply_text(
                f"{st['exam']} > {st['subject']} – Select Publisher:",
                reply_markup=publishers_kb(st["exam"], st["subject"], include_add=(st["mode"]=="add"), include_folder=True)
            )
            return
        elif st["step"] == "choose_file":
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
            await update.message.reply_text(f"✅ Deleted publisher \"{txt}\" from {st['exam']} > {st['subject']}", reply_markup=publishers_kb(st["exam"], st["subject"], include_add=False))
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
            await update.message.reply_text(f"{st['exam']} > {st['subject']} > {st['publisher']} – Select Sub-Folder:", reply_markup=subfolders_kb(st["exam"], st["subject"], st["publisher"], include_add=False))
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
            elif txt in subfolders_for(st["exam"], st["subject"], st["publisher"]):
                st["subfolder"] = txt
                st["step"] = "choose_file"
                folder_key = f"_folder:{txt}"
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
            else:
                await update.message.reply_text("❌ Invalid sub-folder. Choose from buttons.")
                return
            
        if st["step"] == "choose_file":
            if st.get("subfolder"):
                folder_key = f"_folder:{st['subfolder']}"
                items = MATERIALS.get(st["exam"], {}).get(st["subject"], {}).get(st["publisher"], {}).get(folder_key, [])
            else:
                items = MATERIALS.get(st["exam"], {}).get(st["subject"], {}).get(st["publisher"], [])
                
            try:
                idx = int(txt) - 1
                if idx < 0 or idx >= len(items):
                    await update.message.reply_text("❌ Invalid file number.")
                    return
                    
                removed = items.pop(idx)
                save_materials()
                await update.message.reply_text(f"✅ Deleted file: {removed.get('name', 'file')}")
                
                if not items:
                    await update.message.reply_text("ℹ️ No more files left here.", reply_markup=kb([["⬅️ Back", "🏠 Menu"]]))
                    return
                    
                lines = ["Remaining files:"]
                for i, it in enumerate(items, start=1):
                    label = it.get("name") or it.get("type") or "file"
                    lines.append(f"{i}. {label}")
                    
                await update.message.reply_text("\n".join(lines), reply_markup=kb([["⬅️ Back", "🏠 Menu"]]))
            except ValueError:
                await update.message.reply_text("❌ Send a valid file number.")

    if st.get("mode") == "add_subject":
        if st["step"] == "ask_exam":
            st["exam"] = txt
            st["step"] = "ask_subject"
            await update.message.reply_text("✍️ Now send the subject name to add:")
            return
            
        if st["step"] == "ask_subject":
            subject = txt
            ensure_subject(st["exam"], subject)
            save_materials()
            await update.message.reply_text(f"✅ Subject '{subject}' added under exam '{st['exam']}'.")
            reset_state(uid)
            return

    if st.get("mode") == "delete_subject":
        if st["step"] == "choose_exam":
            if txt not in exams_from_data():
                await update.message.reply_text("❌ Invalid exam. Choose from buttons.")
                return
                
            st["exam"] = txt
            st["step"] = "choose_subject"
            await update.message.reply_text(f"{st['exam']} – Select Subject to DELETE:", reply_markup=subjects_kb(st["exam"]))
            return
            
        if st["step"] == "choose_subject":
            if txt not in subjects_for_exam(st["exam"]):
                await update.message.reply_text("❌ Invalid subject. Choose from buttons.")
                return
                
            del MATERIALS[st["exam"]][txt]
            save_materials()
            await update.message.reply_text(f"✅ Deleted subject \"{txt}\" from {st['exam']}")
            reset_state(uid)
            return

    if st.get("mode") == "broadcast" and st.get("awaiting_text"):
        text_to_send = txt
        users = MATERIALS.get("_meta", {}).get("users", [])
        success = 0
        fail = 0
        
        for user_id in users:
            try:
                await context.bot.send_message(chat_id=user_id, text=text_to_send)
                success += 1
            except Exception as e:
                fail += 1
                
        await update.message.reply_text(f"📢 Broadcast result:\n✅ Sent: {success}\n❌ Failed: {fail}")
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
            await update.message.reply_text("✍️ Send the new sub-folder name:")
            return
            
        if st["step"] == "ask_subfolder_name":
            new_folder = txt
            folder_key = f"_folder:{new_folder}"
            if folder_key in MATERIALS[st["exam"]][st["subject"]][st["publisher"]]:
                await update.message.reply_text("⚠️ Sub-folder already exists. Choose another name.")
                return
                
            ensure_subfolder(st["exam"], st["subject"], st["publisher"], new_folder)
            save_materials()
            await update.message.reply_text(f"✅ Sub-folder \"{new_folder}\" added to {st['exam']} > {st['subject']} > {st['publisher']}")
            reset_state(uid)
            return

    # =================== PUBLIC BROWSING ===================
    if not st.get("mode"):
        if txt == "📘 IIT JEE":
            st["mode"] = "browse"
            st["exam"] = "IIT JEE"
            st["step"] = "choose_subject"
            await update.message.reply_text("IIT JEE – Select Subject:", reply_markup=subjects_kb("IIT JEE"))
            return
            
        if txt == "📗 NEET":
            st["mode"] = "browse"
            st["exam"] = "NEET"
            st["step"] = "choose_subject"
            await update.message.reply_text("NEET – Select Subject:", reply_markup=subjects_kb("NEET"))
            return
            
        if txt == "👥 Community":
            await update.message.reply_text(
                "Join our community:\n"
                "📢 Main Channel: @MrJaggiX\n"
                "💬 Discussion Group: @MrJaggiX_Chat\n"
                "🤖 Bot Updates: @MrJaggiX_Bots"
            )
            return
            
        if txt == "ℹ️ Credits":
            await update.message.reply_text(
                "🤖 Bot by @MrJaggiX\n"
                "📚 Study materials curated by community\n"
                "🔰 Powered by Python & python-telegram-bot"
            )
            return

    if st.get("mode") == "browse":
        if st["step"] == "choose_subject":
            if txt not in subjects_for_exam(st["exam"]):
                await update.message.reply_text("❌ Invalid subject. Choose from buttons.")
                return
                
            st["subject"] = txt
            st["step"] = "choose_publisher"
            await update.message.reply_text(
                f"{st['exam']} > {st['subject']} – Select Publisher:",
                reply_markup=publishers_kb(st["exam"], st["subject"], include_add=False)
            )
            return
            
        if st["step"] == "choose_publisher":
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
            
        if st["step"] == "choose_subfolder":
            if txt == "📁 Upload Directly":
                st["step"] = "choose_file"
                items = MATERIALS.get(st["exam"], {}).get(st["subject"], {}).get(st["publisher"], [])
                if not items:
                    await update.message.reply_text("⚠️ No files in this publisher.")
                    return
                    
                lines = ["Select file number to download:"]
                for i, it in enumerate(items, start=1):
                    label = it.get("name") or it.get("type") or "file"
                    lines.append(f"{i}. {label}")
                    
                await update.message.reply_text("\n".join(lines), reply_markup=kb([["⬅️ Back", "🏠 Menu"]]))
                return
            elif txt in subfolders_for(st["exam"], st["subject"], st["publisher"]):
                st["subfolder"] = txt
                st["step"] = "choose_file"
                folder_key = f"_folder:{txt}"
                items = MATERIALS.get(st["exam"], {}).get(st["subject"], {}).get(st["publisher"], {}).get(folder_key, [])
                if not items:
                    await update.message.reply_text("⚠️ No files in this sub-folder.")
                    return
                    
                lines = ["Select file number to download:"]
                for i, it in enumerate(items, start=1):
                    label = it.get("name") or it.get("type") or "file"
                    lines.append(f"{i}. {label}")
                    
                await update.message.reply_text("\n".join(lines), reply_markup=kb([["⬅️ Back", "🏠 Menu"]]))
                return
            else:
                await update.message.reply_text("❌ Invalid sub-folder. Choose from buttons.")
                return
            
        if st["step"] == "choose_file":
            if st.get("subfolder"):
                folder_key = f"_folder:{st['subfolder']}"
                items = MATERIALS.get(st["exam"], {}).get(st["subject"], {}).get(st["publisher"], {}).get(folder_key, [])
            else:
                items = MATERIALS.get(st["exam"], {}).get(st["subject"], {}).get(st["publisher"], [])
                
            try:
                idx = int(txt) - 1
                if idx < 0 or idx >= len(items):
                    await update.message.reply_text("❌ Invalid file number.")
                    return
                    
                item = items[idx]
                file_id = item["id"]
                ftype = item["type"]
                caption = item.get("caption", "")
                
                if ftype == "document":
                    await update.message.reply_document(document=file_id, caption=caption)
                elif ftype == "photo":
                    await update.message.reply_photo(photo=file_id, caption=caption)
                elif ftype == "video":
                    await update.message.reply_video(video=file_id, caption=caption)
                    
            except ValueError:
                await update.message.reply_text("❌ Send a valid file number.")

# =================== MAIN ===================

async def post_init(application: Application):
    """Run after bot starts - Auto restore data"""
    print("🤖 Bot started - Attempting auto restore...")
    success = await restore_data(application)
    if success:
        print("✅ Data restored successfully from backup")
    else:
        print("ℹ️ No backup found or restore failed, starting with current data")
    
    # Schedule automatic backups every 6 hours
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(scheduled_backup, interval=6*3600, first=10)

def main():
    if not TOKEN:
        print("❌ BOT_TOKEN not set in environment.")
        return
        
    app = Application.builder().token(TOKEN).post_init(post_init).build()

    # Commands
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

    # File handler (for uploads)
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO | filters.VIDEO, handle_files))

    # Text handler (state machine + browsing)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
