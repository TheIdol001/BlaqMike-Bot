#!/usr/bin/env python3
"""
IQ Option Telegram Bot v5 - Improved Connection Version
- Better timeout handling for IQ Option login
- Clearer error messages
"""

import sys
import asyncio
import os
import threading
import time
import json
import websocket
import pandas as pd
from http.server import HTTPServer, BaseHTTPRequestHandler

# ====================== RENDER FIXES ======================
if sys.platform != "win32":
    try:
        asyncio.set_event_loop(asyncio.new_event_loop())
    except RuntimeError:
        pass

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)

# ==================== DUMMY PORT ====================
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot running")

def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('', port), DummyHandler)
    server.serve_forever()

threading.Thread(target=run_dummy_server, daemon=True).start()
# ============================================================

class IQOption:
    def __init__(self, email, password, account_type="demo"):
        self.email = email
        self.password = password
        self.account_type = account_type.lower()
        self.ws = None
        self.connected = False
        self.balance = 0
        self.candles_data = {}

        self.active_ids = {
            "EUR/USD OTC": 76, "GBP/USD OTC": 77, "AUD/USD OTC": 78,
            "USD/JPY OTC": 79, "XAU/USD OTC": 74, "NZD/USD OTC": 80,
            "USD/CAD OTC": 81
        }

    def connect(self):
        print("[*] Connecting to IQ Option WebSocket...")
        self.ws = websocket.WebSocketApp(
            "wss://iqoption.com/echo/websocket",
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close
        )
        wst = threading.Thread(target=self.ws.run_forever)
        wst.daemon = True
        wst.start()
        time.sleep(15)  # Increased timeout for better reliability

    def on_open(self, ws):
        print("[+] WebSocket connected. Sending login...")
        self.login()

    def login(self):
        login_msg = {"name": "ssid", "msg": {"email": self.email, "password": self.password}}
        self.ws.send(json.dumps(login_msg))

    def on_message(self, ws, message):
        try:
            data = json.loads(message)
        except:
            return

        if data.get("name") == "ssid" and data.get("msg"):
            print("[+] Login successful. Switching to Demo account...")
            self.connected = True
            self.change_account_type()

        elif data.get("name") == "get_balances" and data.get("msg"):
            for balance in data["msg"]:
                if balance.get("type") == 1:  # Demo
                    self.balance = balance.get("amount", 0)
                    print(f"[+] Balance fetched: ${self.balance}")

        elif data.get("name") == "candles":
            active_id = str(data.get("msg", {}).get("active_id"))
            self.candles_data[active_id] = data.get("msg", {}).get("candles", [])

    def change_account_type(self):
        balance_type = 1 if self.account_type == "demo" else 0
        self.ws.send(json.dumps({"name": "change_balance", "msg": balance_type}))
        time.sleep(3)
        self.get_balance()

    def get_balance(self):
        self.ws.send(json.dumps({"name": "get_balances", "msg": {}}))

    def get_candles(self, pair, timeframe=60, count=80):
        active_id = self.active_ids.get(pair)
        if not active_id:
            return None

        to_time = int(time.time())
        from_time = to_time - (count * timeframe)

        msg = {
            "name": "get_candles",
            "msg": {
                "active_id": active_id,
                "size": timeframe,
                "from": from_time,
                "to": to_time,
                "count": count
            }
        }
        self.ws.send(json.dumps(msg))
        time.sleep(4)

        if str(active_id) in self.candles_data:
            candles = self.candles_data[str(active_id)]
            df = pd.DataFrame(candles)
            df = df.rename(columns={'open': 'open', 'max': 'high', 'min': 'low', 'close': 'close'})
            return df[['open', 'high', 'low', 'close']]
        return None

    def on_error(self, ws, error):
        print(f"[IQ ERROR] {error}")

    def on_close(self, ws, close_status_code, close_msg):
        print("[-] IQ Option connection closed")
        self.connected = False


# ==================== GLOBAL STATE ====================
user_data = {}
user_iq = {}

# ==================== HIGH PROBABILITY SIGNAL ====================
def generate_high_probability_signal(df):
    if df is None or len(df) < 50:
        return None

    df = df.copy()
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))

    df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['ema21'] = df['close'].ewm(span=21, adjust=False).mean()

    latest = df.iloc[-1]
    rsi = latest['rsi']
    ema9 = latest['ema9']
    ema21 = latest['ema21']
    close = latest['close']

    signal = None
    confidence = 0

    if rsi < 35 and close > ema9 and ema9 > ema21:
        signal = "CALL"
        confidence = 65 + min(25, int((35 - rsi) * 1.2))
    elif rsi > 65 and close < ema9 and ema9 < ema21:
        signal = "PUT"
        confidence = 65 + min(25, int((rsi - 65) * 1.2))

    if signal:
        confidence = max(60, min(92, confidence))
        return {
            "signal": signal,
            "confidence": round(confidence, 1),
            "rsi": round(rsi, 1)
        }
    return None

# ==================== WELCOME ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("🔐 Login with IQ Option", callback_data="login")]]
    await update.message.reply_text(
        "🤖 **IQ Option Trading Bot v5**\n\n"
        "Real connection • High probability signals\n\n"
        "Press the button below to login.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

# ==================== LOGIN ====================
async def login_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_data[user_id] = {"step": "email"}
    await query.edit_message_text("🔐 Send your **IQ Option Email**:")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_data:
        return

    step = user_data[user_id].get("step")

    if step == "email":
        user_data[user_id]["email"] = update.message.text
        user_data[user_id]["step"] = "password"
        await update.message.reply_text("✅ Email saved.\n\nNow send your **IQ Option Password**:")

    elif step == "password":
        email = user_data[user_id]["email"]
        password = update.message.text

        await update.message.reply_text("🔄 Connecting to IQ Option (this may take 15-20 seconds)...")

        iq = IQOption(email, password, "demo")
        iq.connect()

        if iq.connected:
            user_iq[user_id] = iq
            user_data[user_id]["step"] = "dashboard"

            time.sleep(3)
            balance = iq.balance if iq.balance > 0 else "N/A"

            await update.message.reply_text(
                f"✅ **Connected Successfully!**\n\n"
                f"📊 **Dashboard**\n"
                f"Account: **Demo**\n"
                f"Balance: **${balance}**\n"
                f"Status: Connected\n\n"
                f"What would you like to do?",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🚀 TAKE A TRADE", callback_data="take_trade")],
                    [InlineKeyboardButton("📜 HISTORY", callback_data="history")],
                    [InlineKeyboardButton("📈 STATISTICS", callback_data="stats")]
                ])
            )
        else:
            await update.message.reply_text(
                "❌ Login failed.\n\n"
                "Possible reasons:\n"
                "• Wrong email or password\n"
                "• IQ Option connection is slow/unstable right now\n"
                "• Try again in 1-2 minutes"
            )

# ==================== TAKE A TRADE ====================
async def take_trade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "⏱ **Choose expiry**",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("30s", callback_data="expiry_30s")],
            [InlineKeyboardButton("1m", callback_data="expiry_1m")],
            [InlineKeyboardButton("2m", callback_data="expiry_2m")],
            [InlineKeyboardButton("5m", callback_data="expiry_5m")],
        ])
    )

async def show_real_signals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if user_id not in user_iq:
        await query.edit_message_text("Please login first.")
        return

    iq = user_iq[user_id]
    signals_text = []
    keyboard = []

    pairs = ["GBP/USD OTC", "USD/JPY OTC", "EUR/USD OTC", "USD/CAD OTC"]

    for pair in pairs:
        df = iq.get_candles(pair, timeframe=60, count=80)
        sig = generate_high_probability_signal(df)

        if sig and sig["confidence"] >= 65:
            signals_text.append(f"{sig['signal']} {pair} — {sig['confidence']}% (RSI: {sig['rsi']})")
            keyboard.append([InlineKeyboardButton(f"{sig['signal']} {pair}", callback_data=f"signal_{pair}")])

    if not signals_text:
        text = "No high-probability signals (65%+) right now. Try again in a few minutes."
    else:
        text = "🎯 **High Probability Signals (65%+)**\n\n" + "\n".join(signals_text)

    keyboard.append([InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

# ==================== MAIN ====================
def main():
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        print("Set TELEGRAM_TOKEN")
        return

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(login_button, pattern="^login$"))
    app.add_handler(CallbackQueryHandler(take_trade, pattern="^take_trade$"))
    app.add_handler(CallbackQueryHandler(show_real_signals, pattern="^expiry_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("✅ IQ Option Bot v5 Improved is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
