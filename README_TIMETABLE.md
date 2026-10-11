# Timetable Management System

A weekly timetable module for Dynamic CuroBase. It sits **on top of** the existing
Flask/vanilla-JS architecture and reuses the existing school, teacher, student,
class, section, subject, academic-session, holiday and notification records.
No attendance feature was changed.

---

## 1. What was built

### Admin
* Create / edit / publish / archive / delete timetables for any class + section.
* Weekly grid editor with day, start, end, subject, teacher, room, type and status per cell.
* Periods, breaks, lunch and assembly are all first-class rows.
* School-day settings: opening time, closing time, timezone, working days, default period length.
* Duplication **from a day → other days**, **from a week → another draft**, and **from a week → another class**.
* Publish with an effective date; every publish/edit/duplicate/archive/substitution is written to an
  append-only change history.
* Optional note attached to a publish, shown to recipients.

### Teacher
* "My Timetable" — every period they are assigned to, across all their classes.
* Today's periods with subject, class, section, room and time.
* A live "Now" highlight computed in the school's configured timezone.
* Approved substitutions shown in place of the normal teacher.

### Student & Parent
* The timetable of the student's assigned class and section, derived from the database link —
  never from the query string.
* Parents with several children can pick which child to view; the server verifies the link.
* Today strip (current period, next period, holiday), weekly grid, breaks, cancellations,
  approved substitutions.
* PDF download and print (print stylesheet included).

### Conflict detection (server-side authority)
Checked on every save, publish and duplication. Nothing is written when a blocking conflict exists.

| Code | Blocks |
|---|---|
| `invalid_time` | unparseable times, or end <= start |
| `outside_hours` | a period outside the configured school day |
| `bad_day` / `non_working_day` | unknown weekday (blocking) / non-working weekday (warning only) |
| `unknown_subject` / `unknown_teacher` | a reference that no longer exists |
| `class_overlap` | two cells covering the same minutes — this also catches "two subjects in one period" and "period vs break" |
| `teacher_conflict` | a teacher booked in two classes at the same time |
| `room_conflict` | a room double-booked across classes |
| `duplicate_slot` | the same day + start twice in one payload |

The browser may pre-warn, but it is never the authority.

---

## 2. Design: versions, not in-place edits

A `timetable_versions` row is **a whole week for one class + section**, live from an `effective_from`
date. `timetable_slots` holds the individual cells.

Published timetables are **never edited in place**. An admin forks a draft, edits it, then publishes.
That is what makes the change history truthful, and why `DELETE` on a published version is refused
(archive instead).

The live timetable for a class on a given date is the published version with the latest
`effective_from <= date`.

---

## 3. Files changed

| File | Change |
|---|---|
| `app.py` | Schema + migrations, RBAC entry, conflict detection, all timetable routes, teacher-account linking (`PUT /api/teachers/<id>`), legacy `/api/timetable` rewired to the new model with role scoping |
| `frontend/index.html` | New `#view-timetable`: filters, today strip, weekly grid, and Edit / Settings / History tabs |
| `frontend/style.css` | `.tt-*` design-system styles, mobile breakpoint, `@media print` block |
| `frontend/app.js` | New timetable module (grid, editor, duplicate, publish, settings, history, PDF/print). `api()` now attaches `status` and the parsed `body` to thrown errors so conflict lists can be rendered |

Nothing else changed. `frontend/icons.js` was **not** hand-edited (generated).

---

## 4. Database migrations

Additive only, run automatically by `init_db()` on startup. **The production database is never reset.**

New tables:

* `timetable_versions` — session, class, section, name, status, `effective_from`, parent, audit columns
* `timetable_slots` — version, day, start, end, name, kind, subject, teacher, substitute, room, status, cancel reason, notes
* `timetable_settings` — open/close time, timezone, working days, period length (per class+section or school-wide)
* `timetable_changes` — append-only history
* `timetable_substitutions` — one row per slot per concrete **date**

New indexes:

* `ux_ttslot (version_id, day, start_time)` — one cell per time
* `ix_ttslot_day`, `ix_ttslot_teacher`, `ix_ttslot_sub`
* `ix_ttver_class`
* `ux_ttset (session_id, COALESCE(class_id,-1), COALESCE(section_id,-1))`
* `ux_ttsub (slot_id, date)`
* `ix_ttchg`
* `ux_ttver_pub ... WHERE status='published'` — at most one published version per effective date

Two safety migrations were added alongside:

1. **`academic_sessions` is seeded if empty.** `timetable_versions.session_id` has a real foreign key
   to it, so a database created before that table existed would reject every timetable insert.
2. **One-time import of the legacy flat `timetable` table.** Runs only when legacy rows exist *and*
   `timetable_versions` is still empty, so it can never duplicate on a later restart. Rows whose
   `period_time` cannot be parsed are skipped and counted in a `timetable_changes` entry rather than
   silently dropped. The legacy table is kept read-only as the archive of what was imported.

`COALESCE` is used in the unique indexes because SQLite treats `NULL`s as distinct in `UNIQUE`
constraints — the same trap that previously produced duplicate attendance rows.

### Rollback

The new tables are not read by any pre-existing feature, so rolling back is simply deploying the
previous commit. Optionally clean up (safe, nothing else references them):

```sql
DROP TABLE IF EXISTS timetable_substitutions;
DROP TABLE IF EXISTS timetable_changes;
DROP TABLE IF EXISTS timetable_slots;
DROP TABLE IF EXISTS timetable_versions;
DROP TABLE IF EXISTS timetable_settings;
DROP INDEX IF EXISTS ux_ttver_pub;   -- etc.
```

Do **not** drop `academic_sessions`, `holidays`, `subjects`, `teachers`, `classes` or `sections` —
those are pre-existing tables the module only reads.

---

## 5. Reused, not duplicated

| Existing record | Reused for |
|---|---|
| `academic_sessions` | academic year selector |
| `classes` / `sections` | class + section pickers, Classes 1–12 and configured sections |
| `subjects` | subject assignment (subject colour is derived from a hash of the name, so there is nothing to configure) |
| `teachers` | teacher assignment; `teachers.user_id` is the link to a login |
| `students`, `parent_students`, `users.linked_student_id` | deciding what a student/parent may see |
| `holidays` | holiday strip on the schedule |
| `notifications` | in-app notification on publish |
| `reportlab` (already a dependency) | PDF export |

---

## 6. Environment variables

**None.** The feature introduces no new configuration and no new dependencies
(`reportlab` and `zoneinfo` are already in use). Timezone comes from
`timetable_settings.timezone` (default `Asia/Kolkata`).

---

## 7. Setup / deployment

1. Deploy as usual — `render.yaml`, `wsgi.py` and the start scripts are unchanged.
2. The migration runs automatically on first boot. Nothing manual is required.
3. In **Timetable → Settings**, set the school opening/closing time, timezone and working days.
4. **Link staff accounts.** A teacher's "My Timetable" resolves through `teachers.user_id`, which is
   not populated by the seed. An admin can link it in the Teachers screen
   (`PUT /api/teachers/<id>` with `user_id`). An account may only be linked to a staff record whose
   role is `teacher`, and one account cannot be linked twice.
5. Build each class's week in **Timetable → Edit**, then **Publish** with an effective date.

### Notifications — what is actually sent

Publishing inserts rows into the existing in-app `notifications` table for the administrators, the
teachers scheduled in that version, the students of that class/section, and their parents.

**This application has no SMS, e-mail or WhatsApp gateway.** The publish response therefore reports
exactly what happened and claims nothing else:

```json
{"notifications": {"created": 42, "channel": "in_app",
                   "external_channels": [], "external_sent": false,
                   "note": "In-app notifications only. This app has no SMS, e-mail or WhatsApp gateway configured."}}
```

The `whatsapp_groups` table stores group *links* only — it is not a sending service.

---

## 8. Security

* Every route is behind the existing default-deny `/api/*` guard and the `timetable` RBAC entry
  (`admin: full`; teacher/student/parent: view only).
* Editing, publishing, archiving, deleting, settings, history and substitutions are **admin only**,
  enforced on the server.
* Students and parents cannot choose their own class: it is derived from the database link, so a
  hand-crafted `?class_id=` cannot widen access. `student_id` is verified against the parent's
  linked children.
* Teachers may read only classes they are actually scheduled in; an unlinked teacher account gets an
  honest empty state rather than someone else's week.
* Published versions cannot be edited or deleted (409) — duplicate or archive instead.
* All names pass through `esc()`/`escAttr()` in the frontend (stored XSS), and every value is a
  bound SQL parameter (SQLi). There is no mass assignment: writes go through explicit column lists.
* The versions listing, change history and substitution audit are admin-only, so schedule metadata
  is not exposed to students.

---

## 9. Tests

| Suite | Result |
|---|---|
| `test_timetable.py` (new) | **96 / 96** |
| `test_attendance.py` (regression) | **42 / 42** |
| `test_rbac.py` (regression) | all expectations pass |
| `check_live_tt.py` (live HTTP) | **28 / 28** |
| `jscheck.py` (JS tokenizer) | `app.js`, `portal.js`, `icons.js` OK |

The timetable suite covers settings validation, version CRUD, every conflict code, the
"nothing is written on conflict" guarantee, publish + double-publish refusal, published-version
immutability, day/week/class duplication (including staff-clearing and `keep_teachers` clashes),
change history, substitutions (weekday match, distinct substitute, duplicates, reject/delete,
approved-only visibility), PDF magic bytes, and the role matrix — student/parent IDOR scoping,
teacher class restriction, unlinked-teacher behaviour, and anonymous 401s.

### Known limitations

* Substitutions are assigned by an administrator. There is no teacher self-service request/approval
  workflow (the `status` column supports it if one is added later).
* Notifications are in-app only (see §7).
* Teachers must be linked to a staff record by an admin before "My Timetable" shows anything.
* The weekly grid is a fixed Monday–Saturday shape; a Sunday-school timetable needs `working_days`
  plus a UI tweak.
* Cross-class duplication deliberately clears teachers and rooms, because a copied teacher could
  never validate against the source class. Pass `keep_teachers: true` to opt out — conflicts are
  then checked as normal.
