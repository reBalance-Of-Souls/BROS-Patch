/* =====================================================================
 *  pl033_plugin.c -- Coyote Stark, as ReBalanceOfSouls\pl033.dll.
 *
 *  WHAT IT FIXES
 *  -------------
 *  The HUD lied about Primera. Reported 2026-09-23 with a screenshot:
 *  Stark Awakened on 3 Konpaku, the rival on 4, and the rival's number
 *  stayed WHITE -- "not killable" -- although Primera destroys 4 and the
 *  next Kikon would have ended the match.
 *
 *  WHY IT LIED
 *  -----------
 *  The number the HUD compares against the rival's Konpaku is resolved at
 *  0x14014ABD0 (see DataChakka "Konpaku and Kikon" §6): the running
 *  maximum of `soul_damage` over the Kikon's hit records, read from the
 *  action data. After that maximum the function switches on the character
 *  id -- a byte table at RVA 0x14BB00, offsets at 0x14BAD4 -- and ten
 *  characters get a HARDCODED value instead. Stark's case:
 *
 *      14B812  cmp    dword [rdx+0x1094], 1     ; Awakened?
 *      14B819  jne    14B525                    ; no -> keep the data value
 *      14B81F  movss  xmm0, [3.0f]
 *      14B827  mov    rbx, [rbp+0x958]
 *      14B82E  comiss xmm0, [rdx+0x10C0]        ; own Konpaku <= 3 ?
 *      14B835  jb     14B52C                    ; no -> keep the data value
 *      14B83B  movaps xmm8, xmm10               ; xmm10 = 2.0f  <-- HERE
 *      14B83F  jmp    14B52C
 *
 *  2.0 is vanilla Primera: `soul_damage 2`, 3 Konpaku. The Community Patch
 *  raised `evo_ct_sp_break02` to `soul_damage 3`, so the hit takes 4 while
 *  the HUD still promises 3. Data cannot reach this: the value never comes
 *  from the data.
 *
 *  WHAT THIS DOES
 *  --------------
 *  Replaces the case with a jump to a stub that runs the SAME test and
 *  loads the value Primera really has, read at start-up from the installed
 *  Script/Action/pl033.tadjpkg the way the resolver reads it (max over
 *  the Attack records of soul_damage + charge_soul_damage, or
 *  add_bomb_soul_damage if larger). So the HUD follows whatever data is
 *  installed: vanilla reads 2 and changes nothing, the Community Patch
 *  reads 3, and a later retune needs no rebuild.
 *
 *  ⚠ NEVER THE TAIL. 0x14B83B / 0x14B83F are also reached from the pl017
 *  and pl050 cases (0x14B7D3 `jb 14B83B`, 0x14B89C `je 14B83B`), so the
 *  shared `movaps xmm8,xmm10` is not Stark's to change. His own body,
 *  0x14B812..0x14B83A, has exactly one way in -- the jump table entry --
 *  checked over the whole function and every rel32 in .text.
 *
 *  Both exits of the stock case reach 0x14B52C with rbx = [rbp+0x958]
 *  (the jne path through 0x14B525, which loads it), so the stub loads rbx
 *  first and leaves for 0x14B52C on every path. xmm0 is written before it
 *  is read on every path after 0x14B52C.
 *
 *  WHAT IT CLAIMS
 *  --------------
 *      exe+0x14B812   0x29   Stark's case of the HUD Kikon resolver
 *  Only the first 7 bytes are written (E9 rel32 + 2 NOPs); the rest is dead
 *  code once the jump is in, and is claimed so nobody patches it believing
 *  it still runs.
 *
 *  ONLINE
 *  ------
 *  The resolved value is stored in the fighter (it lands in the block at
 *  +0xFA0) and may be read by more than the HUD, so treat this as a change
 *  of simulation: both players need the same plugin. The launcher mirrors
 *  Plugins/ to everyone on a build, and the pool is seeded from the commit.
 * ==================================================================== */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>

#include "bros_plugin.h"

static const char PL033_OWNER[] = "pl033.dll";

static const BrosHost* g_host = 0;

#define PL033_RVA_CASE     0x14B812u /* Stark's case in the resolver switch  */
#define PL033_CASE_LEN     0x29u     /* up to the shared tail at 0x14B83B    */
#define PL033_RVA_JOIN     0x14B52Cu /* where both stock exits meet          */

#define PL033_ACTION       "evo_ct_sp_break02"   /* Primera                  */
#define PL033_STOCK_VALUE  2.0f                  /* the exe's hardcode       */
#define PL033_THRESHOLD    3.0f                  /* the exe's own test       */

#define CHARA_FORM         0x1094
#define CHARA_KONPAKU      0x10C0

/* The stub's data block, after the code. The code below was generated and
   disassembled with capstone before it went in; every rip-relative disp32
   in it is a constant because code and data share one page. */
#define D_SEEN     0x80   /* qword: Stark resolutions reaching the case     */
#define D_FIRED    0x88   /* qword: ...of those, Primera value applied      */
#define D_FIGHTER  0x90   /* qword: last Stark fighter seen                 */
#define D_THRESH   0x98   /* float: 3.0                                     */
#define D_VALUE    0x9C   /* float: Primera's soul damage, from the data    */
#define D_KONPAKU  0xA0   /* float: own Konpaku at the last application     */
#define STUB_SIZE  0xC0

/*   +00  mov    rbx,[rbp+0x958]
 *   +07  lock inc qword [rip+SEEN]
 *   +0F  mov    [rip+FIGHTER],rdx
 *   +16  cmp    dword [rdx+0x1094],1
 *   +1D  jne    +51
 *   +1F  movss  xmm0,[rip+THRESH]
 *   +27  comiss xmm0,[rdx+0x10C0]
 *   +2E  jb     +51
 *   +30  movss  xmm8,[rip+VALUE]
 *   +39  movss  xmm0,[rdx+0x10C0]
 *   +41  movss  [rip+KONPAKU],xmm0
 *   +49  lock inc qword [rip+FIRED]
 *   +51  jmp    exe+0x14B52C          (rel32 filled in at install) */
static const unsigned char PL033_HUD_STUB[86] = {
    0x48, 0x8B, 0x9D, 0x58, 0x09, 0x00, 0x00, 0xF0, 0x48, 0xFF, 0x05, 0x71,
    0x00, 0x00, 0x00, 0x48, 0x89, 0x15, 0x7A, 0x00, 0x00, 0x00, 0x83, 0xBA,
    0x94, 0x10, 0x00, 0x00, 0x01, 0x75, 0x32, 0xF3, 0x0F, 0x10, 0x05, 0x71,
    0x00, 0x00, 0x00, 0x0F, 0x2F, 0x82, 0xC0, 0x10, 0x00, 0x00, 0x72, 0x21,
    0xF3, 0x44, 0x0F, 0x10, 0x05, 0x63, 0x00, 0x00, 0x00, 0xF3, 0x0F, 0x10,
    0x82, 0xC0, 0x10, 0x00, 0x00, 0xF3, 0x0F, 0x11, 0x05, 0x57, 0x00, 0x00,
    0x00, 0xF0, 0x48, 0xFF, 0x05, 0x37, 0x00, 0x00, 0x00, 0xE9, 0x00, 0x00,
    0x00, 0x00
};
#define STUB_EXIT_REL32   82      /* offset of the exit jmp's rel32         */

/* The stock case, byte for byte (installed exe 28,283,464 B = Clean_EXE).
   Its rel32s are part of the signature: a different exe is a different
   layout, and then nothing is written. */
static const unsigned char PL033_CASE_SIG[PL033_CASE_LEN] = {
    0x83, 0xBA, 0x94, 0x10, 0x00, 0x00, 0x01, 0x0F, 0x85, 0x06, 0xFD, 0xFF,
    0xFF, 0xF3, 0x0F, 0x10, 0x05, 0x6D, 0x4B, 0x37, 0x01, 0x48, 0x8B, 0x9D,
    0x58, 0x09, 0x00, 0x00, 0x0F, 0x2F, 0x82, 0xC0, 0x10, 0x00, 0x00, 0x0F,
    0x82, 0xF1, 0xFC, 0xFF, 0xFF
};

static unsigned char* g_stub = 0;

static void log_line(const char* fmt, ...)
{
    char buf[1024];
    va_list ap;
    if (!g_host || !g_host->log) return;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf) - 1, fmt, ap);
    va_end(ap);
    buf[sizeof(buf) - 1] = 0;
    g_host->log("%s", buf);
}

/* ---- reading Primera out of the installed data ----------------------
   The .tadjpkg layout is DataChakka's bros_action.py, measured over all 96
   shipped packages: "actadj_pkg", u32 count at 0x20, 72-byte index records
   (char[64] name, u32 off, u32 size) from 0x24, and per action an "adjb"
   block of components, each with a bag of key/value strings. */
struct rd { const unsigned char* p; size_t n, o; int bad; };

static const char* rd_str(struct rd* r)
{
    const char* s;
    size_t i = r->o;
    while (i < r->n && r->p[i]) i++;
    if (i >= r->n) { r->bad = 1; return ""; }
    s = (const char*)r->p + r->o;
    r->o = i + 1;
    return s;
}

static unsigned rd_u32(struct rd* r)
{
    unsigned v = 0;
    if (r->o + 4 > r->n) { r->bad = 1; return 0; }
    memcpy(&v, r->p + r->o, 4);
    r->o += 4;
    return v;
}

/* The resolver's getter returns an int; truncate the same way. */
static int as_int(const char* s) { return s && *s ? (int)strtod(s, 0) : 0; }

/* -> 1 and *out = the value the resolver would compute for Primera. */
static int pl033_primera_from_data(float* out, int* records, char* path, size_t pathsz)
{
    FILE* f;
    unsigned char* d;
    long sz;
    unsigned cnt, i;
    char* slash;

    if (!GetModuleFileNameA((HMODULE)g_host->mod, path, (DWORD)pathsz)) return 0;
    slash = strrchr(path, '\\');
    if (!slash) return 0;
    slash[1] = 0;
    strncat(path, "Script\\Action\\pl033.tadjpkg", pathsz - strlen(path) - 1);

    f = fopen(path, "rb");
    if (!f) return 0;
    fseek(f, 0, SEEK_END); sz = ftell(f); fseek(f, 0, SEEK_SET);
    if (sz < 0x24 || sz > 64L * 1024 * 1024) { fclose(f); return 0; }
    d = (unsigned char*)malloc((size_t)sz);
    if (!d) { fclose(f); return 0; }
    if (fread(d, 1, (size_t)sz, f) != (size_t)sz) { fclose(f); free(d); return 0; }
    fclose(f);

    if (memcmp(d, "actadj_pkg", 10) != 0) { free(d); return 0; }
    memcpy(&cnt, d + 0x20, 4);

    for (i = 0; i < cnt; i++) {
        size_t rec = 0x24 + (size_t)i * 72;
        unsigned off, size, ncomp, c;
        struct rd r;
        const char* action;
        int best = 0, seen = 0;

        if (rec + 72 > (size_t)sz) break;
        memcpy(&off, d + rec + 64, 4);
        memcpy(&size, d + rec + 68, 4);
        if ((size_t)off + size > (size_t)sz || size < 4) continue;
        if (memcmp(d + off, "adjb", 4) != 0) continue;

        r.p = d; r.n = (size_t)off + size; r.o = (size_t)off + 4; r.bad = 0;
        rd_str(&r);                          /* category */
        action = rd_str(&r);
        rd_str(&r);                          /* motion   */
        r.o += 16;                           /* f32 u32 u32 f32 */
        rd_str(&r);                          /* tag      */
        ncomp = rd_u32(&r);
        if (r.bad || strcmp(action, PL033_ACTION) != 0) continue;

        for (c = 0; c < ncomp && !r.bad; c++) {
            const char* name;
            unsigned np, k;
            int soul = 0, charge = 0, bomb = 0, cand;

            rd_u32(&r);                      /* uid       */
            name = rd_str(&r);
            rd_str(&r);                      /* condition */
            r.o += 12;                       /* u32, f32 start, f32 end */
            rd_str(&r);                      /* target    */
            np = rd_u32(&r);
            if (np > 4096) { r.bad = 1; break; }
            for (k = 0; k < np && !r.bad; k++) {
                const char* key = rd_str(&r);
                const char* val = rd_str(&r);
                if      (!strcmp(key, "soul_damage"))          soul   = as_int(val);
                else if (!strcmp(key, "charge_soul_damage"))   charge = as_int(val);
                else if (!strcmp(key, "add_bomb_soul_damage")) bomb   = as_int(val);
            }
            /* The resolver's own filter: first letter 'A', contains "Attack". */
            if (name[0] != 'A' || !strstr(name, "Attack")) continue;
            cand = soul + charge;
            if (bomb > cand) cand = bomb;
            if (cand > best) best = cand;
            seen++;
        }
        free(d);
        if (r.bad || !seen) return 0;
        *out = (float)best;
        *records = seen;
        return 1;
    }
    free(d);
    return 0;
}

/* ---- the watcher: the log states what the HUD was told --------------
   The resolver runs many times a second, so the stub only counts; this
   thread samples every 500 ms and writes a line when the count moves,
   at most once every 5 s and at most 40 lines a session. */
static DWORD WINAPI pl033_watch(LPVOID u)
{
    unsigned long long fired = 0;
    DWORD last = 0;
    int lines = 0;
    (void)u;
    while (g_stub && lines < 40) {
        unsigned long long f2 = *(volatile unsigned long long*)(g_stub + D_FIRED);
        DWORD now = GetTickCount();
        if (f2 != fired && (lines == 0 || now - last >= 5000)) {
            unsigned long long seen = *(volatile unsigned long long*)(g_stub + D_SEEN);
            float kon = *(volatile float*)(g_stub + D_KONPAKU);
            float val = *(volatile float*)(g_stub + D_VALUE);
            fired = f2; last = now; lines++;
            log_line("PL033/hud: Stark Awakened on %.1f Konpaku -> Primera, the HUD"
                     " promises %.0f Konpaku (stock hardcode: %.0f). %llu of %llu"
                     " Stark resolutions used the data value.",
                     (double)kon, (double)val + 1.0, (double)PL033_STOCK_VALUE + 1.0,
                     f2, seen);
        }
        Sleep(500);
    }
    return 0;
}

__declspec(dllexport) int BrosPluginInit(const BrosHost* host)
{
    unsigned char* site;
    long long rel;
    float value = 0.0f, thresh = PL033_THRESHOLD;
    int records = 0;
    char path[MAX_PATH * 2];
    DWORD old;

    if (!host || host->abi != BROS_PLUGIN_ABI) return 0;
    if (host->size < (unsigned)sizeof(BrosHost)) return 0;
    g_host = host;
    if (!host->mod || !host->claim || !host->alloc_near) {
        log_line("PL033/hud: host is missing mod/claim/alloc_near -- declining");
        return 0;
    }
    site = host->mod + PL033_RVA_CASE;

    if (memcmp(site, PL033_CASE_SIG, PL033_CASE_LEN) != 0) {
        log_line("PL033/hud: Stark's resolver case at RVA 0x%X is not the expected"
                 " bytes (game updated?) -- NOTHING written, the HUD keeps the"
                 " stock 2.0 for Primera.", PL033_RVA_CASE);
        return 0;
    }
    if (!pl033_primera_from_data(&value, &records, path, sizeof(path))) {
        log_line("PL033/hud: could not read `%s` out of %s -- NOTHING written, the"
                 " HUD keeps the stock 2.0 for Primera.", PL033_ACTION, path);
        return 0;
    }

    /* CLAIM BEFORE YOU WRITE. */
    if (!host->claim(PL033_OWNER, PL033_RVA_CASE, PL033_CASE_LEN,
                     "Stark's case of the HUD Kikon resolver (Primera)")) {
        log_line("PL033/hud: RVA 0x%X is already claimed -- NOTHING written",
                 PL033_RVA_CASE);
        return 0;
    }

    g_stub = (unsigned char*)host->alloc_near(site, STUB_SIZE);
    if (!g_stub) {
        log_line("PL033/hud: no stub page within +/-2GB -- NOTHING written");
        return 0;
    }
    memset(g_stub, 0, STUB_SIZE);
    memcpy(g_stub, PL033_HUD_STUB, sizeof(PL033_HUD_STUB));
    memcpy(g_stub + D_THRESH, &thresh, 4);
    memcpy(g_stub + D_VALUE, &value, 4);

    rel = (long long)(host->mod + PL033_RVA_JOIN) - (long long)(g_stub + STUB_EXIT_REL32 + 4);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("PL033/hud: stub exit out of rel32 range -- NOTHING written");
        g_stub = 0;
        return 0;
    }
    { int r32 = (int)rel; memcpy(g_stub + STUB_EXIT_REL32, &r32, 4); }
    FlushInstructionCache(GetCurrentProcess(), g_stub, STUB_SIZE);

    rel = (long long)g_stub - (long long)(site + 5);
    if (rel > 0x7FFFFFFFLL || rel < -0x80000000LL) {
        log_line("PL033/hud: stub out of rel32 range of the case -- NOTHING written");
        g_stub = 0;
        return 0;
    }
    if (!VirtualProtect(site, 7, PAGE_EXECUTE_READWRITE, &old)) {
        log_line("PL033/hud: VirtualProtect failed at RVA 0x%X -- NOTHING written",
                 PL033_RVA_CASE);
        g_stub = 0;
        return 0;
    }
    site[0] = 0xE9;
    { int r32 = (int)rel; memcpy(site + 1, &r32, 4); }
    site[5] = 0x90; site[6] = 0x90;
    VirtualProtect(site, 7, old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, 7);

    CreateThread(NULL, 0, pl033_watch, NULL, 0, NULL);
    log_line("PL033/hud: ARMED -- Stark Awakened on <= %.0f Konpaku now shows Primera"
             " as the data has it: soul_damage %.0f = %.0f Konpaku, read from %s"
             " (%d Attack record(s)). The exe's hardcode said %.0f. Case at RVA"
             " 0x%X, stub at %p.%s",
             (double)thresh, (double)value, (double)value + 1.0, path, records,
             (double)PL033_STOCK_VALUE + 1.0, PL033_RVA_CASE, (void*)g_stub,
             value == PL033_STOCK_VALUE ? " (same as stock: this data is vanilla"
                                          " Primera, the HUD shows what it always did)" : "");
    return 1;
}
