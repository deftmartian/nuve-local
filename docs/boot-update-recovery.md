# Boot, update, and recovery

Offline analysis mapped these boot and recovery paths. Nuve Local exposes none of
them.

## Bootloader

The retained eMMC image contains U-Boot
`2018.03-imx_v2018.03_4.14.98_2.0.0_ga+gdf148036ec`, built 2025-01-29.
The i.MX IVT at file offset `0x400` declares a ROM-loaded region of `0x81000`
bytes. That exact 528,384-byte region has SHA-256
`af98c7a3241d7b0cf6222f8730bef9b3f38c702e769774bfc79d072269324af1`.
Its IVT CSF pointer is zero, so the boot image contains no HAB command-sequence file.

The default environment in the live backup is byte-identical to the clean recovery
root. `/etc/fw_env.config` points at `/boot/uboot.env`, but neither captured nor
recovery FAT contains that file. The retained evidence therefore exposes no saved
environment overriding the exact default branch below.

## Boot selection state machine

The exact environment runs `gpio input 102`. Upstream U-Boot 2018.03 `cmd/gpio.c`
returns the input value as command status: low returns zero/success, while high or a
read/request error is nonzero/failure. The source contract is preserved at
[U-Boot v2018.03 `cmd/gpio.c`](https://github.com/u-boot/u-boot/blob/v2018.03/cmd/gpio.c).

```text
bootcmd
  |
  +-- GPIO102 low (status 0) ----------> check_update
  |                                        |
  |                                        +-- both p3 update files exist
  |                                        |      -> write p1 boot, then p2 root
  |                                        |
  |                                        +-- otherwise no image update
  |
  +-- GPIO102 high/error (nonzero) ----> check_reset -> read GPIO102 again
                                           |
                                           +-- low -> skip restore
                                           |
                                           +-- high/error
                                                  -> write p1 boot.gz,
                                                     then p2 root.gz from p4

All branches then attempt the normal p1 zImage/device-tree boot.
```

The repeated read means a stable high input selects factory restore. A repeated GPIO
access failure also reaches factory restore; this is a fail-dangerous bootloader
property. A transient first failure followed by a low second read skips both update
and restore. The physical signal mapping remains unresolved: GPIO102 is exact, but
the proposed connection to board button S7 and its electrical behavior are not.

## Image-update path

`check_update` tests only that `update_bootp.gz` and `update_rootfs.gz` both exist on
p3. If present, `image_update` loads and `gzwrite`s boot to p1, then root to p2. No
hash, signature, version, serial, rollback slot, or monotonic counter appears in this
branch. Gzip integrity is not publisher authenticity. Because the boot IVT has no
CSF and the written boot payload is a raw FAT image containing a raw `zImage` and
DTB, the retained path supplies no downstream signed-image gate.

P3 and p4 are retained across these p1/p2 writes. The layout is not A/B: interruption
can leave a mixed or partially written boot/root pair, and no exact rollback branch
was found. Power-loss outcomes must be modeled on cloned media rather than tested on
the thermostat.

## Factory-restore path

`factory_restore` reads p4 `boot.gz` and `root.gz`, writes boot first and root second,
then continues toward normal boot. It does not replace p3 or p4. The preserved p4
files are byte-identical to the retained recovery 1.5.8 pair.

The decompressed boot image is FAT16 with a 53,248-sector BPB, while the MBR p1 is
only 42,598 sectors. Its declared extent therefore reaches 5,325,824 bytes into p2.
The vendor sequence writes root after boot, repairing that overlap as part of the
complete pair. A boot-only restore can corrupt root and is never safe.

The boot image contains:

| File | Size | SHA-256 |
| --- | ---: | --- |
| `zImage` | 5,840,336 | `d75c4b75d298332e713aae288352fca10f6543b066b26fc5709227e542744799` |
| `zImage-4.14.98-imx+g4b55fef88af8` | 5,840,336 | same bytes as `zImage` |
| `imx6sl-evk.dtb` | 31,566 | `0524701e0feac4e7f3913555134b80277ffd802d3be60aaa15e6a3c2828496e7` |

## Application update and reset boundaries

Application update ZIPs and the application-managed recovery updater are separate
from the U-Boot image paths. The application installs ZIPs in place under
`/usr/local/bin`; `RecoveryUpdater` only replaces manifest-named `boot.gz`/`root.gz`
sources on p4, which a later factory restore may consume, and never writes p1/p2
itself. Both are documented in
[application-update.md](application-update.md#application-managed-recovery-updater).
No application or recovery update instruction is exposed by Nuve Local.

The touchscreen Factory Reset is also separate: exact application code clears
registration, Wi-Fi/application state, and log data. It does not run the U-Boot
factory restore, repair ext4, or rewrite p1/p2. Device forget, application reset,
image update, and factory restore remain distinct hazardous workflows
([messages-reset-api.md](messages-reset-api.md#device-forget-and-application-reset)).

## Security and operating boundary

- No cryptographic publisher-authenticity mechanism has been found in either exact
  image-writing branch.
- GPIO read failure can select the destructive restore branch after two failures.
- Neither p1/p2 path is transactional or A/B.
- The FAT geometry makes partial boot restoration unsafe.
- Physical GPIO mapping, cloned-media interruption behavior, target-userland
  recovery-copy execution, and real in-place interruption outcomes remain
  unresolved.
- Update, reset, recovery, and performance-test endpoints must stay unreachable from
  Home Assistant.
