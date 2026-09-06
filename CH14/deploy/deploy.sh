#!/usr/bin/env bash
#
# Deploy CH14 -- the SYSMON on a Grove 16x2 LCD -- to an AUP-ZU3 running PYNQ.
#
#   ./deploy.sh                       # both destinations (see below)
#   ./deploy.sh --jupyter-only        # just the notebook tree
#   ./deploy.sh --harness-only        # just the test harness
#   ./deploy.sh --board 192.168.3.1 --user xilinx
#
# TWO DESTINATIONS, BECAUSE THEY ARE NOT INTERCHANGEABLE
#
#   ~/jupyter_notebooks/handbook/CH14   what Jupyter actually serves. A
#                                       notebook anywhere else is invisible in
#                                       the browser, however correct it is.
#                                       Layout mirrors the repository, with sw/
#                                       one level above project_sysmon_lcd/.
#
#   ~/ch14_sysmon_lcd                   a flat harness for running pytest over
#                                       ssh, with out/ pulled up beside sw/.
#                                       Nothing serves it and nothing should;
#                                       it exists so the tests run against the
#                                       interpreter the notebooks use.
#
# The notebook and sw/paths.py resolve sw/ and the artifacts by SEARCHING
# candidate relative paths, which is what lets one copy of each file work from
# both layouts. Do not "simplify" that to a fixed path.
#
# Nothing is started and nothing is reprogrammed; this only moves files. The
# notebook downloads the bitstream and starts the application itself.
#
# Prerequisites: SSH key auth to the board (ssh-copy-id), the hardware built
# (project_sysmon_lcd/build.tcl) and the application built (sw_mb/build_app.py).

set -euo pipefail

CH14="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
PROJECT="$CH14/project_sysmon_lcd"

BOARD=192.168.3.1
USER_NAME=xilinx
JUPYTER_DEST=/home/xilinx/jupyter_notebooks/handbook/CH14
HARNESS_DEST=/home/xilinx/ch14_sysmon_lcd
DO_JUPYTER=1
DO_HARNESS=1

usage() { sed -n '2,32p' "$0"; exit "${1:-0}"; }

while [ $# -gt 0 ]; do
    case "$1" in
        --board)        BOARD=$2; shift 2 ;;
        --user)         USER_NAME=$2; shift 2 ;;
        --jupyter-dest) JUPYTER_DEST=$2; shift 2 ;;
        --harness-dest) HARNESS_DEST=$2; shift 2 ;;
        --jupyter-only) DO_HARNESS=0; shift ;;
        --harness-only) DO_JUPYTER=0; shift ;;
        -h|--help)      usage 0 ;;
        *) echo "unknown option: $1" >&2; usage 1 ;;
    esac
done

# src | subdirectory under the harness | subdirectory under the Jupyter tree
#
# "-" means the file does not belong in that destination. The test suites go
# to the harness only: Jupyter needs what the notebook imports and nothing
# else.
#
# THE .hwh MUST TRAVEL WITH THE .bit AND KEEP ITS STEM. PYNQ pairs them by
# filename; without it Overlay() cannot build ip_dict and ch14.py cannot find
# a single one of the four windows.
#
# The .elf is an artifact like the other two -- it is what the notebook loads
# into the processor -- so it lives in out/ beside them rather than in sw/.
FILES=(
    "$PROJECT/out/ch14_sysmon_lcd.bit|out|project_sysmon_lcd/out"
    "$PROJECT/out/ch14_sysmon_lcd.hwh|out|project_sysmon_lcd/out"
    "$CH14/sw_mb/out/ch14_sysmon_lcd.elf|out|project_sysmon_lcd/out"
    "$PROJECT/notebooks/ch14_sysmon_lcd.ipynb|-|project_sysmon_lcd/notebooks"
    "$CH14/sw/ch14.py|sw|sw"
    "$CH14/sw/microblaze_v.py|sw|sw"
    "$CH14/sw/elf.py|sw|sw"
    "$CH14/sw/mailbox.py|sw|sw"
    "$CH14/sw/sysmon.py|sw|sw"
    "$CH14/sw/grove_lcd.py|sw|sw"
    "$CH14/sw/paths.py|sw|sw"
    "$CH14/sw/fake_mmio.py|sw|-"
    "$CH14/sw/test_on_board.py|sw|-"
    "$CH14/sw/test_elf.py|sw|-"
    "$CH14/sw/test_mailbox.py|sw|-"
    "$CH14/sw/test_microblaze_v.py|sw|-"
    "$CH14/sw/test_sysmon.py|sw|-"
    "$CH14/sw/test_grove_lcd.py|sw|-"
    "$CH14/sw/test_ch14.py|sw|-"
    "$CH14/sw/test_paths.py|sw|-"
)

field() { printf '%s' "$1" | cut -d'|' -f"$2"; }

echo "==> Checking the build is complete"
missing=0
for entry in "${FILES[@]}"; do
    src="$(field "$entry" 1)"
    if [ ! -f "$src" ]; then
        echo "missing $src" >&2
        missing=1
    fi
done
if [ "$missing" = 1 ]; then
    echo >&2
    echo "build what is missing first:" >&2
    echo "  vivado -mode batch -source project_sysmon_lcd/build.tcl   # .bit .hwh .xsa" >&2
    echo "  vitis  -s sw_mb/build_app.py                              # .elf" >&2
    exit 1
fi

# The application has to fit in the memory the bitstream provides, and the two
# are built by different tools that never check each other. Catching a
# mismatch here beats catching it as a processor that loads and does nothing.
echo "==> Checking the application fits the hardware"
python3 - "$CH14" <<'PY' || exit 1
import os, sys
ch14 = sys.argv[1]
sys.path.insert(0, os.path.join(ch14, "sw"))
import elf
image = open(os.path.join(ch14, "sw_mb", "out", "ch14_sysmon_lcd.elf"), "rb").read()
segments = elf.load_segments(image)
top = max(s.vaddr + s.memsz for s in segments)
if top > 64 * 1024:
    print(f"    the application needs {top} bytes; the hardware has 65536", file=sys.stderr)
    sys.exit(1)
if elf.symbol_address(image, "mailbox") is None:
    print("    the ELF exports no 'mailbox' symbol -- the notebook could not "
          "read anything back", file=sys.stderr)
    sys.exit(1)
print(f"    {top} of 65536 bytes used, mailbox symbol present")
PY

SSH_OPTS=(-o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new)
TARGET="$USER_NAME@$BOARD"

echo "==> Checking $TARGET is reachable"
ssh "${SSH_OPTS[@]}" -o BatchMode=yes "$TARGET" true 2>/dev/null || {
    echo "cannot reach $TARGET with key auth." >&2
    echo "  is the board powered up?   ping $BOARD" >&2
    echo "  set up a key:              ssh-copy-id $TARGET" >&2
    exit 1
}

# Can this account create the destination?
#
# /home/xilinx/jupyter_notebooks/handbook is root-owned and mode 755 on this
# board, so `xilinx` cannot create a chapter directory inside it -- the
# existing CH12 and CH13 were made with elevated rights. Without this check
# the failure arrives as three identical "mkdir: Permission denied" lines
# from inside a compound ssh command, which says nothing about the fix.
#
# The remedy is printed rather than performed. Creating a directory under
# another user's home with sudo is the operator's decision, not a deploy
# script's, and a script that quietly sudos is a script nobody can predict.
check_writable() {
    local root="$1"
    local parent
    parent="$(dirname "$root")"

    ssh "${SSH_OPTS[@]}" "$TARGET" "[ -d '$root' ] && [ -w '$root' ]" && return 0
    ssh "${SSH_OPTS[@]}" "$TARGET" "[ ! -e '$root' ] && [ -w '$parent' ]" && return 0

    echo "cannot write to $root on $TARGET" >&2
    ssh "${SSH_OPTS[@]}" "$TARGET" "ls -ld '$parent' '$root' 2>&1" >&2 || true
    echo >&2
    echo "create it once, as the operator:" >&2
    echo "  ssh $TARGET \"sudo mkdir -p '$root' && sudo chown -R $USER_NAME:$USER_NAME '$root'\"" >&2
    return 1
}

# deploy_to <root> <field index for the subdirectory>
deploy_to() {
    local root="$1" col="$2"
    local subdirs=() entry sub src

    for entry in "${FILES[@]}"; do
        sub="$(field "$entry" "$col")"
        [ "$sub" = "-" ] && continue
        case " ${subdirs[*]-} " in *" $sub "*) ;; *) subdirs+=("$sub") ;; esac
    done

    echo "==> Copying to $TARGET:$root"
    local mkdirs=""
    for sub in "${subdirs[@]}"; do
        mkdirs+="mkdir -p '$root/$sub'; "
    done
    ssh "${SSH_OPTS[@]}" "$TARGET" "$mkdirs"

    local group=()
    for sub in "${subdirs[@]}"; do
        group=()
        for entry in "${FILES[@]}"; do
            [ "$(field "$entry" "$col")" = "$sub" ] && group+=("$(field "$entry" 1)")
        done
        scp -q "${SSH_OPTS[@]}" "${group[@]}" "$TARGET:$root/$sub/"
        echo "    $sub/  ${#group[@]} files"
    done

    # The board has no RTC -- its clock is not even monotonic across reboots --
    # so file timestamps are meaningless here. Checksums are the only honest
    # check. Compared as a sorted multiset, independent of how the remote
    # md5sum prints its paths.
    echo "==> Verifying $root"
    local local_paths=() remote_paths=()
    for entry in "${FILES[@]}"; do
        sub="$(field "$entry" "$col")"
        [ "$sub" = "-" ] && continue
        src="$(field "$entry" 1)"
        local_paths+=("$src")
        remote_paths+=("$root/$sub/$(basename "$src")")
    done

    local local_sums remote_sums
    local_sums="$(md5sum "${local_paths[@]}" | awk '{print $1}' | sort)"
    remote_sums="$(ssh "${SSH_OPTS[@]}" "$TARGET" "md5sum ${remote_paths[*]}" \
                       | awk '{print $1}' | sort)"

    if [ "$local_sums" != "$remote_sums" ]; then
        echo "checksum mismatch under $root -- do not run it" >&2
        diff <(printf '%s\n' "$local_sums") <(printf '%s\n' "$remote_sums") >&2 || true
        exit 1
    fi
    echo "    ${#local_paths[@]} files, md5 OK"
}

echo "==> Checking the destinations can be written"
[ "$DO_JUPYTER" = 1 ] && check_writable "$JUPYTER_DEST"
[ "$DO_HARNESS" = 1 ] && check_writable "$HARNESS_DEST"

[ "$DO_JUPYTER" = 1 ] && deploy_to "$JUPYTER_DEST" 3
[ "$DO_HARNESS" = 1 ] && deploy_to "$HARNESS_DEST" 2

# Both of these silently ruin a run rather than failing it. Neither is touched
# here: stopping a service is the operator's call, not a deploy script's.
echo "==> Checking for things that fight the demonstration"
ssh "${SSH_OPTS[@]}" "$TARGET" '
    if systemctl is-active --quiet ch11-dp 2>/dev/null; then
        echo "    WARNING: ch11-dp is running. It drives CH11'"'"'s bitstream, so"
        echo "             reprogramming the PL points its register reads at"
        echo "             hardware that no longer exists."
        echo "             sudo systemctl stop ch11-dp"
    fi
    if [ -e /dev/i2c-0 ] && fuser /dev/i2c-* >/dev/null 2>&1; then
        echo "    WARNING: something holds an i2c device open. If the xiic"
        echo "             driver bound this core, it and the notebook will"
        echo "             both drive the bus and neither will work."
    fi
' 2>/dev/null || true

echo
echo "=========================================="
if [ "$DO_JUPYTER" = 1 ]; then
    echo " Notebook (this is what Jupyter serves):"
    echo "   handbook/CH14/project_sysmon_lcd/notebooks/ch14_sysmon_lcd.ipynb"
    echo
fi
if [ "$DO_HARNESS" = 1 ]; then
    echo " Tests:"
    echo "   ssh $TARGET 'cd $HARNESS_DEST/sw && \\"
    echo "     /usr/local/share/pynq-venv/bin/python3 -m pytest . -q'"
    echo
fi
echo " The panel stays BLANK until the notebook starts the application:"
echo " the processor powers up held in reset, by design."
echo "=========================================="
