import os
import time
import math
import json
import random
import sqlite3
import urllib.request
import zipfile
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="MintTags Global Empire v4.0 Premium")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === АВТОМАТИЧЕСКАЯ ЗАГРУЗКА АССЕТОВ ===
# Этот блок сам скачает и распакует картинки при старте сервера
if not os.path.exists("assets"):
    try:
        print("Downloading assets...")
        urllib.request.urlretrieve("https://github.com/diedaxit/tg-market-app/raw/main/MintTags-Global-Empire-v4-Full.zip", "assets.zip")
        with zipfile.ZipFile("assets.zip", 'r') as zip_ref:
            zip_ref.extractall(".")
        os.remove("assets.zip")
        print("Assets extracted successfully!")
    except Exception as e:
        print("Failed to download assets:", e)

# Подключение папок с ассетами, иконками и фонами
if os.path.isdir("assets"):
    app.mount("/assets", StaticFiles(directory="assets"), name="assets")
if os.path.isdir("icons"):
    app.mount("/icons", StaticFiles(directory="icons"), name="icons")
if os.path.isdir("backdrops"):
    app.mount("/backdrops", StaticFiles(directory="backdrops"), name="backdrops")

DB_PATH = os.getenv("DB_PATH", "minttags_empire.db")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# ==================== СПРАВОЧНИКИ И КАТАЛОГИ ====================

COUNTRIES = {
    "RU": {"name": "Россия", "flag": "🇷🇺", "prefix": "+7"},
    "US": {"name": "США", "flag": "🇺🇸", "prefix": "+1"},
    "AE": {"name": "ОАЭ (Дубай)", "flag": "🇦🇪", "prefix": "+971"},
    "GB": {"name": "Великобритания", "flag": "🇬🇧", "prefix": "+44"},
    "DE": {"name": "Германия", "flag": "🇩🇪", "prefix": "+49"},
    "CH": {"name": "Швейцария", "flag": "🇨🇭", "prefix": "+41"},
    "JP": {"name": "Япония", "flag": "🇯🇵", "prefix": "+81"},
    "KZ": {"name": "Казахстан", "flag": "🇰🇿", "prefix": "+7"},
    "UA": {"name": "Украина", "flag": "🇺🇦", "prefix": "+380"},
    "BY": {"name": "Беларусь", "flag": "🇧🇾", "prefix": "+375"},
}

COUNTRY_CHANGE_PRICE = 500_000.0

RARITIES = [
    {"tier": 0, "name": "Common",    "color": "#94a3b8", "u_min": 250,       "u_max": 980,        "n_min": 20000,     "n_max": 68000,      "g_min": 35000,      "g_max": 95000},
    {"tier": 1, "name": "Uncommon",  "color": "#10b981", "u_min": 1100,      "u_max": 3800,       "n_min": 75000,     "n_max": 180000,     "g_min": 110000,     "g_max": 260000},
    {"tier": 2, "name": "Rare",      "color": "#24a1de", "u_min": 4500,      "u_max": 15000,      "n_min": 200000,    "n_max": 480000,     "g_min": 300000,     "g_max": 750000},
    {"tier": 3, "name": "Epic",      "color": "#8b5cf6", "u_min": 18000,     "u_max": 65000,      "n_min": 550000,    "n_max": 1400000,    "g_min": 850000,     "g_max": 2200000},
    {"tier": 4, "name": "Legendary", "color": "#f59e0b", "u_min": 75000,     "u_max": 280000,     "n_min": 1600000,   "n_max": 4500000,    "g_min": 2500000,    "g_max": 6800000},
    {"tier": 5, "name": "Mythic",    "color": "#ec8cbd", "u_min": 320000,    "u_max": 1200000,    "n_min": 5000000,   "n_max": 15000000,   "g_min": 7500000,    "g_max": 22000000},
    {"tier": 6, "name": "Immortal",  "color": "#ef4444", "u_min": 1500000,   "u_max": 5500000,    "n_min": 18000000,  "n_max": 50000000,   "g_min": 25000000,   "g_max": 75000000},
    {"tier": 7, "name": "Celestial", "color": "#06b6d4", "u_min": 6000000,   "u_max": 22000000,   "n_min": 55000000,  "n_max": 160000000,  "g_min": 80000000,   "g_max": 240000000},
    {"tier": 8, "name": "Exclusive", "color": "#d6b16b", "u_min": 25000000,  "u_max": 95000000,   "n_min": 180000000, "n_max": 550000000,  "g_min": 260000000,  "g_max": 850000000},
    {"tier": 9, "name": "Divine",    "color": "#ffffff", "u_min": 100000000, "u_max": 500000000,  "n_min": 600000000, "n_max": 2500000000, "g_min": 900000000,  "g_max": 5000000000},
]

# Реальные коллекции, модели и фоны из Telegram Gifts
NFT_COLLECTIONS = {
    "Plush Pepe": {
        "icon": "/assets/genesis-pepe.webp",
        "svg_id": "pepe",
        "min_tier": 4,
        "models": ["Genesis Gold", "Red Menace", "Ninja Mike", "Cyber Toad", "Emerald King", "Polka Dots", "Diamond Frog", "Vantablack Pepe"]
    },
    "Swiss Watch": {
        "icon": "/assets/swiss-watch.webp",
        "svg_id": "watch",
        "min_tier": 3,
        "models": ["Tourbillon Cyan", "Royal Gold", "Carbon Chrono", "Titanium Zero", "Geneva Skeleton", "Deep Sea", "Astral Dial"]
    },
    "Durov's Cap": {
        "icon": "/assets/durov-chest.webp",
        "svg_id": "cap",
        "min_tier": 4,
        "models": ["Founder Black", "TON Stealth", "Resistance Edition", "Telegram Blue", "Encrypted Crown", "Zero Knowledge"]
    },
    "Resistance Dog": {
        "icon": "/assets/durov-chest.webp",
        "svg_id": "redo",
        "min_tier": 3,
        "models": ["Hoodie White", "Cyber Hound", "Golden REDO", "Night Watch", "Paper Plane Guardian", "Neon Bark"]
    },
    "Low Rider": {
        "icon": "/assets/sheikh-case.webp",
        "svg_id": "car",
        "min_tier": 3,
        "models": ["Dubai Gold", "Westside Chrome", "Midnight Purple", "Emerald Hydraulics", "Cyber Coupe"]
    },
    "Mini Oscar": {
        "icon": "/assets/sheikh-case.webp",
        "svg_id": "oscar",
        "min_tier": 2,
        "models": ["Pure Gold", "Platinum Idol", "Obsidian Knight", "Diamond Award"]
    },
    "Astral Shard": {
        "icon": "/assets/all-in.webp",
        "svg_id": "shard",
        "min_tier": 2,
        "models": ["Crimson Core", "Void Crystal", "Ether Prism", "Quantum Nova"]
    },
    "Diamond Ring": {
        "icon": "/assets/sheikh-case.webp",
        "svg_id": "ring",
        "min_tier": 2,
        "models": ["Solitaire 10ct", "Emerald Cut", "Royal Sapphire", "Black Diamond"]
    },
    "Vintage Cigar": {
        "icon": "/assets/sheikh-case.webp",
        "svg_id": "cigar",
        "min_tier": 1,
        "models": ["Havana Gold", "Syndicate Reserve", " Emperor Leaf"]
    },
    "Genie Lamp": {
        "icon": "/assets/sheikh-case.webp",
        "svg_id": "lamp",
        "min_tier": 1,
        "models": ["Arabian Gold", "Mystic Sapphire", "Ancient Brass"]
    }
}

BACKDROPS = [
    {"name": "Black",           "file": "/backdrops/Black.svg",           "rarity_bonus": 1.45, "special": "[BLACKOUT]"},
    {"name": "Onyx Black",      "file": "/backdrops/Onyx_Black.svg",      "rarity_bonus": 1.40, "special": "[BLACKOUT]"},
    {"name": "Pure Gold",       "file": "/backdrops/Pure_Gold.svg",       "rarity_bonus": 1.35, "special": "[GOLD]"},
    {"name": "Satin Gold",      "file": "/backdrops/Satin_Gold.svg",      "rarity_bonus": 1.25, "special": ""},
    {"name": "Cyberpunk",       "file": "/backdrops/Cyberpunk.svg",       "rarity_bonus": 1.30, "special": "[CYBER]"},
    {"name": "Electric Purple", "file": "/backdrops/Electric_Purple.svg", "rarity_bonus": 1.20, "special": ""},
    {"name": "Electric Indigo", "file": "/backdrops/Electric_Indigo.svg", "rarity_bonus": 1.15, "special": ""},
    {"name": "Neon Blue",       "file": "/backdrops/Neon_Blue.svg",       "rarity_bonus": 1.20, "special": ""},
    {"name": "Sapphire",        "file": "/backdrops/Sapphire.svg",        "rarity_bonus": 1.15, "special": ""},
    {"name": "Pacific Cyan",    "file": "/backdrops/Pacific_Cyan.svg",    "rarity_bonus": 1.15, "special": ""},
    {"name": "Emerald",         "file": "/backdrops/Emerald.svg",         "rarity_bonus": 1.25, "special": ""},
    {"name": "Mint Green",      "file": "/backdrops/Mint_Green.svg",      "rarity_bonus": 1.10, "special": ""},
    {"name": "Malachite",       "file": "/backdrops/Malachite.svg",       "rarity_bonus": 1.15, "special": ""},
    {"name": "Midnight Blue",   "file": "/backdrops/Midnight_Blue.svg",   "rarity_bonus": 1.15, "special": ""},
    {"name": "Platinum",        "file": "/backdrops/Platinum.svg",        "rarity_bonus": 1.25, "special": ""},
    {"name": "Burgundy",        "file": "/backdrops/Burgundy.svg",        "rarity_bonus": 1.10, "special": ""},
    {"name": "Mystic Pearl",    "file": "/backdrops/Mystic_Pearl.svg",    "rarity_bonus": 1.20, "special": ""},
]

CASES_CATALOG = {
    "case_all_in": {
        "id": "case_all_in",
        "name": "Всё или Ничего",
        "desc": "Жесткий риск! 99.85% дешевые @username, но есть шанс сорвать Exclusive или Divine артефакт!",
        "price": 10000,
        "currency": "gram",
        "img": "/assets/all-in.webp",
        "accent": "#ef4444",
        "types": ["username"],
        "jackpot_types": ["number", "gift"],
        "weights": {0: 99850, 8: 115, 9: 35}
    },
    "case_nft_box": {
        "id": "case_nft_box",
        "name": "NFT Gift Box",
        "desc": "100% выпадает только коллекционный NFT-подарок с моделью и фоном Telegram!",
        "price": 250000,
        "currency": "gram",
        "img": "/assets/genesis-pepe.webp",
        "accent": "#d6b16b",
        "types": ["gift"],
        "weights": {1: 3500, 2: 3200, 3: 1900, 4: 900, 5: 350, 6: 110, 7: 30, 8: 8, 9: 2}
    },
    "case_sheikh": {
        "id": "case_sheikh",
        "name": "Контейнер Шейха",
        "desc": "Золотой карбоновый дипломат. Анонимные номера +888 и люксовые лоурайдеры.",
        "price": 1200000,
        "currency": "gram",
        "img": "/assets/sheikh-case.webp",
        "accent": "#10b981",
        "types": ["number", "gift"],
        "weights": {2: 3000, 3: 3500, 4: 2000, 5: 1000, 6: 350, 7: 110, 8: 32, 9: 8}
    },
    "case_durov": {
        "id": "case_durov",
        "name": "Сундук Дурова",
        "desc": "Божественный реликт создателя. Только элитные теги, номера +888 и редчайшие гифты Blackout Edition.",
        "price": 5000000,
        "currency": "gram",
        "img": "/assets/durov-chest.webp",
        "accent": "#24a1de",
        "types": ["username", "number", "gift"],
        "weights": {4: 3800, 5: 3200, 6: 1800, 7: 850, 8: 280, 9: 70}
    }
}

WORDS_POOL = [
    "durov", "ton", "crypto", "whale", "fragment", "king", "sheikh", "viper", "shadow", "phantom",
    "genesis", "matrix", "satoshi", "diamond", "emerald", "cyber", "alpha", "omega", "prime", "legend",
    "sniper", "broker", "empire", "mint", "vault", "royal", "gold", "platinum", "astral", "khabib"
]

# ==================== БАЗА ДАННЫХ ====================

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
            balance REAL DEFAULT 25000.0,
            stars_balance INTEGER DEFAULT 50,
            luck_multi REAL DEFAULT 1.0,
            luck_until REAL DEFAULT 0.0,
            pity_counter INTEGER DEFAULT 0,
            country_code TEXT DEFAULT '',
            national_phone TEXT DEFAULT '',
            subs_count INTEGER DEFAULT 0,
            clan_id TEXT DEFAULT '',
            bank_deposit REAL DEFAULT 0.0,
            bank_Updated REAL DEFAULT 0.0,
            created_at REAL DEFAULT 0.0
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS usernames (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER,
            tag TEXT UNIQUE,
            type TEXT DEFAULT 'username',
            tier INTEGER DEFAULT 0,
            rarity_name TEXT DEFAULT 'Common',
            price REAL DEFAULT 500.0,
            verified INTEGER DEFAULT 0,
            in_safe INTEGER DEFAULT 1,
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
    # Миграция новых колонок, если их нет
    existing_cols = [r["name"] for r in cur.execute("PRAGMA table_info(usernames)").fetchall()]
    for col, ctype in [
        ("backdrop", "TEXT DEFAULT ''"),
        ("backdrop_file", "TEXT DEFAULT ''"),
        ("model_name", "TEXT DEFAULT ''"),
        ("collection", "TEXT DEFAULT ''"),
        ("icon_url", "TEXT DEFAULT ''"),
        ("verified", "INTEGER DEFAULT 0"),
        ("on_market", "INTEGER DEFAULT 0"),
        ("market_price", "REAL DEFAULT 0.0"),
    ]:
        if col not in existing_cols:
            try:
                cur.execute(f"ALTER TABLE usernames ADD COLUMN {col} {ctype}")
            except Exception:
                pass

    # Таблицы Аукциона Джекпота
    cur.execute("""
        CREATE TABLE IF NOT EXISTS raffle_rounds (
            round_id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT DEFAULT 'active',
            pot REAL DEFAULT 150000.0,
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
            tickets INTEGER DEFAULT 1,
            updated_at REAL DEFAULT 0.0
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def ensure_user(cur, user_id: int, username: str = "Player") -> dict:
    now = time.time()
    cur.execute("SELECT * FROM users WHERE tg_user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        cur.execute("""
            INSERT INTO users (tg_user_id, username, balance, stars_balance, luck_multi, luck_until, created_at, bank_Updated)
            VALUES (?, ?, 50000.0, 100, 1.0, 0.0, ?, ?)
        """, (user_id, username or f"Player_{user_id % 10000}", now, now))
        cur.execute("SELECT * FROM users WHERE tg_user_id = ?", (user_id,))
        row = cur.fetchone()
    user = dict(row)
    
    # Автоматический сброс истекшей удачи
    if user["luck_until"] > 0 and now >= user["luck_until"]:
        cur.execute("UPDATE users SET luck_multi = 1.0, luck_until = 0.0 WHERE tg_user_id = ?", (user_id,))
        user["luck_multi"] = 1.0
        user["luck_until"] = 0.0
    return user

def ensure_unique_tag_clean(cur, cand: dict) -> dict:
    cur.execute("SELECT 1 FROM usernames WHERE tag = ?", (cand["tag"],))
    if not cur.fetchone():
        return cand
    if cand["type"] == "username":
        base = cand["tag"].split("_")[0]
        for _ in range(15):
            test_tag = f"{base}_{random.randint(10, 999)}"
            cur.execute("SELECT 1 FROM usernames WHERE tag = ?", (test_tag,))
            if not cur.fetchone():
                cand["tag"] = test_tag
                return cand
        cand["tag"] = f"{base}_{random.randint(1000, 9999)}"
    elif cand["type"] == "number":
        for _ in range(15):
            test_num = f"+888 {random.randint(100, 999)} {random.randint(100, 999)}"
            cur.execute("SELECT 1 FROM usernames WHERE tag = ?", (test_num,))
            if not cur.fetchone():
                cand["tag"] = test_num
                return cand
        cand["tag"] = f"+888 {random.randint(1000, 9999)} {random.randint(10, 99)}"
    else:
        base_g = cand["tag"].split("#")[0].strip()
        badge = " [BLACKOUT]" if "[BLACKOUT]" in cand["tag"] else (" [GOLD]" if "[GOLD]" in cand["tag"] else "")
        cand["tag"] = f"{base_g} #{random.randint(101, 9999)}{badge}"
    return cand

def generate_item(cur, item_type: str, tier_idx: int) -> dict:
    tier_idx = max(0, min(9, int(tier_idx)))
    r_info = RARITIES[tier_idx]
    backdrop_name = ""
    backdrop_file = ""
    model_name = ""
    collection_name = ""
    icon_url = ""

    if item_type == "username":
        w = random.choice(WORDS_POOL)
        if tier_idx >= 7:
            tag = f"@{w[:3]}" if random.random() < 0.4 else f"@{w}"
        elif tier_idx >= 4:
            tag = f"@{w}{random.choice(['', '_vip', '_ton', '_x'])}"
        else:
            tag = f"@{w}_{random.randint(10, 999)}"
        price = round(random.uniform(r_info["u_min"], r_info["u_max"]), 0)
        bg = random.choice(BACKDROPS)
        backdrop_name = bg["name"]
        backdrop_file = bg["file"]

    elif item_type == "number":
        if tier_idx >= 7:
            d = random.choice(["000", "777", "888", "999", "111"])
            tag = f"+888 0{d[0]} {d} {d}"
        elif tier_idx >= 4:
            tag = f"+888 {random.randint(100, 999)} {random.choice(['777', '888', '000', '555'])}"
        else:
            tag = f"+888 {random.randint(100, 999)} {random.randint(100, 999)}"
        price = round(random.uniform(r_info["n_min"], r_info["n_max"]), 0)
        bg = random.choice(BACKDROPS)
        backdrop_name = bg["name"]
        backdrop_file = bg["file"]

    else:
        # NFT Gift с коллекцией, моделью и фоном
        eligible_cols = [k for k, v in NFT_COLLECTIONS.items() if v["min_tier"] <= max(tier_idx, 2)]
        if not eligible_cols:
            eligible_cols = list(NFT_COLLECTIONS.keys())
        collection_name = random.choice(eligible_cols)
        col_data = NFT_COLLECTIONS[collection_name]
        model_name = random.choice(col_data["models"])
        icon_url = col_data["icon"]

        # Повышенный шанс на Blackout / Pure Gold для высоких тиров
        if tier_idx >= 6 and random.random() < 0.45:
            bg = random.choice(BACKDROPS[:5])
        else:
            bg = random.choice(BACKDROPS)

        backdrop_name = bg["name"]
        backdrop_file = bg["file"]
        serial = random.randint(1, 99 if tier_idx >= 7 else 4999)
        special_suffix = f" {bg['special']}" if bg["special"] else ""
        tag = f"{collection_name} #{serial}{special_suffix}"
        base_price = random.uniform(r_info["g_min"], r_info["g_max"])
        price = round(base_price * bg["rarity_bonus"], 0)
        if serial <= 10:
            price = round(price * 1.5, 0)

    cand = {
        "tag": tag,
        "type": item_type,
        "tier": tier_idx,
        "rarity_name": r_info["name"],
        "price": price,
        "backdrop": backdrop_name,
        "backdrop_file": backdrop_file,
        "model_name": model_name,
        "collection": collection_name,
        "icon_url": icon_url
    }
    return ensure_unique_tag_clean(cur, cand)

def check_and_resolve_raffle(cur) -> dict:
    now = time.time()
    cur.execute("SELECT * FROM raffle_rounds WHERE status = 'active' ORDER BY round_id DESC LIMIT 1")
    row = cur.fetchone()
    if not row:
        ends = now + 180  # 3 минуты на раунд
        cur.execute("INSERT INTO raffle_rounds (status, pot, ticket_price, ends_at) VALUES ('active', 100000.0, 25000.0, ?)", (ends,))
        cur.execute("SELECT * FROM raffle_rounds WHERE status = 'active' ORDER BY round_id DESC LIMIT 1")
        row = cur.fetchone()

    r_data = dict(row)
    # Розыгрыш банка
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
            win_amount = round(r_data["pot"] * 0.95, 0)  # 5% комиссия
            cur.execute("UPDATE users SET balance = balance + ? WHERE tg_user_id = ?", (win_amount, winner["user_id"]))
            cur.execute("""
                UPDATE raffle_rounds
                SET status = 'finished', winner_id = ?, winner_name = ?, win_amount = ?, win_chance = ?
                WHERE round_id = ?
            """, (winner["user_id"], winner["username"], win_amount, win_chance, r_data["round_id"]))
        else:
            cur.execute("UPDATE raffle_rounds SET status = 'finished', winner_name = 'Никто (0 билетов)' WHERE round_id = ?", (r_data["round_id"],))

        new_ends = now + 180
        cur.execute("INSERT INTO raffle_rounds (status, pot, ticket_price, ends_at) VALUES ('active', 100000.0, 25000.0, ?)", (new_ends,))
        cur.execute("SELECT * FROM raffle_rounds WHERE status = 'active' ORDER BY round_id DESC LIMIT 1")
        r_data = dict(cur.fetchone())

    # Статистика текущего раунда
    cur.execute("SELECT * FROM raffle_tickets WHERE round_id = ? ORDER BY tickets DESC", (r_data["round_id"],))
    parts = [dict(x) for x in cur.fetchall()]
    total_tickets = sum(p["tickets"] for p in parts)
    for p in parts:
        p["chance"] = round((p["tickets"] / total_tickets) * 100, 1) if total_tickets > 0 else 0.0

    cur.execute("SELECT * FROM raffle_rounds WHERE status = 'finished' AND winner_id > 0 ORDER BY round_id DESC LIMIT 5")
    history = [dict(x) for x in cur.fetchall()]

    return {
        "round_id": r_data["round_id"],
        "pot": r_data["pot"],
        "ticket_price": r_data["ticket_price"],
        "ends_at": r_data["ends_at"],
        "seconds_left": max(0, int(r_data["ends_at"] - now)),
        "total_tickets": total_tickets,
        "participants": parts,
        "history": history
    }

# ==================== ЭНДПОИНТЫ ====================

@app.post("/api/state")
def api_get_state(data: ReqUser):
    conn = get_db()
    cur = conn.cursor()
    user = ensure_user(cur, data.user_id, data.username)
    raffle = check_and_resolve_raffle(cur)

    cur.execute("SELECT * FROM usernames WHERE owner_id = ? AND on_market = 0 ORDER BY price DESC", (data.user_id,))
    inventory = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT * FROM usernames WHERE on_market = 1 ORDER BY id DESC LIMIT 60")
    market = [dict(r) for r in cur.fetchall()]

    cur.execute("""
        SELECT u.tg_user_id, u.username, u.balance, u.country_code,
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

    now = time.time()
    luck_rem = max(0, int(user["luck_until"] - now)) if user["luck_until"] > now else 0

    return {
        "user": user,
        "luck_remaining": luck_rem,
        "inventory": inventory,
        "market": market,
        "leaderboard": leaderboard,
        "raffle": raffle,
        "countries": COUNTRIES,
        "country_change_price": COUNTRY_CHANGE_PRICE,
        "cases": CASES_CATALOG,
        "rarities": RARITIES
    }

@app.post("/api/case/open")
def api_open_case(data: ReqCaseOpen):
    if data.case_id not in CASES_CATALOG:
        raise HTTPException(400, "Кейс не найден")
    c_info = CASES_CATALOG[data.case_id]

    conn = get_db()
    cur = conn.cursor()
    user = ensure_user(cur, data.user_id)

    if user["balance"] < c_info["price"]:
        conn.close()
        raise HTTPException(400, f"Недостаточно средств! Цена кейса: {c_info['price']:,} G")

    luck = float(user["luck_multi"] or 1.0)
    tiers = list(c_info["weights"].keys())
    w_list = []
    for t in tiers:
        base_w = c_info["weights"][t]
        if t >= 5 and luck > 1.0:
            base_w = int(base_w * min(3.5, 1.0 + (luck - 1.0) * 0.25))
        w_list.append(base_w)

    picked_tier = random.choices(tiers, weights=w_list, k=1)[0]

    # Фикс All-In: номера и гифты только с джекпота
    if data.case_id == "case_all_in":
        if picked_tier == 0:
            picked_type = "username"
        else:
            picked_type = random.choice(c_info.get("jackpot_types", ["gift", "number"]))
    else:
        picked_type = random.choice(c_info["types"])

    item = generate_item(cur, picked_type, picked_tier)
    cur.execute("UPDATE users SET balance = balance - ? WHERE tg_user_id = ?", (c_info["price"], data.user_id))
    cur.execute("""
        INSERT INTO usernames (owner_id, tag, type, tier, rarity_name, price, backdrop, backdrop_file, model_name, collection, icon_url, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.user_id, item["tag"], item["type"], item["tier"], item["rarity_name"], item["price"],
        item["backdrop"], item["backdrop_file"], item["model_name"], item["collection"], item["icon_url"], time.time()
    ))
    item["id"] = cur.lastrowid
    conn.commit()
    conn.close()
    return {"ok": True, "item": item, "case": c_info}

@app.post("/api/country/select")
def select_or_change_country(data: ReqCountrySelect):
    if data.country_code not in COUNTRIES:
        raise HTTPException(400, "Выберите корректную страну")

    conn = get_db()
    cur = conn.cursor()
    user = ensure_user(cur, data.user_id)
    bal = float(user["balance"])
    old_cc = user["country_code"] or ""

    charged = 0.0
    if old_cc and old_cc != data.country_code:
        if bal < COUNTRY_CHANGE_PRICE:
            conn.close()
            raise HTTPException(400, f"Смена юрисдикции стоит {int(COUNTRY_CHANGE_PRICE):,} GRAM!")
        charged = COUNTRY_CHANGE_PRICE
        cur.execute("UPDATE users SET balance = balance - ? WHERE tg_user_id = ?", (charged, data.user_id))

    prefix = COUNTRIES[data.country_code]["prefix"]
    new_phone = f"{prefix} ({random.randint(900, 999)}) {random.randint(100, 999)}-{random.randint(10, 99)}-{random.randint(10, 99)}"
    cur.execute("UPDATE users SET country_code = ?, national_phone = ? WHERE tg_user_id = ?", (data.country_code, new_phone, data.user_id))
    conn.commit()
    conn.close()
    return {"ok": True, "country_code": data.country_code, "national_phone": new_phone, "charged": charged}

@app.post("/api/raffle/buy")
def api_raffle_buy(data: ReqRaffleBuy):
    count = max(1, min(100, int(data.tickets_count)))
    conn = get_db()
    cur = conn.cursor()
    user = ensure_user(cur, data.user_id, data.username)
    raffle = check_and_resolve_raffle(cur)

    total_cost = round(raffle["ticket_price"] * count, 0)
    if user["balance"] < total_cost:
        conn.close()
        raise HTTPException(400, f"Нужно {int(total_cost):,} G для покупки {count} бил.")

    now = time.time()
    cur.execute("UPDATE users SET balance = balance - ? WHERE tg_user_id = ?", (total_cost, data.user_id))
    cur.execute("UPDATE raffle_rounds SET pot = pot + ? WHERE round_id = ?", (total_cost, raffle["round_id"]))

    cur.execute("SELECT * FROM raffle_tickets WHERE round_id = ? AND user_id = ?", (raffle["round_id"], data.user_id))
    existing = cur.fetchone()
    if existing:
        cur.execute("UPDATE raffle_tickets SET tickets = tickets + ?, updated_at = ? WHERE id = ?", (count, now, existing["id"]))
    else:
        cur.execute("INSERT INTO raffle_tickets (round_id, user_id, username, tickets, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (raffle["round_id"], data.user_id, user["username"], count, now))

    updated_raffle = check_and_resolve_raffle(cur)
    conn.commit()
    conn.close()
    return {"ok": True, "raffle": updated_raffle}

@app.post("/api/admin/action")
def admin_execute_action(data: ReqAdminAction):
    conn = get_db()
    cur = conn.cursor()
    ensure_user(cur, data.target_id)
    now = time.time()

    if data.action == "give_gram":
        cur.execute("UPDATE users SET balance = MAX(0, balance + ?) WHERE tg_user_id = ?", (float(data.amount or 0), data.target_id))
        msg = f"Баланс изменен на {int(data.amount or 0):,} G"
    elif data.action == "give_luck":
        val = float(data.amount or 0)
        if val <= 1.0:
            cur.execute("UPDATE users SET luck_multi = 1.0, luck_until = 0.0 WHERE tg_user_id = ?", (data.target_id,))
            msg = "Буст удачи полностью сброшен (x1.0)"
        else:
            cur.execute("UPDATE users SET luck_multi = ?, luck_until = ? WHERE tg_user_id = ?", (val, now + 86400, data.target_id))
            msg = f"Выдана Удача x{val} на 24 часа"
    elif data.action == "reset_luck":
        cur.execute("UPDATE users SET luck_multi = 1.0, luck_until = 0.0 WHERE tg_user_id = ?", (data.target_id,))
        msg = "Удача принудительно отключена (x1.0)"
    else:
        conn.close()
        raise HTTPException(400, "Неизвестное действие")

    conn.commit()
    conn.close()
    return {"ok": True, "message": msg}
