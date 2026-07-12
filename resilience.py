"""WiFi resiliency + offline queue for CircuitPython sensor nodes.

Shared pattern for the ESP32-S2 QT Py fleet: non-blocking reconnect with
radio reset, multi-network fallback, RAM-backed offline data queue with
NTP-stamped entries drained to Adafruit IO on reconnect.
"""

import time
import wifi
import rtc
import ssl
import socketpool
import adafruit_ntp
import adafruit_requests


def clock_valid():
    try:
        return time.localtime().tm_year >= 2025
    except Exception:
        return False


class WifiManager:
    def __init__(self, networks, retry_interval=30, attempt_timeout=10):
        self.networks = networks
        self.retry_interval = retry_interval
        self.attempt_timeout = attempt_timeout
        self.connected = False
        self.pool = None
        self.requests_session = None
        self._last_attempt = None
        self.time_synced = False

    def ensure_connected(self):
        """Non-blocking-ish connection keeper. Never raises.

        Returns True when wifi is up. When down, attempts a full
        radio-reset + all-networks round at most once per retry_interval.
        """
        if wifi.radio.connected:
            self.connected = True
            return True

        self.connected = False
        now = time.monotonic()
        if self._last_attempt is not None and (now - self._last_attempt) < self.retry_interval:
            return False

        self._last_attempt = now
        try:
            wifi.radio.enabled = False
            time.sleep(1)
            wifi.radio.enabled = True
        except Exception:
            pass

        for net in self.networks:
            try:
                wifi.radio.connect(
                    net["ssid"], net["password"], timeout=self.attempt_timeout
                )
                if self.pool is None:
                    self.pool = socketpool.SocketPool(wifi.radio)
                if self.requests_session is None:
                    self.requests_session = adafruit_requests.Session(
                        self.pool, ssl.create_default_context()
                    )
                self.connected = True
                self._sync_time()
                return True
            except Exception:
                continue

        return False

    def _sync_time(self):
        if self.time_synced:
            return
        try:
            ntp = adafruit_ntp.NTP(self.pool, tz_offset=0)
            rtc.RTC().datetime = ntp.datetime
            self.time_synced = True
        except Exception:
            pass


class OfflineQueue:
    """RAM ring buffer of (feed_key, value, epoch_ts_or_None) tuples."""

    def __init__(self, max_entries=40320):
        self._q = []
        self.max_entries = max_entries

    def append(self, feed_key, value):
        ts = time.time() if clock_valid() else None
        try:
            if len(self._q) >= self.max_entries:
                self._q = self._q[len(self._q) // 10:]
            self._q.append((feed_key, value, ts))
        except MemoryError:
            try:
                self._q = self._q[len(self._q) // 4:]
                self._q.append((feed_key, value, ts))
            except Exception:
                pass

    def __len__(self):
        return len(self._q)

    @staticmethod
    def _send(io, feed_key, value, iso):
        if iso is None:
            io.send_data(feed_key, value)
            return
        # adafruit_io's metadata path requires all four keys present.
        metadata = {"lat": None, "lon": None, "ele": None, "created_at": iso}
        try:
            io.send_data(feed_key, value, metadata=metadata)
        except (TypeError, KeyError):
            io.send_data(feed_key, value)

    def drain(self, io, max_sends=20):
        """Send oldest entries; stop on first failure. Returns count sent."""
        sent = 0
        while self._q and sent < max_sends:
            feed_key, value, ts = self._q[0]
            iso = None
            if ts is not None:
                t = time.localtime(ts)
                iso = "%04d-%02d-%02dT%02d:%02d:%02dZ" % (
                    t[0], t[1], t[2], t[3], t[4], t[5]
                )
            try:
                self._send(io, feed_key, value, iso)
            except Exception:
                break
            self._q.pop(0)
            sent += 1
        return sent
