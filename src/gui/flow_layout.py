"""Wrapping layout: places widgets left-to-right and flows to the next row (Qt FlowLayout pattern)."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, QSize, Qt
from PyQt6.QtWidgets import QLayout, QLayoutItem, QSizePolicy, QStyle, QWidget


class FlowLayout(QLayout):
    """Arranges child widgets horizontally and wraps based on available width."""

    def __init__(
        self,
        parent: QWidget | None = None,
        margin: int = 0,
        h_spacing: int = -1,
        v_spacing: int = -1,
    ) -> None:
        super().__init__(parent)
        self._item_list: list[QLayoutItem] = []
        self._h_space = h_spacing
        self._v_space = v_spacing
        self.setContentsMargins(margin, margin, margin, margin)

    def __del__(self) -> None:
        item = self.takeAt(0)
        while item is not None:
            item = self.takeAt(0)

    def addItem(self, item: QLayoutItem) -> None:
        self._item_list.append(item)

    def horizontalSpacing(self) -> int:
        if self._h_space >= 0:
            return self._h_space
        return self._smart_spacing(Qt.Orientation.Horizontal)

    def verticalSpacing(self) -> int:
        if self._v_space >= 0:
            return self._v_space
        return self._smart_spacing(Qt.Orientation.Vertical)

    def count(self) -> int:
        return len(self._item_list)

    def itemAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._item_list):
            return self._item_list[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._item_list):
            return self._item_list.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize(0, 0)
        for item in self._item_list:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _smart_spacing(self, orientation: Qt.Orientation) -> int:
        parent = self.parent()
        if parent is None:
            return -1
        pw = parent
        if not isinstance(pw, QWidget):
            return -1
        style = pw.style()
        if style is None:
            return -1
        if orientation == Qt.Orientation.Horizontal:
            return style.pixelMetric(
                QStyle.PixelMetric.PM_LayoutHorizontalSpacing,
                None,
                pw,
            )
        return style.pixelMetric(
            QStyle.PixelMetric.PM_LayoutVerticalSpacing,
            None,
            pw,
        )

    def _do_layout(self, rect: QRect, *, test_only: bool) -> int:
        left, top, right, bottom = self.getContentsMargins()
        effective = rect.adjusted(+left, +top, -right, -bottom)
        x = effective.x()
        y = effective.y()
        line_height = 0

        for item in self._item_list:
            wid = item.widget()
            space_x = self.horizontalSpacing()
            if space_x < 0:
                space_x = wid.style().layoutSpacing(
                    QSizePolicy.ControlType.PushButton,
                    QSizePolicy.ControlType.PushButton,
                    Qt.Orientation.Horizontal,
                    None,
                    wid,
                )
            space_y = self.verticalSpacing()
            if space_y < 0:
                space_y = wid.style().layoutSpacing(
                    QSizePolicy.ControlType.PushButton,
                    QSizePolicy.ControlType.PushButton,
                    Qt.Orientation.Vertical,
                    None,
                    wid,
                )

            hint = item.sizeHint()
            next_x = x + hint.width() + space_x
            if next_x - space_x > effective.right() and line_height > 0:
                x = effective.x()
                y = y + line_height + space_y
                next_x = x + hint.width() + space_x
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))

            x = next_x
            line_height = max(line_height, hint.height())

        return y + line_height - rect.y() + bottom
