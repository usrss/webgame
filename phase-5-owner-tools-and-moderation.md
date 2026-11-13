# Phase 5 Prompt: Owner Tools and Moderation

> **How to use:** paste this whole file into your AI coding assistant at the root of the Django project. Requires **Phases 1-4 complete**.
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

Give tank owners the tools to manage their tank, let players leave, add a profanity-aware name filter, add a simple report system, and make the Django admin a usable moderation console. Because players set their own names in a shared space, this is mandatory before any public release.

## 2. Tasks

### 2.1 New model additions
```python
class TankBan(models.Model):
    tank       = models.ForeignKey(Tank, on_delete=models.CASCADE, related_name="bans")
    user       = models.ForeignKey(User, on_delete=models.CASCADE)
    banned_by  = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["tank", "user"], name="one_ban_per_user_per_tank")]

class FishReport(models.Model):
    fish        = models.ForeignKey(Fish, on_delete=models.CASCADE, related_name="reports")
    reporter    = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    reason      = models.CharField(max_length=20, choices=[("name", "Offensive name"), ("other", "Other")])
    note        = models.CharField(max_length=200, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    resolved    = models.BooleanField(default=False)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["fish", "reporter"], name="one_report_per_user_per_fish")]
```
Add a migration. Update `join_tank` to raise a new `Banned` error (shown to the user with the **same generic message as an invalid code** so bans aren't revealed).

### 2.2 Owner services (`game/services.py`)
All take the acting user and **verify `tank.owner == acting_user`** inside the service (raise `PermissionDenied` otherwise), not only in the view.

| Function | Behavior |
|---|---|
| `regenerate_join_code(tank, actor)` | New unique code; old code immediately invalid. Atomic. |
| `kick_player(tank, actor, fish_id)` | Delete that fish and **create a `TankBan`**. Owner cannot kick themselves. |
| `unban_player(tank, actor, user_id)` | Remove the ban. |
| `rename_fish(tank, actor, fish_id, new_name)` | Owner can rename **any** fish in their tank (moderation). Runs the full name validator. |
| `delete_tank(tank, actor)` | Deletes the tank and cascades fish. Requires the client to send the exact tank name as confirmation (checked in the service). |
| `leave_tank(user, tank)` | A non-owner deletes their own fish and leaves. The **owner cannot leave**; they must delete the tank (transfer of ownership is out of scope). |
| `rename_own_fish(user, tank, new_name)` | Players can rename their own fish, **limited to once per 24 hours** (add `renamed_at` to `Fish`, update migration, configurable in `GAME_SETTINGS`). |

### 2.3 Profanity and name filter (`game/validators.py`)
Fill in the hook left in Phase 2:
- Normalize before checking: lowercase, strip spaces/punctuation, map common **leetspeak** substitutions (`0->o, 1->i/l, 3->e, 4->a, 5->s, 7->t, @->a, $->s`), collapse repeated letters.
- Check against a blocklist. Choose and justify **one**: (a) the `better-profanity` package (add to requirements), or (b) a small project-owned list in `game/data/blocked_words.txt` that is easy to extend. Prefer (b) if you can explain the tradeoff; mention the **Scunthorpe problem** (innocent words containing blocked substrings) and how your approach limits false positives (e.g., whole-token matching on the raw name, substring matching only for a short list of severe terms).
- Return a **generic** error ("That name isn't allowed") without revealing which word matched.
- Apply the filter to **tank names, fish names, renames**.
- Do **not** include actual offensive words in committed code comments or tests: use obviously fake placeholder tokens (e.g. `badword1`) and a test-only blocklist override.

### 2.4 Endpoints and UI
All POST endpoints are CSRF-protected, membership-checked, and (for owner actions) owner-checked; return 403 for non-owners and 404 for non-members.

| URL | Method | Who | Purpose |
|---|---|---|---|
| `/tanks/<id>/settings/` | GET | owner | Owner panel |
| `/tanks/<id>/regenerate-code/` | POST | owner | New code |
| `/tanks/<id>/kick/<fish_id>/` | POST | owner | Kick + ban |
| `/tanks/<id>/unban/<user_id>/` | POST | owner | Unban |
| `/tanks/<id>/rename/<fish_id>/` | POST | owner | Rename any fish |
| `/tanks/<id>/delete/` | POST | owner | Delete (name confirmation) |
| `/tanks/<id>/leave/` | POST | member (non-owner) | Leave |
| `/tanks/<id>/rename-me/` | POST | member | Rename own fish (24h limit) |
| `/tanks/<id>/report/<fish_id>/` | POST | member | Report a fish (cannot report own fish) |

- **Owner panel page:** current join code with a "Copy" button (JS clipboard, with fallback), regenerate button (confirm dialog styled in pixel UI), member list with Kick and Rename actions, banned list with Unban, and a clearly separated "Danger zone" with Delete (requires typing the tank name).
- Members see a **Report** button next to other members' names and a **Leave tank** button; owners do not see Leave.
- All confirmations use a pixel-styled modal (or `<dialog>`), not the browser's `confirm()`.
- On the tank view, kicked users hit 404 on the state endpoint; Phase 3's JS already shows the "removed from tank" message. Verify this works.
- Rate limit **report** (e.g. 10/hour per user) and **rename-me** using the Phase 2 limiter.

### 2.5 Django admin as moderation console
- `FishAdmin`: list name, owner, tank, level, stage, report count (annotated); search by name/owner; filter by "has unresolved reports"; **actions**: "Reset name to `Fish #<id>`", "Delete selected fish".
- `FishReportAdmin`: list filters for `resolved`, action "Mark resolved".
- `TankAdmin`: show member count; action "Regenerate join code".
- `TankBanAdmin`: basic list.
- Everything read-only where editing would break invariants (e.g. `join_code`, `created_at`).

### 2.6 Tests
- Each owner action: owner succeeds; **non-owner member gets 403**; non-member gets 404; anonymous redirects.
- Regenerate: old code fails, new code works, other tanks' codes unaffected.
- Kick: fish removed, ban created, banned user cannot rejoin with a valid code (and sees the generic invalid-code message); unban allows rejoin; owner can't kick self.
- Leave: member leaves; owner cannot leave.
- Delete: wrong confirmation name rejected; correct one cascades fish and bans.
- Rename: validator enforced; own-rename 24h limit enforced and expires (pass `now`).
- Report: one per user per fish; can't report own fish; admin action resolves.
- Profanity: leetspeak/spacing variants of the **test-only** blocked token are caught; a legitimate name containing a harmless substring is allowed; error message does not echo the matched word.

## 3. Out of scope
Ownership transfer, appeals, automated moderation, email notifications, audit-log UI (a simple `logging` call per owner action is enough), production hardening.

## 4. Acceptance criteria
- [ ] An owner can regenerate the code, kick, ban, unban, rename, and delete from the UI.
- [ ] A kicked player is removed from the tank view within one poll and cannot rejoin.
- [ ] Offensive and leetspeak-obfuscated names are rejected everywhere names are set.
- [ ] Admin lets me find and resolve reports and reset a bad name in two clicks.
- [ ] No owner action works for a non-owner by crafting requests manually.
- [ ] `python manage.py test game` passes.

## 5. Deliverables and response format
1. Full contents of all new or changed files, with paths, plus migrations.
2. A permission matrix table (action x role) as implemented.
3. Assumptions, false-positive/false-negative tradeoffs of the filter, and anything Phase 6 should know.
