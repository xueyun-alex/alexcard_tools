"""Tab5 闲管家上线：打开闲管家、批量上线。"""

import json
import os
import tkinter as tk
from dataclasses import dataclass
from typing import Literal
from tkinter import filedialog, messagebox

from gemini_copy import (
    BATCH_SEPARATOR,
    BATCH_TXT_NAME,
    ParsedCopy,
    parse_gemini_copy,
)
from xianguanjia import (
    BatchPublishJob,
    PublishJobItem,
    PublishSpec,
    get_xianguanjia_session,
)

from .common import (
    IMAGE_FILETYPES,
    PROJECT_ROOT,
    TEXT_FILETYPES,
    ScrollableTab,
    _add_tool_row,
    _image_stem,
    _is_main_image_stem,
    list_images_in_dir,
    upload_pairs,
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


BATCH_PUBLISH_DRAFT_NAME = ".batch_publish_last.json"


def batch_publish_draft_path() -> str:
    return os.path.join(PROJECT_ROOT, BATCH_PUBLISH_DRAFT_NAME)


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


class XianguanjiaTab(ScrollableTab):
    def __init__(self, notebook: tk.Widget, app) -> None:
        super().__init__(notebook)
        self.app = app
        self._busy = False
        self._session = get_xianguanjia_session()
        _add_tool_row(
            self.body,
            "打开闲管家",
            self.on_open_xianguanjia,
            "打开闲管家登录页，请在弹出浏览器中登录；登录后勿关浏览器。",
        )
        _add_tool_row(
            self.body,
            "批量上线…",
            self.on_batch_publish,
            "填写分类/商品规格/规格名称/运费，选择图片文件夹与文案 txt；"
            "需先打开闲管家并登录，手动进入第一件「新建商品」发布页后再开始自动填表。",
        )

    def close(self) -> None:
        try:
            self._session.submit_close()
        except Exception:
            pass

    def on_open_xianguanjia(self) -> None:
        if self._busy:
            messagebox.showinfo("打开闲管家", "正在处理中，请稍候。")
            return
        self._busy = True
        self.app.append_report_line("正在打开闲管家…")

        def on_progress(line: str) -> None:
            self.app.after(0, lambda l=line: self.app.append_report_line(l))

        def on_done() -> None:
            def finish() -> None:
                self._busy = False
                messagebox.showinfo(
                    "打开闲管家",
                    "浏览器已打开。请登录闲管家账号；登录后勿关窗口（后续上架功能会复用该会话）。",
                )

            self.app.after(0, finish)

        def on_error(msg: str) -> None:
            def fail_ui() -> None:
                self._busy = False
                self.app.append_report_line(f"错误: {msg}")
                messagebox.showerror("打开闲管家", msg)

            self.app.after(0, fail_ui)

        self._session.submit_open(
            on_progress=on_progress, on_done=on_done, on_error=on_error
        )

    def on_batch_publish(self) -> None:
        if self._busy:
            messagebox.showinfo("批量上线", "正在处理中，请稍候。")
            return
        params = ask_batch_publish_dialog(self.app)
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
            self.app.append_report_line(line)

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

        self._busy = True

        def on_progress(line: str) -> None:
            self.app.after(0, lambda l=line: self.app.append_report_line(l))

        def on_done(ok: int, fail: int) -> None:
            def finish() -> None:
                self._busy = False
                self.app.append_report_line(f"批量上线结束：成功 {ok}，失败/中止 {fail}。")
                messagebox.showinfo(
                    "批量上线",
                    f"完成：成功 {ok} 件，失败/中止 {fail} 件。",
                )

            self.app.after(0, finish)

        def on_error(msg: str) -> None:
            def fail_ui() -> None:
                self._busy = False
                self.app.append_report_line(f"错误: {msg}")
                messagebox.showerror("批量上线", msg)

            self.app.after(0, fail_ui)

        self._session.submit_batch_publish(
            job,
            on_progress=on_progress,
            on_done=on_done,
            on_error=on_error,
        )
