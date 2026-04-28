---
name: senior-security
description: "Security engineering toolkit for threat modeling, vulnerability analysis, secure architecture design, and penetration testing guidance. Covers STRIDE analysis, OWASP Top 10, cryptography patterns, defense-in-depth, and incident response. Use when the user asks about security reviews, threat analysis, vulnerability assessments, secure coding practices, attack surface analysis, CVE remediation, or Zero Trust design."
version: "1.1.0"
domain: engineering
mode: prompt
tags: [security, threat-modeling, owasp, cryptography, vulnerability, incident-response, rbac]
source: "https://github.com/alirezarezvani/claude-skills/tree/main/engineering-team/senior-security"
license: MIT
---

# Senior Security Engineer

Security engineering workflows for threat modeling, vulnerability assessment,
secure architecture, secure code review, and incident response.

## When to Use

- Designing or reviewing authentication / authorization systems
- Performing a STRIDE threat model on a feature or service
- Reviewing code for OWASP Top 10 vulnerabilities
- Designing encryption strategy or key management approach
- Responding to a security incident
- Auditing API keys, secrets, or access controls

## Threat Modeling (STRIDE)

Apply STRIDE to each element of a data flow diagram:

| Category | Property | Mitigations |
|----------|----------|-------------|
| Spoofing | Authentication | MFA, certificates, strong auth |
| Tampering | Integrity | Signing, checksums, validation |
| Repudiation | Non-repudiation | Audit logs, digital signatures |
| Information Disclosure | Confidentiality | Encryption, access controls |
| Denial of Service | Availability | Rate limiting, redundancy |
| Elevation of Privilege | Authorization | RBAC, least privilege |

Score each threat with DREAD (Damage × Reproducibility × Exploitability × Affected users × Discoverability, each 1–10).

## Secure Architecture Principles

**Defense-in-depth layers:**
```
Layer 1: PERIMETER  — WAF, DDoS mitigation, rate limiting
Layer 2: NETWORK    — Segmentation, IDS/IPS, mTLS
Layer 3: HOST       — OS hardening, patching, endpoint protection
Layer 4: APPLICATION — Input validation, authentication, SAST
Layer 5: DATA       — Encryption at rest/transit, access controls, DLP
```

**Authentication pattern selection:**
| Use Case | Pattern |
|----------|---------|
| Web app | OAuth 2.0 + PKCE with OIDC |
| API auth | JWT (short expiry) + refresh tokens |
| Service-to-service | mTLS with certificate rotation |
| CLI/Automation | API keys with IP allowlisting |
| High security | FIDO2/WebAuthn hardware keys |

## Cryptography Reference

| Use Case | Algorithm | Notes |
|----------|-----------|-------|
| Symmetric encryption | AES-256-GCM | Authenticated encryption |
| Password hashing | Argon2id | Use library defaults for cost params |
| Message authentication | HMAC-SHA256 | 256-bit key |
| Digital signatures | Ed25519 | Fast, safe defaults |
| Key exchange | X25519 | Modern DH replacement |
| TLS | TLS 1.3 | Disable 1.0 / 1.1 |

Never use: MD5 or SHA1 for passwords, `Math.random()` for tokens, `eval()` on user input.

## Security Code Review Checklist

| Check | Risk if Missing |
|-------|----------------|
| All user input validated and sanitized | Injection |
| Context-appropriate output encoding | XSS |
| Parameterized queries everywhere | SQL injection |
| Path traversal sequences rejected | Path traversal |
| No hardcoded credentials or API keys | Secret leakage |
| Server-side authorization on every endpoint | Privilege escalation |
| Sensitive data not logged | Info disclosure |
| Dependencies audited for CVEs | Supply chain |

## Secret Scanning Patterns

```python
import re, pathlib

SECRET_PATTERNS = {
    "aws_access_key":  re.compile(r"AKIA[0-9A-Z]{16}"),
    "github_token":    re.compile(r"ghp_[A-Za-z0-9]{36}"),
    "private_key":     re.compile(r"-----BEGIN (RSA |EC )?PRIVATE KEY-----"),
    "generic_secret":  re.compile(r'(?i)(password|secret|api_key)\s*=\s*["\']?\S{8,}'),
}

def scan_file(path: pathlib.Path) -> list[dict]:
    findings = []
    for lineno, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
        for name, pattern in SECRET_PATTERNS.items():
            if pattern.search(line):
                findings.append({"file": str(path), "line": lineno, "type": name})
    return findings
```

## Security Headers Checklist

| Header | Recommended Value |
|--------|-------------------|
| Content-Security-Policy | `default-src 'self'; script-src 'self'` |
| X-Frame-Options | `DENY` |
| X-Content-Type-Options | `nosniff` |
| Strict-Transport-Security | `max-age=31536000; includeSubDomains` |
| Referrer-Policy | `strict-origin-when-cross-origin` |
| Permissions-Policy | `geolocation=(), microphone=(), camera=()` |

## Incident Response Severity

| Level | Response Time | Escalation |
|-------|---------------|------------|
| P1 — active breach/exfiltration | Immediate | CISO, Legal, Executive |
| P2 — confirmed, contained | 1 hour | Security Lead |
| P3 — potential, under investigation | 4 hours | Security Team |
| P4 — suspicious, low impact | 24 hours | On-call engineer |

Workflow: Identify → Contain → Eradicate → Recover → Post-mortem → Improve
