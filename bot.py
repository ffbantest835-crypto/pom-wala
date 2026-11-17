# -*- coding: utf-8 -*-
import sqlite3
import logging
import asyncio
import os
import threading
import qrcode
from io import BytesIO
from fastapi import FastAPI
import uvicorn
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, InputFile
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, CallbackQueryHandler
)

# ================== CONFIG ==================
BOT_TOKEN = os.getenv("BOT_TOKEN", "9083925993:AAE9ikMA5FfkfUz7bsjNWWOOW65YE0tH8Q0")

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ================== STYLISH FONTS (FIXED) ==================
FONT_MAP = {
    'a': '𝘢', 'b': '𝘣', 'c': '𝘤', 'd': '𝘥', 'e': '𝘦', 'f': '𝘧', 'g': '𝘨', 'h': '𝘩', 'i': '𝘪', 'j': '𝘫',
    'k': '𝘬', 'l': '𝘭', 'm': '𝘮', 'n': '𝘯', 'o': '𝘰', 'p': '𝘱', 'q': '𝘲', 'r': '𝘳', 's': '𝘴', 't': '𝘵',
    'u': '𝘶', 'v': '𝘷', 'w': '𝘸', 'x': '𝘹', 'y': '𝘺', 'z': '𝘻',
    'A': '𝘈', 'B': '𝘉', 'C': '𝘊', 'D': '𝘋', 'E': '𝘌', 'F': '𝘍', 'G': '𝘎', 'H': '𝘏', 'I': '𝘐', 'J': '𝘑',
    'K': '𝘒', 'L': '𝘓', 'M': '𝘔', 'N': '𝘕', 'O': '𝘖', 'P': '𝘗', 'Q': '𝘘', 'R': '𝘙', 'S': '𝘚', 'T': '𝘛',
    'U': '𝘜', 'V': '𝘝', 'W': '𝘞', 'X': '𝘟', 'Y': '𝘠', 'Z': '𝘡'
}
def f_txt(text): 
    if not text: return ""
    return "".join(FONT_MAP.get(c, c) for c in text)

def p_style(text): return f"<code>{text}</code>,"

# ================== DATABASE ==================
DB_PATH = "paid_promo_bot.db"

def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT, joined INTEGER DEFAULT 0, is_banned INTEGER DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS channels (
        id INTEGER PRIMARY KEY AUTOINCREMENT, link TEXT, channel_id TEXT, name TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS config (
        key TEXT PRIMARY KEY, value TEXT
    )""")
    c.execute("CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)")
    c.execute("""CREATE TABLE IF NOT EXISTS requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT, plan TEXT, screenshot TEXT, type TEXT DEFAULT 'Payment'
    )""")
    conn.commit()
    conn.close()

init_db()

def db_exec(query, params=()):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    c = conn.cursor()
    try:
        c.execute(query, params)
        conn.commit()
        res = c.fetchall()
    finally:
        conn.close()
    return res

def get_all_admins():
    res = db_exec("SELECT user_id FROM admins")
    return [row[0] for row in res] if res else []

def get_config(key, default=None):
    res = db_exec("SELECT value FROM config WHERE key=?", (key,))
    return res[0][0] if res else default

def set_config(key, value):
    db_exec("INSERT OR REPLACE INTO config (key, value) VALUES (?,?)", (key, value))

# ================== FASTAPI ==================
web_app = FastAPI()

@web_app.get("/")
def read_root(): return {"status": "Alive"}

def run_web():
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(web_app, host="0.0.0.0", port=port)

# ================== KEYBOARDS & STATE ==================
user_states = {}

def get_join_keyboard():
    channels = db_exec("SELECT name, link FROM channels")
    kb = []
    for ch in channels:
        kb.append([InlineKeyboardButton(f"Join {ch[0]}", url=ch[1], style="primary")])
    kb.append([InlineKeyboardButton(f_txt("VERIFY MEMBERSHIP"), callback_data="verify_membership", style="success")])
    return InlineKeyboardMarkup(kb)

def get_plan_keyboard():
    kb = [
        [InlineKeyboardButton(f_txt("15 Rs - 4 MONTH ENTRY"), callback_data="plan_15", style="primary")],
        [InlineKeyboardButton(f_txt("16 Rs - 9 MONTH ENTRY"), callback_data="plan_16", style="primary")],
        [InlineKeyboardButton(f_txt("26 Rs - PERMANENT ENTRY"), callback_data="plan_26", style="primary")]
    ]
    return InlineKeyboardMarkup(kb)

def get_qr_keyboard():
    kb = [
        [InlineKeyboardButton(f_txt("I HAVE PAID"), callback_data="paid", style="primary"), InlineKeyboardButton(f_txt("CANCEL"), callback_data="cancel_pay", style="danger")]
    ]
    return InlineKeyboardMarkup(kb)

def get_approve_keyboard(user_id, req_id):
    kb = [
        [InlineKeyboardButton(f_txt("APPROVE"), callback_data=f"approve_{user_id}_{req_id}", style="success"), InlineKeyboardButton(f_txt("DISAPPROVE"), callback_data=f"disapprove_{user_id}_{req_id}", style="danger")]
    ]
    return InlineKeyboardMarkup(kb)

def get_unban_keyboard():
    kb = [
        [InlineKeyboardButton(f_txt("PAY 19RS TO UNBAN"), callback_data="unban_pay", style="primary")]
    ]
    return InlineKeyboardMarkup(kb)

# ================== BOT HANDLERS ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "No Username"
    
    res = db_exec("SELECT is_banned FROM users WHERE user_id=?", (user_id,))
    if res and res[0][0] == 1:
        return await update.message.reply_text(
            f"🚫 <b>{f_txt('YOU ARE BANNED')}</b>\n\n{f_txt('Contact admin or pay 19rs to unban')}",
            reply_markup=get_unban_keyboard(),
            parse_mode="HTML"
        )
    
    total_admins = db_exec("SELECT COUNT(*) FROM admins")[0][0]
    if total_admins == 0:
        db_exec("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))

    if not res:
        db_exec("INSERT INTO users (user_id, username) VALUES (?,?)", (user_id, username))
        for admin in get_all_admins():
            try: await context.bot.send_message(admin, f"🆕 <b>{f_txt('NEW USER')}</b>\nID: <code>{user_id}</code>\n@{username}", parse_mode="HTML")
            except: pass

    welcome_text = f"👋 <b>{f_txt('WELCOME TO PAID POMPOM BOT')}</b>\n\n{f_txt('Please join the group to continue')}:"
    
    welcome_photo = get_config("welcome_photo")
    welcome_video = get_config("welcome_video")

    if welcome_video:
        await update.message.reply_video(video=welcome_video, caption=welcome_text, reply_markup=get_join_keyboard(), parse_mode="HTML")
    elif welcome_photo:
        await update.message.reply_photo(photo=welcome_photo, caption=welcome_text, reply_markup=get_join_keyboard(), parse_mode="HTML")
    else:
        await update.message.reply_text(welcome_text, reply_markup=get_join_keyboard(), parse_mode="HTML")

async def verify_membership(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    db_exec("UPDATE users SET joined=1 WHERE user_id=?", (user_id,))
    
    # FIXED STYLISH PRICE LIST
    plan_text = (
        f"✨⭐ <b>{f_txt('WELCOME TO POOM GROUP')}</b> ⭐✨\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>{f_txt('PRICE LIST')} 👇🏻👇🏻</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"⭐ {f_txt('15 Rs - 4 MONTH ENTRY')}\n"
        f"⭐ {f_txt('16 Rs - 9 MONTH ENTRY')}\n"
        f"💦 {f_txt('26 Rs - PERMANENT ENTRY')} 💦\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"✅ {f_txt('INSTANT ENTRY')}\n"
        f"✅ {f_txt('FULL TRUSTED')}\n"
        f"🔥 {f_txt('JOIN NOW')} 🔥"
    )
    
    plan_photo = get_config("plan_photo")
    if plan_photo:
        await query.message.reply_photo(photo=plan_photo, caption=plan_text, reply_markup=get_plan_keyboard(), parse_mode="HTML")
    else:
        await query.message.reply_text(plan_text, reply_markup=get_plan_keyboard(), parse_mode="HTML")

async def plan_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    plan = query.data.split("_")[1]
    context.user_data['plan'] = plan
    
    upi_id = get_config("upi_id")
    if not upi_id:
        return await query.message.reply_text(f"❌ {f_txt('Admin has not set UPI ID yet')}")

    amount = "15" if plan == "15" else "16" if plan == "16" else "26"
    upi_url = f"upi://pay?pa={upi_id}&pn=Payment&am={amount}&cu=INR"
    
    qr = qrcode.QRCode(box_size=10, border=4)
    qr.add_data(upi_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    bio = BytesIO()
    bio.name = 'qr.png'
    img.save(bio, 'PNG')
    bio.seek(0)
    
    qr_caption = f"📸 <b>{f_txt('SCAN TO PAY')}</b>\n\n{f_txt('Amount')}: <b>{amount} Rs</b>\nUPI: <code>{upi_id}</code>"
    await query.message.reply_photo(photo=InputFile(bio, 'qr.png'), caption=qr_caption, reply_markup=get_qr_keyboard(), parse_mode="HTML")

async def qr_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel_pay":
        await query.message.delete()
        return
        
    if query.data == "paid":
        context.user_data['waiting_screenshot'] = True
        await query.message.reply_text(f"📸 {f_txt('Please send your Payment Screenshot now')}")
        
    if query.data == "unban_pay":
        user_id = query.from_user.id
        context.user_data['unban_waiting'] = True
        upi_id = get_config("upi_id")
        if not upi_id:
            return await query.message.reply_text(f"❌ {f_txt('Admin has not set UPI ID yet')}")
            
        upi_url = f"upi://pay?pa={upi_id}&pn=Payment&am=19&cu=INR"
        qr = qrcode.QRCode(box_size=10, border=4)
        qr.add_data(upi_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        bio = BytesIO()
        bio.name = 'qr.png'
        img.save(bio, 'PNG')
        bio.seek(0)
        
        qr_caption = f"📸 <b>{f_txt('SCAN TO PAY FOR UNBAN')}</b>\n\n{f_txt('Amount')}: <b>19 Rs</b>\nUPI: <code>{upi_id}</code>"
        await query.message.reply_photo(photo=InputFile(bio, 'qr.png'), caption=qr_caption, reply_markup=get_qr_keyboard(), parse_mode="HTML")

async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('waiting_screenshot'):
        user_id = update.effective_user.id
        username = update.effective_user.username or "No Username"
        photo = update.message.photo[-1].file_id
        plan = context.user_data.get('plan', 'Unknown')
        
        db_exec("INSERT INTO requests (user_id, username, plan, screenshot, type) VALUES (?,?,?,?,'Payment')", (user_id, username, plan, photo))
        req_id = db_exec("SELECT last_insert_rowid()")[0][0]
        
        context.user_data['waiting_screenshot'] = False
        await update.message.reply_text(f"⏳ {f_txt('Screenshot sent for verification')}")
        
        admin_text = f"🔔 <b>{f_txt('NEW PAYMENT PROOF')}</b>\n\n{f_txt('User')}: @{username} (<code>{user_id}</code>)\n{f_txt('Plan')}: {plan} Rs"
        for admin in get_all_admins():
            try: await context.bot.send_photo(admin, photo=photo, caption=admin_text, reply_markup=get_approve_keyboard(user_id, req_id), parse_mode="HTML")
            except: pass
            
    elif context.user_data.get('unban_waiting'):
        user_id = update.effective_user.id
        username = update.effective_user.username or "No Username"
        photo = update.message.photo[-1].file_id
        
        db_exec("INSERT INTO requests (user_id, username, plan, screenshot, type) VALUES (?,?,?,?,'Unban')", (user_id, username, "19", photo))
        context.user_data['unban_waiting'] = False
        await update.message.reply_text(f"⏳ {f_txt('Unban request sent')}")
        
        admin_text = f"🔔 <b>{f_txt('UNBAN PAYMENT PROOF')}</b>\n\n{f_txt('User')}: @{username} (<code>{user_id}</code>)\n{f_txt('Plan')}: 19 Rs Unban"
        for admin in get_all_admins():
            try: await context.bot.send_photo(admin, photo=photo, caption=admin_text, reply_markup=get_approve_keyboard(user_id, 0), parse_mode="HTML")
            except: pass

async def approve_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data.split("_")
    action, user_id, req_id = data[0], int(data[1]), int(data[2])
    
    if action == "approve":
        await query.edit_message_caption(caption=f"{query.message.caption}\n\n✅ <b>{f_txt('APPROVED')}</b>", parse_mode="HTML")
        if req_id != 0:
            db_exec("UPDATE requests SET status='Approved' WHERE id=?", (req_id,))
        await context.bot.send_message(user_id, f"🎉 <b>{f_txt('Payment Approved!')}</b>")
    elif action == "disapprove":
        await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ <b>{f_txt('REJECTED')}</b>", parse_mode="HTML")
        if req_id != 0:
            db_exec("UPDATE requests SET status='Rejected' WHERE id=?", (req_id,))
        await context.bot.send_message(user_id, f"❌ {f_txt('Payment was rejected')}")

# ================== OWNER PANEL ==================
async def owner_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in get_all_admins(): return
    
    kb = [
        [InlineKeyboardButton(f_txt("Add Group"), callback_data="admin_add_ch", style="primary"), InlineKeyboardButton(f_txt("Remove Group"), callback_data="admin_rem_ch", style="danger")],
        [InlineKeyboardButton(f_txt("Set UPI ID"), callback_data="admin_set_upi", style="primary"), InlineKeyboardButton(f_txt("Set Welcome Pic"), callback_data="admin_set_welcome", style="primary")],
        [InlineKeyboardButton(f_txt("Set Welcome Vid"), callback_data="admin_set_wvid", style="primary"), InlineKeyboardButton(f_txt("Set Plan Pic"), callback_data="admin_set_planpic", style="primary")],
        [InlineKeyboardButton(f_txt("Total Users"), callback_data="admin_members", style="success"), InlineKeyboardButton(f_txt("Total Payments"), callback_data="admin_payments", style="success")],
        [InlineKeyboardButton(f_txt("Ban User"), callback_data="admin_ban", style="danger"), InlineKeyboardButton(f_txt("Unban User"), callback_data="admin_unban", style="success")],
        [InlineKeyboardButton(f_txt("Add Admin"), callback_data="admin_add", style="primary")]
    ]
    await update.message.reply_text(f"<b>👑 {f_txt('OWNER PANEL')}</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

async def admin_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    uid = query.from_user.id
    
    if uid not in get_all_admins(): return await query.answer("Unauthorized", show_alert=True)
    
    if data == "admin_add_ch":
        await query.edit_message_text(f"🔗 {f_txt('Send Group Link, ID, and Name separated by comma')}\n<code>https://t.me/test, -1001234567890, My Group</code>", parse_mode="HTML")
        user_states[uid] = 'add_channel'
    elif data == "admin_set_upi":
        await query.edit_message_text(f"💳 {f_txt('Send your UPI ID')}:")
        user_states[uid] = 'set_upi'
    elif data == "admin_set_welcome":
        await query.edit_message_text(f"🖼 {f_txt('Send the Welcome Photo')}:")
        user_states[uid] = 'set_welcome'
    elif data == "admin_set_wvid":
        await query.edit_message_text(f"🎬 {f_txt('Send the Welcome Video')}:")
        user_states[uid] = 'set_wvid'
    elif data == "admin_set_planpic":
        await query.edit_message_text(f"🖼 {f_txt('Send the 2nd Photo (For Price List)')}:")
        user_states[uid] = 'set_planpic'
    elif data == "admin_rem_ch":
        channels = db_exec("SELECT id, name FROM channels")
        if not channels: return await query.edit_message_text(f"❌ {f_txt('No channels added')}")
        kb = [[InlineKeyboardButton(f"❌ {f_txt('Delete')} {name}", callback_data=f"delch_{ch_id}", style="danger")] for ch_id, name in channels]
        await query.edit_message_text(f"{f_txt('Select channel to delete')}:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("delch_"):
        db_exec("DELETE FROM channels WHERE id=?", (int(data.split("_")[1]),))
        await query.edit_message_text(f"✅ {f_txt('Channel removed')}")
    elif data == "admin_members":
        users = db_exec("SELECT user_id, username FROM users")
        text = f"👥 <b>{f_txt('Total Users')}: {len(users)}</b>\n\n"
        for u in users[:20]: text += f"🆔 <code>{u[0]}</code> | @{u[1]}\n"
        await query.edit_message_text(text, parse_mode="HTML")
    elif data == "admin_payments":
        payments = db_exec("SELECT user_id, username, plan, screenshot, type FROM requests ORDER BY id DESC LIMIT 20")
        if not payments: return await query.edit_message_text(f"❌ {f_txt('No payments found')}")
        await query.edit_message_text(f"📸 {f_txt('Sending all payment proofs...')}")
        for p in payments:
            txt = f"👤 @{p[1]} (<code>{p[0]}</code>)\n{f_txt('Plan')}: {p[2]} Rs | {f_txt('Type')}: {p[4]}"
            try: await context.bot.send_photo(uid, photo=p[3], caption=txt, parse_mode="HTML")
            except: pass
    elif data == "admin_ban":
        await query.edit_message_text(f"🚫 {f_txt('Send User ID to BAN')}:")
        user_states[uid] = 'ban_user'
    elif data == "admin_unban":
        await query.edit_message_text(f"✅ {f_txt('Send User ID to UNBAN')}:")
        user_states[uid] = 'unban_user'
    elif data == "admin_add":
        await query.edit_message_text(f"👑 {f_txt('Send User ID to make Admin')}:")
        user_states[uid] = 'add_admin'

async def admin_state_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text if update.message.text else ""
    state = user_states.get(uid)
    
    if uid not in get_all_admins(): return
    
    if state == 'add_channel':
        try:
            parts = [p.strip() for p in text.split(",")]
            db_exec("INSERT INTO channels (link, channel_id, name) VALUES (?,?,?)", (parts[0], parts[1], parts[2]))
            await update.message.reply_text(f"✅ {p_style('Group Added')}", parse_mode="HTML")
        except: await update.message.reply_text(f"❌ {f_txt('Invalid format')}")
        user_states[uid] = None
        
    elif state == 'set_upi':
        set_config("upi_id", text)
        await update.message.reply_text(f"✅ {p_style('UPI ID Set')}", parse_mode="HTML")
        user_states[uid] = None
        
    elif state == 'ban_user':
        if text.isdigit():
            db_exec("UPDATE users SET is_banned=1 WHERE user_id=?", (int(text),))
            await update.message.reply_text(f"✅ {p_style('User Banned')}", parse_mode="HTML")
        user_states[uid] = None
        
    elif state == 'unban_user':
        if text.isdigit():
            db_exec("UPDATE users SET is_banned=0 WHERE user_id=?", (int(text),))
            await update.message.reply_text(f"✅ {p_style('User Unbanned')}", parse_mode="HTML")
        user_states[uid] = None
        
    elif state == 'add_admin':
        if text.isdigit():
            db_exec("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (int(text),))
            await update.message.reply_text(f"✅ {p_style('Admin Added')}", parse_mode="HTML")
        user_states[uid] = None

async def handle_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state = user_states.get(uid)
    
    if state == 'set_welcome' and update.message.photo:
        set_config("welcome_photo", update.message.photo[-1].file_id)
        await update.message.reply_text(f"✅ {f_txt('Welcome Photo Saved')}")
        user_states[uid] = None
    elif state == 'set_planpic' and update.message.photo:
        set_config("plan_photo", update.message.photo[-1].file_id)
        await update.message.reply_text(f"✅ {f_txt('Plan Photo Saved')}")
        user_states[uid] = None
    else:
        await handle_screenshot(update, context)

async def handle_videos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if user_states.get(uid) == 'set_wvid' and update.message.video:
        set_config("welcome_video", update.message.video.file_id)
        await update.message.reply_text(f"✅ {f_txt('Welcome Video Saved')}")
        user_states[uid] = None

# ================== MAIN ==================
def main():
    threading.Thread(target=run_web, daemon=True).start()
    app_bot = Application.builder().token(BOT_TOKEN).build()

    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("owner", owner_panel))
    
    app_bot.add_handler(CallbackQueryHandler(verify_membership, pattern="^verify_membership$"))
    app_bot.add_handler(CallbackQueryHandler(plan_selected, pattern="^plan_"))
    app_bot.add_handler(CallbackQueryHandler(qr_callback, pattern="^(paid|cancel_pay|unban_pay)$"))
    app_bot.add_handler(CallbackQueryHandler(approve_callback, pattern="^(approve|disapprove)_"))
    app_bot.add_handler(CallbackQueryHandler(admin_callbacks, pattern="^(admin_|delch_)"))
    
    app_bot.add_handler(MessageHandler(filters.PHOTO, handle_photos))
    app_bot.add_handler(MessageHandler(filters.VIDEO, handle_videos))
    
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_state_router))

    logger.info("Paid Promo Bot started successfully.")
    app_bot.run_polling(allowed_updates=Update.ALL_TYPES, close_loop=False)

if __name__ == "__main__":
    main()
