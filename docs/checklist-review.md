> **Note:** this self-review was made against commit `7cd0cf7`. Its main findings (AA 5.0 migration dependencies, `migrate aa_ticket zero`, `on_commit` without `robust=True`, committed `dump.rdb`) were fixed afterwards in the commits that follow `7cd0cf7`.

# aa-ticket — AA App Checklist review

> **Self-review by the project, not an independent review.**
> This report was written by the project itself (an AI-assisted code review requested by the
> project owner) following the *AA App Checklist*. It has not been checked by a third party and
> should not be treated as one. Before installing on a production instance, have someone outside
> the project repeat the review or at least spot-check the findings below.

## 1. Header

| | |
|---|---|
| App | aa-ticket (Python package `aa_ticket`), version `0.1.0` (`aa_ticket/__init__.py:3`) |
| Repo | https://github.com/yilifaer/aa-ticket |
| Reviewed state | commit `7cd0cf7` (branch `claude/friendly-einstein-21gzh0`). **No Git tag exists** (`git tag` returns nothing), so the commit hash is the only fixed reference. |
| Review date | 2026-11-14 |
| Target environment | Alliance Auth 5.4.0, MariaDB, Redis; apps from checklist section 1.3 plus aa-discordbot |
| Review method | Code review only (read-only). The app was not installed, its code was not run, its tests were not run. The installed AA 5.4.0 source was read to check hook behaviour. PyPI metadata and the AA GitLab repository tree were queried to compare AA versions. |
| Not checked | Runtime behaviour on AA 5.4.0 / MariaDB; GitHub Actions results (whether CI actually ran and passed); rendering of the templates; quality of the de/ru/es translations; behaviour with a real Discord webhook and a real aa-discordbot instance; the installed aa-discordbot version (its `send_message` helper was checked on the upstream `master` branch only). |

## 2. Short description

aa-ticket is a help-desk / ticket system for Alliance Auth. Players with `aa_ticket.basic_access`
submit tickets to a *department* (e.g. Diplomacy). Department staff are the members of AA groups
linked to the department (`models/config.py:52-58`). Departments form a tree; staff of a parent
department see and can act on the tickets of all departments below it (`access.py:67-86`).
Staff claim, reply, write internal notes, invite other departments, transfer, change priority or
category, and close tickets; requesters can reply, request escalation one level up, close and
reopen. Image attachments are stored under `MEDIA_ROOT/aa_ticket/` and served through a
permission-checked view.

External parts:
- **Discord webhooks** per department (outgoing HTTPS POST to `discord.com`), sent from a Celery
  task (`tasks.py:28-56`, `discord/webhook.py:89-90`).
- **aa-discordbot (optional)** for Discord direct messages (`discord/dm.py:8-23`); detected with
  `apps.is_installed("aadiscordbot")`.
- **Alliance Auth notifications** (bell) via `allianceauth.notifications.notify`
  (`notifications.py:9,149-154`).
- Three periodic Celery tasks that the admin adds to `CELERYBEAT_SCHEDULE` (README.md:87-102).

## 3. Assessment per requirement

| Requirement | Rating | Short reason |
|---|---|---|
| AA 5.0+ compatible | ⚠️ | Declares `allianceauth>=5.0,<6` (`pyproject.toml:27`), but `migrations/0001_initial.py:16-17` depends on `authentication.0026_…` and `eveonline.0025_…`, which exist only from AA **5.2.0** (not in v5.0.0 / v5.1.x tags on GitLab). Fine on the target 5.4.0; the stated floor and the CI job for `5.0.*` (`.github/workflows/tests.yml:14`) are wrong. |
| "Jobs" implemented as tasks | ✅ | Reminders, auto-close and attachment clean-up are Celery tasks with `QueueOnce` (`tasks.py:112,147,188`); webhooks and DMs are tasks (`tasks.py:28,59`). Caveat: notification dispatch runs synchronously in `on_commit` in the request (see 6.3). |
| Bootstrap | ✅ | All pages extend `allianceauth/base-bs5.html` via `templates/aa_ticket/base.html:1`; BS5 classes, FA6 icon names (`fa-ticket`, `fa-circle-check`, …); no third-party CSS/JS. |
| No unnecessary ESI calls | ✅ | No ESI usage at all (grep for `esi`, `providers`, `Token` finds nothing). |
| Use of available app data | ✅ | Uses AA `User`, `Group`, `State`, `UserProfile.main_character` / `EveCharacter` (`models/tickets.py:5,14-16`, `utils.py:1-9`), AA notifications, django-solo, aa-discordbot. No duplicate EVE data. |
| Tiered permissions (member / CEO / admin) | ⚠️ | Members see own tickets; department staff see their department and sub-departments; `view_all` sees everything. Tiers follow the **department tree, not corporations** — a CEO only sees tickets if placed in a (parent) department group. Superusers get full access to every ticket incl. internal notes (`access.py:44-45,82-83`). |
| App version | ⚠️ | `__version__ = "0.1.0"` read dynamically (`pyproject.toml:43-44`), CHANGELOG present, but **no Git tag**; README installs `@v0.1.0` (README.md:66), which does not exist at this commit. |
| Proper README | ⚠️ | Covers installation, `local.py`, permissions, tasks, update, uninstall, data protection. Inaccuracies: "Alliance Auth 5.0 or newer" (README.md:54), nonexistent tag (README.md:66), "first migration creates three priorities" (it is 0002, README.md:116), uninstall step 2 can fail (see 11.3). Missing: risk of joinable/auto groups as staff groups, user deletion blocked by tickets, MEDIA_ROOT must not be web-served. |
| No auto-updating of any kind | ✅ | Grep for `pip`, `subprocess`, `os.system`, `importlib.reload`, `pypi`, `update_check`, `latest_version` finds nothing outside tests. |
| Menu hook | ✅ | `TicketMenuItem` registered (`auth_hooks.py:30-54`), visible with `basic_access`; badge cached 60 s. See 3.2.2 for managers without `basic_access`. |
| No hidden creation of tasks, groups, roles or states | ✅ | No `PeriodicTask`/`CrontabSchedule`, no `Group`/`State`/`Permission` writes. Only data migration creates three priorities in the app's own table (`migrations/0002_default_priorities.py:16-28`), documented in README.md:116-117. |

## 4. Permissions table

All models set `default_permissions = ()`; the three permissions live on the unmanaged model
`General` (`models/config.py:25-35`).

| Codename | Display name | Effect (from code) | Recommendation |
|---|---|---|---|
| `aa_ticket.basic_access` | Can submit and view own tickets | Required by **every** view except the manage pages (`views/requester.py:15`, `views/ticket.py:19`, `views/staff.py:17`, `views/files.py:11`, `views/prefs.py:11`, `views/manage.py:18`) and for the menu (`auth_hooks.py:42`). Submitting is further limited per department by states/groups (`access.py:168-176`). | Give to the Member state. Department staff and ticket managers also need it (README says so for staff only). |
| `aa_ticket.view_all` | Can view all tickets | Not only viewing: makes the user a **controller of every ticket** (`access.py:82-83`) — claim, assign, invite, transfer, change priority/category, close, reopen — and shows internal notes, workbench and all statistics (`access.py:146-147,193-194`). | Give only to top leadership who should act on every ticket. Consider the display name misleading. Remember superusers have it implicitly. |
| `aa_ticket.manage` | Can manage ticket settings | Opens all *Manage* pages: departments (incl. webhook URL, staff groups), priorities, categories, all canned replies, settings (`views/manage.py:19,95-255`). Does **not** by itself show tickets. | Give to ticket administrators only. Controls who becomes staff (staff-group selection), so treat it as a high-privilege permission. |
| *(no permission)* department staff | — | Membership in a group linked to a department (`access.py:48-60`) grants read access to that department's and all descendant departments' tickets, internal notes and images, plus staff actions; staff may also edit their departments' canned replies (`views/manage.py:185-191`). | Use closed, non-joinable, non-auto groups for staff (see pitfall 1). |

## 5. Complete list of interfaces

### 8.1 Public endpoints without login
None. `UrlHook` has no `excluded_views` (`auth_hooks.py:57-60`), so AA wraps every view in
`main_character_required` (`allianceauth/urls.py:33-42`); every view also has `login_required`.
No `csrf_exempt`, no `APPS_WITH_PUBLIC_VIEWS`.

### 8.2 Protection of public endpoints
➖ No public endpoints. Cache: Django cache (Redis) for the menu badge (`auth_hooks.py:44-48`) and
celery-once locks for `QueueOnce` tasks.

### 8.3 Web routes (`aa_ticket/urls.py`, prefix `/ticket/`)

| Role | Route | View | Check |
|---|---|---|---|
| basic_access | `` , `mine/` | `requester.index`, `my_tickets` | own tickets only (`views/requester.py:28`) |
| basic_access | `new/`, `new/<department_id>/` | `submit_choose_department`, `submit` | `access.submittable_departments` (`views/requester.py:46,54`) |
| basic_access + can_view | `<pk>/` | `ticket.detail` | `get_visible_ticket` → 404 (`views/ticket.py:24-30`) |
| basic_access + can_view, POST | `<pk>/reply/` | `ticket.reply` | `services.add_reply` / `add_note` → `access.can_act` |
| basic_access + can_view, POST | `<pk>/action/<action>/` | `ticket.action` | action whitelist (`views/ticket.py:21,116`) + `access.can_act` in services |
| basic_access + can_view | `files/<pk>/` | `files.attachment` | can_view, internal notes only for staff (`views/files.py:15-18`) |
| basic_access | `prefs/` | `prefs.prefs` | POST only when DM available |
| staff (dept staff or view_all) | `staff/`, `stats/` | `staff.workbench`, `staff.stats` | `_require_staff` (`views/staff.py:31-33`) |
| staff / manage | `manage/canned/…` | `manage.canned*` | `_canned_scope` (`views/manage.py:185-213`) |
| manage | `manage/departments/…`, `manage/priorities/…`, `manage/categories/…`, `manage/settings/` | `manage.*` | `permission_required("aa_ticket.manage")` (`views/manage.py:19`) |
| manage, POST | `manage/departments/<pk>/test/` | `department_test` | sends a Discord test message **synchronously** (`views/manage.py:127-131`) |

### 8.4 Django admin models
Department (webhook URL excluded), Priority, Category, CannedReply, Ticket: read-only
(`admin.py:14-50`). TicketMessage, Attachment: read-only, superusers may delete (deletes files
too) (`admin.py:53-82`). Not registered: TicketSettings, UserPreference, EscalationRequest.
Because no default permissions exist, only superusers can open these admin pages.

### 8.5 Settings
- `MEDIA_ROOT` (`attachments.py:29`, `checks.py:7`) — uploads disabled without it.
- `SITE_URL` (`links.py:6`) — absolute links in Discord and notifications.
- `LANGUAGE_CODE` (`discord/webhook.py:61`, `translation.py:9`) — language of channel messages.
- Fixed constants in `app_settings.py:3-7` (`MAX_IMAGES_PER_MESSAGE=5`, `BADGE_CACHE_SECONDS=60`,
  `WEBHOOK_TIMEOUT=10`, `WEBHOOK_TEST_TIMEOUT=5`, `WEBHOOK_MAX_RETRIES=5`); not overridable from `local.py`.
- Front-end settings singleton `TicketSettings` (`models/config.py:222-265`): auto-close days,
  warning hours, reopen days, open tickets per person, max image MB, image retention, DM switch.

### 8.6 Signal listeners
None (grep for `@receiver` / `.connect(` finds nothing). `ready()` only imports system checks
(`apps.py:13-14`).

### 8.7 Outgoing connections
- Discord webhooks: `requests.post(url, json=payload, timeout=…)` (`discord/webhook.py:89-90`),
  URL restricted to `https://(canary.|ptb.)discord(app).com/api/webhooks/…` (`discord/webhook.py:24-26`).
  From the Celery worker (`tasks.py:38`) and from the web process for the test message
  (`discord/webhook.py:118`).
- aa-discordbot task queue (`discord/dm.py:16-23`, via `aadiscordbot.tasks.send_message(user_pk=…, embed=…)`).
- No ESI, no other external APIs.

### 8.8 External counterparts
- **Discord** (webhooks) — exists.
- **aa-discordbot** — exists (GitHub `Solar-Helix-Independent-Transport/allianceauth-discordbot`,
  PyPI 5.0.1, `allianceauth>=3,<6`). Its `send_message(user_pk=…, embed=…)` signature matches the
  call on upstream `master`; the installed version on the target was not checked. DMs also require
  a running bot and users linked through AA's Discord service.

## 6. Review catalogue

### 1. Compatibility and packaging

**1.1 AA version**
- 1.1.1 ⚠️ `allianceauth>=5.0,<6` (`pyproject.toml:27`) meets the wording, but the effective floor is 5.2.0 because of `migrations/0001_initial.py:16-17` (AA migrations `authentication.0026` and `eveonline.0025` are absent from GitLab tags v5.0.0, v5.1.0, v5.1.1 and present in v5.2.0). On AA 5.0/5.1, `migrate` would fail.
- 1.1.2 ✅ AA 5.0–5.4 require `django>=5.2,<6` (PyPI). The app uses `TextChoices`, `JSONField`, `transaction.on_commit`, `select_for_update`, `FileResponse` — all available in Django 5.2.
- 1.1.3 ✅ No silent AA upgrade on 5.4.0 (upper bound `<6`). New direct dependencies: `Pillow>=10` (not an AA dependency; unbounded) and `requests` (already required by AA) (`pyproject.toml:26-30`).
- 1.1.4 ⚠️ CI matrix: Python 3.10/3.12/3.13 × AA `5.0.*`/`5.4.0` on SQLite, plus AA 5.4.0 / Python 3.12 on MariaDB 11 with Redis 7 (`.github/workflows/tests.yml:8-60`). The `5.0.*` jobs should fail at migration (see 1.1.1); actual CI results not checked.

**1.2 Version and release**
- 1.2.1 ✅ `__version__ = "0.1.0"` (`aa_ticket/__init__.py:3`), read dynamically (`pyproject.toml:43-44`).
- 1.2.2 ❌ No Git tag for the reviewed state (`git tag` empty); README references `v0.1.0` (README.md:66).
- 1.2.3 ⚠️ CHANGELOG exists (`CHANGELOG.md`), but `[0.1.0]` has no date and the release is not tagged.
- 1.2.4 ⚠️ Git only; not on PyPI (`https://pypi.org/pypi/aa-ticket/json` → 404).

**1.3 Package contents**
- 1.3.1 ✅ `templates/**/*`, `static/**/*`, `locale/**/*` in `package-data` (`pyproject.toml:50-55`); compiled `.mo` files are committed (`git ls-files aa_ticket/locale`).
- 1.3.2 ✅ `exclude = ["aa_ticket.tests*"]` (`pyproject.toml:48`).
- 1.3.3 ✅ Yes, `collectstatic` needed (`static/aa_ticket/css/ticket.css`, `static/aa_ticket/js/ticket.js`); documented (README.md:110).

### 2. Conformity with AA standards

**2.1 Hooks**
- 2.1.1 ✅ `menu_item_hook` registered (`auth_hooks.py:51-54`) → 3.2.
- 2.1.2 ✅ `url_hook` with prefix `^ticket/`, no `excluded_views` (`auth_hooks.py:57-60`); all views are decorated by AA (`allianceauth/authentication/decorators.py:16-40`).
- 2.1.3 ➖ No `services_hook`.
- 2.1.4 ➖ No other hooks (no `dashboard_hook`, `charlink`, `secure_group_filters`).

**2.2 AppConfig**
- 2.2.1 ✅ `ready()` only imports `checks` (`apps.py:13-14`).
- 2.2.2 ✅ No DB writes, tasks, groups or permissions at startup.

**2.3 Logging** ⚠️ Uses `get_extension_logger` (`tasks.py:7,14`). Logged: department name, ticket number, exception type (`tasks.py:54-56`), user primary key at INFO when a DM fails (`tasks.py:83`), count of deleted images (`tasks.py:209`). Webhook URLs and ticket text are never logged; the user PK is an internal ID in plain text (minor).

**2.4 System checks** ✅ One check: `aa_ticket.W001` warns when `MEDIA_ROOT` is not set (`checks.py:5-15`). It does not warn when the folder is missing or not writable, although uploads are then silently disabled (`attachments.py:28-32`).

**2.5 Management commands** ➖ None (`aa_ticket/management/` does not exist).

**2.6 Reuse instead of rebuilding** ✅ django-solo `SingletonModel` (`models/config.py:3,222`), `QueueOnce` (`tasks.py:8`), AA notifications (`notifications.py:9`), `EveCharacter` / main character (`models/tickets.py:5`), AA `Group`/`State` for access, aa-discordbot for DMs. Discord webhooks use plain `requests` (acceptable; no AA helper exists).

**2.7 Comparison with eveuniverse and corptools**
- 2.7.1 ➖ No EVE static data needed.
- 2.7.2 ➖ No corp or member data needed beyond AA's main character.

### 3. User interface

**3.1 Bootstrap**
- 3.1.1 ✅ `grep -rn extends templates`: `base.html` extends `allianceauth/base-bs5.html` (`templates/aa_ticket/base.html:1`); the other 14 page templates extend `aa_ticket/base.html` or `aa_ticket/manage/base.html`.
- 3.1.2 ✅ BS5 classes (`form-select`, `text-bg-info`, `nav-link`) and FA6 names (`fa-circle-check`, `fa-triangle-exclamation`, `fa-ticket`).
- 3.1.3 ✅ No third-party libraries; only the app's own `ticket.css` and `ticket.js` (`templates/aa_ticket/base.html:18`, `templates/aa_ticket/detail.html:192`, `templates/aa_ticket/submit.html:55`); the JS states "No external libraries" (`static/aa_ticket/js/ticket.js:1`).

**3.2 Menu entry**
- 3.2.1 ✅ `TicketMenuItem.render()` returns `""` unless the user is authenticated and has `basic_access` (`auth_hooks.py:40-43`); AA hides items rendering `""` (`allianceauth/menu/templatetags/menu_menu_items.py:102-104`). Badge = unclaimed tickets of the user's own departments, excluding own tickets (`auth_hooks.py:15-27`).
- 3.2.2 ⚠️ Members and department staff reach it via `basic_access`. A ticket administrator who has only `manage` (not `basic_access`) gets no menu entry; the manage pages are reachable only by URL. README does not say managers need `basic_access`.
- 3.2.3 ✅ On a cache miss, one department query plus one `COUNT` per user; cached 60 s (`auth_hooks.py:44-48`, `app_settings.py:4`). The badge is not invalidated on claim (up to 60 s stale).

**3.3 Language** ✅ English source, translations for zh-hans, de, ru, es (`aa_ticket/locale/*`, 283 messages each per `msgfmt --statistics`). No language is forced: pages follow the user's AA language; personal notifications are rendered in the recipient's language (`translation.py:7-15`, `notifications.py:147`). Discord channel messages use `LANGUAGE_CODE` (`discord/webhook.py:61`). German users see German UI. Default priority names "Low/Normal/Urgent" are stored untranslated in the DB (`migrations/0002_default_priorities.py:8-13`). de/ru/es are labelled first versions (README.md:286-288); quality not checked.

### 4. Permissions

**4.1 Defined permissions** ✅ `basic_access`, `view_all`, `manage` (`models/config.py:31-35`), see section 4 table. `default_permissions = ()` on every model (`models/config.py:30,90,169,190,213,261,273`, `models/tickets.py:43,71,87,103`).

**4.2 Enforcement**
- 4.2.1 ✅ Every view has `login_required` plus a permission decorator, and object-level checks through `access` (see 8.3). Unauthorised ticket access returns 404 (`views/ticket.py:28-29`, `views/files.py:15-18`).
- 4.2.2 ✅ `reply`, `action`, all `*_delete` and `department_test` are `require_POST` (`views/ticket.py:94,114`, `views/manage.py:112,126,151,177,228`); edit forms and prefs change data only on POST. CSRF middleware applies; 20 POST forms, 20 `{% csrf_token %}`.
- 4.2.3 ➖ No `csrf_exempt`.

**4.3 Sense-check**
- 4.3.1 ⚠️ Superusers pass `basic_access`, `view_all` and `manage`, so they read every ticket including internal notes and images and can act on all of them (`access.py:44-45,82-83`). Documented (README.md:132-134); intended by the author, but operators should know superuser accounts see all private ticket content.
- 4.3.2 ⚠️ `view_all` grants full controller actions, not only viewing (`access.py:82-83`). `manage` controls which groups become staff and the webhook targets (`forms.py:45-57`), i.e. indirectly who can read tickets and where notifications go.
- 4.3.3 ⚠️ Access follows group membership live (`access.py:55`, cached per request only). Removing a user from a staff group removes access, **except** that a user who is still the ticket's assignee remains controller of that ticket (`access.py:84-85`) until reassigned. Losing `basic_access` (e.g. state change) locks the user out of all views, but they still receive bell notifications for their tickets (`notifications.py:145` checks `can_view`, which ignores `basic_access`). Deactivating a department removes its staff access (`access.py:55`).

**4.4 Tiers (target)**
- 4.4.1 ✅ Requesters see only their own tickets (`views/requester.py:28`, `access.py:99-102`).
- 4.4.2 ⚠️ No corporation tier; "CEO" access exists only if CEOs are put into a parent department group (README.md:154-163). Corp leaders do not automatically see their corp members' tickets.
- 4.4.3 ✅ `view_all` sees all tickets (`access.py:146-147`).

**4.5 Django admin** ✅ See 8.4: everything read-only; superusers may delete single messages/attachments (`admin.py:53-82`).

### 5. Hidden creations and side effects

- 5.1 ✅ No `PeriodicTask`, `CrontabSchedule`, `IntervalSchedule` or `django_celery_beat` usage (grep). Tasks are documented for `CELERYBEAT_SCHEDULE` (README.md:87-104).
- 5.2 ✅ No `Group`, `State` or `Permission` writes, no `.permissions.add`, `user_set.add`, `groups.add` (grep). The only `.add` calls are on the app's own M2M `collaborating_departments` (`services.py`).
- 5.3 ⚠️ One `RunPython` (`migrations/0002_default_priorities.py:16-39`): creates three rows in the app's own `Priority` table only if it is empty — fine. The **reverse** (`remove_defaults`, lines 31-33) deletes priorities by name; `Ticket.priority` is `PROTECT` (`migrations/0001_initial.py:461-467`), so `migrate aa_ticket zero` raises `ProtectedError` as soon as a ticket uses one of these priorities. No `RunSQL`.
- 5.4 ✅ No update check, pip, subprocess, telemetry or self-modification (grep finds nothing outside tests).

### 6. Tasks and jobs

**6.1 Celery tasks**

| Task | Purpose | QueueOnce | Retry |
|---|---|---|---|
| `aa_ticket.tasks.send_webhook` (`tasks.py:28`) | Post one Discord embed for one department | No | Up to 5 retries for network errors and 5xx (30 s × 2^n) and 429 (`retry_after`); other 4xx recorded as "Last delivery failed" (`tasks.py:36-53`) |
| `aa_ticket.tasks.send_dm` (`tasks.py:59`) | Queue one DM via aa-discordbot | No | Never; errors logged at INFO (`tasks.py:80-83`) |
| `aa_ticket.tasks.check_unclaimed` (`tasks.py:112`) | Unclaimed reminder and escalation ping to parent | Yes (graceful) | None; idempotent via conditional UPDATE (`tasks.py:97-109`) |
| `aa_ticket.tasks.check_auto_close` (`tasks.py:147`) | Auto-close warning, auto-close, waiting-for-staff reminder | Yes (graceful) | None |
| `aa_ticket.tasks.cleanup_attachments` (`tasks.py:188`) | Delete images of tickets closed longer than retention | Yes (graceful) | None |

**6.2 Triggers** ✅ Periodic tasks: beat schedule from README only. `send_webhook` / `send_dm`: queued by `notifications.dispatch` after each committed ticket event (`services.py:40,155`, `notifications.py:137,156`), both for user actions and for the periodic tasks' events. No signals.

**6.3 Synchronous work**
- 6.3.1 ⚠️ `dispatch` runs inside the web request after commit: it loads the ticket, writes AA notifications synchronously (`notifications.py:141-154`) and queues tasks. This is light. The "Send test message" button calls Discord synchronously in the request with a 5 s timeout (`views/manage.py:129`, `app_settings.py:6`) — admin-only, acceptable.
- 6.3.2 ⚠️ `transaction.on_commit` is called without `robust=True` (`services.py:40,155`). If the broker is unreachable, `.delay()` raises after the change has been committed, so the user gets HTTP 500 although the action was saved, and the remaining notifications for that event are lost. No synchronous fallback (good), but no graceful handling either.

**6.4 Cleanup** ⚠️ Images: optional retention (`tasks.py:188-209`, default off, `models/config.py:248-253`). Tickets, messages, internal notes, escalation requests and timeline events are **never** deleted; there is no UI or admin action to delete a ticket (`admin.py:14-22,46-50`).

### 7. ESI and use of existing data

- 7.1.1 ➖ No ESI endpoints.
- 7.1.2 ➖ No ESI calls.
- 7.1.3 ✅ No data fetched that AA already has.
- 7.1.4 ➖ No scopes requested.
- 7.2 ✅ Uses AA `EveCharacter` via `UserProfile.main_character` (`services.py:113`, `utils.py:5-8`); `EveCorporationInfo`/`EveAllianceInfo` not needed.
- 7.3 ✅ No data from the 1.3 apps is needed. aa-discordbot is an optional dependency checked with `apps.is_installed` (`discord/dm.py:8-13`).

### 8. Interfaces
See section 5 above (8.1–8.8).

### 9. Documentation (README)

- 9.1 ✅ Installation, `local.py` block, permission setup, Celery Beat tasks, update, uninstall, data protection, translations, development (README.md:12-301). Chinese README and a Raspberry Pi install guide with backup and rollback (`docs/install-raspberry-pi.zh-hans.md`).
- 9.2 ⚠️ Checked claims:
  - Task names `aa_ticket.tasks.check_unclaimed`, `check_auto_close`, `cleanup_attachments` (README.md:90-101) — ✅ match `tasks.py:113,148,189`.
  - Three permissions, codenames (README.md:121-127) — ✅ `models/config.py:31-35`.
  - `aa_ticket.W001` (README.md:85) — ✅ `checks.py:12`.
  - Settings defaults 7 / 24 / 7 / 5 / 5 MB / empty / on (README.md:214-222) — ✅ `models/config.py:223-258`; 5 images per message ✅ `app_settings.py:3`.
  - Webhook URL never shown in full (README.md:172) — ✅ `forms.py:77-78`, `models/config.py:137-140`, `admin.py:28`.
  - Channel table (README.md:182-190) — ✅ `notifications.py:37-54`. Mentions limited to configured roles — ✅ `discord/webhook.py:83-84`.
  - "Retries a few times then shows Last delivery failed" — ⚠️ only for network errors, 429 and 5xx; other 4xx fail immediately (`tasks.py:46-53`).
  - Superusers not pinged, no badge (README.md:132-134) — ✅ `auth_hooks.py:21-23`, `notifications.py:57-80`.
  - "Alliance Auth 5.0 or newer" (README.md:54) — ❌ effective minimum is 5.2.0 (1.1.1).
  - `pip install …@v0.1.0` (README.md:66) — ❌ tag does not exist.
  - "The first migration creates three priorities" (README.md:116) — ⚠️ it is migration 0002.
  - "*Manage* pages … canned replies" for `manage` (README.md:127) — ⚠️ department staff without `manage` can also manage their departments' canned replies (`views/manage.py:185-233`).
  - "Everything is configured from the front end; no … Django admin needed" (README.md:8) — ⚠️ permissions still have to be assigned to states/groups in the Django admin.
  - Uninstall step 2 `migrate aa_ticket zero` (README.md:267-270) — ⚠️ fails with `ProtectedError` when tickets use default priorities (5.3).
- 9.3 ⚠️ Missing for admins: (a) staff access follows AA group membership, so open/requestable or auto-assigned groups give self-service access to tickets; (b) `Ticket.requester` is `PROTECT` (`models/tickets.py:13`), so users with tickets cannot be deleted and there is no ticket deletion for GDPR erasure; (c) `MEDIA_ROOT` must not be served publicly by the web server, or images bypass the permission check; (d) webhook URLs are stored in plain text in the database (and therefore in DB backups); (e) behaviour when the broker is down (6.3.2).
- 9.4 ✅ English README; Simplified Chinese README (`README.zh-hans.md`) and install guide (`docs/install-raspberry-pi.zh-hans.md`).

### 10. Security and operational risks

- 10.1 ✅ All critical logic is inside the app (`access.py` is the single access module). Discord and aa-discordbot are notification channels only; failures do not block ticket handling (except 6.3.2).
- 10.2 ⚠️ Checked: requester identity comes from the session user and main character (`services.py:110-121`); action names whitelisted (`views/ticket.py:21,116`); internal notes and their images hidden from requesters, also when the requester is staff (`access.py:80-81,89-92`, `views/files.py:17-18`); assignees limited to staff of controller departments (`access.py:156-165`); category/department IDs validated (`services.py:96-97,309-310`); ticket text escaped (`templatetags/aa_ticket.py:22-25`); uploads verified by Pillow and served with stored MIME type and `nosniff` (`attachments.py:39-51`, `views/files.py:23-26`); `@everyone` suppressed (`discord/webhook.py:84`). Risks: whoever can join a staff group (open/requestable/auto groups in AA) gets ticket access; `view_all` and superusers see everything; a former assignee keeps control of their assigned ticket (4.3.3).
- 10.3 ⚠️ Only secret: Discord webhook URLs, stored in plain text (`models/config.py:79`), never displayed in full or logged, excluded from admin. They do not expire. Not encrypted at rest.
- 10.4 ✅/⚠️ Row locks via `select_for_update` for every mutating service (`services.py:128-129`), atomic conditional UPDATE for claim (`services.py:179-191`) and for reminder flags (`tasks.py:97-109`), webhook/DM dispatch only after commit. Minor races: the open-ticket limit is checked without a lock (`services.py:98-107`), so parallel submissions can exceed it; `check_auto_close` does not re-check `last_reply_by_staff` after locking (`services.py:325-339`), so a requester reply arriving in the same second can be auto-closed.
- 10.5 ✅ No signal handlers into AA code. No private AA/Django APIs; uses public `MenuItemHook`, `UrlHook`, `QueueOnce`, `notify`, `get_extension_logger`. Leading-underscore helpers used across modules are the app's own (`views/staff.py:48`, `tasks.py:101`).
- 10.6 ⚠️ No listeners on `EveCharacter`/`User`. The ticket page evaluates `can_act` for 12 actions, each reading `collaborating_departments` without prefetch (`views/ticket.py:46`, `access.py:71-76`) — roughly 20–30 queries per page, acceptable. Periodic tasks process at most 500 tickets per run ordered oldest first (`tasks.py:121-128,162-164`); tickets that stay in the candidate set (e.g. Urgent tickets in a top-level department never get `escalated_at`; waiting-for-staff tickets already reminded) can starve newer tickets once more than 500 accumulate. Unlikely at alliance scale.
- 10.7 ⚠️ Stored personal data: requester account and main character, all reply/note text, images, names of staff in timeline events (`event_data`), escalation reasons (`models/tickets.py`). Only users with accounts. Sent outside: ticket title, department, priority, requester main character name to Discord webhooks (`discord/webhook.py:59-86`) and DM text to aa-discordbot. No retention for tickets; user deletion blocked by `PROTECT` (`models/tickets.py:13`); erasure needs a manual shell operation.
- 10.8 ⚠️ Traps: (a) staff groups that are open, requestable or auto-assigned (state/corp groups); (b) `MEDIA_ROOT` inside a path served by nginx/Apache; (c) forgetting `from celery.schedules import crontab` (mentioned only in the Chinese guide, `docs/install-raspberry-pi.zh-hans.md:119`); (d) `SITE_URL` unset gives relative links in Discord (`links.py:6`); (e) managers without `basic_access` have no menu entry. `APPS_WITH_PUBLIC_VIEWS` is not involved.

### 11. Maturity and migration

- 11.1 ⚠️ One author (`yilifaer`), 18 commits, all on 2026-11-14 (`git log`); developed with AI assistance from a design document and plan committed in `docs/superpowers/`. 225 test functions in 17 test modules (`aa_ticket/tests/`), CI defined (`.github/workflows/tests.yml`); CI results not checked. A local, untracked test log reports 225 tests OK on SQLite — not verified by this review. No production track record.
- 11.2 ➖ New app; no predecessor and no data migration.
- 11.3 ⚠️ README uninstall steps (README.md:264-279) cover beat entries, tables, content types by `app_label` (permissions cascade with their content types), media files, and warn against `remove_stale_contenttypes --include-stale-apps`. Problems: step 2 can fail (5.3); AA bell notifications created by the app remain in AA's notification table (harmless). AA's menu sync removes the stale menu item itself (`allianceauth/menu/managers.py:59-61`).

## 7. Further pitfalls

1. **Staff access = AA group membership.** Anyone in a department's staff group reads all tickets, internal notes and images of that department and every department below it (`access.py:48-60,142-153`). If such a group is open, requestable or an auto group (state/corp), users can give themselves access. Use dedicated closed groups.
2. **Wrong AA version floor.** `pyproject.toml:27` allows 5.0/5.1, but `migrations/0001_initial.py:16-17` needs AA ≥ 5.2.0. Harmless on 5.4.0; fix the pin and the CI matrix before others install it.
3. **No release tag.** README installs `@v0.1.0`, which does not exist; the Chinese guide installs from a branch name (`docs/install-raspberry-pi.zh-hans.md:64`), a moving target. Tag a release and install by tag (or commit hash).
4. **Broker outage gives HTTP 500 after a saved action** and drops that event's notifications (`services.py:40,155`, no `robust=True`).
5. **`view_all` and superusers are full controllers of every ticket**, not just viewers (`access.py:82-83`); the display name "Can view all tickets" understates this.
6. **Uninstall `migrate aa_ticket zero` can fail** with `ProtectedError` (reverse of `0002` vs. `PROTECT` FK). Workaround: delete tickets first, or rename the default priorities before migrating to zero.
7. **No ticket retention / erasure;** users with tickets cannot be deleted (`models/tickets.py:13`, `PROTECT`).
8. **Images rely on `MEDIA_ROOT` not being web-served;** the app itself serves them only through the checked view (`views/files.py`).
9. **Webhook URLs in plain text in the DB** (and DB backups).
10. **Former assignee keeps control** of the ticket after leaving the staff group (`access.py:84-85`).
11. **Batch starvation in periodic tasks** above 500 stuck candidates (`tasks.py:121-128,162-164`).
12. **Repository hygiene:** `dump.rdb` (a Redis dump with queued Celery task messages from local test runs and a development host name) is committed; it contains no secrets but does not belong in the repo.
13. **Repo content addressed to an AI:** `docs/superpowers/plans/2026-11-14-aa-ticket.md:26` and `docs/superpowers/specs/2026-11-14-aa-ticket-design.md:67` contain instructions for the AI that wrote the code (commit attribution rules). They do not address the reviewer and had no effect on this review; reported per checklist rule 0.1.2.

## 8. Conclusion

**Install with conditions** on the target (AA 5.4.0, MariaDB, Redis): the code is clean, permission checks are central and consistent, there are no public endpoints, no hidden creations and no auto-update, and AA 5.4.0 satisfies the real migration requirements. Conditions: install from a Git tag or the reviewed commit hash (`7cd0cf7`), not a branch; link departments only to closed, non-auto groups and give `view_all` sparingly; keep `MEDIA_ROOT` out of the public web root; test first on a non-production instance (including a broker outage and the uninstall path). Because this is a **self-review**, get an independent review before the production rollout, and fix the AA version pin, tag and README errors before recommending the app to others.
