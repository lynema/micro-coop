import time
from machine import Pin, PWM, I2C
from ina219 import INA219

# Motor pins
IN1 = PWM(Pin(14))
IN2 = PWM(Pin(15))
L_EN = Pin(16, Pin.OUT)
R_EN = Pin(17, Pin.OUT)
PWM_FREQ = 255
IN1.freq(PWM_FREQ)
IN2.freq(PWM_FREQ)

#i2c = I2C(2)
i2c = I2C(0, sda=Pin(24), scl=Pin(21))
ina = INA219(i2c)

# Sensitivity of the ACS712 30A module (66mV/A)
sensitivity = 0.066

zero_voltage=0

# Calibration offset (adjust if needed based on your setup)
# Measure the sensor's output with no current flowing and record the value
# Subtract this value from all subsequent readings
offset = 0  # Replace with your measured offset

# Function to read current
#def read_current():
    # Read the analog value from the sensor
 #   adc_value = CURRENT_SENSOR.read_u16()
    # Convert the ADC value to voltage
  #  voltage = (adc_value / 65535) * 3.3
    # Convert voltage to current using the sensitivity
    #current = (voltage - 1.65) / sensitivity # For 5V based sensors, adjust calculation if using different supply voltage,
    #current = (voltage - (3.3/2)) / sensitivity
    # 3.3/2 is the offset.  Should be normal volts/2
   # current = (voltage - (5/2)) / sensitivity
   # return current



#def read_current():
#    global zero_voltage
#    adc_value = CURRENT_SENSOR.read_u16()
#    voltage = (adc_value / 65535) * 3.3
#    current = (voltage - zero_voltage) / sensitivity
#    return current

# --- Motor ---
def motor_stop():
    IN1.duty_u16(0)
    IN2.duty_u16(0)
    L_EN.value(0)
    R_EN.value(0)

def motor_open():
    L_EN.value(1)
    R_EN.value(1)
    IN1.duty_u16(50000)
    IN2.duty_u16(0)

def motor_close():
    L_EN.value(1)
    R_EN.value(1)
    IN1.duty_u16(0)
    IN2.duty_u16(50000)

def output_ina219():
    current_mA = ina.current
    voltage_V = ina.bus_voltage
    print("{} mA  {} V".format(current_mA, voltage_V))
    return current_mA

def read_current_ma(samples=7):
    total = 0
    for _ in range(samples):
        read=ina.current
        if read > 0:
          total += ina.current
        else:
          total += 500
        time.sleep(0.01)
    return total / samples

def test_motor():
    motor_stop()
    print("hi")
    motor_open()
    start = time.ticks_ms()
    time.sleep(1)
    print("hiopen")
    timeout=36000
    max_open = 0
    current_current = read_current_ma(samples=6)
    while time.ticks_diff(time.ticks_ms(), start) < timeout:
        #current_reading = output_ina219()
        current_current = read_current_ma(samples=6)
        if current_current > 1150: print(f"Current: {current_current:.1f} mA")
        if current_current < 5:
            print("current close current under 5 breaking")
            break
        max_open = max(max_open, current_current)
        time.sleep(.05)
        

    print(f"hiclose max_open {max_open}")
    timeout=40000
    motor_close()
    start = time.ticks_ms()
    time.sleep(1)
    max_close = 0
    current_current = read_current_ma(samples=6)
    while time.ticks_diff(time.ticks_ms(), start) < timeout:
        current_current = read_current_ma(samples=6)
        if current_current > 1200: print(f"Current: {current_current:.1f} mA")
        if current_current < 5:
            print("current close current under 5 breaking")
            break
        max_close = max(max_close, current_current)
        time.sleep(.05)
       
    print(f"bye open max_open {max_open} close {max_close}")
    motor_stop()


#def calibrate_zero_current(samples=100):
#    total = 0
#    for _ in range(samples):
#        adc_value = CURRENT_SENSOR.read_u16()
#        print(f"adc_value {adc_value}")
#        total += adc_value
#        time.sleep(0.01)
#    avg = total / samples
#    voltage = (avg / 65535) * 3.3
#    print(f"(Calibration voltage {voltage}")
#    return voltage


# Main loop
#set_calibration_32V_1A()
 
#read_current_ma()   
test_motor()
motor_stop()