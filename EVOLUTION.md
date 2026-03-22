# Pipeline Evolution

This document tracks every self-improvement the pipeline has made to itself.
Each entry corresponds to one post-mortem run and the proposals that were applied.

To view the full history as git commits:
```
git log --grep="\[self-improve\]" --oneline
git show <commit-hash>
```

To list all proposals (applied and pending):
```
python apply_proposal.py --list
```

---

## v1.3.0 — Comprehensive Agent Prompt Improvements (2026-03-22)

**Trigger:** Manual analysis of agent definitions and snake-game pipeline run data.

### Changes Applied

**01_requirements.md** — Added `verification_type` field (`unit`/`integration`/`visual`/`manual`) to each AC. Added mandatory logic/presentation separation for UI features. Added category distribution guidance.

**02_plan.md** — Added `complexity_estimate` field. Added AC traceability matrix. Explicitly prohibited integration test files in `file_structure`. Added dev dependency separation. Required explicit `__init__.py` listing.

**03_tdd_red.md** — Scoped strictly to unit tests only (`tests/unit/`). Added verification_type filtering (skip `visual`/`manual` ACs). Added traceability headers per test file. Improved assertion quality standards.

**04_tdd_green.md** — Added pre-implementation setup (dev deps, init files). Added incremental implementation strategy based on project size. Added structured debugging workflow. Improved retry strategy with read-before-rewrite guidance.

**05_verification.md** — Added critical output production mandate with `_verification_report.json` file fallback. Added mandatory code reading process (read 3+ source files, 2+ test files). Added confidence scores per AC. Added `pass_with_caveat` status. Added NFR verification. Added token-limit graceful degradation.

**06_integration.md** — Added mandatory existing-test discovery and gap analysis. Added permission to complete with zero new files. Added clear differentiation from unit tests. Added multi-component interaction guidance.

**07_postmortem.md** — Added `severity` classification (blocking/degrading/cosmetic). Added `recurrence_likelihood` field. Added self-validation checklist for proposals. Added token-limit prioritization guidance.

**08_doc_update.md** — Added staleness assessment workflow. Added verification status in requirements checklist (`[x]`/`[ ]`/`[~]`). Added visual/manual AC documentation. Added explicit read-before-write mandate for existing projects.

**pipeline.json** — Upgraded verification step to Opus model (`"model": "postmortem"`). Added `requires_output: true` to verification step. Bumped version to 1.3.0.

### Rationale

Analysis of the snake-game run (2026-03-22T175049) revealed systemic issues:
- Verification step produced empty output (589s wasted, quality gate bypassed)
- TDD Red wrote integration tests because the plan included them in file_structure (integration step then redundant, 199s wasted)
- TDD Green wasted 63 minutes on a failed run due to missing dev dependencies and no incremental strategy
- Requirements mixed untestable visual assertions with testable logic
- No confidence scoring or NFR verification in the verification step

<!-- Entries are appended below by apply_proposal.py -->
