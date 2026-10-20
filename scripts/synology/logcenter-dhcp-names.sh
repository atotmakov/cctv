#!/bin/bash
# Give Synology Log Center a name for every DHCP client, taken from the
# NAS's own DHCP Server.
#
# Senders that put no HOSTNAME in their BSD syslog messages (e.g. sysklogd
# 1.4.1 forwarding) are filed under their source IP. Log Center's syslog-ng
# resolves that IP (use_dns(yes); hosts: files dns), so an /etc/hosts entry
# per DHCP client turns the IP into a name. Senders that do send a hostname
# keep it (keep_hostname(yes)), so this only fills in the missing ones.
#
# IP, MAC and DHCP hostname come from the DHCP Server: reservations first,
# then active leases. The name is NAME_FORMAT with %m = MAC as 12 lowercase
# hex digits and %h = DHCP hostname; a client that gave no hostname is
# named by its MAC alone. Entries live in a marked block in /etc/hosts; Log Center is
# restarted only when the block changes, since syslog-ng caches lookups.
#
# DSM may rewrite /etc/hosts, so run this as root from Control Panel >
# Task Scheduler: once on boot-up, and on a schedule (e.g. hourly) to pick
# up new clients.
#
# Usage: logcenter-dhcp-names.sh [--dry-run]
set -euo pipefail

HOSTS=${HOSTS:-/etc/hosts}
DHCPD_DIR=${DHCPD_DIR:-/etc/dhcpd}
NAME_FORMAT=${NAME_FORMAT:-%m}
SYNOPKG=${SYNOPKG:-/usr/syno/bin/synopkg}
BEGIN="# BEGIN syslog names from DHCP (logcenter-dhcp-names.sh)"
END="# END syslog names from DHCP"

dry_run=0
case "${1:-}" in
  --dry-run) dry_run=1 ;;
  "") ;;
  *) echo "usage: $0 [--dry-run]" >&2; exit 2 ;;
esac

# "ip mac hostname" triples, reservations before leases so a reservation wins.
dhcp_clients() {
  # dhcp-host=<mac>,<name>,<ip>,<lease>
  cat "$DHCPD_DIR"/dhcpd-*-static.conf 2>/dev/null | awk -F'[=,]' '
    $1 == "dhcp-host" {
      for (i = 3; i <= NF; i++) if ($i ~ /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/) {
        print $i, $2, (i > 3 && $(i - 1) != "" ? $(i - 1) : "*"); break
      }
    }'
  # dnsmasq lease: <expiry> <mac> <ip> <hostname or *> <client-id> [iface]
  awk 'NF >= 4 { print $3, $2, $4 }' "$DHCPD_DIR"/dhcpd.conf.leases 2>/dev/null || true
}

desired_block() {
  dhcp_clients | awk -v fmt="$NAME_FORMAT" '
    {
      ip = $1; mac = tolower($2); host = tolower($3)
      if (mac !~ /^([0-9a-f]{2}:){5}[0-9a-f]{2}$/ || (ip in seen_ip) || (mac in seen_mac)) next
      seen_ip[ip] = 1; seen_mac[mac] = 1
      gsub(":", "", mac)
      if ((host == "" || host == "*") && fmt ~ /%h/) {
        name = mac
      } else {
        name = fmt
        gsub(/%m/, mac, name); gsub(/%h/, host, name)
      }
      printf "%s\t%s\n", ip, name
    }' | sort -t. -k1,1n -k2,2n -k3,3n -k4,4n
}

current_block() {
  awk -v b="$BEGIN" -v e="$END" '$0 == e { inside = 0 } inside { print } $0 == b { inside = 1 }' "$HOSTS"
}

without_block() {
  awk -v b="$BEGIN" -v e="$END" '$0 == b { skip = 1 } !skip { print } $0 == e { skip = 0 }' "$HOSTS"
}

new=$(desired_block)
if [ "$new" = "$(current_block)" ]; then
  echo "$HOSTS up to date ($(printf '%s' "$new" | grep -c . || true) DHCP names)"
  exit 0
fi

if [ "$dry_run" = 1 ]; then
  echo "would write to $HOSTS:"
  printf '%s\n%s\n%s\n' "$BEGIN" "$new" "$END"
  exit 0
fi

tmp=$(mktemp "$HOSTS.dhcp.XXXXXX")
trap 'rm -f "$tmp"' EXIT
{
  without_block
  [ -n "$new" ] && printf '%s\n%s\n%s\n' "$BEGIN" "$new" "$END"
} > "$tmp"
# Rewrite in place rather than mv, keeping the file's owner and mode.
cat "$tmp" > "$HOSTS"
echo "updated $HOSTS ($(printf '%s' "$new" | grep -c . || true) DHCP names)"
[ -n "$new" ] && printf '%s\n' "$new"

"$SYNOPKG" restart LogCenter
