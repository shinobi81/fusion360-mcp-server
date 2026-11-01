# Example: a bracket, end to end

A worked session showing the call shapes and the envelopes to expect. Units are
**centimetres** throughout — a 60 mm × 40 mm bracket is `6` × `4`.

Anything omitted here is in [docs/TOOLS.md](../docs/TOOLS.md).

## 1. Start a design

```json
→ new_document {"name": "bracket"}
← {"created": true, "document": "bracket", "design_type": "parametric", "ok": true}
```

`new_document` matters at a cold start: Fusion opens on the data tab with no active
design, and a document created through the UI is a Part Design document that rejects
`addNewComponent`.

## 2. Sketch the plate

```json
→ create_sketch {"plane": "xy"}
← {"sketch_name": "Sketch1", "plane": "xy", "z_offset": null, "ok": true}

→ draw_rectangle {"width": 6, "height": 4, "origin_x": 0, "origin_y": 0}
← {"sketch": "Sketch1", "width": 6, "height": 4,
   "model_origin": [0.0, 0.0, 0.0], "ok": true}
```

Note there is no `z` in play. Putting the sketch on an offset plane uses
`create_sketch(z_offset=…)`; passing `z` to a draw tool is ignored and reported back as
`ignored_z`, because sketch curves live in the sketch's own frame.

## 3. Extrude it

```json
→ extrude {"height": 0.5, "operation": "new_body"}
← {"feature_name": "Extrude1", "height": 0.5, "ok": true,
   "deltas": {"body_count_before": 0, "body_count_after": 1, "body_count_delta": 1,
              "mass_g_delta": 141.3,
              "bbox_after": {"min": [0, 0, 0], "max": [6, 4, 0.5]}}}
```

The deltas are the sanity check: `body_count_delta: 1` with a plausible mass means the
feature did something. A delta of zero would mean it silently did nothing — follow up
with `check_interference` before retrying.

## 4. Add mounting holes

```json
→ circle_batch
  draw_circles {"count": 4, "radius": 0.25, "spacing": 4.5, "axis": "x",
                "center_x": 0.75, "center_y": 0.75}
```

`draw_circles` inserts several circles in one solve. Adding them one call at a time is
superlinear — measured at 100 circles, 912 ms became 98 ms.

Extrude them as a cut, one operation per call:

```json
→ extrude {"height": 0.5, "operation": "cut"}
← {"ok": true, "deltas": {"mass_g_delta": -6.2, "body_count_delta": 0}}
```

## 5. Break the edges

```json
→ fillet {"radius": 0.1, "selection": "vertical"}
← {"ok": true, "deltas": {"mass_g_delta": 0.3}}
```

Edge selection is coarse (`all` / `top` / `bottom` / `vertical`); for a specific edge,
use `execute_code` with the entity token.

## 6. Look before you commit

```json
→ render_view {"view": "iso"}
← image content block (PNG) + a text block with camera and scene metadata
```

`render_view` returns an actual image block. Deltas tell you the feature *did*
something; a render tells you it did the *right* thing. Use it at checkpoints, not after
every call.

## 7. Measure and export

```json
→ measure_distance {"entity_one_name": "Body1", "entity_two_name": "Body2"}
← {"distance": 2.0, "ok": true}

→ export_step {"body_name": "Body1", "filepath": "C:/work/bracket.step"}
← {"exported": true, "path": "C:/work/bracket.step", "ok": true}
```

## 8. When something goes wrong

```json
→ auto_constrain
← {"ok": false,
   "error_kind": "NOT_ENTITLED",
   "error_message": "3 : AutoConstrain is not available since user is restricted",
   "hints": ["Fusion refused this API for this account — an entitlement gate, not a parameter problem.",
             "Do not retry: the identical call keeps being refused until the account's entitlement changes.",
             "Use an approach that does not need this API, or run it under a Fusion subscription that includes it."]}
```

Branch on `error_kind`, not on the message text. `NOT_ENTITLED` means retrying is
pointless. `TIMEOUT` means the main thread blocked and the command was cancelled — call
`get_scene_info` to see whether it applied before retrying, because mutations are never
retried automatically.

## 9. Undo semantics, if you need them

```json
→ undo
← {"undone": true, "verified": true, "marker_before": 4, "marker_position": 3,
   "timeline_count": 4,
   "note": "Timeline stepped back one feature; it stays in the timeline suppressed rather than being deleted. …"}
```

The feature is suppressed, not deleted: `timeline_count` does not drop, and rolling the
marker forward restores it — but creating a new feature while rolled back discards it.
On a direct-mode design there is no timeline, so `undo` reports `{"undone": "issued",
"verified": false}` and you must confirm with `get_scene_info`.
