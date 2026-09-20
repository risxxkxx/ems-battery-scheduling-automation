"""
Sanitized portfolio version of an EMS battery scheduling automation.

All credentials, controller identifiers, broker details, power limits, and
operating periods are loaded from local environment variables. Do not commit
production .env files, logs, CSV exports, or controller payloads.
"""

import json
import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from paho.mqtt.client import Client
from paho.mqtt.enums import CallbackAPIVersion


load_dotenv()


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def as_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def as_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else default


def parse_hhmm(value: str) -> tuple[int, int]:
    try:
        hour_text, minute_text = value.split(":", 1)
        hour, minute = int(hour_text), int(minute_text)
    except (ValueError, AttributeError) as exc:
        raise ValueError("Time values must use HH:MM format.") from exc

    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("Time values must use a valid 24-hour HH:MM time.")

    return hour, minute


# ================== CONFIG ==================

MQTT_BROKER = required("MQTT_BROKER")
MQTT_PORT = as_int("MQTT_PORT", 1883)
MQTT_USE_TLS = as_bool("MQTT_USE_TLS", False)
MQTT_USERNAME = required("MQTT_USERNAME")
MQTT_PASSWORD = required("MQTT_PASSWORD")
CONTROLLER_SN = required("CONTROLLER_SN")

TIMEZONE = os.getenv("TIMEZONE", "UTC").strip() or "UTC"
EMS_TZ = ZoneInfo(TIMEZONE)

SELF_CONSUMPTION_START = required("SELF_CONSUMPTION_START")
SELF_CONSUMPTION_END = required("SELF_CONSUMPTION_END")
COST_START = required("COST_START")
COST_END = required("COST_END")

SITE_IMPORT_LIMIT_W = as_int("SITE_IMPORT_LIMIT_W", 0)
SITE_EXPORT_LIMIT_W = as_int("SITE_EXPORT_LIMIT_W", 0)
DEBUG_PAYLOADS = as_bool("DEBUG_PAYLOADS", False)

SITE_NODE_ID = f"{CONTROLLER_SN}_site_0"

PUBLISH_TOPIC = f"standard1/rp_one_s/remoteScheduleMetrics/{CONTROLLER_SN}"
FEEDBACK_TOPIC = (
    f"standard1/outbound/remoteScheduleMetrics/feedback/{CONTROLLER_SN}"
)

connected = False
set_ack_received = False


# ================== TIME HELPERS ==================

def next_time_range(start_value: str, end_value: str) -> tuple[int, int]:
    start_h, start_m = parse_hhmm(start_value)
    end_h, end_m = parse_hhmm(end_value)

    now = datetime.now(EMS_TZ)
    start = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)

    if start < now:
        start += timedelta(days=1)

    end = start.replace(hour=end_h, minute=end_m, second=0, microsecond=0)

    if end <= start:
        end += timedelta(days=1)

    return int(start.timestamp()), int(end.timestamp())


def fmt_ts(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=EMS_TZ).strftime("%d.%m.%Y %H:%M:%S")


# ================== MQTT CALLBACKS ==================

def on_connect(client, userdata, flags, reason_code, properties=None):
    global connected

    if reason_code == 0:
        connected = True
        print("MQTT connection established.")
        client.subscribe(FEEDBACK_TOPIC, qos=1)
        print("Subscribed to EMS feedback topic.")
    else:
        print(f"MQTT connection failed: {reason_code}")


def on_message(client, userdata, msg):
    global set_ack_received

    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        data = payload.get("data", {})

        message_type = data.get("message_type")
        response_code = data.get("responseCode")

        print(f"Feedback: {message_type} | responseCode={response_code}")

        # Raw payloads can contain controller or site identifiers.
        # Keep this disabled for normal/public use.
        if DEBUG_PAYLOADS:
            print(json.dumps(payload, indent=2, ensure_ascii=False))

        if message_type == "set_schedules_ack":
            set_ack_received = True

            if response_code == 0:
                print("Schedules accepted by EMS.")
            else:
                print("EMS rejected the schedule request.")

        if message_type == "get_future_schedules_ack":
            schedules = data.get("state", {}).get("schedules", [])
            print(f"Future schedules returned: {len(schedules)}")

            for schedule in schedules:
                start = schedule.get("start_time")
                end = schedule.get("end_time")

                if start and end:
                    print(
                        f"{fmt_ts(start)} -> {fmt_ts(end)} | "
                        f"device={schedule.get('device_type')} | "
                        f"policy={schedule.get('policy')}"
                    )

    except Exception as exc:
        print(f"Feedback parsing error: {exc}")


# ================== SCHEDULE BUILDING ==================

def build_schedule_list() -> list[dict]:
    schedules: list[dict] = []

    # Storage self-consumption window.
    start, end = next_time_range(
        SELF_CONSUMPTION_START,
        SELF_CONSUMPTION_END,
    )
    schedules.append(
        {
            "device_type": "storage",
            "start_time": start,
            "end_time": end,
            "policy": "self-consumption",
            "site_import": SITE_IMPORT_LIMIT_W,
            "site_export": SITE_EXPORT_LIMIT_W,
            "remove_overlap": True,
        }
    )

    # Solar feed-in restriction during the same window.
    schedules.append(
        {
            "device_type": "solar",
            "start_time": start,
            "end_time": end,
            "policy": "feed-in-restriction",
            "site_import": SITE_IMPORT_LIMIT_W,
            "site_export": SITE_EXPORT_LIMIT_W,
            "remove_overlap": True,
        }
    )

    # Storage cost-optimization window.
    start, end = next_time_range(COST_START, COST_END)
    schedules.append(
        {
            "device_type": "storage",
            "start_time": start,
            "end_time": end,
            "policy": "cost",
            "site_import": SITE_IMPORT_LIMIT_W,
            "site_export": SITE_EXPORT_LIMIT_W,
            "remove_overlap": True,
        }
    )

    # Solar feed-in restriction during the cost window.
    schedules.append(
        {
            "device_type": "solar",
            "start_time": start,
            "end_time": end,
            "policy": "feed-in-restriction",
            "site_import": SITE_IMPORT_LIMIT_W,
            "site_export": SITE_EXPORT_LIMIT_W,
            "remove_overlap": True,
        }
    )

    return schedules


def print_schedule_summary(schedules: list[dict]) -> None:
    print("Prepared schedules:")
    for index, schedule in enumerate(schedules):
        print(
            f"{index}: {fmt_ts(schedule['start_time'])} -> "
            f"{fmt_ts(schedule['end_time'])} | "
            f"device={schedule.get('device_type')} | "
            f"policy={schedule.get('policy')}"
        )


# ================== MAIN ==================

def main() -> None:
    global set_ack_received

    client = Client(callback_api_version=CallbackAPIVersion.VERSION2)
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

    if MQTT_USE_TLS:
        client.tls_set()

    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    client.loop_start()

    time.sleep(3)

    if not connected:
        client.loop_stop()
        client.disconnect()
        raise RuntimeError("Unable to establish MQTT connection.")

    schedule_list = build_schedule_list()
    print_schedule_summary(schedule_list)

    fields_payload = {
        str(index): json.dumps(schedule)
        for index, schedule in enumerate(schedule_list)
    }

    full_payload = {
        "extraTags": {"nodeId": SITE_NODE_ID},
        "time": int(time.time()),
        "message_type": "set_schedules",
        "fields": fields_payload,
    }

    print("Publishing schedule request.")
    client.publish(PUBLISH_TOPIC, json.dumps(full_payload), qos=1)

    timeout_seconds = 10
    start_wait = time.time()

    while not set_ack_received and time.time() - start_wait < timeout_seconds:
        time.sleep(0.5)

    if not set_ack_received:
        print("No schedule acknowledgement received within timeout.")
    else:
        print("Requesting future schedules for verification.")
        get_payload = {
            "extraTags": {"nodeId": SITE_NODE_ID},
            "time": int(time.time()),
            "message_type": "get_future_schedules",
            "fields": {},
        }
        client.publish(PUBLISH_TOPIC, json.dumps(get_payload), qos=1)
        time.sleep(5)

    client.loop_stop()
    client.disconnect()
    print("Finished.")


if __name__ == "__main__":
    main()
