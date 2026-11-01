---
name: dixon-parser
description: "Play and design the Dixon Sierra-style text parser adventure. Use when starting a scene, examining historical moments, responding to look/examine/go commands, creating or editing scene cards, managing threads, or discussing the 1830s ferry prototype and later Dixon events."
type: workflow
lifecycle: active
---

# Dixon Parser — Sierra-Style Text Adventure

Interactive text-parser playthroughs and design sessions for the Dixon historical adventure, modeled on mid-80s Sierra SCI games (King's Quest 4, Space Quest 3, Gold Rush). Fixed scene spine with verb freedom inside each moment. Threads run to natural exhaustion. One-shot forks with forced reconvergence. Post-scene dossiers. Legacy bloodlines.

## Modes

### Play Mode
Start or continue a scene. Respond to commands in the established style: short, sensory, period-accurate, no anachronisms. Use the active scene card as the dictionary. Always clarify ambiguity rather than guess. Informational failures ("the rope is too short") not bare "you can't."

**Core commands to support:**
- look around / look [direction] / look at [object]
- examine [object] (aliases via scene card)
- go [direction/exit]
- talk to [npc]
- take / open / use (where defined)
- goals (spoken status recap)
- inventory

**Playable web demo:** Starts in the present-day museum and follows the 1830 ferry thread; `../index.html` is the GitHub Pages entry point. The lighthouse cottage remains a selectable parser test scene, documented in `references/lighthouse-scene.md`.

**Dixon spine scenes** (to be expanded): 1830 Ogee ferry / Dixon arrival, 1843 Joseph Smith arrest, 1873 Truesdell collapse, etc. Load relevant historical notes from references when a scene is active.

### Design Mode
Create or edit scene cards, define threads, update canon notes, sketch forks and reconvergence points. Scene cards use the six-field format: Location, Era, Sensory Details, Interactive Objects (with aliases), Entry/Exit Points, Planted Hook.

When editing, propose the updated card in full and confirm before treating it as canonical.

## Parser Rules
- Scene card is the runtime dictionary. Nouns resolve against its object list + aliases.
- Fuzzy match with clarification on ambiguity (default).
- Verb softening via synonym table (get/grab → take, check/inspect → examine).
- 40-character input buffer constraint: tolerate truncation.
- Threads: a line of interaction that runs to a clear end, then waits. Multiple open, pull one at a time.
- Abandoned threads leave scars (world slightly colder later) rather than hard blocks.

## Resources
- `references/lighthouse-scene.md` — active prototype scene card
- `references/parser-rules.md` — full matching layers and failure categories
- `references/design-principles.md` — forks, dossiers, bloodlines, load-bearing events
- `references/dixon-spine.md` — proposed historical scene list
- `museum-gauge.md` — present-day start, return, and visible historical changes
- `story-spine.md` — intended scene sequence and player role

Load the relevant reference when entering a mode or starting a specific scene.
