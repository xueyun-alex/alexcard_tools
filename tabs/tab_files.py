"""Tab3 文件管理：批量重命名、序号重命名、序号复制。"""

import os
import re
import shutil
import tkinter as tk
from dataclasses import dataclass
from typing import Callable, Literal
from tkinter import filedialog, messagebox, simpledialog

from .common import IMAGE_FILETYPES, ScrollableTab, _add_tool_row


def rename_stem_alternating(index: int, start: int) -> str:
    n = index // 2 + start
    return str(n) if index % 2 == 0 else f"{n}-{n}"


def rename_stem(index: int) -> str:
    return rename_stem_alternating(index, 1)


def natural_filename_key(path: str) -> tuple[tuple[int, int | str], ...]:
    """按文件名中的数字片段进行自然排序，不区分大小写。"""
    return tuple(
        (1, int(part)) if part.isdigit() else (0, part)
        for part in re.split(r"(\d+)", os.path.basename(path).lower())
    )


def alexcard_rename_stem(index: int) -> str:
    return f"alexcard_{index + 1}"


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


class FilesTab(ScrollableTab):
    def __init__(self, notebook: tk.Widget, app) -> None:
        super().__init__(notebook)
        self.app = app
        _add_tool_row(
            self.body,
            "批量重命名…",
            self.on_rename_images,
            "选择同文件夹下的图片，按交替规则重命名（如 1→1, 1-1, 2, 2-2…），预览确认后原地重命名。",
        )
        _add_tool_row(
            self.body,
            "序号重命名…",
            self.on_rename_by_pattern,
            "选择同文件夹下的图片，按连续序号或配对序号重命名（1→1,2,3 或 1-1→1-1,2-2,3-3），预览确认后原地重命名。",
        )
        _add_tool_row(
            self.body,
            "序号复制…",
            self.on_copy_by_sequence,
            "选择图片，仅复制纯数字文件名（1、2、3…，不含 1-1、2-2）到指定文件夹，预览确认后复制。",
        )
        _add_tool_row(
            self.body,
            "重命名文件…",
            self.on_rename_to_alexcard,
            "选择同文件夹下的图片，按原文件名自然排序后重命名为 alexcard_1、alexcard_2…，保留原扩展名。",
        )

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
        if not ask_rename_confirm(self.app, paths, stem_fn):
            return
        report, ok, fail = build_rename_report(paths, stem_fn)
        self.app.text.delete("1.0", tk.END)
        self.app.text.insert(tk.END, report)
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
            self.app,
            paths,
            stem_fn,
            title="序号重命名",
            hint="将按以下规则重命名（不可撤销）：",
        ):
            return
        report, ok, fail = build_rename_report(paths, stem_fn)
        self.app.text.delete("1.0", tk.END)
        self.app.text.insert(tk.END, report)
        messagebox.showinfo("序号重命名", f"完成：成功 {ok} 张，失败 {fail} 张。")

    def on_rename_to_alexcard(self) -> None:
        paths = filedialog.askopenfilenames(
            title="选择要重命名为 Alexcard 顺序的图片",
            filetypes=IMAGE_FILETYPES,
        )
        if not paths:
            return
        paths = sorted(paths, key=natural_filename_key)
        err = validate_rename_batch(paths, alexcard_rename_stem)
        if err:
            messagebox.showerror("重命名文件", err)
            return
        if not ask_rename_confirm(
            self.app,
            paths,
            alexcard_rename_stem,
            title="重命名文件",
            hint="将按原文件名自然排序，并按以下规则重命名（不可撤销）：",
        ):
            return
        report, ok, fail = build_rename_report(paths, alexcard_rename_stem)
        self.app.text.delete("1.0", tk.END)
        self.app.text.insert(tk.END, report)
        messagebox.showinfo("重命名文件", f"完成：成功 {ok} 张，失败 {fail} 张。")

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
        if not ask_copy_confirm(self.app, paths, out_dir):
            return
        report, ok, fail = build_copy_report(paths, out_dir)
        self.app.text.delete("1.0", tk.END)
        self.app.text.insert(tk.END, report)
        messagebox.showinfo("序号复制", f"完成：成功 {ok} 张，失败 {fail} 张。")
