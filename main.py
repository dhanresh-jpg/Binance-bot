import threading
import time
import random
import requests
import sqlite3
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify

# Bot Credentials
BOT_TOKEN = "8997353064:AAGqtm4nFQihOzwgIUuWWXRHagTAt8Itq4w"
VIP_CHANNEL_ID = "-1003836756507"
FREE_CHANNEL_ID = "-1003924921868"

# Trust Wallet TRON Address (USDT TRC-20)
TRON_WALLET_ADDRESS = "TErttGLUQZtrCwusaQsjdywXdkxUrNFm52"
USDT_TRC20_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

app = Flask(__name__)
IST = timezone(timedelta(hours=5, minutes=30))

# Plan Mapping
PLANS = {
    "plan_10": {"days": 10, "price": 10.0, "name": "10 Days VIP Access"},
    "plan_20": {"days": 20, "price": 19.0, "name": "20 Days VIP Access"},
    "plan_30": {"days": 30, "price": 27.0, "name": "30 Days VIP Access"}
}

# --- Database Setup ---
def init_db():
    conn = sqlite3.connect("vip_members.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS members (
            user_id INTEGER PRIMARY KEY,
            tx_hash TEXT,
            expiry_date TEXT,
            status TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending_payments (
            user_id INTEGER,
            plan_key TEXT,
            amount REAL,
            timestamp INTEGER
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def add_vip_member(user_id, tx_hash, days):
    conn = sqlite3.connect("vip_members.db")
    cursor = conn.cursor()
    expiry = datetime.now(IST) + timedelta(days=days)
    expiry_str = expiry.strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute('''
        INSERT OR REPLACE INTO members (user_id, tx_hash, expiry_date, status)
        VALUES (?, ?, ?, 'ACTIVE')
    ''', (user_id, tx_hash, expiry_str))
    conn.commit()
    conn.close()
    return expiry_str

# --- Telegram API Helpers ---
def send_telegram_msg(chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        res = requests.post(url, json=payload, timeout=10)
        return res.json()
    except Exception as e:
        return {"ok": False, "description": str(e)}

def create_single_use_invite_link():
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/createChatInviteLink"
    payload = {
        "chat_id": VIP_CHANNEL_ID,
        "member_limit": 1,
        "expire_date": int(time.time()) + 86400  # Link valid for 24 hours
    }
    try:
        res = requests.post(url, json=payload, timeout=10).json()
        if res.get("ok"):
            return res["result"]["invite_link"]
    except Exception:
        pass
    return None

def kick_expired_member(user_id):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/banChatMember"
    payload = {"chat_id": VIP_CHANNEL_ID, "user_id": user_id}
    requests.post(url, json=payload, timeout=10)
    # Unban immediately so user can re-join after paying again
    unban_url = f"https://api.telegram.org/bot{BOT_TOKEN}/unbanChatMember"
    requests.post(unban_url, json=payload, timeout=10)

# --- TRON Blockchain Verification ---
def verify_blockchain_payment():
    """Monitors Trust Wallet TRON address for incoming USDT-TRC20 payments"""
    conn = sqlite3.connect("vip_members.db")
    cursor = conn.cursor()
    
    # Get pending payments
    cursor.execute("SELECT user_id, plan_key, amount, timestamp FROM pending_payments")
    pending = cursor.fetchall()
    
    if not pending:
        conn.close()
        return

    try:
        url = f"https://api.tronscan.org/api/token_trc20/transfers?limit=20&start=0&contract_address={USDT_TRC20_CONTRACT}&toAddress={TRON_WALLET_ADDRESS}"
        res = requests.get(url, timeout=10).json()
        transfers = res.get("token_transfers", [])

        for user_id, plan_key, required_amount, req_time in pending:
            for tx in transfers:
                tx_amount = float(tx.get("quant", 0)) / 1_000_000 # USDT decimals = 6
                tx_time = int(tx.get("block_timestamp", 0)) / 1000
                tx_hash = tx.get("transaction_id")

                # Match payment amount & verify it occurred after user pressed Buy
                if abs(tx_amount - required_amount) < 0.1 and tx_time >= (req_time - 120):
                    days = PLANS[plan_key]["days"]
                    expiry_str = add_vip_member(user_id, tx_hash, days)
                    invite_link = create_single_use_invite_link()

                    # Remove from pending table
                    cursor.execute("DELETE FROM pending_payments WHERE user_id = ?", (user_id,))
                    conn.commit()

                    success_text = (
                        f"✅ <b>PAYMENT CONFIRMED ON BLOCKCHAIN!</b>\n\n"
                        f"💳 <b>Amount Received</b>: ${tx_amount:.2f} USDT\n"
                        f"🔗 <b>Tx Hash</b>: <code>{tx_hash[:10]}...{tx_hash[-6:]}</code>\n"
                        f"📅 <b>Expiry Date</b>: {expiry_str} IST\n\n"
                        f"👉 <b>Join VIP Channel Now</b>: {invite_link}\n\n"
                        f"<i>Note: This invite link is valid for 1 join only.</i>"
                    )
                    send_telegram_msg(user_id, success_text)
                    break
    except Exception:
        pass
    
    conn.close()

def auto_payment_checker_loop():
    while True:
        verify_blockchain_payment()
        time.sleep(20) # Check blockchain every 20 seconds

threading.Thread(target=auto_payment_checker_loop, daemon=True).start()

# --- Webhooks & Bot Handlers ---
@app.route('/')
def home():
    return "Automated TRON USDT VIP Subscription Bot Active!"

@app.route('/telegram_webhook', methods=['POST'])
def telegram_webhook():
    data = request.get_json()
    
    # Handle /start Command
    if "message" in data and "text" in data["message"]:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"]["text"]
        
        if text.startswith("/start"):
            welcome_text = (
                "🚀 <b>Welcome to Binance Top 10 VIP Signals</b>\n\n"
                "Get 24/7 High-Accuracy Spot & Futures Signals backed by real-time RSI/SMA technical analysis.\n\n"
                "💳 <b>Select a VIP Plan to subscribe automatically</b>:"
            )
            keyboard = {
                "inline_keyboard": [
                    [{"text": "10 Days VIP - $10 USDT", "callback_data": "buy_plan_10"}],
                    [{"text": "20 Days VIP - $19 USDT", "callback_data": "buy_plan_20"}],
                    [{"text": "30 Days VIP - $27 USDT", "callback_data": "buy_plan_30"}]
                ]
            }
            send_telegram_msg(chat_id, welcome_text, reply_markup=keyboard)

    # Handle Plan Selection Clicks
    if "callback_query" in data:
        query = data["callback_query"]
        user_id = query["from"]["id"]
        cb_data = query["data"]

        if cb_data.startswith("buy_"):
            plan_key = cb_data.replace("buy_", "")
            plan = PLANS[plan_key]

            # Store in pending payments table
            conn = sqlite3.connect("vip_members.db")
            cursor = conn.cursor()
            cursor.execute("DELETE FROM pending_payments WHERE user_id = ?", (user_id,))
            cursor.execute("INSERT INTO pending_payments VALUES (?, ?, ?, ?)", 
                           (user_id, plan_key, plan["price"], int(time.time())))
            conn.commit()
            conn.close()

            pay_text = (
                f"💳 <b>AUTOMATED PAYMENT INSTRUCTIONS</b>\n\n"
                f"<b>Selected Plan</b>: {plan['name']}\n"
                f"<b>Exact Amount to Send</b>: <code>{plan['price']}</code> USDT (TRC-20)\n\n"
                f"📍 <b>Send Payment To Address</b>:\n"
                f"<code>{TRON_WALLET_ADDRESS}</code>\n\n"
                f"⚠️ <i>Please send the exact amount on the TRON (TRC-20) network. "
                f"As soon as the transaction is confirmed on the blockchain (approx 1-2 minutes), "
                f"the bot will automatically deliver your instant VIP invite link!</i>"
            )
            send_telegram_msg(user_id, pay_text)

    return jsonify({"status": "ok"})

# --- Expiry Check ---
def expiry_checker_loop():
    while True:
        try:
            conn = sqlite3.connect("vip_members.db")
            cursor = conn.cursor()
            now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
            
            cursor.execute("SELECT user_id FROM members WHERE expiry_date <= ? AND status = 'ACTIVE'", (now_str,))
            expired_users = cursor.fetchall()

            for row in expired_users:
                uid = row[0]
                kick_expired_member(uid)
                cursor.execute("UPDATE members SET status = 'EXPIRED' WHERE user_id = ?", (uid,))
                conn.commit()
                send_telegram_msg(uid, "❌ <b>Your VIP Subscription has expired.</b>\nSend /start to renew your plan.")

            conn.close()
        except Exception:
            pass
        time.sleep(3600)

threading.Thread(target=expiry_checker_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
