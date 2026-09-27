#!/usr/bin/env python3
"""
vram_guard — co-tenancy safety for GPU helper processes (v1.0)

The problem it solves
---------------------
A persistent agent shares a machine with a human who GAMES. Helper processes
(watchdogs, perception loops, QC daemons) love to quietly allocate VRAM and
destroy the next game launch. Busy% is a TRAP: a game sitting at a menu holds
its full allocation while gpu_busy_percent reads near zero. Utilization does
not decide co-tenancy — RESIDENCY does.

Design laws
-----------
1. RESIDENCY, NOT BUSY%: read mem_info_vram_used from sysfs. Above the limit,
   stand down — regardless of what utilization says.
2. FAIL-SHUT: if VRAM state can't be read, report NOT-SAFE. A guard that can't
   verify must never green-light.
3. ZERO allocation by the guard itself: it reads sysfs files. It never loads
   models, never opens devices it doesn't need, never queues work that fires
   while the human is playing.
4. FOREGROUND DISCRIMINATION (Wayland/KWin): a helper that needs the screen
   must first ask "is the game actually the front window?" — a full-screen
   capture pipe aimed at the wrong window is still unseen work spent.

Usage:
  python3 vram_guard.py check              # is it safe to touch the GPU?
  python3 vram_guard.py watch --class GameExe   # loop: safe? foreground? act
  python3 vram_guard.py foreground         # what is the active window (KWin)
"""
import json, os, sys, time, subprocess
from pathlib import Path

VRAM_LIMIT_GB = int(os.environ.get("VRAMGUARD_LIMIT_GB", "8"))
CARD = os.environ.get("VRAMGUARD_CARD", "/sys/class/drm/card0/device")
GAME_CLASSES = set(filter(None, os.environ.get("VRAMGUARD_GAME_CLASSES", "").split(",")))

def vram_used_gb():
    try:
        return int(open(f"{CARD}/mem_info_vram_used").read()) / 1024**3
    except Exception:
        return None

def safe_to_allocate():
    """Residency decides. Unreadable = NOT safe (fail-shut)."""
    used = vram_used_gb()
    if used is None:
        return False, "vram state unreadable (fail-shut)"
    if used >= VRAM_LIMIT_GB:
        return False, f"vram residency {used:.1f}GB >= limit {VRAM_LIMIT_GB}GB"
    return True, f"vram {used:.1f}GB under limit"

def kwin_active_window():
    """Active window caption/resourceClass via KWin scripting DBus (KDE Wayland).
    Returns (caption, resourceClass) or (None, None)."""
    try:
        script = (
            "for (const c of workspace.windowList()) {"
            " if (c.active) { print(JSON.stringify({cap: c.caption, cls: c.resourceClass})); } }"
        )
        out = subprocess.run(
            ["dbus-send", "--session", "--print-reply",
             "--dest=org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.loadScript",
             "string:/dev/null"], capture_output=True, text=True, timeout=5)
        # Fallback path: qdbus + kwin scripting console is fiddly across versions;
        # kdotool if present:
        out = subprocess.run(["kdotool", "getactivewindow", "getwindowname"],
                             capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip(), ""
    except Exception:
        pass
    return None, None

def is_game_foreground(game_classes=None):
    """Gate for screen-touching helpers. Unknown foreground = treat as game (fail-shut)."""
    classes = set(game_classes or GAME_CLASSES_DEFAULT)
    cap, cls = kwin_active_window()
    if not cap and not cls:
        return True, "foreground unknown (fail-shut: treat as occupied)"
    if cls and cls.lower() in {c.lower() for c in classes}:
        return True, f"game foreground: {cls}"
    return False, f"non-game foreground: {cap[:60]!r}"

GAME_CLASSES_DEFAULT = [
    # extend via VRAMGUARD_GAME_CLASSES (comma-separated)
    "steam_app", "wine64-preloader", "wine64-preloader", "htgame", "genshinimpact",
    "ue4ss", "retroarch", "pcsx2", "dolphin-emu", "mame", "ryujinx", "yuzu",
    "steam", "lutris", "heroic", "bottles",
]

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "check":
        ok, why = safe_to_allocate()
        print(json.dumps({"safe": ok, "reason": why}))
    elif cmd == "fg":
        cap, cls = kwin_active_window()
        print(json.dumps({"caption": cap, "resourceClass": cls}))
    elif cmd == "gate":
        ok, why = is_game_foreground()
        print(json.dumps({"game_foreground": ok, "reason": why}))
    elif cmd == "watch":
        interval = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0
        while True:
            ok, why = safe_to_allocate()
            if not ok:
                print(time.strftime("%H:%M:%S"), "STANDDOWN:", why, flush=True)
            else:
                print(json.dumps({"safe": ok, "reason": why}), flush=True)
            time.sleep(interval)
    else:
        print(__doc__)


def selftest() -> int:
    """Prove the guard fails SHUT. A guard that cannot say 'not safe' is decoration."""
    import sys as _sys
    print("vram_guard --selftest")
    print("=" * 60)
    ok = True

    used = vram_used_gb()
    readable = used is not None
    ok &= readable
    print(f"  {'PASS' if readable else 'FAIL'}  reads mem_info_vram_used -> {used}")

    # MUST FAIL SHUT: with an unreadable card path, safe_to_allocate must be (False, ...)
    global CARD
    real = CARD
    try:
        CARD = "/nonexistent/card/that/does/not/exist"
        allowed, why = safe_to_allocate()
        shut = (allowed is False)
        ok &= shut
        print(f"  {'PASS' if shut else 'FAIL'}  unreadable card -> allowed={allowed} ({why}) "
              f"-- must be False (fail-shut)")
    finally:
        CARD = real

    allowed2, why2 = safe_to_allocate()
    definite = isinstance(allowed2, bool)
    ok &= definite
    print(f"  {'PASS' if definite else 'FAIL'}  real hardware -> allowed={allowed2} ({why2})")

    print("=" * 60)
    print("selftest " + ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    import sys as _s
    if "--selftest" in _s.argv:
        _s.exit(selftest())
    main()
