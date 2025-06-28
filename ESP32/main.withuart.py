# ESP32 SIDE: Wi-Fi, Scheduler, Web UI, UART Master

import network, socket, time, urequests, machine, json, os, ntptime
from machine import UART, RTC, WDT, Timer
import _thread
from time_utils import is_dst, get_est_offset, parse_time, today_times
from sun_data_utils import build_month_cache, load_sun_data, manage_cache, max_cache_age_months
import uasyncio as asyncio


# --- LOGGING BUFFER ---
log_buffer = []
MAX_LOG_LINES = 15
FAILSAFE=True

motor_config = {}

FAILSAFE_OPEN_TO_CLOSED = 22 * 3600 + 30 * 60   # 10:30 PM
FAILSAFE_CLOSED_TO_OPEN = 8 * 3600             # 8:00 AM

# Initialize watchdog with 30s timeout
wdt = machine.WDT(timeout=30000)

# Track recent door action status with a timer flag
recent_action_flag = False
recent_action_timer = None

def reset_recent_action_flag(_=None):
    global recent_action_flag
    recent_action_flag = False
    log("[TIMER] Cooldown expired - actions allowed again.")

def start_recent_action_timer():
    global recent_action_flag, recent_action_timer
    recent_action_flag = True

    if recent_action_timer:
        recent_action_timer.deinit()

    recent_action_timer = Timer(0)  # or Timer(1)
    recent_action_timer.init(mode=Timer.ONE_SHOT, period=240_000, callback=reset_recent_action_flag)  # 4 min

def log(msg):
    timestamp = time.localtime()
    entry = f"[{timestamp[1]}/{timestamp[2]} {timestamp[3]:02}:{timestamp[4]:02}:{timestamp[5]:02}] {msg}"
    #print(entry)
    #if send_uart_log: send_uart(f"log {msg}")
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

# UART to RP2040
#uart = UART(1, baudrate=38400, tx=7, rx=6, cts=5, rts=4)

# Global state
DOOR_STATE = "unknown"
current_draw_mv = 0
last_action_time = 0
LAST_NTP_SYNC_MDAY = 0
rtc = RTC()

# --- TIME SYNC ---
def sync_time():
    global config, LAST_NTP_SYNC_MDAY
    try:
        ntptime.settime()
        tm = time.localtime(time.time() + get_est_offset())
        rtc.datetime((tm[0], tm[1], tm[2], tm[6], tm[3], tm[4], tm[5], 0))
        last_ntp_sync = f"{tm[0]:04d}-{tm[1]:02d}-{tm[2]:02d} {tm[3]:02d}:{tm[4]:02d}:{tm[5]:02d}"
        LAST_NTP_SYNC_MDAY = tm[2]
        log("[INFO] Time synced successfully")
        return True
    except Exception as e:
        log(f"[ERROR] NTP sync failed: {e}")
        return False

# --- UART Interface ---


def send_uart(cmd, retry_count=0, log_response=True):
    return "ack\n"



# def send_uart(cmd, retry_count=0, log_response=True):
#     if retry_count == 3:
#         log(f"[ERROR] Command: '{cmd}' failed")
#         return None
#     uart.write((cmd + '\n').encode())
#     time.sleep(0.2)
# 
#     timeout = time.ticks_ms() + 1000  # 1-second timeout
#     response = b""
#     while time.ticks_ms() < timeout:
#         if uart.any():
#             try:
#                 response += uart.read()
#                 if response.endswith(b'\n'):
#                     break
#             except Exception as e:
#                 log(f"[ERROR] UART read failed: {e}")
#                 break
#         time.sleep(0.05)
#     try:
#         response=response.decode().strip()
#         if not response:
#             return send_uart(cmd, retry_count+1)
#         else:
#             if log_response: log(f"[UART] cmd: {cmd} reply: {response}")
#             return response
#             
#     except Exception as e:
#         log(f"[ERROR] UART decode failed: {e}")
#         return None

def fetch_motor_config():
    global motor_config
    #resp = send_uart("config")
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
    global recent_action_flag, DOOR_STATE, FAILSAFE
    OPEN_STATE="open"
    CLOSE_STATE="close"

    if recent_action_flag:
        return
    #open 10 minutes before or after sunrise
    if sunrise_sec - 600 < now_sec < sunrise_sec + 600 and DOOR_STATE != OPEN_STATE:
        log("Opening door at sunrise")
        start_recent_action_timer()
        send_uart(OPEN_STATE)
    #close 10-20 minutes after sunset
    elif sunset_sec + 600 < now_sec < sunset_sec + 1200 and DOOR_STATE != CLOSE_STATE:
        log("Closing door at sunset")
        start_recent_action_timer()
        send_uart(CLOSE_STATE)
    # Failsafe logic
    if FAILSAFE:
        if ((now_sec >= FAILSAFE_OPEN_TO_CLOSED and DOOR_STATE != CLOSE_STATE)
            or (now_sec < sunrise_sec - 600 and DOOR_STATE != CLOSE_STATE)):
            log("[FAILSAFE] Closing door due to time fallback.")
            start_recent_action_timer()
            send_uart(CLOSE_STATE)
        elif FAILSAFE_CLOSED_TO_OPEN <= now_sec < sunset_sec and DOOR_STATE != OPEN_STATE:
            log("[FAILSAFE] Opening door due to time fallback.")
            start_recent_action_timer()
            send_uart(OPEN_STATE)
            start_recent_action_timer()

# --- HTML PAGE ---
def html_page():
    now = time.localtime()
    date_str = f"{now[0]:04d}-{now[1]:02d}-{now[2]:02d}"
    local_time_str = f"{now[3]:02d}:{now[4]:02d}:{now[5]:02d}"
    local_time_seconds = parse_time(local_time_str + " MIL")
    sun_data = load_sun_data()
    sunrise_seconds, sunset_seconds = today_times(sun_data)
    sunrise_str = sun_data.get(date_str, {}).get('sunrise', 'N/A')
    sunset_str = sun_data.get(date_str, {}).get('sunset', 'N/A')
    sync_time_str = LAST_NTP_SYNC_MDAY
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
<button name="action" value="sync">Sync Time</button>
<button name="action" value="failsafe">Toggle FAILSAFE</button>
<br><br>
Current Threshold: <input name="threshold" type="number" value="{threshold}">
Timeout Open (ms): <input name="timeout_open" type="number" value="{timeout_open}">
Timeout Close (ms): <input name="timeout_close" type="number" value="{timeout_close}">
<button type="submit" name="Update Settings" value="1">Update Settings</button>
</form>
<p>Door: <b>{DOOR_STATE}</b></p>
<p>Current: <b>{current_draw_mv} mV</b></p>
<p>Local Date and Time: <b>{date_str} {local_time_str}</b></p>
<p>Local Time Seconds: <b>{local_time_seconds}</b></p>
<p>Sunrise (Door opens between 10m before and 10m after): <b>{sunrise_str}</b></p>
<p>Sunset (Door closes between 10-20m after): <b>{sunset_str}</b></p>
<p>Closed to Open Threshold Seconds: <b>{FAILSAFE_CLOSED_TO_OPEN}</b></p>
<p>Open to Closed Threshold Seconds: <b>{FAILSAFE_OPEN_TO_CLOSED}</b></p>
<p>Recent Action Cooldown: <b>{recent_action_flag}</b></p>
<p>Failsafe: <b>{FAILSAFE}</b></p>

<p>Last Sync Mday: <b>{sync_time_str}</b></p>
<p>Additional Cached Months: <b>{max_cache_age}</b></p>

<h3>Logs</h3><div style='font-family:monospace;'>{log_html}</div>
</body></html>"""

# --- WEB SERVER MODIFICATION ---
def serve():
    global DOOR_STATE, current_draw_mv, FAILSAFE
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
                log("[INFO] Sending open")
                send_uart("open")
            elif 'action=close' in req:
                log("[INFO] Sending close")
                send_uart("close")
            elif 'action=stop' in req:
                log("[INFO] Sending stop")
                send_uart("stop")
            elif 'action=sync' in req:
                sync_time()
            elif 'action=failsafe' in req:
                FAILSAFE = not FAILSAFE
            # Only update settings if submit button was clicked
            if 'Update+Settings' in req:
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
                        if val != motor_config.get("timeout_close"): send_uart(f"timeout_close:{val}")
                    except: pass
                fetch_motor_config()
            cl.send("HTTP/1.0 302 Found\r\nLocation: /\r\n\r\n")

        elif 'GET /status' in req:
            cl.send("HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n")
            cl.send(json.dumps({"door": DOOR_STATE, "current_mv": current_draw_mv}))
            cl.close()
            continue

        elif 'GET /ping' in req:
            cl.send("HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\n")
            cl.send("pong")
            cl.close()
            continue

        cl.sendall(html_page())
        cl.close()
        
def serve_health_check(ip):
    failure_count = 0
    while True:
        try:
            sock = socket.socket()
            sock.settimeout(3)
            sock.connect((ip, 80))
            sock.send(b"GET /ping HTTP/1.1\r\nHost: %s\r\n\r\n" % ip.encode())
            response = sock.recv(1024)
            sock.close()

            if b"200 OK" in response:
                return True
            else:
                return False
        except Exception as e:
            return False
        
async def check_serve_health():
    ip = connect_wifi()
    if ip:
        if not serve_health_check(ip):
            send_uart("log Website is down. Restarting...")
            machine.reset()
            
async def update_status():
    global DOOR_STATE, current_draw_mv
    DOOR_STATE = send_uart("status", 0, False)
    asyncio.sleep(2)
    current_current = send_uart("current", 0, False)
    asyncio.sleep(2)
    if current_current: current_draw_mv = float(current_current)
    
async def auto_door_check(now):
    sun_data = load_sun_data()
    now_sec = now[3]*3600 + now[4]*60 + now[5]
    sunrise_sec, sunset_sec = today_times(sun_data)
    if sunrise_sec and sunset_sec:
        auto_check(now_sec, sunrise_sec, sunset_sec)
        
async def task_time_sync(now):
    if now[3] > 3:
        if LAST_NTP_SYNC_MDAY < now[2]:
          log(f"[INFO] Attempting scheduled time sync for mday {now[2]}")
          sync_time()

# --- MAIN ---
async def main():
    global DOOR_STATE, current_draw_mv
    wdt.feed()
    ip = connect_wifi()
    if ip:
        log(f"[INFO] Connected to Wi-Fi: {ip}")
        print(f"[INFO] Connected to Wi-Fi: {ip}")
        sync_time()
        await manage_cache()
    else:
        log("[WARN] Wi-Fi connection failed. Running in offline mode.")
    log(f"[INFO] Web UI at http://{ip}")
    #UARTfetch_motor_config()

    import _thread
    _thread.start_new_thread(serve, ())
    time.sleep(5)

    while True:
        try:
            wdt.feed()
            await update_status()
            now = time.localtime()
            tasks = [
                auto_door_check(now),
                task_time_sync(now),
                manage_cache(),
                check_serve_health()
            ]
            await asyncio.gather(*tasks)
            await asyncio.sleep(15)

        except MemoryError:
            machine.reset()
        except Exception as e:
            log(f"[ERROR] Unexpected: {e}")

asyncio.run(main())