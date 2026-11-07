# Contributing to hongzhao

Thanks for your interest in contributing!

## Language conventions (important)

This project deliberately mixes languages. Before opening a PR, please check
where your change lands:

| Surface | Language |
| --- | --- |
| CLI help / diagnostics / error messages | English |
| Rendered outputs, managed blocks, templates | English |
| `README.md`, `docs/` (incl. diagrams), issue templates | **Chinese (中文)** |
| `README.en.md`, `docs/en/` | English mirror — keep in sync with the Chinese side |
| SKILL.md | Chinese (中文) |
| **Code comments and docstrings (tests included)** | **Chinese (中文)** |
| Identifiers (function/variable/file names, error codes) | English |

Docs are Chinese-primary: the Chinese tree is the default and the source of
truth; `docs/en/` mirrors it. When you change one side, update the other in the
same PR. The Chinese-comment convention is intentional: it keeps the
maintainer's review context native while engine surfaces stay English.

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
