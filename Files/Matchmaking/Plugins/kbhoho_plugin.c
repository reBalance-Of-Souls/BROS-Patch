/* ====================================================================
 *  kbhoho_plugin.c -- ReBalanceOfSouls\kbhoho.dll
 *
 *  Keyboard + mouse get the Hoho (flash step) the way a pad does.
 *
 *  THE REPORT (2026-09-25)
 *  -----------------------
 *  "The Spiritual Pressure trigger activates 3 frames late on keyboard +
 *  mouse." Ichigo (TYBW)'s sig -> light -> hoho passes every time on a
 *  pad and 2 times out of 10 on keyboard, offline.
 *
 *  WHAT WAS MEASURED (kbprobe.dll, Files/Matchmaking/kbprobe_plugin.c)
 *  -------------------------------------------------------------------
 *  The trigger is NOT late. Per frame the game polls DirectInput
 *  (0xA1FFC0), rebuilds its key table (exe+0x18D7BA0, 0x0EEDA0 called at
 *  0x88FDF6) and then runs BrainPad::vfunc2, all on one thread: Tab
 *  produces cmd 0x20 on the frame it goes down, Tab+X produces the Hoho
 *  (cmd 0x16) on the frame X goes down.
 *
 *  The difference is in what BrainPad::vfunc2 does on the RELEASE of the
 *  Hoho button while the trigger is held. BrainPad reads the pad bits and,
 *  on pad 0 only, the keyboard key table, in two separate code paths:
 *
 *    pad       release -> the "tap" path (the `bl` flag at 0x4125E8, the
 *              site PART 20 hooks) emits the Hoho AGAIN: [03,20,16,28]
 *    keyboard  release -> only the step logic sees it:   [03,20]
 *
 *  The keyboard path tests the Hoho key's pressed edge (0x3000) and never
 *  its release. So a Hoho pressed a frame or two before the fighter can
 *  act is lost on keyboard, and the step that comes with the release is
 *  all that is left; on a pad the release asks for the Hoho a second time.
 *  In the user's 10 attempts every X release while Tab was held gave
 *  [03,20] and nothing else.
 *
 *  THE FIX
 *  -------
 *  Around BrainPad::vfunc2 (its vtable slot, 0x142C048 + 2*8), on pad 0:
 *  on the frame the Hoho key's release edge is set while the SP trigger
 *  key is held, the Hoho key's entry in the key table also gets its
 *  pressed-edge bit for the length of the call, and the entry is put back
 *  exactly as it was afterwards. The game's own keyboard path then emits
 *  what the pad path emits on that frame -- the step from the release AND
 *  the Hoho with its own direction bytes -- so no command is built here and
 *  the command vector is never touched.
 *
 *  Nothing changes when the trigger is not held, when both keys are
 *  released on the same frame (the pad's trigger is not held then either),
 *  or on a pad.
 *
 *  Written as offline only: the key table is local to this machine. (Rig
 *  #213, 2026-09-27, measured that the local player's BrainPad::vfunc2 does
 *  run every frame in an online battle, so this path may apply online too;
 *  the keyboard case was not tested there.)
 *
 *  SECOND FIX, THE PAD (2026-09-27): A HOHO BUTTON THAT IS ALSO AN ATTACK
 *  ----------------------------------------------------------------------
 *  The report: Custom scheme (Signature Move on A, Hoho = SP trigger + A,
 *  SP2 = SP trigger + B). Hold guard, input the Hoho, and SP2 comes out.
 *  Type A (A = Step/Dash) gives nothing until guard is released, then the
 *  Hoho. Open since 2026-08-31 (DataChakka "Custom Scheme SP2", five dead
 *  ends, every one of them a veto on an emission).
 *
 *  Read from the exe, not guessed:
 *  - BrainPad's masks (+0xCC..+0x10C) come from the binding table
 *    exe+0x1CE8380 (P2 +0x1CE8A10): 5 schemes x 28 entries x {f0,f1,f2},
 *    one entry per Input Settings row (0 Quick .. 11 Hoho, 12 Awakening).
 *    An SP-trigger combo is f0 = trigger, f1 = face button. The bits are
 *    the named pad buttons (_PAD_B_ 0x10, _Y_ 0x20, _X_ 0x40, _A_ 0x80 ...).
 *  - The attack commands are LEVEL-triggered on the held mask and never
 *    look at the trigger: [bp+0xD0] -> 5 Quick, +0xD4 -> 6 Flash, +0xD8 ->
 *    8 Breaker, +0xDC -> 7 Signature, +0xFC -> 0x22 Kikon.
 *  - The combo tables name physical buttons, and SP2 is `Pad_R_Right`
 *    (the Signature button, cmd 7) with `in_powerup 1` (cmd 0x20).
 *  - In guard (fighter command 12) the consumer's allowed set drops 3 and
 *    0x16: no step, no Hoho (0x4269E0 catalogue, `param_3 == 0xc`).
 *
 *  So with Signature on A, trigger + A emits [07,20,16,28]: the Hoho AND
 *  Signature-in-powerup. In neutral the Hoho wins. In guard the Hoho is
 *  not allowed and Signature-in-powerup is SP2. Type A's A is Step/Dash,
 *  which is no attack, so nothing is left in guard and the Hoho waits.
 *  No preset ever puts an attack on the Hoho's face button.
 *
 *  The fix: while the SP trigger and the Hoho's face button are both held
 *  (latched until the face button is released, so letting go of the
 *  trigger first does not start a Signature), that button is taken out of
 *  the five attack masks for the length of the call and put back after.
 *  Custom then emits what Type A emits, [20,16,28], and the engine's own
 *  guard rule does the rest. Nothing is vetoed: every command still comes
 *  from the game's code, and the SP moves on their own buttons are
 *  untouched (SP2 on trigger + B still emits 0x26).
 *
 *  Confirmed in game 2026-09-27: hold guard + trigger + A gives nothing,
 *  the Hoho comes on guard release.
 *
 *  SAME FIX, ALL FOUR COMBOS (2026-09-27, second report)
 *  -----------------------------------------------------
 *  "Hakugeki -> yellow Reverse -> SP2 gives a Hakugeki." Hakugeki is the
 *  Kikon Move (`sp_overatk01_u/d` on `Pad_R2`, `in_powerup -1`, so it
 *  fires with the trigger held), and it sits on B, the SP2 face button.
 *  Trigger + B emits [22,20,26]. While the fighter is in the Reverse
 *  action (command 0x19) the consumer's allowed set does not take 0x25 or
 *  0x26 (0x4269E0 catalogue, `param_3 == 0x19`), so the Kikon wins. Type
 *  A's B is Signature: trigger + B emits [07,20,26], and Signature in
 *  powerup is SP2 in the combo tables on its own.
 *
 *  So the rule is the Type A one for every combo: while the trigger and a
 *  combo's face button are held, that button counts as the attack Type A
 *  puts on it and as nothing else -- SP1 as Flash Attack, SP2 as Signature
 *  Move, Reverse as Quick Attack, the Hoho as no attack at all (Type A's
 *  Hoho button is Step/Dash). Custom (scheme 3) only: Type A and B are
 *  already that, and Type C is left as the game ships it.
 *
 *  It does nothing outside Custom, when the SP moves are unpaired, or when
 *  the BrainPad is idle (+0x50/+0x51 both 0).
 *
 *  Online (rig #213, 2026-09-27, room match): each client runs a BrainPad
 *  for its OWN player only, every frame (~60 active calls a second, no idle
 *  call, none for the remote fighter). So the rewrite happens at the source,
 *  before the input leaves the machine, and both clients see the same
 *  thing. Measured: 20 Hoho and 8 SP2 presses rewritten on the host in one
 *  match, no divergence reported.
 *
 *  BUILD FLAGS
 *    KBHOHO_TRACE=1  test build: <game>\kbhoho.log, one line per BrainPad
 *                    frame where the keys, the commands or the fighter's
 *                    action changed, written from its own thread.
 * ==================================================================== */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>

#include "bros_plugin.h"

#ifndef KBHOHO_TRACE
#define KBHOHO_TRACE 0
#endif

static const char KH_OWNER[] = "kbhoho.dll";
static const BrosHost* g_host = 0;
static unsigned char* g_mod = 0;

#define KH_RVA_BP_SLOT2   0x142C058u   /* BrainPad vtable 0x142C048, slot 2  */
#define KH_RVA_BP_VF2     0x410ED0u
#define KH_RVA_KEYTBL     0x18D7BA0u   /* 32 x {u32 code|flags, f32 repeat}  */

#define BP_FIGHTER        0x28
#define BP_ON_A           0x50
#define BP_ON_B           0x51
#define BP_PAD_IDX        0x88
#define BP_KEY_HOHO       0x144        /* the Custom scheme's key codes      */
#define BP_KEY_TRIG       0x170

/* key-table flags, as BrainPad::vfunc2 tests them */
#define KT_PRESSED        0x3000u
#define KT_HELD           0xC000u
#define KT_RELEASED       0xC0000u

/* the pad, for the second fix (masks read by BrainPad::vfunc2) */
#define BP_M_QUICK        0xD0         /* -> cmd 5                           */
#define BP_M_FLASH        0xD4         /* -> cmd 6                           */
#define BP_M_BREAKER      0xD8         /* -> cmd 8                           */
#define BP_M_SIGNATURE    0xDC         /* -> cmd 7                           */
#define BP_M_HOHO         0xF0         /* paired: the Hoho's face button     */
#define BP_M_TRIGGER      0xF8         /* -> cmd 0x20                        */
#define BP_M_KIKON        0xFC         /* -> cmd 0x22                        */
#define BP_M_SP1          0x100        /* paired: SP1's face button -> 0x25  */
#define BP_M_SP2          0x104        /* paired: SP2's face button -> 0x26  */
#define BP_M_REVERSE      0x108        /* paired: Reverse's face -> 0x27     */
#define KH_SCHEME_CUSTOM  3
#define KH_RVA_PADMGR     0x1CF94B8u   /* -> pad manager, pad i at +i*0xA8   */
#define KH_PAD_STRIDE     0xA8
#define KH_PAD_HELD       0xE8         /* held mask, the one vfunc2 copies   */
#define KH_RVA_PAD0_EXTRA 0x18F3934u   /* ORed into pad 0's held mask        */
#define KH_RVA_SCHEME     0x1CDE710u   /* s32 per player, 0..4               */
#define KH_RVA_BIND_P1    0x1CE8380u   /* 5 x 0x150: 28 x {f0,f1,f2}         */
#define KH_RVA_BIND_P2    0x1CE8A10u
#define KH_BIND_STRIDE    0x150
#define KH_BIND_UNPAIRED  0x144        /* entry 27 f0: SP moves unpaired     */

static void log_line(const char* fmt, ...)
{
    char buf[512];
    va_list ap;
    if (!g_host || !g_host->log) return;
    va_start(ap, fmt);
    _vsnprintf(buf, sizeof(buf) - 1, fmt, ap);
    buf[sizeof(buf) - 1] = 0;
    va_end(ap);
    g_host->log("%s", buf);
}

static int ptr_ok(const void* p)
{
    ULONG_PTR v = (ULONG_PTR)p;
    return v >= 0x100000 && (v >> 47) == 0;
}

static unsigned* kt_entry(unsigned key)
{
    unsigned* t = (unsigned*)(g_mod + KH_RVA_KEYTBL);
    int i;
    if (!key || key >= 0x400) return 0;
    for (i = 0; i < 32; i++)
        if ((t[i * 2] & 0x3FFu) == key) return &t[i * 2];
    return 0;
}

static volatile LONG g_fired = 0;          /* releases turned into a Hoho press */

/* ---- the pad: an SP-trigger combo's face button that carries an attack -- */
static const int g_atk_off[5] = { BP_M_QUICK, BP_M_FLASH, BP_M_BREAKER, BP_M_SIGNATURE,
                                  BP_M_KIKON };
static const char* const g_atk_name[5] = { "Quick Attack", "Flash Attack", "Breaker",
                                           "Signature Move", "Kikon Move" };
/* the four combos, and the attack Type A puts on each one's face button
   (an index into g_atk_off; -1 = none, the Hoho's is Step/Dash) */
#define HL_NCOMBO 4
static const int g_combo_off[HL_NCOMBO]     = { BP_M_SP1, BP_M_SP2, BP_M_REVERSE, BP_M_HOHO };
static const int g_combo_partner[HL_NCOMBO] = { 1, 3, 0, -1 };
static const char* const g_combo_name[HL_NCOMBO] = { "SP1", "SP2", "Reverse", "Hoho" };

static unsigned char g_hl_latch[2][HL_NCOMBO];          /* game thread only    */
static volatile LONG g_hl_presses[HL_NCOMBO];           /* presses rewritten   */
static volatile LONG g_hl_seen = 0;                     /* combos to report    */
static LONG g_hl_seen_idx, g_hl_seen_face[HL_NCOMBO], g_hl_seen_which[HL_NCOMBO];

/* While the SP trigger and a combo's face button are held (latched until
   that button is released), the button counts as the attack Type A puts on
   it and nothing else. Writes the five attack masks for the length of the
   call; returns 1 with saved[] holding them as they were, 0 when it left
   them alone. */
static int hl_hold_back(unsigned char* bp, unsigned saved[5])
{
    int idx = *(int*)(bp + BP_PAD_IDX), sch, i, c, any = 0, changed = 0;
    unsigned face[HL_NCOMBO], need[HL_NCOMBO], trig, held, now[5];
    unsigned char *pm, *tbl;

    if (idx < 0 || idx > 1 || (!bp[BP_ON_A] && !bp[BP_ON_B])) return 0;
    trig = *(unsigned*)(bp + BP_M_TRIGGER);
    sch = *(int*)(g_mod + KH_RVA_SCHEME + idx * 4);
    if (!trig || sch != KH_SCHEME_CUSTOM) { memset(g_hl_latch[idx], 0, HL_NCOMBO); return 0; }
    tbl = g_mod + (idx ? KH_RVA_BIND_P2 : KH_RVA_BIND_P1) + sch * KH_BIND_STRIDE;
    if (*(unsigned*)(tbl + KH_BIND_UNPAIRED) != 0) return 0;  /* no trigger combo */

    for (i = 0; i < 5; i++) saved[i] = now[i] = *(unsigned*)(bp + g_atk_off[i]);
    /* a combo needs rewriting when its button carries another attack, or
       lacks the one Type A gives it */
    for (c = 0; c < HL_NCOMBO; c++) {
        int p = g_combo_partner[c];
        unsigned which = 0;
        face[c] = *(unsigned*)(bp + g_combo_off[c]);
        need[c] = 0;
        if (!face[c] || (face[c] & trig)) continue;
        for (i = 0; i < 5; i++)
            if (i != p && (saved[i] & face[c])) which |= 1u << i;
        if (which || (p >= 0 && (saved[p] & face[c]) != face[c])) {
            need[c] = 1; any = 1;
            if (!(g_hl_seen & (1 << c))) {
                g_hl_seen_idx = idx;
                g_hl_seen_face[c] = (LONG)face[c]; g_hl_seen_which[c] = (LONG)which;
                InterlockedOr(&g_hl_seen, 1 << c);
            }
        }
    }
    if (!any) { memset(g_hl_latch[idx], 0, HL_NCOMBO); return 0; }

    pm = *(unsigned char**)(g_mod + KH_RVA_PADMGR);
    if (!ptr_ok(pm)) return 0;
    held = *(unsigned*)(pm + idx * KH_PAD_STRIDE + KH_PAD_HELD);
    if (idx == 0) held |= *(unsigned*)(g_mod + KH_RVA_PAD0_EXTRA);

    for (c = 0; c < HL_NCOMBO; c++) {
        if (!need[c] || !(held & face[c])) { g_hl_latch[idx][c] = 0; continue; }
        if ((held & trig) && !g_hl_latch[idx][c]) {
            g_hl_latch[idx][c] = 1;
            InterlockedIncrement(&g_hl_presses[c]);
        }
        if (g_hl_latch[idx][c])
            for (i = 0; i < 5; i++) now[i] &= ~face[c];
    }
    for (c = 0; c < HL_NCOMBO; c++)
        if (g_hl_latch[idx][c] && g_combo_partner[c] >= 0)
            now[g_combo_partner[c]] |= face[c];

    for (i = 0; i < 5; i++) if (now[i] != saved[i]) changed = 1;
    if (!changed) return 0;
    for (i = 0; i < 5; i++) *(unsigned*)(bp + g_atk_off[i]) = now[i];
    return 1;
}

static void hl_put_back(unsigned char* bp, const unsigned saved[5])
{
    int i;
    for (i = 0; i < 5; i++) *(unsigned*)(bp + g_atk_off[i]) = saved[i];
}

/* ---- diagnostic: the first active call of each player's BrainPad --------
   One line per player per process: its scheme and masks as vfunc2 sees them.
   It answered "is this wrapper on the input path online?" on rig #213 (yes:
   the local player's BrainPad runs every frame in an online battle), and it
   is what to read first when a scheme behaves differently online. Written by
   the game thread, printed by the heartbeat. */
static volatile LONG g_dg_seen[2];
static unsigned g_dg_snap[2][12];
static void* g_dg_bp[2];

static void dg_note(unsigned char* bp)
{
    static const int off[10] = { BP_M_HOHO, BP_M_TRIGGER, BP_M_SP1, BP_M_SP2, BP_M_REVERSE,
                                 BP_M_QUICK, BP_M_FLASH, BP_M_BREAKER, BP_M_SIGNATURE,
                                 BP_M_KIKON };
    int idx = *(int*)(bp + BP_PAD_IDX), i, sch;
    unsigned char* tbl;
    if (idx < 0 || idx > 1 || g_dg_seen[idx]) return;
    if (!bp[BP_ON_A] && !bp[BP_ON_B]) return;
    sch = *(int*)(g_mod + KH_RVA_SCHEME + idx * 4);
    g_dg_snap[idx][0] = (unsigned)sch;
    tbl = g_mod + (idx ? KH_RVA_BIND_P2 : KH_RVA_BIND_P1)
        + ((sch >= 0 && sch < 5) ? sch : 0) * KH_BIND_STRIDE;
    g_dg_snap[idx][1] = *(unsigned*)(tbl + KH_BIND_UNPAIRED);
    for (i = 0; i < 10; i++) g_dg_snap[idx][2 + i] = *(unsigned*)(bp + off[i]);
    g_dg_bp[idx] = bp;
    InterlockedExchange(&g_dg_seen[idx], 1);
}

#if KBHOHO_TRACE
/* ---- trace (test builds only) ------------------------------------------- */
typedef struct {
    unsigned long long qpc;
    unsigned frame, kt_t, kt_h, fired, ncmd, pad, hl;
    unsigned short cmd[16];
    unsigned char fcmd;
    char act[40];
} KhEv;
#define KH_RING 16384
static KhEv g_ring[KH_RING];
static volatile LONG g_head = 0, g_tail = 0;
static CRITICAL_SECTION g_cs;
static KhEv g_last;
static unsigned g_frame = 0;
static LARGE_INTEGER g_freq;

static void kh_action(unsigned char* f, char* out, int cap)
{
    out[0] = 0;
    __try {
        unsigned char* s = f + 0x1388;
        const unsigned char* q = 0;
        unsigned long long len = 0, i;
        if (s[0] & 1u) {
            unsigned long long base = *(unsigned long long*)s & ~1ULL;
            unsigned long long p = *(unsigned long long*)(s + 0x10);
            if (base < 38ULL && p >= 0x10000ULL && p <= 0x00007FFFFFFFFFFFULL) {
                q = (const unsigned char*)(ULONG_PTR)p;
                len = base + (q[base] != 0 ? 1ULL : 0ULL);
            }
        } else if ((s[0] >> 1) <= 15u) {
            len = s[0] >> 1; q = s + 1;
        }
        if (q) {
            for (i = 0; i < len && i < (unsigned long long)(cap - 1); i++)
                out[i] = (q[i] >= 0x20 && q[i] < 0x7F) ? (char)q[i] : '?';
            out[i] = 0;
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) { out[0] = 0; }
}

static void kh_trace(unsigned char* bp, void* out, unsigned kt_t, unsigned kt_h, int fired,
                     unsigned hl)
{
    KhEv e;
    memset(&e, 0, sizeof(e));
    QueryPerformanceCounter((LARGE_INTEGER*)&e.qpc);
    e.frame = ++g_frame;
    e.kt_t = kt_t; e.kt_h = kt_h; e.fired = (unsigned)fired; e.hl = hl;
    __try {
        int idx = *(int*)(bp + BP_PAD_IDX);
        unsigned char* pm = *(unsigned char**)(g_mod + KH_RVA_PADMGR);
        if (idx >= 0 && idx <= 1 && ptr_ok(pm))
            e.pad = *(unsigned*)(pm + idx * KH_PAD_STRIDE + KH_PAD_HELD);
    } __except (EXCEPTION_EXECUTE_HANDLER) { }
    __try {
        unsigned char** v = (unsigned char**)out;
        unsigned char *b = v[0], *en = v[1], *p;
        if (ptr_ok(b) && en >= b && en - b <= 6 * 64)
            for (p = b; p + 6 <= en && e.ncmd < 16; p += 6)
                e.cmd[e.ncmd++] = *(unsigned short*)p;
        {
            unsigned char* f = *(unsigned char**)(bp + BP_FIGHTER);
            if (ptr_ok(f)) { e.fcmd = f[0xFA0]; kh_action(f, e.act, (int)sizeof(e.act)); }
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) { }
    if (!fired && e.ncmd == g_last.ncmd && !memcmp(e.cmd, g_last.cmd, sizeof(e.cmd))
        && ((e.kt_t ^ g_last.kt_t) & 0x5F400u) == 0 && ((e.kt_h ^ g_last.kt_h) & 0x5F400u) == 0
        && e.pad == g_last.pad && e.hl == g_last.hl
        && e.fcmd == g_last.fcmd && !strcmp(e.act, g_last.act)) {
        g_last = e;
        return;
    }
    g_last = e;
    EnterCriticalSection(&g_cs);
    if (g_head - g_tail < KH_RING) { g_ring[g_head % KH_RING] = e; g_head++; }
    LeaveCriticalSection(&g_cs);
}

static DWORD WINAPI kh_writer(LPVOID unused)
{
    char path[MAX_PATH], *s;
    FILE* f;
    unsigned long long q0 = 0;
    (void)unused;
    GetModuleFileNameA(NULL, path, MAX_PATH);
    s = strrchr(path, '\\');
    if (s) strcpy(s + 1, "kbhoho.log"); else strcpy(path, "kbhoho.log");
    f = fopen(path, "w");
    if (!f) return 0;
    fprintf(f, "# kbhoho trace: t_ms frame | trig kt | hoho kt | FIX = release turned into a Hoho press"
               " | pad held | HLD = Hoho button held back from its attack | fcmd action [cmds]\n");
    fflush(f);
    for (;;) {
        Sleep(250);
        for (;;) {
            KhEv e;
            int have = 0, i, k = 0;
            char cm[128];
            EnterCriticalSection(&g_cs);
            if (g_tail != g_head) { e = g_ring[g_tail % KH_RING]; g_tail++; have = 1; }
            LeaveCriticalSection(&g_cs);
            if (!have) break;
            if (!q0) q0 = e.qpc;
            cm[0] = 0;
            for (i = 0; i < (int)e.ncmd && k < (int)sizeof(cm) - 8; i++)
                k += _snprintf(cm + k, sizeof(cm) - (size_t)k, "%s%02X", i ? "," : "", e.cmd[i]);
            fprintf(f, "%10.1f %6u | T %05X | H %05X |%s| P %05X |%s| f%02X %-24s [%s]\n",
                    (double)(e.qpc - q0) * 1000.0 / (double)g_freq.QuadPart, e.frame,
                    e.kt_t & 0xFFFFFu, e.kt_h & 0xFFFFFu, e.fired ? "FIX" : "   ",
                    e.pad & 0xFFFFFu, e.hl ? "HLD" : "   ", e.fcmd, e.act, cm);
        }
        fflush(f);
    }
}
#endif

/* ---- the hook ------------------------------------------------------------ */
typedef void* (*BpFn)(void*, void*, float);
static BpFn g_bp_orig = 0;

static void* hk_bp(void* self, void* out, float dt)
{
    unsigned char* bp = (unsigned char*)self;
    unsigned *et = 0, *eh = 0;
    unsigned saved = 0, kt_t = 0, kt_h = 0;
    unsigned hl_saved[5], hl = 0;
    int fired = 0;
    void* r;

    __try { dg_note(bp); } __except (EXCEPTION_EXECUTE_HANDLER) { }
    __try { hl = hl_hold_back(bp, hl_saved); } __except (EXCEPTION_EXECUTE_HANDLER) { hl = 0; }

    __try {
        if (*(int*)(bp + BP_PAD_IDX) == 0 && (bp[BP_ON_A] || bp[BP_ON_B])) {
            unsigned kt = *(unsigned*)(bp + BP_KEY_TRIG), kh = *(unsigned*)(bp + BP_KEY_HOHO);
            if (kt != kh) {
                et = kt_entry(kt);
                eh = kt_entry(kh);
            }
            if (et && eh) {
                kt_t = *et; kt_h = *eh;
                /* the pad's tap path: the Hoho button released while the
                   trigger is held asks for the Hoho again */
                if ((kt_h & KT_RELEASED) && (kt_t & KT_HELD) && !(kt_h & KT_PRESSED)) {
                    saved = kt_h;
                    *eh = kt_h | 0x1000u;
                    fired = 1;
                }
            }
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) { fired = 0; }

    r = g_bp_orig(self, out, dt);

    if (hl) {
        __try { hl_put_back(bp, hl_saved); } __except (EXCEPTION_EXECUTE_HANDLER) { }
    }
    if (fired) {
        __try { *eh = saved; } __except (EXCEPTION_EXECUTE_HANDLER) { }
        InterlockedIncrement(&g_fired);
    }
#if KBHOHO_TRACE
    if ((et && eh) || g_hl_seen) kh_trace(bp, out, kt_t, kt_h, fired, hl);
#endif
    return r;
}

/* the counts go to patch_ranked.log from here, never from the game thread */
static DWORD WINAPI kh_heartbeat(LPVOID unused)
{
    LONG said = 0, said_seen = 0, said_hl[HL_NCOMBO] = { 0 }, dg_said[2] = { 0 };
    int c;
    (void)unused;
    for (;;) {
        Sleep(5000);
        for (c = 0; c < 2; c++)
            if (g_dg_seen[c] && !dg_said[c]) {
                const unsigned* s = g_dg_snap[c];
                dg_said[c] = 1;
                log_line("KBHOHO/diag: BrainPad P%d (%p) first active call -- scheme %d, unpaired %u;"
                         " hoho %X trig %X sp1 %X sp2 %X rev %X | quick %X flash %X breaker %X"
                         " sig %X kikon %X",
                         c + 1, g_dg_bp[c], (int)s[0], s[1], s[2], s[3], s[4], s[5], s[6],
                         s[7], s[8], s[9], s[10], s[11]);
            }
        for (c = 0; c < HL_NCOMBO; c++) {
            if ((g_hl_seen & (1 << c)) && !(said_seen & (1 << c))) {
                char names[96];
                int i, k = 0, p = g_combo_partner[c];
                said_seen |= 1 << c;
                names[0] = 0;
                for (i = 0; i < 5; i++)
                    if (g_hl_seen_which[c] & (1 << i))
                        k += _snprintf(names + k, sizeof(names) - (size_t)k, "%s%s",
                                       k ? " + " : "", g_atk_name[i]);
                log_line("KBHOHO/pad: P%ld Custom, %s = SP trigger + button 0x%lX, which is %s --"
                         " with the trigger down it counts as %s, as in Type A",
                         g_hl_seen_idx + 1, g_combo_name[c], g_hl_seen_face[c],
                         k ? names : "no attack", p >= 0 ? g_atk_name[p] : "no attack");
            }
            if (g_hl_presses[c] != said_hl[c]) {
                said_hl[c] = g_hl_presses[c];
                log_line("KBHOHO/pad: %s -- %ld trigger press(es) rewritten to Type A so far",
                         g_combo_name[c], said_hl[c]);
            }
        }
        if (g_fired != said) {
            said = g_fired;
            log_line("KBHOHO: %ld keyboard Hoho release(s) answered like the pad's tap path so far", said);
        }
    }
}

__declspec(dllexport) int BrosPluginInit(const BrosHost* host)
{
    unsigned long long* slot;
    unsigned long long want;
    DWORD old;
    HANDLE th;

    if (!host || host->abi != BROS_PLUGIN_ABI) return 0;
    g_host = host;
    g_mod = host->mod;

    slot = (unsigned long long*)(g_mod + KH_RVA_BP_SLOT2);
    want = (unsigned long long)(g_mod + KH_RVA_BP_VF2);
    if (*slot != want) {
        log_line("KBHOHO: BrainPad vtable slot 2 holds %p, not BrainPad::vfunc2 %p -- NOT armed",
                 (void*)*slot, (void*)want);
        return 0;
    }
    if (!host->claim(KH_OWNER, KH_RVA_BP_SLOT2, 8,
                     "BrainPad vtable slot 2 -- keyboard Hoho release, the pad's tap path;"
                     " Custom SP-trigger combo buttons count as Type A's attack")) {
        log_line("KBHOHO: the BrainPad vtable slot is claimed by another owner -- NOT armed");
        return 0;
    }
#if KBHOHO_TRACE
    QueryPerformanceFrequency(&g_freq);
    InitializeCriticalSection(&g_cs);
    th = CreateThread(NULL, 0, kh_writer, NULL, 0, NULL);
    if (th) CloseHandle(th);
#endif
    g_bp_orig = (BpFn)(ULONG_PTR)want;
    if (!VirtualProtect(slot, 8, PAGE_READWRITE, &old)) {
        log_line("KBHOHO: VirtualProtect failed -- NOT armed");
        return 0;
    }
    InterlockedCompareExchange64((volatile LONG64*)slot, (LONG64)(ULONG_PTR)hk_bp, (LONG64)want);
    VirtualProtect(slot, 8, old, &old);

    th = CreateThread(NULL, 0, kh_heartbeat, NULL, 0, NULL);
    if (th) CloseHandle(th);
    log_line("KBHOHO: ARMED%s -- on keyboard, releasing the Hoho key while the SP trigger key is"
             " held asks for the Hoho again, as a pad does; on a pad in Custom, an SP-trigger"
             " combo's button counts as the attack Type A puts on it while the trigger is down",
             KBHOHO_TRACE ? " (TRACE build: <game>\\kbhoho.log)" : "");
    return 1;
}
