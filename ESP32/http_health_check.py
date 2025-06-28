import network
import socket
import time
import machine
import _thread

# === CONFIGURATION ===
SSID = 'your-ssid'
PASSWORD = 'your-password'
HEALTH_CHECK_INTERVAL = 5  # seconds
MAX_FAILURES = 3

# === WIFI CONNECTION ===
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(SSID, PASSWORD)
    print("Connecting to Wi-Fi...")
    while not wlan.isconnected():
        time.sleep(1)
    ip = wlan.ifconfig()[0]
    print("Connected! IP address:", ip)
    return ip

# === WEB SERVER ===
def start_web_server():
    addr = socket.getaddrinfo('0.0.0.0', 80)[0][-1]
    server_socket = socket.socket()
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(addr)
    server_socket.listen(1)
    print("Web server running on http://{}:80".format(DEVICE_IP))

    while True:
        try:
            conn, addr = server_socket.accept()
            conn.settimeout(2)
            request = conn.recv(1024)
            if b"GET /health" in request:
                response = "HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\nOK"
            else:
                response = "HTTP/1.1 404 Not Found\r\n\r\nNot Found"
            conn.send(response)
        except Exception as e:
            print("Web server error:", e)
        finally:
            try:
                conn.close()
            except:
                pass

# === HEALTH CHECK ===
def health_check_loop(ip, wdt):
    failure_count = 0
    time.sleep(5)  # Wait for server to fully start
    while True:
        try:
            print("Performing health check (socket)...")
            sock = socket.socket()
            sock.settimeout(3)
            sock.connect((ip, 80))
            sock.send(b"GET /health HTTP/1.1\r\nHost: %s\r\n\r\n" % ip.encode())
            response = sock.recv(1024)
            sock.close()

            if b"200 OK" in response:
                print("Health check passed.")
                failure_count = 0
                wdt.feed()
            else:
                print("Health check failed.")
                failure_count += 1
        except Exception as e:
            print("Health check exception:", e)
            failure_count += 1

        if failure_count >= MAX_FAILURES:
            print("Too many health check failures. Allowing watchdog to trigger reboot...")
            break  # Stop feeding watchdog, let it reset device

        time.sleep(HEALTH_CHECK_INTERVAL)

# === MAIN ===
DEVICE_IP = connect_wifi()
wdt = machine.WDT(timeout=10000)  # 10 seconds watchdog timeout
_thread.start_new_thread(health_check_loop, (DEVICE_IP, wdt))
start_web_server()
