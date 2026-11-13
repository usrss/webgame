# Phase 6 Prompt: Hardening and Deployment

> **How to use:** paste this whole file into your AI coding assistant at the root of the Django project. Requires **Phases 1-5 complete**. Goal: make the game safe and reliable enough to put in front of real players.
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

Prepare the project for production: split and secure settings, add endpoint throttling backed by a **shared cache**, run a security review specific to this game, set up logging and backups, produce a deployment guide, and define a real-user test plan. Do not add features.

## 2. Tasks

### 2.1 Settings split and secrets
- Convert to `settings/base.py`, `settings/dev.py`, `settings/prod.py` (or an equivalent env-driven approach). Keep Windows local development working (`DJANGO_SETTINGS_MODULE` default to dev).
- Read **all secrets and environment-specific values from environment variables**: `SECRET_KEY`, DB credentials, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, cache URL. Fail loudly at startup in prod if a required variable is missing. Provide `.env.example` (no real values) and make sure `.env` is in `.gitignore`.
- Production flags: `DEBUG=False`, `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_HSTS_SECONDS` (start small, e.g. 3600, with a note on raising it), `SECURE_CONTENT_TYPE_NOSNIFF`, `X_FRAME_OPTIONS="DENY"`, `SECURE_REFERRER_POLICY`, `SESSION_COOKIE_HTTPONLY`, `SECURE_PROXY_SSL_HEADER` (only if behind a proxy; explain).
- MySQL: `utf8mb4`, `CONN_MAX_AGE` (e.g. 60), `init_command` for strict mode, and confirm transaction isolation works with the `select_for_update()` join logic.
- `python manage.py check --deploy` must report **no warnings** (or each remaining one is explained).

### 2.2 Shared cache and throttling
- The Phase 2 rate limiter uses the cache. Configure a **shared** cache for prod (Django database cache table **or** Redis; recommend one with reasoning for a small deployment, and provide setup steps). Per-process `LocMemCache` is not acceptable in prod because limits would multiply by worker count.
- Add throttles (reusing `game/ratelimit.py`):
  | Endpoint | Limit |
  |---|---|
  | login | 10/min per IP |
  | signup | 5/hour per IP |
  | join | 10/min per user (exists) |
  | feed | 12/min per user |
  | state polling | 30/min per user per tank |
  | report / rename-me | existing from Phase 5 |
- Return 429 with `Retry-After`. Make sure the front-end handles 429 on **state polling** by backing off instead of hammering.
- Derive client IP safely (only trust `X-Forwarded-For` when you control the proxy; document it).

### 2.3 Security review (game-specific). Produce a written checklist with results
Verify, and add tests or fixes where needed:
1. **IDOR:** every endpoint that takes `tank_id`, `fish_id`, or `user_id` checks membership/ownership server-side. Write a **parametrized test** that hits every game URL as anonymous, non-member, member, and owner and asserts the expected status for each.
2. **CSRF:** all state-changing endpoints are POST and CSRF-protected; no `@csrf_exempt` anywhere (grep and report).
3. **XSS:** names are rendered via Django auto-escaping, `textContent`, or canvas `fillText` only; no `|safe`, `mark_safe`, or `innerHTML` with user data (grep and report). Add a test that a name like `"><img src=x>` is rejected by the validator **and**, if it somehow existed in the DB, renders escaped.
4. **Join code:** generated with `secrets`; never logged; never in GET query strings or URLs; only shown to the owner.
5. **Enumeration:** invalid/banned/full responses don't leak which condition occurred beyond what's intended.
6. **Race conditions:** concurrent join at full capacity and concurrent feed inside cooldown are both covered by tests (use `TransactionTestCase` + threads on MySQL).
7. **Mass assignment / over-posting:** forms only accept intended fields; the client can never set `xp`, `level`, `stage`, `owner`, or `last_fed_at`.
8. **Dependencies:** list pinned versions in `requirements.txt`; run `pip audit` (or `pip-audit`) and report findings.
9. **Admin:** change the admin URL from `/admin/`, require a strong password, and note enabling 2FA as a follow-up.
10. **Content-Security-Policy:** add a CSP (via `django-csp` or middleware) allowing only self scripts/styles/images/fonts (plus the Google Fonts host **or** self-host the pixel font and remove the external dependency; prefer self-hosting). Report any inline script/style that needed refactoring.

### 2.4 Static files and serving
- Configure `STATIC_ROOT` and `collectstatic`. Serve static files with **WhiteNoise** (add to requirements) with hashed/compressed storage, or explain an alternative.
- Add long-cache headers for hashed assets; make sure sprite sheets get cache-busted when replaced.
- Confirm `image-rendering: pixelated` assets aren't altered by any compression step (lossless PNG only).

### 2.5 Logging, errors, monitoring
- Configure `LOGGING`: console + rotating file in prod, with request errors at `ERROR`, a `game` logger at `INFO` for owner actions (kick, ban, delete, regenerate: include actor and tank id, **never** the join code).
- Custom `404.html` and `500.html` templates in the pixel style.
- Optional: Sentry (or similar) wiring behind an env var, off by default.
- Add a `/healthz/` endpoint (no auth) that checks DB connectivity and returns 200/503.

### 2.6 Database and backups
- Document and script (PowerShell and Linux shell versions) a **daily `mysqldump`** with retention, and a **restore test**. Explain what's lost if you restore from yesterday's dump (fish progress), and decide an acceptable window.
- Add DB indexes where queries need them (e.g. `Fish(tank_id)`, `Tank(join_code)` is already unique); show `EXPLAIN` evidence for the state-endpoint query or justify none are needed.

### 2.7 Deployment guide (`docs/deployment.md`)
Provide a concrete, step-by-step guide for **one** recommended target (a small Linux VPS) and a short comparison table with a PaaS option:
- Python version, venv, `requirements.txt` install, env vars.
- **gunicorn** (note: gunicorn is Linux-only; Windows is for dev only) with a sane worker count and a systemd unit file.
- **Nginx** reverse proxy config with TLS (Let's Encrypt/Certbot), `X-Forwarded-*` headers, gzip, request size limit, and static files handling.
- MySQL production setup (non-root DB user with least privilege, bind to localhost).
- Firewall (only 80/443/SSH), unattended security updates, SSH key auth.
- Migrations on deploy, zero-downtime-ish steps, rollback steps.
- Cost estimate range and when you'd outgrow it (what to change first: DB, cache, then Channels).

### 2.8 Real-user test plan (`docs/test-plan.md`)
For **3-4 real players**, give a script and checklist:
- Roles: owner + 2-3 members on different devices (desktop + phone) and browsers.
- Scenarios: create/join, feed over an hour, a level-up, an **evolution** (use an admin to bump a fish near the threshold to avoid waiting days), kick/rejoin, code regeneration, leave, bad-name attempts, poor network (throttle in DevTools), tab backgrounding on mobile.
- What to record: bugs, confusing UX, perceived balance (is feeding too slow/fast?), and performance (frame rate, battery).
- Exit criteria to call v1 "released".
- A tiny **balance-tuning table** (cooldown, XP per feed, XP curve, hunger interval) with the numbers to change in `GAME_SETTINGS` and what each affects.

## 3. Out of scope
New features, WebSockets/Channels, payments, email verification flow (note it as a recommended follow-up), internationalization.

## 4. Acceptance criteria
- [ ] `python manage.py check --deploy` is clean (or every warning justified).
- [ ] The parametrized permission test passes for every URL x role.
- [ ] Concurrent join and feed tests pass on MySQL.
- [ ] Throttles verified to work across multiple worker processes (shared cache).
- [ ] No `csrf_exempt`, `|safe`, `mark_safe`, or `innerHTML` with user data in the codebase.
- [ ] A fresh server can be stood up from `docs/deployment.md` alone, and a database restore from backup has been demonstrated.
- [ ] `python manage.py test` passes.

## 5. Deliverables and response format
1. Full contents of all new or changed files with paths (settings, nginx/systemd configs, scripts, templates, docs).
2. The completed **security checklist** with a pass/fail/fixed result per item and evidence (grep output or test names).
3. A prioritized list of **known risks and recommended follow-ups** (e.g. email verification, 2FA for admin, CAPTCHA on signup, Channels).
