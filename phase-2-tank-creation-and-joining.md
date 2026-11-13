# Phase 2 Prompt: Tank Creation and Joining

> **How to use:** paste this whole file into your AI coding assistant at the root of the Django project. Requires **Phase 1 to be complete** (models, `services.py`, tests passing).
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

Let a logged-in user **create a tank**, **join a tank by code**, **name their fish**, and **see a list of their tanks**, with correct authorization, safe concurrency, and rate limiting. The tank page itself is only a stub in this phase (the canvas comes in Phase 3).

## 2. Tasks

### 2.1 Validation (`game/validators.py`)
Create `validate_display_name(value)` used for **both tank names and fish names**:
- Strip leading/trailing whitespace and collapse internal runs of spaces.
- Length: fish 2-24 chars, tank 2-40 chars (parametrize).
- Allowed characters: letters, digits, spaces, apostrophe, hyphen, underscore (`^[A-Za-z0-9 _'\-]+$`). Reject everything else (no HTML, emoji, or control chars).
- Structure it as a single function so a **profanity check can be added in Phase 5** without touching callers (leave a clearly marked hook).
- Return the cleaned value or raise `ValidationError`.

### 2.2 Services (add to `game/services.py`)

```python
class JoinError(Exception): ...          # base
class InvalidJoinCode(JoinError): ...
class TankFull(JoinError): ...
class AlreadyInTank(JoinError): ...

def create_tank(owner, tank_name: str, fish_name: str) -> tuple[Tank, Fish]
def join_tank(user, code: str, fish_name: str) -> tuple[Tank, Fish]
def get_membership(user, tank_id) -> Fish | None      # None if not a member
```

Requirements:
- `create_tank`: atomic; creates the tank (capacity from settings) **and the owner's fish** (stage 0, level 1).
- `join_tank`:
  - Normalize the code: `.strip().upper()`.
  - Wrap in `transaction.atomic()`; fetch the tank with `select_for_update()`; **count fish inside the lock**; raise `TankFull` if `count >= capacity`; raise `AlreadyInTank` if the user already has a fish there; raise `InvalidJoinCode` if no tank matches.
  - **Use the same generic error message for "invalid code" regardless of reason** at the view layer, so codes cannot be probed for existence beyond success or failure.
- Make sure the lock works on MySQL/InnoDB (it requires being inside a transaction; verify `ATOMIC_REQUESTS` or use `atomic()` explicitly).

### 2.3 Rate limiting
- Limit the **join endpoint to 10 attempts per minute per user** (count failures and successes).
- Implement as a small reusable decorator in `game/ratelimit.py` using Django's **cache framework** (key like `rl:join:{user_id}`; atomic `cache.add` + `cache.incr`). No new dependency.
- Return HTTP 429 with a friendly message and a `Retry-After` header.
- Leave a comment noting that production needs a **shared cache** (not the default per-process `LocMemCache`); Phase 6 handles this.

### 2.4 Forms, views, URLs, templates
URLs (namespaced `game:`):
| URL | Method | Purpose |
|---|---|---|
| `/tanks/` | GET | "My tanks" list |
| `/tanks/create/` | GET, POST | Create tank form (tank name + fish name) |
| `/tanks/join/` | GET, POST | Join form (code + fish name), rate limited |
| `/tanks/<int:tank_id>/` | GET | Tank page **stub** (membership required) |

- All views `@login_required`.
- Tank page: if the user is not a member, return **404** (don't reveal existence). Show tank name, the join code **only to the owner**, and a list of fish names/levels. Add a placeholder `<div>` where the canvas will go in Phase 3.
- Templates extend `base.html`, use the pixel UI classes (square borders, hard shadows, pixel font). Show form errors clearly.
- "My tanks" list shows tank name, member count / capacity, my fish name and level, and a link in. Include "Create tank" and "Join tank" buttons.
- Use `POST` + redirect after success (PRG pattern). Never put the join code in a GET query string.

### 2.5 Tests
- Create tank: tank + owner fish created, code valid, owner is a member.
- Join: success; wrong code; lowercase/space-padded code works; already in tank; **tank full**; invalid fish name.
- Capacity race: test the logic that the count is evaluated inside the lock (at minimum a test that fills to capacity and rejects the next join; add a `TransactionTestCase` with threads if feasible on MySQL).
- Authorization: anonymous -> redirect to login; non-member -> 404 on tank page; owner sees code, non-owner member does not.
- Rate limit: 11th attempt in a minute returns 429; counter resets after the window (clear cache between tests).
- Validators: accepts normal names, rejects HTML (`<script>`), emoji, too long, too short, only spaces.

## 3. Out of scope
Canvas/JS, state and feed endpoints, evolution visuals, owner tools (kick/regenerate/delete), profanity filtering, sprites, production settings.

## 4. Acceptance criteria
- [ ] Two accounts can share a tank: A creates, B joins with the code.
- [ ] A third user hitting `/tanks/<id>/` gets 404.
- [ ] Joining a full tank fails cleanly with a friendly message.
- [ ] More than 10 join attempts per minute gets 429.
- [ ] Names containing `<`, `>` or emoji are rejected.
- [ ] `python manage.py test game` passes.

## 5. Deliverables and response format
1. Full contents of all new or changed files with paths.
2. PowerShell commands to run migrations (if any) and tests.
3. A short "decisions and assumptions" list, plus anything you noticed that Phase 3 should know.
