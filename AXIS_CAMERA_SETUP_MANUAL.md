# Axis camera manual setup runbook (motion detection + SD + SFTP)

Reference notes for manually configuring a new Axis camera outside the `cctv` tool's
managed settings (motion detection tuning, SD recording, SFTP video-clip upload on
motion). Written after debugging a real SFTP upload failure end-to-end on an
AXIS M3085-V (AXIS OS 10.12.91 → 12.11.72) against a Synology NAS. Use this as a
starting checklist for the next camera; don't assume every step is required for
every model/firmware — verify with the camera's own API discovery first.

## 0. Prerequisites

- Camera IP, VAPIX credentials (root/root or configured admin), reachable from this host.
- SFTP/NAS target IP, port (usually 22), account username/password, target directory.
- All HTTP calls below use `curl --digest -u <user>:<pass>`.

## 1. Discover what the camera actually supports

Don't assume API shape from memory — always check the specific unit/firmware first.

```bash
# Brand/firmware/model
curl -s --digest -u root:root "http://<ip>/axis-cgi/param.cgi?action=list&group=root.Brand,root.Properties.Firmware,root.Properties.System"

# Full VAPIX API discovery — tells you which REST APIs exist on this firmware
curl -s --digest -u root:root -X POST "http://<ip>/axis-cgi/apidiscovery.cgi" \
  -H "Content-Type: application/json" -d '{"apiVersion":"1.0","method":"getApiList"}'

# Installed applications (VMD3 legacy vs VMD4 app vs Object Analytics)
curl -s --digest -u root:root "http://<ip>/axis-cgi/applications/list.cgi"
```

Key finding: **modern cameras (VMD4, app "vmd" v4.x+) do NOT use the legacy
`param.cgi` Motion group.** If `action=list&group=Motion` comes back empty but
`applications/list.cgi` shows `vmd` Running, you're on VMD4 — configure it via
`local/vmd/control.cgi` (JSON), not `param.cgi`.

As of AXIS OS 12, there is still **no modern REST API for events/actions/recipients**
(`apidiscovery.cgi` won't list one) — the legacy **Action1 SOAP** service at
`/vapix/services` remains the only way to configure action rules, even on the
newest firmware. Don't go looking for a REST replacement; it doesn't exist yet.

## 2. Motion detection (VMD4)

```bash
# Get current profile config
curl -s --digest -u root:root -X POST "http://<ip>/local/vmd/control.cgi" \
  -H "Content-Type: application/json" -d '{"apiVersion":"1.4","method":"getConfiguration"}'
```

There's usually a default "Profile 1" already covering most of the frame with
`sizePercentage` filter default `[5,5]` (min object size % to trigger). Lower =
more sensitive; the documented floor is `3`. There is no single 0–100
"sensitivity" knob like the legacy Motion group — it's filter-based (size,
short-lived-object time limit, swaying-object distance).

If the `vmd` application shows `Status="Stopped"` (can happen after a firmware
upgrade crossing major versions), start it:

```bash
curl -s --digest -u root:root "http://<ip>/axis-cgi/applications/control.cgi?action=start&package=vmd"
```

## 3. SD card recording on motion (Action1 SOAP)

Two-step SOAP dance for every action: **AddActionConfiguration** (the "what to do"),
then **AddActionRule** (the "when to do it", i.e. the trigger + condition).

```bash
# 1. Add action configuration (SD storage recording)
curl -s --digest -u root:root -X POST "http://<ip>/vapix/services" \
  -H "Content-Type: application/soap+xml; charset=utf-8" \
  -H 'SOAPAction: "http://www.axis.com/vapix/ws/action1/AddActionConfiguration"' \
  --data '<?xml version="1.0" encoding="utf-8"?><soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" xmlns:aa="http://www.axis.com/vapix/ws/action1"><soap:Body><aa:AddActionConfiguration><aa:NewActionConfiguration><aa:Name>cctv_motion_sd_record</aa:Name><aa:TemplateToken>com.axis.action.unlimited.recording.storage</aa:TemplateToken><aa:Parameters><aa:Parameter Name="storage_id" Value="SD_DISK"/><aa:Parameter Name="pre_duration" Value="5000"/><aa:Parameter Name="post_duration" Value="2000"/><aa:Parameter Name="stream_options" Value=""/></aa:Parameters></aa:NewActionConfiguration></aa:AddActionConfiguration></soap:Body></soap:Envelope>'
# -> returns <aa:ConfigurationID>N</aa:ConfigurationID>
```

Then link it to the VMD motion event (see topic expression notes in section 5 —
use the **concrete profile topic**, not the "ANY profile" wildcard, when creating
rules via the API).

## 4. SD card / disk sanity check

```bash
curl -s --digest -u root:root "http://<ip>/axis-cgi/disks/list.cgi?diskid=all"
```
Check `status="OK"`, `full="no"`, `readonly="no"`, `locked="no"`.

## 5. SFTP video-clip upload on motion — THE IMPORTANT PART

### 5.1 The one parameter that actually matters: `ssh_auth_type`

Per Axis's own developer docs for the `com.axis.recipient.sftp` / the SFTP
action template's embedded recipient parameters:

- `ssh_auth_type = 1` → **public key authentication** — **"currently not supported"**
- `ssh_auth_type = 2` → **password authentication** — the one you want

**If you only ever set a `password` field and leave `ssh_auth_type=1`, the camera
will silently try (unsupported) public-key auth, fail immediately, and report a
misleading generic error** ("Login denied" on older firmware, "Failed to transfer
data" on newer firmware) **without ever sending a real password login attempt.**
This is indistinguishable from a network/credentials/firmware problem from the
logs alone — it looks exactly like an auth failure, a libssh2 bug, or an SSH
server misconfiguration. It is none of those. **Always double check
`ssh_auth_type=2` first**, before chasing anything else.

How this was actually diagnosed (worth repeating next time symptoms look similar):
tcpdump on the SFTP server showed a full TCP+SSH handshake and key exchange
completing, then the camera cleanly closing the connection (FIN, not RST) a few
small packets later — **before any real userauth attempt**. Confirmed by
bumping the SFTP server's sshd to `LogLevel DEBUG3`: a deliberately-wrong test
password from another client always produces an
`pam_unix(sshd:auth): authentication failure` line; the camera's connections
never produced *any* auth line, proving it never actually tried to authenticate
with a password at all — consistent with the client attempting (and giving up on)
unsupported pubkey auth.

Firmware upgrades (even a 2-major-version jump, libssh2 1.9.0 → 1.11.1 inside
Axis's "Monolith" media/action-engine service) did **not** fix this, because the
bug isn't in the SSH library — it's a wrong config value.

### 5.2 The `create_folder` parameter is not a boolean

Despite looking like a yes/no flag, whatever string you put in `create_folder`
gets used as a **literal extra subfolder name** appended under `upload_path`
(confirmed empirically: `create_folder="yes"` creates a folder literally named
`yes`; `create_folder="no"` creates one literally named `no`). If you don't want
an extra nesting level and `upload_path` already exists, **set `create_folder=""`**
(empty string) — clips then land directly in `upload_path`.

### 5.3 Full working action configuration

```bash
curl -s --digest -u root:root -X POST "http://<ip>/vapix/services" \
  -H "Content-Type: application/soap+xml; charset=utf-8" \
  -H 'SOAPAction: "http://www.axis.com/vapix/ws/action1/AddActionConfiguration"' \
  --data '<?xml version="1.0" encoding="utf-8"?><soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" xmlns:aa="http://www.axis.com/vapix/ws/action1"><soap:Body><aa:AddActionConfiguration><aa:NewActionConfiguration><aa:Name>cctv_motion_sftp_upload</aa:Name><aa:TemplateToken>com.axis.action.unlimited.send_videoclip.sftp</aa:TemplateToken><aa:Parameters><aa:Parameter Name="ssh_private_key_passphrase" Value=""/><aa:Parameter Name="pre_duration" Value="5000"/><aa:Parameter Name="stream_options" Value=""/><aa:Parameter Name="upload_path" Value="/YOUR/REAL/PATH"/><aa:Parameter Name="ssh_public_key" Value=""/><aa:Parameter Name="ssh_auth_type" Value="2"/><aa:Parameter Name="qos" Value="0"/><aa:Parameter Name="post_duration" Value="2000"/><aa:Parameter Name="password" Value="YOUR_PASSWORD"/><aa:Parameter Name="temporary" Value="0"/><aa:Parameter Name="port" Value="22"/><aa:Parameter Name="host" Value="YOUR_NAS_IP"/><aa:Parameter Name="ssh_host_pub_key_md5" Value="YOUR_HOST_KEY_MD5"/><aa:Parameter Name="login" Value="YOUR_SFTP_USER"/><aa:Parameter Name="create_folder" Value=""/><aa:Parameter Name="filename" Value="motion_%Y%m%d_%H%M%S"/><aa:Parameter Name="ssh_private_key" Value=""/><aa:Parameter Name="max_duration" Value="0"/><aa:Parameter Name="max_file_size" Value="0"/></aa:Parameters></aa:NewActionConfiguration></aa:AddActionConfiguration></soap:Body></soap:Envelope>'
```

Getting `ssh_host_pub_key_md5` (RSA host key MD5 fingerprint of the SFTP server):

```bash
ssh-keyscan -t rsa <nas-ip> > hostkey.txt
ssh-keygen -l -E md5 -f hostkey.txt   # strip colons, lowercase, no "MD5:" prefix for the param value
```

`SetActionConfigurationParameters` (in-place edit of an existing config) is
**not implemented** on at least this firmware — expect
`{"error":{"message":"Optional action not implemented"}}`. To change any
parameter you must `RemoveActionConfiguration` + `RemoveActionRule`, then
recreate both fresh with new IDs.

### 5.4 Linking the rule (topic expression gotcha)

`GetActionRules` on an existing/inherited config may show a topic like:

```
tnsaxis:CameraApplicationPlatform/VMD/Camera1ProfileANY//.
```

This "ANY profile" wildcard round-trips fine on `GetActionRules` for
pre-existing rules, but **`AddActionRule` rejects it** with a cryptic
`failed to parse topic expression 'axis:CameraApplicationPlatform/...'` fault
(note: the fault message mangles the `tnsaxis:` prefix to `axis:` — this is a
red herring, not the actual problem). When creating a **new** rule via the API,
use the **concrete profile topic** instead (VMD4 profile 1 in this example):

```
tnsaxis:CameraApplicationPlatform/VMD/Camera1Profile1
```

with `MessageContent`:
```xml
<wsnt:MessageContent Dialect="http://www.onvif.org/ver10/tev/messageContentFilter/ItemFilter">boolean(//SimpleItem[@Name="active" and @Value="1"])</wsnt:MessageContent>
```

Full envelope needs these namespaces declared on `soap:Envelope`: `soap`, `aa`,
`wsnt="http://docs.oasis-open.org/wsn/b-2"`,
`tns1="http://www.onvif.org/ver10/topics"`,
`tnsaxis="http://www.axis.com/2009/event/topics"`.

```bash
curl -s --digest -u root:root -X POST "http://<ip>/vapix/services" \
  -H "Content-Type: application/soap+xml; charset=utf-8" \
  -H 'SOAPAction: "http://www.axis.com/vapix/ws/action1/AddActionRule"' \
  --data '<?xml version="1.0" encoding="utf-8"?><soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" xmlns:aa="http://www.axis.com/vapix/ws/action1" xmlns:wsnt="http://docs.oasis-open.org/wsn/b-2" xmlns:tns1="http://www.onvif.org/ver10/topics" xmlns:tnsaxis="http://www.axis.com/2009/event/topics"><soap:Body><aa:AddActionRule><aa:NewActionRule><aa:Name>cctv_motion_sftp_upload</aa:Name><aa:Enabled>true</aa:Enabled><aa:Conditions><aa:Condition><wsnt:TopicExpression Dialect="http://docs.oasis-open.org/wsn/t-1/TopicExpression/Concrete">tnsaxis:CameraApplicationPlatform/VMD/Camera1Profile1</wsnt:TopicExpression><wsnt:MessageContent Dialect="http://www.onvif.org/ver10/tev/messageContentFilter/ItemFilter">boolean(//SimpleItem[@Name="active" and @Value="1"])</wsnt:MessageContent></aa:Condition></aa:Conditions><aa:PrimaryAction>THE_CONFIG_ID_FROM_ABOVE</aa:PrimaryAction></aa:NewActionRule></aa:AddActionRule></soap:Body></soap:Envelope>'
```

## 6. Verifying it actually works

```bash
curl -s --digest -u root:root "http://<ip>/axis-cgi/admin/systemlog.cgi" \
  | grep -iE "sftp_upload|Failed to transfer|Login denied"
```

Wave in front of the camera / cause real motion, then check for a clean
start → stop pair with **no** "Error occurred" / "Aborting" lines. Then verify
the file actually landed:

```bash
curl -s "sftp://<nas-ip>/<upload_path>/" --user "<user>:<pass>" --insecure -k --connect-timeout 10
```
(`--insecure -k` are harmless no-ops for SFTP but avoided a flaky
`libssh2: The requested method(s) are not currently supported` error seen
intermittently with bare curl SFTP calls on this machine — include them.)

## 7. If it's on Synology and you get real "Permission denied" on the SFTP write

If SFTP **login** works (curl from any normal client succeeds) but the actual
folder/file operations don't:

- Check the shared folder's **Windows ACL / Advanced Permissions** (Control
  Panel → Shared Folder → Edit → Permissions → Customize on the account) for
  granular checkboxes — specifically **"Create folders / append data"** and
  **"Delete"/"Delete subfolders and files"**. A locked-down account can easily
  have "create files" allowed but "create folders" denied, which breaks
  `create_folder`-style auto-provisioning while plain file writes still work.
- If a **DSM home directory** gets set for the SFTP account partway through
  setup, its SFTP chroot root changes to that home directory — any
  previously-configured `upload_path` referencing the *old* absolute share path
  (e.g. `/cctv`) will start returning "No such file or directory" until you
  update `upload_path` to be relative to the new root.
- DSM's Auto Block and a separate DoS/connection-flood protection feature are
  two *different* settings (Control Panel → Security) — check both if
  suspecting a silent network-level block, but note that a real auth/protocol
  failure (see section 5.1) can look identical to a network block from the
  camera's error message alone. Get definitive evidence (packet capture +
  server-side auth log at DEBUG3) before concluding it's network-level.

## 8. Cleanup checklist after diagnosing anything invasive

If you enabled SSH shell on the camera (`root.Network.SSH.Enabled`) or bumped
`LogLevel` on the NAS's sshd for debugging, revert both when done — they're
diagnostic-only, not needed for normal operation.
