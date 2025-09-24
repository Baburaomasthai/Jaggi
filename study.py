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
from pymongo import MongoClient
from bson import ObjectId

# =================== MONGODB CONFIG ===================

MONGO_URI = "mongodb://JaggiX9:JaggiX9@cluster0-shard-00-00.p2yvakt.mongodb.net:27017,cluster0-shard-00-01.p2yvakt.mongodb.net:27017,cluster0-shard-00-02.p2yvakt.mongodb.net:27017/?ssl=true&replicaSet=atlas-1fjopd-shard-0&authSource=admin&retryWrites=true&w=majority"  # Add your MongoDB URI to environment variables
DB_NAME = "study_bot"
COLLECTION_NAME = "materials"

# MongoDB client
client = MongoClient(MONGO_URI)
db = client[DB_NAME]
materials_collection = db[COLLECTION_NAME]

# =================== CONFIG ===================

TOKEN = "7931829452:AAEF2zYePG5w3EY3cRwsv6jqxZawH_0HXKI"
OWNER_ID = "6651946441"
DATA_FILE = "materials.json"

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
        # Try to load from MongoDB first
        db_data = materials_collection.find_one({"_id": "main_data"})
        if db_data:
            # Remove MongoDB _id field before returning
            db_data.pop('_id', None)
            return db_data
        
        # Fallback to local file if MongoDB doesn't have data
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Save to MongoDB for future use
            save_to_mongodb(data)
        else:
            data = DEFAULT_STRUCTURE.copy()
            save_to_mongodb(data)
            
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

def save_to_mongodb(data: Dict[str, Any]) -> None:
    try:
        # Store with a fixed _id for easy retrieval
        materials_collection.replace_one(
            {"_id": "main_data"}, 
            {"_id": "main_data", **data}, 
            upsert=True
        )
    except Exception as e:
        print(f"Error saving to MongoDB: {e}")

def save_materials() -> None:
    try:
        # Save to MongoDB
        save_to_mongodb(MATERIALS)
        
        # Also keep local backup (optional)
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(MATERIALS, f, ensure_ascii=False, indent=2)
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

    if txt in ("🏠 Menu", "Menu", "/menu"):
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
            if txt == "📁 Main Folder":
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
            except ValueError:
                await update.message.reply_text("❌ Send a valid number from the list.")
                return
                
            if idx < 0 or idx >= len(items):
                await update.message.reply_text("❌ Number out of range.")
                return
                
            removed = items.pop(idx)
            save_materials()
            await update.message.reply_text(f"✅ Deleted: {removed.get('name') or removed.get('type')}")
            
            if not items:
                await update.message.reply_text("(Folder now empty)")
            else:
                lines = ["Remaining files:"]
                for i, it in enumerate(items, start=1):
                    label = it.get("name") or it.get("type") or "file"
                    lines.append(f"{i}. {label}")
                await update.message.reply_text("\n".join(lines))
            return

    if st.get("mode") == "add_subject":
        if st.get("step") == "ask_exam":
            exam = txt
            st["exam"] = exam
            st["step"] = "ask_subject"
            await update.message.reply_text(f"Send subject name to add under exam '{exam}':", reply_markup=kb([["⬅️ Back", "🏠 Menu"]]))
            return
            
        if st.get("step") == "ask_subject":
            subject = txt
            ensure_subject(st["exam"], subject)
            save_materials()
            await update.message.reply_text(f"✅ Subject '{subject}' added under exam '{st['exam']}'")
            reset_state(uid)
            return

    if st.get("mode") == "delete_subject":
        if st.get("step") == "choose_exam":
            if txt not in exams_from_data():
                await update.message.reply_text("❌ Invalid exam. Choose from buttons.")
                return
                
            st["exam"] = txt
            st["step"] = "choose_subject_to_delete"
            await update.message.reply_text(f"Select subject to DELETE from {txt}:", reply_markup=subjects_kb(txt))
            return
            
        if st.get("step") == "choose_subject_to_delete":
            if txt not in subjects_for_exam(st["exam"]):
                await update.message.reply_text("❌ Invalid subject.")
                return
                
            del MATERIALS[st["exam"]][txt]
            save_materials()
            await update.message.reply_text(f"✅ Deleted subject '{txt}' from exam '{st['exam']}'")
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
            await update.message.reply_text(f"Send sub-folder name to add under {st['exam']} > {st['subject']} > {st['publisher']}:", reply_markup=kb([["⬅️ Back", "🏠 Menu"]]))
            return
            
        if st["step"] == "ask_subfolder_name":
            subfolder = txt
            ensure_subfolder(st["exam"], st["subject"], st["publisher"], subfolder)
            save_materials()
            await update.message.reply_text(f"✅ Sub-folder '{subfolder}' added.")
            reset_state(uid)
            return

    if st.get("mode") == "broadcast" and st.get("awaiting_text"):
        users = MATERIALS.get("_meta", {}).get("users", [])
        sent = 0
        failed = 0
        for user_id in users:
            try:
                await context.bot.send_message(chat_id=user_id, text=txt)
                sent += 1
            except Exception as e:
                failed += 1
                print(f"Broadcast fail to {user_id}: {e}")
                
        await update.message.reply_text(f"📤 Broadcast result: Sent={sent}, Failed={failed}")
        reset_state(uid)
        return

    # PUBLIC BROWSING
    if txt in ("📘 IIT JEE", "📗 NEET", "👥 Community", "ℹ️ Credits"):
        if txt in ("📘 IIT JEE", "📗 NEET"):
            exam = "IIT JEE" if txt == "📘 IIT JEE" else "NEET"
            st["exam"] = exam
            st["step"] = "choose_subject"
            await update.message.reply_text(f"{exam} – Select Subject:", reply_markup=subjects_kb(exam))
            return
            
        elif txt == "👥 Community":
            await update.message.reply_text(
                "📢 Join our community for updates and discussions:\n\n"
                "🔗 @StudyMaterialHub_Group\n"
                "🔗 @StudyMaterialHub_Channel"
            )
            return
            
        elif txt == "ℹ️ Credits":
            await update.message.reply_text(
                "🤖 Bot by @MrJaggiX\n\n"
                "📚 This bot helps you access study materials for IIT JEE & NEET.\n"
                "🔧 Built with Python + Telegram Bot API"
            )
            return

    if st.get("step") == "choose_subject" and st.get("exam"):
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

    if st.get("step") == "choose_subfolder" and st.get("exam") and st.get("subject") and st.get("publisher"):
        if txt == "📁 Main Folder":
            st["step"] = "browse_files"
            items = MATERIALS.get(st["exam"], {}).get(st["subject"], {}).get(st["publisher"], [])
            if not items:
                await update.message.reply_text("⚠️ No files in this publisher.")
                return
                
            st["current_items"] = items
            st["current_index"] = 0
            await send_file(update, context, items[0])
            return
        elif txt in subfolders_for(st["exam"], st["subject"], st["publisher"]):
            st["subfolder"] = txt
            st["step"] = "browse_files"
            folder_key = f"_folder:{txt}"
            items = MATERIALS.get(st["exam"], {}).get(st["subject"], {}).get(st["publisher"], {}).get(folder_key, [])
            if not items:
                await update.message.reply_text("⚠️ No files in this sub-folder.")
                return
                
            st["current_items"] = items
            st["current_index"] = 0
            await send_file(update, context, items[0])
            return
        else:
            await update.message.reply_text("❌ Invalid sub-folder. Choose from buttons.")
            return

    if st.get("step") == "browse_files":
        if txt == "➡️ Next":
            items = st["current_items"]
            idx = st["current_index"] + 1
            if idx >= len(items):
                idx = 0
            st["current_index"] = idx
            await send_file(update, context, items[idx])
            return
        elif txt == "⬅️ Prev":
            items = st["current_items"]
            idx = st["current_index"] - 1
            if idx < 0:
                idx = len(items) - 1
            st["current_index"] = idx
            await send_file(update, context, items[idx])
            return
        elif txt == "⬅️ Back":
            if st.get("subfolder"):
                st["step"] = "choose_subfolder"
                st["subfolder"] = None
                await update.message.reply_text(
                    f"{st['exam']} > {st['subject']} > {st['publisher']} – Select Sub-Folder:",
                    reply_markup=subfolders_kb(st["exam"], st["subject"], st["publisher"], include_add=False)
                )
            else:
                st["step"] = "choose_publisher"
                st["publisher"] = None
                await update.message.reply_text(
                    f"{st['exam']} > {st['subject']} – Select Publisher:",
                    reply_markup=publishers_kb(st["exam"], st["subject"], include_add=False)
                )
            return
        elif txt == "🏠 Menu":
            reset_state(uid)
            await update.message.reply_text("Main Menu:", reply_markup=main_menu_kb())
            return

    # If no state matches, show main menu
    await update.message.reply_text("Choose an option 👇", reply_markup=main_menu_kb())

async def send_file(update: Update, context: ContextTypes.DEFAULT_TYPE, item: Dict):
    file_id = item["id"]
    ftype = item["type"]
    caption = item.get("caption", "")
    name = item.get("name", "file")
    
    nav_buttons = [["⬅️ Prev", "➡️ Next"], ["⬅️ Back", "🏠 Menu"]]
    
    try:
        if ftype == "document":
            await update.message.reply_document(file_id, caption=caption, reply_markup=kb(nav_buttons))
        elif ftype == "photo":
            await update.message.reply_photo(file_id, caption=caption, reply_markup=kb(nav_buttons))
        elif ftype == "video":
            await update.message.reply_video(file_id, caption=caption, reply_markup=kb(nav_buttons))
        else:
            await update.message.reply_text(f"File: {name}\n{caption}", reply_markup=kb(nav_buttons))
    except Exception as e:
        await update.message.reply_text(f"❌ Error sending file: {e}")

# =================== MAIN ===================

def main():
    if not TOKEN:
        print("❌ BOT_TOKEN not set in environment.")
        return

    app_bot = Application.builder().token(TOKEN).build()

    # commands
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("addmaterial", cmd_addmaterial))
    app_bot.add_handler(CommandHandler("deletefile", cmd_deletefile))
    app_bot.add_handler(CommandHandler("deletepublisher", cmd_deletepublisher))
    app_bot.add_handler(CommandHandler("addsubject", cmd_addsubject))
    app_bot.add_handler(CommandHandler("deletesubject", cmd_deletesubject))
    app_bot.add_handler(CommandHandler("addadmin", cmd_addadmin))
    app_bot.add_handler(CommandHandler("removeadmin", cmd_removeadmin))
    app_bot.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app_bot.add_handler(CommandHandler("addsubfolder", cmd_addsubfolder))
    app_bot.add_handler(CommandHandler("done", cmd_done))
    app_bot.add_handler(CommandHandler("cancel", cmd_cancel))

    # files
    app_bot.add_handler(MessageHandler(filters.ATTACHMENT | filters.PHOTO | filters.VIDEO, handle_files))

    # text
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    print("🤖 Bot is running...")
    app_bot.run_polling()

if __name__ == "__main__":
    main()
