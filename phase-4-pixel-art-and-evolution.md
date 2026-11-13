# Phase 4 Prompt: Real Pixel Art and Evolution

> **How to use:** paste this whole file into your AI coding assistant at the root of the Django project. Requires **Phases 1-3 complete** (working shared tank with placeholder rectangles). If you don't have art yet, this prompt includes a **placeholder sprite-sheet generator** so you can build and test the whole pipeline first and swap in real art later.
---

## 0. Project context (shared across all phases)

You are helping build **a pixel-art aquarium web game**.

**Concept**
- A player creates a **tank** and gets a 6-character **join code**. Other players join the tank with that code.
- Every player has **one fish per tank**. They name it, **feed** it, and it **levels up** and **evolves** into new forms at level thresholds.
- Everyone in a tank sees everyone else's fish swimming in a shared, pixel-art tank view.

**Stack (already decided, do not change)**
- **Backend:** Django (+ plain Django views returning JSON where needed; DRF is not required). Auth uses Django's built-in user model.
- **Database:** MySQL (InnoDB, `utf8mb4`).
- **Frontend:** Django templates + **vanilla JavaScript + HTML Canvas 2D**. No React/Vue/Phaser.
- **Shared tank updates:** **polling** (every ~7 s). No WebSockets/Channels in v1.
- **Look:** everything is pixelated. Base canvas **320x180** internal resolution, displayed at an **integer multiple** (3x = 960x540) with `image-rendering: pixelated` and `ctx.imageSmoothingEnabled = false`. Pixel font (*Press Start 2P* or *Pixelify Sans*), one limited palette (16-32 colors), CSS UI with square corners and hard shadows, no gradients.
- **Dev environment:** Windows, MySQL, a `.venv` Python virtual environment. Give commands that work in **PowerShell** (e.g. `.\.venv\Scripts\Activate.ps1`, `python manage.py ...`).

**Assumptions about the existing project (Phase 0 is already done)**
- A Django project exists with an app named **`game`**, MySQL configured, static files configured, user signup/login/logout working, and a `base.html` template that loads the pixel font and palette CSS variables. If any of this is missing, create the minimum needed and say so.

**Engineering conventions**
- **Game rules live in `game/services.py`**, not in views or models' `save()`. Views are thin: parse input, call a service, return a response.
- **Tunable numbers live in settings** under a single `GAME_SETTINGS` dict, never as magic numbers in code.
- **Every tank view and endpoint must check that `request.user` is a member of the tank** (owns a fish in it). Return 403 (or 404) otherwise. Never trust IDs from the client for authorization.
- Pass `now` into service functions as an optional argument (`now=None` -> `timezone.now()`) so time-based logic is testable without extra libraries.
- Write tests with Django's `TestCase`. Prefer small, focused tests.
- Don't add dependencies unless the prompt says so. If you think one is justified, say why before adding it.

**Canonical data model** (keep names and fields consistent across phases)

```python
class Tank(models.Model):
    name        = models.CharField(max_length=40)
    owner       = models.ForeignKey(User, on_delete=models.CASCADE, related_name="owned_tanks")
    join_code   = models.CharField(max_length=6, unique=True, default=generate_join_code)
    capacity    = models.PositiveSmallIntegerField(default=12)
    created_at  = models.DateTimeField(auto_now_add=True)

class EvolutionStage(models.Model):
    stage_number = models.PositiveSmallIntegerField(unique=True)   # 0, 1, 2, 3
    name         = models.CharField(max_length=30)                 # Fry, Juvenile, Adult, Elder
    min_level    = models.PositiveSmallIntegerField()              # 1, 5, 15, 30
    sprite_key   = models.CharField(max_length=30)                 # row key in the sprite sheet

class Fish(models.Model):
    owner        = models.ForeignKey(User, on_delete=models.CASCADE, related_name="fish")
    tank         = models.ForeignKey(Tank, on_delete=models.CASCADE, related_name="fish")
    name         = models.CharField(max_length=24)
    xp           = models.PositiveIntegerField(default=0)          # progress within current level
    level        = models.PositiveSmallIntegerField(default=1)
    stage        = models.PositiveSmallIntegerField(default=0)     # stage_number
    last_fed_at  = models.DateTimeField(null=True, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["owner", "tank"], name="one_fish_per_user_per_tank")]
```

**Canonical game rules** (defaults; all configurable via `GAME_SETTINGS`)
- `XP_PER_FEED = 10`
- `FEED_COOLDOWN_SECONDS = 300`
- `XP_PER_LEVEL_STEP = 50` -> XP needed to go from level *n* to *n+1* is `50 * n`
- `MAX_LEVEL = 50`
- `HUNGER_FULL_SECONDS = 28800` (8 h). Hunger is **derived**, never stored: `0` right after feeding, rising linearly to `100` after this many seconds. Use `last_fed_at`, or `created_at` if never fed.
- Level-ups can chain in one feed (loop until XP < threshold or max level). At max level, XP stops accumulating.
- Stage = the `EvolutionStage` with the highest `min_level <= fish.level`.
- Seed stages: `0 Fry (L1)`, `1 Juvenile (L5)`, `2 Adult (L15)`, `3 Elder (L30)`.

---

## 1. Objective

Replace placeholder rectangles with a **sprite-sheet pipeline**, animate fish, add a **visible evolution moment**, and add layered **background decoration**, all while keeping a strict, consistent pixel look.

## 2. Art specification (fixed. Do not deviate)

- **Base canvas:** 320x180. **One cell size for all fish: 32x32 px.**
- **Sprite sheet:** one PNG per species at `static/game/sprites/fish_<species>.png`. v1 ships a single species: `fish_goldie.png`.
  - **Rows = evolution stages** (row 0 = stage 0 Fry ... row 3 = stage 3 Elder).
  - **Columns = animation frames** (4 frames: swim cycle). Sheet size = **128x128**.
  - Fish face **right** in the sheet; the code flips horizontally for left-facing (no left-facing art).
  - Early stages are drawn **smaller within the 32x32 cell** (Fry about 10px wide, Elder about 28px), anchored at the cell's center.
  - Transparent PNG, no anti-aliasing, no semi-transparent pixels.
- **Palette:** one shared palette of **16-32 colors** stored in `static/game/palette.json` and mirrored as CSS variables. All sprites, background, and UI use only these colors. (Suggest a palette source, e.g. lospec.com, in your notes.)
- **Background pieces** (separate small PNGs or one atlas): sand tile, 2-3 plant sprites, rock, bubble (3 frames), light-ray/wave pattern for the surface.

## 3. Tasks

### 3.1 Placeholder generator (so work isn't blocked on art)
Create `tools/make_placeholder_sheet.py` (Pillow; add to dev requirements only) that generates a valid `fish_goldie.png` (128x128, 4x4 cells) with procedurally drawn fish per stage and a simple 4-frame tail wiggle, using only palette colors. Also generate placeholder background pieces. Document how to replace them with hand-drawn art (**Aseprite** or **Piskel** export as PNG sprite sheet, same layout).

### 3.2 Sprite loading (`static/game/js/sprites.js`)
- Preload all images before starting the loop; show a pixel-style "loading" text on the canvas until ready; handle load failure with a visible error and fall back to the Phase 3 rectangles.
- A `drawFish(ctx, sheet, stage, frame, x, y, facing)` helper using `ctx.drawImage(sheet, frame*32, stage*32, 32, 32, ...)`.
- For `facing = left`, flip using `ctx.save(); ctx.translate(...); ctx.scale(-1, 1); ...; ctx.restore()` with **integer** coordinates.
- Frame timing: advance the swim frame about **6-8 times per second**, with a per-fish random phase offset so fish aren't synchronized.

### 3.3 Data wiring
- State endpoint already returns `stage`. Add `sprite_key` per fish (from `EvolutionStage`) so the client doesn't hard-code mapping. Update the Phase 3 endpoint tests.
- Define a small client constant mapping `sprite_key` -> (sheet file, row). Keep it in one place so adding species later is a one-line change.

### 3.4 Evolution moment
Triggered when:
- **my** feed response has `evolved: true`, **or**
- on a poll, any fish's `stage` is higher than the client's remembered stage (so I see **other players'** fish evolve too, without double-firing for my own).

Effect (all in-canvas, pixel style, about 1.5 s total):
1. Fish freezes and flashes white (alternate a white-silhouette draw and normal, 4-6 flashes). Create the white silhouette by drawing the sprite to an offscreen canvas and using `globalCompositeOperation = "source-in"` with a white fill; **cache it per stage**.
2. A burst of 12-20 square pixel particles (1-2 px, palette colors) with stepped motion, short life, gravity-up.
3. Swap to the new stage sprite at the midpoint of the flash.
4. A toast and a floating text above the fish: `"<name> evolved into <stage name>!"`.
Respect `prefers-reduced-motion`: replace flashing with a single brief highlight and skip particles.

**Level-up** (non-evolving): smaller effect: 6-8 particles and a `+LV` floating text.

### 3.5 Background and ambience
- Layered draw order (back to front): water bands (flat, 2-3 tones), faint light rays, back plants, fish, front plants, sand strip, bubbles. Keep **fish between the plant layers** for depth.
- Bubbles: spawn at random x near the bottom, rise at a stepped speed with a slight horizontal wobble, 3-frame animation, remove at the surface. Cap at ~12 live bubbles.
- Plants sway by swapping between 2 frames every ~600 ms (or an integer-pixel offset).
- Fish swim area is bounded to the water region (above the sand strip); labels must stay on-canvas near edges.
- **Performance:** render at a steady frame rate with ~12 fish; use no per-frame allocations in hot paths (reuse particle arrays); pre-render the static background to an offscreen canvas and redraw only the animated pieces.

### 3.6 Size/readability rules
- Labels: draw a 1px dark outline (draw text offset in 4 directions in a dark palette color, then the light text on top) so names are readable on any background.
- Selected/own fish: keep the 1px outline highlight, drawn via the cached silhouette technique rather than a rectangle.

## 4. Tests
Django: endpoint tests updated for `sprite_key`.
JS: no framework required. Provide a **manual QA checklist** in your response:
- [ ] Sheet loads; each stage shows the right row.
- [ ] Left/right flipping is crisp and pixel-aligned.
- [ ] Forcing a stage change via the admin makes the fish evolve on other players' screens within one poll, and it plays **once**.
- [ ] Evolution doesn't replay on every poll or page reload.
- [ ] `prefers-reduced-motion` disables flashing and particles.
- [ ] Missing/broken sprite file shows a visible fallback, not a blank canvas.

## 5. Out of scope
Multiple species selection UI, owner tools, profanity filter, WebSockets, audio, production hardening.

## 6. Acceptance criteria
- [ ] With placeholder art generated by the script, the whole game looks coherent and pixel-perfect at 2x and 3x.
- [ ] Replacing `fish_goldie.png` with a hand-drawn sheet in the same layout requires **no code changes**.
- [ ] A fish visibly changes form at levels 5, 15, 30, with the effect described.
- [ ] No sub-pixel/blurry drawing anywhere.
- [ ] `python manage.py test game` passes.

## 7. Deliverables and response format
1. Full contents of all new or changed files, with paths, and the generated placeholder assets (or the exact command to generate them).
2. A short **art guide** (`docs/art-guide.md`): cell size, layout, palette rules, export steps for Aseprite and Piskel.
3. Assumptions and known limitations.
