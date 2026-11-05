import sqlite3
import random
import time
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from aiogram.types import LabeledPrice
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
            balance REAL DEFAULT 1000.0,
            last_claim INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            xp INTEGER DEFAULT 0,
            luck_multi REAL DEFAULT 1.0,
            luck_until INTEGER DEFAULT 0
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS usernames (
            tag TEXT PRIMARY KEY,
            owner_id INTEGER,
            rarity TEXT,
            income_per_sec REAL,
            created_at INTEGER,
            FOREIGN KEY(owner_id) REFERENCES users(tg_user_id)
        )
    """)
    conn.commit()

    # Миграция колонок
    cur.execute("PRAGMA table_info(users)")
    existing_cols = [col[1] for col in cur.fetchall()]
    new_cols = [
        ("level", "INTEGER DEFAULT 1"),
        ("xp", "INTEGER DEFAULT 0"),
        ("luck_multi", "REAL DEFAULT 1.0"),
        ("luck_until", "INTEGER DEFAULT 0")
    ]
    for col_name, col_type in new_cols:
        if col_name not in existing_cols:
            cur.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}")
    conn.commit()
    conn.close()

init_db()

# Базы слов и блогеров
INFLUENCERS = [
    "litvin", "mellstroy", "mrbeast", "khaby", "subo", "karna.val",
    "danya_milokhin", "baskov", "morgen", "wylsa", "hasbulla", "buster"
]
WORDS_MYTHIC = ["x", "7", "ai", "tg", "ton", "vip", "god", "top", "nft", "ron"]
WORDS_EPIC = ["cyber", "dark", "king", "flex", "gold", "shadow", "drop", "code"]
WORDS_RARE = ["ghost", "speed", "drift", "power", "club", "trade", "flow", "alpha"]

RECENT_ROOTS = []

def generate_username(conn, luck_multi: float = 1.0, is_rare_spin: bool = False):
    global RECENT_ROOTS
    cur = conn.cursor()

    mult = luck_multi * (2.5 if is_rare_spin else 1.0)
    p_influencer = 0.015 * mult
    p_mythic = 0.03 * mult
    p_epic = 0.15 * mult
    p_rare = 0.35 * mult

    roll = random.random()

    if roll < p_influencer:
        # Уникальный блогер
        available = [w for w in INFLUENCERS if w not in RECENT_ROOTS] or INFLUENCERS
        root = random.choice(available)
        tag = "@" + root
        rarity, income, xp = "Legendary", 250.0, 300
    elif roll < (p_influencer + p_mythic):
        available = [w for w in WORDS_MYTHIC if w not in RECENT_ROOTS] or WORDS_MYTHIC
        root = random.choice(available)
        tag = "@" + root
        rarity, income, xp = "Mythic", 1000.0, 800
    elif roll < (p_influencer + p_mythic + p_epic):
        available = [w for w in WORDS_EPIC if w not in RECENT_ROOTS] or WORDS_EPIC
        root = random.choice(available)
        tag = "@" + root
        rarity, income, xp = "Epic", 60.0, 100
    elif roll < (p_influencer + p_mythic + p_epic + p_rare):
        available = [w for w in WORDS_RARE if w not in RECENT_ROOTS] or WORDS_RARE
        root = random.choice(available)
        tag = "@" + root
        rarity, income, xp = "Rare", 15.0, 40
    else:
        bases = ["user", "gamer", "star", "night", "pro", "zone", "player"]
        available = [b for b in bases if b not in RECENT_ROOTS] or bases
        root = random.choice(available)
        tag = f"@{root}_{random.randint(10, 999)}"
        rarity, income, xp = "Common", 1.0, 5

    # Проверка уникальности редких ников
    if rarity in ["Legendary", "Mythic", "Epic"]:
        cur.execute("SELECT tag FROM usernames WHERE tag = ?", (tag,))
        if cur.fetchone():
            # Если уже выбит другим игроком — выдаем резервный уникальный Common
            tag = f"@{root}_{random.randint(1000, 9999)}"
            rarity, income, xp = "Common", 1.0, 5

    RECENT_ROOTS.append(root)
    if len(RECENT_ROOTS) > 5:
        RECENT_ROOTS.pop(0)

    return tag, rarity, income, xp

class AuthData(BaseModel):
    user_id: int
    username: str = "Anonymous"

@app.get("/")
def serve_index():
    return FileResponse("index.html")

@app.post("/api/login")
def login(data: AuthData):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT member_number, balance, last_claim FROM users WHERE tg_user_id = ?", (data.user_id,))
    row = cur.fetchone()
    now = int(time.time())

    if not row:
        cur.execute(
            "INSERT INTO users (tg_user_id, username, balance, last_claim, level, xp, luck_multi, luck_until) VALUES (?, ?, 1000.0, ?, 1, 0, 1.0, 0)",
            (data.user_id, data.username, now)
        )
        conn.commit()
        member_num = cur.lastrowid
        res = {"member_number": member_num, "balance": 1000.0, "is_new": True}
    else:
        res = {"member_number": row[0], "balance": row[1], "is_new": False}

    conn.close()
    return res

@app.get("/api/state/{user_id}")
def get_user_state(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT member_number, balance, last_claim, level, xp, luck_multi, luck_until FROM users WHERE tg_user_id = ?", (user_id,))
    user = cur.fetchone()
    if not user:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found")

    member_number, balance, last_claim, level, xp, luck_multi, luck_until = user
    cur.execute("SELECT tag, rarity, income_per_sec FROM usernames WHERE owner_id = ? ORDER BY income_per_sec DESC", (user_id,))
    tags = [{"tag": r[0], "rarity": r[1], "income": r[2]} for r in cur.fetchall()]

    total_rate = sum(t["income"] for t in tags)
    now = int(time.time())
    unclaimed = total_rate * min(now - last_claim, 28800)
    active_luck = luck_multi if luck_until > now else 1.0

    conn.close()
    return {
        "member_number": member_number,
        "balance": round(balance, 2),
        "total_rate": round(total_rate, 2),
        "unclaimed": round(unclaimed, 2),
        "level": level,
        "xp": xp,
        "luck_multi": active_luck,
        "luck_until": luck_until,
        "tags": tags
    }

# Каталог доната в Telegram Stars
PRICES = {
    "luck_x2_1h": {"title": "🍀 Удача x2 (1 час)", "price": 19},
    "luck_x3_2h": {"title": "🔥 Удача x3 (2 часа)", "price": 39},
    "coins_50k":  {"title": "🪙 50,000 GRAM", "price": 15},
    "coins_200k": {"title": "💰 200,000 GRAM", "price": 49},
    "vip_30d":    {"title": "👑 VIP Статус (30 дней)", "price": 89},
    "channel_slot": {"title": "📢 +1 Слот Канала", "price": 100},
}

@app.get("/api/invoice")
async def get_invoice(payload: str):
    product = PRICES.get(payload)
    if not product:
        raise HTTPException(status_code=400, detail="Товар не найден")

    link = await bot.create_invoice_link(
        title=product["title"],
        description="Внутриигровая покупка в MintTags: Media Empire",
        payload=payload,
        currency="XTR",
        prices=[LabeledPrice(label=product["title"], amount=product["price"])]
    )
    return {"invoice_link": link}
