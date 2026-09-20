# Security

This repository is a sanitized portfolio example of an EMS scheduling automation.

## Never commit

- MQTT usernames or passwords
- controller serial numbers, node IDs, or device identifiers
- private/internal broker hostnames
- API keys, access tokens, or exported credentials
- customer, factory, site, or installation names
- production power limits, tariffs, or operating schedules
- runtime CSV files, logs, acknowledgements, or raw MQTT payload dumps

## Local configuration

Use a local `.env` file based on `.env.example`. The real `.env` file is excluded by `.gitignore`.

For production deployments, prefer machine-level environment variables or a managed secret store where available.

## Runtime logging

`DEBUG_PAYLOADS` should remain `false` in normal operation because raw feedback payloads may contain controller or site identifiers.

## Transport security

If the MQTT broker supports TLS, set `MQTT_USE_TLS=true` and use the broker's TLS port/configuration.
