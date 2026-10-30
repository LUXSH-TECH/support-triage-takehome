# Incident Runbooks

All examples assume structured logs include timestamp, environment, revision, request ID,
dependency name, outcome, and duration. They must not include API keys, customer messages,
order references, or connection strings.

## A. API starts but Key Vault access fails

1. Check the failing secret reference and exact Key Vault HTTP status in Container Apps
   revision logs. A 403 points to authorization; 404 points to a wrong vault/secret name
   or version; DNS/timeout points to network/private endpoint resolution.
2. Check the Container App system-assigned principal ID and Key Vault diagnostic audit
   event for that principal, secret URI, operation, and denial reason. Compare the
   deployed revision's vault URI and secret-reference version with the approved
   environment configuration; do not print secret values.
3. Check Key Vault RBAC assignment scope/role and the Container Apps environment's private
   DNS zone, route, and firewall logs. A successful DNS resolution plus 403 distinguishes
   RBAC from networking; no resolution or a connection timeout distinguishes private
   endpoint/DNS issues.

Mitigation: restore the last known valid secret reference or narrowly grant the app
identity the required `get` permission at the intended vault scope; do not enable broad
access policies. Recovery: restart/roll a revision only after secret resolution succeeds,
verify readiness and `/health`, then confirm a non-sensitive authenticated smoke request
and a successful Key Vault audit event for the expected principal.

## B. Latency rises and requests time out after release

1. Compare Application Insights request duration, dependency duration, timeout rate, and
   p50/p95 by Container Apps revision. A single slow dependency identifies the path;
   uniform slow spans suggest CPU, thread, or connection-pool saturation.
2. Compare the new revision's CPU/memory, replica count, restart/OOM events, queueing,
   SQL connection waits, and ERP/model dependency spans to the prior revision. Check
   release timestamp, image digest, timeout settings, and concurrency limits.
3. Inspect dependency-specific evidence: SQL pool checkout and query duration; ERP
   request latency/timeouts and open connections; model provider latency/429/5xx; and
   outbound DNS/TLS errors. Increased CPU with short dependency spans differs from a
   provider/ERP dependency regression.

Mitigation: stop traffic promotion and route back to the previous healthy revision; if a
single dependency is responsible, lower concurrency or activate its bounded fallback
while preserving caller-visible behavior. Recovery: deploy the fix, run health and
authenticated smoke tests, then observe at least one representative traffic window with
stable p95, timeout/error rates, and dependency pool utilization before promotion.

## C. Intermittent model-provider rate limits

1. Inspect model dependency spans grouped by HTTP status, provider request ID, deployment,
   and timestamp. Confirm 429 response headers such as retry-after and quota/reset hints;
   do not log prompts or authorization headers.
2. Compare request/token rate by model deployment and tenant against configured quota,
   concurrent requests, and retry count. A 429 with exhausted quota differs from 401/403
   credential errors and 5xx provider availability errors.
3. Check recent traffic/scale changes, prompt/token-size distribution, provider deployment
   configuration, and whether another service is sharing the quota. Confirm application
   retries are bounded and not amplifying load.

Mitigation: preserve the human-review fallback, apply per-tenant throttling/backpressure,
and honor provider retry-after only within the request deadline; request quota increase or
shift to an approved deployment if available. Recovery: verify 429 rate returns to baseline,
provider latency remains within timeout, fallback rate falls, and audit rows still capture
all fallback outcomes without message content.

## D. Human review spikes with ERP timeouts

1. Query audit counts by decision/fallback and ERP timeout count/latency by minute and
   app revision. Verify the spike aligns with ERP timeout failures rather than a model or
   classifier change.
2. Inspect ERP adapter dependency spans by operation/status, gateway/VPN health, DNS/TLS,
   ERP connection count, pool wait, and ERP-side availability/maintenance events. Compare
   successful versus timed-out request duration and upstream status.
3. Check recent network, firewall, credential rotation, ERP deployment, concurrency, and
   timeout configuration changes. A quick failure with DNS/connect errors indicates path
   or auth; long requests ending at the configured deadline with saturated ERP pools
   indicate capacity or ERP slowness.

Mitigation: keep the bounded `human_review` fallback, reduce ERP concurrency to protect the
legacy system, and notify support operations that verified order lookups are degraded. Do
not substitute client-supplied facts. Recovery: confirm ERP health with an approved
non-sensitive probe, verify timeout and pool-wait rates return to baseline, test a known
fixture-equivalent order through the adapter, and confirm triage decisions and audit rows
recover without leaking tenant data.