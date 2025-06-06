# main.py — ربات تلگرام Polling + وب‌سرور aiohttp (مشابه ورژن قبلی، با رفع خطای loop)
# -------------------------------------------------------------
import logging
import json
import os
import asyncio
from datetime import datetime, timedelta

import requests
from telegram import (
    Update,
    KeyboardButton,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

from aiohttp import web  # برای وب‌سرور سبک

# -------------------------------------------------------------
# ==== تنظیمات اصلی (از متغیرهای محیطی خوانده می‌شود) ====

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
if not BOT_TOKEN:
    logging.error("متغیر محیطی BOT_TOKEN تعریف نشده است!")
    exit(1)

try:
    CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "0"))
except ValueError:
    logging.error("متغیر محیطی CHANNEL_ID معتبر نیست یا تعریف نشده!")
    exit(1)

CHANNEL_USERNAME     = os.environ.get("CHANNEL_USERNAME", "@your_channel_username")
CHANNEL_INVITE_STATIC = os.environ.get(
    "CHANNEL_INVITE_STATIC", "https://t.me/+QYggjf71z9lmODVl"
)
SUPPORT_ID          = os.environ.get("SUPPORT_ID", "@your_support_id")
GOOGLE_SHEET_URL    = os.environ.get(
    "GOOGLE_SHEET_URL",
    "https://script.google.com/macros/s/YOUR_SCRIPT_ID/exec"
)
TWELVE_API_KEY      = os.environ.get("TWELVE_API_KEY", "")
if not TWELVE_API_KEY:
    logging.warning(
        "متغیر محیطی TWELVE_API_KEY تنظیم نشده است؛ احتمالا تحلیل بازار کار نخواهد کرد."
    )

DATA_FILE = "user_data.json"
LINK_EXPIRE_MINUTES = 10
MAX_LINKS_PER_DAY   = 5
ALERT_INTERVAL_SECONDS = 300  # هر ۵ دقیقه یکبار چک هشدار

# -------------------------------------------------------------


# —————————————————————————————————————————————————————————————————————
# بخش اول: بارگذاری و ذخیره اطلاعات کاربران (JSON)
# —————————————————————————————————————————————————————————————————————

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

users_data = load_data()

# —————————————————————————————————————————————————————————————————————
# بخش دوم: دستورات عمومی ربات (/start و احراز هویت)
# —————————————————————————————————————————————————————————————————————

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[KeyboardButton("تایید و احراز هویت", request_contact=True)]]
    await update.message.reply_text(
        "👋 سلام! برای ادامه لطفاً شماره موبایل خود را ارسال کنید:",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True),
    )

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.contact
    user_id = str(update.effective_user.id)
    phone = contact.phone_number

    # اگر شماره با +98 یا 0098 شروع شده باشد، آن را به 0 تبدیل می‌کنیم
    if phone.startswith("+98"):
        phone = "0" + phone[3:]
    elif phone.startswith("0098"):
        phone = "0" + phone[4:]

    first_name = update.effective_user.first_name or ""
    last_name  = update.effective_user.last_name or ""

    # ثبت اولیه در Google Sheet (POST با action=register)
    try:
        payload = {
            "action": "register",
            "phone": phone,
            "name": first_name,
            "family": last_name,
        }
        requests.post(GOOGLE_SHEET_URL, json=payload, timeout=10)
    except Exception as e:
        logging.error(f"خطا در ارسال POST به Google Sheet: {e}")

    # ذخیره در JSON محلی
    users_data[user_id] = {
        "phone": phone,
        "name": first_name,
        "family": last_name,
        "registered_at": datetime.utcnow().isoformat(),
        "expire_date": "",    # بعد از بررسی اشتراک پر می‌شود
        "links": {},          # دفعات درخواست لینک در هر روز
        "alerts": [],         # هشدارهای ارسال‌شده (کلیدهای سطح) برای جلوگیری از تکرار
        "watch_assets": [],   # دارایی‌ها و دوره‌ها برای هشدار لحظه‌ای
    }
    save_data(users_data)

    # نمایش منوی اصلی
    await show_main_menu(update, context)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["📅 اشتراک من", "🔑 ورود به کانال"],
        ["💳 خرید اشتراک", "🛟 پشتیبانی"],
        ["📊 تحلیل بازار"],
    ]
    await update.message.reply_text(
        "از منوی زیر یکی را انتخاب کنید:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
    )

# —————————————————————————————————————————————————————————————————————
# بخش سوم: مدیریت اشتراک و تاریخ انقضا
# —————————————————————————————————————————————————————————————————————

async def my_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users_data.get(user_id)
    if not user:
        await update.message.reply_text("⚠️ لطفاً ابتدا احراز هویت کنید (/start).")
        return

    phone = user["phone"]
    try:
        resp = requests.get(f"{GOOGLE_SHEET_URL}?phone={phone}", timeout=10)
        info = resp.json()
    except Exception as e:
        logging.error(f"خطا در بررسی اشتراک: {e}")
        await update.message.reply_text("⚠️ خطا در بررسی اشتراک. لطفاً بعداً تلاش کنید.")
        return

    if info.get("status") == "found":
        days_left = int(info.get("days_left", 0))
        expire_date = (datetime.utcnow().date() + timedelta(days=days_left)).isoformat()
        user["expire_date"] = expire_date
        save_data(users_data)
        await update.message.reply_text(
            f"✅ اشتراک شما فعال است.\n⏳ {days_left} روز باقی مانده تا {expire_date}."
        )
    else:
        await update.message.reply_text("⚠️ شما تا به حال اشتراکی تهیه نکرده‌اید.")

# —————————————————————————————————————————————————————————————————————
# بخش چهارم: ساخت لینک موقت ۱۰ دقیقه‌ای برای ورود به کانال VIP
# —————————————————————————————————————————————————————————————————————

async def join_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users_data.get(user_id)
    if not user:
        await update.message.reply_text("⚠️ ابتدا احراز هویت کنید (/start).")
        return

    exp_date_str = user.get("expire_date", "")
    if not exp_date_str:
        await update.message.reply_text("⚠️ شما اشتراک فعالی ندارید.")
        return

    exp_date = datetime.fromisoformat(exp_date_str)
    if datetime.utcnow().date() > exp_date.date():
        await update.message.reply_text("⚠️ اشتراک شما منقضی شده است.")
        return

    # محدودیت 5 لینک در روز
    today_str = datetime.utcnow().date().isoformat()
    links_count = user["links"].get(today_str, 0)
    if links_count >= MAX_LINKS_PER_DAY:
        await update.message.reply_text("⚠️ سقف درخواست لینک در روز تمام شده است.")
        return

    # ایجاد لینک موقت
    try:
        res = await context.bot.create_chat_invite_link(
            chat_id=CHANNEL_ID,
            expire_date=int((datetime.utcnow() + timedelta(minutes=LINK_EXPIRE_MINUTES)).timestamp()),
            member_limit=1,
        )
        invite_link = res.invite_link
    except Exception as e:
        logging.error(f"خطا در ایجاد لینک دعوت: {e}")
        await update.message.reply_text("⚠️ در ایجاد لینک دعوت خطایی رخ داد. لطفاً بعداً تلاش کنید.")
        return

    # ذخیره لینک و شمارش
    user["links"][today_str] = links_count + 1
    user.setdefault("last_link", {}).update(
        {"link": invite_link, "timestamp": datetime.utcnow().isoformat()}
    )
    save_data(users_data)

    # ارسال لینک موقت به کاربر
    await update.message.reply_text(
        f"📎 لینک عضویت (۱۰ دقیقه اعتبار):\n{invite_link}\n\n"
        "✅ لطفا از لینک بالا برای ورود به کانال VIP استفاده کنید.\n"
        f"⚠️ محدودیت: فقط {MAX_LINKS_PER_DAY} لینک در روز.\n"
    )

# —————————————————————————————————————————————————————————————————————
# بخش پنجم: تحلیل بازار (انس طلا و سایر دارایی‌ها) + منوی انتخاب دارایی
# —————————————————————————————————————————————————————————————————————

ASSETS = {
    "انس طلا": "XAU/USD",
    "EURUSD": "EUR/USD",
    "GBPUSD": "GBP/USD",
    "USDJPY": "USD/JPY",
    "DXY": "DXY",
    "DJI": "DJI",
    "NAS100": "NASDAQ",
}

PERIODS = {
    "هفتگی": "weekly",
    "ماهانه": "monthly",
    "سه‌ماهه": "quarterly",
    "شش‌ماهه": "semiannual",
}

async def analysis_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton(label, callback_data=f"period|{period}")]
        for label, period in PERIODS.items()
    ]
    kb.append([InlineKeyboardButton("بازگشت به منو", callback_data="analysis|restart")])
    await update.message.reply_text(
        "لطفاً دوره زمانی مورد نظر را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(kb),
    )

async def asset_selection_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, period = query.data.split("|", 1)
    context.user_data["analysis"] = {"period": period}

    kb = [
        [InlineKeyboardButton(label, callback_data=f"asset|{symbol}")]
        for label, symbol in ASSETS.items()
    ]
    kb.append([InlineKeyboardButton("بازگشت", callback_data="analysis|restart")])
    await query.edit_message_text(
        "لطفاً دارایی مورد نظر را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(kb),
    )

async def asset_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, symbol = query.data.split("|", 1)
    context.user_data["analysis"]["symbol"] = symbol
    period = context.user_data["analysis"]["period"]

    asset_data = await get_asset_data(symbol, period)
    if not asset_data:
        await query.edit_message_text("⚠️ خطا در دریافت داده‌ها، لطفا بعداً تلاش کنید.")
        return

    msg = f"📊 تحلیل {symbol} برای دوره {period}:\n"
    msg += f"High: {asset_data['H']:.2f}\nLow: {asset_data['L']:.2f}\nClose: {asset_data['C']:.2f}\n\n"
    msg += f"M1: {asset_data['M1']:.2f}, M2: {asset_data['M2']:.2f}, M3: {asset_data['M3']:.2f}, M4: {asset_data['M4']:.2f}\n"
    msg += f"M5: {asset_data['M5']:.2f}, M6: {asset_data['M6']:.2f}, M7: {asset_data['M7']:.2f}\n"
    msg += f"Z1: {asset_data['Z1']:.2f}\nPip: {asset_data['pip']:.4f}\n\n"
    msg += "مقاومت‌ها (U1–U5): " + ", ".join(f"{u:.2f}" for u in asset_data["U"][:5]) + "\n"
    msg += "حمایت‌ها (D1–D5): " + ", ".join(f"{d:.2f}" for d in asset_data["D"][:5]) + "\n\n"
    msg += "🔔 هشدار لحظه‌ای فعال شد. اگر قیمت به سطوح برخورد کند، به شما اطلاع داده می‌شود."

    await query.edit_message_text(msg)

    user_id = str(update.effective_user.id)
    user = users_data.get(user_id)
    if user is not None:
        watch_list = user.setdefault("watch_assets", [])
        exists = any(
            (w["symbol"] == symbol and w["period"] == period) for w in watch_list
        )
        if not exists:
            watch_list.append(
                {
                    "symbol": symbol,
                    "period": period,
                    "last_processed": datetime.utcnow().isoformat(),
                }
            )
            save_data(users_data)

async def analysis_restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await analysis_menu(update, context)

# —————————————————————————————————————————————————————————————————————
# بخش ششم: دریافت داده‌های دارایی (TwelveData)
# —————————————————————————————————————————————————————————————————————

async def get_asset_data(symbol: str, period: str):
    now = datetime.utcnow()
    if period == "weekly":
        start = now - timedelta(days=7)
    elif period == "monthly":
        start = now - timedelta(days=30)
    elif period == "quarterly":
        start = now - timedelta(days=90)
    elif period == "semiannual":
        start = now - timedelta(days=180)
    else:
        start = now - timedelta(days=7)
    end = now

    url = (
        "https://api.twelvedata.com/time_series?"
        f"symbol={symbol}&"
        "interval=1day&"
        f"start_date={start.date()}&"
        f"end_date={end.date()}&"
        f"apikey={TWELVE_API_KEY}"
    )
    try:
        resp = requests.get(url, timeout=10).json()
        candles = resp.get("values", [])
    except:
        return None

    if not candles:
        return None

    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]
    closes = [float(c["close"]) for c in candles]

    H = max(highs)
    L = min(lows)
    C = closes[-1]

    M1 = (H + L) / 2
    M2 = (H + M1) / 2
    M3 = (L + M1) / 2
    M4 = (H + M2) / 2
    M5 = (M2 + M1) / 2
    M6 = (M1 + M3) / 2
    M7 = (M3 + L) / 2
    Z1 = (H + L + C) / 3
    pip = abs(H - M4)

    U = [H + pip * (i + 1) for i in range(30)]
    D = [L - pip * (i + 1) for i in range(30)]

    return {
        "H": H,
        "L": L,
        "C": C,
        "M1": M1,
        "M2": M2,
        "M3": M3,
        "M4": M4,
        "M5": M5,
        "M6": M6,
        "M7": M7,
        "Z1": Z1,
        "pip": pip,
        "U": U,
        "D": D,
    }

async def get_current_price(symbol: str):
    url = f"https://api.twelvedata.com/price?symbol={symbol}&apikey={TWELVE_API_KEY}"
    try:
        resp = requests.get(url, timeout=10).json()
        return float(resp.get("price", 0))
    except:
        return None

# —————————————————————————————————————————————————————————————————————
# بخش هفتم: هشدار لحظه‌ای قیمت برای تمام کاربران فعال
# —————————————————————————————————————————————————————————————————————

async def check_alerts(app):
    global users_data

    for user_id, user in users_data.items():
        if "watch_assets" not in user:
            continue

        exp_str = user.get("expire_date", "")
        if not exp_str or datetime.utcnow().date() > datetime.fromisoformat(exp_str).date():
            # حذف کاربر از کانال در صورت منقضی شدن اشتراک
            try:
                await app.bot.ban_chat_member(chat_id=CHANNEL_ID, user_id=int(user_id))
                await app.bot.unban_chat_member(chat_id=CHANNEL_ID, user_id=int(user_id))
            except:
                pass
            continue

        for wa in user["watch_assets"]:
            symbol = wa["symbol"]
            period = wa["period"]

            asset_data = await get_asset_data(symbol, period)
            if not asset_data:
                continue
            price = await get_current_price(symbol)
            if price is None:
                continue

            pip = asset_data["pip"]
            levels = [
                asset_data["M1"],
                asset_data["M2"],
                asset_data["M3"],
                asset_data["M4"],
                asset_data["M5"],
                asset_data["M6"],
                asset_data["M7"],
                asset_data["Z1"],
            ] + asset_data["U"] + asset_data["D"]

            for lvl in levels:
                key = f"{symbol}_{period}_{round(lvl, 2)}"
                if key in user["alerts"]:
                    continue
                if abs(price - lvl) < pip / 10:
                    try:
                        await app.bot.send_message(
                            chat_id=int(user_id),
                            text=f"⚠️ قیمت {symbol} به سطح مهم {round(lvl, 2)} رسیده.\nقیمت فعلی: {price:.2f}",
                        )
                        user["alerts"].append(key)
                        save_data(users_data)
                    except Exception as e:
                        logging.error(f"خطا در ارسال هشدار به {user_id}: {e}")

            wa["last_processed"] = datetime.utcnow().isoformat()

        save_data(users_data)

# —————————————————————————————————————————————————————————————————————
# بخش هشتم: هندلر پیام‌های متنی منو
# —————————————————————————————————————————————————————————————————————

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "📅 اشتراک من":
        await my_subscription(update, context)
    elif text == "🔑 ورود به کانال":
        await join_channel(update, context)
    elif text == "💳 خرید اشتراک":
        await buy_subscription(update, context)
    elif text == "🛟 پشتیبانی":
        await support(update, context)
    elif text == "📊 تحلیل بازار":
        await analysis_menu(update, context)
    else:
        await update.message.reply_text("⚠️ لطفاً از منوی اصلی یک گزینه را انتخاب کنید.")

async def buy_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💳 برای خرید اشتراک لطفاً با پشتیبانی تماس بگیرید.\n"
        f"📞 آیدی پشتیبانی: {SUPPORT_ID}"
    )

async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"👨‍💻 برای پشتیبانی لطفاً به آیدی زیر پیام دهید:\n{SUPPORT_ID}")

async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data_cb = update.callback_query.data
    if data_cb.startswith("period|"):
        await asset_selection_menu(update, context)
    elif data_cb.startswith("asset|"):
        await asset_selected(update, context)
    elif data_cb == "analysis|restart":
        await analysis_restart(update, context)
    else:
        await update.callback_query.answer()

# —————————————————————————————————————————————————————————————————————
# بخش نهم: وب‌سرور خیلی ساده با aiohttp (برای Render)
# —————————————————————————————————————————————————————————————————————

async def handle_root(request):
    return web.Response(text="Bot is running")

async def run_webserver():
    """
    وب‌سرور سبک aiohttp که روی پورتی که Render اختصاص می‌دهد گوش می‌دهد.
    """
    app = web.Application()
    app.router.add_get("/", handle_root)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", "8000"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"🚀 Web server listening on port {port}")

# —————————————————————————————————————————————————————————————————————
# بخش دهم: تعریف main_async (غیر مسدودکننده) برای راه‌اندازی وب‌سرور و Polling
# —————————————————————————————————————————————————————————————————————

async def main_async():
    logging.basicConfig(level=logging.INFO)
    logging.info("🚀 Bot is starting...")

    # ۱) استارت وب‌سرور در پس‌زمینه
    asyncio.create_task(run_webserver())

    # २) ساختن ربات و افزودن هندلرها
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_handler(CallbackQueryHandler(callback_query_handler))

    # ۳) شروع حلقهٔ هشدار قیمت در پس‌زمینه
    async def alert_loop():
        await asyncio.sleep(10)  # صبر اولیه برای اطمینان از بالا آمدن ربات
        while True:
            try:
                await check_alerts(app)
            except Exception as e:
                logging.error(f"خطا در حلقه هشدار قیمت: {e}")
            await asyncio.sleep(ALERT_INTERVAL_SECONDS)

    asyncio.create_task(alert_loop())

    # ۴) اجرای Polling ربات (این تابع تا زمانی که Ctrl+C یا SIGTERM بیاید، منتظر می‌ماند)
    await app.run_polling()

# —————————————————————————————————————————————————————————————————————
# نقطهٔ ورود (بدون استفاده از asyncio.run تا از خطای «event loop already running» جلوگیری شود)
# —————————————————————————————————————————————————————————————————————

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    # main_async را در حلقه به عنوان یک تسک اجرا می‌کنیم و سپس حلقه را دائماً نگه می‌داریم
    loop.create_task(main_async())
    loop.run_forever()
