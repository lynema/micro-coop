def send_uart(cmd, retry_count=0, log_response=True):
    if retry_count == 3:
        log(f"[ERROR] Command: '{cmd}' failed")
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
        if not response:
            return send_uart(cmd, retry_count+1)
        else:
            if log_response: log(f"[UART] cmd: {cmd} reply: {response}")
            return response
            
    except Exception as e:
        log(f"[ERROR] UART decode failed: {e}")
        return None

def fetch_motor_config():
    global motor_config
    #resp = send_uart("config")
    # Current Threshold: <input name="threshold" type="number" value="{threshold}">
    # Timeout Open (ms): <input name="timeout_open" type="number" value="{timeout_open}">
    # Timeout Close (ms): <input name="timeout_close" type="number" value="{timeout_close}">

    resp = send_uart("config")
    try:
        motor_config = json.loads(resp)
        print(motor_config)
    except Exception as e:
        log(f"[ERROR] Failed to load motor config: {motor_config} e: {e}")

