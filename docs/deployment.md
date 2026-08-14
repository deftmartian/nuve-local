# Deployment and rollback

This guide moves a Nuve Samo from its vendor endpoint to Nuve Local on your LAN.
Replace angle-bracket placeholders with values from your network.

Work through the numbered sections in order. Adding the Home Assistant integration
starts a five-minute pairing window, so backup and network preparation come first.
For an existing installation, skip to [Routine upgrades](#routine-upgrades).

## 1. Record the starting details

You need Home Assistant 2026.7.4 or newer, access to `/config`, an SSH client, control
of local DNS and firewall rules, and a private backup directory.

Use DHCP or ARP records to confirm the thermostat's IP. Make sure the HVAC is stable
and no firmware update is running. Stop if the installed version is not listed in
the [supported firmware table](../README.md#supported-firmware).

Record these values:

| Value | Your installation |
| --- | --- |
| Thermostat IP | `<thermostat-ip>` |
| Serial number | `<serial>` |
| Firmware version | `<firmware-version>` |
| Existing API base | `<current-endpoint>` |
| API hostname Nuve Local will accept | `<api-hostname>` |
| Thermostat-facing HTTPS port | `<thermostat-facing-port>` |
| Deployment profile | `Trusted reverse proxy` or `Direct TLS` |
| Reverse-proxy IP, if used | `<proxy-ip>` |
| Home Assistant listener IP | `<home-assistant-listen-ip>` |
| Technician Access URL | `<current-technician-url>` or verified empty |
| Temperature-correction version | `<temp-correction-version>` |

Keep the completed worksheet and device backups private.

## 2. Connect over SSH and make a backup

Recovery image 1.5.8 enables root SSH on TCP 22 with this vendor default:

```text
username: root
password: sterm
```

Other versions may differ. Enter the password interactively. On first connection,
record the host-key fingerprint:

```bash
ssh -o StrictHostKeyChecking=ask root@<thermostat-ip>
```

If that key later changes, stop and confirm the device identity. A factory restore
can regenerate it, but the IP may also belong to another host.

Back up both configuration files before editing either one. SSH streaming works even
if this older server rejects `scp`:

```bash
umask 077
install -d -m 700 nuve-backup
ssh root@<thermostat-ip> 'cat /usr/local/bin/device_config.ini' \
  > nuve-backup/device_config.ini.original
ssh root@<thermostat-ip> 'cat /usr/local/bin/sthermConfig.QQS.json' \
  > nuve-backup/sthermConfig.QQS.json.original
sha256sum nuve-backup/*.original > nuve-backup/SHA256SUMS
```

Keep the directory outside the repository. Check the remote files without printing
their contents:

```bash
ssh root@<thermostat-ip> '
  stat -c "%a %U:%G %s %n" \
    /usr/local/bin/device_config.ini \
    /usr/local/bin/sthermConfig.QQS.json
  sha256sum \
    /usr/local/bin/device_config.ini \
    /usr/local/bin/sthermConfig.QQS.json \
    /usr/local/bin/appStherm
'
```

From the local backups, record:

- the root-level `endpoint` value from `device_config.ini`;
- the `technicianURL` leaf value from `sthermConfig.QQS.json`, including an empty
  value if that is what the thermostat stores; and
- the `tempCorrectionVersion` leaf value from `sthermConfig.QQS.json`.

The JSON parent keys vary, so search for the leaf names. Do not guess either value:
incorrect commissioning data can replace saved thermostat metadata.

```bash
sed -n 's/^endpoint=//p' nuve-backup/device_config.ini.original
jq -c '.. | objects | select(has("technicianURL")) | .technicianURL' \
  nuve-backup/sthermConfig.QQS.json.original
jq -c '.. | objects | select(has("tempCorrectionVersion")) | .tempCorrectionVersion' \
  nuve-backup/sthermConfig.QQS.json.original
```

Each JSON search should return one value; `""` is a valid empty Technician Access
URL. If a search returns nothing or conflicting values, inspect the file before
continuing.

After setup, install an SSH key and restrict TCP 22 to administration devices. Change
the default password only if your recovery process preserves the change. Nuve Local
does not use SSH during normal operation.

## 3. Choose the API hostname and connection profile

The thermostat sends requests to the `endpoint` URL. Home Assistant's **API
hostname** field must match that URL's hostname; it is unrelated to the hostname used
to open Home Assistant.

Use a real DNS hostname that you control and a trusted certificate for that hostname.
The name may be dedicated to Nuve Local or be an existing operator-controlled
hostname on a dedicated port. Local DNS must resolve it to your proxy or Home
Assistant listener from the thermostat network. Avoid `.local`, bare hostnames, and
untrusted certificate issuers. Step 6 changes only the root-level `endpoint` entry.

Use one of these URL forms:

```text
https://<api-hostname>/
https://<api-hostname>:<thermostat-facing-port>/
```

Enter only `<api-hostname>` in Home Assistant, without scheme, path, or port.

### Choose the connection profile

| Profile | Thermostat-facing connection | Home Assistant listener | Use when |
| --- | --- | --- | --- |
| Trusted reverse proxy (recommended) | Proxy serves the trusted HTTPS certificate | Restricted HTTP on TCP 18443 | Caddy or another proxy already manages local certificates |
| Direct TLS | Nuve Local serves the trusted HTTPS certificate | HTTPS on TCP 18443 | Home Assistant can read the matching certificate and private key |

In proxy mode, Nuve Local checks the proxy address and accepts one
`X-Forwarded-For` address containing the thermostat IP. In direct mode, Home
Assistant must be able to read the certificate and key, usually under `/config`.
The certificate SAN must match `<api-hostname>`, and the thermostat must trust its
chain.

## 4. Stage Home Assistant and the network

### Install the component

Download one Nuve Local release and extract its complete component to:

```text
/config/custom_components/nuve_local/
```

Restart Home Assistant. Do not add the integration yet.

### Prepare the proxy or direct-TLS certificate

For a trusted reverse proxy, this Caddy example shows the required traffic flow:

```caddyfile
<api-hostname>:<thermostat-facing-port> {
    @thermostat remote_ip <thermostat-ip>
    handle @thermostat {
        reverse_proxy http://<home-assistant-listen-ip>:18443 {
            header_up Host {host}
            header_up X-Forwarded-For {remote_host}
        }
    }
    respond 403
}
```

Adapt the addresses and certificate settings to your network. The Nuve Local
upstream is HTTP; do not add TLS, a CA, or a server name to it.

For direct TLS, put the certificate and key where Home Assistant can read them. The
listener starts when you create the integration entry.

### Prepare DNS and firewall rules

Apply these network rules:

1. `<api-hostname>` resolves to the proxy or direct listener from the thermostat
   network.
2. Only `<thermostat-ip>` can reach the thermostat-facing HTTPS port.
3. In reverse-proxy mode, only `<proxy-ip>` can reach
   `<home-assistant-listen-ip>:18443`.
4. Other clients cannot reach the Nuve Local listener directly.
5. No WAN port-forward or public listener exists.
6. The thermostat cannot bypass the intended path through another DNS resolver or an
   unrestricted vendor-service route.

You may activate the local DNS record now because the thermostat does not use the new
endpoint yet.

Test DNS from the thermostat network. In proxy mode, also test HTTPS with SNI set to
`<api-hostname>`. In direct mode, inspect the certificate now and test the listener
after step 5. A laptop test catches routing, SNI, and certificate-name errors, but
does not prove that the thermostat trusts the same CA.

## 5. Add Nuve Local in Home Assistant

Continue only when the backup and all network changes are ready.

Open **Settings → Devices & services → Add integration → Nuve Local**.

1. Choose **Trusted reverse proxy** or **Direct TLS**.
2. Enter the thermostat IP, serial number, and API hostname from the worksheet.
3. For a proxy, enter its IP. For direct TLS, enter the certificate and private-key
   paths.
4. Leave the Home Assistant listener address blank to detect it automatically, or
   enter `<home-assistant-listen-ip>`. The listener port defaults to 18443.
5. Enter the firmware version, current Technician Access URL, and
   `tempCorrectionVersion` collected in step 2.
6. Confirm that you checked those values and that no firmware update is active.
7. Leave automatic starting-state capture enabled.
8. Submit the setup form.

Submitting starts the listener and five-minute pairing window. Control remains off.
Move directly to step 6. If time expires, open **Pairing window** in the integration
options and start another window.

In direct mode, verify the listener certificate before changing the endpoint.

## 6. Direct the thermostat to Nuve Local

### Change the endpoint

While the HVAC is stable, review and run this script. It changes the single
root-level `endpoint`, preserves every other line, and retains file permissions and
ownership:

```bash
ssh root@<thermostat-ip> 'python3 -' <<'PY'
from pathlib import Path
import os

path = Path("/usr/local/bin/device_config.ini")
endpoint = "https://<api-hostname>:<thermostat-facing-port>/"
with path.open("r", newline="") as source:
    original = source.read()
lines = original.splitlines(keepends=True)
matches = [index for index, line in enumerate(lines) if line.startswith("endpoint=")]
if len(matches) != 1:
    raise SystemExit(f"expected one endpoint entry, found {len(matches)}")
newline = "\r\n" if lines[matches[0]].endswith("\r\n") else "\n"
lines[matches[0]] = f"endpoint={endpoint}{newline}"
updated = "".join(lines)
if updated == original:
    raise SystemExit("endpoint is already configured")
stat = path.stat()
temporary = path.with_name(".device_config.ini.nuve-local")
if temporary.exists():
    raise SystemExit(f"refusing to replace existing {temporary}")
with temporary.open("x", newline="") as output:
    output.write(updated)
    output.flush()
    os.fsync(output.fileno())
os.chmod(temporary, stat.st_mode & 0o7777)
os.chown(temporary, stat.st_uid, stat.st_gid)
os.replace(temporary, path)
directory_fd = os.open(path.parent, os.O_RDONLY)
try:
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
PY
```

For port 443, use `https://<api-hostname>/` without a port.

Confirm that the endpoint appears once and the file still has its original metadata:

```bash
ssh root@<thermostat-ip> '
  test "$(grep -c "^endpoint=" /usr/local/bin/device_config.ini)" -eq 1
  sed -n "s/^endpoint=.*/endpoint=[redacted]/p" \
    /usr/local/bin/device_config.ini
  stat -c "%a %U:%G %s %n" /usr/local/bin/device_config.ini
'
```

Keep the INI private. Restart only the application:

```bash
ssh root@<thermostat-ip> '
  systemctl restart appStherm.service
  systemctl is-active appStherm.service
  pgrep -af "[a]ppStherm"
'
```

Do not reboot, factory-reset, shorten the INI, edit the systemd environment, or
modify the CA bundle. `appStherm` reads the API base from `device_config.ini`, so a
systemd override alone does not redirect it.

## 7. Wait for pairing and complete device state

Before enabling control, confirm:

1. The proxy or direct listener receives a connection from the thermostat.
2. The request Host matches the configured API hostname.
3. Nuve Local pairs one token and closes the pairing window.
4. **Deployment status** shows a running listener and connected thermostat.
5. Settings and Auto starting records are saved.
6. Fresh full monitor data agrees with them.
7. Home Assistant shows the same temperature, target, mode, fan, and stage state as
   the thermostat.
8. No Nuve Local Repair or uncertain-command condition is active.

If pairing fails, check the steps in this order:

1. confirm the five-minute pairing window is still open;
2. resolve `<api-hostname>` from the thermostat network;
3. verify the thermostat-facing certificate and SNI;
4. check the thermostat-to-proxy or thermostat-to-listener firewall rule;
5. in proxy mode, check the proxy-to-Home-Assistant rule, Host header, and single
   `X-Forwarded-For` value; and
6. confirm the configured IP, serial number, and hostname.

Listener reachability alone is not enough; Nuve Local must save complete thermostat
state.

## 8. Enable control and run a reversible test

Open the integration options and choose **Local control**. Enable it only when
**Deployment status** reports ready.

Move display brightness by one step, wait for confirmation in Home Assistant and on
the thermostat, then restore it. Do not send another command while one is pending.

If the result is uncertain, do not retry. Compare the thermostat with fresh Home
Assistant data and let the integration resolve the mismatch. Test HVAC controls
separately, with the equipment in a safe and observable state.

## Rollback

Disable Nuve Local control before rolling anything back.

### Endpoint-change rollback

If `device_config.ini` was edited:

1. Confirm that the HVAC is stable.
2. Restore the complete verified `device_config.ini.original`, preserving its mode
   and ownership. Do not reconstruct only the endpoint line.
3. Restart only `appStherm.service`.
4. Verify the original endpoint and normal local HVAC state.
5. Remove the Nuve Local DNS, proxy, and firewall rules only after the thermostat no
   longer depends on them.

### Home Assistant rollback

Restore one Home Assistant backup containing the component, config entry, and
integration data. Copying old Python files over a newer config entry is not a full
rollback.

A Home Assistant outage does not stop local HVAC control, but API synchronization and
weather data remain unavailable. Do not clear an uncertain-command record just to
re-enable writes.

## Routine upgrades

After the first deployment, a normal Nuve Local upgrade is:

1. Create a Home Assistant backup and retain the currently installed Nuve Local
   release archive.
2. Install the complete component from one release.
3. Validate and restart Home Assistant Core.
4. Verify the listener, thermostat contact, telemetry, Repairs, and control readiness
   without issuing a thermostat command.

Do not change DNS, proxy, firewall, thermostat endpoint, SSH password, or pairing
token during an ordinary integration upgrade.
