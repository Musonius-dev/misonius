# ARCH-001: Fixed Window Counter via SQLite

**Category:** architecture
**Epic:** epic-aed9e3f1
**Status:** Active

## Rationale

Utilizing the existing SQLite infrastructure avoids adding complex external dependencies like Redis while providing the necessary persistence for a public API.

## Files Affected

- `musonius/memory/store.py`
- `musonius/orchestration/rate_limiter.py`

## History

- Created during planning of epic-aed9e3f1
