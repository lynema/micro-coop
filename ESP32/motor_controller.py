from machine import PWM, Pin, I2C
import time
from current_sensor import CurrentSensor

class MotorController:
    def __init__(self, in1_pin, in2_pin, l_en_pin, r_en_pin, current_sensor, pwm_freq=1000, move_timeout_open_ms=5000, move_timeout_close_ms=5000, current_threshold=1000, current_idle_threshold=5):
        # Motor pins
        self.IN1 = PWM(Pin(in1_pin))
        self.IN2 = PWM(Pin(in2_pin))
        self.L_EN = Pin(l_en_pin, Pin.OUT)
        self.R_EN = Pin(r_en_pin, Pin.OUT)
        
        # PWM frequency
        self.PWM_FREQ = pwm_freq
        self.IN1.freq(self.PWM_FREQ)
        self.IN2.freq(self.PWM_FREQ)

        # Thresholds and timeouts
        self.MOVE_TIMEOUT_OPEN_MS = move_timeout_open_ms
        self.MOVE_TIMEOUT_CLOSE_MS = move_timeout_close_ms
        self.CURRENT_THRESHOLD = current_threshold
        self.CURRENT_IDLE_THRESHOLD = current_idle_threshold

        # Current sensor instance
        self.current_sensor = current_sensor

        # State
        self.motor_busy = False
        self.door_state = "stopped"
        self.current_mv = 0
        self.last_higest_average_mv = 0
        self.motor_stop()

    def motor_stop(self):
        """Stops the motor."""
        self.IN1.duty_u16(0)
        self.IN2.duty_u16(0)
        self.L_EN.value(0)
        self.R_EN.value(0)

    def motor_open(self):
        """Opens the motor (moves in one direction)."""
        self.IN1.duty_u16(32768)
        self.IN2.duty_u16(0)
        self.L_EN.value(1)
        self.R_EN.value(1)

    def motor_close(self):
        """Closes the motor (moves in the opposite direction)."""
        self.IN1.duty_u16(0)
        self.IN2.duty_u16(32768)
        self.L_EN.value(1)
        self.R_EN.value(1)

    def safe_move(self, action, log):
        if not self.current_sensor:
            log("[ERROR] No current_sensor initialized motor cannot run")
            return False
        """Executes a safe move (open/close) with retries and obstruction detection."""
        if self.motor_busy:
            return  # Avoid running another operation while the motor is busy

        self.motor_busy = True
        higest_average_mv = 0
        try:
            move_func = self.motor_open if action == 'open' else self.motor_close
            timeout = self.MOVE_TIMEOUT_OPEN_MS if action == 'open' else self.MOVE_TIMEOUT_CLOSE_MS
            retries = 0
            self.door_state = action + "ing"
            
            while retries <= 2:
                move_func()
                start = time.ticks_ms()
                obstructed = False

                log(f"Action: {action} Retries: {retries}")
                time.sleep(1)

                current_buffer = []
                buffer_size = 6
                sample_interval = 10  # ms
                last_sample_time = time.ticks_ms()

                while time.ticks_diff(time.ticks_ms(), start) < timeout:
                    now = time.ticks_ms()
                    last_higest_average_mv = 0
                    time.sleep(0.11)  # Sampling rate
                    if time.ticks_diff(now, last_sample_time) >= sample_interval:
                        last_sample_time = now
                        reading = self.current_sensor.get_current_ma()
                        if -1 < reading:
                            current_buffer.append(reading)
                        else:
                            current_buffer.append(500)
                        
                        if len(current_buffer) > buffer_size:
                            avg_current = sum(current_buffer) / len(current_buffer)
                            self.current_mv = avg_current
                            if higest_average_mv < avg_current:
                                higest_average_mv = avg_current
                            current_buffer.pop(0)
                            if avg_current < self.CURRENT_IDLE_THRESHOLD:
                                self.door_state = action
                                log("move complete")
                                break

                            if avg_current > self.CURRENT_THRESHOLD:
                                log(f"Obstruction detected at current: {avg_current}")
                                self.motor_stop()
                                time.sleep(0.5)
                                for _ in range(3):
                                    self.motor_open() if action == 'close' else self.motor_close()
                                    time.sleep(2)
                                    self.motor_stop()
                                    time.sleep(1)
                                obstructed = True
                                self.door_state = action + "blocked"
                                break

                if not obstructed and self.door_state == action:
                    log(f"Action {action} complete. State: {self.door_state}")
                    break

                retries += 1
                log(f"Retrying State: {self.door_state} Retries: {retries}")

            self.motor_stop()
        finally:
            self.last_higest_average_mv = higest_average_mv
            self.motor_busy = False
            
def fetch_motor_config():
    global motor_config
    #resp = send_uart("config")
    try:
        motor_config = json.loads(resp)
    except Exception as e:
        log(f"[ERROR] Failed to load motor config: {motor_config} e: {e}")

if __name__ == "__main__":
    i2c = I2C(0, scl=Pin(2), sda=Pin(1), freq=10000)
    current_sensor = CurrentSensor(i2c)

    motor_controller = MotorController(
        #t-picoc3
        #in1_pin=14, in2_pin=15, l_en_pin=16, r_en_pin=17,
        #esp32
        in1_pin=4, in2_pin=5, l_en_pin=40, r_en_pin=41, 
        current_sensor=current_sensor, move_timeout_open_ms=40000,
        move_timeout_close_ms=40000, current_threshold=900
    )
    motor_controller.motor_stop()
    motor_controller.motor_close()
    print("closing")
    time.sleep(4)
    motor_controller.motor_open()
    print("opening")
    time.sleep(8)
    motor_controller.motor_stop()