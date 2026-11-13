# Phase 3 Prompt: Shared Tank View (Canvas + Polling, Placeholder Art)

> **How to use:** paste this whole file into your AI coding assistant at the root of the Django project. Requires **Phases 1 and 2 complete**. This phase uses **placeholder rectangles** instead of real art on purpose: prove the multiplayer loop first.
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

Build the live tank page: a **pixel-scaled canvas** showing every member's fish swimming, a **state endpoint** polled by the browser, and a **feed button** wired to the server-side `feed()` service. Two browsers on two accounts must see each other's fish and updates.

## 2. Tasks

### 2.1 Endpoints (all `login_required`, membership required, 404 for non-members)

**`GET /tanks/<id>/state/`** returns JSON:

```json
{
  "tank": {"id": 3, "name": "Reef Squad", "capacity": 12},
  "me": {"fish_id": 17},
  "server_time": "2026-11-13T09:15:02Z",
  "fish": [
    {
      "id": 17, "name": "Bubbles", "owner": "bradi",
      "level": 6, "stage": 1, "xp": 20, "xp_needed": 300,
      "hunger": 42,
      "can_feed": true, "cooldown_remaining": 0
    }
  ]
}
```
- Compute `hunger`, `can_feed`, and `cooldown_remaining` with the Phase 1 services (don't duplicate logic).
- Use `select_related("owner")` to avoid N+1 queries. Add a test asserting a small, constant query count.
- Send `Cache-Control: no-store`.

**`POST /tanks/<id>/feed/`** feeds **the requesting user's own fish only** (look it up from `request.user` + tank; never accept a fish id from the client).
- Success -> 200 with the `FeedResult` as JSON (`xp_gained`, `leveled_up`, `levels_gained`, `evolved`, `old_stage`, `new_stage`, plus the updated fish state).
- Cooldown -> **429** with `{"error": "cooldown", "seconds_remaining": N}`.
- Must be CSRF-protected (client sends `X-CSRFToken` from the cookie or a template-provided value).

### 2.2 Page and template
- Replace the Phase 2 stub with the real tank page.
- Canvas element: `width="320" height="180"`, CSS-scaled to an **integer multiple** (3x on large screens; 2x on narrow screens via a media query; never fractional).
- Below or beside the canvas, a pixel-style **panel for my fish**: name, level, XP bar (a segmented CSS bar, not a gradient), hunger bar, **Feed** button with a visible countdown while on cooldown.
- A small member list (fish name + level) as plain HTML.
- Pass endpoint URLs and the tank id to JS via `data-` attributes on the canvas or a `json_script` block (no inline JS with template variables).

### 2.3 JavaScript (static files, no build step)
Structure as small ES modules under `static/game/js/`:

| File | Responsibility |
|---|---|
| `tank.js` | entry point; wires everything, owns the main loop |
| `api.js` | `fetchState()`, `feed()`, CSRF handling, error mapping |
| `fishSprite.js` | per-fish client state and drawing (placeholder rectangles for now) |
| `ui.js` | updates the HTML panel, countdown, toasts |

Requirements:
- `ctx.imageSmoothingEnabled = false`; all drawing in the 320x180 coordinate space; positions rounded to whole pixels before drawing.
- **Placeholder fish:** a filled rectangle with a small eye pixel and tail, **size and color by stage** (stage 0 = 8x5, 1 = 12x7, 2 = 16x9, 3 = 20x11; pick 4 palette colors). Highlight *my* fish with a 1px outline.
- **Swim logic (client-side, cosmetic only):** each fish picks a random target in the water area, moves toward it at a slow speed, flips direction (`facing`) when the target is on the other side, then waits briefly and picks a new target. Use a **seeded PRNG keyed by fish id** for the initial position so fish don't all spawn at the same point. Keep movement stepped (update ~8 times per second) for the pixel feel; render with `requestAnimationFrame`.
- **Name labels:** draw above each fish using the pixel font at a small size on the canvas. Wait for the font before the first draw (`document.fonts.load(...)`), and truncate names to fit.
- **Polling:** fetch state every **7 seconds**; also immediately after a successful feed. **Pause polling when the tab is hidden** (`visibilitychange`) and refresh immediately when it becomes visible again. Back off (e.g. 15 s) after a network error and show a small "reconnecting" indicator.
- **Reconciliation:** keep a `Map<fishId, FishSprite>`. On each poll: create sprites for new fish, **update stats on existing ones without resetting their position**, remove sprites for fish that are gone. If the request returns 404/403 (kicked or tank deleted), show a message and link back to "My tanks".
- **Feed button:** disabled while on cooldown or in flight (prevent double-clicks); on success show a toast (`+10 XP`, `Level up!`, `Evolved!` as applicable); on 429 sync the countdown from `seconds_remaining`. The countdown should tick locally between polls using `cooldown_remaining` + `server_time` to avoid drift.
- **Safety:** render names with `textContent` (HTML panel) or canvas `fillText` only. Never use `innerHTML` with server-provided strings.

### 2.4 Styling
Pixel UI only: pixel font, square corners, 2-4px hard borders and shadows, palette variables from `base.html`. Simple water background drawn on the canvas (flat bands of 2-3 blues, no gradient) and a sand strip along the bottom, drawn with rectangles.

### 2.5 Tests (Django)
- State endpoint: member gets 200 with correct schema and values; non-member gets 404; anonymous redirects to login; query count is constant for 1 vs 10 fish.
- Feed endpoint: success path returns correct JSON and updates the DB; second call within cooldown returns 429 with `seconds_remaining`; a user cannot feed another user's fish (no way to even specify one); CSRF required.
- A kicked/non-member user posting to feed gets 404.

## 3. Manual test script (include in your response)
1. Run the server; create two accounts in two different browsers (or one normal + one private window).
2. A creates a tank; B joins with the code.
3. Confirm both see two fish. Feed as A; B's view shows A's new XP within one poll.
4. Hide B's tab for 30 s, reshow, and confirm it refreshes immediately.
5. Stop the server, watch the "reconnecting" indicator, restart, and confirm recovery.

## 4. Out of scope
Real sprites and sprite sheets, evolution animation/particles, bubbles/plants, owner tools, WebSockets, production hardening.

## 5. Acceptance criteria
- [ ] Two browsers on different accounts see each other's fish and each other's feed results within ~7 s.
- [ ] Pixels are crisp at 2x and 3x; no blurry scaling; sprite positions are integers.
- [ ] No fractional CSS scaling of the canvas at any viewport width.
- [ ] Feed is impossible to spam (server enforces cooldown; UI also disables).
- [ ] Hidden tabs stop polling.
- [ ] `python manage.py test game` passes.

## 6. Deliverables and response format
1. Full contents of every new or changed file (Python, templates, JS, CSS) with paths.
2. The manual test results you expect for each step above.
3. Assumptions and anything Phase 4 (real art) must know about sprite sizes or drawing order.
