---
title: Remote Access and VPN Guide
effective_from: 2026-01-10
owner: IT Infrastructure
access_level: employee
---
# Remote Access and VPN Guide

## Overview
Acme uses GlobalProtect for remote access. The VPN is required for SAP, the warehouse management system (WMS)
and internal file shares. Microsoft 365 and Teams work without VPN.

## Connecting from home
1. Open the GlobalProtect client from the system tray.
2. Enter the portal address vpn.acme-logistics.de.
3. Sign in with your company account and approve the MFA prompt in Microsoft Authenticator.
If the connection drops every few minutes, switch from Wi-Fi 2.4 GHz to 5 GHz or a cable, and update the client
to version 6.2 or later. Persistent drops after that should be reported with the client log attached.

## Split tunnelling
Split tunnelling is enabled: only traffic to internal ranges goes through the VPN. Video calls go directly to
the internet. Exceptions to split tunnelling must be approved by IT Security.

## Contractors
Contractors receive VPN access only for the duration of their contract and only to the systems listed in
their access request. Contractor VPN accounts expire automatically on the contract end date.

## Working from abroad
Working from EU/EEA countries (for example Austria or the Netherlands) is allowed for up to 30 days per year
with the VPN. Working from outside the EU/EEA requires prior approval from IT Security and HR, because of
data-protection and export-control rules. The VPN blocks connections from sanctioned countries.
