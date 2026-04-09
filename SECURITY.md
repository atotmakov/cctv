# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| latest (`master`) | Yes |

## Reporting a vulnerability

Please **do not** report security vulnerabilities through public GitHub issues.

Instead, open a [GitHub private security advisory](https://github.com/atotmakov/cctv/security/advisories/new) so the issue can be assessed and patched before public disclosure.

Include as much of the following as possible:

- Description of the vulnerability and its potential impact
- Steps to reproduce
- Any suggested fix or mitigation

You can expect an initial response within 5 business days.

## Security considerations

- `cameras.yaml` contains plaintext credentials. Never commit it to a public repository — it is excluded via `.gitignore`.
- All camera communication uses HTTP Basic Auth over the local network via the VAPIX API. Use a dedicated network segment or VPN for camera traffic.
- Credentials are not stored by this tool beyond what is read from `cameras.yaml` at runtime.
