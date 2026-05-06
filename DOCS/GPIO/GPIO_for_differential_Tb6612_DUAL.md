# GPIO connections from Raspberry Pi 4 to DUAL Tb6612fng motor controllers to motors for a TANK TRACK DIFFERENTIAL DRIVE Chassis

This mapping is aligned to the `4wheel_diff_tb6612fng_2.gpio` profile in
`config/control_interfaces.yaml`.

### **This version wires each motor to its own TB6612 channel**:
###   - LEFT FRONT gets its own H-bridge channel
###   - RIGHT FRONT gets its own H-bridge channel
###   - LEFT REAR gets its own H-bridge channel
###   - RIGHT REAR gets its own H-bridge channel
### Do not wire same-side motors in parallel into one TB6612 output channel.
### The software mirrors the left track command to both left motors and mirrors the right track command to both right motors.

#
#

### IMPORTANT:  This robot uses <u>two Tb6612</u> motor drivers.

### ALL WIRING from the Li-Ion batteries to the motor drivers MUST BE at least 18 AWG

### For wiring from the motor drivers to the Pi, common Dupont jumper cables are ok.

#
#

## POWER YOUR MOTOR CIRCUIT (USE 18 AVG!)

**This project uses battery holders for two 3.7V 2800mAh Li-Ion battteries**

**IF** your battery holder(s) have attached cable thinner than 18 AWG, replace all connections with 18 AWG cable

**FIRST** connect the **positive** side of the battery holder(s) to your ON/OFF switch

**THEN** connect the other side of the ON/OFF switch to your fuse holder (with fuse)

**THEN** solder **THREE MORE 18 AWG CABLES** (around 6-8 inches long) to the other side of the fuse holder

### This is the POSITIVE SIDE of your circuit

**SOLDER ONE OF POSITIVE 20 AWG CABLES** to the **VM** on one of your Tb6612 motor controllers

**SOLDER A SECOND POSITIVE 20 AWG CABLE** to the **VM** on the other Tb6612 motor controller

**SOLDER THE THIRD POSITIVE 20 AWG CABLE** to a **1 kΩ (1000 ohm) 1 watt resistor**

**THEN** connect the other side of the resistor to the positive side of a small LED

### Now connect three more 18 AWG cables to the NEGATIVE SIDE of your battery holder(s)

**CONNECT ONE OF YOUR NEGATIVE 18 AWG CABLES** to one of the **GND**s on one of your motor drivers

**CONNECT A SECOND NEGATIVE 18 AWG CABLE** to one of the **GND**s on **the other motor driver**

**FINALLY**, connect the third and last remaining 18 **NEGATIVE 18 AWG CABLE** to the free side of the LED already connected to the positive side of the circuit

### Now test your circuit by switching the ON/OFF button

**THE LED SHOULD LIGHT UP**

**This LED is used as a debugging tool** informing the operator when the circuit is successfully powering the motor system

If the LED does not light up, check your circuit and your batteries.

### IMPORTANT: Make sure to leave the ON/OFF switch on OFF while you perform ANY CHANGES to your circuit or your GPIO pins, otherwise you could blow a fuse

#
#

<br>

#
#

### TB6612 #1 - FRONT MOTORS

**Left Front Motor (Channel A)**

**Motor wires**

Motor + to A01

Motor − to A02

**Right Front Motor (Channel B)**

**Motor wires**

Motor + to B01

Motor − to B02

**GPIO connections**

PWMA → GPIO 12 (PWM0)

AIN1 → GPIO 5

AIN2 → GPIO 6

PWMB → GPIO 13 (PWM1)

BIN1 → GPIO 16

BIN2 → GPIO 19

#
#

<br>

#
#

### TB6612 #2 - REAR MOTORS

**Left Rear Motor (Channel A)**

**Motor wires**

Motor + to A01

Motor − to A02

**Right Rear Motor (Channel B)**

**Motor wires**

Motor + to B01

Motor − to B02

**GPIO connections**

PWMA → GPIO 18

AIN1 → GPIO 20

AIN2 → GPIO 21

PWMB → GPIO 26

BIN1 → GPIO 23

BIN2 → GPIO 24

#
#

<br>

#
#

### ADD BATTERIES TO POWER MOTORS

### Common ground
**All grounds must connect together (critical)**:

Pi GND to TB6612 GND (FRONT MOTOR DRIVER)

Pi GND to TB6612 GND (REAR MOTOR DRIVER)

#
#

### Motor power

Battery + to VM on both boards (make a 3-sided jumper wire **OR** use a breadboard)

Battery – to GND on both boards (make a 3-sided jumper wire **OR** use a breadboard)

#
#

<br>

#
#

### COMPLETE THE CIRCUIT

### To complete the circuit, connect STBY and VCC on BOTH MOTOR DRIVERS to the single 3.3V pin on the Raspberry Pi

**Create a one-to-four jumper cable unless you are using a breadboard**

**One way to do this is to make two three-ended jumper cables and connect one end of each to a third three-ended jumper cable.**

**Then connect**:

One end (the main stem) to the 3.3V pin on the Pi

**Then connect the remaining four ends**:

One end to VCC on MOTOR DRIVER 1

One end to STBY on MOTOR DRIVER 1

One end to VCC on MOTOR DRIVER 2

One end to STBY on MOTOR DRIVER 2

#
#

<br>

#
#



