# Telegram VIP & Market Analysis Bot

## توضیحات
این ربات امکانات زیر را دارد:
- احراز هویت با شماره موبایل
- بررسی اشتراک از Google Sheets
- ساخت لینک موقت ۱۰ دقیقه‌ای ورود به کانال VIP
- حذف خودکار کاربر از کانال پس از اتمام اشتراک
- نمایش «اشتراک من»، «خرید اشتراک»، «پشتیبانی»
- تحلیل بازار (انس طلا و جفت‌ارزها و شاخص‌ها) و هشدار لحظه‌ای قیمت

## فایل‌ها
- `main.py` – کد اصلی ربات
- `requirements.txt` – لیست کتابخانه‌ها
- `user_data.json` – دیتابیس محلی JSON کاربران

## مراحل راه‌اندازی
1. نصب پکیج‌ها: `pip install -r requirements.txt`
2. تنظیم متغیرها در ابتدای `main.py`  
   • `BOT_TOKEN`, `CHANNEL_ID`, `GOOGLE_SHEET_URL`, `TWELVE_API_KEY`  
   • `SUPPORT_ID`, `CHANNEL_USERNAME`
3. اجرای ربات: `python main.py`
4. (در صورت استفاده Render) تنظیمات Deploy در Render را انجام دهید.
