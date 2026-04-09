---
title: "Product Brief: cctv"
status: "draft"
created: "2026-03-31"
updated: "2026-03-31"
inputs: []
---

# Product Brief: cctv

## Executive Summary

Managing multiple IP cameras should not require clicking through a web UI for each device. For home system administrators running a small Axis camera fleet, every configuration change — a new SMB share, a motion detection adjustment, a network setting — means repeating the same manual steps across every camera. This is slow, error-prone, and leaves no audit trail.

**cctv** is a Python CLI tool that brings configuration-as-code to Axis IP cameras. The administrator defines the desired camera state once in a YAML file, and the tool discovers all Axis cameras on the local network and applies that configuration uniformly via the Axis VAPIX API. One command. All cameras. Repeatable.

This fills a clear gap: Axis's own management tool (AXIS Device Manager) is GUI-only and designed for enterprise IT departments, not for home labs. No open-source CLI alternative exists. cctv is the missing tool for the technically-minded home sysadmin who treats their network like infrastructure.

---

## The Problem

A home sysadmin installs four Axis cameras. To configure each one, they open a browser, navigate to the camera's IP, log in, set the SMB network share path, enable motion detection, adjust network settings — then repeat the entire sequence for every remaining camera. If a setting changes later (a NAS IP, a motion sensitivity threshold), the whole manual process repeats.

The status quo has three compounding costs:

- **Time** — Even a modest fleet of 5–10 cameras turns a single configuration change into 30+ minutes of repetitive clicking.
- **Inconsistency** — Manual processes drift. Cameras end up with subtly different settings, making debugging unpredictable.
- **No auditability** — There is no record of what changed, when, or why. Rolling back is impossible without re-clicking everything.

Existing tools don't solve this. AXIS Device Manager is Windows-only, GUI-driven, and built for enterprise procurement workflows. Home Assistant's Axis integration focuses on live events and streaming — not bulk configuration management.

---

## The Solution

cctv reads a single YAML configuration file and applies it to all Axis cameras discovered on the local network.

The workflow is three steps:

1. **Define** — write a YAML file specifying camera settings: SMB share path and credentials, motion detection parameters, network configuration, and camera login credentials.
2. **Run** — execute `cctv apply config.yaml`. The tool scans the configured IP subnet to discover all Axis cameras, then applies the configuration to each one via VAPIX API calls.
3. **Done** — each discovered camera is configured. The tool reports success/failure per device.

A `cctv list` command (discover-only, no changes applied) lets the user verify which cameras are reachable before committing to a full apply.

The config file is plain text. It lives in version control. Changes are diffable, reviewable, and reversible.

---

## What Makes This Different

| | cctv | AXIS Device Manager | Manual Web UI |
|---|---|---|---|
| Scriptable / automatable | Yes | No | No |
| Version-controllable config | Yes | No | No |
| Cross-platform | Yes (Python) | Windows only | Any browser |
| Auto-discovery | Yes | Yes | Manual |
| Open source | Yes | No | — |

The key differentiator is the **declarative config file**. Other tools are session-based — you make changes interactively and nothing is persisted in a reusable, portable form. cctv makes camera configuration a first-class infrastructure artifact.

---

## Who This Serves

**Primary: The home sysadmin.** Technically proficient, runs a home network with a NAS, VLANs, and self-hosted services. Comfortable with the command line and YAML. Has 2–10 Axis cameras installed for home security. Values repeatability, version control, and not clicking through UIs. Likely already uses tools like Ansible, Docker Compose, or Home Assistant.

The "aha moment" arrives the first time a NAS IP changes and reconfiguring all cameras takes 10 seconds instead of 45 minutes.

---

## Success Criteria

- **Configuration applies cleanly** to all discovered cameras in a single command with no manual intervention.
- **Idempotent** — running the same config twice produces no errors and no unintended changes.
- **Discovery works** — all Axis cameras on the local subnet are found without manual IP entry.
- **Failure is clear** — when a camera is unreachable or rejects a setting, the error message tells the user exactly what failed and why.

---

## Scope

**In scope for v1:**
- Subnet IP range scan to discover Axis cameras (`192.168.x.0/24` configurable)
- `cctv list` — discover-only command, no changes applied
- `cctv apply config.yaml` — apply full configuration to all discovered cameras
- YAML configuration file format (camera credentials stored in plaintext — v1 trade-off, documented clearly)
- Apply network settings (IP, hostname)
- Configure SMB/CIFS network share for video storage
- Enable and configure built-in Axis motion detection
- Per-camera success/failure reporting
- Python implementation using VAPIX API

**Explicitly out of scope for v1:**
- Non-Axis camera brands
- Video streaming or playback
- Web UI or GUI of any kind
- Cloud connectivity or remote access
- User authentication management
- Firmware upgrades

---

## Vision

If successful, cctv becomes the standard infrastructure-as-code tool for Axis camera fleets in home and small-office environments. The config file format evolves to cover the full VAPIX API surface — analytics apps, ACAP plugins, certificate management, event rules. An optional "dry run" mode shows what would change before applying. A `--diff` flag compares live camera state against the config file.

In 2–3 years: multi-vendor support (Hikvision, Dahua, ONVIF-compliant cameras) and an Ansible module wrapper, making cctv a natural fit for home lab automation stacks alongside tools like Ansible and Terraform.
