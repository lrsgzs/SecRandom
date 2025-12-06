from PySide6.QtWidgets import *
from PySide6.QtGui import *
from PySide6.QtCore import *
from PySide6.QtNetwork import *
from qfluentwidgets import *

from loguru import logger

from app.tools.personalised import load_custom_font, get_theme_icon, is_dark_theme
from app.tools.settings_access import (
    readme_settings_async,
    update_settings,
    get_settings_signals,
)
from app.tools.path_utils import *
from app.Language.obtain_language import get_content_combo_name_async


class LevitationWindow(QWidget):
    rollCallRequested = Signal()
    quickDrawRequested = Signal()
    instantDrawRequested = Signal()
    customDrawRequested = Signal()
    lotteryRequested = Signal()
    visibilityChanged = Signal(bool)
    positionChanged = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.NoDropShadowWindowHint
        )
        self._shadow = None
        self._drag_timer = QTimer(self)
        self._drag_timer.setSingleShot(True)
        self._drag_timer.timeout.connect(self._begin_drag)
        self._dragging = False
        self._press_pos = QPoint()
        self._indicator = None
        self._retract_timer = QTimer(self)
        self._retract_timer.setSingleShot(True)
        self._retracted = False
        self._last_stuck = False
        self._edge_threshold = 5
        self._placement = 0
        self._display_style = 0
        self._stick_to_edge = True
        self._retract_seconds = 5
        self._long_press_ms = 500
        self._buttons_spec = []
        self._font_family = load_custom_font() or QFont().family()
        self._container = QWidget(self)
        self._layout = None
        self._btn_size = QSize(60, 60)
        self._icon_size = QSize(24, 24)
        self._spacing = 6
        self._margins = 6
        self._init_settings()
        self._build_ui()
        self._apply_window()
        self._apply_position()
        self._install_drag_filters()
        get_settings_signals().settingChanged.connect(self._on_setting_changed)
        # 连接主题变更信号
        try:
            qconfig.themeChanged.connect(self._on_theme_changed)
        except Exception as e:
            logger.exception("连接 themeChanged 信号时出错（已忽略）: {}", e)
        self._apply_theme_style()

    def rebuild_ui(self):
        """
        重新构建浮窗UI
        删除当前布局并创建新的布局
        """
        # 清除现有按钮
        self._clear_buttons()

        # 重新创建容器布局
        container_layout = self._create_container_layout()

        # 设置新的布局
        old_layout = self._container.layout()
        if old_layout:
            QWidget().setLayout(old_layout)  # 从容器中移除旧布局

        self._container.setLayout(container_layout)

        # 重新添加按钮
        for i, spec in enumerate(self._buttons_spec):
            btn = self._create_button(spec)
            self._add_button(btn, i, len(self._buttons_spec))

        self._container.adjustSize()
        self.adjustSize()
        self._install_drag_filters()

    def _clear_buttons(self):
        """清除所有按钮"""
        # 清除顶层和底层的按钮
        if hasattr(self, "_top") and self._top and self._top.layout():
            top_layout = self._top.layout()
            while top_layout.count():
                item = top_layout.takeAt(0)
                widget = item.widget()
                if widget:
                    widget.deleteLater()

        if hasattr(self, "_bottom") and self._bottom and self._bottom.layout():
            bottom_layout = self._bottom.layout()
            while bottom_layout.count():
                item = bottom_layout.takeAt(0)
                widget = item.widget()
                if widget:
                    widget.deleteLater()

        # 清除容器直接包含的按钮
        container_layout = self._container.layout()
        if container_layout:
            while container_layout.count():
                item = container_layout.takeAt(0)
                widget = item.widget()
                if widget:
                    widget.deleteLater()

    def _font(self, size):
        s = int(size) if size and int(size) > 0 else 8
        if s <= 0:
            s = 8
        f = QFont(self._font_family) if self._font_family else QFont()
        if s > 0:  # 确保字体大小大于0
            f.setPointSize(s)
        return f

    def _apply_theme_style(self):
        # 主题样式应用：深色/浅色配色修正
        dark = is_dark_theme(qconfig)
        self._container.setAttribute(Qt.WA_StyledBackground, True)
        if dark:
            self._container.setStyleSheet(
                "background-color: rgba(32,32,32,180); border-radius: 12px; border: 1px solid rgba(255,255,255,20);"
            )
        else:
            self._container.setStyleSheet(
                "background-color: rgba(255,255,255,220); border-radius: 12px; border: 1px solid rgba(0,0,0,12);"
            )

    def _icon_pixmap(self, icon):
        if hasattr(icon, "icon"):
            qicon = icon.icon()
        elif isinstance(icon, QIcon):
            qicon = icon
        else:
            qicon = QIcon()
        return qicon.pixmap(self._icon_size)

    def _init_settings(self):
        self._visible_on_start = bool(
            readme_settings_async(
                "floating_window_management", "startup_display_floating_window"
            )
        )
        self._opacity = float(
            readme_settings_async(
                "floating_window_management", "floating_window_opacity"
            )
            or 0.8
        )
        self._placement = int(
            readme_settings_async(
                "floating_window_management", "floating_window_placement"
            )
            or 0
        )
        self._display_style = int(
            readme_settings_async(
                "floating_window_management", "floating_window_display_style"
            )
            or 0
        )
        self._stick_to_edge = bool(
            readme_settings_async(
                "floating_window_management", "floating_window_stick_to_edge"
            )
        )
        self._retract_seconds = int(
            readme_settings_async(
                "floating_window_management",
                "floating_window_stick_to_edge_recover_seconds",
            )
            or 0
        )
        self._long_press_ms = int(
            readme_settings_async(
                "floating_window_management", "floating_window_long_press_duration"
            )
            or 500
        )
        self._draggable = bool(
            readme_settings_async(
                "floating_window_management", "floating_window_draggable"
            )
            or True
        )
        self._stick_indicator_style = int(
            readme_settings_async(
                "floating_window_management",
                "floating_window_stick_to_edge_display_style",
            )
            or 0
        )
        idx = int(
            readme_settings_async(
                "floating_window_management", "floating_window_button_control"
            )
            or 0
        )
        self._buttons_spec = self._map_button_control(idx)
        # 贴边隐藏功能配置 - 与现有贴边设置保持一致
        self.flash_window_side_switch = bool(
            readme_settings_async(
                "floating_window_management", "flash_window_side_switch"
            )
            or False
        )
        # 复用现有的贴边回收秒数配置
        self.custom_retract_time = int(
            readme_settings_async(
                "floating_window_management",
                "floating_window_stick_to_edge_recover_seconds",
            )
            or 5
        )
        # 复用现有的贴边显示样式配置
        self.custom_display_mode = int(
            readme_settings_async(
                "floating_window_management",
                "floating_window_stick_to_edge_display_style",
            )
            or 1
        )
        # 新增属性
        self._retracted = False
        self._edge_threshold = 5
        self._hidden_width = 10

    def _build_ui(self):
        # 两行布局按索引分配，避免 3+ 个按钮全部落到底部
        lay = self._container.layout()
        if lay:
            while lay.count():
                item = lay.takeAt(0)
                w = item.widget()
                if w:
                    w.setParent(None)
                    w.deleteLater()
            lay.deleteLater()
        if not self._layout:
            self._layout = QHBoxLayout(self)
            self._layout.setContentsMargins(
                self._margins, self._margins, self._margins, self._margins
            )
            self._layout.addWidget(self._container)
        else:
            self._layout.setContentsMargins(
                self._margins, self._margins, self._margins, self._margins
            )
        self._container_layout = self._create_container_layout()
        self._container.setLayout(self._container_layout)
        self._container_layout.setAlignment(Qt.AlignCenter)
        for i, spec in enumerate(self._buttons_spec):
            btn = self._create_button(spec)
            self._add_button(btn, i, len(self._buttons_spec))
        self._container.adjustSize()
        self.adjustSize()
        self._install_drag_filters()

    def _apply_window(self):
        self.setWindowOpacity(self._opacity)
        if self._visible_on_start:
            self.show()
        else:
            self.hide()

    def _apply_position(self):
        x = int(readme_settings_async("float_position", "x") or 100)
        y = int(readme_settings_async("float_position", "y") or 100)
        nx, ny = self._clamp_to_screen(x, y)
        self.move(nx, ny)

    def _clamp_to_screen(self, x, y):
        fg = self.frameGeometry()
        scr = QGuiApplication.screenAt(fg.center()) or QApplication.primaryScreen()
        geo = scr.availableGeometry()
        cx = max(geo.left(), min(x, geo.right() - self.width() + 1))
        cy = max(geo.top(), min(y, geo.bottom() - self.height() + 1))
        return cx, cy

    def _create_container_layout(self):
        if hasattr(self, "_top") and self._top:
            self._top.deleteLater()
            self._top = None
        if hasattr(self, "_bottom") and self._bottom:
            self._bottom.deleteLater()
            self._bottom = None
        if self._placement == 1:
            lay = QVBoxLayout()
            lay.setContentsMargins(
                self._margins, self._margins, self._margins, self._margins
            )
            lay.setSpacing(self._spacing)
            return lay
        if self._placement == 2:
            lay = QHBoxLayout()
            lay.setContentsMargins(
                self._margins, self._margins, self._margins, self._margins
            )
            lay.setSpacing(self._spacing)
            return lay
        lay = QVBoxLayout()
        lay.setContentsMargins(
            self._margins, self._margins, self._margins, self._margins
        )
        lay.setSpacing(self._spacing)
        self._top = QWidget()
        self._bottom = QWidget()
        t = QHBoxLayout(self._top)
        t.setContentsMargins(0, 0, 0, 0)
        t.setSpacing(self._spacing)
        t.setAlignment(Qt.AlignCenter)
        b = QHBoxLayout(self._bottom)
        b.setContentsMargins(0, 0, 0, 0)
        b.setSpacing(self._spacing)
        b.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._top)
        lay.addWidget(self._bottom)
        return lay

    def _create_button(self, spec):
        text_map = get_content_combo_name_async(
            "floating_window_management", "floating_window_button_control"
        )
        names = [text_map[0], text_map[1], text_map[2], text_map[3], text_map[4]]
        if spec == "roll_call":
            icon = get_theme_icon("ic_fluent_people_20_filled")
            text = names[0]
            sig = self.rollCallRequested
        elif spec == "quick_draw":
            icon = get_theme_icon("ic_fluent_flash_20_filled")
            text = names[1]
            sig = self.quickDrawRequested
        elif spec == "instant_draw":
            icon = get_theme_icon("ic_fluent_play_20_filled")
            text = names[2]
            sig = self.instantDrawRequested
        elif spec == "custom_draw":
            icon = get_theme_icon("ic_fluent_edit_20_filled")
            text = names[3]
            sig = self.customDrawRequested
        else:
            icon = get_theme_icon("ic_fluent_gift_20_filled")
            text = names[4]
            sig = self.lotteryRequested

        if self._display_style == 1:
            btn = TransparentToolButton()
            btn.setIcon(icon)
            btn.setIconSize(self._icon_size)
            btn.setFixedSize(self._btn_size)
            btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        elif self._display_style == 2:
            btn = PushButton(text)
            btn.setFixedSize(self._btn_size)
            btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            btn.setFont(self._font(12))
        else:
            btn = PushButton()
            lay = QVBoxLayout(btn)
            lay.setContentsMargins(0, 4, 0, 4)
            lay.setSpacing(2)
            lab_icon = TransparentToolButton()
            lab_icon.setIcon(icon)
            lab_icon.setIconSize(self._icon_size)
            lab_icon.setFixedSize(self._icon_size)
            # 复合按钮图标不置灰，避免低对比；忽略鼠标事件
            lab_icon.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            lab_icon.setFocusPolicy(Qt.NoFocus)
            lab_text = BodyLabel(text)
            lab_text.setAlignment(Qt.AlignCenter)
            lab_text.setFont(self._font(10))
            lab_text.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            lab_text.setFocusPolicy(Qt.NoFocus)
            lay.addWidget(lab_icon)
            lay.addWidget(lab_text)
            lay.setAlignment(Qt.AlignCenter)
            lay.setAlignment(lab_icon, Qt.AlignCenter)
            lay.setAlignment(lab_text, Qt.AlignCenter)
            btn.setFixedSize(self._btn_size)
            btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        btn.clicked.connect(sig.emit)
        return btn

    def _add_button(self, btn, index, total):
        if self._placement == 1:
            self._container.layout().addWidget(btn, 0, Qt.AlignCenter)
            return
        if self._placement == 2:
            self._container.layout().addWidget(btn, 0, Qt.AlignCenter)
            return
        # 前半放顶行，后半放底行
        split = (total + 1) // 2
        if index < split:
            self._top.layout().addWidget(btn, 0, Qt.AlignCenter)
        else:
            self._bottom.layout().addWidget(btn, 0, Qt.AlignCenter)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self._draggable:
            self._press_pos = e.globalPosition().toPoint()
            self._dragging = False
            self._drag_timer.stop()
            self._drag_timer.start(self._long_press_ms)

    def _begin_drag(self):
        self._dragging = True
        self.setCursor(Qt.ClosedHandCursor)
        pass

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton and self._draggable:
            # 支持移动阈值触发拖拽，提升交互体验
            cur = e.globalPosition().toPoint()
            if not self._dragging:
                delta0 = cur - self._press_pos
                if abs(delta0.x()) >= 3 or abs(delta0.y()) >= 3:
                    self._begin_drag()
            if self._dragging:
                delta = cur - self._press_pos
                self.move(self.x() + delta.x(), self.y() + delta.y())
                self._press_pos = cur
                self._cancel_retract()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_timer.stop()
            self.setCursor(Qt.ArrowCursor)
            if self._draggable and self._dragging:
                self._dragging = False
                self._stick_to_nearest_edge()
                if self._last_stuck:
                    self._schedule_retract()
                else:
                    self._clear_indicator()
            self._save_position()

            # 如果启用了边缘贴边隐藏功能，在拖动结束后检查是否需要贴边
            if self.flash_window_side_switch:
                # 使用定时器延迟执行边缘检测，确保位置已经保存
                QTimer.singleShot(100, self._check_edge_proximity)
            pass

    def eventFilter(self, obj, event):
        if not self._draggable:
            return False

        if event.type() == QEvent.MouseButtonPress:
            if event.button() == Qt.LeftButton:
                self._press_pos = event.globalPosition().toPoint()
                self._dragging = False
                self._drag_timer.stop()
                self._drag_timer.start(self._long_press_ms)
            return False
        if event.type() == QEvent.MouseMove:
            if event.buttons() & Qt.LeftButton:
                cur = event.globalPosition().toPoint()
                if not self._dragging:
                    delta0 = cur - self._press_pos
                    if abs(delta0.x()) >= 3 or abs(delta0.y()) >= 3:
                        self._begin_drag()
                if self._dragging:
                    delta = cur - self._press_pos
                    self.move(self.x() + delta.x(), self.y() + delta.y())
                    self._press_pos = cur
                    self._cancel_retract()
                    return True
            return False
        if event.type() == QEvent.MouseButtonRelease:
            if event.button() == Qt.LeftButton:
                self._drag_timer.stop()
                if self._dragging:
                    self._dragging = False
                    self.setCursor(Qt.ArrowCursor)
                    self._stick_to_nearest_edge()
                    if self._last_stuck:
                        self._schedule_retract()
                    else:
                        self._clear_indicator()
                    self._save_position()

                    # 如果启用了边缘贴边隐藏功能，在拖动结束后检查是否需要贴边
                    if self.flash_window_side_switch:
                        # 使用定时器延迟执行边缘检测，确保位置已经保存
                        QTimer.singleShot(100, self._check_edge_proximity)
                    pass
                    return True
            return False
        return False

    def _install_drag_filters(self):
        self._container.installEventFilter(self)
        for w in self._container.findChildren(QWidget):
            w.installEventFilter(self)

    def enterEvent(self, e):
        if self._retracted:
            self._expand_from_edge()
        # 当鼠标进入窗口时，删除可能存在的自动隐藏定时器
        if hasattr(self, "_auto_hide_timer"):
            if self._auto_hide_timer.isActive():
                self._auto_hide_timer.stop()
            # 从对象中移除定时器属性，避免内存泄漏
            delattr(self, "_auto_hide_timer")

    def leaveEvent(self, e):
        if self._retracted:
            self._schedule_retract()

        # 如果启用了边缘贴边隐藏功能，当鼠标离开窗口时，延迟后自动隐藏
        if self.flash_window_side_switch and not self._retracted:
            # 清除旧的定时器
            if hasattr(self, "_auto_hide_timer") and self._auto_hide_timer.isActive():
                self._auto_hide_timer.stop()
            # 创建或重置自动隐藏定时器
            self._auto_hide_timer = QTimer(self)
            self._auto_hide_timer.setSingleShot(True)
            self._auto_hide_timer.timeout.connect(self._auto_hide_window)
            # 设置延迟时间
            self._auto_hide_timer.start(self.custom_retract_time * 1000)

    def _stick_to_nearest_edge(self):
        if not self._stick_to_edge:
            return
        fg = self.frameGeometry()
        scr = QGuiApplication.screenAt(fg.center()) or QApplication.primaryScreen()
        geo = scr.availableGeometry()
        left = fg.left() - geo.left()
        right = geo.right() - fg.right()
        self._last_stuck = False
        if left <= self._edge_threshold:
            self.move(geo.left(), self.y())
            # 如果启用了新的贴边隐藏功能，不显示旧的指示器
            if not self.flash_window_side_switch:
                self._show_indicator("left")
            self._last_stuck = True
            return
        if right <= self._edge_threshold:
            self.move(geo.right() - self.width() + 1, self.y())
            # 如果启用了新的贴边隐藏功能，不显示旧的指示器
            if not self.flash_window_side_switch:
                self._show_indicator("right")
            self._last_stuck = True

    def _schedule_retract(self):
        if not self._stick_to_edge:
            return
        if self._retract_seconds and self._retract_seconds > 0:
            self._retract_timer.stop()
            self._retract_timer.start(self._retract_seconds * 1000)

    def _cancel_retract(self):
        if self._retract_timer.isActive():
            self._retract_timer.stop()

    def _retract_into_edge(self):
        # 防多屏错位：基于当前屏幕几何
        fg = self.frameGeometry()
        scr = QGuiApplication.screenAt(fg.center()) or QApplication.primaryScreen()
        geo = scr.availableGeometry()
        handle = 16
        if self.x() <= geo.left():
            self.move(geo.left() - self.width() + handle, self.y())
            self._retracted = True
            # 如果启用了新的贴边隐藏功能，不显示旧的指示器
            if not self.flash_window_side_switch:
                self._show_indicator("right")
        elif self.x() + self.width() >= geo.right():
            self.move(geo.right() - handle + 1, self.y())
            self._retracted = True
            # 如果启用了新的贴边隐藏功能，不显示旧的指示器
            if not self.flash_window_side_switch:
                self._show_indicator("left")

    def _expand_from_edge(self):
        # 基于当前屏幕可用区域展开
        fg = self.frameGeometry()
        scr = QGuiApplication.screenAt(fg.center()) or QApplication.primaryScreen()
        geo = scr.availableGeometry()
        if self.x() < geo.left():
            self.move(geo.left(), self.y())
        elif self.x() + self.width() > geo.right():
            self.move(geo.right() - self.width() + 1, self.y())
        self._retracted = False
        self._clear_indicator()

    def _check_edge_proximity(self):
        """检测窗口是否靠近屏幕边缘，并实现贴边隐藏功能（带动画效果）"""
        # 如果有正在进行的动画，先停止它
        if (
            hasattr(self, "animation")
            and self.animation.state() == QPropertyAnimation.Running
        ):
            self.animation.stop()

        # 清除可能存在的旧指示器
        self._clear_indicator()

        # 获取屏幕尺寸
        screen = QApplication.primaryScreen().availableGeometry()

        # 获取窗口当前位置和尺寸
        window_pos = self.pos()
        window_width = self.width()
        window_height = self.height()

        # 定义边缘阈值（像素）
        edge_threshold = 5
        hidden_width = 10  # 隐藏后露出的宽度

        # 检测左边缘
        if window_pos.x() <= edge_threshold:
            # 保存主浮窗的原始位置（但不更新实际坐标）
            if not hasattr(self, "_original_position"):
                self._original_position = window_pos

            # 创建平滑动画效果
            self.animation = QPropertyAnimation(self, b"geometry")
            # 设置动画持续时间（更流畅的过渡）
            self.animation.setDuration(400)
            # 设置缓动曲线（使用更自然的缓动）
            self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)

            # 设置动画起始值（当前位置）
            self.animation.setStartValue(self.geometry())

            # 设置动画结束值（隐藏位置）
            end_rect = QRect(
                -window_width + hidden_width,
                window_pos.y(),
                window_width,
                window_height,
            )
            self.animation.setEndValue(end_rect)

            # 动画完成后创建收纳浮窗
            def on_animation_finished():
                self._create_storage_window(
                    "right", 0, window_pos.y() + window_height // 2 - 30
                )
                # 标记为已收纳状态，但保持原始坐标不变
                self._retracted = True

            self.animation.finished.connect(on_animation_finished)

            # 启动动画
            self.animation.start()
            return

        # 检测右边缘
        elif window_pos.x() + window_width >= screen.width() - edge_threshold:
            # 保存主浮窗的原始位置（但不更新实际坐标）
            if not hasattr(self, "_original_position"):
                self._original_position = window_pos

            # 创建平滑动画效果
            self.animation = QPropertyAnimation(self, b"geometry")
            # 设置动画持续时间（更流畅的过渡）
            self.animation.setDuration(400)
            # 设置缓动曲线（使用更自然的缓动）
            self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)

            # 设置动画起始值（当前位置）
            self.animation.setStartValue(self.geometry())

            # 设置动画结束值（隐藏位置）
            end_rect = QRect(
                screen.width() - hidden_width,
                window_pos.y(),
                window_width,
                window_height,
            )
            self.animation.setEndValue(end_rect)

            # 动画完成后创建收纳浮窗
            def on_animation_finished():
                self._create_storage_window(
                    "left",
                    screen.width() - 30,
                    window_pos.y() + window_height // 2 - 30,
                )
                # 标记为已收纳状态，但保持原始坐标不变
                self._retracted = True

            self.animation.finished.connect(on_animation_finished)

            # 启动动画
            self.animation.start()
            return

        # 保存新位置（仅在窗口未贴边隐藏时）
        if (
            window_pos.x() > edge_threshold
            and window_pos.x() + window_width < screen.width() - edge_threshold
        ):
            # 只有在非收纳状态下才保存位置
            if not self._retracted:
                self._save_position()
            # 清除原始位置
            if hasattr(self, "_original_position"):
                delattr(self, "_original_position")

        self._retracted = False

    def _show_indicator(self, direction):
        self._clear_indicator()
        w = QWidget(self)
        w.resize(16, 16)
        if self._stick_indicator_style == 0:
            tb = ToolButton(w)
            qicon = get_theme_icon("ic_fluent_pin_20_filled").icon()
            tb.setIcon(qicon)
            tb.setIconSize(QSize(14, 14))
            tb.setFixedSize(16, 16)
        elif self._stick_indicator_style == 1:
            lab = BodyLabel("浮窗", w)
            lab.setAlignment(Qt.AlignCenter)
            lab.setFont(self._font(8))
        else:
            lab = BodyLabel(w)
            lab.setStyleSheet("border-radius: 2px;")
        if direction == "left":
            w.move(-8, self.height() // 2 - 8)
        elif direction == "right":
            w.move(self.width() - 8, self.height() // 2 - 8)
        else:
            w.move(self.width() // 2 - 8, -8)
        w.show()
        self._indicator = w

    def _clear_indicator(self):
        if self._indicator:
            self._indicator.hide()
            self._indicator.deleteLater()
            self._indicator = None

    def _create_storage_window(self, direction, x, y):
        """创建只能在y轴移动的收纳浮窗"""
        # 先删除可能存在的收纳浮窗
        self._delete_storage_window()

        # 创建收纳浮窗
        self.storage_window = QWidget()
        self.storage_window.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.NoFocus
        )
        self.storage_window.setAttribute(Qt.WA_TranslucentBackground)

        # 设置收纳浮窗尺寸
        self.storage_window.setFixedSize(30, 30)

        # 根据主题设置不同的背景颜色，与主浮窗保持一致
        dark = is_dark_theme(qconfig)
        opacity = self._opacity

        if dark:
            bg_color = f"rgba(32, 32, 32, {opacity})"
            color = "#ffffff"
        else:
            bg_color = f"rgba(255, 255, 255, {opacity})"
            color = "#000000"

        # 设置收纳浮窗样式，与主浮窗保持一致的风格
        self.storage_window.setStyleSheet(
            f"background-color: {bg_color};"
            "border-radius: 15px;"
            "border: 1px solid rgba(0, 0, 0, 12);"
            "background-clip: padding-box;"
        )

        # 创建标签显示内容
        label = BodyLabel(self.storage_window)
        label.setAlignment(Qt.AlignCenter)

        # 根据方向设置显示内容
        if direction == "right":
            label.setText(">")
        elif direction == "left":
            label.setText("<")

        label.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: bold;")
        label.setGeometry(0, 0, 30, 30)

        # 设置收纳浮窗位置
        self.storage_window.move(x, y)

        # 初始化拖动相关属性
        self._storage_dragging = False
        self._storage_drag_start = QPoint()

        # 连接鼠标事件
        self.storage_window.mousePressEvent = self._on_storage_press
        self.storage_window.mouseMoveEvent = self._on_storage_move
        self.storage_window.mouseReleaseEvent = self._on_storage_release

        # 存储收纳浮窗方向和初始位置
        self._storage_direction = direction
        self._storage_initial_x = x

        # 添加悬停效果，提升用户体验
        self.storage_window.setMouseTracking(True)
        self.storage_window.enterEvent = self._on_storage_enter
        self.storage_window.leaveEvent = self._on_storage_leave

        # 显示收纳浮窗
        self.storage_window.show()

    def _on_storage_enter(self, event):
        """收纳浮窗鼠标进入事件"""
        if hasattr(self, "storage_window") and self.storage_window:
            # 鼠标悬停时增加透明度
            current_style = self.storage_window.styleSheet()
            if "background-clip: padding-box;" in current_style:
                self.storage_window.setStyleSheet(
                    current_style
                    + "background-color: rgba("
                    + current_style.split("rgba(")[1].split(")")[0]
                    + ", 0.9);"
                )

    def _on_storage_leave(self, event):
        """收纳浮窗鼠标离开事件"""
        if hasattr(self, "storage_window") and self.storage_window:
            # 鼠标离开时恢复原始透明度
            current_style = self.storage_window.styleSheet()
            if "background-clip: padding-box;" in current_style:
                self.storage_window.setStyleSheet(
                    current_style.split("background-color: rgba(")[0]
                    + "background-color: rgba("
                    + current_style.split("rgba(")[1].split(")")[0]
                    + ", "
                    + str(self._opacity)
                    + ");"
                    + "background-clip: padding-box;"
                )

    def _delete_storage_window(self):
        """删除收纳浮窗"""
        if hasattr(self, "storage_window") and self.storage_window:
            self.storage_window.deleteLater()
            self.storage_window = None

    def _on_storage_press(self, event):
        """收纳浮窗按下事件"""
        if event.button() == Qt.LeftButton:
            self._storage_drag_start = event.pos()
            self._storage_dragging = False

    def _on_storage_move(self, event):
        """收纳浮窗移动事件 - 只允许y轴移动"""
        if event.buttons() & Qt.LeftButton:
            delta = event.pos() - self._storage_drag_start
            if not self._storage_dragging:
                # 检测是否超过拖动阈值
                if abs(delta.y()) > 3:
                    self._storage_dragging = True
            if self._storage_dragging:
                # 只在y轴移动，x轴保持固定
                new_y = self.storage_window.y() + delta.y()
                # 限制在屏幕内
                screen = QApplication.primaryScreen().availableGeometry()
                new_y = max(
                    screen.top(),
                    min(new_y, screen.bottom() - self.storage_window.height()),
                )
                self.storage_window.move(self._storage_initial_x, new_y)

    def _on_storage_release(self, event):
        """收纳浮窗释放事件"""
        if event.button() == Qt.LeftButton:
            if not self._storage_dragging:
                # 点击事件 - 展开主浮窗
                self._expand_window()
            self._storage_dragging = False
        elif event.button() == Qt.RightButton:
            # 右键点击 - 展开主浮窗（提供额外的交互方式）
            if not self._storage_dragging:
                self._expand_window()

    def _expand_window(self):
        """展开隐藏的窗口（带动画效果）"""
        # 如果收纳浮窗不存在，直接返回
        if not hasattr(self, "storage_window") or not self.storage_window:
            return

        # 保存收纳浮窗的当前位置和尺寸
        storage_window = self.storage_window
        storage_pos = storage_window.pos()
        storage_width = storage_window.width()
        storage_height = storage_window.height()

        # 获取屏幕尺寸
        screen = QApplication.primaryScreen().availableGeometry()

        # 创建收纳浮窗的退出动画
        storage_animation = QPropertyAnimation(storage_window, b"geometry")
        storage_animation.setDuration(200)
        storage_animation.setEasingCurve(QEasingCurve.Type.OutQuad)

        # 设置收纳浮窗动画的起始值和结束值
        storage_animation.setStartValue(storage_window.geometry())

        # 根据收纳浮窗的位置，将其移动到屏幕外
        if storage_pos.x() < screen.width() // 2:
            # 左侧收纳浮窗，向右移出屏幕
            storage_end_rect = QRect(
                screen.width(),
                storage_pos.y(),
                storage_width,
                storage_height,
            )
        else:
            # 右侧收纳浮窗，向左移出屏幕
            storage_end_rect = QRect(
                -storage_width,
                storage_pos.y(),
                storage_width,
                storage_height,
            )
        storage_animation.setEndValue(storage_end_rect)

        # 获取主窗口当前尺寸
        window_width = self.width()
        window_height = self.height()

        # 如果有正在进行的动画，先停止它
        if (
            hasattr(self, "animation")
            and self.animation.state() == QPropertyAnimation.Running
        ):
            self.animation.stop()

        # 定义主窗口的动画完成回调
        def on_main_animation_finished():
            self._retracted = False
            # 激活主窗口，确保窗口显示在最前面
            self.raise_()
            self.activateWindow()
            # 设置自动隐藏定时器
            self._auto_hide_timer = QTimer(self)
            self._auto_hide_timer.setSingleShot(True)
            self._auto_hide_timer.timeout.connect(self._auto_hide_window)
            self._auto_hide_timer.start(self.custom_retract_time * 1000)

        # 定义收纳浮窗动画完成后的回调
        def on_storage_animation_finished():
            # 删除收纳浮窗
            self._delete_storage_window()

            # 获取主窗口应该恢复到的位置
            if hasattr(self, "_original_position"):
                # 使用保存的原始位置
                target_x = self._original_position.x()
                target_y = self._original_position.y()
            else:
                # 如果没有保存的原始位置，使用默认位置
                if self.x() < screen.left():
                    # 从左侧展开
                    target_x = screen.left()
                elif self.x() + window_width > screen.right():
                    # 从右侧展开
                    target_x = screen.right() - window_width + 1
                target_y = self.y()

            # 创建主窗口的动画效果
            self.animation = QPropertyAnimation(self, b"geometry")
            self.animation.setDuration(300)
            self.animation.setEasingCurve(
                QEasingCurve.Type.OutCubic
            )  # 使用更自然的缓动曲线

            # 设置主窗口动画的起始值和结束值
            self.animation.setStartValue(self.geometry())
            main_end_rect = QRect(target_x, target_y, window_width, window_height)
            self.animation.setEndValue(main_end_rect)

            # 连接主窗口动画的完成信号
            self.animation.finished.connect(on_main_animation_finished)

            # 启动主窗口动画
            self.animation.start()

        # 连接收纳浮窗动画的完成信号
        storage_animation.finished.connect(on_storage_animation_finished)

        # 启动收纳浮窗动画
        storage_animation.start()

    def _auto_hide_window(self):
        """自动隐藏窗口"""
        # 检查是否启用了边缘贴边隐藏功能
        if self.flash_window_side_switch:
            # 清除自动隐藏定时器
            if hasattr(self, "_auto_hide_timer") and self._auto_hide_timer.isActive():
                self._auto_hide_timer.stop()
            # 调用边缘检测方法隐藏窗口
            self._check_edge_proximity()

    def _save_position(self):
        update_settings("float_position", "x", self.x())
        update_settings("float_position", "y", self.y())
        self.positionChanged.emit(self.x(), self.y())

    def _on_setting_changed(self, first, second, value):
        if first == "floating_window_management":
            if second == "startup_display_floating_window":
                if bool(value):
                    self.show()
                else:
                    self.hide()
                self.visibilityChanged.emit(bool(value))
            elif second == "floating_window_opacity":
                self._opacity = float(value or 0.8)
                self.setWindowOpacity(self._opacity)
            elif second == "floating_window_placement":
                self._placement = int(value or 0)
                self.rebuild_ui()
            elif second == "floating_window_display_style":
                self._display_style = int(value or 0)
                self.rebuild_ui()
            elif second == "floating_window_stick_to_edge":
                self._stick_to_edge = bool(value)
            elif second == "floating_window_stick_to_edge_recover_seconds":
                self._retract_seconds = int(value or 0)
            elif second == "floating_window_long_press_duration":
                self._long_press_ms = int(value or 500)
            elif second == "floating_window_stick_to_edge_display_style":
                self._stick_indicator_style = int(value or 0)
            elif second == "floating_window_button_control":
                self._buttons_spec = self._map_button_control(int(value or 0))
                self.rebuild_ui()
            elif second == "floating_window_draggable":
                self._draggable = bool(value)
            # 贴边隐藏功能配置项
            elif second == "flash_window_side_switch":
                self.flash_window_side_switch = bool(value)
                # 如果启用了功能，立即检查边缘
                if bool(value):
                    QTimer.singleShot(100, self._check_edge_proximity)
                else:
                    # 如果禁用了功能，删除收纳浮窗并展开窗口
                    self._delete_storage_window()
                    if self._retracted:
                        self._expand_from_edge()
            elif second == "custom_retract_time":
                self.custom_retract_time = int(value or 5)
            elif second == "custom_display_mode":
                self.custom_display_mode = int(value or 1)
            # 当任何影响外观的设置改变时，重新应用主题样式
            self._apply_theme_style()
        elif first == "float_position":
            if second == "x":
                x = int(value or 0)
                nx, ny = self._clamp_to_screen(x, self.y())
                self.move(nx, ny)
            elif second == "y":
                y = int(value or 0)
                nx, ny = self._clamp_to_screen(self.x(), y)
                self.move(nx, ny)

    def _on_theme_changed(self):
        """当系统主题变更时调用"""
        self._apply_theme_style()

    def _map_button_control(self, idx):
        combos = [
            ["roll_call"],
            ["quick_draw"],
            ["instant_draw"],
            ["custom_draw"],
            ["lottery"],
            ["roll_call", "quick_draw"],
            ["roll_call", "custom_draw"],
            ["roll_call", "lottery"],
            ["quick_draw", "custom_draw"],
            ["quick_draw", "lottery"],
            ["custom_draw", "lottery"],
            ["roll_call", "quick_draw", "custom_draw"],
            ["roll_call", "quick_draw", "lottery"],
            ["roll_call", "custom_draw", "lottery"],
            ["quick_draw", "custom_draw", "lottery"],
            ["roll_call", "quick_draw", "custom_draw", "lottery"],
        ]
        if idx < 0 or idx >= len(combos):
            return combos[0]
        return combos[idx]
