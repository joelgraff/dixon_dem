# Changelog
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
