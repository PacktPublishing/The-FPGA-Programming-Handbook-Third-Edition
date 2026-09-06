# ---------------------------------------------------------------------------
# CH14 -- the SYSMON on a Grove 16x2 LCD, driven by a MicroBlaze-V
#
#   vivado -mode batch -source project_sysmon_lcd/build.tcl
#   vivado -mode batch -source project_sysmon_lcd/build.tcl -tclargs bd_only
#
# WHAT THIS BUILDS ON
#
# CH14 already ships a block design: ../build/bd/hw.tcl, a write_bd_tcl dump
# carrying a MicroBlaze-V, an AXI IIC on the Grove connector, a System
# Management Wizard, and a Zynq MPSoC whose entire job is to supply pl_clk0
# and pl_resetn0. That file is GENERATED and is not edited. This script
# sources it to get the design and the PS's thousand-line MIO configuration,
# then applies its changes on top, so every difference from the original is
# one visible command here rather than a diff against machine output.
#
# WHY THERE ARE CHANGES AT ALL
#
# The original design has no AXI master from the PS into the PL:
# PSU__USE__M_AXI_GP0/1/2 are all 0, and the .hwh confirms zynq_ultra_ps_e_0
# has zero AXI interfaces. A PYNQ notebook can therefore call Overlay() and
# nothing else -- it cannot put the application into the MicroBlaze's memory,
# cannot start or stop the processor, and cannot read a register to check any
# of it worked. Everything below exists to fix that, plus the 16 KB of local
# memory that the application does not fit in.
# ---------------------------------------------------------------------------

set script_dir [file normalize [file dirname [info script]]]
set ch14_root  [file normalize [file join $script_dir ..]]

set bd_only 0
foreach a [lrange $argv 0 end] {
    switch -- $a {
        bd_only { set bd_only 1 }
        default { error "unknown option '$a' -- expected bd_only" }
    }
}

set part      {xczu3eg-sfvc784-2-e}
set proj_name ch14_sysmon_lcd
set proj_dir  [file join $script_dir vivado]
set out_dir   [file join $script_dir out]
set bd_name   hw
set base_bd   [file join $ch14_root build bd hw.tcl]

# ---------------------------------------------------------------------------
# The address map, in one place
# ---------------------------------------------------------------------------
# TWO MASTERS SEE THE SAME SLAVES AT DIFFERENT ADDRESSES, which is normal and
# is worth stating once rather than rediscovering in the driver.
#
# The MicroBlaze keeps the addresses the original design gave it, because the
# application is compiled against them and there is no reason to move them.
set mb_lmb_base    0x00000000
set mb_lmb_range   64K
set mb_iic_base    0x40800000
set mb_sysmon_base 0x44A00000

# The PS reaches the PL through M_AXI_HPM0_LPD, whose aperture begins at
# 0x80000000 -- the same window CH13 used, for the same reason: it is the
# first valid one through that master.
set ps_bram_base   0x80000000
set ps_ctrl_base   0x80010000
set ps_iic_base    0x80020000
set ps_sysmon_base 0x80030000

# 64 KB of local memory, up from the original 16 KB.
#
# 16 KB is not a budget the application can be squeezed into, it is a wall:
# the Vitis BSP's XIic alone is around 20 KB before any SYSMON code or
# formatting. 64 KB costs 16 RAMB36 of the 216 on this device -- about 7% --
# and leaves room to add to the application without another bitstream.
set lmb_bytes 65536

file mkdir $out_dir
file delete -force $proj_dir

create_project $proj_name $proj_dir -part $part -force

add_files -fileset constrs_1 -norecurse [file join $script_dir constraints pins.xdc]

# ---------------------------------------------------------------------------
# The design as CH14 shipped it
# ---------------------------------------------------------------------------
# hw.tcl creates a project only if none is open, and a block design only if
# one of that name is not already in the project. With the project above
# already created and empty, it takes the "no opened design, design_name not
# in project" path and simply builds "hw" here.
if {![file exists $base_bd]} {
    error "cannot find the base block design at $base_bd"
}
puts "\n==> Building CH14's original block design from build/bd/hw.tcl"
source $base_bd

current_bd_design [get_bd_designs $bd_name]

# ---------------------------------------------------------------------------
# 1. Give the PS a way into the PL
# ---------------------------------------------------------------------------
# GP2 is M_AXI_HPM0_LPD on ZynqMP (GP0 and GP1 are the two FPD masters). The
# check below is not ceremony: the PSU parameter names carry no hint of which
# physical port they enable, so the only honest confirmation is that the pin
# now exists.
puts "\n==> Enabling M_AXI_HPM0_LPD on the PS"
set_property -dict [list \
    CONFIG.PSU__USE__M_AXI_GP2      {1} \
    CONFIG.PSU__MAXIGP2__DATA_WIDTH {32} \
] [get_bd_cells zynq_ultra_ps_e_0]

if {[llength [get_bd_intf_pins -quiet zynq_ultra_ps_e_0/M_AXI_HPM0_LPD]] != 1} {
    error "PSU__USE__M_AXI_GP2 did not produce M_AXI_HPM0_LPD -- the PS still\
           has no master into the PL, so nothing downstream of here is valid."
}

# ---------------------------------------------------------------------------
# 2. Free a BRAM port for the PS, and grow the memory
# ---------------------------------------------------------------------------
# A blk_mem_gen has two ports. The original design spends both of them:
# BRAM_PORTA on the data LMB controller and BRAM_PORTB on the instruction LMB
# controller. There is no third port to hang an axi_bram_ctrl off, which is
# the obstacle that makes this look impossible.
#
# It is not, because lmb_bram_if_cntlr has C_NUM_LMB, and it goes to 8. ONE
# controller can serve BOTH LMB buses through a SINGLE BRAM port, which is
# exactly what PYNQ's own IOP subsystems do. That frees BRAM_PORTB for the PS
# and costs nothing but an arbitration slot the processor was already taking
# serially anyway.
puts "\n==> Merging the two LMB controllers into one, freeing BRAM_PORTB"
current_bd_instance /microblaze_riscv_0_local_memory

delete_bd_objs [get_bd_cells ilmb_bram_if_cntlr]

# Renamed because its role changed. It is no longer the data-side controller;
# it is the only controller, and calling it dlmb_* would be a lie that the
# next person has to read the connections to catch.
set_property NAME lmb_bram_if_cntlr [get_bd_cells dlmb_bram_if_cntlr]
set_property CONFIG.C_NUM_LMB {2} [get_bd_cells lmb_bram_if_cntlr]

# SLMB is the data bus, already connected. SLMB1 is the instruction bus,
# whose lmb_v10 lost its controller when ilmb_bram_if_cntlr was deleted.
connect_bd_intf_net [get_bd_intf_pins ilmb_v10/LMB_Sl_0] \
                    [get_bd_intf_pins lmb_bram_if_cntlr/SLMB1]

# ilmb_v10 keeps the LMB_Clk and SYS_Rst it already had: deleting a cell
# removes only that cell's own connections, not the nets themselves.

# BRAM_PORTB now goes nowhere. Bring it out of the hierarchy so the PS-facing
# controller can sit at the top level with the rest of the AXI slaves, where
# it belongs -- it is a peripheral of the PS, not part of the processor's
# local memory.
create_bd_intf_pin -mode Slave -vlnv xilinx.com:interface:bram_rtl:1.0 BRAM_PORTB
connect_bd_intf_net [get_bd_intf_pins BRAM_PORTB] \
                    [get_bd_intf_pins lmb_bram/BRAM_PORTB]

current_bd_instance /

# ---------------------------------------------------------------------------
# 3. The PS's window into the processor's memory
# ---------------------------------------------------------------------------
# SINGLE_PORT_BRAM 1 because this controller drives only one side of a memory
# whose other side belongs to the LMB. Left at 0 it would expose a second
# BRAM port with nothing to connect it to.
puts "\n==> Adding the PS-side BRAM controller"
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_bram_ctrl mb_bram_ctrl
set_property -dict [list \
    CONFIG.SINGLE_PORT_BRAM   {1} \
    CONFIG.DATA_WIDTH         {32} \
    CONFIG.PROTOCOL           {AXI4} \
    CONFIG.ECC_TYPE           {0} \
] [get_bd_cells mb_bram_ctrl]

connect_bd_intf_net [get_bd_intf_pins mb_bram_ctrl/BRAM_PORTA] \
                    [get_bd_intf_pins microblaze_riscv_0_local_memory/BRAM_PORTB]

# ---------------------------------------------------------------------------
# 4. A way to stop and start the processor
# ---------------------------------------------------------------------------
# Writing an application into memory underneath a running processor produces
# whatever the half-written program happens to do. The PS needs to hold the
# MicroBlaze in reset first.
#
# THE GPIO RESETS THE PROCESSOR AND NOTHING ELSE. The obvious alternative --
# driving the proc_sys_reset's aux_reset_in -- also resets the peripherals,
# the interconnect and the local-memory controllers, which means resetting the
# path the PS is writing the application through, and the memory it is writing
# it into. So the GPIO is OR-ed into the processor's own Reset pin instead,
# and everything else stays up.
#
# C_DOUT_DEFAULT 1 holds the processor in reset from the moment the bitstream
# lands. Without it the MicroBlaze starts executing an all-zero BRAM the
# instant proc_sys_reset lets go, which on RISC-V is an illegal instruction
# and a trap loop. The cost is that this design does nothing until software
# releases it -- loading the overlay alone leaves the panel blank, by design.
puts "\n==> Adding the processor reset control"
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_gpio mb_ctrl
set_property -dict [list \
    CONFIG.C_GPIO_WIDTH   {1} \
    CONFIG.C_ALL_OUTPUTS  {1} \
    CONFIG.C_IS_DUAL      {0} \
    CONFIG.C_DOUT_DEFAULT {0x00000001} \
] [get_bd_cells mb_ctrl]

# The inline-HDL OR rather than xilinx.com:ip:util_vector_logic, which 2025.2
# announces it will stop supporting. Same ports, no packaged IP to generate.
create_bd_cell -type inline_hdl -vlnv xilinx.com:inline_hdl:ilvector_logic mb_reset_or
set_property -dict [list \
    CONFIG.C_OPERATION {or} \
    CONFIG.C_SIZE      {1} \
] [get_bd_cells mb_reset_or]

# microblaze_riscv_0/Reset was driven straight from proc_sys_reset. Break that
# and route it through the OR instead.
delete_bd_objs [get_bd_nets rst_clk_wiz_1_100M_mb_reset]
connect_bd_net [get_bd_pins rst_clk_wiz_1_100M/mb_reset] [get_bd_pins mb_reset_or/Op1]
# Connecting gpio_io_o rather than the GPIO interface draws
#   WARNING: [BD 41-1306] The connection to interface pin </mb_ctrl/gpio_io_o>
#            is being overridden by the user with net <mb_ctrl_gpio_io_o>
# which is Vivado noting that write_bd_tcl could not reproduce this. It is
# inherent to driving fabric from an AXI GPIO -- the pin lives inside an
# interface bundle -- and this design is rebuilt from THIS script, not from a
# write_bd_tcl dump, so the thing it warns about cannot happen here.
connect_bd_net [get_bd_pins mb_ctrl/gpio_io_o]           [get_bd_pins mb_reset_or/Op2]
connect_bd_net [get_bd_pins mb_reset_or/Res]             [get_bd_pins microblaze_riscv_0/Reset]

# ---------------------------------------------------------------------------
# 5. Both masters onto one interconnect
# ---------------------------------------------------------------------------
# An AXI slave takes one connection, and axi_iic_0 and the SYSMON already
# belong to the MicroBlaze's SmartConnect. Rather than give the PS a second
# interconnect and duplicate slaves it cannot have, the existing SmartConnect
# gains a second slave port. Each master then gets its own address space over
# the same four peripherals, which is why the PS and the MicroBlaze see the
# IIC at different addresses.
#
# The PS reading the SYSMON while the application reads it too is safe: both
# are DRP reads through the wizard's own bridge, which arbitrates them. The
# IIC is not -- two masters driving one I2C controller interleave transactions
# into nonsense -- so the notebook only touches the IIC with the processor
# held in reset. That is a software rule; the hardware cannot enforce it.
puts "\n==> Widening the SmartConnect to two masters and four slaves"
set_property -dict [list \
    CONFIG.NUM_SI {2} \
    CONFIG.NUM_MI {4} \
] [get_bd_cells microblaze_riscv_0_axi_periph]

connect_bd_intf_net [get_bd_intf_pins zynq_ultra_ps_e_0/M_AXI_HPM0_LPD] \
                    [get_bd_intf_pins microblaze_riscv_0_axi_periph/S01_AXI]
connect_bd_intf_net [get_bd_intf_pins microblaze_riscv_0_axi_periph/M02_AXI] \
                    [get_bd_intf_pins mb_bram_ctrl/S_AXI]
connect_bd_intf_net [get_bd_intf_pins microblaze_riscv_0_axi_periph/M03_AXI] \
                    [get_bd_intf_pins mb_ctrl/S_AXI]

# One clock domain for everything, including the PS's AXI port: the
# SmartConnect crosses no clocks, so the PS master has to run on the same
# 100 MHz the rest of the PL does.
set pl_clk [get_bd_pins clk_wiz_1/clk_out1]
set pl_rstn [get_bd_pins rst_clk_wiz_1_100M/peripheral_aresetn]
foreach p {zynq_ultra_ps_e_0/maxihpm0_lpd_aclk mb_bram_ctrl/s_axi_aclk mb_ctrl/s_axi_aclk} {
    connect_bd_net $pl_clk [get_bd_pins $p]
}
foreach p {mb_bram_ctrl/s_axi_aresetn mb_ctrl/s_axi_aresetn} {
    connect_bd_net $pl_rstn [get_bd_pins $p]
}

# ---------------------------------------------------------------------------
# 6. Two corrections to the original design
# ---------------------------------------------------------------------------
# clk_in1 is driven by pl_clk0, an internal net, but PRIM_SOURCE says the
# input arrives on a clock-capable PIN. That asks the clocking wizard for an
# input buffer on a signal that never leaves the die. It survived
# implementation, but "No_buffer" is what an internally-driven input is.
puts "\n==> Correcting the clocking wizard's input buffer"
set_property CONFIG.PRIM_SOURCE {No_buffer} [get_bd_cells clk_wiz_1]

# The MDM's Debug_SYS_Rst was wired to the clocking wizard's reset as well as
# to the proc_sys_reset. That was harmless while the PL stood alone. It is not
# now: a debug reset over JTAG would drop clk_out1, which is the clock the
# PS's own AXI master runs on, stalling a transaction the PS has no way to
# recover. The debug reset keeps its proper job and loses that one.
#
# The reset port then goes away entirely rather than being tied off. pl_clk0
# is already stable and running by the time the PL is configured, so there is
# nothing for a reset to do here, and clk_wiz's reset is active HIGH while the
# only reset available is active low -- a tie-off would need an inverter to
# express "never reset".
puts "==> Detaching the debug reset from the clocking wizard"
disconnect_bd_net [get_bd_nets mdm_1_debug_sys_rst] [get_bd_pins clk_wiz_1/reset]
set_property CONFIG.USE_RESET {false} [get_bd_cells clk_wiz_1]

# ---------------------------------------------------------------------------
# 7. SYSMON averaging
# ---------------------------------------------------------------------------
# The wizard's defaults already had the sequencer and timing on Continuous and
# the right channels enabled, which is why the original design's SYSMON needed
# no help. Averaging is the one thing missing, and it is missing for a reason
# that only appears once a display is attached: an unaveraged 10-bit reading
# moves by a code or two between conversions, and on a 16x2 panel refreshing
# several times a second that shows up as digits that will not settle.
#
# 16 samples at 200 ksps costs well under a millisecond, which nothing here
# can perceive.
puts "\n==> Enabling 16-sample averaging on temperature and VP/VN"
set_property -dict [list \
    CONFIG.CHANNEL_AVERAGING             {16} \
    CONFIG.AVERAGE_ENABLE_TEMPERATURE    {true} \
    CONFIG.AVERAGE_ENABLE_VCCINT         {true} \
    CONFIG.AVERAGE_ENABLE_VCCAUX         {true} \
    CONFIG.AVERAGE_ENABLE_VBRAM          {true} \
    CONFIG.AVERAGE_ENABLE_VP_VN          {true} \
] [get_bd_cells system_management_wiz_0]

# ---------------------------------------------------------------------------
# 8. Addresses
# ---------------------------------------------------------------------------
puts "\n==> Assigning addresses"

# The original design's two LMB segments were named after the controllers that
# owned them, one of which no longer exists. Deleting them first means the
# reassignment below names them for what is actually there, rather than
# leaving the data side pointing at a SEG_dlmb_bram_if_cntlr_Mem whose
# controller was merged away.
delete_bd_objs [get_bd_addr_segs -quiet microblaze_riscv_0/Data/SEG_dlmb_bram_if_cntlr_Mem]
delete_bd_objs [get_bd_addr_segs -quiet microblaze_riscv_0/Instruction/SEG_ilmb_bram_if_cntlr_Mem]

set mb_data [get_bd_addr_spaces microblaze_riscv_0/Data]
set mb_inst [get_bd_addr_spaces microblaze_riscv_0/Instruction]
set ps_data [get_bd_addr_spaces zynq_ultra_ps_e_0/Data]

# The processor's own map. The local memory is now one controller with two
# LMB ports, so it presents two segments -- SLMB to the data space and SLMB1
# to the instruction space -- both covering the same 64 KB at zero.
assign_bd_address -offset $mb_lmb_base -range $mb_lmb_range \
    -target_address_space $mb_data \
    [get_bd_addr_segs microblaze_riscv_0_local_memory/lmb_bram_if_cntlr/SLMB/Mem] -force
assign_bd_address -offset $mb_lmb_base -range $mb_lmb_range \
    -target_address_space $mb_inst \
    [get_bd_addr_segs microblaze_riscv_0_local_memory/lmb_bram_if_cntlr/SLMB1/Mem] -force
assign_bd_address -offset $mb_iic_base -range 64K \
    -target_address_space $mb_data [get_bd_addr_segs axi_iic_0/S_AXI/Reg] -force
assign_bd_address -offset $mb_sysmon_base -range 64K \
    -target_address_space $mb_data \
    [get_bd_addr_segs system_management_wiz_0/S_AXI_LITE/Reg] -force

# The PS's map. mb_bram_ctrl's range IS the memory's size -- axi_bram_ctrl
# takes its depth from the address segment, so this line and the LMB range
# above have to agree or the PS sees a different amount of memory than the
# processor does.
assign_bd_address -offset $ps_bram_base -range $mb_lmb_range \
    -target_address_space $ps_data [get_bd_addr_segs mb_bram_ctrl/S_AXI/Mem0] -force
assign_bd_address -offset $ps_ctrl_base -range 64K \
    -target_address_space $ps_data [get_bd_addr_segs mb_ctrl/S_AXI/Reg] -force
assign_bd_address -offset $ps_iic_base -range 64K \
    -target_address_space $ps_data [get_bd_addr_segs axi_iic_0/S_AXI/Reg] -force
assign_bd_address -offset $ps_sysmon_base -range 64K \
    -target_address_space $ps_data \
    [get_bd_addr_segs system_management_wiz_0/S_AXI_LITE/Reg] -force

# THE MICROBLAZE IS DELIBERATELY DENIED TWO OF THE FOUR SLAVES.
#
# Both are reachable from its master port, so leaving them unassigned draws
#   CRITICAL WARNING: [BD 41-1356] Slave segment </mb_ctrl/S_AXI/Reg> is not
#                     assigned into address space </microblaze_riscv_0/Data>
# and, worse, invites a later validate to assign them somewhere arbitrary.
# Excluding them says the omission is a decision:
#
#   mb_bram_ctrl  is a second door onto the memory the processor already has
#                 through its LMB. Two paths to one memory, one of them
#                 uncached and the other not, is a coherency question nobody
#                 needs to answer here.
#   mb_ctrl       holds the processor's own reset. A processor that can assert
#                 its own reset can stop and never restart, with no way in.
exclude_bd_addr_seg -target_address_space $mb_data [get_bd_addr_segs mb_bram_ctrl/S_AXI/Mem0]
exclude_bd_addr_seg -target_address_space $mb_data [get_bd_addr_segs mb_ctrl/S_AXI/Reg]

validate_bd_design
save_bd_design

# ---------------------------------------------------------------------------
# Report what was actually built
# ---------------------------------------------------------------------------
# A CONFIG value that the IP quietly rejected looks identical to one that took
# effect, until the board disagrees. Printing them back is the cheap check.
puts "\n==> Built configuration"
puts [format "    %-38s %s" "local memory" \
      "[expr {$lmb_bytes / 1024}] KB at $mb_lmb_base"]
foreach {cell props} [list \
    system_management_wiz_0 {SEQUENCER_MODE TIMING_MODE CHANNEL_AVERAGING \
                             AVERAGE_ENABLE_TEMPERATURE AVERAGE_ENABLE_VP_VN \
                             CHANNEL_ENABLE_VP_VN BIPOLAR_VP_VN} \
    microblaze_riscv_0_local_memory/lmb_bram_if_cntlr {C_NUM_LMB} \
    mb_bram_ctrl {SINGLE_PORT_BRAM DATA_WIDTH} \
    mb_ctrl {C_GPIO_WIDTH C_ALL_OUTPUTS C_DOUT_DEFAULT} \
    clk_wiz_1 {PRIM_SOURCE} \
    microblaze_riscv_0_axi_periph {NUM_SI NUM_MI}] {
    puts "    $cell"
    foreach p $props {
        puts [format "      %-36s %s" $p [get_property CONFIG.$p [get_bd_cells $cell]]]
    }
}

puts "\n==> Address map"
foreach space [list $mb_inst $mb_data $ps_data] {
    puts "    [get_property NAME $space] ([get_property PATH $space])"
    foreach seg [get_bd_addr_segs -of_objects $space] {
        puts [format "      %-58s %s +%s" [get_property NAME $seg] \
              [get_property OFFSET $seg] [get_property RANGE $seg]]
    }
}
puts ""

if {$bd_only} {
    puts "==> bd_only: block design validated, stopping before synthesis."
    return
}

# ---------------------------------------------------------------------------
# Implement
# ---------------------------------------------------------------------------
make_wrapper -files [get_files $bd_name.bd] -top -import

launch_runs impl_1 -to_step write_bitstream -jobs 8
wait_on_run impl_1

if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} {
    error "implementation did not finish -- see [file join $proj_dir $proj_name.runs impl_1 runme.log]"
}

open_run impl_1

# The bitstream is worthless if the design did not close timing, and a
# bitstream that exists is not evidence that it did.
set wns [get_property SLACK [get_timing_paths -delay_type max]]
set whs [get_property SLACK [get_timing_paths -delay_type min]]
puts "\n==> Timing: WNS $wns ns, WHS $whs ns"
if {$wns < 0 || $whs < 0} {
    error "the design does not meet timing (WNS $wns, WHS $whs) -- not shipping this bitstream"
}

# The SYSMONE4 has to be in the implemented design. CH13 spent a day on a
# vendor overlay whose SYSMON was placed and silently not converting, so the
# cheap structural check is worth keeping.
set sysmon_cells [get_cells -hierarchical -filter {REF_NAME =~ SYSMONE4*}]
if {[llength $sysmon_cells] != 1} {
    error "expected exactly one SYSMONE4 in the implemented design, found [llength $sysmon_cells]"
}
puts "==> SYSMONE4 placed: [get_property LOC [lindex $sysmon_cells 0]]"

# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------
# Three files, and all three are needed:
#   .bit  the bitstream PYNQ downloads
#   .hwh  the metadata PYNQ parses to build ip_dict -- it MUST sit next to the
#         .bit with the same stem or Overlay() will not find it
#   .xsa  what Vitis builds the platform and the BSP from
set stem [file join $out_dir $proj_name]

write_hw_platform -fixed -include_bit -force ${stem}.xsa
file copy -force [file join $proj_dir $proj_name.runs impl_1 ${bd_name}_wrapper.bit] ${stem}.bit

set hwh [glob -nocomplain [file join $proj_dir $proj_name.gen sources_1 bd $bd_name hw_handoff $bd_name.hwh]]
if {[llength $hwh] != 1} {
    error "expected exactly one .hwh handoff, found: $hwh"
}
file copy -force [lindex $hwh 0] ${stem}.hwh

puts "\n=========================================="
puts " out/[file tail ${stem}].bit  .hwh  .xsa"
puts ""
puts " Next: build the application against the XSA"
puts "   python3 sw_mb/build_app.py"
puts "=========================================="
