"""The Grove 16x2 LCD, driven from the PS over the AXI IIC core.

The application drives this panel from the MicroBlaze-V. This drives the same
panel from Python, and it is here for one reason: when nothing appears on the
glass, it separates "the panel or its wiring is broken" from "the application
is broken". With no UART on this design, nothing else can tell those apart.

ONLY ONE MASTER AT A TIME. The AXI IIC core has one bus, and two masters
interleaving transactions on it produce nonsense rather than an error. The
notebook uses this with the processor held in reset; the hardware cannot
enforce that and neither can this module.

The initialisation sequence is CH10's, arrived at empirically, and it is not
the datasheet's. sw_mb/src/grove_lcd.c sends the same one command for
command -- test_grove_lcd.py asserts it -- so that a panel that works under
one works under the other.
"""

import time

# --- AXI IIC (PG090), dynamic controller mode -----------------------------
IIC_ISR = 0x020
IIC_SOFTR = 0x040
IIC_CR = 0x100
IIC_SR = 0x104
IIC_TX_FIFO = 0x108

IIC_CR_EN = 0x01
IIC_CR_TXFIFO_RESET = 0x02
IIC_SR_BB = 0x04              # bus busy
IIC_ISR_TX_ERROR = 0x02       # INT(1): slave NACK in master transmit
IIC_SOFTR_KEY = 0x0A

IIC_START = 0x100
IIC_STOP = 0x200

# --- the panel ------------------------------------------------------------
LCD_ADDR = 0x3E
COLS = 16
ROWS = 2
CTRL_CMD = 0x80               # a command follows
CTRL_DATA = 0x40              # a character follows

# Contrast is not cosmetic on this panel. Wrong, and it is indistinguishable
# from one that never received a byte. 0x38 with 1/5 bias is what is readable.
DEFAULT_CONTRAST = 0x38


class AxiIic:
    """Master transmit only, which is all the panel needs -- it has no
    readable register."""

    def __init__(self, mmio):
        self.mmio = mmio
        self.reset()

    def reset(self):
        # The soft reset first: it is the only thing that clears a bus-busy
        # left behind by a transaction the previous bitstream abandoned.
        self.mmio.write(IIC_SOFTR, IIC_SOFTR_KEY)
        time.sleep(0.001)
        self.mmio.write(IIC_CR, IIC_CR_TXFIFO_RESET)
        self.mmio.write(IIC_CR, IIC_CR_EN)

    def _wait_bus_idle(self, timeout=0.2):
        deadline = time.time() + timeout
        while self.mmio.read(IIC_SR) & IIC_SR_BB:
            if time.time() > deadline:
                raise TimeoutError(
                    "the AXI IIC bus is stuck busy. Check the Grove cable and "
                    "that the MicroBlaze-V is halted -- two masters on one "
                    "bus look exactly like this.")

    def write_bytes(self, addr7, data):
        """One transaction: START, address, the bytes, STOP."""
        if not data:
            # No bytes means no STOP marker to attach, and the bus would stay
            # held after the address.
            raise ValueError("an I2C write needs at least one byte")

        self._wait_bus_idle()
        # Write-one-to-clear: writing back what was read clears exactly the
        # set bits. Without this, one NACK looks permanent.
        self.mmio.write(IIC_ISR, self.mmio.read(IIC_ISR))

        self.mmio.write(IIC_TX_FIFO, IIC_START | (addr7 << 1))
        last = len(data) - 1
        for i, byte in enumerate(data):
            word = byte & 0xFF
            if i == last:
                word |= IIC_STOP
            self.mmio.write(IIC_TX_FIFO, word)

        # Bus-busy takes a moment to assert. Checking immediately would find
        # the bus idle because the transfer had not started, and every write
        # would appear to succeed whether or not anything was connected.
        time.sleep(0.001)
        self._wait_bus_idle()

        if self.mmio.read(IIC_ISR) & IIC_ISR_TX_ERROR:
            self.reset()      # do not leave the core holding this one's mess
            raise IOError(f"no acknowledgement from I2C 0x{addr7:02X} -- "
                          "the panel is not answering")


class GroveLCD:
    """AiP31068L, ST7032-compatible, at 0x3E."""

    def __init__(self, iic, contrast=DEFAULT_CONTRAST):
        self.iic = iic
        self._init(contrast)

    def _cmd(self, value):
        self.iic.write_bytes(LCD_ADDR, [CTRL_CMD, value])

    def _char(self, value):
        self.iic.write_bytes(LCD_ADDR, [CTRL_DATA, value])

    def _init(self, contrast):
        time.sleep(0.05)
        self._cmd(0x38)                                    # 2 line, IS = 0
        self._cmd(0x39)                                    # IS = 1: extended
        self._cmd(0x14)                                    # oscillator, 1/5 bias
        self._cmd(0x70 | (contrast & 0x0F))                # contrast, low bits
        self._cmd(0x50 | 0x04 | ((contrast >> 4) & 0x03))  # booster + high bits
        self._cmd(0x6C)                                    # follower on
        # More than 200 ms, and not a margin to trim: a shorter wait gives a
        # panel that acknowledges every byte and displays nothing.
        time.sleep(0.30)
        self._cmd(0x38)                                    # back to IS = 0
        self._cmd(0x0C)                                    # display on
        self.clear()
        self._cmd(0x06)                                    # entry: increment

    def clear(self):
        self._cmd(0x01)
        time.sleep(0.002)     # the slowest command the panel has

    def set_cursor(self, col, row):
        # The second row is not the seventeenth character: DDRAM jumps to 0x40.
        self._cmd(0x80 | (col | (0x40 if row else 0x00)))

    def write(self, text):
        for character in text:
            self._char(ord(character))

    def write_row(self, row, text):
        """One whole row, padded to 16. The panel has no clear-to-end-of-line,
        so anything shorter leaves the previous frame's tail behind, and
        anything longer wraps onto the other row."""
        self.set_cursor(0, row)
        self.write(text[:COLS].ljust(COLS))
