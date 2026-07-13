"""闲管家：通过 Playwright 打开登录页，并批量自动填表上架。"""

from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable

from gemini_copy import (
    _is_missing_browser_error,
    _launch_persistent_context,
    app_dir,
    ensure_chromium_installed,
)

LOGIN_URL = "https://www.goofish.pro/login"
PROFILE_DIR_NAME = ".playwright-xianguanjia-profile"
TITLE_MAX_CHARS = 30
STOCK_DEFAULT = "999"

ProgressCallback = Callable[[str], None]
DoneCallback = Callable[[], None]
ErrorCallback = Callable[[str], None]
BatchPublishDoneCallback = Callable[[int, int], None]


@dataclass(frozen=True)
class PublishSpec:
    name: str
    price: str


@dataclass(frozen=True)
class PublishJobItem:
    images: tuple[str, ...]
    title: str
    description: str


@dataclass(frozen=True)
class BatchPublishJob:
    category: str
    spec_attr: str
    specs: list[PublishSpec]
    shipping: str
    items: list[PublishJobItem]


def profile_dir(base_dir: str | None = None) -> str:
    root = base_dir or app_dir()
    return os.path.join(root, PROFILE_DIR_NAME)


def _truncate_title(title: str) -> tuple[str, bool]:
    """按约 30 汉字截断标题；返回 (结果, 是否被截断)。"""
    text = title.strip()
    if len(text) <= TITLE_MAX_CHARS:
        return text, False
    return text[:TITLE_MAX_CHARS], True


class XianGuanjiaSession:
    """
    在专用后台线程中串行执行 open / batch_publish / close，保持同一 Playwright 上下文。
    主线程通过 submit_* 投递任务，用回调拿结果。
    """

    def __init__(self, profile_base: str | None = None, headless: bool = False) -> None:
        import queue

        self._profile_base = profile_base
        self._headless = headless
        self._q: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._playwright = None
        self._context = None
        self._page = None

    def start_worker(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="xianguanjia-pw"
        )
        self._thread.start()

    def submit_open(
        self,
        *,
        on_progress: ProgressCallback | None = None,
        on_done: DoneCallback | None = None,
        on_error: ErrorCallback | None = None,
    ) -> None:
        self.start_worker()
        self._q.put(("open", on_progress, on_done, on_error))

    def submit_batch_publish(
        self,
        job: BatchPublishJob,
        *,
        on_progress: ProgressCallback | None = None,
        on_done: BatchPublishDoneCallback | None = None,
        on_error: ErrorCallback | None = None,
    ) -> None:
        self.start_worker()
        self._q.put(("batch_publish", job, on_progress, on_done, on_error))

    def submit_close(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            return
        self._q.put(("close",))

    def _loop(self) -> None:
        while True:
            item = self._q.get()
            try:
                cmd = item[0]
                if cmd == "open":
                    _, on_progress, on_done, on_error = item
                    try:
                        self._do_open(on_progress)
                        if on_done:
                            on_done()
                    except Exception as e:
                        if on_error:
                            on_error(str(e))
                elif cmd == "batch_publish":
                    _, job, on_progress, on_done, on_error = item
                    try:
                        ok, fail = self._do_batch_publish(job, on_progress)
                        if on_done:
                            on_done(ok, fail)
                    except Exception as e:
                        if on_error:
                            on_error(str(e))
                elif cmd == "close":
                    self._do_close()
                    break
            finally:
                self._q.task_done()

    def _context_alive(self) -> bool:
        if self._context is None:
            return False
        try:
            pages = list(self._context.pages)
            if not pages:
                return False
            if self._page is not None:
                try:
                    _ = self._page.url
                    return True
                except Exception:
                    self._page = pages[-1]
                    return True
            self._page = pages[-1]
            return True
        except Exception:
            return False

    def _goto_login(self, page) -> None:
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60_000)

    def _do_open(self, on_progress: ProgressCallback | None) -> None:
        from playwright.sync_api import sync_playwright

        def emit(msg: str) -> None:
            if on_progress:
                on_progress(msg)

        ensure_chromium_installed(on_progress=emit)

        if self._context_alive():
            assert self._page is not None
            self._goto_login(self._page)
            try:
                self._page.bring_to_front()
            except Exception:
                pass
            emit("已打开闲管家登录页，请在浏览器中登录。")
            return

        self._do_close()
        user_data = profile_dir(self._profile_base)
        self._playwright = sync_playwright().start()
        try:
            self._context = _launch_persistent_context(
                self._playwright, user_data, self._headless
            )
        except Exception as e:
            if _is_missing_browser_error(e):
                emit("检测到 Chromium 缺失，正在重试安装…")
                ensure_chromium_installed(on_progress=emit)
                self._context = _launch_persistent_context(
                    self._playwright, user_data, self._headless
                )
            else:
                self._do_close()
                raise

        self._page = (
            self._context.pages[0] if self._context.pages else self._context.new_page()
        )
        self._goto_login(self._page)
        emit("已打开闲管家登录页，请在浏览器中登录。")

    def _do_close(self) -> None:
        if self._context is not None:
            try:
                self._context.close()
            except Exception:
                pass
        self._context = None
        self._page = None
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
        self._playwright = None

    def _publish_form_locator(self, page):
        return page.locator(
            'input[placeholder*="请输入商品标题"], '
            'input[placeholder*="请输入关键词"], '
            ".custom-cascader input.el-input__inner, "
            ".category-opt input.el-input__inner"
        )

    def _find_publish_page(self):
        """在所有标签页中找已打开的发布页（用户可能不在 session 记录的那一页）。"""
        assert self._context is not None
        pages = list(self._context.pages)
        # 后打开的标签优先
        for page in reversed(pages):
            try:
                if self._publish_form_locator(page).count() > 0:
                    return page
            except Exception:
                continue
        if self._page is not None:
            return self._page
        if pages:
            return pages[-1]
        raise RuntimeError("没有可用的浏览器页面。")

    def _do_batch_publish(
        self,
        job: BatchPublishJob,
        on_progress: ProgressCallback | None,
    ) -> tuple[int, int]:
        def emit(msg: str) -> None:
            if on_progress:
                on_progress(msg)

        if not self._context_alive():
            raise RuntimeError("请先点击「打开闲管家」并登录，再手动进入第一件的新建商品页。")

        page = self._find_publish_page()
        self._page = page
        try:
            page.bring_to_front()
        except Exception:
            pass
        emit(f"使用页面：{page.url}")

        total = len(job.items)
        ok = 0
        fail = 0
        for i, item in enumerate(job.items):
            n = i + 1
            emit(f"—— 上架 {n}/{total}：{item.title[:40]} ——")
            try:
                page = self._find_publish_page()
                self._page = page
                if i > 0:
                    self._click_new_product(page)
                    page = self._find_publish_page()
                    self._page = page
                self._fill_one_product(page, job, item, emit)
                self._submit_and_wait_list(page)
                ok += 1
                emit(f"上架成功 {n}/{total}")
            except Exception as e:
                fail += 1
                emit(f"上架失败 {n}/{total}：{e}")
                emit("已中止后续商品，避免错位配对。")
                break
        return ok, fail

    def _wait_publish_form(self, page, timeout: float = 60_000) -> None:
        self._publish_form_locator(page).first.wait_for(
            state="visible", timeout=timeout
        )

    def _click_new_product(self, page) -> None:
        btn = page.locator("button.newly-built, button:has-text('新建商品')").first
        btn.wait_for(state="visible", timeout=60_000)
        btn.click(timeout=10_000)
        self._wait_publish_form(page)

    def _fill_one_product(
        self,
        page,
        job: BatchPublishJob,
        item: PublishJobItem,
        emit: Callable[[str], None],
    ) -> None:
        self._wait_publish_form(page)
        self._fill_category(page, job.category)
        self._upload_images(page, item.images)
        title, truncated = _truncate_title(item.title)
        if truncated:
            emit(f"标题超长已截断至 {TITLE_MAX_CHARS} 字")
        self._fill_title(page, title)
        self._fill_description(page, item.description)
        self._setup_skus(page, job.spec_attr, job.specs)
        self._fill_shipping(page, job.shipping)
        self._select_draft(page)

    def _category_input(self, page):
        candidates = [
            ".custom-cascader.category-opt input.el-input__inner",
            ".custom-cascader input.el-input__inner",
            ".category-opt input.el-input__inner",
            'input[placeholder="请输入关键词"]',
            'input[placeholder*="请输入关键词"]',
        ]
        for sel in candidates:
            loc = page.locator(sel)
            if loc.count() > 0:
                return loc.first
        # 带「商品分类」文案的表单项
        labeled = page.locator("div, .el-form-item").filter(
            has_text=re.compile(r"商品分类")
        ).locator("input.el-input__inner")
        if labeled.count() > 0:
            return labeled.first
        return page.locator(
            ".custom-cascader.category-opt input.el-input__inner"
        ).first

    def _fill_category(self, page, category: str) -> None:
        inp = self._category_input(page)
        try:
            inp.wait_for(state="attached", timeout=15_000)
            inp.scroll_into_view_if_needed(timeout=5_000)
            inp.wait_for(state="visible", timeout=15_000)
        except Exception:
            # 有的页面临时不可见，仍尝试 force 操作
            inp.wait_for(state="attached", timeout=10_000)
        inp.click(timeout=5_000, force=True)
        time.sleep(0.2)
        try:
            inp.fill("")
            inp.fill(category)
        except Exception:
            inp.click(timeout=5_000, force=True)
            page.keyboard.type(category, delay=40)
        time.sleep(0.5)
        # Element cascader / select dropdown panels
        option = page.locator(
            ".el-cascader__suggestion-item, "
            ".el-select-dropdown__item, "
            ".el-cascader-node__label, "
            ".el-cascader-node, "
            "li.el-cascader__suggestion-item"
        ).filter(has_text=re.compile(re.escape(category)))
        try:
            option.first.wait_for(state="visible", timeout=8_000)
            option.first.click(timeout=5_000)
        except Exception:
            loose = page.locator(
                ".el-cascader__suggestion-item, "
                ".el-select-dropdown__item, "
                ".el-cascader-node"
            ).filter(has_text=category)
            if loose.count() > 0:
                loose.first.click(timeout=5_000)
            else:
                inp.press("Enter")
        time.sleep(0.4)

    def _upload_images(self, page, images: tuple[str, ...]) -> None:
        paths = [os.path.abspath(p) for p in images]
        for p in paths:
            if not os.path.isfile(p):
                raise FileNotFoundError(f"图片不存在：{p}")
        file_input = page.locator(
            ".upload-demo input.el-upload__input, "
            "input.el-upload__input[accept*='.jpg']"
        ).first
        file_input.wait_for(state="attached", timeout=30_000)
        file_input.set_input_files(paths)
        time.sleep(1.0)

    def _fill_title(self, page, title: str) -> None:
        inp = page.locator('input[placeholder*="请输入商品标题"]').first
        inp.wait_for(state="visible", timeout=15_000)
        inp.click(timeout=5_000)
        inp.fill(title)

    def _fill_description(self, page, description: str) -> None:
        area = page.locator(
            'textarea[placeholder="请输入商品描述"], '
            "textarea.el-textarea__inner"
        ).first
        area.wait_for(state="visible", timeout=15_000)
        area.click(timeout=5_000)
        area.fill(description)

    def _setup_skus(self, page, spec_attr: str, specs: list[PublishSpec]) -> None:
        add_btn = page.locator(".sku-add-btn").filter(has_text="添加多规格").first
        if add_btn.count() == 0:
            add_btn = page.locator("div.sku-add-btn, button:has-text('添加多规格')").first
        add_btn.click(timeout=10_000)

        # 规格属性名
        attr_input = page.locator(
            'input[placeholder*="商品规格1"], '
            'input[placeholder*="请输入，按"]'
        ).first
        attr_input.wait_for(state="visible", timeout=15_000)
        attr_input.click(timeout=5_000)
        attr_input.fill(spec_attr)

        add_attr_btn = page.locator(
            "button.el-button--primary:has-text('添加')"
        ).first
        add_attr_btn.click(timeout=5_000)
        time.sleep(0.3)

        # 规格值：逐个输入并回车
        value_input = page.locator(
            'input[placeholder*="请输入"], '
            'input[placeholder*="回车"]'
        ).last
        for spec in specs:
            value_input.wait_for(state="visible", timeout=10_000)
            value_input.click(timeout=5_000)
            value_input.fill(spec.name)
            value_input.press("Enter")
            time.sleep(0.25)

        confirm = page.locator(
            "button.el-button--primary:has-text('确认')"
        ).first
        confirm.click(timeout=10_000)
        time.sleep(0.6)

        self._fill_sku_prices_and_stock(page, specs)

    def _edit_inline_cell(self, cell, value: str) -> None:
        """
        闲管家 SKU 表：值默认显示在 p.value-icon，input 隐藏。
        先点编辑图标/单元格，再填可见 input，回车确认。
        """
        trigger = cell.locator("p.value-icon, span.bjbtn").first
        trigger.click(timeout=5_000)
        time.sleep(0.15)
        inp = cell.locator("input.el-input__inner").first
        inp.wait_for(state="visible", timeout=5_000)
        inp.click(timeout=3_000)
        inp.fill(value)
        inp.press("Enter")
        time.sleep(0.2)

    def _fill_sku_prices_and_stock(self, page, specs: list[PublishSpec]) -> None:
        """
        售价：td 内 p.value-icon.can-edit，按规格顺序填价格。
        库存：td 内 input[maxlength=10]，全部填 999。
        均需先点 .value-icon / .bjbtn 展开隐藏 input。
        """
        page.locator("p.value-icon.can-edit").first.wait_for(
            state="visible", timeout=15_000
        )

        price_cells = page.locator(".el-table__body td.el-table__cell").filter(
            has=page.locator("p.value-icon.can-edit")
        )
        n_price = price_cells.count()
        if n_price < len(specs):
            raise RuntimeError(
                f"SKU 售价单元格数（{n_price}）少于规格数（{len(specs)}）"
            )
        for i, spec in enumerate(specs):
            self._edit_inline_cell(price_cells.nth(i), spec.price)

        stock_cells = page.locator(".el-table__body td.el-table__cell").filter(
            has=page.locator('input.el-input__inner[maxlength="10"]')
        )
        n_stock = stock_cells.count()
        if n_stock < len(specs):
            raise RuntimeError(
                f"SKU 库存单元格数（{n_stock}）少于规格数（{len(specs)}）"
            )
        for i in range(len(specs)):
            self._edit_inline_cell(stock_cells.nth(i), STOCK_DEFAULT)

    def _fill_shipping(self, page, shipping: str) -> None:
        page.locator('label.el-radio:has-text("统一运费")').first.click(timeout=8_000)
        time.sleep(0.3)

        fee = str(shipping).strip()
        fee_input = page.locator(
            'input[placeholder*="运费"], input[placeholder*="邮费"]'
        )
        if fee_input.count() > 0:
            box = fee_input.first
            box.click(timeout=5_000)
            box.fill(fee)
            return

        near = page.locator("label.el-radio:has-text('统一运费')").locator(
            "xpath=ancestor::div[contains(@class,'el-form-item') or contains(@class,'flex') or contains(@class,'item')][1]"
        ).locator("input.el-input__inner")
        if near.count() > 0:
            near.first.click(timeout=5_000)
            near.first.fill(fee)
            return

        block = page.locator("div").filter(has_text=re.compile("统一运费")).locator(
            "input.el-input__inner"
        )
        if block.count() > 0:
            block.first.fill(fee)

    def _select_draft(self, page) -> None:
        label = page.locator('label.el-radio:has-text("放入待发布")').first
        label.wait_for(state="visible", timeout=15_000)
        label.click(timeout=5_000)

    def _submit_and_wait_list(self, page) -> None:
        btn = page.locator(
            "button:has-text('确定并新建')"
        ).first
        btn.wait_for(state="visible", timeout=15_000)
        btn.click(timeout=10_000)
        page.locator(
            "button.newly-built, button:has-text('新建商品')"
        ).first.wait_for(state="visible", timeout=90_000)


_default_session: XianGuanjiaSession | None = None


def get_xianguanjia_session() -> XianGuanjiaSession:
    global _default_session
    if _default_session is None:
        _default_session = XianGuanjiaSession()
    return _default_session
