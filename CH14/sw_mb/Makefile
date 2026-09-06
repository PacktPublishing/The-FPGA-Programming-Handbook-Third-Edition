# Host-native build of the MicroBlaze-V drivers, for testing them on a
# workstation instead of on the board.
#
# The point is not convenience. This design has NO UART -- not on the MDM, not
# an axi_uartlite -- so a fault in the application shows up as a blank panel
# and nothing else. Everything that can be settled before the code reaches the
# board has to be, and register-level logic against a fake register space is
# almost all of it.
#
#   make test        build and run every suite
#   make clean
#
# The same .c files are compiled by build_app.py for the board. MB_HOST_TEST
# swaps only mmio.h's two accessors and the delay, which is the boundary --
# and the only thing faked.

CC      ?= cc
CFLAGS  := -std=c11 -O1 -g -Wall -Wextra -Werror -Wconversion -Wshadow \
           -Wstrict-prototypes -Wmissing-prototypes -Wpointer-arith \
           -Wcast-qual -Wundef -Wwrite-strings \
           -fsanitize=address,undefined -fno-omit-frame-pointer \
           -DMB_HOST_TEST -Isrc -Itest

SRC     := src/axi_iic.c src/grove_lcd.c src/sysmon.c src/fmt.c src/pages.c \
           src/render.c
FAKE    := test/fake_mmio.c
SUITES  := test_sysmon test_axi_iic test_grove_lcd test_fmt test_pages test_render
BIN     := $(addprefix build/,$(SUITES))

.PHONY: test clean
test: $(BIN)
	@fail=0; \
	for t in $(BIN); do \
	    echo "== $$t"; \
	    ./$$t || fail=1; \
	done; \
	exit $$fail

build/%: test/%.c $(SRC) $(FAKE) | build
	$(CC) $(CFLAGS) -o $@ $< $(SRC) $(FAKE)

build:
	@mkdir -p build

clean:
	rm -rf build
