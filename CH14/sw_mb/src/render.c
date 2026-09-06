#include "render.h"
#include "fmt.h"
#include "pages.h"

#include <string.h>

/* The row is sixteen characters and every layout below spends all of them.
 *
 *   Temp      42.0 C      4 label + 10 right-aligned + 2 unit
 *   VCCINT    0.851V      8 label + 7 right-aligned  + 1 unit
 *   Rng  41.2/ 44.1C      3 label + 6 + 1 + 5 + 1
 *
 * Right-aligning the numbers is what stops the decimal point walking across
 * the panel as a value crosses ten, which is far more distracting on a
 * two-line display than it sounds.
 */
#define TEMP_LABEL_W  4
#define TEMP_VALUE_W  10
#define RAIL_LABEL_W  8
#define RAIL_VALUE_W  7

static void row_too_small(char *out, size_t cap)
{
    if (out != NULL && cap > 0)
        out[0] = '\0';
}

/* Append `src` to `out`, which already holds `*len` characters. The caller
 * has checked the total fits. */
static void append(char *out, size_t *len, const char *src)
{
    while (*src != '\0')
        out[(*len)++] = *src++;
}

static void append_fixed(char *out, size_t *len, int32_t value,
                         unsigned value_decimals, unsigned show_decimals,
                         size_t width)
{
    char number[24];
    char field[24];

    if (fmt_fixed(number, sizeof number, value, value_decimals, show_decimals) < 0 ||
        fmt_pad_left(field, sizeof field, number, width) < 0) {
        /* Cannot happen with the values this application produces, and the
         * tests cover the extremes. Filling the field keeps the row the right
         * width rather than silently shortening it if it ever does. */
        for (size_t i = 0; i < width; i++)
            out[(*len)++] = '?';
        return;
    }
    append(out, len, field);
}

void render_top(char *out, size_t cap, const readings_t *r)
{
    size_t len = 0;

    if (cap < RENDER_BUF) {
        row_too_small(out, cap);
        return;
    }
    append(out, &len, "Temp");
    append_fixed(out, &len, r->temperature_mc, 3, 1, TEMP_VALUE_W);
    append(out, &len, " C");
    out[len] = '\0';
}

/* Label and microvolt field for the four rail pages, indexed by page_t. */
static const char *rail_label(int page)
{
    switch (page) {
    case PAGE_VCCINT:  return "VCCINT";
    case PAGE_VCCAUX:  return "VCCAUX";
    case PAGE_VCCBRAM: return "VBRAM";
    case PAGE_POT:     return "Pot";
    /* Unreachable: render_bottom clamps the page and handles
     * PAGE_TEMP_RANGE before it gets here. A label rather than NULL anyway,
     * because a new page added to pages.h would otherwise reach fmt_pad as a
     * null pointer, and this application has no way to report a crash. */
    default:           return "?";
    }
}

static uint32_t rail_value(const readings_t *r, int page)
{
    switch (page) {
    case PAGE_VCCINT:  return r->vccint_uv;
    case PAGE_VCCAUX:  return r->vccaux_uv;
    case PAGE_VCCBRAM: return r->vccbram_uv;
    default:           return r->pot_uv;
    }
}

void render_bottom(char *out, size_t cap, const readings_t *r, int page)
{
    char label[RENDER_BUF];
    size_t len = 0;

    if (cap < RENDER_BUF) {
        row_too_small(out, cap);
        return;
    }

    /* page_select cannot return a value outside the range, so this clamp is
     * defence rather than a case that happens. It is here because the cost is
     * one comparison and the alternative is indexing a table off its end on a
     * processor with no memory protection and no console. */
    if (page < 0 || page >= PAGE_COUNT)
        page = PAGE_VCCINT;

    if (page == PAGE_TEMP_RANGE) {
        append(out, &len, "Rng");
        append_fixed(out, &len, r->temp_min_mc, 3, 1, 6);
        append(out, &len, "/");
        append_fixed(out, &len, r->temp_max_mc, 3, 1, 5);
        append(out, &len, "C");
        out[len] = '\0';
        return;
    }

    fmt_pad(label, sizeof label, rail_label(page), RAIL_LABEL_W);
    append(out, &len, label);
    /* Microvolts shown to the millivolt: the rails are specified to about
     * that, and a fourth digit would be the ADC's noise rather than the
     * board's. */
    append_fixed(out, &len, (int32_t)rail_value(r, page), 6, 3, RAIL_VALUE_W);
    append(out, &len, "V");
    out[len] = '\0';
}

void render_sysmon_fault(char *top, char *bottom, size_t cap)
{
    if (cap < RENDER_BUF) {
        row_too_small(top, cap);
        row_too_small(bottom, cap);
        return;
    }
    /* Naming the part that failed matters more here than anywhere else: this
     * panel is the only output this design has, so "no SYSMON" and "no panel"
     * have to look different, and one of them can only be reported by the
     * other still working. */
    fmt_pad(top,    cap, "SYSMON not found", LCD_COLS);
    fmt_pad(bottom, cap, "Check bitstream",  LCD_COLS);
}
