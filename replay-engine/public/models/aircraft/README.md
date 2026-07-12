# Aircraft Model Library

This folder is the canonical offline aircraft model library for Travel Globe.
Replay Engine does not generate a procedural aircraft fallback. It loads a ready model that matches the journey aircraft type; if none matches, it uses the first downloaded ready model in `library.json`. If the library has no ready downloaded model, no aircraft mesh is shown.

## Required Fleet

Travel Globe keeps slots for these aircraft types:

- A320
- A321
- B737
- B767
- B777
- B787
- A350
- A380

## License Rules

Only bundle models that satisfy all of these requirements:

- License is CC0 or CC BY.
- Commercial use is allowed.
- Derivative use is allowed.
- The model is not Editorial-only.
- The model is not NC or ND.
- Attribution includes the author, license, model URL, and source platform.
- Model file is GLB or glTF.
- Polygon count stays within the active LOD budget in `library.json` (currently 500-40k triangles).

Sketchfab downloadable Creative Commons models can be downloaded from the logged-in web UI without registering an OAuth app. Travel Globe does not use automatic OAuth downloads for this first fleet pass.

## Adding A Model

1. Use `npm --prefix replay-engine run prepare:aircraft-models -- --dry-run` to audit configured Sketchfab candidates against the public metadata API.
2. Open the model's `sourceUrl` while logged in to Sketchfab.
3. Confirm the model page shows:

   - Downloadable
   - Creative Commons Attribution / CC BY
   - Not NonCommercial
   - Not NoDerivatives
   - Not Editorial-only

4. Save a screenshot or note of the page showing author, source URL, and license.
5. Download the GLB from Sketchfab.
6. Import the GLB into the offline asset library, or run the Alien Air livery script when using the approved first-fleet source filenames in `~/Downloads`:

   `npm --prefix replay-engine run import:aircraft-model -- --aircraft a350-900 --file /path/to/a350-900.glb`

   `npm --prefix replay-engine run apply:alien-air-livery -- --all`

   The import script copies the GLB to the correct aircraft folder and marks the manifest entry as `ready` when it is within budget. The Alien Air script removes original airline paint, applies a red-and-white `ALIEN AIR` style, writes fuselage/wing/tail markings, and keeps the generated LOD0 under the active runtime budget.

7. If adding a model manually without the import script, store it in this folder, for example:

   `assets/aircraft/a380-800/a380-800-lod0.glb`

8. Update `library.json`:

   ```json
   {
     "status": "ready",
     "modelUrl": "assets/aircraft/a380-800/a380-800-lod0.glb",
     "license": "CC BY",
     "author": "Creator name",
     "sourceName": "Sketchfab",
     "sourceUrl": "https://sketchfab.com/3d-models/...",
     "attribution": "Model title by Creator name, licensed under Creative Commons Attribution via Sketchfab.",
     "commercialUse": true,
     "derivativesAllowed": true,
     "editorialOnly": false
   }
   ```

9. Run:

   `npm --prefix replay-engine run test`

## Alien Air First Fleet Status

The first downloaded Sketchfab fleet has been repainted as Alien Air with a red base, white lettering, wing branding, and tail `AA` marking. All eight first-fleet entries are runtime-ready and safe for fallback selection.

- Ready: `a320-200`, `a321neo`, `a350-900`, `a380-800`, `b737-800`, `b767-300`, `b777-300er`, `b787-9`

When `neutralizeLivery` is true, Replay Engine replaces the bundled model's material maps at runtime with the Travel Globe neutral livery. Alien Air models set `neutralizeLivery` to false because the GLB already contains the approved project livery.
