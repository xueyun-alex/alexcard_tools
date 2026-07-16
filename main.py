import json
import os
import shutil
import sys
import tkinter as tk
from dataclasses import dataclass
from typing import Callable, Iterable, Literal
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk

from PIL import Image, ImageEnhance, ImageTk

from gemini_copy import (
    BATCH_SEPARATOR,
    BATCH_TXT_NAME,
    GEMINI_STYLE_PROMPT,
    ParsedCopy,
    get_gemini_session,
    parse_gemini_copy,
)
from xianguanjia import (
    BatchPublishJob,
    PublishJobItem,
    PublishSpec,
    get_xianguanjia_session,
)


@dataclass(frozen=True)
class SpecPrice:
    name: str
    price: str


@dataclass(frozen=True)
class BatchPublishParams:
    category: str
    spec_attr: str
    specs: list[SpecPrice]
    shipping: str
    desc_suffix: str
    image_dir: str
    image_paths: list[str]
    copy_txt: str
    images_per_item: Literal[1, 2] = 2


@dataclass(frozen=True)
class PublishItem:
    images: tuple[str, ...]
    title: str
    description: str


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

TEXT_FILETYPES = [
    ("文本文件", "*.txt"),
    ("所有文件", "*.*"),
]

IMAGE_EXTENSIONS = frozenset(
    {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
)

BATCH_PUBLISH_DRAFT_NAME = ".batch_publish_last.json"


def batch_publish_draft_path() -> str:
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)), BATCH_PUBLISH_DRAFT_NAME
    )


def load_batch_publish_draft() -> dict[str, str]:
    path = batch_publish_draft_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return {str(k): str(v) for k, v in data.items() if v is not None}
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}


def save_batch_publish_draft(fields: dict[str, str]) -> None:
    path = batch_publish_draft_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(fields, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


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


def parse_spec_prices(raw: str) -> list[SpecPrice] | str:
    """
    解析「裸卡：16.90；挂件袋：23.90」形式。
    成功返回 SpecPrice 列表；失败返回错误说明字符串。
    兼容中英文冒号/分号。
    """
    text = raw.strip()
    if not text:
        return "请填写规格名称。"
    normalized = text.replace("；", ";").replace("：", ":")
    items: list[SpecPrice] = []
    for part in normalized.split(";"):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            return f"规格项格式错误（缺少冒号）：{part}"
        name, price = part.split(":", 1)
        name = name.strip()
        price = price.strip()
        if not name:
            return f"规格名称不能为空：{part}"
        if not price:
            return f"价格不能为空：{part}"
        try:
            float(price)
        except ValueError:
            return f"价格不是有效数字：{price}"
        items.append(SpecPrice(name=name, price=price))
    if not items:
        return "规格名称无效（请用 ； 分隔「名称：价格」）。"
    return items


def format_spec_prices(specs: list[SpecPrice]) -> str:
    return "；".join(f"{s.name}：{s.price}" for s in specs)


def split_batch_copies(txt_path: str) -> list[ParsedCopy] | str:
    """
    按 ======= 切分文案文件，每段 parse_gemini_copy。
    成功返回 ParsedCopy 列表；失败返回错误说明。
    """
    try:
        with open(txt_path, encoding="utf-8") as f:
            raw = f.read()
    except OSError as e:
        return f"无法读取文案文件：{e}"
    text = raw.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return "文案文件为空。"
    parts = [p.strip() for p in text.split(BATCH_SEPARATOR) if p.strip()]
    if not parts:
        return "文案文件中没有有效条目。"
    copies: list[ParsedCopy] = []
    for i, part in enumerate(parts, start=1):
        try:
            copies.append(parse_gemini_copy(part))
        except ValueError as e:
            return f"第 {i} 条文案解析失败：{e}"
    return copies


def build_listing_description(
    description: str, tags: str, desc_suffix: str = ""
) -> str:
    """宝贝描述、标签、结尾补充之间各空一行。"""
    parts = [description.strip(), tags.strip()]
    suffix = desc_suffix.strip()
    if suffix:
        parts.append(suffix)
    return "\n\n".join(p for p in parts if p)


def _numeric_then_name_key(path: str) -> tuple:
    """纯数字文件名按数值排序（1、2、10），其余按文件名。"""
    stem = _image_stem(path)
    if _is_main_image_stem(stem):
        return (0, int(stem), os.path.basename(path).lower())
    return (1, 0, os.path.basename(path).lower())


def prepare_publish_items(params: BatchPublishParams) -> list[PublishItem] | str:
    """配对图片组与文案；数量不一致则返回错误说明。"""
    copies = split_batch_copies(params.copy_txt)
    if isinstance(copies, str):
        return copies
    if params.images_per_item == 1:
        ordered = sorted(params.image_paths, key=_numeric_then_name_key)
        pairs: list[tuple[str, ...]] = [(p,) for p in ordered]
    else:
        result = upload_pairs(params.image_paths)
        if isinstance(result, str):
            return result
        pairs = result
    if len(pairs) != len(copies):
        return (
            f"图片组数（{len(pairs)}）与文案条数（{len(copies)}）不一致，"
            "请检查图片目录与文案文件。"
        )
    items: list[PublishItem] = []
    for pair, copy in zip(pairs, copies):
        items.append(
            PublishItem(
                images=pair,
                title=copy.title.strip(),
                description=build_listing_description(
                    copy.description, copy.tags, params.desc_suffix
                ),
            )
        )
    return items


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

    canvas = tk.Canvas(
        dialog, width=disp_w, height=disp_h, highlightthickness=1, cursor="crosshair"
    )
    canvas.pack(padx=12, pady=4)

    photo = ImageTk.PhotoImage(display, master=dialog)
    canvas.create_image(0, 0, anchor="nw", image=photo)
    canvas.image = photo  # type: ignore[attr-defined]

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

    def on_press(event: tk.Event) -> None:
        if state["step"] > 2:
            return
        state["drag_start"] = (event.x, event.y)
        if state["temp_id"] is not None:
            canvas.delete(state["temp_id"])
            state["temp_id"] = None

    def on_drag(event: tk.Event) -> None:
        start = state["drag_start"]
        if start is None:
            return
        x0, y0 = start
        if state["temp_id"] is not None:
            canvas.delete(state["temp_id"])
        state["temp_id"] = canvas.create_rectangle(
            x0, y0, event.x, event.y, outline="#e53935", width=2
        )

    def on_release(event: tk.Event) -> None:
        start = state["drag_start"]
        if start is None:
            return
        x0, y0 = start
        state["drag_start"] = None
        box = normalize_poster_box(x0, y0, event.x, event.y)
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

    canvas = tk.Canvas(
        dialog, width=disp_w, height=disp_h, highlightthickness=1, cursor="crosshair"
    )
    canvas.pack(padx=12, pady=4)

    photo = ImageTk.PhotoImage(display, master=dialog)
    canvas.create_image(0, 0, anchor="nw", image=photo)
    canvas.image = photo  # type: ignore[attr-defined]

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

    def on_press(event: tk.Event) -> None:
        state["drag_start"] = (event.x, event.y)
        if state["temp_id"] is not None:
            canvas.delete(state["temp_id"])
            state["temp_id"] = None

    def on_drag(event: tk.Event) -> None:
        start = state["drag_start"]
        if start is None:
            return
        x0, y0 = start
        if state["temp_id"] is not None:
            canvas.delete(state["temp_id"])
        state["temp_id"] = canvas.create_rectangle(
            x0, y0, event.x, event.y, outline="#e53935", width=2
        )

    def on_release(event: tk.Event) -> None:
        start = state["drag_start"]
        if start is None:
            return
        x0, y0 = start
        state["drag_start"] = None
        box = normalize_poster_box(x0, y0, event.x, event.y)
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
            self.iconbitmap(resource_path("draw.ico"))
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
        _add_tool_row(
            tab_process,
            "海报双图贴入…",
            self.on_poster_compose,
            "选择海报并框选两个位置；主图（1、2、3…）贴入位置1，副图（1-1、2-2…）贴入位置2；"
            "按组生成新海报，保存在原海报同目录（命名为 poster_x.png，x 为该组第一张图的文件名）。",
        )
        _add_tool_row(
            tab_process,
            "单图多次贴入…",
            self.on_poster_single_multi,
            "选择海报并框选多处位置；每张图（1、2、3…）贴入全部位置，各生成一张海报，"
            "保存在原海报同目录（命名为 poster_x.png，x 为该图文件名）。",
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

        tab_xg = tk.Frame(notebook)
        notebook.add(tab_xg, text="闲管家上线")
        _add_tool_row(
            tab_xg,
            "打开闲管家",
            self.on_open_xianguanjia,
            "打开闲管家登录页，请在弹出浏览器中登录；登录后勿关浏览器。",
        )
        _add_tool_row(
            tab_xg,
            "批量上线…",
            self.on_batch_publish,
            "填写分类/商品规格/规格名称/运费，选择图片文件夹与文案 txt；"
            "需先打开闲管家并登录，手动进入第一件「新建商品」发布页后再开始自动填表。",
        )

        self._gemini_busy = False
        self._gemini_session = get_gemini_session()
        self._xg_busy = False
        self._xg_session = get_xianguanjia_session()
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

    def on_poster_compose(self) -> None:
        poster_path = filedialog.askopenfilename(
            title="选择海报模板",
            filetypes=IMAGE_FILETYPES,
        )
        if not poster_path:
            return
        regions = ask_poster_regions(self, poster_path)
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
        self.text.delete("1.0", tk.END)
        self.text.insert(tk.END, report)
        messagebox.showinfo(
            "海报双图贴入", f"完成：成功 {ok} 组，失败 {fail} 组。"
        )

    def on_poster_single_multi(self) -> None:
        poster_path = filedialog.askopenfilename(
            title="选择海报模板",
            filetypes=IMAGE_FILETYPES,
        )
        if not poster_path:
            return
        boxes = ask_poster_regions_multi(self, poster_path)
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
        self.text.delete("1.0", tk.END)
        self.text.insert(tk.END, report)
        messagebox.showinfo(
            "单图多次贴入", f"完成：成功 {ok} 张，失败 {fail} 张。"
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
        try:
            self._xg_session.submit_close()
        except Exception:
            pass
        self.destroy()

    def on_open_xianguanjia(self) -> None:
        if self._xg_busy:
            messagebox.showinfo("打开闲管家", "正在处理中，请稍候。")
            return
        self._xg_busy = True
        self._append_report_line("正在打开闲管家…")

        def on_progress(line: str) -> None:
            self.after(0, lambda l=line: self._append_report_line(l))

        def on_done() -> None:
            def finish() -> None:
                self._xg_busy = False
                messagebox.showinfo(
                    "打开闲管家",
                    "浏览器已打开。请登录闲管家账号；登录后勿关窗口（后续上架功能会复用该会话）。",
                )

            self.after(0, finish)

        def on_error(msg: str) -> None:
            def fail_ui() -> None:
                self._xg_busy = False
                self._append_report_line(f"错误: {msg}")
                messagebox.showerror("打开闲管家", msg)

            self.after(0, fail_ui)

        self._xg_session.submit_open(
            on_progress=on_progress, on_done=on_done, on_error=on_error
        )

    def on_batch_publish(self) -> None:
        if self._xg_busy:
            messagebox.showinfo("批量上线", "正在处理中，请稍候。")
            return
        params = ask_batch_publish_dialog(self)
        if params is None:
            return
        items = prepare_publish_items(params)
        if isinstance(items, str):
            messagebox.showerror("批量上线", items)
            return

        n = len(params.image_paths)
        pair_count = len(items)
        lines = [
            "—— 批量上线 ——",
            f"商品分类：{params.category}",
            f"商品规格：{params.spec_attr}",
            f"规格名称：{format_spec_prices(params.specs)}",
            f"运费：{params.shipping}",
            f"商品描述结尾补充：{params.desc_suffix or '（无）'}",
            f"图片目录：{params.image_dir}（{n} 张，共 {pair_count} 组；"
            f"{'一张图' if params.images_per_item == 1 else '主图+副图'}）",
            f"文案：{params.copy_txt}",
            "请确认浏览器已打开第一件发布页，开始自动填表…",
        ]
        for line in lines:
            self._append_report_line(line)

        job = BatchPublishJob(
            category=params.category,
            spec_attr=params.spec_attr,
            specs=[PublishSpec(name=s.name, price=s.price) for s in params.specs],
            shipping=params.shipping,
            items=[
                PublishJobItem(
                    images=it.images,
                    title=it.title,
                    description=it.description,
                )
                for it in items
            ],
        )

        self._xg_busy = True

        def on_progress(line: str) -> None:
            self.after(0, lambda l=line: self._append_report_line(l))

        def on_done(ok: int, fail: int) -> None:
            def finish() -> None:
                self._xg_busy = False
                self._append_report_line(f"批量上线结束：成功 {ok}，失败/中止 {fail}。")
                messagebox.showinfo(
                    "批量上线",
                    f"完成：成功 {ok} 件，失败/中止 {fail} 件。",
                )

            self.after(0, finish)

        def on_error(msg: str) -> None:
            def fail_ui() -> None:
                self._xg_busy = False
                self._append_report_line(f"错误: {msg}")
                messagebox.showerror("批量上线", msg)

            self.after(0, fail_ui)

        self._xg_session.submit_batch_publish(
            job,
            on_progress=on_progress,
            on_done=on_done,
            on_error=on_error,
        )

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


def ask_batch_publish_dialog(parent: tk.Tk) -> BatchPublishParams | None:
    """分类 / 商品规格 / 规格名称 / 运费 / 描述结尾补充 + 图片目录 + 文案 txt。确定返回 BatchPublishParams，取消返回 None。"""
    dlg = tk.Toplevel(parent)
    dlg.title("批量上线")
    dlg.transient(parent)
    dlg.grab_set()
    dlg.minsize(520, 460)
    dlg.geometry("600x500")

    result: dict[str, object] = {"ok": False}

    form = tk.Frame(dlg)
    form.pack(fill=tk.X, padx=12, pady=(12, 4))

    tk.Label(form, text="商品分类：", anchor="w").grid(row=0, column=0, sticky="w", pady=4)
    category_entry = tk.Entry(form)
    category_entry.grid(row=0, column=1, sticky="ew", pady=4, padx=(8, 0))

    tk.Label(form, text="商品规格：", anchor="w").grid(row=1, column=0, sticky="w", pady=4)
    spec_attr_entry = tk.Entry(form)
    spec_attr_entry.grid(row=1, column=1, sticky="ew", pady=4, padx=(8, 0))
    tk.Label(
        form,
        text="属性名，如 品相",
        anchor="w",
        fg="#666666",
    ).grid(row=2, column=1, sticky="w", padx=(8, 0))

    tk.Label(form, text="规格名称：", anchor="w").grid(row=3, column=0, sticky="w", pady=4)
    specs_entry = tk.Entry(form)
    specs_entry.grid(row=3, column=1, sticky="ew", pady=4, padx=(8, 0))
    tk.Label(
        form,
        text="名称：价格；多个用 ； 分隔，如 裸卡：16.90；挂件袋：23.90",
        anchor="w",
        fg="#666666",
    ).grid(row=4, column=1, sticky="w", padx=(8, 0))

    tk.Label(form, text="运费：", anchor="w").grid(row=5, column=0, sticky="w", pady=4)
    shipping_entry = tk.Entry(form)
    shipping_entry.grid(row=5, column=1, sticky="ew", pady=4, padx=(8, 0))

    tk.Label(form, text="商品描述结尾补充：", anchor="w").grid(
        row=6, column=0, sticky="w", pady=4
    )
    desc_suffix_entry = tk.Entry(form)
    desc_suffix_entry.grid(row=6, column=1, sticky="ew", pady=4, padx=(8, 0))
    tk.Label(
        form,
        text="可选，追加到每条宝贝描述末尾",
        anchor="w",
        fg="#666666",
    ).grid(row=7, column=1, sticky="w", padx=(8, 0))

    tk.Label(form, text="图片目录：", anchor="w").grid(row=8, column=0, sticky="w", pady=4)
    dir_row = tk.Frame(form)
    dir_row.grid(row=8, column=1, sticky="ew", pady=4, padx=(8, 0))
    dir_entry = tk.Entry(dir_row)
    dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

    tk.Label(form, text="每件图片数：", anchor="w").grid(
        row=9, column=0, sticky="w", pady=4
    )
    images_per_item_var = tk.IntVar(value=2)
    mode_row = tk.Frame(form)
    mode_row.grid(row=9, column=1, sticky="w", pady=4, padx=(8, 0))
    tk.Radiobutton(
        mode_row,
        text="两张图（主图+副图）",
        variable=images_per_item_var,
        value=2,
    ).pack(side=tk.LEFT)
    tk.Radiobutton(
        mode_row,
        text="一张图",
        variable=images_per_item_var,
        value=1,
    ).pack(side=tk.LEFT, padx=(12, 0))

    HINT_TWO = "文件名 1、2、3… 为主图（每组第一张）；其余图按名排序与主图一一配对"
    HINT_ONE = "纯数字文件名按 1、2、3… 数值顺序，每张图对应一件商品"
    image_hint = tk.Label(form, text=HINT_TWO, anchor="w", fg="#666666")
    image_hint.grid(row=10, column=1, sticky="w", padx=(8, 0))

    def on_images_per_item_changed(*_args: object) -> None:
        image_hint.config(
            text=HINT_ONE if images_per_item_var.get() == 1 else HINT_TWO
        )

    images_per_item_var.trace_add("write", on_images_per_item_changed)

    tk.Label(form, text="文案文件：", anchor="w").grid(
        row=11, column=0, sticky="w", pady=4
    )
    txt_row = tk.Frame(form)
    txt_row.grid(row=11, column=1, sticky="ew", pady=4, padx=(8, 0))
    txt_entry = tk.Entry(txt_row)
    txt_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def on_browse_dir() -> None:
        chosen = filedialog.askdirectory(parent=dlg, title="选择图片文件夹")
        if not chosen:
            return
        dir_entry.delete(0, tk.END)
        dir_entry.insert(0, chosen)
        default_txt = os.path.join(os.path.abspath(chosen), BATCH_TXT_NAME)
        if os.path.isfile(default_txt) and not txt_entry.get().strip():
            txt_entry.delete(0, tk.END)
            txt_entry.insert(0, default_txt)

    def on_browse_txt() -> None:
        initial = dir_entry.get().strip() or None
        chosen = filedialog.askopenfilename(
            parent=dlg,
            title="选择文案 txt 文件",
            filetypes=TEXT_FILETYPES,
            initialdir=initial if initial and os.path.isdir(initial) else None,
        )
        if not chosen:
            return
        txt_entry.delete(0, tk.END)
        txt_entry.insert(0, chosen)

    tk.Button(dir_row, text="浏览…", command=on_browse_dir).pack(
        side=tk.LEFT, padx=(6, 0)
    )
    tk.Button(txt_row, text="浏览…", command=on_browse_txt).pack(
        side=tk.LEFT, padx=(6, 0)
    )

    form.columnconfigure(1, weight=1)

    draft = load_batch_publish_draft()

    def _prefill(entry: tk.Entry, key: str) -> None:
        val = draft.get(key, "").strip()
        if val:
            entry.insert(0, val)

    _prefill(category_entry, "category")
    _prefill(spec_attr_entry, "spec_attr")
    _prefill(specs_entry, "specs_raw")
    _prefill(shipping_entry, "shipping")
    _prefill(desc_suffix_entry, "desc_suffix")
    _prefill(dir_entry, "image_dir")
    _prefill(txt_entry, "copy_txt")
    draft_ipi = draft.get("images_per_item", "2").strip()
    if draft_ipi == "1":
        images_per_item_var.set(1)
    else:
        images_per_item_var.set(2)
    on_images_per_item_changed()

    def on_ok() -> None:
        category = category_entry.get().strip()
        spec_attr = spec_attr_entry.get().strip()
        specs_raw = specs_entry.get().strip()
        shipping = shipping_entry.get().strip()
        desc_suffix = desc_suffix_entry.get().strip()
        image_dir = dir_entry.get().strip()
        copy_txt = txt_entry.get().strip()
        images_per_item: Literal[1, 2] = 1 if images_per_item_var.get() == 1 else 2
        if not category:
            messagebox.showerror("批量上线", "请填写商品分类。", parent=dlg)
            return
        if not spec_attr:
            messagebox.showerror("批量上线", "请填写商品规格。", parent=dlg)
            return
        if not specs_raw:
            messagebox.showerror("批量上线", "请填写规格名称。", parent=dlg)
            return
        parsed = parse_spec_prices(specs_raw)
        if isinstance(parsed, str):
            messagebox.showerror("批量上线", parsed, parent=dlg)
            return
        specs = parsed
        if not shipping:
            messagebox.showerror("批量上线", "请填写运费。", parent=dlg)
            return
        if not image_dir:
            messagebox.showerror("批量上线", "请填写图片目录。", parent=dlg)
            return
        if not os.path.isdir(image_dir):
            messagebox.showerror("批量上线", "图片目录不存在。", parent=dlg)
            return
        image_paths = list_images_in_dir(image_dir)
        if not image_paths:
            messagebox.showerror(
                "批量上线", "该目录下未找到图片文件。", parent=dlg
            )
            return
        if not copy_txt:
            messagebox.showerror("批量上线", "请选择文案 txt 文件。", parent=dlg)
            return
        if not os.path.isfile(copy_txt):
            messagebox.showerror("批量上线", "文案 txt 文件不存在。", parent=dlg)
            return
        abs_dir = os.path.abspath(image_dir)
        abs_txt = os.path.abspath(copy_txt)
        save_batch_publish_draft(
            {
                "category": category,
                "spec_attr": spec_attr,
                "specs_raw": specs_raw,
                "shipping": shipping,
                "desc_suffix": desc_suffix,
                "image_dir": abs_dir,
                "copy_txt": abs_txt,
                "images_per_item": str(images_per_item),
            }
        )
        result["ok"] = True
        result["params"] = BatchPublishParams(
            category=category,
            spec_attr=spec_attr,
            specs=specs,
            shipping=shipping,
            desc_suffix=desc_suffix,
            image_dir=abs_dir,
            image_paths=image_paths,
            copy_txt=abs_txt,
            images_per_item=images_per_item,
        )
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
    category_entry.focus_set()
    parent.wait_window(dlg)

    if not result.get("ok"):
        return None
    return result["params"]  # type: ignore[return-value]


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
