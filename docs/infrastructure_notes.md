# Infrastructure

## Overhead power

`pipeline/fetch_osm.py` fetches mapped overhead power lines and support nodes.
After fetching and rebuilding vectors, `game/data/power.json` contains:

- `lines`: clipped overhead line ways, with local-space `x/y/z` vertices and
  the OSM line class, voltage, and cable-count tags. Underground and indoor
  ways are excluded.
- `supports`: mapped poles, towers, portals, terminals, and transformers
  inside the play area.

`game/infrastructure/power_network.gd` draws each line as a sagged conductor
and samples terrain elevation for pole placement. It inserts additional
supports at a regular spacing along each line so long OSM ways do not become
unsupported spans. Mapped towers use a lattice model and high-voltage lines
use taller, more widely spaced fallback supports; poles, portals, terminals,
and transformers use shorter support models. These structures and conductor
layouts are schematic rather than engineering-accurate.

Rebuild sequence: run `pipeline/fetch_osm.py` to acquire `osm_power.json`, then
run the vector build step (or `pipeline/build_all.py`) to create
`game/data/power.json`.
