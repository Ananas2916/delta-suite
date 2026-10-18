"""Classifica compatta (posizione, pilota, distacco, ultimo giro); clic su una riga → car_clicked."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget

from ui.theme import C
from ui.widgets import table_item


class TimingTable(QTableWidget):
    """Classifica compatta come le torri dei tempi in TV: posizione, pilota, distacco, ultimo giro.
    Un segno colorato a sinistra indica le auto nei riquadri; clic su una riga → riquadro principale."""

    car_clicked = pyqtSignal(int)

    def __init__(self):
        super().__init__(0, 4)
        self.setHorizontalHeaderLabels(["P", "Pilota", "Distacco", "Ultimo"])
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(22)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setShowGrid(False)
        self.setStyleSheet("QTableWidget { font-size: 9pt; }")
        hh = self.horizontalHeader()
        for col, mode in enumerate((QHeaderView.ResizeMode.ResizeToContents, QHeaderView.ResizeMode.Stretch,
                                    QHeaderView.ResizeMode.ResizeToContents,
                                    QHeaderView.ResizeMode.ResizeToContents)):
            hh.setSectionResizeMode(col, mode)
        self._indices: list[int] = []
        self.cellClicked.connect(lambda row, _col: self.car_clicked.emit(self._indices[row])
                                 if row < len(self._indices) else None)

    def fill(self, rows: list[tuple[int, str, str, str, str, bool, str | None]]):
        """rows: (indice auto, posizione, pilota, distacco, ultimo, sei tu, colore del riquadro o None)."""
        self._indices = [r[0] for r in rows]
        self.setRowCount(len(rows))
        for i, (_idx, pos, driver, gap, last, me, ring) in enumerate(rows):
            cells = [table_item(pos, bold=True), table_item(driver, C["accent"] if me else None, me),
                     table_item(gap), table_item(last)]
            cells[1].setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            if ring:
                cells[0].setBackground(QColor(ring))
                cells[0].setForeground(QColor("#111111"))
            for col, cell in enumerate(cells):
                self.setItem(i, col, cell)
