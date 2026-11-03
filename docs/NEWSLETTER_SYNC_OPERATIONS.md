# GetOffDeals Newsletter Synchronization
## Technical Setup, Configuration & Troubleshooting Guide

**Project:** GetOffDeals
**Integration:** Supabase PostgreSQL → GitHub Actions → Resend
**Purpose:** Automatically synchronize confirmed newsletter subscribers and unsubscribe requests.
**Last documented:** October 30, 2026

---

# 1. System Overview

GetOffDeals uses Supabase as its primary newsletter subscriber database, Resend for contact management, and GitHub Actions to execute the synchronization worker.

### System architecture

```text
       GETOFFDEALS WEBSITE
               |
               |
        Subscriber Signup
               |
               v
       SUPABASE DATABASE
               |
       subscribers table
               |
       resend_sync_outbox
               |
               v
        GITHUB ACTIONS
               |
       Python Sync Worker
               |
               v
          RESEND API
               |
               v
      RESEND CONTACTS
               |
               v
    GETOFFDEALS NEWSLETTER
           SEGMENT
```

### Responsibilities

| Component | Responsibility |
|---|---|
| GetOffDeals | Collects newsletter subscriptions and confirmation |
| Supabase | Stores subscriber records and synchronization jobs |
| Outbox | Tracks pending add/unsubscribe operations |
| GitHub Actions | Executes the Python synchronization worker |
| Resend API | Creates contacts and manages segment membership |
| Resend Segment | Groups GetOffDeals newsletter subscribers |

**Important:** Resend webhooks are not required for this synchronization architecture. The worker uses outbound API requests to Resend. Webhooks can be added later for bounce, complaint, and delivery-event tracking.

---

# 2. Supabase Configuration

## 2.1 Primary subscriber table

Database table:

`public.subscribers`

Purpose:
- Stores newsletter subscribers.
- Maintains subscription status.
- Provides the source of truth for consent.
- Determines whether a subscriber can be synchronized.

Relevant statuses:

| Status | Meaning | Synchronize? |
|---|---|---|
| pending | Awaiting email confirmation | No |
| confirmed | Subscriber confirmed consent | Yes |
| unsubscribed | Subscriber withdrew consent | No |

The worker rechecks the subscriber's current status before contacting Resend.

## 2.2 Synchronization outbox

Database table:

`public.resend_sync_outbox`

Purpose:
- Stores contact synchronization jobs.
- Tracks whether jobs are pending, processing, done, or failed.
- Supports automatic retries.
- Prevents the need to rely on a single immediate API request during signup.

Relevant fields:

| Field | Purpose |
|---|---|
| id | Job identifier |
| email | Subscriber email |
| action | add or unsubscribe |
| status | Job processing state |
| attempts | Number of attempts |
| next_attempt_at | Next eligible processing time |
| last_error | Recorded error type |
| created_at | Job creation time |
| updated_at | Last modification time |

Database migrations:

- `migrations/20261028_resend_sync_outbox.sql`
- `migrations/20261028_resend_sync_failed_status.sql`

The failed-status migration extends the permitted outbox statuses to include `failed`.

## 2.3 Inspect the synchronization queue

Run in Supabase SQL Editor:

```sql
SELECT
    id,
    action,
    status,
    attempts,
    last_error,
    next_attempt_at,
    created_at
FROM public.resend_sync_outbox
ORDER BY created_at DESC
LIMIT 10;
```

Interpretation:

| Status | Meaning |
|---|---|
| pending | Waiting for processing or retry |
| processing | Currently claimed by a worker |
| done | Worker completed processing |
| failed | Maximum retry attempts reached |

Important: A `done` status confirms that the worker completed its processing path. It does not independently prove that the contact is visible in Resend.

## 2.4 Check pending jobs and subscriber consent

```sql
SELECT
    o.action,
    o.status AS job_status,
    o.attempts,
    o.next_attempt_at,
    NOW() AS current_time,
    s.status AS subscriber_status
FROM public.resend_sync_outbox o
LEFT JOIN public.subscribers s
    ON LOWER(s.email) = LOWER(o.email)
WHERE o.status = 'pending'
ORDER BY o.created_at DESC;
```

Expected conditions for an add job:

- `job_status = pending`
- `subscriber_status = confirmed`
- `next_attempt_at` is earlier than the current database time.

## 2.5 Check subscriber records

```sql
SELECT
    email,
    status,
    created_at
FROM public.subscribers
ORDER BY created_at DESC
LIMIT 10;
```

Note: The current subscribers table does not have an `updated_at` column. Do not assume it exists when preparing diagnostic queries.

## 2.6 Outbox processing rules

The worker currently uses:

- Batch size: 20 jobs per execution.
- Maximum attempts: 8.
- Processing lease: 15 minutes.
- Exponential retry delay, capped at 360 minutes.

Jobs that are no longer valid because consent has changed are completed without making an inappropriate Resend API request.

---

# 3. Resend Configuration

## 3.1 Resend account

Dashboard:

https://resend.com

Contacts:

https://resend.com/contacts

API Keys:

https://resend.com/api-keys

The GetOffDeals newsletter segment is:

`GetOffDeals newsletter`

Segment ID:

`0e04d901-317d-469a-bdf5-e244f676e5e2`

Keep the segment ID consistent between local configuration and GitHub Actions.

## 3.2 Required API configuration

Two environment variables are required:

```env
RESEND_API_KEY=your_resend_api_key
RESEND_NEWSLETTER_SEGMENT_ID=your_segment_id
```

Never commit `.env` to GitHub.

Never expose API keys in screenshots, terminal output, GitHub issues, or documentation.

## 3.3 Resend API operations

The integration uses these operations:

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/contacts/{email}` | Find an existing contact |
| POST | `/contacts` | Create a new contact |
| POST | `/contacts/{id}/segments/{segment_id}` | Add an existing contact to a segment |
| PATCH | `/contacts/{id}` | Update unsubscribe status |

The contact creation request includes the newsletter segment ID.

Existing contacts are checked before adding them. Resend-side unsubscribes are not silently reactivated.

Adding a contact does not send a newsletter campaign.

## 3.4 Verify a contact through the API

Run locally using the `.env` configuration:

```bash
python - <<'PY'
from dotenv import load_dotenv
import os
import requests

load_dotenv(".env")

email = "your-test-email@example.com"
api_key = os.environ["RESEND_API_KEY"]

r = requests.get(
    f"https://api.resend.com/contacts/{email}",
    headers={"Authorization": f"Bearer {api_key}"},
    timeout=15,
)

print("HTTP status:", r.status_code)
print("Contact found:", r.status_code == 200)
PY
```

This verifies the contact lookup without printing the API key.

## 3.5 Verify segment membership

```python
contact = r.json()

print("Contact ID exists:", bool(contact.get("id")))
print("Unsubscribed:", contact.get("unsubscribed"))

segments = contact.get("segments", [])

print(
    "Segment IDs:",
    [segment.get("id") for segment in segments]
)
```

Expected results for a properly synchronized subscriber:

- Contact ID exists: True
- Unsubscribed: False
- Expected segment ID appears in the contact's segment list.

---

# 4. GitHub Actions Configuration

## 4.1 Repository

GitHub repository:

https://github.com/ritzardB/GetOffDeals

Default branch:

`main`

Workflow file:

`.github/workflows/resend-sync.yml`

## 4.2 Repository secrets

Navigate to:

GitHub → Repository → Settings → Secrets and variables → Actions

The following secrets are required:

| Secret | Purpose |
|---|---|
| DATABASE_URL | Supabase PostgreSQL connection |
| RESEND_API_KEY | Resend authentication |
| RESEND_NEWSLETTER_SEGMENT_ID | Target newsletter segment |

Important:
- Use the connection URI alone for DATABASE_URL.
- Do not include `DATABASE_URL=` in the secret value.
- Do not add surrounding quotation marks.
- Ensure the Resend API key belongs to the account containing the newsletter segment.
- Ensure the segment ID is correct.

If changing an API key, update the GitHub repository secret and rerun the workflow.

## 4.3 Workflow configuration

The workflow is designed to support manual execution and scheduled execution.

The schedule configuration should be:

```yaml
name: GetOffDeals Resend Contact Sync

on:
  workflow_dispatch:
  schedule:
    - cron: "*/10 * * * *"

permissions:
  contents: read

concurrency:
  group: getoffdeals-resend-sync
  cancel-in-progress: false

jobs:
  sync:
    name: Process newsletter sync queue
    runs-on: ubuntu-latest
    timeout-minutes: 10

    env:
      DATABASE_URL: ${{ secrets.DATABASE_URL }}
      RESEND_API_KEY: ${{ secrets.RESEND_API_KEY }}
      RESEND_NEWSLETTER_SEGMENT_ID: ${{ secrets.RESEND_NEWSLETTER_SEGMENT_ID }}

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.13"
          cache: pip

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Run Resend sync worker
        run: python -m getoffdeals.resend_sync_worker
```

Schedule:

`*/10 * * * *`

Meaning: Every 10 minutes, using UTC.

GitHub scheduled workflows can occasionally be delayed. The schedule must be present on the default branch (`main`).

## 4.4 Manual execution

Navigate to:

GitHub → Actions → GetOffDeals Resend Contact Sync → Run workflow.

Select `main` and execute.

To inspect the result:

1. Open the latest workflow run.
2. Select the job named Process newsletter sync queue.
3. Expand Run Resend sync worker.
4. Review the output.

Expected successful log:

```text
INFO:__main__:Resend sync worker processed 1 jobs
```

A result of zero is not necessarily an error.

It means the worker did not find any eligible jobs to process.

---

# 5. Python Synchronization Components

Relevant source files:

| File | Responsibility |
|---|---|
| `getoffdeals/resend_contacts.py` | Resend API communication |
| `getoffdeals/resend_sync_worker.py` | Outbox processing |
| `getoffdeals/database.py` | Supabase PostgreSQL connection |
| `getoffdeals/newsletter_service.py` | Newsletter subscriber and outbox operations |

## 5.1 Contact synchronization logic

For an `add` operation:

1. Worker claims a pending job.
2. Worker checks current subscriber consent.
3. If the subscriber is not confirmed, the job is completed without adding the contact.
4. Worker checks whether the contact exists in Resend.
5. If the contact exists and is not unsubscribed, it is added to the newsletter segment.
6. If the contact does not exist, the worker creates it and includes the segment.
7. Worker marks the job done after successful processing.

For an `unsubscribe` operation:

1. Worker verifies that the subscriber is currently unsubscribed.
2. Worker locates the Resend contact.
3. Worker updates the Resend unsubscribe status.
4. Worker marks the job done.

The system deliberately avoids reactivating previously unsubscribed Resend contacts automatically.

## 5.2 Retry behavior

If a Resend operation fails:

- The worker catches `ResendContactsError`.
- The job is returned to pending or marked failed after eight attempts.
- The error type is stored in `last_error`.
- Retry timing increases progressively.

The worker does not store the raw subscriber email or provider response body in the retry error field.

---

# 6. Issues Encountered and Resolutions

This section records the actual issues encountered during the October 30, 2026 setup.

## Issue 1: GitHub Actions DATABASE_URL error

Error:

```text
psycopg.ProgrammingError:
missing "=" after "***" in connection info string
```

Cause:

The GitHub Actions DATABASE_URL secret was incorrectly formatted.

Resolution:

- Opened GitHub repository settings.
- Updated the DATABASE_URL secret.
- Ensured the secret contained the PostgreSQL connection URI itself.
- Removed unnecessary assignment syntax and quotation marks.
- Reran GitHub Actions.

Result: Database connection succeeded.

## Issue 2: Resend returned HTTP 404

Log:

```text
Resend contact API failed:
method=GET
path=/contacts/...
status=404
```

Initial interpretation:

The contact lookup returned 404.

Important implementation detail:

The current `get_contact()` function interprets HTTP 404 as a missing contact and returns `None`. The add function then attempts to create the contact.

Therefore, a 404 during the initial lookup is not necessarily a fatal error.

However, a subsequent creation failure must be investigated.

## Issue 3: Local and GitHub Resend credentials differed

Local API verification returned:

```text
HTTP status: 200
Contact found: True
```

GitHub Actions previously returned HTTP 404 for the same contact.

Investigation identified the Resend API key configuration as a likely cause.

Resolution:

- Updated the GitHub `RESEND_API_KEY` secret.
- Reran the workflow.
- Confirmed that a new contact appeared in Resend.

Lesson:

Always check that local and GitHub API keys belong to the same Resend account/workspace.

Never print the keys to compare them.

## Issue 4: Contact existed but was not assigned to the newsletter segment

Local verification returned:

```text
HTTP status: 200
Contact ID exists: True
Unsubscribed: False
Segment IDs: []
Expected segment matches: False
```

Interpretation:

The contact existed in Resend but did not belong to the GetOffDeals newsletter segment.

Resolution:

- Investigated the API key and segment configuration.
- Updated the GitHub Resend API secret.
- Generated a new pending outbox job.
- Triggered GitHub Actions again.
- Verified that the contact count increased and the contact appeared in the newsletter segment.

Lesson:

A contact existing in Resend is not the same as being a member of the correct segment.

Always verify segment membership.

## Issue 5: GitHub Actions processed zero jobs

Log:

```text
INFO:__main__:Resend sync worker processed 0 jobs
```

Interpretation:

The worker executed successfully but did not find any eligible pending jobs.

Possible reasons:

- All jobs are already done.
- No pending jobs exist.
- The next retry time has not arrived.
- The worker has no eligible jobs due to subscriber status or retry limits.

Resolution:

Inspected the Supabase outbox.

A subsequent pending, confirmed subscriber job was processed successfully.

## Issue 6: Supabase query referenced a missing column

Error:

```text
ERROR: 42703:
column "updated_at" does not exist
```

Cause:

The diagnostic query assumed the subscribers table had an `updated_at` field.

Resolution:

Removed `updated_at` from the query.

Use the actual subscriber table schema when creating future diagnostic queries.

## Issue 7: Git push rejected

Error:

```text
! [rejected] main -> main (non-fast-forward)
```

Cause:

The local feature branch was used while trying to push to `main`, and local `main` was behind the remote branch.

Resolution:

1. Switched to local `main`.
2. Updated it with:

```bash
git pull --ff-only origin main
```

3. Transferred only the schedule commit using:

```bash
git cherry-pick 08ff605
```

4. Created the new local commit:

```text
02bbbe3 Enable scheduled Resend contact synchronization
```

The next step was to push the updated local `main` to GitHub.

---

# 7. Troubleshooting Decision Guide

Use this section whenever synchronization stops working.

| Symptom | First place to investigate | Likely cause |
|---|---|---|
| GitHub workflow fails at database connection | GitHub Secrets | Invalid DATABASE_URL |
| Worker reports missing configuration | GitHub Secrets | Missing environment variable |
| Resend API returns 401 | Resend API key | Invalid or incorrect key |
| Resend contact lookup returns 404 | Resend Contacts API | Contact may not exist |
| Contact exists but segment is empty | Resend | Segment assignment failed or was never completed |
| Worker processes 0 jobs | Supabase outbox | No eligible pending jobs |
| Job stays pending | Supabase outbox | Future retry time or worker not running |
| Job becomes failed | Supabase outbox | Retry limit reached |
| Workflow succeeds but no contact appears | Resend and Supabase | Check API account, segment ID, and job result |
| Contact is unsubscribed | Resend and Supabase | Respect existing opt-out |
| GitHub workflow does not run automatically | GitHub Actions | Schedule missing from default branch or delayed execution |

## Recommended diagnostic order

Always troubleshoot in this order:

**1. GitHub Actions**

Is the workflow executing successfully?

**2. Supabase**

Is there a pending job? Is the subscriber confirmed? Is the job due?

**3. GitHub Secrets**

Are DATABASE_URL, RESEND_API_KEY and RESEND_NEWSLETTER_SEGMENT_ID configured correctly?

**4. Resend API**

Can the API key retrieve the contact?

**5. Resend Segment**

Does the contact actually belong to GetOffDeals newsletter?

This sequence avoids unnecessary code changes.

---

# 8. Useful Commands

### Check current Git branch

```bash
git branch --show-current
```

### Check working tree

```bash
git status
```

### Inspect workflow changes

```bash
git diff -- .github/workflows/resend-sync.yml
```

### Inspect latest commit

```bash
git log -5 --oneline
```

### Push main

```bash
git push origin main
```

### Run the worker locally

Only do this when the local environment has the correct database and Resend configuration:

```bash
python -m getoffdeals.resend_sync_worker
```

### Run the relevant tests

```bash
pytest -q tests/test_resend_contacts.py tests/test_resend_sync_worker.py
```

The previously recorded full test suite result was:

```text
103 passed
```

---

# 9. Security and Operational Rules

1. Never commit `.env`.
2. Never expose DATABASE_URL or RESEND_API_KEY.
3. Never manually mark an outbox job as done just to clear the queue.
4. Never automatically reactivate a Resend-side unsubscribed contact.
5. Never synchronize a subscriber whose consent is pending or withdrawn.
6. Avoid manually inserting outbox jobs unless following a controlled recovery procedure.
7. Inspect failed jobs before retrying.
8. Keep database migrations under version control.
9. Keep backup files separate from application commits.
10. Test with a controlled subscriber before making changes to the production synchronization logic.

---

# 10. Final Verification Checklist

Use this checklist after deployment or when troubleshooting.

- [ ] Supabase `subscribers` table is accessible.
- [ ] Supabase `resend_sync_outbox` table is accessible.
- [ ] Newsletter migrations have been applied.
- [ ] GitHub DATABASE_URL secret is correct.
- [ ] GitHub RESEND_API_KEY secret is correct.
- [ ] GitHub RESEND_NEWSLETTER_SEGMENT_ID secret is correct.
- [ ] GitHub Actions workflow is present on `main`.
- [ ] Manual workflow execution succeeds.
- [ ] Scheduled execution is enabled on `main`.
- [ ] Confirmed subscribers generate outbox jobs.
- [ ] Pending jobs are processed.
- [ ] Resend contacts are created or updated.
- [ ] Contacts belong to GetOffDeals newsletter.
- [ ] Unsubscribe operations are respected.
- [ ] Failed jobs can be identified and investigated.

---

# 11. Current Project Status and Important Follow-up

As of October 30, 2026:

**Verified during troubleshooting:**
- Supabase database connection was corrected.
- GitHub Actions successfully executed the Python worker.
- Resend API authentication was corrected.
- A new contact was successfully added to the Resend audience.
- The Resend audience showed four contacts.
- The contacts were visible in the GetOffDeals newsletter segment.
- Supabase showed no remaining pending jobs after successful processing.
- The full Python test suite previously passed 103 tests.

**Git status at the last recorded step:**
- Scheduled synchronization commit was cherry-picked onto local `main`.
- Commit: `02bbbe3 Enable scheduled Resend contact synchronization`.
- Local `main` was one commit ahead of `origin/main`.
- The next required operation was:

```bash
git push origin main
```

**Important:** The scheduled workflow should not be considered active until that push succeeds and the workflow file is verified on GitHub's default branch.

---

## Final Architecture Principle

Supabase is the source of truth for subscriber consent.

GitHub Actions is the execution engine.

Resend is the contact and newsletter segment management platform.

The outbox is the synchronization queue.

If something goes wrong, identify which of these four components failed before changing application code.
