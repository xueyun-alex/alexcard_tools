import os
import sys
import tkinter as tk
from dataclasses import dataclass
from typing import Callable, Iterable, Literal
from tkinter import filedialog, messagebox, scrolledtext, simpledialog

from PIL import Image, ImageEnhance


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


def rename_stem(index: int) -> str:
    n = index // 2 + 1
    return str(n) if index % 2 == 0 else f"{n}-{n}"


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


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("批量图片长宽比 — 选择多张图片后查看")
        self.minsize(520, 360)
        self.geometry("720x480")
        try:
            self.iconbitmap(resource_path("monitor.ico"))
        except tk.TclError:
            pass

        bar = tk.Frame(self, padx=8, pady=8)
        bar.pack(fill=tk.X)

        tk.Button(bar, text="选择图片…", command=self.on_select_images).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        tk.Button(bar, text="复制全部", command=self.on_copy_all).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        tk.Button(bar, text="转为 JPG…", command=self.on_convert_to_jpg).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        tk.Button(bar, text="调整亮度…", command=self.on_adjust_brightness).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        tk.Button(bar, text="批量重命名…", command=self.on_rename_images).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        tk.Button(bar, text="序号重命名…", command=self.on_rename_by_pattern).pack(
            side=tk.LEFT
        )

        hint = (
            "每行：文件名 - 比例 (像素宽×高)。比例为短边=1、长边=倍数（横图 宽/高:1，竖图 1:高/宽）。无法读取的文件会标「错误」。"
        )
        tk.Label(self, text=hint, anchor="w", justify="left").pack(
            fill=tk.X, padx=8, pady=(0, 4)
        )

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
        err = validate_rename_batch(paths, rename_stem)
        if err:
            messagebox.showerror("批量重命名", err)
            return
        if not ask_rename_confirm(self, paths, rename_stem):
            return
        report, ok, fail = build_rename_report(paths, rename_stem)
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


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
