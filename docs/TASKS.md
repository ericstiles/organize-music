# Task Roadmap & Execution Checklist

> **Feature / Milestone**: `[e.g., Audio Metadata Extraction Engine]`  
> **Target Spec**: [`docs/SPECS.md`](file:///Users/wilder/repo/organize_music/docs/SPECS.md)  
> **Workflow**: **Explore → Plan → Test → Implement → Verify**

---

## Progress Overview
- [ ] Phase 1: Explore & Design
- [ ] Phase 2: Test Harness & Fixtures
- [ ] Phase 3: Core Implementation (Pure Logic)
- [ ] Phase 4: Integration & CLI Interface
- [ ] Phase 5: Verification & Documentation Gate

---

### Phase 1: Explore & Design
*Goal: Understand constraints, sample data, and edge cases before writing code.*
- [ ] Inspect sample audio files / directory layouts on target SSD.
- [ ] Document tag formats (ID3v2.3/2.4, Vorbis comments, MP4 tags).
- [ ] Finalize data structures and function contracts in [`docs/SPECS.md`](file:///Users/wilder/repo/organize_music/docs/SPECS.md).

### Phase 2: Test Harness & Fixtures
*Goal: Write deterministic, failing unit tests before implementing features (TDD).*
- [ ] Create synthetic test fixtures / minimal mock audio files in `tests/fixtures/`.
- [ ] Write unit tests for successful metadata extraction (`tests/test_metadata.py`).
- [ ] Write unit tests for fallback extraction (filename parsing).
- [ ] Write unit tests for corrupt/missing tag handling.
- [ ] Confirm tests fail predictably (`pytest`).

### Phase 3: Core Implementation (Pure Logic)
*Goal: Implement business logic to turn tests green without side effects.*
- [ ] Implement data models (`src/organize_music/models.py`).
- [ ] Implement pure metadata extraction functions (`src/organize_music/metadata.py`).
- [ ] Keep file under 200 lines; strictly type all arguments and return values.
- [ ] Run `pytest` to confirm all unit tests pass.

### Phase 4: Integration & CLI Interface
*Goal: Wire pure logic to filesystem operations with safe guardrails.*
- [ ] Implement CLI argument parser with mandatory `--dry-run` default (`scripts/scan_library.py`).
- [ ] Add safe reporting / logging for warnings and unparseable tracks.
- [ ] Test CLI behavior with mock directory tree.

### Phase 5: Verification & Quality Gate
*Goal: Ensure clean, deterministic state before pushing or committing.*
- [ ] Run linter: `ruff check .`
- [ ] Run formatter check: `ruff format --check .`
- [ ] Run test suite: `pytest -v`
- [ ] Ensure conventional commit message format (`feat: ...`, `fix: ...`).
