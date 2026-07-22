# METACRAWLER EVOLUTION AUDIT (2025-10-01 to 2026-07-18)

## 1. Executive summary

Metacrawler’s verifiable history begins on **2025-12-22**, not 2025-10-01. From repository evidence, it began as a **single-repository, Veredictum-led document acquisition engine** with strong architectural intent but weak runtime isolation, fragile shared planning, and limited recovery safeguards. By **2026-07-11**, it had become a **more operationally serious acquisition core**: plans moved out of the repository, the writable data root became explicit and validated, scheduler state became atomic and recoverable, structured crawler results and JSONL event logs were added, and a meaningful offline regression suite appeared.

The project matured materially in four areas:

- deterministic and scoped planning;
- persistent scheduler safety;
- runtime/environment validation;
- offline, repo-safe test discipline.

The most important unresolved reality is that **the core is now safer than many crawler modules it orchestrates**. Several source implementations still flatten internal errors into `"skipped"`, carry hardcoded institutional assumptions, or use very thin per-source state that limits resumability and observability. The repository therefore shows a creator who learned to turn painful operational ambiguity into permanent safeguards in the core, but who has not yet fully propagated that discipline into every source adapter.

Final judgment: **clear and meaningful technical growth, with the core now approaching professional operational discipline, but acquisition should not fully resume until crawler-level failure semantics, deduplication enforcement, and source generalization are tightened.**

## 2. Repository evidence and methodology

### Verified evidence used

- Git history from `git log --reverse --date=short`
- Commit contents and diffs for:
  - `1de7543` on 2025-12-22 (`1st load`)
  - `7d17c26` on 2025-12-22 (`Add initial Metacrawler README`)
  - `75ed321` on 2025-12-22 (`Fix Round Robin execution and crawler selection`)
  - `ad389e4` on 2026-07-11 (`feat: establish persistent metacrawler runtime foundation`)
- Current implementation in:
  - `runner.py`
  - `Backend/core/*`
  - `Backend/config/*`
  - `clients/veredictum/*`
  - `tests/test_runtime_foundation.py`
  - `README.md`

### Audit method

1. Reconstructed the repository chronology from the four available commits.
2. Compared initial and current versions of scheduling, bootstrap, runtime, and manager code.
3. Read current crawler implementations to assess whether core guarantees are actually upheld at the adapter layer.
4. Ran the repository’s offline test suite with `python3 -m unittest tests/test_runtime_foundation.py`.

### Evidence limitations

- There is **no verifiable repository history before 2025-12-22**.
- The history is sparse: four commits total, with one large initial import. This limits fine-grained reconstruction.
- Operational incidents are mostly inferable from code changes and commit messages; there are no issue trackers, postmortems, or archived runtime state in the repository.
- The audit did **not** execute networked crawling and therefore cannot validate live source compatibility.

### Fact / inference / unavailable evidence legend

- **Verified fact**: directly supported by repository contents or test execution.
- **Reasonable inference**: strongly suggested by code shape, commit messages, or documentation, but not explicitly stated.
- **Unavailable evidence**: not provable from this repository.

## 3. Earliest verifiable project state

### Earliest date

The earliest verifiable repository state is **2025-12-22** (`1de7543`). The requested audit window starts on 2025-10-01, but no repository evidence exists for October or November 2025.

### What Metacrawler initially appears to have been

**Verified facts**

- The initial import already contained a substantial acquisition core, client-specific crawlers, a classifier layer, a round-robin scheduler, bootstrap planning, and architecture documents.
- The initial repository was tightly centered on **Veredictum** as the concrete consumer: `clients/veredictum/`, Veredictum-specific classifier rules, and Costa Rica/Mexico URL inventories were already present.
- The original documentation framed Metacrawler as the acquisition layer for FileForgeAI and similar systems, with strong emphasis on modularity, persistence, anti-duplication, and “human” crawling behavior.

**Reasonable inference**

- The project was likely born from a real ingestion pain point, not as an abstract framework. The presence of numerous concrete institutional crawlers in the first commit suggests implementation pressure preceded full architectural consolidation.
- The creator had already formed strong design principles before the first public snapshot, but those principles had not yet been fully enforced by code.

## 4. Current project state

As of **2026-07-18**, Metacrawler is best described as a **single-process, file-backed, offline-testable acquisition core with client/country/source scoping and improved recovery semantics**, still specialized around Veredictum-era institutional crawlers.

### Verified current characteristics

- Runtime data root is explicit, environment-overridable, existence-checked, and write-probed in `Backend/config/runtime.py:12-30`.
- Generated plans are scoped to `<data_root>/<client>/<country>/_plans/sources.yaml`, not stored in the repository, in `Backend/core/bootstrap_sources.py:55-127`.
- Scheduler state writes are atomic (`mkstemp` + `fsync` + `os.replace`) and malformed state is backed up rather than silently overwritten in `Backend/core/utils/round_robin.py:35-60`.
- Scheduler identity is now scoped by `(client, country, source_id)` and supports inactive retained tasks in `Backend/core/utils/round_robin.py:62-100`.
- The manager emits both human logs and JSONL events, and normalizes crawler outputs into structured `CrawlerResult` objects in `Backend/core/crawler_manager.py:79-91` and `205-257`.
- An offline regression suite blocks socket, urllib, HTTP, `requests`, and subprocess access during tests in `tests/test_runtime_foundation.py:23-40`.

### Current boundaries

- Metacrawler still owns acquisition, source planning, scheduling, per-source state, and run logging.
- FileForge and Veredictum appear only as integration context, not as audited codebases.
- The dominant operational surface remains `clients/veredictum/crawlers/ti/*`.

## 5. Chronological evolution by phase

## Phase 0. Pre-history outside the repository

### Approximate dates

Before **2025-12-22**

### Interpretation

**Reasonable inference**

The project had meaningful private or local development before the first commit. The first commit is too complete to represent day-one coding: it already includes multiple crawlers, contracts, architecture notes, and client URL inventories.

### Supporting evidence

- Large initial import: 47 files and 3779 insertions in `1de7543`.
- Initial docs already articulate a mature philosophy around rate limiting, state, anti-duplication, and separation of concerns.

### Creator reasoning shift

Unavailable from repository history. The repo begins after the initial conceptual model existed.

## Phase 1. Initial public snapshot: architecture by intent, implementation by shared files

### Approximate dates

**2025-12-22** (`1de7543`, `7d17c26`)

### Major goals

- Establish a reusable crawler core.
- Separate clients, countries, and institutional crawlers.
- Encode a round-robin discipline to avoid aggressive crawling.
- Document the system’s philosophy and operating rules.

### Major subsystems introduced

- `runner.py`
- `Backend/core/crawler_manager.py`
- `Backend/core/bootstrap_sources.py`
- `Backend/core/utils/round_robin.py`
- `Backend/core/crawler_loader.py`
- `clients/veredictum/crawlers/ti/*`
- `clients/veredictum/classifier.py`
- `Backend/core/CRAWLER_CONTRACT.md`
- `Backend/core/Readme.md`
- `README.md`

### Architectural state in this phase

**Verified facts**

- Bootstrap wrote a single shared repository file, `Backend/core/sources.yaml`, rather than a client/country-scoped plan.
- Initial bootstrap incorrectly took the first classified URL’s `source_id` and reused it for all URLs, collapsing heterogeneous sources into one source bucket.
- Initial runner launched bootstrap via `subprocess.run`, removed the shared `sources.yaml` first, and then reloaded that same shared file.
- Initial scheduler wrote YAML directly and bootstrapped only when empty; it did not validate malformed state, did not scope identity by client/country, and could delete then recreate state on reset.
- Initial manager always reset the scheduler before running, which destroyed continuity.

### Defects or limitations being addressed later

- Shared plan file created cross-run and cross-country coupling.
- Classification bug could collapse all URLs into the wrong source.
- Scheduler persistence existed, but the manager immediately wiped it before each run.
- State writes were not atomic.
- Runtime data root was implicit and filesystem-assumptive.

### Evidence

- Initial bootstrap: `git show 1de7543:Backend/core/bootstrap_sources.py`
- Initial manager: `git show 1de7543:Backend/core/crawler_manager.py`
- Initial scheduler: `git show 1de7543:Backend/core/utils/round_robin.py`

### What changed in the creator’s apparent reasoning

The creator already reasoned in terms of contracts, bounded work, and modularity, but the code still prioritized “make the system work end-to-end” over hard guarantees around scoped state and resumability. This is a common early-systems pattern: the architectural model is ahead of the reliability model.

## Phase 2. Same-day correction: source identity and scheduler semantics repaired

### Approximate dates

**2025-12-22** (`75ed321`)

### Major goals

- Fix round-robin behavior.
- Fix crawler selection and source modeling.
- Make multiple crawlers execute as expected.

### Architectural changes

**Verified facts**

- `Backend/core/sources.yaml` was added to the repository as a committed sample/generated plan artifact.
- Scheduler bootstrap was changed from target expansion to `1 source = 1 task`.
- Runner stopped invoking bootstrap through a subprocess and imported it directly.
- Bootstrap changed from “one classified source for all URLs” to per-URL classification.
- Special handling was added so `www.tramites.go.cr` becomes its own source rather than falling into the institutional fallback bucket.

### Defects addressed

- Incorrect crawler/source selection.
- Broken round-robin alternation across selected sources.
- Trámites collapsing into a generic institutions bucket.

### Evidence

- Commit message of `75ed321`.
- `git show 75ed321:Backend/core/utils/round_robin.py`
- `git show 75ed321:runner.py`
- Current bootstrap special case retained in `Backend/core/bootstrap_sources.py:71-95`.

### What changed in the creator’s reasoning

This phase shows a shift from “task = maybe source/target fan-out” toward a more deliberate unit of scheduling. The creator appears to have learned that source identity and scheduling granularity must be explicit and stable, not emergent from nested target structures.

## Phase 3. Runtime foundation hardening: persistence, recoverability, offline safety

### Approximate dates

**2026-07-11** through **2026-07-18** (`ad389e4` plus current tree)

### Major goals

- Make runtime state safe and relocatable.
- Keep generated plans and scheduler state out of the repository.
- Add recovery behavior for malformed state.
- Improve observability and structured outcomes.
- Prove non-networked operations with tests.

### Architectural changes

**Verified facts**

- Added canonical runtime configuration in `Backend/config/runtime.py:12-30`.
- Moved plans into scoped runtime storage via `plan_path()` in `Backend/core/bootstrap_sources.py:55-58`.
- Replaced direct file writes with atomic temporary-file replacement for plans and scheduler state in `Backend/core/bootstrap_sources.py:113-123` and `Backend/core/utils/round_robin.py:50-60`.
- Added malformed-state backup and failure signaling in `Backend/core/utils/round_robin.py:35-48`.
- Added scheduler task identity scoping, inactive task retention, and legacy migration behavior in `Backend/core/utils/round_robin.py:62-79`.
- Stopped unconditional scheduler reset; the manager now preserves state unless reset is explicitly requested in `Backend/core/crawler_manager.py:183-199`.
- Added structured crawler results in `Backend/core/results.py`.
- Added JSONL event logs in `Backend/core/crawler_manager.py:86-91` and `192-256`.
- Added CLI commands for `validate-config`, `status`, `plan`, and explicit `reset-state` in `runner.py:204-251`.
- Added offline runtime tests covering config, plan determinism, repo safety, scheduler persistence, malformed backups, result normalization, and manager behavior in `tests/test_runtime_foundation.py`.

### Failures or operational pain likely behind these changes

**Reasonable inferences**

- Shared repository planning likely caused accidental code-tree writes or conflicting runs.
- Loss of scheduler continuity likely made incremental crawling unreliable.
- Malformed or partially written state likely occurred often enough to justify backup-on-read-failure.
- “Did it work, or did the crawler silently skip?” became a serious enough problem to justify structured results and JSONL events.

### What changed in the creator’s reasoning

This phase reflects the clearest growth in software reasoning. The creator moved from local-script assumptions to operational contracts:

- configuration must be explicit and validated;
- persistence must be atomic;
- malformed state must be preserved for inspection;
- offline administrative commands must be provably repo-safe;
- tests must actively forbid hidden network/subprocess escape routes.

## 6. Architecture map

### Current architecture

- `runner.py`
  - CLI and interactive entrypoint.
  - Provides offline-safe commands for config validation, plan generation, state status, and scoped state reset.
- `Backend/config/runtime.py`
  - Canonical runtime root resolution and write-probe validation.
- `Backend/core/bootstrap_sources.py`
  - Converts client URL inventories into scoped source plans.
- `Backend/core/crawler_manager.py`
  - Loads plan data, initializes logs/state, schedules a bounded cycle, loads crawlers, normalizes outcomes.
- `Backend/core/utils/round_robin.py`
  - Persistent scheduler state, atomic writes, malformed-state backup, active/inactive task tracking.
- `Backend/core/results.py`
  - Structured result normalization between legacy string crawlers and richer outcome schema.
- `Backend/core/classifiers/master.py`
  - Client classifier dispatch with fallback `NullClassifier`.
- `Backend/core/crawler_loader.py`
  - Dynamic module loading by client/country/source path.
- `clients/<client>/classifier.py`
  - URL-to-source mapping.
- `clients/<client>/crawlers/<country>/*.py`
  - Source-specific acquisition logic.

### Integration boundaries

- **FileForge / Veredictum boundary**: documented consumer relationship in `README.md:3-5`, but the repository only contains Metacrawler’s acquisition side.
- **Persistent state boundary**: runtime data now lives outside the code tree by contract in `README.md:163-189` and `Backend/config/runtime.py:12-30`.

## 7. Major capabilities gained

1. **Scoped runtime root**
   - Gained on 2026-07-11.
   - Evidence: `Backend/config/runtime.py:12-30`, `README.md:165-173`.

2. **Plan generation outside the repository**
   - Replaced shared `Backend/core/sources.yaml` as the live plan target.
   - Evidence: `Backend/core/bootstrap_sources.py:55-127`.

3. **Atomic writes for plans and scheduler state**
   - Reduced partial-write corruption risk.
   - Evidence: `Backend/core/bootstrap_sources.py:113-123`, `Backend/core/utils/round_robin.py:50-60`.

4. **Malformed-state backup and explicit recovery failure**
   - Scheduler now preserves forensic evidence.
   - Evidence: `Backend/core/utils/round_robin.py:35-48`, `tests/test_runtime_foundation.py:144-160`.

5. **State-preserving scheduler bootstrap**
   - Existing tasks are merged and deactivated/reactivated rather than discarded.
   - Evidence: `Backend/core/utils/round_robin.py:65-79`.

6. **Structured results and JSONL observability**
   - Core can distinguish exceptions from legacy `"skipped"` results.
   - Evidence: `Backend/core/results.py`, `Backend/core/crawler_manager.py:230-256`, `tests/test_runtime_foundation.py:163-194`.

7. **Offline-safe operational commands**
   - `validate-config`, `status`, `plan`, `reset-state`.
   - Evidence: `runner.py:204-251`, tests at `59-64` and `92-98`.

8. **Real offline regression discipline**
   - Network and subprocess calls are actively forbidden during tests.
   - Evidence: `tests/test_runtime_foundation.py:23-40`.

## 8. Major defects or painful transitions

1. **Initial source-collapse bug**
   - Early bootstrap classified the first URL once, then assigned all URLs to that same source.
   - Impact: incorrect source plan, wrong crawler selection, hidden missing coverage.
   - Resolved in Phase 2.

2. **Round-robin persistence that was reset every run**
   - Early manager reset the scheduler before execution.
   - Impact: apparent persistence without actual continuity.
   - Resolved in Phase 3.

3. **Shared repository plan file**
   - Early and mid-stage flow depended on `Backend/core/sources.yaml`.
   - Impact: code/data coupling, unsafe concurrent use, accidental repository mutation.
   - Largely resolved in Phase 3, though the committed sample file remains in-tree.

4. **Opaque crawler outcomes**
   - Legacy crawlers returned only `"downloaded"`, `"skipped"`, or `"failed"`, and many crawler internals still swallow exceptions into `"skipped"`.
   - Impact: operator ambiguity and weak retry semantics.
   - Partially resolved in the core only.

## 9. Resolved technical debt

### Historical debt already resolved

- **Shared live plan in repository**
  - Evidence: initial/bootstrap history versus current `plan_path()`.
  - Resolution: plans moved to scoped runtime storage.

- **Unvalidated writable-root assumptions**
  - Evidence: initial `config.paths` import-time directory creation versus current write-probe validation.
  - Resolution: `RuntimeConfigError` and explicit validation.

- **Non-atomic scheduler writes**
  - Evidence: initial direct write versus current temp-file replacement.
  - Resolution: atomic persistence added.

- **Scheduler reset as default behavior**
  - Evidence: initial manager `self.rr.reset()` before bootstrap versus current explicit reset only.
  - Resolution: preserved continuity.

- **No offline regression guardrails**
  - Evidence: tests absent before July 2026, present after.
  - Resolution: broad offline test suite added.

## 10. Current technical debt

## Critical

### C1. Claimed persistent cross-source deduplication is not evidenced in the active runtime path

- **Evidence**
  - README claims global persistent deduplication in `README.md:76-94` and `116-126`.
  - Current manager path does not invoke `Backend/core/utils/dedupe.py`.
  - Crawlers generally only skip if destination filenames already exist locally, for example:
    - `clients/veredictum/crawlers/ti/tramites.py:98-100`
    - `clients/veredictum/crawlers/ti/pgr.py:172-176`
- **Impact**
  - Duplicate documents from different URLs or sources can likely be reacquired and stored multiple times despite documentation claiming otherwise.
- **Probability**
  - High.
- **Affected subsystem**
  - Acquisition core and crawler adapters.
- **Recommended direction**
  - Move deduplication enforcement into a mandatory core path or standardized crawler helper with content-hash persistence and tests.
- **Before acquisition resumes?**
  - **Yes.**

### C2. Crawler-level exception swallowing still hides acquisition failures as skips

- **Evidence**
  - README explicitly admits this limitation in `README.md:184-189`.
  - Many crawlers catch broad exceptions and return `"skipped"` after advancing state or ending a pass, for example:
    - `clients/veredictum/crawlers/ti/tramites.py:75-91`
    - `clients/veredictum/crawlers/ti/pgr.py:128-179`
- **Impact**
  - Real extraction failures can look like harmless no-op outcomes, undermining retry policy, operational trust, and source-health diagnosis.
- **Probability**
  - High.
- **Affected subsystem**
  - Source adapters and operational observability.
- **Recommended direction**
  - Standardize structured crawler outcomes with explicit retryable failure categories and migrate legacy crawlers away from string-only returns.
- **Before acquisition resumes?**
  - **Yes.**

## High

### H1. Resumability remains shallow and inconsistent across crawlers

- **Evidence**
  - Several crawlers use minimal per-source state such as `"done"` or a single integer/date:
    - `clients/veredictum/crawlers/ti/asamblea.py:166-171`
    - `clients/veredictum/crawlers/ti/pgr.py:176-181`
    - `clients/veredictum/crawlers/ti/gaceta.py:64-76`
    - `clients/veredictum/crawlers/ti/tramites.py:49-67`
- **Impact**
  - Recovery after partial progress is coarse. Re-entrancy depends on destination files or simplistic counters rather than explicit checkpoints.
- **Probability**
  - High.
- **Affected subsystem**
  - Source-specific acquisition logic.
- **Recommended direction**
  - Define a richer per-crawler state contract: cursor, last successful document identity, last failed target, retry hint, and schema version.
- **Before acquisition resumes?**
  - **Yes**, for high-volume or legally critical sources.

### H2. Source behavior is still highly hardcoded and not yet safely extensible

- **Evidence**
  - Veredictum classifier uses fixed domain mappings and broad fallback to `instituciones` in `clients/veredictum/classifier.py:10-69`.
  - `tramites.py` is driven by a hardcoded list of predicted PDF paths in `clients/veredictum/crawlers/ti/tramites.py:55-71`.
  - `pgr.py` relies on hardcoded search keywords in `clients/veredictum/crawlers/ti/pgr.py:17-40`.
- **Impact**
  - Adding sources safely remains labor-intensive and brittle. Subtle website shifts may silently degrade acquisition.
- **Probability**
  - High.
- **Affected subsystem**
  - Source definitions and crawler implementations.
- **Recommended direction**
  - Separate source metadata, crawl strategy, and source-specific parsing rules more explicitly; codify adapter capabilities and expected state shape.
- **Before acquisition resumes?**
  - Not globally, but high-risk sources should be reviewed first.

### H3. Multi-client architecture is only partially realized

- **Evidence**
  - README presents multi-client reuse as a core property in `README.md:23-31`.
  - Current repository has substantive crawlers only for `veredictum`; `clients/mit` contains URL inventory but no crawler tree or classifier.
- **Impact**
  - The core is reusable in principle, but real compatibility outside Veredictum is not yet proven.
- **Probability**
  - High.
- **Affected subsystem**
  - Extension model and maintainability.
- **Recommended direction**
  - Validate the adapter model with a second fully implemented client, not just a placeholder URL inventory.
- **Before acquisition resumes?**
  - No, unless multi-client rollout is part of the resume plan.

## Medium

### M1. Scheduler fairness is deterministic but may still allow long-term starvation of latent work

- **Evidence**
  - Scheduler rotates active tasks deterministically in `Backend/core/utils/round_robin.py:86-101`.
  - Manager executes a bounded cycle of `len(tasks)` selections per run in `Backend/core/crawler_manager.py:192-200`.
  - There is no source weighting, aging, backlog awareness, or retry priority.
- **Impact**
  - Fairness is simple but coarse. Sources with large backlogs advance no faster than light ones; retryable failures have no priority model.
- **Probability**
  - Medium.
- **Affected subsystem**
  - Scheduling and planning.
- **Recommended direction**
  - Add optional prioritization/backoff policy above pure round robin while preserving determinism.
- **Before acquisition resumes?**
  - Not necessarily.

### M2. Offline safety is proven for core commands and tests, but not enforced as a design boundary in crawler modules

- **Evidence**
  - Tests forbid network during core/unit operations in `tests/test_runtime_foundation.py:23-40`.
  - Crawler modules directly import `requests` and implement live network logic without a mockable transport abstraction.
- **Impact**
  - Test isolation is strong for the core, weaker for adapter-level regression testing.
- **Probability**
  - Medium.
- **Affected subsystem**
  - Testing and crawler architecture.
- **Recommended direction**
  - Introduce adapter-level fixtures or a small fetch abstraction to allow deterministic crawler tests without live I/O.
- **Before acquisition resumes?**
  - Helpful, not mandatory.

### M3. Legacy/generated artifacts remain in the repository and blur operational boundaries

- **Evidence**
  - Tracked `.bash_history` appears in the initial commit and is still tracked.
  - `Backend/core/sources.yaml` remains in-tree even though README now says plans belong in runtime `_plans`.
- **Impact**
  - Weakens repository hygiene and can confuse operators about canonical state locations.
- **Probability**
  - Medium.
- **Affected subsystem**
  - Operational clarity and repo discipline.
- **Recommended direction**
  - Remove or archive non-canonical artifacts and keep docs aligned with live paths.
- **Before acquisition resumes?**
  - No, but should be cleaned soon.

## Low

### L1. Portability remains Linux-first

- **Evidence**
  - README says Linux recommended in `README.md:145-151`.
  - `scripts/metacrawler-vm` and path defaults assume a specific Linux-style environment.
- **Impact**
  - Limits easy relocation, but does not threaten correctness in the intended deployment model.
- **Probability**
  - High.
- **Affected subsystem**
  - Runtime/deployment assumptions.
- **Recommended direction**
  - Keep Linux as the supported target, but document unsupported environments more explicitly.
- **Before acquisition resumes?**
  - No.

## Intentional limitations

- Interactive CLI remains operator-driven rather than daemonized.
- The system is HTTP-first and intentionally avoids browser automation.
- The core is specialized rather than a polished general-purpose library.

## 11. Testing and operational maturity

### Testing maturity

Metacrawler’s testing story changed dramatically.

**Beginning of period**

- No tests in the repository.
- No active guard against network calls during validation operations.
- No proof that plan generation or state inspection avoided mutating the repository.

**Current state**

- Standard-library `unittest` suite present and runnable.
- Network and subprocess operations explicitly blocked in tests:
  - socket connect
  - `socket.create_connection`
  - `urllib.request.urlopen`
  - `http.client.HTTPConnection.request`
  - `subprocess.run`
  - `subprocess.Popen`
  - `requests.Session.request` when installed
- Determinism and repo safety tested for plan generation.
- Scheduler migration, malformed-state backup, atomic replacement, scoped reset, and result normalization all covered.

### Verified test execution

Executed on **2026-07-18**:

```text
python3 -m unittest tests/test_runtime_foundation.py
Ran 15 tests in 2.156s
OK
```

### Remaining testing gaps

- No crawler-specific offline regression suite for institutional source modules.
- No contract tests asserting that crawlers return structured failure categories.
- No concurrency or multi-process state contention tests.
- No deduplication enforcement tests in the active runtime path.

### Operational maturity

The core is now operationally much more mature than the adapters:

- explicit root validation;
- atomic state writes;
- malformed backup behavior;
- explicit reset confirmation;
- JSONL event logs;
- offline admin commands.

This is a substantial maturation step.

## 12. Security and data-integrity observations

### Positive observations

- Writable-root validation uses an actual write probe, not only `os.access`, in `Backend/config/runtime.py:17-25`.
- Atomic replacement reduces partial-write corruption for plans and scheduler state.
- Malformed scheduler files are preserved as uniquely named backups, reducing silent data loss risk.
- Reset is explicit and requires `--yes`.
- Offline admin commands avoid importing crawlers in the tested path.

### Risks

- No evidence of locking around scheduler state or per-source state files. Concurrent runs could race on YAML/JSON files.
- Crawler modules often write state directly with minimal schema and no atomic helper.
- Global deduplication is documented but not proven in the active path.
- The repository historically tracked `.bash_history`, which is a hygiene concern even if not an active runtime risk.

## 13. Creator growth analysis

This repository shows real growth in software reasoning, but the growth is uneven in a revealing way.

### Problem decomposition

**Verified evidence of growth**

- From the beginning, the creator decomposed the system into runner, bootstrapper, loader, manager, classifier, scheduler, and crawler adapters.
- Later changes further separated runtime config, result normalization, and scheduler recovery logic into dedicated modules.

### Defensive programming

**Strong growth**

- Early code assumed paths and state would mostly behave.
- Later code validates the root, probes write access, treats malformed state as first-class, and preserves broken files for analysis rather than overwriting them.

### Deterministic execution

**Strong growth**

- Determinism was originally more aspirational than enforced.
- By July 2026, deterministic plan generation, stable scheduler merging, and bounded-cycle execution were explicitly encoded and tested.

### State safety

**Strong growth**

- The clearest maturity signal in the whole repository.
- The creator learned that persistence without atomicity and recovery semantics is not enough.

### Test discipline

**Strong growth**

- The current test file does not merely check happy paths; it actively blocks network and subprocess escape hatches and verifies repo immutability for admin commands.
- That is a notably more professional testing mindset than “does the function return a value.”

### Architectural boundaries

**Moderate growth**

- Boundaries between acquisition core and downstream consumers are well described.
- Boundaries between core and crawler adapters improved, but are not yet fully contractual at the result/state/deduplication level.

### Incident-to-safeguard conversion

**Strongest evidence of growth**

The July 2026 changes read like lessons extracted from real failures:

- shared plan file became scoped runtime planning;
- silent scheduler overwrite risk became atomic writes plus backup-on-malformation;
- opaque outcomes became structured results and JSONL events;
- unsafe environment assumptions became explicit validation;
- “offline command” claims became enforced tests.

This is the pattern of someone learning to encode operational pain into permanent system protections.

### Limits of that growth

The creator’s reasoning matured faster in the core than in the crawler modules. The remaining crawler code still reflects earlier habits:

- broad exception swallowing,
- hardcoded source heuristics,
- thin state,
- weakly typed outcomes.

That is not a contradiction. It is evidence of a project in transition.

## 14. Comparison table

| Dimension | Beginning of period | Current state | Next professional maturity level |
|---|---|---|---|
| Project identity | Veredictum-led crawler engine with reusable ambitions | Operational acquisition core with scoped runtime and offline admin commands | Reusable acquisition platform with adapter contracts and source test harnesses |
| Planning | Shared repository plan file, cross-run coupling | Scoped runtime plans under `_plans` | Versioned plan schema plus provenance and diff history |
| Scheduling | Persistent in concept, reset in practice | Deterministic bounded-cycle scheduler with merge/migration behavior | Priority/backoff-aware scheduling with concurrency safety |
| State integrity | Direct writes, weak malformed-state handling | Atomic YAML replacement and malformed backups | File locking, schema migration strategy, richer per-crawler checkpoints |
| Results/observability | String outcomes and human logs | Structured results plus JSONL events | Uniform structured outcomes across all crawlers with dashboards/alerts |
| Offline safety | Not demonstrated | Explicitly tested for core commands and state logic | Adapter-level offline fixtures and contract tests |
| Multi-client maturity | Claimed in architecture | Core supports it, but only Veredictum is proven | Second full client implemented to validate abstraction |
| Deduplication | Strongly claimed | Not evidenced in live runtime path | Core-enforced content-hash dedupe with regression tests |

## 15. Prioritized recommendations

1. Make deduplication a mandatory core capability, not a documented aspiration.
2. Migrate all active crawlers from string-only outcomes to structured `CrawlerResult` semantics with explicit retryability and failure causes.
3. Standardize per-crawler checkpoint schemas so resumability survives partial progress and source drift.
4. Add offline adapter tests for at least the highest-value institutional crawlers.
5. Decide whether Metacrawler is truly multi-client now or still a Veredictum-specialized system, and align docs and structure accordingly.
6. Add concurrency protection or declare single-run exclusivity explicitly in runtime docs and code.
7. Remove or quarantine non-canonical artifacts such as tracked shell history and in-tree generated plan remnants.

## 16. Confidence level and evidence limitations

### Confidence

**Moderately high** on:

- chronology,
- major architectural shifts,
- core runtime maturity,
- scheduler/state evolution,
- testing maturity.

**Moderate** on:

- operational pain behind specific fixes,
- true live-source reliability,
- deduplication effectiveness in production use.

### Main limitations

- No history before 2025-12-22.
- Sparse commit cadence compresses many changes into large snapshots.
- No external operational records.
- No live crawling executed.

## 17. Final verdict

Metacrawler began this audit period, as far as the repository can prove, as a **promising but still script-shaped acquisition engine**: ambitious, thoughtfully decomposed, and already aware of institutional crawling risks, yet still coupled to shared files, fragile persistence, and source-specific assumptions.

It has since become a **substantially more disciplined runtime core**. The strongest evidence of maturity is not cosmetic cleanup but the addition of:

- scoped runtime configuration,
- atomic persistence,
- malformed-state preservation,
- structured operational results,
- offline-safe admin commands,
- and a regression suite that actively forbids hidden network escape paths.

The creator’s growth is most visible in the transition from “architecture described” to “failure modes encoded into safeguards.” That is real engineering progress.

Metacrawler is **not yet fully ready for carefree acquisition resumption**. The core is increasingly trustworthy; several crawlers are not. The next maturity step is to bring source adapters up to the same standard the core now demonstrates.
