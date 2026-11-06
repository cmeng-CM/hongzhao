# Contributing to hongzhao

Thanks for your interest in contributing!

## Language conventions (important)

This project deliberately mixes languages. Before opening a PR, please check
where your change lands:

| Surface | Language |
| --- | --- |
| CLI help / diagnostics / error messages | English |
| Rendered outputs, managed blocks, templates | English |
| README, docs, SKILL.md, issue templates | English |
| **Code comments and docstrings (tests included)** | **Chinese (中文)** |
| Identifiers (function/variable/file names, error codes) | English |

The Chinese-comment convention is intentional: it keeps the maintainer's
review context native while all user-facing surfaces stay English.

## Sign your work (DCO)

Contributions are accepted under the Developer Certificate of Origin. Each
commit must include a `Signed-off-by:` line (use `git commit -s`):

```
Signed-off-by: Your Name <your-email@example.com>
```

## Development quickstart

```bash
pip install -e ".[dev]"
pytest
```

## Reporting issues / security

See [SECURITY.md](SECURITY.md) for vulnerability reporting. Regular bugs and
feature requests go through GitHub Issues (templates provided once the issue
trackers open during the beta phase).
