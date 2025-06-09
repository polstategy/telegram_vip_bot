# main.py — ربات تلگرام Polling + وب‌سرور aiohttp (رفع کامل خطای event loop)
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

# اضافه شدن کانال CIP
try:
    CIP_CHANNEL_ID = int(os.environ.get("CIP_CHANNEL_ID", "0"))
except ValueError:
    logging.error("متغیر محیطی CIP_CHANNEL_ID معتبر نیست یا تعریف نشده!")
    exit(1)

CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "@your_channel_username")
CHANNEL_INVITE_STATIC = os.environ.get(
    "CHANNEL_INVITE_STATIC", "https://t.me/+QYggjf71z9lmODVl"
)
SUPPORT_ID = os.environ.get("SUPPORT_ID", "@your_support_id")
GOOGLE_SHEET_URL = os.environ.get(
    "GOOGLE_SHEET_URL",
    "https://script.google.com/macros/s/YOUR_SCRIPT_ID/exec"
)
TWELVE_API_KEY = os.environ.get("TWELVE_API_KEY", "")
if not TWELVE_API_KEY:
    logging.warning(
        "متغیر محیطی TWELVE_API_KEY تنظیم نشده است؛ احتمالا تحلیل بازار کار نخواهد کرد."
    )

DATA_FILE = "user_data.json"
LINK_EXPIRE_MINUTES = 10
MAX_LINKS_PER_DAY = 5
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

    # اگر شماره با +98 یا 0098 آمده باشد، آن را به 0 تبدیل می‌کنیم:
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
        "CIP": False,         # اشتراک CIP - مقدار اولیه
        "Hotline": False,     # اشتراک Hotline - مقدار اولیه
    }
    save_data(users_data)

    # نمایش منوی اصلی
    await show_main_menu(update, context)

# تابع بهبود یافته برای به‌روزرسانی اطلاعات اشتراک از Google Sheet
async def update_subscription_from_sheet(user_id):
    user = users_data.get(user_id)
    if not user:
        return False
        
    phone = user["phone"]
    try:
        # افزایش timeout به 30 ثانیه
        resp = requests.get(f"{GOOGLE_SHEET_URL}?phone={phone}", timeout=30)
        info = resp.json()
    except Exception as e:
        logging.error(f"خطا در بررسی اشتراک: {e}")
        return False
        
    if info.get("status") == "found":
        days_left = int(info.get("days_left", 0))
        expire_date = (datetime.utcnow().date() + timedelta(days=days_left)).isoformat()
        
        # به‌روزرسانی اطلاعات اشتراک
        user["expire_date"] = expire_date
        user["CIP"] = info.get("CIP", "F") == "T"
        user["Hotline"] = info.get("Hotline", "F") == "T"
        save_data(users_data)
        return True
    else:
        # اگر اشتراک پیدا نشد، وضعیت را ریست می‌کنیم
        user["expire_date"] = ""
        user["CIP"] = False
        user["Hotline"] = False
        save_data(users_data)
        return True

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    
    # به‌روزرسانی اطلاعات اشتراک از Google Sheet
    await update_subscription_from_sheet(user_id)
    
    user = users_data.get(user_id)
    if not user:
        await update.message.reply_text("⚠️ لطفاً ابتدا احراز هویت کنید (/start).")
        return

    # ساخت منوی پویا بر اساس نوع اشتراک
    keyboard = []
    
    # ردیف اول: اشتراک من و گزینه‌های اشتراک
    row1 = ["📅 اشتراک من"]
    if user.get("Hotline", False):
        row1.append("🔑 ورود به کانال")
    if user.get("CIP", False):
        row1.append("🌐 کانال CIP")
    keyboard.append(row1)
    
    # ردیف دوم: خرید اشتراک و پشتیبانی
    keyboard.append(["💳 خرید اشتراک", "🛟 پشتیبانی"])
    
    # ردیف سوم: تحلیل بازار و اخبار اقتصادی
    keyboard.append(["📊 تحلیل بازار", "📰 اخبار اقتصادی فارکس"])
    
    await update.message.reply_text(
        "از منوی زیر یکی را انتخاب کنید:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
    )

# —————————————————————————————————————————————————————————————————————
# بخش سوم: مدیریت اشتراک و تاریخ انقضا
# —————————————————————————————————————————————————————————————————————

async def my_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    
    # به‌روزرسانی اطلاعات اشتراک از Google Sheet
    updated = await update_subscription_from_sheet(user_id)
    
    user = users_data.get(user_id)
    if not user:
        await update.message.reply_text("⚠️ لطفاً ابتدا احراز هویت کنید (/start).")
        return

    if not updated:
        await update.message.reply_text("⚠️ خطا در بررسی اشتراک. لطفاً بعداً تلاش کنید.")
        return

    if user.get("expire_date"):
        exp_date = datetime.fromisoformat(user["expire_date"]).date()
        today = datetime.utcnow().date()
        days_left = (exp_date - today).days
        
        if days_left <= 0:
            await update.message.reply_text("⚠️ اشتراک شما منقضی شده است.")
            return
            
        # نمایش نوع اشتراک
        subscription_type = []
        if user.get("CIP", False):
            subscription_type.append("CIP")
        if user.get("Hotline", False):
            subscription_type.append("Hotline")
        
        if subscription_type:
            await update.message.reply_text(
                f"✅ اشتراک شما فعال است.\n"
                f"🔹 نوع اشتراک: {', '.join(subscription_type)}\n"
                f"⏳ {days_left} روز باقی مانده تا {user['expire_date']}."
            )
        else:
            await update.message.reply_text("⚠️ شما تا به حال اشتراکی تهیه نکرده‌اید.")
    else:
        await update.message.reply_text("⚠️ شما تا به حال اشتراکی تهیه نکرده‌اید.")

# —————————————————————————————————————————————————————————————————————
# بخش چهارم: ساخت لینک موقت ۱۰ دقیقه‌ای برای ورود به کانال‌ها
# —————————————————————————————————————————————————————————————————————

async def join_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    
    # به‌روزرسانی اطلاعات اشتراک از Google Sheet
    await update_subscription_from_sheet(user_id)
    
    user = users_data.get(user_id)
    if not user:
        await update.message.reply_text("⚠️ ابتدا احراز هویت کنید (/start).")
        return

    # بررسی اشتراک Hotline
    if not user.get("Hotline", False):
        await update.message.reply_text("⚠️ شما اشتراک Hotline ندارید.")
        return

    exp_date_str = user.get("expire_date", "")
    if not exp_date_str:
        await update.message.reply_text("⚠️ اشتراک شما فعال نیست.")
        return

    exp_date = datetime.fromisoformat(exp_date_str).date()
    today = datetime.utcnow().date()
    if today > exp_date:
        await update.message.reply_text("⚠️ اشتراک شما منقضی شده است.")
        return

    # محدودیت 5 لینک در روز
    today_str = today.isoformat()
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
        f"📎 لینک عضویت در کانال VIP (۱۰ دقیقه اعتبار):\n{invite_link}\n\n"
        "✅ لطفا از لینک بالا برای ورود به کانال VIP استفاده کنید.\n"
        f"⚠️ محدودیت: فقط {MAX_LINKS_PER_DAY} لینک در روز.\n"
    )

# تابع برای عضویت در کانال CIP
async def join_cip_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    
    # به‌روزرسانی اطلاعات اشتراک از Google Sheet
    await update_subscription_from_sheet(user_id)
    
    user = users_data.get(user_id)
    if not user:
        await update.message.reply_text("⚠️ ابتدا احراز هویت کنید (/start).")
        return

    # بررسی اشتراک CIP
    if not user.get("CIP", False):
        await update.message.reply_text("⚠️ شما اشتراک CIP ندارید.")
        return

    exp_date_str = user.get("expire_date", "")
    if not exp_date_str:
        await update.message.reply_text("⚠️ اشتراک شما فعال نیست.")
        return

    exp_date = datetime.fromisoformat(exp_date_str).date()
    today = datetime.utcnow().date()
    if today > exp_date:
        await update.message.reply_text("⚠️ اشتراک شما منقضی شده است.")
        return

    # محدودیت 5 لینک در روز
    today_str = today.isoformat()
    links_count = user["links"].get(today_str, 0)
    if links_count >= MAX_LINKS_PER_DAY:
        await update.message.reply_text("⚠️ سقف درخواست لینک در روز تمام شده است.")
        return

    # ایجاد لینک موقت
    try:
        res = await context.bot.create_chat_invite_link(
            chat_id=CIP_CHANNEL_ID,
            expire_date=int((datetime.utcnow() + timedelta(minutes=LINK_EXPIRE_MINUTES)).timestamp()),
            member_limit=1,
        )
        invite_link = res.invite_link
    except Exception as e:
        logging.error(f"خطا در ایجاد لینک دعوت CIP: {e}")
        await update.message.reply_text("⚠️ در ایجاد لینک دعوت CIP خطایی رخ داد. لطفاً بعداً تلاش کنید.")
        return

    # ذخیره لینک و شمارش
    user["links"][today_str] = links_count + 1
    user.setdefault("last_link", {}).update(
        {"link": invite_link, "timestamp": datetime.utcnow().isoformat()}
    )
    save_data(users_data)

    # ارسال لینک موقت به کاربر
    await update.message.reply_text(
        f"📎 لینک عضویت در کانال CIP (۱۰ دقیقه اعتبار):\n{invite_link}\n\n"
        "✅ لطفا از لینک بالا برای ورود به کانال CIP استفاده کنید.\n"
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
    "هفته گذشته": "1w",
    "ماه گذشته": "1m",
    "سه ماه گذشته": "3m",
    "شش ماه گذشته": "6m",
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

    # نمایش نام فارسی دارایی
    asset_label = [k for k, v in ASSETS.items() if v == symbol][0]
    
    # نمایش نام فارسی دوره
    period_label = [k for k, v in PERIODS.items() if v == period][0]
    
    msg = f"📊 تحلیل {asset_label} برای {period_label}:\n"
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
    
    # تعیین محدوده زمانی بر اساس انتخاب کاربر
    if period == "1w":
        days = 7
    elif period == "1m":
        days = 30
    elif period == "3m":
        days = 90
    elif period == "6m":
        days = 180
    else:
        days = 7
        
    start_date = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    end_date = now.strftime("%Y-%m-%d")

    url = (
        "https://api.twelvedata.com/time_series?"
        f"symbol={symbol}&"
        "interval=1day&"
        f"start_date={start_date}&"
        f"end_date={end_date}&"
        f"apikey={TWELVE_API_KEY}"
    )
    try:
        resp = requests.get(url, timeout=15).json()
        candles = resp.get("values", [])
    except Exception as e:
        logging.error(f"خطا در دریافت داده‌های دارایی: {e}")
        return None

    if not candles:
        return None

    # تبدیل داده‌ها به فرمت عددی
    highs = []
    lows = []
    closes = []
    for c in candles:
        try:
            highs.append(float(c["high"]))
            lows.append(float(c["low"]))
            closes.append(float(c["close"]))
        except (KeyError, ValueError):
            continue

    if not highs:
        return None

    H = max(highs)
    L = min(lows)
    C = closes[-1] if closes else (H + L) / 2

    # محاسبات سطوح
    M1 = (H + L) / 2
    M2 = (H + M1) / 2
    M3 = (L + M1) / 2
    M4 = (H + M2) / 2
    M5 = (M2 + M1) / 2
    M6 = (M1 + M3) / 2
    M7 = (M3 + L) / 2
    Z1 = (H + L + C) / 3
    pip = abs(H - M4)

    # محاسبه سطوح مقاومت و حمایت
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
                await app.bot.ban_chat_member(chat_id=CIP_CHANNEL_ID, user_id=int(user_id))
                await app.bot.unban_chat_member(chat_id=CIP_CHANNEL_ID, user_id=int(user_id))
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
    elif text == "🌐 کانال CIP":
        await join_cip_channel(update, context)
    elif text == "💳 خرید اشتراک":
        await buy_subscription(update, context)
    elif text == "🛟 پشتیبانی":
        await support(update, context)
    elif text == "📊 تحلیل بازار":
        await analysis_menu(update, context)
    elif text == "📰 اخبار اقتصادی فارکس":
        await economic_news(update, context)
    else:
        await update.message.reply_text("⚠️ لطفاً از منوی اصلی یک گزینه را انتخاب کنید.")

# تابع جدید برای اخبار اقتصادی فارکس
async def economic_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    news_sources = [
        "📰 اخبار و تقویم اقتصادی فارکس:",
        "• Forex Factory (تقویم اقتصادی): https://www.forexfactory.com/",
        "• Investing.com: https://www.investing.com/economic-calendar/",
        "• DailyFX: https://www.dailyfx.com/economic-calendar",
        "• FXStreet: https://www.fxstreet.com/economic-calendar",
        "• Babypips: https://www.babypips.com/economic-calendar",
        "• خبرگزاری فارس (بخش اقتصاد): https://www.farsnews.ir/economy",
        "• بورس نیوز (اخبار فارکس): https://www.boursenews.ir/tag/فارکس",
    ]
    
    await update.message.reply_text("\n".join(news_sources))

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
    app_http = web.Application()
    app_http.router.add_get("/", handle_root)
    app_http.router.add_get("/health", health_check)  # اضافه کردن سلامت‌سنج
    runner = web.AppRunner(app_http)
    await runner.setup()
    port = int(os.environ.get("PORT", "10000"))  # پورت پیش‌فرض 10000
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"🚀 Web server listening on port {port}")

# بعد از تابع handle_root
async def health_check(request):
    return web.Response(text="OK", status=200)

# در تابع run_webserver
app_http.router.add_get("/health", health_check)

# —————————————————————————————————————————————————————————————————————
# بخش دهم: تعریف main_async (غیر مسدودکننده) برای راه‌اندازی وب‌سرور و ربات
# —————————————————————————————————————————————————————————————————————

async def main_async():
    logging.basicConfig(level=logging.INFO)
    logging.info("🚀 Bot is starting...")

    # ۱) استارت وب‌سرور aiohttp در پس‌زمینه
    asyncio.create_task(run_webserver())

    # ۲) ساخت ربات و افزودن هندلرها
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_handler(CallbackQueryHandler(callback_query_handler))

    # مقداردهی اولیه و اجرا (بدون بستن حلقه)
    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    # ۳) حلقهٔ هشدار قیمت (در پس‌زمینه)
    async def alert_loop():
        await asyncio.sleep(10)  # صبر اولیه برای بالا آمدن ربات
        while True:
            try:
                await check_alerts(app)
            except Exception as e:
                logging.error(f"خطا در حلقه هشدار قیمت: {e}")
            await asyncio.sleep(ALERT_INTERVAL_SECONDS)

    asyncio.create_task(alert_loop())

    # ۴) نگه داشتن ترد ربات و وب‌سرور تا زمانی که SIGTERM بیاید
    #    با این کار حلقهٔ asyncio بسته نمی‌شود و همه چیز زنده می‌ماند.
    await asyncio.Event().wait()

# —————————————————————————————————————————————————————————————————————
# نقطهٔ ورود (استفاده از یک حلقهٔ واحد asyncio)
# —————————————————————————————————————————————————————————————————————

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(main_async())
    loop.run_forever()
