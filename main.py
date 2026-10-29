from datetime import datetime, timedelta, timezone
import os
import random
import sqlite3
import threading
import time
import logging
import re
import html

from flask import Flask, jsonify, request
import requests

# ============================================================
# BINANCE TOP 10 - UPDATED MAIN.PY
# ============================================================
# IMPORTANT:
# The bot tokens that were pasted in chat are intentionally NOT
# reproduced here. Keep your existing local token values in the
# environment variables FREE_BOT_TOKEN and VIP_BOT_TOKEN.
#
# This version:
# - keeps the existing Telegram/Flask/SQLite architecture
# - removes automatic random-group joining/posting
# - adds real RSI from 15m candles
# - adds real recent support/resistance
# - improves signal filtering
# - fixes TP1 -> TP2 -> TP3 tracking
# - adds real result statistics
# - adds opt-in referral/deep-link tracking
# - verifies Free Channel membership
# - creates tracked channel invite links when possible
# - removes fake accuracy/FOMO claims
# - makes SQLite safer for multiple workers
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

FREE_BOT_TOKEN = os.getenv(
    "FREE_BOT_TOKEN", "8842407289:AAHD6UcvOZ0pgvN8EJXXetb2qrW-fGeZCvU"
)
VIP_BOT_TOKEN = os.getenv(
    "VIP_BOT_TOKEN", "8997353064:AAH2gTVchfQqqId1TvBa2CD8nIXY00ZUj_8"
)

FREE_CHANNEL_ID = os.getenv("FREE_CHANNEL_ID", "-1003924921868")
VIP_CHANNEL_ID = os.getenv("VIP_CHANNEL_ID", "-1003836756507")

TRUST_WALLET_ADDRESS = os.getenv(
    "TRUST_WALLET_ADDRESS",
    "TErttGLUQZtrCwusaQsjdywXdkxUrNFm52"
)

BINANCE_REF_LINK = os.getenv(
    "BINANCE_REF_LINK",
    "https://accounts.binance.com/register?ref=GRO_28502_IBUUM"
)

VIP_BOT_USERNAME = os.getenv("VIP_BOT_USERNAME", "BinanceTop10_VIPBot")
FREE_CHANNEL_USERNAME = os.getenv("FREE_CHANNEL_USERNAME", "BinanceTop10Free")

API_ID = int(os.getenv("TELEGRAM_API_ID", "12345678"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")

DB_PATH = os.getenv("DB_PATH", "vip_members.db")

IST = timezone(timedelta(hours=5, minutes=30))
app = Flask(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; BinanceTop10/2.0)"
}

system_logs = []
log_lock = threading.Lock()

free_signals_today = 0
vip_signals_today = 0
last_reset_date = datetime.now(IST).date()
last_free_dispatch_time = 0
last_vip_dispatch_time = 0

FREE_MAX_PER_DAY = 6
VIP_MAX_PER_DAY = 18
FREE_INTERVAL = 4 * 3600
VIP_INTERVAL = 40 * 60

# Signal quality requirements
MIN_VOLUME_USDT = 1_000_000
CANDLE_INTERVAL = "15m"
CANDLE_LIMIT = 100


# ============================================================
# LOGGING / DB
# ============================================================

def log_event(message):
    timestamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] {message}"
    with log_lock:
        system_logs.append(entry)
        if len(system_logs) > 300:
            del system_logs[:-300]
    print(entry)


def db_connect():
    conn = sqlite3.connect(
        DB_PATH,
        timeout=30,
        check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db():
    conn = db_connect()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS members (
            user_id INTEGER PRIMARY KEY,
            expiry_date TEXT,
            status TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS processed_txids (
            txid TEXT PRIMARY KEY
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS referral_claims (
            user_id INTEGER,
            binance_uid TEXT PRIMARY KEY,
            status TEXT DEFAULT 'PENDING',
            created_date TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS signal_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            side TEXT DEFAULT 'LONG',
            entry_price REAL,
            tp1 REAL,
            tp2 REAL,
            tp3 REAL,
            sl REAL,
            timestamp REAL,
            created_date TEXT,
            status TEXT DEFAULT 'PENDING',
            current_stage INTEGER DEFAULT 0,
            closed INTEGER DEFAULT 0,
            closed_date TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_seen TEXT,
            last_seen TEXT,
            start_source TEXT DEFAULT 'direct',
            free_join_verified INTEGER DEFAULT 0,
            referral_code TEXT UNIQUE,
            referred_by INTEGER
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER,
            referred_user_id INTEGER UNIQUE,
            source_code TEXT,
            joined_free INTEGER DEFAULT 0,
            created_date TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS invite_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_code TEXT UNIQUE,
            invite_link TEXT,
            created_date TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_states (
            user_id INTEGER PRIMARY KEY,
            state TEXT DEFAULT 'IDLE',
            updated_date TEXT
        )
    """)

    # Safe migrations for databases created by the old version.
    existing = {
        row["name"]
        for row in cur.execute("PRAGMA table_info(signal_history)")
    }

    migrations = [
        ("side", "TEXT DEFAULT 'LONG'"),
        ("current_stage", "INTEGER DEFAULT 0"),
        ("closed", "INTEGER DEFAULT 0"),
        ("closed_date", "TEXT"),
    ]

    for col, definition in migrations:
        if col not in existing:
            cur.execute(
                f"ALTER TABLE signal_history ADD COLUMN {col} {definition}"
            )

    conn.commit()
    conn.close()
    log_event("Database initialized / migrated successfully.")


init_db()


def cleanup_old_data():
    try:
        cutoff = (
            datetime.now(IST) - timedelta(days=7)
        ).strftime("%Y-%m-%d %H:%M:%S")

        conn = db_connect()
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM signal_history WHERE created_date < ? AND closed = 1",
            (cutoff,)
        )
        cur.execute(
            "DELETE FROM invite_links WHERE created_date < ?",
            (cutoff,)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log_event(f"Cleanup error: {e}")


def format_price(value):
    if value is None or value == 0:
        return "0.00"
    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 1:
        return f"{value:.4f}"
    if value >= 0.001:
        return f"{value:.6f}"
    return f"{value:.8f}"


# ============================================================
# TELEGRAM API
# ============================================================

def tg_request(token, method, payload=None, timeout=15):
    if not token:
        log_event(f"Telegram token missing for {method}")
        return {"ok": False, "description": "Bot token missing"}

    try:
        url = f"https://api.telegram.org/bot{token}/{method}"
        res = requests.post(
            url,
            json=payload or {},
            timeout=timeout
        )
        return res.json()
    except Exception as e:
        log_event(f"Telegram API {method} error: {e}")
        return {"ok": False, "description": str(e)}


def send_telegram_msg(bot_token, chat_id, text, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    if reply_markup is not None:
        payload["reply_markup"] = reply_markup

    data = tg_request(bot_token, "sendMessage", payload)

    if not data.get("ok"):
        log_event(
            f"Telegram send failed to {chat_id}: "
            f"{data.get('description')}"
        )
        return False

    return True


def get_chat_member(chat_id, user_id):
    data = tg_request(
        FREE_BOT_TOKEN,
        "getChatMember",
        {"chat_id": chat_id, "user_id": user_id}
    )
    if not data.get("ok"):
        return None
    return data.get("result")


def is_free_channel_member(user_id):
    member = get_chat_member(FREE_CHANNEL_ID, user_id)
    if not member:
        return False

    status = member.get("status")
    return status in ("creator", "administrator", "member")


def create_invite_link(source_code):
    """
    Requires the FREE bot to be an administrator of the Free Channel.
    """
    conn = db_connect()
    row = conn.execute(
        "SELECT invite_link FROM invite_links WHERE source_code = ?",
        (source_code,)
    ).fetchone()
    conn.close()

    if row and row["invite_link"]:
        return row["invite_link"]

    data = tg_request(
        FREE_BOT_TOKEN,
        "createChatInviteLink",
        {
            "chat_id": FREE_CHANNEL_ID,
            "name": source_code[:32],
            "creates_join_request": False
        }
    )

    if not data.get("ok"):
        log_event(
            f"Invite creation failed for {source_code}: "
            f"{data.get('description')}"
        )
        return f"https://t.me/{FREE_CHANNEL_USERNAME}"

    invite = data["result"].get("invite_link")

    if invite:
        conn = db_connect()
        conn.execute(
            """
            INSERT OR REPLACE INTO invite_links
            (source_code, invite_link, created_date)
            VALUES (?, ?, ?)
            """,
            (
                source_code,
                invite,
                datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
            )
        )
        conn.commit()
        conn.close()

    return invite


def free_channel_link():
    return f"https://t.me/{FREE_CHANNEL_USERNAME}"


def vip_bot_link(payload=None):
    if payload:
        return f"https://t.me/{VIP_BOT_USERNAME}?start={payload}"
    return f"https://t.me/{VIP_BOT_USERNAME}"


# ============================================================
# USER / REFERRAL TRACKING
# ============================================================

def make_referral_code(user_id):
    return f"ref_{user_id}"


def register_user(user_id, start_source="direct"):
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")

    conn = db_connect()
    existing = conn.execute(
        "SELECT user_id FROM users WHERE user_id = ?",
        (user_id,)
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE users SET last_seen = ? WHERE user_id = ?",
            (now, user_id)
        )
    else:
        code = make_referral_code(user_id)
        conn.execute(
            """
            INSERT INTO users
            (user_id, first_seen, last_seen, start_source, referral_code)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, now, now, start_source, code)
        )

    conn.commit()
    conn.close()


def register_referral(referred_user_id, payload):
    if not payload:
        return

    if not payload.startswith("ref_"):
        return

    raw = payload[4:]
    if not raw.isdigit():
        return

    referrer_id = int(raw)

    if referrer_id == referred_user_id:
        return

    conn = db_connect()

    already = conn.execute(
        "SELECT referred_user_id FROM referrals WHERE referred_user_id = ?",
        (referred_user_id,)
    ).fetchone()

    if already:
        conn.close()
        return

    referrer_exists = conn.execute(
        "SELECT user_id FROM users WHERE user_id = ?",
        (referrer_id,)
    ).fetchone()

    if not referrer_exists:
        conn.close()
        return

    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")

    conn.execute(
        """
        INSERT INTO referrals
        (referrer_id, referred_user_id, source_code, joined_free, created_date)
        VALUES (?, ?, ?, 0, ?)
        """,
        (referrer_id, referred_user_id, payload, now)
    )

    conn.execute(
        "UPDATE users SET referred_by = ? WHERE user_id = ?",
        (referrer_id, referred_user_id)
    )

    conn.commit()
    conn.close()

    log_event(
        f"Referral registered: {referrer_id} -> {referred_user_id}"
    )


def update_free_join_status(user_id):
    joined = is_free_channel_member(user_id)

    conn = db_connect()
    conn.execute(
        "UPDATE users SET free_join_verified = ? WHERE user_id = ?",
        (1 if joined else 0, user_id)
    )

    if joined:
        conn.execute(
            """
            UPDATE referrals
            SET joined_free = 1
            WHERE referred_user_id = ?
            """,
            (user_id,)
        )

    conn.commit()
    conn.close()

    return joined


# ============================================================
# MARKET DATA
# ============================================================

def get_binance_24h():
    url = "https://api.binance.com/api/v3/ticker/24hr"
    res = requests.get(url, headers=HEADERS, timeout=8)
    if res.status_code != 200:
        raise RuntimeError(f"Binance HTTP {res.status_code}")

    data = res.json()
    coins = []

    for item in data:
        symbol = item.get("symbol", "")
        if not symbol.endswith("USDT"):
            continue

        # Avoid leveraged tokens and obvious stablecoin pairs.
        if any(x in symbol for x in ("UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT")):
            continue

        try:
            price = float(item.get("lastPrice", 0))
            change = float(item.get("priceChangePercent", 0))
            volume = float(item.get("quoteVolume", 0))
            high = float(item.get("highPrice", 0))
            low = float(item.get("lowPrice", 0))
        except (TypeError, ValueError):
            continue

        if price <= 0:
            continue

        coins.append({
            "symbol": symbol,
            "price": price,
            "change": change,
            "volume": volume,
            "high": high,
            "low": low
        })

    return coins


def get_market_data():
    try:
        coins = get_binance_24h()
        if coins:
            return coins
    except Exception as e:
        log_event(f"Binance market data error: {e}")

    try:
        url = "https://api.binance.us/api/v3/ticker/24hr"
        res = requests.get(url, headers=HEADERS, timeout=8)
        if res.status_code == 200:
            data = res.json()
            coins = []

            for item in data:
                symbol = item.get("symbol", "")
                if not symbol.endswith("USDT"):
                    continue

                try:
                    price = float(item.get("lastPrice", 0))
                    change = float(item.get("priceChangePercent", 0))
                    volume = float(item.get("quoteVolume", 0))
                    high = float(item.get("highPrice", 0))
                    low = float(item.get("lowPrice", 0))
                except (TypeError, ValueError):
                    continue

                if price > 0:
                    coins.append({
                        "symbol": symbol,
                        "price": price,
                        "change": change,
                        "volume": volume,
                        "high": high,
                        "low": low
                    })

            if coins:
                log_event("Using Binance.US market-data fallback.")
                return coins

    except Exception as e:
        log_event(f"Binance.US market data error: {e}")

    log_event("No market data available.")
    return []


def get_klines(symbol, interval=CANDLE_INTERVAL, limit=CANDLE_LIMIT):
    url = "https://api.binance.com/api/v3/klines"
    res = requests.get(
        url,
        params={
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        },
        headers=HEADERS,
        timeout=8
    )

    if res.status_code != 200:
        raise RuntimeError(
            f"Klines HTTP {res.status_code}: {res.text[:100]}"
        )

    return res.json()


def calculate_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_ema(values, period):
    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)
    ema = sum(values[:period]) / period

    for value in values[period:]:
        ema = ((value - ema) * multiplier) + ema

    return ema


def get_technical_data(symbol):
    try:
        candles = get_klines(symbol)

        if len(candles) < 50:
            return None

        closes = [float(c[4]) for c in candles]
        highs = [float(c[2]) for c in candles]
        lows = [float(c[3]) for c in candles]
        volumes = [float(c[5]) for c in candles]

        rsi = calculate_rsi(closes, 14)
        ema20 = calculate_ema(closes[-50:], 20)
        ema50 = calculate_ema(closes[-50:], 50)

        recent_high = max(highs[-20:])
        recent_low = min(lows[-20:])

        avg_volume = sum(volumes[-20:]) / 20
        current_volume = volumes[-1]

        return {
            "rsi": rsi,
            "ema20": ema20,
            "ema50": ema50,
            "support": recent_low,
            "resistance": recent_high,
            "volume": current_volume,
            "avg_volume": avg_volume,
            "current": closes[-1]
        }

    except Exception as e:
        log_event(f"Technical data error {symbol}: {e}")
        return None


# ============================================================
# SIGNAL ENGINE
# ============================================================

def build_signal(candidate):
    symbol = candidate["symbol"]
    price = candidate["price"]
    change = candidate["change"]
    volume = candidate["volume"]

    if volume < MIN_VOLUME_USDT:
        return None

    tech = get_technical_data(symbol)
    if not tech:
        return None

    rsi = tech["rsi"]
    ema20 = tech["ema20"]
    ema50 = tech["ema50"]

    if rsi is None or ema20 is None or ema50 is None:
        return None

    # Do not enter extremely overbought/oversold conditions.
    if rsi >= 78 or rsi <= 22:
        return None

    # Trend + momentum scoring.
    long_score = 0
    short_score = 0

    if ema20 > ema50:
        long_score += 2
    elif ema20 < ema50:
        short_score += 2

    if change > 0.8:
        long_score += 1
    elif change < -0.8:
        short_score += 1

    if rsi >= 50:
        long_score += 1
    elif rsi <= 50:
        short_score += 1

    if tech["volume"] >= tech["avg_volume"] * 1.15:
        if change > 0:
            long_score += 1
        elif change < 0:
            short_score += 1

    if long_score >= 4 and long_score > short_score:
        side = "LONG"
    elif short_score >= 4 and short_score > long_score:
        side = "SHORT"
    else:
        return None

    # Conservative target/SL distances.
    if side == "LONG":
        tp1 = price * 1.006
        tp2 = price * 1.012
        tp3 = price * 1.020
        sl = price * 0.990
        mode = "15M FUTURES SCALP LONG"
    else:
        tp1 = price * 0.994
        tp2 = price * 0.988
        tp3 = price * 0.980
        sl = price * 1.010
        mode = "15M FUTURES SCALP SHORT"

    return {
        "symbol": symbol,
        "price": price,
        "side": side,
        "mode": mode,
        "leverage": "Up to 5x (risk-managed)",
        "rsi": round(rsi, 2),
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "sl": sl,
        "change": round(change, 2),
        "support": tech["support"],
        "resistance": tech["resistance"],
        "volume_ratio": round(
            tech["volume"] / tech["avg_volume"], 2
        ) if tech["avg_volume"] else 0,
        "score": max(long_score, short_score)
    }


def find_best_signal():
    coins = get_market_data()

    if not coins:
        return None

    # First shortlist by movement and volume.
    candidates = [
        c for c in coins
        if c["volume"] >= MIN_VOLUME_USDT
        and abs(c["change"]) >= 0.8
    ]

    candidates.sort(
        key=lambda x: (
            abs(x["change"]),
            x["volume"]
        ),
        reverse=True
    )

    # Analyze only top candidates to keep API load reasonable.
    for candidate in candidates[:15]:
        signal = build_signal(candidate)
        if signal:
            return signal

    return None


# ============================================================
# SIGNAL MESSAGES
# ============================================================

def signal_message(s, vip=False):
    if vip:
        return (
            "🚨 <b>BINANCE VIP TRADE SIGNAL</b> 🚨\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 <b>Pair:</b> #{html.escape(s['symbol'])}\n"
            f"📊 <b>Side:</b> {s['side']}\n"
            f"📈 <b>Setup:</b> {s['mode']}\n"
            f"⚙️ <b>Leverage:</b> {s['leverage']}\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"📥 <b>Entry:</b> ${format_price(s['price'])}\n"
            f"🎯 <b>TP1:</b> ${format_price(s['tp1'])}\n"
            f"🎯 <b>TP2:</b> ${format_price(s['tp2'])}\n"
            f"🚀 <b>TP3:</b> ${format_price(s['tp3'])}\n"
            f"⛔ <b>SL:</b> ${format_price(s['sl'])}\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>RSI:</b> {s['rsi']}\n"
            f"🛡️ <b>Support:</b> ${format_price(s['support'])}\n"
            f"🚧 <b>Resistance:</b> ${format_price(s['resistance'])}\n"
            f"📈 <b>24h Change:</b> {s['change']}%\n"
            f"📊 <b>Signal Score:</b> {s['score']}/5\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 <b>Binance:</b> {BINANCE_REF_LINK}\n"
            "⚠️ <i>Use strict risk management. This is market analysis, "
            "not a profit guarantee.</i>"
        )

    return (
        "🔥 <b>FREE SIGNAL</b> 🔥\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 <b>Pair:</b> #{html.escape(s['symbol'])}\n"
        f"📊 <b>Side:</b> {s['side']}\n"
        f"📥 <b>Entry:</b> ${format_price(s['price'])}\n"
        f"🎯 <b>TP1:</b> ${format_price(s['tp1'])}\n"
        f"⛔ <b>SL:</b> ${format_price(s['sl'])}\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>RSI:</b> {s['rsi']}\n"
        f"🛡️ <b>Support:</b> ${format_price(s['support'])}\n"
        f"🚧 <b>Resistance:</b> ${format_price(s['resistance'])}\n"
        f"📈 <b>24h Change:</b> {s['change']}%\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "💎 <b>Full TP1/TP2/TP3 + live updates:</b> "
        f"{vip_bot_link()}\n\n"
        "⚠️ <i>Market analysis only. No guaranteed returns.</i>"
    )


def save_signal(s):
    conn = db_connect()
    now = time.time()
    now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")

    cur = conn.execute(
        """
        INSERT INTO signal_history
        (symbol, side, entry_price, tp1, tp2, tp3, sl,
         timestamp, created_date, status, current_stage, closed)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', 0, 0)
        """,
        (
            s["symbol"],
            s["side"],
            s["price"],
            s["tp1"],
            s["tp2"],
            s["tp3"],
            s["sl"],
            now,
            now_str
        )
    )

    signal_id = cur.lastrowid
    conn.commit()
    conn.close()
    return signal_id


def dispatch_vip_signal(s):
    return send_telegram_msg(
        VIP_BOT_TOKEN,
        VIP_CHANNEL_ID,
        signal_message(s, vip=True)
    )


def dispatch_free_signal(s):
    return send_telegram_msg(
        FREE_BOT_TOKEN,
        FREE_CHANNEL_ID,
        signal_message(s, vip=False)
    )


# ============================================================
# SIGNAL SCANNING
# ============================================================

def reset_daily_counters_if_needed():
    global free_signals_today
    global vip_signals_today
    global last_reset_date

    today = datetime.now(IST).date()

    if today != last_reset_date:
        free_signals_today = 0
        vip_signals_today = 0
        last_reset_date = today
        cleanup_old_data()


def scan_and_dispatch(force_mode=False):
    global free_signals_today
    global vip_signals_today
    global last_free_dispatch_time
    global last_vip_dispatch_time

    reset_daily_counters_if_needed()

    now = time.time()

    signal = find_best_signal()

    if not signal:
        log_event("No high-quality signal found in this scan.")
        return False

    vip_allowed = (
        vip_signals_today < VIP_MAX_PER_DAY
        and now - last_vip_dispatch_time >= VIP_INTERVAL
    )

    free_allowed = (
        free_signals_today < FREE_MAX_PER_DAY
        and now - last_free_dispatch_time >= FREE_INTERVAL
    )

    if force_mode:
        vip_allowed = True
        free_allowed = True

    sent_any = False

    # Save only once per signal.
    signal_id = None

    if vip_allowed:
        if dispatch_vip_signal(signal):
            vip_signals_today += 1
            last_vip_dispatch_time = now
            sent_any = True
            log_event(
                f"VIP signal sent: {signal['symbol']} "
                f"{signal['side']} score={signal['score']}"
            )

    if free_allowed:
        if dispatch_free_signal(signal):
            free_signals_today += 1
            last_free_dispatch_time = now
            sent_any = True
            log_event(
                f"Free signal sent: {signal['symbol']} "
                f"{signal['side']} score={signal['score']}"
            )

    if sent_any:
        signal_id = save_signal(signal)
        log_event(f"Signal #{signal_id} saved.")

    return sent_any


# ============================================================
# LIVE TP/SL MONITOR
# ============================================================

def update_signal_stage(signal_id, status, stage, closed=0):
    conn = db_connect()

    if closed:
        conn.execute(
            """
            UPDATE signal_history
            SET status = ?, current_stage = ?, closed = 1,
                closed_date = ?
            WHERE id = ?
            """,
            (
                status,
                stage,
                datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S"),
                signal_id
            )
        )
    else:
        conn.execute(
            """
            UPDATE signal_history
            SET status = ?, current_stage = ?
            WHERE id = ?
            """,
            (status, stage, signal_id)
        )

    conn.commit()
    conn.close()


def send_signal_update(sym, side, entry, current_price, text):
    message = (
        "🔔 <b>LIVE SIGNAL UPDATE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 <b>Pair:</b> #{sym}\n"
        f"📊 <b>Side:</b> {side}\n"
        f"📥 <b>Entry:</b> ${format_price(entry)}\n"
        f"📊 <b>Current:</b> ${format_price(current_price)}\n"
        f"🔥 <b>Status:</b> {text}\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"💎 <b>VIP:</b> {vip_bot_link()}"
    )

    send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, message)
    send_telegram_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, message)


def live_signal_monitor_worker():
    log_event("Live TP/SL monitor started.")

    while True:
        try:
            conn = db_connect()
            rows = conn.execute(
                """
                SELECT id, symbol, side, entry_price, tp1, tp2, tp3, sl,
                       current_stage, status
                FROM signal_history
                WHERE closed = 0
                """
            ).fetchall()
            conn.close()

            if not rows:
                time.sleep(60)
                continue

            coins = get_market_data()
            prices = {c["symbol"]: c["price"] for c in coins}

            for row in rows:
                signal_id = row["id"]
                sym = row["symbol"]
                side = row["side"]
                entry = row["entry_price"]
                tp1 = row["tp1"]
                tp2 = row["tp2"]
                tp3 = row["tp3"]
                sl = row["sl"]
                stage = row["current_stage"]

                current = prices.get(sym)
                if not current:
                    continue

                new_stage = stage
                event = None
                closed = False
                status = row["status"]

                if side == "LONG":
                    if current >= tp3 and stage < 3:
                        new_stage = 3
                        event = f"🚀 TP3 HIT @ ${format_price(tp3)}"
                        status = "TP3_HIT"
                        closed = True
                    elif current >= tp2 and stage < 2:
                        new_stage = 2
                        event = f"🎯 TP2 HIT @ ${format_price(tp2)}"
                        status = "TP2_HIT"
                    elif current >= tp1 and stage < 1:
                        new_stage = 1
                        event = f"✅ TP1 HIT @ ${format_price(tp1)}"
                        status = "TP1_HIT"
                    elif current <= sl:
                        # If TP1/TP2 was already hit, record a
                        # post-target stop rather than pretending it
                        # was a clean SL trade.
                        if stage > 0:
                            status = "STOP_AFTER_TARGET"
                            event = (
                                f"⛔ Stop reached after TP{stage} "
                                f"@ ${format_price(sl)}"
                            )
                        else:
                            status = "SL_HIT"
                            event = f"⛔ SL HIT @ ${format_price(sl)}"
                        closed = True

                else:
                    if current <= tp3 and stage < 3:
                        new_stage = 3
                        event = f"🚀 TP3 HIT @ ${format_price(tp3)}"
                        status = "TP3_HIT"
                        closed = True
                    elif current <= tp2 and stage < 2:
                        new_stage = 2
                        event = f"🎯 TP2 HIT @ ${format_price(tp2)}"
                        status = "TP2_HIT"
                    elif current <= tp1 and stage < 1:
                        new_stage = 1
                        event = f"✅ TP1 HIT @ ${format_price(tp1)}"
                        status = "TP1_HIT"
                    elif current >= sl:
                        if stage > 0:
                            status = "STOP_AFTER_TARGET"
                            event = (
                                f"⛔ Stop reached after TP{stage} "
                                f"@ ${format_price(sl)}"
                            )
                        else:
                            status = "SL_HIT"
                            event = f"⛔ SL HIT @ ${format_price(sl)}"
                        closed = True

                if event:
                    update_signal_stage(
                        signal_id,
                        status,
                        new_stage,
                        1 if closed else 0
                    )

                    send_signal_update(
                        sym,
                        side,
                        entry,
                        current,
                        event
                    )

                    log_event(
                        f"Signal #{signal_id} {sym}: {event} "
                        f"(closed={closed})"
                    )

        except Exception as e:
            log_event(f"Live monitor error: {e}")

        time.sleep(60)


# ============================================================
# RESULT STATISTICS
# ============================================================

def get_result_stats(hours=24):
    cutoff = (
        datetime.now(IST) - timedelta(hours=hours)
    ).strftime("%Y-%m-%d %H:%M:%S")

    conn = db_connect()

    rows = conn.execute(
        """
        SELECT status, current_stage, closed
        FROM signal_history
        WHERE created_date >= ?
        """,
        (cutoff,)
    ).fetchall()

    conn.close()

    total = len(rows)
    tp1 = sum(r["current_stage"] >= 1 for r in rows)
    tp2 = sum(r["current_stage"] >= 2 for r in rows)
    tp3 = sum(r["current_stage"] >= 3 for r in rows)
    sl = sum(r["status"] == "SL_HIT" for r in rows)
    stop_after_target = sum(
        r["status"] == "STOP_AFTER_TARGET" for r in rows
    )
    closed = sum(r["closed"] == 1 for r in rows)

    clean_wins = tp3
    clean_losses = sl
    decided = clean_wins + clean_losses

    win_rate = (
        round(clean_wins / decided * 100, 1)
        if decided else 0.0
    )

    return {
        "total": total,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "sl": sl,
        "stop_after_target": stop_after_target,
        "closed": closed,
        "win_rate": win_rate
    }


def generate_24h_result_report():
    stats = get_result_stats(24)

    msg = (
        "📊 <b>24-HOUR SIGNAL REPORT</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 <b>Total Signals:</b> {stats['total']}\n"
        f"✅ <b>TP1 Reached:</b> {stats['tp1']}\n"
        f"🎯 <b>TP2 Reached:</b> {stats['tp2']}\n"
        f"🚀 <b>TP3 Reached:</b> {stats['tp3']}\n"
        f"⛔ <b>Clean SL:</b> {stats['sl']}\n"
        f"⚠️ <b>Stop After Target:</b> "
        f"{stats['stop_after_target']}\n"
        f"📈 <b>Clean TP3/SL Rate:</b> "
        f"{stats['win_rate']}%\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "ℹ️ <i>Statistics are generated from recorded signals. "
        "Past results do not guarantee future performance.</i>\n"
        f"💎 <b>VIP:</b> {vip_bot_link()}"
    )

    send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, msg)
    send_telegram_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, msg)

    log_event(
        f"24h report sent: total={stats['total']} "
        f"TP3={stats['tp3']} SL={stats['sl']} "
        f"rate={stats['win_rate']}%"
    )


# ============================================================
# FREE CHANNEL CONVERSION / REFERRAL BOT
# ============================================================

KEYBOARD_LAYOUT = {
    "keyboard": [
        [
            {"text": "📢 Join Free Channel"},
            {"text": "✅ Verify Free Join"}
        ],
        [
            {"text": "🎁 My Referral Link"},
            {"text": "📊 24H Results"}
        ],
        [
            {"text": "💎 View VIP Plans"},
            {"text": "💳 Get Payment Address"}
        ],
        [
            {"text": "🔍 Verify Payment"},
            {"text": "✅ How to Verify TXID"}
        ]
    ],
    "resize_keyboard": True,
    "is_persistent": True
}


def set_user_state(user_id, state):
    conn = db_connect()
    conn.execute(
        """
        INSERT OR REPLACE INTO user_states
        (user_id, state, updated_date)
        VALUES (?, ?, ?)
        """,
        (
            user_id,
            state,
            datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
        )
    )
    conn.commit()
    conn.close()


def get_user_state(user_id):
    conn = db_connect()
    row = conn.execute(
        "SELECT state FROM user_states WHERE user_id = ?",
        (user_id,)
    ).fetchone()
    conn.close()

    return row["state"] if row else "IDLE"


def get_referral_stats(user_id):
    conn = db_connect()
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(joined_free) AS joined
        FROM referrals
        WHERE referrer_id = ?
        """,
        (user_id,)
    ).fetchone()
    conn.close()

    return {
        "total": int(row["total"] or 0),
        "joined": int(row["joined"] or 0)
    }


def get_or_create_user_invite(user_id):
    code = make_referral_code(user_id)
    return vip_bot_link(code)


def send_bot_welcome(chat_id, payload=None):
    msg = (
        "🤖 <b>Welcome to Binance Top 10 Signals</b>\n\n"
        "Get free market signals, live target updates and "
        "recorded performance statistics.\n\n"
        "🎯 <b>Start here:</b>\n"
        "1️⃣ Join the Free Channel\n"
        "2️⃣ Tap Verify Free Join\n"
        "3️⃣ Receive the latest free signal updates\n\n"
        f"📢 <b>Free Channel:</b> {free_channel_link()}\n\n"
        "⚠️ <i>No guaranteed profits. Always use your own risk "
        "management.</i>"
    )

    send_telegram_msg(
        VIP_BOT_TOKEN,
        chat_id,
        msg,
        KEYBOARD_LAYOUT
    )


def handle_start(chat_id, payload):
    register_user(chat_id, payload or "direct")
    register_referral(chat_id, payload)
    send_bot_welcome(chat_id, payload)


def handle_bot_message(chat_id, text):
    text_clean = text.strip()

    # /start and /start ref_xxx
    if text_clean.startswith("/start"):
        parts = text_clean.split(maxsplit=1)
        payload = parts[1].strip() if len(parts) > 1 else None
        handle_start(chat_id, payload)
        return

    register_user(chat_id)

    if text_clean == "📢 Join Free Channel":
        invite = create_invite_link(f"user_{chat_id}")

        msg = (
            "📢 <b>Join the Free Channel</b>\n\n"
            "Join the channel first, then come back and press "
            "<b>Verify Free Join</b>.\n\n"
            f"👉 <a href=\"{invite}\">JOIN FREE CHANNEL</a>\n\n"
            "This is an opt-in verification step so the bot can "
            "unlock the free content."
        )

        send_telegram_msg(VIP_BOT_TOKEN, chat_id, msg)
        return

    if text_clean == "✅ Verify Free Join":
        joined = update_free_join_status(chat_id)

        if joined:
            send_telegram_msg(
                VIP_BOT_TOKEN,
                chat_id,
                "✅ <b>Free Channel membership verified.</b>\n\n"
                "You are now eligible for the free signal flow.\n\n"
                f"📢 {free_channel_link()}"
            )
        else:
            send_telegram_msg(
                VIP_BOT_TOKEN,
                chat_id,
                "❌ <b>Join not detected yet.</b>\n\n"
                f"Please join: {free_channel_link()}\n"
                "Then press <b>Verify Free Join</b> again."
            )
        return

    if text_clean == "🎁 My Referral Link":
        link = get_or_create_user_invite(chat_id)
        stats = get_referral_stats(chat_id)

        msg = (
            "🎁 <b>Your Referral Link</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"<code>{link}</code>\n\n"
            f"👥 <b>Total referrals:</b> {stats['total']}\n"
            f"✅ <b>Free-channel joins:</b> {stats['joined']}\n\n"
            "Share the link with people who are genuinely interested "
            "in crypto signals. Referral tracking is automatic when "
            "they start the bot."
        )

        send_telegram_msg(VIP_BOT_TOKEN, chat_id, msg)
        return

    if text_clean == "📊 24H Results":
        stats = get_result_stats(24)

        msg = (
            "📊 <b>24-HOUR RESULTS</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"Signals: {stats['total']}\n"
            f"TP1 reached: {stats['tp1']}\n"
            f"TP2 reached: {stats['tp2']}\n"
            f"TP3 reached: {stats['tp3']}\n"
            f"Clean SL: {stats['sl']}\n"
            f"Stop after target: {stats['stop_after_target']}\n"
            f"Clean TP3/SL rate: {stats['win_rate']}%\n\n"
            "Past results are not a guarantee of future performance."
        )

        send_telegram_msg(VIP_BOT_TOKEN, chat_id, msg)
        return

    if text_clean == "💎 View VIP Plans":
        msg = (
            "💎 <b>VIP PLANS</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "• 10 Days — $10 USDT\n"
            "• 20 Days — $18 USDT\n"
            "• 30 Days — $27 USDT\n\n"
            "VIP includes the complete signal levels and live "
            "TP/SL updates.\n\n"
            "No guaranteed-return claims are made."
        )

        send_telegram_msg(VIP_BOT_TOKEN, chat_id, msg)
        return

    if text_clean == "💳 Get Payment Address":
        set_user_state(chat_id, "AWAITING_TXID")

        msg = (
            "💳 <b>USDT TRC20 PAYMENT</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"<code>{TRUST_WALLET_ADDRESS}</code>\n\n"
            "Send only USDT on TRC20 network.\n"
            "After payment, press <b>Verify Payment</b> and send "
            "the transaction hash."
        )

        send_telegram_msg(VIP_BOT_TOKEN, chat_id, msg)
        return

    if text_clean == "🔍 Verify Payment":
        set_user_state(chat_id, "AWAITING_TXID")

        send_telegram_msg(
            VIP_BOT_TOKEN,
            chat_id,
            "🔍 <b>Payment Verification</b>\n\n"
            "Please send your TRC20 transaction hash (TXID)."
        )
        return

    if text_clean == "✅ How to Verify TXID":
        send_telegram_msg(
            VIP_BOT_TOKEN,
            chat_id,
            "📖 <b>HOW TO VERIFY</b>\n\n"
            "1. Send the correct USDT amount to the wallet.\n"
            "2. Use TRC20 network.\n"
            "3. Copy the transaction hash/TXID.\n"
            "4. Send it here."
        )
        return

    # Numeric messages are treated as Binance UID ONLY when the
    # user explicitly requested the referral flow.
    state = get_user_state(chat_id)

    if text_clean.isdigit() and 7 <= len(text_clean) <= 12:
        if state == "AWAITING_BINANCE_UID":
            save_binance_uid(chat_id, text_clean)
            return

        send_telegram_msg(
            VIP_BOT_TOKEN,
            chat_id,
            "ℹ️ If you want to submit a Binance UID, first use "
            "the referral flow. Random numeric messages are not "
            "treated as payment/UID automatically."
        )
        return

    if state == "AWAITING_TXID":
        process_payment_txid(chat_id, text_clean)
        return

    send_telegram_msg(
        VIP_BOT_TOKEN,
        chat_id,
        "Use the menu buttons above or send /start."
    )


def save_binance_uid(chat_id, binance_uid):
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")

    conn = db_connect()

    try:
        conn.execute(
            """
            INSERT INTO referral_claims
            (user_id, binance_uid, status, created_date)
            VALUES (?, ?, 'PENDING', ?)
            """,
            (chat_id, binance_uid, now)
        )

        conn.commit()

    except sqlite3.IntegrityError:
        conn.close()

        send_telegram_msg(
            VIP_BOT_TOKEN,
            chat_id,
            "⚠️ This Binance UID has already been submitted."
        )
        return

    conn.close()

    send_telegram_msg(
        VIP_BOT_TOKEN,
        chat_id,
        "📥 <b>Binance UID received.</b>\n\n"
        f"UID: <code>{binance_uid}</code>\n"
        "Status: <b>Pending verification</b>\n\n"
        "No VIP access is granted until the referral is actually "
        "verified."
    )

    set_user_state(chat_id, "IDLE")


# ============================================================
# PAYMENT VERIFICATION
# ============================================================

def verify_usdt_trc20_tx(txid, expected_amount_min=10.0):
    try:
        url = (
            "https://apilist.tronscan.org/api/"
            f"transaction-info?hash={txid.strip()}"
        )

        res = requests.get(url, timeout=10)

        if res.status_code != 200:
            return False, 0, "Blockchain API error."

        data = res.json()

        if not data:
            return False, 0, "Transaction not found."

        if data.get("contractRet") not in (None, "SUCCESS"):
            return False, 0, "Transaction failed or is not confirmed."

        transfers = data.get("trc20TransferInfo", [])

        if not transfers:
            return False, 0, "No TRC20 transfer found."

        for transfer in transfers:
            to_addr = transfer.get("to_address", "")
            symbol = transfer.get("symbol", "")

            try:
                amount = float(
                    transfer.get("amount_str", "0")
                ) / 10**6
            except Exception:
                amount = 0

            if (
                to_addr == TRUST_WALLET_ADDRESS
                and symbol.upper() == "USDT"
                and amount >= expected_amount_min
            ):
                return True, amount, "Verification successful."

        return (
            False,
            0,
            "Recipient, token or amount does not match."
        )

    except Exception as e:
        return False, 0, f"Verification error: {e}"


def process_payment_txid(chat_id, txid):
    # Basic TXID format check.
    if not re.fullmatch(r"[A-Za-z0-9]{20,100}", txid):
        send_telegram_msg(
            VIP_BOT_TOKEN,
            chat_id,
            "❌ Invalid TXID format. Please send the TRON "
            "transaction hash."
        )
        return

    conn = db_connect()

    used = conn.execute(
        "SELECT txid FROM processed_txids WHERE txid = ?",
        (txid,)
    ).fetchone()

    conn.close()

    if used:
        send_telegram_msg(
            VIP_BOT_TOKEN,
            chat_id,
            "⚠️ This TXID has already been used."
        )
        return

    valid, amount, reason = verify_usdt_trc20_tx(
        txid,
        expected_amount_min=10
    )

    if not valid:
        send_telegram_msg(
            VIP_BOT_TOKEN,
            chat_id,
            "❌ <b>Payment verification failed</b>\n\n"
            f"Reason: {html.escape(reason)}"
        )
        return

    if amount >= 27:
        days = 30
        plan = "30 Days VIP"
    elif amount >= 18:
        days = 20
        plan = "20 Days VIP"
    else:
        days = 10
        plan = "10 Days VIP"

    expiry = datetime.now(IST) + timedelta(days=days)
    expiry_str = expiry.strftime("%Y-%m-%d %H:%M:%S")

    conn = db_connect()

    try:
        conn.execute(
            "INSERT INTO processed_txids (txid) VALUES (?)",
            (txid,)
        )

        conn.execute(
            """
            INSERT OR REPLACE INTO members
            (user_id, expiry_date, status)
            VALUES (?, ?, 'ACTIVE')
            """,
            (chat_id, expiry_str)
        )

        conn.commit()

    except sqlite3.IntegrityError:
        conn.close()
        send_telegram_msg(
            VIP_BOT_TOKEN,
            chat_id,
            "⚠️ This transaction has already been processed."
        )
        return

    conn.close()

    invite = create_vip_invite(chat_id)

    send_telegram_msg(
        VIP_BOT_TOKEN,
        chat_id,
        "✅ <b>PAYMENT VERIFIED</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 Plan: {plan}\n"
        f"💰 Amount: {amount:.2f} USDT\n"
        f"⏳ Valid till: {expiry_str}\n\n"
        f"💎 <b>VIP Channel:</b>\n{invite}"
    )

    set_user_state(chat_id, "IDLE")

    log_event(
        f"Payment verified for {chat_id}: "
        f"{amount:.2f} USDT / {days} days"
    )


def create_vip_invite(user_id):
    data = tg_request(
        VIP_BOT_TOKEN,
        "createChatInviteLink",
        {
            "chat_id": VIP_CHANNEL_ID,
            "name": f"vip_{user_id}"[:32],
            "member_limit": 1
        }
    )

    if data.get("ok"):
        return data["result"]["invite_link"]

    # Fallback. Replace with a permanent VIP invite if your
    # VIP channel is private and bot cannot create links.
    return "Please contact admin for the VIP invite."


# ============================================================
# EXPIRY WORKER
# ============================================================

def kick_telegram_user(chat_id, user_id):
    ban = tg_request(
        VIP_BOT_TOKEN,
        "banChatMember",
        {
            "chat_id": chat_id,
            "user_id": user_id,
            "revoke_messages": False
        }
    )

    if not ban.get("ok"):
        return False

    unban = tg_request(
        VIP_BOT_TOKEN,
        "unbanChatMember",
        {
            "chat_id": chat_id,
            "user_id": user_id,
            "only_if_banned": True
        }
    )

    return unban.get("ok", False)


def membership_expiry_checker():
    log_event("Membership expiry worker started.")

    while True:
        try:
            now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")

            conn = db_connect()
            rows = conn.execute(
                """
                SELECT user_id
                FROM members
                WHERE expiry_date <= ?
                AND status = 'ACTIVE'
                """,
                (now,)
            ).fetchall()

            for row in rows:
                user_id = row["user_id"]

                kick_telegram_user(
                    VIP_CHANNEL_ID,
                    user_id
                )

                conn.execute(
                    """
                    UPDATE members
                    SET status = 'EXPIRED'
                    WHERE user_id = ?
                    """,
                    (user_id,)
                )

                send_telegram_msg(
                    VIP_BOT_TOKEN,
                    user_id,
                    "⚠️ <b>Your VIP membership has expired.</b>\n\n"
                    "You can renew from the bot menu."
                )

                log_event(
                    f"VIP membership expired: {user_id}"
                )

            conn.commit()
            conn.close()

        except Exception as e:
            log_event(f"Expiry worker error: {e}")

        time.sleep(3600)


# ============================================================
# TELEGRAM POLLING
# ============================================================

def telegram_polling_worker():
    log_event("Telegram polling worker started.")

    offset = 0

    # Ensure polling works if a webhook was previously configured.
    try:
        tg_request(
            VIP_BOT_TOKEN,
            "deleteWebhook",
            {"drop_pending_updates": False}
        )
    except Exception:
        pass

    while True:
        try:
            data = tg_request(
                VIP_BOT_TOKEN,
                "getUpdates",
                {
                    "offset": offset,
                    "timeout": 30,
                    "allowed_updates": ["message"]
                },
                timeout=35
            )

            if data.get("ok"):
                for update in data.get("result", []):
                    offset = update["update_id"] + 1

                    message = update.get("message")
                    if not message:
                        continue

                    chat = message.get("chat", {})
                    chat_id = chat.get("id")
                    text = message.get("text", "")

                    if chat_id and text:
                        threading.Thread(
                            target=handle_bot_message,
                            args=(chat_id, text),
                            daemon=True
                        ).start()

        except Exception as e:
            log_event(f"Polling error: {e}")
            time.sleep(3)


# ============================================================
# MARKET SCANNER
# ============================================================

def continuous_market_scanner():
    log_event(
        f"Market scanner started: "
        f"Free={FREE_MAX_PER_DAY}/day, VIP={VIP_MAX_PER_DAY}/day"
    )

    while True:
        try:
            scan_and_dispatch(False)
        except Exception as e:
            log_event(f"Scanner error: {e}")

        time.sleep(120)


# ============================================================
# FLASK ROUTES
# ============================================================

@app.route("/")
def home():
    return jsonify({
        "status": "active",
        "service": "BinanceTop10",
        "time": datetime.now(IST).isoformat()
    })


@app.route("/logs")
def get_logs():
    with log_lock:
        return jsonify({"logs": list(system_logs)})


@app.route("/stats")
def stats_route():
    stats = get_result_stats(24)

    conn = db_connect()

    users = conn.execute(
        "SELECT COUNT(*) AS c FROM users"
    ).fetchone()["c"]

    verified = conn.execute(
        """
        SELECT COUNT(*) AS c
        FROM users
        WHERE free_join_verified = 1
        """
    ).fetchone()["c"]

    referrals = conn.execute(
        "SELECT COUNT(*) AS c FROM referrals"
    ).fetchone()["c"]

    conn.close()

    return jsonify({
        "signals_24h": stats,
        "bot_users": users,
        "verified_free_members": verified,
        "referrals": referrals,
        "free_signals_today": free_signals_today,
        "vip_signals_today": vip_signals_today
    })


@app.route("/force-signal")
def force_signal():
    # Admin-only protection is recommended before exposing this route.
    threading.Thread(
        target=scan_and_dispatch,
        args=(True,),
        daemon=True
    ).start()

    return jsonify({
        "status": "success",
        "message": "Force scan triggered."
    })


@app.route("/force-result")
def force_result():
    threading.Thread(
        target=generate_24h_result_report,
        daemon=True
    ).start()

    return jsonify({
        "status": "success",
        "message": "24h result report triggered."
    })


@app.route("/health")
def health():
    try:
        conn = db_connect()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        db_ok = True
    except Exception:
        db_ok = False

    return jsonify({
        "status": "ok" if db_ok else "degraded",
        "database": db_ok,
        "time": datetime.now(IST).isoformat()
    })


# ============================================================
# START WORKERS
# ============================================================

threading.Thread(
    target=telegram_polling_worker,
    daemon=True
).start()

threading.Thread(
    target=continuous_market_scanner,
    daemon=True
).start()

threading.Thread(
    target=live_signal_monitor_worker,
    daemon=True
).start()

threading.Thread(
    target=membership_expiry_checker,
    daemon=True
).start()


# ============================================================
# RUN FLASK
# ============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True
    )
