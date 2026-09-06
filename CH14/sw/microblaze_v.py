"""Loading and starting the MicroBlaze-V from the PS.

This is what build.tcl's three additions are for. The PS reaches the
processor's 64 KB of local memory through mb_bram_ctrl -- the third port that
merging the two LMB controllers freed up -- and holds or releases the
processor through one bit of mb_ctrl, which is OR-ed into the processor's
Reset pin and touches nothing else.

The order is not negotiable: HALT, LOAD, RUN. Writing a program underneath a
running processor produces whatever the half-written program happens to do,
and this processor has no console to report that on.

PYNQ's own PynqMicroblaze class is not used. It expects the naming and the
memory layout of PYNQ's IOP subsystems, and this is a plain MicroBlaze-V with
a BRAM controller. Forty lines that match the hardware beat a class that
almost does.
"""

import elf

# The 64 KB assigned to mb_bram_ctrl in build.tcl. The LMB sees the same
# memory at 0x00000000 and the PS at 0x80000000; these are offsets within the
# PS's window.
MEM_SIZE = 64 * 1024

# The PS-side addresses build.tcl assigns. Kept here so the notebook can find
# the IP even on a PYNQ that did not populate ip_dict the way it expected.
BRAM_BASE = 0x80000000
CTRL_BASE = 0x80010000
IIC_BASE = 0x80020000
SYSMON_BASE = 0x80030000

# AXI GPIO, channel 1 data register.
GPIO_DATA = 0x00

# Bit 0 asserts the processor's reset. mb_ctrl powers up with this SET, so the
# processor is held from the moment the bitstream lands rather than executing
# an all-zero BRAM -- which on RISC-V is an illegal instruction and a trap
# loop. The consequence is that loading the overlay alone leaves the panel
# blank: this class is the thing that starts it.
CTRL_RESET_BIT = 0x1


class MicroblazeV:
    def __init__(self, bram_mmio, ctrl_mmio, mem_size=MEM_SIZE):
        self.bram = bram_mmio
        self.ctrl = ctrl_mmio
        self.mem_size = mem_size
        self._symbols = {}

    # --- holding and releasing -------------------------------------------

    def halt(self):
        value = self.ctrl.read(GPIO_DATA) | CTRL_RESET_BIT
        self.ctrl.write(GPIO_DATA, value)

    def run(self):
        value = self.ctrl.read(GPIO_DATA) & ~CTRL_RESET_BIT & 0xFFFFFFFF
        self.ctrl.write(GPIO_DATA, value)

    def is_halted(self):
        return bool(self.ctrl.read(GPIO_DATA) & CTRL_RESET_BIT)

    # --- memory ----------------------------------------------------------
    #
    # The BRAM controller is 32 bits wide and MMIO reads and writes whole
    # words, so a byte range that does not start or end on a word boundary has
    # to be merged with what is already in the partial words at each end. The
    # alternative -- rounding the range outwards -- would clobber bytes the
    # caller did not ask to change, which for two adjacent segments means the
    # second one eats the tail of the first.

    def _check_range(self, address, length):
        if address < 0 or length < 0 or address + length > self.mem_size:
            raise ValueError(
                f"0x{address:X}+{length} is outside the processor's "
                f"{self.mem_size // 1024} KB of memory")

    def read_memory(self, address, length):
        self._check_range(address, length)
        if length == 0:
            return b""
        first = address & ~0x3
        last = (address + length + 3) & ~0x3
        raw = bytearray()
        for offset in range(first, last, 4):
            raw += self.bram.read(offset).to_bytes(4, "little")
        start = address - first
        return bytes(raw[start:start + length])

    def write_memory(self, address, data):
        self._check_range(address, len(data))
        if not data:
            return
        first = address & ~0x3
        last = (address + len(data) + 3) & ~0x3

        # Read the two partial words at the ends back before merging. Only the
        # ends can be partial, so at most two reads however long the write is.
        block = bytearray(last - first)
        if address != first:
            block[0:4] = self.bram.read(first).to_bytes(4, "little")
        if (address + len(data)) != last:
            block[-4:] = self.bram.read(last - 4).to_bytes(4, "little")

        start = address - first
        block[start:start + len(data)] = data

        for i in range(0, len(block), 4):
            self.bram.write(first + i,
                            int.from_bytes(block[i:i + 4], "little"))

    # --- the application -------------------------------------------------

    def load_elf(self, image):
        """Write an ELF's loadable segments into the processor's memory.

        Does NOT start the processor. That is a separate call so the caller
        can check what it loaded, and set the mailbox up, before anything
        begins executing.
        """
        if not self.is_halted():
            raise RuntimeError(
                "the processor is running. Writing a program underneath it "
                "produces whatever the half-written program does -- call "
                "halt() first.")

        segments = elf.load_segments(image)
        if not segments:
            raise ValueError("this ELF has no loadable segments")

        for segment in segments:
            self._check_range(segment.vaddr, segment.memsz)
            self.write_memory(segment.vaddr, segment.data)
            # Everything the segment claims beyond what the file carries is
            # .bss, and it has to be zero before the application runs.
            padding = segment.memsz - len(segment.data)
            if padding:
                self.write_memory(segment.vaddr + len(segment.data),
                                  b"\x00" * padding)

        self._symbols = elf.symbols(image)
        return segments

    def verify_elf(self, image):
        """Read back what load_elf wrote. The path is PS to AXI to BRAM with
        the LMB side idle, so it should be exact -- and if it is not, that is
        worth knowing before the processor runs rather than after."""
        for segment in elf.load_segments(image):
            if self.read_memory(segment.vaddr, len(segment.data)) != segment.data:
                return False
        return True

    def symbol_address(self, name):
        """Where a symbol from the loaded ELF ended up. This is how the
        mailbox is found -- see sw_mb/src/mailbox.h."""
        return self._symbols.get(name)
