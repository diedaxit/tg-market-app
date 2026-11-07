import sqlite3
import psycopg2
from psycopg2 import pool
import asyncio
import random
import time
import os
import json
import hmac
import hashlib
from urllib.parse import parse_qsl
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from aiogram.types import LabeledPrice, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from bot import bot, APP_URL

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATABASE_URL = os.getenv("DATABASE_URL", "")
DB_NAME = "market.db"
NEWS_CHANNEL = "@MintTags_News"

# ==========================================
# БЫСТРЫЙ ПУЛ СОЕДИНЕНИЙ POSTGRESQL NEON
# ==========================================
PG_POOL = None
if DATABASE_URL:
    try:
        PG_POOL = psycopg2.pool.ThreadedConnectionPool(1, 20, dsn=DATABASE_URL)
    except Exception:
        PG_POOL = None

class CursorWrapper:
    def __init__(self, raw_cur, is_pg: bool):
        self.cur = raw_cur
        self.is_pg = is_pg

    def execute(self, sql: str, params: tuple | list = ()):
        if self.is_pg:
            q = sql.replace("?", "%s")
            q = q.replace("INSERT OR IGNORE INTO", "INSERT INTO")
            if "INSERT INTO clans" in q and "ON CONFLICT" not in q:
                q += " ON CONFLICT (clan_id) DO NOTHING"
            if "INSERT INTO usernames" in sql and "OR IGNORE" in sql and "ON CONFLICT" not in q:
                q += " ON CONFLICT (tag) DO NOTHING"
            if "INSERT OR REPLACE INTO usernames" in q:
                q = q.replace("INSERT OR REPLACE INTO usernames", "INSERT INTO usernames")
                q += """ ON CONFLICT (tag) DO UPDATE SET
                    owner_id = EXCLUDED.owner_id, rarity = EXCLUDED.rarity, quality_pct = EXCLUDED.quality_pct,
                    income_per_sec = EXCLUDED.income_per_sec, sell_price = EXCLUDED.sell_price,
                    num_multi = EXCLUDED.num_multi, reasons = EXCLUDED.reasons, is_equipped = EXCLUDED.is_equipped,
                    channel_slot = EXCLUDED.channel_slot, is_saved = EXCLUDED.is_saved, on_market = EXCLUDED.on_market"""
            return self.cur.execute(q, params)
        return self.cur.execute(sql, params)

    def fetchone(self):
        return self.cur.fetchone()

    def fetchall(self):
        return self.cur.fetchall()

class ConnWrapper:
    def __init__(self, raw_conn, is_pg: bool, from_pool: bool = False):
        self.conn = raw_conn
        self.is_pg = is_pg
        self.from_pool = from_pool

    def cursor(self):
        return CursorWrapper(self.conn.cursor(), self.is_pg)

    def commit(self):
        self.conn.commit()

    def close(self):
        if self.is_pg and self.from_pool and PG_POOL:
            try:
                PG_POOL.putconn(self.conn)
                return
            except Exception:
                pass
        try:
            self.conn.close()
        except Exception:
            pass

def get_db():
    global PG_POOL
    if DATABASE_URL:
        if PG_POOL:
            try:
                c = PG_POOL.getconn()
                if c.closed != 0:
                    PG_POOL.putconn(c, close=True)
                    c = psycopg2.connect(DATABASE_URL)
                    return ConnWrapper(c, True, False)
                return ConnWrapper(c, True, True)
            except Exception:
                pass
        raw = psycopg2.connect(DATABASE_URL)
        return ConnWrapper(raw, True, False)
    raw = sqlite3.connect(DB_NAME, timeout=15.0)
    raw.execute("PRAGMA journal_mode=WAL")
    raw.execute("PRAGMA synchronous=NORMAL")
    return ConnWrapper(raw, False, False)

# ==========================================
# СТРОГИЙ БАЛАНС 10 РЕДКОСТЕЙ (БЕЗ МИЛЛИОНОВ В СЕКУНДУ!)
# ==========================================
RARITIES = [
    {"name": "Common",       "ru": "Обычный",      "w": 820000, "min_p": 40,       "max_p": 250,       "inc": 0.1,   "xp": 5,     "num_x": 1.10},
    {"name": "Uncommon",     "ru": "Необычный",    "w": 145000, "min_p": 251,      "max_p": 900,       "inc": 0.3,   "xp": 15,    "num_x": 1.20},
    {"name": "Rare",         "ru": "Редкий",       "w": 28000,  "min_p": 901,      "max_p": 4200,      "inc": 0.9,   "xp": 40,    "num_x": 1.35},
    {"name": "Epic",         "ru": "Эпический",    "w": 5500,   "min_p": 4201,     "max_p": 22000,     "inc": 2.5,   "xp": 100,   "num_x": 1.50},
    {"name": "Legendary",    "ru": "Легендарный",  "w": 1100,   "min_p": 22001,    "max_p": 110000,    "inc": 6.5,   "xp": 300,   "num_x": 1.75},
    {"name": "Mythic",       "ru": "Мифический",   "w": 280,    "min_p": 110001,   "max_p": 550000,    "inc": 15.0,  "xp": 800,   "num_x": 2.00},
    {"name": "Luxury",       "ru": "Роскошный",    "w": 85,     "min_p": 550001,   "max_p": 3000000,   "inc": 32.0,  "xp": 1500,  "num_x": 2.30},
    {"name": "Ultra-Mythic", "ru": "Ультра-Мифик", "w": 25,     "min_p": 3000001,  "max_p": 18000000,  "inc": 60.0,  "xp": 2500,  "num_x": 2.60},
    {"name": "Exclusive",    "ru": "Эксклюзивный", "w": 8,      "min_p": 18000001, "max_p": 95000000,  "inc": 90.0,  "xp": 5000,  "num_x": 3.00},
    {"name": "Divine",       "ru": "Божественный", "w": 2,      "min_p": 95000001, "max_p": 600000000, "inc": 135.0, "xp": 15000, "num_x": 3.50}
]

def init_db():
    conn = get_db()
    cur = conn.cursor()
    id_type = "SERIAL PRIMARY KEY" if conn.is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    big_type = "BIGINT" if conn.is_pg else "INTEGER"

    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS users (
            member_number {id_type},
            tg_user_id {big_type} UNIQUE,
            username TEXT,
            balance REAL DEFAULT 15000.0,
            level INTEGER DEFAULT 1,
            xp INTEGER DEFAULT 0,
            season_xp INTEGER DEFAULT 0,
            season_claimed TEXT DEFAULT '[]',
            luck_multi REAL DEFAULT 1.0,
            luck_until {big_type} DEFAULT 0,
            vip_until {big_type} DEFAULT 0,
            max_hold INTEGER DEFAULT 100,
            max_channels INTEGER DEFAULT 2,
            ref_by {big_type} DEFAULT NULL,
            refs_count INTEGER DEFAULT 0,
            ref_3_rewarded INTEGER DEFAULT 0,
            contrib_gram REAL DEFAULT 0.0,
            contrib_stars INTEGER DEFAULT 0,
            smm_lvl INTEGER DEFAULT 1,
            buyer_lvl INTEGER DEFAULT 0,
            ai_boost INTEGER DEFAULT 0,
            clan_id TEXT DEFAULT NULL,
            total_spins INTEGER DEFAULT 0,
            pity_100 INTEGER DEFAULT 0,
            pity_500 INTEGER DEFAULT 0,
            last_wheel {big_type} DEFAULT 0,
            last_vault {big_type} DEFAULT 0,
            daily_streak INTEGER DEFAULT 0,
            last_daily {big_type} DEFAULT 0,
            q_spins INTEGER DEFAULT 0,
            q_rare INTEGER DEFAULT 0,
            q_crafts INTEGER DEFAULT 0,
            q_duels INTEGER DEFAULT 0,
            q_claimed TEXT DEFAULT '[]',
            ach_stats TEXT DEFAULT '{{}}',
            ach_claimed TEXT DEFAULT '[]',
            albums_claimed TEXT DEFAULT '[]',
            promos_used TEXT DEFAULT '[]',
            contracts_done TEXT DEFAULT '[]',
            tax_shield_until {big_type} DEFAULT 0,
            duel_wins INTEGER DEFAULT 0,
            auto_save_min_idx INTEGER DEFAULT 0,
            sub_verified INTEGER DEFAULT 0,
            notify_merchant INTEGER DEFAULT 0,
            last_claim {big_type} DEFAULT 0,
            created_at {big_type}
        )
    """)
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS usernames (
            tag TEXT PRIMARY KEY,
            item_type TEXT DEFAULT 'username',
            owner_id {big_type},
            rarity TEXT,
            quality_pct INTEGER DEFAULT 50,
            income_per_sec REAL,
            sell_price REAL,
            num_multi REAL DEFAULT 1.0,
            reasons TEXT,
            is_equipped INTEGER DEFAULT 0,
            channel_slot INTEGER DEFAULT 0,
            is_saved INTEGER DEFAULT 1,
            on_market INTEGER DEFAULT 0,
            is_staked INTEGER DEFAULT 0,
            is_verified INTEGER DEFAULT 0,
            last_duel_at {big_type} DEFAULT 0,
            created_at {big_type}
        )
    """)
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS staked_deposits (
            stake_id {id_type},
            user_id {big_type},
            stake_type TEXT,
            tag TEXT DEFAULT '',
            principal_gram REAL DEFAULT 0.0,
            reward_gram REAL DEFAULT 0.0,
            hours INTEGER DEFAULT 3,
            unlocks_at {big_type},
            claimed INTEGER DEFAULT 0,
            created_at {big_type}
        )
    """)
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS gift_checks (
            code TEXT PRIMARY KEY,
            creator_id {big_type},
            amount REAL,
            claimed_by {big_type} DEFAULT NULL,
            created_at {big_type}
        )
    """)
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS market_lots (
            lot_id {id_type},
            tag TEXT UNIQUE,
            item_type TEXT,
            rarity TEXT,
            income_per_sec REAL,
            num_multi REAL DEFAULT 1.0,
            reasons TEXT,
            seller_id {big_type},
            seller_name TEXT,
            is_auction INTEGER DEFAULT 0,
            start_price REAL,
            current_price REAL,
            buyout_price REAL,
            highest_bidder_id {big_type} DEFAULT NULL,
            highest_bidder_name TEXT DEFAULT '',
            bids_count INTEGER DEFAULT 0,
            ends_at {big_type},
            created_at {big_type}
        )
    """)
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS clans (
            clan_id TEXT PRIMARY KEY,
            name TEXT UNIQUE,
            owner_id {big_type} DEFAULT 0,
            level INTEGER DEFAULT 1,
            treasury REAL DEFAULT 0.0,
            members_count INTEGER DEFAULT 0,
            max_members INTEGER DEFAULT 100,
            created_at {big_type} DEFAULT 0
        )
    """)
    conn.commit()

    for col, ctype in [
        ("notify_merchant", "INTEGER DEFAULT 0"),
        ("ref_3_rewarded", "INTEGER DEFAULT 0"),
        ("last_vault", f"{big_type} DEFAULT 0"),
        ("promos_used", "TEXT DEFAULT '[]'"),
        ("contracts_done", "TEXT DEFAULT '[]'")
    ]:
        try:
            cur.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {ctype}" if conn.is_pg else f"ALTER TABLE users ADD COLUMN {col} {ctype}")
            conn.commit()
        except Exception:
            if conn.is_pg: conn.conn.rollback()

    for col, ctype in [
        ("is_staked", "INTEGER DEFAULT 0"),
        ("is_verified", "INTEGER DEFAULT 0"),
        ("last_duel_at", f"{big_type} DEFAULT 0")
    ]:
        try:
            cur.execute(f"ALTER TABLE usernames ADD COLUMN IF NOT EXISTS {col} {ctype}" if conn.is_pg else f"ALTER TABLE usernames ADD COLUMN {col} {ctype}")
            conn.commit()
        except Exception:
            if conn.is_pg: conn.conn.rollback()

    # ==========================================
    # АВТО-САНИТАЙЗЕР ЭКОНОМИКИ: ИСПРАВЛЯЕТ СТАРЫЕ 27 МЛН/С В БАЗЕ!
    # ==========================================
    try:
        for r_obj in RARITIES:
            max_allowed_inc = round(r_obj["inc"] * 2.5, 2)
            cur.execute(
                "UPDATE usernames SET income_per_sec = ?, num_multi = ? WHERE rarity = ? AND (income_per_sec > ? OR num_multi > 3.5)",
                (r_obj["inc"], r_obj["num_x"], r_obj["name"], max_allowed_inc)
            )
        # Если кто-то нафармил триллионы на старом баге множителя, срезаем сверхлимит до 50M
        cur.execute("UPDATE users SET balance = 50000000.0 WHERE balance > 150000000.0")
        conn.commit()
    except Exception:
        if conn.is_pg: conn.conn.rollback()

    cur.execute("""
        INSERT OR IGNORE INTO clans (clan_id, name, owner_id, level, treasury, members_count, max_members, created_at)
        VALUES ('mint_general', 'MintGeneral', 0, 5, 1000000.0, 1, 1000, ?)
    """, (int(time.time()),))
    conn.commit()
    conn.close()

init_db()

# ==========================================
# ЗАЩИТА И АКТИВНЫЕ СЕССИИ РАКЕТКИ (РУЧНОЙ КЭШАУТ В ЛЮБОЙ МОМЕНТ!)
# ==========================================
RATE_BUCKETS = {}
TX_LOCKS = set()
ACTIVE_ROCKETS = {} # user_id -> {"bet": float, "crash_x": float, "started_at": float}

def check_rate(uid: int, max_hits: int = 18, window: float = 2.0):
    now = time.time()
    arr = [t for t in RATE_BUCKETS.get(uid, []) if now - t < window]
    if len(arr) >= max_hits:
        raise HTTPException(429, "Слишком быстро! Подождите 1 секунду.")
    arr.append(now)
    RATE_BUCKETS[uid] = arr

def verify_tg_auth(init_data: str, uid: int):
    if not init_data:
        return
    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
        r_hash = parsed.pop("hash", None)
        if not r_hash:
            return
        data_str = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret = hmac.new(b"WebAppData", bot.token.encode(), hashlib.sha256).digest()
        c_hash = hmac.new(secret, data_str.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(c_hash, r_hash):
            raise HTTPException(403, "Ошибка подписи безопасности Telegram")
    except HTTPException:
        raise
    except Exception:
        pass

SPIN_TIERS = {
    "tier_0": {"min_idx": 0, "u_cost": 600,      "n_cost": 45000,     "title": "Обычный+"},
    "tier_1": {"min_idx": 1, "u_cost": 2200,     "n_cost": 140000,    "title": "Необычный+"},
    "tier_2": {"min_idx": 2, "u_cost": 8500,     "n_cost": 450000,    "title": "Редкий+"},
    "tier_3": {"min_idx": 3, "u_cost": 35000,    "n_cost": 1800000,   "title": "Эпический+"},
    "tier_4": {"min_idx": 4, "u_cost": 160000,   "n_cost": 7500000,   "title": "Легендарный+"},
    "tier_5": {"min_idx": 5, "u_cost": 750000,   "n_cost": 32000000,  "title": "Мифический+"},
    "tier_6": {"min_idx": 6, "u_cost": 3500000,  "n_cost": 120000000, "title": "Luxury+"}
}

MAX_SMM_LVL = 20
MAX_BUYER_LVL = 15

def get_smm_upgrade_cost(lvl: int) -> float:
    return round(6000.0 * (2.45 ** (lvl - 1)))

def get_buyer_upgrade_cost(lvl: int) -> float:
    return round(35000.0 * (2.75 ** lvl))

WORD_LORE = {
    "x": ("Ультра-символ «X» (1 буква)", "×500"),
    "v": ("Знак Победы «V» (1 буква)", "×480"),
    "ai": ("Искусственный Интеллект «AI»", "×420"),
    "go": ("Глагол действия «GO» (2 буквы)", "×380"),
    "durov": ("Культовый корень «durov» (Основатель)", "×120"),
    "telegram": ("Официальный бренд «telegram»", "×110"),
    "ton": ("Крипто-тикер блокчейна «TON»", "×95"),
    "notcoin": ("Легендарный веб3-токен «notcoin»", "×85"),
    "redo": ("Символ Resistance Dog «redo»", "×80"),
    "cat": ("Короткое слово «cat» (3 буквы)", "×45"),
    "dog": ("Короткое слово «dog» (3 буквы)", "×45"),
    "nft": ("Индекс цифровых активов «NFT»", "×55"),
    "god": ("Статусный тег «god» (3 буквы)", "×50"),
    "dubai": ("Эмиратская серия «dubai»", "×25"),
    "money": ("Финансовый корень «money»", "×22"),
    "rich": ("Лакшери статус «rich»", "×20"),
    "gold": ("Премиальный корень «gold»", "×20"),
    "star": ("Звездная серия «star» (4 буквы)", "×12"),
    "litvin": ("Медийный никнейм «litvin»", "×14"),
    "mellstroy": ("Хайп-индекс «mellstroy»", "×15"),
    "mrbeast": ("Мировой бренд «mrbeast»", "×16"),
    "tiger": ("Хищный корень «tiger» (5 букв)", "×8,5"),
    "ghost": ("Анонимный корень «ghost» (5 букв)", "×8,5"),
    "alpha": ("Лидерский индекс «alpha» (5 букв)", "×8,5"),
    "whale": ("Индекс крипто-кита «whale» (5 букв)", "×9,0")
}

WORDS = {
    "Divine": ["x", "v", "ai", "go", "ok", "up", "id", "on", "tv", "io"],
    "Exclusive": ["durov", "telegram", "ton", "notcoin", "pavel", "vk", "redo", "fragment", "tether", "bitcoin"],
    "Ultra-Mythic": ["cat", "dog", "bot", "nft", "god", "top", "ceo", "vip", "pro", "pay", "dex", "jet"],
    "Luxury": ["dubai", "money", "rich", "gold", "boss", "king", "stars", "rolex", "yacht", "lambo", "sheikh", "monaco", "cartier", "bugatti"],
    "Mythic": ["star", "epic", "moon", "flow", "dark", "litvin", "mellstroy", "mrbeast", "diamond", "empire", "billion", "legend"],
    "Legendary": ["tiger", "ghost", "alpha", "prime", "whale", "daner", "avusk", "leoon", "hasbulla", "dragon", "knight", "sultan"],
    "Epic": ["shadow", "crypto", "hacker", "sniper", "ninja", "blade", "phantom", "cyber", "vortex", "matrix"],
    "Rare": ["gamer", "player", "rocket", "market", "trade", "speed", "hunter", "stream", "glory", "booster"]
}

GIFT_CATALOG = {
    "Common":       [("🍭 Леденец TON", "×1,2"), ("☕️ Кофе Разработчика", "×1,2"), ("🎈 Шарик Telegram", "×1,3")],
    "Uncommon":     [("🌹 Алая Роза", "×1,6"), ("🎂 Торт Дурова", "×1,7"), ("🍾 Шампанское Магната", "×1,8")],
    "Rare":         [("💎 Синий Кристалл", "×2,5"), ("🎩 Цилиндр Джентльмена", "×2,8"), ("🔮 Магический Шар", "×3,0")],
    "Epic":         [("🧪 Зелье Павла", "×4,5"), ("🎸 Неоновая Гитара", "×4,8"), ("👾 Кибер-Череп", "×5,2")],
    "Legendary":    [("🧢 Кепка Дурова (Durov's Cap)", "×10"), ("🕶 Очки Матрицы", "×9,5"), ("🏆 Золотой Кубок TON", "×11")],
    "Mythic":       [("🐶 Resistance Dog (REDO)", "×22"), ("🐸 Изумрудный Plush Pepe", "×25"), ("⌚️ Часы Patek TON", "×20")],
    "Luxury":       [("🐸 Золотой Plush Pepe", "×48"), ("🏎 Спорткар Магната", "×42"), ("🛥 Яхта Шейха Дубая", "×50")],
    "Ultra-Mythic": [("👑 Корона Основателя", "×95"), ("🐸 Бриллиантовый Pepe", "×110"), ("✈️ Частный Джет G650", "×90")],
    "Exclusive":    [("🐶 Золотой REDO #001", "×220"), ("🐸 Астральный Plush Pepe", "×250"), ("🏝 Остров в Дубае", "×200")],
    "Divine":       [("🗝 Ключ от Блокчейна TON #1", "×500"), ("🐸 Божественный Genesis Pepe", "×600"), ("💎 Монолит Павла Дурова", "×550")]
}

CASES_CATALOG = {
    "case_tag_start": {
        "title": "🏷 Стартовый Tag-Кейс", "sub": "Только @username (Uncommon ➔ Epic)",
        "curr": "gram", "price": 6500, "types": ["username"],
        "weights": {1: 680, 2: 260, 3: 55, 4: 5}
    },
    "case_gifts_ton": {
        "title": "🐸 Gift-Бокс: Мемы TON", "sub": "Только NFT-Подарки (Pepe, REDO, Cap)",
        "curr": "gram", "price": 48000, "types": ["gift"],
        "weights": {2: 520, 3: 330, 4: 115, 5: 30, 6: 5}
    },
    "case_num_888": {
        "title": "📞 Кейс Анонимных +888", "sub": "Только номера +888 для каналов",
        "curr": "gram", "price": 95000, "types": ["number"],
        "weights": {1: 480, 2: 350, 3: 130, 4: 35, 5: 5}
    },
    "case_sheikh_mix": {
        "title": "👳‍♂️ Кейс Шейха (Микс 3-в-1)", "sub": "@username + Номера +888 + NFT-Подарки (Rare+)",
        "curr": "gram", "price": 290000, "types": ["username", "number", "gift"],
        "weights": {2: 420, 3: 360, 4: 160, 5: 48, 6: 10, 7: 2}
    },
    "case_oligarch": {
        "title": "💼 Олигарх Контейнер", "sub": "Тяжелый люкс: гарантия Legendary и выше!",
        "curr": "gram", "price": 1800000, "types": ["username", "number", "gift"],
        "weights": {4: 580, 5: 290, 6: 100, 7: 24, 8: 5, 9: 1}
    },
    "case_stars_lite": {
        "title": "⭐️ Звездный Ларец", "sub": "Донатный кейс: Epic+ теги и NFT-Подарки",
        "curr": "stars", "price": 29, "types": ["username", "gift"],
        "weights": {3: 540, 4: 320, 5: 110, 6: 25, 7: 5}
    },
    "case_stars_founder": {
        "title": "👑 Кейс Основателя", "sub": "Гарантия Mythic+ (+888, Топ-Ник или Золотой Пепе)",
        "curr": "stars", "price": 99, "types": ["username", "number", "gift"],
        "weights": {5: 560, 6: 310, 7: 100, 8: 25, 9: 5}
    },
    "case_stars_divine": {
        "title": "💎 Божественный Сундук Дурова", "sub": "Высшая лига: Luxury, Exclusive и Divine!",
        "curr": "stars", "price": 249, "types": ["username", "number", "gift"],
        "weights": {6: 500, 7: 320, 8: 140, 9: 40}
    }
}

LAST_NOTIFIED_MERCHANT_SLOT = -1

def get_daily_hot_series():
    day_seed = int(time.time() // 3600)
    series_list = [
        {"code": "pepe", "title": "Рыночный бум на NFT-Подарки Pepe!", "bonus_pct": 45},
        {"code": "77",   "title": "Ажиотаж на цифры «77» в номере/теге", "bonus_pct": 40},
        {"code": "888",  "title": "Высокий спрос на все номера +888", "bonus_pct": 35},
        {"code": "redo", "title": "Взлет цен на REDO и Кепки Дурова", "bonus_pct": 45},
        {"code": "a",    "title": "Теги, начинающиеся на «@a»", "bonus_pct": 35}
    ]
    return series_list[day_seed % len(series_list)]

def get_daily_vip_contracts():
    day_seed = int(time.time() // 86400)
    return [
        {"id": f"c1_{day_seed}", "title": "🕵️ Заказ Блогера: Любой Epic @username", "req_type": "username", "req_rar": "Epic", "mult": 2.1, "flat_bonus": 25000},
        {"id": f"c2_{day_seed}", "title": "🐸 Заказ Коллекционера: Rare+ NFT-Подарок", "req_type": "gift", "req_rar": "Rare", "mult": 2.2, "flat_bonus": 35000},
        {"id": f"c3_{day_seed}", "title": "📞 Заказ Холдинга: Номер +888 (Rare)", "req_type": "number", "req_rar": "Rare", "mult": 1.9, "flat_bonus": 75000}
    ]

def get_active_merchant_offer():
    now = int(time.time())
    slot_20m = now // 1200
    phase = now % 1200
    offers = [
        {"rarity": "Rare",      "ru": "Редкий",      "bonus_mult": 1.65, "bonus_pct": 65, "title": "Тайный Скупщик охотится за Rare!"},
        {"rarity": "Epic",      "ru": "Эпический",   "bonus_mult": 1.75, "bonus_pct": 75, "title": "Арабский Шейх скупает Epic!"},
        {"rarity": "Uncommon",  "ru": "Необычный",   "bonus_mult": 1.80, "bonus_pct": 80, "title": "Оптовый Байер скупает Uncommon!"},
        {"rarity": "Legendary", "ru": "Легендарный", "bonus_mult": 1.60, "bonus_pct": 60, "title": "Киты TON скупают Legendary!"}
    ]
    pick = dict(offers[slot_20m % len(offers)])
    if phase < 600:
        pick["active"] = True
        pick["left_sec"] = 600 - phase
        pick["next_in_sec"] = 0
    else:
        pick["active"] = False
        pick["left_sec"] = 0
        pick["next_in_sec"] = 1200 - phase
    pick["slot_id"] = slot_20m
    return pick

async def merchant_notification_worker():
    global LAST_NOTIFIED_MERCHANT_SLOT
    await asyncio.sleep(5)
    while True:
        try:
            m = get_active_merchant_offer()
            if m["active"] and m["slot_id"] != LAST_NOTIFIED_MERCHANT_SLOT:
                LAST_NOTIFIED_MERCHANT_SLOT = m["slot_id"]
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🕵️‍♂️ Продать Скупщику (+ бонус)", web_app=WebAppInfo(url=APP_URL))]
                ])
                text = (
                    f"🕵️‍♂️ <b>{m['title']}</b>\n\n"
                    f"В <b>MintTags</b> только что приехал Тайный Перекуп!\n"
                    f"🔹 Принимает редкость: <b>{m['ru']} ({m['rarity']})</b>\n"
                    f"💰 Наценка к рынку: <b>+{m['bonus_pct']}%</b>\n"
                    f"⏳ Уедет ровно через: <b>10 минут</b>!"
                )
                try:
                    await bot.send_message(chat_id=NEWS_CHANNEL, text=text, reply_markup=kb, parse_mode="HTML")
                except Exception:
                    pass
                try:
                    conn = get_db(); cur = conn.cursor()
                    cur.execute("SELECT tg_user_id FROM users WHERE notify_merchant = 1 LIMIT 200")
                    uids = [r[0] for r in cur.fetchall()]
                    conn.close()
                    for uid in uids:
                        try:
                            await bot.send_message(chat_id=uid, text=text, reply_markup=kb, parse_mode="HTML")
                            await asyncio.sleep(0.05)
                        except Exception:
                            pass
                except Exception:
                    pass
        except Exception:
            pass
        await asyncio.sleep(20)

@app.on_event("startup")
async def on_startup_tasks():
    asyncio.create_task(merchant_notification_worker())

def generate_live_nickname():
    syllables = ["ka", "mi", "ro", "va", "ze", "lu", "no", "ta", "ke", "si", "da", "ve", "xo", "ni", "ba", "le", "fa", "mo", "ri", "to"]
    prefixes = ["neo", "ava", "max", "leo", "dan", "nik", "art", "tim", "kir", "rom", "vlad", "mak", "sem", "gleb"]
    suffixes = ["ov", "ev", "sk", "ix", "on", "er", "ik", "us", "in", "ax", "ez"]
    t = random.randint(1, 3)
    if t == 1: return "".join(random.sample(syllables, random.randint(2, 3)))
    if t == 2: return random.choice(prefixes) + random.choice(syllables) + random.choice(suffixes)
    return random.choice(prefixes) + random.choice(suffixes)

def calc_range_price(r_obj: dict, quality_pct: int, item_type: str = "username"):
    q = max(0.01, min(1.0, quality_pct / 100.0))
    span = r_obj["max_p"] - r_obj["min_p"]
    price = round(r_obj["min_p"] + span * q)
    inc = round(r_obj["inc"] * (0.75 + 0.5 * q), 2)
    if item_type == "number":
        price = round(price * 12)
        inc = round(inc * 1.3, 2)
    elif item_type == "gift":
        price = round(price * 4.0)
        inc = round(inc * 1.25, 2)
    return price, inc

def generate_nft_gift(r_obj: dict):
    rarity_name = r_obj["name"]
    quality = random.randint(15, 99)
    pool_g = GIFT_CATALOG.get(rarity_name, GIFT_CATALOG["Common"])
    g_title, g_mult = random.choice(pool_g)
    serial = random.randint(1, 99) if rarity_name in ["Divine", "Exclusive", "Ultra-Mythic", "Luxury"] else random.randint(100, 9999)
    tag = f"{g_title} #{serial}"
    sell, inc = calc_range_price(r_obj, quality, item_type="gift")
    factors = [
        {"label": f"Коллекционный подарок «{g_title}»", "mult": g_mult},
        {"label": f"Серийный номер минта #{serial}", "mult": "×3,5" if serial < 100 else "×1,4"},
        {"label": f"Сохранность в тире {rarity_name}", "mult": f"×{round(1.0 + quality/100, 2)}".replace(".", ",")}
    ]
    reasons_str = "|".join(f"{f['label']} {f['mult']}" for f in factors)
    return tag, inc, sell, 1.0, quality, reasons_str, factors

def build_factors_for_tag(tag: str, rarity: str, quality: int, is_num: bool, num_x: float) -> list[dict]:
    factors = []
    clean = tag.replace("@", "").replace("+888 ", "").replace(" ", "")

    if is_num:
        if len(clean) == 4 and clean.startswith("0"):
            factors.append({"label": "Ультра-короткая серия «0XXX»", "mult": "×250"})
        if "777" in clean or "888" in clean or "999" in clean:
            factors.append({"label": "Три одинаковые цифры подряд", "mult": "×18"})
        elif "00" in clean or "77" in clean or "88" in clean:
            factors.append({"label": "2 одинаковые цифры", "mult": "×2,4"})
        factors.append({"label": "Множитель к доходу каналов", "mult": f"×{num_x}"})
        factors.append({"label": f"Индекс редкости внутри {rarity}", "mult": f"×{round(1.0 + quality/100, 2)}".replace(".", ",")})
    else:
        base_word = "".join(c for c in clean if c.isalpha())
        digits = "".join(c for c in clean if c.isdigit())
        if base_word in WORD_LORE:
            lbl, m = WORD_LORE[base_word]
            factors.append({"label": lbl, "mult": m})
        else:
            factors.append({"label": f"Читаемый корень «{base_word[:8]}»", "mult": f"×{round(1.1 + quality/120, 1)}".replace(".", ",")})

        if "_" not in tag and not digits:
            if len(base_word) <= 4:
                factors.append({"label": f"Ультра-короткий тег ({len(base_word)} симв. без цифр)", "mult": "×15,0"})
            elif len(base_word) == 5:
                factors.append({"label": "Чистый 5-буквенный ник (Без цифр и _)", "mult": "×8,5"})
            else:
                factors.append({"label": f"Чистые буквы без цифр ({len(base_word)} симв.)", "mult": "×4,0"})
        else:
            factors.append({"label": f"Индекс редкости внутри {rarity}", "mult": f"×{round(1.0 + quality/100, 2)}".replace(".", ",")})

    return factors

def generate_phone_number(r_obj: dict):
    rarity_name = r_obj["name"]
    num_x = r_obj["num_x"]
    quality = random.randint(8, 99)

    if rarity_name == "Divine":
        tag = f"+888 0{random.choice(['001','007','777','888','999'])} {random.randint(10,99)}"
        quality = random.randint(92, 100)
    elif rarity_name == "Exclusive":
        d = random.choice(["7", "8", "9", "0"])
        tag = f"+888 {d*4} {random.randint(100,999)}"
    elif rarity_name == "Ultra-Mythic":
        d1 = random.choice(["7", "8", "9"])
        tag = f"+888 {d1*3}{random.randint(0,9)} {random.randint(100,999)}"
    elif rarity_name == "Luxury":
        d = random.choice(["777", "888", "999"])
        tag = f"+888 0{d} {random.randint(100,999)}"
    elif rarity_name == "Mythic":
        d = random.choice(["777", "888", "999"])
        tag = f"+888 {random.randint(10, 99)}00 {d}"
    elif rarity_name == "Legendary":
        tag = f"+888 {random.randint(10,99)}77 {random.randint(100,999)}"
    elif rarity_name == "Epic":
        a, b = random.randint(1, 9), random.randint(1, 9)
        tag = f"+888 {a}{a}{b}{b} {random.randint(100,999)}"
    elif rarity_name == "Rare":
        a = random.randint(10, 99)
        tag = f"+888 {a}{a} {random.randint(100,999)}"
    elif rarity_name == "Uncommon":
        tag = f"+888 {random.randint(100,999)}0 {random.randint(10,99)}0"
    else:
        tag = f"+888 {random.randint(1000,9999)} {random.randint(100,999)}"

    sell, inc = calc_range_price(r_obj, quality, item_type="number")
    factors = build_factors_for_tag(tag, rarity_name, quality, True, num_x)
    reasons_str = "|".join(f"{f['label']} {f['mult']}" for f in factors)
    return tag, inc, sell, num_x, quality, reasons_str, factors

# ==========================================
# СВЕРХБЫСТРАЯ ГЕНЕРАЦИЯ В ОПЕРАТИВНОЙ ПАМЯТИ (0 ЗАПРОСОВ В БД ВНУТРИ ЦИКЛА!)
# ==========================================
def fast_build_item_in_memory(item_type: str, rar_idx: int, luck: float = 1.0):
    picked = RARITIES[rar_idx]
    rarity = picked["name"]

    if item_type == "number":
        tag, inc, sell, num_x, qual, reas_str, factors = generate_phone_number(picked)
        return {
            "tag": tag, "type": "number", "rarity": rarity, "rar_idx": rar_idx, "quality": qual,
            "inc": inc, "xp": picked["xp"] * 2, "sell": sell, "num_multi": num_x,
            "reasons": reas_str, "factors": factors
        }

    if item_type == "gift":
        tag, inc, sell, num_x, qual, reas_str, factors = generate_nft_gift(picked)
        return {
            "tag": tag, "type": "gift", "rarity": rarity, "rar_idx": rar_idx, "quality": qual,
            "inc": inc, "xp": picked["xp"] * 2, "sell": sell, "num_multi": num_x,
            "reasons": reas_str, "factors": factors
        }

    min_q = min(85, int(10 + (luck - 1.0) * 12))
    quality = random.randint(min_q, 99)

    if rarity in ["Divine", "Exclusive", "Ultra-Mythic", "Luxury", "Mythic", "Legendary"]:
        base_w = random.choice(WORDS.get(rarity, ["king"]))
        tag = f"@{base_w}"
        quality = max(65, 100 - len(base_w) * 3 + random.randint(0, 15))
    elif rarity == "Epic":
        if random.random() < 0.45:
            base5 = generate_live_nickname()[:5]
            tag = f"@{base5}"
            quality = random.randint(82, 99)
        else:
            base_w = random.choice(WORDS["Epic"])
            tag = f"@{base_w}{random.randint(1, 9)}"
    elif rarity == "Rare":
        base_w = random.choice(WORDS["Rare"])
        tag = f"@{base_w}_{random.choice(['vip', 'ton', 'pro', 'hq'])}{random.randint(1,9)}"
    elif rarity == "Uncommon":
        base = generate_live_nickname()
        tag = f"@{base}{random.randint(10, 99)}"
    else:
        base = generate_live_nickname()
        tag = f"@{base}{random.randint(100, 9999)}"

    sell, inc = calc_range_price(picked, quality, item_type="username")
    factors = build_factors_for_tag(tag, rarity, quality, False, 1.0)
    reas_str = "|".join(f"{f['label']} {f['mult']}" for f in factors)
    return {
        "tag": tag, "type": "username", "rarity": rarity, "rar_idx": rar_idx, "quality": quality,
        "inc": inc, "xp": picked["xp"], "sell": sell, "num_multi": 1.0,
        "reasons": reas_str, "factors": factors
    }

def roll_single_candidate_fast(item_type: str, tier_key: str, luck: float):
    min_idx = SPIN_TIERS.get(tier_key, SPIN_TIERS["tier_0"])["min_idx"]
    pool_r = []
    total_w = 0
    for i, r in enumerate(RARITIES):
        if i < min_idx:
            continue
        dist = i - min_idx
        if min_idx == 0:
            base_w = r["w"]
        else:
            decay_weights = [880000, 95000, 18000, 3800, 750, 160, 35, 8, 2, 1]
            base_w = decay_weights[min(dist, len(decay_weights) - 1)]

        effective_luck = 1.0 if dist == 0 else float(max(1.0, luck))
        w = max(1, int(base_w * effective_luck))
        pool_r.append({"idx": i, "w": w})
        total_w += w

    rnd = random.random() * total_w
    rar_idx = pool_r[-1]["idx"]
    for p in pool_r:
        if rnd < p["w"]:
            rar_idx = p["idx"]
            break
        rnd -= p["w"]

    rar_idx = max(min_idx, rar_idx)
    return fast_build_item_in_memory(item_type, rar_idx, luck)

def ensure_unique_tag_once(cur, cand: dict):
    """Всего 1 быстрая проверка в БД вместо 10 циклов!"""
    cur.execute("SELECT 1 FROM usernames WHERE tag = ?", (cand["tag"],))
    if cur.fetchone():
        suf = random.randint(10, 99)
        if cand["type"] == "username":
            cand["tag"] = f"{cand['tag']}_{suf}"
        elif cand["type"] == "number":
            cand["tag"] = f"{cand['tag']} #{suf}"
        else:
            cand["tag"] = f"{cand['tag']}{suf}"
    return cand

def get_clan_bonus_multiplier(cur, clan_id: str) -> float:
    if not clan_id: return 1.0
    cur.execute("SELECT level, members_count FROM clans WHERE clan_id = ?", (clan_id,))
    row = cur.fetchone()
    if not row: return 1.0
    lvl, mems = row
    bonus_pct = 5.0 + (lvl * 1.5) + min(25.0, mems * 0.3)
    return 1.0 + (bonus_pct / 100.0)

def settle_expired_auctions(cur):
    now = int(time.time())
    cur.execute("SELECT lot_id, tag, item_type, rarity, income_per_sec, num_multi, reasons, seller_id, current_price, highest_bidder_id FROM market_lots WHERE ends_at <= ?", (now,))
    for lot in cur.fetchall():
        lid, tag, itype, rar, inc, num_m, reas, seller_id, price, winner_id = lot
        if winner_id:
            cur.execute("""
                INSERT OR REPLACE INTO usernames (tag, item_type, owner_id, rarity, quality_pct, income_per_sec, sell_price, num_multi, reasons, is_equipped, channel_slot, is_saved, on_market, created_at)
                VALUES (?, ?, ?, ?, 80, ?, ?, ?, ?, 0, 0, 1, 0, ?)
            """, (tag, itype, winner_id, rar, min(200.0, inc), round(price * 0.8, 0), min(3.5, num_m or 1.2), reas, now))
            if seller_id and seller_id > 0:
                cur.execute("UPDATE users SET balance = balance + ? WHERE tg_user_id = ?", (round(price * 0.95, 2), seller_id))
        else:
            if seller_id and seller_id > 0:
                cur.execute("UPDATE usernames SET on_market = 0, is_saved = 1 WHERE tag = ? AND owner_id = ?", (tag, seller_id))
        cur.execute("DELETE FROM market_lots WHERE lot_id = ?", (lid,))

def auto_sell_unsaved(cur, user_id: int) -> float:
    cur.execute("SELECT SUM(sell_price) FROM usernames WHERE owner_id = ? AND is_saved = 0 AND on_market = 0 AND is_staked = 0", (user_id,))
    val = cur.fetchone()[0]
    if val and val > 0:
        cur.execute("UPDATE users SET balance = balance + ? WHERE tg_user_id = ?", (val, user_id))
        cur.execute("DELETE FROM usernames WHERE owner_id = ? AND is_saved = 0 AND on_market = 0 AND is_staked = 0", (user_id,))
        return float(val)
    return 0.0

def process_passive_income(cur, user_id: int):
    now = int(time.time())
    cur.execute("SELECT balance, last_claim, smm_lvl, buyer_lvl, ai_boost, vip_until, clan_id, ref_by, tax_shield_until FROM users WHERE tg_user_id = ?", (user_id,))
    u = cur.fetchone()
    if not u: return 0.0
    balance, last_claim, smm, buyer, ai_b, vip_until, clan_id, ref_by, tax_until = u
    if last_claim <= 0:
        cur.execute("UPDATE users SET last_claim = ? WHERE tg_user_id = ?", (now, user_id))
        return 0.0
    elapsed = min(max(0, now - last_claim), 43200)
    if elapsed < 2: return 0.0

    cur.execute("SELECT SUM(LEAST(income_per_sec, 200.0)) FROM usernames WHERE owner_id = ? AND is_equipped = 1 AND channel_slot < 90 AND is_saved = 1 AND on_market = 0 AND is_staked = 0" if cur.is_pg else "SELECT SUM(MIN(income_per_sec, 200.0)) FROM usernames WHERE owner_id = ? AND is_equipped = 1 AND channel_slot < 90 AND is_saved = 1 AND on_market = 0 AND is_staked = 0", (user_id,))
    ch_inc = min(1000.0, float(cur.fetchone()[0] or 0.0))

    cur.execute("SELECT MAX(num_multi), SUM(income_per_sec) FROM usernames WHERE owner_id = ? AND is_equipped = 1 AND channel_slot = 99 AND is_saved = 1 AND on_market = 0 AND is_staked = 0", (user_id,))
    num_row = cur.fetchone()
    num_mult = min(3.5, float(num_row[0] or 1.0))
    num_direct = min(200.0, float(num_row[1] or 0.0))

    mgr_mult = (1.0 + smm * 0.04) * (1.0 + buyer * 0.08) * (1.35 if ai_b > 0 else 1.0)
    base_total = ((ch_inc * mgr_mult * num_mult) if ch_inc > 0 else 0.0) + (num_direct * mgr_mult * 0.15)

    if vip_until > now:
        base_total *= 1.35
    if clan_id:
        base_total *= get_clan_bonus_multiplier(cur, clan_id)
    if vip_until <= now and tax_until <= now:
        base_total *= 0.75

    # ЖЕСТКИЙ ПОТОЛОК ПАССИВНОГО ДОХОДА: максимум 2,500 GRAM/сек (никаких 27 млн/сек!)
    base_total = min(2500.0, base_total)

    earned = round(base_total * elapsed, 2)
    cur.execute("UPDATE users SET balance = balance + ?, last_claim = ? WHERE tg_user_id = ?", (earned, now, user_id))

    if earned > 0 and ref_by:
        ref_cut = round(earned * 0.10, 2)
        cur.execute("UPDATE users SET balance = balance + ? WHERE tg_user_id = ?", (ref_cut, ref_by))
        cur.execute("UPDATE users SET contrib_gram = contrib_gram + ? WHERE tg_user_id = ?", (ref_cut, user_id))

    return earned

# ==========================================
# МОДЕЛИ ЗАПРОСОВ
# ==========================================
class ReqLogin(BaseModel): user_id: int; username: str = "Player"; ref_by: str = ""; init_data: str = ""
class ReqMint(BaseModel): user_id: int; item_type: str = "username"; tier: str = "tier_0"; spin_count: int = 1; auto_save_min_idx: int = 0; init_data: str = ""
class ReqCaseOpen(BaseModel): user_id: int; case_key: str
class ReqAction(BaseModel): user_id: int; tag: str; action_type: str; slot: int = 0; init_data: str = ""
class ReqCraft(BaseModel): user_id: int; tags: list[str]; init_data: str = ""
class ReqDuel(BaseModel): user_id: int; tag: str; bet: float
class ReqUpgradeItem(BaseModel): user_id: int; tag: str; target_mult: int
class ReqCrashBet(BaseModel): user_id: int; bet: float; target_x: float = 2.0
class ReqRocketCashout(BaseModel): user_id: int; current_x: float
class ReqVaultHack(BaseModel): user_id: int; cell: int
class ReqMinesPlay(BaseModel): user_id: int; mode: str = "gram"; bet: float = 1000.0; tag: str = ""; bombs: int = 5; steps: int = 3
class ReqJackpotWheel(BaseModel): user_id: int; tag: str = ""; bet: float = 0.0
class ReqBankStake(BaseModel): user_id: int; stake_type: str = "item"; tag: str = ""; amount: float = 0.0; hours: int = 6
class ReqBankClaim(BaseModel): user_id: int; stake_id: int
class ReqCheckCreate(BaseModel): user_id: int; amount: float
class ReqMarketCreate(BaseModel): user_id: int; username: str; tag: str; is_auction: int; price: float; hours: int = 3
class ReqMarketInteract(BaseModel): user_id: int; username: str; lot_id: int; act: str
class ReqSimple(BaseModel): user_id: int; key: str = ""
class ReqClanCreate(BaseModel): user_id: int; name: str
class ReqClanAction(BaseModel): user_id: int; clan_id: str = ""; amount: float = 0.0

@app.get("/")
def serve_index():
    if os.path.exists("index.html"): return FileResponse("index.html")
    return HTMLResponse("<h2>index.html not found</h2>", status_code=404)

@app.get("/api/ping")
def api_ping():
    return {"status": "ok", "version": "v4_cases_rocket_live"}

@app.get("/api/check_sub/{uid}")
async def check_channel_sub(uid: int):
    is_sub = False
    try:
        member = await bot.get_chat_member(chat_id=NEWS_CHANNEL, user_id=uid)
        if member.status in ["member", "administrator", "creator"]:
            is_sub = True
    except Exception:
        is_sub = True

    if is_sub:
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT sub_verified FROM users WHERE tg_user_id = ?", (uid,))
        row = cur.fetchone()
        if row and row[0] == 0:
            cur.execute("UPDATE users SET sub_verified = 1, balance = balance + 15000.0 WHERE tg_user_id = ?", (uid,))
            conn.commit()
        conn.close()
    return {"subscribed": is_sub}

@app.post("/api/toggle_notify_merchant")
def toggle_notify_merchant(data: ReqSimple):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT notify_merchant FROM users WHERE tg_user_id = ?", (data.user_id,))
    row = cur.fetchone()
    new_val = 0 if (row and row[0] == 1) else 1
    cur.execute("UPDATE users SET notify_merchant = ? WHERE tg_user_id = ?", (new_val, data.user_id))
    conn.commit(); conn.close()
    return {"notify_merchant": new_val}

def apply_ref_bonus_and_check_3_friends(cur, ref_uid: int):
    now = int(time.time())
    cur.execute("SELECT refs_count, ref_3_rewarded, luck_until FROM users WHERE tg_user_id = ?", (ref_uid,))
    r_row = cur.fetchone()
    if not r_row:
        return
    old_cnt, r3_done, l_until = r_row
    nc = old_cnt + 1
    rew = 25000.0 if nc == 1 else (75000.0 if nc == 2 else (250000.0 if nc == 5 else (5000000.0 if nc == 20 else 35000.0)))
    cur.execute("UPDATE users SET refs_count = ?, balance = balance + ? WHERE tg_user_id = ?", (nc, rew, ref_uid))
    if nc >= 3 and (r3_done or 0) == 0:
        new_until = max(now, l_until or 0) + 10800
        cur.execute("UPDATE users SET luck_multi = GREATEST(luck_multi, 2.0), luck_until = ?, ref_3_rewarded = 1 WHERE tg_user_id = ?" if cur.is_pg else "UPDATE users SET luck_multi = MAX(luck_multi, 2.0), luck_until = ?, ref_3_rewarded = 1 WHERE tg_user_id = ?", (new_until, ref_uid))

@app.post("/api/login")
def login(data: ReqLogin):
    check_rate(data.user_id, 15, 3.0)
    verify_tg_auth(data.init_data, data.user_id)
    conn = get_db(); cur = conn.cursor()
    now = int(time.time())

    parsed_ref = None
    raw_r = (data.ref_by or "").strip()
    if raw_r.startswith("ref_"):
        try: parsed_ref = int(raw_r.split("_")[1])
        except Exception: pass
    elif raw_r.startswith("r") and raw_r[1:].isdigit():
        parsed_ref = int(raw_r[1:])
    elif raw_r.isdigit():
        parsed_ref = int(raw_r)

    cur.execute("SELECT ref_by FROM users WHERE tg_user_id = ?", (data.user_id,))
    existing = cur.fetchone()

    if not existing:
        valid_ref = None
        if parsed_ref and parsed_ref != data.user_id:
            cur.execute("SELECT 1 FROM users WHERE tg_user_id = ?", (parsed_ref,))
            if cur.fetchone():
                valid_ref = parsed_ref
                apply_ref_bonus_and_check_3_friends(cur, valid_ref)
        start_bal = 35000.0 if valid_ref else 15000.0
        cur.execute("""
            INSERT INTO users (tg_user_id, username, balance, level, xp, ref_by, tax_shield_until, last_claim, created_at)
            VALUES (?, ?, ?, 1, 0, ?, ?, ?, ?)
        """, (data.user_id, data.username, start_bal, valid_ref, now + 7200, now, now))
    else:
        if existing[0] is None and parsed_ref and parsed_ref != data.user_id:
            cur.execute("SELECT 1 FROM users WHERE tg_user_id = ?", (parsed_ref,))
            if cur.fetchone():
                apply_ref_bonus_and_check_3_friends(cur, parsed_ref)
                cur.execute("UPDATE users SET ref_by = ?, balance = balance + 15000.0 WHERE tg_user_id = ?", (parsed_ref, data.user_id))
        cur.execute("UPDATE users SET username = ? WHERE tg_user_id = ?", (data.username, data.user_id))
        auto_sell_unsaved(cur, data.user_id)
        process_passive_income(cur, data.user_id)

    conn.commit(); conn.close()
    return {"status": "ok"}

@app.get("/api/state/{uid}")
def get_state(uid: int):
    conn = get_db(); cur = conn.cursor()
    now = int(time.time())
    settle_expired_auctions(cur)
    process_passive_income(cur, uid)
    conn.commit()

    cur.execute("""
        SELECT member_number, balance, level, xp, season_xp, season_claimed, smm_lvl, buyer_lvl, ai_boost,
               luck_multi, luck_until, vip_until, max_hold, max_channels, refs_count, ref_3_rewarded, clan_id,
               total_spins, pity_100, pity_500, last_wheel, last_vault, daily_streak, last_daily,
               q_spins, q_rare, q_crafts, q_duels, q_claimed, ach_stats, ach_claimed,
               albums_claimed, contracts_done, tax_shield_until, duel_wins, auto_save_min_idx, sub_verified, notify_merchant
        FROM users WHERE tg_user_id = ?
    """, (uid,))
    u = cur.fetchone()
    if not u:
        conn.close(); raise HTTPException(404, "User not found")

    (mem_num, bal, lvl, xp, s_xp, s_cl, smm, buyer, ai_b, luck_m, luck_u, vip_u, max_h, max_ch,
     refs, ref3_rew, clan_id, tot_spins, p100, p500, l_wheel, l_vault, d_streak, l_daily, qs, qr, qc, qd, q_cl,
     a_st, a_cl, alb_cl, cnt_done, tax_u, d_wins, auto_idx, sub_v, notif_m) = u

    cur.execute("""
        SELECT tag, item_type, rarity, quality_pct, income_per_sec, sell_price, num_multi, reasons,
               is_equipped, channel_slot, is_staked, is_verified, last_duel_at
        FROM usernames WHERE owner_id = ? AND is_saved = 1 AND on_market = 0
        ORDER BY sell_price DESC
    """, (uid,))
    tags = [{
        "tag": r[0], "type": r[1] or "username", "rarity": r[2], "q": r[3] or 50,
        "inc": min(200.0, float(r[4] or 0.1)), "sell": r[5],
        "num_x": min(3.5, float(r[6] or 1.1)), "reasons": r[7].split("|") if r[7] else [],
        "eq": r[8], "slot": r[9], "staked": r[10] or 0, "verified": r[11] or 0,
        "duel_cd": max(0, (int(r[12] or 0) + 120) - now)
    } for r in cur.fetchall()]

    cur.execute("""
        SELECT stake_id, stake_type, tag, principal_gram, reward_gram, hours, unlocks_at
        FROM staked_deposits WHERE user_id = ? AND claimed = 0 ORDER BY stake_id DESC
    """, (uid,))
    stakes = [{
        "id": r[0], "type": r[1], "tag": r[2], "principal": r[3],
        "reward": r[4], "hours": r[5], "left": max(0, r[6] - now)
    } for r in cur.fetchall()]

    cur.execute("SELECT username, level, contrib_gram, contrib_stars FROM users WHERE ref_by = ? ORDER BY contrib_gram DESC LIMIT 50", (uid,))
    referrals_list = [{
        "username": r[0] or "Игрок", "level": r[1],
        "gram": round(r[2] or 0.0, 0), "stars": r[3] or 0
    } for r in cur.fetchall()]

    cur.execute("SELECT COUNT(*) + 1 FROM users WHERE balance > ?", (bal,))
    my_rank = cur.fetchone()[0]

    cur.execute("SELECT username, balance, level, duel_wins FROM users ORDER BY balance DESC LIMIT 20")
    leaders = [{"username": r[0] or "Магнат", "balance": round(r[1], 0), "level": r[2], "wins": r[3] or 0} for r in cur.fetchall()]

    cur.execute("SELECT clan_id, name, owner_id, level, treasury, members_count, max_members FROM clans ORDER BY level DESC, treasury DESC")
    clans = [{
        "id": r[0], "name": r[1], "owner_id": r[2], "level": r[3],
        "treasury": round(r[4], 0), "members": r[5], "max_members": r[6],
        "bonus": round(5.0 + (r[3] * 1.5) + min(25.0, r[5] * 0.3), 1)
    } for r in cur.fetchall()]

    cur.execute("""
        SELECT lot_id, tag, item_type, rarity, income_per_sec, num_multi, reasons, seller_id, seller_name,
               is_auction, current_price, buyout_price, highest_bidder_id, highest_bidder_name, bids_count, ends_at
        FROM market_lots WHERE ends_at > ? ORDER BY created_at DESC LIMIT 50
    """, (now,))
    market = [{
        "lot_id": r[0], "tag": r[1], "type": r[2], "rarity": r[3], "inc": min(200.0, float(r[4] or 0.1)),
        "num_x": min(3.5, float(r[5] or 1.1)),
        "reasons": r[6].split("|") if r[6] else [], "seller_id": r[7], "seller_name": r[8],
        "is_auction": r[9], "price": r[10], "buyout": r[11], "bidder_id": r[12],
        "bidder_name": r[13], "bids": r[14], "left": max(0, r[15] - now)
    } for r in cur.fetchall()]

    conn.close()
    is_vip = vip_u > now
    active_luck = (luck_m if luck_u > now else 1.0) * (1.35 if is_vip else 1.0)
    actual_refs = max(refs, len(referrals_list))

    return {
        "member_number": mem_num, "balance": round(bal, 2), "level": lvl, "xp": xp,
        "season_xp": s_xp, "season_claimed": json.loads(s_cl or "[]"),
        "smm": smm, "smm_max": MAX_SMM_LVL, "smm_cost": get_smm_upgrade_cost(smm),
        "buyer": buyer, "buyer_max": MAX_BUYER_LVL, "buyer_cost": get_buyer_upgrade_cost(buyer),
        "ai_boost": ai_b, "luck_multi": round(active_luck, 2), "luck_left": max(0, (luck_u or 0) - now),
        "is_vip": is_vip, "max_hold": max_h, "max_channels": max_ch,
        "refs_count": actual_refs, "ref_3_done": (ref3_rew or 0) == 1 or actual_refs >= 3,
        "referrals_list": referrals_list,
        "clan_id": clan_id, "total_spins": tot_spins, "pity_100": p100, "pity_500": p500,
        "wheel_wait": max(0, (l_wheel + 1800) - now),
        "vault_wait": max(0, ((l_vault or 0) + 3600) - now),
        "daily_streak": d_streak, "can_daily": (now - l_daily) >= 86400,
        "quests": {"spins": qs, "rare": qr, "crafts": qc, "duels": qd or 0, "claimed": json.loads(q_cl or "[]")},
        "ach": {"stats": json.loads(a_st or "{}"), "claimed": json.loads(a_cl or "[]")},
        "albums_claimed": json.loads(alb_cl or "[]"),
        "contracts": get_daily_vip_contracts(),
        "contracts_done": json.loads(cnt_done or "[]"),
        "stakes": stakes,
        "tax_active": (vip_u <= now and (tax_u or 0) <= now),
        "tax_shield_left": max(0, (tax_u or 0) - now),
        "duel_wins": d_wins or 0,
        "hot_series": get_daily_hot_series(),
        "merchant": get_active_merchant_offer(),
        "notify_merchant": (notif_m or 0) == 1,
        "auto_save_min_idx": auto_idx, "sub_verified": sub_v,
        "my_rank": my_rank, "leaders": leaders, "clans": clans, "tags": tags, "market": market
    }

# ==========================================
# МГНОВЕННЫЙ ПРОКРУТ (БЕЗ ЦИКЛОВ SELECT — 0.02 СЕК!)
# ==========================================
def execute_spins_internal(cur, user_id: int, item_type: str, tier: str, count: int, cost: float, auto_save_min_idx: int = 0):
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
    base_luck = (luck_m if luck_u > now else 1.0) * (1.35 if is_vip else 1.0)
    ach_stats = json.loads(ach_raw or "{}")

    drops = []
    added_xp = 0
    for _ in range(count):
        tot_s += 1; p100 += 1; p500 += 1; qs += 1; s_xp += 2

        choice_pool = 1
        pity_factor = None
        if p500 >= 500:
            choice_pool = 25; p500 = 0; p100 = 0
            pity_factor = {"label": "Гарант 500-го броска (Лучший из 25)", "mult": "×25"}
        elif p100 >= 100:
            choice_pool = 5; p100 = 0
            pity_factor = {"label": "Гарант 100-го броска (Лучший из 5)", "mult": "×5"}

        # Генерируем кандидатов в оперативной памяти БЕЗ запросов к БД (0 мс!)
        best_cand = None
        for _ in range(choice_pool):
            c_try = roll_single_candidate_fast(item_type, tier, base_luck)
            if best_cand is None or c_try["sell"] > best_cand["sell"]:
                best_cand = c_try

        cand = ensure_unique_tag_once(cur, best_cand)

        if cand["rar_idx"] >= 2:
            qr += 1
        ach_stats[cand["rarity"]] = ach_stats.get(cand["rarity"], 0) + 1

        save_flag = 0
        if cand["rar_idx"] >= auto_save_min_idx and cur_hold_cnt < max_h:
            save_flag = 1
            cur_hold_cnt += 1

        cur.execute("""
            INSERT OR IGNORE INTO usernames (tag, item_type, owner_id, rarity, quality_pct, income_per_sec, sell_price, num_multi, reasons, is_equipped, channel_slot, is_saved, on_market, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, 0, ?)
        """, (cand["tag"], cand["type"], user_id, cand["rarity"], cand["quality"], cand["inc"], cand["sell"], cand["num_multi"], cand["reasons"], save_flag, now))

        factors_out = list(cand.get("factors", []))
        if pity_factor:
            factors_out.insert(0, pity_factor)

        drops.append({
            "tag": cand["tag"], "type": cand["type"], "rarity": cand["rarity"], "rar_idx": cand["rar_idx"],
            "q": cand["quality"], "inc": cand["inc"], "xp": cand["xp"], "sell": cand["sell"],
            "num_x": cand["num_multi"], "auto_saved": save_flag == 1,
            "reasons": cand["reasons"].split("|"), "factors": factors_out
        })
        added_xp += cand["xp"]

    new_bal = round(bal - cost, 2)
    new_xp = xp + added_xp
    new_lvl = lvl
    while new_xp >= new_lvl * 150:
        new_xp -= new_lvl * 150
        new_lvl += 1

    cur.execute("""
        UPDATE users SET balance = ?, level = ?, xp = ?, season_xp = ?, total_spins = ?,
                         pity_100 = ?, pity_500 = ?, q_spins = ?, q_rare = ?, ach_stats = ?, auto_save_min_idx = ?
        WHERE tg_user_id = ?
    """, (new_bal, new_lvl, new_xp, s_xp, tot_s, p100, p500, qs, qr, json.dumps(ach_stats), auto_save_min_idx, user_id))

    return drops, new_bal

@app.post("/api/mint")
def mint(data: ReqMint):
    check_rate(data.user_id, 12, 2.0)
    verify_tg_auth(data.init_data, data.user_id)
    if data.tier not in SPIN_TIERS: raise HTTPException(400, "Неверный тир прокрутки")
    if data.spin_count not in [1, 5]: raise HTTPException(400, "За GRAM доступно 1x или 5x")
    if data.user_id in TX_LOCKS: raise HTTPException(429, "Операция уже выполняется")

    TX_LOCKS.add(data.user_id)
    conn = get_db(); cur = conn.cursor()
    try:
        auto_sold = auto_sell_unsaved(cur, data.user_id)
        tier_info = SPIN_TIERS[data.tier]
        unit_cost = tier_info["n_cost"] if data.item_type == "number" else tier_info["u_cost"]
        total_cost = unit_cost * data.spin_count
        drops, new_bal = execute_spins_internal(cur, data.user_id, data.item_type, data.tier, data.spin_count, total_cost, data.auto_save_min_idx)
        conn.commit()
        return {"drops": drops, "auto_sold": auto_sold, "balance": new_bal}
    finally:
        TX_LOCKS.discard(data.user_id)
        conn.close()

# ==========================================
# ОТКРЫТИЕ КЕЙСОВ CS:GO (0 ЗАДЕРЖЕК + ДУБЛИРУЮЩИЕ АЛИАСЫ ОТ 404)
# ==========================================
def roll_case_drop_fast(cur, case_key: str, luck: float = 1.0):
    c_info = CASES_CATALOG[case_key]
    itype = random.choice(c_info["types"])
    w_map = c_info["weights"]
    pool_c = []
    tot = 0
    min_r = min(w_map.keys())
    for r_idx, w_val in w_map.items():
        eff_w = int(w_val * (luck if r_idx > min_r else 1.0))
        pool_c.append((r_idx, eff_w))
        tot += eff_w

    rnd = random.random() * tot
    picked_idx = pool_c[-1][0]
    for r_idx, ew in pool_c:
        if rnd < ew:
            picked_idx = r_idx
            break
        rnd -= ew

    cand = ensure_unique_tag_once(cur, fast_build_item_in_memory(itype, picked_idx, luck))

    # Генерируем 28 карточек ленты CS:GO в оперативной памяти за 0.0001 сек (без БД!)
    tape = []
    for _ in range(28):
        f_idx = random.choice(list(w_map.keys()))
        f_type = random.choice(c_info["types"])
        f_item = fast_build_item_in_memory(f_type, f_idx, 1.0)
        tape.append({"tag": f_item["tag"], "rarity": f_item["rarity"], "type": f_type, "sell": f_item["sell"]})
    return cand, tape

@app.post("/api/cases/open")
@app.post("/api/case_open")
def open_case_gram(data: ReqCaseOpen):
    check_rate(data.user_id, 10, 2.0)
    if data.case_key not in CASES_CATALOG:
        raise HTTPException(400, "Кейс не найден")
    c_info = CASES_CATALOG[data.case_key]
    if c_info["curr"] != "gram":
        raise HTTPException(400, "Этот кейс открывается за Telegram Stars!")

    conn = get_db(); cur = conn.cursor()
    now = int(time.time())
    cur.execute("SELECT balance, luck_multi, luck_until, vip_until, max_hold FROM users WHERE tg_user_id = ?", (data.user_id,))
    bal, luck_m, luck_u, vip_u, max_h = cur.fetchone()
    if bal < c_info["price"]:
        conn.close(); raise HTTPException(400, f"Недостаточно средств: нужно {c_info['price']:,} GRAM")

    cur.execute("SELECT COUNT(*) FROM usernames WHERE owner_id = ? AND is_saved = 1 AND on_market = 0", (data.user_id,))
    if cur.fetchone()[0] >= max_h:
        conn.close(); raise HTTPException(400, f"Сейф полон ({max_h} мест)! Освободите место.")

    eff_luck = (luck_m if luck_u > now else 1.0) * (1.35 if vip_u > now else 1.0)
    cand, tape = roll_case_drop_fast(cur, data.case_key, eff_luck)

    cur.execute("""
        INSERT OR IGNORE INTO usernames (tag, item_type, owner_id, rarity, quality_pct, income_per_sec, sell_price, num_multi, reasons, is_equipped, channel_slot, is_saved, on_market, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 1, 0, ?)
    """, (cand["tag"], cand["type"], data.user_id, cand["rarity"], cand["quality"], cand["inc"], cand["sell"], cand["num_multi"], cand["reasons"], now))

    new_bal = round(bal - c_info["price"], 2)
    cur.execute("UPDATE users SET balance = ?, season_xp = season_xp + 20 WHERE tg_user_id = ?", (new_bal, data.user_id))
    conn.commit(); conn.close()

    return {
        "winner": {
            "tag": cand["tag"], "type": cand["type"], "rarity": cand["rarity"], "rar_idx": cand["rar_idx"],
            "q": cand["quality"], "inc": cand["inc"], "sell": cand["sell"], "num_x": cand["num_multi"],
            "reasons": cand["reasons"].split("|"), "eq": 0, "slot": 0, "staked": 0, "verified": 0, "duel_cd": 0
        },
        "tape": tape,
        "balance": new_bal
    }

# ==========================================
# TON РАКЕТКА С ОСТАНОВКОЙ В ЛЮБОЙ МОМЕНТ (РУЧНОЙ CASH OUT + АВТО-ВЫВОД)
# ==========================================
def roll_rocket_crash_point() -> float:
    r = random.random()
    if r < 0.08:
        return 1.00
    raw_x = 0.92 / ((1.0 - r) ** 1.18)
    return round(min(1200.0, max(1.01, raw_x)), 2)

@app.post("/api/minigame/rocket/start")
def rocket_start_flight(data: ReqCrashBet):
    check_rate(data.user_id, 8, 2.0)
    if data.bet < 200:
        raise HTTPException(400, "Минимальная ставка — 200 GRAM")
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT balance FROM users WHERE tg_user_id = ?", (data.user_id,))
    bal = cur.fetchone()[0]
    if bal < data.bet:
        conn.close(); raise HTTPException(400, "Недостаточно GRAM для старта!")

    new_bal = round(bal - data.bet, 2)
    cur.execute("UPDATE users SET balance = ?, season_xp = season_xp + 5 WHERE tg_user_id = ?", (new_bal, data.user_id))
    conn.commit(); conn.close()

    crash_x = roll_rocket_crash_point()
    ACTIVE_ROCKETS[data.user_id] = {
        "bet": data.bet,
        "crash_x": crash_x,
        "target_x": max(1.05, min(1200.0, data.target_x or 1000.0)),
        "started_at": time.time(),
        "cashed": False
    }
    return {"status": "flying", "crash_x": crash_x, "balance": new_bal}

@app.post("/api/minigame/rocket/cashout")
def rocket_manual_cashout(data: ReqRocketCashout):
    sess = ACTIVE_ROCKETS.get(data.user_id)
    if not sess or sess.get("cashed"):
        raise HTTPException(400, "Активный полет уже завершен")

    claim_x = round(max(1.01, min(data.current_x, sess["crash_x"])), 2)
    if claim_x > sess["crash_x"] or sess["crash_x"] <= 1.00:
        ACTIVE_ROCKETS.pop(data.user_id, None)
        raise HTTPException(400, f"💥 Поздно! Ракета уже взорвалась на ×{sess['crash_x']}")

    sess["cashed"] = True
    ACTIVE_ROCKETS.pop(data.user_id, None)
    winnings = round(sess["bet"] * claim_x)

    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE users SET balance = balance + ?, season_xp = season_xp + 15 WHERE tg_user_id = ?", (winnings, data.user_id))
    cur.execute("SELECT balance FROM users WHERE tg_user_id = ?", (data.user_id,))
    new_bal = cur.fetchone()[0]
    conn.commit(); conn.close()

    return {
        "win": True,
        "cashed_x": claim_x,
        "crash_x": sess["crash_x"],
        "winnings": winnings,
        "balance": round(new_bal, 2),
        "message": f"💰 ВЫВЕДЕНО НА ×{claim_x}! Получено +{winnings:,} GRAM! (Ракета летела до ×{sess['crash_x']})"
    }

# Старый маршрут тоже оставлен для полной обратной совместимости
@app.post("/api/minigame/rocket")
def minigame_rocket_legacy(data: ReqCrashBet):
    st = rocket_start_flight(data)
    crash_x = st["crash_x"]
    if crash_x >= data.target_x:
        res = rocket_manual_cashout(ReqRocketCashout(user_id=data.user_id, current_x=data.target_x))
        return {"win": True, "crash_x": crash_x, "target_x": data.target_x, "message": res["message"], "balance": res["balance"]}
    else:
        ACTIVE_ROCKETS.pop(data.user_id, None)
        return {"win": False, "crash_x": crash_x, "target_x": data.target_x, "message": f"💥 ВЗРЫВ НА ×{crash_x}!", "balance": st["balance"]}

# ==========================================
# ХОЛД-БАНК (СТЕЙКИНГ ПРЕДМЕТОВ И GRAM ПОД ПРОЦЕНТЫ)
# ==========================================
STAKE_PLANS = {3: 0.12, 6: 0.25, 12: 0.45}

@app.post("/api/bank/stake")
def bank_stake_create(data: ReqBankStake):
    if data.hours not in STAKE_PLANS:
        raise HTTPException(400, "Доступные сроки Холда: 3, 6 или 12 часов")
    rate_pct = STAKE_PLANS[data.hours]
    now = int(time.time())
    unlocks = now + (data.hours * 3600)

    conn = get_db(); cur = conn.cursor()
    if data.stake_type == "item":
        cur.execute("SELECT sell_price, is_equipped, on_market, is_staked FROM usernames WHERE tag = ? AND owner_id = ? AND is_saved = 1", (data.tag, data.user_id))
        row = cur.fetchone()
        if not row:
            conn.close(); raise HTTPException(400, "Предмет не найден в Сейфе!")
        sell_p, is_eq, on_mkt, is_st = row
        if is_eq == 1 or on_mkt == 1 or is_st == 1:
            conn.close(); raise HTTPException(400, "Предмет должен быть свободен!")
        reward = round(sell_p * rate_pct)
        cur.execute("UPDATE usernames SET is_staked = 1 WHERE tag = ? AND owner_id = ?", (data.tag, data.user_id))
        cur.execute("""
            INSERT INTO staked_deposits (user_id, stake_type, tag, principal_gram, reward_gram, hours, unlocks_at, claimed, created_at)
            VALUES (?, 'item', ?, ?, ?, ?, ?, 0, ?)
        """, (data.user_id, data.tag, sell_p, reward, data.hours, unlocks, now))
    else:
        if data.amount < 5000:
            conn.close(); raise HTTPException(400, "Минимальный вклад в GRAM — 5,000 G")
        cur.execute("SELECT balance FROM users WHERE tg_user_id = ?", (data.user_id,))
        bal = cur.fetchone()[0]
        if bal < data.amount:
            conn.close(); raise HTTPException(400, "Недостаточно GRAM на балансе!")
        reward = round(data.amount * rate_pct)
        cur.execute("UPDATE users SET balance = balance - ? WHERE tg_user_id = ?", (data.amount, data.user_id))
        cur.execute("""
            INSERT INTO staked_deposits (user_id, stake_type, tag, principal_gram, reward_gram, hours, unlocks_at, claimed, created_at)
            VALUES (?, 'gram', '💰 Вклад GRAM', ?, ?, ?, ?, 0, ?)
        """, (data.user_id, data.amount, reward, data.hours, unlocks, now))

    conn.commit(); conn.close()
    return {"status": "ok", "reward": reward}

@app.post("/api/bank/claim")
def bank_stake_claim(data: ReqBankClaim):
    now = int(time.time())
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT stake_type, tag, principal_gram, reward_gram, unlocks_at, claimed FROM staked_deposits WHERE stake_id = ? AND user_id = ?", (data.stake_id, data.user_id))
    row = cur.fetchone()
    if not row or row[5] == 1:
        conn.close(); raise HTTPException(400, "Вклад не найден или уже забран")
    stype, tag, princ, rew, unl, _ = row
    if now < unl:
        left_m = int((unl - now) // 60) + 1
        conn.close(); raise HTTPException(400, f"Срок Холда ещё не вышел! Осталось {left_m} мин.")

    cur.execute("UPDATE staked_deposits SET claimed = 1 WHERE stake_id = ?", (data.stake_id,))
    if stype == "item":
        cur.execute("UPDATE usernames SET is_staked = 0 WHERE tag = ? AND owner_id = ?", (tag, data.user_id))
        cur.execute("UPDATE users SET balance = balance + ?, season_xp = season_xp + 25 WHERE tg_user_id = ?", (rew, data.user_id))
        msg = f"🏦 Холд завершен! Предмет {tag} возвращен в Сейф + выплачены дивиденды +{int(rew):,} GRAM!"
    else:
        total_ret = princ + rew
        cur.execute("UPDATE users SET balance = balance + ?, season_xp = season_xp + 25 WHERE tg_user_id = ?", (total_ret, data.user_id))
        msg = f"🏦 Вклад разморожен! Возвращено {int(princ):,} G + проценты +{int(rew):,} GRAM!"

    conn.commit(); conn.close()
    return {"status": "ok", "message": msg}

# ==========================================
# ТЮНИНГ И ВЕРИФИКАЦИЯ ГАЛОЧКОЙ (☑️ VERIFIED БЕЗ ПОЛОМКИ ДОХОДА)
# ==========================================
@app.post("/api/tune_item")
def tune_verify_item(data: ReqSimple):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT sell_price, income_per_sec, is_verified, reasons FROM usernames WHERE tag = ? AND owner_id = ? AND is_saved = 1", (data.key, data.user_id))
    row = cur.fetchone()
    if not row:
        conn.close(); raise HTTPException(400, "Предмет не найден в Сейфе")
    sell_p, inc, is_ver, reas = row
    if is_ver == 1:
        conn.close(); raise HTTPException(400, "Этот предмет уже верифицирован галочкой ☑️!")

    cost = max(5000, round(sell_p * 0.35))
    cur.execute("SELECT balance FROM users WHERE tg_user_id = ?", (data.user_id,))
    if cur.fetchone()[0] < cost:
        conn.close(); raise HTTPException(400, f"Для верификации галочкой нужно {cost:,} GRAM")

    new_sell = round(sell_p * 1.45)
    new_inc = min(200.0, round(inc * 1.25, 2))
    new_reas = (reas + "|☑️ Верификация Fragment ×1,45") if reas else "☑️ Верификация Fragment ×1,45"

    cur.execute("UPDATE users SET balance = balance - ?, season_xp = season_xp + 30 WHERE tg_user_id = ?", (cost, data.user_id))
    cur.execute("UPDATE usernames SET sell_price = ?, income_per_sec = ?, is_verified = 1, reasons = ? WHERE tag = ? AND owner_id = ?",
                (new_sell, new_inc, new_reas, data.key, data.user_id))
    conn.commit(); conn.close()
    return {"status": "ok", "new_sell": new_sell, "new_inc": new_inc, "cost": cost}

# ==========================================
# МИНИ-ИГРЫ: АПГРЕЙДЕР, САПЁР 5x5, РУЛЕТКА МАГНАТОВ, PVP-ДУЭЛИ
# ==========================================
UPGRADE_CHANCES = {2: 48, 3: 31, 5: 18, 10: 9}

@app.post("/api/minigame/upgrade")
def minigame_upgrade_item(data: ReqUpgradeItem):
    check_rate(data.user_id, 6, 2.0)
    if data.target_mult not in UPGRADE_CHANCES:
        raise HTTPException(400, "Выберите множитель апгрейда: ×2, ×3, ×5 или ×10")

    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT item_type, rarity, sell_price, is_equipped, on_market, is_staked FROM usernames WHERE tag = ? AND owner_id = ? AND is_saved = 1", (data.tag, data.user_id))
    row = cur.fetchone()
    if not row:
        conn.close(); raise HTTPException(400, "Предмет не найден в Сейфе!")
    itype, rar, old_sell, is_eq, on_mkt, is_st = row
    if is_eq == 1 or on_mkt == 1 or is_st == 1:
        conn.close(); raise HTTPException(400, "Сначала снимите предмет с канала/банка/рынка!")

    chance_pct = UPGRADE_CHANCES[data.target_mult]
    roll_deg = random.uniform(0, 360)
    win_sector_deg = (chance_pct / 100.0) * 360.0
    is_win = roll_deg <= win_sector_deg

    cur.execute("DELETE FROM usernames WHERE tag = ? AND owner_id = ?", (data.tag, data.user_id))

    if not is_win:
        cur.execute("UPDATE users SET season_xp = season_xp + 10 WHERE tg_user_id = ?", (data.user_id,))
        conn.commit(); conn.close()
        return {"win": False, "chance": chance_pct, "angle": round(roll_deg, 1), "message": f"💥 Промах! Стрелка остановилась вне зеленой зоны ({chance_pct}%). {data.tag} сгорел..."}

    target_value = round(old_sell * data.target_mult)
    old_idx = next((i for i, r in enumerate(RARITIES) if r["name"] == rar), 0)
    step_up = 1 if data.target_mult == 2 else (2 if data.target_mult == 3 else (3 if data.target_mult == 5 else 4))
    new_idx = min(len(RARITIES) - 1, old_idx + step_up)

    now = int(time.time())
    cand = ensure_unique_tag_once(cur, fast_build_item_in_memory(itype or "username", new_idx, 2.0))
    new_tag = cand["tag"]

    cur.execute("""
        INSERT OR IGNORE INTO usernames (tag, item_type, owner_id, rarity, quality_pct, income_per_sec, sell_price, num_multi, reasons, is_equipped, channel_slot, is_saved, on_market, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 1, 0, ?)
    """, (new_tag, cand["type"], data.user_id, cand["rarity"], cand["quality"], cand["inc"], target_value, cand["num_multi"], cand["reasons"], now))
    cur.execute("UPDATE users SET season_xp = season_xp + 35 WHERE tg_user_id = ?", (data.user_id,))

    conn.commit(); conn.close()
    return {
        "win": True, "chance": chance_pct, "angle": round(roll_deg, 1),
        "new_item": {"tag": new_tag, "type": cand["type"], "rarity": cand["rarity"], "sell": target_value, "inc": cand["inc"]},
        "message": f"🔥 АПГРЕЙД ×{data.target_mult} УСПЕШЕН! Получен {new_tag} стоимостью {target_value:,} GRAM!"
    }

@app.post("/api/minigame/mines")
def minigame_mines(data: ReqMinesPlay):
    check_rate(data.user_id, 6, 2.0)
    bombs = max(3, min(15, data.bombs))
    steps = max(1, min(25 - bombs, data.steps))

    conn = get_db(); cur = conn.cursor()
    stake_val = data.bet
    if data.mode == "item":
        cur.execute("SELECT sell_price, is_equipped, on_market, is_staked FROM usernames WHERE tag = ? AND owner_id = ? AND is_saved = 1", (data.tag, data.user_id))
        row = cur.fetchone()
        if not row or row[1] == 1 or row[2] == 1 or row[3] == 1:
            conn.close(); raise HTTPException(400, "Выберите свободный предмет из Сейфа!")
        stake_val = row[0]
        cur.execute("DELETE FROM usernames WHERE tag = ? AND owner_id = ?", (data.tag, data.user_id))
    else:
        if stake_val < 500:
            conn.close(); raise HTTPException(400, "Минимальная ставка — 500 GRAM")
        cur.execute("SELECT balance FROM users WHERE tg_user_id = ?", (data.user_id,))
        if cur.fetchone()[0] < stake_val:
            conn.close(); raise HTTPException(400, "Недостаточно GRAM!")
        cur.execute("UPDATE users SET balance = balance - ? WHERE tg_user_id = ?", (stake_val, data.user_id))

    survive_prob = 1.0
    for s in range(steps):
        survive_prob *= (25 - bombs - s) / (25 - s)

    mult = round((0.94 / survive_prob), 2)
    win = random.random() <= survive_prob

    if win:
        payout = round(stake_val * mult)
        cur.execute("UPDATE users SET balance = balance + ?, season_xp = season_xp + 20 WHERE tg_user_id = ?", (payout, data.user_id))
        msg = f"💎 САПЁР ПРОЙДЕН (×{mult})! Открыто {steps} кристаллов без мин! Выигрыш: +{payout:,} GRAM!"
    else:
        cur.execute("UPDATE users SET season_xp = season_xp + 5 WHERE tg_user_id = ?", (data.user_id,))
        msg = f"💣 ПОДРЫВ НА МИНЕ! Ты пытался открыть {steps} ячеек на множитель ×{mult}, но нарвался на бомбу."

    conn.commit(); conn.close()
    return {"win": win, "mult": mult, "payout": round(stake_val * mult) if win else 0, "message": msg}

@app.post("/api/minigame/jackpot")
def minigame_jackpot_wheel(data: ReqJackpotWheel):
    check_rate(data.user_id, 6, 2.0)
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT sell_price, is_equipped, on_market, is_staked FROM usernames WHERE tag = ? AND owner_id = ? AND is_saved = 1", (data.tag, data.user_id))
    row = cur.fetchone()
    if not row or row[1] == 1 or row[2] == 1 or row[3] == 1:
        conn.close(); raise HTTPException(400, "Выберите свободный предмет из Сейфа для взноса в Котел!")
    my_val = row[0]
    cur.execute("DELETE FROM usernames WHERE tag = ? AND owner_id = ?", (data.tag, data.user_id))

    bot1_val = round(my_val * random.uniform(0.55, 1.15))
    bot2_val = round(my_val * random.uniform(0.45, 1.05))
    total_pot = my_val + bot1_val + bot2_val
    my_chance = round((my_val / total_pot) * 100, 1)

    win = (random.random() * total_pot) <= my_val
    if win:
        payout = round(total_pot * 0.95)
        cur.execute("UPDATE users SET balance = balance + ?, season_xp = season_xp + 30 WHERE tg_user_id = ?", (payout, data.user_id))
        msg = f"🎡 ДЖЕКПОТ КОТЛА ТВОЙ (Шанс {my_chance}%)! Твой лот {data.tag} забрал весь банк магнатов: +{payout:,} GRAM!"
    else:
        msg = f"🎡 Колесо Магнатов остановилось на секторе соперника (Твой шанс был {my_chance}%). Банк {total_pot:,} G ушел оппоненту."

    conn.commit(); conn.close()
    return {"win": win, "chance": my_chance, "pot": total_pot, "message": msg}

@app.post("/api/duel")
def play_pvp_duel(data: ReqDuel):
    check_rate(data.user_id, 6, 2.0)
    if data.bet < 500: raise HTTPException(400, "Минимальная ставка — 500 GRAM")
    now = int(time.time())
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT balance FROM users WHERE tg_user_id = ?", (data.user_id,))
    bal = cur.fetchone()[0]
    if bal < data.bet: conn.close(); raise HTTPException(400, "Недостаточно GRAM!")

    cur.execute("SELECT item_type, rarity, quality_pct, is_verified, last_duel_at, is_staked FROM usernames WHERE tag = ? AND owner_id = ? AND is_saved = 1", (data.tag, data.user_id))
    my_item = cur.fetchone()
    if not my_item: conn.close(); raise HTTPException(400, "Выберите предмет из Сейфа!")

    itype, my_rar, my_q, is_ver, last_duel, is_st = my_item
    if is_st == 1:
        conn.close(); raise HTTPException(400, "Этот предмет заморожен в Холд-Банке!")

    cd_left = (int(last_duel or 0) + 120) - now
    if cd_left > 0:
        conn.close()
        raise HTTPException(400, f"⏳ На предмете {data.tag} перезарядка после боя! Подождите ещё {cd_left} сек. или выберите другой предмет.")

    my_rar_idx = next((i for i, r in enumerate(RARITIES) if r["name"] == my_rar), 0)
    opp_name = random.choice(["@crypto_shark", "@ton_mafia", "@durov_guard", "@arab_whale", "@zxc_king", "@dubai_prince"])
    opp_cand = fast_build_item_in_memory(itype or "username", my_rar_idx, 1.0)
    opp_tag = opp_cand["tag"]
    if opp_tag == data.tag:
        opp_tag = f"{opp_tag}_pro"

    opp_q = random.randint(35, 92)
    my_power = 500 + (my_q or 50) + (25 if is_ver else 0) + random.randint(-28, 28)
    opp_power = 500 + opp_q + random.randint(-28, 28)

    if random.random() < 0.04:
        win = False
        opp_power = my_power + random.randint(5, 18)
    else:
        win = my_power >= opp_power

    cur.execute("UPDATE usernames SET last_duel_at = ? WHERE tag = ? AND owner_id = ?", (now, data.tag, data.user_id))

    if win:
        profit = round(data.bet * 0.90)
        cur.execute("UPDATE users SET balance = balance + ?, duel_wins = duel_wins + 1, q_duels = q_duels + 1, season_xp = season_xp + 20 WHERE tg_user_id = ?", (profit, data.user_id))
        msg = f"⚔️ ПОБЕДА (Масть {my_rar})! Твой {data.tag} ({my_power} очк.) одолел равного {opp_tag} ({opp_power} очк.) игрока {opp_name}! Выигрыш: +{profit:,} G! (КД: 2 мин)"
    else:
        cur.execute("UPDATE users SET balance = balance - ?, q_duels = q_duels + 1, season_xp = season_xp + 5 WHERE tg_user_id = ?", (data.bet, data.user_id))
        msg = f"💥 Поражение в масти {my_rar}! {opp_name} с {opp_tag} ({opp_power} очк.) обошел твой {data.tag} ({my_power} очк.). (КД: 2 мин)"

    conn.commit(); conn.close()
    return {"win": win, "message": msg}

# ==========================================
# VIP-КОНТРАКТЫ, ЧЕКИ, СЕЙФ, ПРОМОКОДЫ
# ==========================================
@app.post("/api/contract/fulfill")
def fulfill_vip_contract(data: ReqSimple):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT contracts_done FROM users WHERE tg_user_id = ?", (data.user_id,))
    done_list = json.loads(cur.fetchone()[0] or "[]")
    if data.key in done_list:
        conn.close(); raise HTTPException(400, "Вы уже выполнили этот контракт сегодня!")

    contracts = get_daily_vip_contracts()
    c_obj = next((c for c in contracts if c["id"] == data.key), None)
    if not c_obj:
        conn.close(); raise HTTPException(400, "Контракт не найден")

    cur.execute("""
        SELECT tag, sell_price FROM usernames
        WHERE owner_id = ? AND item_type = ? AND rarity = ? AND is_saved = 1 AND is_equipped = 0 AND on_market = 0 AND is_staked = 0
        LIMIT 1
    """, (data.user_id, c_obj["req_type"], c_obj["req_rar"]))
    item = cur.fetchone()
    if not item:
        conn.close(); raise HTTPException(400, f"В Сейфе нет свободного предмета типа {c_obj['req_type']} редкости {c_obj['req_rar']}!")

    tag, sell_p = item
    payout = round(sell_p * c_obj["mult"] + c_obj["flat_bonus"])
    done_list.append(data.key)

    cur.execute("DELETE FROM usernames WHERE tag = ? AND owner_id = ?", (tag, data.user_id))
    cur.execute("UPDATE users SET balance = balance + ?, contracts_done = ?, season_xp = season_xp + 60 WHERE tg_user_id = ?",
                (payout, json.dumps(done_list), data.user_id))
    conn.commit(); conn.close()
    return {"status": "ok", "tag": tag, "payout": payout}

@app.post("/api/checks/create")
def create_gift_check(data: ReqCheckCreate):
    if data.amount < 5000:
        raise HTTPException(400, "Минимальная сумма чека — 5,000 GRAM")
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT balance FROM users WHERE tg_user_id = ?", (data.user_id,))
    bal = cur.fetchone()[0]
    if bal < data.amount:
        conn.close(); raise HTTPException(400, "Недостаточно GRAM на балансе!")

    code = f"CHK-{random.randint(1000,9999)}-{random.choice(['TON','VIP','MINT','GOLD'])}"
    cur.execute("UPDATE users SET balance = balance - ? WHERE tg_user_id = ?", (data.amount, data.user_id))
    cur.execute("INSERT INTO gift_checks (code, creator_id, amount, claimed_by, created_at) VALUES (?, ?, ?, NULL, ?)",
                (code, data.user_id, data.amount, int(time.time())))
    conn.commit(); conn.close()
    return {"code": code, "amount": data.amount}

@app.post("/api/minigame/vault")
def minigame_vault(data: ReqVaultHack):
    conn = get_db(); cur = conn.cursor()
    now = int(time.time())
    cur.execute("SELECT last_vault, level FROM users WHERE tg_user_id = ?", (data.user_id,))
    lv, lvl = cur.fetchone()
    if (now - (lv or 0)) < 3600:
        left_m = int((3600 - (now - (lv or 0))) // 60) + 1
        conn.close(); raise HTTPException(400, f"Крипто-сейф перезагружается! Доступно через {left_m} мин.")

    win_cell = random.randint(1, 3)
    if data.cell == win_cell:
        prize = 35000 * lvl
        cur.execute("UPDATE users SET balance = balance + ?, last_vault = ?, season_xp = season_xp + 30 WHERE tg_user_id = ?", (prize, now, data.user_id))
        res_msg = f"🔓 СЕЙФ ВЗЛОМАН! В ячейке #{data.cell} найдено +{prize:,} GRAM!"
    else:
        consolation = 5000 * lvl
        cur.execute("UPDATE users SET balance = balance + ?, last_vault = ? WHERE tg_user_id = ?", (consolation, now, data.user_id))
        res_msg = f"🚨 Сигнализация! Главный куш был в ячейке #{win_cell}, но ты успел унести +{consolation:,} GRAM!"

    conn.commit(); conn.close()
    return {"message": res_msg, "win_cell": win_cell}

PROMO_CODES = {
    "MINTTAGS": {"gram": 50000, "desc": "50,000 GRAM"},
    "DUROV":    {"gram": 75000, "desc": "75,000 GRAM"},
    "888":      {"gram": 100000,"desc": "100,000 GRAM"}
}

@app.post("/api/promo")
def activate_promo(data: ReqSimple):
    code = (data.key or "").strip().upper()
    conn = get_db(); cur = conn.cursor()

    if code.startswith("CHK-"):
        cur.execute("SELECT amount, claimed_by FROM gift_checks WHERE code = ?", (code,))
        chk = cur.fetchone()
        if not chk:
            conn.close(); raise HTTPException(400, "Чек не найден!")
        if chk[1] is not None:
            conn.close(); raise HTTPException(400, "Этот крипто-чек уже был активирован!")
        cur.execute("UPDATE gift_checks SET claimed_by = ? WHERE code = ?", (data.user_id, code))
        cur.execute("UPDATE users SET balance = balance + ? WHERE tg_user_id = ?", (chk[0], data.user_id))
        conn.commit(); conn.close()
        return {"reward": chk[0], "code": code}

    if code not in PROMO_CODES:
        conn.close(); raise HTTPException(400, "Промокод не найден или истек!")
    cur.execute("SELECT promos_used FROM users WHERE tg_user_id = ?", (data.user_id,))
    used = json.loads(cur.fetchone()[0] or "[]")
    if code in used:
        conn.close(); raise HTTPException(400, "Вы уже активировали этот промокод!")
    used.append(code)
    rew = PROMO_CODES[code]["gram"]
    cur.execute("UPDATE users SET balance = balance + ?, promos_used = ? WHERE tg_user_id = ?", (rew, json.dumps(used), data.user_id))
    conn.commit(); conn.close()
    return {"reward": rew, "code": code}

@app.post("/api/action")
def tag_action(data: ReqAction):
    check_rate(data.user_id, 15, 2.0)
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT item_type, rarity, sell_price, is_saved, is_equipped, on_market, is_staked FROM usernames WHERE tag = ? AND owner_id = ?", (data.tag, data.user_id))
    t = cur.fetchone()
    if not t:
        conn.close(); raise HTTPException(400, "Предмет не найден")
    itype, rar, sell_price, is_saved, is_eq, on_mkt, is_st = t
    if on_mkt == 1 or is_st == 1:
        conn.close(); raise HTTPException(400, "Предмет занят на Рынке или в Холд-Банке!")

    used_slot = data.slot
    if data.action_type == "save":
        cur.execute("SELECT max_hold FROM users WHERE tg_user_id = ?", (data.user_id,))
        max_h = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM usernames WHERE owner_id = ? AND is_saved = 1 AND on_market = 0", (data.user_id,))
        if cur.fetchone()[0] >= max_h:
            conn.close(); raise HTTPException(400, f"Сейф заполнен ({max_h} мест)!")
        cur.execute("UPDATE usernames SET is_saved = 1 WHERE tag = ? AND owner_id = ?", (data.tag, data.user_id))

    elif data.action_type in ["sell", "sell_merchant"]:
        if is_eq == 1:
            conn.close(); raise HTTPException(400, "Сначала снимите предмет с канала!")
        final_price = sell_price
        hot = get_daily_hot_series()
        if hot["code"] in data.tag.lower():
            final_price = round(final_price * (1.0 + hot["bonus_pct"] / 100.0))
        if data.action_type == "sell_merchant":
            merch = get_active_merchant_offer()
            if not merch["active"]:
                conn.close(); raise HTTPException(400, "Скупщик сейчас уехал! Дождитесь следующего визита.")
            if rar != merch["rarity"]:
                conn.close(); raise HTTPException(400, f"Скупщик сейчас принимает только редкость {merch['rarity']}!")
            final_price = round(final_price * merch["bonus_mult"])

        cur.execute("DELETE FROM usernames WHERE tag = ? AND owner_id = ?", (data.tag, data.user_id))
        cur.execute("UPDATE users SET balance = balance + ? WHERE tg_user_id = ?", (final_price, data.user_id))
        conn.commit(); conn.close()
        return {"status": "ok", "sold_for": final_price}

    elif data.action_type == "equip":
        if itype == "number":
            used_slot = 99
            cur.execute("UPDATE usernames SET is_equipped = 0, channel_slot = 0 WHERE owner_id = ? AND channel_slot = 99", (data.user_id,))
            cur.execute("UPDATE usernames SET is_saved = 1, is_equipped = 1, channel_slot = 99 WHERE tag = ? AND owner_id = ?", (data.tag, data.user_id))
        else:
            cur.execute("SELECT max_channels FROM users WHERE tg_user_id = ?", (data.user_id,))
            max_ch = cur.fetchone()[0]
            if data.slot and 1 <= data.slot <= max_ch:
                used_slot = data.slot
            else:
                cur.execute("SELECT channel_slot FROM usernames WHERE owner_id = ? AND is_equipped = 1 AND channel_slot < 90", (data.user_id,))
                busy = {r[0] for r in cur.fetchall()}
                used_slot = next((s for s in range(1, max_ch + 1) if s not in busy), 1)
            cur.execute("UPDATE usernames SET is_equipped = 0, channel_slot = 0 WHERE owner_id = ? AND channel_slot = ?", (data.user_id, used_slot))
            cur.execute("UPDATE usernames SET is_saved = 1, is_equipped = 1, channel_slot = ? WHERE tag = ? AND owner_id = ?", (used_slot, data.tag, data.user_id))
    elif data.action_type == "unequip":
        cur.execute("UPDATE usernames SET is_equipped = 0, channel_slot = 0 WHERE tag = ? AND owner_id = ?", (data.tag, data.user_id))

    conn.commit(); conn.close()
    return {"status": "ok", "sold_for": sell_price, "slot": used_slot}

@app.post("/api/pay_tax_shield")
def pay_tax_shield(data: ReqSimple):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT balance, level FROM users WHERE tg_user_id = ?", (data.user_id,))
    bal, lvl = cur.fetchone()
    cost = round(2000.0 * lvl)
    if bal < cost: conn.close(); raise HTTPException(400, f"Нужно {cost:,} GRAM")
    now = int(time.time())
    cur.execute("UPDATE users SET balance = balance - ?, tax_shield_until = ? WHERE tg_user_id = ?", (cost, now + 14400, data.user_id))
    conn.commit(); conn.close()
    return {"status": "ok"}

@app.post("/api/claim_album")
def claim_album(data: ReqSimple):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT albums_claimed FROM users WHERE tg_user_id = ?", (data.user_id,))
    claimed = json.loads(cur.fetchone()[0] or "[]")
    if data.key in claimed: conn.close(); raise HTTPException(400, "Коллекция уже собрана!")
    cur.execute("SELECT tag, item_type, rarity FROM usernames WHERE owner_id = ? AND is_saved = 1", (data.user_id,))
    my_tags = cur.fetchall()

    reward = 0
    if data.key == "alb_numbers":
        cnt = sum(1 for t in my_tags if t[1] == "number")
        if cnt < 3: conn.close(); raise HTTPException(400, f"Нужно 3 номера +888 в Сейфе ({cnt}/3)")
        reward = 150000
    elif data.key == "alb_gifts":
        cnt = sum(1 for t in my_tags if t[1] == "gift")
        if cnt < 3: conn.close(); raise HTTPException(400, f"Нужно 3 NFT-Подарка в Сейфе ({cnt}/3)")
        reward = 250000
    elif data.key == "alb_epic":
        cnt = sum(1 for t in my_tags if t[2] in ["Epic", "Legendary", "Mythic", "Luxury", "Ultra-Mythic", "Exclusive", "Divine"])
        if cnt < 5: conn.close(); raise HTTPException(400, f"Нужно 5 предметов Epic+ в Сейфе ({cnt}/5)")
        reward = 350000
    elif data.key == "alb_short":
        cnt = sum(1 for t in my_tags if t[1] == "username" and len(t[0]) <= 5)
        if cnt < 3: conn.close(); raise HTTPException(400, f"Нужно 3 коротких @username до 4 букв ({cnt}/3)")
        reward = 1000000
    else:
        conn.close(); raise HTTPException(400, "Неизвестная коллекция")

    claimed.append(data.key)
    cur.execute("UPDATE users SET balance = balance + ?, albums_claimed = ?, season_xp = season_xp + 100 WHERE tg_user_id = ?", (reward, json.dumps(claimed), data.user_id))
    conn.commit(); conn.close()
    return {"reward": reward}

@app.post("/api/clan/create")
def clan_create(data: ReqClanCreate):
    clean_name = data.name.strip()
    if len(clean_name) < 3 or len(clean_name) > 16: raise HTTPException(400, "От 3 до 16 символов!")
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT balance, clan_id FROM users WHERE tg_user_id = ?", (data.user_id,))
    bal, cur_clan = cur.fetchone()
    if cur_clan: conn.close(); raise HTTPException(400, "Сначала выйдите из текущего клана!")
    if bal < 1000000.0: conn.close(); raise HTTPException(400, "Создание стоит 1,000,000 GRAM!")
    cur.execute("SELECT 1 FROM clans WHERE LOWER(name) = LOWER(?)", (clean_name,))
    if cur.fetchone(): conn.close(); raise HTTPException(400, "Имя уже занято!")
    cid = f"clan_{data.user_id}_{int(time.time())}"
    cur.execute("UPDATE users SET balance = balance - 1000000.0, clan_id = ? WHERE tg_user_id = ?", (cid, data.user_id))
    cur.execute("INSERT INTO clans (clan_id, name, owner_id, level, treasury, members_count, max_members, created_at) VALUES (?, ?, ?, 1, 0.0, 1, 100, ?)", (cid, clean_name, data.user_id, int(time.time())))
    conn.commit(); conn.close()
    return {"status": "ok", "clan_id": cid}

@app.post("/api/clan/join")
def clan_join(data: ReqClanAction):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT clan_id FROM users WHERE tg_user_id = ?", (data.user_id,))
    old_c = cur.fetchone()[0]
    if old_c == data.clan_id: conn.close(); raise HTTPException(400, "Вы уже здесь!")
    cur.execute("SELECT members_count, max_members FROM clans WHERE clan_id = ?", (data.clan_id,))
    cl = cur.fetchone()
    if not cl or cl[0] >= cl[1]: conn.close(); raise HTTPException(400, "Клан переполнен!")
    if old_c:
        cur.execute("UPDATE clans SET members_count = GREATEST(0, members_count - 1) WHERE clan_id = ?" if conn.is_pg else "UPDATE clans SET members_count = MAX(0, members_count - 1) WHERE clan_id = ?", (old_c,))
    cur.execute("UPDATE clans SET members_count = members_count + 1 WHERE clan_id = ?", (data.clan_id,))
    cur.execute("UPDATE users SET clan_id = ? WHERE tg_user_id = ?", (data.clan_id, data.user_id))
    conn.commit(); conn.close()
    return {"status": "ok"}

@app.post("/api/clan/leave")
def clan_leave(data: ReqSimple):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT clan_id FROM users WHERE tg_user_id = ?", (data.user_id,))
    row = cur.fetchone()
    if not row or not row[0]: conn.close(); raise HTTPException(400, "Вы не в клане")
    cur.execute("UPDATE clans SET members_count = GREATEST(0, members_count - 1) WHERE clan_id = ?" if conn.is_pg else "UPDATE clans SET members_count = MAX(0, members_count - 1) WHERE clan_id = ?", (row[0],))
    cur.execute("UPDATE users SET clan_id = NULL WHERE tg_user_id = ?", (data.user_id,))
    conn.commit(); conn.close()
    return {"status": "ok"}

@app.post("/api/clan/donate")
def clan_donate(data: ReqClanAction):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT balance, clan_id FROM users WHERE tg_user_id = ?", (data.user_id,))
    bal, cid = cur.fetchone()
    if not cid or bal < data.amount: conn.close(); raise HTTPException(400, "Недостаточно средств")
    cur.execute("UPDATE users SET balance = balance - ? WHERE tg_user_id = ?", (data.amount, data.user_id))
    cur.execute("SELECT level, treasury FROM clans WHERE clan_id = ?", (cid,))
    lvl, tr = cur.fetchone()
    new_tr = tr + data.amount; new_lvl = lvl
    while new_tr >= new_lvl * 250000.0:
        new_tr -= new_lvl * 250000.0; new_lvl += 1
    cur.execute("UPDATE clans SET level = ?, treasury = ? WHERE clan_id = ?", (new_lvl, new_tr, cid))
    conn.commit(); conn.close()
    return {"status": "ok"}

CRAFT_COSTS = {"Common": 250, "Uncommon": 1200, "Rare": 5000, "Epic": 25000, "Legendary": 120000, "Mythic": 500000, "Luxury": 2000000}

@app.post("/api/craft")
def craft_items(data: ReqCraft):
    if len(data.tags) != 5: raise HTTPException(400, "Нужно 5 предметов!")
    conn = get_db(); cur = conn.cursor()
    ph = ",".join("?" for _ in data.tags)
    cur.execute(f"SELECT tag, item_type, rarity, is_equipped, on_market, is_staked FROM usernames WHERE owner_id = ? AND tag IN ({ph})", [data.user_id, *data.tags])
    rows = cur.fetchall()
    if len(rows) != 5 or len({r[2] for r in rows}) > 1 or any(r[3] == 1 or r[4] == 1 or r[5] == 1 for r in rows):
        conn.close(); raise HTTPException(400, "Выберите 5 свободных предметов одной редкости!")
    base_rar = rows[0][2]; itype = rows[0][1] or "username"
    rar_idx = next((i for i, r in enumerate(RARITIES) if r["name"] == base_rar), -1)
    if rar_idx < 0 or rar_idx >= len(RARITIES) - 1: conn.close(); raise HTTPException(400, "Нельзя улучшить")
    cost = CRAFT_COSTS.get(base_rar, 2000)
    cur.execute("SELECT balance FROM users WHERE tg_user_id = ?", (data.user_id,))
    if cur.fetchone()[0] < cost: conn.close(); raise HTTPException(400, f"Нужно {cost:,} GRAM")

    cur.execute(f"DELETE FROM usernames WHERE owner_id = ? AND tag IN ({ph})", [data.user_id, *data.tags])
    cur.execute("UPDATE users SET balance = balance - ?, q_crafts = q_crafts + 1, season_xp = season_xp + 15 WHERE tg_user_id = ?", (cost, data.user_id))
    if random.random() < 0.20:
        conn.commit(); conn.close()
        return {"burned": True, "message": "💥 Перегрев! Все 5 предметов сгорели..."}

    now = int(time.time())
    cand = ensure_unique_tag_once(cur, fast_build_item_in_memory(itype, rar_idx + 1, 1.5))
    new_tag = cand["tag"]

    cur.execute("INSERT OR REPLACE INTO usernames (tag, item_type, owner_id, rarity, quality_pct, income_per_sec, sell_price, num_multi, reasons, is_equipped, channel_slot, is_saved, on_market, created_at) VALUES (?,?,?,?,?,?,?,?,?,0,0,1,0,?)",
                (new_tag, cand["type"], data.user_id, cand["rarity"], cand["quality"], cand["inc"], cand["sell"], cand["num_multi"], cand["reasons"], now))
    conn.commit(); conn.close()
    return {"burned": False, "item": {"tag": new_tag, "type": cand["type"], "rarity": cand["rarity"], "inc": cand["inc"], "sell": cand["sell"]}}

@app.post("/api/market/create")
def market_create(data: ReqMarketCreate):
    if data.price < 50: raise HTTPException(400, "Мин. цена 50 GRAM")
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT item_type, rarity, income_per_sec, num_multi, reasons, is_equipped, on_market, is_staked FROM usernames WHERE tag = ? AND owner_id = ? AND is_saved = 1", (data.tag, data.user_id))
    row = cur.fetchone()
    if not row or row[5] == 1 or row[6] == 1 or row[7] == 1:
        conn.close(); raise HTTPException(400, "Снимите предмет с канала/банка перед выставлением!")
    itype, rar, inc, num_x, reas, _, _, _ = row
    now = int(time.time()); ends_at = now + (data.hours * 3600)
    cur.execute("UPDATE usernames SET on_market = 1 WHERE tag = ? AND owner_id = ?", (data.tag, data.user_id))
    cur.execute("""
        INSERT INTO market_lots (tag, item_type, rarity, income_per_sec, num_multi, reasons, seller_id, seller_name, is_auction, start_price, current_price, buyout_price, ends_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (data.tag, itype, rar, inc, num_x or 1.2, reas, data.user_id, data.username, data.is_auction, data.price, data.price, data.price * 2.5, ends_at, now))
    conn.commit(); conn.close()
    return {"status": "ok"}

@app.post("/api/market/interact")
def market_interact(data: ReqMarketInteract):
    conn = get_db(); cur = conn.cursor()
    now = int(time.time())
    settle_expired_auctions(cur)
    cur.execute("SELECT tag, item_type, rarity, income_per_sec, num_multi, reasons, seller_id, is_auction, current_price, buyout_price, highest_bidder_id, bids_count, ends_at FROM market_lots WHERE lot_id = ?", (data.lot_id,))
    lot = cur.fetchone()
    if not lot: conn.close(); raise HTTPException(400, "Лот уже закрыт")
    tag, itype, rar, inc, num_x, reas, seller_id, is_auc, cur_price, buyout, prev_bidder, bids_cnt, ends_at = lot
    if seller_id == data.user_id: conn.close(); raise HTTPException(400, "Это ваш лот!")
    cur.execute("SELECT balance FROM users WHERE tg_user_id = ?", (data.user_id,))
    my_bal = cur.fetchone()[0]

    if is_auc == 0 or data.act == "buy":
        pay = cur_price if is_auc == 0 else buyout
        if my_bal < pay: conn.close(); raise HTTPException(400, f"Нужно {int(pay):,} GRAM")
        if prev_bidder and prev_bidder > 0:
            cur.execute("UPDATE users SET balance = balance + ? WHERE tg_user_id = ?", (cur_price, prev_bidder))
        cur.execute("UPDATE users SET balance = balance - ? WHERE tg_user_id = ?", (pay, data.user_id))
        if seller_id and seller_id > 0:
            cur.execute("UPDATE users SET balance = balance + ? WHERE tg_user_id = ?", (round(pay * 0.95, 2), seller_id))
        cur.execute("INSERT OR REPLACE INTO usernames (tag, item_type, owner_id, rarity, quality_pct, income_per_sec, sell_price, num_multi, reasons, is_equipped, channel_slot, is_saved, on_market, created_at) VALUES (?,?,?,?,85,?,?,?,?,0,0,1,0,?)",
                    (tag, itype, data.user_id, rar, min(200.0, inc), round(pay * 0.8, 0), min(3.5, num_x or 1.2), reas, now))
        cur.execute("DELETE FROM market_lots WHERE lot_id = ?", (data.lot_id,))
        conn.commit(); conn.close()
        return {"status": "bought", "tag": tag}

    new_bid = round(cur_price * 1.10, 0) if bids_cnt > 0 else cur_price
    if my_bal < new_bid: conn.close(); raise HTTPException(400, f"Для ставки нужно {int(new_bid):,} GRAM")
    if prev_bidder and prev_bidder > 0:
        cur.execute("UPDATE users SET balance = balance + ? WHERE tg_user_id = ?", (cur_price, prev_bidder))
    cur.execute("UPDATE users SET balance = balance - ? WHERE tg_user_id = ?", (new_bid, data.user_id))
    cur.execute("UPDATE market_lots SET current_price = ?, highest_bidder_id = ?, highest_bidder_name = ?, bids_count = bids_count + 1, ends_at = ? WHERE lot_id = ?",
                (new_bid, data.user_id, data.username, max(ends_at, now + 60), data.lot_id))
    conn.commit(); conn.close()
    return {"status": "bid_placed", "new_price": new_bid}

WHEEL_PRIZES = [
    {"idx": 0, "title": "5,000 GRAM",       "type": "coins", "val": 5000,   "w": 360},
    {"idx": 1, "title": "15,000 GRAM",      "type": "coins", "val": 15000,  "w": 250},
    {"idx": 2, "title": "🍀 Удача ×2 (1ч)", "type": "luck",  "val": 3600,   "w": 130},
    {"idx": 3, "title": "35,000 GRAM",      "type": "coins", "val": 35000,  "w": 110},
    {"idx": 4, "title": "🐸 NFT-Подарок",   "type": "gift",  "val": "Rare", "w": 85},
    {"idx": 5, "title": "100,000 GRAM",     "type": "coins", "val": 100000, "w": 40},
    {"idx": 6, "title": "📞 Номер +888",    "type": "num",   "val": "Rare", "w": 20},
    {"idx": 7, "title": "💎 ДЖЕКПОТ 1M G",  "type": "coins", "val": 1000000,"w": 5}
]

@app.post("/api/wheel_spin")
def spin_wheel(data: ReqSimple):
    conn = get_db(); cur = conn.cursor()
    now = int(time.time())
    cur.execute("SELECT last_wheel FROM users WHERE tg_user_id = ?", (data.user_id,))
    lw = cur.fetchone()[0]
    if (now - lw) < 1800: conn.close(); raise HTTPException(400, "Колесо доступно раз в 30 минут!")
    tot = sum(p["w"] for p in WHEEL_PRIZES); r = random.random() * tot
    picked = WHEEL_PRIZES[0]
    for p in WHEEL_PRIZES:
        if r < p["w"]: picked = p; break
        r -= p["w"]
    if picked["type"] == "coins":
        cur.execute("UPDATE users SET balance = balance + ?, last_wheel = ?, season_xp = season_xp + 10 WHERE tg_user_id = ?", (picked["val"], now, data.user_id))
    elif picked["type"] == "luck":
        cur.execute("UPDATE users SET luck_multi = 2.0, luck_until = ?, last_wheel = ? WHERE tg_user_id = ?", (now + picked["val"], now, data.user_id))
    elif picked["type"] == "gift":
        t, inc, sell, num_x, q, reas, _ = generate_nft_gift(RARITIES[2])
        cur.execute("INSERT OR IGNORE INTO usernames (tag, item_type, owner_id, rarity, quality_pct, income_per_sec, sell_price, num_multi, reasons, is_saved, created_at) VALUES (?,?,?,?,?,?,?,?,?,1,?)", (t, "gift", data.user_id, "Rare", q, inc, sell, 1.0, reas, now))
        cur.execute("UPDATE users SET last_wheel = ? WHERE tg_user_id = ?", (now, data.user_id))
    elif picked["type"] == "num":
        t, inc, sell, num_x, q, reas, _ = generate_phone_number(RARITIES[2])
        cur.execute("INSERT OR IGNORE INTO usernames (tag, item_type, owner_id, rarity, quality_pct, income_per_sec, sell_price, num_multi, reasons, is_saved, created_at) VALUES (?,?,?,?,?,?,?,?,?,1,?)", (t, "number", data.user_id, "Rare", q, inc, sell, num_x, reas, now))
        cur.execute("UPDATE users SET last_wheel = ? WHERE tg_user_id = ?", (now, data.user_id))
    conn.commit(); conn.close()
    return {"prize_idx": picked["idx"], "title": picked["title"]}

DAILY_REWARDS = [10000, 25000, 50000, 100000, 200000, 400000, 1000000]

@app.post("/api/daily_gift")
def claim_daily(data: ReqSimple):
    conn = get_db(); cur = conn.cursor()
    now = int(time.time())
    cur.execute("SELECT daily_streak, last_daily, vip_until FROM users WHERE tg_user_id = ?", (data.user_id,))
    streak, last_d, vip_u = cur.fetchone()
    if (now - last_d) < 86400: conn.close(); raise HTTPException(400, "Подарок уже получен сегодня!")
    if (now - last_d) > 172800: streak = 0
    reward = DAILY_REWARDS[streak % 7]; new_streak = (streak % 7) + 1
    new_vip = max(now, vip_u or 0) + 86400 if new_streak == 7 else (vip_u or 0)
    cur.execute("UPDATE users SET balance = balance + ?, daily_streak = ?, last_daily = ?, vip_until = ?, season_xp = season_xp + 25 WHERE tg_user_id = ?", (reward, new_streak, now, new_vip, data.user_id))
    conn.commit(); conn.close()
    return {"reward": reward, "day": new_streak, "vip_bonus": new_streak == 7}

@app.post("/api/claim_reward")
def claim_quest_or_pass(data: ReqSimple):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT q_spins, q_rare, q_crafts, q_duels, q_claimed, season_xp, season_claimed, ach_stats, ach_claimed FROM users WHERE tg_user_id = ?", (data.user_id,))
    qs, qr, qc, qd, q_cl_raw, s_xp, s_cl_raw, a_st_raw, a_cl_raw = cur.fetchone()
    q_cl = json.loads(q_cl_raw or "[]"); s_cl = json.loads(s_cl_raw or "[]")
    a_st = json.loads(a_st_raw or "{}"); a_cl = json.loads(a_cl_raw or "[]")
    key = data.key; reward = 0; add_s_xp = 0

    if key == "q1" and qs >= 20 and "q1" not in q_cl:
        reward = 15000; add_s_xp = 50; q_cl.append("q1")
    elif key == "q2" and qr >= 5 and "q2" not in q_cl:
        reward = 45000; add_s_xp = 50; q_cl.append("q2")
    elif key == "q3" and qc >= 1 and "q3" not in q_cl:
        reward = 35000; add_s_xp = 50; q_cl.append("q3")
    elif key == "q4" and (qd or 0) >= 3 and "q4" not in q_cl:
        reward = 50000; add_s_xp = 60; q_cl.append("q4")
    elif key == "q_all" and all(x in q_cl for x in ["q1", "q2", "q3"]) and "q_all" not in q_cl:
        reward = 150000; add_s_xp = 100; q_cl.append("q_all")
    elif key.startswith("pass_"):
        lvl = int(key.split("_")[1])
        if s_xp >= lvl * 50 and key not in s_cl:
            reward = lvl * 10000; s_cl.append(key)
    elif key.startswith("ach_"):
        parts = key.split("_"); rar = parts[1]; target = int(parts[2])
        if a_st.get(rar, 0) >= target and key not in a_cl:
            reward = target * 20000; a_cl.append(key)
    else:
        conn.close(); raise HTTPException(400, "Условия не выполнены или награда уже получена")

    cur.execute("UPDATE users SET balance = balance + ?, season_xp = season_xp + ?, q_claimed = ?, season_claimed = ?, ach_claimed = ? WHERE tg_user_id = ?",
                (reward, add_s_xp, json.dumps(q_cl), json.dumps(s_cl), json.dumps(a_cl), data.user_id))
    conn.commit(); conn.close()
    return {"reward": reward}

@app.post("/api/upgrade_mgr")
def upgrade_manager(data: ReqSimple):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT balance, smm_lvl, buyer_lvl FROM users WHERE tg_user_id = ?", (data.user_id,))
    bal, smm, buyer = cur.fetchone()
    if data.key == "smm":
        if smm >= MAX_SMM_LVL: conn.close(); raise HTTPException(400, f"Макс. уровень СММ ({MAX_SMM_LVL})!")
        cost = get_smm_upgrade_cost(smm)
        if bal < cost: conn.close(); raise HTTPException(400, f"Нужно {int(cost):,} GRAM")
        cur.execute("UPDATE users SET balance = balance - ?, smm_lvl = smm_lvl + 1 WHERE tg_user_id = ?", (cost, data.user_id))
    else:
        if buyer >= MAX_BUYER_LVL: conn.close(); raise HTTPException(400, f"Макс. уровень Байера ({MAX_BUYER_LVL})!")
        cost = get_buyer_upgrade_cost(buyer)
        if bal < cost: conn.close(); raise HTTPException(400, f"Нужно {int(cost):,} GRAM")
        cur.execute("UPDATE users SET balance = balance - ?, buyer_lvl = buyer_lvl + 1 WHERE tg_user_id = ?", (cost, data.user_id))
    conn.commit(); conn.close()
    return {"status": "ok"}

PRICES = {
    "spin_10_stars":      {"title": "⚡ 10× Прокрутов сразу (Rare+)",       "price": 150},
    "spin_25_stars":      {"title": "🔥 25× Мега-Прокрутов (Epic+)",       "price": 219},
    "ai_holding":         {"title": "🤖 AI-Нейросеть Каналов (×1.35)",      "price": 129},
    "vip_pass":           {"title": "👑 VIP Game Pass (30 дней)",          "price": 89},
    "luck_x2_1h":         {"title": "🍀 Буст Удачи ×2 (1 час)",            "price": 19},
    "luck_x5_2h":         {"title": "🔥 Мега Удача ×5 (2 часа)",           "price": 49},
    "hold_plus_50":       {"title": "💼 +50 слотов в Хранилище",           "price": 45},
    "channel_slot":       {"title": "📢 Новый слот Канала",                "price": 59},
    "coins_10m":          {"title": "🪙 2,500,000 GRAM Магната",           "price": 35},
    "coins_100m":         {"title": "💰 25,000,000 GRAM Империи",          "price": 99},
    "num_888_box":        {"title": "📞 Секретный Бокс +888 (Mythic+)",     "price": 99},
    "case_stars_lite":    {"title": "⭐️ Звездный Ларец (Кейс)",            "price": 29},
    "case_stars_founder": {"title": "👑 Кейс Основателя (Mythic+)",        "price": 99},
    "case_stars_divine":  {"title": "💎 Божественный Сундук Дурова",       "price": 249}
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
    conn = get_db(); cur = conn.cursor()
    now = int(time.time())
    parts = data.key.split(":")
    p = parts[0]
    itype = parts[1] if len(parts) > 1 else "username"
    stars_spent = PRICES.get(p, {}).get("price", 0)

    cur.execute("SELECT ref_by FROM users WHERE tg_user_id = ?", (data.user_id,))
    r_row = cur.fetchone()
    if r_row and r_row[0] and stars_spent > 0:
        ref_stars = max(1, int(stars_spent * 0.15))
        cur.execute("UPDATE users SET contrib_stars = contrib_stars + ? WHERE tg_user_id = ?", (ref_stars, data.user_id))

    drops = []
    case_res = None
    if p == "spin_10_stars":
        drops, _ = execute_spins_internal(cur, data.user_id, itype, "tier_2", 10, 0.0, 0)
    elif p == "spin_25_stars":
        drops, _ = execute_spins_internal(cur, data.user_id, itype, "tier_3", 25, 0.0, 0)
    elif p in ["case_stars_lite", "case_stars_founder", "case_stars_divine"]:
        cand, tape = roll_case_drop_fast(cur, p, 2.0)
        cur.execute("""
            INSERT OR IGNORE INTO usernames (tag, item_type, owner_id, rarity, quality_pct, income_per_sec, sell_price, num_multi, reasons, is_equipped, channel_slot, is_saved, on_market, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 1, 0, ?)
        """, (cand["tag"], cand["type"], data.user_id, cand["rarity"], cand["quality"], cand["inc"], cand["sell"], cand["num_multi"], cand["reasons"], now))
        case_res = {
            "winner": {
                "tag": cand["tag"], "type": cand["type"], "rarity": cand["rarity"], "rar_idx": cand["rar_idx"],
                "q": cand["quality"], "inc": cand["inc"], "sell": cand["sell"], "num_x": cand["num_multi"],
                "reasons": cand["reasons"].split("|"), "eq": 0, "slot": 0, "staked": 0, "verified": 0, "duel_cd": 0
            },
            "tape": tape
        }
    elif p == "ai_holding":
        cur.execute("UPDATE users SET ai_boost = 1 WHERE tg_user_id = ?", (data.user_id,))
    elif p == "vip_pass":
        cur.execute("UPDATE users SET vip_until = ?, max_hold = max_hold + 50, balance = balance + 1000000 WHERE tg_user_id = ?", (now + 2592000, data.user_id))
    elif p == "luck_x2_1h":
        cur.execute("UPDATE users SET luck_multi = 2.0, luck_until = ? WHERE tg_user_id = ?", (now + 3600, data.user_id))
    elif p == "luck_x5_2h":
        cur.execute("UPDATE users SET luck_multi = 5.0, luck_until = ? WHERE tg_user_id = ?", (now + 7200, data.user_id))
    elif p == "hold_plus_50":
        cur.execute("UPDATE users SET max_hold = max_hold + 50 WHERE tg_user_id = ?", (data.user_id,))
    elif p == "channel_slot":
        cur.execute("UPDATE users SET max_channels = LEAST(15, max_channels + 1) WHERE tg_user_id = ?" if conn.is_pg else "UPDATE users SET max_channels = MIN(15, max_channels + 1) WHERE tg_user_id = ?", (data.user_id,))
    elif p == "coins_10m":
        cur.execute("UPDATE users SET balance = balance + 2500000 WHERE tg_user_id = ?", (data.user_id,))
    elif p == "coins_100m":
        cur.execute("UPDATE users SET balance = balance + 25000000 WHERE tg_user_id = ?", (data.user_id,))
    elif p == "num_888_box":
        t, inc, sell, num_x, q, reas, _ = generate_phone_number(RARITIES[5])
        cur.execute("INSERT OR IGNORE INTO usernames (tag, item_type, owner_id, rarity, quality_pct, income_per_sec, sell_price, num_multi, reasons, is_saved, created_at) VALUES (?,?,?,?,?,?,?,?,?,1,?)",
                    (t, "number", data.user_id, "Mythic", q, inc, sell, num_x, reas, now))

    conn.commit(); conn.close()
    return {"status": "ok", "drops": drops, "case_res": case_res}
