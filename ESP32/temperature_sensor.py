from machine import Pin
from onewire import OneWire
from ds18x20 import DS18X20
import time

class DS18B20Sensor:
    def __init__(self, data_pin_num, vcc_pin_num=None, resolution=10):
        self.data_pin = Pin(data_pin_num, Pin.OPEN_DRAIN)
        self.ow = OneWire(self.data_pin)
        self.sensor = DS18X20(self.ow)

        # Optional VCC control
        if vcc_pin_num is not None:
            self.vcc_pin = Pin(vcc_pin_num, Pin.OUT)
            self.vcc_pin.value(1)
            time.sleep_ms(100)  # allow time for sensor to power up

        # Scan for devices
        self.roms = self.sensor.scan()
        if not self.roms:
            raise Exception("No DS18B20 sensor found on bus.")

        self.rom = self.roms[0]
        self.sensor.resolution(self.rom, resolution)
        self.sensor.convert_temp()
        time.sleep_ms(200)

    def read_celsius(self):
        self.sensor.convert_temp()
        time.sleep_ms(200)
        return self.sensor.read_temp(self.rom)

    def read_fahrenheit(self):
        c = self.read_celsius()
        return self.sensor.fahrenheit(c)
    
if __name__ == "__main__":  
    # Use GPIO13 for data, GPIO12 to power VCC
    sensor = DS18B20Sensor(data_pin_num=13)

    while True:
        temp_c = sensor.read_celsius()
        temp_f = sensor.read_fahrenheit()
        print(f"{temp_c:.2f} °C / {temp_f:.2f} °F")
        time.sleep(2)

