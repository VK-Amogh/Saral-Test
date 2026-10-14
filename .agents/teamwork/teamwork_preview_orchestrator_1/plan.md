# Implementation & Orchestration Plan — Saral AI

## 1. Objective
Build, integrate, and verify the full Saral AI system end-to-end adhering strictly to `SARAL_AI_IMPLEMENTATION_PLAN.md`, `rules.md`, and `ORIGINAL_REQUEST.md`.

## 2. Tracks & Architecture
- **Track 1: Implementation Track**
  - M1: Supabase Database Schema, Migrations, RLS Policies, Realtime Publications, and Storage setup.
  - M2: FastAPI Backend Core & AI Engine (JWT auth, PII/Verhoeff scrubber, Groq LLM streaming SSE chat, deterministic state machine, Postgres job queue, challenge broker).
  - M3: Mock Portal & Playwright Automation Worker (standalone mock portal with failure modes, browser worker with WebSocket link, domain allowlist, document verification).
  - M4: Flutter Mobile Application (monochrome theme tokens, Arapey/Inter typography, Riverpod, GoRouter, Supabase auth, chat streaming, inline task stepper, secure input sheets with FLAG_SECURE, document vault).
  - M5: Operations, CI/CD & Production Configurations (GitHub Actions CI, keepalive, cleanup cron, render.yaml, .env.example, README).
  - M6: Final Milestone (100% E2E test suite pass + Adversarial Coverage Hardening).
- **Track 2: E2E Testing Track (Parallel)**
  - Opaque-box test harness, runner, and 4-tier test suite based on requirements.
  - Generates `TEST_READY.md`.

## 3. Step-by-Step Execution Plan
1. **Survey Phase**: Spawn 3 Explorers/Spec Miners in parallel to analyze specs, APIs, contracts, schemas, and requirements across the backend, worker, mock portal, and Flutter app.
2. **Decomposition & PROJECT.md**: Merge survey findings into comprehensive Feature Inventory, Architecture, Code Layout, and Interface Contracts in `PROJECT.md`.
3. **Dispatch E2E Test Orchestrator**: In parallel, spawn E2E testing track to establish test runner and test cases (Tiers 1-4).
4. **Dispatch Implementation Sub-orchestrators/Milestones**: Execute M1 through M5 with strict Explorer -> Worker -> Reviewer -> Challenger -> Auditor cycles.
5. **Final Integration & Hardening**: Run full test suite, pass 100% E2E tests, execute Tier 5 adversarial testing.
6. **Integrity Audit & Reporting**: Complete gate checks and notify Sentinel.
