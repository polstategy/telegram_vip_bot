# main.py — ربات تلگرام با پنل ادمین و مدیریت اشتراک
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

# -------------------------------------------------------------
# ==== تنظیمات اصلی ====
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")  # رمز عبور پیشفرض ادمین

# تنظیمات کانال‌ها
try:
    CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "0"))
    CIP_CHANNEL_ID = int(os.environ.get("CIP_CHANNEL_ID", "0"))
except ValueError:
    logging.error("خطا در ID کانال‌ها!")
    exit(1)

CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "@your_channel_username")
SUPPORT_ID = os.environ.get("SUPPORT_ID", "@your_support_id")
GOOGLE_SHEET_URL = os.environ.get(
    "GOOGLE_SHEET_URL",
    "https://script.google.com/macros/s/YOUR_SCRIPT_ID/exec"
)
TWELVE_API_KEY = os.environ.get("TWELVE_API_KEY", "")

# تنظیمات فایل داده‌ها
DATA_FILE = "user_data.json"
LINK_EXPIRE_MINUTES = 10
MAX_LINKS_PER_DAY = 5
ALERT_INTERVAL_SECONDS = 300

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
        except:
            return {}
    return {}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

users_data = load_data()

# —————————————————————————————————————————————————————————————————————
# بخش دوم: ارتباط با Google Sheet
# —————————————————————————————————————————————————————————————————————

def normalize_phone(phone):
    """نرمال‌سازی شماره تلفن"""
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
            "action": "update_user",
            "phone": user_data["phone"],
            "name": user_data.get("name", ""),
            "days": user_data.get("subscription_days", 0),
            "start_date": user_data.get("subscription_start", ""),
            "days_left": user_data.get("days_left", 0),
            "CIP": "T" if user_data.get("CIP", False) else "F",
            "Hotline": "T" if user_data.get("Hotline", False) else "F"
        }
        response = requests.post(GOOGLE_SHEET_URL, json=payload, timeout=30)
        return response.status_code == 200
    except Exception as e:
        logging.error(f"خطا در به‌روزرسانی Google Sheet: {e}")
        return False

async def get_user_from_sheet(phone):
    """دریافت اطلاعات کاربر از Google Sheet"""
    try:
        phone = normalize_phone(phone)
        response = requests.get(f"{GOOGLE_SHEET_URL}?phone={phone}", timeout=30)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        logging.error(f"خطا در دریافت اطلاعات از Google Sheet: {e}")
    return None

async def sync_user_data(user_id, user_data):
    """همگام‌سازی داده‌های کاربر بین سیستم و Google Sheet"""
    # همیشه اول از گوگل شیت اطلاعات را بگیر
    sheet_data = await get_user_from_sheet(user_data["phone"])
    
    if sheet_data and sheet_data.get("status") == "found":
        # به‌روزرسانی داده‌ها از گوگل شیت
        user_data["CIP"] = sheet_data.get("CIP", "F") == "T"
        user_data["Hotline"] = sheet_data.get("Hotline", "F") == "T"
        user_data["subscription_days"] = int(sheet_data.get("days", 0))
        user_data["subscription_start"] = sheet_data.get("start_date", "")
        
        # محاسبه days_left
        if user_data["subscription_start"]:
            start_date = datetime.strptime(user_data["subscription_start"], "%Y-%m-%d").date()
            today = datetime.utcnow().date()
            days_passed = (today - start_date).days
            user_data["days_left"] = max(0, user_data["subscription_days"] - days_passed)
        else:
            user_data["days_left"] = 0
            
        # ذخیره محلی
        users_data[user_id] = user_data
        save_data(users_data)
    else:
        # اگر کاربر در گوگل شیت وجود ندارد، آن را اضافه کن
        await update_user_in_sheet(user_data)
    
    return user_data

# —————————————————————————————————————————————————————————————————————
# بخش سوم: احراز هویت و منوی اصلی
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
        "days_left": 0
    }
    
    # همگام‌سازی با گوگل شیت
    user_data = await sync_user_data(user_id, user_data)
    
    # نمایش منوی اصلی
    await show_main_menu(update, context, user_data)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, user_data):
    """نمایش منوی اصلی بر اساس سطح دسترسی کاربر"""
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
    
    await update.message.reply_text(
        "از منوی زیر یکی را انتخاب کنید:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
    )

# —————————————————————————————————————————————————————————————————————
# بخش چهارم: مدیریت اشتراک‌ها
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
            start_date = datetime.strptime(user["subscription_start"], "%Y-%m-%d").date()
            expire_date = (start_date + timedelta(days=user["subscription_days"])).isoformat()
        
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
# بخش پنجم: دسترسی به کانال‌ها
# —————————————————————————————————————————————————————————————————————

async def generate_invite_link(context, chat_id, expire_minutes=10):
    """تولید لینک دعوت موقت"""
    try:
        res = await context.bot.create_chat_invite_link(
            chat_id=chat_id,
            expire_date=int((datetime.utcnow() + timedelta(minutes=expire_minutes)).timestamp()),
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
    
    # ارسال لینک
    await update.message.reply_text(
        f"🔑 لینک دسترسی به کانال (۱۰ دقیقه اعتبار):\n{invite_link}\n\n"
        f"⚠️ محدودیت: فقط {MAX_LINKS_PER_DAY} لینک در روز"
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
    
    # ارسال لینک
    await update.message.reply_text(
        f"🌐 لینک دسترسی به کانال CIP (۱۰ دقیقه اعتبار):\n{invite_link}\n\n"
        f"⚠️ محدودیت: فقط {MAX_LINKS_PER_DAY} لینک در روز"
    )

# —————————————————————————————————————————————————————————————————————
# بخش ششم: تحلیل بازار (فقط برای کاربران Hotline)
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

# بقیه توابع تحلیل بازار مانند قبل...

# —————————————————————————————————————————————————————————————————————
# بخش هفتم: پنل مدیریت ادمین
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
    message = "📋 لیست کاربران:\n\n"
    for user_id, data in users_data.items():
        phone = data.get("phone", "نامشخص")
        name = data.get("name", "بدون نام")
        days_left = data.get("days_left", 0)
        cip = "✅" if data.get("CIP", False) else "❌"
        hotline = "✅" if data.get("Hotline", False) else "❌"
        
        message += (
            f"📱: {phone}\n"
            f"👤: {name}\n"
            f"⏳: {days_left} روز\n"
            f"CIP: {cip} | Hotline: {hotline}\n"
            f"───────────────────\n"
        )
    
    await update.message.reply_text(message[:4000])  # محدودیت طول پیام

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
        await update.message.reply_text("✅ دسترسی CIP فعال شد")
    
    elif action == "📡 فعال‌سازی Hotline":
        user["Hotline"] = True
        await update_user_in_sheet(user)
        await update.message.reply_text("✅ دسترسی Hotline فعال شد")
    
    elif action == "🔘 غیرفعال‌سازی CIP":
        user["CIP"] = False
        await update_user_in_sheet(user)
        await update.message.reply_text("❌ دسترسی CIP غیرفعال شد")
    
    elif action == "📴 غیرفعال‌سازی Hotline":
        user["Hotline"] = False
        await update_user_in_sheet(user)
        await update.message.reply_text("❌ دسترسی Hotline غیرفعال شد")
    
    # به‌روزرسانی داده‌های محلی
    users_data[user_id] = user
    save_data(users_data)
    
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
            user["subscription_days"] = max(0, user.get("subscription_days", 0) + days)
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
# بخش دهم: وب‌سرور و راه‌اندازی اصلی
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
    port = int(os.environ.get("PORT", "10000"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"🚀 Web server listening on port {port}")

async def main_async():
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO
    )
    logging.info("🚀 Starting bot...")

    # راه‌اندازی وب‌سرور
    asyncio.create_task(run_webserver())

    # تنظیم ربات تلگرام
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # تنظیم handler برای پنل ادمین
    admin_handler = ConversationHandler(
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
    
    # اضافه کردن handlerها
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(admin_handler)
    
    # تحلیل بازار (به صورت ساده شده)
    app.add_handler(CallbackQueryHandler(asset_selection_menu, pattern=r"^period\|"))
    app.add_handler(CallbackQueryHandler(asset_selected, pattern=r"^asset\|"))
    app.add_handler(CallbackQueryHandler(analysis_restart, pattern=r"^analysis\|restart"))
    
    # شروع ربات
    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    # نگه داشتن ربات
    await asyncio.Event().wait()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(main_async())
    loop.run_forever()
