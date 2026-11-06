import sqlite3
import random
import time
import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
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
            level INTEGER DEFAULT 1,
            xp INTEGER DEFAULT 0,
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
            last_claim INTEGER DEFAULT 0,
            created_at INTEGER
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
            is_equipped INTEGER DEFAULT 0,
            channel_slot INTEGER DEFAULT 0,
            is_saved INTEGER DEFAULT 1,
            created_at INTEGER,
            FOREIGN KEY(owner_id) REFERENCES users(tg_user_id)
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

    # Безопасная миграция для существующей БД
    cur.execute("PRAGMA table_info(users)")
    u_cols = [c[1] for c in cur.fetchall()]
    user_migrations = [
        ("member_number", "INTEGER DEFAULT 1"),
        ("vip_until", "INTEGER DEFAULT 0"),
        ("max_hold", "INTEGER DEFAULT 100"),
        ("max_channels", "INTEGER DEFAULT 2"),
        ("ref_by", "INTEGER DEFAULT NULL"),
        ("refs_count", "INTEGER DEFAULT 0"),
        ("smm_lvl", "INTEGER DEFAULT 1"),
        ("buyer_lvl", "INTEGER DEFAULT 0"),
        ("clan_id", "TEXT DEFAULT NULL"),
        ("pity_50", "INTEGER DEFAULT 0"),
        ("pity_100", "INTEGER DEFAULT 0")
    ]
    for col, ctype in user_migrations:
        if col not in u_cols:
            try:
                cur.execute(f"ALTER TABLE users ADD COLUMN {col} {ctype}")
            except Exception:
                pass

    cur.execute("PRAGMA table_info(usernames)")
    t_cols = [c[1] for c in cur.fetchall()]
    for col, ctype in [("is_equipped", "INTEGER DEFAULT 0"), ("channel_slot", "INTEGER DEFAULT 0"), ("is_saved", "INTEGER DEFAULT 1")]:
        if col not in t_cols:
            try:
                cur.execute(f"ALTER TABLE usernames ADD COLUMN {col} {ctype}")
            except Exception:
                pass

    # Инициализация стартовых кланов
    default_clans = [
        ("ton_whales", "🐋 TON Whales", 250000.0, 14),
        ("durov_syndicate", "👑 Durov Syndicate", 520000.0, 28),
        ("emerald_cartel", "💚 Emerald Cartel", 180000.0, 9)
    ]
    for cid, cname, ctr, cmem in default_clans:
        cur.execute("INSERT OR IGNORE INTO clans (clan_id, name, treasury, members_count) VALUES (?, ?, ?, ?)", (cid, cname, ctr, cmem))

    conn.commit()
    conn.close()

init_db()

# Словарь переводов и смыслов для описания ценности
WORD_MEANINGS = {
    "x": "Буква «X» — символ империи", "v": "Символ Победы (Victory)", "ai": "Искусственный Интеллект",
    "go": "Движение («Вперед»)", "ok": "Мировой символ согласия", "up": "Вечный рост («Вверх»)",
    "durov": "Фамилия основателя Telegram", "telegram": "Главный мессенджер мира", "ton": "Блокчейн The Open Network",
    "notcoin": "Легендарный веб3-токен", "pavel": "Имя основателя", "vk": "Крупнейшая соцсеть", "redo": "Символ Resistance Dog",
    "cat": "Слово «Кот»", "dog": "Слово «Пес»", "bot": "Слово «Бот»", "nft": "Крипто-токен NFT",
    "god": "Слово «Бог»", "top": "Слово «Топ»", "ceo": "Генеральный директор",
    "dubai": "Столица роскоши («Дубай»)", "money": "Слово «Деньги»", "rich": "Слово «Богатый»",
    "gold": "Слово «Золото»", "boss": "Слово «Босс»", "king": "Слово «Король»", "stars": "Слово «Звезды»",
    "star": "Слово «Звезда»", "epic": "Слово «Эпичный»", "moon": "Крипто-мем «На Луну»", "flow": "Слово «Поток»",
    "dark": "Слово «Темный»", "litvin": "Топ-блогер Михаил Литвин", "mellstroy": "Топ-стример Мелстрой",
    "mrbeast": "Главный ютубер мира MrBeast", "tiger": "Слово «Тигр»", "ghost": "Слово «Призрак»",
    "alpha": "Лидер («Альфа»)", "prime": "Статус «Прайм»", "whale": "Крипто-кит («Кит»)",
    "wylsa": "Топ техно-блогер Wylsacom", "subo": "Популярный блогер Субо", "buster": "Топ-стример Бустер",
    "hasbulla": "Мировая звезда Хасбик", "karna_val": "Тиктокер Валя Карнавал"
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

RARITIES = [
    {"name": "Common",       "w": 780000, "inc": 1,      "xp": 5,     "sell": 50},
    {"name": "Uncommon",     "w": 160000, "inc": 5,      "xp": 15,    "sell": 250},
    {"name": "Rare",         "w": 45000,  "inc": 15,     "xp": 40,    "sell": 750},
    {"name": "Epic",         "w": 12000,  "inc": 50,     "xp": 100,   "sell": 2500},
    {"name": "Legendary",    "w": 2200,   "inc": 200,    "xp": 300,   "sell": 10000},
    {"name": "Mythic",       "w": 550,    "inc": 450,    "xp": 800,   "sell": 25000},
    {"name": "Luxury",       "w": 180,    "inc": 1500,   "xp": 1500,  "sell": 75000},
    {"name": "Ultra-Mythic", "w": 50,     "inc": 5000,   "xp": 2500,  "sell": 200000},
    {"name": "Exclusive",    "w": 15,     "inc": 25000,  "xp": 5000,  "sell": 800000},
    {"name": "Divine",       "w": 5,      "inc": 100000, "xp": 15000, "sell": 3000000}
]

SPIN_MODES = {
    "basic":   {"cost": 100,  "min_idx": 0},
    "silver":  {"cost": 300,  "min_idx": 1},
    "gold":    {"cost": 1000, "min_idx": 2},
    "diamond": {"cost": 5000, "min_idx": 3}
}

RECENT_ROOTS = []

def generate_live_nickname():
    """Генерирует естественные, живые ники, которые используют реальные пользователи Telegram"""
    syllables = ["ka", "mi", "ro", "va", "ze", "lu", "no", "ta", "ke", "si", "da", "ve", "xo", "ni", "ba", "le", "fa", "mo", "ri", "to", "sa", "ku"]
    prefixes = ["neo", "ava", "max", "leo", "dan", "nik", "art", "tim", "evg", "kir", "rom", "vlad", "mak", "sem", "gleb", "yar"]
    suffixes = ["ov", "ev", "sk", "ix", "on", "er", "ik", "us", "in", "ax", "ez"]
    
    style = random.randint(1, 3)
    if style == 1:
        base = "".join(random.sample(syllables, random.randint(2, 3)))
    elif style == 2:
        base = random.choice(prefixes) + random.choice(syllables) + random.choice(suffixes)
    else:
        base = random.choice(prefixes) + random.choice(suffixes)
    return base

def generate_tag(cur, mode: str, luck: float, force_epic: bool = False):
    global RECENT_ROOTS
    min_idx = 3 if force_epic else SPIN_MODES[mode]["min_idx"]
    
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
    word = None

    if rarity in WORDS:
        candidates = [w for w in WORDS[rarity] if w not in RECENT_ROOTS] or WORDS[rarity][:]
        random.shuffle(candidates)
        for w in candidates:
            if rarity in ["Divine", "Exclusive", "Ultra-Mythic", "Luxury", "Mythic", "Legendary"]:
                cur.execute("SELECT tag FROM usernames WHERE tag = ?", (f"@{w}",))
                if not cur.fetchone():
                    word = w
                    break
            else:
                word = w
                break
        if not word:
            rarity = "Epic"
            picked = RARITIES[3]
            word = random.choice(WORDS["Epic"])

    reasons = []
    if rarity in ["Divine", "Exclusive", "Ultra-Mythic", "Luxury", "Mythic", "Legendary"]:
        tag = f"@{word}"
        meaning = WORD_MEANINGS.get(word, f"Премиум слово «{word.upper()}»")
        reasons = [
            f"💡 {meaning}",
            "🚫 Без цифр и нижних подчеркиваний",
            f"📏 Длина: {len(word)} симв. (Высокая ценность)"
        ]
    elif rarity == "Epic":
        tag = f"@{word}{random.randint(1, 19)}"
        reasons = [f"💡 Корень «{word}»", "✅ Короткий суффикс без _", "📏 Легко читается и запоминается"]
    elif rarity == "Rare":
        tag = f"@{word}_{random.choice(['official', 'real', 'tg', 'hq', 'vip'])}"
        reasons = ["✅ Статусная приставка", "📏 Узнаваемый корень слова"]
    elif rarity == "Uncommon":
        base = generate_live_nickname()
        while base in RECENT_ROOTS:
            base = generate_live_nickname()
        word = base
        tag = f"@{base}{random.choice(['', '_' + str(random.randint(1, 99)), str(random.randint(10, 99))])}"
        if tag == f"@{base}":
            reasons = ["✅ Чистый живой никнейм без цифр", f"📏 {len(base)} букв"]
        else:
            reasons = ["✅ Реалистичный никнейм", "✅ Короткий тег"]
    else:
        base = generate_live_nickname()
        word = base
        year_or_num = random.choice([random.randint(1995, 2009), random.randint(100, 9999)])
        tag = f"@{base}{year_or_num}"
        reasons = ["Живой пользовательский никнейм", "Стандартный числовой индекс"]

    if word:
        RECENT_ROOTS.append(word)
        if len(RECENT_ROOTS) > 6:
            RECENT_ROOTS.pop(0)

    return tag, rarity, picked["inc"], picked["xp"], picked["sell"], "|".join(reasons)

def auto_sell_unsaved(cur, user_id: int) -> float:
    cur.execute("SELECT SUM(sell_price) FROM usernames WHERE owner_id = ? AND is_saved = 0", (user_id,))
    val = cur.fetchone()[0]
    if val and val > 0:
        cur.execute("UPDATE users SET balance = balance + ? WHERE tg_user_id = ?", (val, user_id))
        cur.execute("DELETE FROM usernames WHERE owner_id = ? AND is_saved = 0", (user_id,))
        return float(val)
    return 0.0

def process_passive_income(cur, user_id: int):
    now = int(time.time())
    cur.execute("SELECT balance, last_claim, smm_lvl, buyer_lvl, vip_until, clan_id FROM users WHERE tg_user_id = ?", (user_id,))
    u = cur.fetchone()
    if not u:
        return 0.0
    balance, last_claim, smm, buyer, vip_until, clan_id = u
    if last_claim <= 0:
        cur.execute("UPDATE users SET last_claim = ? WHERE tg_user_id = ?", (now, user_id))
        return 0.0

    elapsed = min(max(0, now - last_claim), 43200)
    if elapsed < 2:
        return 0.0

    cur.execute("SELECT SUM(income_per_sec) FROM usernames WHERE owner_id = ? AND is_equipped = 1 AND is_saved = 1", (user_id,))
    tag_inc = cur.fetchone()[0] or 0.0
    mgr_inc = (smm * 2.0) + (buyer * 10.0)
    total_rate = tag_inc + mgr_inc if tag_inc > 0 else 0.0

    if vip_until > now:
        total_rate *= 2.0
    if clan_id:
        total_rate *= 1.15

    earned = total_rate * elapsed
    if earned > 0:
        cur.execute("UPDATE users SET balance = balance + ?, last_claim = ? WHERE tg_user_id = ?", (earned, now, user_id))
    else:
        cur.execute("UPDATE users SET last_claim = ? WHERE tg_user_id = ?", (now, user_id))
    return earned

class ReqLogin(BaseModel):
    user_id: int
    username: str = "Player"
    ref_by: str = ""

class ReqMint(BaseModel):
    user_id: int
    mode: str = "basic"
    spin_count: int = 1

class ReqAction(BaseModel):
    user_id: int
    tag: str
    action_type: str
    slot: int = 1

class ReqManager(BaseModel):
    user_id: int
    mgr_type: str

class ReqClan(BaseModel):
    user_id: int
    clan_id: str
    donate_amount: float = 0.0

class ReqDonate(BaseModel):
    user_id: int
    payload: str

@app.get("/")
def serve_index():
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return HTMLResponse("<h2>index.html not found</h2>", status_code=404)

@app.post("/api/login")
def login(data: ReqLogin):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    now = int(time.time())

    cur.execute("SELECT tg_user_id FROM users WHERE tg_user_id = ?", (data.user_id,))
    exists = cur.fetchone()

    if not exists:
        ref_id = None
        if data.ref_by and data.ref_by.startswith("ref_"):
            try:
                candidate = int(data.ref_by.split("_")[1])
                if candidate != data.user_id:
                    cur.execute("SELECT refs_count FROM users WHERE tg_user_id = ?", (candidate,))
                    r_user = cur.fetchone()
                    if r_user:
                        ref_id = candidate
                        new_cnt = r_user[0] + 1
                        reward = 1000.0
                        if new_cnt == 2: reward = 3000.0
                        elif new_cnt == 5: reward = 10000.0
                        elif new_cnt == 20: reward = 1000000.0
                        cur.execute("UPDATE users SET refs_count = ?, balance = balance + ? WHERE tg_user_id = ?", (new_cnt, reward, ref_id))
            except Exception:
                pass

        cur.execute("""
            INSERT INTO users (tg_user_id, username, balance, level, xp, ref_by, last_claim, created_at)
            VALUES (?, ?, 1500.0, 1, 0, ?, ?, ?)
        """, (data.user_id, data.username, ref_id, now, now))
    else:
        cur.execute("UPDATE users SET username = ? WHERE tg_user_id = ?", (data.username, data.user_id))
        auto_sell_unsaved(cur, data.user_id)
        process_passive_income(cur, data.user_id)

    conn.commit()
    conn.close()
    return {"status": "ok"}

@app.get("/api/state/{uid}")
def get_state(uid: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    now = int(time.time())

    process_passive_income(cur, uid)
    conn.commit()

    cur.execute("""
        SELECT rowid, balance, level, xp, smm_lvl, buyer_lvl, luck_multi, luck_until,
               vip_until, max_hold, max_channels, refs_count, clan_id, pity_50, pity_100
        FROM users WHERE tg_user_id = ?
    """, (uid,))
    u = cur.fetchone()
    if not u:
        conn.close()
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    (member_num, balance, level, xp, smm, buyer, luck_m, luck_u,
     vip_u, max_hold, max_ch, refs_cnt, clan_id, pity50, pity100) = u

    cur.execute("""
        SELECT tag, rarity, income_per_sec, sell_price, reasons, is_equipped, channel_slot
        FROM usernames WHERE owner_id = ? AND is_saved = 1
        ORDER BY income_per_sec DESC
    """, (uid,))
    tags = []
    for r in cur.fetchall():
        tags.append({
            "tag": r[0], "rarity": r[1], "inc": r[2], "sell": r[3],
            "reasons": r[4].split("|") if r[4] else [], "eq": r[5], "slot": r[6]
        })

    # Расчет места в лидерборде
    cur.execute("SELECT COUNT(*) + 1 FROM users WHERE balance > ?", (balance,))
    my_rank = cur.fetchone()[0]

    cur.execute("SELECT username, balance, level FROM users ORDER BY balance DESC LIMIT 10")
    leaders = [{"username": r[0] or "Аноним", "balance": round(r[1], 0), "level": r[2]} for r in cur.fetchall()]

    cur.execute("SELECT clan_id, name, treasury, members_count FROM clans ORDER BY treasury DESC")
    clans = [{"id": r[0], "name": r[1], "treasury": round(r[2], 0), "members": r[3]} for r in cur.fetchall()]

    conn.close()
    is_vip = vip_u > now
    active_luck = (luck_m if luck_u > now else 1.0) * (1.5 if is_vip else 1.0)

    return {
        "member_number": member_num,
        "balance": round(balance, 2),
        "level": level,
        "xp": xp,
        "smm": smm,
        "buyer": buyer,
        "luck_multi": round(active_luck, 2),
        "luck_left": max(0, luck_u - now),
        "is_vip": is_vip,
        "vip_left": max(0, vip_u - now),
        "max_hold": max_hold,
        "max_channels": max_ch,
        "refs_count": refs_cnt,
        "clan_id": clan_id,
        "pity_50": pity50,
        "pity_100": pity100,
        "my_rank": my_rank,
        "leaders": leaders,
        "clans": clans,
        "tags": tags
    }

@app.post("/api/mint")
def mint(data: ReqMint):
    if data.mode not in SPIN_MODES:
        raise HTTPException(status_code=400, detail="Неверный режим прокрутки")
    if data.spin_count not in [1, 5]:
        raise HTTPException(status_code=400, detail="Допустимо крутить по 1 или 5 тегов")

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    now = int(time.time())

    auto_sold = auto_sell_unsaved(cur, data.user_id)
    process_passive_income(cur, data.user_id)

    cur.execute("SELECT balance, level, xp, luck_multi, luck_until, vip_until, pity_50, pity_100 FROM users WHERE tg_user_id = ?", (data.user_id,))
    u = cur.fetchone()
    if not u:
        conn.close()
        raise HTTPException(status_code=404, detail="Игрок не найден")

    balance, level, xp, luck_m, luck_u, vip_u, pity50, pity100 = u
    cost = SPIN_MODES[data.mode]["cost"] * data.spin_count
    if balance < cost:
        conn.close()
        raise HTTPException(status_code=400, detail=f"Недостаточно GRAM! Нужно {cost}")

    is_vip = vip_u > now
    base_luck = (luck_m if luck_u > now else 1.0) * (1.5 if is_vip else 1.0)

    drops = []
    added_xp = 0

    for _ in range(data.spin_count):
        pity50 += 1
        pity100 += 1
        spin_luck = base_luck * (2.0 if pity50 >= 50 else 1.0)
        if pity50 >= 50:
            pity50 = 0
        force_epic = False
        if pity100 >= 100:
            force_epic = True
            pity100 = 0

        for _ in range(12):
            tag, rar, inc, xpg, sell, reas = generate_tag(cur, data.mode, spin_luck, force_epic)
            cur.execute("SELECT tag FROM usernames WHERE tag = ?", (tag,))
            if not cur.fetchone():
                break
        else:
            tag = f"@{generate_live_nickname()}{random.randint(100, 9999)}"
            rar, inc, xpg, sell, reas = "Common", 1.0, 5, 50.0, "Живой никнейм|Стандартный индекс"

        cur.execute("""
            INSERT INTO usernames (tag, owner_id, rarity, income_per_sec, sell_price, reasons, is_equipped, channel_slot, is_saved, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0, ?)
        """, (tag, data.user_id, rar, inc, sell, reas, now))

        drops.append({"tag": tag, "rarity": rar, "inc": inc, "xp": xpg, "sell": sell, "reasons": reas.split("|")})
        added_xp += xpg

    new_bal = balance - cost
    new_xp = xp + added_xp
    new_lvl = level
    while new_xp >= new_lvl * 150:
        new_xp -= new_lvl * 150
        new_lvl += 1

    cur.execute("""
        UPDATE users SET balance = ?, level = ?, xp = ?, pity_50 = ?, pity_100 = ?
        WHERE tg_user_id = ?
    """, (new_bal, new_lvl, new_xp, pity50, pity100, data.user_id))

    conn.commit()
    conn.close()
    return {"drops": drops, "auto_sold": auto_sold}

@app.post("/api/action")
def tag_action(data: ReqAction):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute("SELECT sell_price, is_saved, is_equipped FROM usernames WHERE tag = ? AND owner_id = ?", (data.tag, data.user_id))
    t = cur.fetchone()
    if not t:
        conn.close()
        raise HTTPException(status_code=400, detail="Тег не найден")

    sell_price, is_saved, is_eq = t

    if data.action_type == "save":
        cur.execute("SELECT max_hold FROM users WHERE tg_user_id = ?", (data.user_id,))
        max_h = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM usernames WHERE owner_id = ? AND is_saved = 1", (data.user_id,))
        if cur.fetchone()[0] >= max_h:
            conn.close()
            raise HTTPException(status_code=400, detail=f"Сейф ХОЛД переполнен ({max_h} мест)!")
        cur.execute("UPDATE usernames SET is_saved = 1 WHERE tag = ? AND owner_id = ?", (data.tag, data.user_id))

    elif data.action_type == "sell":
        if is_eq == 1:
            conn.close()
            raise HTTPException(status_code=400, detail="Сначала снимите тег с канала!")
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

    conn.commit()
    conn.close()
    return {"status": "ok", "sold_for": sell_price}

@app.post("/api/upgrade_mgr")
def upgrade_manager(data: ReqManager):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT balance, smm_lvl, buyer_lvl FROM users WHERE tg_user_id = ?", (data.user_id,))
    u = cur.fetchone()
    if not u:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found")
    bal, smm, buyer = u

    if data.mgr_type == "smm":
        cost = smm * 250.0
        if bal < cost:
            conn.close()
            raise HTTPException(status_code=400, detail="Не хватает GRAM для прокачки СММщика")
        cur.execute("UPDATE users SET balance = balance - ?, smm_lvl = smm_lvl + 1 WHERE tg_user_id = ?", (cost, data.user_id))
    else:
        cost = (buyer + 1) * 1000.0
        if bal < cost:
            conn.close()
            raise HTTPException(status_code=400, detail="Не хватает GRAM для прокачки Байера")
        cur.execute("UPDATE users SET balance = balance - ?, buyer_lvl = buyer_lvl + 1 WHERE tg_user_id = ?", (cost, data.user_id))

    conn.commit()
    conn.close()
    return {"status": "ok"}

@app.post("/api/clan_action")
def clan_action(data: ReqClan):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    if data.donate_amount > 0:
        cur.execute("SELECT balance FROM users WHERE tg_user_id = ?", (data.user_id,))
        bal = cur.fetchone()[0]
        if bal < data.donate_amount:
            conn.close()
            raise HTTPException(status_code=400, detail="Недостаточно GRAM для взноса в казну")
        cur.execute("UPDATE users SET balance = balance - ? WHERE tg_user_id = ?", (data.donate_amount, data.user_id))
        cur.execute("UPDATE clans SET treasury = treasury + ? WHERE clan_id = ?", (data.donate_amount, data.clan_id))
    else:
        cur.execute("UPDATE users SET clan_id = ? WHERE tg_user_id = ?", (data.clan_id, data.user_id))
    conn.commit()
    conn.close()
    return {"status": "ok"}

# РАСШИРЕННЫЙ КАТАЛОГ ДОНАТА В STARS
PRICES = {
    "vip_pass":     {"title": "👑 VIP Game Pass (30 дней)", "price": 89},
    "luck_x2_1h":   {"title": "🍀 Буст Удачи x2 (1 час)", "price": 19},
    "luck_x3_2h":   {"title": "🔥 Мега Удача x3 (2 часа)", "price": 39},
    "hold_plus_50": {"title": "💼 +50 слотов в сейф ХОЛД", "price": 45},
    "channel_slot": {"title": "📢 Новый слот Канала", "price": 59},
    "coins_50k":    {"title": "🪙 50,000 GRAM в казну", "price": 15},
    "coins_250k":   {"title": "💰 250,000 GRAM Магната", "price": 49},
    "blogger_box":  {"title": "🎁 Секретный Бокс (Legendary+)", "price": 75}
}

@app.get("/api/invoice")
async def get_invoice(payload: str):
    product = PRICES.get(payload)
    if not product:
        raise HTTPException(status_code=400, detail="Товар не найден")
    link = await bot.create_invoice_link(
        title=product["title"],
        description="Премиальное усиление в MintTags: Media Empire",
        payload=payload,
        currency="XTR",
        prices=[LabeledPrice(label=product["title"], amount=product["price"])]
    )
    return {"invoice_link": link}

@app.post("/api/activate_donate")
def activate_donate(data: ReqDonate):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    now = int(time.time())
    p = data.payload

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
    elif p == "blogger_box":
        w = random.choice(WORDS["Mythic"] + WORDS["Legendary"])
        tag = f"@{w}_{random.randint(1,9)}" if cur.execute("SELECT 1 FROM usernames WHERE tag=?", (f"@{w}",)).fetchone() else f"@{w}"
        cur.execute("INSERT INTO usernames (tag, owner_id, rarity, income_per_sec, sell_price, reasons, is_saved, created_at) VALUES (?,?,?,?,?,?,1,?)",
                    (tag, data.user_id, "Mythic", 450.0, 25000.0, "🎁 Дроп из Секретного Бокса|🚫 Эксклюзивная серия", now))

    conn.commit()
    conn.close()
    return {"status": "ok"}
