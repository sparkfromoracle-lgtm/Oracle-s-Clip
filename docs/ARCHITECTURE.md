# Oracle Clip Production Hub — Architecture Specification

## 1. System Mission & Scope

Oracle Clip Production Hub is the operational control plane and media execution core for deterministic, production-grade media-to-clip generation. It enforces strict boundary validation, tenant isolation, controlled subprocess execution, and policy gates.

---

## 2. Canonical Pipeline Architecture (Sealed)

The production pipeline is **sealed**. The ordering, naming, and boundaries of components are strictly immutable:

```
ContentOpportunity
       ↓
ClipSpecification
       ↓
ClipSpecificationValidator
       ↓
Renderer (FFmpeg Adapter / Controlled Subprocess)
       ↓
RenderJob
       ↓
RenderedAsset
       ↓
QualityChecker
       ↓
GuardianHook (Policy & Safety Gate)
       ↓
Publishing (Signed Base44 Webhook Event)
```

### Component Contracts
1. **ContentOpportunity**: Heuristic zero-LLM or multimodal extraction of high-value candidate regions based on scene transitions, speech timing, and heuristic weights.
2. **ClipSpecification**: Declarative, normalized specification defining time boundaries, target aspect ratio (e.g. 9:16 vertical), resolution, audio leveling, and metadata.
3. **ClipSpecificationValidator**: Strict fail-closed validator checking source duration bounds, non-negative timestamps, positive duration, and non-overlapping sequence rules.
4. **Renderer**: Abstract rendering engine executing controlled FFmpeg subprocesses with memory limits, timeouts, and sanitized argv parameters.
5. **RenderJob**: State-tracked rendering lifecycle with asynchronous progression (`PENDING` → `VALIDATED` → `RENDERING` → `COMPLETED` / `FAILED`).
6. **RenderedAsset**: Validated binary output with storage URIs, deterministic SHA256 hashes, and duration properties.
7. **QualityChecker**: Automated verification of bitrate, audio synchronization, black-frame ratios, and codec parameters.
8. **GuardianHook**: Distinct policy and security gatekeeper verifying watermark placement, brand guidelines, and tenant compliance.
9. **Publishing**: Dispatches signed Base44 webhook events with HMAC-SHA256 timestamp authentication.

---

## 3. System Agents

The architecture identifies three distinct architectural agents:
- **Spark**: Deterministic candidate opportunity generator and heuristic extractor.
- **Guardian**: Safety, policy, and compliance validator acting at the post-render boundary.
- **Pulse**: Render queue manager, subprocess supervisor, and bulkhead concurrency limiter.

---

## 4. Zero-LLM Deterministic Pipeline

The system is designed with a **Zero-LLM core path**:
- Structural validation, hash calculations, FFmpeg arguments, quality checks, tenant isolation, and webhook signatures are 100% deterministic and do not require external LLM calls.
- AI Gateway integration is optional and modular; if an external LLM/multimodal service fails or is unreachable, the system executes fail-closed or falls back to deterministic zero-LLM pipelines without crashing.

---

## 5. Security & Isolation Model

1. **Authentication**:
   - Timing-safe API key comparison (`hmac.compare_digest`).
   - Tenant-bound principal tokens.
   - Cross-tenant access rejection (`TenantIsolationError` returning HTTP 403).
   - Only sanitized key identifiers (last 4 characters) appear in logs or safe summaries.

2. **Webhook Security**:
   - HMAC-SHA256 signature scheme with payload format: `timestamp + "." + body`.
   - 300-second timestamp freshness tolerance to prevent replay attacks.
   - Timing-safe verification.

3. **Subprocess Sandboxing**:
   - Direct `execve` execution without shell interpolation (`shell=False`).
   - Whitelisted binaries (`/usr/bin/ffmpeg`, `/usr/bin/ffprobe`).
   - Enforced maximum subprocess execution timeouts.

4. **Observability**:
   - Structured JSON logging with `correlation_id`, `tenant_id`, and `job_id`.
   - Recursive credential redaction across all log channels.
