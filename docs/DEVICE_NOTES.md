# XIM4 Device Notes

Operational behaviour and gotchas observed while reverse-engineering and driving the device.

## Shell LED ("beacon")

- **Steady / breathing color** = the **active config's beacon color** (the palette index stored in
  the config; see [CONFIG_FORMAT.md](CONFIG_FORMAT.md)).
- **White flicker** = Bluetooth **data exchange** in progress.

## Connecting and pairing

- The Manager app connects with an **insecure** (unauthenticated) RFCOMM socket, so a client can
  connect **without bonding**.
- Caveat: an unbonded connection is only accepted while the device is in its **connectable /
  discoverable window** — briefly after the physical button is pressed, and for a while after
  recent activity. Outside that window a connect attempt fails with `Host is down` (errno 112).
- For **autonomous reconnection** (no button press), **bond and trust** the host with the device.
  Once bonded, it is connectable whenever powered.
- The device is Classic Bluetooth: **one host connection at a time**.

## Wedging

Repeated or competing connection attempts (e.g. two hosts contending, or many rapid reconnects)
can leave the device **wedged** — the RFCOMM socket opens but the device goes silent on the
application handshake. Recovery:

1. Power-cycle the device (unplug ~10 s, replug, let it boot).
2. Ensure **only one host** has Bluetooth enabled while connecting.

## Firmware / app versioning

- The last XIM4 firmware is `4.00.20171004`; the app version handshake references `4.00.20160405`.
- The official Manager app is discontinued and does not run cleanly on current Android. This
  project communicates with the device directly over Bluetooth rather than depending on the app.

## Capture methodology (for extending this work)

- **btsnoop over the network** — with full HCI snoop logging enabled, the Android Bluetooth stack
  runs a TCP listener (port `8872`) that streams live snoop-formatted HCI. Forward it over adb and
  read it; this works on a non-rooted phone (the `adb bugreport` snoop log is not always included by
  OEM builds). Bound the read by wall-clock — the stream never idles.
- **Decode** with `tools/rfcomm_decode.py` (btsnoop → HCI → L2CAP → RFCOMM payloads).
- **Map fields** by controlled A/B: change one value in the app, save, capture the write, and diff
  consecutive writes with `tools/ab_diff.py`. The changed byte(s) are the field.
- **Cross-checking** — the checksum construction and the config field layout derived from captures
  were independently confirmed against the app's own behaviour, so the values here are not guesses.
