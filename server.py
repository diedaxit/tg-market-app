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
            balance REAL DEFAULT 1500.0,
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
            sell_price REAL,
            reasons TEXT,
            created_at INTEGER,
            FOREIGN KEY(owner_id) REFERENCES users(tg_user_id)
        )
    """)
    conn.commit()
    conn.close()

init_db()

# БАЗА СЛОВ И РЕДКОСТЕЙ (10 Тиров)
WORDS_DIVINE = ["x", "v", "ai", "go", "ok", "up"]
WORDS_EXCLUSIVE = ["durov", "telegram", "ton", "pavel", "vk", "notcoin"]
WORDS_ULTRA = ["cat", "dog", "bot", "nft", "god", "top"]
WORDS_LUXURY = ["dubai", "money", "rich", "gold", "boss", "king"]
WORDS_MYTHIC = ["star", "epic", "moon", "flow", "dark"]
WORDS_LEGENDARY = ["tiger", "ghost", "alpha", "prime", "whale"]
WORDS_EPIC = ["shadow", "crypto", "hacker", "sniper", "ninja"]
WORDS_RARE = ["gamer", "player", "rocket", "market", "trade"]
WORDS_UNCOMMON = ["user", "pro", "hero", "fan"]

# Редкости: Название, Базовый Вес, Доход/сек, Опыт, Цена продажи
RARITIES = [
    {"name": "Common", "w": 70000, "inc": 1, "xp": 5, "sell": 50},
    {"name": "Uncommon", "w": 20000, "inc": 5, "xp": 15, "sell": 250},
    {"name": "Rare", "w": 7000, "inc": 15, "xp": 40, "sell": 750},
    {"name": "Epic", "w": 2000, "inc": 50, "xp": 100, "sell": 2500},
    {"name": "Legendary", "w": 600, "inc": 200, "xp": 300, "sell": 10000},
    {"name": "Mythic", "w": 200, "inc": 450, "xp": 800, "sell": 22500},
    {"name": "Luxury", "w": 50, "inc": 1500, "xp": 1500, "sell": 75000},
    {"name": "Ultra-Mythic", "w": 20, "inc": 5000, "xp": 2500, "sell": 250000},
    {"name": "Exclusive", "w": 5, "inc": 25000, "xp": 5000, "sell": 1250000},
    {"name": "Divine", "w": 1, "inc": 100000, "xp": 15000, "sell": 5000000}
]

# Режимы прокрутки
SPIN_MODES = {
    "basic": {"cost": 100, "min_idx": 0},    # Доступны все
    "silver": {"cost": 300, "min_idx": 1},   # Без Common
    "gold": {"cost": 1000, "min_idx": 2},    # Без Common, Uncommon
    "diamond": {"cost": 5000, "min_idx": 3}  # Только Epic и выше
}

def generate_username(mode="basic", luck_multi=1.0):
    min_idx = SPIN_MODES[mode]["min_idx"]
    
    # Срезаем пул редкостей в зависимости от режима прокрутки
    pool = []
    total_w = 0
    for i, r in enumerate(RARITIES):
        if i >= min_idx:
            w = r["w"]
            # Удача работает на Legendary и выше (индекс 4+)
            if i >= 4:
                w = int(w * luck_multi)
            pool.append({"idx": i, "data": r, "w": w})
            total_w += w

    rnd = random.random() * total_w
    picked = pool[0]["data"]
    for p in pool:
        if rnd < p["w"]:
            picked = p["data"]
            break
        rnd -= p["w"]

    rarity = picked["name"]
    reasons = []
    tag = ""

    # Генерация логики слова и причин
    if rarity == "Divine":
        word = random.choice(WORDS_DIVINE)
        tag = f"@{word}"
        reasons = ["👑 2 буквы", "✨ Высшая редкость (Divine)", "🚫 Без цифр и символов"]
    elif rarity == "Exclusive":
        word = random.choice(WORDS_EXCLUSIVE)
        tag = f"@{word}"
        reasons = ["💎 Уникальный эксклюзив", f"💡 Слово: {word}", "🚫 Без цифр и символов"]
    elif rarity == "Ultra-Mythic":
        word = random.choice(WORDS_ULTRA)
        tag = f"@{word}"
        reasons = ["🔥 3 буквы", "🚫 Без цифр и символов"]
    elif rarity == "Luxury":
        word = random.choice(WORDS_LUXURY)
        tag = f"@{word}"
        reasons = ["💰 Роскошное слово (Luxury)", f"💡 Слово: {word}", "🚫 Без цифр и символов"]
    elif rarity == "Mythic":
        word = random.choice(WORDS_MYTHIC)
        tag = f"@{word}"
        reasons = ["🔥 4 буквы", "🚫 Без цифр и символов"]
    elif rarity == "Legendary":
        word = random.choice(WORDS_LEGENDARY)
        tag = f"@{word}"
        reasons = ["⭐ 5 букв", "🚫 Без цифр и символов"]
    elif rarity == "Epic":
        word = random.choice(WORDS_EPIC)
        tag = f"@{word}"
        reasons = ["✅ Короткое читаемое слово", "🚫 Без цифр и символов"]
    elif rarity == "Rare":
        word = random.choice(WORDS_RARE)
        tag = f"@{word}"
        reasons = ["✅ Без спецсимволов", "✅ Красивое слово"]
    elif rarity == "Uncommon":
        word = random.choice(WORDS_UNCOMMON)
        tag = f"@{word}{random.randint(10,99)}"
        reasons = ["✅ Без нижнего подчеркивания", "✅ Читаемый корень"]
    else:
        word = random.choice(["user", "bot", "acc", "id"])
        tag = f"@{word}_{random.randint(100,9999)}"
        reasons = ["Обычный тег с цифрами"]

    return tag, rarity, picked["inc"], picked["xp"], picked["sell"], ",".join(reasons)

class AuthData(BaseModel):
    user_id: int
    username: str = "Anonymous"

class MintData(BaseModel):
    user_id: int
    mode: str = "basic"

class SellData(BaseModel):
    user_id: int
    tag: str

@app.get("/")
def serve_index():
    return FileResponse("index.html")

@app.post("/api/login")
def login(data: AuthData):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT member_number, balance FROM users WHERE tg_user_id = ?", (data.user_id,))
    row = cur.fetchone()
    now = int(time.time())
    if not row:
        cur.execute("INSERT INTO users (tg_user_id, username, balance, last_claim, level, xp) VALUES (?, ?, 1500.0, ?, 1, 0)",
                    (data.user_id, data.username, now))
        conn.commit()
        member_num = cur.lastrowid
        res = {"member_number": member_num, "balance": 1500.0}
    else:
        res = {"member_number": row[0], "balance": row[1]}
    conn.close()
    return res

@app.get("/api/state/{user_id}")
def get_user_state(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT member_number, balance, level, xp FROM users WHERE tg_user_id = ?", (user_id,))
    user = cur.fetchone()
    if not user:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found")
        
    member_number, balance, level, xp = user
    cur.execute("SELECT tag, rarity, income_per_sec, sell_price, reasons FROM usernames WHERE owner_id = ? ORDER BY income_per_sec DESC", (user_id,))
    tags = [{"tag": r[0], "rarity": r[1], "income": r[2], "sell_price": r[3], "reasons": r[4].split(',')} for r in cur.fetchall()]
    
    conn.close()
    return {
        "member_number": member_number,
        "balance": round(balance, 2),
        "level": level,
        "xp": xp,
        "tags": tags
    }

@app.post("/api/mint")
def mint(data: MintData):
    if data.mode not in SPIN_MODES:
        raise HTTPException(status_code=400, detail="Invalid spin mode")
        
    cost = SPIN_MODES[data.mode]["cost"]
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    
    cur.execute("SELECT balance, level, xp, luck_multi, luck_until FROM users WHERE tg_user_id = ?", (data.user_id,))
    user = cur.fetchone()
    if not user or user[0] < cost:
        conn.close()
        raise HTTPException(status_code=400, detail="Недостаточно GRAM для прокрутки!")
        
    balance, level, xp, luck_multi, luck_until = user
    now = int(time.time())
    
    # Проверка лимита Холда (100 тегов)
    cur.execute("SELECT COUNT(*) FROM usernames WHERE owner_id = ?", (data.user_id,))
    if cur.fetchone()[0] >= 100:
        conn.close()
        raise HTTPException(status_code=400, detail="Твой ХОЛД переполнен! Продай ненужные теги.")

    active_luck = luck_multi if luck_until > now else 1.0

    # Генерация с проверкой на уникальность (15 попыток)
    for _ in range(15):
        tag, rarity, income, xp_gain, sell_price, reasons = generate_username(data.mode, active_luck)
        if rarity in ["Legendary", "Mythic", "Luxury", "Ultra-Mythic", "Exclusive", "Divine"]:
            cur.execute("SELECT tag FROM usernames WHERE tag = ?", (tag,))
            if not cur.fetchone(): break
        else:
            break
    else:
        tag = f"@tag_{random.randint(1000, 9999)}"
        rarity, income, xp_gain, sell_price, reasons = "Common", 1.0, 5, 50, "Резервный тег"

    new_balance = balance - cost
    new_xp = xp + xp_gain
    new_level = level
    while new_xp >= new_level * 150:
        new_xp -= new_level * 150
        new_level += 1

    cur.execute("UPDATE users SET balance = ?, level = ?, xp = ? WHERE tg_user_id = ?", (new_balance, new_level, new_xp, data.user_id))
    cur.execute("INSERT INTO usernames (tag, owner_id, rarity, income_per_sec, sell_price, reasons, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (tag, data.user_id, rarity, income, sell_price, reasons, now))
    conn.commit()
    conn.close()
    
    return {
        "tag": tag,
        "rarity": rarity,
        "income": income,
        "sell_price": sell_price,
        "reasons": reasons.split(','),
        "new_balance": round(new_balance, 2),
        "level": new_level,
        "xp": new_xp
    }

@app.post("/api/sell")
def sell_tag(data: SellData):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT sell_price FROM usernames WHERE tag = ? AND owner_id = ?", (data.tag, data.user_id))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=400, detail="Тег не найден в твоем Холде")
        
    price = row[0]
    cur.execute("DELETE FROM usernames WHERE tag = ?", (data.tag,))
    cur.execute("UPDATE users SET balance = balance + ? WHERE tg_user_id = ?", (price, data.user_id))
    conn.commit()
    
    cur.execute("SELECT balance FROM users WHERE tg_user_id = ?", (data.user_id,))
    new_bal = cur.fetchone()[0]
    conn.close()
    return {"sold_for": price, "new_balance": round(new_bal, 2)}

# Демократичный донат
PRICES = {
    "luck_x2_1h": {"title": "🍀 Удача x2 (1 час)", "price": 19},
    "luck_x3_2h": {"title": "🔥 Удача x3 (2 часа)", "price": 39},
    "coins_50k":  {"title": "🪙 50,000 GRAM", "price": 15},
    "coins_200k": {"title": "💰 200,000 GRAM", "price": 49},
    "vip_30d":    {"title": "👑 VIP Статус", "price": 89},
}

@app.get("/api/invoice")
async def get_invoice(payload: str):
    product = PRICES.get(payload)
    if not product: raise HTTPException(status_code=400, detail="Товар не найден")
    link = await bot.create_invoice_link(
        title=product["title"], description="Покупка в MintTags", payload=payload,
        currency="XTR", prices=[LabeledPrice(label=product["title"], amount=product["price"])]
    )
    return {"invoice_link": link}
