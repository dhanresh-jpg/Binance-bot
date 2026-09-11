import threading
import time
import random
import requests
import sqlite3
import os
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify

# --- CONFIGURATION ---
BOT_TOKEN = "8997353064:AAGqtm4nFQihOzwgIUuWWXRHagTAt8Itq4w"
VIP_CHANNEL_ID = "-1003836756507"
FREE_CHANNEL_ID = "-1003924921868"
TRUST_WALLET_ADDRESS = "TErttGLUQZtrCwusaQsjdywXdkxUrNFm52"

app = Flask(__name__)
IST = timezone(timedelta(hours=5, minutes=30))

PLANS = {
    "plan_10": {"days": 10, "price": 10.0, "name": "10 Days VIP Access"},
    "plan_20": {"days": 20, "price": 19.0, "name": "20 Days VIP Access"},
    "plan_30": {"days": 30, "price": 27.0, "name": "30 Days VIP Access"}
}

pending_payments = {}

@app.route('/')
def home():
    return "Binance VIP Bot Server Active & Running!"

@app.route('/telegram_webhook', methods=['POST', 'GET'])
def telegram_webhook():
    if request.method == 'GET':
        return "Webhook Endpoint Ready!", 200

    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"status": "no data"}), 200

    if "message" in data and "text" in data["message"]:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"]["text"]
        
        if text.startswith("/start"):
            welcome_text = (
                "🚀 <b>Welcome to Binance Top 10 VIP Signals Bot</b>\n\n"
                "Get 24/7 High-Accuracy Spot & Futures Signals.\n\n"
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

    if "callback_query" in data:
        query = data["callback_query"]
        user_id = query["from"]["id"]
        cb_data = query["data"]

        if cb_data.startswith("buy_"):
            plan_key = cb_data.replace("buy_", "")
            plan = PLANS[plan_key]
            
            pending_payments[user_id] = {
                "amount": plan["price"],
                "days": plan["days"],
                "timestamp": time.time(),
                "plan": plan["name"]
            }

            pay_text = (
                f"💳 <b>Payment Invoice ({plan['name']})</b>\n\n"
                f"<b>Amount</b>: <code>{plan['price']}</code> USDT\n"
                f"<b>Network</b>: TRC20 (TRON)\n\n"
                f"📍 <b>Deposit Address</b>:\n"
                f"<code>{TRUST_WALLET_ADDRESS}</code>\n\n"
                f"⚠️ <i>Send the exact amount. After payment, click below to verify.</i>"
            )
            keyboard = {"inline_keyboard": [[{"text": "🔄 Check My Payment", "callback_data": "check_payment"}]]}
            send_telegram_msg(user_id, pay_text, reply_markup=keyboard)

    return jsonify({"status": "ok"}), 200

def send_telegram_msg(chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception:
        pass

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
