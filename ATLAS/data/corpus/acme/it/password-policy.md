---
title: Password and Account Policy
effective_from: 2026-03-01
owner: IT Security
access_level: employee
---
# Password and Account Policy

## Scope
This policy applies to every Acme Logistics employee, contractor and service account that authenticates
against the company directory (Entra ID) or any system connected to single sign-on (SSO).

## Password requirements
All interactive accounts must meet the following requirements.

| Requirement | Standard accounts | Privileged accounts |
|---|---|---|
| Minimum length | 14 characters | 20 characters |
| Rotation | Only after suspected compromise | Every 180 days |
| MFA | Required | Required, phishing-resistant (FIDO2 key) |
| Reuse | Last 12 passwords blocked | Last 24 passwords blocked |
| Lockout | 10 failed attempts, 15 minutes | 5 failed attempts, until IT unlocks |

Passphrases (four or more unrelated words) are encouraged. Password managers approved by IT: Bitwarden Business.

## Account lockout
After 10 failed sign-in attempts a standard account is locked for 15 minutes and unlocks automatically.
If you are still locked out after 15 minutes, open a ticket with the IT Service Desk. Privileged accounts are
only unlocked by IT after identity verification by phone.

## Password resets
Self-service reset is available at https://passwordreset.acme.internal for accounts with MFA registered.
If self-service fails, the IT Service Desk sends a reset link to the user's registered company email after
verifying identity. IT staff never ask for your current password. Resets requested on behalf of another person
are refused unless the request comes from that person's line manager and is approved by IT Security.

## Shared and service accounts
Shared accounts are prohibited except for documented service accounts. Service account passwords are stored
in the IT vault and rotated every 90 days by the platform team.
