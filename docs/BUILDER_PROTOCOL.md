# Builder protocol (every builder agent)
1. Read docs/ARCHITECTURE.md, docs/ART_DIRECTION.md, docs/pipeline_notes.md, and any docs/*_notes.md relevant to what you consume (materials_notes.md, atmosphere_notes.md — they may not exist yet if that workstream is still running; check again later and adopt their outputs when they appear). Visual references: docs/references/ (dixon_vernacular.md, style_long_dark.md, landmark docs + img/).
2. Only write inside your owned folder(s) + docs/<workstream>_notes.md. Never run git. Never `pkill -f Godot` (it kills your own shell); kill by PID.
3. Prefer generation at import/build time (tool scripts or Python pipeline emitting .tscn/.res/.glb/.mesh) over runtime generation of large static geometry, so the game loads fast; but runtime generation is OK if it is fast (<2 s) and cached.
4. Performance: RX 580 8 GB. Chunk static geometry (~128–256 m cells), use visibility_range for LOD/HLOD, MultiMeshInstance3D for repeated items, avoid per-object materials (use instance uniforms / vertex colors for variation). Collision: simple shapes / HeightMapShape3D / trimesh per chunk.
5. Visual verification: game/tools/capture.sh (see ARCHITECTURE). Standard evaluation shots must be at player eye height (1.7 m) in real locations using Godot coords from docs/pipeline_notes.md, plus 1–2 elevated vistas. Cover at least: summer clear midday, autumn overcast, winter snow, spring rain, and one dusk/night. Save to captures/<workstream>/iterN/. LOOK at every image yourself (Read tool) and fix obvious problems before reporting.
6. Check Godot logs for SCRIPT ERROR/ERROR after every run.
7. Write/refresh docs/<workstream>_notes.md (what exists, how to regenerate, how other systems integrate, perf).
8. Final report ≤250 words: what changed, capture directory, measured FPS if relevant, known weaknesses. An independent harsh critic will review; expect iteration requests.

## Waiting for the GPU capture lock (important)
Captures are serialized by a flock and several agents may be queued, so a capture run can take far longer
than the Bash tool's 10-minute foreground cap. Don't poll in a loop and don't just stop and wait. Do this:
1. Launch the capture detached, writing a marker when it finishes:
   `nohup bash -c 'game/tools/capture.sh <scene> <shots.json> <outdir> <warmup> > <outdir>.log 2>&1; echo done > <outdir>.marker' >/dev/null 2>&1 &`
2. Then arm ONE notification with Bash `run_in_background`:
   `until [ -f <outdir>.marker ]; do sleep 10; done` — you are re-invoked when it exits.
3. On wake, check the log for `SCRIPT ERROR`/`ERROR`, then review the PNGs with Read.
