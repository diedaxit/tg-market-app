import sqlite3
import random
import time
import os
import json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from aiogram.types import (
    LabeledPrice, InlineQueryResultArticle, InputTextMessageContent,
    InlineKeyboardMarkup, InlineKeyboardButton
)
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
            balance REAL DEFAULT 5000.0,
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
            total_spins INTEGER DEFAULT 0,
            pity_100 INTEGER DEFAULT 0,
            pity_500 INTEGER DEFAULT 0,
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
            sim_multi REAL DEFAULT 1.0,
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
            name TEXT UNIQUE,
            owner_id INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            treasury REAL DEFAULT 0.0,
            members_count INTEGER DEFAULT 0,
            max_members INTEGER DEFAULT 100,
            created_at INTEGER DEFAULT 0
        )
    """)
    conn.commit()

    # Авто-миграции колонок
    cur.execute("PRAGMA table_info(users)")
    u_cols = [c[1] for c in cur.fetchall()]
    for col, ctype in [
        ("season_xp", "INTEGER DEFAULT 0"), ("season_claimed", "TEXT DEFAULT '[]'"),
        ("vip_until", "INTEGER DEFAULT 0"), ("max_hold", "INTEGER DEFAULT 100"),
        ("max_channels", "INTEGER DEFAULT 2"), ("ref_by", "INTEGER DEFAULT NULL"),
        ("refs_count", "INTEGER DEFAULT 0"), ("smm_lvl", "INTEGER DEFAULT 1"),
        ("buyer_lvl", "INTEGER DEFAULT 0"), ("clan_id", "TEXT DEFAULT NULL"),
        ("total_spins", "INTEGER DEFAULT 0"), ("pity_100", "INTEGER DEFAULT 0"),
        ("pity_500", "INTEGER DEFAULT 0"), ("last_wheel", "INTEGER DEFAULT 0"),
        ("daily_streak", "INTEGER DEFAULT 0"), ("last_daily", "INTEGER DEFAULT 0"),
        ("q_spins", "INTEGER DEFAULT 0"), ("q_rare", "INTEGER DEFAULT 0"),
        ("q_crafts", "INTEGER DEFAULT 0"), ("q_claimed", "TEXT DEFAULT '[]'"),
        ("ach_stats", "TEXT DEFAULT '{}'"), ("ach_claimed", "TEXT DEFAULT '[]'")
    ]:
        if col not in u_cols:
            try: cur.execute(f"ALTER TABLE users ADD COLUMN {col} {ctype}")
            except Exception: pass

    cur.execute("PRAGMA table_info(usernames)")
    t_cols = [c[1] for c in cur.fetchall()]
    for col, ctype in [
        ("item_type", "TEXT DEFAULT 'username'"), ("sim_multi", "REAL DEFAULT 1.0"),
        ("is_equipped", "INTEGER DEFAULT 0"), ("channel_slot", "INTEGER DEFAULT 0"),
        ("is_saved", "INTEGER DEFAULT 1"), ("on_market", "INTEGER DEFAULT 0")
    ]:
        if col not in t_cols:
            try: cur.execute(f"ALTER TABLE usernames ADD COLUMN {col} {ctype}")
            except Exception: pass

    cur.execute("PRAGMA table_info(clans)")
    c_cols = [c[1] for c in cur.fetchall()]
    for col, ctype in [
        ("owner_id", "INTEGER DEFAULT 0"), ("level", "INTEGER DEFAULT 1"),
        ("max_members", "INTEGER DEFAULT 100"), ("created_at", "INTEGER DEFAULT 0")
    ]:
        if col not in c_cols:
            try: cur.execute(f"ALTER TABLE clans ADD COLUMN {col} {ctype}")
            except Exception: pass

    # Удаляем старые шаблонные кланы и создаем единственный официальный клан MintGeneral (лимит 1000 мест)
    cur.execute("DELETE FROM clans WHERE clan_id IN ('ton_whales', 'durov_syndicate', 'emerald_cartel')")
    cur.execute("""
        INSERT OR IGNORE INTO clans (clan_id, name, owner_id, level, treasury, members_count, max_members, created_at)
        VALUES ('mint_general', 'MintGeneral', 0, 5, 1000000.0, 1, 1000, ?)
    """, (int(time.time()),))

    cur.execute("SELECT COUNT(*) FROM market_lots")
    if cur.fetchone()[0] == 0:
        now = int(time.time())
        seed_lots = [
            ("+888 0777", "number", "Divine", 350000.0, "👑 Короткая серия 0XXX|🎰 Три семерки 777|📡 SIM-Шлюз ×15.0 к каналам", 0, "Fragment_DAO", 1, 1200000.0, 1200000.0, 3500000.0, 6, now + 14400),
            ("@durov", "username", "Exclusive", 25000.0, "💎 Основатель Telegram|🚫 Без цифр и знаков", 0, "Whale_TON", 1, 450000.0, 450000.0, 950000.0, 9, now + 10800),
            ("+888 8888 888", "number", "Exclusive", 120000.0, "🔥 Моно-репит 8888888|📡 SIM-Шлюз ×8.0 к каналам", 0, "CryptoBoss", 0, 650000.0, 650000.0, 650000.0, 0, now + 86400)
        ]
        for st in seed_lots:
            cur.execute("""
                INSERT INTO market_lots (tag, item_type, rarity, income_per_sec, reasons, seller_id, seller_name, is_auction, start_price, current_price, buyout_price, bids_count, ends_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (*st, now))

    conn.commit()
    conn.close()

init_db()

# ==========================================
# ЭКОНОМИКА РЕДКОСТЕЙ, ТЕГОВ И +888 НОМЕРОВ
# ==========================================
RARITIES = [
    {"name": "Common",       "ru": "Обычный",      "w": 750000, "inc": 2,      "xp": 5,     "sell": 60,      "sim": 1.25},
    {"name": "Uncommon",     "ru": "Необычный",    "w": 175000, "inc": 8,      "xp": 15,    "sell": 280,     "sim": 1.50},
    {"name": "Rare",         "ru": "Редкий",       "w": 55000,  "inc": 25,     "xp": 40,    "sell": 850,     "sim": 2.00},
    {"name": "Epic",         "ru": "Эпический",    "w": 15000,  "inc": 90,     "xp": 100,   "sell": 3000,    "sim": 2.75},
    {"name": "Legendary",    "ru": "Легендарный",  "w": 3500,   "inc": 350,    "xp": 300,   "sell": 12000,   "sim": 4.00},
    {"name": "Mythic",       "ru": "Мифический",   "w": 1000,   "inc": 900,    "xp": 800,   "sell": 35000,   "sim": 5.50},
    {"name": "Luxury",       "ru": "Роскошный",    "w": 300,    "inc": 2800,   "xp": 1500,  "sell": 95000,   "sim": 7.50},
    {"name": "Ultra-Mythic", "ru": "Ультра-Мифик", "w": 90,     "inc": 8500,   "xp": 2500,  "sell": 280000,  "sim": 10.0},
    {"name": "Exclusive",    "ru": "Эксклюзивный", "w": 25,     "inc": 35000,  "xp": 5000,  "sell": 950000,  "sim": 12.5},
    {"name": "Divine",       "ru": "Божественный", "w": 5,      "inc": 150000, "xp": 15000, "sell": 4000000, "sim": 15.0}
]

# Цены тиров: для @username базовая 100 G, для +888 Номеров базовая 25,000 G (множитель x250!)
SPIN_TIERS = {
    "tier_0": {"min_idx": 0, "u_cost": 100,    "n_cost": 25000,    "title": "Обычный+"},
    "tier_1": {"min_idx": 1, "u_cost": 300,    "n_cost": 75000,    "title": "Необычный+"},
    "tier_2": {"min_idx": 2, "u_cost": 1000,   "n_cost": 250000,   "title": "Редкий+"},
    "tier_3": {"min_idx": 3, "u_cost": 3500,   "n_cost": 850000,   "title": "Эпический+"},
    "tier_4": {"min_idx": 4, "u_cost": 12000,  "n_cost": 2500000,  "title": "Легендарный+"},
    "tier_5": {"min_idx": 5, "u_cost": 35000,  "n_cost": 7500000,  "title": "Мифический+"},
    "tier_6": {"min_idx": 6, "u_cost": 100000, "n_cost": 20000000, "title": "Luxury+"}
}

WORD_MEANINGS = {
    "x": "Символ «X» (2 симв.)", "v": "Знак Победы «V»", "ai": "Искусственный Интеллект", "go": "Глагол «Вперед»",
    "durov": "Павел Дуров (Основатель)", "telegram": "Главный бренд Telegram", "ton": "Блокчейн TON",
    "notcoin": "Токен Notcoin", "redo": "Символ Resistance Dog", "vk": "Короткий бренд",
    "cat": "Слово «Кот» (3 буквы)", "dog": "Слово «Пес» (3 буквы)", "nft": "Крипто-токен NFT", "god": "Слово «Бог»", "top": "Статус «Топ»",
    "dubai": "Столица роскоши Дубай", "money": "Слово «Деньги»", "rich": "Статус «Богатый»", "gold": "Чистое «Золото»", "king": "Титул «Король»",
    "star": "Слово «Звезда» (4 буквы)", "moon": "Крипто-мем «На Луну»", "litvin": "Блогер Михаил Литвин", "mellstroy": "Стример Мелстрой",
    "mrbeast": "Топ-1 креатор MrBeast", "tiger": "Слово «Тигр» (5 букв)", "ghost": "Слово «Призрак»", "alpha": "Статус «Альфа»",
    "whale": "Крипто-кит", "wylsa": "Техноблогер Wylsacom", "subo": "Блогер Субо", "buster": "Стример Бустер", "hasbulla": "Хасбик"
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

def generate_phone_number(rarity_obj: dict):
    """Генерация NFT-номеров +888 с высокой доходностью и SIM-множителем"""
    rarity_name = rarity_obj["name"]
    sim_m = rarity_obj["sim"]
    inc = round(rarity_obj["inc"] * 25.0, 0)
    sell = round(rarity_obj["sell"] * 220.0, 0)

    if rarity_name == "Divine":
        d = random.choice(["0001", "0007", "0777", "0888", "0999", "0000"])
        tag = f"+888 {d}"
        reasons = [f"👑 Короткий пул +888 0XXX", f"📡 SIM-Шлюз: ×{sim_m} ко всем каналам", "💎 Высшая ценность Fragment"]
    elif rarity_name == "Exclusive":
        d = random.choice(["7", "8", "9", "0", "1"])
        tag = f"+888 {d*4} {d*3}"
        reasons = [f"💎 Моно-репит из одних «{d}»", f"📡 SIM-Шлюз: ×{sim_m} ко всем каналам", "🔥 Идеальный паттерн"]
    elif rarity_name == "Ultra-Mythic":
        d1, d2 = random.choice(["7", "8", "9"]), random.choice(["0", "1", "5"])
        tag = f"+888 {d1*4} {d2*3}"
        reasons = [f"🔥 Квадра «{d1*4}» + Триплет «{d2*3}»", f"📡 SIM-Шлюз: ×{sim_m} к каналам"]
    elif rarity_name == "Luxury":
        d = random.choice(["777", "888", "999", "000"])
        tag = f"+888 0{d} {d}"
        reasons = [f"💰 Двойной блок «{d}»", f"📡 SIM-Шлюз: ×{sim_m} к каналам"]
    elif rarity_name == "Mythic":
        d = random.choice(["777", "888", "999"])
        tag = f"+888 {random.randint(10, 99)}00 {d}"
        reasons = [f"🎰 Триплет «{d}» + Сотня", f"📡 SIM-Шлюз: ×{sim_m} к каналам"]
    elif rarity_name == "Legendary":
        tag = random.choice(["+888 1234 567", "+888 7654 321", f"+888 {random.randint(10,99)}77 700"])
        reasons = ["⭐ Красивая лесенка / 777", f"📡 SIM-Шлюз: ×{sim_m} к каналам"]
    elif rarity_name == "Epic":
        a, b = random.randint(1, 9), random.randint(1, 9)
        tag = f"+888 {a}{a}{b}{b} {random.randint(100,999)}"
        reasons = [f"✅ Парный дубль «{a}{a}{b}{b}»", f"📡 SIM-Шлюз: ×{sim_m} к каналам"]
    elif rarity_name == "Rare":
        a = random.randint(10, 99)
        tag = f"+888 {a}{a} {random.randint(100,999)}"
        reasons = [f"✅ Зеркальная пара «{a}{a}»", f"📡 SIM-Шлюз: ×{sim_m} к каналам"]
    elif rarity_name == "Uncommon":
        tag = f"+888 {random.randint(100,999)}0 {random.randint(10,99)}0"
        reasons = ["✅ Круглые окончания 0", f"📡 SIM-Шлюз: ×{sim_m} к каналам"]
    else:
        tag = f"+888 {random.randint(1000,9999)} {random.randint(100,999)}"
        reasons = ["Анонимный NFT-номер Telegram", f"📡 SIM-Шлюз: ×{sim_m} к каналам"]

    return tag, inc, sell, sim_m, "|".join(reasons)

def roll_single_candidate(cur, item_type: str, tier_key: str, luck: float):
    global RECENT_ROOTS
    min_idx = SPIN_TIERS.get(tier_key, SPIN_TIERS["tier_0"])["min_idx"]

    pool = []
    total_w = 0
    for i, r in enumerate(RARITIES):
        if i >= min_idx:
            w = int(r["w"] * (luck if i >= 3 else 1.0))
            pool.append({"idx": i, "data": r, "w": w})
            total_w += w

    rnd = random.random() * total_w
    picked = pool[-1]["data"]
    rar_idx = pool[-1]["idx"]
    for p in pool:
        if rnd < p["w"]:
            picked = p["data"]
            rar_idx = p["idx"]
            break
        rnd -= p["w"]

    rarity = picked["name"]

    if item_type == "number":
        tag, inc, sell, sim_m, reas = generate_phone_number(picked)
        return {"tag": tag, "rarity": rarity, "rar_idx": rar_idx, "inc": inc, "xp": picked["xp"] * 3, "sell": sell, "sim_multi": sim_m, "reasons": reas}

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
            rarity = "Epic"; picked = RARITIES[3]; rar_idx = 3
            word = random.choice(WORDS["Epic"])

    if rarity in ["Divine", "Exclusive", "Ultra-Mythic", "Luxury", "Mythic", "Legendary"]:
        tag = f"@{word}"
        meaning = WORD_MEANINGS.get(word, f"Премиум тег «{word.upper()}»")
        reasons = [f"💡 {meaning}", "🚫 Без цифр и символов _", f"📏 {len(word)} букв (Высокая ценность)"]
    elif rarity == "Epic":
        tag = f"@{word}{random.randint(1, 19)}"
        reasons = [f"💡 Корень «{word}»", "✅ Короткий индекс без _"]
    elif rarity == "Rare":
        tag = f"@{word}_{random.choice(['vip', 'ton', 'pro', 'hq'])}"
        reasons = ["✅ Статусная приставка", "📏 Узнаваемый корень"]
    elif rarity == "Uncommon":
        base = generate_live_nickname()
        word = base
        tag = f"@{base}{random.choice(['', str(random.randint(10, 99))])}"
        reasons = ["✅ Живой читаемый никнейм", "📏 Короткая форма"]
    else:
        base = generate_live_nickname()
        word = base
        tag = f"@{base}{random.randint(100, 9999)}"
        reasons = ["Пользовательский никнейм", "Базовый числовой индекс"]

    if word:
        RECENT_ROOTS.append(word)
        if len(RECENT_ROOTS) > 6: RECENT_ROOTS.pop(0)

    return {"tag": tag, "rarity": rarity, "rar_idx": rar_idx, "inc": picked["inc"], "xp": picked["xp"], "sell": picked["sell"], "sim_multi": 1.0, "reasons": "|".join(reasons)}

def generate_item_with_pity_choice(cur, item_type: str, tier_key: str, luck: float, choice_count: int = 1):
    """Если сработал гарант x5 (100 спинов) или x50 (500 спинов), генерирует N вариантов и выбирает САМЫЙ ДОРОГОЙ"""
    best = None
    for _ in range(max(1, choice_count)):
        cand = roll_single_candidate(cur, item_type, tier_key, luck)
        if best is None or cand["sell"] > best["sell"]:
            best = cand
    return best

def get_clan_bonus_multiplier(cur, clan_id: str) -> float:
    if not clan_id:
        return 1.0
    cur.execute("SELECT level, members_count FROM clans WHERE clan_id = ?", (clan_id,))
    row = cur.fetchone()
    if not row:
        return 1.0
    lvl, mems = row
    # База +5%, +2% за каждый уровень казны клана, +0.5% за каждого участника (до +150%)
    bonus_pct = 5.0 + (lvl * 2.0) + min(50.0, mems * 0.5)
    return 1.0 + (bonus_pct / 100.0)

def settle_expired_auctions(cur):
    now = int(time.time())
    cur.execute("SELECT lot_id, tag, item_type, rarity, income_per_sec, reasons, seller_id, current_price, highest_bidder_id FROM market_lots WHERE ends_at <= ?", (now,))
    for lot in cur.fetchall():
        lid, tag, itype, rar, inc, reas, seller_id, price, winner_id = lot
        sim_m = next((r["sim"] for r in RARITIES if r["name"] == rar), 1.25) if itype == "number" else 1.0
        if winner_id:
            cur.execute("""
                INSERT OR REPLACE INTO usernames (tag, item_type, owner_id, rarity, income_per_sec, sell_price, sim_multi, reasons, is_equipped, channel_slot, is_saved, on_market, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 1, 0, ?)
            """, (tag, itype, winner_id, rar, inc, round(price * 0.75, 0), sim_m, reas, now))
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

    # Считаем доход каналов (слоты 1..15) и глобальный множитель SIM-Шлюза +888 (слот 99)
    cur.execute("SELECT SUM(income_per_sec) FROM usernames WHERE owner_id = ? AND is_equipped = 1 AND channel_slot < 90 AND is_saved = 1 AND on_market = 0", (user_id,))
    ch_inc = cur.fetchone()[0] or 0.0

    cur.execute("SELECT MAX(sim_multi), SUM(income_per_sec) FROM usernames WHERE owner_id = ? AND is_equipped = 1 AND channel_slot = 99 AND is_saved = 1 AND on_market = 0", (user_id,))
    sim_row = cur.fetchone()
    sim_mult = sim_row[0] or 1.0
    sim_direct_inc = sim_row[1] or 0.0

    base_total = ((ch_inc + (smm * 5.0) + (buyer * 25.0)) * sim_mult if ch_inc > 0 else 0.0) + sim_direct_inc
    if vip_until > now:
        base_total *= 2.0
    if clan_id:
        base_total *= get_clan_bonus_multiplier(cur, clan_id)

    earned = base_total * elapsed
    cur.execute("UPDATE users SET balance = balance + ?, last_claim = ? WHERE tg_user_id = ?", (earned, now, user_id))
    return earned

# ==========================================
# МОДЕЛИ ЗАПРОСОВ
# ==========================================
class ReqLogin(BaseModel): user_id: int; username: str = "Player"; ref_by: str = ""
class ReqMint(BaseModel): user_id: int; item_type: str = "username"; tier: str = "tier_0"; spin_count: int = 1; auto_save_mythic: bool = False
class ReqAction(BaseModel): user_id: int; tag: str; action_type: str; slot: int = 1
class ReqCraft(BaseModel): user_id: int; tags: list[str]
class ReqMarketCreate(BaseModel): user_id: int; username: str; tag: str; is_auction: int; price: float; hours: int = 3
class ReqMarketInteract(BaseModel): user_id: int; username: str; lot_id: int; act: str
class ReqSimple(BaseModel): user_id: int; key: str = ""
class ReqClanCreate(BaseModel): user_id: int; name: str
class ReqClanAction(BaseModel): user_id: int; clan_id: str = ""; amount: float = 0.0

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
                        rew = 2500.0 if nc == 1 else (5000.0 if nc == 2 else (15000.0 if nc == 5 else (1000000.0 if nc == 20 else 2500.0)))
                        cur.execute("UPDATE users SET refs_count = ?, balance = balance + ? WHERE tg_user_id = ?", (nc, rew, ref_id))
            except Exception: pass
        cur.execute("INSERT INTO users (tg_user_id, username, balance, level, xp, ref_by, last_claim, created_at) VALUES (?, ?, 5000.0, 1, 0, ?, ?, ?)",
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
               total_spins, pity_100, pity_500, last_wheel, daily_streak, last_daily,
               q_spins, q_rare, q_crafts, q_claimed, ach_stats, ach_claimed
        FROM users WHERE tg_user_id = ?
    """, (uid,))
    u = cur.fetchone()
    if not u:
        conn.close(); raise HTTPException(404, "User not found")

    (mem_num, bal, lvl, xp, s_xp, s_cl, smm, buyer, luck_m, luck_u, vip_u, max_h, max_ch,
     refs, clan_id, tot_spins, p100, p500, l_wheel, d_streak, l_daily, qs, qr, qc, q_cl, a_st, a_cl) = u

    cur.execute("""
        SELECT tag, item_type, rarity, income_per_sec, sell_price, sim_multi, reasons, is_equipped, channel_slot
        FROM usernames WHERE owner_id = ? AND is_saved = 1 AND on_market = 0
        ORDER BY sell_price DESC
    """, (uid,))
    tags = [{
        "tag": r[0], "type": r[1] or "username", "rarity": r[2], "inc": r[3],
        "sell": r[4], "sim": r[5] or 1.0, "reasons": r[6].split("|") if r[6] else [], "eq": r[7], "slot": r[8]
    } for r in cur.fetchall()]

    cur.execute("SELECT COUNT(*) + 1 FROM users WHERE balance > ?", (bal,))
    my_rank = cur.fetchone()[0]

    cur.execute("SELECT username, balance, level FROM users ORDER BY balance DESC LIMIT 20")
    leaders = [{"username": r[0] or "Магнат", "balance": round(r[1], 0), "level": r[2]} for r in cur.fetchall()]

    cur.execute("SELECT clan_id, name, owner_id, level, treasury, members_count, max_members FROM clans ORDER BY level DESC, treasury DESC")
    clans = []
    for r in cur.fetchall():
        bonus_pct = round(5.0 + (r[3] * 2.0) + min(50.0, r[5] * 0.5), 1)
        clans.append({
            "id": r[0], "name": r[1], "owner_id": r[2], "level": r[3],
            "treasury": round(r[4], 0), "members": r[5], "max_members": r[6], "bonus": bonus_pct
        })

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
        "clan_id": clan_id, "total_spins": tot_spins, "pity_100": p100, "pity_500": p500,
        "wheel_wait": max(0, (l_wheel + 1800) - now),
        "daily_streak": d_streak, "can_daily": (now - l_daily) >= 86400,
        "quests": {"spins": qs, "rare": qr, "crafts": qc, "claimed": json.loads(q_cl or "[]")},
        "ach": {"stats": json.loads(a_st or "{}"), "claimed": json.loads(a_cl or "[]")},
        "my_rank": my_rank, "leaders": leaders, "clans": clans, "tags": tags, "market": market
    }

def execute_spins_internal(cur, user_id: int, item_type: str, tier: str, count: int, cost: float, auto_save_mythic: bool = False):
    now = int(time.time())
    cur.execute("""
        SELECT balance, level, xp, season_xp, luck_multi, luck_until, vip_until,
               total_spins, pity_100, pity_500, q_spins, q_rare, ach_stats, max_hold
        FROM users WHERE tg_user_id = ?
    """, (user_id,))
    u = cur.fetchone()
    if not u: raise HTTPException(404, "User not found")
    (bal, lvl, xp, s_xp, luck_m, luck_u, vip_u, tot_s, p100, p500, qs, qr, ach_raw, max_h) = u

    if bal < cost:
        raise HTTPException(400, f"Не хватает на ставку: нужно {int(cost):,} GRAM")

    cur.execute("SELECT COUNT(*) FROM usernames WHERE owner_id = ? AND is_saved = 1 AND on_market = 0", (user_id,))
    cur_hold_cnt = cur.fetchone()[0]

    is_vip = vip_u > now
    base_luck = (luck_m if luck_u > now else 1.0) * (1.5 if is_vip else 1.0)
    ach_stats = json.loads(ach_raw or "{}")

    drops = []
    added_xp = 0
    for _ in range(count):
        tot_s += 1; p100 += 1; p500 += 1; qs += 1; s_xp += 2

        # Гарант x50 (выбор лучшего из 50 на каждом 500-м броске) и Гарант x5 (лучший из 5 на каждом 100-м броске)
        choice_pool = 1
        pity_triggered = None
        if p500 >= 500:
            choice_pool = 50
            p500 = 0
            p100 = 0
            pity_triggered = "x50 ULTRA PITY (Лучший из 50!)"
        elif p100 >= 100:
            choice_pool = 5
            p100 = 0
            pity_triggered = "x5 LUCKY PITY (Лучший из 5!)"

        for _ in range(10):
            cand = generate_item_with_pity_choice(cur, item_type, tier, base_luck, choice_pool)
            cur.execute("SELECT tag FROM usernames WHERE tag = ?", (cand["tag"],))
            if not cur.fetchone():
                break
        else:
            fallback_tag = f"+888 {random.randint(1000,9999)} {random.randint(100,999)}" if item_type == "number" else f"@{generate_live_nickname()}{random.randint(100,999)}"
            cand = {"tag": fallback_tag, "rarity": "Common", "rar_idx": 0, "inc": 2.0, "xp": 5, "sell": 60.0, "sim_multi": 1.25, "reasons": "Базовая генерация"}

        if cand["rar_idx"] >= 2:
            qr += 1
        ach_stats[cand["rarity"]] = ach_stats.get(cand["rarity"], 0) + 1

        # Авто-сохранение в гараж для Мифических+, если включена настройка
        save_flag = 0
        if auto_save_mythic and cand["rar_idx"] >= 5 and cur_hold_cnt < max_h:
            save_flag = 1
            cur_hold_cnt += 1

        cur.execute("""
            INSERT INTO usernames (tag, item_type, owner_id, rarity, income_per_sec, sell_price, sim_multi, reasons, is_equipped, channel_slot, is_saved, on_market, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, 0, ?)
        """, (cand["tag"], item_type, user_id, cand["rarity"], cand["inc"], cand["sell"], cand["sim_multi"], cand["reasons"], save_flag, now))

        reasons_list = cand["reasons"].split("|")
        if pity_triggered:
            reasons_list.insert(0, f"⚡ {pity_triggered}")

        drops.append({
            "tag": cand["tag"], "type": item_type, "rarity": cand["rarity"], "rar_idx": cand["rar_idx"],
            "inc": cand["inc"], "xp": cand["xp"], "sell": cand["sell"], "sim": cand["sim_multi"],
            "auto_saved": save_flag == 1, "reasons": reasons_list
        })
        added_xp += cand["xp"]

    new_bal = bal - cost
    new_xp = xp + added_xp
    new_lvl = lvl
    while new_xp >= new_lvl * 150:
        new_xp -= new_lvl * 150
        new_lvl += 1

    cur.execute("""
        UPDATE users SET balance = ?, level = ?, xp = ?, season_xp = ?, total_spins = ?,
                         pity_100 = ?, pity_500 = ?, q_spins = ?, q_rare = ?, ach_stats = ?
        WHERE tg_user_id = ?
    """, (new_bal, new_lvl, new_xp, s_xp, tot_s, p100, p500, qs, qr, json.dumps(ach_stats), user_id))

    return drops

@app.post("/api/mint")
def mint(data: ReqMint):
    if data.tier not in SPIN_TIERS: raise HTTPException(400, "Неверный тир прокрутки")
    if data.spin_count not in [1, 5]: raise HTTPException(400, "За GRAM доступно 1x или 5x")

    conn = sqlite3.connect(DB_NAME); cur = conn.cursor()
    auto_sold = auto_sell_unsaved(cur, data.user_id)
    process_passive_income(cur, data.user_id)

    tier_info = SPIN_TIERS[data.tier]
    unit_cost = tier_info["n_cost"] if data.item_type == "number" else tier_info["u_cost"]
    total_cost = unit_cost * data.spin_count

    try:
        drops = execute_spins_internal(cur, data.user_id, data.item_type, data.tier, data.spin_count, total_cost, data.auto_save_mythic)
        conn.commit()
    finally:
        conn.close()

    return {"drops": drops, "auto_sold": auto_sold}

@app.post("/api/action")
def tag_action(data: ReqAction):
    conn = sqlite3.connect(DB_NAME); cur = conn.cursor()
    cur.execute("SELECT item_type, sell_price, is_saved, is_equipped, on_market FROM usernames WHERE tag = ? AND owner_id = ?", (data.tag, data.user_id))
    t = cur.fetchone()
    if not t:
        conn.close(); raise HTTPException(400, "Предмет не найден")
    itype, sell_price, is_saved, is_eq, on_mkt = t
    if on_mkt == 1:
        conn.close(); raise HTTPException(400, "Предмет выставлен на Рынке!")

    if data.action_type == "save":
        cur.execute("SELECT max_hold FROM users WHERE tg_user_id = ?", (data.user_id,))
        max_h = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM usernames WHERE owner_id = ? AND is_saved = 1 AND on_market = 0", (data.user_id,))
        if cur.fetchone()[0] >= max_h:
            conn.close(); raise HTTPException(400, f"Хранилище заполнено ({max_h} мест)!")
        cur.execute("UPDATE usernames SET is_saved = 1 WHERE tag = ? AND owner_id = ?", (data.tag, data.user_id))
    elif data.action_type == "sell":
        if is_eq == 1:
            conn.close(); raise HTTPException(400, "Сначала снимите предмет со слота!")
        cur.execute("DELETE FROM usernames WHERE tag = ? AND owner_id = ?", (data.tag, data.user_id))
        cur.execute("UPDATE users SET balance = balance + ? WHERE tg_user_id = ?", (sell_price, data.user_id))
    elif data.action_type == "equip":
        if itype == "number":
            # Номера +888 ставятся в SIM-Шлюз (slot = 99), умножающий доход всех каналов
            cur.execute("UPDATE usernames SET is_equipped = 0, channel_slot = 0 WHERE owner_id = ? AND channel_slot = 99", (data.user_id,))
            cur.execute("UPDATE usernames SET is_saved = 1, is_equipped = 1, channel_slot = 99 WHERE tag = ? AND owner_id = ?", (data.tag, data.user_id))
        else:
            cur.execute("SELECT max_channels FROM users WHERE tg_user_id = ?", (data.user_id,))
            max_ch = cur.fetchone()[0]
            slot = max(1, min(data.slot, max_ch))
            cur.execute("UPDATE usernames SET is_equipped = 0, channel_slot = 0 WHERE owner_id = ? AND channel_slot = ?", (data.user_id, slot))
            cur.execute("UPDATE usernames SET is_saved = 1, is_equipped = 1, channel_slot = ? WHERE tag = ? AND owner_id = ?", (slot, data.tag, data.user_id))
    elif data.action_type == "unequip":
        cur.execute("UPDATE usernames SET is_equipped = 0, channel_slot = 0 WHERE tag = ? AND owner_id = ?", (data.tag, data.user_id))

    conn.commit(); conn.close()
    return {"status": "ok", "sold_for": sell_price}

# ==========================================
# ПОЛЬЗОВАТЕЛЬСКИЕ КЛАНЫ + MINTGENERAL
# ==========================================
@app.post("/api/clan/create")
def clan_create(data: ReqClanCreate):
    clean_name = data.name.strip()
    if len(clean_name) < 3 or len(clean_name) > 16:
        raise HTTPException(400, "Название клана должно быть от 3 до 16 символов!")

    conn = sqlite3.connect(DB_NAME); cur = conn.cursor()
    cur.execute("SELECT balance, clan_id FROM users WHERE tg_user_id = ?", (data.user_id,))
    u = cur.fetchone()
    if not u:
        conn.close(); raise HTTPException(404, "User not found")
    bal, cur_clan = u
    if cur_clan:
        conn.close(); raise HTTPException(400, "Сначала выйдите из текущего клана!")
    if bal < 1000000.0:
        conn.close(); raise HTTPException(400, "Создание клана стоит 1,000,000 GRAM!")

    cur.execute("SELECT 1 FROM clans WHERE LOWER(name) = LOWER(?)", (clean_name,))
    if cur.fetchone():
        conn.close(); raise HTTPException(400, "Клан с таким названием уже существует!")

    cid = f"clan_{data.user_id}_{int(time.time())}"
    cur.execute("UPDATE users SET balance = balance - 1000000.0, clan_id = ? WHERE tg_user_id = ?", (cid, data.user_id))
    cur.execute("""
        INSERT INTO clans (clan_id, name, owner_id, level, treasury, members_count, max_members, created_at)
        VALUES (?, ?, ?, 1, 0.0, 1, 100, ?)
    """, (cid, clean_name, data.user_id, int(time.time())))

    conn.commit(); conn.close()
    return {"status": "ok", "clan_id": cid}

@app.post("/api/clan/join")
def clan_join(data: ReqClanAction):
    conn = sqlite3.connect(DB_NAME); cur = conn.cursor()
    cur.execute("SELECT clan_id FROM users WHERE tg_user_id = ?", (data.user_id,))
    old_clan = cur.fetchone()[0]
    if old_clan == data.clan_id:
        conn.close(); raise HTTPException(400, "Вы уже состоите в этом клане!")

    cur.execute("SELECT members_count, max_members FROM clans WHERE clan_id = ?", (data.clan_id,))
    cl = cur.fetchone()
    if not cl:
        conn.close(); raise HTTPException(404, "Клан не найден")
    if cl[0] >= cl[1]:
        conn.close(); raise HTTPException(400, f"В клане достигнут лимит участников ({cl[1]})!")

    if old_clan:
        cur.execute("UPDATE clans SET members_count = MAX(0, members_count - 1) WHERE clan_id = ?", (old_clan,))

    cur.execute("UPDATE clans SET members_count = members_count + 1 WHERE clan_id = ?", (data.clan_id,))
    cur.execute("UPDATE users SET clan_id = ? WHERE tg_user_id = ?", (data.clan_id, data.user_id))
    conn.commit(); conn.close()
    return {"status": "ok"}

@app.post("/api/clan/leave")
def clan_leave(data: ReqSimple):
    conn = sqlite3.connect(DB_NAME); cur = conn.cursor()
    cur.execute("SELECT clan_id FROM users WHERE tg_user_id = ?", (data.user_id,))
    row = cur.fetchone()
    if not row or not row[0]:
        conn.close(); raise HTTPException(400, "Вы не состоите в клане")
    cid = row[0]
    cur.execute("UPDATE clans SET members_count = MAX(0, members_count - 1) WHERE clan_id = ?", (cid,))
    cur.execute("UPDATE users SET clan_id = NULL WHERE tg_user_id = ?", (data.user_id,))
    conn.commit(); conn.close()
    return {"status": "ok"}

@app.post("/api/clan/donate")
def clan_donate(data: ReqClanAction):
    if data.amount < 1000:
        raise HTTPException(400, "Минимальный взнос — 1,000 GRAM")
    conn = sqlite3.connect(DB_NAME); cur = conn.cursor()
    cur.execute("SELECT balance, clan_id FROM users WHERE tg_user_id = ?", (data.user_id,))
    bal, cid = cur.fetchone()
    if not cid:
        conn.close(); raise HTTPException(400, "Сначала вступите в клан!")
    if bal < data.amount:
        conn.close(); raise HTTPException(400, "Недостаточно GRAM на балансе")

    cur.execute("UPDATE users SET balance = balance - ? WHERE tg_user_id = ?", (data.amount, data.user_id))
    cur.execute("SELECT level, treasury FROM clans WHERE clan_id = ?", (cid,))
    lvl, tr = cur.fetchone()
    new_tr = tr + data.amount
    new_lvl = lvl
    # Каждые 250,000 GRAM в казне повышают уровень клана и дают +2% к доходу всех участников
    while new_tr >= new_lvl * 250000.0:
        new_tr -= new_lvl * 250000.0
        new_lvl += 1
    cur.execute("UPDATE clans SET level = ?, treasury = ? WHERE clan_id = ?", (new_lvl, new_tr, cid))
    conn.commit(); conn.close()
    return {"status": "ok", "new_level": new_lvl}

# ==========================================
# КРАФТЫ, РЫНОК, КОЛЕСО, ЗАДАНИЯ, ПАСС
# ==========================================
CRAFT_COSTS = {
    "Common": 10, "Uncommon": 50, "Rare": 250, "Epic": 1000,
    "Legendary": 5000, "Mythic": 15000, "Luxury": 50000, "Ultra-Mythic": 150000, "Exclusive": 500000
}

@app.post("/api/craft")
def craft_items(data: ReqCraft):
    if len(data.tags) != 5:
        raise HTTPException(400, "Выберите ровно 5 предметов одной редкости!")

    conn = sqlite3.connect(DB_NAME); cur = conn.cursor()
    placeholders = ",".join("?" for _ in data.tags)
    cur.execute(f"SELECT tag, item_type, rarity, is_equipped, on_market FROM usernames WHERE owner_id = ? AND tag IN ({placeholders})", [data.user_id, *data.tags])
    rows = cur.fetchall()
    if len(rows) != 5:
        conn.close(); raise HTTPException(400, "Не все предметы найдены в Хранилище")
    if len({r[2] for r in rows}) > 1:
        conn.close(); raise HTTPException(400, "Предметы должны быть одной редкости")
    if any(r[3] == 1 or r[4] == 1 for r in rows):
        conn.close(); raise HTTPException(400, "Снимите предметы со слотов перед крафтом")

    base_rar = rows[0][2]
    item_type = rows[0][1] or "username"
    rar_idx = next((i for i, r in enumerate(RARITIES) if r["name"] == base_rar), -1)
    if rar_idx < 0 or rar_idx >= len(RARITIES) - 1:
        conn.close(); raise HTTPException(400, "Максимальная редкость достигнута")

    cost = CRAFT_COSTS.get(base_rar, 100)
    cur.execute("SELECT balance FROM users WHERE tg_user_id = ?", (data.user_id,))
    if cur.fetchone()[0] < cost:
        conn.close(); raise HTTPException(400, f"Для крафта нужно {cost} GRAM")

    cur.execute(f"DELETE FROM usernames WHERE owner_id = ? AND tag IN ({placeholders})", [data.user_id, *data.tags])
    cur.execute("UPDATE users SET balance = balance - ?, q_crafts = q_crafts + 1, season_xp = season_xp + 15 WHERE tg_user_id = ?", (cost, data.user_id))

    if random.random() < 0.25:
        conn.commit(); conn.close()
        return {"burned": True, "message": "💥 Перегрев! Все 5 предметов сгорели при крафте..."}

    next_rar = RARITIES[rar_idx + 1]
    now = int(time.time())
    if item_type == "number":
        new_tag, inc, sell, sim_m, reas = generate_phone_number(next_rar)
    else:
        cand = roll_single_candidate(cur, "username", f"tier_{min(6, rar_idx+1)}", 1.0)
        new_tag, inc, sell, sim_m, reas = cand["tag"], next_rar["inc"], next_rar["sell"], 1.0, cand["reasons"]

    cur.execute("""
        INSERT OR REPLACE INTO usernames (tag, item_type, owner_id, rarity, income_per_sec, sell_price, sim_multi, reasons, is_equipped, channel_slot, is_saved, on_market, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 1, 0, ?)
    """, (new_tag, item_type, data.user_id, next_rar["name"], inc, sell, sim_m, reas, now))

    conn.commit(); conn.close()
    return {"burned": False, "item": {"tag": new_tag, "rarity": next_rar["name"], "inc": inc, "sell": sell}}

@app.post("/api/market/create")
def market_create(data: ReqMarketCreate):
    if data.price < 50: raise HTTPException(400, "Минимальная цена — 50 GRAM")
    if data.hours not in [1, 3, 6, 12, 24]: raise HTTPException(400, "Некорректное время")

    conn = sqlite3.connect(DB_NAME); cur = conn.cursor()
    cur.execute("SELECT item_type, rarity, income_per_sec, reasons, is_equipped, on_market FROM usernames WHERE tag = ? AND owner_id = ? AND is_saved = 1", (data.tag, data.user_id))
    row = cur.fetchone()
    if not row:
        conn.close(); raise HTTPException(400, "Предмет не найден")
    itype, rar, inc, reas, is_eq, on_mkt = row
    if is_eq == 1 or on_mkt == 1:
        conn.close(); raise HTTPException(400, "Снимите предмет со слота!")

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
        conn.close(); raise HTTPException(400, "Лот уже завершен")

    tag, itype, rar, inc, reas, seller_id, is_auc, cur_price, buyout, prev_bidder_id, bids_cnt, ends_at = lot
    if seller_id == data.user_id:
        conn.close(); raise HTTPException(400, "Это ваш собственный лот!")

    cur.execute("SELECT balance FROM users WHERE tg_user_id = ?", (data.user_id,))
    my_bal = cur.fetchone()[0]
    sim_m = next((r["sim"] for r in RARITIES if r["name"] == rar), 1.25) if itype == "number" else 1.0

    if is_auc == 0 or data.act == "buy":
        pay_price = cur_price if is_auc == 0 else buyout
        if my_bal < pay_price:
            conn.close(); raise HTTPException(400, f"Нужно {int(pay_price):,} GRAM")
        if prev_bidder_id and prev_bidder_id > 0:
            cur.execute("UPDATE users SET balance = balance + ? WHERE tg_user_id = ?", (cur_price, prev_bidder_id))
        cur.execute("UPDATE users SET balance = balance - ? WHERE tg_user_id = ?", (pay_price, data.user_id))
        if seller_id and seller_id > 0:
            cur.execute("UPDATE users SET balance = balance + ? WHERE tg_user_id = ?", (round(pay_price * 0.95, 2), seller_id))
        cur.execute("""
            INSERT OR REPLACE INTO usernames (tag, item_type, owner_id, rarity, income_per_sec, sell_price, sim_multi, reasons, is_equipped, channel_slot, is_saved, on_market, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 1, 0, ?)
        """, (tag, itype, data.user_id, rar, inc, round(pay_price * 0.75, 0), sim_m, reas, now))
        cur.execute("DELETE FROM market_lots WHERE lot_id = ?", (data.lot_id,))
        conn.commit(); conn.close()
        return {"status": "bought", "tag": tag}

    new_bid = round(cur_price * 1.10, 0) if bids_cnt > 0 else cur_price
    if my_bal < new_bid:
        conn.close(); raise HTTPException(400, f"Для ставки нужно {int(new_bid):,} GRAM")

    if prev_bidder_id and prev_bidder_id > 0:
        cur.execute("UPDATE users SET balance = balance + ? WHERE tg_user_id = ?", (cur_price, prev_bidder_id))

    cur.execute("UPDATE users SET balance = balance - ? WHERE tg_user_id = ?", (new_bid, data.user_id))
    cur.execute("""
        UPDATE market_lots SET current_price = ?, highest_bidder_id = ?, highest_bidder_name = ?,
                               bids_count = bids_count + 1, ends_at = ?
        WHERE lot_id = ?
    """, (new_bid, data.user_id, data.username, max(ends_at, now + 60), data.lot_id))

    conn.commit(); conn.close()
    return {"status": "bid_placed", "new_price": new_bid}

WHEEL_PRIZES = [
    {"idx": 0, "title": "2,500 GRAM",       "type": "coins", "val": 2500,   "w": 340},
    {"idx": 1, "title": "10,000 GRAM",      "type": "coins", "val": 10000,  "w": 240},
    {"idx": 2, "title": "🍀 Удача ×2 (1ч)", "type": "luck",  "val": 3600,   "w": 130},
    {"idx": 3, "title": "25,000 GRAM",      "type": "coins", "val": 25000,  "w": 110},
    {"idx": 4, "title": "📦 Редкий @тег",   "type": "tag",   "val": "Rare", "w": 90},
    {"idx": 5, "title": "50,000 GRAM",      "type": "coins", "val": 50000,  "w": 50},
    {"idx": 6, "title": "📞 Номер +888",    "type": "num",   "val": "Epic", "w": 30},
    {"idx": 7, "title": "💎 ДЖЕКПОТ 250K",  "type": "coins", "val": 250000, "w": 10}
]

@app.post("/api/wheel_spin")
def spin_wheel(data: ReqSimple):
    conn = sqlite3.connect(DB_NAME); cur = conn.cursor()
    now = int(time.time())
    cur.execute("SELECT last_wheel FROM users WHERE tg_user_id = ?", (data.user_id,))
    lw = cur.fetchone()[0]
    if (now - lw) < 1800:
        conn.close(); raise HTTPException(400, "Колесо доступно раз в 30 минут!")

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
        cur.execute("INSERT OR IGNORE INTO usernames (tag, item_type, owner_id, rarity, income_per_sec, sell_price, sim_multi, reasons, is_saved, created_at) VALUES (?,?,?,?,?,?,1.0,?,1,?)",
                    (t, "username", data.user_id, "Rare", 25.0, 850.0, "🎡 Приз Колеса Фортуны", now))
        cur.execute("UPDATE users SET last_wheel = ? WHERE tg_user_id = ?", (now, data.user_id))
    elif picked["type"] == "num":
        t, inc, sell, sim_m, reas = generate_phone_number(RARITIES[3])
        cur.execute("INSERT OR IGNORE INTO usernames (tag, item_type, owner_id, rarity, income_per_sec, sell_price, sim_multi, reasons, is_saved, created_at) VALUES (?,?,?,?,?,?,?,?,1,?)",
                    (t, "number", data.user_id, "Epic", inc, sell, sim_m, reas, now))
        cur.execute("UPDATE users SET last_wheel = ? WHERE tg_user_id = ?", (now, data.user_id))

    conn.commit(); conn.close()
    return {"prize_idx": picked["idx"], "title": picked["title"]}

DAILY_REWARDS = [2500, 5000, 10000, 20000, 35000, 50000, 100000]

@app.post("/api/daily_gift")
def claim_daily(data: ReqSimple):
    conn = sqlite3.connect(DB_NAME); cur = conn.cursor()
    now = int(time.time())
    cur.execute("SELECT daily_streak, last_daily FROM users WHERE tg_user_id = ?", (data.user_id,))
    streak, last_d = cur.fetchone()
    if (now - last_d) < 86400:
        conn.close(); raise HTTPException(400, "Подарок уже получен сегодня!")
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
        reward = 5000; add_s_xp = 50; q_cl.append("q1")
    elif key == "q2" and qr >= 5 and "q2" not in q_cl:
        reward = 12000; add_s_xp = 50; q_cl.append("q2")
    elif key == "q3" and qc >= 1 and "q3" not in q_cl:
        reward = 10000; add_s_xp = 50; q_cl.append("q3")
    elif key == "q_all" and all(x in q_cl for x in ["q1", "q2", "q3"]) and "q_all" not in q_cl:
        reward = 50000; add_s_xp = 100; q_cl.append("q_all")
    elif key.startswith("pass_"):
        lvl = int(key.split("_")[1])
        if s_xp >= lvl * 50 and key not in s_cl:
            reward = lvl * 2500
            s_cl.append(key)
    elif key.startswith("ach_"):
        parts = key.split("_")
        rar = parts[1]
        target = int(parts[2])
        if a_st.get(rar, 0) >= target and key not in a_cl:
            reward = target * 5000
            a_cl.append(key)
    else:
        conn.close(); raise HTTPException(400, "Условия не выполнены или награда уже получена")

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
    bal, smm, buyer = cur.fetchone()
    if data.key == "smm":
        cost = smm * 500.0
        if bal < cost: conn.close(); raise HTTPException(400, "Не хватает GRAM")
        cur.execute("UPDATE users SET balance = balance - ?, smm_lvl = smm_lvl + 1 WHERE tg_user_id = ?", (cost, data.user_id))
    else:
        cost = (buyer + 1) * 2000.0
        if bal < cost: conn.close(); raise HTTPException(400, "Не хватает GRAM")
        cur.execute("UPDATE users SET balance = balance - ?, buyer_lvl = buyer_lvl + 1 WHERE tg_user_id = ?", (cost, data.user_id))
    conn.commit(); conn.close()
    return {"status": "ok"}

@app.get("/api/prepare_share")
async def prepare_share(user_id: int, mode: str = "ref"):
    param = f"ref_{user_id}" if mode == "ref" else f"trade_{user_id}"
    bot_link = f"https://t.me/MintTagsBot?startapp={param}"
    html_text = (
        f"👑 Забирай эксклюзивные <b>@username</b> и анонимные номера <b>+888</b> в "
        f"<a href=\"{bot_link}\">MintTags: Media Empire</a>!\n\n"
        f"🎁 Тебе начислен стартовый капитал <b>5,000 GRAM</b>!"
    )
    try:
        res = await bot.save_prepared_inline_message(
            user_id=user_id,
            result=InlineQueryResultArticle(
                id=f"sh_{user_id}_{int(time.time())}",
                title="Пригласить друга в MintTags",
                input_message_content=InputTextMessageContent(message_text=html_text, parse_mode="HTML"),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚀 Запустить MintTags", url=bot_link)]])
            ),
            allow_user_chats=True, allow_group_chats=True, allow_channel_chats=True
        )
        return {"prepared_id": res.id}
    except Exception:
        return {"prepared_id": None}

# КАТАЛОГ TELEGRAM STARS (Включая 10x за 150 звезд и 25x за 219 звезд!)
PRICES = {
    "spin_10_stars": {"title": "⚡ 10 Прокрутов сразу (Rare+)",  "price": 150},
    "spin_25_stars": {"title": "🔥 25 Прокрутов сразу (Epic+)",  "price": 219},
    "vip_pass":      {"title": "👑 VIP Game Pass (30 дней)",     "price": 89},
    "luck_x2_1h":    {"title": "🍀 Буст Удачи ×2 (1 час)",       "price": 19},
    "luck_x5_2h":    {"title": "🔥 Мега Удача ×5 (2 часа)",      "price": 49},
    "hold_plus_50":  {"title": "💼 +50 слотов в Хранилище",      "price": 45},
    "channel_slot":  {"title": "📢 Новый слот Канала",           "price": 59},
    "coins_100k":    {"title": "🪙 100,000 GRAM",                "price": 25},
    "coins_500k":    {"title": "💰 500,000 GRAM Магната",        "price": 75},
    "num_888_box":   {"title": "📞 Элитный Бокс +888 (Mythic+)", "price": 99}
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
    now = int(time.time())
    raw_key = data.key
    parts = raw_key.split(":")
    p = parts[0]
    itype = parts[1] if len(parts) > 1 else "username"

    drops = []
    if p == "spin_10_stars":
        drops = execute_spins_internal(cur, data.user_id, itype, "tier_2", 10, 0.0, True)
    elif p == "spin_25_stars":
        drops = execute_spins_internal(cur, data.user_id, itype, "tier_3", 25, 0.0, True)
    elif p == "vip_pass":
        cur.execute("UPDATE users SET vip_until = ?, max_hold = max_hold + 50, balance = balance + 50000 WHERE tg_user_id = ?", (now + 2592000, data.user_id))
    elif p == "luck_x2_1h":
        cur.execute("UPDATE users SET luck_multi = 2.0, luck_until = ? WHERE tg_user_id = ?", (now + 3600, data.user_id))
    elif p == "luck_x5_2h":
        cur.execute("UPDATE users SET luck_multi = 5.0, luck_until = ? WHERE tg_user_id = ?", (now + 7200, data.user_id))
    elif p == "hold_plus_50":
        cur.execute("UPDATE users SET max_hold = max_hold + 50 WHERE tg_user_id = ?", (data.user_id,))
    elif p == "channel_slot":
        cur.execute("UPDATE users SET max_channels = MIN(15, max_channels + 1) WHERE tg_user_id = ?", (data.user_id,))
    elif p == "coins_100k":
        cur.execute("UPDATE users SET balance = balance + 100000 WHERE tg_user_id = ?", (data.user_id,))
    elif p == "coins_500k":
        cur.execute("UPDATE users SET balance = balance + 500000 WHERE tg_user_id = ?", (data.user_id,))
    elif p == "num_888_box":
        t, inc, sell, sim_m, reas = generate_phone_number(RARITIES[5])
        cur.execute("INSERT OR IGNORE INTO usernames (tag, item_type, owner_id, rarity, income_per_sec, sell_price, sim_multi, reasons, is_saved, created_at) VALUES (?,?,?,?,?,?,?,?,1,?)",
                    (t, "number", data.user_id, "Mythic", inc, sell, sim_m, reas, now))

    conn.commit(); conn.close()
    return {"status": "ok", "drops": drops}
