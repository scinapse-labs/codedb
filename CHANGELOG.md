# Changelog

## 0.2.55 - 2026-04-09

`0.2.55` is a performance and reliability release focused on warm reopen, MCP startup behavior, search quality, parser correctness, and installer safety. The headline change is that warm CLI and MCP project loads now reopen persisted state directly instead of spending seconds rebuilding heap indexes.

### Highlights

- Warm snapshot reopen now restores snapshot outline/state directly, reuses persisted trigram sidecars, and avoids redundant `word.index` rewrites. This closes [#220](https://github.com/justrach/codedb/issues/220).
- `codedb_query` adds a composable MCP search pipeline so agents can do multi-step retrieval in one tool call. This closes [#168](https://github.com/justrach/codedb/issues/168).
- Search ranking now learns from query-to-open history through WAL-backed combo boosts. This closes [#195](https://github.com/justrach/codedb/issues/195).
- MCP sessions now record real client identity and expose memory diagnostics in `codedb_status`. This closes [#37](https://github.com/justrach/codedb/issues/37).
- Root policy now refuses to index the home directory itself, preventing the large MCP RAM spike reported in [#174](https://github.com/justrach/codedb/issues/174).

### Performance And Memory

- Persisted warm-reopen state now covers startup-critical outline/state data and trigram sidecars, with lazy word-index rebuild and persistence on demand.
- Repeat snapshots in the same cache location skip redundant `word.index` rewrites instead of paying full rewrite cost every time.
- `mmap_overlay` now supports zero-heap incremental updates on top of mmap-backed indexes, and allocation-pressure fallback avoids false negatives by dropping to the safe full-scan path.
- `releaseContents` now uses `clearAndFree` so content-cache bucket arrays are actually released instead of being retained.
- MCP startup refuses exact home-directory roots, preventing pathological scans of `~` and the resulting multi-gigabyte memory spikes.

#### CLI Benchmarks (`ReleaseFast`, `openclaw`, current `main` vs `v0.2.54`)

| Benchmark | 0.2.55 | 0.2.54 | Delta |
| --- | ---: | ---: | ---: |
| cold `tree` | `5.32s` | `5.29s` | `+0.6%` |
| `snapshot` | `6.53s` | `6.25s` | `+4.6%` |
| warm `tree` | `0.26s` | `6.16s` | `23.7x faster` |
| warm `search workspace` | `0.24s` | `6.14s` | `25.6x faster` |
| warm `word session` | `0.61s` | `5.99s` | `9.9x faster` |

Cold paths stay effectively flat, snapshot creation remains within the benchmark regression threshold, and warm reopen is dramatically faster.

#### MCP First Secondary-Project Call (`ReleaseFast`, `openclaw`)

| Tool | 0.2.55 | 0.2.54 | Delta |
| --- | ---: | ---: | ---: |
| `codedb_tree` | `0.076s` | `5.289s` | `69.6x faster` |
| `codedb_search` | `0.067s` | `5.278s` | `78.8x faster` |
| `codedb_word` | `0.285s` | `5.312s` | `18.6x faster` |

#### Peak RSS On `openclaw`

| Benchmark | 0.2.55 | 0.2.54 |
| --- | ---: | ---: |
| cold `tree` | `3478.8MB` | `3478.1MB` |
| warm `tree` | `192.6MB` | `3314.0MB` |
| warm `search` | `193.3MB` | `3312.9MB` |
| warm `word` | `677.1MB` | `3313.3MB` |

Warm RSS is materially lower because reopen no longer reconstructs the same large heap state on every process start.

#### Small-Corpus Sanity Pass (`codedb/src`)

| Benchmark | 0.2.55 | 0.2.54 |
| --- | ---: | ---: |
| cold `tree` | `0.045s` | `0.040s` |
| warm `tree` | `0.010s` | `0.030s` |
| warm `search` | `0.010s` | `0.030s` |
| warm `word` | `0.010s` | `0.030s` |

### Search, Ranking, And MCP

- Added `codedb_query`, a composable search pipeline for agent-driven retrieval workflows, including chained `find`, `search`, `filter`, `outline`, `read`, and `limit` stages in one call.
- `codedb_find` now retries delimiter-heavy queries more intelligently, truncates overly noisy per-file output, and skips more large generated directories by default.
- Search and file-access activity now writes to a local WAL, enabling combo-boost ranking for files that were historically opened after similar queries.
- WAL profiling now records latency and file-access patterns locally, and hashed telemetry upload preserves aggregation value without sending raw queries or file paths off-machine.
- `codedb_status` now reports client identity and index-memory diagnostics so MCP clients can see which kind of index is active and how much memory it is retaining.

### Installer, Update, And Release Reliability

- `codedb update` now downloads binaries directly from GitHub Releases instead of depending on the old CDN path.
- The install script now downloads release binaries from GitHub Releases as well.
- The `nuke` output now points at the correct install URL.
- Installer shell docs and checksum fallback behavior were tightened so release/install flows fail more predictably.

### Parser And Correctness Fixes

- Fixed five correctness bugs from [#179](https://github.com/justrach/codedb/issues/179), including large-repo mmap cache validation, ANSI escape stripping, block-comment handling, Python docstring detection, and a telemetry write-path race.
- Parsing now correctly resumes after single-line `/* ... */` comments instead of skipping subsequent code on the line.
- Added regression coverage for the `#179` parser fixes so comment/docstring edge cases stay fixed.

### Merged PRs In This Release

- [#222](https://github.com/justrach/codedb/pull/222) `perf: speed up warm snapshot reopen`
- [#204](https://github.com/justrach/codedb/pull/204) `test: regression tests for #179 parser fixes`
- [#203](https://github.com/justrach/codedb/pull/203) `fix: parse code after single-line /* */ comments`
- [#202](https://github.com/justrach/codedb/pull/202) `fix: 5 bugs from issue #179`
- [#201](https://github.com/justrach/codedb/pull/201) `fix: install script downloads from GitHub releases`
- [#200](https://github.com/justrach/codedb/pull/200) `feat: combo-boost ranking from WAL`
- [#199](https://github.com/justrach/codedb/pull/199) `feat: cloud WAL sync — hashed profiling telemetry`
- [#198](https://github.com/justrach/codedb/pull/198) `feat: WAL profiling — latency + file access logging`
- [#194](https://github.com/justrach/codedb/pull/194) `feat: search UX — auto-retry, per-file truncation, query WAL, skip dirs`
- [#192](https://github.com/justrach/codedb/pull/192) `feat: MCP client identity + memory diagnostics`
- [#191](https://github.com/justrach/codedb/pull/191) `fix: mmap_overlay fail-safe on allocation pressure`
- [#190](https://github.com/justrach/codedb/pull/190) `perf: mmap overlay pattern for zero-heap incremental updates`
- [#189](https://github.com/justrach/codedb/pull/189) `fix: releaseContents reclaims HashMap bucket memory`
- [#180](https://github.com/justrach/codedb/pull/180) `feat: composable search pipeline — codedb_query`
- [#178](https://github.com/justrach/codedb/pull/178) `fix: block home directory indexing to prevent 17GB RAM spike`
- [#177](https://github.com/justrach/codedb/pull/177) `fix: correct install URL in nuke output`
- [#176](https://github.com/justrach/codedb/pull/176) `fix: codedb update downloads directly from GitHub releases`

### Issues Closed In This Release Window

- [#220](https://github.com/justrach/codedb/issues/220) `perf: persist startup-critical indexes aggressively for mmap-backed warm reopen`
- [#195](https://github.com/justrach/codedb/issues/195) `feat: combo-boost ranking from query WAL`
- [#174](https://github.com/justrach/codedb/issues/174) `MCP mode: 17GB RAM spike when Claude Code starts in home directory`
- [#168](https://github.com/justrach/codedb/issues/168) `feat: agent-defined search — let agents compose custom search pipelines`
- [#37](https://github.com/justrach/codedb/issues/37) `Add real MCP client identity instead of hardcoding all edits to agent 1`

### Validation Used For This Release

- `SDKROOT=$(xcrun --show-sdk-path) zig build test`
- `SDKROOT=$(xcrun --show-sdk-path) zig build -Doptimize=ReleaseFast`
- `SDKROOT=$(xcrun --show-sdk-path) zig build run -- --version`
