# Bambu slicing workflow

- Read README.md before using this toolchain. This is file-based automation, not a printer controller.
- Prefer `bambu.py doctor/inspect/prepare/slice/compare` to GUI automation.
- Preserve source geometry, dimensions, global presets and existing results. Always use new job/output folders.
- Do not treat `.gcode.3mf` as an editable model unless `inspect` reports mesh data.
- Inspect model coordinates before writing region boxes. Region boxes use original STL mm coordinates, triangle centroids and optional normal filtering. Do not claim semantic segmentation or guaranteed coverage.
- Use the user's actual printer/material/nozzle and original settings where available. Defaults are P1S / 0.4 / PLA, not universal presets.
- The support tool writes enforcer/blocker paint; Bambu generates support paths. Confirm roundtrip paint and actual support G-code, not only saved JSON values.
- Every finished slice must have verification.json with no override mismatch. Show print time/material tradeoffs and clearly state physical checks not performed.
- For directly printable sliced files use `slice --print-file` (native Bambu `--min-save`). Never rename a model-containing project to `.gcode.3mf` as a substitute. Verify no editable mesh, actual G-code, archive CRC and case-insensitive G-code MD5.
- Never send a print or change machine state through this toolchain.

# Editable multi-plate project packaging

- For arranging or packaging a Bambu 3MF project, read `3MF项目整理流程.md`. Default to files/CLI rather than desktop automation.
- Start from an explicit production BOM with quantities and a plate plan. Exclude tests, backups, prior versions and references unless specifically requested. Never glob all models into a deliverable.
- For single-filament print-oriented STL inputs, use `plate_project.py` with a project-local manifest, fresh work/check directories and a new output path. It does not repair, rescale, orient, slice or send a print.
- Use a valid native template matching the intended machine/nozzle. Do not assume P1S/0.4/PLA for unrelated projects. Keep all task-specific inputs, artifacts and reports in that project.
- Child mesh IDs must be globally unique across model files and disjoint from parent object IDs. Shared geometry is allowed only for intentional repeated instances.
- After native `--arrange 0 --export-3mf`, verify exact plate membership and quantities plus each actual mesh's face count and transformed vertex geometry against its source. Names and ZIP integrity alone are insufficient.
- Publish only after verification. A failed check must leave no final deliverable. Expose one editable production 3MF by default, with explicit sliced/unsliced status; keep logs and rejected candidates out of the delivery folder.
- This packager does not flatten colored multipart assemblies; preserve their relationships and material assignments in a dedicated workflow.
