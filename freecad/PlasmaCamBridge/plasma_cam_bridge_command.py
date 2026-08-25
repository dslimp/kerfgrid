from __future__ import annotations

from pathlib import Path

import plasma_cam_bridge_core as core


COMMAND_NAME = "PlasmaCamBridge_SendSelection"
ACTION_TEXT = "To Nest"
ACTION_TOOLTIP = "Send active Sketch or selected 2D object to KerfGrid nest"
ICON_PATH = Path(__file__).resolve().parent / "icons" / "plasma_cam.svg"


def _freecad_modules():
    try:
        import FreeCAD as App
        import FreeCADGui as Gui
    except Exception as exc:
        raise core.PlasmaCamBridgeError("This command must run inside FreeCAD GUI") from exc
    return App, Gui


def _message(title: str, text: str, *, error: bool = False) -> None:
    for module_name in ("PySide6", "PySide2", "PySide"):
        try:
            if module_name == "PySide":
                from PySide import QtGui

                box_class = QtGui.QMessageBox
            else:
                QtWidgets = __import__(module_name + ".QtWidgets", fromlist=["QMessageBox"])
                box_class = QtWidgets.QMessageBox
            break
        except Exception:
            box_class = None
    if box_class is None:
        print(f"{title}: {text}")
        return
    method = box_class.critical if error else box_class.information
    method(None, title, text)


def _copy_to_clipboard(text: str) -> bool:
    for module_name in ("PySide6", "PySide2", "PySide"):
        try:
            if module_name == "PySide":
                from PySide import QtGui

                app = QtGui.QApplication.instance()
            else:
                QtWidgets = __import__(module_name + ".QtWidgets", fromlist=["QApplication"])
                app = QtWidgets.QApplication.instance()
            if app is None:
                continue
            app.clipboard().setText(text)
            return True
        except Exception:
            continue
    return False


def selection_objects() -> list[object]:
    _, Gui = _freecad_modules()
    objects = list(Gui.Selection.getSelection() or [])
    if objects:
        return objects
    edit_object = _active_edit_object(Gui)
    return [edit_object] if edit_object is not None else []


def _active_edit_object(Gui) -> object | None:
    active_document = getattr(Gui, "ActiveDocument", None)
    getter = getattr(active_document, "getInEdit", None)
    if not callable(getter):
        return None
    try:
        item = getter()
    except Exception:
        return None
    if isinstance(item, tuple):
        item = item[0] if item else None
    item = getattr(item, "Object", item)
    return item


def selection_name(objects: list[object]) -> str:
    if not objects:
        return "freecad-selection"
    names = [str(getattr(obj, "Label", "") or getattr(obj, "Name", "") or "selection") for obj in objects]
    if len(names) == 1:
        return names[0]
    return f"{names[0]}-and-{len(names) - 1}-more"


def export_selection_to_dxf(objects: list[object], dxf_path: str | Path) -> Path:
    if not objects:
        raise core.PlasmaCamBridgeError("Select one Sketch or planar 2D object first")
    target = Path(dxf_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        import importDXF

        importDXF.export(objects, str(target))
    except Exception as first_exc:
        try:
            import Draft

            Draft.export(objects, str(target))
        except Exception as second_exc:
            raise core.PlasmaCamBridgeError(
                f"FreeCAD DXF export failed: {first_exc}; Draft fallback failed: {second_exc}"
            ) from second_exc
    if not target.exists() or target.stat().st_size <= 0:
        raise core.PlasmaCamBridgeError(f"FreeCAD DXF exporter created no file: {target}")
    return target


def send_selected_to_plasma_cam(
    *,
    server_url: str | None = None,
    output_dir: str | Path | None = None,
) -> tuple[core.PlasmaCamImportFiles, dict]:
    paths = export_selected_to_dxf(output_dir=output_dir)
    imported_project = core.import_dxf_file(paths.dxf_path, server_url=server_url)
    core.write_json(paths.project_path, imported_project)
    core.publish_pending_project(imported_project, server_url=server_url)
    return paths, imported_project


def export_selected_to_dxf(
    *,
    output_dir: str | Path | None = None,
) -> core.PlasmaCamImportFiles:
    App, _ = _freecad_modules()
    if App.ActiveDocument is not None:
        App.ActiveDocument.recompute()
    objects = selection_objects()
    paths = core.build_output_paths(selection_name(objects), root=output_dir)
    export_selection_to_dxf(objects, paths.dxf_path)
    return paths


def run_command() -> None:
    try:
        paths = export_selected_to_dxf()
        try:
            imported_project = core.import_dxf_file(paths.dxf_path)
            core.write_json(paths.project_path, imported_project)
            core.publish_pending_project(imported_project)
            core.open_plasma_cam_pending_project()
            copied = _copy_to_clipboard(str(paths.project_path))
            clip_text = "Project path copied to clipboard." if copied else "Copy the project path manually."
            _message(
                "KerfGrid",
                (
                    f"Exported DXF:\n{paths.dxf_path}\n\n"
                    f"Imported project:\n{paths.project_path}\n\n"
                    f"{core.summary_text(imported_project)}\n\n"
                    f"{clip_text}\n"
                    "KerfGrid should load this project automatically in the browser."
                ),
            )
        except Exception as import_exc:
            copied = _copy_to_clipboard(str(paths.dxf_path))
            clip_text = "DXF path copied to clipboard." if copied else "Copy the DXF path manually."
            core.open_plasma_cam()
            _message(
                "KerfGrid DXF exported",
                (
                    f"Exported DXF:\n{paths.dxf_path}\n\n"
                    f"Automatic KerfGrid import failed:\n{import_exc}\n\n"
                    f"{clip_text}\n"
                    "In KerfGrid import the generated .dxf file."
                ),
                error=True,
            )
    except Exception as exc:
        _message("KerfGrid export failed", str(exc), error=True)


class SendSelectionCommand:
    def GetResources(self):
        return {
            "MenuText": ACTION_TEXT,
            "ToolTip": ACTION_TOOLTIP,
            "Pixmap": str(ICON_PATH),
        }

    def IsActive(self):
        try:
            return bool(selection_objects())
        except Exception:
            return False

    def Activated(self):
        run_command()


def register_command() -> None:
    _, Gui = _freecad_modules()
    existing = set(Gui.listCommands()) if hasattr(Gui, "listCommands") else set()
    if COMMAND_NAME not in existing:
        Gui.addCommand(COMMAND_NAME, SendSelectionCommand())
