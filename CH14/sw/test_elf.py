"""The ELF reader, which is how the application reaches the processor.

There is no bootloader here and no filesystem the processor can see: the PS
writes the program into BRAM itself, so what this module gets wrong lands as a
processor executing something that is not the program.
"""
import os
import struct
import unittest

import elf

HERE = os.path.dirname(os.path.abspath(__file__))
REAL_ELF = os.path.join(HERE, os.pardir, "sw_mb", "out", "ch14_sysmon_lcd.elf")


def build_elf(segments, symbols=(), machine=243, elf_class=1, data=1,
              etype=2, magic=b"\x7fELF"):
    """A minimal but real ELF32 file, so the tests exercise the parser rather
    than a mock of it. `segments` is a list of (vaddr, bytes, memsz)."""
    ehsize, phentsize, shentsize = 52, 32, 40

    strtab = b"\x00"
    symtab = b"\x00" * 16                      # the mandatory null symbol
    for name, value in symbols:
        name_off = len(strtab)
        strtab += name.encode() + b"\x00"
        # st_name, st_value, st_size, st_info, st_other, st_shndx
        symtab += struct.pack("<IIIBBH", name_off, value, 4, 0x10, 0, 1)

    phoff = ehsize
    body_off = phoff + phentsize * len(segments)

    phdrs, body = b"", b""
    for vaddr, payload, memsz in segments:
        off = body_off + len(body)
        # p_type PT_LOAD, offset, vaddr, paddr, filesz, memsz, flags, align
        phdrs += struct.pack("<IIIIIIII", 1, off, vaddr, vaddr,
                             len(payload), memsz, 6, 1)
        body += payload

    symtab_off = body_off + len(body)
    strtab_off = symtab_off + len(symtab)
    shstr = b"\x00.symtab\x00.strtab\x00"
    shstr_off = strtab_off + len(strtab)
    shoff = shstr_off + len(shstr)

    # null, .symtab (type 2), .strtab (type 3), .shstrtab (type 3)
    shdrs = b"\x00" * shentsize
    shdrs += struct.pack("<IIIIIIIIII", 1, 2, 0, 0, symtab_off, len(symtab),
                         2, 0, 4, 16)
    shdrs += struct.pack("<IIIIIIIIII", 9, 3, 0, 0, strtab_off, len(strtab),
                         0, 0, 1, 0)
    shdrs += struct.pack("<IIIIIIIIII", 9, 3, 0, 0, shstr_off, len(shstr),
                         0, 0, 1, 0)

    ident = magic + bytes([elf_class, data, 1]) + b"\x00" * 9
    header = ident + struct.pack("<HHIIIIIHHHHHH", etype, machine, 1, 0,
                                 phoff, shoff, 0, ehsize, phentsize,
                                 len(segments), shentsize, 4, 3)
    return header + phdrs + body + symtab + strtab + shstr + shdrs


class LoadSegments(unittest.TestCase):
    def test_returns_the_bytes_a_loadable_segment_carries(self):
        image = build_elf([(0x0, b"\x01\x02\x03\x04", 4)])
        segments = elf.load_segments(image)
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].vaddr, 0)
        self.assertEqual(segments[0].data, b"\x01\x02\x03\x04")

    def test_reports_the_memory_a_segment_needs_beyond_its_bytes(self):
        """.bss occupies memory the file does not carry. A loader that only
        wrote filesz would leave the previous program's data as this one's
        zero-initialised variables."""
        image = build_elf([(0x0, b"\xAA" * 8, 32)])
        segments = elf.load_segments(image)
        self.assertEqual(len(segments[0].data), 8)
        self.assertEqual(segments[0].memsz, 32)

    def test_skips_segments_that_are_not_loadable(self):
        image = build_elf([(0x0, b"\x01\x02\x03\x04", 4)])
        # Turn the single PT_LOAD into PT_NOTE.
        image = bytearray(image)
        struct.pack_into("<I", image, 52, 4)
        self.assertEqual(elf.load_segments(bytes(image)), [])

    def test_rejects_a_file_that_is_not_an_elf(self):
        with self.assertRaises(ValueError):
            elf.load_segments(b"not an elf at all, not even close")

    def test_rejects_a_64_bit_elf(self):
        """The MicroBlaze-V here is rv32. A 64-bit image would parse into
        nonsense offsets rather than failing on its own."""
        with self.assertRaises(ValueError):
            elf.load_segments(build_elf([(0, b"\x00" * 4, 4)], elf_class=2))

    def test_rejects_a_big_endian_elf(self):
        with self.assertRaises(ValueError):
            elf.load_segments(build_elf([(0, b"\x00" * 4, 4)], data=2))

    def test_rejects_an_elf_for_another_architecture(self):
        """Building for psu_cortexa53_0 by mistake produces a perfectly valid
        ELF that would load and never execute."""
        with self.assertRaises(ValueError):
            elf.load_segments(build_elf([(0, b"\x00" * 4, 4)], machine=183))


class Symbols(unittest.TestCase):
    def test_finds_a_symbol_by_name(self):
        image = build_elf([(0, b"\x00" * 4, 4)], symbols=[("mailbox", 0x1FB8)])
        self.assertEqual(elf.symbol_address(image, "mailbox"), 0x1FB8)

    def test_returns_none_for_a_symbol_that_is_not_there(self):
        image = build_elf([(0, b"\x00" * 4, 4)], symbols=[("mailbox", 0x10)])
        self.assertIsNone(elf.symbol_address(image, "nonesuch"))


class TheRealApplication(unittest.TestCase):
    """Against the actual ELF, when there is one. Skipped rather than failed
    if the application has not been built, so the suite is still useful on a
    checkout that has only run the host tests."""

    def setUp(self):
        if not os.path.isfile(REAL_ELF):
            self.skipTest(f"not built: {REAL_ELF}")
        with open(REAL_ELF, "rb") as handle:
            self.image = handle.read()

    def test_it_loads_at_the_processors_reset_vector(self):
        """C_BASE_VECTORS is 0 on this processor, so an image starting
        anywhere else would never be reached."""
        segments = elf.load_segments(self.image)
        self.assertEqual(min(s.vaddr for s in segments), 0)

    def test_it_fits_in_the_local_memory_the_hardware_provides(self):
        segments = elf.load_segments(self.image)
        top = max(s.vaddr + s.memsz for s in segments)
        self.assertLessEqual(top, 64 * 1024,
                             "the application no longer fits in 64 KB")

    def test_it_exports_the_mailbox_the_notebook_reads(self):
        """The notebook finds the mailbox through this symbol rather than at a
        fixed address, so losing the symbol loses the only debug channel this
        design has."""
        self.assertIsNotNone(elf.symbol_address(self.image, "mailbox"))


if __name__ == "__main__":
    unittest.main()
