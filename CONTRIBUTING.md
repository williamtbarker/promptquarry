# Contributing

Focused issues and pull requests are welcome.

1. Install the development dependencies with `python -m pip install -e '.[dev]'`.
2. Add synthetic tests for any supported export variation.
3. Run `python -m ruff format .` and `python -m ruff check --fix .`.
4. Run `./scripts/verify.sh`.
5. Document changes to parsing, scoring, privacy flags, or the SQLite schema.

Never use private conversation archives as fixtures. Tests and bug reports must contain minimal,
synthetic data. New detection rules should remain deterministic and explainable.

By contributing, you agree that your contribution may be distributed under the MIT License.
