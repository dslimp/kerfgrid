# FreeCAD -> KerfGrid Bridge

Sidecar integration for sending selected FreeCAD 2D geometry to the KerfGrid
nest at `http://192.168.88.61/kerfgrid/`.

The bridge exports the current FreeCAD selection to DXF, posts that DXF to
`POST http://192.168.88.61/api/workspace/import-dxf`, opens the KerfGrid web UI,
and saves a backup `.kerfgrid.json` project file. The upload appears in all
open windows without a pending slot or file picker.

## Install As FreeCAD Workbench On macOS

FreeCAD 1.x on macOS uses the versioned user directory:

```sh
mkdir -p "$HOME/Library/Application Support/FreeCAD/v1-1/Mod"
```

Copy the bridge folder:

```sh
cp -R freecad/PlasmaCamBridge \
  "$HOME/Library/Application Support/FreeCAD/v1-1/Mod/PlasmaCamBridge"
```

Older FreeCAD installs may use the non-versioned directory instead:

```sh
mkdir -p "$HOME/Library/Application Support/FreeCAD/Mod"
```

Copy the bridge folder:

```sh
cp -R freecad/PlasmaCamBridge \
  "$HOME/Library/Application Support/FreeCAD/Mod/PlasmaCamBridge"
```

Restart FreeCAD. The command is available as:

- A visible `To Nest` button with the KerfGrid icon in Sketcher's
  `Edit Mode` / `Режим редактирования` toolbar while editing a sketch.
- A visible `To Nest` button with the KerfGrid icon in the top `KerfGrid`
  toolbar.
- `KerfGrid -> To Nest` in the main menu.

A separate `KerfGrid` workbench is also registered as a fallback place for the
same command.

## Install As A Macro

For FreeCAD 1.x, copy both the macro file and the helper folder to the versioned
FreeCAD macro directory:

```sh
mkdir -p "$HOME/Library/Application Support/FreeCAD/v1-1/Macro"
cp freecad/PlasmaCamBridge.FCMacro \
  "$HOME/Library/Application Support/FreeCAD/v1-1/Macro/PlasmaCamBridge.FCMacro"
cp -R freecad/PlasmaCamBridge \
  "$HOME/Library/Application Support/FreeCAD/v1-1/Macro/PlasmaCamBridge"
```

Older FreeCAD installs may use the non-versioned macro directory:

```sh
mkdir -p "$HOME/Library/Application Support/FreeCAD/Macro"
cp freecad/PlasmaCamBridge.FCMacro \
  "$HOME/Library/Application Support/FreeCAD/Macro/PlasmaCamBridge.FCMacro"
cp -R freecad/PlasmaCamBridge \
  "$HOME/Library/Application Support/FreeCAD/Macro/PlasmaCamBridge"
```

Run `Macro -> Macros... -> PlasmaCamBridge.FCMacro`.

## Use

1. Make sure KerfGrid is reachable at `http://192.168.88.61/kerfgrid/`.
2. In FreeCAD, edit or select one `Sketcher::SketchObject`, or select several
   planar 2D objects.
3. Press `To Nest` in the Sketcher `Edit Mode` / `Режим редактирования`
   toolbar, or use `KerfGrid -> To Nest` from the menu.
4. KerfGrid opens in the browser and loads the generated project
   automatically.
5. The generated `.kerfgrid.json` backup path is copied to the clipboard.

Generated files are written to:

```text
/tmp/plasma-cam-freecad/
```

Override paths and server URL with:

```sh
export PLASMA_CAM_API_URL=http://192.168.88.61
export PLASMA_CAM_UI_URL=http://192.168.88.61/kerfgrid
export PLASMA_CAM_FREECAD_OUTPUT_DIR=/tmp/plasma-cam-freecad
```

The older `PLASMA_CAM_URL` variable is still accepted when API and UI live at
the same root, for example a workstation-local `http://127.0.0.1:8765` server.

## Current Limits

- The server owns the shared active project and original DXF files. Browser
  storage is a cache/recovery draft.
- The FreeCAD selection must be exportable by FreeCAD's DXF exporter
  (`importDXF.export` or `Draft.export` fallback).
- For 3D bodies, select a planar sketch/profile whenever possible; arbitrary 3D
  solids may export projection geometry that is not what plasma cutting expects.
