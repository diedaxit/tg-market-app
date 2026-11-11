import os
import time
import json
import random
import sqlite3
import urllib.request
from typing import Optional, List
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="MintTags: Global Empire 2.0 Full")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== СТАТИКА С КЭШИРОВАНИЕМ (0% НАГРУЗКИ НА RENDER) ====================
class CachedStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=2592000, immutable"
        return response

for folder in ["assets", "assets/cases", "assets/nft", "icons", "backdrops"]:
    os.makedirs(folder, exist_ok=True)
    # ==================== АВТО-КОНВЕРТАЦИЯ ЛЮБЫХ PNG/JPG В ЛЕГКИЙ ПРОЗРАЧНЫЙ WEBP НА СЕРВЕРЕ ====================
def auto_build_webp_assets():
    try:
        from PIL import Image
    except ImportError:
        return

    for root, _, files in os.walk("assets"):
        for f in files:
            if f.lower().endswith((".png", ".jpg", ".jpeg")):
                src = os.path.join(root, f)
                dst = os.path.join(root, os.path.splitext(f)[0] + ".webp")
                if not os.path.exists(dst):
                    try:
                        im = Image.open(src).convert("RGBA")
                        im.thumbnail((512, 512), Image.Resampling.LANCZOS)
                        # Автоматически убираем чисто чёрный фон (#000000) в прозрачность
                        pixels = im.getdata()
                        im.putdata([
                            (0, 0, 0, 0) if (r < 12 and g < 12 and b < 12) else (r, g, b, a)
                            for r, g, b, a in pixels
                        ])
                        im.save(dst, "WEBP", quality=82, method=6)
                    except Exception as e:
                        print(f"[WEBP] Skip {f}: {e}")

auto_build_webp_assets()

# Обновляем привязку всех 10 категорий и 14 кейсов к новым WebP-файлам
CATEGORY_IMAGE_MAP = {
    "plush": "/assets/nft/gold_pepe.webp",
    "watches": "/assets/nft/chronos_watch.webp",
    "royal": "/assets/nft/imperial_crown.webp",
    "telegram": "/assets/nft/durov_cap.webp",
    "cyberpunk": "/assets/nft/durov_mask.webp",
    "resistance": "/assets/dog.webp",
    "gaming": "/assets/nft/cyber_katana.webp",
    "genesis": "/assets/nft/genesis_shard.webp",
    "luxury": "/assets/cases/emerald_vault_chest.webp",
    "seasonal": "/assets/nft/genesis_shard.webp",
}

for item in NFT_CATALOG_500:
    if item["category"] in CATEGORY_IMAGE_MAP:
        item["image"] = CATEGORY_IMAGE_MAP[item["category"]]

CASE_IMAGE_MAP = {
    "case_emerald_vault": "/assets/cases/emerald_vault_chest.webp",
    "case_founder_mask": "/assets/cases/founder_emerald_case.webp",
    "case_all_in": "/assets/cases/all_in_case.webp",
    "case_standard": "/assets/cases/fragment_box.webp",
    "case_premium": "/assets/cases/fragment_box.webp",
    "case_elite": "/assets/cases/founder_emerald_case.webp",
    "case_luxury": "/assets/cases/jackpot_box.webp",
    "case_fragment": "/assets/cases/fragment_box.webp",
    "case_nft": "/assets/cases/founder_emerald_case.webp",
    "case_jackpot": "/assets/cases/jackpot_box.webp",
    "case_star": "/assets/cases/jackpot_box.webp",
    "case_ton": "/assets/cases/fragment_box.webp",
    "case_genesis": "/assets/cases/divine_case.webp",
    "case_divine": "/assets/cases/divine_case.webp",
}

for c in CASES_CATALOG_14:
    if c["id"] in CASE_IMAGE_MAP:
        c["image"] = CASE_IMAGE_MAP[c["id"]]

app.mount("/assets", CachedStaticFiles(directory="assets"), name="assets")
app.mount("/icons", CachedStaticFiles(directory="icons"), name="icons")
app.mount("/backdrops", CachedStaticFiles(directory="backdrops"), name="backdrops")

# ==================== БАЗА ДАННЫХ И БЕЗОПАСНАЯ АВТО-МИГРАЦИЯ ====================
DATABASE_URL = os.getenv("DATABASE_URL", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "@MintTagsNews")
ADMIN_USERNAME = "hatebeinsober21"
MAX_DIVINE_GLOBAL = 75

USE_PG = False
pg_pool = None
if DATABASE_URL:
    try:
        import psycopg2
        from psycopg2 import pool
        pg_pool = psycopg2.pool.ThreadedConnectionPool(1, 12, dsn=DATABASE_URL)
        USE_PG = True
    except Exception as e:
        print(f"[DB] Fallback to SQLite: {e}")
        USE_PG = False

class CursorWrapper:
    def __init__(self, cur, is_pg: bool):
        self.cur = cur
        self.is_pg = is_pg

    def execute(self, sql: str, params=None):
        if not self.is_pg:
            sql = sql.replace("%s", "?")
        if params is not None:
            self.cur.execute(sql, params)
        else:
            self.cur.execute(sql)
        return self

    def fetchone(self):
        return self.cur.fetchone()

    def fetchall(self):
        return self.cur.fetchall()

class ConnWrapper:
    def __init__(self):
        self.is_pg = USE_PG
        if self.is_pg:
            self.conn = pg_pool.getconn()
        else:
            self.conn = sqlite3.connect("market.db", check_same_thread=False)
            self.conn.execute("PRAGMA journal_mode=WAL;")

    def cursor(self):
        return CursorWrapper(self.conn.cursor(), self.is_pg)

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        if self.is_pg:
            pg_pool.putconn(self.conn)
        else:
            self.conn.close()

def init_db():
    db = ConnWrapper()
    cur = db.cursor()
    id_col = "SERIAL PRIMARY KEY" if db.is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT DEFAULT 'player',
            balance BIGINT DEFAULT 25000,
            stars INTEGER DEFAULT 50,
            country TEXT DEFAULT '',
            country_changed INTEGER DEFAULT 0,
            vip_until BIGINT DEFAULT 0,
            luck_mult REAL DEFAULT 1.0,
            compact_pref INTEGER DEFAULT 1,
            safe_slots INTEGER DEFAULT 50,
            scrap_parts INTEGER DEFAULT 15,
            lockpicks INTEGER DEFAULT 1,
            pass_xp INTEGER DEFAULT 120,
            flex_likes INTEGER DEFAULT 0,
            obep_fine BIGINT DEFAULT 0,
            clan_id INTEGER DEFAULT 0,
            sub_verified INTEGER DEFAULT 0,
            total_mints INTEGER DEFAULT 0,
            last_sync BIGINT DEFAULT 0
        )
    """)
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS usernames (
            id {id_col},
            owner_id BIGINT,
            tag TEXT,
            item_type TEXT DEFAULT 'user',
            category TEXT DEFAULT 'telegram',
            tier INTEGER DEFAULT 0,
            value BIGINT DEFAULT 500,
            income BIGINT DEFAULT 5,
            wear REAL DEFAULT 100.0,
            image TEXT DEFAULT '',
            is_listed INTEGER DEFAULT 0,
            is_flex INTEGER DEFAULT 0,
            is_staked INTEGER DEFAULT 0
        )
    """)
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS channels (
            id {id_col},
            owner_id BIGINT,
            name TEXT,
            level INTEGER DEFAULT 1,
            subs INTEGER DEFAULT 100,
            income BIGINT DEFAULT 50
        )
    """)
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS market_lots (
            id {id_col},
            seller_id BIGINT,
            seller_name TEXT,
            item_id INTEGER,
            tag TEXT,
            item_type TEXT,
            tier INTEGER,
            price BIGINT,
            wear REAL DEFAULT 100.0,
            image TEXT DEFAULT ''
        )
    """)
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS staked_deposits (
            id {id_col},
            user_id BIGINT,
            amount BIGINT,
            rate REAL DEFAULT 0.25,
            plan_name TEXT DEFAULT 'Имперский +25%',
            created_at BIGINT
        )
    """)
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS clans (
            id {id_col},
            name TEXT,
            owner_id BIGINT,
            bank BIGINT DEFAULT 0,
            members_cnt INTEGER DEFAULT 1
        )
    """)
    db.commit()

    # Авто-миграция новых колонок без потери старых таблиц на Render
    migrations = [
        ("users", "sub_verified", "INTEGER DEFAULT 0"),
        ("users", "total_mints", "INTEGER DEFAULT 0"),
        ("users", "obep_fine", "BIGINT DEFAULT 0"),
        ("usernames", "is_staked", "INTEGER DEFAULT 0"),
        ("usernames", "category", "TEXT DEFAULT 'telegram'"),
        ("staked_deposits", "plan_name", "TEXT DEFAULT 'Имперский'"),
    ]
    for tbl, col, ctype in migrations:
        try:
            cur.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {ctype}")
            db.commit()
        except Exception:
            db.rollback()
    db.close()

init_db()

# ==================== КАТАЛОГ РЕДКОСТЕЙ, 500 NFT И 14 КЕЙСОВ ====================
RARITIES = [
    {"tier": 0, "name": "Common", "ru": "Обычный", "color": "#94a3b8", "mult": 1},
    {"tier": 1, "name": "Uncommon", "ru": "Необычный", "color": "#10b981", "mult": 2.5},
    {"tier": 2, "name": "Rare", "ru": "Редкий", "color": "#3b82f6", "mult": 6},
    {"tier": 3, "name": "Elite", "ru": "Элитный", "color": "#06b6d4", "mult": 16},
    {"tier": 4, "name": "Epic", "ru": "Эпический", "color": "#a855f7", "mult": 45},
    {"tier": 5, "name": "Mythic", "ru": "Мифический", "color": "#ec4899", "mult": 130},
    {"tier": 6, "name": "Legendary", "ru": "Легендарный", "color": "#f59e0b", "mult": 420},
    {"tier": 7, "name": "Ancient", "ru": "Древний", "color": "#ef4444", "mult": 1500},
    {"tier": 8, "name": "Celestial", "ru": "Небесный", "color": "#38bdf8", "mult": 6500},
    {"tier": 9, "name": "Divine", "ru": "Божественный", "color": "#fde047", "mult": 35000},
]

CATEGORY_SPECS = [
    ("plush", 60, "Plush / Игрушки", ["Genesis Crown Pepe", "Gold Plush Pepe", "Emerald Crystal Pepe", "Scared Neon Cat", "Obsidian Teddy", "Diamond Frog"], "/assets/nft/gold_pepe.webp"),
    ("watches", 50, "Watches / Часы", ["Chronos Tourbillon Cyan", "Swiss Skeleton Royal", "Obsidian Chronograph", "Emerald Patek", "TON Submariner"], "/assets/nft/chronos_watch.webp"),
    ("royal", 50, "Royal / Королевские", ["Imperial Obsidian Crown", "Emerald Scepter", "Sovereign Signet Ring", "Monarch Chalice", "Dynasty Tiara"], "/assets/nft/imperial_crown.webp"),
    ("telegram", 60, "Telegram Legends", ["Faceted Durov Mask", "Founder Stealth Cap", "Paper Plane Relic", "Fragment Obsidian Key", "TON Core Heart"], "/assets/durov.webp"),
    ("cyberpunk", 60, "Cyberpunk", ["Aegis Neural Visor", "Neon Plasma Katana", "Cyber Cortex Implant", "Holo Matrix Deck", "Quantum Gauntlet"], "/assets/nft/durov_mask.webp"),
    ("resistance", 50, "Resistance", ["Emerald Crystal Dog REDO", "Sentinel Hooded Hound", "Cipher Torch", "Freedom Obsidian Shield", "Resistance Crest"], "/assets/dog.webp"),
    ("gaming", 50, "Gaming", ["Arcade Emerald Core", "Mythic Cyber Gamepad", "VR Genesis Helm", "Pixel Gold Relic", "Pro Neon Blade"], "/assets/cases/emerald_vault_chest.webp"),
    ("genesis", 40, "Genesis", ["Genesis Block Shard", "Zero Epoch Coin", "Alpha Validator Key", "First Mint Scroll"], "/assets/cases/founder_emerald_case.webp"),
    ("luxury", 40, "Luxury Artifacts", ["Emerald Vault Relic", "Obsidian Diamond Briefcase", "Imperial Gold Bar", "Private Jet Key"], "/assets/cases/emerald_vault_chest.webp"),
    ("seasonal", 40, "Seasonal", ["Starfall Lantern", "Eclipse Crystal", "Solstice Amulet", "Winter Frost Crown"], "/assets/nft/imperial_crown.webp"),
]

NFT_CATALOG_500 = []
for cat_slug, count, cat_title, base_names, default_img in CATEGORY_SPECS:
    for idx in range(1, count + 1):
        tier_idx = min(9, int((idx - 1) / max(1, count / 10)))
        rar = RARITIES[tier_idx]
        b_name = base_names[(idx - 1) % len(base_names)]
        item_id = f"nft_{cat_slug}_{idx:03d}"
        base_price = int(900 * rar["mult"] * (1 + (idx % 7) * 0.14))
        NFT_CATALOG_500.append({
            "id": item_id,
            "name": f"{b_name} #{idx}",
            "category": cat_slug,
            "category_title": cat_title,
            "rarity": rar["name"],
            "rarity_ru": rar["ru"],
            "tier": tier_idx,
            "image": default_img,
            "base_price": base_price,
            "description": f"Эксклюзивный коллекционный актив категории {cat_title} ({rar['ru']})."
        })

CASES_CATALOG_14 = [
    {"id": "case_emerald_vault", "name": "Emerald Vault Chest", "price": 75000, "currency": "gram", "image": "/assets/cases/emerald_vault_chest.webp", "color": "#10b981", "desc": "Изумрудно-обсидиановый сундук Империи! Повышенный шанс на REDO и Корону.", "weights": [16, 28, 25, 15, 8, 4.5, 2.2, 0.9, 0.35, 0.05], "types": ["gift", "num", "user"]},
    {"id": "case_founder_mask", "name": "Founder Obsidian Case", "price": 149, "currency": "stars", "image": "/assets/cases/founder_emerald_case.webp", "color": "#fde047", "desc": "Сундук с золотой маской Дурова! Только 4–9 тир (Эпик ➔ Divine).", "weights": [0, 0, 0, 0, 18, 34, 25, 13, 7, 3.0], "types": ["gift", "num"]},
    {"id": "case_all_in", "name": "ALL-IN Case (Всё или Ничего)", "price": 10000, "currency": "gram", "image": "/assets/cases/emerald_vault_chest.webp", "color": "#ef4444", "desc": "99.89% дешёвый @username (без окупа) или 0.11% МЕГА-ДЖЕКПОТ!", "weights": [99.889, 0, 0, 0, 0, 0, 0.05, 0.03, 0.02, 0.011], "types": ["user", "gift"]},
    {"id": "case_standard", "name": "Standard Case", "price": 15000, "currency": "gram", "image": "/assets/cases/emerald_vault_chest.webp", "color": "#3b82f6", "desc": "Базовый контейнер с @username и подарками.", "weights": [48, 28, 14, 6, 2.5, 1.0, 0.35, 0.1, 0.04, 0.01], "types": ["user", "gift"]},
    {"id": "case_premium", "name": "Premium Case", "price": 35000, "currency": "gram", "image": "/assets/cases/emerald_vault_chest.webp", "color": "#06b6d4", "desc": "Улучшенный пул тегов и +888 номеров.", "weights": [30, 32, 20, 10, 5, 2, 0.7, 0.2, 0.08, 0.02], "types": ["user", "num", "gift"]},
    {"id": "case_elite", "name": "Elite Case", "price": 65000, "currency": "gram", "image": "/assets/cases/founder_emerald_case.webp", "color": "#a855f7", "desc": "Отборные активы для медиа-империи.", "weights": [15, 25, 28, 17, 9, 4, 1.4, 0.45, 0.12, 0.03], "types": ["gift", "num", "user"]},
    {"id": "case_luxury", "name": "Luxury Case", "price": 140000, "currency": "gram", "image": "/assets/cases/founder_emerald_case.webp", "color": "#ec4899", "desc": "Люксовые часы, короны и редкие @ID.", "weights": [5, 15, 28, 24, 15, 8, 3.2, 1.3, 0.4, 0.1], "types": ["gift", "num"]},
    {"id": "case_fragment", "name": "Fragment +888 Box", "price": 110000, "currency": "gram", "image": "/assets/cases/emerald_vault_chest.webp", "color": "#24A1DE", "desc": "Фирменный бокс с анонимными номерами +888.", "weights": [12, 24, 28, 18, 10, 5, 2, 0.7, 0.25, 0.05], "types": ["num"]},
    {"id": "case_nft", "name": "NFT Gift Box", "price": 55000, "currency": "gram", "image": "/assets/cases/founder_emerald_case.webp", "color": "#10b981", "desc": "100% шанс выпадения коллекционного NFT-подарка.", "weights": [20, 28, 24, 15, 7, 3.8, 1.5, 0.5, 0.15, 0.05], "types": ["gift"]},
    {"id": "case_jackpot", "name": "Jackpot Box", "price": 250000, "currency": "gram", "image": "/assets/cases/founder_emerald_case.webp", "color": "#f59e0b", "desc": "Охота за Древними и Божественными активами.", "weights": [0, 10, 22, 26, 20, 12, 6, 2.8, 1.0, 0.2], "types": ["gift", "num"]},
    {"id": "case_star", "name": "Star Box", "price": 49, "currency": "stars", "image": "/assets/cases/emerald_vault_chest.webp", "color": "#f59e0b", "desc": "Звёздный ларец без дешёвого дропа.", "weights": [0, 0, 25, 35, 22, 11, 4.5, 1.8, 0.5, 0.2], "types": ["gift", "num"]},
    {"id": "case_ton", "name": "TON Crystal Box", "price": 95000, "currency": "gram", "image": "/assets/cases/emerald_vault_chest.webp", "color": "#38bdf8", "desc": "Кристаллический бокс экосистемы TON.", "weights": [10, 22, 28, 20, 11, 5.5, 2.3, 0.85, 0.28, 0.07], "types": ["gift", "user"]},
    {"id": "case_genesis", "name": "Genesis Case", "price": 99, "currency": "stars", "image": "/assets/cases/founder_emerald_case.webp", "color": "#a855f7", "desc": "Реликвии первой эпохи Telegram.", "weights": [0, 0, 0, 25, 32, 24, 11, 5, 2.2, 0.8], "types": ["gift"]},
    {"id": "case_divine", "name": "Divine Durov Case", "price": 249, "currency": "stars", "image": "/assets/cases/founder_emerald_case.webp", "color": "#fde047", "desc": "Высший Сундук Дурова! Легендарные, Древние, Небесные и 9% шанс на DIVINE!", "weights": [0, 0, 0, 0, 0, 0, 38, 33, 20, 9.0], "types": ["gift", "num"]},
]
CASES_MAP = {c["id"]: c for c in CASES_CATALOG_14}
WORDS_POOL = ["durov", "ton", "gram", "whale", "crypto", "king", "empire", "fragment", "alpha", "nexus", "vault", "emerald", "cyber", "shadow", "royal", "matrix", "genesis", "prime", "viper", "legend"]

def get_divine_count(cur) -> int:
    cur.execute("SELECT COUNT(*) FROM usernames WHERE tier = 9")
    r = cur.fetchone()
    return int(r[0]) if r and r[0] else 0

def generate_item(cur, owner_id: int, item_type: str, tier: int, is_all_in_trash: bool = False):
    if tier == 9:
        if get_divine_count(cur) >= MAX_DIVINE_GLOBAL:
            tier = 8
        else:
            cur.execute("SELECT COUNT(*) FROM usernames WHERE owner_id = %s AND tier = 9", (owner_id,))
            if cur.fetchone()[0] >= 1:
                tier = 8

    rar = RARITIES[tier]
    if is_all_in_trash:
        tag = f"@{random.choice(WORDS_POOL)}_{random.randint(1000, 9999)}"
        val = random.randint(260, 980)
        inc = max(1, val // 180)
        return {"tag": tag, "item_type": "user", "category": "telegram", "tier": 0, "value": val, "income": inc, "image": "/assets/durov.webp"}

    if item_type == "gift":
        tier_gifts = [g for g in NFT_CATALOG_500 if g["tier"] == tier] or NFT_CATALOG_500
        chosen = random.choice(tier_gifts)
        serial = random.randint(1, 999)
        tag = f"{chosen['name'].split('#')[0].strip()} #{serial}"
        val = int(chosen["base_price"] * random.uniform(0.92, 1.15))
        inc = max(6, val // 105)
        return {"tag": tag, "item_type": "gift", "category": chosen["category"], "tier": tier, "value": val, "income": inc, "image": chosen["image"]}
    elif item_type == "num":
        digits = f"{random.randint(1,9)}" * 4 if tier >= 7 else f"{random.randint(1000, 9999)} {random.randint(10, 99)}"
        tag = f"+888 0{digits}"
        val = int(1450 * rar["mult"] * random.uniform(0.9, 1.2))
        inc = max(8, val // 100)
        return {"tag": tag, "item_type": "num", "category": "telegram", "tier": tier, "value": val, "income": inc, "image": "/assets/cases/emerald_vault_chest.webp"}
    else:
        w = random.choice(WORDS_POOL)
        tag = f"@{w}" if tier >= 6 else f"@{w}_{random.randint(10, 999)}"
        val = int(780 * rar["mult"] * random.uniform(0.88, 1.2))
        inc = max(3, val // 115)
        return {"tag": tag, "item_type": "user", "category": "telegram", "tier": tier, "value": val, "income": inc, "image": "/assets/durov.webp"}

# ==================== СХЕМЫ ЗАПРОСОВ ====================
class SyncReq(BaseModel):
    user_id: int
    username: str = "player"

class MintReq(BaseModel):
    user_id: int
    mode: str = "user"

class CaseReq(BaseModel):
    user_id: int
    case_id: str

class SellReq(BaseModel):
    user_id: int
    item_id: Optional[int] = None
    mode: str = "single"  # single | bulk | shred | repair | flex | stake_item | unstake_item | list_market
    price: int = 0

class StakeGramReq(BaseModel):
    user_id: int
    amount: int
    plan: str = "imperial"  # flex (15%) | imperial (35%) | durov (60%)

class CountryReq(BaseModel):
    user_id: int
    country: str

class CompactReq(BaseModel):
    user_id: int
    compact: int

class MiniGameReq(BaseModel):
    user_id: int
    game: str
    bet: int = 1000
    mult: float = 2.0
    item_id: Optional[int] = None
    item_ids: Optional[List[int]] = None
    extra: Optional[str] = ""

class AdminReq(BaseModel):
    user_id: int
    username: str
    action: str
    amount: int = 0
    target_tag: str = ""

# ==================== ПОЛНОЕ СОСТОЯНИЕ ИГРОКА ====================
def fetch_full_state(cur, user_id: int, username: str = "player"):
    now = int(time.time())
    cur.execute("""
        SELECT user_id, username, balance, stars, country, country_changed, vip_until, luck_mult,
               compact_pref, safe_slots, scrap_parts, lockpicks, pass_xp, flex_likes, obep_fine,
               clan_id, sub_verified, total_mints, last_sync
        FROM users WHERE user_id = %s
    """, (user_id,))
    u = cur.fetchone()
    if not u:
        cur.execute("""
            INSERT INTO users (user_id, username, balance, stars, country, country_changed, vip_until, luck_mult, compact_pref, safe_slots, scrap_parts, lockpicks, pass_xp, flex_likes, obep_fine, clan_id, sub_verified, total_mints, last_sync)
            VALUES (%s, %s, 25000, 50, '', 0, 0, 1.0, 1, 50, 15, 1, 120, 0, 0, 0, 0, 0, %s)
        """, (user_id, username, now))
        cur.execute("""
            SELECT user_id, username, balance, stars, country, country_changed, vip_until, luck_mult,
                   compact_pref, safe_slots, scrap_parts, lockpicks, pass_xp, flex_likes, obep_fine,
                   clan_id, sub_verified, total_mints, last_sync
            FROM users WHERE user_id = %s
        """, (user_id,))
        u = cur.fetchone()

    uid, uname, bal, stars, country, c_changed, vip_until, luck, compact, slots, scrap, picks, pxp, flikes, obep, clan_id, sub_ver, tmints, last_sync = u
    if username and username != "player" and username != uname:
        uname = username
        cur.execute("UPDATE users SET username = %s WHERE user_id = %s", (uname, uid))

    cur.execute("SELECT id, tag, item_type, category, tier, value, income, wear, image, is_listed, is_flex, is_staked FROM usernames WHERE owner_id = %s ORDER BY value DESC", (uid,))
    items_rows = cur.fetchall()
    cur.execute("SELECT id, name, level, subs, income FROM channels WHERE owner_id = %s", (uid,))
    ch_rows = cur.fetchall()
    cur.execute("SELECT id, amount, rate, plan_name, created_at FROM staked_deposits WHERE user_id = %s", (uid,))
    st_rows = cur.fetchall()

    # Предметы в Холд-Банке (is_staked == 1) дают +50% к доходу и не теряют прочность!
    safe_income = 0
    staked_items_income = 0
    for r in items_rows:
        if r[9]:  # на продаже
            continue
        if r[11]:  # в Холд-Банке
            staked_items_income += int(r[6] * 1.5)
        else:
            safe_income += int(r[6] * (r[7] / 100.0))

    ch_income = sum(r[4] for r in ch_rows)
    total_income = safe_income + staked_items_income + ch_income

    elapsed = max(0, min(3600, now - (last_sync or now)))
    earned = int(total_income * (elapsed / 10.0)) if elapsed >= 5 else 0
    if earned > 0 or last_sync == 0:
        bal += earned
        cur.execute("UPDATE users SET balance = %s, last_sync = %s WHERE user_id = %s", (bal, now, uid))

    cur.execute("SELECT id, seller_id, seller_name, item_id, tag, item_type, tier, price, wear, image FROM market_lots ORDER BY id DESC LIMIT 40")
    market_rows = cur.fetchall()

    cur.execute("SELECT country, SUM(balance) as tb FROM users WHERE country != '' GROUP BY country ORDER BY tb DESC LIMIT 10")
    country_top = [{"country": r[0], "power": int(r[1] or 0)} for r in cur.fetchall()]

    cur.execute("SELECT id, name, bank, members_cnt FROM clans ORDER BY bank DESC LIMIT 15")
    clans_list = [{"id": r[0], "name": r[1], "bank": r[2], "members": r[3]} for r in cur.fetchall()]

    merch_tier = (now // 3600) % 6 + 1
    hot_cat = CATEGORY_SPECS[(now // 3600) % len(CATEGORY_SPECS)][2]

    return {
        "user": {
            "user_id": uid,
            "username": uname,
            "is_admin": uname.lower().replace("@", "") == ADMIN_USERNAME,
            "balance": bal,
            "stars": stars,
            "country": country,
            "country_changed": c_changed,
            "vip_active": vip_until > now,
            "luck_mult": round(float(luck), 2),
            "compact_pref": int(compact),
            "safe_slots": slots,
            "scrap_parts": scrap,
            "lockpicks": picks,
            "pass_xp": pxp,
            "pass_level": min(100, 1 + pxp // 100),
            "flex_likes": flikes,
            "obep_fine": obep,
            "clan_id": clan_id,
            "sub_verified": int(sub_ver),
            "total_mints": int(tmints),
            "income_per_sec": total_income,
            "staked_items_income": staked_items_income,
        },
        "required_channel": REQUIRED_CHANNEL,
        "divine_global": get_divine_count(cur),
        "merch_tier": merch_tier,
        "merch_tier_name": RARITIES[merch_tier]["ru"],
        "hot_trend": hot_cat,
        "inventory": [
            {"id": r[0], "tag": r[1], "item_type": r[2], "category": r[3], "tier": r[4], "value": r[5], "income": r[6], "wear": round(r[7], 1), "image": r[8], "is_listed": r[9], "is_flex": r[10], "is_staked": r[11]}
            for r in items_rows
        ],
        "channels": [{"id": r[0], "name": r[1], "level": r[2], "subs": r[3], "income": r[4]} for r in ch_rows],
        "stakes": [{"id": r[0], "amount": r[1], "rate": r[2], "plan_name": r[3], "created_at": r[4]} for r in st_rows],
        "market": [{"id": r[0], "seller_id": r[1], "seller_name": r[2], "item_id": r[3], "tag": r[4], "item_type": r[5], "tier": r[6], "price": r[7], "wear": r[8], "image": r[9]} for r in market_rows],
        "country_top": country_top,
        "clans": clans_list,
    }

# ==================== ЭНДПОИНТЫ ====================
@app.get("/", response_class=HTMLResponse)
async def serve_index():
    with open("index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/api/nft_catalog")
async def api_nft_catalog(category: str = "all", page: int = 1, per_page: int = 16):
    filtered = NFT_CATALOG_500 if category == "all" else [x for x in NFT_CATALOG_500 if x["category"] == category]
    start = max(0, (page - 1) * per_page)
    return {"total": len(filtered), "page": page, "items": filtered[start:start + per_page]}

@app.get("/api/cases_catalog")
async def api_cases_catalog():
    return {"cases": CASES_CATALOG_14}

@app.post("/api/sync")
async def api_sync(req: SyncReq):
    db = ConnWrapper()
    try:
        cur = db.cursor()
        state = fetch_full_state(cur, req.user_id, req.username)
        db.commit()
        return state
    finally:
        db.close()

@app.post("/api/check_sub")
async def api_check_sub(req: SyncReq):
    """Проверка обязательной подписки без вечного бага + бонус 15 000 G за вход."""
    db = ConnWrapper()
    try:
        cur = db.cursor()
        is_member = True
        if BOT_TOKEN and REQUIRED_CHANNEL:
            try:
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember?chat_id={REQUIRED_CHANNEL}&user_id={req.user_id}"
                with urllib.request.urlopen(url, timeout=3) as resp:
                    data = json.loads(resp.read().decode())
                    if data.get("ok"):
                        status = data["result"].get("status", "")
                        is_member = status in ("creator", "administrator", "member", "restricted")
            except Exception:
                # Если бот ещё не админ в канале — не блокируем игрока навсегда
                is_member = True

        if not is_member:
            return JSONResponse({"ok": False, "error": f"Подпишитесь на канал {REQUIRED_CHANNEL} и нажмите «Проверить»!"}, status_code=400)

        cur.execute("SELECT sub_verified FROM users WHERE user_id = %s", (req.user_id,))
        r = cur.fetchone()
        if r and int(r[0]) == 0:
            cur.execute("UPDATE users SET sub_verified = 1, balance = balance + 15000 WHERE user_id = %s", (req.user_id,))
        else:
            cur.execute("UPDATE users SET sub_verified = 1 WHERE user_id = %s", (req.user_id,))
        state = fetch_full_state(cur, req.user_id, req.username)
        db.commit()
        return {"ok": True, "state": state}
    finally:
        db.close()

@app.post("/api/mint")
async def api_mint(req: MintReq):
    db = ConnWrapper()
    try:
        cur = db.cursor()
        cur.execute("SELECT balance, luck_mult, safe_slots, obep_fine FROM users WHERE user_id = %s", (req.user_id,))
        row = cur.fetchone()
        if not row:
            return JSONResponse({"error": "Профиль не найден"}, status_code=400)
        bal, luck, slots, obep = row
        cost = 4500 if req.mode == "gift" else (2500 if req.mode == "num" else 1000)
        if bal < cost:
            return JSONResponse({"error": f"Недостаточно GRAM (нужно {cost} G)"}, status_code=400)

        cur.execute("SELECT COUNT(*) FROM usernames WHERE owner_id = %s AND is_staked = 0", (req.user_id,))
        if cur.fetchone()[0] >= slots:
            return JSONResponse({"error": "Сейф переполнен! Положите активы в Холд-Банк, расширьте слоты или продайте лишнее."}, status_code=400)

        weights = [45, 26, 14, 7.2, 3.8, 2.0, 1.1, 0.55, 0.25, 0.06]
        boosted = [w * (luck if i >= 3 else 1.0) for i, w in enumerate(weights)]
        tier = random.choices(range(10), weights=boosted, k=1)[0]
        itype = "gift" if req.mode == "gift" else ("num" if req.mode == "num" else "user")
        item = generate_item(cur, req.user_id, itype, tier)

        # Случайная налоговая проверка ОБЭП при крупных активах
        new_fine = obep
        if tier >= 5 and random.random() < 0.18:
            new_fine += int(item["value"] * 0.12)

        cur.execute("UPDATE users SET balance = balance - %s, pass_xp = pass_xp + 15, total_mints = total_mints + 1, obep_fine = %s WHERE user_id = %s", (cost, new_fine, req.user_id))
        cur.execute("""
            INSERT INTO usernames (owner_id, tag, item_type, category, tier, value, income, wear, image)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 100.0, %s)
        """, (req.user_id, item["tag"], item["item_type"], item["category"], item["tier"], item["value"], item["income"], item["image"]))
        state = fetch_full_state(cur, req.user_id)
        db.commit()
        return {"ok": True, "dropped": item, "state": state}
    finally:
        db.close()

@app.post("/api/open_case")
async def api_open_case(req: CaseReq):
    case = CASES_MAP.get(req.case_id)
    if not case:
        return JSONResponse({"error": "Кейс не найден"}, status_code=400)
    db = ConnWrapper()
    try:
        cur = db.cursor()
        cur.execute("SELECT balance, stars, luck_mult, safe_slots FROM users WHERE user_id = %s", (req.user_id,))
        bal, stars, luck, slots = cur.fetchone()
        cur.execute("SELECT COUNT(*) FROM usernames WHERE owner_id = %s AND is_staked = 0", (req.user_id,))
        if cur.fetchone()[0] >= slots:
            return JSONResponse({"error": "Сейф переполнен!"}, status_code=400)

        if case["currency"] == "stars":
            if stars < case["price"]:
                return JSONResponse({"error": f"Недостаточно Stars ({case['price']} ⭐️)"}, status_code=400)
            cur.execute("UPDATE users SET stars = stars - %s, pass_xp = pass_xp + 45 WHERE user_id = %s", (case["price"], req.user_id))
        else:
            if bal < case["price"]:
                return JSONResponse({"error": f"Недостаточно GRAM ({case['price']} G)"}, status_code=400)
            cur.execute("UPDATE users SET balance = balance - %s, pass_xp = pass_xp + 25 WHERE user_id = %s", (case["price"], req.user_id))

        boosted = [w * (luck if i >= 4 else 1.0) for i, w in enumerate(case["weights"])]
        tier = random.choices(range(10), weights=boosted, k=1)[0]
        is_all_in_trash = (req.case_id == "case_all_in" and tier == 0)
        itype = "user" if is_all_in_trash else random.choice(case["types"])
        item = generate_item(cur, req.user_id, itype, tier, is_all_in_trash=is_all_in_trash)

        cur.execute("""
            INSERT INTO usernames (owner_id, tag, item_type, category, tier, value, income, wear, image)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 100.0, %s)
        """, (req.user_id, item["tag"], item["item_type"], item["category"], item["tier"], item["value"], item["income"], item["image"]))
        state = fetch_full_state(cur, req.user_id)
        db.commit()
        return {"ok": True, "dropped": item, "state": state}
    finally:
        db.close()

@app.post("/api/stake/gram")
async def api_stake_gram(req: StakeGramReq):
    """Ручной вклад любой суммы GRAM под выбранный тариф."""
    db = ConnWrapper()
    try:
        cur = db.cursor()
        amt = int(req.amount)
        if amt < 500:
            return JSONResponse({"error": "Минимальная сумма вклада — 500 GRAM!"}, status_code=400)
        cur.execute("SELECT balance, vip_until FROM users WHERE user_id = %s", (req.user_id,))
        bal, vip_until = cur.fetchone()
        if bal < amt:
            return JSONResponse({"error": "Недостаточно GRAM на балансе!"}, status_code=400)

        plans = {
            "flex": (0.15, "Гибкий +15%"),
            "imperial": (0.35, "Имперский +35%"),
            "durov": (0.60, "Фонд Дурова +60%"),
        }
        rate, p_name = plans.get(req.plan, (0.25, "Имперский +25%"))
        cur.execute("UPDATE users SET balance = balance - %s, pass_xp = pass_xp + 20 WHERE user_id = %s", (amt, req.user_id))
        cur.execute("INSERT INTO staked_deposits (user_id, amount, rate, plan_name, created_at) VALUES (%s, %s, %s, %s, %s)", (req.user_id, amt, rate, p_name, int(time.time())))
        state = fetch_full_state(cur, req.user_id)
        db.commit()
        return {"ok": True, "message": f"Вклад {amt} G оформлен по тарифу «{p_name}»!", "state": state}
    finally:
        db.close()

@app.post("/api/sell_item")
async def api_sell_item(req: SellReq):
    """Управление предметами: продажа, опт, шредер, ремонт, музей, Вклад в Холд-Банк (NFT/+888/@ID) и Рынок."""
    db = ConnWrapper()
    try:
        cur = db.cursor()
        merch_tier = (int(time.time()) // 3600) % 6 + 1
        msg = "Выполнено!"

        if req.mode == "bulk":
            cur.execute("SELECT id, value, tier FROM usernames WHERE owner_id = %s AND tier <= 4 AND is_flex = 0 AND is_listed = 0 AND is_staked = 0", (req.user_id,))
            rows = cur.fetchall()
            if not rows:
                return JSONResponse({"error": "В Сейфе нет обычных предметов (0–4 тир) для оптовой продажи"}, status_code=400)
            total_gain = sum(int(r[1] * (1.8 if r[2] == merch_tier else 1.0)) for r in rows)
            cur.execute("DELETE FROM usernames WHERE owner_id = %s AND tier <= 4 AND is_flex = 0 AND is_listed = 0 AND is_staked = 0", (req.user_id,))
            cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (total_gain, req.user_id))
            msg = f"Продано {len(rows)} шт. за +{total_gain} G!"
        elif req.mode == "stake_item":
            cur.execute("UPDATE usernames SET is_staked = 1, is_flex = 0 WHERE id = %s AND owner_id = %s AND is_listed = 0", (req.item_id, req.user_id))
            msg = "Актив помещён в ячейку Холд-Банка (+50% к доходу/сек и 0% износа)!"
        elif req.mode == "unstake_item":
            cur.execute("UPDATE usernames SET is_staked = 0 WHERE id = %s AND owner_id = %s", (req.item_id, req.user_id))
            msg = "Актив возвращён из Холд-Банка в Сейф!"
        elif req.mode == "shred":
            cur.execute("SELECT id, tier FROM usernames WHERE id = %s AND owner_id = %s", (req.item_id, req.user_id))
            r = cur.fetchone()
            if not r:
                return JSONResponse({"error": "Предмет не найден"}, status_code=400)
            parts = 8 + r[1] * 6
            cur.execute("DELETE FROM usernames WHERE id = %s", (req.item_id,))
            cur.execute("UPDATE users SET scrap_parts = scrap_parts + %s WHERE user_id = %s", (parts, req.user_id))
            msg = f"Разобрано на +{parts} деталей!"
        elif req.mode == "repair":
            cur.execute("UPDATE usernames SET wear = 100.0 WHERE id = %s AND owner_id = %s", (req.item_id, req.user_id))
            cur.execute("UPDATE users SET balance = GREATEST(0, balance - 1500) WHERE user_id = %s" if db.is_pg else "UPDATE users SET balance = MAX(0, balance - 1500) WHERE user_id = %s", (req.user_id,))
            msg = "Состояние восстановлено до 100%!"
        elif req.mode == "flex":
            cur.execute("UPDATE usernames SET is_flex = CASE WHEN is_flex = 1 THEN 0 ELSE 1 END WHERE id = %s AND owner_id = %s", (req.item_id, req.user_id))
            msg = "Витрина Музея обновлена!"
        elif req.mode == "list_market":
            cur.execute("SELECT id, tag, item_type, tier, value, wear, image FROM usernames WHERE id = %s AND owner_id = %s AND is_staked = 0", (req.item_id, req.user_id))
            r = cur.fetchone()
            if not r:
                return JSONResponse({"error": "Предмет не найден или в Холд-Банке"}, status_code=400)
            lot_price = max(500, req.price or int(r[4] * 1.25))
            cur.execute("SELECT username FROM users WHERE user_id = %s", (req.user_id,))
            sname = cur.fetchone()[0]
            cur.execute("DELETE FROM usernames WHERE id = %s", (req.item_id,))
            cur.execute("INSERT INTO market_lots (seller_id, seller_name, item_id, tag, item_type, tier, price, wear, image) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", (req.user_id, sname, r[0], r[1], r[2], r[3], lot_price, r[5], r[6]))
            msg = f"Выставлено на Рынок за {lot_price} G!"
        else:
            cur.execute("SELECT value, tier FROM usernames WHERE id = %s AND owner_id = %s", (req.item_id, req.user_id))
            r = cur.fetchone()
            if not r:
                return JSONResponse({"error": "Предмет не найден"}, status_code=400)
            gain = int(r[0] * (1.8 if r[1] == merch_tier else 1.0))
            cur.execute("DELETE FROM usernames WHERE id = %s", (req.item_id,))
            cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (gain, req.user_id))
            msg = f"Продано за +{gain} G!"

        state = fetch_full_state(cur, req.user_id)
        db.commit()
        return {"ok": True, "message": msg, "state": state}
    finally:
        db.close()

@app.post("/api/country/change")
async def api_change_country(req: CountryReq):
    db = ConnWrapper()
    try:
        cur = db.cursor()
        cur.execute("SELECT balance, country_changed FROM users WHERE user_id = %s", (req.user_id,))
        bal, changed = cur.fetchone()
        cost = 500000 if changed >= 1 else 0
        if bal < cost:
            return JSONResponse({"error": "Повторная смена страны стоит 500 000 GRAM!"}, status_code=400)
        cur.execute("UPDATE users SET balance = balance - %s, country = %s, country_changed = country_changed + 1 WHERE user_id = %s", (cost, req.country, req.user_id))
        state = fetch_full_state(cur, req.user_id)
        db.commit()
        return {"ok": True, "state": state}
    finally:
        db.close()

@app.post("/api/settings/compact")
async def api_settings_compact(req: CompactReq):
    db = ConnWrapper()
    try:
        cur = db.cursor()
        cur.execute("UPDATE users SET compact_pref = %s WHERE user_id = %s", (1 if req.compact else 0, req.user_id))
        state = fetch_full_state(cur, req.user_id)
        db.commit()
        return {"ok": True, "state": state}
    finally:
        db.close()

@app.post("/api/minigame/play")
async def api_minigame_play(req: MiniGameReq):
    db = ConnWrapper()
    try:
        cur = db.cursor()
        cur.execute("SELECT balance, stars, scrap_parts, lockpicks, safe_slots, obep_fine FROM users WHERE user_id = %s", (req.user_id,))
        bal, stars, scrap, picks, slots, obep = cur.fetchone()
        msg = "Готово!"

        if req.game == "craft_lockpick":
            if scrap < 50:
                return JSONResponse({"error": "Нужно 50 деталей со Шредера!"}, status_code=400)
            cur.execute("UPDATE users SET scrap_parts = scrap_parts - 50, lockpicks = lockpicks + 1 WHERE user_id = %s", (req.user_id,))
            msg = "Мастер-Отмычка успешно выкована!"
        elif req.game == "hack_vault":
            if picks < 1:
                return JSONResponse({"error": "Нужна Мастер-Отмычка!"}, status_code=400)
            cur.execute("UPDATE users SET lockpicks = lockpicks - 1 WHERE user_id = %s", (req.user_id,))
            tier = random.choices([5, 6, 7, 8, 9], weights=[34, 30, 20, 12, 4], k=1)[0]
            item = generate_item(cur, req.user_id, "gift", tier)
            cur.execute("INSERT INTO usernames (owner_id, tag, item_type, category, tier, value, income, wear, image) VALUES (%s,%s,%s,%s,%s,%s,%s,100.0,%s)", (req.user_id, item["tag"], item["item_type"], item["category"], item["tier"], item["value"], item["income"], item["image"]))
            msg = f"Сейф Дурова взломан! Получен: {item['tag']}"
        elif req.game == "buy_slots":
            if bal < 50000:
                return JSONResponse({"error": "Нужно 50 000 GRAM для +50 слотов!"}, status_code=400)
            cur.execute("UPDATE users SET balance = balance - 50000, safe_slots = safe_slots + 50 WHERE user_id = %s", (req.user_id,))
            msg = "+50 слотов Сейфа открыто!"
        elif req.game == "pay_obep":
            if obep <= 0:
                return JSONResponse({"error": "Штрафов ОБЭП нет!"}, status_code=400)
            if bal < obep:
                return JSONResponse({"error": f"Недостаточно GRAM для оплаты штрафа ({obep} G)"}, status_code=400)
            cur.execute("UPDATE users SET balance = balance - %s, obep_fine = 0 WHERE user_id = %s", (obep, req.user_id))
            msg = "Штраф ОБЭП полностью погашен!"
        elif req.game == "channel_create":
            if bal < 25000:
                return JSONResponse({"error": "Создание канала стоит 25 000 G"}, status_code=400)
            cname = (req.extra or f"Empire Media #{random.randint(10,99)}")[:28]
            cur.execute("UPDATE users SET balance = balance - 25000 WHERE user_id = %s", (req.user_id,))
            cur.execute("INSERT INTO channels (owner_id, name, level, subs, income) VALUES (%s, %s, 1, 500, 140)", (req.user_id, cname))
            msg = f"Канал «{cname}» запущен!"
        elif req.game == "stake_withdraw":
            cur.execute("SELECT id, amount, rate FROM staked_deposits WHERE user_id = %s", (req.user_id,))
            rows = cur.fetchall()
            if not rows:
                return JSONResponse({"error": "У вас нет активных вкладов GRAM"}, status_code=400)
            total = sum(int(r[1] * (1.0 + float(r[2]))) for r in rows)
            cur.execute("DELETE FROM staked_deposits WHERE user_id = %s", (req.user_id,))
            cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (total, req.user_id))
            msg = f"Выведено с процентами: +{total} GRAM!"
        elif req.game == "forge_5to1":
            ids = req.item_ids or []
            if len(ids) < 5:
                return JSONResponse({"error": "Для крафта 5➔1 нужно минимум 5 предметов в Сейфе!"}, status_code=400)
            placeholders = ",".join(["%s"] * 5)
            cur.execute(f"SELECT id, tier FROM usernames WHERE owner_id = %s AND id IN ({placeholders})", tuple([req.user_id] + ids[:5]))
            found = cur.fetchall()
            if len(found) < 5:
                return JSONResponse({"error": "Выбранные предметы недоступны"}, status_code=400)
            avg_tier = min(9, int(sum(x[1] for x in found) / 5) + 1)
            for x in found:
                cur.execute("DELETE FROM usernames WHERE id = %s", (x[0],))
            crafted = generate_item(cur, req.user_id, "gift", avg_tier)
            cur.execute("INSERT INTO usernames (owner_id, tag, item_type, category, tier, value, income, wear, image) VALUES (%s,%s,%s,%s,%s,%s,%s,100.0,%s)", (req.user_id, crafted["tag"], crafted["item_type"], crafted["category"], crafted["tier"], crafted["value"], crafted["income"], crafted["image"]))
            msg = f"Синтез 5➔1 успешен! Создан: {crafted['tag']}"
        elif req.game == "buy_market":
            cur.execute("SELECT id, seller_id, tag, item_type, tier, price, wear, image FROM market_lots WHERE id = %s", (req.item_id,))
            lot = cur.fetchone()
            if not lot:
                return JSONResponse({"error": "Лот уже куплен"}, status_code=400)
            if bal < lot[5]:
                return JSONResponse({"error": "Недостаточно GRAM для покупки лота"}, status_code=400)
            cur.execute("DELETE FROM market_lots WHERE id = %s", (lot[0],))
            cur.execute("UPDATE users SET balance = balance - %s WHERE user_id = %s", (lot[5], req.user_id))
            cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (int(lot[5] * 0.95), lot[1]))
            cur.execute("INSERT INTO usernames (owner_id, tag, item_type, category, tier, value, income, wear, image) VALUES (%s,%s,%s,'telegram',%s,%s,%s,%s,%s)", (req.user_id, lot[2], lot[3], lot[4], lot[5], max(5, lot[5]//110), lot[6], lot[7]))
            msg = f"Куплен лот {lot[2]}!"
        elif req.game == "clan_create":
            if bal < 100000:
                return JSONResponse({"error": "Создание Синдиката стоит 100 000 G"}, status_code=400)
            cname = (req.extra or f"Syndicate #{random.randint(10,99)}")[:24]
            cur.execute("UPDATE users SET balance = balance - 100000 WHERE user_id = %s", (req.user_id,))
            cur.execute("INSERT INTO clans (name, owner_id, bank, members_cnt) VALUES (%s, %s, 50000, 1)", (cname, req.user_id))
            msg = f"Клан «{cname}» основан!"
        elif req.game == "buy_vip_stars":
            if stars < 100:
                return JSONResponse({"error": "Нужно 100 ⭐️ Stars для VIP и Удачи ×2.5!"}, status_code=400)
            cur.execute("UPDATE users SET stars = stars - 100, vip_until = %s, luck_mult = 2.5 WHERE user_id = %s", (int(time.time()) + 86400 * 7, req.user_id))
            msg = "VIP-Статус и Удача ×2.5 активированы!"
        else:
            # Ставки в Ракетке, Сапёре, Дуэлях, Колесе и Апгрейдере
            bet = max(500, int(req.bet))
            if bal < bet:
                return JSONResponse({"error": "Недостаточно GRAM для ставки!"}, status_code=400)
            win_mult = max(0.0, float(req.mult))
            delta = int(bet * win_mult) - bet
            cur.execute("UPDATE users SET balance = balance + %s, pass_xp = pass_xp + 20 WHERE user_id = %s", (delta, req.user_id))
            msg = f"Победа! Выигрыш +{int(bet * win_mult)} G (×{win_mult:.2f})" if win_mult > 0 else f"Ставка {bet} G сгорела!"

        state = fetch_full_state(cur, req.user_id)
        db.commit()
        return {"ok": True, "message": msg, "state": state}
    finally:
        db.close()

@app.post("/api/admin/action")
async def api_admin_action(req: AdminReq):
    if req.username.lower().replace("@", "") != ADMIN_USERNAME:
        return JSONResponse({"error": "Доступ строго для @hatebeinsober21"}, status_code=403)
    db = ConnWrapper()
    try:
        cur = db.cursor()
        if req.action == "give_gram":
            cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (req.amount, req.user_id))
        elif req.action == "give_stars":
            cur.execute("UPDATE users SET stars = stars + %s WHERE user_id = %s", (req.amount, req.user_id))
        elif req.action == "set_luck":
            new_luck = 1.0 if req.amount <= 1 else float(req.amount)
            cur.execute("UPDATE users SET luck_mult = %s WHERE user_id = %s", (new_luck, req.user_id))
        elif req.action == "reset_luck":
            cur.execute("UPDATE users SET luck_mult = 1.0 WHERE user_id = %s", (req.user_id,))
        elif req.action == "spawn_divine":
            tag = req.target_tag or "Imperial Obsidian Crown #1"
            cur.execute("INSERT INTO usernames (owner_id, tag, item_type, category, tier, value, income, wear, image) VALUES (%s, %s, 'gift', 'royal', 9, 260000000, 95000, 100.0, '/assets/nft/imperial_crown.webp')", (req.user_id, tag))
        state = fetch_full_state(cur, req.user_id, req.username)
        db.commit()
        return {"ok": True, "state": state}
    finally:
        db.close()
