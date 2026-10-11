# User Registration & Profile System

A complete sign-up, profile and account-security module for Dynamic CuroBase. It sits **on top of**
the existing Flask/vanilla-JS architecture, reuses the existing `users` table, permission matrix and
SQLite database, and changes no attendance, timetable or portal feature.

---

## 1. What was built

### Sign up (`/` → "Create an account")
Full name, unique username, unique e-mail, optional mobile, password + confirmation, optional date of
birth, preferred language, optional country, and an explicit Terms/Privacy consent checkbox.

* Validated in the browser **and** on the server (the browser is never the authority).
* Show/hide toggle on both password fields.
* Passwords are hashed with PBKDF2-HMAC-SHA256; the plaintext is never stored, logged or echoed back.
* Duplicate username / e-mail / mobile are each reported against their **own** field. `users.phone`
  has carried a unique index since before this feature, so a duplicate mobile used to surface as a
  misleading "username taken" — that is now an explicit check plus an `IntegrityError` handler that
  maps the constraint name back to the right field.
* Registration cannot set `role`, `status` or `permissions`. They are simply never read from the
  payload.

### Complete Your Profile (skippable onboarding)
A five-step wizard — Identity, Details, Preferences, Social links, Review. Every field except what
sign-up already collected is optional, and the whole screen can be dismissed. Progress and "what's
still missing" are shown as a checklist.

### My Profile (profile dashboard)
Avatar, cover, display name, username, account status, completion ring, and the actions a person
actually needs: Edit Profile, Change Photo, Change Password, Account Settings, Privacy Settings,
Notification Settings, Language and Log out. Role-appropriate context is added underneath — a parent
sees their linked children, a student sees attendance stats **only** because the server authorised
that student, a teacher sees their classes.

### Edit Profile
Loads every current value, Save / Cancel, server-side validation, persisted across sessions. Updates
go through an explicit column allowlist (`_PROFILE_TEXT` / `_PROFILE_ENUM` / `_PROFILE_FLAGS`), so
`role`, `permissions` and `status` are unreachable from this endpoint by construction, not by filter.

### Account / Privacy settings
Session list with real `auth_epoch`, "sign out all other devices", notification toggles, accessibility
toggles, theme, visibility (private / school / public), what-is-shown flags, and a password change
that requires the current password first.

### Account deletion
**Request only.** A user files a request; an admin approves or rejects it. Approving suspends the
account's ability to sign in — it never deletes attendance records, marks or timetable history.

### Public profile
`GET /api/profile/public/<username>` returns a record only when that account's `visibility` is
exactly `public`. There is **no** directory or search endpoint, so students cannot be enumerated.

---

## 2. Design decisions worth knowing

| Decision | Rationale |
|---|---|
| **Registration creates `status='pending'`** and issues no session | A school cannot let strangers pick a role. The office approves and assigns the role in the existing Users screen. |
| **No SMTP exists, so nothing claims e-mail is sent** | Verification and reset tokens are stored **hashed** in `password_reset_tokens` with `kind='verify'`/`'reset'`, and surfaced to an admin (or returned to the caller only when `PROFILE_DEV_TOKENS=1`). No message says "check your inbox". |
| **`PROFILE_DEV_TOKENS` defaults to OFF** | A default of "on unless production" leaks reset links on a single missing env var. It must be switched on deliberately. |
| **Password policy applies to *new* passwords only** | The current password is verified **before** the strength check, so a user changing to a weak password gets a strength error, not an auth error. |
| **Password *change* does not bump `auth_epoch`** | Otherwise the device that just changed its password would be signed out by its own request. An explicit "sign out other devices" control covers the rest. Password **reset** (via token) does bump it. |
| **Profile completion = exactly 5 signals × 20%** | Photo, display name, bio, interests, one social link. Deliberately non-personal fields — nobody is nudged to disclose their date of birth to "complete" an account. |
| **CSRF strategy is `SameSite=Lax` + `Content-Type: application/json`** | Every mutating endpoint reads a JSON body, so a cross-origin HTML form cannot forge one. Documented rather than sprinkled with tokens the SPA would have to thread through. |
| **Public registration cannot assign a role** | Not filtered after the fact — the fields are never read. |

---

## 3. Files changed

| File | Change |
|---|---|
| `app.py` | Schema + additive migrations, 13 new routes, password policy, profile/photo/session/deletion logic, `users` create validation |
| `frontend/index.html` | `#signupForm`, `#resetForm`, `#view-editprofile`, `#view-accountsettings`, `#view-privacy`, `#view-onboarding` |
| `frontend/app.js` | Profile module (sign-up, reset, dashboard, edit, settings, privacy, onboarding) + `VIEW_ROLES` / `VIEW_LABELS` / `VIEW_ICONS` / `MORE_ITEMS` / `navigate()` entries |
| `frontend/portal.js` | `LOGIN_CARDS` extended with signup/reset; `forgotPassword()` opens the reset card; `loadProfileView` moved to `app.js` |
| `frontend/style.css` | Section 17: profile, registration and account styles, mobile breakpoints, print rules |
| `frontend/sw.js` | Cache key `dynamic-curo-v5` → `dynamic-curo-v6` |

`frontend/icons.js` was **not** hand-edited (generated). No new dependency was added and no existing
route changed its URL.

---

## 4. New API surface (13 routes)

| Method + path | Who |
|---|---|
| `POST /api/auth/register` | public |
| `POST /api/auth/verify-email` | public (single-use token) |
| `POST /api/auth/forgot-password` | public (never reveals whether an account exists) |
| `POST /api/auth/reset-password` | public (single-use token) |
| `GET` / `PUT /api/profile` | signed in |
| `POST` / `DELETE /api/profile/photo` | signed in |
| `POST` / `DELETE /api/profile/cover` | signed in |
| `GET /api/profile/sessions` | signed in (own sessions only) |
| `POST /api/profile/logout-others` | signed in |
| `GET` / `POST /api/profile/delete-request` | signed in (own request) |
| `GET /api/profile/public/<username>` | public, `visibility='public'` only |
| `POST /api/users/<id>/token` | admin only (mints a sign-in token for support) |
| `GET` / `POST /api/account-deletions` | admin only (review queue) |

Existing routes that were extended, not replaced: `POST /api/auth/change-password` (now enforces the
strength policy), `POST /api/users` (admin "add user" now validates username, `role ∈ ROLES`, and the
same password policy).

---

## 5. Database migrations

Additive only, run automatically by `init_db()` on startup, and safe to run repeatedly. **The
production database is never reset.**

New columns on the existing `users` table (existing rows keep their values; new columns have safe
defaults so nothing else in the app changes):

| Column | Default |
|---|---|
| `email` | `''` |
| `phone` | `''` |
| `status` | `'active'` |
| `email_verified` | `0` |
| `updated_at` | `NULL` |
| `auth_epoch` | `0` |

New indexes:

```sql
CREATE UNIQUE INDEX IF NOT EXISTS ux_users_email ON users(email) WHERE email <> '';
CREATE UNIQUE INDEX IF NOT EXISTS ux_users_phone ON users(phone) WHERE phone <> '';
```

Both are **partial** indexes on purpose: legacy rows all hold `''`, and a plain `UNIQUE` would make
every legacy account collide with every other one. The partial form gives uniqueness for real values
and ignores empty ones.

New tables:

* `user_profiles` — 1:1 with `users` (`user_id UNIQUE`), `ON DELETE CASCADE`. Display name, bio,
  photo, cover, DOB, gender, pronouns, country, city, language, interests, theme, `socials` (JSON),
  four notification flags, two accessibility flags, visibility + three "show" flags, audit columns.
  **No auth secret lives here** — no password, no token, no session id.
* `password_reset_tokens` — `user_id`, `token_hash`, `kind`, `expires_at`, `used`, `created_at`,
  `ON DELETE CASCADE`. Only a **hash** of the token is stored.
* `account_deletion_requests` — request, status, reason, admin decision columns,
  `ON DELETE CASCADE`.

A backfill creates a `user_profiles` row for every existing user that lacks one, so no endpoint has
to handle "profile not found yet".

### Rollback

None of the pre-existing tables are modified beyond `ALTER TABLE ... ADD COLUMN`, and no existing
column is dropped or redefined, so rolling back is simply deploying the previous commit. To remove
the feature's own objects (nothing else references them):

```sql
DROP TABLE IF EXISTS account_deletion_requests;
DROP TABLE IF EXISTS password_reset_tokens;
DROP TABLE IF EXISTS user_profiles;
DROP INDEX IF EXISTS ux_users_phone;
DROP INDEX IF EXISTS ux_users_email;
-- optional: restore the original column set
ALTER TABLE users DROP COLUMN auth_epoch;
ALTER TABLE users DROP COLUMN updated_at;
ALTER TABLE users DROP COLUMN email_verified;
ALTER TABLE users DROP COLUMN status;
ALTER TABLE users DROP COLUMN phone;
ALTER TABLE users DROP COLUMN email;
```

`ALTER TABLE ... DROP COLUMN` needs SQLite 3.35+. Leaving the columns in place is harmless — they
are ignored by the previous commit.

Do **not** drop `users`; that is the pre-existing table everything else reads.

---

## 6. Security

* **Authorisation on every endpoint.** Everything sits behind the existing default-deny `/api/*`
  guard. `GET /api/profile` is **not** in the public allowlist, so an anonymous caller gets 401.
* **No mass assignment.** Profile updates iterate an explicit allowlist; `role`, `permissions` and
  `status` are not in it. Sign-up never reads them from the payload either.
* **No IDOR.** Sessions, deletion requests and profile rows are always filtered by the session's own
  `user_id`; an admin-only route checks `can(...)`. Public profiles resolve by exact username and
  honour `visibility='public'`.
* **No public student search.** There is no directory endpoint — only the exact-username lookup.
* **Uploads.** JPEG/PNG/WebP only, checked by **magic bytes** rather than the client's `Content-Type`
  or the filename extension. Oversized files are refused. Filenames are generated by the server from
  a random token — the client never supplies a path, so path traversal has nothing to traverse into.
  Executables are rejected even if renamed to `.jpg`. Images are re-encoded on resize.
* **Stored XSS.** Social links must match `^https?://`, which blocks `javascript:` and `data:` URIs.
  Everything rendered passes through `esc()`/`escAttr()`.
* **SQLi.** Every value is a bound parameter; no user input is interpolated into SQL.
* **Passwords** are PBKDF2-HMAC-SHA256 with `PW_ITERATIONS` (default 390000) and a per-user salt.
  Passwords and tokens are never written to any log.
* **Sessions.** `HttpOnly`, `SameSite=Lax`, a 12-hour lifetime, and `Secure` whenever
  `FLASK_ENV=production` (local HTTP dev is unaffected). `auth_epoch` lets an account invalidate
  every other device at once.
* **Rate limiting** on sign-up, login, forgot-password and reset.
* **No stack traces or DB errors are shown to users** — the client gets a friendly message; details
  stay server-side.

---

## 7. Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `ATTENDANCE_SECRET` | **yes, in production** | a built-in dev fallback | Flask session signing key |
| `PROFILE_UPLOAD_DIR` | no | `data/photos` | Where profile images are written |
| `PROFILE_DEV_TOKENS` | no | **off** | `1` returns verification/reset tokens in the API response. Dev only. |
| `PW_ITERATIONS` | no | `390000` | PBKDF2 iterations |
| `ALLOWED_ORIGINS` | no | (existing) | CORS origins — unchanged by this feature |

No new secret, no new third-party service, no credential is committed to the repository.

### Where photos are stored — and why `render.yaml` has no disk stanza

`PROFILE_UPLOAD_DIR` defaults to `data/photos` — **the same directory the attendance database and the
pre-existing student photos already live in**. So by default profile photos have exactly the same
persistence characteristics as the records that are already surviving in production, and existing
student photos are untouched.

A `disks:` stanza was deliberately **not** added to `render.yaml`. Attaching a disk mounts a *fresh,
empty* volume at a new path; pointing `PROFILE_UPLOAD_DIR` (or worse, the database) at it would hide
the existing data and look exactly like data loss. If you want a mounted disk:

1. Attach the disk in the Render dashboard **first** and note its mount path.
2. Copy the existing contents of `data/` into it (do not simply repoint).
3. Then set `PROFILE_UPLOAD_DIR` to the copied location.
4. Verify with a real `GET /api/health` **and** by confirming existing attendance records and photos
   are still present, before treating the change as done.

---

## 8. Setup / deployment

1. Deploy as usual — `render.yaml`, `wsgi.py` and the start command are unchanged.
2. Set `ATTENDANCE_SECRET` in the environment (it is already `sync: false` in `render.yaml`).
3. The migration runs automatically on first boot and is idempotent. Nothing manual is required.
4. Confirm `GET /api/health` answers `200` unauthenticated.
5. Approve sign-ups in **Users** — a registration creates `status='pending'`; the office sets the
   role and flips it to active. The account cannot sign in before that.
6. Returning users get the new assets immediately: the service worker is network-first with a cache
   fallback, and its cache key was bumped to `dynamic-curo-v6` so the previous `index.html`,
   `app.js`, `style.css` and `portal.js` entries are purged on activate.

### Verification tokens — what is actually shown

This application has **no SMTP or SMS gateway**. A verification/reset token is therefore:

* generated server-side, stored **hashed** (`password_reset_tokens.token_hash`) with a TTL and
  single-use flag, and
* shown **only** to an administrator, or returned in the API response when `PROFILE_DEV_TOKENS=1`.

No UI ever claims "we've sent you an e-mail". When a real mail service is added, the token already
exists and is already single-use — only the delivery step needs writing.

---

## 9. Tests

| Suite | Result |
|---|---|
| `test_profile.py` (new) | **169 / 169** |
| `test_portal.py` (regression) | **55 / 55** |
| `test_attendance.py` (regression) | **42 / 42** |
| `test_timetable.py` (regression) | **96 / 96** |
| `test_rbac.py` (regression) | all expectations pass |
| `smoke_http.py` vs a real server | **51 / 51** |
| `check_wiring.py` (static UI wiring) | **43 / 43** |
| `check_frontend.py` (CSS/HTML/JS balance) | clean |
| `jscheck.py` (JS tokenizer) | `app.js`, `portal.js` OK |
| `py_compile app.py` | clean |

`test_profile.py` covers registration validation and uniqueness (username, e-mail **and** the
pre-existing phone index), pending-accounts being unable to sign in, admin approval and role
assignment, e-mail verification (single-use, garbage token), profile read/write, completion
percentage, mass-assignment denial, photo upload (magic bytes, oversize, path safety, delete, cover),
password change, forgot/reset (no account enumeration, token single-use, policy checked before the
token is burned), session revocation, public-profile privacy, deletion requests and admin decisions,
admin token minting, an RBAC sweep over every new route, and migration idempotency.

`smoke_http.py` repeats the core flow over a real socket — served assets, anonymous 401s, sign-up,
pending-refused, duplicate, admin approval, sign-in, profile edit, mass-assignment and cleanup —
because the test client cannot prove the browser receives the new page.

Language names are covered explicitly in every script (`हिन्दी`, `বাংলা`, `اردو`, `English (US)`)
plus a rejection case for markup. This is a regression test for a real bug: a `\w`-based regex
rejects Devanagari because Python's `\w` is built from `str.isalnum()` and Devanagari vowel signs and
viramas are category `Mn`/`Mc`, not alphanumeric — so a perfectly ordinary language name was being
refused with "letters only".

---

## 10. Known limitations

* **No e-mail/SMS delivery** (see §8). Verification and reset links are admin/dev-displayed only.
* **Rate limits are in-process.** `_LOGIN_ATTEMPTS` and `_API_HITS` are module-level dicts, and
  production runs `gunicorn --workers 3`, so each worker counts separately — the effective limit is
  roughly three times the configured one, and counters reset on restart. This stops naive scripted
  abuse; it is not a distributed defence. A shared store would be needed for one global budget.
* **Registration is not self-approval.** Every account waits for an administrator. There is no
  invitation link or e-mail-domain rule yet; the `status` column supports both if they are added.
* **Account deletion is a request, not a deletion.** An admin decides, and the destructive step (if
  any) is manual. Attendance and marks are never touched by this flow.
* **Photos are stored on local disk**, not object storage. On a platform without a mounted disk they
  behave exactly like the existing database and student photos — whatever persists today persists
  for these too.
* **Public profiles are lookup-by-exact-username only.** There is intentionally no directory, so
  "find my teacher's profile" requires knowing the handle.
* **Profile completion never requires personal data** — by design it cannot reach 100% for someone
  who declines to share a bio or social link.
