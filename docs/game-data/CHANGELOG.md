# Changelog

The game (docs/play.html and docs/game-data) gets a new version on every
push. The version shows in the top bar of play.html, in Settings, and with the
`version` command, so you can always tell which build you are playing.

## Versioning rules

- Every push that changes the game bumps the version. No releases or tags.
- **Patch** (0.3.0 to 0.3.1): text, dialogue, fixes, tests.
- **Minor** (0.3.0 to 0.4.0): new features, puzzles, rooms or mechanics.
- **Major** (0.x to 1.0): a whole new chapter, or when you decide it's ready.
- Bump `save_compat` in game.yaml as well when a change would break saved
  games (renamed or removed flags, items or rooms). Older saves are then
  refused with a message instead of loading half-broken.
- To bump: `cd docs/game-data/tools && npm run bump -- patch "what changed"`.
  It updates game.yaml, the `?v=` in play.html and this file together, and the
  checker fails if they ever disagree.

## 0.4.0 (2026-11-03)
- In-game guided tour: type tour (or tutorial), or Settings > Take the tour. It outlines each part of the real screen with a caption, with Next, Back and Close (Esc closes); it never touches the game state. New players are offered it once. The steps live in game.yaml. Tests can now click page elements and check what is shown.

## 0.3.2 (2026-11-03)
- Movement accepts more natural phrasings: "go down stairs", "go down the stairs", "take the stairs", "climb down the steps", "downstairs", "walk down to the water". A new test tries every exit by every name in several shapes.

## 0.3.1 (2026-11-03)
- npm run tour films a captioned video tour of play.html (every part of the screen and every setting) into tools/out/.

## 0.3.0 (2026-11-03)
- Version number in the top bar, in Settings, and from the `version` command.
- Saves record their version; a save from an incompatible version is refused
  with a message instead of being loaded.
- play.js is loaded with `?v=` so browsers fetch the new engine after a push.
- `npm run bump`, a version check in the checker, and an optional pre-push hook.
- The old prototype (index.html) links to play.html.

## 0.2.0 (2026-11-03)
- docs/play.html and docs/play.js: a browser engine that plays chapter 1 from
  the scene-card data. index.html is unchanged.
- Headless playthrough tests (tools/test.mjs, ch1/tests): the winning path to
  100 points, the wrong fix and rewind, each death, save and restore, and every
  declared phrasing.
- Fixes from playtesting: names learned from name tags and by addressing
  people by name, pronouns, `look north`, articles in the inventory, shorter
  speech tags, room text that no longer repeats unknown names.

## 0.1.0 (2026-11-03)
- Chapter 1 as scene-card data: FORMAT.md, game.yaml, sources.yaml,
  ch1/chapter.yaml and one file per room.
- tools/check.mjs validates references, flags, score and citations.
