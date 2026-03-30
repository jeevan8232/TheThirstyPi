# TheThirstyPi
Worry-free watering for the modern plant parent. It actively reads your soil moisture levels and waters your plants on demand, so you don't have to. Book that weekend getaway or extended vacation with total peace of mind—your garden is in good hands.

# Hand-Wiring the Electronics

Since we are keeping this accessible, there is no custom PCB required—everything is hand-wired directly to the microcontroller!

Hand-wiring a project like this is incredibly rewarding. Take your time, trim your wires to length so they fit nicely inside the shell, and double-check your connections as you go.

Below is the complete wiring guide based on the Raspberry Pi Pico (RP2040) pinout used for this project.

⚠️ Quick warning: Take it from me, never try to power a motor directly from your Pico’s pins. Motors are power-hungry and noisy, and they will absolutely fry your microcontroller. We are going to use the L293D Motor Driver as a heavy-duty bouncer to keep the power separate.

The Brain (Logic): Connect the L293D's logic power (VCC1 or 5V) to the Pico's VBUS pin. Connect the control pins: ENA to Pico GP10, IN1 (or 1A) to GP8, and IN2 (or 1B) to GP9.

The Muscle (Power): Connect the L293D's motor power (VCC2 or VMOTOR) directly to the positive wire of your 6V Battery Pack. Connect your water pump to the OUT1 and OUT2 (or 1Y and 2Y) pins.
The Golden Rule: You must connect the Pico's GND, the Battery Pack's GND, and the L293D's GND all together. If they don't share a common ground, your signals won't make sense to the chip.

Step 2: Giving It Senses

Next, we need to wire up the environmental sensors so the Pico actually knows what's going on in the dirt.

DHT11 (Temp/Hum): Connect VCC to Pico 3V3, GND to GND, and the Data pin to Pico GP14.
Soil Moisture Sensor: Connect VCC to Pico 3V3, GND to GND, and the Analog Output (A0) to Pico GP27 (ADC1).

(Optional) System Voltage: If you want to track battery voltage, I set up a quick voltage sensor module into Pico GP28 (ADC2).
