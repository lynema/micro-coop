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

def safe_move(action):
    global current_mv, door_state, motor_busy
    motor_busy = True
    try:
        move_func = motor_open if action == 'open' else motor_close
        timeout = MOVE_TIMEOUT_OPEN_MS if action == 'open' else MOVE_TIMEOUT_CLOSE_MS
        retries = 0
        door_state = action + "ing"
        while retries < 3:
            move_func()
            start = time.ticks_ms()
            obstructed = False

            log_tft(f"Action: {action} Retries: {retries}")
            time.sleep(1)

            current_buffer = []
            buffer_size = 6
            sample_interval = 10  # ms
            last_sample_time = time.ticks_ms()

            while time.ticks_diff(time.ticks_ms(), start) < timeout:
                now = time.ticks_ms()
                time.sleep(0.11)
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
                        current_buffer.pop(0)
                        if avg_current < CURRENT_IDLE_THRESHOLD:
                            door_state = action
                            break

                        if avg_current > CURRENT_THRESHOLD:
                            log_tft(f"Obstruction detected at current: {avg_current}")
                            motor_stop()
                            time.sleep(0.5)
                            for _ in range(3):
                                motor_open() if action == 'close' else motor_close()
                                time.sleep(2)
                                motor_stop()
                                time.sleep(1)
                            obstructed = True
                            door_state = action + "blocked"
                            break

            if not obstructed and door_state == action:
                log_tft(f"Action {action} complete. State: {door_state}")
                break

            retries += 1
            log_tft(f"Retrying State: {door_state} Retries: {retries}")

        motor_stop()
    finally:
        motor_busy = False
