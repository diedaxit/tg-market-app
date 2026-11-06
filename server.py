import sqlite3
import random
import time
import os
import json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from aiogram.types import LabeledPrice, InlineQueryResultArticle, InputTextMessageContent, InlineKeyboardMarkup, InlineKeyboardButton
from bot import bot

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_NAME = "market.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            member_number INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_user_id INTEGER UNIQUE,
            username TEXT,
            balance REAL DEFAULT 2500.0,
            level INTEGER DEFAULT 1,
            xp INTEGER DEFAULT 0,
            season_xp INTEGER DEFAULT 0,
            season_claimed TEXT DEFAULT '[]',
            luck_multi REAL DEFAULT 1.0,
            luck_until INTEGER DEFAULT 0,
            vip_until INTEGER DEFAULT 0,
            max_hold INTEGER DEFAULT 100,
            max_channels INTEGER DEFAULT 2,
            ref_by INTEGER DEFAULT NULL,
            refs_count INTEGER DEFAULT 0,
            smm_lvl INTEGER DEFAULT 1,
            buyer_lvl INTEGER DEFAULT 0,
            clan_id TEXT DEFAULT NULL,
            pity_50 INTEGER DEFAULT 0,
            pity_100 INTEGER DEFAULT 0,
            last_wheel INTEGER DEFAULT 0,
            daily_streak INTEGER DEFAULT 0,
            last_daily INTEGER DEFAULT 0,
            q_spins INTEGER DEFAULT 0,
            q_rare INTEGER DEFAULT 0,
            q_crafts INTEGER DEFAULT 0,
            q_claimed TEXT DEFAULT '[]',
            ach_stats TEXT DEFAULT '{}',
            ach_claimed TEXT DEFAULT '[]',
            last_claim INTEGER DEFAULT 0,
            created_at INTEGER
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS usernames (
            tag TEXT PRIMARY KEY,
            item_type TEXT DEFAULT 'username',
            owner_id INTEGER,
            rarity TEXT,
            income_per_sec REAL,
            sell_price REAL,
            reasons TEXT,
            is_equipped INTEGER DEFAULT 0,
            channel_slot INTEGER DEFAULT 0,
            is_saved INTEGER DEFAULT 1,
            on_market INTEGER DEFAULT 0,
            created_at INTEGER
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS market_lots (
            lot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            tag TEXT UNIQUE,
            item_type TEXT,
            rarity TEXT,
            income_per_sec REAL,
            reasons TEXT,
            seller_id INTEGER,
            seller_name TEXT,
            is_auction INTEGER DEFAULT 0,
            start_price REAL,
            current_price REAL,
            buyout_price REAL,
            highest_bidder_id INTEGER DEFAULT NULL,
            highest_bidder_name TEXT DEFAULT '',
            bids_count INTEGER DEFAULT 0,
            ends_at INTEGER,
            created_at INTEGER
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS clans (
            clan_id TEXT PRIMARY KEY,
            name TEXT,
            treasury REAL DEFAULT 0.0,
            members_count INTEGER DEFAULT 1
        )
    """)
    conn.commit()

    cur.execute("PRAGMA table_info(users)")
    u_cols = [c[1] for c in cur.fetchall()]
    new_u_cols = [
        ("season_xp", "INTEGER DEFAULT 0"), ("season_claimed", "TEXT DEFAULT '[]'"),
        ("vip_until", "INTEGER DEFAULT 0"), ("max_hold", "INTEGER DEFAULT 100"),
        ("max_channels", "INTEGER DEFAULT 2"), ("ref_by", "INTEGER DEFAULT NULL"),
        ("refs_count", "INTEGER DEFAULT 0"), ("smm_lvl", "INTEGER DEFAULT 1"),
        ("buyer_lvl", "INTEGER DEFAULT 0"), ("clan_id", "TEXT DEFAULT NULL"),
        ("pity_50", "INTEGER DEFAULT 0"), ("pity_100", "INTEGER DEFAULT 0"),
        ("last_wheel", "INTEGER DEFAULT 0"), ("daily_streak", "INTEGER DEFAULT 0"),
        ("last_daily", "INTEGER DEFAULT 0"), ("q_spins", "INTEGER DEFAULT 0"),
        ("q_rare", "INTEGER DEFAULT 0"), ("q_crafts", "INTEGER DEFAULT 0"),
        ("q_claimed", "TEXT DEFAULT '[]'"), ("ach_stats", "TEXT DEFAULT '{}'"),
        ("ach_claimed", "TEXT DEFAULT '[]'")
    ]
    for col, ctype in new_u_cols:
        if col not in u_cols:
            try: cur.execute(f"ALTER TABLE users ADD COLUMN {col} {ctype}")
            except Exception: pass

    cur.execute("PRAGMA table_info(usernames)")
    t_cols = [c[1] for c in cur.fetchall()]
    for col, ctype in [("item_type", "TEXT DEFAULT 'username'"), ("is_equipped", "INTEGER DEFAULT 0"),
                       ("channel_slot", "INTEGER DEFAULT 0"), ("is_saved", "INTEGER DEFAULT 1"), ("on_market", "INTEGER DEFAULT 0")]:
        if col not in t_cols:
            try: cur.execute(f"ALTER TABLE usernames ADD COLUMN {col} {ctype}")
            except Exception: pass

    default_clans = [
        ("ton_whales", "🐋 TON Whales", 340000.0, 19),
        ("durov_syndicate", "👑 Durov Syndicate", 680000.0, 34),
        ("emerald_cartel", "💚 Emerald Cartel", 210000.0, 12)
    ]
    for cid, cname, ctr, cmem in default_clans:
        cur.execute("INSERT OR IGNORE INTO clans (clan_id, name, treasury, members_count) VALUES (?, ?, ?, ?)", (cid, cname, ctr, cmem))

    cur.execute("SELECT COUNT(*) FROM market_lots")
    if cur.fetchone()[0] == 0:
        now = int(time.time())
        seed_lots = [
            ("+888 0777", "number", "Divine", 250000.0, "👑 Короткая серия 0XXX|🎰 Три семерки 777|💎 Топ-1 ценность Fragment", 0, "Fragment_DAO", 1, 950000.0, 950000.0, 2500000.0, 4, now + 14400),
            ("@durov_king", "username", "Luxury", 1500.0, "💰 Статусный корень|🚫 Без цифр", 0, "Whale_TON", 1, 45000.0, 45000.0, 90000.0, 7, now + 7200),
            ("+888 8880 888", "number", "Exclusive", 65000.0, "🔥 Палиндром 888|💎 Эксклюзивный пул +888", 0, "CryptoBoss", 0, 320000.0, 320000.0, 320000.0, 0, now + 86400),
            ("@mellstroy", "username", "Mythic", 450.0, "⭐ Топ-стример|🚫 Без цифр и знаков", 0, "MediaLord", 1, 18500.0, 18500.0, 40000.0, 12, now + 5400)
        ]
        for st in seed_lots:
            cur.execute("""
                INSERT INTO market_lots (tag, item_type, rarity, income_per_sec, reasons, seller_id, seller_name, is_auction, start_price, current_price, buyout_price, bids_count, ends_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (*st, now))

    conn.commit()
    conn.close()

init_db()

RARITIES = [
    {"name": "Common",       "ru": "Обычный",        "w": 750000, "inc": 1,      "xp": 5,     "sell": 50},
    {"name": "Uncommon",     "ru": "Необычный",      "w": 175000, "inc": 5,      "xp": 15,    "sell": 250},
    {"name": "Rare",         "ru": "Редкий",         "w": 55000,  "inc": 15,     "xp": 40,    "sell": 750},
    {"name": "Epic",         "ru": "Эпический",      "w": 15000,  "inc": 50,     "xp": 100,   "sell": 2500},
    {"name": "Legendary",    "ru": "Легендарный",    "w": 3500,   "inc": 200,    "xp": 300,   "sell": 10000},
    {"name": "Mythic",       "ru": "Мифический",     "w": 1000,   "inc": 450,    "xp": 800,   "sell": 25000},
    {"name": "Luxury",       "ru": "Роскошный",      "w": 300,    "inc": 1500,   "xp": 1500,  "sell": 75000},
    {"name": "Ultra-Mythic", "ru": "Ультра-Мифик",   "w": 90,     "inc": 5000,   "xp": 2500,  "sell": 200000},
    {"name": "Exclusive",    "ru": "Эксклюзивный",   "w": 25,     "inc": 25000,  "xp": 5000,  "sell": 800000},
    {"name": "Divine",       "ru": "Божественный",   "w": 5,      "inc": 100000, "xp": 15000, "sell": 3000000}
]

SPIN_TIERS = {
    "tier_0": {"min_idx": 0, "cost": 100,    "title": "Любая (Обычный+)"},
    "tier_1": {"min_idx": 1, "cost": 300,    "title": "Необычный+"},
    "tier_2": {"min_idx": 2, "cost": 1000,   "title": "Редкий+"},
    "tier_3": {"min_idx": 3, "cost": 3500,   "title": "Эпический+"},
    "tier_4": {"min_idx": 4, "cost": 12000,  "title": "Легендарный+"},
    "tier_5": {"min_idx": 5, "cost": 35000,  "title": "Мифический+"},
    "tier_6": {"min_idx": 6, "cost": 100000, "title": "Luxury+"}
}

WORD_MEANINGS = {
    "x": "Символ «X»", "v": "Знак Победы (V)", "ai": "Искусственный Интеллект", "go": "Движение «Вперед»",
    "durov": "Павел Дуров (Основатель)", "telegram": "Официальный бренд Telegram", "ton": "Блокчейн TON",
    "notcoin": "Главный веб3-токен Notcoin", "redo": "Символ Resistance Dog", "vk": "Бренд соцсети",
    "cat": "Слово «Кот» (3 буквы)", "dog": "Слово «Пес» (3 буквы)", "nft": "Крипто-актив NFT", "god": "Слово «Бог»", "top": "Статус «Топ»",
    "dubai": "Столица роскоши Дубай", "money": "Слово «Деньги»", "rich": "Статус «Богатый»", "gold": "Чистое «Золото»", "king": "Титул «Король»",
    "star": "Слово «Звезда» (4 буквы)", "moon": "Крипто-мем «На Луну»", "litvin": "Топ-блогер Литвин", "mellstroy": "Топ-стример Мелстрой",
    "mrbeast": "Топ-1 блогер мира MrBeast", "tiger": "Слово «Тигр» (5 букв)", "ghost": "Слово «Призрак»", "alpha": "Статус «Альфа»",
    "whale": "Крипто-кит", "wylsa": "Блогер Wylsacom", "subo": "Инфлюенсер Субо", "buster": "Стример Бустер", "hasbulla": "Звезда Хасбик"
}

WORDS = {
    "Divine": ["x", "v", "ai", "go", "ok", "up"],
    "Exclusive": ["durov", "telegram", "ton", "notcoin", "pavel", "vk", "redo"],
    "Ultra-Mythic": ["cat", "dog", "bot", "nft", "god", "top", "ceo"],
    "Luxury": ["dubai", "money", "rich", "gold", "boss", "king", "stars"],
    "Mythic": ["star", "epic", "moon", "flow", "dark", "litvin", "mellstroy", "mrbeast"],
    "Legendary": ["tiger", "ghost", "alpha", "prime", "whale", "wylsa", "subo", "buster", "hasbulla"],
    "Epic": ["shadow", "crypto", "hacker", "sniper", "ninja", "blade", "phantom", "cyber"],
    "Rare": ["gamer", "player", "rocket", "market", "trade", "speed", "hunter", "matrix"]
}

RECENT_ROOTS = []

def generate_live_nickname():
    syllables = ["ka", "mi", "ro", "va", "ze", "lu", "no", "ta", "ke", "si", "da", "ve", "xo", "ni", "ba", "le", "fa", "mo", "ri", "to"]
    prefixes = ["neo", "ava", "max", "leo", "dan", "nik", "art", "tim", "kir", "rom", "vlad", "mak", "sem", "gleb"]
    suffixes = ["ov", "ev", "sk", "ix", "on", "er", "ik", "us", "in", "ax", "ez"]
    t = random.randint(1, 3)
    if t == 1: return "".join(random.sample(syllables, random.randint(2, 3)))
    if t == 2: return random.choice(prefixes) + random.choice(syllables) + random.choice(suffixes)
    return random.choice(prefixes) + random.choice(suffixes)

def generate_phone_number(rarity_name: str, base_inc: float, base_sell: float):
    inc = round(base_inc * 3.5, 1)
    sell = round(base_sell * 4.0, 0)

    if rarity_name == "Divine":
        d = random.choice(["0001", "0007", "0777", "0888", "0999", "0000"])
        tag = f"+888 {d}"
        reasons = ["👑 Ультра-короткая серия +888 0XXX (7 цифр)", "💎 Высший тир Fragment", "🔥 Только 999 таких номеров в мире"]
    elif rarity_name == "Exclusive":
        d = random.choice(["7", "8", "9", "0", "1"])
        tag = f"+888 {d*4} {d*3}"
        reasons = [f"💎 Моно-репит из одних «{d}»", "🔥 Идеальный визуальный паттерн", "🚫 Нулевая энтропия"]
    elif rarity_name == "Ultra-Mythic":
        d1 = random.choice(["7", "8", "9"])
        d2 = random.choice(["0", "1", "5"])
        tag = f"+888 {d1*4} {d2*3}"
        reasons = [f"🔥 Квадра «{d1*4}» + Триплет «{d2*3}»", "✨ Коллекционный VIP-номер"]
    elif rarity_name == "Luxury":
        d = random.choice(["777", "888", "999", "000"])
        tag = f"+888 0{d} {d}"
        reasons = [f"💰 Двойной блок «{d}»", "✨ Премиальный зеркальный код"]
    elif rarity_name == "Mythic":
        d = random.choice(["777", "888", "999"])
        p1 = random.randint(10, 99)
        tag = f"+888 {p1}00 {d}"
        reasons = [f"🎰 Блок «{d}» + Круглая сотня", "✅ Высокая ликвидность на бирже"]
    elif rarity_name == "Legendary":
        tag = random.choice(["+888 1234 567", "+888 7654 321", f"+888 {random.randint(10,99)}77 700"])
        reasons = ["⭐ Редкая числовая последовательность", "✅ Красивый ритм цифр"]
    elif rarity_name == "Epic":
        a, b = random.randint(1, 9), random.randint(1, 9)
        tag = f"+888 {a}{a}{b}{b} {random.randint(100,999)}"
        reasons = [f"✅ Парный дубль «{a}{a}{b}{b}»", "📞 Анонимный NFT-номер"]
    elif rarity_name == "Rare":
        a = random.randint(10, 99)
        tag = f"+888 {a}{a} {random.randint(100,999)}"
        reasons = [f"✅ Повтор блока «{a}{a}»", "📞 Защита приватности Telegram"]
    elif rarity_name == "Uncommon":
        tag = f"+888 {random.randint(100,999)}0 {random.randint(10,99)}0"
        reasons = ["✅ Четные круглые окончания", "📞 Стандартый пул +888"]
    else:
        tag = f"+888 {random.randint(1000,9999)} {random.randint(100,999)}"
        reasons = ["Базовый анонимный номер +888", "Случайная генерация"]

    return tag, inc, sell, "|".join(reasons)

def generate_item(cur, item_type: str, tier_key: str, luck: float, force_epic: bool = False):
    global RECENT_ROOTS
    min_idx = max(3 if force_epic else 0, SPIN_TIERS.get(tier_key, SPIN_TIERS["tier_0"])["min_idx"])

    pool = []
    total_w = 0
    for i, r in enumerate(RARITIES):
        if i >= min_idx:
            w = int(r["w"] * (luck if i >= 3 else 1.0))
            pool.append({"data": r, "w": w})
            total_w += w

    rnd = random.random() * total_w
    picked = pool[-1]["data"]
    for p in pool:
        if rnd < p["w"]:
            picked = p["data"]
            break
        rnd -= p["w"]

    rarity = picked["name"]

    if item_type == "number":
        tag, inc, sell, reas = generate_phone_number(rarity, picked["inc"], picked["sell"])
        return tag, rarity, inc, picked["xp"] * 2, sell, reas

    word = None
    if rarity in WORDS:
        candidates = [w for w in WORDS[rarity] if w not in RECENT_ROOTS] or WORDS[rarity][:]
        random.shuffle(candidates)
        for w in candidates:
            if rarity in ["Divine", "Exclusive", "Ultra-Mythic", "Luxury", "Mythic", "Legendary"]:
                cur.execute("SELECT tag FROM usernames WHERE tag = ?", (f"@{w}",))
                if not cur.fetchone():
                    word = w; break
            else:
                word = w; break
        if not word:
            rarity = "Epic"
            picked = RARITIES[3]
            word = random.choice(WORDS["Epic"])

    if rarity in ["Divine", "Exclusive", "Ultra-Mythic", "Luxury", "Mythic", "Legendary"]:
        tag = f"@{word}"
        meaning = WORD_MEANINGS.get(word, f"Премиум слово «{word.upper()}»")
        reasons = [f"💡 {meaning}", "🚫 Без цифр и символов _", f"📏 {len(word)} букв (Чистый тег)"]
    elif rarity == "Epic":
        tag = f"@{word}{random.randint(1, 19)}"
        reasons = [f"💡 Корень «{word}»", "✅ Короткий индекс без _"]
    elif rarity == "Rare":
        tag = f"@{word}_{random.choice(['vip', 'ton', 'pro', 'hq'])}"
        reasons = ["✅ Статусная приставка", "📏 Звучный корень"]
    elif rarity == "Uncommon":
        base = generate_live_nickname()
        word = base
        tag = f"@{base}{random.choice(['', str(random.randint(10, 99))])}"
        reasons = ["✅ Реалистичный никнейм", "📏 Удобен для чтения"]
    else:
        base = generate_live_nickname()
        word = base
        tag = f"@{base}{random.randint(100, 9999)}"
        reasons = ["Живой пользовательский никнейм", "Стандартный номер"]

    if word:
        RECENT_ROOTS.append(word)
        if len(RECENT_ROOTS) > 6: RECENT_ROOTS.pop(0)

    return tag, rarity, picked["inc"], picked["xp"], picked["sell"], "|".join(reasons)

def settle_expired_auctions(cur):
    now = int(time.time())
    cur.execute("SELECT lot_id, tag, item_type, rarity, income_per_sec, reasons, seller_id, current_price, highest_bidder_id FROM market_lots WHERE ends_at <= ?", (now,))
    expired = cur.fetchall()
    for lot in expired:
        lid, tag, itype, rar, inc, reas, seller_id, price, winner_id = lot
        if winner_id:
            cur.execute("""
                INSERT OR REPLACE INTO usernames (tag, item_type, owner_id, rarity, income_per_sec, sell_price, reasons, is_equipped, channel_slot, is_saved, on_market, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 1, 0, ?)
            """, (tag, itype, winner_id, rar, inc, round(price * 0.7, 0), reas, now))
            if seller_id and seller_id > 0:
                cur.execute("UPDATE users SET balance = balance + ? WHERE tg_user_id = ?", (round(price * 0.95, 2), seller_id))
        else:
            if seller_id and seller_id > 0:
                cur.execute("UPDATE usernames SET on_market = 0, is_saved = 1 WHERE tag = ? AND owner_id = ?", (tag, seller_id))
        cur.execute("DELETE FROM market_lots WHERE lot_id = ?", (lid,))

def auto_sell_unsaved(cur, user_id: int) -> float:
    cur.execute("SELECT SUM(sell_price) FROM usernames WHERE owner_id = ? AND is_saved = 0 AND on_market = 0", (user_id,))
    val = cur.fetchone()[0]
    if val and val > 0:
        cur.execute("UPDATE users SET balance = balance + ? WHERE tg_user_id = ?", (val, user_id))
        cur.execute("DELETE FROM usernames WHERE owner_id = ? AND is_saved = 0 AND on_market = 0", (user_id,))
        return float(val)
    return 0.0

def process_passive_income(cur, user_id: int):
    now = int(time.time())
    cur.execute("SELECT balance, last_claim, smm_lvl, buyer_lvl, vip_until, clan_id FROM users WHERE tg_user_id = ?", (user_id,))
    u = cur.fetchone()
    if not u: return 0.0
    balance, last_claim, smm, buyer, vip_until, clan_id = u
    if last_claim <= 0:
        cur.execute("UPDATE users SET last_claim = ? WHERE tg_user_id = ?", (now, user_id))
        return 0.0
    elapsed = min(max(0, now - last_claim), 43200)
    if elapsed < 2: return 0.0

    cur.execute("SELECT SUM(income_per_sec) FROM usernames WHERE owner_id = ? AND is_equipped = 1 AND is_saved = 1 AND on_market = 0", (user_id,))
    tag_inc = cur.fetchone()[0] or 0.0
    total_rate = (tag_inc + (smm * 2.0) + (buyer * 10.0)) if tag_inc > 0 else 0.0
    if vip_until > now: total_rate *= 2.0
    if clan_id: total_rate *= 1.15

    earned = total_rate * elapsed
    cur.execute("UPDATE users SET balance = balance + ?, last_claim = ? WHERE tg_user_id = ?", (earned, now, user_id))
    return earned

class ReqLogin(BaseModel): user_id: int; username: str = "Player"; ref_by: str = ""
class ReqMint(BaseModel): user_id: int; item_type: str = "username"; tier: str = "tier_0"; spin_count: int = 1
class ReqAction(BaseModel): user_id: int; tag: str; action_type: str; slot: int = 1
class ReqCraft(BaseModel): user_id: int; tags: list[str]
class ReqMarketCreate(BaseModel): user_id: int; username: str; tag: str; is_auction: int; price: float; hours: int = 3
class ReqMarketInteract(BaseModel): user_id: int; username: str; lot_id: int; act: str
class ReqSimple(BaseModel): user_id: int; key: str = ""
class ReqClan(BaseModel): user_id: int; clan_id: str; donate_amount: float = 0.0

@app.get("/")
def serve_index():
    if os.path.exists("index.html"): return FileResponse("index.html")
    return HTMLResponse("<h2>index.html not found</h2>", status_code=404)

@app.post("/api/login")
def login(data: ReqLogin):
    conn = sqlite3.connect(DB_NAME); cur = conn.cursor()
    now = int(time.time())
    settle_expired_auctions(cur)

    cur.execute("SELECT tg_user_id FROM users WHERE tg_user_id = ?", (data.user_id,))
    if not cur.fetchone():
        ref_id = None
        if data.ref_by and data.ref_by.startswith("ref_"):
            try:
                cand = int(data.ref_by.split("_")[1])
                if cand != data.user_id:
                    cur.execute("SELECT refs_count FROM users WHERE tg_user_id = ?", (cand,))
                    ru = cur.fetchone()
                    if ru:
                        ref_id = cand
                        nc = ru[0] + 1
                        rew = 1000.0 if nc == 1 else (3000.0 if nc == 2 else (10000.0 if nc == 5 else (1000000.0 if nc == 20 else 1500.0)))
                        cur.execute("UPDATE users SET refs_count = ?, balance = balance + ? WHERE tg_user_id = ?", (nc, rew, ref_id))
            except Exception: pass
        cur.execute("INSERT INTO users (tg_user_id, username, balance, level, xp, ref_by, last_claim, created_at) VALUES (?, ?, 2500.0, 1, 0, ?, ?, ?)",
                    (data.user_id, data.username, ref_id, now, now))
    else:
        cur.execute("UPDATE users SET username = ? WHERE tg_user_id = ?", (data.username, data.user_id))
        auto_sell_unsaved(cur, data.user_id)
        process_passive_income(cur, data.user_id)

    conn.commit(); conn.close()
    return {"status": "ok"}

@app.get("/api/state/{uid}")
def get_state(uid: int):
    conn = sqlite3.connect(DB_NAME); cur = conn.cursor()
    now = int(time.time())
    settle_expired_auctions(cur)
    process_passive_income(cur, uid)
    conn.commit()

    cur.execute("""
        SELECT rowid, balance, level, xp, season_xp, season_claimed, smm_lvl, buyer_lvl,
               luck_multi, luck_until, vip_until, max_hold, max_channels, refs_count, clan_id,
               pity_50, pity_100, last_wheel, daily_streak, last_daily,
               q_spins, q_rare, q_crafts, q_claimed, ach_stats, ach_claimed
        FROM users WHERE tg_user_id = ?
    """, (uid,))
    u = cur.fetchone()
    if not u:
        conn.close()
        raise HTTPException(404, "User not found")

    (mem_num, bal, lvl, xp, s_xp, s_cl, smm, buyer, luck_m, luck_u, vip_u, max_h, max_ch,
     refs, clan_id, p50, p100, l_wheel, d_streak, l_daily, qs, qr, qc, q_cl, a_st, a_cl) = u

    cur.execute("""
        SELECT tag, item_type, rarity, income_per_sec, sell_price, reasons, is_equipped, channel_slot
        FROM usernames WHERE owner_id = ? AND is_saved = 1 AND on_market = 0
        ORDER BY income_per_sec DESC
    """, (uid,))
    tags = [{
        "tag": r[0], "type": r[1] or "username", "rarity": r[2], "inc": r[3],
        "sell": r[4], "reasons": r[5].split("|") if r[5] else [], "eq": r[6], "slot": r[7]
    } for r in cur.fetchall()]

    cur.execute("SELECT COUNT(*) + 1 FROM users WHERE balance > ?", (bal,))
    my_rank = cur.fetchone()[0]

    cur.execute("SELECT username, balance, level FROM users ORDER BY balance DESC LIMIT 15")
    leaders = [{"username": r[0] or "Магнат", "balance": round(r[1], 0), "level": r[2]} for r in cur.fetchall()]

    cur.execute("SELECT clan_id, name, treasury, members_count FROM clans ORDER BY treasury DESC")
    clans = [{"id": r[0], "name": r[1], "treasury": round(r[2], 0), "members": r[3]} for r in cur.fetchall()]

    cur.execute("""
        SELECT lot_id, tag, item_type, rarity, income_per_sec, reasons, seller_id, seller_name,
               is_auction, current_price, buyout_price, highest_bidder_id, highest_bidder_name, bids_count, ends_at
        FROM market_lots WHERE ends_at > ? ORDER BY created_at DESC LIMIT 50
    """, (now,))
    market = [{
        "lot_id": r[0], "tag": r[1], "type": r[2], "rarity": r[3], "inc": r[4],
        "reasons": r[5].split("|") if r[5] else [], "seller_id": r[6], "seller_name": r[7],
        "is_auction": r[8], "price": r[9], "buyout": r[10], "bidder_id": r[11],
        "bidder_name": r[12], "bids": r[13], "left": max(0, r[14] - now)
    } for r in cur.fetchall()]

    conn.close()
    is_vip = vip_u > now
    active_luck = (luck_m if luck_u > now else 1.0) * (1.5 if is_vip else 1.0)

    return {
        "member_number": mem_num, "balance": round(bal, 2), "level": lvl, "xp": xp,
        "season_xp": s_xp, "season_claimed": json.loads(s_cl or "[]"),
        "smm": smm, "buyer": buyer, "luck_multi": round(active_luck, 2),
        "is_vip": is_vip, "max_hold": max_h, "max_channels": max_ch, "refs_count": refs,
        "clan_id": clan_id, "pity_50": p50, "pity_100": p100,
        "wheel_Wait": max(0, (l_wheel + 1800) - now),
        "daily_streak": d_streak, "can_daily": (now - l_daily) >= 86400,
        "quests": {"spins": qs, "rare": qr, "crafts": qc, "claimed": json.loads(q_cl or "[]")},
        "ach": {"stats": json.loads(a_st or "{}"), "claimed": json.loads(a_cl or "[]")},
        "my_rank": my_rank, "leaders": leaders, "clans": clans, "tags": tags, "market": market
    }

@app.post("/api/mint")
def mint(data: ReqMint):
    if data.tier not in SPIN_TIERS: raise HTTPException(400, "Неверный тир прокрутки")
    if data.spin_count not in [1, 5]: raise HTTPException(400, "Можно крутить 1x или 5x")

    conn = sqlite3.connect(DB_NAME); cur = conn.cursor()
    now = int(time.time())
    auto_sold = auto_sell_unsaved(cur, data.user_id)
    process_passive_income(cur, data.user_id)

    cur.execute("""
        SELECT balance, level, xp, season_xp, luck_multi, luck_until, vip_until, pity_50, pity_100,
               q_spins, q_rare, ach_stats
        FROM users WHERE tg_user_id = ?
    """, (data.user_id,))
    u = cur.fetchone()
    if not u:
        conn.close(); raise HTTPException(404, "User not found")

    bal, lvl, xp, s_xp, luck_m, luck_u, vip_u, p50, p100, qs, qr, ach_raw = u
    type_mult = 5 if data.item_type == "number" else 1
    cost = SPIN_TIERS[data.tier]["cost"] * type_mult * data.spin_count

    if bal < cost:
        conn.close()
        raise HTTPException(400, f"Не хватает на ставку: нужно {cost:,} GRAM")

    is_vip = vip_u > now
    base_luck = (luck_m if luck_u > now else 1.0) * (1.5 if is_vip else 1.0)
    ach_stats = json.loads(ach_raw or "{}")

    drops = []
    added_xp = 0
    for _ in range(data.spin_count):
        p50 += 1; p100 += 1; qs += 1; s_xp += 2
        spin_luck = base_luck * (2.0 if p50 >= 50 else 1.0)
        if p50 >= 50: p50 = 0
        force_epic = False
        if p100 >= 100: force_epic = True; p100 = 0

        for _ in range(12):
            tag, rar, inc, xpg, sell, reas = generate_item(cur, data.item_type, data.tier, spin_luck, force_epic)
            cur.execute("SELECT tag FROM usernames WHERE tag = ?", (tag,))
            if not cur.fetchone(): break
        else:
            tag = f"+888 {random.randint(1000,9999)} {random.randint(100,999)}" if data.item_type == "number" else f"@{generate_live_nickname()}{random.randint(100,999)}"
            rar, inc, xpg, sell, reas = "Common", 1.0, 5, 50.0, "Базовая серия"

        rar_idx = next((i for i, r in enumerate(RARITIES) if r["name"] == rar), 0)
        if rar_idx >= 2: qr += 1
        ach_stats[rar] = ach_stats.get(rar, 0) + 1

        cur.execute("""
            INSERT INTO usernames (tag, item_type, owner_id, rarity, income_per_sec, sell_price, reasons, is_equipped, channel_slot, is_saved, on_market, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, ?)
        """, (tag, data.item_type, data.user_id, rar, inc, sell, reas, now))

        drops.append({"tag": tag, "type": data.item_type, "rarity": rar, "inc": inc, "xp": xpg, "sell": sell, "reasons": reas.split("|")})
        added_xp += xpg

    new_bal = bal - cost
    new_xp = xp + added_xp
    new_lvl = lvl
    while new_xp >= new_lvl * 150:
        new_xp -= new_lvl * 150
        new_lvl += 1

    cur.execute("""
        UPDATE users SET balance = ?, level = ?, xp = ?, season_xp = ?, pity_50 = ?, pity_100 = ?,
                         q_spins = ?, q_rare = ?, ach_stats = ?
        WHERE tg_user_id = ?
    """, (new_bal, new_lvl, new_xp, s_xp, p50, p100, qs, qr, json.dumps(ach_stats), data.user_id))

    conn.commit(); conn.close()
    return {"drops": drops, "auto_sold": auto_sold}

@app.post("/api/action")
def tag_action(data: ReqAction):
    conn = sqlite3.connect(DB_NAME); cur = conn.cursor()
    cur.execute("SELECT sell_price, is_saved, is_equipped, on_market FROM usernames WHERE tag = ? AND owner_id = ?", (data.tag, data.user_id))
    t = cur.fetchone()
    if not t:
        conn.close(); raise HTTPException(400, "Предмет не найден")
    sell_price, is_saved, is_eq, on_mkt = t
    if on_mkt == 1:
        conn.close(); raise HTTPException(400, "Предмет выставлен на Рынке!")

    if data.action_type == "save":
        cur.execute("SELECT max_hold FROM users WHERE tg_user_id = ?", (data.user_id,))
        max_h = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM usernames WHERE owner_id = ? AND is_saved = 1 AND on_market = 0", (data.user_id,))
        if cur.fetchone()[0] >= max_h:
            conn.close(); raise HTTPException(400, f"Хранилище заполнено ({max_h} мест)! Купите слоты или продайте лишнее.")
        cur.execute("UPDATE usernames SET is_saved = 1 WHERE tag = ? AND owner_id = ?", (data.tag, data.user_id))
    elif data.action_type == "sell":
        if is_eq == 1:
            conn.close(); raise HTTPException(400, "Сначала снимите предмет с канала!")
        cur.execute("DELETE FROM usernames WHERE tag = ? AND owner_id = ?", (data.tag, data.user_id))
        cur.execute("UPDATE users SET balance = balance + ? WHERE tg_user_id = ?", (sell_price, data.user_id))
    elif data.action_type == "equip":
        cur.execute("SELECT max_channels FROM users WHERE tg_user_id = ?", (data.user_id,))
        max_ch = cur.fetchone()[0]
        slot = max(1, min(data.slot, max_ch))
        cur.execute("UPDATE usernames SET is_equipped = 0, channel_slot = 0 WHERE owner_id = ? AND channel_slot = ?", (data.user_id, slot))
        cur.execute("UPDATE usernames SET is_saved = 1, is_equipped = 1, channel_slot = ? WHERE tag = ? AND owner_id = ?", (slot, data.tag, data.user_id))
    elif data.action_type == "unequip":
        cur.execute("UPDATE usernames SET is_equipped = 0, channel_slot = 0 WHERE tag = ? AND owner_id = ?", (data.tag, data.user_id))

    conn.commit(); conn.close()
    return {"status": "ok", "sold_for": sell_price}

CRAFT_COSTS = {
    "Common": 10, "Uncommon": 50, "Rare": 250, "Epic": 1000,
    "Legendary": 5000, "Mythic": 15000, "Luxury": 50000, "Ultra-Mythic": 150000, "Exclusive": 500000
}

@app.post("/api/craft")
def craft_items(data: ReqCraft):
    if len(data.tags) != 5:
        raise HTTPException(400, "Для крафта нужно выбрать ровно 5 предметов одной редкости!")

    conn = sqlite3.connect(DB_NAME); cur = conn.cursor()
    placeholders = ",".join("?" for _ in data.tags)
    cur.execute(f"SELECT tag, item_type, rarity, is_equipped, on_market FROM usernames WHERE owner_id = ? AND tag IN ({placeholders})", [data.user_id, *data.tags])
    rows = cur.fetchall()
    if len(rows) != 5:
        conn.close(); raise HTTPException(400, "Не все выбранные предметы найдены в Хранилище")

    rarities = {r[2] for r in rows}
    if len(rarities) > 1:
        conn.close(); raise HTTPException(400, "Все 5 предметов должны быть одной редкости!")
    if any(r[3] == 1 or r[4] == 1 for r in rows):
        conn.close(); raise HTTPException(400, "Нельзя крафтить предметы, стоящие на канале или на рынке!")

    base_rar = rows[0][2]
    item_type = rows[0][1] or "username"
    rar_idx = next((i for i, r in enumerate(RARITIES) if r["name"] == base_rar), -1)
    if rar_idx < 0 or rar_idx >= len(RARITIES) - 1:
        conn.close(); raise HTTPException(400, "Эту редкость уже нельзя улучшить!")

    cost = CRAFT_COSTS.get(base_rar, 100)
    cur.execute("SELECT balance FROM users WHERE tg_user_id = ?", (data.user_id,))
    bal = cur.fetchone()[0]
    if bal < cost:
        conn.close(); raise HTTPException(400, f"Недостаточно GRAM для крафта (нужно {cost} GRAM)")

    cur.execute(f"DELETE FROM usernames WHERE owner_id = ? AND tag IN ({placeholders})", [data.user_id, *data.tags])
    cur.execute("UPDATE users SET balance = balance - ?, q_crafts = q_crafts + 1, season_xp = season_xp + 15 WHERE tg_user_id = ?", (cost, data.user_id))

    if random.random() < 0.25:
        conn.commit(); conn.close()
        return {"burned": True, "message": "💥 Перегрев плавильни! Все 5 предметов сгорели..."}

    next_rar = RARITIES[rar_idx + 1]
    now = int(time.time())
    if item_type == "number":
        new_tag, inc, sell, reas = generate_phone_number(next_rar["name"], next_rar["inc"], next_rar["sell"])
    else:
        new_tag, _, inc, _, sell, reas = generate_item(cur, "username", f"tier_{min(6, rar_idx+1)}", 1.0)
        inc, sell = next_rar["inc"], next_rar["sell"]

    cur.execute("""
        INSERT OR REPLACE INTO usernames (tag, item_type, owner_id, rarity, income_per_sec, sell_price, reasons, is_equipped, channel_slot, is_saved, on_market, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 1, 0, ?)
    """, (new_tag, item_type, data.user_id, next_rar["name"], inc, sell, reas, now))

    conn.commit(); conn.close()
    return {"burned": False, "item": {"tag": new_tag, "rarity": next_rar["name"], "inc": inc, "sell": sell}}

@app.post("/api/market/create")
def market_create(data: ReqMarketCreate):
    if data.price < 10: raise HTTPException(400, "Минимальная цена — 10 GRAM")
    if data.hours not in [1, 3, 6, 12, 24]: raise HTTPException(400, "Выберите время: 1, 3, 6, 12 или 24 ч.")

    conn = sqlite3.connect(DB_NAME); cur = conn.cursor()
    cur.execute("SELECT item_type, rarity, income_per_sec, reasons, is_equipped, on_market FROM usernames WHERE tag = ? AND owner_id = ? AND is_saved = 1", (data.tag, data.user_id))
    row = cur.fetchone()
    if not row:
        conn.close(); raise HTTPException(400, "Предмет не найден в Хранилище")
    itype, rar, inc, reas, is_eq, on_mkt = row
    if is_eq == 1 or on_mkt == 1:
        conn.close(); raise HTTPException(400, "Снимите предмет с канала перед продажей!")

    now = int(time.time())
    ends_at = now + (data.hours * 3600)
    cur.execute("UPDATE usernames SET on_market = 1 WHERE tag = ? AND owner_id = ?", (data.tag, data.user_id))
    cur.execute("""
        INSERT INTO market_lots (tag, item_type, rarity, income_per_sec, reasons, seller_id, seller_name, is_auction, start_price, current_price, buyout_price, ends_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (data.tag, itype, rar, inc, reas, data.user_id, data.username, data.is_auction, data.price, data.price, data.price * 2.5, ends_at, now))

    conn.commit(); conn.close()
    return {"status": "ok"}

@app.post("/api/market/interact")
def market_interact(data: ReqMarketInteract):
    conn = sqlite3.connect(DB_NAME); cur = conn.cursor()
    now = int(time.time())
    settle_expired_auctions(cur)

    cur.execute("""
        SELECT tag, item_type, rarity, income_per_sec, reasons, seller_id, is_auction,
               current_price, buyout_price, highest_bidder_id, bids_count, ends_at
        FROM market_lots WHERE lot_id = ?
    """, (data.lot_id,))
    lot = cur.fetchone()
    if not lot:
        conn.close(); raise HTTPException(400, "Лот уже завершен или куплен!")

    tag, itype, rar, inc, reas, seller_id, is_auc, cur_price, buyout, prev_bidder_id, bids_cnt, ends_at = lot
    if seller_id == data.user_id:
        conn.close(); raise HTTPException(400, "Нельзя покупать или делать ставку на свой же лот!")

    cur.execute("SELECT balance FROM users WHERE tg_user_id = ?", (data.user_id,))
    my_bal = cur.fetchone()[0]

    if is_auc == 0 or data.act == "buy":
        pay_price = cur_price if is_auc == 0 else buyout
        if my_bal < pay_price:
            conn.close(); raise HTTPException(400, f"Не хватает GRAM (нужно {pay_price:,} GRAM)")

        if prev_bidder_id and prev_bidder_id > 0:
            cur.execute("UPDATE users SET balance = balance + ? WHERE tg_user_id = ?", (cur_price, prev_bidder_id))

        cur.execute("UPDATE users SET balance = balance - ? WHERE tg_user_id = ?", (pay_price, data.user_id))
        if seller_id and seller_id > 0:
            cur.execute("UPDATE users SET balance = balance + ? WHERE tg_user_id = ?", (round(pay_price * 0.95, 2), seller_id))

        cur.execute("""
            INSERT OR REPLACE INTO usernames (tag, item_type, owner_id, rarity, income_per_sec, sell_price, reasons, is_equipped, channel_slot, is_saved, on_market, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 1, 0, ?)
        """, (tag, itype, data.user_id, rar, inc, round(pay_price * 0.7, 0), reas, now))
        cur.execute("DELETE FROM market_lots WHERE lot_id = ?", (data.lot_id,))
        conn.commit(); conn.close()
        return {"status": "bought", "tag": tag}

    new_bid = round(cur_price * 1.10, 0) if bids_cnt > 0 else cur_price
    if my_bal < new_bid:
        conn.close(); raise HTTPException(400, f"Для ставки нужно {new_bid:,} GRAM")

    if prev_bidder_id and prev_bidder_id > 0:
        cur.execute("UPDATE users SET balance = balance + ? WHERE tg_user_id = ?", (cur_price, prev_bidder_id))

    cur.execute("UPDATE users SET balance = balance - ? WHERE tg_user_id = ?", (new_bid, data.user_id))
    new_ends = max(ends_at, now + 60)
    cur.execute("""
        UPDATE market_lots SET current_price = ?, highest_bidder_id = ?, highest_bidder_name = ?,
                               bids_count = bids_count + 1, ends_at = ?
        WHERE lot_id = ?
    """, (new_bid, data.user_id, data.username, new_ends, data.lot_id))

    conn.commit(); conn.close()
    return {"status": "bid_placed", "new_price": new_bid}

WHEEL_PRIZES = [
    {"idx": 0, "title": "1,000 GRAM",       "type": "coins", "val": 1000,  "w": 350},
    {"idx": 1, "title": "3,500 GRAM",       "type": "coins", "val": 3500,  "w": 250},
    {"idx": 2, "title": "🍀 Удача x2 (1ч)", "type": "luck",  "val": 3600,  "w": 120},
    {"idx": 3, "title": "10,000 GRAM",      "type": "coins", "val": 10000, "w": 100},
    {"idx": 4, "title": "📦 Редкий @тег",   "type": "tag",   "val": "Rare","w": 90},
    {"idx": 5, "title": "25,000 GRAM",      "type": "coins", "val": 25000, "w": 50},
    {"idx": 6, "title": "📞 Номер +888",    "type": "num",   "val": "Epic","w": 30},
    {"idx": 7, "title": "💎 ДЖЕКПОТ 100K",  "type": "coins", "val": 100000,"w": 10}
]

@app.post("/api/wheel_spin")
def spin_wheel(data: ReqSimple):
    conn = sqlite3.connect(DB_NAME); cur = conn.cursor()
    now = int(time.time())
    cur.execute("SELECT last_wheel FROM users WHERE tg_user_id = ?", (data.user_id,))
    lw = cur.fetchone()[0]
    if (now - lw) < 1800:
        conn.close(); raise HTTPException(400, "Колесо перезаряжается (раз в 30 мин)!")

    tot = sum(p["w"] for p in WHEEL_PRIZES)
    r = random.random() * tot
    picked = WHEEL_PRIZES[0]
    for p in WHEEL_PRIZES:
        if r < p["w"]: picked = p; break
        r -= p["w"]

    if picked["type"] == "coins":
        cur.execute("UPDATE users SET balance = balance + ?, last_wheel = ?, season_xp = season_xp + 10 WHERE tg_user_id = ?", (picked["val"], now, data.user_id))
    elif picked["type"] == "luck":
        cur.execute("UPDATE users SET luck_multi = 2.0, luck_until = ?, last_wheel = ? WHERE tg_user_id = ?", (now + picked["val"], now, data.user_id))
    elif picked["type"] == "tag":
        t = f"@wheel_vip{random.randint(10,99)}"
        cur.execute("INSERT OR IGNORE INTO usernames (tag, item_type, owner_id, rarity, income_per_sec, sell_price, reasons, is_saved, created_at) VALUES (?,?,?,?,?,?,?,1,?)",
                    (t, "username", data.user_id, "Rare", 15.0, 750.0, "🎡 Приз Колеса Фортуны", now))
        cur.execute("UPDATE users SET last_wheel = ? WHERE tg_user_id = ?", (now, data.user_id))
    elif picked["type"] == "num":
        t, inc, sell, reas = generate_phone_number("Epic", 50.0, 2500.0)
        cur.execute("INSERT OR IGNORE INTO usernames (tag, item_type, owner_id, rarity, income_per_sec, sell_price, reasons, is_saved, created_at) VALUES (?,?,?,?,?,?,?,1,?)",
                    (t, "number", data.user_id, "Epic", inc, sell, reas, now))
        cur.execute("UPDATE users SET last_wheel = ? WHERE tg_user_id = ?", (now, data.user_id))

    conn.commit(); conn.close()
    return {"prize_idx": picked["idx"], "title": picked["title"]}

DAILY_REWARDS = [1000, 3000, 5000, 10000, 15000, 25000, 50000]

@app.post("/api/daily_gift")
def claim_daily(data: ReqSimple):
    conn = sqlite3.connect(DB_NAME); cur = conn.cursor()
    now = int(time.time())
    cur.execute("SELECT daily_streak, last_daily FROM users WHERE tg_user_id = ?", (data.user_id,))
    streak, last_d = cur.fetchone()
    if (now - last_d) < 86400:
        conn.close(); raise HTTPException(400, "Подарок дня уже получен сегодня!")
    if (now - last_d) > 172800:
        streak = 0
    reward = DAILY_REWARDS[streak % 7]
    new_streak = (streak % 7) + 1
    cur.execute("UPDATE users SET balance = balance + ?, daily_streak = ?, last_daily = ?, season_xp = season_xp + 25 WHERE tg_user_id = ?", (reward, new_streak, now, data.user_id))
    conn.commit(); conn.close()
    return {"reward": reward, "day": new_streak}

@app.post("/api/claim_reward")
def claim_quest_or_pass(data: ReqSimple):
    conn = sqlite3.connect(DB_NAME); cur = conn.cursor()
    cur.execute("SELECT q_spins, q_rare, q_crafts, q_claimed, season_xp, season_claimed, ach_stats, ach_claimed FROM users WHERE tg_user_id = ?", (data.user_id,))
    qs, qr, qc, q_cl_raw, s_xp, s_cl_raw, a_st_raw, a_cl_raw = cur.fetchone()
    q_cl = json.loads(q_cl_raw or "[]")
    s_cl = json.loads(s_cl_raw or "[]")
    a_st = json.loads(a_st_raw or "{}")
    a_cl = json.loads(a_cl_raw or "[]")

    key = data.key
    reward = 0
    add_s_xp = 0

    if key == "q1" and qs >= 15 and "q1" not in q_cl:
        reward = 3000; add_s_xp = 50; q_cl.append("q1")
    elif key == "q2" and qr >= 5 and "q2" not in q_cl:
        reward = 7500; add_s_xp = 50; q_cl.append("q2")
    elif key == "q3" and qc >= 1 and "q3" not in q_cl:
        reward = 5000; add_s_xp = 50; q_cl.append("q3")
    elif key == "q_all" and all(x in q_cl for x in ["q1", "q2", "q3"]) and "q_all" not in q_cl:
        reward = 25000; add_s_xp = 100; q_cl.append("q_all")
    elif key.startswith("pass_"):
        lvl = int(key.split("_")[1])
        if s_xp >= lvl * 50 and key not in s_cl:
            reward = lvl * 1500
            s_cl.append(key)
    elif key.startswith("ach_"):
        parts = key.split("_")
        rar = parts[1]
        target = int(parts[2])
        if a_st.get(rar, 0) >= target and key not in a_cl:
            reward = target * 2500
            a_cl.append(key)
    else:
        conn.close(); raise HTTPException(400, "Условия ещё не выполнены или награда уже забрана")

    cur.execute("""
        UPDATE users SET balance = balance + ?, season_xp = season_xp + ?,
                         q_claimed = ?, season_claimed = ?, ach_claimed = ?
        WHERE tg_user_id = ?
    """, (reward, add_s_xp, json.dumps(q_cl), json.dumps(s_cl), json.dumps(a_cl), data.user_id))
    conn.commit(); conn.close()
    return {"reward": reward}

@app.post("/api/upgrade_mgr")
def upgrade_manager(data: ReqSimple):
    conn = sqlite3.connect(DB_NAME); cur = conn.cursor()
    cur.execute("SELECT balance, smm_lvl, buyer_lvl FROM users WHERE tg_user_id = ?", (data.user_id,))
    u = cur.fetchone()
    if not u:
        conn.close(); raise HTTPException(404, "User not found")
    bal, smm, buyer = u

    if data.key == "smm":
        cost = smm * 250.0
        if bal < cost:
            conn.close(); raise HTTPException(400, "Не хватает GRAM для прокачки СММщика")
        cur.execute("UPDATE users SET balance = balance - ?, smm_lvl = smm_lvl + 1 WHERE tg_user_id = ?", (cost, data.user_id))
    else:
        cost = (buyer + 1) * 1000.0
        if bal < cost:
            conn.close(); raise HTTPException(400, "Не хватает GRAM для прокачки Байера")
        cur.execute("UPDATE users SET balance = balance - ?, buyer_lvl = buyer_lvl + 1 WHERE tg_user_id = ?", (cost, data.user_id))

    conn.commit(); conn.close()
    return {"status": "ok"}

@app.post("/api/clan_action")
def clan_action(data: ReqClan):
    conn = sqlite3.connect(DB_NAME); cur = conn.cursor()
    if data.donate_amount > 0:
        cur.execute("SELECT balance FROM users WHERE tg_user_id = ?", (data.user_id,))
        bal = cur.fetchone()[0]
        if bal < data.donate_amount:
            conn.close(); raise HTTPException(400, "Недостаточно GRAM для взноса в казну")
        cur.execute("UPDATE users SET balance = balance - ? WHERE tg_user_id = ?", (data.donate_amount, data.user_id))
        cur.execute("UPDATE clans SET treasury = treasury + ? WHERE clan_id = ?", (data.donate_amount, data.clan_id))
    else:
        cur.execute("UPDATE users SET clan_id = ? WHERE tg_user_id = ?", (data.clan_id, data.user_id))
    conn.commit(); conn.close()
    return {"status": "ok"}

@app.get("/api/prepare_share")
async def prepare_share(user_id: int, mode: str = "ref"):
    param = f"ref_{user_id}" if mode == "ref" else f"trade_{user_id}"
    bot_link = f"https://t.me/MintTagsBot?startapp={param}"
    html_text = (
        f"👑 Забирай элитные <b>@username</b> и анонимные номера <b>+888</b> первее всех в "
        f"<a href=\"{bot_link}\">MintTags: Media Empire</a>!\n\n"
        f"🎁 Переходи по ссылке и забирай стартовый бонус <b>2,500 GRAM</b>!"
    )
    try:
        res = await bot.save_prepared_inline_message(
            user_id=user_id,
            result=InlineQueryResultArticle(
                id=f"share_{user_id}_{int(time.time())}",
                title="Пригласить друга в MintTags",
                input_message_content=InputTextMessageContent(
                    message_text=html_text,
                    parse_mode="HTML",
                    disable_web_page_preview=False
                ),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="🚀 Играть в MintTags", url=bot_link)
                ]])
            ),
            allow_user_chats=True,
            allow_group_chats=True,
            allow_channel_chats=True
        )
        return {"prepared_id": res.id}
    except Exception:
        return {"prepared_id": None}

PRICES = {
    "vip_pass":     {"title": "👑 VIP Game Pass (30 дней)", "price": 89},
    "luck_x2_1h":   {"title": "🍀 Буст Удачи x2 (1 час)", "price": 19},
    "luck_x3_2h":   {"title": "🔥 Мега Удача x3 (2 часа)", "price": 39},
    "hold_plus_50": {"title": "💼 +50 слотов в Хранилище", "price": 45},
    "channel_slot": {"title": "📢 Новый слот Канала", "price": 59},
    "coins_50k":    {"title": "🪙 50,000 GRAM", "price": 15},
    "coins_250k":   {"title": "💰 250,000 GRAM", "price": 49},
    "num_888_box":  {"title": "📞 Элитный Бокс +888 (Legendary+)", "price": 75}
}

@app.get("/api/invoice")
async def get_invoice(payload: str):
    product = PRICES.get(payload)
    if not product: raise HTTPException(400, "Товар не найден")
    link = await bot.create_invoice_link(
        title=product["title"], description="Покупка в MintTags: Media Empire",
        payload=payload, currency="XTR",
        prices=[LabeledPrice(label=product["title"], amount=product["price"])]
    )
    return {"invoice_link": link}

@app.post("/api/activate_donate")
def activate_donate(data: ReqSimple):
    conn = sqlite3.connect(DB_NAME); cur = conn.cursor()
    now = int(time.time()); p = data.key
    if p == "vip_pass":
        cur.execute("UPDATE users SET vip_until = ?, max_hold = max_hold + 50, balance = balance + 25000 WHERE tg_user_id = ?", (now + 2592000, data.user_id))
    elif p == "luck_x2_1h":
        cur.execute("UPDATE users SET luck_multi = 2.0, luck_until = ? WHERE tg_user_id = ?", (now + 3600, data.user_id))
    elif p == "luck_x3_2h":
        cur.execute("UPDATE users SET luck_multi = 3.0, luck_until = ? WHERE tg_user_id = ?", (now + 7200, data.user_id))
    elif p == "hold_plus_50":
        cur.execute("UPDATE users SET max_hold = max_hold + 50 WHERE tg_user_id = ?", (data.user_id,))
    elif p == "channel_slot":
        cur.execute("UPDATE users SET max_channels = MIN(15, max_channels + 1) WHERE tg_user_id = ?", (data.user_id,))
    elif p == "coins_50k":
        cur.execute("UPDATE users SET balance = balance + 50000 WHERE tg_user_id = ?", (data.user_id,))
    elif p == "coins_250k":
        cur.execute("UPDATE users SET balance = balance + 250000 WHERE tg_user_id = ?", (data.user_id,))
    elif p == "num_888_box":
        t, inc, sell, reas = generate_phone_number("Legendary", 200.0, 10000.0)
        cur.execute("INSERT OR IGNORE INTO usernames (tag, item_type, owner_id, rarity, income_per_sec, sell_price, reasons, is_saved, created_at) VALUES (?,?,?,?,?,?,?,1,?)",
                    (t, "number", data.user_id, "Legendary", inc, sell, reas, now))
    conn.commit(); conn.close()
    return {"status": "ok"}
