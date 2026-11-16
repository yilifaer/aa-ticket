# aa-ticket 0.4.0 — AA App Checklist review

> **Follow-up (0.4.1):** this report describes commit `280f5df` (0.4.0). The whole-app review that
> ran alongside it led to version 0.4.1, which fixes among others: the README statement about
> invited departments, the misleading "Claim the ticket" hint for helping departments, the
> "first migration" wording, the guarantee that tickets of departed assignees return to
> *Unclaimed* (all in-progress tickets are now checked), and notification loss during a short
> broker outage. Still open: there is no Git tag yet (install from a commit hash until one exists).


> **Self-review by the project, not an independent review.**
> This report was written by the project itself (an AI-assisted review requested by the project
> owner) following the *AA App Checklist*, for **version 0.4.0**. It has not been checked by a
> third party and should not be treated as one. Before installing on a production instance, have
> someone outside the project repeat the review or at least spot-check the findings below.
> It replaces the earlier self-review of commit `7cd0cf7` (version 0.1.0).

## 1. Header

| | |
|---|---|
| App | aa-ticket (Python package `aa_ticket`), version `0.4.0` (`aa_ticket/__init__.py:3`) |
| Repo | https://github.com/yilifaer/aa-ticket |
| Reviewed state | commit `280f5df` (branch `claude/friendly-einstein-21gzh0`). **No Git tag exists** (`git tag` and `git ls-remote --tags origin` return nothing), so the commit hash is the only fixed reference. |
| Review date | 2026-11-16 |
| Target environment | Alliance Auth 5.4.0, MariaDB, Redis; apps from checklist section 1.3 plus aa-discordbot 5.0.1 |
| Review method | Code review of the whole repository. **Deviation from rule 0.1.1, at the requester's explicit request:** the app's own test suite was run (`python runtests.py aa_ticket`, 334 tests, OK, SQLite + Redis, AA 5.4.0, Django 5.2.19, Celery 5.7.0, Python 3.13), and throwaway probe tests were written and run in a scratch folder outside the repo to confirm suspected issues (marked "probe" below). The installed AA 5.4.0 source was read to check hook behaviour; the AA 5.0.0 and 5.1.0 wheels and the aa-discordbot 5.0.1 wheel from PyPI were inspected. |
| Not checked | Runtime on MariaDB (CI defines a MariaDB job, results not checked); GitHub Actions results; behaviour of a real Discord webhook and a real aa-discordbot instance; visual rendering of the templates in a browser and in AA themes; quality of the de/ru/es translations; behaviour when the Celery broker is really unreachable (only simulated by mocking `.delay`); the Raspberry Pi test server. |

## 2. Short description

aa-ticket is a help-desk / ticket system for Alliance Auth. Players with `aa_ticket.basic_access`
submit tickets to a *department* (e.g. Diplomacy). Department staff are the members of AA groups
linked to the department (`models/config.py:52-58`, `access.py:48-60`). Departments form a tree;
staff of a department and of every department above it are *controllers* of its tickets
(`access.py:67-84`); invited or escalated-to departments are *collaborators* (`access.py:71-90`).
Controllers claim, assign, invite, transfer, change priority/category and close; anyone on the
staff side writes internal notes. Since 0.4.0, **only the requester and the current assignee can
reply publicly** (`access.py:127-131`). Requesters can reply, request escalation one level up,
close and reopen. Image attachments are re-encoded and stored under `MEDIA_ROOT/aa_ticket/` and
served through a permission-checked view. An overview page and an AA dashboard card show counts.

External parts:
- **Discord webhooks** per department (outgoing HTTPS POST to `discord.com`), sent from a Celery
  task (`tasks.py:28-56`, `discord/webhook.py:90-91`).
- **aa-discordbot (optional)** for Discord direct messages (`discord/dm.py:8-23`), detected with
  `apps.is_installed("aadiscordbot")`.
- **Alliance Auth notifications** (bell) via `allianceauth.notifications.notify`
  (`notifications.py:10,167-172`).
- Three periodic Celery tasks that the admin adds to `CELERYBEAT_SCHEDULE` (README.md:101-118).

## 3. Assessment per requirement

| Requirement | Rating | Short reason |
|---|---|---|
| AA 5.0+ compatible | ✅ | `allianceauth>=5.0,<6` (`pyproject.toml:27`). Migration `0001_initial.py:14-19` now depends on `authentication.0025_v5squash` and `eveonline.0019_v5squash`, both present in the AA 5.0.0 and 5.1.0 wheels (`unzip -l`). All AA APIs used (`MenuItemHook`, `UrlHook`, `DashboardItemHook`, `QueueOnce`, `notify`, `framework/dashboard/widget-title.html`) exist in 5.0.0. CI tests `5.0.*` and `5.4.0` (`.github/workflows/tests.yml:14`). |
| "Jobs" implemented as tasks | ✅ | Reminders, auto-close, assignee release and attachment clean-up are `QueueOnce` Celery tasks (`tasks.py:158,185,234`); webhooks and DMs are tasks (`tasks.py:28,59`). Only light work runs in the request (`notifications.dispatch` after commit) and the admin-only "Send test message" (`views/manage.py:162-170`). |
| Bootstrap | ✅ | All pages extend `allianceauth/base-bs5.html` via `templates/aa_ticket/base.html:1`; BS5 classes and FA6 icon names; no third-party CSS/JS. |
| No unnecessary ESI calls | ✅ | No ESI usage at all (checklist grep for `esi`, `providers`, `Token` finds nothing but docstrings). |
| Use of available app data | ✅ | Uses AA `User`, `Group`, `State`, `UserProfile.main_character` / `EveCharacter` (`models/tickets.py:5,13-16`, `utils.py:1-9`), AA notifications, django-solo, aa-discordbot. No duplicated EVE data. |
| Tiered permissions (member / CEO / admin) | ⚠️ | Members see own tickets; department staff see their department and sub-departments; `view_all` sees and handles everything. Tiers follow the **department tree, not corporations**; a CEO only sees tickets if placed in a (parent) department group. Superusers are full controllers of every ticket incl. internal notes (`access.py:44-45,82-83`). |
| App version | ⚠️ | `__version__ = "0.4.0"` read dynamically (`pyproject.toml:40-41`), CHANGELOG present, but **no Git tag**; README installs `@v0.4.0` (README.md:69), which does not exist; Chinese docs install from the branch name. |
| Proper README | ⚠️ | Covers installation, `local.py`, permissions, tasks, update, uninstall, data protection. Inaccuracies: invited departments "can read, reply and write internal notes" (README.md:264) contradicts the 0.4.0 reply rule; nonexistent tag (README.md:69); "first migration creates three priorities" (it is 0002, README.md:130); channel table omits the "assignee left" message (README.md:200-208 vs `notifications.py:55-56`); "within five minutes" is not guaranteed (README.md:273-274, see 10.6). |
| No auto-updating of any kind | ✅ | Grep for `pip`, `subprocess`, `os.system`, `importlib.reload`, `pypi`, `update_check`, `latest_version` finds nothing outside tests. |
| Menu hook | ✅ | `TicketMenuItem` registered (`auth_hooks.py:31-50,77-79`), visible with `basic_access`; badge cached 60 s. All management pages also require `basic_access` (`views/manage.py:18-19`), so every role reaches the app from the menu. |
| No hidden creation of tasks, groups, roles or states | ✅ | No `PeriodicTask`/`CrontabSchedule`, no `Group`/`State` writes, no permission assignment. Data migrations only touch the app's own `Priority` rows and rename the app's own `view_all` permission filtered by `app_label` (`migrations/0002…:16-28`, `0003…:6-11`, `0004…:6-15`). |

## 4. Permissions table

All models set `default_permissions = ()`; the three permissions live on the unmanaged model
`General` (`models/config.py:25-35`).

| Codename | Display name | Effect (from code) | Recommendation |
|---|---|---|---|
| `aa_ticket.basic_access` | Can submit and view own tickets | Required by **every** view (`views/requester.py:15`, `views/ticket.py:19`, `views/staff.py:17`, `views/files.py:11`, `views/prefs.py:11`, `views/manage.py:18`), for the menu (`auth_hooks.py:42`), the dashboard card (`auth_hooks.py:59`) and for receiving notifications (`notifications.py:163`). Submitting is further limited per department by states/groups (`access.py:191-199`). | Give to the Member state. Department staff and ticket managers also need it (README.md:139,141 says so). |
| `aa_ticket.view_all` | Can view and handle all tickets | Makes the user a **controller of every ticket** except their own (`access.py:79-84`): claim, assign, invite, transfer, change priority/category, close, reopen; internal notes and images; workbench and all statistics (`access.py:164-165,214-217`). Public replies only after claiming/being assigned (`access.py:127-131`). Never pinged, no badge. | Give only to top leadership who should act on every ticket. Superusers have it implicitly. |
| `aa_ticket.manage` | Can manage ticket settings | Opens all *Manage* pages: departments (incl. webhook URL, staff groups, submit restrictions), priorities, categories, all canned replies, settings (`views/manage.py:124-224,230-236,284-301`). Does **not** by itself show tickets. | Ticket administrators only. Controls who becomes staff (staff-group selection, `forms.py:46-57`) and where notifications go, so treat it as high privilege. |
| *(no permission)* department staff | — | Membership in a group linked to an active department (`access.py:48-60`) grants read access to that department's and all descendant departments' tickets, internal notes and images, staff actions as controller, internal notes as collaborator, and editing of their departments' canned replies (`views/manage.py:230-278`). | Use closed (internal), non-auto groups. The department pages warn for joinable/requestable groups (`views/manage.py:73-80`). |

## 5. Complete list of interfaces

### 8.1 Public endpoints without login
None. `UrlHook` has no `excluded_views` (`auth_hooks.py:82-84`), so AA wraps every view in
`main_character_required` (`allianceauth/urls.py:23-47`, `allianceauth/authentication/decorators.py:16-40`);
every view also has `login_required`. No `csrf_exempt`, no `APPS_WITH_PUBLIC_VIEWS`.

### 8.2 Protection of public endpoints
➖ No public endpoints. Cache: Django cache (Redis) for the menu badge (`auth_hooks.py:44-48`) and
celery-once locks for the `QueueOnce` tasks (`tasks.py:158,185,234`).

### 8.3 Web routes (`aa_ticket/urls.py`, prefix `/ticket/`)

| Role | Route | View | Check |
|---|---|---|---|
| basic_access | `` | `requester.index` (overview) | sections by role (`overview.py:82-121`) |
| basic_access | `mine/` | `requester.my_tickets` | own tickets only (`views/requester.py:34`) |
| basic_access | `new/`, `new/<department_id>/` | `submit_choose_department`, `submit` | `access.submittable_departments` (`views/requester.py:52,60`, `services.py:102`) |
| basic_access + can_view | `<pk>/` | `ticket.detail` | `get_visible_ticket` → 404 (`views/ticket.py:24-30`) |
| basic_access + can_view, POST | `<pk>/reply/` | `ticket.reply` | `services.add_reply` / `add_note` → `access.can_act` (`services.py:153,181`) |
| basic_access + can_view, POST | `<pk>/action/<action>/` | `ticket.action` | action whitelist (`views/ticket.py:21,130-131`) + `access.can_act` in services |
| basic_access + can_view | `files/<pk>/` | `files.attachment` | can_view; internal-note images only for staff (`views/files.py:15-18`) |
| basic_access | `prefs/` | `prefs.prefs` | POST only when DMs are available (`views/prefs.py:15`) |
| staff (dept staff or view_all) | `staff/`, `stats/` | `staff.workbench`, `staff.stats` | `_require_staff` (`views/staff.py:31-33`) |
| staff / manage | `manage/canned/`, `manage/canned/<pk>/`, `…/delete/` | `manage.canned*` | `_canned_scope` (`views/manage.py:230-278`) |
| manage | `manage/departments/…`, `manage/priorities/…`, `manage/categories/…`, `manage/settings/` | `manage.*` | `permission_required("aa_ticket.manage")` (`views/manage.py:19`) |
| manage, POST | `manage/departments/<pk>/test/` | `department_test` | sends a Discord test message **synchronously**, 5 s timeout (`views/manage.py:162-170`, `app_settings.py:9`) |

Also: dashboard card via `dashboard_hook` (`auth_hooks.py:53-74`), rendered on the AA dashboard.

### 8.4 Django admin models
Department (webhook URL excluded), Priority, Category, CannedReply, Ticket: read-only
(`admin.py:14-50`). TicketMessage, Attachment: read-only, superusers may delete (deletes files
too) (`admin.py:53-82`). Not registered: TicketSettings, UserPreference, EscalationRequest.
Because no default permissions exist, only superusers can open these admin pages.

### 8.5 Settings
- `MEDIA_ROOT` (`attachments.py:30-34`, `checks.py:9-25`) — uploads disabled when unset, missing
  or not writable (`aa_ticket.W001` / `W002`).
- `SITE_URL` (`links.py:6`) — absolute links in Discord and notifications.
- `LANGUAGE_CODE` (`translation.py:9`) — fallback for users without a profile language.
- Fixed constants in `app_settings.py:3-10` (`MAX_IMAGES_PER_MESSAGE=5`, `MAX_IMAGE_PIXELS`,
  `MAX_FRAMES`, `MAX_ANIMATION_PIXELS`, `BADGE_CACHE_SECONDS=60`, `WEBHOOK_TIMEOUT=10`,
  `WEBHOOK_TEST_TIMEOUT=5`, `WEBHOOK_MAX_RETRIES=5`); not overridable from `local.py`.
- Front-end settings singleton `TicketSettings` (`models/config.py:227-284`): auto-close days,
  warning hours, reopen days, open tickets per person, max image MB, image retention, DM switch,
  channel language, DM language mode.

### 8.6 Signal listeners
None (grep for `@receiver` / `.connect(` finds nothing). `ready()` only imports the system checks
(`apps.py:11-12`).

### 8.7 Outgoing connections
- Discord webhooks: `requests.post(url, json=payload, timeout=…)` (`discord/webhook.py:90-91`),
  URL restricted to `https://(canary.|ptb.)discord(app).com/api/webhooks/<id>/<token>`
  (`discord/webhook.py:23-25,30-37`). From the Celery worker (`tasks.py:38`) and from the web
  process for the test message (`discord/webhook.py:124`).
- aa-discordbot task queue (`discord/dm.py:16-23`, `aadiscordbot.tasks.send_message(user_pk=…, embed=…)`).
- No ESI, no other external APIs.

### 8.8 External counterparts
- **Discord** (webhooks) — exists.
- **aa-discordbot 5.0.1** — exists (PyPI `allianceauth-discordbot` 5.0.1, `allianceauth>=3,<6`).
  Its `send_message(message="", channel_id=None, user_id=None, user=None, user_pk=None, embed=None, countdown=0)`
  in `aadiscordbot/tasks.py:11` of the 5.0.1 wheel matches the call; it queues
  `send_direct_message_by_user_id`, which needs the bot's Celery route and a running bot
  (README.md:230-232). Not run against a real bot.

## 6. Review catalogue

### 1. Compatibility and packaging

**1.1 AA version**
- 1.1.1 ✅ `allianceauth>=5.0,<6` (`pyproject.toml:27`). Migration dependencies `authentication.0025_v5squash` and `eveonline.0019_v5squash` (`migrations/0001_initial.py:14-19`) exist in AA 5.0.0 and 5.1.0 (wheel listing), so the stated floor is real.
- 1.1.2 ✅ AA 5.0–5.4 require `django>=5.2,<6`, `celery>=5.5/5.6,<6` (wheel METADATA). The app uses `TextChoices`, `JSONField`, `transaction.on_commit(…, robust=True)` (Django ≥ 4.2), `select_for_update`, `FileResponse` — all in Django 5.2.
- 1.1.3 ✅ No silent AA upgrade on 5.4.0 (upper bound `<6`). Extra direct dependencies: `Pillow>=10` (unbounded) and `requests` (already required by AA) (`pyproject.toml:26-30`).
- 1.1.4 ✅ CI: Python 3.10/3.12/3.13 × AA `5.0.*`/`5.4.0` on SQLite + Redis 7, and AA 5.4.0 / Python 3.12 on MariaDB 11 + Redis 7 (`.github/workflows/tests.yml:8-62`). Results not checked; locally 334 tests pass on SQLite / AA 5.4.0. Python 3.11 (classifier `pyproject.toml:22`) is not in the matrix.

**1.2 Version and release**
- 1.2.1 ✅ `__version__ = "0.4.0"` (`aa_ticket/__init__.py:3`), read dynamically (`pyproject.toml:40-41`); also shown in the page header (`templates/aa_ticket/base.html:6`).
- 1.2.2 ❌ No Git tag for the reviewed state (`git tag`, `git ls-remote --tags origin` empty); README installs `@v0.4.0` (README.md:69).
- 1.2.3 ⚠️ CHANGELOG exists (`CHANGELOG.md`), Keep-a-Changelog format, but no release has a date and none is tagged (`CHANGELOG.md:9,30,46,75`).
- 1.2.4 ⚠️ Git only; not on PyPI (`https://pypi.org/pypi/aa-ticket/json` → 404).

**1.3 Package contents**
- 1.3.1 ✅ `templates/**/*`, `static/**/*`, `locale/**/*` in `package-data` (`pyproject.toml:47-52`); compiled `.mo` files are committed (`git ls-files aa_ticket/locale`).
- 1.3.2 ✅ `exclude = ["aa_ticket.tests*"]` (`pyproject.toml:45`).
- 1.3.3 ✅ Yes, `collectstatic` is needed (`static/aa_ticket/css/ticket.css`, `static/aa_ticket/js/ticket.js`); documented (README.md:124).

### 2. Conformity with AA standards

**2.1 Hooks**
- 2.1.1 ✅ `menu_item_hook` registered (`auth_hooks.py:77-79`) → 3.2.
- 2.1.2 ✅ `url_hook` with prefix `^ticket/`, no `excluded_views` (`auth_hooks.py:82-84`); AA decorates every view with `main_character_required` (`allianceauth/urls.py:33-44`).
- 2.1.3 ➖ No `services_hook`.
- 2.1.4 ✅ `dashboard_hook` (`auth_hooks.py:53-74`): card for users with `basic_access`, returns `""` when there is nothing to show; AA catches exceptions in dashboard hooks (`allianceauth/hooks.py:131-137`). No `charlink`, no `secure_group_filters`.

**2.2 AppConfig**
- 2.2.1 ✅ `ready()` only imports `checks` (`apps.py:11-12`).
- 2.2.2 ✅ No DB writes, tasks, groups or permissions at startup.

**2.3 Logging** ✅ Uses `get_extension_logger` (`tasks.py:7,14`). Logged: department name, ticket number, error class/HTTP status (`tasks.py:54-56`), user primary key at INFO when a DM fails (`tasks.py:83`), count of deleted images (`tasks.py:255`). Webhook URLs, tokens and ticket text are never logged. Failures inside `on_commit(robust=True)` are logged by Django's own logger, not the extension logger.

**2.4 System checks** ✅ `aa_ticket.W001` when `MEDIA_ROOT` is not set, `aa_ticket.W002` when it does not exist or is not writable (`checks.py:7-26`).

**2.5 Management commands** ➖ None (`aa_ticket/management/` does not exist).

**2.6 Reuse instead of rebuilding** ✅ django-solo `SingletonModel` (`models/config.py:3,227`), `QueueOnce` (`tasks.py:8`), AA notifications (`notifications.py:10`), `EveCharacter` / main character (`models/tickets.py:5`), AA `Group`/`State`/`AuthGroup` for access and warnings (`views/manage.py:73-80`), AA dashboard widget title template, aa-discordbot for DMs. Discord webhooks use plain `requests` (no AA helper exists).

**2.7 Comparison with eveuniverse and corptools**
- 2.7.1 ➖ No EVE static data needed.
- 2.7.2 ➖ No corp or member data needed beyond AA's main character.

### 3. User interface

**3.1 Bootstrap**
- 3.1.1 ✅ `grep -rn extends templates`: `base.html` extends `allianceauth/base-bs5.html` (`templates/aa_ticket/base.html:1`); the other 15 page templates extend `aa_ticket/base.html` or `aa_ticket/manage/base.html`. The dashboard card is a fragment using AA's `framework/dashboard/widget-title.html` (`templates/aa_ticket/dashboard_card.html:6`).
- 3.1.2 ✅ BS5 classes (`form-select`, `text-body-secondary`, `alert`, `card`) and FA6 names (`fa-triangle-exclamation`, `fa-circle-info`, `fa-circle-check`, `fa-ticket`).
- 3.1.3 ✅ No third-party libraries; only the app's own `ticket.css` and `ticket.js` (`templates/aa_ticket/base.html:19`, `detail.html:205`, `submit.html:55`); `static/aa_ticket/js/ticket.js:1` "No external libraries"; no `innerHTML`.

**3.2 Menu entry**
- 3.2.1 ✅ `TicketMenuItem.render()` returns `""` unless the user is authenticated and has `basic_access` (`auth_hooks.py:40-43`); AA hides items rendering `""` (`allianceauth/menu/templatetags/menu_menu_items.py:103`). Badge = unclaimed tickets of the user's own departments, excluding own tickets (`auth_hooks.py:15-28`).
- 3.2.2 ✅ Members, department staff, `view_all` holders and managers all need `basic_access` for any page (`views/manage.py:18-19`) and then get the menu entry; the in-app navigation shows Workbench/Statistics/Manage by role (`templatetags/aa_ticket.py:81-98`). README states that managers also need `basic_access` (README.md:141).
- 3.2.3 ⚠️ Menu: on a cache miss one department query plus one `COUNT`, cached 60 s (`auth_hooks.py:44-48`); the badge cache is cleared for the department's staff on every ticket event (`notifications.py:124-129`). The **dashboard card is not cached**: about six queries on every dashboard load (`overview.py:124-150`); probe: the whole AA dashboard page took 26 queries in the test setup. Acceptable, but it scales with dashboard traffic.

**3.3 Language** ✅ English source, translations for zh-hans, de, ru, es (325 messages each per `msgfmt --statistics`, all translated). No language is forced: pages follow the user's AA language; bell notifications use the recipient's profile language (`translation.py:7-9,38-41`, `notifications.py:165`); Discord channel messages use the *channel language* setting (`translation.py:12-15`, default English), DMs per person or channel language (`translation.py:18-23`). German users see German UI. Default priority names "Low/Normal/Urgent" are stored untranslated in the DB (`migrations/0002_default_priorities.py:8-13`). de/ru/es are labelled first versions (README.md:324-325); quality not checked.

### 4. Permissions

**4.1 Defined permissions** ✅ `basic_access`, `view_all`, `manage` (`models/config.py:31-35`), see section 4 table. `default_permissions = ()` on every model (`models/config.py:30,90,174,195,218,280,292`, `models/tickets.py:43,71,87,103`).

**4.2 Enforcement**
- 4.2.1 ✅ Every view has `login_required` plus `permission_required(basic_access)`, and object-level checks through `access` (see 8.3). Unauthorised ticket or attachment access returns 404 (`views/ticket.py:28-29`, `views/files.py:15-20`). Services re-check `can_act` under a row lock (`services.py:23-25,146-153`).
- 4.2.2 ✅ `reply`, `action`, all `*_delete` and `department_test` are `require_POST` (`views/ticket.py:95,128`, `views/manage.py:150,165,193,222,273`); edit forms and prefs change data only on POST. CSRF middleware applies; 21 `method="post"` forms, 21 `{% csrf_token %}`. Minor: `prefs` creates a `UserPreference` row on GET (`views/prefs.py:13`, `models/config.py:294-297`).
- 4.2.3 ➖ No `csrf_exempt`.

**4.3 Sense-check**
- 4.3.1 ⚠️ Superusers pass `basic_access`, `view_all` and `manage`, so they read every ticket including internal notes and images and can act on all of them (`access.py:44-45,82-83`). Documented (README.md:150-152); intended, but operators should know superuser accounts see all private ticket content.
- 4.3.2 ⚠️ `view_all` grants full controller actions, not only viewing (`access.py:82-83`); the display name was changed to "Can view and handle all tickets" (`migrations/0003…:6-11`). `manage` controls which groups become staff and the webhook targets (`forms.py:46-57,100-119`), i.e. indirectly who can read tickets and where notifications go.
- 4.3.3 ✅ Access follows group membership live (`access.py:55`, cached per request object only). A user removed from a staff group loses access at once: `can_act("reply")` requires the assignee to still be a controller (`access.py:129-131`), and `check_unclaimed` puts such tickets back to *Unclaimed* (`tasks.py:112-136`) — but see 10.6 for the 500-ticket batch limit. Losing `basic_access` locks the user out and stops notifications (`notifications.py:163`); a user who loses only `basic_access` stays assignee of their tickets (probe), so controllers have to reassign. Deactivating a department removes its staff access (`access.py:55`) and is refused while it has open tickets or active children (`forms.py:80-98`).

**4.4 Tiers (target)**
- 4.4.1 ✅ Requesters see only their own tickets (`views/requester.py:34`, `access.py:97-100,167`); internal notes are hidden from requesters even if they are staff (`access.py:80-81,88-89`).
- 4.4.2 ⚠️ No corporation tier; "CEO" access exists only if CEOs are put into a parent department group (README.md:172-181). Corp leaders do not automatically see their corp members' tickets.
- 4.4.3 ✅ `view_all` sees all tickets (`access.py:164-165`).

**4.5 Django admin** ✅ See 8.4: everything read-only; superusers may delete single messages/attachments (`admin.py:53-82`); webhook URL excluded (`admin.py:28`).

### 5. Hidden creations and side effects

- 5.1 ✅ No `PeriodicTask`, `CrontabSchedule`, `IntervalSchedule` or `django_celery_beat` usage (grep). Tasks are documented for `CELERYBEAT_SCHEDULE` (README.md:101-118).
- 5.2 ✅ No `Group` or `State` writes and no `.permissions.add`, `user_set.add`, `groups.add` (grep). The only `Permission.objects` use is the rename in migration 0003, limited to `content_type__app_label="aa_ticket"` (`migrations/0003_language_settings_and_view_all_name.py:9`); it does not assign permissions.
- 5.3 ✅ Three `RunPython` operations, all with `noop` reverse: `0002` creates three rows in the app's own `Priority` table only if it is empty (`migrations/0002_default_priorities.py:16-36`); `0003` renames the app's own `view_all` permission (`0003…:6-11,64`); `0004` flags one existing priority as urgent (`0004_priority_is_urgent.py:6-15,34`). No `RunSQL`. `migrate aa_ticket zero` no longer deletes rows by name, so the earlier `ProtectedError` is gone.
- 5.4 ✅ No update check, pip, subprocess, telemetry or self-modification (grep finds nothing outside tests).

### 6. Tasks and jobs

**6.1 Celery tasks**

| Task | Purpose | QueueOnce | Retry |
|---|---|---|---|
| `aa_ticket.tasks.send_webhook` (`tasks.py:28`) | Post one Discord embed for one department | No | Up to 5 retries for network errors and 5xx (30 s × 2^n) and 429 (`retry_after`); other 4xx recorded as "Last delivery failed" at once (`tasks.py:37-56`) |
| `aa_ticket.tasks.send_dm` (`tasks.py:59`) | Queue one DM via aa-discordbot | No | Never; errors logged at INFO (`tasks.py:80-83`) |
| `aa_ticket.tasks.check_unclaimed` (`tasks.py:158`) | Release tickets of departed assignees, unclaimed reminder, escalation ping to parent | Yes (graceful) | None; idempotent via conditional UPDATE (`tasks.py:97-109,131-136`) |
| `aa_ticket.tasks.check_auto_close` (`tasks.py:185`) | Auto-close warning, auto-close, waiting-for-staff reminder | Yes (graceful) | None |
| `aa_ticket.tasks.cleanup_attachments` (`tasks.py:234`) | Delete images of tickets closed longer than retention | Yes (graceful) | None |

**6.2 Triggers** ✅ Periodic tasks: beat schedule from README only. `send_webhook` / `send_dm`: queued by `notifications.dispatch` after each committed ticket event (`services.py:40,174`, `notifications.py:152-154,173-174`), both for user actions and for the periodic tasks' events. No signals.

**6.3 Synchronous work**
- 6.3.1 ✅ `dispatch` runs in the web request after commit: loads the ticket, clears badge cache keys, writes AA notifications (`notifications.py:136-174`) and queues tasks — light. The "Send test message" button calls Discord synchronously with a 5 s timeout (`views/manage.py:162-170`, `app_settings.py:9`) — admin-only, acceptable.
- 6.3.2 ⚠️ `on_commit(…, robust=True)` (`services.py:40,174`): a broker failure no longer gives HTTP 500 and the saved action stays saved. But one failing `.delay()` aborts the rest of `dispatch`: webhooks are queued first (`notifications.py:152-154`), so the **bell notifications of that event are lost as well** (probe: `send_webhook.delay` raising `OperationalError` → 0 `notify` calls after a transfer). No synchronous fallback (good). Possible request delay from kombu's publish retries was not checked.

**6.4 Cleanup** ⚠️ Images: optional retention (`tasks.py:234-255`, default off, `models/config.py:253-258`). Tickets, messages, internal notes, escalation requests and timeline events are **never** deleted; there is no UI or admin action to delete a ticket (`admin.py:14-22,46-50`).

### 7. ESI and use of existing data

- 7.1.1 ➖ No ESI endpoints.
- 7.1.2 ➖ No ESI calls.
- 7.1.3 ✅ No data fetched that AA already has.
- 7.1.4 ➖ No scopes requested.
- 7.2 ✅ Uses AA `EveCharacter` via `UserProfile.main_character` (`services.py:131`, `utils.py:5-8`); `EveCorporationInfo`/`EveAllianceInfo` not needed.
- 7.3 ✅ No data from the 1.3 apps is needed. aa-discordbot is optional, checked with `apps.is_installed` (`discord/dm.py:8-13`); its modules are imported only inside `send()` (`discord/dm.py:18-20`).

### 8. Interfaces
See section 5 above (8.1–8.8).

### 9. Documentation (README)

- 9.1 ✅ Installation, `local.py` block, nginx upload limit, permission setup, Celery Beat tasks, update, uninstall, data protection, translations, development (README.md:62-339). Chinese README, a Raspberry Pi install guide with backup and rollback (`docs/install-raspberry-pi.zh-hans.md`) and upgrade notes for 0.3.0 and 0.4.0 (`docs/upgrade-0.*.zh-hans.md`).
- 9.2 ⚠️ Checked claims:
  - Task names `check_unclaimed`, `check_auto_close`, `cleanup_attachments` (README.md:104-114) — ✅ `tasks.py:158-159,185-186,234-235`.
  - Three permissions, codenames, `view_all` display name (README.md:137-141) — ✅ `models/config.py:31-35`.
  - Managers need `basic_access` (README.md:141) — ✅ `views/manage.py:18-19`.
  - `aa_ticket.W001` (README.md:88) — ✅ `checks.py:14`.
  - "Alliance Auth 5.0 or newer" (README.md:57) — ✅ see 1.1.1.
  - Settings defaults 7 / 24 / 7 / 5 / 5 MB / empty / on / English / personal (README.md:241-251) — ✅ `models/config.py:228-277`; warning must be shorter than auto-close — ✅ `forms.py:173-183`; 5 images per message — ✅ `app_settings.py:3`.
  - Webhook URL never shown in full (README.md:190) — ✅ `forms.py:77-78`, `models/config.py:137-140`, `admin.py:28`.
  - Only configured roles can be mentioned, `@everyone` does nothing (README.md:212-213) — ✅ `discord/webhook.py:84-85`; ticket text never posted — ✅ `discord/webhook.py:60-87`.
  - Channel table (README.md:200-208) — ⚠️ matches `notifications.py:38-57`, but the "assignee left" message (`notifications.py:55-56`) is missing from the table (mentioned only at README.md:273-274).
  - "Retries a few times then shows Last delivery failed" (README.md:215-216) — ⚠️ only for network errors, 429 and 5xx; other 4xx fail immediately (`tasks.py:46-53`).
  - Superusers not pinged, no badge; `view_all` never pinged (README.md:140,150-152) — ✅ `auth_hooks.py:21-23`, `notifications.py:60-89`.
  - Reply rule "only the requester and the current assignee can reply publicly" (README.md:262-263) — ✅ `access.py:127-131`; but "or claims / assigns the ticket to themselves first" is impossible for staff of invited departments, who are collaborators, not controllers (`access.py:134-137`; probe).
  - "Invite department: the invited department can read, reply and write internal notes" (README.md:264) — ❌ invited departments cannot reply since 0.4.0 (`access.py:127-131`; probe: `can_act(reply)` False). Same contradiction in `CHANGELOG.md:13-15` ("helping … departments … claim the ticket or assign it to themselves") and in the design spec (`docs/superpowers/specs/2026-11-14-aa-ticket-design.md:107,133,142,182`).
  - "Assignee leaves … ticket goes back to Unclaimed within five minutes" (README.md:273-274) — ⚠️ true with the README schedule only while there are at most 500 in-progress tickets (`tasks.py:121-125`, see 10.6).
  - Requester who is staff cannot see internal notes / claim own ticket (README.md:271-272) — ✅ `access.py:80-81,88-89`.
  - `pip install …@v0.4.0` (README.md:69) — ❌ tag does not exist.
  - "The first migration creates three priorities" (README.md:130) — ⚠️ it is migration 0002.
  - "*Manage* pages … canned replies" for `manage` (README.md:141) — ⚠️ department staff without `manage` can also manage their departments' canned replies (`views/manage.py:230-278`).
  - "Everything is configured from the Alliance Auth front end; no code or Django admin needed" (README.md:8) — ⚠️ the three permissions still have to be assigned to states/groups in the Django admin, and `local.py` has to be edited.
  - Uninstall step 2 `migrate aa_ticket zero` (README.md:302-305) — ✅ all reverse operations are `noop` or schema operations (5.3). Step 4 deletes content types by `app_label` (README.md:307-312) — ✅ permissions cascade.
  - Data protection "nothing is sent outside your server except the Discord messages" (README.md:280-281) — ✅ with the note that DMs (title + one-line event text) also go to Discord via the bot.
- 9.3 ⚠️ Missing for admins: (a) `Ticket.requester` is `PROTECT` (`models/tickets.py:13`), so users with tickets cannot be deleted and there is no ticket deletion for GDPR erasure; (b) webhook URLs are stored in plain text in the database and its backups; (c) a broker outage drops that event's notifications (6.3.2); (d) the joinable-group warning only covers non-internal groups; auto-assigned groups are only covered by the README text (README.md:146-148); (e) whether helping departments are expected to reply (the 0.4.0 rule means they must ask the assignee or get the ticket transferred).
- 9.4 ✅ English README; Simplified Chinese README (`README.zh-hans.md`, which states the 0.4.0 reply rule correctly at line 16), install and upgrade guides in Chinese.

### 10. Security and operational risks

- 10.1 ✅ All critical logic is inside the app (`access.py` is the single access module, `access.py:1-6`). Discord and aa-discordbot are notification channels only; their failures do not block ticket handling.
- 10.2 ⚠️ Checked: requester identity comes from the session user and main character (`services.py:128-131`); action names whitelisted (`views/ticket.py:21,130-131`); all actions re-checked under `select_for_update` (`services.py:146-153`); internal notes and their images hidden from requesters, also when the requester is staff (`access.py:80-81,88-89`, `views/files.py:17-18`); assignees limited to active staff of controller departments (`access.py:179-188`); category/department/priority validated (`services.py:112-115,319-320,333-334`); ticket text escaped (`templatetags/aa_ticket.py:23-26`; `event_text` is a `simple_tag`, auto-escaped); text stripped of bidi controls and NUL (`services.py:68-84`); uploads verified and re-encoded by Pillow with pixel/frame limits, stored under random names, served with stored MIME type, `nosniff` and `Content-Security-Policy: sandbox` (`attachments.py:50-143`, `views/files.py:22-28`); webhook URLs restricted to Discord (`discord/webhook.py:23-37`); `@everyone` suppressed (`discord/webhook.py:85`). Remaining risks: whoever can join a staff group gets ticket access; `view_all` and superusers see everything.
- 10.3 ⚠️ Only secret: Discord webhook URLs, stored in plain text (`models/config.py:79`), never displayed in full or logged, excluded from admin. They do not expire. Not encrypted at rest.
- 10.4 ⚠️ Row locks via `select_for_update` for every mutating service (`services.py:146-147`), atomic conditional UPDATE for claim (`services.py:201-203`), reminder flags (`tasks.py:104-107`) and assignee release (`tasks.py:132-134`); automatic close re-checks status and `last_reply_by_staff` under the lock (`services.py:357-358`); dispatch only after commit. Remaining races: (a) auto-close does **not** re-check `last_reply_at`, so a staff reply that arrives after `check_auto_close` loaded its batch is closed anyway (probe: closed = True); (b) the open-ticket limit is counted without a lock (`services.py:116-118`), so parallel submissions can exceed it.
- 10.5 ✅ No signal handlers into AA code. No private AA/Django APIs; uses public `MenuItemHook`, `UrlHook`, `DashboardItemHook`, `QueueOnce`, `notify`, `get_extension_logger`. Leading-underscore helpers used across modules are the app's own (`views/staff.py:48`, `tasks.py:101,119`).
- 10.6 ⚠️ No listeners on `EveCharacter`/`User`. Ticket page: `can_act` is evaluated for 12 actions, each walking department ancestors and collaborators without prefetch (`views/ticket.py:46`, `access.py:67-90`) — probe: 45 queries for an assignee on a three-level tree. `_release_departed_assignees` checks only the **first 500 in-progress tickets by primary key** every run (`tasks.py:121-125`); above 500, departed assignees of newer tickets are never released (probe with batch size 3: ticket stays *In progress*), and each run costs about 2–3 queries per in-progress ticket (probe: 50 queries for 21 tickets), i.e. ~1,200 queries every 5 minutes at 500 tickets. The unclaimed and auto-close candidate queries are now filtered so finished tickets drop out (`tasks.py:139-155,200-206`); starvation there only above 500 genuinely pending tickets.
- 10.7 ⚠️ Stored personal data: requester account and main character, all reply/note text, images (EXIF/GPS removed by re-encoding, `attachments.py:98-129`), original file names, names of staff in timeline events (`event_data`), escalation reasons (`models/tickets.py`). Only users with accounts. Sent outside: ticket title, department, category, priority and requester main character name to Discord webhooks (`discord/webhook.py:60-87`), title and event text as DMs via aa-discordbot. No retention for tickets; user deletion blocked by `PROTECT` (`models/tickets.py:13`); erasure needs a manual shell operation.
- 10.8 ⚠️ Traps: (a) staff groups that are open, requestable or auto-assigned (state/corp groups); (b) `MEDIA_ROOT` inside a path served by nginx/Apache (README.md:90-92 warns); (c) nginx `client_max_body_size` (README.md:94-99); (d) forgetting `from celery.schedules import crontab` in `local.py` (not mentioned in README.md:101-116); (e) `SITE_URL` unset gives relative links in Discord (`links.py:6`); (f) aa-discordbot Celery route missing (README.md:230-232). `APPS_WITH_PUBLIC_VIEWS` is not involved.

### 11. Maturity and migration

- 11.1 ⚠️ One author (`yilifaer`), 38 commits between 2026-11-14 and 2026-11-16 (`git log`); developed with AI assistance from a design document and plan committed in `docs/superpowers/`. 334 tests in 27 test modules (`aa_ticket/tests/`), all passing locally on SQLite / AA 5.4.0; CI defined (`.github/workflows/tests.yml`), results not checked. No production track record; four minor versions in three days.
- 11.2 ✅ No predecessor app. Upgrades between the app's own versions are plain migrations (0003 and 0004 add fields and adjust the app's own rows); upgrade notes for 0.3.0 and 0.4.0 exist (`docs/upgrade-0.3.0.zh-hans.md`, `docs/upgrade-0.4.0.zh-hans.md`).
- 11.3 ✅ README uninstall steps (README.md:297-314) cover beat entries, tables (`migrate aa_ticket zero`, reversible, see 5.3), content types by `app_label` (permissions cascade), media files, and warn against `remove_stale_contenttypes --include-stale-apps`. AA's menu sync removes the stale menu item itself (`allianceauth/menu/managers.py:59-61`). AA bell notifications created by the app remain in AA's notification table (harmless).

## 7. Further pitfalls

1. **Staff access = AA group membership.** Anyone in a department's staff group reads all tickets, internal notes and images of that department and every department below it (`access.py:48-60,160-171`). If such a group is open, requestable or an auto group (state/corp), users can give themselves access. Use dedicated closed groups; the department page warns only for non-internal groups (`views/manage.py:73-80`).
2. **No release tag.** README installs `@v0.4.0`, which does not exist; the Chinese guides install from the branch `claude/friendly-einstein-21gzh0` (`docs/install-raspberry-pi.zh-hans.md:76,333,376`, `docs/upgrade-0.4.0.zh-hans.md:34`), a moving target. Tag a release and install by tag or commit hash.
3. **Invited (helping) departments cannot reply and are told to claim, but cannot claim.** `can_act("reply")` allows only requester and assignee (`access.py:127-131`); collaborators are not controllers, so they cannot claim or assign either (`access.py:134-137`), yet the ticket page shows "Claim the ticket to reply to the requester." without a Claim button (`access.py:157`; probe). README.md:264 and `CHANGELOG.md:13-15` describe the opposite. Either fix the text and hint, or decide whether helping departments should be able to reply.
4. **`view_all` and superusers are full controllers of every ticket**, including internal notes and images (`access.py:82-83`).
5. **Broker outage loses the event's notifications.** No HTTP 500 any more (`robust=True`), but a failing `.delay()` aborts `dispatch` before the bell notifications are written (`notifications.py:152-174`; probe).
6. **Assignee release only scans 500 in-progress tickets** ordered by primary key (`tasks.py:121-125`); above that, "back to Unclaimed within five minutes" (README.md:273-274) silently stops for newer tickets (probe). Access is still removed at once.
7. **Auto-close race:** a staff reply arriving while `check_auto_close` processes its batch can be closed anyway, because the re-check under lock ignores `last_reply_at` (`services.py:357-358`; probe).
8. **No ticket retention / erasure;** users with tickets cannot be deleted (`models/tickets.py:13`, `PROTECT`).
9. **Images rely on `MEDIA_ROOT` not being web-served;** the app itself serves them only through the checked view (`views/files.py`).
10. **Webhook URLs in plain text in the DB** (and DB backups).
11. **Assignee who loses only `basic_access` stays assignee** (they are still a controller by group, `access.py:79-84`; `tasks.py:129` does not check `basic_access`), cannot open the ticket and gets no notifications; controllers must reassign (probe).
12. **Open-ticket limit is not race-free** (`services.py:116-118`).
13. **Design spec is stale** on the reply rule (`docs/superpowers/specs/2026-11-14-aa-ticket-design.md:107,133,142,182`); README.md and README.zh-hans.md:16 / CHANGELOG are the reference for 0.4.0.
14. **Repo content addressed to an AI:** `docs/superpowers/plans/2026-11-14-aa-ticket.md:26` and `docs/superpowers/specs/2026-11-14-aa-ticket-design.md:67` contain instructions for the AI that wrote the code (commit attribution rules). They do not address the reviewer and had no effect on this review; reported per checklist rule 0.1.2.

## 8. Conclusion

**Install with conditions** on the target (AA 5.4.0, MariaDB, Redis, aa-discordbot 5.0.1): access checks are central, consistent and re-checked under row locks, there are no public endpoints, no hidden creations, no auto-update, the AA 5.0 floor is now real, and the 334-test suite passes. Conditions: install from a Git tag or the reviewed commit hash `280f5df`, not a branch; link departments only to closed, non-auto groups and give `view_all` sparingly; keep `MEDIA_ROOT` out of the web root; test on the Raspberry Pi instance first (including a broker outage, the uninstall path and how invited departments are expected to work under the 0.4.0 reply rule). Because this is a **self-review**, get an independent review before production, and fix the missing tag, the README/CHANGELOG reply-rule contradiction and the misleading "Claim the ticket" hint for helping departments before recommending the app to others.
