# Changelog

## 1.0.0 — 2026-11-26

Initial public release.

### Features

- Logitech G502 LIGHTSPEED via HID++ 2.0 feature `0x1001` battery voltage
- MCHOSE G98 V2 via Sinowealth `0x13` report (`0x4A` direct reply + `0x0A/0x05` notifications)
- ATK / VXE Nordic mouse (`0xFF05`, report `0x08`)
- DARKRIM JL_RCSP headset (VID `0x3654`, 65-byte report, CRC16-CCITT-FALSE)
- Standard HID Battery Strength fallback and manual calibration
- Compact Tkinter panel and two GDI-drawn tray icons
- Startup-folder `.lnk` with Task Manager enable/disable state
- Desktop directory link (symlink/junction) and file link (symlink/hardlink/`.lnk` fallback)
- Full debug window: feature dump, report-ID probe, input listen, raw output/feature send, calibration
- Overlapped HID reads with timeout and `CancelIoEx`
- No third-party dependencies and no log files

### Fixes / calibration

- G502 voltage-to-percentage uses the Solaar Logitech curve with `+0.4` calibration
- MCHOSE direct reply uses byte 5 and matches the vendor HUB's 10% rounding
