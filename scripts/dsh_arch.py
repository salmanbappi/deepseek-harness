"""Resolve the Android architecture identities the installer and patcher need.

node-pty loads its native library from ``prebuilds/<platform>-<arch>`` where the
two components come from ``process.platform`` and ``process.arch``. Every native
artifact the Termux install places must land under that exact directory name, so
the name is derived here once instead of being written as a literal.

``uname -m`` reports the kernel's view, which is not always Node's. A 64-bit
device running a 32-bit Termux userland reports ``armv8l`` and Node reports
``arm``; native binaries must match Node, because Node is what dlopens them.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from dataclasses import dataclass

# Node's process.arch names. These are the only values that can appear in a
# prebuilds directory that node-pty will ever look in.
_NODE_ARCH_ARM = "arm"
_NODE_ARCH_ARM64 = "arm64"
_NODE_ARCH_X64 = "x64"
_NODE_ARCH_IA32 = "ia32"

# `uname -m` values mapped to Node's naming. armv7l and armv8l are both 32-bit
# userlands: armv8l is an ARMv8 core executing AArch32, and Node reports 'arm'.
_UNAME_TO_NODE_ARCH = {
    "arm64": _NODE_ARCH_ARM64,
    "aarch64": _NODE_ARCH_ARM64,
    "armv8l": _NODE_ARCH_ARM,
    "armv8a": _NODE_ARCH_ARM,
    "armv7l": _NODE_ARCH_ARM,
    "armv7": _NODE_ARCH_ARM,
    "armv6l": _NODE_ARCH_ARM,
    "arm": _NODE_ARCH_ARM,
    "x86_64": _NODE_ARCH_X64,
    "amd64": _NODE_ARCH_X64,
    "x64": _NODE_ARCH_X64,
    "i686": _NODE_ARCH_IA32,
    "i386": _NODE_ARCH_IA32,
    "ia32": _NODE_ARCH_IA32,
}

# Android NDK ABI names, for cross-compiling the native addons.
_NODE_ARCH_TO_NDK_ABI = {
    _NODE_ARCH_ARM64: "arm64-v8a",
    _NODE_ARCH_ARM: "armeabi-v7a",
    _NODE_ARCH_X64: "x86_64",
    _NODE_ARCH_IA32: "x86",
}

# ELF e_machine values that a correct binary for each Node arch carries.
_NODE_ARCH_TO_ELF_MACHINE = {
    _NODE_ARCH_ARM64: 183,  # EM_AARCH64
    _NODE_ARCH_ARM: 40,  # EM_ARM
    _NODE_ARCH_X64: 62,  # EM_X86_64
    _NODE_ARCH_IA32: 3,  # EM_386
}

# ELF EI_CLASS values: 1 is 32-bit, 2 is 64-bit.
_ELF_CLASS_32 = 1
_ELF_CLASS_64 = 2

_NODE_ARCH_TO_ELF_CLASS = {
    _NODE_ARCH_ARM64: _ELF_CLASS_64,
    _NODE_ARCH_ARM: _ELF_CLASS_32,
    _NODE_ARCH_X64: _ELF_CLASS_64,
    _NODE_ARCH_IA32: _ELF_CLASS_32,
}

SUPPORTED_NODE_ARCHES = tuple(sorted(_NODE_ARCH_TO_NDK_ABI))


class UnsupportedArchitectureError(RuntimeError):
    """The requested architecture has no Termux native-artifact mapping."""


@dataclass(frozen=True)
class AndroidTarget:
    """Architecture identities for one build or install target.

    Attributes:
        node_arch: Node's `process.arch` value, e.g. `arm` or `arm64`.
        prebuild_dir: Directory name node-pty and other prebuild-aware addons
            search, `android-<node_arch>`.
        cache_dir_name: Directory under `~/.dsh/native` holding the cached
            native binaries for this architecture.
        ndk_abi: Android NDK ABI name used when cross-compiling.
        elf_machine: Expected ELF `e_machine` value.
        elf_class: Expected ELF `EI_CLASS` value, 1 for 32-bit and 2 for 64-bit.
    """

    node_arch: str
    prebuild_dir: str
    cache_dir_name: str
    ndk_abi: str
    elf_machine: int
    elf_class: int


def _normalize_node_arch(arch: str) -> str:
    """Map a Node arch name or a `uname -m` value to a Node arch name.

    Args:
        arch: A value such as `arm64`, `aarch64`, `armv8l`, or `x64`.

    Returns:
        The canonical Node arch name.

    Raises:
        UnsupportedArchitectureError: The value has no mapping.
    """
    key = arch.strip().lower()
    if key in _NODE_ARCH_TO_NDK_ABI:
        return key
    if key in _UNAME_TO_NODE_ARCH:
        return _UNAME_TO_NODE_ARCH[key]
    raise UnsupportedArchitectureError(
        f"unsupported architecture {arch!r}; supported: {', '.join(SUPPORTED_NODE_ARCHES)}",
    )


def target_for(arch: str) -> AndroidTarget:
    """Build the architecture identity set for one Node arch or `uname -m` value.

    Args:
        arch: A Node arch name or a `uname -m` value.

    Returns:
        The identities native artifacts for that architecture use.
    """
    node_arch = _normalize_node_arch(arch)
    return AndroidTarget(
        node_arch=node_arch,
        prebuild_dir=f"android-{node_arch}",
        cache_dir_name=f"android-{node_arch}",
        ndk_abi=_NODE_ARCH_TO_NDK_ABI[node_arch],
        elf_machine=_NODE_ARCH_TO_ELF_MACHINE[node_arch],
        elf_class=_NODE_ARCH_TO_ELF_CLASS[node_arch],
    )


def running_node_arch() -> str:
    """Return the architecture of the Node running this process.

    The value is read from Node itself rather than from `uname`, because native
    binaries are dlopened by Node and must match Node's own architecture. A
    32-bit Termux userland on 64-bit silicon reports `armv8l` from `uname` but
    `arm` from Node.

    Returns:
        Node's `process.arch` value.

    Raises:
        UnsupportedArchitectureError: Node could not report its arch, or it is
            unsupported.
    """
    try:
        out = subprocess.run(
            ["node", "-p", "process.arch"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        out = ""
    if not out:
        # Fall back to the kernel's report when Node is unavailable, e.g. while
        # bootstrapping before nodejs is installed.
        out = platform.machine()
    return _normalize_node_arch(out)


def running_target() -> AndroidTarget:
    """Return the architecture identities for this device.

    Returns:
        The identities native artifacts for the running Node use.
    """
    return target_for(running_node_arch())


def native_cache_dir(arch: str | None = None, home: str | None = None) -> str:
    """Path of the cached native binaries for one architecture.

    Args:
        arch: Node arch name or `uname -m` value; defaults to the running device.
        home: Home directory override, for tests.

    Returns:
        The absolute cache directory path.
    """
    target = running_target() if arch is None else target_for(arch)
    root = home if home is not None else os.path.expanduser("~")
    return os.path.join(root, ".dsh", "native", target.cache_dir_name)


def elf_identity(header: bytes) -> tuple[int, int]:
    """Read the class and machine of an ELF header.

    Args:
        header: At least the first 20 bytes of an ELF file.

    Returns:
        A `(elf_class, elf_machine)` pair.

    Raises:
        ValueError: The bytes are not a little-endian ELF header.
    """
    if len(header) < 20 or header[:4] != b"\x7fELF":
        raise ValueError("not an ELF file")
    if header[5] != 1:
        raise ValueError("only little-endian ELF is supported")
    elf_class = header[4]
    # e_machine sits at offset 18 as a little-endian u16.
    elf_machine = int.from_bytes(header[18:20], "little")
    return elf_class, elf_machine


def binary_matches(binary_header: bytes, arch: str) -> bool:
    """Whether an ELF header matches the architecture Node would load it as.

    Args:
        binary_header: At least the first 20 bytes of the binary.
        arch: Node arch name or `uname -m` value the binary is expected to be.

    Returns:
        True when class and machine both match.
    """
    expected = target_for(arch)
    try:
        elf_class, elf_machine = elf_identity(binary_header)
    except ValueError:
        return False
    return elf_class == expected.elf_class and elf_machine == expected.elf_machine


def describe(arch: str) -> str:
    """Human-readable one-line summary of a target, for diagnostics.

    Args:
        arch: Node arch name or `uname -m` value.

    Returns:
        A line naming the prebuild directory, cache, and NDK ABI.
    """
    t = target_for(arch)
    return (
        f"node_arch={t.node_arch} prebuild_dir={t.prebuild_dir} "
        f"cache={t.cache_dir_name} ndk_abi={t.ndk_abi}"
    )


def _main(argv: list[str]) -> int:
    """Print the resolved target for the running device or a named arch.

    Usage:
        dsh_arch.py [--json] [ARCH]

    Without an argument the running device's Node arch is used. ``--json`` emits
    every field, for callers that must not parse prose; shell callers use
    ``--field NAME`` to read one value.
    """
    args = argv[1:]
    as_json = False
    field = ""
    arch_arg = ""
    rest = list(args)
    while rest:
        arg = rest.pop(0)
        if arg == "--json":
            as_json = True
        elif arg == "--field" and rest:
            field = rest.pop(0)
        elif arg.startswith("--field="):
            field = arg.split("=", 1)[1]
        else:
            arch_arg = arg
    try:
        target = running_target() if not arch_arg else target_for(arch_arg)
    except UnsupportedArchitectureError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    fields = {
        "node_arch": target.node_arch,
        "prebuild_dir": target.prebuild_dir,
        "cache_dir_name": target.cache_dir_name,
        "ndk_abi": target.ndk_abi,
        "elf_machine": str(target.elf_machine),
        "elf_class": str(target.elf_class),
    }
    if field:
        if field not in fields:
            print(f"error: unknown field {field!r}", file=sys.stderr)
            return 2
        print(fields[field])
    elif as_json:
        import json

        print(json.dumps(fields))
    else:
        print(
            f"node_arch={fields['node_arch']} prebuild_dir={fields['prebuild_dir']} "
            f"cache={fields['cache_dir_name']} ndk_abi={fields['ndk_abi']}",
        )
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
