#!/usr/bin/env python3
"""codedb (MCP) vs ast-grep vs ripgrep benchmark suite."""
import subprocess, json, time, sys, os, select

CODEDB = "./zig-out/bin/codedb"
REPOS = [
    ("/Users/rachpradhan/codedb2", "codedb2", "20 files, 12.6k lines"),
    ("/Users/rachpradhan/merjs", "merjs", "100 files, 17.3k lines"),
    ("/Users/rachpradhan/turboAPI", "turboAPI", "160 files, 41.2k lines"),
]
ITERS = 20

W, G, C, D, Y, N = '\033[1;37m', '\033[0;32m', '\033[0;36m', '\033[0;90m', '\033[0;33m', '\033[0m'

class McpClient:
    def __init__(self, repo):
        self.proc = subprocess.Popen(
            [CODEDB, "mcp", repo],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            bufsize=0,
        )
        self.id = 0
        self.buf = b""
        self._init()

    def _send(self, obj):
        body = json.dumps(obj)
        # Try Content-Length framing first (standard MCP)
        msg = f"Content-Length: {len(body)}\r\n\r\n{body}"
        self.proc.stdin.write(msg.encode())
        self.proc.stdin.flush()

    def _recv(self, timeout=10):
        """Read a complete JSON object from stdout, handling both raw JSON and Content-Length framing."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if select.select([self.proc.stdout], [], [], 0.05)[0]:
                chunk = os.read(self.proc.stdout.fileno(), 65536)
                if chunk:
                    self.buf += chunk
            # Try to parse a complete JSON object from buffer
            text = self.buf.decode(errors="replace")
            # Skip any Content-Length headers
            while text.startswith("Content-Length:"):
                nl = text.find("\r\n\r\n")
                if nl == -1:
                    break
                text = text[nl+4:]
                self.buf = text.encode()
            # Find JSON object boundaries
            start = text.find("{")
            if start == -1:
                continue
            depth = 0
            in_str = False
            esc = False
            for i in range(start, len(text)):
                c = text[i]
                if esc:
                    esc = False
                    continue
                if c == "\\":
                    esc = True
                    continue
                if c == '"':
                    in_str = not in_str
                    continue
                if in_str:
                    continue
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        obj_text = text[start:i+1]
                        self.buf = text[i+1:].encode()
                        try:
                            return json.loads(obj_text)
                        except json.JSONDecodeError:
                            continue
        return None

    def _init(self):
        self._send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                                "clientInfo": {"name": "bench", "version": "1.0"}}})
        resp = self._recv()
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        time.sleep(0.5)  # let indexing finish

    def call(self, tool, args):
        self.id += 1
        self._send({"jsonrpc": "2.0", "id": self.id, "method": "tools/call",
                     "params": {"name": tool, "arguments": args}})
        return self._recv()

    def close(self):
        self.proc.terminate()
        self.proc.wait()


def time_mcp(client, tool, args, iters=ITERS):
    client.call(tool, args)  # warmup
    start = time.perf_counter()
    for _ in range(iters):
        client.call(tool, args)
    return (time.perf_counter() - start) / iters * 1000


def time_cmd(args):
    subprocess.run(args, capture_output=True)  # warmup
    start = time.perf_counter()
    for _ in range(3):
        subprocess.run(args, capture_output=True)
    return (time.perf_counter() - start) / 3 * 1000


def token_estimate(text):
    """Rough token count: ~4 chars per token for code."""
    return len(text) // 4


cpu = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True).stdout.strip()
ram = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout.strip()) // (1024**3)

print(f"\n{W}{'═'*65}{N}")
print(f"{W}  codedb (MCP) vs ast-grep vs ripgrep — benchmark suite{N}")
print(f"{W}{'═'*65}{N}")
print(f"{D}  Machine: {cpu}{N}")
print(f"{D}  RAM:     {ram}GB{N}")
print(f"{D}  Date:    {time.strftime('%Y-%m-%d %H:%M')}{N}")
print(f"{D}  Mode:    MCP server (pre-indexed, warm, {ITERS} iterations avg){N}")
print(flush=True)

all_results = []

for repo, name, desc in REPOS:
    print(f"{W}━━━ {name} ({desc}) ━━━{N}")
    print(flush=True)

    src_dir = os.path.join(repo, "src")
    first_zig = ""
    for f in sorted(os.listdir(src_dir)):
        if f.endswith(".zig"):
            first_zig = f"src/{f}"
            break

    client = McpClient(repo)
    results = {}

    # ── 1. Tree ──
    print(f"{C}  1. File Tree{N}")
    ms = time_mcp(client, "codedb_tree", {})
    results["tree"] = ms
    print(f"     {G}codedb{N}    {W}{ms:.2f} ms{N}  (MCP, pre-indexed)")
    ms2 = time_cmd(["ast-grep", "scan", "--rule", "{ id: b, language: zig, rule: { kind: source_file } }", src_dir])
    print(f"     {Y}ast-grep{N}  {W}{ms2:.1f} ms{N}  (cold, re-parses every call)")
    print(flush=True)

    # ── 2. Symbol Search ──
    print(f"{C}  2. Symbol Search (find 'init'){N}")
    ms = time_mcp(client, "codedb_symbol", {"name": "init"})
    results["symbol"] = ms
    print(f"     {G}codedb{N}    {W}{ms:.2f} ms{N}  (MCP, hash lookup)")
    ms2 = time_cmd(["ast-grep", "scan", "--pattern", "fn init($$$)", src_dir])
    print(f"     {Y}ast-grep{N}  {W}{ms2:.1f} ms{N}  (tree-sitter parse + match)")
    ms3 = time_cmd(["rg", "-n", "fn init", src_dir])
    print(f"     {D}ripgrep{N}   {W}{ms3:.1f} ms{N}  (regex)")
    print(flush=True)

    # ── 3. Full-Text Search ──
    print(f"{C}  3. Full-Text Search ('allocator'){N}")
    ms = time_mcp(client, "codedb_search", {"query": "allocator"})
    results["search"] = ms
    print(f"     {G}codedb{N}    {W}{ms:.2f} ms{N}  (MCP, trigram index)")
    ms3 = time_cmd(["rg", "-c", "allocator", src_dir])
    print(f"     {D}ripgrep{N}   {W}{ms3:.1f} ms{N}  (brute force)")
    ms2 = time_cmd(["ast-grep", "scan", "--pattern", "allocator", src_dir])
    print(f"     {Y}ast-grep{N}  {W}{ms2:.1f} ms{N}  (tree-sitter parse + match)")
    print(flush=True)

    # ── 4. Word Index ──
    print(f"{C}  4. Word Index Lookup ('self'){N}")
    ms = time_mcp(client, "codedb_word", {"word": "self"})
    results["word"] = ms
    print(f"     {G}codedb{N}    {W}{ms:.2f} ms{N}  (MCP, O(1) inverted index)")
    ms3 = time_cmd(["rg", "-wc", "self", src_dir])
    print(f"     {D}ripgrep{N}   {W}{ms3:.1f} ms{N}  (regex word boundary)")
    print(f"     {Y}ast-grep{N}  {D}n/a (no word index){N}")
    print(flush=True)

    # ── 5. Outline ──
    print(f"{C}  5. Structural Outline ({os.path.basename(first_zig)}){N}")
    ms = time_mcp(client, "codedb_outline", {"path": first_zig})
    results["outline"] = ms
    print(f"     {G}codedb{N}    {W}{ms:.2f} ms{N}  (MCP, cached parse)")
    ms2 = time_cmd(["ast-grep", "scan", "--rule", "{ id: b, language: zig, rule: { kind: function_declaration } }",
                     os.path.join(repo, first_zig)])
    print(f"     {Y}ast-grep{N}  {W}{ms2:.1f} ms{N}  (tree-sitter cold parse)")
    ms4 = time_cmd(["ctags", "-f", "/dev/null", "--languages=all", os.path.join(repo, first_zig)])
    print(f"     {D}ctags{N}     {W}{ms4:.1f} ms{N}  (regex)")
    print(flush=True)

    # ── 6. Deps ──
    print(f"{C}  6. Dependency Graph{N}")
    ms = time_mcp(client, "codedb_deps", {"path": first_zig})
    results["deps"] = ms
    print(f"     {G}codedb{N}    {W}{ms:.2f} ms{N}  (MCP, pre-computed reverse graph)")
    print(f"     {Y}ast-grep{N}  {D}n/a (no dependency tracking){N}")
    print(f"     {D}ripgrep{N}   {D}n/a (no dependency tracking){N}")
    print(flush=True)

    # ── 7. Token Efficiency ──
    print(f"{C}  7. Token Efficiency (search 'allocator'){N}")
    resp = client.call("codedb_search", {"query": "allocator"})
    codedb_out = json.dumps(resp) if resp else ""
    codedb_tokens = token_estimate(codedb_out)
    rg_out = subprocess.run(["rg", "allocator", src_dir], capture_output=True, text=True).stdout
    rg_tokens = token_estimate(rg_out)
    ratio = rg_tokens / codedb_tokens if codedb_tokens > 0 else 0
    print(f"     {G}codedb{N}    ~{codedb_tokens:,} tokens  (structured JSON, relevant matches)")
    print(f"     {D}ripgrep{N}   ~{rg_tokens:,} tokens  (raw line output)")
    if ratio > 1:
        print(f"     {W}→ codedb uses {ratio:.1f}x fewer tokens{N}")
    print(flush=True)

    # ── 8. Status ──
    print(f"{C}  8. Status{N}")
    ms = time_mcp(client, "codedb_status", {})
    results["status"] = ms
    print(f"     {G}codedb{N}    {W}{ms:.2f} ms{N}  (MCP)")
    print(flush=True)

    all_results.append((name, results))
    client.close()

# Summary table
print(f"{W}{'═'*65}{N}")
print(f"{W}  Summary — codedb MCP query latency (ms, avg of {ITERS} calls){N}")
print(f"{W}{'═'*65}{N}")
print()
hdr = f"  {'Query':<20} "
for name, _ in all_results:
    hdr += f" {name:>12}"
print(hdr)
sep = f"  {'─'*20} "
for _ in all_results:
    sep += f" {'─'*12}"
print(sep)
for key in ["tree", "symbol", "search", "word", "outline", "deps", "status"]:
    label = f"codedb_{key}"
    line = f"  {label:<20} "
    for _, results in all_results:
        line += f" {results[key]:>10.2f}ms"
    print(line)
print()

print(f"{W}{'═'*65}{N}")
print(f"{W}  Feature Matrix{N}")
print(f"{W}{'═'*65}{N}")
print()
print(f"  {'Feature':<28}  {G}codedb{N}  {Y}ast-grep{N}  {D}ripgrep{N}  {D}ctags{N}")
print(f"  {'─'*28}  ──────  ────────  ───────  ─────")
features = [
    ("Structural parsing",     "✓", "✓", "✗", "✓"),
    ("Trigram search index",   "✓", "✗", "✗", "✗"),
    ("Inverted word index",    "✓", "✗", "✗", "✗"),
    ("Dependency graph",       "✓", "✗", "✗", "✗"),
    ("Version tracking",       "✓", "✗", "✗", "✗"),
    ("Multi-agent locking",    "✓", "✗", "✗", "✗"),
    ("MCP server (AI agents)", "✓", "✗", "✗", "✗"),
    ("HTTP API + SSE events",  "✓", "✗", "✗", "✗"),
    ("File watcher",           "✓", "✗", "✗", "✗"),
    ("Portable snapshot",      "✓", "✗", "✗", "✗"),
    ("Full-text search",       "✓", "✓", "✓", "✗"),
    ("Atomic file edits",      "✓", "✓", "✗", "✗"),
]
for feat, *vals in features:
    colors = [G, Y, D, D]
    line = f"  {feat:<28} "
    for v, c in zip(vals, colors):
        line += f" {c}  {v}   {N} "
    print(line)
print(f"\n  {D}codedb = tree-sitter + search index + dep graph + agent runtime{N}")
print(f"  {D}Zero external dependencies. Pure Zig. Single binary.{N}\n")
