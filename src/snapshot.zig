// snapshot.zig — Portable `.codedb` artifact writer/reader
//
// Produces a single binary file containing the full indexed state of a repo.
// Any agent can read this file to understand the codebase without re-indexing.
//
// Format (all integers little-endian):
//   Header (52 bytes):
//     magic:         "CDB\x01"  (4 bytes)
//     version:       u16
//     flags:         u16         (reserved)
//     git_head:      [40]u8      (hex SHA or zeroes)
//     section_count: u32
//   Section Table (section_count × 20 bytes):
//     id:     u32    (section type)
//     offset: u64    (byte offset from file start)
//     length: u64    (byte length)
//   Sections:
//     TREE    (1): JSON array of {path, language, line_count, byte_size, symbol_count}
//     OUTLINE (2): JSON object mapping path → [{name, kind, line, detail}]
//     CONTENT (3): for each file: path_len(u16) + path + content_len(u32) + content
//     FREQ    (5): 256×256×u16 LE frequency table
//     META    (6): JSON {file_count, total_bytes, indexed_at, format_version}

const std = @import("std");
const Explorer = @import("explore.zig").Explorer;
const git_mod = @import("git.zig");

const MAGIC = [4]u8{ 'C', 'D', 'B', 0x01 };
const FORMAT_VERSION: u16 = 1;

pub const SectionId = enum(u32) {
    tree = 1,
    outline = 2,
    content = 3,
    freq_table = 5,
    meta = 6,
};

const SectionEntry = struct {
    id: u32,
    offset: u64,
    length: u64,
};

/// Write a portable `.codedb` snapshot file.
pub fn writeSnapshot(
    explorer: *Explorer,
    root_path: []const u8,
    output_path: []const u8,
    allocator: std.mem.Allocator,
) !void {
    const tmp_path = try std.fmt.allocPrint(allocator, "{s}.tmp", .{output_path});
    defer allocator.free(tmp_path);

    var file = try std.fs.cwd().createFile(tmp_path, .{});

    var sections: std.ArrayList(SectionEntry) = .{};
    defer sections.deinit(allocator);

    // Reserve space for header + section table (rewritten at end)
    // Header: 52 bytes.  Section table: up to 5 sections × 20 = 100.
    // Round to 256 for alignment.
    const header_reserve: u64 = 256;
    try file.seekTo(header_reserve);

    explorer.mu.lockShared();
    defer explorer.mu.unlockShared();

    // ── Section: META ──
    {
        const offset = try file.getPos();
        var buf: std.ArrayList(u8) = .{};
        defer buf.deinit(allocator);
        const writer = buf.writer(allocator);
        var total_bytes: u64 = 0;
        var ct_iter = explorer.contents.valueIterator();
        while (ct_iter.next()) |v| total_bytes += v.*.len;

        try writer.print(
            \\{{"file_count":{d},"total_bytes":{d},"indexed_at":{d},"format_version":{d}}}
        , .{
            explorer.outlines.count(),
            total_bytes,
            std.time.timestamp(),
            FORMAT_VERSION,
        });
        try file.writeAll(buf.items);
        try sections.append(allocator, .{ .id = @intFromEnum(SectionId.meta), .offset = offset, .length = buf.items.len });
    }

    // ── Section: TREE ──
    {
        const offset = try file.getPos();
        var buf: std.ArrayList(u8) = .{};
        defer buf.deinit(allocator);
        const writer = buf.writer(allocator);
        try writer.writeByte('[');
        var first = true;
        var iter = explorer.outlines.iterator();
        while (iter.next()) |entry| {
            if (!first) try writer.writeByte(',');
            first = false;
            const outline = entry.value_ptr;
            try writer.print(
                \\{{"path":"{s}","language":"{s}","line_count":{d},"byte_size":{d},"symbol_count":{d}}}
            , .{
                entry.key_ptr.*,
                @tagName(outline.language),
                outline.line_count,
                outline.byte_size,
                outline.symbols.items.len,
            });
        }
        try writer.writeByte(']');
        try file.writeAll(buf.items);
        try sections.append(allocator, .{ .id = @intFromEnum(SectionId.tree), .offset = offset, .length = buf.items.len });
    }

    // ── Section: OUTLINE ──
    {
        const offset = try file.getPos();
        var buf: std.ArrayList(u8) = .{};
        defer buf.deinit(allocator);
        const writer = buf.writer(allocator);
        try writer.writeByte('{');
        var first = true;
        var iter = explorer.outlines.iterator();
        while (iter.next()) |entry| {
            if (!first) try writer.writeByte(',');
            first = false;
            try writer.print("\"{s}\":[", .{entry.key_ptr.*});
            for (entry.value_ptr.symbols.items, 0..) |sym, si| {
                if (si > 0) try writer.writeByte(',');
                try writer.print(
                    \\{{"name":"{s}","kind":"{s}","line":{d}
                , .{ sym.name, @tagName(sym.kind), sym.line_start });
                if (sym.detail) |d| {
                    try writer.print(",\"detail\":\"{s}\"", .{d});
                }
                try writer.writeByte('}');
            }
            try writer.writeByte(']');
        }
        try writer.writeByte('}');
        try file.writeAll(buf.items);
        try sections.append(allocator, .{ .id = @intFromEnum(SectionId.outline), .offset = offset, .length = buf.items.len });
    }

    // ── Section: CONTENT ──
    {
        const offset = try file.getPos();
        var ct_iter = explorer.contents.iterator();
        while (ct_iter.next()) |entry| {
            const path = entry.key_ptr.*;
            const content = entry.value_ptr.*;
            var pl_buf: [2]u8 = undefined;
            std.mem.writeInt(u16, &pl_buf, @intCast(path.len), .little);
            try file.writeAll(&pl_buf);
            try file.writeAll(path);
            var cl_buf: [4]u8 = undefined;
            std.mem.writeInt(u32, &cl_buf, @intCast(content.len), .little);
            try file.writeAll(&cl_buf);
            try file.writeAll(content);
        }
        const end = try file.getPos();
        try sections.append(allocator, .{ .id = @intFromEnum(SectionId.content), .offset = offset, .length = end - offset });
    }

    // ── Section: FREQ TABLE ──
    {
        const offset = try file.getPos();
        const index_mod = @import("index.zig");
        const table = index_mod.active_pair_freq;
        var row_buf: [256 * 2]u8 = undefined;
        for (table) |row| {
            for (row, 0..) |val, j| {
                std.mem.writeInt(u16, row_buf[j * 2 ..][0..2], val, .little);
            }
            try file.writeAll(&row_buf);
        }
        const end = try file.getPos();
        try sections.append(allocator, .{ .id = @intFromEnum(SectionId.freq_table), .offset = offset, .length = end - offset });
    }

    // ── Write header + section table at file start ──
    try file.seekTo(0);

    try file.writeAll(&MAGIC);
    var ver_buf: [2]u8 = undefined;
    std.mem.writeInt(u16, &ver_buf, FORMAT_VERSION, .little);
    try file.writeAll(&ver_buf);
    try file.writeAll(&[2]u8{ 0, 0 }); // flags

    const git_head = git_mod.getGitHead(root_path, allocator) catch null;
    if (git_head) |head| {
        try file.writeAll(&head);
    } else {
        try file.writeAll(&([_]u8{0} ** 40));
    }

    var sc_buf: [4]u8 = undefined;
    std.mem.writeInt(u32, &sc_buf, @intCast(sections.items.len), .little);
    try file.writeAll(&sc_buf);

    for (sections.items) |sec| {
        var id_buf: [4]u8 = undefined;
        std.mem.writeInt(u32, &id_buf, sec.id, .little);
        try file.writeAll(&id_buf);
        var off_buf: [8]u8 = undefined;
        std.mem.writeInt(u64, &off_buf, sec.offset, .little);
        try file.writeAll(&off_buf);
        var len_buf: [8]u8 = undefined;
        std.mem.writeInt(u64, &len_buf, sec.length, .little);
        try file.writeAll(&len_buf);
    }

    file.close();
    file = undefined;
    std.fs.cwd().rename(tmp_path, output_path) catch |err| {
        // If rename fails (e.g. output_path is a directory), clean up tmp
        std.fs.cwd().deleteFile(tmp_path) catch {};
        return err;
    };
}

/// Read section table from a `.codedb` file.
pub fn readSections(path: []const u8, allocator: std.mem.Allocator) !?std.AutoHashMap(u32, SectionEntry) {
    const file = std.fs.cwd().openFile(path, .{}) catch return null;
    defer file.close();

    var magic_buf: [4]u8 = undefined;
    const n = file.readAll(&magic_buf) catch return null;
    if (n != 4 or !std.mem.eql(u8, &magic_buf, &MAGIC)) return null;

    file.seekBy(44) catch return null; // skip version + flags + git_head

    var sc_buf: [4]u8 = undefined;
    if (file.readAll(&sc_buf) catch return null != 4) return null;
    const section_count = std.mem.readInt(u32, &sc_buf, .little);

    var result = std.AutoHashMap(u32, SectionEntry).init(allocator);
    errdefer result.deinit();

    for (0..section_count) |_| {
        var entry_buf: [20]u8 = undefined;
        if (file.readAll(&entry_buf) catch return null != 20) return null;
        try result.put(
            std.mem.readInt(u32, entry_buf[0..4], .little),
            .{
                .id = std.mem.readInt(u32, entry_buf[0..4], .little),
                .offset = std.mem.readInt(u64, entry_buf[4..12], .little),
                .length = std.mem.readInt(u64, entry_buf[12..20], .little),
            },
        );
    }
    return result;
}

/// Read a section's raw bytes from a `.codedb` file.
pub fn readSectionBytes(path: []const u8, section_id: SectionId, allocator: std.mem.Allocator) !?[]u8 {
    var sections = try readSections(path, allocator) orelse return null;
    defer sections.deinit();

    const entry = sections.get(@intFromEnum(section_id)) orelse return null;
    const file = try std.fs.cwd().openFile(path, .{});
    defer file.close();

    try file.seekTo(entry.offset);
    const buf = try allocator.alloc(u8, @intCast(entry.length));
    errdefer allocator.free(buf);
    const n = try file.readAll(buf);
    if (n != buf.len) {
        allocator.free(buf);
        return null;
    }
    return buf;
}
