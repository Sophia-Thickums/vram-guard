#!/usr/bin/env python3
"""test_vram_guard.py — the guard's decisions, against inputs whose answers are known.

vram-guard exists to stop a helper process from taking VRAM a game has already claimed.
Its four claims, and how each is checked here with no GPU involved:

  1. RESIDENCY DECIDES — used above the limit is not-safe, below it is safe.
  2. BUSY% DOES NOT DECIDE — a card pegged at 99% busy with little VRAM held is SAFE.
     This is the tool's whole thesis; if it ever starts consulting utilisation, that
     assertion is the one that goes red.
  3. FAIL-SHUT — an unreadable card reports NOT-safe, never safe.
  4. FOREGROUND — an unknown window counts as occupied; a known game class counts as
     occupied; anything else does not.

Run with no arguments. Needs no GPU, no display and no root: the card path is pointed at
a temporary directory and the values are written by the test.

Exit: 0 all checks pass, 1 a check failed.
"""
import importlib.util
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.join(HERE, "vram_guard.py")

spec = importlib.util.spec_from_file_location("vram_guard", MOD)
if spec is None or spec.loader is None:
    sys.exit(f"could not load {MOD}")
vg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vg)

failures = []
checks = 0


def check(name, got, want):
    global checks
    checks += 1
    if got != want:
        failures.append(f"{name}: got {got!r}, want {want!r}")


GB = 1024 ** 3


def fake_card(used_gb=None, busy_percent=None, limit_gb=8):
    """A sysfs-shaped directory holding only what the guard is allowed to read."""
    d = tempfile.mkdtemp(prefix="vramguard-")
    if used_gb is not None:
        with open(os.path.join(d, "mem_info_vram_used"), "w") as fh:
            fh.write(f"{int(used_gb * GB)}\n")
    if busy_percent is not None:
        with open(os.path.join(d, "gpu_busy_percent"), "w") as fh:
            fh.write(f"{busy_percent}\n")
    return d


real_card, real_limit = vg.CARD, vg.VRAM_LIMIT_GB
try:
    # ---------------------------------------------------------------- 1 and 2
    setattr(vg, "VRAM_LIMIT_GB", 8)

    setattr(vg, "CARD", fake_card(used_gb=2.0))
    ok, why = vg.safe_to_allocate()
    check("2 GB used is safe", ok, True)

    setattr(vg, "CARD", fake_card(used_gb=8.0))
    ok, why = vg.safe_to_allocate()
    check("exactly at the limit is NOT safe (>= not >)", ok, False)

    setattr(vg, "CARD", fake_card(used_gb=7.99))
    ok, why = vg.safe_to_allocate()
    check("just under the limit is safe", ok, True)

    # The thesis: a game parked at a menu holds its VRAM at ~0% busy. Residency must rule.
    setattr(vg, "CARD", fake_card(used_gb=2.0, busy_percent=99))
    ok, why = vg.safe_to_allocate()
    check("99% busy but 2 GB held is still SAFE — busy%% must not decide", ok, True)
    check("...and the reason cites residency, not utilisation", "vram" in why, True)

    # ------------------------------------------------------------------ 3
    setattr(vg, "CARD", "/nonexistent/card/path")
    ok, why = vg.safe_to_allocate()
    check("unreadable card is NOT safe", ok, False)
    check("...and says why", "fail-shut" in why or "unreadable" in why, True)

    d = fake_card(used_gb=None)
    setattr(vg, "CARD", d)
    ok, why = vg.safe_to_allocate()
    check("a card directory with no mem_info_vram_used is NOT safe", ok, False)

    # ------------------------------------------------------------------ 4
    classes = ["steam_app", "htgame"]
    check("known game class is occupied",
          vg.decide_foreground("Neverness to Everness", "steam_app", classes)[0], True)
    check("class matching is case-insensitive",
          vg.decide_foreground("x", "Steam_App", classes)[0], True)
    check("a normal window is not occupied",
          vg.decide_foreground("konsole — sophia", "konsole", classes)[0], False)
    check("unknown foreground is occupied (fail-shut)",
          vg.decide_foreground(None, None, classes)[0], True)
    check("a caption with no class still decides",
          vg.decide_foreground("some window", None, classes)[0], False)
    # The shipped default list is what a user actually gets; a few entries must exist.
    check("default class list is not empty", len(vg.GAME_CLASSES_DEFAULT) > 5, True)

    # ------------------------------------------------ the CLI really checks something
    # The kit used to run `vram_guard.py --check`, which is not a command: main() fell
    # through to printing the docstring and exiting 0. Prove the commands exist.
    import subprocess
    for cmd in ("check", "gate"):
        r = subprocess.run([sys.executable, MOD, cmd], capture_output=True, text=True, timeout=30)
        check(f"`{cmd}` runs and exits 0", r.returncode, 0)
        check(f"`{cmd}` prints JSON", r.stdout.strip().startswith("{"), True)

finally:
    setattr(vg, "CARD", real_card)
    setattr(vg, "VRAM_LIMIT_GB", real_limit)

print(f"{checks} checks")
if failures:
    print(f"\nFAIL ({len(failures)})")
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("PASS: residency governs, busy% does not, unreadable fails shut, foreground is honest.")
sys.exit(0)
