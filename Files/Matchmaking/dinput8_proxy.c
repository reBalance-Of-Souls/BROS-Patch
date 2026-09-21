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
 *  CANONICAL MERGED SOURCE -- 2026-08-05.
 *  Four divergent copies of this file existed (game dir, Patch/,
 *  Patch_Dev_Environment/, and the community-patch repo) and each was
 *  missing patches the others had. This file is the union of all four and
 *  is the ONLY one that should be edited from now on. It contains:
 *      Steam matchmaking hook   (patch-only pool + worldwide region)
 *      patch_version_string     title -> "ReBalance <ver>"
 *      patch_yamamoto_selfcost  sublimation-Kikon 2-konpaku self-cost -> 0
 *      patch_byakuya_evo_icon   Pl22 stance icon kept visible in evo
 *      patch_aizen_kikon_counter  Kikon Counter costs 5 flames only  [DISABLED]
 *      patch_aizen_flamecost    Aizen SP1 costs 1 (base) / 3 (evo) flames [DISABLED]
 *      patch_stage_new_id_gate  brand-new stage ids can load their geometry
 *      patch_room_result_menu   room match ends on the free-match result menu
 *      patch_room_rematch_wait  a split choice falls back to the room in 1 s, not 120
 *      patch_reawaken_battle    the Reawakeners start the match Reawakened [OFF by default]
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
#include <stdint.h>
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
#define ENABLE_ROOM_RESULT_MENU    1   /* room match ends on a result menu          */
#define ENABLE_UIRES_GUARD         1   /* NULL guard for the UI resource-table lookup */

/* ---- boot shortcuts, ported from the dev environment 2026-08-26 --------
   FAST_BOOT and SKIP_LOGOS are ON here: they are what makes a normal launch
   open on the title screen. BOOT_TRAINING and BOOT_ROOMMATCH are OFF and each
   ships as its own loader under GameModes/, selected by its Quick Launch
   script. None of them changes any simulation, so none carries a pool tag. */
#define ENABLE_FAST_BOOT           1   /* skip the AUTO_SAVE notice at boot */
#define ENABLE_SKIP_LOGOS          1   /* skip the four publisher logos     */
#ifndef ENABLE_BOOT_TRAINING
#define ENABLE_BOOT_TRAINING       0   /* boot into the Training character select */
#endif
#ifndef ENABLE_BOOT_ROOMMATCH
#define ENABLE_BOOT_ROOMMATCH      0   /* boot into the online room-match menu */
#endif

/* "Reawakening Battle" -- a TEST-ONLY game mode, off in the shipped loader.
   The launcher installs GameModes/ReawakeningBattle/dinput8.dll, which IS this
   source built with  -DENABLE_REAWAKEN_BATTLE=1  , only while that mode is
   selected; the default loader keeps the 0 and behaves exactly as before. */
#ifndef ENABLE_REAWAKEN_BATTLE
#define ENABLE_REAWAKEN_BATTLE     0   /* the Reawakeners start Reawakened */
#endif

/* Yhwach reaches the Reawakening on his NINTH Kaiser, not his eighth, and he
   opens EVERY mode on level 1 -- Training included. Both are balance fixes,
   not modes: they change no netcode and shift no matchmaking pool, so they
   ship ON. See PART 17 and PART 18. */
#ifndef ENABLE_YHWACH_REAWAKEN_9
#define ENABLE_YHWACH_REAWAKEN_9   1   /* Reawakening wants 9 Kaiser, not 8 */
#endif
#ifndef ENABLE_YHWACH_START_LEVEL
#define ENABLE_YHWACH_START_LEVEL  1   /* level 1 at the bell in every mode  */
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
static void log_line(const char* fmt, ...)
{
#if ENABLE_LOG
    char path[MAX_PATH], buf[512];
    SYSTEMTIME t; GetLocalTime(&t);
    va_list ap; va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap); va_end(ap);
    exe_dir_path("patch_ranked.log", path, sizeof(path));
    FILE* f = fopen(path, "a");
    if (f) { fprintf(f, "[%02d:%02d:%02d.%03d] %s\n",
                     t.wHour,t.wMinute,t.wSecond,t.wMilliseconds, buf); fclose(f); }
#else
    (void)fmt;
#endif
}


/* ---- trampoline allocation within rel32 reach of a hook site ---------
   An E9 jmp only reaches +/-2GB, so a code cave has to land near the exe.
   VirtualAlloc with an address hint does that.

   ! This function is REQUIRED, not new convenience: patch_kaiser_trace
   below has always called gauge_alloc_near and this file has never defined
   it. mingw-gcc accepted that silently -- kaiser_trace is static and never
   invoked, so -O2 deleted it before the linker could object -- but any
   C99-conforming compiler (clang, zig cc) refuses the file outright. Now
   it builds with either. -------------------------------------------- */
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

static void hk_AddNumFilter(void* self, const char* key, int value, int cmp)
{
    if (key && strcmp(key,"issuer")==0) { log_line("SEARCH: filtering issuer %d -> %d", value, g_issuer); value=g_issuer; }
    o_AddNumFilter(self,key,value,cmp);
}
static unsigned char hk_SetLobbyData(void* self, uint64_t lobby, const char* key, const char* value)
{
    char b[16];
    if (key && strcmp(key,"issuer")==0) { snprintf(b,sizeof(b),"%d",g_issuer); log_line("HOST: tagging issuer %s -> %s", value?value:"(null)", b); value=b; }
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
static int try_install(void)
{
    HMODULE steam = GetModuleHandleA("steam_api64.dll");
    if (!steam) return 0;
    SteamMatchmaking_v009_t get = (SteamMatchmaking_v009_t)GetProcAddress(steam,"SteamAPI_SteamMatchmaking_v009");
    if (!get) { log_line("ERROR: SteamAPI_SteamMatchmaking_v009 missing"); return -1; }
    void* mm = get(); if (!mm) return 0;
    void** vt = *(void***)mm; if (!vt) return 0;
    g_vt = vt;
    if (!patch_slot(vt,VT_ADD_NUM_FILTER,(void*)&hk_AddNumFilter,(void**)&o_AddNumFilter) ||
        !patch_slot(vt,VT_SET_LOBBY_DATA,(void*)&hk_SetLobbyData,(void**)&o_SetLobbyData) ||
        !patch_slot(vt,VT_JOIN_LOBBY,(void*)&hk_JoinLobby,(void**)&o_JoinLobby) ||
        !patch_slot(vt,VT_REQUEST_LIST,(void*)&hk_RequestLobbyList,(void**)&o_RequestLobbyList)) { log_line("ERROR: vtable patch failed"); return -1; }
    log_line("HOOKS INSTALLED (in game) -- pool code %d, join-guard %s, region=worldwide", g_issuer, g_block?"ON":"log-only");
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

/* ---- trampoline allocator, needed by the label hooks below ---------- */
static void* rr_alloc_near(unsigned char* anchor, size_t n)
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
#define ROOMRESULT_GLOBAL_RVA 0x1CFBAB8  /* &SceneGlobalInfo; +0x498 = online mode */
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
    unsigned char* gptr = mod + ROOMRESULT_GLOBAL_RVA;   /* &SceneGlobalInfo* */
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

    stub = (unsigned char*)rr_alloc_near(site, 128);
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
    stub = (unsigned char*)rr_alloc_near(site, 0x200);
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

#if ENABLE_BOOT_ROOMMATCH
#define BOOTTR_DEST_RVA  BOOTTR_JUMP_ROOM_RVA
#define BOOTTR_DEST_NAME "JUMP_RoomMatchMenu"
#else
#define BOOTTR_DEST_RVA  BOOTTR_JUMP_TRAINING_RVA
#define BOOTTR_DEST_NAME "JUMP_TrainingCharacterSelect"
#endif
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
#if ENABLE_BOOT_ROOMMATCH
    /* The room-match issuer (0x1407E6847) writes no mode at all -- the online
       menu has already chosen by then, through the selector this sets. */
    (void)o;
    *(int*)(mod + BOOTTR_ONLINE_SEL_RVA) = BOOTTR_ONLINE_SEL_ROOM;
    if (!said) { said = 1;
        log_line("BOOTTRAIN: online selector at RVA 0x%X set to %d (room match) "
                 "before the jump", BOOTTR_ONLINE_SEL_RVA, BOOTTR_ONLINE_SEL_ROOM); }
#else
    if (o) {
        *(int*)((unsigned char*)o + BOOTTR_MODE_OFF) = BOOTTR_MODE_TRAINING;
        if (!said) { said = 1;
            log_line("BOOTTRAIN: setup singleton %p, mode +0x%X set to %d (Training) "
                     "before the jump", o, BOOTTR_MODE_OFF, BOOTTR_MODE_TRAINING); }
    } else if (!said) { said = 1;
        log_line("BOOTTRAIN: setup singleton is NULL and could not be created -- "
                 "jumping without setting the mode, expect offline versus");
    }
#endif
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
        log_line("BOOTTRAIN: " BOOTTR_DEST_NAME " out of rel32 range -- skipped");
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
             "calls %p, which prepares the mode and then sends " BOOTTR_DEST_NAME
             " to the dispatcher at %p, instead of "
             "raising LOGO_NEXT through vtable slot 0x88",
             BOOTTR_WINDOW_RVA, (void*)&boottr_handoff,
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


/* =====================================================================
 *  patch_uires_guard -- the Training -> Battle -> CharaSelect -> Battle crash
 *
 *  Ported from the dev environment 2026-09-07. This is the fix players
 *  report as "the Nel crash": it was deployed into a working tree on
 *  2026-09-05, never committed, and commit 52f919d's revert then took the
 *  shipped dinput8.dll back to a build that predates the guard. No commit
 *  in this repository has ever carried it. It carries it now.
 *
 *  CRASH: access violation at exe+0x9DB40A -- reading from 0x4
 *
 *      0x9DB400  mov    [rsp+8], rbx
 *      0x9DB405  mov    [rsp+10h], rdi
 *      0x9DB40A  movsxd rax, [rcx+4]      <-- rcx = NULL
 *
 *  0x9DB400 is the UI resource-table lookup: find_row_by_id(table, id). It
 *  reads a row count at table+4 and walks 8-byte entries from table+0xC
 *  comparing a dword id, returning the matching row or 0. Its callers at
 *  0x23EAA0.. parse the row as CSV, so this is the model/resource index.
 *
 *  Requesting a UI page whose scene is absent -- whose .cat data was never
 *  loaded -- lands here with a NULL table. Training loads
 *  ui_TrainingMenu_*.cat because STrainingMenu exists; Battle does not.
 *  Going Training -> Battle -> CharacterSelect -> Battle asks for a row out
 *  of a table that is no longer loaded, and the lookup dereferences NULL.
 *  Which character was on the cursor coming back in is irrelevant -- Nel
 *  was simply who got picked. It is not a Nel bug and not an asset bug.
 *
 *  EVERY call site already null-checks the RETURN value:
 *
 *      call 0x1409db400 ; test rax,rax ; jne .. ; xor r15d,r15d
 *      call 0x1409db400 ; mov rcx,rax  ; test rax,rax ; je ..
 *
 *  so "not found" is a state the callers are written to handle. The lookup
 *  simply never checks its own argument. Returning 0 for a NULL table is
 *  therefore not a behaviour change invented here -- it is the answer the
 *  callers already expect for a row that is not present.
 *
 *  5-byte detour to a near cave; the stolen instruction is one whole
 *  instruction (mov [rsp+8],rbx, exactly 5 bytes) so nothing is padded and
 *  no half instruction is left behind. The site is byte-verified first, so
 *  a game update is a logged skip, never a crash.
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

/* ================= PART 17: Yhwach Reawakens on the NINTH Kaiser =====
 *  THE BUG: Yhwach Awakens with EIGHT Kaiser on the gauge and comes out
 *  Reawakened. He is meant to reach the Reawakening on the ninth.
 *
 *  THE GATE. Two sites, both private to this character by an explicit chara-id
 *  test, both comparing the Kaiser level (`fighter+0x1A40`) against the image's
 *  8.0f at 0x1414C0414 while he is still in the base form:
 *
 *      0x482B62  cmp    [rdi+0xC00],0x34       ; chara id 52 = Yhwach
 *      0x482B6F  movss  xmm0,[rdi+0x1A40]      ; the Kaiser level
 *      0x482B77  comiss xmm0,[8.0f]
 *      0x482B7E  jb     <ordinary Awakening>
 *                ...builds "READY_URA_TRANSFORM", then plays `ct_revolut`
 *
 *      0x4A5ED7  cmp    [r14+0xC00],0x34       ; the same test on the routing
 *      0x4A5EE5  movss  xmm0,[r14+0x1A40]      ; side, which picks
 *      0x4A5EEE  comiss xmm0,[8.0f]            ; `revolut_start`
 *      0x4A5EF5  jb     <ordinary Awakening>
 *
 *  So `ura_transform_mothod = 3` is "Kaiser >= 8" in the binary. The fix
 *  repoints both displacements at the 9.0f four bytes further on
 *  (0x1414C041C): two disp32 fields, eight bytes of exe, nothing else touched.
 *
 *  ⚠ BOTH OR NEITHER. Moving one alone leaves the other able to Reawaken him
 *  on eight.
 *
 *  ⚠ The `-0.5` AddUniqueVal pair on `1_normal_ct_ct_evolve` in
 *  `pl052.tadjpkg` is correct and still needed -- it cancels the `+1` the
 *  Awakening grants, which is a separate mechanic from this gate. Do not
 *  remove it with this change.
 *
 *  ★ It took two wrong fixes to find these two sites, and the way out is the
 *  part worth keeping: the first attempt moved the 9.0f inside Yhwach's
 *  per-frame handler 0x516340 to 10.0 and changed NOTHING in game, because
 *  that handler's auto-Reawakening is a different path from the one a player's
 *  Awakening takes. What ended it was a probe on the transform routine logging
 *  the RETURN ADDRESS: it named the caller (the `Revolut` action component at
 *  0x3A6E10) and showed the level at 8.000 with its mirror +0x1A34 also 8.000,
 *  so there was no transient and `ct_ct_evolve` had never played. When a fix
 *  changes nothing in game, instrument rather than re-reason.
 *
 *  Confirmed in game 2026-09-21. DataChakka: guides/Nilsix researches/
 *  Yhwach Kaiser Level/BROS_YHWACH_KAISER_LEVEL.md §8.
 * ==================================================================== */
#define YRW_SITES      2
#define YRW_OLD_CONST  0x14C0414u  /* the 8.0f the two gates read today    */
#define YRW_NEW_CONST  0x14C041Cu  /* the 9.0f, four bytes further on      */

/* Each gate: the `comiss xmm?,[rip+disp32]` and the guard in front of it, so a
   moved function is refused instead of silently mis-patched. */
static const struct {
    unsigned       insn_rva;
    unsigned       disp_rva;
    unsigned       next_rva;
    unsigned       sig_rva;
    unsigned char  sig[24];
    unsigned       sig_len;
} g_yrw[YRW_SITES] = {
    { 0x482B77u, 0x482B7Au, 0x482B7Eu, 0x482B62u,
      { 0x83,0xBF,0x00,0x0C,0x00,0x00,0x34,            /* cmp [rdi+0xC00],0x34   */
        0x0F,0x85,0x1D,0x01,0x00,0x00,                 /* jne                    */
        0xF3,0x0F,0x10,0x87,0x40,0x1A,0x00,0x00 }, 21  /* movss xmm0,[rdi+0x1A40]*/
    },
    { 0x4A5EEEu, 0x4A5EF1u, 0x4A5EF5u, 0x4A5ED7u,
      { 0x41,0x83,0xBE,0x00,0x0C,0x00,0x00,0x34,       /* cmp [r14+0xC00],0x34   */
        0x0F,0x85,0xB0,0x00,0x00,0x00,                 /* jne                    */
        0xF3,0x41,0x0F,0x10,0x86,0x40,0x1A,0x00,0x00 }, 23
    }
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
        log_line("YHWACH_REAW: Reawakening gate 8.0 -> 9.0 at exe+0x%X and exe+0x%X"
                 " (%u written, %u already right). Eight Kaiser now gives the"
                 " ordinary Awakening; the Reawakening wants nine.",
                 g_yrw[0].insn_rva, g_yrw[1].insn_rva, done, already);
    else
        log_line("YHWACH_REAW: \u26a0 only %u of %u gates moved to 9.0 -- Yhwach can"
                 " still reach the Reawakening on eight through the site that did"
                 " not take. Read the lines above.", done + already, YRW_SITES);
}

/* ================= PART 18: Yhwach's level 1 in EVERY mode ===========
 *  THE BUG: Yhwach opens a Versus or online match on Kaiser level 1 and a
 *  TRAINING match on level 0.
 *
 *  WHY. The grant is data -- an `AddUniqueVal` with `is_val_set = 1` on
 *  `1_normal_ct_ct_start`, the only component that action carries in
 *  `pl052.tadjpkg`. `ct_start` is the battle-intro action, and Training does
 *  not play it. Nothing else touches the level at the opening bell, so in
 *  Training it stays where the engine left it: zero.
 *
 *  ★ THE FIX IS A FLOOR, NOT A GRANT, and that is what makes it safe in every
 *  mode without knowing anything about match or round boundaries: while Yhwach
 *  is in a battle, a Kaiser level of exactly +0.0 is the bug state and nothing
 *  else. `ct_start` assigns 1, the SP grants only add, and the `-0.5` pair on
 *  `ct_ct_evolve` nets zero -- so the counter never legitimately reads 0 once a
 *  match is running. Raising 0 to 1 every frame therefore costs nothing where
 *  the data already works, and fixes the mode where it never ran. It is also
 *  idempotent with the record, which assigns rather than adds.
 *
 *  ⚠ The one thing that COULD read 0 deliberately is a combo node carrying
 *  `unique_combo = 10`, which 0x140518430 evaluates as "level <= 0". No node in
 *  `pl052.tcmbpkg` uses 10 -- checked, the file uses 2..8 only. Re-check that
 *  before anyone adds one.
 *
 *  WHERE. 0x140516340 is Yhwach's per-frame unique handler -- the function that
 *  pushes his HUD level through `ActionCharaUniqueUI_Pl52::SetLevel`, which
 *  PART 16 established "runs every frame for Yhwach and nobody else". The hook
 *  sits on the first instruction after its own null check, where `rdx` is the
 *  fighter:
 *
 *      0x516390  cmp  byte [rdx+0x9A8],0
 *      0x516397  je   0x5163B2
 *      ...
 *      0x5163B2  movups xmm0,[rdx+0x1A10]   <- stolen, re-executed LAST so the
 *      0x5163B9  movaps [rbp+0x90],xmm0        block copy sees the new level
 *
 *  THE STUB saves rax around its own use and restores it, which is safe here
 *  because this is mid-function and rsp is already framed -- unlike the
 *  transform entry PART 16 hooks, where a push would frame the callee off a
 *  captured rsp. Flags are not live at the site: it is a branch TARGET.
 *
 *  ⚠ The first attempt hooked 0x460A4E, a store in the unique-block reset at
 *  0x460840. Right idea, unproven site: `[rdi+0xC00]` is only READ there, so
 *  nothing established that the chara id was populated, and a match played with
 *  it armed left the gauge on 0. Its watcher then polled for 100 s from DLL
 *  init -- a window that expired during the menu walk, so its negative result
 *  meant nothing at all. A counter is only evidence if its window covered the
 *  event; hence the two separate counters below.
 *
 *  Confirmed in game 2026-09-21. DataChakka: guides/Nilsix researches/
 *  Yhwach Kaiser Level/BROS_YHWACH_KAISER_LEVEL.md §9.
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
       inside the window. */
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
                 " in a match, or this is not his per-frame handler after all.", YSL_RVA);
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

static DWORD WINAPI worker(LPVOID u)
{
    (void)u;
    log_line("==== dinput8 proxy loaded INTO GAME (pid %lu) ====", GetCurrentProcessId());
    load_settings();
    patch_version_string();
    patch_yamamoto_selfcost();
    /* patch_byakuya_evo_icon() repoints Pl22's vtable slot 22 (RVA 0x1440678)
       to a private form-getter stub. The Sakura Gauge hook under development
       writes to that SAME slot, so while testing the gauge, comment this call
       out locally -- but it MUST stay enabled in anything that ships, or a
       dev->live push silently removes Byakuya's evo icon (which is exactly how
       it went missing once already). */
    patch_byakuya_evo_icon();
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
    if (ENABLE_UIRES_GUARD) patch_uires_guard();
    else log_line("UIRESGUARD: DISABLED at build time -- Training->Battle->"
                  "CharaSelect->Battle still crashes at exe+0x9DB40A");
    if (ENABLE_ROOM_RESULT_MENU) { patch_room_result_menu(); patch_room_rematch_wait(); }
    else log_line("ROOMRESULT: DISABLED at build time -- a room match still ends with "
                  "no menu and drops back to the room on a timer");
    if (ENABLE_FAST_BOOT) patch_fast_boot();
    else log_line("FASTBOOT: DISABLED at build time -- boot still stops on the "
                  "clickable auto-save notice");
    if (ENABLE_SKIP_LOGOS) patch_skip_logos();
    else log_line("SKIPLOGO: DISABLED at build time -- the four boot logos still "
                  "play before the title screen");
    if (ENABLE_BOOT_TRAINING || ENABLE_BOOT_ROOMMATCH) patch_boot_training();
    else log_line("BOOTTRAIN: DISABLED at build time -- boot goes to the title "
                  "screen (build with -DENABLE_BOOT_TRAINING=1 or "
                  "-DENABLE_BOOT_ROOMMATCH=1 for those loaders)");
    if (ENABLE_YHWACH_REAWAKEN_9) patch_yhwach_reawaken();
    else log_line("YHWACH_REAW: DISABLED at build time -- Yhwach still Reawakens "
                  "off his EIGHTH Kaiser (build with -DENABLE_YHWACH_REAWAKEN_9=1)");
    if (ENABLE_YHWACH_START_LEVEL) patch_yhwach_start_level();
    else log_line("YHWACH_LV1: DISABLED at build time -- Yhwach still opens Training "
                  "on Kaiser level 0 (build with -DENABLE_YHWACH_START_LEVEL=1)");
    if (ENABLE_REAWAKEN_BATTLE) patch_reawaken_battle();
    else log_line("REAWAKEN: DISABLED at build time -- Reawakenings use their stock "
                  "triggers (build with -DENABLE_REAWAKEN_BATTLE=1 for the "
                  "Reawakening Battle game mode's loader)");
    /* Wait for steam_api64 as long as it takes.

       This used to poll 600 times at 500 ms -- five minutes -- and then give up
       for good. The game does not load steam_api64 until the title screen is
       left, so a session left sitting at "Press Start" longer than that had
       nothing still looking when it finally appeared, and the matchmaking patch
       never installed.

       The consequence is the one the issuer tagging exists to prevent: the
       player lands in the DEFAULT matchmaking pool and meets unpatched clients,
       with a single ERROR line as the only sign.

       try_install()'s three answers are unchanged -- 1 installed, negative means
       this is not the game process and giving up is right, 0 means keep
       waiting. Only the cap is gone.

       500 ms while a normal start is in progress, 2 s afterwards: the fast poll
       is there to hook a real launch promptly, and a session that has idled past
       five minutes has nothing to be prompt about. */
    {
        ULONGLONG t0 = GetTickCount64();
        int said = 0;

        for (;;) {
            int r = try_install();
            if (r == 1) {
                ULONGLONG secs = (GetTickCount64() - t0) / 1000;
                if (secs >= 300)
                    log_line("MATCH: steam_api64 appeared after %llu s -- the old "
                             "five-minute cap would have abandoned this session, "
                             "leaving the player in the default pool.",
                             (unsigned long long)secs);
                return 0;
            }
            if (r < 0)
                return 0;              /* not the game process; give up is correct */

            if (!said && GetTickCount64() - t0 >= 300000) {
                said = 1;
                log_line("MATCH: steam_api64 still absent after five minutes -- "
                         "STILL WAITING. The game loads it when the title screen "
                         "is left, so idling there is normal and no longer ends "
                         "the attempt.");
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
    return TRUE;
}
