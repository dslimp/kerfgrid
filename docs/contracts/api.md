# HTTP API Contract

The local server listens on `127.0.0.1:8765` by default and serves JSON under
`/api/`.

Core endpoints:

- `GET /api/workspace`: `{revision, project, files, updated_at}` for the shared
  workspace. `?after_revision=N` returns `unchanged:true` without a project
  when nothing has changed.
- `POST /api/workspace`: `{expected_revision, project}` saves atomically.
  Stale revisions return HTTP 409 and the latest `workspace`; clients must
  retain their draft rather than overwrite silently.
- `POST /api/workspace/import-dxf`: upload and publish in one operation:
  `{filename, content, quantity:1, thickness_mm:4, request_id:"unique-id"}`.
  `content` is DXF text. Default `mode:"append"` adds parts or updates matching
  `(source_file, source_part_name)` definitions while preserving positions,
  quantities and manual leads. Outdated generated leads on updated parts are
  removed. `mode:"replace"` requires `expected_revision`. That revision field
  is optional for append imports. Reuse `request_id` for uncertain retries;
  different content/options with the same ID are rejected. Responses contain
  the shared project, revision, file ID and import summary.
- `GET /api/workspace/files`: original-upload metadata.
- `GET /api/workspace/files/<file_id>`: original DXF text as a download.

- `POST /api/import-dxf`: DXF text plus import options to a project document.
  This remains stateless for compatibility/geometry previews; use the shared
  upload endpoint to load a file into the common workspace.
- `POST /api/validate`: warning list for the submitted project.
- `POST /api/auto-nest`: best valid project found before the optimization limit.
- `POST /api/export`: QtPlasmaC G-code and filename.
- `POST /api/send-linuxcnc`: generate the same QtPlasmaC G-code as
  `/api/export`, generate a torch-off outline file, validate the generated
  G-code, upload both live files to the configured LinuxCNC machine over SSH,
  and load the job file into the running LinuxCNC interface.
- `POST /api/export-outline`: torch-off framing G-code. Dry feed uses
  `post.outline_feed_rate_mm_min` (default 3000) through the named parameter
  `#<kerfgrid_outline_feed>` and `F#<kerfgrid_outline_feed>`, independently of
  the cut-material feed table. No material substitution or filter disabling.
- `POST /api/simulate`: events parsed from the generated export G-code.
- `POST /api/export-dxf`: review DXF.
- `POST /api/review-report`: machine-readable review report.

Expected operator findings use HTTP 200 and appear as warning objects or G-code
comments. HTTP 400 is reserved for malformed requests or failures that prevent
the requested artifact from being constructed at all.

Normal DXF import is non-mutating. `auto_close_gaps` and `repair_geometry`
default to `false`; repair is only allowed when the caller explicitly enables
it. Open and invalid paths remain in the project and are exported as source
centerlines with warnings.

`POST /api/pending-project` remains a compatibility publisher for older
FreeCAD clients. `GET /api/pending-project` reads the durable shared snapshot;
it no longer consumes a one-use slot. New clients use the shared upload API.

LinuxCNC transfer reads connection settings from environment variables:
`KERFGRID_LINUXCNC_HOST`, `KERFGRID_LINUXCNC_PORT`,
`KERFGRID_LINUXCNC_USER`, `KERFGRID_LINUXCNC_REMOTE_DIR`,
`KERFGRID_LINUXCNC_KEY`, `KERFGRID_LINUXCNC_OWNER`, and
`KERFGRID_LINUXCNC_TIMEOUT_S`. `KERFGRID_LINUXCNC_CONTROL_PERSIST_S` and
`KERFGRID_LINUXCNC_CONTROL_PATH` control OpenSSH connection reuse.
`KERFGRID_LINUXCNC_LOAD_COMMAND` may override the fixed remote load command
template and receives `{remote_path}`. Defaults target the local UTM development
VM at `192.168.64.5:22`, upload fixed live files
`kerfgrid_job_live.ngc` and `kerfgrid_outline_live.ngc` to
`/home/linuxcnc/linuxcnc/nc_files/kerfgrid` through one SSH stdin stream, keep a
short-lived OpenSSH control socket for follow-up sends, and invoke the native
GUI loader as the `linuxcnc` user after checking that LinuxCNC is idle and motion
has stopped. The controller must provide `/usr/local/bin/linuxcnc-load --ini
<active-ini> <source-ngc>` or a compatible `KERFGRID_LINUXCNC_LOAD_COMMAND`.
The loader must run the QtPlasmaC filter, open through the native GUI, and verify
the filtered path through `linuxcnc.stat().file`. KerfGrid does not install that
controller helper or issue a direct NML `program_open` fallback.
QtPlasmaC temporary material magic comments are emitted in compact form to
avoid LinuxCNC filter `Command too long` failures. The response includes
`remote_path`, `byte_count`, `files`, `uploaded`, `loaded`, optional
`load_error`, `loaded_file`, and non-blocking transfer warnings. `loaded=true`
requires exit status zero, the upload marker, and a JSON-line receipt containing
`loaded: true`, `native_gui_load: true`, `source` equal to the uploaded job path,
and an absolute `loaded_file` different from the source. Exit status zero alone
is not a load acknowledgement. A missing helper or receipt reports uploaded but
not loaded; it never starts the machine.

Safe travel uses `post.safe_travel` as the master switch and
`post.travel_clearance_mm` as the clearance around completed contour outlines
and fixed zones. The browser consolidates legacy
`post.avoid_completed_contours=false` into direct mode and thereafter stores
that compatibility field as true. Export and simulation share the same routes.
An unresolved safe route produces a warning, an M0, and then the warned direct
rapid. Simulation segments expose `operator_pause_before` for that transition;
estimated time excludes the operator's pause. Direct mode emits ordinary
rapids without generated avoidance pauses.
