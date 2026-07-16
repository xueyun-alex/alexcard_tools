"""Tab1 长宽比查看。"""

import os
import tkinter as tk
from typing import Iterable
from tkinter import filedialog, messagebox

from PIL import Image

from .common import IMAGE_FILETYPES, ScrollableTab, _add_tool_row, _trim_float


def aspect_ratio_text(width: int, height: int) -> str:
    """短边为 1，长边为其倍数（横图 宽/高:1，竖图 1:高/宽，正方形 1:1）。"""
    if width <= 0 or height <= 0:
        return f"{width}×{height}"
    if width == height:
        return "1:1"
    if width > height:
        return f"{_trim_float(width / height)}:1"
    return f"1:{_trim_float(height / width)}"


def line_for_path(path: str) -> str:
    name = os.path.basename(path)
    try:
        with Image.open(path) as im:
            w, h = im.size
        ratio = aspect_ratio_text(w, h)
        return f"{name} - {ratio} ({w}×{h})"
    except Exception as e:
        return f"{name} - 错误: {e}"


def build_report(paths: Iterable[str]) -> str:
    lines = [line_for_path(p) for p in paths]
    return "\n".join(lines)


class AspectTab(ScrollableTab):
    def __init__(self, notebook: tk.Widget, app) -> None:
        super().__init__(notebook)
        self.app = app
        _add_tool_row(
            self.body,
            "选择图片…",
            self.on_select_images,
            "选择多张图片，在下方报告区显示文件名、长宽比（短边=1）和像素尺寸；无法读取的文件会标注错误。",
        )
        _add_tool_row(
            self.body,
            "复制全部",
            self.on_copy_all,
            "将报告区的全部文本复制到系统剪贴板。",
        )

    def on_select_images(self) -> None:
        paths = filedialog.askopenfilenames(
            title="选择图片（可多选）",
            filetypes=IMAGE_FILETYPES,
        )
        if not paths:
            return
        report = build_report(paths)
        self.app.text.delete("1.0", tk.END)
        self.app.text.insert(tk.END, report)

    def on_copy_all(self) -> None:
        content = self.app.text.get("1.0", tk.END).rstrip("\n")
        if not content:
            messagebox.showinfo("复制", "没有可复制的内容。")
            return
        self.app.clipboard_clear()
        self.app.clipboard_append(content)
        self.app.update()
        messagebox.showinfo("复制", "已复制到剪贴板。")
