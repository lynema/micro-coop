# micro-coop
Some micropython microcontroller work to automate a chicken coop

This project started with a T-PicoC3 from Liligo and then evolved into running on a ESP32-S3-DevKitC-1-N8R2 Development Board.  After experiencing WiFi connection troubles with the S3, it moved to the ESP32-C6.  Currently, the ESP32-C6 is my recommendation.

There is going to be a lot of details that are unneceary and unwanted.  Everything could use a cleanup.  For those getting into microcontrolers, this should provide a decent demo of some functionality they can provide.

# Features
- Actuates a door at sunrise and sunset
- - Amperage-sensor-driven obstruction detection
- Heater function via relay switch
- Light that will provide a consistent amount of "daylight" per day

## Code features
- HTML page for status and manual function
- Caches sunrise/sunset data
- Watchdog and website down detection for added peice of mind

# Hardware list
## Automatic door function
- Teyleten Robot BTS7960 43A High Power H-Bridge DC Motor Driver
- USB-C PD Trigger Board Module PD/QC Decoy Board
- Electric Stroke Linear Actuator 900N
- CJMCU-219 INA219 I2C Interface
- DS3231 RTC

## For the lights and heater
- DS18B20 Temperature Sensor
- Relay Board - 4 Gang - only use 2 though
- RJ45 Network Port Adapter(Horizontal Socket) PCB Board Kit

# This is not yet great

Under RP2040 you fill find some of the code that worked on the T-PicoC3.  When the rp2040 started to overheat (I likely shorted it out at some point), I moved to the S3 board.  That is where the funcional-for-me code is.  There's a few main.py backups from when this was in testing.  Things are functionally ok; the code is never done.

There are drivers and code that others have written.  They are mostly unmodified.  
