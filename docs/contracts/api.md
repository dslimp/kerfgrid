# HTTP API Contract

The local server listens on `127.0.0.1:8765` by default and serves JSON under
`/api/`.

Core endpoints:

- `POST /api/import-dxf`: DXF text plus import options to a project document.
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
short-lived OpenSSH control socket for follow-up sends, and run a LinuxCNC
Python `program_open` command as the `linuxcnc` user for the job file.
QtPlasmaC temporary material magic comments are emitted in compact form to
avoid LinuxCNC filter `Command too long` failures. The response includes
`remote_path`, `byte_count`, `files`, `uploaded`, `loaded`, optional
`load_error`, and non-blocking transfer warnings. `loaded=true` is only returned
when the remote load command succeeds.
