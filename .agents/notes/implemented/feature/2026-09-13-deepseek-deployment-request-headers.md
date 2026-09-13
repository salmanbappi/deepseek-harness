# Agent Note: Deployment request headers for the DeepSeek adapter

Status: implemented

English | [中文](2026-09-13-deepseek-deployment-request-headers.zh.md)

## Problem

Some OpenAI-compatible gateways admit only clients they recognize and answer every other `User-Agent` with HTTP 401, so a deployment cannot reach the models behind them. AgentRouter is one: `deepseek-harness/<version> (+<url>)` and `curl` both receive 401 `unauthorized client detected`, while `cline/3.5.0` receives 200. `dsh-llm-pi-ai` provider profiles already carry a `headers` map for such gateways; `dsh-llm-deepseek` had no equivalent, so the `deepseek-official` route could not be pointed at one, and the in-history system prompt capability that route declares for its catalog stayed unreachable behind that gateway.

## Decision

`dsh-llm-deepseek` accepts `headers`, a deployment-owned map of extra request headers, as a validated config field rather than a hardcoded constant.

### Merge and ownership

`requestHeaders` in `@deepseek-ai/dsh-llm` combines `attributionHeaders()` with the map, letting the map win per field name and dropping the attribution spelling of any name the map restates under another capitalization: a gateway that admits one client rejects both a comma-joined `User-Agent` and whichever single value a downstream normalizer kept. The credential, `content-type`, `accept`, and `x-deepseek-harness-*` headers are applied after the merge and stay harness-owned, so a deployment cannot replace the API key or the request identity. `dsh-llm-pi-ai` calls the same helper instead of its identical local copy.

### Validation

`resolveAdapterOptions` judges the map at load and at each settings snapshot: names must be RFC 9110 `tchar`, values must not contain CR, LF, or NUL, and two spellings of one field name are refused because HTTP field names are case-insensitive and a joined pair would send neither value the deployment meant. An empty map resolves to absent facts, so an empty section cannot change a snapshot's identity. The map travels on the chat request and on the Files API through `DeepSeekConnectionOptions.headers` and `DeepSeekFileConnection.headers`.

### Attribution

The [mandatory attribution decision](../architecture/2026-06-21-mandatory-app-attribution-headers.md) owns the default, and it holds: a deployment that configures no headers sends the harness `User-Agent` on every provider request. A deployment that restates `User-Agent` replaces it, which is the rule `dsh-llm-pi-ai` already ships: a gateway that admits one client rejects both a joined pair and a value it does not recognize, so reserving the name leaves every client-gated gateway unreachable through this route. `requestHeaders` is the one home for the rule, and both adapters call it.

## Alternatives considered

**A `userAgent`-only field.** Covers the observed rejection, but gateways also demand tenancy, client, or tracing headers that this field cannot express, and pi-ai already exposed the general map.

**Deployment `AppIdentity` plumbing.** Renders `product/version (+url)`, so it cannot produce the exact `cline/3.5.0` this gateway admits; a value it can express is still the harness product token wearing another version.

**Reserving `user-agent` for attribution.** Keeps the identity unconditional, but leaves every client-gated gateway unreachable through this route, which is the deployment case that asked for the field.

**A package-local copy of the pi-ai helper.** Two copies of one merge rule drift; the helper belongs beside the attribution it merges.

## Consequences

- A deployment admits itself to a client-gated gateway, and owns the identity it presents there; a value the gateway does not recognize fails as a provider error with no adapter-side clue.
- The map is plain strings. A credential stored in it is outside the credentials seam, so it is not ranked, rotated, or redacted there; store keys as `apiKeyEnv` references.
- Uploaded-file reuse is scoped by endpoint and API key, so deployments that differ only in headers share each other's uploaded-file mappings.
- A gateway that rewrites or reorders request headers silently changes the wire request; the provider's own error is the only signal.

## Testing

- `packages/llm/llm-deepseek/tests/adapter.spec.ts` asserts the merged chat headers on a mock server, the harness-owned fields beside them, and each refusal: an invalid name, a value carrying LF, two spellings of one name, and an empty map resolving to absent facts.
- `packages/llm/llm-deepseek/tests/files-api.spec.ts` and `tests/file-store.spec.ts` assert the same map on the file transport, including the connection-to-client path.
- `docs/config-catalog.md` carries the field with its JSDoc; `pnpm run verify-config-catalog` owns freshness.
