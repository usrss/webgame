# Phase 1 Prompt: Core Models and Game Rules

> **How to use:** paste this whole file into your AI coding assistant at the root of the Django project. It is self-contained. Phase 1 has **no UI**. The goal is a fully tested game engine.
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

Build the data models, the game-rule service layer, the admin registration, and a thorough test suite for: **creating fish, feeding, cooldowns, hunger, leveling, and evolution**. No templates, no JavaScript, no public URLs in this phase.

## 2. Tasks

### 2.1 Settings
Add to `settings.py`:

```python
GAME_SETTINGS = {
    "XP_PER_FEED": 10,
    "FEED_COOLDOWN_SECONDS": 300,
    "XP_PER_LEVEL_STEP": 50,
    "MAX_LEVEL": 50,
    "HUNGER_FULL_SECONDS": 8 * 3600,
    "JOIN_CODE_LENGTH": 6,
    "DEFAULT_TANK_CAPACITY": 12,
}
```

### 2.2 Models (`game/models.py`)
- Implement `Tank`, `EvolutionStage`, `Fish` exactly as in the canonical model above.
- Implement `generate_join_code()` using the `secrets` module (never `random`). Alphabet: uppercase letters and digits **excluding look-alikes `0 O 1 I`**. Length from settings.
- Join code must be unique: on the (very unlikely) collision, regenerate in a retry loop (max ~10 tries) rather than failing. Put this in a `Tank.save()` override or a `create_tank` helper; document which.
- Add `__str__` methods and sensible `Meta.ordering`.
- Add model-level validation of `Fish.name` length only (full name validation comes in Phase 2/5).

### 2.3 Data migration for evolution stages
Create a **data migration** that seeds the four `EvolutionStage` rows (see canonical rules). It must be idempotent (`update_or_create`) and reversible.

### 2.4 Services (`game/services.py`)
Implement these with full docstrings and type hints:

```python
class FeedOnCooldown(Exception):
    seconds_remaining: int

@dataclass
class FeedResult:
    fish: Fish
    xp_gained: int
    leveled_up: bool
    levels_gained: int
    evolved: bool
    old_stage: int
    new_stage: int
    cooldown_seconds: int

def xp_to_next_level(level: int) -> int
def stage_for_level(level: int) -> int
def get_hunger(fish: Fish, now=None) -> int           # 0..100, integer
def seconds_until_can_feed(fish: Fish, now=None) -> int  # 0 if can feed now
def feed(fish: Fish, now=None) -> FeedResult
```

Requirements for `feed()`:
- Wrap in `transaction.atomic()` and re-fetch the fish with `select_for_update()` so two simultaneous feeds cannot both succeed inside the cooldown.
- Raise `FeedOnCooldown` (with `seconds_remaining`) if the cooldown has not passed. A never-fed fish can always feed.
- Add `XP_PER_FEED`, then loop: while `xp >= xp_to_next_level(level)` and `level < MAX_LEVEL`: subtract threshold, increment level.
- At `MAX_LEVEL`, clamp XP to 0 (or leave it unchanged) and document the choice.
- Recompute `stage` from the level, using `EvolutionStage` rows (cache nothing in v1, but structure the lookup so it could be cached later).
- Set `last_fed_at = now`, save, and return a populated `FeedResult`.

### 2.5 Admin
Register `Tank`, `Fish`, `EvolutionStage` in `admin.py` with useful `list_display`, `search_fields` (tank name, join code, fish name, owner username), and `list_filter` (stage, level). Make `join_code` read-only in the admin.

## 3. Tests (`game/tests/test_services.py`, `test_models.py`)

Cover at minimum:
- Join code: correct length, only allowed characters, uniqueness, collision retry.
- `xp_to_next_level`: values for levels 1, 2, 10.
- `get_hunger`: 0 right after feeding, ~50 at half the interval, capped at 100, uses `created_at` when never fed.
- `feed`: first feed succeeds; second within cooldown raises `FeedOnCooldown` with correct seconds; after cooldown succeeds.
- Level-up: single level; **multiple levels in one feed** (set up XP so it chains); XP carry-over is correct.
- Evolution: crossing levels 5, 15, 30 sets the right stage and `evolved=True`; non-boundary level-ups have `evolved=False`.
- Max level: no level above `MAX_LEVEL`.
- Unique constraint: a user cannot have two fish in the same tank.
- Data migration seeded exactly four stages.
- A concurrency-style test of the cooldown guard (at minimum: two sequential calls with the same `now` where only the first succeeds).

## 4. Out of scope (do not build yet)
Views, URLs, templates, JavaScript, join/create flows, rate limiting, profanity filtering, sprites.

## 5. Acceptance criteria
- [ ] `python manage.py makemigrations --check` is clean; `python manage.py migrate` works on MySQL.
- [ ] `python manage.py test game` passes.
- [ ] No game numbers are hard-coded outside `GAME_SETTINGS`.
- [ ] `feed()` is the only code path that changes `xp`, `level`, `stage`, or `last_fed_at`.
- [ ] Admin lets me view and edit tanks, fish, and stages.

## 6. Deliverables and response format
1. Full contents of every file created or changed, with paths.
2. The exact PowerShell commands to migrate and run tests.
3. A short list of any assumptions or decisions you made (e.g. max-level XP behavior).
