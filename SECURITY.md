# Security

Device Monitor is intended for trusted local networks only.

The Agent has no built-in authentication and exposes configuration and diagnostic endpoints on port 9090. To limit its exposure it enforces a source-address allowlist, which is **loopback-only by default** — set `MONITOR_ALLOW_NETS` to the range your dashboard polls from (comma-separated CIDRs; empty means refuse everything). The check uses the TCP peer address; `X-Forwarded-For` and `X-Real-IP` are attacker-controlled headers and are deliberately ignored. All POSTs must declare `Content-Type: application/json`.

The allowlist is not authentication: any host that can send packets from an allowed range is treated as trusted, so keep the ranges as narrow as you can. Do not expose the agent directly to the public internet. Across an untrusted boundary, add authentication and an HTTPS reverse proxy on top.

Do not commit `config.json`, API keys, passwords, host inventories, private IP addresses, or deployment scripts containing machine-specific paths.

If you discover a vulnerability, report it privately to the repository owner rather than opening a public issue with exploit details.
