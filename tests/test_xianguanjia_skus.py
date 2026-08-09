import unittest
from unittest.mock import Mock, call

from xianguanjia import PublishSpec, XianGuanjiaSession


def _locator(*, count=1):
    locator = Mock()
    locator.first = locator
    locator.last = locator
    locator.count.return_value = count
    return locator


class SetupSkusTests(unittest.TestCase):
    def test_only_uses_controls_in_visible_dialog(self) -> None:
        page = Mock()
        add_multi = _locator()
        dialog_collection = _locator()
        dialog = _locator()
        dialog_collection.last = dialog

        attr_input = _locator()
        value_input = _locator()
        primary_buttons = _locator()
        confirm = _locator()
        primary_buttons.filter.return_value = confirm

        page_selectors = []

        def page_locator(selector):
            page_selectors.append(selector)
            if selector == ".sku-add-btn:visible":
                add_multi.filter.return_value = add_multi
                return add_multi
            if ".sku-dlg-pro:visible" in selector:
                return dialog_collection
            raise AssertionError(f"规格弹窗控件不应从页面全局查找：{selector}")

        def dialog_locator(selector):
            if "商品规格1" in selector and ":not(" not in selector:
                return attr_input
            if ":not(" in selector:
                return value_input
            if selector == "button.el-button--primary:visible":
                return primary_buttons
            raise AssertionError(f"未预期的弹窗选择器：{selector}")

        page.locator.side_effect = page_locator
        dialog.locator.side_effect = dialog_locator

        session = XianGuanjiaSession.__new__(XianGuanjiaSession)
        session._fill_sku_prices_and_stock = Mock()
        specs = [PublishSpec("红色", "12.5"), PublishSpec("蓝色", "13")]

        session._setup_skus(page, "颜色", specs)

        attr_input.fill.assert_called_once_with("颜色")
        attr_input.press.assert_called_once_with("Enter")
        self.assertEqual(
            value_input.fill.call_args_list,
            [call("红色"), call("蓝色")],
        )
        self.assertEqual(value_input.press.call_count, 2)
        confirm.click.assert_called_once_with(timeout=10_000)
        session._fill_sku_prices_and_stock.assert_called_once_with(page, specs)
        self.assertTrue(
            all("has-text('添加')" not in selector for selector in page_selectors)
        )


if __name__ == "__main__":
    unittest.main()
