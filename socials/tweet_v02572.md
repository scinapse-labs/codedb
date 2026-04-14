# codedb v0.2.572 launch tweets

Best times to post (PST): Tue-Thu, 8-10 AM
Best times to post (SGT): Tue-Thu, 11 PM - 1 AM

---

Tweet 1 (Hook)

codedb v0.2.572 just dropped.

220µs search on 6,315 files. 2.3x faster than fff-mcp. 6x better recall. 2,272x faster than ripgrep.

12 SIMD optimizations. Zero std.json. Single-threaded Zig beating Rust + rayon.

---

Tweet 2 (v0.2.56 → v0.2.572)

v0.2.572 vs v0.2.56:

10x faster cold indexing: 3.6s → 346ms.
83% less cold RSS: 3.5GB → 580MB.
92% less warm RSS: 1.9GB → 150MB.
220µs search vs cold disk scans.
---

Tweet 3 (Recall)

fff-mcp uses word-boundary grep. Searches "manager", misses "DatabaseManager".

codedb uses a trigram index. Finds substrings. 6x more files returned.

Same latency tier. Way more results.

---

Tweet 4 (SIMD engine)

12 search engine changes in v0.2.572:

16-byte @Vector memmem scanner. SIMD newline detection. Tiered search — trigram → sparse → word → full scan. Lazy sparse: skip covering-set hash when trigrams hit. Size-sorted candidates. Per-file result cap. Deferred searched HashMap.

O(1) everywhere it matters.

---

Tweet 5 (MCP layer)

MCP layer improvements:

Zero std.json — scanner-based extraction for all request types. Arena allocator + reusable buffers. Single stdout write per response. Buffered stdin reads.

Every round-trip down.

---

Tweet 6 (vs the competition)

Real benchmarks on openclaw (6,315 files), query "fn":

codedb:  220µs  — 12 files (22% recall)
fff-mcp: 510µs  — 2 files (4% recall)
ripgrep: ~500ms — ~48,000 lines
grep:    ~1,500ms — ~48,200 lines

2.3x faster than fff-mcp. 6x better recall. 2,272x faster than ripgrep.

---

Tweet 7 (Contributors)

18 issues closed. 10 contributors.

@JF10R @ocordeiro @destroyer22719 @wilsonsilva @killop @sims1253 @JustFly1984 @mochadwi @Mavis2103

Thank you.

---

Tweet 8 (CTA)

Update:

codedb update

Fresh install:
curl -fsSL https://codedb.codegraff.com/install.sh | bash

macOS: signed + notarized. Linux: x86_64.

---

Single tweet version

codedb v0.2.572: 220µs search. 2.3x faster than fff-mcp (Rust+rayon). 6x better recall. 2,272x faster than ripgrep.

12 SIMD optimizations. Zero std.json. Pure Zig.

codedb update

---

Thread starter

codedb v0.2.572.

220µs. 6,315 files. Query "fn".
2.3x faster than fff-mcp.
6x better recall than fff-mcp.
2,272x faster than ripgrep.

Thread ↓

---

Hashtags

#codedb #zig #ai #mcp #codeintelligence #devtools #performance

---

Link

https://github.com/justrach/codedb/releases/tag/v0.2.572
