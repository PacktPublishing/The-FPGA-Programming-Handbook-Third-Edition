# ---------------------------------------------------------------------------
# CH14 -- SYSMON on a Grove 16x2 LCD
# ---------------------------------------------------------------------------
# The Grove connector on the PL side of the AUP-ZU3. Same two pins CH14's
# original design used; carried here because pin constraints belong in
# constraints/pins.xdc and never in the source.
#
# The AXI IIC drives these through IOBUFs that the block design's wrapper
# infers from the iic_rtl interface port, which is why the port names end in
# _io rather than _i/_o/_t.
#
# No PULLUP is set. The Grove LCD module carries its own bus pull-ups, and
# adding weak internal ones on top changes the rise time for no benefit. If a
# bare panel with no pull-ups is ever wired here, that is the line to revisit.

set_property PACKAGE_PIN AD15 [get_ports {iic_display_io_scl_io}]
set_property PACKAGE_PIN AD14 [get_ports {iic_display_io_sda_io}]
set_property IOSTANDARD LVCMOS33 [get_ports {iic_display*}]

# VP/VN are DEDICATED analog pins (R13/T12 on this package) carrying the
# board's 10K potentiometer into SYSMON channel 3. Dedicated pins take no
# location constraint -- the Vp_Vn interface port binds to them by function.
