# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
