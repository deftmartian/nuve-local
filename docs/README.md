# Documentation

Start with the page that matches your task.

## Install or operate Nuve Local

| Page | Use it for |
| --- | --- |
| [Deployment and rollback](deployment.md) | First installation, endpoint redirection, pairing, verification, and rollback |
| [Maintenance](maintenance.md) | Development checks, packaging, and releases |
| [Security and privacy](security-privacy.md) | Stock-firmware risks and Nuve Local protections |
| [Thermostat platform](thermostat-platform.md) | A readable hardware and software overview |

## Understand the integration

| Page | Use it for |
| --- | --- |
| [Firmware architecture](firmware-architecture.md) | State flow, HVAC logic, telemetry, hardware ownership, and updates |
| [Field matrix](field-matrix.md) | Every recovered field and its Home Assistant status |
| [API catalog](api-contract-catalog.md) | All thermostat API routes and whether Nuve Local supports them |
| [Reference tests](live-validation-ledger.md) | Dated tests on the reference thermostat |
| [Version differences](version-differences.md) | What can and cannot be carried between firmware builds |

## Firmware subsystems

| Page | Subsystem |
| --- | --- |
| [Scheduling](scheduling-protocol.md) | V1/V2 schedules, holds, conflicts, and failure behavior |

## Private research

Reverse-engineering methodology and tooling, artifact inventories, emulators, and
security-sensitive firmware internals (boot and recovery, update channels, private
vendor APIs, hardware bus map, open questions) are kept in a separate private
repository and are not part of this documentation set.
