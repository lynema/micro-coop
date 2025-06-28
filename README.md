# micro-coop
Some micropython microcontroller work to automate a chicken coop

This project started with a T-PicoC3 from Liligo and then evolved into running on a ESP32-S3-DevKitC-1-N8R2 Development Board.

There is going to be a lot of details that are unneceary and unwanted.  Everything could use a cleanup.  For those getting into microcontrolers, this should provide a decent demo of some functionality they can provide.

# Hardware list for automatic door function

Teyleten Robot BTS7960 43A High Power H-Bridge DC Motor Driver
USB-C PD Trigger Board Module PD/QC Decoy Board
Electric Stroke Linear Actuator 900N
CJMCU-219 INA219 I2C Interface
ESP32-S3-DevKitC-1-N8R2 - the N8R2 is able to withstand higher temp than the alternative s3 boards

# This is not yet great

Under RP2040 you fill find some of the code that worked on the T-PicoC3.  When the rp2040 started to overheat (I likely shorted it out at some point), I moved to the S3 board.  That is where the funcional-for-me code is.

There are drivers and code that others have written.  They are mostly unmodified.  
