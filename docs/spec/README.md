# Dixon DEM Spec

Authoritative, machine-readable contract for the Dixon world model. Every renderer — 3D walk, Sierra-style rooms, top-down map, text parser — reads from this data. Nothing downstream guesses.

## Layers

### 1. Geometry (the contract)
Structured exports, one JSON schema per domain:

- `buildings.json` — footprints, styles, heights, adjacency to roads
- `roads.json` — polylines, classifications, intersections
- `terrain.json` — height grid, water, elevation bands
- `landmarks.json` — tagged points of interest with coordinates
- `interiors.json` — room graphs, doors, connections to exteriors (future)

Each entry carries an ID, geometry, and a **confidence score** so a low-fidelity renderer knows when to trust source data versus fall back to a style template.

### 2. Canon (the history)
Human-readable layer that travels with the geometry:

- Place names and their origins
- Local histories tied to specific buildings, streets, or sites
- References to photos, documents, and source material

A renderer uses canon however it fits — a Sierra game might surface a place name as an examine-able noun, a top-down map might show it as a label, a parser might accept it as a valid input the player can type.

## Relationship to existing docs

`docs/references/` holds the prose notes and photos. This folder is the structured counterpart: same facts, queryable form. When a reference note changes, the corresponding spec entry should update too.

## Schemas

Starter schemas live in this folder. They are drafts — expect the field lists to move as the composers mature.
