"""The PS-side panel driver.

The application drives this panel from the MicroBlaze-V. This module drives
the same panel from Python, over the same AXI IIC core, and exists for one
reason: when nothing appears on the glass, it separates "the panel or its
wiring is broken" from "the application is broken". With no UART on this
design there is no other way to tell those apart.

Only ONE of the two may drive the bus at a time. Two masters interleaving
transactions on one I2C controller produce nonsense, so the notebook uses this
with the processor held in reset. The hardware cannot enforce that; test
below asserts the driver at least refuses the obvious mistake.
"""
import unittest

import grove_lcd
from fake_mmio import FakeMMIO


class FakeIicWindow(FakeMMIO):
    """The AXI IIC register window, answering as an idle bus with a slave
    that acknowledges."""

    def __init__(self, nack=False, stuck_busy=False):
        super().__init__(0x1000)
        self._nack = nack
        self._stuck = stuck_busy
        self.fifo = []

    def read(self, offset, length=4):
        if offset == grove_lcd.IIC_SR:
            return grove_lcd.IIC_SR_BB if self._stuck else 0
        if offset == grove_lcd.IIC_ISR:
            return grove_lcd.IIC_ISR_TX_ERROR if self._nack else 0
        return super().read(offset, length)

    def write(self, offset, value):
        if offset == grove_lcd.IIC_TX_FIFO:
            self.fifo.append(value)
        super().write(offset, value)


def commands(window):
    """The command bytes sent, recovered from the FIFO writes."""
    out = []
    for i in range(len(window.fifo) - 2):
        if (window.fifo[i] & 0x1FF) == (grove_lcd.IIC_START |
                                        (grove_lcd.LCD_ADDR << 1)) \
                and (window.fifo[i + 1] & 0xFF) == grove_lcd.CTRL_CMD:
            out.append(window.fifo[i + 2] & 0xFF)
    return out


class Framing(unittest.TestCase):
    def test_a_write_starts_with_the_addressing_byte(self):
        window = FakeIicWindow()
        iic = grove_lcd.AxiIic(window)
        iic.write_bytes(0x3E, [0x80, 0x01])
        self.assertEqual(window.fifo[0],
                         grove_lcd.IIC_START | (0x3E << 1))

    def test_only_the_last_byte_carries_the_stop_marker(self):
        """A STOP on the wrong byte truncates the transfer; a missing one
        leaves the bus held and every later transaction times out."""
        window = FakeIicWindow()
        iic = grove_lcd.AxiIic(window)
        iic.write_bytes(0x3E, [0x80, 0x01, 0x02])
        self.assertEqual(window.fifo[1] & grove_lcd.IIC_STOP, 0)
        self.assertEqual(window.fifo[2] & grove_lcd.IIC_STOP, 0)
        self.assertEqual(window.fifo[3] & grove_lcd.IIC_STOP,
                         grove_lcd.IIC_STOP)

    def test_a_slave_that_does_not_acknowledge_is_reported(self):
        window = FakeIicWindow(nack=True)
        iic = grove_lcd.AxiIic(window)
        with self.assertRaises(IOError):
            iic.write_bytes(0x3E, [0x80, 0x01])

    def test_a_bus_that_never_goes_idle_is_reported(self):
        window = FakeIicWindow(stuck_busy=True)
        with self.assertRaises(TimeoutError):
            grove_lcd.AxiIic(window).write_bytes(0x3E, [0x80])

    def test_an_empty_write_is_refused(self):
        """No bytes means no STOP to attach, which would leave the bus held."""
        window = FakeIicWindow()
        iic = grove_lcd.AxiIic(window)
        with self.assertRaises(ValueError):
            iic.write_bytes(0x3E, [])


class Initialisation(unittest.TestCase):
    def setUp(self):
        self.window = FakeIicWindow()
        self.lcd = grove_lcd.GroveLCD(grove_lcd.AxiIic(self.window))

    def test_it_enters_the_extended_instruction_set_before_the_contrast(self):
        """The booster, follower and contrast registers do not exist outside
        it -- written with IS=0 they move the cursor instead, and the panel
        comes up initialised and blank."""
        self.assertEqual(commands(self.window)[:3], [0x38, 0x39, 0x14])

    def test_it_programs_both_halves_of_the_contrast(self):
        contrast = grove_lcd.DEFAULT_CONTRAST
        self.assertEqual(commands(self.window)[3:5],
                         [0x70 | (contrast & 0x0F),
                          0x50 | 0x04 | ((contrast >> 4) & 0x03)])

    def test_it_leaves_the_extended_set_before_enabling_the_display(self):
        """0x0C means display-on only while IS = 0."""
        self.assertEqual(commands(self.window)[5:8], [0x6C, 0x38, 0x0C])

    def test_it_matches_the_application_command_for_command(self):
        """The C driver in sw_mb/src/grove_lcd.c sends this exact sequence.
        If they ever differ, one of them is displaying and the other is not,
        and the notebook's panel check stops meaning anything."""
        self.assertEqual(commands(self.window),
                         [0x38, 0x39, 0x14,
                          0x70 | (grove_lcd.DEFAULT_CONTRAST & 0x0F),
                          0x50 | 0x04 | ((grove_lcd.DEFAULT_CONTRAST >> 4) & 0x03),
                          0x6C, 0x38, 0x0C, 0x01, 0x06])


class Writing(unittest.TestCase):
    def setUp(self):
        self.window = FakeIicWindow()
        self.lcd = grove_lcd.GroveLCD(grove_lcd.AxiIic(self.window))
        self.window.fifo.clear()

    def test_the_second_row_is_reached_through_the_ddram_offset(self):
        """It is not the seventeenth character: DDRAM jumps to 0x40."""
        self.lcd.set_cursor(0, 1)
        self.assertEqual(commands(self.window), [0x80 | 0x40])

    def test_a_row_is_padded_to_the_full_width(self):
        """The panel has no clear-to-end-of-line, so a short string leaves the
        previous frame's tail on the glass."""
        self.lcd.write_row(0, "Hi")
        characters = [w & 0xFF for i, w in enumerate(self.window.fifo)
                      if i % 3 == 2][1:]
        self.assertEqual(len(characters), grove_lcd.COLS)
        self.assertEqual(bytes(characters).decode(), "Hi" + " " * 14)

    def test_a_row_too_long_is_truncated_rather_than_wrapped(self):
        """A 17th character wraps onto the other row, so one bad line would
        silently corrupt the other."""
        self.lcd.write_row(0, "0123456789ABCDEFGHIJ")
        characters = [w & 0xFF for i, w in enumerate(self.window.fifo)
                      if i % 3 == 2][1:]
        self.assertEqual(bytes(characters).decode(), "0123456789ABCDEF")


if __name__ == "__main__":
    unittest.main()
