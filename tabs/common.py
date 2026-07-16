"""跨 Tab 共享的常量与工具函数。"""

import os
import sys
import tkinter as tk

from PIL import Image

# 项目根目录（tabs/ 的上一级），保证草稿等文件位置与拆分前一致
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(relative: str) -> str:
    base = getattr(sys, "_MEIPASS", PROJECT_ROOT)
    return os.path.join(base, relative)


IMAGE_FILETYPES = [
    ("常见图片", "*.png;*.jpg;*.jpeg;*.webp;*.bmp;*.gif;*.tif;*.tiff"),
    ("PNG", "*.png"),
    ("JPEG", "*.jpg;*.jpeg"),
    ("WebP", "*.webp"),
    ("位图", "*.bmp"),
    ("GIF", "*.gif"),
    ("TIFF", "*.tif;*.tiff"),
    ("所有文件", "*.*"),
]

TEXT_FILETYPES = [
    ("文本文件", "*.txt"),
    ("所有文件", "*.*"),
]

IMAGE_EXTENSIONS = frozenset(
    {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
)


def list_images_in_dir(dir_path: str) -> list[str]:
    """非递归枚举目录内图片，按文件名排序，返回绝对路径。"""
    root = os.path.abspath(dir_path)
    names = [
        name
        for name in os.listdir(root)
        if os.path.splitext(name)[1].lower() in IMAGE_EXTENSIONS
        and os.path.isfile(os.path.join(root, name))
    ]
    names.sort()
    return [os.path.join(root, name) for name in names]


def _image_stem(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def _is_main_image_stem(stem: str) -> bool:
    """纯数字文件名（1、2、3…）视为该组主图。"""
    return bool(stem) and stem.isdigit()


def upload_pairs(paths: list[str]) -> list[tuple[str, ...]] | str:
    """
    两两成组；文件名（不含扩展名）为纯数字的是主图，须作为每组第一张。
    有主图时：主图按数字排序，其余图按文件名排序后一一配对为 (主图, 副图)。
    无主图时：退回按当前顺序两两分组。
    成功返回组列表；失败返回错误说明。
    """
    if not paths:
        return "未找到图片。"

    mains: list[str] = []
    others: list[str] = []
    for p in paths:
        if _is_main_image_stem(_image_stem(p)):
            mains.append(p)
        else:
            others.append(p)

    if mains:
        mains.sort(key=lambda p: int(_image_stem(p)))
        others.sort(key=lambda p: os.path.basename(p).lower())
        if len(mains) != len(others):
            return (
                f"主图（文件名为 1、2、3…）共 {len(mains)} 张，"
                f"副图共 {len(others)} 张，数量须一致。"
            )
        # 校验主图编号连续从 1 起更友好，但不强制（允许缺号只要数量对齐）
        return [(mains[i], others[i]) for i in range(len(mains))]

    pairs: list[tuple[str, ...]] = []
    for i in range(0, len(paths), 2):
        pairs.append(tuple(paths[i : i + 2]))
    return pairs


def _trim_float(x: float) -> str:
    """Trim trailing zeros from a fixed-point string."""
    s = f"{x:.10f}".rstrip("0").rstrip(".")
    return s if s else "0"


def prepare_for_jpeg(im: Image.Image) -> Image.Image:
    if im.mode in ("RGBA", "LA"):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        return bg
    if im.mode == "P":
        return prepare_for_jpeg(im.convert("RGBA"))
    if im.mode != "RGB":
        return im.convert("RGB")
    return im


# 按钮区固定高度（像素），超出部分通过滚动查看，给下方日志区留出更多空间
TAB_BODY_HEIGHT = 150


class ScrollableTab(tk.Frame):
    """按钮区固定高度、可上下滚动的 Tab 基类，工具行加到 self.body。"""

    def __init__(self, notebook: tk.Widget) -> None:
        super().__init__(notebook)
        canvas = tk.Canvas(self, height=TAB_BODY_HEIGHT, highlightthickness=0)
        scrollbar = tk.Scrollbar(self, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.body = tk.Frame(canvas)
        window = canvas.create_window((0, 0), window=self.body, anchor="nw")

        def on_body_configure(_event=None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def on_canvas_configure(event) -> None:
            canvas.itemconfigure(window, width=event.width)

        self.body.bind("<Configure>", on_body_configure)
        canvas.bind("<Configure>", on_canvas_configure)

        def on_mousewheel(event) -> None:
            canvas.yview_scroll(-1 * (event.delta // 120), "units")

        # 指针进入按钮区时接管滚轮，离开时归还（避免影响下方日志区滚动）
        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", on_mousewheel))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))


def _add_tool_row(parent: tk.Widget, text: str, command, description: str) -> None:
    block = tk.Frame(parent, padx=12, pady=6)
    block.pack(fill=tk.X, anchor="w")
    tk.Button(block, text=text, command=command).pack(anchor="w")
    tk.Label(
        block,
        text=description,
        anchor="w",
        justify="left",
        wraplength=660,
        fg="#555555",
        font=("", 9),
    ).pack(anchor="w", pady=(4, 0))
