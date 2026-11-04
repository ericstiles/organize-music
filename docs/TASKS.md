# Task Roadmap

> **Plan**: [PLAN.md](PLAN.md) · **Spec**: [SPECS.md](SPECS.md)
> **Workflow**: Explore → Plan → Test → Implement → Verify
> **Live tracking is in beads** (`bd ready`, `bd list`). This file is the
> phase-level overview only. Each line maps to a beads issue.

## Progress Overview
- [x] Explore: library survey ([LIBRARY_SURVEY.md](LIBRARY_SURVEY.md))
- [x] Plan: [PLAN.md](PLAN.md), [SPECS.md](SPECS.md)
- [x] Phase 0: Tracer bullet (scan + meta, one folder, Mac → Pi → Markdown report)
- [ ] Phase 1: Metadata (full library, field sources, filename/folder fallback)
- [ ] Phase 2: Naming preview (configurable template, no renames)
- [ ] Phase 3: Duplicates report (resumable MD5, report only)
- [ ] Phase 4: Organize into formatted folder structure + journal + undo (first phase that changes files)
- [ ] Phase 5: Address duplicates after organizing (quarantine + undo)
- [x] Pi deployment script (`scripts/deploy_to_pi.sh`)
- [ ] Later: web UI, audio-payload hash, applying renames

## Quality gate (every phase)
- [ ] `ruff check . && ruff format --check . && pytest`
- [ ] Coverage ≥ 80% overall, 100% on pure modules
- [ ] Conventional commit via `/Users/wilder/repo/pre-commit-scripts/scripts/<type>`
