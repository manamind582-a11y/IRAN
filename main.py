import requests
import time
import json
import os
import glob
import shutil
import re
import threading
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
FAKE_TEST_DELETE_AFTER = 60   # ثانیه؛ پیام تستِ سفارش فیک بعد از این مدت خودکار از کانال پاک می‌شود
FAKE_LINK            = "https://www.aparat.com/v/TEST"   # لینک پیش‌فرض سفارش‌های فیک (تست)

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

def _ble_rest(link):
    """بخش بعد از ble.ir/ ؛ اگر لینک بله نباشد None"""
    link = link.strip()
    if " " in link or "\n" in link:
        return None
    low = link.lower()
    for p in ["https://ble.ir/", "http://ble.ir/", "ble.ir/"]:
        if low.startswith(p):
            return link[len(p):].split("?")[0].strip("/")
    return None

def validate_bale_id_link(link):
    """فقط شناسه: @username"""
    link = link.strip()
    return link.startswith("@") and len(link) >= 4 and " " not in link and "/" not in link

def validate_bale_channel_link(link):
    """@username یا https://ble.ir/username"""
    if validate_bale_id_link(link):
        return True
    rest = _ble_rest(link)
    return bool(rest) and "/" not in rest and rest.lower() != "join" and len(rest) >= 3

def validate_bale_group_link(link):
    """لینک گروه: https://ble.ir/join/xxxx"""
    rest = _ble_rest(link)
    if not rest:
        return False
    parts = rest.split("/")
    return len(parts) == 2 and parts[0].lower() == "join" and len(parts[1]) >= 3

def validate_bale_channel_group_link(link):
    """لینک کانال یا گروه (عمومی/خصوصی)"""
    return validate_bale_channel_link(link) or validate_bale_group_link(link)

def validate_bale_post_link(link):
    """لینک پست: https://ble.ir/username/123/456"""
    rest = _ble_rest(link)
    if not rest:
        return False
    parts = rest.split("/")
    return (len(parts) in (2, 3) and len(parts[0]) >= 3
            and all(x.isdigit() for x in parts[1:]))

def validate_soroush_id_link(link):
    """یوزرنیم کانال سروش با @"""
    link = link.strip()
    return link.startswith("@") and len(link) >= 4 and " " not in link and "/" not in link

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

# ─ ایتا و آیدی‌های ساده ─
def _eitaa_rest(link):
    """بخش بعد از eitaa.com/ ؛ اگر لینک ایتا نباشد None"""
    link = link.strip()
    if " " in link or "\n" in link:
        return None
    low = link.lower()
    for p in ["https://eitaa.com/", "http://eitaa.com/", "https://www.eitaa.com/",
              "http://www.eitaa.com/", "eitaa.com/", "www.eitaa.com/"]:
        if low.startswith(p):
            return link[len(p):].split("?")[0].strip("/")
    return None

def validate_eitaa_channel_link(link):
    """https://eitaa.com/username"""
    rest = _eitaa_rest(link)
    return bool(rest) and "/" not in rest and rest.lower() != "joinchat" and len(rest) >= 3

def validate_eitaa_join_link(link):
    """https://eitaa.com/joinchat/xxxxxxxx"""
    rest = _eitaa_rest(link)
    if not rest:
        return False
    parts = rest.split("/")
    return len(parts) == 2 and parts[0].lower() == "joinchat" and len(parts[1]) >= 6

def validate_eitaa_channel_or_join_link(link):
    return validate_eitaa_channel_link(link) or validate_eitaa_join_link(link)

def validate_eitaa_post_link(link):
    """https://eitaa.com/username/123"""
    rest = _eitaa_rest(link)
    if not rest:
        return False
    parts = rest.split("/")
    return (len(parts) == 2 and len(parts[0]) >= 3
            and parts[0].lower() != "joinchat" and parts[1].isdigit())

_ID_RE = r"[A-Za-z0-9_]{3,64}"

def validate_plain_id(link):
    """username بدون @"""
    return bool(re.fullmatch(_ID_RE, link.strip()))

def validate_id_at_suffix(link):
    """username@"""
    return bool(re.fullmatch(_ID_RE + "@", link.strip()))

def validate_id_any(link):
    """username یا @username"""
    return bool(re.fullmatch("@?" + _ID_RE, link.strip()))

# ─ روبیکا / روبینو ─
def _rubika_rest(link):
    """بخش بعد از rubika.ir/ ؛ اگر لینک روبیکا نباشد None"""
    link = link.strip()
    if " " in link or "\n" in link:
        return None
    low = link.lower()
    for p in ["https://rubika.ir/", "http://rubika.ir/", "https://www.rubika.ir/",
              "http://www.rubika.ir/", "rubika.ir/", "www.rubika.ir/"]:
        if low.startswith(p):
            return link[len(p):].split("?")[0].strip("/")
    return None

def validate_rubika_post_link(link):
    """https://rubika.ir/username/POSTCODE"""
    rest = _rubika_rest(link)
    if not rest:
        return False
    parts = rest.split("/")
    return (len(parts) == 2 and len(parts[0]) >= 3 and len(parts[1]) >= 6
            and parts[0].lower() not in ("post", "page", "joinc", "joing"))

def validate_rubika_chat_link(link):
    """لینک کانال/گروه: https://rubika.ir/username  یا  https://rubika.ir/joinc/xxxx"""
    rest = _rubika_rest(link)
    if not rest:
        return False
    parts = rest.split("/")
    if len(parts) == 1:
        return len(parts[0]) >= 3 and parts[0].lower() not in ("post", "page")
    return len(parts) == 2 and parts[0].lower().startswith("join") and len(parts[1]) >= 4

def validate_rubika_any_link(link):
    rest = _rubika_rest(link)
    return bool(rest) and len(rest) >= 3

def validate_rubino_post_link(link):
    """https://rubika.ir/post/AbCfGh"""
    rest = _rubika_rest(link)
    if not rest:
        return False
    parts = rest.split("/")
    return len(parts) == 2 and parts[0].lower() == "post" and len(parts[1]) >= 4

def validate_rubino_page(link):
    """یوزرنیم پیج (بدون @) یا https://rubika.ir/page/username"""
    link = link.strip()
    if re.fullmatch(_ID_RE, link):
        return True
    rest = _rubika_rest(link)
    if not rest:
        return False
    parts = rest.split("/")
    return len(parts) == 2 and parts[0].lower() == "page" and bool(re.fullmatch(_ID_RE, parts[1]))

# ─ اینستاگرام ─
_IG_HOST = r"(?:https?://)?(?:www\.)?instagram\.com"
_IG_USER = r"[A-Za-z0-9_.]{2,30}"

def validate_insta_post(link):
    """https://www.instagram.com/reel/xyz  (p / reel / reels / tv)"""
    return bool(re.fullmatch(_IG_HOST + r"/(?:p|reel|reels|tv)/[A-Za-z0-9_-]{4,}/?(?:\?\S*)?", link.strip(), re.I))

def validate_insta_story_link(link):
    """https://instagram.com/stories/username/1234567890"""
    return bool(re.fullmatch(_IG_HOST + r"/stories/" + _IG_USER + r"/\d+/?(?:\?\S*)?", link.strip(), re.I))

def validate_insta_post_or_story(link):
    return validate_insta_post(link) or validate_insta_story_link(link)

def validate_insta_user(link):
    """username یا @username یا https://instagram.com/username"""
    link = link.strip()
    if re.fullmatch("@?" + _IG_USER, link):
        return True
    m = re.fullmatch(_IG_HOST + r"/(" + _IG_USER + r")/?(?:\?\S*)?", link, re.I)
    return bool(m) and m.group(1).lower() not in ("p", "reel", "reels", "tv", "stories", "explore")

def validate_insta_live(link):
    link = link.strip()
    return validate_insta_user(link) or bool(re.fullmatch(_IG_HOST + r"/" + _IG_USER + r"/live/\S*", link, re.I))

def validate_phone_ir(link):
    return bool(re.fullmatch(r"(?:\+98|0098|98|0)?9\d{9}", link.strip().replace(" ", "")))

def _ig_lines(link):
    return [l.strip() for l in link.strip().split("\n") if l.strip()]

def validate_insta_post_user(link):
    """خط ۱: لینک پست شما | خط ۲: آیدی پیج هدف"""
    ls = _ig_lines(link)
    return len(ls) == 2 and validate_insta_post(ls[0]) and validate_insta_user(ls[1])

def validate_insta_post_media(link):
    """خط ۱: لینک پست شما | خط ۲: لینک پست هدف"""
    ls = _ig_lines(link)
    return len(ls) == 2 and validate_insta_post(ls[0]) and validate_insta_post(ls[1])

def validate_insta_post_list(link):
    """خط ۱: لینک پست شما | خطوط بعد: یوزرنیم‌ها (هر کدام یک خط، بدون @)"""
    ls = _ig_lines(link)
    return (len(ls) >= 2 and validate_insta_post(ls[0])
            and all(re.fullmatch(_IG_USER, x) for x in ls[1:]))

_EMAIL_RE = r"[^@\s]+@[^@\s]+\.[^@\s]+"

def validate_email_media(link):
    """خط ۱: ایمیل | خط ۲: لینک پست هدف"""
    ls = _ig_lines(link)
    return len(ls) == 2 and bool(re.fullmatch(_EMAIL_RE, ls[0])) and validate_insta_post(ls[1])

def validate_email_user(link):
    """خط ۱: ایمیل | خط ۲: آیدی پیج هدف"""
    ls = _ig_lines(link)
    return len(ls) == 2 and bool(re.fullmatch(_EMAIL_RE, ls[0])) and validate_insta_user(ls[1])

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
        text = f"{s.get('icon', '🎬')} {s['head']} (تومان {calc_price(s, s['min']):,})\n\n{s.get('desc', '')}"
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

def _delete_test_post(channel, message_id, notify_chat):
    """پاک کردن پیام تستِ سفارش فیک از کانال."""
    ok = False
    try:
        r = requests.post(f"{BASE_URL}/deleteMessage",
                          json={"chat_id": channel, "message_id": message_id}, timeout=10).json()
        ok = bool(r.get("ok"))
    except Exception as e:
        print(f"delete test post error: {e}")
    if notify_chat:
        send(notify_chat, "*🧹 پیام تست از کانال پاک شد.*" if ok else
             "*⚠️ پیام تست از کانال پاک نشد! لطفاً همین الان دستی پاکش کنید (ربات باید دسترسی حذف پیام داشته باشد).*")

def complete_order(order_id, notify_chat=None):
    data   = load_data()
    target = next((o for o in data["orders"] if o["id"]==order_id),None)
    if not target: return False,"سفارش یافت نشد."
    if target["status"]=="done": return False,"این سفارش قبلاً تکمیل شده."
    if target["status"]=="cancelled": return False,"این سفارش لغو شده است."
    target["status"]="done"; save_data(data)
    masked=mask_user_id(target["user_id"]); jalali_now=now_jalali_str()
    channel=data["settings"]["channel"]
    fake = bool(target.get("fake"))      # سفارش فیک: بدون برچسب می‌رود ولی چند ثانیه بعد خودکار پاک می‌شود
    tag  = ""
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
        if fake:
            mid = (r.get("result") or {}).get("message_id")
            if mid:
                threading.Timer(FAKE_TEST_DELETE_AFTER, _delete_test_post, args=(channel, mid, notify_chat)).start()
                if notify_chat:
                    send(notify_chat, f"*🧪 پیام تست توی کانال گذاشته شد و بعد از {FAKE_TEST_DELETE_AFTER} ثانیه خودکار پاک می‌شود.*")
            elif notify_chat:
                send(notify_chat, "*⚠️ پیام تست توی کانال رفت ولی آیدی پیام نگرفتم؛ لطفاً دستی پاکش کنید.*")
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

def send_fake_service_list(chat_id, data, fid="root"):
    """انتخاب سرویس برای سفارش فیک، پوشه‌به‌پوشه (مثل منوی کاربر)."""
    nodes = data["catalog"]["nodes"]
    if fid != "root" and (fid not in nodes or nodes[fid]["type"] != "folder"):
        fid = "root"
    rows = []
    for n in nodes.values():
        if n["parent"] != fid:
            continue
        if n["type"] == "folder":
            rows.append([{"text": n["title"], "callback_data": f"fake_open|{n['id']}"}])
        elif n.get("key") in data["settings"]:
            rows.append([{"text": n["title"], "callback_data": f"fake_svc|{n['id']}"}])
    if fid != "root":
        rows.append([{"text": "🔙 بازگشت", "callback_data": f"fake_open|{nodes[fid]['parent']}"}])
    if not rows:
        send(chat_id, "*⚠️ این بخش خالی است.*", BACK_BTN); return
    head = ("*🧪 سفارش فیک (تست)\n\n"
            "اول اپلیکیشن، بعد بخش و در آخر سرویس را انتخاب کنید. "
            "سفارش فیک روی آمار، موجودی و کیف پول اثری ندارد و با «✅ تکمیل سفارش» گزارش تست به کانال می‌رود.*"
            if fid == "root" else f"*🧪 سفارش فیک\n📂 {cat_path(data, fid)}*")
    send(chat_id, head, {"inline_keyboard": rows})

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

# ══════════════════════════════════════════
#  بله (ممبر / ری‌اکشن) و ممبر سروش
# ══════════════════════════════════════════
# عنوان اپلیکیشن‌ها (دایره‌ی رنگی): بله سبز، سروش آبی، آپارات بنفش، ایتا نارنجی
APARAT_TITLE  = "🟣 آپارات"
SOROUSH_TITLE = "🔵 سروش"
BALE_TITLE    = "🟢 بله"
EITAA_TITLE   = "🟠 ایتا"
RUBIKA_TITLE  = "🟡 روبیکا"
INSTAGRAM_TITLE = "🔴 اینستاگرام"
_APP_TITLE_ALIASES = {          # عنوان جدید ← عنوان‌های قدیمی که باید شناخته شوند
    APARAT_TITLE:  {APARAT_TITLE,  "🎬 آپارات"},
    SOROUSH_TITLE: {SOROUSH_TITLE, "📱 سروش"},
    BALE_TITLE:    {BALE_TITLE,    "🔵 بله"},
    EITAA_TITLE:   {EITAA_TITLE},
    RUBIKA_TITLE:  {RUBIKA_TITLE},
    INSTAGRAM_TITLE: {INSTAGRAM_TITLE},
}

def find_app_folder(data, title):
    names = _APP_TITLE_ALIASES.get(title, {title})
    return next((n["id"] for n in data["catalog"]["nodes"].values()
                 if n["type"] == "folder" and n["parent"] == "root" and n["title"] in names), None)

def rename_app_circles(data):
    """یک‌بار: عنوان پوشه‌های اپلیکیشن را به دایره‌ی رنگی جدید تغییر می‌دهد (بقیه‌ی کاتالوگ دست نمی‌خورد)."""
    nodes = (data.get("catalog") or {}).get("nodes") or {}
    for new, olds in _APP_TITLE_ALIASES.items():
        for n in nodes.values():
            if n["type"] == "folder" and n["parent"] == "root" and n["title"] in olds and n["title"] != new:
                n["title"] = new
                if new == BALE_TITLE and n.get("text"):
                    n["text"] = n["text"].replace("🔵", "🟢")

_BALE_MEMBER_NOTES = (
    "نکات مهم :\n\n"
    "📌 در زمان ثبت سفارش از سرویس یا سایت دیگر سفارش ممبر ثبت نکنید.\n\n"
    "📌کانال در حال ریزش نباشد. مسئولیت ریزش ممبرهای قبلی کانال بر عهده مشتری می باشد.\n\n"
    "📌قبل از خرید، موارد بالا را خوانده و پذیرفته اید! اگر موافق توضیحات بالا نیستید، سفارش ثبت نکنید."
)
_BALE_BUY_NOTE = "📌قبل از خرید، موارد بالا را خوانده و پذیرفته اید! اگر موافق توضیحات بالا نیستید، سفارش ثبت نکنید."

def _bale_member_desc(head, price, drop, finish, link_line, samples, start=None):
    lines = [f"{head} (تومان {price:,} برای هر ۱۰۰۰)", ""]
    if start:
        lines += [f"🕑 زمان شروع : {start}", "", "📂 نوع ممبر: فیک", "",
                  f"🩸 میزان ریزش : {drop}", "", f"✅ زمان تکمیل : {finish}", ""]
    else:
        lines += [f"✅ زمان تکمیل : {finish}", "", "📂 نوع ممبر: فیک", "",
                  f"🩸 میزان ریزش : {drop}", ""]
    lines += [f"🔗 لینک : {link_line}", "", "نمونه لینک", ""]
    for smp in samples:
        lines += [smp, ""]
    return "\n".join(lines) + "\n" + _BALE_MEMBER_NOTES

def _bale_real_member_desc(head, price, link_line, link_sample):
    return (f"{head} (تومان {price:,} برای هر ۱۰۰۰)\n\n"
            "🕑 زمان شروع : 6 الی 24 ساعت\n\n"
            "✅ زمان تکمیل : 1 تا 3 روز\n\n"
            "🩸 میزان ریزش : به دلیل واقعی بودن ممبرها ریزش نامشخص است.\n\n"
            "👌 کیفیت سرویس : واقعی\n\n"
            f"🔗 فرمت لینک : {link_line}\n\n"
            f"{link_sample}\n\n"
            f"{_BALE_BUY_NOTE}")

_ALL_POS = "❤👌🏼👏🏼✅️🔥🚀🙏🏼😍🌷"

# (کلید، عنوان دکمه، نام سفارش، قیمت هر ۱۰۰۰، حداقل، حداکثر، توضیحات، نوع لینک)
BALE_MEMBER_SERVICES = [
    ("bale_mem_7_slow", "🐢 ممبر کانال و گروه - ۷ روز (سرعت کم)",
     "ممبر کانال و گروه بله {بدون ریزش 7 روزه} - سرعت کم", 273000, 500, 31000,
     _bale_member_desc("ممبر کانال و گروه بله {بدون ریزش 7 روزه} - سرعت کم", 273000,
                       "7 روز بدون ریزش", "48 تا 72 ساعت", "لینک عمومی یا خصوصی کانال یا گروه بله",
                       ["https://ble.ir/marketing98", "https://ble.ir/join/nt4q4AiHp1"], start="24 تا 48 ساعت"),
     "bale_channel_group"),
    ("bale_mem_7_fast", "⚡ ممبر کانال - ۷ روز بدون ریزش (سریع)",
     "ممبر کانال بله - 7 روز بدون ریزش - سریع", 286000, 100, 15000,
     _bale_member_desc("ممبر کانال بله - 7 روز بدون ریزش - سریع", 286000,
                       "7 روز بدون ریزش", "5 تا 24 ساعت", "لینک عمومی یا شناسه کانال",
                       ["@marketing98", "https://ble.ir/marketing98"]),
     "bale_channel"),
    ("bale_mem_drop", "👤 ممبر کانال - ریزش دار (واقعی)",
     "ممبر کانال بله {ریزش دار}", 380800, 100, 10000,
     _bale_real_member_desc("ممبر کانال بله {ریزش دار}", 380800, "فقط شناسه کانال", "@iran"),
     "bale_id"),
    ("bale_mem_30_fast", "🚀 ممبر کانال - ۱ ماه بدون ریزش (سریع)",
     "ممبر کانال بله {بدون ریزش 1 ماه} - سریع", 600000, 100, 20000,
     _bale_member_desc("ممبر کانال بله {بدون ریزش 1 ماه} - سریع", 600000,
                       "30 روز بدون ریزش", "6 تا 24 ساعت", "لینک عمومی یا شناسه کانال",
                       ["@marketing98", "https://ble.ir/marketing98"]),
     "bale_channel"),
    ("bale_mem_30_slow", "🐌 ممبر کانال و گروه - ۱ ماه (سرعت کم)",
     "ممبر کانال و گروه بله {بدون ریزش 1 ماه} سرعت کم", 612000, 1000, 31000,
     _bale_member_desc("ممبر کانال و گروه بله {بدون ریزش 1 ماه} سرعت کم", 612000,
                       "30 روز بدون ریزش", "48 تا 72 ساعت", "لینک عمومی یا خصوصی کانال یا گروه بله",
                       ["https://ble.ir/marketing98", "https://ble.ir/join/nt4q4AiHp1"], start="24 تا 48 ساعت"),
     "bale_channel_group"),
    ("bale_mem_group_drop", "👥 ممبر گروه - ریزش دار (واقعی)",
     "ممبر گروه بله {ریزش دار}", 756000, 100, 10000,
     _bale_real_member_desc("ممبر گروه بله {ریزش دار}", 756000, "لینک گروه بله", "https://ble.ir/join/nt4q4AiHp1"),
     "bale_group"),
    ("bale_mem_90", "🛡 ممبر کانال - ۹۰ روز بدون ریزش",
     "ممبر کانال بله {بدون ریزش 90 روز}", 1280000, 100, 13000,
     _bale_member_desc("ممبر کانال بله {بدون ریزش 90 روز}", 1280000,
                       "90 روز بدون ریزش", "48 تا 72 ساعت", "لینک عمومی یا شناسه کانال",
                       ["@marketing98", "https://ble.ir/marketing98"]),
     "bale_channel"),
    ("bale_mem_12m", "👑 ممبر کانال - ۱۲ ماه بدون ریزش",
     "ممبر کانال بله {بدون ریزش 12 ماه}", 3190000, 100, 13000,
     _bale_member_desc("ممبر کانال بله {بدون ریزش 12 ماه}", 3190000,
                       "12 ماه بدون ریزش", "48 تا 72 ساعت", "لینک عمومی یا شناسه کانال",
                       ["@marketing98"]),
     "bale_channel"),
]

# ── ری‌اکشن بله ──
_RX_NOTE_MIX    = "🔸ری اکشن مورد نظر حتما برای پست فعال باشد\n🔸کانال عمومی باشد."
_RX_NOTE_MIX_S  = "🔸ری اکشن های مورد نظر حتما برای پست فعال باشد\n🔸کانال عمومی باشد."
_RX_NOTE_SINGLE = ("📌کانال حتما عمومی باشد و دارای لینک عمومی باشد.\n"
                   "⚠️ در صورت درج لینک اشتباه وضعیت سفارش شما تکمیل شده و هزینه برگشت داده نمی شود.")
_RX_NOTE_LAST   = "🔸ری اکشن مورد نظر حتما برای پست فعال باشد\n\n🔸کانال نباید خصوصی باشد."

def _bale_react_desc(head, price, start, link_line, sample, notes, finish="24 تا 48 ساعت"):
    return (f"{head} (تومان {price:,} برای هر ۱۰۰۰)\n"
            f"⏰استارت: {start}\n\n"
            f"✅ زمان تکمیل : {finish}\n\n"
            f"🔗 لینک : {link_line}\n\n"
            f"{sample}\n"
            "---------------\n\n"
            f"⚠️ نکات مهم:\n\n{notes}")

_BALE_POST_SAMPLE = "https://ble.ir/username/123/456"

# ری‌اکشن‌های میکس و «پست‌های آخر»
BALE_REACTION_SERVICES = [
    ("bale_rx_pos_mix", "✨ ری‌اکشن مثبت میکس", "ری اکشن مثبت میکس پست کانال بله", 44800, 100, 5000,
     _bale_react_desc(f"ری اکشن مثبت میکس پست کانال بله ({_ALL_POS})", 44800,
                      "2 الی 12 ساعت", "لینک پست کانال بله وارد شود", _BALE_POST_SAMPLE, _RX_NOTE_MIX),
     "bale_post"),
    ("bale_rx_neg_mix", "💢 ری‌اکشن منفی میکس", "ری اکشن منفی میکس پست کانال بله", 44800, 100, 5000,
     _bale_react_desc("ری اکشن منفی میکس پست کانال بله (🤯👎🏼😐😡)", 44800,
                      "2 الی 12 ساعت", "لینک پست کانال بله وارد شود", _BALE_POST_SAMPLE, _RX_NOTE_MIX),
     "bale_post"),
    ("bale_rx_pos_single_post", "🌟 ری‌اکشن مثبت - تک پست", "ری اکشن مثبت بله - تک پست", 72000, 100, 20000,
     _bale_react_desc("ری اکشن مثبت بله (❤👌🏼✅️🔥🙏🏼😍🌷) - تک پست", 72000,
                      "2 الی 12 ساعت", "لینک پست کانال بله وارد شود", _BALE_POST_SAMPLE, _RX_NOTE_MIX_S),
     "bale_post"),
    ("bale_rx_last5", "📚 ری‌اکشن مثبت - ۵ پست آخر", "ری اکشن مثبت 5 پست آخر کانال بله", 444000, 75, 10000,
     _bale_react_desc(f"ری اکشن مثبت 5 پست آخر کانال بله ({_ALL_POS})", 444000,
                      "30 دقیقه الی 3 ساعت (اغلب سریع)", "شناسه کانال بله", "@iran", _RX_NOTE_LAST,
                      finish="48 تا 72 ساعت"),
     "bale_id"),
    ("bale_rx_last10", "🏆 ری‌اکشن مثبت - ۱۰ پست آخر", "واکنش های مثبت 10 پست آخر کانال بله", 744000, 75, 10000,
     _bale_react_desc(f"واکنش های مثبت 10 پست آخر کانال بله ({_ALL_POS})", 744000,
                      "30 دقیقه الی 3 ساعت (اغلب سریع)", "شناسه کانال بله", "@iran", _RX_NOTE_LAST,
                      finish="48 تا 72 ساعت"),
     "bale_id"),
]

# ری‌اکشن تک‌ایموجی: (ایموجی، قیمت هر ۱۰۰۰)
BALE_SINGLE_REACTIONS = [
    ("🔥", 48000), ("😂", 48000), ("🙏", 48000), ("👍", 48000), ("❤", 48000),
    ("👌", 48000), ("🥳", 48000), ("😍", 48000), ("👏", 48000), ("🇮🇷", 48000),
    ("😘", 48000), ("🗿", 48000), ("😨", 48000), ("🤬", 48000), ("🇵🇸", 48000),
    ("💔", 48000), ("🌷", 48800), ("🖤", 48000), ("✅", 48800),
]

def _bale_single_reactions():
    out = []
    for i, (emo, price) in enumerate(BALE_SINGLE_REACTIONS, 1):
        head = f"ری اکشن پست کانال بله {emo}"
        out.append((f"bale_rx_{i}", f"ری‌اکشن {emo}", head, price, 100, 20000,
                    _bale_react_desc(head, price, "2 الی 12 ساعت", "لینک پست کانال بله وارد شود",
                                     _BALE_POST_SAMPLE, _RX_NOTE_SINGLE),
                    "bale_post"))
    return out

# ── ممبر سروش ──
def _soroush_member_desc(head, price, drop, public_note=False):
    notes = "نکات مهم :\n\n"
    if public_note:
        notes += "📌 کانال عمومی باشد.\n\n"
    notes += ("📌 در زمان ثبت سفارش از سرویس یا سایت دیگر سفارش ممبر ثبت نکنید.\n\n"
              "📌کانال در حال ریزش نباشد. مسئولیت ریزش ممبرهای قبلی کانال بر عهده مشتری می باشد.\n\n"
              f"{_BALE_BUY_NOTE}")
    return (f"{head} (تومان {price:,} برای هر ۱۰۰۰)\n"
            "✅ زمان تکمیل : 48 تا 72 ساعت\n\n"
            "📂 نوع ممبر: فیک\n\n"
            f"🩸 میزان ریزش : {drop}\n\n"
            "🔗 لینک : یوزرنیم کانال با @ وارد کنید مثال:\n\n"
            "@username\n\n" + notes)

SOROUSH_MEMBER_SERVICES = [
    ("soroush_mem_7", "🌱 ممبر کانال سروش - ۷ روز", "ممبر کانال سروش - 7 روز بدون ریزش", 210000, 100, 5000,
     _soroush_member_desc("ممبر کانال سروش - 7 روز بدون ریزش", 210000, "7 روز بدون ریزش")),
    ("soroush_mem_30", "🌿 ممبر کانال سروش - ۳۰ روز", "ممبر کانال سروش - 30 روز بدون ریزش", 540000, 100, 10000,
     _soroush_member_desc("ممبر کانال سروش - 30 روز بدون ریزش", 540000, "30 روز بدون ریزش")),
    ("soroush_mem_60", "🌳 ممبر کانال سروش - ۶۰ روز", "ممبر کانال سروش - 60 روز بدون ریزش", 750000, 100, 7000,
     _soroush_member_desc("ممبر کانال سروش – 60 روز بدون ریزش", 750000, "60 روز بدون ریزش", public_note=True)),
    ("soroush_mem_90", "👑 ممبر کانال سروش - ۹۰ روز", "ممبر کانال سروش - 90 روز بدون ریزش", 990000, 100, 7000,
     _soroush_member_desc("ممبر کانال سروش - 90 روز بدون ریزش", 990000, "90 روز بدون ریزش")),
]

def add_bale_and_soroush_members(data):
    """
    پوشه‌ی «بله» (ممبر + ری‌اکشن) و پوشه‌ی «ممبرها»ی سروش را به کاتالوگِ موجود اضافه می‌کند.
    چیزی را پاک یا جایگزین نمی‌کند و اگر قبلاً اضافه شده باشد کاری نمی‌کند.
    """
    cat = data["catalog"]; nodes = cat["nodes"]; settings = data["settings"]
    if not nodes:          # کاتالوگ عمداً خالی شده (بعد از پاک‌سازی کل حافظه)
        return

    def find_folder(parent, title):
        return next((n["id"] for n in nodes.values()
                     if n["type"] == "folder" and n["parent"] == parent and n["title"] == title), None)

    def add_folder(parent, title, text):
        cat["counter"] += 1
        fid = str(cat["counter"])
        nodes[fid] = {"id": fid, "parent": parent, "type": "folder", "title": title, "text": text}
        return fid

    def add_service(parent, key, title, label, price1000, mn, mx, desc, platform):
        cat["counter"] += 1
        nid = str(cat["counter"])
        nodes[nid] = {"id": nid, "parent": parent, "type": "service", "title": title, "key": key}
        settings[key] = {"enabled": True, "stock": 999999, "unit": "عدد",
                         "min": mn, "max": mx, "price_per_1000": price1000, "platform": platform,
                         "label": label, "head": label, "desc": desc}

    # ─ سروش ← ممبرها ─
    soroush_id = find_app_folder(data, SOROUSH_TITLE)
    if soroush_id and not find_folder(soroush_id, "👥 ممبرها"):
        mid = add_folder(soroush_id, "👥 ممبرها", "ممبر مورد نظر رو انتخاب کن 👇👥")
        for key, title, label, price1000, mn, mx, desc in SOROUSH_MEMBER_SERVICES:
            add_service(mid, key, title, label, price1000, mn, mx, desc, "soroush_id")

    # ─ بله ─
    if not find_app_folder(data, BALE_TITLE):
        bale_id = add_folder("root", BALE_TITLE, "بخش مورد نظر رو انتخاب کن 👇🟢")
        members_id = add_folder(bale_id, "👥 ممبرها", "ممبر مورد نظر رو انتخاب کن 👇👥")
        for key, title, label, price1000, mn, mx, desc, platform in BALE_MEMBER_SERVICES:
            add_service(members_id, key, title, label, price1000, mn, mx, desc, platform)
        react_id = add_folder(bale_id, "❤️ ری‌اکشن و لایک", "ری‌اکشن مورد نظر رو انتخاب کن 👇❤️")
        single_id = add_folder(react_id, "😍 ری‌اکشن تک‌ایموجی", "ایموجی مورد نظر رو انتخاب کن 👇😍")
        for key, title, label, price1000, mn, mx, desc, platform in _bale_single_reactions():
            add_service(single_id, key, title, label, price1000, mn, mx, desc, platform)
        for key, title, label, price1000, mn, mx, desc, platform in BALE_REACTION_SERVICES:
            add_service(react_id, key, title, label, price1000, mn, mx, desc, platform)


# ══════════════════════════════════════════
#  بله (بازدید / تبلیغات)  و  ایتا (ممبر / بازدید / تبلیغات)
# ══════════════════════════════════════════
def _hdr(label, price):
    return f"{label} (تومان {price:,} برای هر ۱۰۰۰)"

# ── بازدید بله ──
def _bale_view_desc(label, price, sample, link_note="آیدی کانال را بدون @ وارد کنید"):
    parts = [_hdr(label, price), "",
             "🕑 زمان شروع : 3 الی 24 ساعت", "",
             "✅ زمان تکمیل : 24 تا 72 ساعت", "",
             "👌 کیفیت سرویس : واقعی", "",
             "-----------------", "",
             f"🔗 نمونه لینک : {sample}", "",
             "-------------------", ""]
    if link_note:
        parts += [link_note, ""]
    parts.append("کانال حتما عمومی باشد")
    return "\n".join(parts)

_BALE_VIEW_CUSTOM_DESC = (
    _hdr("بازدید پست دلخواه کانال بله", 78000) + "\n\n"
    "🕑 زمان شروع : 3 الی 24 ساعت\n\n"
    "✅ زمان تکمیل : 24 تا 72 ساعت\n\n"
    "👌 کیفیت سرویس : واقعی\n\n"
    "نمونه: https://ble.ir/digikalashop/5747922689655516/1637047232600\n\n"
    "❗نحوه کپی لینک.(روی پست مورد نظر کلیک کنید و روی رونوشت پیوند پیام بزنید)"
)

# (کلید، عنوان دکمه، نام سفارش، قیمت هر ۱۰۰۰، حداقل، حداکثر، توضیحات، نوع لینک)
BALE_VIEW_SERVICES = [
    ("bale_view_1", "👁 بازدید ۱ پست", "بازدید ۱ پست بله", 17000, 100, 20000,
     _bale_view_desc("بازدید ۱ پست بله", 17000, "username"), "plain_id"),
    ("bale_view_5", "👀 بازدید ۵ پست", "بازدید ۵ پست بله", 34000, 100, 20000,
     _bale_view_desc("بازدید ۵ پست بله", 34000, "username"), "plain_id"),
    ("bale_view_10", "🔎 بازدید ۱۰ پست", "بازدید ۱۰ پست بله", 48000, 100, 20000,
     _bale_view_desc("بازدید ۱۰ پست بله", 48000, "username"), "plain_id"),
    ("bale_view_20", "📚 بازدید ۲۰ پست", "بازدید ۲۰ پست بله", 57000, 100, 20000,
     _bale_view_desc("بازدید ۲۰ پست بله", 57000, "username"), "plain_id"),
    ("bale_view_last1", "📌 بازدید پست آخر کانال", "بازدید پست آخر کانال بله", 62000, 500, 2000,
     _bale_view_desc("بازدید پست آخر کانال بله", 62000, "username"), "plain_id"),
    ("bale_view_last5", "📑 بازدید ۵ پست آخر کانال", "بازدید 5 پست آخر کانال بله", 68000, 500, 2000,
     _bale_view_desc("بازدید 5 پست آخر کانال بله", 68000, "username"), "plain_id"),
    ("bale_view_custom", "🎯 بازدید پست دلخواه کانال", "بازدید پست دلخواه کانال بله", 78000, 500, 2000,
     _BALE_VIEW_CUSTOM_DESC, "bale_post"),
    ("bale_view_last10", "🗂 بازدید ۱۰ پست آخر کانال", "بازدید 10 پست آخر کانال بله", 99600, 500, 2000,
     _bale_view_desc("بازدید 10 پست آخر کانال بله", 99600, "username"), "plain_id"),
    ("bale_view_last30", "🏆 بازدید ۳۰ پست آخر کانال", "بازدید پست کانال بله (30 پست آخر)", 112000, 100, 20000,
     _bale_view_desc("بازدید پست کانال بله (30 پست آخر)", 112000, "username@", link_note=None), "id_at_suffix"),
]

# ── تبلیغات بله ── قیمت ثابت (تعداد ۱)
def _bale_popup_desc(start_title, start_val, members, guarantee=False):
    g = "عدد جذب ممبر تضمینی نیست و تعداد ممبر دریافتی به جذابیت کانال بستگی دارد.\n\n" if guarantee else ""
    return (f"🕑 {start_title} : {start_val}\n\n"
            f"🚀 تعداد ممبر : جذب حدودی {members}\n\n"
            f"{g}"
            "🩸 میزان ریزش : ممبر ها واقعی اند و ممکن است از کانال لفت دهند\n\n"
            "🔗 نمونه لینک : لینک جوین کانال بله را ثبت کنید\n\n"
            "نکات مهم :\n\n"
            "📌بعد از ثبت سفارش امکان لغو و برگشت وجه وجود ندارد.\n\n"
            "📌پست گذاری در زمان انجام سفارش ممنوع است")

def _bale_ad_desc(start):
    return (f"🕑 زمان شروع : {start}\n\n"
            "👌 کیفیت سرویس : واقعی\n\n"
            "🔗 نمونه لینک : لینک کانال بله را ثبت کنید\n\n"
            "نکات مهم :\n\n"
            "📌نمایش تبلیغ شما در تب گفت‌وگوی کاربران با مدل پرداخت به ازای بازدید\n\n"
            "📌تضمینی بابت افزایش فروش و جذب ممبر وجود ندارد و بازخورد تبلیغ بستگی به کانال شما دارد\n\n"
            "📌بعد از ثبت سفارش امکان لغو و برگشت وجه وجود ندارد.\n\n"
            "📌 هرجا سوالی داشتید و یا نیاز به راهنمایی داشتید به پشتیبانی پیام دهید")

# (کلید، عنوان دکمه، نام سفارش، قیمت کل (تومان)، توضیحات، نوع لینک، آیکن)
BALE_AD_SERVICES = [
    ("bale_popup_3h", "⏱ پاپ آپ ۳ ساعته", "پاپ آپ بله 3 ساعته [جذب 100 الی 200 ممبر]", 2760000,
     _bale_popup_desc("زمان تکمیل", "1 الی 3 روز", "100 الی 200 ممبر"), "bale_channel_group", "📣"),
    ("bale_popup_6h", "⏰ پاپ آپ ۶ ساعته", "پاپ آپ بله 6 ساعته [جذب 200 الی 400 ممبر]", 4440000,
     _bale_popup_desc("زمان شروع", "1 الی 3 روز", "200 الی 400 ممبر"), "bale_channel_group", "📣"),
    ("bale_popup_12h", "🕛 پاپ آپ ۱۲ ساعته", "پاپ آپ بله 12 ساعته [جذب 300 الی 600 ممبر]", 6636000,
     _bale_popup_desc("زمان شروع", "1 الی 3 روز", "300 الی 600 ممبر", guarantee=True), "bale_channel_group", "📣"),
    ("bale_ad_channels", "📢 تبلیغ پست داخل کانال‌ها", "تبلیغ پست داخل کانال ها", 9100000,
     _bale_ad_desc("7 الی 15 روز"), "bale_channel", "📢"),
    ("bale_ad_view_tab", "👁 تبلیغ بازدیدی تب گفتگو", "تبلیغ بازدیدی تب گفتگو با لینک داخل", 19440000,
     _bale_ad_desc("2 الی 5 روز"), "bale_channel", "📢"),
    ("bale_ad_click_tab", "🖱 تبلیغ کلیکی تب گفتگو", "تبلیغ کلیکی تب گفتگو با لینک داخل", 22200000,
     _bale_ad_desc("2 الی 5 روز"), "bale_channel", "📢"),
]

# ── ممبر ایتا ──
_EITAA_BUY_NOTE = "📌قبل از خرید، موارد بالا را خوانده و پذیرفته اید! اگر موافق توضیحات بالا نیستید، سفارش ثبت نکنید."
_EITAA_WRONG_LINK = "📌 اگر لینک اشتباه وارد کنید هزینه سوخت خواهد شد."

EITAA_MEMBER_SERVICES = [
    ("eitaa_mem_force", "🔒 ممبر کانال | اد اجباری", "ممبر کانال ایتا | اد اجباری", 294600, 100, 5000,
     _hdr("ممبر کانال ایتا | اد اجباری", 294600) + "\n\n"
     "🕑 زمان شروع : 12 تا 24 ساعت\n"
     "🩸 میزان ریزش : ریزش بستگی به کانال بین 30 تا 80 درصد\n"
     "✅ زمان تکمیل : 48 تا 72 ساعت\n"
     "🔗 نمونه لینک : یوزنیم کانال با @ وارد کنید\n\n"
     "مثال:\n\nmarketing98@\n\n"
     "نکات مهم :\n" + _EITAA_WRONG_LINK + "\n" + _EITAA_BUY_NOTE,
     "id_at_suffix"),
    ("eitaa_mem_s2", "⚡ ممبر کانال - سرور ۲", "ممبر کانال ایتا - سرور 2", 316800, 100, 20000,
     _hdr("ممبر کانال ایتا - سرور 2", 316800) + "\n\n"
     "🕑 زمان شروع : 12 تا 24 ساعت\n\n"
     "🩸 میزان ریزش : ریزش بستگی به کانال بین 30 تا 80 درصد\n\n"
     "✅ زمان تکمیل : 48 تا 72 ساعت\n\n"
     "🔗 نمونه لینک : یوزنیم کانال وارد کنید مثال:\n\nmarketing98\n\n"
     "نکات مهم :\n\n" + _EITAA_WRONG_LINK + "\n\n" + _EITAA_BUY_NOTE,
     "plain_id"),
    ("eitaa_mem_vip", "⭐ ممبر کانال - اختصاصی", "ممبر کانال ایتا-اختصاصی⭐", 483000, 500, 30000,
     _hdr("ممبر کانال ایتا-اختصاصی⭐", 483000) + "\n\n"
     "🕑 زمان شروع : 12 تا 24 ساعت\n"
     "🩸 میزان ریزش : نامشخص است بین 30 تا 80 درصد\n"
     "✅ زمان تکمیل : 48 تا 72 ساعت\n"
     "🔗 نمونه لینک : آیدی کانال را وارد کنید.\n\n"
     "نکات مهم :\n📌 کانال عمومی باشد.\n\n"
     "📌 در صورت وارد کردن لینک اشتباه هزینه سوخت خواهد شد.\n" + _EITAA_BUY_NOTE,
     "id_any"),
    ("eitaa_mem_group", "👥 ممبر گروه ایتا", "ممبر گروه ایتا", 500000, 500, 30000,
     _hdr("ممبر گروه ایتا", 500000) + "\n\n"
     "این سرویس برای گروه ایتا است\n"
     "🕑 زمان شروع : 1 تا 24 ساعت\n"
     "✅ زمان تکمیل : 24 تا 72 ساعت\n"
     "🚀 سرعت ارسال : 100 تا 1000 عدد در 24 ساعت\n"
     "🩸 میزان ریزش : بین 30 الی 70 درصد است\n"
     "🔗 نمونه لینک: https://eitaa.com/joinchat/xxxxxxxx\n\n"
     "نکات مهم :\n\n"
     "📌به هیچ عنوان پس از ثبت سفارش ، آیدی یا لینک گروه خود را تغییر ندهید.\n"
     "📌لطفا در لینک گذاری دقت کنید در صورت لینک گذاری اشتباه امکان لغو و برگشت وجه وجود ندارد.\n"
     "📌ممبر ها فقط برای افزایش آمار هستند، طرفدار مشتری شدن،فعالیت داشتن را از این نوع ممبر نخواهید!",
     "eitaa_join"),
    ("eitaa_mem_quality", "💎 ممبر کانال با کیفیت", "ممبر کانال ایتا با کیفیت", 596000, 100, 10000,
     _hdr("ممبر کانال ایتا با کیفیت", 596000) + "\n\n"
     "🕑 زمان شروع : 0 الی 3 ساعت\n\n"
     "🚀 سرعت ارسال : 1 الی 3کا در 24 ساعت\n\n"
     "🩸 میزان ریزش : به دلیل واقعی بودن ممبرها ریزش دارد و جبران ریزش ندارد\n\n"
     "✅ زمان تکمیل : بستگی به تعداد ممبر ها\n\n"
     "🔗 نمونه لینک : آیدی یا یوزرنیم کانال وارد کنید مثال\n\nmarketing98\n\n"
     "نکات مهم :\n\n"
     "⚠️ لینک دعوت یا لینک عضویت وارد نکنید ! کانال حتما عمومی باشد\n\n"
     "⚠️ پس از ثبت سفارش ، آیدی یا لینک کانال خود را تغییر ندهید.",
     "id_any"),
    ("eitaa_mem_7d", "🛡 ممبر کانال و گروه | ۷ روز بدون ریزش", "ممبر کانال و گروه ایتا {بدون ریزش تا 7 روز}", 680000, 500, 4000,
     _hdr("ممبر کانال و گروه ایتا {بدون ریزش تا 7 روز}", 680000) + "\n\n"
     "⏰ زمان شروع: 6 تا 24 ساعت\n\n"
     "⏰ زمان تکمیل: 48 تا 72 ساعت\n\n"
     "📂 نوع ممبر : فیک\n\n"
     "💧 ریزش: 7 روز بدون ریزش\n\n"
     "🌀 جبران ریزش: ندارد\n\n"
     "🔓 وضعیت کانال: عمومی یا خصوصی\n\n"
     "🔗 لینک: لینک کانال ایتا را وارد کنید، مانند:\n\n"
     "https://eitaa.com/iran\n\n"
     "https://eitaa.com/joinchat/16339448C0f89526ce\n\n"
     "نکات مهم: 🔰\n\n"
     "📌 در زمان ثبت سفارش از سرویس یا سایت دیگر سفارش ممبر ثبت نکنید.\n\n"
     "📌 بعد از گذشت 7 روز تمامی ممبر ها ریزش خواهد داشت.\n\n"
     "📌کانال در حال ریزش نباشد . مسئولیت ریزش ممبرهای قبلی کانال بر عهده مشتری می باشد.\n\n" + _EITAA_BUY_NOTE,
     "eitaa_channel_join"),
]

# ── بازدید ایتا ──
_EITAA_SIMUL = "📌 سفارش همزمان برای یک لینک از یک سرویس ثبت نکنید تا سفارش قبلی شما برای همان لینک تکمیل شود."
_EITAA_VIEW_WARN = "⚠️ در صورت لینک گذاری اشتباه وضعیت سفارش شما تکمیل شده و هزینه برگشت داده نمی شود."

def _eitaa_view_desc(label, price, start, speed, link_head, link_examples, notes,
                     finish_early=False, warn_header=False):
    finish = "✅ زمان تکمیل : 24 تا 48 ساعت"
    body = [f"🕑 زمان شروع : {start}"]
    if finish_early:
        body.append(finish)
    body += [f"🚀 سرعت ارسال : {speed}", "🩸 میزان ریزش : ندارد", "👌 کیفیت سرویس : ایرانی"]
    if not finish_early:
        body.append(finish)
    lines = [_hdr(label, price), "", "\n".join(body), "",
             f"🔗 نمونه لینک : {link_head}", ""]
    lines += link_examples + ["", "نکات مهم :", ""]
    lines += notes
    if warn_header:
        lines += ["", "هشدار :"]
    lines += ["", _EITAA_VIEW_WARN]
    return "\n".join(lines)

EITAA_VIEW_SERVICES = [
    ("eitaa_view_custom", "🎯 بازدید ۱ پست دلخواه", "بازدید ایتا | 1 پست دلخواه", 60000, 100, 10000,
     _eitaa_view_desc("بازدید ایتا | 1 پست دلخواه", 60000, "1 الی 2 ساعت", "1 الی 5 کا در هر 24 ساعت",
                      "لینک پست ایتا", ["https://eitaa.com/marketing98/17"],
                      ["📌کانال حتما عمومی باشد.", "📌سفارش برای پست آخر انجام می شود.", _EITAA_SIMUL]),
     "eitaa_post"),
    ("eitaa_view_last1", "📌 بازدید پست آخر کانال", "بازدید ایتا | یک پست آخر کانال", 80000, 100, 10000,
     _eitaa_view_desc("بازدید ایتا | یک پست آخر کانال", 80000, "1 الی 2 ساعت", "1 الی 5 کا در هر 24 ساعت",
                      "لینک کانال ایتا", ["https://eitaa.com/marketing98"],
                      ["📌کانال حتما عمومی باشد.", "📌سفارش برای پست آخر انجام می شود.", _EITAA_SIMUL]),
     "eitaa_channel"),
    ("eitaa_view_last5_fast", "🚀 بازدید ۵ پست آخر (سریع)", "بازدید ایتا | 5 پست آخر - سریع", 84000, 100, 10000,
     _eitaa_view_desc("بازدید ایتا | 5 پست آخر - سریع", 84000, "1 الی 2 ساعت", "2 الی 10کا در هر 24 ساعت",
                      "آیدی کانال ایتا", ["🔗مثال: marketing98"],
                      ["📌کانال حتما عمومی باشد.", "📌سفارش برای 5 پست آخر انجام می شود.", _EITAA_SIMUL],
                      warn_header=True),
     "plain_id"),
    ("eitaa_view_last10_s2", "🥈 بازدید ۱۰ پست آخر - سرور ۲", "ویو 10 پست آخر کانال ایتا - سرور 2", 87000, 100, 50000,
     _eitaa_view_desc("ویو 10 پست آخر کانال ایتا - سرور 2", 87000, "2 الی 5 ساعت", "2 الی 5کا در هر 24 ساعت",
                      "شناسه کانال (یوزرنیم) را با @ بنویسید", ["user@"],
                      ["📌کانال حتما عمومی باشد.", "📌سفارش برای 10 پست آخر انجام می شود."],
                      finish_early=True),
     "id_at_suffix"),
    ("eitaa_view_last25", "📚 بازدید ۲۵ پست آخر", "بازدید ایتا 25 پست آخر", 117000, 100, 50000,
     _eitaa_view_desc("بازدید ایتا 25 پست آخر", 117000, "2 الی 5 ساعت", "2 الی 5کا در هر 24 ساعت",
                      "شناسه کانال (یوزرنیم) را با علامت @ بنویسید", ["@user"],
                      ["📌کانال حتما عمومی باشد.", "📌سفارش برای 25 پست آخر انجام می شود."],
                      finish_early=True),
     "id_at"),
    ("eitaa_view_last10_fast", "⚡ بازدید ۱۰ پست آخر (سریع)", "بازدید ایتا | 10 پست آخر - سریع", 120000, 100, 10000,
     _eitaa_view_desc("بازدید ایتا | 10 پست آخر - سریع", 120000, "0 الی 3 ساعت", "2 الی 10کا در هر 24 ساعت",
                      "آیدی کانال ایتا", ["🔗مثال: marketing98"],
                      ["📌کانال حتما عمومی باشد.", "📌سفارش برای 10 پست آخر انجام می شود.", _EITAA_SIMUL],
                      warn_header=True),
     "plain_id"),
]

# ── تبلیغات ایتا ── قیمت ثابت (تعداد ۱)
def _eitaa_popup_desc(members, guarantee, last_note):
    g = "عدد جذب ممبر تضمینی نیست و تعداد ممبر دریافتی به جذابیت کانال بستگی دارد.\n\n" if guarantee else ""
    return ("🕑 زمان شروع : 1 الی 3 روز\n\n"
            f"🚀 تعداد ممبر : جذب حدودی {members}\n\n"
            "🩸 میزان ریزش : ممبر ها واقعی اند و ممکن است از کانال لفت دهند\n\n"
            f"{g}"
            "🔗 فرمت لینک : لینک کانال خود را ثبت کنید\n\n"
            "https://eitaa.com/iran\n\n"
            "نکات مهم :\n\n"
            "📌بعد از ثبت سفارش امکان لغو و برگشت وجه وجود ندارد.\n\n"
            f"{last_note}")

def _eitaa_bulk_popup_desc(quality, example_line):
    return ("⏳ زمان شروع: 24 تا 72 ساعت\n\n"
            f"👌 کیفیت: {quality}\n\n"
            "🚀 سرعت ارسال روزانه: بالا\n\n"
            "⛔️ ریزش: به دلیل واقعی بودن نامشخص\n\n"
            "🔗 نحوه درج لینک : لینک کانال ایتا\n\n"
            f"{example_line}\n\n"
            "🔰 بعد از ثبت سفارش حتما جهت رزرو تایم پاپ آپ به پشتیبانی پیام دهید\n\n"
            "🔰 نتیجه گیری و میزان جذب ممبر در این سرویس برعهده خودتان است و ما فقط تعداد پاپ آپ سفارش داده شده "
            "را ارسال میکنیم و هیچ تضمینی در تعداد ممبر جذب شده وجود ندارد.\n\n" + _EITAA_BUY_NOTE)

_EITAA_LAST3 = "📌پست گذاری در هنگام تبلیغ ممنوع است."
_EITAA_LAST_PUBLIC = "📌کانال حتما عمومی باشد."

EITAA_AD_SERVICES = [
    ("eitaa_popup_3h", "⏱ پاپ آپ ۳ ساعته", "پاپ آپ ایتا 3 ساعته [جذب 100 الی 200 ممبر]", 2535000,
     _eitaa_popup_desc("100 الی 200 ممبر", False, _EITAA_LAST3), "eitaa_channel", "📣"),
    ("eitaa_popup_6h", "⏰ پاپ آپ ۶ ساعته", "پاپ آپ ایتا 6 ساعته [جذب 200 الی 400 ممبر]", 5083000,
     _eitaa_popup_desc("200 تا 400 ممبر", True, _EITAA_LAST_PUBLIC), "eitaa_channel", "📣"),
    ("eitaa_popup_50k", "🔥 ۵۰ هزار پاپ آپ", "تبلیغات 50 هزار پاپ آپ ایتا", 6240000,
     _eitaa_bulk_popup_desc("کاملا واقعی", "✏️ مثال درج لینک: https://eitaa.com/marketing98"), "eitaa_channel", "🔥"),
    ("eitaa_popup_12h", "🕛 پاپ آپ ۱۲ ساعته", "پاپ آپ ایتا 12 ساعته [جذب 500 الی 800 ممبر]", 10270000,
     _eitaa_popup_desc("500 الی 800 ممبر", True, _EITAA_LAST_PUBLIC), "eitaa_channel", "📣"),
    ("eitaa_popup_100k", "💥 ۱۰۰ هزار پاپ آپ", "تبلیغات 100 هزار پاپ آپ ایتا", 11520000,
     _eitaa_bulk_popup_desc("فوق العاده بالا و کاملا واقعی", "✏️ مثال درج لینک: https://eitaa.com/iran"),
     "eitaa_channel", "💥"),
    ("eitaa_popup_24h", "🌞 پاپ آپ ۲۴ ساعته", "پاپ آپ ایتا 24 ساعته [جذب 800 الی 1000 ممبر]", 11736000,
     _eitaa_popup_desc("800 تا 1000 ممبر", True, _EITAA_LAST_PUBLIC), "eitaa_channel", "📣"),
    ("eitaa_ad_slot1", "👑 تبلیغات جایگاه یک", "تبلیغات جایگاه یک ایتا", 52800000,
     "⏳ زمان شروع: 24 تا 72 ساعت\n\n"
     "🔗 نحوه درج لینک : لینک کانال ایتا\n\n"
     "✏️ مثال درج لینک: https://eitaa.com/iran\n\n"
     "🔰 بعد از ثبت سفارش حتما جهت رزرو تبلیغات به پشتیبانی پیام دهید\n\n"
     "🔰 نتیجه گیری و میزان جذب ممبر در این سرویس برعهده خودتان است و ما فقط تبلیغات شما را انجام خواهیم داد "
     "و هیچ تضمینی برای فروش و تعداد ممبر جذب شده وجود ندارد\n\n" + _EITAA_BUY_NOTE,
     "eitaa_channel", "👑"),
]

def add_bale_views_ads_and_eitaa(data):
    """
    بله ← «👁 بازدیدها» و «📣 تبلیغات» و اپلیکیشن «🟠 ایتا» (ممبرها / بازدیدها / تبلیغات) را اضافه می‌کند.
    چیزی را پاک یا جایگزین نمی‌کند؛ پوشه یا سرویسی که از قبل باشد دوباره ساخته نمی‌شود.
    """
    cat = data.get("catalog") or {}
    nodes = cat.get("nodes")
    if not nodes:          # کاتالوگ عمداً خالی شده
        return
    settings = data["settings"]

    def find_folder(parent, title):
        return next((n["id"] for n in nodes.values()
                     if n["type"] == "folder" and n["parent"] == parent and n["title"] == title), None)

    def add_folder(parent, title, text):
        cat["counter"] += 1
        fid = str(cat["counter"])
        nodes[fid] = {"id": fid, "parent": parent, "type": "folder", "title": title, "text": text}
        return fid

    def get_folder(parent, title, text):
        return find_folder(parent, title) or add_folder(parent, title, text)

    def add_service(parent, key, title, label, price1000, mn, mx, desc, platform, fixed_price=None, icon=None):
        if key in settings:
            return
        cat["counter"] += 1
        nid = str(cat["counter"])
        nodes[nid] = {"id": nid, "parent": parent, "type": "service", "title": title, "key": key}
        cfg = {"enabled": True, "stock": 999999, "unit": "عدد", "min": mn, "max": mx,
               "price_per_1000": price1000, "platform": platform,
               "label": label, "head": label, "desc": desc}
        if fixed_price:
            cfg["fixed_price"] = fixed_price
            cfg["price_per_1000"] = max(1, round(fixed_price * 1000 / max(1, mn)))
        if icon:
            cfg["icon"] = icon
        settings[key] = cfg

    def add_views(parent, services):
        for key, title, label, price1000, mn, mx, desc, platform in services:
            add_service(parent, key, title, label, price1000, mn, mx, desc, platform)

    def add_fixed(parent, services):
        for key, title, label, price, desc, platform, icon in services:
            add_service(parent, key, title, label, price, 1, 1, desc, platform, fixed_price=price, icon=icon)

    # ─ بله ─
    bale_id = find_app_folder(data, BALE_TITLE)
    if bale_id:
        v = get_folder(bale_id, "👁 بازدیدها", "بازدید مورد نظر رو انتخاب کن 👇👁")
        add_views(v, BALE_VIEW_SERVICES)
        a = get_folder(bale_id, "📣 تبلیغات", "سرویس تبلیغاتی مورد نظر رو انتخاب کن 👇📣")
        add_fixed(a, BALE_AD_SERVICES)

    # ─ ایتا ─
    eitaa_id = find_app_folder(data, EITAA_TITLE) or add_folder("root", EITAA_TITLE, "بخش مورد نظر رو انتخاب کن 👇🟠")
    m = get_folder(eitaa_id, "👥 ممبرها", "ممبر مورد نظر رو انتخاب کن 👇👥")
    add_views(m, EITAA_MEMBER_SERVICES)
    v = get_folder(eitaa_id, "👁 بازدیدها", "بازدید مورد نظر رو انتخاب کن 👇👁")
    add_views(v, EITAA_VIEW_SERVICES)
    a = get_folder(eitaa_id, "📣 تبلیغات", "سرویس تبلیغاتی مورد نظر رو انتخاب کن 👇📣")
    add_fixed(a, EITAA_AD_SERVICES)


# ══════════════════════════════════════════
#  روبیکا (ری‌اکشن / نظرسنجی / لایو / استوری / روبینو / فالوور / ممبر)
# ══════════════════════════════════════════
_RB_LINE = "➖➖➖➖ـ➖➖➖➖"
_RB_GUIDE = (
    "🔴 راهنمای ثبت لینک:\n\n"
    "روی پست موردنظر در کانال انگشت خود را نگه دارید و گزینه «کپی لینک» را انتخاب کنید. سپس لینکی شبیه\n\n"
    "https://rubika.ir/marketing98/HHCEFICGAIFEECA\n\n"
    "را در بخش لینک سفارش وارد نمایید."
)

# ─ ری‌اکشن ─
def _rb_rx_desc(label, price):
    return (_hdr(label, price) + "\n\n"
            "🕑 زمان شروع : 2 الی 6 ساعت\n"
            "👌 کیفیت سرویس : ایرانی\n"
            "✅ زمان تکمیل : 24 تا 48 ساعت\n"
            "🔗 نمونه لینک : لینک پست کانال روبیکا\n\n"
            + _RB_GUIDE + "\n\n"
            "نکات مهم :\n\n"
            "📌 لطفا قبل از ثبت سفارش، از قسمت تنظیمات کانال روبیکا تمامی ری اکشن ها را فعال کنید.\n"
            "📌کانال حتما عمومی باشد و دارای لینک عمومی باشد.\n"
            "📌در صورت رعایت نکردن دو مورد بالا و ثبت سفارش، هزینه قابل برگشت نخواهد بود.\n"
            "📌 سرور معمولاً ۲۰٪ بیشتر یا کمترارسال می کند که این موضوع به رفتار روبیکا بستگی دارد و تحت کنترل ما نیست.")

def _rb_rx_fast_desc(label, price):
    return (_hdr(label, price) + "\n\n"
            "🕑 زمان شروع : 0 الی 1 ساعت\n"
            "🚀 سرعت ارسال : 1 الی 10کا در هر 24 ساعت\n"
            "🩸 میزان ریزش : ندارد\n"
            "👌 کیفیت سرویس : ایرانی\n"
            "✅ زمان تکمیل : 24 تا 48 ساعت\n"
            "🔗 نمونه لینک : لینک پست کانال روبیکا\n\n"
            "نکات مهم :\n\n"
            "📌 لطفا قبل از ثبت سفارش، از قسمت تنظیمات کانال روبیکا تمامی واکنش ها را فعال کنید.\n"
            "📌کانال حتما عمومی باشد و دارای لینک عمومی باشد.\n"
            "📌سفارش همزمان برای یک لینک از یک سرویس ثبت نکنید تا سفارش قبلی شما برای همان لینک تکمیل شود.")

# (کلید، ایموجی، اسم دکمه، نام سفارش، سرویس سریع؟)
_RB_RX_SINGLES = [
    ("rubika_rx_heart",     "❤️", "قلب",       "ری اکشن پست کانال روبیکا (❤)",  False),
    ("rubika_rx_like",      "👍", "لایک",      "ری اکشن پست کانال روبیکا (👍)",  False),
    ("rubika_rx_dislike",   "👎", "دیسلایک",   "ری اکشن پست کانال روبیکا (👎)",  False),
    ("rubika_rx_fire",      "🔥", "آتش",       "ری اکشن پست کانال روبیکا (🔥)",  False),
    ("rubika_rx_love",      "🥰", "عاشق",      "ری اکشن پست کانال روبیکا (🥰)",  False),
    ("rubika_rx_pray",      "🙏", "دعا",       "ری واکنش پست کانال روبیکا (🙏)", True),
    ("rubika_rx_laugh",     "🤣", "خنده",      "ری اکشن پست کانال روبیکا (🤣)",  False),
    ("rubika_rx_angry",     "😡", "عصبانی",    "ری اکشن پست کانال روبیکا (😡)",  True),
    ("rubika_rx_heartfire", "❤️‍🔥", "قلب آتشین", "ری اکشن پست کانال روبیکا (❤‍🔥)", False),
    ("rubika_rx_cry",       "😭", "گریه",      "ری اکشن پست کانال روبیکا (😭)",  False),
]
# (کلید، اسم دکمه، نام سفارش)
_RB_RX_GROUPS = [
    ("rubika_rx_pos", "👍 ری‌اکشن‌های مثبت", "ری‌اکشن های مثبت 👍🔥🎉🤩👌😍💘😘"),
    ("rubika_rx_neg", "👎 ری‌اکشن‌های منفی", "ری‌اکشن های منفی 👎🤬🤮💩🥱😡"),
    ("rubika_rx_mix", "🎲 مخلوط همه‌ی ری‌اکشن‌ها (+🎁بازدید)", "مخلوطی از تمام ری‌ اکشن ها روبیکا [+🎁بازدید]"),
    ("rubika_rx_pink", "💘 ری‌اکشن 💘 (+🎁بازدید)", "ری‌اکشن💘 روبیکا [+🎁بازدید]"),
]

# ─ نظرسنجی ─
def _rb_poll_desc(label, price):
    return (_hdr(label, price) + "\n\n"
            "🕑 زمان شروع : 0 الی 1 ساعت\n"
            "✅ زمان تکمیل : 24 تا 48 ساعت\n"
            "🔗 نمونه لینک : لینک پست کانال روبیکا\n"
            + _RB_LINE + "\n"
            "🌀 نکات مهم\n"
            "📌 درحین انجام سفارش لینک کانال خود را تغییر ندهید. کانال را در حالت خصوصی نگذارید. و یا پست را حذف نکنید. "
            "( درصورت عدم رعایت این موارد سفارش شما سوخت خواهد شد. )\n"
            "📌 درحین انجام سفارش، نظرسنجی را خاتمه ندهید و باز نگه دارید. ( درغیر این صورت سفارش شما سوخت خواهد شد )\n"
            "⭕️ نکته پایانی(مهم):\n"
            "درصورتی که تمایل دارید برای پست خود، هم سفارش رای و هم بازدید ثبت کنید، لطفا ابتدا سفارش بازدید خود را "
            "ارسال نموده و پس از تکمیل آن اقدام به ثبت این سرویس نمایید تا سفارش بازدید شما دچار اختلال نگردد.")

# ─ ممبر گروه / کانال ─
def _rb_group_desc(label, price):
    return (_hdr(label, price) + "\n\n"
            "🕑 زمان شروع : 0 الی 3 ساعت\n"
            "✅ زمان تکمیل : 24 تا 48 ساعت\n"
            "🚀 سرعت ارسال : 5 کا در هر 24 ساعت\n"
            "👌 کیفیت سرویس : ایرانی\n"
            "🔗 نمونه لینک : لینک گروه را وارد کنید\n\n"
            + _RB_LINE + "\n"
            "🌀 نکات مهم\n"
            "📌 تا اتمام سفارش، اطلاعات لینک گروه را تغییر ندهید.\n"
            "📌 حتما از صحت و سلامت لینک خود اطمینان حاصل کنید تا منقضی نشده باشد.\n"
            "📌 به هیچ عنوان از لینک های خصوصی که نیاز به تایید عضویت توسط ادمین گروه میباشد استفاده نکنید."
            "( درصورت استفاده، سفارش شما در لحظه سوخت خواهد شد! )")

def _rb_channel_desc(label, price, months):
    return (_hdr(label, price) + "\n\n"
            "🕑 زمان شروع : 0 الی 3 ساعت\n"
            "✅ زمان تکمیل : 24 تا 48 ساعت\n"
            "🚀 سرعت ارسال : 5 کا در هر 24 ساعت\n"
            f"🩸 میزان ریزش : {months} ماه بدون ریزش\n"
            "👌 کیفیت سرویس : ایرانی\n"
            "🔗 نمونه لینک : لینک عمومی یا خصوصی کانال را وارد کنید\n\n"
            "https://rubika.ir/iran\n\n"
            + _RB_LINE + "\n"
            "🌀 نکات مهم:\n"
            "📌 درحین انجام سفارش، همزمان از ارائه دهنده دیگری سفارش ثبت نکنید.\n"
            "📌 کانال شما حتما باید در حالت عمومی باشد.\n"
            "📌 تا اتمام سفارش،لینک کانال را تغییر ندهید.")

# (کلید، اسم دکمه، نام سفارش، قیمت هر ۱۰۰۰، حداقل، حداکثر)
_RB_GROUP_SERVICES = [
    ("rubika_grp_1m",   "👥 گروه | گارانتی ۱ ماهه",       "ممبر گروه روبیکا بدون ریزش [ گارانتی یک ماهه ]",            360000, 50, 111288),
    ("rubika_grp_1m_m", "🧔🏻‍♂️ گروه آقا | ۱ ماهه",        "ممبر گروه روبیکا بدون ریزش آقا 🧔🏻‍♂️ [ گارانتی یک ماهه ]",  420000, 50, 53463),
    ("rubika_grp_1m_f", "👧🏻 گروه خانم | ۱ ماهه",         "ممبر گروه روبیکا بدون ریزش خانم 👧🏻 [ گارانتی یک ماهه ]",   420000, 50, 57825),
    ("rubika_grp_2m",   "👥 گروه | گارانتی ۲ ماهه",       "ممبر گروه روبیکا بدون ریزش [ گارانتی دو ماهه ]",            450000, 50, 111288),
    ("rubika_grp_3m",   "👥 گروه | گارانتی ۳ ماهه",       "ممبر گروه روبیکا بدون ریزش [ گارانتی سه ماهه ]",            555000, 50, 111288),
    ("rubika_grp_3m_f", "👧🏻 گروه خانم | ۳ ماهه",         "ممبر گروه روبیکا بدون ریزش خانم 👧🏻 [ گارانتی سه ماهه ]",   630000, 50, 57825),
    ("rubika_grp_3m_m", "🧔🏻‍♂️ گروه آقا | ۳ ماهه",        "ممبر گروه روبیکا بدون ریزش آقا 🧔🏻‍♂️ [ گارانتی سه ماهه ]",  630000, 50, 53463),
]
# (کلید، اسم دکمه، نام سفارش، قیمت هر ۱۰۰۰، حداقل، حداکثر، ماه گارانتی)
_RB_CHANNEL_SERVICES = [
    ("rubika_ch_1m",   "💎 کانال | گارانتی ۱ ماهه",       "ممبر کانال روبیکا بدون ریزش [ گارانتی یک ماهه ]",            360000, 50, 111288, 1),
    ("rubika_ch_1m_f", "👧🏻 کانال خانم | ۱ ماهه",         "ممبر کانال روبیکا بدون ریزش خانم 👧🏻 [ گارانتی یک ماهه ]",   390000, 50, 57825, 1),
    ("rubika_ch_1m_m", "🧔🏻‍♂️ کانال آقا | ۱ ماهه",        "ممبر کانال روبیکا بدون ریزش آقا 🧔🏻‍♂️ [ گارانتی یک ماهه ]",  390000, 50, 53463, 1),
    ("rubika_ch_2m",   "💎 کانال | گارانتی ۲ ماهه",       "ممبر کانال روبیکا بدون ریزش [ گارانتی دو ماهه ]",            420000, 50, 111288, 2),
    ("rubika_ch_2m_f", "👧🏻 کانال خانم | ۲ ماهه",         "ممبر کانال روبیکا بدون ریزش خانم 👧🏻 [ گارانتی دو ماهه ]",   450000, 50, 57825, 2),
    ("rubika_ch_2m_m", "🧔🏻‍♂️ کانال آقا | ۲ ماهه",        "ممبر کانال روبیکا بدون ریزش آقا 🧔🏻‍♂️ [ گارانتی دو ماهه ]",  450000, 50, 53463, 12),
    ("rubika_ch_3m",   "💎 کانال | گارانتی ۳ ماهه",       "ممبر کانال روبیکا بدون ریزش [ گارانتی سه ماهه ]",            540000, 50, 111288, 12),
    ("rubika_ch_3m_f", "👧🏻 کانال خانم | ۳ ماهه",         "ممبر کانال روبیکا بدون ریزش خانم 👧🏻 [ گارانتی سه ماهه ]",   540000, 50, 57825, 3),
    ("rubika_ch_3m_m", "🧔🏻‍♂️ کانال آقا | ۳ ماهه",        "ممبر کانال روبیکا بدون ریزش آقا 🧔🏻‍♂️ [ گارانتی سه ماهه ]",  540000, 50, 53463, 3),
]
_RB_CHANNEL_PLAIN = (
    _hdr("ممبر کانال روبیکا", 747000) + "\n\n"
    "🕑 زمان شروع : 0 الی 3 ساعت\n"
    "🚀 سرعت ارسال : 100 الی 200 عدد در هر 24 ساعت\n"
    "🩸 میزان ریزش : 0 الی 50 درصد\n"
    "👌 کیفیت سرویس : ریزش ندارد اما به دلیل واقعی بودن اعضا امکان دارد از کانال خارج شوند\n"
    "✅ زمان تکمیل : 2 تا 4 روز\n"
    "🔗 نمونه لینک : لینک کانال روبیکا ثبت شود")
_RB_CHANNEL_FAST = (
    _hdr("ممبر کانال روبیکا سریع", 1194000) + "\n\n"
    "🕑 زمان شروع : 0 الی 3 ساعت\n"
    "🚀 سرعت ارسال : 100 الی 200 عدد در هر 24 ساعت\n"
    "🩸 میزان ریزش : 0 الی 50 درصد\n"
    "🎁 هدیه : 0 الی 10%\n"
    "👌 کیفیت سرویس : ریزش ندارد اما به دلیل واقعی بودن اعضا امکان دارد از کانال خارج شوند\n"
    "✅ زمان تکمیل : 1 تا 2 روز\n"
    "🔗 نمونه لینک : لینک کانال روبیکا ثبت شود")

# ─ بازدید لایو ─
_RB_LIVE_DESC = (
    _hdr("بازدید لایو روبیکا", 352000) + "\n\n"
    "🕑 زمان شروع : 10 الی 30 دقیقه\n"
    "✅ زمان تکمیل : 1 تا 6 ساعت\n"
    "🚀 سرعت ارسال : 5 کا در هر 24 ساعت\n"
    "👌 کیفیت سرویس : ایرانی\n"
    "🔗 نمونه لینک : لینک لایو روبیکا را وارد کنید\n\n"
    + _RB_LINE + "\n"
    "آموزش کپی لینک لایو روبیکا\n\n"
    "برای ثبت سفارش وارد کانال شده و پخش زنده را آغاز کنید ، به کانال برگشته و کنار پخش زنده ضربه بزنید تا منو باز شود ، "
    "سپس گزینه کپی لینک را انتخاب کنید و وارد سایت شده و در قسمت لینک آن را پیست (جایگذاری) کنید\n\n"
    + _RB_LINE + "\n\n"
    "🌀 نکات مهم:\n\n"
    "📌 در صورتی که پخش زنده تمام شود ، در هنگام ثبت سفارش پخش زنده متوقف شود و... مبلغ سفارش عودت داده نخواهد شد\n\n"
    "📌 زمان ماندن کاربران در لایو تضمینی نیست ، ممکن است لایو را سریع ترک کنند ممکن است تا آخر لایو همراه شما باشند.")

# ─ بازدید استوری ─
def _rb_story_desc(label, price):
    return (_hdr(label, price) + "\n\n"
            "🕑 زمان شروع : 0 الی 3 ساعت\n"
            "✅ زمان تکمیل : 3 تا 12 ساعت\n"
            "🚀 سرعت ارسال : 5 کا در هر 24 ساعت\n"
            "🩸 میزان ریزش : 12 ماه بدون ریزش\n"
            "👌 کیفیت سرویس : ایرانی\n"
            "🔗 نمونه لینک : یوزرنیم پیج را وارد کنید\n\n"
            + _RB_LINE + "\n"
            "🌀 نکات مهم:\n"
            "📌 تا اتمام سفارش، پیج باید عمومی بماند.\n"
            "📌 تا اتمام سفارش، اطلاعات پیج تغییر نکند.\n"
            "📌 تا اتمام سفارش، استوری ها حذف یا ویرایش نشود.")

_RB_STORY_SERVICES = [
    ("rubika_story_f", "✈️ بازدید استوری خانم",  "بازدید استوری خانم 👧🏻 [ 25 استوری آخر ]", 24000, 50, 470772),
    ("rubika_story_m", "✈️ بازدید استوری آقا",   "بازدید استوری آقا 🧔🏻‍♂️ [ 25 استوری آخر ]", 24000, 50, 427874),
    ("rubika_story",   "✈️ بازدید استوری",       "بازدید استوری روبیکا [ 25 استوری آخر ]", 28000, 50, 898645),
]

# ─ روبینو: بازدید / لایک ─
def _rb_rubino_desc(label, price, finish="12 تا 48 ساعت"):
    return (_hdr(label, price) + "\n\n"
            "🕑 زمان شروع : 0 الی 3 ساعت\n\n"
            f"✅ زمان تکمیل : {finish}\n\n"
            "🚀 سرعت ارسال : 5 کا در هر 24 ساعت\n\n"
            "👌 کیفیت سرویس : ایرانی\n\n"
            "🔗 نمونه لینک : لینک پست روبینو را وارد کنید\n\n"
            + _RB_LINE + "\n\n"
            "🌀 نکات مهم:\n\n"
            "📌 تا اتمام سفارش، پیج باید عمومی بماند.\n\n"
            "📌 تا اتمام سفارش، اطلاعات پیج تغییر نکند.")

_RB_RUBINO_LIKE_PLAIN = (
    _hdr("لایک پست روبینو", 15000) + "\n\n"
    "🕑 زمان شروع : 0 الی 3 ساعت\n"
    "🚀 سرعت ارسال : 1 الی 5 کا در هر 24 ساعت\n"
    "🩸 میزان ریزش : 0 الی 20%\n"
    "👌 کیفیت سرویس : کیفیت خوب\n"
    "✅ زمان تکمیل : 24 تا 48 ساعت\n"
    "🔗 نمونه لینک : لینک پست ثبت شود\n\n"
    "🔗مثال: https://rubika.ir/post/AbCfGh")

_RB_RUBINO_SERVICES = [
    ("rubino_view",   "👁 بازدید پست روبینو",        "بازدید پست روبینو",            12000, 50, 898645,
     _rb_rubino_desc("بازدید پست روبینو", 12000), "rubino_post"),
    ("rubino_like_s2", "👍 لایک پست روبینو",         "لایک پست روبینو",              15000, 100, 20000,
     _RB_RUBINO_LIKE_PLAIN, "rubino_post"),
    ("rubino_like",   "❤️ لایک پست روبینو",         "لایک پست روبینو (ایرانی)",     15000, 50, 898645,
     _rb_rubino_desc("لایک پست روبینو (ایرانی)", 15000), "rubino_post"),
    ("rubino_like_m", "🧔🏻‍♂️ لایک پست روبینو آقا",   "لایک پست روبینو آقا 🧔🏻‍♂️",     18000, 50, 427874,
     _rb_rubino_desc("لایک پست روبینو آقا 🧔🏻‍♂️", 18000), "rubino_post"),
    ("rubino_like_f", "👧🏻 لایک پست روبینو خانم",    "لایک پست روبینو خانم 👧🏻",     24000, 50, 470772,
     _rb_rubino_desc("لایک پست روبینو خانم 👧🏻", 24000), "rubino_post"),
]

# ─ روبینو: فالوور ─
def _rb_follower_desc(label, price):
    return (_hdr(label, price) + "\n\n"
            "🕑 زمان شروع : 0 الی 3 ساعت\n"
            "✅ زمان تکمیل : 24 تا 48 ساعت\n"
            "🚀 سرعت ارسال : 5 کا در هر 24 ساعت\n"
            "🩸 میزان ریزش : 12 ماه بدون ریزش\n"
            "👌 کیفیت سرویس : ایرانی\n"
            "🔗 نمونه لینک : یوزرنیم یا لینک پیج را وارد کنید\n\n"
            "https://rubika.ir/page/iran\n\n"
            + _RB_LINE + "\n"
            "🌀 نکات مهم:\n"
            "📌 درحین انجام سفارش، همزمان از ارائه دهنده دیگری سفارش ثبت نکنید.\n"
            "📌 پیج شما حتما باید در حالت عمومی باشد.\n"
            "📌 تا اتمام سفارش، اطلاعات پیج را تغییر ندهید.")

_RB_FOLLOWER_S1 = (
    _hdr("فالوور روبیکا - سرور 1", 294000) + "\n\n"
    "📌این سرویس مخصوص صفحه روبینو میباشد نه کانال روبیکا\n\n"
    "🕑 زمان شروع : 0 الی 3 ساعت\n"
    "🚀 سرعت ارسال : 2 الی 5کا در هر 24 ساعت\n"
    "🩸 میزان ریزش : 0 الی 10%\n"
    "👌 کیفیت سرویس : کاربران نیمه واقعی\n"
    "🔗 نمونه لینک : آیدی بدون علامت @\n\n"
    "نکات مهم :\n"
    "📌پیج عمومی باشد")
_RB_FOLLOWER_FAST = (
    _hdr("فالوور روبیکا - سریع", 588000) + "\n\n"
    "🕑 زمان شروع : 0 الی 3 ساعت\n"
    "🚀 سرعت ارسال : 1 الی 5 کا در هر 24 ساعت\n"
    "🩸 میزان ریزش : 0 الی 30 درصد\n"
    "👌 کیفیت سرویس : واقعی\n"
    "✅ زمان تکمیل : 24 تا 48 ساعت\n"
    "🔗 نمونه لینک : آیدی بدون علامت @")

_RB_FOLLOWER_SERVICES = [
    ("rubino_fol",   "👤 فالوور روبینو بدون ریزش",       "فالوور روبینو بدون ریزش",              80000, 50, 898645,
     _rb_follower_desc("فالوور روبینو بدون ریزش", 80000), "rubino_page"),
    ("rubino_fol_f", "👧🏻 فالوور روبینو خانم",           "فالوور روبینو بدون ریزش خانم 👧🏻",     88000, 50, 470772,
     _rb_follower_desc("فالوور روبینو بدون ریزش خانم 👧🏻", 88000), "rubino_page"),
    ("rubino_fol_m", "🧔🏻‍♂️ فالوور روبینو آقا",          "فالوور روبینو بدون ریزش آقا 🧔🏻‍♂️",    88000, 50, 427874,
     _rb_follower_desc("فالوور روبینو بدون ریزش آقا 🧔🏻‍♂️", 88000), "rubino_page"),
    ("rubika_fol_s1", "🖥 فالوور روبیکا - سرور ۱",       "فالوور روبیکا - سرور 1",               294000, 100, 20000,
     _RB_FOLLOWER_S1, "plain_id"),
    ("rubika_fol_fast", "⚡ فالوور روبیکا - سریع",        "فالوور روبیکا - سریع",                 588000, 100, 20000,
     _RB_FOLLOWER_FAST, "plain_id"),
]


def _cat_helpers(data):
    """ابزارهای ساخت پوشه/سرویس روی کاتالوگ موجود (بدون پاک کردن چیزی)."""
    cat = data.get("catalog") or {}
    nodes = cat.get("nodes")
    if not nodes:          # کاتالوگ عمداً خالی شده
        return None
    settings = data["settings"]

    class H:
        pass
    h = H()

    def find_folder(parent, title):
        return next((n["id"] for n in nodes.values()
                     if n["type"] == "folder" and n["parent"] == parent and n["title"] == title), None)

    def add_folder(parent, title, text):
        cat["counter"] += 1
        fid = str(cat["counter"])
        nodes[fid] = {"id": fid, "parent": parent, "type": "folder", "title": title, "text": text}
        return fid

    def get_folder(parent, title, text):
        return find_folder(parent, title) or add_folder(parent, title, text)

    def add_service(parent, key, title, label, price1000, mn, mx, desc, platform, fixed_price=None, icon=None):
        if key in settings:
            return
        cat["counter"] += 1
        nid = str(cat["counter"])
        nodes[nid] = {"id": nid, "parent": parent, "type": "service", "title": title, "key": key}
        cfg = {"enabled": True, "stock": 999999, "unit": "عدد", "min": mn, "max": mx,
               "price_per_1000": price1000, "platform": platform,
               "label": label, "head": label, "desc": desc}
        if fixed_price:
            cfg["fixed_price"] = fixed_price
            cfg["price_per_1000"] = max(1, round(fixed_price * 1000 / max(1, mn)))
        if icon:
            cfg["icon"] = icon
        settings[key] = cfg

    h.find_folder, h.add_folder, h.get_folder, h.add_service = find_folder, add_folder, get_folder, add_service
    return h


def fix_rubika_12m(data):
    """دو سرویس ممبر کانال روبیکا طبق متن خود صاحب فروشگاه «12 ماه بدون ریزش» می‌مانند."""
    for key, m in (("rubika_ch_2m_m", 2), ("rubika_ch_3m", 3)):
        s = data["settings"].get(key)
        if isinstance(s, dict) and s.get("desc"):
            s["desc"] = s["desc"].replace(f"🩸 میزان ریزش : {m} ماه بدون ریزش", "🩸 میزان ریزش : 12 ماه بدون ریزش")

def fix_rubika_3m_price(data):
    """ممبر کانال روبیکا سه‌ماهه (معمولی): قیمت درست ۵۴۰,۰۰۰ است (فقط اگر هنوز ۳۱۰,۰۰۰ مانده باشد)."""
    s = data["settings"].get("rubika_ch_3m")
    if isinstance(s, dict) and s.get("price_per_1000") == 310000:
        s["price_per_1000"] = 540000
        if s.get("desc"):
            s["desc"] = s["desc"].replace("(تومان 310,000 برای هر ۱۰۰۰)", "(تومان 540,000 برای هر ۱۰۰۰)")

def add_rubika(data):
    """
    اپلیکیشن «🟡 روبیکا» را با همه‌ی بخش‌هایش اضافه می‌کند.
    چیزی را پاک یا جایگزین نمی‌کند؛ پوشه یا سرویسی که از قبل باشد دوباره ساخته نمی‌شود.
    """
    h = _cat_helpers(data)
    if h is None:
        return
    rb = find_app_folder(data, RUBIKA_TITLE) or h.add_folder("root", RUBIKA_TITLE, "بخش مورد نظر رو انتخاب کن 👇🟡")

    # ❤️ ری‌اکشن
    f = h.get_folder(rb, "❤️ ری‌اکشن پست کانال", "ری‌اکشن مورد نظر رو انتخاب کن 👇❤️")
    for key, emoji, name, label, fast in _RB_RX_SINGLES:
        desc = _rb_rx_fast_desc(label, 36000) if fast else _rb_rx_desc(label, 36000)
        h.add_service(f, key, f"{emoji} ری‌اکشن {name}", label, 36000, 25, 50000, desc, "rubika_post")
    for key, title, label in _RB_RX_GROUPS:
        h.add_service(f, key, title, label, 36000, 10, 111288, _rb_rx_desc(label, 36000), "rubika_post")

    # 📊 نظرسنجی
    f = h.get_folder(rb, "📊 نظرسنجی", "گزینه‌ی نظرسنجی رو انتخاب کن 👇📊")
    for i in range(1, 7):
        label = f"افزایش رای نظرسنجی [ برای گزینه {i} ]"
        h.add_service(f, f"rubika_poll_{i}", f"📊 رای نظرسنجی | گزینه {i}", label, 60000, 10, 111288,
                      _rb_poll_desc(label, 60000), "rubika_post")

    # 📡 بازدید لایو (فقط ۱ سرویس، مستقیم زیر روبیکا)
    h.add_service(rb, "rubika_live", "📡 بازدید لایو روبیکا", "بازدید لایو روبیکا", 352000, 25, 10000,
                  _RB_LIVE_DESC, "rubika_any")

    # 📖 بازدید استوری
    f = h.get_folder(rb, "📖 بازدید استوری", "سرویس مورد نظر رو انتخاب کن 👇📖")
    for key, title, label, price, mn, mx in _RB_STORY_SERVICES:
        h.add_service(f, key, title, label, price, mn, mx, _rb_story_desc(label, price), "rubino_page")

    # 📸 بازدید/لایک/کامنت روبینو
    f = h.get_folder(rb, "📸 بازدید/لایک/کامنت روبینو", "سرویس مورد نظر رو انتخاب کن 👇📸")
    for key, title, label, price, mn, mx, desc, platform in _RB_RUBINO_SERVICES:
        h.add_service(f, key, title, label, price, mn, mx, desc, platform)

    # 👤 فالوور روبیکا (روبینو)
    f = h.get_folder(rb, "👤 فالوور روبیکا (روبینو)", "سرویس مورد نظر رو انتخاب کن 👇👤")
    for key, title, label, price, mn, mx, desc, platform in _RB_FOLLOWER_SERVICES:
        h.add_service(f, key, title, label, price, mn, mx, desc, platform)

    # 👥 ممبر گروه
    f = h.get_folder(rb, "👥 ممبر گروه روبیکا", "سرویس مورد نظر رو انتخاب کن 👇👥")
    for key, title, label, price, mn, mx in _RB_GROUP_SERVICES:
        h.add_service(f, key, title, label, price, mn, mx, _rb_group_desc(label, price), "rubika_chat")

    # 💎 ممبر کانال
    f = h.get_folder(rb, "💎 ممبر کانال روبیکا", "سرویس مورد نظر رو انتخاب کن 👇💎")
    for key, title, label, price, mn, mx, months in _RB_CHANNEL_SERVICES:
        h.add_service(f, key, title, label, price, mn, mx, _rb_channel_desc(label, price, months), "rubika_chat")
    h.add_service(f, "rubika_ch_plain", "👑 ممبر کانال روبیکا", "ممبر کانال روبیکا", 747000, 100, 20000,
                  _RB_CHANNEL_PLAIN, "rubika_chat")
    h.add_service(f, "rubika_ch_fast", "🚀 ممبر کانال روبیکا سریع", "ممبر کانال روبیکا سریع", 1194000, 100, 20000,
                  _RB_CHANNEL_FAST, "rubika_chat")


# ══════════════════════════════════════════
#  اینستاگرام  (قیمت‌ها دو برابر ثبت شده؛ فقط «فالوور خارجی» همان قیمت اصلی است)
# ══════════════════════════════════════════
_IG_N_SIMUL = "📌 سفارش همزمان برای یک لینک از یک سرویس ثبت نکنید."
_IG_N_PUB   = "📌 پیج عمومی باشد."
_IG_N_SLIDE = "📌 برای پست اسلایدی سفارش ثبت نکنید."
_IG_N_LIMIT = "📌 در زمان محدودیت های اینستاگرام امکان افت سرعت وجود دارد."
_IG_N_NOSUP = "📌 سرویس بدون پشتیبانی (به دلیل ارزان بودن )."
_IG_N_SIMUL_LONG = "📌سفارش همزمان برای یک لینک از یک سرویس ثبت نکنید تا سفارش قبلی شما برای همان لینک تکمیل شود."
_IG_STATS_NOTE = ("امار تنها برای صاحب پیج در دسترس است و این امار برای ما قابل مشاهده نیست به همین علت تعداد ارسالی ها "
                  "از سمت ما قابل بررسی نیستند و در صورتی که سفارش ناقص انجام شود پیگیری و پشتیبانی ندارد.")


def _ig(key, title, label, price, mn, mx, body, platform, x=2, comments=False, fixed=False, icon=None):
    """یک سرویس اینستاگرام؛ x = ضریب قیمت (پیش‌فرض ۲ برابر)."""
    final = price * x
    desc = body if fixed else (_hdr(label, final) + "\n\n" + body)
    return dict(key=key, title=title, label=label, price=final, mn=mn, mx=mx, desc=desc, platform=platform,
                comments=comments, fixed=fixed, icon=icon)


def _L(*lines):
    return "\n".join(lines)


# ─ ویو ریلز + ویدئو ─
def _ig_view_a():
    return _L("🕑 زمان شروع : 0 تا 3 ساعت", "✅ زمان تکمیل : 24 تا 48 ساعت", "🩸 میزان ریزش : ندارد",
              "👌 کیفیت سرویس : خارجی", "🔗 نمونه لینک : https://www.instagram.com/reel/xyz", "",
              "نکات مهم :", _IG_N_NOSUP, _IG_N_SLIDE, _IG_N_SIMUL, _IG_N_PUB, _IG_N_LIMIT)

def _ig_view_cheap(start):
    return _L(f"⌛ زمان شروع : {start}", "🚀 سرعت ارسال : 1 الی 100کا در 24 ساعت", "🩸 میزان ریزش : ندارد",
              "🎁 هدیه : 0 الی 10%", "👌 کیفیت سرویس : خوب",
              "🔗 نمونه لینک : https://www.instagram.com/reel/xyz", "🔍 نوع پست : Video و Reels", "",
              "نکات مهم :", "📌برای پست اسلایدی سفارش ثبت نکنید.", "📌پیج عمومی باشد.")

def _ig_view_server():
    return _L("🕑 زمان شروع : 0 تا 3 ساعت", "🚀 سرعت ارسال : 1 الی 50 کا در 24 ساعت", "🩸 میزان ریزش : ندارد",
              "👌 کیفیت سرویس : بالا", "✅ زمان تکمیل : 24 تا 48 ساعت",
              "🔗 نمونه لینک : https://www.instagram.com/reel/C1mPNJW", "",
              "نکات مهم :", _IG_N_SLIDE, _IG_N_SIMUL, _IG_N_PUB)

IG_VIEWS = [
    _ig("ig_view_1", "⚡ ویو ریلز", "ویو ریلز اینستاگرام⚡", 500, 100, 50000000, _ig_view_a(), "insta_post"),
    _ig("ig_view_2", "🚀 ویو ریلز | ظرفیت بالا", "ویو ریلز اینستاگرام⚡ظرفیت بالا", 500, 100, 2147483647, _ig_view_a(), "insta_post"),
    _ig("ig_view_3", "💸 ویو اینستاگرام ارزان", "ویو اینستاگرام ارزان", 1300, 100, 100000000, _ig_view_cheap("0 الی 3 ساعت"), "insta_post"),
    _ig("ig_view_4", "🪙 بازدید فوق ارزان", "بازدید فوق ارزان اینستاگرام", 2100, 100, 100000000, _ig_view_cheap("1 الی 3 ساعت"), "insta_post"),
    _ig("ig_view_5", "🥈 ویو ریلز | سرور ۲", "ویو ریلز اینستاگرام - سرور 2", 6800, 100, 100000000, _ig_view_server(), "insta_post"),
    _ig("ig_view_6", "🥇 ویو ریلز | سرور ۵", "ویو ریلز اینستاگرام - سرور 5⚡️", 8500, 100, 100000000, _ig_view_server(), "insta_post"),
    _ig("ig_view_7", "🔥 ویو اورژانسی | جدید", "ویو اورژانسی اینستاگرام - جدید 🔥", 17800, 100, 15000000,
        _L("🕑 زمان شروع : 0 تا 2ساعت", "🚀 سرعت ارسال : 1 الی 10 کا در 24 ساعت", "🩸 میزان ریزش : ندارد",
           "👌 کیفیت سرویس : با کیفیت و عالی", "✅ زمان تکمیل : 24 تا 48 ساعت",
           "🔗 نمونه لینک : لینک پست ثبت شود", "🔗 مثال: https://www.instagram.com/p/xxxx/"), "insta_post"),
    _ig("ig_view_8", "⭐ ویو | سرور ۴", "ویو اینستاگرام - سرور 4⭐", 52000, 100, 100000000, _ig_view_server(), "insta_post"),
    _ig("ig_view_9", "💎 ویو ریلز + ایمپرشن", "ویو ریلز + ایمپرشن اینستاگرام", 757900, 100, 2147483647,
        _L("شروع آنی", "لینک پست را وارد کنید", "https://www.instagram.com/REEL/B910VxfgEIO"), "insta_post"),
]

# ─ اکسپلور ─
def _ig_explore_desc(audience, n, views, tier, link_block):
    return _L(f"مناسب برای پیج هایی که از {audience} فالوور دارند.", "",
              "🕑 زمان شروع : 2 تا 3 ساعت", "",
              "✅ زمان تکمیل : 24 تا 48 ساعت", "",
              link_block, "",
              f"📦 محتویات بسته اکسپلور {tier} :", "",
              f"💎 {n} عدد لایک پست", f"💎 {views} عدد بازدید ریلز", f"💎 {n} عدد سیو (Save) پست",
              f"💎 {n} عدد شیر (Share) پست", f"💎 {n} عدد پروفایل ویزیت", f"💎 {n} عدد ریچ و ایمپریشن")

_IG_EXP_LINK = "🔗 فرمت لینک : لینک ریلز اینستاگرام وارد کنید.\n\nhttps://www.instagram.com/reel/Dc62xRSAEeF"

IG_EXPLORE = [
    _ig("ig_exp_100", "🥉 بسته ۱۰۰ تایی اکسپلور", "بسته ۱۰۰ تایی اکسپلور", 147000, 1, 1,
        _ig_explore_desc("1 عدد تا 5 کا", 100, 100, "برنزی", _IG_EXP_LINK), "insta_post", fixed=True, icon="🧭"),
    _ig("ig_exp_bronze", "🥉 اکسپلور برنزی", "پکیج ورود به اکسپلور برنزی", 213000, 1, 1,
        _ig_explore_desc("1 عدد تا 5 کا", 200, 1000, "برنزی", "🔗 فرمت لینک : https://www.instagram.com/reel/xyz"),
        "insta_post", fixed=True, icon="🧭"),
    _ig("ig_exp_silver", "🥈 اکسپلور نقره‌ای", "پکیج ورود به اکسپلور نقره ای", 367500, 1, 1,
        _ig_explore_desc("5 عدد تا 10 کا", 500, 2000, "نقره ای", _IG_EXP_LINK), "insta_post", fixed=True, icon="🧭"),
    _ig("ig_exp_gold", "🥇 اکسپلور طلایی", "پکیج ورود به اکسپلور طلایی", 495000, 1, 1,
        _ig_explore_desc("5 عدد تا 10 کا", 1000, 5000, "طلایی", _IG_EXP_LINK), "insta_post", fixed=True, icon="🧭"),
    _ig("ig_exp_diamond", "💎 اکسپلور الماسی", "پکیج ورود به اکسپلور الماسی", 727500, 1, 1,
        _ig_explore_desc("30 کا تا 100 کا", 2000, 10000, "الماسی", _IG_EXP_LINK), "insta_post", fixed=True, icon="🧭"),
    _ig("ig_exp_plus", "🚀 اکسپلور پلاس", "پکیج اکسپلور پلاس", 1297500, 1, 1,
        _ig_explore_desc("50 کا تا 200 کا", 3000, 15000, "پلاس", _IG_EXP_LINK), "insta_post", fixed=True, icon="🧭"),
    _ig("ig_exp_vip", "👑 اکسپلور VIP", "پکیج ورود به اکسپلور vip", 1350000, 100, 5000,
        _L("🕑 زمان شروع : 2 تا 3 ساعت", "✅ زمان تکمیل : 24 تا 48 ساعت",
           "🔗 نمونه لینک : https://www.instagram.com/reel/xyz", "",
           "📦 محتویات بسته اکسپلور vip :", "",
           "افزایش تعامل واقعی (لایک، کامنت، ویو، ریچ و ایمپرشن، سیو پست، ارسال به دایرکت)", "",
           "تعداد انتخابی شما در بین تمام موارد بالا تقسیم میشود"), "insta_post"),
]

# ─ سیو / شیر / ایمپرشن / بازدید پروفایل ─
def _ig_share_desc(gift=False):
    lines = ["🕑 زمان شروع : 0 تا 3 ساعت", "🚀 سرعت ارسال : 1 تا 3 کا در 24 ساعت", "🩸 میزان ریزش : 0 تا 10 درصد"]
    if gift:
        lines.append("🎁 هدیه : 0 تا 10 درصد")
    lines += ["👌 کیفیت سرویس : مناسب", "✅ زمان تکمیل : 24 تا 48 ساعت",
              "🔗 نمونه لینک : https://www.instagram.com/reel/xyz", "🔍 نوع پست : reels", "",
              "نکات مهم :", "", _IG_N_SIMUL_LONG, "📌 پیج عمومی و بیزینس باشد.",
              "📌 در صورت ریزش بیشتر، جبران ریزش ندارد.",
              "📌 تعداد شیر تنها برای صاحب پیج در دسترس است و این امار برای ما قابل مشاهده نیست به همین علت تعداد "
              "ارسالی ها از سمت ما قابل بررسی نیستند و در صورتی که سفارش ناقص انجام شود پیگیری و پشتیبانی ندارد."]
    return _L(*lines)

_IG_IMP_SIMUL = "سفارش همزمان برای یک لینک از یک سرویس ثبت نکنید تا سفارش قبلی شما برای همان لینک تکمیل شود."

def _ig_imp_fast_desc():
    return _L("🕑 زمان شروع : 0 تا 5 ساعت", "🚀 سرعت ارسال : بالا", "🩸 میزان ریزش : کم", "👌 کیفیت سرویس : واقعی",
              "✅ زمان تکمیل : 24 تا 48 ساعت", "🔗 نمونه لینک : https://www.instagram.com/p/xyz",
              "🔍 نوع پست : IGTV- video-photo", "",
              "نکات مهم :", "", _IG_IMP_SIMUL,
              "در صورت لینک گذاری اشتباه سفارش تکمیل شده و هزینه برگشت داده نمی شود.",
              "پیج عمومی باشد.", "پیج حتما بیزینسی باشد.", "در صورت ریزش بیشتر، جبران ریزش ندارد.", "",
              "⚠️ آمار تنها برای صاحب پیج در دسترس است و این امار برای ما قابل مشاهده نیست به همین علت تعداد "
              "ارسالی ها از سمت ما قابل بررسی نیستند و در صورتی که سفارش ناقص انجام شود پیگیری و پشتیبانی ندارد.")

def _ig_imp_desc():
    return _L("⛔ برای پست های ریلز سفارش ثبت نکنید ⛔", "",
              "🕑 زمان شروع : 0 تا 1 ساعت", "🚀 سرعت ارسال : بالا", "🩸 میزان ریزش : کم", "👌 کیفیت سرویس : عالی",
              "✅ زمان تکمیل : 24 تا 48 ساعت", "🔗 نمونه لینک : https://www.instagram.com/p/xyz",
              "🔍 نوع پست : IGTV- video-photo", "",
              "نکات مهم :", "",
              "برای پست های ریلز سفارش ثبت نکنید. در صورت لینک گذاری اشتباه وضعیت سفارش به تکمیل شده تغییر کرده و "
              "هزینه برگشت داده نمی شود.",
              _IG_IMP_SIMUL, "پیج عمومی باشد.", "پیج بیزینسی باشد.", _IG_STATS_NOTE,
              "در صورت ریزش بیشتر، جبران ریزش ندارد.")

IG_SAVE_SHARE = [
    _ig("ig_share_1", "📤 شیر اینستاگرام", "شیر اینستاگرام", 6000, 10, 1000000, _ig_share_desc(), "insta_post"),
    _ig("ig_imp_fast", "⚡ ایمپرشن سریع", "ایمپرشن اینستاگرام - سریع ⚡️💧⭐🔥", 17000, 100, 5000000,
        _ig_imp_fast_desc(), "insta_post"),
    _ig("ig_imp_reach", "📈 ایمپرشن + ریچ", "ایمپرشن + ریچ ⚡💧⭐🔥", 17000, 10, 100000, _ig_imp_desc(), "insta_post"),
    _ig("ig_imp_home", "🏠 ایمپرشن از پروفایل/خانه/هشتگ", "ایمپرشن اینستاگرام از {پروفایل+خانه+هشتگ و سایر} ⚡💧⭐🔥",
        17000, 10, 500000, _ig_imp_desc(), "insta_post"),
    _ig("ig_save_1", "💾 سیو اینستاگرام", "سیو اینستاگرام ⚡💧", 17800, 10, 50000,
        _L("🕑 زمان شروع : 0 تا 24 ساعت", "🚀 سرعت ارسال : 1 الی 5 کا در 24 ساعت", "🩸 میزان ریزش : کم",
           "👌 کیفیت سرویس : بالا", "✅ زمان تکمیل : 1 الی 4 روز",
           "🔗 نمونه لینک : https://www.instagram.com/p/xyz", "🔍 نوع پست : IGTV- video-reels-photo", "",
           "نکات مهم :", "", _IG_N_SIMUL_LONG, "📌 پیج عمومی باشد.", "📌 پیج حتما بیزینسی باشد.",
           "📌 در صورت ریزش بیشتر، جبران ریزش ندارد.",
           "📌 تعدادسیو تنها برای صاحب پیج در دسترس است و این امار برای ما قابل مشاهده نیست به همین علت تعداد "
           "ارسالی ها از سمت ما قابل بررسی نیستند و در صورتی که سفارش ناقص انجام شود پیگیری و پشتیبانی ندارد."),
        "insta_post"),
    _ig("ig_imp_explore", "🧭 ایمپرشن از اکسپلور/خانه/پروفایل", "ایمپرشن اینستاگرام از [اکسپلور+ خانه+ پروفایل] ⚡️💧⭐🔥",
        19900, 100, 1000000, _ig_imp_desc(), "insta_post"),
    _ig("ig_share_2", "📤 شیر اینستا | سرور ۲", "شیر اینستا - سرور 2", 79700, 100, 10000000,
        _ig_share_desc(gift=True), "insta_post"),
    _ig("ig_share_ir", "🇮🇷 شیر پست | ایرانی", "شیر پست اینستاگرام | ایرانی", 300000, 100, 5000,
        _L("🕑 زمان شروع : 1 تا 5 ساعت", "🩸 میزان ریزش : ندارد", "👌 کیفیت سرویس : ایرانی",
           "✅ زمان تکمیل : 24 تا 48 ساعت", "🔗 نمونه لینک : https://www.instagram.com/reel/xyz", "",
           "نکات مهم :", "",
           "📌 تعداد شیر تنها برای صاحب پیج در دسترس است و این امار برای ما قابل مشاهده نیست به همین علت در صورتی که "
           "سفارش ناقص انجام شود پیگیری و پشتیبانی ندارد."), "insta_post"),
    _ig("ig_save_ir", "🇮🇷 سیو پست | ایرانی", "سیو پست اینستاگرام | ایرانی", 900000, 300, 5000,
        _L("🕑 زمان شروع : 1 تا 5 ساعت", "🩸 میزان ریزش : ندارد", "👌 کیفیت سرویس : ایرانی",
           "✅ زمان تکمیل : 24 تا 48 ساعت", "🔗 نمونه لینک : https://www.instagram.com/reel/xyz"), "insta_post"),
]

# ─ ریپست ─
def _ig_repost_desc(start, drop, quality):
    return _L(f"⌛ زمان شروع : {start}", f"🩸 میزان ریزش : {drop}", f"👌 کیفیت سرویس : {quality}",
              "🔗 نمونه لینک : https://www.instagram.com/reel/xyz", "🔍 نوع پست : Video و Reels", "",
              "نکات مهم :", "📌پیج عمومی باشد.", "📌جبران ریزش: ندارد")

IG_REPOST = [
    _ig("ig_repost_intl", "🌍 ریپست بین‌المللی | همه کشورها", "ریپست بین المللی از تمام کشور ها", 113400, 100, 100000,
        _ig_repost_desc("2 الی 6 ساعت", "نامشخص", "خارجی"), "insta_post"),
    _ig("ig_repost_2", "🔁 ریپست | سرور ۲", "ریپست اینستاگرام - سرور 2", 146500, 10, 217545811,
        _ig_repost_desc("2 الی 4 ساعت", "فعلا ندارد", "خارجی"), "insta_post"),
    _ig("ig_repost_rec", "⭐ ریپست | پیشنهادی", "ریپست اینستاگرام (پیشنهادی)", 187300, 10, 2147483647,
        _ig_repost_desc("2 الی 6 ساعت", "فعلا ندارد", "خارجی"), "insta_post"),
    _ig("ig_repost_ir", "🇮🇷 ری‌پست ایرانی", "ری پست ایرانی", 420000, 100, 5000,
        _ig_repost_desc("2 الی 12 ساعت", "ندارد", "ایرانی"), "insta_post"),
]

# ─ فالوور ایرانی ─
_IG_FLAG = ("📌لطفا گزینه پرچم گذاری یا flagged را حتما خاموش کنید در غیر اینصورت اگر فالور کمتری دریافت کنید "
            "امکان پشتیبانی و پیگیری ندارد.")
_IG_PAGE_PUB = "🔰 پیج حتما باید عمومی باشد"

IG_FOLLOWER_IR = [
    _ig("ig_fol_ir90", "🇮🇷 فالوور ۹۰٪ ایرانی", "فالوور 90 درصد ایرانی", 267300, 100, 10000,
        _L("🕑 زمان تکمیل : 24 الی 72 ساعت", "🚀 سرعت ارسال: 100 الی 1 کا",
           "🩸 میزان ریزش: 10 تا 60 درصد ( زمان محدودیت ها  بیشتر)", "👌 کیفیت سرویس:  ایرانی",
           "🔗 نمونه لینک : ایدی پیج اینستاگرام را وارد کنید", "",
           "نکات مهم :", "", _IG_FLAG, "📌پیج عمومی باشد.", "📌جبران ریزش ندارد"), "insta_user"),
    _ig("ig_fol_ir30d", "🛡 فالوور ایرانی | ۳۰ روز جبران ریزش", "فالوور ایرانی 30 روز جبران ریزش", 523500, 100, 10000,
        _L("⚠️ برای دریافت فالوور حتما فلگ را خاموش کنید", "در غیراینصورت 30% فالور کمتری دریافت می کنید", "",
           "1. به تنظیمات حساب خود بروید.", "2. Follow and Invite Friends را انتخاب کنید.",
           "3. گزینه Flag for Review را پیدا کرده و تیک آن را بردارید.", "",
           "⏳ زمان تکمیل : 24 الی 72 ساعت", "", "👦 کیفیت پروفایل ها : ایرانی", "",
           "🚀 سرعت ارسال روزانه : 2000 عدد", "", "⛔ ریزش : 30 تا 40 درصد (در زمان محدودیتها  بیشتر)", "",
           "🔗 فرمت لینک : یوزرنیم (نام کاربری) پیج را بدون علامت @ ثبت کنید. مثال:", "", "example", "",
           "نکات مهم :", "",
           "📌 پیج حتما باید عمومی و ایدی پیج صحیح باشد.", "📌 فالوور ها فیک و غیرفعال هستند.",
           "📌در صورت ریزش بیشتر ، جبران ریزش ندارد."), "insta_user"),
    _ig("ig_fol_ir_vip1", "💎 فالوور ایرانی | اختصاصی", "فالوور ایرانی - اختصاصی", 555000, 100, 5000,
        _L("⏳ زمان استارت سرویس : 1 الی 2 ساعت", "🛒 ظرفیت ثبت : 1 کا برای هر پیج",
           "👦 کیفیت پروفایل ها : 100 درصد ایرانی", "🚀 سرعت ارسال روزانه : 300 الی 1000 عدد",
           "⛔ ریزش : دارد، میزان ریزش بستگی به پیج دارد", "⛔ جبران ریزش: ندارد",
           "🔗 نحوه درج لینک : فقط آیدی پیج", "", _IG_PAGE_PUB,
           "🔰ابتدا در تعداد پایین تست کنید در صورت رضایت حجم سفارش را افزایش دهید"), "insta_user"),
    _ig("ig_fol_ir100", "🇮🇷 فالوور ۱۰۰٪ ایرانی", "فالوور ۱۰۰ درصد ایرانی", 560000, 100, 30000,
        _L("⏳ زمان تکمیل: 12 الی 72 ساعت", "", "🛒 ظرفیت ثبت : 30 کا برای هر پیج", "",
           "👦 کیفیت پروفایل ها : ایرانی", "", "🚀 سرعت ارسال روزانه : 5000 عدد", "",
           "⛔ ریزش : 20 الی 30 درصد ( سی روز جبرانی دارد برای ارسال جبرانی تیکت ارسال نمایید)", "",
           "🔗 فرمت لینک : یوزرنیم (نام کاربری) پیج را بدون علامت @ ثبت کنید. مثال:", "", "example", "",
           "نکات مهم :", "",
           "📌 پیج حتما باید عمومی و ایدی پیج صحیح باشد.", "📌 فالوور ها فیک و غیرفعال هستند.",
           "📌در زمان محدودیت ها، سرعت کاهش و ریزش افزایش خواهد داشت."), "insta_user"),
    _ig("ig_fol_ir_gold", "⭐ فالوور ایرانی | سرور طلایی", "فالوور ایرانی | سرورطلایی⭐", 623700, 10, 20000,
        _L("🕑 زمان تکمیل: 24 الی 72 ساعت", "", "🚀 سرعت ارسال: 500 تا 5 کا روزانه", "",
           "🩸 میزان ریزش : 30 تا 40 درصد (در زمان محدودیتها  بیشتر)", "", "👌 کیفیت سرویس : ایرانی", "",
           "🔗 نمونه لینک : username", "", "نکات مهم :", "",
           "📌لطفا گزینه پرچم گذاری یا flagged را حتما و حتما خاموش کنید در غیر اینصورت اگر فالور کمتری دریافت کنید "
           "امکان پشتیبانی و پیگیری ندارد.", "", "📌پیج عمومی باشد.", "📌جبران ریزش ندارد"), "insta_user"),
    _ig("ig_fol_ir_vip2", "👑 فالوور ایرانی | سرور VIP", "فالوور ایرانی سرور Vip [100% ایرانی]", 9450000, 50, 2000,
        _L("⏳ زمان استارت سرویس : 1 الی 2 ساعت", "🛒 ظرفیت ثبت : 1 کا برای هر پیج",
           "👦 کیفیت پروفایل ها : 100 درصد ایرانی", "🚀 سرعت ارسال روزانه : 300 الی 1000 عدد",
           "⛔ ریزش : دارد، میزان ریزش بستگی به پیج دارد", "⛔ جبران ریزش: ندارد",
           "🔗 نحوه درج لینک : فقط آیدی پیج", "", _IG_PAGE_PUB,
           "🔰ابتدا در تعداد پایین تست کنید در صورت رضایت حجم سفارش را افزایش دهید"), "insta_user"),
]

# ─ لایک ایرانی ─
def _ig_like_ir_desc(start, drop, quality, speed=True):
    lines = [f"🕑 زمان شروع : {start}", f"🩸 میزان ریزش : {drop}", f"👌 کیفیت سرویس : {quality}"]
    if speed:
        lines.append("✅ سرعت : 2 تا 5 کا روزانه")
    lines += ["🔗 نمونه لینک : لینک پست را وارد کنید", "", "نکات مهم :", "📌پیج عمومی باشد.", "📌جبران ریزش ندارد"]
    return _L(*lines)

IG_LIKE_IR = [
    _ig("ig_like_ir80", "🌟 لایک ۸۰٪ ایرانی", "لایک ۸۰ درصد ایرانی", 37200, 100, 15000,
        _ig_like_ir_desc("1 الی 2 ساعت", "10 الی 30 درصد", "لایک ۸۰ درصد ایرانی"), "insta_post"),
    _ig("ig_like_ir70", "✨ لایک ۷۰٪ ایرانی", "لایک 70 درصد ایرانی", 111400, 100, 3000,
        _ig_like_ir_desc("1 الی 2 ساعت", "5 الی 10 درصد", "لایک 7۰ درصد ایرانی"), "insta_post"),
    _ig("ig_like_ir100", "💎 لایک ۱۰۰٪ ایرانی", "لایک 100 درصد ایرانی 💎", 140000, 10, 20000,
        _ig_like_ir_desc("1 الی 2 ساعت", "30 روز بدون ریزش", "ایرانی", speed=False), "insta_post"),
    _ig("ig_like_iran_arab", "🌙 لایک ایرانی - عربی", "لایک ایرانی - عربی", 350200, 100, 100000,
        _L("شروع بین 1 تا 3 ساعت", "ریزش نامشخص و جبران ریزش ندارد", "با مقدار کم تست کنید", "لینک پست را وارد کنید"),
        "insta_post"),
    _ig("ig_like_explore", "🧭 لایک ایرانی ویژه اکسپلور", "لایک ایرانی ویژه اکسپلور", 450000, 100, 5000,
        _L("🕑 زمان شروع : 2 الی 5 ساعت", "🕑 زمان تکمیل : 12 الی 24 ساعت", "🩸 میزان ریزش : بین 10 تا 20 درصد",
           "👌 کیفیت سرویس : ایرانی", "🔗 نمونه لینک : لینک پست را وارد کنید", "", "نکات مهم :", "📌پیج عمومی باشد."),
        "insta_post"),
    _ig("ig_like_vip", "👑 لایک ایرانی سرور VIP", "لایک ایرانی سرور Vip [100% ایرانی]", 2700000, 30, 200000,
        _L("لایک توسط کاربران ایرانی، کیفیت بالا", "لایک برای هر نوع پست ، ریل و ویدیو igtv", "",
           "⏳ زمان استارت سرویس : 2 الی 12 ساعت", "🛒 ظرفیت ثبت : 2 کا برای هر پست",
           "👦 کیفیت پروفایل ها : 100 درصد ایرانی", "🚀 سرعت ارسال روزانه : 100 الی 500 عدد", "⛔ ریزش : کم",
           "🔗 نحوه درج لینک : لینک پست درج گردد", "", _IG_PAGE_PUB), "insta_post"),
]

# ─ لایک خارجی ─
IG_LIKE_F = [
    _ig("ig_like_f_cheap", "💸 لایک خارجی | ارزان", "لایک خارجی - ارزان", 12200, 10, 1000000,
        _L("⏰ استارت: 2 الی 20 دقیقه", "💎کیفیت سرویس: خارجی پروفایلدار و بدون پروفایل", "💧ریزش: 5 الی 20 درصد",
           "〰️〰️〰️〰️〰️〰️〰️〰️", "⚠️ نکات مهم:", "🔸پیج عمومی باشد.", "🔸لینک پست رو وارد کنید."), "insta_post"),
    _ig("ig_like_f", "🌍 لایک خارجی", "لایک خارجی", 18900, 10, 250000,
        _L("🕑 زمان شروع : 0 تا 3 ساعت", "🚀 سرعت ارسال : 1 الی 3 کا در 24 ساعت", "🩸 میزان ریزش : ندارد",
           "👌 کیفیت سرویس : خارجی", "🔗 نمونه لینک : لینک پست اینستاگرام را وارد کنید", "",
           "نکات مهم :", "📌 پیج عمومی باشد."), "insta_post"),
    _ig("ig_like_f_q", "🛡 لایک خارجی | کیفیت و ریزش کم", "لایک خارجی با کیفیت و ریزش کم", 92000, 10, 500000,
        _L("لایک خارجی با کیفیت بالا", "ریزش بین 10 تا 15%", "شروع بین 12 تا 24 ساعت", "با مقدار کم تست کنید",
           "لینک پست را وارد کنید"), "insta_post"),
    _ig("ig_like_f2", "🌐 لایک خارجی | سرور ۲", "لایک خارجی (سرور 2)", 233500, 10, 5000000,
        _L("🕑 زمان شروع : 5 تا 12 ساعت", "🚀 سرعت ارسال : 1 الی 3 کا در 24 ساعت", "🩸 میزان ریزش : 10 الی 30%",
           "🎁 هدیه : 0 الی 5%", "👌 کیفیت سرویس : خارجی", "🔗 نمونه لینک : https://www.instagram.com/reel/xyz", "",
           "نکات مهم :", "📌 پیج عمومی باشد.", "📌 در صورت ریزش بیشتر، جبران ریزش ندارد."), "insta_post"),
    _ig("ig_like_f_hq", "🏅 لایک خارجی با کیفیت بالا", "لایک خارجی با کیفیت بالا", 268400, 10, 30000,
        _L("شروع سفارش بین 2 تا 5 ساعت", "سرعت ارسال متوسط", "کیفت لایک ها مناسب", "ریزش کم می باشد",
           "با مقدار کم تست کنید"), "insta_post"),
]

# ─ استوری ─
def _ig_story_view_desc(start, complete, speed=None, note_extra=None):
    lines = [f"🕑 زمان شروع : {start}", f"✅ زمان تکمیل : {complete}"]
    if speed:
        lines.append(f"🚀 سرعت ارسال : {speed}")
    lines += ["🩸 میزان ریزش : ندارد", "👌 کیفیت سرویس : خارجی (عالی)", "🔗 نمونه لینک : username", "",
              "نکات مهم :", "📌 ابتدا استوری گذاشته و سپس سفارش خود را ثبت کنید.",
              "📌 به تمام استوری ها ویو زده می شود.", "📌 پیج عمومی باشد."]
    return _L(*lines)

IG_STORY = [
    _ig("ig_story_view", "⭐ بازدید استوری", "بازدید استوری ⭐", 33700, 10, 15000,
        _ig_story_view_desc("1 الی 2 ساعت (اغلب آنی)", "12 ساعت"), "insta_user"),
    _ig("ig_story_s3", "⚡ ویو همه استوری‌ها | سرور ۳", "ویو همه استوری ها- سرور 3⚡️⭐", 35400, 10, 10000,
        _ig_story_view_desc("1 الی 3 ساعت (اغلب آنی)", "24 ساعت", "5 الی 20کا در 24 ساعت"), "insta_user"),
    _ig("ig_story_vote_yes", "✅ نظرسنجی استوری | گزینه بله", "نظرسنجی استوری - گزینه بله", 57500, 100, 100000,
        _L("شروع بین 2 تا 5 ساعت", "لینک را طبق الگوی زیر وارد کنید",
           "https://instagram.com/stories/username/2775373807903362640?vote=yes"), "insta_story_link"),
    _ig("ig_story_s2", "⚡ ویو همه استوری‌ها | سرور ۲", "ویو همه استوری ها- سرور 2⚡️⭐", 38200, 10, 10000,
        _ig_story_view_desc("1 الی 3 ساعت (اغلب آنی)", "24 ساعت", "5 الی 20کا در 24 ساعت"), "insta_user"),
    _ig("ig_story_like", "❤️ لایک استوری", "لایک استوری", 79600, 100, 100000,
        _L("لایک فقط برای استوری", "ایدی پیج را وارد کنید", "لطفا با کمترین مقدار تست کنید",
           "به دلیل غیرقابل چک کردن پشتیبانی ندارد"), "insta_user"),
    _ig("ig_story_reach", "📊 ویو استوری + Reach + Impressions", "ویو استوری + Reach+Impressions", 84900, 10, 15000,
        _ig_story_view_desc("1 الی 3 ساعت (اغلب آنی)", "24 ساعت", "5 الی 20کا در 24 ساعت"), "insta_user"),
    _ig("ig_story_vote_no", "❌ نظرسنجی استوری | گزینه خیر", "نظرسنجی استوری - خیر", 57500, 100, 100000,
        _L("شروع بین 2 تا 5 ساعت", "لینک را طبق الگوی زیر وارد کنید",
           "https://instagram.com/stories/username/2775373807903362640?vote=no"), "insta_story_link"),
    _ig("ig_story_trend", "📈 ترند استوری", "ترند استوری اینستاگرام", 290100, 100, 100000000,
        _L("شروع بین 2 تا 6 ساعت", "افزایش موارد زیر انجام خواهد شد",
           "Story Shares, Impressions, Profile Visits, Next Count, Back Count, Exit Count",
           "فقط برای یک لینک استوری می باشد"), "insta_story_link"),
    _ig("ig_story_click", "🔗 کلیک لینک استوری", "افزایش کلیک لینک استوری", 331600, 100, 1000,
        _L("شروع بین 1 تا 5 ساعت", "لینک استوری را وارد کنید"), "insta_story_link"),
    _ig("ig_story_share", "📤 شیر استوری", "شیر استوری - Story Share", 106200, 100, 1000000,
        _L("استارت : آنی", "لینک استوری را وارد کنید ( برای یک استوری )"), "insta_story_link"),
    _ig("ig_story_view_ir", "🇮🇷 بازدید استوری فعال و ایرانی", "بازدید استوری فعال و ایرانی", 600000, 100, 5000,
        _L("🕑 زمان شروع : 2 الی 5 ساعت (اغلب آنی)", "✅ زمان تکمیل : 12 ساعت", "🩸 میزان ریزش : ندارد",
           "👌 کیفیت سرویس : ایرانی", "🔗 نمونه لینک : لینک استوری را کپی کرده و وارد کنید", "",
           "نکات مهم :", "📌 ابتدا استوری گذاشته و سپس سفارش خود را ثبت کنید.",
           "📌 به تمام استوری ها ویو زده می شود.", "📌 پیج عمومی باشد."), "insta_story_link"),
    _ig("ig_story_add", "➕ اد استوری پست فعال و ایرانی", "اد استوری پست فعال و ایرانی", 750000, 300, 5000,
        _L("🕑 زمان شروع : 2 الی 5 ساعت (اغلب آنی)", "✅ زمان تکمیل : 12 ساعت", "🩸 میزان ریزش : ندارد",
           "👌 کیفیت سرویس : ایرانی", "🔗 نمونه لینک : لینک پست یا استوری را کپی کرده و وارد کنید", "",
           "نکات مهم :", "📌 ابتدا استوری گذاشته و سپس سفارش خود را ثبت کنید.",
           "📌 به تمام استوری ها ویو زده می شود.", "📌 پیج عمومی باشد."), "insta_post_or_story"),
    _ig("ig_story_ir", "🇮🇷 بازدید استوری ایرانی", "بازدید استوری ایرانی", 825000, 50, 300,
        _L("🕑 زمان شروع : 2 تا 5 ساعت", "🚀 سرعت ارسال : 1 کا در 24 ساعت", "🩸 میزان ریزش : کم",
           "👌 کیفیت سرویس : ایرانی", "✅ زمان تکمیل : 24 تا 48 ساعت", "🔗 نمونه لینک : username", "",
           "نکات مهم :", "📌 ابتدا استوری گذاشته و سپس سفارش دهید.", "📌 پیج عمومی باشد.",
           "⚠️ در صورت لینک گذاری اشتباه هزینه برگشت داده نمی شود."), "insta_user"),
]

# ─ کامنت ─
_IG_CM_RULES = [
    "📌در هر خط یک کامنت نوشته شود و Enter بزنید و در خط بعد کامنت جدید را وارد نمائید.",
    "📌 کامنت با @ ثبت نکنید",
    "📌 کامنت‌های سیاسی, ناسزا و ... به هیچ عنوان انجام نشده و مبلغ سفارش بازگشت داده نمی شود",
    "📌پیج عمومی باشد.",
]

def _ig_cm_custom_desc(quality):
    return _L("تا تکمیل سفارش کامنت‌ها باز باشد.", "",
              "🕑 زمان شروع : 0 الی 48 ساعت", "🚀 سرعت ارسال : 50 الی 100عدد در 24 ساعت", "🩸 میزان ریزش : ندارد",
              f"👌 کیفیت سرویس : {quality}", "🔗 نمونه لینک : https://www.instagram.com/p/xyz", "",
              "نکات مهم :", *_IG_CM_RULES)

def _ig_cm_panel_desc(start, quality, capacity, speed, extra=None):
    lines = [f"⏳ زمان استارت سرویس : {start}", f"🛒 ظرفیت ثبت : {capacity} برای هر پست",
             f"👦 کیفیت پروفایل ها : {quality}", f"🚀 سرعت ارسال روزانه : {speed}", "⛔ ریزش : ندارد",
             "🔗 نحوه درج لینک : لینک پست را درج کنید", "🔰 پیج حتما باید عمومی باشد کامنت پست باز باشد"]
    return _L(*lines)

IG_COMMENT = [
    _ig("ig_cm_emoji_f", "😍 کامنت ایموجی خارجی", "کامنت ایموجی خارجی", 212300, 10, 50000,
        _L("زمان شروع: بین 12 تا 24 ساعت", "لینک پست را وارد کنید", "https://www.instagram.com/tv/B4u8cDHgT1K"),
        "insta_post"),
    _ig("ig_cm_custom_ir", "✍️ کامنت سفارشی ایرانی", "کامنت سفارشی ایرانی", 675000, 10, 5000,
        _ig_cm_custom_desc("میکس ایرانی و خارجی"), "insta_post", comments=True),
    _ig("ig_cm_random_ir", "🎲 کامنت رندوم ایرانی", "کامنت رندوم ایرانی", 675000, 100, 5000,
        _ig_cm_panel_desc("0 الی 5 ساعت", "ایرانی", "5 کا", "10 الی 5000 عدد"), "insta_post"),
    _ig("ig_cm_emoji_ir", "😎 کامنت ایموجی ایرانی", "کامنت ایموجی ایرانی", 825000, 10, 1000,
        _ig_cm_panel_desc("0 الی 1 ساعت", "ایرانی", "5 کا", "10 الی 5000 عدد"), "insta_post"),
    _ig("ig_cm_custom_ir2", "✍️ کامنت دلخواه ایرانی", "کامنت دلخواه ایرانی", 1035000, 10, 1000,
        _ig_cm_custom_desc("میکس ایرانی و خارجی"), "insta_post", comments=True),
    _ig("ig_cm_custom_f", "✍️ کامنت دلخواه خارجی", "کامنت دلخواه خارجی", 1061200, 10, 50000,
        _L("زمان شروع: بین 1 تا 3 ساعت", "تاثیر در رفتن پست به اکسپلور ( تضمینی نیست )", "لینک پست را وارد کنید",
           "https://www.instagram.com/tv/B4u8cDHgT1K"), "insta_post", comments=True),
    _ig("ig_cm_emoji_fast", "⚡ کامنت ایموجی", "کامنت ایموجی ⚡️⭐", 1591700, 10, 100000,
        _ig_cm_panel_desc("0 الی 1 ساعت", "خارجی", "5 کا", "10 الی 5000 عدد"), "insta_post"),
    _ig("ig_cm_custom_f2", "✍️ کامنت دلخواه خارجی | سرور ۲", "کامنت دلخواه خارجی (سرور 2)", 1591700, 10, 100000,
        _ig_cm_custom_desc("خارجی"), "insta_post", comments=True),
    _ig("ig_cm_pos", "👍 کامنت ایموجی مثبت", "کامنت اموجی مثبت 👍🤩🎉🔥❤🥰👏🏻", 1910000, 1, 20000,
        _ig_cm_panel_desc("0 الی 1 ساعت", "خارجی", "1 کا", "20 کا"), "insta_post"),
    _ig("ig_cm_neg", "👎 کامنت ایموجی منفی", "کامنت اموجی منفی 👎😢💩🤮🤔🤯🤬", 1910000, 10, 20000,
        _ig_cm_panel_desc("0 الی 1 ساعت", "خارجی", "1 کا", "10 الی 50 عدد"), "insta_post"),
    _ig("ig_cm_custom_vip", "👑 کامنت دلخواه ایرانی | اختصاصی", "کامنت دلخواه ایرانی - اختصاصی", 13500000, 10, 100,
        _L("تا تکمیل سفارش کامنت‌ها باز باشد.", "",
           "🕑 زمان تکمیل : 12 الی 48 ساعت", "🩸 میزان ریزش : ندارد", "👌 کیفیت سرویس : ایرانی",
           "🔗 فرمت لینک : لینک پست اینستاگرام را وارد کنید", "",
           "https://www.instagram.com/reel/DcY7lvAsX38", "",
           "نکات مهم :",
           "📌در هر خط یک کامنت نوشته شود و Enter بزنید و در خط بعد کامنت جدید را وارد نمائید.",
           "📌 کامنت با @ ثبت نکنید. مبلغ تون سوخت میشه",
           "📌 کامنت‌های سیاسی, ناسزا و ... به هیچ عنوان انجام نشده و مبلغ سفارش بازگشت داده نمی شود",
           "📌پیج عمومی باشد."), "insta_post", comments=True),
]

# ─ واچ‌تایم ─
_IG_WT_NOTES = _L("", "نکات مهم :", _IG_N_NOSUP, _IG_N_SLIDE, _IG_N_SIMUL, _IG_N_PUB, _IG_N_LIMIT)
IG_WATCH = [
    _ig("ig_wt_10s", "⏱ ویو + واچ‌تایم ۵ تا ۱۰ ثانیه", "ویو اینستاگرام +{واچ تایم 5 تا 10 ثانیه}", 12300, 500, 100000,
        _L("🕑 زمان شروع : 0 تا 3 ساعت", "✅ زمان تکمیل : 24 تا 48 ساعت",
           "⏱️ میزان دریافت واچ تایم : بین 5 تا 10ثانیه، بستگی به زمان ویدیو دارد", "👌 کیفیت سرویس : خارجی",
           "🔗 نمونه لینک", "https://www.instagram.com/reel/xyz") + _IG_WT_NOTES, "insta_post"),
    _ig("ig_wt_stats", "📊 افزایش آمار اینستاگرام", "افزایش آمار اینستاگرام {Engagement + Shares + Reach + Impressions + Profile Visits}",
        420800, 100, 100000,
        _L("🕑 زمان شروع : 3 تا 12 ساعت", "✅ زمان تکمیل : 24 تا 48 ساعت", "👌 کیفیت سرویس : خارجی",
           "🔗 نمونه لینک", "https://www.instagram.com/reel/xyz"), "insta_post"),
    _ig("ig_wt_1m", "⏳ ویو + واچ‌تایم ۱ دقیقه", "ویو اینستاگرام + {واچ تایم 1 دقیقه}", 11957000, 5, 1000,
        _L("🕑 زمان شروع : 3 تا 12 ساعت", "✅ زمان تکمیل : 24 تا 48 ساعت",
           "⏱️ میزان دریافت واچ تایم : 1 دقیقه ، بستگی به زمان ویدیو دارد", "👌 کیفیت سرویس : خارجی",
           "🔗 نمونه لینک", "https://www.instagram.com/reel/xyz", "",
           "نکات مهم :", _IG_N_SLIDE, _IG_N_SIMUL, _IG_N_PUB, _IG_N_LIMIT), "insta_post"),
]

# ─ IGTV ─
IG_IGTV = [
    _ig("ig_igtv_2", "📺 ویو IGTV | سرور ۲", "ویو IGTV - سرور 2", 105500, 100, 2147483647,
        _L("شروع بین 1 تا 3 ساعت", "لینک پست را وارد کنید"), "insta_post"),
    _ig("ig_igtv_imp", "📺 IGTV Views + Impressions", "Instagram IGTV Views + Impressions", 215000, 100, 2147483647,
        _L("شروع بین 5 تا 12 ساعت", "لینک پست را وارد کنید"), "insta_post"),
]

# ─ منشن ─
IG_MENTION = [
    _ig("ig_mention_following", "👥 منشن از فالوینگ پیج هدف", "منشن اینستاگرام از فالوینگ پیج هدف", 707500, 2000, 100000,
        _L("توجه کنید این سرویس برای فالوینگ هست نه فالوور اشتباه ثبت کنید برگشت داده نخواهد شد",
           "شروع سفارش بین 12 تا 24 ساعت", "تکمیل سفارش بین 3 تا 5 روز برای هر 1 کا",
           "شما با استفاده از این سرویس میتوانید تعداد زیادی از افراد رو به پست های خودتون جذب کنید", "",
           "لینک : در این قسمت لینک یکی از پست های خودتان که قصد تبلیغات دارید را وارد نمایید", "",
           "نام کاربری : در این قسمت باید ایدی پیج هدف ( پیج رقبا ) را وارد کنید که قصد دارید فالوینک آن پیج زیر پست شما منشن شوند را وارد کنید"),
        "insta_post_user"),
    _ig("ig_mention_comments", "💬 منشن از کامنت‌های پست هدف", "منشن اینستاگرام از کامنت های پست هدف", 707500, 2000, 100000,
        _L("شروع سفارش بین 1 تا 3 ساعت", "تکمیل سفارش بین 1 تا 3 روز برای هر 1 کا",
           "شما با استفاده از این سرویس میتوانید تعداد زیادی از افراد رو به پست های خودتون جذب کنید", "",
           "لینک : در این قسمت لینک یکی از پست های خودتان که قصد تبلیغات دارید را وارد نمایید", "",
           "لینک مدیا : لینک پست اینستاگرامی (رقبا) که می‌خواهید کاربرانی را زیر این پست کامنت گذاشتند را زیر پست شما منشن کنیم"),
        "insta_post_media"),
    _ig("ig_mention_vip", "💎 منشن از فالوورهای پیج هدف | اختصاصی", "منشن از فالوورهای پیج هدف - اختصاصی💎", 1950000, 100, 5000,
        _L("🕑 زمان شروع : 24 الی 48 ساعت", "👌 کیفیت سرویس : متوسط", "✅ زمان تکمیل : 3 تا 5 روز برای هر کا",
           "🔗 نمونه لینک : https://www.instagram.com/reel/xyz", "",
           "توضیحات سرویس :", "",
           "📌لینک : لینک پست اینستاگرام خود را وارد کنید ( بخش کامنت ها باز باشد )",
           "📌لیست سفارشی : لطفاً یوزرنیم‌ها را بدون @ و هر کدام در یک خط وارد نمایید"), "insta_post_list"),
    _ig("ig_mention_followers", "🎯 منشن از فالوورهای پیج هدف", "منشن از فالوورهای پیج هدف", 3065500, 1000, 1000000,
        _L("🕑 زمان شروع : 12 الی 48 ساعت", "👌 کیفیت سرویس : متوسط", "✅ زمان تکمیل : 3 تا 7 روز برای هر کا",
           "🔗 نمونه لینک : https://www.instagram.com/reel/xyz", "",
           "نکات مهم :", "",
           "📌لینک : در این قسمت لینک یکی از پست های خودتان که قصد تبلیغات دارید را وارد نمایید",
           "📌نام کاربری : در این قسمت باید ایدی پیج هدف ( پیج رقبا ) را وارد کنید که قصد دارید فالوورهای آن پیج زیر پست شما منشن شوند را وارد کنید"),
        "insta_post_user"),
    _ig("ig_mention_list", "📝 منشن لیست دلخواه | سرور ۱", "منشن لیست دلخواه - سرور1", 3065500, 1000, 1000000,
        _L("🕑 زمان شروع : 12 الی 48 ساعت", "👌 کیفیت سرویس : متوسط", "✅ زمان تکمیل : 3 تا 7 روز برای هر کا",
           "🔗 نمونه لینک : https://www.instagram.com/reel/xyz", "",
           "نکات مهم :", "",
           "📌لینک : در این قسمت لینک یکی از پست های خودتان که قصد تبلیغات دارید را وارد نمایید",
           "📌نام کاربری ها : در این قسمت باید لیست ایدی کاربران را وارد کنید که قصد دارید زیر پست شما منشن شوند را وارد کنید"),
        "insta_post_list"),
]

# ─ خرید پیج / تیک آبی ─
IG_PAGE = [
    _ig("ig_page_cheap", "📱 پیج اینستاگرام ارزان", "پیج اینستاگرام ارزان", 450000, 5000, 200000,
        _L("🕑 زمان تحویل : 3 الی 7 روز کاری (هماهنگی با پشتیبانی)", "", "🩸 میزان ریزش : 30 روز بدون ریزش", "",
           "👌 کیفیت سرویس : میکس ایرانی و خارجی", "",
           "🔗 لینک : در بخش لینک شماره موبایل خود را وارد کنید.", "",
           "نکات مهم :", "",
           "📌 لطفا بعد از ثبت سفارش به پشتبانی سایت اطلاع دهید.",
           "📌عمر پیج ها چقدر است؟ پیج ها تازه تاسیس می باشد",
           "📌ریزش پیج ها چقدر است؟ با آپدیت های بعدی اینستاگرام احتمالا تا 50% ریزش داشته باشند",
           "⚠️ در زمان محدودیت ریزش افزایش پیدا می کند."), "phone_ir"),
    _ig("ig_page_raw", "🆕 پیج خام اینستاگرام", "پیج خام اینستاگرام", 295000000, 1, 100,
        _L("🕑 زمان تحویل : 2 الی 3 روز", "", "👌 کیفیت سرویس : پیج خام", "",
           "🔗 لینک : شماره موبایل خود را وارد کنید.", "",
           "نکات مهم :", "",
           "📌 پیج ها به صورت خام و بدون فالوور به شما تحویل داده میشوند.",
           "📌 برای هماهنگی تحویل پیج تیکت بزنید یا به پشتیبانی پیام بدید"), "phone_ir"),
]
IG_BLUE_TICK = _ig("ig_blue_tick", "✅ تیک آبی اینستاگرام", "تیک آبی اینستاگرام", 15000000, 1, 1,
    _L("🕑 زمان شروع : 1 الی 24 ساعت", "👌 کیفیت سرویس : واقعی", "✅ زمان تکمیل : 3 الی 7 روز",
       "🔗 نمونه لینک : شماره تماس", "",
       "نکات مهم :", "",
       "📌 پیج ها به صورت آماده با تیک آبی (1کا فالوور) به شما تحویل داده میشوند.",
       "📌اعتبار تیک آبی 1 ماه هست و برای تمدید مجدد باید خودتون اقدام کنید.",
       "📌 لطفا پس از ثبت سفارش برای تکمیل روند سفارش با پشتیبانی در ارتباط باشید."),
    "phone_ir", fixed=True, icon="✅")

# ─ لایک / فالوور عربی ─
def _ig_arab_desc(start, drop, link, need_public=True, quality="عرب"):
    lines = [f"⏳ زمان شروع : {start}", f"👦 کیفیت پروفایل ها : {quality}", f"⛔ ریزش : {drop}", f"🔗 نحوه درج لینک : {link}"]
    if need_public:
        lines.append("🔰 پیج حتما باید عمومی باشد")
    return _L(*lines)

IG_ARAB = [
    _ig("ig_ar_like_s2", "🌙 لایک عربی | سرور ۲", "لایک عربی - سرور2", 34100, 100, 10000,
        _ig_arab_desc("2 الی 5 ساعت", "30 روز بدون ریزش", "لینک پست را وارد کنید"), "insta_post"),
    _ig("ig_ar_like_ir", "🇮🇷 لایک ایرانی - عربی | سرور ۲", "لایک ایرانی - عربی (سرور 2)", 93400, 50, 10000,
        _ig_arab_desc("2 الی 5 ساعت", "کم", "پست اینستاگرام را وارد کنید", need_public=False), "insta_post"),
    _ig("ig_ar_story", "👁 ویو استوری عربی", "ویو استوری عربی", 96700, 20, 50000,
        _ig_arab_desc("1 الی 5 ساعت", "ندارد", "لینک استوری را وارد کنید"), "insta_story_link"),
    _ig("ig_ar_like_cheap", "💸 لایک عربی | ارزان", "لایک عربی- ارزان", 107200, 10, 20000,
        _ig_arab_desc("2 الی 5 ساعت", "ندارد", "لینک پست را وارد کنید"), "insta_post"),
    _ig("ig_ar_fol_mix", "🌀 فالوور میکس ایرانی - عربی", "فالوور میکس ایرانی - عربی", 428000, 10, 30000,
        _ig_arab_desc("2 الی 5 ساعت", "کم", "یوزنیم اینستاگرام را وارد کنید", need_public=False), "insta_user"),
    _ig("ig_ar_fol_s1", "🖥 فالوور عربی | سرور ۱", "فالوور عربی- سرور 1", 2047500, 10, 100000,
        _ig_arab_desc("2 الی 5 ساعت", "0 الی 10 درصد", "یوزنیم اینستاگرام را وارد کنید"), "insta_user"),
    _ig("ig_ar_fol_3m", "🛡 فالوور عربی | ۳ ماه بدون ریزش", "فالوور عربی- 3 ماه بدون ریزش", 2242500, 10, 100000,
        _ig_arab_desc("2 الی 5 ساعت", "3 ماه بدون ریزش", "یوزنیم اینستاگرام را وارد کنید"), "insta_user"),
]

# ─ فالوور خارجی (قیمت اصلی، بدون ۲ برابر) ─
def _ig_fol_f_desc(start, drop, complete, notes, speed=None, gift=None, quality="خارجی"):
    lines = [f"🕑 زمان شروع : {start}"]
    if speed:
        lines.append(f"🚀 سرعت ارسال : {speed}")
    lines.append(f"🩸 میزان ریزش : {drop}")
    if gift:
        lines.append(f"🎁 هدیه : {gift}")
    lines += [f"👌 کیفیت سرویس : {quality}", f"✅ زمان تکمیل : {complete}", "🔗 نمونه لینک : username", "",
              "نکات مهم :", ""] + notes
    return _L(*lines)

IG_FOLLOWER_F = [
    _ig("ig_fol_f_cheap", "💸 فالوور خارجی ارزان", "فالوور خارجی ارزان", 794000, 100, 5000000,
        _ig_fol_f_desc("6 الی 12 ساعت", "10 تا 30 درصد ( در زمان محدویت ها بیشتر)", "24 تا 72 ساعت",
                       ["📌 جبران ریزش ندارد", "📌 پیج عمومی باشد.", "📌 سفارش همزمان ثبت نکنید تا سفارش قبلی شما تکمیل شود."]),
        "insta_user", x=1),
    _ig("ig_fol_f_limit", "🛡 فالوور خارجی | ویژه محدودیت", "فالوور خارجی اینستاگرام ویژه محدودیت", 1235000, 10, 1000000,
        _ig_fol_f_desc("6 الی 12 ساعت", "کم ریزش", "24 تا 72 ساعت",
                       ["📌 جبران ریزش ندارد", "📌 پیج عمومی باشد.",
                        "📌 سفارش همزمان برای یک لینک از یک سرویس ثبت نکنید تا سفارش قبلی شما برای همان لینک تکمیل شود."]),
        "insta_user", x=1),
    _ig("ig_fol_f_30d", "🔄 فالوور خارجی | جبران ریزش ۳۰ روزه", "فالوور خارجی | جبران ریزش 30 روزه", 1560000, 10, 1000000,
        _ig_fol_f_desc("6 الی 12 ساعت", "30 روز بدون ریزش", "24 تا 72 ساعت",
                       ["📌 جبران ریزش تا یک ماه", "📌 پیج عمومی باشد.",
                        "📌 سفارش همزمان برای یک لینک از یک سرویس ثبت نکنید تا سفارش قبلی شما برای همان لینک تکمیل شود.",
                        "📌 ریزش فالوور های قبلی بر عهده مشتری است پیج داری ریزش نباشد"]),
        "insta_user", x=1),
    _ig("ig_fol_f_s1", "🖥 فالوور خارجی | سرور ۱", "فالوور خارجی اینستاگرام - سرور 1", 1697800, 10, 1000000,
        _ig_fol_f_desc("2 الی 5 ساعت", "0 الی 20%", "24 تا 72 ساعت",
                       ["📌 ایدی پیج را کپی و ثبت کرده و ایدی پیج را دستی وارد نکنید.", "📌 جبران ریزش ندارد.",
                        "📌 سفارش همزمان برای یک لینک از یک سرویس ثبت نکنید تا سفارش قبلی شما برای همان لینک تکمیل شود.",
                        "📌 در صورت ثبت سفارش همزمان امکان بررسی سفارش و عودت وجه وجود ندارد.", "📌 پیج عمومی باشد."],
                       speed="5 الی 20 کا در 24 ساعت", gift="0 الی 10%", quality="خارجی با کیفیت"),
        "insta_user", x=1),
    _ig("ig_fol_f_s4", "🚀 فالوور خارجی | سرور ۴", "فالوور خارجی -سرور4", 1768600, 1, 10000000,
        _ig_fol_f_desc("2 الی 5 ساعت", "0 الی 20%", "24 تا 72 ساعت",
                       ["📌 ایدی پیج را کپی و ثبت کنید و ایدی پیج را دستی وارد نکنید.",
                        "📌 در صورت ثبت سفارش همزمان امکان بررسی سفارش و عودت وجه وجود ندارد.", "📌 پیج عمومی باشد"],
                       speed="5 الی 20 کا در 24 ساعت", quality="خارجی با کیفیت"),
        "insta_user", x=1),
]

# ─ لایو ─
def _ig_live_desc(start):
    return _L(f"⏳ زمان شروع: {start}", "👌 کیفیت: خارجی", "🚀 سرعت ارسال روزانه: نامحدود", "⛔️ ریزش : ندارد",
              "🔗 نحوه درج لینک : لینک لایو یا آیدی پیج", "✏️ نمونه لینک:", "",
              "https://www.instagram.com/username/live/12345", "",
              "🔰 هرجا سوالی داشتید و یا نیاز به راهنمایی داشتید به پشتیبانی پیام دهید",
              "🔰 پیج حتما باید عمومی باشد")

IG_LIVE = [
    _ig("ig_live_15", "📡 بازدید لایو | ۱۵ دقیقه‌ای", "بازدید لایو اینستاگرام (15 دقیقه ای)", 313700, 10, 10000,
        _ig_live_desc("0 الی 1 ساعت"), "insta_live"),
    _ig("ig_live_30", "📡 بازدید لایو | ۳۰ دقیقه‌ای", "بازدید لایو اینستاگرام (30 دقیقه ای)", 621700, 10, 10000,
        _ig_live_desc("0 الی 1 ساعت"), "insta_live"),
    _ig("ig_live_30_s2", "⚡ بازدید لایو ۳۰ دقیقه‌ای | سرور ۲", "بازدید لایو اینستاگرام (30 دقیقه ای) - سرور 2", 707500, 5, 5000,
        _ig_live_desc("5 الی 15 دقیقه"), "insta_live"),
    _ig("ig_live_15_s2", "🚀 بازدید لایو ۱۵ دقیقه‌ای | سرور ۲", "بازدید لایو اینستاگرام (15 دقیقه ای) - سرور 2", 1300000, 50, 50000,
        _ig_live_desc("0 الی 1 ساعت"), "insta_live"),
]

# ─ استخراج دیتا ─
IG_EXTRACT = [
    _ig("ig_ext_cm_s2", "📥 استخراج کامنت‌ها | سرور ۲", "استخراج کامنت های اینستا [Commets]سرور 2", 37500, 50000, 3000000,
        _L("استخراج کامنت های اینستاگرام در اکسل", "",
           "⏳ زمان تکمیل : 12 الی 48 ساعت", "🛒 ظرفیت ثبت : 5 میلیون کامنت",
           "🔗 در قسمت لینک آدرس ایمیل خود را درج کنید", "🔗 در قسمت لینک مدیا، لینک پست هدف درج گردد",
           "🔰 پیج باید عمومی باشد", "🔰 اطلاعات استخراجی در فایل EXCEL به ایمیل شما ارسال می گردد"), "email_media"),
    _ig("ig_ext_cm", "📥 استخراج کامنت‌های پست دلخواه", "استخراج کامنت های اینستا پست دلخواه [Commets]", 72000, 1000, 200000,
        _L("استخراج کامنت های اینستاگرام در اکسل", "",
           "⏳ زمان تکمیل : 12 الی 48 ساعت", "🛒 ظرفیت ثبت : 2 میلیون کامنت",
           "🔗 در قسمت لینک آدرس ایمیل خود را درج کنید", "🔗 در قسمت لینک مدیا، لینک پست هدف درج گردد", "",
           "🔰 پیج باید عمومی باشد", "🔰 اطلاعات استخراجی در فایل EXCEL به ایمیل شما ارسال می گردد"), "email_media"),
    _ig("ig_ext_followers", "📇 استخراج ایمیل و موبایل فالوورها", "استخراج ایمیل و موبایل فالوورهای پیج دلخواه", 825000, 1000, 100000,
        _L("استخراج  اطلاعات کامل فالوورهای هر پیج از اینستاگرام", "",
           "داده ها شامل: (ایمیل، شماره تلفن، آدرس، نام کاربری، متن بایو، آیدی کاربر، تعداد فالوور، تعداد فالوینگ ، وب سایت و ..)", "",
           "برای مثال: اگر نام کاربری را وارد کنید: رونالدو ،ما اطلاعات کامل فالوورهای کریستیانو رونالدو را جمع آوری می‌کنیم", "",
           "بهترین سرویس بازاریابی برای تبلیغات پیامکی و ایمیل مارکتینگ", "",
           "اطلاعات فالوور های هر یک از اینفلوئنسرهای اینستاگرام را با این روش استخراج کرده و محصولات و خدمات خود را مستقیم به آنها معرفی کنید", "",
           "نکات مهم :", "",
           "📌 : برای اکانت هایی که تیک آبی و تایید شده دارند امکان پذیر نمی باشد.", "",
           "📌 : شماره موبایل و ایمیل در بخش بایو {در صورت موجود بودن }فقط قابل استخراج است به همین خاطر ممکن است از هر 1 کا فالوور فقط 30% کاربران ایمیل و موبایل داشته باشند.", "",
           "📌:  ایدی اکانت خود را به طور صحیح وارد کنید. در صورتی که ایدی اشتباه ثبت شود سفارش برای ایدی اشتباه ثبت شده و سایت هیچ مسئولیتی در قبال این موارد ندارد و هزینه برگشت داده نمی شود.", "",
           "⚠️ : با ثبت سفارش برای این سرویس شما تمامی توضیحات را پذیرفته و تایید کردید و بعد از ثبت امکان کنسل کردن و برگشت هزینه وجود ندارد.", "",
           "⏳ زمان استارت سرویس : 2 الی 24 ساعت", "",
           "⏳ زمان تحویل سرویس : برای هر 1 کا 48 ساعت",
           "🔗 در قسمت لینک آدرس ایمیل خود را درج کنید",
           "🔗 در قسمت نام کاربری، آیدی پیج هدف را وارد کنید", "",
           "🔰 پیج باید عمومی باشد", "🔰 اطلاعات استخراجی در فایل EXCEL به ایمیل شما ارسال می گردد"), "email_user"),
]


def add_instagram(data):
    """
    اپلیکیشن «🔴 اینستاگرام» را با همه‌ی بخش‌هایش اضافه می‌کند.
    چیزی را پاک یا جایگزین نمی‌کند؛ پوشه یا سرویسی که از قبل باشد دوباره ساخته نمی‌شود.
    """
    h = _cat_helpers(data)
    if h is None:
        return
    ig = find_app_folder(data, INSTAGRAM_TITLE) or h.add_folder("root", INSTAGRAM_TITLE, "بخش مورد نظر رو انتخاب کن 👇🔴")

    def add(parent, svc):
        h.add_service(parent, svc["key"], svc["title"], svc["label"], svc["price"], svc["mn"], svc["mx"],
                      svc["desc"], svc["platform"],
                      fixed_price=svc["price"] if svc["fixed"] else None, icon=svc["icon"])
        if svc["comments"] and svc["key"] in data["settings"]:
            data["settings"][svc["key"]].setdefault("need_comments", True)

    def section(parent, title, text, services):
        f = h.get_folder(parent, title, text)
        for s in services:
            add(f, s)
        return f

    section(ig, "👁 ویو ریلز + ویدئو", "سرویس مورد نظر رو انتخاب کن 👇👁", IG_VIEWS)
    section(ig, "🧭 اکسپلور اینستاگرام", "بسته‌ی مورد نظر رو انتخاب کن 👇🧭", IG_EXPLORE)
    section(ig, "💾 سیو/شیر/ایمپرشن/بازدید پروفایل", "سرویس مورد نظر رو انتخاب کن 👇💾", IG_SAVE_SHARE)
    section(ig, "🔁 ریپست اینستاگرام", "سرویس مورد نظر رو انتخاب کن 👇🔁", IG_REPOST)
    section(ig, "🇮🇷 فالوور ایرانی", "سرویس مورد نظر رو انتخاب کن 👇🇮🇷", IG_FOLLOWER_IR)
    likes = h.get_folder(ig, "❤️ لایک اینستاگرام", "نوع لایک رو انتخاب کن 👇❤️")
    section(likes, "🇮🇷 لایک ایرانی", "سرویس مورد نظر رو انتخاب کن 👇🇮🇷", IG_LIKE_IR)
    section(likes, "🌍 لایک خارجی", "سرویس مورد نظر رو انتخاب کن 👇🌍", IG_LIKE_F)
    section(ig, "📖 استوری اینستاگرام", "سرویس مورد نظر رو انتخاب کن 👇📖", IG_STORY)
    section(ig, "💬 کامنت اینستاگرام", "سرویس مورد نظر رو انتخاب کن 👇💬", IG_COMMENT)
    section(ig, "⏱ واچ‌تایم اینستاگرام", "سرویس مورد نظر رو انتخاب کن 👇⏱", IG_WATCH)
    section(ig, "📺 IGTV اینستاگرام", "سرویس مورد نظر رو انتخاب کن 👇📺", IG_IGTV)
    section(ig, "🏷 منشن اینستاگرام", "سرویس مورد نظر رو انتخاب کن 👇🏷", IG_MENTION)
    section(ig, "🛒 خرید پیج اینستاگرام", "سرویس مورد نظر رو انتخاب کن 👇🛒", IG_PAGE)
    add(ig, IG_BLUE_TICK)                       # فقط ۱ سرویس → مستقیم زیر اینستاگرام
    section(ig, "🌙 لایک / فالوور عربی", "سرویس مورد نظر رو انتخاب کن 👇🌙", IG_ARAB)
    section(ig, "🌍 فالوور خارجی", "سرویس مورد نظر رو انتخاب کن 👇🌍", IG_FOLLOWER_F)
    section(ig, "📡 لایو اینستاگرام", "سرویس مورد نظر رو انتخاب کن 👇📡", IG_LIVE)
    section(ig, "🗂 استخراج دیتا", "سرویس مورد نظر رو انتخاب کن 👇🗂", IG_EXTRACT)


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
    aparat_id = add_folder("root", APARAT_TITLE, "بخش مورد نظر رو انتخاب کن 👇🎬")

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
    soroush_id = add_folder("root", SOROUSH_TITLE, "بخش مورد نظر رو انتخاب کن 👇🔵")
    soroush_view_id = add_folder(soroush_id, "👁 بازدیدها", "بازدید مورد نظر رو انتخاب کن 👇👁")
    for key, title, label, price1000, mn, mx, desc in SOROUSH_SERVICES:
        add_service(soroush_view_id, key, title, {
            "min": mn, "max": mx, "price_per_1000": price1000, "platform": "soroush",
            "label": label, "head": label, "desc": desc,
        })

    data["catalog"]["counter"] = counter
    add_bale_and_soroush_members(data)
    add_bale_views_ads_and_eitaa(data)
    add_rubika(data)
    add_instagram(data)
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
    if "bale_soroush_members_v1" not in done:
        add_bale_and_soroush_members(data)
        done.append("bale_soroush_members_v1")
    if "app_circles_v1" not in done:
        rename_app_circles(data)
        done.append("app_circles_v1")
    if "bale_views_ads_eitaa_v1" not in done:
        add_bale_views_ads_and_eitaa(data)
        done.append("bale_views_ads_eitaa_v1")
    if "rubika_v1" not in done:
        add_rubika(data)
        done.append("rubika_v1")
    if "rubika_12m_v1" not in done:
        fix_rubika_12m(data)
        done.append("rubika_12m_v1")
    if "rubika_3m_price_v1" not in done:
        fix_rubika_3m_price(data)
        done.append("rubika_3m_price_v1")
    if "instagram_v1" not in done:
        add_instagram(data)
        done.append("instagram_v1")

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
    "soroush_id":   validate_soroush_id_link,
    "bale_id":      validate_bale_id_link,
    "bale_channel": validate_bale_channel_link,
    "bale_group":   validate_bale_group_link,
    "bale_channel_group": validate_bale_channel_group_link,
    "bale_post":    validate_bale_post_link,
    "plain_id":     validate_plain_id,
    "id_at_suffix": validate_id_at_suffix,
    "id_any":       validate_id_any,
    "id_at":        validate_bale_id_link,
    "eitaa_channel":      validate_eitaa_channel_link,
    "eitaa_join":         validate_eitaa_join_link,
    "eitaa_channel_join": validate_eitaa_channel_or_join_link,
    "eitaa_post":         validate_eitaa_post_link,
    "rubika_post":        validate_rubika_post_link,
    "rubika_chat":        validate_rubika_chat_link,
    "rubika_any":         validate_rubika_any_link,
    "rubino_post":        validate_rubino_post_link,
    "rubino_page":        validate_rubino_page,
    "insta_post":         validate_insta_post,
    "insta_user":         validate_insta_user,
    "insta_story_link":   validate_insta_story_link,
    "insta_post_or_story": validate_insta_post_or_story,
    "insta_live":         validate_insta_live,
    "phone_ir":           validate_phone_ir,
    "insta_post_user":    validate_insta_post_user,
    "insta_post_media":   validate_insta_post_media,
    "insta_post_list":    validate_insta_post_list,
    "email_media":        validate_email_media,
    "email_user":         validate_email_user,
}
LINK_HINTS = {
    "aparat":       "https://www.aparat.com/v/xxxxx",
    "aparat_short": "https://aparat.com/shorts/123456",
    "aparat_channel": "https://www.aparat.com/username",
    "aparat_live":  "https://www.aparat.com/username/live",
    "soroush":      "https://splus.ir/channel/xxxxx  یا  @channel",
    "soroush_id":   "@username",
    "bale_id":      "@marketing98",
    "bale_channel": "@marketing98  یا  https://ble.ir/marketing98",
    "bale_group":   "https://ble.ir/join/nt4q4AiHp1",
    "bale_channel_group": "https://ble.ir/marketing98  یا  https://ble.ir/join/nt4q4AiHp1",
    "bale_post":    "https://ble.ir/username/123/456",
    "plain_id":     "marketing98  (آیدی کانال بدون @)",
    "id_at_suffix": "marketing98@  (آیدی کانال با @ در انتها)",
    "id_any":       "marketing98  یا  @marketing98",
    "id_at":        "@marketing98",
    "eitaa_channel":      "https://eitaa.com/marketing98",
    "eitaa_join":         "https://eitaa.com/joinchat/xxxxxxxx",
    "eitaa_channel_join": "https://eitaa.com/marketing98  یا  https://eitaa.com/joinchat/xxxxxxxx",
    "eitaa_post":         "https://eitaa.com/marketing98/17",
    "rubika_post":        "https://rubika.ir/marketing98/HHCEFICGAIFEECA",
    "rubika_chat":        "https://rubika.ir/marketing98  یا  https://rubika.ir/joinc/xxxxxxxx",
    "rubika_any":         "https://rubika.ir/marketing98",
    "rubino_post":        "https://rubika.ir/post/AbCfGh",
    "rubino_page":        "marketing98  یا  https://rubika.ir/page/marketing98",
    "insta_post":         "https://www.instagram.com/reel/xyz",
    "insta_user":         "username  (آیدی پیج، بدون @)",
    "insta_story_link":   "https://instagram.com/stories/username/2775373807903362640",
    "insta_post_or_story": "https://www.instagram.com/reel/xyz  یا  لینک استوری",
    "insta_live":         "username  یا  https://www.instagram.com/username/live/12345",
    "phone_ir":           "09123456789  (شماره موبایل)",
    "insta_post_user":    "دو خط بفرستید:\nخط اول: لینک پست شما\nخط دوم: آیدی پیج هدف (رقیب)",
    "insta_post_media":   "دو خط بفرستید:\nخط اول: لینک پست شما\nخط دوم: لینک پست هدف (رقیب)",
    "insta_post_list":    "چند خط بفرستید:\nخط اول: لینک پست شما\nخط‌های بعد: یوزرنیم‌ها بدون @ (هر کدام در یک خط)",
    "email_media":        "دو خط بفرستید:\nخط اول: آدرس ایمیل شما\nخط دوم: لینک پست هدف",
    "email_user":         "دو خط بفرستید:\nخط اول: آدرس ایمیل شما\nخط دوم: آیدی پیج هدف",
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

                    elif cb_data.startswith("fake_open|"):
                        if not is_admin(chat_id): continue
                        send_fake_service_list(chat_id,data,cb_data.split("|",1)[1])

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
