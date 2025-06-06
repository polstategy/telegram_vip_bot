# main.py — ربات تلگرام جامع با قابلیت‌های VIP و تحلیل بازار
# -------------------------------------------------------------
# ویژگی‌ها:
# 1. احراز هویت با شماره موبایل (ارسال شماره با دکمه تماس)
# 2. ثبت نام با نام و نام خانوادگی
# 3. ذخیره‌سازی اطلاعات کاربر در فایل محلی (JSON) و Google Sheets (برای اشتراک)
# 4. بررسی اشتراک با Google Sheets (Web App) و محاسبه روزهای باقی‌مانده
# 5. ساخت لینک عضویت موقت ۱۰ دقیقه‌ای برای کانال VIP (محدودیت ۵ بار در روز)
# 6. حذف خودکار کاربر از کانال پس از اتمام اشتراک
# 7. منوی کامل با گزینه‌های:
#    📥 عضویت   📅 اشتراک من   🔑 ورود به کانال   💳 خرید اشتراک   🛟 پشتیبانی   📊 تحلیل بازار
# 8. تحلیل بازار (انس طلا، جفت‌ارزها، داوجونز، نزدک، شاخص دلار) برای دوره‌های:
#    هفته گذشته، ماه گذشته، سه‌ماهه گذشته، شش‌ماهه گذشته
# 9. محاسبه سطوح M1–M7، Z1، U1–U30، D1–D30 و هشدار لحظه‌ای در صورت رسیدن قیمت به هر سطح
# 10. ذخیره هشدارهای ارسال‌شده برای جلوگیری از ارسال تکراری
# -------------------------------------------------------------


import logging
import json
import os
from datetime import datetime, timedelta
import asyncio
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

# -------------------------------------------------------------
# ==== تنظیمات اصلی ====

# 1) توکن ربات تلگرام
BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"

# 2) آیدی عددی کانال VIP (برای حذف خودکار اعضا)
#    برای بدست آوردن آیدی عددی از ربات @userinfobot استفاده کنید.
CHANNEL_ID = -1001234567890

# 3) یوزرنیم کانال VIP (فقط برای نمایش لینک ثابت اگر بخواهید)
CHANNEL_USERNAME = "@your_channel_username"

# 4) لینک ثابت دعوت (برای نمایش در منوی خرید اشتراک یا راهنما)
#    (در تولید لینک موقت از API استفاده می‌شود)
CHANNEL_INVITE_STATIC = "https://t.me/+QYggjf71z9lmODVl"

# 5) آیدی پشتیبانی (برای نمایش در منوی پشتیبانی)
SUPPORT_ID = "@your_support_id"

# 6) آدرس Google Apps Script Web App برای ذخیره و خواندن اشتراک:
#    این Web App باید دو endpoint داشته باشد:
#      • GET?phone=<phone> → { "status": "found"/"not_found", "days_left": int }
#      • POST JSON { "action":"register", "phone":..., "name":..., "family":... } → ثبت نام اولیه
GOOGLE_SHEET_URL = "https://script.google.com/macros/s/YOUR_SCRIPT_ID/exec"

# 7) کلید API برای دریافت داده‌های قیمت از TwelveData
TWELVE_API_KEY = "YOUR_TWELVE_DATA_API_KEY"

# 8) فایل محلی برای ذخیره‌سازی اطلاعات کاربران و لینک‌های موقت
DATA_FILE = "user_data.json"

# 9) تنظیمات لینک موقت کانال
LINK_EXPIRE_MINUTES = 10   # مدت اعتبار لینک (دقیقه)
MAX_LINKS_PER_DAY = 5      # حداکثر تعداد لینک درخواست‌شده در هر روز

# 10) تنظیمات هشدار قیمت
ALERT_INTERVAL_SECONDS = 300  # هر ۵ دقیقه یکبار قیمت و سطوح را چک کن

# -------------------------------------------------------------


# —————————————————————————————————————————————————————————————————————
# بخش اول: بارگذاری و ذخیره اطلاعات کاربران (محلی - JSON)
# —————————————————————————————————————————————————————————————————————

def load_data():
    """
    خواندن فایل DATA_FILE و برگرداندن دیکشنری اطلاعات کاربران.
    ساختار داده:
    {
        "<user_id>": {
            "phone": "09123456789",
            "name": "Ali",
            "family": "Rezaei",
            "registered_at": "2024-06-01T12:34:56",
            "expire_date": "2024-12-01",
            "links": {
                "2024-06-05": 3,  # تعداد لینک ساخته‌شده در 2024-06-05
                ...
            },
            "alerts": [   # هشدارهای ارسال‌شده (کلیدهای سطح) برای جلوگیری از تکرار
                "1800.50",
                ...
            ],
            "watch_assets": [  # لیستی از دارایی‌ها و دوره‌ها برای رصد هشدارها
                {
                    "symbol": "XAU/USD",
                    "period": "weekly",
                    "last_processed": "2024-06-05T12:00:00"
                },
                ...
            ]
        },
        ...
    }
    """
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_data(data):
    """ذخیره دیکشنری data در فایل DATA_FILE"""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# بارگذاری اولیه
users_data = load_data()

# —————————————————————————————————————————————————————————————————————
# بخش دوم: دستورات عمومی ربات (/start و منوها)
# —————————————————————————————————————————————————————————————————————

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    هنگام /start:
    • درخواست ارسال شماره موبایل با دکمه CONTACT
    """
    keyboard = [[KeyboardButton("تایید و احراز هویت", request_contact=True)]]
    await update.message.reply_text(
        "👋 سلام! برای ادامه لطفاً شماره موبایل خود را ارسال کنید:",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True),
    )

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    پس از ارسال شماره موبایل:
    • ذخیره نام، نام خانوادگی (از اطلاعات پروفایل Telegram) و شماره موبایل
    • ثبت در Google Sheet (POST با action=register)
    • نمایش منوی اصلی ربات
    """
    contact = update.message.contact
    user_id = str(update.effective_user.id)
    phone = contact.phone_number

    # در صورت ارسال +98 به 0 تبدیل شود
    if phone.startswith("+98"):
        phone = "0" + phone[3:]
    elif phone.startswith("0098"):
        phone = "0" + phone[4:]

    first_name = update.effective_user.first_name or ""
    last_name = update.effective_user.last_name or ""

    # ارسال POST برای ثبت اولیه در Google Sheet
    try:
        payload = {
            "action": "register",
            "phone": phone,
            "name": first_name,
            "family": last_name
        }
        requests.post(GOOGLE_SHEET_URL, json=payload, timeout=10)
    except Exception as e:
        logging.error(f"خطا در ثبت اولیه Google Sheet: {e}")

    # ذخیره محلی
    users_data[user_id] = {
        "phone": phone,
        "name": first_name,
        "family": last_name,
        "registered_at": datetime.utcnow().isoformat(),
        "expire_date": "",          # بعد از دریافت از Google Sheet پر می‌شود
        "links": {},                # شمارش لینک‌ها برای هر روز
        "alerts": [],               # کلیدهای هشدارهای ارسالی
        "watch_assets": []          # لیست دارایی‌ها برای هشدار
    }
    save_data(users_data)

    # نمایش منوی اصلی
    await show_main_menu(update, context)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    نمایش منوی اصلی ربات با گزینه‌های:
    📥 عضویت   📅 اشتراک من   🔑 ورود به کانال   📊 تحلیل بازار   💳 خرید اشتراک   🛟 پشتیبانی
    """
    keyboard = [
        ["📅 اشتراک من", "🔑 ورود به کانال"],
        ["💳 خرید اشتراک", "🛟 پشتیبانی"],
        ["📊 تحلیل بازار"]
    ]
    await update.message.reply_text(
        "از منوی زیر یکی را انتخاب کنید:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
    )

# —————————————————————————————————————————————————————————————————————
# بخش سوم: مدیریت اشتراک و تاریخ انقضا
# —————————————————————————————————————————————————————————————————————

async def show_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    • بررسی اشتراک فعلی از Google Sheet (GET?phone=...)
    • نمایش روزهای باقی‌مانده یا پیام عدم اشتراک
    """
    user_id = str(update.effective_user.id)
    user = users_data.get(user_id)
    if not user:
        await update.message.reply_text("⚠️ لطفاً ابتدا احراز هویت کنید (/start).")
        return

    phone = user["phone"]
    try:
        response = requests.get(f"{GOOGLE_SHEET_URL}?phone={phone}", timeout=10)
        info = response.json()
    except Exception as e:
        logging.error(f"خطا در دریافت اطلاعات اشتراک: {e}")
        await update.message.reply_text("⚠️ خطا در بررسی اشتراک. لطفاً بعداً تلاش کنید.")
        return

    if info.get("status") == "found":
        days_left = int(info.get("days_left", 0))
        expire_date = (
            datetime.utcnow().date() + timedelta(days=days_left)
        ).isoformat()
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
    """
    • چک اشتراک (expire_date)
    • بررسی تعداد لینک‌های درخواست‌شده در امروز
    • ایجاد لینک موقت با create_chat_invite_link
    • ذخیره لینک و timestamp و افزایش شمارش برای امروز
    """
    user_id = str(update.effective_user.id)
    user = users_data.get(user_id)
    if not user:
        await update.message.reply_text("⚠️ ابتدا احراز هویت کنید (/start).")
        return

    # بررسی انقضای اشتراک
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
    user.setdefault("last_link", {})["link"] = invite_link
    user["last_link"]["timestamp"] = datetime.utcnow().isoformat()
    save_data(users_data)

    # ارسال پیام لینک به کاربر
    await update.message.reply_text(
        f"📎 لینک عضویت (۱۰ دقیقه اعتبار):\n{invite_link}\n\n"
        "✅ لطفا از لینک بالا برای ورود به کانال VIP استفاده کنید.\n"
        f"⚠️ محدودیت: فقط {MAX_LINKS_PER_DAY} لینک در روز.\n"
    )

# —————————————————————————————————————————————————————————————————————
# بخش پنجم: تحلیل بازار (انس طلا و سایر دارایی‌ها) + منوی انتخاب دارایی
# —————————————————————————————————————————————————————————————————————

# لیست دارایی‌های پشتیبانی‌شده (symbol بر مبنای API TwelveData)
ASSETS = {
    "INS": "XAU/USD",        # انس طلا
    "EURUSD": "EUR/USD",     # یورو/دلار
    "GBPUSD": "GBP/USD",     # پوند/دلار
    "USDJPY": "USD/JPY",     # دلار/ین
    "DXY": "DXY",            # شاخص دلار
    "DJI": "DJI",            # شاخص داوجونز
    "NAS100": "NASDAQ"       # شاخص نزدک 100
}

# لیست دوره‌های زمانی مجاز
PERIODS = {
    "هفتگی": "weekly",
    "ماهانه": "monthly",
    "سه‌ماهه": "quarterly",
    "شش‌ماهه": "semiannual"
}

# ذخیره‌سازی انتخاب دارایی توسط کاربر در context.user_data
# کلید context.user_data["analysis"] = { "symbol":..., "period":... }

async def analysis_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    وقتی کاربر «📊 تحلیل بازار» را می‌فشارد:
    • نمایش منوی انتخاب دوره (هفتگی، ماهانه، سه‌ماهه، شش‌ماهه)
    """
    kb = [
        [InlineKeyboardButton(per, callback_data=f"period|{period}")]
        for per, period in PERIODS.items()
    ]
    kb.append([InlineKeyboardButton("بازگشت به منو", callback_data="back")])
    await update.message.reply_text(
        "لطفاً دوره زمانی مورد نظر را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(kb),
    )

async def asset_selection_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    وقتی کاربر دوره را انتخاب می‌کند (callback با data = "period|<period>"):
    • ذخیره دوره در context.user_data["analysis"]["period"]
    • نمایش منو انتخاب دارایی
    """
    query = update.callback_query
    await query.answer()
    data_cb = query.data  # مانند "period|weekly"
    _, period = data_cb.split("|", 1)
    context.user_data["analysis"] = {"period": period}

    kb = [
        [InlineKeyboardButton(name, callback_data=f"asset|{symbol}")]
        for name, symbol in ASSETS.items()
    ]
    kb.append([InlineKeyboardButton("بازگشت", callback_data="analysis|restart")])
    await query.edit_message_text(
        "لطفاً دارایی مورد نظر را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(kb),
    )

async def asset_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    وقتی کاربر دارایی را انتخاب می‌کند (callback با data="asset|<symbol>"):
    • ذخیره symbol در context.user_data["analysis"]
    • فراخوانی تابع get_gold_data یا get_asset_data برای محاسبه سطوح
    • نمایش نتایج محاسبات
    • افزودن این دارایی و دوره به لیست watch_assets کاربر برای هشدار لحظه‌ای
    """
    query = update.callback_query
    await query.answer()
    data_cb = query.data  # مانند "asset|XAU/USD"
    _, symbol = data_cb.split("|", 1)
    context.user_data["analysis"]["symbol"] = symbol

    period = context.user_data["analysis"]["period"]

    # فراخوانی تابع دریافت داده‌ها
    asset_data = await get_asset_data(symbol, period)
    if not asset_data:
        await query.edit_message_text("⚠️ خطا در دریافت داده‌ها، لطفا بعدا تلاش کنید.")
        return

    # ساخت پیام نتیجه محاسبات
    msg = f"📊 تحلیل {symbol} برای دوره {period}:\n"
    msg += f"High: {asset_data['H']:.2f}\nLow: {asset_data['L']:.2f}\nClose: {asset_data['C']:.2f}\n\n"
    msg += f"M1: {asset_data['M1']:.2f}, M2: {asset_data['M2']:.2f}, M3: {asset_data['M3']:.2f}, M4: {asset_data['M4']:.2f}\n"
    msg += f"M5: {asset_data['M5']:.2f}, M6: {asset_data['M6']:.2f}, M7: {asset_data['M7']:.2f}\n"
    msg += f"Z1: {asset_data['Z1']:.2f}\nPip: {asset_data['pip']:.4f}\n\n"
    msg += "مقاومت‌ها (U1-U5): " + ", ".join(f"{u:.2f}" for u in asset_data["U"][:5]) + "\n"
    msg += "حمایت‌ها (D1-D5): " + ", ".join(f"{d:.2f}" for d in asset_data["D"][:5]) + "\n\n"
    msg += "🔔 هشدار لحظه‌ای فعال شد. اگر قیمت به سطوح برخورد کند، به شما اطلاع داده می‌شود."

    await query.edit_message_text(msg)

    # اضافه کردن به لیست watch_assets کاربر
    user_id = str(update.effective_user.id)
    user = users_data.get(user_id)
    if user is not None:
        watch_list = user.setdefault("watch_assets", [])
        # برای جلوگیری از تکرار بررسی، اول چک کنیم آیا وجود دارد یا نه
        exists = any(w["symbol"] == symbol and w["period"] == period for w in watch_list)
        if not exists:
            watch_list.append({
                "symbol": symbol,
                "period": period,
                "last_processed": datetime.utcnow().isoformat()
            })
            save_data(users_data)

async def analysis_restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    وقتی کاربر «بازگشت» را می‌زند در منوی تحلیل:
    برگشت به منوی اصلی یا شروع مجدد انتخاب دوره
    """
    query = update.callback_query
    await query.answer()
    # شروع مجدد فرایند انتخاب دوره
    await analysis_menu(update, context)

# —————————————————————————————————————————————————————————————————————
# بخش ششم: دریافت داده‌های یک دارایی خاص (اعم از انس طلا یا جفت‌ارز و شاخص)
# —————————————————————————————————————————————————————————————————————

async def get_asset_data(symbol: str, period: str):
    """
    • استفاده از API TwelveData برای دریافت کندل‌های دوره‌ای یک ابزار مالی
    • محاسبه H, L, C از کندل‌های دوره انتخاب‌شده
    • محاسبه سطوح M1–M7، Z1، Pip، و U[1..30], D[1..30]
    • برگرداندن یک دیکشنری با کلیدهای بالا
    """

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

    # ساخت URL بر اساس TwelveData
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
        "H": H, "L": L, "C": C,
        "M1": M1, "M2": M2, "M3": M3, "M4": M4,
        "M5": M5, "M6": M6, "M7": M7,
        "Z1": Z1, "pip": pip,
        "U": U, "D": D
    }

async def get_current_price(symbol: str):
    """
    • دریافت قیمت لحظه‌ای یک ابزار مالی از TwelveData
    """
    url = f"https://api.twelvedata.com/price?symbol={symbol}&apikey={TWELVE_API_KEY}"
    try:
        resp = requests.get(url, timeout=10).json()
        return float(resp.get("price", 0))
    except:
        return None

# —————————————————————————————————————————————————————————————————————
# بخش هفتم: هشدار لحظه‌ای قیمت برای تمام کاربران فعال
# —————————————————————————————————————————————————————————————————————

async def check_alerts(context: ContextTypes.DEFAULT_TYPE):
    """
    هر دوره (مثلاً هر 5 دقیقه) اجرا می‌شود:
    • برای هر کاربر ذخیره‌شده:
        – لیست watch_assets را بگیر
        – برای هر (symbol, period):
            · محاسبه مجدد سطوح با get_asset_data
            · دریافت قیمت لحظه‌ای با get_current_price
            · بررسی فاصله قیمت تا هر سطح ( if abs(price-level)< pip/10 )
            · اگر هشدار جدیدی باشد (عدم وجود کلید در SENT_ALERTS[user_id] ), ارسال پیام
    • ارسال پیام به user_id مربوطه
    • ذخیره کلید هشدار در users_data[user_id]["alerts"]
    """
    global users_data

    for user_id, user in users_data.items():
        if "watch_assets" not in user:
            continue
        phone = user.get("phone")
        exp_str = user.get("expire_date", "")
        if not exp_str or datetime.utcnow().date() > datetime.fromisoformat(exp_str).date():
            # حذف خودکار کاربر از کانال پس از اتمام اشتراک
            try:
                await context.bot.ban_chat_member(chat_id=CHANNEL_ID, user_id=int(user_id))
                await context.bot.unban_chat_member(chat_id=CHANNEL_ID, user_id=int(user_id))
            except:
                pass
            continue

        for wa in user["watch_assets"]:
            symbol = wa["symbol"]
            period = wa["period"]
            last_proc = datetime.fromisoformat(wa.get("last_processed"))
            # برای جلوگیری از پردازش بیش از حد می‌توان شرطی اضافه کرد، اما ما هر بار کامل پردازش می‌کنیم.
            asset_data = await get_asset_data(symbol, period)
            if not asset_data:
                continue
            price = await get_current_price(symbol)
            if price is None:
                continue

            pip = asset_data["pip"]
            levels = [
                asset_data["M1"], asset_data["M2"], asset_data["M3"], asset_data["M4"],
                asset_data["M5"], asset_data["M6"], asset_data["M7"], asset_data["Z1"]
            ] + asset_data["U"] + asset_data["D"]

            for level in levels:
                key = f"{symbol}_{period}_{round(level,2)}"
                if key in user["alerts"]:
                    continue
                if abs(price - level) < pip / 10:
                    # ارسال پیام هشدار به کاربر
                    try:
                        await context.bot.send_message(
                            chat_id=int(user_id),
                            text=f"⚠️ قیمت {symbol} به سطح مهم {round(level,2)} رسید.\nقیمت فعلی: {price:.2f}"
                        )
                        user["alerts"].append(key)
                        save_data(users_data)
                    except Exception as e:
                        logging.error(f"خطا در ارسال هشدار به {user_id}: {e}")

            # به‌روز کردن last_processed
            wa["last_processed"] = datetime.utcnow().isoformat()

        save_data(users_data)

# —————————————————————————————————————————————————————————————————————
# بخش هشتم: هندلر پیام‌های متنی منو
# —————————————————————————————————————————————————————————————————————

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "📅 اشتراک من":
        await my_subscription(update, context)
    elif text == "📥 ورود به کانال":
        await join_channel(update, context)
    elif text == "💳 خرید اشتراک":
        await buy_subscription(update, context)
    elif text == "👨‍💻 پشتیبانی":
        await support(update, context)
    elif text == "📊 تحلیل بازار":
        await analysis_menu(update, context)
    else:
        await update.message.reply_text("⚠️ لطفاً از منوی اصلی یک گزینه را انتخاب کنید.")

# هنگام callback query های منوی تحلیل:
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
# بخش نهم: تابع اصلی — بارگذاری ربات، هندلرها، JobQueue
# —————————————————————————————————————————————————————————————————————

def main():
    logging.info("🚀 Bot is starting...")
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # هندلرها
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.CONTACT, contact_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    application.add_handler(CallbackQueryHandler(callback_query_handler))

    # JobQueue برای هشدار قیمت — هر ALERT_INTERVAL_SECONDS ثانیه
    application.job_queue.run_repeating(check_alerts, interval=ALERT_INTERVAL_SECONDS, first=10)

    application.run_polling()

if __name__ == "__main__":
    main()
