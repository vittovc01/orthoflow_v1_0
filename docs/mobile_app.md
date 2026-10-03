# OrthoFlow mobile

A dedicated installable web application (PWA) for couriers and agents. The desktop stays on Streamlit. This is not an App Store / Play Store native package.

## Included workflows

- Approved `utenti_app` username/password login, using the same PBKDF2 hash as desktop. No hardcoded emergency admin fallback. Each authenticated request reloads current role, active state and password fingerprint.
- Role-aware Home and persistent bottom navigation, dedicated OF icon, installation instructions for Safari/Android. The mobile interface does not load Streamlit chrome, Fork or GitHub links.
- Couriers: own missions only, structure details, GPS on explicit stamp, multiple photos, private signed archive links, uploaded washing/decontamination certificate plus touch signature, completion with explicit with/without-signature choice.
- Agents: only clients whose `clienti.agente` matches `utenti_app.agente_nome`; OCR of multiple photos/PDFs, manual rows, instant delete/code/lot/quantity edits, manual J&J verification, nonsterile lotless confirmation, Excel export.
- Server-side offer/history pricing with punctuation-insensitive lookup while preserving the original code. Missing prices remain provisional. Manual price entry is restricted to management/administration. Malzoni `9010013` structure-stock rows keep revenue and skip own stock debit through the existing RPC.
- Scarico writes use the same transaction/RPC and reintegration records as desktop; source documents go to existing `documenti_impianto`/Storage. No duplicated operational archive.

## Run locally

```
python -m pip install -r requirements-mobile.lock
export MOBILE_LOCAL_DEV=true
export MOBILE_PUBLIC_ORIGIN=http://localhost:8000
uvicorn mobile.app:app --host 127.0.0.1 --port 8000
```

Set server-side environment variables `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`; never put the service key in frontend files or GitHub. Set `OPENAI_API_KEY`, `ENABLE_AI_OCR=true`, and the same `OPENAI_VISION_MODEL` used by the desktop. Apply `sql/mobile_operations.sql` after the existing OrthoFlow schema/migrations. Login does not work for the old hardcoded emergency admin: create/approve a normal management user with Users & Permissions if necessary.

## Publish

Hosting/domain is not yet selected. The repository includes a provider-neutral Dockerfile and a separate optional `render-mobile.yaml`; neither creates a paid service automatically. Community Cloud runs the desktop, and cannot run this FastAPI service alongside it.

1. Choose hosting supporting the Docker container or Python ASGI, with HTTPS and a stable public origin.
2. Run the mobile SQL after reviewing it against the current Supabase schema. New functions use `SECURITY INVOKER`; EXECUTE is denied to anon/authenticated/PUBLIC and allowed only to service_role. The idempotency table has RLS and no public policies/grants. All mission actions recheck the supplied server-authenticated user and lock the mission before changing mission, stamp, kit and history together.
3. Set `MOBILE_PUBLIC_ORIGIN=https://your-mobile-domain` exactly; it is required for same-origin POST validation. Leave `MOBILE_LOCAL_DEV=false` in production. Set `ORTHOFLOW_DESKTOP_URL` to the actual HTTPS desktop address.
4. Set `GIT_SHA` to the deployed commit (Render supplies `RENDER_GIT_COMMIT`). `/health` reports this version.
5. Configure GitHub repository variable `MOBILE_PUBLIC_URL` to that HTTPS origin. Workflow **Verifica app pubblicata** waits for both a 200 response and the expected deployed commit after a successful CI push to main, or a successful GitHub deployment event for `orthoflow-mobile`. It can also run manually. Until the variable is configured, its job is skipped; skipped is not a successful availability verification.
6. Enable automatic deployment on that branch or emit a deployment event from the chosen platform. A failed health run signals a release that is unavailable or still serving the previous version. It does not roll back automatically.
7. On iPhone: Safari → Share → Add to Home Screen; on Android: browser → Install app. Verify camera, GPS, uploads and signature on actual phones with a test mission before rollout.

`python scripts/check_deployment.py --kind streamlit --url https://actual-desktop-origin --timeout 60` additionally checks the desktop's `/_stcore/health`; this proves reachability only, not a commit version. Configure `DESKTOP_PUBLIC_URL` to the verified desktop origin for the separate PC health job, triggered manually or after a successful GitHub deployment event in `orthoflow-desktop`. The selected hosting pipeline must emit that event. No desktop address is assumed valid from an old Render configuration.

## Sessions and connectivity

Opaque random session tokens are hashed in server-side SQLite, expire in 12 hours and are carried only in Secure HttpOnly SameSite=Strict cookies. Password changes and account disablement invalidate access on the next request. SQLite shares sessions and login limits between workers on one container. For multiple container replicas, use a shared session store before scaling; this release is designed for one container with multiple workers. With ephemeral storage, restart requires a new login; operational data remain in Supabase. `MOBILE_DATA_DIR` can point to a persistent volume if the selected plan supports it.

Only public shell assets are cached. Clinical documents, API data and signed URLs are not cached by the service worker and are not saved in browser localStorage. Writes require connectivity; this release does not queue stock operations offline. Draft rows and selected files remain in memory while navigating, and disappear on browser reload/logout. Keep the scarico screen open during OCR.

## Tests

CI runs API authorization/session/file validation and real Chromium mobile navigation/editing tests with synthetic data. SQL tests use a disposable PostgreSQL instance and verify atomic/idempotent stamps/completion and scarico, rollback, Malzoni, nonsterile lotless stock, manual-price history and denial of public RPC execution. No production users/passwords or medical records are used. OCR calls are not made during CI; actual recognition still needs document review. `/health` proves service/version availability, not the full Supabase/OCR business workflow.
