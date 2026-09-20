import requests
import time
import json
import os
import glob
import shutil
from datetime import datetime, timedelta, timezone

TOKEN          = "1866774166:DS6uzYhJhxY3MTEU89WPgh8uIS-ZfmUVljs"
BASE_URL       = f"https://tapi.bale.ai/bot{TOKEN}"
PROVIDER_TOKEN = "WALLET-fBQfc9qer4hIUiBT"

BOT_USERNAME = "IRAN_MARKET"
ADMIN_IDS    = [1823050517, 324157864]

CHANNEL_ID   = "@irani_market"
CHANNEL_LINK = "https://ble.ir/irani_market"

BACKUP_PASSWORD = "Arka_Team"   # رمز دریافت بکاپ در پنل ادمین
DATA_FILE    = "bot_data.json"

CATALOG_VERSION      = 5      # با بالا بردن این عدد، بخش خدمات (کاتالوگ) هنگام استارت دوباره ساخته می‌شود
FAKE_LINK            = "https://www.aparat.com/v/TEST"   # لینک پیش‌فرض سفارش‌های فیک (تست)
MARK_FAKE_IN_CHANNEL = False  # False = روی پیام کانال برای سفارش فیک هیچ علامت آزمایشی ننویس (کاربر نفهمد)

# ══════════════════════════════════════════
#  DATA
# ══════════════════════════════════════════
def default_data():
    data = {
        "settings": {
            "forced_join":  True,
            "channel":      CHANNEL_ID,
            "channel_link": CHANNEL_LINK,
        },
        "stats": {
            "total_users": 0, "total_orders": 0,
            "total_revenue": 0, "daily_stats": {}
        },
        "users":          {},
        "orders":         [],
        "tickets":        {},
        "ticket_counter": 0,
        "order_counter":  0,
    }
    seed_services(data)          # کاتالوگ و تنظیمات خدمات (واچ‌تایم آپارات)
    return data

def migrate_data(data):
    if "catalog_version" not in data:
        data["catalog_version"] = 1
    if "catalog" not in data:
        seed_services(data)
    defaults = default_data()
    for k, v in defaults.items():
        if k not in data:
            data[k] = v
    # فقط تنظیمات عمومی ادغام می‌شود؛ تنظیمات سرویس‌ها فقط از روی کاتالوگ ساخته می‌شود
    for k, v in defaults["settings"].items():
        if not isinstance(v, dict) and k not in data["settings"]:
            data["settings"][k] = v
    return data

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return migrate_data(data)
        except:
            pass
    return default_data()

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_today():
    return datetime.now().strftime("%Y-%m-%d")

# ══════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════
def is_admin(chat_id):
    return int(chat_id) in ADMIN_IDS

def register_user(data, chat_id, uinfo=None):
    uid = str(chat_id)
    if uid not in data["users"]:
        data["users"][uid] = {
            "chat_id":     chat_id,
            "first_seen":  datetime.now().isoformat(),
            "last_seen":   datetime.now().isoformat(),
            "orders":      0,
            "total_spent": 0,
            "blocked":     False,
            "wallet":      0,
            "username":    (uinfo or {}).get("username", ""),
            "first_name":  (uinfo or {}).get("first_name", ""),
        }
        data["stats"]["total_users"] += 1
    else:
        data["users"][uid]["last_seen"] = datetime.now().isoformat()
        if uinfo:
            data["users"][uid]["username"]   = uinfo.get("username",   data["users"][uid].get("username",""))
            data["users"][uid]["first_name"] = uinfo.get("first_name", data["users"][uid].get("first_name",""))
    save_data(data)

def check_membership(chat_id):
    data = load_data()
    if not data["settings"]["forced_join"]:
        return True
    try:
        r = requests.get(
            f"{BASE_URL}/getChatMember",
            params={"chat_id": data["settings"]["channel"], "user_id": chat_id},
            timeout=10
        ).json()
        if r.get("ok"):
            return r["result"].get("status","") in ["member","administrator","creator"]
        return False
    except Exception as e:
        print(f"check_membership error: {e}")
        return False

def validate_aparat_link(link):
    link = link.strip()
    if " " in link or "\n" in link:
        return False
    low = link.lower()
    for p in ["https://www.aparat.com/v/", "http://www.aparat.com/v/",
              "https://aparat.com/v/",     "http://aparat.com/v/",
              "www.aparat.com/v/",         "aparat.com/v/"]:
        if low.startswith(p) and len(link) >= len(p) + 3:
            return True
    return False

def validate_aparat_short_link(link):
    """لینک شورتس آپارات"""
    link = link.strip()
    if " " in link or "\n" in link:
        return False
    low = link.lower()
    for p in ["https://aparat.com/shorts/", "http://aparat.com/shorts/",
              "https://www.aparat.com/shorts/", "http://www.aparat.com/shorts/",
              "aparat.com/shorts/", "www.aparat.com/shorts/"]:
        if low.startswith(p) and len(link) >= len(p) + 3:
            return True
    return False

def _aparat_rest(link):
    """بخش بعد از aparat.com/ ؛ اگر لینک آپارات نباشد None"""
    link = link.strip()
    if " " in link or "\n" in link:
        return None
    low = link.lower()
    for p in ["https://www.aparat.com/", "http://www.aparat.com/", "https://aparat.com/",
              "http://aparat.com/", "www.aparat.com/", "aparat.com/"]:
        if low.startswith(p):
            return link[len(p):].split("?")[0].strip("/")
    return None

def validate_aparat_channel_link(link):
    """لینک کانال آپارات: aparat.com/username"""
    rest = _aparat_rest(link)
    if not rest or "/" in rest:
        return False
    return len(rest) >= 2 and rest.lower() not in ("v", "shorts", "live")

def validate_aparat_live_link(link):
    """لینک لایو آپارات: aparat.com/username/live"""
    rest = _aparat_rest(link)
    if not rest:
        return False
    parts = rest.split("/")
    return len(parts) == 2 and len(parts[0]) >= 2 and parts[1].lower() == "live"

def validate_soroush_link(link):
    """لینک پست یا یوزرنیم کانال سروش"""
    link = link.strip()
    if " " in link or "\n" in link:
        return False
    low = link.lower()
    if low.startswith("@") and len(link) >= 3:
        return True
    for p in ["https://splus.ir/", "http://splus.ir/", "splus.ir/"]:
        if low.startswith(p) and len(link) >= len(p) + 3:
            return True
    return False

def gregorian_to_jalali(gy, gm, gd):
    g_days_in_month = [31,28,31,30,31,30,31,31,30,31,30,31]
    j_days_in_month = [31,31,31,31,31,31,30,30,30,30,30,29]
    gy2=gy-1600; gm2=gm-1; gd2=gd-1
    g_day_no = 365*gy2+(gy2+3)//4-(gy2+99)//100+(gy2+399)//400
    for i in range(gm2): g_day_no += g_days_in_month[i]
    if gm2>1 and ((gy%4==0 and gy%100!=0) or (gy%400==0)): g_day_no+=1
    g_day_no+=gd2
    j_day_no=g_day_no-79
    j_np=j_day_no//12053; j_day_no%=12053
    jy=979+33*j_np+4*(j_day_no//1461); j_day_no%=1461
    if j_day_no>=366:
        jy+=(j_day_no-1)//365; j_day_no=(j_day_no-1)%365
    for i in range(11):
        if j_day_no<j_days_in_month[i]: jm=i+1; jd=j_day_no+1; break
        j_day_no-=j_days_in_month[i]
    else: jm=12; jd=j_day_no+1
    return jy,jm,jd

def now_jalali_str():
    utc_now  = datetime.now(timezone.utc).replace(tzinfo=None)
    iran_now = utc_now + timedelta(hours=3, minutes=30)
    jy,jm,jd = gregorian_to_jalali(iran_now.year, iran_now.month, iran_now.day)
    return f"{jy:04d}/{jm:02d}/{jd:02d} - {iran_now.strftime('%H:%M:%S')}"

def mask_user_id(chat_id):
    s=str(chat_id); n=len(s)
    if n<=4: return "*"*n
    vs=max(2,(n-4)//2); ve=n-vs-4
    if ve<2: ve=2; vs=n-ve-4
    if vs<1: vs=1
    ml=n-vs-ve
    if ml<1: ml=1
    return s[:vs]+("*"*ml)+s[n-ve:]

def send(chat_id, text, markup=None):
    """ارسال پیام. اگر Markdown خطا داد، یک بار بدون Markdown دوباره تلاش می‌کند."""
    payload = {"chat_id":chat_id,"text":text,"parse_mode":"Markdown"}
    if markup: payload["reply_markup"] = markup
    try:
        r = requests.post(f"{BASE_URL}/sendMessage", json=payload, timeout=10)
        try:    ok = bool(r.json().get("ok"))
        except: ok = r.ok
        if ok:
            return True
        payload.pop("parse_mode", None)
        r = requests.post(f"{BASE_URL}/sendMessage", json=payload, timeout=10)
        try:    return bool(r.json().get("ok"))
        except: return r.ok
    except Exception as e:
        print(f"send error: {e}")
        return False

def kb(*rows):
    return {"keyboard":[[{"text":t} for t in row] for row in rows],"resize_keyboard":True}

BACK_BTN      = kb(["🔙 بازگشت"])
BACK_BTN_USER = kb(["🔙 بازگشت به منوی اصلی 🏠"])

# ══════════════════════════════════════════
#  JOIN / START
# ══════════════════════════════════════════
def send_join_required(chat_id):
    data = load_data()
    send(chat_id,
        "*✨🥳 اوه! ی لحظه صبر کن! 🥳✨\n\n"
        "برای اینکه بتونی از تمام قدرتِ ربات استفاده کنی و اولین سفارش‌ها خفن رو ثبت کنی، باید اول به باشگاه ویژه ما بیای! 🏃‍♂️💨\n\n"
        "🌈 فقط کافیه عضو کانال ما بشی تا قفل ربات باز بشه:\n\n"
        "🌟 با عضویت در کانال، از تخفیف‌ها، خبر‌های داغ و آپدیت‌های جدید ما جا نمونی! 🌟\n\n"
        "✅ بعد از عضویت، دوباره به اینجا برگرد تا بترکونیم! 🚀🔥*",
        {"inline_keyboard":[
            [{"text":"خدمات ممبر ایران","url":data["settings"]["channel_link"]}],
            [{"text":"تأیید عضویت✔️","callback_data":"check_join"}]
        ]}
    )

def send_not_joined(chat_id):
    data = load_data()
    send(chat_id,
        "*⚠️ اوپس! یه کوچولو اشتباه شد! 😅✨\n\n"
        "ای وای! انگار هنوز عضو کانال رسمی ما نشدی رفیق! 🧐💔\n\n"
        "نگران نباش، خیلی ساده‌ست! فقط چند لحظه وقت بذار و عضو بشو تا بتونیم با هم شروع کنیم به رشد و بترکونیم! 🚀🌈\n\n"
        "👇 سریع برو عضو شو و دوباره برگرد:\n\n"
        "🌟 منتظر برگشتت هستیم تا قفل ربات رو برات باز کنیم! 🌟\n\n"
        "✨ بزن بریم! ✨*",
        {"inline_keyboard":[
            [{"text":"خدمات ممبر ایران","url":data["settings"]["channel_link"]}],
            [{"text":"تأیید عضویت✔️","callback_data":"check_join"}]
        ]}
    )

def send_start(chat_id):
    send(chat_id,
        "*🌈 سلام سلام! به ربات افزایش ممبر | بازدید ایران خوش اومدی! 🌈🎉\n\n"
        "چه خوب که اینجایی 😍💖\n\n"
        "اینجا قراره با یه عالمه انرژی خوب،\n"
        "ممبر و بازدید رو سریع، راحت و جذاب تجربه کنی 🚀🔥\n\n"
        "💫 چرا اینجا؟\n\n"
        "🌟 سریع و آسان\n\n"
        "🌟 شاد و کاربرپسند\n\n"
        "🌟 پشتیبانی همیشه همراه\n\n"
        "🌟 مناسب برای رشد بهتر و بیشتر\n\n"
        "🚀 برای شروع همین الان وارد شو:\n\n"
        "🔗 " + CHANNEL_ID + "\n\n"
        "💌 پشتیبانی مهربون و پاسخ‌گو:\n\n"
        "🆔 @ARKA_SUPPORT_IR\n\n"
        "🌸✨ منتظر یه تجربه عالی و پرانرژی باش! ✨🌸\n\n"
        "با ما، رشدت شیرین‌تره 🍭💎\n\n"
        "👇 از دکمه‌های زیر برای دسترسی به خدمات ربات استفاده کنید:*",
        kb(
            ["مشاهده و خرید خدمات 🛍"],
            ["حساب کاربری 👤",     "پیگیری سفارش 🔎"],
            ["قوانین ⚖️",          "📞 پشتیبانی"]
        )
    )

# ══════════════════════════════════════════
#  حساب کاربری
# ══════════════════════════════════════════
def send_account(chat_id):
    data    = load_data()
    uid     = str(chat_id)
    u       = data["users"].get(uid, {})
    name    = u.get("first_name", "نامشخص")
    wallet  = u.get("wallet", 0)
    uname   = f"@{u['username']}" if u.get("username") else "ندارد"
    total   = u.get("orders", 0)
    done    = sum(1 for o in data["orders"] if str(o.get("user_id"))==uid and o.get("status")=="done")
    pending = sum(1 for o in data["orders"] if str(o.get("user_id"))==uid and o.get("status")=="pending")
    send(chat_id,
        f"*👤 حساب کاربری\n"
        f"━━━━━━━━━━━━\n\n"
        f"🆔 شناسه کاربری: {chat_id}\n"
        f"👤 نام: {name}\n"
        f"🔗 نام کاربری: {uname}\n"
        f"💼 موجودی کیف پول: {wallet:,} تومان\n\n"
        f"📦 آمار سفارش‌ها\n"
        f"📋 کل سفارش‌ها: {total}\n"
        f"⏳ در حال انجام: {pending}\n"
        f"✅ تکمیل شده: {done}*",
        BACK_BTN_USER
    )

# ══════════════════════════════════════════
#  پیگیری سفارش
# ══════════════════════════════════════════
def send_tracking(chat_id):
    data   = load_data()
    uid    = str(chat_id)
    orders = [o for o in data["orders"] if str(o.get("user_id"))==uid]
    if not orders:
        send(chat_id, "*📋 شما هنوز هیچ سفارشی ثبت نکرده‌اید.*", BACK_BTN_USER)
        return
    send(chat_id, f"*🔎 پیگیری سفارش‌ها | {len(orders)} سفارش*")
    for o in reversed(orders[-20:]):
        st = o.get("status","")
        if st=="done":              st_icon="✅ تکمیل شده"
        elif st=="pending":         st_icon="⏳ در حال انجام"
        elif st=="pending_payment": st_icon="💳 در انتظار پرداخت"
        elif st=="cancelled":       st_icon="❌ لغو شده"
        else:                       st_icon="❓ نامشخص"
        date_str = o.get("date","")[:10]
        reason_line = f"\n📝 علت لغو: {o['cancel_reason']}\n💼 مبلغ به کیف پول شما برگشت." if st=="cancelled" and o.get("cancel_reason") else ""
        send(chat_id,
            f"*🆔 {o.get('id','?')}\n"
            f"📦 {o.get('service','?')}\n"
            f"🔢 تعداد: {o.get('amount',0):,}\n"
            f"💰 مبلغ: {o.get('price',0):,} تومان\n"
            f"🔗 لینک: {o.get('link','?')}\n"
            f"📅 تاریخ: {date_str}\n"
            f"وضعیت: {st_icon}{reason_line}*"
        )
    send(chat_id, "👆 لیست سفارش‌های شما", BACK_BTN_USER)

# ══════════════════════════════════════════
#  قوانین
# ══════════════════════════════════════════
def send_rules(chat_id):
    send(chat_id,
        "*━━━━━━━━━━━━━━━━━━\n"
        "⚖️ قوانین و ضوابط استفاده از ربات «افزایش ممبر | بازدید ایران»\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "استفاده از خدمات این ربات به منزله‌ی تایید کامل تمامی موارد زیر می‌باشد. لطفاً پیش از ثبت سفارش، با دقت مطالعه کنید:\n\n"
        "📍 بخش اول: مسئولیت کاربر\n"
        "🔹 دقت در اطلاعات: مسئولیت صحت تمامی اطلاعات وارد شده (لینک، آیدی، تعداد و پلتفرم) بر عهده کاربر است. اشتباه در ارسال لینک، منجر به عدم انجام سفارش می‌شود.\n"
        "🔹 فرمت صحیح: ثبت سفارش با لینک‌های نامعتبر یا فرمت اشتباه، مسئولیت خود کاربر است.\n\n"
        "⚠️ بخش دوم: سیاست‌های مهم (حتماً بخوانید)\n"
        "🚫 عدم بازگشت وجه: با توجه به ماهیت دیجیتالی خدمات، به هیچ عنوان امکان استرداد یا بازگشت وجه پس از ثبت سفارش و پرداخت وجود ندارد. لطفاً قبل از خرید، از انتخاب صحیح سرویس اطمینان حاصل کنید.\n"
        "🚫 ماهیت سرویس: توجه داشته باشید که برخی خدمات (مانند بازدید) صرفاً جهت بهبود آمار و نمایش هستند و هدف تبلیغاتی یا جذب مخاطب واقعی (Engagement) نمی‌باشند.\n\n"
        "💡 توصیه نهایی:\n"
        "برای دریافت بهترین نتیجه، همیشه ابتدا با مقادیر کم تست کنید. 🚀\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🆘 نیاز به کمک دارید؟\n"
        "ارتباط با پشتیبانی: [@ARKA_SUPPORT_IR]\n"
        "━━━━━━━━━━━━━━━━━━*",
        BACK_BTN_USER
    )

# ══════════════════════════════════════════
#  سیستم تیکت پشتیبانی
# ══════════════════════════════════════════
def get_user_open_ticket(data, chat_id):
    uid = str(chat_id)
    for tid, t in data["tickets"].items():
        if str(t.get("user_id"))==uid and t.get("status")=="open":
            return tid, t
    return None, None

def create_ticket(data, chat_id, first_msg, uinfo=None):
    data["ticket_counter"] = data.get("ticket_counter",0) + 1
    tid   = f"TKT{data['ticket_counter']}"
    name  = (uinfo or {}).get("first_name","کاربر")
    uname = (uinfo or {}).get("username","")
    data["tickets"][tid] = {
        "id":       tid,
        "user_id":  chat_id,
        "name":     name,
        "username": uname,
        "status":   "open",
        "created":  datetime.now().isoformat(),
        "messages": [{"from":"user","text":first_msg,"time":datetime.now().isoformat()}]
    }
    save_data(data)
    return tid

def send_support_menu(chat_id):
    data   = load_data()
    tid, t = get_user_open_ticket(data, chat_id)
    if tid:
        send(chat_id,
            f"*📞 پشتیبانی\n\n"
            f"شما یک گفتگوی باز دارید: #{tid}\n\n"
            f"پیام خود را ارسال کنید تا پشتیبان پاسخ دهد.*",
            kb(["❌ بستن تیکت","🔙 بازگشت به منوی اصلی 🏠"])
        )
    else:
        send(chat_id,
            "*📞 پشتیبانی\n\n"
            "پیام خود را بنویسید تا گفتگو با پشتیبان شروع شود.\n\n"
            "💡 سوال، مشکل یا درخواست خود را ارسال کنید:*",
            kb(["🔙 بازگشت به منوی اصلی 🏠"])
        )

def handle_support_message(chat_id, text, data, states, uinfo=None):
    uid = str(chat_id)

    if text=="❌ بستن تیکت":
        tid, t = get_user_open_ticket(data, chat_id)
        if tid:
            data["tickets"][tid]["status"]="closed"; save_data(data)
            states.pop(uid,None)
            send(chat_id, f"*✅ گفتگو #{tid} بسته شد.*", BACK_BTN_USER)
            for aid in ADMIN_IDS:
                send(aid, f"*🔴 تیکت #{tid} توسط کاربر بسته شد.*")
        else:
            states.pop(uid,None)
            send(chat_id, "*هیچ گفتگوی بازی وجود ندارد.*", BACK_BTN_USER)
        return

    tid, t = get_user_open_ticket(data, chat_id)
    if not tid:
        tid   = create_ticket(data, chat_id, text, uinfo)
        uname = (uinfo or {}).get("username","")
        uname_str = f"@{uname}" if uname else str(chat_id)
        name  = (uinfo or {}).get("first_name","کاربر")
        send(chat_id,
            f"*✅ گفتگو #{tid} شروع شد!\n\n"
            f"پشتیبان پیام شما را دریافت کرد و به زودی پاسخ می‌دهد.\n"
            f"می‌توانید ادامه گفتگو را همینجا دنبال کنید.*",
            kb(["❌ بستن تیکت","🔙 بازگشت به منوی اصلی 🏠"])
        )
        for aid in ADMIN_IDS:
            send(aid,
                f"*🎫 گفتگوی جدید #{tid}\n\n"
                f"👤 {name} ({uname_str})\n"
                f"🆔 آیدی: {chat_id}\n\n"
                f"💬 پیام:\n{text}*",
                {"inline_keyboard":[
                    [{"text":f"↩️ پاسخ به #{tid}","callback_data":f"reply_ticket|{tid}"}],
                    [{"text":f"🔴 بستن #{tid}","callback_data":f"close_ticket|{tid}"}]
                ]}
            )
    else:
        t["messages"].append({"from":"user","text":text,"time":datetime.now().isoformat()})
        save_data(data)
        send(chat_id, "*✅ پیام ارسال شد. منتظر پاسخ باشید.*",
             kb(["❌ بستن تیکت","🔙 بازگشت به منوی اصلی 🏠"]))
        uname     = t.get("username","")
        uname_str = f"@{uname}" if uname else str(chat_id)
        for aid in ADMIN_IDS:
            send(aid,
                f"*💬 پیام جدید در #{tid}\n\n"
                f"👤 {t.get('name','کاربر')} ({uname_str})\n\n"
                f"📩 پیام:\n{text}*",
                {"inline_keyboard":[
                    [{"text":f"↩️ پاسخ به #{tid}","callback_data":f"reply_ticket|{tid}"}],
                    [{"text":f"🔴 بستن #{tid}","callback_data":f"close_ticket|{tid}"}]
                ]}
            )

def admin_reply_to_ticket(admin_chat_id, tid, reply_text, data):
    t = data["tickets"].get(tid)
    if not t:
        send(admin_chat_id, f"*⚠️ تیکت #{tid} یافت نشد.*"); return
    if t.get("status")=="closed":
        send(admin_chat_id, f"*⚠️ تیکت #{tid} بسته است.*"); return
    t["messages"].append({"from":"admin","text":reply_text,"time":datetime.now().isoformat()})
    save_data(data)
    user_id = t.get("user_id")
    send(user_id,
        f"*📩 پاسخ پشتیبانی - گفتگو #{tid}\n\n"
        f"━━━━━━━━━━━━\n\n"
        f"{reply_text}\n\n"
        f"━━━━━━━━━━━━\n"
        f"می‌توانید پاسخ دهید یا گفتگو را ببندید.*",
        kb(["❌ بستن تیکت","🔙 بازگشت به منوی اصلی 🏠"])
    )
    send(admin_chat_id,
        f"*✅ پاسخ به #{tid} ارسال شد.*",
        {"inline_keyboard":[
            [{"text":f"↩️ پاسخ دیگر به #{tid}","callback_data":f"reply_ticket|{tid}"}],
            [{"text":f"🔴 بستن #{tid}","callback_data":f"close_ticket|{tid}"}]
        ]}
    )

# ══════════════════════════════════════════
#  ORDER
# ══════════════════════════════════════════
def send_service_info(chat_id, key):
    data  = load_data()
    s     = data["settings"][key]
    title = s.get("label") or key
    unit  = s.get("unit", "عدد")
    fixed = s["min"] == s["max"]          # تعداد ثابت (مثلاً فقط ۱۰۰۰)
    if s.get("head") and fixed:
        text = f"🎬 {s['head']} (تومان {calc_price(s, s['min']):,})\n\n{s.get('desc', '')}"
    else:
        head = s.get("head") or title
        if fixed:
            price_line = f"• تعداد ثابت: {s['min']:,}  |  قیمت: {calc_price(s, s['min']):,} تومان"
        else:
            price_line = (f"• حداقل: {s['min']:,}  |  حداکثر: {s['max']:,}\n"
                          f"• قیمت هر ۱۰۰۰ {unit}: {s['price_per_1000']:,} تومان")
        notes = f"\n\n📌 نکات\n{s['desc']}" if s.get("desc") else ""
        text  = f"📦 {head}\n{price_line}{notes}"
    if fixed:
        ask = "🔗 لینک یا آیدی مورد نظر را ارسال کنید:"
    else:
        ask = (f"⚠️ در هر بار سفارش از {s['min']:,} تا {s['max']:,} {unit} میتونید ثبت کنید\n\n"
               f"🔢 تعداد {unit} موردنظر را ارسال کنید:")
    send(chat_id, f"*{text}\n\n{ask}*",
         kb(["🔙 مرحله قبل"], ["🔙 بازگشت به منوی اصلی 🏠"]))

def check_stock_and_start(chat_id, key, data, states):
    s = data["settings"].get(key,{})
    if not s.get("enabled",True):
        send(chat_id,"*⚠️ این سرویس موقتاً غیرفعال است.*"); return
    stock = s.get("stock",999999)
    if stock<=0:
        send(chat_id,"*⚠️ موجودی این سرویس تمام شده. لطفاً بعداً مراجعه کنید.*"); return
    if s["min"] == s["max"]:
        # تعداد ثابت → مستقیم می‌رود سراغ لینک
        if s["min"] > stock:
            send(chat_id,"*⚠️ موجودی این سرویس کافی نیست. لطفاً بعداً مراجعه کنید.*"); return
        states[str(chat_id)] = f"order_link|{key}|{s['min']}"
    else:
        states[str(chat_id)] = f"order_qty|{key}"
    send_service_info(chat_id, key)

def send_invoice(chat_id, key, qty, price, link, comments=None):
    data = load_data()
    label = svc_label(data,key)
    data["order_counter"] = data.get("order_counter",0)+1
    oid  = data["order_counter"]
    order = {
        "id":      f"ORK{oid}",
        "user_id": chat_id,
        "service": label,
        "key":     key,
        "amount":  qty,
        "price":   price,
        "link":    link,
        "status":  "pending_payment",
        "date":    datetime.now().isoformat()
    }
    if comments:
        order["comments"] = comments
    data["orders"].append(order)
    save_data(data)
    desc = f"📦 سرویس: {label}\n🔢 تعداد: {qty:,}\n🔗 لینک: {link}\n🆔 سفارش: ORK{oid}"
    if comments:
        desc += f"\n✍️ کامنت‌ها: {len(comments.splitlines())} مورد"
    result = requests.post(f"{BASE_URL}/sendInvoice", json={
        "chat_id":        chat_id,
        "title":          f"🛒 {label}",
        "description":    desc,
        "payload":        f"order_{oid}",
        "provider_token": PROVIDER_TOKEN,
        "currency":       "IRR",
        "prices":         [{"label":label,"amount":price*10}],
        "start_parameter":"pay"
    }, timeout=15).json()
    print(f"INVOICE RESULT = {result}")
    if not result.get("ok"):
        send(chat_id,"*❌ خطا در ارسال فاکتور! با پشتیبانی تماس بگیرید: @ARKA_SUPPORT_IR*")

def activate_order(data, target, via_wallet=False):
    """بعد از پرداخت موفق (درگاه یا کیف پول): وضعیت، آمار، موجودی و اعلان کاربر/ادمین."""
    chat_id = target["user_id"]
    target["status"]    = "pending"
    target["paid_with"] = "wallet" if via_wallet else "gateway"
    today = get_today()
    target["stat_day"]  = today
    data["stats"]["total_orders"]  += 1
    data["stats"]["total_revenue"] += target["price"]
    uid = str(chat_id)
    if uid in data["users"]:
        data["users"][uid]["orders"]      = data["users"][uid].get("orders", 0) + 1
        data["users"][uid]["total_spent"] = data["users"][uid].get("total_spent", 0) + target["price"]
    if today not in data["stats"]["daily_stats"]:
        data["stats"]["daily_stats"][today] = {"orders": 0, "revenue": 0}
    data["stats"]["daily_stats"][today]["orders"]  += 1
    data["stats"]["daily_stats"][today]["revenue"] += target["price"]
    sset = data["settings"].get(target.get("key", ""))
    if isinstance(sset, dict):
        cur = sset.get("stock", 999999)
        if cur < 999999:                       # موجودی نامحدود کم نمی‌شود
            sset["stock"] = max(0, cur - target["amount"])
    save_data(data)
    pay_line = ""
    if via_wallet:
        bal = data["users"].get(uid, {}).get("wallet", 0)
        pay_line = f"💼 پرداخت از کیف پول (موجودی باقی‌مانده: {bal:,} تومان)\n"
    send(chat_id,
        f"*🎉 پرداخت موفق! سفارش ثبت شد!\n\n"
        f"━━━━━━━━━━━━\n\n"
        f"🆔 شماره سفارش: {target['id']}\n"
        f"📦 سرویس: {target['service']}\n"
        f"🔢 تعداد: {target['amount']:,}\n"
        f"🔗 لینک: {target['link']}\n"
        f"💰 مبلغ: {target['price']:,} تومان\n"
        f"{pay_line}\n"
        f"⏳ سفارش در حال پردازش است.\n"
        f"💌 پشتیبانی: @ARKA_SUPPORT_IR*"
    )
    for aid in ADMIN_IDS:
        try:
            cmt = ""
            if target.get("comments"):
                cmt = f"\n✍️ کامنت‌ها:\n{target['comments'][:500]}"
            send(aid,
                f"*🔔 سفارش جدید!{' (کیف پول 💼)' if via_wallet else ''}\n\n"
                f"🆔 {target['id']} | 👤 {chat_id}\n"
                f"📦 {target['service']} | {target['amount']:,}\n"
                f"🔗 {target['link']}\n"
                f"💰 {target['price']:,} تومان{cmt}*",
                {"inline_keyboard":[[
                    {"text":"✅ تکمیل سفارش","callback_data":f"complete|{target['id']}"},
                    {"text":"❌ لغو سفارش",  "callback_data":f"ocancel|{target['id']}"}
                ]]}
            )
        except: pass

def register_successful_order(chat_id, payload):
    data = load_data()
    order_num = None
    try: order_num = int(payload.replace("order_",""))
    except: pass
    target = None
    for o in data["orders"]:
        if o["id"]==f"ORK{order_num}" and o["user_id"]==chat_id and o["status"]=="pending_payment":
            target=o; break
    if not target:
        for o in reversed(data["orders"]):
            if o["user_id"]==chat_id and o["status"]=="pending_payment":
                target=o; break
    if target:
        activate_order(data, target)
    else:
        send(chat_id,"*✅ پرداخت انجام شد!\n\n⏳ سفارش در حال پردازش است.\n💌 @ARKA_SUPPORT_IR*")

def complete_order(order_id, notify_chat=None):
    data   = load_data()
    target = next((o for o in data["orders"] if o["id"]==order_id),None)
    if not target: return False,"سفارش یافت نشد."
    if target["status"]=="done": return False,"این سفارش قبلاً تکمیل شده."
    if target["status"]=="cancelled": return False,"این سفارش لغو شده است."
    target["status"]="done"; save_data(data)
    masked=mask_user_id(target["user_id"]); jalali_now=now_jalali_str()
    channel=data["settings"]["channel"]
    tag = "\n🧪 (سفارش آزمایشی)" if target.get("fake") and MARK_FAKE_IN_CHANNEL else ""
    try:
        r = requests.post(f"{BASE_URL}/sendMessage", json={
            "chat_id":    channel,
            "text":       f"*✅ گزارش خرید موفق\n\n"
                          f"📦 سرویس: {target['service']}\n"
                          f"🔢 تعداد: {target['amount']:,} عدد\n"
                          f"💰 مبلغ: {target['price']:,} تومان\n"
                          f"👤 کاربر: {masked}\n"
                          f"🕒 تاریخ: {jalali_now}\n\n"
                          f"━━━━━━━━━━━━━━\n"
                          f"🟢 وضعیت سفارش: موفق{tag}*",
            "parse_mode": "Markdown",
            "reply_markup":{"inline_keyboard":[[{"text":"ربات ممبر | بازدید ایران 🚀","url":f"https://ble.ir/{BOT_USERNAME}"}]]}
        }, timeout=10).json()
        if not r.get("ok"):
            raise Exception(r.get("description", r))
    except Exception as e:
        print(f"channel report error: {e}")
        if notify_chat:
            send(notify_chat, f"*⚠️ سفارش تکمیل شد ولی پیام کانال ارسال نشد:\n{e}*")
    return True, target

def cancel_order_refund(order_id, reason):
    """لغو سفارش توسط ادمین: مبلغ به کیف پول کاربر برمی‌گردد و علت برای کاربر ارسال می‌شود."""
    data   = load_data()
    target = next((o for o in data["orders"] if o["id"]==order_id),None)
    if not target: return False,"سفارش یافت نشد."
    st = target.get("status")
    if st=="cancelled": return False,"این سفارش قبلاً لغو شده."
    if st=="done":      return False,"این سفارش تکمیل شده و قابل لغو نیست."
    if st!="pending":   return False,"این سفارش هنوز پرداخت نشده و نیازی به لغو ندارد."
    price = target.get("price",0)
    uid   = str(target["user_id"])
    bal   = 0
    if not target.get("fake"):
        u = data["users"].setdefault(uid, {
            "chat_id": target["user_id"], "first_seen": datetime.now().isoformat(),
            "last_seen": datetime.now().isoformat(), "orders": 0, "total_spent": 0,
            "blocked": False, "username": "", "first_name": "", "wallet": 0})
        u["wallet"]      = u.get("wallet",0) + price
        u["orders"]      = max(0, u.get("orders",0) - 1)
        u["total_spent"] = max(0, u.get("total_spent",0) - price)
        bal = u["wallet"]
        stt = data["stats"]                     # این فروش دیگر جزو آمار حساب نمی‌شود
        stt["total_orders"]  = max(0, stt["total_orders"] - 1)
        stt["total_revenue"] = max(0, stt["total_revenue"] - price)
        day = target.get("stat_day") or target.get("date","")[:10]
        d   = stt["daily_stats"].get(day)
        if d:
            d["orders"]  = max(0, d.get("orders",0) - 1)
            d["revenue"] = max(0, d.get("revenue",0) - price)
        sset = data["settings"].get(target.get("key",""))
        if isinstance(sset, dict) and sset.get("stock",999999) < 999999:
            sset["stock"] += target.get("amount",0)
    target["status"]        = "cancelled"
    target["cancel_reason"] = reason
    target["cancelled_at"]  = datetime.now().isoformat()
    save_data(data)
    if not target.get("fake"):
        send(target["user_id"],
            f"*❌ سفارش شما لغو شد\n\n"
            f"🆔 شماره سفارش: {target['id']}\n"
            f"📦 سرویس: {target['service']}\n"
            f"🔢 تعداد: {target['amount']:,}\n\n"
            f"📝 علت لغو:\n{reason}\n\n"
            f"💰 مبلغ {price:,} تومان به کیف پول شما در ربات برگشت.\n"
            f"💼 موجودی کیف پول: {bal:,} تومان\n\n"
            f"می‌توانید دوباره سفارش دهید؛ موقع خرید امکان پرداخت با کیف پول را خواهید داشت. 🌷*",
            BACK_BTN_USER)
    return True, target

def _get_pending_buy(chat_id, data):
    uid = str(chat_id)
    pb  = pending_buy.get(uid)
    if not pb or states.get(uid) != "order_pay":
        send(chat_id, "*⚠️ این درخواست منقضی شده. لطفاً دوباره از منوی خدمات سفارش دهید.*", BACK_BTN_USER)
        return None
    s = data["settings"].get(pb["key"])
    if not isinstance(s, dict) or not s.get("enabled", True):
        pending_buy.pop(uid, None); states.pop(uid, None)
        send(chat_id, "*⚠️ این سرویس موقتاً غیرفعال است.*", BACK_BTN_USER); return None
    if pb["qty"] > s.get("stock", 999999):
        pending_buy.pop(uid, None); states.pop(uid, None)
        send(chat_id, "*⚠️ موجودی این سرویس تغییر کرد. لطفاً دوباره سفارش دهید.*", BACK_BTN_USER); return None
    return pb, s, calc_price(s, pb["qty"])

def pay_with_wallet(chat_id):
    uid  = str(chat_id)
    data = load_data()
    got  = _get_pending_buy(chat_id, data)
    if not got: return
    pb, s, price = got
    u = data["users"].get(uid)
    if not u or u.get("wallet", 0) < price:
        pending_buy.pop(uid, None); states.pop(uid, None)
        send(chat_id, "*⚠️ موجودی کیف پول کافی نیست.*", BACK_BTN_USER); return
    u["wallet"] -= price
    data["order_counter"] = data.get("order_counter", 0) + 1
    oid = data["order_counter"]
    order = {
        "id":      f"ORK{oid}",
        "user_id": chat_id,
        "service": svc_label(data, pb["key"]),
        "key":     pb["key"],
        "amount":  pb["qty"],
        "price":   price,
        "link":    pb["link"],
        "status":  "pending_payment",
        "date":    datetime.now().isoformat()
    }
    if pb.get("comments"):
        order["comments"] = pb["comments"]
    data["orders"].append(order)
    pending_buy.pop(uid, None); states.pop(uid, None)
    activate_order(data, order, via_wallet=True)

def pay_online(chat_id):
    data = load_data()
    got  = _get_pending_buy(chat_id, data)
    if not got: return
    pb, s, price = got
    uid = str(chat_id)
    pending_buy.pop(uid, None); states.pop(uid, None)
    send_invoice(chat_id, pb["key"], pb["qty"], price, pb["link"], comments=pb.get("comments"))

# ══════════════════════════════════════════
#  ADMIN TOOLS  |  پاک‌سازی کامل دیتا + سفارش فیک
# ══════════════════════════════════════════
def send_wipe_step(chat_id, step):
    if step == 1:
        text = ("*☢️ پاک‌سازی کامل دیتای ربات\n\n"
                "با این کار همه‌چیز پاک می‌شود:\n"
                "👥 کاربران و کیف پول‌ها\n"
                "📦 سفارش‌ها\n"
                "🎫 تیکت‌ها\n"
                "📊 آمار\n"
                "🛍 بخش خدمات و کاتالوگ\n\n"
                "ربات به حالت اولیه برمی‌گردد.\n"
                "⚠️ این کار برگشت‌پذیر نیست! اگر لازم است، اول از بخش 💾 بکاپ فایل‌ها را بگیرید.\n\n"
                "🔴 تأیید ۱ از ۳ — ادامه می‌دهید؟*")
        rows = [[{"text": "✅ بله، ادامه", "callback_data": "wipe|1"},
                 {"text": "❌ انصراف",    "callback_data": "wipe|cancel"}]]
    elif step == 2:
        text = ("*🔴 تأیید ۲ از ۳\n\n"
                "مطمئنی؟ کاربران، کیف پول‌ها، سفارش‌ها و تمام خدمات پاک می‌شوند.*")
        rows = [[{"text": "❌ انصراف",      "callback_data": "wipe|cancel"},
                 {"text": "✅ بله، مطمئنم", "callback_data": "wipe|2"}]]
    else:
        text = ("*🔴 تأیید ۳ از ۳ (آخرین مرحله)\n\n"
                "با زدن دکمه‌ی پایین، همه‌ی دیتا همین لحظه پاک می‌شود و راه برگشتی نیست!*")
        rows = [[{"text": "❌ انصراف", "callback_data": "wipe|cancel"}],
                [{"text": "☢️ بله، همه‌چیز پاک شود", "callback_data": "wipe|3"}]]
    send(chat_id, text, {"inline_keyboard": rows})

def wipe_all_data():
    save_data(default_data())
    states.clear(); last_folder.clear(); admin_tmp.clear()
    pending_buy.clear(); wipe_state.clear()

def send_fake_service_list(chat_id, data):
    nodes = data["catalog"]["nodes"]
    rows  = []
    for n in sorted((n for n in nodes.values() if n["type"] == "service"), key=lambda n: int(n["id"])):
        if n.get("key") in data["settings"]:
            rows.append([{"text": n["title"], "callback_data": f"fake_svc|{n['id']}"}])
    if not rows:
        send(chat_id, "*⚠️ هیچ سرویسی در کاتالوگ نیست.*", BACK_BTN); return
    send(chat_id,
         "*🧪 سفارش فیک (تست)\n\n"
         "یک سرویس انتخاب کنید. سفارش فیک روی آمار، موجودی و کیف پول اثری ندارد.\n"
         "با زدن «✅ تکمیل سفارش» گزارش خرید داخل کانال ارسال می‌شود تا ظاهرش را ببینید.*",
         {"inline_keyboard": rows})

def create_fake_order(chat_id, key, qty):
    data = load_data()
    s    = data["settings"][key]
    data["order_counter"] = data.get("order_counter", 0) + 1
    oid  = f"TEST{data['order_counter']}"
    order = {
        "id": oid, "user_id": chat_id, "service": svc_label(data, key), "key": key,
        "amount": qty, "price": calc_price(s, qty), "link": FAKE_LINK,
        "status": "pending", "fake": True, "date": datetime.now().isoformat()
    }
    data["orders"].append(order)
    save_data(data)
    send(chat_id,
         f"*🧪 سفارش فیک ثبت شد\n\n"
         f"🆔 {oid}\n"
         f"📦 {order['service']}\n"
         f"🔢 {qty:,}\n"
         f"💰 {order['price']:,} تومان\n\n"
         f"👇 برای دیدن پیام کانال روی «تکمیل سفارش» بزنید.*",
         {"inline_keyboard": [[
             {"text": "✅ تکمیل سفارش", "callback_data": f"complete|{oid}"},
             {"text": "❌ لغو سفارش",   "callback_data": f"ocancel|{oid}"}
         ]]})

# ══════════════════════════════════════════
#  ADMIN PANEL
# ══════════════════════════════════════════
def send_admin_panel(chat_id):
    data = load_data()
    s  = data["settings"]
    st = data["stats"]
    td = st["daily_stats"].get(get_today(),{})
    open_t   = sum(1 for t in data["tickets"].values() if t.get("status")=="open")
    closed_t = sum(1 for t in data["tickets"].values() if t.get("status")=="closed")
    send(chat_id,
        f"*🔧 پنل مدیریت ربات آرکا\n\n"
        f"━━━━━━━━━━━━\n"
        f"👥 کاربران: {st['total_users']:,}  |  📦 سفارشات: {st['total_orders']:,}\n"
        f"💰 درآمد کل: {st['total_revenue']:,} تومان\n"
        f"📅 امروز: {td.get('orders',0):,} سفارش | {td.get('revenue',0):,} تومان\n"
        f"🎫 تیکت باز: {open_t} | بسته: {closed_t}\n"
        f"🔒 جوین اجباری: {'✅' if s['forced_join'] else '❌'}\n"
        f"━━━━━━━━━━━━\n\n"
        f"👇 یک بخش را انتخاب کنید:*",
        kb(
            ["📊 آمار و گزارشات",   "📦 مدیریت سفارشات"],
            ["🛍 مدیریت کاتالوگ",  "🧪 سفارش فیک (تست)"],
            ["👥 مدیریت کاربران",  "📨 پیام همگانی"],
            ["🔒 جوین اجباری",     "📢 تنظیمات کانال"],
            ["🗑 پاک‌سازی تاریخچه", "💾 بکاپ"],
            ["🎫 تیکت‌های باز",    "🔴 تیکت‌های بسته"],
            ["☢️ پاک‌سازی کامل دیتای ربات"],
            ["🏠 خروج از پنل ادمین"]
        )
    )

def send_open_tickets(chat_id, data):
    tickets = [(tid,t) for tid,t in data["tickets"].items() if t.get("status")=="open"]
    if not tickets:
        send(chat_id,"*هیچ تیکت باز فعالی وجود ندارد.*",BACK_BTN); return
    send(chat_id,f"*🎫 تیکت‌های باز: {len(tickets)} مورد*")
    for tid,t in tickets[-20:]:
        uname_str = f"@{t['username']}" if t.get("username") else str(t.get("user_id",""))
        last_msg  = t["messages"][-1]["text"][:80] if t.get("messages") else "-"
        send(chat_id,
            f"*🎫 #{tid} | {t.get('name','?')} ({uname_str})\n"
            f"💬 {len(t.get('messages',[]))} پیام | آخرین: {last_msg}*",
            {"inline_keyboard":[
                [{"text":f"↩️ پاسخ به #{tid}","callback_data":f"reply_ticket|{tid}"}],
                [{"text":f"🔴 بستن #{tid}","callback_data":f"close_ticket|{tid}"}]
            ]}
        )
    send(chat_id,"👆 تیکت‌های باز", kb(["🗑 ریست تیکت‌های باز","🔙 بازگشت"]))

def send_closed_tickets(chat_id, data):
    tickets = [(tid,t) for tid,t in data["tickets"].items() if t.get("status")=="closed"]
    if not tickets:
        send(chat_id,"*هیچ تیکت بسته‌ای وجود ندارد.*",BACK_BTN); return
    send(chat_id,f"*🔴 تیکت‌های بسته: {len(tickets)} مورد*")
    for tid,t in tickets[-20:]:
        uname_str = f"@{t['username']}" if t.get("username") else str(t.get("user_id",""))
        send(chat_id,
            f"*🔴 #{tid} | {t.get('name','?')} ({uname_str}) | {len(t.get('messages',[]))} پیام*"
        )
    send(chat_id,"👆 تیکت‌های بسته", kb(["🗑 ریست تیکت‌های بسته","🔙 بازگشت"]))

# ══════════════════════════════════════════
#  CATALOG  |  مشاهده و خرید خدمات (قابل ویرایش توسط ادمین)
# ══════════════════════════════════════════
last_folder    = {}     # آخرین بخشی که کاربر باز کرده
admin_tmp      = {}     # اطلاعات موقت هنگام ساخت دکمه/سرویس توسط ادمین
CURRENT_MSG_ID = None   # آیدی پیام فعلی (برای پاک کردن پیام رمز)

RESERVED_TITLES = {
    "🔙 مرحله قبل", "🔙 بازگشت به منوی اصلی 🏠", "🔙 بازگشت", "🏠 بازگشت",
    "❌ بستن تیکت", "❌ لغو", "مشاهده و خرید خدمات 🛍", "حساب کاربری 👤",
    "پیگیری سفارش 🔎", "قوانین ⚖️", "📞 پشتیبانی",
    "سفارش بازدید 👁️", "سفارش ممبر 👥", "/start", "/admin", "/cancel",
}

def fa_to_en(s):
    """تبدیل اعداد فارسی/عربی به انگلیسی"""
    return s.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))

def to_int(s):
    return int(fa_to_en(s).replace(",", "").replace("،", "").strip())

def svc_label(data, key):
    return data["settings"].get(key, {}).get("label") or key

def svc_price(s):
    return s.get("fixed_price") or s.get("price_per_1000", 0)

APARAT_DESC = (
    "⏳ زمان استارت سرویس :5 الی 12 ساعت\n"
    "✅ زمان تکمیل : {finish}\n"
    "👦 کیفیت سرویس : متوسط\n"
    "⛔ ریزش : ندارد\n"
    "🔗 نحوه درج لینک : لینک با فرمت زیر درج گردد\n\n"
    "https://www.aparat.com/v/NnpWU\n\n"
    "نکات مهم :\n"
    "🔰 مدت زمان ویدیو باید بالای {over} دقیقه باشد\n"
    "🔰 تعداد {qty} = {hours} ساعت واچ تایم\n"
    "🔰 بعد از ثبت سفارش، امکان لغو و عودت وجه وجود ندارد\n"
    "📌در صورت نیاز به بررسی واچ تایم از سمت ما، فرستادن ایدی و رمز کانال الزامی است\n"
    "⚠️ هیچ گونه تضمینی بابت کسب درآمد از آپارات وجود ندارد.\n"
    "📌قبل از خرید، موارد بالا را خوانده و پذیرفته اید! اگر موافق توضیحات بالا نیستید، سفارش ثبت نکنید."
)

# (ایموجی دکمه، ساعت واچ‌تایم، طول ویدیو، حداقل مدت ویدیو، تعداد ثابت سفارش، قیمت کل بسته (تومان)، زمان تکمیل)
APARAT_WATCH_PACKAGES = [
    ("⏱", 50,   "3 دقیقه",     3,  1000, 36000,   "24 تا 72 ساعت"),
    ("⏰", 100,  "7-10 دقیقه",  7,  1000, 54000,   "24 تا 72 ساعت"),
    ("🔥", 200,  "15 دقیقه",    12, 1000, 99000,   "24 تا 72 ساعت"),
    ("💎", 500,  "30 دقیقه",    30, 1000, 252000,  "48 تا 72 ساعت"),
    ("🚀", 1000, "60 دقیقه",    60, 1000, 639000,  "24 تا 72 ساعت"),
    ("👑", 3000, "60 دقیقه",    60, 1,    2458000, "24 تا 72 ساعت"),  # تعداد ثابت ۱ بسته = ۳۰۰۰ ساعت
]

# سرویس‌های لایک/کامنت آپارات: (کلید، عنوان دکمه، لیبل، قیمت هر۱۰۰۰، حداقل، حداکثر، توضیحات، پلتفرم)
APARAT_EXTRA = [
    (
        "aparat_view",
        "👁 بازدید آپارات",
        "بازدید آپارات",
        16000, 1000, 1000000,
        "بازدید آپارات (تومان 16,000 برای هر ۱۰۰۰)\n\n"
        "🕑 زمان شروع : 12 الی 24 ساعت\n\n"
        "🩸 میزان ریزش : ندارد\n\n"
        "👌 کیفیت سرویس : خوب\n\n"
        "✅ زمان تکمیل : 24 تا 48 ساعت\n\n"
        "🔗 نمونه لینک : لینک ویدیو آپارات\n\n"
        "https://www.aparat.com/v/NnpWU",
        "aparat"
    ),
    (
        "aparat_view_short",
        "📱 بازدید ویدیو‌کوتاه آپارات",
        "بازدید ویدیو‌کوتاه آپارات",
        17000, 900, 100000,
        "بازدید ویدیو‌کوتاه آپارات (تومان 17,000 برای هر ۱۰۰۰)\n\n"
        "🕑 زمان شروع : 12 الی 24 ساعت\n\n"
        "🩸 میزان ریزش : ندارد\n\n"
        "👌 کیفیت سرویس : خوب\n\n"
        "✅ زمان تکمیل : 24 تا 48 ساعت\n\n"
        "🔗 نمونه لینک :\n\n"
        "https://aparat.com/shorts/1234",
        "aparat_short"
    ),
    (
        "aparat_view_fast",
        "⚡ بازدید آپارات سریع",
        "بازدید آپارات سریع",
        30000, 1000, 1000000,
        "بازدید آپارات سریع ⭐ (تومان 30,000 برای هر ۱۰۰۰)\n\n"
        "🕑 زمان شروع : آنی\n\n"
        "🩸 میزان ریزش : ندارد\n\n"
        "👌 کیفیت سرویس : خوب\n\n"
        "✅ زمان تکمیل : 12 تا 24 ساعت\n\n"
        "🔗 نمونه لینک :\n\n"
        "https://www.aparat.com/v/NnpWU",
        "aparat"
    ),
    (
        "aparat_view_s2",
        "🛰 بازدید آپارات - سرور2",
        "بازدید آپارات - سرور2",
        156000, 100, 2000,
        "بازدید آپارات - سرور2 (تومان 156,000 برای هر ۱۰۰۰)\n\n"
        "🕑 زمان شروع : آنی\n\n"
        "🩸 میزان ریزش : ندارد\n\n"
        "👌 کیفیت سرویس : عالی\n\n"
        "✅ زمان تکمیل : 12 تا 24 ساعت\n\n"
        "🔗 نمونه لینک :\n\n"
        "https://www.aparat.com/v/NnpWU",
        "aparat"
    ),
    (
        "aparat_like",
        "👍 لایک آپارات",
        "لایک آپارات",
        57000, 100, 500000,
        "لایک آپارات (تومان 57,000 برای هر ۱۰۰۰)\n\n"
        "🕑 زمان شروع : 1 الی 24 ساعت\n\n"
        "🚀 سرعت ارسال : 1 الی 5کا در 24 ساعت\n\n"
        "🩸 میزان ریزش : ندارد\n\n"
        "👌 کیفیت سرویس : کیفیت مناسب\n\n"
        "✅ زمان تکمیل : 24 تا 48 ساعت\n\n"
        "🔗 نمونه لینک : https://www.aparat.com/v/NnpWU",
        "aparat"
    ),
    (
        "aparat_like_short",
        "📱 لایک ویدیو‌کوتاه آپارات",
        "لایک ویدیو‌کوتاه آپارات",
        72000, 100, 100000,
        "لایک ویدیو‌کوتاه آپارات (تومان 72,000 برای هر ۱۰۰۰)\n\n"
        "🕑 زمان شروع : 1 الی 24 ساعت\n\n"
        "🚀 سرعت ارسال : 1 الی 5کا در 24 ساعت\n\n"
        "🩸 میزان ریزش : ندارد\n\n"
        "👌 کیفیت سرویس : کیفیت مناسب\n\n"
        "✅ زمان تکمیل : 24 تا 48 ساعت\n\n"
        "🔗 نمونه لینک :\n\n"
        "https://aparat.com/shorts/123456",
        "aparat_short"
    ),
    (
        "aparat_like_ex",
        "⭐ لایک آپارات | اختصاصی",
        "لایک آپارات | اختصاصی",
        96000, 1000, 10000,
        "لایک آپارات | اختصاصی ⭐ (تومان 96,000 برای هر ۱۰۰۰)\n\n"
        "افزایش لایک ویدیو آپارات\n"
        "زمان انجام سفارش بین 2 تا 24 ساعت\n\n"
        "🔗 لینک ویدیو مورد نظر را وارد کنید:\n"
        "https://www.aparat.com/v/NnpWU\n\n"
        "🩸 میزان ریزش : ندارد\n"
        "👌 کیفیت سرویس : کیفیت مناسب",
        "aparat"
    ),
    (
        "aparat_repost",
        "🔄 بازنشر ویدیو آپارات",
        "بازنشر ویدیو آپارات",
        220000, 100, 50000,
        "بازنشر ویدیو آپارات (تومان 220,000 برای هر ۱۰۰۰)\n\n"
        "🕑 زمان شروع : 1 الی 24 ساعت\n\n"
        "🩸 میزان ریزش : ندارد\n\n"
        "👌 کیفیت سرویس : کیفیت مناسب\n\n"
        "✅ زمان تکمیل : 24 تا 48 ساعت\n\n"
        "🔗 نمونه لینک :\n\n"
        "https://www.aparat.com/v/NnpWU\n\n"
        "نکته: حتما در تنظیمات اعلانات کانال آپاراتی بخش {دریافت اعلان های بازنشر ویدیو} را روشن کنید.",
        "aparat"
    ),
    (
        "aparat_comment_rand",
        "💬 کامنت رندوم آپارات",
        "کامنت رندوم آپارات",
        4800000, 10, 100,
        "کامنت رندوم آپارات (تومان 4,800,000 برای هر ۱۰۰۰)\n\n"
        "🕑 زمان شروع : 6 تا 12 ساعت\n"
        "✅ زمان تکمیل : 24 تا 48 ساعت\n"
        "🩸 میزان ریزش : ندارد\n"
        "👌 کیفیت سرویس : ایرانی\n"
        "🔗 نمونه لینک : لینک ویدیو آپارات\n"
        "🔗مثال: https://www.aparat.com/v/NnpWU\n\n"
        "نکات مهم :\n"
        "📌 بخش کامنت ها باز باشد",
        "aparat"
    ),
    (
        "aparat_comment_custom",
        "✍️ کامنت دلخواه آپارات",
        "کامنت دلخواه آپارات",
        6000000, 10, 100,
        "کامنت دلخواه آپارات (تومان 6,000,000 برای هر ۱۰۰۰)\n\n"
        "🕑 زمان شروع : 6 تا 12 ساعت\n"
        "✅ زمان تکمیل : 24 تا 48 ساعت\n"
        "🩸 میزان ریزش : ندارد\n"
        "👌 کیفیت سرویس : ایرانی\n"
        "🔗 نمونه لینک : لینک ویدیو آپارات\n"
        "🔗مثال: https://www.aparat.com/v/NnpWU\n\n"
        "نکات مهم :\n"
        "📌 لینک پست آپارات خود را به طور کامل ثبت کنید.\n"
        "📌 بعد از هر کامنت اینتر بزنید\n"
        "📌سفارش همزمان برای یک لینک از یک سرویس ثبت نکنید تا سفارش قبلی شما برای همان لینک تکمیل شود.\n"
        "📌 تعداد کامنت‌هایی که می‌نویسید باید دقیقاً برابر تعداد سفارش باشد.",
        "aparat"
    ),
    (
        "aparat_follow_cheap",
        "💸 فالوور آپارات ارزان - ریزش دار",
        "فالوور آپارات ارزان - ریزش دار",
        135000, 5000, 10000,
        "فالوور آپارات ارزان - ریزش دار (تومان 135,000 برای هر ۱۰۰۰)\n\n"
        "🕑 زمان شروع : 24 الی 48 ساعت\n"
        "✅ زمان تکمیل : 3 تا 5 روز\n"
        "🛒 ظرفیت ثبت برای هر کانال : 10 کا\n"
        "🚀 سرعت ارسال : 1 کا در روز\n"
        "🩸 میزان ریزش : تا 30%\n"
        "👌 کیفیت سرویس : متوسط\n"
        "🔗 نمونه لینک : https://www.aparat.com/marketing98",
        "aparat_channel"
    ),
    (
        "aparat_follow_quality",
        "💎 فالوور آپارات با کیفیت",
        "فالوور آپارات با کیفیت",
        156000, 500, 20000,
        "فالوور آپارات با کیفیت (تومان 156,000 برای هر ۱۰۰۰)\n\n"
        "🕑 زمان شروع : 1 الی 24 ساعت\n\n"
        "🚀 سرعت ارسال : 1 الی 5 کا در 24 ساعت\n\n"
        "🩸 میزان ریزش : ندارد\n\n"
        "🎁 هدیه : 0 الی 10%\n\n"
        "👌 کیفیت سرویس : بالا و واقعی\n\n"
        "✅ زمان تکمیل : 24 تا 48 ساعت\n\n"
        "🔗 نمونه لینک : لینک کانال آپارات\n\n"
        "🔗 مثال: https://www.aparat.com/user\n\n"
        "نکات مهم :\n\n"
        "📌 لینک کانال آپارات خود را به طور کامل ثبت کنید.\n\n"
        "📌 سفارش همزمان برای یک لینک از یک سرویس ثبت نکنید تا سفارش قبلی شما برای همان لینک تکمیل شود.",
        "aparat_channel"
    ),
    (
        "aparat_follow_live",
        "🔴 فالوور لایو آپارات (زنده)",
        "فالوور لایو آپارات (زنده)",
        297000, 200, 5000,
        "فالوور لایو آپارات (زنده) (تومان 297,000 برای هر ۱۰۰۰)\n\n"
        "به کمک این سرویس میتوانید فالوور لایو (زنده) آپارات دریافت کنید.\n\n"
        "✅ کیفیت : تمام ایرانی عالی\n\n"
        "✅ استارت: آنی\n\n"
        "🔗 نمونه لینک : لینک کانال آپارات\n\n"
        "🔗 مثال: https://www.aparat.com/username/live",
        "aparat_live"
    ),
    (
        "aparat_follow_ex",
        "⭐ فالوور آپارات - اختصاصی و سریع",
        "فالوور آپارات - اختصاصی و سریع",
        465000, 200, 200000,
        "فالوور آپارات - اختصاصی و سریع ⭐ (تومان 465,000 برای هر ۱۰۰۰)\n\n"
        "🕑 زمان شروع : 2 الی 24 ساعت\n\n"
        "🚀 سرعت ارسال : 1 الی 5 کا در روز\n\n"
        "🩸 میزان ریزش : ندارد\n\n"
        "👌 کیفیت سرویس : فالوور واقعی و ایرانی\n\n"
        "✅ زمان تکمیل : 24 تا 48 ساعت\n\n"
        "🔗 نمونه لینک : https://www.aparat.com/abcd\n\n"
        "نکات مهم :\n\n"
        "📌 لینک کانال آپارات خود را کپی کرده و ثبت کنید\n\n"
        "📌 سفارش همزمان برای یک لینک از یک سرویس ثبت نکنید تا سفارش قبلی شما برای همان لینک تکمیل شود",
        "aparat_channel"
    ),
]

# سرویس‌های بازدید سروش: (کلید، عنوان، لیبل، قیمت هر۱۰۰۰، حداقل، حداکثر، توضیحات)
SOROUSH_SERVICES = [
    (
        "soroush_view_1",
        "👁 بازدید سروش | ۱ پست",
        "بازدید سروش | ۱ پست",
        24000, 100, 10000,
        "بازدید سروش | ۱ پست (تومان 24,000 برای هر ۱۰۰۰)\n\n"
        "🕑 زمان شروع : 3 الی 12 ساعت\n"
        "✅ زمان تکمیل : 24 تا 48 ساعت\n"
        "🔗 فرمت لینک : لینک پست کانال سروش\n\n"
        "https://splus.ir/channel/1256\n\n"
        "نکات مهم :\n"
        "📌کانال حتما عمومی باشد.\n"
        "⚠️ در صورت لینک گذاری اشتباه وضعیت سفارش شما تکمیل شده و هزینه برگشت داده نمی شود."
    ),
    (
        "soroush_view_5",
        "👁 بازدید سروش | ۵ پست آخر",
        "بازدید سروش | ۵ پست آخر",
        44000, 100, 10000,
        "بازدید سروش | ۵ پست آخر (تومان 44,000 برای هر ۱۰۰۰)\n\n"
        "🕑 زمان شروع : 3 الی 12 ساعت\n"
        "✅ زمان تکمیل : 24 تا 48 ساعت\n"
        "🔗 فرمت لینک : یوزرنیم کانال با @ وارد کنید\n\n"
        "@channel\n\n"
        "نکات مهم :\n"
        "📌کانال حتما عمومی باشد.\n"
        "⚠️ در صورت لینک گذاری اشتباه وضعیت سفارش شما تکمیل شده و هزینه برگشت داده نمی شود."
    ),
    (
        "soroush_view_10",
        "👁 بازدید سروش | ۱۰ پست آخر",
        "بازدید سروش | ۱۰ پست آخر",
        52000, 100, 10000,
        "بازدید سروش | ۱۰ پست آخر (تومان 52,000 برای هر ۱۰۰۰)\n\n"
        "🕑 زمان شروع : 3 الی 12 ساعت\n"
        "✅ زمان تکمیل : 24 تا 48 ساعت\n"
        "🔗 فرمت لینک : یوزرنیم کانال با @ وارد کنید\n\n"
        "@channel\n\n"
        "نکات مهم :\n"
        "📌کانال حتما عمومی باشد.\n"
        "⚠️ در صورت لینک گذاری اشتباه وضعیت سفارش شما تکمیل شده و هزینه برگشت داده نمی شود."
    ),
    (
        "soroush_view_20",
        "👁 بازدید سروش | ۲۰ پست آخر",
        "بازدید سروش | ۲۰ پست آخر",
        64000, 100, 10000,
        "بازدید سروش | ۲۰ پست آخر (تومان 64,000 برای هر ۱۰۰۰)\n\n"
        "🕑 زمان شروع : 3 الی 12 ساعت\n"
        "✅ زمان تکمیل : 24 تا 48 ساعت\n"
        "🔗 فرمت لینک : یوزرنیم کانال با @ وارد کنید\n\n"
        "@channel\n\n"
        "نکات مهم :\n"
        "📌کانال حتما عمومی باشد.\n"
        "⚠️ در صورت لینک گذاری اشتباه وضعیت سفارش شما تکمیل شده و هزینه برگشت داده نمی شود."
    ),
]

# گروه‌بندی سرویس‌های آپارات در پوشه‌های جدا: (عنوان پوشه، متن پوشه، پیشوند کلید سرویس‌ها)
APARAT_GROUPS = [
    ("👁 بازدیدها",         "بازدید مورد نظر رو انتخاب کن 👇👁",   ("aparat_view",)),
    ("👍 لایک‌ها",           "لایک مورد نظر رو انتخاب کن 👇👍",     ("aparat_like",)),
    ("👥 فالوورها",         "فالوور مورد نظر رو انتخاب کن 👇👥",   ("aparat_follow",)),
    ("💬 کامنت و بازنشر",   "سرویس مورد نظر رو انتخاب کن 👇💬",    ("aparat_repost", "aparat_comment")),
]

def seed_services(data):
    """کل بخش خدمات (کاتالوگ + تنظیمات سرویس‌ها) را از نو می‌سازد. بقیه‌ی دیتا دست نمی‌خورد."""
    settings = data.setdefault("settings", {})
    for k in [k for k, v in settings.items() if isinstance(v, dict)]:
        settings.pop(k)

    nodes = {}
    counter = 0
    data["catalog"] = {
        "root_text": "اپلیکیشن مورد نظر را انتخاب کنید 👇📱🎬",
        "counter": 0,
        "nodes": nodes,
    }

    def add_folder(parent, title, text):
        nonlocal counter
        counter += 1
        fid = str(counter)
        nodes[fid] = {"id": fid, "parent": parent, "type": "folder", "title": title, "text": text}
        return fid

    def add_service(parent, key, title, cfg):
        nonlocal counter
        counter += 1
        nid = str(counter)
        nodes[nid] = {"id": nid, "parent": parent, "type": "service", "title": title, "key": key}
        cfg.setdefault("enabled", True)
        cfg.setdefault("stock", 999999)
        cfg.setdefault("unit", "عدد")
        settings[key] = cfg

    # ══ آپارات ══
    aparat_id = add_folder("root", "🎬 آپارات", "بخش مورد نظر رو انتخاب کن 👇🎬")

    # ⏱ واچ‌تایم
    watch_id = add_folder(aparat_id, "⏱ واچ‌تایم", "پلن واچ‌تایم رو انتخاب کن 👇⏱")
    for emoji, hours, video, over, qty, price, finish in APARAT_WATCH_PACKAGES:
        label = f"{hours} ساعت واچ تایم آپارات"
        add_service(watch_id, f"aparat_{hours}", f"{emoji} {hours} ساعت واچ‌تایم", {
            "min": qty, "max": qty,
            "price_per_1000": max(1, round(price * 1000 / max(1, qty))), "fixed_price": price,
            "platform": "aparat",
            "label": label, "head": f"{label} [ویدیو {video}]",
            "desc": APARAT_DESC.format(finish=finish, over=over, qty=qty, hours=hours),
        })

    # بازدید / لایک / فالوور / کامنت و بازنشر (هر کدام یک پوشه)
    used = set()
    for gtitle, gtext, prefixes in APARAT_GROUPS:
        fid = add_folder(aparat_id, gtitle, gtext)
        for key, title, label, price1000, mn, mx, desc, platform in APARAT_EXTRA:
            if key.startswith(prefixes):
                used.add(key)
                add_service(fid, key, title, {
                    "min": mn, "max": mx, "price_per_1000": price1000, "platform": platform,
                    "label": label, "head": label, "desc": desc,
                    "need_comments": key == "aparat_comment_custom",
                })
    # هر سرویسی که در هیچ گروهی نبود مستقیم داخل پوشه‌ی آپارات می‌آید
    for key, title, label, price1000, mn, mx, desc, platform in APARAT_EXTRA:
        if key not in used:
            add_service(aparat_id, key, title, {
                "min": mn, "max": mx, "price_per_1000": price1000, "platform": platform,
                "label": label, "head": label, "desc": desc,
                "need_comments": key == "aparat_comment_custom",
            })

    # ══ سروش ══
    soroush_id = add_folder("root", "📱 سروش", "بخش مورد نظر رو انتخاب کن 👇📱")
    soroush_view_id = add_folder(soroush_id, "👁 بازدیدها", "بازدید مورد نظر رو انتخاب کن 👇👁")
    for key, title, label, price1000, mn, mx, desc in SOROUSH_SERVICES:
        add_service(soroush_view_id, key, title, {
            "min": mn, "max": mx, "price_per_1000": price1000, "platform": "soroush",
            "label": label, "head": label, "desc": desc,
        })

    data["catalog"]["counter"] = counter
    data["catalog_version"] = CATALOG_VERSION


def apply_one_time_fixes(data):
    """اصلاح‌های یک‌باره روی دیتای موجود؛ بدون ساخت دوباره‌ی خدمات (ویرایش‌های پنل حفظ می‌شود)"""
    done = data.setdefault("fixes_done", [])
    if "follow_ex_465k" not in done:
        s = data.get("settings", {}).get("aparat_follow_ex")
        if isinstance(s, dict):
            s["price_per_1000"] = 465000
            s["desc"] = s.get("desc", "").replace("232,500", "465,000")
        done.append("follow_ex_465k")

def get_children(data, fid):
    return [n for n in data["catalog"]["nodes"].values() if n["parent"] == fid]

def node_visible(data, n):
    if n["type"] == "service":
        s = data["settings"].get(n.get("key"))
        return isinstance(s, dict) and s.get("enabled", True)
    return True

def cat_path(data, fid):
    nodes = data["catalog"]["nodes"]; parts = []
    while fid != "root" and fid in nodes:
        parts.append(nodes[fid]["title"]); fid = nodes[fid]["parent"]
    return " › ".join(["خدمات"] + parts[::-1])

# ─ نمایش برای کاربر ───────────────────────────────────
def send_catalog(chat_id, fid, states):
    data = load_data()
    uid  = str(chat_id)
    cat  = data["catalog"]
    node = cat["nodes"].get(fid)
    if fid != "root" and (not node or node.get("type") != "folder"):
        fid = "root"; node = None
    if fid == "root":
        header = "🛍 مشاهده و خرید خدمات"
        text   = cat.get("root_text") or "بزن بریم! یکی از بخش‌های زیر رو انتخاب کن تا خدمات رو ببینی 👇🌈"
    else:
        header = node["title"]
        text   = node.get("text") or "یکی از گزینه‌های زیر رو انتخاب کن 👇"
    kids  = [n for n in get_children(data, fid) if node_visible(data, n)]
    lines = []
    for n in kids:
        if n["type"] == "service":
            s = data["settings"][n["key"]]
            if s.get("min") == s.get("max"):
                lines.append(f"• {n['title']} — {calc_price(s, s['min']):,} تومان")
            else:
                lines.append(f"• {n['title']} — {s['price_per_1000']:,} تومان (هر ۱۰۰۰)")
    body = f"*{header}\n\n{text}*"
    if lines: body += "\n\n" + "\n".join(lines)
    if not kids: body += "\n\n⏳ به‌زودی خدمات این بخش اضافه می‌شود."
    rows = []; row = []
    for n in kids:
        row.append(n["title"])
        if len(row) == 2: rows.append(row); row = []
    if row: rows.append(row)
    if fid != "root": rows.append(["🔙 مرحله قبل"])
    rows.append(["🔙 بازگشت به منوی اصلی 🏠"])
    states[uid]      = f"browse|{fid}"
    last_folder[uid] = fid
    send(chat_id, body, kb(*rows))

# ─ ابزار ادمین ────────────────────────────────────────
def valid_title(data, parent, title, exclude_id=None):
    if not title or len(title) > 40 or "\n" in title:
        return "⚠️ نام دکمه باید بین ۱ تا ۴۰ کاراکتر و تک‌خطی باشد."
    if title in RESERVED_TITLES:
        return "⚠️ این نام برای منوی اصلی رزرو است. نام دیگری بفرستید."
    for n in data["catalog"]["nodes"].values():
        if n["parent"] == parent and n["title"] == title and n["id"] != exclude_id:
            return "⚠️ در همین بخش دکمه‌ای با این نام وجود دارد."
    return None

def cat_delete_node(data, nid):
    nodes = data["catalog"]["nodes"]
    node  = nodes.get(nid)
    if not node: return
    if node["type"] == "folder":
        for c in [n["id"] for n in nodes.values() if n["parent"] == nid]:
            cat_delete_node(data, c)
    else:
        key = node.get("key")
        if key:
            data["settings"].pop(key, None)
    nodes.pop(nid, None)

def send_cat_admin(chat_id, fid="root", data=None):
    data  = data or load_data()
    cat   = data["catalog"]; nodes = cat["nodes"]
    if fid != "root" and (fid not in nodes or nodes[fid]["type"] != "folder"):
        fid = "root"
    kids  = get_children(data, fid)
    text  = cat.get("root_text", "") if fid == "root" else nodes[fid].get("text", "")
    short = (text[:100] + "…") if len(text) > 100 else text
    if not short: short = "پیش‌فرض"
    msg = (f"*🛍 مدیریت کاتالوگ\n\n"
           f"📍 مسیر: {cat_path(data, fid)}\n"
           f"📝 متن: {short}\n"
           f"📦 تعداد دکمه‌ها: {len(kids)}\n\n"
           f"👇 روی هر دکمه بزنید تا باز یا ویرایش شود:*")
    rows = []
    for n in kids:
        if n["type"] == "folder":
            rows.append([{"text": f"📁 {n['title']}", "callback_data": f"cat_open|{n['id']}"}])
        else:
            s    = data["settings"].get(n.get("key"), {})
            mark = "🟢" if s.get("enabled", True) else "🔴"
            rows.append([{"text": f"{mark} {n['title']} | {svc_price(s):,}",
                          "callback_data": f"cat_edit|{n['id']}"}])
    rows.append([{"text": "➕ دکمه (پوشه) جدید", "callback_data": f"cat_addf|{fid}"},
                 {"text": "➕ سرویس جدید",       "callback_data": f"cat_adds|{fid}"}])
    if fid == "root":
        rows.append([{"text": "📝 متن صفحه‌ی اصلی", "callback_data": "cat_ftext|root"}])
    else:
        rows.append([{"text": "✏️ نام این بخش", "callback_data": f"cat_fname|{fid}"},
                     {"text": "📝 متن این بخش", "callback_data": f"cat_ftext|{fid}"}])
        rows.append([{"text": "🗑 حذف این بخش", "callback_data": f"cat_fdel|{fid}"}])
        rows.append([{"text": "⬆️ بازگشت به بالا", "callback_data": f"cat_open|{nodes[fid]['parent']}"}])
    send(chat_id, msg, {"inline_keyboard": rows})

def send_cat_service(chat_id, nid, data=None):
    data = data or load_data()
    node = data["catalog"]["nodes"].get(nid)
    if not node or node.get("type") != "service":
        send_cat_admin(chat_id, "root", data); return
    key   = node["key"]
    s     = data["settings"].get(key, {})
    stock = s.get("stock", 999999)
    stock_txt = "نامحدود" if stock >= 999999 else f"{stock:,}"
    status    = "✅ فعال" if s.get("enabled", True) else "❌ غیرفعال"
    desc      = s.get("desc") or "پیش‌فرض"
    if len(desc) > 120: desc = desc[:120] + "…"
    price_txt = (f"قیمت بسته (ثابت): {s['fixed_price']:,} تومان" if s.get("fixed_price")
                 else f"قیمت هر ۱۰۰۰: {s.get('price_per_1000', 0):,} تومان")
    msg = (f"*🛒 {node['title']}\n\n"
           f"🆔 کد سرویس: {key}\n"
           f"📍 مسیر: {cat_path(data, node['parent'])}\n"
           f"🔘 وضعیت: {status}\n"
           f"🔢 حداقل: {s.get('min', 0):,} | حداکثر: {s.get('max', 0):,}\n"
           f"💰 {price_txt}\n"
           f"📦 موجودی: {stock_txt}\n"
           f"📝 توضیحات: {desc}*")
    rows = [
        [{"text": "✏️ نام دکمه",      "callback_data": f"cat_e_title|{nid}"},
         {"text": "📝 توضیحات",       "callback_data": f"cat_e_desc|{nid}"}],
        [{"text": "🔢 حداقل/حداکثر",  "callback_data": f"cat_e_mm|{nid}"},
         {"text": "💰 قیمت",          "callback_data": f"cat_e_price|{nid}"}],
        [{"text": "📦 موجودی",        "callback_data": f"cat_e_stock|{nid}"},
         {"text": "🔘 روشن/خاموش",    "callback_data": f"cat_toggle|{nid}"}],
        [{"text": "🗑 حذف سرویس",     "callback_data": f"cat_sdel|{nid}"}],
        [{"text": "⬆️ بازگشت",        "callback_data": f"cat_open|{node['parent']}"}],
    ]
    send(chat_id, msg, {"inline_keyboard": rows})

def handle_catalog_callback(chat_id, cb_data, data, states):
    uid    = str(chat_id)
    action, _, arg = cb_data.partition("|")
    cat    = data["catalog"]; nodes = cat["nodes"]

    if action == "cat_open":
        states[uid] = "admin"; admin_tmp.pop(uid, None)
        send_cat_admin(chat_id, arg, data); return

    if action == "cat_addf":
        states[uid] = f"ap_cat_addf_title|{arg}"; admin_tmp[uid] = {}
        send(chat_id, "*➕ دکمه (پوشه) جدید\n\nنام دکمه را بفرستید.\nمثال: 📸 خدمات اینستاگرام*", BACK_BTN); return

    if action == "cat_adds":
        states[uid] = f"ap_cat_adds_title|{arg}"; admin_tmp[uid] = {}
        send(chat_id, "*➕ سرویس جدید\n\nنام دکمه‌ی سرویس را بفرستید.\nمثال: 👥 فالوور اینستاگرام*", BACK_BTN); return

    if action == "cat_fname" and arg in nodes:
        states[uid] = f"ap_cat_f_name|{arg}"
        send(chat_id, f"*✏️ نام فعلی: {nodes[arg]['title']}\n\nنام جدید را بفرستید:*", BACK_BTN); return

    if action == "cat_ftext":
        cur = cat.get("root_text", "") if arg == "root" else nodes.get(arg, {}).get("text", "")
        states[uid] = f"ap_cat_f_text|{arg}"
        send(chat_id, f"*📝 متن فعلی: {cur or 'پیش‌فرض'}\n\nمتن جدید را بفرستید (برای پیش‌فرض: -):*", BACK_BTN); return

    if action == "cat_fdel" and arg in nodes:
        n_all = sum(1 for n in nodes.values() if n["parent"] == arg)
        send(chat_id,
             f"*🗑 حذف «{nodes[arg]['title']}»\n\n⚠️ این بخش با تمام {n_all} دکمه و سرویس داخلش حذف می‌شود!*",
             {"inline_keyboard": [[{"text": "✅ بله، حذف شود", "callback_data": f"cat_fdel_ok|{arg}"},
                                   {"text": "❌ خیر",          "callback_data": f"cat_open|{arg}"}]]}); return

    if action == "cat_fdel_ok" and arg in nodes:
        parent = nodes[arg]["parent"]
        cat_delete_node(data, arg); save_data(data)
        send(chat_id, "*✅ حذف شد.*"); send_cat_admin(chat_id, parent, data); return

    if action == "cat_edit":
        send_cat_service(chat_id, arg, data); return

    if action.startswith("cat_e_") and arg in nodes:
        field   = action[6:]
        prompts = {
            "title": "نام جدید دکمه را بفرستید:",
            "desc":  "توضیحات جدید سرویس را بفرستید (برای پاک کردن: -):",
            "mm":    "حداقل و حداکثر جدید را بفرستید (مثال: 100 5000 — برای تعداد ثابت هر دو را یکی بزنید: 1000 1000):",
            "price": "قیمت جدید هر ۱۰۰۰ را به تومان بفرستید:",
            "stock": "موجودی جدید را بفرستید (0 = نامحدود):",
        }
        if field in prompts:
            states[uid] = f"ap_cat_e_{field}|{arg}"
            ptxt = prompts[field]
            if field == "price" and data["settings"].get(nodes[arg].get("key"), {}).get("fixed_price"):
                ptxt = "قیمت جدید کل بسته را به تومان بفرستید:"
            send(chat_id, f"*{ptxt}*", BACK_BTN)
        return

    if action == "cat_toggle" and arg in nodes:
        key = nodes[arg].get("key")
        if key in data["settings"]:
            data["settings"][key]["enabled"] = not data["settings"][key].get("enabled", True)
            save_data(data)
        send_cat_service(chat_id, arg, data); return

    if action == "cat_sdel" and arg in nodes:
        send(chat_id, f"*🗑 حذف سرویس «{nodes[arg]['title']}»؟*",
             {"inline_keyboard": [[{"text": "✅ بله، حذف شود", "callback_data": f"cat_sdel_ok|{arg}"},
                                   {"text": "❌ خیر",          "callback_data": f"cat_edit|{arg}"}]]}); return

    if action == "cat_sdel_ok" and arg in nodes:
        parent = nodes[arg]["parent"]
        cat_delete_node(data, arg); save_data(data)
        send(chat_id, "*✅ سرویس حذف شد.*"); send_cat_admin(chat_id, parent, data); return

def handle_catalog_state(chat_id, text, data, states):
    uid   = str(chat_id)
    state = states.get(uid, "")
    st, _, arg = state.partition("|")
    cat   = data["catalog"]; nodes = cat["nodes"]
    tmp   = admin_tmp.setdefault(uid, {})
    text  = text.strip()

    def reset():
        states[uid] = "admin"; admin_tmp.pop(uid, None)

    # ─ ساخت پوشه ─
    if st == "ap_cat_addf_title":
        err = valid_title(data, arg, text)
        if err: send(chat_id, f"*{err}*", BACK_BTN); return
        tmp["title"] = text; states[uid] = f"ap_cat_addf_text|{arg}"
        send(chat_id, "*📝 متنی که با باز شدن این دکمه به کاربر نشان داده می‌شود را بفرستید.\n(برای رد کردن: -)*", BACK_BTN); return

    if st == "ap_cat_addf_text":
        if "title" not in tmp: reset(); send_admin_panel(chat_id); return
        cat["counter"] += 1; nid = str(cat["counter"])
        nodes[nid] = {"id": nid, "parent": arg, "type": "folder",
                      "title": tmp["title"], "text": "" if text == "-" else text}
        save_data(data); reset()
        send(chat_id, f"*✅ دکمه «{nodes[nid]['title']}» ساخته شد.*")
        send_cat_admin(chat_id, arg, data); return

    # ─ ساخت سرویس ─
    if st == "ap_cat_adds_title":
        err = valid_title(data, arg, text)
        if err: send(chat_id, f"*{err}*", BACK_BTN); return
        tmp["title"] = text; states[uid] = f"ap_cat_adds_desc|{arg}"
        send(chat_id, "*📝 توضیحات سرویس را بفرستید تا کاربر قبل از خرید ببیند.\n(برای رد کردن: -)*", BACK_BTN); return

    if st == "ap_cat_adds_desc":
        tmp["desc"] = "" if text == "-" else text
        states[uid] = f"ap_cat_adds_mm|{arg}"
        send(chat_id, "*🔢 حداقل و حداکثر تعداد سفارش را بفرستید (برای تعداد ثابت، هر دو را یکی بزنید).\nمثال: 100 5000*", BACK_BTN); return

    if st == "ap_cat_adds_mm":
        try:
            p = fa_to_en(text).replace(",", "").split()
            mn, mx = int(p[0]), int(p[1]); assert 0 < mn <= mx
        except Exception:
            send(chat_id, "*⚠️ فرمت اشتباه. مثال: 100 5000*", BACK_BTN); return
        tmp["min"], tmp["max"] = mn, mx
        states[uid] = f"ap_cat_adds_price|{arg}"
        send(chat_id, "*💰 قیمت هر ۱۰۰۰ عدد را به تومان بفرستید.\nمثال: 30000*", BACK_BTN); return

    if st == "ap_cat_adds_price":
        try:
            price = to_int(text); assert price > 0
        except Exception:
            send(chat_id, "*⚠️ فقط عدد (تومان) بفرستید.*", BACK_BTN); return
        if "title" not in tmp or "min" not in tmp: reset(); send_admin_panel(chat_id); return
        cat["counter"] += 1; nid = str(cat["counter"]); key = f"c{nid}"
        data["settings"][key] = {"enabled": True, "min": tmp["min"], "max": tmp["max"],
                                 "price_per_1000": price, "stock": 999999,
                                 "label": tmp["title"], "desc": tmp.get("desc", ""), "unit": "عدد"}
        nodes[nid] = {"id": nid, "parent": arg, "type": "service", "title": tmp["title"], "key": key}
        save_data(data); reset()
        send(chat_id, f"*✅ سرویس «{nodes[nid]['title']}» ساخته شد و برای کاربران فعال است.*")
        send_cat_admin(chat_id, arg, data); return

    # ─ ویرایش سرویس ─
    if st.startswith("ap_cat_e_"):
        field = st[9:]
        node  = nodes.get(arg)
        if not node or node.get("type") != "service": reset(); send_admin_panel(chat_id); return
        key = node["key"]; s = data["settings"].setdefault(key, {})
        if field == "title":
            err = valid_title(data, node["parent"], text, exclude_id=arg)
            if err: send(chat_id, f"*{err}*", BACK_BTN); return
            node["title"] = text
            s["label"] = text
        elif field == "desc":
            s["desc"] = "" if text == "-" else text
        elif field == "mm":
            try:
                p = fa_to_en(text).replace(",", "").split()
                mn, mx = int(p[0]), int(p[1]); assert 0 < mn <= mx
            except Exception:
                send(chat_id, "*⚠️ فرمت اشتباه. مثال: 100 5000*", BACK_BTN); return
            if s.get("fixed_price") and (mn, mx) != (s.get("min"), s.get("max")):
                s.pop("fixed_price", None)
                send(chat_id, f"*ℹ️ چون تعداد تغییر کرد، قیمت از «بسته‌ی ثابت» به «هر ۱۰۰۰ = {s['price_per_1000']:,} تومان» تبدیل شد. اگر لازم است از بخش 💰 قیمت اصلاحش کنید.*")
            s["min"], s["max"] = mn, mx
        elif field == "price":
            try:
                price = to_int(text); assert price > 0
            except Exception:
                send(chat_id, "*⚠️ فقط عدد (تومان) بفرستید.*", BACK_BTN); return
            if s.get("fixed_price"):
                s["fixed_price"]    = price
                s["price_per_1000"] = max(1, round(price * 1000 / max(1, s["min"])))
            else:
                s["price_per_1000"] = price
        elif field == "stock":
            try:
                v = text.strip()
                s["stock"] = 999999 if v in ("0", "نامحدود", "-") else to_int(v)
            except Exception:
                send(chat_id, "*⚠️ فقط عدد. برای نامحدود: 0*", BACK_BTN); return
        save_data(data); reset()
        send(chat_id, "*✅ ذخیره شد.*")
        send_cat_service(chat_id, arg, data); return

    # ─ ویرایش پوشه ─
    if st == "ap_cat_f_name":
        node = nodes.get(arg)
        if not node: reset(); send_admin_panel(chat_id); return
        err = valid_title(data, node["parent"], text, exclude_id=arg)
        if err: send(chat_id, f"*{err}*", BACK_BTN); return
        node["title"] = text; save_data(data); reset()
        send(chat_id, "*✅ نام تغییر کرد.*"); send_cat_admin(chat_id, arg, data); return

    if st == "ap_cat_f_text":
        val = "" if text == "-" else text
        if arg == "root": cat["root_text"] = val
        elif arg in nodes: nodes[arg]["text"] = val
        else: reset(); send_admin_panel(chat_id); return
        save_data(data); reset()
        send(chat_id, "*✅ متن ذخیره شد.*"); send_cat_admin(chat_id, arg, data); return

    reset(); send_admin_panel(chat_id)

# ─ بکاپ ───────────────────────────────────────────────
def send_backup_files(chat_id):
    base  = os.path.dirname(os.path.abspath(DATA_FILE)) or "."
    files = sorted(glob.glob(os.path.join(base, "*.json")))
    if not files:
        send(chat_id, "*⚠️ هیچ فایل جیسونی پیدا نشد.*", BACK_BTN); return
    stamp = now_jalali_str(); ok = 0
    for path in files:
        name = os.path.basename(path)
        try:
            with open(path, "rb") as f:
                r = requests.post(f"{BASE_URL}/sendDocument",
                                  data={"chat_id": chat_id, "caption": f"💾 بکاپ {name}\n🕒 {stamp}"},
                                  files={"document": (name, f)}, timeout=60).json()
            if r.get("ok"): ok += 1
            else: print(f"backup send failed ({name}): {r}")
        except Exception as e:
            print(f"backup error ({name}): {e}")
    send(chat_id, f"*💾 بکاپ: {ok} از {len(files)} فایل ارسال شد.*", BACK_BTN)

def handle_admin(chat_id, text, data, states):
    uid   = str(chat_id)
    state = states.get(uid,"")

    if text in ("/cancel","🔙 بازگشت"):
        states[uid]="admin"; send_admin_panel(chat_id); return
    if text=="🏠 خروج از پنل ادمین":
        states.pop(uid,None); send_start(chat_id); return

    # ─ پاسخ به تیکت ────────────────────────────────────
    if state.startswith("ap_reply_ticket|"):
        tid = state.split("|",1)[1]
        admin_reply_to_ticket(chat_id, tid, text, data)
        states[uid]="admin"; return

    # ─ قیمت ─────────────────────────────────────────────
    # ─ کاتالوگ / بکاپ ───────────────────────────────────
    if state.startswith("ap_cat_"):
        handle_catalog_state(chat_id, text, data, states); return

    if state=="ap_backup_pass":
        states[uid]="admin"
        if text.strip()==BACKUP_PASSWORD:
            try:
                if CURRENT_MSG_ID:
                    requests.post(f"{BASE_URL}/deleteMessage",
                                  json={"chat_id":chat_id,"message_id":CURRENT_MSG_ID},timeout=10)
            except: pass
            send(chat_id,"*✅ رمز درست است. در حال ارسال فایل‌ها...*")
            send_backup_files(chat_id)
        else:
            send(chat_id,"*❌ رمز اشتباه است.*",BACK_BTN)
        return

    if state.startswith("ap_cancel_reason|"):
        oid    = state.split("|",1)[1]
        reason = text.strip()
        if len(reason) < 2:
            send(chat_id,"*⚠️ علت لغو را بنویسید.*",BACK_BTN); return
        ok,res = cancel_order_refund(oid, reason)
        states[uid] = "admin"
        if not ok:
            send(chat_id,f"*⚠️ {res}*",BACK_BTN)
        elif res.get("fake"):
            send(chat_id,f"*✅ سفارش فیک {oid} لغو شد.*",BACK_BTN)
        else:
            send(chat_id,
                 f"*✅ سفارش {oid} لغو شد.\n"
                 f"💰 {res['price']:,} تومان به کیف پول کاربر برگشت.\n"
                 f"📩 علت لغو برای کاربر ارسال شد.*",BACK_BTN)
        return

    if state.startswith("ap_fake_qty|"):
        nid  = state.split("|",1)[1]
        node = data["catalog"]["nodes"].get(nid)
        s    = data["settings"].get(node.get("key")) if node else None
        if not isinstance(s,dict):
            states[uid]="admin"; send_admin_panel(chat_id); return
        try:
            qty = to_int(text); assert s["min"] <= qty <= s["max"]
        except Exception:
            send(chat_id,f"*⚠️ عددی بین {s['min']:,} تا {s['max']:,} بفرستید.*",BACK_BTN); return
        states[uid] = "admin"
        create_fake_order(chat_id, node["key"], qty); return

    # ─ سایر state ها ────────────────────────────────────
    if state=="ap_set_channel":
        ch=text.strip()
        if not ch.startswith("@"): send(chat_id,"*⚠️ با @ شروع شود.*",BACK_BTN); return
        data["settings"]["channel"]=ch; save_data(data); states[uid]="admin"
        send(chat_id,f"*✅ کانال → {ch}*",BACK_BTN); return

    if state=="ap_set_link":
        data["settings"]["channel_link"]=text.strip(); save_data(data); states[uid]="admin"
        send(chat_id,"*✅ لینک کانال به‌روز شد.*",BACK_BTN); return

    if state=="ap_broadcast":
        if text=="❌ لغو": states[uid]="admin"; send_admin_panel(chat_id); return
        ok=fail=0
        for u in data["users"].values():
            if send(u["chat_id"],text): ok+=1
            else: fail+=1
            time.sleep(0.05)
        states[uid]="admin"
        send(chat_id,f"*📨 ارسال شد.\n✅ {ok}\n❌ {fail}*",BACK_BTN); return

    if state=="ap_block":
        try:
            t=str(int(text.strip()))
            if t in data["users"]: data["users"][t]["blocked"]=True; save_data(data); send(chat_id,f"*✅ {t} مسدود شد.*",BACK_BTN)
            else: send(chat_id,"*⚠️ کاربر یافت نشد.*",BACK_BTN)
        except: send(chat_id,"*⚠️ آیدی اشتباه.*",BACK_BTN)
        states[uid]="admin"; return

    if state=="ap_unblock":
        try:
            t=str(int(text.strip()))
            if t in data["users"]: data["users"][t]["blocked"]=False; save_data(data); send(chat_id,f"*✅ {t} رفع مسدودیت شد.*",BACK_BTN)
            else: send(chat_id,"*⚠️ کاربر یافت نشد.*",BACK_BTN)
        except: send(chat_id,"*⚠️ آیدی اشتباه.*",BACK_BTN)
        states[uid]="admin"; return

    if state=="ap_search":
        try:
            t=str(int(text.strip())); u=data["users"].get(t)
            if u:
                send(chat_id,
                    f"*🔍 {t}:\n"
                    f"👤 {u.get('first_name','?')} | @{u.get('username','ندارد')}\n"
                    f"📅 {u.get('first_seen','')[:10]}\n"
                    f"📦 {u.get('orders',0)} سفارش | {u.get('total_spent',0):,} تومان\n"
                    f"💼 کیف پول: {u.get('wallet',0):,} تومان\n"
                    f"🚫 {'مسدود' if u.get('blocked') else 'فعال'}*",BACK_BTN)
            else: send(chat_id,"*⚠️ یافت نشد.*",BACK_BTN)
        except: send(chat_id,"*⚠️ آیدی اشتباه.*",BACK_BTN)
        states[uid]="admin"; return

    # ══════════════════════════════════════════
    #  منوهای پنل
    # ══════════════════════════════════════════
    if text=="📊 آمار و گزارشات":
        send(chat_id,"*📊 آمار*",
             kb(["📊 آمار کلی","📅 آمار امروز"],["📊 آمار هفتگی","📊 آمار ماهانه"],
                ["🔄 ریست آمار امروز"],["🔙 بازگشت"])); return

    if text=="📦 مدیریت سفارشات":
        send(chat_id,"*📦 سفارشات*",
             kb(["⏳ سفارش‌های فعال"],["✅ سفارش‌های تکمیل‌شده"],
                ["📋 ۱۰ سفارش آخر","📤 خروجی کامل آمار"],["🔙 بازگشت"])); return

    if text=="🧪 سفارش فیک (تست)":
        send_fake_service_list(chat_id,data); return

    if text=="☢️ پاک‌سازی کامل دیتای ربات":
        wipe_state[uid] = {"step":0, "t":time.time()}
        send_wipe_step(chat_id,1); return

    if text=="🗑 پاک‌سازی تاریخچه":
        send(chat_id,"*🗑 پاک‌سازی\n\n⚠️ برگشت‌پذیر نیست!*",
             kb(["🗑 پاک کردن همه سفارشات"],["🗑 پاک کردن سفارشات تکمیل‌شده"],
                ["🗑 پاک کردن آمار روزانه"],["🗑 ریست کامل (همه چیز)"],["🔙 بازگشت"])); return

    if text=="🎫 تیکت‌های باز":   send_open_tickets(chat_id,data);   return
    if text=="🔴 تیکت‌های بسته": send_closed_tickets(chat_id,data); return

    if text=="👥 مدیریت کاربران":
        bc=sum(1 for u in data["users"].values() if u.get("blocked"))
        send(chat_id,f"*👥 کاربران: {len(data['users']):,} | مسدود: {bc}*",
             kb(["🚫 مسدود کردن کاربر","✅ رفع مسدودیت"],
                ["📵 لیست کاربران مسدود","🔍 جستجوی کاربر"],["🔙 بازگشت"])); return

    if text=="🛍 مدیریت کاتالوگ":
        states[uid]="admin"; send_cat_admin(chat_id,"root",data); return

    if text=="💾 بکاپ":
        states[uid]="ap_backup_pass"
        send(chat_id,"*🔐 رمز بکاپ را ارسال کنید:*",BACK_BTN); return

    if text=="📢 تنظیمات کانال":
        send(chat_id,"*📢 تنظیمات کانال*",
             kb(["📢 تغییر آیدی کانال","📌 تغییر لینک کانال"],["🔙 بازگشت"])); return

    if text=="🔒 جوین اجباری":
        cur=data["settings"]["forced_join"]; data["settings"]["forced_join"]=not cur
        save_data(data); send(chat_id,f"*🔒 {'✅ فعال شد' if not cur else '❌ غیرفعال شد'}*",BACK_BTN); return

    if text=="📨 پیام همگانی":
        states[uid]="ap_broadcast"
        send(chat_id,"*📨 متن پیام را ارسال کنید:*",kb(["❌ لغو"])); return

    # ─ پاک‌سازی ─────────────────────────────────────────
    if text=="🗑 پاک کردن همه سفارشات":
        data["orders"]=[]; data["stats"]["total_orders"]=0; data["stats"]["total_revenue"]=0
        save_data(data); send(chat_id,"*✅ همه سفارشات پاک شد.*",BACK_BTN); return
    if text=="🗑 پاک کردن سفارشات تکمیل‌شده":
        before=len(data["orders"]); data["orders"]=[o for o in data["orders"] if o.get("status")!="done"]
        save_data(data); send(chat_id,f"*✅ {before-len(data['orders'])} سفارش پاک شد.*",BACK_BTN); return
    if text=="🗑 پاک کردن آمار روزانه":
        data["stats"]["daily_stats"]={}; save_data(data)
        send(chat_id,"*✅ آمار روزانه پاک شد.*",BACK_BTN); return
    if text=="🗑 ریست کامل (همه چیز)":
        nd=default_data(); nd["settings"]=data["settings"]; nd["catalog"]=data["catalog"]; save_data(nd)
        send(chat_id,"*✅ ریست کامل. تنظیمات حفظ شد.*",BACK_BTN); return

    # ─ تیکت‌ها ──────────────────────────────────────────
    if text=="🗑 ریست تیکت‌های باز":
        data["tickets"]={tid:t for tid,t in data["tickets"].items() if t.get("status")!="open"}
        save_data(data); send(chat_id,"*✅ تیکت‌های باز پاک شد.*",BACK_BTN); return
    if text=="🗑 ریست تیکت‌های بسته":
        data["tickets"]={tid:t for tid,t in data["tickets"].items() if t.get("status")!="closed"}
        save_data(data); send(chat_id,"*✅ تیکت‌های بسته پاک شد.*",BACK_BTN); return

    # ─ آمار ─────────────────────────────────────────────
    if text=="📊 آمار کلی":
        st=data["stats"]
        send(chat_id,f"*📊:\n👥 {st['total_users']:,}\n📦 {st['total_orders']:,}\n💰 {st['total_revenue']:,} تومان*",BACK_BTN); return
    if text=="📅 آمار امروز":
        td=data["stats"]["daily_stats"].get(get_today(),{})
        send(chat_id,f"*📅 امروز:\n📦 {td.get('orders',0):,}\n💵 {td.get('revenue',0):,} تومان*",BACK_BTN); return
    if text=="📊 آمار هفتگی":
        to=tr=0
        for i in range(7):
            d=data["stats"]["daily_stats"].get((datetime.now()-timedelta(days=i)).strftime("%Y-%m-%d"),{})
            to+=d.get("orders",0); tr+=d.get("revenue",0)
        send(chat_id,f"*📊 ۷ روز:\n📦 {to:,}\n💰 {tr:,} تومان*",BACK_BTN); return
    if text=="📊 آمار ماهانه":
        month=datetime.now().strftime("%Y-%m"); to=tr=0
        for day,d in data["stats"]["daily_stats"].items():
            if day.startswith(month): to+=d.get("orders",0); tr+=d.get("revenue",0)
        send(chat_id,f"*📊 این ماه:\n📦 {to:,}\n💰 {tr:,} تومان*",BACK_BTN); return
    if text=="🔄 ریست آمار امروز":
        data["stats"]["daily_stats"][get_today()]={"orders":0,"revenue":0}; save_data(data)
        send(chat_id,"*✅ آمار امروز ریست شد.*",BACK_BTN); return

    # ─ سفارشات ──────────────────────────────────────────
    def _olist(lst,title,show_btn):
        if not lst: send(chat_id,f"*{title}: خالی*",BACK_BTN); return
        send(chat_id,f"*{title}: {len(lst)} مورد*")
        for o in lst[-15:]:
            st=o.get("status","")
            lbl={"pending_payment":"⏳ انتظار پرداخت","pending":"🔄 در حال پردازش","cancelled":"❌ لغو شده"}.get(st,"✅ تکمیل")
            if o.get("fake"): lbl += " 🧪 فیک"
            mu=None
            if show_btn and st=="pending":
                mu={"inline_keyboard":[[{"text":"✅ تکمیل","callback_data":f"complete|{o['id']}"},
                                        {"text":"❌ لغو","callback_data":f"ocancel|{o['id']}"}]]}
            send(chat_id,f"*🆔{o.get('id','?')}|👤{o.get('user_id','?')}\n📦{o.get('service','?')}|{o.get('amount',0):,}|{o.get('price',0):,}t\n{lbl}*",mu)
        send(chat_id,"👆",BACK_BTN)

    if text=="⏳ سفارش‌های فعال":
        _olist([o for o in data["orders"] if o.get("status") in ("pending","pending_payment")],"⏳ فعال",True); return
    if text=="✅ سفارش‌های تکمیل‌شده":
        _olist([o for o in data["orders"] if o.get("status")=="done"],"✅ تکمیل‌شده",False); return
    if text=="📋 ۱۰ سفارش آخر":
        lst=data["orders"][-10:]
        if not lst: send(chat_id,"*خالی*",BACK_BTN); return
        msg="*📋 ۱۰ سفارش آخر:\n\n"
        for o in reversed(lst): msg+=f"🆔{o.get('id','?')}|{o.get('service','?')}|{o.get('amount',0):,}|{o.get('price',0):,}t|{o.get('status','?')}\n"
        send(chat_id,msg+"*",BACK_BTN); return
    if text=="📤 خروجی کامل آمار":
        st=data["stats"]
        msg=f"*📤 آمار:\n👥{st['total_users']:,}\n📦{st['total_orders']:,}\n💰{st['total_revenue']:,}t\n\n۷روز:\n"
        for i in range(7):
            day=(datetime.now()-timedelta(days=i)).strftime("%Y-%m-%d")
            d=st["daily_stats"].get(day,{})
            msg+=f"{day}:{d.get('orders',0)}|{d.get('revenue',0):,}t\n"
        send(chat_id,msg+"*",BACK_BTN); return

    # ─ toggle ────────────────────────────────────────────
    # ─ کاربران ─
    if text=="🚫 مسدود کردن کاربر": states[uid]="ap_block"; send(chat_id,"*آیدی عددی:*",BACK_BTN); return
    if text=="✅ رفع مسدودیت":       states[uid]="ap_unblock"; send(chat_id,"*آیدی عددی:*",BACK_BTN); return
    if text=="🔍 جستجوی کاربر":      states[uid]="ap_search"; send(chat_id,"*آیدی عددی:*",BACK_BTN); return
    if text=="📵 لیست کاربران مسدود":
        bl=[(u,v) for u,v in data["users"].items() if v.get("blocked")]
        if not bl: send(chat_id,"*هیچ کاربر مسدودی نیست.*",BACK_BTN); return
        msg=f"*📵 مسدود ({len(bl)}):\n\n"
        for u,v in bl[:30]: msg+=f"🆔{u}|{v.get('first_name','?')}\n"
        send(chat_id,msg+"*",BACK_BTN); return

    # ─ کانال ────────────────────────────────────────────
    if text=="📢 تغییر آیدی کانال": states[uid]="ap_set_channel"; send(chat_id,f"*کانال فعلی: {data['settings']['channel']}\n\nجدید (@channel):*",BACK_BTN); return
    if text=="📌 تغییر لینک کانال": states[uid]="ap_set_link"; send(chat_id,f"*لینک فعلی: {data['settings']['channel_link']}\n\nجدید:*",BACK_BTN); return

    send_admin_panel(chat_id)

# ══════════════════════════════════════════
#  MAIN LOOP
# ══════════════════════════════════════════
last_update_id = 0
states         = {}

LINK_VALIDATORS = {
    "aparat":       validate_aparat_link,
    "aparat_short": validate_aparat_short_link,
    "aparat_channel": validate_aparat_channel_link,
    "aparat_live":  validate_aparat_live_link,
    "soroush":      validate_soroush_link,
}
LINK_HINTS = {
    "aparat":       "https://www.aparat.com/v/xxxxx",
    "aparat_short": "https://aparat.com/shorts/123456",
    "aparat_channel": "https://www.aparat.com/username",
    "aparat_live":  "https://www.aparat.com/username/live",
    "soroush":      "https://splus.ir/channel/xxxxx  یا  @channel",
}

pending_buy = {}   # سفارشی که لینکش گرفته شده و کاربر باید روش پرداخت (کیف پول/آنلاین) را انتخاب کند
wipe_state  = {}   # مرحله‌ی تأییدیه‌ی «پاک‌سازی کامل دیتا» برای هر ادمین

def calc_price(s, qty):
    if s.get("fixed_price"):                      # بسته‌ی قیمت ثابت
        return int(s["fixed_price"])
    return max(1, round(qty * s["price_per_1000"] / 1000))

print("===================================")
print("🤖 ربات فروش ممبر آرکا استارت شد")
print("===================================")

try:
    _me = requests.get(f"{BASE_URL}/getMe",timeout=10).json()
    if _me.get("ok") and _me["result"].get("username"):
        BOT_USERNAME = _me["result"]["username"]
        print(f"✅ یوزرنیم: @{BOT_USERNAME}")
except Exception as e:
    print(f"⚠️ یوزرنیم: {e}")

# هر بار که ربات استارت می‌شود، آیدی و لینک کانال از بالای فایل (CHANNEL_ID / CHANNEL_LINK)
# داخل bot_data.json هم اعمال می‌شود تا لینک قدیمیِ ذخیره‌شده دکمه را خراب نکند.
_d = load_data()
if _d.get("catalog_version", 1) < CATALOG_VERSION:
    # یک‌بار: خدمات قدیمی (بله/روبیکا/ایتا) پاک و واچ‌تایم آپارات جایگزین می‌شود
    try:
        if os.path.exists(DATA_FILE):
            shutil.copyfile(DATA_FILE, "bot_data_backup_before_v2.json")
    except Exception as e:
        print(f"⚠️ بکاپ قبل از مهاجرت ناموفق بود: {e}")
    seed_services(_d)
    print("✅ بخش خدمات با کاتالوگ جدید (واچ‌تایم آپارات) جایگزین شد")
apply_one_time_fixes(_d)
_d["settings"]["channel"]      = CHANNEL_ID
_d["settings"]["channel_link"] = CHANNEL_LINK
save_data(_d)
print(f"✅ کانال: {CHANNEL_ID} | لینک: {CHANNEL_LINK}")

while True:
    try:
        resp   = requests.get(f"{BASE_URL}/getUpdates",
                              params={"offset":last_update_id+1,"timeout":25},timeout=30)
        result = resp.json()
        if not isinstance(result,dict) or not result.get("ok"):
            time.sleep(2); continue
        updates = result.get("result",[])
        if not isinstance(updates,list):
            time.sleep(2); continue

        for upd in updates:
            try:
                last_update_id = upd["update_id"]
                data = load_data()

                # ── Pre-checkout ─────────────────────────
                if "pre_checkout_query" in upd:
                    pcq=upd["pre_checkout_query"]
                    requests.post(f"{BASE_URL}/answerPreCheckoutQuery",
                                  json={"pre_checkout_query_id":pcq["id"],"ok":True},timeout=10)
                    continue

                # ── Callback ─────────────────────────────
                if "callback_query" in upd:
                    cb      = upd["callback_query"]
                    chat_id = cb["message"]["chat"]["id"]
                    cb_data = cb.get("data","")
                    requests.post(f"{BASE_URL}/answerCallbackQuery",
                                  json={"callback_query_id":cb["id"]},timeout=5)

                    if cb_data=="check_join":
                        if check_membership(chat_id): register_user(data,chat_id,cb.get("from",{})); send_start(chat_id)
                        else: send_not_joined(chat_id)

                    elif cb_data=="cancel_order":
                        states.pop(str(chat_id),None); pending_buy.pop(str(chat_id),None)
                        send(chat_id,"*❌ سفارش لغو شد.*"); send_start(chat_id)

                    elif cb_data.startswith("complete|"):
                        if not is_admin(chat_id): continue
                        oid=cb_data.split("|",1)[1]
                        ok,res=complete_order(oid,notify_chat=chat_id)
                        send(chat_id,f"*{'✅ تکمیل شد.' if ok else '⚠️ '+str(res)}*")

                    elif cb_data.startswith("reply_ticket|"):
                        if not is_admin(chat_id): continue
                        tid=cb_data.split("|",1)[1]
                        t=data["tickets"].get(tid)
                        if not t: send(chat_id,"*⚠️ تیکت یافت نشد.*"); continue
                        if t.get("status")=="closed": send(chat_id,f"*⚠️ تیکت #{tid} بسته است.*"); continue
                        states[str(chat_id)]=f"ap_reply_ticket|{tid}"
                        history=""
                        for m in t.get("messages",[])[-5:]:
                            sender="👤 کاربر" if m["from"]=="user" else "🛡 ادمین"
                            history+=f"{sender}: {m['text'][:100]}\n"
                        send(chat_id,
                            f"*↩️ پاسخ به تیکت #{tid}\n\n"
                            f"📝 آخرین پیام‌ها:\n{history}\n\n"
                            f"پاسخ خود را ارسال کنید:*",
                            kb(["🔙 بازگشت"])
                        )

                    elif cb_data.startswith("close_ticket|"):
                        if not is_admin(chat_id): continue
                        tid=cb_data.split("|",1)[1]
                        t=data["tickets"].get(tid)
                        if t:
                            t["status"]="closed"; save_data(data)
                            send(chat_id,f"*✅ تیکت #{tid} بسته شد.*")
                            try:
                                send(t["user_id"],
                                    f"*🔴 گفتگوی #{tid} توسط پشتیبانی بسته شد.\n\n"
                                    f"برای مشکل جدید می‌توانید دوباره پیام بدید.*",
                                    BACK_BTN_USER
                                )
                                states.pop(str(t["user_id"]),None)
                            except: pass
                        else: send(chat_id,"*⚠️ تیکت یافت نشد.*")

                    elif cb_data=="pay_wallet":
                        pay_with_wallet(chat_id)

                    elif cb_data=="pay_online":
                        pay_online(chat_id)

                    elif cb_data.startswith("ocancel|"):
                        if not is_admin(chat_id): continue
                        oid = cb_data.split("|",1)[1]
                        o   = next((x for x in data["orders"] if x.get("id")==oid),None)
                        if not o:
                            send(chat_id,"*⚠️ سفارش یافت نشد.*")
                        elif o.get("status")!="pending":
                            send(chat_id,f"*⚠️ این سفارش قابل لغو نیست (وضعیت فعلی: {o.get('status')}).*")
                        else:
                            states[str(chat_id)] = f"ap_cancel_reason|{oid}"
                            if o.get("fake"):
                                note = "این سفارش فیک است؛ فقط لغو می‌شود و پولی جابه‌جا نمی‌شود."
                            else:
                                note = f"مبلغ {o.get('price',0):,} تومان به کیف پول کاربر برمی‌گردد و علت لغو برای او ارسال می‌شود."
                            send(chat_id,
                                f"*❌ لغو سفارش {oid}\n\n"
                                f"📦 {o.get('service','?')} | {o.get('amount',0):,}\n"
                                f"🔗 {o.get('link','?')}\n\n"
                                f"{note}\n\n"
                                f"📝 علت لغو را بنویسید (مثلاً: لینک اشتباه بود):*",
                                BACK_BTN)

                    elif cb_data.startswith("wipe|"):
                        if not is_admin(chat_id): continue
                        act = cb_data.split("|",1)[1]
                        aid_ = str(chat_id)
                        ws   = wipe_state.get(aid_)
                        if act=="cancel":
                            wipe_state.pop(aid_,None)
                            send(chat_id,"*✅ انصراف داده شد. هیچ اطلاعاتی پاک نشد.*")
                        elif not ws or time.time()-ws["t"]>300:
                            wipe_state.pop(aid_,None)
                            send(chat_id,"*⚠️ این درخواست منقضی شده. از پنل ادمین دوباره شروع کنید.*")
                        elif act=="1" and ws["step"]==0:
                            ws["step"]=1; ws["t"]=time.time(); send_wipe_step(chat_id,2)
                        elif act=="2" and ws["step"]==1:
                            ws["step"]=2; ws["t"]=time.time(); send_wipe_step(chat_id,3)
                        elif act=="3" and ws["step"]==2:
                            wipe_all_data()
                            states[aid_]="admin"
                            send(chat_id,"*✅ تمام دیتای ربات پاک شد و ربات به حالت اولیه برگشت.*")
                            send_admin_panel(chat_id)
                        else:
                            send(chat_id,"*⚠️ ترتیب تأییدیه‌ها رعایت نشد. از پنل ادمین دوباره شروع کنید.*")
                            wipe_state.pop(aid_,None)

                    elif cb_data.startswith("fake_svc|"):
                        if not is_admin(chat_id): continue
                        nid  = cb_data.split("|",1)[1]
                        node = data["catalog"]["nodes"].get(nid)
                        s    = data["settings"].get(node.get("key")) if node else None
                        if not node or node.get("type")!="service" or not isinstance(s,dict):
                            send(chat_id,"*⚠️ سرویس یافت نشد.*")
                        elif s["min"]==s["max"]:
                            create_fake_order(chat_id,node["key"],s["min"])
                        else:
                            states[str(chat_id)] = f"ap_fake_qty|{nid}"
                            send(chat_id,f"*🧪 تعداد را بفرستید ({s['min']:,} تا {s['max']:,}):*",BACK_BTN)

                    elif cb_data.startswith("cat_"):
                        if not is_admin(chat_id): continue
                        handle_catalog_callback(chat_id,cb_data,data,states)
                    continue

                # ── Message ──────────────────────────────
                if "message" not in upd: continue
                msg     = upd["message"]
                chat_id = msg["chat"]["id"]
                uid     = str(chat_id)
                uinfo   = msg.get("from",{})
                CURRENT_MSG_ID = msg.get("message_id")

                if "successful_payment" in msg:
                    register_successful_order(chat_id,msg["successful_payment"].get("invoice_payload",""))
                    states.pop(uid,None); continue

                text = msg.get("text","").strip()
                if not text: continue

                register_user(data,chat_id,uinfo)

                if data["users"].get(uid,{}).get("blocked"):
                    send(chat_id,"*⛔ دسترسی شما مسدود شده است.*"); continue

                if text=="/admin":
                    if is_admin(chat_id): states[uid]="admin"; send_admin_panel(chat_id)
                    continue

                cur_state=states.get(uid,"")
                if cur_state=="admin" or cur_state.startswith("ap_"):
                    handle_admin(chat_id,text,data,states); continue

                if not check_membership(chat_id):
                    send_join_required(chat_id); continue

                if text=="/start":
                    states.pop(uid,None); send_start(chat_id); continue

                if text in ("🔙 بازگشت به منوی اصلی 🏠","🏠 بازگشت","🔙 بازگشت"):
                    states.pop(uid,None); send_start(chat_id); continue

                # ─ منوی اصلی ─────────────────────────────
                if text in ("مشاهده و خرید خدمات 🛍","سفارش بازدید 👁️","سفارش ممبر 👥"):
                    send_catalog(chat_id,"root",states); continue
                if text=="حساب کاربری 👤":
                    send_account(chat_id); continue
                if text=="پیگیری سفارش 🔎":
                    send_tracking(chat_id); continue
                if text=="قوانین ⚖️":
                    send_rules(chat_id); continue
                if text=="📞 پشتیبانی":
                    states[uid]="support"; send_support_menu(chat_id); continue

                # ─ مرحله قبل ──────────────────────────────
                if text=="🔙 مرحله قبل":
                    if cur_state.startswith("browse|"):
                        fid    = cur_state.split("|",1)[1]
                        parent = data["catalog"]["nodes"].get(fid,{}).get("parent","root")
                    else:
                        parent = last_folder.get(uid,"root")
                    send_catalog(chat_id,parent,states); continue

                # ─ پشتیبانی ───────────────────────────────
                if text=="❌ بستن تیکت" or cur_state=="support":
                    if text!="❌ بستن تیکت": states[uid]="support"
                    handle_support_message(chat_id,text,data,states,uinfo); continue

                # ─ گشت‌وگذار در کاتالوگ خدمات ─────────────
                if cur_state.startswith("browse|"):
                    fid   = cur_state.split("|",1)[1]
                    child = next((n for n in get_children(data,fid)
                                  if n["title"]==text and node_visible(data,n)),None)
                    if child:
                        if child["type"]=="folder":
                            send_catalog(chat_id,child["id"],states)
                        else:
                            last_folder[uid]=fid
                            check_stock_and_start(chat_id,child["key"],data,states)
                    else:
                        send_catalog(chat_id,fid,states)
                    continue

                # ─ مرحله ۱: دریافت تعداد (فقط برای سرویس‌هایی که حداقل ≠ حداکثر است) ─
                if cur_state.startswith("order_qty|"):
                    key = cur_state.split("|",1)[1]
                    s   = data["settings"].get(key)
                    if not isinstance(s,dict) or "price_per_1000" not in s:
                        states.pop(uid,None); send_start(chat_id); continue
                    if not s.get("enabled",True):
                        states.pop(uid,None)
                        send(chat_id,"*⚠️ این سرویس موقتاً غیرفعال است.*",BACK_BTN_USER); continue
                    try:
                        qty = to_int(text)
                    except:
                        send(chat_id,"*⚠️ لطفاً فقط عدد ارسال کنید.*"); continue
                    if qty < s["min"] or qty > s["max"]:
                        send(chat_id,f"*⚠️ تعداد باید بین {s['min']:,} تا {s['max']:,} باشد.*"); continue
                    stock = s.get("stock",999999)
                    if qty > stock:
                        send(chat_id,f"*⚠️ موجودی کافی نیست. حداکثر موجودی فعلی: {stock:,}*"); continue
                    price = calc_price(s,qty)
                    states[uid] = f"order_link|{key}|{qty}"
                    hint = LINK_HINTS.get(s.get("platform",""),"لینک، آیدی یا اطلاعات مورد نیاز سفارش")
                    send(chat_id,
                        f"*✅ تعداد: {qty:,}\n"
                        f"💰 مبلغ قابل پرداخت: {price:,} تومان\n\n"
                        f"🔗 حالا لینک یا آیدی مورد نظر را ارسال کنید:\n"
                        f"{hint}*"
                    )
                    continue

                # ─ مرحله ۲: دریافت لینک → کیف پول یا فاکتور ────
                if cur_state.startswith("order_link|"):
                    parts = cur_state.split("|")
                    try:
                        key = parts[1]; qty = int(parts[2])
                    except:
                        states.pop(uid,None); send_start(chat_id); continue
                    s = data["settings"].get(key)
                    if not isinstance(s,dict) or "price_per_1000" not in s:
                        states.pop(uid,None); send_start(chat_id); continue
                    platform = s.get("platform")
                    link     = text.strip()
                    if platform in LINK_VALIDATORS:
                        link_ok  = LINK_VALIDATORS[platform](link)
                        link_fmt = LINK_HINTS[platform]
                    else:
                        link_ok  = len(link) >= 3
                        link_fmt = "لینک، آیدی یا اطلاعات کامل سفارش"
                    if not link_ok:
                        send(chat_id,
                            f"*⚠️ لینک یا آیدی نامعتبر است.\n\n"
                            f"فرمت صحیح:\n{link_fmt}*"); continue
                    if not s.get("enabled",True):
                        states.pop(uid,None)
                        send(chat_id,"*⚠️ این سرویس موقتاً غیرفعال است.*",BACK_BTN_USER); continue
                    if qty > s.get("stock",999999):
                        states.pop(uid,None)
                        send(chat_id,"*⚠️ موجودی این سرویس تغییر کرد. لطفاً دوباره سفارش دهید.*",BACK_BTN_USER); continue

                    # اگر سرویس کامنت دلخواه است → اول کامنت‌ها را بگیر
                    if s.get("need_comments"):
                        states[uid] = f"order_comments|{key}|{qty}|{link}"
                        send(chat_id,
                            f"*✍️ کامنت‌های دلخواه\n\n"
                            f"تعداد سفارش شما: {qty:,} کامنت\n\n"
                            f"لطفاً دقیقاً {qty:,} کامنت بنویسید.\n"
                            f"هر کامنت را در یک خط جدا بنویسید (بعد از هر کامنت اینتر بزنید).\n\n"
                            f"مثال:\n"
                            f"عالی بود\n"
                            f"خیلی خوبه\n"
                            f"...\n\n"
                            f"⚠️ تعداد خطوط باید دقیقاً برابر {qty:,} باشد.*",
                            kb(["🔙 بازگشت به منوی اصلی 🏠"]))
                        continue

                    price  = calc_price(s,qty)
                    wallet = data["users"].get(uid,{}).get("wallet",0)
                    if wallet >= price:
                        # موجودی کیف پول به‌اندازه‌ی قیمت سفارش هست → از کاربر می‌پرسیم
                        pending_buy[uid] = {"key":key,"qty":qty,"link":link}
                        states[uid] = "order_pay"
                        send(chat_id,
                            f"*💼 روش پرداخت\n\n"
                            f"📦 {svc_label(data,key)}\n"
                            f"🔢 تعداد: {qty:,}\n"
                            f"💰 مبلغ سفارش: {price:,} تومان\n\n"
                            f"💼 موجودی کیف پول شما: {wallet:,} تومان\n\n"
                            f"می‌خواهید این سفارش را با کیف پولتان پرداخت کنید؟*",
                            {"inline_keyboard":[
                                [{"text":"💼 بله، از کیف پول","callback_data":"pay_wallet"}],
                                [{"text":"💳 پرداخت آنلاین","callback_data":"pay_online"}],
                                [{"text":"❌ انصراف","callback_data":"cancel_order"}]
                            ]})
                    else:
                        states.pop(uid,None)
                        send_invoice(chat_id,key,qty,price,link)
                    continue

                # ─ مرحله ۳: دریافت کامنت‌های دلخواه ────
                if cur_state.startswith("order_comments|"):
                    parts = cur_state.split("|")
                    try:
                        key = parts[1]; qty = int(parts[2]); link = parts[3]
                    except:
                        states.pop(uid,None); send_start(chat_id); continue
                    s = data["settings"].get(key)
                    if not isinstance(s, dict):
                        states.pop(uid,None); send_start(chat_id); continue
                    comments = [c.strip() for c in text.splitlines() if c.strip()]
                    if len(comments) != qty:
                        send(chat_id,
                            f"*⚠️ تعداد کامنت‌ها باید دقیقاً {qty:,} باشد.\n"
                            f"شما {len(comments):,} کامنت فرستادید.\n\n"
                            f"هر کامنت را در یک خط جدا بنویسید و دوباره ارسال کنید.*")
                        continue
                    comments_text = "\n".join(comments)
                    price  = calc_price(s, qty)
                    wallet = data["users"].get(uid, {}).get("wallet", 0)
                    if wallet >= price:
                        pending_buy[uid] = {"key": key, "qty": qty, "link": link, "comments": comments_text}
                        states[uid] = "order_pay"
                        send(chat_id,
                            f"*💼 روش پرداخت\n\n"
                            f"📦 {svc_label(data,key)}\n"
                            f"🔢 تعداد: {qty:,}\n"
                            f"💰 مبلغ سفارش: {price:,} تومان\n\n"
                            f"✍️ {qty:,} کامنت دریافت شد.\n\n"
                            f"💼 موجودی کیف پول شما: {wallet:,} تومان\n\n"
                            f"می‌خواهید این سفارش را با کیف پولتان پرداخت کنید؟*",
                            {"inline_keyboard":[
                                [{"text":"💼 بله، از کیف پول","callback_data":"pay_wallet"}],
                                [{"text":"💳 پرداخت آنلاین","callback_data":"pay_online"}],
                                [{"text":"❌ انصراف","callback_data":"cancel_order"}]
                            ]})
                    else:
                        states.pop(uid, None)
                        send_invoice(chat_id, key, qty, price, link, comments=comments_text)
                    continue

                if cur_state=="order_pay":
                    send(chat_id,"*👆 لطفاً یکی از گزینه‌های بالا را انتخاب کنید: کیف پول / پرداخت آنلاین / انصراف.*")
                    continue

                # ─ پیام آزاد وقتی تیکت باز دارد ───────────
                tid,_t = get_user_open_ticket(data,chat_id)
                if tid:
                    states[uid]="support"
                    handle_support_message(chat_id,text,data,states,uinfo); continue

                # ─ هر چیز دیگر → منوی اصلی ───────────────
                send_start(chat_id)

            except Exception as ie:
                print(f"inner error: {ie}")
                continue

        time.sleep(1)

    except Exception as e:
        print(f"ERROR: {e}")
        time.sleep(5)
