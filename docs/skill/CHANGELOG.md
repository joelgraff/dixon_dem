# Changelog
## 2026-11-02
- 1830 anachronisms removed (chapter stays in 1830, since the panel, marker and ferry sale all depend on it): Dixon now talks about the Sauk and Fox and Saukenuk, and treats 1832 as two years off; Eli's father died in the 1827 Winnebago trouble, and his rifle is a flintlock; Dixon "came up this spring".
- Land price matches the government rate: thirty-two acres for forty dollars at $1.25 an acre.
- Hauling names whoever is present (Ogee at his landing, Dixon on the far bank) and is blocked in the chapter-end fog.
- Clicking a highlighted exit word ([path], [north], [south]) now walks that way instead of failing to examine it (only with click-to-examine on).
- Playtest fixes: the empty museum case now matches the changed exhibit panel (brass ferry token) after the chapter; inventory shows 1830 money only while in 1830; `haul` has varied lines and accepts `haul week` / `haul N` (max 6); the ferry price message mentions hauling; `go water` gives a nudge during the fog build-up and after the planks appear. Re-entering 1830 after the ending stays allowed.
## 2026-11-01
- Demo redesign: scrollback instead of clearing, prose rooms, gradual museum-to-1830 transition with fog, `?scene=` test param, lighthouse removed from the demo
- Progressive discovery (`hidden`/`reveals`), per-object verbs, topic-based `ask` for every NPC, Margaret present from the start
- Added `references/interaction-design.md`; updated parser rules and evals
- Playtest feedback applied: removed vague cues, folded the pen into the guestbook, window no longer shows the river, randomized guestbook entries, desk with a locked drawer
## 2026-10-31
- Initial skill creation: play and design modes for Dixon Sierra-style text parser adventure
- Added lighthouse prototype scene card, parser rules, design principles, and Dixon scene spine as references
- Spoken lines are attributed to the speaker; added pleasantries (thanks, hello, goodbye, how are you, sorry)
- Museum renamed Dixon Historic Center (205 W 5th St); added `references/future-hooks.md`
- Real geography: residential street, courthouse and police station, three downtown blocks, river four blocks north; Margaret introduces herself naturally and suggests signing the guestbook
- Added a looked-at sidebar (per-scene, expandable notes of examined things)
- Added a Settings panel: sidebar toggle and optional click-to-examine highlights, saved in localStorage
- Leaving or re-entering a room now includes in-character farewells and greetings
- Mobile layout: full-height flex layout on narrow screens, 16px input (no iOS zoom), safe-area padding, and a touch-only quick-command row (look, compass, up/down, examine/talk/ask prefixes, inventory)
- Water's edge transition reworked: fog builds from examining, looking at the water shifts concrete to planks, the next look around shows 1830 and Ogee's voice, answering it crosses over
- Return from 1830 is gated: the east fog only returns once both land and ferry are bought; stairs run north/south
- 1830 geography fixed: ferry landing on the south bank, far bank is north, cabins path south. Chapter end (land and ferry bought) rolls fog in anywhere; moves are blocked and Ogee guides the player back
