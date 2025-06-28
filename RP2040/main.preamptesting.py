# RP2040 SIDE: Motor Control, Obstruction Detection, UART Slave

from machine import Pin, ADC, PWM, UART
import time
import random
import st7789
import tft_config
import vga1_bold_16x32 as font
import json
import _thread

# --- CONFIGURATION ---
CONFIG_FILE = "motor_config.json"
def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)

config = load_config()
CURRENT_THRESHOLD = config.get("current_threshold", 500)
MOVE_TIMEOUT_OPEN_MS = config.get("move_timeout_open_ms", 4000)
MOVE_TIMEOUT_CLOSE_MS = config.get("move_timeout_close_ms", 4000)

# UART from ESP32
uart = UART(1, baudrate=38400, tx=Pin(8), rx=Pin(9), cts=Pin(10), rts=Pin(11))

# Motor pins
IN1 = PWM(Pin(14))
IN2 = PWM(Pin(15))
PWM_FREQ = 1000
IN1.freq(PWM_FREQ)
IN2.freq(PWM_FREQ)

# Current sensor
CURRENT_SENSOR = ADC(Pin(26))
CURRENT_SCALE = 3.3 / 65535 * 1000

# State
door_state = "unknown"
current_mv = 0
motor_busy = False

# Logging
def log(msg):
    timestamp = time.localtime()
    entry = f"[{timestamp[1]}/{timestamp[2]} {timestamp[3]:02}:{timestamp[4]:02}:{timestamp[5]:02}] {msg}"
    print(entry)

# --- Motor ---
def motor_stop():
    IN1.duty_u16(0)
    IN2.duty_u16(0)

def motor_open():
    IN1.duty_u16(50000)
    IN2.duty_u16(0)

def motor_close():
    IN1.duty_u16(0)
    IN2.duty_u16(50000)

def read_current_mv():
    raw = CURRENT_SENSOR.read_u16()
    mv = raw * CURRENT_SCALE
    return round(mv, 2)

def safe_move(action):
    global current_mv, door_state, motor_busy
    motor_busy = True
    move_func = motor_open if action == 'open' else motor_close
    retries = 0

    while retries < 3:
        move_func()
        start = time.ticks_ms()
        obstructed = False

        timeout = MOVE_TIMEOUT_OPEN_MS if action == 'open' else MOVE_TIMEOUT_CLOSE_MS
        while time.ticks_diff(time.ticks_ms(), start) < timeout:
            current_mv = read_current_mv()
            if current_mv > CURRENT_THRESHOLD:
                motor_stop()
                time.sleep(0.5)
                motor_open() if action == 'close' else motor_close()
                time.sleep(1)
                motor_stop()
                obstructed = True
                break
            time.sleep(0.1)

        motor_stop()

        if not obstructed:
            door_state = 'open' if action == 'open' else 'closed'
            motor_busy = False
            return

        retries += 1
    motor_busy = False

def cycle(p):
    try:
        len(p)
    except TypeError:
        cache = []
        for i in p:
            yield i
            cache.append(i)
        p = cache
    while p:
        yield from p

# --- TFT Setup ---
tft = tft_config.config(0)
tft.init()
tft.fill(st7789.BLACK)
colors = cycle([0xe000, 0xece0, 0xe7e0, 0x5e0, 0x00d3, 0x7030])
foreground = next(colors)
background = st7789.BLACK
height = tft.height()
width = tft.width()
last_line = height - font.HEIGHT
tfa = tft_config.TFA
bfa = tft_config.BFA
tft.vscrdef(tfa, height, bfa)
scroll = 0
font_height = font.HEIGHT
next_line = (scroll + last_line) % height

def log_tft(line):
    global scroll, next_line, foreground
    scroll = scroll+30
    tft.text(font, '{}'.format(line), 32, next_line, foreground, background)
    tft.fill_rect(0, scroll, width, 1, background)
    if scroll % font.HEIGHT == 0:
        next_line = (scroll + last_line) % height
    foreground = next(colors)

def run_motor_thread(action):
    safe_move(action)
    uart.write("ok\n")

# --- UART Command Loop ---
log_tft("Gogogogo")
while True:
    tft.vscsad(scroll + tfa)
    scroll += 1
    scroll %= height
    time.sleep(0.05)
    
    if uart.any():
        timeout = time.ticks_ms() + 1000  # 1-second timeout
        response = b""
        while time.ticks_ms() < timeout:
                try:
                    response += uart.read()
                    if response.endswith(b'\n'):
                        break
                except Exception as e:
                    log(f"[ERROR] UART read failed: {e}")
                    break
        time.sleep(0.05)
        try:
            line = response.decode().strip()
            log(f"[UART] {line}")
            log_tft(f"{line}")

            if line in ("open", "close"):
                if motor_busy:
                    uart.write("busy\n")
                    log(f"[UART] busy returned")
                    log_tft(f"busy")
                
                else:
                    _thread.start_new_thread(run_motor_thread, (line,))
            elif line == "stop":
                motor_stop()
                uart.write("stopped\n")
            elif line == "status":
                uart.write(f"{door_state}\n")
            elif line == "current":
                current_mv = read_current_mv()
                uart.write(f"{current_mv}\n")
            elif line == "config":
                uart.write(json.dumps(config) + "\n")
                log("Sending config:" + json.dumps(config) + "\n") 
                
            elif line.startswith("threshold:"):
                try:
                    val = int(line.split(":")[1])
                    config["current_threshold"] = val
                    CURRENT_THRESHOLD = val
                    with open(CONFIG_FILE, "w") as f:
                        json.dump(config, f)
                    uart.write("threshold updated\n")
                except:
                    uart.write("invalid threshold\n")
            elif line.startswith("timeout_open:"):
                try:
                    val = int(line.split(":")[1])
                    config["move_timeout_open_ms"] = val
                    MOVE_TIMEOUT_OPEN_MS = val
                    with open(CONFIG_FILE, "w") as f:
                        json.dump(config, f)
                    uart.write("timeout open updated\n")
                except:
                    uart.write("invalid timeout open\n")
            elif line.startswith("timeout_close:"):
                try:
                    val = int(line.split(":")[1])
                    config["move_timeout_close_ms"] = val
                    MOVE_TIMEOUT_CLOSE_MS = val
                    with open(CONFIG_FILE, "w") as f:
                        json.dump(config, f)
                    uart.write("timeout close updated\n")
                except:
                    uart.write("invalid timeout close\n")
        except Exception as e:
            log(f"[ERROR] UART decode failed: {e}")
    tft.vscsad(scroll + tfa)
    scroll += 1
    scroll %= height
    time.sleep(0.05)


