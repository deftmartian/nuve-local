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
| [Firmware evidence](firmware-evidence.md) | Protocol behavior and the analysis behind supported controls |
| [Field matrix](field-matrix.md) | Every recovered field and its Home Assistant status |
| [API catalog](api-contract-catalog.md) | All thermostat API routes and whether Nuve Local supports them |
| [Traceability](traceability.md) | Safety requirements linked to code and tests |
| [Evidence ledger](evidence-ledger.md) | Claim-by-claim evidence strength |
| [Reference tests](live-validation-ledger.md) | Dated tests on the reference thermostat |
| [Version differences](version-differences.md) | What can and cannot be carried between firmware builds |
| [Open questions](remaining-unknowns.md) | Unknowns, impact, and evidence needed to answer them |

## Firmware subsystems

| Page | Subsystem |
| --- | --- |
| [Scheduling](scheduling-protocol.md) | V1/V2 schedules, holds, conflicts, and failure behavior |
| [Persistence](persistence-schema.md) | Saved object graph, timing, and corruption behavior |
| [Remote sensors](remote-sensors.md) | Sensor UI, pairing, and TI/NRF data paths |
| [Screen lock](lock-protocol.md) | Local PIN state and server lock path |
| [Equipment test](performance-test.md) | Performance-test state machine and relay risk |
| [Installer and warranty APIs](installer-private-api.md) | Private onboarding and identity workflows |
| [Messages and reset APIs](messages-reset-api.md) | Messages, alerts, identity, reset, and reporting |
| [Application update](application-update.md) | Normal application updater |
| [Recovery updater](recovery-updater.md) | Recovery-file planner and copy path |
| [Boot and recovery](boot-update-recovery.md) | U-Boot update and factory-restore paths |

## Research inventories

| Page | Inventory |
| --- | --- |
| [Artifact inventory](artifact-inventory.md) | Private corpus metadata and hashes |
| [Function inventory](function-inventory.md) | Native and QV4 structural coverage |
| [UI action register](ui-action-register.md) | Every recognized QML event handler |
| [Hardware and bus map](hardware-bus-map.md) | Components, buses, GPIOs, watchdogs, and electrical unknowns |
