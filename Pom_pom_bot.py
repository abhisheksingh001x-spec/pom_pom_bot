# bot.py
# Final all-in-one Telegram bot (copy-paste ready)
# Requirements: python-telegram-bot==21.4, httpx
#
# Provided token and owner id: (from user)
# BOT_TOKEN = "8234434490:AAFe8jRZeSxilpvVS0_9iejm3svDfouyvCg"
# OWNER_ID = 5912282643

import os
import sqlite3
import random
from datetime import datetime
import logging
import asyncio

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ---------------- CONFIG ----------------
DB_NAME = "bot.db"
BOT_TOKEN = "8234434490:AAFe8jRZeSxilpvVS0_9iejm3svDfouyvCg"
OWNER_ID = 5912282643

# ---------------- LOGGING ----------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------------- DB helpers ----------------
def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS owner (
        user_id INTEGER
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS admins (
        user_id INTEGER UNIQUE
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS channels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        link TEXT UNIQUE,
        active INTEGER DEFAULT 1
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS storage_channels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER UNIQUE,
        title TEXT,
        active INTEGER DEFAULT 1
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS videos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id TEXT UNIQUE,
        caption TEXT,
        added_by INTEGER,
        added_at TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS sent (
        user_id INTEGER,
        video_id INTEGER,
        sent_at TEXT,
        PRIMARY KEY (user_id, video_id)
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        first_name TEXT,
        username TEXT,
        seen_at TEXT
    )
    """)
    # ensure owner row exists
    cur.execute("SELECT * FROM owner")
    if cur.fetchone() is None:
        cur.execute("INSERT INTO owner (user_id) VALUES (?)", (OWNER_ID,))
    conn.commit()
    conn.close()

init_db()

# ---------------- Helpers: owner/admin ----------------
def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID

def is_admin(user_id: int) -> bool:
    if is_owner(user_id):
        return True
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,))
    r = cur.fetchone()
    conn.close()
    return r is not None

def add_admin_db(user_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

def remove_admin_db(user_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM admins WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

async def user_joined_all_channels(bot, user_id: int) -> bool:
    chans = list_channels_db()

    for r in chans:
        link = r["link"]

        try:
            if link.startswith("http"):
                chat = "@" + link.rstrip("/").split("/")[-1]
            elif link.startswith("@"):
                chat = link
            else:
                chat = "@" + link

            member = await bot.get_chat_member(chat, user_id)
            if member.status not in ("member", "administrator", "creator"):
                return False
        except:
            return False

    return True

# ---------------- Channels DB ----------------
def add_channel_db(link: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO channels (link, active) VALUES (?, 1)", (link,))
    cur.execute("UPDATE channels SET active=1 WHERE link=?", (link,))
    conn.commit()
    conn.close()

import re

def _normalize_variants(identifier: str):
    v = identifier.strip()
    out = set()
    out.add(v)
    out.add(v.lstrip("@"))
    if v.startswith("https://"):
        out.add(v.replace("https://", "").rstrip("/"))
    if v.startswith("http://"):
        out.add(v.replace("http://", "").rstrip("/"))
    if v.startswith("t.me/"):
        out.add(v.replace("t.me/", "").rstrip("/"))
    if v.startswith("@"):
        out.add("https://t.me/" + v.lstrip("@"))
    out.add(v.replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/"))
    return out


def remove_channel_db(identifier: str) -> bool:
    conn = get_db()
    cur = conn.cursor()
    ident = identifier.strip()

    try:
        maybe = int(ident)
    except:
        maybe = None

    if maybe is not None:
        cur.execute("SELECT id FROM channels WHERE link=? OR id=?", (str(maybe), maybe))
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE channels SET active=0 WHERE id=?", (row["id"],))
            conn.commit()
            conn.close()
            return True

    variants = _normalize_variants(ident)
    for v in variants:
        cur.execute("SELECT id FROM channels WHERE link=? OR link LIKE ?", (v, f'%{v}%'))
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE channels SET active=0 WHERE id=?", (row["id"],))
            conn.commit()
            conn.close()
            return True

    uname = ident.lstrip("@")
    cur.execute("SELECT id FROM channels WHERE link LIKE ?", (f'%{uname}%',))
    row = cur.fetchone()
    if row:
        cur.execute("UPDATE channels SET active=0 WHERE id=?", (row["id"],))
        conn.commit()
        conn.close()
        return True

    conn.close()
    return False

def list_channels_db():
    """
    Return only active channels (active = 1) as list of rows.
    Each row: dict-like with keys 'id', 'link', 'active'
    """
    conn = get_db()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT id, link, active FROM channels WHERE active=1 ORDER BY id")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows
# ---------------- Storage channels ----------------
def add_storage_channel_db(chat_id: int, title: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO storage_channels (chat_id, title, active) VALUES (?, ?, 1)", (chat_id, title))
    cur.execute("UPDATE storage_channels SET active=1, title=? WHERE chat_id=?", (title, chat_id))
    conn.commit()
    conn.close()

def deactivate_storage_channel_db(identifier: str) -> bool:
    conn = get_db()
    cur = conn.cursor()
    ident = identifier.strip()

    try:
        maybe = int(ident)
    except:
        maybe = None

    if maybe is not None:
        cur.execute("SELECT id FROM storage_channels WHERE chat_id=? OR id=?", (maybe, maybe))
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE storage_channels SET active=0 WHERE id=?", (row["id"],))
            conn.commit()
            conn.close()
            return True

    variants = _normalize_variants(ident)
    for v in variants:
        cur.execute("SELECT id FROM storage_channels WHERE title=? OR title LIKE ?", (v, f'%{v}%'))
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE storage_channels SET active=0 WHERE id=?", (row["id"],))
            conn.commit()
            conn.close()
            return True

    uname = ident.lstrip("@")
    cur.execute("SELECT id FROM storage_channels WHERE title LIKE ?", (f'%{uname}%',))
    row = cur.fetchone()
    if row:
        cur.execute("UPDATE storage_channels SET active=0 WHERE id=?", (row["id"],))
        conn.commit()
        conn.close()
        return True

    conn.close()
    return False

def list_storage_channels_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, chat_id, title, active FROM storage_channels ORDER BY id")
    rows = cur.fetchall()
    conn.close()
    return rows

def is_storage_channel(chat_id: int) -> bool:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM storage_channels WHERE chat_id=? AND active=1", (chat_id,))
    r = cur.fetchone()
    conn.close()
    return r is not None

# ---------------- Video DB helpers ----------------
def add_video_row(file_id: str, caption: str = None, added_by: int = None):
    conn = get_db()
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    try:
        cur.execute("INSERT OR IGNORE INTO videos (file_id, caption, added_by, added_at) VALUES (?, ?, ?, ?)",
                    (file_id, caption or "", added_by, now))
    except Exception as e:
        logger.error("DB insert error: %s", e)
    conn.commit()
    conn.close()

def get_video_count():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as c FROM videos")
    count = cur.fetchone()["c"]
    conn.close()
    return count

def get_random_video_not_sent(user_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT v.id, v.file_id
        FROM videos v
        WHERE v.id NOT IN (SELECT video_id FROM sent WHERE user_id=?)
        ORDER BY RANDOM()
        LIMIT 1
    """, (user_id,))
    row = cur.fetchone()
    if row:
        conn.close()
        return row
    # if none left, clear user's sent list and return random
    cur.execute("DELETE FROM sent WHERE user_id=?", (user_id,))
    conn.commit()
    cur.execute("SELECT id, file_id FROM videos ORDER BY RANDOM() LIMIT 1")
    row = cur.fetchone()
    conn.close()
    return row

def mark_video_sent(user_id: int, video_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO sent (user_id, video_id, sent_at) VALUES (?, ?, ?)",
                (user_id, video_id, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()

async def _delete_message_after(bot, chat_id: int, message_id: int, delay_seconds: int = 300):
    """Wait delay_seconds then try to delete the message (silently ignore errors)."""
    try:
        await asyncio.sleep(delay_seconds)
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:
            # ignore if message already deleted or cannot delete
            return
    except asyncio.CancelledError:
        return

# ---------------- User tracking ----------------
def register_user_db(user_id: int, first_name: str = None, username: str = None):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO users (user_id, first_name, username, seen_at)
        VALUES (?, ?, ?, ?)
    """, (user_id, first_name or "", username or "", datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()

def get_all_user_ids():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users")
    rows = [r["user_id"] for r in cur.fetchall()]
    conn.close()
    return rows

# ---------------- UI helpers ----------------
def build_join_keyboard():
    """
    User ko dikhane ke liye JOIN buttons banata hai.
    Sirf active channels (active=1) hi show honge.
    """
    channels = list_channels_db()   # list of dicts: {'id','link','active'}

    keyboard = []
    for ch in channels:
        link = ch.get("link") or ""
        url = None
        if link.startswith("t.me/"):
            url = "https://" + link
        elif link.startswith("http://") or link.startswith("https://"):
            url = link
        elif link.startswith("@"):
            url = "https://t.me/" + link.lstrip("@")
        else:
            # attempt to form t.me link from plain username
            if link:
                url = "https://t.me/" + link.lstrip("@")

        if url:
            keyboard.append([InlineKeyboardButton(text="JOIN", url=url)])
        else:
            keyboard.append([InlineKeyboardButton(text="JOIN", callback_data="noop")])

    # Verify button at the end
    keyboard.append([InlineKeyboardButton(text="I Joined / Verify", callback_data="verify_join")])
    return InlineKeyboardMarkup(keyboard)
# ---------------- COMMAND HANDLERS ----------------

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user:
        register_user_db(user.id, user.first_name, user.username)

    # ✅ check: user already sab channels join kar chuka hai?
    joined = await user_joined_all_channels(context.bot, user.id)

    if joined:
        video = get_random_video_not_sent(user.id)
        if not video:
            await update.message.reply_text("😔 Abhi koi video available nahi hai.")
            return

        try:
            sent_msg = await context.bot.send_video(
                chat_id=user.id,
                video=video["file_id"],
                caption=(
                    "🎉 Verified! Video bhej diya.\n\n"
                    "⏳ Ye video 5 minutes me auto delete ho jayega.\n"
                    "▶️ Next video ke liye /start dabao"
                )
            )
        except:
            sent_msg = await context.bot.send_document(
                chat_id=user.id,
                document=video["file_id"],
                caption=(
                    "🎉 Verified! Video bhej diya.\n\n"
                    "⏳ Ye video 5 minutes me auto delete ho jayega.\n"
                    "▶️ Next video ke liye /start dabao"
                )
            )

        # mark video as sent
        mark_video_sent(user.id, video["id"])

        # ⏳ auto delete after 5 minutes
        asyncio.create_task(
            _delete_message_after(
                context.bot,
                user.id,
                sent_msg.message_id,
                300
            )
        )
        return

    # ❌ agar user ne channels join nahi kiye
    rows = list_channels_db()
    if not rows:
        await update.message.reply_text(
            "Filhaal koi join channel set nahi hai. Owner se contact karo."
        )
        return

    kb = build_join_keyboard()
    text = (
        f"Hi {user.first_name or user.username}!\n\n"
        "Pehle niche diye gaye channels join karo, "
        "phir 'I Joined / Verify' dabao."
    )
    await update.message.reply_text(text, reply_markup=kb)

# ---------- channel add/remove/list ----------
async def cmd_addchannel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return await update.message.reply_text("❌ Ye command sirf owner/admin ke liye hai.")
    if not context.args:
        return await update.message.reply_text("Use: /addchannel <t.me link or @username or chaturl>")
    link = context.args[0].strip()
    add_channel_db(link)
    await update.message.reply_text(f"✅ Channel add kar diya: {link}")

async def cmd_removechannel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return await update.message.reply_text("❌ Ye command sirf owner/admin ke liye hai.")
    if not context.args:
        return await update.message.reply_text("Use: /removechannel <id_or_link>")
    identifier = context.args[0].strip()
    remove_channel_db(identifier)
    await update.message.reply_text(f"Channel deactivate kar diya gaya: {identifier}")

async def cmd_listchannels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return await update.message.reply_text("❌ Ye command sirf owner/admin ke liye hai.")
    rows = list_channels_db()
    if not rows:
        return await update.message.reply_text("Koi active join channel nahi hai.")
    text = "📋 Channels List:\n\n"
    for r in rows:
        text += f"ID: {r['id']} — {r['link']}\n"
    await update.message.reply_text(text)

# ---------- storage (database) channel commands ----------
async def cmd_addstore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return await update.message.reply_text("❌ Sirf owner/admin ke liye.")
    msg = update.message
    # If arg provided (chat id or @username or t.me link)
    if context.args:
        arg = context.args[0].strip()
        chat_identifier = None
        if arg.startswith("https://") or arg.startswith("http://") or arg.startswith("t.me/"):
            tail = arg.rstrip("/").split("/")[-1]
            if tail:
                chat_identifier = tail if tail.startswith("@") else tail
        elif arg.startswith("@") or arg.startswith("-100") or arg.lstrip("-").isdigit():
            chat_identifier = arg
        else:
            return await msg.reply_text("Invalid identifier. Use @username or -100id or t.me/username")
        try:
            chat = await context.bot.get_chat(chat_identifier)
            chat_id = chat.id
            title = chat.title or getattr(chat, "username", str(chat_id))
        except Exception:
            return await msg.reply_text("Bot couldn't resolve that channel. Make sure bot is added to that channel or use chat_id (-100...).")
        add_storage_channel_db(chat_id, title)
        return await msg.reply_text(f"✅ Storage channel add ho gaya: {title} ({chat_id})")
    # Otherwise if reply to forwarded message from channel
    if msg.reply_to_message:
        fwd = msg.reply_to_message
        # sender_chat available when a message is forwarded from a channel
        source = None
        if getattr(fwd, "sender_chat", None):
            source = fwd.sender_chat
        elif getattr(fwd, "forward_from_chat", None):
            source = fwd.forward_from_chat
        if source:
            chat_id = source.id
            title = getattr(source, "title", getattr(source, "username", str(chat_id)))
            add_storage_channel_db(chat_id, title)
            return await msg.reply_text(f"✅ Storage channel add ho gaya: {title} ({chat_id})")
    await msg.reply_text("Use:\n1) /addstore -1001234567890  OR\n2) /addstore @ChannelUsername OR\n3) Forward any message from channel to me, then reply to that forwarded message with /addstore")

async def cmd_removestore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return await update.message.reply_text("❌ Sirf owner/admin ke liye.")
    if not context.args:
        return await update.message.reply_text("Use: /removestore <id_or_chatid>")
    identifier = context.args[0].strip()
    deactivate_storage_channel_db(identifier)
    await update.message.reply_text(f"🗑️ Storage channel deactivate kar diya gaya: {identifier}")

async def cmd_liststore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return await update.message.reply_text("❌ Sirf owner/admin ke liye.")
    rows = list_storage_channels_db()
    if not rows:
        return await update.message.reply_text("📦 Koi storage channel set nahi hai.")
    text = "📦 Storage Channels:\n\n"
    for r in rows:
        status = "✅ Active" if r["active"] == 1 else "❌ Inactive"
        text += f"ID: {r['id']} — `{r['chat_id']}` — {r['title']} — {status}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

# ---------- admin add/remove/list ----------
async def cmd_addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        return await update.message.reply_text("❌ Sirf owner hi ye kar sakta hai.")
    if not context.args:
        return await update.message.reply_text("Use: /addadmin <user_id>")
    try:
        new_id = int(context.args[0])
        add_admin_db(new_id)
        await update.message.reply_text(f"✅ Admin add kar diya: {new_id}")
    except Exception:
        await update.message.reply_text("Invalid user id.")

async def cmd_removeadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        return await update.message.reply_text("❌ Sirf owner hi ye kar sakta hai.")
    if not context.args:
        return await update.message.reply_text("Use: /removeadmin <user_id>")
    try:
        rem_id = int(context.args[0])
        remove_admin_db(rem_id)
        await update.message.reply_text(f"✅ Admin removed: {rem_id}")
    except Exception:
        await update.message.reply_text("Invalid user id.")

async def cmd_listadmins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return await update.message.reply_text("❌ Sirf owner/admin dekh sakte hain.")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM admins")
    rows = cur.fetchall()
    conn.close()
    if not rows:
        return await update.message.reply_text("Koi admin set nahi hai.")
    text = "🛡️ Admins:\n"
    for r in rows:
        text += f"- `{r['user_id']}`\n"
    await update.message.reply_text(text, parse_mode="Markdown")

# ---------- video count & reset ----------
async def cmd_videocount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return await update.message.reply_text("❌ Sirf owner/admin dekh sakte hain.")
    count = get_video_count()
    await update.message.reply_text(f"📦 Database me total videos: {count}")

async def cmd_resetvideos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        return await update.message.reply_text("❌ Sirf owner hi ye kar sakta hai.")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM videos")
    cur.execute("DELETE FROM sent")
    conn.commit()
    conn.close()
    await update.message.reply_text("✅ Saare videos aur sent history delete kar diye gaye.")

async def cmd_exportusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return await update.message.reply_text("❌ Sirf OWNER use kar sakta hai.")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users")
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return await update.message.reply_text("❌ Koi users nahi mile.")

    filename = "users_export.txt"
    with open(filename, "w") as f:
        for r in rows:
            f.write(str(r["user_id"]) + "\n")

    await update.message.reply_document(open(filename, "rb"))

async def cmd_importusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if not is_owner(uid):
        return await update.message.reply_text("❌ Sirf OWNER hi import kar sakta hai.")

    msg = update.message

    if not msg.reply_to_message or not msg.reply_to_message.document:
        return await msg.reply_text(
            "📎 Users file ko reply karke /importusers likho.\n\n"
            "Example:\n"
            "1) users_export.txt bhejo\n"
            "2) Us file ko reply karke /importusers"
        )

    doc = msg.reply_to_message.document
    file = await doc.get_file()

    temp_path = "import_users.txt"
    await file.download_to_drive(temp_path)

    added = 0
    skipped = 0

    conn = get_db()
    cur = conn.cursor()

    with open(temp_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line.isdigit():
                continue
            try:
                cur.execute(
                    "INSERT OR IGNORE INTO users (user_id, first_name, username, seen_at) VALUES (?, '', '', ?)",
                    (int(line), datetime.utcnow().isoformat())
                )
                if cur.rowcount > 0:
                    added += 1
                else:
                    skipped += 1
            except:
                continue

    conn.commit()
    conn.close()
    os.remove(temp_path)

    await msg.reply_text(
        f"✅ Import complete!\n\n"
        f"➕ New users added: {added}\n"
        f"⏭️ Already existing: {skipped}"
    )

async def cmd_usercount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if not is_admin(uid):
        return await update.message.reply_text("❌ Sirf OWNER ya ADMIN hi ye command use kar sakta hai.")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    count = cur.fetchone()[0]
    conn.close()

    await update.message.reply_text(f"👥 Total users: {count}")

# ---------- verify callback ----------
async def verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    user_id = user.id

    # get channels
    chans = list_channels_db()
    if not chans:
        return await query.edit_message_text(
            "Filhaal koi join channel set nahi hai. Owner se contact karo."
        )

    not_joined = []
    for r in chans:
        link = r["link"]
        chat_identifier = None

        # --- convert link to chat id / username ---
        try:
            if link.startswith("http://") or link.startswith("https://") or link.startswith("t.me/"):
                tail = link.rstrip("/").split("/")[-1]
                if tail.startswith("@"):
                    chat_identifier = tail
                else:
                    chat_identifier = "@" + tail
            elif link.startswith("@"):
                chat_identifier = link
            elif link.lstrip("-").isdigit():
                chat_identifier = int(link)
            else:
                chat_identifier = link
        except:
            chat_identifier = link

        # --- check join status ---
        try:
            member = await context.bot.get_chat_member(chat_id=chat_identifier, user_id=user_id)
            if member.status not in ("member", "administrator", "creator"):
                not_joined.append(link)
        except:
            not_joined.append(link)

    # --- if not joined any channel ---
    if not_joined:
        text = "😕 Aisa lagta hai tumne abhi tak ye channels join nahi kiye:\n\n"
        for ch in not_joined:
            text += f"• {ch}\n"
        text += "\nSab join karne ke baad 'I Joined / Verify' dobara dabao."
        return await query.edit_message_text(text)

    # --- get video not sent ---
    video = get_random_video_not_sent(user_id)
    if not video:
        return await query.edit_message_text(
            "😔 Abhi koi video available nahi hai."
        )

    vid_id = video["id"]
    file_id = video["file_id"]

    # --- try to send video/document ---
    try:
        sent_msg = None

        # pehle video try:
        try:
            sent_msg = await context.bot.send_video(
                chat_id=user_id,
                video=file_id,
                caption=(
                    "🎉 Verified! Video bhej diya.\n\n"
                    "⏳ Ye video 5 minutes me auto delete ho jayega.\n"
                    "▶️ Next video ke liye /start dabao"
                )
            )
        except:
            # agar video fail to document bhejo
            sent_msg = await context.bot.send_document(
                chat_id=user_id,
                document=file_id,
                caption=(
                    "🎉 Verified! Video bhej diya.\n\n"
                    "⏳ Ye video 5 minutes me auto delete ho jayega.\n"
                    "▶️ Next video ke liye /start dabao"
                )
            )

        # mark video sent
        mark_video_sent(user_id, vid_id)

        # schedule delete after 5 minutes
        try:
            if sent_msg and getattr(sent_msg, "message_id", None):
                asyncio.create_task(
                    _delete_message_after(
                        context.bot,
                        user_id,
                        sent_msg.message_id,
                        300  # 5 minutes
                    )
                )
        except:
            pass  # delete scheduler fail → no error message to user

        return await query.edit_message_text(
            "🎉 Verified! Video bhej diya.\n\n"
            "⏳ Ye video 5 minutes me auto delete ho jayega.\n"
            "▶️ Next video ke liye /start dabao"
        )

    except Exception:
        return await query.edit_message_text(
            "⚠️ Video bhejte waqt error aaya. Thodi der baad try karein."
        )

# noop callback
async def noop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer("Open the channel manually in Telegram and join.", show_alert=False)

# ---------------- message handler for storage channels (auto-save) ----------------
async def channel_post_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not msg.chat:
        return
    chat_id = msg.chat.id
    if not is_storage_channel(chat_id):
        return
    file_id = None
    caption = None
    # video
    if getattr(msg, "video", None):
        file_id = msg.video.file_id
        caption = msg.caption or ""
    elif getattr(msg, "animation", None):
        file_id = msg.animation.file_id
        caption = msg.caption or ""
    elif getattr(msg, "document", None):
        # only save if document is a video-type or we accept any document
        file_id = msg.document.file_id
        caption = msg.caption or ""
    if file_id:
        add_video_row(file_id, caption, added_by=None)
        logger.info("[DB] saved file_id %s from chat %s", file_id, chat_id)

import time

async def broadcast_task(bot, admin_id, user_ids, text=None, from_chat_id=None, message_id=None):
    total = len(user_ids)
    sent = 0
    failed = 0
    start_time = time.time()

    for uid in user_ids:
        try:
            if text:
                await bot.send_message(chat_id=uid, text=text)
            else:
                await bot.copy_message(
                    chat_id=uid,
                    from_chat_id=from_chat_id,
                    message_id=message_id
                )
            sent += 1
            await asyncio.sleep(0.1)  # async delay (safe)
        except Exception:
            failed += 1
            continue

    elapsed = int(time.time() - start_time)
    minutes = elapsed // 60
    seconds = elapsed % 60

    summary = (
        "✅ Broadcast Complete!\n\n"
        f"👥 Total users: {total}\n"
        f"📤 Sent: {sent}\n"
        f"❌ Failed: {failed}\n"
        f"⏳ Time taken: {minutes} min {seconds} sec"
    )

    await bot.send_message(chat_id=admin_id, text=summary)

# ---------- simple utility commands ----------
async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Pong — bot chal raha hai.")

# ---------------- broadcast (async /all) ----------------
async def cmd_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return await update.message.reply_text("❌ Sirf owner/admin ye command use kar sakta hai.")

    msg = update.message
    user_ids = get_all_user_ids()

    if not user_ids:
        return await msg.reply_text("❌ Koi users database me nahi mile.")

    # TEXT broadcast
    if context.args:
        text = " ".join(context.args)
        asyncio.create_task(
            broadcast_task(
                context.bot,
                uid,
                user_ids,
                text=text
            )
        )
        return await msg.reply_text(
            f"📢 Broadcast started!\n"
            f"👥 Total users: {len(user_ids)}\n"
            f"⏳ Background me dheere-dheere send ho raha hai."
        )

    # REPLY broadcast (copy message)
    if msg.reply_to_message:
        asyncio.create_task(
            broadcast_task(
                context.bot,
                uid,
                user_ids,
                from_chat_id=msg.chat.id,
                message_id=msg.reply_to_message.message_id
            )
        )
        return await msg.reply_text(
            f"📢 Broadcast started!\n"
            f"👥 Total users: {len(user_ids)}\n"
            f"⏳ Background me dheere-dheere send ho raha hai."
        )

    return await msg.reply_text(
        "Use:\n"
        "/all <text>\n"
        "ya kisi message ka reply karke /all bhejo"
    )

# ---------- admin owner transfer (owner-only) ----------
async def cmd_transfer_owner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        return await update.message.reply_text("❌ Sirf current owner ye kar sakta hai.")
    if not context.args:
        return await update.message.reply_text("Use: /transfer_owner <new_owner_user_id>")
    try:
        new_owner = int(context.args[0])
        conn = get_db()
        cur = conn.cursor()
        cur.execute("DELETE FROM owner")
        cur.execute("INSERT INTO owner (user_id) VALUES (?)", (new_owner,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ Owner transfered to {new_owner}")
    except Exception:
        await update.message.reply_text("Invalid user id.")

# ---------------- BUILD APP & HANDLERS ----------------
# create application (top-level so handlers can use it)
app = ApplicationBuilder().token(BOT_TOKEN).build()

# core handlers
app.add_handler(CommandHandler("start", start_handler))
app.add_handler(CommandHandler("ping", cmd_ping))

app.add_handler(CommandHandler("addchannel", cmd_addchannel))
app.add_handler(CommandHandler("removechannel", cmd_removechannel))
app.add_handler(CommandHandler("listchannels", cmd_listchannels))

app.add_handler(CommandHandler("addstore", cmd_addstore))
app.add_handler(CommandHandler("removestore", cmd_removestore))
app.add_handler(CommandHandler("liststore", cmd_liststore))

app.add_handler(CommandHandler("addadmin", cmd_addadmin))
app.add_handler(CommandHandler("removeadmin", cmd_removeadmin))
app.add_handler(CommandHandler("listadmins", cmd_listadmins))

app.add_handler(CommandHandler("videocount", cmd_videocount))
app.add_handler(CommandHandler("resetvideos", cmd_resetvideos))

app.add_handler(CommandHandler("all", cmd_all))
app.add_handler(CommandHandler("transfer_owner", cmd_transfer_owner))

app.add_handler(CommandHandler("exportusers", cmd_exportusers))
app.add_handler(CommandHandler("importusers", cmd_importusers))

app.add_handler(CommandHandler("usercount", cmd_usercount))

# broadcast helper: owner/admin only - already above
# callback handlers
app.add_handler(CallbackQueryHandler(verify_callback, pattern="^verify_join$"))
app.add_handler(CallbackQueryHandler(noop_callback, pattern="^noop$"))

# single channel-only handler — compatible across PTB versions
app.add_handler(
    MessageHandler(
        filters.ChatType.CHANNEL & (~filters.COMMAND),
        channel_post_handler,
    )
)


# ---------------- RUN ----------------
def main():
    logger.info("Bot starting...")
    print("Bot is running...")
    # run polling in blocking mode
    app.run_polling()

if __name__ == "__main__":
    main()
