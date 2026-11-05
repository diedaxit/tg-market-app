import sqlite3
import random
import time
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

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
            balance REAL DEFAULT 150.0,
            last_claim INTEGER DEFAULT 0
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
    conn.close()

init_db()

WORDS_MYTHIC = ["x", "7", "ai", "tg", "ton", "vip", "god", "top", "nft", "ron"]
WORDS_LEGENDARY = ["crypto", "bank", "sueta", "money", "sigma", "prime", "boss", "whale"]
WORDS_EPIC = ["cyber", "dark", "king", "flex", "gold", "shadow", "drop", "code"]
WORDS_RARE = ["ghost", "speed", "drift", "power", "club", "trade", "flow", "alpha"]

def generate_username():
    roll = random.random()
    if roll < 0.01:
        tag = "@" + random.choice(WORDS_MYTHIC)
        return tag, "Mythic", 12.0
    elif roll < 0.06:
        tag = "@" + random.choice(WORDS_LEGENDARY)
        return tag, "Legendary", 5.0
    elif roll < 0.20:
        tag = "@" + random.choice(WORDS_EPIC)
        return tag, "Epic", 2.0
    elif roll < 0.50:
        tag = "@" + random.choice(WORDS_RARE)
        return tag, "Rare", 0.8
    else:
        suffix = random.randint(10, 999)
        base = random.choice(["user", "gamer", "star", "night", "pro", "zone", "player"])
        tag = f"@{base}_{suffix}"
        return tag, "Common", 0.2

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
        cur.execute("INSERT INTO users (tg_user_id, username, balance, last_claim) VALUES (?, ?, 150.0, ?)",
                    (data.user_id, data.username, now))
        conn.commit()
        member_num = cur.lastrowid
        res = {"member_number": member_num, "balance": 150.0, "is_new": True}
    else:
        res = {"member_number": row[0], "balance": row[1], "is_new": False}
    
    conn.close()
    return res

@app.get("/api/state/{user_id}")
def get_user_state(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT member_number, balance, last_claim FROM users WHERE tg_user_id = ?", (user_id,))
    user = cur.fetchone()
    if not user:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found")
        
    member_number, balance, last_claim = user
    cur.execute("SELECT tag, rarity, income_per_sec FROM usernames WHERE owner_id = ? ORDER BY income_per_sec DESC", (user_id,))
    tags = [{"tag": r[0], "rarity": r[1], "income": r[2]} for r in cur.fetchall()]
    
    total_rate = sum(t["income"] for t in tags)
    now = int(time.time())
    unclaimed = total_rate * min(now - last_claim, 28800)
    
    conn.close()
    return {
        "member_number": member_number,
        "balance": round(balance, 2),
        "total_rate": round(total_rate, 2),
        "unclaimed": round(unclaimed, 2),
        "tags": tags
    }

@app.post("/api/claim/{user_id}")
def claim(user_id: int):
    now = int(time.time())
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    
    cur.execute("SELECT balance, last_claim FROM users WHERE tg_user_id = ?", (user_id,))
    user = cur.fetchone()
    if not user:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found")
        
    balance, last_claim = user
    cur.execute("SELECT SUM(income_per_sec) FROM usernames WHERE owner_id = ?", (user_id,))
    rate = cur.fetchone()[0] or 0.0
    
    passed = min(now - last_claim, 28800)
    profit = rate * passed
    new_bal = balance + profit
    
    cur.execute("UPDATE users SET balance = ?, last_claim = ? WHERE tg_user_id = ?", (new_bal, now, user_id))
    conn.commit()
    conn.close()
    return {"claimed": round(profit, 2), "new_balance": round(new_bal, 2)}

@app.post("/api/mint/{user_id}")
def mint(user_id: int):
    MINT_COST = 50.0
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    
    cur.execute("SELECT balance FROM users WHERE tg_user_id = ?", (user_id,))
    user = cur.fetchone()
    if not user or user[0] < MINT_COST:
        conn.close()
        raise HTTPException(status_code=400, detail="Недостаточно монет для создания!")
        
    for _ in range(15):
        tag, rarity, income = generate_username()
        cur.execute("SELECT tag FROM usernames WHERE tag = ?", (tag,))
        if not cur.fetchone():
            break
    else:
        tag = f"@tag_{random.randint(1000, 9999)}"
        rarity = "Common"
        income = 0.2

    new_balance = user[0] - MINT_COST
    now = int(time.time())
    cur.execute("UPDATE users SET balance = ? WHERE tg_user_id = ?", (new_balance, user_id))
    cur.execute("INSERT INTO usernames (tag, owner_id, rarity, income_per_sec, created_at) VALUES (?, ?, ?, ?, ?)",
                (tag, user_id, rarity, income, now))
    conn.commit()
    conn.close()
    
    return {
        "tag": tag,
        "rarity": rarity,
        "income": income,
        "new_balance": round(new_balance, 2)
    }
    from aiogram.types import LabeledPrice
from bot import bot

PRICES = {
    "luck_x2_1h": {"title": "Удача x2 (1 час)", "price": 15},
    "luck_x3_2h": {"title": "Удача x3 (2 часа)", "price": 25},
    "coins_50k":  {"title": "50,000 COIN", "price": 10},
    "vip_30d":    {"title": "VIP на 30 дней", "price": 99},
}

@app.get("/api/invoice")
async def get_invoice(payload: str):
    product = PRICES.get(payload)
    if not product:
        raise HTTPException(status_code=400, detail="Товар не найден")
    
    link = await bot.create_invoice_link(
        title=product["title"],
        description="Внутриигровая покупка в MintTags",
        payload=payload,
        currency="XTR",
        prices=[LabeledPrice(label=product["title"], amount=product["price"])]
    )
    return {"invoice_link": link}
