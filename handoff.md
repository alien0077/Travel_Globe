# Handoff — IFR Global Route-Shapes Completion

**Updated**: 2026-07-31
**Project**: `/Users/alien/Desktop/Travel_Globe`

## Current Truth

This handoff is about the IFR/global route-shapes work from `IFR_modify.md`.
It should not be mixed with general product backlog items.

The active goal is:

1. Produce a globally useful route geometry system, not just a fallback airport-pair pack.
2. Prefer verified AviationDB/FlightGear directed airway geometry when filed/observed truth is unavailable.
3. Use IFR directed airway routing as a sanity-check layer for observed ADS-B routes.
4. Never use `great_circle_waypoint_corridor` or fake waypoint chaining as official route geometry.
5. Keep unresolved pairs explicit as `route_unavailable` unless a defensible fallback policy is accepted.

## What Is Already Done

- The directed IFR selector exists.
- Runtime reads route-shapes before falling back to Great Circle endpoint interpolation.
- Mobile runtime does not perform global graph search.
- The three IFR acceptance routes were verified through route-shapes:
  - `RCKH -> RJAA` / `KHH -> NRT`
  - `RCTP -> VHHH` / `TPE -> HKG`
  - `RCTP -> RJAA` / `TPE -> NRT`
- Key wrong-route sources were removed from official route geometry:
  - nearest-waypoint shortest path as the only connector choice
  - Great Circle corridor waypoint chaining
- OpenFlights `routes.dat` is not route geometry. It is only historical route context and missing aircraft/equipment-code fallback.
- Observed ADS-B routes are not automatically trusted. They still need IFR/corridor sanity checks before they can be considered validated route geometry.

## Important Current Inconsistency

The route-shapes artifacts are partially inconsistent, but the work order is now fixed:

1. The `19,497` fallback route-shapes run is considered done for now.
2. The `2,006` skipped fallback routes are a known later problem to solve.
3. The `162` report is a newer algorithm/diagnostic judgment for part of that problem, but it is not the next job.
4. The next job is IFR validation of the `157,769` observed ADS-B routes.
5. Only after observed ADS-B validation should the project return to solving the `2,006` fallback-route gap.

- The route-fallback source pack currently has:
  - `routes`: 177,266
  - `observedRoutes`: 157,769
  - `fallbackRoutes`: 19,497
  - `connectivityFallbackRoutes`: 1,040
- The `19,497 fallbackRoutes` have already been processed. Do not rerun all 19,497 paths now.
- The current committed/runtime route-shapes pack currently shows:
  - `routesConsidered`: 19,497
  - `routeShapes`: 17,491
  - `skipped`: 2,006
  - `directed_airway_graph`: 16,715
  - `approximate_direct_fallback`: 776
  - `route_unavailable`: 2,006
- A later diagnostic/report indicates a newer algorithm/diagnostic judgment reached:
  - `routesConsidered`: 19,497
  - `routeShapes`: 19,335
  - `skipped`: 162
  - `directed_airway_graph`: 19,335
  - `route_unavailable`: 162
- Treat the `162` result as evidence for the later `2,006` cleanup phase, not as the current top-priority task.
- The `157,769 observedRoutes` also require IFR validation/pruning. The previous `observed-route-pruning-audit` reduced raw ADS-B point weight, but the handoff must still track whether observed route geometry matches reasonable IFR/direct-corridor behavior and does not contain endpoint/merge/split mistakes.

Do not claim global route geometry is complete until:

- observed ADS-B routes are classified as validated/review-needed/rejected,
- the known `2,006` fallback-route gap is resolved or explicitly categorized with policy,
- coverage source limitations are documented.

## Remaining IFR Global Tasks

Run these in this order:

1. **Validate observed ADS-B routes with IFR sanity checks**
   - Input: `157,769` observed ADS-B routes from the current observed pack.
   - Compare each observed route against IFR/direct-corridor expectations.
   - Detect endpoint mistakes, trace merge/split mistakes, excessive detours, wrong-side routing, and severe IFR mismatch.
   - Output explicit provenance classes:
     - `observed_adsb_validated`
     - `observed_adsb_needs_review`
     - `observed_adsb_endpoint_suspect`
     - `observed_adsb_excessive_detour`
     - `observed_adsb_ifr_mismatch`
     - `observed_adsb_no_ifr_comparison`
     - `observed_adsb_no_observed_geometry` for routes whose points were already removed by the older pruning pass
   - Only validated observed routes should remain high-confidence geometry in route-source fusion.
   - This must be a detached/background job with checkpointed status. Do not foreground-poll it.

2. **Rebuild route-source fusion only after observed validation**
   - Rebuild route-source fusion from validated observed ADS-B, OpenFlights/static route graph, and connectivity fallback.
   - Re-export `global.route-fallback.json.gz`.
   - Confirm whether `fallbackRoutes` changes from `19,497`.
   - Remember: even solving all fallback pairs does not prove all worldwide commercial route coverage. It only completes the current source-derived candidate set.

3. **Solve the known `2,006` fallback-route gap**
   - Use the newer `162` diagnostic result as evidence, but do not let it distract from observed ADS-B validation.
   - Apply recoverable route-unavailable recovery only when directed edge validation still passes.
   - Decide policy for excessive-detour, short/remote, and public-airway-gap routes.
   - Do not restore approximate/fake geometry as IFR.

4. **Classify final unavailable fallback routes**
   - Produce a final `route-unavailable-diagnostics.json`.
   - Split the remaining routes into:
     - selector constraints recoverable
     - reachable but excessive detour
     - short/remote pair with no public airway path
     - public airway graph gap
     - missing airport metadata
   - For each category, decide whether it stays unavailable, needs observed ADS-B, needs approximate fallback with explicit warning, or needs licensed/public airway data.

## Background Job Policy

Long route/observed validation work must run detached.

Do not use a long foreground Codex session to poll progress.

The current completion wrapper was intentionally stopped/needs revision because it would blindly rerun the `19,497` selector. Before restarting background work, split it into narrower jobs:

1. observed ADS-B IFR validation job,
2. source fusion refresh job,
3. targeted fallback route-shapes recovery job for the known `2,006` gap.

Use:

```bash
AviationDB/scripts/run_global_route_shapes_completion_pipeline.sh
```

Only after revising it so it does not blindly rerun `19,497` paths.

Status:

```bash
AviationDB/scripts/run_global_route_shapes_completion_pipeline.sh status
```

Stop:

```bash
AviationDB/scripts/run_global_route_shapes_completion_pipeline.sh stop
```

Primary files:

- Job dir: `/private/tmp/travel-globe-global-route-shapes-completion`
- Status: `/private/tmp/travel-globe-global-route-shapes-completion/status.json`
- Log: `/private/tmp/travel-globe-global-route-shapes-completion/pipeline.log`

## Runtime Sync After Completion

When the completion pipeline finishes successfully:

1. Confirm `AviationDB/data/releases/private/route-shapes/global.route-shapes.json.gz` summary.
2. Confirm `shared/offline-packs/route-shapes/global.route-shapes.json.gz`.
3. Confirm `shared/offline-packs/route-shapes/global.route-shapes.runtime.json`.
4. Confirm `replay-engine/public/offline-packs/route-shapes/*`.
5. Confirm observed ADS-B validation output and route-source fusion no longer treats unvalidated observed routes as high-confidence geometry.
6. Run `npm --prefix replay-engine run build`.
7. Run `./scripts/copy-replay-to-ios.sh`.
8. Run web/iOS verification before commit.

## Verification Baseline

```bash
PYTHONPATH=AviationDB/src pytest AviationDB/tests/test_ifr_routing.py AviationDB/tests/test_pipeline.py
npm --prefix replay-engine run typecheck
npm --prefix replay-engine run test
npm --prefix replay-engine run build
npm --prefix replay-engine run verify:preview
./scripts/copy-replay-to-ios.sh
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcodebuild build -quiet -scheme TravelGlobe -destination 'generic/platform=iOS Simulator' -derivedDataPath /private/tmp/TravelGlobeDerived CODE_SIGNING_ALLOWED=NO
git diff --check
```

## Current Caution

The worktree is intentionally dirty with route/data/runtime changes. Do not revert unrelated files. Before commit, inspect generated packs and decide whether all generated offline assets belong in the same commit.
