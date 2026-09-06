"""A stand-in for PYNQ's MMIO, so the drivers can be tested off the board.

PYNQ's MMIO is a window onto physical memory; this is the same interface over
a bytearray. It is the only thing faked -- the drivers themselves are the ones
that run on the board.

Reads and writes are 32-bit and little-endian, matching both MMIO and the
MicroBlaze-V.
"""


class FakeMMIO:
    def __init__(self, length, base_addr=0):
        self.array = bytearray(length)
        self.length = length
        self.base_addr = base_addr
        self.writes = []          # (offset, value), in order

    def read(self, offset, length=4):
        if length != 4:
            raise ValueError("only 32-bit reads")
        if offset < 0 or offset + 4 > self.length:
            raise IndexError(f"read at 0x{offset:X} is outside the window")
        return int.from_bytes(self.array[offset:offset + 4], "little")

    def write(self, offset, value):
        if offset < 0 or offset + 4 > self.length:
            raise IndexError(f"write at 0x{offset:X} is outside the window")
        self.array[offset:offset + 4] = int(value).to_bytes(4, "little")
        self.writes.append((offset, int(value)))
