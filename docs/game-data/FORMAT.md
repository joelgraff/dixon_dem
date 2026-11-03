# Scene-card format

The game's content lives here as YAML data. The browser runtime reads it; the
runtime holds no story text of its own. Writing a room's text now also writes
the art brief for the picture that may later replace it.

Run the checker after every change:

```
cd docs/game-data/tools && npm install && node check.mjs
```

## Files

```
game-data/
  FORMAT.md            this file
  game.yaml            verbs, narrator defaults, meta commands (all chapters)
  sources.yaml         sources (S1, S2...) and the claims ledger (C1, C2...)
  ch1/
    chapter.yaml       flags and score, items, variables, deaths, chapter-wide actions
    rooms/<room>.yaml  one file per room
  tools/check.mjs      validator
```

## Text

A text field is either a plain string or a **variant list**. The runtime shows
the first variant whose `when` holds; a variant with no `when` is the default
and must come last.

```yaml
look:
  - when: [1830.lease_dixon]
    text: The panel is whole.
  - text: The paragraph ends a line short.
```

A variant may carry `do:` effects that run when it is shown (used for the fog,
where looking is what moves things on).

Markup inside text:

| Markup | Meaning |
| --- | --- |
| `[cases]` | A lookable noun, by id or alias, in this room. The checker requires every bracket to resolve. |
| `[emptycase\|empty case]` | Same, showing different words. |
| `[ogee]` | An NPC id shows that NPC's current name: `unknown` until `known.<id>` is set, then `name`. |
| `{town}` | A chapter variable (see `vars` in chapter.yaml). |
| `{money}`, `{score}`, `{max_score}` | Live values. |
| `{picked}` | Random entries from the noun's `pick` pool (see Nouns). |

The runtime capitalizes a bracket that starts a sentence, so `[ogee] stands
by the river` reads "A man in a buckskin shirt stands by the river" until the
player learns his name.

Every noun the prose mentions should be bracketed and defined, because
everything described is lookable. Highlighting (`key: true`) is separate.

## Conditions: `when`

A list; every entry must hold. (YAML reads a leading `!` as a tag, so negation is the word `not`.)

| Entry | Holds when |
| --- | --- |
| `1830.canoe_tarred` | the flag is set |
| `not 1830.canoe_tarred` | the flag is not set (`not` works before any entry) |
| `has:rope` | the player carries the item |
| `here:ogee` | that NPC is visible in the current room |
| `in:landing` | the player is in that room |
| `era:1830` | the current room belongs to that era |
| `money>=100` | compare `money`, `score`, `turns` (turns in this room) or `n` (a number typed in the command) with `>= <= == > <` |
| `{any: [a, b]}` | at least one of the nested conditions holds |

## Effects: `do`

A list of one-key maps, run in order.

| Effect | Does |
| --- | --- |
| `set: flag` / `clear: flag` | set or clear a flag (or a list of flags) |
| `give: item` / `take: item` | add or remove an inventory item |
| `money: 40` / `money: -n` | change the purse (`n` = the typed number) |
| `reveal: noun` | make a hidden noun in this room findable |
| `say: text` | print a line (text variants allowed) |
| `move: room` | go to a room (no farewell lines) |
| `death: id` | show that death and the Restore / Restart / Retry prompt |
| `rewind: 1830` | clear every `1830.` flag and 1830 item, set money to 0, take back their points |
| `if: {when: [...], do: [...]}` | conditional effects |

**Score** is never awarded by an effect. chapter.yaml lists the flags that
score; the points are given the first time the flag is set, and taken back if
a rewind clears it.

Flag prefixes: `present.` (the present day), `1830.` (cleared by a rewind),
`known.` (names the player has learned; never cleared), `chapter1.`.

## Rooms

```yaml
id: landing
era: 1830                  # present | 1830
name: The ferry landing, 1830
sources: [S1, S2, S4]      # ids from sources.yaml, for the histories panel
picture: >-                # art brief for the later picture
  ...
look: ...                  # text or variants; the room's fixed description
listen: ...                # optional
nouns:   {id: noun, ...}
npcs:    {id: npc, ...}
exits:   [exit, ...]
actions: [action, ...]     # puzzle actions that belong to this room
on_turn: [{when: [...], say: ..., do: [...]}]   # checked after each turn spent here
```

The room description the player sees is `look`, then the `room_line` of each
visible noun and NPC that has one, in file order. Objects that change between
states (the pedestal, the clock) put their changing sentence in `room_line`,
so the description always matches the state.

### Nouns

```yaml
pedestal:
  name: pedestal                # shown in clarifications and the sidebar
  aliases: [plinth, stand]
  key: true                     # highlighted in Key-items mode
  hidden: true                  # not a target until revealed
  when: [not 1830.shoe_returned]   # visible only while this holds
  look: ...                     # text or variants
  room_line: ...                # optional sentence added to the room text
  reveals: [card]               # looking at it reveals these nouns
  on_look: [{set: present.panel_read}]   # effects run every time it is looked at
  pick:                         # random entries for {picked} in its text
    count: 3
    from: [...]
    also: [{when: [...], from: [...]}]   # extra entries once a condition holds
  verbs:
    touch: The velvet is cool.  # a natural verb: text, or {when, say, do}, or a variant list
```

### NPCs

```yaml
ogee:
  name: Joseph Ogee
  unknown: the man in buckskin  # used until known.ogee is set
  aliases: [ferryman, man in buckskin, joseph]
  when: [not 1830.fog]
  look: ...
  room_line: ...
  talk:                         # variants; the first talk usually sets known.<id>
    - when: [not known.ogee]
      text: ...
      do: [{set: [known.ogee, 1830.met_ogee]}]
    - text: ...
  topics:
    - keys: [rope, river, high water]    # whole words
      when: [...]
      say: ...
      do: [...]
  fallback: ...                 # unknown topics, in character
  social: {hello: ..., thanks: ..., bye: ..., how: ..., sorry: ...}
  parting: ...                  # said when the player leaves the room
```

Speaker attribution ("Ogee says, ...") is added by the runtime when a spoken
line starts with a quotation mark. Never write the speaker into the line
itself.

### Exits

```yaml
- names: [south, path, cabin]
  to: cabin
  when: [...]                   # otherwise `blocked` is printed
  blocked: ...
  text: You walk up the path.
  peek: The path climbs toward woodsmoke.   # answer to "look south"
  farewell: false               # skip the parting line
```

An exit with no `to` is a direction that is always blocked; its `blocked`
text explains why. `blocked` may be a variant list.

### Actions

Puzzle actions are declared where they happen, with every phrasing the parser
must accept. Phrasings are matched whole, after lower-casing, trimming and
dropping `the`, `a`, `an`. `{n}` matches a number; quote any phrase that contains it (`"give dixon {n}"`), because YAML reads bare braces as a map.

```yaml
- id: tar_canoe
  phrases: [tar canoe, tar the seam, patch canoe, fix canoe, use tar on canoe]
  when: [not 1830.canoe_tarred]
  do:
    - set: 1830.canoe_tarred
    - say: You work the hot tar into the split...
  else:                         # first matching entry when `when` fails
    - when: [1830.canoe_tarred]
      say: The seam is already tarred.
    - do: [{death: canoe_sinks}]  # an else entry may run effects instead of, or as well as, saying something
```

Order of matching: room actions, then chapter actions, then NPC
conversation, then verb + noun, then meta commands.

chapter.yaml has an `actions` list in the same shape for actions that work in
several rooms (following Ogee home, swimming).

## Chapter

`chapter.yaml` holds the chapter's id and title, the start room, `max_score`,
the scoring flags, `vars`, `items` (an item with `era: 1830` is removed by a
rewind), `deaths`, the fog lock (exits blocked and a line added to every 1830
room while it holds), chapter-wide actions, and `npcs` who move between rooms.
A moving NPC has an `at` variant list instead of living in one room file:

```yaml
npcs:
  asa:
    at:
      - when: [1830.wagon_free]
        room: landing
      - room: slough
```

## Sources

`sources.yaml` lists each source once with an id, a title, a URL and what it
supports, and the claims ledger: each claim with its status (`record`,
`disputed`, `guess`, `invented`, `needs-source`), the rooms it appears in and
its source ids. A room's `sources` list is what the optional histories panel
shows. Any new historical claim gets a ledger entry in the same change.
