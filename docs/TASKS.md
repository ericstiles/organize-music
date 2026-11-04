# Task Roadmap

> **Plan**: [PLAN.md](PLAN.md) · **Spec**: [SPECS.md](SPECS.md)
> **Workflow**: Explore → Plan → Test → Implement → Verify
> **Live tracking is in beads** (`bd ready`, `bd list`). This file is the
> phase-level overview only. Each line maps to a beads issue.

## Progress Overview
- [x] Explore: library survey ([LIBRARY_SURVEY.md](LIBRARY_SURVEY.md))
- [x] Plan: [PLAN.md](PLAN.md), [SPECS.md](SPECS.md)
- [ ] Phase 0: Tracer bullet (scan + meta, one folder, Mac → Pi → Markdown report)
- [ ] Phase 1: Metadata (full library, field sources, filename/folder fallback)
- [ ] Phase 2: Naming preview (configurable template, no renames)
- [ ] Phase 3: Duplicates (resumable MD5, keeper rules, report)
- [ ] Phase 4: Quarantine + journal + undo (first phase that changes files)
- [ ] Phase 5: Pi deployment script
- [ ] Later: web UI, audio-payload hash, applying renames

## Quality gate (every phase)
- [ ] `ruff check . && ruff format --check . && pytest`
- [ ] Coverage ≥ 80% overall, 100% on pure modules
- [ ] Conventional commit via `/Users/wilder/repo/pre-commit-scripts/scripts/<type>`
