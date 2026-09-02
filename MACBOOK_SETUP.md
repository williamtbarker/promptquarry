# macOS setup and GitHub release

These commands assume the repository is `~/Documents/promptquarry`.

## Verify locally

```bash
cd ~/Documents/promptquarry
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
python -m ruff format .
python -m ruff check --fix .
./scripts/verify.sh
```

The first two Ruff commands may make formatting and import-order edits. Review them with
`git diff` if the directory is already a repository.

## Test on your real export

Indexing is read-only with respect to the archive. Replace the filename below with the actual
export path:

```bash
promptquarry build ~/Downloads/chatgpt-export.zip \
  --db quarry.sqlite3 \
  --skip-archive-hash

promptquarry summary quarry.sqlite3
promptquarry review quarry.sqlite3 \
  --languages python,rust,bash \
  --limit 100 > top-candidates.json
```

The generated database and review files are ignored by Git. Do not add them to the public
repository.

## Publish

```bash
git init
git add .
git commit -m "Initial release: recover code from large conversation archives"
git branch -M main
gh repo create promptquarry --public --source=. --remote=origin --push
```

Recommended topics:

```text
python cli sqlite chatgpt data-export code-recovery digital-forensics
```

## Optional tagged release

```bash
git tag -a v0.1.0 -m "PromptQuarry v0.1.0"
git push origin v0.1.0
gh release create v0.1.0 --generate-notes
```
