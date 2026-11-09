import os
import time
import math
import json
import random
import sqlite3
import urllib.request
import urllib.parse
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="MintTagsApp | Медиа Империя Full Edition")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключение твоих папок с картинками на GitHub
if os.path.isdir("assets"):
    app.mount("/assets", StaticFiles(directory="assets"), name="assets")
if os.path.isdir("icons"):
    app.mount("/icons", StaticFiles(directory="icons"), name="icons")
if os.path.isdir("backdrops"):
    app.mount("/backdrops", StaticFiles(directory="backdrops"), name="backdrops")

DB_PATH = os.getenv("DB_PATH", "minttags_empire.db")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DEFAULT_CHANNEL = os.getenv("REQUIRED_CHANNEL", "@durov")
COUNTRY_CHANGE_PRICE = 500_000.0

# ==================== СПРАВОЧНИКИ И КАТАЛОГИ ====================

COUNTRIES = {
    "RU": {"name": "Россия", "flag": "🇷🇺", "prefix": "+7"},
    "US": {"name": "США", "flag": "🇺🇸", "prefix": "+1"},
    "AE": {"name": "ОАЭ (Дубай)", "flag": "🇦🇪", "prefix": "+971"},
    "GB": {"name": "Англия", "flag": "🇬🇧", "prefix": "+44"},
    "DE": {"name": "Германия", "flag": "🇩🇪", "prefix": "+49"},
    "CH": {"name": "Швейцария", "flag": "🇨🇭", "prefix": "+41"},
    "JP": {"name": "Япония", "flag": "🇯🇵", "prefix": "+81"},
    "KZ": {"name": "Казахстан", "flag": "🇰🇿", "prefix": "+7"},
    "UA": {"name": "Украина", "flag": "🇺🇦", "prefix": "+380"},
    "BY": {"name": "Беларусь", "flag": "🇧🇾", "prefix": "+375"},
}

RARITIES = [
    {"tier": 0, "name": "Обычный (1/10)",      "color": "#64748b", "u_min": 250,       "u_max": 950,        "n_min": 20000,     "n_max": 65000,      "g_min": 35000,      "g_max": 90000},
    {"tier": 1, "name": "Необычный (2/10)",    "color": "#10b981", "u_min": 1200,      "u_max": 4200,       "n_min": 75000,     "n_max": 180000,     "g_min": 110000,     "g_max": 260000},
    {"tier": 2, "name": "Редкий (3/10)",       "color": "#06b6d4", "u_min": 5000,      "u_max": 18000,      "n_min": 200000,    "n_max": 480000,     "g_min": 300000,     "g_max": 750000},
    {"tier": 3, "name": "Эпический (4/10)",    "color": "#3b82f6", "u_min": 22000,     "u_max": 75000,      "n_min": 550000,    "n_max": 1400000,    "g_min": 850000,     "g_max": 2200000},
    {"tier": 4, "name": "Элитный (5/10)",      "color": "#8b5cf6", "u_min": 90000,     "u_max": 320000,     "n_min": 1600000,   "n_max": 4500000,    "g_min": 2500000,    "g_max": 6800000},
    {"tier": 5, "name": "Мифический (6/10)",   "color": "#ec4899", "u_min": 380000,    "u_max": 1400000,    "n_min": 5000000,   "n_max": 15000000,   "g_min": 7500000,    "g_max": 22000000},
    {"tier": 6, "name": "Роскошный (7/10)",    "color": "#14b8a6", "u_min": 1800000,   "u_max": 4800000,    "n_min": 18000000,  "n_max": 50000000,   "g_min": 25000000,   "g_max": 75000000},
    {"tier": 7, "name": "Имперский (8/10)",    "color": "#f59e0b", "u_min": 6500000,   "u_max": 24000000,   "n_min": 55000000,  "n_max": 160000000,  "g_min": 80000000,   "g_max": 240000000},
    {"tier": 8, "name": "Эксклюзивный (9/10)", "color": "#ef4444", "u_min": 28000000,  "u_max": 95000000,   "n_min": 180000000, "n_max": 550000000,  "g_min": 260000000,  "g_max": 850000000},
    {"tier": 9, "name": "Божественный (10/10)","color": "#fde047", "u_min": 110000000, "u_max": 500000000,  "n_min": 600000000, "n_max": 2500000000, "g_min": 900000000,  "g_max": 5000000000},
]

PACK_TIERS = {
    "standard": {"name": "STANDARD", "cost": 5000,     "min_t": 0, "max_t": 5},
    "luxury":   {"name": "LUXURY+",  "cost": 3500000,  "min_t": 5, "max_t": 8},
    "royal":    {"name": "ROYAL",    "cost": 25000000, "min_t": 7, "max_t": 9},
}

NFT_COLLECTIONS = {
    "Plush Pepe":     {"icon": "/assets/genesis-pepe.webp", "models": ["Genesis Gold", "Red Menace", "Ninja Mike", "Emerald King", "Polka Dots", "Vantablack Pepe"]},
    "Swiss Watch":    {"icon": "/assets/swiss-watch.webp",  "models": ["Tourbillon Cyan", "Royal Gold", "Carbon Chrono", "Titanium Zero", "Geneva Skeleton"]},
    "Durov's Cap":    {"icon": "/assets/durov-chest.webp",  "models": ["Founder Black", "TON Stealth", "Resistance Edition", "Telegram Blue", "Encrypted Crown"]},
    "Resistance Dog": {"icon": "/assets/durov-chest.webp",  "models": ["Hoodie White", "Cyber Hound", "Golden REDO", "Night Watch", "Paper Plane"]},
    "Low Rider":      {"icon": "/assets/sheikh-case.webp",  "models": ["Dubai Gold", "Westside Chrome", "Midnight Purple", "Emerald Hydraulics"]},
    "Mini Oscar":     {"icon": "/assets/sheikh-case.webp",  "models": ["Pure Gold", "Platinum Idol", "Obsidian Knight", "Diamond Award"]},
    "Astral Shard":   {"icon": "/assets/all-in.webp",       "models": ["Crimson Core", "Void Crystal", "Ether Prism", "Quantum Nova"]},
    "Diamond Ring":   {"icon": "/assets/sheikh-case.webp",  "models": ["Solitaire 10ct", "Emerald Cut", "Royal Sapphire", "Black Diamond"]},
}

BACKDROPS = [
    {"name": "Black",           "file": "/backdrops/Black.svg",           "bonus": 1.45},
    {"name": "Onyx Black",      "file": "/backdrops/Onyx_Black.svg",      "bonus": 1.40},
    {"name": "Pure Gold",       "file": "/backdrops/Pure_Gold.svg",       "bonus": 1.35},
    {"name": "Satin Gold",      "file": "/backdrops/Satin_Gold.svg",      "bonus": 1.25},
    {"name": "Cyberpunk",       "file": "/backdrops/Cyberpunk.svg",       "bonus": 1.30},
    {"name": "Electric Purple", "file": "/backdrops/Electric_Purple.svg", "bonus": 1.20},
    {"name": "Neon Blue",       "file": "/backdrops/Neon_Blue.svg",       "bonus": 1.20},
    {"name": "Pacific Cyan",    "file": "/backdrops/Pacific_Cyan.svg",    "bonus": 1.15},
    {"name": "Emerald",         "file": "/backdrops/Emerald.svg",         "bonus": 1.25},
    {"name": "Midnight Blue",   "file": "/backdrops/Midnight_Blue.svg",   "bonus": 1.15},
    {"name": "Platinum",        "file": "/backdrops/Platinum.svg",        "bonus": 1.25},
]

CASES_CATALOG = {
    "case_all_in": {
        "id": "case_all_in",
        "name": "Всё или Ничего",
        "desc": "Жесткий риск! 99.85% дешевые @username (250-950 G), но есть шанс сорвать Божественный джекпот!",
        "price": 10000,
        "img": "/assets/all-in.webp",
        "types": ["username"],
        "jackpot_types": ["number", "gift"],
        "weights": {0: 99850, 8: 115, 9: 35}
    },
    "case_nft_box": {
        "id": "case_nft_box",
        "name": "NFT Gift Box",
        "desc": "100% выпадает только коллекционный NFT-подарок с моделью и фоном Telegram (Pepe, Watch, Cap, REDO)!",
        "price": 250000,
        "img": "/assets/genesis-pepe.webp",
        "types": ["gift"],
        "weights": {1: 3500, 2: 3200, 3: 1900, 4: 900, 5: 350, 6: 110, 7: 30, 8: 8, 9: 2}
    },
    "case_sheikh": {
        "id": "case_sheikh",
        "name": "Контейнер Шейха",
        "desc": "Золотой карбоновый дипломат. Анонимные номера +888, турбийоны и люксовые лоурайдеры.",
        "price": 1200000,
        "img": "/assets/sheikh-case.webp",
        "types": ["number", "gift"],
        "weights": {2: 3000, 3: 3500, 4: 2000, 5: 1000, 6: 350, 7: 110, 8: 32, 9: 8}
    },
    "case_durov": {
        "id": "case_durov",
        "name": "Сундук Дурова",
        "desc": "Реликт создателя. Только элитные теги, номера +888 и редчайшие гифты Blackout Edition.",
        "price": 5000000,
        "img": "/assets/durov-chest.webp",
        "types": ["username", "number", "gift"],
        "weights": {4: 3800, 5: 3200, 6: 1800, 7: 850, 8: 280, 9: 70}
    }
}

ACHIEVEMENTS = [
    {"id": "ach_first_mint", "title": "Первый Минт",       "desc": "Сделать хотя бы 1 прокрут в Реестре",      "reward_g": 50000,    "reward_s": 10},
    {"id": "ach_rich_10m",   "title": "Миллионер",         "desc": "Накопить 10,000,000 GRAM на балансе",       "reward_g": 1500000,  "reward_s": 25},
    {"id": "ach_fame_3",     "title": "Коллекционер Славы","desc": "Заполнить все 3 слота Витрины Славы",       "reward_g": 500000,   "reward_s": 15},
    {"id": "ach_subs_10k",   "title": "Медиа-Магнат",      "desc": "Набрать 10,000 подписчиков в своем канале", "reward_g": 2000000,  "reward_s": 30},
    {"id": "ach_pvp_win",    "title": "Гладиатор Арены",   "desc": "Победить в PvP-бою за теги и банк",         "reward_g": 750000,   "reward_s": 20},
    {"id": "ach_upgrader",   "title": "Мастер Апгрейда",   "desc": "Успешно улучшить предмет в Апгрейдере",     "reward_g": 1000000,  "reward_s": 20},
]

WORDS_POOL = [
    "CHANEL", "BRATISHKIN", "PATEK", "PHARAOH", "MACAN", "DUROV", "ROLEX", "CARTIER",
    "BUGATTI", "FRAGMENT", "SATOSHI", "GENESIS", "EMPIRE", "WHALE", "SHEIKH", "DIAMOND",
    "HERMES", "PRADA", "BALENCIAGA", "LAMBO", "FERRARI", "MONACO", "DUBAI", "CRYPTO"
]

# ==================== БАЗА ДАННЫХ И МИГРАЦИИ ====================

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            tg_user_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT 'Player',
            balance REAL DEFAULT 150000.0,
            stars_balance INTEGER DEFAULT 25,
            xp INTEGER DEFAULT 100,
            luck_multi REAL DEFAULT 1.0,
            luck_until REAL DEFAULT 0.0,
            pity_counter INTEGER DEFAULT 0,
            country_code TEXT DEFAULT 'RU',
            national_phone TEXT DEFAULT '',
            subs_count INTEGER DEFAULT 0,
            channel_name TEXT DEFAULT '',
            clan_name TEXT DEFAULT '',
            bank_deposit REAL DEFAULT 0.0,
            bank_updated REAL DEFAULT 0.0,
            last_passive_ts REAL DEFAULT 0.0,
            daily_claimed_at REAL DEFAULT 0.0,
            sub_rewarded INTEGER DEFAULT 0,
            compact_pref INTEGER DEFAULT 0,
            pvp_wins INTEGER DEFAULT 0,
            upgrades_won INTEGER DEFAULT 0,
            total_spins INTEGER DEFAULT 0
        )
    """)
    u_cols = [r["name"] for r in cur.execute("PRAGMA table_info(users)").fetchall()]
    for col, ctype in [
        ("xp", "INTEGER DEFAULT 100"),
        ("subs_count", "INTEGER DEFAULT 0"),
        ("channel_name", "TEXT DEFAULT ''"),
        ("clan_name", "TEXT DEFAULT ''"),
        ("bank_deposit", "REAL DEFAULT 0.0"),
        ("bank_updated", "REAL DEFAULT 0.0"),
        ("last_passive_ts", "REAL DEFAULT 0.0"),
        ("daily_claimed_at", "REAL DEFAULT 0.0"),
        ("sub_rewarded", "INTEGER DEFAULT 0"),
        ("compact_pref", "INTEGER DEFAULT 0"),
        ("pvp_wins", "INTEGER DEFAULT 0"),
        ("upgrades_won", "INTEGER DEFAULT 0"),
        ("total_spins", "INTEGER DEFAULT 0"),
    ]:
        if col not in u_cols:
            try:
                cur.execute(f"ALTER TABLE users ADD COLUMN {col} {ctype}")
            except Exception:
                pass

    cur.execute("""
        CREATE TABLE IF NOT EXISTS usernames (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER,
            tag TEXT,
            type TEXT DEFAULT 'username',
            tier INTEGER DEFAULT 0,
            rarity_name TEXT DEFAULT 'Обычный (1/10)',
            price REAL DEFAULT 500.0,
            income REAL DEFAULT 10.0,
            quality INTEGER DEFAULT 85,
            in_safe INTEGER DEFAULT 0,
            in_showcase INTEGER DEFAULT 0,
            verified INTEGER DEFAULT 0,
            on_market INTEGER DEFAULT 0,
            market_price REAL DEFAULT 0.0,
            backdrop TEXT DEFAULT '',
            backdrop_file TEXT DEFAULT '',
            model_name TEXT DEFAULT '',
            collection TEXT DEFAULT '',
            icon_url TEXT DEFAULT '',
            created_at REAL DEFAULT 0.0
        )
    """)
    i_cols = [r["name"] for r in cur.execute("PRAGMA table_info(usernames)").fetchall()]
    for col, ctype in [
        ("income", "REAL DEFAULT 10.0"),
        ("quality", "INTEGER DEFAULT 85"),
        ("in_safe", "INTEGER DEFAULT 0"),
        ("in_showcase", "INTEGER DEFAULT 0"),
        ("verified", "INTEGER DEFAULT 0"),
        ("on_market", "INTEGER DEFAULT 0"),
        ("market_price", "REAL DEFAULT 0.0"),
        ("backdrop", "TEXT DEFAULT ''"),
        ("backdrop_file", "TEXT DEFAULT ''"),
        ("model_name", "TEXT DEFAULT ''"),
        ("collection", "TEXT DEFAULT ''"),
        ("icon_url", "TEXT DEFAULT ''"),
    ]:
        if col not in i_cols:
            try:
                cur.execute(f"ALTER TABLE usernames ADD COLUMN {col} {ctype}")
            except Exception:
                pass

    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_achievements (
            user_id INTEGER,
            ach_id TEXT,
            PRIMARY KEY (user_id, ach_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS promos (
            code TEXT PRIMARY KEY,
            reward_gram REAL DEFAULT 250000.0,
            uses_left INTEGER DEFAULT 100
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS promo_used (
            user_id INTEGER,
            code TEXT,
            PRIMARY KEY (user_id, code)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS raffle_rounds (
            round_id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT DEFAULT 'active',
            pot REAL DEFAULT 100000.0,
            ticket_price REAL DEFAULT 25000.0,
            ends_at REAL DEFAULT 0.0,
            winner_id INTEGER DEFAULT 0,
            winner_name TEXT DEFAULT '',
            win_amount REAL DEFAULT 0.0,
            win_chance REAL DEFAULT 0.0
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS raffle_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            round_id INTEGER,
            user_id INTEGER,
            username TEXT,
            tickets INTEGER DEFAULT 1
        )
    """)
    cur.execute("CREATE TABLE IF NOT EXISTS app_config (k TEXT PRIMARY KEY, v TEXT)")
    cur.execute("INSERT OR IGNORE INTO app_config (k, v) VALUES ('required_channel', ?)", (DEFAULT_CHANNEL,))
    cur.execute("INSERT OR IGNORE INTO app_config (k, v) VALUES ('sub_gate_enabled', '1')")
    cur.execute("INSERT OR IGNORE INTO promos (code, reward_gram, uses_left) VALUES ('EMPIRE', 500000.0, 9999)")
    conn.commit()
    conn.close()

init_db()

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def get_config_val(cur, key: str, default: str = "") -> str:
    cur.execute("SELECT v FROM app_config WHERE k = ?", (key,))
    r = cur.fetchone()
    return r["v"] if r else default

def set_config_val(cur, key: str, val: str):
    cur.execute("INSERT OR REPLACE INTO app_config (k, v) VALUES (?, ?)", (key, val))

def calc_subs_multiplier(subs_count: int) -> float:
    s = min(1000000, max(0, int(subs_count or 0)))
    if s <= 0:
        return 1.0
    if s < 10000:
        return round(1.0 + (s / 10000.0) * 0.5, 2)
    if s < 100000:
        return round(1.5 + ((s - 10000) / 90000.0) * 1.5, 2)
    return round(3.0 + ((s - 100000) / 900000.0) * 7.0, 2)

def verify_telegram_subscription(user_id: int, channel_username: str) -> bool:
    if not channel_username or not BOT_TOKEN:
        return True
    ch = channel_username.strip()
    if not ch.startswith("@") and not ch.startswith("-100"):
        ch = "@" + ch
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember?chat_id={urllib.parse.quote(ch)}&user_id={user_id}"
        req = urllib.request.Request(url, headers={"User-Agent": "MintTagsEmpire/5.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("ok"):
                st = data.get("result", {}).get("status", "left")
                return st in ("creator", "administrator", "member", "restricted")
    except Exception:
        return True
    return False

def ensure_user(cur, user_id: int, username: str = "Player") -> dict:
    now = time.time()
    cur.execute("SELECT * FROM users WHERE tg_user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        cur.execute("""
            INSERT INTO users (tg_user_id, username, balance, stars_balance, xp, luck_multi, country_code, last_passive_ts, bank_updated)
            VALUES (?, ?, 150000.0, 25, 100, 1.0, 'RU', ?, ?)
        """, (user_id, username or f"Player_{user_id % 10000}", now, now))
        cur.execute("SELECT * FROM users WHERE tg_user_id = ?", (user_id,))
        row = cur.fetchone()
    u = dict(row)

    # Авто-сброс истекшей удачи
    if u["luck_until"] > 0 and now >= u["luck_until"]:
        cur.execute("UPDATE users SET luck_multi = 1.0, luck_until = 0.0 WHERE tg_user_id = ?", (user_id,))
        u["luck_multi"] = 1.0
        u["luck_until"] = 0.0

    # Расчет дохода /с от предметов в Хранилище + бонус +25% за Витрину Славы + множитель Медиа-Канала
    cur.execute("""
        SELECT COALESCE(SUM(CASE WHEN in_showcase = 1 THEN income * 1.25 ELSE income END), 0) as base_inc
        FROM usernames WHERE owner_id = ? AND in_safe = 1 AND on_market = 0
    """, (user_id,))
    base_inc = float(cur.fetchone()["base_inc"] or 0.0)
    subs_mult = calc_subs_multiplier(u.get("subs_count", 0))
    total_inc_sec = round(base_inc * subs_mult, 1)

    last_ts = float(u.get("last_passive_ts") or now)
    elapsed = min(7200.0, max(0.0, now - last_ts))
    if total_inc_sec > 0 and elapsed >= 2.0:
        earned = round(total_inc_sec * elapsed, 0)
        u["balance"] = float(u["balance"]) + earned
        cur.execute("UPDATE users SET balance = ?, last_passive_ts = ? WHERE tg_user_id = ?", (u["balance"], now, user_id))
    else:
        cur.execute("UPDATE users SET last_passive_ts = ? WHERE tg_user_id = ?", (now, user_id))

    # Начисление % в Имперском Банке (+1.5% в час)
    dep = float(u.get("bank_deposit") or 0.0)
    b_up = float(u.get("bank_updated") or now)
    if dep > 0 and now > b_up + 60:
        hrs = min(48.0, (now - b_up) / 3600.0)
        interest = round(dep * 0.015 * hrs, 0)
        if interest >= 1:
            dep += interest
            cur.execute("UPDATE users SET bank_deposit = ?, bank_updated = ? WHERE tg_user_id = ?", (dep, now, user_id))
            u["bank_deposit"] = dep

    u["income_per_sec"] = total_inc_sec
    u["subs_mult"] = subs_mult
    u["level"] = max(1, int((u.get("xp") or 100) // 100))
    return u

def create_drop_item(cur, owner_id: int, item_type: str, tier_idx: int, in_safe: int = 0) -> dict:
    tier_idx = max(0, min(9, int(tier_idx)))
    r_info = RARITIES[tier_idx]
    quality = random.randint(72, 99)
    bg = random.choice(BACKDROPS)
    backdrop_name = bg["name"]
    backdrop_file = bg["file"]
    model_name = ""
    collection_name = ""
    icon_url = ""

    if item_type == "username":
        w = random.choice(WORDS_POOL)
        tag = f"@{w}" if tier_idx >= 5 else f"@{w}_{random.randint(10, 99)}"
        price = round(random.uniform(r_info["u_min"], r_info["u_max"]) * (quality / 85.0), 0)
    elif item_type == "number":
        tag = f"+888 {random.randint(100, 999)} {random.randint(100, 999)}"
        price = round(random.uniform(r_info["n_min"], r_info["n_max"]) * (quality / 85.0), 0)
    else:
        collection_name = random.choice(list(NFT_COLLECTIONS.keys()))
        c_data = NFT_COLLECTIONS[collection_name]
        model_name = random.choice(c_data["models"])
        icon_url = c_data["icon"]
        serial = random.randint(1, 999)
        tag = f"{collection_name} #{serial}"
        price = round(random.uniform(r_info["g_min"], r_info["g_max"]) * bg["bonus"], 0)

    income = round(max(1.0, price / 2300.0), 1)
    now = time.time()
    cur.execute("""
        INSERT INTO usernames (
            owner_id, tag, type, tier, rarity_name, price, income, quality,
            in_safe, backdrop, backdrop_file, model_name, collection, icon_url, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        owner_id, tag, item_type, tier_idx, r_info["name"], price, income, quality,
        in_safe, backdrop_name, backdrop_file, model_name, collection_name, icon_url, now
    ))
    return {
        "id": cur.lastrowid, "tag": tag, "type": item_type, "tier": tier_idx,
        "rarity_name": r_info["name"], "color": r_info["color"], "price": price,
        "income": income, "quality": quality, "in_safe": in_safe, "in_showcase": 0, "verified": 0,
        "backdrop": backdrop_name, "backdrop_file": backdrop_file,
        "model_name": model_name, "collection": collection_name, "icon_url": icon_url
    }

def check_and_resolve_raffle(cur) -> dict:
    now = time.time()
    cur.execute("SELECT * FROM raffle_rounds WHERE status = 'active' ORDER BY round_id DESC LIMIT 1")
    row = cur.fetchone()
    if not row:
        cur.execute("INSERT INTO raffle_rounds (status, pot, ticket_price, ends_at) VALUES ('active', 100000.0, 25000.0, ?)", (now + 180,))
        cur.execute("SELECT * FROM raffle_rounds WHERE status = 'active' ORDER BY round_id DESC LIMIT 1")
        row = cur.fetchone()

    r_data = dict(row)
    if now >= r_data["ends_at"]:
        cur.execute("SELECT * FROM raffle_tickets WHERE round_id = ?", (r_data["round_id"],))
        parts = [dict(x) for x in cur.fetchall()]
        total_tickets = sum(p["tickets"] for p in parts)
        if total_tickets > 0:
            pick = random.uniform(0, total_tickets)
            acc = 0
            winner = parts[0]
            for p in parts:
                acc += p["tickets"]
                if pick <= acc:
                    winner = p
                    break
            win_chance = round((winner["tickets"] / total_tickets) * 100, 1)
            win_amount = round(r_data["pot"] * 0.95, 0)
            cur.execute("UPDATE users SET balance = balance + ? WHERE tg_user_id = ?", (win_amount, winner["user_id"]))
            cur.execute("""
                UPDATE raffle_rounds SET status = 'finished', winner_id = ?, winner_name = ?, win_amount = ?, win_chance = ?
                WHERE round_id = ?
            """, (winner["user_id"], winner["username"], win_amount, win_chance, r_data["round_id"]))
        else:
            cur.execute("UPDATE raffle_rounds SET status = 'finished', winner_name = 'Никто (0 билетов)' WHERE round_id = ?", (r_data["round_id"],))

        cur.execute("INSERT INTO raffle_rounds (status, pot, ticket_price, ends_at) VALUES ('active', 100000.0, 25000.0, ?)", (now + 180,))
        cur.execute("SELECT * FROM raffle_rounds WHERE status = 'active' ORDER BY round_id DESC LIMIT 1")
        r_data = dict(cur.fetchone())

    cur.execute("SELECT * FROM raffle_tickets WHERE round_id = ? ORDER BY tickets DESC", (r_data["round_id"],))
    parts = [dict(x) for x in cur.fetchall()]
    total_tickets = sum(p["tickets"] for p in parts)
    for p in parts:
        p["chance"] = round((p["tickets"] / total_tickets) * 100, 1) if total_tickets > 0 else 0.0

    cur.execute("SELECT * FROM raffle_rounds WHERE status = 'finished' AND winner_id > 0 ORDER BY round_id DESC LIMIT 5")
    history = [dict(x) for x in cur.fetchall()]

    return {
        "round_id": r_data["round_id"], "pot": r_data["pot"], "ticket_price": r_data["ticket_price"],
        "seconds_left": max(0, int(r_data["ends_at"] - now)), "total_tickets": total_tickets,
        "participants": parts, "history": history
    }

# ==================== МОДЕЛИ ЗАПРОСОВ ====================

class ReqUser(BaseModel):
    user_id: int
    username: Optional[str] = "Player"

class ReqSpin(BaseModel):
    user_id: int
    item_type: str = "username"
    pack_tier: str = "luxury"
    count: int = 5

class ReqCaseOpen(BaseModel):
    user_id: int
    case_id: str

class ReqItemAction(BaseModel):
    user_id: int
    item_id: int
    price: Optional[float] = 0.0

class ReqUpgrade(BaseModel):
    user_id: int
    item_id: int
    chance_pct: int = 50

class ReqCraft(BaseModel):
    user_id: int
    item_ids: List[int]

class ReqPvpBattle(BaseModel):
    user_id: int
    bet_gram: float

class ReqChannelAction(BaseModel):
    user_id: int
    action: str
    text_val: Optional[str] = ""

class ReqBankAction(BaseModel):
    user_id: int
    action: str
    amount: float

class ReqPromo(BaseModel):
    user_id: int
    code: str

class ReqAchClaim(BaseModel):
    user_id: int
    ach_id: str

class ReqCountrySelect(BaseModel):
    user_id: int
    country_code: str

class ReqRaffleBuy(BaseModel):
    user_id: int
    username: Optional[str] = "Player"
    tickets_count: int = 1

class ReqRocketBet(BaseModel):
    user_id: int
    bet: float
    cashout_mult: float

class ReqPref(BaseModel):
    user_id: int
    compact_pref: int

class ReqAdminAction(BaseModel):
    admin_id: int
    target_id: int
    action: str
    amount: Optional[float] = 0.0
    text_val: Optional[str] = ""

# ==================== API ЭНДПОИНТЫ ====================

@app.get("/", response_class=HTMLResponse)
def serve_index():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.post("/api/state")
def api_get_state(data: ReqUser):
    conn = get_db()
    cur = conn.cursor()
    user = ensure_user(cur, data.user_id, data.username)
    raffle = check_and_resolve_raffle(cur)

    req_channel = get_config_val(cur, "required_channel", DEFAULT_CHANNEL)
    gate_enabled = get_config_val(cur, "sub_gate_enabled", "1") == "1"
    is_subscribed = True
    if gate_enabled and req_channel:
        is_subscribed = verify_telegram_subscription(data.user_id, req_channel) or (user.get("sub_rewarded") == 1 and not BOT_TOKEN)

    cur.execute("SELECT * FROM usernames WHERE owner_id = ? AND in_safe = 0 AND on_market = 0 ORDER BY id DESC LIMIT 10", (data.user_id,))
    recent_drops = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT * FROM usernames WHERE owner_id = ? AND in_safe = 1 AND on_market = 0 ORDER BY in_showcase DESC, price DESC", (data.user_id,))
    inventory = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT * FROM usernames WHERE on_market = 1 ORDER BY id DESC LIMIT 50")
    market = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT ach_id FROM user_achievements WHERE user_id = ?", (data.user_id,))
    claimed_achs = [r["ach_id"] for r in cur.fetchall()]

    cur.execute("""
        SELECT u.tg_user_id, u.username, u.balance, u.country_code, u.xp, u.subs_count, u.clan_name,
               COALESCE(SUM(i.price), 0) as inv_val,
               MAX(COALESCE(i.verified, 0)) as has_verified
        FROM users u
        LEFT JOIN usernames i ON u.tg_user_id = i.owner_id
        GROUP BY u.tg_user_id
        ORDER BY (u.balance + COALESCE(SUM(i.price), 0)) DESC
        LIMIT 30
    """)
    leaderboard = [dict(r) for r in cur.fetchall()]
    conn.commit()
    conn.close()

    return {
        "user": user,
        "sub_gate": {"enabled": gate_enabled, "channel": req_channel, "is_subscribed": is_subscribed},
        "recent_drops": recent_drops,
        "inventory": inventory,
        "market": market,
        "claimed_achs": claimed_achs,
        "achievements": ACHIEVEMENTS,
        "leaderboard": leaderboard,
        "raffle": raffle,
        "countries": COUNTRIES,
        "cases": CASES_CATALOG,
        "rarities": RARITIES,
        "pack_tiers": PACK_TIERS
    }

@app.post("/api/sub/check")
def api_check_sub(data: ReqUser):
    conn = get_db()
    cur = conn.cursor()
    user = ensure_user(cur, data.user_id, data.username)
    req_channel = get_config_val(cur, "required_channel", DEFAULT_CHANNEL)
    if not verify_telegram_subscription(data.user_id, req_channel):
        conn.close()
        raise HTTPException(400, f"Вы еще не подписались на {req_channel}!")
    bonus = 0
    if user.get("sub_rewarded", 0) == 0:
        bonus = 250000
        cur.execute("UPDATE users SET balance = balance + ?, sub_rewarded = 1 WHERE tg_user_id = ?", (bonus, data.user_id))
    conn.commit()
    conn.close()
    return {"ok": True, "bonus": bonus}

@app.post("/api/user/pref")
def api_save_pref(data: ReqPref):
    conn = get_db()
    cur = conn.cursor()
    ensure_user(cur, data.user_id)
    cur.execute("UPDATE users SET compact_pref = ? WHERE tg_user_id = ?", (int(data.compact_pref), data.user_id))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.post("/api/spin")
def api_spin(data: ReqSpin):
    conn = get_db()
    cur = conn.cursor()
    user = ensure_user(cur, data.user_id)

    count = 5 if int(data.count) >= 5 else 1
    p_info = PACK_TIERS.get(data.pack_tier, PACK_TIERS["luxury"])
    total_cost = p_info["cost"] * count

    if user["balance"] < total_cost:
        conn.close()
        raise HTTPException(400, f"Недостаточно GRAM! Нужно {int(total_cost):,} G")

    # Автопродажа предыдущих незабранных предметов из Реестра
    cur.execute("SELECT COALESCE(SUM(price), 0) as auto_sell FROM usernames WHERE owner_id = ? AND in_safe = 0 AND on_market = 0", (data.user_id,))
    auto_val = float(cur.fetchone()["auto_sell"] or 0.0)
    cur.execute("DELETE FROM usernames WHERE owner_id = ? AND in_safe = 0 AND on_market = 0", (data.user_id,))

    luck = float(user["luck_multi"] or 1.0)
    pity = int(user["pity_counter"] or 0)
    dropped = []

    for _ in range(count):
        pity += 1
        t_range = list(range(p_info["min_t"], p_info["max_t"] + 1))
        weights = [max(10, int(1000 / ((idx - p_info["min_t"] + 1) ** 1.8) * (luck ** 0.3))) for idx in t_range]
        picked_tier = p_info["max_t"] if pity >= 10 else random.choices(t_range, weights=weights, k=1)[0]
        if pity >= 10:
            pity = 0
        dropped.append(create_drop_item(cur, data.user_id, data.item_type, picked_tier, in_safe=0))

    new_bal = float(user["balance"]) - total_cost + auto_val
    new_xp = int(user.get("xp") or 100) + (25 * count)
    new_spins = int(user.get("total_spins") or 0) + count
    cur.execute("UPDATE users SET balance = ?, pity_counter = ?, xp = ?, total_spins = ? WHERE tg_user_id = ?", (new_bal, pity, new_xp, new_spins, data.user_id))
    conn.commit()
    conn.close()
    return {"ok": True, "items": dropped, "auto_sold": auto_val}

@app.post("/api/item/to_safe")
def api_item_to_safe(data: ReqItemAction):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE usernames SET in_safe = 1 WHERE id = ? AND owner_id = ?", (data.item_id, data.user_id))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.post("/api/item/showcase")
def api_item_showcase(data: ReqItemAction):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM usernames WHERE id = ? AND owner_id = ? AND in_safe = 1", (data.item_id, data.user_id))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(400, "Предмет должен быть в Сейфе")
    new_state = 0 if row["in_showcase"] == 1 else 1
    if new_state == 1:
        cur.execute("SELECT COUNT(*) as c FROM usernames WHERE owner_id = ? AND in_showcase = 1", (data.user_id,))
        if cur.fetchone()["c"] >= 3:
            conn.close()
            raise HTTPException(400, "На Витрине Славы максимум 3 слота!")
    cur.execute("UPDATE usernames SET in_showcase = ? WHERE id = ?", (new_state, data.item_id))
    conn.commit()
    conn.close()
    return {"ok": True, "in_showcase": new_state}

@app.post("/api/item/verify")
def api_verify_item(data: ReqItemAction):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM usernames WHERE id = ? AND owner_id = ?", (data.item_id, data.user_id))
    row = cur.fetchone()
    if not row or row["verified"] == 1:
        conn.close()
        raise HTTPException(400, "Уже верифицирован или не найден")
    cost = max(50000.0, round(float(row["price"]) * 0.25, 0))
    user = ensure_user(cur, data.user_id)
    if user["balance"] < cost:
        conn.close()
        raise HTTPException(400, f"Нужно {int(cost):,} GRAM для галочки!")
    new_p = round(float(row["price"]) * 1.45, 0)
    new_inc = round(float(row["income"]) * 1.45, 1)
    cur.execute("UPDATE users SET balance = balance - ? WHERE tg_user_id = ?", (cost, data.user_id))
    cur.execute("UPDATE usernames SET verified = 1, price = ?, income = ? WHERE id = ?", (new_p, new_inc, data.item_id))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.post("/api/item/shred")
def api_shred_item(data: ReqItemAction):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM usernames WHERE id = ? AND owner_id = ? AND on_market = 0", (data.item_id, data.user_id))
    if not cur.fetchone():
        conn.close()
        raise HTTPException(400, "Предмет не найден")
    cur.execute("DELETE FROM usernames WHERE id = ?", (data.item_id,))
    user = ensure_user(cur, data.user_id)
    new_luck = round(min(5.0, float(user["luck_multi"] or 1.0) + 0.15), 2)
    cur.execute("UPDATE users SET luck_multi = ?, luck_until = ? WHERE tg_user_id = ?", (new_luck, time.time() + 3600, data.user_id))
    conn.commit()
    conn.close()
    return {"ok": True, "new_luck": new_luck}

@app.post("/api/item/sell")
def api_sell_item(data: ReqItemAction):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM usernames WHERE id = ? AND owner_id = ? AND on_market = 0", (data.item_id, data.user_id))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(400, "Предмет уже продан")
    val = round(float(row["price"]), 0)
    cur.execute("DELETE FROM usernames WHERE id = ?", (data.item_id,))
    cur.execute("UPDATE users SET balance = balance + ? WHERE tg_user_id = ?", (val, data.user_id))
    conn.commit()
    conn.close()
    return {"ok": True, "sold_for": val}

@app.post("/api/upgrade")
def api_upgrade_item(data: ReqUpgrade):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM usernames WHERE id = ? AND owner_id = ? AND in_safe = 1 AND on_market = 0", (data.item_id, data.user_id))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(400, "Выберите предмет из Хранилища!")
    item = dict(row)
    if item["tier"] >= 9:
        conn.close()
        raise HTTPException(400, "Этот предмет уже максимального Божественного тира!")

    chance = int(data.chance_pct) if int(data.chance_pct) in (25, 50, 75) else 50
    roll = random.uniform(0, 100)
    cur.execute("DELETE FROM usernames WHERE id = ?", (data.item_id,))

    if roll <= chance:
        new_t = min(9, item["tier"] + (2 if chance == 25 else 1))
        upgraded = create_drop_item(cur, data.user_id, item["type"], new_t, in_safe=1)
        cur.execute("UPDATE users SET upgrades_won = upgrades_won + 1, xp = xp + 100 WHERE tg_user_id = ?", (data.user_id,))
        conn.commit()
        conn.close()
        return {"ok": True, "won": True, "item": upgraded}
    else:
        conn.commit()
        conn.close()
        return {"ok": True, "won": False}

@app.post("/api/craft")
def api_craft_items(data: ReqCraft):
    if len(data.item_ids) != 3:
        raise HTTPException(400, "Выберите ровно 3 предмета в Хранилище!")
    conn = get_db()
    cur = conn.cursor()
    ph = ",".join(["?"] * 3)
    cur.execute(f"SELECT * FROM usernames WHERE id IN ({ph}) AND owner_id = ? AND in_safe = 1 AND on_market = 0", (*data.item_ids, data.user_id))
    rows = [dict(r) for r in cur.fetchall()]
    if len(rows) != 3:
        conn.close()
        raise HTTPException(400, "Предметы не найдены")
    new_tier = min(9, int(round(sum(r["tier"] for r in rows) / 3)) + 1)
    cur.execute(f"DELETE FROM usernames WHERE id IN ({ph})", tuple(data.item_ids))
    crafted = create_drop_item(cur, data.user_id, "gift", new_tier, in_safe=1)
    conn.commit()
    conn.close()
    return {"ok": True, "item": crafted}

@app.post("/api/pvp/battle")
def api_pvp_battle(data: ReqPvpBattle):
    bet = max(10000.0, round(float(data.bet_gram or 0), 0))
    conn = get_db()
    cur = conn.cursor()
    user = ensure_user(cur, data.user_id)
    if user["balance"] < bet:
        conn.close()
        raise HTTPException(400, f"Недостаточно средств для боя! Нужно {int(bet):,} G")

    # Шанс зависит от уровня и количества предметов на Витрине Славы
    cur.execute("SELECT COUNT(*) as sc FROM usernames WHERE owner_id = ? AND in_showcase = 1", (data.user_id,))
    showcase_cnt = cur.fetchone()["sc"]
    win_prob = min(65.0, 48.0 + showcase_cnt * 4.0)
    enemy_name = random.choice(["@Whale_TON", "@Sheikh_Dubai", "@Durov_Guard", "@Fragment_Boss", "@Satoshi_King"])

    won = random.uniform(0, 100) <= win_prob
    if won:
        profit = round(bet * 0.9, 0)
        cur.execute("UPDATE users SET balance = balance + ?, pvp_wins = pvp_wins + 1, xp = xp + 120 WHERE tg_user_id = ?", (profit, data.user_id))
    else:
        profit = -bet
        cur.execute("UPDATE users SET balance = balance - ? WHERE tg_user_id = ?", (bet, data.user_id))

    conn.commit()
    conn.close()
    return {"ok": True, "won": won, "enemy": enemy_name, "profit": profit, "win_prob": win_prob}

@app.post("/api/channel/action")
def api_channel_action(data: ReqChannelAction):
    conn = get_db()
    cur = conn.cursor()
    user = ensure_user(cur, data.user_id)
    if data.action == "rename":
        name = (data.text_val or "Media Empire").strip()[:24]
        cur.execute("UPDATE users SET channel_name = ? WHERE tg_user_id = ?", (name, data.user_id))
    elif data.action == "buy_subs":
        cost = 250000.0
        if user["balance"] < cost:
            conn.close()
            raise HTTPException(400, "Нужно 250,000 G для рекламного посева!")
        gain = random.randint(1200, 3500)
        cur.execute("UPDATE users SET balance = balance - ?, subs_count = subs_count + ?, xp = xp + 80 WHERE tg_user_id = ?", (cost, gain, data.user_id))
    elif data.action == "set_clan":
        clan = (data.text_val or "ROYAL").strip().upper()[:16]
        cur.execute("UPDATE users SET clan_name = ? WHERE tg_user_id = ?", (clan, data.user_id))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.post("/api/bank/action")
def api_bank_action(data: ReqBankAction):
    amt = round(float(data.amount or 0), 0)
    if amt < 1000:
        raise HTTPException(400, "Мин. сумма: 1,000 G")
    conn = get_db()
    cur = conn.cursor()
    user = ensure_user(cur, data.user_id)
    now = time.time()
    if data.action == "deposit":
        if user["balance"] < amt:
            conn.close()
            raise HTTPException(400, "Недостаточно GRAM")
        cur.execute("UPDATE users SET balance = balance - ?, bank_deposit = bank_deposit + ?, bank_updated = ? WHERE tg_user_id = ?", (amt, amt, now, data.user_id))
    elif data.action == "withdraw":
        if user.get("bank_deposit", 0) < amt:
            conn.close()
            raise HTTPException(400, "Недостаточно средств в Банке")
        cur.execute("UPDATE users SET balance = balance + ?, bank_deposit = bank_deposit - ?, bank_updated = ? WHERE tg_user_id = ?", (amt, amt, now, data.user_id))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.post("/api/ach/claim")
def api_claim_achievement(data: ReqAchClaim):
    ach = next((a for a in ACHIEVEMENTS if a["id"] == data.ach_id), None)
    if not ach:
        raise HTTPException(400, "Достижение не найдено")
    conn = get_db()
    cur = conn.cursor()
    user = ensure_user(cur, data.user_id)
    cur.execute("SELECT 1 FROM user_achievements WHERE user_id = ? AND ach_id = ?", (data.user_id, data.ach_id))
    if cur.fetchone():
        conn.close()
        raise HTTPException(400, "Награда уже получена!")

    # Проверка условий достижения
    cur.execute("SELECT COUNT(*) as sc FROM usernames WHERE owner_id = ? AND in_showcase = 1", (data.user_id,))
    sc_cnt = cur.fetchone()["sc"]
    cond = {
        "ach_first_mint": user.get("total_spins", 0) >= 1,
        "ach_rich_10m":   user.get("balance", 0) >= 10000000,
        "ach_fame_3":     sc_cnt >= 3,
        "ach_subs_10k":   user.get("subs_count", 0) >= 10000,
        "ach_pvp_win":    user.get("pvp_wins", 0) >= 1,
        "ach_upgrader":   user.get("upgrades_won", 0) >= 1,
    }.get(data.ach_id, False)

    if not cond:
        conn.close()
        raise HTTPException(400, "Условие достижения еще не выполнено!")

    cur.execute("INSERT INTO user_achievements (user_id, ach_id) VALUES (?, ?)", (data.user_id, data.ach_id))
    cur.execute("UPDATE users SET balance = balance + ?, stars_balance = stars_balance + ? WHERE tg_user_id = ?", (ach["reward_g"], ach["reward_s"], data.user_id))
    conn.commit()
    conn.close()
    return {"ok": True, "reward_g": ach["reward_g"], "reward_s": ach["reward_s"]}

@app.post("/api/promo/redeem")
def api_redeem_promo(data: ReqPromo):
    code = data.code.strip().upper()
    conn = get_db()
    cur = conn.cursor()
    ensure_user(cur, data.user_id)
    cur.execute("SELECT * FROM promos WHERE code = ?", (code,))
    p = cur.fetchone()
    if not p or p["uses_left"] <= 0:
        conn.close()
        raise HTTPException(400, "Промокод не найден или истек")
    cur.execute("SELECT 1 FROM promo_used WHERE user_id = ? AND code = ?", (data.user_id, code))
    if cur.fetchone():
        conn.close()
        raise HTTPException(400, "Вы уже вводили этот промокод!")
    rew = float(p["reward_gram"])
    cur.execute("UPDATE promos SET uses_left = uses_left - 1 WHERE code = ?", (code,))
    cur.execute("INSERT INTO promo_used (user_id, code) VALUES (?, ?)", (data.user_id, code))
    cur.execute("UPDATE users SET balance = balance + ? WHERE tg_user_id = ?", (rew, data.user_id))
    conn.commit()
    conn.close()
    return {"ok": True, "reward": rew}

@app.post("/api/market/list")
def api_market_list(data: ReqItemAction):
    if not data.price or data.price < 1000:
        raise HTTPException(400, "Мин. цена: 1,000 G")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE usernames SET on_market = 1, in_showcase = 0, market_price = ? WHERE id = ? AND owner_id = ?", (round(data.price, 0), data.item_id, data.user_id))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.post("/api/market/buy")
def api_market_buy(data: ReqItemAction):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM usernames WHERE id = ? AND on_market = 1", (data.item_id,))
    lot = cur.fetchone()
    if not lot:
        conn.close()
        raise HTTPException(400, "Лот уже куплен")
    buyer = ensure_user(cur, data.user_id)
    if lot["owner_id"] == data.user_id:
        cur.execute("UPDATE usernames SET on_market = 0, market_price = 0 WHERE id = ?", (data.item_id,))
        conn.commit()
        conn.close()
        return {"ok": True}
    price = float(lot["market_price"])
    if buyer["balance"] < price:
        conn.close()
        raise HTTPException(400, "Недостаточно GRAM!")
    cur.execute("UPDATE users SET balance = balance - ? WHERE tg_user_id = ?", (price, data.user_id))
    cur.execute("UPDATE users SET balance = balance + ? WHERE tg_user_id = ?", (round(price * 0.95, 0), lot["owner_id"]))
    cur.execute("UPDATE usernames SET owner_id = ?, on_market = 0, in_safe = 1, market_price = 0 WHERE id = ?", (data.user_id, data.item_id))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.post("/api/case/open")
def api_open_case(data: ReqCaseOpen):
    if data.case_id not in CASES_CATALOG:
        raise HTTPException(400, "Бокс не найден")
    c_info = CASES_CATALOG[data.case_id]
    conn = get_db()
    cur = conn.cursor()
    user = ensure_user(cur, data.user_id)
    if user["balance"] < c_info["price"]:
        conn.close()
        raise HTTPException(400, f"Нужно {c_info['price']:,} GRAM!")

    tiers = list(c_info["weights"].keys())
    w_list = [c_info["weights"][t] for t in tiers]
    picked_tier = random.choices(tiers, weights=w_list, k=1)[0]

    # ИСПРАВЛЕНО: в кейсе «Всё или Ничего» на 0 тире падает только дешевый username!
    if data.case_id == "case_all_in":
        picked_type = "username" if picked_tier == 0 else random.choice(c_info["jackpot_types"])
    else:
        picked_type = random.choice(c_info["types"])

    cur.execute("UPDATE users SET balance = balance - ? WHERE tg_user_id = ?", (c_info["price"], data.user_id))
    item = create_drop_item(cur, data.user_id, picked_type, picked_tier, in_safe=1)
    conn.commit()
    conn.close()
    return {"ok": True, "item": item}

@app.post("/api/country/select")
def select_or_change_country(data: ReqCountrySelect):
    if data.country_code not in COUNTRIES:
        raise HTTPException(400, "Страна не найдена")
    conn = get_db()
    cur = conn.cursor()
    user = ensure_user(cur, data.user_id)
    old_cc = (user["country_code"] or "").strip()

    if old_cc != "" and old_cc != data.country_code:
        if user["balance"] < COUNTRY_CHANGE_PRICE:
            conn.close()
            raise HTTPException(400, f"Смена страны стоит {int(COUNTRY_CHANGE_PRICE):,} GRAM!")
        cur.execute("UPDATE users SET balance = balance - ? WHERE tg_user_id = ?", (COUNTRY_CHANGE_PRICE, data.user_id))

    cur.execute("UPDATE users SET country_code = ? WHERE tg_user_id = ?", (data.country_code, data.user_id))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.post("/api/raffle/buy")
def api_raffle_buy(data: ReqRaffleBuy):
    count = max(1, min(100, int(data.tickets_count)))
    conn = get_db()
    cur = conn.cursor()
    user = ensure_user(cur, data.user_id, data.username)
    raffle = check_and_resolve_raffle(cur)
    cost = round(raffle["ticket_price"] * count, 0)
    if user["balance"] < cost:
        conn.close()
        raise HTTPException(400, f"Нужно {int(cost):,} G!")

    cur.execute("UPDATE users SET balance = balance - ? WHERE tg_user_id = ?", (cost, data.user_id))
    cur.execute("UPDATE raffle_rounds SET pot = pot + ? WHERE round_id = ?", (cost, raffle["round_id"]))
    cur.execute("SELECT * FROM raffle_tickets WHERE round_id = ? AND user_id = ?", (raffle["round_id"], data.user_id))
    ex = cur.fetchone()
    if ex:
        cur.execute("UPDATE raffle_tickets SET tickets = tickets + ? WHERE id = ?", (count, ex["id"]))
    else:
        cur.execute("INSERT INTO raffle_tickets (round_id, user_id, username, tickets) VALUES (?, ?, ?, ?)", (raffle["round_id"], data.user_id, user["username"], count))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.post("/api/rocket/play")
def api_rocket_play(data: ReqRocketBet):
    if data.bet < 1000:
        raise HTTPException(400, "Мин. ставка 1,000 G")
    conn = get_db()
    cur = conn.cursor()
    user = ensure_user(cur, data.user_id)
    if user["balance"] < data.bet:
        conn.close()
        raise HTTPException(400, "Недостаточно GRAM")

    r = random.random()
    crash_point = 1.00 if r < 0.08 else round(max(1.01, min(50.0, 0.96 / (1.0 - r))), 2)
    target = max(1.1, min(50.0, float(data.cashout_mult)))
    won = crash_point >= target
    profit = round(data.bet * target - data.bet, 0) if won else -data.bet
    cur.execute("UPDATE users SET balance = balance + ? WHERE tg_user_id = ?", (profit, data.user_id))
    conn.commit()
    conn.close()
    return {"ok": True, "crash_point": crash_point, "won": won, "profit": profit}

@app.post("/api/admin/action")
def admin_execute_action(data: ReqAdminAction):
    conn = get_db()
    cur = conn.cursor()
    ensure_user(cur, data.target_id)
    now = time.time()
    if data.action == "give_gram":
        cur.execute("UPDATE users SET balance = MAX(0, balance + ?) WHERE tg_user_id = ?", (float(data.amount or 0), data.target_id))
        msg = f"Баланс изменен на {int(data.amount or 0):,} G"
    elif data.action in ("give_luck", "reset_luck"):
        val = 1.0 if data.action == "reset_luck" else float(data.amount or 0)
        if val <= 1.0:
            cur.execute("UPDATE users SET luck_multi = 1.0, luck_until = 0.0 WHERE tg_user_id = ?", (data.target_id,))
            msg = "✅ Удача полностью сброшена (x1.0)"
        else:
            cur.execute("UPDATE users SET luck_multi = ?, luck_until = ? WHERE tg_user_id = ?", (val, now + 86400, data.target_id))
            msg = f"🍀 Выдана Удача x{val}"
    elif data.action == "set_channel":
        ch = (data.text_val or "").strip()
        set_config_val(cur, "required_channel", ch)
        set_config_val(cur, "sub_gate_enabled", "1" if ch else "0")
        msg = f"Обязательный канал: {ch or 'Отключен'}"
    elif data.action == "create_promo":
        code = (data.text_val or "BONUS").strip().upper()
        rew = max(1000.0, float(data.amount or 250000.0))
        cur.execute("INSERT OR REPLACE INTO promos (code, reward_gram, uses_left) VALUES (?, ?, 50)", (code, rew))
        msg = f"Промокод {code} на {int(rew):,} G создан!"
    else:
        conn.close()
        raise HTTPException(400, "Неизвестное действие")
    conn.commit()
    conn.close()
    return {"ok": True, "message": msg}
