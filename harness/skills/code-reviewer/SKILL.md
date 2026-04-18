---
name: code-reviewer
description: "Automated code review for TypeScript, JavaScript, Python, Go, Swift, and Kotlin. Analyzes PRs for complexity and risk, checks for SOLID violations and code smells, detects security patterns (SQL injection, hardcoded secrets), and generates scored review reports. Use when reviewing pull requests, analyzing code quality, or generating review checklists."
version: "1.1.0"
domain: engineering
mode: prompt
tags: [engineering, code-review, security, quality, pr, refactoring]
source: "https://github.com/alirezarezvani/claude-skills/tree/main/engineering-team/code-reviewer"
license: MIT
---

# Code Reviewer

Automated code review tools for analyzing pull requests, detecting code quality
issues, and generating structured review reports.

## When to Use

- Reviewing a pull request before merge
- Checking code quality in a directory or file
- Generating a formal review report with a score and verdict
- Detecting security issues (SQL injection, hardcoded secrets, debug statements)
- Assessing PR blast radius and complexity before diving in

## Review Workflow

```
Analyze PR → Check Quality → Generate Report → Enforce Verdict
```

### Step 1: Assess PR Complexity

Look at the diff for:
- **Hardcoded secrets** — passwords, API keys, tokens
- **SQL injection risk** — string concatenation in queries
- **Debug statements** — `debugger`, `console.log`, `print()` left in
- **TypeScript `any` types** — weakens type safety
- **TODO/FIXME comments** — unfinished work indicators
- **ESLint disable comments** — bypassing lint rules

Assign a **complexity score 1–10** and a **risk category** (critical / high / medium / low).

### Step 2: Code Quality Check

Flag structural issues:
| Issue | Threshold |
|-------|-----------|
| Long function | > 50 lines |
| Large file | > 500 lines |
| God class | > 20 methods |
| Too many params | > 5 |
| Deep nesting | > 4 levels |
| High cyclomatic complexity | > 10 branches |

Also flag: missing error handling, unused imports, magic numbers, SOLID violations.

### Step 3: Security Code Review Checklist

| Category | Check |
|----------|-------|
| Input Validation | All user input validated and sanitized |
| Output Encoding | Context-appropriate encoding applied |
| Authentication | Passwords hashed with Argon2/bcrypt |
| Session | Secure cookie flags (HttpOnly, Secure, SameSite) |
| Authorization | Server-side permission checks on all endpoints |
| SQL | Parameterized queries used exclusively |
| File Access | Path traversal sequences rejected |
| Secrets | No hardcoded credentials or keys |
| Dependencies | No known-vulnerable packages |
| Logging | Sensitive data not logged |

### Step 4: Generate Verdict

| Score | Verdict |
|-------|---------|
| 90+ / no high issues | ✅ Approve |
| 75+ / ≤ 2 high issues | 💬 Approve with suggestions |
| 50–74 | 🔄 Request changes |
| < 50 or critical issues | 🚫 Block |

## Secure vs Insecure Patterns

```python
# ❌ SQL injection risk
query = f"SELECT * FROM users WHERE username = '{username}'"

# ✅ Parameterized query
query = "SELECT * FROM users WHERE username = %s"
cursor.execute(query, (username,))
```

```python
# ❌ Weak password hashing
import hashlib
hashed = hashlib.md5(password.encode()).hexdigest()

# ✅ Argon2id
from argon2 import PasswordHasher
ph = PasswordHasher()
hashed = ph.hash(password)
```

## Languages Supported

Python · TypeScript · JavaScript · Go · Swift · Kotlin
