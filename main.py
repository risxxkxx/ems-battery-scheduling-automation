import json
import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from paho.mqtt.client import Client
from paho.mqtt.enums import CallbackAPIVersion


load_dotenv()


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def parse_clock(value: str) -> tuple[int, int]:
    try:
        hour_text, minute_text = value.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid time value: {value!r}. Expected HH:MM.") from exc

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Invalid time value: {value!r}. Expected HH:MM.")

    return hour, minute


# ================== CONFIG ==================

MQTT_BROKER = require_env("MQTT_BROKER")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = require_env("MQTT_USERNAME")
MQTT_PASSWORD = require_env("MQTT_PASSWORD")
CONTROLLER_SN = require_env("CONTROLLER_SN")

TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "Europe/Skopje"))

SELF_CONSUMPTION_START = parse_clock(require_env("SELF_CONSUMPTION_START"))
SELF_CONSUMPTION_END = parse_clock(require_env("SELF_CONSUMPTION_END"))
COST_START = parse_clock(require_env("COST_START"))
COST_END = parse_clock(require_env("COST_END"))

SITE_IMPORT_LIMIT_W = int(require_env("SITE_IMPORT_LIMIT_W"))
SITE_EXPORT_LIMIT_W = int(require_env("SITE_EXPORT_LIMIT_W"))

SITE_NODE_ID = f"{CONTROLLER_SN}_site_0"

PUBLISH_TOPIC = f"standard1/rp_one_s/remoteScheduleMetrics/{CONTROLLER_SN}"
FEEDBACK_TOPIC = f"standard1/outbound/remoteScheduleMetrics/feedback/{CONTROLLER_SN}"


client = Client(callback_api_version=CallbackAPIVersion.VERSION2)
client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

connected = False
set_ack_received = False


def next_time_range(
    start_h: int,
    start_m: int,
    end_h: int,
    end_m: int,
) -> tuple[int, int]:
    now = datetime.now(TIMEZONE)

    start = now.replace(
        hour=start_h,
        minute=start_m,
        second=0,
        microsecond=0,
    )

    if start < now:
        start += timedelta(days=1)

    end = start.replace(
        hour=end_h,
        minute=end_m,
        second=0,
        microsecond=0,
    )

    if end <= start:
        end += timedelta(days=1)

    return int(start.timestamp()), int(end.timestamp())


def fmt_ts(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=TIMEZONE).strftime(
        "%d.%m.%Y %H:%M:%S"
    )


def on_connect(client, userdata, flags, reason_code, properties=None):
    global connected

    if reason_code == 0:
        connected = True
        print("MQTT connection successful")
        client.subscribe(FEEDBACK_TOPIC, qos=1)
    else:
        print(f"MQTT connection error: {reason_code}")


def on_message(client, userdata, msg):
    global set_ack_received

    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        data = payload.get("data", {})

        message_type = data.get("message_type")
        response_code = data.get("responseCode")

        print(f"Feedback: {message_type} | responseCode={response_code}")

        if message_type == "set_schedules_ack":
            set_ack_received = True

            if response_code == 0:
                state = data.get("state", {})
                print("Schedules accepted")
                print(f"New schedule IDs: {state.get('schedule_ids')}")
                print(f"Removed overlapping IDs: {state.get('deleted_ids')}")
            else:
                print("Schedules were not accepted")
                print(json.dumps(data.get("error"), indent=2, ensure_ascii=False))

        if message_type == "get_future_schedules_ack":
            schedules = data.get("state", {}).get("schedules", [])
            print(f"Future schedules: {len(schedules)}")

            for schedule in schedules:
                start = schedule.get("start_time")
                end = schedule.get("end_time")

                start_text = fmt_ts(start) if start else "-"
                end_text = fmt_ts(end) if end else "-"

                print(
                    f"{start_text} -> {end_text} | "
                    f"device={schedule.get('device_type')} | "
                    f"policy={schedule.get('policy')}"
                )

    except Exception as exc:
        print(f"Feedback parse error: {exc}")


def add_schedule(
    schedule_list: list[dict],
    device_type: str,
    policy: str,
    start_clock: tuple[int, int],
    end_clock: tuple[int, int],
) -> None:
    start, end = next_time_range(
        start_clock[0],
        start_clock[1],
        end_clock[0],
        end_clock[1],
    )

    schedule_list.append(
        {
            "device_type": device_type,
            "start_time": start,
            "end_time": end,
            "policy": policy,
            "site_import": SITE_IMPORT_LIMIT_W,
            "site_export": SITE_EXPORT_LIMIT_W,
            "remove_overlap": True,
        }
    )


def build_schedules() -> list[dict]:
    schedules: list[dict] = []

    add_schedule(
        schedules,
        "storage",
        "self-consumption",
        SELF_CONSUMPTION_START,
        SELF_CONSUMPTION_END,
    )

    add_schedule(
        schedules,
        "solar",
        "feed-in-restriction",
        SELF_CONSUMPTION_START,
        SELF_CONSUMPTION_END,
    )

    add_schedule(
        schedules,
        "storage",
        "cost",
        COST_START,
        COST_END,
    )

    add_schedule(
        schedules,
        "solar",
        "feed-in-restriction",
        COST_START,
        COST_END,
    )

    return schedules


def publish_schedules(schedule_list: list[dict]) -> None:
    fields_payload = {
        str(index): json.dumps(schedule)
        for index, schedule in enumerate(schedule_list)
    }

    payload = {
        "extraTags": {"nodeId": SITE_NODE_ID},
        "time": int(time.time()),
        "message_type": "set_schedules",
        "fields": fields_payload,
    }

    client.publish(PUBLISH_TOPIC, json.dumps(payload), qos=1)


def request_future_schedules() -> None:
    payload = {
        "extraTags": {"nodeId": SITE_NODE_ID},
        "time": int(time.time()),
        "message_type": "get_future_schedules",
        "fields": {},
    }

    client.publish(PUBLISH_TOPIC, json.dumps(payload), qos=1)


def main() -> None:
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    client.loop_start()

    time.sleep(3)

    if not connected:
        client.loop_stop()
        client.disconnect()
        raise RuntimeError("MQTT connection failed")

    schedules = build_schedules()

    print("Schedules prepared:")
    for schedule in schedules:
        print(
            f"{fmt_ts(schedule['start_time'])} -> "
            f"{fmt_ts(schedule['end_time'])} | "
            f"device={schedule['device_type']} | "
            f"policy={schedule['policy']}"
        )

    publish_schedules(schedules)

    timeout_seconds = 10
    start_wait = time.time()

    while not set_ack_received and time.time() - start_wait < timeout_seconds:
        time.sleep(0.5)

    if not set_ack_received:
        print("No set_schedules_ack received within the timeout")
    else:
        request_future_schedules()
        time.sleep(5)

    client.loop_stop()
    client.disconnect()
    print("Finished")


if __name__ == "__main__":
    main()
