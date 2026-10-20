# Style Vocabulary

The `style` field in `buildings.schema.json` references a template key from the building composer. This document tracks the canonical list of those keys so the schema and the composer stay in sync.

## Status

**Not yet populated.** The building composer is still maturing, and the key names are expected to shift. Once a stable set exists, add each key here with a one-line description and an example building in Dixon that uses it.

## Planned entries

- Roof forms: gable, hip, flat, shed, mansard (matches the `roof` enum in the schema)
- Dormer types: gable dormer, hip dormer, shed dormer, eyebrow
- Material cues already anticipated by `material_hint`: brick, vinyl, wood, stone
- Composite styles the composer can assemble, e.g. `hip_roof_gable_dormer`

## Open question

Whether style keys should be compositional (parts assembled by the renderer) or atomic (one key per full look). Compositional keys are more flexible for low-fidelity renderers that only render a subset of parts; atomic keys are simpler for a parser or point-and-click front end that just needs a noun to display.
