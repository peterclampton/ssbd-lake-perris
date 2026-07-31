# CAD Master Level

This is the clean rebuild of the Lake Perris level.

Source priority:

1. `2026_Festival_Map_-_PE_-_7-18.dxf` controls coordinates, scale, rotation,
   footprints, fence runs, access gaps, and labels.
2. `2026 Festival Map - PE - 7-18.pdf` controls human-readable intent, aerial
   orientation, shoreline context, and ambiguous CAD symbols or layers.
3. `ssbd-lake-perris_28` controls the visual language and interaction design:
   materials, stage/tent/vendor styling, lighting, water, terrain, HUD, and
   movement.

`site-plan.json` is generated data. Do not hand-edit it. Regenerate it with:

```sh
/usr/bin/python3 tools/export_cad_level.py \
  /Users/simonsayz/Downloads/2026_Festival_Map_-_PE_-_7-18.dxf \
  cad-level/site-plan.json
```

The original production level remains at `/`. This rebuild is served from
`/cad-level/` until it is visually verified and promoted.
