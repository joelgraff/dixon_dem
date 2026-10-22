# Parser Spec — Pipeline Prototype

## Grammar
Verb optionally followed by a noun phrase. Verbs: look, examine, go, take, open, talk. Nouns resolved at runtime from the scene card's object list — the card is the dictionary.

## Matching Layers
1. **Synonym expansion** — every object carries aliases built from playtesting, not guesswork. "Look at the light" hits lantern.
2. **Fuzzy matching with confidence bands** — exact match wins silently. Near-match above threshold resolves silently. Below threshold but above a floor, offer top two candidates ("did you mean the lantern or the lighthouse?"). Clarifying is the default on ambiguity.
3. **Verb softening** — get/grab/pick up map to take; check/inspect/study map to examine. ~20 synonym entries per verb covers most failure cases.

## Failure Categories
- Unknown verb: "you don't know how to do that" with a nudge toward available verbs
- Unknown noun in known verb context: "you don't see that here"
- Ambiguous noun: "which one?" — always clarify rather than guess

## Vocabulary Format
- Verb entry: canonical name, synonym list, handler it dispatches to
- Noun entry: canonical name, aliases, which scene cards reference it
- Both are data files loaded at startup — growing vocabulary is editing data, not changing code

## SCI Input Buffer Constraint
SCI's input buffer caps at 40 characters. Matcher must tolerate truncated phrases — "examine the" should still resolve before the buffer cuts off the noun. Pushes toward short, punchy commands.

## LSCI Implementation Split
- Loader, matcher, dispatcher: LSCI (file I/O, strings, arrays available)
- Fuzzy matching: precompute alias and near-match tables in Python, ship as a resource; LSCI does cheap indexed lookups at runtime
- Phase one's Python prototype doubles as the table generator — build once, run twice
- Handlers are methods on the room object returning response text
