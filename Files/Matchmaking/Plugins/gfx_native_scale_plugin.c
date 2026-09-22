/* =====================================================================
 *  gfx_native_scale_plugin.c -- render at native resolution.
 *
 *  ONE four-byte operand, in memory only, nothing on disk:
 *  ComputeResolutionScale (exe RVA 0x5E4F10) loads its nominal scale from
 *  .rdata and stores min(nominal, max(2880/W, 1620/H)) to 0x1CEDA68.
 *  The nominal is 1.5f when the Texture Quality byte 0x1CEDA6D is 1 (High)
 *  and 1.0f when it is 0 (Low). This plugin repoints the High load at the
 *  1.0f constant, so High renders at the window's own resolution -- the
 *  resolution Low already renders at. Nothing else changes: textures stay
 *  High, the cap is untouched, no code is moved, no cave is allocated.
 *
 *  WHAT IT IS WORTH (measured on a 3080 at 2560x1440 windowed, 2026-09-22,
 *  on a CLEAN loader build -- the shipped Files/Matchmaking/dinput8.dll is a
 *  debug build with the room-match tracer on, so do not expect these numbers
 *  to reproduce against it; that is a loader question, not a scale question):
 *  battle 55-57 -> 57-60 fps, GPU wait per frame 7-11 ms -> ~0.2 ms.
 *  WHO IT MOVES, from the routine's own arithmetic:
 *      1920x1080 High : 1.5   -> 1.0  (2880x1620 -> 1920x1080; the biggest
 *                                      change, and the one a player can SEE,
 *                                      because stock was supersampling)
 *      2560x1440 High : 1.125 -> 1.0  (the measured case)
 *      3440x1440 High : 1.125 -> 1.0
 *      2880x1620 High : 1.0   -> 1.0  (nothing)
 *      3840x2160 High : 0.75  -> 0.75 (nothing: the cap already binds, 4K
 *                                      renders at 2880x1620 stock as well)
 *      anything Low   : 1.0   -> 1.0  (nothing)
 *
 *  WHY THE CAP'S `jbe` AT 0x5E4F97 IS LEFT ALONE. Turning it into `jmp`
 *  would drop the min() and make every display above 2880x1620 render at
 *  native instead of the stock 0.75 -- a large, silent performance LOSS for
 *  4K players. The separate C-track loader's own switch does flip it because it also
 *  offers 1.25/1.5/2.0, where uncapping is the point. Here it must not.
 *
 *  THE OPT-OUT. An empty file named native_scale_off.txt beside
 *  BLEACH_Rebirth_of_Souls.exe makes this plugin decline before it claims
 *  anything, so a player can go back to the stock render scale without
 *  touching the patch.
 *
 *  HOST CONTRACT. Built against bros_plugin.h (ABI 1). It uses exactly
 *  mod, log and claim, all of which the public Sep-22 master provides at
 *  the same offsets, and it guards every field with BROS_HOST_HAS -- never
 *  with `host->size < sizeof(BrosHost)`, because that master advertises
 *  size 96 while this header is 120 and the plugin would decline for no
 *  reason. It writes nothing before claim() grants the operand, and a
 *  refusal (the C-track master's own GFX switch owns the same site) is a
 *  clean decline, not an error.
 * ===================================================================== */

#include <windows.h>
#include <string.h>
#include "bros_plugin.h"

#ifndef PATCH_BUILD_ID
#define PATCH_BUILD_ID "unstamped-local-build"
#endif

#define NS_OWNER        "gfx_native_scale"
#define NS_OFF_FILE     "native_scale_off.txt"

#define NS_SITE_RVA     0x5E4F77u   /* movss/jmp/movss/movss/comiss/mov byte/jbe */
#define NS_SITE_LEN     34u
#define NS_DISP_OFF     4u          /* the nominal movss's disp32, RVA 0x5E4F7B  */
#define NS_DISP_END     0x5E4F7Fu   /* that movss's end: float = mod + this + disp */
#define NS_JCC_OFF      32u         /* the cap's jbe, RVA 0x5E4F97 -- NOT touched */
#define NS_DISP_STOCK   0x00EDB3BDu /* -> RVA 0x14C033C, 1.5f                     */
#define NS_DISP_NATIVE  0x00EDB385u /* -> RVA 0x14C0304, 1.0f                     */
#define NS_FLOAT_RVA    0x014C0304u /* NS_DISP_END + NS_DISP_NATIVE, spelled out  */
#define NS_FLOAT_ONE    0x3F800000u /* the bits 1.0f must read as                 */

/* ---------------------------------------------------------------------------
 *  THE ONE-BYTE STORE'S OWN PRECONDITION, CHECKED BY THE COMPILER.
 *
 *  Writing a single byte to change a four-byte operand is only correct while
 *  the two disp32s differ in nothing but their low byte. That is true of the
 *  four floats this routine can select -- 1.0 at RVA 0x14C0304, 1.25 at
 *  0x14C032C, 1.5 at 0x14C033C and 2.0 at 0x14C0360, 0x5C apart end to end,
 *  so their operands are 0x00EDB385/3AD/3BD/3E1 and share a high 0x00EDB3 --
 *  but that is a property of these constants, not of the code, and the
 *  obvious next edit to this file is a different nominal (1.25 instead of 1.0,
 *  or a float that moved in a later exe). Note that such an edit is THREE
 *  constants, not one: NS_DISP_NATIVE, NS_FLOAT_RVA and NS_FLOAT_ONE all move
 *  together, and the asserts below refuse an incomplete change -- verified by
 *  compiling a half-done 1.25 edit and watching it fail to build.
 *  A constant whose upper bytes differ would leave
 *  three stale bytes behind and point the movss at arbitrary memory, and the
 *  read-back at the end only downgrades the RETURN VALUE -- by then the write
 *  has happened. So the check has to be before the build, not after the store.
 *
 *  If one of these fires, the change you are making is no longer a one-byte
 *  store: write all four bytes under the existing claim (the claim already
 *  covers the whole operand) and delete the assert that stopped you.
 * ------------------------------------------------------------------------- */
_Static_assert((NS_DISP_STOCK & 0xFFFFFF00u) == (NS_DISP_NATIVE & 0xFFFFFF00u),
               "the stock and target disp32 differ above their low byte -- the "
               "one-byte store at p[NS_DISP_OFF] would leave a garbage operand");
_Static_assert(NS_DISP_STOCK != NS_DISP_NATIVE,
               "stock and target disp32 are the same value -- nothing to patch");
_Static_assert(NS_SITE_RVA + NS_DISP_OFF + 4u == NS_DISP_END,
               "NS_DISP_END is not the end of the disp32 at NS_SITE_RVA + "
               "NS_DISP_OFF, so the rip-relative target would be computed wrong");
_Static_assert(NS_DISP_END + NS_DISP_NATIVE == NS_FLOAT_RVA,
               "the target operand does not resolve to the 1.0f constant's RVA");
_Static_assert(NS_DISP_OFF + 4u <= NS_SITE_LEN && NS_JCC_OFF < NS_SITE_LEN,
               "the disp32 or the cap's jcc lies outside the verified window");

/* The stock 34 bytes, exactly as the shipping exe holds them
   (BLEACH_Rebirth_of_Souls.exe sha256 bfd85d8b..., 28,283,464 B). */
static const unsigned char k_ns_stock[NS_SITE_LEN] = {
    0xF3, 0x0F, 0x10, 0x0D, 0xBD, 0xB3, 0xED, 0x00,  /* movss xmm1,[rip+0xEDB3BD]  1.5f  */
    0xEB, 0x08,                                      /* jmp 0x5E4F89                     */
    0xF3, 0x0F, 0x10, 0x0D, 0x7B, 0xB3, 0xED, 0x00,  /* movss xmm1,[rip+0xEDB37B]  1.0f  */
    0xF3, 0x0F, 0x10, 0x00,                          /* movss xmm0,[rax]  the cap        */
    0x0F, 0x2F, 0xC8,                                /* comiss xmm1,xmm0                 */
    0xC6, 0x05, 0xD5, 0x8A, 0x70, 0x01, 0x01,        /* mov byte [0x1CEDA6C],1           */
    0x76, 0x0D                                       /* jbe 0x5E4FA6 (store the nominal) */
};

/* ---- is the whole site inside this image? ------------------------------- */
static int ns_in_image(const unsigned char* mod, unsigned rva, unsigned len)
{
    const IMAGE_DOS_HEADER* dos = (const IMAGE_DOS_HEADER*)mod;
    const IMAGE_NT_HEADERS64* nt;
    if (!mod || dos->e_magic != IMAGE_DOS_SIGNATURE) return 0;
    nt = (const IMAGE_NT_HEADERS64*)(mod + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) return 0;
    if (nt->OptionalHeader.Magic != IMAGE_NT_OPTIONAL_HDR64_MAGIC) return 0;
    return len <= nt->OptionalHeader.SizeOfImage &&
           rva <= nt->OptionalHeader.SizeOfImage - len;
}

/* ---- the opt-out file, beside the exe ----------------------------------- */
static int ns_opted_out(const unsigned char* mod)
{
    char path[MAX_PATH + 64];
    DWORD n;
    size_t i, cut = 0;
    /* host->mod IS the game module; the header's rule is "never call
       GetModuleHandle", not "never ask Windows about the module you were
       handed". */
    n = GetModuleFileNameA((HMODULE)mod, path, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) return 0;
    for (i = 0; i < n; i++)
        if (path[i] == '\\' || path[i] == '/') cut = i + 1;
    if (cut == 0 || cut + sizeof(NS_OFF_FILE) > sizeof(path)) return 0;
    memcpy(path + cut, NS_OFF_FILE, sizeof(NS_OFF_FILE));
    return GetFileAttributesA(path) != INVALID_FILE_ATTRIBUTES;
}

__declspec(dllexport) const char* BrosPluginId(void) { return PATCH_BUILD_ID; }

__declspec(dllexport) int BrosPluginInit(const BrosHost* host)
{
    unsigned char* mod;
    unsigned char* p;
    unsigned disp, bits;
    unsigned char lo = (unsigned char)(NS_DISP_NATIVE & 0xFFu);
    DWORD old;

    if (!host || host->abi != BROS_PLUGIN_ABI) return 0;
    if (!BROS_HOST_HAS(host, mod) || !BROS_HOST_HAS(host, log) ||
        !BROS_HOST_HAS(host, claim))
        return 0;                       /* nothing to do without these three */

    mod = host->mod;
    if (!ns_in_image(mod, NS_SITE_RVA, NS_SITE_LEN) ||
        !ns_in_image(mod, NS_DISP_END + NS_DISP_NATIVE, 4)) {
        host->log("NATIVE/scale: RVA 0x%X is outside this exe's image -- left alone, "
                  "stock render scale", NS_SITE_RVA);
        return 0;
    }
    p = mod + NS_SITE_RVA;

    if (ns_opted_out(mod)) {
        host->log("NATIVE/scale: %s is present beside the exe -- declined on purpose, "
                  "stock render scale", NS_OFF_FILE);
        return 0;
    }

    memcpy(&disp, p + NS_DISP_OFF, sizeof disp);
    if (disp == NS_DISP_NATIVE) {
        host->log("NATIVE/scale: RVA 0x%X already selects 1.0 (disp32 0x%06X) -- nothing "
                  "to do", NS_SITE_RVA + NS_DISP_OFF, disp);
        return 1;
    }
    /* Every byte but the disp32 must be stock, the cap's jbe included: a jmp
       there means somebody removed the min(), which is a different routine
       from the one this was measured on. */
    if (memcmp(p, k_ns_stock, NS_DISP_OFF) != 0 ||
        memcmp(p + NS_DISP_OFF + 4, k_ns_stock + NS_DISP_OFF + 4,
               NS_SITE_LEN - NS_DISP_OFF - 4) != 0) {
        host->log("NATIVE/scale: the bytes at RVA 0x%X are not this exe's stock "
                  "ComputeResolutionScale (disp32 0x%06X, jcc 0x%02X) -- left alone, "
                  "stock render scale", NS_SITE_RVA, disp, (unsigned)p[NS_JCC_OFF]);
        return 0;
    }
    if (disp != NS_DISP_STOCK) {
        host->log("NATIVE/scale: RVA 0x%X selects disp32 0x%06X, not the stock 0x%06X -- "
                  "somebody else set the render scale, left alone",
                  NS_SITE_RVA + NS_DISP_OFF, disp, NS_DISP_STOCK);
        return 0;
    }
    /* And the constant the new operand points at must really read 1.0f. */
    memcpy(&bits, mod + NS_DISP_END + NS_DISP_NATIVE, sizeof bits);
    if (bits != NS_FLOAT_ONE) {
        host->log("NATIVE/scale: the float at RVA 0x%X reads bits 0x%08X, not 1.0 -- "
                  "left alone, stock render scale",
                  NS_DISP_END + NS_DISP_NATIVE, bits);
        return 0;
    }

    /* Claim the whole operand (4 bytes) even though one byte is written: the
       operand is the unit another patch would collide with. */
    if (!host->claim(NS_OWNER, NS_SITE_RVA + NS_DISP_OFF, 4,
                     "ComputeResolutionScale's nominal render scale: Texture High "
                     "1.5 -> 1.0 (render at native resolution)")) {
        host->log("NATIVE/scale: the claim for RVA 0x%X was refused -- the owner is "
                  "named above, nothing was written",
                  NS_SITE_RVA + NS_DISP_OFF);
        return 0;
    }

    /* The four selectable disp32 values (1.0/1.25/1.5/2.0) differ ONLY in
       their low byte, so this is a single-byte store: it cannot tear, and no
       thread can observe a half-written operand. */
    if (!VirtualProtect(p + NS_DISP_OFF, 4, PAGE_EXECUTE_READWRITE, &old)) {
        host->log("NATIVE/scale: RVA 0x%X could not be unlocked (error %lu) -- left "
                  "alone, stock render scale", NS_SITE_RVA + NS_DISP_OFF,
                  (unsigned long)GetLastError());
        return 0;
    }
    p[NS_DISP_OFF] = lo;
    VirtualProtect(p + NS_DISP_OFF, 4, old, &old);
    FlushInstructionCache(GetCurrentProcess(), p + NS_DISP_OFF, 4);

    memcpy(&disp, p + NS_DISP_OFF, sizeof disp);
    host->log("NATIVE/scale [%s]: RVA 0x%X disp32 0x%06X -> 0x%06X, so "
              "ComputeResolutionScale's nominal is now 1.0 (RVA 0x%X) instead of 1.5 "
              "on Texture Quality High; the cap at 0x5E4F97 is untouched, so a display "
              "above 2880x1620 is unchanged and Texture Quality Low was already 1.0. "
              "Remove it for one run with %s beside the exe.",
              PATCH_BUILD_ID, NS_SITE_RVA + NS_DISP_OFF, NS_DISP_STOCK, disp,
              NS_DISP_END + NS_DISP_NATIVE, NS_OFF_FILE);
    return disp == NS_DISP_NATIVE;
}
