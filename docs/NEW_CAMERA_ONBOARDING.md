# Onboarding a brand-new AXIS M3085-V (reference: 192.168.0.4)

Live comparison done 2026-08-27/28 between the working reference camera
**192.168.0.4** and two brand-new out-of-box units, **192.168.0.24** and
**192.168.0.25**, all AXIS M3085-V.

**Status (2026-08-28): applied in full to .24 and .25.** Both are on
firmware 12.11.72, VMD4 full-frame, `sds3sync` installed/configured/running,
SD-record action rule created, SD retention unlimited, NTP fixed. S3
connectivity confirmed on both (housekeeping files uploaded successfully) —
see "Verification status" at the end of this doc for what's confirmed vs.
still pending (real motion clips need actual motion in front of the
cameras, which wasn't available during setup).

**The `cctv` CLI tool (`src/cctv/`) does not apply to this model — do not run
`cctv apply` against these cameras.** It targets `root.NetworkShare` (SMB)
and the legacy `root.Motion` param group; both are unusable on the M3085-V's
firmware (see Finding row below — `root.NetworkShare` errors outright,
`root.Motion` is empty because VMD4 doesn't use it). `cameras.yaml` and the
tool's reconciler are for a different camera generation. The reference
camera's real working setup was built entirely by hand:

```
VMD4 motion event → record clip to SD card (SD_DISK) → third-party ACAP
"sds3sync" polls the SD card and pushes clips to an S3-compatible bucket
```

## Findings: .4 (configured) vs .24/.25 (factory default)

| Area | 192.168.0.4 (reference) | 192.168.0.24 / .25 (new) | Action needed |
|---|---|---|---|
| Firmware | 12.11.72 (built 2026-07-01) | 10.12.91 (built 2022-08-15) | Upgrade to 12.11.72 (step 1) |
| `vmd` app (motion) | v4.5.70, **Running**, 1 profile, full-frame `includeArea` trigger, filters `sizePercentage=[5,5]`, `timeShortLivedLimit=1`, `distanceSwayingObject=5` | v4.5-2, **Stopped**, default (non-full-frame) profile | Start app, expand trigger area, filters (step 4) |
| `objectanalytics` app | v1.26.205, Stopped | v1.1-5, Stopped | No action — not part of the live pipeline on either |
| `sds3sync` app (SD→S3 upload) | v0.9.5, **Running**, fully configured (`root.Sds3sync.*`) | **not installed** | Install .eap + configure (step 5) — the critical missing piece |
| Action1 rule (SD record) | 1 config `cctv_motion_sd_record` (`recording.storage`, `storage_id=SD_DISK`, pre=5000ms, post=2000ms) + 1 rule on topic `VMD/Camera1ProfileANY` | none | Recreate rule (step 6) |
| System clock (live, via HTTP `Date:` header) | correct, current | **stuck at Fri, 19 Nov 2021** on both units | Fix NTP (step 2) — clips would otherwise get 2021 timestamps |
| `root.Time.NTP.Server` / `ObtainFromDHCP` | `0.0.0.0` / `yes` | **identical values**, `0.0.0.0` / `yes` | Config alone is not a reliable check — the router hands out no NTP/DNS via DHCP at all (confirmed on the router's own admin UI), so set a static server on every unit (step 2) |
| `root.NetworkShare` | param group **errors** (`Error -1`) — not usable on this firmware/model despite existing in `root.Properties.NetworkShare` | same | Confirms SMB path is a dead end here — don't chase it |
| `root.Motion` (legacy) | errors — VMD4 doesn't use it | empty response | Not applicable to this model |
| `root.Storage.S0` (SD) | `CleanupMaxAge=0` (unlimited) | `CleanupMaxAge=7` | Set to `0` to match (step 7) |
| `root.Network.SSH.Enabled` | `no` | `no` | Already matches |
| `root.HTTPS.Enabled` | `yes` | `yes` | Already matches |
| Static IP | `.4` (matches `eth0.IPAddress`) | `.24`/`.25` (already matches) | No action |
| Hostname | `axis-b8a44f6c2746` (default, never renamed) | `axis-b8a44f73558a` / `axis-b8a44f734f32` | No action |

## Setup steps for 192.168.0.24 and 192.168.0.25

Read `AXIS_CAMERA_SETUP_MANUAL.md` section 1 first (API discovery habits, VMD4
vs legacy quirks) — this doc only adds the SD+S3 pipeline specifics that
manual doesn't cover.

### 1. Firmware upgrade

.24/.25 are two major versions behind (10.12.91 → 12.11.72). VMD4 4.5.70 and
`sds3sync`'s compatible-OS range (`Min 12.0`) both assume firmware 12.x.

The exact firmware file that produced .4's build is available locally —
don't download a different one from Axis's site, use this one so the
resulting build matches exactly:

```
C:\Users\atotmakov\Documents\GitHub\axis\vendors_bins\axis_firmware\M3085-V_12_11_72.bin
```

**Confirmed on real hardware (2026-08-28, both .24 and .25): a direct jump
from 10.12.91 straight to 12.11.72 fails.** The camera accepts the upload
(200 OK, correct multipart form — `-F 'data={"apiVersion":"1.4","method":"upgrade"};type=application/json' -F "fwimage=@<path>;type=application/octet-stream"`,
JSON API version may report `1.4` or `1.5` depending on the currently
running firmware, harmless either way), reboots into it, then:
```
fwmgr-init: Rebooting to rollback firmware upgrade. Initiated by 'fwmgr'. Reason: Firmware initialization failed.
rrdetect: Firmware rollback detected after 0 min.
```
Axis's dual-bank safety net catches this and auto-rolls-back within about a
minute — no lasting damage, camera comes back exactly as it was — but the
target firmware never actually applies. **Go through the intermediate
version first**, also available locally:
```
C:\Users\atotmakov\Documents\GitHub\axis\vendors_bins\axis_firmware\M3085-V_11_11_212.bin
```
i.e. two upgrade calls in sequence: 10.12.91 → 11.11.212 → 12.11.72. Each
hop reboots the camera — expect a real (if brief) drop in reachability
during each one, unlike the failed direct jump (which never actually went
down long enough to notice, itself a tell that something was wrong).

Upload via AXIS web UI (System → Maintenance → Firmware upgrade) or curl,
**note the native Windows path** (`C:/...`, not Git Bash's `/c/...` — the
native curl.exe build can't resolve MSYS-style paths for local file reads
and fails with `curl: (26)`):

```bash
curl -s --digest -u root:root \
  -F 'data={"apiVersion":"1.4","method":"upgrade"};type=application/json' \
  -F "fwimage=@C:/Users/atotmakov/Documents/GitHub/axis/vendors_bins/axis_firmware/M3085-V_11_11_212.bin;type=application/octet-stream" \
  "http://<ip>/axis-cgi/firmwaremanagement.cgi"
# then, after it's back up and verified healthy:
curl -s --digest -u root:root \
  -F 'data={"apiVersion":"1.4","method":"upgrade"};type=application/json' \
  -F "fwimage=@C:/Users/atotmakov/Documents/GitHub/axis/vendors_bins/axis_firmware/M3085-V_12_11_72.bin;type=application/octet-stream" \
  "http://<ip>/axis-cgi/firmwaremanagement.cgi"
```

Poll for reboot completion and re-verify after **each** hop before moving to
the next:

```bash
until curl -s -m 4 --digest -u root:root "http://<ip>/axis-cgi/param.cgi?action=list&group=root.Properties.Firmware.Version" | grep -q "<target-version>"; do sleep 15; done
curl -s --digest -u root:root "http://<ip>/axis-cgi/param.cgi?action=list&group=root.Brand"   # basic health check
curl -s --digest -u root:root "http://<ip>/axis-cgi/admin/systemlog.cgi" | grep -iE "rollback|initialization failed"   # confirm no silent rollback
```

### 2. NTP / system clock — do not trust `ObtainFromDHCP=yes` alone

Both new units report the **exact same** time config as .4
(`root.Time.ObtainFromDHCP=yes`, `root.Time.NTP.Server=0.0.0.0`, meaning "use
whatever DHCP hands me") — yet .4's clock is live and correct while both new
units are frozen at **Fri, 19 Nov 2021**. Identical config does not mean
identical behavior here; DHCP-provided NTP silently isn't reaching these two
units. Don't just check the param value — check the actual clock:

```bash
# Quick check: HTTP response Date header reflects the camera's real system clock
curl -sI "http://<ip>/" | grep -i "^Date:"
```

**Confirmed root cause** (checked the router's own admin UI, Huawei
HG8145V5 at 192.168.0.1, LAN → DHCP Server): the DHCP server config page has
no NTP field at all (and Primary/Secondary DNS Server are also blank) — this
network's DHCP genuinely never hands out an NTP source via option 42. Relying
on `ObtainFromDHCP=yes` for time is a dead end here, on every camera, not
just these two — set a static NTP server explicitly instead:

```bash
curl -s --digest -u root:root -d "action=update&root.Time.NTP.Server=pool.ntp.org&root.Time.SyncSource=NTP" \
  "http://<ip>/axis-cgi/param.cgi"
```

Using `pool.ntp.org` (global NTP pool, round-robins across many servers,
works reliably from most networks). After setting it, wait a minute or two
and re-check the `Date:` header — confirm it's live and matches real time
before moving on, since every following step (recorded clip timestamps, S3
object keys via `sds3sync`'s time-based naming, systemlog correlation)
depends on the clock being correct.

**Add a Russian fallback server too.** The camera's web UI (System → Time
and location) exposes this as a proper multi-entry "Fallback NTP servers"
list — the legacy `root.Time.NTP.Server` param above only ever writes/reads
the **first** entry in that same list (confirmed: setting it via `param.cgi`
shows up as the first fallback server in the UI).

**The actual REST API, found 2026-08-29 by reading the web UI's own network
traffic** (via the browser's network-request log while loading/editing this
page — far more reliable than guessing method names): it's a completely
different endpoint family from the `ntp.cgi` JSON-RPC style APIs used
elsewhere in this doc (vmd, firmwaremanagement). `apidiscovery.cgi`'s
`"id": "ntp"` entry is a red herring for this — the real one isn't listed
there at all under an obvious name.

```bash
# Read current config
curl -s --digest -u root:root "http://<ip>/config/rest/network-time-sync/v1/ntp/client"
# -> {"status":"success","data":{"staticServers":["pool.ntp.org"],"enabled":true,
#     "maximumPoll":10,"minimumPoll":6,"serversSource":"DHCP","synced":true,
#     "nts":{...},"advertisedServers":[],"timeOffset":...,"timeToNextSync":...}}

# Set the fallback server list (full replace, not append — include every
# server you want, not just the new one)
curl -s --digest -u root:root -X POST "http://<ip>/config/rest/network-time-sync/v1/ntp/client" \
  -H "Content-Type: application/json" \
  -d '{"data":{"staticServers":["pool.ntp.org","ntp1.vniiftri.ru"]}}'
# -> {"status":"success"}
```

Two gotchas found by trial (both against a real device, immediately
reverted after confirming): POSTing the bare fields without a `data`
wrapper fails with `{"status":"error","error":{"code":12,"message":"Invalid
JSON body: There is no 'data' field in the request body"}}` — the write
body must mirror the `data` envelope the GET returns. And `staticServers` is
a **full replace**, not an add — POST the complete list you want, including
existing entries, or you'll drop them.

Verify:
```bash
curl -s --digest -u root:root "http://<ip>/config/rest/network-time-sync/v1/ntp/client"
# staticServers should list everything you set; synced flips to true within ~10-20s
```
(The web UI path from before still works fine too — System → Time and
location → second "Fallback NTP servers" field, auto-saves on blur — this
REST call is just the scriptable equivalent, useful for applying it to many
cameras at once instead of clicking through each one.)

Used `ntp1.vniiftri.ru` — Russia's State Time and Frequency Standard
(VNIIFTRI), a sensible low-latency fallback for MSK-timezone cameras next to
the global `pool.ntp.org` primary. Applied to all three cameras (.4, .24,
.25); all three show `synced: true` with both servers listed.

### 3. Confirm VAPIX access

```bash
curl -s --digest -u root:root "http://<ip>/axis-cgi/param.cgi?action=list&group=root.Brand"
```
Already confirmed working with `root`/`root` on both units — no admin
account setup needed.

### 4. Motion detection (VMD4)

```bash
# Start it (ships Stopped on new units)
curl -s --digest -u root:root "http://<ip>/axis-cgi/applications/control.cgi?action=start&package=vmd"

# Read current profile
curl -s --digest -u root:root -X POST "http://<ip>/local/vmd/control.cgi" \
  -H "Content-Type: application/json" -d '{"apiVersion":"1.4","method":"getConfiguration"}'
```

Expand the profile's `includeArea` trigger to full-frame and match the
reference filters, via `setConfiguration` (payload key is `params`, not
`data` — see `AXIS_CAMERA_SETUP_MANUAL.md` / `vapix.set_vmd4_configuration`
docstring for the exact quirk). Target profile shape (mirrors .4):

```json
{
  "profiles": [{
    "camera": 1,
    "uid": 1,
    "name": "Profile 1",
    "filters": [
      {"active": true, "type": "sizePercentage", "data": [5, 5]},
      {"active": true, "type": "timeShortLivedLimit", "data": 1},
      {"active": true, "type": "distanceSwayingObject", "data": 5}
    ],
    "triggers": [
      {"type": "includeArea", "data": [[-1.0,-1.0],[-1.0,1.0],[1.0,1.0],[1.0,-1.0]]}
    ]
  }],
  "cameras": [{"id": 1, "rotation": 0, "active": true}]
}
```
Read-modify-write the actual GET'd payload rather than pushing this verbatim
— preserve `configurationStatus` and anything else present.

### 5. Install and configure `sds3sync`

This is the piece that's completely absent on new units — nothing else in
the pipeline matters without it. The signed package is available locally:

```
C:\Users\atotmakov\Documents\GitHub\axis\acap-sd-s3-sync\dist\signed_SD_to_S3_Sync_0_9_5_aarch64.eap
```

**Correction (2026-08-29): the claim below that unsigned .eaps get rejected
was never actually verified and turned out to be wrong** — checked
`applications/config.cgi?action=get&name=AllowUnsigned` on all three cameras
and it's `true` everywhere, including .4, which ran the **unsigned** build
of this exact app successfully for months. Unsigned
installs work fine as long as `AllowUnsigned=true`. Use the `signed_` one
anyway — it clears the "ACAP apps: Unsigned" warning on the camera's own
Status page (Security card) and there's no downside — but don't repeat the
"camera will reject it" claim as if it's a hard technical requirement; it
isn't, on this device's current settings.

1. Upload + install:
   ```bash
   curl -s --digest -u root:root \
     -F "packfil=@signed_SD_to_S3_Sync_0_9_5_aarch64.eap" \
     "http://<ip>/axis-cgi/applications/upload.cgi"
   curl -s --digest -u root:root \
     "http://<ip>/axis-cgi/applications/control.cgi?action=start&package=sds3sync"
   ```
2. Confirm it registered and is running:
   ```bash
   curl -s --digest -u root:root "http://<ip>/axis-cgi/applications/list.cgi" | grep -i sds3sync
   ```
3. Configure via `param.cgi` (group `root.Sds3sync`). Fields observed on .4:
   `RecordingPath`, `Prefix` (per-camera S3 key prefix — use the new camera's
   own hostname, e.g. `axis-b8a44f73558a/`, **not** .4's), `S3Endpoint`,
   `S3Region`, `S3Bucket`, `S3PathStyle`, `S3InsecureTLS`, `IntervalSeconds`,
   `HeartbeatIntervalSeconds`, `S3AccessKey`, `S3SecretKey`.

   **Don't put the raw S3 credentials in any tracked file in this repo** —
   `cameras.yaml` is gitignored for exactly this reason; follow the same
   pattern. Current values pulled from .4 (2026-08-28) are saved to
   `docs/camera-004.secrets.md`, which is gitignored (`docs/*.secrets.md` in
   `.gitignore`) — read that file locally, or re-fetch live:
   ```bash
   curl -s --digest -u root:root \
     "http://192.168.0.4/axis-cgi/param.cgi?action=list&group=root.Sds3sync"
   ```
   then hand-apply the same values (with the new camera's own `Prefix` — its
   own hostname, not .4's) to `<new-ip>` via `action=update` on `param.cgi`.
   Whether every new camera should share .4's bucket/access key or get its
   own scoped credentials is a judgment call — confirm with whoever owns the
   VK Cloud storage account before reusing the same key across units.

   **Git Bash path-mangling gotcha, confirmed 2026-08-28:** if you set
   `RecordingPath` from Git Bash with a value like `/var/spool/storage/SD_DISK`,
   MSYS auto-rewrites it to a Windows path (e.g.
   `C:/Program Files/Git/var/spool/storage/SD_DISK`) before curl ever sends
   it, and the camera happily accepts the garbage value with no error —
   always read the param back afterward to confirm, and prefix the command
   with `MSYS_NO_PATHCONV=1` when setting this one:
   ```bash
   MSYS_NO_PATHCONV=1 curl -s --digest -u root:root \
     --data-urlencode "action=update" \
     --data-urlencode "root.Sds3sync.RecordingPath=/var/spool/storage/SD_DISK" \
     "http://<ip>/axis-cgi/param.cgi"
   ```

   **The app reads its config only at startup — it does not hot-reload.**
   If you start `sds3sync` before setting `root.Sds3sync.*`, its own log
   shows `S3Endpoint/S3AccessKey/S3SecretKey not configured yet` and it sits
   idle indefinitely even after you set the params. Set the config **first**,
   then start the app — or if you already started it, stop and start again
   (`action=stop` then `action=start` on `applications/control.cgi`) after
   configuring. Confirm it actually picked things up via its own log:
   ```bash
   curl -s --digest -u root:root "http://<ip>/axis-cgi/admin/systemlog.cgi?appname=sds3sync" | tail -20
   ```
   A healthy startup looks like `timer armed` → `heartbeat armed` →
   `heartbeat sent` → `uploaded <path> (N bytes)` for a handful of small
   housekeeping files (`recording_groups.conf`, `osr/...` index files,
   `status.json`) even before any real motion clip exists — that's the app
   confirming S3 connectivity/auth work, worth checking as an early signal
   before waiting on real motion.

### 6. SD-record action rule

Same two-step Action1 SOAP dance as `AXIS_CAMERA_SETUP_MANUAL.md` section 3,
but with `storage_id=SD_DISK` (not `NetworkShare`) and durations matching .4
(`pre_duration=5000`, `post_duration=2000`):

```bash
curl -s --digest -u root:root -X POST "http://<ip>/vapix/services" \
  -H "Content-Type: application/soap+xml; charset=utf-8" \
  -H 'SOAPAction: "http://www.axis.com/vapix/ws/action1/AddActionConfiguration"' \
  --data '<?xml version="1.0" encoding="utf-8"?><soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" xmlns:aa="http://www.axis.com/vapix/ws/action1"><soap:Body><aa:AddActionConfiguration><aa:NewActionConfiguration><aa:Name>cctv_motion_sd_record</aa:Name><aa:TemplateToken>com.axis.action.unlimited.recording.storage</aa:TemplateToken><aa:Parameters><aa:Parameter Name="storage_id" Value="SD_DISK"/><aa:Parameter Name="pre_duration" Value="5000"/><aa:Parameter Name="post_duration" Value="2000"/><aa:Parameter Name="stream_options" Value=""/></aa:Parameters></aa:NewActionConfiguration></aa:AddActionConfiguration></soap:Body></soap:Envelope>'
# -> note the returned <aa:ConfigurationID>
```

Then link the rule. .4's existing rule uses the **wildcard** profile topic
`tnsaxis:CameraApplicationPlatform/VMD/Camera1ProfileANY` — but per the setup
manual section 5.4, `AddActionRule` rejects that wildcard on creation. Use
the concrete topic instead when creating fresh:

```bash
curl -s --digest -u root:root -X POST "http://<ip>/vapix/services" \
  -H "Content-Type: application/soap+xml; charset=utf-8" \
  -H 'SOAPAction: "http://www.axis.com/vapix/ws/action1/AddActionRule"' \
  --data '<?xml version="1.0" encoding="utf-8"?><soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" xmlns:aa="http://www.axis.com/vapix/ws/action1" xmlns:wsnt="http://docs.oasis-open.org/wsn/b-2" xmlns:tns1="http://www.onvif.org/ver10/topics" xmlns:tnsaxis="http://www.axis.com/2009/event/topics"><soap:Body><aa:AddActionRule><aa:NewActionRule><aa:Name>cctv_motion_sd_record</aa:Name><aa:Enabled>true</aa:Enabled><aa:Conditions><aa:Condition><wsnt:TopicExpression Dialect="http://docs.oasis-open.org/wsn/t-1/TopicExpression/Concrete">tnsaxis:CameraApplicationPlatform/VMD/Camera1Profile1</wsnt:TopicExpression><wsnt:MessageContent Dialect="http://www.onvif.org/ver10/tev/messageContentFilter/ItemFilter">boolean(//SimpleItem[@Name="active" and @Value="1"])</wsnt:MessageContent></aa:Condition></aa:Conditions><aa:PrimaryAction>THE_CONFIG_ID_FROM_ABOVE</aa:PrimaryAction></aa:NewActionRule></aa:AddActionRule></soap:Body></soap:Envelope>'
```

### 7. SD retention

.4 has `root.Storage.S0.CleanupMaxAge=0` (unlimited — the card is a rolling
short-term buffer managed by its own `fifo` cleanup policy at 90% full,
regardless of age). New units default to `CleanupMaxAge=7`. Match .4:

```bash
curl -s --digest -u root:root -d "action=update&root.Storage.S0.CleanupMaxAge=0" \
  "http://<ip>/axis-cgi/param.cgi"
```
Confirm this is actually the intended behavior (vs. just never having been
touched on .4) before applying — worth a quick question rather than assuming.

### 8. Image/tampering settings — found via full plain-config diff

**Do this comparison on every new camera going forward, not just once.**
With all three cameras finally on identical firmware (12.11.72), a full
`param.cgi` dump diff against .4 is clean enough to be genuinely useful —
this is the same data the web UI's **System → Plain config** page shows
(`Select group` → the group you want, or leave "None" and search by
parameter ID). Pulling it via `curl` is far faster than the UI for a
three-way comparison:

```bash
for ip in <ip1> <ip2> <ip3>; do
  curl -s --digest -u root:root "http://$ip/axis-cgi/param.cgi?action=list" -o "/tmp/plainconfig_$ip.txt"
done
diff "/tmp/plainconfig_<reference-ip>.txt" "/tmp/plainconfig_<new-ip>.txt"
```

Expect identity-only diffs (hostname, MAC/IP, serial number, RTP multicast
addresses, `Sds3sync.Prefix`) — ignore those. **Found and fixed on
2026-08-29**, three genuine (non-identity) differences, present identically
on both .24 and .25 (both matched each other, both diverged from .4 the same
way — a strong signal these were untouched factory defaults, not anything
specific to either unit):

| Parameter | .4 | New units (factory default) | Applied |
|---|---|---|---|
| `root.ImageSource.I0.CaptureFrequency` | `50Hz` | `60Hz` | Set to `50Hz` — correct mains flicker-free frequency for this deployment (Russia is 50Hz) |
| `root.Tampering.T0.DarkDetectionEnabled` | `no` | `yes` | Set new units to `yes` (factory default); .4 was later updated to `yes` too (2026-08-29) so all three now agree — .4's original `no` was the outlier |
| `root.ImageSource.I0.CameraTiltOrientation` | `0` | `-90` | Set to `0` to match .4 |

**This `param.cgi` dump is NOT the full picture — it misses installed-app
metadata entirely.** Found the hard way (2026-08-29, user caught it after
noticing it in the web UI, not from this diff): `.4` was running the
**unsigned** build of `sds3sync` (`SignatureStatus="Unknown"`) while `.24`
and `.25` had the signed one — a real, meaningful difference that a
`param.cgi`-only diff can never show, because app signature/version/status
lives under a completely separate API. Always check both:

```bash
for ip in <ip1> <ip2> <ip3>; do
  curl -s --digest -u root:root "http://$ip/axis-cgi/applications/list.cgi" -o "/tmp/apps_$ip.txt"
done
diff "/tmp/apps_<reference-ip>.txt" "/tmp/apps_<new-ip>.txt"
```
Resolved by reinstalling the signed `.eap` on .4 (`applications/upload.cgi`
with the same package name upgrades in place) — confirmed the app stayed
`Running` through the upgrade with zero interruption, and its stored config
(`root.Sds3sync.*`, including the uploaded-file dedup state — logged as
`loaded N uploaded-file records` on restart) survived intact. All three now
show `SignatureStatus="Signed"`.

```bash
curl -s --digest -u root:root -d "action=update&root.ImageSource.I0.CaptureFrequency=50Hz&root.Tampering.T0.DarkDetectionEnabled=yes&root.ImageSource.I0.CameraTiltOrientation=0" \
  "http://<ip>/axis-cgi/param.cgi"
```

**A fourth setting also lives entirely outside `param.cgi`, found 2026-08-29
the same way as the app-signature gap above** (user caught it in the web UI,
not from any diff I ran): the **"Video object detection (VOD) engine"**
toggle (System → Plain config, its own card above the group selector — easy
to miss since it's not inside the group-browser UI at all). `.4` had it
`false`, `.24`/`.25` had it `true` (same "new units agree with each other,
.4 is the outlier" pattern as the earlier three). This is the
Deep-Learning-Processing-Unit engine backing AXIS Object Analytics / Scene
Metadata — currently moot either way since `objectanalytics` is `Stopped`
on all three, but matters the moment that app gets turned on.

Real endpoint (found by toggling it in the UI and reading the resulting
network call, not by guessing):
```bash
curl -s --digest -u root:root "http://<ip>/config/rest/video-analytics/v1/dlpu/enabled"
# -> {"status":"success","data":true|false}
curl -s --digest -u root:root -X PATCH "http://<ip>/config/rest/video-analytics/v1/dlpu/enabled" \
  -H "Content-Type: application/json" -d '{"data":false}'
```
Resolved 2026-08-29 by disabling it on **all three** cameras (not matching
.4 to the others this time — the other direction, matching the others to
.4) — confirm which way makes sense before assuming "match .4" is always
the right call; it wasn't for the first three findings, but was for this one.

**`CameraTiltOrientation` is the one to be careful with** — unlike the other
two, it's tied to the camera's actual physical mounting/rotation, not just
an environmental constant. Copying .4's value blindly is only correct if
the new camera is mounted the same way; a wrong guess here rotates the
recorded image incorrectly. Check the live image (Video → Installation, or
`Video/Rotate` in the UI) before applying, don't assume from the diff alone.

### 9. 24-hour clock display preference

Purely a web-UI display preference (how the "Date and time" panel and the
top-of-page clock render, e.g. `22:05` vs `10:05 PM`) — **not** a
`param.cgi` setting and not part of any REST config API; found by watching
network traffic while toggling it in System → Time and location. It's a
generic per-key preference store, not specific to time settings:

```bash
curl -s --digest -u root:root "http://<ip>/axis-cgi/clientnotes/set.cgi?group=ADA&key=24Hour&value=true"
```
No `get` counterpart exists (404) — verify by loading
`https://<ip>/camera/index.html#/system/timeLocation` in a browser and
checking the toggle/clock format directly. Applied to all three cameras
2026-08-29.

### 10. Verify end-to-end

Work through these in order — each rules out one link in the chain, so if
something's wrong you know which stage broke it instead of guessing:

1. **Clock is correct** (should already be confirmed in step 2, recheck
   anyway):
   ```bash
   curl -sI "http://<ip>/" | grep -i "^Date:"
   ```

2. **VMD is running and armed**:
   ```bash
   curl -s --digest -u root:root "http://<ip>/axis-cgi/applications/list.cgi" | grep -A0 'Name="vmd"'
   # Status="Running" expected
   ```

3. **SD card is healthy** (not full, not read-only, not locked):
   ```bash
   curl -s --digest -u root:root "http://<ip>/axis-cgi/disks/list.cgi?diskid=all"
   ```

4. **Trigger real motion** in front of the camera, then confirm the VMD
   event actually fired (poll briefly, or check the event system directly):
   ```bash
   curl -s --digest -u root:root "http://<ip>/axis-cgi/admin/systemlog.cgi" | tail -50
   ```

5. **A new clip landed on the SD card** under the configured
   `RecordingPath` (`/var/spool/storage/SD_DISK` on .4) — if you have shell
   access (`root.Network.SSH.Enabled` — leave `no` for normal operation,
   only enable temporarily for this check and disable again after, per
   `AXIS_CAMERA_SETUP_MANUAL.md` section 8):
   ```bash
   ls -la /var/spool/storage/SD_DISK
   ```
   Without shell access, at minimum confirm the Action1 rule actually fired
   by checking the systemlog for the action-engine's own trigger/record
   lines (same log as step 4) rather than assuming silence means success.

6. **`sds3sync` picked it up and uploaded it** — check its own log output.
   Axis ACAPs typically log through the camera's application log:
   ```bash
   curl -s --digest -u root:root "http://<ip>/axis-cgi/admin/systemlog.cgi?appname=sds3sync" | tail -50
   ```
   Look for a clean upload cycle with no repeated errors — a heartbeat line
   every `HeartbeatIntervalSeconds` (300s on .4) is a good sign the app loop
   itself is alive even between uploads.

7. **File actually exists in the S3 bucket**, under this camera's own
   `Prefix` (not .4's) — confirm object key, size, and that its timestamp
   reflects the corrected clock from step 1, not 2021:
   ```bash
   # Adjust for whatever S3-compatible client is available (aws cli / s3cmd / curl+sigv4)
   aws s3 ls "s3://<bucket>/<new-camera-prefix>/" --endpoint-url "<S3Endpoint>"
   ```
   Confirmed 2026-08-28: **no `aws` CLI or `boto3` available** in this
   environment. Worked around it with a ~60-line stdlib-only Python script
   (`hashlib`/`hmac`/`urllib`, no deps) that signs a plain `ListObjectsV2`
   GET with AWS SigV4 and hits the VK Cloud endpoint directly — write it to
   a scratch path outside the repo (it necessarily embeds the secret key
   inline) and delete it again right after use, same handling as any other
   secret-bearing temp file.

8. **Repeat steps 4–7 once more** after the first pass succeeds, ideally
   a few minutes apart — confirms the pipeline is stable across multiple
   trigger/upload cycles, not just a one-off that happened to work.

9. **Clean up any diagnostic access** opened along the way (SSH shell,
   verbose logging) per `AXIS_CAMERA_SETUP_MANUAL.md` section 8.

## Verification status (as of 2026-08-28)

Ran steps 1–3 and 6 of the verify sequence above against both .24 and .25
right after setup — items 4/5/8 need real motion, which wasn't available
(no way to physically trigger it remotely):

| Check | .24 | .25 |
|---|---|---|
| 1. Clock correct | ✅ live, matches real time | ✅ live, matches real time |
| 2. VMD running | ✅ `vmd` v4.5.70, `Status="Running"`, full-frame trigger confirmed | ✅ same |
| 3. SD card healthy | ✅ `status="OK"`, not full/locked/readonly | ✅ same |
| Action rule created + enabled | ✅ `RuleID=1`, topic `VMD/Camera1Profile1`, `Enabled=true` | ✅ same |
| 4/5. Real motion → SD clip | ⏳ not yet — no motion occurred in front of the camera during setup | ⏳ not yet |
| 6. `sds3sync` picked up config | ✅ log shows `timer armed` → `heartbeat armed` → `heartbeat sent` → 5 files uploaded, 0 failed | ✅ same |
| 7. Object confirmed in S3 bucket | ✅ housekeeping files present under `axis-b8a44f73558a/` (`status.json`, `recording_groups.conf`, `osr/...` index files) — **no motion `.mkv` yet** | ✅ same under `axis-b8a44f734f32/`, **no motion `.mkv` yet** |
| 8. Repeated pass | ⏳ blocked on the same missing motion trigger | ⏳ blocked |

For comparison, .4's bucket prefix (`axis-b8a44f6c2746/`) has real motion
clips from earlier the same day (e.g.
`20260828/20/20260828_200513_.../20260828_200513_14E5.mkv`), confirming the
full pipeline works end-to-end on a camera that's actually seeing motion.

**What's confirmed:** every piece of the pipeline is correctly configured
and S3 auth/connectivity is proven working (the housekeeping-file uploads
are `sds3sync` actually talking to the real bucket with the real
credentials, not a mock). **What's not yet proven:** the motion → SD-record
→ upload chain hasn't fired end-to-end on .24/.25, only exercised
individually per-link. Whoever's near these cameras next should walk in
front of each one, wait ~60s (the `IntervalSeconds` sync interval), then
re-run the step 7 bucket check for a `.mkv` under each camera's prefix to
close this out.

## Notes

- `objectanalytics` is Stopped on every camera checked (.4 included) — it's
  not part of the live pipeline; leave it alone.
- `root.NetworkShare` and legacy `root.Motion` are both dead ends on this
  model/firmware — don't spend time debugging `cctv apply` failures against
  these cameras, the tool's targets genuinely don't exist here.
- Should each camera get its own S3 access key (least privilege) instead of
  sharing .4's, now that this is being repeated across multiple units? Still
  open — flag to whoever owns the VK Cloud storage account before scaling
  past these two.
