---
title: Laptop Troubleshooting Runbook
effective_from: 2026-04-02
owner: IT Service Desk
access_level: helpdesk
---
# Laptop Troubleshooting Runbook

## Blue screen after updates
If a laptop shows a blue screen after a Windows update, boot into Safe Mode (hold Shift while selecting
Restart), uninstall the latest quality update and restart. Report the stop code. If three consecutive boots fail,
swap the device and send it to IT for reimaging.

## Outlook crashes when opening attachments
Run Outlook in safe mode (outlook.exe /safe). If it works, disable add-ins one by one; the PDF preview add-in is
the most common cause. Clear the Outlook cache folder if the problem persists.

## Slow laptop
Check disk space (less than 10% free causes slowness), pending updates, and the antivirus scan schedule.
