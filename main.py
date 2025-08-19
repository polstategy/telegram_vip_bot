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
    ReplyKeyboardRemove,
    ChatJoinRequest
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
    ConversationHandler,
    ChatJoinRequestHandler
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

# اطلاعات ارتباطی
WEBSITE_URL = os.environ.get("WEBSITE_URL", "https://example.com")
INSTAGRAM_URL = os.environ.get("INSTAGRAM_URL", "https://instagram.com/example")
YOUTUBE_URL = os.environ.get("YOUTUBE_URL", "https://youtube.com/example")

# کدهای تخفیف
DISCOUNT_CODE_10 = os.environ.get("DISCOUNT_CODE_10", "KHZD10")
DISCOUNT_CODE_20 = os.environ.get("DISCOUNT_CODE_20", "KHZD20")

DATA_FILE = "user_data.json"
KEYWORDS_FILE = "keywords.json"
REGISTRATION_OPTIONS_FILE = "registration_options.json"
REGISTRATIONS_FILE = "registrations.json"
LINK_EXPIRE_MINUTES = 10
MAX_LINKS_PER_DAY = 5
ALERT_INTERVAL_SECONDS = 300
SUBSCRIPTION_ALERT_DAYS = 3  # تعداد روزهای مانده به پایان اشتراک برای ارسال هشدار

# مراحل گفتگو برای پنل ادمین
ADMIN_LOGIN, ADMIN_ACTION, SELECT_USER, EDIT_SUBSCRIPTION, EDIT_DISCOUNT, EDIT_KEYWORDS, EDIT_REGISTRATION_OPTIONS = range(7)

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

def load_keywords():
    """بارگذاری کلمات کلیدی از فایل JSON"""
    if os.path.exists(KEYWORDS_FILE):
        try:
            with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"خطا در بارگیری فایل کلمات کلیدی: {e}")
            return {}
    return {}

def save_keywords(keywords):
    """ذخیره کلمات کلیدی در فایل JSON"""
    try:
        with open(KEYWORDS_FILE, "w", encoding="utf-8") as f:
            json.dump(keywords, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logging.error(f"خطا در ذخیره فایل کلمات کلیدی: {e}")
        return False

def load_registration_options():
    """بارگذاری گزینه‌های ثبت‌نام از فایل JSON"""
    if os.path.exists(REGISTRATION_OPTIONS_FILE):
        try:
            with open(REGISTRATION_OPTIONS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"خطا در بارگیری فایل گزینه‌های ثبت‌نام: {e}")
            return []
    return []

def save_registration_options(options):
    """ذخیره گزینه‌های ثبت‌نام در فایل JSON"""
    try:
        with open(REGISTRATION_OPTIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(options, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logging.error(f"خطا در ذخیره فایل گزینه‌های ثبت‌نام: {e}")
        return False

def save_registration(registration_data):
    """ذخیره اطلاعات ثبت‌نام در فایل"""
    try:
        # بارگذاری ثبت‌نام‌های موجود
        registrations = []
        if os.path.exists(REGISTRATIONS_FILE):
            with open(REGISTRATIONS_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        registrations.append(json.loads(line))
        
        # اضافه کردن ثبت‌نام جدید
        registrations.append(registration_data)
        
        # ذخیره تمام ثبت‌نام‌ها
        with open(REGISTRATIONS_FILE, "w", encoding="utf-8") as f:
            for reg in registrations:
                f.write(json.dumps(reg, ensure_ascii=False) + "\n")
        
        return True
    except Exception as e:
        logging.error(f"خطا در ذخیره اطلاعات ثبت‌نام: {e}")
        return False

users_data = load_data()
keywords_data = load_keywords()
registration_options = load_registration_options()

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
            "action": "register",
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

async def send_registration_to_sheet(name, phone, reg_option):
    """ارسال اطلاعات ثبت‌نام به گوگل شیت"""
    try:
        payload = {
            "action": "reg",
            "name": name,
            "phone": phone,
            "reg": reg_option
        }
        logging.info(f"ارسال داده ثبت‌نام به گوگل شیت: {payload}")
        response = requests.post(GOOGLE_SHEET_URL, json=payload, timeout=30)
        logging.info(f"پاسخ گوگل شیت برای ثبت‌نام: {response.status_code} - {response.text}")
        return response.status_code == 200
    except Exception as e:
        logging.error(f"خطا در ارسال ثبت‌نام به Google Sheet: {e}")
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
# بخش جدید: ارسال هشدار اشتراک
# —————————————————————————————————————————————————————————————————————
async def send_subscription_alert(bot, user_id, user_data):
    """ارسال هشدار اتمام اشتراک به کاربر"""
    subscription_types = []
    if user_data.get("CIP", False):
        subscription_types.append("کانال CIP")
    if user_data.get("Hotline", False):
        subscription_types.append("کانال اصلی")
    
    if not subscription_types:
        return
    
    subscription_names = " و ".join(subscription_types)
    message = (
        f"⏳ از زمان اشتراک شما برای {subscription_names} فقط {user_data['days_left']} روز باقی مانده است!\n"
        f"⚠️ لطفاً جهت جلوگیری از حذف دسترسی به کانال‌ها اشتراک خود را تمدید کنید.\n\n"
        f"📞 برای تمدید اشتراک با پشتیبانی تماس بگیرید: {SUPPORT_ID}"
    )
    
    try:
        await bot.send_message(
            chat_id=int(user_id),
            text=message,
            protect_content=True
        )
    except Exception as e:
        logging.error(f"خطا در ارسال هشدار اشتراک به {user_id}: {e}")

# —————————————————————————————————————————————————————————————————————
# بخش دوم: احراز هویت و منوی اصلی (با تغییرات چیدمان)
# —————————————————————————————————————————————————————————————————————
def build_main_menu_keyboard(user_data):
    """تابع کمکی برای ساخت کیبورد منوی اصلی با چیدمان جدید"""
    keyboard = []
    
    # ردیف اول: اشتراک من و تحلیل بازار
    row1 = ["📅 اشتراک من"]
    if user_data.get("Hotline", False) and user_data.get("days_left", 0) > 0:
        row1.append("📊 تحلیل بازار")
    keyboard.append(row1)
    
    # ردیف دوم: دسترسی‌ها
    row2 = []
    if user_data.get("Hotline", False) and user_data.get("days_left", 0) > 0:
        row2.append("🔑 Hotline ورود به کانال")
    if user_data.get("CIP", False) and user_data.get("days_left", 0) > 0:
        row2.append("🌐 ورود به کانال CIP")
    if row2:  # فقط اگر حداقل یک گزینه وجود داشته باشد
        keyboard.append(row2)
    
    # ردیف سوم: گزینه‌های ثبت‌نام (اگر وجود داشته باشد)
    if registration_options:
        for i in range(0, len(registration_options), 2):
            row = registration_options[i:i+2]
            keyboard.append(row)
    
    # ردیف بعدی: خرید اشتراک و پشتیبانی
    keyboard.append(["💳 خرید اشتراک", "🛟 پشتیبانی"])
    
    # ردیف بعدی: اخبار، ارتباط با ما و کد تخفیف
    keyboard.append(["📰 اخبار اقتصادی فارکس", "📞 ارتباط با ما"])
    keyboard.append(["🔰 کد تخفیف پراپفرم ForFx"])
    
    # ردیف آخر: بازگشت به منو
    keyboard.append(["🔙 بازگشت به منو"])
    
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
        "last_alert_sent": None
    }
    
    # همگام‌سازی با گوگل شیت
    user_data = await sync_user_data(user_id, user_data)
    
    # ارسال هشدار اگر اشتراک در حال اتمام است
    if user_data.get("days_left", 0) <= SUBSCRIPTION_ALERT_DAYS:
        await send_subscription_alert(context.bot, user_id, user_data)
    
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
        
        # ارسال هشدار اگر اشتراک در حال اتمام است
        if user['days_left'] <= SUBSCRIPTION_ALERT_DAYS:
            await send_subscription_alert(context.bot, user_id, user)
    else:
        message = "⚠️ شما اشتراک فعالی ندارید."
    
    await update.message.reply_text(message)

# —————————————————————————————————————————————————————————————————————
# بخش چهارم: دسترسی به کانال‌ها (با امنیت افزایشی)
# —————————————————————————————————————————————————————————————————————
async def generate_invite_link(context, chat_id, expire_minutes=10):
    """تولید لینک دعوت با سیستم درخواست عضویت"""
    try:
        expire_timestamp = int((datetime.utcnow() + timedelta(minutes=expire_minutes)).timestamp())
        
        res = await context.bot.create_chat_invite_link(
            chat_id=chat_id,
            expire_date=expire_timestamp,
            creates_join_request=True  # فعال‌سازی سیستم درخواست عضویت
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
    keyboard = [[InlineKeyboardButton("Hotlineورود به کانال", url=invite_link)]]
    await update.message.reply_text(
        f"🔑 لینک دسترسی به کانال (۱۰ دقیقه اعتبار):\n\n"
        f"⚠️ توجه: این لینک فقط برای شما فعال است\n"
        f"⚠️ پس از کلیک، درخواست عضویت شما به صورت خودکار تایید می‌شود\n"
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
    
    # ارسال لینک به صورت دکته اینلاین
    keyboard = [[InlineKeyboardButton("ورود به کانال CIP", url=invite_link)]]
    await update.message.reply_text(
        f"🌐 لینک دسترسی به کانال CIP (۱۰ دقیقه اعتبار):\n\n"
        f"⚠️ توجه: این لینک فقط برای شما فعال است\n"
        f"⚠️ پس از کلیک، درخواست عضویت شما به صورت خودکار تایید می‌شود\n"
        f"⚠️ محدودیت: فقط {MAX_LINKS_PER_DAY} لینک در روز",
        reply_markup=InlineKeyboardMarkup(keyboard),
        protect_content=True  # غیرفعال کردن فوروارد و کپی
    )

# —————————————————————————————————————————————————————————————————————
# بخش جدید: مدیریت درخواست‌های عضویت در کانال
# —————————————————————————————————————————————————————————————————————
async def handle_chat_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت درخواست‌های عضویت در کانال"""
    join_request = update.chat_join_request
    user_id = str(join_request.from_user.id)
    chat_id = join_request.chat.id
    
    logging.info(f"دریافت درخواست عضویت: کاربر {user_id} برای کانال {chat_id}")
    
    # پیدا کردن کاربر در دیتابیس
    user = users_data.get(user_id)
    if not user:
        logging.warning(f"کاربر {user_id} در دیتابیس یافت نشد")
        await context.bot.decline_chat_join_request(chat_id, user_id)
        return
    
    # همگام‌سازی داده‌ها
    user = await sync_user_data(user_id, user)
    
    # بررسی اعتبار دسترسی
    valid_access = False
    if chat_id == CHANNEL_ID and user.get("Hotline", False) and user.get("days_left", 0) > 0:
        valid_access = True
    elif chat_id == CIP_CHANNEL_ID and user.get("CIP", False) and user.get("days_left", 0) > 0:
        valid_access = True
    
    # تأیید یا رد درخواست
    if valid_access:
        logging.info(f"تأیید عضویت کاربر {user_id} برای کانال {chat_id}")
        await context.bot.approve_chat_join_request(chat_id, user_id)
    else:
        logging.warning(f"رد عضویت کاربر {user_id} برای کانال {chat_id}")
        await context.bot.decline_chat_join_request(chat_id, user_id)
        await context.bot.send_message(
            chat_id=int(user_id),
            text="⚠️ این لینک برای شما معتبر نیست یا اشتراک شما منقضی شده است.",
            protect_content=True
        )

# —————————————————————————————————————————————————————————————————————
# بخش پنجم: تحلیل بازار
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

async def get_asset_data(symbol, period):
    """تابع موقت برای دریافت داده‌های دارایی (پیاده‌سازی واقعی نیازمند اتصال به API)"""
    # این قسمت باید با اتصال به API واقعی جایگزین شود
    return {
        "H": 1800.0, "L": 1750.0, "C": 1775.0,
        "M1": 1760.0, "M2": 1765.0, "M3": 1770.0, "M4": 1775.0,
        "M5": 1780.0, "M6": 1785.0, "M7": 1790.0,
        "Z1": 1775.0,
        "pip": 0.1,
        "U": [1800.0, 1810.0, 1820.0, 1830.0, 1840.0],
        "D": [1750.0, 1740.0, 1730.0, 1720.0, 1710.0]
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
    kb.append([InlineKeyboardButton("🔙 بازگشت به منو", callback_data="analysis|back_to_main")])
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
    kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data="analysis|back")])
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

async def analysis_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await analysis_menu(update, context)

async def analysis_back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(update.effective_user.id)
    user = users_data.get(user_id)
    await show_main_menu(query.message, context, user)

# —————————————————————————————————————————————————————————————————————
# بخش ششم: هشدار اتمام اشتراک (با رفع مشکل)
# —————————————————————————————————————————————————————————————————————
async def check_subscription_alerts(app):
    """ارسال هشدار به کاربرانی که اشتراکشان در حال اتمام است"""
    global users_data
    now = datetime.utcnow()
    logging.info(f"🔔 شروع بررسی هشدارهای اشتراک در {now}")
    
    for user_id, user in users_data.items():
        days_left = user.get("days_left", 0)
        last_alert = user.get("last_alert_sent")
        
        # شرایط ارسال هشدار:
        if days_left > 0 and days_left <= SUBSCRIPTION_ALERT_DAYS:
            logging.info(f"کاربر {user_id} واجد شرایط هشدار: {days_left} روز باقی مانده")
            
            # بررسی زمان آخرین هشدار
            if last_alert:
                try:
                    last_alert_time = datetime.fromisoformat(last_alert)
                    if (now - last_alert_time) < timedelta(hours=3):
                        logging.info(f"اخیراً به کاربر {user_id} هشدار ارسال شده است. رد شد.")
                        continue
                except Exception as e:
                    logging.error(f"خطا در بررسی زمان هشدار برای {user_id}: {e}")
            
            # تشخیص نوع اشتراک
            subscription_types = []
            if user.get("CIP", False):
                subscription_types.append("CIP")
            if user.get("Hotline", False):
                subscription_types.append("Hotline")
            
            if not subscription_types:
                logging.warning(f"کاربر {user_id} اشتراک فعال دارد اما نوع اشتراک تعریف نشده است")
                continue
                
            # ساخت پیام با ذکر نوع اشتراک
            subscription_names = " و ".join(subscription_types)
            message = (
                f"⏳ از زمان اشتراک شما برای {subscription_names} فقط {days_left} روز باقی مانده است!\n"
                f"⚠️ لطفاً جهت جلوگیری از حذف دسترسی به کانال‌ها اشتراک خود را تمدید کنید.\n\n"
                f"📞 برای تمدید اشتراک با پشتیبانی تماس بگیرید: {SUPPORT_ID}"
            )
            
            try:
                logging.info(f"ارسال هشدار اشتراک به {user_id}")
                await app.bot.send_message(
                    chat_id=int(user_id),
                    text=message,
                    protect_content=True
                )
                
                # به‌روزرسانی زمان آخرین هشدار
                user["last_alert_sent"] = now.isoformat()
                save_data(users_data)
                
            except Exception as e:
                logging.error(f"خطا در ارسال هشدار اشتراک به {user_id}: {e}")
        else:
            logging.info(f"کاربر {user_id} واجد شرایط هشدار نیست: {days_left} روز باقی مانده")
    
    logging.info(f"✅ بررسی هشدارهای اشتراک تکمیل شد")

# —————————————————————————————————————————————————————————————————————
# بخش هفتم: پنل مدیریت ادمین (با قابلیت مدیریت کدهای تخفیف)
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
        ["✏️ ویرایش کدهای تخفیف", "🔄 همگام‌سازی داده‌ها"],
        ["🔤 مدیریت کلمات کلیدی", "📝 مدیریت ثبت‌نام"],
        ["🔙 بازگشت به منو"]
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
            datetime.strptime(value, "%Y-%m-%d")
            user["subscription_start"] = value
            
            start_date = datetime.strptime(value, "%Y-%m-%d").date()
            today = datetime.utcnow().date()
            days_passed = (today - start_date).days
            user["days_left"] = max(0, user.get("subscription_days", 0) - days_passed)
            
            user["last_alert_sent"] = None
            
            await update.message.reply_text(f"✅ تاریخ شروع اشتراک به {value} تنظیم شد")
        except ValueError:
            await update.message.reply_text("❌ فرمت تاریخ نامعتبر. لطفاً از فرمت YYYY-MM-DD استفاده کنید")
    
    await update_user_in_sheet(user)
    users_data[user_id] = user
    save_data(users_data)
    return await show_admin_dashboard(update, context)

async def edit_discount_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["✏️ ویرایش کد 10%", "✏️ ویرایش کد 20%"],
        ["🔙 بازگشت"]
    ]
    await update.message.reply_text(
        f"کدهای تخفیف فعلی:\n\n"
        f"🔸 کد 10%: {DISCOUNT_CODE_10}\n"
        f"🔸 کد 20%: {DISCOUNT_CODE_20}\n\n"
        "لطفاً انتخاب کنید:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return EDIT_DISCOUNT

async def handle_discount_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    action = update.message.text
    global DISCOUNT_CODE_10, DISCOUNT_CODE_20
    
    if action == "✏️ ویرایش کد 10%":
        await update.message.reply_text("لطفاً کد تخفیف 10% جدید را وارد کنید:")
        context.user_data["discount_action"] = "edit_10"
        return EDIT_DISCOUNT
    
    elif action == "✏️ ویرایش کد 20%":
        await update.message.reply_text("لطفاً کد تخفیف 20% جدید را وارد کنید:")
        context.user_data["discount_action"] = "edit_20"
        return EDIT_DISCOUNT
    
    elif action == "🔙 بازگشت":
        return await show_admin_dashboard(update, context)

async def handle_discount_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global DISCOUNT_CODE_10, DISCOUNT_CODE_20
    action = context.user_data.get("discount_action")
    new_code = update.message.text.strip()
    
    # لیست دستورات ممنوعه
    forbidden_commands = [
        "👥 لیست کاربران", "✏️ ویرایش اشترак", "✏️ ویرایش کدهای تخفیف",
        "🔄 همگام‌سازی داده‌ها", "🔙 بازگشت به منو", "📅 افزایش روز اشتراک",
        "🔄 تنظیم تاریخ شروع", "🔛 فعال‌سازی CIP", "📡 فعال‌سازی Hotline",
        "🔘 غیرفعال‌سازی CIP", "📴 غیرفعال‌سازی Hotline", "🔙 بازگشت",
        "✏️ ویرایش کد 10%", "✏️ ویرایش کد 20%", "🔤 مدیریت کلمات کلیدی",
        "📝 مدیریت ثبت‌نام"
    ]
    
    if new_code in forbidden_commands:
        await update.message.reply_text("❌ این کد با دستورات پنل تداخل دارد. لطفاً کد دیگری انتخاب کنید.")
        return EDIT_DISCOUNT
    
    if action == "edit_10":
        DISCOUNT_CODE_10 = new_code
        await update.message.reply_text(f"✅ کد تخفیف 10% به {new_code} به‌روزرسانی شد")
    elif action == "edit_20":
        DISCOUNT_CODE_20 = new_code
        await update.message.reply_text(f"✅ کد تخفیف 20% به {new_code} به‌روزرسانی شد")
    
    return await show_admin_dashboard(update, context)

async def sync_all_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count = 0
    for user_id, user_data in users_data.items():
        if await update_user_in_sheet(user_data):
            count += 1
    await update.message.reply_text(f"✅ {count} کاربر با گوگل شیت همگام‌سازی شدند")
    return ADMIN_ACTION

# —————————————————————————————————————————————————————————————————————
# بخش جدید: مدیریت کلمات کلیدی و پاسخ‌ها (با استفاده از فایل JSON)
# —————————————————————————————————————————————————————————————————————
async def edit_keywords_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع مدیریت کلمات کلیدی"""
    global keywords_data
    
    if not keywords_data:
        message = "📝 هیچ کلمه کلیدی تعریف نشده است."
    else:
        message = "📝 کلمات کلیدی فعلی:\n\n"
        for keyword, response in keywords_data.items():
            message += f"🔹 {keyword}: {response[:50]}...\n"
    
    keyboard = [
        ["➕ افزودن کلمه کلیدی", "✏️ ویرایش کلمه کلیدی"],
        ["🗑️ حذف کلمه کلیدی", "🔙 بازگشت"]
    ]
    
    await update.message.reply_text(
        message,
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return EDIT_KEYWORDS

async def handle_keywords_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت عملیات کلمات کلیدی"""
    global keywords_data
    action = update.message.text
    
    if action == "➕ افزودن کلمه کلیدی":
        await update.message.reply_text(
            "لطفاً کلمه کلیدی جدید را وارد کنید:",
            reply_markup=ReplyKeyboardRemove()
        )
        context.user_data["keyword_action"] = "add_keyword"
        return EDIT_KEYWORDS
    
    elif action == "✏️ ویرایش کلمه کلیدی":
        if not keywords_data:
            await update.message.reply_text("❌ هیچ کلمه کلیدی برای ویرایش وجود ندارد.")
            return await edit_keywords_start(update, context)
        
        keyboard = [[k] for k in keywords_data.keys()]
        keyboard.append(["🔙 بازگشت"])
        
        await update.message.reply_text(
            "لطفاً کلمه کلیدی برای ویرایش انتخاب کنید:",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )
        context.user_data["keyword_action"] = "edit_keyword"
        return EDIT_KEYWORDS
    
    elif action == "🗑️ حذف کلمه کلیدی":
        if not keywords_data:
            await update.message.reply_text("❌ هیچ کلمه کلیدی برای حذف وجود ندارد.")
            return await edit_keywords_start(update, context)
        
        keyboard = [[k] for k in keywords_data.keys()]
        keyboard.append(["🔙 بازگشت"])
        
        await update.message.reply_text(
            "لطفاً کلمه کلیدی برای حذف انتخاب کنید:",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )
        context.user_data["keyword_action"] = "delete_keyword"
        return EDIT_KEYWORDS
    
    elif action == "🔙 بازگشت":
        return await show_admin_dashboard(update, context)
    
    return EDIT_KEYWORDS

async def handle_keyword_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش ورودی کاربر برای کلمات کلیدی"""
    global keywords_data
    user_input = update.message.text
    action = context.user_data.get("keyword_action")
    
    # اگر کاربر می‌خواهد بازگردد
    if user_input == "🔙 بازگشت":
        return await edit_keywords_start(update, context)
    
    if action == "add_keyword":
        # ذخیره کلمه کلیدی موقت و درخواست پاسخ
        context.user_data["new_keyword"] = user_input
        await update.message.reply_text("لطفاً پاسخ برای این کلمه کلیدی را وارد کنید:")
        context.user_data["keyword_action"] = "add_response"
        return EDIT_KEYWORDS
    
    elif action == "add_response":
        keyword = context.user_data.get("new_keyword")
        keywords_data[keyword] = user_input
        if save_keywords(keywords_data):
            await update.message.reply_text(f"✅ کلمه کلیدی '{keyword}' با پاسخ مربوطه اضافه شد.")
        else:
            await update.message.reply_text("❌ خطا در ذخیره کلمه کلیدی.")
        # بازگشت به منوی مدیریت کلمات کلیدی
        return await edit_keywords_start(update, context)
    
    elif action == "edit_keyword":
        if user_input in keywords_data:
            context.user_data["selected_keyword"] = user_input
            await update.message.reply_text(
                f"کلمه کلیدی انتخاب شده: {user_input}\n"
                f"پاسخ فعلی: {keywords_data[user_input]}\n\n"
                "لطفاً پاسخ جدید را وارد کنید:",
                reply_markup=ReplyKeyboardRemove()
            )
            context.user_data["keyword_action"] = "edit_response"
        else:
            await update.message.reply_text("❌ کلمه کلیدی یافت نشد.")
            return await edit_keywords_start(update, context)
        return EDIT_KEYWORDS
    
    elif action == "edit_response":
        keyword = context.user_data.get("selected_keyword")
        keywords_data[keyword] = user_input
        if save_keywords(keywords_data):
            await update.message.reply_text(f"✅ پاسخ کلمه کلیدی '{keyword}' به‌روزرسانی شد.")
        else:
            await update.message.reply_text("❌ خطا در به‌روزرسانی پاسخ.")
        return await edit_keywords_start(update, context)
    
    elif action == "delete_keyword":
        if user_input in keywords_data:
            del keywords_data[user_input]
            if save_keywords(keywords_data):
                await update.message.reply_text(f"✅ کلمه کلیدی '{user_input}' حذف شد.")
            else:
                await update.message.reply_text("❌ خطا در حذف کلمه کلیدی.")
        else:
            await update.message.reply_text("❌ کلمه کلیدی یافت نشد.")
        return await edit_keywords_start(update, context)
    
    # اگر عمل‌شناسی نشد، به منوی اصلی برگرد
    return await edit_keywords_start(update, context)

# —————————————————————————————————————————————————————————————————————
# بخش جدید: مدیریت گزینه‌های ثبت‌نام
# —————————————————————————————————————————————————————————————————————
async def edit_registration_options_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع مدیریت گزینه‌های ثبت‌نام"""
    global registration_options
    
    if not registration_options:
        message = "📝 هیچ گزینه ثبت‌نامی تعریف نشده است."
    else:
        message = "📝 گزینه‌های ثبت‌نام فعلی:\n\n"
        for option in registration_options:
            message += f"🔹 {option}\n"
    
    keyboard = [
        ["➕ افزودن گزینه ثبت‌نام", "🗑️ حذف گزینه ثبت‌نام"],
        ["🔙 بازگشت"]
    ]
    
    await update.message.reply_text(
        message,
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return EDIT_REGISTRATION_OPTIONS

async def handle_registration_options_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت عملیات گزینه‌های ثبت‌نام"""
    global registration_options
    action = update.message.text
    
    if action == "➕ افزودن گزینه ثبت‌نام":
        await update.message.reply_text(
            "لطفاً عنوان گزینه ثبت‌نام جدید را وارد کنید:",
            reply_markup=ReplyKeyboardRemove()
        )
        context.user_data["reg_action"] = "add_option"
        return EDIT_REGISTRATION_OPTIONS
    
    elif action == "🗑️ حذف گزینه ثبت‌نام":
        if not registration_options:
            await update.message.reply_text("❌ هیچ گزینه ثبت‌نامی برای حذف وجود ندارد.")
            return await edit_registration_options_start(update, context)
        
        keyboard = [[option] for option in registration_options]
        keyboard.append(["🔙 بازگشت"])
        
        await update.message.reply_text(
            "لطفاً گزینه ثبت‌نام برای حذف انتخاب کنید:",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )
        context.user_data["reg_action"] = "delete_option"
        return EDIT_REGISTRATION_OPTIONS
    
    elif action == "🔙 بازگشت":
        return await show_admin_dashboard(update, context)
    
    return EDIT_REGISTRATION_OPTIONS

async def handle_registration_option_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش ورودی کاربر برای گزینه‌های ثبت‌نام"""
    global registration_options
    user_input = update.message.text
    action = context.user_data.get("reg_action")
    
    # اگر کاربر می‌خواهد بازگردد
    if user_input == "🔙 بازگشت":
        return await edit_registration_options_start(update, context)
    
    if action == "add_option":
        if user_input in registration_options:
            await update.message.reply_text("❌ این گزینه قبلاً اضافه شده است.")
            return await edit_registration_options_start(update, context)
        
        registration_options.append(user_input)
        if save_registration_options(registration_options):
            await update.message.reply_text(f"✅ گزینه ثبت‌نام '{user_input}' اضافه شد.")
        else:
            await update.message.reply_text("❌ خطا در ذخیره گزینه ثبت‌نام.")
        return await edit_registration_options_start(update, context)
    
    elif action == "delete_option":
        if user_input in registration_options:
            registration_options.remove(user_input)
            if save_registration_options(registration_options):
                await update.message.reply_text(f"✅ گزینه ثبت‌نام '{user_input}' حذف شد.")
            else:
                await update.message.reply_text("❌ خطا در حذف گزینه ثبت‌نام.")
        else:
            await update.message.reply_text("❌ گزینه ثبت‌نام یافت نشد.")
        return await edit_registration_options_start(update, context)
    
    return EDIT_REGISTRATION_OPTIONS

# —————————————————————————————————————————————————————————————————————
# بخش جدید: پردازش ثبت‌نام کاربران
# —————————————————————————————————————————————————————————————————————
async def handle_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش درخواست ثبت‌نام کاربر"""
    user_id = str(update.effective_user.id)
    user = users_data.get(user_id)
    option = update.message.text
    
    if not user:
        await update.message.reply_text("⚠️ لطفاً ابتدا احراز هویت کنید (/start).")
        return
    
    # ذخیره اطلاعات ثبت‌نام
    registration_data = {
        "user_id": user_id,
        "name": user.get("name", ""),
        "phone": user.get("phone", ""),
        "option": option,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    # ذخیره در فایل محلی
    if save_registration(registration_data):
        # ارسال به گوگل شیت
        success = await send_registration_to_sheet(
            user.get("name", ""), 
            user.get("phone", ""), 
            option
        )
        
        if success:
            await update.message.reply_text("✅ ثبت‌نام شما با موفقیت انجام شد.")
        else:
            await update.message.reply_text("⚠️ ثبت‌نام شما ذخیره شد اما ارسال به گوگل شیت با مشکل مواجه شد.")
    else:
        await update.message.reply_text("❌ خطا در ثبت‌نام. لطفاً با پشتیبانی تماس بگیرید.")

async def admin_logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users_data.get(user_id)
    await update.message.reply_text(
        "شما از پنل ادمین خارج شدید.",
        reply_markup=ReplyKeyboardRemove()
    )
    if user:
        await show_main_menu(update.message, context, user)
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
# بخش جدید: ارتباط با ما
# —————————————————————————————————————————————————————————————————————
async def contact_us(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact_info = f"""
📞 ارتباط با ما

🌐 وبسایت رسمی:
{WEBSITE_URL}

📱 اینستاگرام:
{INSTAGRAM_URL}

▶️ یوتیوب:
{YOUTUBE_URL}

✉️ پشتیبانی:
{SUPPORT_ID}
"""
    await update.message.reply_text(contact_info)

# —————————————————————————————————————————————————————————————————————
# بخش جدید: کد تخفیف پراپ‌فرم ForFx
# —————————————————————————————————————————————————————————————————————
async def forfx_discount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    discount_info = f"""
🔰برای دریافت چالش پراپ از پراپفرم ForFx🔰

🎆میتوانید از کد های تخفیف آکادمی (خان زاده) استفاده نمایید:

🔻کد تخفیف مخصوص حساب peak Scalp🔻

🔸10% تخفیف🔸

🟣  {DISCOUNT_CODE_10}کد تخفیف :  🟣

➖➖➖➖➖➖➖➖➖➖➖➖➖➖➖➖➖➖
🔻کد تخفیف مخصوص حساب های Legend و Flash 🔻

🔸20% تخفیف 🔸

🟣  {DISCOUNT_CODE_20}   کد تخفیف : 🟣


ForFx.com

🟡قبل از خرید به id شخصی بنده پیام دهید و مشاوره شوید.


🔻🌐ID telegram:🌐🔻

{SUPPORT_ID}
"""
    await update.message.reply_text(discount_info)

# —————————————————————————————————————————————————————————————————————
# بخش نهم: سایر دستورات (با تغییرات)
# —————————————————————————————————————————————————————————————————————
async def buy_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💳 برای خرید اشتراک لطفاً با پشتیبانی تماس بگیرید.\n"
        f"📞 آیدی پشتیبانی: {SUPPORT_ID}"
    )

async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"👨‍💻 برای پشتیبانی لطفاً به آیدی زیر پیام دهید:\n{SUPPORT_ID}")

async def handle_keyword_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش پیام‌های حاوی کلمات کلیدی"""
    global keywords_data, registration_options
    text = update.message.text.strip()
    user_id = str(update.effective_user.id)
    user = users_data.get(user_id)
    
    if not user:
        await update.message.reply_text("⚠️ لطفاً ابتدا احراز هویت کنید (/start).")
        return
    
    # اول بررسی می‌کنیم آیا این پیام یک گزینه ثبت‌نام است؟
    if text in registration_options:
        await handle_registration(update, context)
        return
    
    # سپس کلمات کلیدی را بررسی می‌کنیم
    text_lower = text.lower()
    for keyword, response in keywords_data.items():
        if keyword.lower() in text_lower:
            await update.message.reply_text(response)
            return
    
    # اگر هیچکدام نبود، به هندلر اصلی برو
    await handle_text(update, context)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = str(update.effective_user.id)
    user = users_data.get(user_id)
    
    if not user:
        await update.message.reply_text("⚠️ لطفاً ابتدا احراز هویت کنید (/start).")
        return
    
    if text == "📅 اشتراک من":
        await my_subscription(update, context)
    elif text == "🔑 Hotline ورود به کانال":
        await join_channel(update, context)
    elif text == "🌐 ورود به کانال CIP":
        await join_cip_channel(update, context)
    elif text == "💳 خرید اشتراک":
        await buy_subscription(update, context)
    elif text == "🛟 پشتیبانی":
        await support(update, context)
    elif text == "📊 تحلیل بازار":
        await analysis_menu(update, context)
    elif text == "📰 اخبار اقتصادی فارکس":
        await economic_news(update, context)
    elif text == "📞 ارتباط با ما":
        await contact_us(update, context)
    elif text == "🔰 کد تخفیف پراپفرم ForFx":
        await forfx_discount(update, context)
    elif text == "🔙 بازگشت به منو":
        await show_main_menu(update.message, context, user)
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
                MessageHandler(filters.Regex("^✏️ ویرایش کدهای تخفیف$"), edit_discount_start),
                MessageHandler(filters.Regex("^🔄 همگام‌سازی داده‌ها$"), sync_all_data),
                MessageHandler(filters.Regex("^🔤 مدیریت کلمات کلیدی$"), edit_keywords_start),
                MessageHandler(filters.Regex("^📝 مدیریت ثبت‌نام$"), edit_registration_options_start),
                MessageHandler(filters.Regex("^🔙 بازگشت به منو$"), admin_logout),
            ],
            SELECT_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_selection)],
            EDIT_SUBSCRIPTION: [
                MessageHandler(filters.Regex("^(📅 افزایش روز اشتراک|🔄 تنظیم تاریخ شروع|🔛 فعال‌سازی CIP|📡 فعال‌سازی Hotline|🔘 غیرفعال‌سازی CIP|📴 غیرفعال‌سازی Hotline|🔙 بازگشت)$"), handle_subscription_edit),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_value)
            ],
            EDIT_DISCOUNT: [
                MessageHandler(filters.Regex("^(✏️ ویرایش کد 10%|✏️ ویرایش کد 20%|🔙 بازگشت)$"), handle_discount_edit),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_discount_value)
            ],
            EDIT_KEYWORDS: [
                MessageHandler(filters.Regex("^(➕ افزودن کلمه کلیدی|✏️ ویرایش کلمه کلیدی|🗑️ حذف کلمه کلیدی|🔙 بازگشت)$"), handle_keywords_edit),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_keyword_input)
            ],
            EDIT_REGISTRATION_OPTIONS: [
                MessageHandler(filters.Regex("^(➕ افزودن گزینه ثبت‌نام|🗑️ حذف گزینه ثبت‌نام|🔙 بازگشت)$"), handle_registration_options_edit),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_registration_option_input)
            ]
        },
        fallbacks=[CommandHandler("admin", admin_login)]
    )
    
    # اضافه کردن تمام هندلرهای ربات
    app.add_handler(admin_conv_handler)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    
    # تغییر هندلر متن برای پشتیبانی از کلمات کلیدی و ثبت‌نام
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_keyword_messages))
    
    app.add_handler(CallbackQueryHandler(asset_selection_menu, pattern=r"^period\|"))
    app.add_handler(CallbackQueryHandler(asset_selected, pattern=r"^asset\|"))
    app.add_handler(CallbackQueryHandler(analysis_back, pattern=r"^analysis\|back$"))
    app.add_handler(CallbackQueryHandler(analysis_back_to_main, pattern=r"^analysis\|back_to_main$"))
    
    # افزودن هندلر جدید برای مدیریت درخواست‌های عضویت
    app.add_handler(ChatJoinRequestHandler(handle_chat_join_request))
    
    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    async def alert_loop():
        await asyncio.sleep(10)
        while True:
            try:
                # await check_alerts(app)  # غیرفعال تا پیاده‌سازی شود
                pass
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
            await asyncio.sleep(3 * 3600)  # هر 3 ساعت یکبار اجرا شود

    asyncio.create_task(alert_loop())
    asyncio.create_task(subscription_alert_loop())
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
