# ambient-temp-sensor Local HTTP Endpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Home Assistant a direct local HTTP JSON endpoint on the ambient-temp-sensor
ESP32-S2 QT PY board, reachable by mDNS hostname, without disturbing the existing Adafruit IO
push.

**Architecture:** `adafruit_httpserver.Server` + `mdns.Server` started once after WiFi connects,
inside `ambient-temp-sensor/code.py`. The main loop is restructured from a single 60s
`time.sleep()` into a tight loop that calls `server.poll()` every ~0.1s and only does the
sensor-read/Adafruit-IO-push work once every 60s (tracked via `time.monotonic()`). A single
`GET /sensors` route returns the four most recently read values as JSON, sourced from the same
module-level variables the existing sensor-read code already populates.

**Tech Stack:** CircuitPython 8.2.8, `adafruit_httpserver` (bundled at
`/home/thesa/Downloads/adafruit-circuitpython-bundle-9.x-mpy-20250208/lib/adafruit_httpserver`),
`mdns` (CircuitPython core built-in, no install needed).

## Global Constraints

- Scope is `ambient-temp-sensor/` only — do not touch bbq-monitor, indoor-air-quality-monitor,
  monitor-light-strip, or water-me-iot-reminder.
- Adafruit IO push must keep working unchanged — this adds a second data path, it does not
  replace the first.
- No auth/TLS on the new HTTP endpoint — LAN-only, same trust boundary as the rest of the home
  network.
- mDNS hostname: `ambient-temp-sensor.local`, service `_http._tcp` on port `80`.
- HA polls at `scan_interval: 60` to match the board's read cadence.
- Never print or commit the contents of `secrets.py`.
- This directory is not a git repository — there are no commit steps in this plan. Skip any
  instinct to `git add`/`git commit`.
- Board is currently disconnected and offsite; the outstanding WiFi connection issue
  (`ConnectionError: Unknown failure 15/204`, see project memory `ambient-temp-sensor-wifi-issue`)
  must be resolved before Tasks 3-6 (anything requiring the physical board) can run. Tasks 1-2
  (code changes, static validation, review) do not require the board and can run now.

---

## Task 1: Implement the HTTP server + mdns in code.py

**Files:**
- Modify: `/home/thesa/Projects/ESP32-S2_QT_QY/ambient-temp-sensor/code.py`

**Interfaces:**
- Produces: module-level globals `garage_ceiling_temp`, `garage_ceiling_hum`,
  `garage_attic_temp`, `garage_floor_temp` (already exist in the file; this task adds an
  `/sensors` HTTP handler that reads them, and initializes them to `None` before the main loop
  so the handler never raises `NameError` on a request that arrives before the first sensor
  read completes).

- [ ] **Step 1: Add the new imports**

At the top of `ambient-temp-sensor/code.py`, after the existing `import neopixel` (line 32), add:

```python
import mdns
from adafruit_httpserver import Server, Request, JSONResponse
```

- [ ] **Step 2: Start the HTTP server and mdns advertisement right after the socket pool is created**

Replace lines 58-63 (the duplicated `pool`/`requests` block):

```python
pool = socketpool.SocketPool(wifi.radio)
requests = adafruit_requests.Session(pool, ssl.create_default_context())

radio = wifi.radio
pool = socketpool.SocketPool(radio)
requests = adafruit_requests.Session(pool, ssl.create_default_context())
```

with:

```python
pool = socketpool.SocketPool(wifi.radio)
requests = adafruit_requests.Session(pool, ssl.create_default_context())

mdns_server = mdns.Server(wifi.radio)
mdns_server.hostname = "ambient-temp-sensor"
mdns_server.advertise_service(service_type="_http", protocol="_tcp", port=80)

garage_ceiling_temp = None
garage_ceiling_hum = None
garage_attic_temp = None
garage_floor_temp = None

http_server = Server(pool, debug=True)


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


http_server.start(str(wifi.radio.ipv4_address))
```

This removes the pre-existing duplicate `pool`/`requests` creation (dead code — it was
overwriting the identical objects created two lines above) while adding the server setup in the
same spot.

- [ ] **Step 3: Confirm the edit**

Read back `ambient-temp-sensor/code.py` and confirm: two new imports present, no leftover
duplicate `pool`/`requests` block, `http_server.start(...)` appears before the Adafruit IO feed
setup (`aio_username = secrets["aio_username"]`, currently line 67).

---

## Task 2: Restructure the main loop for non-blocking polling

**Files:**
- Modify: `/home/thesa/Projects/ESP32-S2_QT_QY/ambient-temp-sensor/code.py`

**Interfaces:**
- Consumes: `http_server` (from Task 1, has `.poll()` method per
  `adafruit_httpserver.Server`), `time.monotonic()` (stdlib).
- Produces: same four globals as Task 1, now reassigned every 60s inside the loop instead of
  once per `time.sleep(60)` cycle.

- [ ] **Step 1: Replace the `while True:` loop**

Replace the entire loop currently at the end of the file (from `while True:` through the final
`time.sleep(60)`, originally lines 120-153) with:

```python
last_read = time.monotonic() - 60  # force an immediate first read

while True:
    try:
        http_server.poll()
    except OSError as error:
        print("HTTP server poll failed: " + str(error))

    now = time.monotonic()
    if now - last_read >= 60:
        last_read = now

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

    time.sleep(0.1)
```

Also delete the now-redundant one-off pre-loop reads (originally lines 104-118, the three
`try/except` blocks that read `aht20`/`ds18b20_1`/`ds18b20_2` once before the loop) — the `- 60`
seed on `last_read` already forces the loop's own read block to fire on the very first
iteration, so the separate pre-loop reads are dead code once this change lands.

- [ ] **Step 2: Confirm the edit**

Read back the file. Confirm: exactly one `while True:` loop remains, it contains
`http_server.poll()` as its first statement, the 60s-gated block contains all four sensor reads
plus the Adafruit IO push plus the LED/print logic, and the loop ends with `time.sleep(0.1)` (not
`time.sleep(60)`).

---

## Task 3: Static validation and code review (no board required)

**Files:**
- Read: `/home/thesa/Projects/ESP32-S2_QT_QY/ambient-temp-sensor/code.py`

- [ ] **Step 1: Syntax-check locally via devops-agent**

Call `mcp__devops-agent__devops_task` with:
- `task`: `"Run locally (run_local, no SSH): python3 -m py_compile /home/thesa/Projects/ESP32-S2_QT_QY/ambient-temp-sensor/code.py && echo SYNTAX_OK. This only checks Python syntax — board/wifi/etc. imports will not resolve on this host and that's expected, py_compile does not execute the module. Report the exact output."`
- `hosts`: `["192.168.2.60"]`

Expected: `SYNTAX_OK` printed, no `SyntaxError` traceback. (`board`, `wifi`, `mdns`, etc. are
CircuitPython-only modules that don't exist on this host — `py_compile` never imports them, it
only parses, so this is safe and catches real syntax mistakes like the earlier secrets.py
apostrophe bug.)

If it fails: read the traceback, fix the indicated line in `code.py`, re-run.

- [ ] **Step 2: Second-opinion code review via ollama-bridge**

Call `mcp__ollama-bridge__ollama_review_file` (or `ollama_review_code` with the file's contents
pasted in) pointed at
`/home/thesa/Projects/ESP32-S2_QT_QY/ambient-temp-sensor/code.py`, asking it to review
specifically for: (a) whether the non-blocking loop still leaves `http_server.poll()` responsive
(no other blocking call was accidentally left inside the 0.1s tick path), (b) whether the
`/sensors` handler could ever reference a name that's out of scope, (c) whether the broad
`try/except` usage is consistent with the rest of the file.

- [ ] **Step 3: Triage the review feedback**

Read the review output. Any finding that points at a real bug in the Task 1/2 diff (not a
pre-existing issue in code this plan didn't touch, like the duplicate-feed-variable typos on
lines 75/79/83/87 using `office_temperature_feed`/`office_humidity_feed` instead of the
`garage_*` names — those are pre-existing and out of scope) gets fixed directly in `code.py`.
Re-run Step 1 after any fix.

---

## Task 4: Deploy to the board (on-site, board must be reconnected and WiFi working)

**Files:**
- Copy: `/home/thesa/Downloads/adafruit-circuitpython-bundle-9.x-mpy-20250208/lib/adafruit_httpserver`
  → `/media/thesa/CIRCUITPY/lib/adafruit_httpserver`
- Copy: `/home/thesa/Projects/ESP32-S2_QT_QY/ambient-temp-sensor/code.py`
  → `/media/thesa/CIRCUITPY/code.py`

**Precondition:** board is plugged in, mounted at `/media/thesa/CIRCUITPY`, serial at
`/dev/ttyACM0`, and the WiFi connection issue is resolved (board can reach `wifi.radio.connect`
without raising). Confirm the mount and serial device exist before proceeding — do not guess.

- [ ] **Step 1: Verify the board is present**

Call `mcp__devops-agent__devops_task` with:
- `task`: `"Run locally (run_local, no SSH): ls /dev/ttyACM0 && ls /media/thesa/CIRCUITPY && echo BOARD_PRESENT. Report the exact output."`
- `hosts`: `["192.168.2.60"]`

Expected: `BOARD_PRESENT`. If this fails, stop — board isn't connected/mounted, nothing past this
point can run.

- [ ] **Step 2: Copy the httpserver library onto the board**

Call `mcp__devops-agent__devops_task` with:
- `task`: `"Run locally (run_local, no SSH): cp -r /home/thesa/Downloads/adafruit-circuitpython-bundle-9.x-mpy-20250208/lib/adafruit_httpserver /media/thesa/CIRCUITPY/lib/ && ls /media/thesa/CIRCUITPY/lib/adafruit_httpserver | head -5 && echo LIB_COPIED. Report the exact output."`
- `hosts`: `["192.168.2.60"]`

Expected: file listing followed by `LIB_COPIED`.

- [ ] **Step 3: Deploy the updated code.py**

Call `mcp__devops-agent__devops_task` with:
- `task`: `"Run locally (run_local, no SSH): cp /home/thesa/Projects/ESP32-S2_QT_QY/ambient-temp-sensor/code.py /media/thesa/CIRCUITPY/code.py && echo CODE_DEPLOYED. Report the exact output."`
- `hosts`: `["192.168.2.60"]`

Expected: `CODE_DEPLOYED`. CircuitPython's auto-reload will restart `code.py` as soon as this
write completes.

---

## Task 5: Hardware boot verification (on-site)

**Files:**
- Create (temp, at execution time): a pyserial verification script — same pattern already used
  earlier this session, recreate it since the original was in a session-scoped scratchpad
  directory that no longer exists.

- [ ] **Step 1: Write the verification script**

Write to a scratchpad path (use the current session's scratchpad directory):

```python
import serial
import time

ser = serial.Serial("/dev/ttyACM0", 115200, timeout=1)
ser.write(b"\x04")  # Ctrl-D soft reboot, re-runs code.py
time.sleep(1)
end = time.time() + 25
buf = b""
while time.time() < end:
    chunk = ser.read(500)
    if chunk:
        buf += chunk
print(buf.decode(errors="replace"))
ser.close()
```

- [ ] **Step 2: Run it via devops-agent**

Call `mcp__devops-agent__devops_task` with:
- `task`: `"Run locally (run_local, no SSH): python3 <path-to-script-from-step-1>. Soft-reboots the CircuitPython board and captures 25 seconds of serial output. Report the COMPLETE raw output exactly, do not summarize — need to check for a successful WiFi connect (an IP address printed) and no Python traceback."`
- `hosts`: `["192.168.2.60"]`

Expected: `Connected to <ssid>!`, an IP address, sensor readings printed
(`AHT20 Temperature: ...`, etc.) repeating, and no `Traceback` anywhere in the output. If a
traceback appears, read it — if it's an `ImportError` for `adafruit_httpserver` or `mdns`, go
back to Task 4 Step 2 and confirm the library actually landed in `/media/thesa/CIRCUITPY/lib/`.

---

## Task 6: Network verification (on-site)

- [ ] **Step 1: Confirm the endpoint answers**

Call `mcp__devops-agent__devops_task` with:
- `task`: `"Run locally (run_local, no SSH): curl -sS -m 5 http://ambient-temp-sensor.local/sensors. Report the exact output, including curl's exit status if the command fails."`
- `hosts`: `["192.168.2.60"]`

Expected: a JSON body like
`{"garage_ceiling_temp_f": 72.3, "garage_ceiling_humidity": 41.2, "garage_attic_temp_f": 68.1, "garage_floor_temp_f": 65.4}`.

If `curl` can't resolve `ambient-temp-sensor.local` (mDNS not reachable from this host/network
segment): fall back to hitting the board's IP address directly. Get the IP from the Task 5
serial capture (`"My IP address is ..."` line printed at boot) and re-run
`curl -sS -m 5 http://<ip>/sensors`. Note in the task tracker whether the mDNS name or only the
raw IP worked — this determines whether the spec's DHCP-reservation fallback is needed.

---

## Task 7: Home Assistant configuration (manual, outside this repo)

- [ ] **Step 1: Add the REST sensor block**

In HA's `configuration.yaml`, add:

```yaml
rest:
  - resource: http://ambient-temp-sensor.local/sensors
    scan_interval: 60
    sensor:
      - name: "Garage Ceiling Temp"
        value_template: "{{ value_json.garage_ceiling_temp_f }}"
      - name: "Garage Ceiling Humidity"
        value_template: "{{ value_json.garage_ceiling_humidity }}"
      - name: "Garage Attic Temp"
        value_template: "{{ value_json.garage_attic_temp_f }}"
      - name: "Garage Floor Temp"
        value_template: "{{ value_json.garage_floor_temp_f }}"
```

If Task 6 found mDNS unreachable from HA's network segment, use the board's raw IP in `resource`
instead, and set up a DHCP reservation for `58:cf:79:ab:29:64` on the router so that IP is
stable.

- [ ] **Step 2: Restart HA and verify**

Restart Home Assistant. Check the HA logs for errors on the four new `rest` sensor entities.
Confirm all four show non-null numeric values within one `scan_interval` (60s) of startup.

---

## Self-Review Notes

- **Spec coverage:** every spec section (architecture, loop restructure, endpoint shape, error
  handling, HA config, testing plan) maps to a task above (Tasks 1-2, 2, 1, 1/2, 7, 5/6
  respectively). The spec's two open risks are both resolved: exact `adafruit_httpserver` API
  confirmed against the bundled examples (`httpserver_start_and_poll.py`,
  `httpserver_mdns.py`, `httpserver_cpu_information.py`) rather than left as a guess; the mDNS
  fallback path is now an explicit step in Task 6/7 instead of a footnote.
- **Pre-existing bugs found but left alone (out of scope):** lines 75/79/83/87 assign the
  `AdafruitIO_RequestError` fallback to `office_temperature_feed`/`office_humidity_feed`
  instead of the `garage_*` names actually used later — likely copy-paste from another project.
  Not touched here; flag it to the user separately if desired.
- **Type/name consistency:** `http_server` (Task 1) is the exact name used in Task 2's
  `http_server.poll()` and Task 3's review target. `garage_ceiling_temp` /
  `garage_ceiling_hum` / `garage_attic_temp` / `garage_floor_temp` are the exact pre-existing
  names, unchanged, referenced identically in Task 1's handler and Task 2's loop.
