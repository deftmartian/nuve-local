# Application-managed recovery updater

This updater comes from `appStherm` SHA-256
`2117a5456445fe57a851ecf09aa452a8d3a2a59d166d4c6f5475bb69d5151c8e`
and the 1.5.8 recovery artifacts in
[artifact-inventory.md](artifact-inventory.md). It was reconstructed offline. Nuve
Local exposes none of its operations.

## Boundary to boot recovery

The application and U-Boot do different jobs:

```text
HTTP metadata and payload
          |
          v
appStherm RecoveryUpdater
  stage: /mnt/log/download/recovery
  copy:  /mnt/recovery/ on /dev/mmcblk1p4
          |
          | exact p4 snapshot: boot.gz, root.gz, filesInfo.json
          v
later U-Boot factory_restore, only if its GPIO branch selects it
  gzwrite p4 boot.gz -> p1, then p4 root.gz -> p2
```

`RecoveryUpdater` does not itself write p1 or p2. It can replace manifest-named
files on p4, which is the source U-Boot later consumes. The exact retained p4
`filesInfo.json` has two records: `boot.gz` and `root.gz`, with the same sizes and
MD5 values as the retained vendor 1.5.8 pair. This connects the
application-to-boot routing boundary without running either path.

## Paths and state

| Role | Exact path/state |
| --- | --- |
| recovery partition | `/dev/mmcblk1p4` mounted at `/mnt/recovery` |
| destination directory | `/mnt/recovery/` |
| download stage | `/mnt/log/download/recovery` |
| recovery cache | `/mnt/recovery/filesInfo.json` |
| application directory used by the space cleaner | `QCoreApplication::applicationDirPath()`, normally `/usr/local/bin` |
| download executor | object offset `+0x24` |
| copy executor | object offset `+0x28` |
| pending download map | object offset `+0x2c` |
| verified copy list | object offsets `+0x30..+0x38` |
| in-process latch | object offset `+0x20` |

Each recovery-manifest value must be a nonempty object with the keys
`CurrentFileSize`, `CheckSum`, `Address`, and `fileName`. The syntax validator
checks presence, not value types. The bounded emulator covers ordinary integral
sizes, string paths, and canonical 32-hex MD5 values; malformed Qt conversion and
`QByteArray::fromHex` edge cases remain outside it.

## `filesInfo.json`

The native builder emits this shape:

```json
{
  "files": [
    {
      "Name": "boot.gz",
      "CheckSum": "<md5-hex>",
      "CurrentFileSize": 10800310
    }
  ]
}
```

It scans regular files in the recovery directory, skips zero-length or
unhashable files, and skips any file whose complete suffix contains the
case-sensitive substring `json`. The embedded `cpuLoad.json` literal supplies the
merged `json` substring used by that test; the behavior is broader than one
filename. A non-forced cache can be reused for up to `2,592,000` seconds (30
days), subject to the function's file-time and directory-consistency checks.

The update planner itself reads the cached `files` array. A record with matching
`Name` and `CheckSum` is treated as current without recalculating the destination
MD5 at that point. A stale but matching record can therefore suppress both the
destination check and the staged-file path.

## Exact planning order

After internet, nonempty-manifest, and in-process checks, the updater walks the
manifest keys and applies this decision per entry:

1. Read `fileName`, `CheckSum`, `Address`, and `CurrentFileSize`.
2. If cached `Name` and `CheckSum` match, treat the destination as current.
3. Otherwise calculate MD5 for
   `/mnt/log/download/recovery/<fileName>`.
4. If the staged MD5 matches, append `fileName` to the copy list.
5. Otherwise retain the manifest key and `Address` in the download map. Count
   `max(0, CurrentFileSize - staged-size)` as required download space.
6. For a needed entry, add `CurrentFileSize` to one cumulative recovery-space
   counter, subtract the existing destination size from that cumulative counter,
   and clamp it at zero. This is not an independent per-file sum.

If downloads are pending, the updater runs the free-space preflight and then the
download loop. If no downloads are pending but the copy list is nonempty, it goes
directly to rsync **without the free-space preflight**. If neither is present, it
finishes without copying.

## Free-space preflight and destructive cleanup

The two storage paths must remain valid after mount attempts. Recovery and download
space each require the calculated byte count plus exactly 1 MiB; equality passes.
Insufficient recovery-partition space fails immediately.

Insufficient download-stage space instead invokes this exact cleanup order:

1. Remove the contents of the application directory, normally `/usr/local/bin`.
2. Recheck download-stage space.
3. If still short, remove `/mnt/log/log/` and `/mnt/log/networkLogs/`.
4. Recheck and fail only if it remains short.

The first cleanup can remove the running application's on-disk executable and
support files before a recovery payload has downloaded or copied. This is an exact
native-code property, not a hypothetical low-space policy.

Before creating the download executor, the caller runs
`/bin/bash -c "chmod +x /usr/bin/wget"`. Its unsigned result check rejects only
QProcess sentinel results `-2` and `-1`; ordinary nonzero exit codes are accepted.

## Download loop

For one pending entry, `ProcessExecutor` runs:

```text
ionice -c3 nice -n 19 wget -c <http-base><Address> -O \
  /mnt/log/download/recovery/<fileName>
```

Those are distinct `-n` and `19` argv elements. The payload URL is plaintext HTTP
and is the update-server base concatenated with the manifest `Address`. On exit
zero, the callback calculates staged-file MD5. A match moves the filename to the
copy list and removes the pending map entry. A mismatch removes the staged file but
retains the entry. A nonzero process exit also retains the entry.

Whenever the map remains nonempty, the callback immediately calls the download
function again. No retry counter, delay, or backoff was found. A persistent process
failure or attacker-controlled checksum mismatch can therefore cycle indefinitely
while the higher-level internet check keeps succeeding.

## Copy and post-copy gate

Only staged paths that exist are appended. The exact program and argv are:

```text
ionice -c3 nice "-n 19" rsync -a -c --whole-file --inplace \
  --remove-source-files <existing-staged-path>... /mnt/recovery/
```

Unlike the wget path, `-n 19` is one QString and therefore one argv element. The
exact target-userland outcome of that unusual argument still needs an isolated
execution harness; the static claim is the argv shape itself. The rsync policy is
in-place, whole-file, checksum-based, and removes source files. It has no atomic
pair transaction or rollback.

After a normal exit zero, the callback recalculates MD5 for every manifest-named
destination, not only newly copied files. All matches produce success, clean the
download directory, rebuild `filesInfo.json`, and clear the in-process latch. A
checksum mismatch reports failure, retains the download directory, rebuilds file
information, and clears the latch.

A missing process, crash, or nonzero copy exit reports failure through a different
branch: it does not rebuild file information and does not clear the in-process
latch. Subsequent calls can remain blocked as “recovery update is in process” until
the process is restarted or other unrecovered state changes it.

## Server report and retry

After rebuilding file information, `reportRecoveryInfomation` serializes a supplied
nonempty object in compact JSON form. With an empty object it reads the cached
`/mnt/recovery/filesInfo.json`; empty bytes are not sent. DeviceController forwards
the exact bytes to `POST api/device/recovery-image?sn=<serial>`.

The network callback ignores the response body and returns transport success plus
the original bytes. Failure stores those bytes in the report timer's dynamic
`fileData` property and retries every 10,000 ms without a cap while the application
believes internet is available. Success clears the payload and retry-valid flag.
A failure observed while the connectivity flag is false retains the payload but
does not start the timer, and no connectivity-change restart was found. See
[messages-reset-api.md](messages-reset-api.md) for the exact request and completion
contract.

## Authenticity and path hazards

- The metadata/payload chain is HTTP plus attacker-selected MD5, not a publisher
  signature. Post-copy MD5 confirms consistency with that metadata, not origin.
- `fileName` is concatenated into staging and destination paths without a recovered
  parent-traversal rejection. The fixed prefix contains a leading slash, so a
  leading slash in `fileName` does not by itself replace that prefix; `..` segments
  remain meaningful. The isolated model preserves them to make the missing guard
  visible; no exploit is executed.
- A matching cache record is trusted before a destination existence or MD5 check.
- Low download space can erase the application directory before download success.
- Copying is in-place and source-removing; boot/root are not committed as one unit.
- A later U-Boot restore writes boot before root, with no A/B slot or rollback.

Nuve Local and Home Assistant do not expose recovery update, factory restore,
application update, reset, or boot-partition writes.

## Reproduction boundary

`scripts/emulate_firmware_recovery_updater.py` and its synthetic tests reproduce
the normal planner, the cumulative space counter, cleanup ordering, exact argv,
retry disposition, file-info schema, path concatenation, and copy callback. They do
not execute target ARM userland, contact the vendor, mount p4, or simulate power
loss. `scripts/emulate_firmware_misc_api.py` separately reproduces report retries.
Real process interruption and ext4 durability remain in `UPD-U03`.
