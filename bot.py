"""Aniwu kolleksiya boti (aiogram 3.13+, SQLite, Mini App).

Muhit o'zgaruvchilari: BOT_TOKEN, OWNER_ID, ADMIN_IDS (ixtiyoriy), DB_PATH (masalan /data/aniwu.db),
WEBAPP_URL (ixtiyoriy: Railway'da domen yaratilsa RAILWAY_PUBLIC_DOMAIN dan o'zi olinadi).
"""
import asyncio
import hashlib
import hmac
import html
import json
import logging
import os
import random
import sqlite3
import time
from datetime import date
from io import BytesIO
from urllib.parse import parse_qsl, quote

from aiohttp import web
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (BotCommand, BufferedInputFile, CallbackQuery, ChatMemberUpdated, KeyboardButton,
                           KeyboardButtonRequestUsers, MenuButtonWebApp, Message, ReplyKeyboardMarkup,
                           WebAppInfo)
from aiogram.types import InlineKeyboardButton as Btn
from aiogram.types import InlineKeyboardMarkup as Kb

TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
ENV_ADMINS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()}
PORT = int(os.getenv("PORT", "8080"))
_dom = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
WEBAPP_URL = (os.getenv("WEBAPP_URL", "").strip() or (_dom and "https://" + _dom)).rstrip("/")
if WEBAPP_URL and not WEBAPP_URL.startswith("http"):
    WEBAPP_URL = "https://" + WEBAPP_URL

# daraja: (belgi, tushish vazni). Ramka ranglari ham shu tartibda.
RARITY = {"common": ("🔵", 60), "epic": ("🟣", 25), "legendary": ("🟠", 10),
          "mifik": ("🔴", 4), "ultimate": ("🟡", 1)}
# xabar effektlari (faqat shaxsiy chatda): 👍 ❤️ 🔥 🎉
EFFECT = {"epic": "5107584321108051014", "legendary": "5044134455711629726",
          "mifik": "5104841245755180586", "ultimate": "5046509860389126442"}
STK_KEYS = [("start", "👋 Salom"), ("sandiq", "🎁 Sandiq ochilganda"), ("common", "🔵 Common tushganda"),
            ("epic", "🟣 Epic tushganda"), ("legendary", "🟠 Legendary tushganda"),
            ("mifik", "🔴 Mifik tushganda"), ("ultimate", "🟡 Ultimate tushganda"),
            ("toplam", "🏆 To'plam yig'ilganda"), ("yutuq", "🎮 O'yin yutganda"), ("sovga", "💝 Sovga"),
            ("almashuv", "🔄 Almashuv"), ("sotib", "🛒 Xarid"), ("up_ok", "⬆️ Upgrade yutuq"),
            ("up_fail", "💥 Upgrade yutqazish")]
FREE_BOXES_PER_DAY = 3
GIFTS_PER_DAY = 3
INVITES_PER_BOX = 10
MONEY_PER_DIAMOND = 1000  # 1 💎 = 1000 💰 (ikki tomonga)
BOX_PRICE = 500  # tekin sandiqlar tugagach, har bir sandiq narxi
PAGE = 8

# ---------- daraja ramkalari (rasm /add qilinganda avtomatik qo'shiladi) ----------
# daraja: (rang 1, rang 2, ramka qalinligi)
FRAME = {
    "common": ((140, 195, 255), (37, 99, 235), 10),      # 🔵
    "epic": ((222, 178, 255), (124, 58, 237), 16),       # 🟣
    "legendary": ((255, 196, 110), (234, 88, 12), 22),   # 🟠
    "mifik": ((255, 140, 140), (200, 25, 40), 26),       # 🔴
    "ultimate": ((255, 240, 150), (210, 150, 10), 34),   # 🟡
}


def _font(size):
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


def _star(d, cx, cy, r, fill):
    k = r * 0.3
    d.polygon([(cx, cy - r), (cx + k, cy - k), (cx + r, cy), (cx + k, cy + k), (cx, cy + r),
               (cx - k, cy + k), (cx - r, cy), (cx - k, cy - k)], fill=fill)


def _diamond(d, cx, cy, r, fill):
    d.polygon([(cx, cy - r), (cx + r * 0.7, cy), (cx, cy + r), (cx - r * 0.7, cy)], fill=fill)


def frame_image(raw, rarity, W=720, H=960):
    """Rasmni 3:4 ga keltirib, daraja ramkasini qo'shadi. JPEG baytlarini qaytaradi."""
    c1, c2, th = FRAME[rarity]
    im = Image.open(BytesIO(raw)).convert("RGB")
    s = max(W / im.width, H / im.height)
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    left, top = (im.width - W) // 2, (im.height - H) // 2
    im = im.crop((left, top, left + W, top + H))
    grad = Image.new("RGB", (W, H))
    gd = ImageDraw.Draw(grad)
    for y in range(H):
        k = y / H
        gd.line([(0, y), (W, y)], fill=tuple(int(c1[i] + (c2[i] - c1[i]) * k) for i in range(3)))
    ring = Image.new("L", (W, H), 0)
    rd = ImageDraw.Draw(ring)
    rd.rectangle((0, 0, W, H), fill=255)
    rd.rounded_rectangle((th, th, W - th - 1, H - th - 1), 26, fill=0)
    if rarity != "common":  # ichki yorug'lik
        glow = ring.filter(ImageFilter.GaussianBlur(th * 1.2)).point(lambda v: int(v * 0.8))
        im.paste(Image.new("RGB", (W, H), c1), (0, 0), glow)
    im.paste(grad, (0, 0), ring)
    d = ImageDraw.Draw(im)
    if rarity != "common":
        o = th + 8
        d.rounded_rectangle((o, o, W - o - 1, H - o - 1), 20, outline=c1, width=3)
    cs = lambda r: [(r, r), (W - r, r), (r, H - r), (W - r, H - r)]  # burchak bezaklari to'liq ko'rinadi
    mids = [(W // 2, th), (W // 2, H - th), (th, H // 2), (W - th, H // 2)]
    if rarity == "epic":
        for x, y in cs(24):
            _diamond(d, x, y, 24, c1)
    elif rarity == "legendary":
        for x, y in cs(34):
            _diamond(d, x, y, 34, c1)
            _diamond(d, x, y, 15, c2)
        for x, y in mids[:2]:
            _diamond(d, x, y, 22, c1)
    elif rarity == "mifik":
        d.rectangle((5, 5, W - 6, H - 6), outline=c1, width=2)
        for x, y in cs(40):
            _star(d, x, y, 40, c1)
        for x, y in mids:
            _diamond(d, x, y, 20, c1)
    elif rarity == "ultimate":
        d.rectangle((5, 5, W - 6, H - 6), outline=(255, 255, 255), width=3)
        for x, y in cs(58):
            _star(d, x, y, 58, c1)
            _star(d, x, y, 26, c2)
        for x, y in mids:
            _star(d, x, y, 30, c1)
    # pastdagi daraja yozuvi
    rw, rh = 330, 68
    rx, ry = (W - rw) // 2, H - th - rh - 24
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(ov).rounded_rectangle((rx, ry, rx + rw, ry + rh), 18, fill=(10, 8, 24, 190),
                                         outline=c1 + (255,), width=4)
    im = Image.alpha_composite(im.convert("RGBA"), ov).convert("RGB")
    ImageDraw.Draw(im).text((W // 2, ry + rh // 2), rarity.upper(), font=_font(40), fill=c1, anchor="mm")
    out = BytesIO()
    im.save(out, "JPEG", quality=92)
    return out.getvalue()


logging.basicConfig(level=logging.INFO)
bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

db = sqlite3.connect(os.getenv("DB_PATH", "aniwu.db"))
db.row_factory = sqlite3.Row
db.executescript("""
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT, name TEXT,
  money INTEGER DEFAULT 0, diamonds INTEGER DEFAULT 0,
  box_date TEXT DEFAULT '', box_used INTEGER DEFAULT 0, extra_boxes INTEGER DEFAULT 0,
  gift_date TEXT DEFAULT '', gift_used INTEGER DEFAULT 0, invites INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS collections(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, reward INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS aniwus(id INTEGER PRIMARY KEY, col_id INTEGER, name TEXT, rarity TEXT, price INTEGER, photo TEXT);
CREATE TABLE IF NOT EXISTS inv(uid INTEGER, aid INTEGER, qty INTEGER, PRIMARY KEY(uid, aid));
CREATE TABLE IF NOT EXISTS market(id INTEGER PRIMARY KEY AUTOINCREMENT, seller INTEGER, aid INTEGER, price INTEGER);
CREATE TABLE IF NOT EXISTS claimed(uid INTEGER, col_id INTEGER, PRIMARY KEY(uid, col_id));
CREATE TABLE IF NOT EXISTS game(id INTEGER PRIMARY KEY, aid INTEGER);
CREATE TABLE IF NOT EXISTS admins(id INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS chats(id INTEGER PRIMARY KEY, title TEXT, type TEXT, adm INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS stk(key TEXT, fid TEXT, PRIMARY KEY(key, fid));
""")
try:
    db.execute("ALTER TABLE aniwus ADD COLUMN orig TEXT")  # ramkasiz asl rasm
    db.commit()
except sqlite3.OperationalError:
    pass


# ---------- yordamchi funksiyalar ----------
def q(sql, *a):
    return db.execute(sql, a).fetchall()


def q1(sql, *a):
    return db.execute(sql, a).fetchone()


def ex(sql, *a):
    cur = db.execute(sql, a)
    db.commit()
    return cur


esc = html.escape


def is_owner(uid):
    return uid == OWNER_ID


def is_admin(uid):
    return uid == OWNER_ID or uid in ENV_ADMINS or q1("SELECT 1 FROM admins WHERE id=?", uid) is not None


def ensure_user(u):
    ex("INSERT INTO users(id,username,name) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET "
       "username=excluded.username, name=excluded.name", u.id, (u.username or "").lower(), u.full_name)


def find_user(ref):
    ref = ref.strip()
    if ref.isdigit():
        return q1("SELECT * FROM users WHERE id=?", int(ref))
    return q1("SELECT * FROM users WHERE username=?", ref.lstrip("@").lower())


def get_aniwu(aid):
    return q1("SELECT * FROM aniwus WHERE id=?", aid)


def emo(a):
    return RARITY[a["rarity"]][0]


def plain(a):  # tugma matni uchun
    return f"{emo(a)} #{a['id']} {a['name']}"


def label(a):  # xabar matni uchun (HTML)
    return f"{emo(a)} #{a['id']} <b>{esc(a['name'])}</b>"


def card(a):
    c = q1("SELECT name FROM collections WHERE id=?", a["col_id"])
    return (f"{emo(a)} <b>{esc(a['name'])}</b>\n━━━━━━━━━━━━\n"
            f"🏷 Daraja: <b>{a['rarity'].upper()}</b>\n💰 Narx: <b>{a['price']:,}</b>\n"
            f"🔢 Raqam: <b>#{a['id']}</b>\n📚 To'plam: {esc(c['name']) if c else '-'}")


def kb(rows):
    return Kb(inline_keyboard=[[Btn(text=t, callback_data=d) for t, d in r] for r in rows])


def balance(uid, col):
    return q1(f"SELECT {col} FROM users WHERE id=?", uid)[col]


def has_bal(uid, col, n):
    return is_owner(uid) or balance(uid, col) >= n


def change_bal(uid, col, n):  # col: "money" yoki "diamonds"; ega uchun o'zgarmaydi (cheksiz)
    if not is_owner(uid):
        ex(f"UPDATE users SET {col}={col}+? WHERE id=?", n, uid)


def qty(uid, aid):
    if is_owner(uid):
        return 10**9
    r = q1("SELECT qty FROM inv WHERE uid=? AND aid=?", uid, aid)
    return r["qty"] if r else 0


def take(uid, aid, n=1):
    if not is_owner(uid):
        ex("UPDATE inv SET qty=qty-? WHERE uid=? AND aid=?", n, uid, aid)
        ex("DELETE FROM inv WHERE qty<=0")


async def give(uid, aid, n=1):
    if not is_owner(uid):
        ex("INSERT INTO inv VALUES(?,?,?) ON CONFLICT(uid,aid) DO UPDATE SET qty=qty+?", uid, aid, n, n)
        await check_collections(uid)


def progress(uid, col_id):
    total = q1("SELECT COUNT(*) n FROM aniwus WHERE col_id=?", col_id)["n"]
    if is_owner(uid):
        return total, total
    have = q1("SELECT COUNT(*) n FROM inv i JOIN aniwus a ON a.id=i.aid WHERE i.uid=? AND a.col_id=?",
              uid, col_id)["n"]
    return have, total


async def safe_send(chat, text, **kw):
    try:
        return await bot.send_message(chat, text, **kw)
    except Exception:
        return None


async def photo_to(chat, photo, caption, effect=None, **kw):
    if effect:
        try:
            return await bot.send_photo(chat, photo, caption=caption, message_effect_id=effect, **kw)
        except Exception:
            pass
    try:
        return await bot.send_photo(chat, photo, caption=caption, **kw)
    except Exception:
        logging.exception("send_photo")
        return None


async def fx(chat, *keys):
    """Birinchi stikeri bor kalit bo'yicha tasodifiy stiker yuboradi."""
    for k in keys:
        r = q("SELECT fid FROM stk WHERE key=?", k)
        if r:
            try:
                await bot.send_sticker(chat, random.choice(r)["fid"])
            except Exception:
                pass
            return


async def download(fid):
    f = await bot.get_file(fid)
    return (await bot.download_file(f.file_path)).read()


async def check_collections(uid):
    for c in q("SELECT * FROM collections WHERE id NOT IN (SELECT col_id FROM claimed WHERE uid=?)", uid):
        have, total = progress(uid, c["id"])
        if total and have == total:
            ex("INSERT INTO claimed VALUES(?,?)", uid, c["id"])
            change_bal(uid, "diamonds", c["reward"])
            await fx(uid, "toplam")
            await safe_send(uid, f"🏆 <b>Tabriklaymiz!</b>\n\"{esc(c['name'])}\" to'plamini to'liq yig'dingiz!\n"
                                 f"🎁 Mukofot: <b>+{c['reward']}</b> 💎 olmos")


async def broadcast(ids, fn):
    ok = 0
    for i in ids:
        try:
            await fn(i)
            ok += 1
        except Exception:
            pass
        await asyncio.sleep(0.05)
    return ok


def target_ids(kind):
    ids = []
    if kind in ("users", "all"):
        ids += [r["id"] for r in q("SELECT id FROM users")]
    if kind in ("chats", "all"):
        ids += [r["id"] for r in q("SELECT id FROM chats")]
    return ids


def pick_aniwu():
    rows = q("SELECT * FROM aniwus")
    if not rows:
        return None
    rar = random.choices(list(RARITY), weights=[v[1] for v in RARITY.values()])[0]
    return random.choice([r for r in rows if r["rarity"] == rar] or rows)


def open_box(uid):
    """(Aniwu, izoh) yoki (None, xato matni) qaytaradi."""
    a = pick_aniwu()
    if not a:
        return None, "Hozircha Aniwu yo'q."
    note = ""
    if not is_owner(uid):
        u = q1("SELECT * FROM users WHERE id=?", uid)
        today = str(date.today())
        used = u["box_used"] if u["box_date"] == today else 0
        if used < FREE_BOXES_PER_DAY:
            ex("UPDATE users SET box_date=?, box_used=? WHERE id=?", today, used + 1, uid)
            note = "🎁 Tekin sandiq"
        elif u["extra_boxes"] > 0:
            ex("UPDATE users SET extra_boxes=extra_boxes-1 WHERE id=?", uid)
            note = "🎁 Bonus sandiq"
        elif u["money"] >= BOX_PRICE:
            change_bal(uid, "money", -BOX_PRICE)
            note = f"📦 Sandiq ochildi: -{BOX_PRICE} 💰"
        else:
            return None, f"❌ Tekin sandiqlar tugadi. Yana ochish {BOX_PRICE} 💰, pulingiz yetmaydi."
    return a, note


def convert(uid, d, n):
    """d: 'md' = pul ➜ olmos, 'dm' = olmos ➜ pul. (ok, xabar) qaytaradi."""
    cost = n * MONEY_PER_DIAMOND
    if d == "md":
        if not has_bal(uid, "money", cost):
            return False, "❌ Pul yetarli emas."
        change_bal(uid, "money", -cost)
        change_bal(uid, "diamonds", n)
        return True, f"✅ {cost:,} 💰 ➜ {n} 💎"
    if not has_bal(uid, "diamonds", n):
        return False, "❌ Olmos yetarli emas."
    change_bal(uid, "diamonds", -n)
    change_bal(uid, "money", cost)
    return True, f"✅ {n} 💎 ➜ {cost:,} 💰"


def bal_line(uid):
    if is_owner(uid):
        return "💰 ∞   💎 ∞"
    u = q1("SELECT money, diamonds FROM users WHERE id=?", uid)
    return f"💰 {u['money']:,}   💎 {u['diamonds']}"


def up_chance(mine, tgt):
    return round(min(95, max(1, mine["price"] / tgt["price"] * 100)), 1)


async def do_buy(uid, mid):
    """(ok, xabar) qaytaradi."""
    it = q1("SELECT * FROM market WHERE id=?", mid)
    if not it:
        return False, "Allaqachon sotilgan yoki olib tashlangan."
    if it["seller"] == uid:
        return False, "Bu sizning e'loningiz."
    if not has_bal(uid, "money", it["price"]):
        return False, "❌ Pul yetarli emas."
    ex("DELETE FROM market WHERE id=?", it["id"])
    change_bal(uid, "money", -it["price"])
    change_bal(it["seller"], "money", it["price"])
    await give(uid, it["aid"])
    await safe_send(it["seller"], f"💰 {label(get_aniwu(it['aid']))} sotildi!\n+{it['price']:,} 💰")
    return True, "✅ Sotib olindi!"


def list_market(uid, aid, price):
    if not is_admin(uid):  # adminlar o'z zaxirasisiz ham qo'ya oladi
        if qty(uid, aid) < 1:
            return None
        take(uid, aid)
    return ex("INSERT INTO market(seller,aid,price) VALUES(?,?,?)", uid, aid, price).lastrowid


def stats():
    return {t: q1(f"SELECT COUNT(*) n FROM {t}")["n"] for t in ("users", "aniwus", "collections", "market")}


def stats_text():
    s = stats()
    app = f"✅ {WEBAPP_URL}" if WEBAPP_URL else "❌ ulanmagan"
    return (f"📊 <b>Statistika</b>\n━━━━━━━━━━━━\n👥 A'zolar: <b>{s['users']}</b>\n"
            f"💬 Guruhlar: <b>{q1('SELECT COUNT(*) n FROM chats')['n']}</b>\n"
            f"📚 To'plamlar: <b>{s['collections']}</b>\n🎴 Aniwular: <b>{s['aniwus']}</b>\n"
            f"🏪 Marketda: <b>{s['market']}</b>\n📱 Ilova: {app}")


def profile_text(uid):
    u, own = q1("SELECT * FROM users WHERE id=?", uid), is_owner(uid)
    used = u["box_used"] if u["box_date"] == str(date.today()) else 0
    cnt = q1("SELECT COALESCE(SUM(qty),0) n, COUNT(*) k FROM inv WHERE uid=?", uid)
    role = "👑 Ega" if own else "🛠 Admin" if is_admin(uid) else "👤 A'zo"
    aniwus = "∞ (hammasi)" if own else f"{cnt['n']} ({cnt['k']} xil)"
    return (f"{role}  <b>{esc(u['name'])}</b>\n━━━━━━━━━━━━\n{bal_line(uid)}\n"
            f"🎴 Aniwular: <b>{aniwus}</b>\n"
            f"🎁 Tekin sandiq: <b>{max(FREE_BOXES_PER_DAY - used, 0)}</b> + <b>{u['extra_boxes']}</b> bonus\n"
            f"👥 Takliflar: <b>{u['invites']}</b>")


# ---------- holat (ko'p bosqichli amallar) ----------
ST = {}
STK_PENDING = {}


def setst(uid, **kw):
    ST[uid] = {"t": time.time(), **kw}


def has_state(m):
    uid = m.from_user.id if m.from_user else None
    s = ST.get(uid)
    if s and time.time() - s["t"] > 900:
        ST.pop(uid, None)
        return False
    return s is not None


def shared_id(m):
    us = m.users_shared
    if not us:
        return None
    users = getattr(us, "users", None)
    if users:
        return users[0].user_id
    ids = getattr(us, "user_ids", None)
    return ids[0] if ids else None


# ---------- menyular ----------
MAIN_BTNS = {"🎁 Sandiq ochish", "👤 Profil", "🎒 Kolleksiya", "🏪 Market", "👥 Do'stlar", "📱 Ilova",
             "🛠 Admin panel", "👑 Ega paneli", "❌ Bekor qilish"}


def menu(uid):
    rows = [["🎁 Sandiq ochish"], ["👤 Profil", "🎒 Kolleksiya"], ["🏪 Market", "👥 Do'stlar"], ["📱 Ilova"]]
    if is_owner(uid):
        rows.append(["👑 Ega paneli"])
    elif is_admin(uid):
        rows.append(["🛠 Admin panel"])
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=b) for b in r] for r in rows],
                               resize_keyboard=True)


def pick_user_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="👤 Foydalanuvchini tanlash",
                        request_users=KeyboardButtonRequestUsers(request_id=1, user_is_bot=False, max_quantity=1))],
        [KeyboardButton(text="❌ Bekor qilish")]], resize_keyboard=True, one_time_keyboard=True)


async def ask_user(chat, text):
    await bot.send_message(chat, text + "\n\n<i>Yoki @username / ID yozing.</i>", reply_markup=pick_user_kb())


def nav_menu(name):
    if name == "coll":
        return "🎒 <b>Kolleksiya</b>\nNima qilamiz?", kb([
            [("🎴 Aniwularim", "pg:view:inv:0"), ("📚 To'plamlar", "cols")],
            [("💝 Sovga qilish", "pg:gift:inv:0"), ("🔄 Almashtirish", "pg:trA:inv:0")],
            [("⬆️ Upgrade", "pg:upA:inv:0")]])
    return (f"🏪 <b>Market</b>\nAniwu sotib oling yoki soting, valyutani almashtiring.\n"
            f"<i>1 💎 = {MONEY_PER_DIAMOND:,} 💰</i>"), kb([
        [("🛒 Aniwu market", "mk:0"), ("📤 Aniwu sotish", "pg:sell:inv:0")],
        [("📋 E'lonlarim", "mine")],
        [("💰 ➜ 💎 Pul → Olmos", "cv:md"), ("💎 ➜ 💰 Olmos → Pul", "cv:dm")]])


ADMIN_TITLE = "🛠 <b>Admin panel</b>\nTanlang 👇"


def admin_kb(uid):
    rows = [[("📚 To'plam qo'shish", "ad:col"), ("🖼 Aniwu qo'shish", "ad:an")],
            [("🗑 Aniwu o'chirish", "ad:del"), ("♻️ Ramkalarni yangilash", "ad:reframe")],
            [("📢 Xabar yuborish", "ad:bc"), ("🎮 O'yin boshlash", "ad:game")],
            [("🎁 Pul / Olmos / Aniwu yuborish", "ad:give")],
            [("🎭 Stikerlar", "ad:stk"), ("📊 Statistika", "ad:stats")],
            [("💬 Guruhlar", "ad:groups")]]
    if is_owner(uid):
        rows.append([("👮 Adminlar", "ad:adm")])
    return kb(rows)


def targets_kb(p):
    nu = q1("SELECT COUNT(*) n FROM users")["n"]
    nc = q1("SELECT COUNT(*) n FROM chats")["n"]
    return kb([[(f"👥 A'zolar ({nu})", f"{p}:users"), (f"💬 Guruhlar ({nc})", f"{p}:chats")],
               [(f"🌐 Hammasi ({nu + nc})", f"{p}:all")], [("🔙 Admin", "nav:admin")]])


def give_target_kb():
    return kb([[("👤 Bitta foydalanuvchiga", "gt:one"), ("👥 Hamma a'zoga", "gt:all")], [("🔙 Admin", "nav:admin")]])


async def show(ev, text, markup=None):
    """Callback bo'lsa xabarni tahrirlaydi, aks holda yangi xabar yuboradi."""
    if isinstance(ev, CallbackQuery):
        try:
            return await ev.message.edit_text(text, reply_markup=markup)
        except Exception as e:
            if "not modified" in str(e):
                return None
            return await ev.message.answer(text, reply_markup=markup)
    return await ev.answer(text, reply_markup=markup)


# ---------- Aniwu tanlash ro'yxati (sahifalangan) ----------
PICK = {  # amal: (sarlavha, orqaga)
    "view": ("🎴 <b>Aniwuni tanlang</b>", "nav:coll"),
    "gift": ("💝 <b>Qaysi Aniwuni sovg'a qilasiz?</b>", "nav:coll"),
    "trA": ("🔄 Almashtirish uchun <b>o'zingizning</b> Aniwuni tanlang", "nav:coll"),
    "trB": ("🔄 Do'stingizning qaysi Aniwusini olmoqchisiz?", "nav:coll"),
    "upA": ("⬆️ <b>Qaysi Aniwuni upgrade qilasiz?</b> (u sarflanadi)", "nav:coll"),
    "upB": ("⬆️ <b>Qaysi Aniwuga</b> upgrade qilmoqchisiz?", "nav:coll"),
    "sell": ("📤 <b>Qaysi Aniwuni sotasiz?</b>", "nav:market"),
    "gmA": ("🎮 O'yin uchun Aniwuni tanlang", "nav:admin"),
    "gvA": ("🎁 Qaysi Aniwuni yuborasiz?", "nav:admin"),
    "del": ("🗑 Qaysi Aniwuni o'chirasiz?", "nav:admin"),
}
AN_ACTS = set(PICK)


def src_rows(src, uid):
    if src == "all":
        return q("SELECT a.*, NULL AS qty FROM aniwus a ORDER BY a.id")
    if src[0] == "c":
        return q("SELECT a.*, NULL AS qty FROM aniwus a WHERE a.col_id=? ORDER BY a.id", int(src[1:]))
    owner = uid if src == "inv" else int(src[1:])
    if is_owner(owner):
        return q("SELECT a.*, NULL AS qty FROM aniwus a ORDER BY a.id")
    return q("SELECT a.*, i.qty AS qty FROM inv i JOIN aniwus a ON a.id=i.aid WHERE i.uid=? "
             "ORDER BY a.price DESC, a.id", owner)


async def show_picker(ev, uid, act, src, page):
    rows = src_rows(src, uid)
    title, back = PICK[act]
    if act == "view" and src.startswith("c"):
        back = "cols"
    pages = max(1, -(-len(rows) // PAGE))
    page = min(max(page, 0), pages - 1)
    btns = []
    for r in rows[page * PAGE:(page + 1) * PAGE]:
        mark = ("✅ " if qty(uid, r["id"]) > 0 else "▫️ ") if src.startswith("c") else ""
        extra = f" ×{r['qty']}" if r["qty"] and r["qty"] > 1 else ""
        btns.append([(f"{mark}{plain(r)} · {r['price']:,}💰{extra}", f"{act}:{r['id']}")])
    if pages > 1:
        nv = []
        if page > 0:
            nv.append(("⬅️", f"pg:{act}:{src}:{page - 1}"))
        nv.append((f"{page + 1}/{pages}", "noop"))
        if page < pages - 1:
            nv.append(("➡️", f"pg:{act}:{src}:{page + 1}"))
        btns.append(nv)
    btns.append([("🔙 Orqaga", back)])
    await show(ev, title + ("" if rows else "\n\n<i>Hozircha bo'sh.</i>"), kb(btns))


async def cols_menu(c, uid):
    rows = q("SELECT * FROM collections ORDER BY id")
    if not rows:
        return await show(c, "📚 Hozircha to'plam yo'q.", kb([[("🔙 Orqaga", "nav:coll")]]))
    btns = []
    for col in rows:
        have, total = progress(uid, col["id"])
        btns.append([(f"📚 {col['name']} · {have}/{total} · 💎{col['reward']}", f"col:{col['id']}")])
    btns.append([("🔙 Orqaga", "nav:coll")])
    await show(c, "📚 <b>To'plamlar</b>\nTo'liq yig'sangiz 💎 olmos mukofoti beriladi 👇", kb(btns))


# ---------- sandiq, sovga, bozor ----------
async def do_open(chat, uid):
    a, note = open_box(uid)
    if not a:
        return await bot.send_message(chat, note)
    await fx(chat, "sandiq")
    try:
        await bot.send_dice(chat, emoji="🎰")
        await asyncio.sleep(2.6)
    except Exception:
        pass
    await fx(chat, a["rarity"])
    await photo_to(chat, a["photo"], f"{note}\n\n✨ <b>Sizga tushdi!</b>\n\n" + card(a),
                   EFFECT.get(a["rarity"]), reply_markup=kb([[("🎁 Yana ochish", "box")]]))
    await give(uid, a["id"])


async def do_gift(chat, uid, aid, tid):
    a = get_aniwu(aid)
    if not a or qty(uid, aid) < 1:
        return await bot.send_message(chat, "❌ Sizda bu Aniwu yo'q.")
    if not is_owner(uid):
        u, today = q1("SELECT * FROM users WHERE id=?", uid), str(date.today())
        used = u["gift_used"] if u["gift_date"] == today else 0
        if used >= GIFTS_PER_DAY:
            return await bot.send_message(chat, f"❌ Kuniga {GIFTS_PER_DAY} tagacha sovg'a qilish mumkin.")
        ex("UPDATE users SET gift_date=?, gift_used=? WHERE id=?", today, used + 1, uid)
    take(uid, aid)
    await give(tid, aid)
    await fx(chat, "sovga")
    await bot.send_message(chat, f"💝 Sovg'a yuborildi!\n{label(a)}")
    me = q1("SELECT name FROM users WHERE id=?", uid)
    await photo_to(tid, a["photo"], f"💝 <b>{esc(me['name'])}</b> sizga sovg'a yubordi!\n\n" + card(a),
                   EFFECT.get(a["rarity"]))


async def market_list(c, page):
    total = q1("SELECT COUNT(*) n FROM market")["n"]
    rows = q("SELECT m.id mid, m.price mprice, a.id aid, a.name, a.rarity FROM market m "
             "JOIN aniwus a ON a.id=m.aid ORDER BY m.id DESC LIMIT ? OFFSET ?", PAGE, page * PAGE)
    if not rows:
        return await show(c, "🏪 Market hozircha bo'sh.", kb([[("🔙 Orqaga", "nav:market")]]))
    btns = [[(f"{RARITY[r['rarity']][0]} #{r['aid']} {r['name']} · {r['mprice']:,}💰", f"mi:{r['mid']}")]
            for r in rows]
    nv = []
    if page > 0:
        nv.append(("⬅️", f"mk:{page - 1}"))
    if (page + 1) * PAGE < total:
        nv.append(("➡️", f"mk:{page + 1}"))
    if nv:
        btns.append(nv)
    btns.append([("🔙 Orqaga", "nav:market")])
    await show(c, f"🛒 <b>Aniwu market</b> · {total} ta e'lon\nBatafsil ko'rish uchun bosing 👇", kb(btns))


async def market_item(c, mid):
    it = q1("SELECT * FROM market WHERE id=?", mid)
    if not it:
        return await c.answer("Allaqachon sotilgan yoki olib tashlangan.", show_alert=True)
    a, seller = get_aniwu(it["aid"]), q1("SELECT name FROM users WHERE id=?", it["seller"])
    cap = (card(a) + f"\n\n💸 Sotuv narxi: <b>{it['price']:,}</b> 💰\n"
           f"👤 Sotuvchi: {esc(seller['name']) if seller else '-'}")
    await photo_to(c.message.chat.id, a["photo"], cap,
                   reply_markup=kb([[(f"🛒 Sotib olish · {it['price']:,} 💰", f"buy:{mid}")], [("🔙 Market", "mk:0")]]))


# ---------- Aniwu ustidagi amallar (tugmalar) ----------
async def an_action(c, uid, act, aid):
    a, chat = get_aniwu(aid), c.message.chat.id
    if not a:
        return await c.answer("Topilmadi.", show_alert=True)
    if act == "view":
        have = "∞" if is_owner(uid) else qty(uid, aid)
        return await photo_to(chat, a["photo"], card(a) + f"\n🎒 Sizda: <b>{have}</b> ta")
    if act in ("gift", "trA", "sell", "upA") and qty(uid, aid) < 1:
        return await c.answer("❌ Sizda bu Aniwu yo'q.", show_alert=True)
    if act in ("gmA", "gvA", "del") and not is_admin(uid):
        return await c.answer("⛔ Faqat adminlar uchun.", show_alert=True)
    if act == "gift":
        setst(uid, act="gift", aid=aid)
        await ask_user(chat, f"💝 {label(a)}\nKimga sovg'a qilasiz? Do'stingizni tanlang 👇")
    elif act == "trA":
        setst(uid, act="tr_to", mine=aid)
        await ask_user(chat, f"🔄 Sizniki: {label(a)}\nKim bilan almashasiz? 👇")
    elif act == "trB":
        s = ST.get(uid)
        if not s or s["act"] != "tr_pick":
            return await c.answer("Seans tugagan, qaytadan boshlang.", show_alert=True)
        mine, to = get_aniwu(s["mine"]), s["to"]
        if qty(to, aid) < 1 or qty(uid, mine["id"]) < 1:
            return await c.answer("❌ Aniwu endi mavjud emas.", show_alert=True)
        markup = kb([[("✅ Qabul qilish", f"tr:y:{uid}:{mine['id']}:{aid}"), ("❌ Rad etish", "tr:n")]])
        sent = await safe_send(to, f"🔄 <b>{esc(c.from_user.full_name)}</b> almashuv taklif qilmoqda:\n\n"
                                   f"🎁 U beradi: {label(mine)}\n🎴 Siz berasiz: {label(a)}", reply_markup=markup)
        ST.pop(uid, None)
        await show(c, "✅ Taklif yuborildi! Javobni kuting." if sent else
                   "❌ Foydalanuvchiga yozib bo'lmadi (u botni ishga tushirmagan).")
    elif act == "upA":
        setst(uid, act="up", mine=aid)
        await show_picker(c, uid, "upB", "all", 0)
    elif act == "upB":
        s = ST.get(uid)
        if not s or s["act"] != "up":
            return await c.answer("Seans tugagan, qaytadan boshlang.", show_alert=True)
        mine = get_aniwu(s["mine"])
        if mine["id"] == aid:
            return await c.answer("Bir xil Aniwu tanlandi.", show_alert=True)
        s["tgt"] = aid
        ch = up_chance(mine, a)
        await show(c, f"⬆️ <b>Upgrade</b>\n\n{label(mine)}\n⬇️\n{label(a)}\n\n🎲 Omad ehtimoli: <b>{ch}%</b>\n"
                      f"⚠️ Omadsiz bo'lsa {esc(mine['name'])} yo'qoladi.",
                   kb([[(f"🎲 Boshlash ({ch}%)", "up:go")], [("🔙 Orqaga", "nav:coll")]]))
    elif act == "sell":
        setst(uid, act="sell", aid=aid)
        b = a["price"]
        await show(c, f"📤 {label(a)}\nSotuv narxini tanlang (asl narxi {b:,} 💰):",
                   kb([[(f"{b:,} 💰", f"sp:{b}"), (f"{b * 2:,} 💰", f"sp:{b * 2}")],
                       [(f"{b * 5:,} 💰", f"sp:{b * 5}"), ("✍️ Boshqa narx", "sp:x")],
                       [("🔙 Orqaga", "nav:market")]]))
    elif act == "gmA":
        setst(uid, act="game", aid=aid)
        await show(c, f"🎮 O'yin: {label(a)}\nKimlarga yuboramiz?", targets_kb("gg"))
    elif act == "gvA":
        s = ST.get(uid)
        if not s or s["act"] != "give":
            return await c.answer("Seans tugagan.", show_alert=True)
        s["val"] = aid
        await show(c, f"🎁 {label(a)}\nKimga yuboramiz?", give_target_kb())
    elif act == "del":
        await show(c, f"🗑 {label(a)}\nRostdan o'chirasizmi? (hammaning kolleksiyasidan ham o'chadi)",
                   kb([[("✅ Ha, o'chirish", f"delc:{aid}"), ("❌ Yo'q", "nav:admin")]]))


async def give_many(ids, kind, val):
    a = get_aniwu(val) if kind == "aniwu" else None
    for i in ids:
        try:
            if a:
                await give(i, val)
                await photo_to(i, a["photo"], "🎁 <b>Admin sizga sovg'a yubordi!</b>\n\n" + card(a),
                               EFFECT.get(a["rarity"]))
            else:
                change_bal(i, "money" if kind == "pul" else "diamonds", val)
                await safe_send(i, f"🎁 <b>Admin sizga sovg'a yubordi!</b>\n"
                                   f"{val:,} {'💰 pul' if kind == 'pul' else '💎 olmos'}")
        except Exception:
            logging.exception("give_many")
        await asyncio.sleep(0.04)
    return len(ids)


async def create_aniwu(chat, s, price):
    aid = q1("SELECT COALESCE(MAX(id),0)+1 n FROM aniwus")["n"]
    ex("INSERT INTO aniwus(id,col_id,name,rarity,price,photo,orig) VALUES(?,?,?,?,?,?,?)",
       aid, s["col"], s["name"], s["rar"], price, s["photo"], s["photo"])
    a = get_aniwu(aid)
    try:  # daraja ramkasini rasmga qo'shamiz
        framed = await asyncio.to_thread(frame_image, await download(s["photo"]), s["rar"])
        sent = await bot.send_photo(chat, BufferedInputFile(framed, "aniwu.jpg"),
                                    caption="✅ <b>Qo'shildi!</b> (ramka bilan)\n\n" + card(a))
        ex("UPDATE aniwus SET photo=? WHERE id=?", sent.photo[-1].file_id, aid)
    except Exception:
        logging.exception("frame")
        await bot.send_photo(chat, s["photo"], caption="✅ <b>Qo'shildi</b> (ramkasiz)\n\n" + card(a))


async def reframe_all(chat):
    rows = q("SELECT id, rarity, orig FROM aniwus WHERE orig IS NOT NULL")
    n = 0
    for r in rows:
        try:
            framed = await asyncio.to_thread(frame_image, await download(r["orig"]), r["rarity"])
            msg = await bot.send_photo(chat, BufferedInputFile(framed, "a.jpg"))
            ex("UPDATE aniwus SET photo=? WHERE id=?", msg.photo[-1].file_id, r["id"])
            await msg.delete()
            n += 1
        except Exception:
            logging.exception("reframe")
    return n, len(rows)


# ---------- callback tugmalarni yo'naltirish ----------
ADMIN_KEYS = {"ad", "ac", "ar", "delc", "bt", "gg", "gk", "gv", "gt", "sk", "skc", "adm"}


async def route(c, uid, p):
    k, chat = p[0], c.message.chat.id
    if k == "noop":
        return
    if k in ADMIN_KEYS and not is_admin(uid):
        return await c.answer("⛔ Faqat adminlar uchun.", show_alert=True)
    if k == "nav":
        if p[1] == "admin":
            if not is_admin(uid):
                return await c.answer("⛔ Faqat adminlar uchun.", show_alert=True)
            return await show(c, ADMIN_TITLE, admin_kb(uid))
        text, markup = nav_menu(p[1])
        return await show(c, text, markup)
    if k == "cols":
        return await cols_menu(c, uid)
    if k == "col":
        return await show_picker(c, uid, "view", f"c{p[1]}", 0)
    if k == "pg":
        return await show_picker(c, uid, p[1], p[2], int(p[3]))
    if k in AN_ACTS:
        return await an_action(c, uid, k, int(p[1]))
    if k == "box":
        return await do_open(chat, uid)
    if k == "mk":
        return await market_list(c, int(p[1]))
    if k == "mi":
        return await market_item(c, int(p[1]))
    if k == "buy":
        it = q1("SELECT * FROM market WHERE id=?", int(p[1]))
        ok, msg = await do_buy(uid, int(p[1]))
        await c.answer(msg, show_alert=True)
        if ok and it:
            a = get_aniwu(it["aid"])
            await fx(chat, "sotib")
            await photo_to(chat, a["photo"], "🛒 <b>Xarid muvaffaqiyatli!</b>\n\n" + card(a), EFFECT.get(a["rarity"]))
        return
    if k == "mine":
        rows = q("SELECT m.id mid, m.price mprice, a.id aid, a.name, a.rarity FROM market m "
                 "JOIN aniwus a ON a.id=m.aid WHERE m.seller=? ORDER BY m.id DESC", uid)
        btns = [[(f"🗑 {RARITY[r['rarity']][0]} #{r['aid']} {r['name']} · {r['mprice']:,}💰", f"unl:{r['mid']}")]
                for r in rows]
        btns.append([("🔙 Orqaga", "nav:market")])
        return await show(c, "📋 <b>Mening e'lonlarim</b>\nOlib tashlash uchun bosing 👇" if rows
                          else "📋 Sizda e'lon yo'q.", kb(btns))
    if k == "unl":
        it = q1("SELECT * FROM market WHERE id=?", int(p[1]))
        if not it or (it["seller"] != uid and not is_admin(uid)):
            return await c.answer("Topilmadi.", show_alert=True)
        ex("DELETE FROM market WHERE id=?", it["id"])
        if not is_admin(it["seller"]):
            await give(it["seller"], it["aid"])
        await c.answer("✅ Olib tashlandi, Aniwu qaytdi.", show_alert=True)
        p[0], p[1:] = "mine", []
        return await route(c, uid, p)
    if k == "sp":
        s = ST.get(uid)
        if not s or s.get("act") != "sell":
            return await c.answer("Seans tugagan.", show_alert=True)
        if p[1] == "x":
            s["act"] = "sell_price"
            return await bot.send_message(chat, "✍️ Sotuv narxini raqam bilan yozing (masalan 2500):")
        mid = list_market(uid, s["aid"], int(p[1]))
        ST.pop(uid, None)
        return await show(c, f"🏪 Marketga qo'yildi! (#{mid})" if mid else "❌ Sizda bu Aniwu yo'q.",
                          kb([[("📋 E'lonlarim", "mine"), ("🔙 Market", "nav:market")]]))
    if k == "up":
        s = ST.pop(uid, None)
        if not s or s.get("act") != "up" or "tgt" not in s:
            return await c.answer("Seans tugagan.", show_alert=True)
        mine, tgt = get_aniwu(s["mine"]), get_aniwu(s["tgt"])
        if qty(uid, mine["id"]) < 1:
            return await c.answer("❌ Sizda bu Aniwu yo'q.", show_alert=True)
        take(uid, mine["id"])
        try:
            await c.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        if random.random() * 100 < up_chance(mine, tgt):
            await give(uid, tgt["id"])
            await fx(chat, "up_ok")
            await photo_to(chat, tgt["photo"], "🎉 <b>Upgrade muvaffaqiyatli!</b>\n\n" + card(tgt),
                           EFFECT.get(tgt["rarity"]))
        else:
            await fx(chat, "up_fail")
            await bot.send_message(chat, f"💥 <b>Omad kelmadi...</b>\n{label(mine)} yo'qoldi.")
        return
    if k == "tr":
        if p[1] == "n":
            return await show(c, "❌ Almashuv rad etildi.")
        frm, mine, theirs = int(p[2]), int(p[3]), int(p[4])
        if qty(frm, mine) < 1 or qty(uid, theirs) < 1:
            return await show(c, "⚠️ Almashuv bekor: Aniwu yetarli emas.")
        take(frm, mine)
        take(uid, theirs)
        await give(uid, mine)
        await give(frm, theirs)
        await fx(chat, "almashuv")
        await show(c, f"✅ <b>Almashuv bajarildi!</b>\n{label(get_aniwu(theirs))} ➜ {label(get_aniwu(mine))}")
        return await safe_send(frm, f"✅ Almashuv qabul qilindi!\n{label(get_aniwu(mine))} ➜ {label(get_aniwu(theirs))}")
    if k == "cv":
        d = p[1]
        t = ("💰 ➜ 💎 <b>Nechta 💎 olmoqchisiz?</b>" if d == "md" else "💎 ➜ 💰 <b>Nechta 💎 ni pulga aylantirasiz?</b>")
        return await show(c, f"{t}\n<i>1 💎 = {MONEY_PER_DIAMOND:,} 💰</i>\n\n{bal_line(uid)}",
                          kb([[(f"{n} 💎", f"cvn:{d}:{n}") for n in (1, 5, 10, 50)],
                              [("✍️ Boshqa son", f"cvn:{d}:x")], [("🔙 Orqaga", "nav:market")]]))
    if k == "cvn":
        d = p[1]
        if p[2] == "x":
            setst(uid, act="cv_amt", d=d)
            return await bot.send_message(chat, "🔢 Nechta 💎? Raqam yozing:")
        ok, msg = convert(uid, d, int(p[2]))
        return await show(c, f"{msg}\n\n{bal_line(uid)}", kb([[("🔁 Yana", f"cv:{d}"), ("🔙 Market", "nav:market")]]))
    # ---- admin ----
    if k == "ad":
        w = p[1]
        if w == "col":
            setst(uid, act="col_name")
            return await bot.send_message(chat, "📚 Yangi <b>to'plam nomini</b> yozing:")
        if w == "an":
            cols = q("SELECT * FROM collections ORDER BY id")
            if not cols:
                return await c.answer("Avval to'plam qo'shing.", show_alert=True)
            return await show(c, "🖼 Qaysi to'plamga qo'shamiz?",
                              kb([[(f"📚 {x['name']}", f"ac:{x['id']}")] for x in cols] + [[("🔙 Admin", "nav:admin")]]))
        if w == "del":
            return await show_picker(c, uid, "del", "all", 0)
        if w == "reframe":
            await c.answer("⏳ Ishlanmoqda...")
            n, tot = await reframe_all(chat)
            return await bot.send_message(chat, f"♻️ {n}/{tot} ta Aniwu ramkasi yangilandi.\n"
                                                f"<i>(Faqat yangi versiyada qo'shilganlar yangilanadi.)</i>")
        if w == "bc":
            setst(uid, act="bc_msg")
            return await bot.send_message(chat, "📢 Yubormoqchi bo'lgan xabaringizni yuboring (matn, rasm, video, "
                                                "stiker — istalgani).")
        if w == "game":
            return await show_picker(c, uid, "gmA", "all", 0)
        if w == "give":
            return await show(c, "🎁 Nima yuboramiz?", kb([[("💰 Pul", "gk:pul"), ("💎 Olmos", "gk:olmos")],
                                                         [("🎴 Aniwu", "gk:aniwu")], [("🔙 Admin", "nav:admin")]]))
        if w == "stk":
            lines, btns = [], []
            for key, name in STK_KEYS:
                n = q1("SELECT COUNT(*) n FROM stk WHERE key=?", key)["n"]
                lines.append(f"{name}: <b>{n}</b>")
                if n:
                    btns.append([(f"🧹 {name} — tozalash", f"skc:{key}")])
            btns.append([("🔙 Admin", "nav:admin")])
            return await show(c, "🎭 <b>Stikerlar</b>\n\nBotga stiker yuboring (premium ham bo'ladi), qaysi holatda "
                                 "chiqishini tanlaysiz. Bir holatga bir nechta qo'shsangiz, tasodifiy chiqadi.\n\n"
                              + "\n".join(lines), kb(btns))
        if w == "stats":
            return await show(c, stats_text(), kb([[("🔙 Admin", "nav:admin")]]))
        if w == "groups":
            rows = q("SELECT * FROM chats ORDER BY title")
            body = "\n".join(f"{'🛡' if r['adm'] else '•'} {esc(r['title'] or str(r['id']))} <i>({r['type']})</i>"
                             for r in rows) or ("Hozircha yo'q.\nBotni guruhga qo'shib admin qiling; guruhda biror "
                                                "xabar yozilgach ro'yxatga tushadi.")
            return await show(c, f"💬 <b>Guruhlar</b>\n\n{body}", kb([[("🔙 Admin", "nav:admin")]]))
        if w == "adm":
            if not is_owner(uid):
                return await c.answer("⛔ Faqat ega uchun.", show_alert=True)
            btns = []
            for r in q("SELECT id FROM admins"):
                u = q1("SELECT name FROM users WHERE id=?", r["id"])
                btns.append([(f"❌ {u['name'] if u else r['id']} ({r['id']})", f"adm:del:{r['id']}")])
            btns += [[("➕ Admin qo'shish", "adm:add")], [("🔙 Admin", "nav:admin")]]
            return await show(c, "👮 <b>Adminlar</b>\nO'chirish uchun ismni bosing 👇", kb(btns))
    if k == "adm":
        if not is_owner(uid):
            return await c.answer("⛔ Faqat ega uchun.", show_alert=True)
        if p[1] == "add":
            setst(uid, act="adm_add")
            return await ask_user(chat, "👮 Yangi adminni tanlang 👇")
        ex("DELETE FROM admins WHERE id=?", int(p[2]))
        return await route(c, uid, ["ad", "adm"])
    if k == "ac":
        setst(uid, act="an", col=int(p[1]))
        rows = [[(f"{e} {r.upper()}", f"ar:{r}")] for r, (e, _) in RARITY.items()]
        return await show(c, "🏷 Darajasini tanlang:", kb(rows + [[("🔙 Admin", "nav:admin")]]))
    if k == "ar":
        s = ST.get(uid)
        if not s or s.get("act") != "an":
            return await c.answer("Seans tugagan.", show_alert=True)
        s["rar"], s["act"] = p[1], "an_photo"
        return await bot.send_message(chat, f"🖼 {RARITY[p[1]][0]} <b>{p[1].upper()}</b> Aniwu <b>rasmini</b> yuboring "
                                            "(tik, 3:4 bo'lsa yaxshi).")
    if k == "delc":
        aid = int(p[1])
        for tbl, col in (("aniwus", "id"), ("inv", "aid"), ("market", "aid")):
            ex(f"DELETE FROM {tbl} WHERE {col}=?", aid)
        return await show(c, "🗑 O'chirildi.", kb([[("🔙 Admin", "nav:admin")]]))
    if k == "bt":
        s = ST.pop(uid, None)
        if not s or "src" not in s:
            return await c.answer("Seans tugagan.", show_alert=True)
        cid, mid = s["src"]
        await c.answer("⏳ Yuborilmoqda...")
        n = await broadcast(target_ids(p[1]), lambda t: bot.copy_message(t, cid, mid))
        return await bot.send_message(chat, f"📢 <b>{n}</b> ta chatga yuborildi.", reply_markup=menu(uid))
    if k == "gg":
        s = ST.pop(uid, None)
        a = get_aniwu(s["aid"]) if s and s.get("act") == "game" else None
        if not a:
            return await c.answer("Seans tugagan.", show_alert=True)
        ex("INSERT OR REPLACE INTO game VALUES(1,?)", a["id"])
        img = a["orig"] or a["photo"]  # ramkasiz rasm: daraja ko'rinmasin
        cap = ("🎮 <b>O'YIN!</b>\n━━━━━━━━━━━━\n❓ Bu qaysi Aniwu?\n✍️ Birinchi bo'lib <b>ISMI</b> va <b>DARAJASINI</b> yozing.\n"
               "Masalan: <code>Naruto epic</code>\n"
               "Darajalar: common · epic · legendary · mifik · ultimate\n\n🎁 Yutuq: shu Aniwu!")
        await c.answer("⏳ Yuborilmoqda...")
        n = await broadcast(target_ids(p[1]), lambda t: bot.send_photo(t, img, caption=cap))
        return await bot.send_message(chat, f"🎮 O'yin boshlandi! <b>{n}</b> ta chatga yuborildi.", reply_markup=menu(uid))
    if k == "gk":
        kind = p[1]
        setst(uid, act="give", kind=kind)
        if kind == "aniwu":
            return await show_picker(c, uid, "gvA", "all", 0)
        pre = (500, 1000, 5000, 10000) if kind == "pul" else (1, 5, 10, 50)
        return await show(c, f"🎁 Qancha {'💰 pul' if kind == 'pul' else '💎 olmos'}?",
                          kb([[(f"{n:,}", f"gv:{n}") for n in pre], [("✍️ Boshqa son", "gv:x")],
                              [("🔙 Admin", "nav:admin")]]))
    if k == "gv":
        s = ST.get(uid)
        if not s or s.get("act") != "give":
            return await c.answer("Seans tugagan.", show_alert=True)
        if p[1] == "x":
            s["act"] = "give_val"
            return await bot.send_message(chat, "🔢 Miqdorni raqam bilan yozing:")
        s["val"] = int(p[1])
        return await show(c, "Kimga yuboramiz?", give_target_kb())
    if k == "gt":
        s = ST.get(uid)
        if not s or s.get("act") != "give" or "val" not in s:
            return await c.answer("Seans tugagan.", show_alert=True)
        if p[1] == "one":
            s["act"] = "give_to"
            return await ask_user(chat, "👤 Kimga yuboramiz? Tanlang 👇")
        ST.pop(uid, None)
        await c.answer("⏳ Yuborilmoqda...")
        n = await give_many([r["id"] for r in q("SELECT id FROM users")], s["kind"], s["val"])
        return await bot.send_message(chat, f"✅ <b>{n}</b> ta a'zoga yuborildi.", reply_markup=menu(uid))
    if k == "sk":
        fid = STK_PENDING.get(uid)
        if not fid:
            return await c.answer("Avval stiker yuboring.", show_alert=True)
        ex("INSERT OR IGNORE INTO stk VALUES(?,?)", p[1], fid)
        n = q1("SELECT COUNT(*) n FROM stk WHERE key=?", p[1])["n"]
        return await c.answer(f"✅ Saqlandi! Bu holatda {n} ta stiker bor.", show_alert=True)
    if k == "skc":
        ex("DELETE FROM stk WHERE key=?", p[1])
        return await c.answer("🧹 Tozalandi.", show_alert=True)


@dp.callback_query()
async def on_cb(c: CallbackQuery):
    try:
        await route(c, c.from_user.id, c.data.split(":"))
    except Exception:
        logging.exception("callback")
        try:
            await c.answer("⚠️ Xatolik yuz berdi, qayta urinib ko'ring.", show_alert=True)
        except Exception:
            pass
        return
    try:
        await c.answer()
    except Exception:
        pass


# ---------- xabarlar ----------
@dp.message(CommandStart())
async def start(m: Message, command: CommandObject, is_new: bool):
    if m.chat.type != "private":
        return
    uid, arg = m.from_user.id, command.args or ""
    ST.pop(uid, None)
    if is_new and arg.startswith("ref_") and arg[4:].isdigit():
        inviter = int(arg[4:])
        if inviter != uid and q1("SELECT 1 FROM users WHERE id=?", inviter):
            ex("UPDATE users SET invites=invites+1 WHERE id=?", inviter)
            if balance(inviter, "invites") % INVITES_PER_BOX == 0:
                ex("UPDATE users SET extra_boxes=extra_boxes+1 WHERE id=?", inviter)
                await safe_send(inviter, f"🎁 {INVITES_PER_BOX} ta do'st taklif qildingiz!\n<b>+1</b> tekin sandiq")
    await fx(m.chat.id, "start")
    me = await bot.me()
    await m.answer(f"🎴 <b>Aniwu kolleksiya botiga xush kelibsiz!</b>\n\nAnime Aniwu kartalarini yig'ing, "
                   f"almashtiring, soting va 💎 olmos yuting!\n\n🎁 Kuniga {FREE_BOXES_PER_DAY} ta tekin sandiq\n"
                   f"👥 {INVITES_PER_BOX} ta do'st = 1 tekin sandiq\n📚 To'plamni yig'sangiz — olmos mukofoti\n\n"
                   "Pastdagi menyudan foydalaning 👇", reply_markup=menu(uid))


@dp.message(Command("menu"))
async def show_menu(m: Message):
    ST.pop(m.from_user.id, None)
    await m.answer("📋 Menyu yangilandi.", reply_markup=menu(m.from_user.id))


@dp.message(F.chat.type == "private", F.text.in_(MAIN_BTNS))
async def on_menu(m: Message):
    uid, t = m.from_user.id, m.text
    ST.pop(uid, None)
    if t == "❌ Bekor qilish":
        return await m.answer("Bekor qilindi.", reply_markup=menu(uid))
    if t == "🎁 Sandiq ochish":
        return await do_open(m.chat.id, uid)
    if t == "👤 Profil":
        return await m.answer(profile_text(uid), reply_markup=kb([[("🎴 Aniwularim", "pg:view:inv:0"),
                                                                    ("💱 Valyuta", "nav:market")]]))
    if t == "🎒 Kolleksiya":
        text, markup = nav_menu("coll")
        return await m.answer(text, reply_markup=markup)
    if t == "🏪 Market":
        text, markup = nav_menu("market")
        return await m.answer(text, reply_markup=markup)
    if t == "👥 Do'stlar":
        u = q1("SELECT invites FROM users WHERE id=?", uid)
        link = f"https://t.me/{(await bot.me()).username}?start=ref_{uid}"
        left = INVITES_PER_BOX - u["invites"] % INVITES_PER_BOX
        share = Kb(inline_keyboard=[[Btn(text="📤 Do'stlarga ulashish", url="https://t.me/share/url?url=" + quote(link)
                                         + "&text=" + quote("🎴 Aniwu kolleksiya botiga qo'shiling!"))]])
        return await m.answer(f"👥 <b>Do'stlarni taklif qiling</b>\n━━━━━━━━━━━━\n🔗 {link}\n\n"
                              f"👤 Taklif qilinganlar: <b>{u['invites']}</b>\n"
                              f"🎁 Keyingi tekin sandiqgacha: <b>{left}</b> ta do'st", reply_markup=share)
    if t == "📱 Ilova":
        if WEBAPP_URL:
            return await m.answer("📱 Ilovani ochish uchun tugmani bosing 👇", reply_markup=Kb(
                inline_keyboard=[[Btn(text="📱 Ilovani ochish", web_app=WebAppInfo(url=WEBAPP_URL))]]))
        hint = ("\n\n🛠 Admin uchun: Railway → Aniwu-bot → Settings → Networking → <b>Generate Domain</b>, "
                "so'ng Redeploy qiling.") if is_admin(uid) else ""
        return await m.answer("📱 Ilova hozircha ulanmagan." + hint)
    if t in ("🛠 Admin panel", "👑 Ega paneli"):
        if not is_admin(uid):
            return
        return await m.answer(ADMIN_TITLE, reply_markup=admin_kb(uid))


@dp.message(F.chat.type == "private", F.sticker)
async def got_sticker(m: Message):
    uid = m.from_user.id
    if not is_admin(uid):
        return
    STK_PENDING[uid] = m.sticker.file_id
    rows = [[(STK_KEYS[i][1], f"sk:{STK_KEYS[i][0]}")] for i in range(len(STK_KEYS))]
    await m.answer("🎭 Bu stikerni qachon ishlatay? Tanlang 👇 (bir nechta holatga ham qo'shsa bo'ladi)",
                   reply_markup=kb(rows))


USER_ACTS = {"gift", "tr_to", "give_to", "adm_add"}


@dp.message(F.chat.type == "private", has_state)
async def pending(m: Message):
    uid = m.from_user.id
    s = ST[uid]
    act, txt = s["act"], (m.text or "").strip()
    num = int(txt) if txt.isdigit() else None
    if act in USER_ACTS:
        tid = shared_id(m)
        if tid is None and txt:
            u = find_user(txt)
            tid = u["id"] if u else (int(txt) if act == "adm_add" and txt.isdigit() else None)
        ST.pop(uid, None)
        known = tid is not None and q1("SELECT 1 FROM users WHERE id=?", tid) is not None
        if tid is None or (act != "adm_add" and (not known or tid == uid)):
            return await m.answer("❌ Foydalanuvchi topilmadi. U botni /start qilgan bo'lishi kerak.",
                                  reply_markup=menu(uid))
        await m.answer("✅ Tanlandi.", reply_markup=menu(uid))
        if act == "gift":
            return await do_gift(m.chat.id, uid, s["aid"], tid)
        if act == "tr_to":
            setst(uid, act="tr_pick", mine=s["mine"], to=tid)
            return await show_picker(m, uid, "trB", f"u{tid}", 0)
        if act == "give_to":
            await give_many([tid], s["kind"], s["val"])
            return await m.answer("✅ Yuborildi.")
        ex("INSERT OR IGNORE INTO admins VALUES(?)", tid)
        await safe_send(tid, "👮 Siz admin qilindingiz! /menu ni bosing.")
        return await m.answer("✅ Admin qo'shildi.")
    if act in ("sell_price", "cv_amt", "give_val", "an_price", "col_reward"):
        if not num or num < 1:
            return await m.answer("🔢 Iltimos, musbat raqam yozing.")
        ST.pop(uid, None)
        if act == "sell_price":
            mid = list_market(uid, s["aid"], num)
            return await m.answer(f"🏪 Marketga qo'yildi! (#{mid})" if mid else "❌ Sizda bu Aniwu yo'q.",
                                  reply_markup=menu(uid))
        if act == "cv_amt":
            ok, msg = convert(uid, s["d"], num)
            return await m.answer(f"{msg}\n\n{bal_line(uid)}", reply_markup=menu(uid))
        if act == "give_val":
            s["val"], s["act"] = num, "give"
            ST[uid] = s
            return await m.answer("Kimga yuboramiz?", reply_markup=give_target_kb())
        if act == "col_reward":
            try:
                cur = ex("INSERT INTO collections(name,reward) VALUES(?,?)", s["name"], num)
            except sqlite3.IntegrityError:
                return await m.answer("❌ Bunday nomli to'plam bor.", reply_markup=menu(uid))
            return await m.answer(f"✅ To'plam <b>#{cur.lastrowid} {esc(s['name'])}</b> ochildi!\n"
                                  f"Mukofot: {num} 💎", reply_markup=menu(uid))
        return await create_aniwu(m.chat.id, s, num)
    if act == "col_name" and txt:
        setst(uid, act="col_reward", name=txt)
        return await m.answer(f"📚 <b>{esc(txt)}</b>\nTo'liq yig'ganga necha 💎 olmos mukofot beriladi? (raqam)")
    if act == "an_photo":
        if not m.photo:
            return await m.answer("🖼 Iltimos, rasm yuboring.")
        s["photo"], s["act"] = m.photo[-1].file_id, "an_name"
        return await m.answer("✍️ Aniwu <b>nomini</b> yozing:")
    if act == "an_name" and txt:
        s["name"], s["act"] = txt, "an_price"
        return await m.answer("💰 Aniwu <b>narxini</b> yozing (raqam):")
    if act == "bc_msg":
        s["src"] = (m.chat.id, m.message_id)
        return await m.answer("📢 Kimlarga yuboramiz?", reply_markup=targets_kb("bt"))
    ST.pop(uid, None)  # eskirgan holat: oddiy matn sifatida (o'yin taxmini bo'lishi mumkin)
    if m.text and not m.text.startswith("/"):
        await guess(m)


@dp.message(F.text & ~F.text.startswith("/"))
async def guess(m: Message):
    """O'yin: Aniwuning ismi va darajasini birinchi topgan yutadi (shaxsiy chatda ham, guruhda ham)."""
    g = q1("SELECT * FROM game WHERE id=1")
    a = get_aniwu(g["aid"]) if g else None
    if not a or not m.from_user:
        return
    t = m.text.lower()
    if a["name"].lower() in t and a["rarity"] in t:
        ex("DELETE FROM game WHERE id=1")
        ensure_user(m.from_user)
        await give(m.from_user.id, a["id"])
        await fx(m.chat.id, "yutuq")
        await photo_to(m.chat.id, a["photo"], "🏆 <b>Siz topdingiz!</b> Yutuq sizniki 🎁\n\n" + card(a),
                       EFFECT.get(a["rarity"]))
        text = f"🏆 <b>{esc(m.from_user.full_name)}</b> birinchi topdi!\nJavob: {label(a)} ({a['rarity'].upper()})"
        await broadcast(target_ids("all"), lambda cid: bot.send_message(cid, text))


@dp.my_chat_member()
async def on_my_chat_member(e: ChatMemberUpdated):
    if e.chat.type == "private":
        return
    st = str(getattr(e.new_chat_member.status, "value", e.new_chat_member.status))
    if st in ("administrator", "member", "creator"):
        ex("INSERT INTO chats(id,title,type,adm) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
           "title=excluded.title, adm=excluded.adm", e.chat.id, e.chat.title or "", e.chat.type, int(st != "member"))
    else:
        ex("DELETE FROM chats WHERE id=?", e.chat.id)


async def reg(handler, event, data):
    """Foydalanuvchi va guruhlarni ro'yxatga oladi."""
    u, ch = data.get("event_from_user"), data.get("event_chat")
    data["is_new"] = False
    if ch is not None and ch.type in ("group", "supergroup", "channel"):
        ex("INSERT INTO chats(id,title,type) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title",
           ch.id, ch.title or "", ch.type)
    elif ch is not None and ch.type == "private" and u and not u.is_bot:
        data["is_new"] = q1("SELECT 1 FROM users WHERE id=?", u.id) is None
        ensure_user(u)
    return await handler(event, data)


dp.update.outer_middleware(reg)

# ---------- Mini App ("Ilova") serveri ----------
HERE = os.path.dirname(os.path.abspath(__file__))
PHOTOS = {}


def verify(init_data):
    """Telegram initData imzosini tekshiradi, foydalanuvchini qaytaradi."""
    try:
        d = dict(parse_qsl(init_data, strict_parsing=True))
        h = d.pop("hash")
        s = "\n".join(f"{k}={v}" for k, v in sorted(d.items()))
        key = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
        if hmac.compare_digest(hmac.new(key, s.encode(), hashlib.sha256).hexdigest(), h):
            return json.loads(d["user"])
    except Exception:
        pass
    return None


def api(fn):
    async def wrapper(req):
        body = await req.json()
        u = verify(body.get("initData", ""))
        if not u or not q1("SELECT 1 FROM users WHERE id=?", u["id"]):
            return web.json_response({"error": "Botda /start bosing."}, status=401)
        return web.json_response(await fn(u["id"], body))
    return wrapper


def aj(r):
    return {"id": r["id"], "name": r["name"], "rarity": r["rarity"], "price": r["price"]}


async def api_me(uid, body):
    u, own = q1("SELECT * FROM users WHERE id=?", uid), is_owner(uid)
    used = u["box_used"] if u["box_date"] == str(date.today()) else 0
    inv = ([dict(aj(r), qty=None) for r in q("SELECT * FROM aniwus ORDER BY id")] if own else
           [dict(aj(r), qty=r["qty"]) for r in q(
               "SELECT a.*, i.qty FROM inv i JOIN aniwus a ON a.id=i.aid WHERE i.uid=? ORDER BY a.id", uid)])
    cols = []
    for c in q("SELECT * FROM collections"):
        items = [dict(aj(a), own=qty(uid, a["id"]) > 0) for a in q("SELECT * FROM aniwus WHERE col_id=?", c["id"])]
        cols.append({"name": c["name"], "reward": c["reward"], "items": items,
                     "have": sum(i["own"] for i in items)})
    mk = [dict(aj(r), price=r["mprice"], base=r["price"], mid=r["mid"], mine=r["seller"] == uid) for r in q(
        "SELECT m.id mid, m.price mprice, m.seller, a.* FROM market m JOIN aniwus a ON a.id=m.aid "
        "ORDER BY m.id DESC LIMIT 40")]
    return {"role": "owner" if own else "admin" if is_admin(uid) else "member", "name": u["name"],
            "money": None if own else u["money"], "diamonds": None if own else u["diamonds"],
            "free": max(FREE_BOXES_PER_DAY - used, 0) + u["extra_boxes"], "price": BOX_PRICE,
            "inv": inv, "cols": cols, "market": mk, "stats": stats() if is_admin(uid) else None}


async def api_open(uid, body):
    a, note = open_box(uid)
    if not a:
        return {"error": note}
    await give(uid, a["id"])
    return {"aniwu": aj(a), "note": note}


async def api_buy(uid, body):
    ok, msg = await do_buy(uid, int(body.get("mid", 0)))
    return {"ok": ok, "msg": msg}


async def photo(req):
    a = get_aniwu(int(req.match_info["aid"]))
    if not a:
        raise web.HTTPNotFound()
    if a["photo"] not in PHOTOS:
        f = await bot.get_file(a["photo"])
        PHOTOS[a["photo"]] = (await bot.download_file(f.file_path)).read()
    return web.Response(body=PHOTOS[a["photo"]], content_type="image/jpeg",
                        headers={"Cache-Control": "max-age=86400"})


async def index(req):
    return web.FileResponse(os.path.join(HERE, "app.html"))


async def api_convert(uid, body):
    d, n = body.get("d"), int(body.get("n", 0))
    if d not in ("md", "dm") or n < 1:
        return {"ok": False, "msg": "Noto'g'ri so'rov"}
    ok, msg = convert(uid, d, n)
    return {"ok": ok, "msg": msg}


async def health(req):
    return web.Response(text="ok")


async def main():
    app = web.Application()
    app.add_routes([web.get("/", index), web.get("/health", health), web.get("/photo/{aid}", photo),
                    web.post("/api/me", api(api_me)), web.post("/api/open", api(api_open)),
                    web.post("/api/buy", api(api_buy)), web.post("/api/convert", api(api_convert))])
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    logging.info("Ilova manzili: %s", WEBAPP_URL or "ulanmagan")
    if WEBAPP_URL:  # chatdagi ko'k "Ilova" tugmasi
        try:
            await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Ilova", web_app=WebAppInfo(url=WEBAPP_URL)))
        except Exception:
            logging.exception("menu button")
    try:
        await bot.set_my_commands([BotCommand(command="start", description="Botni boshlash"),
                                   BotCommand(command="menu", description="Menyuni yangilash")])
    except Exception:
        logging.exception("commands")
    await dp.start_polling(bot, allowed_updates=["message", "callback_query", "my_chat_member"])


if __name__ == "__main__":
    asyncio.run(main())
