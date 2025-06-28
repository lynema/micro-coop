# ESP32 SIDE: Wi-Fi, Scheduler, Web UI, UART Master

import network, socket, time, urequests, machine, json, os, ntptime
from machine import UART, RTC
import _thread

# --- LOGGING BUFFER ---
log_buffer = []
MAX_LOG_LINES = 30

motor_config = {}

FAILSAFE_OPEN_TO_CLOSED = 22 * 3600 + 30 * 60   # 10:30 PM
FAILSAFE_CLOSED_TO_OPEN = 8 * 3600             # 8:00 AM


def log(msg, send_uart_log=True):
    timestamp = time.localtime()
    entry = f"[{timestamp[1]}/{timestamp[2]} {timestamp[3]:02}:{timestamp[4]:02}:{timestamp[5]:02}] {msg}"
    print(entry)
    if send_uart_log: send_uart(f"log {msg}")
    log_buffer.append(entry)
    if len(log_buffer) > MAX_LOG_LINES:
        log_buffer.pop(0)

# --- CONFIGURATION ---
CONFIG_FILE = "config.json"
def load_config():
    with open(CONFIG_FILE) as f:
        cfg = json.load(f)
    return cfg

config = load_config()
LAT, LNG = config["latitude"], config["longitude"]
SSID, PASSWORD = config["ssid"], config["password"]
CACHE_DIR = "sun_cache"

# UART to RP2040
uart = UART(1, baudrate=38400, tx=7, rx=6, cts=5, rts=4)

# Global state
DOOR_STATE = "unknown"
current_draw_mv = 0
last_action_time = 0
last_ntp_sync_mday = 0
rtc = RTC()
    
# --- Detroit Time Utilities ---
def is_dst(year, month, day, hour=0, minute=0):
    """
    Determine if DST is in effect for America/Detroit.

    DST starts at 2 AM (local time) on the second Sunday in March,
    and ends at 2 AM on the first Sunday in November.
    """
    # --- DST Start (2nd Sunday of March) ---
    # March 8–14 are possible 2nd Sundays
    for d in range(8, 15):
        if time.localtime(time.mktime((year, 3, d, 0, 0, 0, 0, 0)))[6] == 6:  # Sunday
            dst_start = time.mktime((year, 3, d, 2, 0, 0, 0, 0))
            break

    # --- DST End (1st Sunday of November) ---
    for d in range(1, 8):
        if time.localtime(time.mktime((year, 11, d, 0, 0, 0, 0, 0)))[6] == 6:  # Sunday
            dst_end = time.mktime((year, 11, d, 2, 0, 0, 0, 0))
            break

    now = time.mktime((year, month, day, hour, minute, 0, 0, 0))
    return dst_start <= now < dst_end

def get_est_offset():
    """
    Return the local time in America/Detroit as an offset value.
    """
    current_time = time.localtime()
    year, month, day, hour, minute, second, _, _ = current_time
    offset = -5  # Standard Time: UTC-5
    if is_dst(year, month, day, hour, minute):
        offset = -4  # Daylight Time: UTC-4
    return offset * 3600

# --- TIME SYNC ---
def sync_time():
    global config, last_ntp_sync_mday
    try:
        ntptime.settime()
        tm = time.localtime(time.time() + get_est_offset())
        rtc.datetime((tm[0], tm[1], tm[2], tm[6], tm[3], tm[4], tm[5], 0))
        last_ntp_sync = f"{tm[0]:04d}-{tm[1]:02d}-{tm[2]:02d} {tm[3]:02d}:{tm[4]:02d}:{tm[5]:02d}"
        last_ntp_sync_mday = tm[2]
        log("[INFO] Time synced successfully")
        return True
    except Exception as e:
        log(f"[ERROR] NTP sync failed: {e}")
        return False

# --- SUNRISE/SUNSET ---
def build_month_cache(year, month):
    sun_data = {}
    for day in range(1, 32):
        try:
            t = time.mktime((year, month, day, 0, 0, 0, 0, 0))
            tm = time.localtime(t)
            date_str = f"{tm[0]:04d}-{tm[1]:02d}-{tm[2]:02d}"
            url = f"https://api.sunrisesunset.io/json?lat={LAT}&lng={LNG}&date={date_str}"
            r = urequests.get(url)
            js = r.json()['results']
            sun_data[date_str] = js
            time.sleep(0.3)
        except Exception as e:
            continue
    with open(f"{CACHE_DIR}/{year}-{month:02d}.json", 'w') as f:
        f.write(json.dumps(sun_data))

def load_sun_data():
    try:
        now = time.localtime()
        fname = f"{CACHE_DIR}/{now[0]:04d}-{now[1]:02d}.json"
        with open(fname) as f:
            return json.loads(f.read())
    except:
        return {}

def manage_cache():
    now = time.localtime()
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
            build_month_cache(year, month)

    for fname in os.listdir(CACHE_DIR):
        try:
            y, m = map(int, fname.replace(".json", "").split("-"))
            age_months = (current_year - y) * 12 + (current_month - m)
            if age_months > 2:
                os.remove(f"{CACHE_DIR}/{fname}")
        except:
            continue

def parse_time(time_str):
  """
  Parses a time string in 12-hour AM/PM format (like "10:30 AM" or "3:15 PM")
  and returns the total seconds into the day (from midnight).

  Args:
    time_str: A string representing the time in "HH:MM AM/PM/MIL" format.

  Returns:
    The total seconds into the day (integer) or None if the format is invalid.
  """
  try:
    parts = time_str.split()
    time_part = parts[0]
    ampm_part = parts[1].upper()

    hour, minute, second = map(int, time_part.split(':'))

    # Convert hour to 24-hour format
    if ampm_part == "PM" and hour != 12:
      hour += 12
    elif ampm_part == "AM" and hour == 12:
      hour = 0  # 12 AM is midnight (0 hour in 24-hour format)

    # Calculate total seconds
    total_seconds = hour * 3600 + minute * 60 + second

    return total_seconds

  except (ValueError, IndexError) as e:
    log(f"parsing {time_str} {e}")

    return None  # Handle invalid input format


def today_times(sun_data):
    now = time.localtime()
    #date_str = f"{t[0]:04d}-{t[1]:02d}-{t[2]:02d}"
    date_str = f"{now[0]:04d}-{now[1]:02d}-{now[2]:02d}"

    if date_str not in sun_data:
        log("Could not find current date str in sundata {str}")
        return None, None
    
    sunrise = parse_time(sun_data.get(date_str, {}).get('sunrise', 'N/A'))
    sunset = parse_time(sun_data[date_str]['sunset'])

    return sunrise, sunset
# --- UART Interface ---

def send_uart(cmd, retry_count=0):
    if retry_count == 3:
        log(f"[ERROR] Command: '{cmd}' failed", False)
        return None
    uart.write((cmd + '\n').encode())
    time.sleep(0.2)

    timeout = time.ticks_ms() + 1000  # 1-second timeout
    response = b""
    while time.ticks_ms() < timeout:
        if uart.any():
            try:
                response += uart.read()
                if response.endswith(b'\n'):
                    break
            except Exception as e:
                log(f"[ERROR] UART read failed: {e}")
                break
        time.sleep(0.05)
    try:
        response=response.decode().strip()
        if not response or response == "unknown" or response == "":
            return send_uart(cmd, retry_count+1)
        else:
            log(response, False)
            return response
            
    except Exception as e:
        log(f"[ERROR] UART decode failed: {e}", False)
        return None

def fetch_motor_config():
    global motor_config
    resp = send_uart("config")
    try:
        motor_config = json.loads(resp)
    except Exception as e:
        log(f"[ERROR] Failed to load motor config: {motor_config} e: {e}")

# --- NETWORK ---
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
      wlan.connect(SSID, PASSWORD)
      timeout = 10
      while not wlan.isconnected() and timeout > 0:
          time.sleep(1)
          timeout -= 1
    return wlan.ifconfig()[0] if wlan.isconnected() else None

# --- DOOR AUTOMATION ---
def auto_check(now_sec, sunrise_sec, sunset_sec):
    global last_action_time, DOOR_STATE
    if now_sec - last_action_time < 300:
        return

    if sunrise_sec < now_sec < sunrise_sec + 600 and DOOR_STATE != "open":
        log("Opening door at sunrise", False)
        send_uart("open")
        last_action_time = now_sec
    elif sunset_sec < now_sec < sunset_sec + 600 and DOOR_STATE != "closed":
        send_uart("close")
        log("Closing door at sunset", False)
        last_action_time = now_sec

    # Failsafe logic
    if now_sec >= FAILSAFE_OPEN_TO_CLOSED and DOOR_STATE != "closed":
        log("[FAILSAFE] Closing door due to time fallback.")
        send_uart("close")
        last_action_time = now_sec
    elif now_sec >= FAILSAFE_CLOSED_TO_OPEN and DOOR_STATE != "open":
        log("[FAILSAFE] Opening door due to time fallback.")
        send_uart("open")
        last_action_time = now_sec
        
def max_cache_age_months(current_year, current_month):
    max_age = 0
    for fname in os.listdir(CACHE_DIR):
        try:
            y, m = map(int, fname.replace(".json", "").split("-"))
            age_months = (y - current_year) * 12 + (m - current_month)
            max_age = max(max_age, age_months)
        except Exception:
            continue
    return max_age
        
# --- WEB SERVER ---
def html_page():
    global FAILSAFE_OPEN_TO_CLOSED, FAILSAFE_CLOSED_TO_OPEN
    now = time.localtime()
    date_str = f"{now[0]:04d}-{now[1]:02d}-{now[2]:02d}"
    local_time_str = f"{now[3]:02d}:{now[4]:02d}:{now[5]:02d}"
    local_time_seconds = parse_time(local_time_str + " MIL")
    sun_data = load_sun_data()
    sunrise_seconds, sunset_seconds = today_times(sun_data)
    sunrise_str = sun_data.get(date_str, {}).get('sunrise', 'N/A')
    sunset_str = sun_data.get(date_str, {}).get('sunset', 'N/A')
    sunrise_sec, sunset_sec = today_times(sun_data)
    sync_time_str = last_ntp_sync_mday

    threshold = motor_config.get("current_threshold", "N/A")
    timeout_open = motor_config.get("move_timeout_open_ms", "N/A")
    timeout_close = motor_config.get("move_timeout_close_ms", "N/A")
    
    max_cache_age = max_cache_age_months(now[0], now[1])

    log_html = '<br>'.join(log_buffer[::-1])
    return f"""<!DOCTYPE html><html><body>
<h2>Auto Coop Door</h2>
<form action="/" method="get">
<button name="action" value="open">Open</button>
<button name="action" value="close">Close</button>
<button name="action" value="stop">Stop</button>
<button name="action" value="sync">Sync Time</button><br><br>
Current Threshold: <input name="threshold" type="number" value="{threshold}">
Timeout Open (ms): <input name="timeout_open" type="number" value="{timeout_open}">
Timeout Close (ms): <input name="timeout_close" type="number" value="{timeout_close}">
<button type="submit">Update Settings</button>
</form>
<p>Door: <b>{DOOR_STATE}</b></p>
<p>Current: <b>{current_draw_mv} mV</b></p>
<p>Local Date and Time: <b>{date_str} {local_time_str}</b></p>
<p>Local Time Seconds: <b>{local_time_seconds}</b></p>
<p>Closed to Open Threshold Seconds: <b>{FAILSAFE_CLOSED_TO_OPEN}</b></p>
<p>Open to Closed Threshold Seconds: <b>{FAILSAFE_OPEN_TO_CLOSED}</b></p>
<p>Sunrise: <b>{sunrise_str}</b></p>
<p>Sunrise in Seconds: <b>{sunrise_sec}</b></p>
<p>Sunset: <b>{sunset_str}</b></p>
<p>Sunset in Seconds: <b>{sunset_sec}</b></p>
<p>Last Sync Mday: <b>{sync_time_str}</b></p>
<p>Additional Cached Months: <b>{max_cache_age}</b></p>
<h3>Logs</h3><div style='font-family:monospace;'>{log_html}</div>
</body></html>"""

def serve():
    global DOOR_STATE, current_draw_mv
    addr = socket.getaddrinfo('0.0.0.0', 80)[0][-1]
    s = socket.socket()
    s.bind(addr)
    s.listen(1)
    log("[INFO] Web server started on port 80")
    while True:
        cl, addr = s.accept()
        req = cl.recv(1024).decode()

        if 'GET /?' in req:
            if 'action=open' in req:
                log("[INFO] Sending open", False)
                send_uart("open")
            elif 'action=close' in req:
                log("[INFO] Sending close", False)
                send_uart("close")
            elif 'action=stop' in req:
                log("[INFO] Sending stop", False)
                send_uart("stop")
            elif 'action=sync' in req:
                sync_time()
            #threshold = motor_config.get("current_threshold", "N/A")
            #timeout_open = motor_config.get("move_timeout_open_ms", "N/A")
            #timeout_close = motor_config.get("move_timeout_close_ms", "N/A")

            if 'threshold=' in req:
                try:
                    val = int(req.split("threshold=")[1].split("&")[0])
                    if val != motor_config.get("current_threshold"): send_uart(f"threshold:{val}")
                except: pass
            if 'timeout_open=' in req:
                try:
                    val = int(req.split("timeout_open=")[1].split("&")[0])
                    if val != motor_config.get("timeout_open"): send_uart(f"timeout_open:{val}")
                except: pass
            if 'timeout_close=' in req:
                try:
                    val = int(req.split("timeout_close=")[1].split("&")[0])
                    if val != motor_config.get("timeout_close"): send_uart(f":{val}")
                    send_uart(f"timeout_close:{val}")
                except: pass
            fetch_motor_config()

        elif 'GET /status' in req:
            cl.send("HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n")
            cl.send(json.dumps({"door": DOOR_STATE, "current_mv": current_draw_mv}))
            cl.close()
            continue

        cl.send("HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n")
        cl.sendall(html_page())
        cl.close()

# --- MAIN ---
def main():
    global DOOR_STATE, current_draw_mv
    ip = connect_wifi()
    if ip:
        log(f"[INFO] Connected to Wi-Fi: {ip}")
        sync_time()
        manage_cache()
    else:
        log("[WARN] Wi-Fi connection failed. Running in offline mode.")
    sun_data = load_sun_data()
    fetch_motor_config()
    log(f"[INFO] Web UI at http://{ip}")

    import _thread
    _thread.start_new_thread(serve, ())

    while True:
        connect_wifi()
        now = time.localtime()
        DOOR_STATE = send_uart("status")
        print("gatheringstatups")
        time.sleep(2)
        current_current = send_uart("current")
        time.sleep(2)
        if current_current: current_draw_mv = float(current_current)

        if now[3] > 3 and now[3] < 4:
            if last_ntp_sync_mday < now[2]:
              log(f"[INFO] Attempting scheduled time sync for mday {now[2]}")
              synced = sync_time()
              if not synced:
                  print("[WARN] Scheduled time sync failed")
              sync_time()
        manage_cache()
        sun_data = load_sun_data()
        now_sec = now[3]*3600 + now[4]*60 + now[5]
        sunrise_sec, sunset_sec = today_times(sun_data)
        if sunrise_sec and sunset_sec:
            auto_check(now_sec, sunrise_sec, sunset_sec)
        time.sleep(15)

main()
