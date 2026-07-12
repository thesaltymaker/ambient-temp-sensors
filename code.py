# Wiring for ESP32-S2 QT PY
# ESP32-S2 QT PY
#     SCK
#     MI
#     MO
#     3V
#     GND
#     5V
#     A0     -> DS18B20 OneWire bus (both sensors)
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
import wifi
import digitalio
from adafruit_io.adafruit_io import IO_HTTP, AdafruitIO_RequestError
import adafruit_ds18x20
from adafruit_onewire.bus import OneWireBus
import neopixel
import mdns
from adafruit_httpserver import Server, Request, JSONResponse

from resilience import WifiManager, OfflineQueue

pixel = neopixel.NeoPixel(board.NEOPIXEL, 1)
# Get wifi details and more from a secrets.py file
try:
    from secrets import secrets
except ImportError:
    print("My secrets are kept in secrets.py, please add them there!")
    raise

print("My MAC addr:", [hex(i) for i in wifi.radio.mac_address])

# Multi-network fallback: secrets["networks"] = [{"ssid":..., "password":...}, ...]
# Falls back to the legacy single ssid/password pair.
networks = secrets.get("networks") or [
    {"ssid": secrets["ssid"], "password": secrets["password"]}
]
wm = WifiManager(networks, retry_interval=30, attempt_timeout=10)
queue = OfflineQueue()

FEED_KEYS = (
    "garage-attic-temperature",
    "garage-floor-temperature",
    "garage-ceiling-temperature",
    "garage-ceiling-humidity",
)

garage_ceiling_temp = None
garage_ceiling_hum = None
garage_attic_temp = None
garage_floor_temp = None

io = None
feeds_ready = False
http_started = False
http_server = None


def ensure_services():
    """Bring up Adafruit IO + feeds + HTTP server once wifi is available."""
    global io, feeds_ready, http_started, http_server
    if not wm.connected:
        return
    if io is None:
        io = IO_HTTP(secrets["aio_username"], secrets["aio_key"], wm.requests_session)
    if not feeds_ready:
        try:
            for key in FEED_KEYS:
                try:
                    io.get_feed(key)
                except AdafruitIO_RequestError:
                    io.create_new_feed(key)
            feeds_ready = True
        except Exception as error:
            print("feed setup failed, will retry: " + str(error))
    if not http_started:
        try:
            mdns_server = mdns.Server(wifi.radio)
            mdns_server.hostname = "ambient-temp-sensor"
            mdns_server.advertise_service(
                service_type="_http", protocol="_tcp", port=80
            )
            http_server = Server(wm.pool, debug=True)

            @http_server.route("/sensors")
            def sensors_handler(request: Request):
                """Return the most recently read sensor values as JSON."""
                return JSONResponse(
                    request,
                    {
                        "garage_ceiling_temp_f": garage_ceiling_temp,
                        "garage_ceiling_humidity": garage_ceiling_hum,
                        "garage_attic_temp_f": garage_attic_temp,
                        "garage_floor_temp_f": garage_floor_temp,
                    },
                )

            http_server.start(str(wifi.radio.ipv4_address), port=80)
            http_started = True
        except Exception as error:
            print("HTTP server start failed, will retry: " + str(error))


# Create attic/floor temp sensors -- tolerate missing hardware (bench mode)
ds18b20_1 = None
ds18b20_2 = None
try:
    ow_bus = OneWireBus(board.A0)
    devices = ow_bus.scan()
    for device in devices:
        print("ROM = {} \tFamily = 0x{:02x}".format(
            [hex(i) for i in device.rom], device.family_code))
    if len(devices) > 0:
        ds18b20_1 = adafruit_ds18x20.DS18X20(ow_bus, devices[0])
    if len(devices) > 1:
        ds18b20_2 = adafruit_ds18x20.DS18X20(ow_bus, devices[1])
except Exception as error:
    print("DS18B20 init failed: " + str(error))

# Create sensor object, communicating over the board's default I2C bus
aht20 = None
try:
    i2c = busio.I2C(board.SCL1, board.SDA1)  # uses board.SCL and board.SDA
    aht20 = adafruit_ahtx0.AHTx0(i2c)
except Exception as error:
    print("AHT20 init failed: " + str(error))

last_read = time.monotonic() - 60  # force an immediate first read

while True:
    wm.ensure_connected()
    ensure_services()

    if http_started:
        try:
            http_server.poll()
        except Exception as error:
            print("HTTP server poll failed: " + str(error))

    now = time.monotonic()
    if now - last_read >= 60:
        last_read = now

        if aht20 is not None:
            try: garage_ceiling_temp = (aht20.temperature * 9)/5 + 32
            except: print(" failed to get aht20 data")
            try: garage_ceiling_hum = aht20.relative_humidity
            except: print(" failed to get aht20 data")

        if ds18b20_1 is not None:
            try: garage_attic_temp = (ds18b20_1.temperature * 9)/5 + 32
            except: print(" failed to get ds18b20_1 attic data")
        if ds18b20_2 is not None:
            try: garage_floor_temp = (ds18b20_2.temperature * 9)/5 + 32
            except: print(" failed to get ds18b20_2 floor data")

        # Queue every good reading; drain sends live + backlog on reconnect.
        if garage_attic_temp is not None and garage_attic_temp < 150:
            queue.append("garage-attic-temperature", garage_attic_temp)
        if garage_floor_temp is not None and garage_floor_temp < 150:
            queue.append("garage-floor-temperature", garage_floor_temp)
        if garage_ceiling_temp is not None:
            queue.append("garage-ceiling-temperature", garage_ceiling_temp)
        if garage_ceiling_hum is not None:
            queue.append("garage-ceiling-humidity", garage_ceiling_hum)

        if wm.connected and feeds_ready and len(queue) > 0:
            sent = queue.drain(io, max_sends=25)
            if len(queue) > 0:
                print("queue: sent %d, %d pending" % (sent, len(queue)))

        # set the led: Red, attic is +3 degrees from ceiling, Green, within 3 degrees, Blue, garage ceiling is hotter
        if None not in (garage_attic_temp, garage_ceiling_temp, garage_ceiling_hum, garage_floor_temp):
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

    time.sleep(0.1)
