"""Just enough ELF32 to put a program into a processor's memory.

The standard library has no ELF reader and pyelftools is not on the board, so
this parses the two things the loader needs: the program headers, which say
what to write where, and the symbol table, which is how the notebook finds the
mailbox without a fixed address to keep in step with.

Everything here is ELF32 little-endian RISC-V and refuses to be anything else.
A 64-bit or big-endian file would otherwise parse into plausible-looking
offsets and load garbage.
"""

import struct
from collections import namedtuple

Segment = namedtuple("Segment", "vaddr data memsz")

# e_ident
ELF_MAGIC = b"\x7fELF"
ELFCLASS32 = 1
ELFDATA2LSB = 1

ET_EXEC = 2
EM_RISCV = 243

PT_LOAD = 1
SHT_SYMTAB = 2

EHDR = "<16sHHIIIIIHHHHHH"
EHDR_SIZE = struct.calcsize(EHDR)
PHDR = "<IIIIIIII"
SHDR = "<IIIIIIIIII"
SYM = "<IIIBBH"
SYM_SIZE = struct.calcsize(SYM)


def _header(image):
    if len(image) < EHDR_SIZE:
        raise ValueError("too short to be an ELF file")

    (ident, e_type, e_machine, _version, _entry, e_phoff, e_shoff, _flags,
     _ehsize, e_phentsize, e_phnum, e_shentsize, e_shnum,
     e_shstrndx) = struct.unpack(EHDR, image[:EHDR_SIZE])

    if ident[:4] != ELF_MAGIC:
        raise ValueError("not an ELF file")
    if ident[4] != ELFCLASS32:
        raise ValueError("not a 32-bit ELF -- this processor is rv32, so a "
                         "64-bit image is the wrong build, not a big one")
    if ident[5] != ELFDATA2LSB:
        raise ValueError("not a little-endian ELF")
    if e_machine != EM_RISCV:
        raise ValueError(
            f"built for machine {e_machine}, not RISC-V ({EM_RISCV}) -- "
            "check build_app.py picked microblaze_riscv_0 and not one of the "
            "MPSoC's own cores, which produce a perfectly valid ELF that "
            "would load and never execute")
    if e_type != ET_EXEC:
        raise ValueError("not an executable ELF")

    return (e_phoff, e_phentsize, e_phnum, e_shoff, e_shentsize, e_shnum,
            e_shstrndx)


def _as_bytes(image):
    """Accept a path or the bytes themselves, so callers do not have to care
    and the tests can build an image in memory."""
    if isinstance(image, (bytes, bytearray)):
        return bytes(image)
    with open(image, "rb") as handle:
        return handle.read()


def load_segments(image):
    """The PT_LOAD segments, in file order.

    memsz beyond len(data) is .bss: memory the segment claims but the file
    does not carry, which the loader has to zero. Leaving it alone would give
    the application the previous run's bytes as its zero-initialised
    variables.
    """
    image = _as_bytes(image)
    e_phoff, e_phentsize, e_phnum = _header(image)[:3]

    segments = []
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        if off + struct.calcsize(PHDR) > len(image):
            raise ValueError("program header table runs past the end of file")
        (p_type, p_offset, p_vaddr, _p_paddr, p_filesz, p_memsz, _flags,
         _align) = struct.unpack(PHDR, image[off:off + struct.calcsize(PHDR)])
        if p_type != PT_LOAD:
            continue
        if p_offset + p_filesz > len(image):
            raise ValueError("segment contents run past the end of file")
        if p_memsz < p_filesz:
            raise ValueError("segment claims less memory than it carries")
        segments.append(Segment(vaddr=p_vaddr,
                                data=image[p_offset:p_offset + p_filesz],
                                memsz=p_memsz))
    return segments


def symbols(image):
    """Every symbol in the file, as {name: address}."""
    image = _as_bytes(image)
    (_phoff, _phentsize, _phnum, e_shoff, e_shentsize,
     e_shnum, _shstrndx) = _header(image)

    found = {}
    for i in range(e_shnum):
        off = e_shoff + i * e_shentsize
        if off + struct.calcsize(SHDR) > len(image):
            raise ValueError("section header table runs past the end of file")
        (_name, sh_type, _flags, _addr, sh_offset, sh_size, sh_link, _info,
         _align, _entsize) = struct.unpack(
             SHDR, image[off:off + struct.calcsize(SHDR)])
        if sh_type != SHT_SYMTAB:
            continue

        # sh_link names the string table this symbol table's names live in.
        str_off = e_shoff + sh_link * e_shentsize
        (_n, _t, _f, _a, str_start, str_len) = struct.unpack(
            SHDR, image[str_off:str_off + struct.calcsize(SHDR)])[:6]
        strings = image[str_start:str_start + str_len]

        for entry in range(sh_size // SYM_SIZE):
            sym_off = sh_offset + entry * SYM_SIZE
            st_name, st_value = struct.unpack(
                SYM, image[sym_off:sym_off + SYM_SIZE])[:2]
            if st_name == 0:
                continue
            end = strings.find(b"\x00", st_name)
            found[strings[st_name:end].decode("ascii", "replace")] = st_value
    return found


def symbol_address(image, name):
    """The address of one symbol, or None if it is not there."""
    return symbols(image).get(name)
