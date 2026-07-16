"""Tab2 图片处理：转 JPG、亮度调整、海报双图/单图多次/组合贴入。"""

import os
import tkinter as tk
from typing import Iterable
from tkinter import filedialog, messagebox, simpledialog

from PIL import Image, ImageEnhance, ImageTk

from .common import (
    IMAGE_FILETYPES,
    _add_tool_row,
    _image_stem,
    _is_main_image_stem,
    _trim_float,
    list_images_in_dir,
    prepare_for_jpeg,
    upload_pairs,
)


def jpg_output_path(src_path: str, out_dir: str) -> str:
    base, _ = os.path.splitext(os.path.basename(src_path))
    return os.path.join(out_dir, f"{base}.jpg")


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


PosterBox = tuple[int, int, int, int]  # left, top, right, bottom


def fit_cover(im: Image.Image, box_w: int, box_h: int) -> Image.Image:
    """等比放大后居中裁切，铺满目标尺寸。"""
    if box_w <= 0 or box_h <= 0:
        raise ValueError("框尺寸无效")
    src_w, src_h = im.size
    if src_w <= 0 or src_h <= 0:
        raise ValueError("源图尺寸无效")
    scale = max(box_w / src_w, box_h / src_h)
    new_w = max(1, round(src_w * scale))
    new_h = max(1, round(src_h * scale))
    resized = im.resize((new_w, new_h), Image.Resampling.LANCZOS)
    left = max(0, (new_w - box_w) // 2)
    top = max(0, (new_h - box_h) // 2)
    return resized.crop((left, top, left + box_w, top + box_h))


def paste_into_poster(
    poster: Image.Image, img: Image.Image, box: PosterBox
) -> None:
    left, top, right, bottom = box
    fitted = fit_cover(img, right - left, bottom - top)
    if fitted.mode == "P":
        fitted = fitted.convert("RGBA")
    if fitted.mode in ("RGBA", "LA"):
        rgba = fitted.convert("RGBA")
        poster.paste(rgba, (left, top), rgba)
    else:
        if fitted.mode != poster.mode and poster.mode in ("RGB", "RGBA", "L"):
            fitted = fitted.convert(poster.mode)
        poster.paste(fitted, (left, top))


def poster_compose_output_path(poster_path: str, img1_path: str) -> str:
    """导出为 poster_{组内第一张图stem}.png，保存在海报同目录。"""
    directory = os.path.dirname(os.path.abspath(poster_path))
    return os.path.join(directory, f"poster_{_image_stem(img1_path)}.png")


def compose_poster_pair(
    poster_path: str,
    img1_path: str,
    img2_path: str,
    box1: PosterBox,
    box2: PosterBox,
    dest_path: str,
) -> tuple[bool, str]:
    label = (
        f"{os.path.basename(img1_path)} + {os.path.basename(img2_path)}"
        f" → {os.path.basename(dest_path)}"
    )
    try:
        with Image.open(poster_path) as base:
            poster = base.copy()
        # JPG 海报先转 RGB，便于贴图与导出 PNG
        if os.path.splitext(poster_path)[1].lower() in (".jpg", ".jpeg"):
            poster = prepare_for_jpeg(poster)
        with Image.open(img1_path) as im1:
            paste_into_poster(poster, im1.copy(), box1)
        with Image.open(img2_path) as im2:
            paste_into_poster(poster, im2.copy(), box2)
        if poster.mode not in ("RGB", "RGBA"):
            if poster.mode in ("LA", "P"):
                poster = poster.convert("RGBA")
            else:
                poster = poster.convert("RGB")
        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        poster.save(dest_path, "PNG")
        w, h = poster.size
        return True, f"{label} - 已保存 ({w}×{h})"
    except Exception as e:
        return False, f"{label} - 错误: {e}"


def build_poster_compose_report(
    poster_path: str,
    pairs: list[tuple[str, ...]],
    box1: PosterBox,
    box2: PosterBox,
) -> tuple[str, int, int]:
    lines: list[str] = []
    ok = fail = 0
    for i, pair in enumerate(pairs, start=1):
        if len(pair) < 2:
            lines.append(f"第 {i} 组 - 错误: 图片不足两张，已跳过")
            fail += 1
            continue
        dest = poster_compose_output_path(poster_path, pair[0])
        success, line = compose_poster_pair(
            poster_path, pair[0], pair[1], box1, box2, dest
        )
        lines.append(line)
        if success:
            ok += 1
        else:
            fail += 1
    return "\n".join(lines), ok, fail


def compose_poster_single_multi(
    poster_path: str,
    img_path: str,
    boxes: list[PosterBox],
    dest_path: str,
) -> tuple[bool, str]:
    label = (
        f"{os.path.basename(img_path)} × {len(boxes)} 处"
        f" → {os.path.basename(dest_path)}"
    )
    try:
        with Image.open(poster_path) as base:
            poster = base.copy()
        if os.path.splitext(poster_path)[1].lower() in (".jpg", ".jpeg"):
            poster = prepare_for_jpeg(poster)
        with Image.open(img_path) as im:
            img = im.copy()
            for box in boxes:
                paste_into_poster(poster, img, box)
        if poster.mode not in ("RGB", "RGBA"):
            if poster.mode in ("LA", "P"):
                poster = poster.convert("RGBA")
            else:
                poster = poster.convert("RGB")
        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        poster.save(dest_path, "PNG")
        w, h = poster.size
        return True, f"{label} - 已保存 ({w}×{h})"
    except Exception as e:
        return False, f"{label} - 错误: {e}"


def build_poster_single_multi_report(
    poster_path: str,
    image_paths: list[str],
    boxes: list[PosterBox],
) -> tuple[str, int, int]:
    lines: list[str] = []
    ok = fail = 0
    for img_path in image_paths:
        dest = poster_compose_output_path(poster_path, img_path)
        success, line = compose_poster_single_multi(
            poster_path, img_path, boxes, dest
        )
        lines.append(line)
        if success:
            ok += 1
        else:
            fail += 1
    return "\n".join(lines), ok, fail


def compose_poster_combined(
    poster_path: str,
    img1_path: str,
    img2_path: str,
    box1: PosterBox,
    box2: PosterBox,
    multi_boxes: list[PosterBox],
    dest_path: str,
) -> tuple[bool, str]:
    """主图贴入 box1 与全部 multi_boxes，副图贴入 box2，输出一张海报。"""
    label = (
        f"{os.path.basename(img1_path)} + {os.path.basename(img2_path)}"
        f"（主图另贴 {len(multi_boxes)} 处）"
        f" → {os.path.basename(dest_path)}"
    )
    try:
        with Image.open(poster_path) as base:
            poster = base.copy()
        if os.path.splitext(poster_path)[1].lower() in (".jpg", ".jpeg"):
            poster = prepare_for_jpeg(poster)
        with Image.open(img1_path) as im1:
            img1 = im1.copy()
            paste_into_poster(poster, img1, box1)
            for box in multi_boxes:
                paste_into_poster(poster, img1, box)
        with Image.open(img2_path) as im2:
            paste_into_poster(poster, im2.copy(), box2)
        if poster.mode not in ("RGB", "RGBA"):
            if poster.mode in ("LA", "P"):
                poster = poster.convert("RGBA")
            else:
                poster = poster.convert("RGB")
        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        poster.save(dest_path, "PNG")
        w, h = poster.size
        return True, f"{label} - 已保存 ({w}×{h})"
    except Exception as e:
        return False, f"{label} - 错误: {e}"


def build_poster_combined_report(
    poster_path: str,
    pairs: list[tuple[str, ...]],
    box1: PosterBox,
    box2: PosterBox,
    multi_boxes: list[PosterBox],
) -> tuple[str, int, int]:
    lines: list[str] = []
    ok = fail = 0
    for i, pair in enumerate(pairs, start=1):
        if len(pair) < 2:
            lines.append(f"第 {i} 组 - 错误: 图片不足两张，已跳过")
            fail += 1
            continue
        dest = poster_compose_output_path(poster_path, pair[0])
        success, line = compose_poster_combined(
            poster_path, pair[0], pair[1], box1, box2, multi_boxes, dest
        )
        lines.append(line)
        if success:
            ok += 1
        else:
            fail += 1
    return "\n".join(lines), ok, fail


def sorted_main_image_paths(paths: list[str]) -> list[str]:
    """仅保留纯数字 stem（1、2、3…）并按数字排序。"""
    mains = [p for p in paths if _is_main_image_stem(_image_stem(p))]
    mains.sort(key=lambda p: int(_image_stem(p)))
    return mains


def normalize_poster_box(x0: int, y0: int, x1: int, y1: int) -> PosterBox:
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def ask_poster_regions(
    parent: tk.Tk, poster_path: str
) -> tuple[PosterBox, PosterBox] | None:
    """弹出预览，依次拖出两个矩形；确认后返回原图像素坐标，取消返回 None。"""
    try:
        with Image.open(poster_path) as im:
            original = im.convert("RGBA") if im.mode == "P" else im.copy()
            orig_w, orig_h = original.size
    except Exception as e:
        messagebox.showerror("海报双图贴入", f"无法打开海报：{e}", parent=parent)
        return None

    max_side = 900
    scale = min(1.0, max_side / max(orig_w, orig_h))
    disp_w = max(1, int(round(orig_w * scale)))
    disp_h = max(1, int(round(orig_h * scale)))
    display = original.resize((disp_w, disp_h), Image.Resampling.LANCZOS)

    dialog = tk.Toplevel(parent)
    dialog.title("框选海报两个位置")
    dialog.transient(parent)
    dialog.grab_set()
    dialog.resizable(True, True)

    hint = tk.StringVar(value="请拖拽框选位置 1，完成后点击「确认本框」")
    top_row = tk.Frame(dialog)
    top_row.pack(fill=tk.X, padx=12, pady=(12, 4))
    tk.Label(top_row, textvariable=hint, anchor="w").pack(
        side=tk.LEFT, fill=tk.X, expand=True
    )
    confirm_btn = tk.Button(top_row, text="确认本框")
    confirm_btn.pack(side=tk.LEFT, padx=(8, 0))

    # 视口高度受屏幕限制，内容超出时右侧显示滚动条
    view_h = min(disp_h, max(200, parent.winfo_screenheight() - 260))

    canvas_frame = tk.Frame(dialog)
    canvas_frame.pack(padx=12, pady=4, fill=tk.BOTH, expand=True)

    canvas = tk.Canvas(
        canvas_frame,
        width=disp_w,
        height=view_h,
        highlightthickness=1,
        cursor="crosshair",
        scrollregion=(0, 0, disp_w, disp_h),
    )
    vbar = tk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=canvas.yview)
    canvas.configure(yscrollcommand=vbar.set)
    vbar.pack(side=tk.RIGHT, fill=tk.Y)
    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    photo = ImageTk.PhotoImage(display, master=dialog)
    canvas.create_image(0, 0, anchor="nw", image=photo)
    canvas.image = photo  # type: ignore[attr-defined]

    def on_mousewheel(event: tk.Event) -> None:
        canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    canvas.bind("<MouseWheel>", on_mousewheel)

    state: dict = {
        "step": 1,
        "boxes_disp": [],
        "drag_start": None,
        "temp_id": None,
        "box_ids": [],
        "result": None,
    }

    def canvas_to_orig(box: PosterBox) -> PosterBox:
        l, t, r, b = box
        return (
            max(0, min(orig_w, int(round(l / scale)))),
            max(0, min(orig_h, int(round(t / scale)))),
            max(0, min(orig_w, int(round(r / scale)))),
            max(0, min(orig_h, int(round(b / scale)))),
        )

    def event_xy(event: tk.Event) -> tuple[int, int]:
        return int(canvas.canvasx(event.x)), int(canvas.canvasy(event.y))

    def on_press(event: tk.Event) -> None:
        if state["step"] > 2:
            return
        state["drag_start"] = event_xy(event)
        if state["temp_id"] is not None:
            canvas.delete(state["temp_id"])
            state["temp_id"] = None

    def on_drag(event: tk.Event) -> None:
        start = state["drag_start"]
        if start is None:
            return
        x0, y0 = start
        ex, ey = event_xy(event)
        if state["temp_id"] is not None:
            canvas.delete(state["temp_id"])
        state["temp_id"] = canvas.create_rectangle(
            x0, y0, ex, ey, outline="#e53935", width=2
        )

    def on_release(event: tk.Event) -> None:
        start = state["drag_start"]
        if start is None:
            return
        x0, y0 = start
        state["drag_start"] = None
        ex, ey = event_xy(event)
        box = normalize_poster_box(x0, y0, ex, ey)
        if box[2] - box[0] < 4 or box[3] - box[1] < 4:
            if state["temp_id"] is not None:
                canvas.delete(state["temp_id"])
                state["temp_id"] = None
            return
        if state["temp_id"] is not None:
            canvas.delete(state["temp_id"])
            state["temp_id"] = None
        # replace unfinished rect for current step
        while len(state["boxes_disp"]) >= state["step"]:
            state["boxes_disp"].pop()
            if state["box_ids"]:
                canvas.delete(state["box_ids"].pop())
        color = "#1e88e5" if state["step"] == 1 else "#43a047"
        rid = canvas.create_rectangle(*box, outline=color, width=2)
        state["boxes_disp"].append(box)
        state["box_ids"].append(rid)

    def confirm_box() -> None:
        if len(state["boxes_disp"]) < state["step"]:
            messagebox.showwarning(
                "框选海报两个位置",
                f"请先框选位置 {state['step']}。",
                parent=dialog,
            )
            return
        if state["step"] == 1:
            state["step"] = 2
            hint.set("请拖拽框选位置 2，完成后点击「确认本框」")
        else:
            b1 = canvas_to_orig(state["boxes_disp"][0])
            b2 = canvas_to_orig(state["boxes_disp"][1])
            if b1[2] - b1[0] < 2 or b1[3] - b1[1] < 2:
                messagebox.showwarning(
                    "框选海报两个位置", "位置 1 映射后过小，请重新框选。", parent=dialog
                )
                return
            if b2[2] - b2[0] < 2 or b2[3] - b2[1] < 2:
                messagebox.showwarning(
                    "框选海报两个位置", "位置 2 映射后过小，请重新框选。", parent=dialog
                )
                return
            state["result"] = (b1, b2)
            dialog.destroy()

    def undo_current() -> None:
        if state["temp_id"] is not None:
            canvas.delete(state["temp_id"])
            state["temp_id"] = None
        if len(state["boxes_disp"]) >= state["step"] and state["box_ids"]:
            canvas.delete(state["box_ids"].pop())
            state["boxes_disp"].pop()
        elif state["step"] == 2 and state["boxes_disp"]:
            state["step"] = 1
            hint.set("请拖拽框选位置 1，完成后点击「确认本框」")
            if state["box_ids"]:
                canvas.delete(state["box_ids"].pop())
            state["boxes_disp"].pop()

    def on_cancel() -> None:
        state["result"] = None
        dialog.destroy()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)

    confirm_btn.configure(command=confirm_box)

    btn_row = tk.Frame(dialog)
    btn_row.pack(fill=tk.X, padx=12, pady=(8, 12))
    tk.Button(btn_row, text="撤销当前框", command=undo_current).pack(side=tk.LEFT)
    tk.Button(btn_row, text="取消", command=on_cancel).pack(side=tk.RIGHT)

    dialog.protocol("WM_DELETE_WINDOW", on_cancel)
    parent.wait_window(dialog)
    return state["result"]


_MULTI_BOX_COLORS = ("#1e88e5", "#43a047", "#fb8c00", "#8e24aa", "#e53935")


def ask_poster_regions_multi(
    parent: tk.Tk, poster_path: str
) -> list[PosterBox] | None:
    """弹出预览，边框边加多个矩形；完成框选后返回原图像素坐标，取消返回 None。"""
    try:
        with Image.open(poster_path) as im:
            original = im.convert("RGBA") if im.mode == "P" else im.copy()
            orig_w, orig_h = original.size
    except Exception as e:
        messagebox.showerror("单图多次贴入", f"无法打开海报：{e}", parent=parent)
        return None

    max_side = 900
    scale = min(1.0, max_side / max(orig_w, orig_h))
    disp_w = max(1, int(round(orig_w * scale)))
    disp_h = max(1, int(round(orig_h * scale)))
    display = original.resize((disp_w, disp_h), Image.Resampling.LANCZOS)

    dialog = tk.Toplevel(parent)
    dialog.title("框选海报多个位置")
    dialog.transient(parent)
    dialog.grab_set()
    dialog.resizable(True, True)

    hint = tk.StringVar(
        value="请拖拽框选位置 1，完成后点击「确认本框」；至少 2 处后点「完成框选」"
    )
    top_row = tk.Frame(dialog)
    top_row.pack(fill=tk.X, padx=12, pady=(12, 4))
    tk.Label(top_row, textvariable=hint, anchor="w").pack(
        side=tk.LEFT, fill=tk.X, expand=True
    )
    confirm_btn = tk.Button(top_row, text="确认本框")
    confirm_btn.pack(side=tk.LEFT, padx=(8, 0))

    # 视口高度受屏幕限制，内容超出时右侧显示滚动条
    view_h = min(disp_h, max(200, parent.winfo_screenheight() - 260))

    canvas_frame = tk.Frame(dialog)
    canvas_frame.pack(padx=12, pady=4, fill=tk.BOTH, expand=True)

    canvas = tk.Canvas(
        canvas_frame,
        width=disp_w,
        height=view_h,
        highlightthickness=1,
        cursor="crosshair",
        scrollregion=(0, 0, disp_w, disp_h),
    )
    vbar = tk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=canvas.yview)
    canvas.configure(yscrollcommand=vbar.set)
    vbar.pack(side=tk.RIGHT, fill=tk.Y)
    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    photo = ImageTk.PhotoImage(display, master=dialog)
    canvas.create_image(0, 0, anchor="nw", image=photo)
    canvas.image = photo  # type: ignore[attr-defined]

    def on_mousewheel(event: tk.Event) -> None:
        canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    canvas.bind("<MouseWheel>", on_mousewheel)

    state: dict = {
        "step": 1,
        "confirmed_count": 0,
        "boxes_disp": [],
        "drag_start": None,
        "temp_id": None,
        "box_ids": [],
        "result": None,
    }

    def canvas_to_orig(box: PosterBox) -> PosterBox:
        l, t, r, b = box
        return (
            max(0, min(orig_w, int(round(l / scale)))),
            max(0, min(orig_h, int(round(t / scale)))),
            max(0, min(orig_w, int(round(r / scale)))),
            max(0, min(orig_h, int(round(b / scale)))),
        )

    def box_color(step: int) -> str:
        return _MULTI_BOX_COLORS[(step - 1) % len(_MULTI_BOX_COLORS)]

    def event_xy(event: tk.Event) -> tuple[int, int]:
        return int(canvas.canvasx(event.x)), int(canvas.canvasy(event.y))

    def on_press(event: tk.Event) -> None:
        state["drag_start"] = event_xy(event)
        if state["temp_id"] is not None:
            canvas.delete(state["temp_id"])
            state["temp_id"] = None

    def on_drag(event: tk.Event) -> None:
        start = state["drag_start"]
        if start is None:
            return
        x0, y0 = start
        ex, ey = event_xy(event)
        if state["temp_id"] is not None:
            canvas.delete(state["temp_id"])
        state["temp_id"] = canvas.create_rectangle(
            x0, y0, ex, ey, outline="#e53935", width=2
        )

    def on_release(event: tk.Event) -> None:
        start = state["drag_start"]
        if start is None:
            return
        x0, y0 = start
        state["drag_start"] = None
        ex, ey = event_xy(event)
        box = normalize_poster_box(x0, y0, ex, ey)
        if box[2] - box[0] < 4 or box[3] - box[1] < 4:
            if state["temp_id"] is not None:
                canvas.delete(state["temp_id"])
                state["temp_id"] = None
            return
        if state["temp_id"] is not None:
            canvas.delete(state["temp_id"])
            state["temp_id"] = None
        while len(state["boxes_disp"]) >= state["step"]:
            state["boxes_disp"].pop()
            if state["box_ids"]:
                canvas.delete(state["box_ids"].pop())
        rid = canvas.create_rectangle(*box, outline=box_color(state["step"]), width=2)
        state["boxes_disp"].append(box)
        state["box_ids"].append(rid)

    def confirm_box() -> None:
        if len(state["boxes_disp"]) < state["step"]:
            messagebox.showwarning(
                "框选海报多个位置",
                f"请先框选位置 {state['step']}。",
                parent=dialog,
            )
            return
        state["confirmed_count"] += 1
        state["step"] += 1
        hint.set(
            f"请拖拽框选位置 {state['step']}，完成后点击「确认本框」；"
            f"或点击「完成框选」（已确认 {state['confirmed_count']} 处）"
        )

    def finish_boxes() -> None:
        if state["confirmed_count"] < 2:
            messagebox.showwarning(
                "框选海报多个位置",
                "至少须框选并确认 2 处位置。",
                parent=dialog,
            )
            return
        boxes_orig: list[PosterBox] = []
        for i, box in enumerate(state["boxes_disp"][: state["confirmed_count"]], 1):
            mapped = canvas_to_orig(box)
            if mapped[2] - mapped[0] < 2 or mapped[3] - mapped[1] < 2:
                messagebox.showwarning(
                    "框选海报多个位置",
                    f"位置 {i} 映射后过小，请重新框选。",
                    parent=dialog,
                )
                return
            boxes_orig.append(mapped)
        state["result"] = boxes_orig
        dialog.destroy()

    def undo_current() -> None:
        if state["temp_id"] is not None:
            canvas.delete(state["temp_id"])
            state["temp_id"] = None
            return
        if len(state["boxes_disp"]) >= state["step"] and state["box_ids"]:
            canvas.delete(state["box_ids"].pop())
            state["boxes_disp"].pop()
        elif state["confirmed_count"] > 0:
            state["confirmed_count"] -= 1
            state["step"] -= 1
            if state["box_ids"]:
                canvas.delete(state["box_ids"].pop())
            state["boxes_disp"].pop()
            hint.set(
                f"请拖拽框选位置 {state['step']}，完成后点击「确认本框」；"
                f"或点击「完成框选」（已确认 {state['confirmed_count']} 处）"
            )

    def on_cancel() -> None:
        state["result"] = None
        dialog.destroy()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)

    confirm_btn.configure(command=confirm_box)

    btn_row = tk.Frame(dialog)
    btn_row.pack(fill=tk.X, padx=12, pady=(8, 12))
    tk.Button(btn_row, text="撤销当前框", command=undo_current).pack(side=tk.LEFT)
    tk.Button(btn_row, text="完成框选", command=finish_boxes).pack(side=tk.LEFT, padx=(8, 0))
    tk.Button(btn_row, text="取消", command=on_cancel).pack(side=tk.RIGHT)

    dialog.protocol("WM_DELETE_WINDOW", on_cancel)
    parent.wait_window(dialog)
    return state["result"]


class ProcessTab(tk.Frame):
    def __init__(self, notebook: tk.Widget, app) -> None:
        super().__init__(notebook)
        self.app = app
        _add_tool_row(
            self,
            "转为 JPG…",
            self.on_convert_to_jpg,
            "选择图片和输出文件夹，将图片转换为 JPG（透明背景填充白色），并在报告区显示每张的转换结果。",
        )
        _add_tool_row(
            self,
            "调整亮度…",
            self.on_adjust_brightness,
            "选择图片和输出文件夹，按倍数（0.01~10，1.0 不变）调整亮度后保存，保留原格式。",
        )
        _add_tool_row(
            self,
            "海报双图贴入…",
            self.on_poster_compose,
            "选择海报并框选两个位置；主图（1、2、3…）贴入位置1，副图（1-1、2-2…）贴入位置2；"
            "按组生成新海报，保存在原海报同目录（命名为 poster_x.png，x 为该组第一张图的文件名）。",
        )
        _add_tool_row(
            self,
            "单图多次贴入…",
            self.on_poster_single_multi,
            "选择海报并框选多处位置；每张图（1、2、3…）贴入全部位置，各生成一张海报，"
            "保存在原海报同目录（命名为 poster_x.png，x 为该图文件名）。",
        )
        _add_tool_row(
            self,
            "组合贴入…",
            self.on_poster_combined,
            "选择海报后先框选双图两处位置，再框选多处位置（至少 2 处）；"
            "主图（1、2、3…）贴入位置1及全部多选位置，副图（1-1、2-2…）贴入位置2；"
            "每组生成一张海报，保存在原海报同目录（命名为 poster_x.png，x 为主图文件名）。",
        )

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
        self.app.text.delete("1.0", tk.END)
        self.app.text.insert(tk.END, report)
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
        self.app.text.delete("1.0", tk.END)
        self.app.text.insert(tk.END, report)
        messagebox.showinfo("调整亮度", f"完成：成功 {ok} 张，失败 {fail} 张。")

    def on_poster_compose(self) -> None:
        poster_path = filedialog.askopenfilename(
            title="选择海报模板",
            filetypes=IMAGE_FILETYPES,
        )
        if not poster_path:
            return
        regions = ask_poster_regions(self.app, poster_path)
        if regions is None:
            return
        box1, box2 = regions

        use_dir = messagebox.askyesno(
            "海报双图贴入",
            "是否从文件夹选择图片？\n「是」=选文件夹，「否」=多选文件。",
        )
        if use_dir:
            image_dir = filedialog.askdirectory(title="选择图片文件夹")
            if not image_dir:
                return
            paths = list_images_in_dir(image_dir)
        else:
            paths = list(
                filedialog.askopenfilenames(
                    title="选择要贴入的图片（主图 1/2/3… 与副图 1-1/2-2…）",
                    filetypes=IMAGE_FILETYPES,
                )
            )
            if not paths:
                return

        pairs = upload_pairs(paths)
        if isinstance(pairs, str):
            messagebox.showerror("海报双图贴入", pairs)
            return
        incomplete = [i for i, p in enumerate(pairs, start=1) if len(p) < 2]
        if incomplete:
            messagebox.showerror(
                "海报双图贴入",
                f"存在不完整的组（第 {incomplete[0]} 组等），每组须恰好 2 张图。",
            )
            return
        if not pairs:
            messagebox.showerror("海报双图贴入", "未找到可配对的图片。")
            return

        report, ok, fail = build_poster_compose_report(
            poster_path, pairs, box1, box2
        )
        self.app.text.delete("1.0", tk.END)
        self.app.text.insert(tk.END, report)
        messagebox.showinfo(
            "海报双图贴入", f"完成：成功 {ok} 组，失败 {fail} 组。"
        )

    def on_poster_combined(self) -> None:
        poster_path = filedialog.askopenfilename(
            title="选择海报模板",
            filetypes=IMAGE_FILETYPES,
        )
        if not poster_path:
            return
        regions = ask_poster_regions(self.app, poster_path)
        if regions is None:
            return
        box1, box2 = regions
        multi_boxes = ask_poster_regions_multi(self.app, poster_path)
        if multi_boxes is None:
            return

        use_dir = messagebox.askyesno(
            "组合贴入",
            "是否从文件夹选择图片？\n「是」=选文件夹，「否」=多选文件。",
        )
        if use_dir:
            image_dir = filedialog.askdirectory(title="选择图片文件夹")
            if not image_dir:
                return
            paths = list_images_in_dir(image_dir)
        else:
            paths = list(
                filedialog.askopenfilenames(
                    title="选择要贴入的图片（主图 1/2/3… 与副图 1-1/2-2…）",
                    filetypes=IMAGE_FILETYPES,
                )
            )
            if not paths:
                return

        pairs = upload_pairs(paths)
        if isinstance(pairs, str):
            messagebox.showerror("组合贴入", pairs)
            return
        incomplete = [i for i, p in enumerate(pairs, start=1) if len(p) < 2]
        if incomplete:
            messagebox.showerror(
                "组合贴入",
                f"存在不完整的组（第 {incomplete[0]} 组等），每组须恰好 2 张图。",
            )
            return
        if not pairs:
            messagebox.showerror("组合贴入", "未找到可配对的图片。")
            return

        report, ok, fail = build_poster_combined_report(
            poster_path, pairs, box1, box2, multi_boxes
        )
        self.app.text.delete("1.0", tk.END)
        self.app.text.insert(tk.END, report)
        messagebox.showinfo(
            "组合贴入", f"完成：成功 {ok} 组，失败 {fail} 组。"
        )

    def on_poster_single_multi(self) -> None:
        poster_path = filedialog.askopenfilename(
            title="选择海报模板",
            filetypes=IMAGE_FILETYPES,
        )
        if not poster_path:
            return
        boxes = ask_poster_regions_multi(self.app, poster_path)
        if boxes is None:
            return

        use_dir = messagebox.askyesno(
            "单图多次贴入",
            "是否从文件夹选择图片？\n「是」=选文件夹，「否」=多选文件。",
        )
        if use_dir:
            image_dir = filedialog.askdirectory(title="选择图片文件夹")
            if not image_dir:
                return
            paths = list_images_in_dir(image_dir)
        else:
            paths = list(
                filedialog.askopenfilenames(
                    title="选择要贴入的图片（1、2、3…）",
                    filetypes=IMAGE_FILETYPES,
                )
            )
            if not paths:
                return

        image_paths = sorted_main_image_paths(paths)
        if not image_paths:
            messagebox.showerror(
                "单图多次贴入",
                "未找到有效图片。文件名须为纯数字（1、2、3…）。",
            )
            return

        report, ok, fail = build_poster_single_multi_report(
            poster_path, image_paths, boxes
        )
        self.app.text.delete("1.0", tk.END)
        self.app.text.insert(tk.END, report)
        messagebox.showinfo(
            "单图多次贴入", f"完成：成功 {ok} 张，失败 {fail} 张。"
        )
