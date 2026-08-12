# Firmware 1.5.8 remote-sensor path

This sensor path comes from `appStherm` SHA-256
`2117a5456445fe57a851ecf09aa452a8d3a2a59d166d4c6f5475bb69d5151c8e`.
The configurable sensor UI and TI/NRF environmental-data path are separate systems.

## Data model

Exact `Sensor.qml` at binary file offset `6374912` declares a `QSObject` with:

| Property | Type | Default |
| --- | --- | --- |
| `name` | string | empty |
| `type` | int | `SensorType.OnBoard` (`0`) |
| `strength` | int | `100` |
| `battery` | int | `100` |
| `location` | int | `SensorLocation.Unknown` (`0`) |

The QML-only `SensorType` enum is `OnBoard=0`, `Wireless=1`. `SensorLocation`
declares `Unknown=0`, `Other=1`, `Bedroom=2`, `LivingRoom=3`, `KidsRoom=4`,
`Bathroom=5`, `Kitchen=6`, `Basement=7`, `MainFloor=8`, `Office=9`,
`Upstairs=10`, `Downstairs=11`, `DiningRoom=12`, and `GuestHouse=13`. The picker
offers the 13 non-Unknown choices.

`I_Device.qml` owns two distinct arrays:

- public `sensors`, loaded/persisted with the device object and populated by the
  server-shaped Settings state; and
- private `_sensors`, excluded by the leading-underscore serializer rule and used
  by the visible sensor list and the complete Settings upload builder.

At `SensorController.onCompleted`, exact QV4 first replaces `_sensors` with an empty
array. It iterates public `sensors` only to log `name` and `location`; it never copies
any entry into `_sensors`. The private snapshot from the reference unit contains
empty sensor arrays, so it supplies shape evidence but no populated-row example.

## Pairing UI is disconnected

`SensorPairPage.qml` at file offset `8027104` declares:

```text
sensorPaired(sensor: Sensor)
sensorPairingCanceled()
```

The Ok button starts a one-second repeating countdown at 60 seconds. This changes
the page into its `pairing` state and keeps the screen saver inactive. It does not
call `deviceController`, `createSensor`, `getPairedSensors`, `addPendingSensor`, or
the page's own empty `startPairing()` function. At zero it displays `No sensor is
found.`, then the next tick stops and emits only `sensorPairingCanceled()`.

The exhaustive 8,988-function QV4 inventory contains no call to `startPairing` and
no emitter of `sensorPaired`. The page's `deviceController` property is resolved but
never used. The native methods are also inert in exact 1.5.8:

| Native method | Exact behavior |
| --- | --- |
| `DeviceIOController::createSensor(QString, QString)` (`0x328384`) | returns immediately |
| `DeviceIOController::getPairedSensors()` (`0x3286a8`) | returns an empty/default value |
| `DeviceIOController::addPendingSensor(DeviceType)` (`0x3286bc`) | returns true without work |

No subclass override or separate remote-sensor CRUD route exists in the exact
defined-symbol or 38-route API inventory. Consequently, the stock Add Sensor flow
cannot advance from pairing to the name page through any statically reachable
application path in this build. Whether an unavailable secondary-board firmware
has a radio-pairing implementation cannot repair the missing application call.

## Add, edit, remove, and Settings upload

If some external actor were to emit `sensorPaired(Sensor)`, the Add Sensor page
would collect a name and one of the 13 locations, register the object with the
default repository, and append it only to `device._sensors`. It does not call
`saveSettings` or a native pairing method.

The sensor-info page edits `sensor.name` or `sensor.location` in place. It likewise
does not save, explicitly emit `_sensorsChanged`, or push Settings. A later unrelated
full Settings push would nevertheless read the mutated private object.

`SensorController.removeSensor` is not called by any QV4 function or visible
control. Its implementation is internally inconsistent: it finds the object by
identity in public `device.sensors`, then splices the same numeric index from private
`device._sensors`. A runtime-only object is therefore normally not found; if the
arrays differ, it can remove the wrong private object.

There is no dedicated remote-sensor API. A full `POST /api/sync/update` projects
each private `_sensors` object to:

```json
{"name":"<name>","location":"Office|Bedroom","type":"OnBoard|Wireless","uid":"213137"}
```

The projection is defective and lossy:

- location `0` becomes `Office`; every other value `1..13` becomes `Bedroom`;
- type `0` becomes `OnBoard`; every other integer becomes `Wireless`;
- every row receives the same literal UID `213137`; and
- `strength` and `battery` are omitted.

On the reverse Settings path, `DeviceController.checkSensors` merely logs
`location`, `name`, `type`, `uid`, and the misspelled `locationsd`. It changes no
array and returns no usable value. It performs even less work while the Sensors edit
bit is set. Thus server rows cannot repopulate the visible private array.

`POST /api/device/current-sensors?sn=...` is unrelated: it publishes current room
temperature, humidity, and categorical IAQ. It is not a remote-sensor CRUD endpoint.

## Evidence and disposition

Exact QML declarations/bytecode, native stubs, native route inventory, and the
private empty-array shape provide **A (exact static)** evidence. The isolated
[sensor emulator](../scripts/emulate_firmware_sensors.py) reproduces
startup clearing, no-op server reconciliation, dead pairing initiation, add/remove
array ownership, and the lossy upload projection for **B (emulated)** evidence.

Remote-sensor control must remain unsupported. The exact application-side add,
edit, delete, restart, and server-reconciliation paths are not merely unvalidated;
they are disconnected or internally inconsistent.

## Remaining unknowns

- **U:** photographed nRF52832 firmware, radio protocol/configuration, calibration,
  battery/signal ingestion, and actual board-side pairing behavior;
- **U:** vendor-server acceptance and interpretation of the literal UID and lossy
  location mapping;
- **U:** whether another application build repaired these paths; and
- **U:** any live behavior produced by vendor-side or secondary-firmware components
  absent from the exact corpus.
