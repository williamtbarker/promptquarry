# PromptQuarry

[![CI](https://github.com/williamtbarker/promptquarry/actions/workflows/ci.yml/badge.svg)](https://github.com/williamtbarker/promptquarry/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

PromptQuarry is a local, dependency-free Python CLI for recovering code from large ChatGPT
data-export archives. It builds an auditable SQLite index, deduplicates exact fragments, ranks
likely salvage candidates, flags material that needs a privacy review, and exports a manageable
shortlist without executing recovered code.

The project is designed for archives too large to load into memory. Its incremental JSON decoder
reads conversation arrays in bounded chunks directly from ZIP members; the archive is never
extracted.

## Why this exists

Years of technical conversations can contain useful scripts, abandoned prototypes, and multiple
versions of the same project. A raw search finds snippets but does not answer the more useful
questions: Which fragments are substantial? Which parse? How many are duplicates? Which may
contain credentials or personal paths? Where did each block occur?

PromptQuarry turns that recovery problem into a deterministic pipeline:

1. Discover standard `conversations.json` or chunked `conversations-NNN.json` members.
2. Stream conversation objects without expanding the entire JSON document in memory.
3. Extract backtick and tilde fences plus messages explicitly typed as code.
4. Normalize line endings and deduplicate blocks by SHA-256 digest.
5. Infer language and calculate an explainable salvage score.
6. Record every occurrence and its provenance in SQLite.
7. Review metadata, search locally, and export only selected candidates.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .

promptquarry build ~/Downloads/chatgpt-export.zip --db quarry.sqlite3
promptquarry summary quarry.sqlite3
promptquarry review quarry.sqlite3 --languages python,rust,bash --limit 50
promptquarry search quarry.sqlite3 "argparse"
promptquarry extract quarry.sqlite3 candidates \
  --languages python,rust,bash \
  --minimum-score 20
```

Commands emit JSON on standard output. A long build reports periodic counts on standard error,
so the final JSON remains machine-readable.

For very large archives, `--skip-archive-hash` avoids the separate pass needed to fingerprint
the complete ZIP. Content-block digests are still calculated.

## Commands

```text
promptquarry build ARCHIVE [--db DATABASE]
promptquarry summary DATABASE
promptquarry review DATABASE [--languages LIST] [--limit N]
promptquarry search DATABASE QUERY [--limit N]
promptquarry extract DATABASE OUTPUT [--languages LIST] [--minimum-score N]
```

Language filters are comma-separated. Common aliases such as `py`, `rs`, `sh`, and `rscript`
are accepted.

## Scoring

Scores are deterministic triage signals, not claims that code is correct. The scorer records its
reasons alongside each block.

| Signal | Effect |
|---|---:|
| Recognized language | +12 |
| At least 12 lines | +8 |
| At least 40 lines | +8 |
| Function, class, process, or similar declaration | +10 |
| Test-related constructs | +8 |
| CLI or main entry point | +7 |
| Valid Python or JSON syntax | +12 |
| Invalid Python or JSON syntax | -16 |
| Unterminated fence | -10 |
| Placeholder markers | -7 each |
| Fewer than 40 non-whitespace characters | -15 |

The bounded score range is 0–100. Syntax remains `unchecked` for languages that cannot be safely
validated with the Python standard library. PromptQuarry never compiles or runs candidates.

## Privacy and safety

The index contains recovered code and, by default, conversation titles. Treat it as private:

- index databases, manifests, and extracted code are created with owner-only file permissions on
  POSIX systems;
- `--title-policy hash` stores title hashes, while `--title-policy drop` stores no titles;
- likely credentials, private keys, email addresses, and macOS home paths are flagged;
- flagged blocks are excluded from `review` and `extract` unless `--include-sensitive` is given;
- source messages and complete transcripts are not copied into the index; and
- archive members are read directly, with configurable per-member and total size limits.

Sensitivity detection is intentionally conservative and cannot guarantee that a block is safe to
publish. Human review and testing remain mandatory.

## SQLite model

| Table | Purpose |
|---|---|
| `metadata` | Schema version, archive name/hash, build time, and title policy |
| `conversations` | Minimal conversation-level provenance |
| `code_blocks` | Unique normalized code, score, language, flags, and reasons |
| `occurrences` | Every message location in which each unique block appeared |

An index is built at a temporary path, integrity-checked, permission-restricted, and atomically
moved into place. If rebuilding fails, a previously valid index is preserved.

## Supported export shape

Conversation members must contain a top-level JSON array, which is the standard ChatGPT export
shape. Both a single `conversations.json` and numbered chunks are supported, including members
inside ZIP subdirectories. Each conversation must contain an object-valued `mapping`. Malformed
JSON, non-object conversations, and missing or non-object mappings fail with an explicit error
without replacing an existing index. Empty arrays, empty mappings, and structural nodes without
messages are supported. Unusable entries inside a supported mapping are skipped; the tool does
not certify that every possible message payload contains recoverable code.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m ruff format .
python -m ruff check --fix .
./scripts/verify.sh
```

The verifier runs compilation, 35 unit and integration tests, Ruff, strict mypy checks, an
end-to-end synthetic recovery, and wheel creation. CI executes the complete suite on Python 3.10
through 3.13.

## Limitations

- Deduplication is exact after whitespace normalization, not semantic or near-duplicate matching.
- Ranking prioritizes review; it does not establish correctness, ownership, licensing, or safety.
- Only fenced blocks and messages explicitly typed as code are indexed.
- Search uses portable SQLite substring matching rather than language-aware indexing.
- The tool requires the conversation containers described above; new export formats may need an
  explicit parser update.

## License

MIT. See [LICENSE](LICENSE).
