import unittest
from types import SimpleNamespace
from unittest import mock

from tabs.tab_gemini import GeminiTab


class GeminiPromptUiFlowTests(unittest.TestCase):
    def _tab(self) -> SimpleNamespace:
        return SimpleNamespace(
            _busy=False,
            app=mock.Mock(),
            _session=mock.Mock(),
        )

    def test_cancel_does_not_overwrite_saved_prompt(self) -> None:
        tab = self._tab()
        with (
            mock.patch(
                "tabs.tab_gemini.load_last_gemini_prompt",
                return_value="上次提示词",
            ),
            mock.patch(
                "tabs.tab_gemini.ask_gemini_batch_dialog",
                return_value=None,
            ) as dialog,
            mock.patch(
                "tabs.tab_gemini.save_last_gemini_prompt"
            ) as save_prompt,
        ):
            GeminiTab.on_gemini_batch(tab)

        self.assertEqual(dialog.call_args.args[1], "上次提示词")
        save_prompt.assert_not_called()
        tab._session.submit_batch.assert_not_called()

    def test_confirm_saves_modified_prompt_before_batch(self) -> None:
        tab = self._tab()
        with (
            mock.patch(
                "tabs.tab_gemini.load_last_gemini_prompt",
                return_value="上次提示词",
            ),
            mock.patch(
                "tabs.tab_gemini.ask_gemini_batch_dialog",
                return_value=("本次修改后的提示词", ["1.png"]),
            ),
            mock.patch(
                "tabs.tab_gemini.save_last_gemini_prompt",
                return_value=None,
            ) as save_prompt,
        ):
            GeminiTab.on_gemini_batch(tab)

        save_prompt.assert_called_once_with("本次修改后的提示词")
        tab._session.submit_batch.assert_called_once()


if __name__ == "__main__":
    unittest.main()
