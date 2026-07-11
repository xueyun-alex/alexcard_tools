import os
import shutil
import sys
import tkinter as tk
from dataclasses import dataclass
from typing import Callable, Iterable, Literal
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk

from PIL import Image, ImageEnhance

from gemini_copy import GEMINI_STYLE_PROMPT, get_gemini_session


def resource_path(relative: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
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


def _trim_float(x: float) -> str:
    """Trim trailing zeros from a fixed-point string."""
    s = f"{x:.10f}".rstrip("0").rstrip(".")
    return s if s else "0"


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


def jpg_output_path(src_path: str, out_dir: str) -> str:
    base, _ = os.path.splitext(os.path.basename(src_path))
    return os.path.join(out_dir, f"{base}.jpg")


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


def convert_to_jpg(src_path: str, out_dir: str, quality: int = 90) -> tuple[bool, str]:
    name = os.path.basename(src_path)
    dest = jpg_output_path(src_path, out_dir)
    try:
        with Image.open(src_path) as im:
            rgb = prepare_for_jpeg(im)
            os.makedirs(out_dir, exist_ok=True)
            rgb.save(dest, "JPEG", quality=quality)
            w, h = rgb.size
        return True, f"{os.path.basename(dest)} - 已保存 ({w}×{h})"
    except Exception as e:
        return False, f"{name} - 错误: {e}"


def build_convert_report(paths: Iterable[str], out_dir: str) -> tuple[str, int, int]:
    lines: list[str] = []
    ok = fail = 0
    for path in paths:
        success, line = convert_to_jpg(path, out_dir)
        lines.append(line)
        if success:
            ok += 1
        else:
            fail += 1
    return "\n".join(lines), ok, fail


def adjust_brightness(im: Image.Image, factor: float) -> Image.Image:
    if im.mode in ("RGBA", "LA"):
        rgb = ImageEnhance.Brightness(im.convert("RGB")).enhance(factor)
        result = rgb.convert("RGBA")
        result.putalpha(im.split()[-1])
        return result
    if im.mode == "P":
        return adjust_brightness(im.convert("RGBA"), factor)
    return ImageEnhance.Brightness(im).enhance(factor)


def brightness_output_path(src_path: str, out_dir: str) -> str:
    return os.path.join(out_dir, os.path.basename(src_path))


def save_image(im: Image.Image, dest_path: str, src_path: str) -> None:
    ext = os.path.splitext(src_path)[1].lower()
    if ext in (".jpg", ".jpeg"):
        im.save(dest_path, "JPEG", quality=90)
    elif ext == ".png":
        im.save(dest_path, "PNG")
    elif ext == ".webp":
        im.save(dest_path, "WEBP", quality=90)
    else:
        im.save(dest_path)


def adjust_image_brightness(
    src_path: str, out_dir: str, factor: float
) -> tuple[bool, str]:
    name = os.path.basename(src_path)
    dest = brightness_output_path(src_path, out_dir)
    try:
        with Image.open(src_path) as im:
            adjusted = adjust_brightness(im, factor)
            os.makedirs(out_dir, exist_ok=True)
            save_image(adjusted, dest, src_path)
            w, h = adjusted.size
        factor_text = _trim_float(factor)
        return True, f"{os.path.basename(dest)} - 已保存 ({w}×{h}, 倍数×{factor_text})"
    except Exception as e:
        return False, f"{name} - 错误: {e}"


def build_brightness_report(
    paths: Iterable[str], out_dir: str, factor: float
) -> tuple[str, int, int]:
    lines: list[str] = []
    ok = fail = 0
    for path in paths:
        success, line = adjust_image_brightness(path, out_dir, factor)
        lines.append(line)
        if success:
            ok += 1
        else:
            fail += 1
    return "\n".join(lines), ok, fail


def rename_stem_alternating(index: int, start: int) -> str:
    n = index // 2 + start
    return str(n) if index % 2 == 0 else f"{n}-{n}"


def rename_stem(index: int) -> str:
    return rename_stem_alternating(index, 1)


@dataclass(frozen=True)
class RenamePattern:
    mode: Literal["sequential", "paired"]
    start: int


def parse_rename_pattern(text: str) -> RenamePattern | None:
    text = text.strip()
    if not text:
        return None
    if text.isdigit():
        return RenamePattern("sequential", int(text))
    if "-" in text:
        left, _, right = text.partition("-")
        if left.isdigit() and right.isdigit() and left == right:
            return RenamePattern("paired", int(left))
    return None


def rename_stem_from_pattern(index: int, pattern: RenamePattern) -> str:
    n = pattern.start + index
    if pattern.mode == "sequential":
        return str(n)
    return f"{n}-{n}"


def rename_target_path(
    src_path: str, index: int, stem_fn: Callable[[int], str]
) -> str:
    ext = os.path.splitext(src_path)[1]
    return os.path.join(os.path.dirname(src_path), stem_fn(index) + ext)


def validate_rename_batch(
    paths: list[str], stem_fn: Callable[[int], str]
) -> str | None:
    if not paths:
        return "未选择任何图片。"
    dirs = {os.path.dirname(p) for p in paths}
    if len(dirs) > 1:
        return "所选图片须在同一文件夹内。"
    src_cases = {os.path.normcase(p) for p in paths}
    for i, src in enumerate(paths):
        dest = rename_target_path(src, i, stem_fn)
        if os.path.normcase(src) == os.path.normcase(dest):
            continue
        if os.path.exists(dest) and os.path.normcase(dest) not in src_cases:
            return f"目标文件名已存在：{os.path.basename(dest)}"
    return None


def rename_one_file(src: str, dest: str) -> tuple[bool, str]:
    src_name = os.path.basename(src)
    dest_name = os.path.basename(dest)
    try:
        os.rename(src, dest)
        return True, f"{src_name} -> {dest_name}"
    except Exception as e:
        return False, f"{src_name} - 错误: {e}"


def build_rename_preview(
    paths: list[str], stem_fn: Callable[[int], str]
) -> str:
    lines = [
        f"{os.path.basename(src)} -> {os.path.basename(rename_target_path(src, i, stem_fn))}"
        for i, src in enumerate(paths)
    ]
    return "\n".join(lines)


def ask_rename_confirm(
    parent: tk.Misc,
    paths: list[str],
    stem_fn: Callable[[int], str],
    *,
    title: str = "批量重命名",
    hint: str = "将按以下规则重命名（不可撤销）：",
) -> bool:
    """Show rename preview in a scrollable dialog; return True if user confirms."""
    result = {"confirmed": False}

    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.transient(parent)
    dialog.resizable(True, False)

    def close(confirmed: bool) -> None:
        result["confirmed"] = confirmed
        dialog.grab_release()
        dialog.destroy()

    dialog.protocol("WM_DELETE_WINDOW", lambda: close(False))

    tk.Label(
        dialog,
        text=hint,
        anchor="w",
    ).pack(fill=tk.X, padx=12, pady=(12, 4))

    list_frame = tk.Frame(dialog)
    list_frame.pack(fill=tk.X, padx=12, pady=4)

    scrollbar = tk.Scrollbar(list_frame)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    preview_box = tk.Text(
        list_frame,
        height=12,
        width=52,
        font=("Consolas", 10),
        wrap=tk.NONE,
        yscrollcommand=scrollbar.set,
        state=tk.NORMAL,
    )
    preview_box.pack(side=tk.LEFT, fill=tk.BOTH)
    scrollbar.config(command=preview_box.yview)

    preview_box.insert(tk.END, build_rename_preview(paths, stem_fn))
    preview_box.config(state=tk.DISABLED)

    btn_frame = tk.Frame(dialog, padx=12, pady=12)
    btn_frame.pack(fill=tk.X)
    tk.Button(btn_frame, text="继续", width=8, command=lambda: close(True)).pack(
        side=tk.RIGHT, padx=(6, 0)
    )
    tk.Button(btn_frame, text="取消", width=8, command=lambda: close(False)).pack(
        side=tk.RIGHT
    )

    dialog.update_idletasks()
    pw = parent.winfo_width()
    ph = parent.winfo_height()
    px = parent.winfo_rootx()
    py = parent.winfo_rooty()
    dw = dialog.winfo_width()
    dh = dialog.winfo_height()
    dialog.geometry(f"+{px + (pw - dw) // 2}+{py + (ph - dh) // 2}")

    dialog.grab_set()
    parent.wait_window(dialog)
    return result["confirmed"]


def rename_images_batch(
    paths: list[str], stem_fn: Callable[[int], str]
) -> tuple[str, int, int]:
    err = validate_rename_batch(paths, stem_fn)
    if err:
        return err, 0, len(paths)

    plan = [(p, rename_target_path(p, i, stem_fn)) for i, p in enumerate(paths)]
    lines: list[str] = []
    ok = fail = 0
    work: list[tuple[int, str, str]] = []

    for i, (src, dest) in enumerate(plan):
        if os.path.normcase(src) == os.path.normcase(dest):
            name = os.path.basename(src)
            lines.append(f"{name} - 已是目标名，跳过")
            ok += 1
        else:
            work.append((i, src, dest))

    tmp_map: dict[int, str] = {}
    for i, src, _dest in work:
        ext = os.path.splitext(src)[1]
        tmp = os.path.join(os.path.dirname(src), f".__rename_tmp_{i}{ext}")
        success, line = rename_one_file(src, tmp)
        if success:
            tmp_map[i] = tmp
        else:
            lines.append(line)
            fail += 1

    for i, _src, dest in work:
        if i not in tmp_map:
            continue
        success, line = rename_one_file(tmp_map[i], dest)
        lines.append(line)
        if success:
            ok += 1
        else:
            fail += 1

    return "\n".join(lines), ok, fail


def build_rename_report(
    paths: list[str], stem_fn: Callable[[int], str]
) -> tuple[str, int, int]:
    return rename_images_batch(paths, stem_fn)


def is_pure_sequence_stem(stem: str) -> bool:
    return stem.isdigit() and int(stem) >= 1


def filter_sequence_copy_paths(paths: list[str]) -> list[str]:
    filtered = [
        p
        for p in paths
        if is_pure_sequence_stem(os.path.splitext(os.path.basename(p))[0])
    ]
    return sorted(
        filtered, key=lambda p: int(os.path.splitext(os.path.basename(p))[0])
    )


def copy_dest_path(src_path: str, out_dir: str) -> str:
    return os.path.join(out_dir, os.path.basename(src_path))


def validate_copy_batch(paths: list[str], out_dir: str) -> str | None:
    if not paths:
        return "未选择任何图片。"
    dest_cases: set[str] = set()
    for src in paths:
        dest = copy_dest_path(src, out_dir)
        dest_case = os.path.normcase(dest)
        if dest_case in dest_cases:
            return f"目标文件名冲突：{os.path.basename(dest)}"
        dest_cases.add(dest_case)
        if os.path.exists(dest):
            return f"目标文件名已存在：{os.path.basename(dest)}"
    return None


def copy_one_file(src: str, dest: str) -> tuple[bool, str]:
    src_name = os.path.basename(src)
    dest_name = os.path.basename(dest)
    try:
        shutil.copy2(src, dest)
        return True, f"{src_name} -> {dest_name}"
    except Exception as e:
        return False, f"{src_name} - 错误: {e}"


def build_copy_preview(paths: list[str], out_dir: str) -> str:
    lines = [
        f"{os.path.basename(src)} -> {os.path.basename(copy_dest_path(src, out_dir))}"
        for src in paths
    ]
    return "\n".join(lines)


def ask_copy_confirm(parent: tk.Misc, paths: list[str], out_dir: str) -> bool:
    """Show copy preview in a scrollable dialog; return True if user confirms."""
    result = {"confirmed": False}

    dialog = tk.Toplevel(parent)
    dialog.title("序号复制")
    dialog.transient(parent)
    dialog.resizable(True, False)

    def close(confirmed: bool) -> None:
        result["confirmed"] = confirmed
        dialog.grab_release()
        dialog.destroy()

    dialog.protocol("WM_DELETE_WINDOW", lambda: close(False))

    tk.Label(
        dialog,
        text="将仅复制文件名为 1、2、3… 的图片（1-1、2-2 等跳过，原文件不变）：",
        anchor="w",
    ).pack(fill=tk.X, padx=12, pady=(12, 4))

    list_frame = tk.Frame(dialog)
    list_frame.pack(fill=tk.X, padx=12, pady=4)

    scrollbar = tk.Scrollbar(list_frame)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    preview_box = tk.Text(
        list_frame,
        height=12,
        width=52,
        font=("Consolas", 10),
        wrap=tk.NONE,
        yscrollcommand=scrollbar.set,
        state=tk.NORMAL,
    )
    preview_box.pack(side=tk.LEFT, fill=tk.BOTH)
    scrollbar.config(command=preview_box.yview)

    preview_box.insert(tk.END, build_copy_preview(paths, out_dir))
    preview_box.config(state=tk.DISABLED)

    btn_frame = tk.Frame(dialog, padx=12, pady=12)
    btn_frame.pack(fill=tk.X)
    tk.Button(btn_frame, text="继续", width=8, command=lambda: close(True)).pack(
        side=tk.RIGHT, padx=(6, 0)
    )
    tk.Button(btn_frame, text="取消", width=8, command=lambda: close(False)).pack(
        side=tk.RIGHT
    )

    dialog.update_idletasks()
    pw = parent.winfo_width()
    ph = parent.winfo_height()
    px = parent.winfo_rootx()
    py = parent.winfo_rooty()
    dw = dialog.winfo_width()
    dh = dialog.winfo_height()
    dialog.geometry(f"+{px + (pw - dw) // 2}+{py + (ph - dh) // 2}")

    dialog.grab_set()
    parent.wait_window(dialog)
    return result["confirmed"]


def copy_images_batch(paths: list[str], out_dir: str) -> tuple[str, int, int]:
    err = validate_copy_batch(paths, out_dir)
    if err:
        return err, 0, len(paths)

    os.makedirs(out_dir, exist_ok=True)
    lines: list[str] = []
    ok = fail = 0
    for src in paths:
        dest = copy_dest_path(src, out_dir)
        success, line = copy_one_file(src, dest)
        lines.append(line)
        if success:
            ok += 1
        else:
            fail += 1
    return "\n".join(lines), ok, fail


def build_copy_report(paths: list[str], out_dir: str) -> tuple[str, int, int]:
    return copy_images_batch(paths, out_dir)


def _add_tool_row(parent: tk.Widget, text: str, command, description: str) -> None:
    block = tk.Frame(parent, padx=12, pady=8)
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


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("ALEXCARD工具集")
        self.minsize(520, 360)
        self.geometry("720x520")
        try:
            self.iconbitmap(resource_path("monitor.ico"))
        except tk.TclError:
            pass

        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.X, padx=8, pady=8)

        tab_aspect = tk.Frame(notebook)
        notebook.add(tab_aspect, text="长宽比查看")
        _add_tool_row(
            tab_aspect,
            "选择图片…",
            self.on_select_images,
            "选择多张图片，在下方报告区显示文件名、长宽比（短边=1）和像素尺寸；无法读取的文件会标注错误。",
        )
        _add_tool_row(
            tab_aspect,
            "复制全部",
            self.on_copy_all,
            "将报告区的全部文本复制到系统剪贴板。",
        )

        tab_process = tk.Frame(notebook)
        notebook.add(tab_process, text="图片处理")
        _add_tool_row(
            tab_process,
            "转为 JPG…",
            self.on_convert_to_jpg,
            "选择图片和输出文件夹，将图片转换为 JPG（透明背景填充白色），并在报告区显示每张的转换结果。",
        )
        _add_tool_row(
            tab_process,
            "调整亮度…",
            self.on_adjust_brightness,
            "选择图片和输出文件夹，按倍数（0.01~10，1.0 不变）调整亮度后保存，保留原格式。",
        )

        tab_files = tk.Frame(notebook)
        notebook.add(tab_files, text="文件管理")
        _add_tool_row(
            tab_files,
            "批量重命名…",
            self.on_rename_images,
            "选择同文件夹下的图片，按交替规则重命名（如 1→1, 1-1, 2, 2-2…），预览确认后原地重命名。",
        )
        _add_tool_row(
            tab_files,
            "序号重命名…",
            self.on_rename_by_pattern,
            "选择同文件夹下的图片，按连续序号或配对序号重命名（1→1,2,3 或 1-1→1-1,2-2,3-3），预览确认后原地重命名。",
        )
        _add_tool_row(
            tab_files,
            "序号复制…",
            self.on_copy_by_sequence,
            "选择图片，仅复制纯数字文件名（1、2、3…，不含 1-1、2-2）到指定文件夹，预览确认后复制。",
        )

        tab_xianyu = tk.Frame(notebook)
        notebook.add(tab_xianyu, text="gmini自动获取文案")
        _add_tool_row(
            tab_xianyu,
            "打开 Gemini",
            self.on_open_gemini,
            "打开 Google AI Mode 网页，请先在此窗口登录；登录后勿关浏览器，再点「批量获取文案」。",
        )
        _add_tool_row(
            tab_xianyu,
            "批量获取文案…",
            self.on_gemini_batch,
            "弹出对话框输入提示词并选择图片，确定后依次发送给 Gemini；"
            "结果合并保存为所选图片目录下的 文案汇总.txt（仅【标题】【宝贝描述】【标签】，多条用 ======= 分隔）。",
        )

        self._gemini_busy = False
        self._gemini_session = get_gemini_session()
        self.protocol("WM_DELETE_WINDOW", self._on_app_close)
        self.text = scrolledtext.ScrolledText(
            self, wrap=tk.NONE, font=("Consolas", 10), undo=True
        )
        self.text.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

    def on_select_images(self) -> None:
        paths = filedialog.askopenfilenames(
            title="选择图片（可多选）",
            filetypes=IMAGE_FILETYPES,
        )
        if not paths:
            return
        report = build_report(paths)
        self.text.delete("1.0", tk.END)
        self.text.insert(tk.END, report)

    def on_copy_all(self) -> None:
        content = self.text.get("1.0", tk.END).rstrip("\n")
        if not content:
            messagebox.showinfo("复制", "没有可复制的内容。")
            return
        self.clipboard_clear()
        self.clipboard_append(content)
        self.update()
        messagebox.showinfo("复制", "已复制到剪贴板。")

    def on_convert_to_jpg(self) -> None:
        paths = filedialog.askopenfilenames(
            title="选择要转换的图片",
            filetypes=IMAGE_FILETYPES,
        )
        if not paths:
            return
        out_dir = filedialog.askdirectory(title="选择 JPG 输出文件夹")
        if not out_dir:
            return
        report, ok, fail = build_convert_report(paths, out_dir)
        self.text.delete("1.0", tk.END)
        self.text.insert(tk.END, report)
        messagebox.showinfo("转为 JPG", f"完成：成功 {ok} 张，失败 {fail} 张。")

    def on_adjust_brightness(self) -> None:
        paths = filedialog.askopenfilenames(
            title="选择要调整的图片",
            filetypes=IMAGE_FILETYPES,
        )
        if not paths:
            return
        out_dir = filedialog.askdirectory(title="选择输出文件夹")
        if not out_dir:
            return
        factor = simpledialog.askfloat(
            "亮度调整",
            "亮度倍数（1.0=不变，>1变亮，<1变暗）：",
            initialvalue=1.0,
            minvalue=0.01,
            maxvalue=10.0,
        )
        if factor is None:
            return
        if factor == 1.0 and not messagebox.askyesno(
            "亮度调整", "倍数为 1.0，图片亮度不会改变。是否继续？"
        ):
            return
        report, ok, fail = build_brightness_report(paths, out_dir, factor)
        self.text.delete("1.0", tk.END)
        self.text.insert(tk.END, report)
        messagebox.showinfo("调整亮度", f"完成：成功 {ok} 张，失败 {fail} 张。")

    def on_rename_images(self) -> None:
        paths = filedialog.askopenfilenames(
            title="选择要重命名的图片",
            filetypes=IMAGE_FILETYPES,
        )
        if not paths:
            return
        paths = list(paths)
        pattern_text = simpledialog.askstring(
            "批量重命名",
            "起始名称（如 1 → 1,1-1,2,2-2；3 → 3,3-3,4,4-4）：",
            initialvalue="1",
        )
        if pattern_text is None:
            return
        pattern = parse_rename_pattern(pattern_text)
        if pattern is None:
            messagebox.showerror(
                "批量重命名",
                "起始名称无效。请输入整数（如 1）或相同数字对（如 1-1）。",
            )
            return
        stem_fn = lambda i, s=pattern.start: rename_stem_alternating(i, s)
        err = validate_rename_batch(paths, stem_fn)
        if err:
            messagebox.showerror("批量重命名", err)
            return
        if not ask_rename_confirm(self, paths, stem_fn):
            return
        report, ok, fail = build_rename_report(paths, stem_fn)
        self.text.delete("1.0", tk.END)
        self.text.insert(tk.END, report)
        messagebox.showinfo("批量重命名", f"完成：成功 {ok} 张，失败 {fail} 张。")

    def on_rename_by_pattern(self) -> None:
        paths = filedialog.askopenfilenames(
            title="选择要重命名的图片",
            filetypes=IMAGE_FILETYPES,
        )
        if not paths:
            return
        paths = list(paths)
        pattern_text = simpledialog.askstring(
            "序号重命名",
            "起始名称（如 1 → 1,2,3；1-1 → 1-1,2-2,3-3）：",
            initialvalue="1",
        )
        if pattern_text is None:
            return
        pattern = parse_rename_pattern(pattern_text)
        if pattern is None:
            messagebox.showerror(
                "序号重命名",
                "起始名称无效。请输入整数（如 1）或相同数字对（如 1-1）。",
            )
            return
        stem_fn = lambda i, p=pattern: rename_stem_from_pattern(i, p)
        err = validate_rename_batch(paths, stem_fn)
        if err:
            messagebox.showerror("序号重命名", err)
            return
        if not ask_rename_confirm(
            self,
            paths,
            stem_fn,
            title="序号重命名",
            hint="将按以下规则重命名（不可撤销）：",
        ):
            return
        report, ok, fail = build_rename_report(paths, stem_fn)
        self.text.delete("1.0", tk.END)
        self.text.insert(tk.END, report)
        messagebox.showinfo("序号重命名", f"完成：成功 {ok} 张，失败 {fail} 张。")

    def on_copy_by_sequence(self) -> None:
        paths = filedialog.askopenfilenames(
            title="选择要复制的图片",
            filetypes=IMAGE_FILETYPES,
        )
        if not paths:
            return
        paths = list(paths)
        paths = filter_sequence_copy_paths(paths)
        if not paths:
            messagebox.showerror(
                "序号复制",
                "所选图片中没有纯序号文件（1、2、3…）。1-1、2-2 等不会被复制。",
            )
            return
        out_dir = filedialog.askdirectory(title="选择输出文件夹")
        if not out_dir:
            return
        err = validate_copy_batch(paths, out_dir)
        if err:
            messagebox.showerror("序号复制", err)
            return
        if not ask_copy_confirm(self, paths, out_dir):
            return
        report, ok, fail = build_copy_report(paths, out_dir)
        self.text.delete("1.0", tk.END)
        self.text.insert(tk.END, report)
        messagebox.showinfo("序号复制", f"完成：成功 {ok} 张，失败 {fail} 张。")

    def _append_report_line(self, line: str) -> None:
        self.text.insert(tk.END, line + "\n")
        self.text.see(tk.END)

    def _on_app_close(self) -> None:
        try:
            self._gemini_session.submit_close()
        except Exception:
            pass
        self.destroy()

    def on_open_gemini(self) -> None:
        if self._gemini_busy:
            messagebox.showinfo("打开 Gemini", "正在处理中，请稍候。")
            return
        self._gemini_busy = True
        self._append_report_line("正在打开 Gemini…")

        def on_progress(line: str) -> None:
            self.after(0, lambda l=line: self._append_report_line(l))

        def on_done() -> None:
            def finish() -> None:
                self._gemini_busy = False
                messagebox.showinfo(
                    "打开 Gemini",
                    "浏览器已打开。请先登录 Google，再点击「批量获取文案」。",
                )

            self.after(0, finish)

        def on_error(msg: str) -> None:
            def fail_ui() -> None:
                self._gemini_busy = False
                self._append_report_line(f"错误: {msg}")
                messagebox.showerror("打开 Gemini", msg)

            self.after(0, fail_ui)

        self._gemini_session.submit_open(
            on_progress=on_progress, on_done=on_done, on_error=on_error
        )

    def on_gemini_batch(self) -> None:
        if self._gemini_busy:
            messagebox.showinfo("批量获取文案", "正在处理中，请稍候。")
            return
        result = ask_gemini_batch_dialog(self, GEMINI_STYLE_PROMPT)
        if result is None:
            return
        prompt, paths = result
        self._gemini_busy = True
        self.text.delete("1.0", tk.END)
        self.text.insert(tk.END, f"开始处理 {len(paths)} 张图片…\n")

        def on_progress(line: str) -> None:
            self.after(0, lambda l=line: self._append_report_line(l))

        def on_done(lines: list[str], ok: int, fail: int, dest: str | None) -> None:
            def finish() -> None:
                self._gemini_busy = False
                if not lines:
                    self._append_report_line("没有处理结果。")
                detail = f"完成：成功 {ok} 张，失败 {fail} 张。"
                if dest:
                    detail += f"\n已写入：{dest}"
                elif ok == 0:
                    detail += "\n无成功文案可保存。"
                messagebox.showinfo("批量获取文案", detail)

            self.after(0, finish)

        def on_error(msg: str) -> None:
            def fail_ui() -> None:
                self._gemini_busy = False
                self._append_report_line(f"错误: {msg}")
                messagebox.showerror("批量获取文案", msg)

            self.after(0, fail_ui)

        self._gemini_session.submit_batch(
            paths,
            prompt,
            on_progress=on_progress,
            on_done=on_done,
            on_error=on_error,
        )


def ask_gemini_batch_dialog(
    parent: tk.Tk, default_prompt: str
) -> tuple[str, list[str]] | None:
    """提示词 + 选图对话框。确定返回 (prompt, paths)，取消返回 None。"""
    dlg = tk.Toplevel(parent)
    dlg.title("批量获取文案")
    dlg.transient(parent)
    dlg.grab_set()
    dlg.minsize(520, 420)
    dlg.geometry("640x480")

    result: dict[str, object] = {"ok": False}

    tk.Label(dlg, text="提示词：", anchor="w").pack(fill=tk.X, padx=12, pady=(12, 4))
    prompt_box = scrolledtext.ScrolledText(dlg, wrap=tk.WORD, height=12, font=("", 10))
    prompt_box.pack(fill=tk.BOTH, expand=True, padx=12)
    prompt_box.insert("1.0", default_prompt)

    paths_var = tk.StringVar(value="未选择图片")
    selected: list[str] = []

    def on_pick() -> None:
        files = filedialog.askopenfilenames(
            parent=dlg,
            title="选择图片（可多选）",
            filetypes=IMAGE_FILETYPES,
        )
        if not files:
            return
        selected.clear()
        selected.extend(files)
        names = [os.path.basename(p) for p in selected]
        preview = "、".join(names[:8])
        if len(names) > 8:
            preview += f" 等共 {len(names)} 张"
        else:
            preview = f"已选 {len(names)} 张：" + preview
        paths_var.set(preview)

    pick_row = tk.Frame(dlg, padx=12, pady=8)
    pick_row.pack(fill=tk.X)
    tk.Button(pick_row, text="选择图片…", command=on_pick).pack(side=tk.LEFT)
    tk.Label(
        pick_row, textvariable=paths_var, anchor="w", justify="left", wraplength=480
    ).pack(side=tk.LEFT, padx=(8, 0), fill=tk.X, expand=True)

    def on_ok() -> None:
        prompt = prompt_box.get("1.0", tk.END).strip()
        if not prompt:
            messagebox.showerror("批量获取文案", "请输入提示词。", parent=dlg)
            return
        if not selected:
            messagebox.showerror("批量获取文案", "请至少选择一张图片。", parent=dlg)
            return
        result["ok"] = True
        result["prompt"] = prompt
        result["paths"] = list(selected)
        dlg.destroy()

    def on_cancel() -> None:
        dlg.destroy()

    btn_row = tk.Frame(dlg, padx=12, pady=12)
    btn_row.pack(fill=tk.X)
    tk.Button(btn_row, text="取消", command=on_cancel, width=10).pack(side=tk.RIGHT)
    tk.Button(btn_row, text="确定", command=on_ok, width=10).pack(
        side=tk.RIGHT, padx=(0, 8)
    )

    dlg.protocol("WM_DELETE_WINDOW", on_cancel)
    parent.wait_window(dlg)

    if not result.get("ok"):
        return None
    return str(result["prompt"]), list(result["paths"])  # type: ignore[arg-type]


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
