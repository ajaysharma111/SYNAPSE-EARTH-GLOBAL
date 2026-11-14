# Security notes — SYNAPSE EARTH v5

## Implemented in this prototype
- Passwords are hashed with Python `hashlib.scrypt`; no plaintext password is persisted.
- Session identifiers are generated with `secrets.token_urlsafe(32)`; only SHA-256 token digests are stored.
- Session cookies are HttpOnly, SameSite=Strict, path-scoped and expire after 12 hours.
- HTTPS deployments receive the Secure cookie attribute when the reverse proxy sends `X-Forwarded-Proto: https`.
- Login attempts are throttled per client IP and email identity.
- Logout checks a per-session CSRF token.
- Guest mode bypasses account creation and remains available.

## Not implemented / not claimed
- Email verification and email-based password reset.
- MFA, role-based operator authorization, signed FieldSync packages, end-to-end peer encryption.
- A complete CSRF model for every future state-changing endpoint.
- Production security headers/CSP, reverse-proxy configuration, audit log, backups, penetration testing.
- Emergency response certification.

## Deployment rule
Do not expose the built-in Python HTTP server directly to the public internet. Use a maintained production server behind HTTPS, secure secrets, configure trusted proxy headers, and complete the production checklist in README.md.


## Location privacy
- Geolocation is requested only after the user presses the location button.
- The browser sends coordinates to the local SYNAPSE EARTH server for lookup against locally installed packages.
- The prototype does not persist GPS coordinates in the account database.
- When deployed publicly, location requests would reach the deployed server; disclose this clearly and apply data minimization, access controls and retention limits.
