from __future__ import annotations

import sys
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
ICON_PATH = THIS_DIR / "icons" / "plasma_cam.svg"
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))


import FreeCADGui as Gui

for module_name in ("plasma_cam_bridge_command", "plasma_cam_bridge_core"):
    loaded_module = sys.modules.get(module_name)
    loaded_file = getattr(loaded_module, "__file__", "") if loaded_module is not None else ""
    if loaded_file and Path(loaded_file).resolve().parent != THIS_DIR:
        sys.modules.pop(module_name, None)

import plasma_cam_bridge_command


GLOBAL_TOOLBAR_OBJECT_NAME = "PlasmaCamBridgeGlobalToolbar"
GLOBAL_ACTION_OBJECT_NAME = "PlasmaCamBridgeSendSelectionAction"
SKETCHER_EDIT_TOOLBAR_OBJECT_NAME = "Edit Mode"
SKETCHER_TOOLBAR_OBJECT_NAME = "PlasmaCamBridgeSketcherToolbar"
SKETCHER_EDIT_ACTION_OBJECT_NAME = "PlasmaCamBridgeSketcherEditAction"
GLOBAL_MENU_OBJECT_NAME = "PlasmaCamBridgeMenu"
GLOBAL_MENU_ACTION_OBJECT_NAME = "PlasmaCamBridgeMenuSendSelectionAction"
GLOBAL_TOOLBAR_BREAK_PROPERTY = "PlasmaCamBridgeToolbarBreakInstalled"


def _qt_modules():
    try:
        from PySide6 import QtCore, QtGui, QtWidgets
    except Exception:
        try:
            from PySide2 import QtCore, QtGui, QtWidgets
        except Exception:
            from PySide import QtCore, QtGui

            QtWidgets = QtGui
    return QtCore, QtGui, QtWidgets


def _text_under_icon_style(QtCore):
    tool_button_style = getattr(QtCore.Qt, "ToolButtonStyle", QtCore.Qt)
    return getattr(tool_button_style, "ToolButtonTextUnderIcon")


def _text_beside_icon_style(QtCore):
    tool_button_style = getattr(QtCore.Qt, "ToolButtonStyle", QtCore.Qt)
    return getattr(tool_button_style, "ToolButtonTextBesideIcon")


def _top_toolbar_area(QtCore):
    toolbar_area = getattr(QtCore.Qt, "ToolBarArea", QtCore.Qt)
    return getattr(toolbar_area, "TopToolBarArea")


def _new_bridge_action(QtGui, QtWidgets, parent, object_name: str):
    action_class = getattr(QtGui, "QAction", None) or QtWidgets.QAction
    action = action_class(QtGui.QIcon(str(ICON_PATH)), plasma_cam_bridge_command.ACTION_TEXT, parent)
    action.setObjectName(object_name)
    action.triggered.connect(lambda _checked=False: plasma_cam_bridge_command.run_command())
    return action


def _new_bridge_button_action(QtCore, QtGui, QtWidgets, parent, object_name: str):
    widget_action_class = getattr(QtWidgets, "QWidgetAction", None) or getattr(QtGui, "QWidgetAction")
    action = widget_action_class(parent)
    action.setObjectName(object_name)
    button = QtWidgets.QToolButton(parent)
    button.setObjectName(f"{object_name}Button")
    button.setText(plasma_cam_bridge_command.ACTION_TEXT)
    button.setIcon(QtGui.QIcon(str(ICON_PATH)))
    button.setToolButtonStyle(_text_beside_icon_style(QtCore))
    button.setMinimumSize(QtCore.QSize(128, 42))
    button.setToolTip(plasma_cam_bridge_command.ACTION_TOOLTIP)
    button.setStatusTip(plasma_cam_bridge_command.ACTION_TOOLTIP)
    button.clicked.connect(lambda _checked=False: plasma_cam_bridge_command.run_command())
    action.setDefaultWidget(button)
    return action


def _configure_bridge_action(QtGui, action) -> None:
    action.setText(plasma_cam_bridge_command.ACTION_TEXT)
    action.setIconText(plasma_cam_bridge_command.ACTION_TEXT)
    action.setIcon(QtGui.QIcon(str(ICON_PATH)))
    action.setToolTip(plasma_cam_bridge_command.ACTION_TOOLTIP)
    action.setStatusTip(plasma_cam_bridge_command.ACTION_TOOLTIP)
    action.setVisible(True)
    action.setEnabled(True)


def _bridge_action(toolbar, object_name: str):
    for action in toolbar.actions():
        if action.objectName() == object_name:
            return action
    return None


def _is_button_action(QtWidgets, action) -> bool:
    widget_action_class = getattr(QtWidgets, "QWidgetAction", None)
    return widget_action_class is not None and isinstance(action, widget_action_class) and action.defaultWidget() is not None


def _install_sketcher_edit_action(QtCore, QtGui, QtWidgets, main_window) -> None:
    edit_toolbar = main_window.findChild(QtWidgets.QToolBar, SKETCHER_EDIT_TOOLBAR_OBJECT_NAME)
    if edit_toolbar is None:
        return
    old_toolbar = main_window.findChild(QtWidgets.QToolBar, SKETCHER_TOOLBAR_OBJECT_NAME)
    if old_toolbar is not None:
        try:
            main_window.removeToolBar(old_toolbar)
            old_toolbar.deleteLater()
        except Exception:
            old_toolbar.hide()
    bridge_action = _bridge_action(edit_toolbar, SKETCHER_EDIT_ACTION_OBJECT_NAME)
    if bridge_action is not None and not _is_button_action(QtWidgets, bridge_action):
        edit_toolbar.removeAction(bridge_action)
        bridge_action = None
    if bridge_action is None:
        bridge_action = _new_bridge_button_action(
            QtCore,
            QtGui,
            QtWidgets,
            edit_toolbar,
            SKETCHER_EDIT_ACTION_OBJECT_NAME,
        )
        actions = list(edit_toolbar.actions())
        if actions:
            edit_toolbar.insertAction(actions[0], bridge_action)
        else:
            edit_toolbar.addAction(bridge_action)
    _configure_bridge_action(QtGui, bridge_action)
    button = edit_toolbar.widgetForAction(bridge_action)
    if button is not None:
        button.setToolButtonStyle(_text_beside_icon_style(QtCore))
        button.setMinimumSize(QtCore.QSize(128, 42))
        button.setText(plasma_cam_bridge_command.ACTION_TEXT)
    edit_toolbar.setVisible(True)
    edit_toolbar.show()


def _remove_toolbar(QtWidgets, main_window, object_name: str) -> None:
    toolbar = main_window.findChild(QtWidgets.QToolBar, object_name)
    if toolbar is None:
        return
    try:
        main_window.removeToolBar(toolbar)
        toolbar.deleteLater()
    except Exception:
        toolbar.hide()


def _install_global_menu(QtGui, QtWidgets, main_window) -> None:
    menu_bar = main_window.menuBar()
    if menu_bar is None:
        return
    menu = main_window.findChild(QtWidgets.QMenu, GLOBAL_MENU_OBJECT_NAME)
    if menu is None:
        menu = menu_bar.addMenu("KerfGrid")
        menu.setObjectName(GLOBAL_MENU_OBJECT_NAME)
    bridge_action = None
    for action in menu.actions():
        if action.objectName() == GLOBAL_MENU_ACTION_OBJECT_NAME:
            bridge_action = action
            break
    if bridge_action is None:
        bridge_action = _new_bridge_action(QtGui, QtWidgets, menu, GLOBAL_MENU_ACTION_OBJECT_NAME)
        menu.addAction(bridge_action)
    _configure_bridge_action(QtGui, bridge_action)


def _install_global_toolbar() -> None:
    try:
        QtCore, QtGui, QtWidgets = _qt_modules()
        main_window = Gui.getMainWindow()
    except Exception:
        return
    if main_window is None:
        return
    _remove_toolbar(QtWidgets, main_window, SKETCHER_TOOLBAR_OBJECT_NAME)
    toolbar = main_window.findChild(QtWidgets.QToolBar, GLOBAL_TOOLBAR_OBJECT_NAME)
    if toolbar is None:
        toolbar = QtWidgets.QToolBar("KerfGrid", main_window)
        toolbar.setObjectName(GLOBAL_TOOLBAR_OBJECT_NAME)
        toolbar.setMovable(True)
        toolbar.setFloatable(False)
        main_window.addToolBar(_top_toolbar_area(QtCore), toolbar)
    bridge_action = _bridge_action(toolbar, GLOBAL_ACTION_OBJECT_NAME)
    if bridge_action is not None and not _is_button_action(QtWidgets, bridge_action):
        toolbar.removeAction(bridge_action)
        bridge_action = None
    if bridge_action is None:
        bridge_action = _new_bridge_button_action(QtCore, QtGui, QtWidgets, toolbar, GLOBAL_ACTION_OBJECT_NAME)
        toolbar.addAction(bridge_action)
    _configure_bridge_action(QtGui, bridge_action)
    button = toolbar.widgetForAction(bridge_action)
    if button is not None:
        button.setToolButtonStyle(_text_beside_icon_style(QtCore))
        button.setMinimumSize(QtCore.QSize(128, 42))
        button.setText(plasma_cam_bridge_command.ACTION_TEXT)
    toolbar.setVisible(True)
    toolbar.show()
    _install_sketcher_edit_action(QtCore, QtGui, QtWidgets, main_window)
    _install_global_menu(QtGui, QtWidgets, main_window)


def _install_global_toolbar_later() -> None:
    try:
        QtCore, _QtGui, _QtWidgets = _qt_modules()
    except Exception:
        _install_global_toolbar()
        return
    QtCore.QTimer.singleShot(0, _install_global_toolbar)
    QtCore.QTimer.singleShot(1500, _install_global_toolbar)


plasma_cam_bridge_command.register_command()
_install_global_toolbar_later()


class PlasmaCamBridgeWorkbench(Gui.Workbench):
    MenuText = "KerfGrid"
    ToolTip = "Export selected FreeCAD 2D geometry to the local KerfGrid nest"
    Icon = str(ICON_PATH)

    def Initialize(self):
        plasma_cam_bridge_command.register_command()
        self.appendToolbar("KerfGrid", [plasma_cam_bridge_command.COMMAND_NAME])
        self.appendMenu("KerfGrid", [plasma_cam_bridge_command.COMMAND_NAME])

    def Activated(self):
        return

    def Deactivated(self):
        return

    def GetClassName(self):
        return "Gui::PythonWorkbench"


try:
    Gui.addWorkbench(PlasmaCamBridgeWorkbench())
except Exception as exc:
    if "already exists" not in str(exc):
        raise
