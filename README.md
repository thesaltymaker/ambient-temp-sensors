# ambient-temp-sensors
Overview

This project leverages an ESP32-S2 QT PY board to monitor environmental conditions in a garage. It collects temperature data from two DS18B20 sensors (attic and floor) and ambient temperature and humidity from an AHT20 sensor. The data is then sent to Adafruit IO for remote monitoring, while a NeoPixel LED provides a visual indication of temperature differences.
Key Features
    WiFi Connectivity:
        Scans available WiFi networks and connects using credentials stored in a separate secrets.py file.
        Displays connection details including MAC address and IP address.
    Sensor Integration:
        AHT20 Sensor: Communicates via I2C (using busio.I2C(board.SCL1, board.SDA1)) to measure ambient temperature and humidity.
        DS18B20 Sensors: Connected via a OneWire bus on board.A0, these sensors measure the attic and floor temperatures.
    Adafruit IO Integration:
        Publishes sensor readings to specific Adafruit IO feeds:
            garage-attic-temperature
            garage-floor-temperature
            garage-ceiling-temperature
            garage-ceiling-humidity
    Visual LED Indicator:
        A NeoPixel LED on the board indicates the temperature difference between the attic and ceiling:
            Red: Attic is significantly warmer.
            Green: Temperatures are within a small range.
            Blue: Ceiling is warmer.
    Error Handling:
        Uses try-except blocks to gracefully handle sensor read errors and data transmission issues.

Wiring & Setup
  Board: ESP32-S2 QT PY
    I2C Bus: Uses the stemma connector via busio.I2C(board.SCL1, board.SDA1) for the AHT20 sensor.
    OneWire Bus: DS18B20 sensors are connected to board.A0.
    NeoPixel: Configured on board.NEOPIXEL for status indication.

Getting Started
  Configure Credentials:
        Create a secrets.py file with your WiFi and Adafruit IO credentials.
    Wire the Sensors:
        be sure to map to the correct pins for the DS18B20 sensorsT PY board.
    Deploy the Code:
        Upload the code to your ESP32-S2 QT PY board.
    Monitor:
        The board will connect to WiFi, acquire sensor data, send the readings to Adafruit IO, and update the NeoPixel LED based on temperature differences.
        You will need to create and io.adafruit.com account and get the api credentials.

