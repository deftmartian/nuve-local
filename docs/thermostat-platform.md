# Nuve Samo thermostat platform

This platform summary combines recovery image `1.5.8` with photographs of the
installed `HVAC021-C2-MAIN` board. Other revisions may differ.

## At a glance

| Layer | Identified platform |
| --- | --- |
| Main processor | NXP i.MX 6SoloLite `MCIMX6L3DVN10AC`, one Cortex-A9 core up to 1 GHz |
| Memory | 1 GiB LPDDR2 address range; installed `NT6TL256T32BQ-60` device |
| Storage | 4 GB Kioxia/Toshiba `THGBMTG5D1LBAIL` eMMC 5.0 |
| Wireless | AMPAK AP6256 SISO Wi-Fi/Bluetooth module; SDIO Wi-Fi is established, Bluetooth use is not |
| Sensor-side controller | Nordic nRF52832-QFAA; its firmware, sensor algorithms, and pairing protocol are unavailable |
| HVAC-side controller | Separate TI-side controller over UART; its MCU model, firmware, relay electronics, and terminal schematic are unavailable |
| Display | 480 × 480 LCD, SPI panel setup, I²C capacitive touch, and 200 Hz PWM backlight |
| Audio | Nuvoton NAU88C22 codec is installed; an active application audio path is not established |
| Power | NXP PF0100-family configurable PMIC |

The i.MX6 runs the user interface, HVAC policy, persistence, networking, and vendor
API client. It sends logical relay requests over UART to the separate HVAC
controller rather than driving equipment terminals directly. Environmental and
proximity values similarly arrive as processed data from the nRF-side controller.

```text
                  Nuve Samo mainboard

 Wi-Fi/API --> i.MX6 Linux + Qt application --> display/touch/backlight
                     |              |
                     | UART         | UART
                     v              v
              nRF sensor MCU    TI HVAC controller --> equipment terminals
```

For bus details, chip markings, GPIOs, watchdogs, photographs, and open electrical
questions, see [Hardware and bus map](hardware-bus-map.md).

## Recovered software stack

| Component | Recovery 1.5.8 |
| --- | --- |
| Operating system | `Stherm XWayland 1.0.0 (zeus)`, a Yocto Project Zeus-generation root filesystem |
| Kernel | Linux `4.14.98-imx+g4b55fef88af8` |
| Bootloader | U-Boot `2018.03-imx_v2018.03_4.14.98_2.0.0_ga+gdf148036ec` |
| Main application | `appStherm` 1.5.8, ARM ELF, SHA-256 `2117a5456445fe57a851ecf09aa452a8d3a2a59d166d4c6f5475bb69d5151c8e` |
| UI/runtime | Qt 6.4.0/QML on the Linux framebuffer |
| TLS library | OpenSSL 1.1.1g with normal CA and hostname verification |
| Remote administration | Socket-activated OpenSSH 8.0p1 on TCP 22 |
| Network management | NetworkManager with Broadcom `brcmfmac` Wi-Fi support |

`appStherm.service` starts `/usr/local/bin/appStherm -platform linuxfb` and restarts
it on failure. The application reads `/usr/local/bin/device_config.ini` during
startup. Its root-level `endpoint` setting becomes `API_SERVER_BASE_URL`, which is
the supported configuration seam when a deployment uses a dedicated hostname. A
split-DNS deployment can retain an already-matching vendor endpoint. A systemd
environment override alone is overwritten by the application.

## Storage and recovery layout

| Device path | Role |
| --- | --- |
| `/dev/mmcblk1p1` | FAT boot partition containing the kernel and device tree |
| `/dev/mmcblk1p2` | Active ext4 root filesystem |
| `/dev/mmcblk1p3` | Update, application-data, and log storage |
| `/dev/mmcblk1p4` | Factory `boot.gz` and `root.gz` recovery source |

This is not an A/B update design. Application updates replace files in place, and
the U-Boot recovery path writes boot and root from partition 4 without a recovered
publisher-signature or automatic rollback boundary. The boot filesystem geometry
also overlaps the beginning of root, so a boot-only restore is unsafe.

The main application and recovery protocol are well mapped. The secondary-controller
firmware, schematics, secure-boot policy, storage behavior during power loss, and
vendor services are still open questions. See
[Firmware architecture](firmware-architecture.md),
[Boot, update, and recovery](boot-update-recovery.md), and
[Remaining unknowns](remaining-unknowns.md) for the evidence boundary.

## What matters for deployment

- The thermostat validates HTTPS certificates and hostnames normally.
- The API base can include an explicit port. When it must change, the existing
  `endpoint` key is used rather than patching the application; a matching split-DNS
  vendor endpoint may instead be retained.
- The stock image exposes root SSH for maintenance. The deployment guide documents
  the recovered default and safe handling.
- Nuve Local does not update firmware, change installer wiring, operate recovery,
  or access the secondary controllers directly.
- A factory-root replacement restores the stock account verifier, removes any added
  SSH key, and regenerates host keys, so a changed fingerprint must be investigated
  rather than blindly accepted.
