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

from ds3231_gen import *
from motor_controller import MotorController
from current_sensor import CurrentSensor
from neo_pixel import NeoPixelController
from temperature_sensor import DS18B20Sensor
from relay_controller import Relay

DEBUG = True
log_buffer = []
MAX_LOG_LINES = 45
FAILSAFE=True
HTML_SERVER_RUNNING=False

FAILSAFE_OPEN_TO_CLOSED = 22 * 3600 + 30 * 60   # 10:30 PM
FAILSAFE_CLOSED_TO_OPEN = 8 * 3600             # 8:00 AM

wdt = machine.WDT(timeout=30000)

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

i2c_pins = {}
ibt_pins = {}
temp_pins = {}
relay_pins = {}
neo_pixel_pins = {}

try:
    i2c_pins = get_pins(motor_config, "i2c", ["sda", "sdc"])
    ibt_pins = get_pins(motor_config, "ibt", ["in1", "in2", "l_en", "r_en"])
    temp_pins = get_pins(motor_config, "temp", ["data"])
    relay_pins = get_pins(motor_config, "relay", ["light", "heat"])
    neo_pixel_pins = get_pins(motor_config, "pixel", ["din"])

    
except ValueError as e:
    print("Configuration error:", e)
    
#t-picoc3 i2c = I2C(0, sda=Pin(24), scl=Pin(21))
#i2c = I2C(0, sda=Pin(i2c_pins["sda"], Pin.OUT), scl=Pin(i2c_pins["sdc"], Pin.OUT), freq=10000) 
i2c = I2C(0, sda=Pin(i2c_pins["sda"]), scl=Pin(i2c_pins["sdc"]), freq=100000) 

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

np = NeoPixelController(neo_pixel_pins["din"], brightness=0.1)

rtc_ds = None
try:
    rtc_ds = DS3231(i2c)
    time.sleep(0.5)
    rtc_ds.get_time()
except Exception as e:
    rtc_ds = None
    log(f"[ERROR] RTC_DS init: {e}")
    print(f"[ERROR] RTC_DS init: {e}")
    sys.print_exception(e)

temp_ds = None
try:
    temp_ds = DS18B20Sensor(data_pin_num=temp_pins["data"])
except Exception as e:
    temp_ds = None
    log(f"[ERROR] TEMP_DS: {e}")
    print(f"[ERROR] TEMP_DS: {e}")
    sys.print_exception(e)

heat = None
light = None
heat = Relay("heat", relay_pins["heat"], False)
light = Relay("light", relay_pins["light"], False)


#for pin in relay_pins:

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
rtc_sys = RTC()

def sync_time():
    global config, LAST_NTP_SYNC_MDAY
    try:
        ntptime.settime()
        tm = time.localtime(time.time() + get_est_offset())
        rtc_sys.datetime((tm[0], tm[1], tm[2], tm[6], tm[3], tm[4], tm[5], 0))
        if rtc_ds: rtc_ds.set_time(tm)
        last_ntp_sync = f"{tm[0]:04d}-{tm[1]:02d}-{tm[2]:02d} {tm[3]:02d}:{tm[4]:02d}:{tm[5]:02d}"
        LAST_NTP_SYNC_MDAY = tm[2]
        log("[INFO] Time synced successfully")
        return True
    except Exception as e:
        log(f"[ERROR] NTP sync failed: {e}")
        return False
    
    
def restore_time_from_ds3231():
    tm = rtc_ds.get_time()  # (year, month, mday, hour, min, sec, wday, yday)
    rtc_sys.datetime((tm[0], tm[1], tm[2], tm[6], tm[3], tm[4], tm[5], 0))
    log("[INFO] System time restored from DS3231")
    
def run_motor_thread(action):
    motor_controller.safe_move(action, log)

# --- UART Interface ---
def send_uart(line, retry_count=0, log_response=True):
    if line in ("open", "close"):
            _thread.start_new_thread(run_motor_thread, (line,))
            return("ack\n")
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
    else:
        commands = [
            "current_threshold",
            "move_timeout_open_ms",
            "move_timeout_close_ms",
            "sun_seconds",
            "heat_toggle_temp",
        ]
        for key in commands:
            if line.startswith(f"{key}:"):
                try:
                    val = int(line.split(":", 1)[1])
                    motor_config[key] = val
                    globals()[key.upper()] = val
                    setattr(motor_controller, key.upper(), val)

                    with open(MOTOR_CONFIG_FILE, "w") as f:
                        json.dump(motor_config, f)
                    log(f"{key} updated\n")
                except Exception as e:
                    log(f"invalid {key}: {e}\n")
                break

# --- NETWORK ---
def connect_wifi(wifi):
    global HTML_SERVER_RUNNING
    if not wifi.isconnected():
      log("[INFO] attempting wifi connection")
      wifi.active(False)
      time.sleep(1)  # Give it a moment
      wifi.active(True)
      wifi.disconnect()
      time.sleep(0.5)
      wifi.connect(SSID, PASSWORD)
      timeout = 6
      while not wifi.isconnected() and timeout > 0:
          time.sleep(1)
          timeout -= 1
    if wifi.isconnected() and not HTML_SERVER_RUNNING:
        _thread.start_new_thread(serve, ())
        HTML_SERVER_RUNNING = True
        log(f"[INFO] Web UI starting at http://{wifi.ifconfig()[0]}")
    return wifi.ifconfig()[0] if wifi.isconnected() else None

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
    current_threshold = motor_config.get("current_threshold", "N/A")
    move_timeout_open_ms = motor_config.get("move_timeout_open_ms", "N/A")
    move_timeout_close_ms = motor_config.get("move_timeout_close_ms", "N/A")
    sun_seconds = motor_config.get("sun_seconds", "N/A")
    heat_toggle_temp = motor_config.get("heat_toggle_temp", "N/A")

    max_cache_age = max_cache_age_months(now[0], now[1])
    current_current = "N/A"
    if current_sensor:
        current_current = current_sensor.get_current_ma()
    heat_status = "ON" if heat.is_on() else "OFF"
    light_status = "ON" if light.is_on() else "OFF"

    log_html = '<br>'.join(log_buffer[::-1])
    internal_temperature = (esp32.mcu_temperature() * 9 / 5) + 32
    ds_temperature = (rtc_ds.temperature() * 9 / 5) + 32 if rtc_ds else None
    out_ds_temperature = temp_ds.read_fahrenheit() if temp_ds else None
    free_memory = gc.mem_free() / 1024
    return f"""<!DOCTYPE html><html><body>
<h2>Auto Coop Door</h2>
<form action="/" method="get">
<button name="action" value="open">Open</button>
<button name="action" value="close">Close</button>
<button name="action" value="stop">Stop</button>
<button name="action" value="sync">Sync Time</button>
<button name="action" value="failsafe">Toggle FAILSAFE from <b>{FAILSAFE}</b></button>
<button name="action" value="toggle_heat">Toggle Heat from <b>{heat_status}</b></button> 
<button name="action" value="toggle_light">Toggle Light from <b>{light_status}</b></button> 
<button name="action" value="reset">Reset()</button>
<br><br>
Current Threshold: <input name="current_threshold" type="number" value="{current_threshold}">
Timeout Open (ms): <input name="move_timeout_open_ms" type="number" value="{move_timeout_open_ms}">
Timeout Close (ms): <input name="move_timeout_close_ms" type="number" value="{move_timeout_close_ms}">
Seconds of daylight for light (ms): <input name="sun_seconds" type="number" value="{sun_seconds}">
Heat on below this temp: <input name="heat_toggle_temp" type="number" value="{heat_toggle_temp}">
<button type="submit" name="Update Settings" value="1">Update Settings</button>
</form>
<p>
MCU Temp: <b>{internal_temperature}F</b>
 DS3231 Temp: <b>{ds_temperature}F</b>
 DS18X20 Temp: <b>{out_ds_temperature}F</b>
</p>
<p>Last Reset:<b>{machine.reset_cause()}</b> Free Mem: <b>{free_memory}KB</b></p>
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
                    elif 'action=toggle_heat' in req:
                        heat.toggle()
                    elif 'action=toggle_light' in req:
                        light.toggle()
                    elif 'action=reset' in req:
                        machine.reset()
                    # Only update settings if submit button was clicked
                    if 'Update+Settings' in req:
                        for key in ["current_threshold", "move_timeout_open_ms", "move_timeout_close_ms", "heat_toggle_temp", "sun_seconds"]:
                            if f"{key}=" in req:
                                try:
                                    val = int(req.split(f"{key}=")[1].split("&")[0])
                                    if val != motor_config.get(key):
                                        send_uart(f"{key}:{val}")
                                except:
                                    pass                          
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
            time.sleep(2)
            failure_count+=1
    return False
    
        
async def check_serve_health(ip):
    if ip:
        if not serve_health_check(ip):
            log("log Website is down. Restarting...")
            machine.reset()
    
async def auto_door_check(now, sun_data):
    now_sec = now[3]*3600 + now[4]*60 + now[5]
    sunrise_sec, sunset_sec = today_times(sun_data)
    if sunrise_sec and sunset_sec:
        auto_check(now_sec, sunrise_sec, sunset_sec)
        
async def auto_temp_check(temp_relay):
    global temp_ds
    if temp_ds:
        current_temp = temp_ds.read_fahrenheit()
        if current_temp < motor_config["heat_toggle_temp"]:
            if not temp_relay.is_on():
                temp_relay.on()
        else:
            if temp_relay.is_on():
                temp_relay.off()
    
async def auto_light_check(now, light_relay, sun_data):
    now_seconds = now[3]*3600 + now[4]*60 + now[5]
    sunrise_sec, sunset_sec = today_times(sun_data)

    desired_daylight = motor_config["sun_seconds"]
    actual_daylight = sunset_sec - sunrise_sec

    if actual_daylight >= desired_daylight:
        # Enough natural light for the day, make sure relay is off
        if light_relay.is_on():
            light_relay.off()
        return

    extension = (desired_daylight - actual_daylight) // 2
    light_on_start_sunrise = sunrise_sec - extension
    light_on_end_sunrise = sunrise_sec + 300

    light_on_start_sunset = sunset_sec - 300
    light_on_end_sunset = sunset_sec + extension

    if (light_on_start_sunrise <= now_seconds < light_on_end_sunrise):
        if not light_relay.is_on():
            log(f"[INFO] Turning light on for sunrise supplement for {light_on_end-now_seconds} seconds")
            light_relay.on()
    elif (light_on_start_sunset <= now_seconds < light_on_end_sunset):
        if not light_relay.is_on():
            log(f"[INFO] Turning light on for sunset supplement for {light_on_end_sunset-now_seconds} seconds")
            light_relay.on()

        
async def task_time_sync(now):
    if now[3] > 3:
        if LAST_NTP_SYNC_MDAY < now[2]:
          log(f"[INFO] Attempting scheduled time sync for mday {now[2]}")
          sync_time()
          
async def main():
    print(f"Startup, last reset cause: {machine.reset_cause()}")
    wdt.feed()
    if rtc_ds: restore_time_from_ds3231()
    np.show_color((255,0,0))
    ip = None
    wlan = network.WLAN(network.STA_IF)
    try:
        ip = connect_wifi(wlan)
        if ip:
            log(f"[INFO] Connected to Wi-Fi: {ip}")
            print(f"[INFO] Connected to Wi-Fi: {ip}")
            sync_time()
            await manage_cache(time.localtime(), LAT, LNG, log)

        else:
            log(f"[WARN] Wi-Fi connection failed. Running in offline mode. {wlan.status()}")
            #wlan.ifconfig(('192.168.6.152', '255.255.255.0', '192.168.1.1', '8.8.8.8'))
    except Exception as e:
        log(f"[ERROR] Cannot initilize wifi: {e}")
        print(f"[ERROR] Cannot initilize wifi: {e}")
        sys.print_exception(e)

    time.sleep(5)
    if DEBUG:
        try:
            if rtc_ds: print(f"rtc_ds {rtc_ds.temperature()}")
            if current_sensor: print(f"current_sensor {current_sensor.get_current_ma()}")
            if temp_ds: print(f"temp_ds: {temp_ds.read_fahrenheit()}")
        except Exception as e:
            log(f"[ERROR] Debug Sensor: {e}")
            print(f"[ERROR] Debug Sensor: {e}")
            sys.print_exception(e)

    while True:
        np.random_color()
        try:
            wdt.feed()
            #await update_status()
            now = time.localtime()
            sun_data = load_sun_data()

            tasks = [
                auto_door_check(now, sun_data),
                auto_temp_check(heat),
                auto_light_check(now, light,sun_data)
                ]
            if ip:
                tasks.extend([
                task_time_sync(now),
                manage_cache(now, LAT, LNG, log),
                check_serve_health(ip)])
            
            await asyncio.gather(*tasks)
            ip = connect_wifi(wlan)
            await asyncio.sleep(7)
        

        except MemoryError:
            machine.reset()
        except Exception as e:
            log(f"[ERROR] Unexpected: {e}")
            print(f"[ERROR] Unexpected: {e}")
            sys.print_exception(e)
            await asyncio.sleep(7)
asyncio.run(main())