from machine import Pin
import time

class Relay:
    def __init__(self, name, pin_num, active_high=True):
        self.name = name
        self.pin = Pin(pin_num, Pin.OUT)
        self.active_high = active_high
        self.off()

    def on(self):
        self.pin.value(1 if self.active_high else 0)

    def off(self):
        self.pin.value(0 if self.active_high else 1)

    def toggle(self):
        self.pin.value(not self.pin.value())

    def is_on(self):
        return self.pin.value() == (1 if self.active_high else 0)

if __name__ == "__main__":
    relays = [
        Relay("Relay1", 19, False),
        Relay("Relay2", 18, False),
        #Relay("Relay3", 16, False),
        #Relay("Relay4", 15, False)
    ]

    # Test sequence: turn each on/off with delay
    while True:
        time.sleep(3)
        for r in relays:
            r.on()
            time.sleep(1.5)
            r.off()
            time.sleep(1.5)

