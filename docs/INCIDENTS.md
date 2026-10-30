# Incidents and handover

Each runbook lists the first three checks in order, the evidence to read, how to tell causes
apart, an immediate mitigation, and how to verify recovery. Resource names follow the Azure plan.

## A — API starts, but Key Vault access fails

1. **Exact error from the app's first Key Vault call.** Look in Container Apps console logs and
   App Insights exceptions (`exceptions | where outerMessage has "vault"`).
   - `403 Forbidden` + `ForbiddenByRbac` → identity has no role.
   - `401` / `ManagedIdentityCredential authentication unavailable` → wrong or unassigned identity.
   - `ForbiddenByConnection` / `ForbiddenByFirewall` → network.
   - DNS/timeout → private endpoint or DNS.
2. **Identity binding.** `az containerapp show -n triage-api --query identity` should list
   `id-triage-api`, and the app must request a token with that MI's **client ID**
   (`AZURE_CLIENT_ID` env var). A frequent cause is a release that removed the user-assigned
   identity or changed the client ID. Then run
   `az role assignment list --assignee <principalId> --scope <vault id>` and expect
   **Key Vault Secrets User**. Check that the vault is in RBAC mode, not access-policy mode.
3. **Network path.** The vault has public access disabled. From the app's console, run
   `nslookup kv-triage-prod.vault.azure.net`; it must resolve to a **private IP**
   (privatelink zone linked to the VNet). Check the Key Vault diagnostic logs (`AzureDiagnostics |
   where ResourceProvider == "MICROSOFT.KEYVAULT"`) to see whether requests arrive at all
   and with which `identity_claim_oid_g` and `httpStatusCode_d`.
   - If no requests arrive, the problem is network or DNS.
   - If requests arrive with 403, the problem is RBAC.
   - If requests arrive with an unexpected OID, the app is using the wrong identity.
   - Also check whether the secret itself is disabled or expired (`az keyvault secret show`).
   - If the secret is fine, check recent role-assignment changes in the Activity Log.

**Mitigation:** shift traffic back to the previous healthy revision, which still has its
identity and secrets cached. Otherwise restore the role assignment or identity binding through
Bicep, not portal clicks, so it does not drift again. Do not paste secrets into env vars as a
workaround.

**Verify:** the new revision starts. `/health` returns 200. Key Vault logs show 200s for the
app's OID. A smoke triage call authenticates, which proves the API-key pepper loaded.

## B — After a release, latency rises sharply and some requests time out

1. **Correlate with the release.** In App Insights, look at `requests | summarize
   percentiles(duration,50,95,99), count() by cloud_RoleInstance, application_Version,
   bin(timestamp,1m)` and compare the new revision with the old one if traffic is split.
   - If only the new version is slow, the cause is the code or config change.
   - If both versions are slow, the cause is a dependency or load.
2. **Find which dependency got slower.** Look at `dependencies | summarize percentiles(duration,95)
   by target, type`, which covers Postgres, the ERP over VPN, Azure OpenAI, and Key Vault. Also
   check the `triage_log` latency split by `fallback_reason` and `erp_status`.
   - Slow DB: look for a new query without an index, or migration locks
     (`pg_stat_activity`, `pg_locks`, Query Store).
   - Slow model: a prompt grew (`tokens_in` metric), a model or deployment changed, or a
     retry config changed (`LLM_MAX_RETRIES`).
   - Slow ERP: see runbook D.
3. **Resource saturation and config diff.** Check replica count against the max, CPU and memory
   per replica, restarts or OOMKilled, and the Postgres connection count against the limit. Diff
   env vars between revisions (`az containerapp revision show`). Typical regressions:
   - a timeout raised (8 s → 30 s keeps requests in flight longer)
   - the scale rule's `concurrentRequests` changed
   - a sync call placed on the event loop (CPU flat, latency high, low throughput per replica)

**Mitigation:** roll traffic back to the previous revision (instant), and confirm the latency
returns to baseline. If both revisions are affected, temporarily raise max replicas and lower the
model timeout so requests fail fast into the fallback instead of queueing.

**Verify:** p95 is back within baseline for 30 minutes. The 5xx/timeout rate is under threshold.
The fallback rate is normal. Then reproduce the regression in staging with Azure Load Testing
before re-releasing.

## C — The model provider returns intermittent rate-limit errors

1. **Measure the 429s.** Count model calls with 429 against total, by minute, with the
   `x-ratelimit-remaining-tokens` / `-requests` and `retry-after` headers (log them as dependency
   properties). Compare against the deployment's TPM/RPM quota in Azure OpenAI metrics
   (`ProcessedPromptTokens`, `GeneratedTokens`, `RateLimitedCalls`).
   - Token limit hit → prompt size or traffic.
   - Request limit hit → call count.
2. **Find the source of the extra load.** Group APIM and `triage_log` by `retailer` and minute.
   - One retailer bursting → tighten that retailer's APIM rate limit.
   - Overall growth → raise quota.
   - Retry amplification → check whether `LLM_MAX_RETRIES` or the client-side retries changed.
   - Larger prompts → check average `tokens_in` per request since the last release.
3. **Check whether the quota changed.** Look at the deployment's capacity in the portal or with
   `az cognitiveservices account deployment show`, a region-wide capacity incident on the Azure
   status page, and whether another app shares the same deployment.

**Mitigation:**
- Per-retailer throttling in APIM.
- Keep retries at most 1, with `Retry-After` honoured inside the budget.
- Add a second deployment or region to the APIM backend pool, or request a quota increase.
- Temporarily skip the model for fixed acknowledgement replies.
- Affected requests already degrade to the documented fallback, so no wrong advice goes out.
  Tell retailers that the human-review rate is elevated.

**Verify:** `RateLimitedCalls` back near zero, the share of requests with `model.fallback=true`
back to baseline, and token usage inside the quota with headroom (< 70% of TPM at peak).

## D — Spike in `human_review`, audit log shows many ERP timeouts

1. **Confirm the cause in the audit data.**
   `SELECT date_trunc('minute', created_at::timestamptz) m, erp_status, fallback_reason, count(*) FROM triage_log
   WHERE created_at > now() - interval '2 hours' GROUP BY 1,2,3 ORDER BY 1`.
   - If `erp_timeout` explains the extra `human_review`, the ERP is the cause.
   - If `human_review` rose without ERP timeouts, look at discrepancies or the classifier
     (e.g. a new message pattern routing to `other`).
2. **Network or ERP?** Check VPN Gateway metrics (tunnel `TunnelIngressBytes`, tunnel status,
   `TunnelEgressPacketDropCount`) and the ERP adapter's dependency telemetry (connect time vs
   time-to-first-byte).
   - Tunnel down, or connect failures → network. Check the on-prem firewall and the gateway's
     IKE logs.
   - Connects succeed but responses are slow → the ERP itself is slow (batch jobs, DB locks).
     Ask the ERP team for their server metrics for the same minutes.
   - Only `-TIMEOUT`-style refs, or a single retailer → data-specific.
3. **Are we overloading it?** Compare ERP request rate and concurrent connections (per replica ×
   replicas) against the agreed limit. Also check whether a recent scale-out multiplied
   connections, or retries amplified load. Check whether the circuit breaker opened.

**Mitigation:**
- Lower the per-replica ERP concurrency cap, or cap max replicas, so we stop amplifying.
- Let the circuit breaker short-circuit to the fallback so callers get fast answers instead of
  2 s timeouts.
- Coordinate with the ERP team, or fail the VPN over to the secondary tunnel.
- Do **not** raise the ERP timeout or bypass the ERP using client facts. Orders must not be
  decided on unverified data.
- Once the ERP is back, re-run the affected tickets. The audit rows list `request_id`/`ticket_id`
  with `fallback_reason='erp_timeout'`.

**Verify:** `erp_status='timeout'` back to baseline (< 0.5%), `human_review` share back to its
normal level, ERP p95 back under 500 ms, VPN tunnels healthy, and the replayed tickets processed.
