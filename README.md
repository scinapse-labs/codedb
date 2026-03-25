# codedb2

A Zig data engine for agent-driven codebase exploration and modular edits. No SQL — agents, files, and versions are all native primitives.

## Quick Start

```bash
zig build run -- /path/to/your/project
# listening on localhost:7719
```

## Agent Exploration API

An agent can understand the entire codebase through these endpoints:

| Endpoint | What it returns |
|---|---|
| `GET /explore/tree` | Full file tree with language, line counts, symbol counts |
| `GET /explore/outline?path=src/main.zig` | Symbols in a file: functions, structs, imports, with line numbers |
| `GET /explore/symbol?name=Store` | Find where a symbol is defined across the codebase |
| `GET /explore/hot` | Top 10 most recently modified files |
| `GET /explore/deps?path=store.zig` | Which files import this file (reverse dependency graph) |

### Example: agent explores a new codebase

```bash
# 1. Register as an agent
curl -X POST localhost:7719/agent/register
# → {"id": 2}

# 2. Get the file tree
curl localhost:7719/explore/tree
# → src/main.zig      (zig, 55L, 4 symbols)
#   src/store.zig     (zig, 156L, 12 symbols)
#   src/agent.zig     (zig, 135L, 8 symbols)
#   ...

# 3. Drill into a file
curl "localhost:7719/explore/outline?path=src/store.zig"
# → src/store.zig (zig, 156 lines)
#     L20: struct_def Store
#     L30: function init
#     L55: function recordSnapshot
#     L62: function recordEdit
#     ...

# 4. Find a symbol
curl "localhost:7719/explore/symbol?name=AgentRegistry"
# → {"path":"src/agent.zig","line":30,"kind":"struct_def"}

# 5. See what's hot
curl localhost:7719/explore/hot
# → src/server.zig
#   src/explore.zig
#   ...

# 6. Check dependencies
curl "localhost:7719/explore/deps?path=store.zig"
# → imported_by:
#     src/main.zig
#     src/edit.zig
#     src/watcher.zig
```


## Data Storage & Privacy

codedb2 is **fully local** — no telemetry, no analytics, no network calls. Nothing leaves your machine.

### What gets stored

| Location | Contents | Purpose |
|----------|----------|---------|
| `~/.codedb/projects/<hash>/` | Trigram index, frequency table, data log | Persistent index cache (faster restarts) |
| `~/.codedb/projects/<hash>/project.txt` | Absolute path to your project root | Maps hash back to project |
| `~/.codedb/projects/<hash>/data.log` | File paths, sizes, content hashes | Version tracking (append-only) |
| `./codedb.snapshot` (in project root) | File tree, outlines, content, frequency table | Portable snapshot for instant MCP startup |

### What is NOT stored

- **No source code** is sent anywhere — all indexing is local
- **No network requests** — codedb2 never phones home
- **No usage analytics or crash reports**
- **Sensitive files are auto-excluded** from snapshots: `.env*`, `credentials.json`, `secrets.*`, `.pem`, `.key`, SSH keys, AWS configs, and more (see `isSensitivePath` in `src/snapshot.zig`)

### Clearing your data

```bash
# Remove all cached indexes for all projects
rm -rf ~/.codedb/

# Remove snapshot from current project
rm -f codedb.snapshot

# Remove cache for a specific project (find the hash first)
ls ~/.codedb/projects/
cat ~/.codedb/projects/<hash>/project.txt  # shows which project
rm -rf ~/.codedb/projects/<hash>/
```

## Architecture

```
Agents ──HTTP──▶ Server ──▶ Explorer (symbols, deps, tree)
                    │
                    ▼
                  Store (version chains, append-only log)
                    ▲
                    │
               FS Watcher (mtime diff, ghost agent)
                    │
                    ▼
               File System
```

**No SQLite.** The data model is purpose-built:
- **Agents** = first-class structs with cursors, heartbeats, locks
- **Files** = immutable version chains (every edit = new version)
- **Explorer** = structural index (symbols, imports, dep graph) rebuilt on change
