# nRF52832 firmware and DFU channel

This page covers the mainboard nRF52832 (U18) application firmware and the path that
`appStherm` uses to update it. It applies to `appStherm` `1.5.8` with SHA-256
`2117a5456445fe57a851ecf09aa452a8d3a2a59d166d4c6f5475bb69d5151c8e`; addresses are
specific to that build. The analysis was offline: no thermostat, Home Assistant, or
vendor service was contacted.

Evidence marks: **[E]** observed in the artifact (address, string, decoded field);
**[I]** inference from that evidence.

## Package

| Item | Value |
| --- | --- |
| Location | Qt resource `:/Stherm/Backend/scripts/nrf_fw_update.zip` in `appStherm`; staged to `/mnt/update/nrf_fw/update.zip` [E] |
| Package SHA-256 | `022961673cb0b48d3c859240538c0386150593a17a250c4c0d436bfe460df775` (103,945 bytes, identical in 1.5.7.4 and 1.5.8) [E] |
| `dfu_client.bin` SHA-256 | `8d339916b3ca6967089060137d2c6d476a89f9064dda170a6151ffcffc14ac37` (103,320 bytes) [E] |
| Init packet | Nordic secure DFU: type APPLICATION, `hw_version` 52, `sd_req` [0], `fw_version` 11002, `app_size` 103,320, SHA-256 image hash, boot validation `VALIDATE_GENERATED_CRC`, ECDSA-P256-SHA256 signature [E] |
| Version string | `01.10-RC1`, reported over UART command `0x43` [E] |
| Build | nRF5 SDK / nrfx 2.x, unoptimised, no SoftDevice; linked at `0x1000` directly after the MBR [E] |

The device's own self-test record from 2026-08-08 reports nRF `01.10-RC1` and TI
`01.02`. That the installed part runs exactly this image is inferred from the version
string; it has not been read back [I].

## Update trigger

1. On every application start, `NUVE::System::System()` (`0x223970`) calls
   `installUpdate_NRF_FW_Service()` (`0x220c80`). It copies the embedded package to
   `/mnt/update/nrf_fw/update.zip` and installs `update_fw_nrf_seamless.sh` into
   `/usr/local/bin`. It does not flash [E].
2. After each `0x43` version reply, `checkForNRFUpdate()` (`0x253ec4`) compares the
   reported software string with the literal `01.10-RC1`. Any other value, including
   an empty string, schedules `updateNRFFirmware()` (`0x25398c`) 3,000 ms later [E].
3. `updateNRFFirmware()` restages the files and calls `update_nRF_Firmware()`
   (`0x31e1e8`), which queues the enter-DFU command `0x4b`
   (`f0 4b 00 01 00 00 f1`) [E].
4. When the nRF acknowledges `0x4b`, `processNRFResponse` runs
   `/usr/local/bin/update_fw_nrf_seamless.sh` through a blocking `QProcess::execute`
   (`0x32cf4c`), sleeps 5 s, and requests the version again [E]. No retry limit was
   found; a part that keeps reporting another version would loop [I].
5. The script runs `nrfdfu serial --port /dev/ttymxc1` at its default 115,200 baud,
   then deletes `/mnt/update/nrf_fw/*` and exits 0 regardless of the `nrfdfu`
   result [E].

`nrfdfu` (`/usr/bin/nrfdfu`, 22 KB) implements Nordic SLIP serial DFU (ping, PRN,
MTU, select, create, write, CRC, execute). It checks the manifest, ZIP contents, and
the bootloader's CRC-32 replies only; it links no cryptographic library, so the
signature is enforced only by the nRF bootloader, which is not in any retained
artifact [E].

The embedded `update_fw_nrf.sh` variant is not referenced by code [E]. No retained log
shows whether a flash ever ran on the reference unit; the staged copy present on p3
after the 2026-08-09 recovery boot is consistent with staging alone [I].

## UART link

Application traffic uses UARTE0 (`TX` P0.02, `RX` P0.03), 9,600 baud 8N1 with no flow
control [E]. The i.MX6 side is `/dev/ttymxc1`; the TI link on `/dev/ttymxc3` uses the
same framing with a different command set [E].

| Element | Format |
| --- | --- |
| Frame | `F0`, stuffed body, `F1` |
| Stuffing | `F0`, `F1`, or `F2` in the body is sent as `F2`, then the complemented byte |
| Body | `cmd`, `b1`, `b2`, payload, CRC-16 |
| CRC | CRC-16/X-25 (reflected `0x8408`, init `0xFFFF`, final complement) over the payload only, high byte first on the wire; an empty payload gives `00 00` [E: nRF `0x164d0` byte-swaps before a little-endian store] |
| Replies | Sent only in response to a request; echo `cmd` and `b2`; unknown commands return `b1 = 0x04` with no payload [E] |

The nRF receive path appears not to verify the CRC [I: no comparison found in the
parser at `0x4fac`].

| Cmd | Direction and meaning |
| --- | --- |
| `0x02` | Set the 16-LED WS2812 ring (driven through I2S on P0.18): R, G, B, brightness, mode (0 static, 1 animated) [E] |
| `0x03` | PWM0 duty 0–100 on P0.31, inverted [E]; Linux names it fan speed (`setFanSpeed`) [E]. A pulse counter on P0.28 sampled over 5 s is probably that fan's tachometer [I] |
| `0x21` | Plausibility windows for temperature, humidity, pressure, and air quality; exact field order partly unresolved [E/I] |
| `0x42` | Status report; content depends on board-variant straps P0.06/P0.07 [E] |
| `0x43` | Hardware and software version strings, for example `01` and `01.10-RC1` [E] |
| `0x49` | ToF and ambient-light status and values [E] |
| `0x4a` | 20-byte sensor snapshot: temperature, humidity, four air-quality values, pressure, ToF distance (mm), lux ×10, pulse count [E]; the order of the four air-quality values is unresolved |
| `0x4b` | Acknowledge, stop UART, wait 500 ms, set `GPREGRET` `0xB1`, and reset into the DFU bootloader [E] |

P0.04 and P0.05 are driven low when new sensor data crosses its thresholds; they are
probably the data-ready lines that reach i.MX6 GPIO21/22 [I].

## Sensors

All sensors are on TWIM0 (SCL P0.20, SDA P0.19, 100 kHz) [E].

| Address | Part | Notes |
| --- | --- | --- |
| `0x44` | Sensirion SHT4x | Single-shot `0xFD`; temperature in 0.1 °C, RH clamped to 100 % [E]. Earlier board notes named an SHT25; address `0x44` and the command set match SHT4x [I] |
| `0x76` | DPS310/SPL06-type barometer | Coefficient read from `0x10`–`0x21`; reported in hPa [E] |
| `0x29` | LTR-329/303 ambient light | Part ID `0xA0`, 48× gain; lux ×10; read only while P0.12 is high [E] |
| `0x29` | ST VL53L0X ToF | ST API present; calibration stored in flash; range above 1,000 mm reported as 0 [E] |
| `0x32` | Renesas ZMOD4410 | Product ID `0x2310`; vendor IAQ algorithm library produces floating-point results [E] |

The light sensor and ToF share address `0x29`; P0.12 probably selects which one is
powered [I]. Initial values before the first sample are 20.0 °C and 40 % RH [E].
Timers run at 10 ms, 50 ms, 250 ms, 1 s, 5 s, and 15 s; the watchdog reloads every
60 s [E].

No RADIO peripheral access, SoftDevice dependency, or BLE stack was found, and no HVAC
relay or equipment output is driven by this image [E]. Remote-sensor pairing therefore
does not live in this application image [I].

## Consequences for Nuve Local

- Nothing here changes supported controls. Nuve Local does not send UART commands and
  does not expose firmware updates.
- The ZMOD4410 produces numeric air-quality results on the nRF, and they cross the
  UART in `0x4a`. Whether `appStherm` forwards any of them through the API is a
  separate question; until a transported, calibrated value is proven, Nuve Local keeps
  its IAQ entity limited to the firmware's categories.
- Any root process on the i.MX6 can put the nRF into DFU mode with one unauthenticated
  frame. Image authenticity then depends on the unrecovered nRF bootloader key and
  policy.

## Open items

- Bootloader image, signing key, readback protection, and version policy.
- Order of the four air-quality values in `0x4a`, the field order of `0x21`, and the
  per-variant `0x42` content.
- The P0.12 selection between the light sensor and the ToF, and what the P0.28 pulses
  measure.
- The unexplained pressure reading of 0 in the 2026-08-09 sensor log, which did not
  recover after the 06:19 UTC restart.
- An emulator boot beyond early initialisation needs interrupt dispatch for the RTC1
  application timers.
