# Security

Device Monitor is intended for trusted local networks only.

The Agent currently has no built-in authentication and exposes configuration and diagnostic endpoints on port 9090. Do not expose it directly to the public internet. Restrict access with the Windows firewall, a trusted VPN, or an authenticated HTTPS reverse proxy.

Do not commit `config.json`, API keys, passwords, host inventories, private IP addresses, or deployment scripts containing machine-specific paths.

If you discover a vulnerability, report it privately to the repository owner rather than opening a public issue with exploit details.
