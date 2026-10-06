/* =====================================================================
 *  pacing_plugin.c -- the game's two frame limiters, without the busy wait
 *  and without the drift. Not a character: one feature, for every match.
 *
 *  THE STOCK CODE (exe md5 7b213566), both limiters identical in shape:
 *    render loop  sub_9E6E70  @0x9E6FA0: fps = word [timer+0x82],
 *                 mark = [timer+0x90], yield call at 0x9E700D,
 *                 new mark stored at 0x9E7052
 *    main thread  sub_9E72A0  @0x9E7300: fps = word [timer+0x80],
 *                 mark = [timer+0x88], yield call at 0x9E7370,
 *                 new mark stored at 0x9E73C4
 *  Each spins `while ((now - mark)/1000 < 1e6/fps) SwitchToThread();`
 *  and then stores mark = now.
 *    - The spin keeps a core busy for the whole slack of every frame, on
 *      two threads, and SwitchToThread hands the core to any ready thread:
 *      the return can be a scheduler quantum late, past the vblank.
 *    - mark = now loses the overshoot every frame (and all of a late
 *      frame), so the cadence drifts against vsync and never catches up.
 *
 *  WHAT THIS PLUGIN CHANGES (both halves on by default):
 *    wait  the yield call goes to pace_wait(elapsed, interval): a
 *          high-resolution waitable timer sleeps until ~1 ms before the
 *          deadline, then the loop spins on PAUSE (YieldProcessor) without
 *          giving the core away. The game's own loop still decides when
 *          the frame is due -- this only changes how it waits. Without a
 *          high-resolution timer (before Windows 10 1803) it keeps the stock
 *          SwitchToThread: a plain timer wakes on the 15.6 ms tick.
 *    abs   the new mark is the previous mark + one interval (an absolute
 *          schedule at the game's own rate, tempo changes included), unless
 *          the frame is a full interval late, in which case it is now: one
 *          late frame is made up by the next one, never by a burst.
 *  Nothing else: no simulation code, no input, no netcode. Both players of
 *  an online match still advance one frame per frame; this only decides
 *  when the wait before each frame ends.
 *
 *  MEASURED 2026-10-06, online, two boxed clients on one PC (Ryzen 7 2700X),
 *  each pinned to its own 4 cores, Byakuya mirror room match, idle battle,
 *  probe v6 with the profiler off, ~5 min per battle, host / guest:
 *                     fps          frames > 33 ms per min   p95 frame
 *    vanilla (V2)     57.0 / 57.5   85 / 66                  24.5 ms
 *    patch   (P1)     56.9 / 57.6   89 / 69                  25.0 ms
 *    patch + pacing   59.8 / 59.7    4 /  6                  18.4 ms (PF1)
 *                     59.5 / 59.5    7 / 11                  18.9 ms (PF2)
 *  The patch itself measured the same as vanilla online. The drops were the
 *  stock limiter, and they are in vanilla too.
 *
 *  SWITCHES, beside the exe:
 *    pacing_off.txt   (any content) declines before claiming anything:
 *                     the stock limiters, as if the plugin were absent
 *    pacing.txt       `wait 0` / `abs 0` turn one half off (an A/B is
 *                     one file)
 * ===================================================================== */
#include <windows.h>
#include <stddef.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include "bros_plugin.h"
#ifndef PATCH_BUILD_ID
#define PATCH_BUILD_ID "pacing-local"
#endif
#define OWNER "pacing.dll"
/* Check each field against host->size, never sizeof(BrosHost): the installed
   master can be older than this header (bros-dll-plugin-standard, rule 6). */
#define HAS(h, f) ((h)->size >= offsetof(BrosHost, f) + sizeof((h)->f))

/* stock bytes at each site */
static const unsigned char k_yield_r[5]  = { 0xE8, 0xFE, 0x78, 0x6B, 0x00 };   /* 9E700D call 109E910 */
static const unsigned char k_yield_m[5]  = { 0xE8, 0x9B, 0x75, 0x6B, 0x00 };   /* 9E7370 call 109E910 */
static const unsigned char k_mark_r[14]  = { 0x48, 0x8B, 0x0E,                 /* 9E704B mov rcx,[rsi]      */
                                             0x48, 0x8B, 0x51, 0x10,           /*        mov rdx,[rcx+10h]  */
                                             0x48, 0x89, 0x82, 0x90, 0x00, 0x00, 0x00 }; /* mov [rdx+90h],rax */
static const unsigned char k_mark_m[11]  = { 0x48, 0x8B, 0x4E, 0x10,           /* 9E73C0 mov rcx,[rsi+10h]  */
                                             0x48, 0x89, 0x81, 0x88, 0x00, 0x00, 0x00 }; /* mov [rcx+88h],rax */

static const BrosHost* H;
static int g_wait = 1, g_abs = 1;
static DWORD g_tls = TLS_OUT_OF_INDEXES;
/* 1 = high-resolution waitable timers exist (Windows 10 1803+). 0 = they do not, and then this plugin never
   sleeps: a plain waitable timer wakes on the system tick, up to 15.6 ms late, which is a dropped frame. */
static volatile LONG g_hires = 1;
/* Counted only on the timer path (~120 a second). The spin path runs ~1M times a second on two threads, and a
   shared atomic there would bounce one cache line between them (see bros-hot-hook-no-shared-writes). */
static volatile LONG g_sleeps, g_marks_abs, g_marks_now;

static HANDLE my_timer(void)
{
    HANDLE t;
    if (g_tls == TLS_OUT_OF_INDEXES || !g_hires) return NULL;
    t = (HANDLE)TlsGetValue(g_tls);
    if (!t) {
        t = CreateWaitableTimerExW(NULL, NULL, 0x00000002 /* HIGH_RESOLUTION */, TIMER_ALL_ACCESS);
        if (!t) { g_hires = 0; return NULL; }
        TlsSetValue(g_tls, t);
    }
    return t;
}

/* Called by the game's limiter loops instead of SwitchToThread, with the
   loop's own elapsed and interval (microseconds, doubles in xmm0/xmm1).
   The loop calls again until the frame is due, so each call only has to
   wait a while: sleep to ~1 ms before the deadline, then spin on PAUSE. */
void pace_wait(double elapsed_us, double interval_us)
{
    double rem = interval_us - elapsed_us;
    if (g_wait && rem > 1500.0) {
        HANDLE t = my_timer();
        LARGE_INTEGER due;
        due.QuadPart = -(LONGLONG)((rem - 1000.0) * 10.0);     /* 100 ns units, relative */
        if (t && SetWaitableTimer(t, &due, 0, NULL, NULL, FALSE)) {
            WaitForSingleObject(t, (DWORD)(rem / 1000.0) + 4);
            InterlockedIncrement(&g_sleeps);
            return;
        }
    }
    if (!g_wait || !g_hires) { SwitchToThread(); return; }     /* the stock wait */
    { int i; for (i = 0; i < 32; i++) YieldProcessor(); }
}

/* Called where the stock code stores mark = now. */
static void pace_mark(unsigned char* timer, LONGLONG now_ns, unsigned fps_off, unsigned mark_off)
{
    unsigned fps = *(unsigned short*)(timer + fps_off);
    LONGLONG prev = *(LONGLONG*)(timer + mark_off);
    LONGLONG iv = fps ? (1000000000LL + fps / 2) / fps : 16666667LL;
    LONGLONG next = prev + iv;
    if (g_abs && prev > 0 && now_ns >= next && now_ns - next < iv) {
        *(LONGLONG*)(timer + mark_off) = next;
        InterlockedIncrement(&g_marks_abs);
    } else {
        *(LONGLONG*)(timer + mark_off) = now_ns;
        InterlockedIncrement(&g_marks_now);
    }
}
void pace_mark_r(unsigned char* timer, LONGLONG now_ns) { pace_mark(timer, now_ns, 0x82, 0x90); }
void pace_mark_m(unsigned char* timer, LONGLONG now_ns) { pace_mark(timer, now_ns, 0x80, 0x88); }

/* ---- stubs ------------------------------------------------------------- */
static int emit_jmp_abs(unsigned char* p, void* target)
{
    p[0] = 0xFF; p[1] = 0x25; p[2] = p[3] = p[4] = p[5] = 0;          /* jmp [rip+0] */
    memcpy(p + 6, &target, 8);
    return 14;
}
static int emit_call_abs(unsigned char* p, void* target)
{
    p[0] = 0xFF; p[1] = 0x15; p[2] = 2; p[3] = p[4] = p[5] = 0;       /* call [rip+2] */
    p[6] = 0xEB; p[7] = 0x08;                                         /* jmp over the qword */
    memcpy(p + 8, &target, 8);
    return 16;
}

static int patch_call(unsigned char* site, unsigned len, unsigned char* stub)
{
    DWORD old; unsigned i;
    long long rel = (long long)stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) return 0;
    if (!VirtualProtect(site, len, PAGE_EXECUTE_READWRITE, &old)) return 0;
    site[0] = 0xE8; memcpy(site + 1, &rel, 4);
    for (i = 5; i < len; i++) site[i] = 0x90;
    VirtualProtect(site, len, old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, len);
    return 1;
}

/* <exe dir>\name into path; 0 if the module path does not fit. */
static int exe_side(const unsigned char* mod, const char* name, char* path, size_t cap)
{
    DWORD n = GetModuleFileNameA((HMODULE)mod, path, (DWORD)cap);
    size_t i, cut = 0, len = strlen(name);
    if (!n || n >= cap) return 0;
    for (i = 0; i < n; i++) if (path[i] == '\\' || path[i] == '/') cut = i + 1;
    if (cut + len + 1 > cap) return 0;
    memcpy(path + cut, name, len + 1);
    return 1;
}

static void read_cfg(const unsigned char* mod)
{
    char path[MAX_PATH + 32], buf[256];
    DWORD got = 0;
    HANDLE f;
    if (!exe_side(mod, "pacing.txt", path, sizeof(path))) return;
    f = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    if (f == INVALID_HANDLE_VALUE) return;
    if (ReadFile(f, buf, sizeof(buf) - 1, &got, NULL)) {
        char* p;
        buf[got] = 0;
        if ((p = strstr(buf, "wait")) != NULL) g_wait = atoi(p + 4) != 0;
        if ((p = strstr(buf, "abs")) != NULL) g_abs = atoi(p + 3) != 0;
    }
    CloseHandle(f);
}

/* One line after 30 s, then one every 5 minutes: enough to see in a player's
   log that both limiters run on schedule, without filling it. */
static DWORD WINAPI stats_thread(LPVOID u)
{
    DWORD period = 30000;
    (void)u;
    for (;;) {
        Sleep(period);
        H->log("PACING: %lu s -- %ld waits slept on the timer, marks %ld on schedule / %ld reset to now%s",
               (unsigned long)(period / 1000), InterlockedExchange(&g_sleeps, 0),
               InterlockedExchange(&g_marks_abs, 0), InterlockedExchange(&g_marks_now, 0),
               g_hires ? "" : " | no high-resolution timer: stock wait");
        period = 300000;
    }
    return 0;
}

__declspec(dllexport) const char* BrosPluginId(void) { return PATCH_BUILD_ID; }
__declspec(dllexport) int BrosPluginInit(const BrosHost* host)
{
    char off[MAX_PATH + 32];
    unsigned char *mod, *stub, *p;
    if (!host || host->abi != BROS_PLUGIN_ABI) return 0;
    if (!HAS(host, mod) || !HAS(host, log) || !HAS(host, alloc_near) || !HAS(host, claim)) return 0;
    H = host; mod = host->mod;
    if (exe_side(mod, "pacing_off.txt", off, sizeof(off)) && GetFileAttributesA(off) != INVALID_FILE_ATTRIBUTES) {
        host->log("PACING: pacing_off.txt is beside the exe -- declined on purpose, stock frame limiters");
        return 0;
    }
    if (memcmp(mod + 0x9E700D, k_yield_r, 5) || memcmp(mod + 0x9E7370, k_yield_m, 5) ||
        memcmp(mod + 0x9E704B, k_mark_r, 14) || memcmp(mod + 0x9E73C0, k_mark_m, 11)) {
        host->log("PACING: declined -- the limiter bytes are not stock (another exe, or patched)");
        return 0;
    }
    read_cfg(mod);
    if (!g_wait && !g_abs) { host->log("PACING: declined -- pacing.txt says wait 0 and abs 0"); return 0; }
    if (!host->claim(OWNER, 0x9E700D, 5, "render limiter yield") ||
        !host->claim(OWNER, 0x9E7370, 5, "main limiter yield") ||
        !host->claim(OWNER, 0x9E704B, 14, "render limiter mark") ||
        !host->claim(OWNER, 0x9E73C0, 11, "main limiter mark")) {
        host->log("PACING: declined -- a limiter site is claimed by someone else");
        return 0;
    }
    g_tls = TlsAlloc();
    {   /* one high-resolution timer now, so the log says which wait the game gets */
        HANDLE t = CreateWaitableTimerExW(NULL, NULL, 0x00000002, TIMER_ALL_ACCESS);
        if (t) CloseHandle(t); else g_hires = 0;
    }
    stub = (unsigned char*)host->alloc_near(mod + 0x9E7000, 256);
    if (!stub) { host->log("PACING: declined -- no stub memory near the exe"); return 0; }
    /* stub A: the yield -- xmm0 = elapsed us, xmm6 = interval us -> pace_wait(xmm0, xmm1) */
    p = stub;
    p[0] = 0x66; p[1] = 0x0F; p[2] = 0x28; p[3] = 0xCE;             /* movapd xmm1, xmm6 */
    emit_jmp_abs(p + 4, (void*)pace_wait);
    /* stub B: render mark -- rcx = [[rsi]+0x10], rdx = rax (now). The code after
       0x9E7059 sets rcx/rdx/rax again before reading them. */
    {
        unsigned char* q = stub + 32; int n = 0;
        q[n++] = 0x48; q[n++] = 0x8B; q[n++] = 0x0E;                   /* mov rcx,[rsi]      */
        q[n++] = 0x48; q[n++] = 0x8B; q[n++] = 0x49; q[n++] = 0x10;    /* mov rcx,[rcx+10h]  */
        q[n++] = 0x48; q[n++] = 0x89; q[n++] = 0xC2;                   /* mov rdx,rax        */
        n += emit_jmp_abs(q + n, (void*)pace_mark_r);
    }
    /* stub C: main mark -- rcx = [rsi+0x10], rdx = rax; rcx is put back after (the stock left it there) */
    {
        unsigned char* q = stub + 96; int n = 0;
        q[n++] = 0x48; q[n++] = 0x8B; q[n++] = 0x4E; q[n++] = 0x10;    /* mov rcx,[rsi+10h]  */
        q[n++] = 0x48; q[n++] = 0x89; q[n++] = 0xC2;                   /* mov rdx,rax        */
        q[n++] = 0x48; q[n++] = 0x83; q[n++] = 0xEC; q[n++] = 0x28;    /* sub rsp,28h        */
        n += emit_call_abs(q + n, (void*)pace_mark_m);
        q[n++] = 0x48; q[n++] = 0x83; q[n++] = 0xC4; q[n++] = 0x28;    /* add rsp,28h        */
        q[n++] = 0x48; q[n++] = 0x8B; q[n++] = 0x4E; q[n++] = 0x10;    /* mov rcx,[rsi+10h]  */
        q[n++] = 0xC3;                                                 /* ret                */
    }
    FlushInstructionCache(GetCurrentProcess(), stub, 256);
    if (g_wait) {
        if (!patch_call(mod + 0x9E700D, 5, stub) || !patch_call(mod + 0x9E7370, 5, stub)) {
            host->log("PACING: the yield sites could not be written"); return 0;
        }
    }
    if (g_abs) {
        if (!patch_call(mod + 0x9E704B, 14, stub + 32) || !patch_call(mod + 0x9E73C0, 11, stub + 96)) {
            host->log("PACING: the mark sites could not be written"); return 0;
        }
    }
    CloseHandle(CreateThread(NULL, 0, stats_thread, NULL, 0, NULL));
    host->log("PACING: ARMED [%s] -- wait %d (%s), abs %d (absolute schedule) on the render "
              "(0x9E6FA0) and main (0x9E7300) limiters; stubs at %p", PATCH_BUILD_ID, g_wait,
              !g_wait ? "stock" : g_hires ? "high-resolution timer sleep, then PAUSE spin"
                                          : "no high-resolution timer here: stock wait", g_abs, stub);
    return 1;
}

BOOL WINAPI DllMain(HINSTANCE h, DWORD r, LPVOID v) { (void)h; (void)r; (void)v; return TRUE; }
