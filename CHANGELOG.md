# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
