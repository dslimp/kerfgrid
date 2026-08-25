# HTTP API Contract

The local server listens on `127.0.0.1:8765` by default and serves JSON under
`/api/`.

Core endpoints:

- `POST /api/import-dxf`: DXF text plus import options to a project document.
- `POST /api/validate`: warning list for the submitted project.
- `POST /api/auto-nest`: best valid project found before the optimization limit.
- `POST /api/export`: QtPlasmaC G-code and filename.
- `POST /api/export-outline`: torch-off framing G-code.
- `POST /api/simulate`: events parsed from the generated export G-code.
- `POST /api/export-dxf`: review DXF.
- `POST /api/review-report`: machine-readable review report.

Expected operator findings use HTTP 200 and appear as warning objects or G-code
comments. HTTP 400 is reserved for malformed requests or failures that prevent
the requested artifact from being constructed at all.
