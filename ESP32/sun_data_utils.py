import time, os, json, sys, urequests

CACHE_DIR = "sun_cache"

# --- SUNRISE/SUNSET ---
def build_month_cache(year, month, lat, lng, log):
    sun_data = {}
    log(f"Bulding sunrise/sunset cache for {year}/{month}")
    for day in range(1, 32):
        try:
            t = time.mktime((year, month, day, 0, 0, 0, 0, 0))
            tm = time.localtime(t)
            date_str = f"{tm[0]:04d}-{tm[1]:02d}-{tm[2]:02d}"
            url = f"https://api.sunrisesunset.io/json?lat={lat}&lng={lng}&date={date_str}"
            r = urequests.get(url)
            js = r.json()['results']
            sun_data[date_str] = js
            time.sleep(0.3)
        except Exception as e:
            print("downloading day")
            sys.print_exception(e)
            break
    with open(f"{CACHE_DIR}/{year}-{month:02d}.json", 'w') as f:
        f.write(json.dumps(sun_data))
    log(f"Wrote sunrise/sunset cache for {year}/{month}")
def load_sun_data():
    try:
        now = time.localtime()
        fname = f"{CACHE_DIR}/{now[0]:04d}-{now[1]:02d}.json"
        with open(fname) as f:
            return json.loads(f.read())
    except:
        return {}

async def manage_cache(now, lat, lng, log):
    current_year = now[0]
    current_month = now[1]
    

    if CACHE_DIR not in os.listdir():
        os.mkdir(CACHE_DIR)

    for i in range(7):
        month = current_month + i
        year = current_year + (month - 1) // 12
        month = ((month - 1) % 12) + 1
        fname = f"{year}-{month:02d}.json"
        if fname not in os.listdir(CACHE_DIR):
            build_month_cache(year, month, lat, lng, log)
            #only one month at a time to avoid watchdog issues
            break

    for fname in os.listdir(CACHE_DIR):
        try:
            y, m = map(int, fname.replace(".json", "").split("-"))
            age_months = (current_year - y) * 12 + (current_month - m)
            if age_months > 2:
                os.remove(f"{CACHE_DIR}/{fname}")
        except:
            continue
        
def max_cache_age_months(current_year, current_month):
    max_age = 0
    try:
        for fname in os.listdir(CACHE_DIR):
            try:
                y, m = map(int, fname.replace(".json", "").split("-"))
                age_months = (y - current_year) * 12 + (m - current_month)
                max_age = max(max_age, age_months)
            except Exception:
                continue
    finally:
        return max_age


