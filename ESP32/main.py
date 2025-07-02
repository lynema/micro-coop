# ESP32 SIDE: Wi-Fi, Scheduler, Web UI, UART Master
import network, socket, time, urequests, machine, json, os, ntptime
from machine import UART, RTC, WDT, Timer, I2C, Pin, PWM
import _thread
from time_utils import is_dst, get_est_offset, parse_time, today_times
from sun_data_utils import build_month_cache, load_sun_data, manage_cache, max_cache_age_months
import uasyncio as asyncio
import sys
import esp32
import gc

from motor_controller import MotorController
from current_sensor import CurrentSensor
from neo_pixel import NeoPixelController

# --- LOGGING BUFFER ---
log_buffer = []
MAX_LOG_LINES = 45
FAILSAFE=True
HTML_SERVER_RUNNING=False

FAILSAFE_OPEN_TO_CLOSED = 22 * 3600 + 30 * 60   # 10:30 PM
FAILSAFE_CLOSED_TO_OPEN = 8 * 3600             # 8:00 AM

wdt = machine.WDT(timeout=90000)

# Track recent door action status with a timer flag
recent_action_flag = False
recent_action_timer = None

def disable_deep_sleep():
    machine.deepsleep(0)  # Disable deep sleep completely in this case

def log(msg):
    timestamp = time.localtime()
    entry = f"[{timestamp[1]}/{timestamp[2]} {timestamp[3]:02}:{timestamp[4]:02}:{timestamp[5]:02}] {msg}"
    print(entry)
    #if send_uart_log: send_uart(f"log {msg}")
    log_buffer.append(entry)
    if len(log_buffer) > MAX_LOG_LINES:
        log_buffer.pop(0)

CONFIG_FILE = "config.json"
MOTOR_CONFIG_FILE = "motor_config.json"
def load_config(file):
    with open(file) as f:
        cfg = json.load(f)
    return cfg

config = load_config(CONFIG_FILE)
motor_config = load_config(MOTOR_CONFIG_FILE)
LAT, LNG = config["latitude"], config["longitude"]
SSID, PASSWORD = config["ssid"], config["password"]

def get_pins(config, device, required_keys):
    device_pins = config.get("pin", {}).get(device)
    if not device_pins:
        raise ValueError(f"Device '{device}' not found in pin config")
    
    pins = {}
    for key in required_keys:
        if key not in device_pins:
            raise ValueError(f"Missing pin '{key}' for device '{device}'")
        pins[key] = device_pins[key]
    return pins

ina_pins = {}
ibt_pins = {}

try:
    ina_pins = get_pins(motor_config, "ina", ["sda", "sdc"])
    ibt_pins = get_pins(motor_config, "ibt", ["in1", "in2", "l_en", "r_en"])
except ValueError as e:
    print("Configuration error:", e)
    
#t-picoc3 i2c = I2C(0, sda=Pin(24), scl=Pin(21))
i2c = I2C(0, sda=Pin(ina_pins["sda"], Pin.OUT), scl=Pin(ina_pins["sdc"], Pin.OUT), freq=10000) 
current_sensor = None
try:
    current_sensor = CurrentSensor(i2c)
except OSError as e:
    log(f"[ERROR] Configuration error with current sensor: {e}")
    
motor_controller = MotorController(
    #t-picoc3 in1_pin=14, in2_pin=15, l_en_pin=16, r_en_pin=17,
    in1_pin=ibt_pins["in1"], in2_pin=ibt_pins["in2"], l_en_pin=ibt_pins["l_en"], r_en_pin=ibt_pins["r_en"], 
    current_sensor=current_sensor, move_timeout_open_ms=motor_config["move_timeout_open_ms"],
    move_timeout_close_ms=motor_config["move_timeout_close_ms"], current_threshold=motor_config["current_threshold"]
)

np = NeoPixelController(brightness=0.1)

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

# UART to RP2040 #uart = UART(1, baudrate=38400, tx=7, rx=6, cts=5, rts=4)

LAST_NTP_SYNC_MDAY = 0
rtc = RTC()

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
    
def run_motor_thread(action):
    motor_controller.safe_move(action, log)

# --- UART Interface ---
def send_uart(line, retry_count=0, log_response=True):
    if line in ("open", "close"):
            _thread.start_new_thread(run_motor_thread, (line,))
            log("ack\n")
    elif line == "stop":
        motor_controller.motor_stop()
        return ("ack\n")
    elif line == "status":
        return (f"{motor_controller.door_state}\n")
    elif line == "current":
        current_mv = current_sensor.get_current_ma()
        return (f"{current_mv}\n")
    elif line == "config":
        return (json.dumps(MOTOR_CONFIG_FILE) + "\n")
    elif line.startswith("threshold:"):
        try:
            val = int(line.split(":")[1])
            motor_config["current_threshold"] = val
            CURRENT_THRESHOLD = val
            with open(MOTOR_CONFIG_FILE, "w") as f:
                json.dump(motor_config, f)
            motor_controller.CURRENT_THRESHOLD = val
            log("threshold updated\n")
        except:
            log("invalid threshold\n")
    elif line.startswith("timeout_open:"):
        try:
            val = int(line.split(":")[1])
            motor_config["move_timeout_open_ms"] = val
            MOVE_TIMEOUT_OPEN_MS = val
            with open(MOTOR_CONFIG_FILE, "w") as f:
                json.dump(motor_config, f)
            motor_controller.MOVE_TIMEOUT_OPEN_MS = val

            log("timeout open updated\n")
        except:
            log("invalid timeout open\n")
    elif line.startswith("timeout_close:"):
        try:
            val = int(line.split(":")[1])
            motor_config["move_timeout_close_ms"] = val
            MOVE_TIMEOUT_CLOSE_MS = val
            with open(MOTOR_CONFIG_FILE, "w") as f:
                json.dump(motor_config, f)
            motor_controller.MOVE_TIMEOUT_CLOSE_MS = val
            log("timeout close updated\n")
        except:
            log("invalid timeout close\n")

# --- NETWORK ---
def connect_wifi():
    global HTML_SERVER_RUNNING
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
      wlan.connect(SSID, PASSWORD)
      timeout = 10
      while not wlan.isconnected() and timeout > 0:
          time.sleep(1)
          timeout -= 1
    if wlan.isconnected() and not HTML_SERVER_RUNNING:
        import _thread
        _thread.start_new_thread(serve, ())
        HTML_SERVER_RUNNING = True
    return wlan.ifconfig()[0] if wlan.isconnected() else None

# --- DOOR AUTOMATION ---
def auto_check(now_sec, sunrise_sec, sunset_sec):
    global recent_action_flag, FAILSAFE
    OPEN_STATE="open"
    CLOSE_STATE="close"
    
    door_state = motor_controller.door_state
    if recent_action_flag:
        return
    #open 10 minutes before or after sunrise
    if sunrise_sec - 600 < now_sec < sunrise_sec + 600 and door_state != OPEN_STATE:
        log("Opening door at sunrise")
        start_recent_action_timer()
        send_uart(OPEN_STATE)
    #close 10-20 minutes after sunset
    elif sunset_sec + 600 < now_sec < sunset_sec + 1200 and door_state != CLOSE_STATE:
        log("Closing door at sunset")
        start_recent_action_timer()
        send_uart(CLOSE_STATE)
    # Failsafe logic
    if FAILSAFE:
        if ((now_sec >= FAILSAFE_OPEN_TO_CLOSED and door_state != CLOSE_STATE)
            or (now_sec < sunrise_sec - 600 and door_state != CLOSE_STATE)):
            log("[FAILSAFE] Closing door due to time fallback.")
            start_recent_action_timer()
            send_uart(CLOSE_STATE)
        elif FAILSAFE_CLOSED_TO_OPEN <= now_sec < sunset_sec and door_state != OPEN_STATE:
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
    current_current = "N/A"
    if current_sensor:
        current_current = current_sensor.get_current_ma()
    log_html = '<br>'.join(log_buffer[::-1])
    internal_temperature = (esp32.mcu_temperature() * 9 / 5) + 32
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
<p>MCU Temp: <b>{internal_temperature}F</b> Last Reset:<b>{machine.reset_cause()}</b> Free Mem: <b>{gc.mem_free()}</b></p>
<p>Door: <b>{motor_controller.door_state}</b></p>
<p>Current Current: <b>{current_current} mV</b></p>
<p>Last Highest Average Current:<b> {motor_controller.last_higest_average_mv} mV</b></p>
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

# Read the PNG file and print out the byte data
with open("favicon.ico", "rb") as f:
    favicon_data = f.read()

# --- WEB SERVER MODIFICATION ---
def serve():
    s = socket.socket()
    try:
        global FAILSAFE
        addr = socket.getaddrinfo('0.0.0.0', 80)[0][-1]
        s.bind(addr)
        s.listen(1)
        log("[INFO] Web server started on port 80")
        while True:
            cl, addr = s.accept()
            try:
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
                        #fetch_motor_config()
                    cl.send("HTTP/1.0 302 Found\r\nLocation: /\r\n\r\n")
                    continue

                elif 'GET /status' in req:
                    cl.send("HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n")
                    cl.send(json.dumps({"door": motor_controller.door_state, "current_mv": current_sensor.get_current_ma()}))
                    continue

                elif 'GET /ping' in req:
                    cl.send("HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\npong")
                    continue
                elif 'GET /favicon.ico' in req:
                    # Send the ICO data with caching headers
                    cl.send(b"HTTP/1.1 200 OK\r\n")
                    cl.send(b"Content-Type: image/x-icon\r\n")
                    cl.send(b"Cache-Control: public, max-age=31536000\r\n")  # Cache for 1 year
                    cl.send(b"Connection: close\r\n\r\n")
                    cl.send(favicon_data)
                    continue
                cl.sendall(html_page())
            finally:
                cl.close()
    except Exception as e:
        log(f"[ERROR] Serve crashed: {e}")
        sys.print_exception(e)
    finally:
        s.close()  # Always close the socket when done        
        
def serve_health_check(ip):
    failure_count = 0
    while failure_count < 3:
        try:
            sock = socket.socket()
            sock.settimeout(3)
            sock.connect((ip, 80))
            sock.send(b"GET /ping HTTP/1.1\r\nHost: %s\r\n\r\n" % ip.encode())
            response = sock.recv(1024)
            #print(f"response {response}")
            sock.close()
            if b"pong" in response:
                return True
        except Exception as e:
            return False
        finally:
            asyncio.sleep(2)
            failure_count+=1
    return False
    
        
async def check_serve_health():
    ip = connect_wifi()
    if ip:
        if not serve_health_check(ip):
            log("log Website is down. Restarting...")
            machine.reset()
    
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
    print(f"Startup, last reset cause: {machine.reset_cause()}")
    wdt.feed()
    #disable_deep_sleep()
    np.show_color((255,0,0))
    ip = connect_wifi()
    if ip:
        log(f"[INFO] Connected to Wi-Fi: {ip}")
        print(f"[INFO] Connected to Wi-Fi: {ip}")
        sync_time()
        await manage_cache(time.localtime(), LAT, LNG, log)

    else:
        log("[WARN] Wi-Fi connection failed. Running in offline mode.")
    log(f"[INFO] Web UI at http://{ip}")
    #fetch_motor_config()

    time.sleep(5)


    while True:
        np.random_color()
        ip = connect_wifi()
        try:
            wdt.feed()
            #await update_status()
            now = time.localtime()
            tasks = [
                auto_door_check(now),
                task_time_sync(now),
                manage_cache(now, LAT, LNG, log),
                check_serve_health()
            ]
            await asyncio.gather(*tasks)
            await asyncio.sleep(5)

        except MemoryError:
            machine.reset()
        except Exception as e:
            log(f"[ERROR] Unexpected: {e}")
            print(f"[ERROR] Unexpected: {e}")
            sys.print_exception(e)
asyncio.run(main())