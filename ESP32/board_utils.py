import esp32
import time

while True:
  # Read the internal temperature of the MCU, in Celsius
  temp_celsius = esp32.mcu_temperature() 

  # Print the temperature
  print("MCU Temperature: {:.2f} °C".format(temp_celsius))
  print("MCU Temperature: {:.2f} °F".format((temp_celsius * 9 / 5) + 32))


  # Wait for a bit before the next reading
  time.sleep(5) 