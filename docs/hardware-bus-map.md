# Firmware 1.5.8 hardware and bus map

This map applies to the recovery `1.5.8` application with SHA-256
`2117a5456445fe57a851ecf09aa452a8d3a2a59d166d4c6f5475bb69d5151c8e`
and device tree with SHA-256
`0524701e0feac4e7f3913555134b80277ffd802d3be60aaa15e6a3c2828496e7`.
It combines the device tree, application, service units, recovery filesystem, and
photographs of the installed mainboard. Electrical behavior that would require
continuity measurements, a schematic, or secondary-controller firmware remains
unknown.

The installed unit was photographed but was not probed, reset, or used for electrical
tests. The six original photographs are stored privately; this page records only the
visible component markings and board labels needed for the hardware map.

## Ownership boundary

```text
                         Samo thermostat mainboard

  Network/API                   NXP i.MX6 SoloLite                    Display
  over Wi-Fi           +--------------------------------+     +------------------+
       <-------------->| appStherm / Qt 6 / Linux       |---->| LCDIF pixel bus  |
                       |                                |     | SPI panel config |
  eMMC <-------------->| storage, UI, policy, control  |     | I2C touch        |
  SD/service slot <----| state machine, telemetry      |     | PWM backlight    |
                       |                                |     +------------------+
                       | UART2 /dev/ttymxc1, 9600 8N1  |
                       |<------------------------------>| NRF-side sensor MCU
                       |      GPIO21 data-ready         |   sensors / ToF data
                       |      GPIO22 ToF-ready          |
                       |                                |
                       | UART4 /dev/ttymxc3, 9600 8N1  |
                       |<------------------------------>| TI-side HVAC controller
                       |      packets and heartbeat     |   terminals / relays
                       +--------------------------------+
```

The application computes requested and effective HVAC state on the i.MX6, then
serializes logical relay commands for the TI-side controller. It does not drive
the equipment terminals directly through i.MX6 GPIO. Similarly, the application
receives already processed environmental and proximity values through the
NRF-side path; the sensor chips are not direct Linux I2C children in this device
tree.

## Processor, memory, and console

| Item | Exact evidence | Disposition |
| --- | --- | --- |
| Board model | Root `model` is `Hardware Design House - Samo Thermostat Mainboard`; installed-board silk is `HVAC021-C2-MAIN` and the visible revision label is `v1.3.1.1` | Exact DT and photographic identity; the separate `08.25` label is recorded but not interpreted as a date |
| Processor | U4 is marked `MCIMX6L3DVN10AC`; root compatibles are `fsl,imx6sl-evk` and `fsl,imx6sl` | Exact installed [NXP i.MX 6SoloLite](https://www.nxp.com/part/MCIMX6L3DVN10AC), single Cortex-A9 up to 1 GHz, 13 mm TFBGA432 |
| RAM | U5 is marked `NT6TL256T32BQ-60`; `/memory` is `0x80000000` + `0x40000000` | Exact installed 8 Gbit LPDDR2 marking and corroborating 1 GiB physical address range |
| CMA | `/reserved-memory/linux,cma` size `0x14000000` | 320 MiB default contiguous DMA pool |
| Console | `/chosen/stdout-path` points to serial0/UART1 at `0x02020000` | Kernel/boot console path; physical connector and voltage are unknown |
| SoC temperature | `tempmon` is present; the app reads `/sys/class/thermal/thermal_zone%1/temp` | Linux thermal telemetry path, separate from room temperature |
| Device identity | OCOTP exists and the app reads `HW_OCOTP_CFG0`, `HW_OCOTP_CFG1`, and `HW_OCOTP_GP1` | Exact read path; fuse meaning and provisioning policy are not fully recovered |

## Installed-board photographic evidence

| Ref | Visible marking | What it tells us |
| --- | --- | --- |
| U3 | `MMPF0100 F1AEP` | Installed [NXP PF0100](https://www.nxp.com/docs/en/data-sheet/MMPF0100.pdf) configurable PMIC; consistent with the DT's `pfuze100` family binding |
| U7 | `THGBMTG5D1LBAIL` | Installed 4 GB, eMMC 5.0 managed-flash device; the [Kioxia product brief](https://americas.kioxia.com/content/dam/kioxia/en-us/business/application/iot/asset/KIOXIA_e-MMC_Product_Brief.pdf) corroborates capacity, interface revision, and package |
| U18 | `N52832 QFAAE1` | Installed [Nordic nRF52832](https://docs-be.nordicsemi.com/bundle/nRF52832-PS/raw/resource/enus/nRF52832_PS_v1.8.pdf) QFAA, revision-2 build marking; this closes the mainboard NRF silicon identity, not its firmware, readback-protection state, packet ownership, or radio/sensor algorithm |
| U9 | `AP6256 SISO` | Installed [AMPAK AP6256](https://www.ampak.com.tw/product/WiFi-Bluetooth/stamp-type-1T1R/AP6256) Wi-Fi/Bluetooth module; its documented SDIO Wi-Fi and UART Bluetooth interfaces agree with the board's SDIO topology but do not prove Bluetooth is enabled here |
| U17 | `NAU88C22` | Installed [Nuvoton NAU88C22](https://www.nuvoton.com/products/smart-home-audio/audio-converters/audio-codec-series/nau88c22yg/index.html) audio codec; the active runtime route remains unresolved because enabled SSI nodes alone do not establish AUDMUX/application ownership |

The back silk exposes `DEBUG`, `D-RX`, `D-TX`, `RX2`, `TX2`, `SDA3`, `SCL3`,
`J-TCK`, `J-TMS`, `J-TDI`, `J-TDO`, `J-TRSTn`, `SRSTn`, and an SD-style
`SD00`-`SD03`/`SDCLK`/`SDCMD` pad group. These labels make a future donor-board
continuity plan specific, but they do not identify voltage, processor ownership,
direction, or safe connector pinout. The installed unit must not be used to resolve
those questions.

## UART and secondary controllers

The constructor at `DeviceIOController::DeviceIOController` (`0x33e3b4`) binds
the exact device paths. The two connection factories and `UARTConnection` then
establish the runtime settings. Both application links use 9600 baud, 8 data
bits, no parity, 1 stop bit, and no flow control. The device-tree
`current-speed=115200` and `hw-flow-control` properties on UART2 are defaults;
the application's later termios configuration is authoritative for its session.

| DT alias / controller | Linux device | Exact application owner | Role | Status |
| --- | --- | --- | --- | --- |
| serial0 / UART1 `0x02020000` | Console | No application transport owner | Boot/kernel console | DT `okay` |
| serial1 / UART2 `0x02024000` | `/dev/ttymxc1` | `createNRF` (`0x32c16c`) | NRF-side sensors, ToF/luminosity, and related responses | DT `okay`; app 9600 8N1 |
| serial2 / UART3 `0x02034000` | Expected `/dev/ttymxc2` | None established | Enabled but application-unowned | DT `okay`; physical use unknown |
| serial3 / UART4 `0x02038000` | `/dev/ttymxc3` | `createTIConnection` (`0x3330f8`) | HVAC controller requests, responses, relay delivery, heartbeat | DT `okay`; app 9600 8N1 |
| serial4 / UART5 `0x02018000` | Not used | None | No active path | DT `disabled` |

Both application links carry `STHERM::SIOPacket` objects whose exact in-memory
size is `0x108` bytes. This establishes the Linux-side framing boundary. The
photographs establish an nRF52832 on the mainboard, but do not establish the
electrical transceivers, TI MCU model, nRF/TI bootloaders and firmware, exact pad
ownership, or every packet-side safety rule.

## GPIO interrupt contract and exact defect

`DeviceIOController` constructs handlers for Linux global GPIO numbers 21 and
22. `createNRF` configures both. GPIO21 starts the general NRF data-ready path;
`startTOFGpioHandler` (`0x32a694`) starts GPIO22 and its event callback leads to
`checkTOFLuminosity`.

| Linux GPIO | Exact application role | Trigger setup | Remaining physical uncertainty |
| ---: | --- | --- | --- |
| 21 | NRF data-ready/receive trigger | sysfs `edge=falling` | Legacy i.MX numbering strongly indicates GPIO1_IO21; pad, net name, polarity source, and electrical pull are unproven |
| 22 | ToF/luminosity-ready trigger | sysfs `edge=falling` | Legacy i.MX numbering strongly indicates GPIO1_IO22; pad, net name, polarity source, and electrical pull are unproven |

Application logs call these “GPIO 4” and “GPIO 5.” Those are stale schematic or
logical labels, not the Linux global numbers supplied to sysfs.

There is an exact implementation defect in `UtilityHelper::configurePins`
(`0x325ef4`):

1. it writes the numeric pin to `/sys/class/gpio/export`;
2. it opens `/sys/class/gpio/gpio%0/direction`;
3. it writes the literal `/usr/local/bin` instead of `in`;
4. it opens `/sys/class/gpio/gpio%0/edge` and writes `falling`; and
5. it treats successful file opens as success without establishing that the
   direction write succeeded.

`UtilityHelper::exportGPIOPin` (`0x31e784`) contains the same invalid literal on
its input branch; only its output branch writes the valid value `out`. A newly
exported legacy sysfs GPIO normally begins as an input, which can allow falling
edge setup to work despite the bad write. A process restart with an already
exported line could depend on retained direction or another actor. This is an
availability/reliability defect, not evidence that the function validly sets an
input. It is not corrected by Nuve Local because the integration does not modify
thermostat firmware or sysfs.

## HVAC terminal and relay boundary

The native control stack computes effective modes, thresholds, minimum-on/off
timing, stage decisions, fan arbitration, accessory behavior, and the complete
logical relay set. `DeviceIOController::sendRelays` (`0x336014`) then sends that
set through `/dev/ttymxc3` to the TI-side controller. Responses supply the actual
stage and fan observations that reach telemetry.

The recovered application proves packet production and its logical safety rules.
It does **not** prove:

- the TI MCU model or exact firmware;
- terminal-driver polarity, isolation, contact ratings, or failure modes;
- board-side enforcement when Linux hangs or sends malformed packets;
- physical relay/contact state from a Linux command alone; or
- actual airflow, refrigerant flow, flame, or equipment operation.

Those require the TI firmware, schematic/BOM, or isolated bench instrumentation.
The connected thermostat is not an acceptable fault-injection target.

## Sensor and proximity boundary

The exact application receives processed temperature, humidity, pressure, IAQ
family, and related values from the NRF-side link. The installed mainboard carries
an nRF52832-QFAA at U18, while prior board inspection identified ZMOD4410 and SHT25
parts. They are not children of an enabled i.MX6 I2C controller in this device tree.
This is consistent with secondary-controller ownership rather than direct Linux
ownership, but only continuity or secondary firmware can bind each physical net to
the recovered UART/GPIO contract.

VL53L0X-related strings occur in the exact application, and the GPIO22 callback
path receives ToF range/luminosity data. That establishes an application-side
feature family, not the exact sensor variant, driver/library revision,
calibration, optical geometry, or secondary-firmware algorithm. Remote-sensor
pairing is also a secondary-firmware/radio boundary; its application-side model is
documented separately in [remote-sensors.md](remote-sensors.md).

## Display, touch, and backlight

| Function | Exact topology | Application boundary |
| --- | --- | --- |
| Pixel output | LCDIF at `0x020f8000`, endpoint linked to the panel | `appStherm.service` launches Qt with `-platform linuxfb` and `QT_QPA_FB_DRM=1` |
| Panel setup | ECSPI2 at `0x0200c000`, CS0 child compatible with `techstar,ts8550b` and `sitronix,st7701`; CPOL+CPHA; 1 MHz maximum | Kernel panel driver owns low-level initialization; exact physical panel revision remains board-specific |
| Panel reset/power | GPIO2 line 19 active-high flag; PFUZE `sw2` supply | Exact DT connection |
| Touch | I2C2 at `0x021a4000`, 100 kHz; EDT FT5x06 at `0x38`; 480 by 480 | IRQ GPIO2 line 10 active-low/type 2; reset GPIO3 line 30 active-low |
| Backlight | PWM1 at `0x02080000`, channel 0, 5,000,000 ns period | 200 Hz PWM; 255 levels from 1 through 255; DT default 125 |

`UtilityHelper::setBrightness` (`0x323a28`) writes a decimal value to
`/sys/class/backlight/backlight_display/brightness`.
`DeviceIOController::setBrightness` (`0x328290`) selects and caches the effective
manual/adaptive value before that write. UI and persistence semantics are
separate from this physical path and are summarized in
[firmware-architecture.md](firmware-architecture.md).

## Storage and network

| Controller | Exact DT role | Recovered runtime role |
| --- | --- | --- |
| USDHC1 `0x02190000` | 4-bit removable media, card-detect on GPIO3 line 24 active-low | Enabled service/removable slot; connector and supported field workflow are unproven |
| USDHC2 `0x02194000` | 8-bit non-removable media | Photographed U7 is `THGBMTG5D1LBAIL`, a 4 GB eMMC 5.0 device observed as `/dev/mmcblk1`; updater/recovery references partitions 3 and 4 |
| USDHC3 `0x02198000` | 4-bit non-removable `wifi-host` with child compatible `brcm,bcm4329-fmac` | Photographed U9 is an AP6256 SISO module; SDIO Wi-Fi runs under NetworkManager and the recovery root carries `brcmfmac.ko` plus matching 43456-family firmware/NVRAM |
| USDHC4 `0x0219c000` | Disabled | No active path |

The photographed AP6256 marking closes the previously generic radio-module identity
and is consistent with the SDIO/device-file evidence. Antenna and RF routing,
Bluetooth enablement, module firmware provenance, and current runtime state remain
unknown.

Ethernet FEC and every USB controller are disabled in the exact device tree, so
Wi-Fi is the only established normal network path.

The update and recovery partitioning, write order, and authenticity failures are
documented in [application-update.md](application-update.md),
[recovery-updater.md](recovery-updater.md), and
[boot-update-recovery.md](boot-update-recovery.md).

## Three distinct watchdog paths

The exact build contains three mechanisms that must not be conflated:

1. **TI heartbeat.** `DeviceIOController::wtdExec` (`0x330ba0`) checks
   `IsTIWatchdogEnabled`, requires the TI UART to be connected, builds an empty
   type/direction-1 `SIOPacket` command `0x34`, and sends it through
   `sendTIRequest`. This is a UART heartbeat, not `/dev/watchdog`.
2. **NRF-data watchdog.** `NRFWatchdog` arms a single-shot precise 120,000 ms
   timer while the persisted restart count permits it. Two minutes without
   qualifying NRF sensor data increments that counter and disables TI heartbeats
   through `setIsTIWatchdogEnabled(false)`. It does not directly call Linux
   reboot. The apparent recovery chain depends on unseen TI-side behavior.
3. **i.MX6 watchdog hardware.** watchdog1 at `0x020bc000` is enabled in the DT and
   has `fsl,ext-reset-output`; watchdog2 is disabled. The exact systemd defaults
   leave `RuntimeWatchdogSec=0`, and `appStherm.service` has no `WatchdogSec` or
   notify contract. No exact recovery-root watchdog daemon or application
   `/dev/watchdog` path was found. Presence in the DT is therefore not proof that
   Linux arms it during normal operation.

The persisted NRF restart limiter suppresses repeated watchdog arming after more
than one recorded restart. The exact TI-side timeout, reset target, electrical
effect, and behavior when heartbeats stop remain unresolved until its firmware or
schematic is available.

## Other enabled and disabled interfaces

- I2C1 at `0x021a0000` runs at 100 kHz and owns the PFUZE100 PMIC at address
  `0x08`; I2C3 is disabled.
- ECSPI1, ECSPI3, and ECSPI4 are disabled. ECSPI1 has a dormant `m25p80` child,
  but a child below a disabled parent is not an active flash path.
- Three SSI nodes are marked `okay`, while AUDMUX is disabled and no exact
  application consumer was established. The photographed NAU88C22 closes the
  installed codec identity, but audio runtime ownership remains unresolved rather
  than assumed.
- A GPIO LED on GPIO3 line 20 is labeled `debug` and uses the Linux `heartbeat`
  trigger.
- Hardware RNG, OCOTP, and DCP nodes exist. `rngd.service` is enabled in the
  recovery root. None of those facts establishes cryptographic publisher
  authentication for application or recovery updates; those paths remain
  unauthenticated as documented in the update analysis.
- CSI, EPDC, keypad, Ethernet, USB, UART5, USDHC4, and the remaining SPI
  controllers are disabled or lack an application owner.
- No `gpio-keys` or button node appears. U-Boot's recovery selection reads GPIO102,
  but the physical button/net and electrical polarity remain unresolved.

## Reproduction

The checked-in parser is read-only and emits decoded metadata to stdout. Against
a verified private copy:

```bash
.venv/bin/python scripts/inventory_device_tree.py \
  <private-corpus>/imx6sl-evk.dtb
```

Use `--node-pattern` and `--property-pattern` to make a reviewable subset. Recheck
the DTB hash before relying on an address or status. Do not copy the private DTB,
recovery filesystem, configuration, captures, or credentials into the worktree.

## Exact remaining unknowns

| Unknown | Why static application/DT evidence cannot close it | Required evidence |
| --- | --- | --- |
| TI-side MCU, firmware, terminal electrical design, and heartbeat/reset behavior | The i.MX6 sees only UART packets and responses; the separate HVAC controller is not visible in the mainboard photographs | Exact secondary board photographs, firmware, and schematic/BOM; isolated donor-board harness if permitted |
| nRF52832 firmware, readback-protection state, sensor drivers, algorithms, calibration, and pairing | U18 establishes the installed MCU identity, while the i.MX6 receives only processed values and interrupt indications | Exact nRF52832 firmware/vendor protocol plus schematic/BOM; protection-status or continuity work only on a donor board |
| GPIO21/22 pad/net/pull/electrical mapping and restart behavior after invalid direction write | Linux global number and app literals do not establish board wiring or all sysfs initial states | Schematic/kernel source plus cloned-kernel sysfs harness; optional isolated logic trace |
| GPIO102 recovery-button identity and polarity | U-Boot numeric read has no DT button description | Schematic or separately approved read-only physical correlation with HVAC isolated |
| UART3 and SSI physical ownership | Enabled DT nodes have no exact application consumer | Schematic and boot/runtime ownership evidence |
| Visible debug/test-point electrical ownership | Silk labels do not establish voltage, net continuity, processor ownership, direction, or safe pinout | Schematic or continuity measurement on a disposable unpowered donor board |
| AP6256 antenna/RF integration, Bluetooth enablement, and module firmware provenance | The exact module marking and host software stack do not establish board RF routing or enabled runtime functions | Schematic/module configuration plus a cloned or separately approved read-only runtime inventory |
| Active i.MX6 watchdog policy | Enabled hardware node is not an arming policy | Exact live read-only boot logs/register status or a cloned target harness |

These are evidence gaps, not permission to probe the connected thermostat. They
remain unsupported until the listed artifact or an approved safe
experiment exists.
