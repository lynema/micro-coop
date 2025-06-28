import time
from machine import Pin, I2C
from ina219 import INA219

class CurrentSensor:
    def __init__(self, i2c_bus, addr=0x40):
        self.i2c = i2c_bus
        self.ina = INA219(self.i2c, addr)
        time.sleep(0.5)  # Give INA219 time to settle
    
    def get_current_ma(self):
        try:
            return self.ina.current
        except Exception as e:
            print(f"Error reading current: {e}")
            return 0.0
        
if __name__ == "__main__":
    print("Hello, World!")
    i2c = I2C(0, scl=Pin(2), sda=Pin(1), freq=10000)
    print("Scanning I2C bus...")
    devices = i2c.scan()
    print("Devices found:", devices)
    #i2c.writeto_mem(0x40, 0x00, b'\x01\x00')
    
    if 0x40 in devices:
        current_sensor = CurrentSensor(i2c)
        print("Current (mA):", current_sensor.get_current_ma())
    else:
        print("INA219 not found at address 0x40.")