# AI coding agent instructions for this repo

Use these repo-specific notes to be productive quickly. Keep changes small, align with conventions below, and validate with fast Django runs.

## Big picture
- Django 5 project (`expense_project`) with a single app `expenses` implementing expense application + approval workflow.
- DB: MySQL (internal LAN server) via `PyMySQL` shim, credentials hardcoded in `settings.py` (host `172.16.100.150`). Same DB used for local dev and production.
- Static files served by WhiteNoise and Apache aliases; media files under `BASE_DIR/media`. In dev, media is served when `SERVE_MEDIA` true.
- Auth uses custom user `expenses.M_User` and a custom backend `expenses.auth_backends.ManNumberModelBackend` enabling login by employee number.
- Workflow engine: `T_WorkflowInstance`, `T_WorkflowAction`, `M_WorkflowStep` tied to `T_Document`. Steps/candidates are built via `utils.steps_with_candidates`.

## Key files
- `expense_project/settings.py`: env-driven config (DEBUG, SERVE_MEDIA, EMAIL_*), static/media, CSRF trusted origins, custom auth model/backend. MySQL connection is hardcoded (not env-driven).
- `expense_project/urls.py`: routes app and accounts; conditionally serves media in dev.
- `expenses/urls.py`: main feature routes (`home`, `new`, `list`, `detail`, `edit`, approvals).
- `expenses/views.py`: core flows for create/edit/submit/cancel and workflow actions. Uses formsets and attachments.
- `apache/expense_project2.conf` + `apache/README.md`: mod_wsgi deployment, venv path, static/media aliases, enable steps.
- `build.sh`: installs deps, collectstatic, migrate, then runs two custom management commands: `superuser`, `load_initial_master`.

## Run and validate
- Local dev quick start:
  - Ensure the internal LAN MySQL server (`172.16.100.150`) is reachable.
  - Migrate and create initial data via `./build.sh` or `python manage.py migrate` + `python manage.py load_initial_master`.
  - Run server: `python manage.py runserver`.
- Static/media:
  - `python manage.py collectstatic` writes to `static/` (served by WhiteNoise/Apache). Media under `media/` and optionally served when `SERVE_MEDIA` is true.
- Deployment (Apache/mod_wsgi): follow `apache/README.md`; verify logs at `/var/log/apache2/expense_project2_error.log`.

## Conventions & patterns
- Templates live under `BASE_DIR/templates` and app templates under `expenses/templates/expenses/...`. Use Japanese labels/messages; `LANGUAGE_CODE='ja'` and `TIME_ZONE='Asia/Tokyo'`.
- Formsets for document details: `ExpenseDetailFormSet` (create) and `ExpenseDetailEditFormSet` (edit). Attachments handled via `T_DocumentAttachment` with file inputs named `{form.prefix}-receipt`.
- Document state codes: `M_Status.status_cd` values like `SUB` (submitted), `DRA` (draft), `RET` (returned), `CAN` (cancelled). Submissions create or update `T_WorkflowInstance` and append `T_WorkflowAction`.
- Dynamic fields for `DocType=4`: definitions in `M_DocumentField`; render inputs using `field_type` (text/number/date/select:<DATA_KBN>) and store as JSON in first detail's `content`.
- Approver candidates API: `expenses.views.approver_candidates` returns approver options driven by department (`M_Bumon`) and workflow step logic.
- Email: internal SMTP at `172.16.100.243:25` without AUTH by default. `EMAIL_FORCE_TO` used in dev to pin recipients.
- CSRF/Reverse proxy: `SECURE_PROXY_SSL_HEADER` and `USE_X_FORWARDED_HOST` enabled; trusted origins include the internal IP.

## When adding features
- Respect custom auth model `expenses.M_User` and backend; use `login_required` on views.
- Use existing status codes and workflow tables when changing document lifecycle. Create `T_WorkflowAction` entries on significant transitions.
- Follow template structure and Japanese copy; wire new routes in `expenses/urls.py` and include under root.
- Prefer env vars for behavior (DEBUG, SERVE_MEDIA, EMAIL_*); avoid hardcoding secrets.
- Validate currency codes (`M_Item` with `data_kbn='CUR'`) and default to `'00'` when available.

## Examples
- Serving media in dev: guarded by `settings.SERVE_MEDIA` in `expense_project/urls.py`.
- Submitting an edit (`views.expense_edit`): sets status to `SUB`, creates `T_WorkflowInstance` if absent, and logs `T_WorkflowAction`.
- Cancelling a submitted request (`views.expense_detail` POST `cancel_expense`): set status to `CAN` and append workflow action.

## Gotchas
- `build.sh` expects custom management commands (`superuser`, `load_initial_master`) present under `expenses/management/`; ensure they exist before running.
- MySQL connection settings are hardcoded in `settings.py`; edit that file directly if the internal host/credentials change.
- Attachments must be removed before deleting details to maintain referential integrity (see edit flow).
