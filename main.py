# main.py — ربات تلگرام Polling + وب‌سرور aiohttp + پنل ادمین
# -------------------------------------------------------------
import logging
import json
import os
import asyncio
import re
from datetime import datetime, timedelta

import requests
from telegram import (
    Update,
    KeyboardButton,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
    ConversationHandler
)
from aiohttp import web

# تنظیمات اصلی
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "0"))
CIP_CHANNEL_ID = int(os.environ.get("CIP_CHANNEL_ID", "0"))
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "@your_channel_username")
SUPPORT_ID = os.environ.get("SUPPORT_ID", "@Daniyalkhanzadeh")
GOOGLE_SHEET_URL = os.environ.get("GOOGLE_SHEET_URL", "https://script.google.com/macros/s/YOUR_SCRIPT_ID/exec")
TWELVE_API_KEY = os.environ.get("TWELVE_API_KEY", "")
PORT = int(os.environ.get("PORT", "10000"))

DATA_FILE = "user_data.json"
LINK_EXPIRE_MINUTES = 10
MAX_LINKS_PER_DAY = 5
ALERT_INTERVAL_SECONDS = 300
SUBSCRIPTION_ALERT_DAYS = 3  # تعداد روزهای مانده به پایان اشتراک برای ارسال هشدار

# مراحل گفتگو برای پنل ادمین
ADMIN_LOGIN, ADMIN_ACTION, SELECT_USER, EDIT_SUBSCRIPTION = range(4)

# -------------------------------------------------------------

# —————————————————————————————————————————————————————————————————————
# بخش اول: مدیریت داده‌ها (بارگذاری و ذخیره)
# —————————————————————————————————————————————————————————————————————

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"خطا در بارگیری فایل داده‌ها: {e}")
            return {}
    return {}

def save_data(data):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logging.error(f"خطا در ذخیره فایل داده‌ها: {e}")

users_data = load_data()

def normalize_phone(phone):
    """نرمال‌سازی شماره تلفن"""
    if not phone:
        return ""
        
    phone = re.sub(r'\D', '', phone)  # حذف همه غیر ارقام
    if phone.startswith('98'):
        phone = '0' + phone[2:]
    elif phone.startswith('+98'):
        phone = '0' + phone[3:]
    elif phone.startswith('0098'):
        phone = '0' + phone[4:]
    return phone[-10:]  # 10 رقم آخر

async def update_user_in_sheet(user_data):
    """به‌روزرسانی کاربر در Google Sheet"""
    try:
        payload = {
            "action": "register",  # تغییر به register برای ثبت اولیه
            "phone": user_data["phone"],
            "name": user_data.get("name", ""),
            "days": user_data.get("subscription_days", 0),
            "start_date": user_data.get("subscription_start", ""),
            "days_left": user_data.get("days_left", 0),
            "CIP": "T" if user_data.get("CIP", False) else "F",
            "Hotline": "T" if user_data.get("Hotline", False) else "F"
        }
        logging.info(f"ارسال داده به گوگل شیت: {payload}")
        response = requests.post(GOOGLE_SHEET_URL, json=payload, timeout=30)
        logging.info(f"پاسخ گوگل شیت: {response.status_code} - {response.text}")
        return response.status_code == 200
    except Exception as e:
        logging.error(f"خطا در به‌روزرسانی Google Sheet: {e}")
        return False

async def get_user_from_sheet(phone):
    """دریافت اطلاعات کاربر از Google Sheet"""
    try:
        phone = normalize_phone(phone)
        url = f"{GOOGLE_SHEET_URL}?phone={phone}"
        logging.info(f"دریافت اطلاعات از گوگل شیت: {url}")
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            logging.info(f"داده دریافتی از گوگل شیت: {response.text}")
            return response.json()
        else:
            logging.error(f"خطا در دریافت از گوگل شیت: {response.status_code}")
    except Exception as e:
        logging.error(f"خطا در دریافت اطلاعات از Google Sheet: {e}")
    return None

async def sync_user_data(user_id, user_data):
    """همگام‌سازی داده‌های کاربر بین سیستم و Google Sheet"""
    sheet_data = await get_user_from_sheet(user_data["phone"])

    if sheet_data and sheet_data.get("status") == "found":
        # تبدیل مقادیر به boolean
        user_data["CIP"] = bool(sheet_data.get("CIP", False))
        user_data["Hotline"] = bool(sheet_data.get("Hotline", False))

        # تعداد روز اشتراک
        try:
            user_data["subscription_days"] = int(sheet_data.get("days", 0))
        except:
            user_data["subscription_days"] = 0

        # تاریخ شروع اشتراک
        user_data["subscription_start"] = sheet_data.get("start_date", "")

        # محاسبه days_left
        if user_data["subscription_start"]:
            try:
                start_date = datetime.strptime(user_data["subscription_start"], "%Y-%m-%d").date()
                today = datetime.utcnow().date()
                days_passed = (today - start_date).days
                user_data["days_left"] = max(0, user_data["subscription_days"] - days_passed)
            except Exception as e:
                logging.error(f"خطا در محاسبه days_left: {e}")
                user_data["days_left"] = 0
        else:
            user_data["days_left"] = 0

        # ذخیره محلی
        users_data[user_id] = user_data
        save_data(users_data)

    else:
        # اگر کاربر در گوگل شیت نبود → ثبت اولیه
        await update_user_in_sheet(user_data)
        users_data[user_id] = user_data
        save_data(users_data)

    return user_data


# —————————————————————————————————————————————————————————————————————
# بخش دوم: احراز هویت و منوی اصلی
# —————————————————————————————————————————————————————————————————————
def build_main_menu_keyboard(user_data):
    """تابع کمکی برای ساخت کیبورد منوی اصلی"""
    keyboard = []
    
    # ردیف اول: اشتراک من
    keyboard.append(["📅 اشتراک من"])
    
    # ردیف دوم: دسترسی‌ها
    if user_data.get("Hotline", False) and user_data.get("days_left", 0) > 0:
        keyboard.append(["🔑 ورود به کانال"])
    if user_data.get("CIP", False) and user_data.get("days_left", 0) > 0:
        keyboard.append(["🌐 کانال CIP"])
    
    # ردیف سوم: تحلیل بازار (فقط برای Hotline فعال)
    if user_data.get("Hotline", False) and user_data.get("days_left", 0) > 0:
        keyboard.append(["📊 تحلیل بازار"])
    
    # ردیف چهارم: سایر گزینه‌ها
    keyboard.append(["💳 خرید اشتراک", "🛟 پشتیبانی"])
    keyboard.append(["📰 اخبار اقتصادی فارکس"])
    
    return keyboard

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[KeyboardButton("تایید و احراز هویت", request_contact=True)]]
    await update.message.reply_text(
        "👋 سلام! برای ادامه لطفاً شماره موبایل خود را ارسال کنید:",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True),
    )

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.contact
    user_id = str(update.effective_user.id)
    phone = normalize_phone(contact.phone_number)
    full_name = f"{update.effective_user.first_name or ''} {update.effective_user.last_name or ''}".strip()

    # ذخیره اولیه اطلاعات کاربر
    user_data = {
        "phone": phone,
        "name": full_name,
        "registered_at": datetime.utcnow().isoformat(),
        "links": {},
        "alerts": [],
        "watch_assets": [],
        "CIP": False,
        "Hotline": False,
        "subscription_days": 0,
        "subscription_start": "",
        "days_left": 0,
        "last_alert_sent": None  # تاریخ آخرین هشدار ارسالی
    }
    
    # همگام‌سازی با گوگل شیت
    user_data = await sync_user_data(user_id, user_data)
    
    # ذخیره کاربر جدید در دیتا
    users_data[user_id] = user_data
    save_data(users_data)
    
    # نمایش منوی اصلی
    await show_main_menu(update.message, context, user_data)

async def show_main_menu(message, context: ContextTypes.DEFAULT_TYPE, user_data):
    """نمایش منوی اصلی بر اساس سطح دسترسی کاربر"""
    keyboard = build_main_menu_keyboard(user_data)
    await message.reply_text(
        "از منوی زیر یکی را انتخاب کنید:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
    )

# —————————————————————————————————————————————————————————————————————
# بخش سوم: مدیریت اشتراک‌ها
# —————————————————————————————————————————————————————————————————————
async def my_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users_data.get(user_id)
    
    if not user:
        await update.message.reply_text("⚠️ لطفاً ابتدا احراز هویت کنید (/start).")
        return
    
    # همگام‌سازی با گوگل شیت
    user = await sync_user_data(user_id, user)
    
    if user.get("days_left", 0) > 0:
        # نمایش نوع اشتراک
        subscription_type = []
        if user.get("CIP", False):
            subscription_type.append("CIP")
        if user.get("Hotline", False):
            subscription_type.append("Hotline")
        
        expire_date = "نامشخص"
        if user.get("subscription_start"):
            try:
                start_date = datetime.strptime(user["subscription_start"], "%Y-%m-%d").date()
                expire_date = (start_date + timedelta(days=user["subscription_days"])).isoformat()
            except:
                pass
        
        message = (
            f"✅ اشتراک شما فعال است\n"
            f"🔹 نوع اشتراک: {', '.join(subscription_type) or 'تعریف نشده'}\n"
            f"⏳ روزهای باقی‌مانده: {user['days_left']}\n"
            f"📅 تاریخ انقضا: {expire_date}"
        )
    else:
        message = "⚠️ شما اشتراک فعالی ندارید."
    
    await update.message.reply_text(message)

# —————————————————————————————————————————————————————————————————————
# بخش چهارم: دسترسی به کانال‌ها (با تغییرات درخواستی)
# —————————————————————————————————————————————————————————————————————
async def generate_invite_link(context, chat_id, expire_minutes=10):
    """تولید لینک دعوت موقت"""
    try:
        # محاسبه زمان انقضا به درستی
        expire_timestamp = int((datetime.utcnow() + timedelta(minutes=expire_minutes)).timestamp())
        
        res = await context.bot.create_chat_invite_link(
            chat_id=chat_id,
            expire_date=expire_timestamp,  # استفاده از تایمستامپ محاسبه شده
            member_limit=1,
        )
        return res.invite_link
    except Exception as e:
        logging.error(f"خطا در ایجاد لینک دعوت: {e}")
        return None

async def join_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users_data.get(user_id)
    
    if not user:
        await update.message.reply_text("⚠️ ابتدا احراز هویت کنید (/start).")
        return
    
    # همگام‌سازی و بررسی دسترسی
    user = await sync_user_data(user_id, user)
    
    if not user.get("Hotline", False) or user.get("days_left", 0) <= 0:
        await update.message.reply_text("⚠️ شما دسترسی به این کانال را ندارید.")
        return
    
    # محدودیت تعداد لینک‌ها
    today = datetime.utcnow().date().isoformat()
    links_count = user.get("links", {}).get(today, 0)
    
    if links_count >= MAX_LINKS_PER_DAY:
        await update.message.reply_text("⚠️ سقف درخواست لینک در روز تمام شده است.")
        return
    
    # تولید لینک
    invite_link = await generate_invite_link(context, CHANNEL_ID, LINK_EXPIRE_MINUTES)
    
    if not invite_link:
        await update.message.reply_text("⚠️ خطا در ایجاد لینک. لطفاً بعداً تلاش کنید.")
        return
    
    # ذخیره اطلاعات
    user["links"][today] = links_count + 1
    users_data[user_id] = user
    save_data(users_data)
    
    # ارسال لینک به صورت دکمه اینلاین
    keyboard = [[InlineKeyboardButton("ورود به کانال", url=invite_link)]]
    await update.message.reply_text(
        f"🔑 لینک دسترسی به کانال (۱۰ دقیقه اعتبار):\n\n"
        f"⚠️ محدودیت: فقط {MAX_LINKS_PER_DAY} لینک در روز",
        reply_markup=InlineKeyboardMarkup(keyboard),
        protect_content=True  # غیرفعال کردن فوروارد و کپی
    )

async def join_cip_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users_data.get(user_id)
    
    if not user:
        await update.message.reply_text("⚠️ ابتدا احراز هویت کنید (/start).")
        return
    
    # همگام‌سازی و بررسی دسترسی
    user = await sync_user_data(user_id, user)
    
    if not user.get("CIP", False) or user.get("days_left", 0) <= 0:
        await update.message.reply_text("⚠️ شما دسترسی به این کانال را ندارید.")
        return
    
    # محدودیت تعداد لینک‌ها
    today = datetime.utcnow().date().isoformat()
    links_count = user.get("links", {}).get(today, 0)
    
    if links_count >= MAX_LINKS_PER_DAY:
        await update.message.reply_text("⚠️ سقف درخواست لینک در روز تمام شده است.")
        return
    
    # تولید لینک
    invite_link = await generate_invite_link(context, CIP_CHANNEL_ID, LINK_EXPIRE_MINUTES)
    
    if not invite_link:
        await update.message.reply_text("⚠️ خطا در ایجاد لینک. لطفاً بعداً تلاش کنید.")
        return
    
    # ذخیره اطلاعات
    user["links"][today] = links_count + 1
    users_data[user_id] = user
    save_data(users_data)
    
    # ارسال لینک به صورت دکمه اینلاین
    keyboard = [[InlineKeyboardButton("ورود به کانال CIP", url=invite_link)]]
    await update.message.reply_text(
        f"🌐 لینک دسترسی به کانال CIP (۱۰ دقیقه اعتبار):\n\n"
        f"⚠️ محدودیت: فقط {MAX_LINKS_PER_DAY} لینک در روز",
        reply_markup=InlineKeyboardMarkup(keyboard),
        protect_content=True  # غیرفعال کردن فوروارد و کپی
    )

# —————————————————————————————————————————————————————————————————————
# بخش پنجم: تحلیل بازار (فقط برای کاربران Hotline)
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
    user_id = str(update.effective_user.id)
    user = users_data.get(user_id)
    
    # بررسی دسترسی
    if not user or not user.get("Hotline", False) or user.get("days_left", 0) <= 0:
        await update.message.reply_text("⚠️ برای دسترسی به تحلیل بازار باید اشتراک Hotline فعال داشته باشید.")
        return
    
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
# بخش ششم: هشدار لحظه‌ای قیمت برای تمام کاربران فعال
# —————————————————————————————————————————————————————————————————————
async def check_alerts(app):
    global users_data
    
    for user_id, user in users_data.items():
        if "watch_assets" not in user:
            continue
        
        if user.get("days_left", 0) <= 0:
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
                            protect_content=True  # غیرفعال کردن فوروارد و کپی
                        )
                        user["alerts"].append(key)
                        save_data(users_data)
                    except Exception as e:
                        logging.error(f"خطا در ارسال هشدار به {user_id}: {e}")
            
            wa["last_processed"] = datetime.utcnow().isoformat()
        
        save_data(users_data)

# —————————————————————————————————————————————————————————————————————
# بخش جدید: هشدار اتمام اشتراک (با تغییرات درخواستی)
# —————————————————————————————————————————————————————————————————————
async def check_subscription_alerts(app):
    """ارسال هشدار به کاربرانی که اشتراکشان در حال اتمام است"""
    global users_data
    today = datetime.utcnow().date()
    
    for user_id, user in users_data.items():
        days_left = user.get("days_left", 0)
        last_alert = user.get("last_alert_sent")
        
        # شرایط ارسال هشدار:
        # - اشتراک فعال باشد (days_left > 0)
        # - ۳ روز یا کمتر به پایان اشتراک مانده باشد
        # - در ۲۴ ساعت گذشته هشداری ارسال نشده باشد
        if days_left > 0 and days_left <= SUBSCRIPTION_ALERT_DAYS:
            if last_alert:
                last_alert_date = datetime.fromisoformat(last_alert).date()
                if (today - last_alert_date).days < 1:
                    continue  # در ۲۴ ساعت گذشته هشدار ارسال شده
            
            # تشخیص نوع اشتراک
            subscription_types = []
            if user.get("CIP", False):
                subscription_types.append("کانال CIP")
            if user.get("Hotline", False):
                subscription_types.append("کانال اصلی")
            
            if not subscription_types:
                continue
                
            # ساخت پیام با ذکر نوع اشتراک
            subscription_names = " و ".join(subscription_types)
            message = (
                f"⏳ از زمان اشتراک شما برای {subscription_names} فقط {days_left} روز باقی مانده است!\n"
                f"⚠️ لطفاً جهت جلوگیری از حذف دسترسی به کانال‌ها اشتراک خود را تمدید کنید.\n\n"
                f"📞 برای تمدید اشتراک با پشتیبانی تماس بگیرید: {SUPPORT_ID}"
            )
            
            try:
                # ارسال پیام هشدار
                await app.bot.send_message(
                    chat_id=int(user_id),
                    text=message,
                    protect_content=True  # غیرفعال کردن فوروارد و کپی
                )
                
                # به‌روزرسانی زمان آخرین هشدار
                user["last_alert_sent"] = today.isoformat()
                save_data(users_data)
                
            except Exception as e:
                logging.error(f"خطا در ارسال هشدار اشتراک به {user_id}: {e}")

# —————————————————————————————————————————————————————————————————————
# بخش هفتم: پنل مدیریت ادمین (اصلاح شده)
# —————————————————————————————————————————————————————————————————————
async def admin_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔐 لطفاً رمز عبور ادمین را وارد کنید:",
        reply_markup=ReplyKeyboardRemove()
    )
    return ADMIN_LOGIN

async def handle_admin_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text
    if password == ADMIN_PASSWORD:
        await show_admin_dashboard(update, context)
        return ADMIN_ACTION
    else:
        await update.message.reply_text("❌ رمز عبور اشتباه است. لطفاً مجدداً تلاش کنید.")
        return ADMIN_LOGIN

async def show_admin_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["👥 لیست کاربران", "✏️ ویرایش اشتراک"],
        ["🔄 همگام‌سازی داده‌ها", "🔙 خروج"]
    ]
    await update.message.reply_text(
        "🔧 پنل مدیریت ادمین",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not users_data:
        await update.message.reply_text("❌ هیچ کاربری ثبت نشده است.")
        return ADMIN_ACTION
        
    message = "📋 لیست کاربران:\n\n"
    for user_id, data in users_data.items():
        phone = data.get("phone", "نامشخص")
        name = data.get("name", "بدون نام")
        days_left = data.get("days_left", 0)
        cip = "✅" if data.get("CIP", False) else "❌"
        hotline = "✅" if data.get("Hotline", False) else "❌"
        
        message += (
            f"🆔 ID: {user_id}\n"
            f"📱: {phone}\n"
            f"👤: {name}\n"
            f"⏳: {days_left} روز\n"
            f"CIP: {cip} | Hotline: {hotline}\n"
            f"───────────────────\n"
        )
    
    # ارسال پیام به صورت چند قسمتی اگر طولانی باشد
    for i in range(0, len(message), 4000):
        await update.message.reply_text(message[i:i+4000])
    return ADMIN_ACTION

async def edit_subscription_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "لطفاً شماره تلفن کاربر را وارد کنید:",
        reply_markup=ReplyKeyboardRemove()
    )
    return SELECT_USER

async def handle_user_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = normalize_phone(update.message.text)
    context.user_data["edit_user_phone"] = phone
    
    # پیدا کردن کاربر
    user_found = False
    for user_id, data in users_data.items():
        if data.get("phone") == phone:
            context.user_data["edit_user_id"] = user_id
            user_found = True
            break
    
    if not user_found:
        await update.message.reply_text("❌ کاربر یافت نشد. لطفاً شماره صحیح وارد کنید.")
        return SELECT_USER
    
    keyboard = [
        ["📅 افزایش روز اشتراک", "🔄 تنظیم تاریخ شروع"],
        ["🔛 فعال‌سازی CIP", "📡 فعال‌سازی Hotline"],
        ["🔘 غیرفعال‌سازی CIP", "📴 غیرفعال‌سازی Hotline"],
        ["🔙 بازگشت"]
    ]
    
    await update.message.reply_text(
        f"ویرایش اشتراک برای کاربر: {phone}",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return EDIT_SUBSCRIPTION

async def handle_subscription_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    action = update.message.text
    user_id = context.user_data.get("edit_user_id")
    phone = context.user_data.get("edit_user_phone")
    
    if not user_id or not phone:
        await update.message.reply_text("❌ خطا در ویرایش کاربر")
        return await show_admin_dashboard(update, context)
    
    user = users_data.get(user_id)
    if not user:
        await update.message.reply_text("❌ کاربر یافت نشد")
        return await show_admin_dashboard(update, context)
    
    if action == "📅 افزایش روز اشتراک":
        await update.message.reply_text("لطفاً تعداد روزهای اشتراک را وارد کنید:")
        context.user_data["edit_action"] = "add_days"
        return EDIT_SUBSCRIPTION
    
    elif action == "🔄 تنظیم تاریخ شروع":
        await update.message.reply_text("لطفاً تاریخ شروع را به فرمت YYYY-MM-DD وارد کنید:")
        context.user_data["edit_action"] = "set_start_date"
        return EDIT_SUBSCRIPTION
    
    elif action == "🔛 فعال‌سازی CIP":
        user["CIP"] = True
        await update_user_in_sheet(user)
        users_data[user_id] = user
        save_data(users_data)
        await update.message.reply_text("✅ دسترسی CIP فعال شد")
        return await show_admin_dashboard(update, context)
    
    elif action == "📡 فعال‌سازی Hotline":
        user["Hotline"] = True
        await update_user_in_sheet(user)
        users_data[user_id] = user
        save_data(users_data)
        await update.message.reply_text("✅ دسترسی Hotline فعال شد")
        return await show_admin_dashboard(update, context)
    
    elif action == "🔘 غیرفعال‌سازی CIP":
        user["CIP"] = False
        await update_user_in_sheet(user)
        users_data[user_id] = user
        save_data(users_data)
        await update.message.reply_text("❌ دسترسی CIP غیرفعال شد")
        return await show_admin_dashboard(update, context)
    
    elif action == "📴 غیرفعال‌سازی Hotline":
        user["Hotline"] = False
        await update_user_in_sheet(user)
        users_data[user_id] = user
        save_data(users_data)
        await update.message.reply_text("❌ دسترسی Hotline غیرفعال شد")
        return await show_admin_dashboard(update, context)
    
    elif action == "🔙 بازگشت":
        return await show_admin_dashboard(update, context)

async def handle_edit_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    value = update.message.text
    action = context.user_data.get("edit_action")
    user_id = context.user_data.get("edit_user_id")
    
    if not user_id or not action:
        await update.message.reply_text("❌ خطا در پردازش")
        return await show_admin_dashboard(update, context)
    
    user = users_data.get(user_id)
    if not user:
        await update.message.reply_text("❌ کاربر یافت نشد")
        return await show_admin_dashboard(update, context)
    
    if action == "add_days":
        try:
            days = int(value)
            # اگر کاربر قبلاً اشتراک نداشته (تاریخ شروع ندارد) یا اشتراکش تمام شده، تاریخ شروع را امروز قرار بده
            if not user.get("subscription_start") or user.get("days_left", 0) <= 0:
                user["subscription_start"] = datetime.utcnow().date().isoformat()
            
            user["subscription_days"] = max(0, user.get("subscription_days", 0) + days)
            
            # محاسبه days_left
            start_date = datetime.strptime(user["subscription_start"], "%Y-%m-%d").date()
            today = datetime.utcnow().date()
            days_passed = (today - start_date).days
            user["days_left"] = max(0, user["subscription_days"] - days_passed)
            
            # ریست کردن هشدارهای ارسال شده
            user["last_alert_sent"] = None
            
            await update.message.reply_text(f"✅ {days} روز به اشتراک کاربر اضافه شد")
        except ValueError:
            await update.message.reply_text("❌ تعداد روز باید عدد باشد")
    
    elif action == "set_start_date":
        try:
            # بررسی فرمت تاریخ
            datetime.strptime(value, "%Y-%m-%d")
            user["subscription_start"] = value
            
            # محاسبه days_left
            start_date = datetime.strptime(value, "%Y-%m-%d").date()
            today = datetime.utcnow().date()
            days_passed = (today - start_date).days
            user["days_left"] = max(0, user.get("subscription_days", 0) - days_passed)
            
            # ریست کردن هشدارهای ارسال شده
            user["last_alert_sent"] = None
            
            await update.message.reply_text(f"✅ تاریخ شروع اشتراک به {value} تنظیم شد")
        except ValueError:
            await update.message.reply_text("❌ فرمت تاریخ نامعتبر. لطفاً از فرمت YYYY-MM-DD استفاده کنید")
    
    # به‌روزرسانی در گوگل شیت
    await update_user_in_sheet(user)
    
    # به‌روزرسانی داده‌های محلی
    users_data[user_id] = user
    save_data(users_data)
    
    return await show_admin_dashboard(update, context)

async def sync_all_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """همگام‌سازی تمام داده‌ها با گوگل شیت"""
    count = 0
    for user_id, user_data in users_data.items():
        if await update_user_in_sheet(user_data):
            count += 1
    
    await update.message.reply_text(f"✅ {count} کاربر با گوگل شیت همگام‌سازی شدند")
    return ADMIN_ACTION

async def admin_logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "شما از پنل ادمین خارج شدید.",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

# —————————————————————————————————————————————————————————————————————
# بخش هشتم: اخبار اقتصادی فارکس
# —————————————————————————————————————————————————————————————————————
async def economic_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    news_sources = [
        "📰 منابع خبری و تقویم اقتصادی فارکس:",
        "• Forex Factory (تقویم اقتصادی): https://www.forexfactory.com/",
        "• Investing.com: https://www.investing.com/economic-calendar/",
        "• DailyFX: https://www.dailyfx.com/economic-calendar",
        "• FXStreet: https://www.fxstreet.com/economic-calendar",
        "• Babypips: https://www.babypips.com/economic-calendar",
        "• خبرگزاری فارس (بخش اقتصاد): https://www.farsnews.ir/economy",
        "• بورس نیوز (اخبار فارکس): https://www.boursenews.ir/tag/فارکس"
    ]
    
    await update.message.reply_text("\n".join(news_sources))

# —————————————————————————————————————————————————————————————————————
# بخش نهم: سایر دستورات
# —————————————————————————————————————————————————————————————————————
async def buy_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💳 برای خرید اشتراک لطفاً با پشتیبانی تماس بگیرید.\n"
        f"📞 آیدی پشتیبانی: {SUPPORT_ID}"
    )

async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"👨‍💻 برای پشتیبانی لطفاً به آیدی زیر پیام دهید:\n{SUPPORT_ID}")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = str(update.effective_user.id)
    user = users_data.get(user_id)
    
    if not user:
        await update.message.reply_text("⚠️ لطفاً ابتدا احراز هویت کنید (/start).")
        return
    
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

# —————————————————————————————————————————————————————————————————————
# بخش دهم: وب‌سرور و راه‌اندازی اصلی (اصلاح شده)
# —————————————————————————————————————————————————————————————————————
async def handle_root(request):
    return web.Response(text="Bot is running")

async def health_check(request):
    return web.Response(text="OK", status=200)

async def run_webserver():
    app_http = web.Application()
    app_http.router.add_get("/", handle_root)
    app_http.router.add_get("/health", health_check)
    runner = web.AppRunner(app_http)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logging.info(f"🌐 Web server listening on port {PORT}")

# اجرای اصلی
async def main():
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO
    )
    logging.info("🚀 Starting bot...")

    asyncio.create_task(run_webserver())

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # تعریف ConversationHandler برای پنل ادمین
    admin_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("admin", admin_login)],
        states={
            ADMIN_LOGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_password)],
            ADMIN_ACTION: [
                MessageHandler(filters.Regex("^👥 لیست کاربران$"), list_users),
                MessageHandler(filters.Regex("^✏️ ویرایش اشتراک$"), edit_subscription_start),
                MessageHandler(filters.Regex("^🔄 همگام‌سازی داده‌ها$"), sync_all_data),
                MessageHandler(filters.Regex("^🔙 خروج$"), admin_logout),
            ],
            SELECT_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_selection)],
            EDIT_SUBSCRIPTION: [
                MessageHandler(filters.Regex("^(📅 افزایش روز اشتراک|🔄 تنظیم تاریخ شروع|🔛 فعال‌سازی CIP|📡 فعال‌سازی Hotline|🔘 غیرفعال‌سازی CIP|📴 غیرفعال‌سازی Hotline|🔙 بازگشت)$"), handle_subscription_edit),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_value)
            ]
        },
        fallbacks=[CommandHandler("admin", admin_login)]
    )
    
    # اضافه کردن تمام هندلرهای ربات
    app.add_handler(admin_conv_handler)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(asset_selection_menu, pattern=r"^period\|"))
    app.add_handler(CallbackQueryHandler(asset_selected, pattern=r"^asset\|"))
    app.add_handler(CallbackQueryHandler(analysis_restart, pattern=r"^analysis\|restart"))
    
    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    async def alert_loop():
        await asyncio.sleep(10)
        while True:
            try:
                await check_alerts(app)
            except Exception as e:
                logging.error(f"خطا در حلقه هشدار قیمت: {e}")
            await asyncio.sleep(ALERT_INTERVAL_SECONDS)
    
    async def subscription_alert_loop():
        await asyncio.sleep(30)
        while True:
            try:
                await check_subscription_alerts(app)
            except Exception as e:
                logging.error(f"خطا در حلقه هشدار اشتراک: {e}")
            await asyncio.sleep(6 * 3600)  # هر ۶ ساعت یکبار اجرا شود

    asyncio.create_task(alert_loop())
    asyncio.create_task(subscription_alert_loop())
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
