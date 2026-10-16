# 0004: Keep the .max test corpus local, never committed

- Status: Accepted
- Date: 2026-10-16

## Context

The first draft of ROADMAP §6 planned a committed corpus of redistributable `.max` files with a licence per
case. The maintainer prefers not to commit `.max` files at all: most useful test scenes come from real
projects and can't be redistributed, and binary scenes bloat the repository.

## Decision

- `.max` files and their reference exports live in `tests/corpus/local/`, which is gitignored, or in any
  directory named by `MX_CORPUS_DIR`.
- Every `*.max` file below the corpus root is a case. Reference exports are found next to it by name, and an
  optional `manifest.toml` adds metadata (expected status, Max version, renderer, features).
- `tests/corpus/corpus.py` discovers cases; corpus-based tests skip when there are none.
- The licence field and the "only redistributable files" rule are dropped, since nothing is redistributed.

## Consequences

- No Git LFS needed, and no licence bookkeeping.
- CI can't run corpus tests unless a corpus is provided to it some other way (e.g. a private cache or artifact).
  Unit tests use small synthetic fixtures built in code.
- Results on real files aren't reproducible by contributors who don't have the same files, so bug reports should
  include `maxdump` output.
