#ifndef PLAT_H
#define PLAT_H

/* clk_wiz_1 divides the PS's 95.4545 MHz pl_clk0 up to 100 MHz, and that is
 * what clocks the processor, the interconnect, the IIC and the SYSMON's
 * DCLK. If build.tcl's clock ever changes, this changes with it -- every
 * delay in the application is derived from it. */
#define PLAT_CPU_HZ 100000000u

/* The two peripherals, as the MicroBlaze sees them. The PS sees the same two
 * at different addresses; see build.tcl's address map. */
#define IIC_BASE_ADDR    0x40800000u
#define SYSMON_BASE_ADDR 0x44A00000u

#endif /* PLAT_H */
