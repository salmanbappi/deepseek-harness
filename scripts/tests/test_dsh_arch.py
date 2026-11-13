"""Tests for the Android architecture resolver.

The resolver decides which directory every native artifact lands in. A wrong
answer is silent: node-pty simply never finds the binary, and the harness loses
its shell. These tests pin the mapping to node-pty's own resolution rule,
``prebuilds/<platform>-<process.arch>``.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dsh_arch  # noqa: E402


class TargetMappingTest(unittest.TestCase):
    """Each architecture resolves to the directory node-pty searches."""

    def test_arm64(self) -> None:
        target = dsh_arch.target_for("arm64")
        self.assertEqual(target.prebuild_dir, "android-arm64")
        self.assertEqual(target.ndk_abi, "arm64-v8a")
        self.assertEqual(target.elf_machine, 183)
        self.assertEqual(target.elf_class, 2)

    def test_arm32(self) -> None:
        target = dsh_arch.target_for("arm")
        self.assertEqual(target.prebuild_dir, "android-arm")
        self.assertEqual(target.ndk_abi, "armeabi-v7a")
        self.assertEqual(target.elf_machine, 40)
        self.assertEqual(target.elf_class, 1)

    def test_x64(self) -> None:
        target = dsh_arch.target_for("x64")
        self.assertEqual(target.prebuild_dir, "android-x64")
        self.assertEqual(target.ndk_abi, "x86_64")

    def test_uname_values_normalize_to_node_arch(self) -> None:
        for uname_machine, node_arch in {
            "aarch64": "arm64",
            "arm64": "arm64",
            "armv8l": "arm",
            "armv7l": "arm",
            "armv8a": "arm",
            "amd64": "x64",
            "x86_64": "x64",
            "i686": "ia32",
        }.items():
            with self.subTest(uname_machine=uname_machine):
                self.assertEqual(dsh_arch.target_for(uname_machine).node_arch, node_arch)

    def test_armv8l_is_32_bit(self) -> None:
        # The case that shipped wrong: an ARMv8 core running an AArch32
        # userland reports armv8l from uname but 'arm' from Node, and only
        # 32-bit binaries load.
        self.assertEqual(dsh_arch.target_for("armv8l").prebuild_dir, "android-arm")

    def test_matches_node_pty_resolution_rule(self) -> None:
        for arch in dsh_arch.SUPPORTED_NODE_ARCHES:
            target = dsh_arch.target_for(arch)
            # Restating node-pty's formula: prebuilds/${platform}-${arch}.
            self.assertEqual(f"prebuilds/android-{target.node_arch}", f"prebuilds/{target.prebuild_dir}")

    def test_unknown_architectures_are_rejected(self) -> None:
        for arch in ("sparc64", "", "mips"):
            with self.subTest(arch=arch):
                with self.assertRaises(dsh_arch.UnsupportedArchitectureError):
                    dsh_arch.target_for(arch)


class ElfIdentityTest(unittest.TestCase):
    """The ELF check is what distinguishes a real binary from a mislabeled one."""

    @staticmethod
    def header(elf_class: int, machine: int, endian: int = 1) -> bytes:
        """Build a minimal ELF identification block."""
        return (
            b"\x7fELF"
            + bytes([elf_class, endian, 1])
            + bytes(9)
            + (3).to_bytes(2, "little")
            + machine.to_bytes(2, "little")
        )

    def test_reads_arm32_header(self) -> None:
        self.assertEqual(dsh_arch.elf_identity(self.header(1, 40)), (1, 40))

    def test_reads_aarch64_header(self) -> None:
        self.assertEqual(dsh_arch.elf_identity(self.header(2, 183)), (2, 183))

    def test_arm32_binary_matches_arm_only(self) -> None:
        probe = self.header(1, 40)
        self.assertTrue(dsh_arch.binary_matches(probe, "arm"))
        self.assertFalse(dsh_arch.binary_matches(probe, "arm64"))

    def test_aarch64_binary_does_not_match_arm32(self) -> None:
        probe = self.header(2, 183)
        self.assertTrue(dsh_arch.binary_matches(probe, "arm64"))
        self.assertFalse(dsh_arch.binary_matches(probe, "arm"))

    def test_rejects_non_elf(self) -> None:
        self.assertFalse(dsh_arch.binary_matches(b"not an elf file at all", "arm"))

    def test_rejects_short_and_truncated_input(self) -> None:
        self.assertFalse(dsh_arch.binary_matches(b"\x7fELF", "arm"))

    def test_rejects_big_endian(self) -> None:
        with self.assertRaises(ValueError):
            dsh_arch.elf_identity(self.header(1, 40, endian=2))


class CacheDirectoryTest(unittest.TestCase):
    """The cache lives under the per-arch name so two arches cannot collide."""

    def test_uses_the_prebuild_name(self) -> None:
        path = dsh_arch.native_cache_dir("armv8l", home="/home/example")
        self.assertEqual(path, "/home/example/.dsh/native/android-arm")

    def test_arm64_and_arm_do_not_share_a_directory(self) -> None:
        self.assertNotEqual(
            dsh_arch.native_cache_dir("arm64", home="/h"),
            dsh_arch.native_cache_dir("arm", home="/h"),
        )


class RunningTargetTest(unittest.TestCase):
    """The running target must match what Node reports, not what uname says."""

    def test_matches_node_process_arch(self) -> None:
        import subprocess

        try:
            reported = subprocess.run(
                ["node", "-p", "process.arch"],
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            self.skipTest("node is not available")
        self.assertEqual(dsh_arch.running_node_arch(), dsh_arch.target_for(reported).node_arch)


if __name__ == "__main__":
    unittest.main()
