## 5_adafruit_logging.py
# set the adafruit.io API key, connect to adafruit.io 
# initialize the feeds for the touch sensor and temperature
# send the values to adafruit.io once a minute
##


import time
import board
from adafruit_seesaw.seesaw import Seesaw
import neopixel
import json
import ipaddress
import ssl
import wifi
import socketpool
import adafruit_requests
from adafruit_io.adafruit_io import IO_HTTP, AdafruitIO_RequestError


# Get wifi details and more from a secrets.py file
try:
    from secrets import secrets
except ImportError:
    print("My secrets are kept in secrets.py, please add them there!")
    raise
    
# Networking Stuff
print("My MAC addr:", [hex(i) for i in wifi.radio.mac_address])

# Print the avaiable wifi network signals and strength
print("Available WiFi networks:")
for network in wifi.radio.start_scanning_networks():
    print(
        "\t%s\t\tRSSI: %d\tChannel: %d"
        % (str(network.ssid, "utf-8"), network.rssi, network.channel)
    )
wifi.radio.stop_scanning_networks()

# Use the credentials in secrets.py to connect to the wifi
print("Connecting to %s" % secrets["ssid_2"])
wifi.radio.connect(secrets["ssid_2"], secrets["password_2"])
print("Connected to %s!" % secrets["ssid_2"])
print("My IP address is", wifi.radio.ipv4_address)

# Confirm device connected to the internet
ipv4 = ipaddress.ip_address("8.8.4.4")
print("Ping google.com: %f ms" % (wifi.radio.ping(ipv4) * 1000))

# Create a connection pool object, and sesson request
radio = wifi.radio
pool = socketpool.SocketPool(radio)
requests = adafruit_requests.Session(pool, ssl.create_default_context())

# Set your Adafruit IO Username and Key in secrets.py
aio_username = secrets["aio_username"]
aio_key = secrets["aio_key"]

# Initialize an Adafruit IO HTTP API object
io = IO_HTTP(aio_username, aio_key, requests)
# Get the 'water-me' feed from Adafruit IO, if it does not exist, create it
try:    water_me_feed = io.get_feed("water-me")
except AdafruitIO_RequestError:    water_me_feed = io.create_new_feed("water-me")
try:    water_me_temp_feed = io.get_feed("water-me-temp")
except AdafruitIO_RequestError:    water_me_temp_feed = io.create_new_feed("water-me-temp")


# initialize the i2c bus and sensor
i2c = board.STEMMA_I2C()  # For using the built-in STEMMA QT connector on a microcontroller
seesaw = Seesaw(i2c, addr=0x36)
LED = neopixel.NeoPixel(board.NEOPIXEL, 1)


# set LED on ESP32-S2 QT PY to green (RGB)
LED.fill((0, 20, 0))

while True:
    temp = 100
    touch = 100
    
    # read moisture level through capacitive touch pad
    try:
        touch = seesaw.moisture_read()
    except:
        print("Failed to read touch sensor")
    
    # read temperature from the temperature sensor and convert to Fahrenheit
    try: 
        temp = seesaw.get_temp()
        temp = ((temp * 9) / 5) + 32
        print("temp: " + str(temp) + "  moisture: " + str(touch))
    except:
        print("Failed to read temp sensor")
    
    # set the LED color based on touch capacitance
    if touch == 100:
        LED.fill((8, 0, 8))  #LED is PURPLE noting a problem reading gthe sensor
    elif touch < 450:
        LED.fill((16, 0, 0))  #LED is RED indicating soil is dry
    elif touch < 600:
        LED.fill((12, 4, 0))  #LED is ORANGE indicating soil is dry
    elif touch < 750:
        LED.fill((8, 8, 0))  #LED is YELLOW indicating soil is dry
    elif touch < 900:
        LED.fill((0, 16, 0))  #LED is GREEN indicating soil is dry
    else:
        LED.fill((0, 0, 16))  #LED is BLUE indicating soil is wet
        
    # push the data to adafruit.io
    try:
        io.send_data(water_me_feed["key"], touch)
        io.send_data(water_me_temp_feed["key"], temp)
    except Exception as error:
        print("failed to send data: " + str(error))
        
    time.sleep(60)
