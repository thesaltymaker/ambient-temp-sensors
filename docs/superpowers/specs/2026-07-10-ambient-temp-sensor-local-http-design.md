# ambient-temp-sensor: local HTTP endpoint for Home Assistant

## Problem

Home Assistant currently has no way to read this board's sensor data. The board only pushes
readings to Adafruit IO (cloud). The goal is to let HA query the board directly over the local
network, without giving up the existing Adafruit IO push.

## Goals

- HA polls the board directly via HTTP, gets current sensor readings as JSON.
- Adafruit IO push keeps working unchanged (both data paths coexist).
- Board reachable by a stable hostname, not a DHCP IP that can change on reboot.
- No new physical/library dependencies beyond what's already available locally
  (see [[circuitpython-bundle-location]] memory: `adafruit_httpserver` is in the bundle at
  `/home/thesa/Downloads/adafruit-circuitpython-bundle-9.x-mpy-20250208/lib/adafruit_httpserver`;
  `mdns` is a built-in CircuitPython core module on ESP32-S2, no bundle copy needed).

## Non-goals

- Not touching bbq-monitor, indoor-air-quality-monitor, monitor-light-strip, or
  water-me-iot-reminder. This is scoped to ambient-temp-sensor only. A shared reusable pattern
  across all 5 projects can be a follow-up if this works out.
- Not adding auth/TLS to the HTTP endpoint — it's LAN-only, same trust boundary as the rest of
  the home network.
- Not fixing the outstanding WiFi connection issue here (see
  [[ambient-temp-sensor-wifi-issue]] memory) — that's a prerequisite blocking this from being
  testable, not part of this design.

## Architecture

`code.py` gains two new pieces of state, both started once right after `wifi.radio.connect()`
succeeds (same place `secrets`/`IO_HTTP` setup already happens):

1. `adafruit_httpserver.Server` bound to the existing `socketpool.SocketPool(wifi.radio)`.
2. `mdns.Server` advertising the hostname `ambient-temp-sensor.local` and an `_http._tcp`
   service on port 80, so HA doesn't depend on a static/reserved DHCP IP.

## Main loop restructure

Current loop does `sensor read -> IO push -> time.sleep(60)`, which would block HTTP requests
for up to 60s at a time (CircuitPython is single-threaded; nothing else runs during `sleep`).

New loop:

```
last_read = time.monotonic() - 60  # force immediate first read
while True:
    try:
        server.poll()
    except Exception as error:
        print("HTTP server poll failed: " + str(error))

    now = time.monotonic()
    if now - last_read >= 60:
        last_read = now
        # existing sensor read + LED update + Adafruit IO push logic, unchanged
        ...

    time.sleep(0.1)
```

The `time.sleep(0.1)` per iteration keeps the loop from pegging the CPU while still answering
HTTP requests promptly (worst case ~100ms latency instead of up to 60s).

## HTTP endpoint

Single route, all four values in one response — matches the existing global variables the
sensor-read block already populates (no restructuring of sensor-read logic needed):

`GET /sensors` →

```json
{
  "garage_ceiling_temp_f": 72.3,
  "garage_ceiling_humidity": 41.2,
  "garage_attic_temp_f": 68.1,
  "garage_floor_temp_f": 65.4
}
```

The handler reads the cached globals directly — it never triggers its own sensor read, it just
serves whatever the last 60s cycle produced.

## Error handling

`server.poll()` and the route handler are wrapped in the same broad `try/except` style already
used throughout this project (see CLAUDE.md conventions) — a malformed/dropped HTTP request must
not crash the sensor loop, same principle already applied to every sensor read in this codebase.

## Home Assistant configuration (external to this repo)

Added to HA's `configuration.yaml`:

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

`scan_interval: 60` matches the board's read cadence — polling faster gains nothing.

## Testing plan

Board is currently disconnected (offsite). Once reconnected and the WiFi issue
([[ambient-temp-sensor-wifi-issue]]) is resolved:

1. Serial round-trip (via the existing devops-agent + pyserial setup) to confirm the board logs
   "HTTP server started" (or equivalent) with no traceback on boot.
2. `curl http://ambient-temp-sensor.local/sensors` from the `.60` rig — confirm valid JSON with
   all four fields.
3. Add the `rest:` block to HA's `configuration.yaml`, restart HA, confirm the four new sensor
   entities populate with non-null values within one `scan_interval`.

## Open questions / risks

- Exact `adafruit_httpserver` API (method names for non-blocking poll, response helpers) needs
  confirming against the version in the local bundle during implementation — the library's
  general shape (route handler classes/functions returning JSON) is confirmed via docs, but
  the precise non-blocking poll call wasn't verified against this specific bundled version.
- mDNS resolution can be flaky on some HA network setups (e.g. HA running in Docker without host
  networking, or a VLAN-segmented network) — if `ambient-temp-sensor.local` doesn't resolve from
  HA, fallback is a DHCP reservation for the board's MAC (`58:cf:79:ab:29:64`) instead.
