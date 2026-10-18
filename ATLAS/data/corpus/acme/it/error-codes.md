---
title: Application Error Codes Reference
effective_from: 2026-02-01
owner: IT Applications
access_level: employee
---
# Application Error Codes Reference

## Warehouse management system (WMS) errors
| Code | Meaning | First action |
|---|---|---|
| E-4471 | Scanner lost session with the WMS server (token expired) | Log out of the handheld scanner and log in again; if it persists, restart the scanner cradle |
| E-4472 | Pallet ID not found in WMS | Check the label is not damaged; enter the ID manually |
| E-5103 | Printer queue for shipping labels is full | Clear the queue in the label printer web console |
| E-6001 | SAP interface timeout | Wait 5 minutes and retry; if it repeats, open a ticket with priority high |

## SAP errors
SAP short dumps (ST22) must be reported with the transaction code and the time of the error.
Do not retry financial postings more than once; duplicate postings must be reversed by Finance.
