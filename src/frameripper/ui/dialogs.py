from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from frameripper.export import naming
from frameripper.export.exporter import FORMATS, LOSSY, ExportOptions


def _buttons(dialog: QDialog, ok_text: str) -> QDialogButtonBox:
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    ok = box.button(QDialogButtonBox.Ok)
    ok.setText(ok_text)
    ok.setObjectName("Primary")
    box.accepted.connect(dialog.accept)
    box.rejected.connect(dialog.reject)
    return box


class ExportDialog(QDialog):
    """Folder, format, quality and filename template for exports."""

    def __init__(
        self,
        opts: ExportOptions,
        sample: dict,
        count: int,
        parent=None,
        title: str = "Export",
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(520)
        self._sample = sample

        self.folder = QLineEdit(str(opts.folder))
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(browse)

        self.fmt = QComboBox()
        for key in FORMATS:
            self.fmt.addItem(key.upper(), key)
        self.fmt.setCurrentIndex(max(0, self.fmt.findData(opts.fmt)))

        self.quality = QSlider(Qt.Horizontal)
        self.quality.setRange(50, 100)
        self.quality.setValue(opts.quality)
        self.quality_label = QLabel()
        self.quality_label.setMinimumWidth(80)
        q_row = QHBoxLayout()
        q_row.addWidget(self.quality, 1)
        q_row.addWidget(self.quality_label)

        self.template = QLineEdit(opts.template)
        tokens = "  ".join(f"{{{k}}}" for k in naming.TOKENS)
        hint = QLabel(f"Tokens: {tokens}")
        hint.setObjectName("Muted")
        hint.setToolTip("\n".join(f"{{{k}}}  {v}" for k, v in naming.TOKENS.items()))
        self.preview = QLabel()
        self.preview.setObjectName("Muted")
        self.preview.setTextInteractionFlags(Qt.TextSelectableByMouse)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setVerticalSpacing(10)
        form.addRow("Folder", folder_row)
        form.addRow("Format", self.fmt)
        form.addRow("Quality", q_row)
        form.addRow("File name", self.template)
        form.addRow("", hint)
        form.addRow("Preview", self.preview)

        heading = QLabel(f"Export {count} frame{'s' if count != 1 else ''}")
        heading.setObjectName("Heading")

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(heading)
        layout.addLayout(form)
        layout.addWidget(_buttons(self, "Export"))

        self.fmt.currentIndexChanged.connect(self._update)
        self.quality.valueChanged.connect(self._update)
        self.template.textChanged.connect(self._update)
        self._update()

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Export folder", self.folder.text())
        if folder:
            self.folder.setText(folder)

    def _update(self) -> None:
        fmt = self.fmt.currentData()
        lossy = fmt in LOSSY
        self.quality.setEnabled(lossy)
        q = self.quality.value()
        if not lossy:
            self.quality_label.setText("lossless")
        elif fmt == "webp" and q >= 100:
            self.quality_label.setText("lossless")
        else:
            self.quality_label.setText(str(q))
        stem = naming.expand(self.template.text(), **self._sample)
        self.preview.setText(f"{stem}.{fmt}")

    def options(self) -> ExportOptions:
        return ExportOptions(
            folder=Path(self.folder.text()).expanduser(),
            fmt=self.fmt.currentData(),
            quality=self.quality.value(),
            template=self.template.text() or naming.DEFAULT_TEMPLATE,
        )


class AutoPickDialog(QDialog):
    def __init__(self, analysed_fraction: float, window: float, mode: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Auto-pick stills")
        self.setMinimumWidth(420)

        heading = QLabel("Suggest the sharpest, steadiest frames")
        heading.setObjectName("Heading")

        self.per_window = QRadioButton("Best frame every")
        self.per_scene = QRadioButton("Best frame per scene (detected cuts)")
        group = QButtonGroup(self)
        group.addButton(self.per_window)
        group.addButton(self.per_scene)
        (self.per_scene if mode == "scene" else self.per_window).setChecked(True)

        self.window = QDoubleSpinBox()
        self.window.setRange(0.2, 600)
        self.window.setDecimals(1)
        self.window.setSingleStep(0.5)
        self.window.setSuffix(" s")
        self.window.setValue(window)
        win_row = QHBoxLayout()
        win_row.addWidget(self.per_window)
        win_row.addWidget(self.window)
        win_row.addStretch(1)

        self.replace = QCheckBox("Replace existing suggestions")
        self.replace.setChecked(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(heading)
        if analysed_fraction < 1:
            note = QLabel(
                f"Sharpness analysis is {analysed_fraction:.0%} done; "
                "only analysed frames can be picked."
            )
            note.setObjectName("Muted")
            note.setWordWrap(True)
            layout.addWidget(note)
        layout.addLayout(win_row)
        layout.addWidget(self.per_scene)
        layout.addWidget(self.replace)
        layout.addWidget(_buttons(self, "Suggest"))

    def mode(self) -> str:
        return "scene" if self.per_scene.isChecked() else "window"


class ShortcutsDialog(QDialog):
    def __init__(self, groups: list[tuple[str, list[tuple[str, str]]]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Keyboard shortcuts")
        self.setMinimumSize(560, 520)

        body = QWidget()
        grid = QGridLayout(body)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(6)
        row = 0
        for title, entries in groups:
            head = QLabel(title)
            head.setObjectName("Heading")
            grid.addWidget(head, row, 0, 1, 2)
            row += 1
            for label, keys in entries:
                k = QLabel(keys)
                k.setStyleSheet(
                    "font-family: Consolas, 'Cascadia Mono', monospace; color: #4cc2ff;"
                )
                grid.addWidget(k, row, 0, Qt.AlignRight)
                grid.addWidget(QLabel(label), row, 1)
                row += 1
            grid.setRowMinimumHeight(row, 10)
            row += 1
        grid.setColumnStretch(1, 1)

        scroll = QScrollArea()
        scroll.setWidget(body)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)

        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(scroll, 1)
        layout.addWidget(close)


def key_text(shortcuts: list[QKeySequence]) -> str:
    return "  /  ".join(s.toString(QKeySequence.NativeText) for s in shortcuts)


class PreferencesDialog(QDialog):
    def __init__(self, cache_mb: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.cache = QSpinBox()
        self.cache.setRange(128, 16384)
        self.cache.setSingleStep(128)
        self.cache.setSuffix(" MB")
        self.cache.setValue(cache_mb)
        note = QLabel(
            "Memory used to keep recently viewed frames for instant stepping.\n"
            "Applies to the next video you open."
        )
        note.setObjectName("Muted")
        form = QFormLayout()
        form.addRow("Frame cache", self.cache)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(_buttons(self, "Save"))
