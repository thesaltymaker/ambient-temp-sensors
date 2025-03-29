# Wiring for ESP32-S2 QT PY
# ESP32-S2 QT PY
#     SCK
#     MI
#     MO
#     3V
#     GND
#     5V
#     A0
#     A1
#     A2
#     A3 
#     SDA
#     SCL
#     i2c bus for stemma connector is i2c = busio.I2C(board.SCL1, board.SDA1)

import time
import board
import busio
import adafruit_ahtx0
from digitalio import DigitalInOut
import ipaddress
import ssl
import wifi
import socketpool
import adafruit_requests
import digitalio
from adafruit_io.adafruit_io import IO_HTTP, AdafruitIO_RequestError
from random import randint
import adafruit_ds18x20
from adafruit_onewire.bus import OneWireBus
import neopixel


pixel = neopixel.NeoPixel(board.NEOPIXEL, 1)
# Get wifi details and more from a secrets.py file
try:
    from secrets import secrets
except ImportError:
    print("My secrets are kept in secrets.py, please add them there!")
    raise

print("My MAC addr:", [hex(i) for i in wifi.radio.mac_address])
print("Available WiFi networks:")
for network in wifi.radio.start_scanning_networks():
    print("\t%s\t\tRSSI: %d\tChannel: %d" % (str(network.ssid, "utf-8"),
            network.rssi, network.channel))
wifi.radio.stop_scanning_networks()

print("Connecting to %s"%secrets["ssid"])
wifi.radio.connect(secrets["ssid"], secrets["password"])
print("Connected to %s!"%secrets["ssid"])
print("My IP address is", wifi.radio.ipv4_address)

ipv4 = ipaddress.ip_address("8.8.4.4")
print("Ping google.com: %f ms" % (wifi.radio.ping(ipv4)*1000))

pool = socketpool.SocketPool(wifi.radio)
requests = adafruit_requests.Session(pool, ssl.create_default_context())

radio = wifi.radio
pool = socketpool.SocketPool(radio)
requests = adafruit_requests.Session(pool, ssl.create_default_context())


# Set your Adafruit IO Username and Key in secrets.py
aio_username = secrets["aio_username"]
aio_key = secrets["aio_key"]

# Initialize an Adafruit IO HTTP API object
io = IO_HTTP(aio_username, aio_key, requests)

# Get the 'garage-attic-_temperature' feed from Adafruit IO
try:    garage_attic_temperature_feed = io.get_feed("garage-attic-temperature")
except AdafruitIO_RequestError:    office_temperature_feed = io.create_new_feed("garage-attic-temperature")

#Get the 'garage-floor-temperature' feed from Adafruit IO
try:    garage_floor_temperature_feed = io.get_feed("garage-floor-temperature")
except AdafruitIO_RequestError:    office_temperature_feed = io.create_new_feed("garage-floor-temperature")

# Get the 'garage_ceiling_temperature' feed from Adafruit IO
try:    garage_ceiling_temperature_feed = io.get_feed("garage-ceiling-temperature")
except AdafruitIO_RequestError:    office_temperature_feed = io.create_new_feed("garage-ceiling-temperature")

# Get the 'garage_ceiling_humidity' feed from Adafruit IO
try:    garage_ceiling_humidity_feed = io.get_feed("garage-ceiling-humidity")
except AdafruitIO_RequestError:    office_humidity_feed = io.create_new_feed("garage-ceiling-humidity")

#print("break1")
# Create attic temp sensor
ow_bus = OneWireBus(board.A0)
devices = ow_bus.scan()
print("break2")
for device in devices:
    print("in for loop")
    print("ROM = {} \tFamily = 0x{:02x}".format([hex(i) for i in device.rom], device.family_code))
ds18b20_1 = adafruit_ds18x20.DS18X20(ow_bus, devices[0])
ds18b20_2 = adafruit_ds18x20.DS18X20(ow_bus, devices[1])

# Create sensor object, communicating over the board's default I2C bus
i2c = busio.I2C(board.SCL1, board.SDA1)  # uses board.SCL and board.SDA
aht20 = adafruit_ahtx0.AHTx0(i2c)

try:
    garage_ceiling_temp = (aht20.temperature * 9)/5 + 26.7
    garage_ceiling_hum = aht20.relative_humidity
except:
    print(" failed to get aht20 data")

try:
    garage_attic_temp = (ds18b20_1.temperature * 9)/5 + 32
except:
    print(" failed to get ds18b20_1 attic data")

try:
    garage_floor_temp = (ds18b20_2.temperature * 9)/5 + 32
except:
    print(" failed to get ds18b20_1 floor data")

while True:
    try: garage_ceiling_temp = (aht20.temperature * 9)/5 + 32
    except: print(" failed to get aht20 data")
    try: garage_ceiling_hum = aht20.relative_humidity
    except: print(" failed to get aht20 data")

    try: garage_attic_temp = (ds18b20_1.temperature * 9)/5 + 32
    except: print(" failed to get ds18b20_1 attic data")
    try: garage_floor_temp = (ds18b20_2.temperature * 9)/5 + 32
    except: print(" failed to get ds18b20_2 floor data")
    try:
        if garage_attic_temp < 150:
            io.send_data(garage_attic_temperature_feed["key"], garage_attic_temp)
        if garage_floor_temp < 150:
            io.send_data(garage_floor_temperature_feed["key"], garage_floor_temp)
        io.send_data(garage_ceiling_temperature_feed["key"], garage_ceiling_temp)
        io.send_data(garage_ceiling_humidity_feed["key"], garage_ceiling_hum)
    except Exception as error:
        print("failed to send data: " + str(error))

    # set the led: Red, attic is +3 degrees from ceiling, Green, within 3 degrees, Blue, garage ceiling is hotter
    temp_diff = garage_attic_temp - garage_ceiling_temp
    if temp_diff > 3:
        pixel.fill((255, 0, 0))
    elif temp_diff > 0:
        pixel.fill((0, 255, 0))
    else:
        pixel.fill((0, 0, 255))
    print("AHT20 Temperature: %0.1f F" % float(garage_ceiling_temp))
    print("AHT20 Humidity: %0.1f %%" % garage_ceiling_hum)
    print("DS18B20_1 Attic Temperature: {0:0.1f}F".format(garage_attic_temp))
    print("DS18B20_2 Floor Temperature: {0:0.1f}F".format(garage_floor_temp))

    time.sleep(60)

