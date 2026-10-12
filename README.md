# Custody Band Monitoring API

A modular FastAPI backend using Firebase Authentication and Cloud Firestore.
It includes user profiles and roles, device inventory and assignment, gated
simulated location ingestion, latest/history APIs, circular geofences, alert
acknowledgement, reporting endpoints, and an authenticated WebSocket handshake.
The actual C05 hardware protocol is not implemented.

## Requirements

- Python 3.12 or newer
- Windows PowerShell

## Set up

From the project folder, run:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

If PowerShell blocks virtual-environment activation, allow it for the current
terminal with `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, then
activate the environment again.

## Run the API

```powershell
uvicorn app.main:app --reload
```

Open Swagger UI at <http://127.0.0.1:8000/docs> or ReDoc at
<http://127.0.0.1:8000/redoc>.

The health endpoint is `GET /api/v1/health`. Authenticated profile endpoints are
available at `GET /api/v1/auth/me`, `GET /api/v1/users/me`, and
`GET /api/v1/users` (super-admin only). Liveness and readiness are
`GET /api/v1/health/live` and `GET /api/v1/health/ready`.
For example:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
```

`/health` reports API and Firebase status. Liveness does not depend on Firebase;
readiness checks Firestore availability.

## Run tests

With the virtual environment active:

```powershell
pytest
```

The tests use Firebase mocks and do not require live custody data, Firebase
credentials, or a physical device.

## Configuration

Application settings can be changed in `.env` or through environment variables.
The `.env.example` file contains only non-secret local development values. Do
not commit `.env` files or Firebase credentials.

### Firebase setup

To connect the FastAPI backend to Firestore, set these values in `.env`:

```dotenv
FIREBASE_PROJECT_ID=your-project-id
# Optional: use a rotated key stored outside this repository.
FIREBASE_CREDENTIALS_PATH=C:/secure/firebase-service-account.json
# optional for the Firestore emulator
FIREBASE_EMULATOR_HOST=localhost:8080
SIMULATED_INGESTION_ENABLED=false
DEVICE_ONLINE_TIMEOUT_SECONDS=300
OFFLINE_DEVICE_WORKER_ENABLED=false
OFFLINE_DEVICE_SCAN_INTERVAL_SECONDS=60
LOW_BATTERY_THRESHOLD=20
TRIP_IDLE_GAP_SECONDS=1800
TRIP_MIN_DISTANCE_METERS=100
NOTIFICATION_MODE=mock
```

The backend also supports Google Application Default Credentials. For local
development, configure ADC with `gcloud auth application-default login`; on
Google Cloud, use the runtime service account. Alternatively, set
`GOOGLE_APPLICATION_CREDENTIALS` or `FIREBASE_CREDENTIALS_PATH` to a protected
service-account file. The Firebase project ID is `update-custody-band-backend`
for this deployment.

If Firebase settings or credentials are missing, the health endpoint reports
that Firebase is not configured. Protected routes fail closed and are only
available when valid Firebase credentials are provided.

**Credential rotation:** a service-account key was uploaded in the project
conversation. Treat that key as compromised: revoke it in Google Cloud IAM,
create a replacement, store the replacement outside this repository, and set
`FIREBASE_CREDENTIALS_PATH` to the new file. Never commit or upload the key.
The repository ignores typical Firebase service-account filenames.

### Provision user profiles

Users sign in through Firebase Authentication in the frontend. The frontend
must send the resulting Firebase ID token to this API as:

```http
Authorization: Bearer <Firebase-ID-token>
```

For every request, the backend verifies the token (including revocation status)
and then loads the user's profile from Firestore at `users/{firebase_uid}`.
Roles come only from this server-managed Firestore profile; a role or UID sent
by the client is never trusted.

Create each profile in the Firebase Console under Firestore Database, in the
`users` collection, with the document ID set to the user's Firebase Authentication
UID. Example fields:

```json
{
  "display_name": "Example Officer",
  "email": "officer@example.com",
  "role": "operator",
  "tenant_id": "tenant-001",
  "is_active": true
}
```

Supported current roles are `super_admin`, `admin`, `supervisor`, `operator`,
and `viewer`. Legacy role values from the earlier project phase remain accepted.
Accounts must be active. Keep role assignment restricted to trusted
administrators; no client-facing endpoint lets a user create or promote their
own profile.

`GET /api/v1/users/me` returns only the caller's authorized profile.
`GET /api/v1/users?limit=50` lists at most 100 profiles and requires the
`super_admin` role. Use Swagger UI's **Authorize** button with a Firebase ID
token to try these routes.

## API scope

- Devices: register, list, get, update, soft-deactivate, status, assign, and
  unassign. Assignment records require a corresponding `persons/{person_id}`
  Firestore document in the same tenant. Device groups and validated
  configuration metadata are tenant-scoped.
- People: create and list reference records using an authorized alias; legal
  names and sensitive identity fields are not exposed by these endpoints.
- Administration: super-admin tenant creation and user role changes; scoped
  audit-log reads and per-user notification preferences.
- Locations: simulated ingestion is disabled unless
  `SIMULATED_INGESTION_ENABLED=true`; simulated heartbeat, battery, SOS, and
  tamper event ingestion is available at `/api/v1/ingestion/simulated/events`.
  Live/latest/history/playback/status
  endpoints are tenant-scoped. History is paginated and playback is bounded to
  500 points over a maximum 90-day range.
- Geofences: circular and closed polygon zones. Polygon rings are bounded,
  non-zero-area, non-self-intersecting, and antimeridian crossings are rejected.
  A point too close to a boundary relative to its reported accuracy does not
  trigger an entry/exit event.
- Alerts: list, get, acknowledge, and resolve; simulated events can create SOS,
  tamper, low-battery, and geofence transition alerts. The battery threshold is
  configurable and no physical-device signal is inferred.
- Reports: device status, alert date range, location history, trip records, and
  device assignments. Alert CSV export is bounded to 500 records. Management
  users can rebuild trips from a 90-day window of up to 500 chronological points;
  idle-gap and minimum-distance thresholds are configurable.
- Management: super-admin tenant creation and user role changes; tenant-scoped
  device groups and audit logs; per-user notification preferences; validated
  device configuration metadata.
- WebSocket: `/api/v1/ws/tracking` authenticates a token sent in the first
  WebSocket JSON message (`{"token":"..."}`), checks the active user profile
  and tenant, supports ping/pong heartbeats, and receives tenant-scoped
  location/offline events. The connection manager is single-process only.
  Multi-instance deployment needs a Redis Pub/Sub fan-out keyed by tenant; each
  API process should publish sanitized device events and forward only to local
  sockets subscribed to that tenant.
- Offline detection: set `OFFLINE_DEVICE_WORKER_ENABLED=true` to schedule the
  in-process scanner. It marks up to 150 stale devices per scan, creates an
  offline alert, and writes a mock notification-delivery record. Leave this
  disabled when running multiple API replicas; use a single worker instance.
- Notifications: a provider interface and mock delivery records are present.
  Set `NOTIFICATION_MODE=mock` in development; mock records are disabled outside
  development/test environments. Email, SMS, and push providers are not
  connected, and preferences do not yet deliver messages to recipients.

Physical-device ingestion and SOS/tamper event adapters are not implemented.
No C05 protocol or tracking capability is assumed; the supported simulated
events are explicitly marked `source=simulated`.

## Project layout

```text
custody-band-backend/
|-- app/
|   |-- main.py
|   |-- config.py
|   |-- firebase.py
|   |-- dependencies.py
|   |-- exceptions.py
|   |-- middleware/
|   |-- api/v1/
|   |   |-- auth.py
|   |   |-- users.py
|   |   |-- devices.py
|   |   |-- device_groups.py
|   |   |-- management.py
|   |   |-- persons.py
|   |   |-- assignments.py
|   |   |-- tracking.py
|   |   |-- ingestion.py
|   |   |-- geofences.py
|   |   |-- alerts.py
|   |   |-- reports.py
|   |   |-- health.py
|   |   `-- router.py
|   |-- schemas/
|   |-- services/
|   |-- repositories/
|   |-- models/
|   |-- device_integrations/
|   |-- websockets/
|   |-- workers/
|   `-- utils/
|-- tests/
|-- scripts/
|-- firebase.json
|-- firestore.indexes.json
|-- Dockerfile
|-- docker-compose.yml
|-- requirements.txt
`-- README.md
```

## Firestore collections and operations

Implemented records use UTC timestamps. Location events are stored at
`devices/{device_id}/locations/{event_id}`; `latest_locations/{device_id}` is
the single latest point and is updated only by a newer device timestamp.
`device_status/{device_id}` tracks receipt time, connectivity, battery, and
last location. Device and person assignments are retained in
`device_assignments`; device records are soft-deactivated.

The API also uses `users/{firebase_uid}`, `tenants/{tenant_id}`,
`persons/{person_id}` (reference number and authorized alias only),
`device_groups/{group_id}`, `geofences/{geofence_id}`,
`geofence_states/{device_id}_{geofence_id}`, `alerts/{alert_id}`,
`audit_logs/{audit_id}`, `notification_preferences/{uid}`, and
`notification_deliveries/{delivery_id}`. The `trips` collection is populated
by the bounded management rebuild endpoint. `device_events` and command records
are reserved for a verified device protocol and are not currently written.

Deploy the composite indexes from `firestore.indexes.json` before using the
tenant scoped alert, geofence, trip, offline status, audit, and assignment
queries. Location queries are device-subcollection queries with a bounded
90-day range and at most 500 returned points per request. No automatic location
TTL or backup policy is configured: set retention, scheduled exports, and
restore drills in the Firebase/GCP project to match your legal and operational
requirements. Firebase Admin uses privileged server credentials, so enforce
least-privilege IAM and keep production credentials out of the repository.

To use the Firebase Emulator Suite, set `FIREBASE_EMULATOR_HOST=127.0.0.1:8080`
and `FIREBASE_AUTH_EMULATOR_HOST=127.0.0.1:9099`, then start the Firestore/Auth
emulators using the repository's `firebase.json`. Keep emulator and production
project IDs separate. `/api/v1/health/live` is process liveness;
`/api/v1/health/ready` checks Firebase readiness without returning credential
details.

Assignment endpoints are implemented in `app/api/v1/assignments.py`. Some
existing route modules still call Firestore directly; the repository layer has
not yet been applied uniformly across the API.
