import os
import sys
import tkinter as tk
from typing import Iterable
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


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
