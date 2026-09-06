"""One object that ties the four pieces together, for the notebook to drive.

The overlay gives four AXI slaves through M_AXI_HPM0_LPD:

    mb_bram_ctrl   0x80000000  the processor's 64 KB, where the ELF goes
    mb_ctrl        0x80010000  one bit: hold or release the processor
    axi_iic_0      0x80020000  the panel's bus, shared with the processor
    sysmon         0x80030000  the same sensors the application reads

The last two are shared with the MicroBlaze-V, and they are shared
differently. Reading the SYSMON from both is safe: the wizard's bridge
arbitrates DRP reads. Driving the IIC from both is NOT -- two masters
interleave transactions on one controller and produce nonsense -- so the panel
may only be driven from here with the processor halted.

PYNQ is imported lazily so that everything except from_overlay() can be
tested on a workstation.
"""

import time

from microblaze_v import (MicroblazeV, BRAM_BASE, CTRL_BASE, IIC_BASE,
                          SYSMON_BASE, MEM_SIZE)
import mailbox as mailbox_module
import sysmon as sysmon_module
import grove_lcd as lcd_module

# What the four windows are called in the block design, and where build.tcl
# put them. Looked up by name and checked against the address, because an
# overlay whose addresses moved should say so rather than be read at the
# wrong place.
EXPECTED = {
    "mb_bram_ctrl": (BRAM_BASE, MEM_SIZE),
    "mb_ctrl": (CTRL_BASE, 0x10000),
    "axi_iic_0": (IIC_BASE, 0x10000),
    "system_management_wiz_0": (SYSMON_BASE, 0x10000),
}


def find_window(ip_dict, mem_dict, name, expected_address):
    """One peripheral's metadata, from whichever dictionary PYNQ filed it in.

    PYNQ SPLITS AN OVERLAY'S PERIPHERALS ACROSS TWO DICTIONARIES, and which
    one a peripheral lands in is not visible from the block design.
    `hwh_parser.init_mem_dict()` moves any IP whose address segment is a
    MEMORY into `mem_dict`, and the device layer then drops it from
    `ip_dict`. An `axi_bram_ctrl`'s segment is `Mem0`, not `Reg`, so
    `mb_bram_ctrl` is a memory as far as PYNQ is concerned and is NOT in
    `ip_dict` at all.

    Searching only `ip_dict` finds the other three and concludes the
    bitstream is wrong -- which is the one thing it definitely is not, since
    `mb_ctrl` is right there beside them and exists in no other design.
    """
    info = ip_dict.get(name)
    if info is None:
        info = (mem_dict or {}).get(name)

    if info is None:
        raise RuntimeError(
            f"the overlay has no peripheral called {name}.\n"
            f"  ip_dict : {sorted(ip_dict)}\n"
            f"  mem_dict: {sorted(mem_dict or {})}\n"
            f"Both were searched. If neither lists it, this is the wrong "
            f"bitstream -- check the .hwh beside the .bit is this project's.")

    if info["phys_addr"] != expected_address:
        raise RuntimeError(
            f"{name} is at 0x{info['phys_addr']:08X}, but this software is "
            f"built for 0x{expected_address:08X}. The bitstream and sw/ have "
            f"drifted apart -- compare build.tcl's address map with "
            f"microblaze_v.py.")

    return info


class Ch14:
    def __init__(self, bram, ctrl, iic, sysmon_window):
        self.bram = bram
        self.ctrl = ctrl
        self.iic = iic
        self.sysmon_window = sysmon_window
        self.mb = MicroblazeV(bram, ctrl)
        self.sysmon = sysmon_module.Sysmon(sysmon_window)
        self._mailbox_address = None

    # --- getting here from a bitstream ------------------------------------

    @classmethod
    def from_overlay(cls, bitstream):
        """Download the bitstream and map the four windows.

        The processor comes up HELD IN RESET -- mb_ctrl's output register
        powers up with the reset bit set -- so nothing runs until
        start_application() says so. That is deliberate: an all-zero BRAM is
        an illegal instruction on RISC-V, and a processor trap-looping while
        the ELF is written is not a useful starting point.
        """
        from pynq import Overlay, MMIO       # noqa: F401  (board only)

        overlay = Overlay(bitstream)
        mem_dict = getattr(overlay, "mem_dict", {})
        windows = {}
        for name, (address, length) in EXPECTED.items():
            info = find_window(overlay.ip_dict, mem_dict, name, address)
            # MMIO maps by physical address and does not care which dictionary
            # the address came from, so the BRAM controller is reached exactly
            # like the three register peripherals.
            windows[name] = MMIO(info["phys_addr"],
                                 max(length, info["addr_range"]))

        session = cls(windows["mb_bram_ctrl"], windows["mb_ctrl"],
                      windows["axi_iic_0"],
                      windows["system_management_wiz_0"])
        session.overlay = overlay
        return session

    # --- the application ---------------------------------------------------

    def start_application(self, elf_path, timeout=5.0):
        """Halt, load, verify, release, and wait for the first heartbeat.

        Returns the first mailbox read. Raising here rather than returning a
        blank panel is the whole point: every step below has a distinct
        failure and this design has no console to report them on.
        """
        with open(elf_path, "rb") as handle:
            image = handle.read()

        self.mb.halt()
        self.mb.load_elf(image)

        if not self.mb.verify_elf(image):
            raise RuntimeError(
                "the memory did not read back what was written to it. The "
                "path is PS to AXI to BRAM with the LMB side idle, so this "
                "should be exact -- suspect the bitstream rather than the ELF.")

        self._mailbox_address = self.mb.symbol_address("mailbox")
        if self._mailbox_address is None:
            raise RuntimeError(
                "this ELF exports no 'mailbox' symbol, so there is no way to "
                "find out what the application is doing. Was it built from "
                "sw_mb/src?")

        # Blank the magic word before release. Otherwise a previous run's
        # mailbox, still sitting in BRAM, would answer the first read and
        # report a heartbeat for an application that has not started.
        self.mb.write_memory(self._mailbox_address, b"\x00" * 4)

        self.mb.run()
        return self.wait_for_mailbox(timeout)

    def stop_application(self):
        self.mb.halt()

    # --- what the application has to say -----------------------------------

    def read_mailbox(self):
        if self._mailbox_address is None:
            raise RuntimeError("no application has been started from this "
                               "session, so the mailbox address is not known")
        raw = self.mb.read_memory(self._mailbox_address, mailbox_module.SIZE)
        return mailbox_module.decode(raw)

    def wait_for_mailbox(self, timeout=5.0):
        """Poll until the application writes its magic word."""
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            try:
                return self.read_mailbox()
            except ValueError as problem:
                last = problem
                time.sleep(0.05)
        raise RuntimeError(
            f"the application did not reach main() within {timeout} s "
            f"({last}). The processor was released, so suspect the reset "
            f"wiring or an ELF built for the wrong processor.")

    def is_running(self, settle=0.5):
        """Watch the heartbeat. This is the one thing that distinguishes an
        application that is loaded and stopped from one that is working."""
        before = self.read_mailbox()
        time.sleep(settle)
        return mailbox_module.is_alive(before, self.read_mailbox())

    # --- the panel, for when it is the panel that is in doubt ---------------

    def take_panel(self, contrast=lcd_module.DEFAULT_CONTRAST):
        """Halt the processor and drive the panel from here instead.

        Halting first is not politeness. Both masters reach the same AXI IIC
        core, and two masters interleaving transactions on one I2C controller
        produce nonsense rather than an error.
        """
        self.mb.halt()
        return lcd_module.GroveLCD(lcd_module.AxiIic(self.iic), contrast)
