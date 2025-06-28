# RP2040 SIDE: Motor Control, Obstruction Detection, UART Slave

from machine import Pin, PWM, UART, I2C, WDT
import time
import random
import st7789py
import tft_config
import vga1_16x16 as font
import json
import _thread
from ina219 import INA219
import uasyncio as asyncio
from motor_utils import safe_move, motor_stop, motor_open, motor_close

# --- CONFIGURATION ---
CONFIG_FILE = "motor_config.json"
def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)

config = load_config()
CURRENT_THRESHOLD = config.get("current_threshold", 900)
MOVE_TIMEOUT_OPEN_MS = config.get("move_timeout_open_ms", 40000)
MOVE_TIMEOUT_CLOSE_MS = config.get("move_timeout_close_ms", 40000)
CURRENT_IDLE_THRESHOLD = 5  # mA

# UART from ESP32
uart = UART(1, baudrate=38400, tx=Pin(8), rx=Pin(9), cts=Pin(10), rts=Pin(11))

# Motor pins
IN1 = PWM(Pin(14))
IN2 = PWM(Pin(15))
L_EN = Pin(16, Pin.OUT)
R_EN = Pin(17, Pin.OUT)
PWM_FREQ = 1000

IN1.freq(PWM_FREQ)
IN2.freq(PWM_FREQ)



# State
door_state = "unknown"
current_mv = 0
motor_busy = False

# Initialize watchdog with max rp2040 timeout
wdt = WDT(timeout=8388)

# INA219 setup
i2c = I2C(0, sda=Pin(24), scl=Pin(21))
ina = INA219(i2c)

def read_current_ma():
    try:
        return ina.current
    except:
        return 0.0

def log(msg):
    timestamp = time.localtime()
    entry = f"[{timestamp[1]}/{timestamp[2]} {timestamp[3]:02}:{timestamp[4]:02}:{timestamp[5]:02}] {msg}"
    log_tft(entry)


def send(msg):
    uart.write(msg)


def log_and_send(msg, uart_write=True):
    log(msg)
    if uart_write:
        send(msg)

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
tft.rotation(1)  # Landscape

colors = cycle([0xe000, 0xece0, 0xe7e0, 0x5e0, 0x00d3, 0x7030])
foreground = next(colors)
background = st7789py.BLACK
tft.fill(background)

height = tft.height
width = tft.width
last_line = height - font.HEIGHT
log_buffer = ["", "", "", ""]
tfa = tft_config.TFA
bfa = tft_config.BFA
tft.vscrdef(tfa, height, bfa)
scroll = 0
font_height = font.HEIGHT
next_line = (scroll + last_line) % height


def log_tft(line):
    global scroll, next_line, foreground, log_buffer, font, width
    wrapped_lines = []
    max_chars = (width - 32) // font.WIDTH
    while len(line) > max_chars:
        wrapped_lines.append(line[:max_chars])
        line = line[max_chars:]
    wrapped_lines.append(line)

    for w in wrapped_lines:
        log_buffer.append(w)
    if len(log_buffer) > 6:
        log_buffer = log_buffer[-6:]

    tft.fill(background)
    y = 0
    for l in log_buffer:
        tft.text(font, l, 32, y, foreground, background)
        y += font.HEIGHT
    foreground = next(colors)

def run_motor_thread(action):
    safe_move(action)

# --- UART Command Loop ---

log_tft("Gogogogo")
time.sleep(1)
async def main():
    while True:
        await asyncio.sleep(0.05)
        try:
            wdt.feed()
            if uart.any():
                timeout = time.ticks_ms() + 500  # .5-second timeout
                response = b""
                while time.ticks_ms() < timeout:
                    try:
                        response += uart.read()
                        if response.endswith(b'\n'):
                            break
                    except Exception as e:
                        log_tft(f"[ERROR] UART read failed: {e}")
                        break
                    await asyncio.sleep(0.15)

                line = response.decode().strip()

                if line in ("open", "close"):
                    if motor_busy:
                        log_and_send("busy\n")
                    else:
                        _thread.start_new_thread(run_motor_thread, (line,))
                        send("ack\n")
                elif line == "stop":
                    motor_stop()
                    send("ack\n")
                elif line == "status":
                    send(f"{door_state}\n")
                elif line == "current":
                    current_mv = read_current_ma()
                    send(f"{current_mv}\n")
                elif line == "config":
                    send(json.dumps(config) + "\n")
                elif line.startswith("threshold:"):
                    try:
                        val = int(line.split(":")[1])
                        config["current_threshold"] = val
                        CURRENT_THRESHOLD = val
                        with open(CONFIG_FILE, "w") as f:
                            json.dump(config, f)
                        log_and_send("threshold updated\n")
                    except:
                        log_and_send("invalid threshold\n")
                elif line.startswith("timeout_open:"):
                    try:
                        val = int(line.split(":")[1])
                        config["move_timeout_open_ms"] = val
                        MOVE_TIMEOUT_OPEN_MS = val
                        with open(CONFIG_FILE, "w") as f:
                            json.dump(config, f)
                        log_and_send("timeout open updated\n")
                    except:
                        log_and_send("invalid timeout open\n")
                elif line.startswith("timeout_close:"):
                    try:
                        val = int(line.split(":")[1])
                        config["move_timeout_close_ms"] = val
                        MOVE_TIMEOUT_CLOSE_MS = val
                        with open(CONFIG_FILE, "w") as f:
                            json.dump(config, f)
                        log_and_send("timeout close updated\n")
                    except:
                        log_and_send("invalid timeout close\n")
                elif line.startswith("log"):
                    send("logged")
                else:
                    send("unknown\n")
        except MemoryError:
            log_tft("[CRITICAL] Out of memory. Restarting...")
            machine.reset()
        except Exception as e:
            log_tft(f"[ERROR] Unexpected: {e}")

            #tft.vscsad(scroll + tfa)
            #scroll += 10
            #scroll %= height
            #time.sleep(0.25)
asyncio.run(main())
    
