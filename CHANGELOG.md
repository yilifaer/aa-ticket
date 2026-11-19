# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.0.1]

Fixes from the AA App Checklist review of 1.0.0. One database migration
(`0006_submit_restriction_and_hourly_limit`): run `migrate`.

### Added

- System check `aa_ticket.W003` warns when one of the three periodic tasks is missing from
  `CELERYBEAT_SCHEDULE`; `aa_ticket.W004` warns when `SITE_URL` is not set.
- Management command `aa_ticket_erase_user <username> [--yes]` erases one person's ticket data:
  their tickets and images are deleted, and other tickets no longer name them (found by user ID,
  so older main characters are covered; nothing is changed by matching text). The account must be
  deactivated first. Afterwards it can be deleted in Alliance Auth.
- Setting *New tickets per person per hour* (default 5, `0` = no limit), so one person cannot
  ping a department over and over.

### Changed

- *Maximum image size* is limited to 6 MB. Older settings above that are treated as 6 MB. The
  recommended nginx `client_max_body_size` is now `32m` (five images of 6 MB).
- A Discord direct message that cannot be sent (bot error, missing Celery route) is logged as a
  warning instead of info.
- Submissions limited to some states or groups stay limited when all of them are deleted:
  nobody can submit then (before, the department silently opened up to everyone), and the
  department list shows a warning. Existing departments with such limits are marked by the
  migration.
- The staff group warning also covers groups that members of a state join automatically.
- Messages whose author account was deleted or erased show *Deleted user* instead of *System*.
- Opening the preferences page no longer creates a database row; images are cached by the
  browser for 5 minutes instead of an hour.
- CI also tests Python 3.11, Alliance Auth 5.2 and MariaDB with Alliance Auth 5.0.

### Documentation

- Uninstalling: delete the three `aa_ticket_*` periodic tasks that Celery Beat keeps in the
  database.
- Updating: back up first; how to go back to the previous version.
- Permissions: `view_all` and `manage` also need `basic_access`; `manage` decides who can read
  which tickets; department staff manage their own canned replies without `manage`.
- Data protection: which names go to Discord; webhook URLs are stored in plain text; how to erase
  one person's data.
- The default priorities ping and remind as soon as a department has a webhook: check them first.
- Screenshots in both READMEs.
- The Chinese installation guide is now `docs/install.zh-hans.md` and no longer specific to a
  test machine. Internal review notes, design and planning documents were removed.

## [1.0.0]

First stable release. The code is the same as 0.4.7; only the version number and the
documentation changed. No database changes.

### Documentation

- Install from the version tag (`@v1.0.0`). The installation guide no longer installs from a
  development branch, and the upgrade guides for the 0.x test versions were removed: upgrade
  from any 0.x version with the steps under "升级" in `docs/install.zh-hans.md`.

## [0.4.7]

Change from the 0.4.6 test round. No database changes.

### Changed

- Animations (GIF, WEBP) may have at most 25 megapixels across all frames together (was 100).
  A 4-frame 5000 × 5000 animation took about 860 MB of memory on a Raspberry Pi. The refusal
  message now says that the animation as a whole is too large, gives the number of frames and
  the frame size, and suggests fewer frames or a smaller size.
- Only GIF and WEBP count as animations. Phone photos that carry a hidden extra picture (MPO:
  HDR gain map, depth map) and animated PNGs are saved as their first picture only, so only that
  picture is checked against the 25 MP limit. Without this, ordinary 12 MP phone photos were
  refused as "animations".

## [0.4.6]

Changes from the 0.4.5 test round. No database changes.

### Changed

- The image limit is back to 25 megapixels for every format. Decoding a 100-megapixel PNG took
  about 1 GB of memory and 17 seconds on a Raspberry Pi. Images within the limit whose longer
  edge is above 4096 pixels are still scaled down to 4096 pixels.
- Discord messages show the department and the assignee as they were when the event happened,
  not when the queued message is finally sent. Messages queued by an older version still look
  up the current state.
- The auto-close notice on the ticket page shows the exact EVE time on hover.

## [0.4.5]

No database changes.

### Added

- Every Discord message (channel and direct message, including the test message) ends with a
  small footer line, always in English:
  `This was a Ticket Bot Notice from <sender> to <recipient> at 2026-11-15 11:03:28 EVE`.
  The sender is the person who caused the message, or `Alliance Auth` for new tickets and
  automatic messages; the recipient is the department (channel) or the person (direct message);
  the time is when the event happened.

## [0.4.4]

Changes from the 0.4.3 test round. No database changes.

### Changed

- Large images are no longer refused: an image whose longer edge is above 4096 pixels is scaled
  down to 4096 pixels when it is saved (metadata is still removed). Only images above
  100 megapixels are refused, with a message that names the limit.
- Discord direct messages show the department and the assignee as extra fields (never the
  message text).
- All times are labelled "EVE" (EVE time is UTC): message times, the sidebar, the hover text in
  lists and on the dashboard card, and the last webhook error on the department page.
- The daily clean-up of unreferenced image files is more careful: it only runs when files are
  stored on the local disk, skips a linked `aa_ticket` folder and linked files, and only removes
  files with the names this app gives (32 hex characters and an image extension).
- "Close ticket" on the ticket page has red text: dark red on light themes, light red on dark
  themes.

### Fixed

- Only people who can handle a ticket (active, with `aa_ticket.basic_access`, in a responsible
  department) are offered in *Assign* and can be assigned.
- Fixed colour pairs (at least 4.5:1) for yellow, red, grey and blue notices and for red and grey
  buttons, on the ticket pages and on the dashboard card, in all themes and states.

### Documentation

- Changes to permissions and groups reach the dashboard card within 30 seconds and the menu
  badge within 60 seconds.

## [0.4.3]

Fixes from the 0.4.2 test round. No database changes.

### Fixed

- Dashboard card: refreshed for the previous assignee after a reassignment or transfer; one cache
  entry per language, so switching languages cannot keep old numbers alive.
- Requesting escalation a second time always says which department was already asked, also when
  there is no further level; a changed department number in the request no longer reveals the
  name of other departments.
- Reopening a ticket whose assignee has left the department puts it back to *Unclaimed*.
- Image files written by an action that fails afterwards are removed again; the daily clean-up
  task also deletes files no ticket refers to (older than one day).
- The hourly limit for "requester added a reply" channel notices is only used when a message is
  really sent, and released when sending fails.
- Singular/plural wording for "open ticket(s)" messages (all languages, Russian plural forms).
- Contrast of at least 4.5:1 through fixed colour pairs for the yellow "internal note" and
  "unclaimed" marks, grey labels, all priority marks, the urgent mark, "waiting for you", the
  Claim and escalation buttons and the outline buttons on the ticket page — at rest, on hover
  and with keyboard focus. Measured in the Flatly, Darkly, Bootstrap and Bootstrap Dark themes.
  (In the Materia theme the theme's own primary buttons remain white on blue, 3.1:1.)
- Reopening a ticket whose assignee had to be removed also tells the department channel.
- Image files of a saved ticket or reply are never removed by a failure that happens after the
  database commit.
- Spanish: "Responsable" for assignee everywhere. Chinese: one term, 申请上级介入, for
  escalation (the automatic one is 自动申请上级介入).

### Changed

- Channel messages are only queued for departments that have a webhook.

## [0.4.2]

### Added

- When the requester adds a reply to a ticket nobody has claimed yet, the department channel gets
  a short message (no role mention, at most once an hour per ticket).
- Workbench filter by category; "My tickets" is paginated (50 per page).
- The Alliance Auth dashboard card is cached for 30 seconds and refreshed when a ticket changes.

### Changed

- A priority that open tickets still use cannot be deactivated; department names must be unique;
  deleting a category says that its tickets lose the category.
- The query behind all ticket lists no longer needs DISTINCT over a join (faster with many tickets).
- After a transfer the old department's menu badge is refreshed at once.
- Accessibility: dialogs are labelled, the current tab is marked, symbol-only cells have text.
- The navigation highlights the current area on the submit and ticket pages.
- Chinese: "Invite department" is 邀请协作 as in the glossary; the statistics column for closed
  tickets has its own text in every language.

### Internal

- Tests against the real aa-discordbot package, a concurrent claim test on MariaDB, a test for
  migration 0004, and CI checks for the built package and for migration drift.
- The source distribution includes CHANGELOG and both READMEs.

## [0.4.1]

Fixes from a whole-app review. No behaviour of the 0.4.0 reply rule changes.

### Fixed

- Requesting escalation twice in a row (double click) no longer skips a level.
- Transferring without "keeps helping" sends you to the workbench instead of a "not found" page,
  and departments that only joined through an escalation leave the ticket too.
- Helping departments get a correct hint (they write internal notes; they cannot claim).
- A rejected reply keeps the text you typed. Actions on a ticket that changed meanwhile show a
  message instead of an error page.
- Tickets go back to *Unclaimed* also when the assignee was deleted, deactivated or lost access;
  all in-progress tickets are checked, and the auto-close clock restarts.
- Auto-close re-checks under lock that nobody replied meanwhile; unclaimed reminders are skipped
  if the ticket was transferred meanwhile.
- Notifications: one failing recipient or a short broker outage no longer drops the remaining
  Alliance Auth notifications; reasons are not sent to the task broker; a Discord read timeout is
  not retried (avoids duplicate posts).
- Images: processed before the ticket is locked and decoded less often, limit 25 megapixels,
  no leftover files when one image of a message fails, JPEG/GIF comments removed, phone
  "MPO" photos accepted.
- Nobody can reopen a ticket of an inactive department.
- Pages: submit form shows priority/category errors, hint when a ticket can no longer be reopened,
  Invite/Transfer hidden when there is no other department, category templates switch with the
  category, keyboard-reachable image picker, readable version label, stable list ordering.
- Workbench no longer fails on absurdly long numbers in filters.

### Added

- Database indexes for the closed tab and the periodic tasks (migration 0005).

## [0.4.0]

### Changed

- **Only the requester and the current assignee can reply publicly.** Other staff (colleagues,
  helping and parent departments, `view_all`) can write internal notes; they claim the ticket or
  assign it to themselves to reply. The ticket page explains this and offers the Claim button.
  Only the requester and the assignee can add a final reply when closing.
- The version is shown next to "Tickets" in the page header.
- Urgent tickets carry one red "urgent" badge, whatever colour the priority has.
- The workbench "Helping" tab and the overview use the same rule for shared/escalated tickets.

### Fixed

- Overview: "waiting for you" ordering matches the badge; `view_all` users without departments
  see their assigned tickets; no extra queries per listed ticket.
- Department management: tree indentation when parents are inactive, "No active departments"
  message, readable "no player tickets" badge.
- Internal note header readable in dark themes; larger tap targets on phones.
- German and Russian wording for "unclaimed", Chinese text for empty escalations.

## [0.3.0]

### Added

- Overview page as the plugin's start page: players see their open tickets (waiting for them
  first); officers also see tickets assigned to them, unclaimed tickets of their departments
  (urgent first, with a Claim button) and tickets escalated or shared with their departments.
- Card on the Alliance Auth dashboard with ticket counts, urgent unclaimed tickets and the most
  recent tickets.
- "Counts as urgent" switch on priorities (migration flags the existing "Urgent" priority).

### Changed

- Inactive departments are folded on the management page.
- Warnings on the management pages use normal text with a coloured icon, readable in dark themes.

## [0.2.0]

### Added

- Setting for the language of Discord channel messages (English by default) and whether direct
  messages follow each person's language or the channel language.
- Tickets go back to *Unclaimed* when the assignee leaves the department.
- Assignees are notified when the requester closes or reopens a ticket and when a colleague replies.
- Warning on the department pages when a staff group can be joined or requested by anyone.

### Changed

- All translations use the context `aa_ticket`, so other apps can no longer override them.
- Uploaded images are re-encoded: EXIF/GPS metadata and trailing data are removed.
- The app is shown as "Tickets" in the admin (no version number); `view_all` is now called
  "Can view and handle all tickets".
- Management pages also require `basic_access`.
- Transfer and reopen restart the auto-close timer; transfer clears the category.

### Fixed

- Invalid or inactive categories, unicode digits in workbench filters, own tickets in the
  sub-departments tab, reopening tickets of inactive departments, misleading escalation message,
  duplicate notifications when closing with a final reply, untranslated breadcrumb label.
- Text input: zero-width-only text is rejected, bidirectional control characters and NUL are
  removed, replies are limited to 10,000 characters.
- Attachments are served with `Content-Security-Policy: sandbox` and their original file name.
- `aa_ticket.W002` warns when `MEDIA_ROOT` does not exist or is not writable.

## [0.1.0]

### Added

- Departments with parent departments, staff groups, Discord webhook and roles to mention.
- Priorities with role mentions, unclaimed reminders and escalation to the parent department.
- Categories per department with optional text templates.
- Ticket conversation with replies, internal notes and image attachments.
- Claim, assign, invite department, transfer, request escalation, close and reopen.
- Automatic close of tickets waiting for the requester, with a warning; reminders for tickets waiting for staff.
- Alliance Auth notifications and optional Discord direct messages through aa-discordbot.
- Staff workbench, statistics, canned replies and management pages in the front end.
- Translations: English, Simplified Chinese, German, Russian, Spanish.
