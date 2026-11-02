# CLAUDE.md - AI Development Orientation Guide

## Project Overview
`organize_music`: CLI tools and automation scripts for organizing a music library (metadata extraction, audio file de-duplication, and directory restructuring). Companion tools for music stored on the Raspberry Pi 5 SSD.

## Tech Stack & Tooling
- **Language**: Python >= 3.12 (standard library + targeted audio libraries like `mutagen`)
- **Virtual Environment**: `.venv` in repository root
- **Test Runner**: `pytest` (strict markers, fast deterministic unit tests)
- **Linter & Formatter**: `ruff` (line-length: 100, pycodestyle, pyflakes, isort, bugbear)
- **Git Conventions**: Conventional Commits only (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`)

## Essential Commands
```bash
# Setup & Environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

# Verification & Testing
pytest                        # Run all unit tests
pytest -v -k "test_smoke"     # Run focused test
ruff check .                  # Lint codebase
ruff format --check .         # Check formatting
ruff format .                 # Auto-format files

# Full Quality Gate (Run before committing)
ruff check . && ruff format --check . && pytest
```

## Directory Architecture
```
organize_music/
├── .venv/                  # Local isolated Python environment (gitignored)
├── docs/                   # Specifications, tasks, and documentation (UPPERCASE_WITH_UNDERSCORES.md)
│   ├── SPECS.md            # Feature requirements & behavioral contracts
│   └── TASKS.md            # Granular, checkable development tasks
├── scripts/                # Standalone shell scripts & executable entry points
├── src/organize_music/     # Core modular Python package
│   ├── config.py           # Paths, constants, and environment defaults
│   ├── dedup.py            # Audio duplicate detection & comparison logic
│   ├── metadata.py         # Tag reading, normalization, and validation
│   └── organizer.py        # Safe filesystem operations & directory reorganizer
├── tests/                  # Deterministic unit and integration tests
│   ├── test_dedup.py
│   ├── test_metadata.py
│   ├── test_organizer.py
│   └── test_smoke.py
├── pyproject.toml          # Project config, pytest settings, ruff rules
└── README.md               # High-level repo summary
```

## Coding Guardrails & Standards
1. **Modularity & File Size**: Max 200 lines per file. Single responsibility per module.
2. **Type Annotations**: Mandatory explicit type hints on all function signatures and return types.
3. **Safety First**: Any filesystem mutation (move, delete, rename) **must** support a `--dry-run` mode and fail-fast validation before execution.
4. **Pure Logic Separation**: Separate pure business logic (tag parsing, duplicate matching) from side effects (disk I/O, network).
5. **Naming Conventions**:
   - Python files: `snake_case.py`
   - Shell scripts: `scripts/snake_case.sh` (or `kebab-case.sh`)
   - Markdown docs: `UPPERCASE_WITH_UNDERSCORES.md`
6. **No Phantom Code**: No placeholder functions, dead imports, or untested branches.
