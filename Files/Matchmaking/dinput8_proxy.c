/* =====================================================================
 *  dinput8.dll  (proxy loader + patch-only matchmaking)
 *  BLEACH: Rebirth of Souls
 * ---------------------------------------------------------------------
 *  The game statically imports dinput8.dll!DirectInput8Create, so placing
 *  this file in the game folder makes the GAME load it into its own
 *  process. We forward every dinput8 export to the real system dinput8
 *  (so input works exactly as before) and, on load, install the Steam
 *  matchmaking hook so patched players only match players using the same
 *  match code.
 *
 *  Match code: read from  patch_ranked.txt  (line 1) next to the game exe.
 *  Log:        patch_ranked.log  next to the game exe.
 * ---------------------------------------------------------------------
 *  CANONICAL SOURCE.  This file, git-tracked in
 *  Bleach-Rebalance-Of-Souls-Dev-Environment/Files/Matchmaking/.
 *  Edit it here and nowhere else; the repo is the source of truth.
 *
 *  !! 2026-08-25: the previous version of this paragraph still described the
 *  2026-08-05 merge and named four other locations.  It had been wrong for
 *  three weeks.  FIVE byte-identical 688-line copies of that Aug-06 file
 *  (md5 a075c82faacf) sit in the game dir, Patch/, Patch_Dev_Environment/ and
 *  the community-patch repo twice.  They are STALE DEPLOY COPIES, not sources,
 *  and this file has since grown to 4x their size.  Nothing on disk said so,
 *  which is exactly the failure the 08-05 merge was meant to end.  They are
 *  retired to _to_delete/.  If you find another copy, it is stale.
 *
 *  BUILD:  ./build_dinput8.sh [community|cre|both]
 *  Toolchain established by measuring the shipping DLL 2026-08-25: it has a
 *  .buildid section (LLD), NO Rich header (not MSVC link.exe), no GCC banner
 *  (not mingw) and imports api-ms-win-crt-*.dll (UCRT) => zig cc, target
 *  x86_64-windows-gnu, -O2.  Rebuilding reproduces the shipping DLL's exact
 *  size (208,384 B), its seven sections, their VAs and their raw sizes.
 *
 *  It contains:
 *      Steam matchmaking hook   (patch-only pool + worldwide region)
 *      patch_version_string     title -> "ReBalance <ver>"
 *      patch_yamamoto_selfcost  sublimation-Kikon 2-konpaku self-cost -> 0
 *      patch_byakuya_evo_icon   Pl22 stance icon kept visible in evo
 *      patch_aizen_kikon_counter  Kikon Counter costs 5 flames only  [DISABLED]
 *      patch_aizen_flamecost    Aizen SP1 costs 1 (base) / 3 (evo) flames [DISABLED]
 *      patch_stage_new_id_gate  brand-new stage ids can load their geometry
 *      patch_intro_skip         online battles skip the pre-match character intros [DISABLED]
 *      patch_room_result_menu   room match ends on the free-match result menu
 *      patch_room_rematch_wait  a split choice falls back to the room in 1 s, not 120
 *      patch_room_draw_guard    NULL vertex-buffer map no longer memcpys to a raw offset
 *      patch_room_draw_guard2   same NULL map, second consumer; records the map fn
 *      patch_dred_hook          turns on D3D12 DRED and reports WHY the device died
 *      crash_veh                logs the faulting RVA + DRED at the moment of the fault
 *      d3d12_debug_*            opt-in debug layer; names the INVALID_CALL that kills the device
 *      patch_room_steam_guard   NULL Steam interface no longer called through
 *      patch_meri_first_kill    Kikon caps at 4 konpaku before your first kill [OFF by default]
 *      patch_meri_display       the Konpaku bar promises 4 too, not 5      [OFF by default]
 *      patch_reawaken_battle    the four Reawakeners start the match Reawakened [OFF by default]
 *                               (Try Again = synced rematch, same characters)
 *      patch_fast_boot          boot skips the clickable auto-save notice
 *      patch_skip_logos         boot skips the four publisher logo animations
 *      patch_boot_training      boot lands on Training, or on the room-match menu [OFF by default]
 *  Rebuild with build_dinput8.bat and check patch_ranked.log for one line
 *  per patch. See the header of each patch_* function for its anchors.
 * ---------------------------------------------------------------------
 *  2026-08-06 CRASH HOTFIX. Both Aizen patches are DISABLED at build time
 *  (see the ENABLE_* flags below). Players reported Aizen crashing the game
 *  on Kikon, on the cocoon->evo transition, and when hit while holding 5
 *  flames. Cause (static analysis, see patch_aizen_flamecost's header):
 *  af_action_is() reads the action-name tsd::string 8 bytes below where it
 *  actually lives, so for any action name >= 16 characters it dereferences a
 *  non-pointer POD field as a char*. 68 of pl020's 211 action names are >= 16
 *  chars, and they are exactly the reported repros. patch_aizen_kikon_counter
 *  is disabled as a precaution only -- its three edits look mechanically safe
 *  but it also shipped for the first time in the crashing build and has never
 *  been playtested in this configuration. Re-enable it first when testing.
 *  NOT implicated: VERSION, SELFCOST (pl020 has no sp_break02 at all, so the
 *  selfcost lambda can never fire on Aizen), BYAKUYA_ICON, PART 2.
 * ===================================================================== */

#include <windows.h>
#include <tlhelp32.h>   /* PART 27: thread enumeration for the stall sampler */
#include <stdint.h>
#include <io.h>      /* _fileno / _get_osfhandle -- see log_line */
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>

#define PATCH_ISSUER_DEFAULT 700001
#define ENABLE_LOG 1

/* ---- build-time patch switches (§9e: gate with a flag, never a commented
   -out call, so the log always says what shipped) ---------------------- */
#define ENABLE_AIZEN_KIKON_COUNTER 0   /* 2026-08-06: off, precaution (see header) */
#define ENABLE_AIZEN_FLAMECOST     0   /* 2026-08-06: off, CRASHES (see header)    */
/* Guarded like ENABLE_PL005_GAUGE, so `/DENABLE_BYAKUYA_GAUGE=0` actually
   takes. As a bare #define the command line lost to this line with a C4005
   warning, which means the A/B build everyone assumed existed did not: every
   "gauge off" build ever made this way shipped the gauge on. */
#ifndef ENABLE_BYAKUYA_GAUGE
#define ENABLE_BYAKUYA_GAUGE       1   /* base-form stance gauge, 3 sites          */
#endif
/* Guarded like ENABLE_BYAKUYA_GAUGE so `/DENABLE_GAUGE_HANDLE_GUARD=0` actually
   takes. It did not, until 2026-09-04: the E variant was built, installed and
   launched, and the log still said `hooked RVA 0x92790`. A flag whose whole
   purpose is an A/B has to be overridable, or the A/B silently tests A twice. */
#ifndef ENABLE_GAUGE_HANDLE_GUARD
#define ENABLE_GAUGE_HANDLE_GUARD  1   /* empties a corrupt handle's +0x40 block  */
#endif
/* Byakuya's EVO stance becomes a resource: petals drain on the engine's own
   1340-frame clock as they already do, evo's sword stance refills the bar over
   the same duration, and SP1 only grants petals again on a full bar. Base form
   is untouched. Guarded like ENABLE_BYAKUYA_GAUGE so
   `/DENABLE_BYAKUYA_PETAL_TIMER=1` actually takes. Needs ENABLE_BYAKUYA_GAUGE=1:
   the gate and the bar both live on Byakuya's own controller, and
   pl022_gauge_install is what puts them in. */
#ifndef ENABLE_BYAKUYA_PETAL_TIMER
#define ENABLE_BYAKUYA_PETAL_TIMER 0   /* test variant -- see pl022_gauge.c       */
#endif
/* Byakuya as a builder/spender: sword hits build the gauge, petal hits spend
   it, an empty gauge forces sword back. A different answer to the same question
   as the petal timer, and mutually exclusive with it -- both own the element's
   value. Guarded like the others so `/DENABLE_BYAKUYA_BUILDER_SPENDER=1` takes,
   and it needs ENABLE_BYAKUYA_GAUGE=1: the whole mechanic runs in Byakuya's own
   controller update. See pl022_builder_spender.c. */
#ifndef ENABLE_BYAKUYA_BUILDER_SPENDER
#define ENABLE_BYAKUYA_BUILDER_SPENDER 0
#endif
/* Three people in a room match. A probe on the Steam lobby layer plus the
   member-cap lever, shipped together because one test run has to answer WHERE
   the two-player cap lives before anything can be built on top of it. Test
   variant only -- it moves the matchmaking pool. See PART 27. */
#ifndef ENABLE_ROOM3
#define ENABLE_ROOM3 0
#endif
#define ENABLE_TEARDOWN_GUARD      1   /* skip a destroy through a NULL vtable    */
#define ENABLE_BYAKUYA_EVO_ICON    0   /* superseded by the gauge -- see worker()  */
#define ENABLE_INTRO_SKIP          0   /* 2026-08-21: OFF, froze both players inputs */
#define ENABLE_ROOM_RESULT_MENU    1   /* room match ends on the free-match result menu */
#define ENABLE_ROOM_GUARDS         1   /* NULL guards for the two room-match crashes */
#define ENABLE_UIRES_GUARD         1   /* NULL guard for the UI resource-table lookup */
#define ENABLE_VOICE_PROBE         0   /* OFF. The 0x24BB10 detour crashed selection twice
                                       (runs 3 and 4); the one-arg version in runs 1-2 was
                                       fine, so the return-address stub is the difference.
                                       Not re-armed until it is understood. */
#define ENABLE_DRED                1   /* ask D3D12 why the device was removed */

/* ---- CRE build only: Zangetsu's own gauge ---------------------------- */
#ifndef ENABLE_PL005_GAUGE
#define ENABLE_PL005_GAUGE     1   /* pl005 owns his controller outright */
#endif

/* Build identity. build_dinput8.sh injects -DPATCH_BUILD_ID="<git sha> <date>".
   Deliberately NOT the compile-time date macros: they make the build
   unreproducible and zig rejects them under -Werror=date-time. A git sha is
   more useful anyway -- it names the SOURCE, not the minute someone happened
   to compile it. verify_patchlog.py refuses to certify an unstamped log. */
#ifndef PATCH_BUILD_ID
#define PATCH_BUILD_ID "unstamped-local-build"
#endif

/* "Meri's mode" -- a TEST-ONLY mechanic, off in the shipping build. Build the
   test DLL with  -DENABLE_MERI_MODE=1  and keep it in dll_switch/variants as
   "Meri's mode"; the default 0 keeps the released loader exactly the behaviour
   it has today. */
#ifndef ENABLE_MERI_MODE
#define ENABLE_MERI_MODE           0   /* first-kill cap on Kikon konpaku damage */
#endif

/* "Reawakening Battle" -- the other TEST-ONLY mode, also off by default.
   Build it with  -DENABLE_REAWAKEN_BATTLE=1  and keep it in
   dll_switch/variants as "Reawakening Battle". */
#ifndef ENABLE_REAWAKEN_BATTLE
#define ENABLE_REAWAKEN_BATTLE     0   /* the four Reawakeners start Reawakened */
#endif

/* "Backstep hold" -- SHIPS ON, back only. Holding the step/dash button
   with the stick held BACK currently yields the backward run, because the dash
   action is forward-only; a backstep only exists on the button's RELEASE frame,
   so mashing it out of blockstun online is a coin flip. This makes the held
   back+dash gesture emit the STEP command every frame instead, which is what
   gives the run its frame-1 reliability.
   ! It changes simulation, so it needs no pool tag ONLY because it is in the
   main loader: the game can only be started through the launcher, the launcher
   installs this DLL, so every client on the patch has it. That argument is
   about DELIVERY -- if this ever becomes a toggle, it needs its own pool.
   ! Shipped with the recovery defect still open: a HELD step still spams and
   still cancels into a run far earlier than a tapped one. Measured, not
   guessed -- the command-level guard below runs correctly and does not fix it,
   so the cause is elsewhere (most likely the step action's own cancel windows
   in step_?_act). Deliberate call: ship the mechanic, fix the recovery after.
   Build -DENABLE_BACKSTEP_HOLD=0 for a loader without it.
   ! SWITCHED OFF 2026-09-03, and taken back out of the public patch in the same
   pass (reverted there to 92c5425). Reported from play: it produces gameplay
   changes beyond the intended one, not yet characterised, and a major tournament
   is a week out. Shipping an uncharacterised movement change into the build a
   tournament runs on is not a risk worth taking for a feature that can wait.
   This is a scheduling decision, NOT a verdict on the mechanic: the code, the
   blockstun gate, the grace window and the one-step rule all stay exactly as
   they are, and -DENABLE_BACKSTEP_HOLD=1 brings the whole thing back. The
   dll_switch variants "2-backstep hold" and "4-Backstep hold" are still built
   with it on, so it stays testable while it is being looked at properly. */
#ifndef ENABLE_BACKSTEP_HOLD
#define ENABLE_BACKSTEP_HOLD       0   /* OFF pre-tournament -- see above */
#endif

/* "Flash step hold" -- SHIPS ON. Same defect as the backstep, same shape: the
   flash step (syunpo, command 0x16) is emitted on two EDGE conditions only -- a
   button mask, or the "tap" flag, which is "released without a long hold". So
   pressing it in neutral works and HOLDING it through blockstun produces
   nothing at all, because on the frame the fighter becomes actionable there is
   no edge left to catch. Reported exactly that way from play.
   ! MEASURED INERT 2026-08-31, and turned OFF. The gate counters this patch
   carries reported `held=0` in every session while `edge` and `tap` moved, so
   the level condition never once fired. Two keys were tried and both are dead
   for the same single reason: `sil` -- which drives the +0x94 timer and hence
   the +0xC9 hold bit -- is computed from `[r14+0xF0] & r12d`, and **r12d never
   contains this button**. (Not a liveness bug: r12 is provably not rewritten
   between 0x140412372 and the gate.)
   ! And the approach itself is wrong, not just the key. Over 1346 frames of a
   real match the gate ran 37 times -- **2.7% of frames** -- so no condition
   placed inside it can make the flash step available on an arbitrary actionable
   frame. The constraint is UPSTREAM, in whatever lets this block run.
   ! There are also THREE parallel emit sites for cmd 0x16 (0x4125F5, 0x4127F9,
   0x412D00), structurally different; this hooks only the first.
   Kept in the tree because the gate counters are the measurement that produced
   all of the above, and PART 21 reads them. Do not re-enable without first
   answering what gates the block. */
#ifndef ENABLE_FLASHSTEP_HOLD
#define ENABLE_FLASHSTEP_HOLD      0   /* suspected regression, no measured gain */
#endif

/* Diagnostic only -- dumps BrainPad's per-action button masks so a custom
   control scheme can be checked for two actions claiming the same button.
   Not a mode, never ship it on. */
#ifndef ENABLE_INPUT_PROBE
#define ENABLE_INPUT_PROBE         0   /* log the button-mask block             */
#endif

/* Stops the flash-step button from firing the catch-all command 0x21. Reported:
   with a custom scheme, pressing Hoho WHILE GUARDING fires Spiritual Pressure
   Move 2; the correct behaviour (and what Type A does) is that nothing comes
   out at all until guard is released. */
#ifndef ENABLE_HOHO_CATCHALL_FIX
#define ENABLE_HOHO_CATCHALL_FIX   0   /* MEASURED INEFFECTIVE -- see below */
#endif

/* EXPERIMENT. Drops the companion command 0x28 that is pushed unconditionally
   right after the flash step. Per-site counters put it at 24 emissions against
   24 Hoho presses -- exact lockstep, unlike 0x21 (13) which fires from LT and is
   innocent. Tests whether 0x28 is what becomes the stray SP2 during guard. */
/* THE FIX. In guard, pressing the flash step must do nothing at all -- that is
   what Type A does, and what a custom scheme stopped doing. Vetoes the flash
   step's emission while the fighter's current command is guard_in.
   The value 12 is MEASURED, not assumed: the state histogram of fighter+0xFA0
   sampled at the emission itself came back 0x00C01041 = bits 0,6,12,22,23 --
   ntrl_in, 6, guard_in, syunpo_in, syunpo_out. Bit 12 is there. */
/* THE ACTUAL FIX for the reported bug: no Spiritual Pressure move out of the
   LT+button combo while guarding. See PART 25. */
#ifndef ENABLE_SP_GUARD_VETO
#define ENABLE_SP_GUARD_VETO       0   /* CAUSED A REGRESSION -- see PART 25 */
#endif

#ifndef ENABLE_HOHO_GUARD_VETO
#define ENABLE_HOHO_GUARD_VETO     0   /* works, but belongs to the OPEN SP2
                                          investigation -- not shipped */
#endif

#ifndef ENABLE_HOHO_NO_COMPANION
#define ENABLE_HOHO_NO_COMPANION   0   /* MEASURED INNOCENT -- 0x28@634 went 24->0
                                          and the stray SP2 survived */
#endif

/* "Fast boot" -- drops the clickable auto-save notice that sits between the
   publisher logos and the title screen. Confirmed in game 2026-08-26 and ON in
   the shipped loader from that date: it is not a mode, it costs nothing and it
   changes no simulation, so there is no pool to separate. Build with
   -DENABLE_FAST_BOOT=0 for a loader that keeps the notice. */
#ifndef ENABLE_FAST_BOOT
#define ENABLE_FAST_BOOT           1   /* skip the AUTO_SAVE notice at boot */
#endif

/* Diagnostic only -- logs every change of Yhwach's Kaiser level so a match can
   say WHEN it moves and by how much. Not a mode, never ship it on. */
#ifndef ENABLE_KAISER_TRACE
#define ENABLE_KAISER_TRACE        0
#endif

/* Yhwach reaches the Reawakening on his NINTH Kaiser, not his eighth. A
   balance fix, not a mode: it changes no netcode and shifts no pool, so it
   ships ON. Build with -DENABLE_YHWACH_REAWAKEN_9=0 for the stock threshold.
   See PART 35. */
#ifndef ENABLE_YHWACH_REAWAKEN_9
#define ENABLE_YHWACH_REAWAKEN_9   1
#endif

/* Diagnostic only -- one line per transform Yhwach takes, naming the exe site
   that asked for it and his whole unique block at that instant. Changes no
   behaviour. Never ship it on; it shares a hook site with PART 16, so the two
   must never be enabled together. See PART 36. */
#ifndef ENABLE_YHWACH_PROBE
#define ENABLE_YHWACH_PROBE        0
#endif

/* Yhwach starts every mode on Kaiser level 1, Training included. The data
   record that grants it rides the battle-intro action, which Training never
   plays. A balance fix, not a mode: it ships ON. Build with
   -DENABLE_YHWACH_START_LEVEL=0 for the stock start. See PART 37. */
#ifndef ENABLE_YHWACH_START_LEVEL
#define ENABLE_YHWACH_START_LEVEL  1
#endif

/* Diagnostic only -- one line per change of the battle intro's demo state,
   with the pad mask on the same line, so the offline B-press skip names its
   own mechanism. Read-only, but it logs during every intro: never ship it on.
   See PART 38. */
#ifndef ENABLE_INTRO_PROBE
#define ENABLE_INTRO_PROBE         0
#endif

/* Diagnostic only -- a hardware write breakpoint on the intro's play flag, to
   name the code that kills the demo when B is pressed. Needs PART 38 for the
   address, and ROOM3 OFF: that probe owns DR0 and claims every single-step.
   See PART 39. */
#ifndef ENABLE_INTRO_WHO
#define ENABLE_INTRO_WHO           0
#endif

/* The player-triggered intro skip, ONLINE. SHIPS ON since 2026-09-21: tested on
   the three-client rig (#156 two players, #157 with a spectator, #158-#160 for
   the victory animation and the gallery's own intro) and confirmed in play.

   ⚠ It changes WHEN A MATCH STARTS, so a client carrying it and a stock client
   disagree about the first seconds: the one with the patch ends its intro on the
   press, the stock one watches the intro out. That is a cosmetic offset, not a
   desync -- rig #156 measured 37 ms between two patched clients and the netcode's
   frame counter is not anchored in a way a skip disturbs. Mixed pairs are
   therefore safe, just not synchronised during the intro. See PART 42. */
#ifndef ENABLE_ONLINE_INTRO_SKIP
#define ENABLE_ONLINE_INTRO_SKIP   1
#endif
#ifndef OIS_SYNC_SLOT
#define OIS_SYNC_SLOT              11   /* 0,5,6,8,9,10 are the engine's */
#endif

/* Diagnostic only -- read-only hooks on SceneMessage::SetAdditionalData that
   answer why a throw cannot be teched out of a run. Changes no behaviour, but
   it logs on every state transition, so never ship it on. See PART 26. */
#ifndef ENABLE_THROWTECH_PROBE
#define ENABLE_THROWTECH_PROBE     0
#endif

/* Skip the four boot logos outright, so the game opens on the title screen.
   Separate from ENABLE_FAST_BOOT because it is a different call: that one drops
   a dialog nobody wants, this one drops the publisher animations. Build with
   -DENABLE_SKIP_LOGOS=0 for a loader that plays them. */
#ifndef ENABLE_SKIP_LOGOS
#define ENABLE_SKIP_LOGOS          1   /* boot straight to the title screen */
#endif

/* "Training boot" -- a launch SHORTCUT, not a game mode: the boot flow jumps
   straight to the Training character select instead of the title screen. Ships
   as its own loader, GameModes/TrainingBoot/dinput8.dll, built from this source
   with  -DENABLE_BOOT_TRAINING=1  and selected by "Quick Launch Training
   Mode.py". No pool tag: it changes no simulation, only which scene the logo
   flow hands off to, so a client running it is identical in a match. */
#ifndef ENABLE_BOOT_TRAINING
#define ENABLE_BOOT_TRAINING       0   /* boot into the Training character select */
#endif

/* "Room match boot" -- the same shortcut aimed at the ONLINE room-match menu
   (Create room / Find room). Ships as GameModes/RoomMatchBoot/dinput8.dll,
   built with  -DENABLE_BOOT_ROOMMATCH=1  and selected by "Quick Launch Room
   Match.py". Mutually exclusive with ENABLE_BOOT_TRAINING -- they rewrite the
   same handoff. */
#ifndef ENABLE_BOOT_ROOMMATCH
#define ENABLE_BOOT_ROOMMATCH      0   /* boot into the online room-match menu */
#endif

/* ---------- shared helpers ------------------------------------------- */
static void exe_dir_path(const char* name, char* out, size_t n)
{
    char exe[MAX_PATH];
    DWORD len = GetModuleFileNameA(NULL, exe, MAX_PATH);
    while (len > 0 && exe[len-1] != '\\' && exe[len-1] != '/') len--;
    exe[len] = 0;
    snprintf(out, n, "%s%s", exe, name);
}
/* ★ 2026-09-01: log_line used to fopen/fprintf/fclose with no synchronisation.
   That was survivable while only the install path and low-rate drivers called it,
   and it crashed the process the moment a probe logged from several threads at
   once -- an access violation deep in a foreign module reading -1, i.e. the CRT's
   FILE machinery torn between threads. A lock is the fix; nothing that logs should
   have to know how often the rest of the module logs. */
static CRITICAL_SECTION g_log_cs;
static volatile LONG     g_log_cs_state = 0;   /* 0 unset, 1 initialising, 2 ready */

static void log_lock_ready(void)
{
    LONG prev = InterlockedCompareExchange(&g_log_cs_state, 1, 0);
    if (prev == 0) {
        InitializeCriticalSection(&g_log_cs);
        InterlockedExchange(&g_log_cs_state, 2);
    } else {
        while (g_log_cs_state != 2) Sleep(0);
    }
}

static void log_line(const char* fmt, ...)
{
#if ENABLE_LOG
    char path[MAX_PATH], buf[512];
    SYSTEMTIME t; GetLocalTime(&t);
    va_list ap; va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap); va_end(ap);
    exe_dir_path("patch_ranked.log", path, sizeof(path));
    log_lock_ready();
    EnterCriticalSection(&g_log_cs);
    {
        FILE* f = fopen(path, "a");
        if (f) { fprintf(f, "[%02d:%02d:%02d.%03d] %s\n",
                         t.wHour,t.wMinute,t.wSecond,t.wMilliseconds, buf);
                 /* \u2605\u2605 2026-09-17: PUSH IT TO THE DEVICE, NOT JUST TO THE OS.
                    Berg: "I will have to restart my pc after it lags because
                    it's unusable when it is lagging ... make sure whatever we
                    get from the lag log is not gone on restart or anything."
                    fclose() flushes the CRT buffer into the OS cache and
                    returns; a clean shutdown writes that cache out, a held
                    power button does not -- and a machine wedged badly enough
                    that the user reaches for the button is exactly the machine
                    this log exists to describe. FlushFileBuffers is what forces
                    the data and the file's metadata onto the disk.
                    \u21d2 \u2605\u2605 RULE: "FLUSHED" HAS TWO MEANINGS AND ONLY ONE OF THEM
                      SURVIVES A POWER CUT. Decide which one the diagnostic
                      needs. Cost is one disk round-trip per line at the ~2
                      lines/second this log measured at -- and it is already
                      serialised behind g_log_cs, so no new contention. */
                 fflush(f);
                 { int fd = _fileno(f);
                   if (fd >= 0) {
                       HANDLE h = (HANDLE)_get_osfhandle(fd);
                       if (h != INVALID_HANDLE_VALUE && h != (HANDLE)(INT_PTR)-2)
                           FlushFileBuffers(h);
                   } }
                 fclose(f); }
    }
    LeaveCriticalSection(&g_log_cs);
#else
    (void)fmt;
#endif
}

/* Crash, hang and abrupt-exit reporting. Its own file so that diagnostics and
   balance work do not have to merge around each other; the C track's port
   carries #included .c files transitively, so this costs nothing to ship.
   Included here because it needs log_line above and crash_veh below needs
   it. */
#include "crashlog.c"

/* ================= PART 1: dinput8 proxy (forward to real) =========== */
static HMODULE g_real_dinput8 = NULL;
static void ensure_real_dinput8(void)
{
    if (!g_real_dinput8) {
        char p[MAX_PATH];
        UINT n = GetSystemDirectoryA(p, MAX_PATH);
        snprintf(p + n, sizeof(p) - n, "\\dinput8.dll");
        g_real_dinput8 = LoadLibraryA(p);
        if (!g_real_dinput8) log_line("PROXY ERROR: could not load real dinput8 at %s", p);
    }
}
static FARPROC real_proc(const char* name)
{
    ensure_real_dinput8();
    return g_real_dinput8 ? GetProcAddress(g_real_dinput8, name) : NULL;
}

__declspec(dllexport) HRESULT WINAPI DirectInput8Create(void* hinst, DWORD ver, const void* riid, void** out, void* outer)
{
    static HRESULT (WINAPI *fn)(void*,DWORD,const void*,void**,void*) = NULL;
    if (!fn) fn = (HRESULT (WINAPI*)(void*,DWORD,const void*,void**,void*))real_proc("DirectInput8Create");
    if (!fn) return 0x80004005; /* E_FAIL */
    return fn(hinst, ver, riid, out, outer);
}
/* The game only imports DirectInput8Create; every later input call goes to the
   real dinput8 COM object this returns, so no other exports are needed. */

/* ================= PART 2: Steam matchmaking hook ===================
 *  DO NOT REMOVE OR WEAKEN THIS SECTION. It is what keeps patched players
 *  in their own matchmaking pool: an unpatched client and a patched client
 *  playing each other desync, so the "issuer" tag/filter and the join guard
 *  are a correctness requirement, not a convenience. Any future edit to this
 *  file must leave PART 2 intact. */
#define VT_REQUEST_LIST    4   /* RequestLobbyList */
#define VT_ADD_NUM_FILTER  6
#define VT_DISTANCE_FILTER 9   /* AddRequestLobbyListDistanceFilter */
#define VT_JOIN_LOBBY      14
#define VT_GET_LOBBY_DATA  19
#define VT_SET_LOBBY_DATA  20

typedef void*         (*SteamMatchmaking_v009_t)(void);
typedef void          (*AddNumFilter_t)(void* self, const char* key, int value, int cmp);
typedef unsigned char (*SetLobbyData_t)(void* self, uint64_t lobby, const char* key, const char* value);
typedef uint64_t      (*JoinLobby_t)(void* self, uint64_t lobby);
typedef const char*   (*GetLobbyData_t)(void* self, uint64_t lobby, const char* key);
typedef uint64_t      (*RequestLobbyList_t)(void* self);
typedef void          (*DistanceFilter_t)(void* self, int eLobbyDistanceFilter);

static AddNumFilter_t o_AddNumFilter = NULL;
static SetLobbyData_t o_SetLobbyData = NULL;
static JoinLobby_t    o_JoinLobby    = NULL;
static RequestLobbyList_t o_RequestLobbyList = NULL;
static void**         g_vt           = NULL;
static int            g_issuer       = PATCH_ISSUER_DEFAULT;
static int            g_block        = 1;
static LONG           g_started      = 0;

static int file_exists(const char* name){ char p[MAX_PATH]; exe_dir_path(name,p,sizeof(p)); FILE* f=fopen(p,"r"); if(f){fclose(f);return 1;} return 0; }

static void load_settings(void)
{
    char path[MAX_PATH], buf[64];
    exe_dir_path("patch_ranked.txt", path, sizeof(path));
    FILE* f = fopen(path, "r");
    if (!f) log_line("WARNING: no patch_ranked.txt; using default code %d", g_issuer);
    else {
        if (fgets(buf,sizeof(buf),f)) {
            int v = atoi(buf);
            if (v!=0 && v!=8 && v!=1 && v!=256) { g_issuer=v; log_line("match code %d loaded", v); }
            else log_line("WARNING: invalid code '%d' (0/1/8/256 reserved); using %d", v, g_issuer);
        }
        fclose(f);
    }
    g_block = file_exists("patch_ranked_logonly.txt") ? 0 : 1;
    if (!g_block) log_line("JOIN guard = LOG-ONLY");
}

/* ================= PART 27: room member cap (TEST) ===================
 *  A room match holds two people. That was MEASURED on 2026-09-16 with three
 *  live clients on one pool code, so the cap is real and not a rig artefact.
 *  What was not known is WHERE it is enforced: Steam's lobby, or the game's
 *  own room UI before Steam is ever asked. Those need different fixes --
 *  SetLobbyMemberLimit reaches the first and can never reach the second --
 *  and only a log taken while a third client is refused tells them apart.
 *
 *  So this part is a PROBE first and a lever second. It sits on the same
 *  SteamMatchMaking009 vtable PART 2 already owns (4/6/9/14/19/20 up there,
 *  8/13/17/31/32/34 here -- one interface, ISteamMatchmaking009) and it:
 *
 *    1. LOGS every capacity-carrying call the game makes -- CreateLobby's
 *       cMaxMembers, SetLobbyMemberLimit, SetLobbyJoinable, the slots filter
 *       used when searching -- plus the member count on every join.
 *    2. RAISES the requested maximum to ROOM3_MEMBERS on the way through.
 *
 *  READING THE RESULT, which is the whole point of the build:
 *    * "CreateLobby(type N, max 2) -- raising to 3" appears, and the third
 *      client's JoinLobby runs and the host logs 3/3 members  -> the lobby
 *      layer accepts three and everything after this is the game's own room
 *      state and UI.
 *    * The host logs 3/3 but the third client sees nothing / is bounced by
 *      the room UI  -> Steam was never the cap; the refusal is in
 *      RoomMatchUiCtrl and this lever is finished, it cannot go further.
 *    * The third client logs no JOIN line at all  -> it never asked Steam.
 *      Same conclusion, one step earlier.
 *
 *  What this deliberately does NOT do: add a third role, a third UI slot, a
 *  rotation rule, or any netcode. The game has exactly two player roles
 *  (ROOMMATCH_PLAYER_HOST / ROOMMATCH_PLAYER_GUEST) and no spectator role.
 *  Read the research before extending it:
 *      DataChakka/guides/Nilsix researches/Three Player Room/
 *
 *  ⚠ A client that thinks a room holds three must not meet one that thinks
 *  it holds two, so this shifts the matchmaking issuer by ROOM3_POOL_TAG
 *  exactly as Meri's mode and Reawakening Battle do. Every client in the
 *  test must run this same DLL. */
/* ROOM3_CAP_ONLY=1 raises the member cap and does NOTHING else: no seat arm, no mute, no
   clamps, no probes, no vtable map. It exists to answer one question that neither the
   spectator work nor the crash work can answer without it -- "is this the engine, or is it
   us?" -- by putting a third member in a room with an otherwise stock loader. Anything
   that still breaks with this build is the game meeting a case it never shipped for. */
#ifndef ROOM3_CAP_ONLY
#define ROOM3_CAP_ONLY 0
#endif
/* ROOM3_GALLERY_PLAYBACK=1: the spectator's SOnlineAction+0xC34 goes 0 -> 1 at the first
   per-frame online update, which hands it to the engine's own gallery playback of the
   host's live stream (see P33 at patch_room3_setup_breadcrumb). */
#ifndef ROOM3_GALLERY_PLAYBACK
#define ROOM3_GALLERY_PLAYBACK 0
#endif
/* ROOM3_GALLERY_QUIET=1: once the spectator plays back, it sends no SOnlineAction battle
   packet (sync words, RoomPacket, ...). See P34 at room3_pkt_gate. */
#ifndef ROOM3_GALLERY_QUIET
#define ROOM3_GALLERY_QUIET ROOM3_GALLERY_PLAYBACK
#endif
#ifndef ROOM3_MEMBERS
#define ROOM3_MEMBERS        3     /* what CreateLobby/SetLobbyMemberLimit are forced to */
#endif
#ifndef ROOM3_POOL_TAG
#define ROOM3_POOL_TAG    4003     /* distinct from MERI 4002 and REAWAKEN 4001 */
#endif
#ifndef ROOM3_FORCE_JOINABLE
/* OFF for the first run, on purpose. The game closes a lobby with
   SetLobbyJoinable(false) both when it is FULL and when the match STARTS, and
   from inside this hook those two are indistinguishable -- forcing it open
   would invite a stranger into a running fight. Log it first, then decide. */
#define ROOM3_FORCE_JOINABLE 0
#endif

#define VT_SLOTS_FILTER     8   /* AddRequestLobbyListFilterSlotsAvailable */
#define VT_CREATE_LOBBY    13
#define VT_NUM_MEMBERS     17   /* GetNumLobbyMembers   */
#define VT_SET_MEMBER_LIM  31   /* SetLobbyMemberLimit  */
#define VT_GET_MEMBER_LIM  32   /* GetLobbyMemberLimit  */
#define VT_LEAVE_LOBBY     15   /* LeaveLobby           */
#define VT_SET_MEMBER_DATA 25   /* SetLobbyMemberData   */
#define VT_SET_JOINABLE    34   /* SetLobbyJoinable     */

typedef uint64_t      (*CreateLobby_t)(void* self, int eLobbyType, int cMaxMembers);
typedef void          (*LeaveLobby_t)(void* self, uint64_t lobby);
typedef void          (*SetMemberData_t)(void* self, uint64_t lobby, const char* k, const char* v);
typedef void          (*SlotsFilter_t)(void* self, int slots);
typedef int           (*NumMembers_t)(void* self, uint64_t lobby);
typedef unsigned char (*SetMemberLimit_t)(void* self, uint64_t lobby, int cMax);
typedef int           (*GetMemberLimit_t)(void* self, uint64_t lobby);
typedef unsigned char (*SetJoinable_t)(void* self, uint64_t lobby, unsigned char joinable);

/* The battle context the clamp stubs see, parked so the 30 s heartbeat can read the
   state out of it. Guessing at whether Spectator was ON cost a whole run: with the
   toggle ON the fighter list is built and only the seat index is -1; with it OFF the
   list is empty. Those two are one byte apart in the log and were indistinguishable. */
static void* volatile  g_room3_ctx         = NULL;
static int patch_slot(void** vt, int slot, void* hook, void** saved);  /* defined with PART 2 */
static volatile char    g_room3_is_spectator = 0;  /* set by the mode-2 arm stub     */
static volatile int     g_room3_mode = -1;         /* [obj+0x480] as the arm saw it  */
static volatile LONG64  g_room3_muted = 0;      /* battle-stream packets not sent */
static volatile LONG64  g_room3_gate_passed = 0; /* participant test waved through */
static volatile LONG64  g_room3_state1_forced = 0; /* state-1 exit bypassed     */
static volatile LONG64  g_room3_state1_seen   = 0; /* 0x8018CC reached at all   */
static volatile LONG64  g_room3_setup_seen    = 0; /* 0x801800 entered at all   */
static volatile LONG64  g_room3_slot26_seen   = 0; /* SOnlineAction slot 26     */
static volatile LONG64  g_room3_reg_seen      = 0; /* the callback registration */
static volatile LONG64  g_room3_s26[5];            /* five points inside slot 26 */
static volatile LONG    g_room3_evt[0x1000];       /* one slot per slot-26 message id */
static volatile LONG    g_room3_st[0x1000];        /* one slot per battle-machine state */
static volatile LONG64  g_room3_sm_calls  = 0;     /* calls into the state machine       */
static volatile LONG    g_room3_sm_last   = 0;     /* the state it was last entered with */
static void*            g_room3_sm_this   = 0;     /* and on which object                */
static volatile LONG64  g_room3_stw_calls = 0;     /* writes of state = 0x32             */
static volatile LONG    g_room3_stw_seen  = 0;
static volatile LONG64  g_room3_stw2_calls = 0;    /* writes by the handler's default tail */
static volatile LONG    g_room3_trace     = 0;     /* shared budget for the ordered trace  */
static volatile LONG    g_room3_sm_caller = 0;     /* the RVA that drives the machine      */
static volatile LONG    g_room3_sm_callers = 0;
static volatile LONG    g_room3_wait_calls = 0;    /* frames spent in state 0x32's case   */
static volatile LONG    g_room3_wait_lines = 0;
static volatile LONG    g_room3_forced_ready = 0;  /* the rendezvous answered locally    */
static volatile LONG64  g_room3_up_calls   = 0;    /* calls into the per-frame update    */
static volatile LONG    g_room3_up_last    = 0;
static volatile LONG    g_room3_up_caller  = 0;
static volatile LONG    g_room3_up_callers = 0;
static ULONGLONG        g_room3_up_tick    = 0;
/* one row per instance of the class that gets ticked; four is more than the game uses */
/* One row per sub-object seen at the gate exe+0x8A0D29. Before this, a single shared
   `last` turned several objects' bytes into one bogus time series -- see the header of
   patch_p9.py. Keyed by pointer, never reused, and a full table just stops recording. */
#define ROOM3_SUB_MAX 16
static void*     g_room3_sub[ROOM3_SUB_MAX];
static LONG      g_room3_sub_byte[ROOM3_SUB_MAX];
static LONG64    g_room3_sub_pass[ROOM3_SUB_MAX];
static LONG64    g_room3_sub_skip[ROOM3_SUB_MAX];
static LONG64    g_room3_sub_seen[ROOM3_SUB_MAX];   /* EVERY visit, pass or skip: without
                                                       this a frozen row's byte is just the
                                                       last value read, which is stale if
                                                       the gate stopped being called */
static ULONGLONG g_room3_sub_stick[ROOM3_SUB_MAX];  /* when it was last visited          */
static ULONGLONG g_room3_sub_ptick[ROOM3_SUB_MAX];  /* when it was last let through      */
static void*     g_room3_sub_bytes[ROOM3_SUB_MAX]; /* [obj+8], the object carrying +0xF0 */
static LONG      g_room3_sub_word[ROOM3_SUB_MAX];  /* [obj+0x7C], the gate BEFORE the byte:
                                                      must be 4 or the element is skipped  */
static LONG64    g_room3_sub_walk[ROOM3_SUB_MAX];  /* visits to the loop body itself, which
                                                      happen whatever +0x7C says           */
static ULONGLONG g_room3_sub_wtick[ROOM3_SUB_MAX];

/* The container the driving loop walks: exe+0x8A0CF5 reads [this+0x70]..[this+0x78] and
   falls straight past the body when they are equal, silently. */
static volatile LONG64 g_room3_walk_calls = 0;
static ULONGLONG       g_room3_walk_tick  = 0;
static void*           g_room3_walk_this  = 0;
static LONG            g_room3_walk_count = -1;
static LONG            g_room3_walk_min   = -1;
static LONG            g_room3_walk_max   = -1;
static volatile LONG   g_room3_walk_lines = 0;
/* the ENTRY of the same function, so "still called" and "still reaches the loop head" stop
   being the same number */
static volatile LONG64 g_room3_fn_calls  = 0;
static ULONGLONG       g_room3_fn_tick   = 0;
static LONG            g_room3_fn_caller = 0;
static volatile LONG   g_room3_fn_lines  = 0;
/* slot 5 of TAppRootTask / SteamTask: its entry, and the point just before it calls the
   function above -- the two must be compared, never conflated */
static volatile LONG64 g_room3_t5_calls  = 0;
static ULONGLONG       g_room3_t5_tick   = 0;
static LONG            g_room3_t5_caller = 0;
static volatile LONG   g_room3_t5_lines  = 0;
static volatile LONG64 g_room3_t5_reach  = 0;
static volatile LONG   g_room3_exit      = 0;   /* RVA of the last exit slot 5 took */
static volatile LONG   g_room3_exits_on  = 0;
#define ROOM3_EXIT_MAX 24
static volatile LONG64 g_room3_exit_n[ROOM3_EXIT_MAX];   /* one counter per exit */
static unsigned int    g_room3_exit_rva[ROOM3_EXIT_MAX];
static ULONGLONG       g_room3_t5_rtick  = 0;
static void*     g_room3_bp_sub   = 0;
/* RVA 0x1CE1D39: the one-shot "skip the next frame" byte tested at exe+0x8575AA. Four
   sites set it, all rip-relative, so a tally by faulting RIP is the only honest way to
   say which one is doing it on a given client. */
#define ROOM3_SKIPFLAG_RVA 0x1CE1D39
#define ROOM3_WR_MAX 12
#define ROOM3_THR_MAX 12
static volatile LONG   g_room3_thr_state[ROOM3_THR_MAX];  /* the value at 0x801BF1 */
static volatile LONG64 g_room3_thr_n[ROOM3_THR_MAX];
static volatile LONG64 g_room3_thr_calls = 0;
static volatile LONG   g_room3_nop_done  = 0;
static volatile LONG   g_room3_abort_n  = 0;
static volatile LONG   g_room3_bit_lines = 0;
static volatile LONG64 g_room3_bit_set   = 0;
static volatile LONG   g_room3_bit_last  = -1;
static volatile LONG   g_room3_to_lines  = 0;
/* The pluggable input Brains, resolved from RTTI rather than guessed. */
#define ROOM3_VT_BRAINBASE 0x145B978
#define ROOM3_VT_BRAINPAD  0x142C048
#define ROOM3_VT_BRAINAI   0x142C0C8
#define ROOM3_VT_BRAINTRAI 0x1463C90
static volatile LONG64 g_room3_brain_tick = 0;
/* P26: creations per Brain installer, per client */
#define ROOM3_EP_MAX 16
static void*          g_room3_lsm      = 0;    /* the OnlineLiveStreamingDataManager */
static volatile LONG   g_room3_lsm_kind = -99;  /* kind of the last Start             */
static void* volatile  g_room3_sa       = 0;    /* SOnlineAction, from the update entry */
static volatile LONG64 g_room3_flips    = 0;    /* spectator role 0 -> 1 (playback)     */
static volatile LONG64 g_room3_gal_send = 0;    /* live-stream packets shipped          */
static volatile LONG64 g_room3_gal_recv = 0;    /* live-stream packets received         */
static volatile LONG64 g_room3_handoffs = 0;    /* P35: end-of-match handoffs           */
static ULONGLONG       g_room3_starve_t0 = 0;   /* P35: when the queue went empty at 0x190 */
static volatile LONG64 g_room3_name_clamp = 0;  /* P36: result-screen name index clamped */
static ULONGLONG       g_room3_result_t0 = 0;   /* P36: when the result menu came up      */
static ULONGLONG       g_room3_result_log = 0;  /* P41: last sync-word dump on that screen */
static volatile LONG64 g_room3_rematch = 0;     /* P36: rematches followed                */
static volatile LONG64 g_room3_toroom  = 0;     /* P36: returns to the room followed      */
static volatile LONG64 g_room3_skips   = 0;     /* P37: jumps forward to the live edge    */
static volatile LONG64 g_room3_idx_src = 0;     /* P38: index clamped at the copy         */
static volatile LONG64 g_room3_norestart = 0;   /* P39: 0x462 answered with 0x45A         */
/* P34: every PacketData class this client sends, by vtable, and what the gate did */
#define ROOM3_PK_MAX 32
static void* volatile  g_room3_pk_vt[ROOM3_PK_MAX];
static const char*     g_room3_pk_name[ROOM3_PK_MAX];
static volatile LONG64 g_room3_pk_sent[ROOM3_PK_MAX];
static volatile LONG64 g_room3_pk_drop[ROOM3_PK_MAX];
static volatile char   g_room3_pk_ours[ROOM3_PK_MAX];  /* 1 = an SOnlineAction class */
static volatile LONG   g_room3_pk_n = 0;
static const char*     g_room3_ep_name[ROOM3_EP_MAX];
static volatile LONG64 g_room3_ep_n[ROOM3_EP_MAX];
static volatile LONG   g_room3_ep_lines[ROOM3_EP_MAX];
static volatile LONG   g_room3_ep_count = 0;
static volatile LONG   g_room3_ct_lines = 0;
static volatile LONG64 g_room3_ct_n[8];      /* control types 0..7 seen at vfunc75 */
static volatile LONG   g_room3_brain_line = 0;
static LONG            g_room3_brain_seen[4];   /* offset per seat, and the class id */
static float           g_room3_to_now    = 0.0f;
static float           g_room3_to_then   = 0.0f;
static volatile LONG64 g_room3_thr_skip  = 0;
static volatile LONG   g_room3_wr_rip[ROOM3_WR_MAX];
static volatile LONG64 g_room3_wr_n[ROOM3_WR_MAX];

#define ROOM3_OBJ_MAX 4
static void*     g_room3_obj[ROOM3_OBJ_MAX];
static LONG64    g_room3_obj_calls[ROOM3_OBJ_MAX];
static LONG      g_room3_obj_state[ROOM3_OBJ_MAX];
static ULONGLONG g_room3_obj_tick[ROOM3_OBJ_MAX];
static volatile LONG64  g_room3_tick_calls   = 0;  /* the scene tick above the update    */
static volatile LONG    g_room3_tick_caller  = 0;
static volatile LONG    g_room3_tick_callers = 0;
static ULONGLONG        g_room3_tick_tick    = 0;
static volatile LONG64  g_room3_reach_calls  = 0;  /* frames that reach the slot-27 call */
static ULONGLONG        g_room3_reach_tick   = 0;
static volatile LONG64  g_room3_drive_calls  = 0;  /* the gate above slot 11             */
static volatile LONG    g_room3_drive_lines  = 0;
static volatile LONG    g_room3_reach_caller = 0;
static volatile LONG    g_room3_reach_callers = 0;
static ULONGLONG        g_room3_sm_tick   = 0;     /* when it was last driven              */
static void*            g_room3_stw_this  = 0;
#ifndef ROOM3_HWBP
#define ROOM3_HWBP 1
#endif
/* ⚠ DEFAULT 0, AND THE 1 WAS MEASURED WRONG. Forcing the branch at exe+0x8A0D29 does make
   the object tick again -- and the tick then dies at exe+0x6ACD04 reading [rcx+0x390] with
   rcx = [r14+0x440] = NULL (spectator, 2026-09-18 07:28, stack: 0x8A0D6A -> 0x802B44).
   So that byte does not mean "paused", it means "this object's +0x440 is not built yet",
   and stepping over it just moves the failure from a freeze to a crash. Kept as a flag
   because the probe beside it is still the measurement that matters. */
#ifndef ROOM3_FORCE_TICK
#define ROOM3_FORCE_TICK 0
#endif
/* The load-wait throttle at exe+0x801BF1: state <= 0x12C makes slot 5 drop its next
   frame. Measured 2026-09-18: the spectator sits at 0xC9 and cannot advance because
   advancing needs the frames the throttle removes. Default 0 -- the measurement comes
   first, and the arm is a separate decision. */
/* The barrier's fourth exit: bit 0x400 of the fighter flag word at the awaited seat.
   Measured zero on the spectator at essai #125, and the battle ends ten seconds in. */
#ifndef ROOM3_FORCE_BATTLE_BIT
#define ROOM3_FORCE_BATTLE_BIT 1
#endif
#ifndef ROOM3_NO_THROTTLE
#define ROOM3_NO_THROTTLE 0
#endif
#ifndef ROOM3_FORCE_READY
#define ROOM3_FORCE_READY 1
#endif
#ifndef ROOM3_MUTE_SPECTATOR
#define ROOM3_MUTE_SPECTATOR 1
#endif
static void* volatile   g_room3_mm    = NULL;   /* the ISteamMatchmaking object   */
static uint64_t volatile g_room3_lobby = 0;     /* the lobby the room is in       */
static CreateLobby_t    o_CreateLobby    = NULL;
static NumMembers_t     o_NumMembers     = NULL;
static SlotsFilter_t    o_SlotsFilter    = NULL;
static SetMemberLimit_t o_SetMemberLimit = NULL;
static SetJoinable_t    o_SetJoinable    = NULL;

/* The two numbers that say whether a third client ever reached the lobby layer
   at all. Slots 17 and 32 are not hooked, so this cannot recurse. */
static void room3_state(void* self, uint64_t lobby, const char* tag)
{
    int n, lim;
    if (!g_vt || !self || !lobby) return;
    n   = o_NumMembers ? o_NumMembers(self, lobby)
                       : ((NumMembers_t)g_vt[VT_NUM_MEMBERS])(self, lobby);
    lim = ((GetMemberLimit_t)g_vt[VT_GET_MEMBER_LIM])(self, lobby);
    log_line("ROOM3: %s -- lobby %llu holds %d/%d members",
             tag, (unsigned long long)lobby, n, lim);
}
/* The room UI polls the member count every frame, so this is the cheapest place
   to watch a third client arrive -- but only a CHANGE is worth a line. This is
   the decisive measurement on the HOST: if it ever prints 3, three members are
   in the Steam lobby and everything after that is the game's own room state. */
static int hk_NumMembers(void* self, uint64_t lobby)
{
    static int last = -1;
    int n = o_NumMembers(self, lobby);
    g_room3_mm = self; g_room3_lobby = lobby;   /* what the P2P watch needs */
    if (n != last) {
        last = n;
        log_line("ROOM3: member count now %d (lobby %llu, limit %d)",
                 n, (unsigned long long)lobby,
                 g_vt ? ((GetMemberLimit_t)g_vt[VT_GET_MEMBER_LIM])(self, lobby) : -1);
    }
    return n;
}

/* ---- PART 27, the P2P watch (READ-ONLY) --------------------------------
 *  THE QUESTION IT ANSWERS, and it is the one everything now hangs on.
 *
 *  With Spectator ON the third client enters the battle, renders the stage,
 *  has `fighters 0 and 0` -- nothing was ever built for it -- and the game's
 *  own net layer drops it. It does NOT leave the Steam lobby: no LeaveLobby
 *  call, and the host still counts three members. So the lobby is fine and
 *  the peer-to-peer session is not.
 *
 *  Steam can be asked about that directly. `ISteamNetworking006::
 *  GetP2PSessionState` reports, per remote user, whether a session is
 *  active, whether it is still connecting, which error ended it, and whether
 *  it is relayed. Polling it for every lobby member, on all three clients,
 *  says exactly one of two things:
 *
 *    * the two players never open a session with the spectator at all
 *      -> the host must be made to send to a third endpoint. That is netcode
 *         to write, not a byte to patch, and the rotation design is the
 *         cheaper answer.
 *    * a session opens and then fails with an error
 *      -> the error names the cause (4 = timeout, 3 = destination not logged
 *         in, 2 = no rights, 1 = target not running the app) and there may be
 *         something to fix.
 *
 *  ⚠ READ-ONLY, deliberately. Nothing here patches a vtable, sends a packet
 *  or accepts a session: it reads state Steam already keeps. A probe that
 *  changes the thing it measures is how the last two runs contradicted each
 *  other.
 *
 *  Slot 6 is `GetP2PSessionState` in ISteamNetworking004 through 006; the
 *  game uses 006 (confirmed in §3 of the research). Slot 18 is
 *  `GetLobbyMemberByIndex`, from the same table PART 2 indexes. */
typedef void*         (*SteamNetworking_v006_t)(void);
typedef unsigned char (*GetP2PSessionState_t)(void* self, uint64_t remote, void* out);
/* ⚠ CSteamID is RETURNED, and it declares constructors -- so MSVC x64 returns it
   through a hidden first-argument pointer, not in RAX. Calling this as if it
   returned a uint64 puts `lobby` where that pointer belongs and the callee writes
   to it: an instant access violation the moment a lobby exists. Measured on
   2026-09-16, a crash on room creation.
   The asymmetry is real and is why PART 2 has been right for months: as an
   ARGUMENT a CSteamID has a trivial copy constructor and travels in a register;
   only the return goes through memory. */
typedef void*         (*MemberByIndex_t)(void* self, uint64_t* ret, uint64_t lobby, int idx);
#define VT_MEMBER_BY_IDX   18
#define VT_NET_P2P_STATE    6

/* Packet flow per peer. The session being ACTIVE says Steam would carry a packet;
   it does not say the game sends one. These two counters are the difference between
   "the players stop talking to the spectator when the match starts" and "it is being
   told everything and gives up by itself". Pass-through hooks: nothing is added,
   dropped, delayed or rewritten. */
#define VT_NET_SEND         0   /* SendP2PPacket */
#define VT_NET_READ         2   /* ReadP2PPacket */
typedef unsigned char (*SendP2P_t)(void* self, uint64_t remote, const void* data,
                                  unsigned int cub, int sendtype, int channel);
typedef unsigned char (*ReadP2P_t)(void* self, void* dest, unsigned int cubDest,
                                  unsigned int* msgsize, uint64_t* remote, int channel);
static SendP2P_t o_SendP2P = NULL;
static ReadP2P_t o_ReadP2P = NULL;
/* Packet TYPES, read as the first byte of each payload. The spectator receives ~60
   packets a second and still waits on the loading screen, so the question is no longer
   "does it get data" but "does it get the SAME data a player gets". All three clients
   run this build, so the diff between a player's type list and the spectator's is the
   message that never reaches a third party. */
static volatile LONG64 g_pkt_rx_type[256];
static volatile LONG64 g_pkt_tx_type[256];
static volatile LONG   g_pkt_rx_seen[256];
/* The three low-volume types carry the control traffic -- the high-volume 03 and 06 are
   the two players' per-frame streams. Dumping the control ones on a player and on the
   spectator at the same moment is the cheapest way to find the message that lets a client
   leave the loading screen. Capped hard: this runs on the game thread. */
/* ⚠ One shared cap does NOT work here, measured 2026-09-16: the spectator sends far more
   control packets than it receives, so a single 400-line budget was spent entirely on TX
   and the log showed zero RX -- which reads exactly like "it receives nothing" and is a
   lie. The budget is per direction AND per type. */
#ifndef ROOM3_DUMP_CAP
#define ROOM3_DUMP_CAP 30
#endif
static volatile LONG   g_pkt_dumped_rx[256];
static volatile LONG   g_pkt_dumped_tx[256];
static int room3_is_control(unsigned char t) { return t == 0x04 || t == 0x0E || t == 0x40; }
static void room3_dump(const char* dir, unsigned char* p, unsigned int len, uint64_t who)
{
    char hex[64]; unsigned int i, n = len > 16 ? 16 : len;
    volatile LONG* budget = (dir[0] == 'R') ? &g_pkt_dumped_rx[p[0]] : &g_pkt_dumped_tx[p[0]];
    if (InterlockedIncrement(budget) > ROOM3_DUMP_CAP) return;
    for (i = 0; i < n; i++) snprintf(hex + i*3, sizeof(hex) - i*3, "%02X ", p[i]);
    log_line("ROOM3/dump: %s type %02X len %u %s %llu : %s", dir, p[0], len,
             dir[0] == 'R' ? "from" : "to", (unsigned long long)who, hex);
}
static uint64_t volatile g_p2p_id[8];
static volatile LONG64   g_p2p_sent[8], g_p2p_recv[8];
/* per (peer, type) for the two input streams and the rest -- the cross that the per-peer
   and per-type totals never gave. [peer][0] = 0x03, [1] = 0x06, [2] = everything else */
static volatile LONG64   g_p2p_tx3[8][3], g_p2p_rx3[8][3];
static int room3_stream_col(unsigned char t) { return t == 0x03 ? 0 : t == 0x06 ? 1 : 2; }
/* P29: a few input-stream packets per (peer, type), and who in the game reads them */
static volatile LONG   g_p2p_sdump[8][2];
static volatile LONG64 g_p2p_sseq[8][2];      /* packets of that (peer, type) seen */
/* P31: the input histories -- first byte N, then N 16-bit frames, 2N+1 bytes (or +20) */
static volatile LONG64 g_p2p_hseq[8];
static volatile LONG   g_p2p_hdump[8];
static volatile LONG64 g_p2p_hist[8];          /* histories received per peer          */
static volatile LONG   g_p2p_hmax[8];          /* longest history seen per peer        */
static volatile LONG   g_p2p_slen[8][2];      /* length of the last one dumped    */
static volatile LONG   g_rx_caller[6];
static volatile LONG   g_rx_callers = 0;
/* An input history, if this packet is one: 2N+1 bytes, or 2N+1 behind a 20-byte header. */
static int room3_history_frames(unsigned char* p, unsigned int len, unsigned int* start)
{
    unsigned int nn = p[0];
    if (nn < 0x08 || nn > 0x7F) return -1;
    if (len == 2 * nn + 1)      { *start = 1;  return (int)nn; }
    if (len == 2 * nn + 21)     { *start = 21; return (int)nn; }
    return -1;
}

static void room3_decode_history(unsigned char* p, unsigned int len, uint64_t who, int peer)
{
    unsigned int st = 0, k;
    int nn = room3_history_frames(p, len, &st);
    char out[12 * 5 + 1]; int at = 0;
    LONG64 seq;
    if (nn < 0 || peer < 0) return;
    g_p2p_hist[peer]++;
    if (nn > g_p2p_hmax[peer]) g_p2p_hmax[peer] = nn;
    if (!g_room3_ctx) return;                       /* the battle has not started yet */
    seq = InterlockedIncrement64(&g_p2p_hseq[peer]);
    if ((seq % 120) != 1) return;
    if (InterlockedIncrement(&g_p2p_hdump[peer]) > 20) return;
    for (k = 0; k < (unsigned)nn && k < 12; k++) {
        unsigned short v = (unsigned short)(p[st + 2*k] | (p[st + 2*k + 1] << 8));
        at += snprintf(out + at, sizeof(out) - at, "%04X ", v);
    }
    log_line("ROOM3/hist: #%lld from %llu -- %d frame(s)%s, first 12: %s", (long long)seq,
             (unsigned long long)who, nn, st == 21 ? " behind a 20-byte header" : "", out);
}

static void room3_dump_stream(unsigned char* p, unsigned int len, uint64_t who, int peer)
{
    char hex[3 * 32 + 1]; unsigned int i, n = len > 32 ? 32 : len;
    int col = p[0] == 0x03 ? 0 : 1;
    LONG64 seq;
    if (peer < 0) return;
    seq = InterlockedIncrement64(&g_p2p_sseq[peer][col]);
    /* ⚠ Not "the first N": that budget was spent entirely in the lobby handshake at
       essai #132. Dump on a change of length, and every 400th regardless, so the sampling
       runs through the battle instead of stopping at the door. */
    if ((LONG)len == g_p2p_slen[peer][col] && (seq % 400) != 0) return;
    if (InterlockedIncrement(&g_p2p_sdump[peer][col]) > 16) return;
    g_p2p_slen[peer][col] = (LONG)len;
    for (i = 0; i < n; i++) snprintf(hex + i*3, sizeof(hex) - i*3, "%02X ", p[i]);
    log_line("ROOM3/sdump: RX #%lld type %02X len %u from %llu : %s", (long long)seq, p[0],
             len, (unsigned long long)who, hex);
}
static int room3_peer_slot(uint64_t id)
{
    int i;
    for (i = 0; i < 8; i++) if (g_p2p_id[i] == id) return i;
    for (i = 0; i < 8; i++) if (g_p2p_id[i] == 0) { g_p2p_id[i] = id; return i; }
    return -1;
}
static unsigned char hk_SendP2P(void* self, uint64_t remote, const void* data,
                                unsigned int cub, int sendtype, int channel)
{
    int i = room3_peer_slot(remote);
    if (ROOM3_MUTE_SPECTATOR && g_room3_is_spectator && data && cub) {
        unsigned char t = ((const unsigned char*)data)[0];
        if (t == 0x03 || t == 0x06) {      /* the two per-frame player streams */
            g_room3_muted++;
            return 1;                      /* claim success: nothing is queued or retried */
        }
    }
    if (i >= 0) g_p2p_sent[i]++;
    if (i >= 0 && data && cub)
        g_p2p_tx3[i][room3_stream_col(((const unsigned char*)data)[0])]++;
    if (data && cub) {
        g_pkt_tx_type[((const unsigned char*)data)[0]]++;
        if (room3_is_control(((const unsigned char*)data)[0]))
            room3_dump("TX", (unsigned char*)data, cub, remote);
    }
    return o_SendP2P(self, remote, data, cub, sendtype, channel);
}
static unsigned char hk_ReadP2P(void* self, void* dest, unsigned int cubDest,
                                unsigned int* msgsize, uint64_t* remote, int channel)
{
    unsigned char r = o_ReadP2P(self, dest, cubDest, msgsize, remote, channel);
    {   /* the game's receive function -- the dispatch on the type byte is there or below */
        unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
        LONG rva = (LONG)((unsigned char*)__builtin_return_address(0) - mod);
        int k, known = 0;
        for (k = 0; k < 6 && k < g_rx_callers; k++) if (g_rx_caller[k] == rva) known = 1;
        if (!known && g_rx_callers < 6) {
            g_rx_caller[g_rx_callers] = rva;
            InterlockedIncrement(&g_rx_callers);
            log_line("ROOM3/rx: ReadP2PPacket is called from exe+0x%X", (unsigned)rva);
        }
    }
    if (r && remote) {
        int i = room3_peer_slot(*remote);
        if (i >= 0) {
            g_p2p_recv[i]++;
            if (dest && msgsize && *msgsize) {
                unsigned char t = ((unsigned char*)dest)[0];
                g_p2p_rx3[i][room3_stream_col(t)]++;
                if (t == 0x03 || t == 0x06)
                    room3_dump_stream((unsigned char*)dest, *msgsize, *remote, i);
                room3_decode_history((unsigned char*)dest, *msgsize, *remote, i);
            }
        }
    }
    if (r && dest && msgsize && *msgsize) {
        unsigned char t = ((unsigned char*)dest)[0];
        g_pkt_rx_type[t]++;
        if (InterlockedCompareExchange(&g_pkt_rx_seen[t], 1, 0) == 0)
            log_line("ROOM3/pkt: FIRST packet of type 0x%02X (%u bytes) from %llu", t,
                     *msgsize, (unsigned long long)(remote ? *remote : 0));
        if (room3_is_control(t))
            room3_dump("RX", (unsigned char*)dest, *msgsize, remote ? *remote : 0);
    }
    return r;
}

/* P2PSessionState_t, as the Steamworks header lays it out. */
typedef struct {
    unsigned char  active, connecting, err, relay;
    int            queued_bytes, queued_packets;
    unsigned int   remote_ip;
    unsigned short remote_port;
} room3_p2p_t;


static const char* room3_p2p_err(unsigned char e)
{
    switch (e) {
        case 0: return "none";
        case 1: return "target not running the app";
        case 2: return "no rights to play";
        case 3: return "destination not logged in";
        case 4: return "TIMEOUT -- no reply";
        default: return "unknown";
    }
}

/* ---- PART 27, the stall sampler ----------------------------------------
 *  The spectator sits on the loading screen forever. Rather than reverse the
 *  protocol to find which message never comes, ask the process what it is
 *  actually executing: sample every thread's RIP a few times a second and
 *  keep a histogram of the exe-resident addresses. A client waiting on a
 *  condition spends its time in the code that tests it, so the top of that
 *  histogram IS the wait -- and the same histogram taken on a player that is
 *  playing normally says which entries are just the engine running.
 *
 *  The suspension is one GetThreadContext long and nothing is logged while a
 *  thread is held: log_line takes a lock, and taking a lock with the game
 *  suspended is how a probe deadlocks the thing it measures. */
#define ROOM3_RIP_SLOTS 64
static uint64_t volatile g_rip_addr[ROOM3_RIP_SLOTS];
static volatile LONG64   g_rip_hits[ROOM3_RIP_SLOTS];

static void room3_rip_record(uint64_t rva)
{
    int i;
    rva &= ~0xFULL;                  /* 16-byte buckets: a loop is a region, not an address */
    for (i = 0; i < ROOM3_RIP_SLOTS; i++) {
        if (g_rip_addr[i] == rva) { g_rip_hits[i]++; return; }
        if (g_rip_addr[i] == 0)   { g_rip_addr[i] = rva; g_rip_hits[i] = 1; return; }
    }
}
static void room3_rip_sample(void)
{
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
    THREADENTRY32 te;
    DWORD me = GetCurrentThreadId(), pid = GetCurrentProcessId();
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    if (snap == INVALID_HANDLE_VALUE || !mod) return;
    te.dwSize = sizeof(te);
    if (Thread32First(snap, &te)) {
        do {
            HANDLE th;
            CONTEXT ctx;
            if (te.th32OwnerProcessID != pid || te.th32ThreadID == me) continue;
            th = OpenThread(THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT, FALSE, te.th32ThreadID);
            if (!th) continue;
            memset(&ctx, 0, sizeof(ctx));
            ctx.ContextFlags = CONTEXT_CONTROL;
            if (SuspendThread(th) != (DWORD)-1) {
                if (GetThreadContext(th, &ctx) && ctx.Rip) {
                    unsigned char* a = (unsigned char*)ctx.Rip;
                    if (a > mod && a < mod + 0x2000000) room3_rip_record((uint64_t)(a - mod));
                }
                ResumeThread(th);
            }
            CloseHandle(th);
        } while (Thread32Next(snap, &te));
    }
    CloseHandle(snap);
}
static void room3_rip_log(void)
{
    char line[420]; int off = 0, shown = 0, i, j;
    for (j = 0; j < 8; j++) {                     /* eight passes, highest first */
        int best = -1; LONG64 bv = 0;
        for (i = 0; i < ROOM3_RIP_SLOTS; i++) {
            if (!g_rip_addr[i] || g_rip_hits[i] < 0) continue;
            if (g_rip_hits[i] > bv) { bv = g_rip_hits[i]; best = i; }
        }
        if (best < 0 || bv < 3) break;
        off += snprintf(line + off, sizeof(line) - off, "%s0x%llX:%lld", shown++ ? " " : "",
                        (unsigned long long)g_rip_addr[best], (long long)bv);
        g_rip_hits[best] = -g_rip_hits[best] - 1;      /* mark as reported, keep the count */
        if (off > (int)sizeof(line) - 24) break;
    }
    /* ⚠ CLEARED after every report, deliberately. Cumulative counts made the first
       measurement useless: the player's history still held its menus and the stalled
       client's wait was buried in a common address. Each line is now a snapshot of the
       last 30 s, so a player's line and a stalled client's line can be read against
       each other directly. */
    for (i = 0; i < ROOM3_RIP_SLOTS; i++) { g_rip_addr[i] = 0; g_rip_hits[i] = 0; }
    if (shown) log_line("ROOM3/rip: busiest exe addresses in the last 30 s (rva:samples) -- %s", line);
}

static DWORD WINAPI room3_p2p_watch(LPVOID unused)
{
    HMODULE steam;
    SteamNetworking_v006_t getnet;
    void*  net = NULL;
    void** nvt = NULL;
    uint64_t seen_id[8];
    room3_p2p_t seen[8];
    int nseen = 0, i, j, said = 0;

    (void)unused;
    memset(seen_id, 0, sizeof(seen_id));
    memset(seen, 0, sizeof(seen));

    steam = GetModuleHandleA("steam_api64.dll");
    if (!steam) return 0;
    getnet = (SteamNetworking_v006_t)GetProcAddress(steam, "SteamAPI_SteamNetworking_v006");
    if (!getnet) { log_line("ROOM3/p2p: SteamAPI_SteamNetworking_v006 missing -- no watch"); return 0; }

    for (;;) {
        int k;
        for (k = 0; k < 20; k++) { room3_rip_sample(); Sleep(100); }  /* 2 s of sampling */
        if (!net) {
            net = getnet();
            if (!net) continue;
            nvt = *(void***)net;
            if (!nvt) { net = NULL; continue; }
            if (patch_slot(nvt, VT_NET_SEND, (void*)&hk_SendP2P, (void**)&o_SendP2P) &&
                patch_slot(nvt, VT_NET_READ, (void*)&hk_ReadP2P, (void**)&o_ReadP2P))
                log_line("ROOM3/p2p: watching peer sessions every 2 s, and counting packets "
                         "both ways (pass-through)");
            else
                log_line("ROOM3/p2p: session watch only -- the packet counters did not install");
        }
        if (!g_vt || !g_room3_mm || !g_room3_lobby) continue;
        {
            void*    mm    = (void*)g_room3_mm;
            uint64_t lobby = g_room3_lobby;
            int n = o_NumMembers ? o_NumMembers(mm, lobby) : 0;
            if (n > 8) n = 8;
            for (i = 0; i < n; i++) {
                uint64_t id = 0;
                room3_p2p_t st;
                int slot = -1;
                unsigned char ok;
                ((MemberByIndex_t)g_vt[VT_MEMBER_BY_IDX])(mm, &id, lobby, i);
                if (!id) continue;
                memset(&st, 0, sizeof(st));
                ok = ((GetP2PSessionState_t)nvt[VT_NET_P2P_STATE])(net, id, &st);
                for (j = 0; j < nseen; j++) if (seen_id[j] == id) { slot = j; break; }
                if (slot < 0 && nseen < 8) { slot = nseen++; seen_id[slot] = id; memset(&seen[slot],0xFF,sizeof(st)); }
                if (slot < 0) continue;
                if (memcmp(&seen[slot], &st, sizeof(st)) == 0) continue;
                seen[slot] = st;
                log_line("ROOM3/p2p: member %llu -- session %s%s, error %s, %d byte(s) queued, "
                         "relay %d%s", (unsigned long long)id,
                         ok ? "" : "(no state) ",
                         st.active ? "ACTIVE" : (st.connecting ? "connecting" : "none"),
                         room3_p2p_err(st.err), st.queued_bytes, st.relay,
                         st.active ? "" : " -- nobody is talking to this member");
            }
            {   /* packet flow, printed only when it moves */
                static LONG64 lasts[8], lastr[8];
                int k;
                for (k = 0; k < 8; k++) {
                    if (!g_p2p_id[k]) continue;
                    if (g_p2p_sent[k] == lasts[k] && g_p2p_recv[k] == lastr[k]) continue;
                    log_line("ROOM3/p2p: peer %llu -- %lld sent, %lld received (+%lld/+%lld "
                             "in the last 2 s)", (unsigned long long)g_p2p_id[k],
                             (long long)g_p2p_sent[k], (long long)g_p2p_recv[k],
                             (long long)(g_p2p_sent[k]-lasts[k]), (long long)(g_p2p_recv[k]-lastr[k]));
                    lasts[k] = g_p2p_sent[k]; lastr[k] = g_p2p_recv[k];
                }
            }
            if (!said && nseen) { said = 1;
                log_line("ROOM3/p2p: %d member(s) in the lobby are being watched; a member "
                         "that never goes ACTIVE is one the others never opened a session "
                         "with", nseen); }
        }
    }
}

static uint64_t hk_CreateLobby(void* self, int eLobbyType, int cMaxMembers)
{
    int want = ROOM3_MEMBERS;
    if (cMaxMembers < want) {
        log_line("ROOM3: CreateLobby(type %d, max %d) -- raising max to %d",
                 eLobbyType, cMaxMembers, want);
        cMaxMembers = want;
    } else {
        log_line("ROOM3: CreateLobby(type %d, max %d) -- already >= %d, left alone. "
                 "The game does NOT ask Steam for a two-member lobby, so the cap is "
                 "somewhere else.", eLobbyType, cMaxMembers, want);
    }
    return o_CreateLobby(self, eLobbyType, cMaxMembers);
}
static unsigned char hk_SetLobbyMemberLimit(void* self, uint64_t lobby, int cMax)
{
    int want = ROOM3_MEMBERS;
    log_line("ROOM3: SetLobbyMemberLimit(lobby %llu, %d)%s",
             (unsigned long long)lobby, cMax, cMax < want ? " -- raising" : "");
    if (cMax < want) cMax = want;
    return o_SetMemberLimit(self, lobby, cMax);
}
static unsigned char hk_SetLobbyJoinable(void* self, uint64_t lobby, unsigned char joinable)
{
    room3_state(self, lobby, joinable ? "SetLobbyJoinable(true)" : "SetLobbyJoinable(false)");
    if (!joinable && ROOM3_FORCE_JOINABLE) {
        log_line("ROOM3: forcing the lobby to stay joinable (ROOM3_FORCE_JOINABLE=1)");
        joinable = 1;
    }
    return o_SetJoinable(self, lobby, joinable);
}
/* Its own matchmaking pool, for the same reason Meri's mode has one: a client
   that believes a room holds three and one that believes it holds two disagree
   about a shared thing, and nothing else in either build says so. */
static void room3_pool_shift(void)
{
    if (ROOM3_POOL_TAG) {
        int before = g_issuer;
        g_issuer += ROOM3_POOL_TAG;
        log_line("ROOM3: matchmaking issuer %d -> %d -- this build raises the room "
                 "member cap to %d, so it gets its own pool. Every client in the test "
                 "must run this same DLL.", before, g_issuer, ROOM3_MEMBERS);
    } else {
        log_line("ROOM3: pool tag disabled -- this build shares the normal matchmaking "
                 "pool with clients that cap a room at two");
    }
}
static void room3_backtrace(const char* tag);   /* defined next to alloc_backtrace */

/* WHO drops the spectator. The room loses the third member (`member count now 2`)
   whenever the client is disconnected, so the game does call LeaveLobby -- this
   says from where, which is the difference between "a state machine gave up" and
   "the transmission layer refuses a third endpoint". */
static LeaveLobby_t o_LeaveLobby = NULL;
static void hk_LeaveLobby(void* self, uint64_t lobby)
{
    room3_state(self, lobby, "LeaveLobby -- this client is leaving the room");
    room3_backtrace("leave");
    o_LeaveLobby(self, lobby);
}

/* The state the battle is actually in on this client, printed by the 30 s
   heartbeat. Everything is read through the context the clamp stubs park in
   g_room3_ctx, so it only reports once a battle has been entered. */
static void room3_state_log(void)
{
    unsigned char* c = (unsigned char*)g_room3_ctx;
    if (!c) return;
    __try {
        unsigned char* box = *(unsigned char**)(c + 0xBC0);
        long long a0 = 0, a1 = 0;
        int idx_a = *(int*)(c + 0xC3C), idx_b = *(int*)(c + 0xC40);
        int role  = *(int*)(c + 0xC34), state = *(int*)(c + 0xCE0);
        int flag  = *(unsigned char*)(c + 0xC3A);
        if (box) {
            a0 = (*(long long*)(box + 0x10) - *(long long*)(box + 0x08)) / 8;
            a1 = (*(long long*)(box + 0x28) - *(long long*)(box + 0x20)) / 8;
        }
        log_line("ROOM3/state: seats %d/%d, role %d, state %d, flag(0xC3A) %d, "
                 "fighters %lld and %lld -- seats -1 mean no seat of my own, and a "
                 "non-empty fighter list means Spectator was ON",
                 idx_a, idx_b, role, state, flag, a0, a1);
        /* The battle state machine's own step counter (+0xCD0) and the one global its
           step-1 arm tests. Step 1 is where a stuck spectator sits: it advances only when
           a singleton answers ready twice, or when the global at RVA 0x18EC038 is zero
           (exe+0x802C4D). Printing both says which of the two is holding it, on the very
           client that is stuck, instead of guessing from the disassembly. */
        {
            unsigned char* mod2 = (unsigned char*)GetModuleHandleA(NULL);
            log_line("ROOM3/step: battle step %d (+0xCD0), clock %d s (+0xC38), "
                     "gate global 0x18EC038 = %d",
                     *(int*)(c + 0xCD0), (int)(*(unsigned short*)(c + 0xC38)),
                     mod2 ? *(int*)(mod2 + 0x18EC038) : -1);
        }
        /* THE READINESS WORD THE EXE ITSELF TESTS.
           exe+0x807190 is the battle-load barrier: it walks the fighter vector at
           [ctx+0xBC0]+0x08 .. +0x10 and, for each entry, does

               cmp word ptr [fighter], 0   ;  je -> return false

           so a single zero there means "not ready", and the whole thing sits under a
           30-second timeout that reads the timestamp at ctx+0xCE8 -- the field that never
           advances on the spectator. This logs precisely that word, per fighter, rather
           than an offset assumed from another context (the previous readout here did the
           latter and printed nonsense). */
        if (box) {
            unsigned char** vec = *(unsigned char***)(box + 0x08);
            unsigned char** end = *(unsigned char***)(box + 0x10);
            int k = 0;
            for (; vec && vec < end && k < 4; vec++, k++) {
                unsigned char* f = *vec;
                if (!f) { log_line("ROOM3/ready: fighter %d is NULL", k); continue; }
                log_line("ROOM3/ready: fighter %d word[0] = 0x%04X %s", k,
                         *(unsigned short*)f,
                         *(unsigned short*)f ? "(ready)" : "(NOT ready -- the barrier fails here)");
            }
        }
        /* ⚠ A fighter-health readout used to sit here and it was WRONG: it assumed
           [box+0x08] is a vector of fighter pointers and that +0x10BC / +0x10C0 apply to
           them, and it printed things like "konpaku 2417851639229258349412352000". The
           offsets are right for a fighter (see the Konpaku memory) but these pointers are
           not fighters. Removed rather than left to be read as data. The honest
           is-this-client-simulating signal is the row diff below: +0xCE0 moves on a
           client that simulates and stays put on the spectator. */
        /* The anchor-and-diff the capture guides describe, applied to the one object
           both clients have: the host is PLAYING and the spectator is STUCK, same build,
           same structure. Whatever decides "you may leave the loading screen" is a field
           that differs between the two dumps. 0xC00..0xD00 covers every field already
           identified (0xBC0 container, 0xC34 role, 0xC3A flag, 0xC3C/0xC40 seats, 0xC48,
           0xCCA, 0xCD4, 0xCE0) with room around them. */
        {
            unsigned int off;
            for (off = 0xC00; off < 0xD00; off += 32) {
                char hex[128]; int k;
                for (k = 0; k < 32; k++) snprintf(hex + k*3, sizeof(hex) - k*3, "%02X ", c[off+k]);
                log_line("ROOM3/ctx: +%03X : %s", off, hex);
            }
        }
    } __except(EXCEPTION_EXECUTE_HANDLER) {
        log_line("ROOM3/state: context %p no longer readable (battle torn down)", (void*)c);
    }
}

static SetMemberData_t o_SetMemberData = NULL;
static void hk_SetMemberData(void* self, uint64_t lobby, const char* k, const char* v)
{
    log_line("ROOM3/lobby: SetLobbyMemberData \"%s\" = \"%s\"", k ? k : "(null)", v ? v : "(null)");
    o_SetMemberData(self, lobby, k, v);
}
static void hk_SlotsFilter(void* self, int slots)
{
    /* A search that demands free slots hides a full lobby. If the third client
       never SEES the room, this line is the first place to look. */
    log_line("ROOM3: search asks for %d free slot(s)", slots);
    o_SlotsFilter(self, slots);
}
static void hk_AddNumFilter(void* self, const char* key, int value, int cmp)
{
    if (key && strcmp(key,"issuer")==0) { log_line("SEARCH: filtering issuer %d -> %d", value, g_issuer); value=g_issuer; }
    o_AddNumFilter(self,key,value,cmp);
}
static unsigned char hk_SetLobbyData(void* self, uint64_t lobby, const char* key, const char* value)
{
    char b[16];
    if (key && strcmp(key,"issuer")==0) { snprintf(b,sizeof(b),"%d",g_issuer); log_line("HOST: tagging issuer %s -> %s", value?value:"(null)", b); value=b; }
    else if (ENABLE_ROOM3 && key)
        /* Every other room setting, verbatim. The room UI shows who is spectating, so the
           status has to travel -- and lobby data is where it would travel. This names the
           key instead of us taking anyone's word for what the toggle was set to. */
        log_line("ROOM3/lobby: SetLobbyData \"%s\" = \"%s\"", key, value ? value : "(null)");
    return o_SetLobbyData(self,lobby,key,value);
}
static uint64_t hk_JoinLobby(void* self, uint64_t lobby)
{
    if (g_vt) {
        GetLobbyData_t get = (GetLobbyData_t)g_vt[VT_GET_LOBBY_DATA];
        const char* v = get(self, lobby, "issuer");
        if (v && v[0]) {
            int their = atoi(v);
            int mismatch = (their != g_issuer);
            if (mismatch && g_block) { log_line("JOIN BLOCKED: lobby issuer %d != our code %d (prevents desync)", their, g_issuer); return 0; }
            log_line("JOIN %s: lobby issuer %d (our code %d)", mismatch?"MISMATCH-allowed":"OK", their, g_issuer);
        } else log_line("JOIN: issuer not readable yet -- allowing");
        /* PART 27. Printed on the JOINING client: proof that it reached the
           lobby layer at all. No such line while a third client is refused
           means the game's own UI refused before Steam was ever asked. */
        if (ENABLE_ROOM3) room3_state(self, lobby, "JoinLobby requested");
    }
    return o_JoinLobby(self, lobby);
}
static uint64_t hk_RequestLobbyList(void* self)
{
    /* The game never sets a distance filter, so Steam defaults to region-limited
       matching. Force WORLDWIDE (3) before every search so players match across
       regions regardless of their Steam download region. Covers ranked, free
       battle, and room-match browsing (all go through RequestLobbyList). */
    if (g_vt) {
        DistanceFilter_t df = (DistanceFilter_t)g_vt[VT_DISTANCE_FILTER];
        df(self, 3);
        log_line("REGION: forced worldwide distance filter before search");
    }
    return o_RequestLobbyList(self);
}
static int patch_slot(void** vt, int slot, void* hook, void** saved)
{
    DWORD old;
    if (vt[slot]==hook){*saved=NULL;return 1;}
    if (!VirtualProtect(&vt[slot],sizeof(void*),PAGE_READWRITE,&old)) return 0;
    *saved=vt[slot]; vt[slot]=hook; VirtualProtect(&vt[slot],sizeof(void*),old,&old); return 1;
}
/* Which of try_install's three "not yet" gates is closed. Written on every
   poll and read by the waiter, because all three used to print the SAME line --
   "steam_api64 still absent" -- and only the first of them is that.

   ★ 2026-09-22. A host client sat for 19 minutes on that message while
   steam_api64.dll was demonstrably loaded in the process (checked against the
   module list of the live pid). The module was there; SteamAPI_SteamMatchmaking_v009
   was returning NULL. The log named the wrong thing, the rig's advice was built
   on the log, and the advice sent the reader to the title screen -- which had
   nothing to do with it. One sentence for three states is not a diagnostic. */
static volatile LONG g_mm_gate = 0;   /* 0 no module, 1 no interface, 2 no vtable */
static const char* mm_gate_name(LONG g)
{
    switch (g) {
    case 0:  return "steam_api64.dll is NOT LOADED in this process -- the game has "
                    "not reached its Steam init yet";
    case 1:  return "steam_api64.dll IS loaded, but SteamAPI_SteamMatchmaking_v009() "
                    "returns NULL -- the module is in, SteamAPI_Init has not run";
    default: return "SteamMatchmaking exists but its vtable pointer is NULL -- "
                    "the interface is half-built";
    }
}
static int try_install(void)
{
    HMODULE steam = GetModuleHandleA("steam_api64.dll");
    if (!steam) { g_mm_gate = 0; return 0; }
    SteamMatchmaking_v009_t get = (SteamMatchmaking_v009_t)GetProcAddress(steam,"SteamAPI_SteamMatchmaking_v009");
    if (!get) { log_line("ERROR: SteamAPI_SteamMatchmaking_v009 missing"); return -1; }
    void* mm = get(); if (!mm) { g_mm_gate = 1; return 0; }
    void** vt = *(void***)mm; if (!vt) { g_mm_gate = 2; return 0; }
    g_vt = vt;
    if (!patch_slot(vt,VT_ADD_NUM_FILTER,(void*)&hk_AddNumFilter,(void**)&o_AddNumFilter) ||
        !patch_slot(vt,VT_SET_LOBBY_DATA,(void*)&hk_SetLobbyData,(void**)&o_SetLobbyData) ||
        !patch_slot(vt,VT_JOIN_LOBBY,(void*)&hk_JoinLobby,(void**)&o_JoinLobby) ||
        !patch_slot(vt,VT_REQUEST_LIST,(void*)&hk_RequestLobbyList,(void**)&o_RequestLobbyList)) { log_line("ERROR: vtable patch failed"); return -1; }
    log_line("HOOKS INSTALLED (in game) -- pool code %d, join-guard %s, region=worldwide", g_issuer, g_block?"ON":"log-only");
    if (ENABLE_ROOM3) {
        /* Same vtable, same patch_slot, separate report: PART 2 is a correctness
           requirement and PART 27 is a test, so a failure here must never read
           as a failure there. */
        if (!patch_slot(vt,VT_CREATE_LOBBY,   (void*)&hk_CreateLobby,        (void**)&o_CreateLobby)   ||
            !patch_slot(vt,VT_SET_MEMBER_LIM, (void*)&hk_SetLobbyMemberLimit,(void**)&o_SetMemberLimit)||
            !patch_slot(vt,VT_NUM_MEMBERS,    (void*)&hk_NumMembers,         (void**)&o_NumMembers)    ||
            !patch_slot(vt,VT_SET_JOINABLE,   (void*)&hk_SetLobbyJoinable,   (void**)&o_SetJoinable)   ||
            !patch_slot(vt,VT_LEAVE_LOBBY,    (void*)&hk_LeaveLobby,         (void**)&o_LeaveLobby)    ||
            !patch_slot(vt,VT_SET_MEMBER_DATA,(void*)&hk_SetMemberData,      (void**)&o_SetMemberData) ||
            !patch_slot(vt,VT_SLOTS_FILTER,   (void*)&hk_SlotsFilter,        (void**)&o_SlotsFilter))
            log_line("ROOM3: vtable patch FAILED -- the capacity probe is not installed, "
                     "and this run measures nothing");
        else
            log_line("ROOM3: capacity probe installed -- lobbies forced to %d members, "
                     "force-joinable %s. Every capacity call is logged from here on.",
                     ROOM3_MEMBERS, ROOM3_FORCE_JOINABLE ? "ON" : "off");
            CreateThread(NULL, 0, room3_p2p_watch, NULL, 0, NULL);
    }
    return 1;
}
static void patch_version_string(void)
{
    /* Title-screen shows "Ver.<gameversion>". Rename the "Ver." prefix (in the
       game exe's .rdata) to "ReBalance " so patched clients clearly read
       "ReBalance <ver>". Only 12 bytes are free before the next string, so the
       marker is length-limited. This only happens while the DLL is loaded
       (patch mode); vanilla is untouched. */
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    if (!mod) return;
    unsigned char* v = mod + 0x14a031c;   /* RVA of the "Ver." title string */
    if (!(v[0]=='V' && v[1]=='e' && v[2]=='r' && v[3]=='.')) {
        log_line("VERSION: 'Ver.' not at expected location (game updated?) -- title rename skipped");
        return;
    }
    static const char repl[] = "ReBalance ";   /* 10 chars + NUL = 11 <= 12 free */
    DWORD old;
    if (VirtualProtect(v, sizeof(repl), PAGE_READWRITE, &old)) {
        memcpy(v, repl, sizeof(repl));
        VirtualProtect(v, sizeof(repl), old, &old);
        log_line("VERSION: title renamed -> 'ReBalance <ver>'");
    }
}
static void patch_yamamoto_selfcost(void)
{
    /* Sublimation-Kikon self-cost removal (exe memory patch).
       At RVA 0x5311FC the game loads xmm1 = 2.0 -- the number of the caster's
       own konpaku (Soul stocks) to spend -- immediately before the single call
       to the sublimation-Kikon self-cost routine (VA 0x1404EB980). Replacing
       that load with 'xorps xmm1,xmm1' (amount = 0) + NOPs makes the cost 0.
       The routine still runs, so the sublimation cutscene is fully preserved,
       and 0x1404EB980 has exactly one caller and sits in no vtable, so nothing
       else in the game reaches it.

         orig:  F3 0F 10 0D 5C F1 F8 00   movss xmm1,[rip+0xF8F15C]   ; =2.0
         new :  0F 57 C9 90 90 90 90 90   xorps xmm1,xmm1 ; nop*5     ; =0.0

       RVA VERIFIED 2026-08-05 against the shipping build: the 8 original bytes
       are present at 0x5311FC in the clean Steam exe (and in Clean_EXE/). The
       "bytes not at expected RVA" line people were seeing in patch_ranked.log
       was NOT a stale RVA -- it was a dev machine whose exe had the same 8
       bytes permanently baked in on disk (the V7_NOSELFCOST static exe), so the
       one-directional memcmp could never match. The guard below now recognises
       the already-patched form and says so instead of crying "game updated?".

       SCOPE CAVEAT (read before re-tuning): the patched instruction lives in
       _Do_call (RVA 0x531140) of a GLOBAL std::function<void(ComponentPtr<
       OPlayableBase>, tsd::string)> installed at static-init (RVA 0x22560).
       Its only filter is  name.find("evo_ct_sp_break02") != npos  &&
       name.find("_maxout") == npos . There is no [fighter+0xC00] character-id
       compare in the lambda or in 0x1404EB980, and 37 pl*.tadjpkg define a
       non-_maxout evo_ct_sp_break02 -- so statically this reads as roster-wide
       (every character's awakened Kikon), not Yamamoto-only. Shipped and
       playtested on Yamamoto (V7/V8); the wider effect has never been checked
       in game. If the awakened Kikon self-cost matters for other characters,
       this needs an id gate rather than an amount edit. */
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    if (!mod) return;
    unsigned char* p = mod + 0x5311FC;
    static const unsigned char orig[8] = {0xF3,0x0F,0x10,0x0D,0x5C,0xF1,0xF8,0x00};
    static const unsigned char repl[8] = {0x0F,0x57,0xC9,0x90,0x90,0x90,0x90,0x90};
    if (memcmp(p, repl, 8) == 0) {
        log_line("SELFCOST: already 0 at RVA 0x5311FC (exe pre-patched on disk) -- nothing to do");
        return;
    }
    if (memcmp(p, orig, 8) != 0) {
        log_line("SELFCOST: bytes not at expected RVA 0x5311FC (game updated?) -- skipped");
        return;
    }
    DWORD old;
    if (VirtualProtect(p, 8, PAGE_EXECUTE_READWRITE, &old)) {
        memcpy(p, repl, 8);
        VirtualProtect(p, 8, old, &old);
        FlushInstructionCache(GetCurrentProcess(), p, 8);
        log_line("SELFCOST: sublimation-Kikon self-cost -> 0 (RVA 0x5311FC)");
    } else {
        log_line("SELFCOST: VirtualProtect failed at RVA 0x5311FC");
    }
}
static void patch_byakuya_evo_icon(void)
{
    /* Byakuya (pl022) unique stance icon kept visible in evo -- Pl22-ONLY.
       CORRECTED 2026-07-22 (Aizen/Stark bugfix). The form getter at VA
       0x1402065C0 is a SHARED base-class method: vtable slot 22 of 27 UI
       classes (Pl22 Byakuya AND Pl20 Aizen, Pl33 Stark, ...). Patching its body
       in place forced form=0 for all of them, so Aizen/Stark icons flickered.
       Fix: give ONLY Byakuya's class a private copy of the getter that always
       returns form 0, and repoint just his vtable slot (VA 0x141440678 /
       RVA 0x1440678). Shared method left untouched; all other classes normal. */
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    if (!mod) return;
    void**         slot   = (void**)(mod + 0x1440678);   /* Pl22 vtable[22] */
    unsigned char* shared = mod + 0x2065C0;              /* shared getter   */
    static const unsigned char sig[8] = {0x48,0x8B,0x41,0x08,0x48,0x8B,0x88,0x10};
    if ((unsigned char*)*slot != shared || memcmp(shared, sig, 8) != 0) {
        log_line("BYAKUYA_ICON: Pl22 vt[22]/getter not as expected (game updated?) -- skipped");
        return;
    }
    static const unsigned char stub[40] = {
        0x48,0x8B,0x41,0x08, 0x48,0x8B,0x88,0x10,0x01,0x00,0x00,
        0x48,0x85,0xC9, 0x74,0x14, 0x83,0x79,0x08,0x00, 0x74,0x0E,
        0x48,0x8B,0x80,0xF0,0x00,0x00,0x00,
        0x31,0xC0,0x90,0x90,0x90,0x90, 0xC3,
        0x8B,0x40,0x44, 0xC3
    };
    void* code = VirtualAlloc(NULL, sizeof(stub),
                              MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!code) { log_line("BYAKUYA_ICON: VirtualAlloc failed"); return; }
    memcpy(code, stub, sizeof(stub));
    FlushInstructionCache(GetCurrentProcess(), code, sizeof(stub));
    DWORD old;
    if (VirtualProtect(slot, sizeof(void*), PAGE_READWRITE, &old)) {
        *slot = code;
        VirtualProtect(slot, sizeof(void*), old, &old);
        log_line("BYAKUYA_ICON: Pl22-only form getter repointed (icon in evo; Aizen/Stark/others unaffected)");
    } else {
        log_line("BYAKUYA_ICON: VirtualProtect(vtable slot) failed");
    }
}
static void patch_aizen_kikon_counter(void)
{
    /* Aizen (pl020) Kikon Counter now costs the 5 flames ONLY -- Pl20-ONLY.
       The engine calls this mechanic KIKON_COUNTER (string at VA 0x1414700C0,
       three bytes after "ct_reset"); it is the R3+L3 cancel of an opponent's
       Kikon. It is entirely hardcoded: pl020.tadjpkg's 1_normal_ct_ct_reset is
       four blocks of cutscene + invulnerability with no cost, and there is no
       ct_reset node in his tcmb at all.

       Shipped, it also required a FULL reverse gauge and consumed all of it.
       The gauge is two floats on the fighter -- +0x10B0 max, +0x10B4 value --
       drawn as rebirth_gauge1/2/3, i.e. the "bars" players count.

         RVA 0x4F2B6F  76 05                 jbe -> EB 05 jmp   (requirement always passes)
         RVA 0x4F3240  44 89 85 54 02 00 00  mov [rbp+0x254],r8d -> 7-byte nop
         RVA 0x4F3308  E8 43 BA CF FF        call 0x1401EED50    -> 5-byte nop

       Site 2 is the deduction. It sits inside a stack copy of
       self+0xFA0..+0x1340 that is copied straight back, and it is the only
       modification between copy-out and copy-back -- so nopping the single
       store makes the whole copy a no-op.

       Site 3 is the HUD widget, and it is NOT optional. 0x1401EED50 is
       event-driven, not a per-frame resync, so removing the deduction without
       it would empty the DISPLAYED gauge while the value stayed full.

       Left alone deliberately: the flames cost (0x1404F31C3 still zeroes
       UNIQUE_0 at fighter+0x1A34), the once-per-match flag (+0x1A5C), the
       base-form gate, and the shipped blocklist that stops the counter working
       against pl000-pl004 and pl033.

       Pl20-ONLY is proven, not assumed: all three sites are inside 0x1404F2980
       (the gate) and 0x1404F3070 (the executor), whose callers trace back
       through vtables 0x14146D748 / 0x141468C88 to constructors reachable only
       from pl020's behaviour slot at 0x1418E1130. */
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    if (!mod) return;

    unsigned char* gate = mod + 0x4F2B6F;   /* jbe  -> jmp */
    unsigned char* dedu = mod + 0x4F3240;   /* mov  -> nop */
    unsigned char* hud  = mod + 0x4F3308;   /* call -> nop */

    static const unsigned char sig_gate[2] = {0x76,0x05};
    static const unsigned char sig_dedu[7] = {0x44,0x89,0x85,0x54,0x02,0x00,0x00};
    static const unsigned char sig_hud [5] = {0xE8,0x43,0xBA,0xCF,0xFF};

    static const unsigned char rep_gate[2] = {0xEB,0x05};                          /* jmp +5        */
    static const unsigned char rep_dedu[7] = {0x0F,0x1F,0x80,0x00,0x00,0x00,0x00}; /* nop dword[rax]*/
    static const unsigned char rep_hud [5] = {0x0F,0x1F,0x44,0x00,0x00};           /* nop dword[rax+rax] */

    /* Some dev installs run an exe that already has these three sites baked in
       on disk. Recognise that instead of reporting it as a game update -- the
       mechanic is live either way and there is nothing to write. */
    if (memcmp(gate, rep_gate, sizeof(rep_gate)) == 0 &&
        memcmp(dedu, rep_dedu, sizeof(rep_dedu)) == 0 &&
        memcmp(hud,  rep_hud,  sizeof(rep_hud))  == 0) {
        log_line("AIZEN_COUNTER: already applied (exe pre-patched on disk) -- nothing to do");
        return;
    }

    /* All three or none -- a half-patched counter would deduct without paying
       back, or drain the gauge with the requirement already lifted. */
    if (memcmp(gate, sig_gate, sizeof(sig_gate)) != 0 ||
        memcmp(dedu, sig_dedu, sizeof(sig_dedu)) != 0 ||
        memcmp(hud,  sig_hud,  sizeof(sig_hud))  != 0) {
        log_line("AIZEN_COUNTER: sites not as expected (game updated?) -- skipped, cost unchanged");
        return;
    }

    struct { unsigned char* at; const unsigned char* to; SIZE_T n; } w[3] = {
        { gate, rep_gate, sizeof(rep_gate) },
        { dedu, rep_dedu, sizeof(rep_dedu) },
        { hud,  rep_hud,  sizeof(rep_hud)  },
    };
    for (int i = 0; i < 3; i++) {
        DWORD old;
        if (!VirtualProtect(w[i].at, w[i].n, PAGE_EXECUTE_READWRITE, &old)) {
            log_line("AIZEN_COUNTER: VirtualProtect failed at site %d -- PARTIAL, expect odd costs", i);
            return;
        }
        memcpy(w[i].at, w[i].to, w[i].n);
        VirtualProtect(w[i].at, w[i].n, old, &old);
    }
    FlushInstructionCache(GetCurrentProcess(), gate, 1);
    log_line("AIZEN_COUNTER: Pl20-only -- Kikon Counter now costs 5 flames only (reverse gauge free)");
}

/* ================= Aizen (pl020) SP1 flame cost ======================
 *  !!! DISABLED 2026-08-06 -- THIS IS THE CRASH. Do not re-enable until the
 *  !!! two defects below are fixed AND it has been retested offline.
 *
 *  Intent: sp_atk01 consumes flames, 1 (base) / 3 (evo). SP2 untouched.
 *  We detour what was believed to be Aizen's per-frame unique-action handler
 *  (VA 0x140148970 / RVA 0x148970) and add an sp_atk01 branch.
 *    combat  = [rcx+0x20];  char-id [combat+0xC00]==0x14 (20=Aizen)
 *    flames  = float [combat+0x1A34]      (0..5, confirmed via CE)
 *  Handler runs every frame -> edge-detect so we subtract once per activation.
 *
 *  DEFECT 1 (fatal) -- af_action_is() is reading 8 bytes too low.
 *  rdx is NOT the tsd::string; the string is a MEMBER at rdx+8. The game
 *  itself proves this twice:
 *      RVA 0x1489DE  mov r8,[rdi+0x20]      ; capacity
 *      RVA 0x1489E2  lea rax,[rdi+8]        ; &string   <-- +8, not +0
 *      RVA 0x1489E6  mov rcx,[rax+0x10]     ; length    = [rdi+0x18]
 *      RVA 0x1489F3  mov rdx,[rax]          ; data ptr  = [rdi+0x08]
 *      RVA 0x4225BC  lea rcx,[rbx+8] / mov rdx,[rcx+0x10] / cmp [rcx+0x18],0x10
 *  So the real layout relative to the pointer we are handed is
 *      +0x08 data-or-SSO-buffer, +0x18 length, +0x20 capacity.
 *  af_action_is() instead reads capacity from +0x18 (that is the LENGTH) and
 *  takes the string base from +0x00 (that is the record field BEFORE the
 *  string). Consequences:
 *    - name shorter than 16 chars -> it compares the 8 bytes preceding the
 *      string, so the flame cost NEVER fires. The feature has never worked.
 *    - name 16 chars or longer  -> it does *(const char**)(record+0) and
 *      dereferences it. record+0 is a plain POD scalar field, not a pointer
 *      (an 11 KB function that walks these 0x180-byte records --
 *      RVA 0x3FC6E0..0x3FF1F0 -- reads +0x18/+0x28/+0x48/+0x54/+0x88/+0x100/
 *      +0x13C.. and never once dereferences +0x00). Reading through it is an
 *      access violation unless the field happens to be 0.
 *  68 of pl020's 211 action names are >= 16 chars, including
 *  sp_break01_maxout(17), ct_sp_break01_maxout(20),
 *  evo_ct_sp_break01_maxout(24), evo_ct_revolut_rev(18) (cocoon -> evo),
 *  bind_dam_bind_loop(18) and neckbind_dam_*(24..31) -- i.e. every single
 *  reported repro. The handler self-filters on [combat+0xC00]==0x14 at RVA
 *  0x1489A2, which is why ONLY Aizen crashes.
 *
 *  DEFECT 2 (why it was never noticed) -- wrong anchor. RVA 0x148970 is not
 *  the SP1 handler. It compares the action name against "sp_atk02" (RVA
 *  0x1489FC) and "evo_sp_atk02" (RVA 0x148A1E) -- it is the SP2 handler. It
 *  has exactly one caller (RVA 0x422594) and is in no vtable.
 *
 *  Minor: the hook reads [rcx+0x20] and [combat+0xC00] before the original's
 *  own guards ([rcx+0x40] non-null, [r8+8] non-zero) have run, so it also
 *  touches the object in states the game treats as not-yet-valid.
 *
 *  Anchors + derivation: Patched Aizen/V6/. */
#define AIZEN_UNIQ_RVA   0x148970
#define AIZEN_CHARID_OFF 0xC00
#define AIZEN_ID         0x14
#define AIZEN_FLAME_OFF  0x1A34
#define AIZEN_COST_BASE  1.0f
#define AIZEN_COST_EVO   3.0f

typedef long long (*aizen_uniq_t)(void* rcx, void* rdx, void* r8, void* r9);
static aizen_uniq_t o_aizen_uniq = NULL;   /* -> trampoline (stolen bytes + jmp back) */
static void* g_af_obj[2] = {0,0};          /* per-instance edge state (P1/P2) */
static int   g_af_in [2] = {0,0};

static int af_action_is(void* actctx, const char* want)
{
    if (!actctx) return 0;
    unsigned long long cap = *(unsigned long long*)((char*)actctx + 24);
    const char* s = (cap >= 16) ? *(const char**)actctx : (const char*)actctx;
    if (!s) return 0;
    int i = 0;
    for (; want[i]; ++i) if (s[i] != want[i]) return 0;
    return s[i] == '\0';
}

static long long hk_aizen_uniq(void* rcx, void* rdx, void* r8, void* r9)
{
    void* combat = rcx ? *(void**)((char*)rcx + 0x20) : NULL;
    if (combat && *(int*)((char*)combat + AIZEN_CHARID_OFF) == AIZEN_ID) {
        int base = af_action_is(rdx, "sp_atk01");
        int evo  = base ? 0 : af_action_is(rdx, "evo_sp_atk01");
        int slot = (g_af_obj[0]==combat) ? 0 : (g_af_obj[1]==combat) ? 1
                 : (g_af_obj[0]==NULL)   ? 0 : 1;
        g_af_obj[slot] = combat;
        if (base || evo) {
            if (!g_af_in[slot]) {                /* rising edge = SP1 activation */
                g_af_in[slot] = 1;
                float  cost  = evo ? AIZEN_COST_EVO : AIZEN_COST_BASE;
                float* flame = (float*)((char*)combat + AIZEN_FLAME_OFF);
                float  f     = *flame - cost;
                if (f < 0.0f) f = 0.0f;           /* clamp; hard-block = phase 2 */
                *flame = f;
                log_line("AIZEN_FLAME: sp_atk01(%s) -%.0f -> %.1f flames",
                         evo ? "evo" : "base", cost, f);
            }
        } else {
            g_af_in[slot] = 0;                    /* left the move -> re-arm */
        }
    }
    return o_aizen_uniq(rcx, rdx, r8, r9);        /* always run the original */
}

static void patch_aizen_flamecost(void)
{
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    if (!mod) return;
    unsigned char* entry = mod + AIZEN_UNIQ_RVA;
    /* 13-byte position-independent prologue: mov [rsp+10],rbx / push rdi / sub rsp,0xD0 */
    static const unsigned char expect[13] = {
        0x48,0x89,0x5C,0x24,0x10, 0x57, 0x48,0x81,0xEC,0xD0,0x00,0x00,0x00
    };
    if (o_aizen_uniq) { log_line("AIZEN_FLAME: already installed -- skipped"); return; }
    if (memcmp(entry, expect, sizeof expect) != 0) {
        log_line("AIZEN_FLAME: prologue moved (game update?) -- skipped");
        return;
    }
    unsigned char* tramp = (unsigned char*)VirtualAlloc(
        NULL, 64, MEM_COMMIT|MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!tramp) { log_line("AIZEN_FLAME: VirtualAlloc failed"); return; }
    memcpy(tramp, entry, 13);                                    /* stolen prologue */
    unsigned long long ret = (unsigned long long)(entry + 13);
    tramp[13]=0x48; tramp[14]=0xB8; memcpy(tramp+15,&ret,8);     /* mov rax,entry+13 */
    tramp[23]=0xFF; tramp[24]=0xE0;                              /* jmp rax          */
    FlushInstructionCache(GetCurrentProcess(), tramp, 64);
    o_aizen_uniq = (aizen_uniq_t)tramp;

    unsigned char patch[13];
    unsigned long long hk = (unsigned long long)&hk_aizen_uniq;
    patch[0]=0x48; patch[1]=0xB8; memcpy(patch+2,&hk,8);         /* mov rax,&hk      */
    patch[10]=0xFF; patch[11]=0xE0; patch[12]=0x90;              /* jmp rax ; nop    */
    DWORD old;
    if (VirtualProtect(entry, 13, PAGE_EXECUTE_READWRITE, &old)) {
        memcpy(entry, patch, 13);
        VirtualProtect(entry, 13, old, &old);
        FlushInstructionCache(GetCurrentProcess(), entry, 13);
        log_line("AIZEN_FLAME: installed at RVA 0x%X (flame off 0x%X)",
                 AIZEN_UNIQ_RVA, AIZEN_FLAME_OFF);
    } else {
        o_aizen_uniq = NULL;
        log_line("AIZEN_FLAME: VirtualProtect failed");
    }
}

/* ================= brand-new stage ids ===============================
 *  Shipped, a stage id the game did not ship with is selectable, has its name
 *  and thumbnail, spawns both fighters -- and shows an EMPTY arena. That is a
 *  hard-coded whitelist in the exe, not a missing data file.
 *
 *  `.data` at VA 0x1418EDF00 (RVA 0x18EDF00) is a 71-row table of
 *  {const char* label; const char* id;}, 16 bytes per row: three MapEdit sample
 *  maps, then bg000_00..07, bg000_10..14, bg001_00..12, bg002_00..05,
 *  bg002_07..15, bg003_00..05, bg004_00..03, bg_adv_001..017, testmap_00.
 *
 *  ActionSceneBase::LoadBattleArea (VA 0x1406A42F0 / RVA 0x6A42F0) copies all
 *  71 ids into a local vector (bound `cmp esi,0x47` at RVA 0x6A4421), linearly
 *  searches it for the requested id, and:
 *
 *      RVA 0x6A4488   48 3B FB              cmp rdi, rbx    ; rdi == end() => miss
 *      RVA 0x6A448B   0F 84 FB 03 00 00     je  0x1406A488C ; <-- THE GATE
 *      RVA 0x6A4491   ...                   the entire field load: "<id>_project",
 *                                           FieldSetup::Load -> LoadEditMap ->
 *                                           BuildMap -> the geometry
 *
 *  0x1406A488C is `xor r15d,r15d` and rejoins the shared tail that arms the
 *  AreaMove_In_/Out_ triggers, camera and spawn -- so an unknown id skips the
 *  map load and NOTHING else. Exactly the reported symptom. It is also why
 *  "adopting" a story-only id works: all nineteen of those are in the table.
 *
 *  We nop the je, so any id reaches the loader. This is data-driven -- it works
 *  for an unlimited number of new stages with no further exe change. The engine
 *  still has the real existence answer in Fnames/file_exist.htable; if the files
 *  are not registered the loader finds nothing, which is what the whitelist was
 *  short-circuiting anyway.
 *
 *  Register safety (block RVA 0x6A4491..0x6A488A read instruction by
 *  instruction): rdi is written before it is read (`mov rdi,rax` RVA 0x6A45E0),
 *  rbx likewise (RVA 0x6A44F6), r15 is only read there and both arms of the load
 *  path already zero it. The cmp is left in place; the next instruction does not
 *  use flags.
 *
 *  Guarded on the 9-byte cmp+je window, which occurs exactly ONCE in the whole
 *  28 MB image. Static-equivalent edit: Zangetsu Patch/stage_new_id_gate.py.
 *  NOTE: found statically; not yet confirmed in a running game. */
#define STAGEGATE_RVA 0x6A4488

#include "bros_plugin.h"

/* =====================================================================
 *  V1.2 / V1.3 ROSTER  --  MOVED OUT, 2026-09-06
 * ---------------------------------------------------------------------
 *  The block that used to sit here is bros_roster.c now, and it is
 *  compiled into ReBalanceOfSouls\pl005.dll instead of into this binary.
 *
 *  Nilsix, 2026-09-06: *"separate all our dll plugins into a rebalance of
 *  souls folder that a master dll can call to ... that way we dont have
 *  any fucked criss crossing."*
 *
 *  It went WITH the gauge rather than into a plugin of its own because
 *  the two have an order: the roster is applied first, and on 2026-09-05
 *  running it later cost a battle-load access violation. Plugins have no
 *  defined order between them; code inside one plugin has whatever order
 *  it writes. One owner for the added characters and the grid that holds
 *  them is the only arrangement that keeps that guarantee.
 *
 *  The stub below exists so the CALL SITE in init is untouched by this
 *  refactor. Build with -DBROS_PL005_PLUGIN=0 to compile the real thing
 *  back into this binary; that path is kept working, not left to rot.
 * ===================================================================== */
#if defined(BROS_PL005_PLUGIN) && BROS_PL005_PLUGIN
static void patch_v12_roster(void)
{
    log_line("V12/V13: the added-character roster is not in this binary --"
             " it ships in %s\\pl005.dll. If a slot is missing from the"
             " character select grid, the plugin did not load: read the"
             " BROS/plugins lines above this one.", BROS_PLUGIN_DIR);
}
#else
#include "bros_roster.c"
#endif

static void patch_stage_new_id_gate(void)
{
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    if (!mod) return;
    unsigned char* p = mod + STAGEGATE_RVA;

    /* cmp rdi,rbx ; je 0x1406A488C */
    static const unsigned char orig[9] = {0x48,0x3B,0xFB, 0x0F,0x84,0xFB,0x03,0x00,0x00};
    /* cmp rdi,rbx ; nop word ptr [rax+rax]                                    */
    static const unsigned char repl[9] = {0x48,0x3B,0xFB, 0x66,0x0F,0x1F,0x44,0x00,0x00};

    /* Dev installs run an exe with this baked in on disk (stage_new_id_gate.py).
       Recognise that rather than reporting it as a game update. */
    if (memcmp(p, repl, sizeof(repl)) == 0) {
        log_line("STAGEGATE: already applied (exe pre-patched on disk) -- nothing to do");
        return;
    }
    if (memcmp(p, orig, sizeof(orig)) != 0) {
        log_line("STAGEGATE: bytes not at expected RVA 0x%X (game updated?) -- skipped, "
                 "new stage ids will still load empty", STAGEGATE_RVA);
        return;
    }
    DWORD old;
    if (VirtualProtect(p, sizeof(repl), PAGE_EXECUTE_READWRITE, &old)) {
        memcpy(p, repl, sizeof(repl));
        VirtualProtect(p, sizeof(repl), old, &old);
        FlushInstructionCache(GetCurrentProcess(), p, sizeof(repl));
        log_line("STAGEGATE: applied at RVA 0x%X -- ActionSceneBase::LoadBattleArea no longer "
                 "requires the 71-entry stage whitelist at 0x18EDF00", STAGEGATE_RVA);
    } else {
        log_line("STAGEGATE: VirtualProtect failed at RVA 0x%X", STAGEGATE_RVA);
    }
}

/* =====================================================================
 *  BYAKUYA BASE-FORM STANCE GAUGE  (pl022, chara id 0x16)
 * ---------------------------------------------------------------------
 *  Port of the three validated Cheat Engine scripts from
 *  bros-patch-researches/Byakuya/BROS-BYAKUYA-TIMER-STANCE-GAUGE.md.
 *
 *      base + sword stance   -> gauge hidden
 *      base + petal stance   -> gauge full, sakura pink
 *      evo   (either stance) -> untouched, native timer keeps running
 *
 *  THREE SITES, and what each one can and cannot reach:
 *
 *  1. RVA 0x21FF64, one byte 09 -> 17.  This is the class-selection table,
 *     indexed by uiId-2. Byakuya's uiId is 22, so index 20, so ONE byte.
 *     It moves him from ActionCharaUniqueUI_Pl22 (icon only) to
 *     ActionCharaUniqueUICom (gauge only). No other character's entry is
 *     touched -- a neighbouring byte is a different character's class.
 *
 *     RVA 0x21D9A8 carries the same value in a SECOND table and MUST stay
 *     at 09: that one picks the layout name, i.e. Byakuya's resource group.
 *     We verify it is still 09 and refuse to install if it is not.
 *
 *  2. RVA 0x92790, resource-handle copy constructor.  This is GENERIC and
 *     shared by the whole game, so it is the one place here that could
 *     "overflow" onto other characters -- see the note below on why it
 *     cannot, and how we prove it at runtime.
 *
 *  3. RVA 0x48C390, enhance update, rcx = Chara*.  Also shared: it runs for
 *     every fighter. The character filter lives INSIDE our hook
 *     (chara id != 0x16 -> immediate return), so every other character
 *     falls straight through to the original prologue.
 *
 *  WHY THIS DOES NOT REPEAT THE AIZEN/STARK BUG
 *  --------------------------------------------
 *  That bug (ICON_PATCH_bugfix_Aizen_Stark.md) came from patching the BODY
 *  of a method that turned out to be vtable slot 22 of 27 different
 *  ActionCharaUniqueUI_PlXX classes, so forcing its result changed 26 other
 *  characters. The rule it produced: before an in-place patch to a vtable
 *  method, count the vtables that reference it; if >1, repoint the slot.
 *
 *  Nothing here patches a vtable method body. Site 1 is a per-character
 *  table byte. Sites 2 and 3 are inline hooks on ordinary functions that
 *  re-execute the original prologue verbatim and return to it, so for any
 *  caller we do not care about, behaviour is bit-for-bit unchanged.
 *
 *  Site 2 deserves the closest look, because it fires for every resource
 *  handle copy in the game. It only ever writes when the SOURCE handle is
 *  already invalid -- null-but-nonzero, misaligned, below 0x100000, or
 *  carrying bits above bit 47 -- i.e. exactly the shapes that would fault
 *  on the very next instruction. A legitimate handle takes the early exit
 *  and nothing is written. Those broken handles only arise from Byakuya's
 *  Com-class controller looking up asset names his resource group does not
 *  contain; any other character reaching this state would already be
 *  crashing today. We do not assume that, though: the neutralise counter is
 *  logged, so if it ever fires outside this feature we will see a non-zero
 *  count in patch_ranked.log and can go looking.
 *
 *  INSTALL ORDER IS ENFORCED HERE, unlike the manual CE workflow.
 *  The CE scripts must be enabled 1 -> 2 -> 3 by hand, and enabling 1
 *  without 2 crashes on SP1. We do the reverse and install the two hooks
 *  FIRST, flipping the class byte only once both are in. If either hook
 *  fails we never flip the byte, so the game stays vanilla-safe instead of
 *  crash-prone. A guard hook left installed on its own is inert.
 * ===================================================================== */

/* ★ 2026-09-01: the class byte and the two Pl38 vtable repoints that used to
   live here are GONE. Byakuya has his own controller and his own vtable now --
   pl022_gauge.c -- so nothing writes 0x21FF64 and nothing writes into
   0x143FB78. The RVAs are kept only where something still reads them. */
#define GAUGE_RVA_LAYOUT    0x21D9A8   /* switch A: MUST remain 09      */
#define GAUGE_RVA_HANDLE    0x92790    /* handle copy ctor (hook)       */
/* The copy ASSIGNMENT for the same 0x48-byte handle type the ctor above
   copies. Observed only, never modified -- see gauge_assign_probe. */
#define GAUGE_RVA_ASSIGN    0x95410    /* handle operator= (read-only)  */
#define GAUGE_RVA_ENHANCE   0x48C390   /* enhance update  (hook)        */
#define GAUGE_RVA_BATTLEUI  0x1CDE758  /* g_battleUi[slot]              */
#define GAUGE_RVA_ELEMSTATE 0x207E00    /* Com's per-element state dispatch */
#define GAUGE_RVA_PALPUSH   0x2075A0    /* the palette push itself          */
/* 1 = the controller's update slot runs Com::slot2, which pushes the palette
   for every dirty element; that is what our own vtable slot 2 does, behind a
   null check. 0 = push it ourselves from the driver instead, element by
   element, via ELEMSTATE + PALPUSH. Kept as a switch because the two paths
   were compared once and could need comparing again -- the name still says
   "repoint" for history; nothing is repointed any more. */
#define ENABLE_GAUGE_UPDATE_REPOINT 1

#define GAUGE_VALUE_FULL    0x3F7D70A4 /* 0.99f -- saturates the bar without
                                          touching the clamp at 1.0f      */

/* Bar colour -- element+0xB0, the first of nine RGBA float4 slots.
 *
 * Which slot is drawn comes from the value: the draw push at 0x1402075A0 takes
 * k1 = clamp((int)value - 1, 0, 8) and k2 = clamp((int)value, 0, 8). Our max is
 * 1.0f so value never leaves [0,1], k1 = k2 = 0, and slot 0 is the only one that
 * can ever be seen. Raising max would unlock slots 1..8, one colour per segment
 * -- that is how Ikkaku gets his two-segment bar, and it is the hook to use if
 * the gauge rework ever wants thresholds.
 *
 * The push only runs when (int)value changed or the colour-dirty flag at +0x9A
 * is set, and it clears the flag afterwards. Only .rgb is read; alpha never is,
 * and is written here purely so the slot is not left half-initialised.
 *
 * #FFB7C5, sakura pink -- Senbonzakura. Without this the bar renders in the cyan
 * ActionCharaUniqueUIBase::Init preloads into slot 0, which is why every
 * character on the generic controller reads blue.
 *
 * Reference: DataChakka guides/EXE_WALL_PATCHING.md sections 2.3 and 2.4.
 */
/* Sakura pink, RGB(255,213,246) as authored, 2026-08-26. Each channel is
   value/255 as an IEEE-754 float: the push reads R as a raw dword and G/B as
   floats, so all three are stored the same way here.

   The two values this has held are both taken from the icon art, which is what
   makes them checkable rather than eyeballed: byak_gauge_logo.png is drawn in
   exactly two pinks, #FFBEF1 for the inner petals and #FFD5F6 for the outer
   ones. The bar was on the inner pink and read too saturated next to the
   flower; it is now on the outer one. Anything the renderer does to the colour
   -- bloom, tone mapping -- it does to the icon as well, so matching a petal
   matches on screen and not just in the source.

   Previously RGB(255,190,241) = 3F800000 / 3F3EBEBF / 3F71F1F2,
   and before that RGB(248,182,230) = 3F78F8F9 / 3F36B6B7 / 3F66E6E7. */
#define GAUGE_COL_R         0x3F800000 /* 255/255 = 1.000000 */
#define GAUGE_COL_G         0x3F55D5D6 /* 213/255 = 0.835294 */
#define GAUGE_COL_B         0x3F76F6F7 /* 246/255 = 0.964706 */
#define GAUGE_COL_A         0x3F800000 /* 1.000                */

static unsigned char* g_gauge_mod = NULL;

/* diagnostics, dumped to patch_ranked.log by log_gauge_stats() */
static volatile LONG64 g_hg_calls = 0, g_hg_kills = 0;
/* The read-only probe on handle operator=. Observations, not saves: nothing
   here changes behaviour, so a non-zero g_ha_bad is evidence rather than an
   intervention. */
static volatile LONG64 g_ha_calls = 0, g_ha_bad = 0;
/* PART 10 room-match NULL guards; declared here so the 30s heartbeat can print them */
static volatile LONG64 g_rg_draw_skips  = 0;   /* NULL mapped vertex buffer */
static volatile LONG64 g_rg_steam_skips = 0;   /* NULL Steam interface      */
static volatile LONG64 g_rg_draw2_skips = 0;   /* NULL map, second consumer */
static volatile void*  g_rg_map_fn      = 0;   /* the map fn that returned NULL */
static volatile LONG64 g_rg_map_hr      = 0;   /* what that map returned (rax)  */
/* PART 27 seat guard; declared here for the same reason -- the 30 s heartbeat
   is the only thing that reports a guard which never faults. */
static volatile LONG64 g_room3_clamped     = 0;  /* seat -1 read as seat 0 (watch)   */
static volatile LONG64 g_room3_skip_empty  = 0;  /* no fighter list at all -- bailed */
static volatile LONG64 g_room3_role_forced = 0;  /* spectator sent down the build path */
static volatile LONG64 g_sq_frames = 0, g_sq_hides = 0, g_sq_shows = 0;
/* The evo branch, which is the ONE rule in pl022_update not transcribed from an
   engine function: there the native timer owns the value through our SetRate,
   and Com::SetRate -- which made the element visible as a side effect -- no
   longer runs, so visibility follows the value. Until these existed the branch
   moved no counter at all, so a log could not say whether evo had even been
   played. Diagnostic only. */
static volatile LONG64 g_sq_evo_frames = 0, g_sq_evo_sets = 0;
/* Evo + SWORD stance: times the bar was emptied because the petals are spent.
   Reported 2026-09-06: "quand je fais un sp1 en petals, la barre se fige a la
   valeur ou le petals etait avant de swap au lieu de repasser a zero". Nothing
   wrote the element on that branch at all -- see pl022_gauge.c. */
static volatile LONG64 g_sq_evo_zero = 0;
/* Which slots currently hold Byakuya, bit per slot. The 2026-08-22 online
   crash was a MIRROR match and that case was never tested, so record it
   rather than guess at it after the fact. */
static volatile LONG   g_sq_slotmask = 0;
static volatile LONG   g_sq_mirror_seen = 0;
/* teardown guard: times a destroy through a NULL vtable was skipped */
static volatile LONG64 g_td_saves = 0;
/* the same, at the second inlined copy of that release (exe+0x33A587) */
static volatile LONG64 g_td2_saves = 0;
/* uiplay guard: what it caught, and the evidence with it.

   The four slots live in the trampoline's OWN allocation rather than in this
   DLL. gauge_alloc_near puts that within +/-2GB of the exe by construction, so
   a rip-relative store always encodes -- no "counter out of rel32 reach"
   fallback to get wrong, which is the branch the teardown guard has to carry.

       +0x00  how many times it fired
       +0x08  the bogus object (rcx = handle+0x20)
       +0x10  the handle it came from (rbx)
       +0x18  the UI state name (rdi), a const char* in .rdata            */
static volatile unsigned long long* g_up_slots = 0;
#define UP_SLOT_COUNT  0
#define UP_SLOT_PTR    1
#define UP_SLOT_HANDLE 2
#define UP_SLOT_NAME   3
/* Both are defined next to the guard itself, far below; the 30-second stats
   block sits above it and needs them here. */
static unsigned long long uiplay_saves(void);
static void uiplay_report(void);

/* lookup guard: same idea one function deeper -- see patch_lookup_guard */
static volatile unsigned long long* g_lk_slots = 0;
static unsigned long long lookup_saves(void);
static void lookup_live_report(void);
static volatile unsigned long long* g_vc_slots = 0;
static unsigned long long vcall_saves(void);
static volatile unsigned long long* g_r2_slots = 0;
static unsigned long long refrel2_saves(void);
static volatile unsigned long long* g_vfn_slots = 0;
static void vfn_report(const char* why);
static void vcall_report(void);
static void lookup_report(void);
/* times a shared_ptr release through a dead control block was skipped */
static volatile LONG64 g_rr_saves = 0;
/* The SetRate and slot2 counters used to live here, next to two guards patched
   into the engine's own bytes. Byakuya now owns his controller, so both checks
   sit in HIS vtable slots and their counters live in the thunk page -- see
   pl022_saves() in pl022_gauge.c. The 30s line still prints them. */
/* palette pushes we issued ourselves instead of via the vtable repoint */
static volatile LONG64 g_pal_pushes = 0;
/* PART 19 backstep probe; declared here so the 30s heartbeat can print it. The
   slots live inside the stub allocation, not in the DLL, because the stub is
   placed near the exe and a rip-relative store from it could not reach here. */
#define BSH_LAST         0x184      /* byte : fighter+0xFA0 last seen          */
#define BSH_MASK         0x188      /* dword: bitmask of the values seen (0-31)*/
#define BSH_FORCED       0x18C      /* dword: how many frames we forced a step */
#define BSH_BLOCKED      0x190      /* dword: frames the guard declined to force*/
/* Buffer the backstep ONLY out of blockstun, never in neutral. Reported: being
   able to hold dash and just flick back made run -> backdash far too direct;
   the stock motion is run, stick back to neutral as you release run, then
   backdash. So the forced step is now gated on the fighter still being in a
   guard/blockstun state -- the SAME range PART 24 measured: commands 5..8 (one
   shared blank name-table entry) plus 12 (guard_in). In neutral the gesture
   falls through to stock behaviour and gives the run, as before the patch. */
#define BSH_ONLY_IN_STUN 1
#define BSH_STUN_LO      5
#define BSH_STUN_HI      8
#define BSH_STUN_GUARD   12   /* 12..14: guard_in, just_guard, dam_short.
                                 14 is HITSTUN, measured -- the state histogram
                                 came back 0x40F9 with bit 14 set and last=14
                                 after taking hits. Before this it was only ever
                                 covered by leftover credit from a previous guard,
                                 which worked by accident and not reliably.  */
#define BSH_STUN2_LO     12
#define BSH_STUN2_HI     14
/* ...but the state has already left that range by the frame the player becomes
   actionable, so testing it alone removed the mechanic outright: `fighter+0xFA0`
   is NOT sticky across that transition, contrary to what PART 19 first assumed.
   A grace window fixes it, and the reporter proposed exactly this: seeing a stun
   state arms N frames of credit, and the force is still allowed while credit
   remains. Long enough to cover the first actionable frame, far too short to
   survive into neutral -- so run -> backdash still needs its real motion.
   Counted in frames where the GESTURE is held, which is the thing that matters. */
#define BSH_GRACE        0x194      /* byte: frames of credit left            */
#define BSH_GRACE_N      5          /* armed on seeing a stun state           */
static volatile unsigned char* g_bsh_cave = 0;
/* PART 21 input probe; the snapshot lives in the stub, see PART 19 for why. */
#define IPR_SNAP   0x200
/* One counter per command id we care about, so a repro says WHICH command the
   press actually pushed. Order: 0x16 0x20 0x21 0x25 0x26 0x27 0x28. */
#define IPR_LASTCMD  0x2C4   /* fighter+0xFA0   at the LAST flash-step emit */
#define IPR_LAST9A8  0x2C5   /* fighter+0x9A8   at the same instant        */
#define IPR_LAST1310 0x2C6   /* fighter+0x1310  at the same instant        */
#define IPR_CAVE_SZ  0x80   /* per-site stub slot. The flash-step stub grew to
                              ~87 bytes across several probe iterations and
                              silently overran a 0x40 slot, corrupting the next
                              site's code -- that crashed the game. Bounds are
                              now checked per site, below. */
#define IPR_DOWN      0x2CC   /* the buttons-down mask, sampled EVERY frame, so a
                                 single held button names its own bit         */
#define IPR_R12       0x2C8   /* r12d at the 0x26 emission -- why does it match? */
#define IPR_FMASK    0x2C0   /* bitmask of fighter+0xFA0 seen when 0x16 is emitted */
#define IPR_CMD_BASE 0x240
#define IPR_NCMD     7
#define IPR_N28      5   /* 0x28 counted per site, slots 6..10  */
#define IPR_N26      3   /* 0x26 counted per site, slots 11..13 */
#define IPR_SITE2  0x238   /* cmd 0x16 emitted from 0x4127F9              */
#define IPR_SITE3  0x23C   /* cmd 0x16 emitted from 0x412D00              */
#define IPR_TICKS  0x230   /* frames the hook has run -- tells a LIVE
                              reading from a snapshot frozen because the
                              match ended and vfunc2 stopped running */
#define IPR_NSLOT  11
static volatile unsigned char* g_ipr_cave = 0;
/* PART 20 gate counters: which path let the flash step out, if any. Cheap enough
   to ship -- a stray-input report is then answerable from a log instead of a
   rebuild, which this session paid for twice over. */
#define FSH_C_EDGE  0x100
#define FSH_C_HELD  0x104
#define FSH_C_TAP   0x108
#define FSH_C_SKIP  0x10C
#define FSH_GRACE   0x110   /* byte: blockstun credit, as PART 19 */
#define FSH_GRACE_N 5
#define FSH_SYUNPO  22      /* already flash-stepping             */
#define FSH_GUARD_LO 5
#define FSH_GUARD_HI 8
#define FSH_GUARD_IN 12
static volatile unsigned char* g_fsh_cave = 0;

/* ---- site 2 payload: neutralise an already-invalid source handle ------
   Mirrors h_kill/h_ok in script 2. rdx (the source) arrives as arg 1.    */
/* Is this pointer inside the loaded exe image? A shared_ptr control block is
   heap-allocated and never is; the handle guard uses that to reject a bogus
   one whose value merely looks like a valid address. */
static int gauge_in_exe(const void* p)
{
    uintptr_t v = (uintptr_t)p, base = (uintptr_t)g_gauge_mod;
    return g_gauge_mod && v >= base && v < base + 0x2000000;
}

/* ---- read-only probe on handle operator= (exe+0x95410) ---------------
   The crash at exe+0x9546C, three times now and twice confirmed on entry to
   character select, is this:

       9545A  mov  rcx,[rbx+0x40]        ; rbx = the DESTINATION (mov rbx,rcx)
       95462  test rcx,rcx
       95465  je   9547C                 ; the engine's own empty-handle path
       95467  mov  eax,-1
       9546C  lock xadd [rcx+0Ch],eax    ; <-- faults

   An interlocked refcount decrement on the destination's control block. The
   game null-checks that pointer and nothing else, so a NON-canonical value
   sails through: 0x0400040004200400 on 2026-09-07, which is packed 16-bit
   data (1024, 1056, 1024, 1024) sitting where a pointer belongs.

   WHY THIS OBSERVES AND DOES NOT ACT. The sibling hook on the copy
   constructor (gauge_handle_guard, exe+0x92790) validates the SOURCE and
   nulls it when bad. Nothing has ever inspected the DESTINATION, which is
   the field that actually faults here. But neutralising it would be wrong:
   0x95410 has 1051 callers, and zeroing a live destination converts a loud
   crash into a leaked control block and a silently wrong refcount on a screen
   that is about to be rebuilt -- while destroying the only signal this bug
   produces. So this logs and returns. Nothing is written.

   Rate: the function runs tens of millions of times a session (the ctor logged
   29 million copies in one run), and bad ones are single digits, so logging
   every hit costs nothing. Ten per session is the cap regardless, because a
   probe that can flood the log is a probe that can hide the thing it found.

   arg_from_rdx is 0 for this hook, unlike the ctor's 1: the destination is
   rcx on entry, and reading rdx here would observe the wrong object. */
static void gauge_assign_probe(unsigned char* dst)
{
    unsigned long long v40, v38;
    const char* why = 0;

    g_ha_calls++;
    if (!dst) return;
    v40 = *(unsigned long long*)(dst + 0x40);
    if (v40 == 0) return;                  /* empty handle: the je path      */

    /* The same rules the ctor guard keeps, and for the same reasons -- facts
       about pointers, not heuristics, except the last which says so. */
    if (v40 >> 47)                 why = "cb non-canonical";
    else if (v40 & 7)              why = "cb misaligned";
    else if (v40 < 0x10000ULL)     why = "cb inside the first page";
    else if (gauge_in_exe((void*)(uintptr_t)v40))
                                   why = "cb points into the exe image";
    /* No "far below any heap" rule here either -- it assumed a Windows heap at
       1.8e12 and rejected every live handle under Proton, where the heap is
       three orders of magnitude lower. Removed from the ctor guard the same
       day; see the note there. Read-only or not, a rule that is wrong on one
       platform would fill this log with false positives on exactly the machine
       the probe was added to observe. */
    if (!why) return;

    g_ha_bad++;
    if (g_ha_bad <= 10) {
        v38 = *(unsigned long long*)(dst + 0x38);
        /* Deliberately NOT reporting a caller. The obvious way is
           _ReturnAddress(), and it would be wrong: by the time this runs the
           trampoline has already pushed a frame, so it returns into our own
           shim rather than into the game. Recovering the real caller means
           knowing the shim's exact stack layout, which is a second thing to
           get wrong. The value and the object identity are what this probe is
           for; the caller comes from the crash dump, which has a real stack. */
        log_line("HANDLE/assign: destination %p would fault -- %s "
                 "(cb=%016llX payload=%016llX). "
                 "NOT modified; this is an observation.",
                 dst, why, v40, v38);
    }
}

static void gauge_handle_guard(unsigned char* src)
{
    unsigned long long v40, v38 = 0;
    int bad = 0;
    const char* why = "";
    g_hg_calls++;
    if (!src) return;
    v40 = *(unsigned long long*)(src + 0x40);
    if (v40 == 0) return;                    /* nothing to validate       */
    /* ★ 2026-09-01: the two PAYLOAD rules are gone, and the evidence is in
       exe+0x92790 itself:

           927D6  mov  rax,[rdx+0x38]      ; the payload is READ
           927DA  mov  [rcx+0x38],rax      ; ...and COPIED. Never dereferenced.
           927DE  mov  rax,[rdx+0x40]
           927E2  mov  [rcx+0x40],rax
           927E6  lock inc dword [rax+0xc] ; ONLY +0x40 is dereferenced

       Whatever `+0x38` holds, its VALUE cannot fault this function -- it is
       moved bit for bit. Only `+0x40` can. So testing `+0x38` could never
       prevent a crash here, and firing on it is pure cost.

       And it fired constantly. Across 22 neutralisations on record, 18 were
       `payload non-canonical` and only 4 were a `cb` rule. The payload values
       are not garbage either: over 22 samples their top byte is ONLY ever
       0x00, 0x80 or 0x88, and the same values recur on the same two source
       objects all session -- `80018000F120B253` four times, `8001C400F1B8B2AB`
       three. Heap garbage is uniformly distributed; that is a tagged value
       with a flag in the high bits, and it was never a pointer to begin with.

       The cost is what this function's own comment predicted for the "payload
       NULL" rule, one paragraph down: zeroing `+0x40` on a LIVE handle strands
       the object -- the copy comes back empty while the caller believes it took
       a reference. Two of the 22 are followed 1 ms later by a crash
       (exe+0x207510 on 2026-09-01 02:44, exe+0x8A8F43 the same evening), and
       both fired on `payload non-canonical`. With only 22 neutralisations in
       the whole log, landing inside a 1 ms window twice is not coincidence.

       Dropping them cannot reopen the SP1 fault: all 18 had a `+0x40` that
       passed every cb test, so `lock inc [cb+0xc]` would have been fine on
       each. The three rules left are exactly the preconditions of the
       instruction that actually faults. */
    if (v40 >> 47)            { bad = 1; why = "cb non-canonical"; }
    else if (v40 & 7)         { bad = 1; why = "cb misaligned"; }
    else if (v40 < 0x100000)  { bad = 1; why = "cb below first page"; }
    /* ★ 2026-09-02, and it corrects the change made this morning. A control
       block is heap-allocated -- it is never inside the exe image. The three
       tests above all PASS for an image address: it is canonical, aligned, and
       far above the first page.

       Removing the payload rules in 3a93b9a re-opened the SP1 crash within the
       day: exe+0x927E6, `lock inc [rax+0xc]`, writing to 0x7FF72671E07C, with
       `guard neutralised 0 of 11295167`. The reasoning there was right about
       the mechanism -- +0x38 is copied, never dereferenced, so its value cannot
       fault 0x92790 -- and wrong about the consequence. A garbage payload was a
       CORRELATED signal that the whole handle was bogus, and it was the only
       signal catching a control block that points into the image. The record
       says so plainly: of the control blocks that rule stopped, eight were
       image addresses -- 00007FF7A3F4E070 five times, 00007FF70BE3E070 twice,
       00007FF70BED00C8 once -- and no cb rule fired on any of them.

       So the right rule is not the payload's, it is this one: test the field
       that faults, against the property that actually distinguishes a real
       control block from a bogus one. */
    else if (gauge_in_exe((const void*)(uintptr_t)v40))
                              { bad = 1; why = "cb inside the exe image"; }
    /* ★ 2026-09-04. The fifth rule, and it is the one that would have saved the
       host client tonight: it died AT 0x927E6, `lock inc [rax+0xc]`, WRITING to
       0x40000000C -- so rax was 0x400000000, and that value passes every rule
       above. Canonical, aligned, far past the first page, nowhere near the exe.
       It is simply not a heap address: user-mode allocations on Win64 land
       around 0x000001xx_xxxxxxxx, three orders of magnitude higher.
    
       It is the same shape the whole night kept producing -- 8006C78000000002,
       C004718000000002, 8801D500E3DFF366 -- a small number in one half and a
       flag in the other, a packed pair being read as a pointer.
    
       This is a heuristic on an address range, unlike the four above which are
       facts about pointers, and it is written down as one. The floor is
       deliberately far below any real allocation: 0x10000000000 is 1.1e12
       against a typical heap at 1.8e12, so a legitimate control block cannot
       fall under it while 0x400000000 (1.7e10) cannot climb over it.

       ★ 2026-09-07: REMOVED. "a typical heap at 1.8e12" is a fact about
       Windows, and this loader also runs under Proton, where it is false.

       A Steam Deck log: EVERY control block sits at 0x8CA484B0 (2.4e9) or
       0x025BBA20 (4.0e7). Wine's heap lives low, so this rule rejected 35 of
       35 handles -- 100% of that machine's neutralisations, with no other
       rule ever firing. Every one of them was a LIVE handle, and nulling +0x40
       is what the comment below it always warned it would be: a skipped
       release and an unbalanced refcount.

       Then the game died, five times, always at exe+0x8CEB6B reading 0x258 --
       a member read through a base this guard had zeroed. Each crash was
       preceded by exactly 7 neutralisations within 5 seconds, and 0 of the 35
       were NOT followed by a crash. The denominator is the part that matters:
       there were no innocent firings to weigh against it.

       On Windows it never fired at all -- "neutralised 0 of 29,042,625" -- so
       removing it costs nothing there. A heuristic that is wrong on one
       platform and inert on the other is not worth keeping. Rules 1-4 stay:
       they are facts about pointers and hold under any allocator. */
    v38 = *(unsigned long long*)(src + 0x38);   /* logged only, never judged */
    if (bad) {
        g_hg_kills++;
        /* Which rule fired, and on what. This writes to a LIVE handle somebody
           else owns, so it matters a great deal whether the thing being
           neutralised was really garbage.

           This comment used to say "payload NULL is the rule to distrust",
           and to note that correlation alone could not settle it because the
           guard fires in most Byakuya sessions. Logging WHICH rule fired is
           what settled it, on 2026-09-01: both payload rules were wrong, for a
           reason stronger than correlation -- the faulting function never
           dereferences +0x38 at all. They are removed; see the block above.

           What is left tests only +0x40, which is what `lock inc [rax+0xc]`
           reads. Rare -- single digits per session against hundreds of millions
           of copies -- so logging every one costs nothing, and the payload is
           still printed because its top byte is the evidence that it is a
           tagged value rather than a pointer. */
        log_line("BYAKUYA_GAUGE/guard: neutralising handle %p -- %s "
                 "(cb=%016llX payload=%016llX)", src, why, v40, v38);
        /* Clear the CONTROL BLOCK ONLY, never the payload at +0x38.
           exe+0x92790 is a shared_ptr copy constructor and its own empty test
           reads +0x40 and nothing else:

               927C8  mov  [rcx+0x38],0      ; dest starts empty
               927CC  mov  [rcx+0x40],0
               927CE  cmp  qword [rdx+0x40],rax   ; rax==0: source control block null?
               927D4  je   927EA                  ; yes -> copy nothing, return
               927D6  mov  rax,[rdx+0x38]         ; no  -> copy payload
               927DE  mov  rax,[rdx+0x40]         ;        copy control block
               927E6  lock inc dword [rax+0xc]    ; <-- SP1 faulted here on a
                                                  ;     garbage control block

           So zeroing +0x40 makes the engine take its own `je` path: no copy, no
           refcount increment, a well-formed empty handle. Zeroing +0x38 as well
           went outside that contract -- it wiped a live object's payload pointer,
           and the teardown destructor (exe+0x8B0530, `lock xadd [rbx+8]` then
           `call [rax]` at 0x8B06D0) then faulted on the fallout. Guard on and
           both fields cleared crashed at teardown; guard off crashed at SP1;
           guard on with +0x40 alone crashes at neither. */
        *(unsigned long long*)(src + 0x40) = 0;
    }
}

/* ---- site 3 payload: the stance driver -------------------------------
   Mirrors sqcode in script 3. rcx (Chara*) arrives as arg 1.             */
/* Paint every element's five RGBA presets sakura pink, then re-arm the two
   dirty flags.

   The element does not carry ONE colour, it carries FIVE presets -- Com's
   element init at 0x140207050 copies them in from xmm8..xmm12:

       +0xB0 cyan    (0.133, 0.733, 0.773)
       +0xC0 blue    (0.133, 0.384, 0.773)   <- what Grimmjow's gauge shows
       +0xD0 gold    (0.871, 0.839, 0.298)
       +0xE0 orange  (0.902, 0.427, 0.212)
       +0xF0 magenta (0.686, 0.000, 0.561)

   Which preset is drawn is picked from stack locals inside the push, not by
   us, so paint all five rather than guess. +0x94 is the dword Com::slot2
   tests before calling the push; +0x9A is the per-sub-block flag the push at
   0x1402075A0 consumes. Both are set AFTER the colour, never before. */
typedef void (*gauge_elemfn)(void* self, float rate, int index);

static void gauge_paint(unsigned char* ctrl, unsigned char* elem,
                        unsigned char* end)
{
    unsigned int off;
    int index = 0;
    gauge_elemfn state = (gauge_elemfn)(g_gauge_mod + GAUGE_RVA_ELEMSTATE);
    gauge_elemfn push  = (gauge_elemfn)(g_gauge_mod + GAUGE_RVA_PALPUSH);
    for (; elem + 0x240 <= end; elem += 0x240, index++) {
        for (off = 0xB0; off <= 0xF0; off += 0x10) {
            *(unsigned int*)(elem + off +  0) = GAUGE_COL_R;
            *(unsigned int*)(elem + off +  4) = GAUGE_COL_G;
            *(unsigned int*)(elem + off +  8) = GAUGE_COL_B;
            *(unsigned int*)(elem + off + 12) = GAUGE_COL_A;
        }
        *(unsigned int*)(elem + 0x94) = 1;
        *(unsigned char*)(elem + 0x9A) = 1;
        /* What Com::slot2 does for a dirty element, minus its sub-object loop
           -- Pl38::slot2 still runs and still handles those, and this+0x18.
           The float is the rate slot2 was called with; the push does not read
           it on this path, so 0 is fine. */
        if (!ENABLE_GAUGE_UPDATE_REPOINT && ctrl) {
            state(ctrl, 0.0f, index);
            push (ctrl, 0.0f, index);
            g_pal_pushes++;
        }
    }
}

/* ---- read-only probe: where does Pl38 keep the icon? -----------------
   The unique icon never changes with the stance, and cannot, because the
   update slot points at Com::slot2 -- which does the palette and nothing else.
   Pl38::slot2 is the function that owns the icon (this+0xc, +0x10, +0x18) and
   it no longer runs; ComIcon::slot2 ran both and is the one that corrupted the
   heap. So the two-texture "off/on" pair in the art can never be switched by
   the engine here: whatever Pl38::Init's one "Normal" is showing is what stays
   on screen for the whole match.

   Driving it from this hook instead needs the icon's sprite object. Two facts
   point at where it is: Pl38 allocates a 0x48-byte block at this+0x18, and
   0x48 is exactly the stride of a gauge element's slot -- whose object pointer
   sits at slot+0x20. That makes *(ctrl+0x38) the candidate, and the sprite's
   material parameters would then be at [obj+0x19B0], the same array the bar's
   palette push writes through.

   Candidate, not conclusion. This logs what is actually there, once per
   session, next to a known-good sprite object (the bar's, at *(elem+0x20)) so
   the two can be compared, and WRITES NOTHING. Reads are both range-checked
   and wrapped in SEH, so a wrong guess costs a log line, not the process. */
static int gauge_ptr_ok(const void* p)
{
    uintptr_t v = (uintptr_t)p;
    return v >= 0x100000 && (v & 7) == 0 && (v >> 47) == 0;
}

/* gauge_is_sprite(), gauge_heap_block() and the material-array bookkeeping
   (g_icon_sprite / g_icon_pcount, GAUGE_ICON_LIT / _DIM / _MAXP) lived here.
   All of it existed to write the icon's colour into [sprite+0x19B0] safely,
   and none of it is needed now that the engine's own setter takes the node.
   g_icon_writes stays: it still counts tint calls, in the 30 s line. */
static volatile LONG64 g_icon_writes = 0;
/* Times pl022_tint_icon() found its cached node already dead and dropped it
   instead of writing through it. An intervention, not an observation: every
   count here is 3 dwords per entry that used to land in whatever now owns
   that block. See the 2026-09-09 note in pl022_tint_icon(). */
static volatile LONG64 g_icon_dead = 0;

/* gauge_icon_tint() lived here. It wrote the icon's colour as raw 32-bit
   dwords into [sprite+0x19B0] + 32*i, through a pointer cached once per
   session -- the write-after-free that corrupted a neighbouring pointer's low
   half and produced `exe+0x227980 reading from 0x2D000000EF6`.

   Byakuya now does what pl005 has always done: hand the NODE to the engine's
   own setter, exe+0x224700(node, idx, R, G, B), and let it resolve the
   material array itself. Nothing of ours is cached across a frame, so nothing
   of ours can go stale. See pl022_tint_icon() in pl022_gauge.c. */

/* gauge_stance_driver() lived here: the payload of an inline hook on the
   enhance update at 0x48C390. It found the controller through
   g_battleUi[slot] -> +0x200 and wrote the element from outside the object.
   Its body is now pl022_update() in pl022_gauge.c, our own vtable slot 2 --
   same logic, same fields, same hands_off rule, but the engine calls it, with
   the object in rcx, at the moment the engine updates that object. Nothing
   reaches in through a global table any more. */

/* ---- trampoline allocation within rel32 reach of the hook site -------
   An E9 jmp only reaches +/-2GB, which is why the CE scripts say
   alloc(...,exe+RVA): the allocation has to land near the exe. VirtualAlloc
   with an address hint does the same job.                                */
static void* gauge_alloc_near(unsigned char* anchor, size_t n)
{
    SYSTEM_INFO si;
    uintptr_t gran, a, d, base;
    void* p;
    int i;
    GetSystemInfo(&si);
    gran = si.dwAllocationGranularity ? si.dwAllocationGranularity : 0x10000;
    a = (uintptr_t)anchor;
    for (d = gran; d < 0x60000000ULL; d += gran) {
        uintptr_t cands[2];
        cands[0] = a - d;
        cands[1] = a + d;
        for (i = 0; i < 2; i++) {
            base = cands[i] & ~(gran - 1);
            if (base < 0x10000) continue;
            p = VirtualAlloc((void*)base, n, MEM_COMMIT | MEM_RESERVE,
                             PAGE_EXECUTE_READWRITE);
            if (p) return p;
        }
    }
    return NULL;
}

/* ---- inline hook on a FUNCTION ENTRY ---------------------------------
   Both sites were confirmed to be function entries (each is preceded by CC
   padding), which is what makes this shape safe: at an entry only the ABI
   argument registers are live, so saving rcx/rdx/r8/r9 -- plus r10/r11/rax
   and xmm0-3, belt and braces -- is enough. The stolen prologue is then
   re-executed verbatim, so a caller we filter out runs the original code
   with the original register state and never knows we were here.         */
static int gauge_install_hook(unsigned int rva, int stolen, void* payload,
                              int arg_from_rdx, const char* tag)
{
    unsigned char* site = g_gauge_mod + rva;
    unsigned char* stub;
    unsigned char  b[160];
    int   n = 0, i;
    long long rel;
    DWORD old;

    stub = (unsigned char*)gauge_alloc_near(site, 256);
    if (!stub) { log_line("%s: no trampoline within +/-2GB -- skipped", tag); return 0; }

    b[n++]=0x55;                                            /* push rbp          */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xE5;                  /* mov  rbp,rsp      */
    b[n++]=0x51;                                            /* push rcx          */
    b[n++]=0x52;                                            /* push rdx          */
    b[n++]=0x41; b[n++]=0x50;                               /* push r8           */
    b[n++]=0x41; b[n++]=0x51;                               /* push r9           */
    b[n++]=0x41; b[n++]=0x52;                               /* push r10          */
    b[n++]=0x41; b[n++]=0x53;                               /* push r11          */
    b[n++]=0x50;                                            /* push rax          */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xE4; b[n++]=0xF0;     /* and  rsp,-16      */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xEC; b[n++]=0x60;     /* sub  rsp,0x60     */
    b[n++]=0x0F; b[n++]=0x11; b[n++]=0x44; b[n++]=0x24; b[n++]=0x20; /* movups [rsp+20],xmm0 */
    b[n++]=0x0F; b[n++]=0x11; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30; /* movups [rsp+30],xmm1 */
    b[n++]=0x0F; b[n++]=0x11; b[n++]=0x54; b[n++]=0x24; b[n++]=0x40; /* movups [rsp+40],xmm2 */
    b[n++]=0x0F; b[n++]=0x11; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x50; /* movups [rsp+50],xmm3 */
    if (arg_from_rdx) { b[n++]=0x48; b[n++]=0x89; b[n++]=0xD1; }     /* mov rcx,rdx */
    b[n++]=0x48; b[n++]=0xB8;                               /* mov  rax,imm64    */
    memcpy(b + n, &payload, 8); n += 8;
    b[n++]=0xFF; b[n++]=0xD0;                               /* call rax          */
    b[n++]=0x0F; b[n++]=0x10; b[n++]=0x44; b[n++]=0x24; b[n++]=0x20; /* movups xmm0,[rsp+20] */
    b[n++]=0x0F; b[n++]=0x10; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30; /* movups xmm1,[rsp+30] */
    b[n++]=0x0F; b[n++]=0x10; b[n++]=0x54; b[n++]=0x24; b[n++]=0x40; /* movups xmm2,[rsp+40] */
    b[n++]=0x0F; b[n++]=0x10; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x50; /* movups xmm3,[rsp+50] */
    b[n++]=0x48; b[n++]=0x8D; b[n++]=0x65; b[n++]=0xC8;     /* lea rsp,[rbp-0x38]*/
    b[n++]=0x58;                                            /* pop  rax          */
    b[n++]=0x41; b[n++]=0x5B;                               /* pop  r11          */
    b[n++]=0x41; b[n++]=0x5A;                               /* pop  r10          */
    b[n++]=0x41; b[n++]=0x59;                               /* pop  r9           */
    b[n++]=0x41; b[n++]=0x58;                               /* pop  r8           */
    b[n++]=0x5A;                                            /* pop  rdx          */
    b[n++]=0x59;                                            /* pop  rcx          */
    b[n++]=0x5D;                                            /* pop  rbp -> rsp back
                                                               to function entry */
    memcpy(b + n, site, (size_t)stolen); n += stolen;       /* stolen prologue   */
    rel = (long long)(site + stolen) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b + n, &rel, 4); n += 4;            /* jmp back          */

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);

    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("%s: trampoline out of rel32 range -- skipped", tag);
        return 0;
    }
    if (!VirtualProtect(site, (size_t)stolen, PAGE_EXECUTE_READWRITE, &old)) {
        log_line("%s: VirtualProtect failed at RVA 0x%X", tag, rva);
        return 0;
    }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    for (i = 5; i < stolen; i++) site[i] = 0x90;    /* pad the remainder so we
                                                      never leave half an
                                                      instruction behind      */
    VirtualProtect(site, (size_t)stolen, old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, (size_t)stolen);
    log_line("%s: hooked RVA 0x%X, %d bytes stolen", tag, rva, stolen);
    return 1;
}

/* ---- vtable slot repoint -------------------------------------------
   Two slots of ActionCharaUniqueUI_Pl38 have to move for Byakuya.

   slot 0x50  SetRate -> Com::SetRate.  Pl38::SetRate is a bare thunk: it
   writes the value and nothing else, so nothing ever makes the bar visible
   again and the evo timer disappears.

   slot 0x10  update  -> Com::slot2.  This is the one that matters for the
   colour.

   It pointed at ComIcon::slot2 (0x208EC0) until 2026-08-21 and that CRASHED:
   leaving a mode with Byakuya gave a heap corruption (0xC0000374 in ntdll,
   detected at teardown, once per session without fail). ComIcon and Pl38 are
   both 0x20-byte objects, but they disagree about this+0x18 -- Pl38 allocates a
   0x48-byte block there and ComIcon never does. Measured on the field offsets
   each update actually touches:

       Com::slot2      this+0x10 only          <- compatible with Pl38
       ComIcon::slot2  this+0xc
       Pl38::slot2     this+0xc, +0x10, +0x18

   Com::slot2 is the one that carries the palette push in the first place;
   ComIcon::slot2 was only ever a wrapper that called it. Pointing straight at
   it keeps the colour and drops the layout conflict. The cost is Pl38's icon
   ANIMATION work, which nothing re-triggers in a match anyway -- Init plays
   "Normal" once and that is that. The palette at element+0xB0 is only ever pushed to the sprite
   material by 0x1402075A0, whose SINGLE caller is 0x140207548, inside
   Com::slot2 (0x140207490). Pl38::slot2 (0x140215510) replaces that update
   wholesale and -- verified across the whole function, 0x140215510..0x140215B97
   -- calls neither. So under Pl38 the palette is data nobody reads, and the
   bar keeps Grimmjow's blue however much we paint it. ComIcon::slot2
   (0x140208EC0, from the 0x14143FDC8 "gauge + icon" class) calls BOTH
   Com::slot2 and the icon animation helpers, which is exactly the pair we
   need. Pl38::Init is left alone, so the ui_pl038_unique_icon_L00 binding --
   and with it Byakuya's transplanted icon art -- still loads.

   Both slots live in the Pl38 vtable, which is Grimmjow's as well. */
/* gauge_repoint() lived here: it wrote one qword into an ENGINE vtable, with
   verify-before-write and a log line. It was correct and it is deleted anyway,
   because the only caller is gone and a helper that edits a shared class vtable
   should not sit around waiting to be reached for again. The replacement is a
   private vtable -- an array in this DLL -- in pl022_gauge.c. */

/* ★★★★★ SHARED INFRASTRUCTURE, THEN THE HOST, THEN CHARACTERS.

   That order is the standard in one line, and it is enforced by what each
   piece needs rather than by anybody remembering it.

   bros_uifactory.c is the single detour on the controller factory with a
   claim table behind it. It used to live in pl022_gauge.c, which meant
   Zangetsu's code could not compile without Byakuya's file -- the exact
   criss-crossing this change removes, hiding inside the one piece of code
   whose whole job is to stop two characters colliding.

   Nilsix, 2026-09-06: *"separate all our dll plugins into a rebalance of
   souls folder that a master dll can call to ... that way we dont have any
   fucked criss crossing."* */
#include "bros_uifactory.c"
#include "bros_plugin_host.c"

/* Byakuya's own controller: the shared factory hook, his private vtable and
   the two guarded slots. Included here because it needs g_gauge_mod,
   gauge_alloc_near and log_line, and because patch_byakuya_gauge below calls
   into it. Always compiled -- the gauge ships in the Community Patch. */
#include "pl022_gauge.c"



/* ============ PART 11: WHY THE D3D12 DEVICE IS REMOVED (DRED) ========
 *  The room-match "opponent changed character" crash is NOT a logic bug and
 *  NOT ours: the 10:41 dump caught the buffer map returning 0x887A0005,
 *  DXGI_ERROR_DEVICE_REMOVED, and the same repro happens on VANILLA. Every
 *  NULL the ROOMGUARD patches swallow is fallout from that one event.
 *
 *  A removed device cannot be un-removed from here. What can be done is make
 *  the game say WHY, because D3D12 will tell you if you ask before it happens:
 *
 *    - DRED (Device Removed Extended Data) has to be switched on BEFORE the
 *      device is created. The game never calls D3D12GetDebugInterface, so it
 *      never does. We do it inside our own hook on D3D12CreateDevice, which is
 *      the only place ordering is guaranteed.
 *    - The exe imports D3D12CreateDevice BY ORDINAL (101) -- it is not in the
 *      import names -- so the IAT slot is found by ordinal, at RVA 0x11B5BE0.
 *    - Once removed, GetDeviceRemovedReason() distinguishes the cases that
 *      matter: HUNG (0x887A0006) is a GPU hang, DRIVER_INTERNAL_ERROR
 *      (0x887A0020) is a driver bug, INVALID_CALL (0x887A0001) is the app
 *      doing something illegal, REMOVED (0x887A0005) is the generic one.
 *    - DRED's page-fault output then names the GPU virtual address that
 *      faulted and, crucially, whether that address belongs to a RECENTLY
 *      FREED allocation. That is the signature of a use-after-free of a GPU
 *      resource -- which is exactly what "the opponent's old model is
 *      destroyed while the GPU is still drawing it" would look like, and it
 *      fits the one workaround that avoids the crash (being on Battle
 *      Settings, where that model is not being drawn).
 *
 *  All of it lands in patch_ranked.log. Nothing here changes rendering; if any
 *  step is unavailable (older Windows, no DRED, slot not where we expect) it
 *  logs that and stays out of the way.
 *
 *  Vtable indices are the public D3D12 ABI:
 *    ID3D12Device::GetDeviceRemovedReason           = 37
 *    IDREDSettings::SetAutoBreadcrumbsEnablement    = 3, SetPageFaultEnablement = 4
 *    IDRED::GetAutoBreadcrumbsOutput                = 3, GetPageFaultAllocationOutput = 4
 * --------------------------------------------------------------------- */
#define DRED_IAT_RVA 0x11B5BE0      /* IAT slot for d3d12.dll ordinal 101 */

typedef HRESULT (WINAPI *D3D12CreateDevice_t)(void*, int, const GUID*, void**);
typedef HRESULT (WINAPI *D3D12GetDebugInterface_t)(const GUID*, void**);

static void*  g_d3d12_device = NULL;
static D3D12CreateDevice_t o_D3D12CreateDevice = NULL;
static volatile LONG g_dred_reported = 0;

/* {82BC481C-6B9B-4030-AEDB-7EE3D1DF1E63} ID3D12DeviceRemovedExtendedDataSettings */
static const GUID IID_DREDSettings =
    {0x82bc481c,0x6b9b,0x4030,{0xae,0xdb,0x7e,0xe3,0xd1,0xdf,0x1e,0x63}};
/* {98931D33-5AE8-4791-AA3C-1A73A2934E71} ID3D12DeviceRemovedExtendedData */
static const GUID IID_DRED =
    {0x98931d33,0x5ae8,0x4791,{0xaa,0x3c,0x1a,0x73,0xa2,0x93,0x4e,0x71}};

typedef struct DredAllocNode {
    const char*  nameA;
    const wchar_t* nameW;
    unsigned int type;
    const struct DredAllocNode* next;
} DredAllocNode;

typedef struct {
    unsigned long long pageFaultVA;
    const DredAllocNode* existing;
    const DredAllocNode* recentlyFreed;
} DredPageFault;

typedef struct DredBreadcrumbNode {
    const char*    cmdListNameA;
    const wchar_t* cmdListNameW;
    const char*    cmdQueueNameA;
    const wchar_t* cmdQueueNameW;
    void*          cmdList;
    void*          cmdQueue;
    unsigned int   count;
    const unsigned int* lastValue;
    const unsigned int* history;
    const struct DredBreadcrumbNode* next;
} DredBreadcrumbNode;

typedef struct { const DredBreadcrumbNode* head; } DredBreadcrumbs;

static void dred_enable_before_device(void)
{
    HMODULE d3d12 = GetModuleHandleA("d3d12.dll");
    D3D12GetDebugInterface_t get;
    void* s = NULL;
    void*** itf;
    if (!d3d12) { log_line("DRED: d3d12.dll not loaded yet -- breadcrumbs off"); return; }
    get = (D3D12GetDebugInterface_t)GetProcAddress(d3d12, "D3D12GetDebugInterface");
    if (!get) { log_line("DRED: D3D12GetDebugInterface missing -- breadcrumbs off"); return; }
    if (get(&IID_DREDSettings, &s) < 0 || !s) {
        log_line("DRED: this Windows has no DRED settings interface -- breadcrumbs off");
        return;
    }
    itf = (void***)s;
    ((void (WINAPI*)(void*, int))(*itf)[3])(s, 2);   /* SetAutoBreadcrumbsEnablement FORCED_ON */
    /* ★★★ 2026-09-17 -- PAGE-FAULT ENABLEMENT IS NO LONGER FORCED ON, AND IT IS
       THE HALF WITH UNBOUNDED STATE BEHIND IT. Breadcrumbs (slot 3) write into
       fixed-size per-command-list rings: a per-op cost, but a CONSTANT one.
       Page faults (slot 4) are different in kind -- the runtime cannot produce
       DredPageFault's `existing` and `recentlyFreed` allocation-name lists (the
       struct is declared 40 lines above this) without RETAINING a record of
       every GPU allocation, live and freed, for the whole session. That is the
       only session-long growth this translation unit asks for, and it asks for
       it in a SHIPPED patch, on every run, for a report that has never once
       fired: there is no "*** DEVICE REMOVED ***" line anywhere in six launches
       of patch_ranked.log.
       ⓘ What is kept: GetDeviceRemovedReason and its INVALID_CALL decode -- the
         part that actually produced a diagnosis (it is what ruled out the whole
         TDR / VRAM / use-after-free family). What is lost: the page-fault VA and
         the freed-allocation names, which is the use-after-free hunt. Put the
         line back the day a device removal needs that, and not before.
       ⇒ ★★★ RULE: A DIAGNOSTIC THAT RETAINS STATE FOR THE WHOLE SESSION IS NOT
         FREE, AND "it might help if we ever crash" is not a reason to ship it
         switched on. Measure the report's hit rate: this one is zero. */
    ((ULONG (WINAPI*)(void*))(*itf)[2])(s);          /* Release                                */
    log_line("DRED: auto-breadcrumbs FORCED ON before device creation "
             "(page-fault allocation tracking deliberately NOT enabled -- it "
             "retains every GPU allocation, live and freed, all session)");
}

/* ---- INVALID_CALL: make D3D12 name the call ------------------------------
 *  The 11:12 repro answered the question the guards could not:
 *
 *      CRASH: access violation at exe+0xA07EEA -- reading from 0x0
 *      CRASH: roomguard draw=55234 draw2=12448 steam=0 map_hr=0x887A0005
 *      DRED:  *** DEVICE REMOVED *** GetDeviceRemovedReason = 0x887A0001 (INVALID_CALL)
 *      DRED:  page fault at GPU VA 0x0
 *
 *  DXGI_ERROR_DEVICE_REMOVED **because of INVALID_CALL**, and no GPU page
 *  fault. That rules out the whole family of theories that were on the table:
 *  it is not a TDR, not a driver bug, not VRAM, not a use-after-free the GPU
 *  tripped over. The runtime removed the device because the game made an
 *  illegal D3D12 call. Everything after -- 67,682 failed buffer maps caught by
 *  the roomguards, then a NULL read at 0xA07EEA -- is the corpse twitching.
 *
 *  D3D12 knows exactly which call it was, and will say so, but only through the
 *  debug layer, which the game never enables. So: enable it ourselves before
 *  the device is created, keep the ID3D12InfoQueue, and drain the stored
 *  messages when things go wrong -- from the crash handler, which is the only
 *  place guaranteed to run.
 *
 *  OPT-IN, because the debug layer is expensive and this DLL ships to every
 *  player: it only turns on when `patch_d3d12_debug.txt` sits next to the exe.
 *  If the layer is not installed, the log says so -- it needs the Windows
 *  optional feature "Graphics Tools".
 *
 *  ID3D12InfoQueue vtable: IUnknown 0-2, SetMessageCountLimit 3,
 *  ClearStoredMessages 4, GetMessage 5, ..., GetNumStoredMessages 8.
 */
/* {344488b7-6846-474b-b989-f027448245e0} ID3D12Debug */
static const GUID IID_D3D12Debug =
    {0x344488b7,0x6846,0x474b,{0xb9,0x89,0xf0,0x27,0x44,0x82,0x45,0xe0}};
/* {0742a90b-c387-483f-b946-30a7e4e61458} ID3D12InfoQueue */
static const GUID IID_InfoQueue =
    {0x0742a90b,0xc387,0x483f,{0xb9,0x46,0x30,0xa7,0xe4,0xe6,0x14,0x58}};

typedef struct {
    int    category;
    int    severity;
    int    id;
    const char* description;
    SIZE_T descriptionByteLength;
} D3D12Message;

static void* g_infoqueue = NULL;
static volatile LONG g_iq_drained = 0;

/* ---- 2026-09-19: the SYSTEM debug layer can be the wrong version ----------
 *  Installing "Graphics Tools" put d3d12SDKLayers.dll 10.0.26100.1 next to a
 *  D3D12Core.dll serviced to 10.0.26100.9278. With that pair, EnableDebugLayer
 *  followed by D3D12CreateDevice returns E_INVALIDARG (0x80070057) -- measured
 *  outside the game with a 30-line ctypes test -- and the game then crashes on
 *  its NULL device at exe+0xA0A32B before the title screen, on BOTH rig
 *  clients. A freshly added Feature on Demand stays at its base build until the
 *  next cumulative update, so this is the normal state right after the DISM.
 *
 *  The way round it needs no admin and no developer mode: the Agility SDK.
 *  ID3D12SDKConfiguration1::CreateDeviceFactory(ver, path) loads a D3D12Core
 *  and its MATCHING d3d12SDKLayers from a folder we ship, and the factory
 *  enables the debug layer and DRED on itself. (SetSDKVersion, the global
 *  variant, answers INVALID_CALL without developer mode -- also measured.)
 *  The folder is `<game>\D3D12Agility\` holding D3D12Core.dll and
 *  d3d12SDKLayers.dll from the Microsoft.Direct3D.D3D12 NuGet package; the
 *  SDK version is that package's minor number (619 for 1.619.x) and can be
 *  overridden with `sdk=NNN` in patch_d3d12_debug.txt.
 *
 *  If the folder is absent, the system layer is used only when the text file
 *  says `system` -- because on this machine it breaks device creation.
 *
 *  ID3D12SDKConfiguration1 vtable: 3 SetSDKVersion, 4 CreateDeviceFactory.
 *  ID3D12DeviceFactory vtable: 7 GetConfigurationInterface, 9 CreateDevice.
 * --------------------------------------------------------------------- */
typedef HRESULT (WINAPI *D3D12GetInterface_t)(const GUID*, const GUID*, void**);
/* {7cda6aca-a03e-49c8-9458-0334d20e07ce} */
static const GUID CLSID_SDKConfiguration =
    {0x7cda6aca,0xa03e,0x49c8,{0x94,0x58,0x03,0x34,0xd2,0x0e,0x07,0xce}};
/* {8aaf9303-ad25-48b9-9a57-d9c37e009d9f} ID3D12SDKConfiguration1 */
static const GUID IID_SDKConfiguration1 =
    {0x8aaf9303,0xad25,0x48b9,{0x9a,0x57,0xd9,0xc3,0x7e,0x00,0x9d,0x9f}};
/* {61f307d3-d34e-4e7c-8374-3ba4de23cccb} ID3D12DeviceFactory */
static const GUID IID_DeviceFactory =
    {0x61f307d3,0xd34e,0x4e7c,{0x83,0x74,0x3b,0xa4,0xde,0x23,0xcc,0xcb}};
/* {f2352aeb-dd84-49fe-b97b-a9dcfdcc1b4f} */
static const GUID CLSID_D3D12DebugCfg =
    {0xf2352aeb,0xdd84,0x49fe,{0xb9,0x7b,0xa9,0xdc,0xfd,0xcc,0x1b,0x4f}};
/* {4a75bbc4-9ff4-4ad8-9f18-abae84dc5ff2} */
static const GUID CLSID_D3D12DredCfg =
    {0x4a75bbc4,0x9ff4,0x4ad8,{0x9f,0x18,0xab,0xae,0x84,0xdc,0x5f,0xf2}};
/* {2852dd88-b484-4c0c-b6b1-67168500e600} ID3D12InfoQueue1 */
static const GUID IID_InfoQueue1 =
    {0x2852dd88,0xb484,0x4c0c,{0xb6,0xb1,0x67,0x16,0x85,0x00,0xe6,0x00}};

static void* g_d3d12_factory = NULL;

/* Reads patch_d3d12_debug.txt once: `sdk=NNN` and whether it says `system`. */
static void d3d12_debug_cfg(unsigned* sdk, int* allow_system)
{
    char buf[512];
    DWORD got = 0;
    HANDLE f = CreateFileA("patch_d3d12_debug.txt", GENERIC_READ, FILE_SHARE_READ, NULL,
                           OPEN_EXISTING, 0, NULL);
    const char* p;
    *sdk = 619;
    *allow_system = 0;
    if (f == INVALID_HANDLE_VALUE) return;
    if (!ReadFile(f, buf, sizeof(buf) - 1, &got, NULL)) got = 0;
    CloseHandle(f);
    buf[got] = 0;
    if ((p = strstr(buf, "sdk=")) != NULL && atoi(p + 4) > 0) *sdk = (unsigned)atoi(p + 4);
    if (strstr(buf, "system")) *allow_system = 1;
}

/* Builds the Agility device factory with the debug layer and DRED switched on.
   Returns 1 when the game's devices will come from it. */
static int d3d12_agility_factory(void)
{
    HMODULE d3d12 = GetModuleHandleA("d3d12.dll");
    D3D12GetInterface_t gi;
    char dir[MAX_PATH], core[MAX_PATH + 32], layers[MAX_PATH + 32];
    char* slash;
    unsigned sdk; int allow_system;
    void* cfg = NULL; void* fac = NULL; void* itf = NULL;
    HRESULT hr;

    d3d12_debug_cfg(&sdk, &allow_system);
    if (!GetModuleFileNameA(NULL, dir, MAX_PATH)) return 0;
    if ((slash = strrchr(dir, '\\')) != NULL) slash[1] = 0;
    if (strlen(dir) + 16 >= MAX_PATH) return 0;
    strcat(dir, "D3D12Agility\\");
    wsprintfA(core, "%sD3D12Core.dll", dir);
    wsprintfA(layers, "%sd3d12SDKLayers.dll", dir);
    if (GetFileAttributesA(core) == INVALID_FILE_ATTRIBUTES ||
        GetFileAttributesA(layers) == INVALID_FILE_ATTRIBUTES) {
        log_line("D3D12DEBUG/agility: no D3D12Core.dll + d3d12SDKLayers.dll in %s -- "
                 "the Agility route is off", dir);
        return 0;
    }
    if (!d3d12 || !(gi = (D3D12GetInterface_t)GetProcAddress(d3d12, "D3D12GetInterface"))) {
        log_line("D3D12DEBUG/agility: this d3d12.dll has no D3D12GetInterface -- off");
        return 0;
    }
    hr = gi(&CLSID_SDKConfiguration, &IID_SDKConfiguration1, &cfg);
    if (hr < 0 || !cfg) {
        log_line("D3D12DEBUG/agility: no ID3D12SDKConfiguration1 (hr 0x%08lX) -- off",
                 (unsigned long)hr);
        return 0;
    }
    hr = ((HRESULT (WINAPI*)(void*, unsigned, const char*, const GUID*, void**))
          (*(void***)cfg)[4])(cfg, sdk, dir, &IID_DeviceFactory, &fac);
    ((ULONG (WINAPI*)(void*))(*(void***)cfg)[2])(cfg);
    if (hr < 0 || !fac) {
        log_line("D3D12DEBUG/agility: CreateDeviceFactory(sdk %u, %s) failed, hr 0x%08lX -- "
                 "does the folder's D3D12Core match sdk=%u?", sdk, dir, (unsigned long)hr, sdk);
        return 0;
    }
    if (((HRESULT (WINAPI*)(void*, const GUID*, const GUID*, void**))(*(void***)fac)[7])
            (fac, &CLSID_D3D12DebugCfg, &IID_D3D12Debug, &itf) >= 0 && itf) {
        ((void (WINAPI*)(void*))(*(void***)itf)[3])(itf);          /* EnableDebugLayer */
        ((ULONG (WINAPI*)(void*))(*(void***)itf)[2])(itf);
        itf = NULL;
    } else {
        log_line("D3D12DEBUG/agility: factory has no debug interface -- continuing without it");
    }
    if (ENABLE_DRED &&
        ((HRESULT (WINAPI*)(void*, const GUID*, const GUID*, void**))(*(void***)fac)[7])
            (fac, &CLSID_D3D12DredCfg, &IID_DREDSettings, &itf) >= 0 && itf) {
        ((void (WINAPI*)(void*, int))(*(void***)itf)[3])(itf, 2);   /* breadcrumbs FORCED_ON */
        ((ULONG (WINAPI*)(void*))(*(void***)itf)[2])(itf);
    }
    g_d3d12_factory = fac;
    log_line("D3D12DEBUG/agility: device factory ready -- Agility SDK %u from %s, debug "
             "layer ON, DRED breadcrumbs ON; the game's device will be created by it", sdk, dir);
    return 1;
}

/* Called by the debug layer, on the thread making the D3D12 call, for every
   message it produces. ERROR and CORRUPTION are logged the moment they happen,
   with the exe frames on that thread's stack -- which names the GAME function
   that made the illegal call, not only the API. Capped, and deduplicated by
   message id after the first few of each. */
static void desc_who_copied(unsigned long long handle);   /* PART 31 */

static volatile LONG g_iqcb_lines = 0;
static void __stdcall d3d12_msg_cb(int category, int severity, int id,
                                   const char* desc, void* ctx)
{
    static volatile LONG seen[64];
    static volatile LONG seen_n = 0;
    void* frames[48];
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    IMAGE_NT_HEADERS* nt;
    unsigned long long lo, hi;
    USHORT n, i;
    int shown = 0, k, repeats = 0;
    char line[512];
    size_t used;
    (void)ctx;
    if (severity > 1) return;                            /* 0 CORRUPTION, 1 ERROR */
    for (k = 0; k < seen_n && k < 64; k++)
        if (seen[k] == id) { repeats = 1; break; }
    if (!repeats && seen_n < 64) {
        LONG s = InterlockedIncrement(&seen_n) - 1;
        if (s < 64) seen[s] = id;
    }
    /* ★ 2026-09-20: the cap was spent entirely on the game's own pre-existing
       noise -- 303 lines of id=615 and id=1319 in five seconds -- and the
       message that names the removal never got logged. These ids are logged
       once each and never count against the cap. */
    {
        static const int noise[] = { 615, 1319, 520, 538, 838 };
        int is_noise = 0, z;
        for (z = 0; z < (int)(sizeof noise / sizeof noise[0]); z++)
            if (noise[z] == id) { is_noise = 1; break; }
        if (is_noise && repeats) return;
        if (!is_noise && InterlockedIncrement(&g_iqcb_lines) > 400) return;
    }
    log_line("D3D12DEBUG/live: [%s cat=%d id=%d] %.600s (thread %lu)",
             severity == 0 ? "CORRUPTION" : "ERROR", category, id,
             desc ? desc : "(no text)", GetCurrentThreadId());
    /* The STATIC-descriptor message carries the offending CPU handle. Read it
       out of the text and ask the map who last copied over that descriptor:
       that answer is the game function this whole hunt is for. */
    if (desc) {
        const char* q = strstr(desc, "CPU Handle 0x");
        if (q) {
            unsigned long long hnd = 0;
            q += 13;
            while ((*q >= '0' && *q <= '9') || (*q >= 'a' && *q <= 'f') || (*q >= 'A' && *q <= 'F')) {
                hnd = (hnd << 4) | (unsigned long long)(*q <= '9' ? *q - '0' : (*q | 32) - 'a' + 10);
                q++;
            }
            desc_who_copied(hnd);
        }
    }
    if (repeats || !mod) return;                         /* stack only on the first of each id */
    nt = (IMAGE_NT_HEADERS*)(mod + ((IMAGE_DOS_HEADER*)mod)->e_lfanew);
    lo = (unsigned long long)mod;
    hi = lo + nt->OptionalHeader.SizeOfImage;
    n = RtlCaptureStackBackTrace(0, 48, frames, NULL);
    used = (size_t)wsprintfA(line, "D3D12DEBUG/live:   exe frames:");
    for (i = 0; i < n && shown < 14; i++) {
        unsigned long long a = (unsigned long long)frames[i];
        if (a < lo || a >= hi) continue;
        used += (size_t)wsprintfA(line + used, " exe+0x%I64X", a - lo);
        shown++;
        if (used > sizeof(line) - 32) break;
    }
    if (!shown) wsprintfA(line + used, " (none in the first 48)");
    log_line("%s", line);
}

static void d3d12_debug_enable(void)      /* called before device creation */
{
    HMODULE d3d12 = GetModuleHandleA("d3d12.dll");
    D3D12GetDebugInterface_t get;
    void* dbg = NULL;
    unsigned sdk; int allow_system;
    if (!file_exists("patch_d3d12_debug.txt")) return;
    d3d12_debug_cfg(&sdk, &allow_system);
    if (!allow_system) {
        log_line("D3D12DEBUG: the SYSTEM debug layer is not used -- on this machine its "
                 "version did not match D3D12Core and device creation failed with "
                 "E_INVALIDARG. Put the Agility files in D3D12Agility\\, or write `system` "
                 "in patch_d3d12_debug.txt to force the system layer.");
        return;
    }
    if (!d3d12) return;
    get = (D3D12GetDebugInterface_t)GetProcAddress(d3d12, "D3D12GetDebugInterface");
    if (!get) return;
    if (get(&IID_D3D12Debug, &dbg) < 0 || !dbg) {
        log_line("D3D12DEBUG: requested by patch_d3d12_debug.txt but the debug layer is "
                 "not installed -- add the Windows optional feature \"Graphics Tools\" "
                 "(DISM /online /Add-Capability /CapabilityName:Tools.Graphics.DirectX~~~~0.0.1.0)");
        return;
    }
    ((void (WINAPI*)(void*))(*(void***)dbg)[3])(dbg);        /* EnableDebugLayer */
    ((ULONG (WINAPI*)(void*))(*(void***)dbg)[2])(dbg);       /* Release          */
    log_line("D3D12DEBUG: debug layer ENABLED (patch_d3d12_debug.txt present) -- the "
             "invalid call that removes the device will be named in this log");
}

static void d3d12_debug_attach(void* device)   /* called after device creation */
{
    void* iq = NULL;
    if (!device || !file_exists("patch_d3d12_debug.txt")) return;
    if (((HRESULT (WINAPI*)(void*, const GUID*, void**))(*(void***)device)[0])
            (device, &IID_InfoQueue, &iq) < 0 || !iq) {
        log_line("D3D12DEBUG: no ID3D12InfoQueue on this device (debug layer off?)");
        return;
    }
    ((HRESULT (WINAPI*)(void*, unsigned long long))(*(void***)iq)[3])(iq, 4096);
    g_infoqueue = iq;
    log_line("D3D12DEBUG: info queue attached, storing up to 4096 messages");
    {
        void* iq1 = NULL;
        DWORD cookie = 0;
        HRESULT hr = -1;
        if (((HRESULT (WINAPI*)(void*, const GUID*, void**))(*(void***)device)[0])
                (device, &IID_InfoQueue1, &iq1) >= 0 && iq1) {
            hr = ((HRESULT (WINAPI*)(void*, void*, int, void*, DWORD*))(*(void***)iq1)[38])
                    (iq1, (void*)&d3d12_msg_cb, 0, NULL, &cookie);  /* RegisterMessageCallback */
            log_line("D3D12DEBUG: live message callback %s (hr 0x%08lX, cookie %lu) -- every "
                     "ERROR/CORRUPTION is logged as it happens, with the exe frames that made "
                     "the call", hr >= 0 ? "REGISTERED" : "REFUSED", (unsigned long)hr, cookie);
            /* iq1 is kept referenced for the life of the process on purpose */
        } else {
            log_line("D3D12DEBUG: no ID3D12InfoQueue1 -- errors are only read back at a "
                     "throw, a device removal or a crash, never live");
        }
        /* ★★ 2026-09-20, measured: SetMuteDebugOutput(TRUE) silences the CALLBACK too,
           not just OutputDebugString. A muted queue stored 4096 messages and called us
           zero times, and the first build read as "the callback does not work". So the
           mute is only for the case where there is no callback to lose -- and then it
           is worth having, because every message otherwise raises a first-chance
           0x40010006 through our own VEH. */
        if (hr < 0) {
            ((void (WINAPI*)(void*, BOOL))(*(void***)iq)[36])(iq, TRUE);
            log_line("D3D12DEBUG: OutputDebugString muted (no callback to keep alive)");
        }
    }
}

/* Drain whatever D3D12 complained about. Errors and corruption first: with
   INVALID_CALL the offending call is an ERROR or CORRUPTION message, and it is
   logged verbatim -- message id included, which is what names the API call. */
static void d3d12_debug_drain(const char* why)
{
    void* iq = g_infoqueue;
    unsigned long long n, i, start;
    char buf[1024];
    SIZE_T len;
    D3D12Message* m;
    int shown = 0;

    if (!iq) return;
    /* Up to three drains per session, not one: the first useful one used to be
       spent by an unrelated first-chance fault, and the message that matters is
       the one next to the throw or the removal. */
    if (InterlockedIncrement(&g_iq_drained) > 3) return;
    n = ((unsigned long long (WINAPI*)(void*))(*(void***)iq)[8])(iq);  /* GetNumStoredMessages */
    log_line("D3D12DEBUG: %llu stored messages at %s", n, why);
    start = n > 40 ? n - 40 : 0;
    for (i = start; i < n && shown < 20; i++) {
        len = sizeof(buf);
        if (((HRESULT (WINAPI*)(void*, unsigned long long, void*, SIZE_T*))(*(void***)iq)[5])
                (iq, i, buf, &len) < 0) continue;
        m = (D3D12Message*)buf;
        if (m->severity > 1) continue;            /* 0 CORRUPTION, 1 ERROR */
        log_line("D3D12DEBUG:   [%s id=%d] %.400s",
                 m->severity == 0 ? "CORRUPTION" : "ERROR", m->id,
                 m->description ? m->description : "(no text)");
        shown++;
    }
    if (!shown) log_line("D3D12DEBUG:   no error/corruption messages stored");
}

/* ============ PART 30: THE ROOM-LOBBY DEVICE REMOVAL, AT ITS CAUSE ========
 *  2026-09-20, measured with the debug layer on (the Agility route above), on
 *  the two-client rig, at the moment the opponent changed character:
 *
 *    [ERROR id=1001] ID3D12CommandQueue1::ExecuteCommandLists: Descriptor (at
 *    CPU Handle 0x...1E0) is bound as STATIC (not-DESCRIPTORS_VOLATILE) on
 *    Command List 0x...:'CommandList'. It was most recently changed by
 *    CopyDescriptorsSimple call, but it is invalid to change it until the
 *    command list has finished executing for the last time.
 *    DRED: *** DEVICE REMOVED *** GetDeviceRemovedReason = 0x887A0001
 *
 *  So the game rebinds the member's art by copying a descriptor over a slot a
 *  RECORDED, still-executing command list declares STATIC. Root signature 1.1
 *  lets a shader promise the runtime that a table's descriptors will not move
 *  between recording and execution; this one does move, and the runtime
 *  answers by removing the device. Everything the ROOMGUARD patches swallow
 *  afterwards is the corpse.
 *
 *  The promise is the only thing wrong here, and it is ours to withdraw:
 *  marking the ranges DESCRIPTORS_VOLATILE (which is what root signature 1.0
 *  meant, and what these shaders were evidently written against) makes the
 *  same sequence legal. The cost is defined behaviour rather than removal: the
 *  draw in flight may read the new descriptor, i.e. one frame of the wrong
 *  portrait, instead of killing the device.
 *
 *  Two entry points, because a root signature can arrive either way and which
 *  one this game uses is counted rather than assumed:
 *    - D3D12SerializeVersionedRootSignature, hooked in the IAT (found by
 *      scanning for the resolved address -- EAC repacks the import table, so
 *      the directory cannot be walked statically);
 *    - ID3D12Device::CreateRootSignature (vtable 16) for blobs that were
 *      serialised earlier, e.g. the PLRS chunks in the dx12 .pld libraries.
 *      There the RTS0 chunk is patched in a copy of the blob, and a refusal
 *      falls straight back to the original bytes.
 *
 *  OFF by default: it changes what every shader in the game promises.
 * --------------------------------------------------------------------- */
#ifndef ENABLE_RS_VOLATILE
#define ENABLE_RS_VOLATILE 0
#endif

/* D3D12_DESCRIPTOR_RANGE_FLAGS */
#define RS_DESCRIPTORS_VOLATILE 0x1
#define RS_DATA_VOLATILE        0x2

typedef struct { UINT RangeType, NumDescriptors, BaseShaderRegister, RegisterSpace, Flags,
                      OffsetInDescriptorsFromTableStart; } RsRange1;
typedef struct { UINT NumDescriptorRanges; const RsRange1* pDescriptorRanges; } RsTable1;
typedef struct { UINT ParameterType; union { RsTable1 t; UINT raw[3]; } u; UINT ShaderVisibility; } RsParam1;
typedef struct { UINT NumParameters; const RsParam1* pParameters;
                 UINT NumStaticSamplers; const void* pStaticSamplers; UINT Flags; } RsDesc1;
typedef struct { UINT Version; union { RsDesc1 d11; char pad[64]; } u; } RsVersionedDesc;

typedef HRESULT (WINAPI *SerializeVersionedRS_t)(const RsVersionedDesc*, void**, void**);
static SerializeVersionedRS_t o_SerializeVersionedRS = NULL;
static HRESULT (WINAPI *o_CreateRootSignature)(void*, UINT, const void*, SIZE_T,
                                               const GUID*, void**) = NULL;
static volatile LONG g_rs_serialized = 0, g_rs_serialized_fixed = 0;
static volatile LONG g_rs_blobs = 0, g_rs_blobs_fixed = 0, g_rs_blobs_refused = 0;

/* A sampler range may not carry the DATA_* flags; everything else takes both. */
static UINT rs_volatile_flags(UINT rangeType)
{
    return rangeType == 3 /* SAMPLER */ ? RS_DESCRIPTORS_VOLATILE
                                        : (RS_DESCRIPTORS_VOLATILE | RS_DATA_VOLATILE);
}

static HRESULT WINAPI hk_SerializeVersionedRS(const RsVersionedDesc* desc,
                                              void** ppBlob, void** ppErr)
{
    RsVersionedDesc copy;
    RsParam1* params = NULL;
    RsRange1* ranges = NULL;
    UINT i, j, nranges = 0, cursor = 0;
    HRESULT hr;

    InterlockedIncrement(&g_rs_serialized);
    if (!desc || desc->Version != 2 /* 1_1 */ || !desc->u.d11.NumParameters)
        return o_SerializeVersionedRS(desc, ppBlob, ppErr);

    for (i = 0; i < desc->u.d11.NumParameters; i++)
        if (desc->u.d11.pParameters[i].ParameterType == 0 /* DESCRIPTOR_TABLE */)
            nranges += desc->u.d11.pParameters[i].u.t.NumDescriptorRanges;
    if (!nranges) return o_SerializeVersionedRS(desc, ppBlob, ppErr);

    params = (RsParam1*)HeapAlloc(GetProcessHeap(), 0, sizeof(RsParam1) * desc->u.d11.NumParameters);
    ranges = (RsRange1*)HeapAlloc(GetProcessHeap(), 0, sizeof(RsRange1) * nranges);
    if (!params || !ranges) {
        if (params) HeapFree(GetProcessHeap(), 0, params);
        if (ranges) HeapFree(GetProcessHeap(), 0, ranges);
        return o_SerializeVersionedRS(desc, ppBlob, ppErr);
    }
    copy = *desc;
    for (i = 0; i < desc->u.d11.NumParameters; i++) {
        params[i] = desc->u.d11.pParameters[i];
        if (params[i].ParameterType != 0) continue;
        for (j = 0; j < desc->u.d11.pParameters[i].u.t.NumDescriptorRanges; j++) {
            ranges[cursor + j] = desc->u.d11.pParameters[i].u.t.pDescriptorRanges[j];
            ranges[cursor + j].Flags = rs_volatile_flags(ranges[cursor + j].RangeType);
        }
        params[i].u.t.pDescriptorRanges = &ranges[cursor];
        cursor += desc->u.d11.pParameters[i].u.t.NumDescriptorRanges;
    }
    copy.u.d11.pParameters = params;
    hr = o_SerializeVersionedRS(&copy, ppBlob, ppErr);
    if (hr >= 0) InterlockedIncrement(&g_rs_serialized_fixed);
    else hr = o_SerializeVersionedRS(desc, ppBlob, ppErr);   /* never lose a root signature */
    HeapFree(GetProcessHeap(), 0, params);
    HeapFree(GetProcessHeap(), 0, ranges);
    return hr;
}

/* The serialised form inside a DXBC container's RTS0 chunk, and it is NOT the
   in-memory struct: a parameter record is 12 bytes and its payload lives at an
   offset, where the API packs the union inline. Read off three real blobs from
   the game's own tam_sys\Shader\dx12\system.pld before writing this:

     header   u32 Version, NumParameters, ParametersOffset, NumStaticSamplers,
              StaticSamplersOffset, Flags
     param[i] at ParametersOffset + i*12:  u32 ParameterType, ShaderVisibility,
              PayloadOffset
     table    at PayloadOffset:            u32 NumDescriptorRanges, RangesOffset
     range[j] at RangesOffset + j*24:      u32 RangeType, NumDescriptors,
              BaseShaderRegister, RegisterSpace, Flags, OffsetFromTableStart

   Every offset is from the start of the RTS0 DATA. Flags read 0 on the shipped
   blobs, which in 1.1 means "descriptors static, data static while set at
   execute" -- exactly the promise the lobby breaks.

   ⚠ A first version used the in-memory 20-byte stride. It wrote flags over
   whatever sat there, and the runtime answered "Unsupported RangeType value
   768" and then refused whole pipelines. So: validate FIRST, write second, and
   refuse the whole blob on anything unexpected. Returns ranges rewritten, or
   -1 for "not something I understand, leave it alone". */
static int rs_patch_blob(unsigned char* b, SIZE_T len)
{
    UINT chunks, i, ver, nparam, poff, p, fixed = 0;
    unsigned char* rts0 = NULL;
    SIZE_T rts_off = 0, rts_len = 0;
    int pass;

    if (len < 36 || memcmp(b, "DXBC", 4) != 0) return -1;
    chunks = *(UINT*)(b + 28);
    if (chunks == 0 || 32 + 4 * (SIZE_T)chunks > len) return -1;
    for (i = 0; i < chunks; i++) {
        UINT off = ((UINT*)(b + 32))[i];
        if ((SIZE_T)off + 8 > len) return -1;
        if (memcmp(b + off, "RTS0", 4) == 0) {
            rts_len = *(UINT*)(b + off + 4);
            rts_off = (SIZE_T)off + 8;
            if (rts_off + rts_len > len) return -1;
            rts0 = b + rts_off;
            break;
        }
    }
    if (!rts0 || rts_len < 24) return -1;
    ver = *(UINT*)rts0;
    if (ver == 1) return 0;                      /* 1.0 is volatile by definition */
    if (ver != 2 && ver != 3) return -1;         /* 1.1 and 1.2 share this layout  */
    nparam = *(UINT*)(rts0 + 4);
    poff   = *(UINT*)(rts0 + 8);
    if (nparam > 64) return -1;
    if ((SIZE_T)poff + (SIZE_T)nparam * 12 > rts_len) return -1;

    /* pass 0 validates every byte this function would write; pass 1 writes. */
    for (pass = 0; pass < 2; pass++) {
        fixed = 0;
        for (p = 0; p < nparam; p++) {
            unsigned char* par = rts0 + poff + (SIZE_T)p * 12;
            UINT payload, nranges, roff, r;
            if (*(UINT*)par != 0) continue;      /* not a descriptor table */
            payload = *(UINT*)(par + 8);
            if ((SIZE_T)payload + 8 > rts_len) return -1;
            nranges = *(UINT*)(rts0 + payload);
            roff    = *(UINT*)(rts0 + payload + 4);
            if (nranges > 256) return -1;
            if ((SIZE_T)roff + (SIZE_T)nranges * 24 > rts_len) return -1;
            for (r = 0; r < nranges; r++) {
                unsigned char* rg = rts0 + roff + (SIZE_T)r * 24;
                UINT type = *(UINT*)rg;
                if (type > 3) return -1;         /* SRV UAV CBV SAMPLER, nothing else */
                if (pass) *(UINT*)(rg + 16) = rs_volatile_flags(type);
                fixed++;
            }
        }
        if (!fixed) return 0;
    }
    return (int)fixed;
}

static HRESULT WINAPI hk_CreateRootSignature(void* dev, UINT nodeMask, const void* blob,
                                             SIZE_T len, const GUID* riid, void** ppv)
{
    unsigned char* copy;
    HRESULT hr;
    int fixed;
    InterlockedIncrement(&g_rs_blobs);
    if (!blob || !len) return o_CreateRootSignature(dev, nodeMask, blob, len, riid, ppv);
    copy = (unsigned char*)HeapAlloc(GetProcessHeap(), 0, len);
    if (!copy) return o_CreateRootSignature(dev, nodeMask, blob, len, riid, ppv);
    memcpy(copy, blob, len);
    fixed = rs_patch_blob(copy, len);
    if (fixed <= 0) {
        HeapFree(GetProcessHeap(), 0, copy);
        return o_CreateRootSignature(dev, nodeMask, blob, len, riid, ppv);
    }
    hr = o_CreateRootSignature(dev, nodeMask, copy, len, riid, ppv);
    HeapFree(GetProcessHeap(), 0, copy);
    if (hr >= 0) { InterlockedIncrement(&g_rs_blobs_fixed); return hr; }
    InterlockedIncrement(&g_rs_blobs_refused);
    return o_CreateRootSignature(dev, nodeMask, blob, len, riid, ppv);
}

/* The IAT slot is found by its VALUE, because EAC repacks the import table --
   the directory cannot be walked, but the resolved address is still in .rdata. */
static void rs_hook_serializer(void)
{
    HMODULE d3d12 = GetModuleHandleA("d3d12.dll");
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    IMAGE_NT_HEADERS* nt;
    IMAGE_SECTION_HEADER* sh;
    void* target;
    int i, hits = 0;
    if (!d3d12 || !mod) return;
    target = (void*)GetProcAddress(d3d12, "D3D12SerializeVersionedRootSignature");
    if (!target) { log_line("RSVOLATILE: d3d12.dll has no versioned serializer -- skipped"); return; }
    nt = (IMAGE_NT_HEADERS*)(mod + ((IMAGE_DOS_HEADER*)mod)->e_lfanew);
    sh = IMAGE_FIRST_SECTION(nt);
    for (i = 0; i < nt->FileHeader.NumberOfSections; i++, sh++) {
        void** p; void** end;
        if (memcmp(sh->Name, ".rdata", 6) != 0) continue;
        p   = (void**)(mod + sh->VirtualAddress);
        end = (void**)(mod + sh->VirtualAddress + sh->Misc.VirtualSize - sizeof(void*));
        for (; p <= end; p++) {
            DWORD old;
            if (*p != target) continue;
            if (!VirtualProtect(p, sizeof(void*), PAGE_READWRITE, &old)) continue;
            o_SerializeVersionedRS = (SerializeVersionedRS_t)target;
            *p = (void*)&hk_SerializeVersionedRS;
            VirtualProtect(p, sizeof(void*), old, &old);
            hits++;
        }
    }
    log_line("RSVOLATILE: serializer hook on %d IAT slot(s) -- every descriptor range a "
             "root signature 1.1 declares STATIC becomes DESCRIPTORS_VOLATILE, which is "
             "what the room-lobby device removal is caused by promising", hits);
}

/* The device's own vtable, patched once. Slot 16 is CreateRootSignature. */
static void rs_hook_device(void* device)
{
    void*** dev = (void***)device;
    DWORD old;
    if (!device || o_CreateRootSignature) return;
    o_CreateRootSignature = (HRESULT (WINAPI*)(void*, UINT, const void*, SIZE_T,
                                               const GUID*, void**))(*dev)[16];
    if (!VirtualProtect(&(*dev)[16], sizeof(void*), PAGE_READWRITE, &old)) {
        log_line("RSVOLATILE: could not unprotect the device vtable -- blob path off");
        o_CreateRootSignature = NULL;
        return;
    }
    (*dev)[16] = (void*)&hk_CreateRootSignature;
    VirtualProtect(&(*dev)[16], sizeof(void*), old, &old);
    log_line("RSVOLATILE: CreateRootSignature hooked (device vtable slot 16) -- "
             "pre-serialised blobs get their RTS0 ranges rewritten too");
}

/* ============ PART 31: WHO COPIES THE DESCRIPTOR =========================
 *  2026-09-20, measured on the rig: with every descriptor range rewritten
 *  VOLATILE (PART 30 -- 8003 blobs, 7974 rewritten, 0 refused, plus 7951
 *  serializer calls made volatile) the room-lobby removal happened again,
 *  same reason 0x887A0001 INVALID_CALL, at the same moment. So one of two
 *  things is true: the offending root signature never passes through either
 *  entry point, or the illegal call is a different one. Both are answered by
 *  naming the game function that copies, and by asking the runtime whether
 *  the device is gone the instant a command list is submitted.
 *
 *  Two hooks, diagnostics only -- nothing is changed for the game:
 *    ID3D12Device::CopyDescriptorsSimple     (vtable 24) -> a 128-entry ring of
 *        (destination handle, count, heap type, thread, caller RVA).
 *    ID3D12CommandQueue::ExecuteCommandLists (vtable 10) -> GetDeviceRemovedReason
 *        after the call. The first submit that reports a removed device dumps
 *        the ring, so the last copies before the removal and the exe RVA that
 *        made them are on disk even though the game does not die there.
 *
 *  The queue vtable is shared by every queue of the device, so it is patched
 *  once, from a CreateCommandQueue (vtable 8) hook.
 * ----------------------------------------------------------------------- */
#ifndef ENABLE_DESC_RING
#define ENABLE_DESC_RING 0
#endif

#if defined(__GNUC__) || defined(__clang__)
#define DESC_RET_ADDR() ((UINT64)(SIZE_T)__builtin_return_address(0))
#else
#define DESC_RET_ADDR() ((UINT64)(SIZE_T)_ReturnAddress())
#endif

typedef struct { UINT64 dest, ret; UINT num, type; DWORD tid; } DescCopy;

/* The ring is only milliseconds deep at 17 000 copies a second, and the
   debug layer names the offending descriptor by its CPU handle rather than by
   time. So the handle is the key: this map holds, per destination, the last
   copy that wrote it and the exe frames that made it. */
#define DMAP_N 8192
typedef struct { UINT64 dest; UINT64 f[4]; UINT seq, num, type; DWORD tid; } DescSlot;
static DescSlot      g_dmap[DMAP_N];
static DescCopy      g_dring[128];
static volatile LONG g_dring_n = 0;        /* total copies; the low 7 bits are the slot */
static volatile LONG g_dring_dumped = 0;
static volatile LONG g_exec_calls = 0;
static volatile LONG g_exec_noticed = 0;

static void    (WINAPI* o_CopyDescriptorsSimple)(void*, UINT, SIZE_T, SIZE_T, UINT) = NULL;
static HRESULT (WINAPI* o_CreateCommandQueue)(void*, const void*, const GUID*, void**) = NULL;
static void    (WINAPI* o_ExecuteCommandLists)(void*, UINT, void* const*) = NULL;

/* A CPU descriptor handle is one SIZE_T wide, so it travels in a register
   exactly like the struct the API declares. */
static void WINAPI hk_CopyDescriptorsSimple(void* dev, UINT num, SIZE_T dst, SIZE_T src, UINT type)
{
    LONG i = InterlockedIncrement(&g_dring_n) - 1;
    DescCopy* e = &g_dring[i & 127];
    DescSlot* m = &g_dmap[(UINT)((((UINT64)dst >> 5) ^ ((UINT64)dst >> 17)) & (DMAP_N - 1))];
    void* fr[8];
    USHORT nf, k;
    int kept = 0;
    e->dest = (UINT64)dst;
    e->ret  = DESC_RET_ADDR();
    e->num  = num;
    e->type = type;
    e->tid  = GetCurrentThreadId();
    /* The leaf is always the same copy helper, so the answer is one frame up:
       capture the stack rather than the return address alone. */
    nf = RtlCaptureStackBackTrace(1, 8, fr, NULL);
    for (k = 0; k < nf && kept < 4; k++) m->f[kept++] = (UINT64)(SIZE_T)fr[k];
    while (kept < 4) m->f[kept++] = 0;
    m->num  = num;
    m->type = type;
    m->tid  = e->tid;
    m->seq  = (UINT)i;
    m->dest = (UINT64)dst;          /* written last: a reader sees a complete entry */
    o_CopyDescriptorsSimple(dev, num, dst, src, type);
}

static void desc_who_copied(unsigned long long handle)
{
    unsigned char* mod;
    UINT64 lo, hi;
    DescSlot* best = NULL;
    DescSlot* h;
    UINT i;
    char line[512];
    size_t used;
    int k;
    if (!ENABLE_DESC_RING || !o_CopyDescriptorsSimple || !handle) return;
    h = &g_dmap[(UINT)(((handle >> 5) ^ (handle >> 17)) & (DMAP_N - 1))];
    if (h->dest == handle) best = h;
    if (!best)                       /* a multi-descriptor copy covers a range */
        for (i = 0; i < DMAP_N; i++) {
            DescSlot* t = &g_dmap[i];
            if (!t->dest || t->dest > handle) continue;
            if (handle - t->dest >= (UINT64)t->num * 64) continue;
            if ((handle - t->dest) % 32) continue;
            if (!best || t->seq > best->seq) best = t;
        }
    if (!best) {
        log_line("DESCRING: no recorded copy wrote descriptor 0x%I64X -- it was written by "
                 "something other than CopyDescriptorsSimple (CreateShaderResourceView and "
                 "friends write descriptors too), or the map has already been overwritten",
                 handle);
        return;
    }
    mod = (unsigned char*)GetModuleHandleA(NULL);
    lo = (UINT64)(SIZE_T)mod; hi = lo;
    if (mod) {
        IMAGE_NT_HEADERS* nt = (IMAGE_NT_HEADERS*)(mod + ((IMAGE_DOS_HEADER*)mod)->e_lfanew);
        hi = lo + nt->OptionalHeader.SizeOfImage;
    }
    used = (size_t)wsprintfA(line, "DESCRING: *** descriptor 0x%I64X was last copied by #%u "
                             "(dest 0x%I64X num=%u heap=%u thread=%lu) from:",
                             handle, best->seq, best->dest, best->num, best->type, best->tid);
    for (k = 0; k < 4 && best->f[k]; k++) {
        UINT64 a = best->f[k];
        if (a >= lo && a < hi) used += (size_t)wsprintfA(line + used, " exe+0x%I64X", a - lo);
        else                   used += (size_t)wsprintfA(line + used, " 0x%I64X", a);
    }
    log_line("%s", line);
}

static void desc_ring_dump(const char* why)
{
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    UINT64 lo = (UINT64)(SIZE_T)mod, hi = lo;
    LONG n, i, shown;
    if (!ENABLE_DESC_RING || !o_CopyDescriptorsSimple) return;
    if (InterlockedIncrement(&g_dring_dumped) > 3) return;
    if (mod) {
        IMAGE_NT_HEADERS* nt = (IMAGE_NT_HEADERS*)(mod + ((IMAGE_DOS_HEADER*)mod)->e_lfanew);
        hi = lo + nt->OptionalHeader.SizeOfImage;
    }
    n = g_dring_n;
    shown = n > 32 ? 32 : n;
    log_line("DESCRING: %ld CopyDescriptorsSimple calls, %ld ExecuteCommandLists -- the last "
             "%ld copies before %s, newest first", n, g_exec_calls, shown, why);
    for (i = 0; i < shown; i++) {
        DescCopy* e = &g_dring[(n - 1 - i) & 127];
        if (e->ret >= lo && e->ret < hi)
            log_line("DESCRING:   #%ld dest=0x%llX num=%u heap=%u thread=%lu  caller exe+0x%llX",
                     n - 1 - i, e->dest, e->num, e->type, e->tid, e->ret - lo);
        else
            log_line("DESCRING:   #%ld dest=0x%llX num=%u heap=%u thread=%lu  caller 0x%llX "
                     "(outside the exe)", n - 1 - i, e->dest, e->num, e->type, e->tid, e->ret);
    }
}

/* ============ PART 32: THE BARRIER WITH NO RESOURCE =======================
 *  Measured 2026-09-20, host client, in the room lobby, in this order:
 *      [id=520]  ResourceBarrier: NULL pointer specified
 *      THROW     _com_error 0x80070057 (E_INVALIDARG)
 *      [id=838]  ExecuteCommandLists: Command lists must be successfully closed
 *      [id=232]  RemoveDevice -- DXGI_ERROR_INVALID_CALL
 *  So the device is not removed by the descriptor copy itself. The game
 *  barriers a resource it no longer has -- the member art it is in the middle
 *  of swapping -- a D3D12 call answers E_INVALIDARG, the game's own
 *  ThrowIfFailed throws out of the middle of the recording, the command list is
 *  therefore never closed, and submitting an unclosed list is the illegal call
 *  that kills the device.
 *
 *  The cheapest place to break that chain is its first link: a barrier whose
 *  resource is NULL does nothing anyway, so it is dropped instead of passed on.
 *  Dropping it leaves the resource in the state it was already in, which is
 *  what a barrier on a resource that does not exist means.
 * ----------------------------------------------------------------------- */
/* ON by default since 2026-09-21. Measured on the rig: when the room lobby
   swaps the member art, the list is poisoned BEFORE any guard of ours touches
   it -- Close answers 0x80004005 E_FAIL and every later Reset answers
   0x80070057, which is the black screen. A command list only refuses to close
   when the runtime recorded an error into it, and the error the debug layer
   named twice at that exact moment is `id=520 ResourceBarrier: NULL pointer
   specified`. Dropping that barrier is therefore not a nicety: it is what
   keeps the list recordable. Build with -DENABLE_BARRIER_GUARD=0 for an A/B. */
#ifndef ENABLE_BARRIER_GUARD
#define ENABLE_BARRIER_GUARD 1
#endif

/* D3D12_RESOURCE_BARRIER is 32 bytes: Type, Flags, then the union. The
   resource pointer is at +8 for TRANSITION and UAV, and the second one of an
   ALIASING pair is at +16. */
typedef struct { UINT Type, Flags; UINT64 res; UINT64 res2; UINT64 tail; } BarrierRaw;
static volatile LONG g_bar_calls = 0, g_bar_dropped = 0, g_bar_empty = 0;

/* ★★ 2026-09-20, the finding that cost a whole shipping build: a command list
   vtable is NOT unique in this process. With the debug layer on, every list is
   an SDKLayers wrapper and they all share one vtable, so patching the first
   list that came back from ExecuteCommandLists guarded everything -- 58 million
   binds counted, the stale bind caught. With the layer off, D3D12Core hands out
   SEVERAL distinct command list vtables; the room screen records on one we had
   never patched, and the guard counted zero binds while the device was removed
   exactly as before. So every vtable is patched, each with its own originals. */
#define CLVT_N 24
typedef struct {
    void** vt;
    HRESULT (WINAPI* o9)(void*);                    /* Close */
    HRESULT (WINAPI* o10)(void*, void*, void*);     /* Reset */
    void (WINAPI* o26)(void*, UINT, const void*);   /* ResourceBarrier */
    void (WINAPI* o31)(void*, UINT, UINT64);        /* SetComputeRootDescriptorTable */
    void (WINAPI* o32)(void*, UINT, UINT64);        /* SetGraphicsRootDescriptorTable */
} ClVt;
static ClVt          g_clvt[CLVT_N];
static volatile LONG g_clvt_n = 0;
static volatile LONG g_clvt_full = 0;

static ClVt* clvt_find(void* list)
{
    void** vt = *(void***)list;
    LONG n = g_clvt_n, i;
    if (n > CLVT_N) n = CLVT_N;
    for (i = 0; i < n; i++)
        if (g_clvt[i].vt == vt) return &g_clvt[i];
    return NULL;
}

static void WINAPI hk_ResourceBarrier(void* list, UINT num, const void* bars)
{
    BarrierRaw keep[16];
    ClVt* v = clvt_find(list);
    UINT i, k = 0;
    if (!v) return;                    /* unreachable: only patched vtables get here */
    InterlockedIncrement(&g_bar_calls);
    if (!num || !bars) { InterlockedIncrement(&g_bar_empty); return; }
    if (num > 16) { v->o26(list, num, bars); return; }
    for (i = 0; i < num; i++) {
        const BarrierRaw* r = (const BarrierRaw*)((const unsigned char*)bars + (SIZE_T)i * 32);
        int ok = 1;
        if (r->Type == 0 || r->Type == 2) ok = (r->res != 0);                  /* TRANSITION, UAV */
        else if (r->Type == 1)            ok = (r->res != 0 || r->res2 != 0);  /* ALIASING */
        if (ok) keep[k++] = *r;
        else InterlockedIncrement(&g_bar_dropped);
    }
    if (!k) return;
    v->o26(list, k, keep);
}

/* ============ PART 33: THE TABLE THAT IS IN NO HEAP =======================
 *  Measured 2026-09-20, host client, room lobby, the moment the process died:
 *
 *    [ERROR id=646] CGraphicsCommandList::SetGraphicsRootDescriptorTable:
 *    Specified GPU descriptor handle ptr=0x5678a0010ffe0 does not refer to a
 *    location in a descriptor heap.
 *      exe+0xA24C1F exe+0xA25243 exe+0x9E2FF8 exe+0x9E4E49 exe+0xA05324
 *      exe+0x2260A0 exe+0x2259A2 exe+0x8BC325 exe+0x8C7D0F exe+0x5E4A0F exe+0x858053
 *
 *  Same game-side chain as the NULL ResourceBarrier of PART 32 and as the
 *  id=1023 "Static Descriptor ... TEXTURE2D vs TEXTURECUBE" floods before it:
 *  the room screen keeps drawing the member art through a descriptor table
 *  handle whose heap is gone, because the character change released it. The
 *  driver is then handed a pointer into nothing, and that is what takes the
 *  device -- and the machine -- down.
 *
 *  So every descriptor heap is registered when it is created and struck off
 *  when its last reference goes, and a root-table bind whose handle falls in
 *  no live heap is DROPPED. The draw then keeps whatever table was bound
 *  before -- one frame of the wrong portrait -- instead of killing the device.
 *
 *  If more heaps exist than the registry holds, the guard disarms itself
 *  rather than risk dropping a valid bind.
 * ----------------------------------------------------------------------- */
/* ON by default since 2026-09-20: this is the fix for the room-lobby crash,
   measured over 42 character changes on the rig -- 58 198 021 binds, exactly
   one dropped, no device removal, where every earlier run died. Build with
   -DENABLE_BIND_GUARD=0 to get the old behaviour back for an A/B. */
/* ON by default: this is the last link of the chain, the one that is the same
   in every capture, and dropping an unclosed list costs a frame of one
   portrait where passing it costs the device. Build with
   -DENABLE_SUBMIT_GUARD=0 for an A/B. */
#ifndef ENABLE_SUBMIT_GUARD
#define ENABLE_SUBMIT_GUARD 1
#endif

#ifndef ENABLE_BIND_GUARD
#define ENABLE_BIND_GUARD 1
#endif

#define DHEAP_N 96
typedef struct { void* heap; UINT64 gpu0, gpu1; UINT type, num; volatile LONG live; } DHeap;
static DHeap         g_dheap[DHEAP_N];
static volatile LONG g_dheap_overflow = 0;
static volatile LONG g_dheap_made = 0, g_dheap_gone = 0;
static volatile LONG g_bind_calls = 0, g_bind_blocked = 0, g_bind_reports = 0;
static volatile LONG g_bind_substituted = 0, g_bind_nofallback = 0;

static HRESULT (WINAPI* o_CreateDescriptorHeap)(void*, const void*, const GUID*, void**) = NULL;

/* Same trap as the command lists: a descriptor heap vtable is not unique
   either, so a single Release hook misses every heap of another flavour and
   the registry keeps dead heaps alive -- which is exactly how a stale bind
   gets waved through. One entry per heap vtable, each with its own original. */
#define HPVT_N 8
typedef struct { void** vt; ULONG (WINAPI* o2)(void*); } HpVt;
static HpVt          g_hpvt[HPVT_N];
static volatile LONG g_hpvt_n = 0;

/* The last binds, for the moment the device goes anyway: which handle, which
   root slot, and who bound it. */
#define BRING_N 64
typedef struct { UINT64 h, ret; UINT idx; DWORD tid; } BindRec;
static BindRec       g_bring[BRING_N];
static volatile LONG g_bring_n = 0;
static volatile LONG g_bring_dumped = 0;

/* ★ Measured 2026-09-20, the hard way: this D3D12Core returns the handle
   through a HIDDEN BUFFER POINTER, MSVC member-function style -- `this` in
   RCX, the buffer in RDX. Called as a plain 8-byte return it computed the
   handle into RAX and then wrote it to whatever RDX held, which was 0:
   `D3D12Core.dll+0x373C4 writing to 0x0`, on both clients, one tenth of a
   second after the hook went in. So it is called with the buffer, and the
   RAX value is kept as the fallback for a runtime that returns it that way. */
static UINT64 heap_gpu_start(void* heap)
{
    UINT64 out = 0;
    UINT64 rax = ((UINT64 (WINAPI*)(void*, UINT64*))(*(void***)heap)[10])(heap, &out);
    return out ? out : rax;
}

static int gpu_handle_live(UINT64 h)
{
    int i;
    if (g_dheap_overflow) return 1;          /* disarmed: never drop a valid bind */
    for (i = 0; i < DHEAP_N; i++)
        if (g_dheap[i].live && h >= g_dheap[i].gpu0 && h < g_dheap[i].gpu1) return 1;
    return 0;
}

/* ★★ 2026-09-20, measured: DROPPING the stale bind is what blacked the screen.
   A draw whose root table was never set is invalid, the runtime records that
   error in the command list, and the list then refuses to close --
   `Close` answered 0x80004005 E_FAIL forever, so Reset could never succeed and
   nothing was ever drawn again. The bind must therefore be REPLACED, not
   removed: the last handle that was good on that root slot is bound instead.
   The draw stays legal and shows a stale portrait for a frame, which is the
   whole cost. */
#define ROOTSLOT_N 32
static UINT64 g_last_good[ROOTSLOT_N];

static UINT64 bind_substitute(UINT idx)
{
    int i;
    if (idx < ROOTSLOT_N && g_last_good[idx] && gpu_handle_live(g_last_good[idx]))
        return g_last_good[idx];
    for (i = 0; i < DHEAP_N; i++)          /* anything legal beats an illegal bind */
        if (g_dheap[i].live && g_dheap[i].type == 0) return g_dheap[i].gpu0;
    for (i = 0; i < DHEAP_N; i++)
        if (g_dheap[i].live) return g_dheap[i].gpu0;
    return 0;
}
static UINT          g_desc_inc[4] = { 0, 0, 0, 0 };

static void bind_report(const char* which, UINT idx, UINT64 h)
{
    void* fr[32];
    unsigned char* m = (unsigned char*)GetModuleHandleA(NULL);
    char line[512];
    size_t used;
    USHORT n, i;
    int shown = 0;
    unsigned long long lo, hi;
    IMAGE_NT_HEADERS* nt;
    if (!m) return;
    nt = (IMAGE_NT_HEADERS*)(m + ((IMAGE_DOS_HEADER*)m)->e_lfanew);
    lo = (unsigned long long)m;
    hi = lo + nt->OptionalHeader.SizeOfImage;
    log_line("BINDGUARD: *** %s(root %u, handle 0x%I64X) -- that handle is in no live "
             "descriptor heap; it is REPLACED by the last handle that was good on this root "
             "slot, because removing the bind instead poisons the command list", which, idx, h);
    n = RtlCaptureStackBackTrace(0, 32, fr, NULL);
    used = (size_t)wsprintfA(line, "BINDGUARD:   exe frames:");
    for (i = 0; i < n && shown < 14; i++) {
        unsigned long long a = (unsigned long long)fr[i];
        if (a < lo || a >= hi) continue;
        used += (size_t)wsprintfA(line + used, " exe+0x%I64X", a - lo);
        shown++;
        if (used > sizeof(line) - 32) break;
    }
    if (shown) log_line("%s", line);
    desc_who_copied(h);            /* in case the handle is a CPU one after all */
}

static void bind_record(UINT idx, UINT64 h, UINT64 ret)
{
    LONG i = InterlockedIncrement(&g_bring_n) - 1;
    BindRec* r = &g_bring[i & (BRING_N - 1)];
    r->h   = h;
    r->ret = ret;
    r->idx = idx;
    r->tid = GetCurrentThreadId();
}

/* Called when a submit finds the device already removed: the binds that were
   live at that moment are the only evidence left once the debug layer is off. */
static void bind_ring_dump(const char* why)
{
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    UINT64 lo = (UINT64)(SIZE_T)mod, hi = lo;
    LONG n, i, shown;
    if (!ENABLE_BIND_GUARD) return;
    if (InterlockedCompareExchange(&g_bring_dumped, 1, 0) != 0) return;
    if (mod) {
        IMAGE_NT_HEADERS* nt = (IMAGE_NT_HEADERS*)(mod + ((IMAGE_DOS_HEADER*)mod)->e_lfanew);
        hi = lo + nt->OptionalHeader.SizeOfImage;
    }
    n = g_bring_n;
    shown = n > 24 ? 24 : n;
    log_line("BINDRING: the last %ld of %ld root-table binds before %s, newest first; the "
             "registry held %ld heaps made and %ld released over %ld heap vtable(s)",
             shown, n, why, g_dheap_made, g_dheap_gone, g_hpvt_n);
    for (i = 0; i < shown; i++) {
        BindRec* r = &g_bring[(n - 1 - i) & (BRING_N - 1)];
        int live = gpu_handle_live(r->h);
        if (r->ret >= lo && r->ret < hi)
            log_line("BINDRING:   #%ld root %u handle 0x%I64X (%s) thread %lu  caller exe+0x%I64X",
                     n - 1 - i, r->idx, r->h, live ? "in a live heap" : "STALE", r->tid, r->ret - lo);
        else
            log_line("BINDRING:   #%ld root %u handle 0x%I64X (%s) thread %lu  caller 0x%I64X",
                     n - 1 - i, r->idx, r->h, live ? "in a live heap" : "STALE", r->tid, r->ret);
    }
    for (i = 0; i < DHEAP_N; i++)
        if (g_dheap[i].live)
            log_line("BINDRING:   live heap type %u, %u descriptors, GPU 0x%I64X..0x%I64X",
                     g_dheap[i].type, g_dheap[i].num, g_dheap[i].gpu0, g_dheap[i].gpu1);
}

static void WINAPI hk_SetGraphicsRootDescriptorTable(void* list, UINT idx, UINT64 h)
{
    ClVt* v = clvt_find(list);
    if (!v) return;
    bind_record(idx, h, DESC_RET_ADDR());
    InterlockedIncrement(&g_bind_calls);
    if (!gpu_handle_live(h)) {
        UINT64 sub = bind_substitute(idx);
        InterlockedIncrement(&g_bind_blocked);
        if (InterlockedIncrement(&g_bind_reports) <= 6)
            bind_report("SetGraphicsRootDescriptorTable", idx, h);
        if (!sub) { InterlockedIncrement(&g_bind_nofallback); return; }
        InterlockedIncrement(&g_bind_substituted);
        v->o32(list, idx, sub);
        return;
    }
    if (idx < ROOTSLOT_N) g_last_good[idx] = h;
    v->o32(list, idx, h);
}

static void WINAPI hk_SetComputeRootDescriptorTable(void* list, UINT idx, UINT64 h)
{
    ClVt* v = clvt_find(list);
    if (!v) return;
    InterlockedIncrement(&g_bind_calls);
    if (!gpu_handle_live(h)) {
        UINT64 sub = bind_substitute(idx);
        InterlockedIncrement(&g_bind_blocked);
        if (InterlockedIncrement(&g_bind_reports) <= 6)
            bind_report("SetComputeRootDescriptorTable", idx, h);
        if (!sub) { InterlockedIncrement(&g_bind_nofallback); return; }
        InterlockedIncrement(&g_bind_substituted);
        v->o31(list, idx, sub);
        return;
    }
    v->o31(list, idx, h);
}

/* The last Release of a heap is what makes every handle into it stale, so it
   is the event the registry exists to see. */
static ULONG WINAPI hk_HeapRelease(void* heap)
{
    void** vt = *(void***)heap;
    ULONG (WINAPI* orig)(void*) = NULL;
    ULONG left;
    LONG n = g_hpvt_n, i;
    if (n > HPVT_N) n = HPVT_N;
    for (i = 0; i < n; i++)
        if (g_hpvt[i].vt == vt) { orig = g_hpvt[i].o2; break; }
    if (!orig) return 1;                  /* unreachable: only patched vtables get here */
    left = orig(heap);
    if (!left) {
        int i;
        for (i = 0; i < DHEAP_N; i++)
            if (g_dheap[i].live && g_dheap[i].heap == heap) {
                g_dheap[i].live = 0;
                g_dheap[i].heap = NULL;
                InterlockedIncrement(&g_dheap_gone);
                break;
            }
    }
    return left;
}

static void heap_hook_release(void* heap)
{
    void** vt = *(void***)heap;
    LONG n = g_hpvt_n, i, slot;
    DWORD old;
    if (n > HPVT_N) n = HPVT_N;
    for (i = 0; i < n; i++) if (g_hpvt[i].vt == vt) return;      /* known flavour */
    slot = InterlockedIncrement(&g_hpvt_n) - 1;
    if (slot >= HPVT_N) {
        g_hpvt_n = HPVT_N;
        g_dheap_overflow = 1;
        log_line("BINDGUARD: more than %d descriptor heap vtables -- the guard disarms itself, "
                 "because a registry that cannot see a heap die would pass the very bind it "
                 "exists to stop", HPVT_N);
        return;
    }
    g_hpvt[slot].o2 = (ULONG (WINAPI*)(void*))vt[2];
    if (!VirtualProtect(&vt[2], sizeof(void*), PAGE_READWRITE, &old)) {
        g_dheap_overflow = 1;
        log_line("BINDGUARD: a descriptor heap vtable cannot be unprotected -- the guard is "
                 "disarmed, because a registry that never forgets a dead heap would pass the "
                 "very bind it exists to stop");
        return;
    }
    vt[2] = (void*)&hk_HeapRelease;
    VirtualProtect(&vt[2], sizeof(void*), old, &old);
    g_hpvt[slot].vt = vt;                  /* written last, so a reader sees it complete */
    log_line("BINDGUARD: descriptor heap vtable %p patched (#%ld) -- its heaps are now struck "
             "off the registry when their last reference goes", (void*)vt, slot + 1);
}

static HRESULT WINAPI hk_CreateDescriptorHeap(void* dev, const void* desc,
                                              const GUID* riid, void** ppv)
{
    HRESULT hr = o_CreateDescriptorHeap(dev, desc, riid, ppv);
    if (hr >= 0 && ppv && *ppv && desc) {
        UINT type = *(const UINT*)desc;
        UINT num  = *(const UINT*)((const unsigned char*)desc + 4);
        UINT flags = *(const UINT*)((const unsigned char*)desc + 8);
        int i, placed = 0;
        heap_hook_release(*ppv);
        if (flags & 1) {                     /* SHADER_VISIBLE: only those have GPU handles */
            UINT64 g0 = heap_gpu_start(*ppv);
            UINT   inc = (type < 4 && g_desc_inc[type]) ? g_desc_inc[type] : 32;
            for (i = 0; i < DHEAP_N; i++) {
                if (InterlockedCompareExchange(&g_dheap[i].live, 1, 0) != 0) continue;
                g_dheap[i].heap = *ppv;
                g_dheap[i].gpu0 = g0;
                g_dheap[i].gpu1 = g0 + (UINT64)num * inc;
                g_dheap[i].type = type;
                g_dheap[i].num  = num;
                placed = 1;
                InterlockedIncrement(&g_dheap_made);
                break;
            }
            if (!placed && !g_dheap_overflow) {
                g_dheap_overflow = 1;
                log_line("BINDGUARD: more than %d live shader-visible descriptor heaps -- the "
                         "guard disarms itself rather than drop a bind that is in fact valid",
                         DHEAP_N);
            }
        }
    }
    return hr;
}

/* ============ PART 34: THE LIST THAT WAS NEVER CLOSED ====================
 *  Every capture of this crash ends the same way, whatever went wrong first:
 *
 *      THROW          _com_error 0x80070057 out of the middle of a recording
 *      [ERROR id=838] ExecuteCommandLists: Command lists must be successfully
 *                     closed before execution
 *      [ERROR id=232] RemoveDevice -- DXGI_ERROR_INVALID_CALL
 *
 *  The upstream failure varies -- a barrier on a released resource, a table
 *  bound from a heap the lobby has just dropped -- and guarding each one in
 *  turn has now failed twice, because the debug layer's view of a descriptor
 *  heap is not the runtime's. The step that actually removes the device does
 *  not vary: a command list is submitted that was never successfully closed,
 *  because a C++ exception unwound out of its recording.
 *
 *  So that is what is guarded here. Close and Reset are tracked per list, and
 *  ExecuteCommandLists submits only the lists that are closed. A list that is
 *  still recording is dropped from the call -- the frame loses whatever that
 *  list drew, which is the portrait the game was in the middle of swapping,
 *  and the device survives. A list we have never seen is passed through: not
 *  knowing is not a reason to drop somebody's rendering.
 * ----------------------------------------------------------------------- */
#define CLST_N 128
typedef struct { void* list; volatile LONG closed; } ClState;
static ClState       g_clst[CLST_N];
static volatile LONG g_clst_n = 0;
static volatile LONG g_clst_full = 0;
static volatile LONG g_submit_dropped = 0, g_submit_emptied = 0, g_submit_reports = 0;
static volatile LONG g_submit_closed = 0, g_submit_closefail = 0;

static ClState* clst_find(void* list)
{
    LONG n = g_clst_n, i;
    if (n > CLST_N) n = CLST_N;
    for (i = 0; i < n; i++) if (g_clst[i].list == list) return &g_clst[i];
    return NULL;
}

/* Called from Close, from Reset and from the creation hook, so a list is known
   from its first breath. */
static void clst_set(void* list, LONG closed)
{
    ClState* e = clst_find(list);
    LONG slot;
    if (e) { e->closed = closed; return; }
    slot = InterlockedIncrement(&g_clst_n) - 1;
    if (slot >= CLST_N) {
        g_clst_n = CLST_N;
        if (InterlockedCompareExchange(&g_clst_full, 1, 0) == 0)
            log_line("SUBMITGUARD: more than %d command lists -- the ones past that are passed "
                     "through unchecked", CLST_N);
        return;
    }
    g_clst[slot].closed = closed;
    g_clst[slot].list   = list;        /* written last: a reader sees a finished entry */
}

static HRESULT WINAPI hk_Close(void* list)
{
    ClVt* v = clvt_find(list);
    HRESULT hr;
    if (!v) return 0;
    hr = v->o9(list);
    clst_set(list, hr >= 0 ? 1 : 0);   /* a Close that FAILED leaves it unclosed */
    return hr;
}

static volatile LONG g_reset_calls = 0, g_reset_failed = 0, g_reset_reports = 0;

static HRESULT WINAPI hk_Reset(void* list, void* alloc, void* pso)
{
    ClVt* v = clvt_find(list);
    HRESULT hr;
    if (!v) return 0;
    InterlockedIncrement(&g_reset_calls);
    hr = v->o10(list, alloc, pso);
    if (hr >= 0) clst_set(list, 0);    /* recording again */
    else {
        InterlockedIncrement(&g_reset_failed);
        if (InterlockedIncrement(&g_reset_reports) <= 4)
            log_line("SUBMITGUARD: Reset of command list %p FAILED (hr 0x%08lX) -- the list "
                     "cannot start a new frame, which is what a black screen looks like from "
                     "here", list, (unsigned long)hr);
    }
    return hr;
}

/* Slot 26 is ResourceBarrier, 31 SetComputeRootDescriptorTable, 32
   SetGraphicsRootDescriptorTable. Every command list this process shows us has
   its vtable patched, once each -- see the note on CLVT_N for why one was not
   enough. */
static void clvt_hook(void* list)
{
    void** vt;
    ClVt* e;
    LONG slot;
    DWORD old;
    if (!list || clvt_find(list)) return;
    vt = *(void***)list;
    slot = InterlockedIncrement(&g_clvt_n) - 1;
    if (slot >= CLVT_N) {
        g_clvt_n = CLVT_N;
        if (InterlockedCompareExchange(&g_clvt_full, 1, 0) == 0)
            log_line("BINDGUARD: more than %d command list vtables in this process -- lists "
                     "beyond that are NOT guarded; raise CLVT_N", CLVT_N);
        return;
    }
    e = &g_clvt[slot];
    e->o9  = (HRESULT (WINAPI*)(void*))vt[9];
    e->o10 = (HRESULT (WINAPI*)(void*, void*, void*))vt[10];
    e->o26 = (void (WINAPI*)(void*, UINT, const void*))vt[26];
    e->o31 = (void (WINAPI*)(void*, UINT, UINT64))vt[31];
    e->o32 = (void (WINAPI*)(void*, UINT, UINT64))vt[32];
    if (!VirtualProtect(&vt[9], sizeof(void*) * 24, PAGE_READWRITE, &old)) {
        log_line("BINDGUARD: a command list vtable could not be unprotected -- lists of that "
                 "kind are NOT guarded");
        return;
    }
    if (ENABLE_SUBMIT_GUARD) {
        vt[9]  = (void*)&hk_Close;
        vt[10] = (void*)&hk_Reset;
    }
    if (ENABLE_BARRIER_GUARD) vt[26] = (void*)&hk_ResourceBarrier;
    if (ENABLE_BIND_GUARD) {
        vt[31] = (void*)&hk_SetComputeRootDescriptorTable;
        vt[32] = (void*)&hk_SetGraphicsRootDescriptorTable;
    }
    VirtualProtect(&vt[9], sizeof(void*) * 24, old, &old);
    e->vt = vt;                  /* written last: a reader only sees a finished entry */
    log_line("BINDGUARD: command list vtable %p patched (#%ld) -- a table handle that is in no "
             "live heap is dropped instead of being handed to the driver", (void*)vt, slot + 1);
}

static void WINAPI hk_ExecuteCommandLists(void* queue, UINT n, void* const* lists)
{
    InterlockedIncrement(&g_exec_calls);
    if ((ENABLE_BIND_GUARD || ENABLE_BARRIER_GUARD || ENABLE_SUBMIT_GUARD) && lists) {
        UINT li;
        for (li = 0; li < n; li++) clvt_hook(lists[li]);
    }
    if (ENABLE_SUBMIT_GUARD && lists && n && n <= 32) {
        void* keep[32];
        UINT li, k = 0;
        for (li = 0; li < n; li++) {
            ClState* st = clst_find(lists[li]);
            if (st && !st->closed) {
                /* ★★ 2026-09-20, measured: refusing the submit alone leaves a BLACK
                   SCREEN. A command list that was never closed cannot be Reset, so
                   the game's next frame fails to start recording, records nothing,
                   and submits the same open list again -- 846 times in 20 seconds,
                   every one of them refused, nothing ever drawn. The loop is
                   circular and one call breaks it: close the list ourselves. The
                   frame it held is still dropped, because what it contains is what
                   the exception abandoned halfway, but Reset succeeds next frame
                   and the game draws again. */
                ClVt* v = clvt_find(lists[li]);
                HRESULT chr = v ? v->o9(lists[li]) : (HRESULT)-1;
                if (chr >= 0) { st->closed = 1; InterlockedIncrement(&g_submit_closed); }
                else InterlockedIncrement(&g_submit_closefail);
                InterlockedIncrement(&g_submit_dropped);
                if (InterlockedIncrement(&g_submit_reports) <= 6) {
                    log_line("SUBMITGUARD: *** command list %p reached submit #%ld still "
                             "recording -- dropped from the submit, and CLOSED here (hr "
                             "0x%08lX) so the game's next Reset can succeed and the screen "
                             "comes back", lists[li], g_exec_calls, (unsigned long)chr);
                    bind_ring_dump("the unclosed submit");
                }
                continue;
            }
            keep[k++] = lists[li];
        }
        if (k != n) {
            if (!k) { InterlockedIncrement(&g_submit_emptied); return; }
            o_ExecuteCommandLists(queue, k, keep);
        } else {
            o_ExecuteCommandLists(queue, n, lists);
        }
    } else {
        o_ExecuteCommandLists(queue, n, lists);
    }
    if (!g_exec_noticed && g_d3d12_device) {
        void*** dev = (void***)g_d3d12_device;
        HRESULT reason = ((HRESULT (WINAPI*)(void*))(*dev)[37])(dev);
        if (reason < 0 && InterlockedCompareExchange(&g_exec_noticed, 1, 0) == 0) {
            log_line("DESCRING: the device is GONE at ExecuteCommandLists -- reason 0x%08lX, "
                     "submit #%ld", (unsigned long)reason, g_exec_calls);
            bind_ring_dump("the device removal");
            desc_ring_dump("the device removal");
            d3d12_debug_drain("the device removal seen at ExecuteCommandLists");
        }
    }
}

static HRESULT (WINAPI* o_CreateCommandList)(void*, UINT, UINT, void*, void*,
                                             const GUID*, void**) = NULL;

static HRESULT WINAPI hk_CreateCommandList(void* dev, UINT node, UINT type, void* alloc,
                                           void* pso, const GUID* riid, void** ppv)
{
    HRESULT hr = o_CreateCommandList(dev, node, type, alloc, pso, riid, ppv);
    if (hr >= 0 && ppv && *ppv) {
        clvt_hook(*ppv);
        if (ENABLE_SUBMIT_GUARD) clst_set(*ppv, 0);   /* created open, still recording */
    }
    return hr;
}

static HRESULT WINAPI hk_CreateCommandQueue(void* dev, const void* desc, const GUID* riid, void** ppv)
{
    HRESULT hr = o_CreateCommandQueue(dev, desc, riid, ppv);
    if (hr >= 0 && ppv && *ppv && !o_ExecuteCommandLists) {
        void*** q = (void***)*ppv;
        DWORD old;
        if (VirtualProtect(&(*q)[10], sizeof(void*), PAGE_READWRITE, &old)) {
            o_ExecuteCommandLists = (void (WINAPI*)(void*, UINT, void* const*))(*q)[10];
            (*q)[10] = (void*)&hk_ExecuteCommandLists;
            VirtualProtect(&(*q)[10], sizeof(void*), old, &old);
            log_line("DESCRING: ExecuteCommandLists hooked (queue vtable slot 10) -- the first "
                     "submit made after the device is removed writes the ring to this log");
        }
    }
    return hr;
}

/* ★ 2026-09-20, caught before the commit: the queue hook used to live behind
   the ring's own early return, so a build with the guard but no ring installed
   NOTHING -- CreateCommandQueue was never hooked, so ExecuteCommandLists was
   never hooked, so the command list vtable was never reached and the bind was
   never guarded. The shipping build ran a full session with the fix silently
   absent. The three jobs are now independent: the ring hooks the copier, the
   queue hook is installed for either job, and the heap registry is its own. */
static void desc_hook_device(void* device)
{
    void*** dev = (void***)device;
    DWORD old;
    static LONG once = 0;
    if (!device || InterlockedCompareExchange(&once, 1, 0) != 0) return;
    if (ENABLE_DESC_RING) {
        o_CopyDescriptorsSimple = (void (WINAPI*)(void*, UINT, SIZE_T, SIZE_T, UINT))(*dev)[24];
        if (VirtualProtect(&(*dev)[24], sizeof(void*), PAGE_READWRITE, &old)) {
            (*dev)[24] = (void*)&hk_CopyDescriptorsSimple;
            VirtualProtect(&(*dev)[24], sizeof(void*), old, &old);
            log_line("DESCRING: CopyDescriptorsSimple hooked (device vtable slot 24) -- a "
                     "128-entry ring now records which descriptor each caller copies over, "
                     "and from where in the exe");
        } else {
            o_CopyDescriptorsSimple = NULL;
            log_line("DESCRING: could not unprotect the device vtable -- ring off");
        }
    }
    /* The queue is the only way to reach a command list vtable, so it is hooked
       for the ring's removal check AND for the two guards that live on the list. */
    if (ENABLE_BIND_GUARD || ENABLE_BARRIER_GUARD) {
        o_CreateCommandList = (HRESULT (WINAPI*)(void*, UINT, UINT, void*, void*,
                                                 const GUID*, void**))(*dev)[12];
        if (VirtualProtect(&(*dev)[12], sizeof(void*), PAGE_READWRITE, &old)) {
            (*dev)[12] = (void*)&hk_CreateCommandList;
            VirtualProtect(&(*dev)[12], sizeof(void*), old, &old);
        } else {
            o_CreateCommandList = NULL;
            log_line("BINDGUARD: CreateCommandList could not be hooked -- a list is only "
                     "guarded from its first submit on");
        }
    }
    o_CreateCommandQueue = (HRESULT (WINAPI*)(void*, const void*, const GUID*, void**))(*dev)[8];
    if (VirtualProtect(&(*dev)[8], sizeof(void*), PAGE_READWRITE, &old)) {
        (*dev)[8] = (void*)&hk_CreateCommandQueue;
        VirtualProtect(&(*dev)[8], sizeof(void*), old, &old);
    } else {
        o_CreateCommandQueue = NULL;
        log_line("BINDGUARD: CreateCommandQueue could not be hooked -- nothing downstream of "
                 "it is installed, so the stale-bind guard is NOT active in this process");
    }
    if (ENABLE_BIND_GUARD) {
        UINT t;
        for (t = 0; t < 4; t++)
            g_desc_inc[t] = ((UINT (WINAPI*)(void*, UINT))(*dev)[15])(device, t);
        o_CreateDescriptorHeap = (HRESULT (WINAPI*)(void*, const void*, const GUID*, void**))(*dev)[14];
        if (VirtualProtect(&(*dev)[14], sizeof(void*), PAGE_READWRITE, &old)) {
            (*dev)[14] = (void*)&hk_CreateDescriptorHeap;
            VirtualProtect(&(*dev)[14], sizeof(void*), old, &old);
            log_line("BINDGUARD: CreateDescriptorHeap hooked (device vtable slot 14) -- every "
                     "shader-visible heap is registered; increments %u/%u/%u/%u",
                     g_desc_inc[0], g_desc_inc[1], g_desc_inc[2], g_desc_inc[3]);
        } else {
            o_CreateDescriptorHeap = NULL;
            g_dheap_overflow = 1;
            log_line("BINDGUARD: the device vtable cannot be unprotected -- guard disarmed");
        }
    }
}

static HRESULT WINAPI hk_D3D12CreateDevice(void* adapter, int minLevel,
                                           const GUID* riid, void** ppDevice)
{
    HRESULT hr;
    static LONG once = 0;
    if (InterlockedCompareExchange(&once, 1, 0) == 0) {
        if (!(file_exists("patch_d3d12_debug.txt") && d3d12_agility_factory())) {
            d3d12_debug_enable();      /* must precede device creation */
            dred_enable_before_device();
        }
        if (ENABLE_RS_VOLATILE) rs_hook_serializer();
        else log_line("RSVOLATILE: DISABLED at build time -- root signatures keep their "
                      "STATIC descriptor ranges, so the room-lobby descriptor overwrite "
                      "still removes the device (build with -DENABLE_RS_VOLATILE=1)");
    }
    if (g_d3d12_factory) {
        hr = ((HRESULT (WINAPI*)(void*, void*, int, const GUID*, void**))
              (*(void***)g_d3d12_factory)[9])(g_d3d12_factory, adapter, minLevel, riid, ppDevice);
        if (hr < 0) {
            log_line("D3D12DEBUG/agility: factory CreateDevice failed (hr 0x%08lX, level 0x%X) "
                     "-- falling back to the system runtime for this call",
                     (unsigned long)hr, minLevel);
            hr = o_D3D12CreateDevice(adapter, minLevel, riid, ppDevice);
        }
    } else {
        hr = o_D3D12CreateDevice(adapter, minLevel, riid, ppDevice);
    }
    if (hr >= 0 && ppDevice && *ppDevice && !g_d3d12_device) {
        g_d3d12_device = *ppDevice;
        log_line("DRED: captured ID3D12Device %p -- removal reason will be reported", *ppDevice);
        d3d12_debug_attach(*ppDevice);
        if (ENABLE_RS_VOLATILE) rs_hook_device(*ppDevice);
        if (ENABLE_DESC_RING || ENABLE_BIND_GUARD || ENABLE_BARRIER_GUARD)
            desc_hook_device(*ppDevice);
    }
    return hr;
}

static void patch_dred_hook(void)
{
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    void** slot;
    HMODULE d3d12;
    MEMORY_BASIC_INFORMATION mbi;
    DWORD old;
    if (!mod) return;
    slot = (void**)(mod + DRED_IAT_RVA);
    d3d12 = GetModuleHandleA("d3d12.dll");
    if (!d3d12) { log_line("DRED: d3d12.dll not loaded -- IAT hook skipped"); return; }
    if (!VirtualQuery(*slot, &mbi, sizeof(mbi)) || mbi.AllocationBase != (void*)d3d12) {
        log_line("DRED: IAT slot at RVA 0x%X does not point into d3d12.dll -- skipped",
                 DRED_IAT_RVA);
        return;
    }
    o_D3D12CreateDevice = (D3D12CreateDevice_t)*slot;
    if (!VirtualProtect(slot, sizeof(void*), PAGE_READWRITE, &old)) {
        log_line("DRED: VirtualProtect failed on the IAT slot -- skipped"); return;
    }
    *slot = (void*)&hk_D3D12CreateDevice;
    VirtualProtect(slot, sizeof(void*), old, &old);
    log_line("DRED: hooked D3D12CreateDevice (imported by ordinal 101) at RVA 0x%X",
             DRED_IAT_RVA);
}

/* Called from the 30s heartbeat. Reports once, and only after the device has
   actually been removed -- GetDeviceRemovedReason is S_OK until then. */
static void dred_report_if_removed(void)
{
    void*** dev = (void***)g_d3d12_device;
    HRESULT reason;
    void* dred = NULL;
    DredPageFault pf;
    DredBreadcrumbs bc;
    const DredAllocNode* n;
    int i;

    if (!dev || g_dred_reported) return;
    reason = ((HRESULT (WINAPI*)(void*))(*dev)[37])(dev);   /* GetDeviceRemovedReason */
    if (reason >= 0) return;
    if (InterlockedCompareExchange(&g_dred_reported, 1, 0) != 0) return;

    log_line("DRED: *** DEVICE REMOVED *** GetDeviceRemovedReason = 0x%08lX (%s)",
             (unsigned long)reason,
             reason == (HRESULT)0x887A0006 ? "DEVICE_HUNG" :
             reason == (HRESULT)0x887A0005 ? "DEVICE_REMOVED" :
             reason == (HRESULT)0x887A0007 ? "DEVICE_RESET" :
             reason == (HRESULT)0x887A0020 ? "DRIVER_INTERNAL_ERROR" :
             reason == (HRESULT)0x887A0001 ? "INVALID_CALL" : "other");

    if (((HRESULT (WINAPI*)(void*, const GUID*, void**))(*dev)[0])(dev, &IID_DRED, &dred) < 0
        || !dred) {
        log_line("DRED: no ID3D12DeviceRemovedExtendedData on this device");
        d3d12_debug_drain("device removal");
        return;
    }
    memset(&pf, 0, sizeof(pf));
    memset(&bc, 0, sizeof(bc));
    if (((HRESULT (WINAPI*)(void*, void*))(*(void***)dred)[4])(dred, &pf) >= 0) {
        log_line("DRED: page fault at GPU VA 0x%llX", (unsigned long long)pf.pageFaultVA);
        for (n = pf.recentlyFreed, i = 0; n && i < 6; n = n->next, i++)
            log_line("DRED:   recently FREED allocation: %s (type %u)  <-- use-after-free "
                     "candidate", n->nameA ? n->nameA : "(unnamed)", n->type);
        for (n = pf.existing, i = 0; n && i < 6; n = n->next, i++)
            log_line("DRED:   existing allocation: %s (type %u)",
                     n->nameA ? n->nameA : "(unnamed)", n->type);
    }
    if (((HRESULT (WINAPI*)(void*, void*))(*(void***)dred)[3])(dred, &bc) >= 0) {
        const DredBreadcrumbNode* b = bc.head;
        for (i = 0; b && i < 4; b = b->next, i++)
            log_line("DRED:   breadcrumb queue='%s' list='%s' ops=%u last=%u",
                     b->cmdQueueNameA ? b->cmdQueueNameA : "(unnamed)",
                     b->cmdListNameA ? b->cmdListNameA : "(unnamed)",
                     b->count, b->lastValue ? *b->lastValue : 0u);
    }
    ((ULONG (WINAPI*)(void*))(*(void***)dred)[2])(dred);    /* Release */
    d3d12_debug_drain("device removal");   /* the stored messages, whichever path found it */
    if (ENABLE_DESC_RING) desc_ring_dump("the device removal (heartbeat)");
}

/* ---- the report has to be written BEFORE the process dies ----------------
 *  The 30 s heartbeat was the wrong place to ask about a removed device: the
 *  game does not freeze on this bug, it CRASHES, so nothing gets to run 30
 *  seconds later. A vectored exception handler runs in the faulting thread at
 *  the moment of the fault, ahead of the crash path, which is the only place
 *  that is guaranteed to happen.
 *
 *  On an access violation it writes one line naming the faulting RVA (so a
 *  repro no longer needs the dump to be read at all) and then asks D3D12 for
 *  the removal reason and the DRED page-fault output. Then it returns
 *  CONTINUE_SEARCH so the normal crash handling -- and the Windows dump --
 *  still happen exactly as before.
 *
 *  It reports at most a handful of times: an access violation the game handles
 *  itself would otherwise burn the one report we care about.
 */
/* ---- C++ throws ------------------------------------------------------
   Measured 2026-08-27 on nine WER dumps of "crash on leaving training / ending
   a match": eight of them are `0xC0000409` at exe+0x10CA21D, with an identical
   stack every time. That address is `mov ecx,7 ; int 29h` --
   __fastfail(FAST_FAIL_FATAL_APP_EXIT), which is what the CRT's abort() raises.
   So the process is not corrupting memory, it is calling std::terminate: a C++
   exception nobody caught.

   `int 29h` goes straight to the kernel and never reaches a vectored handler,
   which is exactly why the loader's crash handler had logged nothing for any of
   those crashes. The *throw* that leads to it is an ordinary SEH exception and
   does reach one, so that is where to look.

   Layout of an MSVC x64 throw (code 0xE06D7363):

       ExceptionInformation[0]  magic 0x19930520..22
       ExceptionInformation[1]  the thrown object
       ExceptionInformation[2]  ThrowInfo*      (0 on a rethrow)
       ExceptionInformation[3]  module base -- ThrowInfo uses 32-bit RVAs

       ThrowInfo     +0x0C -> CatchableTypeArray RVA
       CatchableTypeArray  { int count; int types[] }   RVAs
       CatchableType       +0x04 -> TypeDescriptor RVA
       TypeDescriptor      +0x10 -> the mangled name, ".?AV<class>@@"

   Reported once per distinct throw site, so an engine that throws in normal play
   does not bury the one that appears at teardown. */
#define CXX_THROW_CODE 0xE06D7363u

static const char* cxx_thrown_type(EXCEPTION_RECORD* er)
{
    __try {
        unsigned char* base;
        unsigned char* ti;
        int cta_rva, n, ct_rva, td_rva;
        if (er->NumberParameters < 4) return NULL;
        ti   = (unsigned char*)er->ExceptionInformation[2];   /* 0 on a rethrow */
        base = (unsigned char*)er->ExceptionInformation[3];
        if (!ti || !base) return NULL;
        cta_rva = *(int*)(ti + 12);
        if (!cta_rva) return NULL;
        n = *(int*)(base + cta_rva);
        if (n < 1 || n > 64) return NULL;
        ct_rva = *(int*)(base + cta_rva + 4);
        if (!ct_rva) return NULL;
        td_rva = *(int*)(base + ct_rva + 4);
        if (!td_rva) return NULL;
        return (const char*)(base + td_rva + 16);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return NULL;
    }
}

static volatile LONG g_comthrow_frames = 0;
static void cxx_throw_report(EXCEPTION_POINTERS* ep)
{
    /* EVERY throw, not one per site.

       The first version logged one line per distinct throw site, so an engine
       that throws in normal play could not bury the interesting one. That was
       the wrong trade: the crash of 2026-08-27 01:52 logged no throw at all,
       because the only site seen that session was `_com_error` at
       exe+0x1406187A -- and a `_com_error` is what a failed COM/D3D call throws.
       If the fatal one is the *n*th throw from a site that also throws
       harmlessly, deduplicating by site hides exactly the event we are after.
       Timestamps are what tie a throw to the crash, so every one gets a line. */
    static volatile LONG n_logged = 0;
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* addr = (unsigned char*)ep->ExceptionRecord->ExceptionAddress;
    /* Name the module the address is actually in. Subtracting the exe base
       unconditionally printed "exe+0x25AA187A" for a 28 MB image -- RaiseException
       lives in KERNELBASE, so a C++ throw never reports an exe address at all,
       and the earlier lines in this log claim a module they are not in. */
    char modname[64] = "?";
    HMODULE owner = NULL;
    unsigned long long off = 0;
    const char* name;
    unsigned int w0 = 0, w1 = 0, w2 = 0;

    if (InterlockedIncrement(&n_logged) > 400) return;

    if (GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS
                           | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                           (LPCSTR)addr, &owner) && owner) {
        char full[MAX_PATH];
        DWORD n = GetModuleFileNameA(owner, full, MAX_PATH);
        while (n > 0 && full[n - 1] != '\\' && full[n - 1] != '/') n--;
        snprintf(modname, sizeof modname, "%s", full + n);
        off = (unsigned long long)(addr - (unsigned char*)owner);
    } else {
        off = (unsigned long long)addr;
    }

    name = cxx_thrown_type(ep->ExceptionRecord);
    /* the thrown object's head -- a _com_error carries its HRESULT in there,
       which is the difference between "device removed" and anything else */
    __try {
        unsigned int* o = (unsigned int*)ep->ExceptionRecord->ExceptionInformation[1];
        if (o) { w0 = o[0]; w1 = o[1]; w2 = o[2]; }
    } __except (EXCEPTION_EXECUTE_HANDLER) { }

    log_line("THROW: %s+0x%llX -- %s  obj=%08X %08X %08X (thread %lu, slots=0x%X)",
             modname, off, name ? name : "<type not readable, or a rethrow>",
             w0, w1, w2, GetCurrentThreadId(), (unsigned)g_sq_slotmask);

    /* ★ 2026-09-20: a _com_error IS a failed D3D12 call most of the time, and the
       debug layer has already written down why. The game throws it and dies
       unhandled -- no access violation, so the crash handler's own drain never
       runs. Drain here instead: this is the only place that sees the failure at
       the moment it happens. */
    if (name && strstr(name, "_com_error")) d3d12_debug_drain("a _com_error throw");
    /* 2026-09-20: the throw itself is the first domino -- the game's
       ThrowIfFailed unwinds out of the middle of a command list, the list is
       never closed, and the unclosed submit is what removes the device. The
       throw RVA is shared by every throw in the exe, so the STACK is the only
       thing that names the D3D12 call that failed. */
    if (name && strstr(name, "_com_error") && InterlockedIncrement(&g_comthrow_frames) <= 3) {
        void* fr[32];
        unsigned char* m2 = (unsigned char*)GetModuleHandleA(NULL);
        if (m2) {
            IMAGE_NT_HEADERS* n2 = (IMAGE_NT_HEADERS*)(m2 + ((IMAGE_DOS_HEADER*)m2)->e_lfanew);
            unsigned long long flo = (unsigned long long)m2;
            unsigned long long fhi = flo + n2->OptionalHeader.SizeOfImage;
            char fl[512];
            size_t fu;
            USHORT nf, fi;
            int fs = 0;
            nf = RtlCaptureStackBackTrace(0, 32, fr, NULL);
            fu = (size_t)wsprintfA(fl, "THROW:   exe frames:");
            for (fi = 0; fi < nf && fs < 14; fi++) {
                unsigned long long a2 = (unsigned long long)fr[fi];
                if (a2 < flo || a2 >= fhi) continue;
                fu += (size_t)wsprintfA(fl + fu, " exe+0x%I64X", a2 - flo);
                fs++;
                if (fu > sizeof(fl) - 32) break;
            }
            if (fs) log_line("%s", fl);
        }
    }
    if (ENABLE_DESC_RING && name && strstr(name, "_com_error"))
        desc_ring_dump("a _com_error throw");

    /* A bad_alloc is the one that ends the process, so it gets the expensive
       treatment. Two questions to separate, and the answer is different work:

         is the machine actually out of memory?   -> GlobalMemoryStatusEx
         or is one allocation asking for nonsense? -> the call path

       The throw RVA above cannot answer the second: ExceptionAddress for a C++
       throw is the RaiseException inside _CxxThrowException, shared by every
       throw in the module, which is why a _com_error and a bad_alloc report the
       same address. The stack is what differs, so scan it -- the VEH runs on the
       faulting thread, so ContextRecord->Rsp is the throwing frame. Same crude
       scan as BalanceLeadTools/disasm/dmp.py: no unwind data, so some entries
       are stale, but the live ones are in there. */
    /* CORRECTION to commit 700794e, which claimed "the process leaks about
       700 MB a minute". That was two samples of 20 s and 45 s taken during
       unknown activity, and it does not survive the fuller trace: private bytes
       OSCILLATE (7,582 -> 7,153 -> 7,700 MB) and the steep climb lines up with
       a match load, not with a steady drip. A leak is monotonic; this is not
       demonstrated to be one.

       What does hold: the game sits at 7-8 GB private, and on the machine this
       was measured on -- 16 GB, with Discord, Chrome, Steam and Defender taking
       ~5 GB between them -- that is right at the commit ceiling. At the ceiling,
       any allocation spike at a load produces a bad_alloc whether or not
       anything leaks.

       Two tests, neither run yet, in cost order:
         1. close the other applications and play as usual. If the crash stops,
            the mechanism is memory pressure and the fix is footprint, not a leak
            hunt.
         2. same loader, a character who is NOT Byakuya, measured in a match
            rather than during a load. That isolates this loader's code.

       The obvious third test -- remove the loader and keep the assets -- is NOT
       valid and crashes by itself: the cloned pl038->pl022 containers require
       the class byte, and without it Pl22::Init looks up an icon that no longer
       exists. Cloned assets plus an inactive class byte is a documented crash. */
    if (name && strstr(name, "bad_alloc")) {
        MEMORYSTATUSEX ms;
        ms.dwLength = sizeof ms;
        if (GlobalMemoryStatusEx(&ms))
            log_line("THROW/oom: memory load %lu%%, phys avail %llu MB of %llu, "
                     "commit avail %llu MB of %llu, this process VA avail %llu MB",
                     ms.dwMemoryLoad,
                     ms.ullAvailPhys >> 20, ms.ullTotalPhys >> 20,
                     ms.ullAvailPageFile >> 20, ms.ullTotalPageFile >> 20,
                     ms.ullAvailVirtual >> 20);
        __try {
            unsigned char** sp = (unsigned char**)ep->ContextRecord->Rsp;
            int i, shown = 0;
            for (i = 0; i < 0x400 && shown < 14; i++) {
                unsigned char* v = sp[i];
                if (v > mod && v < mod + 0x2000000)
                    log_line("THROW/stack: rsp+%04X  exe+0x%X",
                             i * 8, (unsigned)(v - mod)), shown++;
            }
        } __except (EXCEPTION_EXECUTE_HANDLER) { }
    }
}

/* ---------------------------------------------------------------------
   ** 2026-08-28 -- WHY THIS HANDLE EXISTS, AND WHY IT IS RE-ARMED.

   The game ships its own crash reporter at exe+0x11B4667 (present in the
   untouched retail exe -- not ours).  Given an access violation it walks the
   faulting thread's stack looking for return addresses inside the image:

       mov rdi, [rbx+0x98]      ; CONTEXT.Rsp
       cmp r12, 0x200           ; up to 512 slots = 4 KB
       mov rax, [rdi+r12*8]     ; <- unprobed
       cmp rdx, 0x11b5000       ; keep it if it points into .text

   That read is unguarded, so when Rsp is anywhere near the end of a thread's
   stack the walk runs off it and the reporter itself faults.  It registers
   ahead of us, so what we then log is ITS address, not the real one -- which
   is exactly how four test cycles in a row reported

       CRASH: access violation at exe+0x11B474D -- reading from 0xAA8DC00000

   with three different garbage fault addresses and never once named the code
   that actually crashed.  Every one of those was the game's stack walker
   dying on top of the real bug and burying it.

   Removing and re-adding our handler puts us back at the head of the chain,
   so we see the ORIGINAL exception first and log the true RVA before the
   game's reporter gets to mangle it.  We do it from the stats thread that
   already runs, and only while nothing has been reported yet, so it costs a
   pointer swap every 30 seconds and nothing at all after the first crash.
   --------------------------------------------------------------------- */
static PVOID g_veh_handle = 0;
static LONG64 g_veh_rearms = 0;
static volatile LONG g_crash_reported = 0;

/* The budget is per DISTINCT fault site. It used to be per fault, and on
   2026-09-07 four first-chance access violations at ONE address -- the same
   exe+0x6C09ECD4E three minutes apart, all survived -- spent the whole budget
   of four, so the fault that actually killed the client six minutes later
   printed nothing at all. A site that repeats is one thing that went wrong,
   however many times it says so. */
#define CRASH_SITES 8
static volatile LONG64 g_crash_site[CRASH_SITES];
static volatile LONG   g_crash_site_n = 0;
static volatile LONG64 g_crash_repeats = 0;

/* Has this RVA already been logged? Racy by construction: two threads faulting
   at once may both log, which costs two lines and is much cheaper than a lock
   inside an exception handler. */
static int crash_site_seen(unsigned long long rva)
{
    LONG i, n = g_crash_site_n;
    if (n > CRASH_SITES) n = CRASH_SITES;
    for (i = 0; i < n; i++)
        if ((unsigned long long)g_crash_site[i] == rva) {
            InterlockedIncrement64(&g_crash_repeats);
            return 1;
        }
    i = InterlockedIncrement(&g_crash_site_n) - 1;
    if (i < CRASH_SITES) g_crash_site[i] = (LONG64)rva;
    return 0;
}

static LONG CALLBACK crash_veh(EXCEPTION_POINTERS* ep)
{
    unsigned char* mod;
    void* addr;
    unsigned long long rva;
    ULONG_PTR kind, at;

    if (!ep || !ep->ExceptionRecord) return EXCEPTION_CONTINUE_SEARCH;
    if (ep->ExceptionRecord->ExceptionCode == CXX_THROW_CODE) {
        cxx_throw_report(ep);
        return EXCEPTION_CONTINUE_SEARCH;
    }
    /* Written for every fatal code, not just the access violation below.
       Stack overflow, illegal instruction, divide by zero and heap corruption
       all used to fall through here silently -- indistinguishable in the log
       from no crash at all. (0xC0000409/__fastfail, which is eight of the
       nine dumps on the maintainer's machine, still cannot be caught by any
       handler; the session marker is what covers it.) */
    crashlog_on_exception(ep);

    if (ep->ExceptionRecord->ExceptionCode != (DWORD)0xC0000005)
        return EXCEPTION_CONTINUE_SEARCH;

    mod  = (unsigned char*)GetModuleHandleA(NULL);
    addr = ep->ExceptionRecord->ExceptionAddress;
    rva  = (unsigned long long)((unsigned char*)addr - mod);

    /* Order matters: the site test comes FIRST, so a repeat costs no budget.
       Then the budget, so eight distinct sites cannot fill the log either. */
    if (crash_site_seen(rva)) return EXCEPTION_CONTINUE_SEARCH;
    if (InterlockedIncrement(&g_crash_reported) > 4) return EXCEPTION_CONTINUE_SEARCH;
    kind = ep->ExceptionRecord->NumberParameters > 0
         ? ep->ExceptionRecord->ExceptionInformation[0] : 0;
    at   = ep->ExceptionRecord->NumberParameters > 1
         ? ep->ExceptionRecord->ExceptionInformation[1] : 0;

    log_line("CRASH: access violation at exe+0x%llX -- %s 0x%llX (thread %lu)",
             rva,
             kind == 1 ? "writing to" : kind == 8 ? "executing" : "reading from",
             (unsigned long long)at, GetCurrentThreadId());
    log_line("CRASH: roomguard draw=%lld draw2=%lld steam=%lld map_hr=0x%llX",
             (long long)g_rg_draw_skips, (long long)g_rg_draw2_skips,
             (long long)g_rg_steam_skips, (unsigned long long)g_rg_map_hr);
    /* Without this a deduped storm is indistinguishable from a single fault,
       and "it happened once" is a different bug from "it happened 400 times". */
    if (g_crash_repeats)
        log_line("CRASH: %lld further fault(s) at an address already reported",
                 (long long)g_crash_repeats);

    /* ---- the register file and a poor-man's unwind ----------------------
       An RVA alone names the faulting instruction and nothing else, and the
       crashes this project keeps meeting are all of one shape: a function
       dereferences something it never tested, and the question is always
       WHICH register was bad and WHO called it. Both are already in hand
       here -- the CONTEXT is a parameter -- so there is no reason to read
       them out of a 51 MB dump with a debugger that is not installed.

       The "unwind" is deliberately not one: no RtlVirtualUnwind, no symbol
       machinery. It scans the top of the stack for qwords that land inside
       the exe image and prints them in order. Some are return addresses,
       some are spilled pointers, and it does not pretend to tell them
       apart -- but the first few exe-resident values on the stack ARE the
       call chain in practice, and that is what names the caller.

       Everything here is a read of memory the process already owns, inside
       SEH, in a handler that has already decided the process is dying. */
    if (ep->ContextRecord) {
        CONTEXT* c = ep->ContextRecord;
        log_line("CRASH/regs: rax=%016llX rbx=%016llX rcx=%016llX rdx=%016llX",
                 (unsigned long long)c->Rax, (unsigned long long)c->Rbx,
                 (unsigned long long)c->Rcx, (unsigned long long)c->Rdx);
        log_line("CRASH/regs: rsi=%016llX rdi=%016llX rbp=%016llX rsp=%016llX",
                 (unsigned long long)c->Rsi, (unsigned long long)c->Rdi,
                 (unsigned long long)c->Rbp, (unsigned long long)c->Rsp);
        log_line("CRASH/regs: r8 =%016llX r9 =%016llX r10=%016llX r11=%016llX",
                 (unsigned long long)c->R8,  (unsigned long long)c->R9,
                 (unsigned long long)c->R10, (unsigned long long)c->R11);
        log_line("CRASH/regs: r12=%016llX r13=%016llX r14=%016llX r15=%016llX",
                 (unsigned long long)c->R12, (unsigned long long)c->R13,
                 (unsigned long long)c->R14, (unsigned long long)c->R15);
        __try {
            unsigned long long base = (unsigned long long)mod;
            unsigned long long* sp  = (unsigned long long*)c->Rsp;
            int i, n = 0;
            for (i = 0; i < 512 && n < 12; i++) {
                unsigned long long v = sp[i];
                if (v > base && v < base + 0x2000000ULL) {
                    log_line("CRASH/stack: [rsp+0x%03X] exe+0x%llX",
                             (unsigned)(i * 8), v - base);
                    n++;
                }
            }
            if (!n) log_line("CRASH/stack: no exe-resident value in the first 4 KB");
        } __except(EXCEPTION_EXECUTE_HANDLER) {
            log_line("CRASH/stack: stack unreadable from the handler");
        }
    }
    vfn_report("at the crash");
    lookup_live_report();
    if (ENABLE_DRED) dred_report_if_removed();
    d3d12_debug_drain("the access violation");
    return EXCEPTION_CONTINUE_SEARCH;
}

/* Observability for the one genuinely shared site. If the neutralise count
   climbs while Byakuya is not in the match, then the assumption that only
   his Com-class lookups produce broken handles is wrong -- and it shows up
   in patch_ranked.log instead of being guessed at.                        */
/* ★★★ 2026-09-17 -- THE LINE THAT WOULD HAVE ANSWERED THIS IN ONE SESSION.
 *
 *  Berg's progressive frame-rate collapse was diagnosed by reverse-engineering
 *  the wall-clock gaps between `PL005/tel` lines out of patch_ranked.log: 60.0
 *  fps flat for 33 minutes, then 31.6, then 18.1. That worked, but it is a
 *  forensic exercise over a log that was never meant to state the frame rate,
 *  and it cannot tell CPU from GPU at all.
 *
 *  So state it. Two numbers make the next session decisive instead of
 *  suggestive:
 *    FPS     -- frames in this window / the window's own measured duration.
 *               No more inferring it from timestamps of something else.
 *    CYCLES  -- QueryProcessCycleTime delta / frames. THE DISCRIMINATOR. If
 *               cycles-per-frame DOUBLES as fps halves, the extra work is
 *               CPU-side and in this process: the per-frame code in these
 *               plugins is where to look. If cycles-per-frame stays FLAT while
 *               fps halves, this process is not doing more work -- the loss is
 *               in the driver or on the GPU, and every CPU-side candidate dies
 *               at once. One number, two whole families of cause eliminated.
 *  Plus working set, private commit, page faults and the handle count, which
 *  are nearly free and rule out the leak families.
 *
 *  ⓘ The frame counter is pl005_update's tick, so it reads as the frame rate in
 *    a match containing Zangetsu and as zero otherwise. Named FPS/pl005 for
 *    exactly that reason -- a counter whose name overstates what it measures is
 *    how a measurement becomes a wrong conclusion later.
 *  ⇒ ★★★ RULE: WHEN A SYMPTOM IS "IT GETS SLOWER", THE FIRST DELIVERABLE IS A
 *    NUMBER PER UNIT TIME, NOT A THEORY. Everything else is argument. */
/* ★★★ THIS FILE OWNS THE COUNTER, AND pl005_gauge.c MUST KNOW THAT.
   pl005_gauge.c is #include'd into TWO binaries: this one (at the bottom of
   this file, which is why the declaration below is enough here) and
   pl005.dll, via pl005_plugin.c, which never sees this line. Adding
   `g_perf_frames++` to pl005_update on 09-17 therefore compiled fine here
   and BROKE build_plugin.sh outright:
       pl005_gauge.c:1144: error: use of undeclared identifier 'g_perf_frames'
   Berg would have hit that on his next plugin build, from a change made for
   a measurement in a different binary.
   ⇒ ★★★ RULE: A FILE THAT IS #include'd INTO MORE THAN ONE TRANSLATION UNIT
     MAY NOT REFERENCE A SYMBOL THAT ONLY ONE OF THEM DEFINES. Give the
     shared file its own fallback definition and let the owner claim it. */
#define BROS_PERF_FRAMES_OWNED 1
static volatile LONG64 g_perf_frames = 0;    /* incremented by pl005_update */

static DWORD WINAPI gauge_stats_thread(LPVOID u)
{
    LONG64 seen_kills = 0;
    LONG64 last_frames = 0, last_cycles = 0;
    unsigned long long last_ms = 0;
    (void)u;
    for (;;) {
        Sleep(30000);
        {   /* ---- the perf line, first, so a crash report carries it ----
               ⓘ NO psapi. GetProcessMemoryInfo would have meant -lpsapi and a
                 new import in a loader that every run of the game depends on,
                 and it would have bought nothing: the ALLOC lines already carry
                 GlobalMemoryStatusEx, and on Berg's machine they already refute
                 the memory story -- load fell 53% -> 31% and available physical
                 ROSE 14.7 -> 21.8 GB across the session that collapsed to 18
                 fps. Everything below is kernel32, already imported.
               ⇒ ★ RULE: do not add a dependency to collect a number you have
                 already been given by something you are not reading. */
            ULONG64 cyc = 0;
            unsigned long long now = GetTickCount64();
            LONG64 fr = g_perf_frames;
            DWORD handles = 0;
            MEMORYSTATUSEX ms;
            double secs = last_ms ? (double)(now - last_ms) / 1000.0 : 0.0;
            LONG64 dfr = fr - last_frames;
            LONG64 dcy;
            QueryProcessCycleTime(GetCurrentProcess(), &cyc);
            dcy = (LONG64)cyc - last_cycles;
            ms.dwLength = sizeof ms;
            GetProcessHandleCount(GetCurrentProcess(), &handles);
            /* ★★★ THE PER-FRAME COLUMNS MOVED TO pl005.dll, AND HERE IS WHY.
               The frame counter is incremented by pl005_update, which lives in
               pl005_gauge.c -- and pl005_gauge.c is #include'd into THIS file
               only under `#if BUILD_CRE && BROS_PL005_PLUGIN` (line 8665). The
               build Berg actually runs is **Community**, where that is false
               and pl005_gauge.c is not in this binary at all. So g_perf_frames
               is declared here, never incremented here, and the line I added
               on 09-17 would have printed
                   PERF: FPS/pl005 0.0 (0 frames / 30.0s) | Mcycles/frame 0.000
               in the only build anyone runs -- while I described it to him as
               "the number that matters, and it splits the whole problem in
               half". A measurement that reads zero looks like an answer.
               ⇒ ★★★ RULE: WHEN A MEASUREMENT'S PRODUCER AND ITS CONSUMER CAN
                 LAND IN DIFFERENT BINARIES, VERIFY IT IN THE BUILD THE USER
                 ACTUALLY RUNS, NOT THE ONE YOU WROTE IT IN.
               What is left here is what THIS binary can honestly say: process
               cycles per WALL SECOND, handles, and memory. The per-frame split
               -- the load-bearing number -- is printed by PL005/perf, in the
               binary that owns the counter. */
            if (secs > 0.0 && GlobalMemoryStatusEx(&ms))
                log_line("PERF: Mcycles/sec %.1f | handles %lu | load %lu%% "
                         "availphys %llu MB | commit free %llu MB%s",
                         (double)dcy / secs / 1.0e6,
                         (unsigned long)handles,
                         (unsigned long)ms.dwMemoryLoad,
                         (unsigned long long)(ms.ullAvailPhys >> 20),
                         (unsigned long long)(ms.ullAvailPageFile >> 20),
                         dfr > 0 ? "" : "   [frames/Mcycles-per-frame: see the"
                                        " PL005/perf line -- the counter lives"
                                        " in pl005.dll]");
            last_frames = fr; last_cycles = (LONG64)cyc; last_ms = now;
        }
        /* stay first in the VEH chain -- see the note above g_veh_handle */
        if (g_veh_handle && !g_crash_reported) {
            PVOID re;
            RemoveVectoredExceptionHandler(g_veh_handle);
            re = AddVectoredExceptionHandler(1, crash_veh);
            if (re) { g_veh_handle = re; g_veh_rearms++; }
            else log_line("CRASH: re-arm failed -- the handler is no longer installed");
        }
        if (ENABLE_DRED) dred_report_if_removed();
        if (ENABLE_RS_VOLATILE && (g_rs_serialized || g_rs_blobs))
            log_line("RSVOLATILE: serializer calls %ld (%ld made volatile); blobs %ld "
                     "(%ld rewritten, %ld refused and passed through unchanged) -- a "
                     "rewritten range can no longer remove the device when the lobby "
                     "copies over it", g_rs_serialized, g_rs_serialized_fixed,
                     g_rs_blobs, g_rs_blobs_fixed, g_rs_blobs_refused);
        if (ENABLE_DESC_RING && g_dring_n)
            log_line("DESCRING: %ld descriptor copies, %ld submits, ring %s", g_dring_n,
                     g_exec_calls, g_dring_dumped ? "DUMPED" : "armed");
        if (ENABLE_BIND_GUARD && g_bind_calls)
            log_line("BINDGUARD: %ld root-table binds over %ld command list vtable(s), %ld "
                     "stale (%ld replaced, %ld with nothing to replace them); heaps %ld made, "
                     "%ld released, registry %s",
                     g_bind_calls, g_clvt_n, g_bind_blocked, g_bind_substituted,
                     g_bind_nofallback, g_dheap_made, g_dheap_gone,
                     g_dheap_overflow ? "OVERFLOWED (guard disarmed)" : "healthy");
        if (ENABLE_SUBMIT_GUARD && g_exec_calls)
            log_line("SUBMITGUARD: %ld submits, %ld unclosed list(s) dropped (%ld closed "
                     "here, %ld refused to close), %ld submit(s) left with nothing to send; "
                     "%ld list(s) tracked; %ld Reset(s), %ld of them failed",
                     g_exec_calls, g_submit_dropped, g_submit_closed, g_submit_closefail,
                     g_submit_emptied, g_clst_n, g_reset_calls, g_reset_failed);
        if (ENABLE_BARRIER_GUARD && g_bar_calls)
            log_line("BARRIERGUARD: %ld ResourceBarrier calls, %ld barriers dropped for having "
                     "no resource, %ld calls with no barrier at all", g_bar_calls,
                     g_bar_dropped, g_bar_empty);
        /* Unconditional, and every 30s rather than 60s. A crash report is only as
           good as the last line written before it, and the old form skipped the
           line entirely whenever the kill count had not moved -- which is most of
           the time, since the guard fires roughly 3 times in 27 million copies. */
        {
            LONG mask = g_sq_slotmask;
            g_sq_slotmask = 0;                     /* start the next window */
            (void)seen_kills;
            uiplay_report();
            lookup_report();
            vcall_report();
            vfn_report("30s window");
            log_line("BYAKUYA_GAUGE: guard neutralised %lld of %lld handle copies; "
                     "driver %lld frames (%lld shows, %lld hides); evo %lld frames, "
                     "%lld visibility sets, %lld sword zeroes; slots=%ld%s; "
                     "teardown saves=%lld; teardown2 saves=%lld; setrate saves=%u; "
                     "refrel saves=%lld; slot2 saves=%u; "
                     "uiplay saves=%lld; lookup saves=%lld; vcall saves=%lld; "
                     "refrel2 saves=%lld; "
                     "icon writes=%lld; icon dead-drops=%lld; palette pushes=%lld; "
                     "roomguard draw=%lld draw2=%lld steam=%lld map_fn=0x%llX map_hr=0x%llX; "
                     /* Observations, not saves -- deliberately worded so a
                        non-zero count is never mistaken for an intervention.
                        This is the field that faults at exe+0x9546C. */
                     "assign-probe %lld bad of %lld destinations seen",
                     (long long)g_hg_kills,  (long long)g_hg_calls,
                     (long long)g_sq_frames, (long long)g_sq_shows,
                     (long long)g_sq_hides,
                     (long long)g_sq_evo_frames, (long long)g_sq_evo_sets,
                     (long long)g_sq_evo_zero,
                     (long)mask,
                     (mask & 3) == 3 ? " MIRROR" : "", (long long)g_td_saves,
                     (long long)g_td2_saves,
                     pl022_saves(PL022_CNT_SETRATE), (long long)g_rr_saves,
                     (unsigned int)g_pl022_upd_skips, (long long)uiplay_saves(),
                     (long long)lookup_saves(), (long long)vcall_saves(),
                     (long long)refrel2_saves(),
                     (long long)g_icon_writes, (long long)g_icon_dead,
                     (long long)g_pal_pushes,
                     (long long)g_rg_draw_skips, (long long)g_rg_draw2_skips,
                     (long long)g_rg_steam_skips,
                     (unsigned long long)(g_rg_map_fn
                         ? (unsigned char*)g_rg_map_fn - (unsigned char*)GetModuleHandleA(NULL)
                         : 0),
                     (unsigned long long)g_rg_map_hr,
                     (long long)g_ha_bad, (long long)g_ha_calls);
        }
        /* Its own line, not appended to the one above: log_line's buffer is 512
           chars and that format is already close to it, so an appended clause is
           the first thing to be silently truncated. */
        if (ENABLE_ROOM3) {
            char line[400]; int off = 0, t, shown = 0;
            for (t = 0; t < 256 && off < (int)sizeof(line) - 24; t++) {
                if (!g_pkt_rx_type[t] && !g_pkt_tx_type[t]) continue;
                off += snprintf(line + off, sizeof(line) - off, "%s%02X:%lld/%lld",
                                shown++ ? " " : "", t,
                                (long long)g_pkt_rx_type[t], (long long)g_pkt_tx_type[t]);
            }
            if (shown)
                log_line("ROOM3/pkt: types seen (hex: received/sent) -- %s", line);
        }
        if (ENABLE_ROOM3) { room3_state_log(); room3_rip_log(); }
        /* ⚠ Gated on the clamp counters until 2026-09-16, which meant the line vanished
           exactly when the arm patch made the clamps unnecessary -- and with it the only
           report of whether the spectator was muted. Print it whenever this build is in. */
        if (ENABLE_ROOM3)
            log_line("ROOM3: seat clamp -- %lld read(s) with no seat of their own served "
                     "seat 0, %lld bailed with no fighter list at all. The first number is "
                     "a spectator watching; the second is a client that never built the "
                     "fight. Role forced %lld time(s); %lld outgoing battle-stream packets "
                     "suppressed (this client %s the spectator).",
                     (long long)g_room3_clamped, (long long)g_room3_skip_empty,
                     (long long)g_room3_role_forced, (long long)g_room3_muted,
                     g_room3_is_spectator ? "IS" : "is not");
        if (ENABLE_ROOM3 && (g_room3_slot26_seen || g_room3_setup_seen || g_room3_state1_seen))
            log_line("ROOM3/crumb: inside slot26 -- +0E3D %lld, +0E56 %lld, +0F0E %lld "
                     "(registration is at +0x10C9)",
                     (long long)g_room3_s26[0], (long long)g_room3_s26[1],
                     (long long)g_room3_s26[2]);
            log_line("ROOM3/crumb: slot26 %lld, callback registered %lld, battle set-up "
                     "entered %lld, its state test %lld -- the first number that stays at "
                     "zero is where this client stops",
                     (long long)g_room3_slot26_seen, (long long)g_room3_reg_seen,
                     (long long)g_room3_setup_seen, (long long)g_room3_state1_seen);
        if (ENABLE_ROOM3 && (g_room3_sm_calls || g_room3_stw_calls))
            log_line("ROOM3/st: machine called %lld time(s), last state 0x%X on object %p; "
                     "state set to 0x32 %lld time(s) on object %p -- a call count that "
                     "stops rising means the driver gave up; two different objects mean the "
                     "write lands somewhere the machine never reads",
                     (long long)g_room3_sm_calls, (unsigned)g_room3_sm_last, g_room3_sm_this,
                     (long long)g_room3_stw_calls, g_room3_stw_this);
        if (ENABLE_ROOM3 && (g_room3_tick_calls || g_room3_reach_calls))
            log_line("ROOM3/tick: scene tick %lld (last %.1f s ago, from exe+0x%X), reached "
                     "slot 11 ran %lld time(s) (last %.1f s ago, from exe+0x%X) -- slot 11 "
                     "calls the tick with nothing in between, so these two numbers agree "
                     "and the caller is the next thing to look at",
                     (long long)g_room3_tick_calls,
                     (double)(GetTickCount64() - g_room3_tick_tick) / 1000.0,
                     (unsigned)g_room3_tick_caller,
                     (long long)g_room3_reach_calls,
                     (double)(GetTickCount64() - g_room3_reach_tick) / 1000.0,
                     (unsigned)g_room3_reach_caller);
        if (ENABLE_ROOM3) {
            int i;
            for (i = 0; i < 8; i++) {
                if (!g_p2p_id[i] || !g_p2p_hist[i]) continue;
                log_line("ROOM3/hist: peer %llu -- %lld input histories received, longest %d "
                         "frames -- a history that keeps growing is one nobody acknowledges",
                         (unsigned long long)g_p2p_id[i], (long long)g_p2p_hist[i],
                         (int)g_p2p_hmax[i]);
            }
            for (i = 0; i < 8; i++) {
                if (!g_p2p_id[i]) continue;
                log_line("ROOM3/streams: peer %llu -- SENT 0x03:%lld 0x06:%lld other:%lld | "
                         "RECEIVED 0x03:%lld 0x06:%lld other:%lld -- 0x03/0x06 are the "
                         "per-frame input streams; a peer that sends them to one side only "
                         "leaves the other with nothing to replay",
                         (unsigned long long)g_p2p_id[i],
                         (long long)g_p2p_tx3[i][0], (long long)g_p2p_tx3[i][1],
                         (long long)g_p2p_tx3[i][2], (long long)g_p2p_rx3[i][0],
                         (long long)g_p2p_rx3[i][1], (long long)g_p2p_rx3[i][2]);
            }
        }
        if (ENABLE_ROOM3 && (g_room3_lsm || g_room3_sa)) {
            int role = -9, sendon = -1, rq = -1; unsigned sent = 0, used = 0, played = 0;
            unsigned seed = 0; LONG64 queue = -1;
            __try {
                unsigned char* m = (unsigned char*)g_room3_lsm;
                unsigned char* a = (unsigned char*)g_room3_sa;
                if (m) {
                    sendon = *(unsigned char*)(m + 0x18);
                    used   = *(unsigned short*)(m + 0x38);
                    sent   = *(unsigned short*)(m + 0x3A);
                    rq     = *(int*)(m + 0x50);
                }
                if (a) {
                    unsigned char* box = *(unsigned char**)(a + 0xBC0);
                    role = *(int*)(a + 0xC34);
                    if (box) {
                        queue  = (LONG64)((*(unsigned char**)(box + 0xD8) -
                                           *(unsigned char**)(box + 0xD0)) / 0x68);
                        played = *(unsigned short*)(box + 0xE8);
                        if (*(unsigned char**)box)
                            seed = *(unsigned*)(*(unsigned char**)box + 4);
                    }
                }
            } __except(EXCEPTION_EXECUTE_HANDLER) { }
            log_line("ROOM3/galpipe: role %d, playback queue %lld played %u, send-enabled %d, "
                     "sent-cursor %u, consumed %u, request %d, stream packets sent %lld "
                     "received %lld, flips %lld, handoffs %lld, name-clamps %lld, "
                     "rematches %lld, returns to room %lld, skips %lld, index-clamps %lld, "
                     "restarts refused %lld, seed %08X", role,
                     (long long)queue, played,
                     sendon, sent, used, rq, (long long)g_room3_gal_send,
                     (long long)g_room3_gal_recv, (long long)g_room3_flips,
                     (long long)g_room3_handoffs, (long long)g_room3_name_clamp,
                     (long long)g_room3_rematch, (long long)g_room3_toroom,
                     (long long)g_room3_skips, (long long)g_room3_idx_src,
                     (long long)g_room3_norestart, seed);
        }
        if (ENABLE_ROOM3 && g_room3_pk_n) {
            char out[900]; int at = 0, i;
            for (i = 0; i < (int)g_room3_pk_n && i < ROOM3_PK_MAX && at < 820; i++) {
                const char* nm = g_room3_pk_name[i] ? g_room3_pk_name[i] : "?";
                const char* u = strstr(nm, "@U");      /* ?$TypePacketData@U<Name>@... */
                char shortn[40]; int j = 0;
                u = u ? u + 2 : nm;
                while (u[j] && u[j] != '@' && j < 39) { shortn[j] = u[j]; j++; }
                shortn[j] = 0;
                at += snprintf(out + at, sizeof(out) - at, "%s%s:%lld/%lld ", shortn,
                               g_room3_pk_ours[i] ? "*" : "", (long long)g_room3_pk_sent[i],
                               (long long)g_room3_pk_drop[i]);
            }
            log_line("ROOM3/quiet: packet classes sent/dropped (* = SOnlineAction) -- %s", out);
        }
        if (ENABLE_ROOM3 && g_room3_lsm) {
            LONG mode = -1, kind = -1; LONG64 recs = -1;
            __try {
                unsigned char* m = (unsigned char*)g_room3_lsm;
                mode = *(LONG*)(m + 0x10);
                kind = *(LONG*)(m + 0x14);
                recs = (LONG64)((*(unsigned char**)(m + 0x28) -
                                 *(unsigned char**)(m + 0x20)) / 0x68);
            } __except(EXCEPTION_EXECUTE_HANDLER) { }
            log_line("ROOM3/gallery: stream manager %p -- system_mode %d (%s), kind %d, %lld "
                     "per-frame record(s) buffered -- a buffer that grows on the spectator "
                     "means the host's stream is arriving", g_room3_lsm, (int)mode,
                     mode == 1 ? "LiveStreaming" : mode == 0 ? "Idle" : "?", (int)kind,
                     (long long)recs);
        }
        if (ENABLE_ROOM3 && g_room3_ep_count) {
            int i; char line[400]; int at = 0;
            for (i = 0; i < ROOM3_EP_MAX && i < g_room3_ep_count; i++) {
                if (at > (int)sizeof(line) - 60) break;
                at += sprintf(line + at, "%s%s:%lld", at ? ", " : "",
                              g_room3_ep_name[i] ? g_room3_ep_name[i] : "?",
                              (long long)g_room3_ep_n[i]);
            }
            log_line("ROOM3/make: Brains created so far -- %s", line);
        }
        if (ENABLE_ROOM3 && g_room3_to_lines)
            log_line("ROOM3/timeout: the barrier's clock last read %.1f, mark %.1f, delta "
                     "%.1f of a 1000 budget", g_room3_to_now, g_room3_to_then,
                     g_room3_to_now - g_room3_to_then);
        if (ENABLE_ROOM3 && g_room3_bit_lines)
            log_line("ROOM3/bit: the barrier's flag word last read 0x%X; 0x401 forced %lld "
                     "time(s) -- a client that never aborts shows what a healthy value is",
                     (unsigned)g_room3_bit_last, (long long)g_room3_bit_set);
        if (ENABLE_ROOM3 && g_room3_thr_calls) {
            int i; char line[256]; int at = 0;
            for (i = 0; i < ROOM3_THR_MAX && g_room3_thr_n[i]; i++) {
                if (at > (int)sizeof(line) - 32) break;
                at += sprintf(line + at, "%s0x%X:%lld", at ? " " : "",
                              (unsigned)g_room3_thr_state[i], (long long)g_room3_thr_n[i]);
            }
            log_line("ROOM3/thr: the throttle ran %lld time(s) and asked for a frame drop "
                     "%lld time(s); states seen below 0x12D: %s%s",
                     (long long)g_room3_thr_calls, (long long)g_room3_thr_skip,
                     at ? line : "(none)",
                     ROOM3_NO_THROTTLE && g_room3_is_spectator
                         ? " -- and the drop is being refused on this client" : "");
        }
        if (ENABLE_ROOM3 && g_room3_wr_rip[0]) {
            int i; char line[512]; int at = 0;
            for (i = 0; i < ROOM3_WR_MAX && g_room3_wr_rip[i]; i++) {
                if (at > (int)sizeof(line) - 40) break;
                at += sprintf(line + at, "%s0x%X:%lld", at ? " " : "",
                              (unsigned)g_room3_wr_rip[i], (long long)g_room3_wr_n[i]);
            }
            log_line("ROOM3/bp: skip-frame byte written from %s -- a data breakpoint traps "
                     "AFTER the store, so each RIP is the instruction following the setter "
                     "(the four known ones are 0x801A5C, 0x801C6D, 0x802875, 0x802A77)",
                     line);
        }
        if (ENABLE_ROOM3 && g_room3_exits_on) {
            int i; char line[512]; int at = 0;
            for (i = 0; i < ROOM3_EXIT_MAX; i++) {
                if (!g_room3_exit_rva[i] || !g_room3_exit_n[i]) continue;
                if (at > (int)sizeof(line) - 40) break;
                at += sprintf(line + at, "%s0x%X:%lld", at ? " " : "",
                              g_room3_exit_rva[i], (long long)g_room3_exit_n[i]);
            }
            /* ⚠ The counts are the measurement, not the "last" -- every client takes some
               exit sometimes, so a single most-recent value reads the same on a frozen
               client and a healthy one. It did, on 2026-09-18: all three said 0x8575BA. */
            log_line("ROOM3/exit: per-exit counts %s (last 0x%X) -- the exit whose count "
                     "keeps climbing while the reach count stops is where it gives up",
                     at ? line : "(none taken)", (unsigned)g_room3_exit);
        }
        if (ENABLE_ROOM3 && g_room3_t5_calls)
            log_line("ROOM3/task5: exe+0x857390 entered %lld time(s), last %.1f s ago, from "
                     "exe+0x%X; reached the call at 0x857CC9 %lld time(s), last %.1f s ago "
                     "-- entered but not reaching means it returns inside 0x940 bytes, both "
                     "frozen means the task itself is no longer ticked",
                     (long long)g_room3_t5_calls,
                     (double)(GetTickCount64() - g_room3_t5_tick) / 1000.0,
                     (unsigned)g_room3_t5_caller, (long long)g_room3_t5_reach,
                     g_room3_t5_rtick
                         ? (double)(GetTickCount64() - g_room3_t5_rtick) / 1000.0 : -1.0);
        if (ENABLE_ROOM3 && g_room3_fn_calls) {
            unsigned char* m = (unsigned char*)GetModuleHandleA(NULL);
            LONG sw = -1;
            __try { sw = *(LONG*)(m + 0x1CE1D4C); }
            __except(EXCEPTION_EXECUTE_HANDLER) { sw = -2; }
            log_line("ROOM3/fn: exe+0x8A0B10 entered %lld time(s), last %.1f s ago, from "
                     "exe+0x%X; the switch global at RVA 0x1CE1D4C reads %d -- compare with "
                     "the loop-head count below: entered but not reaching the head means "
                     "something returns inside the first 485 bytes",
                     (long long)g_room3_fn_calls,
                     (double)(GetTickCount64() - g_room3_fn_tick) / 1000.0,
                     (unsigned)g_room3_fn_caller, (int)sw);
        }
        if (ENABLE_ROOM3 && g_room3_walk_calls)
            log_line("ROOM3/walk: the loop HEAD (exe+0x8A0CF5, +0x1E5 into the function) "
                     "was reached %lld time(s) on %p, last %.1f s ago, "
                     "with %d element(s) last time (min %d, max %d) -- if this keeps running "
                     "while a row below stops being walked, that row left the container",
                     (long long)g_room3_walk_calls, g_room3_walk_this,
                     (double)(GetTickCount64() - g_room3_walk_tick) / 1000.0,
                     (int)g_room3_walk_count, (int)g_room3_walk_min, (int)g_room3_walk_max);
        if (ENABLE_ROOM3 && g_room3_sub[0]) {
            int i;
            for (i = 0; i < ROOM3_SUB_MAX && g_room3_sub[i]; i++) {
                /* Read the byte NOW rather than trusting the cached value: the cached one
                   is only refreshed when the gate runs, so on a row the gate has stopped
                   visiting it says whatever it said at the last visit. That difference is
                   the whole question -- a stale 0 and a live 1 mean opposite things. */
                int live = -1, liveword = -1;
                __try {
                    if (g_room3_sub_bytes[i])
                        live = (int)(*((unsigned char*)g_room3_sub_bytes[i] + 0xF0));
                    liveword = (int)(*(LONG*)((unsigned char*)g_room3_sub[i] + 0x7C));
                } __except(EXCEPTION_EXECUTE_HANDLER) { live = -2; liveword = -2; }
                log_line("ROOM3/gate: sub %p word %d (live %d) byte %d (live %d) -- ticked "
                         "%lld time(s) (last %.1f s ago), skipped %lld, visited %lld time(s) "
                         "(last %.1f s ago), walked %lld time(s) (last %.1f s ago)%s -- the "
                         "row whose tick count matches the frozen scene tick is ours; walked "
                         "but not visited means 0x8A0D1F skipped it on the state word",
                         g_room3_sub[i], (int)g_room3_sub_word[i], liveword,
                         (int)g_room3_sub_byte[i], live,
                         (long long)g_room3_sub_pass[i],
                         g_room3_sub_ptick[i]
                             ? (double)(GetTickCount64() - g_room3_sub_ptick[i]) / 1000.0
                             : -1.0,
                         (long long)g_room3_sub_skip[i],
                         (long long)g_room3_sub_seen[i],
                         g_room3_sub_stick[i]
                             ? (double)(GetTickCount64() - g_room3_sub_stick[i]) / 1000.0
                             : -1.0,
                         (long long)g_room3_sub_walk[i],
                         g_room3_sub_wtick[i]
                             ? (double)(GetTickCount64() - g_room3_sub_wtick[i]) / 1000.0
                             : -1.0,
                         g_room3_sub[i] == g_room3_bp_sub ? " <<< the watched one" : "");
            }
        }
        if (ENABLE_ROOM3 && g_room3_obj[0]) {
            int i;
            for (i = 0; i < ROOM3_OBJ_MAX && g_room3_obj[i]; i++)
                log_line("ROOM3/obj: %p ticked %lld time(s), state 0x%X, last %.1f s ago",
                         g_room3_obj[i], (long long)g_room3_obj_calls[i],
                         (unsigned)g_room3_obj_state[i],
                         (double)(GetTickCount64() - g_room3_obj_tick[i]) / 1000.0);
        }
        if (ENABLE_ROOM3 && g_room3_up_calls)
            log_line("ROOM3/up: update called %lld time(s), last state 0x%X, last run %.1f s "
                     "ago, from exe+0x%X -- if THIS stops, nothing below it can run",
                     (long long)g_room3_up_calls, (unsigned)g_room3_up_last,
                     (double)(GetTickCount64() - g_room3_up_tick) / 1000.0,
                     (unsigned)g_room3_up_caller);
        if (ENABLE_ROOM3 && g_room3_sm_calls)
            log_line("ROOM3/st: last driven %.1f s ago, from exe+0x%X -- on the spectator this "
                     "stops climbing the moment the state becomes 0x32, so the question is "
                     "why THAT caller gives up",
                     (double)(GetTickCount64() - g_room3_sm_tick) / 1000.0,
                     (unsigned)g_room3_sm_caller);
        if (ENABLE_ROOM3 && g_room3_stw2_calls)
            log_line("ROOM3/stw: the message handler's default tail set the state %lld "
                     "time(s) -- every message without a case of its own becomes the state",
                     (long long)g_room3_stw2_calls);
        if (ENABLE_ROOM3 && g_room3_state1_forced)
            log_line("ROOM3/state1: the state-1 exit was bypassed %lld time(s) on this "
                     "client", (long long)g_room3_state1_forced);
        if (ENABLE_ROOM3 && g_room3_gate_passed)
            log_line("ROOM3/part: participant test waved through %lld time(s) -- without "
                     "this the client sits in state 2 with its match clock frozen",
                     (long long)g_room3_gate_passed);
        if (ENABLE_ROOM3 && g_room3_mode >= 0)
            log_line("ROOM3/mode: this client entered the battle with [obj+0x480] = %d "
                     "(0 = player 1, 1 = player 2, 2 = no side -- the spectator)",
                     g_room3_mode);
        if (ENABLE_BYAKUYA_PETAL_TIMER) pl022_timer_log();
        if (ENABLE_BYAKUYA_BUILDER_SPENDER) pl022_bs_log();
        if (ENABLE_BACKSTEP_HOLD && g_bsh_cave) {
            unsigned int  forced = *(volatile unsigned int*) (g_bsh_cave + BSH_FORCED);
            unsigned int  seen   = *(volatile unsigned int*) (g_bsh_cave + BSH_MASK);
            unsigned char last   = *(volatile unsigned char*)(g_bsh_cave + BSH_LAST);
            unsigned int blocked = *(volatile unsigned int*)(g_bsh_cave + BSH_BLOCKED);
            log_line("BACKSTEP/probe: forced %u, blocked %u; fighter+0xFA0 last=%u, "
                     "values seen (bit N = command N) = 0x%08X",
                     forced, blocked, (unsigned)last, seen);
        }
        if (g_fsh_cave) {
            volatile unsigned int* c = (volatile unsigned int*)g_fsh_cave;
            log_line("FLASHSTEP/gate: emitted via edge=%u held=%u tap=%u; NOT emitted=%u",
                     c[FSH_C_EDGE/4], c[FSH_C_HELD/4], c[FSH_C_TAP/4], c[FSH_C_SKIP/4]);
        }
        if (ENABLE_INPUT_PROBE && g_ipr_cave) {
            volatile unsigned int* v = (volatile unsigned int*)(g_ipr_cave + IPR_SNAP);
            unsigned int ticks = *(volatile unsigned int*)(g_ipr_cave + IPR_TICKS);
            {
                volatile unsigned int* q = (volatile unsigned int*)(g_ipr_cave + IPR_CMD_BASE);
                log_line("INPUTPROBE/cmds: 0x16 hoho=%u | 0x20=%u 0x21=%u | "
                         "0x25=%u 0x27=%u | 0x26 by site: 6C4=%u B20=%u E8D=%u "
                         "| 0x28 by site: "
                         "634=%u 838=%u D3F=%u FA5=%u 3061=%u",
                         q[0], q[1], q[2], q[3], q[5],
                         q[11], q[12], q[13],
                         q[6], q[7], q[8], q[9], q[10]);
                log_line("INPUTPROBE/r12: at the 0x26 emission r12d = 0x%08X "
                         "(gate is `test [r14+0x104], r12d`, +0x104 = 0x10)",
                         *(volatile unsigned int*)(g_ipr_cave + IPR_R12));
                log_line("INPUTPROBE/state: seen-mask=0x%08X | LAST emit: cmd=%u "
                         "flag9A8=%u flag1310=%u",
                         *(volatile unsigned int*)(g_ipr_cave + IPR_FMASK),
                         *(volatile unsigned char*)(g_ipr_cave + IPR_LASTCMD),
                         *(volatile unsigned char*)(g_ipr_cave + IPR_LAST9A8),
                         *(volatile unsigned char*)(g_ipr_cave + IPR_LAST1310));
            }
            unsigned int s2 = *(volatile unsigned int*)(g_ipr_cave + IPR_SITE2);
            unsigned int s3 = *(volatile unsigned int*)(g_ipr_cave + IPR_SITE3);
            log_line("INPUTPROBE: flash-step emits from site2(0x4127F9)=%u site3(0x412D00)=%u",
                     s2, s3);
            log_line("INPUTPROBE/down: buttons-down mask right now = 0x%08X",
                     *(volatile unsigned int*)(g_ipr_cave + IPR_DOWN));
            log_line("INPUTPROBE: %u frames since install | masks CC=%08X D8=%08X E0=%08X E4=%08X | "
                     "F0(hoho)=%08X F4=%08X F8=%08X | "
                     "100(sp)=%08X 104(sp)=%08X 108(sp)=%08X 10C=%08X",
                     ticks, v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8], v[9], v[10]);
        }
    }
}

/* The handle guard, installed WITHOUT Byakuya's gauge.

   2026-09-22. patch_byakuya_gauge() installs the guard as its first hook, so
   -DENABLE_BYAKUYA_GAUGE=0 silently removed the guard too -- and the guard is
   load-bearing. DataChakka BYAKUYA_CRASH.md says it twice: conclusion 8, "the
   handle guard is load-bearing -- removing it reopens exe+0x927E6", and the
   section "There is no evo bug", which puts the evo crash seen in the
   gauge-disabled arm down to that arm's configuration rather than to the evo
   transition itself. A build that gives Byakuya his public-patch mechanism
   still has to carry the guard.

   The guard needs nothing the gauge installs: it validates the SOURCE handle's
   +0x40, and the only state it shares is g_gauge_mod, set here. The layout
   byte at GAUGE_RVA_LAYOUT is deliberately NOT checked -- that byte picks
   Byakuya's UI layout, which this configuration leaves vanilla on purpose, and
   the shared_ptr chain the guard contains is not Byakuya-specific. */
static void patch_gauge_handle_guard_only(void)
{
    static const unsigned char sig_handle[6] = {0x48,0x8B,0x02,0x48,0x89,0x01};
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);

    if (!mod) return;
    g_gauge_mod = mod;

    if (memcmp(mod + GAUGE_RVA_HANDLE, sig_handle, sizeof(sig_handle)) != 0) {
        log_line("HANDLE/guard: prologue not at the expected RVA 0x%X (game updated?) "
                 "-- NOT installed, so exe+0x927E6 is unprotected this run",
                 GAUGE_RVA_HANDLE);
        return;
    }
    if (!gauge_install_hook(GAUGE_RVA_HANDLE, 6, (void*)gauge_handle_guard, 1,
                            "HANDLE/guard (gauge off)")) {
        log_line("HANDLE/guard: hook failed -- exe+0x927E6 is unprotected this run");
        return;
    }
    log_line("HANDLE/guard: installed WITHOUT the Byakuya gauge -- Byakuya keeps his "
             "public-patch mechanism and UI, and the shared_ptr chain stays contained.");
}

static void patch_byakuya_gauge(void)
{
    static const unsigned char sig_handle[6]  = {0x48,0x8B,0x02,0x48,0x89,0x01};
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);

    if (!mod) return;
    g_gauge_mod = mod;

    /* Every anchor is verified BEFORE anything is written, so a game update
       leaves the process untouched rather than half-patched. The class byte
       at GAUGE_RVA_CLASSBYTE is checked inside pl022_gauge_install, which
       accepts both the shipped 0x09 and the 0x12 an older build left behind. */
    if (mod[GAUGE_RVA_LAYOUT] != 0x09) {
        log_line("BYAKUYA_GAUGE: layout byte at RVA 0x%X is 0x%02X, expected 0x09 -- "
                 "REFUSING to install. That byte picks the layout name, and therefore "
                 "Byakuya resource group; moving it is what makes the SP1 lookup fail.",
                 GAUGE_RVA_LAYOUT, mod[GAUGE_RVA_LAYOUT]);
        return;
    }
    if (memcmp(mod + GAUGE_RVA_HANDLE, sig_handle, sizeof(sig_handle)) != 0) {
        log_line("BYAKUYA_GAUGE: handle-guard prologue not at expected RVA 0x%X "
                 "(game updated?) -- skipped", GAUGE_RVA_HANDLE);
        return;
    }

    /* Hooks first, controller last -- the CE order 1->2->3 deliberately
       inverted. The controller alone is what could crash on SP1; the hooks
       alone are inert. Installing this way means a partial install can never
       leave a crashing game behind.                                        */
    /* The guard nulls [obj+0x40] when a handle looks broken. That skips the
       release that field would otherwise drive, which unbalances a refcount --
       and the teardown destructor at exe+0x8B0530 walks it. Flag so a build
       can be made without it and the two compared.

       ★ 2026-09-07: that comparison has now been made, and it was not needed.
       This comment used to say the guard nulls +0x38 AND +0x40, which stopped
       being true when the payload rules were removed -- and the stale wording
       was itself used to build a hypothesis that the guard was causing the
       exe+0x9546C crash. It was not: the crashing session logged
       "guard neutralised 0 of 29,042,625 handle copies", so it never acted,
       and nulling can only ever produce 0, which 0x95410 explicitly tests for
       and skips. It cannot produce the non-canonical value that faulted.
       Corrected here so the next reader does not repeat it. */
    if (ENABLE_GAUGE_HANDLE_GUARD) {
        if (!gauge_install_hook(GAUGE_RVA_HANDLE, 6, (void*)gauge_handle_guard, 1,
                                "BYAKUYA_GAUGE/guard")) {
            log_line("BYAKUYA_GAUGE: guard hook failed -- class byte left at 0x09, so "
                     "Byakuya keeps his vanilla icon UI and the game is unchanged");
            return;
        }
    } else {
        log_line("BYAKUYA_GAUGE/guard: DISABLED at build time -- SP1 will fault at "
                 "exe+0x927E6, `lock inc [rax+0xc]` on a garbage shared_ptr control block");
    }

    /* Observe the DESTINATION handle in operator=, the field that faults at
       exe+0x9546C and that nothing has ever looked at. Read-only: see
       gauge_assign_probe. Installed unconditionally and independently of the
       guard above, because it changes nothing and because the crash it is
       watching for happens whether or not Byakuya's gauge is in play.

       Its failure is not fatal to anything: without it the game behaves
       exactly as it does today, minus one diagnostic. */
    {
        static const unsigned char sig_assign[5] =
            { 0x48, 0x89, 0x5C, 0x24, 0x08 };   /* mov [rsp+8],rbx           */
        if (memcmp(mod + GAUGE_RVA_ASSIGN, sig_assign, sizeof(sig_assign)) != 0) {
            log_line("HANDLE/assign: exe+0x%X is not the expected prologue "
                     "(game updated?) -- probe skipped", GAUGE_RVA_ASSIGN);
        } else if (!gauge_install_hook(GAUGE_RVA_ASSIGN, 5,
                                       (void*)gauge_assign_probe, 0,
                                       "HANDLE/assign")) {
            log_line("HANDLE/assign: probe hook failed -- no diagnostic, and "
                     "nothing else changes");
        } else {
            log_line("HANDLE/assign: read-only probe installed at exe+0x%X. "
                     "Watches the DESTINATION control block that faults at "
                     "exe+0x9546C on entry to character select. Observes only "
                     "-- it never modifies a handle, because 0x95410 has 1051 "
                     "callers and neutralising there would trade a loud crash "
                     "for a silent refcount bug.", GAUGE_RVA_ASSIGN);
        }
    }
    /* ★ 2026-09-02: the driver hook on the enhance update at GAUGE_RVA_ENHANCE
       is GONE. It reached the controller through g_battleUi[slot] -> +0x200 and
       wrote its element fields from outside the object, at a timing the engine
       does not own -- the one structural difference from pl005_gauge.c, and the
       shape of the crashes that survived every other fix. The same work now
       runs inside our own update slot (pl022_update), called by the engine on
       an object it has just validated. */

    /* The commit, and the whole of the 2026-09-01 rework: instead of moving
       uiId 22 onto Pl38 and editing PL38'S SHARED VTABLE, we intercept the
       controller factory and hand back an object carrying a vtable of our
       own. Same 36 slots, same Pl38::Init, same object layout -- but slots 2
       and 10 go through a null check before reaching Com::slot2 and
       Com::SetRate, which is what the two engine-side guards at 0x20750A and
       0x208470 were containing from the outside. See pl022_gauge.c. */
    if (!pl022_gauge_install()) {
        log_line("BYAKUYA_GAUGE: controller not installed -- Byakuya keeps the stock "
                 "Pl22 icon UI. The driver and guard hooks above are inert without it: "
                 "the driver filters on chara id and finds no gauge to drive.");
        return;
    }
    log_line("BYAKUYA_GAUGE: installed -- layout byte 0x%X still 0x09; no vtable method "
             "body patched and no engine vtable written, so Grimmjow, Zangetsu, "
             "Aizen/Stark and the other 26 UI classes are all unaffected",
             GAUGE_RVA_LAYOUT);
}

/* =====================================================================
 *  TEARDOWN GUARD  (exe+0x8B06CA)
 * ---------------------------------------------------------------------
 *  2026-08-22, from a crash dump off another player's machine: an online
 *  match with Byakuya in BOTH slots faulted at exe+0x8B06D0 at the end of
 *  the match, on a client running the +0x40-only handle guard. So that fix
 *  made the teardown crash rarer, not gone.
 *
 *  exe+0x8B0530 releases two smart pointers held by one object:
 *
 *      8B0695  mov  rcx,[rdi+0x18]      ; weak_ptr
 *      8B06A5  lock xadd [rcx+0xc],eax
 *      8B06B5  mov  rbx,[rdi+8]         ; shared_ptr control block
 *      8B06C0  lock xadd [rbx+8],eax    ; strong--, eax = old value
 *      8B06C8  jne  8B06E5              ; not the last -> done
 *      8B06CA  mov  rax,[rbx]           ; control block vtable   <-- WE HOOK HERE
 *      8B06CD  mov  rcx,rbx
 *      8B06D0  call [rax]               ; _Destroy()             <-- FAULTED
 *      8B06D2  lock xadd [rbx+0xc],esi  ; weak--
 *      8B06DA  jne  8B06E5
 *      8B06E2  call [rax+8]             ; _Delete_this()
 *      8B06E5  epilogue
 *
 *  In the dump rax was 0 and rbx was a live, writable address -- the strong
 *  count really did reach 0, and the control block's vtable slot really was
 *  zero. A control block with a NULL vtable has already been destroyed, so
 *  calling through it is a guaranteed access violation while skipping it is
 *  not. We jump to the epilogue instead.
 *
 *  What this DOES NOT do: fix why the block is in that state. This is
 *  containment. It leaks the block (the weak decrement at 8B06D2 is skipped
 *  too, which is deliberate -- 8B06E2 would dereference the same NULL vtable),
 *  and it fires only on a path that was going to crash anyway.
 *
 *  Anchors verified against the shipping exe: the 6 bytes at 0x8B06CA are
 *  48 8B 03 48 8B CB, and NO branch anywhere in .text targets bytes 1..5 of
 *  them, so stealing 6 for an E9 is safe.
 * ===================================================================== */
#define TEARDOWN_RVA      0x8B06CA
#define TEARDOWN_RESUME   0x8B06D0   /* re-enter the original call     */
#define TEARDOWN_SKIP     0x8B06E5   /* the epilogue                   */


/* ---- the same release, inlined a second time -------------------------
   exe+0x33A577 is the identical MSVC _Ref_count_base release, at another
   inlining:

       33A577  lock xadd [rbx+8],eax    ; strong--
       33A57C  cmp  eax,1
       33A57F  jne  33A59C              ; not the last -> epilogue
       33A581  mov  rax,[rbx]           ; the control block's vtable  <-- HOOK
       33A584  mov  rcx,rbx
       33A587  call [rax]               ; _Destroy()                  <-- FAULT
       33A589  lock xadd [rbx+0xc],edi  ; weak--
       33A59C  epilogue

   2026-09-03: crashed on the maintainer's machine, `reading from 0x0` at
   33A587, at the end of an online match on reaching the rematch menu. The
   faulting instruction is byte-identical to the guarded 0x8B06D0 apart from
   one ModRM register field -- 73 vs 7b, esi vs edi -- which is why the first
   guard never covered it:

       8B06D0  ff 10 f0 0f c1 73 0c 83
       33A587  ff 10 f0 0f c1 7b 0c 83

   That makes three known copies of this release: 0x8B06D0, 0x8CDD5F and this
   one. If a fourth exists the tell is the same, and cheap to check against any
   dump: `call [rax]` with rax zero, reached through `lock xadd [rbx+8]`.

   Unlike the 0x8B06CA site, this one has actually fired -- it is the only one
   of the three observed here -- so it gets its own counter rather than sharing
   g_td_saves. That separation is what let REFREL's note say 0x8B06CA has never
   fired in any log.

   Anchors verified against the shipping exe: the 6 bytes at 0x33A581 are
   48 8B 03 48 8B CB, 0x33A59C is the epilogue (mov rdi,[rsp+0x30];
   add rsp,0x20; pop rbx), and NO branch anywhere in .text targets bytes 1..5
   of them, so stealing 6 for an E9 is safe.  */
#define TEARDOWN2_RVA     0x33A581
#define TEARDOWN2_RESUME  0x33A587   /* re-enter the original call     */
#define TEARDOWN2_SKIP    0x33A59C   /* the epilogue                   */


/* ---- shared_ptr release through a dead control block -----------------
   exe+0x8CDD59 is the release sequence of an MSVC _Ref_count_base:

       8CDD59  mov  rax,[rdi]          ; the control block's vtable
       8CDD5C  mov  rcx,rdi
       8CDD5F  call [rax]              ; _Destroy()          <-- FAULT
       8CDD61  mov  eax,-1
       8CDD66  lock xadd [rdi+0xc],eax ; weak count--
       8CDD6B  cmp  eax,1
       8CDD6E  jne  8CDD7A
       8CDD70  mov  rcx,[rbp-0x51]
       8CDD74  mov  rax,[rcx]
       8CDD77  call [rax+8]            ; _Delete_this()
       8CDD7A  ...                     ; the loop continues here

   A tester hit `reading from 0x0` at 8CDD5F twice in one evening on the
   current build: [rdi] is zero, so the control block has already been freed
   and its memory zeroed. This is the same shape as the guarded 0x8B06D0 and,
   unlike that one, it does reproduce -- 0x8B06CA has never fired in any log.

   Not tint-related, and that is measured rather than assumed: the same site
   crashed him while the tint was disabled, and crashes of this family predate
   the tint by four days.

   The guard skips to 8CDD7A, not merely past the call. Letting the sequence
   continue would run `lock xadd [rdi+0xc]` -- a read-modify-write into freed
   memory -- and then possibly `call [rax+8]` through the same dead vtable. If
   the block is gone there is nothing left to release, so the only correct move
   is to leave the whole release alone and carry on with the loop.

   Containment, not a cure: it stops the crash and does not explain why a
   control block reaches this state. The count rides in the 30-second stats
   line so "it fires constantly" cannot go unnoticed.

   Generic code, so the blast radius is the whole game -- same as the existing
   teardown guard. It only diverges on a state that is already fatal. */
#define REFREL_RVA      0x8CDD59
#define REFREL_RESUME   0x8CDD5F   /* the call, once the vtable is known good */
#define REFREL_SKIP     0x8CDD7A   /* the loop, release abandoned             */

static void patch_refrelease_guard(void)
{
    static const unsigned char orig[6] = {0x48,0x8B,0x07,0x48,0x8B,0xCF};
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char *site, *stub, b[64];
    int n = 0, jz;
    long long rel;
    DWORD old;

    if (!mod) return;
    site = mod + REFREL_RVA;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        crashlog_note_site("REFREL", REFREL_RVA, REFREL_RVA,
                       "shared_ptr release with a NULL control-block vtable", 0);
        log_line("REFREL: bytes not at expected RVA 0x%X (game updated?) -- skipped",
                 REFREL_RVA);
        return;
    }
    stub = (unsigned char*)gauge_alloc_near(site, 128);
    if (!stub) { log_line("REFREL: no trampoline within +/-2GB -- skipped"); return; }

    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x07;          /* mov  rax,[rdi]      */
    b[n++]=0x48; b[n++]=0x85; b[n++]=0xC0;          /* test rax,rax        */
    jz = n; b[n++]=0x74; b[n++]=0x00;               /* jz   -> skip        */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0xCF;          /* mov  rcx,rdi        */
    b[n++]=0xE9;                                    /* jmp  resume         */
    rel = (long long)(mod + REFREL_RESUME) - (long long)(stub + n + 4);
    memcpy(b + n, &rel, 4); n += 4;

    b[jz + 1] = (unsigned char)(n - (jz + 2));
    b[n++]=0xFF; b[n++]=0x05;                       /* inc dword [rip+d]   */
    rel = (long long)&g_rr_saves - (long long)(stub + n + 4);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) n -= 2;   /* out of reach */
    else { memcpy(b + n, &rel, 4); n += 4; }
    b[n++]=0xE9;                                    /* jmp  skip           */
    rel = (long long)(mod + REFREL_SKIP) - (long long)(stub + n + 4);
    memcpy(b + n, &rel, 4); n += 4;

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);

    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("REFREL: trampoline out of rel32 range -- skipped"); return;
    }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("REFREL: VirtualProtect failed at RVA 0x%X", REFREL_RVA); return;
    }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    site[5] = 0x90;
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));
    crashlog_note_site("REFREL", REFREL_RVA, REFREL_RVA,
                       "shared_ptr release with a NULL control-block vtable", 1);
    log_line("REFREL: guard installed at RVA 0x%X -- a shared_ptr release whose "
             "control block has a NULL vtable now skips the whole release instead "
             "of faulting at 0x%X. Reproduced twice on 2026-08-31; containment "
             "only, the reason a control block reaches that state is still open.",
             REFREL_RVA, REFREL_RESUME);
}

/* =====================================================================
 *  UIPLAY GUARD  --  exe+0x1FE4B0, "play a named UI state"
 * ---------------------------------------------------------------------
 *  2026-09-03, from a partner's crash in an online MIRROR Byakuya match,
 *  15 s after both controllers initialised, on pressing SIG in base form.
 *  The register dump added the same morning is what made it readable:
 *
 *      exe+0x22797D  mov  rax,[rcx]              ; rax = *(this+0x490)
 *      exe+0x227980  call qword ptr [rax+0xF0]   <- access violation
 *      this = exe+0x141E070
 *
 *  exe+0x141E070 is in .rdata and the qwords there are all .text pointers
 *  (0x8B1A0, 0x92120, 0x97FD0, 0x92300) -- it is a shared_ptr control block
 *  VTABLE being used as an object. One indirection off. It is also, minus
 *  the image base, exactly the value the handle guard has been catching:
 *  00007FF7A3F4E070 and 00007FF70BE3E070 are both exe+0x141E070. So the
 *  "reason a control block reaches that state", open since that guard was
 *  written, at least has a name now -- the field holds a vtable address.
 *
 *  THE CHAIN, straight off the stack scan:
 *
 *      exe+0x20FC45  call 0x92790        the shared_ptr copy we already guard
 *      exe+0x20FC57  call 0x1FE4B0       play state "on"
 *      exe+0x1FE4CD  mov rax,[rcx+0x40]   ; the CONTROL BLOCK   -- tested
 *      exe+0x1FE4D6  cmp dword [rax+8],0  ; its refcount        -- tested
 *      exe+0x1FE4DC  mov rcx,[rcx+0x20]   ; the OBJECT          -- NOT tested
 *      exe+0x1FE4E0  call 0x1CC2D0       the name-hash lookup
 *      exe+0x1FE4F9  call 0x2278B0       hash the name, then the virtual call
 *
 *  The engine validates the handle and then dereferences a DIFFERENT field.
 *  Our handle guard judges +0x40 too, so it could never have caught this --
 *  and it did not: the crashing session logged `guard neutralised 0`.
 *
 *  WHY HERE AND NOT AT THE FAULT
 *  Every path funnels through 0x1FE4B0. The gauge's own show/hide -- vtable
 *  slot 33, exe+0x2085F0, playing "loop1" -- reaches it by the identical
 *  sequence, and so does the "on" that actually died. One test covers all
 *  three +0x20 dereferences in the function.
 *
 *  WHAT IT DOES, AND WHAT IT DOES NOT
 *  It READS +0x20 and, if it points into the exe image, takes the bail the
 *  engine already has at 0x1FE548 -- which still runs the `lock xadd` that
 *  releases the reference this function owns, so nothing leaks. It writes
 *  nothing. That is deliberate: the handle guard's +0x40 blanking writes to
 *  a live object somebody else owns, and firing it on a valid handle cost
 *  this project a crash on 2026-09-01.
 *
 *  Containment only. It stops the process dying; what puts a vtable address
 *  in +0x20 is still unknown.
 *
 *  SHARED SITE. 0x1FE4B0 serves every character's UI, not Byakuya's.
 *  Approved by Nilsix on 2026-09-03 for exactly that reason: the crash is
 *  reachable from any UI state change, and the guard only ever diverges on
 *  a pointer that would have faulted one call later.
 * ===================================================================== */
#define UIPLAY_RVA      0x1FE4DC   /* mov rcx,[rcx+0x20]; call 0x1CC2D0 */
#define UIPLAY_RESUME   0x1FE4E5   /* after the stolen call             */
#define UIPLAY_BAIL     0x1FE548   /* the engine's own release-and-exit */
#define UIPLAY_TARGET   0x1CC2D0   /* the stolen call's callee          */

/* The count, read back from the trampoline's data slots. Zero until the guard
   is installed, and zero if it never fired. */
static unsigned long long uiplay_saves(void)
{
    return g_up_slots ? g_up_slots[UP_SLOT_COUNT] : 0ULL;
}

/* Print what the guard caught, once per stats window and only while the number
   is still moving. The name is only dereferenced when it points inside the exe
   image -- it is a .rdata literal in every path we have seen, and a pointer
   that failed that test is exactly the kind of thing this guard exists for. */
static void uiplay_report(void)
{
    static unsigned long long seen = 0;
    unsigned long long now, ptr, hnd, nm;
    unsigned char* mod;
    const char* name = "<not in the image>";
    const char* why;

    if (!g_up_slots) return;
    now = g_up_slots[UP_SLOT_COUNT];
    if (now == seen) return;
    seen = now;
    ptr = g_up_slots[UP_SLOT_PTR];
    hnd = g_up_slots[UP_SLOT_HANDLE];
    nm  = g_up_slots[UP_SLOT_NAME];
    mod = (unsigned char*)GetModuleHandleA(NULL);
    if (mod && nm >= (unsigned long long)(uintptr_t)mod
            && nm <  (unsigned long long)(uintptr_t)mod + 0x2000000ULL)
        name = (const char*)(uintptr_t)nm;
    /* Say WHICH rule rejected it, in the same order the stub tests them. The
       two crashes on record fail different ones -- 2026-09-03 was an image
       address, 2026-09-04 was non-canonical -- and knowing which is what tells
       the two apart in a log. */
    if (ptr >> 47)                                          why = "non-canonical";
    else if (ptr & 7)                                       why = "misaligned";
    else if (ptr < 0x100000ULL)                             why = "below the first page";
    else                                                    why = "inside the exe image";
    log_line("UIPLAY/caught: %llu so far -- object %016llX (%s), handle %016llX,"
             " state '%s'. A real object is none of those, so the lookup at"
             " 0x1CC2D0 would have run on garbage and the compare at 0x1CC33C"
             " faulted.",
             now, ptr, why, hnd, name);
}

static void patch_uiplay_guard(void)
{
    static const unsigned char orig[9] =
        {0x48,0x8B,0x49,0x20,0xE8,0xEB,0xDD,0xFC,0xFF};
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    unsigned char* stub;
    unsigned char* data;
    unsigned char  b[160];
    unsigned long long lo, hi;
    int n = 0, jb_at, jae_at, i, nbad = 0, bad_at[8], ok_at;
    long long rel;
    DWORD old;

    if (!mod) return;
    site = mod + UIPLAY_RVA;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        crashlog_note_site("UIPLAY", UIPLAY_RVA, UIPLAY_RVA,
                       "UI state change through an object pointing into the exe image", 0);
        log_line("UIPLAY: bytes not at expected RVA 0x%X (game updated?) -- skipped",
                 UIPLAY_RVA);
        return;
    }
    stub = (unsigned char*)gauge_alloc_near(site, 256);
    if (!stub) { log_line("UIPLAY: no trampoline within +/-2GB -- skipped"); return; }
    data = stub + 0xC0;                       /* past the code, same page */
    memset(data, 0, 32);
    g_up_slots = (volatile unsigned long long*)data;

    lo = (unsigned long long)(uintptr_t)mod;
    hi = lo + 0x2000000ULL;

    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x49; b[n++]=0x20;   /* mov rcx,[rcx+0x20] */
    /* r10/r11 are volatile and dead here: the function uses rax, rbx, rsi,
       rdi and rcx only, and the call below would clobber them anyway.

       The four rules are the handle guard's, not new ones. That guard has
       tested exactly these since it was written, and the first of them --
       non-canonical -- is what this site needed: on 2026-09-04 the object
       arriving here was C004598000000002, three minutes after the handle
       guard caught cb=C004718000000002 in the same session. Same shape, same
       garbage. The image rule alone let it through, because a non-canonical
       value is not in the image. */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0xD1;                /* mov  r10,rcx       */
    b[n++]=0x49; b[n++]=0xC1; b[n++]=0xEA; b[n++]=0x2F;   /* shr  r10,47        */
    bad_at[nbad++] = n; b[n++]=0x75; b[n++]=0x00;         /* jnz  -> bad        */
    b[n++]=0xF6; b[n++]=0xC1; b[n++]=0x07;                /* test cl,7          */
    bad_at[nbad++] = n; b[n++]=0x75; b[n++]=0x00;         /* jnz  -> bad        */
    b[n++]=0x48; b[n++]=0x81; b[n++]=0xF9;                /* cmp  rcx,0x100000  */
    { unsigned int page = 0x100000; memcpy(b+n,&page,4); n+=4; }
    bad_at[nbad++] = n; b[n++]=0x72; b[n++]=0x00;         /* jb   -> bad        */
    b[n++]=0x49; b[n++]=0xBA; memcpy(b+n,&lo,8); n+=8;    /* mov  r10,imagebase */
    b[n++]=0x4C; b[n++]=0x39; b[n++]=0xD1;                /* cmp  rcx,r10       */
    jb_at = n; b[n++]=0x72; b[n++]=0x00;                  /* jb   -> ok         */
    b[n++]=0x49; b[n++]=0xBB; memcpy(b+n,&hi,8); n+=8;    /* mov  r11,base+32MB */
    b[n++]=0x4C; b[n++]=0x39; b[n++]=0xD9;                /* cmp  rcx,r11       */
    bad_at[nbad++] = n; b[n++]=0x72; b[n++]=0x00;         /* jb   -> bad        */
    jae_at = n; b[n++]=0xEB; b[n++]=0x00;                 /* jmp  -> ok         */
    /* ok: the pointer passed all four rules -- run the stolen call and rejoin */
    ok_at = n;
    b[jb_at  + 1] = (unsigned char)(n - (jb_at  + 2));
    b[jae_at + 1] = (unsigned char)(n - (jae_at + 2));
    b[n++]=0xE8;                                          /* call 0x1CC2D0      */
    rel = (long long)(mod + UIPLAY_TARGET) - (long long)(stub + n + 4);
    memcpy(b+n,&rel,4); n += 4;
    b[n++]=0xE9;                                          /* jmp resume         */
    rel = (long long)(mod + UIPLAY_RESUME) - (long long)(stub + n + 4);
    memcpy(b+n,&rel,4); n += 4;

    /* bad: record WHAT it was before bailing. A counter alone says the guard
       fired and nothing about the thing it caught, and this crash will only be
       understood from the values. rcx is the bogus object, rbx the handle it
       came out of, rdi the UI state name this call was about to play. Then take
       the engine's own release-and-return: rax still holds the control block,
       which is what 0x1FE548 expects. */
    for (i = 0; i < nbad; i++)
        b[bad_at[i] + 1] = (unsigned char)(n - (bad_at[i] + 2));
    b[n++]=0x48; b[n++]=0xFF; b[n++]=0x05;                /* inc qword [rip+d]  */
    rel = (long long)(data + UP_SLOT_COUNT*8) - (long long)(stub + n + 4);
    memcpy(b+n,&rel,4); n += 4;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x0D;                /* mov [rip+d],rcx    */
    rel = (long long)(data + UP_SLOT_PTR*8) - (long long)(stub + n + 4);
    memcpy(b+n,&rel,4); n += 4;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x1D;                /* mov [rip+d],rbx    */
    rel = (long long)(data + UP_SLOT_HANDLE*8) - (long long)(stub + n + 4);
    memcpy(b+n,&rel,4); n += 4;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x3D;                /* mov [rip+d],rdi    */
    rel = (long long)(data + UP_SLOT_NAME*8) - (long long)(stub + n + 4);
    memcpy(b+n,&rel,4); n += 4;
    b[n++]=0xE9;                                          /* jmp bail           */
    rel = (long long)(mod + UIPLAY_BAIL) - (long long)(stub + n + 4);
    memcpy(b+n,&rel,4); n += 4;
    (void)ok_at;

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);

    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("UIPLAY: trampoline out of rel32 range -- skipped"); return;
    }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("UIPLAY: VirtualProtect failed at RVA 0x%X", UIPLAY_RVA); return;
    }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    for (i = 5; i < (int)sizeof(orig); i++) site[i] = 0x90;
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));
    crashlog_note_site("UIPLAY", UIPLAY_RVA, UIPLAY_RVA,
                       "UI state change through an object pointing into the exe image", 1);
    log_line("UIPLAY: guard installed at RVA 0x%X -- a UI state change whose object "
             "at +0x20 fails any of the handle guard's four rules (non-canonical, "
             "misaligned, below the first page, inside the exe image) now takes the "
             "engine's own bail at 0x%X. The reference is still released. Two crash "
             "sites are covered: 0x227980 and 0x1CC33C. Containment only -- what "
             "writes garbage into +0x20 is still unknown.",
             UIPLAY_RVA, UIPLAY_BAIL);
}

/* =====================================================================
 *  LOOKUP GUARD  --  exe+0x1CC2D0, "does this node play that named animation"
 * ---------------------------------------------------------------------
 *  The UIPLAY guard at 0x1FE4DC was right about the field and wrong about the
 *  reach. On 2026-09-04, in a self-hosted online mirror, it caught one bogus
 *  object on one client -- object 00007FF74F8DE2C0, inside the exe image,
 *  state "on" -- and the OTHER client still died at exe+0x1CC33C, because that
 *  call came in through a different caller:
 *
 *      exe+0x20FC91  mov rcx,[rax+0x20]   ; the object -- NOT tested
 *      exe+0x20FC95  call 0x1401cc2d0
 *      exe+0x20FC9A  test al,al
 *
 *  Byte for byte the same mistake as 0x1FE4B0: validate the control block at
 *  +0x40 and its refcount, then dereference +0x20 unchecked. It is an idiom in
 *  this codebase, not a one-off, so guarding callers one at a time is a losing
 *  game -- there is no way to know how many more there are.
 *
 *  So this one sits at the callee's own entry and every caller is covered at
 *  once. rcx is the object; the four rules are the handle guard's, unchanged.
 *
 *  RETURNING 0 IS SAFE HERE, and that is why the guard can live at this site.
 *  The function answers a yes/no question -- "is this the animation playing" --
 *  and 0x20FC9A does `test al,al` with a real branch for 0. It is a normal
 *  answer, not an error path.
 *
 *  ⚠ It does NOT replace the 0x1FE4DC guard. On that caller a 0 sends the code
 *  to 0x1FE4F2, which calls 0x2278B0 with the same bad object and faults at
 *  0x227980 instead -- the partner's crash. The two compose: 0x1FE4DC bails
 *  its caller before the call, this one catches everyone else.
 *
 *  Six bytes are stolen -- `push rbx` here is 40 53, with a redundant REX, so
 *  the prologue is 6 and not 5.
 * ===================================================================== */
#define LOOKUP_RVA     0x1CC2D0
#define LOOKUP_RESUME  0x1CC2D6

static void patch_lookup_guard(void)
{
    static const unsigned char orig[6] = {0x40,0x53,0x48,0x83,0xEC,0x20};
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    unsigned char* stub;
    unsigned char* data;
    unsigned char  b[160];
    unsigned long long lo, hi;
    int n = 0, i, nbad = 0, bad_at[8], jb_at, jmp_at;
    long long rel;
    DWORD old;

    if (!mod) return;
    site = mod + LOOKUP_RVA;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        crashlog_note_site("LOOKUP", LOOKUP_RVA, LOOKUP_RESUME,
                           "UI state name lookup on a bogus object", 0);
        log_line("LOOKUP: bytes not at expected RVA 0x%X (game updated?) -- skipped",
                 LOOKUP_RVA);
        return;
    }
    stub = (unsigned char*)gauge_alloc_near(site, 256);
    if (!stub) { log_line("LOOKUP: no trampoline within +/-2GB -- skipped"); return; }
    data = stub + 0xC0;
    memset(data, 0, 64);
    g_lk_slots = (volatile unsigned long long*)data;

    lo = (unsigned long long)(uintptr_t)mod;
    hi = lo + 0x2000000ULL;

    /* r10/r11 are dead here: the function sets them itself at 0x1CC2D6 and
       0x1CC2D9, both after the bytes we stole. */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0xD1;                /* mov  r10,rcx       */
    b[n++]=0x49; b[n++]=0xC1; b[n++]=0xEA; b[n++]=0x2F;   /* shr  r10,47        */
    bad_at[nbad++] = n; b[n++]=0x75; b[n++]=0x00;         /* jnz  -> bad        */
    b[n++]=0xF6; b[n++]=0xC1; b[n++]=0x07;                /* test cl,7          */
    bad_at[nbad++] = n; b[n++]=0x75; b[n++]=0x00;         /* jnz  -> bad        */
    b[n++]=0x48; b[n++]=0x81; b[n++]=0xF9;                /* cmp  rcx,0x100000  */
    { unsigned int page = 0x100000; memcpy(b+n,&page,4); n+=4; }
    bad_at[nbad++] = n; b[n++]=0x72; b[n++]=0x00;         /* jb   -> bad        */
    b[n++]=0x49; b[n++]=0xBA; memcpy(b+n,&lo,8); n+=8;    /* mov  r10,imagebase */
    b[n++]=0x4C; b[n++]=0x39; b[n++]=0xD1;                /* cmp  rcx,r10       */
    jb_at = n; b[n++]=0x72; b[n++]=0x00;                  /* jb   -> ok         */
    b[n++]=0x49; b[n++]=0xBB; memcpy(b+n,&hi,8); n+=8;    /* mov  r11,base+32MB */
    b[n++]=0x4C; b[n++]=0x39; b[n++]=0xD9;                /* cmp  rcx,r11       */
    bad_at[nbad++] = n; b[n++]=0x72; b[n++]=0x00;         /* jb   -> bad        */
    jmp_at = n; b[n++]=0xEB; b[n++]=0x00;                 /* jmp  -> ok         */

    /* ok: run the stolen prologue, then rejoin the function */
    b[jb_at  + 1] = (unsigned char)(n - (jb_at  + 2));
    b[jmp_at + 1] = (unsigned char)(n - (jmp_at + 2));

    /* ---- and record what PASSED, which is the half that was missing -------
       2026-09-07, boxed client of a mirror match: the client died INSIDE this
       function, at 0x1CC33C, reading [rax+0x38] where rax was 1C35451B1F0.
       That pointer is canonical, 8-aligned, above the first page and outside
       the image -- it passes all four rules at this door without argument. It
       is an ordinary heap address whose page no longer exists.

       So the object was not malformed, it was FREED, and no test of a
       pointer's shape can ever catch that. Eight guards have each moved the
       fault one use further along for exactly this reason.

       Slots 0..2 hold what was REFUSED. These three hold what was let
       through, so a crash report can answer the one question the refusals
       cannot: was the corpse already at this door, and how recently. If the
       faulting rax equals slot 4, it died between here and 0x1CC33C -- inside
       one call. If it does not, it was cached somewhere upstream and died
       earlier, which points at a different owner entirely.

       Three stores and an increment. No branch, no call, no flow change:
       whatever the game did before this line, it still does. */
    b[n++]=0x48; b[n++]=0xFF; b[n++]=0x05;                /* inc qword [rip+d]  */
    { long long r = (long long)(data + 24) - (long long)(stub + n + 4);
      memcpy(b+n,&r,4); n += 4; }
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x0D;                /* mov [rip+d],rcx    */
    { long long r = (long long)(data + 32) - (long long)(stub + n + 4);
      memcpy(b+n,&r,4); n += 4; }
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x15;                /* mov [rip+d],rdx    */
    { long long r = (long long)(data + 40) - (long long)(stub + n + 4);
      memcpy(b+n,&r,4); n += 4; }

    memcpy(b + n, orig, sizeof(orig)); n += (int)sizeof(orig);
    b[n++]=0xE9;                                          /* jmp resume         */
    rel = (long long)(mod + LOOKUP_RESUME) - (long long)(stub + n + 4);
    memcpy(b+n,&rel,4); n += 4;

    /* bad: record it and answer "no". rdx is the name string at entry. The
       stack is untouched -- we detoured the very first instruction -- so a
       plain ret goes straight back to the caller. */
    for (i = 0; i < nbad; i++)
        b[bad_at[i] + 1] = (unsigned char)(n - (bad_at[i] + 2));
    b[n++]=0x48; b[n++]=0xFF; b[n++]=0x05;                /* inc qword [rip+d]  */
    rel = (long long)(data + 0) - (long long)(stub + n + 4);
    memcpy(b+n,&rel,4); n += 4;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x0D;                /* mov [rip+d],rcx    */
    rel = (long long)(data + 8) - (long long)(stub + n + 4);
    memcpy(b+n,&rel,4); n += 4;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x15;                /* mov [rip+d],rdx    */
    rel = (long long)(data + 16) - (long long)(stub + n + 4);
    memcpy(b+n,&rel,4); n += 4;
    b[n++]=0x31; b[n++]=0xC0;                             /* xor eax,eax        */
    b[n++]=0xC3;                                          /* ret                */

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);

    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("LOOKUP: trampoline out of rel32 range -- skipped"); return;
    }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("LOOKUP: VirtualProtect failed at RVA 0x%X", LOOKUP_RVA); return;
    }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    for (i = 5; i < (int)sizeof(orig); i++) site[i] = 0x90;
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));
    crashlog_note_site("LOOKUP", LOOKUP_RVA, LOOKUP_RESUME,
                       "UI state name lookup on a bogus object", 1);
    log_line("LOOKUP: guard installed at RVA 0x%X -- the name lookup now answers 'no' "
             "instead of dereferencing an object that fails the handle guard's four "
             "rules. Covers EVERY caller, which 0x1FE4DC could not: 0x20FC95 reaches "
             "it by the same unchecked +0x20 and killed a client at 0x1CC33C on "
             "2026-09-04.", LOOKUP_RVA);
}

static unsigned long long lookup_saves(void)
{
    return g_lk_slots ? g_lk_slots[0] : 0ULL;
}

/* The last object this door let through, printed next to the register file so
   the faulting pointer can be compared with it without a second run. */
static void lookup_live_report(void)
{
    unsigned long long n, obj, nm;
    if (!g_lk_slots) return;
    n   = g_lk_slots[3];
    obj = g_lk_slots[4];
    nm  = g_lk_slots[5];
    if (!n) { log_line("LOOKUP/live: never called with a sound object"); return; }
    log_line("LOOKUP/live: %llu call(s) passed the door; last object %016llX,"
             " name %016llX -- compare with the faulting pointer above: the same"
             " value means it died inside one call, a different one means it was"
             " held somewhere upstream", n, obj, nm);
}

static void lookup_report(void)
{
    static unsigned long long seen = 0;
    unsigned long long now, ptr, nm;
    unsigned char* mod;
    const char* name = "<not in the image>";
    const char* why;

    if (!g_lk_slots) return;
    now = g_lk_slots[0];
    if (now == seen) return;
    seen = now;
    ptr = g_lk_slots[1];
    nm  = g_lk_slots[2];
    mod = (unsigned char*)GetModuleHandleA(NULL);
    if (mod && nm >= (unsigned long long)(uintptr_t)mod
            && nm <  (unsigned long long)(uintptr_t)mod + 0x2000000ULL)
        name = (const char*)(uintptr_t)nm;
    if (ptr >> 47)               why = "non-canonical";
    else if (ptr & 7)            why = "misaligned";
    else if (ptr < 0x100000ULL)  why = "below the first page";
    else                         why = "inside the exe image";
    log_line("LOOKUP/caught: %llu so far -- object %016llX (%s), name '%s'. Answered"
             " 'no' instead of faulting at 0x1CC33C.", now, ptr, why, name);
}

/* =====================================================================
 *  VCALL GUARD  --  exe+0x227980, the virtual call that keeps killing clients
 * ---------------------------------------------------------------------
 *  This is the third guard on one chain, and the first that sits on the
 *  faulting instruction itself. The two before it test a POINTER; this crash
 *  proved that is not enough.
 *
 *  2026-09-04, self-hosted online mirror, host client:
 *
 *      exe+0x22797D  mov  rax,[rcx]            ; rcx = object + 0x490
 *      exe+0x227980  call qword ptr [rax+0xF0] <- access violation
 *      rdi = 0000019D8F8C50C0   the object: heap, aligned, outside the image
 *      rax = 8003EC0078000000   what it points to: non-canonical
 *
 *  The object passed all four of the handle guard's rules, and rightly so --
 *  it is a perfectly plausible heap pointer. What is rotten is its CONTENTS.
 *  No test on the pointer can catch that, which is why UIPLAY at 0x1FE4DC did
 *  not fire even though this call came in through exactly its caller
 *  (0x20FC5C -> 0x1FE4B0 -> 0x1FE4F9 -> 0x2278B0 -> 0x227940).
 *
 *  So the test moves to the value actually dereferenced: rax, the vptr.
 *
 *  THREE RULES, NOT FOUR. rax is a vtable pointer, so it BELONGS in the image
 *  -- the fourth rule is inverted here and must not be applied. Non-canonical,
 *  misaligned and below-the-first-page remain, and the first is what the
 *  observed value fails.
 *
 *  On a bad vptr the guard takes 0x227999, which is the engine's own path for
 *  "the call returned non-zero". That skips the block at 0x22798A and nothing
 *  else -- the conservative branch of a decision the engine already makes.
 * ===================================================================== */
#define VCALL_RVA     0x22797D
#define VCALL_RESUME  0x227986   /* test al,al -- after the stolen call      */
#define VCALL_SKIP    0x227999   /* the engine's own "non-zero" destination  */

static void patch_vcall_guard(void)
{
    static const unsigned char orig[9] =
        {0x48,0x8B,0x01,0xFF,0x90,0xF0,0x00,0x00,0x00};
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    unsigned char* stub;
    unsigned char* data;
    unsigned char  b[224];
    unsigned long long lo, hi;
    int n = 0, i, nbad = 0, bad_at[8];
    long long rel;
    DWORD old;

    if (!mod) return;
    lo = (unsigned long long)(uintptr_t)mod;
    hi = lo + 0x2000000ULL;
    site = mod + VCALL_RVA;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        crashlog_note_site("VCALL", VCALL_RVA, VCALL_RESUME,
                           "virtual call through a vptr outside the image", 0);
        log_line("VCALL: bytes not at expected RVA 0x%X (game updated?) -- skipped",
                 VCALL_RVA);
        return;
    }
    stub = (unsigned char*)gauge_alloc_near(site, 256);
    if (!stub) { log_line("VCALL: no trampoline within +/-2GB -- skipped"); return; }
    data = stub + 0xC0;
    memset(data, 0, 32);
    g_vc_slots = (volatile unsigned long long*)data;

    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x01;                /* mov  rax,[rcx]     */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0xD0;                /* mov  r10,rax       */
    b[n++]=0x49; b[n++]=0xC1; b[n++]=0xEA; b[n++]=0x2F;   /* shr  r10,47        */
    bad_at[nbad++] = n; b[n++]=0x75; b[n++]=0x00;         /* jnz  -> bad        */
    b[n++]=0xA8; b[n++]=0x07;                             /* test al,7          */
    bad_at[nbad++] = n; b[n++]=0x75; b[n++]=0x00;         /* jnz  -> bad        */
    b[n++]=0x48; b[n++]=0x3D;                             /* cmp  rax,0x100000  */
    { unsigned int page = 0x100000; memcpy(b+n,&page,4); n+=4; }
    bad_at[nbad++] = n; b[n++]=0x72; b[n++]=0x00;         /* jb   -> bad        */
    /* ★ 2026-09-05, and it corrects this guard's own comment. It said "three
       rules, not four, because a vptr belongs IN the image" -- and then dropped
       the image test instead of INVERTING it. The right rule is the opposite of
       the handle guard's: a vptr must be inside the image, not outside it.
    
       The VFN probe made the invariant visible. Across six healthy calls, on
       both clients, *(this+0x490) was ALWAYS the same value: 00007FF63BEAAA18,
       a vtable in the image. On the call that killed the sandboxed client it
       was 0000022201B14920 -- a heap address. The memory had been freed and
       reallocated for something else, and 0x227940 ran on it anyway. The fault
       was `executing 0x0`, because [rax+0xF0] of a stranger's object is not a
       function pointer.
    
       The three rules above could never catch that: a heap pointer is
       canonical, aligned and far past the first page. */
    b[n++]=0x49; b[n++]=0xBA; { unsigned long long v = lo; memcpy(b+n,&v,8); } n+=8; /* mov r10,base */
    b[n++]=0x4C; b[n++]=0x39; b[n++]=0xD0;                /* cmp  rax,r10       */
    bad_at[nbad++] = n; b[n++]=0x72; b[n++]=0x00;         /* jb   -> bad        */
    b[n++]=0x49; b[n++]=0xBB; { unsigned long long v = hi; memcpy(b+n,&v,8); } n+=8; /* mov r11,base+32M */
    b[n++]=0x4C; b[n++]=0x39; b[n++]=0xD8;                /* cmp  rax,r11       */
    bad_at[nbad++] = n; b[n++]=0x73; b[n++]=0x00;         /* jae  -> bad        */
    /* ok: make the call the engine wanted, then rejoin at the test */
    b[n++]=0xFF; b[n++]=0x90;                             /* call [rax+0xF0]    */
    { unsigned int off = 0xF0; memcpy(b+n,&off,4); n+=4; }
    b[n++]=0xE9;                                          /* jmp resume         */
    rel = (long long)(mod + VCALL_RESUME) - (long long)(stub + n + 4);
    memcpy(b+n,&rel,4); n += 4;
    /* bad: record the vptr, then take the engine's own non-zero path */
    for (i = 0; i < nbad; i++)
        b[bad_at[i] + 1] = (unsigned char)(n - (bad_at[i] + 2));
    b[n++]=0x48; b[n++]=0xFF; b[n++]=0x05;                /* inc qword [rip+d]  */
    rel = (long long)(data + 0) - (long long)(stub + n + 4);
    memcpy(b+n,&rel,4); n += 4;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x05;                /* mov [rip+d],rax    */
    rel = (long long)(data + 8) - (long long)(stub + n + 4);
    memcpy(b+n,&rel,4); n += 4;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x0D;                /* mov [rip+d],rcx    */
    rel = (long long)(data + 16) - (long long)(stub + n + 4);
    memcpy(b+n,&rel,4); n += 4;
    b[n++]=0xE9;                                          /* jmp skip           */
    rel = (long long)(mod + VCALL_SKIP) - (long long)(stub + n + 4);
    memcpy(b+n,&rel,4); n += 4;

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);

    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("VCALL: trampoline out of rel32 range -- skipped"); return;
    }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("VCALL: VirtualProtect failed at RVA 0x%X", VCALL_RVA); return;
    }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    for (i = 5; i < (int)sizeof(orig); i++) site[i] = 0x90;
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));
    crashlog_note_site("VCALL", VCALL_RVA, VCALL_RESUME,
                       "virtual call through a vptr outside the image", 1);
    log_line("VCALL: guard installed at RVA 0x%X -- the virtual call at 0x227980 is "
             "skipped when the vptr at *(object+0x490) is non-canonical, misaligned or "
             "below the first page. Three rules, not four: a vptr belongs IN the image, "
             "so that rule is inverted here. This is the one the pointer tests cannot "
             "reach -- the object is valid, its contents are not.", VCALL_RVA);
}

static unsigned long long vcall_saves(void)
{
    return g_vc_slots ? g_vc_slots[0] : 0ULL;
}

static void vcall_report(void)
{
    static unsigned long long seen = 0;
    unsigned long long now, vptr, obj;
    const char* why;
    if (!g_vc_slots) return;
    now = g_vc_slots[0];
    if (now == seen) return;
    seen = now;
    vptr = g_vc_slots[1];
    obj  = g_vc_slots[2];
    if (vptr >> 47)               why = "non-canonical";
    else if (vptr & 7)            why = "misaligned";
    else if (vptr < 0x100000ULL)  why = "below the first page";
    else                          why = "OUTSIDE the exe image -- a vtable is never on the heap";
    log_line("VCALL/caught: %llu so far -- vptr %016llX (%s) read from %016llX. The"
             " object was fine and its contents were not, which is why the pointer"
             " guards never saw this one.", now, vptr, why, obj);
}

/* =====================================================================
 *  NULL-VTABLE RELEASE GUARDS  --  one policy, a table of sites
 * ---------------------------------------------------------------------
 *  This exact sequence is emitted all over the binary, and never with a
 *  vtable check:
 *
 *      lock xadd dword ptr [rcx+0xC], eax   ; drop the refcount
 *      cmp  eax, 1
 *      jne  <done>
 *      mov  rax, [rcx]                      ; the control block's vtable
 *      call qword ptr [rax+8]               ; NULL -> reads 0x8
 *
 *  Five copies are on record: 0x8B06CA and 0x33A581 (teardown), 0x8CDD59
 *  (the shared helper), and now 0x1FE55F and 0x20FCCC, both inline in the
 *  UI state-change path and both hit in the 2026-09-04 online mirror.
 *
 *  Writing a bespoke guard per site was the wrong shape once the count passed
 *  four. This is one function and a table: the stolen bytes are identical
 *  everywhere (48 8B 01 FF 50 08), so a new site costs one line.
 *
 *  ⚠ Skipping the release leaks the control block, deliberately and in line
 *  with the three that came before: a leak costs memory, calling through a
 *  NULL vtable costs the process.
 *
 *  ⚠ These are containment. Every value the guards on this chain have caught
 *  was NULL rather than garbage -- an object destroyed while the UI still
 *  held it, not memory scribbled over. The cause is upstream of all five.
 * ===================================================================== */
static unsigned long long refrel2_saves(void)
{
    return g_r2_slots ? g_r2_slots[0] : 0ULL;
}

static int patch_nullvt_release(unsigned int rva, unsigned int resume,
                                const char* label, volatile unsigned long long** slots)
{
    static const unsigned char orig[6] = {0x48,0x8B,0x01,0xFF,0x50,0x08};
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    unsigned char* stub;
    unsigned char* data;
    unsigned char  b[96];
    int n = 0, i, jz_at;
    long long rel;
    DWORD old;

    if (!mod) return 0;
    site = mod + rva;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        crashlog_note_site(label, rva, resume,
                           "release through a NULL vtable", 0);
        log_line("%s: bytes not at expected RVA 0x%X (game updated?) -- skipped",
                 label, rva);
        return 0;
    }
    stub = (unsigned char*)gauge_alloc_near(site, 256);
    if (!stub) { log_line("%s: no trampoline within +/-2GB -- skipped", label); return 0; }
    data = stub + 0xC0;
    memset(data, 0, 16);
    if (slots) *slots = (volatile unsigned long long*)data;

    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x01;                /* mov  rax,[rcx]     */
    b[n++]=0x48; b[n++]=0x85; b[n++]=0xC0;                /* test rax,rax       */
    jz_at = n; b[n++]=0x74; b[n++]=0x00;                  /* jz   -> skip       */
    b[n++]=0xFF; b[n++]=0x50; b[n++]=0x08;                /* call [rax+8]       */
    b[n++]=0xE9;                                          /* jmp  resume        */
    rel = (long long)(mod + resume) - (long long)(stub + n + 4);
    memcpy(b+n,&rel,4); n += 4;
    b[jz_at + 1] = (unsigned char)(n - (jz_at + 2));      /* skip:              */
    b[n++]=0x48; b[n++]=0xFF; b[n++]=0x05;                /* inc qword [rip+d]  */
    rel = (long long)(data + 0) - (long long)(stub + n + 4);
    memcpy(b+n,&rel,4); n += 4;
    b[n++]=0xE9;                                          /* jmp  resume        */
    rel = (long long)(mod + resume) - (long long)(stub + n + 4);
    memcpy(b+n,&rel,4); n += 4;

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);

    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("%s: trampoline out of rel32 range -- skipped", label); return 0;
    }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("%s: VirtualProtect failed at RVA 0x%X", label, rva); return 0;
    }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    for (i = 5; i < (int)sizeof(orig); i++) site[i] = 0x90;
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));
    crashlog_note_site(label, rva, resume,
                       "release through a NULL vtable", 1);
    log_line("%s: guard installed at RVA 0x%X -- a release through a NULL vtable now "
             "continues at 0x%X instead of faulting one instruction later.",
             label, rva, resume);
    return 1;
}

static void patch_refrel2_guard(void)
{
    /* 0x1FE55F: inside 0x1FE4B0, the "play a named UI state" function, on the
       bail our own UIPLAY guard jumps to. Crashed 18:51:16.
       0x20FCCC: inside 0x20F8A0, its caller. Crashed 18:56:47, other client. */
    int ok = 0;
    ok += patch_nullvt_release(0x1FE55F, 0x1FE565, "REFREL2", &g_r2_slots);
    ok += patch_nullvt_release(0x20FCCC, 0x20FCD2, "REFREL3", 0);
    log_line("NULLVT: %d of 2 inline release sites guarded. The idiom appears at least "
             "five times in this binary -- adding another is one line.", ok);
}

/* =====================================================================
 *  VFN PROBE  --  exe+0x227940, the function every crash dies inside
 * ---------------------------------------------------------------------
 *  Not a guard. An instrument, and it exists because of one measurement
 *  nothing else in this project can make.
 *
 *  2026-09-04, self-hosted mirror, two clients on ONE machine playing each
 *  other. At 21:35:36 both received the same stance change -- the first of the
 *  match, in base form. One survived it and logged a healthy node; the other
 *  died at exe+0x2279CB, `cmp byte [rax+0x50]` with rax = [this+0x258] =
 *  8801D500E3DFF366. Same event, same millisecond, two outcomes.
 *
 *  So the difference is in the object, and the object is reachable at the
 *  entry of the function that dies. This records it there, on both clients,
 *  and the fatal call is simply the last one recorded before the crash --
 *  there is no need for a ring buffer.
 *
 *      +0x00  call count
 *      +0x08  this  (rcx at entry)
 *      +0x10  [this+0x258]   faulted at 0x2279CB
 *      +0x18  [this+0x490]   faulted at 0x227980
 *      +0x20  [this+0x6b8]   the field 0x22796C tests first
 *
 *  The member reads are skipped when `this` itself fails the handle guard's
 *  first three rules, so the instrument cannot fault on the pointer it is
 *  measuring. That lesson came from the stance probe two hours earlier, which
 *  printed a form label read from an unassigned variable and sent the whole
 *  investigation at the wrong half of the code.
 *
 *  Seven bytes are stolen: `mov rax,rsp` is 3 and `mov [rax+0x10],rbx` is 4,
 *  and the detour needs 5. They are replayed in the stub before the jump back.
 *  Only r10 is touched, and it is volatile and dead at a function entry.
 * ===================================================================== */
#define VFN_RVA     0x227940
#define VFN_RESUME  0x227947

static void patch_vfn_probe(void)
{
    static const unsigned char orig[7] = {0x48,0x8B,0xC4,0x48,0x89,0x58,0x10};
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    unsigned char* stub;
    unsigned char* data;
    unsigned char  b[256];
    unsigned long long lo, hi;
    int n = 0, i, nbad = 0, bad_at[8], ngate = 0, gate_at[4];
    long long rel;
    DWORD old;

    if (!mod) return;
    lo = (unsigned long long)(uintptr_t)mod;
    hi = lo + 0x2000000ULL;
    site = mod + VFN_RVA;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("VFN: bytes not at expected RVA 0x%X (game updated?) -- skipped",
                 VFN_RVA);
        return;
    }
    stub = (unsigned char*)gauge_alloc_near(site, 256);
    if (!stub) { log_line("VFN: no trampoline within +/-2GB -- skipped"); return; }
    data = stub + 0xC0;
    memset(data, 0, 64);
    g_vfn_slots = (volatile unsigned long long*)data;

    b[n++]=0x48; b[n++]=0xFF; b[n++]=0x05;                /* inc qword [rip+cnt] */
    rel = (long long)(data + 0) - (long long)(stub + n + 4);
    memcpy(b+n,&rel,4); n += 4;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x0D;                /* mov [rip+this],rcx  */
    rel = (long long)(data + 8) - (long long)(stub + n + 4);
    memcpy(b+n,&rel,4); n += 4;
    /* The calling thread, straight out of the TEB at gs:[0x48]. No call, no
       clobber beyond r10. The UI code is not gated on the online mode -- there
       is not one read of SceneGlobalInfo+0x498 anywhere in 0x1C0000..0x240000 --
       so online cannot be taking a different PATH. It can only be changing
       timing, and a bug that appears only at a different cadence, kills one
       client and spares the other on the same event, is a race. Which means the
       thread doing the fatal call is worth knowing, and we have never recorded
       it: the crash lines name a thread id, the working ones never did. */
    b[n++]=0x65; b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x14; b[n++]=0x25;
    { unsigned int teb = 0x48; memcpy(b+n,&teb,4); n += 4; }   /* mov r10,gs:[0x48] */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x15;                /* mov [rip+tid],r10   */
    rel = (long long)(data + 40) - (long long)(stub + n + 4);
    memcpy(b+n,&rel,4); n += 4;

    /* Only read members if `this` can be read at all. */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0xD1;                /* mov  r10,rcx        */
    b[n++]=0x49; b[n++]=0xC1; b[n++]=0xEA; b[n++]=0x2F;   /* shr  r10,47         */
    bad_at[nbad++] = n; b[n++]=0x75; b[n++]=0x00;         /* jnz  -> skip        */
    b[n++]=0xF6; b[n++]=0xC1; b[n++]=0x07;                /* test cl,7           */
    bad_at[nbad++] = n; b[n++]=0x75; b[n++]=0x00;         /* jnz  -> skip        */
    b[n++]=0x48; b[n++]=0x81; b[n++]=0xF9;                /* cmp  rcx,0x100000   */
    { unsigned int page = 0x100000; memcpy(b+n,&page,4); n+=4; }
    bad_at[nbad++] = n; b[n++]=0x72; b[n++]=0x00;         /* jb   -> skip        */

    /* r10 = [rcx+off]; [rip+slot] = r10, three times */
    {
        static const unsigned int offs[3] = { 0x258, 0x490, 0x6B8 };
        int k;
        for (k = 0; k < 3; k++) {
            b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x91;        /* mov r10,[rcx+d32]   */
            memcpy(b+n,&offs[k],4); n += 4;
            b[n++]=0x4C; b[n++]=0x89; b[n++]=0x15;        /* mov [rip+d],r10     */
            rel = (long long)(data + 16 + k*8) - (long long)(stub + n + 4);
            memcpy(b+n,&rel,4); n += 4;
        }
    }
    /* THE GATE. *(this+0x490) is the sub-object's vptr, and it is the one value
       on this chain that has ever held still: six healthy calls across two
       clients all read 00007FF63BEAAA18 there, a vtable in the exe image. The
       two fatal calls read 0000022201B14920 and 0000002000000002.

       Guarding single dereferences has failed seven times. Each guard moves the
       fault to the next use of the same corpse -- the last was a strlen at
       0x9D26F7, sixteen instructions past a virtual call our own new rule had
       just correctly prevented. So the whole function is refused instead, which
       is the level the evidence supports: the object is dead, and nothing
       0x227940 does with it is worth doing.

       Returning 0 is safe. 0x2278B0 hands the result straight up and 0x1FE4B0
       ignores it, so the UI state change simply does not happen. */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x91;                /* mov r10,[rcx+0x490] */
    { unsigned int off = 0x490; memcpy(b+n,&off,4); n += 4; }
    b[n++]=0x49; b[n++]=0xBB; memcpy(b+n,&lo,8); n += 8;  /* mov r11,imagebase   */
    b[n++]=0x4D; b[n++]=0x39; b[n++]=0xDA;                /* cmp r10,r11         */
    gate_at[ngate++] = n; b[n++]=0x72; b[n++]=0x00;       /* jb  -> refuse       */
    b[n++]=0x49; b[n++]=0xBB; memcpy(b+n,&hi,8); n += 8;  /* mov r11,base+32MB   */
    b[n++]=0x4D; b[n++]=0x39; b[n++]=0xDA;                /* cmp r10,r11         */
    gate_at[ngate++] = n; b[n++]=0x73; b[n++]=0x00;       /* jae -> refuse       */

    /* skip: `this` failed the pointer rules, so the member reads were never
       made and there is nothing to judge. Proceed as the engine would rather
       than refuse on no evidence. */
    for (i = 0; i < nbad; i++)
        b[bad_at[i] + 1] = (unsigned char)(n - (bad_at[i] + 2));
    memcpy(b + n, orig, sizeof(orig)); n += (int)sizeof(orig);   /* stolen bytes */
    b[n++]=0xE9;                                          /* jmp resume          */
    rel = (long long)(mod + VFN_RESUME) - (long long)(stub + n + 4);
    memcpy(b+n,&rel,4); n += 4;

    /* refuse: the stack is untouched -- the very first instruction was
       detoured -- so a plain ret returns 0 to the caller. */
    for (i = 0; i < ngate; i++)
        b[gate_at[i] + 1] = (unsigned char)(n - (gate_at[i] + 2));
    b[n++]=0x48; b[n++]=0xFF; b[n++]=0x05;                /* inc qword [rip+d]   */
    rel = (long long)(data + 48) - (long long)(stub + n + 4);
    memcpy(b+n,&rel,4); n += 4;
    b[n++]=0x31; b[n++]=0xC0;                             /* xor eax,eax         */
    b[n++]=0xC3;                                          /* ret                 */

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);

    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("VFN: trampoline out of rel32 range -- skipped"); return;
    }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("VFN: VirtualProtect failed at RVA 0x%X", VFN_RVA); return;
    }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    for (i = 5; i < (int)sizeof(orig); i++) site[i] = 0x90;
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));
    log_line("VFN: probe installed at RVA 0x%X -- every call records `this` and the "
             "three members the crashes read. Not a guard: it changes nothing, it "
             "only makes the last call before a crash readable. AND it gates: a call whose *(this+0x490) is outside the image is refused outright, because six healthy calls all read the same vtable there and the two fatal ones did not.", VFN_RVA);
}

/* Called from the crash handler and once per stats window. `why` says which. */
static void vfn_report(const char* why)
{
    unsigned long long cnt, self, m258, m490, m6b8;
    const char* verdict;
    if (!g_vfn_slots) return;
    cnt  = g_vfn_slots[0];
    self = g_vfn_slots[1];
    m258 = g_vfn_slots[2];
    m490 = g_vfn_slots[3];
    m6b8 = g_vfn_slots[4];
    if (!cnt) { log_line("VFN/last (%s): never called", why); return; }
    /* The recurring shape: a tagged value with a flag in the high bits, used as
       a pointer. 0x88.., 0x80.., 0xC0.. -- never a real address. */
    if ((m258 >> 47) || (m490 >> 47))
        verdict = "TAGGED VALUE in a member -- this is the shape that faults";
    else if (!m258 || !m490)
        verdict = "a member is NULL";
    else
        verdict = "members look like pointers";
    if (g_vfn_slots[6])
        log_line("VFN/refused: %llu call(s) turned away at the door --"
                 " dead object, whole function skipped", g_vfn_slots[6]);
    log_line("VFN/last (%s): call #%llu on thread %llu, this %016llX;"
             " [+0x258] %016llX; [+0x490] %016llX; [+0x6b8] %016llX -- %s",
             why, cnt, g_vfn_slots[5], self, m258, m490, m6b8, verdict);
}

static void patch_teardown_guard(void)
{
    static const unsigned char orig[6] = {0x48,0x8B,0x03,0x48,0x8B,0xCB};
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    unsigned char* stub;
    unsigned char  b[64];
    int n = 0, jz_at;
    long long rel;
    DWORD old;

    if (!mod) return;
    site = mod + TEARDOWN_RVA;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        crashlog_note_site("TEARDOWN", TEARDOWN_RVA, TEARDOWN_RESUME,
                       "destroy through a NULL vtable", 0);
        log_line("TEARDOWN: bytes not at expected RVA 0x%X (game updated?) -- skipped",
                 TEARDOWN_RVA);
        return;
    }
    stub = (unsigned char*)gauge_alloc_near(site, 128);
    if (!stub) { log_line("TEARDOWN: no trampoline within +/-2GB -- skipped"); return; }

    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x03;          /* mov  rax,[rbx]     */
    b[n++]=0x48; b[n++]=0x85; b[n++]=0xC0;          /* test rax,rax       */
    jz_at = n; b[n++]=0x74; b[n++]=0x00;            /* jz   -> skip       */
    /* counter: inc qword [rip+disp] -- purely so the log can say it fired */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0xCB;          /* mov  rcx,rbx       */
    b[n++]=0xE9;                                    /* jmp  resume        */
    rel = (long long)(mod + TEARDOWN_RESUME) - (long long)(stub + n + 4);
    memcpy(b + n, &rel, 4); n += 4;
    b[jz_at + 1] = (unsigned char)(n - (jz_at + 2)); /* patch the jz now  */
    b[n++]=0xFF; b[n++]=0x05;                       /* inc  dword [rip+d] */
    rel = (long long)&g_td_saves - (long long)(stub + n + 4);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        /* counter out of rel32 reach: drop it rather than mis-encode */
        n -= 2;
    } else {
        memcpy(b + n, &rel, 4); n += 4;
    }
    b[n++]=0xE9;                                    /* jmp  skip          */
    rel = (long long)(mod + TEARDOWN_SKIP) - (long long)(stub + n + 4);
    memcpy(b + n, &rel, 4); n += 4;

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);

    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("TEARDOWN: trampoline out of rel32 range -- skipped");
        return;
    }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("TEARDOWN: VirtualProtect failed at RVA 0x%X", TEARDOWN_RVA);
        return;
    }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    site[5] = 0x90;
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));
    crashlog_note_site("TEARDOWN", TEARDOWN_RVA, TEARDOWN_RESUME,
                       "destroy through a NULL vtable", 1);
    log_line("TEARDOWN: guard installed at RVA 0x%X -- a destroy through a NULL vtable "
             "now jumps to the epilogue instead of faulting at 0x%X. Containment only: "
             "the reason a control block reaches that state is still unknown.",
             TEARDOWN_RVA, 0x8B06D0);
}

/* The second inlined copy. Same six bytes, same shape, its own counter --
   see the anchors above. */
static void patch_teardown2_guard(void)
{
    static const unsigned char orig[6] = {0x48,0x8B,0x03,0x48,0x8B,0xCB};
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char *site, *stub, b[64];
    int n = 0, jz;
    long long rel;
    DWORD old;

    if (!mod) return;
    site = mod + TEARDOWN2_RVA;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        crashlog_note_site("TEARDOWN2", TEARDOWN2_RVA, TEARDOWN2_RESUME,
                       "destroy through a NULL vtable, second inlined copy", 0);
        log_line("TEARDOWN2: bytes not at expected RVA 0x%X (game updated?) -- skipped",
                 TEARDOWN2_RVA);
        return;
    }
    stub = (unsigned char*)gauge_alloc_near(site, 128);
    if (!stub) { log_line("TEARDOWN2: no trampoline within +/-2GB -- skipped"); return; }

    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x03;          /* mov  rax,[rbx]      */
    b[n++]=0x48; b[n++]=0x85; b[n++]=0xC0;          /* test rax,rax        */
    jz = n; b[n++]=0x74; b[n++]=0x00;               /* jz   -> skip        */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0xCB;          /* mov  rcx,rbx        */
    b[n++]=0xE9;                                    /* jmp  resume         */
    rel = (long long)(mod + TEARDOWN2_RESUME) - (long long)(stub + n + 4);
    memcpy(b + n, &rel, 4); n += 4;

    b[jz + 1] = (unsigned char)(n - (jz + 2));
    b[n++]=0xFF; b[n++]=0x05;                       /* inc dword [rip+d]   */
    rel = (long long)&g_td2_saves - (long long)(stub + n + 4);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) n -= 2;   /* out of reach */
    else { memcpy(b + n, &rel, 4); n += 4; }
    b[n++]=0xE9;                                    /* jmp  skip           */
    rel = (long long)(mod + TEARDOWN2_SKIP) - (long long)(stub + n + 4);
    memcpy(b + n, &rel, 4); n += 4;

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);

    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("TEARDOWN2: trampoline out of rel32 range -- skipped"); return;
    }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("TEARDOWN2: VirtualProtect failed at RVA 0x%X", TEARDOWN2_RVA); return;
    }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    site[5] = 0x90;
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));
    crashlog_note_site("TEARDOWN2", TEARDOWN2_RVA, TEARDOWN2_RESUME,
                       "destroy through a NULL vtable, second inlined copy", 1);
    log_line("TEARDOWN2: guard installed at RVA 0x%X -- a destroy through a NULL "
             "vtable now jumps to the epilogue instead of faulting at 0x%X. "
             "Observed once on 2026-09-03 at the end of an online match; "
             "containment only, the reason a control block reaches that state is "
             "still open.", TEARDOWN2_RVA, TEARDOWN2_RESUME);
}

/* =====================================================================
 *  ONLINE INTRO SKIP  (pre-match character entrances)
 * ---------------------------------------------------------------------
 *  What the intro IS
 *  -----------------
 *  Demo/plNNN_ct_start.tdemopkg, one per character. The battle scene runs
 *  100 -> 200 -> 201 -> 300 -> 301: state 200 plays fighter 0's ct_start,
 *  state 201 plays fighter 1's, state 300 is the kakeai draw offline and the
 *  netcode RNG reseed online, 301 is the countdown into the fight.
 *
 *  All of it lives in the SHARED ActionSceneBase, with no battle-context
 *  test anywhere in the chain -- unlike TryAreaMove, which has an explicit
 *  `mode == 3` early-return. So online plays the exact same intro through
 *  the exact same code: there is no gate to flip, only a transition to move.
 *
 *  What this patch does
 *  --------------------
 *  ActionSceneBase::vfunc27 leaves state 100 with SetState(200), and that is
 *  what starts the intro. We hook that one call site and pass 300 instead
 *  when the battle context is online, so the two ct_start states are never
 *  entered. Offline is untouched -- story, missions, versus and training all
 *  still play their intros.
 *
 *  This is not a novel code path. STutorialAction::vfunc26 already does
 *  exactly this jump (RVA 0x7016DF is byte-for-byte the `mov edx,12Ch ;
 *  mov rcx,rdi ; call [rax+0D0h]` we synthesise), and STrainingAction goes
 *  to 300 as well. So skipping 200/201 -- and with them the vtable+0xF0 call
 *  that state 201 makes -- is a path the shipping game already executes.
 *
 *  Why gating on "online" is enough, and safe
 *  ------------------------------------------
 *  The netcode has NO rendezvous between the intro and the fight: the only
 *  pre-battle sync point is slot 0, at scene state 0x32, before the load.
 *  A client that skipped while its opponent did not would reach the fight
 *  early. That is a non-issue here, for two independent reasons -- the
 *  launcher git-reset-hard's every non-dev user on launch, and the issuer
 *  segregation above already keeps patched clients in their own pool -- so
 *  both sides run this identically and deterministically. It would NOT be
 *  safe as a player-pressable skip: that is per-client input, and would need
 *  one of the free sync slots (0/5/6/8/9/10 are used, there are 32).
 *
 *  Anchors -- verified against the shipping exe, 28,283,464 bytes
 *  -------------------------------------------------------------
 *  RVA 0x6B35B7  BA C8 00 00 00 48 8B CF FF 90 D0 00 00 00
 *                mov edx,0C8h ; mov rcx,rdi ; call qword [rax+0D0h]
 *                This 14-byte sequence occurs exactly ONCE in the image, and
 *                no branch anywhere in .text targets bytes 1..7 of it, so
 *                stealing 8 for an E9 is safe.
 *  RVA 0x1CFBAB8 SceneGlobalInfo* singleton. Confirmed three times over:
 *                every lazy-init store (`mov [rip+d],rax` at RVA 0x42CAA0,
 *                0x6A3B2E and 0x6D1EED) resolves to this same address, and
 *                each is immediately followed by `cmp dword [rax+0D8h],3`.
 *  +0xD8         battle context: 0 single player, 1 offline versus,
 *                2 training, 3 online.
 *
 *  Register safety: at the hook site rcx is DEAD -- the very next original
 *  instruction overwrites it with rdi -- so the stub uses rcx as its scratch
 *  and writes nothing else. rax (the vtable, already loaded) and rdi (this)
 *  are never touched. Flags are clobbered, which is free: a call follows
 *  immediately, and the ABI does not preserve flags across one.
 *
 *  NOTE: found and verified statically; NOT yet confirmed in a running game.
 * ===================================================================== */
#define INTROSKIP_RVA        0x6B35B7
#define INTROSKIP_GLOBAL_RVA 0x1CFBAB8

static void patch_intro_skip(void)
{
    static const unsigned char orig[14] = {
        0xBA,0xC8,0x00,0x00,0x00,       /* mov  edx,0C8h          */
        0x48,0x8B,0xCF,                 /* mov  rcx,rdi           */
        0xFF,0x90,0xD0,0x00,0x00,0x00   /* call qword [rax+0D0h]  */
    };
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    unsigned char* stub;
    unsigned char* gptr;
    unsigned char  b[96];
    int n = 0, off_jz, off_jne, off_done;
    long long rel;
    DWORD old;

    if (!mod) return;
    site = mod + INTROSKIP_RVA;

    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("INTROSKIP: bytes not at expected RVA 0x%X (game updated?) -- skipped, "
                 "online keeps playing the pre-match intros", INTROSKIP_RVA);
        return;
    }

    stub = (unsigned char*)gauge_alloc_near(site, 128);
    if (!stub) { log_line("INTROSKIP: no trampoline within +/-2GB -- skipped"); return; }

    gptr = mod + INTROSKIP_GLOBAL_RVA;                                /* &SceneGlobalInfo*   */

    b[n++]=0xBA; b[n++]=0xC8; b[n++]=0x00; b[n++]=0x00; b[n++]=0x00;  /* mov  edx,0C8h  (200)*/
    b[n++]=0x48; b[n++]=0xB9; memcpy(b+n,&gptr,8); n+=8;              /* mov  rcx,&singleton */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x09;                            /* mov  rcx,[rcx]      */
    b[n++]=0x48; b[n++]=0x85; b[n++]=0xC9;                            /* test rcx,rcx        */
    b[n++]=0x74; off_jz  = n++;                                       /* jz   done           */
    b[n++]=0x83; b[n++]=0xB9; b[n++]=0xD8; b[n++]=0x00;
    b[n++]=0x00; b[n++]=0x00; b[n++]=0x03;                            /* cmp  [rcx+0D8h],3   */
    b[n++]=0x75; off_jne = n++;                                       /* jne  done           */
    b[n++]=0xBA; b[n++]=0x2C; b[n++]=0x01; b[n++]=0x00; b[n++]=0x00;  /* mov  edx,12Ch  (300)*/
    off_done = n;                                                     /* done:               */
    b[off_jz]  = (unsigned char)(off_done - (off_jz  + 1));
    b[off_jne] = (unsigned char)(off_done - (off_jne + 1));
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0xCF;                            /* mov  rcx,rdi stolen */
    rel = (long long)(site + 8) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;                            /* jmp  back           */

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);

    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("INTROSKIP: trampoline out of rel32 range -- skipped");
        return;
    }
    if (!VirtualProtect(site, 8, PAGE_EXECUTE_READWRITE, &old)) {
        log_line("INTROSKIP: VirtualProtect failed at RVA 0x%X", INTROSKIP_RVA);
        return;
    }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    site[5] = 0x90; site[6] = 0x90; site[7] = 0x90;   /* never leave half an instruction */
    VirtualProtect(site, 8, old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, 8);
    log_line("INTROSKIP: installed at RVA 0x%X -- state 100 now enters 300 instead of 200 "
             "when SceneGlobalInfo+0xD8 == 3, so online skips both ct_start states; "
             "offline unchanged", INTROSKIP_RVA);
}

/* ===================== PART 9: ONLINE ROOM-MATCH RESULT MENU ==========
 *  Offline versus ends on a three-entry menu over the VICTOR screen --
 *  "Try Again" / "Character Selection" / "Return to Offline Menu". An online
 *  ROOM MATCH ends with no menu at all: the result screen runs a timer out and
 *  drops straight back to the room lobby. Free match and ranked match DO get a
 *  menu ("Try Again" / "Opponent Search" / "Quit ..."), and its "Try Again" is
 *  a real netcode-synchronised rematch.
 *
 *  None of that machinery is missing for room match -- only unreachable.
 *
 *  WHAT PICKS THE MENU. SOnlineAction::SetupDynamic computes a result-screen
 *  KIND from the online mode at SceneGlobalInfo+0x498 (0 room, 1 free,
 *  2 ranked) and hands it to the result UI, which stores it at ctrl+0x250:
 *
 *      mov r15d,3            ; default: free match
 *      test r8d,r8d          ; mode
 *      jne  +9
 *      lea  r15d,[r8+7]      ; mode 0 (ROOM MATCH) -> kind 7
 *      ...                   ; mode 2 -> 4, or 5/6 for a ranked series
 *
 *  Both the menu builder and the scene dispatcher then gate on that kind:
 *
 *      builder    (uint)(kind-5) > 2                 -> build the choice list
 *      builder    (uint)(kind-3) <= 1                -> ONLINE labels + codes
 *      dispatcher (uint)(kind-3) <= 1 || kind >= 8   -> read the player's choice
 *
 *  Kind 7 fails all three, which is the whole reason room match has no menu.
 *
 *  WHAT THE CHOICES DO. The builder writes a parallel array of action codes
 *  next to the labels (ctrl+0x308, a vector<int>), and SOnlineAction::vfunc27
 *  dispatches codes[cursor] in scene state 0x406:
 *
 *      0 -> SetState(0x458) + sync slot 8   the two-sided REMATCH handshake,
 *                                           which ends in the "RESTART_BATTLE"
 *                                           flow command and SetState(0x462)
 *      6 -> SetState(0x45a) "BACK_ONLINE_MENU"
 *      7 -> SetState(0x45b) "BACK_MAIN_MENU"
 *
 *  and the online flow graph registers ALL THREE on the RoomMatchAction node:
 *  RESTART_BATTLE -> JUMP_RoomMatchAction (straight back into the fight, same
 *  characters, no character select), BACK_ONLINE_MENU (pops to the room), and
 *  BACK_MAIN_MENU. So every code the free-match menu emits is already a valid
 *  room-match transition -- the room-match kind just never lets you pick one.
 *
 *  THE PATCH. One byte: lea r15d,[r8+7] -> [r8+3], so a room match uses the
 *  free-match result kind and gets the free-match menu. That path is what free
 *  match runs every day, which is the point: no new combination of kind and UI
 *  state is invented. Kind 4/6 (ranked) is deliberately NOT used -- it drives
 *  the rank-point animation, which a room match has no data for.
 *
 *  Two label hooks then fix the wording, because entries 2 and 3 would
 *  otherwise read "Opponent Search" and "Quit Free Match" while actually
 *  returning to the room and to the main menu. Each hook swaps the CommonText
 *  key the builder passes, but ONLY when SceneGlobalInfo+0x498 == 0, so a real
 *  free match keeps its own wording. Both replacement keys already ship in
 *  Text/CommonText.cat, so no data file changes.
 *
 *  Live-build anchors (28,283,464 B). Every site is byte-checked before it is
 *  touched, and the label hooks additionally check that the displacement they
 *  find really resolves to the string they expect.
 *
 *      0x8043F9  mov r15d,3 / test r8d,r8d / jne / lea r15d,[r8+7]
 *      0x3362C9  lea rdx,[rip+..] -> "BATTLE_RESULT_CHOICES_1"  (entry 2)
 *      0x33632E  lea rdx,[rip+..] -> "BATTLE_RESULT_CHOICES_3"  (entry 3)
 *      0x1CFBAB8 &SceneGlobalInfo (shared with INTROSKIP), +0x498 = online mode
 *
 *  rax is dead at both label sites (a call follows before any read of it) and
 *  flags are dead there too, so each stub needs no save/restore.
 * --------------------------------------------------------------------- */
#define ROOMRESULT_KIND_RVA   0x8043F9
#define ROOMRESULT_LBL2_RVA   0x3362C9
#define ROOMRESULT_LBL3_RVA   0x33632E
#define ROOMRESULT_MODE_OFF   0x498      /* SceneGlobalInfo + this = online mode */

static int roomresult_hook_label(unsigned char* mod, unsigned int rva,
                                 const char* expect, const char* replace,
                                 const char* tag)
{
    unsigned char* site = mod + rva;
    unsigned char* key;
    unsigned char* stub;
    unsigned char* gptr = mod + INTROSKIP_GLOBAL_RVA;   /* &SceneGlobalInfo* */
    unsigned char  b[128];
    int n = 0, off_jz, off_jne, off_skip, off_orig, off_back;
    int disp;
    long long rel;
    DWORD old;

    if (site[0] != 0x48 || site[1] != 0x8D || site[2] != 0x15) {
        log_line("ROOMRESULT: %s is not a lea rdx,[rip+d] at RVA 0x%X -- label left alone",
                 tag, rva);
        return 0;
    }
    memcpy(&disp, site + 3, 4);
    key = site + 7 + disp;
    if (strcmp((const char*)key, expect) != 0) {
        log_line("ROOMRESULT: %s at RVA 0x%X resolves to \"%.32s\", expected \"%s\" -- "
                 "label left alone", tag, rva, (const char*)key, expect);
        return 0;
    }

    stub = (unsigned char*)gauge_alloc_near(site, 128);
    if (!stub) {
        log_line("ROOMRESULT: %s no trampoline within +/-2GB -- label left alone", tag);
        return 0;
    }

    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&gptr,8); n+=8;      /* mov  rax,&singleton  */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x00;                    /* mov  rax,[rax]       */
    b[n++]=0x48; b[n++]=0x85; b[n++]=0xC0;                    /* test rax,rax         */
    b[n++]=0x74; off_jz  = n++;                               /* jz   orig            */
    b[n++]=0x83; b[n++]=0xB8;
    b[n++]=(unsigned char)(ROOMRESULT_MODE_OFF & 0xFF);
    b[n++]=(unsigned char)((ROOMRESULT_MODE_OFF >> 8) & 0xFF);
    b[n++]=0x00; b[n++]=0x00; b[n++]=0x00;                    /* cmp  [rax+498h],0    */
    b[n++]=0x75; off_jne = n++;                               /* jne  orig            */
    b[n++]=0x48; b[n++]=0xBA; memcpy(b+n,&replace,8); n+=8;   /* mov  rdx,room key    */
    b[n++]=0xEB; off_skip = n++;                              /* jmp  back            */
    off_orig = n;                                             /* orig:                */
    b[off_jz]  = (unsigned char)(off_orig - (off_jz  + 1));
    b[off_jne] = (unsigned char)(off_orig - (off_jne + 1));
    b[n++]=0x48; b[n++]=0xBA; memcpy(b+n,&key,8); n+=8;       /* mov  rdx,original    */
    off_back = n;                                             /* back:                */
    b[off_skip] = (unsigned char)(off_back - (off_skip + 1));
    rel = (long long)(site + 7) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;                    /* jmp  site+7          */

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);

    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("ROOMRESULT: %s trampoline out of rel32 range -- label left alone", tag);
        return 0;
    }
    if (!VirtualProtect(site, 7, PAGE_EXECUTE_READWRITE, &old)) {
        log_line("ROOMRESULT: %s VirtualProtect failed at RVA 0x%X", tag, rva);
        return 0;
    }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    site[5] = 0x90; site[6] = 0x90;          /* never leave half an instruction */
    VirtualProtect(site, 7, old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, 7);
    log_line("ROOMRESULT: %s at RVA 0x%X -- \"%s\" -> \"%s\" when the online mode is "
             "room match, unchanged for free/ranked", tag, rva, expect, replace);
    return 1;
}

static void patch_room_result_menu(void)
{
    /* The CommonText keys the room-match menu reads instead. Both already ship in
       Text/CommonText.cat: ONLINE_MENU_ROOMMATCH = "ROOM MATCH" (JA "ROOM MATCH"),
       mainMenu = "Return to Main Menu". */
    static const char k_room[] = "ONLINE_MENU_ROOMMATCH";
    static const char k_main[] = "mainMenu";

    static const unsigned char kind_orig[15] = {
        0x41,0xBF,0x03,0x00,0x00,0x00,   /* mov  r15d,3       free-match kind   */
        0x45,0x85,0xC0,                  /* test r8d,r8d      online mode       */
        0x75,0x09,                       /* jne  +9                             */
        0x45,0x8D,0x78,0x07              /* lea  r15d,[r8+7]  room-match kind   */
    };
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    DWORD old;

    if (!mod) return;
    site = mod + ROOMRESULT_KIND_RVA;

    if (memcmp(site, kind_orig, sizeof(kind_orig)) != 0) {
        log_line("ROOMRESULT: bytes not at expected RVA 0x%X (game updated?) -- skipped, "
                 "a room match still ends with no menu", ROOMRESULT_KIND_RVA);
        return;
    }
    if (!VirtualProtect(site + 14, 1, PAGE_EXECUTE_READWRITE, &old)) {
        log_line("ROOMRESULT: VirtualProtect failed at RVA 0x%X", ROOMRESULT_KIND_RVA + 14);
        return;
    }
    site[14] = 0x03;                     /* lea r15d,[r8+7] -> [r8+3]           */
    VirtualProtect(site + 14, 1, old, &old);
    FlushInstructionCache(GetCurrentProcess(), site + 14, 1);
    log_line("ROOMRESULT: kind patched at RVA 0x%X -- a room match now uses the free-match "
             "result kind 3, so it ends on the menu: Try Again (synced rematch, same "
             "characters) / back to the room / back to the main menu",
             ROOMRESULT_KIND_RVA + 14);

    roomresult_hook_label(mod, ROOMRESULT_LBL2_RVA, "BATTLE_RESULT_CHOICES_1", k_room, "entry2");
    roomresult_hook_label(mod, ROOMRESULT_LBL3_RVA, "BATTLE_RESULT_CHOICES_3", k_main, "entry3");
}

/* ============ PART 10: ROOM-MATCH NULL GUARDS (crash containment) =====
 *  Repro (2026-08-23): in a ROOM MATCH, when the OPPONENT changes character,
 *  the client crashes. The one thing that avoids it is being on the Battle
 *  Settings screen while they switch and coming back afterwards.
 *
 *  Read from the Windows crash dumps in %LOCALAPPDATA%\CrashDumps, which are
 *  full thread dumps: eight of them, two distinct faults, both 0xC0000005 and
 *  both a NULL used without a check. Neither is in patched code.
 *
 *  --- Fault A: the draw path (dumps 10:08 and 10:17, the reported repro) ----
 *  RIP is inside memcpy at RVA 0x10A62AB, on the store half of the AVX copy:
 *
 *      rcx (dst) = 0xF9F0 / 0x129C0     <- NOT a pointer
 *      rdx (src) = a stack address       <- fine
 *      r8  (len) = 0x90                  <- 4 verts * 0x24 stride, one quad
 *
 *  Return address RVA 0x9DDB31 puts the call in the vertex-upload helper at
 *  0x9DDA60, which does:
 *
 *      mov  eax,[r14+0x158]              ; current buffer index
 *      mov  rcx,[r14+rax*8+0x140]        ; that buffer
 *      call [vtable+0x40]                ; MAP -> writes a pointer to [rsp+38]
 *      mov  eax,[r14+0x15c]              ; running byte offset in the buffer
 *      mov  rcx,[rsp+0x38]               ; mapped base
 *      add  rcx,rax                      ; dst = base + offset
 *      ...  memcpy(dst, src, count*stride)
 *
 *  dst was exactly the running offset in both dumps, so **the map returned
 *  NULL and the code used it anyway**. The two offsets differ (63,984 and
 *  76,224), so it is the map failing, not a fixed capacity being crossed.
 *
 *  GUARD A: if the mapped base is NULL, leave the helper through its own
 *  epilogue at 0x9DDD25 instead of copying. That path releases [rbp+0x38] and
 *  runs the stack-cookie check, and rbp is untouched between the map and
 *  there, so the frame unwinds exactly as the function itself would. The cost
 *  of a fired guard is one quad missing for one frame; the cost of not having
 *  it is the process dying.
 *
 *  --- Fault B: the Steam call-result cancel (dumps 22:05, 22:09, 22:42, 09:18)
 *  Four dumps, byte-identical stacks, on a worker thread:
 *
 *      0xA75E60  mov rax,[rcx]      <- rcx = 0
 *      0xA75E5D  mov rcx,[rax]      <- rax = SteamInternal_ContextInit(...)
 *      0xA75E63  call [rax+0x78]
 *
 *  `SteamInternal_ContextInit` hands back the game's static Steam context and
 *  the first field is the interface pointer. It is NULL — the interface is not
 *  live at that moment — and the game dereferences it to make one call. The
 *  caller chain is 0x813DEA -> 0x91338A: the room-session object being
 *  (re)built, i.e. the same room-match traffic the repro produces. `[rdi+0x2a]`
 *  gates the call, so this is "cancel the pending Steam call result before
 *  issuing a new one".
 *
 *  GUARD B: if that interface pointer is NULL, skip the one call and carry on
 *  to the release that follows at 0xA75E66. A cancel that cannot be delivered
 *  because the interface is gone is a no-op anyway.
 *
 *  Both guards are containment, not a root cause: they say what fired in
 *  patch_ranked.log (counters, every 30 s with the gauge heartbeat) so the next
 *  session tells us which one the room-match repro actually hits and how often.
 *  If a counter climbs steadily rather than firing on the switch, the real bug
 *  is upstream and this only bought time.
 *
 *  Anchors verified against the shipping exe (28,283,464 B):
 *      0x9DDAF7  41 8B 86 5C 01 00 00        mov eax,[r14+0x15c]
 *      0x9DDD25  (jump target: the helper's own release+epilogue)
 *      0xA75E5D  48 8B 08 48 8B 01 FF 50 78  mov rcx,[rax] / mov rax,[rcx] / call [rax+78]
 * --------------------------------------------------------------------- */
#define ROOMGUARD_DRAW_RVA   0x9DDAF7
#define ROOMGUARD_DRAW_EXIT  0x9DDD25
#define ROOMGUARD_STEAM_RVA  0xA75E5D


/* =====================================================================
 *  patch_uires_guard -- the Training -> Battle -> CharaSelect -> Battle crash
 *
 *  CRASH: access violation at exe+0x9DB40A -- reading from 0x4
 *
 *      0x9DB400  mov    [rsp+8], rbx
 *      0x9DB405  mov    [rsp+10h], rdi
 *      0x9DB40A  movsxd rax, [rcx+4]      <-- rcx = NULL
 *
 *  0x9DB400 is the UI resource-table lookup: `find_row_by_id(table, id)`.
 *  It reads a row count at table+4 and walks 8-byte entries from table+0xC
 *  comparing a dword id, returning the matching row or 0. Its callers at
 *  0x23EAA0.. parse the row as CSV (they scan for ',' 0x2C and test a "tmd"
 *  extension), so this is the model/resource index.
 *
 *  ★ UI_SYSTEM_REFERENCE.md section 3 already documented this exact RVA:
 *  requesting a UI page whose scene is absent -- whose `.cat` data was never
 *  loaded -- lands here with a NULL table. Training loads
 *  ui_TrainingMenu_*.cat because STrainingMenu exists; Battle does not. Going
 *  Training -> Battle -> CharacterSelect -> Battle asks for a row out of a
 *  table that is no longer loaded, and the lookup dereferences NULL.
 *
 *  ★★ EVERY call site already null-checks the RETURN value:
 *
 *      call 0x1409db400 ; test rax,rax ; jne .. ; xor r15d,r15d
 *      call 0x1409db400 ; mov rcx,rax  ; test rax,rax ; je ..
 *
 *  so "not found" is a state the callers are written to handle. The lookup
 *  simply never checks its own argument. Returning 0 for a NULL table is
 *  therefore not a behaviour change invented here -- it is the answer the
 *  callers already expect for a row that is not present.
 *
 *  Same shape as the two room guards: 5-byte detour to a near cave, the
 *  stolen instruction is one whole instruction (mov [rsp+8],rbx, exactly 5
 *  bytes) so nothing is padded and no half instruction is left behind.
 * ===================================================================== */
#define UIRES_GUARD_RVA  0x9DB400
static volatile LONG64 g_uires_skips = 0;   /* NULL UI resource table */

static void patch_uires_guard(void)
{
    static const unsigned char orig[5] = {
        0x48,0x89,0x5C,0x24,0x08            /* mov [rsp+8], rbx */
    };
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    unsigned char* stub;
    void* ctr = (void*)&g_uires_skips;
    unsigned char b[96];
    int n = 0, off_jne, off_ok;
    long long rel;
    DWORD old;

    if (!mod) return;
    site = mod + UIRES_GUARD_RVA;

    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("UIRESGUARD: bytes at RVA 0x%X are %02X %02X %02X %02X %02X, expected"
                 " 48 89 5C 24 08 (game updated?) -- skipped, the Training->Battle"
                 " ->CharaSelect->Battle NULL lookup still crashes",
                 UIRES_GUARD_RVA, site[0], site[1], site[2], site[3], site[4]);
        return;
    }

    stub = (unsigned char*)gauge_alloc_near(site, 128);
    if (!stub) { log_line("UIRESGUARD: no trampoline within +/-2GB -- skipped"); return; }

    b[n++]=0x48; b[n++]=0x85; b[n++]=0xC9;                  /* test rcx,rcx         */
    b[n++]=0x75; off_jne = n++;                             /* jne  ok              */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&ctr,8); n+=8;     /* mov  rax,&counter    */
    b[n++]=0xF0; b[n++]=0x48; b[n++]=0xFF; b[n++]=0x00;     /* lock inc qword [rax] */
    b[n++]=0x33; b[n++]=0xC0;                               /* xor  eax,eax         */
    b[n++]=0xC3;                                            /* ret  -- "not found"  */
    off_ok = n;                                             /* ok:                  */
    b[off_jne] = (unsigned char)(off_ok - (off_jne + 1));
    memcpy(b+n, orig, sizeof(orig)); n += (int)sizeof(orig);/* stolen instruction   */
    rel = (long long)(site + 5) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;                  /* jmp  back            */

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);

    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("UIRESGUARD: trampoline out of rel32 range -- skipped"); return;
    }
    if (!VirtualProtect(site, 5, PAGE_EXECUTE_READWRITE, &old)) {
        log_line("UIRESGUARD: VirtualProtect failed at RVA 0x%X", UIRES_GUARD_RVA);
        return;
    }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    VirtualProtect(site, 5, old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, 5);
    log_line("UIRESGUARD: installed at RVA 0x%X -- a UI resource lookup on a table"
             " that was never loaded now returns \"not found\" (0), which every call"
             " site already handles, instead of reading [NULL+4]", UIRES_GUARD_RVA);
}


/* =====================================================================
 *  patch_voice_probe -- what event does the select screen actually post?
 *
 *  Two data-side fixes for pl005's character-select voice changed nothing:
 *  the event `pl005_chara_select` exists in both banks with a verified
 *  Event -> Play action -> Sound -> wem chain, all six file_exist.htable
 *  entries are registered, and pl005.bnk now declares its own bank id. So
 *  stop inferring and read the live value.
 *
 *  The select screen builds the name and posts it BY NAME:
 *
 *      call 0x14025FED0 / 0x14025FFA0   ; chara id
 *      call 0x1400E2E30                 ; "pl" + %03d
 *      lea  rdx, "_chara_select" ; call 0x140090080   ; append
 *      lea  rcx, [rsp+0x30] ; call 0x14024BB10        ; <- post, rcx = std::string*
 *
 *  0x24BB10 takes the name in rcx and stashes it in rbx at +0x13, so a
 *  detour on its first five bytes sees the string intact. Its first four
 *  pushes are exactly 5 bytes (40 55 53 56 57), so nothing is padded and no
 *  half instruction is left behind.
 *
 *  The answer is one of three, and each points somewhere different:
 *    - "pl005_chara_select" posted  -> the name is right, the bank is not
 *      being loaded on the select screen; chase LoadBank, not the event.
 *    - some other name posted       -> that is the name to add to the bank.
 *    - nothing posted at all        -> the select screen never asks for a
 *      voice for this slot; the gate is upstream of the sound system.
 *
 *  Capped at VOICEPROBE_MAX lines so a battle cannot flood the log.
 * ===================================================================== */
#define VOICEPROBE_RVA  0x24BB10
#define VOICEPROBE_MAX  20
static volatile LONG64 g_voiceprobe_calls = 0;
static unsigned int    g_voiceprobe_logged = 0;

/* MSVC std::string: char buf[16] | char* ptr  at +0, size_t len at +0x10,
   size_t cap at +0x18. cap >= 16 means the data is heap-allocated. */
static void pl005_voice_probe(void* str, void* ret)
{
    const char* sdata;
    unsigned long long len, cap;
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    char buf[80];
    unsigned i;
    g_voiceprobe_calls++;
    /* ★ only the select-voice call site. 0x25E9BB is the call, so the return
       address is 0x25E9C0. Everything else is other systems posting audio and
       would only add volume -- and volume is what crashed the last build. */
    if ((unsigned long long)((unsigned char*)ret - mod) != 0x25E9C0ULL) return;
    if (g_voiceprobe_logged >= VOICEPROBE_MAX) return;
    g_voiceprobe_logged++;
    if (!str) {
        log_line("VOICEPROBE: call %lld from exe+0x%llX -- string pointer NULL",
                 (long long)g_voiceprobe_calls,
                 (unsigned long long)((unsigned char*)ret - mod));
        return;
    }
    __try {
        len   = *(unsigned long long*)((unsigned char*)str + 0x10);
        cap   = *(unsigned long long*)((unsigned char*)str + 0x18);
        sdata = (cap >= 16) ? *(const char**)str : (const char*)str;
        buf[0] = 0;
        if (sdata) {
            for (i = 0; i < 72 && i < (unsigned)len; i++) {
                char c = sdata[i];
                buf[i] = (c >= 32 && c < 127) ? c : '.';
            }
            buf[i] = 0;
        }
        log_line("VOICEPROBE: call %lld from exe+0x%llX  len=%llu cap=%llu  name=\"%s\"",
                 (long long)g_voiceprobe_calls,
                 (unsigned long long)((unsigned char*)ret - mod),
                 (unsigned long long)len, (unsigned long long)cap, buf);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        log_line("VOICEPROBE: call %lld from exe+0x%llX -- faulted reading the string",
                 (long long)g_voiceprobe_calls,
                 (unsigned long long)((unsigned char*)ret - mod));
    }
}

static void patch_voice_probe(void)
{
    static const unsigned char orig[5] = {
        0x40,0x55,0x53,0x56,0x57            /* push rbp; push rbx; push rsi; push rdi */
    };
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    unsigned char* stub;
    void* fn = (void*)&pl005_voice_probe;
    unsigned char b[160];
    int n = 0;
    long long rel;
    DWORD old;

    if (!mod) return;
    site = mod + VOICEPROBE_RVA;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("VOICEPROBE: bytes at RVA 0x%X are %02X %02X %02X %02X %02X, expected"
                 " 40 55 53 56 57 -- skipped", VOICEPROBE_RVA,
                 site[0], site[1], site[2], site[3], site[4]);
        return;
    }
    stub = (unsigned char*)gauge_alloc_near(site, 160);
    if (!stub) { log_line("VOICEPROBE: no trampoline within +/-2GB -- skipped"); return; }

    /* rsp is 8 mod 16 at entry; sub 0x48 makes it 0 mod 16 for the call. */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xEC; b[n++]=0x48;          /* sub rsp,0x48      */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x20;  /* mov [rsp+20],rcx */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x54; b[n++]=0x24; b[n++]=0x28;  /* mov [rsp+28],rdx */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x44; b[n++]=0x24; b[n++]=0x30;  /* mov [rsp+30],r8  */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x38;  /* mov [rsp+38],r9  */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x54; b[n++]=0x24; b[n++]=0x48;  /* mov rdx,[rsp+48] = retaddr */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&fn,8); n+=8;           /* mov rax,&probe    */
    b[n++]=0xFF; b[n++]=0xD0;                                    /* call rax          */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x20;  /* mov rcx,[rsp+20] */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x54; b[n++]=0x24; b[n++]=0x28;  /* mov rdx,[rsp+28] */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x30;  /* mov r8,[rsp+30]  */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x38;  /* mov r9,[rsp+38]  */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xC4; b[n++]=0x48;          /* add rsp,0x48      */
    memcpy(b+n, orig, sizeof(orig)); n += (int)sizeof(orig);     /* stolen pushes     */
    rel = (long long)(site + 5) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;                       /* jmp back          */

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);

    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("VOICEPROBE: trampoline out of rel32 range -- skipped"); return;
    }
    if (!VirtualProtect(site, 5, PAGE_EXECUTE_READWRITE, &old)) {
        log_line("VOICEPROBE: VirtualProtect failed at RVA 0x%X", VOICEPROBE_RVA);
        return;
    }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    VirtualProtect(site, 5, old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, 5);
    log_line("VOICEPROBE: installed at RVA 0x%X -- every Wwise event posted by name is"
             " logged (first %d). Hover and confirm Zangetsu on the character select"
             " screen, then read the VOICEPROBE lines.", VOICEPROBE_RVA, VOICEPROBE_MAX);
}


/* =====================================================================
 *  patch_prefix_probe -- does the select-voice path run at all, and with
 *  which chara id?
 *
 *  The first probe on the post-by-name function (0x24BB10) logged ZERO
 *  calls across a full character-select pass -- pl005 hovered, selected,
 *  costume chosen, then pl000 selected the same way. pl000 has a shipped
 *  select voice, so "the event name is wrong" cannot explain it: the
 *  posting function was never reached for either character.
 *
 *  So probe one step earlier. 0x1400E2E30 is the prefix builder:
 *
 *      rcx = out std::string, edx = chara id  ->  "pl%03d"
 *
 *  It is called immediately before "_chara_select" is appended, so if it
 *  runs, the select-voice path runs, and edx names the character. If it
 *  does not run either, the gate is further upstream still and the sound
 *  system is not involved at all.
 *
 *  Prologue is 40 55 53 57 48 8B EC -- push rbp; push rbx; push rdi;
 *  mov rbp,rsp = 7 whole bytes, so 5 are detoured and 2 padded with nop.
 * ===================================================================== */
#define PREFIXPROBE_RVA 0xE2E30
#define PREFIXPROBE_MAX 200
static volatile LONG64 g_prefixprobe_calls = 0;
static unsigned int    g_prefixprobe_logged = 0;

static void pl005_prefix_probe(void* out, unsigned int id, void* ret)
{
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned long long rva = (unsigned long long)((unsigned char*)ret - mod);
    (void)out;
    g_prefixprobe_calls++;
    /* The startup pass enumerates every character from one call site; log each
       DISTINCT call site once, then only ids that matter, so the burst cannot
       bury the select-time call. */
    if (g_prefixprobe_logged < PREFIXPROBE_MAX && (id == 5 || id == 0 || g_prefixprobe_calls < 3)) {
        g_prefixprobe_logged++;
        log_line("PREFIXPROBE: chara id %u -> \"pl%03u\"  caller exe+0x%llX  (call %lld)",
                 id, id, rva, (long long)g_prefixprobe_calls);
    }
}

static void patch_prefix_probe(void)
{
    static const unsigned char orig[7] = {
        0x40,0x55,0x53,0x57,0x48,0x8B,0xEC   /* push rbp; push rbx; push rdi; mov rbp,rsp */
    };
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    unsigned char* stub;
    void* fn = (void*)&pl005_prefix_probe;
    unsigned char b[160];
    int n = 0;
    long long rel;
    DWORD old;

    if (!mod) return;
    site = mod + PREFIXPROBE_RVA;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("PREFIXPROBE: bytes at RVA 0x%X are %02X %02X %02X %02X %02X %02X %02X,"
                 " expected 40 55 53 57 48 8B EC -- skipped", PREFIXPROBE_RVA,
                 site[0], site[1], site[2], site[3], site[4], site[5], site[6]);
        return;
    }
    stub = (unsigned char*)gauge_alloc_near(site, 160);
    if (!stub) { log_line("PREFIXPROBE: no trampoline within +/-2GB -- skipped"); return; }

    b[n++]=0x48; b[n++]=0x83; b[n++]=0xEC; b[n++]=0x48;               /* sub rsp,0x48   */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x20;  /* [rsp+20]=rcx   */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x54; b[n++]=0x24; b[n++]=0x28;  /* [rsp+28]=rdx   */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x44; b[n++]=0x24; b[n++]=0x30;  /* [rsp+30]=r8    */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x38;  /* [rsp+38]=r9    */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x48;  /* mov r8,[rsp+48] = retaddr */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&fn,8); n+=8;                /* mov rax,&probe */
    b[n++]=0xFF; b[n++]=0xD0;                                         /* call rax       */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x20;  /* rcx=[rsp+20]   */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x54; b[n++]=0x24; b[n++]=0x28;  /* rdx=[rsp+28]   */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x30;  /* r8=[rsp+30]    */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x38;  /* r9=[rsp+38]    */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xC4; b[n++]=0x48;               /* add rsp,0x48   */
    memcpy(b+n, orig, sizeof(orig)); n += (int)sizeof(orig);          /* stolen 7       */
    rel = (long long)(site + 7) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);

    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("PREFIXPROBE: trampoline out of rel32 range -- skipped"); return;
    }
    if (!VirtualProtect(site, 7, PAGE_EXECUTE_READWRITE, &old)) {
        log_line("PREFIXPROBE: VirtualProtect failed at RVA 0x%X", PREFIXPROBE_RVA);
        return;
    }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    site[5] = 0x90; site[6] = 0x90;
    VirtualProtect(site, 7, old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, 7);
    log_line("PREFIXPROBE: installed at RVA 0x%X -- logs the chara id every time the"
             " select-voice name is built", PREFIXPROBE_RVA);
}

static void patch_room_draw_guard(void)
{
    static const unsigned char orig[7] = {
        0x41,0x8B,0x86,0x5C,0x01,0x00,0x00      /* mov eax,[r14+0x15c] */
    };
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    unsigned char* stub;
    unsigned char* exitp;
    void* ctr = (void*)&g_rg_draw_skips;
    unsigned char b[96];
    int n = 0, off_jne, off_ok;
    long long rel;
    DWORD old;

    if (!mod) return;
    site  = mod + ROOMGUARD_DRAW_RVA;
    exitp = mod + ROOMGUARD_DRAW_EXIT;

    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("ROOMGUARD/draw: bytes not at expected RVA 0x%X (game updated?) -- "
                 "skipped, a NULL vertex map still crashes", ROOMGUARD_DRAW_RVA);
        return;
    }

    stub = (unsigned char*)gauge_alloc_near(site, 128);
    if (!stub) { log_line("ROOMGUARD/draw: no trampoline within +/-2GB -- skipped"); return; }

    b[n++]=0x48; b[n++]=0x83; b[n++]=0x7C; b[n++]=0x24;
    b[n++]=0x38; b[n++]=0x00;                               /* cmp qword [rsp+38],0 */
    b[n++]=0x75; off_jne = n++;                             /* jne  ok              */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&ctr,8); n+=8;     /* mov  rax,&counter    */
    b[n++]=0xF0; b[n++]=0x48; b[n++]=0xFF; b[n++]=0x00;     /* lock inc qword [rax] */
    rel = (long long)exitp - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;                  /* jmp  epilogue        */
    off_ok = n;                                             /* ok:                  */
    b[off_jne] = (unsigned char)(off_ok - (off_jne + 1));
    memcpy(b+n, orig, sizeof(orig)); n += (int)sizeof(orig);/* stolen instruction   */
    rel = (long long)(site + 7) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;                  /* jmp  back            */

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);

    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("ROOMGUARD/draw: trampoline out of rel32 range -- skipped"); return;
    }
    if (!VirtualProtect(site, 7, PAGE_EXECUTE_READWRITE, &old)) {
        log_line("ROOMGUARD/draw: VirtualProtect failed at RVA 0x%X", ROOMGUARD_DRAW_RVA);
        return;
    }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    site[5] = 0x90; site[6] = 0x90;
    VirtualProtect(site, 7, old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, 7);
    log_line("ROOMGUARD/draw: installed at RVA 0x%X -- a vertex upload whose buffer map "
             "returned NULL now leaves through the helper's own epilogue at 0x%X instead "
             "of memcpy'ing to the raw offset", ROOMGUARD_DRAW_RVA, ROOMGUARD_DRAW_EXIT);
}

static void patch_room_steam_guard(void)
{
    static const unsigned char orig[9] = {
        0x48,0x8B,0x08,                         /* mov  rcx,[rax]       */
        0x48,0x8B,0x01,                         /* mov  rax,[rcx]       */
        0xFF,0x50,0x78                          /* call qword [rax+78]  */
    };
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    unsigned char* stub;
    void* ctr = (void*)&g_rg_steam_skips;
    unsigned char b[96];
    int n = 0, off_jz, off_jmp, off_skip, off_back;
    long long rel;
    DWORD old;

    if (!mod) return;
    site = mod + ROOMGUARD_STEAM_RVA;

    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("ROOMGUARD/steam: bytes not at expected RVA 0x%X (game updated?) -- "
                 "skipped, a NULL Steam interface still crashes", ROOMGUARD_STEAM_RVA);
        return;
    }

    stub = (unsigned char*)gauge_alloc_near(site, 128);
    if (!stub) { log_line("ROOMGUARD/steam: no trampoline within +/-2GB -- skipped"); return; }

    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x08;                  /* mov  rcx,[rax]       */
    b[n++]=0x48; b[n++]=0x85; b[n++]=0xC9;                  /* test rcx,rcx         */
    b[n++]=0x74; off_jz = n++;                              /* jz   skip            */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x01;                  /* mov  rax,[rcx]       */
    b[n++]=0xFF; b[n++]=0x50; b[n++]=0x78;                  /* call qword [rax+78]  */
    b[n++]=0xEB; off_jmp = n++;                             /* jmp  back            */
    off_skip = n;                                           /* skip:                */
    b[off_jz] = (unsigned char)(off_skip - (off_jz + 1));
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&ctr,8); n+=8;     /* mov  rax,&counter    */
    b[n++]=0xF0; b[n++]=0x48; b[n++]=0xFF; b[n++]=0x00;     /* lock inc qword [rax] */
    off_back = n;                                           /* back:                */
    b[off_jmp] = (unsigned char)(off_back - (off_jmp + 1));
    rel = (long long)(site + 9) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;                  /* jmp  site+9          */

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);

    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("ROOMGUARD/steam: trampoline out of rel32 range -- skipped"); return;
    }
    if (!VirtualProtect(site, 9, PAGE_EXECUTE_READWRITE, &old)) {
        log_line("ROOMGUARD/steam: VirtualProtect failed at RVA 0x%X", ROOMGUARD_STEAM_RVA);
        return;
    }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    site[5] = 0x90; site[6] = 0x90; site[7] = 0x90; site[8] = 0x90;
    VirtualProtect(site, 9, old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, 9);
    log_line("ROOMGUARD/steam: installed at RVA 0x%X -- a cancel through a NULL Steam "
             "interface is now skipped instead of faulting", ROOMGUARD_STEAM_RVA);
}

/* ---- PART 27, the seat clamp -------------------------------------------
 *  THE MEASUREMENT THAT CHANGED THIS CODE, 2026-09-16, run 3.
 *
 *  The room menu has a **Spectator mode** toggle. It is retail, it is not in
 *  any of the exe's strings (that text lives in the UI data), and it was
 *  almost certainly never reachable in a shipped build: a room held two
 *  people, so nobody could ever be the third one who spectates. With the
 *  member cap raised it appears, and with it ON the third client:
 *
 *    * does NOT crash,
 *    * LOADS AND RENDERS THE STAGE -- it is really in the battle,
 *    * counts 2968 seat-guard skips and **0 empty fighter lists**,
 *    * and is dropped after ~40 s with "You have been disconnected."
 *
 *  The zero is the important number. With the toggle OFF the fighter vector
 *  was empty; with it ON the fighters ARE built and only the seat index is
 *  still -1. So the first two guards were skipping work the spectator path
 *  legitimately needs -- every frame, thousands of times -- and a client
 *  whose battle state machine never advances is exactly what a netcode drops.
 *
 *  So the guards become a CLAMP. A reader with no seat of its own is pointed
 *  at seat 0 instead of being sent away:
 *
 *      movsxd rcx,[rdi+0xC3C or 0xC40]   ; -1
 *      -> if negative, rcx = 0 and carry on into the stock code
 *
 *  which is what "watch" means here: the viewer reads the fight through
 *  player 1's slot. The element writes on that path (0x80189F bumps a word
 *  on it) land on the viewer's OWN copy of player 1's state, never on the
 *  wire, so a spectator cannot corrupt the players' match.
 *
 *  The empty-vector case is still a bail, because clamping to seat 0 of a
 *  vector that does not exist reads [NULL]. That is the Spectator-OFF state
 *  and it keeps the behaviour the first two guards measured.
 *
 *  THREE SITES, one shape, because the exe reads the seat index three times
 *  in two functions and every read is the same four instructions:
 *
 *      site      index      vector   resume    bail
 *      0x8034EA  +0xC40     +0x20    0x8034F8  0x80372B
 *      0x801889  +0xC3C     +0x08    0x801897  0x8018CC (needs r12d=1)
 *      0x8018A2  +0xC3C     +0x08    0x8018B0  0x8018CC (needs r12d=1)
 *
 *  All three steal the same 7 bytes (`mov rax,[rdi+0xBC0]`), so one installer
 *  builds all three and a fourth site is one more line rather than another
 *  hand-assembled stub. `resume` deliberately re-enters AFTER the movsxd the
 *  stub replaced -- re-entering before it would reload the -1 it just fixed.
 *
 *  What this does NOT claim to fix: the disconnect. If the drop is a timeout
 *  on a state machine that could not advance, the clamp removes its cause; if
 *  it is the room's transmission layer refusing a third endpoint, the clamp
 *  will not touch it and the next run says so in the same 30 s line. */

typedef struct {
    unsigned int   site_rva;     /* mov rax,[rdi+0xBC0] -- 7 bytes, always      */
    unsigned int   idx_disp;     /* the seat-index field on the same object     */
    unsigned char  vec_disp;     /* the vector's begin pointer inside it        */
    unsigned int   resume_rva;   /* re-entry, AFTER the movsxd being replaced   */
    unsigned int   bail_rva;     /* where an empty vector goes instead          */
    unsigned char  bail_r12;     /* 1: the bail target expects r12d = 1         */
    const char*    what;         /* for the log line                           */
} room3_clamp_t;

static const room3_clamp_t g_room3_clamps[] = {
    { 0x8034EA, 0xC40, 0x20, 0x8034F8, 0x80372B, 0, "battle state" },
    { 0x801889, 0xC3C, 0x08, 0x801897, 0x8018CC, 1, "battle set-up" },
    { 0x8018A2, 0xC3C, 0x08, 0x8018B0, 0x8018CC, 1, "set-up, second read" },
};
#define ROOM3_NCLAMPS ((int)(sizeof(g_room3_clamps)/sizeof(g_room3_clamps[0])))

static void room3_kick_battle_start(void);   /* defined with the gate logger */

static int room3_clamp_one(const room3_clamp_t* c)
{
    static const unsigned char orig[7] = {
        0x48,0x8B,0x87,0xC0,0x0B,0x00,0x00      /* mov rax,[rdi+0xbc0] */
    };
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    unsigned char* stub;
    void* c_view  = (void*)&g_room3_clamped;
    void* c_ctx   = (void*)&g_room3_ctx;
    void* c_empty = (void*)&g_room3_skip_empty;
    unsigned char b[160];
    int n = 0, off_jz_pass, off_jz_empty, off_jns_pass, off_pass, off_empty;
    long long rel;
    DWORD old;

    if (!mod) return 0;
    site = mod + c->site_rva;

    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("ROOM3/clamp: bytes not at expected RVA 0x%X (%s) -- skipped",
                 c->site_rva, c->what);
        return 0;
    }
    stub = (unsigned char*)gauge_alloc_near(site, 192);
    if (!stub) { log_line("ROOM3/clamp: no trampoline near 0x%X -- skipped", c->site_rva); return 0; }

    memcpy(b+n, orig, sizeof(orig)); n += (int)sizeof(orig);   /* mov rax,[rdi+0xBC0]  */
    /* Park the battle context for the heartbeat. rax is the only scratch here and it
       already holds the container, so it goes through the stack -- balanced, and mid
       function, so nothing depends on rsp between these two instructions. */
    b[n++]=0x50;                                               /* push rax             */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&c_ctx,8); n+=8;      /* mov rax,&g_room3_ctx */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x38;                     /* mov [rax],rdi        */
    b[n++]=0x58;                                               /* pop rax              */
    if (c->site_rva == 0x8034EA) {
        /* One site only, and this one, because it is the per-frame battle state machine:
           the kick needs the GAME thread and a live battle object, and both are true
           here. Everything volatile is saved -- the stolen instruction below still has
           to run exactly as the exe wrote it. */
        void* kick = (void*)&room3_kick_battle_start;
        b[n++]=0x51; b[n++]=0x52;                              /* push rcx, rdx        */
        b[n++]=0x41; b[n++]=0x50; b[n++]=0x41; b[n++]=0x51;    /* push r8, r9           */
        b[n++]=0x50;                                           /* push rax              */
        b[n++]=0x55;                                           /* push rbp              */
        b[n++]=0x48; b[n++]=0x89; b[n++]=0xE5;                 /* mov rbp,rsp           */
        b[n++]=0x48; b[n++]=0x83; b[n++]=0xE4; b[n++]=0xF0;    /* and rsp,-16           */
        b[n++]=0x48; b[n++]=0x83; b[n++]=0xEC; b[n++]=0x20;    /* sub rsp,0x20          */
        b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&kick,8); n+=8;   /* mov rax,&kick         */
        b[n++]=0xFF; b[n++]=0xD0;                              /* call rax              */
        b[n++]=0x48; b[n++]=0x89; b[n++]=0xEC;                 /* mov rsp,rbp           */
        b[n++]=0x5D;                                           /* pop rbp               */
        b[n++]=0x58;                                           /* pop rax               */
        b[n++]=0x41; b[n++]=0x59; b[n++]=0x41; b[n++]=0x58;    /* pop r9, r8            */
        b[n++]=0x5A; b[n++]=0x59;                              /* pop rdx, rcx          */
        /* rax must be the container again for the rest of the stub */
        memcpy(b+n, orig, sizeof(orig)); n += (int)sizeof(orig);
    }
    b[n++]=0x48; b[n++]=0x85; b[n++]=0xC0;                     /* test rax,rax         */
    b[n++]=0x74; off_jz_pass = n++;                            /* jz  pass (vanilla)   */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x48; b[n++]=c->vec_disp; /* mov rcx,[rax+vec]    */
    b[n++]=0x48; b[n++]=0x85; b[n++]=0xC9;                     /* test rcx,rcx         */
    b[n++]=0x74; off_jz_empty = n++;                           /* jz  empty            */
    b[n++]=0x48; b[n++]=0x63; b[n++]=0x8F;                     /* movsxd rcx,          */
    b[n++]=(unsigned char)( c->idx_disp        & 0xFF);        /*   [rdi+idx]          */
    b[n++]=(unsigned char)((c->idx_disp >>  8) & 0xFF);
    b[n++]=(unsigned char)((c->idx_disp >> 16) & 0xFF);
    b[n++]=(unsigned char)((c->idx_disp >> 24) & 0xFF);
    b[n++]=0x48; b[n++]=0x85; b[n++]=0xC9;                     /* test rcx,rcx         */
    b[n++]=0x79; off_jns_pass = n++;                           /* jns pass (has a seat)*/
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&c_view,8); n+=8;     /* mov rax,&clamped     */
    b[n++]=0xF0; b[n++]=0x48; b[n++]=0xFF; b[n++]=0x00;        /* lock inc qword [rax] */
    memcpy(b+n, orig, sizeof(orig)); n += (int)sizeof(orig);   /* rax = container again*/
    b[n++]=0x31; b[n++]=0xC9;                                  /* xor ecx,ecx -> seat 0*/
    rel = (long long)(mod + c->resume_rva) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;                     /* jmp resume           */
    off_pass = n;                                              /* pass:                */
    b[off_jz_pass]  = (unsigned char)(off_pass - (off_jz_pass  + 1));
    b[off_jns_pass] = (unsigned char)(off_pass - (off_jns_pass + 1));
    rel = (long long)(site + 7) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;                     /* jmp site+7           */
    off_empty = n;                                             /* empty:               */
    b[off_jz_empty] = (unsigned char)(off_empty - (off_jz_empty + 1));
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&c_empty,8); n+=8;    /* mov rax,&empty       */
    b[n++]=0xF0; b[n++]=0x48; b[n++]=0xFF; b[n++]=0x00;        /* lock inc qword [rax] */
    if (c->bail_r12) {
        b[n++]=0x41; b[n++]=0xBC;                              /* mov r12d,1 -- what   */
        b[n++]=0x01; b[n++]=0x00; b[n++]=0x00; b[n++]=0x00;    /*   the bail expects   */
    }
    rel = (long long)(mod + c->bail_rva) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;                     /* jmp bail             */

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);

    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("ROOM3/clamp: trampoline out of rel32 range at 0x%X -- skipped", c->site_rva);
        return 0;
    }
    if (!VirtualProtect(site, 7, PAGE_EXECUTE_READWRITE, &old)) {
        log_line("ROOM3/clamp: VirtualProtect failed at RVA 0x%X", c->site_rva);
        return 0;
    }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    site[5] = 0x90; site[6] = 0x90;
    VirtualProtect(site, 7, old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, 7);
    log_line("ROOM3/clamp: 0x%X (%s) -- seat index %s+0x%X, %d-byte stub at %p",
             c->site_rva, c->what, "rdi", c->idx_disp, n, (void*)stub);
    return 1;
}


/* ---- PART 27, the role gate --------------------------------------------
 *  THE ONE BRANCH THAT DECIDES WHETHER A SPECTATOR SEES ANYTHING.
 *
 *      exe+0x800579  mov  eax,[rsi+0xC34]    ; role: 0 on both players, 1 on the spectator
 *      exe+0x80057F  test eax,eax
 *      exe+0x800581  jne  0x801259           ; role != 0 -> skip everything
 *
 *  What is skipped is the whole battle build: it empties the four vectors of
 *  the fighter container at ctx+0xBC0 (`end = begin` at +0x10, +0x28, +0x40,
 *  +0x58) and fills them again. What it jumps to, `0x801259`, clears three
 *  flags and returns. That is the entire "no side" path in this function --
 *  Bandai's spectator builds nothing at all, which is exactly what the probe
 *  measured on the third client: `fighters 0 and 0`, on a client that is
 *  receiving ~60 packets a second from each player.
 *
 *  The role comes from `[obj+0x480]` a few hundred bytes earlier:
 *      0 -> role 0, seats 0/1      "I am player 1"
 *      1 -> role 0, seats 1/0      "I am player 2"
 *      2 -> role 1, seats untouched (-1/-1)   <- the spectator
 *    >=3 -> role 2, seats untouched
 *
 *  So this patch makes role 1 -- and only role 1 -- take the players' path.
 *  Role 2 is left alone deliberately: it was never observed, it belongs to
 *  some other context, and a patch that silences a branch it has not measured
 *  is how a real bug gets buried.
 *
 *  ⚠ WHAT THIS IS: an experiment, and the honest description of it is that the
 *  spectator is made to build the match as a player would. It may work,
 *  because the data is already arriving. It may also make the client behave
 *  like a second player 1 on the wire, in which case the two real players
 *  will say so immediately and this is a dead end -- which is itself the
 *  answer to the question the session is on.
 *
 *  The seats stay -1 and the clamp keeps serving seat 0 for them; setting
 *  them here would be a second change in the same measurement. One at a time. */
#define ROOM3_ROLE_RVA  0x800579   /* mov eax,[rsi+0xC34] -- 6 bytes, clean steal */

static void patch_room3_role_gate(void)
{
    static const unsigned char orig[6] = {
        0x8B,0x86,0x34,0x0C,0x00,0x00           /* mov eax,[rsi+0xc34] */
    };
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    unsigned char* stub;
    void* ctr = (void*)&g_room3_role_forced;
    unsigned char b[128];
    int n = 0, off_jne_pass, off_pass;
    long long rel;
    DWORD old;

    if (!mod) return;
    site = mod + ROOM3_ROLE_RVA;

    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("ROOM3/role: bytes not at expected RVA 0x%X (game updated?) -- skipped, "
                 "a spectator still builds no fighters", ROOM3_ROLE_RVA);
        return;
    }
    stub = (unsigned char*)gauge_alloc_near(site, 160);
    if (!stub) { log_line("ROOM3/role: no trampoline within +/-2GB -- skipped"); return; }

    memcpy(b+n, orig, sizeof(orig)); n += (int)sizeof(orig);  /* mov eax,[rsi+0xC34]  */
    b[n++]=0x83; b[n++]=0xF8; b[n++]=0x01;                    /* cmp eax,1            */
    b[n++]=0x75; off_jne_pass = n++;                          /* jne pass (0 or 2)    */
    b[n++]=0x50;                                              /* push rax             */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&ctr,8); n+=8;       /* mov rax,&counter     */
    b[n++]=0xF0; b[n++]=0x48; b[n++]=0xFF; b[n++]=0x00;       /* lock inc qword [rax] */
    b[n++]=0x58;                                              /* pop rax              */
    b[n++]=0x31; b[n++]=0xC0;                                 /* xor eax,eax          */
    b[n++]=0x89; b[n++]=0x86;                                 /* mov [rsi+0xC34],eax  */
    b[n++]=0x34; b[n++]=0x0C; b[n++]=0x00; b[n++]=0x00;       /*   so later readers   */
    off_pass = n;                                             /*   agree              */
    b[off_jne_pass] = (unsigned char)(off_pass - (off_jne_pass + 1));
    rel = (long long)(site + 6) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;                    /* jmp site+6           */

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);

    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("ROOM3/role: trampoline out of rel32 range -- skipped"); return;
    }
    if (!VirtualProtect(site, 6, PAGE_EXECUTE_READWRITE, &old)) {
        log_line("ROOM3/role: VirtualProtect failed at RVA 0x%X", ROOM3_ROLE_RVA);
        return;
    }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    site[5] = 0x90;
    VirtualProtect(site, 6, old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, 6);
    log_line("ROOM3/role: installed at RVA 0x%X (%d-byte stub at %p) -- role 1 (a room "
             "member with no side) now takes the players' battle build instead of the "
             "empty path at 0x801259. Role 2 is untouched.", ROOM3_ROLE_RVA, n, (void*)stub);
}


/* ---- PART 27, the spectator takes player 1's seat ----------------------
 *  MEASURED 2026-09-16, run with the role gate: forcing role 1 -> 0 made the
 *  third client BUILD THE MATCH for the first time --
 *
 *      ROOM3/state: seats -1/-1, role 0, state 2, fighters 2 and 2
 *
 *  -- and it died ten seconds later at a fourth read of the same missing seat
 *  (exe+0x803FCD, container in rcx this time, so the clamps did not cover it).
 *  With the fighter vector now populated, `base[-1]` no longer returns NULL:
 *  it returns a garbage pointer, and the fault simply moves one instruction
 *  along. Clamping every reader is the wrong end of the problem.
 *
 *  The right end is the dispatch that left the seats at -1 in the first place:
 *
 *      exe+0x80049C  mov edx,[rax+0x480]
 *      exe+0x8004A2  test edx,edx ; je 0x8004E3   ; 0 -> I am player 1
 *      exe+0x8004A6  sub  edx,1   ; je 0x8004C8   ; 1 -> I am player 2
 *      exe+0x8004AB  cmp  edx,1   ; je 0x8004BC   ; 2 -> role 1, seats untouched
 *      exe+0x8004B0  mov  [rsi+0xC34],2           ; >=3 -> role 2
 *
 *  and the player-1 arm at 0x8004E3 writes everything the rest of the battle
 *  code expects:
 *
 *      role 0xC34 = 0, flag 0xC3A = 1, seat 0xC3C = 0, seat 0xC40 = 1,
 *      and 0xC48 = [ctx+0x3F8], which the "no side" arm never sets at all.
 *
 *  So this patch retargets ONE branch: mode 2 -- a room member with no side --
 *  takes the player-1 arm. One byte, 0x0C -> 0x33, no trampoline.
 *
 *  ⚠ What it means, stated plainly: the spectator becomes, locally, a client
 *  that believes it is player 1. It builds both fighters and reads the fight
 *  through player 1's slot. Whether it also starts behaving like player 1 on
 *  the wire is the thing to watch -- the packet counters already say it sends
 *  one packet a second against the players' sixty, so the sending side is
 *  driven by something else, but "already" is not "still" once this lands.
 *
 *  Mode >= 3 (role 2) is untouched. It was never observed and is not ours. */
#define ROOM3_ARM_RVA   0x8004BC   /* the mode-2 arm: mov [rsi+0xC34],1 ; jmp -- 12 bytes */
#define ROOM3_ARM_P1    0x8004E3   /* the player-1 arm            */
#define ROOM3_ARM_P2    0x8004C8   /* the player-2 arm            */
#ifndef ROOM3_SEAT_ARM
#define ROOM3_SEAT_ARM  1
#endif
/* Silence the spectator's outgoing player stream. MEASURED 2026-09-16: sent down the
   player-1 arm the third client broadcasts a player-1 stream of its own, ~60 packets a
   second, alongside the real host's -- and with three clients doing that, NOBODY leaves
   the loading screen. A spectator that talks can freeze the whole room, which is worse
   than a spectator that cannot see. So the same patch that gives it a seat now also
   marks it, and the mark suppresses the two battle-stream types on the way out. */

static void patch_room3_spectator_as_p1(void)
{
    static const unsigned char orig[12] = {
        0xC7,0x86,0x34,0x0C,0x00,0x00,0x01,0x00,0x00,0x00,   /* mov dword [rsi+0xC34],1 */
        0xEB,0x48                                            /* jmp 0x800510            */
    };
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    unsigned char* stub;
    unsigned char* arm;
    void* flag = (void*)&g_room3_is_spectator;
    void* mode = (void*)&g_room3_mode;
    unsigned char b[64];
    int n = 0;
    long long rel;
    DWORD old;

    if (!mod) return;
    site = mod + ROOM3_ARM_RVA;
    arm  = mod + (ROOM3_SEAT_ARM == 2 ? ROOM3_ARM_P2 : ROOM3_ARM_P1);

    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("ROOM3/arm: bytes not at expected RVA 0x%X (game updated?) -- skipped, "
                 "a member with no side keeps seat -1", ROOM3_ARM_RVA);
        return;
    }
    stub = (unsigned char*)gauge_alloc_near(site, 96);
    if (!stub) { log_line("ROOM3/arm: no trampoline within +/-2GB -- skipped"); return; }

    /* ⚠ rax must survive: the player arms read the context through it two instructions
       later (`mov rax,[rax+0x3F8]`). Hence the push/pop rather than a free scratch. */
    b[n++]=0x51;                                              /* push rcx              */
    b[n++]=0x8B; b[n++]=0x88;                                 /* mov ecx,[rax+0x480]   */
    b[n++]=0x80; b[n++]=0x04; b[n++]=0x00; b[n++]=0x00;       /*   the mode, verbatim  */
    b[n++]=0x50;                                              /* push rax              */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&mode,8); n+=8;      /* mov rax,&g_room3_mode */
    b[n++]=0x89; b[n++]=0x08;                                 /* mov [rax],ecx         */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&flag,8); n+=8;      /* mov rax,&is_spectator */
    b[n++]=0xC6; b[n++]=0x00; b[n++]=0x01;                    /* mov byte [rax],1      */
    b[n++]=0x58;                                              /* pop rax               */
    b[n++]=0x59;                                              /* pop rcx               */
    rel = (long long)arm - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;                    /* jmp the player arm    */

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);

    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("ROOM3/arm: trampoline out of rel32 range -- skipped"); return;
    }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("ROOM3/arm: VirtualProtect failed at RVA 0x%X", ROOM3_ARM_RVA);
        return;
    }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    memset(site + 5, 0x90, sizeof(orig) - 5);
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));
    log_line("ROOM3/arm: installed at RVA 0x%X (%d-byte stub at %p) -- a member with no "
             "side is marked as the spectator and sent down the player-%d arm; its outgoing "
             "battle stream is %s", ROOM3_ARM_RVA, n, (void*)stub, ROOM3_SEAT_ARM,
             ROOM3_MUTE_SPECTATOR ? "SUPPRESSED" : "left alone");
}


/* ---- PART 27, the participant gate -------------------------------------
 *  THE BARRIER, found 2026-09-17 by diffing a playing host against a stuck
 *  spectator rather than by reading the protocol.
 *
 *  The battle context keeps its own match clock at +0xC38. On the host it runs
 *  0x012C (300 s) down to zero; on the spectator it sits at 300 forever. The
 *  same diff shows the state at +0xCE0: **0 on the host, 2 on the spectator**.
 *  And the code that writes that 2 is a search:
 *
 *      exe+0x8036D0  call 0x140A77920          ; the online manager
 *      exe+0x8036D9  mov  rax,[rcx+8]          ; its participant table
 *      exe+0x8036E5  movzx r8d,word [rax+0x18] ; how many entries
 *      exe+0x8036EF  add  rax,0xA08            ; the first one
 *      exe+0x8036F5  mov  rdx,[rax+0x58]       ; this entry's key
 *      exe+0x8036F9  cmp  rdx,rbx              ; rbx = MY descriptor, [obj+0x3F8]
 *      exe+0x8036FC  je   0x803719             ; found -> state stays 0, the fight runs
 *      exe+0x803701  add  rax,0x188            ; next entry
 *      exe+0x80370C  mov  esi,2                ; NOT FOUND -> state 2
 *
 *  A client asks "am I one of the participants of this match?" and the answer
 *  for a spectator is no, permanently. That is the whole loading screen: not a
 *  missing packet, not a handshake nobody answers -- a membership test that a
 *  third party cannot pass by design.
 *
 *  So the gate is skipped, and ONLY for the client that marked itself as the
 *  spectator at the mode-2 arm. `mov esi,2` is exactly five bytes, so the
 *  detour is clean, and on the normal path the stolen instruction runs
 *  unchanged: a real player whose descriptor is genuinely missing still gets
 *  state 2, which is a real error and not ours to silence.
 *
 *  Leaving esi alone means the state keeps the value the function read at
 *  entry (`mov esi,[rcx+0xCE0]`), which for a client that has finished loading
 *  is 0 -- the same value the search produces when it succeeds. */
#define ROOM3_PART_RVA   0x80370C   /* mov esi,2 -- 5 bytes, the not-found arm */
#define ROOM3_PART_NEXT  0x803711   /* mov [rdi+0xCE0],esi                     */

static void patch_room3_participant_gate(void)
{
    static const unsigned char orig[5] = { 0xBE,0x02,0x00,0x00,0x00 };   /* mov esi,2 */
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    unsigned char* stub;
    void* flag = (void*)&g_room3_is_spectator;
    void* ctr  = (void*)&g_room3_gate_passed;
    unsigned char b[96];
    int n = 0, off_jne, off_keep;
    long long rel;
    DWORD old;

    if (!mod) return;
    site = mod + ROOM3_PART_RVA;

    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("ROOM3/part: bytes not at expected RVA 0x%X (game updated?) -- skipped, "
                 "a spectator stays in state 2 on the loading screen", ROOM3_PART_RVA);
        return;
    }
    stub = (unsigned char*)gauge_alloc_near(site, 128);
    if (!stub) { log_line("ROOM3/part: no trampoline within +/-2GB -- skipped"); return; }

    /* rax holds the table cursor and rbx the descriptor; both are dead after this point,
       but the flag test goes through the stack anyway so the stub cannot be blamed for a
       register it did not need to touch. `pop` does not disturb the flags `cmp` sets. */
    b[n++]=0x50;                                              /* push rax              */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&flag,8); n+=8;      /* mov rax,&is_spectator */
    b[n++]=0x80; b[n++]=0x38; b[n++]=0x00;                    /* cmp byte [rax],0      */
    b[n++]=0x58;                                              /* pop rax               */
    b[n++]=0x75; off_jne = n++;                               /* jne keep (spectator)  */
    memcpy(b+n, orig, sizeof(orig)); n += (int)sizeof(orig);  /* mov esi,2 -- stolen   */
    rel = (long long)(mod + ROOM3_PART_NEXT) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;                    /* jmp on, state = 2     */
    off_keep = n;                                             /* keep:                 */
    b[off_jne] = (unsigned char)(off_keep - (off_jne + 1));
    b[n++]=0x50;                                              /* push rax              */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&ctr,8); n+=8;       /* mov rax,&counter      */
    b[n++]=0xF0; b[n++]=0x48; b[n++]=0xFF; b[n++]=0x00;       /* lock inc qword [rax]  */
    b[n++]=0x58;                                              /* pop rax               */
    rel = (long long)(mod + ROOM3_PART_NEXT) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;                    /* jmp on, esi untouched */

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);

    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("ROOM3/part: trampoline out of rel32 range -- skipped"); return;
    }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("ROOM3/part: VirtualProtect failed at RVA 0x%X", ROOM3_PART_RVA);
        return;
    }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));
    log_line("ROOM3/part: installed at RVA 0x%X (%d-byte stub at %p) -- the spectator no "
             "longer fails the 'am I a participant of this match' test, so its state stays "
             "0 instead of 2. Players are untouched.", ROOM3_PART_RVA, n, (void*)stub);
}


/* ---- PART 27, the battle-start probe -----------------------------------
 *  WHERE THIS CAME FROM. Diffing the host's battle object across the moment
 *  its match clock starts falling isolates two flags that flip together:
 *
 *      +0xCCC  0 -> 1      +0xCD5  0 -> 1
 *
 *  and both stay 0 on the spectator for the whole match. `+0xCD5` has exactly
 *  three references in the entire exe -- a test, a clear, and ONE write of 1,
 *  at exe+0x805A2E, unconditional inside the function at **exe+0x805870**.
 *
 *  That function is `SOnlineAction` **slot 45** (its vtable is at RVA
 *  0x14A3888 -- note that the address recorded in the research, 0x1414A18A8,
 *  is wrong and reads as string data). So the spectator is not failing a test
 *  inside battle start: **battle start is never called on it at all.**
 *
 *  It has no direct callers -- it is reached through the vtable -- and the
 *  +0x168 slot offset is shared with unrelated classes, so a static scan of
 *  call sites gives thirty candidates and no answer. A backtrace taken on the
 *  client where it DOES run gives the real one, once, in a line.
 *
 *  Read-only: the stolen prologue is re-executed verbatim and every volatile
 *  register a caller could be passing arguments in is saved across the log
 *  call. rsp is realigned to 16 before the call, because at function entry it
 *  is 8 mod 16 and four pushes leave it there. */
#define ROOM3_START_RVA   0x805870
#define ROOM3_START_BACK  0x80587B   /* after the three stolen instructions */
/* The battle-start caller, named by the probe on 2026-09-17: exe+0x6C6095 is the return
   address of `call [rax+0x168]` at exe+0x6C608F, inside the 3 KB function at 0x6C5390.
   That call is unconditional where it sits, so the decision is higher up -- and the next
   question is simply whether the spectator enters that function at all. Same probe, one
   level up: five bytes of prologue (`mov [rsp+0x10],rbx`) stolen the same way. */
#define ROOM3_CALLER_RVA  0x6C5390
#define ROOM3_CALLER_BACK 0x6C5395

static volatile LONG g_room3_start_seen = 0;
static volatile LONG g_room3_caller_seen = 0;

/* ⚠ RtlCaptureStackBackTrace stops at the stub: cave code has no unwind information,
   so the first attempt printed exactly one frame -- the stub itself. The caller is on
   the stack anyway, because the game reached the function through a CALL, so the stub
   reads the return address directly and hands it over. */
static void room3_log_battle_start(void* ret)
{
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    if (InterlockedCompareExchange(&g_room3_start_seen, 1, 0) != 0) return;
    if (ret && mod && (unsigned char*)ret > mod && (unsigned char*)ret < mod + 0x2000000)
        log_line("ROOM3/start: SOnlineAction slot 45 (battle start, exe+0x%X) RAN on this "
                 "client, called from exe+0x%X", ROOM3_START_RVA,
                 (unsigned)((unsigned char*)ret - mod));
    else
        log_line("ROOM3/start: SOnlineAction slot 45 RAN on this client, caller %p is "
                 "outside the exe", ret);
    room3_backtrace("start");
}

static void room3_log_start_caller(void* ret)
{
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    if (InterlockedCompareExchange(&g_room3_caller_seen, 1, 0) != 0) return;
    log_line("ROOM3/start: the FUNCTION THAT CALLS battle start (exe+0x%X) ran on this "
             "client, called from exe+0x%X -- if the spectator prints this line but never "
             "the 'battle start RAN' one, the decision is inside it",
             ROOM3_CALLER_RVA,
             (mod && (unsigned char*)ret > mod && (unsigned char*)ret < mod + 0x2000000)
                 ? (unsigned)((unsigned char*)ret - mod) : 0);
}

static void patch_room3_caller_probe(void)
{
    static const unsigned char orig[5] = { 0x48,0x89,0x5C,0x24,0x10 };  /* mov [rsp+0x10],rbx */
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    unsigned char* stub;
    void* fn = (void*)&room3_log_start_caller;
    unsigned char b[128];
    int n = 0;
    long long rel;
    DWORD old;

    if (!mod) return;
    site = mod + ROOM3_CALLER_RVA;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("ROOM3/start: caller bytes not at expected RVA 0x%X -- probe skipped",
                 ROOM3_CALLER_RVA);
        return;
    }
    stub = (unsigned char*)gauge_alloc_near(site, 160);
    if (!stub) { log_line("ROOM3/start: no trampoline near the caller -- skipped"); return; }

    b[n++]=0x51; b[n++]=0x52;                                /* push rcx, rdx         */
    b[n++]=0x41; b[n++]=0x50; b[n++]=0x41; b[n++]=0x51;      /* push r8, r9           */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xEC; b[n++]=0x28;      /* sub rsp,0x28          */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x48;  /* mov rcx,[rsp+0x48] */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&fn,8); n+=8;       /* mov rax,&logger       */
    b[n++]=0xFF; b[n++]=0xD0;                                /* call rax              */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xC4; b[n++]=0x28;      /* add rsp,0x28          */
    b[n++]=0x41; b[n++]=0x59; b[n++]=0x41; b[n++]=0x58;      /* pop r9, r8            */
    b[n++]=0x5A; b[n++]=0x59;                                /* pop rdx, rcx          */
    memcpy(b+n, orig, sizeof(orig)); n += (int)sizeof(orig); /* stolen prologue       */
    rel = (long long)(mod + ROOM3_CALLER_BACK) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);
    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("ROOM3/start: caller trampoline out of range -- skipped"); return; }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("ROOM3/start: VirtualProtect failed at the caller"); return; }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));
    log_line("ROOM3/start: caller probe installed at RVA 0x%X (%d-byte stub at %p)",
             ROOM3_CALLER_RVA, n, (void*)stub);
}

static void patch_room3_start_probe(void)
{
    static const unsigned char orig[11] = {
        0x48,0x8B,0xC4,                         /* mov  rax,rsp   */
        0x57,                                   /* push rdi       */
        0x48,0x81,0xEC,0x90,0x00,0x00,0x00      /* sub  rsp,0x90  */
    };
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    unsigned char* stub;
    void* fn = (void*)&room3_log_battle_start;
    unsigned char b[128];
    int n = 0;
    long long rel;
    DWORD old;

    if (!mod) return;
    site = mod + ROOM3_START_RVA;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("ROOM3/start: bytes not at expected RVA 0x%X -- probe skipped",
                 ROOM3_START_RVA);
        return;
    }
    stub = (unsigned char*)gauge_alloc_near(site, 160);
    if (!stub) { log_line("ROOM3/start: no trampoline within +/-2GB -- skipped"); return; }

    b[n++]=0x51;                                             /* push rcx  (this)      */
    b[n++]=0x52;                                             /* push rdx              */
    b[n++]=0x41; b[n++]=0x50;                                /* push r8               */
    b[n++]=0x41; b[n++]=0x51;                                /* push r9               */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xEC; b[n++]=0x28;      /* sub rsp,0x28          */
    /* the caller's return address: 4 pushes (0x20) + 0x28 of shadow below it */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x48;  /* mov rcx,[rsp+0x48] */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&fn,8); n+=8;       /* mov rax,&logger       */
    b[n++]=0xFF; b[n++]=0xD0;                                /* call rax              */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xC4; b[n++]=0x28;      /* add rsp,0x28          */
    b[n++]=0x41; b[n++]=0x59;                                /* pop r9                */
    b[n++]=0x41; b[n++]=0x58;                                /* pop r8                */
    b[n++]=0x5A;                                             /* pop rdx               */
    b[n++]=0x59;                                             /* pop rcx               */
    memcpy(b+n, orig, sizeof(orig)); n += (int)sizeof(orig); /* the real prologue     */
    rel = (long long)(mod + ROOM3_START_BACK) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;                   /* jmp back              */

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);

    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("ROOM3/start: trampoline out of rel32 range -- skipped"); return;
    }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("ROOM3/start: VirtualProtect failed at RVA 0x%X", ROOM3_START_RVA);
        return;
    }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    memset(site + 5, 0x90, sizeof(orig) - 5);
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));
    log_line("ROOM3/start: probe installed at RVA 0x%X (%d-byte stub at %p) -- the first "
             "call to battle start on this client will print its caller chain",
             ROOM3_START_RVA, n, (void*)stub);
}


/* ---- PART 27, the battle-start gate ------------------------------------
 *  THE END OF THE CHAIN, 2026-09-17. Each step was measured, not guessed:
 *
 *    the spectator's local match clock (+0xC38) never leaves 300
 *      -> the two flags that flip when a fight starts (+0xCCC, +0xCD5) stay 0
 *      -> +0xCD5 has ONE write in the whole exe, unconditional, inside
 *         SOnlineAction slot 45 at exe+0x805870
 *      -> an entry probe says that function never runs on the spectator,
 *         and names its caller: exe+0x6C5390
 *      -> a probe one level up says THAT never runs either, and names
 *         exe+0x6C5185
 *      -> and there the call is guarded:
 *
 *      exe+0x6C5162  mov  rax,[rsi+0x318]
 *      exe+0x6C5169  cmp  byte [rax+0xE8],0
 *      exe+0x6C5170  jne  0x6C5186          ; skip
 *      exe+0x6C5172  cmp  byte [rsi+0x468],0
 *      exe+0x6C5179  jne  0x6C5186          ; skip
 *      exe+0x6C517B  mov  dl,1 ; mov rcx,rsi ; call 0x6C5390
 *
 *  Two one-byte flags. Either one set means "do not start the battle", and on
 *  a spectator one of them is set for the whole match. That is the loading
 *  screen, in two comparisons -- no packet, no handshake, no timeout.
 *
 *  This jumps straight to the call for the client that marked itself the
 *  spectator, and logs both flags the first time so the write-up can say WHICH
 *  one was set rather than "one of them". Everyone else runs the stock test:
 *  those flags mean something for a real player (a pause, a teardown, a replay
 *  -- unknown), and silencing them for everybody would be the kind of blind
 *  patch this session has been avoiding. */
#define ROOM3_GATE_RVA   0x6C5162   /* mov rax,[rsi+0x318] -- 7 bytes  */
#define ROOM3_GATE_BACK  0x6C5169   /* the stock test                  */
#define ROOM3_GATE_CALL  0x6C517B   /* mov dl,1 ; mov rcx,rsi ; call   */

static volatile LONG g_room3_gate_seen = 0;
static volatile LONG g_room3_entry_seen = 0;
static volatile LONG g_room3_set4e_seen = 0;

/* SOnlineAction slot 72 (exe+0x8092E0) writes the 8-byte scene parameter at this+0x4E.
   The whole-vtable map showed both players calling it at the instant the battle-start
   cascade begins, and the spectator never -- it only ever calls the matching getter,
   slot 73. Whoever calls the setter is the last unknown in the chain, so: name it. */
static void room3_log_set4e(void* ret, void* value)
{
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    if (InterlockedCompareExchange(&g_room3_set4e_seen, 1, 0) != 0) return;
    log_line("ROOM3/set4e: the scene parameter at this+0x4E was written on this client, "
             "from exe+0x%X (value %p)",
             (mod && (unsigned char*)ret > mod && (unsigned char*)ret < mod + 0x2000000)
                 ? (unsigned)((unsigned char*)ret - mod) : 0, value);
}

/* The function that leads to battle start (exe+0x6C5070) opens with
       mov eax,0x130 ; cmp ax,[rcx+0x3A0] ; je <return>
   so a client can enter it and leave immediately. The probe that fired at +0xF2 could
   not tell that apart from "never called", which is why this one sits at the entry and
   simply prints the field being compared, on both clients, before anything is changed. */
static void room3_log_entry(void* self, void* ret)
{
    unsigned char* s2 = (unsigned char*)self;
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned int r = (mod && (unsigned char*)ret > mod && (unsigned char*)ret < mod + 0x2000000)
                     ? (unsigned)((unsigned char*)ret - mod) : 0;
    if (InterlockedCompareExchange(&g_room3_entry_seen, 1, 0) != 0) return;
    __try {
        unsigned short v = *(unsigned short*)(s2 + 0x3A0);
        log_line("ROOM3/entry: exe+0x6C5070 entered on this client, called from exe+0x%X, "
                 "[this+0x3A0] = 0x%X (0x130 returns at once)", r, v);
    } __except(EXCEPTION_EXECUTE_HANDLER) {
        log_line("ROOM3/entry: exe+0x6C5070 entered from exe+0x%X, field unreadable", r);
    }
}

/* ---- PART 27, the battle-start kick ------------------------------------
 *  THE HYPOTHESIS THIS TESTS, 2026-09-17.
 *
 *  Battle start is SOnlineAction slot 45 (exe+0x805870). It sets the two flags
 *  that make a client's match run (+0xCCC, +0xCD5) and it is UNCONDITIONAL once
 *  entered -- five probes proved it simply never runs on the spectator, because
 *  the 3 KB routine that ends by calling it (exe+0x6C5390) is itself only
 *  reached through the gameplay event pipe, and a spectator posts no gameplay
 *  events.
 *
 *  So: call it once, by hand, on the spectator's own object. The object is the
 *  same `this` the clamp stubs already park in g_room3_ctx -- +0xC38 is its
 *  match clock, +0xCD5 the flag slot 45 writes, so there is no ambiguity about
 *  which instance this is.
 *
 *  ⚠ This deliberately SKIPS everything 0x6C5390 does before the call. If slot
 *  45 is self-contained -- it walks the fighter list and arms the battle -- the
 *  spectator starts simulating and we have the lever. If it depends on that
 *  preamble, this crashes and the RVA says which part. Either answer is worth
 *  one run; neither is a guess.
 *
 *  It runs from the clamp stub at 0x8034EA, i.e. on the GAME thread inside the
 *  per-frame battle state machine, once, and only on the client that marked
 *  itself the spectator at the mode-2 arm. */
/* ⚠ BOTH OFF as of 2026-09-17. The kick answered its question -- slot 45 is safe to call
   by hand and does set +0xCD5, and forcing +0xCCC as well changes nothing, so the two
   flags are consequences and not the gate. But the run that proved it also froze the
   PLAYERS' match timer at 123: a hand-called battle start is not side-effect free, and the
   control packet types (04/0E/40) are not muted, so the spectator can still tell the two
   participants something they only expect once. Experiments that answer their question
   come back out of the build -- especially the ones that touch other people's match. */
#ifndef ROOM3_KICK_START
#define ROOM3_KICK_START 0
#endif
#ifndef ROOM3_FORCE_CCC
#define ROOM3_FORCE_CCC 0
#endif
#define ROOM3_SLOT45_RVA 0x805870

static volatile LONG g_room3_kicked = 0;

static void room3_kick_battle_start(void)
{
    unsigned char* mod;
    void* ctx = (void*)g_room3_ctx;
    if (!ROOM3_KICK_START || !g_room3_is_spectator || !ctx) return;
    if (InterlockedCompareExchange(&g_room3_kicked, 1, 0) != 0) return;
    mod = (unsigned char*)GetModuleHandleA(NULL);
    if (!mod) return;
    __try {
        /* already running? then there is nothing to kick and saying so is the
           useful outcome, not calling it twice. */
        if (*(unsigned char*)((unsigned char*)ctx + 0xCD5)) {
            log_line("ROOM3/kick: +0xCD5 is already set on this client -- battle start "
                     "ran by itself, nothing to do");
            return;
        }
        log_line("ROOM3/kick: calling SOnlineAction slot 45 (exe+0x%X) by hand on %p "
                 "-- clock %d, +0xCD5 %d, +0xCCC %d before the call",
                 ROOM3_SLOT45_RVA, ctx,
                 (int)(*(unsigned short*)((unsigned char*)ctx + 0xC38)),
                 *(unsigned char*)((unsigned char*)ctx + 0xCD5),
                 *(unsigned char*)((unsigned char*)ctx + 0xCCC));
        ((void (*)(void*))(mod + ROOM3_SLOT45_RVA))(ctx);
        /* MEASURED 2026-09-17: the hand call is safe and does set +0xCD5, but +0xCCC stays
           0 and the clock does not move. That second flag is written deep inside
           SOnlineAction slot 26 (exe+0x803B10, at +0x10FD) -- a function the spectator DOES
           call, so it is an internal branch it fails, not a missing call.
           Setting it by hand is a probe, not a fix: if the clock then runs, the two flags
           are the gate and the honest way to obtain them is worth hunting; if it does not,
           they are one more symptom and this build says so in one run. */
        if (ROOM3_FORCE_CCC) *(unsigned char*)((unsigned char*)ctx + 0xCCC) = 1;
        log_line("ROOM3/kick: returned -- clock %d, +0xCD5 %d, +0xCCC %d after the call%s",
                 (int)(*(unsigned short*)((unsigned char*)ctx + 0xC38)),
                 *(unsigned char*)((unsigned char*)ctx + 0xCD5),
                 *(unsigned char*)((unsigned char*)ctx + 0xCCC),
                 ROOM3_FORCE_CCC ? " (+0xCCC forced by hand)" : "");
    } __except(EXCEPTION_EXECUTE_HANDLER) {
        log_line("ROOM3/kick: the hand call FAULTED -- slot 45 needs the preamble that "
                 "0x6C5390 runs before it");
    }
}

static void room3_log_gate(void* self)
{
    unsigned char* s = (unsigned char*)self;
    if (InterlockedCompareExchange(&g_room3_gate_seen, 1, 0) != 0) return;
    __try {
        unsigned char* inner = *(unsigned char**)(s + 0x318);
        log_line("ROOM3/gate: battle start was blocked for the spectator -- "
                 "[[rsi+0x318]+0xE8] = %d, [rsi+0x468] = %d (either one non-zero skips the "
                 "call). Going to exe+0x%X anyway.",
                 inner ? inner[0xE8] : -1, s[0x468], ROOM3_GATE_CALL);
    } __except(EXCEPTION_EXECUTE_HANDLER) {
        log_line("ROOM3/gate: battle start forced, flags unreadable");
    }
}

/* ---- PART 27, the barrier probe ----------------------------------------
 *  exe+0x807190 is the battle-load barrier: state must be 0, every fighter's
 *  word[0] non-zero, and the whole thing sits under a 30 s timeout measured
 *  against the timestamp at ctx+0xCE8 -- the one field that never advances on
 *  the spectator.
 *
 *  The fighter words turned out to be non-zero on all three clients, so that
 *  loop is not the gate. Two possibilities are left and one probe separates
 *  them: the function returns early on the first test, or it is never called
 *  on the spectator at all. This prints, once per client, that it ran and what
 *  the state was when it did. */
static volatile LONG g_room3_barrier_seen = 0;

static void room3_log_barrier(void* self)
{
    unsigned char* c = (unsigned char*)self;
    if (InterlockedCompareExchange(&g_room3_barrier_seen, 1, 0) != 0) return;
    __try {
        log_line("ROOM3/barrier: exe+0x807190 ran on this client -- state(+0xCE0) = %d "
                 "(non-zero returns false immediately), timestamp(+0xCE8) = %llu",
                 *(int*)(c + 0xCE0), (unsigned long long)*(unsigned long long*)(c + 0xCE8));
    } __except(EXCEPTION_EXECUTE_HANDLER) {
        log_line("ROOM3/barrier: exe+0x807190 ran, fields unreadable");
    }
}

/* ---- PART 27, the state-1 exit ------------------------------------------
 *  MEASURED 2026-09-17: the battle-load barrier at exe+0x807190 runs on BOTH
 *  players (state 0, timestamp set) and NEVER on the spectator. Its call site
 *  is exe+0x802A97, inside the battle set-up function, and the only way past it
 *  is this decision:
 *
 *      exe+0x8018CC  mov r8d,[rdi+0xCE0]   ; the state
 *      exe+0x8018D3  cmp r8d,r12d          ; r12d = 1
 *      exe+0x8018D6  je  0x802A9E          ; state 1 -> skip the barrier entirely
 *
 *  So the spectator carries state 1 at that instant, jumps over the barrier,
 *  and its battle therefore never starts. State 1 is written by the arm at
 *  exe+0x80372B in the state machine, which is reached when its own element
 *  carries flag 0x200.
 *
 *  This makes the marked spectator -- and nobody else -- read state 0 at that
 *  one decision, so it falls into the path that evaluates the barrier. It does
 *  NOT write the field: the object keeps whatever state it had, because this is
 *  a test of "is that jump the thing keeping it out", not a fix. */
#ifndef ROOM3_STATE1_EXIT
#define ROOM3_STATE1_EXIT 1
#endif


static void patch_room3_state1_exit(void)
{
    static const unsigned char orig[7] = {
        0x44,0x8B,0x87,0xE0,0x0C,0x00,0x00      /* mov r8d,[rdi+0xCE0] */
    };
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site; unsigned char* stub;
    void* flag = (void*)&g_room3_is_spectator;
    void* ctr  = (void*)&g_room3_state1_forced;
    void* seen = (void*)&g_room3_state1_seen;
    unsigned char b[128]; int n = 0, off_je, off_pass; long long rel; DWORD old;

    if (!ROOM3_STATE1_EXIT || !mod) return;
    site = mod + 0x8018CC;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("ROOM3/state1: bytes not at expected RVA 0x8018CC -- skipped"); return; }
    stub = (unsigned char*)gauge_alloc_near(site, 160);
    if (!stub) { log_line("ROOM3/state1: no trampoline -- skipped"); return; }

    b[n++]=0x50;                                             /* push rax              */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&flag,8); n+=8;     /* mov rax,&is_spectator */
    b[n++]=0x80; b[n++]=0x38; b[n++]=0x00;                   /* cmp byte [rax],0      */
    b[n++]=0x58;                                             /* pop rax               */
    /* every pass is counted, whoever it is: "the bypass fired 0 times" and "this client
       never reaches the instruction at all" look identical otherwise, and that ambiguity
       cost a run. */
    b[n++]=0x50;                                             /* push rax              */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&seen,8); n+=8;     /* mov rax,&seen         */
    b[n++]=0xF0; b[n++]=0x48; b[n++]=0xFF; b[n++]=0x00;      /* lock inc qword [rax]  */
    b[n++]=0x58;                                             /* pop rax               */
    b[n++]=0x74; off_je = n++;                               /* je  pass (a player)   */
    b[n++]=0x50;                                             /* push rax              */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&ctr,8); n+=8;      /* mov rax,&counter      */
    b[n++]=0xF0; b[n++]=0x48; b[n++]=0xFF; b[n++]=0x00;      /* lock inc qword [rax]  */
    b[n++]=0x58;                                             /* pop rax               */
    b[n++]=0x45; b[n++]=0x31; b[n++]=0xC0;                   /* xor r8d,r8d -> state 0*/
    rel = (long long)(mod + 0x8018D3) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;                   /* jmp the compare       */
    off_pass = n;
    b[off_je] = (unsigned char)(off_pass - (off_je + 1));
    memcpy(b+n, orig, sizeof(orig)); n += (int)sizeof(orig); /* stock read            */
    rel = (long long)(mod + 0x8018D3) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);
    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) { log_line("ROOM3/state1: out of range"); return; }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("ROOM3/state1: VirtualProtect failed"); return; }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    site[5] = 0x90; site[6] = 0x90;
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));
    log_line("ROOM3/state1: installed at RVA 0x8018CC (%d-byte stub at %p) -- the spectator "
             "now reads state 0 at the decision that skips the battle-load barrier",
             n, (void*)stub);
}

/* P36: the result screen indexes an array of TWO player-name strings with the local
   player's index, and the third member's index is 2. On the spectator only, clamp it.

       exe+0x332446  lea rax,[r14+0x28]     <- r14 is the index
       exe+0x33244A  lea rax,[rax+rax*2]    <- both stolen; the stub rebuilds them in rax

   Flags are dead here (the site sits between a call and a chain of lea/mov), so the
   comparison costs nothing. r14 itself is left alone: later code reads it. */
/* P38: the same index, at the one place every consumer reads it from. */
static void patch_room3_result_index(void)
{
    static const unsigned char orig[6] = { 0x8B,0x83,0x98,0x00,0x00,0x00 };  /* mov eax,[rbx+0x98] */
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site; unsigned char* stub;
    void* spf = (void*)&g_room3_is_spectator;
    void* ctr = (void*)&g_room3_idx_src;
    unsigned char b[96]; int n = 0, j1, j2; long long rel; DWORD old;

    if (!mod) return;
    site = mod + 0x336A78;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("ROOM3/index: bytes not at expected RVA 0x336A78 -- skipped"); return; }
    stub = (unsigned char*)gauge_alloc_near(site, 96);
    if (!stub) { log_line("ROOM3/index: no trampoline -- skipped"); return; }

    memcpy(b + n, orig, sizeof(orig)); n += (int)sizeof(orig);  /* mov eax,[rbx+0x98]  */
    b[n++]=0x51;                                             /* push rcx               */
    b[n++]=0x48; b[n++]=0xB9; memcpy(b+n,&spf,8); n+=8;      /* mov rcx,&is_spectator  */
    b[n++]=0x80; b[n++]=0x39; b[n++]=0x00;                   /* cmp byte [rcx],0       */
    b[n++]=0x74; j1 = n++;                                   /* je keep                */
    b[n++]=0x83; b[n++]=0xF8; b[n++]=0x01;                   /* cmp eax,1              */
    b[n++]=0x76; j2 = n++;                                   /* jbe keep               */
    b[n++]=0x31; b[n++]=0xC0;                                /* xor eax,eax            */
    b[n++]=0x48; b[n++]=0xB9; memcpy(b+n,&ctr,8); n+=8;      /* mov rcx,&counter       */
    b[n++]=0xF0; b[n++]=0x48; b[n++]=0xFF; b[n++]=0x01;      /* lock inc qword [rcx]   */
    b[j1] = (unsigned char)(n - (j1 + 1));
    b[j2] = (unsigned char)(n - (j2 + 1));
    b[n++]=0x59;                                             /* keep: pop rcx          */
    rel = (long long)(site + 6) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;                   /* jmp site+6             */

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);
    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) { log_line("ROOM3/index: out of range"); return; }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("ROOM3/index: VirtualProtect failed"); return; }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    site[5] = 0x90;
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));
    log_line("ROOM3/index: installed at RVA 0x336A78 (%d-byte stub) -- on the spectator the "
             "result screen's player index is clamped where every reader gets it from", n);
}

static void patch_room3_result_name(void)
{
    static const unsigned char orig[8] = { 0x49,0x8D,0x46,0x28, 0x48,0x8D,0x04,0x40 };
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site; unsigned char* stub;
    void* spf = (void*)&g_room3_is_spectator;
    void* ctr = (void*)&g_room3_name_clamp;
    unsigned char b[96]; int n = 0, j1, j2; long long rel; DWORD old;

    if (!mod) return;
    site = mod + 0x332446;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("ROOM3/name: bytes not at expected RVA 0x332446 -- skipped, the result "
                 "screen still reads name[%d] on a spectator", 2);
        return;
    }
    stub = (unsigned char*)gauge_alloc_near(site, 96);
    if (!stub) { log_line("ROOM3/name: no trampoline -- skipped"); return; }

    b[n++]=0x51;                                             /* push rcx               */
    b[n++]=0x48; b[n++]=0xB9; memcpy(b+n,&spf,8); n+=8;      /* mov rcx,&is_spectator  */
    b[n++]=0x41; b[n++]=0x8B; b[n++]=0xC6;                   /* mov eax,r14d           */
    b[n++]=0x80; b[n++]=0x39; b[n++]=0x00;                   /* cmp byte [rcx],0       */
    b[n++]=0x74; j1 = n++;                                   /* je keep                */
    b[n++]=0x83; b[n++]=0xF8; b[n++]=0x01;                   /* cmp eax,1              */
    b[n++]=0x76; j2 = n++;                                   /* jbe keep               */
    b[n++]=0x31; b[n++]=0xC0;                                /* xor eax,eax            */
    b[n++]=0x48; b[n++]=0xB9; memcpy(b+n,&ctr,8); n+=8;      /* mov rcx,&counter       */
    b[n++]=0xF0; b[n++]=0x48; b[n++]=0xFF; b[n++]=0x01;      /* lock inc qword [rcx]   */
    b[j1] = (unsigned char)(n - (j1 + 1));
    b[j2] = (unsigned char)(n - (j2 + 1));
    b[n++]=0x59;                                             /* keep: pop rcx          */
    b[n++]=0x83; b[n++]=0xC0; b[n++]=0x28;                   /* add eax,0x28           */
    b[n++]=0x48; b[n++]=0x8D; b[n++]=0x04; b[n++]=0x40;      /* lea rax,[rax+rax*2]    */
    rel = (long long)(site + 8) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;                   /* jmp site+8             */

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);
    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) { log_line("ROOM3/name: out of range"); return; }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("ROOM3/name: VirtualProtect failed"); return; }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    memset(site + 5, 0x90, sizeof(orig) - 5);
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));
    log_line("ROOM3/name: installed at RVA 0x332446 (%d-byte stub) -- on the spectator the "
             "result screen's player-name index is clamped to the two names that exist", n);
}

/* How far behind the live edge the gallery playback is allowed to fall, and where
   it lands when it is pulled forward. Both in 60 Hz records.

   ⚠ 600 IS NOT A ROUND NUMBER PICKED FOR COMFORT -- it has to stay ABOVE the
   burst the spectator is handed when it joins a battle. Lowering it to 300 to
   catch the intro-length lag froze the spectator instead, and the log said why
   in one line: "the playback was 304 record(s) behind the stream (cursor 0 of
   304)". The buffer handed over at the start is ~304 records, so the jump fired
   before the first frame was ever played and started the playback 184 records
   into a match it had not begun. Measured, rig attempt #158, 2026-09-21.

   The intro-length lag is therefore NOT fixable here: ~550 records is below any
   trigger that is safe against the opening burst. It has to be fixed where the
   records are made, not where they are read. */
#define ROOM3_LAG_MAX     600
#define ROOM3_LAG_TARGET  120

/* P33/P35: called at every entry of the per-frame online update (exe+0x801800), rcx =
   the SOnlineAction. Captures it; on the spectator, hands the battle to the gallery
   playback (role 0 -> 1) and, at the end of the match, back to the players' free-run. */
static void room3_update_entry(unsigned char* sa)
{
    g_room3_sa = sa;
    if (!ROOM3_GALLERY_PLAYBACK || !g_room3_is_spectator || !sa) return;
    __try {
        int* role = (int*)(sa + 0xC34);
        unsigned char* box;
        LONG64 q; unsigned played; unsigned short st;
        st = *(unsigned short*)(sa + 0x3A0);
        if (!sa[0xCCB] && *role == 0) {   /* a fresh battle: hand it to the playback */
            *role = 1;
            InterlockedIncrement64(&g_room3_flips);
            g_room3_starve_t0 = 0;
            g_room3_result_t0 = 0;
            return;
        }
        if (*role != 1) return;    /* P40: the result menu is handled in the scene tick */
        box = *(unsigned char**)(sa + 0xBC0);
        if (!box) { g_room3_starve_t0 = 0; return; }
        {   /* P37: the host re-ships its whole buffer after a rematch, so the queue can
               hold a match that is already over. Too far behind, jump to 2 s behind
               the end -- the engine's own catch-up only covers ten frames.

               ★ The trigger was 600 records (10 s) and a battle intro is 480-580
               frames, so a spectator that replayed the intro sat at ~9.2 s behind --
               just UNDER the trigger, for the whole match. That is the "the
               spectator works but is behind" report of 2026-09-21, and the cause is
               arithmetic, not the pipe. ROOM3_LAG_MAX is now below an intro, and
               ROOM3_LAG_TARGET is unchanged: the jump still lands 2 s behind, which
               is the buffer the end-of-match starvation test (1 s) needs. */
            LONG64 len = (LONG64)((*(unsigned char**)(box + 0xD8) -
                                   *(unsigned char**)(box + 0xD0)) / 0x68);
            unsigned cur = *(unsigned short*)(box + 0xE8);
            /* `cur > 0` is the guard that was missing: a cursor still at zero is a
               playback that has NOT STARTED, not one that has fallen behind, and
               pulling it forward there drops the opening of the match. */
            if (cur > 0 && len - (LONG64)cur > ROOM3_LAG_MAX && len > ROOM3_LAG_TARGET) {
                *(unsigned short*)(box + 0xE8) = (unsigned short)(len - ROOM3_LAG_TARGET);
                InterlockedIncrement64(&g_room3_skips);
                log_line("ROOM3/skip: the playback was %lld record(s) behind the stream "
                         "(cursor %u of %lld) -- jumped to 2 s behind the live edge",
                         len - (LONG64)cur, cur, len);
            }
        }
        if (st != 0x190) { g_room3_starve_t0 = 0; return; }
        q      = (LONG64)((*(unsigned char**)(box + 0xD8) - *(unsigned char**)(box + 0xD0)) / 0x68);
        played = *(unsigned short*)(box + 0xE8);
        if (q > (LONG64)played) { g_room3_starve_t0 = 0; return; }
        if (!g_room3_starve_t0) { g_room3_starve_t0 = GetTickCount64(); return; }
        if (GetTickCount64() - g_room3_starve_t0 < 1000) return;
        {   /* the barrier's success arm, FUN_140805DC0: message 0x191, then +0xCCB = 1 */
            void (*msg)(void*, int) = (void (*)(void*, int))((*(void***)sa)[0xD0 / 8]);
            msg(sa, 0x191);
            sa[0xCCB] = 1;
            *role = 0;
            g_room3_starve_t0 = 0;
            InterlockedIncrement64(&g_room3_handoffs);
            log_line("ROOM3/handoff: the match ended on the spectator (state 0x190, %u of "
                     "%lld records played, the stream silent for 1 s) -- 0x191 sent, +0xCCB "
                     "set, role 1 -> 0: the scene now free-runs like the players'",
                     played, (long long)q);
        }
    } __except(EXCEPTION_EXECUTE_HANDLER) { }
}

/* A breadcrumb at the battle set-up entry (exe+0x801800). Between this and the counter
   at 0x8018CC, one run says how far into the function a client gets -- which is the
   question left after the state-1 bypass never fired on the spectator. */
static void patch_room3_setup_breadcrumb(void)
{
    /* ⚠ These are 0x801800's own first five bytes -- mov rax,rsp ; push rbp ; push rbx.
       The first attempt pasted 0x805870's prologue here by mistake and every client
       answered "bytes not at expected RVA", which is precisely why that check exists. */
    static const unsigned char orig[5] = { 0x48,0x8B,0xC4, 0x55, 0x53 };
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site; unsigned char* stub;
    void* ctr = (void*)&g_room3_setup_seen;
    void* fn  = (void*)&room3_update_entry;
    unsigned char b[192]; int n = 0; long long rel; DWORD old;

    if (!mod) return;
    site = mod + 0x801800;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("ROOM3/crumb: bytes not at expected RVA 0x801800 -- skipped"); return; }
    stub = (unsigned char*)gauge_alloc_near(site, 192);
    if (!stub) { log_line("ROOM3/crumb: no trampoline -- skipped"); return; }

    /* rcx = the SOnlineAction (FUN_140808140 calls this with [lambda+8]). Flags need no
       saving: this is a function entry, and no caller reads flags across a call. */
    b[n++]=0x50;                                             /* push rax              */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&ctr,8); n+=8;      /* mov rax,&counter      */
    b[n++]=0xF0; b[n++]=0x48; b[n++]=0xFF; b[n++]=0x00;      /* lock inc qword [rax]  */
    b[n++]=0x58;                                             /* pop rax               */
    /* room3_update_entry(rcx), every volatile register kept */
    b[n++]=0x55;                                                      /* push rbp        */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xE5;                            /* mov rbp,rsp     */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xE4; b[n++]=0xF0;               /* and rsp,-16     */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xEC; b[n++]=0x60;               /* sub rsp,0x60    */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x44; b[n++]=0x24; b[n++]=0x28;  /* rax             */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;  /* rcx             */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x54; b[n++]=0x24; b[n++]=0x38;  /* rdx             */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x44; b[n++]=0x24; b[n++]=0x40;  /* r8              */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x48;  /* r9              */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x54; b[n++]=0x24; b[n++]=0x50;  /* r10             */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x58;  /* r11             */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&fn,8); n+=8;                /* mov rax,&fn     */
    b[n++]=0xFF; b[n++]=0xD0;                                         /* call rax        */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x28;
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x54; b[n++]=0x24; b[n++]=0x38;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x40;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x48;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x54; b[n++]=0x24; b[n++]=0x50;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x58;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xEC;                            /* mov rsp,rbp     */
    b[n++]=0x5D;                                                      /* pop rbp         */
    memcpy(b+n, orig, sizeof(orig)); n += (int)sizeof(orig); /* the real prologue     */
    rel = (long long)(mod + 0x801805) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);
    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) { log_line("ROOM3/crumb: out of range"); return; }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("ROOM3/crumb: VirtualProtect failed"); return; }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));
    log_line("ROOM3/crumb: breadcrumb installed at the battle set-up entry (RVA 0x801800)%s",
             ROOM3_GALLERY_PLAYBACK ? " -- and GALLERY PLAYBACK armed: on the spectator, "
             "role 0 -> 1 at the first per-frame update, and back to the players' free-run "
             "when the stream ends at the final KO (0x190)" : "");
}

/* Two more breadcrumbs, and they are the last two links of the chain as it stands:
 *
 *   exe+0x801800   battle set-up -- entered thousands of times on both players, NEVER on
 *                  the spectator, and it is not called directly: it is invoked through a
 *                  std::function<bool()> thunk (exe+0x8096A0).
 *   exe+0x804BD9   where that std::function is CONSTRUCTED -- inside SOnlineAction slot
 *                  26 (exe+0x803B10), 0x10C9 bytes in, the same region that writes the
 *                  +0xCCC flag at +0x10FD.
 *
 * So the question is now bounded: does the spectator enter slot 26, and does it reach the
 * registration inside it? One run, two counters, and the answer is a span of 0x10C9 bytes
 * to bisect rather than a new hypothesis. */
static void room3_crumb_install(unsigned int rva, const unsigned char* orig, int len,
                                void* counter, const char* what)
{
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site; unsigned char* stub;
    unsigned char b[96]; int n = 0; long long rel; DWORD old;

    if (!mod) return;
    site = mod + rva;
    if (memcmp(site, orig, (size_t)len) != 0) {
        log_line("ROOM3/crumb: bytes not at expected RVA 0x%X (%s) -- skipped", rva, what);
        return;
    }
    /* ⚠⚠ A STOLEN RIP-RELATIVE INSTRUCTION IS A DIFFERENT INSTRUCTION.
       On 2026-09-17 this installer was pointed at exe+0x804BD9, `lea rax,[rip+0xC9EB98]`,
       which loads the lambda's vtable pointer. Re-executed from a cave two gigabytes away
       it computes a different address, the std::function got a garbage table, and the
       first call through it took ALL THREE clients down at exe+0x8744DC reading -1 --
       twice, before the pattern was recognised. The bytes are refused rather than
       relocated: a breadcrumb is never worth a displacement fix-up. */
    {
        int i;
        for (i = 0; i + 2 < len; i++)
            if ((orig[i] == 0x48 || orig[i] == 0x4C) && orig[i+1] == 0x8D &&
                (orig[i+2] & 0xC7) == 0x05) {
                log_line("ROOM3/crumb: REFUSING %s at RVA 0x%X -- the bytes contain a "
                         "rip-relative lea, which cannot be moved into a trampoline",
                         what, rva);
                return;
            }
    }
    stub = (unsigned char*)gauge_alloc_near(site, 96);
    if (!stub) { log_line("ROOM3/crumb: no trampoline for %s", what); return; }

    b[n++]=0x50;                                             /* push rax              */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&counter,8); n+=8;  /* mov rax,&counter      */
    b[n++]=0xF0; b[n++]=0x48; b[n++]=0xFF; b[n++]=0x00;      /* lock inc qword [rax]  */
    b[n++]=0x58;                                             /* pop rax               */
    memcpy(b+n, orig, (size_t)len); n += len;
    rel = (long long)(mod + rva + len) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);
    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) { log_line("ROOM3/crumb: %s out of range", what); return; }
    if (!VirtualProtect(site, (SIZE_T)len, PAGE_EXECUTE_READWRITE, &old)) {
        log_line("ROOM3/crumb: VirtualProtect failed for %s", what); return; }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    if (len > 5) memset(site + 5, 0x90, (size_t)len - 5);
    VirtualProtect(site, (SIZE_T)len, old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, (size_t)len);
    log_line("ROOM3/crumb: %s instrumented at RVA 0x%X", what, rva);
}

/* Inside SOnlineAction slot 26, between its entry and the registration at +0x10C9.
   MEASURED: players enter slot 26 seven times and register once; the spectator enters
   twice and never registers, so it leaves the function somewhere in this span. Five
   points, each chosen for being >= 5 bytes, not a branch, and free of rip-relative
   operands -- that last one is not a preference, it is the mistake that crashed every
   client twice (§6.13 of the write-up). */
static void patch_room3_slot26_span(void)
{
    /* ⚠ The first five points were picked at even offsets and FOUR OF THEM WERE NEVER
       EXECUTED BY ANYONE -- players included -- so they localised nothing. Guessing at
       addresses inside a 4 KB function is not bisecting. These follow the path the
       players actually take, walked backwards from the one point that did fire
       (+0x0F0E): the loop over [ctx+0x3B0]..[ctx+0x3B8] and the two statements above it. */
    static const unsigned char a[6] = { 0x41,0xB8,0x90,0x13,0x00,0x00 };  /* +0x0E3D mov r8d,0x1390     */
    static const unsigned char b[7] = { 0x4C,0x8B,0xBF,0xB0,0x03,0x00,0x00 }; /* +0x0E56 mov r15,[rdi+3B0] */
    static const unsigned char c[6] = { 0x8B,0x97,0x40,0x0C,0x00,0x00 };  /* +0x0F0E mov edx,[rdi+C40] */
    room3_crumb_install(0x80494D, a, 6, (void*)&g_room3_s26[0], "slot26 +0x0E3D");
    room3_crumb_install(0x804966, b, 7, (void*)&g_room3_s26[1], "slot26 +0x0E56 (the member loop)");
    room3_crumb_install(0x804A1E, c, 6, (void*)&g_room3_s26[2], "slot26 +0x0F0E");
}

/* ---- what slot 26 actually is --------------------------------------------
 *  Disassembled 2026-09-17, after the three path breadcrumbs came back 1/1/1 on both
 *  players and 0/0/0 on the spectator -- a client that ENTERS the function twice and
 *  reaches none of the three points. It does not "leave early": slot 26 is not a
 *  sequence at all, it is a message handler.
 *
 *      exe+0x803B46   movzx r14d, dx          ; dx IS the message id
 *      exe+0x803B5B   cmp r14d, 0x32          ; ... a chain of tests and one jump table
 *
 *  and the ids that matter land exactly where this work has been poking:
 *
 *      0x0C8  -> exe+0x804BBA   builds the battle-set-up std::function (+0x10C9)
 *                               and writes the +0xCCC flag (+0x10FD)
 *      0x12C  -> exe+0x804934   the fighter loop over [ctx+0x3B0]..[ctx+0x3B8]
 *      0x190  -> exe+0x804922   0x190/0x191/0x3F2, other transitions
 *
 *  So "the spectator stops inside slot 26" was the wrong shape of question. The
 *  spectator is never SENT messages 0xC8 and 0x12C. This logs the id of every message
 *  and the address it was sent from, once per distinct id, which answers both halves in
 *  one run: which ids a player gets that the spectator does not, and who sends them. */
/* ⚠ FIRST SIGHT OF EACH VALUE IS NOT ENOUGH, and believing it cost a round of wrong
   conclusions. Measured 2026-09-17: the spectator's state IS written to 0x32 once, on the
   same object its state machine polls -- and the machine, ticked 2595 times afterwards,
   only ever sees 0x31. A set cannot show that, because the reset is a REPEAT of a value
   already logged: the default branch of exe+0x6B0910 is `state = the message just
   received`, so a second message 0x31 arriving after 0x32 puts the state back and the
   client sits there forever. Order is the measurement; these log every event until the
   budget runs out, and the log's own line order is the sequence. */
/* 64 ran out before the freeze on the 2026-09-18 09:41 match, so that run could not
   say whether the gate byte went back to 1 -- the budget, not the game, ended the
   measurement. A match is ~3 minutes and these fire on change only. */
#define ROOM3_TRACE_MAX 4096

static void room3_log_event(unsigned int id, void* ret)
{
    unsigned char* mod;
    const char* what = "";
    LONG64 seq = InterlockedIncrement64(&g_room3_slot26_seen);
    if (id >= 0x1000) id = 0xFFF;    /* out of range still gets exactly one line */
    InterlockedIncrement(&g_room3_evt[id]);
    if (InterlockedIncrement(&g_room3_trace) > ROOM3_TRACE_MAX) return;
    if (id == 0xC8)  what = "  <<< BATTLE SET-UP: registers the callback, sets +0xCCC";
    if (id == 0x12C) what = "  <<< the fighter loop";
    mod = (unsigned char*)GetModuleHandleA(NULL);
    log_line("ROOM3/evt: #%lld slot26 message 0x%X, sent from exe+0x%X%s", (long long)seq, id,
             (unsigned)((unsigned char*)ret - mod), what);
}

/* One installer for both probes: the only thing that differs between "log the message id"
   and "log the state" is the instruction that loads ecx, so that is the parameter. Both
   sites happen to open with the same five-byte `mov [rsp+0x18],rbx`. */
static void room3_install_site_log(unsigned int rva, const unsigned char* orig, int orign,
                                   const unsigned char* load, int loadn,
                                   void* fn, const char* tag)
{
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site; unsigned char* stub;
    unsigned char b[224]; int n = 0; long long rel; DWORD old;

    if (!mod) return;
    site = mod + rva;
    if (memcmp(site, orig, (size_t)orign) != 0) {
        log_line("ROOM3/%s: bytes not at expected RVA 0x%X -- skipped", tag, rva); return; }
    stub = (unsigned char*)gauge_alloc_near(site, 256);
    if (!stub) { log_line("ROOM3/%s: no trampoline within +/-2GB -- skipped", tag); return; }

    /* The return address is read BEFORE anything is pushed, so [rbp+8] is the caller.
       rsp is put back exactly as it was at entry before the stolen instruction runs:
       that instruction writes to [rsp+0x18], the caller's shadow space, and running it
       on a shifted stack would corrupt the caller's frame. */
    b[n++]=0x55;                                                      /* push rbp        */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xE5;                            /* mov rbp,rsp     */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xE4; b[n++]=0xF0;               /* and rsp,-16     */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xEC; b[n++]=0x60;               /* sub rsp,0x60    */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x44; b[n++]=0x24; b[n++]=0x28;  /* mov [rsp+28],rax */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;  /* rcx             */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x54; b[n++]=0x24; b[n++]=0x38;  /* rdx             */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x44; b[n++]=0x24; b[n++]=0x40;  /* r8              */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x48;  /* r9              */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x54; b[n++]=0x24; b[n++]=0x50;  /* r10             */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x58;  /* r11             */
    memcpy(b+n, load, (size_t)loadn); n += loadn;                     /* the arguments   */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&fn,8); n+=8;                /* mov rax,&logger */
    b[n++]=0xFF; b[n++]=0xD0;                                         /* call rax        */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x28;  /* restore rax     */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;  /* rcx             */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x54; b[n++]=0x24; b[n++]=0x38;  /* rdx             */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x40;  /* r8              */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x48;  /* r9              */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x54; b[n++]=0x24; b[n++]=0x50;  /* r10             */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x58;  /* r11             */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xEC;                            /* mov rsp,rbp     */
    b[n++]=0x5D;                                                      /* pop rbp         */
    memcpy(b+n, orig, (size_t)orign); n += orign;                     /* stolen          */
    rel = (long long)(site + orign) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;                            /* jmp back        */

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);
    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("ROOM3/%s: trampoline out of rel32 range -- skipped", tag); return; }
    if (!VirtualProtect(site, (SIZE_T)orign, PAGE_EXECUTE_READWRITE, &old)) {
        log_line("ROOM3/%s: VirtualProtect failed at RVA 0x%X", tag, rva); return; }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    if (orign > 5) memset(site + 5, 0x90, (size_t)orign - 5);
    VirtualProtect(site, (SIZE_T)orign, old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, (size_t)orign);
    log_line("ROOM3/%s: entry log installed at RVA 0x%X -- every distinct value prints once",
             tag, rva);
}

/* ---- the state machine that SENDS those messages -------------------------
 *  MEASURED 2026-09-17, one match, three clients:
 *
 *      players    0x31 0x32 0x64 0xC8 0xC9 0x12C 0x12D
 *      spectator  0x31 0x32
 *
 *  and every missing message is sent from one function, exe+0x6B3490, whose whole body
 *  is a switch on `word [this+0x3A0]` -- a state, whose values ARE the message ids:
 *
 *      exe+0x6B350F   movzx edx, word [rcx+0x3A0]
 *      exe+0x6B3516   cmp edx, 0x64 / ja 0x6B35CA / je 0x6B357D   ; state 0x64 -> sends 0xC8
 *      exe+0x6B3521   sub edx, 0x31 / je 0x6B353D                 ; state 0x31 -> sends 0x32
 *      exe+0x6B3526   cmp edx, 1 / jne exit                       ; state 0x32 -> [vt+0xE0]()
 *
 *  Each case returns the NEXT state in eax (exe+0x6B3467 `mov eax,ebx`), and the message
 *  goes out through `call [vtable+0xD0]` -- which is slot 26, the same object. So the two
 *  probes see the same machine from both ends, and the spectator's stall is one
 *  transition: it sends 0x32 and never advances to 0x64.
 *
 *  This logs each distinct state the machine is entered with, so one run says exactly
 *  which state the spectator sits in and which ones the players pass through. */
static void room3_log_state(unsigned int st, void* self, void* ret)
{
    LONG prev = g_room3_sm_last;
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned rva = (unsigned)((unsigned char*)ret - mod);
    g_room3_sm_tick = GetTickCount64();
    if (rva != (unsigned)g_room3_sm_caller) {
        g_room3_sm_caller = (LONG)rva;
        if (InterlockedIncrement(&g_room3_sm_callers) <= 8)
            log_line("ROOM3/st: the machine is driven from exe+0x%X", rva);
    }
    InterlockedIncrement64(&g_room3_sm_calls);
    g_room3_sm_last = (LONG)st;
    g_room3_sm_this = self;
    if (st >= 0x1000) st = 0xFFF;
    InterlockedIncrement(&g_room3_st[st]);
    if ((LONG)st == prev) return;                       /* only the transitions */
    if (InterlockedIncrement(&g_room3_trace) > ROOM3_TRACE_MAX) return;
    log_line("ROOM3/st: battle state machine entered with state 0x%X (was 0x%X) on object %p%s",
             st, (unsigned)prev, self,
             st == 0x32 ? "  <<< the state the spectator never enters" :
             st == 0x64 ? "  <<< the state that sends 0xC8, battle set-up" : "");
}

/* ---- the one and only writer of the state ---------------------------------
 *  A scan of .text for word-sized stores to +0x3A0 finds exactly ONE: exe+0x803FF6, inside
 *  slot 26 itself, in the branch for message 0x32 -- and it is unconditional. Every path
 *  through that branch converges on `mov eax,0x32 / mov word [rdi+0x3A0],ax`.
 *
 *  Which makes the measurement contradictory as it stands: the spectator RECEIVES message
 *  0x32, so it must run this write, and yet its machine is never entered with state 0x32.
 *  Two things can explain that, and they need opposite fixes, so this run separates them
 *  by logging the object on both sides and counting both:
 *
 *    - two different `this`  -> the write lands on another instance, and the machine the
 *                               spectator polls is not the one being driven;
 *    - the same `this`, and the machine's call count stops rising -> whatever drives it
 *                               each frame gave up on this client, and the state does not
 *                               matter until that is fixed. */
static void room3_log_statewrite(void* self, void* ret)
{
    (void)ret;
    InterlockedIncrement64(&g_room3_stw_calls);
    g_room3_stw_this = self;
    if (InterlockedIncrement(&g_room3_trace) > ROOM3_TRACE_MAX) return;
    log_line("ROOM3/stw: state <- 0x32 on object %p (slot 26's own branch, exe+0x803FF6)",
             self);
}

/* The OTHER writer, and the one that undoes it: exe+0x6B3026, the default tail of the
   message handler exe+0x6B0910, whose whole body is `state = the message just received,
   timer = 0`. Every message without a case of its own lands here -- 0x31 among them. */
static void room3_log_statewrite2(unsigned int st, void* self)
{
    InterlockedIncrement64(&g_room3_stw2_calls);
    if (InterlockedIncrement(&g_room3_trace) > ROOM3_TRACE_MAX) return;
    log_line("ROOM3/stw: state <- 0x%X on object %p (default tail of the message handler, "
             "exe+0x6B3026)%s", st, self,
             st == 0x31 ? "  <<< this is the reset that traps the spectator" : "");
}

/* ---- the wait the spectator never leaves -----------------------------------
 *  exe+0x804C70 is the per-frame update, and it switches on the same state word as the
 *  message machine. Its common tail, exe+0x80557A, is what calls that machine -- so a case
 *  that returns early does not merely skip a frame, it stops driving the machine at all.
 *  State 0x32's case, exe+0x804D84, is exactly that shape: a wait, with three exits that
 *  all jump straight to exe+0x805585, the instruction AFTER the call:
 *
 *      exe+0x804DC9   je  0x805585     ; some fighter's word[0] is still 0
 *      exe+0x804E0F   jmp 0x805585     ; the seat's own fighter is not marked ready
 *      exe+0x804E22   jb  0x805585     ; [[this+0xBC0]+3] < 2
 *
 *  ⚠ The third one was modelled wrong on the first try, and the probe then reported
 *  "this frame gets past the wait" on a client that was already frozen. It does not read
 *  the fighter container at [+0xBC0]+0x08: it reads the OTHER vector, at [+0xBC0]+0x20,
 *  indexes it by the seat, and tests bit 0 of the first byte:
 *
 *      exe+0x804DF4   mov rax,[rdi+0xBC0]
 *      exe+0x804DFB   movsxd rcx,dword [rdi+0xC40]     ; the seat
 *      exe+0x804E02   mov rax,[rax+0x20]
 *      exe+0x804E06   mov rax,[rax+rcx*8]
 *      exe+0x804E0A   test byte [rax],1
 *      exe+0x804E0D   jne 0x804E28                     ; ready -> carry on
 *      exe+0x804E0F   jmp 0x805585                     ; else leave, machine undriven
 *
 *  Measured: the spectator's machine freezes for good the moment the state becomes 0x32,
 *  and the state stays 0x32 because only the machine would move it -- so every later frame
 *  takes the same exit. Which one is a question about field values, not about control flow,
 *  so this reads them rather than counting three branches.
 *
 *  The verdict is computed here, in C, from the same fields the engine tests, and printed
 *  only when it changes: a line per frame would be 60 a second and would say nothing more
 *  than the first one did. */
static void room3_log_wait(void* self, void* ret)
{
    static char last[400];
    char now[400];
    unsigned char* t = (unsigned char*)self;
    (void)ret;
    if (InterlockedIncrement(&g_room3_wait_calls) == 1)
        log_line("ROOM3/wait: state 0x32's per-frame case reached -- from here the machine is "
                 "only driven if this case runs to its end");
    __try {
        int role   = *(int*)(t + 0xC34);
        int ce0    = *(int*)(t + 0xCE0);
        int seat   = *(int*)(t + 0xC40);
        unsigned char c3a = t[0xC3A];
        unsigned char* bc0 = *(unsigned char**)(t + 0xBC0);
        unsigned char** beg = bc0 ? *(unsigned char***)(bc0 + 8) : 0;
        unsigned char** end = bc0 ? *(unsigned char***)(bc0 + 0x10) : 0;
        unsigned char* first = bc0 ? *(unsigned char**)bc0 : 0;
        int nfi = (beg && end) ? (int)(end - beg) : -1;
        int zero = -1, i, off = 0, off2 = 0;
        char words[80];
        char kinds[130];
        unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
        /* the seat's own fighter, through the +0x20 vector, which is the test at 0x804E0A */
        unsigned char** sv = bc0 ? *(unsigned char***)(bc0 + 0x20) : 0;
        unsigned char* mine = (sv && seat >= 0) ? sv[seat] : 0;
        int ready = mine ? (mine[0] & 1) : -1;
        words[0] = 0;
        kinds[0] = 0;
        if (nfi > 0 && nfi < 16) {
            zero = 0;
            for (i = 0; i < nfi; i++) {
                unsigned short w = beg[i] ? *(unsigned short*)beg[i] : 0;
                off += snprintf(words + off, sizeof(words) - off, "%s%u", i ? "," : "", w);
                if (!w) zero = 1;
                (void)mod;   /* these objects carry no vptr: word0 IS offset 0 */
            }
        }
        /* the +0x20 vector in full: this is the one the wait tests, and the players' entry
           for their own seat is what flips. Its whole flags dword, not just bit 0. */
        if (sv) {
            unsigned char** sbeg = *(unsigned char***)(bc0 + 0x20);
            (void)sbeg;
            unsigned char** send = *(unsigned char***)(bc0 + 0x28);
            int ns = (sbeg && send) ? (int)(send - sbeg) : -1;
            off2 += snprintf(kinds + off2, sizeof(kinds) - off2, " | +0x20 x%d:", ns);
            if (ns > 0 && ns < 8)
                for (i = 0; i < ns; i++)
                    off2 += snprintf(kinds + off2, sizeof(kinds) - off2, " [%d]=%08X",
                                     i, sbeg[i] ? *(unsigned*)sbeg[i] : 0);
        }
        snprintf(now, sizeof(now),
                 "role %d, [+0xCE0] %d, seat %d, [+0xC3A] %u, fighters %d word0 [%s], "
                 "seat fighter ready bit %d, [[+0xBC0]+3] %u, %s -- %s",
                 role, ce0, seat, c3a, nfi, words, ready, first ? first[3] : 255, kinds,
                 zero == 1 ? "STUCK at exe+0x804DC9: a fighter's word[0] is 0"
                 : ready == 0 ? "STUCK at exe+0x804E0F: the seat's fighter has bit 0 clear"
                 : ready < 0 ? "STUCK at exe+0x804E0F: no fighter at this seat in the "
                               "+0x20 vector"
                 : (first && first[3] < 2) ? "STUCK at exe+0x804E22: [[+0xBC0]+3] < 2"
                 : "this frame gets past the wait and drives the machine");
    } __except(EXCEPTION_EXECUTE_HANDLER) {
        snprintf(now, sizeof(now), "fields unreadable");
    }
    /* ---- and the one thing this probe does rather than watch -------------------
     *  MEASURED, three clients, one match:
     *
     *      host      (marks [0], waits [1])   [0]=0 [1]=0 -> [0]=1 [1]=0 -> [0]=1 [1]=1
     *      BROS2     (marks [1], waits [0])   [0]=0 [1]=0 ->            -> [0]=1 [1]=1
     *      spectator (marks [0], waits [1])   [0]=1 [1]=0, and never anything else
     *
     *  It is a two-party rendezvous: each side marks its own seat when its local load
     *  finishes and receives the other's over the wire, which is why the two players flip
     *  16 ms apart. The spectator is a third participant wearing player 1's seat pair
     *  (+0xC3C = 0, +0xC40 = 1, identical to the host), so it marks the host's entry and
     *  waits on a mark nobody will ever address to it.
     *
     *  It has nothing to wait for -- it is not fighting anyone -- so its own copy of the
     *  other seat's "ready" is set here, locally, on the spectator only. Nothing is sent
     *  and no other client can see this. The mute is NOT what was blocking it: with the
     *  mute off the wait was unchanged, so this is not papering over our own suppression. */
    if (ROOM3_FORCE_READY && g_room3_is_spectator) {
        __try {
            unsigned char* bc = *(unsigned char**)(t + 0xBC0);
            int other = *(int*)(t + 0xC40);
            unsigned char** v = bc ? *(unsigned char***)(bc + 0x20) : 0;
            unsigned char* o = (v && other >= 0) ? v[other] : 0;
            if (o && !(*(unsigned*)o & 1)) {
                *(unsigned*)o |= 1u;
                if (InterlockedIncrement(&g_room3_forced_ready) <= 4)
                    log_line("ROOM3/wait: marked the other seat (%d) ready locally on the "
                             "spectator -- it was waiting on a rendezvous addressed to the "
                             "host", other);
            }
        } __except(EXCEPTION_EXECUTE_HANDLER) { }
    }

    if (strcmp(now, last) == 0) return;                 /* only when it changes */
    if (InterlockedIncrement(&g_room3_wait_lines) > 20) return;
    memcpy(last, now, sizeof(last));
    log_line("ROOM3/wait: %s", now);
}

/* exe+0x804C70, the per-frame update that drives everything else. Same shape of probe as
   the machine's: a call count, the state it saw, when it last ran and who called it. */
/* P40: the result menu, from the scene's own per-frame update. `self` is the
   SOnlineAction and `st` the state it is ticking with, so this keeps working after the
   battle's online update has been unregistered. */
static void room3_follow_result(unsigned char* sa, unsigned int st)
{
    if (!ROOM3_GALLERY_PLAYBACK || !g_room3_is_spectator || !sa || g_room3_flips <= 0) return;
    if (st != 0x406) {
        if (st != 0x3E8 && st != 0x191) g_room3_result_t0 = 0;
        return;
    }
    __try {
        unsigned char* box = *(unsigned char**)(sa + 0xBC0);
        int peer = *(int*)(sa + 0xC40);
        unsigned* word = 0;
        void (*msg)(void*, int) = (void (*)(void*, int))((*(void***)sa)[0xD0 / 8]);
        if (box && peer >= 0)
            word = *(unsigned**)(*(unsigned char**)(box + 0x20) + 8 * peer);
        if (!g_room3_result_t0) {
            g_room3_result_t0 = GetTickCount64();
            g_room3_result_log = 0;
            log_line("ROOM3/follow: the result menu is up on the spectator -- watching the "
                     "host's sync word for slot 8 (its word is %08X now)", word ? *word : 0);
        }
        {   /* P41: every sync word this client holds, once a second -- the one read through
               its own seat mapping never moves, so the question is whether any of them does */
            ULONGLONG now = GetTickCount64();
            if (box && now - g_room3_result_log >= 1000) {
                unsigned char** beg = *(unsigned char***)(box + 0x20);
                unsigned char** end = *(unsigned char***)(box + 0x28);
                char out[160]; int at = 0, k = 0;
                g_room3_result_log = now;
                while (beg && beg + k < end && k < 4) {
                    unsigned* w = (unsigned*)beg[k];
                    at += snprintf(out + at, sizeof(out) - at, "[%d] %08X/%08X ", k,
                                   w ? w[0] : 0, w ? w[1] : 0);
                    k++;
                }
                log_line("ROOM3/words: on the result screen, seat %d is mine -- %s",
                         *(int*)(sa + 0xC3C), out);
            }
        }
        if (word && (*word & 0x100)) {
            g_room3_result_t0 = 0;
            if (InterlockedIncrement64(&g_room3_rematch) == 1)
                log_line("ROOM3/follow: the host asked for a rematch (word %08X) -- sending "
                         "0x458, the state Try Again sends", *word);
            msg(sa, 0x458);
        } else if (GetTickCount64() - g_room3_result_t0 > 2000) {
            g_room3_result_t0 = 0;
            if (InterlockedIncrement64(&g_room3_toroom) == 1)
                log_line("ROOM3/follow: nothing to decide on this screen -- sending 0x45A "
                         "after 2 s, back to the room, where the players' next battle picks "
                         "this client up again");
            msg(sa, 0x45A);
        }
    } __except(EXCEPTION_EXECUTE_HANDLER) { }
}

static void room3_note_object(void* self, unsigned int st)
{
    int i;
    room3_follow_result((unsigned char*)self, st);
    for (i = 0; i < ROOM3_OBJ_MAX; i++) {
        if (g_room3_obj[i] == self || g_room3_obj[i] == 0) {
            if (g_room3_obj[i] == 0) {
                g_room3_obj[i] = self;
                log_line("ROOM3/obj: a %s instance is being ticked: %p (first seen with "
                         "state 0x%X)", i ? "SECOND/further" : "first", self, st);
            }
            g_room3_obj_calls[i]++;
            g_room3_obj_state[i] = (LONG)st;
            g_room3_obj_tick[i] = GetTickCount64();
            return;
        }
    }
}

/* Shared logger for every generic entry probe. `tag` indexes g_room3_ep_*. */
static void room3_log_maker(void* self, void* ret, int tag, void* arg1)
{
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned rva = (unsigned)((unsigned char*)ret - mod);
    if (tag < 0 || tag >= ROOM3_EP_MAX) return;
    InterlockedIncrement64(&g_room3_ep_n[tag]);
    /* the gallery probes carry their meaning in the first argument */
    if (g_room3_ep_name[tag] && g_room3_ep_name[tag][0] == '*') {
        if (!strcmp(g_room3_ep_name[tag], "*StartLiveStreamingSystem")) {
            g_room3_lsm = self;
            g_room3_lsm_kind = (LONG)(LONG_PTR)arg1;
        }
        else if (!strcmp(g_room3_ep_name[tag], "*LiveStreamSend(0x1B04C0)"))
            InterlockedIncrement64(&g_room3_gal_send);
        else if (!strcmp(g_room3_ep_name[tag], "*LiveStreamRecv(0x1AF3F0)"))
            InterlockedIncrement64(&g_room3_gal_recv);
        if (InterlockedIncrement(&g_room3_ep_lines[tag]) <= 12)
            log_line("ROOM3/gallery: %s on %p from exe+0x%X, arg %lld%s",
                     g_room3_ep_name[tag] + 1, self, rva, (long long)(LONG_PTR)arg1,
                     !strcmp(g_room3_ep_name[tag], "*StartLiveStreamingSystem")
                        ? ((LONG_PTR)arg1 == 0 ? " = HOST" : (LONG_PTR)arg1 == 1 ? " = P2" :
                           (LONG_PTR)arg1 == 2 ? " = GALLERY LEADER" :
                           ((LONG_PTR)arg1 >= 3 && (LONG_PTR)arg1 <= 5) ? " = GALLERY MEMBER"
                           : " = NO SLOT")
                        : "");
        return;
    }
    if (InterlockedIncrement(&g_room3_ep_lines[tag]) <= 6)
        log_line("ROOM3/make: %s installer entered on %p from exe+0x%X",
                 g_room3_ep_name[tag], self, rva);
}

/* One generic entry probe: steal `len` clean bytes at `rva` (the caller has checked they
   hold no rip operand, call or branch), log (this, return address, tag), re-execute them
   and continue. Replaces seventy hand-copied lines per probe. */
/* P34: OnlineData::PacketData::Send's gate. Returns 1 to drop the send. */
static int room3_pkt_gate(void* pkt)
{
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    void* vt = 0; const char* name = "?"; int i, k = -1, ours = 0;
    __try {
        vt = *(void**)pkt;
        for (i = 0; i < (int)g_room3_pk_n && i < ROOM3_PK_MAX; i++)
            if (g_room3_pk_vt[i] == vt) { k = i; break; }
        if (k < 0) {
            unsigned char* col = ((unsigned char**)vt)[-1];
            unsigned int td = *(unsigned int*)(col + 12);
            name = (const char*)(mod + td + 0x10);
            ours = strstr(name, "SOnlineAction") != NULL;
            k = (int)InterlockedIncrement(&g_room3_pk_n) - 1;
            if (k < ROOM3_PK_MAX) {
                g_room3_pk_name[k] = name;
                g_room3_pk_ours[k] = (char)ours;
                g_room3_pk_vt[k]   = vt;
                log_line("ROOM3/pkt-class: first send of %s (vtable exe+0x%X, id %08X)%s",
                         name, (unsigned)((unsigned char*)vt - mod), *(unsigned*)((unsigned char*)pkt + 8),
                         ours ? " -- an SOnlineAction battle packet" : "");
            } else k = -1;
        }
    } __except(EXCEPTION_EXECUTE_HANDLER) { return 0; }
    if (k < 0) return 0;
    if (ROOM3_GALLERY_QUIET && g_room3_pk_ours[k] && g_room3_is_spectator && g_room3_flips > 0) {
        InterlockedIncrement64(&g_room3_pk_drop[k]);
        return 1;
    }
    InterlockedIncrement64(&g_room3_pk_sent[k]);
    return 0;
}

static void patch_room3_pkt_gate(void)
{
    static const unsigned char orig[5] = { 0x40,0x53,0x55,0x56,0x57 };  /* push rbx..rdi */
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site; unsigned char* stub;
    void* fn = (void*)&room3_pkt_gate;
    unsigned char b[160]; int n = 0; long long rel; DWORD old;

    if (!mod) return;
    site = mod + 0x675D60;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("ROOM3/quiet: bytes not at expected RVA 0x675D60 -- skipped"); return; }
    stub = (unsigned char*)gauge_alloc_near(site, 160);
    if (!stub) { log_line("ROOM3/quiet: no trampoline -- skipped"); return; }

    b[n++]=0x55;                                                      /* push rbp        */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xE5;                            /* mov rbp,rsp     */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xE4; b[n++]=0xF0;               /* and rsp,-16     */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xEC; b[n++]=0x60;               /* sub rsp,0x60    */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x44; b[n++]=0x24; b[n++]=0x28;  /* rax             */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;  /* rcx = the pkt   */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x54; b[n++]=0x24; b[n++]=0x38;  /* rdx             */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x44; b[n++]=0x24; b[n++]=0x40;  /* r8              */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x48;  /* r9              */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x54; b[n++]=0x24; b[n++]=0x50;  /* r10             */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x58;  /* r11             */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&fn,8); n+=8;                /* mov rax,&gate   */
    b[n++]=0xFF; b[n++]=0xD0;                                         /* call rax        */
    b[n++]=0x85; b[n++]=0xC0;                                         /* test eax,eax    */
    /* the restores are movs and a pop: none of them touches the flags the test set */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x28;
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x54; b[n++]=0x24; b[n++]=0x38;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x40;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x48;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x54; b[n++]=0x24; b[n++]=0x50;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x58;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xEC;                            /* mov rsp,rbp     */
    b[n++]=0x5D;                                                      /* pop rbp         */
    b[n++]=0x75; b[n++]=0x0A;                                         /* jnz drop        */
    memcpy(b+n, orig, sizeof(orig)); n += (int)sizeof(orig);          /* the real entry  */
    rel = (long long)(site + 5) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;                            /* jmp site+5      */
    b[n++]=0xC3;                                                      /* drop: ret (void)*/

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);
    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) { log_line("ROOM3/quiet: out of range"); return; }
    if (!VirtualProtect(site, 5, PAGE_EXECUTE_READWRITE, &old)) {
        log_line("ROOM3/quiet: VirtualProtect failed"); return; }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    VirtualProtect(site, 5, old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, 5);
    log_line("ROOM3/quiet: PacketData::Send gate installed at RVA 0x675D60 (%d-byte stub) -- "
             "every packet class is named on its first send%s", n,
             ROOM3_GALLERY_QUIET ? ", and once the spectator plays back it sends no "
             "SOnlineAction battle packet" : " (measurement only)");
}

static int room3_entry_probe(unsigned int rva, const unsigned char* orig, int len,
                             const char* name)
{
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site; unsigned char* stub;
    void* fn = (void*)&room3_log_maker;
    unsigned char b[224]; int n = 0; long long rel; DWORD old;
    int tag = (int)InterlockedIncrement(&g_room3_ep_count) - 1;

    if (!mod || tag >= ROOM3_EP_MAX) return 0;
    g_room3_ep_name[tag] = name;
    site = mod + rva;
    if (memcmp(site, orig, (size_t)len) != 0) {
        log_line("ROOM3/make: bytes not at expected RVA 0x%X (%s) -- skipped", rva, name);
        return 0;
    }
    stub = (unsigned char*)gauge_alloc_near(site, 256);
    if (!stub) return 0;

    b[n++]=0x55;                                                      /* push rbp        */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xE5;                            /* mov rbp,rsp     */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xE4; b[n++]=0xF0;               /* and rsp,-16     */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xEC; b[n++]=0x60;               /* sub rsp,0x60    */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x44; b[n++]=0x24; b[n++]=0x28;  /* rax             */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;  /* rcx             */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x54; b[n++]=0x24; b[n++]=0x38;  /* rdx             */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x44; b[n++]=0x24; b[n++]=0x40;  /* r8              */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x48;  /* r9              */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x54; b[n++]=0x24; b[n++]=0x50;  /* r10             */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x58;  /* r11             */
    b[n++]=0x49; b[n++]=0x89; b[n++]=0xD1;                            /* mov r9,rdx: arg1 */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x55; b[n++]=0x08;               /* mov rdx,[rbp+8] */
    b[n++]=0x41; b[n++]=0xB8; memcpy(b+n,&tag,4); n+=4;               /* mov r8d,tag     */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&fn,8); n+=8;                /* mov rax,&logger */
    b[n++]=0xFF; b[n++]=0xD0;                                         /* call rax        */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x28;
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x54; b[n++]=0x24; b[n++]=0x38;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x40;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x48;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x54; b[n++]=0x24; b[n++]=0x50;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x58;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xEC;                            /* mov rsp,rbp     */
    b[n++]=0x5D;                                                      /* pop rbp         */
    memcpy(b+n, orig, (size_t)len); n += len;
    rel = (long long)(site + len) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);
    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) return 0;
    if (!VirtualProtect(site, (SIZE_T)len, PAGE_EXECUTE_READWRITE, &old)) return 0;
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    if (len > 5) memset(site + 5, 0x90, (size_t)len - 5);
    VirtualProtect(site, (SIZE_T)len, old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, (size_t)len);
    return 1;
}

/* exe+0x142537, inside OOnlinePlayable::vfunc75, just before it asks the playable for
   its control type. Calls that same getter (slot 76, [vtable+0x260]) and logs the answer --
   4 is the pad, 5 a BrainBase, 6 the AI, anything else gets no Brain from this function. */
static void room3_log_ctltype(void* playable)
{
    int t = -1;
    __try {
        void** vt = *(void***)playable;
        int (*get)(void*) = (int (*)(void*))vt[0x260 / 8];
        t = get(playable);
    } __except(EXCEPTION_EXECUTE_HANDLER) { t = -2; }
    if (t >= 0 && t < 8) InterlockedIncrement64(&g_room3_ct_n[t]);
    if (InterlockedIncrement(&g_room3_ct_lines) <= 12)
        log_line("ROOM3/ctl: OOnlinePlayable::vfunc75 on %p -- control type %d (%s)",
                 playable, t,
                 t == 4 ? "the pad, gets a BrainPad" :
                 t == 5 ? "gets a BrainBase" :
                 t == 6 ? "the AI, gets a BrainAi" : "NO Brain from this function");
}

/* The control-type probe needs its own stub: the generic one passes rcx, and here the
   playable is in rsi. */
static void patch_room3_ctltype(void)
{
    static const unsigned char orig[6] = { 0x48,0x8B,0x06, 0x48,0x8B,0xCE };
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site; unsigned char* stub;
    void* fn = (void*)&room3_log_ctltype;
    unsigned char b[224]; int n = 0; long long rel; DWORD old;

    if (!mod) return;
    site = mod + 0x142537;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("ROOM3/ctl: bytes not at expected RVA 0x142537 -- skipped"); return; }
    stub = (unsigned char*)gauge_alloc_near(site, 256);
    if (!stub) return;

    b[n++]=0x55;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xE5;
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xE4; b[n++]=0xF0;
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xEC; b[n++]=0x60;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x44; b[n++]=0x24; b[n++]=0x28;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x54; b[n++]=0x24; b[n++]=0x38;
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x44; b[n++]=0x24; b[n++]=0x40;
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x48;
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x54; b[n++]=0x24; b[n++]=0x50;
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x58;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xF1;                            /* mov rcx,rsi */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&fn,8); n+=8;
    b[n++]=0xFF; b[n++]=0xD0;
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x28;
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x54; b[n++]=0x24; b[n++]=0x38;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x40;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x48;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x54; b[n++]=0x24; b[n++]=0x50;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x58;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xEC;
    b[n++]=0x5D;
    memcpy(b+n, orig, sizeof(orig)); n += (int)sizeof(orig);
    rel = (long long)(mod + 0x14253D) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);
    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) return;
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) return;
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    site[5] = 0x90;
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));
    log_line("ROOM3/ctl: installed at RVA 0x142537 -- every fighter's control type is now "
             "read as OOnlinePlayable::vfunc75 chooses its Brain");
}

static void patch_room3_brain_makers(void)
{
    static const unsigned char pad[5]  = { 0x48,0x89,0x5C,0x24,0x18 };
    static const unsigned char ai1[5]  = { 0x48,0x89,0x54,0x24,0x10 };
    static const unsigned char ai2[5]  = { 0x48,0x89,0x5C,0x24,0x08 };
    static const unsigned char trai[5] = { 0x48,0x89,0x5C,0x24,0x10 };
    int ok = 0;
    ok += room3_entry_probe(0x143C30, pad,  5, "BrainPad");
    ok += room3_entry_probe(0x143080, ai1,  5, "BrainAi (0x143080)");
    ok += room3_entry_probe(0x3F2890, ai2,  5, "BrainAi (0x3F2890)");
    ok += room3_entry_probe(0x4662C0, trai, 5, "BrainTrainingAi");
    {   /* type 5's Brain, which P26 did not count */
        static const unsigned char bb[5] = { 0x48,0x89,0x54,0x24,0x10 };
        ok += room3_entry_probe(0x4104B0, bb, 5, "BrainBase");
    }
    patch_room3_ctltype();
    {   /* the native gallery (spectator) system -- live-build addresses, verified by the
           functions' own assert strings. A leading '*' routes them to the gallery logger. */
        static const unsigned char st[5] = { 0x48,0x89,0x5C,0x24,0x10 };
        static const unsigned char cr[5] = { 0x48,0x89,0x5C,0x24,0x18 };
        static const unsigned char gl[5] = { 0x48,0x89,0x5C,0x24,0x18 };
        static const unsigned char sp[5] = { 0x48,0x89,0x5C,0x24,0x10 };
        int g = 0;
        g += room3_entry_probe(0x1AF920, st, 5, "*StartLiveStreamingSystem");
        g += room3_entry_probe(0x1AFD10, cr, 5, "*CreateOneMatchReplayData");
        g += room3_entry_probe(0x1B0760, gl, 5, "*GalleryLeaderSend(FUN_1B0760)");
        g += room3_entry_probe(0x1AFAC0, sp, 5, "*StopLiveStreaming");
        {   /* P33: the host's shipping call and the receiver's packet handler (corpus
               0x1401B0240 and PacketLiveStream::vfunc3 0x1401AF170, via buildmap) */
            static const unsigned char snd[5] = { 0x40,0x53,0x55,0x56,0x57 };  /* pushes */
            static const unsigned char rcv[5] = { 0x48,0x89,0x5C,0x24,0x08 };
            g += room3_entry_probe(0x1B04C0, snd, 5, "*LiveStreamSend(0x1B04C0)");
            g += room3_entry_probe(0x1AF3F0, rcv, 5, "*LiveStreamRecv(0x1AF3F0)");
        }
        log_line("ROOM3/gallery: %d of 6 native spectator-streaming probes installed", g);
        patch_room3_pkt_gate();
    }
    log_line("ROOM3/make: %d of 5 Brain installers instrumented -- a player should make a "
             "BrainPad for its own fighter; what the spectator makes is the question", ok);
}

/* Scan a fighter for a pointer to any Brain vtable. Returns the offset, or -1. */
static int room3_find_brain(unsigned char* f, const char** cls)
{
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    int i;
    if (!mod || !f) return -1;
    for (i = 0; i < 0x2000; i += 8) {
        void* v;
        __try { v = *(void**)(f + i); }
        __except(EXCEPTION_EXECUTE_HANDLER) { return -1; }
        if ((unsigned char*)v < mod || (unsigned char*)v > mod + 0x2000000) continue;
        {
            unsigned rva = (unsigned)((unsigned char*)v - mod);
            if (rva == ROOM3_VT_BRAINPAD)  { *cls = "BrainPad";        return i; }
            if (rva == ROOM3_VT_BRAINAI)   { *cls = "BrainAi";         return i; }
            if (rva == ROOM3_VT_BRAINBASE) { *cls = "BrainBase";       return i; }
            if (rva == ROOM3_VT_BRAINTRAI) { *cls = "BrainTrainingAi"; return i; }
        }
    }
    return -1;
}

/* Which Brain each fighter carries. Rate-limited: scanning 0x2000 bytes per fighter every
   frame would be a probe that changes what it measures, which §6.11 already paid for. */
static void room3_log_brains(void)
{
    unsigned char* c = (unsigned char*)g_room3_ctx;
    int seat;
    if (!c) return;
    if ((InterlockedIncrement64(&g_room3_brain_tick) % 240) != 1) return;
    __try {
        unsigned char* bc0 = *(unsigned char**)(c + 0xBC0);
        unsigned char** vec = bc0 ? *(unsigned char***)(bc0 + 0x20) : 0;
        unsigned char** end = bc0 ? *(unsigned char***)(bc0 + 0x28) : 0;
        int cnt = (vec && end && end > vec) ? (int)(end - vec) : 0;
        if (cnt > 2) cnt = 2;
        for (seat = 0; seat < cnt; seat++) {
            const char* cls = "(none)";
            int at = room3_find_brain(vec[seat], &cls);
            LONG key = (LONG)((at & 0xFFFF) | (cls[5] << 16));
            if (g_room3_brain_seen[seat] == key) continue;
            g_room3_brain_seen[seat] = key;
            if (InterlockedIncrement(&g_room3_brain_line) > 16) return;
            log_line("ROOM3/brain: fighter at seat %d carries %s at +0x%X -- a normal client "
                     "has a different Brain on its own side than on the remote one, so the "
                     "pair is what matters, not either half", seat, cls, at);
        }
    } __except(EXCEPTION_EXECUTE_HANDLER) { }
}

static void room3_log_update(void* ret, void* self, unsigned int st)
{
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned rva = (unsigned)((unsigned char*)ret - mod);
    room3_note_object(self, st);
    room3_log_brains();            /* which Brain sits on each fighter, per client */
    InterlockedIncrement64(&g_room3_up_calls);
    g_room3_up_last = (LONG)st;
    g_room3_up_tick = GetTickCount64();
    if (rva != (unsigned)g_room3_up_caller) {
        g_room3_up_caller = (LONG)rva;
        if (InterlockedIncrement(&g_room3_up_callers) <= 8)
            log_line("ROOM3/up: the per-frame update is called from exe+0x%X", rva);
    }
}

/* exe+0x6AA0D0, the scene tick that calls the update as vtable slot 27. */
static void room3_log_tick(void* ret)
{
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned rva = (unsigned)((unsigned char*)ret - mod);
    InterlockedIncrement64(&g_room3_tick_calls);
    g_room3_tick_tick = GetTickCount64();
    if (rva != (unsigned)g_room3_tick_caller) {
        g_room3_tick_caller = (LONG)rva;
        if (InterlockedIncrement(&g_room3_tick_callers) <= 8)
            log_line("ROOM3/tick: the scene tick is called from exe+0x%X", rva);
    }
}

/* slot 11, the object's own entry point: whoever calls this is what drives everything. */
static void room3_log_reach(void* ret)
{
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned rva = (unsigned)((unsigned char*)ret - mod);
    InterlockedIncrement64(&g_room3_reach_calls);
    g_room3_reach_tick = GetTickCount64();
    if (rva != (unsigned)g_room3_reach_caller) {
        g_room3_reach_caller = (LONG)rva;
        if (InterlockedIncrement(&g_room3_reach_callers) <= 8)
            log_line("ROOM3/slot11: the object is driven from exe+0x%X", rva);
    }
}

/* ---- a hardware write breakpoint on one byte -------------------------------- */
static void*         g_room3_bp_addr   = 0;
static volatile LONG g_room3_bp_hits   = 0;
static volatile LONG g_room3_bp_armed  = 0;
static DWORD         g_room3_bp_thread = 0;
static PVOID         g_room3_veh       = 0;
static int           g_room3_bp_threads = 0;


static LONG CALLBACK room3_bp_handler(EXCEPTION_POINTERS* ep)
{
    if (ep->ExceptionRecord->ExceptionCode == EXCEPTION_SINGLE_STEP && g_room3_bp_addr) {
        unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
        ULONG_PTR rip = (ULONG_PTR)ep->ExceptionRecord->ExceptionAddress;
        /* ⚠ A tally, not "the first N". This byte is written tens of thousands of times
           per match, so a capped list of early hits describes start-up and nothing else. */
        {
            LONG r = (LONG)(rip - (ULONG_PTR)mod);
            int k;
            for (k = 0; k < ROOM3_WR_MAX; k++) {
                if (g_room3_wr_rip[k] == r) { g_room3_wr_n[k]++; break; }
                if (g_room3_wr_rip[k] == 0) {
                    g_room3_wr_rip[k] = r; g_room3_wr_n[k] = 1;
                    log_line("ROOM3/bp: the skip-frame byte is written from exe+0x%X "
                             "(thread %lu) -- it now reads %d", (unsigned)r,
                             GetCurrentThreadId(), *(unsigned char*)g_room3_bp_addr);
                    break;
                }
            }
            InterlockedIncrement(&g_room3_bp_hits);
        }
        ep->ContextRecord->Dr6 = 0;
        ep->ContextRecord->EFlags |= 0x10000;   /* RF: resume without trapping again */
        return EXCEPTION_CONTINUE_EXECUTION;
    }
    return EXCEPTION_CONTINUE_SEARCH;
}

/* Arm DR0 on one thread. Silent by construction: the caller logs, never this. */
static int room3_bp_arm_one(DWORD tid, CONTEXT* c)
{
    HANDLE th;
    BOOL got, set = FALSE;
    if (tid == GetCurrentThreadId()) return 0;
    th = OpenThread(THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT | THREAD_SET_CONTEXT,
                    FALSE, tid);
    if (!th) return 0;
    if (SuspendThread(th) == (DWORD)-1) { CloseHandle(th); return 0; }
    memset(c, 0, sizeof(CONTEXT));
    c->ContextFlags = CONTEXT_DEBUG_REGISTERS;
    got = GetThreadContext(th, c);
    if (got) {
        c->Dr0 = (DWORD64)(ULONG_PTR)g_room3_bp_addr;
        c->Dr7 = (c->Dr7 & ~(DWORD64)0xF0003) | 1 | ((DWORD64)1 << 16);
        c->ContextFlags = CONTEXT_DEBUG_REGISTERS;
        set = SetThreadContext(th, c);
    }
    ResumeThread(th);
    CloseHandle(th);
    return set ? 1 : 0;
}

static DWORD WINAPI room3_bp_arm_thread(LPVOID unused)
{
    CONTEXT* c;
    void* buf;
    int pass;
    (void)unused;
    /* CONTEXT wants 16-byte alignment, so it is allocated rather than put on the stack. */
    buf = VirtualAlloc(NULL, sizeof(CONTEXT) + 32, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!buf) return 0;
    c = (CONTEXT*)(((ULONG_PTR)buf + 15) & ~(ULONG_PTR)15);


    /* ⚠⚠ NOT ONE LINE OF LOGGING WHILE A TARGET IS SUSPENDED, and that rule is the whole
       reason this works. On 2026-09-18 08:04 all three clients hung at launch: the ticking
       thread was suspended while it happened to hold the log's lock, this thread then
       blocked inside log_line waiting for that same lock, ResumeThread was never reached,
       and the game froze with no crash and no output -- which is also why not one ROOM3/bp
       line ever appeared. Suspending every thread in turn would reproduce that far more
       reliably, so room3_bp_arm_one is silent and the counting happens out here. */
    for (pass = 0; pass < 40; pass++) {
        HANDLE snap;
        /* ⚠ Arm on the object that is actually being ticked, not the first one that came
           through the gate. On 2026-09-18 14:55 the register watched a row with 2 ticks
           while the battle rode one with 1636 -- which is why the write of the 1 was never
           trapped despite 65 threads being armed. Re-picked every pass, and the whole loop
           re-arms every 3 s anyway, so a change of address costs nothing. */
        /* The target is no longer a heap object that has to be guessed at: it is a fixed
           global, so it is set once and never re-picked. The old code chased the busiest
           sub-object because the byte at [obj+8]+0xF0 lived on one -- that byte turned out
           not to be the cause at all (P10), and this one is. */
        {
            unsigned char* m = (unsigned char*)GetModuleHandleA(NULL);
            if (m && g_room3_bp_addr != m + ROOM3_SKIPFLAG_RVA) {
                g_room3_bp_addr = m + ROOM3_SKIPFLAG_RVA;
                g_room3_bp_sub  = 0;
                g_room3_bp_threads = -1;          /* force the next line to print */
            }
        }
        snap = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
        THREADENTRY32 te;
        DWORD pid = GetCurrentProcessId();
        int armed = 0;
        if (snap != INVALID_HANDLE_VALUE) {
            te.dwSize = sizeof(te);
            if (Thread32First(snap, &te)) {
                do {
                    if (te.th32OwnerProcessID == pid)
                        armed += room3_bp_arm_one(te.th32ThreadID, c);
                } while (Thread32Next(snap, &te));
            }
            CloseHandle(snap);
        }
        if (pass == 0 || armed != g_room3_bp_threads) {
            g_room3_bp_threads = armed;
            log_line("ROOM3/bp: watching writes to %p -- the skip-frame byte, RVA 0x%X, "
                     "tested at exe+0x8575AA -- on %d thread(s)", g_room3_bp_addr,
                     (unsigned)ROOM3_SKIPFLAG_RVA, armed);
        }
        if (!armed && pass == 0)
            log_line("ROOM3/bp: could not arm on any thread -- the writer stays unnamed");
        Sleep(3000);       /* re-arm: threads made later start with clean debug registers */
    }
    return 0;
}

/* ⚠ One row per OBJECT, and every probe here keys by the same pointer. The table used to
   be keyed by [obj+8], which the loop probe below never sees, so its rows would have sat
   beside the gate's instead of merging -- the exact conflation P9 had just removed, in a
   new costume. Find-or-insert, never overwrite, a full table simply stops recording. */
static int room3_sub_row(void* obj)
{
    int i;
    for (i = 0; i < ROOM3_SUB_MAX; i++) {
        if (g_room3_sub[i] == obj) return i;
        if (g_room3_sub[i] == 0) {
            g_room3_sub[i] = obj;
            g_room3_sub_byte[i] = -1;
            g_room3_sub_word[i] = -1;
            return i;
        }
    }
    return -1;
}

/* exe+0x8077E4, on the path to the barrier's timeout test. The delta it compares against
   1000.0 is [[ctx+0x4A8]+0x300]+0x10 minus +0x8, and 1000 units is ten seconds if the unit
   is a hundredth -- which is exactly how long the spectator's battle survives. */
static void room3_log_timeout(void* ctx)
{
    float now = 0.0f, then = 0.0f, d;
    __try {
        unsigned char* a = *(unsigned char**)((unsigned char*)ctx + 0x4A8);
        unsigned char* t = a ? *(unsigned char**)(a + 0x300) : 0;
        if (!t) {
            if (InterlockedIncrement(&g_room3_to_lines) <= 8)
                log_line("ROOM3/timeout: [ctx+0x4A8] = %p, its +0x300 is null -- the site "
                         "ran but there is no timer object", a);
            return;
        }
        now  = *(float*)(t + 0x10);
        then = *(float*)(t + 0x08);
    } __except(EXCEPTION_EXECUTE_HANDLER) { return; }
    d = now - then;
    g_room3_to_now = now; g_room3_to_then = then;
    /* one line per whole unit of drift, so a healthy client costs a handful and a drifting
       one draws its own curve */
    if ((LONG)(d / 100.0f) != (LONG)(g_room3_to_lines ? g_room3_to_lines - 1 : -1)) {
        if (InterlockedIncrement(&g_room3_to_lines) <= 24)
            log_line("ROOM3/timeout: the barrier's clock reads %.1f, its mark %.1f, delta "
                     "%.1f -- it ends the battle above 1000 (exe+0x80782A)", now, then, d);
    }
}

/* exe+0x80782C, where the barrier loads the fighter flag word it is about to test for
   bit 0x400. Logs it on every client -- a healthy value has never been observed, only the
   spectator's zero -- and, on the spectator, sets the bits before the test. */
static void room3_log_battlebit(void* ctx)
{
    LONG seat = -1, w = -1;
    unsigned char* f = 0;
    __try {
        unsigned char* bc0 = *(unsigned char**)((unsigned char*)ctx + 0xBC0);
        unsigned char** vec = bc0 ? *(unsigned char***)(bc0 + 0x20) : 0;
        seat = *(LONG*)((unsigned char*)ctx + 0xC40);
        f = (vec && seat >= 0) ? vec[seat] : 0;
        /* ⚠ No silent return. A probe that says nothing when a pointer is null is
           indistinguishable from a probe that never ran, and that ambiguity is what made
           essai #126 unreadable. */
        if (!f) {
            if (InterlockedIncrement(&g_room3_bit_lines) <= 24)
                log_line("ROOM3/bit: reached exe+0x80782C but the fighter pointer is null "
                         "(bc0 %p, vec %p, seat %d) -- the site DID run", bc0, vec,
                         (int)seat);
            return;
        }
        w = *(LONG*)f;
        if (ROOM3_FORCE_BATTLE_BIT && g_room3_is_spectator && (w & 0x401) != 0x401) {
            *(unsigned*)f |= 0x401u;
            InterlockedIncrement64(&g_room3_bit_set);
        }
    } __except(EXCEPTION_EXECUTE_HANDLER) { return; }
    if (w == g_room3_bit_last) return;
    g_room3_bit_last = w;
    if (InterlockedIncrement(&g_room3_bit_lines) > 24) return;
    log_line("ROOM3/bit: the barrier is about to test bit 0x400 of the fighter at seat %d "
             "-- the word reads 0x%X (exe+0x807842)%s", (int)seat, (unsigned)w,
             (ROOM3_FORCE_BATTLE_BIT && g_room3_is_spectator)
                 ? "; 0x401 forced on this client" : "");
}

/* exe+0x80789A, the head of the battle-load barrier's ABORT block: [ctx+0xCE0] = 2 and
   then message 0x45F, which is what ended the spectator's own battle 9.73 s in. Reads the
   four conditions that lead here rather than counting which branch fired -- two of them are
   rel8 and could not be retargeted anyway, and a counter per branch would only ever say
   "not me". */
static void room3_log_abort(void* ctx)
{
    void* p4C8 = 0; LONG v4C8 = -1, flags = -1, seat = -1; LONG64 nth;
    nth = InterlockedIncrement(&g_room3_abort_n);
    if (nth > 6) return;
    __try {
        p4C8 = *(void**)((unsigned char*)ctx + 0x4C8);
        if (p4C8) v4C8 = *(LONG*)((unsigned char*)p4C8 + 8);
        seat = *(LONG*)((unsigned char*)ctx + 0xC40);
        {
            unsigned char* bc0 = *(unsigned char**)((unsigned char*)ctx + 0xBC0);
            unsigned char* vec = *(unsigned char**)(bc0 + 0x20);
            unsigned char* f   = *(unsigned char**)(vec + (size_t)seat * 8);
            flags = *(LONG*)f;
        }
    } __except(EXCEPTION_EXECUTE_HANDLER) { }
    log_line("ROOM3/abort: the load barrier is ending this battle (exe+0x80789A, sends "
             "0x45F). [+0x4C8] = %p, [[+0x4C8]+8] = %d, seat = %d, fighter flags = 0x%X, "
             "bit 0x400 %s -- null or zero on the first two is one exit, a clear 0x400 is "
             "another, and a 10 s timeout is the third",
             p4C8, (int)v4C8, (int)seat, (unsigned)flags,
             (flags >= 0 && (flags & 0x400)) ? "SET" : "CLEAR");
}

/* exe+0x801BF1, the load-wait throttle's test. Returns non-zero when the caller should
   pretend the state is high enough -- i.e. when this client is the spectator and the arm
   is on. The value is tallied per distinct state so "it is always 0xC9" is a reading and
   not an inference from a different probe. */
static int room3_log_throttle(void* self)
{
    LONG v = -1;
    int i;
    __try { v = (LONG)(*(unsigned short*)((unsigned char*)self + 0x3A0)); }
    __except(EXCEPTION_EXECUTE_HANDLER) { return 0; }
    InterlockedIncrement64(&g_room3_thr_calls);
    if (v <= 0x12C) {
        InterlockedIncrement64(&g_room3_thr_skip);
        for (i = 0; i < ROOM3_THR_MAX; i++) {
            if (g_room3_thr_state[i] == v) { g_room3_thr_n[i]++; break; }
            if (g_room3_thr_n[i] == 0) {
                g_room3_thr_state[i] = v; g_room3_thr_n[i] = 1;
                log_line("ROOM3/thr: the load-wait throttle read state 0x%X at exe+0x801BF1 "
                         "-- anything <= 0x12C drops the next frame of the whole task", v);
                break;
            }
        }
    }
    /* ⚠ Bypassing the `jbe` at 0x801BF8 was measured to change nothing: the flag kept
       being set 24918 times while the branch was refused 12904 times, because 0x801C58 has
       three ways in and only one was bypassed. So the STORE is neutralised instead -- the
       one instruction all three edges exist to reach, and the one the breakpoint tally
       named on every client. Once, and only on a client that is the spectator. */
    if (ROOM3_NO_THROTTLE && g_room3_is_spectator &&
        InterlockedCompareExchange(&g_room3_nop_done, 1, 0) == 0) {
        static const unsigned char want[7] = { 0xC6, 0x05, 0, 0, 0, 0, 0x01 };
        unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
        unsigned char* site = mod + 0x801C6D;
        DWORD old;
        if (site[0] != want[0] || site[1] != want[1] || site[6] != want[6]) {
            log_line("ROOM3/thr: exe+0x801C6D is not `mov byte [rip+d],1` -- not touched");
        } else if (VirtualProtect(site, 7, PAGE_EXECUTE_READWRITE, &old)) {
            memset(site, 0x90, 7);
            VirtualProtect(site, 7, old, &old);
            FlushInstructionCache(GetCurrentProcess(), site, 7);
            log_line("ROOM3/thr: exe+0x801C6D replaced with 7 NOPs on this client -- the "
                     "skip-frame flag can no longer be set from the site that set it "
                     "24918 times, and the two players are untouched");
        } else {
            log_line("ROOM3/thr: VirtualProtect failed at exe+0x801C6D -- not touched");
        }
    }
    return 0;      /* the branch is left alone; the store is what was neutralised */
}

/* exe+0x857390, slot 5 of TAppRootTask / SteamTask. */
static void room3_log_task5(void* self, void* ret)
{
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned rva = (unsigned)((unsigned char*)ret - mod);
    InterlockedIncrement64(&g_room3_t5_calls);
    g_room3_t5_tick = GetTickCount64();
    if ((LONG)rva != g_room3_t5_caller) {
        g_room3_t5_caller = (LONG)rva;
        if (InterlockedIncrement(&g_room3_t5_lines) <= 8)
            log_line("ROOM3/task5: exe+0x857390 entered on %p from exe+0x%X", self, rva);
    }
}

/* exe+0x857CC9, immediately before slot 5 calls exe+0x8A0B10. */
static void room3_log_task5_reach(void)
{
    InterlockedIncrement64(&g_room3_t5_reach);
    g_room3_t5_rtick = GetTickCount64();
}

/* exe+0x8A0B10, the entry of the function that contains the driving loop. Its counter and
   the loop head's counter must be compared, never conflated: 0x8A0CF5 is +0x1E5 inside. */
static void room3_log_fnentry(void* self, void* ret)
{
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned rva = (unsigned)((unsigned char*)ret - mod);
    InterlockedIncrement64(&g_room3_fn_calls);
    g_room3_fn_tick = GetTickCount64();
    if ((LONG)rva != g_room3_fn_caller) {
        g_room3_fn_caller = (LONG)rva;
        if (InterlockedIncrement(&g_room3_fn_lines) <= 8)
            log_line("ROOM3/fn: exe+0x8A0B10 entered on %p from exe+0x%X", self, rva);
    }
}

/* exe+0x8A0CF5, the head of the driving loop: how many elements it is about to walk. A
   count of zero means the body never runs and NOTHING is logged below -- which is exactly
   what "walked 0 times" looks like from inside the body, and why it needs its own probe. */
static void room3_log_walkhead(void* self, void* begin, void* end)
{
    LONG cnt;
    if (begin > end) return;
    cnt = (LONG)(((unsigned char*)end - (unsigned char*)begin) / 8);
    InterlockedIncrement64(&g_room3_walk_calls);
    g_room3_walk_tick = GetTickCount64();
    g_room3_walk_this = self;
    if (g_room3_walk_min < 0 || cnt < g_room3_walk_min) g_room3_walk_min = cnt;
    if (cnt > g_room3_walk_max) g_room3_walk_max = cnt;
    if (cnt == g_room3_walk_count) return;
    g_room3_walk_count = cnt;
    if (InterlockedIncrement(&g_room3_walk_lines) > 128) return;
    log_line("ROOM3/walk: the driving loop on %p is about to walk %d element(s) "
             "(exe+0x8A0CF5) -- zero means its body never runs and every probe inside it "
             "goes quiet without saying why", self, (int)cnt);
}

/* exe+0x8A0D10, the top of the driving loop's body -- reached for every element whatever
   its state word says, which is precisely what the exe+0x8A0D29 probe could not do. */
static void room3_log_driveloop(void* obj)
{
    LONG w;
    int i;
    __try {
        w = *(LONG*)((unsigned char*)obj + 0x7C);
    } __except(EXCEPTION_EXECUTE_HANDLER) { return; }
    i = room3_sub_row(obj);
    if (i < 0) return;
    g_room3_sub_walk[i]++;
    g_room3_sub_wtick[i] = GetTickCount64();
    if (w == g_room3_sub_word[i]) return;
    g_room3_sub_word[i] = w;
    if (InterlockedIncrement(&g_room3_drive_lines) > 512) return;
    log_line("ROOM3/word: obj %p [+0x7C] = %d -- the driving loop skips this element unless "
             "it is 4 (exe+0x8A0D1F), and that test runs BEFORE the byte at 0x8A0D29",
             obj, (int)w);
}

static void room3_log_drivegate(void* sub, void* scene)
{
    LONG v;
    int i;
    /* `sub` is [rbx+8], the object that carries the byte; `scene` is rbx, the element the
       loop is driving. The row is the element. */
    if (ROOM3_HWBP && InterlockedCompareExchange(&g_room3_bp_armed, 1, 0) == 0) {
        g_room3_bp_addr = (unsigned char*)sub + 0xF0;
        g_room3_bp_sub = scene;          /* WHICH element the debug register is watching:
                                            two hits with no attribution taught nothing */
        g_room3_bp_thread = GetCurrentThreadId();
        if (!g_room3_veh) g_room3_veh = AddVectoredExceptionHandler(1, room3_bp_handler);
        CloseHandle(CreateThread(NULL, 0, room3_bp_arm_thread, NULL, 0, NULL));
    }
    __try {
        v = (LONG)(*((unsigned char*)sub + 0xF0));
    } __except(EXCEPTION_EXECUTE_HANDLER) { return; }
    InterlockedIncrement64(&g_room3_drive_calls);
    i = room3_sub_row(scene);
    if (i < 0) return;
    g_room3_sub_bytes[i] = sub;
    g_room3_sub_seen[i]++;
    g_room3_sub_stick[i] = GetTickCount64();
    if (v) g_room3_sub_skip[i]++;
    else { g_room3_sub_pass[i]++; g_room3_sub_ptick[i] = GetTickCount64(); }
    if (v == g_room3_sub_byte[i]) return;
    g_room3_sub_byte[i] = v;
    if (InterlockedIncrement(&g_room3_drive_lines) > 512) return;
    log_line("ROOM3/drive: obj %p (byte carrier %p) [[rbx+8]+0xF0] = %d -- non-zero stops "
             "THIS object being ticked at all (exe+0x8A0D29)%s", scene, sub, v,
             (v && g_room3_is_spectator && ROOM3_FORCE_TICK)
                 ? "; forcing the branch not-taken on this client" : "");
}

/* Retarget one rel32 branch to a thunk that records its own RVA and jumps on. Nothing is
   stolen and no flag is written, so a branch sitting between a compare and another branch
   is safe -- which the `lock inc` crumb installer is not. */
static int room3_exit_thunk(unsigned int rva, int dispoff, int idx)
{
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site = mod + rva;
    int insn = dispoff + 4;
    int rel; unsigned char* target; unsigned char* th;
    unsigned char b[64]; int n = 0; long long d; DWORD old;
    void* g = (void*)&g_room3_exit;
    void* c = (void*)&g_room3_exit_n[idx];

    memcpy(&rel, site + dispoff, 4);
    target = site + insn + rel;
    th = (unsigned char*)gauge_alloc_near(site, 64);
    if (!th) return 0;
    g_room3_exit_rva[idx] = rva;

    b[n++] = 0x50;                                              /* push rax           */
    b[n++] = 0x9C;                                              /* pushfq             */
    b[n++] = 0x48; b[n++] = 0xB8; memcpy(b + n, &g, 8); n += 8; /* mov rax,&g_exit    */
    b[n++] = 0xC7; b[n++] = 0x00;                               /* mov dword [rax],   */
    memcpy(b + n, &rva, 4); n += 4;                             /*     this RVA       */
    /* ⚠ `lock inc` writes flags. These thunks hang off branch targets whose code may
       still read them, so the whole increment sits inside pushfq/popfq. The mov above
       needs no such care -- mov and push/pop leave flags alone. */
    b[n++] = 0x48; b[n++] = 0xB8; memcpy(b + n, &c, 8); n += 8; /* mov rax,&counter   */
    b[n++] = 0xF0; b[n++] = 0x48; b[n++] = 0xFF; b[n++] = 0x00; /* lock inc qword[rax]*/
    b[n++] = 0x9D;                                              /* popfq              */
    b[n++] = 0x58;                                              /* pop rax            */
    d = (long long)target - (long long)(th + n + 5);
    if (d > 0x7FFFFFFFLL || d < -0x80000000LL) return 0;
    b[n++] = 0xE9; memcpy(b + n, &d, 4); n += 4;

    memcpy(th, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), th, (size_t)n);

    d = (long long)th - (long long)(site + insn);
    if (d > 0x7FFFFFFFLL || d < -0x80000000LL) return 0;
    if (!VirtualProtect(site + dispoff, 4, PAGE_EXECUTE_READWRITE, &old)) return 0;
    rel = (int)d; memcpy(site + dispoff, &rel, 4);
    VirtualProtect(site + dispoff, 4, old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, (size_t)insn);
    return 1;
}

/* The twenty branches that leave exe+0x857390 before it reaches the call at 0x857CC9.
   Sixteen go to the shared tail exe+0x857E5D, so knowing the TARGET would say almost
   nothing -- it is the source that has to be named. */
static void patch_room3_exits(void)
{
    static const struct { unsigned int rva; int dispoff; } tab[] = {
        { 0x8575BA, 1 },
        { 0x857715, 2 },
        { 0x857723, 2 },
        { 0x857731, 2 },
        { 0x857802, 2 },
        { 0x85799E, 2 },
        { 0x857A2C, 1 },
        { 0x857A4D, 2 },
        { 0x857A84, 1 },
        { 0x857AA1, 1 },
        { 0x857AC1, 1 },
        { 0x857AD6, 2 },
        { 0x857AEA, 2 },
        { 0x857BF7, 2 },
        { 0x857C03, 1 },
        { 0x857C22, 2 },
        { 0x857C35, 1 },
        { 0x857C4F, 2 },
        { 0x857C5D, 1 },
        { 0x857C65, 2 },
    };
    int i, ok = 0;
    for (i = 0; i < (int)(sizeof(tab) / sizeof(tab[0])); i++)
        ok += room3_exit_thunk(tab[i].rva, tab[i].dispoff, i);
    g_room3_exits_on = ok;
    log_line("ROOM3/exit: %d of %d exits of slot 5 now record themselves -- the one still "
             "being taken at the freeze is where it gives up", ok,
             (int)(sizeof(tab) / sizeof(tab[0])));
}

/* exe+0x8077E4: steal `mov r8,[rdi+0x4A8]` (7 bytes, 4C 8B 87 A8 04 00 00 -- no rip
   operand, no call) and re-execute it after the logger. */
static void patch_room3_timeout(void)
{
    static const unsigned char orig[7] = { 0x4C,0x8B,0x87,0xA8,0x04,0x00,0x00 };
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site; unsigned char* stub;
    void* fn = (void*)&room3_log_timeout;
    unsigned char b[224]; int n = 0; long long rel; DWORD old;

    if (!mod) return;
    site = mod + 0x8077E4;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("ROOM3/timeout: bytes not at expected RVA 0x8077E4 -- skipped"); return; }
    stub = (unsigned char*)gauge_alloc_near(site, 256);
    if (!stub) { log_line("ROOM3/timeout: no trampoline within +/-2GB -- skipped"); return; }

    b[n++]=0x55;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xE5;
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xE4; b[n++]=0xF0;
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xEC; b[n++]=0x60;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x44; b[n++]=0x24; b[n++]=0x28;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x54; b[n++]=0x24; b[n++]=0x38;
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x44; b[n++]=0x24; b[n++]=0x40;
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x48;
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x54; b[n++]=0x24; b[n++]=0x50;
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x58;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xF9;                            /* mov rcx,rdi */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&fn,8); n+=8;
    b[n++]=0xFF; b[n++]=0xD0;
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x28;
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x54; b[n++]=0x24; b[n++]=0x38;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x40;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x48;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x54; b[n++]=0x24; b[n++]=0x50;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x58;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xEC;
    b[n++]=0x5D;

    memcpy(b+n, orig, sizeof(orig)); n += (int)sizeof(orig);
    rel = (long long)(mod + 0x8077EB) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);
    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("ROOM3/timeout: trampoline out of rel32 range -- skipped"); return; }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("ROOM3/timeout: VirtualProtect failed at RVA 0x8077E4"); return; }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    memset(site + 5, 0x90, sizeof(orig) - 5);
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));
    log_line("ROOM3/timeout: installed at RVA 0x8077E4 (%d-byte stub) -- the barrier's own "
             "clock is now read on every client", n);
}

/* exe+0x80782C: steal `mov rax,[rdi+0xBC0]` (7 bytes, 48 8B 87 C0 0B 00 00 -- no rip
   operand, no call) and re-execute it after the logger. */
static void patch_room3_battlebit(void)
{
    static const unsigned char orig[7] = { 0x48,0x8B,0x87,0xC0,0x0B,0x00,0x00 };
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site; unsigned char* stub;
    void* fn = (void*)&room3_log_battlebit;
    unsigned char b[224]; int n = 0; long long rel; DWORD old;

    if (!mod) return;
    site = mod + 0x80782C;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("ROOM3/bit: bytes not at expected RVA 0x80782C -- skipped"); return; }
    stub = (unsigned char*)gauge_alloc_near(site, 256);
    if (!stub) { log_line("ROOM3/bit: no trampoline within +/-2GB -- skipped"); return; }

    b[n++]=0x55;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xE5;
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xE4; b[n++]=0xF0;
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xEC; b[n++]=0x60;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x44; b[n++]=0x24; b[n++]=0x28;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x54; b[n++]=0x24; b[n++]=0x38;
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x44; b[n++]=0x24; b[n++]=0x40;
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x48;
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x54; b[n++]=0x24; b[n++]=0x50;
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x58;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xF9;                            /* mov rcx,rdi */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&fn,8); n+=8;
    b[n++]=0xFF; b[n++]=0xD0;
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x28;
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x54; b[n++]=0x24; b[n++]=0x38;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x40;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x48;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x54; b[n++]=0x24; b[n++]=0x50;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x58;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xEC;
    b[n++]=0x5D;

    memcpy(b+n, orig, sizeof(orig)); n += (int)sizeof(orig);
    rel = (long long)(mod + 0x807833) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);
    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("ROOM3/bit: trampoline out of rel32 range -- skipped"); return; }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("ROOM3/bit: VirtualProtect failed at RVA 0x80782C"); return; }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    memset(site + 5, 0x90, sizeof(orig) - 5);
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));
    log_line("ROOM3/bit: installed at RVA 0x80782C (%d-byte stub) -- the fighter flag word "
             "the barrier tests is now read%s", n,
             ROOM3_FORCE_BATTLE_BIT ? ", and 0x401 is forced on the spectator" : "");
}

/* exe+0x80789A: steal `mov dword [rdi+0xCE0], 2` (10 bytes, C7 87 E0 0C 00 00 02 00 00 00
   -- no rip operand, no call) and re-execute it after the logger. */
static void patch_room3_abort(void)
{
    static const unsigned char orig[10] =
        { 0xC7,0x87,0xE0,0x0C,0x00,0x00,0x02,0x00,0x00,0x00 };
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site; unsigned char* stub;
    void* fn = (void*)&room3_log_abort;
    unsigned char b[224]; int n = 0; long long rel; DWORD old;

    if (!mod) return;
    site = mod + 0x80789A;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("ROOM3/abort: bytes not at expected RVA 0x80789A -- skipped"); return; }
    stub = (unsigned char*)gauge_alloc_near(site, 256);
    if (!stub) { log_line("ROOM3/abort: no trampoline within +/-2GB -- skipped"); return; }

    b[n++]=0x55;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xE5;
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xE4; b[n++]=0xF0;
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xEC; b[n++]=0x60;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x44; b[n++]=0x24; b[n++]=0x28;  /* rax */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;  /* rcx */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x54; b[n++]=0x24; b[n++]=0x38;  /* rdx */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x44; b[n++]=0x24; b[n++]=0x40;  /* r8  */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x48;  /* r9  */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x54; b[n++]=0x24; b[n++]=0x50;  /* r10 */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x58;  /* r11 */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xF9;                            /* mov rcx,rdi */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&fn,8); n+=8;
    b[n++]=0xFF; b[n++]=0xD0;
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x28;
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x54; b[n++]=0x24; b[n++]=0x38;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x40;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x48;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x54; b[n++]=0x24; b[n++]=0x50;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x58;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xEC;
    b[n++]=0x5D;

    memcpy(b+n, orig, sizeof(orig)); n += (int)sizeof(orig);
    rel = (long long)(mod + 0x8078A4) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);
    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("ROOM3/abort: trampoline out of rel32 range -- skipped"); return; }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("ROOM3/abort: VirtualProtect failed at RVA 0x80789A"); return; }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    memset(site + 5, 0x90, sizeof(orig) - 5);
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));
    log_line("ROOM3/abort: installed at RVA 0x80789A (%d-byte stub) -- the battle-load "
             "barrier's abort path now says why it fired", n);
}

/* exe+0x801BF1: steal `cmp word [rdi+0x3A0],ax` (7 bytes, 66 39 87 A0 03 00 00 -- no rip
   operand, no call). The compare is re-executed after the logger returns so the `jbe` that
   follows sees the flags it expects. With the arm on, the spectator jumps straight past
   the flag-setting block instead. */
static void patch_room3_throttle(void)
{
    static const unsigned char orig[7] = { 0x66,0x39,0x87,0xA0,0x03,0x00,0x00 };
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site; unsigned char* stub;
    void* fn = (void*)&room3_log_throttle;
    unsigned char b[224]; int n = 0, off_norm; long long rel; DWORD old;

    if (!mod) return;
    site = mod + 0x801BF1;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("ROOM3/thr: bytes not at expected RVA 0x801BF1 -- skipped"); return; }
    stub = (unsigned char*)gauge_alloc_near(site, 256);
    if (!stub) { log_line("ROOM3/thr: no trampoline within +/-2GB -- skipped"); return; }

    b[n++]=0x55;                                                      /* push rbp        */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xE5;                            /* mov rbp,rsp     */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xE4; b[n++]=0xF0;               /* and rsp,-16     */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xEC; b[n++]=0x60;               /* sub rsp,0x60    */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x44; b[n++]=0x24; b[n++]=0x28;  /* rax             */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;  /* rcx             */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x54; b[n++]=0x24; b[n++]=0x38;  /* rdx             */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x44; b[n++]=0x24; b[n++]=0x40;  /* r8              */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x48;  /* r9              */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x54; b[n++]=0x24; b[n++]=0x50;  /* r10             */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x58;  /* r11             */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xF9;                            /* mov rcx,rdi     */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&fn,8); n+=8;                /* mov rax,&logger */
    b[n++]=0xFF; b[n++]=0xD0;                                         /* call rax        */
    b[n++]=0x84; b[n++]=0xC0;                                         /* test al,al      */
    b[n++]=0x0F; b[n++]=0x84; memset(b+n,0,4); off_norm = n; n+=4;    /* je normal       */

    /* the arm: restore and jump PAST the whole flag-setting block, to where a healthy
       client goes when its state is high enough */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x28;
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x54; b[n++]=0x24; b[n++]=0x38;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x40;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x48;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x54; b[n++]=0x24; b[n++]=0x50;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x58;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xEC;
    b[n++]=0x5D;
    b[n++]=0x48; b[n++]=0x39; b[n++]=0xFF;                            /* cmp rdi,rdi -> ZF */
    rel = (long long)(mod + 0x801BFA) - (long long)(stub + n + 5);    /* the not-taken arm */
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;

    {   /* patch the je displacement now that the arm block's length is known */
        int here = n;
        int d = here - (off_norm + 4);
        memcpy(b + off_norm, &d, 4);
    }

    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x28;
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x54; b[n++]=0x24; b[n++]=0x38;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x40;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x48;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x54; b[n++]=0x24; b[n++]=0x50;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x58;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xEC;
    b[n++]=0x5D;
    memcpy(b+n, orig, sizeof(orig)); n += (int)sizeof(orig);          /* the stock compare */
    rel = (long long)(mod + 0x801BF8) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);
    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("ROOM3/thr: trampoline out of rel32 range -- skipped"); return; }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("ROOM3/thr: VirtualProtect failed at RVA 0x801BF1"); return; }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    site[5] = 0x90; site[6] = 0x90;
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));
    log_line("ROOM3/thr: installed at RVA 0x801BF1 (%d-byte stub) -- the load-wait throttle "
             "is now read%s", n,
             ROOM3_NO_THROTTLE ? ", and disarmed on the spectator" : " (measurement only)");
}

/* exe+0x857390: steal `mov rax,rsp` (3 bytes) -- too short for a jmp on its own, so the
   next store goes with it: 48 8B C4 48 89 58 10, seven bytes, no rip operand and no call.
   `mov rax,rsp` must run BEFORE the stub frames anything, so it is re-executed at the end
   like every other stolen pair here; rax is dead on entry. */
static void patch_room3_task5_entry(void)
{
    static const unsigned char orig[7] = { 0x48,0x8B,0xC4, 0x48,0x89,0x58,0x10 };
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site; unsigned char* stub;
    void* fn = (void*)&room3_log_task5;
    unsigned char b[224]; int n = 0; long long rel; DWORD old;

    if (!mod) return;
    site = mod + 0x857390;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("ROOM3/task5: bytes not at expected RVA 0x857390 -- skipped"); return; }
    stub = (unsigned char*)gauge_alloc_near(site, 256);
    if (!stub) { log_line("ROOM3/task5: no trampoline within +/-2GB -- skipped"); return; }

    b[n++]=0x55;                                                      /* push rbp        */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xE5;                            /* mov rbp,rsp     */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xE4; b[n++]=0xF0;               /* and rsp,-16     */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xEC; b[n++]=0x60;               /* sub rsp,0x60    */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x44; b[n++]=0x24; b[n++]=0x28;  /* [rsp+28]=rax    */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;  /* rcx             */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x54; b[n++]=0x24; b[n++]=0x38;  /* rdx             */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x44; b[n++]=0x24; b[n++]=0x40;  /* r8              */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x48;  /* r9              */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x54; b[n++]=0x24; b[n++]=0x50;  /* r10             */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x58;  /* r11             */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x55; b[n++]=0x08;               /* mov rdx,[rbp+8] */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&fn,8); n+=8;                /* mov rax,&logger */
    b[n++]=0xFF; b[n++]=0xD0;                                         /* call rax        */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x28;  /* restore rax     */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;  /* rcx             */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x54; b[n++]=0x24; b[n++]=0x38;  /* rdx             */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x40;  /* r8              */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x48;  /* r9              */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x54; b[n++]=0x24; b[n++]=0x50;  /* r10             */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x58;  /* r11             */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xEC;                            /* mov rsp,rbp     */
    b[n++]=0x5D;                                                      /* pop rbp         */

    memcpy(b+n, orig, sizeof(orig)); n += (int)sizeof(orig);
    rel = (long long)(mod + 0x857397) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);
    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("ROOM3/task5: trampoline out of rel32 range -- skipped"); return; }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("ROOM3/task5: VirtualProtect failed at RVA 0x857390"); return; }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    site[5] = 0x90; site[6] = 0x90;
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));
    log_line("ROOM3/task5: installed at RVA 0x857390 (%d-byte stub) -- slot 5 of "
             "TAppRootTask / SteamTask, the only caller of the loop function", n);
}

/* exe+0x857CC9: steal `movaps xmm1,xmm9` + `mov rcx,rax` (7 bytes, no rip operand, no
   call), immediately before the call to exe+0x8A0B10. Both are re-executed after the
   logger returns, so nothing the call clobbers can matter. */
static void patch_room3_task5_reach(void)
{
    static const unsigned char orig[7] = { 0x41,0x0F,0x28,0xC9, 0x48,0x8B,0xC8 };
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site; unsigned char* stub;
    void* fn = (void*)&room3_log_task5_reach;
    unsigned char b[224]; int n = 0; long long rel; DWORD old;

    if (!mod) return;
    site = mod + 0x857CC9;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("ROOM3/task5: bytes not at expected RVA 0x857CC9 -- skipped"); return; }
    stub = (unsigned char*)gauge_alloc_near(site, 256);
    if (!stub) { log_line("ROOM3/task5: no trampoline near 0x857CC9 -- skipped"); return; }

    b[n++]=0x55;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xE5;
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xE4; b[n++]=0xF0;
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xEC; b[n++]=0x60;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x44; b[n++]=0x24; b[n++]=0x28;  /* rax             */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;  /* rcx             */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x54; b[n++]=0x24; b[n++]=0x38;  /* rdx             */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x44; b[n++]=0x24; b[n++]=0x40;  /* r8              */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x48;  /* r9              */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x54; b[n++]=0x24; b[n++]=0x50;  /* r10             */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x58;  /* r11             */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&fn,8); n+=8;
    b[n++]=0xFF; b[n++]=0xD0;
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x28;
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x54; b[n++]=0x24; b[n++]=0x38;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x40;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x48;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x54; b[n++]=0x24; b[n++]=0x50;
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x58;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xEC;
    b[n++]=0x5D;

    memcpy(b+n, orig, sizeof(orig)); n += (int)sizeof(orig);
    rel = (long long)(mod + 0x857CD0) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);
    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("ROOM3/task5: reach trampoline out of rel32 range -- skipped"); return; }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("ROOM3/task5: VirtualProtect failed at RVA 0x857CC9"); return; }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    site[5] = 0x90; site[6] = 0x90;
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));
    log_line("ROOM3/task5: reach crumb installed at RVA 0x857CC9 (%d-byte stub) -- the only "
             "jump into this area targets it, so nothing can branch past it", n);
}

/* exe+0x8A0B10: steal the entry's `mov [rsp+0x18],rbx` (5 bytes, no rip operand, no call).
   The return address is at [rbp+8] once the stub has framed -- and NOTHING else is read
   through rbp, which is the 2026-09-17 trap. */
static void patch_room3_fn_entry(void)
{
    static const unsigned char orig[5] = { 0x48,0x89,0x5C,0x24,0x18 };
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site; unsigned char* stub;
    void* fn = (void*)&room3_log_fnentry;
    unsigned char b[224]; int n = 0; long long rel; DWORD old;

    if (!mod) return;
    site = mod + 0x8A0B10;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("ROOM3/fn: bytes not at expected RVA 0x8A0B10 -- skipped"); return; }
    stub = (unsigned char*)gauge_alloc_near(site, 256);
    if (!stub) { log_line("ROOM3/fn: no trampoline within +/-2GB -- skipped"); return; }

    b[n++]=0x55;                                                      /* push rbp        */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xE5;                            /* mov rbp,rsp     */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xE4; b[n++]=0xF0;               /* and rsp,-16     */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xEC; b[n++]=0x60;               /* sub rsp,0x60    */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x44; b[n++]=0x24; b[n++]=0x28;  /* [rsp+28]=rax    */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;  /* rcx             */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x54; b[n++]=0x24; b[n++]=0x38;  /* rdx             */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x44; b[n++]=0x24; b[n++]=0x40;  /* r8              */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x48;  /* r9              */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x54; b[n++]=0x24; b[n++]=0x50;  /* r10             */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x58;  /* r11             */
    /* self = rcx already; ret = [rbp+8] */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x55; b[n++]=0x08;               /* mov rdx,[rbp+8] */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&fn,8); n+=8;                /* mov rax,&logger */
    b[n++]=0xFF; b[n++]=0xD0;                                         /* call rax        */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x28;  /* restore rax     */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;  /* rcx             */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x54; b[n++]=0x24; b[n++]=0x38;  /* rdx             */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x40;  /* r8              */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x48;  /* r9              */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x54; b[n++]=0x24; b[n++]=0x50;  /* r10             */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x58;  /* r11             */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xEC;                            /* mov rsp,rbp     */
    b[n++]=0x5D;                                                      /* pop rbp         */

    memcpy(b+n, orig, sizeof(orig)); n += (int)sizeof(orig);          /* the stolen store */
    rel = (long long)(mod + 0x8A0B15) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);
    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("ROOM3/fn: trampoline out of rel32 range -- skipped"); return; }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("ROOM3/fn: VirtualProtect failed at RVA 0x8A0B10"); return; }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));
    log_line("ROOM3/fn: installed at RVA 0x8A0B10 (%d-byte stub) -- the ENTRY of the loop "
             "function, so a frozen loop head can be told from a function that stopped "
             "being called at all", n);
}

/* exe+0x8A0CF5: steal `mov rsi,[rdi+0x78]` + `mov rdi,[rdi+0x70]` (8 bytes, no rip operand
   and no call). The second overwrites rdi, so both ends are read from the original rdi in
   the stub, before the pair is re-executed for real. Observation only. */
static void patch_room3_walk_head(void)
{
    static const unsigned char orig[8] = { 0x48,0x8B,0x77,0x78, 0x48,0x8B,0x7F,0x70 };
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site; unsigned char* stub;
    void* fn = (void*)&room3_log_walkhead;
    unsigned char b[224]; int n = 0; long long rel; DWORD old;

    if (!mod) return;
    site = mod + 0x8A0CF5;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("ROOM3/walk: bytes not at expected RVA 0x8A0CF5 -- skipped"); return; }
    stub = (unsigned char*)gauge_alloc_near(site, 256);
    if (!stub) { log_line("ROOM3/walk: no trampoline within +/-2GB -- skipped"); return; }

    b[n++]=0x55;                                                      /* push rbp        */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xE5;                            /* mov rbp,rsp     */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xE4; b[n++]=0xF0;               /* and rsp,-16     */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xEC; b[n++]=0x60;               /* sub rsp,0x60    */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x44; b[n++]=0x24; b[n++]=0x28;  /* [rsp+28]=rax    */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;  /* rcx             */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x54; b[n++]=0x24; b[n++]=0x38;  /* rdx             */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x44; b[n++]=0x24; b[n++]=0x40;  /* r8              */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x48;  /* r9              */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x54; b[n++]=0x24; b[n++]=0x50;  /* r10             */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x58;  /* r11             */
    /* self = rdi, begin = [rdi+0x70], end = [rdi+0x78] -- read before rdi is clobbered */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xF9;                            /* mov rcx,rdi     */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x57; b[n++]=0x70;               /* mov rdx,[rdi+70]*/
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x47; b[n++]=0x78;               /* mov r8,[rdi+78] */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&fn,8); n+=8;                /* mov rax,&logger */
    b[n++]=0xFF; b[n++]=0xD0;                                         /* call rax        */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x28;  /* restore rax     */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;  /* rcx             */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x54; b[n++]=0x24; b[n++]=0x38;  /* rdx             */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x40;  /* r8              */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x48;  /* r9              */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x54; b[n++]=0x24; b[n++]=0x50;  /* r10             */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x58;  /* r11             */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xEC;                            /* mov rsp,rbp     */
    b[n++]=0x5D;                                                      /* pop rbp         */

    memcpy(b+n, orig, sizeof(orig)); n += (int)sizeof(orig);          /* the stolen pair */
    rel = (long long)(mod + 0x8A0CFD) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);
    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("ROOM3/walk: trampoline out of rel32 range -- skipped"); return; }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("ROOM3/walk: VirtualProtect failed at RVA 0x8A0CF5"); return; }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    site[5] = 0x90; site[6] = 0x90; site[7] = 0x90;
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));
    log_line("ROOM3/walk: installed at RVA 0x8A0CF5 (%d-byte stub) -- the driving loop now "
             "reports how many elements it is about to walk, including none", n);
}

/* exe+0x8A0D10: steal `mov rax,[rdi]` + `mov rbx,[rax+0x18]` (7 bytes, no rip operand and
   no call, so they relocate safely), report the element, then re-execute them and return to
   exe+0x8A0D17. Observation only -- no branch is touched. */
static void patch_room3_drive_loop(void)
{
    static const unsigned char orig[7] = { 0x48,0x8B,0x07, 0x48,0x8B,0x58,0x18 };
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site; unsigned char* stub;
    void* fn = (void*)&room3_log_driveloop;
    unsigned char b[224]; int n = 0; long long rel; DWORD old;

    if (!mod) return;
    site = mod + 0x8A0D10;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("ROOM3/word: bytes not at expected RVA 0x8A0D10 -- skipped"); return; }
    stub = (unsigned char*)gauge_alloc_near(site, 256);
    if (!stub) { log_line("ROOM3/word: no trampoline within +/-2GB -- skipped"); return; }

    b[n++]=0x55;                                                      /* push rbp        */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xE5;                            /* mov rbp,rsp     */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xE4; b[n++]=0xF0;               /* and rsp,-16     */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xEC; b[n++]=0x60;               /* sub rsp,0x60    */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x44; b[n++]=0x24; b[n++]=0x28;  /* [rsp+28]=rax    */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;  /* rcx             */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x54; b[n++]=0x24; b[n++]=0x38;  /* rdx             */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x44; b[n++]=0x24; b[n++]=0x40;  /* r8              */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x48;  /* r9              */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x54; b[n++]=0x24; b[n++]=0x50;  /* r10             */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x58;  /* r11             */
    /* the element, computed exactly as the stolen instructions do: rcx = [[rdi]+0x18] */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x0F;                            /* mov rcx,[rdi]   */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x49; b[n++]=0x18;               /* mov rcx,[rcx+18]*/
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&fn,8); n+=8;                /* mov rax,&logger */
    b[n++]=0xFF; b[n++]=0xD0;                                         /* call rax        */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x28;  /* restore rax     */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;  /* rcx             */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x54; b[n++]=0x24; b[n++]=0x38;  /* rdx             */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x40;  /* r8              */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x48;  /* r9              */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x54; b[n++]=0x24; b[n++]=0x50;  /* r10             */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x58;  /* r11             */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xEC;                            /* mov rsp,rbp     */
    b[n++]=0x5D;                                                      /* pop rbp         */

    memcpy(b+n, orig, sizeof(orig)); n += (int)sizeof(orig);          /* the stolen pair */
    rel = (long long)(mod + 0x8A0D17) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);
    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("ROOM3/word: trampoline out of rel32 range -- skipped"); return; }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("ROOM3/word: VirtualProtect failed at RVA 0x8A0D10"); return; }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    site[5] = 0x90; site[6] = 0x90;
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));
    log_line("ROOM3/word: installed at RVA 0x8A0D10 (%d-byte stub) -- every element of the "
             "driving loop now reports its [+0x7C], including the ones the loop skips", n);
}

/* Its own installer: the stub does not just observe, it decides the branch, so it cannot
   go through room3_install_site_log. */
static void patch_room3_drive_gate(void)
{
    static const unsigned char orig[7] = { 0x44,0x38,0xB0,0xF0,0x00,0x00,0x00 }; /* cmp [rax+F0],r14b */
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site; unsigned char* stub;
    void* fn = (void*)&room3_log_drivegate;
    void* flag = (void*)&g_room3_is_spectator;
    unsigned char b[224]; int n = 0, off_je, off_normal; long long rel; DWORD old;

    if (!mod) return;
    site = mod + 0x8A0D29;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("ROOM3/drive: bytes not at expected RVA 0x8A0D29 -- skipped"); return; }
    stub = (unsigned char*)gauge_alloc_near(site, 256);
    if (!stub) { log_line("ROOM3/drive: no trampoline within +/-2GB -- skipped"); return; }

    b[n++]=0x55;                                                      /* push rbp        */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xE5;                            /* mov rbp,rsp     */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xE4; b[n++]=0xF0;               /* and rsp,-16     */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xEC; b[n++]=0x60;               /* sub rsp,0x60    */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x44; b[n++]=0x24; b[n++]=0x28;  /* [rsp+28]=rax    */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;  /* rcx             */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x54; b[n++]=0x24; b[n++]=0x38;  /* rdx             */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x44; b[n++]=0x24; b[n++]=0x40;  /* r8              */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x48;  /* r9              */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x54; b[n++]=0x24; b[n++]=0x50;  /* r10             */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x58;  /* r11             */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xC1;                            /* mov rcx,rax     */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xDA;                            /* mov rdx,rbx     */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&fn,8); n+=8;                /* mov rax,&logger */
    b[n++]=0xFF; b[n++]=0xD0;                                         /* call rax        */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x28;  /* restore rax     */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;  /* rcx             */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x54; b[n++]=0x24; b[n++]=0x38;  /* rdx             */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x40;  /* r8              */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x48;  /* r9              */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x54; b[n++]=0x24; b[n++]=0x50;  /* r10             */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x58;  /* r11             */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xEC;                            /* mov rsp,rbp     */
    b[n++]=0x5D;                                                      /* pop rbp         */

    if (ROOM3_FORCE_TICK) {
        /* am I the spectator? push/pop do not touch flags, and the answer is settled
           before the flags that matter are set below. */
        b[n++]=0x50;                                                  /* push rax        */
        b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&flag,8); n+=8;          /* mov rax,&flag   */
        b[n++]=0x80; b[n++]=0x38; b[n++]=0x00;                        /* cmp byte [rax],0 */
        b[n++]=0x58;                                                  /* pop rax         */
        b[n++]=0x74; off_je = n++;                                    /* je normal       */
        /* the spectator: ZF=1 so the jne below falls through, and NOT ONE register or
           byte of engine state is changed by saying so. */
        b[n++]=0x38; b[n++]=0xC0;                                     /* cmp al,al       */
        rel = (long long)(mod + 0x8A0D30) - (long long)(stub + n + 5);
        b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;
        off_normal = n;
        b[off_je] = (unsigned char)(off_normal - (off_je + 1));
    }

    memcpy(b+n, orig, sizeof(orig)); n += (int)sizeof(orig);          /* the stock test  */
    rel = (long long)(mod + 0x8A0D30) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);
    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("ROOM3/drive: trampoline out of rel32 range -- skipped"); return; }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("ROOM3/drive: VirtualProtect failed at RVA 0x8A0D29"); return; }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    site[5] = 0x90; site[6] = 0x90;
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));
    log_line("ROOM3/drive: installed at RVA 0x8A0D29 (%d-byte stub) -- the byte that gates "
             "the whole object's per-frame life is now logged%s", n,
             ROOM3_FORCE_TICK ? ", and ignored on the spectator" : "");
    patch_room3_drive_loop();      /* the gate one instruction earlier, and the real one */
    patch_room3_walk_head();       /* and the loop head above both gates                  */
    patch_room3_fn_entry();        /* and the entry, 485 bytes above the loop head        */
    patch_room3_task5_entry();     /* and slot 5 above that, with its own reach crumb     */
    patch_room3_task5_reach();
    patch_room3_exits();           /* and which of its twenty exits it leaves by         */
    patch_room3_throttle();        /* and the state test that arms the frame drop        */
    patch_room3_abort();           /* and why the load barrier ends the battle           */
    patch_room3_battlebit();       /* and the flag word that answer named                */
    patch_room3_timeout();         /* and the clock its timeout exit compares            */
    patch_room3_brain_makers();    /* and which input Brains each client creates          */
}

static void patch_room3_event_log(void)
{
    patch_room3_drive_gate();
    static const unsigned char entry[5] = { 0x48,0x89,0x5C,0x24,0x18 };  /* mov [rsp+0x18],rbx */
    static const unsigned char setst[5] = { 0xB8,0x32,0x00,0x00,0x00 };  /* mov eax,0x32       */
    /* rcx = the message id, rdx = the return address, so one line names both */
    static const unsigned char id[7]  = { 0x0F,0xB7,0xCA,                /* movzx ecx,dx       */
                                          0x48,0x8B,0x55,0x08 };         /* mov rdx,[rbp+8]    */
    /* rdx = this FIRST: loading ecx from [rcx+0x3A0] clobbers rcx */
    static const unsigned char st[14] = { 0x48,0x89,0xCA,                /* mov rdx,rcx        */
                                          0x4C,0x8B,0x45,0x08,           /* mov r8,[rbp+8]     */
                                          0x0F,0xB7,0x8A,0xA0,0x03,0x00,0x00 };
    static const unsigned char sw[7]  = { 0x48,0x89,0xF9,                /* mov rcx,rdi        */
                                          0x48,0x8B,0x55,0x08 };         /* mov rdx,[rbp+8]    */
    static const unsigned char wait[6] = { 0x39,0xB7,0x34,0x0C,0x00,0x00 }; /* cmp [rdi+C34],esi */
    static const unsigned char self1[3] = { 0x48,0x89,0xF9 };            /* mov rcx,rdi        */
    /* mov rax,rsp ; mov [rax+0x18],rbx -- the update's first two instructions, 7 bytes,
       re-executed on the original rsp because the stub restores it before they run */
    static const unsigned char upd[7] = { 0x48,0x8B,0xC4, 0x48,0x89,0x58,0x18 };
    /* the scene tick opens with the same two instructions as the update it calls */
    static const unsigned char ret1[4] = { 0x48,0x8B,0x4D,0x08 };       /* mov rcx,[rbp+8] */
    /* rdx = this FIRST, then the state, then rcx = the caller */
    static const unsigned char updarg[15] = { 0x48,0x89,0xCA,               /* mov rdx,rcx     */
                                              0x44,0x0F,0xB7,0x81,0xA0,0x03,0x00,0x00,
                                              0x48,0x8B,0x4D,0x08 };        /* mov rcx,[rbp+8] */
    static const unsigned char tail[7] = { 0x0F,0xB7,0x85,0x08,0x10,0x00,0x00 }; /* movzx eax,[rbp+1008] */
    /* ⚠ [rbp+0x1008] must be read through the function's OWN rbp, which the stub pushed
       and then overwrote: the saved copy is at [rbp]. Reading it off the stub's rbp is
       what made the default tail report writing 0x13F and 0xCD40. */
    static const unsigned char sw2[14] = { 0x4C,0x89,0xFA,                /* mov rdx,r15        */
                                           0x48,0x8B,0x45,0x00,           /* mov rax,[rbp]      */
                                           0x0F,0xB7,0x88,0x08,0x10,0x00,0x00 };
    room3_install_site_log(0x803B10, entry, 5, id,  7, (void*)&room3_log_event,      "evt");
    room3_install_site_log(0x6B3490, entry, 5, st, 14, (void*)&room3_log_state,      "st");
    room3_install_site_log(0x803FF1, setst, 5, sw,  7, (void*)&room3_log_statewrite, "stw");
    /* exe+0x6B3026 `movzx eax, word [rbp+0x1008]` -- [rbp+0x1008] is the home slot of the
       message argument, so eax here IS the value about to become the state. */
    room3_install_site_log(0x6B3026, tail, 7, sw2, 14, (void*)&room3_log_statewrite2, "stw2");
    /* the `cmp` is stolen and re-executed last, so the jne right after it still reads the
       flags this comparison sets */
    room3_install_site_log(0x804D86, wait, 6, self1, 3, (void*)&room3_log_wait, "wait");
    room3_install_site_log(0x804C70, upd, 7, updarg, 15, (void*)&room3_log_update, "up");
    room3_install_site_log(0x6AA0D0, upd, 7, ret1, 4, (void*)&room3_log_tick,  "tick");
    room3_install_site_log(0x802B10, upd, 7, ret1, 4, (void*)&room3_log_reach, "slot11");
}

static void patch_room3_more_crumbs(void)
{
    static const unsigned char slot26[5] = { 0x48,0x89,0x5C,0x24,0x18 };   /* mov [rsp+0x18],rbx */
    /* the instruction AFTER the lea: mov [rbp+0x22A0],rax -- same moment, no rip operand */
    static const unsigned char reg[7]    = { 0x48,0x89,0x85,0xA0,0x22,0x00,0x00 };
    (void)slot26;                 /* the entry is hooked by patch_room3_event_log now */
    patch_room3_event_log();
    room3_crumb_install(0x804BE0, reg, 7, (void*)&g_room3_reg_seen,
                        "the battle set-up callback registration");
    patch_room3_slot26_span();
}

static void patch_room3_barrier_probe(void)
{
    static const unsigned char orig[5] = { 0x48,0x89,0x5C,0x24,0x18 };  /* mov [rsp+0x18],rbx */
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site; unsigned char* stub;
    void* fn = (void*)&room3_log_barrier;
    unsigned char b[160]; int n = 0; long long rel; DWORD old;

    if (!mod) return;
    site = mod + 0x807190;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("ROOM3/barrier: bytes not at expected RVA 0x807190 -- probe skipped"); return; }
    stub = (unsigned char*)gauge_alloc_near(site, 160);
    if (!stub) { log_line("ROOM3/barrier: no trampoline -- skipped"); return; }

    b[n++]=0x51; b[n++]=0x52;                                /* push rcx, rdx         */
    b[n++]=0x41; b[n++]=0x50; b[n++]=0x41; b[n++]=0x51;      /* push r8, r9           */
    b[n++]=0x55;                                             /* push rbp              */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xE5;                   /* mov rbp,rsp           */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xE4; b[n++]=0xF0;      /* and rsp,-16           */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xEC; b[n++]=0x20;      /* sub rsp,0x20          */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&fn,8); n+=8;       /* mov rax,&logger       */
    b[n++]=0xFF; b[n++]=0xD0;                                /* call rax (rcx = this) */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xEC;                   /* mov rsp,rbp           */
    b[n++]=0x5D;                                             /* pop rbp               */
    b[n++]=0x41; b[n++]=0x59; b[n++]=0x41; b[n++]=0x58;      /* pop r9, r8            */
    b[n++]=0x5A; b[n++]=0x59;                                /* pop rdx, rcx          */
    memcpy(b+n, orig, sizeof(orig)); n += (int)sizeof(orig);
    rel = (long long)(mod + 0x807195) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);
    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) { log_line("ROOM3/barrier: out of range"); return; }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("ROOM3/barrier: VirtualProtect failed"); return; }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));
    log_line("ROOM3/barrier: probe installed at RVA 0x807190 (%d-byte stub at %p)", n, (void*)stub);
}

static void patch_room3_entry_probe(void)
{
    static const unsigned char orig[5] = { 0x48,0x89,0x5C,0x24,0x08 };  /* mov [rsp+8],rbx */
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site; unsigned char* stub;
    void* fn = (void*)&room3_log_entry;
    unsigned char b[160]; int n = 0; long long rel; DWORD old;

    if (!mod) return;
    site = mod + 0x6C5070;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("ROOM3/entry: bytes not at expected RVA 0x6C5070 -- probe skipped"); return; }
    stub = (unsigned char*)gauge_alloc_near(site, 160);
    if (!stub) { log_line("ROOM3/entry: no trampoline -- skipped"); return; }

    b[n++]=0x51; b[n++]=0x52;                                /* push rcx, rdx         */
    b[n++]=0x41; b[n++]=0x50; b[n++]=0x41; b[n++]=0x51;      /* push r8, r9           */
    b[n++]=0x55;                                             /* push rbp              */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xE5;                   /* mov rbp,rsp           */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xE4; b[n++]=0xF0;      /* and rsp,-16           */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xEC; b[n++]=0x20;      /* sub rsp,0x20          */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x55; b[n++]=0x28;      /* mov rdx,[rbp+0x28] ret*/
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&fn,8); n+=8;       /* mov rax,&logger       */
    b[n++]=0xFF; b[n++]=0xD0;                                /* call rax (rcx = this) */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xEC;                   /* mov rsp,rbp           */
    b[n++]=0x5D;                                             /* pop rbp               */
    b[n++]=0x41; b[n++]=0x59; b[n++]=0x41; b[n++]=0x58;      /* pop r9, r8            */
    b[n++]=0x5A; b[n++]=0x59;                                /* pop rdx, rcx          */
    memcpy(b+n, orig, sizeof(orig)); n += (int)sizeof(orig);
    rel = (long long)(mod + 0x6C5075) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);
    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) { log_line("ROOM3/entry: out of range"); return; }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("ROOM3/entry: VirtualProtect failed"); return; }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));
    log_line("ROOM3/entry: probe installed at RVA 0x6C5070 (%d-byte stub at %p)", n, (void*)stub);
}

static void patch_room3_battle_gate(void)
{
    static const unsigned char orig[7] = {
        0x48,0x8B,0x86,0x18,0x03,0x00,0x00          /* mov rax,[rsi+0x318] */
    };
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    unsigned char* stub;
    void* flag = (void*)&g_room3_is_spectator;
    void* fn   = (void*)&room3_log_gate;
    unsigned char b[192];
    int n = 0, off_je, off_normal;
    long long rel;
    DWORD old;

    if (!mod) return;
    site = mod + ROOM3_GATE_RVA;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("ROOM3/gate: bytes not at expected RVA 0x%X -- skipped, the spectator "
                 "keeps waiting on the loading screen", ROOM3_GATE_RVA);
        return;
    }
    stub = (unsigned char*)gauge_alloc_near(site, 224);
    if (!stub) { log_line("ROOM3/gate: no trampoline within +/-2GB -- skipped"); return; }

    b[n++]=0x50;                                              /* push rax               */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&flag,8); n+=8;      /* mov rax,&is_spectator  */
    b[n++]=0x80; b[n++]=0x38; b[n++]=0x00;                    /* cmp byte [rax],0       */
    b[n++]=0x58;                                              /* pop rax                */
    b[n++]=0x74; off_je = n++;                                /* je normal              */

    /* spectator: log once, then jump past both tests straight to the call.
       The frame is realigned by hand because this is the middle of a function and the
       logger ends up in snprintf, which is entitled to aligned SSE stores. */
    b[n++]=0x55;                                              /* push rbp               */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xE5;                    /* mov rbp,rsp            */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xE4; b[n++]=0xF0;       /* and rsp,-16            */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xEC; b[n++]=0x60;       /* sub rsp,0x60           */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x44; b[n++]=0x24; b[n++]=0x28;  /* mov [rsp+28],rax */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;  /* mov [rsp+30],rcx */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x54; b[n++]=0x24; b[n++]=0x38;  /* mov [rsp+38],rdx */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x44; b[n++]=0x24; b[n++]=0x40;  /* mov [rsp+40],r8  */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x48;  /* mov [rsp+48],r9  */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x54; b[n++]=0x24; b[n++]=0x50;  /* mov [rsp+50],r10 */
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x58;  /* mov [rsp+58],r11 */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xF1;                    /* mov rcx,rsi            */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&fn,8); n+=8;        /* mov rax,&logger        */
    b[n++]=0xFF; b[n++]=0xD0;                                 /* call rax               */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x28;  /* restore rax     */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;  /* rcx             */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x54; b[n++]=0x24; b[n++]=0x38;  /* rdx             */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x40;  /* r8              */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x48;  /* r9              */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x54; b[n++]=0x24; b[n++]=0x50;  /* r10             */
    b[n++]=0x4C; b[n++]=0x8B; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x58;  /* r11             */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xEC;                    /* mov rsp,rbp            */
    b[n++]=0x5D;                                              /* pop rbp                */
    rel = (long long)(mod + ROOM3_GATE_CALL) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;                    /* jmp the call           */

    off_normal = n;                                           /* normal:                */
    b[off_je] = (unsigned char)(off_normal - (off_je + 1));
    memcpy(b+n, orig, sizeof(orig)); n += (int)sizeof(orig);  /* stolen mov             */
    rel = (long long)(mod + ROOM3_GATE_BACK) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;                    /* jmp the stock test     */

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);

    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("ROOM3/gate: trampoline out of rel32 range -- skipped"); return;
    }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("ROOM3/gate: VirtualProtect failed at RVA 0x%X", ROOM3_GATE_RVA);
        return;
    }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    site[5] = 0x90; site[6] = 0x90;
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));
    log_line("ROOM3/gate: installed at RVA 0x%X (%d-byte stub at %p) -- the spectator now "
             "reaches battle start instead of being turned away by two byte flags",
             ROOM3_GATE_RVA, n, (void*)stub);
}


/* ---- PART 27, the SOnlineAction slot map -------------------------------
 *  WHY A WHOLE-VTABLE PROBE, 2026-09-17 02:40.
 *
 *  The chain into battle start is now known and verified by execution:
 *
 *      ???  ->  exe+0x6C5070  ->  exe+0x6C5390  ->  exe+0x805870
 *                (slot 36)                            (slot 45)
 *
 *  and every level of it runs on BOTH players at the same millisecond and on
 *  the spectator never. Walking up one level per run costs a rig cycle each
 *  time -- four so far. `0x6C5070` turned out to be **slot 36 of
 *  ActionSceneBase**, the shared base of every scene class, and battle start is
 *  slot 45 of the same object: both are entries in `SOnlineAction`'s vtable at
 *  RVA 0x14A3888.
 *
 *  So instead of chasing one caller per run: replace EVERY slot of that vtable
 *  with a thunk that records its first call and jumps to the original. One run
 *  then prints, on each client, the set of SOnlineAction methods that actually
 *  executed -- and the difference between a player's set and the spectator's is
 *  the trigger that never reaches it.
 *
 *  Only SOnlineAction's table is touched, so the other eight scene classes that
 *  share slot 36's implementation are unaffected. Each slot logs once; after
 *  that the thunk is two instructions of overhead on a virtual call.
 *
 *  ⚠ The vtable lives in .rdata and the game may hold copies of a slot's value
 *  taken before we patch, so this is a probe and not a mechanism: it answers a
 *  question and comes straight back out of the build. */
/* ⚠ OFF by default since 2026-09-17, and it must stay that way in any build someone
   plays on. Measured: with the map installed the two PLAYERS' match timer freezes (123,
   every run), while the shipped build on the same rig counts down normally. The fight
   itself still runs -- players move and hit each other -- so this is not a crash, it is
   74 replaced virtual slots quietly costing something the round clock depends on.
   It remains the best tool in this folder for "which methods does this client call",
   but it is a probe: build it with -DROOM3_VTMAP=1 for one run and take it back out. */
#ifndef ROOM3_VTMAP
#define ROOM3_VTMAP 0
#endif
#define ROOM3_VT_RVA      0x14A3888      /* SOnlineAction's vtable        */
#define ROOM3_VT_MAX      96             /* hard cap on slots probed      */
#define ROOM3_THUNK_SIZE  72

static void*  g_room3_vt_orig[ROOM3_VT_MAX];
static volatile LONG g_room3_vt_seen[ROOM3_VT_MAX];
static int    g_room3_vt_count = 0;

static void room3_slot_ran(int slot)
{
    if (slot < 0 || slot >= ROOM3_VT_MAX) return;
    if (InterlockedCompareExchange(&g_room3_vt_seen[slot], 1, 0) != 0) return;
    log_line("ROOM3/vt: SOnlineAction slot %d (exe+0x%X) ran on this client", slot,
             (unsigned)((unsigned char*)g_room3_vt_orig[slot]
                        - (unsigned char*)GetModuleHandleA(NULL)));
}

static void patch_room3_set4e_probe(void)
{
    static const unsigned char orig[7] = {
        0x48,0x8B,0x02,                     /* mov rax,[rdx]        */
        0x48,0x89,0x41,0x4E                 /* mov [rcx+0x4E],rax   */
    };
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site; unsigned char* stub;
    void* fn = (void*)&room3_log_set4e;
    unsigned char b[176]; int n = 0; long long rel; DWORD old;

    if (!mod) return;
    site = mod + 0x8092E0;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("ROOM3/set4e: bytes not at expected RVA 0x8092E0 -- probe skipped"); return; }
    stub = (unsigned char*)gauge_alloc_near(site, 176);
    if (!stub) { log_line("ROOM3/set4e: no trampoline -- skipped"); return; }

    b[n++]=0x51; b[n++]=0x52;                                /* push rcx, rdx         */
    b[n++]=0x41; b[n++]=0x50; b[n++]=0x41; b[n++]=0x51;      /* push r8, r9           */
    b[n++]=0x55;                                             /* push rbp              */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xE5;                   /* mov rbp,rsp           */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xE4; b[n++]=0xF0;      /* and rsp,-16           */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xEC; b[n++]=0x20;      /* sub rsp,0x20          */
    /* the return address sits above the five pushes made after entry */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x4D; b[n++]=0x28;      /* mov rcx,[rbp+0x28]    */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x55; b[n++]=0x18;      /* mov rdx,[rbp+0x18]    */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&fn,8); n+=8;       /* mov rax,&logger       */
    b[n++]=0xFF; b[n++]=0xD0;                                /* call rax              */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xEC;                   /* mov rsp,rbp           */
    b[n++]=0x5D;                                             /* pop rbp               */
    b[n++]=0x41; b[n++]=0x59; b[n++]=0x41; b[n++]=0x58;      /* pop r9, r8            */
    b[n++]=0x5A; b[n++]=0x59;                                /* pop rdx, rcx          */
    memcpy(b+n, orig, sizeof(orig)); n += (int)sizeof(orig); /* the stolen body       */
    b[n++]=0xC3;                                             /* ret                   */

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);
    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) { log_line("ROOM3/set4e: out of range"); return; }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("ROOM3/set4e: VirtualProtect failed"); return; }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    site[5] = 0x90; site[6] = 0x90;
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));
    log_line("ROOM3/set4e: probe installed at RVA 0x8092E0 (%d-byte stub at %p)", n, (void*)stub);
}

/* ---- PART 27, the scene-flow probe -------------------------------------
 *  The loading screen is a SCENE state, and DataChakka's Boot Sequence write-up
 *  §5 already reverse-engineered how scenes move: the flow is a named registry
 *  and every transition goes through ONE dispatcher, exe+0x89E310, called with
 *  the command name in rdx ("JUMP_Title", "JUMP_DirectTrainingMode", ...). 52
 *  of those names exist.
 *
 *  So instead of inferring the spectator's state from battle-object fields,
 *  print the transitions by name on all three clients. At match start the two
 *  players jump somewhere; whatever the spectator does or does not do is then a
 *  line of text rather than an RVA.
 *
 *  This is where last night should have gone after "it is a scene state, not a
 *  battle-object state" -- the chain-walking that followed cost four rig cycles
 *  and ended in the gameplay event pipe. The guide had the answer already:
 *  read DataChakka first. */
#ifndef ROOM3_SCENE_PROBE
#define ROOM3_SCENE_PROBE 1
#endif
#define ROOM3_FLOW_RVA  0x89E310
#define ROOM3_FLOW_BACK 0x89E315

typedef void (*flowcmd_t)(void* self, const char* name);
static volatile LONG g_room3_flow_n = 0;

static void room3_log_flow(const char* name)
{
    if (!name) return;
    /* P39: 400, not 60. The first sixty are spent before the title screen, and the one
       that matters -- what the room's spectate entry issues -- comes minutes later. */
    if (InterlockedIncrement(&g_room3_flow_n) > 400) return;
    __try {
        log_line("ROOM3/scene: flow command \"%s\"", name);
    } __except(EXCEPTION_EXECUTE_HANDLER) {
        log_line("ROOM3/scene: flow command at %p (unreadable)", (void*)name);
    }
}

static void patch_room3_scene_probe(void)
{
    static const unsigned char orig[5] = { 0x48,0x89,0x5C,0x24,0x08 };  /* mov [rsp+8],rbx */
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site; unsigned char* stub;
    void* fn = (void*)&room3_log_flow;
    unsigned char b[176]; int n = 0; long long rel; DWORD old;

    if (!ROOM3_SCENE_PROBE || !mod) return;
    site = mod + ROOM3_FLOW_RVA;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("ROOM3/scene: bytes not at expected RVA 0x%X -- probe skipped", ROOM3_FLOW_RVA);
        return;
    }
    stub = (unsigned char*)gauge_alloc_near(site, 176);
    if (!stub) { log_line("ROOM3/scene: no trampoline -- skipped"); return; }

    b[n++]=0x51; b[n++]=0x52;                                /* push rcx, rdx         */
    b[n++]=0x41; b[n++]=0x50; b[n++]=0x41; b[n++]=0x51;      /* push r8, r9           */
    b[n++]=0x55;                                             /* push rbp              */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xE5;                   /* mov rbp,rsp           */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xE4; b[n++]=0xF0;      /* and rsp,-16           */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xEC; b[n++]=0x20;      /* sub rsp,0x20          */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x4D; b[n++]=0x18;      /* mov rcx,[rbp+0x18] = rdx */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&fn,8); n+=8;       /* mov rax,&logger       */
    b[n++]=0xFF; b[n++]=0xD0;                                /* call rax              */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xEC;                   /* mov rsp,rbp           */
    b[n++]=0x5D;                                             /* pop rbp               */
    b[n++]=0x41; b[n++]=0x59; b[n++]=0x41; b[n++]=0x58;      /* pop r9, r8            */
    b[n++]=0x5A; b[n++]=0x59;                                /* pop rdx, rcx          */
    memcpy(b+n, orig, sizeof(orig)); n += (int)sizeof(orig);
    rel = (long long)(mod + ROOM3_FLOW_BACK) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);
    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) { log_line("ROOM3/scene: out of range"); return; }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("ROOM3/scene: VirtualProtect failed"); return; }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));
    log_line("ROOM3/scene: flow probe installed at RVA 0x%X (%d-byte stub at %p) -- every "
             "scene transition now prints its command name", ROOM3_FLOW_RVA, n, (void*)stub);
}

static void patch_room3_vtable_map(void)
{
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    void** vt;
    unsigned char* cave;
    void* fn = (void*)&room3_slot_ran;
    int i, count = 0;
    DWORD old;

    if (!ROOM3_VTMAP) {
        log_line("ROOM3/vt: slot map DISABLED at build time -- it freezes the players' "
                 "match timer, so it is opt-in (-DROOM3_VTMAP=1) for a single probe run");
        return;
    }
    if (!mod) return;
    vt = (void**)(mod + ROOM3_VT_RVA);

    /* Count the slots: entries stay inside .text until the table ends. */
    for (i = 0; i < ROOM3_VT_MAX; i++) {
        unsigned char* p = (unsigned char*)vt[i];
        if (p < mod + 0x1000 || p > mod + 0x2000000) break;
        count++;
    }
    if (count < 40) {
        log_line("ROOM3/vt: only %d plausible slots at RVA 0x%X -- not patching",
                 count, ROOM3_VT_RVA);
        return;
    }
    g_room3_vt_count = count;

    cave = (unsigned char*)gauge_alloc_near((unsigned char*)vt, count * ROOM3_THUNK_SIZE + 32);
    if (!cave) { log_line("ROOM3/vt: no cave for %d thunks -- skipped", count); return; }

    for (i = 0; i < count; i++) {
        unsigned char* t = cave + i * ROOM3_THUNK_SIZE;
        void* orig = vt[i];
        int n = 0;
        g_room3_vt_orig[i] = orig;

        t[n++]=0x51; t[n++]=0x52;                                /* push rcx, rdx      */
        t[n++]=0x41; t[n++]=0x50; t[n++]=0x41; t[n++]=0x51;      /* push r8, r9        */
        t[n++]=0x55;                                             /* push rbp           */
        t[n++]=0x48; t[n++]=0x89; t[n++]=0xE5;                   /* mov rbp,rsp        */
        t[n++]=0x48; t[n++]=0x83; t[n++]=0xE4; t[n++]=0xF0;      /* and rsp,-16        */
        t[n++]=0x48; t[n++]=0x83; t[n++]=0xEC; t[n++]=0x20;      /* sub rsp,0x20       */
        t[n++]=0xB9; t[n++]=(unsigned char)(i & 0xFF);           /* mov ecx, slot      */
        t[n++]=0x00; t[n++]=0x00; t[n++]=0x00;
        t[n++]=0x48; t[n++]=0xB8; memcpy(t+n,&fn,8); n+=8;       /* mov rax,&logger    */
        t[n++]=0xFF; t[n++]=0xD0;                                /* call rax           */
        t[n++]=0x48; t[n++]=0x89; t[n++]=0xEC;                   /* mov rsp,rbp        */
        t[n++]=0x5D;                                             /* pop rbp            */
        t[n++]=0x41; t[n++]=0x59; t[n++]=0x41; t[n++]=0x58;      /* pop r9, r8         */
        t[n++]=0x5A; t[n++]=0x59;                                /* pop rdx, rcx       */
        t[n++]=0x48; t[n++]=0xB8; memcpy(t+n,&orig,8); n+=8;     /* mov rax,original   */
        t[n++]=0xFF; t[n++]=0xE0;                                /* jmp rax            */
    }
    FlushInstructionCache(GetCurrentProcess(), cave, (size_t)(count * ROOM3_THUNK_SIZE));

    if (!VirtualProtect(vt, (SIZE_T)count * sizeof(void*), PAGE_READWRITE, &old)) {
        log_line("ROOM3/vt: VirtualProtect failed on the vtable -- skipped"); return;
    }
    for (i = 0; i < count; i++) vt[i] = cave + i * ROOM3_THUNK_SIZE;
    VirtualProtect(vt, (SIZE_T)count * sizeof(void*), old, &old);
    log_line("ROOM3/vt: %d SOnlineAction slots instrumented at RVA 0x%X -- every slot "
             "prints once, the first time this client calls it. Slot 36 leads to battle "
             "start, slot 45 IS battle start.", count, ROOM3_VT_RVA);
}

static void patch_room3_seat_clamps(void)
{
    int i, ok = 0;
    for (i = 0; i < ROOM3_NCLAMPS; i++) ok += room3_clamp_one(&g_room3_clamps[i]);
    if (ok == ROOM3_NCLAMPS)
        log_line("ROOM3/clamp: all %d seat reads clamped -- a room member with no seat now "
                 "watches through seat 0 instead of indexing the fighter list with -1. An "
                 "empty fighter list still bails.", ok);
    else
        log_line("ROOM3/clamp: only %d of %d sites installed -- a seatless client can still "
                 "read the fighter list with -1 and die", ok, ROOM3_NCLAMPS);
}

/*  Fault C, 2026-08-23 10:41 (RVA 0x9FF73C) -- the SAME failure as fault A,
 *  one consumer over, which is what makes the shape rather than the site the
 *  thing to fix:
 *
 *      mov  rcx,[rdi+0x10]        ; the GPU buffer object
 *      lea  r9,[rdi+0x18]         ; out: mapped pointer
 *      lea  r8,[rsp+0x40]         ; out: {offset,size}
 *      call [vtable+0x40]         ; MAP -- the same slot fault A calls
 *      mov  rcx,[rdi+0x18]        ; the mapped pointer it just wrote
 *      mov  rax,[rcx]             ; <-- 0xC0000005, rcx = 0
 *
 *  So a second caller of the same map takes NULL and dereferences it without
 *  a check. Guard A only covered the first one.
 *
 *  GUARD C: if the map wrote NULL, jump to 0x9FF755 -- the shared epilogue
 *  (restores rbx, checks the stack cookie, pops and returns). That skips the
 *  two reads AND the matching unmap at +0x48, which is correct: nothing was
 *  mapped.
 *
 *  It also captures the diagnosis the other two guards could not. On the NULL
 *  path it reads the object's vtable slot +0x40 and parks it in g_rg_map_fn,
 *  which the 30 s heartbeat prints as an RVA. That names the map function
 *  itself -- the one place that decides to return NULL -- so the next session
 *  can go at the cause instead of guarding a third consumer.
 */
#define ROOMGUARD_DRAW2_RVA   0x9FF733
#define ROOMGUARD_DRAW2_EXIT  0x9FF755

static void patch_room_draw_guard2(void)
{
    static const unsigned char orig[9] = {
        0x48,0x8B,0x4F,0x18,                    /* mov rcx,[rdi+0x18] */
        0x45,0x33,0xC0,                         /* xor r8d,r8d        */
        0x33,0xD2                               /* xor edx,edx        */
    };
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    unsigned char* stub;
    unsigned char* exitp;
    void* ctr = (void*)&g_rg_draw2_skips;
    void* slot = (void*)&g_rg_map_fn;
    void* hr   = (void*)&g_rg_map_hr;
    unsigned char b[128];
    int n = 0, off_jnz, off_ok;
    long long rel;
    DWORD old;

    if (!mod) return;
    site  = mod + ROOMGUARD_DRAW2_RVA;
    exitp = mod + ROOMGUARD_DRAW2_EXIT;

    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("ROOMGUARD/draw2: bytes not at expected RVA 0x%X (game updated?) -- "
                 "skipped", ROOMGUARD_DRAW2_RVA);
        return;
    }

    stub = (unsigned char*)gauge_alloc_near(site, 160);
    if (!stub) { log_line("ROOMGUARD/draw2: no trampoline within +/-2GB -- skipped"); return; }

    memcpy(b + n, orig, sizeof(orig)); n += (int)sizeof(orig);  /* stolen           */
    b[n++]=0x48; b[n++]=0x85; b[n++]=0xC9;                  /* test rcx,rcx         */
    b[n++]=0x75; off_jnz = n++;                             /* jnz  ok              */
    /* rax still holds what the map returned -- 0x887A0005 (DXGI_ERROR_DEVICE_REMOVED)
       in the 10:41 dump. Park it before anything clobbers it: that one value is the
       difference between "a NULL we can guard" and "the GPU device is gone". */
    b[n++]=0x48; b[n++]=0xB9; memcpy(b+n,&hr,8); n+=8;      /* mov  rcx,&g_rg_map_hr*/
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x01;                  /* mov  [rcx],rax       */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x47; b[n++]=0x10;     /* mov  rax,[rdi+0x10]  */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x00;                  /* mov  rax,[rax]       */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x40; b[n++]=0x40;     /* mov  rax,[rax+0x40]  */
    b[n++]=0x48; b[n++]=0xB9; memcpy(b+n,&slot,8); n+=8;    /* mov  rcx,&g_rg_map_fn*/
    b[n++]=0x48; b[n++]=0x89; b[n++]=0x01;                  /* mov  [rcx],rax       */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b+n,&ctr,8); n+=8;     /* mov  rax,&counter    */
    b[n++]=0xF0; b[n++]=0x48; b[n++]=0xFF; b[n++]=0x00;     /* lock inc qword [rax] */
    rel = (long long)exitp - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;                  /* jmp  epilogue        */
    off_ok = n;                                             /* ok:                  */
    b[off_jnz] = (unsigned char)(off_ok - (off_jnz + 1));
    rel = (long long)(site + 9) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b+n,&rel,4); n+=4;                  /* jmp  back            */

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);

    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("ROOMGUARD/draw2: trampoline out of rel32 range -- skipped"); return;
    }
    if (!VirtualProtect(site, 9, PAGE_EXECUTE_READWRITE, &old)) {
        log_line("ROOMGUARD/draw2: VirtualProtect failed at RVA 0x%X", ROOMGUARD_DRAW2_RVA);
        return;
    }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    site[5] = 0x90; site[6] = 0x90; site[7] = 0x90; site[8] = 0x90;
    VirtualProtect(site, 9, old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, 9);
    log_line("ROOMGUARD/draw2: installed at RVA 0x%X -- a second consumer of the same "
             "NULL map now returns through the epilogue at 0x%X, and records the map "
             "function it called so we can fix the cause",
             ROOMGUARD_DRAW2_RVA, ROOMGUARD_DRAW2_EXIT);
}

/* ---- the rematch wait is 120 seconds, and that is the "freeze" -----------
 *  Reported as a crash, then as a freeze, and it is neither: pick Play again
 *  while the opponent picks Return to room and YOUR client sits there for two
 *  minutes before dropping back into the room. Theirs returns immediately.
 *
 *  `SOnlineAction::vfunc27`, scene state 0x458 -- the rematch handshake:
 *
 *      if ((peer_flags & 0x100) == 0) {          // slot 8 not announced
 *          [scene+0xC8] += dt;                   // accumulate
 *          comiss xmm0, [rip -> 120.0f]          // 0x8054CA
 *          jbe  keep waiting;
 *          ... SetState(0x45a)                   // give up -> back to the room
 *      } else {
 *          clear bit 8 everywhere;
 *          SetState(0x459)                       // both said yes -> rematch
 *      }
 *
 *  So the engine's own answer to a split choice is already "both end up in the
 *  room" -- it just takes 120 s to get there, because that timeout was written
 *  for a mode where the menu never disagrees. Note this also rules out the
 *  obvious-looking fix of announcing slot 8 on the way out: bit 8 means "I want
 *  the rematch", so the waiting client would restart the fight alone.
 *
 *  The wait only has to cover how much LATER than you the opponent presses.
 *  Tuned down 120 -> 15 -> 5 -> 1 on request. At 1 s the fallback is effectively
 *  instant, and two things follow that are worth writing down rather than
 *  discovering twice:
 *
 *    - a mutual rematch now needs both players to press within a second of each
 *      other, otherwise both fall back to the room;
 *    - the slower player can enter 0x458 and find the faster player's slot-8 bit
 *      ALREADY set after that player has timed out and left, which sends them to
 *      0x459 -- restarting the fight against someone who is no longer there.
 *      Nothing was found that clears an announced bit on the timeout path, so
 *      this race is real and gets likelier the shorter the wait.
 *
 *  The image carries 1, 2, 3, 4, 5, 6, 8, 10 and 15 as literals, so re-tuning is
 *  always the same four bytes.
 *
 *  120.0f is a SHARED literal -- ~40 instructions across the exe divide by it
 *  (frame/second conversions) -- so it must not be edited in place. Instead the
 *  single `comiss` at RVA 0x8054CA is repointed at the 15.0f literal the image
 *  already carries at RVA 0x1213920. Four bytes, one instruction, nothing else
 *  in the process sees a different number.
 */
#define REMATCHWAIT_RVA      0x8054CA     /* comiss xmm0, dword [rip+disp32]  */
#define REMATCHWAIT_NEWRVA   0x11CFEC8    /* the image's own 1.0f             */
#define REMATCHWAIT_OLDVAL   120.0f
#define REMATCHWAIT_NEWVAL   1.0f

static void patch_room_rematch_wait(void)
{
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    unsigned char* oldp;
    unsigned char* newp;
    int disp;
    DWORD old;

    if (!mod) return;
    site = mod + REMATCHWAIT_RVA;

    if (site[0] != 0x0F || site[1] != 0x2F || site[2] != 0x05) {
        log_line("REMATCHWAIT: no `comiss xmm0,[rip+d]` at RVA 0x%X (game updated?) -- "
                 "skipped, a split choice still stalls for %g s",
                 REMATCHWAIT_RVA, (double)REMATCHWAIT_OLDVAL);
        return;
    }
    memcpy(&disp, site + 3, 4);
    oldp = site + 7 + disp;
    newp = mod + REMATCHWAIT_NEWRVA;
    if (*(const float*)oldp != REMATCHWAIT_OLDVAL) {
        log_line("REMATCHWAIT: the operand at RVA 0x%X reads %g, expected %g -- skipped",
                 REMATCHWAIT_RVA, (double)*(const float*)oldp, (double)REMATCHWAIT_OLDVAL);
        return;
    }
    if (*(const float*)newp != REMATCHWAIT_NEWVAL) {
        log_line("REMATCHWAIT: RVA 0x%X does not hold %g -- skipped",
                 REMATCHWAIT_NEWRVA, (double)REMATCHWAIT_NEWVAL);
        return;
    }
    disp = (int)(long long)(newp - (site + 7));
    if (!VirtualProtect(site + 3, 4, PAGE_EXECUTE_READWRITE, &old)) {
        log_line("REMATCHWAIT: VirtualProtect failed at RVA 0x%X", REMATCHWAIT_RVA);
        return;
    }
    memcpy(site + 3, &disp, 4);
    VirtualProtect(site + 3, 4, old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, 7);
    log_line("REMATCHWAIT: RVA 0x%X repointed %g -> %g s -- when one side picks Play again "
             "and the other leaves, the waiting client now falls back to the room in %g s "
             "instead of %g", REMATCHWAIT_RVA, (double)REMATCHWAIT_OLDVAL,
             (double)REMATCHWAIT_NEWVAL, (double)REMATCHWAIT_NEWVAL, (double)REMATCHWAIT_OLDVAL);
}

/* ================= PART 12: "Meri's mode" ============================
 *  WHAT IT DOES
 *  ------------
 *  While a player has not broken a single Konpaku yet, their Kikon can
 *  destroy at most 4 Konpaku, never 5. Once they have killed once, the
 *  sublimation Kikon does its full 5 again.
 *
 *  WHY (Meri's "lose to win" case)
 *  -------------------------------
 *  Everyone has 9 Konpaku, a Kikon in Awakening destroys 4 and the
 *  sublimation Kikon destroys 5, so a match is exactly two kills. Whoever
 *  kills FIRST without sublimation takes 4 and leaves 5 -- so their second
 *  kill now REQUIRES sublimation. The player who was behind can then reach
 *  sublimation before their own first kill, take 5, leave 4, and finish with
 *  any Kikon. Being better first is punished. Capping the first kill at 4 for
 *  both sides removes the 5-4 split: kill one is always 4, kill two is always
 *  5, whoever gets there first.
 *
 *  HOW
 *  ---
 *  Hook RVA 0x468049 -- `movss [rsp+0x58], xmm9`, the first instruction of
 *  the stock-loss path in the damage applier (VA 0x140467B60) that stores the
 *  incoming soul damage into the local the konpaku subtraction later reads.
 *  Hooking there is deliberate: it is the ONE point where both values we need
 *  are still arguments (EXE_WALL_PATCHING rule "patch where the value is an
 *  ARGUMENT" -- four Zangetsu builds were lost to register provenance).
 *
 *      rsi  = the VICTIM fighter   -- `mov rsi,rcx` at 0x140467BBF, the only
 *                                     write to rsi in the whole prologue
 *      xmm9 = the SOUL DAMAGE      -- `movaps xmm9,xmm3` at 0x140467BB5, the
 *                                     only write to xmm9
 *
 *  Both are non-volatile in the Win64 ABI, so no callee in between can have
 *  changed them. Everything downstream reads the value through [rsp+0x58] and
 *  through xmm9 itself, so lowering xmm9 here is exactly equivalent to the
 *  attack having been authored with a smaller `soul_damage`.
 *
 *  soul_damage in the .tadjpkg is one LESS than the Konpaku the move destroys
 *  (base Kikon 2 -> 3 Konpaku, Awakening 3 -> 4, sublimation 4 -> 5), so the
 *  cap is `soul_damage <= 3`.
 *
 *  "has not killed yet" is read off the victim, not off a counter of our own:
 *  konpaku `[victim+0x10C0] >= [victim+0xC74]` (current >= max) means nobody
 *  has ever taken a Konpaku off them, and only the attacker can. That matters
 *  for two reasons: it is pure game state, so it ROLLS BACK correctly online
 *  (a counter living in the DLL would desync), and it survives transformation
 *  -- 0x140471160 rewrites max at +0xC74 and adds the same delta to +0x10C0,
 *  so "current == max" is preserved when a Reawakening moves 8 -> 10.
 *  Positive floats compare correctly as unsigned ints, so the test is integer.
 *
 *  ! It assumes nothing else drains a fighter's own konpaku. The sublimation
 *  Kikon self-cost did (2 konpaku, VA 0x1404EB980) -- patch_yamamoto_selfcost
 *  in this same DLL sets that to 0, so it cannot fire. If SELFCOST is ever
 *  turned back on, this test needs a different "has killed" signal.
 *
 *  SCOPE: the ids in g_meri_ids. All of them ship a sublimation Kikon at
 *  soul_damage 4, so the cap takes each of them from 5 Konpaku to 4 -- there is
 *  no outlier among them needing a different rule. Characters whose sublimation
 *  Kikon is ABOVE the norm (pl027 Kenpachi and pl052 Yhwach at 5, pl019 at 6,
 *  pl050 at 5 on one variant) would be cut harder than the rest by this flat
 *  cap, so adding them is a balance decision, not a list edit.
 * ==================================================================== */
#define MERI_HOOK_RVA    0x468049u   /* movss [rsp+0x58], xmm9            */
#define MERI_CAP_BITS    0x40400000  /* 3.0f == 4 Konpaku destroyed       */
#define MERI_OFF_KONPAKU 0x10C0      /* fighter: current konpaku (float)  */
#define MERI_OFF_KONPMAX 0x0C74      /* fighter: max konpaku (float)      */
#define MERI_OFF_RIVAL   0x05F0      /* fighter: rival object (weak-ref)  */
#define MERI_OFF_RIVALCB 0x0610      /* fighter: rival control block      */
#define MERI_OFF_CHARAID 0x0C00      /* fighter: character id             */

/* Telemetry, kept INSIDE the trampoline page so the stub reaches it with a
   rip-relative disp32 wherever the DLL landed. EVERY konpaku-carrying hit is
   recorded, not only the ones we cap: "it fired and the screen did not move"
   and "it never fired" are different bugs and the log has to separate them. */
#define MERI_SEQ         0x180       /* qword: konpaku-carrying hits seen  */
#define MERI_CAPPED      0x188       /* qword: hits actually capped        */
#define MERI_WHO         0x190       /* dword: attacker character id (-1)  */
#define MERI_DMG_IN      0x194       /* float bits: soul damage as passed  */
#define MERI_DMG_OUT     0x198       /* float bits: soul damage as we left */
#define MERI_KONPAKU     0x19C       /* float bits: victim konpaku before  */
#define MERI_KONPMAX     0x1A0       /* float bits: victim konpaku max     */
/* This mode changes what a Kikon does, so a client running it simulates a
   different fight from a stock patched one and the two desync if they meet.
   PART 2's issuer tag is the pool separator; keep this distinct from
   REAWAKEN_POOL_TAG so the two modes do not share a pool either. */
#ifndef MERI_POOL_TAG
#define MERI_POOL_TAG    4002
#endif
#define MERI_DATA_LO     MERI_SEQ    /* the code must stay below this      */

/* Who the rule applies to. Add or remove ids here -- nothing else changes.
   pl034 is Halibel's second slot and is listed with pl035 so "Halibel" means
   Halibel whichever slot a mode puts on the field. */
static const int g_meri_ids[] = {
     1,   /* pl001  Ichigo Kurosaki (Bankai)  soul_num 8, rev_soul_num 10 */
     3,   /* pl003  Uryu Ishida               */
     4,   /* pl004  Yasutora Sado (Chad)      */
     6,   /* pl006  Kisuke Urahara            */
     7,   /* pl007  Yoruichi Shihoin          */
    10,   /* pl010  Rukia Kuchiki             */
    12,   /* pl012  Rangiku Matsumoto         */
    16,   /* pl016  Yamamoto -- 6 Konpaku, the one outlier here (see below) */
    18,   /* pl018  Gin Ichimaru              */
    20,   /* pl020  Sosuke Aizen              soul_num 8, rev_soul_num 10 */
    21,   /* pl021  Sosuke Aizen, 2nd slot    */
    22,   /* pl022  Byakuya Kuchiki           */
    24,   /* pl024  Shunsui Kyoraku           */
    25,   /* pl025  Kaname Tosen              */
    26,   /* pl026  Toshiro Hitsugaya         */
    29,   /* pl029  Mayuri Kurotsuchi         */
    31,   /* pl031  Kaien Shiba               */
    32,   /* pl032  Shinji Hirako             */
    34,   /* pl034  Tier Halibel              */
    35,   /* pl035  Tier Halibel              */
    36,   /* pl036  Ulquiorra Shifar          */
    38,   /* pl038  Grimmjow Jeagerjaques     */
    42,   /* pl042  Nelliel Tu Odelschwanck   */
    44,   /* pl044  Sosuke Aizen, 3rd slot    */
    51,   /* pl051  Ichigo Kurosaki (TYBW)    */
    52,   /* pl052  Yhwach                    */
};
#define MERI_NIDS ((int)(sizeof(g_meri_ids) / sizeof(g_meri_ids[0])))

/* The scope test is a 64-bit BITMASK, not a chain of compares. A chain costs 7
   bytes per id and breaks in three SILENT ways once the roster is large: the
   `je rel8` back to `inscope` runs past its 127-byte reach, the ji[] patch
   array overflows the stack frame, and PART 14's stub grows past the telemetry
   it keeps at +0x180. One `bt` is 31 bytes whatever the roster is, and every
   character id in this game is below 64, so a single qword covers all of it. */
static unsigned long long meri_mask(int* dropped)
{
    unsigned long long m = 0;
    int i, d = 0;
    for (i = 0; i < MERI_NIDS; i++) {
        if (g_meri_ids[i] < 0 || g_meri_ids[i] > 63) { d++; continue; }
        m |= 1ULL << g_meri_ids[i];
    }
    if (dropped) *dropped = d;
    return m;
}

static unsigned char* g_meri_cave = NULL;

static DWORD WINAPI meri_watch(LPVOID u)
{
    long long seq = 0;
    int lines = 0;
    (void)u;
    while (g_meri_cave && lines < 300) {
        long long s2 = *(volatile long long*)(g_meri_cave + MERI_SEQ);
        if (s2 != seq) {
            long long cap = *(volatile long long*)(g_meri_cave + MERI_CAPPED);
            int   who = *(volatile int*)  (g_meri_cave + MERI_WHO);
            float din = *(volatile float*)(g_meri_cave + MERI_DMG_IN);
            float dou = *(volatile float*)(g_meri_cave + MERI_DMG_OUT);
            float kon = *(volatile float*)(g_meri_cave + MERI_KONPAKU);
            float mx  = *(volatile float*)(g_meri_cave + MERI_KONPMAX);
            seq = s2; lines++;
            log_line("MERI: hit #%lld -- attacker pl%03d, victim konpaku %.1f/%.1f (%s), "
                     "soul damage %.1f -> %.1f, so %.0f Konpaku should be destroyed "
                     "(%lld capped so far)",
                     seq, who, (double)kon, (double)mx,
                     kon >= mx ? "UNTOUCHED, attacker has no kill yet" : "already lost konpaku",
                     (double)din, (double)dou, (double)dou + 1.0, cap);
        }
        Sleep(500);
    }
    return 0;
}

static void patch_meri_first_kill(void)
{
    static const unsigned char orig[7] = {0xF3,0x44,0x0F,0x11,0x4C,0x24,0x58};
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    unsigned char* stub;
    unsigned char  b[512];
    int  n = 0, i;
    int  jx[16], nx = 0;         /* rel32 jumps to the shared exit          */
    int  jr[4],  nr = 0;         /* rel8 jumps to "no rival"                */
    int  j_have;
    int  dropped = 0;
    unsigned long long mask = meri_mask(&dropped);
    long long rel;
    DWORD old;

    if (!mod) return;
    site = mod + MERI_HOOK_RVA;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("MERI: no `movss [rsp+0x58],xmm9` at RVA 0x%X (game updated?) -- skipped",
                 MERI_HOOK_RVA);
        return;
    }
    stub = (unsigned char*)gauge_alloc_near(site, 0x400);
    if (!stub) { log_line("MERI: no trampoline within +/-2GB -- skipped"); return; }
    memset(stub, 0, 0x400);

#define P32(v)    do { int _v = (int)(v); memcpy(b + n, &_v, 4); n += 4; } while (0)
#define P64(v)    do { unsigned long long _v = (unsigned long long)(v);                        memcpy(b + n, &_v, 8); n += 8; } while (0)
#define RIP32(o)  do { int _v = (int)((o) - (n + 4)); memcpy(b + n, &_v, 4); n += 4; } while (0)
#define JEXIT(cc) do { b[n++]=0x0F; b[n++]=(unsigned char)(cc); jx[nx++]=n; n += 4; } while (0)

    b[n++]=0x50;                                                  /* push rax             */
    b[n++]=0x51;                                                  /* push rcx             */
    b[n++]=0x52;                                                  /* push rdx             */

    /* only konpaku-carrying hits are interesting at all                    */
    b[n++]=0x66; b[n++]=0x44; b[n++]=0x0F; b[n++]=0x7E; b[n++]=0xC8;  /* movd eax,xmm9    */
    b[n++]=0x85; b[n++]=0xC0;                                     /* test eax,eax         */
    JEXIT(0x84);                                                  /* je   exit            */

    /* ---- record, capped or not ---------------------------------------- */
    b[n++]=0x89; b[n++]=0x05; RIP32(MERI_DMG_IN);                 /* mov [rip+in],eax     */
    b[n++]=0x89; b[n++]=0x05; RIP32(MERI_DMG_OUT);                /* mov [rip+out],eax    */
    b[n++]=0x8B; b[n++]=0x86; P32(MERI_OFF_KONPAKU);              /* mov eax,[rsi+konp]   */
    b[n++]=0x89; b[n++]=0x05; RIP32(MERI_KONPAKU);
    b[n++]=0x8B; b[n++]=0x86; P32(MERI_OFF_KONPMAX);              /* mov eax,[rsi+max]    */
    b[n++]=0x89; b[n++]=0x05; RIP32(MERI_KONPMAX);

    /* attacker = victim's rival, through the engine's own weak-ref guard   */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x86; P32(MERI_OFF_RIVALCB); /* mov rax,[rsi+cb]     */
    b[n++]=0x48; b[n++]=0x85; b[n++]=0xC0;                        /* test rax,rax         */
    b[n++]=0x74; jr[nr++]=n++;                                    /* je  norival          */
    b[n++]=0x83; b[n++]=0x78; b[n++]=0x08; b[n++]=0x00;           /* cmp dword[rax+8],0   */
    b[n++]=0x74; jr[nr++]=n++;                                    /* je  norival          */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x86; P32(MERI_OFF_RIVAL);   /* mov rax,[rsi+rival]  */
    b[n++]=0x48; b[n++]=0x85; b[n++]=0xC0;                        /* test rax,rax         */
    b[n++]=0x74; jr[nr++]=n++;                                    /* je  norival          */
    b[n++]=0x8B; b[n++]=0x80; P32(MERI_OFF_CHARAID);              /* mov eax,[rax+0xC00]  */
    b[n++]=0xEB; j_have = n++;                                    /* jmp have             */
    for (i = 0; i < nr; i++) b[jr[i]] = (unsigned char)(n - (jr[i] + 1));   /* norival:   */
    b[n++]=0xB8; P32(-1);                                         /* mov eax,-1           */
    b[j_have] = (unsigned char)(n - (j_have + 1));                /* have:                */
    b[n++]=0x89; b[n++]=0x05; RIP32(MERI_WHO);                    /* mov [rip+who],eax    */
    b[n++]=0xF0; b[n++]=0x48; b[n++]=0xFF; b[n++]=0x05; RIP32(MERI_SEQ);  /* lock inc seq  */

    /* ---- the rule ------------------------------------------------------ */
    b[n++]=0x83; b[n++]=0xF8; b[n++]=0x3F;                        /* cmp eax,63           */
    JEXIT(0x87);                                                  /* ja   exit (also -1)  */
    b[n++]=0x89; b[n++]=0xC1;                                     /* mov ecx,eax          */
    b[n++]=0x48; b[n++]=0xBA; P64(mask);                          /* movabs rdx,mask      */
    b[n++]=0x48; b[n++]=0x0F; b[n++]=0xA3; b[n++]=0xCA;           /* bt   rdx,rcx         */
    JEXIT(0x83);                                                  /* jnc  exit            */
    b[n++]=0x8B; b[n++]=0x86; P32(MERI_OFF_KONPAKU);              /* mov eax,[rsi+konp]   */
    b[n++]=0x3B; b[n++]=0x86; P32(MERI_OFF_KONPMAX);              /* cmp eax,[rsi+max]    */
    JEXIT(0x82);                                                  /* jb   exit (has killed) */
    b[n++]=0x66; b[n++]=0x44; b[n++]=0x0F; b[n++]=0x7E; b[n++]=0xC8;  /* movd eax,xmm9    */
    b[n++]=0x3D; P32(MERI_CAP_BITS);                              /* cmp eax,3.0f         */
    JEXIT(0x86);                                                  /* jbe  exit            */
    b[n++]=0xB8; P32(MERI_CAP_BITS);                              /* mov eax,3.0f         */
    b[n++]=0x66; b[n++]=0x44; b[n++]=0x0F; b[n++]=0x6E; b[n++]=0xC8;  /* movd xmm9,eax    */
    b[n++]=0x89; b[n++]=0x05; RIP32(MERI_DMG_OUT);                /* mov [rip+out],eax    */
    b[n++]=0xF0; b[n++]=0x48; b[n++]=0xFF; b[n++]=0x05; RIP32(MERI_CAPPED);

    for (i = 0; i < nx; i++) {                                    /* exit:                */
        int d = n - (jx[i] + 4);
        memcpy(b + jx[i], &d, 4);
    }
    b[n++]=0x5A;                                                  /* pop rdx              */
    b[n++]=0x59;                                                  /* pop rcx              */
    b[n++]=0x58;                                                  /* pop rax  (rsp back)  */
    memcpy(b + n, orig, sizeof(orig)); n += (int)sizeof(orig);    /* stolen instruction   */
    rel = (long long)(site + sizeof(orig)) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b + n, &rel, 4); n += 4;                  /* jmp back             */

#undef P32
#undef P64
#undef RIP32
#undef JEXIT

    if (n > MERI_DATA_LO) {
        log_line("MERI: stub is %d bytes, would overwrite its telemetry -- skipped", n);
        return;
    }
    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);

    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("MERI: trampoline out of rel32 range -- skipped"); return;
    }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("MERI: VirtualProtect failed at RVA 0x%X", MERI_HOOK_RVA); return;
    }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    for (i = 5; i < (int)sizeof(orig); i++) site[i] = 0x90;
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));

    g_meri_cave = stub;
    *(int*)(stub + MERI_WHO) = -1;
    CreateThread(NULL, 0, meri_watch, NULL, 0, NULL);
    {
        char roster[320]; int off = 0;
        if (dropped) log_line("MERI: %d roster id(s) are >= 64, out of the bitmask's reach -- "
                              "they are NOT in scope", dropped);
        for (i = 0; i < MERI_NIDS && off < (int)sizeof(roster) - 8; i++)
            off += snprintf(roster + off, sizeof(roster) - off, "%spl%03d",
                            i ? ", " : "", g_meri_ids[i]);
        log_line("MERI: Meri's mode ON -- %d characters (%s) cannot destroy more than 4 "
                 "Konpaku before their first kill (RVA 0x%X hooked, %d-byte stub at %p, "
                 "scope mask %016llX). Every konpaku-carrying hit is logged from here on.",
                 MERI_NIDS, roster, MERI_HOOK_RVA, n, (void*)stub,
                 (unsigned long long)mask);
    }

    if (MERI_POOL_TAG) {
        int before = g_issuer;
        g_issuer += MERI_POOL_TAG;
        log_line("MERI: matchmaking issuer %d -> %d -- this mode simulates a different "
                 "fight from a stock patched client, so it gets its own pool. Every player "
                 "must run this same DLL.", before, g_issuer);
    } else {
        log_line("MERI: pool tag disabled -- this build shares the normal matchmaking "
                 "pool, which desyncs against anyone not running it");
    }
}

/* ================= PART 14: "Meri's mode", the DISPLAY half ==========
 *  WHY THIS EXISTS
 *  ---------------
 *  PART 12 caps the konpaku a Kikon actually destroys, and that works. The
 *  HUD still drew 5. The preview is not computed from the value PART 12
 *  lowers: the applier (OPlayableBase vtable slot 81, VA 0x140467B60 -- there
 *  is no rel32 call to it anywhere, it is only ever reached through slot 81)
 *  receives the soul damage as an ARGUMENT that was resolved much earlier.
 *  The HUD reads that earlier, resolved number, so it never saw our cap and
 *  the bar promised 5 while the hit took 4.
 *
 *  WHERE THE NUMBER COMES FROM
 *  ---------------------------
 *  VA 0x14014ABD0 walks every hit record of an action (`add rdi,0xA0` per
 *  record) and resolves each one's soul damage BY NAME out of the action data,
 *  through the property getter at 0x140936380:
 *
 *      soul_damage          -> the base value          (0x14142C8E0)
 *      charge_soul_damage   -> added for a charged use (0x14142C8F0)
 *      add_bomb_soul_damage -> the alternative total   (0x14142C940)
 *      enhance_soul_damage  -> added per enhance bit, tested against
 *                              [fighter+0x1098] bits 1/2/4
 *
 *  It keeps the RUNNING MAXIMUM over the records, which is the number the move
 *  is advertised by -- "Destroys 5 Konpaku" is this maximum plus one, exactly
 *  the +1 that PART 12 already documents for `soul_damage`.
 *
 *      0x14014B40A  comiss xmm0,xmm8        ; candidate > best so far ?
 *      0x14014B40E  jbe  0x14014B41E
 *      0x14014B410  movaps xmm8,xmm0        ; <- 10 bytes stolen from here
 *      0x14014B414  movss [rsp+0x38],xmm0
 *
 *  Capping xmm0 at 0x14014B410 is therefore the same edit PART 12 makes, one
 *  stage earlier: the maximum that gets recorded is 3.0 instead of 4.0, and
 *  every consumer of the resolved value -- the HUD included -- sees 4 Konpaku.
 *  Nothing branches into the 10 stolen bytes (checked over the whole function;
 *  the only jump nearby, the `jbe` above, lands past them at 0x14014B41E).
 *
 *  THE FIGHTER, AND WHY THE RULE READS THE SAME WAY AS PART 12
 *  ----------------------------------------------------------
 *  `rbp` is this function's frame pointer (`lea rbp,[rax-0x938]` in the
 *  prologue, never written again) and `[rbp+0x940]` is an object whose `+0x20`
 *  is the fighter -- the function's own code proves it, reading `+0x1098` off
 *  it at 0x14014B38F and `+0x1A44` at 0x14014B7CB, both fighter fields. That
 *  fighter is the ATTACKER here (it is resolving its own moveset), the mirror
 *  image of PART 12 where rsi is the victim, so the rival walk runs the other
 *  way: attacker -> [+0x610] guard -> [+0x5F0] rival = the victim whose
 *  konpaku answers "has this player killed yet".
 *
 *  ! Unlike PART 12 this does NOT fire per hit -- it fires when an action is
 *  resolved (10 call sites, among them CharaStatus init 0x140462E50 and the
 *  transform routine 0x140471160, so entering sublimation re-resolves). The
 *  open question is whether it re-resolves again after the first kill, which
 *  is what the telemetry below is for: if it does not, the display would stick
 *  at 4 after a kill and this part needs a different refresh trigger. Read the
 *  MERIUI lines in patch_ranked.log before trusting it.
 * ==================================================================== */
#define MERIUI_HOOK_RVA   0x14B410u  /* movaps xmm8,xmm0 + movss [rsp+0x38] */
#define MERIUI_FRAME_OBJ  0x940      /* [rbp+0x940] -> object               */
#define MERIUI_OBJ_FIGHT  0x20       /* object+0x20 -> fighter              */

#define MERIUI_SEQ        0x180      /* qword: resolutions seen             */
#define MERIUI_CAPPED     0x188      /* qword: resolutions actually capped  */
#define MERIUI_WHO        0x190      /* dword: attacker character id (-1)   */
#define MERIUI_VAL_IN     0x194      /* float bits: resolved max, as found  */
#define MERIUI_VAL_OUT    0x198      /* float bits: resolved max, as left   */
#define MERIUI_KONPAKU    0x19C      /* float bits: victim konpaku          */
#define MERIUI_KONPMAX    0x1A0      /* float bits: victim konpaku max      */
#define MERIUI_DATA_LO    MERIUI_SEQ

static unsigned char* g_meriui_cave = NULL;

static DWORD WINAPI meriui_watch(LPVOID u)
{
    long long seq = 0;
    int lines = 0;
    (void)u;
    while (g_meriui_cave && lines < 300) {
        long long s2 = *(volatile long long*)(g_meriui_cave + MERIUI_SEQ);
        if (s2 != seq) {
            long long cap = *(volatile long long*)(g_meriui_cave + MERIUI_CAPPED);
            int   who = *(volatile int*)  (g_meriui_cave + MERIUI_WHO);
            float vin = *(volatile float*)(g_meriui_cave + MERIUI_VAL_IN);
            float vou = *(volatile float*)(g_meriui_cave + MERIUI_VAL_OUT);
            float kon = *(volatile float*)(g_meriui_cave + MERIUI_KONPAKU);
            float mx  = *(volatile float*)(g_meriui_cave + MERIUI_KONPMAX);
            seq = s2; lines++;
            log_line("MERIUI: resolve #%lld -- attacker pl%03d, victim konpaku %.1f/%.1f (%s), "
                     "max soul damage %.1f -> %.1f, so the HUD should promise %.0f Konpaku "
                     "(%lld capped so far)",
                     seq, who, (double)kon, (double)mx,
                     kon >= mx ? "UNTOUCHED, attacker has no kill yet" : "already lost konpaku",
                     (double)vin, (double)vou, (double)vou + 1.0, cap);
        }
        Sleep(500);
    }
    return 0;
}

static void patch_meri_display(void)
{
    static const unsigned char orig[10] = {0x44,0x0F,0x28,0xC0,
                                           0xF3,0x0F,0x11,0x44,0x24,0x38};
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    unsigned char* stub;
    unsigned char  b[512];
    int  n = 0, i;
    int  jx[16], nx = 0;         /* rel32 jumps to the shared exit          */
    long long rel;
    DWORD old;
    int  dropped = 0;
    unsigned long long mask = meri_mask(&dropped);

    if (!mod) return;
    site = mod + MERIUI_HOOK_RVA;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("MERIUI: no `movaps xmm8,xmm0 / movss [rsp+0x38],xmm0` at RVA 0x%X "
                 "(game updated?) -- skipped", MERIUI_HOOK_RVA);
        return;
    }
    stub = (unsigned char*)gauge_alloc_near(site, 0x400);
    if (!stub) { log_line("MERIUI: no trampoline within +/-2GB -- skipped"); return; }
    memset(stub, 0, 0x400);

#define P32(v)    do { int _v = (int)(v); memcpy(b + n, &_v, 4); n += 4; } while (0)
#define RIP32(o)  do { int _v = (int)((o) - (n + 4)); memcpy(b + n, &_v, 4); n += 4; } while (0)
#define P64(v)    do { unsigned long long _v = (unsigned long long)(v);                        memcpy(b + n, &_v, 8); n += 8; } while (0)
#define JEXIT(cc) do { b[n++]=0x0F; b[n++]=(unsigned char)(cc); jx[nx++]=n; n += 4; } while (0)

    b[n++]=0x50;                                                  /* push rax             */
    b[n++]=0x51;                                                  /* push rcx             */
    b[n++]=0x52;                                                  /* push rdx             */

    /* fighter = [[rbp+0x940] + 0x20], guarding both hops                   */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x85; P32(MERIUI_FRAME_OBJ); /* mov rax,[rbp+obj]    */
    b[n++]=0x48; b[n++]=0x85; b[n++]=0xC0;                        /* test rax,rax         */
    JEXIT(0x84);                                                  /* je   exit            */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x40;
    b[n++]=(unsigned char)MERIUI_OBJ_FIGHT;                       /* mov rax,[rax+0x20]   */
    b[n++]=0x48; b[n++]=0x85; b[n++]=0xC0;                        /* test rax,rax         */
    JEXIT(0x84);                                                  /* je   exit            */

    /* ---- record every resolution, capped or not ------------------------ */
    b[n++]=0x66; b[n++]=0x0F; b[n++]=0x7E; b[n++]=0xC1;           /* movd ecx,xmm0        */
    b[n++]=0x89; b[n++]=0x0D; RIP32(MERIUI_VAL_IN);               /* mov [rip+in],ecx     */
    b[n++]=0x89; b[n++]=0x0D; RIP32(MERIUI_VAL_OUT);              /* mov [rip+out],ecx    */
    b[n++]=0x8B; b[n++]=0x88; P32(MERI_OFF_CHARAID);              /* mov ecx,[rax+0xC00]  */
    b[n++]=0x89; b[n++]=0x0D; RIP32(MERIUI_WHO);                  /* mov [rip+who],ecx    */
    b[n++]=0xF0; b[n++]=0x48; b[n++]=0xFF; b[n++]=0x05; RIP32(MERIUI_SEQ);  /* lock inc   */

    /* ---- the rule ------------------------------------------------------ */
    b[n++]=0x83; b[n++]=0xF9; b[n++]=0x3F;                        /* cmp ecx,63           */
    JEXIT(0x87);                                                  /* ja   exit (also -1)  */
    b[n++]=0x48; b[n++]=0xBA; P64(mask);                          /* movabs rdx,mask      */
    b[n++]=0x48; b[n++]=0x0F; b[n++]=0xA3; b[n++]=0xCA;           /* bt   rdx,rcx         */
    JEXIT(0x83);                                                  /* jnc  exit            */

    /* victim = the attacker's rival, through the engine's own weak-ref guard */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x88; P32(MERI_OFF_RIVALCB); /* mov rcx,[rax+cb]     */
    b[n++]=0x48; b[n++]=0x85; b[n++]=0xC9;                        /* test rcx,rcx         */
    JEXIT(0x84);                                                  /* je   exit            */
    b[n++]=0x83; b[n++]=0x79; b[n++]=0x08; b[n++]=0x00;           /* cmp dword[rcx+8],0   */
    JEXIT(0x84);                                                  /* je   exit            */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x88; P32(MERI_OFF_RIVAL);   /* mov rcx,[rax+rival]  */
    b[n++]=0x48; b[n++]=0x85; b[n++]=0xC9;                        /* test rcx,rcx         */
    JEXIT(0x84);                                                  /* je   exit            */

    b[n++]=0x8B; b[n++]=0x81; P32(MERI_OFF_KONPAKU);              /* mov eax,[rcx+konp]   */
    b[n++]=0x89; b[n++]=0x05; RIP32(MERIUI_KONPAKU);
    b[n++]=0x8B; b[n++]=0x81; P32(MERI_OFF_KONPMAX);              /* mov eax,[rcx+max]    */
    b[n++]=0x89; b[n++]=0x05; RIP32(MERIUI_KONPMAX);

    b[n++]=0x8B; b[n++]=0x81; P32(MERI_OFF_KONPAKU);              /* mov eax,[rcx+konp]   */
    b[n++]=0x3B; b[n++]=0x81; P32(MERI_OFF_KONPMAX);              /* cmp eax,[rcx+max]    */
    JEXIT(0x82);                                                  /* jb   exit (has killed) */
    b[n++]=0x66; b[n++]=0x0F; b[n++]=0x7E; b[n++]=0xC0;           /* movd eax,xmm0        */
    b[n++]=0x3D; P32(MERI_CAP_BITS);                              /* cmp eax,3.0f         */
    JEXIT(0x86);                                                  /* jbe  exit            */
    b[n++]=0xB8; P32(MERI_CAP_BITS);                              /* mov eax,3.0f         */
    b[n++]=0x66; b[n++]=0x0F; b[n++]=0x6E; b[n++]=0xC0;           /* movd xmm0,eax        */
    b[n++]=0x89; b[n++]=0x05; RIP32(MERIUI_VAL_OUT);              /* mov [rip+out],eax    */
    b[n++]=0xF0; b[n++]=0x48; b[n++]=0xFF; b[n++]=0x05; RIP32(MERIUI_CAPPED);

    for (i = 0; i < nx; i++) {                                    /* exit:                */
        int d = n - (jx[i] + 4);
        memcpy(b + jx[i], &d, 4);
    }
    b[n++]=0x5A;                                                  /* pop rdx              */
    b[n++]=0x59;                                                  /* pop rcx              */
    b[n++]=0x58;                                                  /* pop rax  (rsp back)  */
    memcpy(b + n, orig, sizeof(orig)); n += (int)sizeof(orig);    /* stolen instructions  */
    rel = (long long)(site + sizeof(orig)) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b + n, &rel, 4); n += 4;                  /* jmp back             */

#undef P32
#undef P64
#undef RIP32
#undef JEXIT

    if (n > MERIUI_DATA_LO) {
        log_line("MERIUI: stub is %d bytes, would overwrite its telemetry -- skipped", n);
        return;
    }
    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);

    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("MERIUI: trampoline out of rel32 range -- skipped"); return;
    }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("MERIUI: VirtualProtect failed at RVA 0x%X", MERIUI_HOOK_RVA); return;
    }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    for (i = 5; i < (int)sizeof(orig); i++) site[i] = 0x90;
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));

    g_meriui_cave = stub;
    *(int*)(stub + MERIUI_WHO) = -1;
    CreateThread(NULL, 0, meriui_watch, NULL, 0, NULL);
    if (dropped) log_line("MERIUI: %d roster id(s) are >= 64, out of the bitmask's reach -- "
                          "they are NOT in scope", dropped);
    log_line("MERIUI: Meri's mode display ON -- the resolved max soul damage is capped "
             "the same way, so the Konpaku bar promises 4 and not 5 (RVA 0x%X hooked, "
             "%d-byte stub at %p, scope mask %016llX). Every action resolution is logged "
             "from here on.",
             MERIUI_HOOK_RVA, n, (void*)stub, (unsigned long long)mask);
}

/* ================= PART 13: "Reawakening Battle" =====================
 *  WHAT IT DOES
 *  ------------
 *  A casual mode: the four characters who own a Reawakening start the match
 *  already in it, instead of having to meet its trigger. Everyone else plays
 *  exactly as before.
 *
 *      pl001 Ichigo (Bankai)  Full Hollowfication
 *      pl003 Uryu             Quincy: Letzt Stil
 *      pl020 Aizen            Complete Hogyoku Fusion
 *      pl036 Ulquiorra        Resurreccion Segunda Etapa
 *      pl052 Yhwach           the Kaiser-level Reawakening
 *
 *  WHY IT IS SAFE TO DO AT ALL
 *  ---------------------------
 *  The Reawakening is the "ura transform". Which trigger a character uses is
 *  data -- `ura_transform_mothod` in CharaStatus, read at 0x1404DA709 into the
 *  status record at +0x8C (and hard-set to 3 for Yhwach at 0x1404DA714):
 *
 *      -1  no Reawakening (41 of the roster)
 *       0  at 0 Konpaku with enough Fighting Spirit   pl001, pl008, pl023
 *       1  Awakening again while Awakened, spirit max  pl003, pl036
 *       2  at 0 Konpaku with enough Fighting Spirit    pl020, pl044
 *       3  Kaiser level 9                              pl052 (exe-side)
 *
 *  But NONE of that is consulted when the engine is told which form to start
 *  in. The fighter's CharaStatus init (0x140462E50) ends with a plain
 *  "requested starting form" switch at 0x1404639C1: form 2 means
 *  transform(fighter,1) followed by transform(fighter,2). That is the path
 *  Training uses for its form selector, which is why picking a Reawakened
 *  form there works with no condition met -- and it is character-agnostic.
 *
 *  HOW
 *  ---
 *  Hook RVA 0x4639C1 -- `mov ecx,[rbp+0x670]`, the read of that requested
 *  form. For our four ids we substitute 2 and let the engine's own two-step
 *  transform run; for everyone else the stolen instruction runs untouched, so
 *  Training's own form selector still works normally.
 *
 *      rsi = the fighter -- `mov rsi,rcx` at 0x140462E7D, the ONLY write to
 *            rsi in the 948 instructions before the site
 *      [rsi+0xC00] = the character id, written by this same function at
 *            0x140462E8A from its own argument, so it is already valid here
 *
 *  Verified before hooking: nothing branches INTO the six replaced bytes (one
 *  branch targets the site itself, which lands on our jmp and is fine), and
 *  rbp is the frame pointer set once at 0x140462E5D.
 *
 *  ONLINE
 *  ------
 *  The decision is a pure function of the character id, so both clients reach
 *  the same starting state with no message -- nothing to sync. What is NOT
 *  safe is meeting a client that does not have this DLL: it would simulate a
 *  base-form opponent and desync. PART 2's issuer tag is exactly the pool
 *  separator for that, so this mode shifts it by REAWAKEN_POOL_TAG and says so
 *  in the log. Set the tag to 0 to share the normal pool (only sane if every
 *  player in it runs this build).
 *
 *  ! pl001 and pl020 carry rev_soul_num 10 against soul_num 8, so in this mode
 *  they start on 10 Konpaku where the rest of the roster has 9. That is the
 *  shipped data for the form, and Training does the same thing -- flagging it
 *  because it IS a balance difference, not because it is a defect.
 * ==================================================================== */
#define REAW_HOOK_RVA    0x4639C1u   /* mov ecx,[rbp+0x670] -- requested form */
#define REAW_OFF_CHARAID 0x0C00      /* fighter: character id                 */
#define REAW_FORM_REV    2           /* 0 base, 1 Awakened, 2 Reawakened      */
#define REAW_CNT_FORCED  0x100       /* cave: fighters started Reawakened      */
#ifndef REAWAKEN_POOL_TAG
#define REAWAKEN_POOL_TAG 4001       /* keeps this mode out of the normal pool */
#endif

/* The roster this applies to. Add or remove ids here -- but keep it in step with
   GameModes/ReawakeningBattle/Script/CharaStatus.fsv, which raises the same
   characters' rev_soul_num to 10 so every Reawakening in the mode fields the
   same Konpaku count. The compare below is `cmp eax, imm8` (sign-extended), so
   an id above 127 would need a wider encoding. */
static const int g_reaw_ids[] = { 1, 3, 20, 36, 52 };

static unsigned char* g_reaw_cave = NULL;

static DWORD WINAPI reaw_watch(LPVOID u)
{
    long long forced = 0;
    int lines = 0;
    (void)u;
    while (g_reaw_cave && lines < 200) {
        long long f2 = *(volatile long long*)(g_reaw_cave + REAW_CNT_FORCED);
        if (f2 != forced) {
            forced = f2; lines++;
            log_line("REAWAKEN: %lld fighter(s) started Reawakened so far", forced);
        }
        Sleep(1000);
    }
    return 0;
}

static void patch_reawaken_battle(void)
{
    static const unsigned char orig[6] = {0x8B,0x8D,0x70,0x06,0x00,0x00};
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    unsigned char* stub;
    unsigned char  b[256];
    int  n = 0, i, nj = 0, jf[8], force_at;
    long long rel;
    DWORD old;

    if (!mod) return;
    site = mod + REAW_HOOK_RVA;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("REAWAKEN: no `mov ecx,[rbp+0x670]` at RVA 0x%X (game updated?) -- skipped",
                 REAW_HOOK_RVA);
        return;
    }
    stub = (unsigned char*)gauge_alloc_near(site, 0x200);
    if (!stub) { log_line("REAWAKEN: no trampoline within +/-2GB -- skipped"); return; }
    memset(stub, 0, 0x200);

#define REAW_PUT32(v) do { int _v = (int)(v); memcpy(b + n, &_v, 4); n += 4; } while (0)

    b[n++]=0x50;                                                  /* push rax             */
    b[n++]=0x8B; b[n++]=0x86; REAW_PUT32(REAW_OFF_CHARAID);       /* mov eax,[rsi+0xC00]  */
    for (i = 0; i < (int)(sizeof(g_reaw_ids)/sizeof(g_reaw_ids[0])); i++) {
        b[n++]=0x83; b[n++]=0xF8; b[n++]=(unsigned char)g_reaw_ids[i];  /* cmp eax,id     */
        b[n++]=0x74; jf[nj++]=n++;                                /* je force             */
    }
    b[n++]=0x58;                                                  /* pop rax              */
    memcpy(b + n, orig, sizeof(orig)); n += (int)sizeof(orig);    /* stolen: mov ecx,[..] */
    rel = (long long)(site + sizeof(orig)) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b + n, &rel, 4); n += 4;                  /* jmp back             */

    force_at = n;                                                 /* force:               */
    for (i = 0; i < nj; i++) b[jf[i]] = (unsigned char)(force_at - (jf[i] + 1));
    b[n++]=0xF0; b[n++]=0x48; b[n++]=0xFF; b[n++]=0x05;
    REAW_PUT32(REAW_CNT_FORCED - (n + 4));                        /* lock inc [rip+cnt]   */
    b[n++]=0x58;                                                  /* pop rax              */
    b[n++]=0xB9; REAW_PUT32(REAW_FORM_REV);                       /* mov ecx,2            */
    rel = (long long)(site + sizeof(orig)) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b + n, &rel, 4); n += 4;                  /* jmp back             */

#undef REAW_PUT32

    if (n > REAW_CNT_FORCED) {
        log_line("REAWAKEN: stub is %d bytes, would overwrite its counter -- skipped", n);
        return;
    }
    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);

    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("REAWAKEN: trampoline out of rel32 range -- skipped"); return;
    }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("REAWAKEN: VirtualProtect failed at RVA 0x%X", REAW_HOOK_RVA); return;
    }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    for (i = 5; i < (int)sizeof(orig); i++) site[i] = 0x90;
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));

    g_reaw_cave = stub;
    CreateThread(NULL, 0, reaw_watch, NULL, 0, NULL);
    log_line("REAWAKEN: Reawakening Battle ON -- pl001/pl003/pl020/pl036 start the match "
             "already Reawakened (RVA 0x%X hooked, %d-byte stub at %p)",
             REAW_HOOK_RVA, n, (void*)stub);

    if (REAWAKEN_POOL_TAG) {
        int before = g_issuer;
        g_issuer += REAWAKEN_POOL_TAG;
        log_line("REAWAKEN: matchmaking issuer %d -> %d -- this mode simulates a different "
                 "fight from a stock patched client, so it gets its own pool. Every player "
                 "must run this same DLL.", before, g_issuer);
    } else {
        log_line("REAWAKEN: pool tag disabled -- this build shares the normal matchmaking "
                 "pool, which desyncs against anyone not running it");
    }
}

/* =====================================================================
 *  FAST BOOT -- drop the "This game auto-saves." notice
 * ---------------------------------------------------------------------
 *  The boot flow is one function, SLogo::Update (VA 0x14074F810, 3036 B),
 *  a 16-state machine on [this+0xD0] dispatched through a trailing jump
 *  table at VA 0x1407503AC (16 x u32, each an offset from the image base).
 *  The state names are the strings at 0x141499078..0x141499130:
 *
 *      CESA_jp / movie_BNE_logo / movie_TAMSOFT_logo / logo_all
 *          the four logo entries, a 4 x 0x28 table at 0x141CF3520
 *          { u32 isMovie; char name[0x18]; float frames; }
 *      TITLE_DIALOGUE2   first-boot language/settings dialog
 *      INIT_OPTION / INIT_FONT
 *      AUTO_SAVE         <-- the screen we are removing
 *
 *  State 8 (VA 0x14074FB9E) is "logos finished". If the first-boot flag at
 *  0x141CDE6EC is clear it jumps straight to state 13; otherwise it runs
 *  TITLE_DIALOGUE2 -> 9 -> INIT_OPTION -> 11 -> (INIT_FONT ->) 12 -> 13.
 *  BOTH paths land on 13.
 *
 *  State 13 (VA 0x1407501DB) builds the modal from CommonText key
 *  "AUTO_SAVE" -- the exact en_US record is "This game auto-saves.\n..." --
 *  hands it to the dialog factory at 0x140266FA0 with kind 2, then advances
 *  to state 14, which spins until the dialog count at 0x141CEA210 drops to
 *  zero, i.e. until the player clicks Close. State 15 (VA 0x140750310) is
 *  the terminal state: it returns 1, which is what tells the scene manager
 *  the logo scene is over and the title screen may load.
 *
 *  So the whole screen is one jump-table entry. Repoint slot 13 at state
 *  15's handler and every path into 13 falls straight out of the scene --
 *  no dialog is ever constructed, so state 14 has nothing to wait for and
 *  is skipped with it. Nothing else reads slot 13, and the notice is a
 *  message box only: it neither initialises nor touches the save system.
 *
 *  Guarded on slots 12..15 (16 bytes), which pins the table's identity;
 *  only slot 13 is written.
 *
 *  Found statically on the 2025-12-04 build (28,283,464 B) and CONFIRMED IN
 *  GAME 2026-08-26: the notice is gone and boot runs logos -> title with no
 *  click. */
#define FASTBOOT_JMPTBL_RVA 0x7503AC
#define FASTBOOT_SLOT13_RVA (FASTBOOT_JMPTBL_RVA + 13 * 4)

/* ================= PART 19: "Backstep hold" (TEST) ====================
 *
 *  WHERE THE RULE LIVES.  BrainPad is the player's pad->command encoder, built
 *  by OPlayableBase::vfunc75 AND OOnlinePlayable::vfunc75 -- the same class
 *  online and off. Its vfunc2 emits 6-byte records {u16 cmd, u16 dir, u16 x}
 *  into a list the fighter then consumes; cmd indexes a table of action-name
 *  strings, of which the ones that matter here are
 *      1 = walk    2 = run_in    3 = step_f/_r/_b/_l    4 = dash_f_in
 *  and for cmd 3 the direction bucket is 0/1 = f, 2 = r, 3 = b, 4 = l.
 *
 *  Located on the shipped 28,283,464 B build through RTTI, NOT through any
 *  catalogued address: ".?AVBrainPad@@" -> TypeDescriptor -> COL 0x14DCC58 ->
 *  vtable 0x142C048, whose slot 2 is 0x140410ED0. The sibling init at
 *  0x140410DA0 confirms it -- it reads move_front/back/side_threshold and
 *  step_front/back/side_threshold from CommonParam.fsv in that order into
 *  this+0x70..+0x84, and vfunc2 is the only reader of those fields.
 *
 *  THE ASYMMETRY THIS EXISTS TO FIX.  Walk/run (1,2) are pushed on EVERY frame
 *  the stick is held, and the dash (4) on every frame the button is held past
 *  the threshold -- so a level-triggered command is already present on whatever
 *  frame the fighter becomes actionable, which is why held back+dash retreats
 *  frame 1 out of blockstun. The step (3) is pushed ONCE, on the button's
 *  RELEASE frame, and only while the hold timer at this+0x90 is still under
 *  `comiss [0x1414C0440]` = 15.0 -- 15 frames, the timer counting one per frame.
 *  Mashing it therefore has to land its single release frame on the first
 *  actionable frame. That is the coin flip, and it is not a buffering problem:
 *  the engine's buffered_input_frame latches are on the combo-graph path
 *  (CAppActionEvent::vfunc73), which locomotion never touches.
 *
 *  WHAT THIS DOES.  Hook A lets the step branch run while the button is merely
 *  HELD past the threshold, instead of only on release. Hook B then discards
 *  the result unless the direction bucket passes BSH_ALLOW_SIDES -- by default
 *  bucket >= 2, i.e. back AND the two sides -- handing neutral and front back to
 *  the dash branch untouched. So the stock forward dash is unchanged and only
 *  the held directional gestures are re-pointed onto steps.
 *
 *  ! The stun test alone was NOT enough and briefly removed the mechanic: by the
 *  frame the player is actionable again the state has already left the stun
 *  range, so nothing was forced. `fighter+0xFA0` does not stay put across that
 *  transition. Reported and correctly diagnosed by the player, who proposed the
 *  grace window now implemented: seeing a stun state arms BSH_GRACE_N frames of
 *  credit, spent one per held frame afterwards.
 *
 *  ! NARROWED 2026-08-31, reported from play: the buffer now applies ONLY out of
 *  blockstun. Being able to hold the dash button and merely flick back made
 *  run -> backdash far too direct -- the stock motion is run, stick back to
 *  neutral as the run is released, then backdash. Forcing the step in neutral
 *  removed that whole step. The gate is the fighter's current command being in
 *  the guard/blockstun range measured for PART 24 (5..8 plus 12); anywhere else
 *  the gesture falls through to stock behaviour and still gives the run.
 *
 *  ! REGRESSION FIXED 2026-08-30, reported from play. The first build pushed
 *  cmd 3 on EVERY frame the gesture was held -- including every frame of the
 *  step's own recovery, which the stock game never does because it pushes the
 *  step once, on release. Symptom: a normal sidestep into a run waits out the
 *  full step recovery, but a HELD sidestep into a held run cancelled part of
 *  that recovery and ran early. The extra cmd 3 during the step was the only
 *  difference from stock, so the guard removes exactly it: stub A now reads the
 *  fighter's current command and declines to force when a step is already
 *  running. The frame-1 property is untouched -- coming out of blockstun the
 *  current command is a guard, not a step, so the force still happens on the
 *  first actionable frame.
 *  ! Consequence to watch: holding no longer re-enters at StepCancelTiming, so
 *  a held gesture repeats only once the step has fully ended.
 *
 *  ! THE OPEN QUESTION THIS BUILD EXISTS TO ANSWER.  The consumer's
 *  same-command guard (the current command at fighter+0xFA0) is set only by the
 *  combo-graph selection passes, so a locomotion command is dispatched with no
 *  de-duplication -- the step should re-enter as soon as step_b_act's own
 *  CancelTiming/StepCancelTiming allows, i.e. it should CHAIN. Whether that
 *  chain is playable or awful is exactly what this variant is for. The brake,
 *  if one is wanted, is data: the cancel windows in each character's .tadjpkg.
 *
 *  Hook sites, with the bytes asserted before anything is written:
 *      0x140411A31  84 DB 0F 84 81 01 00 00   test bl,bl / je hold   (8 stolen)
 *      0x140411B92  48 3B 7C 24 50            cmp rdi,[rsp+0x50]     (5 stolen)
 *  bl = "released this frame", sil = "button active", r13b = "hold > 15" are
 *  all set at 0x140411969/196F/197A and live in non-volatile registers, so they
 *  survive the helper call the step branch makes at 0x140411B17.
 *  0x140411B92 is reached ONLY from 0x140411B53 and by fall-through from
 *  0x140411B8D, both inside the step branch, so hooking it catches all five
 *  directions and nothing else.
 *
 *  STATIC ONLY -- never yet run. */
#define BSH_HOOKA_RVA    0x411A31
#define BSH_HOOKB_RVA    0x411B92
#define BSH_STEP_ENTRY   0x411A4C   /* mov word [rsp+0x20],3                  */
#define BSH_REL_CHECK    0x411A39   /* the original post-`test bl,bl` path    */
#define BSH_HOLD_BR      0x411BBA   /* the dash/run branch                    */
#define BSH_PUSH_CONT    0x411B97   /* je 0x140411DFB, just past the stolen 5 */
/* Which direction buckets the held gesture may turn into a step. The bucket is
   0 = neutral, 1 = front, 2 = right, 3 = back, 4 = left -- verified: the front
   case writes r12w at 0x140411B4D and r12d is loaded with 1 at 0x140411A1F/A2B,
   immediately before the step branch. So "back and the two sides" is the single
   test `bucket >= 2`, and neutral/front keep the stock forward dash.
   SHIPPED AT 1 since 2026-08-31. The sides were held back while the force applied
   wherever the gesture was held, because the recovery defect -- held steps that
   spam and cancel into a run far too early -- would have been multiplied by
   three. BSH_ONLY_IN_STUN removed the support for that: the force now happens
   only out of blockstun and only for BSH_GRACE_N frames, so a held gesture in
   neutral no longer produces anything to spam. -DBSH_ALLOW_SIDES=0 restores the
   back-only build. */
#ifndef BSH_ALLOW_SIDES
#define BSH_ALLOW_SIDES  1
#endif
/* BrainPad+0x28 is the FIGHTER. Verified two ways in vfunc2 itself: 0x14041315D
   reads `byte [rcx+0xFA0]` -- the same "current command" byte the consumer reads
   as `local_be4` before deciding whether to re-dispatch -- and 0x1404133CF does
   `cmp dword [rax+0xC00], 0x14`, the chara id PART 12 already uses. */
#define BSH_FIGHTER      0x28
#define BSH_CURCMD       0xFA0
#define BSH_STUBB        0xC0       /* stub B's offset inside the allocation  */
#define BSH_FLAG         0x180      /* the "we forced this step" byte         */

static void patch_backstep_hold(void)
{
    static const unsigned char origA[8] =
        {0x84,0xDB,0x0F,0x84,0x81,0x01,0x00,0x00};
    static const unsigned char origB[5] =
        {0x48,0x3B,0x7C,0x24,0x50};
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* siteA;
    unsigned char* siteB;
    unsigned char* stub;
    unsigned char  b[512];
    int n = 0;
    int jhold[8], njh = 0, jrel, jok, jnobit, jforce, jforce2, jblocked, jspend, i;
    DWORD old;

    if (!mod) return;
    siteA = mod + BSH_HOOKA_RVA;
    siteB = mod + BSH_HOOKB_RVA;
    if (memcmp(siteA, origA, sizeof(origA)) != 0) {
        log_line("BACKSTEP: no `test bl,bl / je` at RVA 0x%X (game updated?) -- skipped",
                 BSH_HOOKA_RVA);
        return;
    }
    if (memcmp(siteB, origB, sizeof(origB)) != 0) {
        log_line("BACKSTEP: no `cmp rdi,[rsp+0x50]` at RVA 0x%X (game updated?) -- skipped",
                 BSH_HOOKB_RVA);
        return;
    }
    stub = (unsigned char*)gauge_alloc_near(siteA, 0x400);
    if (!stub) { log_line("BACKSTEP: no trampoline within +/-2GB -- skipped"); return; }
    memset(stub, 0, 0x400);
    memset(b, 0x90, sizeof(b));

/* rel32 to an absolute address in the exe, from the current point in the stub */
#define BABS(rva) do { int _v = (int)((long long)(mod + (rva)) - (long long)(stub + n + 4)); \
                       memcpy(b + n, &_v, 4); n += 4; } while (0)
/* a plain little-endian u32 (a struct displacement, not a relative address)   */
#define BP32(v)   do { unsigned int _v = (unsigned int)(v); \
                       memcpy(b + n, &_v, 4); n += 4; } while (0)
/* rel32 to the flag byte at offset `o` in the stub; `tail` is how many bytes  */
/* of the instruction still follow the displacement (the imm8, so 1)           */
#define BRIP(o, tail) do { int _v = (int)((o) - (n + 4 + (tail))); \
                           memcpy(b + n, &_v, 4); n += 4; } while (0)

    /* ---------------- stub A : entered instead of `test bl,bl` -------------
       rax is pushed rather than argued about: it looks dead at all three exit
       targets, but HOLD_BR is reached from several predecessors and a liveness
       argument that has to hold down every one of them is not worth 4 bytes. */
    b[n++]=0x50; b[n++]=0x51;                                /* push rax, rcx    */
    b[n++]=0xC6; b[n++]=0x05; BRIP(BSH_FLAG,1); b[n++]=0x00; /* mov byte[flag],0 */
    b[n++]=0x84; b[n++]=0xDB;                                /* test bl,bl       */
    b[n++]=0x0F; b[n++]=0x85; jrel = n; n += 4;              /* jne  L_rel       */
    b[n++]=0x40; b[n++]=0x84; b[n++]=0xF6;                   /* test sil,sil     */
    b[n++]=0x0F; b[n++]=0x84; jhold[njh++] = n; n += 4;      /* je   L_hold      */
    b[n++]=0x45; b[n++]=0x84; b[n++]=0xED;                   /* test r13b,r13b   */
    b[n++]=0x0F; b[n++]=0x84; jhold[njh++] = n; n += 4;      /* je   L_hold      */
    b[n++]=0x49; b[n++]=0x8B; b[n++]=0x46; b[n++]=BSH_FIGHTER;
                                                             /* mov rax,[r14+28] */
    b[n++]=0x48; b[n++]=0x85; b[n++]=0xC0;                   /* test rax,rax     */
    b[n++]=0x0F; b[n++]=0x84; jhold[njh++] = n; n += 4;      /* je L_hold (null) */
    /* The guard, plus the counters that will say whether it is the right one.
       ! An earlier round concluded this guard "removed the held sidestep" and
       tore it out. That reading was wrong: patch_ranked.log showed the run in
       question had loaded the older BACK-ONLY dll (Files/Matchmaking/dinput8.dll
       was stale because dll_switch had not been re-run), which has no sidestep
       at all. The guard had never executed. It is restored here WITH telemetry
       so the next run reports facts instead of inviting another guess. */
    b[n++]=0x0F; b[n++]=0xB6; b[n++]=0x80; BP32(BSH_CURCMD); /* movzx eax,[rax+FA0] */
    b[n++]=0x88; b[n++]=0x05; BRIP(BSH_LAST,0);              /* mov  [last],al   */
    b[n++]=0x3C; b[n++]=0x20;                                /* cmp  al,32       */
    b[n++]=0x73; jnobit = n++;                               /* jae  L_nobit     */
    b[n++]=0x0F; b[n++]=0xAB; b[n++]=0x05; BRIP(BSH_MASK,0); /* bts  [mask],eax  */
    b[jnobit] = (unsigned char)(n - (jnobit + 1));           /* L_nobit:         */
    b[n++]=0x3C; b[n++]=0x03;                                /* cmp  al,3        */
    b[n++]=0x0F; b[n++]=0x84; jblocked = n; n += 4;          /* je   L_blocked   */
    /* in a stun state: arm the credit and force */
    b[n++]=0x8D; b[n++]=0x48; b[n++]=(unsigned char)(0x100 - BSH_STUN_LO);
    b[n++]=0x83; b[n++]=0xF9; b[n++]=(BSH_STUN_HI - BSH_STUN_LO);
    b[n++]=0x76; jforce = n++;                               /* jbe L_setgrace 5..8  */
    b[n++]=0x8D; b[n++]=0x48; b[n++]=(unsigned char)(0x100 - BSH_STUN2_LO);
    b[n++]=0x83; b[n++]=0xF9; b[n++]=(BSH_STUN2_HI - BSH_STUN2_LO);
    b[n++]=0x76; jforce2 = n++;                              /* jbe L_setgrace 12..14 */
    /* out of stun: spend a frame of credit, if any is left */
    b[n++]=0x80; b[n++]=0x3D; BRIP(BSH_GRACE,1); b[n++]=0x00;/* cmp byte[grace],0*/
    b[n++]=0x0F; b[n++]=0x84; jhold[njh++] = n; n += 4;      /* je L_hold (spent)*/
    b[n++]=0xFE; b[n++]=0x0D; BRIP(BSH_GRACE,0);             /* dec byte[grace]  */
    b[n++]=0xE9; jspend = n; n += 4;                         /* jmp  L_force     */
    b[jforce]  = (unsigned char)(n - (jforce  + 1));         /* L_setgrace:      */
    b[jforce2] = (unsigned char)(n - (jforce2 + 1));
    b[n++]=0xC6; b[n++]=0x05; BRIP(BSH_GRACE,1); b[n++]=BSH_GRACE_N;
    { int r = n - (jspend + 4); memcpy(b + jspend, &r, 4); } /* L_force:         */
    b[n++]=0xFF; b[n++]=0x05; BRIP(BSH_FORCED,0);            /* inc  [forced]    */
    b[n++]=0xC6; b[n++]=0x05; BRIP(BSH_FLAG,1); b[n++]=0x01; /* mov byte[flag],1 */
    b[n++]=0x59; b[n++]=0x58;                                /* pop  rcx, rax    */
    b[n++]=0xE9; BABS(BSH_STEP_ENTRY);                       /* jmp  step        */
    { int r = n - (jblocked + 4); memcpy(b + jblocked, &r, 4); }  /* L_blocked:  */
    /* A step is running, so this window has done its job: burn the rest of the
       credit. Without this the credit is never spent DURING a step -- the
       already-stepping test sits before the grace logic -- so enough survived to
       force a second step the moment the first ended, and a held gesture chained
       steps faster than mashing could. Reported from play 2026-08-31. Clearing
       it here keeps the full 5-frame tolerance for CATCHING the wake-up frame
       while allowing exactly one step per window, which is the stated intent;
       shrinking BSH_GRACE_N would only have limited the chain and would have cost
       tolerance. */
    b[n++]=0xC6; b[n++]=0x05; BRIP(BSH_GRACE,1); b[n++]=0x00;/* mov byte[grace],0*/
    b[n++]=0xFF; b[n++]=0x05; BRIP(BSH_BLOCKED,0);           /* inc  [blocked]   */
    b[n++]=0xE9; jhold[njh++] = n; n += 4;                   /* jmp  L_hold      */
    for (i = 0; i < njh; i++) {                              /* L_hold:          */
        int r = n - (jhold[i] + 4); memcpy(b + jhold[i], &r, 4);
    }
    b[n++]=0x59; b[n++]=0x58;                                /* pop  rcx, rax    */
    b[n++]=0xE9; BABS(BSH_HOLD_BR);                          /* jmp  hold        */
    { int r = n - (jrel + 4); memcpy(b + jrel, &r, 4); }     /* L_rel:           */
    b[n++]=0x59; b[n++]=0x58;                                /* pop  rcx, rax    */
    b[n++]=0xE9; BABS(BSH_REL_CHECK);                        /* jmp  original    */

    if (n > BSH_STUBB) { log_line("BACKSTEP: stub A overflowed (%d) -- skipped", n); return; }

    /* ---------------- stub B : entered instead of the record push ---------- */
    n = BSH_STUBB;
    b[n++]=0x80; b[n++]=0x3D; BRIP(BSH_FLAG,1); b[n++]=0x00; /* cmp byte[flag],0 */
    b[n++]=0xC6; b[n++]=0x05; BRIP(BSH_FLAG,1); b[n++]=0x00; /* mov byte[flag],0 */
                                                             /* (mov keeps flags)*/
    b[n++]=0x74; jok = n++;                                  /* je   L_ok        */
    b[n++]=0x66; b[n++]=0x83; b[n++]=0x7C; b[n++]=0x24;
    b[n++]=0x22; b[n++]=(BSH_ALLOW_SIDES ? 0x02 : 0x03);     /* cmp word[rsp+22],N */
    b[n++]=0x0F; b[n++]=(BSH_ALLOW_SIDES ? 0x82 : 0x85);     /* jb / jne  hold   */
    BABS(BSH_HOLD_BR);
    b[jok] = (unsigned char)(n - (jok + 1));                 /* L_ok:            */
    b[n++]=0x48; b[n++]=0x3B; b[n++]=0x7C; b[n++]=0x24;
    b[n++]=0x50;                                             /* cmp rdi,[rsp+50] */
    b[n++]=0xE9; BABS(BSH_PUSH_CONT);                        /* jmp  continue    */

    if (n > BSH_FLAG) { log_line("BACKSTEP: stub B overflowed (%d) -- skipped", n); return; }
#undef BABS
#undef BRIP
#undef BP32

    memcpy(stub, b, BSH_FLAG);
    stub[BSH_FLAG] = 0;
    g_bsh_cave = stub;

    /* ---------------- redirect both sites --------------------------------- */
    if (VirtualProtect(siteA, 8, PAGE_EXECUTE_READWRITE, &old)) {
        int r = (int)((long long)stub - (long long)(siteA + 5));
        siteA[0] = 0xE9; memcpy(siteA + 1, &r, 4);
        siteA[5] = 0x90; siteA[6] = 0x90; siteA[7] = 0x90;
        VirtualProtect(siteA, 8, old, &old);
    } else { log_line("BACKSTEP: VirtualProtect failed on hook A -- skipped"); return; }

    if (VirtualProtect(siteB, 5, PAGE_EXECUTE_READWRITE, &old)) {
        int r = (int)((long long)(stub + BSH_STUBB) - (long long)(siteB + 5));
        siteB[0] = 0xE9; memcpy(siteB + 1, &r, 4);
        VirtualProtect(siteB, 5, old, &old);
    } else { log_line("BACKSTEP: VirtualProtect failed on hook B -- skipped"); return; }

    log_line("BACKSTEP: installed -- held %s+dash now emits the step every frame "
             "(hooks at 0x%X and 0x%X, stub at %p)",
             BSH_ALLOW_SIDES ? "back/left/right" : "back",
             BSH_HOOKA_RVA, BSH_HOOKB_RVA, (void*)stub);
}

/* ================= PART 20: "Flash step hold" ========================
 *
 *  The mirror of PART 19, on the other button. BrainPad carries two identical
 *  tap/hold rigs: timer +0x90 with "was over threshold last frame" at +0xC8 for
 *  the step/dash button, and timer +0x94 with +0xC9 for this one, both compared
 *  against the same pooled 15.0 at 0x140411863 / 0x140412352.
 *
 *  THE GATE, as shipped (0x1404125E8):
 *      test dword [r14+0xF0], esi     ; a button-mask edge
 *      jne  emit
 *      test bl, bl                    ; the "tap" flag: released, hold < 15
 *      je   skip
 *  emit:
 *      mov  word [rsp+0x20], 0x16     ; syunpo_in
 *
 *  Both conditions are edges, so a held button contributes nothing on the frame
 *  blockstun ends. Walk (1), run (2) and dash (4) are re-pushed EVERY frame
 *  their input is held, which is exactly why those come out frame 1 and this
 *  does not. The fix is to give this command the same property.
 *
 *  +0xC9 is the right bit to key on: it is written at 0x140412549 from this
 *  frame's "timer > 15", earlier in the same function than the gate, so it is
 *  current by the time we read it. It also means the level path opens after 15
 *  frames of holding, the same threshold the backstep uses -- which is fine for
 *  the reported case (holding through blockstun) and keeps the two mechanics
 *  consistent.
 *
 *  ! The hook is at 0x1404125E8 and steals 13 bytes, NOT at the `test bl,bl`
 *  itself: that site looks like 8 bytes in a disassembly listing but the `je`
 *  there is rel8 (74 7E), so the whole thing is 4 bytes and a jmp rel32 does not
 *  fit. Read the ENCODING, not the printed mnemonic.
 *
 *  Both original paths are re-emitted verbatim in the stub, so this only ADDS a
 *  way for the command to appear; nothing that worked before stops working.
 *
 *  Verified against the shipped 28,283,464 B build. STATIC ONLY when written. */
#define FSH_HOOK_RVA     0x4125E8
#define FSH_EMIT_RVA     0x4125F5   /* mov word [rsp+0x20], 0x16              */
#define FSH_SKIP_RVA     0x412673   /* the next command block                 */
#define FSH_MASK_OFF     0xF0       /* BrainPad: this button's mask           */
#define FSH_HELD_OFF     0xC9       /* BrainPad: "held past 15 frames"        */

static void patch_flashstep_hold(void)
{
    static const unsigned char orig[13] =
        {0x41,0x85,0xB6,0xF0,0x00,0x00,0x00,0x75,0x04,0x84,0xDB,0x74,0x7E};
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    unsigned char* stub;
    unsigned char  b[128];
    int n = 0, i;
    int jemit[2], nje = 0, jskip, jedge, jheld;
    int jnofi, jclr, jclr2, jarm1, jarm2, jspent, jgo;
    DWORD old;

    if (!mod) return;
    site = mod + FSH_HOOK_RVA;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("FLASHSTEP: the syunpo gate is not at RVA 0x%X (game updated?) -- skipped",
                 FSH_HOOK_RVA);
        return;
    }
    stub = (unsigned char*)gauge_alloc_near(site, 0x200);
    if (!stub) { log_line("FLASHSTEP: no trampoline within +/-2GB -- skipped"); return; }
    memset(stub, 0, 0x200);

#define FABS(rva) do { int _v = (int)((long long)(mod + (rva)) - (long long)(stub + n + 4)); \
                       memcpy(b + n, &_v, 4); n += 4; } while (0)
#define BRIP2(o,t) do { int _v = (int)((o) - (n + 4 + (t)));                                   \
                        memcpy(b + n, &_v, 4); n += 4; } while (0)
#define FP32(v)   do { unsigned int _v = (unsigned int)(v);                                   \
                       memcpy(b + n, &_v, 4); n += 4; } while (0)

    /* Each path gets its own counter, so a log says WHICH condition let the
       command out -- or that none did, which is the interesting case. */
#define FCOUNT(slot) do { b[n++]=0xFF; b[n++]=0x05;                                     \
                          { int _r = (slot) - (n + 4); memcpy(b + n, &_r, 4); n += 4; } \
                        } while (0)

    /* ⛔ OFF, AND CONFIRMED HARMFUL 2026-08-31. It broke the Hoho FOLLOW-UP, and
       removing it brought the follow-up straight back -- reported, then verified
       by the removal, which is as close to causal as this setup gets. Against
       that it delivered nothing measurable: `held=0` in every instrumented
       session, because the level condition it rests on never fires (see below).
       A patch with no measured benefit and a confirmed regression does not ship.
       DO NOT re-enable without a measurement showing the condition fires AND a
       check that the follow-up survives.

       The original level condition, restored on request 2026-08-31.
       ! Measured INERT: the gate counters read `held=0` in every instrumented
       session while `edge` and `tap` moved, because `sil` -- which drives the
       +0x94 timer and hence this +0xC9 bit -- comes from `[r14+0xF0] & r12d`,
       and r12d never carries this button. Kept because it is purely additive:
       if it never fires it removes nothing, and the two shipped paths below are
       re-emitted verbatim.
       ! A PART 19-style blockstun window was tried here and REMOVED: that branch
       jumped straight to the emission WITHOUT TESTING ANY INPUT, so it fired the
       flash step every frame of a stun state. The obstacle it ran into is real
       and still open -- there is no "this button is held" signal at this site.
       The binding is a COMBO (trigger + button), and a combo bit appears only in
       the edge masks, never in the held mask. That is also why +0xC9 never
       sets. */
    b[n++]=0x41; b[n++]=0x80; b[n++]=0xBE; FP32(FSH_HELD_OFF);
    b[n++]=0x00;                                                /* cmp [r14+C9],0    */
    b[n++]=0x0F; b[n++]=0x85; jheld = n; n += 4;                /* jne  L_held       */
    /* the shipped mask edge, re-emitted verbatim */
    b[n++]=0x41; b[n++]=0x85; b[n++]=0xB6; FP32(FSH_MASK_OFF);  /* test [r14+F0],esi */
    b[n++]=0x0F; b[n++]=0x85; jedge = n; n += 4;                /* jne  L_edge       */
    /* the shipped tap path, re-emitted verbatim */
    b[n++]=0x84; b[n++]=0xDB;                                   /* test bl,bl        */
    b[n++]=0x0F; b[n++]=0x84; jskip = n; n += 4;                /* je   L_skip       */
    FCOUNT(FSH_C_TAP);                                          /* L_tap:            */
    b[n++]=0xE9; jemit[nje++] = n; n += 4;                      /* jmp  L_emit       */
    { int r = n - (jedge + 4); memcpy(b + jedge, &r, 4); }      /* L_edge:           */
    FCOUNT(FSH_C_EDGE);
    b[n++]=0xE9; jemit[nje++] = n; n += 4;                      /* jmp  L_emit       */
    { int r = n - (jheld + 4); memcpy(b + jheld, &r, 4); }      /* L_held:           */
    FCOUNT(FSH_C_HELD);
    for (i = 0; i < nje; i++) {                                 /* L_emit:           */
        int r = n - (jemit[i] + 4); memcpy(b + jemit[i], &r, 4);
    }
    b[n++]=0xE9; FABS(FSH_EMIT_RVA);
    { int r = n - (jskip + 4); memcpy(b + jskip, &r, 4); }      /* L_skip:           */
    FCOUNT(FSH_C_SKIP);
    b[n++]=0xE9; FABS(FSH_SKIP_RVA);
#undef FCOUNT

    if (n > FSH_C_EDGE) { log_line("FLASHSTEP: stub overflowed (%d) -- skipped", n); return; }
#undef FABS
#undef FP32
#undef BRIP2

    memcpy(stub, b, n);
    g_fsh_cave = stub;

    if (VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        int r = (int)((long long)stub - (long long)(site + 5));
        site[0] = 0xE9; memcpy(site + 1, &r, 4);
        memset(site + 5, 0x90, sizeof(orig) - 5);
        VirtualProtect(site, sizeof(orig), old, &old);
    } else { log_line("FLASHSTEP: VirtualProtect failed -- skipped"); return; }

    log_line("FLASHSTEP: installed -- a held flash step now comes out on the first "
             "actionable frame (hook at 0x%X, stub at %p)", FSH_HOOK_RVA, (void*)stub);
}

/* ================= PART 21: input-mask probe (DIAGNOSTIC) ============
 *
 *  Reported: with a CUSTOM control scheme, LT+A (Hoho) coming straight out of
 *  blockstun or hitstun produces Spiritual Pressure Move 2 instead. Present in
 *  vanilla, so it is not one of ours.
 *
 *  What the code already says. In BrainPad::vfunc2 the flash step and the three
 *  SP moves are emitted from one contiguous block, each gated on its own mask
 *  field, and the SP gates are a SINGLE mask test with no loose second
 *  condition:
 *      0x16 syunpo <- [r14+0xF0] & mask   (plus an OR on the tap flag)
 *      0x25        <- [r14+0x100] & mask
 *      0x26        <- [r14+0x104] & mask
 *  So an SP firing on a button bound to Hoho is not a lax gate -- it means the
 *  SP's MASK CONTAINS THAT BUTTON'S BIT. This probe is here to prove or kill
 *  that, because the alternative was a third guess and this session has already
 *  paid for two.
 *
 *  Hooked at 0x140411853 (`mov byte [r14+0x111], al`, 7 bytes, on vfunc2's main
 *  path with r14 = the BrainPad). Snapshots the mask block EVERY frame rather
 *  than once, so that a mask rewritten mid-match -- vfunc2 has a path that
 *  re-derives the whole button state from the per-scheme table at stride 0x150
 *  when an action-id list is present, and that path is the prime suspect for
 *  "only out of blockstun" -- is visible instead of being missed by an early
 *  one-shot capture.
 *
 *  Reading it: any bit appearing in TWO of these fields is the defect, and the
 *  pair names which two actions collide. */
#define IPR_HOOK_RVA  0x411853
#define IPR_BACK_RVA  0x41185A

static void patch_input_probe(void)
{
    static const unsigned char orig[7] = {0x41,0x88,0x86,0x11,0x01,0x00,0x00};
    static const unsigned int  off[IPR_NSLOT] =
        {0xCC,0xD8,0xE0,0xE4,0xF0,0xF4,0xF8,0x100,0x104,0x108,0x10C};
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    unsigned char* stub;
    unsigned char  b[512];
    int n = 0, i;
    DWORD old;

    if (!mod) return;
    site = mod + IPR_HOOK_RVA;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("INPUTPROBE: no `mov [r14+0x111],al` at RVA 0x%X -- skipped", IPR_HOOK_RVA);
        return;
    }
    stub = (unsigned char*)gauge_alloc_near(site, 0x1800);
    if (!stub) { log_line("INPUTPROBE: no trampoline within +/-2GB -- skipped"); return; }
    memset(stub, 0, 0x1800);

    memcpy(b + n, orig, sizeof(orig)); n += (int)sizeof(orig);   /* stolen        */
    b[n++]=0x50;                                                 /* push rax      */
    for (i = 0; i < IPR_NSLOT; i++) {
        unsigned int d = off[i];
        int rel;
        b[n++]=0x41; b[n++]=0x8B; b[n++]=0x86;                   /* mov eax,[r14+d] */
        memcpy(b + n, &d, 4); n += 4;
        b[n++]=0x89; b[n++]=0x05;                                /* mov [rip+s],eax */
        rel = (IPR_SNAP + i * 4) - (n + 4);
        memcpy(b + n, &rel, 4); n += 4;
    }
    b[n++]=0x8B; b[n++]=0x44; b[n++]=0x24; b[n++]=0x60;           /* mov eax,[rsp+0x60] */
    b[n++]=0x89; b[n++]=0x05;                                    /* mov [rip+down],eax */
    { int rel2 = IPR_DOWN - (n + 4); memcpy(b + n, &rel2, 4); n += 4; }
    b[n++]=0xFF; b[n++]=0x05;                                    /* inc [rip+ticks] */
    { int rel = IPR_TICKS - (n + 4); memcpy(b + n, &rel, 4); n += 4; }
    b[n++]=0x58;                                                 /* pop rax       */
    b[n++]=0xE9;
    { int rel = (int)((long long)(mod + IPR_BACK_RVA) - (long long)(stub + n + 4));
      memcpy(b + n, &rel, 4); n += 4; }

    if (n > IPR_SNAP) { log_line("INPUTPROBE: stub overflowed (%d) -- skipped", n); return; }
    memcpy(stub, b, n);
    g_ipr_cave = stub;

    if (VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        int rel = (int)((long long)stub - (long long)(site + 5));
        site[0] = 0xE9; memcpy(site + 1, &rel, 4);
        site[5] = 0x90; site[6] = 0x90;
        VirtualProtect(site, sizeof(orig), old, &old);
    } else { log_line("INPUTPROBE: VirtualProtect failed -- skipped"); return; }

    /* ---- the OTHER two places cmd 0x16 is emitted -----------------------
       The engine has THREE parallel emit sites for the flash step, chosen by
       configuration, and they are not variants of one gate:
         0x4125F5  [r14+0xF0] & mask, or the tap flag   (what PART 20 hooks)
         0x4127F9  test dword [r9+rax*8], 0x3000        (table + bitfield)
         0x412D00  reads the config table at 0x1CE8A94 directly
       PART 20 assumed the first was the only one. A custom scheme reported the
       held flash step still doing nothing, and the gate counters came back ALL
       ZERO -- including the "not emitted" path -- while the backstep counters on
       the same frames were moving. That is only possible if that block is never
       reached, i.e. the scheme routes through one of the other two.
       These two hooks only COUNT; they change no behaviour. Each steals the
       7-byte `mov word [rsp+0x20], 0x16` and re-emits it. */
    {
        static const unsigned char emit16[7] = {0x66,0xC7,0x44,0x24,0x20,0x16,0x00};
        const unsigned int sites[2] = {0x4127F9, 0x412D00};
        const unsigned int slots[2] = {IPR_SITE2, IPR_SITE3};
        int k;
        for (k = 0; k < 2; k++) {
            unsigned char* s2 = mod + sites[k];
            unsigned char* c  = stub + 0x100 + k * 0x40;   /* a little code cave each */
            int m = 0, rel;
            if (memcmp(s2, emit16, sizeof(emit16)) != 0) {
                log_line("INPUTPROBE: no `mov word[rsp+0x20],0x16` at 0x%X -- site not counted",
                         sites[k]);
                continue;
            }
            c[m++]=0xFF; c[m++]=0x05;                       /* inc [rip+slot]  */
            rel = (int)((long long)(stub + slots[k]) - (long long)(c + m + 4));
            memcpy(c + m, &rel, 4); m += 4;
            memcpy(c + m, emit16, sizeof(emit16)); m += (int)sizeof(emit16);
            c[m++]=0xE9;                                    /* jmp back        */
            rel = (int)((long long)(s2 + sizeof(emit16)) - (long long)(c + m + 4));
            memcpy(c + m, &rel, 4); m += 4;

            if (VirtualProtect(s2, sizeof(emit16), PAGE_EXECUTE_READWRITE, &old)) {
                rel = (int)((long long)c - (long long)(s2 + 5));
                s2[0] = 0xE9; memcpy(s2 + 1, &rel, 4);
                s2[5] = 0x90; s2[6] = 0x90;
                VirtualProtect(s2, sizeof(emit16), old, &old);
                log_line("INPUTPROBE: counting flash-step emit site 0x%X", sites[k]);
            }
        }
    }

    /* ---- count every emit site of the commands in play --------------------
       The reported bug is "pressing Hoho WHILE GUARDING fires SP2, when it
       should do nothing". That is not a missing Hoho -- something else is being
       pushed. Each of these sites is the same 7-byte `mov word [rsp+0x20], imm`,
       so one loop hooks them all: bump the counter for that command id, re-emit
       the stolen store, jump back. Behaviour is unchanged. */
    {
        /* 0x28 gets one counter PER SITE (slots 6..10) -- it tracks the press
           exactly, so the next question is which of its five sites fires. */
        static const unsigned int cmds[IPR_NCMD] = {0x16,0x20,0x21,0x25,0x26,0x27,0x28};
        static const unsigned int sites[] = {
            0x4125F5, 0x4127F9, 0x412D00,                        /* 0x16 */
            0x4125A9, 0x41276D,                                  /* 0x20 */
            0x41255D,                                            /* 0x21 */
            0x41267C, 0x4129B0, 0x412DE6,                        /* 0x25 */
            0x4126C4, 0x412B20, 0x412E8D,                        /* 0x26 */
            0x412BAB, 0x412F34,                                  /* 0x27 */
            0x412634, 0x412838, 0x412D3F, 0x412FA5, 0x413061 };  /* 0x28 */
        int nsites = (int)(sizeof(sites) / sizeof(sites[0]));
        unsigned char* cave = stub + 0x300;
        int k, installed = 0, n28 = 0, n26 = 0;
        for (k = 0; k < nsites; k++) {
            unsigned char* s2 = mod + sites[k];
            unsigned int   id = (unsigned int)s2[5] | ((unsigned int)s2[6] << 8);
            unsigned char* c;
            int m = 0, rel, w;
            if (s2[0] != 0x66 || s2[1] != 0xC7 || s2[2] != 0x44 ||
                s2[3] != 0x24 || s2[4] != 0x20) {
                log_line("INPUTPROBE: 0x%X is not a command store -- not counted", sites[k]);
                continue;
            }
            for (w = 0; w < IPR_NCMD; w++) if (cmds[w] == id) break;
            if (w == IPR_NCMD) { log_line("INPUTPROBE: 0x%X stores cmd 0x%X, unexpected -- "
                                          "not counted", sites[k], id); continue; }
            if (id == 0x28) w = IPR_NCMD - 1 + n28++;        /* one slot per site */
            if (id == 0x26) w = IPR_NCMD - 1 + IPR_N28 + n26++;
            c = cave + installed * IPR_CAVE_SZ;
            c[m++]=0xFF; c[m++]=0x05;                        /* inc [rip+counter]  */
            rel = (int)((long long)(stub + IPR_CMD_BASE + w * 4) - (long long)(c + m + 4));
            memcpy(c + m, &rel, 4); m += 4;
            if (id == 0x26) {
                /* The gate here is `test [r14+0x104], r12d` and +0x104 is a
                   constant 0x10 (bit 4), yet it matches while the player presses
                   a button on bit 7. Record r12d rather than guess what it is. */
                c[m++]=0x44; c[m++]=0x89; c[m++]=0x25;            /* mov [rip+r12],r12d */
                { int r2 = (int)((long long)(stub + IPR_R12) - (long long)(c + m + 4));
                  memcpy(c + m, &r2, 4); m += 4; }
            }
            if (id == 0x16) {
                /* BrainPad+0x28 is the fighter; +0xFA0 is its current command.
                   Histogram it here so the guard state is measured rather than
                   assumed to be command 12. */
                int js1, js2;
                c[m++]=0x50;                                     /* push rax          */
                c[m++]=0x49; c[m++]=0x8B; c[m++]=0x46; c[m++]=0x28;
                c[m++]=0x48; c[m++]=0x85; c[m++]=0xC0;           /* test rax,rax      */
                c[m++]=0x74; js1 = m++;                          /* je  done          */
                c[m++]=0x0F; c[m++]=0xB6; c[m++]=0x80;
                { unsigned int d = 0xFA0; memcpy(c + m, &d, 4); m += 4; }
                c[m++]=0x88; c[m++]=0x05;                        /* mov [rip+lastcmd],al */
                { int r2 = (int)((long long)(stub + IPR_LASTCMD) - (long long)(c + m + 4));
                  memcpy(c + m, &r2, 4); m += 4; }
                c[m++]=0x3C; c[m++]=0x20;                        /* cmp al,32         */
                c[m++]=0x73; js2 = m++;                          /* jae skiphist      */
                c[m++]=0x0F; c[m++]=0xAB; c[m++]=0x05;           /* bts [rip+fmask],eax */
                { int r2 = (int)((long long)(stub + IPR_FMASK) - (long long)(c + m + 4));
                  memcpy(c + m, &r2, 4); m += 4; }
                c[js2] = (unsigned char)(m - (js2 + 1));
                /* the two booleans vfunc2 itself reads off the fighter at
                   0x140411821 / 0x14041182A -- untested, both plausible guard
                   flags, and cheaper to sample than to reason about */
                c[m++]=0x49; c[m++]=0x8B; c[m++]=0x46; c[m++]=0x28;
                c[m++]=0x0F; c[m++]=0xB6; c[m++]=0x80;
                { unsigned int d = 0x9A8; memcpy(c + m, &d, 4); m += 4; }
                c[m++]=0x88; c[m++]=0x05;
                { int r2 = (int)((long long)(stub + IPR_LAST9A8) - (long long)(c + m + 4));
                  memcpy(c + m, &r2, 4); m += 4; }
                c[m++]=0x49; c[m++]=0x8B; c[m++]=0x46; c[m++]=0x28;
                c[m++]=0x0F; c[m++]=0xB6; c[m++]=0x80;
                { unsigned int d = 0x1310; memcpy(c + m, &d, 4); m += 4; }
                c[m++]=0x88; c[m++]=0x05;
                { int r2 = (int)((long long)(stub + IPR_LAST1310) - (long long)(c + m + 4));
                  memcpy(c + m, &r2, 4); m += 4; }
                c[js1] = (unsigned char)(m - (js1 + 1));
                c[m++]=0x58;                                     /* pop rax           */
            }
            memcpy(c + m, s2, 7); m += 7;                    /* the stolen store   */
            c[m++]=0xE9;                                     /* jmp back           */
            rel = (int)((long long)(s2 + 7) - (long long)(c + m + 4));
            memcpy(c + m, &rel, 4); m += 4;

            if (m > IPR_CAVE_SZ) {
                log_line("INPUTPROBE: stub for 0x%X is %d bytes, slot is %d -- NOT installed",
                         sites[k], m, IPR_CAVE_SZ);
                continue;
            }
            if (VirtualProtect(s2, 7, PAGE_EXECUTE_READWRITE, &old)) {
                rel = (int)((long long)c - (long long)(s2 + 5));
                s2[0] = 0xE9; memcpy(s2 + 1, &rel, 4);
                s2[5] = 0x90; s2[6] = 0x90;
                VirtualProtect(s2, 7, old, &old);
                installed++;
            }
        }
        log_line("INPUTPROBE: counting %d of %d command emit sites", installed, nsites);
    }

    log_line("INPUTPROBE: installed at 0x%X, stub at %p -- the mask block will be "
             "printed every 30s", IPR_HOOK_RVA, (void*)stub);
}

/* ================= PART 22: Hoho must not fire the catch-all =========
 *
 *  MEASURED, not reasoned. The per-command counters (PART 21) over one session
 *  of pressing only Hoho while guarding:
 *
 *      0x16 hoho=+13 | 0x20=+116 0x21=+13 | 0x25=0 0x26=0 0x27=0 0x28=+13
 *
 *  Two things fall out. The dedicated SP commands 0x25/0x26/0x27 are NEVER
 *  emitted -- so the stray SP2 does not come from them. And 0x16, 0x21 and 0x28
 *  move in exact lockstep, so a single press of Hoho pushes the flash step AND
 *  two catch-alls.
 *
 *  0x21 is gated at 0x140412554 on `[r14+0xF4] & esi`, and +0xF4 is not one
 *  button: it reads 0x001E2FF0, a 13-bit union of every action button, and it is
 *  byte-identical under Type A and under a custom scheme -- it ignores the
 *  remap by design, being a superset. So it matches Hoho's button too.
 *
 *  WHY ONLY A CUSTOM SCHEME. Under Type A the same physical button is ALSO
 *  Step/Dash (probe: CC and F0 both read bit 7), so pressing it additionally
 *  emits the step command, which outranks the catch-all and is refused while
 *  guarding -- nothing comes out, which is the wanted behaviour. A scheme that
 *  splits them (CC bit 10, F0 bit 7) emits no step command, the catch-all is
 *  left unopposed, and it resolves into an SP. Confirmed from the other side:
 *  rebinding Step/Dash back onto A makes the stray SP2 stop.
 *
 *  THE FIX. Test `(F4 & ~F0) & esi` instead of `F4 & esi`, so the flash step's
 *  own button no longer counts as "some action button". Every other button keeps
 *  0x21 exactly as before -- this removes nothing else.
 *
 *  Hook 0x140412554, 9 stolen bytes `41 85 B6 F4 00 00 00 74 3F`
 *  (`test dword [r14+0xF4], esi` + `je rel8`). rax is pushed and popped; `pop`
 *  leaves the flags alone, so the test's result still drives the branch.
 *
 *  ! MEASURED INEFFECTIVE 2026-08-31, and turned OFF. With the hook installed,
 *  0x21 still fired 13 times against 16 Hoho presses. The reason is that the
 *  gesture is LT+A: LT is an action button too, so it is also in the +0xF4
 *  union, and masking out A's bit alone leaves LT to trigger the catch-all. The
 *  same is true under Type A, which behaves correctly -- so 0x21 is NOT the
 *  cause. That same run separated the two suspects for the first time:
 *      0x16 hoho=16   0x28=16   0x21=13
 *  0x28 tracks the press exactly; 0x21 does not. Go after 0x28.
 *
 *  ! 0x28 rides along on the same press (+13 as well) and has no gate of its own
 *  -- it is pushed after 0x21's block. If a stray SP survives this, 0x28 is the
 *  next suspect. Deliberately changing ONE thing at a time here. */
#define HCF_HOOK_RVA   0x412554
#define HCF_EMIT_RVA   0x41255D   /* mov word [rsp+0x20], 0x21 */
#define HCF_SKIP_RVA   0x41259C
#define HCF_HOHO_OFF   0xF0
#define HCF_ANY_OFF    0xF4

static void patch_hoho_catchall(void)
{
    static const unsigned char orig[9] =
        {0x41,0x85,0xB6,0xF4,0x00,0x00,0x00,0x74,0x3F};
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    unsigned char* stub;
    unsigned char  b[64];
    int n = 0;
    DWORD old;

    if (!mod) return;
    site = mod + HCF_HOOK_RVA;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("HOHOFIX: the 0x21 gate is not at RVA 0x%X (game updated?) -- skipped",
                 HCF_HOOK_RVA);
        return;
    }
    stub = (unsigned char*)gauge_alloc_near(site, 0x80);
    if (!stub) { log_line("HOHOFIX: no trampoline within +/-2GB -- skipped"); return; }
    memset(stub, 0x90, 0x80);

#define HP32(v)   do { unsigned int _v = (unsigned int)(v);                                   \
                       memcpy(b + n, &_v, 4); n += 4; } while (0)
#define HABS(rva) do { int _v = (int)((long long)(mod + (rva)) - (long long)(stub + n + 4));   \
                       memcpy(b + n, &_v, 4); n += 4; } while (0)

    b[n++]=0x50;                                                /* push rax          */
    b[n++]=0x41; b[n++]=0x8B; b[n++]=0x86; HP32(HCF_HOHO_OFF);  /* mov eax,[r14+F0]  */
    b[n++]=0xF7; b[n++]=0xD0;                                   /* not eax           */
    b[n++]=0x41; b[n++]=0x23; b[n++]=0x86; HP32(HCF_ANY_OFF);   /* and eax,[r14+F4]  */
    b[n++]=0x85; b[n++]=0xF0;                                   /* test eax,esi      */
    b[n++]=0x58;                                                /* pop rax (no flags)*/
    b[n++]=0x0F; b[n++]=0x85; HABS(HCF_EMIT_RVA);               /* jne  emit         */
    b[n++]=0xE9; HABS(HCF_SKIP_RVA);                            /* jmp  skip         */

    if (n > (int)sizeof(b)) { log_line("HOHOFIX: stub overflowed -- skipped"); return; }
#undef HP32
#undef HABS

    memcpy(stub, b, n);

    if (VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        int rel = (int)((long long)stub - (long long)(site + 5));
        site[0] = 0xE9; memcpy(site + 1, &rel, 4);
        memset(site + 5, 0x90, sizeof(orig) - 5);
        VirtualProtect(site, sizeof(orig), old, &old);
    } else { log_line("HOHOFIX: VirtualProtect failed -- skipped"); return; }

    log_line("HOHOFIX: installed -- the flash-step button no longer fires the catch-all "
             "command 0x21 (hook at 0x%X, stub at %p)", HCF_HOOK_RVA, (void*)stub);
}

/* ================= PART 23: drop the flash step's companion 0x28 =====
 *
 *  The Hoho push block ends with `jmp 0x140412634`, and 0x140412634 pushes
 *  command 0x28 with NO gate of its own before falling into 0x140412673. So
 *  every flash step press pushes 0x28 as a companion -- which is exactly what
 *  the per-site counters show: 0x28@0x412634 = 24 against 24 Hoho presses, the
 *  other four 0x28 sites dead at 0.
 *
 *  This is an EXPERIMENT, not a settled fix: it skips the companion outright by
 *  jumping straight to 0x140412673. If the stray SP2 during guard stops and the
 *  flash step still works in neutral, 0x28 is the culprit and the real fix is
 *  the same skip made conditional on guarding. If Hoho breaks, 0x28 is load
 *  bearing and this is the wrong lever.
 *
 *  A 5-byte jump replaces the 7-byte store; no trampoline needed. */
#define HNC_SITE_RVA  0x412634
#define HNC_NEXT_RVA  0x412673

static void patch_hoho_no_companion(void)
{
    static const unsigned char orig[7] = {0x66,0xC7,0x44,0x24,0x20,0x28,0x00};
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    DWORD old;
    int rel;

    if (!mod) return;
    site = mod + HNC_SITE_RVA;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("HOHOCOMP: no `mov word[rsp+0x20],0x28` at RVA 0x%X -- skipped", HNC_SITE_RVA);
        return;
    }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("HOHOCOMP: VirtualProtect failed -- skipped"); return;
    }
    rel = (int)((long long)(mod + HNC_NEXT_RVA) - (long long)(site + 5));
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    site[5] = 0x90; site[6] = 0x90;
    VirtualProtect(site, sizeof(orig), old, &old);
    log_line("HOHOCOMP: installed -- the flash step no longer pushes its companion "
             "command 0x28 (0x%X -> 0x%X)", HNC_SITE_RVA, HNC_NEXT_RVA);
}

/* ================= PART 24: no flash step while guarding =============
 *
 *  Reported: with a custom scheme, pressing Hoho WHILE GUARDING fires SP2. The
 *  wanted behaviour, and what Type A gives, is that nothing comes out until
 *  guard is released.
 *
 *  Three suspects were eliminated by measurement before this one, and each is
 *  recorded so nobody re-tries them:
 *    - cmd 0x21 (the +0xF4 catch-all): masking Hoho's bit out left it firing,
 *      because the gesture is LT+A and LT is in that union too. Fires the same
 *      way under Type A, which is correct. INNOCENT.
 *    - cmd 0x28 (companion pushed unconditionally after the flash step): the
 *      per-site counter went 24 -> 0 with it suppressed and the stray SP2
 *      survived. INNOCENT.
 *    - cmd 0x25/0x26/0x27 (the dedicated SP commands): essentially never
 *      emitted during the repro. INNOCENT.
 *  What is left is 0x16 itself: the fighter receives the flash step while
 *  guarding and resolves it into an SP. Under Type A the same button is also
 *  Step/Dash, so a step command is emitted too, outranks it, and is refused in
 *  guard -- which is why the stock scheme never shows this. Confirmed from the
 *  other side: rebinding Step/Dash onto A makes the stray SP2 stop.
 *
 *  So: do not emit 0x16 at all while the fighter's current command is guard_in.
 *  BrainPad+0x28 is the fighter and +0xFA0 its current command (both proved in
 *  PART 19); 12 = guard_in comes from the measured histogram, not the table.
 *
 *  ! GUARD IS NOT ONE STATE. 12 (guard_in) is only the entry; holding the guard
 *  moves the fighter to command 6, which the command-name table leaves blank and
 *  which two earlier histograms had shown without me following it up. Two
 *  isolated runs, same gesture, opposite results -- `LAST emit: cmd=12` in one
 *  and `cmd=6` in the other -- because the press landed at different points in
 *  the guard. Vetoing only 12 let the second case straight through. Both are
 *  covered now; if a third guard state exists the probe's state recorder will
 *  name it the same way.
 *
 *  ! An earlier run concluded "12 is not the guard state" and this was switched
 *  off. That conclusion came from a session where guard presses and neutral
 *  presses were mixed, so the counters described both at once. An ISOLATED run
 *  -- one Hoho press while guarding, then no input at all -- settled it:
 *      0x16 hoho=1, every SP command 0, and LAST emit: cmd=12
 *  with SP2 confirmed on screen. So the flash step IS emitted while the fighter
 *  is in guard_in, the fighter resolves it into an SP, and 12 is the right
 *  condition. Isolate the repro before reading counters.
 *
 *  Hook 0x1404125E8, 13 stolen bytes -- the same site PART 20 used, and for the
 *  same reason: it is the whole gate, and the `je` inside it is rel8, so the
 *  narrower site cannot take a jmp rel32. Both original emit paths are re-emitted
 *  verbatim, so nothing outside guard changes. */
#define HGV_HOOK_RVA   0x4125E8
#define HGV_EMIT_RVA   0x4125F5
#define HGV_SKIP_RVA   0x412673
#define HGV_FIGHTER    0x28
#define HGV_CURCMD     0xFA0
#define HGV_GUARD_IN   12   /* entering the guard                            */
#define HGV_GUARD_LO   5    /* the guard FAMILY: commands 5..8 all share one */
#define HGV_GUARD_HI   8    /* blank entry in the name table, and 6 and 7 were
                               each measured as a guard state on their own. A
                               range beats adding them one at a time: vetoing 12
                               alone let 6 through, then 6 let 7 through. */

static void patch_hoho_guard_veto(void)
{
    static const unsigned char orig[13] =
        {0x41,0x85,0xB6,0xF0,0x00,0x00,0x00,0x75,0x04,0x84,0xDB,0x74,0x7E};
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    unsigned char* stub;
    unsigned char  b[128];
    int n = 0, j_orig, j_veto, j_veto2, j_e1, j_s1, sk;
    DWORD old;

    if (!mod) return;
    site = mod + HGV_HOOK_RVA;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("HOHOGUARD: the flash-step gate is not at RVA 0x%X -- skipped", HGV_HOOK_RVA);
        return;
    }
    stub = (unsigned char*)gauge_alloc_near(site, 0x100);
    if (!stub) { log_line("HOHOGUARD: no trampoline within +/-2GB -- skipped"); return; }
    memset(stub, 0x90, 0x100);

#define GP32(v)   do { unsigned int _v=(unsigned int)(v); memcpy(b+n,&_v,4); n+=4; } while (0)
#define GABS(rva) do { int _v=(int)((long long)(mod+(rva))-(long long)(stub+n+4));            \
                       memcpy(b+n,&_v,4); n+=4; } while (0)

    b[n++]=0x50; b[n++]=0x51;                                   /* push rax, rcx      */
    b[n++]=0x49; b[n++]=0x8B; b[n++]=0x46; b[n++]=HGV_FIGHTER;  /* mov rax,[r14+0x28] */
    b[n++]=0x48; b[n++]=0x85; b[n++]=0xC0;                      /* test rax,rax       */
    b[n++]=0x74; j_orig = n++;                                  /* je  L_orig         */
    b[n++]=0x0F; b[n++]=0xB6; b[n++]=0x88; GP32(HGV_CURCMD);    /* movzx ecx,[rax+FA0]*/
    b[n++]=0x80; b[n++]=0xF9; b[n++]=HGV_GUARD_IN;              /* cmp cl,12          */
    b[n++]=0x74; j_veto = n++;                                  /* je  L_veto         */
    b[n++]=0x8D; b[n++]=0x41; b[n++]=(unsigned char)(0x100 - HGV_GUARD_LO);
    b[n++]=0x83; b[n++]=0xF8; b[n++]=(HGV_GUARD_HI - HGV_GUARD_LO);
    b[n++]=0x76; j_veto2 = n++;                                 /* jbe L_veto (5..8)  */
    b[j_orig] = (unsigned char)(n - (j_orig + 1));              /* L_orig:            */
    b[n++]=0x59; b[n++]=0x58;                                   /* pop rcx, rax       */
    b[n++]=0x41; b[n++]=0x85; b[n++]=0xB6; GP32(HGV_HOOK_RVA - HGV_HOOK_RVA + 0xF0);
                                                                /* test [r14+0xF0],esi*/
    b[n++]=0x0F; b[n++]=0x85; j_e1 = n; n += 4;                 /* jne EMIT           */
    b[n++]=0x84; b[n++]=0xDB;                                   /* test bl,bl         */
    b[n++]=0x0F; b[n++]=0x84; j_s1 = n; n += 4;                 /* je  SKIP           */
    { int r = n - (j_e1 + 4); memcpy(b + j_e1, &r, 4); }
    b[n++]=0xE9; GABS(HGV_EMIT_RVA);
    b[j_veto]  = (unsigned char)(n - (j_veto  + 1));            /* L_veto:            */
    b[j_veto2] = (unsigned char)(n - (j_veto2 + 1));
    b[n++]=0x59; b[n++]=0x58;                                   /* pop rcx, rax       */
    sk = n;
    b[n++]=0xE9; GABS(HGV_SKIP_RVA);
    { int r = sk - (j_s1 + 4); memcpy(b + j_s1, &r, 4); }
    /* exactly one pop runs per path: the veto path takes the one at L_veto, every
       other path the one at L_orig. A raw push/pop count looks unbalanced here. */

    if (n > (int)sizeof(b)) { log_line("HOHOGUARD: stub overflowed -- skipped"); return; }
#undef GP32
#undef GABS
    memcpy(stub, b, n);

    if (VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        int rel = (int)((long long)stub - (long long)(site + 5));
        site[0] = 0xE9; memcpy(site + 1, &rel, 4);
        memset(site + 5, 0x90, sizeof(orig) - 5);
        VirtualProtect(site, sizeof(orig), old, &old);
    } else { log_line("HOHOGUARD: VirtualProtect failed -- skipped"); return; }

    log_line("HOHOGUARD: installed -- the flash step is not emitted while guarding "
             "(hook at 0x%X, stub at %p)", HGV_HOOK_RVA, (void*)stub);
}

/* ================= PART 25: no SP move out of guard ==================
 *
 *  THE reported bug: with a custom scheme, holding the SP trigger and pressing
 *  the Hoho button WHILE GUARDING fires Spiritual Pressure Move 2. Correct
 *  behaviour, and what Type A gives, is that nothing comes out until guard is
 *  released.
 *
 *  Isolated in-game measurement, one variable at a time, counters reset between
 *  runs -- the three rows are what finally identified it:
 *
 *      in guard, SP trigger alone .................. 0x26@0x4126C4 = 0
 *      in guard, Hoho button alone ................. 0x26@0x4126C4 = 0
 *      in guard, BOTH (the repro) .................. 0x26@0x4126C4 = 21, SP2 on screen
 *
 *  So neither button opens the gate; the COMBINATION does. `test [r14+0x104],
 *  r12d` at 0x1404126BB reads +0x104 = 0x10 (bit 4, constant across schemes) and
 *  r12d = 0x910 at the emission -- so r12d is a mask of SATISFIED BINDINGS, not
 *  of physical buttons, and bit 4 lights when the LT+button combo is satisfied.
 *  That combo satisfies two actions at once: Hoho, and whatever +0x104 is, which
 *  emits an SP command. Outside guard Hoho wins; in guard it is refused and the
 *  SP one goes through. Consistent with the user's own finding that rebinding
 *  Step/Dash onto that button makes the bug disappear.
 *
 *  Four earlier fixes failed because they all targeted the flash step (0x21,
 *  0x28, vetoing 0x16 on guard_in, then on the whole guard range). PART 24 does
 *  now correctly stop the flash step in guard -- verified, and worth keeping --
 *  but it was never the source of the SP2.
 *
 *  Guard is a RANGE, not a state: commands 5..8 (one shared blank name-table
 *  entry) plus 12 (guard_in). Measured -- vetoing 12 alone let 6 through, then 6
 *  let 7 through.
 *
 *  ! REVERTED. In game this blocked a LEGITIMATE mechanic: with it on, holding
 *  guard and inputting SP2 (LT + its own button) no longer produced SP2 -- the
 *  Kikon came out instead. So 0x26@0x4126C4 is SP2's NORMAL emission, and
 *  suppressing every SP while guarding is far too broad. The reported bug also
 *  survived it untouched.
 *
 *  ! What that regression proves, and it is the useful part: the stray SP2 does
 *  NOT come from this site. Blocking emissions is the wrong shape of fix here --
 *  each emission site is also a legitimate move. The defect is that ONE combo
 *  (SP trigger + the Hoho button) satisfies TWO action bindings at once, so the
 *  fix has to be at the binding level, not by vetoing an emission that other
 *  inputs legitimately need.
 *
 *  Hook 0x1404126BB, 9 stolen bytes `45 85 A6 04 01 00 00 74 3F`. */
#define SGV_HOOK_RVA   0x4126BB
#define SGV_EMIT_RVA   0x4126C4   /* mov word [rsp+0x20], 0x26 */
#define SGV_SKIP_RVA   0x412703
#define SGV_MASK_OFF   0x104

static void patch_sp_guard_veto(void)
{
    static const unsigned char orig[9] =
        {0x45,0x85,0xA6,0x04,0x01,0x00,0x00,0x74,0x3F};
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    unsigned char* stub;
    unsigned char  b[128];
    int n = 0, j_orig, j_v1, j_v2, j_e, j_s, sk;
    DWORD old;

    if (!mod) return;
    site = mod + SGV_HOOK_RVA;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("SPGUARD: the SP gate is not at RVA 0x%X (game updated?) -- skipped",
                 SGV_HOOK_RVA);
        return;
    }
    stub = (unsigned char*)gauge_alloc_near(site, 0x100);
    if (!stub) { log_line("SPGUARD: no trampoline within +/-2GB -- skipped"); return; }
    memset(stub, 0x90, 0x100);

#define SP32(v)   do { unsigned int _v=(unsigned int)(v); memcpy(b+n,&_v,4); n+=4; } while (0)
#define SABS(rva) do { int _v=(int)((long long)(mod+(rva))-(long long)(stub+n+4));            \
                       memcpy(b+n,&_v,4); n+=4; } while (0)

    b[n++]=0x50; b[n++]=0x51;                                   /* push rax, rcx      */
    b[n++]=0x49; b[n++]=0x8B; b[n++]=0x46; b[n++]=HGV_FIGHTER;  /* mov rax,[r14+0x28] */
    b[n++]=0x48; b[n++]=0x85; b[n++]=0xC0;                      /* test rax,rax       */
    b[n++]=0x74; j_orig = n++;                                  /* je  L_orig         */
    b[n++]=0x0F; b[n++]=0xB6; b[n++]=0x88; SP32(HGV_CURCMD);    /* movzx ecx,[rax+FA0]*/
    b[n++]=0x80; b[n++]=0xF9; b[n++]=HGV_GUARD_IN;              /* cmp cl,12          */
    b[n++]=0x74; j_v1 = n++;                                    /* je  L_veto         */
    b[n++]=0x8D; b[n++]=0x41; b[n++]=(unsigned char)(0x100 - HGV_GUARD_LO);
    b[n++]=0x83; b[n++]=0xF8; b[n++]=(HGV_GUARD_HI - HGV_GUARD_LO);
    b[n++]=0x76; j_v2 = n++;                                    /* jbe L_veto (5..8)  */
    b[j_orig] = (unsigned char)(n - (j_orig + 1));              /* L_orig:            */
    b[n++]=0x59; b[n++]=0x58;                                   /* pop rcx, rax       */
    b[n++]=0x45; b[n++]=0x85; b[n++]=0xA6; SP32(SGV_MASK_OFF);  /* test [r14+104],r12d*/
    b[n++]=0x0F; b[n++]=0x84; j_s = n; n += 4;                  /* je  SKIP           */
    b[n++]=0xE9; j_e = n; n += 4;                               /* jmp EMIT           */
    b[j_v1] = (unsigned char)(n - (j_v1 + 1));                  /* L_veto:            */
    b[j_v2] = (unsigned char)(n - (j_v2 + 1));
    b[n++]=0x59; b[n++]=0x58;                                   /* pop rcx, rax       */
    sk = n;
    b[n++]=0xE9; SABS(SGV_SKIP_RVA);
    { int r = sk - (j_s + 4); memcpy(b + j_s, &r, 4); }
    { int r = (int)((long long)(mod + SGV_EMIT_RVA) - (long long)(stub + j_e + 4));
      memcpy(b + j_e, &r, 4); }

    if (n > (int)sizeof(b)) { log_line("SPGUARD: stub overflowed -- skipped"); return; }
#undef SP32
#undef SABS
    memcpy(stub, b, n);

    if (VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        int rel = (int)((long long)stub - (long long)(site + 5));
        site[0] = 0xE9; memcpy(site + 1, &rel, 4);
        memset(site + 5, 0x90, sizeof(orig) - 5);
        VirtualProtect(site, sizeof(orig), old, &old);
    } else { log_line("SPGUARD: VirtualProtect failed -- skipped"); return; }

    log_line("SPGUARD: installed -- no SP move is emitted while guarding "
             "(hook at 0x%X, stub at %p)", SGV_HOOK_RVA, (void*)stub);
}

static void patch_fast_boot(void)
{
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    if (!mod) return;
    unsigned char* p = mod + FASTBOOT_JMPTBL_RVA + 12 * 4;

    /* slots 12,13,14,15 = 0x7501BB, 0x7501DB, 0x74FFC1, 0x750310 */
    static const unsigned char orig[16] = {0xBB,0x01,0x75,0x00, 0xDB,0x01,0x75,0x00,
                                           0xC1,0xFF,0x74,0x00, 0x10,0x03,0x75,0x00};
    /* slot 13 -> state 15's handler */
    static const unsigned char repl[4]  = {0x10,0x03,0x75,0x00};

    if (memcmp(p + 4, repl, sizeof(repl)) == 0) {
        log_line("FASTBOOT: slot 13 already points at state 15 -- nothing to do");
        return;
    }
    if (memcmp(p, orig, sizeof(orig)) != 0) {
        log_line("FASTBOOT: SLogo::Update jump table not as expected at RVA 0x%X "
                 "(game updated?) -- skipped, the auto-save notice still shows",
                 FASTBOOT_JMPTBL_RVA);
        return;
    }
    DWORD old;
    if (VirtualProtect(p + 4, sizeof(repl), PAGE_EXECUTE_READWRITE, &old)) {
        memcpy(p + 4, repl, sizeof(repl));
        VirtualProtect(p + 4, sizeof(repl), old, &old);
        FlushInstructionCache(GetCurrentProcess(), p + 4, sizeof(repl));
        log_line("FASTBOOT: applied at RVA 0x%X -- SLogo state 13 (AUTO_SAVE notice) "
                 "now runs state 15 (scene done); boot goes logos -> title with no click",
                 FASTBOOT_SLOT13_RVA);
    } else {
        log_line("FASTBOOT: VirtualProtect failed at RVA 0x%X", FASTBOOT_SLOT13_RVA);
    }
}
/* ================= PART 26: run throw-tech probe (DIAGNOSTIC) ========
 *
 *  Reported: you cannot tech a throw while RUNNING. Standing, back-dashing
 *  and side-stepping all tech fine. Vanilla behaviour, not ours.
 *
 *  What is already established (DataChakka
 *  guides/Nilsix researches/Run Throw Tech/BROS_RUN_THROW_TECH.md):
 *
 *    * The tech is the grab clash, node atk_gr02_1, clash_parry_type 1/2.
 *    * Its two live windows are fighter+0x5F4 (normal) and +0x5F8 (guard),
 *      3 frames each.
 *    * They are armed in ONE place, SceneMessage::SetAdditionalData
 *      (shipped RVA 0x479AF0), case 15, and only when the fighter's current
 *      action name contains the substring "dam_gr".
 *    * case 26 (a clash_parry node) zeroes both; case 8 (actDashClash)
 *      never touches them.
 *    * The data side is CLOSED and negative -- in_stepdash is 0 on every
 *      grab-clash node and 0 already means "ignore the dash state", so no
 *      .tcmbpkg edit can reach this.
 *
 *  The open question is exactly two candidates, and this probe separates them:
 *  a grabbed run either never reaches a dam_gr action, or it arrives at the
 *  transition handler with a category other than 15.
 *
 *  TWO HOOKS, both read-only -- nothing here changes behaviour.
 *
 *  A. RVA 0x479AF0, the function entry, 5 bytes stolen
 *     (40 55 53 56 57 = push rbp/rbx/rsi/rdi -- exactly 5, no padding).
 *     Records the NEW category (dl), the PREVIOUS category (param_5, the 5th
 *     argument, at [rbp+0x30] once the stub has pushed rbp), the fighter
 *     (scene+0xBB0) and both windows as they stand BEFORE the transition.
 *     This is the measurement that answers the question outright: if a grabbed
 *     run arrives as 8 rather than 15, the fix is in the classifier at
 *     0x425A20, not in the arming code.
 *
 *  B. RVA 0x47B846, inside case 15, 7 bytes stolen
 *     (48 8B D8 48 8D 4D 10 = mov rbx,rax / lea rcx,[rbp+0x10]).
 *     This sits immediately after the "dam_gr" substring call returns and
 *     BEFORE the std::string at [rbp+0x10] is destroyed one instruction later,
 *     so it can read the action name verbatim along with the match result
 *     (-1 = no match = no window armed). Every volatile register is dead here
 *     except rax -- the site is the instruction after a call -- which is what
 *     makes a mid-function hook safe at this one address.
 *
 *  Both rings are drained by a watcher thread; the stubs themselves only write
 *  memory, so no file I/O happens on a game thread. The watcher also polls the
 *  last fighter seen for a window going non-zero, which is the direct evidence
 *  that a window was armed at all.
 *
 *  HOW TO READ IT. Get grabbed three times with no other input -- once out of
 *  a run, once standing, once out of a side-step -- and compare. The side-step
 *  is the control: it techs correctly, so it separates "the run is special"
 *  from "movement is special".
 * ==================================================================== */
#define TTP_ENTRY_RVA  0x479AF0u   /* SceneMessage::SetAdditionalData         */
#define TTP_NAME_RVA   0x47B846u   /* case 15, just after the "dam_gr" test   */
#define TTP_FIGHTER    0xBB0u      /* scene+0xBB0 -> the fighter              */
#define TTP_WIN_N      0x5F4u      /* clash_parry_normal_frame lives here     */
#define TTP_WIN_G      0x5F8u      /* clash_parry_guard_frame                 */

#define TTP_NEV   256              /* transition ring (power of two)          */
#define TTP_NNM    64              /* action-name ring (power of two)         */

typedef struct {
    unsigned long long seq;        /* written LAST -- 0 means "not complete"  */
    void*              fighter;
    float              win_n;      /* +0x5F4 as it stood BEFORE the transition */
    float              win_g;      /* +0x5F8, ditto                            */
    unsigned char      newcat;
    unsigned char      prevcat;
} ttp_ev;

typedef struct {
    unsigned long long seq;        /* written LAST                            */
    long long          found;      /* the "dam_gr" match, -1 = not found      */
    char               name[56];
} ttp_nm;

static ttp_ev g_ttp_ev[TTP_NEV];
static ttp_nm g_ttp_nm[TTP_NNM];
static volatile LONG      g_ttp_ev_idx = 0;
static volatile LONG      g_ttp_nm_idx = 0;
static volatile LONGLONG  g_ttp_ev_seq = 0;
static volatile LONGLONG  g_ttp_nm_seq = 0;
static void* volatile     g_ttp_fighter = NULL;
static int                g_ttp_on = 0;

/* the categories this investigation already has names for */
static const char* ttp_cat(unsigned int c)
{
    switch (c) {
        case 5:    return "sp_break+charge";
        case 8:    return "actDashClash";
        case 15:   return "ARMING CASE";
        case 26:   return "clash_parry (zeroes)";
        case 0xFF: return "none";
        default:   return "";
    }
}

/* Hook A payload. rcx = the SceneMessage, dl = the new category, r9b = the
   previous category (param_5, moved into r9 by the stub). r8 is param_3 and
   is named only so the argument lands in the right slot. */
static void ttp_transition(void* scene, char newcat, void* p3, unsigned int prevcat)
{
    unsigned char* f;
    LONG i;
    (void)p3;
    if (!scene) return;
    i = (InterlockedIncrement(&g_ttp_ev_idx) - 1) & (TTP_NEV - 1);
    g_ttp_ev[i].seq     = 0;
    g_ttp_ev[i].newcat  = (unsigned char)newcat;
    g_ttp_ev[i].prevcat = (unsigned char)prevcat;
    g_ttp_ev[i].win_n   = 0.0f;
    g_ttp_ev[i].win_g   = 0.0f;
    f = NULL;
    __try {
        f = *(unsigned char**)((unsigned char*)scene + TTP_FIGHTER);
        if (f) {
            g_ttp_ev[i].win_n = *(float*)(f + TTP_WIN_N);
            g_ttp_ev[i].win_g = *(float*)(f + TTP_WIN_G);
            g_ttp_fighter = f;
        }
    } __except(EXCEPTION_EXECUTE_HANDLER) { f = NULL; }
    g_ttp_ev[i].fighter = f;
    g_ttp_ev[i].seq = (unsigned long long)InterlockedIncrement64(&g_ttp_ev_seq);
}

/* Hook B payload. rcx = the substring result, rdx = the live std::string.
   MSVC's layout is { union { char buf[16]; char* ptr; }; size_t size;
   size_t capacity; } -- capacity >= 16 means the characters are on the heap. */
static void ttp_action_name(long long found, const unsigned char* s)
{
    const char* p;
    size_t cap;
    LONG i;
    int k = 0;
    if (!s) return;
    i = (InterlockedIncrement(&g_ttp_nm_idx) - 1) & (TTP_NNM - 1);
    g_ttp_nm[i].seq   = 0;
    g_ttp_nm[i].found = found;
    g_ttp_nm[i].name[0] = 0;
    __try {
        cap = *(const size_t*)(s + 0x18);
        p   = (cap >= 16) ? *(const char* const*)s : (const char*)s;
        if (p) {
            for (k = 0; k < (int)sizeof(g_ttp_nm[i].name) - 1 && p[k]; k++)
                g_ttp_nm[i].name[k] = p[k];
        }
        g_ttp_nm[i].name[k] = 0;
    } __except(EXCEPTION_EXECUTE_HANDLER) { g_ttp_nm[i].name[0] = 0; }
    g_ttp_nm[i].seq = (unsigned long long)InterlockedIncrement64(&g_ttp_nm_seq);
}

/* Hook A: a function entry, so only the ABI argument registers are live.
   Same shape as gauge_install_hook, plus one instruction that lifts the 5th
   argument off the stack into r9 -- that helper only forwards rcx or rdx. */
static int ttp_install_entry(void)
{
    static const unsigned char orig[5] = {0x40,0x55,0x53,0x56,0x57};
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    unsigned char* stub;
    unsigned char  b[192];
    int n = 0;
    long long rel;
    void* payload = (void*)ttp_transition;
    DWORD old;

    if (!mod) return 0;
    site = mod + TTP_ENTRY_RVA;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("THROWTECH: no SetAdditionalData prologue at RVA 0x%X "
                 "(game updated?) -- probe skipped", TTP_ENTRY_RVA);
        return 0;
    }
    stub = (unsigned char*)gauge_alloc_near(site, 256);
    if (!stub) { log_line("THROWTECH: no trampoline within +/-2GB -- skipped"); return 0; }

    b[n++]=0x55;                                            /* push rbp          */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xE5;                  /* mov  rbp,rsp      */
    b[n++]=0x51;                                            /* push rcx          */
    b[n++]=0x52;                                            /* push rdx          */
    b[n++]=0x41; b[n++]=0x50;                               /* push r8           */
    b[n++]=0x41; b[n++]=0x51;                               /* push r9           */
    b[n++]=0x41; b[n++]=0x52;                               /* push r10          */
    b[n++]=0x41; b[n++]=0x53;                               /* push r11          */
    b[n++]=0x50;                                            /* push rax          */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xE4; b[n++]=0xF0;     /* and  rsp,-16      */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xEC; b[n++]=0x60;     /* sub  rsp,0x60     */
    b[n++]=0x0F; b[n++]=0x11; b[n++]=0x44; b[n++]=0x24; b[n++]=0x20;
    b[n++]=0x0F; b[n++]=0x11; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;
    b[n++]=0x0F; b[n++]=0x11; b[n++]=0x54; b[n++]=0x24; b[n++]=0x40;
    b[n++]=0x0F; b[n++]=0x11; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x50;
    /* param_5 sits at the caller's [rsp+0x28]; the stub was entered by a jmp,
       so rsp was untouched and rbp = entry_rsp - 8 -> [rbp+0x30]. */
    b[n++]=0x44; b[n++]=0x0F; b[n++]=0xB6; b[n++]=0x4D; b[n++]=0x30; /* movzx r9d,byte[rbp+0x30] */
    b[n++]=0x48; b[n++]=0xB8;                               /* mov  rax,imm64    */
    memcpy(b + n, &payload, 8); n += 8;
    b[n++]=0xFF; b[n++]=0xD0;                               /* call rax          */
    b[n++]=0x0F; b[n++]=0x10; b[n++]=0x44; b[n++]=0x24; b[n++]=0x20;
    b[n++]=0x0F; b[n++]=0x10; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;
    b[n++]=0x0F; b[n++]=0x10; b[n++]=0x54; b[n++]=0x24; b[n++]=0x40;
    b[n++]=0x0F; b[n++]=0x10; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x50;
    b[n++]=0x48; b[n++]=0x8D; b[n++]=0x65; b[n++]=0xC8;     /* lea rsp,[rbp-0x38]*/
    b[n++]=0x58;                                            /* pop  rax          */
    b[n++]=0x41; b[n++]=0x5B;                               /* pop  r11          */
    b[n++]=0x41; b[n++]=0x5A;                               /* pop  r10          */
    b[n++]=0x41; b[n++]=0x59;                               /* pop  r9           */
    b[n++]=0x41; b[n++]=0x58;                               /* pop  r8           */
    b[n++]=0x5A;                                            /* pop  rdx          */
    b[n++]=0x59;                                            /* pop  rcx          */
    b[n++]=0x5D;                                            /* pop  rbp          */
    memcpy(b + n, orig, sizeof(orig)); n += (int)sizeof(orig);   /* stolen       */
    rel = (long long)(site + sizeof(orig)) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b + n, &rel, 4); n += 4;

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);

    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("THROWTECH: trampoline out of rel32 range -- skipped");
        return 0;
    }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("THROWTECH: VirtualProtect failed at RVA 0x%X", TTP_ENTRY_RVA);
        return 0;
    }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));
    log_line("THROWTECH: transition hook on RVA 0x%X, 5 bytes stolen", TTP_ENTRY_RVA);
    return 1;
}

/* Hook B: mid-function, one instruction after a call returns, so rax is the
   only live volatile register. The stub saves the volatiles anyway and reads
   the game's own rbp back off the stack to reach the std::string. */
static int ttp_install_name(void)
{
    static const unsigned char orig[7] = {0x48,0x8B,0xD8,0x48,0x8D,0x4D,0x10};
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    unsigned char* stub;
    unsigned char  b[192];
    int n = 0, i;
    long long rel;
    void* payload = (void*)ttp_action_name;
    DWORD old;

    if (!mod) return 0;
    site = mod + TTP_NAME_RVA;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("THROWTECH: no `mov rbx,rax / lea rcx,[rbp+0x10]` at RVA 0x%X "
                 "-- the action name will not be logged", TTP_NAME_RVA);
        return 0;
    }
    stub = (unsigned char*)gauge_alloc_near(site, 256);
    if (!stub) { log_line("THROWTECH: no trampoline for the name hook -- skipped"); return 0; }

    b[n++]=0x50;                                            /* push rax  (found) */
    b[n++]=0x51;                                            /* push rcx          */
    b[n++]=0x52;                                            /* push rdx          */
    b[n++]=0x41; b[n++]=0x50;                               /* push r8           */
    b[n++]=0x41; b[n++]=0x51;                               /* push r9           */
    b[n++]=0x41; b[n++]=0x52;                               /* push r10          */
    b[n++]=0x41; b[n++]=0x53;                               /* push r11          */
    b[n++]=0x55;                                            /* push rbp          */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xE5;                  /* mov  rbp,rsp      */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xE4; b[n++]=0xF0;     /* and  rsp,-16      */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xEC; b[n++]=0x30;     /* sub  rsp,0x30     */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x4D; b[n++]=0x38;     /* mov rcx,[rbp+0x38] -- saved rax */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x55; b[n++]=0x00;     /* mov rdx,[rbp]      -- game rbp  */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xC2; b[n++]=0x10;     /* add rdx,0x10       -- &string   */
    b[n++]=0x48; b[n++]=0xB8;                               /* mov rax,imm64      */
    memcpy(b + n, &payload, 8); n += 8;
    b[n++]=0xFF; b[n++]=0xD0;                               /* call rax           */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xEC;                  /* mov rsp,rbp        */
    b[n++]=0x5D;                                            /* pop rbp            */
    b[n++]=0x41; b[n++]=0x5B;                               /* pop r11            */
    b[n++]=0x41; b[n++]=0x5A;                               /* pop r10            */
    b[n++]=0x41; b[n++]=0x59;                               /* pop r9             */
    b[n++]=0x41; b[n++]=0x58;                               /* pop r8             */
    b[n++]=0x5A;                                            /* pop rdx            */
    b[n++]=0x59;                                            /* pop rcx            */
    b[n++]=0x58;                                            /* pop rax            */
    memcpy(b + n, orig, sizeof(orig)); n += (int)sizeof(orig);
    rel = (long long)(site + sizeof(orig)) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b + n, &rel, 4); n += 4;

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);

    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("THROWTECH: name trampoline out of rel32 range -- skipped");
        return 0;
    }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("THROWTECH: VirtualProtect failed at RVA 0x%X", TTP_NAME_RVA);
        return 0;
    }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    for (i = 5; i < (int)sizeof(orig); i++) site[i] = 0x90;
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));
    log_line("THROWTECH: action-name hook on RVA 0x%X, 7 bytes stolen", TTP_NAME_RVA);
    return 1;
}

/* ---- PART 27: the CONSUMER of the window, and its two extra conditions ----
 *
 *  PART 26 measured that run, standing and side-step all arm +0x5F4 to 3.00
 *  with the action "dam_gr02". So the arming is not what the run loses, and
 *  the question moved to who READS the window.
 *
 *  Found by scanning every SSE access to the two fields in .text -- 33 of them,
 *  and only this one reads the pair together:
 *
 *      0x424A51  mov   rax,[rdx+0xBB0]        ; the fighter, same +0xBB0
 *      0x424A58  movss xmm0,[rax+0x5F8]       ; guard window
 *                comiss xmm0,xmm6             ; xmm6 = 0.0
 *                jbe   .normal
 *                cmp   byte [rdx+0x1288],0
 *                je    .normal
 *                cmp   byte [rax+0x6F8],0
 *                je    0x424AC9               ; GRANTED
 *      .normal:  movss xmm0,[rax+0x5F4]       ; normal window
 *                comiss xmm0,xmm6
 *                jbe   .blocked
 *                cmp   byte [rdx+0x1288],0
 *                je    .blocked
 *                cmp   byte [rax+0x6F8],0
 *                je    0x424AC9               ; GRANTED
 *      .blocked: cmp   byte [rdx+0x10DE],0 / jne reject
 *                movss xmm0,[rdx+0x10E0] / comiss / ja reject
 *                movss xmm0,[rdx+0x10F4] / comiss / ja reject
 *
 *  ★★ The window is an OVERRIDE, not the permission itself. When it is live it
 *  short-circuits the three blocking tests at .blocked and lets the input
 *  through while you are being grabbed. But the override needs THREE things:
 *
 *      1. a window > 0          -- PART 26 proved this is true for the run
 *      2. owner+0x1288  != 0
 *      3. fighter+0x6F8 == 0    <- the suspect
 *
 *  If running leaves +0x6F8 non-zero, the window is armed and the override is
 *  refused anyway. That is the symptom exactly, and it is why no .tcmbpkg edit
 *  can reach it.
 *
 *  The hook steals the 8-byte movss at 0x424A58, where rax is already the
 *  fighter and rdx the owner. Verified before writing: 24 linear sweeps from
 *  different offsets all decode that address as one 8-byte movss, and none of
 *  the 381 branch targets in the function lands inside the stolen bytes.
 *
 *  This gate runs every frame, so the payload records ONLY the frames where a
 *  window is actually live -- about twelve per grab -- and the watcher collapses
 *  runs of identical readings. */
#define TTG_HOOK_RVA   0x424A58u
#define TTG_F_BLOCK    0x6F8u      /* fighter+0x6F8, must be 0 to be granted   */
#define TTG_O_ALLOW    0x1288u     /* owner+0x1288, must be non-zero           */
#define TTG_NGT   128

typedef struct {
    unsigned long long seq;        /* written LAST                            */
    void*              fighter;
    float              win_n;
    float              win_g;
    unsigned char      f_block;    /* fighter+0x6F8                           */
    unsigned char      o_allow;    /* owner+0x1288                            */
    unsigned char      granted;    /* what the three tests add up to          */
} ttp_gt;

static ttp_gt g_ttp_gt[TTG_NGT];
static volatile LONG     g_ttp_gt_idx = 0;
static volatile LONGLONG g_ttp_gt_seq = 0;

/* rcx = the fighter (the site's rax), rdx = the owner (the site's rdx). */
static void ttp_gate(unsigned char* fighter, unsigned char* owner)
{
    float wn, wg;
    unsigned char fb, oa;
    LONG i;
    if (!fighter || !owner) return;
    __try {
        wg = *(float*)(fighter + TTP_WIN_G);
        wn = *(float*)(fighter + TTP_WIN_N);
        if (wn <= 0.0f && wg <= 0.0f) return;     /* only the live frames */
        fb = *(fighter + TTG_F_BLOCK);
        oa = *(owner + TTG_O_ALLOW);
    } __except(EXCEPTION_EXECUTE_HANDLER) { return; }
    i = (InterlockedIncrement(&g_ttp_gt_idx) - 1) & (TTG_NGT - 1);
    g_ttp_gt[i].seq     = 0;
    g_ttp_gt[i].fighter = fighter;
    g_ttp_gt[i].win_n   = wn;
    g_ttp_gt[i].win_g   = wg;
    g_ttp_gt[i].f_block = fb;
    g_ttp_gt[i].o_allow = oa;
    g_ttp_gt[i].granted = (unsigned char)((oa != 0) && (fb == 0));
    g_ttp_gt[i].seq = (unsigned long long)InterlockedIncrement64(&g_ttp_gt_seq);
}

static int ttp_install_gate(void)
{
    static const unsigned char orig[8] = {0xF3,0x0F,0x10,0x80,0xF8,0x05,0x00,0x00};
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    unsigned char* stub;
    unsigned char  b[224];
    int n = 0, i;
    long long rel;
    void* payload = (void*)ttp_gate;
    DWORD old;

    if (!mod) return 0;
    site = mod + TTG_HOOK_RVA;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("THROWTECH: no `movss xmm0,[rax+0x5F8]` at RVA 0x%X "
                 "-- the gate will not be logged", TTG_HOOK_RVA);
        return 0;
    }
    stub = (unsigned char*)gauge_alloc_near(site, 256);
    if (!stub) { log_line("THROWTECH: no trampoline for the gate hook -- skipped"); return 0; }

    b[n++]=0x50;                                            /* push rax  (fighter) */
    b[n++]=0x51;                                            /* push rcx            */
    b[n++]=0x52;                                            /* push rdx  (owner)   */
    b[n++]=0x41; b[n++]=0x50;                               /* push r8             */
    b[n++]=0x41; b[n++]=0x51;                               /* push r9             */
    b[n++]=0x41; b[n++]=0x52;                               /* push r10            */
    b[n++]=0x41; b[n++]=0x53;                               /* push r11            */
    b[n++]=0x55;                                            /* push rbp            */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xE5;                  /* mov  rbp,rsp        */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xE4; b[n++]=0xF0;     /* and  rsp,-16        */
    b[n++]=0x48; b[n++]=0x81; b[n++]=0xEC;                  /* sub  rsp,0x80       */
    { unsigned int fr = 0x80; memcpy(b + n, &fr, 4); n += 4; }
    /* xmm0-5 are volatile and this is mid-function, so all six are saved.
       xmm6 holds the 0.0 the comiss compares against and is callee-saved. */
    b[n++]=0x0F; b[n++]=0x11; b[n++]=0x44; b[n++]=0x24; b[n++]=0x20;
    b[n++]=0x0F; b[n++]=0x11; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;
    b[n++]=0x0F; b[n++]=0x11; b[n++]=0x54; b[n++]=0x24; b[n++]=0x40;
    b[n++]=0x0F; b[n++]=0x11; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x50;
    b[n++]=0x0F; b[n++]=0x11; b[n++]=0x64; b[n++]=0x24; b[n++]=0x60;
    b[n++]=0x0F; b[n++]=0x11; b[n++]=0x6C; b[n++]=0x24; b[n++]=0x70;
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x4D; b[n++]=0x38;     /* mov rcx,[rbp+0x38] fighter */
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x55; b[n++]=0x28;     /* mov rdx,[rbp+0x28] owner   */
    b[n++]=0x48; b[n++]=0xB8;                               /* mov rax,imm64       */
    memcpy(b + n, &payload, 8); n += 8;
    b[n++]=0xFF; b[n++]=0xD0;                               /* call rax            */
    b[n++]=0x0F; b[n++]=0x10; b[n++]=0x44; b[n++]=0x24; b[n++]=0x20;
    b[n++]=0x0F; b[n++]=0x10; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;
    b[n++]=0x0F; b[n++]=0x10; b[n++]=0x54; b[n++]=0x24; b[n++]=0x40;
    b[n++]=0x0F; b[n++]=0x10; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x50;
    b[n++]=0x0F; b[n++]=0x10; b[n++]=0x64; b[n++]=0x24; b[n++]=0x60;
    b[n++]=0x0F; b[n++]=0x10; b[n++]=0x6C; b[n++]=0x24; b[n++]=0x70;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xEC;                  /* mov rsp,rbp         */
    b[n++]=0x5D;                                            /* pop rbp             */
    b[n++]=0x41; b[n++]=0x5B;                               /* pop r11             */
    b[n++]=0x41; b[n++]=0x5A;                               /* pop r10             */
    b[n++]=0x41; b[n++]=0x59;                               /* pop r9              */
    b[n++]=0x41; b[n++]=0x58;                               /* pop r8              */
    b[n++]=0x5A;                                            /* pop rdx             */
    b[n++]=0x59;                                            /* pop rcx             */
    b[n++]=0x58;                                            /* pop rax             */
    memcpy(b + n, orig, sizeof(orig)); n += (int)sizeof(orig);
    rel = (long long)(site + sizeof(orig)) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b + n, &rel, 4); n += 4;

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);

    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("THROWTECH: gate trampoline out of rel32 range -- skipped");
        return 0;
    }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("THROWTECH: VirtualProtect failed at RVA 0x%X", TTG_HOOK_RVA);
        return 0;
    }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    for (i = 5; i < (int)sizeof(orig); i++) site[i] = 0x90;
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));
    log_line("THROWTECH: gate hook on RVA 0x%X, 8 bytes stolen -- logging "
             "fighter+0x6F8 and owner+0x1288 on every frame a window is live",
             TTG_HOOK_RVA);
    return 1;
}

/* ---- PART 28: which commands are emitted while the window is live? --------
 *
 *  Where PART 27 left it: run, standing and side-step all arm +0x5F4 to 3.00
 *  AND all three are GRANTED by the override at 0x424A58 -- same
 *  fighter+0x6F8=0, same owner+0x1288=1. Yet only standing and side-step reach
 *  cat 26 (the clash_parry node). In the run case no transition happens at all
 *  between being grabbed and being thrown.
 *
 *  That leaves exactly two possibilities, because a REFUSED command produces no
 *  transition either:
 *      (a) the tech button emits no command at all in the run-derived state
 *      (b) it emits one and the action lookup refuses the node
 *
 *  Commands are pushed into a vector as 6-byte records, one `mov word
 *  [rsp+0x20], <id>` per emit site. There are FORTY such sites in
 *  BrainPad::vfunc2 carrying 21 distinct ids -- enumerated from the binary
 *  rather than guessed, because PART 20 assumed one site was the only one and
 *  paid a full test cycle for it.
 *
 *  Every site gets a counter. The watcher snapshots all 21 counters when a
 *  window arms and reports the deltas when it expires, so one grab prints the
 *  exact command traffic of its own window. Run against standing:
 *      - a command present standing and missing in the run  -> (a), and the
 *        delta names the id
 *      - identical traffic in both                          -> (b), and the
 *        next hook goes on the consumer of that vector
 *
 *  ⚠ The counters are process-wide, so the opponent's commands are in them too.
 *  That is a constant background across both tests, and the comparison is
 *  between two windows -- but do not read a single delta as "the player pressed
 *  this N times".
 *
 *  Each stub is `pushfq / inc [rip+slot] / popfq` before the stolen 7 bytes.
 *  The flag save is not decoration: six of the forty sites are followed by a
 *  `je`, so the flags are live there. Counters live INSIDE the cave, which is
 *  allocated near the game module -- a rip-relative inc reaching into this
 *  DLL's own .data would be outside rel32 range and is not assumed to work. */
#define TCM_NSLOT   64          /* ids run to 0x2A                            */
#define TCM_CODE    0x100       /* counters occupy [0, 0x100), code after it   */
#define TCM_STRIDE  24          /* bytes per stub                              */

static const struct { unsigned int rva; unsigned char cmd; } g_tcm_emit[] = {
    {0x411392,0x1F},{0x4115D7,0x1F},{0x41188A,0x23},{0x41190C,0x23},
    {0x411A4C,0x03},{0x411BF4,0x04},{0x411D68,0x0C},{0x411DAD,0x09},
    {0x411E4E,0x24},{0x411F5C,0x0A},{0x412060,0x0A},{0x4120C7,0x05},
    {0x4121AD,0x05},{0x412206,0x06},{0x41228B,0x08},{0x41230F,0x07},
    {0x41255D,0x21},{0x4125A9,0x20},{0x4125F5,0x16},{0x412634,0x28},
    {0x41267C,0x25},{0x4126C4,0x26},{0x41276D,0x20},{0x4127F9,0x16},
    {0x412838,0x28},{0x4129B0,0x25},{0x412B20,0x26},{0x412BAB,0x27},
    {0x412D00,0x16},{0x412D3F,0x28},{0x412DE6,0x25},{0x412E8D,0x26},
    {0x412F34,0x27},{0x412FA5,0x28},{0x413061,0x28},{0x413101,0x22},
    {0x4131FB,0x22},{0x413278,0x22},{0x4133F8,0x2A},{0x41353E,0x22},
};
#define TCM_NSITE ((int)(sizeof(g_tcm_emit)/sizeof(g_tcm_emit[0])))

static unsigned char* g_tcm_cave = NULL;

static void patch_throwtech_commands(void)
{
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* cave;
    int k, done = 0, skipped = 0;
    DWORD old;

    if (!mod) return;
    cave = (unsigned char*)gauge_alloc_near(mod + g_tcm_emit[0].rva,
                                            TCM_CODE + TCM_NSITE * TCM_STRIDE + 16);
    if (!cave) { log_line("THROWTECH/cmd: no cave within +/-2GB -- command counting skipped"); return; }
    memset(cave, 0, (size_t)(TCM_CODE + TCM_NSITE * TCM_STRIDE + 16));

    for (k = 0; k < TCM_NSITE; k++) {
        unsigned char  orig[7];
        unsigned char* site = mod + g_tcm_emit[k].rva;
        unsigned char* stub = cave + TCM_CODE + k * TCM_STRIDE;
        unsigned char  b[32];
        int n = 0;
        long long rel;

        orig[0]=0x66; orig[1]=0xC7; orig[2]=0x44; orig[3]=0x24; orig[4]=0x20;
        orig[5]=g_tcm_emit[k].cmd; orig[6]=0x00;
        if (memcmp(site, orig, sizeof(orig)) != 0) {
            /* another patch got here first, or the build moved -- never write */
            skipped++;
            continue;
        }
        b[n++]=0x9C;                                   /* pushfq              */
        b[n++]=0xFF; b[n++]=0x05;                      /* inc dword [rip+slot]*/
        rel = (long long)(cave + g_tcm_emit[k].cmd * 4) - (long long)(stub + n + 4);
        memcpy(b + n, &rel, 4); n += 4;
        b[n++]=0x9D;                                   /* popfq -- rsp back,
                                                          so the stolen store
                                                          still sees [rsp+0x20] */
        memcpy(b + n, orig, sizeof(orig)); n += (int)sizeof(orig);
        rel = (long long)(site + sizeof(orig)) - (long long)(stub + n + 5);
        b[n++]=0xE9; memcpy(b + n, &rel, 4); n += 4;
        if (n > TCM_STRIDE) { skipped++; continue; }
        memcpy(stub, b, (size_t)n);

        rel = (long long)stub - (long long)(site + 5);
        if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) { skipped++; continue; }
        if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) { skipped++; continue; }
        site[0] = 0xE9; memcpy(site + 1, &rel, 4);
        site[5] = 0x90; site[6] = 0x90;
        VirtualProtect(site, sizeof(orig), old, &old);
        FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));
        done++;
    }
    FlushInstructionCache(GetCurrentProcess(), cave, (size_t)(TCM_CODE + TCM_NSITE * TCM_STRIDE));
    g_tcm_cave = cave;
    log_line("THROWTECH/cmd: %d of %d command emit sites counted%s",
             done, TCM_NSITE,
             skipped ? " (the rest did not match their expected bytes -- not written)" : "");
}

/* ---- PART 29: what actually suppresses the tech command ------------------
 *
 *  PART 28 measured that command 0x23 is emitted on the tech button when
 *  standing and side-stepping, and NEVER during a run -- and that its absence
 *  is what the failed tech coincides with. Both of its emit sites are gated on
 *  the same byte:
 *
 *      41185A  movss  xmm0,[r14+0x90]        ; r14 = the BrainPad
 *      411863  comiss xmm0,[rip+0x10AEBD6]   ; = 0x1414C0440, the constant 15.0
 *      41186A  seta   r13b                   ; r13b = ([r14+0x90] > 15.0)
 *      411885  test   r13b,r13b / jne skip   ; site 1, 0x41188A
 *      411907  test   r13b,r13b / jne skip   ; site 2, 0x41190C
 *
 *  So +0x90 above 15.0 suppresses the tech command outright. What +0x90 IS has
 *  not been established: the guess "frames of held direction" came from the
 *  neighbouring constant 16.666 (= 1000/60) and releasing the stick mid-grab
 *  did NOT restore the tech, which is evidence against it. This probe reads the
 *  value instead of inferring it.
 *
 *  Hooked at 0x41185A, 9 bytes -- the instruction is `movss` (scalar) and it
 *  starts at 0x41185A, not the `movups` at 0x41185B that a misaligned decode
 *  suggests; 24 linear sweeps agree on the 9-byte boundary, PART 21's own hook
 *  at 0x411853 (7 bytes) corroborates it, and no branch lands inside.
 *
 *  The site runs every frame, so the payload only publishes the latest value
 *  and the watcher samples it across a live window. */
#define TTH_HOOK_RVA  0x41185Au
#define TTH_HOLD_OFF  0x90u
#define TTH_LIMIT     15.0f

static volatile float         g_ttp_hold = -1.0f;
static volatile unsigned char g_ttp_r13  = 0xFF;

/* rcx = the BrainPad (the site's r14). */
static void ttp_hold(unsigned char* brain)
{
    float v;
    if (!brain) return;
    __try { v = *(float*)(brain + TTH_HOLD_OFF); }
    __except(EXCEPTION_EXECUTE_HANDLER) { return; }
    g_ttp_hold = v;
    g_ttp_r13  = (unsigned char)(v > TTH_LIMIT);
}

static int ttp_install_hold(void)
{
    static const unsigned char orig[9] =
        {0xF3,0x41,0x0F,0x10,0x86,0x90,0x00,0x00,0x00};
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    unsigned char* stub;
    unsigned char  b[224];
    int n = 0, i;
    long long rel;
    void* payload = (void*)ttp_hold;
    DWORD old;

    if (!mod) return 0;
    site = mod + TTH_HOOK_RVA;
    if (memcmp(site, orig, sizeof(orig)) != 0) {
        log_line("THROWTECH: no `movss xmm0,[r14+0x90]` at RVA 0x%X "
                 "-- the suppressor value will not be logged", TTH_HOOK_RVA);
        return 0;
    }
    stub = (unsigned char*)gauge_alloc_near(site, 256);
    if (!stub) { log_line("THROWTECH: no trampoline for the hold hook -- skipped"); return 0; }

    b[n++]=0x50; b[n++]=0x51; b[n++]=0x52;                   /* push rax,rcx,rdx */
    b[n++]=0x41; b[n++]=0x50;                                /* push r8          */
    b[n++]=0x41; b[n++]=0x51;                                /* push r9          */
    b[n++]=0x41; b[n++]=0x52;                                /* push r10         */
    b[n++]=0x41; b[n++]=0x53;                                /* push r11         */
    b[n++]=0x55;                                             /* push rbp         */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xE5;                   /* mov  rbp,rsp     */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xE4; b[n++]=0xF0;      /* and  rsp,-16     */
    b[n++]=0x48; b[n++]=0x81; b[n++]=0xEC;                   /* sub  rsp,0x80    */
    { unsigned int fr = 0x80; memcpy(b + n, &fr, 4); n += 4; }
    b[n++]=0x0F; b[n++]=0x11; b[n++]=0x44; b[n++]=0x24; b[n++]=0x20;
    b[n++]=0x0F; b[n++]=0x11; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;
    b[n++]=0x0F; b[n++]=0x11; b[n++]=0x54; b[n++]=0x24; b[n++]=0x40;
    b[n++]=0x0F; b[n++]=0x11; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x50;
    b[n++]=0x0F; b[n++]=0x11; b[n++]=0x64; b[n++]=0x24; b[n++]=0x60;
    b[n++]=0x0F; b[n++]=0x11; b[n++]=0x6C; b[n++]=0x24; b[n++]=0x70;
    b[n++]=0x4C; b[n++]=0x89; b[n++]=0xF1;                   /* mov rcx,r14      */
    b[n++]=0x48; b[n++]=0xB8;                                /* mov rax,imm64    */
    memcpy(b + n, &payload, 8); n += 8;
    b[n++]=0xFF; b[n++]=0xD0;                                /* call rax         */
    b[n++]=0x0F; b[n++]=0x10; b[n++]=0x44; b[n++]=0x24; b[n++]=0x20;
    b[n++]=0x0F; b[n++]=0x10; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;
    b[n++]=0x0F; b[n++]=0x10; b[n++]=0x54; b[n++]=0x24; b[n++]=0x40;
    b[n++]=0x0F; b[n++]=0x10; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x50;
    b[n++]=0x0F; b[n++]=0x10; b[n++]=0x64; b[n++]=0x24; b[n++]=0x60;
    b[n++]=0x0F; b[n++]=0x10; b[n++]=0x6C; b[n++]=0x24; b[n++]=0x70;
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xEC;                   /* mov rsp,rbp      */
    b[n++]=0x5D;                                             /* pop rbp          */
    b[n++]=0x41; b[n++]=0x5B; b[n++]=0x41; b[n++]=0x5A;      /* pop r11,r10      */
    b[n++]=0x41; b[n++]=0x59; b[n++]=0x41; b[n++]=0x58;      /* pop r9,r8        */
    b[n++]=0x5A; b[n++]=0x59; b[n++]=0x58;                   /* pop rdx,rcx,rax  */
    memcpy(b + n, orig, sizeof(orig)); n += (int)sizeof(orig);
    rel = (long long)(site + sizeof(orig)) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b + n, &rel, 4); n += 4;

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);

    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("THROWTECH: hold trampoline out of rel32 range -- skipped");
        return 0;
    }
    if (!VirtualProtect(site, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("THROWTECH: VirtualProtect failed at RVA 0x%X", TTH_HOOK_RVA);
        return 0;
    }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    for (i = 5; i < (int)sizeof(orig); i++) site[i] = 0x90;
    VirtualProtect(site, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(orig));
    log_line("THROWTECH: hold hook on RVA 0x%X, 9 bytes stolen -- reading "
             "BrainPad+0x90 against the 15.0 that gates command 0x23",
             TTH_HOOK_RVA);
    return 1;
}

/* Drains the rings in arrival order and, between drains, watches the last
   fighter seen for a window actually going non-zero. */
static DWORD WINAPI ttp_watch(LPVOID u)
{
    unsigned long long ev_seen = 0, nm_seen = 0, gt_seen = 0;
    int lines = 0;
    float last_n = -1.0f, last_g = -1.0f;
    void* gt_f = (void*)~(uintptr_t)0;
    unsigned char gt_fb = 0xFF, gt_oa = 0xFF, gt_gr = 0xFF;
    unsigned int cmd_snap[TCM_NSLOT];
    int win_open = 0;
    float hold_min = 0.0f, hold_max = 0.0f;
    int hold_seen = 0, r13_ever_clear = 0;
    (void)u;
    memset(cmd_snap, 0, sizeof(cmd_snap));
    while (g_ttp_on && lines < 3000) {
        int j, bi;
        unsigned long long best;
        for (;;) {
            best = 0; bi = -1;
            for (j = 0; j < TTP_NEV; j++) {
                unsigned long long t = g_ttp_ev[j].seq;
                if (t > ev_seen && (bi < 0 || t < best)) { best = t; bi = j; }
            }
            if (bi < 0) break;
            log_line("THROWTECH: #%llu  cat %u %s <- prev %u %s   fighter %p  "
                     "windows before: n=%.2f g=%.2f",
                     (unsigned long long)g_ttp_ev[bi].seq,
                     (unsigned)g_ttp_ev[bi].newcat,  ttp_cat(g_ttp_ev[bi].newcat),
                     (unsigned)g_ttp_ev[bi].prevcat, ttp_cat(g_ttp_ev[bi].prevcat),
                     g_ttp_ev[bi].fighter,
                     (double)g_ttp_ev[bi].win_n, (double)g_ttp_ev[bi].win_g);
            ev_seen = best;
            if (++lines >= 3000) break;
        }
        for (;;) {
            best = 0; bi = -1;
            for (j = 0; j < TTP_NNM; j++) {
                unsigned long long t = g_ttp_nm[j].seq;
                if (t > nm_seen && (bi < 0 || t < best)) { best = t; bi = j; }
            }
            if (bi < 0) break;
            log_line("THROWTECH:   case 15 action \"%s\"  dam_gr %s -- %s",
                     g_ttp_nm[bi].name,
                     (g_ttp_nm[bi].found == -1) ? "NOT FOUND" : "found",
                     (g_ttp_nm[bi].found == -1) ? "no window armed" : "WINDOW ARMED");
            nm_seen = best;
            /* Forget the collapsed gate reading at every new arming, so each
               grab logs its own GATE line. Without this a second grab with the
               same verdict prints nothing, which reads identically to the gate
               never being reached at all -- and those are different bugs. */
            gt_f = (void*)~(uintptr_t)0; gt_fb = 0xFF; gt_oa = 0xFF; gt_gr = 0xFF;
            if (g_tcm_cave) {                 /* PART 28: the window opens here */
                memcpy(cmd_snap, g_tcm_cave, sizeof(cmd_snap));
                win_open = 1;
            }
            hold_seen = 0; r13_ever_clear = 0;
            hold_min = 0.0f; hold_max = 0.0f;
            if (++lines >= 3000) break;
        }
        /* the gate. Collapsed on (fighter, +0x6F8, +0x1288, verdict) so a
           twelve-frame window is one line unless something actually moves. */
        for (;;) {
            best = 0; bi = -1;
            for (j = 0; j < TTG_NGT; j++) {
                unsigned long long t = g_ttp_gt[j].seq;
                if (t > gt_seen && (bi < 0 || t < best)) { best = t; bi = j; }
            }
            if (bi < 0) break;
            gt_seen = best;
            if (g_ttp_gt[bi].fighter != gt_f || g_ttp_gt[bi].f_block != gt_fb ||
                g_ttp_gt[bi].o_allow != gt_oa || g_ttp_gt[bi].granted != gt_gr) {
                gt_f  = g_ttp_gt[bi].fighter;
                gt_fb = g_ttp_gt[bi].f_block;
                gt_oa = g_ttp_gt[bi].o_allow;
                gt_gr = g_ttp_gt[bi].granted;
                log_line("THROWTECH:   GATE fighter %p  n=%.2f g=%.2f  "
                         "fighter+0x6F8=%u owner+0x1288=%u  -> %s",
                         g_ttp_gt[bi].fighter,
                         (double)g_ttp_gt[bi].win_n, (double)g_ttp_gt[bi].win_g,
                         (unsigned)gt_fb, (unsigned)gt_oa,
                         gt_gr ? "GRANTED (tech allowed)"
                               : (gt_oa == 0 ? "REFUSED -- owner+0x1288 is 0"
                                             : "REFUSED -- fighter+0x6F8 is not 0"));
                if (++lines >= 3000) break;
            }
        }
        {
            unsigned char* f = (unsigned char*)g_ttp_fighter;
            float n = 0.0f, g = 0.0f;
            if (f) {
                __try { n = *(float*)(f + TTP_WIN_N); g = *(float*)(f + TTP_WIN_G); }
                __except(EXCEPTION_EXECUTE_HANDLER) { n = 0.0f; g = 0.0f; }
                if (n != last_n || g != last_g) {
                    if (n > 0.0f || g > 0.0f) {
                        log_line("THROWTECH:   window n=%.2f g=%.2f  (fighter %p)",
                                 (double)n, (double)g, f);
                        lines++;
                    }
                    last_n = n; last_g = g;
                }
                if (win_open) {          /* PART 29: sample the suppressor */
                    float h = g_ttp_hold;
                    if (!hold_seen) { hold_min = hold_max = h; hold_seen = 1; }
                    else { if (h < hold_min) hold_min = h; if (h > hold_max) hold_max = h; }
                    if (g_ttp_r13 == 0) r13_ever_clear = 1;
                }
                /* PART 28: the window has expired -- report its command traffic */
                if (win_open && n <= 0.0f && g <= 0.0f && g_tcm_cave) {
                    char buf[256];
                    int p = 0, c, any = 0;
                    for (c = 0; c < TCM_NSLOT && p < (int)sizeof(buf) - 24; c++) {
                        unsigned int now = *(volatile unsigned int*)(g_tcm_cave + c * 4);
                        unsigned int was = cmd_snap[c];
                        if (now != was) {
                            p += sprintf(buf + p, "%s0x%02X=+%u", any ? " " : "",
                                         (unsigned)c, now - was);
                            any = 1;
                        }
                    }
                    if (!any) { buf[0] = 0; }
                    log_line("THROWTECH:   commands emitted during that window: %s",
                             any ? buf : "NONE AT ALL");
                    if (hold_seen)
                        log_line("THROWTECH:   BrainPad+0x90 during that window: "
                                 "min=%.2f max=%.2f (limit %.1f) -- 0x23 was %s",
                                 (double)hold_min, (double)hold_max, (double)TTH_LIMIT,
                                 r13_ever_clear ? "ALLOWED at least one frame"
                                                : "SUPPRESSED on every frame");
                    win_open = 0;
                    lines++;
                }
            }
        }
        Sleep(8);
    }
    log_line("THROWTECH: watcher stopped after %d lines", lines);
    return 0;
}

static void patch_throwtech_probe(void)
{
    if (!ttp_install_entry()) return;
    ttp_install_name();          /* optional -- the entry hook is the measurement */
    ttp_install_gate();          /* PART 27 -- the three conditions of the override */
    patch_throwtech_commands();  /* PART 28 -- the command traffic in the window   */
    ttp_install_hold();          /* PART 29 -- the value that suppresses 0x23      */
    g_ttp_on = 1;
    CreateThread(NULL, 0, ttp_watch, NULL, 0, NULL);
    log_line("THROWTECH: probe armed -- get grabbed out of a RUN, then STANDING, "
             "then out of a SIDE-STEP, and press R1 to tech each time");
}

/* ============ PART 15: BOOT STRAIGHT INTO THE TRAINING CHARACTER SELECT =====
 *  WHAT IT DOES
 *  ------------
 *  Boot goes logos -> Training character select, skipping the title screen and
 *  the menu walk.
 *
 *  ! FIRST ATTEMPT WAS WRONG, and the log said "applied". Recorded here because
 *  the failure is instructive. The SLogo owner (0x140750B10) contains two
 *  `lea rdx,"JUMP_Title"` sites, at RVA 0x750BCB and 0x750C2C, and repointing
 *  both did nothing at all: they sit on the branch taken when the scene already
 *  has an explicit command pending in [SLogo+0xB0], which never happens on a
 *  normal boot. Patching a site and watching a log line confirm it is not the
 *  same as patching the site that RUNS.
 *
 *  THE PATH THAT ACTUALLY RUNS
 *  ---------------------------
 *      0x140750B66  je 0x140750C66          ; [SLogo+0xB0] empty -> normal boot
 *      0x140750C69  call 0x14074F810        ; SLogo::Update
 *      0x140750C70  je  ...                 ; returned 0 -> nothing to do
 *      0x140750C72  mov rax,[rdi]
 *      0x140750C75  mov rbx,[rax+0x88]      ; flow vtable slot 0x88
 *      0x140750C83  lea rdx,[rip+0xD483FE]  ; "LOGO_NEXT"
 *      0x140750C9C  call rbx
 *
 *  So the boot does not name its destination at all. It raises the EVENT
 *  `LOGO_NEXT`, and the flow graph -- built by the 32 KB function at
 *  0x140866050 -- is what maps that event to the Title state. Slot 0x88 is the
 *  generic "send this request by name" method; SLogo state 10 uses the same one
 *  for `INIT_OPTION` and `INIT_FONT`.
 *
 *  HOW
 *  ---
 *  Rather than rebuild a graph edge, send a scene JUMP from that site instead
 *  of the event. `0x14089E310` is the flow's "jump to scene by name" entry --
 *  a free function, in no vtable, taking exactly (rcx = flow, rdx = &tsd string)
 *  which is the signature `call rbx` is already set up for. It lazily builds its
 *  singleton at 0x141CFBD18, so it needs no other state.
 *
 *  Two edits, no trampoline, and the site's own string construction is reused:
 *
 *      RVA 0x750C72  48 8B 07 48 8B 98 88 00 00 00   mov rax,[rdi]
 *                                                     mov rbx,[rax+0x88]
 *                ->  48 BB <mod+0x89E310>             mov rbx, dispatcher
 *
 *      RVA 0x750C86  the lea's disp32:  "LOGO_NEXT" -> "JUMP_TrainingCharacterSelect"
 *
 *  Both are 10 bytes and 4 bytes exactly, so nothing moves. `rax` is dead after
 *  the replaced pair: the only reader would be the string constructor call at
 *  0x750C8F, which clobbers it as its own return value.
 *
 *  The imm64 is written from the RUNTIME module base, so this is ASLR-correct;
 *  the guard pins all 44 bytes of the window before anything is touched.
 *
 *  ! SECOND CORRECTION -- the jump worked, the MODE did not. With only the two
 *  edits above the game left the logos and landed on the OFFLINE VERSUS
 *  character select. The character select is one shared scene; which mode it
 *  runs in comes from a global setup object, and the jump alone does not set it.
 *
 *  The normal issuer (0x1406EC3E3, reached when the menu selection is 6) shows
 *  exactly what is missing:
 *
 *      0x1406EC3F0  mov rax,[0x141CFBAB8]       ; setup singleton, lazily made
 *                   ...if NULL: new(0x4D0), ctor 0x14082CF10, store the RETURN
 *      0x1406EC41B  mov dword [rax+0x228], 6    ; <-- the mode
 *      0x1406EC42C  lea rdx,"JUMP_TrainingCharacterSelect"
 *
 *  `+0x228 = 6` is the whole difference. It is the only write to that field in
 *  the 11,401-byte issuer, and it sits immediately before the Training jump.
 *
 *  The singleton is created on demand, so at logo time it may still be NULL --
 *  which is why this cannot be a byte patch. `call rbx` is therefore pointed at
 *  a C function in this DLL instead of straight at the dispatcher: it takes the
 *  site's own (rcx = flow, rdx = &string), does the singleton-and-mode dance the
 *  way the issuer does, then tail-calls the real dispatcher. A plain C function
 *  is already (rcx, rdx) in the MS x64 ABI, preserves the non-volatiles the site
 *  relies on (rdi survives to 0x140750C9E), and the frame that just called the
 *  string constructor at 0x750C8F has the shadow space for it.
 * ==================================================================== */
#define BOOTTR_WINDOW_RVA        0x750C72u   /* mov rax,[rdi]; mov rbx,[rax+0x88] */
#define BOOTTR_DISPATCH_RVA      0x89E310u   /* flow "jump to scene by name"      */
#define BOOTTR_JUMP_TRAINING_RVA 0x148EB78u  /* "JUMP_TrainingCharacterSelect"    */
#define BOOTTR_JUMP_ROOM_RVA     0x14A0848u  /* "JUMP_RoomMatchMenu"              */
#define BOOTTR_ONLINE_SEL_RVA    0x1CDF2E8u  /* 0 rank, 1 room match, 2 free      */
#define BOOTTR_ONLINE_SEL_ROOM   1

/* ---- the boot destination is chosen at RUN TIME -------------------------
   It used to be a compile-time #if, which forced one frozen DLL per boot
   shortcut in GameModes/<mode>/dinput8.dll -- and because a mode loader
   SHADOWS the normal one, activating a dll_switch variant and then launching
   through a mode launcher silently ran the mode's old binary instead. That
   cost a full debugging cycle on 2026-08-30: a patch was read as "does not
   work" when patch_ranked.log showed the run had loaded a different DLL.
   Now one DLL serves every shortcut and the launcher says which it wants
   through the BROS_BOOT_MODE environment variable:
       BROS_BOOT_MODE=training    -> JUMP_TrainingCharacterSelect
       BROS_BOOT_MODE=roommatch   -> JUMP_RoomMatchMenu
       unset                      -> whatever the build's flags said
   so the quick launchers can install the ACTIVATED dll like the normal
   launcher does and still boot straight where they mean to. */
static int g_boot_room    = ENABLE_BOOT_ROOMMATCH;                 /* 1 = room match */
static int g_boot_enabled = (ENABLE_BOOT_TRAINING || ENABLE_BOOT_ROOMMATCH);
#define BOOTTR_DEST_RVA  (g_boot_room ? BOOTTR_JUMP_ROOM_RVA : BOOTTR_JUMP_TRAINING_RVA)
#define BOOTTR_DEST_NAME (g_boot_room ? "JUMP_RoomMatchMenu" : "JUMP_TrainingCharacterSelect")

/* Reads the launcher's request. Leaves the build's own defaults alone when the
   variable is absent, so an existing GameModes loader keeps behaving exactly as
   it does today. */
static void boot_mode_from_env(void)
{
    char v[32];
    DWORD n = GetEnvironmentVariableA("BROS_BOOT_MODE", v, sizeof(v));

    /* ⚠ THE ENVIRONMENT DOES NOT ALWAYS REACH THE PROCESS. A client started
       inside a Sandboxie box does not necessarily inherit the launcher's
       variables, and the symptom is silent and expensive: the boxed client boots
       to the TITLE SCREEN, the game never loads steam_api64 (it only does on
       leaving the title), the loader has no matchmaking to hook, and the client
       sits in the room's lobby invisible to everyone. Measured 2026-09-21 --
       both clients on the identical build, identical room code 805088 and
       identical pool 809091, and they still could not see each other.

       So the mode also travels as a FILE beside the exe. The environment still
       wins when it is set; this is the fallback that cannot be stripped by a
       sandbox, a shortcut or a Steam relaunch. */
    if (n == 0 || n >= sizeof(v)) {
        char path[MAX_PATH];
        DWORD got = GetModuleFileNameA(NULL, path, sizeof(path));
        n = 0;
        if (got > 0 && got < sizeof(path)) {
            char* slash = strrchr(path, '\\');
            if (slash && (size_t)(slash - path) < sizeof(path) - 24) {
                FILE* f;
                strcpy(slash + 1, "bros_boot_mode.txt");
                f = fopen(path, "rb");
                if (f) {
                    size_t rd = fread(v, 1, sizeof(v) - 1, f);
                    fclose(f);
                    v[rd] = 0;
                    while (rd && (v[rd-1] == '\n' || v[rd-1] == '\r' ||
                                  v[rd-1] == ' '  || v[rd-1] == '\t')) v[--rd] = 0;
                    n = (DWORD)rd;
                    if (n) log_line("BOOTTRAIN: no BROS_BOOT_MODE in the environment; "
                                    "took '%s' from bros_boot_mode.txt beside the exe", v);
                }
            }
        }
    }
    if (n == 0 || n >= sizeof(v)) return;
    if (!strcmp(v, "training"))       { g_boot_enabled = 1; g_boot_room = 0; }
    else if (!strcmp(v, "roommatch")) { g_boot_enabled = 1; g_boot_room = 1; }
    else if (!strcmp(v, "none"))      { g_boot_enabled = 0; }
    else { log_line("BOOTTRAIN: BROS_BOOT_MODE='%s' not understood -- ignored", v); return; }
    log_line("BOOTTRAIN: BROS_BOOT_MODE='%s' -- boot %s", v,
             g_boot_enabled ? (g_boot_room ? "-> room match" : "-> training") : "left alone");
}
#define BOOTTR_SETUP_PTR_RVA     0x1CFBAB8u  /* the scene-setup singleton         */
#define BOOTTR_SETUP_SIZE        0x4D0u      /* what the issuer allocates for it  */
#define BOOTTR_SETUP_CTOR_RVA    0x82CF10u   /* its constructor; returns the obj  */
#define BOOTTR_NEW_RVA           0x10A1038u  /* the allocator the issuer calls    */
#define BOOTTR_MODE_OFF          0x228       /* setup+0x228 = the mode            */
#define BOOTTR_MODE_TRAINING     6           /* what the Training issuer stores   */

static unsigned char* g_boottr_mod;

/* Called INSTEAD of the flow's vtable slot 0x88, with the site's own arguments.
   Sets the mode the way 0x1406EC3E3 does, then hands the command to the real
   dispatcher. Runs once, on the game thread, at the end of the logo scene. */
static void boottr_handoff(void* flow, void* cmd)
{
    unsigned char* mod  = g_boottr_mod;
    void**         slot = (void**)(mod + BOOTTR_SETUP_PTR_RVA);
    void*          o    = *slot;
    static int     said = 0;

    if (!o) {
        void* raw = ((void* (*)(unsigned long long))(mod + BOOTTR_NEW_RVA))
                        (BOOTTR_SETUP_SIZE);
        if (raw) {
            o = ((void* (*)(void*))(mod + BOOTTR_SETUP_CTOR_RVA))(raw);
            *slot = o;
        }
    }
    if (g_boot_room) {
    /* The room-match issuer (0x1407E6847) writes no mode at all -- the online
       menu has already chosen by then, through the selector this sets. */
    (void)o;
    *(int*)(mod + BOOTTR_ONLINE_SEL_RVA) = BOOTTR_ONLINE_SEL_ROOM;
    if (!said) { said = 1;
        log_line("BOOTTRAIN: online selector at RVA 0x%X set to %d (room match) "
                 "before the jump", BOOTTR_ONLINE_SEL_RVA, BOOTTR_ONLINE_SEL_ROOM); }
    } else {
    if (o) {
        *(int*)((unsigned char*)o + BOOTTR_MODE_OFF) = BOOTTR_MODE_TRAINING;
        if (!said) { said = 1;
            log_line("BOOTTRAIN: setup singleton %p, mode +0x%X set to %d (Training) "
                     "before the jump", o, BOOTTR_MODE_OFF, BOOTTR_MODE_TRAINING); }
    } else if (!said) { said = 1;
        log_line("BOOTTRAIN: setup singleton is NULL and could not be created -- "
                 "jumping without setting the mode, expect offline versus");
    }
    }
    ((void (*)(void*, void*))(mod + BOOTTR_DISPATCH_RVA))(flow, cmd);
}


static void patch_boot_training(void)
{
    /* 0x750C72 .. 0x750C9E -- the whole LOGO_NEXT handoff */
    static const unsigned char orig[44] = {
        0x48,0x8B,0x07,                          /* mov rax,[rdi]            */
        0x48,0x8B,0x98,0x88,0x00,0x00,0x00,      /* mov rbx,[rax+0x88]       */
        0x49,0xC7,0xC0,0xFF,0xFF,0xFF,0xFF,      /* mov r8,-1                */
        0x48,0x8D,0x15,0xFE,0x83,0xD4,0x00,      /* lea rdx,"LOGO_NEXT"      */
        0x48,0x8D,0x4C,0x24,0x20,                /* lea rcx,[rsp+0x20]       */
        0xE8,0x4C,0xD3,0x93,0xFF,                /* call <string ctor>       */
        0x48,0x8D,0x54,0x24,0x20,                /* lea rdx,[rsp+0x20]       */
        0x48,0x8B,0xCF,                          /* mov rcx,rdi              */
        0xFF,0xD3                                /* call rbx                 */
    };
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* p;
    unsigned long long disp64;
    long long rel;
    int  disp32;
    DWORD old;

    if (!mod) return;
    p = mod + BOOTTR_WINDOW_RVA;

    if (p[0] == 0x48 && p[1] == 0xBB) {
        log_line("BOOTTRAIN: already applied -- nothing to do");
        return;
    }
    if (memcmp(p, orig, sizeof(orig)) != 0) {
        log_line("BOOTTRAIN: the LOGO_NEXT handoff at RVA 0x%X is not as expected "
                 "(game updated?) -- skipped, boot still goes to the title screen",
                 BOOTTR_WINDOW_RVA);
        return;
    }

    /* the lea is at window+0x11, its disp32 at window+0x14; the instruction
       ends at window+0x18, which is what a rip-relative operand is measured
       from */
    rel = (long long)(mod + BOOTTR_DEST_RVA) - (long long)(p + 0x18);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("BOOTTRAIN: %s out of rel32 range -- skipped", BOOTTR_DEST_NAME);
        return;
    }
    disp32  = (int)rel;
    g_boottr_mod = mod;
    disp64  = (unsigned long long)(void*)&boottr_handoff;

    if (!VirtualProtect(p, sizeof(orig), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("BOOTTRAIN: VirtualProtect failed at RVA 0x%X", BOOTTR_WINDOW_RVA);
        return;
    }
    p[0] = 0x48; p[1] = 0xBB;                 /* mov rbx, imm64 */
    memcpy(p + 2, &disp64, 8);
    memcpy(p + 0x14, &disp32, 4);             /* the lea's target */
    VirtualProtect(p, sizeof(orig), old, &old);
    FlushInstructionCache(GetCurrentProcess(), p, sizeof(orig));

    log_line("BOOTTRAIN: LOGO_NEXT handoff at RVA 0x%X rewritten -- the logo scene now "
             "calls %p, which prepares the mode and then sends %s"
             " to the dispatcher at %p, instead of "
             "raising LOGO_NEXT through vtable slot 0x88",
             BOOTTR_WINDOW_RVA, (void*)&boottr_handoff, BOOTTR_DEST_NAME,
             (void*)(mod + BOOTTR_DISPATCH_RVA));
}

/* ================= SKIP THE BOOT LOGOS ===============================
 *  Bandai Namco, Tamsoft, and the licensor board after them. With this and
 *  FAST BOOT the game opens on the title screen.
 *
 *  The four entries are a table at 0x141CF3520, stride 0x28, built by the
 *  static initialiser at 0x140048210:
 *
 *      struct { u32 isMovie; char name[0x18]; float frames; };   // 0x28
 *
 *      0  CESA_jp              image  30 frames   (Japan only -- SLogo state 1
 *                                                  compares the name and skips)
 *      1  movie_BNE_logo       movie  45
 *      2  movie_TAMSOFT_logo   movie   0.0
 *      3  logo_all             image  60
 *
 *  `isMovie` entries ignore the frame count and wait for playback state 5;
 *  image entries wait out `frames` in SLogo state 6.
 *
 *  SLogo state 1 is the per-entry loader, and it opens with its own bound
 *  check -- `[rsi+0xD4]` is the entry index:
 *
 *      0x14074F977  movsxd rax,[rsi+0xD4]
 *      0x14074F97E  cmp    eax, 3
 *      0x14074F981  ja     0x14074FB94      ; -> mov [rsi+0xD0], 8 = logos done
 *
 *  Make that branch unconditional and the FIRST entry into state 1 lands on
 *  "logos finished". State 0 falls through into state 1, so this happens on the
 *  very first frame of the scene: nothing is ever loaded, no movie is opened, no
 *  texture is bound. Cheaper and safer than cutting the durations, which would
 *  still load and play everything.
 *
 *      0F 87 0D 02 00 00   ja  0x14074FB94
 *   -> E9 0E 02 00 00 90   jmp 0x14074FB94 ; nop
 *
 *  Six bytes, in place, and the `nop` keeps the instruction boundary at
 *  0x14074F987 for anything that branches there.
 *
 *  From state 8 the flow is unchanged: the first-boot fork, then the AUTO_SAVE
 *  slot (which FAST BOOT points at the terminal state), then the LOGO_NEXT
 *  handoff. So this composes with both of the other boot patches.
 *
 *  Guarded on the whole 16-byte movsxd+cmp+ja opening, which occurs once.
 *
 *  PART 2 -- the fade, which is what is left playing before the title.
 *  ------------------------------------------------------------------
 *  State 0 still ran. It is nothing but the fade object's setup:
 *
 *      0x14074F944  mov rcx,[rsi+0x120]     ; the scene's fade object
 *                   ...zero its fields, set 1.0f
 *      0x14074F963  and dword [rcx], ~4
 *      0x14074F966  or  dword [rcx], 0xB    ; <-- turns it ON
 *      0x14074F969  xorps xmm1,xmm1
 *      0x14074F96C  call 0x1400EE0F0        ; the fade/anim updater
 *      0x14074F971  inc [rsi+0xD0]
 *
 *  and the owner ticks that same object every frame (`0x140750CAF`). With the
 *  logos gone that fade is the only thing the scene still draws, and it is the
 *  short animation that plays just before the title screen.
 *
 *  Point jump-table slot 0 at 0x14074FB94 -- `mov [rsi+0xD0], 8`, which falls
 *  straight into state 8's body. The scene then never touches the fade object
 *  at all, and the whole logo scene is two frames that render nothing:
 *
 *      frame 1   slot 0 -> state 8 -> the first-boot fork -> state 13
 *      frame 2   slot 13 -> (fast boot) state 15 -> return 1 -> LOGO_NEXT
 *
 *  Leaving the object unconfigured is the SAFE direction: state 0's `or 0xB`
 *  is what activates it, so not running that leaves it inactive rather than
 *  leaving a black overlay on screen.
 *
 *      jump table RVA 0x7503AC, slot 0:  44 F9 74 00 -> 94 FB 74 00
 * ==================================================================== */
#define SKIPLOGO_GUARD_RVA  0x74F977u
#define SKIPLOGO_JA_OFF     0x0A          /* the ja, inside that window */
#define SKIPLOGO_JMPTBL_RVA 0x7503ACu     /* SLogo::Update's 16-slot table */

static void patch_skip_logo_fade(void);

static void patch_skip_logos(void)
{
    static const unsigned char orig[16] = {
        0x48,0x63,0x86,0xD4,0x00,0x00,0x00,   /* movsxd rax,[rsi+0xD4] */
        0x83,0xF8,0x03,                       /* cmp    eax,3          */
        0x0F,0x87,0x0D,0x02,0x00,0x00         /* ja     0x14074FB94    */
    };
    static const unsigned char repl[6] = {
        0xE9,0x0E,0x02,0x00,0x00,             /* jmp    0x14074FB94    */
        0x90                                  /* nop                   */
    };
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* p;
    DWORD old;

    if (!mod) return;
    p = mod + SKIPLOGO_GUARD_RVA;

    if (memcmp(p + SKIPLOGO_JA_OFF, repl, sizeof(repl)) == 0) {
        log_line("SKIPLOGO: already applied -- nothing to do");
        return;
    }
    if (memcmp(p, orig, sizeof(orig)) != 0) {
        log_line("SKIPLOGO: SLogo state 1 does not open as expected at RVA 0x%X "
                 "(game updated?) -- skipped, the logos still play",
                 SKIPLOGO_GUARD_RVA);
        return;
    }
    if (!VirtualProtect(p + SKIPLOGO_JA_OFF, sizeof(repl),
                        PAGE_EXECUTE_READWRITE, &old)) {
        log_line("SKIPLOGO: VirtualProtect failed at RVA 0x%X",
                 SKIPLOGO_GUARD_RVA + SKIPLOGO_JA_OFF);
        return;
    }
    memcpy(p + SKIPLOGO_JA_OFF, repl, sizeof(repl));
    VirtualProtect(p + SKIPLOGO_JA_OFF, sizeof(repl), old, &old);
    FlushInstructionCache(GetCurrentProcess(), p + SKIPLOGO_JA_OFF, sizeof(repl));
    log_line("SKIPLOGO: applied at RVA 0x%X -- SLogo state 1's bound check is now "
             "unconditional, so all four boot logos (CESA_jp, movie_BNE_logo, "
             "movie_TAMSOFT_logo, logo_all) are skipped without being loaded",
             SKIPLOGO_GUARD_RVA + SKIPLOGO_JA_OFF);

    patch_skip_logo_fade();
}

/* Slot 0 of SLogo::Update's jump table -> "mov [rsi+0xD0], 8", so the scene
   never configures or starts its fade. See PART 2 in the block above. */
static void patch_skip_logo_fade(void)
{
    static const unsigned char slot0_orig[4] = {0x44,0xF9,0x74,0x00};  /* 0x74F944 */
    static const unsigned char slot8_pin[4]  = {0x9E,0xFB,0x74,0x00};  /* 0x74FB9E */
    static const unsigned char slot0_repl[4] = {0x94,0xFB,0x74,0x00};  /* 0x74FB94 */
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* tbl;
    DWORD old;

    if (!mod) return;
    tbl = mod + SKIPLOGO_JMPTBL_RVA;

    if (memcmp(tbl, slot0_repl, 4) == 0) {
        log_line("SKIPLOGO/fade: slot 0 already points at state 8 -- nothing to do");
        return;
    }
    /* slot 8 pins the table's identity alongside slot 0 */
    if (memcmp(tbl, slot0_orig, 4) != 0 || memcmp(tbl + 8 * 4, slot8_pin, 4) != 0) {
        log_line("SKIPLOGO/fade: SLogo jump table not as expected at RVA 0x%X "
                 "(game updated?) -- skipped, the pre-title fade still plays",
                 SKIPLOGO_JMPTBL_RVA);
        return;
    }
    if (!VirtualProtect(tbl, 4, PAGE_EXECUTE_READWRITE, &old)) {
        log_line("SKIPLOGO/fade: VirtualProtect failed at RVA 0x%X",
                 SKIPLOGO_JMPTBL_RVA);
        return;
    }
    memcpy(tbl, slot0_repl, 4);
    VirtualProtect(tbl, 4, old, &old);
    FlushInstructionCache(GetCurrentProcess(), tbl, 4);
    log_line("SKIPLOGO/fade: slot 0 repointed to state 8 -- the logo scene no longer "
             "configures or starts its fade object, so nothing animates before the "
             "title screen; the whole scene is now two frames that render nothing");
}

/* ================= PART 18: keep a crash dump (DIAGNOSTIC) ===========
 *
 *  Windows writes NO local crash dump unless asked. `LocalDumps` is a per-user
 *  registry key nothing creates on its own, so the first crash on any machine is
 *  always lost -- and a player reporting "there was no dump" almost always means
 *  "nobody ever enabled them". That cost this project a friend's crash report.
 *
 *  ⚠ The key MUST be scoped to the executable. `LocalDumps` on its own applies to
 *  every application the user runs: enabling it globally would make every crash
 *  of every program on their machine write a 50 MB full dump, silently, forever.
 *  `LocalDumps\<exe name>` applies to this game and nothing else, which is what
 *  makes doing it automatically acceptable at all.
 *
 *  HKCU, so no elevation and no policy involvement.
 *
 *  DumpType 2 (full) rather than a minidump: the stack scan that reads these
 *  dumps needs heap and stack memory, and a minidump has neither. That costs
 *  ~50 MB per crash, which is why DumpCount is bounded.
 *
 *  The other half is pruning. WER does not rotate: at DumpCount it simply stops
 *  writing, silently, and from then on an absence of dumps means nothing. That
 *  already happened here -- several crashes left no dump because the folder had
 *  filled days earlier. So make room at startup instead of discovering it later.
 */
#ifndef ENABLE_CRASHDUMP_SETUP
#define ENABLE_CRASHDUMP_SETUP  1
#endif
/* ★★ 2026-09-17: the comment used to say "each is ~50 MB", which is the
   MINIDUMP figure -- DumpType was 2, MiniDumpWithFullMemory, on a process this
   same file documents at 7-8 GB private. So the real figure was 7-8 GB each,
   times DumpCount, on C:. One Bleach dump exists in %LOCALAPPDATA%\CrashDumps
   (Aug 13, 49 MB) and it predates that setting, so it has never actually fired
   -- which is the only reason it has not already filled the drive.
   Type 1 keeps the stack, the loaded-module list and the register context,
   which is what a crash triage here uses; the full heap has never been read.
   ⇒ ★ RULE: a constant and its comment disagreeing is a defect, not an
     annotation -- one of the two is what the next reader will believe. */
#define CRASHDUMP_KEEP  6      /* dumps to keep; each is ~50 MB at DumpType 1 */

static void exe_base_name(char* out, size_t n)
{
    char full[MAX_PATH];
    DWORD len = GetModuleFileNameA(NULL, full, MAX_PATH);
    DWORD i = len;
    while (i > 0 && full[i - 1] != '\\' && full[i - 1] != '/') i--;
    snprintf(out, n, "%s", full + i);
}

/* Delete oldest-first until at most `keep` remain, so WER always has room. */
static void crashdump_prune(const char* dir, const char* exename, int keep)
{
    char pat[MAX_PATH];
    WIN32_FIND_DATAA fd;
    HANDLE h;
    struct { FILETIME t; char name[MAX_PATH]; } list[64];
    int n = 0, i, j;

    snprintf(pat, sizeof pat, "%s\\%s.*.dmp", dir, exename);
    h = FindFirstFileA(pat, &fd);
    if (h == INVALID_HANDLE_VALUE) return;
    do {
        if (n >= (int)(sizeof list / sizeof list[0])) break;
        list[n].t = fd.ftLastWriteTime;
        snprintf(list[n].name, MAX_PATH, "%s", fd.cFileName);
        n++;
    } while (FindNextFileA(h, &fd));
    FindClose(h);
    if (n <= keep) return;

    /* selection sort, oldest first -- n is tiny and this runs once at startup */
    for (i = 0; i < n; i++)
        for (j = i + 1; j < n; j++)
            if (CompareFileTime(&list[j].t, &list[i].t) < 0) {
                FILETIME tt = list[i].t; list[i].t = list[j].t; list[j].t = tt;
                { char nb[MAX_PATH]; memcpy(nb, list[i].name, MAX_PATH);
                  memcpy(list[i].name, list[j].name, MAX_PATH);
                  memcpy(list[j].name, nb, MAX_PATH); }
            }
    for (i = 0; i < n - keep; i++) {
        char full[MAX_PATH];
        snprintf(full, sizeof full, "%s\\%s", dir, list[i].name);
        if (DeleteFileA(full))
            log_line("CRASHDUMP: pruned %s to make room", list[i].name);
    }
}

static void patch_crashdump_setup(void)
{
    char exename[MAX_PATH], key[MAX_PATH], dir[MAX_PATH];
    const char* folder = "%LOCALAPPDATA%\\CrashDumps";
    HKEY k;
    DWORD count = CRASHDUMP_KEEP + 2, type = 1 /* MiniDumpNormal -- see above */;
    LONG rc;

    exe_base_name(exename, sizeof exename);
    snprintf(key, sizeof key,
             "Software\\Microsoft\\Windows\\Windows Error Reporting\\LocalDumps\\%s",
             exename);

    rc = RegCreateKeyExA(HKEY_CURRENT_USER, key, 0, NULL, 0,
                         KEY_SET_VALUE, NULL, &k, NULL);
    if (rc != ERROR_SUCCESS) {
        log_line("CRASHDUMP: could not create the per-exe LocalDumps key (%ld) -- "
                 "crashes will leave no dump", rc);
        return;
    }
    RegSetValueExA(k, "DumpFolder", 0, REG_EXPAND_SZ,
                   (const BYTE*)folder, (DWORD)strlen(folder) + 1);
    RegSetValueExA(k, "DumpCount", 0, REG_DWORD, (const BYTE*)&count, sizeof count);
    RegSetValueExA(k, "DumpType",  0, REG_DWORD, (const BYTE*)&type,  sizeof type);
    RegCloseKey(k);

    if (ExpandEnvironmentStringsA(folder, dir, MAX_PATH))
        crashdump_prune(dir, exename, CRASHDUMP_KEEP);

    log_line("CRASHDUMP: mini dumps (DumpType 1) enabled for %s only, in %s, "
             "keeping %d. Scoped to this exe -- other applications are "
             "unaffected. Type 2 (full memory) would be 7-8 GB per crash on "
             "this process; switch it back only for a specific heap question.",
             exename, folder, CRASHDUMP_KEEP);
}

/* ================= PART 17: allocation probe (DIAGNOSTIC) ============
 *
 *  The crash is an uncaught std::bad_alloc. Memory exhaustion has been ruled
 *  out by measurement, not by argument: over a 20-minute session the game's
 *  private bytes were FLAT (6,910 -> 6,911 MB), and commit stayed 7-8 GB free
 *  throughout. A deliberate 3 GB ballast squeezed physical memory to under
 *  1 GB free and still produced no crash -- and squeezing physical was itself
 *  the wrong lever, since bad_alloc follows commit, not resident pages.
 *
 *  So the failing allocation is not failing because memory ran out. It is one
 *  allocation asking for a size nothing could satisfy -- a length read out of a
 *  structure that is stale or half-destroyed, which fits everything else: eight
 *  crash dumps with a byte-identical stack, the crash landing on a teardown or a
 *  load, and its rarity.
 *
 *  Waiting for the crash to catch it is the slow way round, and the crash has
 *  stopped reproducing. This catches the allocation instead, at the moment it is
 *  requested, whether or not anything crashes afterwards.
 *
 *  Two triggers, and the second is the one that matters:
 *
 *      size >= BIGALLOC_WATCH   an implausible request, logged before it fails
 *      the allocator returns 0  the failure that BECOMES the bad_alloc, logged
 *                               with its exact requested size whatever it is
 *
 *  IAT hooking, not an inline patch. The exe imports HeapAlloc, HeapReAlloc and
 *  VirtualAlloc by name, so swapping a pointer in the import table is enough --
 *  no code is modified, nothing is unmapped, and it is undone by writing the old
 *  pointer back. An inline hook on an allocator this hot would be a much worse
 *  bet. The name is matched wherever it appears, because a modern PE may import
 *  it from an api-ms-win-core-heap stub rather than from kernel32 directly.
 *
 *  Cost on the fast path is a compare and a not-taken branch per allocation.
 */
#ifndef ENABLE_ALLOC_PROBE
#define ENABLE_ALLOC_PROBE   1
#endif
#define BIGALLOC_WATCH       (256u * 1024u * 1024u)
#define ALLOC_FAIL_CAP       60      /* failures: the event we want   */
#define ALLOC_BIG_CAP        12      /* large-but-fine: context only  */

typedef LPVOID (WINAPI *heapalloc_t)(HANDLE, DWORD, SIZE_T);
typedef LPVOID (WINAPI *heaprealloc_t)(HANDLE, DWORD, LPVOID, SIZE_T);
typedef LPVOID (WINAPI *virtualalloc_t)(LPVOID, SIZE_T, DWORD, DWORD);
typedef USHORT (WINAPI *capturebt_t)(ULONG, ULONG, PVOID*, PULONG);

static heapalloc_t    g_real_heapalloc    = NULL;
static heaprealloc_t  g_real_heaprealloc  = NULL;
static virtualalloc_t g_real_virtualalloc = NULL;
static capturebt_t    g_capture_bt        = NULL;
static volatile LONG  g_fail_reports      = 0;
static volatile LONG  g_big_reports       = 0;
static volatile LONG64 g_alloc_fails      = 0;
static volatile LONG64 g_alloc_big        = 0;

/* Same idea as alloc_backtrace, for PART 27: names whoever decided to leave the
   room lobby. Declared up in PART 27, defined here because g_capture_bt is. */
static void room3_backtrace(const char* tag)
{
    void* fr[16];
    USHORT n, i;
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    if (!g_capture_bt) return;
    n = g_capture_bt(1, 16, fr, NULL);
    for (i = 0; i < n; i++) {
        unsigned char* a = (unsigned char*)fr[i];
        if (a > mod && a < mod + 0x2000000)
            log_line("ROOM3/%s:   frame %2u  exe+0x%X", tag, i, (unsigned)(a - mod));
        else
            log_line("ROOM3/%s:   frame %2u  %p", tag, i, a);
    }
}

/* Real return addresses, from the unwind tables -- not the stack scan the crash
   dumps have to settle for. Names the caller instead of guessing at it. */
static void alloc_backtrace(const char* tag)
{
    void* fr[24];
    USHORT n, i;
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    if (!g_capture_bt) return;
    n = g_capture_bt(1, 24, fr, NULL);
    for (i = 0; i < n; i++) {
        unsigned char* a = (unsigned char*)fr[i];
        if (a > mod && a < mod + 0x2000000)
            log_line("ALLOC/%s:   frame %2u  exe+0x%X", tag, i, (unsigned)(a - mod));
        else
            log_line("ALLOC/%s:   frame %2u  %p", tag, i, a);
    }
}

/* Failures and big-but-fine allocations get SEPARATE budgets, and the big ones
   are deduplicated by size.

   The first version shared one cap of 40. A 13-hour session spent 16 of it on
   the same 512 MB request logged over and over -- the game asks for it on every
   load -- and each report drags ~17 backtrace lines with it. Run long enough and
   the budget is gone before the failure we are waiting for ever arrives, and it
   is dropped silently. A tripwire that can be exhausted by the noise it is
   supposed to ignore is not a tripwire. */
static void alloc_report(const char* what, unsigned long long size, void* got)
{
    MEMORYSTATUSEX ms;
    if (got) {
        /* a large allocation that SUCCEEDED: one report per distinct size */
        static volatile LONG n_sizes = 0;
        static unsigned long long seen[16];
        LONG i, n = n_sizes;
        for (i = 0; i < n && i < 16; i++)
            if (seen[i] == size) return;
        if (n >= 16 || InterlockedIncrement(&g_big_reports) > ALLOC_BIG_CAP) return;
        seen[n] = size;
        InterlockedIncrement(&n_sizes);
    } else {
        /* a FAILURE -- this is the event, never deduplicated */
        if (InterlockedIncrement(&g_fail_reports) > ALLOC_FAIL_CAP) return;
    }
    ms.dwLength = sizeof ms;
    log_line("ALLOC/%s: %llu bytes (%llu MB) -> %s (thread %lu, slots=0x%X)",
             what, size, size >> 20, got ? "ok" : "FAILED",
             GetCurrentThreadId(), (unsigned)g_sq_slotmask);
    if (GlobalMemoryStatusEx(&ms))
        log_line("ALLOC/%s: load %lu%%, phys %llu/%llu MB, commit %llu/%llu MB, VA %llu MB",
                 what, ms.dwMemoryLoad,
                 ms.ullAvailPhys >> 20, ms.ullTotalPhys >> 20,
                 ms.ullAvailPageFile >> 20, ms.ullTotalPageFile >> 20,
                 ms.ullAvailVirtual >> 20);
    alloc_backtrace(what);
}

static LPVOID WINAPI probe_HeapAlloc(HANDLE h, DWORD fl, SIZE_T n)
{
    LPVOID p = g_real_heapalloc(h, fl, n);
    if (!p) { InterlockedIncrement64(&g_alloc_fails); alloc_report("heap-fail", n, p); }
    else if (n >= BIGALLOC_WATCH) { InterlockedIncrement64(&g_alloc_big); alloc_report("heap-big", n, p); }
    return p;
}

static LPVOID WINAPI probe_HeapReAlloc(HANDLE h, DWORD fl, LPVOID q, SIZE_T n)
{
    LPVOID p = g_real_heaprealloc(h, fl, q, n);
    if (!p) { InterlockedIncrement64(&g_alloc_fails); alloc_report("realloc-fail", n, p); }
    else if (n >= BIGALLOC_WATCH) { InterlockedIncrement64(&g_alloc_big); alloc_report("realloc-big", n, p); }
    return p;
}

static LPVOID WINAPI probe_VirtualAlloc(LPVOID a, SIZE_T n, DWORD t, DWORD pr)
{
    LPVOID p = g_real_virtualalloc(a, n, t, pr);
    if (!p && (t & MEM_COMMIT)) { InterlockedIncrement64(&g_alloc_fails); alloc_report("va-fail", n, p); }
    else if (n >= BIGALLOC_WATCH && (t & MEM_COMMIT)) { InterlockedIncrement64(&g_alloc_big); alloc_report("va-big", n, p); }
    return p;
}

/* Swap one named import to `repl`, returning the previous target. */
static void* iat_swap(unsigned char* mod, const char* want, void* repl)
{
    IMAGE_DOS_HEADER* dos = (IMAGE_DOS_HEADER*)mod;
    IMAGE_NT_HEADERS* nt;
    IMAGE_IMPORT_DESCRIPTOR* imp;
    DWORD rva;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) return NULL;
    nt = (IMAGE_NT_HEADERS*)(mod + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) return NULL;
    rva = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT].VirtualAddress;
    if (!rva) return NULL;
    for (imp = (IMAGE_IMPORT_DESCRIPTOR*)(mod + rva); imp->Name; imp++) {
        IMAGE_THUNK_DATA* names;
        IMAGE_THUNK_DATA* addrs;
        if (!imp->OriginalFirstThunk || !imp->FirstThunk) continue;
        names = (IMAGE_THUNK_DATA*)(mod + imp->OriginalFirstThunk);
        addrs = (IMAGE_THUNK_DATA*)(mod + imp->FirstThunk);
        for (; names->u1.AddressOfData; names++, addrs++) {
            IMAGE_IMPORT_BY_NAME* nm;
            DWORD old;
            void* prev;
            if (names->u1.Ordinal & IMAGE_ORDINAL_FLAG64) continue;
            nm = (IMAGE_IMPORT_BY_NAME*)(mod + names->u1.AddressOfData);
            if (strcmp((const char*)nm->Name, want) != 0) continue;
            if (!VirtualProtect(&addrs->u1.Function, sizeof(void*),
                                PAGE_READWRITE, &old)) return NULL;
            prev = (void*)addrs->u1.Function;
            addrs->u1.Function = (ULONGLONG)repl;
            VirtualProtect(&addrs->u1.Function, sizeof(void*), old, &old);
            return prev;
        }
    }
    return NULL;
}

static void patch_alloc_probe(void)
{
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    HMODULE nt = GetModuleHandleA("ntdll.dll");
    int n = 0;

    if (nt) g_capture_bt = (capturebt_t)GetProcAddress(nt, "RtlCaptureStackBackTrace");
    if (!g_capture_bt)
        log_line("ALLOC: RtlCaptureStackBackTrace unavailable -- reports will have no frames");

    g_real_heapalloc = (heapalloc_t)iat_swap(mod, "HeapAlloc", (void*)probe_HeapAlloc);
    if (g_real_heapalloc) n++;
    g_real_heaprealloc = (heaprealloc_t)iat_swap(mod, "HeapReAlloc", (void*)probe_HeapReAlloc);
    if (g_real_heaprealloc) n++;
    g_real_virtualalloc = (virtualalloc_t)iat_swap(mod, "VirtualAlloc", (void*)probe_VirtualAlloc);
    if (g_real_virtualalloc) n++;

    if (n)
        log_line("ALLOC: probe on %d import(s) -- logging every failed allocation and "
                 "every request >= %u MB, with a real backtrace. DIAGNOSTIC, changes "
                 "no behaviour.", n, BIGALLOC_WATCH >> 20);
    else
        log_line("ALLOC: no allocation import could be hooked -- probe inactive");
}

/* ================= PART 16: Kaiser level trace (DIAGNOSTIC) ==========
 *  Yhwach's Kaiser level is the float at fighter+0x1A40, and the number the
 *  player actually sees is pushed to the HUD by
 *  ActionCharaUniqueUI_Pl52::SetLevel -- vtable slot 24, RVA 0x21C910, the one
 *  method that class has beyond the shared family:
 *
 *      mov rax,[rcx+0x10]        ; the Work object
 *      cmp [rax+0x2D0],edx       ; +0x2D0 is the level
 *      je  .same
 *      mov [rax+0x2D0],edx
 *
 *  It runs every frame for Yhwach and nobody else, so hooking its entry gives
 *  the level's timeline for free -- no fighter pointer to resolve, no character
 *  test to write.
 *
 *  WHY THIS EXISTS. Two in-game observations refused to add up. With a `-1`
 *  AddUniqueVal on ct_evolve he ENDED A LEVEL DOWN after Awakening; with that
 *  record removed he ends a level UP. The gap between the two runs is 2, and
 *  the record is only worth 1 -- so either the record applies twice, or the
 *  engine's grant is conditional and did not fire in the first run. Guessing a
 *  third time is how you get a third wrong answer: this logs every step instead.
 *
 *  The stub touches NO register and leaves the flags correct, which is why it
 *  needs no save/restore at all:
 *
 *      mov  [rip+level],edx      ; memory write, no scratch register
 *      lock inc qword [rip+seq]  ; ditto
 *      <the 10 stolen bytes, re-executed>   ; rax is set by the stolen mov,
 *      jmp  back                            ; and the cmp re-sets the flags
 *                                             the following `je` needs
 * ==================================================================== */
#define KTR_HOOK_RVA   0x21C910u    /* ActionCharaUniqueUI_Pl52::SetLevel  */
#define KTR_FORM_RVA   0x471160u    /* the transform routine               */
#define KTR_CHARA      0x34         /* pl052                               */
#define KTR_LEVEL      0x80         /* dword: last level pushed to the HUD */
#define KTR_SEQ        0x88         /* qword: SetLevel calls seen          */
#define KTR_FORM       0x90         /* dword: last form requested          */
#define KTR_FSEQ       0x98         /* qword: transforms seen              */
#define KTR_STUB2      0x40         /* the form stub, inside the same cave */

static unsigned char* g_ktr_cave = NULL;

static DWORD WINAPI ktr_watch(LPVOID u)
{
    int level = -12345, form = -12345;
    int lines = 0;
    (void)u;
    while (g_ktr_cave && lines < 400) {
        long long ls = *(volatile long long*)(g_ktr_cave + KTR_SEQ);
        long long fs = *(volatile long long*)(g_ktr_cave + KTR_FSEQ);
        int l2 = *(volatile int*)(g_ktr_cave + KTR_LEVEL);
        int f2 = *(volatile int*)(g_ktr_cave + KTR_FORM);
        if (fs && f2 != form) {
            static const char* nm[3] = {"base", "AWAKENING", "REAWAKENING"};
            log_line("KAISER: >>> transform to form %d (%s) <<<",
                     f2, (f2 >= 0 && f2 <= 2) ? nm[f2] : "?");
            form = f2; lines++;
        }
        if (ls && l2 != level) {
            if (level == -12345) log_line("KAISER: level starts at %d", l2);
            else                 log_line("KAISER: level %d -> %d  (%+d)", level, l2, l2 - level);
            level = l2; lines++;
        }
        Sleep(120);
    }
    return 0;
}

static void patch_kaiser_trace(void)
{
    /* SetLevel: mov rax,[rcx+0x10] / cmp [rax+0x2D0],edx  -- 10 bytes.
       The stub writes only memory, so no register is disturbed, and the
       re-executed cmp re-sets the flags the following `je` reads. */
    static const unsigned char lv[10] =
        {0x48,0x8B,0x41,0x10, 0x39,0x90,0xD0,0x02,0x00,0x00};
    /* the transform routine: mov rax,rsp / mov [rax+0x18],rbx -- 7 bytes.
       ⚠ That first instruction CAPTURES rsp, so the stub must not push
       anything: one push and the function frames itself off a wrong rsp.
       Only rax is touched, and the stolen mov puts it back. */
    static const unsigned char fm[7] =
        {0x48,0x8B,0xC4, 0x48,0x89,0x58,0x18};
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    unsigned char* stub;
    unsigned char  b[128];
    int n, i, jskip;
    long long rel;
    DWORD old;

    if (!mod) return;
    if (memcmp(mod + KTR_HOOK_RVA, lv, sizeof(lv)) != 0 ||
        memcmp(mod + KTR_FORM_RVA, fm, sizeof(fm)) != 0) {
        log_line("KAISER: a trace site does not match (game updated?) -- trace skipped");
        return;
    }
    stub = (unsigned char*)gauge_alloc_near(mod + KTR_FORM_RVA, 0x200);
    if (!stub) { log_line("KAISER: no trampoline within +/-2GB -- trace skipped"); return; }
    memset(stub, 0, 0x200);

#define D32(o, at) do { int _d = (int)((o) - (at)); memcpy(b + n, &_d, 4); n += 4; } while (0)

    /* ---- stub 1, at cave+0: the level ------------------------------- */
    site = mod + KTR_HOOK_RVA; n = 0;
    b[n++]=0x89; b[n++]=0x15; D32(KTR_LEVEL, n + 4);          /* mov [rip+level],edx */
    b[n++]=0xF0; b[n++]=0x48; b[n++]=0xFF; b[n++]=0x05;
    D32(KTR_SEQ, n + 4);                                      /* lock inc [rip+seq]  */
    memcpy(b + n, lv, sizeof(lv)); n += (int)sizeof(lv);
    rel = (long long)(site + sizeof(lv)) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b + n, &rel, 4); n += 4;
    if (n > KTR_STUB2) { log_line("KAISER: level stub overruns -- skipped"); return; }
    memcpy(stub, b, (size_t)n);

    rel = (long long)stub - (long long)(site + 5);
    if (!VirtualProtect(site, sizeof(lv), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("KAISER: VirtualProtect failed at RVA 0x%X", KTR_HOOK_RVA); return; }
    site[0]=0xE9; memcpy(site + 1, &rel, 4);
    for (i = 5; i < (int)sizeof(lv); i++) site[i] = 0x90;
    VirtualProtect(site, sizeof(lv), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(lv));

    /* ---- stub 2, at cave+0x40: the form ----------------------------- */
    site = mod + KTR_FORM_RVA; n = 0;
    b[n++]=0x8B; b[n++]=0x81;                                  /* mov eax,[rcx+0xC00] */
    { int d = 0xC00; memcpy(b + n, &d, 4); n += 4; }
    b[n++]=0x83; b[n++]=0xF8; b[n++]=KTR_CHARA;                /* cmp eax,0x34        */
    b[n++]=0x75; jskip = n++;                                  /* jne .skip           */
    b[n++]=0x89; b[n++]=0x15; D32(KTR_FORM, KTR_STUB2 + n + 4);/* mov [rip+form],edx  */
    b[n++]=0xF0; b[n++]=0x48; b[n++]=0xFF; b[n++]=0x05;
    D32(KTR_FSEQ, KTR_STUB2 + n + 4);                          /* lock inc [rip+fseq] */
    b[jskip] = (unsigned char)(n - (jskip + 1));               /* .skip:              */
    memcpy(b + n, fm, sizeof(fm)); n += (int)sizeof(fm);
    rel = (long long)(site + sizeof(fm)) - (long long)(stub + KTR_STUB2 + n + 5);
    b[n++]=0xE9; memcpy(b + n, &rel, 4); n += 4;
    if (KTR_STUB2 + n > KTR_LEVEL) { log_line("KAISER: form stub overruns -- skipped"); return; }
    memcpy(stub + KTR_STUB2, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, 0x200);

    rel = (long long)(stub + KTR_STUB2) - (long long)(site + 5);
    if (!VirtualProtect(site, sizeof(fm), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("KAISER: VirtualProtect failed at RVA 0x%X", KTR_FORM_RVA); return; }
    site[0]=0xE9; memcpy(site + 1, &rel, 4);
    for (i = 5; i < (int)sizeof(fm); i++) site[i] = 0x90;
    VirtualProtect(site, sizeof(fm), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(fm));

#undef D32

    g_ktr_cave = stub;
    *(int*)(stub + KTR_FORM) = -1;
    CreateThread(NULL, 0, ktr_watch, NULL, 0, NULL);
    log_line("KAISER: trace ON -- Yhwach's level (RVA 0x%X) and every transform "
             "(RVA 0x%X) are logged, so the timeline names its own events. Cave %p",
             KTR_HOOK_RVA, KTR_FORM_RVA, (void*)stub);
}

/* ================= PART 35: Yhwach Reawakens on the NINTH Kaiser =====
 *  THE BUG, reported 2026-09-20: Yhwach Awakens with EIGHT Kaiser on the
 *  gauge and comes out Reawakened. He is meant to reach the Reawakening on
 *  the ninth.
 *
 *  THE GATE. Two sites, both private to this character, both testing the
 *  Kaiser level (`fighter+0x1A40`) against the image's 8.0f at 0x1414C0414
 *  while he is still in the base form:
 *
 *      0x482B62  cmp    [rdi+0xC00],0x34       ; chara id 52 = Yhwach
 *      0x482B6F  movss  xmm0,[rdi+0x1A40]      ; the Kaiser level
 *      0x482B77  comiss xmm0,[8.0f]
 *      0x482B7E  jb     <ordinary Awakening>
 *                ...builds "READY_URA_TRANSFORM", then plays `ct_revolut`
 *
 *      0x4A5ED7  cmp    [r14+0xC00],0x34       ; the same test on the
 *      0x4A5EE5  movss  xmm0,[r14+0x1A40]      ; routing side, which picks
 *      0x4A5EEE  comiss xmm0,[8.0f]            ; `revolut_start`
 *      0x4A5EF5  jb     <ordinary Awakening>
 *
 *  So `ura_transform_mothod = 3` is "Kaiser >= 8" in the binary, not the
 *  "Kaiser level 9" the Reawakening write-up recorded. The fix repoints both
 *  displacements at the 9.0f four bytes further on (0x1414C041C): two disp32
 *  fields, eight bytes of exe, nothing else touched.
 *
 *  ★★ HOW THIS WAS FOUND, because the first two answers were wrong and the
 *  way out of them is the transferable part.
 *
 *  Attempt 1 raised the 9.0f in Yhwach's per-frame handler `0x516340` to
 *  10.0, on the reading that the Awakening's `+1` was being tested before the
 *  `-0.5` records on `ct_ct_evolve` took it back. It was tested in game and
 *  changed nothing: that handler's auto-trigger is a different path from the
 *  one the player's Awakening takes.
 *
 *  Attempt 2 would have been a third reading of the same mechanic. Instead
 *  PART 36 put the question in the watcher -- one hook on the transform
 *  routine, logging the form, the CALLER and the whole unique block -- and
 *  two rounds answered everything at once:
 *
 *      form 2 (REAWAKENING) by exe+0x3A6EBC | +0x1A40 8.000  +0x1A34 8.000
 *      form 1 (AWAKENING)   by exe+0x3A6DBC | +0x1A40 6.000  +0x1A34 7.000
 *
 *  Three facts, none of them derivable from the disassembly alone:
 *    * the caller is the `Revolut` action component (0x3A6E10), not the
 *      handler patched in attempt 1 -- so the exe played `ct_revolut`;
 *    * the level was 8.000 with its mirror ALSO 8.000, so there was no
 *      transient 9 and no `-1` record had run: `ct_ct_evolve` never played,
 *      the routing chose the Reawakening before any Awakening action existed;
 *    * the control round, mirror 7 against level 6, shows the `-1` landing
 *      BEFORE the transform on the ordinary path -- which is what killed
 *      attempt 1's premise outright.
 *
 *  ★ The lesson is the one §6 of the Kaiser write-up already paid for: when
 *  a fix changes nothing, stop reasoning and instrument. One probe run cost
 *  less than either wrong answer.
 *
 *  ⚠ The `-0.5` AddUniqueVal pair on `1_normal_ct_ct_evolve` is still correct
 *  and still needed -- it cancels the `+1` the Awakening grants, which is a
 *  separate mechanic from this gate. Do not remove it with this change.
 *
 *  DataChakka: guides/Nilsix researches/Yhwach Kaiser Level/
 *              BROS_YHWACH_KAISER_LEVEL.md
 * ==================================================================== */
#define YRW_SITES      2
#define YRW_OLD_CONST  0x14C0414u  /* the 8.0f the two gates read today    */
#define YRW_NEW_CONST  0x14C041Cu  /* the 9.0f, four bytes further on      */

/* Each gate: the `comiss xmm?,[rip+disp32]` and the guard in front of it, so
   a moved function is refused instead of silently mis-patched. */
static const struct {
    unsigned       insn_rva;   /* the comiss                                */
    unsigned       disp_rva;   /* its disp32 field                          */
    unsigned       next_rva;   /* the instruction after it                  */
    unsigned       sig_rva;    /* where the signature below starts          */
    unsigned char  sig[24];
    unsigned       sig_len;
    const char*    what;
} g_yrw[YRW_SITES] = {
    { 0x482B77u, 0x482B7Au, 0x482B7Eu, 0x482B62u,
      { 0x83,0xBF,0x00,0x0C,0x00,0x00,0x34,            /* cmp [rdi+0xC00],0x34   */
        0x0F,0x85,0x1D,0x01,0x00,0x00,                 /* jne                    */
        0xF3,0x0F,0x10,0x87,0x40,0x1A,0x00,0x00 }, 21, /* movss xmm0,[rdi+0x1A40]*/
      "Yhwach's Reawakening gate -- the base-form READY_URA_TRANSFORM test" },
    { 0x4A5EEEu, 0x4A5EF1u, 0x4A5EF5u, 0x4A5ED7u,
      { 0x41,0x83,0xBE,0x00,0x0C,0x00,0x00,0x34,       /* cmp [r14+0xC00],0x34   */
        0x0F,0x85,0xB0,0x00,0x00,0x00,                 /* jne                    */
        0xF3,0x41,0x0F,0x10,0x86,0x40,0x1A,0x00,0x00 }, 23,
      "Yhwach's Reawakening gate -- the revolut_start routing test" }
};

static void patch_yhwach_reawaken(void)
{
    static const unsigned char comiss[3] = { 0x0F, 0x2F, 0x05 };
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    float old_c, new_c;
    unsigned done = 0, already = 0;
    int i;

    if (!mod) return;

    /* Verify both ends of the move once: the constant we leave and the one we
       take. A displacement landing on the wrong float is a silent balance
       change, and this is the only place that can catch it. */
    memcpy(&old_c, mod + YRW_OLD_CONST, sizeof(old_c));
    memcpy(&new_c, mod + YRW_NEW_CONST, sizeof(new_c));
    if (!(old_c == 8.0f && new_c == 9.0f)) {
        log_line("YHWACH_REAW: the float pool reads %.4f / %.4f where 8.0 / 9.0"
                 " are expected -- skipped, nothing written", old_c, new_c);
        return;
    }

    for (i = 0; i < YRW_SITES; i++) {
        unsigned char* site = mod + g_yrw[i].insn_rva;
        unsigned int   disp, want;
        DWORD old;

        memcpy(&disp, mod + g_yrw[i].disp_rva, sizeof(disp));
        want = YRW_NEW_CONST - g_yrw[i].next_rva;

        if (memcmp(site, comiss, sizeof(comiss)) != 0 ||
            memcmp(mod + g_yrw[i].sig_rva, g_yrw[i].sig, g_yrw[i].sig_len) != 0) {
            if (disp == want) { already++; continue; }
            log_line("YHWACH_REAW: exe+0x%X is not the shipped gate (game updated?)"
                     " -- skipped, nothing written at this site", g_yrw[i].insn_rva);
            continue;
        }
        if (disp == want) { already++; continue; }
        if (disp != YRW_OLD_CONST - g_yrw[i].next_rva) {
            log_line("YHWACH_REAW: exe+0x%X already points somewhere else (disp"
                     " 0x%08X) -- skipped, nothing written at this site",
                     g_yrw[i].insn_rva, disp);
            continue;
        }
        if (!bros_claim(BROS_MASTER_OWNER, g_yrw[i].disp_rva, 4, g_yrw[i].what)) {
            log_line("YHWACH_REAW: RVA 0x%X is claimed by another owner -- NOT"
                     " written. See the BROS/claim line above.", g_yrw[i].disp_rva);
            continue;
        }
        if (!VirtualProtect(mod + g_yrw[i].disp_rva, 4, PAGE_EXECUTE_READWRITE, &old)) {
            log_line("YHWACH_REAW: VirtualProtect failed at RVA 0x%X", g_yrw[i].disp_rva);
            continue;
        }
        memcpy(mod + g_yrw[i].disp_rva, &want, sizeof(want));
        VirtualProtect(mod + g_yrw[i].disp_rva, 4, old, &old);
        FlushInstructionCache(GetCurrentProcess(), site, 16);
        done++;
    }

    if (done == YRW_SITES || done + already == YRW_SITES)
        log_line("YHWACH_REAW: Reawakening gate 8.0 -> 9.0 at exe+0x%X and"
                 " exe+0x%X (%u written, %u already right). Eight Kaiser now"
                 " gives the ordinary Awakening; the Reawakening wants nine.",
                 g_yrw[0].insn_rva, g_yrw[1].insn_rva, done, already);
    else
        log_line("YHWACH_REAW: \u26a0 only %u of %u gates moved to 9.0 -- Yhwach can"
                 " still reach the Reawakening on eight through the site that did"
                 " not take. Read the lines above.", done + already, YRW_SITES);
}

/* ================= PART 36: who Reawakens Yhwach, and on what ========
 *  A first attempt raised the level gate inside Yhwach's per-frame handler
 *  `0x516340` from 9 to 10, and the bug did not move: he still Reawakened out
 *  of an Awakening taken on EIGHT Kaiser. So that gate was not the one that
 *  fires, and a third guess would have been a third wrong answer -- the trap
 *  §6 of the Kaiser write-up documents. This names the site instead of
 *  reasoning about it, and it is what found the two gates PART 35 now moves.
 *
 *  ONE HOOK, at the transform routine's entry (0x471160), where every form
 *  change in the game passes. For Yhwach and nobody else it records:
 *
 *      the form asked for   edx        0 base / 1 Awakening / 2 Reawakening
 *      WHO asked for it     [rsp]      the return address -- the call site
 *      +0x1A40              the Kaiser level, the number the HUD shows
 *      +0x1A34              its mirror, which 0x516601 writes AFTER the grant
 *                           and which no AddUniqueVal record can take back
 *      +0x1A44              the grant latch
 *      +0x1A4C  +0x1A54     the other two floats this character syncs
 *
 *  ★ +0x1A34 is in the list for a reason. `0x516601` copies the level there
 *  one instruction after the `+1`, and the -0.5 records on `ct_ct_evolve`
 *  write +0x1A40 ONLY. If a gate reads the mirror, the Awakening's grant is
 *  permanent in it while the level the player sees comes back to eight -- and
 *  that is a bug no amount of data can reach. This run says whether that is
 *  what happens.
 *
 *  ⚠ Shares its hook site with PART 16, so the two are never on together.
 *
 *  THE STUB touches rax only, and the stolen `mov rax,rsp` puts it back. It
 *  must not push: that first stolen instruction CAPTURES rsp, and one push
 *  frames the function off a wrong stack pointer -- the same warning PART 16
 *  carries, for the same site.
 * ==================================================================== */
#define YPR_RVA        0x471160u   /* the transform routine               */
#define YPR_CHARA      0x34        /* pl052                               */
#define YPR_FORM       0x100       /* dword: the form asked for           */
#define YPR_CALLER     0x108       /* qword: the return address           */
#define YPR_LV40       0x110       /* float bits: the Kaiser level        */
#define YPR_LV34       0x114       /* float bits: its mirror              */
#define YPR_LV44       0x118       /* float bits: the grant latch         */
#define YPR_LV4C       0x11C
#define YPR_LV54       0x120
#define YPR_SEQ        0x128       /* qword: transforms seen              */

static unsigned char* g_ypr_cave = NULL;

static DWORD WINAPI ypr_watch(LPVOID u)
{
    long long seen = 0;
    int lines = 0;
    (void)u;
    while (g_ypr_cave && lines < 400) {
        long long sq = *(volatile long long*)(g_ypr_cave + YPR_SEQ);
        if (sq != seen) {
            static const char* nm[3] = { "base", "AWAKENING", "REAWAKENING" };
            unsigned char* c = g_ypr_cave;
            int form = *(volatile int*)(c + YPR_FORM);
            unsigned long long who = *(volatile unsigned long long*)(c + YPR_CALLER);
            unsigned long long mb  = (unsigned long long)GetModuleHandleA(NULL);
            float lv40, lv34, lv44, lv4c, lv54;
            memcpy(&lv40, c + YPR_LV40, 4);
            memcpy(&lv34, c + YPR_LV34, 4);
            memcpy(&lv44, c + YPR_LV44, 4);
            memcpy(&lv4c, c + YPR_LV4C, 4);
            memcpy(&lv54, c + YPR_LV54, 4);
            seen = sq;
            log_line("YHWACH: form %d (%s) asked for by exe+0x%llX  |  "
                     "+0x1A40 level %.3f   +0x1A34 mirror %.3f   "
                     "+0x1A44 latch %.3f   +0x1A4C %.3f   +0x1A54 %.3f",
                     form, (form >= 0 && form <= 2) ? nm[form] : "?",
                     (mb && who > mb) ? (who - mb) : who,
                     lv40, lv34, lv44, lv4c, lv54);
            lines++;
        }
        Sleep(60);
    }
    return 0;
}

static void patch_yhwach_probe(void)
{
    static const unsigned char fm[7] =
        { 0x48, 0x8B, 0xC4, 0x48, 0x89, 0x58, 0x18 };  /* mov rax,rsp / mov [rax+0x18],rbx */
    static const unsigned int slots[5] =
        { 0x1A40u, 0x1A34u, 0x1A44u, 0x1A4Cu, 0x1A54u };
    static const unsigned int dsts[5] =
        { YPR_LV40, YPR_LV34, YPR_LV44, YPR_LV4C, YPR_LV54 };
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    unsigned char* stub;
    unsigned char  b[256];
    int n = 0, i, jskip;
    long long rel;
    DWORD old;

    if (!mod) return;
    site = mod + YPR_RVA;
    if (memcmp(site, fm, sizeof(fm)) != 0) {
        log_line("YHWACH: the transform entry at RVA 0x%X does not match (PART 16"
                 " already on, or the game updated?) -- probe skipped", YPR_RVA);
        return;
    }
    if (!bros_claim(BROS_MASTER_OWNER, YPR_RVA, (unsigned)sizeof(fm),
                    "PART 36 Yhwach transform probe (DIAGNOSTIC)")) {
        log_line("YHWACH: RVA 0x%X is claimed by another owner -- probe skipped",
                 YPR_RVA);
        return;
    }
    stub = (unsigned char*)gauge_alloc_near(site, 0x200);
    if (!stub) { log_line("YHWACH: no trampoline within +/-2GB -- probe skipped"); return; }
    memset(stub, 0, 0x200);

#define D32(o, at) do { int _d = (int)((o) - (at)); memcpy(b + n, &_d, 4); n += 4; } while (0)

    b[n++] = 0x8B; b[n++] = 0x81;                      /* mov eax,[rcx+0xC00] */
    { unsigned int dd = 0xC00u; memcpy(b + n, &dd, 4); n += 4; }
    b[n++] = 0x83; b[n++] = 0xF8; b[n++] = YPR_CHARA;  /* cmp eax,0x34        */
    b[n++] = 0x75; jskip = n++;                        /* jne .skip           */

    b[n++] = 0x89; b[n++] = 0x15; D32(YPR_FORM, n + 4);          /* mov [rip+form],edx   */
    b[n++] = 0x48; b[n++] = 0x8B; b[n++] = 0x04; b[n++] = 0x24;  /* mov rax,[rsp]        */
    b[n++] = 0x48; b[n++] = 0x89; b[n++] = 0x05;
    D32(YPR_CALLER, n + 4);                                      /* mov [rip+caller],rax */

    for (i = 0; i < 5; i++) {
        b[n++] = 0x8B; b[n++] = 0x81;                            /* mov eax,[rcx+slot]   */
        memcpy(b + n, &slots[i], 4); n += 4;
        b[n++] = 0x89; b[n++] = 0x05; D32(dsts[i], n + 4);       /* mov [rip+dst],eax    */
    }

    b[n++] = 0xF0; b[n++] = 0x48; b[n++] = 0xFF; b[n++] = 0x05;
    D32(YPR_SEQ, n + 4);                                         /* lock inc [rip+seq]   */

    b[jskip] = (unsigned char)(n - (jskip + 1));                 /* .skip:               */
    memcpy(b + n, fm, sizeof(fm)); n += (int)sizeof(fm);
    rel = (long long)(site + sizeof(fm)) - (long long)(stub + n + 5);
    b[n++] = 0xE9; memcpy(b + n, &rel, 4); n += 4;

#undef D32

    if (n > YPR_FORM) {
        log_line("YHWACH: stub overruns its own data (%d bytes) -- skipped", n);
        return;
    }
    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, 0x200);

    rel = (long long)stub - (long long)(site + 5);
    if (!VirtualProtect(site, sizeof(fm), PAGE_EXECUTE_READWRITE, &old)) {
        log_line("YHWACH: VirtualProtect failed at RVA 0x%X", YPR_RVA);
        return;
    }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    for (i = 5; i < (int)sizeof(fm); i++) site[i] = 0x90;
    VirtualProtect(site, sizeof(fm), old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof(fm));

    g_ypr_cave = stub;
    CreateThread(NULL, 0, ypr_watch, NULL, 0, NULL);
    log_line("YHWACH: probe ON -- every transform Yhwach takes is logged with the"
             " exe site that asked for it and his whole unique block. Cave %p,"
             " stub %d bytes.", (void*)stub, n);
}

/* ================= PART 37: Yhwach's level 1 in EVERY mode ===========
 *  THE BUG, reported 2026-09-21: Yhwach opens a Versus or online match on
 *  Kaiser level 1 and a TRAINING match on level 0.
 *
 *  WHY. The grant is data -- `AddUniqueVal unique_type_idx = 1` with
 *  `is_val_set = 1` on `1_normal_ct_ct_start`, the only component that action
 *  carries. `ct_start` is the battle-intro action, and Training does not play
 *  it. Nothing else in `pl052.tadjpkg` touches the level at the opening bell,
 *  so in Training it stays where the engine left it: zero.
 *
 *  ★ THE FIX IS A FLOOR, NOT A GRANT, and that is what makes it safe in every
 *  mode without knowing anything about match or round boundaries: while Yhwach
 *  is in a battle, a Kaiser level of exactly +0.0 is the bug state and nothing
 *  else. `ct_start` assigns 1, the SP grants only add, and the `-0.5` pair on
 *  `ct_ct_evolve` nets zero -- so the counter never legitimately reads 0 once a
 *  match is running. Raising 0 to 1 every frame therefore costs nothing where
 *  the data already works, and fixes the mode where it never ran.
 *  ⚠ The one thing that COULD read 0 deliberately is a combo node carrying
 *  `unique_combo = 10`, which `0x140518430` evaluates as "level <= 0". No node
 *  in `pl052.tcmbpkg` uses 10 -- checked, the file uses 2..8 only. Re-check
 *  that before anyone adds one.
 *
 *  WHERE. `0x140516340` is Yhwach's per-frame unique handler -- the function
 *  that pushes his HUD level through `ActionCharaUniqueUI_Pl52::SetLevel`,
 *  which PART 16 established "runs every frame for Yhwach and nobody else".
 *  The hook sits on the first instruction after its own null check, where
 *  `rdx` is the fighter:
 *
 *      0x516390  cmp  byte [rdx+0x9A8],0
 *      0x516397  je   0x5163B2
 *      ...
 *      0x5163B2  movups xmm0,[rdx+0x1A10]   <- stolen, and re-executed LAST so
 *      0x5163B9  movaps [rbp+0x90],xmm0        the block copy sees the new level
 *
 *  ⚠ THE FIRST ATTEMPT WAS ON THE WRONG SITE. It stole the block-reset store
 *  at `0x140460A4E` -- the right idea (write after whoever zeroes it) but an
 *  unproven one: `[rdi+0xC00]` is only READ by that function, so whether the
 *  chara id is populated there was never established, and a match played with
 *  it armed left the gauge on 0. The counter below is what said so instead of
 *  leaving "it did nothing" to mean two different things. Keep the counter.
 *
 *  THE STUB saves rax around its own use and restores it, which is safe here
 *  because this is mid-function and rsp is already framed -- unlike the
 *  transform entry PART 16 hooks, where a push would frame the callee off a
 *  captured rsp. Flags are not live at the site: it is a branch TARGET.
 *
 *  DataChakka: guides/Nilsix researches/Yhwach Kaiser Level/
 *              BROS_YHWACH_KAISER_LEVEL.md
 * ==================================================================== */
#define YSL_RVA        0x5163B2u   /* movups xmm0,[rdx+0x1A10] -- 7 bytes  */
#define YSL_STOLEN     7
#define YSL_CHARA      0x34
#define YSL_HITS       0x80        /* dword: times the floor was applied   */
#define YSL_SEEN       0x84        /* dword: times the site ran for pl052  */

static unsigned char* g_ysl_cave = NULL;

static DWORD WINAPI ysl_watch(LPVOID u)
{
    int said = 0, saw = 0, i;
    (void)u;
    /* 40 minutes: a menu walk, character select and a match all have to fit
       inside the window, which is exactly what the first attempt's 100 s did
       not. */
    for (i = 0; i < 2400 && g_ysl_cave; i++) {
        int h = *(volatile int*)(g_ysl_cave + YSL_HITS);
        int v = *(volatile int*)(g_ysl_cave + YSL_SEEN);
        if (v > 0 && !saw) {
            log_line("YHWACH_LV1: the site is running for pl052 (%d frames). The"
                     " floor is armed and will raise any Kaiser level of 0 to 1.", v);
            saw = 1;
        }
        if (h > 0 && !said) {
            log_line("YHWACH_LV1: floor applied -- Yhwach's Kaiser level was 0 and is"
                     " now 1 (%d time(s)). Training opens where Versus does.", h);
            said = 1;
        }
        Sleep(1000);
    }
    if (g_ysl_cave && !saw)
        log_line("YHWACH_LV1: \u26a0 exe+0x%X never ran for pl052. Either no Yhwach was"
                 " in a match, or this is not his per-frame handler after all -- in"
                 " which case the hook is on the wrong site again.", YSL_RVA);
    return 0;
}

static void patch_yhwach_start_level(void)
{
    /* movups xmm0, xmmword ptr [rdx + 0x1a10] */
    static const unsigned char sig[YSL_STOLEN] =
        { 0x0F, 0x10, 0x82, 0x10, 0x1A, 0x00, 0x00 };
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    unsigned char* stub;
    unsigned char  b[128];
    int n = 0, i, jchara, jlevel;
    long long rel;
    DWORD old;

    if (!mod) return;
    site = mod + YSL_RVA;
    if (memcmp(site, sig, sizeof(sig)) != 0) {
        log_line("YHWACH_LV1: exe+0x%X is not the shipped `movups xmm0,[rdx+0x1A10]`"
                 " (game updated?) -- skipped, nothing written", YSL_RVA);
        return;
    }
    if (!bros_claim(BROS_MASTER_OWNER, YSL_RVA, YSL_STOLEN,
                    "Yhwach's level-1 floor -- the block read in his per-frame handler")) {
        log_line("YHWACH_LV1: RVA 0x%X is claimed by another owner -- NOT written."
                 " See the BROS/claim line above.", YSL_RVA);
        return;
    }
    stub = (unsigned char*)gauge_alloc_near(site, 0x100);
    if (!stub) { log_line("YHWACH_LV1: no trampoline within +/-2GB -- skipped"); return; }
    memset(stub, 0, 0x100);

#define D32(o, at) do { int _d = (int)((o) - (at)); memcpy(b + n, &_d, 4); n += 4; } while (0)

    b[n++] = 0x50;                                            /* push rax           */
    b[n++] = 0x8B; b[n++] = 0x82;                             /* mov eax,[rdx+0xC00]*/
    { unsigned int dd = 0xC00u; memcpy(b + n, &dd, 4); n += 4; }
    b[n++] = 0x83; b[n++] = 0xF8; b[n++] = YSL_CHARA;         /* cmp eax,0x34       */
    b[n++] = 0x75; jchara = n++;                              /* jne .skip          */

    b[n++] = 0xF0; b[n++] = 0xFF; b[n++] = 0x05;
    D32(YSL_SEEN, n + 4);                                     /* lock inc [rip+seen]*/

    b[n++] = 0x83; b[n++] = 0xBA;                             /* cmp [rdx+0x1A40],0 */
    { unsigned int dd = 0x1A40u; memcpy(b + n, &dd, 4); n += 4; }
    b[n++] = 0x00;
    b[n++] = 0x75; jlevel = n++;                              /* jne .skip          */

    b[n++] = 0xC7; b[n++] = 0x82;                             /* mov [rdx+0x1A40],  */
    { unsigned int dd = 0x1A40u; memcpy(b + n, &dd, 4); n += 4; }
    { unsigned int one = 0x3F800000u; memcpy(b + n, &one, 4); n += 4; }   /* 1.0f   */

    b[n++] = 0xF0; b[n++] = 0xFF; b[n++] = 0x05;
    D32(YSL_HITS, n + 4);                                     /* lock inc [rip+hits]*/

    b[jlevel] = (unsigned char)(n - (jlevel + 1));            /* .skip:             */
    b[jchara] = (unsigned char)(n - (jchara + 1));
    b[n++] = 0x58;                                            /* pop rax            */
    memcpy(b + n, sig, sizeof(sig)); n += (int)sizeof(sig);   /* the stolen read    */
    rel = (long long)(site + YSL_STOLEN) - (long long)(stub + n + 5);
    b[n++] = 0xE9; memcpy(b + n, &rel, 4); n += 4;

#undef D32

    if (n > YSL_HITS) { log_line("YHWACH_LV1: stub overruns its data (%d) -- skipped", n); return; }
    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, 0x100);

    rel = (long long)stub - (long long)(site + 5);
    if (!VirtualProtect(site, YSL_STOLEN, PAGE_EXECUTE_READWRITE, &old)) {
        log_line("YHWACH_LV1: VirtualProtect failed at RVA 0x%X", YSL_RVA);
        return;
    }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    for (i = 5; i < YSL_STOLEN; i++) site[i] = 0x90;
    VirtualProtect(site, YSL_STOLEN, old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, YSL_STOLEN);

    g_ysl_cave = stub;
    CreateThread(NULL, 0, ysl_watch, NULL, 0, NULL);
    log_line("YHWACH_LV1: installed at exe+0x%X -- a FLOOR on Yhwach's Kaiser level:"
             " a level of exactly 0 becomes 1, every frame, chara-gated. `ct_start`"
             " assigns the same 1.0, so Versus and online are unchanged; Training"
             " stops opening on zero. Cave %p, stub %d bytes.",
             YSL_RVA, (void*)stub, n);
}

/* ================= PART 38: what a B press does to the intro (DIAGNOSTIC) ===
 *  THE QUESTION, from play 2026-09-21: offline, pressing B ends the pre-match
 *  character intro. Online nothing skips it, mashing included. And the button
 *  is HARDCODED, not an action binding -- Kikon was moved off B onto X, and B
 *  still skips while X does not.
 *
 *  Nothing found statically explains that. The 100 -> 200 -> 201 -> 300 walk in
 *  ActionSceneBase::vfunc27 reads no pad; SVersusAction::vfunc27, the override
 *  that only offline runs, carries no intro code at all; and the only "skip"
 *  strings in the image belong to the ADV/story player. Rather than guess at a
 *  fourth candidate, this watches the state the skip MUST pass through.
 *
 *  States 200 and 201 wait on exactly two fields of the demo manager at
 *  scene+0x318:
 *
 *      +0xE8     "a demo is playing"
 *      +0x1E8    demo state -- 2 none, 3/4 playing
 *
 *  and the demo itself is declared over by CDemoPlayer::vfunc75 when
 *  cur >= total, the two floats at +4 and +8 of the timing block at
 *  demoPlayer+0x3B0. So a skip can only have one of three shapes, and one
 *  offline match tells them apart:
 *
 *      cur jumps to total ......... the engine SEEKS the demo to its end
 *      total drops to cur ......... it shortens it, the way our data cut did
 *      +0x1E8 / +0xE8 clear alone .. it kills the demo without moving either
 *
 *  Which one it is decides what the online version has to do, and whether it
 *  inherits the teardown problem the demo_frame cut had -- a seek past the
 *  events at the end drops them, which is what left the post chain dirty and
 *  player 2 displaced (see the Intro Skip write-up).
 *
 *  The XInput button mask is on the same line, so the press frame and the
 *  effect frame are the same log entry rather than two things to correlate.
 *
 *  WHERE. ActionSceneBase::vfunc27's ENTRY -- the scene is in rcx and the
 *  state walk starts there.
 *  ⚠ Its RVA is NOT the catalogue's 0x6B22A0. That address is mid-function on
 *  the shipping 28,283,464 B build (it disassembles as the tail of a compare).
 *  0x6B3490 was found by walking back from the INTROSKIP site 0x6B35B7 --
 *  known-good on this build, byte-checked by patch_intro_skip -- to the CC
 *  padding before it. The function then measures 0x5544 bytes against the
 *  catalogue's 21,482 for vfunc27: the same function, a different build.
 *  Its first five bytes are `mov [rsp+0x18],rbx`, exactly one E9's worth.
 *
 *  READ-ONLY. It writes nothing into the game, so a build carrying it plays
 *  identically. Cost is one call per scene tick and, during an intro only, a
 *  handful of log lines.
 * ==================================================================== */
#define IPB_RVA      0x6B3490u   /* ActionSceneBase::vfunc27, function entry */
#define IPB_STOLEN   5           /* mov [rsp+0x18],rbx                        */
#define IPB_MAXLINES 400
#define IPB_SNAP     0x200   /* bytes of the demo player PART 40 diffs */

static volatile LONG   g_ipb_ticks;
static int             g_ipb_lines;
static unsigned char* volatile g_ipb_mgr;    /* the demo manager, while an intro runs */
static unsigned char* volatile g_ipb_demo;   /* the demo PLAYER -- PART 39 watches +0x110 */
static volatile LONG   g_ipb_state;
static int             g_ipb_diffs;
static int             g_ipb_last_state = -1;
static int             g_ipb_last_e8    = -1;
static int             g_ipb_last_1e8   = -1;
static float           g_ipb_last_cur   = -1.0f;
static float           g_ipb_last_tot   = -1.0f;
static unsigned        g_ipb_last_btn   = 0xFFFFFFFFu;

typedef DWORD (WINAPI *IPB_XIGS)(DWORD, void*);
static IPB_XIGS g_ipb_xi;
static int      g_ipb_xi_tried;

/* The pad, straight from XInput, so the mask is the PHYSICAL buttons and not
   whatever the game's binding layer made of them -- which is the whole point:
   the report says B skips after Kikon was moved off it. 0x2000 is B. */
static unsigned ipb_buttons(void)
{
    unsigned char st[16];
    if (!g_ipb_xi_tried) {
        static const char* dlls[3] =
            { "xinput1_4.dll", "xinput1_3.dll", "xinput9_1_0.dll" };
        int i;
        g_ipb_xi_tried = 1;
        for (i = 0; i < 3 && !g_ipb_xi; i++) {
            HMODULE h = LoadLibraryA(dlls[i]);
            if (h) g_ipb_xi = (IPB_XIGS)GetProcAddress(h, "XInputGetState");
        }
    }
    if (!g_ipb_xi) return 0;
    memset(st, 0, sizeof(st));
    if (g_ipb_xi(0, st) != ERROR_SUCCESS) return 0;
    return (unsigned)(*(unsigned short*)(st + 4));   /* XINPUT_GAMEPAD.wButtons */
}

/* The engine's string: byte 0 carries a flag in bit 0. Clear means the text is
   inline from +1 (15 chars, which every `plNNN_ct_start` fits in); set means it
   is on the heap, pointer at +0x10. Read straight off CAppDemoEvent::vfunc75,
   which branches on exactly that. */
static const char* ipb_str(unsigned char* s, char* out, int n)
{
    const char* p;
    int i;
    out[0] = 0;
    if (!s) return out;
    p = (*s & 1) ? *(const char**)(s + 0x10) : (const char*)(s + 1);
    if (!p) return out;
    for (i = 0; i < n - 1 && p[i]; i++) {
        char c = p[i];
        out[i] = (c >= 0x20 && c < 0x7F) ? c : '?';
    }
    out[i] = 0;
    return out;
}

static void intro_probe(void* scene_)
{
    unsigned char* scene = (unsigned char*)scene_;
    if (!scene || g_ipb_lines >= IPB_MAXLINES) return;
    InterlockedIncrement(&g_ipb_ticks);
    __try {
        unsigned short state = *(unsigned short*)(scene + 0x3A0);
        unsigned char* mgr;
        unsigned char* holder;
        unsigned char* demo;
        unsigned char* tim;
        unsigned  btn;
        int e8, s1e8, moved;
        float cur = -1.0f, tot = -1.0f;
        char  nm[32];

        /* only the two intro states -- everything else is the match, and this
           must not turn into a per-frame log of a whole battle. The state the
           intro LEAVES on is logged once, because which state it goes to is
           half the answer: 201 is the second fighter's intro, 300 is the fight. */
        if (state != 200 && state != 201) {
            if (g_ipb_last_state == 200 || g_ipb_last_state == 201) {
                log_line("INTROPROBE: state %d -> %u -- the intro is over "
                         "(%s), tick %ld", g_ipb_last_state, state,
                         state == 300 ? "straight to the fight, 201 skipped"
                                      : "next state", (long)g_ipb_ticks);
                g_ipb_lines++;
            }
            g_ipb_last_state = state;
            g_ipb_mgr = NULL;
            g_ipb_demo = NULL;
            return;
        }

        mgr = *(unsigned char**)(scene + 0x318);
        if (!mgr) return;
        g_ipb_mgr   = mgr;
        g_ipb_state = state;
        e8   = *(unsigned char*)(mgr + 0xE8);
        s1e8 = *(int*)(mgr + 0x1E8);

        holder = *(unsigned char**)(scene + 0x440);
        demo   = holder ? *(unsigned char**)(holder + 0x370) : NULL;
        tim    = demo   ? *(unsigned char**)(demo + 0x3B0)   : NULL;
        if (tim) { cur = *(float*)(tim + 4); tot = *(float*)(tim + 8); }
        g_ipb_demo = demo;          /* PART 39 arms its watchpoint on this */

        btn = ipb_buttons();

        /* A line per CHANGE, plus every button edge. Frame-to-frame the cursor
           advances by one, which would be a line a frame -- so a move of more
           than two frames in a tick is what counts as movement, and that is
           exactly the signature of a seek. */
        moved = (state != g_ipb_last_state) || (e8 != g_ipb_last_e8) ||
                (s1e8 != g_ipb_last_1e8) || (btn != g_ipb_last_btn) ||
                (g_ipb_last_tot >= 0.0f && tot != g_ipb_last_tot) ||
                (g_ipb_last_cur >= 0.0f && (cur - g_ipb_last_cur > 2.0f ||
                                            cur < g_ipb_last_cur));
        if (moved) {
            log_line("INTROPROBE: state %u  demo %s  playing %d  demoState %d  "
                     "cur %.1f / total %.1f  pad %04X%s  (prev cur %.1f/%.1f, tick %ld)",
                     state, ipb_str(mgr + 0xF0, nm, sizeof(nm)), e8, s1e8,
                     cur, tot, btn, (btn & 0x2000) ? " <-- B" : "",
                     g_ipb_last_cur, g_ipb_last_tot, (long)g_ipb_ticks);
            g_ipb_lines++;
        }
        g_ipb_last_state = state;
        g_ipb_last_e8    = e8;
        g_ipb_last_1e8   = s1e8;
        g_ipb_last_cur   = cur;
        g_ipb_last_tot   = tot;
        g_ipb_last_btn   = btn;

        /* ★ PART 40, and it is where the answer has to be. The unwind (PART 39)
           says the play flag is cleared from vfunc46, called from vfunc11's
           ordinary "this demo is over" branch -- the same path a demo that runs
           to its end takes. So the press does not call anything: it makes
           vfunc11's end test true early, and that test is
               slot 74 (is playing) == false   OR   slot 75 (finished) == true
           on the DEMO PLAYER. The cursor and the total do not move at the press,
           so it is the player's own state that flips. Diff its bytes and the
           field names itself -- read-only, no vtable call, no guess about a
           signature (UI_SYSTEM.md §7 is what that rule cost somebody else). */
        /* ⚠⚠ KEYED BY THE OBJECT, and the first version was not. `demo` is
           per-scene and the holder swaps it between demos, so a snapshot taken
           from one object and diffed against another prints changes that never
           happened -- which is exactly what "+0x110 00->01 +0x118 00->01" was.
           DataChakka's own three-player work names this trap twice (§7.13,
           §8.1): a probe handed the object and throwing it away cannot be
           trusted about that object. One line fixes it: remember the pointer. */
        if (demo) {
            static unsigned char prev[IPB_SNAP];
            static unsigned char* prev_obj;
            static int have_prev;
            if (prev_obj != demo) { have_prev = 0; prev_obj = demo; }
            unsigned char now[IPB_SNAP];
            memcpy(now, demo, sizeof(now));
            if (have_prev && g_ipb_diffs < 40) {
                char out[200];
                int at = 0, k, shown = 0;
                for (k = 0; k < (int)sizeof(now) && shown < 6; k++) {
                    if (now[k] == prev[k]) continue;
                    at += snprintf(out + at, sizeof(out) - at, "+0x%X %02X->%02X ",
                                   k, prev[k], now[k]);
                    shown++;
                }
                if (shown) {
                    g_ipb_diffs++;
                    log_line("INTRODIFF: demoPlayer %s%s(cur %.0f, tick %ld)", out,
                             shown >= 6 ? "... " : "", cur, (long)g_ipb_ticks);
                }
            }
            memcpy(prev, now, sizeof(prev));
            have_prev = 1;
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        /* one of the offsets is not what the catalogue says on this build --
           say so once and stop, rather than fault every frame */
        g_ipb_lines = IPB_MAXLINES;
        log_line("INTROPROBE: faulted walking the scene -- one of scene+0x318 / "
                 "+0x440 / demo+0x3B0 does not hold on this build. Probe stopped, "
                 "nothing else changes.");
    }
}

/* ================= PART 41: who reads the pad during the intro =============
 *  Four probes have now walked DOWN from the effect -- play flag, teardown,
 *  demo player, the 16-byte property -- and each one landed on machinery every
 *  demo runs through, skipped or not. The reason is structural: the press does
 *  not call anything of its own, so there is no distinctive frame to find below
 *  the decision.
 *
 *  So go at it from the INPUT end instead, where the press is by definition
 *  distinctive. `AppPad::vfunc0` (RVA 0xE9510 on the shipping build, a real
 *  function entry: `push rsi / push rdi / push r15`, preceded by CC padding) is
 *  the polled state getter -- TOTAL_CAPTURE.md §L2 calls it exactly that, and
 *  its address needs no re-anchoring because the catalogue and the shipping
 *  build agree below ~0x1C0000.
 *
 *  This logs the RETURN ADDRESS of every caller of it, deduplicated, and only
 *  while the scene is in state 200/201. The intro lasts a few seconds, so the
 *  list is short, and the consumer that only appears when B is pressed is the
 *  skip. Read-only.
 *
 *  ⚠ It needs the caller, not `this`, so it cannot use gauge_install_hook --
 *  that passes rcx or rdx. The stub below is the same shape plus one
 *  instruction: the hook replaces the function's first bytes, so at hook entry
 *  the call's return address is still at [rsp], and after `push rbp / mov
 *  rbp,rsp` it is at [rbp+8]. That is what goes into rcx.
 * ==================================================================== */
#define IPP_STOLEN  5
#define IPP_ROWS    24

/* ⚠ Cover the whole polled set, not just the getter. TOTAL_CAPTURE.md §L2 names
   three: vfunc0 the state getter (78 callers) and vfunc4/vfunc5 at 262 bytes
   each. If the battle intro reads a *pressed/triggered* view rather than raw
   state, hooking only vfunc0 comes back empty -- and an empty result would read
   as "nothing polls the pad during an intro", which is a conclusion, not a
   measurement. All three entries are 5-byte, rip-free prologues, and all three
   sit below 0x13FC10 where the catalogued and installed builds coincide 100%
   (TOTAL_CAPTURE.md §5.4), so no porting is involved. */
static const struct { unsigned rva; unsigned char sig[IPP_STOLEN]; const char* what; }
g_ipp_sites[] = {
    { 0xE9510u, { 0x40, 0x56, 0x57, 0x41, 0x57 }, "vfunc0 state getter" },
    { 0xE9840u, { 0x48, 0x89, 0x5C, 0x24, 0x10 }, "vfunc4" },
    { 0xE9950u, { 0x48, 0x89, 0x5C, 0x24, 0x10 }, "vfunc5" },
};

static LONG g_ipp_rip[IPP_ROWS];
static LONG g_ipp_n[IPP_ROWS];
static int  g_ipp_lines;

static void intro_pad_caller(void* ret)
{
    LONG st = g_ipb_state;
    unsigned char* mod;
    LONG r;
    int k;
    if (!g_ipb_mgr || (st != 200 && st != 201)) return;
    mod = (unsigned char*)GetModuleHandleA(NULL);
    if (!mod || !ret) return;
    r = (LONG)((unsigned char*)ret - mod);
    for (k = 0; k < IPP_ROWS; k++) {
        if (g_ipp_rip[k] == r) { g_ipp_n[k]++; return; }
        if (g_ipp_rip[k] == 0) {
            g_ipp_rip[k] = r; g_ipp_n[k] = 1;
            if (g_ipp_lines < IPP_ROWS) {
                g_ipp_lines++;
                log_line("INTROPAD: the pad is read from exe+0x%X during the intro "
                         "(state %ld, cur tick %ld)", (unsigned)r, (long)st,
                         (long)g_ipb_ticks);
            }
            return;
        }
    }
}

static void patch_intro_pad_one(unsigned rva, const unsigned char* sig, const char* what)
{
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char* site;
    unsigned char* stub;
    unsigned char  b[192];
    void* payload = (void*)intro_pad_caller;
    int n = 0;
    long long rel;
    DWORD old;

    if (!mod) return;
    site = mod + rva;
    if (memcmp(site, sig, IPP_STOLEN) != 0) {
        log_line("INTROPAD: exe+0x%X is not AppPad's %s prologue (game "
                 "updated?) -- that site skipped", rva, what);
        return;
    }
    if (!bros_claim(BROS_MASTER_OWNER, rva, IPP_STOLEN,
                    "PART 41 intro pad-caller probe (DIAGNOSTIC)")) {
        log_line("INTROPAD: exe+0x%X is claimed by another owner -- that site skipped",
                 rva);
        return;
    }
    stub = (unsigned char*)gauge_alloc_near(site, 256);
    if (!stub) { log_line("INTROPAD: no trampoline within +/-2GB -- probe skipped"); return; }

    b[n++]=0x55;                                            /* push rbp          */
    b[n++]=0x48; b[n++]=0x89; b[n++]=0xE5;                  /* mov  rbp,rsp      */
    b[n++]=0x51; b[n++]=0x52;                               /* push rcx, rdx     */
    b[n++]=0x41; b[n++]=0x50; b[n++]=0x41; b[n++]=0x51;     /* push r8, r9       */
    b[n++]=0x41; b[n++]=0x52; b[n++]=0x41; b[n++]=0x53;     /* push r10, r11     */
    b[n++]=0x50;                                            /* push rax          */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xE4; b[n++]=0xF0;     /* and  rsp,-16      */
    b[n++]=0x48; b[n++]=0x83; b[n++]=0xEC; b[n++]=0x60;     /* sub  rsp,0x60     */
    b[n++]=0x0F; b[n++]=0x11; b[n++]=0x44; b[n++]=0x24; b[n++]=0x20;
    b[n++]=0x0F; b[n++]=0x11; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;
    b[n++]=0x0F; b[n++]=0x11; b[n++]=0x54; b[n++]=0x24; b[n++]=0x40;
    b[n++]=0x0F; b[n++]=0x11; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x50;
    b[n++]=0x48; b[n++]=0x8B; b[n++]=0x4D; b[n++]=0x08;     /* mov rcx,[rbp+8]   */
    b[n++]=0x48; b[n++]=0xB8; memcpy(b + n, &payload, 8); n += 8;
    b[n++]=0xFF; b[n++]=0xD0;                               /* call rax          */
    b[n++]=0x0F; b[n++]=0x10; b[n++]=0x44; b[n++]=0x24; b[n++]=0x20;
    b[n++]=0x0F; b[n++]=0x10; b[n++]=0x4C; b[n++]=0x24; b[n++]=0x30;
    b[n++]=0x0F; b[n++]=0x10; b[n++]=0x54; b[n++]=0x24; b[n++]=0x40;
    b[n++]=0x0F; b[n++]=0x10; b[n++]=0x5C; b[n++]=0x24; b[n++]=0x50;
    b[n++]=0x48; b[n++]=0x8D; b[n++]=0x65; b[n++]=0xC8;     /* lea rsp,[rbp-0x38]*/
    b[n++]=0x58;                                            /* pop rax           */
    b[n++]=0x41; b[n++]=0x5B; b[n++]=0x41; b[n++]=0x5A;     /* pop r11, r10      */
    b[n++]=0x41; b[n++]=0x59; b[n++]=0x41; b[n++]=0x58;     /* pop r9, r8        */
    b[n++]=0x5A; b[n++]=0x59;                               /* pop rdx, rcx      */
    b[n++]=0x5D;                                            /* pop rbp           */
    memcpy(b + n, site, IPP_STOLEN); n += IPP_STOLEN;
    rel = (long long)(site + IPP_STOLEN) - (long long)(stub + n + 5);
    b[n++]=0xE9; memcpy(b + n, &rel, 4); n += 4;

    memcpy(stub, b, (size_t)n);
    FlushInstructionCache(GetCurrentProcess(), stub, (size_t)n);

    rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("INTROPAD: trampoline out of rel32 range -- probe skipped"); return;
    }
    if (!VirtualProtect(site, IPP_STOLEN, PAGE_EXECUTE_READWRITE, &old)) {
        log_line("INTROPAD: VirtualProtect failed at RVA 0x%X", rva); return;
    }
    site[0] = 0xE9; memcpy(site + 1, &rel, 4);
    VirtualProtect(site, IPP_STOLEN, old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, IPP_STOLEN);
    log_line("INTROPAD: read-only probe on AppPad::%s (exe+0x%X) -- names every "
             "caller of it while the scene is in state 200/201, once each.",
             what, rva);
}

/* ================= PART 42: the intro skip, for an ONLINE player ===========
 *  THE GATE, measured rather than guessed (rig attempt #155, 2026-09-21).
 *
 *  The press-to-skip intro is vtable **slot 47** (`+0x178`). Every scene class in
 *  the family inherits ONE implementation, `exe+0x6CDD70`, and that function is
 *  the whole feature: it walks both player indices, reads the SYSTEM pad through
 *  `AppPad::vfunc0`, masks `0x10`, and then requires the demo now playing to be
 *  named in a two-entry whitelist at RVA 0x18EEC38 -- literally "ct_start" and
 *  "_VDEMO". Either player pressing is enough. That is why B skips the battle
 *  intro, why it skips nothing else, and why rebinding Kikon off B changes
 *  nothing: the mask is on the system pad, not on an action binding.
 *
 *  `SOnlineAction` is the ONLY class in the family that overrides that slot, and
 *  its override `exe+0x805AC0` is not "never skip" -- it is the SPECTATOR's
 *  fast-forward:
 *
 *      eax = [scene+0xC34]            ; battle role: 0 player, 1 leader, 2 member
 *      if ((eax - 1) > 1) return 0    ; A PLAYER IS ROLE 0 -> always false
 *      mgr = OnlineLiveStreamingDataManager::Get()          ; 0x1401AF7F0
 *      return ([mgr+0x28]-[mgr+0x20])/0x68 > (u16)[mgr+0x38]
 *
 *  So an online player cannot skip because a function written for the gallery
 *  answers in its place. The caller, `exe+0x6AA2A9` inside `vfunc11`, is shared
 *  and ungated -- it asks in every mode. The whole online gate is those four
 *  instructions.
 *
 *  WHAT THIS DOES. Repoints SOnlineAction's slot 47 -- and only that slot, a copy
 *  private to one class, never a shared body (MODDING_RULES rule 7, and the same
 *  shape the Byakuya form-getter work had to learn the hard way). For a spectator
 *  it tail-calls the original, so the gallery is untouched. For a player it:
 *
 *      1. asks the ENGINE'S OWN check `0x6CDD70` whether this client's pad is
 *         asking to skip -- no new input code, no whitelist of ours, and the
 *         teardown stays the engine's, which is what keeps the cast placement
 *         right (the data-side `demo_frame` cut got that wrong and displaced
 *         player 2; the engine's own path demonstrably does not);
 *      2. announces sync slot OIS_SYNC_SLOT through the engine's own rendezvous
 *         primitive `exe+0x806E80` -- the one whose assert names it,
 *         L"sync < 32" at SOnlineAction.cpp:0xBEC;
 *      3. returns true as soon as EITHER seat's word carries the bit.
 *
 *  One press by one player is enough, deliberately. A bit announced on a sync
 *  slot is a REQUEST, not a vote -- the room-match result menu learned that the
 *  expensive way, when "announce slot 8 on the way out" was read by the peer as
 *  "I want the rematch" and restarted a fight against somebody who had left.
 *  Here that semantic is exactly the feature.
 *
 *  IT CHANGES WHEN THE MATCH STARTS, so it takes its own matchmaking pool
 *  (OIS_POOL_TAG). A client running this against a stock one disagrees about the
 *  first second of every match.
 *
 *  The sync word carries ONE shared `value` field at +4, not one per slot, so
 *  announcing overwrites whatever another slot last put there. We announce value
 *  0 for that reason, and the primitive is idempotent once the bit and the value
 *  already match, so it is announced once per intro rather than per frame.
 *
 *  STILL UNPROVEN, and it is the thing to watch in the rig: whether the netcode's
 *  frame counter is anchored before or after the intro. If after, a skip is free;
 *  if before, the two clients enter the fight a round-trip apart. The intro-skip
 *  write-up has flagged this since August and no measurement has settled it.
 *  Watch for a desync in the first seconds, not for a crash.
 *
 *  Live anchors (shipping build 28,283,464 B) -- none from the catalogue, which
 *  describes the other build above RVA 0x13FC10:
 *      0x1414A3888   SOnlineAction's vtable   (RTTI-resolved)
 *      +0x178        slot 47
 *      0x805AC0      its override              (the gate)
 *      0x6CDD70      the real check            (rcx = scene -> bool)
 *      0x806E80      SyncPoint(this, id, value)
 *      scene+0xBC0 / +0xC3C / +0xC40 / +0xC34   box, my seat, peer seat, role
 * ==================================================================== */
#define OIS_VTABLE_RVA   0x14A3888u
#define OIS_SLOT         47
#define OIS_ORIG_RVA     0x805AC0u
#define OIS_CHECK_RVA    0x6CDD70u
#define OIS_SYNC_RVA     0x806E80u
#define OIS_POOL_TAG     4004

typedef unsigned char (*OIS_CHECK)(void*);
typedef unsigned char (*OIS_SYNC)(void*, unsigned, unsigned);

static OIS_CHECK g_ois_orig;      /* SOnlineAction's own override        */
static OIS_CHECK g_ois_base;      /* the real check, 0x6CDD70            */
static OIS_SYNC  g_ois_sync;      /* SyncPoint                           */
static volatile LONG g_ois_asked, g_ois_agreed;
static unsigned char* volatile g_ois_demo;   /* the demo player the last intro ran on */
static char g_ois_last_name[64];   /* the last demo NAME logged -- the object is pooled */
#define OIS_NAME_BUDGET 12
static volatile LONG g_ois_named;
static volatile LONG g_ois_gallery;   /* the gallery skipped its own intro */
static volatile LONG g_ois_in_intro;  /* edge detector: an intro is on screen now */
static volatile LONG g_ois_intro_seq; /* which intro of this session it is        */
static volatile LONG g_ois_said_press, g_ois_said_end;
static volatile LONG g_ois_gal_lines;   /* per-intro budget for the gallery probe */
static ULONGLONG     g_ois_gal_tick;
static LONG64        g_ois_gal_base = -1;  /* queue length when this intro opened */

/* Is the bit set in either seat's word? The primitive writes MY word (indexed by
   +0xC3C) and the peer's arrives over PacketSyncMessage into its own (+0xC40),
   so both have to be read -- reading only one is how the AreaMove barrier ends
   up waiting forever for a mark addressed to somebody else. */
/* Returns a MASK, not a flag: bit 0 = my own word carries it, bit 1 = the peer's
   does. Which one matters -- "I asked", "the peer asked" and "it was already set
   when this intro began" are three different events and a bool calls them one. */
static int ois_announced(unsigned char* scene)
{
    int seen = 0;
    __try {
        unsigned char* box = *(unsigned char**)(scene + 0xBC0);
        unsigned char** words;
        int me, peer, i;
        if (!box) return 0;
        words = *(unsigned char***)(box + 0x20);
        if (!words) return 0;
        me   = *(int*)(scene + 0xC3C);
        peer = *(int*)(scene + 0xC40);
        for (i = 0; i < 2; i++) {
            int idx = i ? peer : me;
            unsigned* w;
            if (idx < 0) continue;
            w = (unsigned*)words[idx];
            if (w && (w[0] & (1u << OIS_SYNC_SLOT))) seen |= (i ? 2 : 1);
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) { }
    return seen;
}

/* The demo playing right now, and its name -- the SAME chain 0x6CDD70 walks at
   +0x12E, read off the disassembly rather than guessed:

        rcx = [scene+0x440]          ; the demo holder
        rax = [rcx+0x390]            ; a guard object; if null, or [rax+8] == 0,
                                     ;   the engine uses an EMPTY name instead
        rax = [rcx+0x370]            ; the demo PLAYER
        rdx = [rax+0x400]            ; <<< a char*, null-tested before std::string

   `*demo_out` is the player object, which is what tells one demo from the next:
   the holder swaps it, and a snapshot not keyed on it is exactly how PART 40
   invented a field that does not exist. */
static const char* ois_demo_name(unsigned char* scene, unsigned char** demo_out)
{
    const char* name = NULL;
    if (demo_out) *demo_out = NULL;
    __try {
        unsigned char* holder = *(unsigned char**)(scene + 0x440);
        unsigned char* guard;
        unsigned char* demo;
        if (!holder) return NULL;
        guard = *(unsigned char**)(holder + 0x390);
        if (!guard || *(int*)(guard + 8) == 0) return NULL;
        demo = *(unsigned char**)(holder + 0x370);
        if (!demo) return NULL;
        if (demo_out) *demo_out = demo;
        name = *(const char**)(demo + 0x400);
    } __except (EXCEPTION_EXECUTE_HANDLER) { return NULL; }
    return name;
}

static int ois_is_intro(const char* name)
{
    const char* p;
    if (!name) return 0;
    __try {
        for (p = name; *p; p++)
            if (p[0] == 'c' && p[1] == 't' && p[2] == '_' && p[3] == 's' &&
                p[4] == 't' && p[5] == 'a' && p[6] == 'r' && p[7] == 't') return 1;
    } __except (EXCEPTION_EXECUTE_HANDLER) { return 0; }
    return 0;
}

/* Did ANY seat announce the skip? The gallery cannot use `ois_announced()`: it
   wears player 1's seat pair (+0xC3C = 0, +0xC40 = 1, identical to the host --
   BROS_THREE_PLAYER_ROOM §7), so the word it reads through its own mapping is the
   host's entry and the players' announcement need not land there. The result-menu
   follow hit exactly this and the probe beside it had to walk the whole array.

   So walk it: `[box+0x20]` to `[box+0x28]`, one pointer per seat, and report the
   index that carries the bit rather than just that somebody does -- that is the
   thing nobody has measured yet, and one run of this answers it. */
static int ois_any_seat_announced(unsigned char* scene, int* which)
{
    int found = -1;
    __try {
        unsigned char* box = *(unsigned char**)(scene + 0xBC0);
        unsigned char** beg;
        unsigned char** end;
        int k = 0;
        if (!box) return 0;
        beg = *(unsigned char***)(box + 0x20);
        end = *(unsigned char***)(box + 0x28);
        while (beg && beg + k < end && k < 8) {
            unsigned* w = (unsigned*)beg[k];
            if (w && (w[0] & (1u << OIS_SYNC_SLOT))) { found = k; break; }
            k++;
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) { return 0; }
    if (which) *which = found;
    return found >= 0;
}

static unsigned char ois_slot47(void* scene_)
{
    unsigned char* scene = (unsigned char*)scene_;
    unsigned char* demo = NULL;
    const char* name;
    int role = 0;
    __try { role = *(int*)(scene + 0xC34); }
    __except (EXCEPTION_EXECUTE_HANDLER) { return 0; }

    /* NOT A PLAYER -- the gallery.
       The shipped override IS a fast-forward: it answers "skip this demo" while
       there are more records available than consumed, and it reads those counts
       off `OnlineLiveStreamingDataManager::Get()`. On the ROOM3 path that object
       is NOT the one carrying our records -- the pipe fills the playback queue on
       the sync box (`scene+0xBC0`, the +0xD0/+0xD8/+0xE8 triple P37 reads) -- so
       it asks an empty manager and always answers no. That is why a spectator
       sat through the whole intro and then carried it as delay for the rest of
       the match, measured at 770 queued against 514 played on rig #159.

       ★ It is left that way for the INTRO on purpose. The requirement is that
       the skip is a press for every seat, so the gallery is given the same check
       a player gets rather than an automatic answer; the delay is the price and
       a press pays it. Every other demo still goes to the shipped override
       untouched. */
    if (role != 0) {
        const char* gname = ois_demo_name(scene, NULL);
        if (ois_is_intro(gname)) {
            /* ⚠ THE INTRO IS NEVER SKIPPED WITHOUT A PRESS -- not even here.
               An earlier version answered "skip" as soon as records were queued,
               which is what the shipped fast-forward means to do and it removed
               the gallery's intro lag for free. It was rejected on purpose: a
               spectator that never watches an intro is a skip nobody asked for,
               and the rule is the same for every seat. So the gallery gets the
               ENGINE'S OWN CHECK, exactly like a player -- its own pad, its own
               press -- and nothing else.

               It is not announced on a sync slot and does not need to be: a
               gallery client replays a stream, so ending its own intro early is
               local. It also shortens the delay it carries, because it starts
               consuming records sooner. */
            if (!g_ois_in_intro) {
                g_ois_in_intro = 1;
                g_ois_intro_seq++;
                g_ois_said_press = 0;
                g_ois_said_end   = 0;
                g_ois_gal_lines = 0;
                g_ois_gal_tick  = 0;
                g_ois_gal_base  = -1;   /* re-baselined on the first frame of each intro */
                log_line("ONLINESKIP: intro #%d begins on the GALLERY (role %d) -- the "
                         "gallery has no press of its own; it follows the players or it "
                         "watches", g_ois_intro_seq, role);
            }
            /* ⚠ THE GALLERY HAS NO PRESS OF ITS OWN, deliberately.
               Measured on rig #170: a spectator that ends its own ct_start gains
               nothing -- its scene is driven by the recorded stream, so it then
               sits waiting for the two fighters to finish theirs anyway. The
               skip was cosmetic and it let one viewer desynchronise their own
               view for no benefit. What it MUST do instead is follow the players.

               ⚠⚠ AND THE SYNC WORD CANNOT CARRY THAT. Measured the same run:
               BROS3 pressed and announced slot 11, BROS2 followed on the peer's
               seat 41 ms later, and the gallery -- scanning all eight seat words
               of its own box -- saw nothing at all. A gallery client's sync words
               stay zero, exactly as BROS_SPECTATOR_MODE §3.3 says. That route is
               closed, and this is a measurement, not a guess.

               So the signal has to come from the stream the gallery actually
               consumes. The probe below prints what that stream looks like during
               a gallery intro; one run with a player skip and one without names
               the field that differs. Until then the gallery simply watches. */
            /* ★★ THE SIGNAL IS THE QUEUE, and it was measured rather than
               reasoned about (rig #171, intro #1):

                 10:28:37.177  gallery intro begins        queue 0
                 10:28:37.946  BROS2 presses, announces    queue 0
                 10:28:38.170                              queue 0
                 10:28:38.416                              queue 20   <- starts
                 ... then ~60 records a second, the fight being recorded

               **The host produces no records while it is in its own intro.** The
               queue sits at zero for as long as the players are watching, and
               starts filling the moment they leave -- whether they pressed or sat
               through all 570 frames. So `queue > 0` is exactly "the players are
               no longer in the intro", which is the thing the gallery has to
               follow, and it is not an automatic skip: it is the players' own
               timing, arriving by the only channel a gallery client has.

               The sync word cannot do this job -- measured the same run, the
               gallery saw slot 11 on no seat at any point while both players
               announced it to each other. */
            {
                LONG64 len = -1;
                __try {
                    unsigned char* box = *(unsigned char**)(scene + 0xBC0);
                    if (box)
                        len = (LONG64)((*(unsigned char**)(box + 0xD8) -
                                        *(unsigned char**)(box + 0xD0)) / 0x68);
                } __except (EXCEPTION_EXECUTE_HANDLER) { len = -1; }

                /* ⚠⚠ NOT `len > 0` -- THE QUEUE IS CUMULATIVE ACROSS THE SESSION
                   and is never cleared between battles. Measured, rig #172: the
                   gallery's intro #2 opened with 1742 records already in it, #3
                   with 2318, #4 with 2945, all left over from earlier matches, so
                   a test on the value fired 12 ms into every intro after the
                   first. That is the third time today a field carrying the past
                   was read as if it carried the present -- the sticky sync bit
                   and the pooled demo object were the other two.

                   What actually means "the players are out of their intro" is the
                   queue GROWING: the host records nothing while it is in its own
                   intro, so the length is flat until they leave it, whether they
                   pressed or watched all 570 frames. Baseline at the edge, follow
                   on growth. */
                if (g_ois_gal_base < 0) {
                    g_ois_gal_base = len;
                    log_line("ONLINESKIP/gal: intro #%d -- baseline %lld record(s) already "
                             "queued from earlier matches; the gallery follows when this "
                             "GROWS, which is the host recording again",
                             g_ois_intro_seq, len);
                }
                else if (len > g_ois_gal_base) {
                    if (!g_ois_said_end) {
                        g_ois_said_end = 1;
                        log_line("ONLINESKIP: intro #%d -- the players have left their "
                                 "intro (queue %lld, up from %lld), so the gallery follows",
                                 g_ois_intro_seq, len, g_ois_gal_base);
                    }
                    return 1;
                }
                /* flat: the players are still watching, so this client watches too */
                {
                    ULONGLONG now = GetTickCount64();
                    if (now - g_ois_gal_tick >= 1000 && g_ois_gal_lines < 15) {
                        g_ois_gal_tick = now;
                        InterlockedIncrement(&g_ois_gal_lines);
                        log_line("ONLINESKIP/gal: intro #%d -- queue flat at %lld, the "
                                 "players are still in their own intro",
                                 g_ois_intro_seq, len);
                    }
                }
            }
            return 0;
        }
        g_ois_in_intro = 0;
        return g_ois_orig ? g_ois_orig(scene_) : 0;
    }

    /* ★ THE ANNOUNCEMENT IS STICKY, AND THIS SLOT IS ASKED FOR EVERY DEMO.
       `vfunc11` calls slot 47 whenever a demo is playing, and the engine's own
       whitelist at 0x18EEC38 has TWO entries -- "ct_start" AND "_VDEMO". Once a
       player has announced slot OIS_SYNC_SLOT the bit stays set in that seat's
       word for the rest of the battle, so without this gate `ois_announced()`
       answered "skip" for the victory demo as well, with nobody touching a
       button: the end animation was cut short. Reported from play, 2026-09-21.

       So: this patch is the INTRO skip and nothing else. Any other demo gets the
       stock online answer, which is 0 -- what SOnlineAction's own override
       returns for a player. */
    name = ois_demo_name(scene, &demo);

    /* Name every demo this slot is asked about, once per demo object, with the
       state of the bit at that moment. Two lines of log answer the question the
       fix above is built on -- WHICH demos reach slot 47 after the intro, and
       whether the victory one is among them -- instead of leaving it as a
       deduction from the whitelist. */
    if (g_ois_named < OIS_NAME_BUDGET) {
        char buf[64];
        int i = 0;
        buf[0] = 0;
        __try {
            if (name) { for (; i < 63 && name[i]; i++) buf[i] = name[i]; }
        } __except (EXCEPTION_EXECUTE_HANDLER) { i = 0; }
        buf[i] = 0;
        /* ★ Keyed on the NAME, never on the demo object. Rig #158 logged exactly one
           line for a whole match, which looked like "no other demo reaches slot 47"
           and is not: the holder HANDS BACK THE SAME PLAYER OBJECT for the next
           demo, so an object-keyed log goes silent while the name underneath it
           changes. That is also why the fix above tests the name -- an object-keyed
           latch would not have caught the victory demo at all. */
        if (memcmp(buf, g_ois_last_name, sizeof(buf)) == 0) goto ois_named_done;
        memcpy(g_ois_last_name, buf, sizeof(buf));
        InterlockedIncrement(&g_ois_named);
        log_line("ONLINESKIP/demo: slot 47 asked about \"%s\" (skippable by the "
                 "engine's whitelist: %s; slot %d currently %s) -- %s",
                 buf, ois_is_intro(name) ? "as ct_start" : "not as ct_start",
                 OIS_SYNC_SLOT, ois_announced(scene) ? "SET" : "clear",
                 ois_is_intro(name) ? "this is the intro, we answer it"
                                    : "not the intro, we return 0 and leave it alone");
    }
ois_named_done:

    if (!ois_is_intro(name)) { g_ois_in_intro = 0; return 0; }

    /* A fresh intro: note it, and say whether the bit was ALREADY set when it
       began. That is the open question about whether the sync word survives a
       rematch, and the cheapest place to answer it is here rather than by
       reasoning about it. */
    if (demo && demo != g_ois_demo) {
        g_ois_demo = demo;
        if (ois_announced(scene))
            log_line("ONLINESKIP: a new ct_start began with slot %d ALREADY set -- "
                     "the sync word survives from the previous battle, so this "
                     "intro ends without anybody pressing", OIS_SYNC_SLOT);
    }

    /* ⚠ ONE LINE PER INTRO, not one per process. The first version guarded these
       with InterlockedIncrement(...) == 1, so the SECOND match of a session
       announced and skipped in complete silence -- and a silent log reads exactly
       like code that did nothing. That is the same trap as the object-keyed demo
       log, twice in one day. g_ois_intro_seq rises on the edge into each intro
       and every line below is emitted once per intro. */
    {
        int mask = ois_announced(scene);
        if (!g_ois_in_intro) {
            g_ois_in_intro = 1;
            g_ois_intro_seq++;
            g_ois_said_press = 0;
            g_ois_said_end   = 0;
            /* ⚠ "already set" is NOT automatically a stale bit. The two clients
               do not enter their intros together -- 5 s apart was measured on
               rig #167 -- so a peer who pressed first is already announced when
               the second client's intro opens. Read the seat, not the flag. */
            log_line("ONLINESKIP: intro #%d begins -- slot %d is %s at this point "
                     "(mine %s, peer %s). Peer-set here usually means the peer "
                     "pressed before this client's intro opened.",
                     g_ois_intro_seq, OIS_SYNC_SLOT, mask ? "ALREADY SET" : "clear",
                     (mask & 1) ? "set" : "clear", (mask & 2) ? "set" : "clear");
        }
        if (g_ois_base && g_ois_base(scene_)) {
            if (!g_ois_said_press) {
                g_ois_said_press = 1;
                log_line("ONLINESKIP: intro #%d -- THIS client's pad is asking to skip; "
                         "announcing sync slot %d", g_ois_intro_seq, OIS_SYNC_SLOT);
            }
            if (g_ois_sync) {
                __try { g_ois_sync(scene_, OIS_SYNC_SLOT, 0); }
                __except (EXCEPTION_EXECUTE_HANDLER) { }
            }
            mask = ois_announced(scene);
        }
        if (mask) {
            if (!g_ois_said_end) {
                g_ois_said_end = 1;
                log_line("ONLINESKIP: intro #%d ENDS here -- slot %d carried by %s",
                         g_ois_intro_seq, OIS_SYNC_SLOT,
                         (mask == 3) ? "both seats" :
                         (mask & 1)  ? "my own seat" : "the peer's seat");
            }
            return 1;
        }
        return 0;
    }
}

static void patch_online_intro_skip(void)
{
    /* the override's first bytes: sub rsp,0x28 ; mov eax,[rcx+0xC34] */
    static const unsigned char orig_sig[10] =
        { 0x48, 0x83, 0xEC, 0x28, 0x8B, 0x81, 0x34, 0x0C, 0x00, 0x00 };
    /* the real check's prologue: mov [rsp+8],rbx ; mov [rsp+0x10],rbp */
    static const unsigned char check_sig[10] =
        { 0x48, 0x89, 0x5C, 0x24, 0x08, 0x48, 0x89, 0x6C, 0x24, 0x10 };
    /* the sync primitive: mov [rsp+0x10],rbx ; mov [rsp+0x18],rsi ; push rdi */
    static const unsigned char sync_sig[11] =
        { 0x48, 0x89, 0x5C, 0x24, 0x10, 0x48, 0x89, 0x74, 0x24, 0x18, 0x57 };
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    unsigned char** slot;
    DWORD old;

    if (!mod) return;
    if (memcmp(mod + OIS_ORIG_RVA,  orig_sig,  sizeof(orig_sig))  != 0 ||
        memcmp(mod + OIS_CHECK_RVA, check_sig, sizeof(check_sig)) != 0 ||
        memcmp(mod + OIS_SYNC_RVA,  sync_sig,  sizeof(sync_sig))  != 0) {
        log_line("ONLINESKIP: one of the three anchors does not match (game "
                 "updated?) -- online keeps the stock behaviour, nothing written");
        return;
    }
    slot = (unsigned char**)(mod + OIS_VTABLE_RVA + OIS_SLOT * 8);
    if (*slot != mod + OIS_ORIG_RVA) {
        log_line("ONLINESKIP: SOnlineAction slot %d does not hold exe+0x%X "
                 "(somebody else repointed it?) -- skipped", OIS_SLOT, OIS_ORIG_RVA);
        return;
    }
    if (!bros_claim(BROS_MASTER_OWNER, OIS_VTABLE_RVA + OIS_SLOT * 8, 8,
                    "PART 42 SOnlineAction slot 47, the online intro skip")) {
        log_line("ONLINESKIP: that vtable slot is claimed by another owner -- skipped");
        return;
    }

    g_ois_orig = (OIS_CHECK)(mod + OIS_ORIG_RVA);
    g_ois_base = (OIS_CHECK)(mod + OIS_CHECK_RVA);
    g_ois_sync = (OIS_SYNC)(mod + OIS_SYNC_RVA);

    if (!VirtualProtect(slot, 8, PAGE_READWRITE, &old)) {
        log_line("ONLINESKIP: VirtualProtect failed on the vtable slot -- skipped");
        return;
    }
    *slot = (unsigned char*)(void*)ois_slot47;
    VirtualProtect(slot, 8, old, &old);

    log_line("ONLINESKIP: SOnlineAction slot %d repointed (was exe+0x%X, the "
             "spectator fast-forward). A player pressing the skip button now "
             "announces sync slot %d, and either seat's announcement ends the "
             "intro on both. The gallery path is untouched.",
             OIS_SLOT, OIS_ORIG_RVA, OIS_SYNC_SLOT);
}

static void patch_intro_pad(void)
{
    int i;
    for (i = 0; i < (int)(sizeof(g_ipp_sites) / sizeof(g_ipp_sites[0])); i++)
        patch_intro_pad_one(g_ipp_sites[i].rva, g_ipp_sites[i].sig, g_ipp_sites[i].what);
    log_line("INTROPAD: the caller that appears ONLY in the run where B was pressed "
             "is the skip. Run one intro untouched first, for the baseline.");
}

static void patch_intro_probe(void)
{
    static const unsigned char sig[IPB_STOLEN] =
        { 0x48, 0x89, 0x5C, 0x24, 0x18 };          /* mov [rsp+0x18],rbx */
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);

    if (!mod) return;
    if (memcmp(mod + IPB_RVA, sig, sizeof(sig)) != 0) {
        log_line("INTROPROBE: exe+0x%X is not ActionSceneBase::vfunc27's prologue "
                 "(game updated?) -- probe skipped", IPB_RVA);
        return;
    }
    if (!bros_claim(BROS_MASTER_OWNER, IPB_RVA, IPB_STOLEN,
                    "PART 38 battle-intro demo probe (DIAGNOSTIC)")) {
        log_line("INTROPROBE: exe+0x%X is claimed by another owner -- probe skipped",
                 IPB_RVA);
        return;
    }
    if (!gauge_install_hook(IPB_RVA, IPB_STOLEN, (void*)intro_probe, 0, "INTROPROBE")) {
        log_line("INTROPROBE: hook failed -- no diagnostic, and nothing else changes");
        return;
    }
    log_line("INTROPROBE: read-only probe on ActionSceneBase::vfunc27 (exe+0x%X). "
             "Logs the demo manager's play flag and state, the demo cursor and its "
             "total, and the XInput pad mask, once per change, while the scene is in "
             "state 200/201 -- the two pre-match intro states. Press B during an "
             "OFFLINE intro: the line that moves names the skip.", IPB_RVA);
}

/* ================= PART 39: WHO kills the intro demo (DIAGNOSTIC) ==========
 *  PART 38 measured the shape of the offline B skip and ruled out two of the
 *  three candidates. Measured 2026-09-21, one press, pl000 vs pl000:
 *
 *      state 200  playing 1  demoState 0  cur   0.0 / 650.0
 *      state 200  playing 0  demoState 3  cur  44.0 / 650.0      <- B
 *      state <- 0x12C (300), 2 ms later                          <- 201 skipped
 *
 *  The cursor does not move and the total does not drop, so it is neither a
 *  seek to the end nor a shortening: the demo is KILLED where it stands, and
 *  the scene then goes straight to the fight. What is still unnamed is the
 *  code that does it -- nothing in the intro's own chain reads a pad, and the
 *  button is physical (B keeps skipping after Kikon is rebound off it).
 *
 *  So stop reading and trap the write. `demoMgr+0xE8` is the play flag that
 *  went 1 -> 0, and a hardware write breakpoint on it reports the RIP of
 *  whoever stores there -- the function name, not a guess about it.
 *
 *  DR0, write, one byte, armed on every thread and re-armed every 3 s because
 *  threads made later start with clean debug registers. The address is not a
 *  global: the demo manager is per-scene, so PART 38 publishes it and this
 *  re-picks whenever it changes.
 *
 *  ⚠ Build this variant with ROOM3 OFF. ROOM3's own watchpoint owns DR0 and
 *  its handler claims EVERY EXCEPTION_SINGLE_STEP while it is armed, so the
 *  two cannot both run -- and this measurement is offline, where ROOM3 has
 *  nothing to do anyway.
 *
 *  ⚠⚠ NOT ONE LINE OF LOGGING WHILE A TARGET THREAD IS SUSPENDED. That rule
 *  is inherited from ROOM3/bp and it is not style: on 2026-09-18 a suspended
 *  thread held the log lock, the arming thread blocked on it inside log_line,
 *  ResumeThread was never reached, and the game froze with no crash and no
 *  output. The arming function is silent; counting happens outside it.
 * ==================================================================== */
#define IPW_ROWS 12
#define IPW_OFF  0x110   /* the field PART 40's diff named */

static void*         g_ipw_addr;
static PVOID         g_ipw_veh;
static int           g_ipw_threads;
static int           g_ipw_lines;
static LONG          g_ipw_rip[IPW_ROWS];
static LONG          g_ipw_n[IPW_ROWS];

/* ★ The store is the END of the chain, not its head. Measured 2026-09-21: the byte
   is cleared at exe+0x6CD8D3, in the tail of ActionSceneBase::vfunc46 (live
   0x6CBBB0, 0x1EEB bytes) -- the demo TEARDOWN, which every demo passes through
   when it finishes normally too. So the RIP alone cannot say what asked for it.
   The stack can: the return addresses above it name the caller chain, and the
   frame that is NOT part of the ordinary "demo ran out" path is the skip. */
/* ⚠⚠ SCANNING THE STACK FOR PLAUSIBLE RETURN ADDRESSES DOES NOT WORK HERE, and two
   runs proved it rather than one. The first had no filter at all and returned
   `.rdata` data that merely lives inside the module. The second filtered to .text
   and required a `call` in the preceding bytes, and still returned six addresses
   with nothing from the scene chain in them -- because vfunc46's frame is large
   and full of stale words from earlier calls, and "looks like a call is in front
   of it" passes on roughly one random qword in thirty.
   ⇒ Unwind properly instead. The frame data is right there in `.pdata`, which is
   the same source `tools/unwind.py` uses on a minidump, and RtlVirtualUnwind is
   allocation-free and safe to call from a vectored handler. */
static void ipw_stack(EXCEPTION_POINTERS* ep, unsigned char* mod)
{
    char out[400];
    int at = 0, n = 0;
    CONTEXT c = *ep->ContextRecord;
    out[0] = 0;
    __try {
        while (n < 10) {
            DWORD64 base = 0, est = 0;
            PVOID hdata = NULL;
            PRUNTIME_FUNCTION fn = RtlLookupFunctionEntry(c.Rip, &base, NULL);
            if (!fn) {
                /* ⚠ A LEAF HAS NO .pdata ENTRY, and stopping there is what made the
                   first run print "(unwind produced nothing)": the writer of
                   demoPlayer+0x110 is a 0x29-byte setter at exe+0x8B4420 that
                   pushes nothing. The x64 rule for a leaf is exactly this -- the
                   return address is at [rsp] and rsp steps over it -- so apply it
                   and keep climbing instead of giving up on the first frame. */
                c.Rip = *(DWORD64*)(ULONG_PTR)c.Rsp;
                c.Rsp += 8;
                if (!c.Rip) break;
                goto emit;
            }
            RtlVirtualUnwind(UNW_FLAG_NHANDLER, base, c.Rip, fn, &c, &hdata, &est, NULL);
            if (!c.Rip) break;
          emit:
            if (c.Rip > (DWORD64)(ULONG_PTR)mod &&
                c.Rip < (DWORD64)(ULONG_PTR)mod + 0x1C00000)
                at += snprintf(out + at, sizeof(out) - at, "exe+0x%X ",
                               (unsigned)(c.Rip - (DWORD64)(ULONG_PTR)mod));
            else
                at += snprintf(out + at, sizeof(out) - at, "%p ", (void*)(ULONG_PTR)c.Rip);
            n++;
            if (at > (int)sizeof(out) - 24) break;
        }
    } __except(EXCEPTION_EXECUTE_HANDLER) { }
    log_line("INTROWHO/stack: %s", out[0] ? out : "(unwind produced nothing)");
}

static LONG CALLBACK ipw_handler(EXCEPTION_POINTERS* ep)
{
    if (ep->ExceptionRecord->ExceptionCode == EXCEPTION_SINGLE_STEP && g_ipw_addr &&
        (ep->ContextRecord->Dr6 & 1)) {
        unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
        LONG r = (LONG)((ULONG_PTR)ep->ExceptionRecord->ExceptionAddress - (ULONG_PTR)mod);
        LONG st = g_ipb_state;
        int k;
        /* ⚠ Only while an intro is actually on screen. The demo manager is
           per-scene: once the intro is over the watched address belongs to
           whatever the allocator handed the memory to next, and the hits that
           produces are somebody else's writes with nonsense RIPs (measured:
           exe+0x308FDF6F, "it now reads 112"). */
        if (g_ipb_demo && (st == 200 || st == 201)) {
            for (k = 0; k < IPW_ROWS; k++) {
                if (g_ipw_rip[k] == r) { g_ipw_n[k]++; break; }
                if (g_ipw_rip[k] == 0) {
                    g_ipw_rip[k] = r; g_ipw_n[k] = 1;
                    break;
                }
            }
            /* Every hit that CLEARS the flag gets a line and a stack, because the
               clear is the event -- the sets are the intro starting. Capped. */
            /* ⚠ A data breakpoint fires on every STORE, not on every change, and
               the two are different questions here: the first run trapped a
               `movups` of four 1.0f and the byte-diff had reported 0->1 at +0x110
               and +0x118, which cannot both be the same write. So log the sixteen
               bytes as they read AFTER each store, and let the values say which
               store is which instead of assuming. */
            if (g_ipw_lines < 24) {
                unsigned char* v = (unsigned char*)g_ipw_addr;
                g_ipw_lines++;
                log_line("INTROWHO: demoPlayer+0x%X written from exe+0x%X -- now "
                         "%02X %02X %02X %02X %02X %02X %02X %02X %02X %02X %02X %02X "
                         "%02X %02X %02X %02X (state %ld, cur %ld)",
                         IPW_OFF, (unsigned)r,
                         v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],
                         v[8],v[9],v[10],v[11],v[12],v[13],v[14],v[15],
                         (long)st, (long)g_ipb_ticks);
                ipw_stack(ep, mod);
            }
        }
        ep->ContextRecord->Dr6 = 0;
        ep->ContextRecord->EFlags |= 0x10000;   /* RF: resume without trapping again */
        return EXCEPTION_CONTINUE_EXECUTION;
    }
    return EXCEPTION_CONTINUE_SEARCH;
}

/* Arm DR0 on one thread. Silent by construction -- see the warning above. */
static int ipw_arm_one(DWORD tid, CONTEXT* c)
{
    HANDLE th;
    BOOL got, set = FALSE;
    if (tid == GetCurrentThreadId()) return 0;
    th = OpenThread(THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT | THREAD_SET_CONTEXT,
                    FALSE, tid);
    if (!th) return 0;
    if (SuspendThread(th) == (DWORD)-1) { CloseHandle(th); return 0; }
    memset(c, 0, sizeof(CONTEXT));
    c->ContextFlags = CONTEXT_DEBUG_REGISTERS;
    got = GetThreadContext(th, c);
    if (got) {
        c->Dr0 = (DWORD64)(ULONG_PTR)g_ipw_addr;
        /* L0 on, RW0 = 01 (write), LEN0 = 00 (one byte) */
        c->Dr7 = (c->Dr7 & ~(DWORD64)0xF0003) | 1 | ((DWORD64)1 << 16);
        c->ContextFlags = CONTEXT_DEBUG_REGISTERS;
        set = SetThreadContext(th, c);
    }
    ResumeThread(th);
    CloseHandle(th);
    return set ? 1 : 0;
}

static DWORD WINAPI ipw_watch(LPVOID unused)
{
    CONTEXT* c;
    void* buf;
    int pass;
    (void)unused;
    /* CONTEXT wants 16-byte alignment, so it is allocated rather than stacked. */
    buf = VirtualAlloc(NULL, sizeof(CONTEXT) + 32, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!buf) return 0;
    c = (CONTEXT*)(((ULONG_PTR)buf + 15) & ~(ULONG_PTR)15);

    for (pass = 0; pass < 1200; pass++) {       /* an hour of matches */
        unsigned char* mgr = g_ipb_demo;
        HANDLE snap;
        THREADENTRY32 te;
        DWORD pid = GetCurrentProcessId();
        int armed = 0;

        if (!mgr) { Sleep(500); continue; }     /* no intro on screen */
        if (g_ipw_addr != mgr + IPW_OFF) {
            g_ipw_addr = mgr + IPW_OFF;
            g_ipw_threads = -1;                 /* force the next line to print */
        }
        snap = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
        if (snap != INVALID_HANDLE_VALUE) {
            te.dwSize = sizeof(te);
            if (Thread32First(snap, &te)) {
                do {
                    if (te.th32OwnerProcessID == pid)
                        armed += ipw_arm_one(te.th32ThreadID, c);
                } while (Thread32Next(snap, &te));
            }
            CloseHandle(snap);
        }
        if (armed != g_ipw_threads) {
            g_ipw_threads = armed;
            log_line("INTROWHO: watching writes to %p -- demoPlayer+0x%X, the byte that goes 0->1 on the frame the intro ends -- on %d thread(s)", g_ipw_addr, IPW_OFF, armed);
            if (!armed)
                log_line("INTROWHO: could not arm on any thread -- the writer stays unnamed");
        }
        Sleep(500);   /* re-arm: threads made later start with clean debug registers */
    }
    return 0;
}

static void patch_intro_who(void)
{
    g_ipw_veh = AddVectoredExceptionHandler(1, ipw_handler);
    if (!g_ipw_veh) {
        log_line("INTROWHO: could not register the exception handler -- no watchpoint");
        return;
    }
    CreateThread(NULL, 0, ipw_watch, NULL, 0, NULL);
    log_line("INTROWHO: armed. A hardware write breakpoint follows the demo manager's "
             "play flag (demoMgr+0xE8) for as long as an intro is on screen, and names "
             "the exe address of every store to it. Press B during an OFFLINE intro: "
             "the store that takes it to 0 is the skip.");
}

#if defined(BUILD_CRE) && BUILD_CRE && defined(BROS_PL005_PLUGIN) && BROS_PL005_PLUGIN
/* ★★★★★ ZANGETSU IS NOT IN THIS BINARY ANY MORE.

   He is ReBalanceOfSouls\\pl005.dll, together with Yumichika and the added
   select grid, and the master loads him like any other plugin. This is the
   whole answer to 2026-09-05: a Community build committed over the shared
   dinput8.dll took him out of the process with nothing saying so, and a
   plugin is not something another dev's build flag can delete.

   The two stubs below keep the CALL SITES in worker() untouched -- that
   function is the riskiest place in this file to edit, and this refactor
   does not edit it. Build with -DBROS_PL005_PLUGIN=0 to compile him back
   in; that path is kept working, not left to rot. */
static void patch_pl005_gauge(void)
{
    log_line("PL005: not in this binary -- Zangetsu ships in %s\\pl005.dll."
             " If his moon gauge is missing, the plugin did not load: read the"
             " BROS/plugins lines above this one.", BROS_PLUGIN_DIR);
}
/* silent: the plugin runs its own copy of this check, right after its own
   roster pass, which is the only place the ordering it guards is decided */
static void v12_assert_legacy_retired(void) { }
#elif defined(BUILD_CRE) && BUILD_CRE
/* Zangetsu's gauge. Included here so gauge_alloc_near() and log_line()
   are already defined; it reuses the former and never duplicates it. */
#include "pl005_gauge.c"

/* ★★★ The V1.2 seatbelt for the ordering above.

   patch_v12_roster() now runs first, so pl005_retire_legacy_driver() finds the two E9
   jumps and removes them exactly as it did under the CRE. This proves that in the log
   every run instead of leaving it to be rediscovered by a crash, and repairs it if some
   future edit ever writes the recipe image late again.

   ⚠ It repairs ONLY when we retired on purpose. If patch_pl005_gauge() rolled its
   install back (pl005_unretire_legacy() clears g_legacy_retired), pl005 has no controller
   of ours and the legacy driver is then the CORRECT one to be running -- retiring it there
   would leave the gauge with no driver at all. */
static void v12_assert_legacy_retired(void)
{
    unsigned char* mod = (unsigned char*)GetModuleHandleA(NULL);
    int armed;
    if (!mod) return;
    armed = (mod[RVA_LEGACY_HOOK1] == 0xE9) + (mod[RVA_LEGACY_HOOK2] == 0xE9);
    if (!armed) {
        log_line("V12/legacy: both ui_ctrl hook sites are clean (0x%02X at 0x%X, 0x%02X at"
                 " 0x%X) -- our controller is the only driver, which is the whole point",
                 mod[RVA_LEGACY_HOOK1], (unsigned)RVA_LEGACY_HOOK1,
                 mod[RVA_LEGACY_HOOK2], (unsigned)RVA_LEGACY_HOOK2);
        return;
    }
    if (!g_legacy_retired) {
        log_line("V12/legacy: %d ui_ctrl hook site(s) armed and we never retired them --"
                 " the legacy driver is running deliberately (no controller of ours)", armed);
        return;
    }
    log_line("V12/legacy: %d ui_ctrl hook site(s) were RE-ARMED after the retire. Something"
             " wrote the recipe image late -- retiring again so the game boots, but the call"
             " order in worker() is what needs fixing.", armed);
    pl005_retire_legacy_driver();
}
#endif

static DWORD WINAPI worker(LPVOID u)
{
    (void)u;
    log_line("==== dinput8 proxy loaded INTO GAME (pid %lu) ====", GetCurrentProcessId());

    /* ---- build stamp -------------------------------------------------
       Until 2026-08-28 nothing in this loader identified WHICH build wrote a
       log. The title reads "ReBalance <ver>" but that <ver> is Bandai's game
       version -- patch_version_string only renames the "Ver." prefix -- so two
       players on different DLLs looked identical in every report either could
       send. That is how the 08-06 Aizen hotfix turned into a desync nobody
       could trace: some clients had the flame patches enabled, some did not,
       and no artefact anywhere said which. One line fixes it permanently.
       verify_patchlog.py reads this line and refuses to certify an unstamped
       log. */
    /* The compiler stamps this, so it cannot be forgotten. PATCH_BUILD_ID is
       hand-written and therefore lies the moment someone edits the source without
       touching it -- which is exactly how a binary missing the bad_alloc fix
       shipped under an id that looked current. __DATE__/__TIME__ are the build,
       not the intent, and that is the point: if the log says a build older than
       the last source change, the binary is stale whatever its id claims. */
    log_line("PATCHSTAMP/build: compiled " __DATE__ " " __TIME__);
    log_line("PATCHSTAMP: %s build, id %s, flags"
             " AIZEN_COUNTER=%d AIZEN_FLAME=%d BYAKUYA_GAUGE=%d INTRO_SKIP=%d"
             " ROOM_RESULT=%d ROOM_GUARDS=%d DRED=%d FAST_BOOT=%d SKIP_LOGOS=%d"
             " MERI=%d REAWAKEN=%d BACKSTEP=%d/sides%d FLASHSTEP=%d PL005=%d"
             " THROWTECH_PROBE=%d BYAKUYA_PETAL_TIMER=%d BYAKUYA_BS=%d ROOM3=%d",
#if defined(BUILD_CRE) && BUILD_CRE
             "CRE",
#else
             "Community",
#endif
             PATCH_BUILD_ID,
             ENABLE_AIZEN_KIKON_COUNTER, ENABLE_AIZEN_FLAMECOST,
             ENABLE_BYAKUYA_GAUGE, ENABLE_INTRO_SKIP, ENABLE_ROOM_RESULT_MENU,
             ENABLE_ROOM_GUARDS, ENABLE_DRED, ENABLE_FAST_BOOT,
             ENABLE_SKIP_LOGOS, ENABLE_MERI_MODE, ENABLE_REAWAKEN_BATTLE,
             ENABLE_BACKSTEP_HOLD, BSH_ALLOW_SIDES, ENABLE_FLASHSTEP_HOLD,
#if defined(BUILD_CRE) && BUILD_CRE
             ENABLE_PL005_GAUGE,
#else
             0,
#endif
             ENABLE_THROWTECH_PROBE, ENABLE_BYAKUYA_PETAL_TIMER,
             ENABLE_BYAKUYA_BUILDER_SPENDER, ENABLE_ROOM3
             );
    load_settings();
    if (ENABLE_DRED) patch_dred_hook();
    else log_line("DRED: DISABLED at build time -- a removed device will not be explained");
    crashlog_init();
    g_veh_handle = AddVectoredExceptionHandler(1, crash_veh);
    if (g_veh_handle)
        log_line("CRASH: vectored handler armed -- an access violation now names its RVA "
                 "and asks D3D12 for the device-removal reason before the process dies");
    else log_line("CRASH: could not arm the vectored handler");

    /* ---- FIRST, before any other patch touches the image ---------------------
       ★★★★★ 2026-09-05, the fourth battle-load crash. This used to sit twenty lines
       below, after patch_pl005_gauge(). That is wrong, and it is wrong for a reason
       worth writing down: under the CRE the exe on disk was ALREADY the recipe image
       when the process started, so every patch in this function ran against a patched
       exe. V1.2 ships no Exe/ and rebuilds that image here at runtime instead -- so
       running it late means the first twenty patches see a STOCK exe and decide
       against it.

       pl005_retire_legacy_driver() is the one that cannot survive that. It removes the
       two E9 jumps into the legacy ui_ctrl cave, and those jumps ARE part of the recipe
       image. Late, it found stock bytes, logged

           PL005/legacy1: RVA 0x48CBD8 is not a jmp (0xBB) -- already clean or the exe
           differs; left alone

       and left them -- and then this function wrote them straight back in. The legacy
       driver then ran alongside our own controller, read [r10+0x18] expecting a
       Pl38-shaped object, and killed the process on the frame the fighter appeared:

           CRASH: access violation at exe+0x13A24C7 -- reading from 0xFFFFFFFFFFFFFFFF
           r10=000001D34D2C0FA0   <- "PL005: gauge is ours -- obj 000001D34D2C0FA0"

       pl005_gauge.c already states the rule ("retire the legacy driver FIRST ... it must
       go before anything it could observe changes"). Restoring the image first is what
       makes that rule true again, and it reproduces the CRE's exact ordering rather than
       working around it. v12_assert_legacy_retired() proves it every run. */
    /* ★ PLUGINS FIRST, in the slot patch_v12_roster() occupies today.
       That is deliberate and it is not a free choice: on 2026-09-05, running
       the roster later than this cost a battle-load access violation, and
       this is the ordering that was proven to boot. A character that moves
       out of this binary inherits that exact position, rather than whatever
       order a directory listing or a merge happens to produce. */
    bros_load_plugins();

    patch_v12_roster();

    patch_version_string();
    patch_yamamoto_selfcost();
    /* BYAKUYA_ICON and BYAKUYA_GAUGE both target Byakuya UI controller and are
       mutually exclusive by construction: the icon patch repoints Pl22 vtable
       slot 22, while the gauge moves him off the Pl22 class entirely, which
       makes that repoint inert for him. Ship one or the other.
       Per the rule at the top of this file, a flag -- never a commented-out
       call -- so patch_ranked.log always states which one shipped. */
    /* ⚠ The 30 s heartbeat used to be started from INSIDE patch_byakuya_gauge(),
       after its controller installed. Building with -DENABLE_BYAKUYA_GAUGE=0 then
       silently took the whole telemetry with it -- BARRIERGUARD's counter and the
       ROOM3/galpipe line, which are the two things every rig session is read
       through -- while the features themselves stayed installed. A log that
       disappears with an unrelated flag is worse than no log: it reads as the
       feature being gone. It starts here now, once, whatever Byakuya does. */
    CreateThread(NULL, 0, gauge_stats_thread, NULL, 0, NULL);
    if (ENABLE_BYAKUYA_GAUGE) patch_byakuya_gauge();
    else {
        log_line("BYAKUYA_GAUGE: DISABLED at build time -- Byakuya keeps the vanilla "
                 "Pl22 icon-only UI");
        /* ...but NOT without the handle guard. See patch_gauge_handle_guard_only. */
        if (ENABLE_GAUGE_HANDLE_GUARD) patch_gauge_handle_guard_only();
        else log_line("HANDLE/guard: DISABLED at build time as well -- SP1 will fault at "
                      "exe+0x927E6, `lock inc [rax+0xc]` on a garbage shared_ptr "
                      "control block");
    }
    if (ENABLE_BYAKUYA_EVO_ICON) patch_byakuya_evo_icon();
    else log_line("BYAKUYA_ICON: DISABLED at build time -- superseded by BYAKUYA_GAUGE "
                  "(on the Com class the Pl22 vtable repoint is inert for Byakuya)");

#if defined(BUILD_CRE) && BUILD_CRE
    if (ENABLE_PL005_GAUGE) patch_pl005_gauge();
    else log_line("PL005: DISABLED at build time -- Zangetsu keeps the generic Com "
                  "gauge (still correct, just not his own)");
#else
    log_line("PL005: not in this build (Community target) -- CRE only");
#endif
    /* Both Aizen patches are switched off for the 2026-08-06 crash hotfix.
       Flip the ENABLE_* defines at the top of this file to bring them back --
       do NOT delete the calls, the log line has to keep telling us which of
       the two configurations a player is running. */
    /* plain `if` on a 0/1 macro, not #if, so both functions stay referenced
       (they keep compiling, and -O2 drops the dead one from the binary). */
    if (ENABLE_AIZEN_KIKON_COUNTER) patch_aizen_kikon_counter();
    else log_line("AIZEN_COUNTER: DISABLED at build time (2026-08-06 crash hotfix, "
                  "precaution) -- reverse gauge requirement and cost unchanged");
    if (ENABLE_AIZEN_FLAMECOST) patch_aizen_flamecost();
    else log_line("AIZEN_FLAME: DISABLED at build time (2026-08-06 crash hotfix) -- "
                  "af_action_is() reads the action-name string 8 bytes low and "
                  "dereferences a non-pointer for any name >= 16 chars");
    patch_stage_new_id_gate();
#if defined(BUILD_CRE) && BUILD_CRE
    if (ENABLE_PL005_GAUGE) v12_assert_legacy_retired();
#endif
    if (ENABLE_CRASHDUMP_SETUP) patch_crashdump_setup();
    if (ENABLE_ALLOC_PROBE) patch_alloc_probe();
    if (ENABLE_TEARDOWN_GUARD) patch_teardown_guard();
    if (ENABLE_TEARDOWN_GUARD) patch_teardown2_guard();
    if (ENABLE_TEARDOWN_GUARD) patch_refrelease_guard();
    if (ENABLE_TEARDOWN_GUARD) patch_uiplay_guard();
    if (ENABLE_TEARDOWN_GUARD) patch_lookup_guard();
    if (ENABLE_TEARDOWN_GUARD) patch_vcall_guard();
    if (ENABLE_TEARDOWN_GUARD) patch_refrel2_guard();
    if (ENABLE_TEARDOWN_GUARD) patch_vfn_probe();
    else log_line("TEARDOWN: DISABLED at build time");
    /* SLOT2 (0x20750A) and SETRATE (0x208470) are GONE as of 2026-09-01, and
       deliberately: both patched a leaf the whole game runs through, to contain
       a fault only Byakuya could reach, and only because a Pl38 vtable slot had
       been repointed at a Com method. He now owns his controller (pl022_gauge.c)
       and the same two checks live in HIS vtable slots, where they cost every
       other character nothing. The saves counters moved with them and are still
       printed in the 30s line. */
    if (ENABLE_INTRO_SKIP) patch_intro_skip();
    else log_line("INTROSKIP: DISABLED at build time -- online still plays the "
                  "pre-match ct_start intros");
    if (ENABLE_ROOM_RESULT_MENU) { patch_room_result_menu(); patch_room_rematch_wait(); }
    else log_line("ROOMRESULT: DISABLED at build time -- a room match still ends with "
                  "no menu and drops back to the room on a timer");
    if (ENABLE_ROOM_GUARDS) { patch_room_draw_guard(); patch_room_draw_guard2();
                              patch_room_steam_guard(); }
    else log_line("ROOMGUARD: DISABLED at build time -- the two room-match NULL "
                  "dereferences still crash the process");
    if (ENABLE_UIRES_GUARD) patch_uires_guard();
    else log_line("UIRESGUARD: DISABLED at build time -- Training->Battle->"
                  "CharaSelect->Battle still crashes at exe+0x9DB40A");
    if (ENABLE_VOICE_PROBE) patch_voice_probe();
    if (ENABLE_MERI_MODE) { patch_meri_first_kill(); patch_meri_display(); }
    else log_line("MERI: DISABLED at build time -- Kikon konpaku damage is stock "
                  "(build with -DENABLE_MERI_MODE=1 for the Meri's mode variant)");
    boot_mode_from_env();
    if (g_boot_enabled) patch_boot_training();
    else log_line("BOOTTRAIN: DISABLED at build time -- boot goes to the title "
                  "screen (build with -DENABLE_BOOT_TRAINING=1 or "
                  "-DENABLE_BOOT_ROOMMATCH=1 for those loaders)");
    if (ENABLE_FAST_BOOT) patch_fast_boot();
    else log_line("FASTBOOT: DISABLED at build time -- boot still stops on the "
                  "clickable auto-save notice (build with -DENABLE_FAST_BOOT=1 "
                  "for the Fast boot variant)");
    if (ENABLE_SKIP_LOGOS) patch_skip_logos();
    else log_line("SKIPLOGO: DISABLED at build time -- the four boot logos still "
                  "play before the title screen");
    if (ENABLE_KAISER_TRACE) patch_kaiser_trace();
    if (ENABLE_YHWACH_REAWAKEN_9) patch_yhwach_reawaken();
    else log_line("YHWACH_REAW: DISABLED at build time -- Yhwach still Reawakens "
                  "off his EIGHTH Kaiser (build with -DENABLE_YHWACH_REAWAKEN_9=1 "
                  "for the fix)");
    if (ENABLE_YHWACH_PROBE) patch_yhwach_probe();
    if (ENABLE_INTRO_PROBE) patch_intro_probe();
    else log_line("INTROPROBE: DISABLED at build time -- nothing watches the "
                  "pre-match intro's demo state (build with -DENABLE_INTRO_PROBE=1)");
    /* PART 39 needs PART 38's published demo manager, so it is called after it. */
    if (ENABLE_INTRO_WHO && ENABLE_INTRO_PROBE) { patch_intro_who(); patch_intro_pad(); }
    else if (ENABLE_INTRO_WHO)
        log_line("INTROWHO: needs ENABLE_INTRO_PROBE for the demo manager address "
                 "-- not armed");
    if (ENABLE_ONLINE_INTRO_SKIP) patch_online_intro_skip();
    else log_line("ONLINESKIP: DISABLED at build time -- an online player still "
                  "cannot skip the pre-match intro (build with "
                  "-DENABLE_ONLINE_INTRO_SKIP=1)");
    if (ENABLE_YHWACH_START_LEVEL) patch_yhwach_start_level();
    else log_line("YHWACH_LV1: DISABLED at build time -- Yhwach still opens Training "
                  "on Kaiser level 0 (build with -DENABLE_YHWACH_START_LEVEL=1)");
    if (ENABLE_REAWAKEN_BATTLE) patch_reawaken_battle();
    else log_line("REAWAKEN: DISABLED at build time -- Reawakenings use their stock "
                  "triggers (build with -DENABLE_REAWAKEN_BATTLE=1 for the "
                  "Reawakening Battle variant)");
    if (ENABLE_BACKSTEP_HOLD) patch_backstep_hold();
    else log_line("BACKSTEP: DISABLED at build time -- held back+dash still gives the "
                  "backward run (build with -DENABLE_BACKSTEP_HOLD=1 for the "
                  "Backstep hold variant)");
    if (ENABLE_FLASHSTEP_HOLD) patch_flashstep_hold();
    else log_line("FLASHSTEP: DISABLED at build time -- a held flash step still produces "
                  "nothing out of blockstun");
    if (ENABLE_HOHO_CATCHALL_FIX) patch_hoho_catchall();
    if (ENABLE_HOHO_GUARD_VETO) patch_hoho_guard_veto();
    if (ENABLE_SP_GUARD_VETO) patch_sp_guard_veto();
    if (ENABLE_HOHO_NO_COMPANION) patch_hoho_no_companion();
    else log_line("HOHOFIX: DISABLED at build time -- the flash-step button still fires "
                  "the catch-all command");
    if (ENABLE_ROOM3 && ROOM3_CAP_ONLY) {
        room3_pool_shift();
        log_line("ROOM3: CAP-ONLY build -- the member cap is raised to %d and nothing else "
                 "is patched. Whatever happens now is the game's own behaviour with three "
                 "members in a room.", ROOM3_MEMBERS);
    }
    else if (ENABLE_ROOM3) { room3_pool_shift(); patch_room3_seat_clamps();
                       /* The seat fix comes FIRST: with real seats the role gate never
                          fires, and its counter staying at 0 is the proof that it did
                          not. Both installed so one run compares them. */
                       patch_room3_spectator_as_p1();
                       patch_room3_participant_gate();
                       patch_room3_start_probe();
                       patch_room3_caller_probe();
                       patch_room3_battle_gate();
                       patch_room3_entry_probe();
                       patch_room3_barrier_probe();
                       patch_room3_state1_exit();
                       patch_room3_setup_breadcrumb();
    patch_room3_result_name();
    patch_room3_result_index();
                       patch_room3_more_crumbs();
                       patch_room3_scene_probe();
                       patch_room3_set4e_probe();
                       patch_room3_vtable_map();
                       patch_room3_role_gate(); }
    else log_line("ROOM3: DISABLED at build time -- a room match still holds two people "
                  "(build with -DENABLE_ROOM3=1 for the three-player room test)");
    if (ENABLE_INPUT_PROBE) patch_input_probe();
    if (ENABLE_THROWTECH_PROBE) patch_throwtech_probe();
    else log_line("THROWTECH: DISABLED at build time -- no run/throw-tech probe "
                  "(build with -DENABLE_THROWTECH_PROBE=1)");
    /* Wait for steam_api64 as long as it takes.

       This used to poll 600 times at 500 ms -- five minutes -- and then give up
       for good. The game does not load steam_api64 until the title screen is
       left, so a session left sitting at "Press Start" longer than that had
       nothing still looking when it finally appeared, and the matchmaking patch
       never installed. Observed 2026-09-05 after a fifteen-minute idle.

       The consequence is the one PART 2 exists to prevent: the player lands in
       the DEFAULT matchmaking pool and meets unpatched clients, with a single
       ERROR line as the only sign.

       try_install()'s three answers are unchanged -- 1 installed, negative means
       this is not the game process and giving up is right, 0 means keep
       waiting. Only the cap is gone.

       500 ms while a normal start is in progress, 2 s afterwards: the fast poll
       is there to hook a real launch promptly, and a session that has idled
       past five minutes has nothing to be prompt about. */
    {
        ULONGLONG t0 = GetTickCount64();
        ULONGLONG next = 30000;        /* 30 s, then 60, 120, 300, 600, ... */

        for (;;) {
            int r = try_install();
            if (r == 1) {
                ULONGLONG secs = (GetTickCount64() - t0) / 1000;
                if (secs >= 30)
                    log_line("MATCH: matchmaking hooked after %llu s.",
                             (unsigned long long)secs);
                return 0;
            }
            if (r < 0)
                return 0;              /* not the game process; give up is correct */

            /* Report on a widening cadence, and NAME THE GATE. The rig gives up
               at 180 s, so a client that will not hook has to have said why
               before then -- the old code said nothing at all until 300 s, and
               what it then said was wrong two times out of three. */
            if (GetTickCount64() - t0 >= next) {
                LONG g = g_mm_gate;
                log_line("MATCH: no matchmaking after %llu s -- STILL WAITING. %s.",
                         (unsigned long long)((GetTickCount64() - t0) / 1000),
                         mm_gate_name(g));
                if (g == 0)
                    log_line("MATCH:   gate 0 means the client is idling before Steam "
                             "init -- typically the title screen. Press through it.");
                else
                    log_line("MATCH:   gate %ld is NOT the title screen: the module is "
                             "already in. Do not go looking there.", g);
                next = (next < 600000) ? next * 2 : next + 600000;
            }
            Sleep(GetTickCount64() - t0 < 300000 ? 500 : 2000);
        }
    }
}

BOOL WINAPI DllMain(HINSTANCE h, DWORD reason, LPVOID res)
{
    (void)res;
    if (reason==DLL_PROCESS_ATTACH) {
        if (InterlockedCompareExchange(&g_started,1,0)==0) {
            DisableThreadLibraryCalls(h);
            CreateThread(NULL,0,worker,NULL,0,NULL);
        }
    }
    else if (reason==DLL_PROCESS_DETACH) {
        /* What makes the session marker mean anything. This line runs on a
           normal exit and does NOT run when the process is killed -- a crash,
           a __fastfail or a hang-kill by WER all skip it -- so a marker that
           survives to the next launch is proof the last session ended badly. */
        crashlog_session_end();
    }
    return TRUE;
}
