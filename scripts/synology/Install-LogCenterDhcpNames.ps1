<#
.SYNOPSIS
Installs logcenter-dhcp-names.sh on a Synology NAS and schedules it.

.DESCRIPTION
Over one SSH session (Windows OpenSSH; you are asked for the SSH password,
then once for sudo) this:
  1. copies logcenter-dhcp-names.sh to RemoteDir on the NAS,
  2. creates two root tasks in DSM Task Scheduler, replacing earlier ones:
       "Log Center DHCP names (boot)"   - triggered on boot-up
       "Log Center DHCP names (hourly)" - every hour at :07
  3. runs the script once, which restarts Log Center if /etc/hosts changed.
Re-running it updates the script and tasks in place.

.EXAMPLE
.\Install-LogCenterDhcpNames.ps1 -NasHost 192.168.1.100 -User oceanadmin

.EXAMPLE
.\Install-LogCenterDhcpNames.ps1 -NasHost 192.168.1.100 -User oceanadmin -NameFormat '%h-%m'
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $NasHost,
    [Parameter(Mandatory)] [string] $User,
    [int] $Port = 22,
    [ValidatePattern('^/[A-Za-z0-9/._-]+$')] [string] $RemoteDir = '/volume1/scripts',
    # %m = MAC (12 lowercase hex digits), %h = DHCP hostname
    [ValidatePattern('^[A-Za-z0-9%._-]+$')] [string] $NameFormat = '%m',
    # Print the bash script that would run on the NAS instead of connecting.
    [switch] $ShowRemoteScript
)
$ErrorActionPreference = 'Stop'

$payloadPath = Join-Path $PSScriptRoot 'logcenter-dhcp-names.sh'
$payload = (Get-Content -Raw -LiteralPath $payloadPath).Replace("`r`n", "`n").TrimEnd("`n")
# Bake NameFormat into the installed copy: DSM rejects a task command that
# sets it inline (error 117), so the tasks run the bare script path.
$defaultFormat = 'NAME_FORMAT=${NAME_FORMAT:-%m}'
if (-not $payload.Contains($defaultFormat)) {
    throw "$payloadPath has no '$defaultFormat' line to set the name format in."
}
$payload = $payload.Replace($defaultFormat, "NAME_FORMAT=`${NAME_FORMAT:-$NameFormat}")

# Task Scheduler is driven through synowebapi, DSM's local WebAPI runner;
# the JSON parameters are built in python3 to keep the quoting sane.
$tasks = @'
import json, subprocess, sys

command = sys.argv[1]
BOOT = "Log Center DHCP names (boot)"
HOURLY = "Log Center DHCP names (hourly)"
NOTIFY = {"notify_enable": False, "notify_mail": "", "notify_if_error": False}


def api(api_name, method, version, check=True, **params):
    args = ["/usr/syno/bin/synowebapi", "--exec", f"api={api_name}", f"method={method}", f"version={version}"]
    args += [f"{k}={json.dumps(v)}" for k, v in params.items()]
    out = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True).stdout
    # The reply follows a "[Line N] Exec WebAPI: ... param={...}" log line.
    start = 0 if out.startswith("{") else out.index("\n{") + 1
    result = json.loads(out[start:])
    if check and not result.get("success"):
        sys.exit(f"{api_name} {method} failed: {result.get('error')}")
    return result.get("data")


api("SYNO.Core.EventScheduler", "delete", 1, check=False, task_name=BOOT)
api("SYNO.Core.EventScheduler.Root", "create", 1, task_name=BOOT, owner={"0": "root"}, event="bootup",
    depend_on_task="", enable=True, operation_type="script", operation=command, **NOTIFY)
print(f"task: {BOOT}")

old = [{"id": t["id"], "real_owner": t["real_owner"]}
       for t in api("SYNO.Core.TaskScheduler", "list", 2)["tasks"] if t["name"] == HOURLY]
if old:
    api("SYNO.Core.TaskScheduler", "delete", 2, tasks=old)
api("SYNO.Core.TaskScheduler.Root", "create", 4, name=HOURLY, owner="root", enable=True, type="script",
    extra={"script": command, **NOTIFY},
    schedule={"date_type": 0, "repeat_date": 1001, "week_day": "0,1,2,3,4,5,6", "monthly_week": [],
              "hour": 0, "minute": 7, "repeat_hour": 1, "last_work_hour": 23, "repeat_min": 0})
print(f"task: {HOURLY}")
'@.Replace("`r`n", "`n")

$remote = @"
set -euo pipefail
script='$RemoteDir/logcenter-dhcp-names.sh'
mkdir -p '$RemoteDir'
cat > "`$script" <<'__LOGCENTER_DHCP_NAMES__'
$payload
__LOGCENTER_DHCP_NAMES__
chmod 755 "`$script"
echo "installed `$script"
python3 - "`$script" <<'__TASKS__'
$tasks
__TASKS__
"`$script"
"@.Replace("`r`n", "`n")

if ($ShowRemoteScript) {
    $remote
    return
}

if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
    throw 'ssh not found - install the Windows OpenSSH client (Settings > Optional features).'
}

# The script travels base64-encoded inside the command line, so the
# terminal stays free for the SSH and sudo password prompts.
$encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($remote))
$command = "t=`$(mktemp) && echo $encoded | base64 -d > `$t && sudo bash `$t; rc=`$?; rm -f `$t; exit `$rc"

ssh -t -p $Port "$User@$NasHost" $command
if ($LASTEXITCODE -ne 0) {
    throw "Install failed on $NasHost (exit $LASTEXITCODE)."
}
Write-Host "Done. Log Center will name DHCP clients by NAME_FORMAT '$NameFormat'."
