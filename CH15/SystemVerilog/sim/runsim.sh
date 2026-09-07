rm -rf xsim*
xvlog -sv ../hdl/debounce.sv \
      ../hdl/ps2_intf.sv \
      ../hdl/ps2_host.sv \
      ../tb/tb_ps2.sv
xelab --timescale 1ns/10ps -debug typical tb_ps2
xsim tb_ps2 -gui -log xsim.log -view tb_ps2.wcfg
