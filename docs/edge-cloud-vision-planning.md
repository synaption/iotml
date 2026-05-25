# Edge + Cloud Vision Pipeline Planning TODO / Decisions

This document consolidates the architecture and implementation planning decisions discussed for the edge + cloud vision pipeline.

## 1) Decisions already made

- [x] **Frame source architecture:** Use a **frame-source sidecar/service architecture (Option 2)**.
  - Inference container consumes a stable frame-source contract instead of directly reading camera devices or datasets.
- [x] **Why Option 2:** Prefer this approach because it supports **real-world dataset loading and replay**.
  - Enables future replay of captured Raspberry Pi sessions and curated regression datasets.
- [x] **Runtime consistency goal:** Keep inference container behavior **consistent across Raspberry Pi and CI**.
  - Only frame acquisition backend varies; preprocessing/inference/escalation flow remains aligned.
- [x] **Data roadmap:** Plan for future support of **real captured data**, not only MNIST.

## 2) Recommended defaults (not yet formally locked)

These are recommended starting defaults and remain open until explicitly finalized:

- [ ] **Protocol:** HTTP
- [ ] **Image format:** PNG
- [ ] **Session model:** Explicit deterministic session
- [ ] **Edge deployment shape:** Same pod (frame-source + edge-inference)
- [ ] **CI dataset mode:** MNIST rendered into synthetic camera-like scenes

## 3) Full prioritized TODO / decision backlog

### P0 — Core architecture and contracts

#### Core architecture
- [ ] Finalize edge/cloud boundary model for phase 1 and phase 2.
  - [ ] Confirm deployment and trust boundaries between edge workloads and cloud services.
  - [ ] Define non-goals for phase 1 to constrain scope.

#### Frame-source service design
- [ ] Define frame-source service API contract.
  - [ ] Endpoint set (e.g., health, session create/reset, next frame).
  - [ ] Response schema for frame metadata and payload delivery.
  - [ ] Versioning strategy for API and metadata fields.

#### Inference pipeline contract
- [ ] Freeze canonical frame lifecycle contract.
  - [ ] Acquire frame.
  - [ ] Canonicalize format.
  - [ ] Preprocess.
  - [ ] Edge infer.
  - [ ] Escalate/confirm when policy requires.
- [ ] Define required trace fields.
  - [ ] frame_id, device_id, source_type, model_version, preprocessing_version, timestamps.

#### Edge inference behavior
- [ ] Finalize edge output schema.
  - [ ] predicted_class, confidence, trace_id, model_version.
  - [ ] Include frame or reference policy for escalations.
- [ ] Define deterministic behavior requirements for CI parity.

#### Cloud confirmation behavior
- [ ] Define cloud confirmation API and return schema.
  - [ ] Inputs required from edge.
  - [ ] Returned class/confidence and comparison metadata.
- [ ] Define persistence/retention for edge-cloud comparison results.

#### Escalation and confidence policy
- [ ] Set initial confidence thresholds and environment overrides.
  - [ ] Static default threshold for phase 1.
  - [ ] Optional class-specific confirmation rules.
- [ ] Define fallback behavior when cloud confirmation is unavailable.

### P1 — Data sources, simulation, and device integration

#### Frame-source backends
- [ ] Implement and prioritize backends.
  - [ ] `mnist_synthetic` backend for CI determinism.
  - [ ] `camera` backend for Raspberry Pi capture.
  - [ ] `replay` backend for recorded sessions.
  - [ ] Future: object storage / RTSP / uploaded datasets.

#### Dataset and simulation strategy
- [ ] Lock deterministic dataset policy for CI.
  - [ ] Fixed seed and fixed frame ordering.
  - [ ] Versioned subset selection.
- [ ] Specify synthetic-scene renderer behavior.
  - [ ] Placement, scale, rotation, noise/blur/lighting transforms.

#### Camera and real-device integration
- [ ] Define Pi camera access constraints and runtime configuration.
  - [ ] Device selection and error handling.
  - [ ] Capture settings and performance expectations.
- [ ] Define captured-data export path for later training/regression corpora.

#### Data transport and messaging
- [ ] Confirm protocol choice and future migration considerations.
  - [ ] HTTP now, evaluate gRPC/async messaging as scale and connectivity needs evolve.
- [ ] Define payload transfer mode.
  - [ ] Binary image payload + metadata model.

### P1 — Platform, deployment, and delivery

#### Kubernetes and deployment design
- [ ] Define manifests/charts for edge + cloud components.
  - [ ] Sidecar/same-pod pattern for frame-source + edge inference.
  - [ ] Service discovery and namespace boundaries.
- [ ] Define scheduling and resource requests/limits for edge nodes.

#### GitHub Actions CI/CD pipeline
- [ ] Define staged workflow gates.
  - [ ] Lint/test/unit/contract.
  - [ ] Build and publish container images.
  - [ ] Deploy test environment on DOKS.
  - [ ] Run deterministic simulated-camera integration tests.
- [ ] Define promotion and approval path to staging/production.

#### Containerization strategy
- [ ] Finalize image strategy.
  - [ ] Multi-arch image policy for Pi and CI compatibility.
  - [ ] Runtime configuration via environment variables/secrets.
- [ ] Define base image hardening and patching cadence.

#### Model management
- [ ] Define model artifact lifecycle.
  - [ ] Versioning and pinning strategy.
  - [ ] Promotion/rollback compatibility across edge and cloud.
- [ ] Define model distribution approach for phase 1.

### P2 — Operations, quality, and repo hygiene

#### Observability and diagnostics
- [ ] Standardize logs/metrics/traces across frame-source, edge, and cloud.
  - [ ] End-to-end correlation with trace/frame IDs.
  - [ ] Dashboard/alert essentials for latency and escalation rates.

#### Failure and resilience testing
- [ ] Build failure-mode test matrix.
  - [ ] Missing/corrupt frames.
  - [ ] Slow inference.
  - [ ] Network partition edge→cloud.
  - [ ] Cloud unavailable.
  - [ ] Duplicate or delayed deliveries.

#### Security and secrets
- [ ] Define secret management for CI/CD and runtime.
  - [ ] GitHub Actions secrets/OIDC for registry and cluster auth.
  - [ ] Runtime credential isolation and rotation policy.
- [ ] Define transport/auth requirements between edge and cloud services.

#### Repository structure
- [ ] Confirm repository layout for edge, cloud, deployment, and simulation assets.
  - [ ] Source directories and ownership boundaries.
  - [ ] Placement of manifests/charts/workflows and shared contracts.

#### Testing strategy
- [ ] Finalize test pyramid and required gates per PR.
  - [ ] Unit tests for loaders/preprocessing/policy logic.
  - [ ] Integration tests for frame-source + edge inference contract.
  - [ ] End-to-end tests on Kubernetes with deterministic datasets.

#### Phase-1 scope definition
- [ ] Freeze phase-1 definition of done.
  - [ ] Deterministic MNIST synthetic CI flow.
  - [ ] Edge inference + cloud confirmation path working end-to-end.
  - [ ] Traceable outputs for pass/fail analysis.
