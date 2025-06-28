# RP2040 SIDE: Motor Control, Obstruction Detection, UART Slave

from machine import Pin, PWM, UART, I2C
import time
import random
import st7789
import tft_config
import vga1_bold_16x32 as font
import json
import _thread
from ina219 import INA219

# --- CONFIGURATION ---
CONFIG_FILE = "motor_config.json"
def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)

config = load_config()
CURRENT_THRESHOLD = config.get("current_threshold", 500)
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

# INA219 setup
i2c = I2C(0, sda=Pin(24), scl=Pin(21))
ina = INA219(i2c)

# State
door_state = "unknown"
current_mv = 0
motor_busy = False

# --- Motor ---
def motor_stop():
    IN1.duty_u16(0)
    IN2.duty_u16(0)
    L_EN.value(0)
    R_EN.value(0)

def motor_open():
    IN1.duty_u16(50000)
    IN2.duty_u16(0)
    L_EN.value(1)
    R_EN.value(1)

def motor_close():
    IN1.duty_u16(0)
    IN2.duty_u16(50000)
    L_EN.value(1)
    R_EN.value(1)

def read_current_ma():
    try:
        return ina.current
    except:
        return 0.0

def safe_move(action):
    global current_mv, door_state, motor_busy
    motor_busy = True
    move_func = motor_open if action == 'open' else motor_close
    timeout = MOVE_TIMEOUT_OPEN_MS if action == 'open' else MOVE_TIMEOUT_CLOSE_MS
    print(f"Safe Move {action}")
    retries = 0
    door_state = action + "ing"
    while retries < 3:
        move_func()
        start = time.ticks_ms()
        obstructed = False
        
        print(f"Safe Move called {action}")
        time.sleep(1)

        
        current_buffer = []
        buffer_size = 5
        sample_interval = 10  # ms
        last_sample_time = time.ticks_ms()

        while time.ticks_diff(time.ticks_ms(), start) < timeout:
            now = time.ticks_ms()
            time.sleep(0.15)
            if time.ticks_diff(now, last_sample_time) >= sample_interval:
                last_sample_time = now
                reading = read_current_ma()
                if reading > 0:
                    current_buffer.append(reading)
                else:
                    current_buffer.append(500)
                if len(current_buffer) > buffer_size:
                    avg_current = sum(current_buffer) / len(current_buffer)
                    current_mv = avg_current

                    print(f"Current: {avg_current:.1f} mA")
                    #print(log_line)
                    #log_tft(log_line)
                    current_buffer.pop(0)
                    if avg_current < CURRENT_IDLE_THRESHOLD:
                        log_line = f"Motion complete"
                        log_tft("Motion complete")
                        print("Motion complete")
                        door_state = action
                        break


                    if avg_current > CURRENT_THRESHOLD:
                        log_tft("Obstruction detected")
                        motor_stop()
                        time.sleep(0.5)
                        for _ in range(3):
                            motor_open() if action == 'close' else motor_close()
                            print("backing it up")
                            time.sleep(2)
                        motor_stop()
                        obstructed = True
                        door_state = action + "blocked"
                            
        if not obstructed and door_state == action:
            print(f"New Door State {door_state}")
            break

        retries += 1
        print(f"Retrying State {door_state} Retries{retries}")


            
    door_state = 'open' if action == 'open' else 'closed'
    motor_stop()
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
    if uart.any():
        line = uart.readline().decode().strip()
        print(f"[UART] {line}")
        log_tft(f"{line}")

        if line in ("open", "close"):
            if motor_busy:
                uart.write("busy\n")
                print(f"[UART] busy returned")
                log_tft(f"busy")
            else:
                _thread.start_new_thread(run_motor_thread, (line,))
        elif line == "stop":
            motor_stop()
            uart.write("stopped\n")
        elif line == "status":
            uart.write(f"{door_state}\n")
        elif line == "current":
            current_mv = read_current_ma()
            uart.write(f"{current_mv}\n")
        elif line == "config":
            uart.write(json.dumps(config) + "\n")
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
        else:
            uart.write("unknown\n")

    tft.vscsad(scroll + tfa)
    scroll += 1
    scroll %= height
    time.sleep(0.05)
