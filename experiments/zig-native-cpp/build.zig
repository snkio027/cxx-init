const std = @import("std");

// Experimental only: no generator, CMake, host installation, or dependency fetch.
pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    const toml = b.option([]const u8, "toml", "Existing toml++ 3.4.0 checkout") orelse
        @panic("Pass -Dtoml=/absolute/path/to/tomlplusplus");
    const records = b.option([]const u8, "records", "Existing absolute directory for Clang -MJ records");
    const bias = b.option(i32, "bias", "Generated configuration value") orelse 2;
    const sanitizer = b.option([]const u8, "sanitizer", "none, undefined, or address") orelse "none";
    if (!std.mem.eql(u8, sanitizer, "none") and
        !std.mem.eql(u8, sanitizer, "undefined") and
        !std.mem.eql(u8, sanitizer, "address")) @panic("Unknown sanitizer");

    const vendor_mod = b.createModule(.{ .target = target, .optimize = optimize, .link_libcpp = true });
    vendor_mod.addIncludePath(.{ .cwd_relative = b.pathJoin(&.{ toml, "include" }) });
    vendor_mod.addCMacro("TOML_HEADER_ONLY", "0");
    vendor_mod.addCSourceFile(.{ .file = b.path("src/toml.cpp"), .flags = flags(b, records, "toml", sanitizer) });
    const vendor = b.addLibrary(.{ .name = "tomlplusplus", .linkage = .static, .root_module = vendor_mod });
    vendor.installHeadersDirectory(.{ .cwd_relative = b.pathJoin(&.{ toml, "include" }) }, "", .{ .include_extensions = &.{ ".h", ".hpp", ".inl" } });

    const core_mod = b.createModule(.{ .target = target, .optimize = optimize, .link_libcpp = true });
    core_mod.addIncludePath(b.path("include"));
    core_mod.addCMacro("TOML_HEADER_ONLY", "0");
    core_mod.addConfigHeader(b.addConfigHeader(.{ .include_path = "config.hpp" }, .{ .PROBE_BIAS = bias }));
    core_mod.addCSourceFile(.{ .file = b.path("src/core.cpp"), .flags = flags(b, records, "core", sanitizer) });
    core_mod.linkLibrary(vendor);
    const core = b.addLibrary(.{ .name = "core", .linkage = .static, .root_module = core_mod });
    core.installHeadersDirectory(b.path("include"), "", .{ .include_extensions = &.{".hpp"} });

    const app_mod = b.createModule(.{ .target = target, .optimize = optimize, .link_libcpp = true });
    app_mod.addCSourceFile(.{ .file = b.path("src/main.cpp"), .flags = flags(b, records, "main", sanitizer) });
    app_mod.linkLibrary(core);
    const app = b.addExecutable(.{ .name = "zig-cpp-probe", .root_module = app_mod });
    b.installArtifact(app);

    const run = b.addRunArtifact(app);
    run.addPassthruArgs();
    b.step("run", "Build and run the C++ application").dependOn(&run.step);
    const test_run = b.addRunArtifact(app);
    test_run.addArg(b.fmt("{d}", .{40 + bias}));
    test_run.expectExitCode(0);
    test_run.expectStdOutEqual(b.fmt("answer={d}\n", .{40 + bias}));
    b.step("test", "Check actual output and nonzero failure propagation").dependOn(&test_run.step);
}

fn flags(b: *std.Build, records: ?[]const u8, name: []const u8, sanitizer: []const u8) []const []const u8 {
    var result: std.array_list.Managed([]const u8) = .init(b.allocator);
    result.appendSlice(&.{ "-std=c++23", "-Wall", "-Wextra", "-Wpedantic" }) catch @panic("OOM");
    if (records) |dir| result.appendSlice(&.{ "-MJ", b.pathJoin(&.{ dir, b.fmt("{s}.json", .{name}) }) }) catch @panic("OOM");
    if (!std.mem.eql(u8, sanitizer, "none")) result.appendSlice(&.{
        b.fmt("-fsanitize={s}", .{sanitizer}), "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
    }) catch @panic("OOM");
    return result.toOwnedSlice() catch @panic("OOM");
}
