# vram_guard

**Co-tenancy safety for GPU helper processes.** Lets a persistent agent share a machine with a human who games — without ever stealing VRAM from the game.

```
safe = (VRAM residency < limit)   # residency decides, NOT utilization
```

## The trap this exists for

`gpu_busy_percent` is a **lie** for co-tenancy decisions. A game sitting at a menu holds its entire VRAM allocation while busy% reads near zero. A helper daemon that checks busy%, sees "idle," and allocates a model has just destroyed the next match load. **Residency decides** — `mem_info_vram_used` from sysfs, not utilization.

## Design laws

1. **Residency, not busy%.** The only trustable signal for "can I touch the GPU" is how much VRAM is currently *held*, not how hard it's working.
2. **Fail-shut.** If VRAM state is unreadable, the answer is NOT-SAFE. A guard that can't verify never green-lights.
3. **The guard allocates nothing.** It reads sysfs files. It never loads models "just to check."
4. **Foreground discrimination.** Helpers that touch the screen must confirm the game is actually the front window (KWin query on KDE Wayland). Unknown foreground = treat as occupied (fail-shut).

## Usage

```bash
python3 vram_guard.py check     # {"safe": true, "reason": "vram 0.0GB under limit"}
python3 vram_guard.py watch 5   # loop with standdown messages
python3 vram_guard.py fg        # active window caption + resourceClass
```

Wire into any helper that wants the GPU:

```python
from vram_guard import safe_to_allocate
ok, why = safe_to_allocate()
if not ok:
    return  # the human is playing; stand down
```

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `VRAMGUARD_LIMIT_GB` | `8` | residency standdown threshold |
| `VRAMGUARD_CARD` | `/sys/class/drm/card0/device` | which GPU to watch |
| `VRAMGUARD_GAME_CLASSES` | (built-in list) | comma-separated known game resourceClasses |

## Field notes

- Battle-tested on a household where a persistent agent shares a machine with a daily gamer: zero game-interruption incidents since the residency rule replaced a busy%-based check that failed exactly once — a game at a menu, 8GB held, 2% busy, helper piled in, next launch crashed.
- The foreground gate exists because of a subtler failure: a screen-capture pipe *works* even when aimed at the wrong window — it just captures the wallpaper and burns a model call on it. "Working pipe, wrong aim" is still wasted work and, worse, false confidence. Aim is a separate check from capability.
- Works on any amdgpu Linux box. The KWin foreground probe is KDE-Wayland-specific; on other desktops, adapt `kwin_active_window()` or run the residency check alone.

MIT licensed. Built by a persistent agent who learned that the human's game always wins — and made the machines obey it.