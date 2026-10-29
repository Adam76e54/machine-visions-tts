#!/usr/bin/env python3
"""
Toolbox Tracker — Pi client

When GPIO17 changes from HIGH to LOW:
  1. Wait briefly for the drawer to settle.
  2. Take a photo with the USB camera.
  3. POST it to the server.

Wiring:
  3.3 V -> switch -> GPIO17 (physical pin 11)
  Internal pull-down enabled.

Test without the switch:
  python3 main.py --test

Normal operation:
  python3 main.py

Starting with GPIO already LOW does not trigger a photo.
"""

import argparse
import logging
import queue
import sys
import time

import cv2
import requests
from gpiozero import DigitalInputDevice


# ── Settings ────────────────────────────────────────────────────────────────

SERVER = "http://10.43.241.117:8000"
SENSOR_PIN = 17  # BCM GPIO17 = physical pin 11

PHOTO_DELAY = 0.5
DEBOUNCE = 0.05
HEARTBEAT_INTERVAL = 30.0

RETRY_COUNT = 3
RETRY_DELAY = 2.0


# ── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("pi_client.log"),
    ],
)

log = logging.getLogger(__name__)


# ── Camera ──────────────────────────────────────────────────────────────────

def open_camera():
    device = "/dev/video0"
    cam = cv2.VideoCapture(device, cv2.CAP_V4L2)

    if not cam.isOpened():
        cam.release()
        raise RuntimeError(f"Could not open camera on {device}")

    cam.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    log.info("Camera opened: %s", device)
    return cam


def take_photo(cam) -> bytes:
    frame = None

    # Read several frames to allow exposure to settle and discard old frames.
    for _ in range(30):
        ok, frame = cam.read()

        if not ok or frame is None:
            raise RuntimeError("Camera read failed")

        time.sleep(0.03)

    ok, jpeg = cv2.imencode(".jpg", frame)

    if not ok:
        raise RuntimeError("JPEG encode failed")

    image_bytes = jpeg.tobytes()
    log.info("Photo captured (%d bytes)", len(image_bytes))

    return image_bytes


# ── Networking ──────────────────────────────────────────────────────────────

def send_photo(image_bytes: bytes) -> bool:
    """Upload a photo, retrying connection failures and server errors."""

    for attempt in range(1, RETRY_COUNT + 1):
        try:
            with requests.post(
                f"{SERVER}/api/events",
                files={
                    "image": ("photo.jpg", image_bytes, "image/jpeg"),
                },
                timeout=(5, 15),
            ) as resp:
                # Client errors generally need a configuration/server fix.
                if 400 <= resp.status_code < 500:
                    log.error(
                        "Server rejected photo: HTTP %d — %s",
                        resp.status_code,
                        resp.text[:300],
                    )
                    return False

                # Server errors are retried below.
                resp.raise_for_status()

                # A successful upload need not include a JSON response.
                try:
                    data = resp.json()
                except ValueError:
                    data = None

                if isinstance(data, dict):
                    log.info(
                        "Upload successful — event_id=%s",
                        data.get("event_id"),
                    )
                else:
                    log.info(
                        "Upload successful — HTTP %d",
                        resp.status_code,
                    )

                return True

        except requests.exceptions.RequestException as exc:
            log.warning(
                "Upload attempt %d/%d failed: %s",
                attempt,
                RETRY_COUNT,
                exc,
            )

            if attempt < RETRY_COUNT:
                time.sleep(RETRY_DELAY)

    log.error("All upload attempts failed — photo not saved locally")
    return False


def send_heartbeat() -> None:
    try:
        with requests.post(
            f"{SERVER}/api/heartbeat",
            timeout=5,
        ) as resp:
            resp.raise_for_status()

    except requests.exceptions.RequestException as exc:
        log.warning("Heartbeat failed: %s", exc)


# ── Drawer event ────────────────────────────────────────────────────────────

def on_drawer_closed(cam) -> bool:
    log.info(
        "Drawer closed — waiting %.1fs before photo",
        PHOTO_DELAY,
    )

    time.sleep(PHOTO_DELAY)

    try:
        photo = take_photo(cam)
        return send_photo(photo)

    except Exception:
        log.exception("Failed to capture/send photo")
        return False


# ── Main ────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Toolbox Tracker Pi client",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Take and upload one photo without using the switch",
    )
    args = parser.parse_args()

    log.info("Toolbox Tracker Pi client starting")
    log.info("Server: %s", SERVER)

    cam = None
    sensor = None

    try:
        cam = open_camera()

        if args.test:
            log.info("TEST MODE — taking and uploading one photo")

            photo = take_photo(cam)
            success = send_photo(photo)

            if success:
                log.info("Test passed. Check the dashboard.")
                return 0

            log.error("Test failed. Check the server and IP address.")
            return 1

        # Queue close events so the GPIO callback does not operate the camera.
        close_events = queue.SimpleQueue()

        sensor = DigitalInputDevice(
            SENSOR_PIN,
            pull_up=False,
            bounce_time=DEBOUNCE,
        )

        def queue_drawer_closed():
            close_events.put(time.monotonic())
            log.info("GPIO changed from HIGH to LOW — event queued")

        sensor.when_deactivated = queue_drawer_closed

        log.info(
            "Watching GPIO%d — initial reading: %d",
            SENSOR_PIN,
            int(sensor.value),
        )
        log.info("Trigger: 1 -> 0. Press Ctrl+C to stop.")

        next_heartbeat = time.monotonic()

        while True:
            now = time.monotonic()

            if now >= next_heartbeat:
                send_heartbeat()
                next_heartbeat = time.monotonic() + HEARTBEAT_INTERVAL

            try:
                event_time = close_events.get(timeout=0.1)
            except queue.Empty:
                continue

            log.info(
                "Processing drawer event (queued %.1fs ago)",
                time.monotonic() - event_time,
            )
            on_drawer_closed(cam)

    except KeyboardInterrupt:
        log.info("Stopped.")
        return 0

    except Exception:
        log.exception("Pi client failed")
        return 1

    finally:
        if sensor is not None:
            sensor.close()

        if cam is not None:
            cam.release()

        log.info("Resources released")


if __name__ == "__main__":
    sys.exit(main())