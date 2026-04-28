---
name: coding-standards
description: "Apply language-specific coding standards and best practices for Python, TypeScript, JavaScript, Go, and Rust. Enforces naming conventions, module structure, import hygiene, error handling patterns, type annotation coverage, and style rules. Use when writing new code, reviewing a pull request, or auditing an existing codebase for standard compliance."
version: "1.0.0"
domain: engineering
mode: prompt
tags: [engineering, standards, quality, code-style, python, typescript, go, rust]
source: "https://github.com/anthropics/skills"
license: MIT
required_tools: [read_file, replace_in_file, lint_and_fix]
dependencies: []
---

# Coding Standards: Language-Specific Best Practices

Apply consistent, language-appropriate coding standards. Produce code that is idiomatic,
maintainable, and passes automated lint/style checks out of the box.

## When to Use

Use this skill when:
- Writing new code that will be merged into a shared codebase
- Reviewing a file or module for style and standard compliance
- Auditing a pull request before merge
- Onboarding a new module that diverges from project conventions

DO NOT use this skill for:
- Emergency hotfixes that must ship before a review cycle
- One-off scripts not committed to the main codebase
- Exploratory prototypes marked as throw-away

---

## Python

### Naming Conventions
| Element | Convention | Example |
|---------|-----------|---------|
| Module | `snake_case` | `task_store.py` |
| Class | `PascalCase` | `TaskRecord` |
| Function / method | `snake_case` | `get_task(task_id)` |
| Constant | `UPPER_SNAKE_CASE` | `MAX_RETRIES = 3` |
| Private | leading underscore | `_internal_helper()` |
| Type alias | `PascalCase` | `TaskId = str` |

### Type Annotations
- ALL public function signatures must have type annotations.
- Use `from __future__ import annotations` at the top of every file.
- Prefer `str | None` over `Optional[str]` (Python 3.10+).
- Use `list[X]` / `dict[K, V]` not `List[X]` / `Dict[K, V]`.

### Module Structure (ordered)
```python
"""Module docstring."""
from __future__ import annotations

# 1. stdlib imports (alphabetical)
# 2. third-party imports (alphabetical)
# 3. local imports (alphabetical)

# 4. constants / type aliases
# 5. dataclasses / models
# 6. helpers (private)
# 7. public API
```

### Error Handling
- Never `except Exception: pass`. Log or re-raise.
- Raise `ValueError` for bad inputs at public API boundaries.
- Raise `RuntimeError` for unrecoverable runtime failures.
- Use `from` chaining: `raise RuntimeError("msg") from original_exc`.

### Style Rules
- Max line length: 100 characters.
- Use `dataclasses.dataclass` over plain `__init__` for data containers.
- Prefer `pathlib.Path` over `os.path` strings.
- `f-string` for interpolation, never `%` or `.format()`.
- Immutable defaults: never use mutable defaults in function signatures.

---

## TypeScript / JavaScript

### Naming Conventions
| Element | Convention | Example |
|---------|-----------|---------|
| Variable / function | `camelCase` | `getTaskList()` |
| Class / interface | `PascalCase` | `TaskRecord` |
| Constant | `UPPER_SNAKE_CASE` | `MAX_RETRIES` |
| React component | `PascalCase` | `RunPanel` |
| File | `kebab-case` or `PascalCase` for components | `task-store.ts`, `RunPanel.tsx` |

### TypeScript Rules
- No implicit `any`. Every function parameter and return must be typed.
- Prefer `interface` for object shapes used in public APIs; `type` for unions/aliases.
- Use `readonly` on data container interfaces.
- Avoid `!` non-null assertions. Use `??` or optional chaining `?.`.
- `async/await` not `.then()`. Catch errors with `try/catch`.

### Module Rules
- Barrel exports via `index.ts` only for public module surfaces.
- No circular imports. Use dependency injection or event buses for cross-module communication.
- Named exports over default exports (except React components and page files).

### React / Component Standards
- Functional components only. No class components.
- Extract logic into custom hooks (`use*`). Keep JSX presentation-only.
- PropTypes via TypeScript interfaces, not the `prop-types` library.
- `key` props must be stable IDs, not array indices.

---

## Go

### Naming Conventions
- Exported symbols: `PascalCase`. Unexported: `camelCase`.
- Interfaces: noun or adjective that describes behaviour (`Reader`, `Storable`).
- Error variables: `errXxx` or `ErrXxx` for sentinel errors.

### Error Handling
- Return errors as the last return value, never panic for expected failures.
- Wrap errors: `fmt.Errorf("context: %w", err)`.
- Check errors immediately; never ignore with `_`.

### Module Rules
- One package per directory; package name equals directory name.
- Avoid `init()` except for registrations that have no other home.
- Use `context.Context` as first parameter for all functions that do I/O.

---

## Rust

### Naming Conventions
| Element | Convention |
|---------|-----------|
| Type / Trait | `PascalCase` |
| Function / method | `snake_case` |
| Constant | `UPPER_SNAKE_CASE` |
| Module | `snake_case` |

### Error Handling
- Use `Result<T, E>` — never `unwrap()` or `expect()` in production code.
- Define error types with `thiserror`.
- Use `?` operator for error propagation; explicit `match` for recovery.

### Style Rules
- Derive `Debug`, `Clone`, `PartialEq` on data structs where applicable.
- Prefer iterators and combinators over explicit loops.
- Mark functions `pub(crate)` when only internal to a crate.

---

## Universal Rules (all languages)

1. **No magic numbers** — extract named constants.
2. **Fail fast** — validate inputs at the boundary; never deep in implementation.
3. **Single responsibility** — a function does one thing; if it needs a comment to explain each section, break it up.
4. **No dead code** — remove unused imports, variables, and commented-out blocks.
5. **Tests alongside implementation** — every public function has at least one test.
6. **No hard-coded credentials** — use config, env vars, or secret stores.
7. **Immutable by default** — prefer `const`/`final`/`let` over mutable bindings.

## Verification Steps

After applying standards:
1. Run `lint_and_fix` with `fix: false` to get a report.
2. Confirm zero errors or document why each remaining warning is acceptable.
3. Run the project's test suite and confirm no regressions.
