import os, sqlite3, asyncio
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

TOKEN = os.getenv("BOT_TOKEN", "")
ADMINS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
POINTS = int(os.getenv("POINTS_PER_REFERRAL", "10"))
DB = sqlite3.connect(os.getenv("DB_PATH", "referrals.db"), check_same_thread=False)
DB.row_factory = sqlite3.Row

if not TOKEN:
    raise RuntimeError("Set BOT_TOKEN first")

bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

def init():
    DB.executescript("""
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY, username TEXT, name TEXT, points INTEGER DEFAULT 0,
      invited_by INTEGER, created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS referrals(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      inviter INTEGER NOT NULL, invited INTEGER UNIQUE NOT NULL, created_at TEXT
    );
    """)
    DB.commit()

def user_exists(uid):
    return DB.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()

def save_user(u):
    if user_exists(u.id):
        DB.execute("UPDATE users SET username=?, name=? WHERE id=?",
                   (u.username or "", u.first_name or "", u.id))
    else:
        DB.execute("INSERT INTO users(id,username,name,created_at) VALUES(?,?,?,?)",
                   (u.id, u.username or "", u.first_name or "", datetime.utcnow().isoformat()))
    DB.commit()

def add_referral(inviter, invited):
    if inviter == invited or not user_exists(inviter):
        return False
    row = DB.execute("SELECT invited_by FROM users WHERE id=?", (invited,)).fetchone()
    if not row or row["invited_by"] is not None:
        return False
    try:
        DB.execute("INSERT INTO referrals(inviter,invited,created_at) VALUES(?,?,?)",
                   (inviter, invited, datetime.utcnow().isoformat()))
        DB.execute("UPDATE users SET invited_by=?, points=points+? WHERE id=?",
                   (inviter, POINTS, invited))
        DB.commit()
        return True
    except sqlite3.IntegrityError:
        DB.rollback()
        return False

def ref_count(uid):
    return DB.execute("SELECT COUNT(*) c FROM referrals WHERE inviter=?", (uid,)).fetchone()["c"]

@dp.message(CommandStart())
async def start(m: Message):
    save_user(m.from_user)
    args = (m.text or "").split(maxsplit=1)
    if len(args) == 2 and args[1].isdigit():
        if add_referral(int(args[1]), m.from_user.id):
            try: await bot.send_message(int(args[1]), f"🎉 إحالة جديدة! +{POINTS} نقطة")
            except: pass
    await home(m)

async def home(m):
    u = user_exists(m.from_user.id)
    link = f"https://t.me/{(await bot.get_me()).username}?start={m.from_user.id}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
      [InlineKeyboardButton(text="🔗 رابط الإحالة", callback_data="link"),
       InlineKeyboardButton(text="📊 إحصائياتي", callback_data="stats")]
    ])
    await m.answer(f"👋 أهلاً <b>{m.from_user.first_name}</b>!\n\n⭐ نقاطك: <b>{u['points']}</b>\n👥 إحالاتك: <b>{ref_count(m.from_user.id)}</b>",
                   reply_markup=kb)

@dp.callback_query(F.data=="link")
async def link(c):
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start={c.from_user.id}"
    await c.message.answer(f"🔗 رابطك:\n<code>{link}</code>\n\n+{POINTS} نقاط لكل إحالة مؤهلة.")
    await c.answer()

@dp.callback_query(F.data=="stats")
async def stats(c):
    u=user_exists(c.from_user.id)
    await c.message.answer(f"📊 الإحصائيات\n\n👥 الإحالات: <b>{ref_count(c.from_user.id)}</b>\n⭐ النقاط: <b>{u['points']}</b>")
    await c.answer()

@dp.message(Command("stats"))
async def admin_stats(m):
    if m.from_user.id not in ADMINS: return
    users=DB.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    refs=DB.execute("SELECT COUNT(*) c FROM referrals").fetchone()["c"]
    pts=DB.execute("SELECT COALESCE(SUM(points),0) s FROM users").fetchone()["s"]
    await m.answer(f"🛠 Admin\nUsers: {users}\nReferrals: {refs}\nPoints: {pts}")

async def main():
    init()
    print("Referral bot running")
    await dp.start_polling(bot)

if __name__=="__main__":
    asyncio.run(main())
