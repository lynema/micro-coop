from machine import Pin
import time

class Relay:
    def __init__(self, name, pin_num, active_high=True):
        self.name = name
        self.pin = Pin(pin_num, Pin.OUT)
        self.active_high = active_high

        # Set initial state to OFF
        self.off()

    def on(self):
        self.pin.value(1 if self.active_high else 0)
        print(f"{self.name} ON")

    def off(self):
        self.pin.value(0 if self.active_high else 1)
        print(f"{self.name} OFF")

    def toggle(self):
        self.pin.value(not self.pin.value())
        print(f"{self.name} TOGGLED")

    def is_on(self):
        return self.pin.value() == (1 if self.active_high else 0)

if __name__ == "__main__":
    relays = [
        Relay("Relay1", 18),
        Relay("Relay2", 17),
        Relay("Relay3", 16),
        Relay("Relay4", 15)
    ]

    # Test sequence: turn each on/off with delay
    while True:
        for r in relays:
            r.on()
            time.sleep(0.5)
            r.off()
            time.sleep(0.5)

