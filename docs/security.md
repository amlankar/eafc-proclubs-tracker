# Security model

The viewer is designed for a small group of trusted friends behind an HTTPS proxy such as Tailscale Funnel. It uses Python's standard-library HTTP server with bounded workers and socket timeouts. It is not intended for large-scale anonymous traffic or multi-tenant hosting.

## Trust boundaries

- Only local CLI collection writes the archive. HTTP accepts GET only and opens SQLite read-only connections. There is no collection or editing endpoint.
- Shared mode authenticates every route, including static files and health checks. Full raw archive export is disabled, while detailed match data and sanitized CSV exports remain accessible to signed-in viewers.
- Unauthenticated serving is restricted to loopback. Network binding requires shared credentials. Keep the backend on loopback and use HTTPS for remote access: Basic authentication alone does not encrypt traffic.
- Passwords use unique 16-byte salts and PBKDF2-HMAC-SHA256 with 600,000 iterations. Comparisons use constant-time primitives. Legacy local SHA-256 verifiers migrate using the matching private password file. This follows the [OWASP password storage guidance](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html).
- Twenty failed authenticated requests within a minute temporarily block login attempts. This is a bounded global window, independent of untrusted forwarding headers. It limits guessing, but an attacker can temporarily block legitimate users. Missing credentials produce the normal browser challenge without consuming this budget.
- HTTP workers are capped at 16, sockets time out after ten seconds, routes and filters are validated, error responses omit traces, and responses carry a restrictive Content Security Policy and other browser headers. Saturated connections are dropped.
- CSV names beginning with spreadsheet formula prefixes are escaped. Browser HTML rendering escapes external names; regression checks exercise malicious name payloads.

## Private files

`config.toml`, `data/`, databases, raw starting snapshots, exports, credentials and tunnel state are ignored by Git. The data directory uses mode 0700 and credentials/database use mode 0600. The plaintext password file exists for local sharing administration; it is not served over HTTP. SQLite backups and exports contain club/player data and should be handled as private files.

Tests use anonymized fixtures and temporary databases. Fixture shape and counters model real API responses, but player names and identifiers have been replaced. Tests never call EA.

## Deployment and maintenance

The setup script uses user services with `NoNewPrivileges`, a restrictive umask, memory/task limits and a file descriptor cap. It does not change router rules or account policy. Sharing commands can change the machine's Funnel mapping on port 443; reserve that mapping for this viewer.

The shared password grants access to the entire dashboard; there are no individual accounts, roles or per-friend revocation. Rotate it with `bash scripts/share.sh rotate` when needed. Basic authentication is cached by browsers and has no reliable server-side logout. The temporary Cloudflare helper is optional and requires an explicit start.

Pinned development dependencies reduce unexpected changes, but need periodic review and updates. Checks run locally; there are no GitHub Actions workflows. No third-party packages are required at runtime. If reporting a security issue, contact the repository owner privately and omit credentials, raw exports and personal data from public issues.
