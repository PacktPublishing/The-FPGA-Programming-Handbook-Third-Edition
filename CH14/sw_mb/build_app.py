#!/usr/bin/env python3
"""Build the CH14 SYSMON application for the MicroBlaze-V.

    vitis -s sw_mb/build_app.py                 # platform + application
    vitis -s sw_mb/build_app.py -- --clean      # rebuild from scratch

Produces sw_mb/out/ch14_sysmon_lcd.elf, which the notebook loads into the
processor's memory through mb_bram_ctrl.

WHY THE APPLICATION DOES NOT USE THE BSP'S DRIVERS

The BSP is built and used -- it supplies the startup code, the linker script
and xil_io.h -- but XIic and XSysMon are deliberately not called. Two reasons,
and the second is the serious one:

  size      XIic alone is around 20 KB. The processor has 64 KB of local
            memory and no other RAM, and all the application does is
            master-transmit to one write-only device.

  address   Vitis's sysmon driver computes the DRP window at 0x400 for
            system_management_wiz. CH13 scanned all 8 KB of that window on
            this IP revision, on this board, and found it at 0x1400. An
            unmapped read there returns zero rather than faulting, which is
            indistinguishable from a SYSMON that is present and not
            converting -- and with no UART on this design, the only symptom
            would be a blank panel. src/sysmon.c finds the window instead of
            assuming it.
"""

import argparse
import glob
import os
import shutil
import sys

import vitis

HERE = os.path.dirname(os.path.abspath(__file__))
CH14 = os.path.dirname(HERE)

XSA = os.path.join(CH14, "project_sysmon_lcd", "out", "ch14_sysmon_lcd.xsa")
WORKSPACE = os.path.join(HERE, "workspace")
OUT = os.path.join(HERE, "out")

PLATFORM = "ch14_platform"
APP = "ch14_sysmon_lcd"

# The processor instance name as the block design calls it. If build.tcl ever
# renames the cell this has to follow, and the check below says so plainly
# rather than failing somewhere inside the BSP generator.
CPU = "microblaze_riscv_0"

SOURCES = [
    "main.c",
    "plat.c",
    "axi_iic.c",
    "grove_lcd.c",
    "sysmon.c",
    "fmt.c",
    "pages.c",
    "render.c",
]


def fail(message):
    print(f"\nERROR: {message}\n", file=sys.stderr)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--clean", action="store_true",
                        help="delete the workspace and rebuild from scratch")
    args = parser.parse_args()

    if not os.path.isfile(XSA):
        fail("no hardware to build against at %s\n"
             "       build it first:\n"
             "         vivado -mode batch -source project_sysmon_lcd/build.tcl"
             % XSA)

    if args.clean and os.path.isdir(WORKSPACE):
        shutil.rmtree(WORKSPACE)
    os.makedirs(WORKSPACE, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)

    client = vitis.create_client()
    client.set_workspace(path=WORKSPACE)

    # The XSA carries more than one processor -- the MicroBlaze-V and the
    # MPSoC's own cores. Naming the wrong one produces a BSP that compiles and
    # an ELF that will never run, so the choice is checked rather than
    # defaulted.
    # An OSProcessorList, which is a protobuf message rather than a sequence,
    # so it is searched as text.
    available = str(client.get_processor_os_list(xsa=XSA))
    if CPU not in available:
        fail("%s is not in this XSA. It offers:\n%s" % (CPU, available))
    print("==> %s found in the XSA" % CPU)

    # The platform carries the BSP, which takes minutes to build and changes
    # only when the hardware does. Rebuilding it on every application edit
    # would make the edit-build loop unusable, so an existing one is reused;
    # --clean is how you force it.
    #
    # Existence is tested by the project directory rather than by the exported
    # .xpfm. create_platform_component RESETS a project that already exists
    # before it reports ALREADY_EXISTS, which destroys the export and leaves a
    # workspace that fails the same way on every subsequent run.
    if os.path.isdir(os.path.join(WORKSPACE, PLATFORM)):
        print("==> Platform %s already exists (--clean to rebuild)" % PLATFORM)
        platform = client.get_component(name=PLATFORM)
    else:
        print("==> Platform component %s" % PLATFORM)
        platform = client.create_platform_component(
            name=PLATFORM,
            hw_design=XSA,
            cpu=CPU,
            os="standalone",
            no_boot_bsp=True,      # nothing boots this; the PS loads the ELF
            generate_dtb=False,    # no Linux on this processor
        )
    platform.build()

    # Where Vitis puts the .xpfm has moved between releases, so it is found
    # rather than assumed.
    xpfms = glob.glob(os.path.join(WORKSPACE, PLATFORM, "**", "*.xpfm"),
                      recursive=True)
    if len(xpfms) != 1:
        fail("expected exactly one exported .xpfm under %s, found: %s"
             % (os.path.join(WORKSPACE, PLATFORM), xpfms))
    xpfm = xpfms[0]
    print("    %s" % xpfm)

    print("==> Application component %s" % APP)
    if os.path.isdir(os.path.join(WORKSPACE, APP)):
        app = client.get_component(name=APP)
        print("    reusing the existing component")
    else:
        app = client.create_app_component(name=APP, platform=xpfm, cpu=CPU,
                                          os="standalone")

    headers = [f for f in os.listdir(os.path.join(HERE, "src"))
               if f.endswith(".h")]
    app.import_files(from_loc=os.path.join(HERE, "src"),
                     files=SOURCES + headers,
                     dest_dir_in_cmp="src")

    # These key names are the cmake variables in the component's own
    # UserConfig.cmake. Vitis rejects anything else with "Unable to get the
    # config information", which does not say which key it did not like.
    #
    # The warning set matches sw_mb/Makefile's, so the host test build and the
    # board build hold the same code to the same standard. -Werror is on in
    # both: a warning here reaches a board with no console to report it on.
    #
    # -Os rather than the default -O0: 64 KB is generous for this application
    # but not so generous that size is free, and nothing here is on a hot path
    # -- the loop spends 160 of every 200 ms waiting.
    for key, value in [
            ("USER_COMPILE_OPTIMIZATION_LEVEL", "-Os"),
            ("USER_COMPILE_WARNINGS_AS_ERRORS", "-Werror"),
            # Truthy turns on -ffunction-sections -fdata-sections; the linker
            # flag below is what actually drops what they separate out.
            ("USER_COMPILE_GARBAGE", "1"),
            ("USER_COMPILE_OTHER_FLAGS",
             "-std=c11 -Wconversion -Wshadow -Wstrict-prototypes "
             "-Wmissing-prototypes"),
            ("USER_LINK_OTHER_FLAGS", "-Wl,--gc-sections"),
    ]:
        app.set_app_config(key=key, values=value)

    app.build()

    elf = os.path.join(WORKSPACE, APP, "build", "%s.elf" % APP)
    if not os.path.isfile(elf):
        # Vitis has moved this between releases; look rather than guess.
        found = []
        for root, _dirs, files in os.walk(os.path.join(WORKSPACE, APP)):
            found += [os.path.join(root, f) for f in files if f.endswith(".elf")]
        if len(found) != 1:
            fail("expected exactly one .elf under the app component, found: %s"
                 % found)
        elf = found[0]

    shutil.copy2(elf, os.path.join(OUT, "%s.elf" % APP))
    print("\n==> %s.elf" % os.path.join(OUT, APP))

    vitis.dispose()


if __name__ == "__main__":
    main()
