# RegionSwipeDesigner_v8.py
# Features: Dark/Light Theme, ZomBroX Script Format, Reset Swipe, File Select, Color/Grey Snap Toggle
# Added: Color Picker (Dialog + Eyedropper from canvas) + Copy-to-clipboard

from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Dict, Tuple, Optional, List
import os, json, sys

import qtawesome as qta
from PyQt6.QtCore import Qt, QRect, QPoint, QSize
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QPixmap, QImage
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter, QFileDialog, QMessageBox, QInputDialog,
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton, QCheckBox,
    QSpinBox, QDoubleSpinBox, QListWidget, QTextEdit, QSlider, QToolButton,
    QSizePolicy, QScrollArea, QColorDialog
)

APP_TITLE = "Region & Swipe Designer v8 (Theme + ZomBroX Gen) + Color Picker"
DEFAULT_W, DEFAULT_H = 720, 1520

# -----------------------------
# Custom Widgets
# -----------------------------
class CollapsibleBox(QWidget):
    def __init__(self, title="", parent=None):
        super().__init__(parent)
        self.toggle_btn = QToolButton(text=f" ▼  {title}", checkable=True, checked=True)
        self.toggle_btn.setStyleSheet("""
            QToolButton {
                border: none; font-weight: bold;
                text-align: left;
                background: #f97316;
                color: #ffffff;
                padding: 8px 10px;
                border-radius: 4px;
                width: 100%;
            }
            QToolButton:hover { background: #fb923c; }
            QToolButton:checked { background: #f97316; }
        """)
        self.toggle_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.toggle_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.toggle_btn.clicked.connect(self.on_toggle)

        self.content_area = QWidget()
        self.content_layout = QVBoxLayout(self.content_area)
        self.content_layout.setSpacing(6)
        self.content_layout.setContentsMargins(4, 4, 4, 4)

        lay = QVBoxLayout(self)
        lay.setSpacing(0)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.toggle_btn)
        lay.addWidget(self.content_area)

    def on_toggle(self):
        checked = self.toggle_btn.isChecked()
        arrow = "▼" if checked else "▶"
        text = self.toggle_btn.text()[3:]
        self.toggle_btn.setText(f" {arrow}  {text}")
        self.content_area.setVisible(checked)

    def addLayout(self, layout):
        self.content_layout.addLayout(layout)

    def addWidget(self, widget):
        self.content_layout.addWidget(widget)


# -----------------------------
# Core data model
# -----------------------------
@dataclass
class RegionRect:
    name: str
    x: int
    y: int
    w: int
    h: int
    custom: bool = False

    def bounds(self) -> Tuple[int, int, int, int]:
        return (self.x, self.y, self.x + self.w, self.y + self.h)

    def clamp(self, px: int, py: int) -> Tuple[int, int]:
        x1, y1, x2, y2 = self.bounds()
        return (min(max(px, x1), x2), min(max(py, y1), y2))

    def to_dict(self):
        return asdict(self)


def compute_regions(screen_w: int, screen_h: int) -> Dict[str, RegionRect]:
    presets = [
        ("Upper_Half",         lambda W, H: (0, 0, W, H // 2)),
        ("Lower_Half",         lambda W, H: (0, H // 2, W, H // 2)),
        ("Upper_Left",         lambda W, H: (0, 0, W // 2, H // 2)),
        ("Upper_Right",        lambda W, H: (W // 2, 0, W // 2, H // 2)),
        ("Lower_Left",         lambda W, H: (0, H // 2, W // 2, H // 2)),
        ("Lower_Right",        lambda W, H: (W // 2, H // 2, W // 2, H // 2)),
        ("Home_Screen_Region", lambda W, H: (W // 2 - 20, 0, 40, 40)),
        ("Lower_Most_Half",    lambda W, H: (0, H - H // 14, W, H // 14)),
        ("Agnes_Region",       lambda W, H: (0, int(H * 0.08), int(W * 0.30), int(H * 0.42))),
        ("Main",               lambda W, H: (0, 0, W, H // 2)),
    ]
    d: Dict[str, RegionRect] = {}
    for n, fn in presets:
        x, y, w, h = fn(screen_w, screen_h)
        d[n] = RegionRect(n, x, y, w, h, custom=False)
    return d


# -----------------------------
# Canvas widget
# -----------------------------
class Canvas(QWidget):
    def __init__(self, parent: "MainWindow"):
        super().__init__(parent)
        self.mw = parent
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setMinimumSize(QSize(100, 100))

        self.screen_w, self.screen_h = DEFAULT_W, DEFAULT_H
        self.scale_to_fit = 1.0
        self.offset_fit_x = 0
        self.offset_fit_y = 0
        self.zoom_factor = 1.0
        self.pan_offset_x = 0
        self.pan_offset_y = 0
        self.panning = False
        self.pan_last = QPoint()

        self.bg_image: Optional[QImage] = None
        self.bg_image_path: Optional[str] = None
        self.regions: Dict[str, RegionRect] = compute_regions(self.screen_w, self.screen_h)
        self.selected_region: Optional[RegionRect] = self.regions.get("Upper_Right")

        self.snap_constrain_clicks = True
        self.region_creation_mode = False
        self.region_start: Optional[QPoint] = None
        self.region_preview: Optional[QPoint] = None
        self.snap_mode = False
        self.snap_start: Optional[QPoint] = None
        self.snap_preview: Optional[QPoint] = None
        self.swipe_start: Optional[QPoint] = None
        self.swipe_end: Optional[QPoint] = None

        # NEW: Eyedropper mode
        self.color_pick_mode = False

    def fit_view(self):
        cw = max(1, self.width())
        ch = max(1, self.height())
        self.scale_to_fit = min(cw / self.screen_w, ch / self.screen_h)
        disp_w = int(self.screen_w * self.scale_to_fit)
        disp_h = int(self.screen_h * self.scale_to_fit)
        self.offset_fit_x = (cw - disp_w) // 2
        self.offset_fit_y = (ch - disp_h) // 2
        self.zoom_factor = 1.0
        self.pan_offset_x = 0
        self.pan_offset_y = 0
        self.update()

    def set_zoom_percent(self, pct: int):
        pct = max(10, min(1000, pct))
        self.zoom_factor = pct / 100.0
        self.update()

    def actual_scale(self) -> float:
        return self.scale_to_fit * self.zoom_factor

    def final_offsets(self) -> Tuple[int, int]:
        return self.offset_fit_x + self.pan_offset_x, self.offset_fit_y + self.pan_offset_y

    def canvas_to_screen(self, cx: int, cy: int) -> Tuple[int, int]:
        scale = self.actual_scale()
        offx, offy = self.final_offsets()
        if scale == 0:
            return 0, 0
        sx = int((cx - offx) / scale)
        sy = int((cy - offy) / scale)
        return sx, sy

    def resizeEvent(self, _e):
        self.fit_view()

    def wheelEvent(self, e):
        delta = e.angleDelta().y()
        factor = 1.1 if delta > 0 else 0.9
        new_zoom = max(0.1, min(self.zoom_factor * factor, 10.0))
        mx, my = e.position().x(), e.position().y()
        sx_before, sy_before = self.canvas_to_screen(int(mx), int(my))
        self.zoom_factor = new_zoom
        scale = self.actual_scale()
        new_px = self.offset_fit_x + sx_before * scale
        new_py = self.offset_fit_y + sy_before * scale
        self.pan_offset_x = int(mx - new_px)
        self.pan_offset_y = int(my - new_py)
        self.update()
        self.mw.zoom_slider.blockSignals(True)
        self.mw.zoom_slider.setValue(int(self.zoom_factor * 100))
        self.mw.zoom_label.setText(f"{int(self.zoom_factor * 100)}%")
        self.mw.zoom_slider.blockSignals(False)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.RightButton:
            self.panning = True
            self.pan_last = e.pos()
            return

        # NEW: Eyedropper (pick pixel from image)
        if self.color_pick_mode:
            self.color_pick_mode = False
            self.setCursor(Qt.CursorShape.ArrowCursor)

            px, py = self.canvas_to_screen(e.pos().x(), e.pos().y())
            if self.bg_image is None:
                QMessageBox.warning(self, "Eyedropper", "No background image loaded!")
                return

            px = max(0, min(px, self.bg_image.width() - 1))
            py = max(0, min(py, self.bg_image.height() - 1))
            col = QColor(self.bg_image.pixel(px, py))
            self.mw.on_canvas_color_picked(col)
            return

        px, py = self.canvas_to_screen(e.pos().x(), e.pos().y())
        if self.snap_constrain_clicks and self.selected_region and not (self.snap_mode or self.region_creation_mode):
            px, py = self.selected_region.clamp(px, py)

        if self.snap_mode:
            self.snap_start = QPoint(px, py)
            self.snap_preview = QPoint(px, py)
        elif self.region_creation_mode:
            self.region_start = QPoint(px, py)
            self.region_preview = QPoint(px, py)
        else:
            if self.swipe_start is None:
                self.swipe_start = QPoint(px, py)
            else:
                self.swipe_end = QPoint(px, py)
            if self.mw:
                self.mw.update_swipe_spinners_from_canvas()

        self.update()
        self.mw.refresh_output()

    def mouseMoveEvent(self, e):
        if self.panning:
            d = e.pos() - self.pan_last
            self.pan_last = e.pos()
            self.pan_offset_x += d.x()
            self.pan_offset_y += d.y()
            self.update()
            return

        px, py = self.canvas_to_screen(e.pos().x(), e.pos().y())
        if self.snap_mode and self.snap_start:
            self.snap_preview = QPoint(px, py)
            self.update()
        elif self.region_creation_mode and self.region_start:
            self.region_preview = QPoint(px, py)
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.RightButton:
            self.panning = False
            return

        px, py = self.canvas_to_screen(e.pos().x(), e.pos().y())
        if self.snap_mode and self.snap_start:
            sx, sy = self.snap_start.x(), self.snap_start.y()
            x = min(sx, px)
            y = min(sy, py)
            w = abs(px - sx)
            h = abs(py - sy)
            self.snap_mode = False
            self.snap_start = None
            self.snap_preview = None
            if w < 5 or h < 5:
                return
            if self.bg_image is None:
                QMessageBox.critical(self, "Error", "No background image loaded!")
                self.update()
                return
            snap_name, ok = QInputDialog.getText(self, "Snapshot Name", "Enter a name for this snapshot:")
            if ok and snap_name:
                cropped = self.bg_image.copy(QRect(x, y, w, h))
                self.mw.save_snapshot_qimage(cropped, snap_name, x, y, w, h)
            self.update()
            return

        if self.region_creation_mode and self.region_start:
            sx, sy = self.region_start.x(), self.region_start.y()
            x = min(sx, px)
            y = min(sy, py)
            w = abs(px - sx)
            h = abs(py - sy)
            self.region_creation_mode = False
            self.region_start = None
            self.region_preview = None
            if w < 5 or h < 5:
                self.update()
                return
            name, ok = QInputDialog.getText(self, "Region Name", "Enter a name for this region:")
            if ok and name:
                if name in self.regions:
                    QMessageBox.critical(self, "Error", f"Region '{name}' already exists.")
                else:
                    reg = RegionRect(name, x, y, w, h, custom=True)
                    self.regions[name] = reg
                    self.selected_region = reg
                    self.mw.repopulate_regions(self.regions, active=name)
                    self.mw.refresh_output()
            self.update()
            return

    def paintEvent(self, _e):
        p = QPainter(self)

        # Theme-aware background
        bg_col = QColor("#1e293b") if self.mw.is_dark else QColor("#e5e7eb")
        p.fillRect(self.rect(), bg_col)

        scale = self.actual_scale()
        offx, offy = self.final_offsets()
        screen_rect_w = int(self.screen_w * scale)
        screen_rect_h = int(self.screen_h * scale)

        # Phone background
        p.fillRect(offx, offy, screen_rect_w, screen_rect_h, QColor("#ffffff"))

        if self.bg_image:
            target_pix = QPixmap.fromImage(
                self.bg_image.scaled(
                    self.screen_w,
                    self.screen_h,
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            disp_pix = target_pix.scaled(
                screen_rect_w,
                screen_rect_h,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            p.drawPixmap(offx, offy, disp_pix)

        pen = QPen(QColor("#9ca3af"))
        pen.setWidth(1)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(offx, offy, screen_rect_w, screen_rect_h)

        if self.selected_region and not (self.region_creation_mode or self.snap_mode):
            x1, y1, x2, y2 = self.selected_region.bounds()
            dx1 = int(x1 * scale) + offx
            dy1 = int(y1 * scale) + offy
            w = int((x2 - x1) * scale)
            h = int((y2 - y1) * scale)
            pen = QPen(QColor("#f97316"))
            pen.setWidth(2)
            p.setPen(pen)
            p.drawRect(dx1, dy1, w, h)
            p.drawText(dx1, dy1 - 5, self.selected_region.name)

        if self.region_creation_mode and self.region_start and self.region_preview:
            self._draw_selection(p, self.region_start, self.region_preview, scale, offx, offy, "#3b82f6")
        elif self.snap_mode and self.snap_start and self.snap_preview:
            self._draw_selection(p, self.snap_start, self.snap_preview, scale, offx, offy, "#a855f7")

        if self.swipe_start:
            sx, sy = self.swipe_start.x(), self.swipe_start.y()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#ef4444"))
            p.drawEllipse(QPoint(int(sx * scale) + offx, int(sy * scale) + offy), 5, 5)

        if self.swipe_end:
            ex, ey = self.swipe_end.x(), self.swipe_end.y()
            p.setBrush(QColor("#22c55e"))
            p.drawEllipse(QPoint(int(ex * scale) + offx, int(ey * scale) + offy), 5, 5)

        if self.swipe_start and self.swipe_end:
            sx, sy = self.swipe_start.x(), self.swipe_start.y()
            ex, ey = self.swipe_end.x(), self.swipe_end.y()
            p.setPen(QPen(QColor("#1f2937"), 2, Qt.PenStyle.DashLine))
            p.drawLine(
                int(sx * scale) + offx,
                int(sy * scale) + offy,
                int(ex * scale) + offx,
                int(ey * scale) + offy,
            )

    def _draw_selection(self, p, start, end, scale, offx, offy, color_hex):
        sx, sy = start.x(), start.y()
        px, py = end.x(), end.y()
        x1 = int(min(sx, px) * scale) + offx
        y1 = int(min(sy, py) * scale) + offy
        w = int(abs(sx - px) * scale)
        h = int(abs(sy - py) * scale)
        pen = QPen(QColor(color_hex))
        pen.setWidth(2)
        pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(x1, y1, w, h)


# -----------------------------
# MainWindow
# -----------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1400, 950)

        self.snap_folder = os.path.join(os.getcwd(), "snapshots")
        self.actions: List[dict] = []
        self.undo_stack: List[Tuple[int, dict]] = []
        self.is_dark = False  # State for theme
        self.icon_targets: Dict[str, Tuple[QPushButton, str, Optional[str], Optional[int]]] = {}

        # NEW: picked color state
        self._picked_color_hex: Optional[str] = None
        self._picked_color_rgb: Tuple[int, int, int] = (0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left_widget = QWidget()
        right_widget = QWidget()
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        self.setCentralWidget(splitter)

        # ---- LEFT PANEL ----
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_content = QWidget()  # Store ref for styling
        self.scroll_content.setObjectName("scrollContent")
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(10, 10, 10, 10)
        self.scroll_layout.setSpacing(12)
        scroll.setWidget(self.scroll_content)
        left_layout.addWidget(scroll)

        # 1. Profiles
        profile_box = CollapsibleBox("Profiles & Screen Res")

        res_layout = QHBoxLayout()
        res_layout.addWidget(QLabel("W:"))
        self.res_w = QSpinBox()
        self.res_w.setRange(100, 10000)
        self.res_w.setValue(DEFAULT_W)
        res_layout.addWidget(self.res_w)
        res_layout.addWidget(QLabel("H:"))
        self.res_h = QSpinBox()
        self.res_h.setRange(100, 10000)
        self.res_h.setValue(DEFAULT_H)
        res_layout.addWidget(self.res_h)
        btn_apply_res = QPushButton("Set")
        btn_apply_res.setToolTip("Apply the custom screen resolution")
        btn_apply_res.setMinimumWidth(70)
        btn_apply_res.setFixedHeight(34)
        res_layout.addWidget(btn_apply_res)

        self.btn_theme = QPushButton("🌗")
        self.btn_theme.setMinimumWidth(46)
        self.btn_theme.setFixedHeight(34)
        self.btn_theme.setToolTip("Toggle dark/light theme")
        self.btn_theme.clicked.connect(self.toggle_theme)
        res_layout.addWidget(self.btn_theme)

        profile_box.addLayout(res_layout)

        prof_btns = QHBoxLayout()
        btn_save = QPushButton("Save Profile")
        btn_load = QPushButton("Load Profile")
        prof_btns.addWidget(btn_save)
        prof_btns.addWidget(btn_load)
        profile_box.addLayout(prof_btns)

        img_btns = QHBoxLayout()
        btn_upload = QPushButton("Upload Bg Image")
        btn_reset = QPushButton("Reset All")
        img_btns.addWidget(btn_upload)
        img_btns.addWidget(btn_reset)
        profile_box.addLayout(img_btns)
        self.scroll_layout.addWidget(profile_box)

        # 2. Regions
        reg_box = CollapsibleBox("Regions & Snaps")
        r1 = QHBoxLayout()
        self.region_box = QComboBox()
        r1.addWidget(self.region_box, 1)
        btn_add_reg = QPushButton("Add Region")
        btn_add_reg.setToolTip("Create a new custom region")
        btn_add_reg.setMinimumWidth(110)
        btn_add_reg.setFixedHeight(32)
        btn_del_reg = QPushButton("Delete Region")
        btn_del_reg.setToolTip("Delete the selected region")
        btn_del_reg.setMinimumWidth(110)
        btn_del_reg.setFixedHeight(32)
        r1.addWidget(btn_add_reg)
        r1.addWidget(btn_del_reg)
        reg_box.addLayout(r1)

        self.constrain_chk = QCheckBox("Constrain clicks to region")
        self.constrain_chk.setChecked(True)
        reg_box.addWidget(self.constrain_chk)

        r2 = QHBoxLayout()
        btn_snap_sel = QPushButton("Snap Selection")
        btn_snap_reg = QPushButton("Snap Region")
        r2.addWidget(btn_snap_sel)
        r2.addWidget(btn_snap_reg)
        reg_box.addLayout(r2)

        r3 = QHBoxLayout()
        self.chk_exact = QCheckBox("Exact Name")
        self.chk_exact.setChecked(True)
        r3.addWidget(self.chk_exact)

        # NEW: checkbox to choose grey snaps
        self.chk_gray_snap = QCheckBox("Grey Snap")
        r3.addWidget(self.chk_gray_snap)

        btn_folder = QPushButton("Folder")
        r3.addWidget(btn_folder)
        reg_box.addLayout(r3)
        self.scroll_layout.addWidget(reg_box)

        # 2.5 Color Picker (NEW)
        color_box = CollapsibleBox("Color Picker")

        c1 = QHBoxLayout()
        c1.addWidget(QLabel("Picked:"))

        self.color_preview = QLabel("")
        self.color_preview.setFixedSize(60, 24)
        self.color_preview.setStyleSheet("background:#ffffff; border:1px solid #cbd5e1; border-radius:4px;")
        c1.addWidget(self.color_preview)

        self.color_value = QLabel("#FFFFFF  (255,255,255)")
        c1.addWidget(self.color_value, 1)

        btn_pick_dialog = QPushButton("Pick…")
        btn_pick_canvas = QPushButton("Eyedropper")
        btn_copy_color = QPushButton("Copy")
        c1.addWidget(btn_pick_dialog)
        c1.addWidget(btn_pick_canvas)
        c1.addWidget(btn_copy_color)

        color_box.addLayout(c1)
        self.scroll_layout.addWidget(color_box)

        # 3. Action Builder
        act_box = CollapsibleBox("Action Builder")
        a1 = QHBoxLayout()
        self.action_type = QComboBox()
        self.action_type.addItems([
            "click", "clickimage", "waitclick", "exists", "existsClick", "imageexists",
            "wait", "waitVanish", "swipe", "dragDrop", "keyevent", "keyevent_back",
            "toast", "Logger", "ifimage_then_click"
        ])
        a1.addWidget(self.action_type)
        act_box.addLayout(a1)

        a2 = QHBoxLayout()
        a2.addWidget(QLabel("Region:"))
        self.action_region = QComboBox()
        a2.addWidget(self.action_region, 1)
        act_box.addLayout(a2)

        a3 = QHBoxLayout()
        self.snap_lbl = QLabel("No Image")
        self.snap_lbl.setStyleSheet("color:gray;")
        a3.addWidget(self.snap_lbl, 1)
        btn_last = QPushButton("Use Last Snap")
        btn_last.setFixedWidth(100)
        btn_select_file = QPushButton("Select File")
        btn_select_file.setFixedWidth(100)
        a3.addWidget(btn_last)
        a3.addWidget(btn_select_file)
        act_box.addLayout(a3)

        a4 = QHBoxLayout()
        a4.addWidget(QLabel("Sim:"))
        self.sim_spin = QDoubleSpinBox()
        self.sim_spin.setValue(0.9)
        self.sim_spin.setSingleStep(0.05)
        a4.addWidget(self.sim_spin)
        a4.addWidget(QLabel("Time:"))
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setValue(15)
        a4.addWidget(self.timeout_spin)
        act_box.addLayout(a4)

        a5 = QHBoxLayout()
        self.sx = QSpinBox()
        self.sx.setRange(-999, 9999)
        self.sy = QSpinBox()
        self.sy.setRange(-999, 9999)
        self.ex = QSpinBox()
        self.ex.setRange(-999, 9999)
        self.ey = QSpinBox()
        self.ey.setRange(-999, 9999)
        a5.addWidget(QLabel("From:"))
        a5.addWidget(self.sx)
        a5.addWidget(self.sy)
        a5.addWidget(QLabel("To:"))
        a5.addWidget(self.ex)
        a5.addWidget(self.ey)

        btn_reset_swipe = QPushButton("Reset Swipe")
        btn_reset_swipe.setToolTip("Clear the swipe start/end coordinates")
        btn_reset_swipe.setStyleSheet("background: #ef4444; color: white; border-radius:4px; padding:2px;")
        btn_reset_swipe.setFixedWidth(90)
        btn_reset_swipe.clicked.connect(self.reset_swipe_points)
        a5.addWidget(btn_reset_swipe)
        act_box.addLayout(a5)

        self.msg_edit = QTextEdit()
        self.msg_edit.setFixedHeight(30)
        self.msg_edit.setPlaceholderText("Message or Keycode")
        act_box.addWidget(self.msg_edit)

        btn_add_act = QPushButton("Add Action")
        btn_add_act.setStyleSheet("background: #f97316; color: white; font-weight: bold;")
        act_box.addWidget(btn_add_act)
        self.scroll_layout.addWidget(act_box)

        # 4. Script Sequence
        seq_box = CollapsibleBox("Script Sequence")
        self.act_list = QListWidget()
        self.act_list.setFixedHeight(150)
        seq_box.addWidget(self.act_list)

        s1 = QHBoxLayout()
        btn_up = QPushButton("Move Up")
        btn_up.setToolTip("Move action up")
        btn_up.setMinimumWidth(100)
        btn_up.setFixedHeight(34)
        btn_dn = QPushButton("Move Down")
        btn_dn.setToolTip("Move action down")
        btn_dn.setMinimumWidth(100)
        btn_dn.setFixedHeight(34)
        self.btn_undo = QPushButton("Undo")
        self.btn_undo.setEnabled(False)
        btn_del_act = QPushButton("Delete")
        s1.addWidget(btn_up)
        s1.addWidget(btn_dn)
        s1.addStretch()
        s1.addWidget(self.btn_undo)
        s1.addWidget(btn_del_act)
        seq_box.addLayout(s1)
        self.scroll_layout.addWidget(seq_box)

        # 5. Export
        exp_box = CollapsibleBox("Export")
        self.lua_out = QTextEdit()
        self.lua_out.setFixedHeight(100)
        exp_box.addWidget(self.lua_out)

        e1 = QHBoxLayout()
        btn_lua = QPushButton("Save Lua")
        btn_json = QPushButton("Save Entry JSON")
        e1.addWidget(btn_lua)
        e1.addWidget(btn_json)
        exp_box.addLayout(e1)
        self.scroll_layout.addWidget(exp_box)

        self.scroll_layout.addStretch()

        # ---- RIGHT PANEL ----
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self.canvas = Canvas(self)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        right_layout.addWidget(self.canvas, 1)

        self.bottom_bar = QFrame()
        b_layout = QHBoxLayout(self.bottom_bar)
        b_layout.setContentsMargins(8, 4, 8, 4)
        b_layout.addWidget(QLabel("Zoom:"))
        btn_fit = QPushButton("Fit")
        btn_fit.setFixedWidth(50)
        b_layout.addWidget(btn_fit)
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(10, 300)
        self.zoom_slider.setValue(100)
        b_layout.addWidget(self.zoom_slider)
        self.zoom_label = QLabel("100%")
        b_layout.addWidget(self.zoom_label)
        b_layout.addStretch()
        b_layout.addWidget(QLabel("Right-click to Pan"))
        right_layout.addWidget(self.bottom_bar, 0)

        # ---- Icons ----
        self.register_icon("apply_res", btn_apply_res, "fa5s.expand-arrows-alt", size=24)
        self.register_icon("theme", self.btn_theme, "fa5s.adjust", size=24)
        self.register_icon("save_profile", btn_save, "fa5s.save")
        self.register_icon("load_profile", btn_load, "fa5s.folder-open")
        self.register_icon("upload", btn_upload, "fa5s.image")
        self.register_icon("reset", btn_reset, "fa5s.sync")
        self.register_icon("add_region", btn_add_reg, "fa5s.plus", size=20)
        self.register_icon("delete_region", btn_del_reg, "fa5s.minus", "#ef4444", size=20)
        self.register_icon("snap_selection", btn_snap_sel, "fa5s.crop")
        self.register_icon("snap_region", btn_snap_reg, "fa5s.crosshairs")
        self.register_icon("snap_folder", btn_folder, "fa5s.folder-open")
        self.register_icon("pick_dialog", btn_pick_dialog, "fa5s.palette")
        self.register_icon("pick_canvas", btn_pick_canvas, "fa5s.eye-dropper")
        self.register_icon("copy_color", btn_copy_color, "fa5s.copy")
        self.register_icon("use_last_snap", btn_last, "fa5s.history")
        self.register_icon("select_file", btn_select_file, "fa5s.file-import")
        self.register_icon("reset_swipe", btn_reset_swipe, "fa5s.eraser")
        self.register_icon("add_action", btn_add_act, "fa5s.plus-circle")
        self.register_icon("move_up", btn_up, "fa5s.arrow-up", size=24)
        self.register_icon("move_down", btn_dn, "fa5s.arrow-down", size=24)
        self.register_icon("undo", self.btn_undo, "fa5s.undo")
        self.register_icon("delete_action", btn_del_act, "fa5s.trash", "#ef4444")
        self.register_icon("save_lua", btn_lua, "fa5s.code")
        self.register_icon("save_json", btn_json, "fa5s.file-code")
        self.register_icon("fit", btn_fit, "fa5s.expand")

        # ---- Wiring ----
        self.canvas.screen_w = DEFAULT_W
        self.canvas.screen_h = DEFAULT_H
        self.repopulate_regions(self.canvas.regions)

        btn_apply_res.clicked.connect(self.apply_resolution)
        btn_save.clicked.connect(self.save_profile)
        btn_load.clicked.connect(self.load_profile)
        btn_upload.clicked.connect(self.upload_bg)
        btn_reset.clicked.connect(self.reset_app)

        self.region_box.currentTextChanged.connect(self.on_region_change)
        btn_add_reg.clicked.connect(self.start_reg_create)
        btn_del_reg.clicked.connect(self.del_region)

        self.constrain_chk.stateChanged.connect(
            lambda: setattr(self.canvas, "snap_constrain_clicks", self.constrain_chk.isChecked())
        )
        btn_snap_sel.clicked.connect(lambda: setattr(self.canvas, "snap_mode", True) or self.canvas.update())
        btn_snap_reg.clicked.connect(self.snap_current_region)
        btn_folder.clicked.connect(self.pick_folder)

        btn_last.clicked.connect(self.use_last_snap)
        btn_select_file.clicked.connect(self.select_manual_snap)
        btn_add_act.clicked.connect(self.add_action)
        btn_del_act.clicked.connect(self.delete_action)
        self.btn_undo.clicked.connect(self.undo_action)
        btn_up.clicked.connect(lambda: self.move_action(-1))
        btn_dn.clicked.connect(lambda: self.move_action(1))

        btn_fit.clicked.connect(self.canvas.fit_view)
        self.zoom_slider.valueChanged.connect(self.canvas.set_zoom_percent)

        btn_lua.clicked.connect(self.export_lua)
        btn_json.clicked.connect(self.export_json)

        # NEW: Color picker wiring
        btn_pick_dialog.clicked.connect(self.pick_color_dialog)
        btn_pick_canvas.clicked.connect(self.start_eyedropper)
        btn_copy_color.clicked.connect(self.copy_picked_color)

        self.apply_theme()  # Initial theme
        self.set_picked_color(QColor("#FFFFFF"))

    # ---------------- Icon helpers ----------------
    def register_icon(
        self, key: str, button: QPushButton, icon_name: str, color: Optional[str] = None, size: Optional[int] = None
    ):
        self.icon_targets[key] = (button, icon_name, color, size)

    def refresh_icons(self):
        accent = "#f97316" if self.is_dark else "#2563eb"
        for button, icon_name, override, override_size in self.icon_targets.values():
            btn_color = override or accent
            button.setIcon(qta.icon(icon_name, color=btn_color))
            size = override_size or 22
            button.setIconSize(QSize(size, size))

    # ---------------- Color Picker (NEW) ----------------
    def set_picked_color(self, qcolor: QColor):
        if not qcolor.isValid():
            return
        hexv = qcolor.name().upper()
        r, g, b, _ = qcolor.getRgb()

        self.color_preview.setStyleSheet(
            f"background:{hexv}; border:1px solid #cbd5e1; border-radius:4px;"
        )
        self.color_value.setText(f"{hexv}  ({r},{g},{b})")

        self._picked_color_hex = hexv
        self._picked_color_rgb = (r, g, b)

    def pick_color_dialog(self):
        col = QColorDialog.getColor(parent=self, title="Pick a color")
        if col.isValid():
            self.set_picked_color(col)
            self.copy_picked_color()

    def start_eyedropper(self):
        self.canvas.color_pick_mode = True
        self.canvas.setCursor(Qt.CursorShape.CrossCursor)

    def on_canvas_color_picked(self, qcolor: QColor):
        self.set_picked_color(qcolor)
        self.copy_picked_color()
        self.canvas.setCursor(Qt.CursorShape.ArrowCursor)

    def copy_picked_color(self):
        hexv = self._picked_color_hex or "#000000"
        r, g, b = self._picked_color_rgb
        text = f"{hexv}  ({r},{g},{b})"
        QApplication.clipboard().setText(text)

    # ---------------- Theme ----------------
    def toggle_theme(self):
        self.is_dark = not self.is_dark
        self.apply_theme()
        self.canvas.update()  # Repaint canvas bg

    def apply_theme(self):
        if self.is_dark:
            # DARK THEME
            self.setStyleSheet("""
                QMainWindow { background: #0f172a; }
                QWidget { color: #e2e8f0; }
                QScrollArea { background: #0f172a; border: none; }
                QWidget#scrollContent { background: #0f172a; }
                QFrame { background: #0f172a; }
                QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QListWidget {
                    background: #1e293b; border: 1px solid #334155;
                    border-radius: 4px; padding: 4px; color: #e2e8f0;
                }
                QSpinBox::up-button, QDoubleSpinBox::up-button,
                QSpinBox::down-button, QDoubleSpinBox::down-button {
                    width: 26px; height: 18px; padding: 0px; margin: 0px;
                }
                QSpinBox::up-arrow, QDoubleSpinBox::up-arrow,
                QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
                    width: 18px; height: 14px;
                }
                QPushButton {
                    background: #1e293b; border: 1px solid #334155;
                    border-radius: 4px; padding: 5px 10px; color: #e2e8f0;
                }
                QPushButton:hover { background: #334155; }
                QLabel { color: #cbd5e1; }
                QCheckBox { color: #cbd5e1; }
            """)
            self.bottom_bar.setStyleSheet("background: #1e293b; border-top: 1px solid #334155;")
        else:
            # LIGHT THEME
            self.setStyleSheet("""
                QMainWindow { background: #f8fafc; }
                QWidget { color: #334155; }
                QScrollArea { background: #f8fafc; border: none; }
                QWidget#scrollContent { background: #f8fafc; }
                QFrame { background: #f8fafc; }
                QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QListWidget {
                    background: white; border: 1px solid #cbd5e1;
                    border-radius: 4px; padding: 4px; color: #334155;
                }
                QSpinBox::up-button, QDoubleSpinBox::up-button,
                QSpinBox::down-button, QDoubleSpinBox::down-button {
                    width: 26px; height: 18px; padding: 0px; margin: 0px;
                }
                QSpinBox::up-arrow, QDoubleSpinBox::up-arrow,
                QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
                    width: 18px; height: 14px;
                }
                QPushButton {
                    background: white; border: 1px solid #cbd5e1;
                    border-radius: 4px; padding: 5px 10px; color: #334155;
                }
                QPushButton:hover { background: #f1f5f9; }
                QLabel { color: #475569; }
            """)
            self.bottom_bar.setStyleSheet("background: white; border-top: 1px solid #d1d5db;")

        self.refresh_icons()

    # ---------------- Existing methods ----------------
    def update_swipe_spinners_from_canvas(self):
        if self.canvas.swipe_start:
            self.sx.setValue(self.canvas.swipe_start.x())
            self.sy.setValue(self.canvas.swipe_start.y())
        if self.canvas.swipe_end:
            self.ex.setValue(self.canvas.swipe_end.x())
            self.ey.setValue(self.canvas.swipe_end.y())

    def reset_swipe_points(self):
        self.canvas.swipe_start = None
        self.canvas.swipe_end = None
        self.sx.setValue(0)
        self.sy.setValue(0)
        self.ex.setValue(0)
        self.ey.setValue(0)
        self.canvas.update()
        self.refresh_output()

    def apply_resolution(self):
        w = self.res_w.value()
        h = self.res_h.value()
        self.canvas.screen_w = w
        self.canvas.screen_h = h
        presets = compute_regions(w, h)
        for name, r in self.canvas.regions.items():
            if r.custom:
                presets[name] = r
        self.canvas.regions = presets
        self.repopulate_regions(self.canvas.regions, active=self.region_box.currentText())
        self.canvas.fit_view()
        self.refresh_output()

    def save_profile(self):
        fp, _ = QFileDialog.getSaveFileName(self, "Save Profile", "", "JSON (*.json)")
        if not fp:
            return
        data = {
            "w": self.canvas.screen_w,
            "h": self.canvas.screen_h,
            "bg": self.canvas.bg_image_path,
            "customs": [r.to_dict() for r in self.canvas.regions.values() if r.custom],
            "actions": self.actions,
        }
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        QMessageBox.information(self, "Saved", f"Profile saved to {fp}")

    def load_profile(self):
        fp, _ = QFileDialog.getOpenFileName(self, "Load Profile", "", "JSON (*.json)")
        if not fp:
            return
        with open(fp, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.res_w.setValue(data.get("w", DEFAULT_W))
        self.res_h.setValue(data.get("h", DEFAULT_H))
        self.apply_resolution()
        if data.get("bg") and os.path.exists(data.get("bg")):
            self.load_bg(data.get("bg"))
        for c in data.get("customs", []):
            self.canvas.regions[c["name"]] = RegionRect(**c)
        self.repopulate_regions(self.canvas.regions)
        self.actions = data.get("actions", [])
        self.update_act_list()
        self.refresh_output()

    def upload_bg(self):
        fp, _ = QFileDialog.getOpenFileName(self, "Select Image", "", "Images (*.png *.jpg)")
        if fp:
            self.load_bg(fp)

    def load_bg(self, path):
        img = QImage(path)
        if img.isNull():
            return
        self.canvas.bg_image = img
        self.canvas.bg_image_path = path
        self.canvas.fit_view()

    def reset_app(self):
        self.res_w.setValue(DEFAULT_W)
        self.res_h.setValue(DEFAULT_H)
        self.apply_resolution()
        self.canvas.bg_image = None
        self.actions.clear()
        self.update_act_list()
        self.refresh_output()

    def repopulate_regions(self, regions, active=None):
        self.region_box.blockSignals(True)
        self.action_region.blockSignals(True)
        self.region_box.clear()
        self.action_region.clear()
        names = sorted(regions.keys())
        self.region_box.addItems(names)
        self.action_region.addItems(names)
        target = active if active in regions else (names[0] if names else None)
        if target:
            self.region_box.setCurrentText(target)
            self.action_region.setCurrentText(target)
            self.canvas.selected_region = regions[target]
        self.region_box.blockSignals(False)
        self.action_region.blockSignals(False)
        self.canvas.update()

    def on_region_change(self, txt):
        self.canvas.selected_region = self.canvas.regions.get(txt)
        self.canvas.update()

    def start_reg_create(self):
        self.canvas.region_creation_mode = True
        self.canvas.update()

    def del_region(self):
        name = self.region_box.currentText()
        if name in self.canvas.regions and self.canvas.regions[name].custom:
            del self.canvas.regions[name]
            self.repopulate_regions(self.canvas.regions)
            self.refresh_output()

    def snap_current_region(self):
        if not self.canvas.bg_image:
            return
        r = self.canvas.selected_region
        if r:
            name, ok = QInputDialog.getText(self, "Name", f"Snapshot name for {r.name}:")
            if ok and name:
                img = self.canvas.bg_image.copy(QRect(r.x, r.y, r.w, r.h))
                self.save_snapshot_qimage(img, name, r.x, r.y, r.w, r.h)

    def pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Snap Folder", self.snap_folder)
        if d:
            self.snap_folder = d

    def save_snapshot_qimage(self, img, name, x, y, w, h):
        # If grey snap is checked, convert to grayscale before saving
        if hasattr(self, "chk_gray_snap") and self.chk_gray_snap.isChecked():
            img = img.convertToFormat(QImage.Format.Format_Grayscale8)

        os.makedirs(self.snap_folder, exist_ok=True)
        fname = f"{name}.png" if not name.endswith(".png") else name
        path = os.path.join(self.snap_folder, fname)
        img.save(path)
        self.snap_lbl.setText(fname)
        QMessageBox.information(self, "Saved", f"Saved {fname}")

    def use_last_snap(self):
        if not os.path.exists(self.snap_folder):
            return
        files = sorted(
            [f for f in os.listdir(self.snap_folder) if f.endswith(".png")],
            key=lambda x: os.path.getmtime(os.path.join(self.snap_folder, x)),
            reverse=True,
        )
        if files:
            self.snap_lbl.setText(files[0])

    def select_manual_snap(self):
        if not os.path.exists(self.snap_folder):
            os.makedirs(self.snap_folder, exist_ok=True)
        fp, _ = QFileDialog.getOpenFileName(self, "Select Snapshot", self.snap_folder, "PNG Images (*.png)")
        if fp:
            self.snap_lbl.setText(os.path.basename(fp))

    def add_action(self):
        t = self.action_type.currentText()
        act = {"type": t}
        if t in ["click", "clickimage", "waitclick", "exists", "existsClick", "imageexists", "wait", "waitVanish", "ifimage_then_click"]:
            img = self.snap_lbl.text()
            if img == "No Image":
                QMessageBox.warning(self, "Err", "Choose image")
                return
            act["img"] = img
            act["region"] = self.action_region.currentText()
            act["sim"] = self.sim_spin.value()
            act["timeout"] = self.timeout_spin.value()
        if t in ["swipe", "dragDrop"]:
            act["from"] = [self.sx.value(), self.sy.value()]
            act["to"] = [self.ex.value(), self.ey.value()]
            if t == "swipe":
                act["duration"] = 0.4
        if t in ["toast", "Logger"]:
            act["message"] = self.msg_edit.toPlainText()
        if t in ["keyevent", "keyevent_back"]:
            act["keycode"] = 4 if "back" in t else int(self.msg_edit.toPlainText() or 0)
        self.actions.append(act)
        self.update_act_list()
        self.refresh_output()

    def delete_action(self):
        row = self.act_list.currentRow()
        if row >= 0:
            item = self.actions.pop(row)
            self.undo_stack.append((row, item))
            self.btn_undo.setEnabled(True)
            self.update_act_list()
            self.refresh_output()

    def undo_action(self):
        if self.undo_stack:
            row, item = self.undo_stack.pop()
            self.actions.insert(row, item)
            self.update_act_list()
            self.refresh_output()
            if not self.undo_stack:
                self.btn_undo.setEnabled(False)

    def move_action(self, d):
        r = self.act_list.currentRow()
        if 0 <= r + d < len(self.actions):
            self.actions[r], self.actions[r + d] = self.actions[r + d], self.actions[r]
            self.update_act_list()
            self.act_list.setCurrentRow(r + d)
            self.refresh_output()

    def update_act_list(self):
        self.act_list.clear()
        for i, a in enumerate(self.actions):
            txt = f"{i+1}. {a['type']}"
            if "img" in a:
                txt += f" [{a['img']}]"
            if "region" in a:
                txt += f" @ {a['region']}"
            self.act_list.addItem(txt)

    def refresh_output(self):
        lines = [
            "-- Generated by Region & Swipe Designer By ZomBroX",
            f"-- Screen {self.canvas.screen_w}x{self.canvas.screen_h}",
            "-- Regions",
        ]

        used_regs = set(a["region"] for a in self.actions if "region" in a)

        regions_to_define = set()
        for name in used_regs:
            regions_to_define.add(name)
        for name, r in self.canvas.regions.items():
            if r.custom:
                regions_to_define.add(name)

        for rname in sorted(regions_to_define):
            if rname in self.canvas.regions:
                r = self.canvas.regions[rname]
                lines.append(f"{rname} = Region({r.x}, {r.y}, {r.w}, {r.h})")

        lines.append("\n-- AnkuLua API Actions")

        for a in self.actions:
            t = a["type"]
            if "img" in a:
                img = a["img"]
                reg = a.get("region", "")
                sim = f"{a['sim']:.2f}"

                # ZomBroX Specific Format: clickimage("pets.png", 1, "pet3", 0.90)
                if t in ["clickimage", "click", "waitclick"]:
                    lines.append(f'clickimage("{img}", 1, "{reg}", {sim})')
                elif t == "exists":
                    lines.append(f'exists("{img}", "{reg}", {sim})')
                elif t == "ifimage_then_click":
                    lines.append(f'if exists("{img}", "{reg}", {sim}) then click(getLastMatch()) end')

            elif t == "swipe":
                fx, fy = a["from"]
                tx, ty = a["to"]
                dur = a.get("duration", 0.4)
                lines.append(f"swipe(Location({fx},{fy}), Location({tx},{ty}), {dur})")

            elif t == "wait":
                lines.append(f"wait({a.get('timeout', 1)})")

        self.lua_out.setPlainText("\n".join(lines))

    def export_lua(self):
        fp, _ = QFileDialog.getSaveFileName(self, "Save Lua", "", "Lua (*.lua)")
        if fp:
            with open(fp, "w", encoding="utf-8") as f:
                f.write(self.lua_out.toPlainText())

    def export_json(self):
        fp, _ = QFileDialog.getSaveFileName(self, "Save JSON", "", "JSON (*.json)")
        if fp:
            with open(fp, "w", encoding="utf-8") as f:
                json.dump(self.actions, f, indent=2)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
