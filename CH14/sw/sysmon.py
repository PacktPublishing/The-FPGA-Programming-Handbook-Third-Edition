"""The UltraScale+ SYSMON, read from the PS.

The application on the MicroBlaze-V reads the same sensors through the same
wizard and puts them on the panel. This module exists so the notebook can read
them independently and compare -- which is the only way to tell "the panel
says 42.0 C" from "the panel says something and it happens to look like a
temperature".

That comparison is only meaningful if both sides agree about where the
registers are and how to convert them, so the candidates, the DRP addresses
and the plausibility bounds below are the same ones as sw_mb/src/sysmon.h and
test_sysmon.py asserts it.

ON THIS PART IT IS SYSMONE4, NOT XADC. The 7-series block is 12-bit; this one
is 10-bit. Both store the result left-justified in a 16-bit register, so code
written against the full 16-bit value is correct on either -- which is why
every conversion here divides by 65536 rather than by 4096 or 1024.
"""

# --- the wizard's own registers -------------------------------------------
# These answer even when the SYSMONE4 macro does not, which is precisely how
# a dead converter can look like a working one.
REG_SRR = 0x00       # IP soft reset: write 0x0A
REG_SR = 0x04        # BUSY, EOC, EOS, current channel
REG_SYSMONRR = 0x10  # SYSMONE4 macro reset: write 0x0A

# The AXI window is 8 KB. Mapping only 4 KB puts the DRP registers outside the
# mapping entirely.
AXI_WINDOW_SIZE = 0x2000

# 0x1400 first because that is where this window was MEASURED, by scanning all
# 8 KB of it on this IP revision and this board. 0x400 is what Vitis's own
# sysmon driver computes for system_management_wiz and 0x200 is the 7-series
# XADC Wizard's; both are kept as fallbacks and neither is trusted first.
#
# 0x1400 IS NOT 0x200, AND THE DIFFERENCE COST A DAY. An unmapped read in this
# window returns zero rather than faulting, which is indistinguishable from a
# SYSMON that is present, placed and not converting -- and it was diagnosed as
# exactly that, wrongly, until the macro's own eoc pin was counted in fabric.
DRP_CANDIDATES = (0x1400, 0x0400, 0x0200)

DRP_TEMPERATURE = 0x00
DRP_VCCINT = 0x01
DRP_VCCAUX = 0x02
DRP_VP_VN = 0x03
DRP_VCCBRAM = 0x06
DRP_MAX_TEMPERATURE = 0x20
DRP_MIN_TEMPERATURE = 0x24

SUPPLY_CHANNELS = {
    "vccint": DRP_VCCINT,
    "vccaux": DRP_VCCAUX,
    "vccbram": DRP_VCCBRAM,
}

# UG580's UltraScale formula. The board's own xilinx-ams driver agrees
# independently: 7.771514892 millidegrees per LSB, offset -280.2 C.
TEMP_SCALE = 509.3140064
TEMP_OFFSET = 280.23087870

# Supply sensors have a fixed 3.0 V full scale; the external VP/VN channel in
# unipolar mode has a fixed 1.0 V full scale. Neither is adjustable.
SUPPLY_FULL_SCALE = 3.0
EXTERNAL_FULL_SCALE = 1.0

# What a healthy AUP-ZU3 must read, used to tell a real window from an
# accidental one. These are properties of the board, known without asking the
# SYSMON, which is what makes them usable as the test.
PLAUSIBLE_TEMP_MIN_C = -40.0
PLAUSIBLE_TEMP_MAX_C = 125.0
VCCINT_MIN_V = 0.75
VCCINT_MAX_V = 0.95
VCCAUX_MIN_V = 1.70
VCCAUX_MAX_V = 1.90


class SysmonNotFound(RuntimeError):
    """No candidate window held readings this board could actually produce."""


def raw_to_celsius(raw16):
    return raw16 * TEMP_SCALE / 65536.0 - TEMP_OFFSET


def raw_to_supply_volts(raw16):
    return raw16 * SUPPLY_FULL_SCALE / 65536.0


def raw_to_external_volts(raw16):
    return raw16 * EXTERNAL_FULL_SCALE / 65536.0


def raw_to_fraction(raw16):
    """The pot's position, 0.0 to 1.0 of the channel's full scale."""
    return raw16 / 65536.0


class Sysmon:
    """Takes anything with read(offset) and write(offset, value), which is
    PYNQ's MMIO and also the fake the tests use."""

    def __init__(self, mmio):
        self.mmio = mmio
        self.drp_base = None

    # --- finding the registers -------------------------------------------

    def _read_at(self, drp_base, address):
        return self.mmio.read(drp_base + 4 * address) & 0xFFFF

    def _window_is_live(self, drp_base):
        raw_temp = self._read_at(drp_base, DRP_TEMPERATURE)
        if raw_temp == 0:
            return False
        if not (PLAUSIBLE_TEMP_MIN_C <= raw_to_celsius(raw_temp)
                <= PLAUSIBLE_TEMP_MAX_C):
            return False

        vccint = raw_to_supply_volts(self._read_at(drp_base, DRP_VCCINT))
        if not VCCINT_MIN_V <= vccint <= VCCINT_MAX_V:
            return False

        vccaux = raw_to_supply_volts(self._read_at(drp_base, DRP_VCCAUX))
        return VCCAUX_MIN_V <= vccaux <= VCCAUX_MAX_V

    def locate(self):
        """Find the DRP window and return its offset. Raises rather than
        guessing: a wrong window reads zero, and a driver that returned
        0.000 V and -280 C would be reporting an address mistake as a
        measurement."""
        for candidate in DRP_CANDIDATES:
            if self._window_is_live(candidate):
                self.drp_base = candidate
                return candidate
        raise SysmonNotFound(
            "no candidate DRP window (%s) held readings this board could "
            "produce. Either the loaded bitstream is not this project's, or "
            "the SYSMONE4 is not converting. The wizard's AXI wrapper "
            "answering is not evidence that it is -- the vendor base overlay "
            "fails in exactly that way."
            % ", ".join("0x%04X" % c for c in DRP_CANDIDATES))

    def _require_located(self):
        if self.drp_base is None:
            raise SysmonNotFound("call locate() before reading -- reading an "
                                 "assumed window is the mistake this class "
                                 "exists to prevent")

    # --- measurements ----------------------------------------------------

    def drp_read(self, address):
        self._require_located()
        return self._read_at(self.drp_base, address)

    def temperature_celsius(self):
        return raw_to_celsius(self.drp_read(DRP_TEMPERATURE))

    def temperature_extremes_celsius(self):
        """(min, max) since power-up, latched by the macro itself."""
        return (raw_to_celsius(self.drp_read(DRP_MIN_TEMPERATURE)),
                raw_to_celsius(self.drp_read(DRP_MAX_TEMPERATURE)))

    def supply_volts(self, name):
        return raw_to_supply_volts(self.drp_read(SUPPLY_CHANNELS[name]))

    def pot_raw(self):
        return self.drp_read(DRP_VP_VN)

    def pot_volts(self):
        return raw_to_external_volts(self.pot_raw())

    def read_all(self):
        """Everything at once, for a comparison that should be taken as a
        single moment rather than a sequence."""
        self._require_located()
        raw_pot = self.drp_read(DRP_VP_VN)
        low, high = self.temperature_extremes_celsius()
        return {
            "temperature": self.temperature_celsius(),
            "temperature_min": low,
            "temperature_max": high,
            "supplies": {name: raw_to_supply_volts(self.drp_read(address))
                         for name, address in SUPPLY_CHANNELS.items()},
            "pot": {
                "raw": raw_pot,
                "volts": raw_to_external_volts(raw_pot),
                "fraction": raw_to_fraction(raw_pot),
            },
        }
