# EMS Battery Scheduling Automation

Python automation for sending and verifying battery operating schedules over MQTT, with optional daily execution through Windows Task Scheduler.

## Problem

The battery scheduling workflow originally depended on a manual daily process. A price forecast and controller feedback had to be reviewed, the required operating periods had to be prepared, and the new schedules had to be submitted manually.

That created two practical problems:

- someone had to be available every day at the correct time;
- a missed or delayed update could leave the battery running with an outdated schedule.

## Solution

This project automates the scheduling workflow with Python and MQTT.

The script:

1. connects to an EMS controller through MQTT;
2. prepares storage and solar schedules from configurable time periods;
3. publishes them through the scheduling topic;
4. waits for a `set_schedules_ack` response;
5. verifies whether the schedules were accepted;
6. can request future schedules for an additional confirmation step.

A Windows batch file can be triggered manually or scheduled with Windows Task Scheduler so the workflow can run without daily manual intervention.

## Workflow

```text
Forecast / operating strategy
            ↓
      Python scheduler
            ↓
    Build schedule payload
            ↓
        MQTT publish
            ↓
      EMS controller
            ↓
  ACK + future schedules
            ↓
   Verification / logging
```

## Implementation Highlights

- MQTT communication with `paho-mqtt`
- configurable credentials and controller identifiers
- timezone-aware Unix timestamp generation
- support for overnight schedules
- acknowledgement handling
- future-schedule verification
- separate storage and solar operating policies
- environment-based configuration
- Windows Task Scheduler compatibility

## Tech Stack

- **Python**
- **MQTT / paho-mqtt**
- **python-dotenv**
- **Windows Batch**
- **Windows Task Scheduler**

## Project Structure

```text
.
├── main.py
├── run_ems.bat
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

## Local Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Create a local environment file

Copy the example file:

```bash
copy .env.example .env
```

Fill in the values for your own controller and environment.

### 3. Run the scheduler

```bash
python main.py
```

For Windows Task Scheduler, `run_ems.bat` can be used as the scheduled program.

## Configuration

The public repository contains **no production credentials or installation-specific values**.

Configuration is supplied through environment variables:

```env
MQTT_BROKER=
MQTT_PORT=1883
MQTT_USERNAME=
MQTT_PASSWORD=
CONTROLLER_SN=
TIMEZONE=Europe/Skopje

SELF_CONSUMPTION_START=
SELF_CONSUMPTION_END=
COST_START=
COST_END=

SITE_IMPORT_LIMIT_W=
SITE_EXPORT_LIMIT_W=
```

No real controller serial number, username, password, private broker hostname, customer name, factory name, or production power limit should be committed to this repository.

## Scheduling Logic

The public version keeps operating periods configurable rather than embedding production schedules in source code.

Two storage modes are demonstrated:

- `self-consumption`
- `cost`

Solar scheduling uses:

- `feed-in-restriction`

The exact time periods and import/export limits are loaded from the local environment.

## ACK Verification

After publishing `set_schedules`, the script waits for a `set_schedules_ack` message.

A response code of `0` is treated as a successful acknowledgement. The script can then request `get_future_schedules` and display the returned schedule periods for verification.

## Automation

The included batch file runs the Python script from the repository directory:

```bat
@echo off
cd /d "%~dp0"
python main.py
```

This file can be configured in Windows Task Scheduler for daily execution.

## Security

This repository is a **sanitized portfolio version** of the project.

The following must remain outside Git:

- MQTT usernames and passwords
- controller serial numbers and node identifiers
- API keys or tokens
- private/internal broker addresses
- customer, factory, or installation names
- production power limits and operating schedules
- generated CSV files and runtime logs that may contain operational identifiers

The included `.gitignore` excludes local environment files, logs, and CSV output.

## Result

The project replaces a repetitive manual scheduling process with a reproducible automated workflow. It reduces dependency on daily manual availability and adds acknowledgement and verification steps so schedule delivery can be checked programmatically.

## Author

**Riste Kozarev**

Portfolio: https://riste-kozarev.netlify.app/
