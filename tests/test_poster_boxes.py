import json
import os
import tempfile
import unittest
from unittest import mock

from tabs.tab_process import (
    ProcessTab,
    RESELECT_POSTER,
    copied_poster_box,
    load_poster_region_preset,
    move_poster_box,
    save_poster_region_preset,
)


class PosterBoxMovementTests(unittest.TestCase):
    def test_move_preserves_size(self) -> None:
        moved = move_poster_box((10, 20, 110, 220), 35, 45, 500, 500)

        self.assertEqual(moved, (45, 65, 145, 265))

    def test_move_stays_inside_poster(self) -> None:
        moved = move_poster_box((10, 20, 110, 220), 999, 999, 300, 350)

        self.assertEqual(moved, (200, 150, 300, 350))

    def test_copy_is_offset_but_keeps_exact_dimensions(self) -> None:
        original = (10, 20, 110, 220)

        copied = copied_poster_box(original, 500, 500)

        self.assertEqual(copied, (22, 32, 122, 232))
        self.assertEqual(copied[2] - copied[0], original[2] - original[0])
        self.assertEqual(copied[3] - copied[1], original[3] - original[1])

    def test_copy_near_edge_remains_inside_poster(self) -> None:
        copied = copied_poster_box((200, 150, 300, 350), 300, 350)

        self.assertEqual(copied, (188, 138, 288, 338))


class PosterRegionPresetTests(unittest.TestCase):
    def test_save_and_load_preserves_poster_and_boxes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            poster_path = os.path.join(temp_dir, "poster.png")
            storage_path = os.path.join(temp_dir, "presets.json")
            with open(poster_path, "wb") as f:
                f.write(b"test")
            boxes = [(10, 20, 110, 220), (150, 30, 250, 230)]

            error = save_poster_region_preset(
                "pendant_bag",
                poster_path,
                boxes,
                storage_path=storage_path,
            )
            loaded = load_poster_region_preset(
                "pendant_bag",
                storage_path=storage_path,
            )

            self.assertIsNone(error)
            self.assertEqual(loaded, (os.path.abspath(poster_path), boxes))

    def test_presets_for_features_do_not_overwrite_each_other(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            poster_path = os.path.join(temp_dir, "poster.png")
            storage_path = os.path.join(temp_dir, "presets.json")
            with open(poster_path, "wb") as f:
                f.write(b"test")

            save_poster_region_preset(
                "single_image",
                poster_path,
                [(1, 2, 30, 40)],
                storage_path=storage_path,
            )
            save_poster_region_preset(
                "multi_image",
                poster_path,
                [(5, 6, 50, 60), (70, 80, 120, 140)],
                storage_path=storage_path,
            )

            self.assertEqual(
                load_poster_region_preset(
                    "single_image",
                    storage_path=storage_path,
                ),
                (os.path.abspath(poster_path), [(1, 2, 30, 40)]),
            )
            self.assertEqual(
                load_poster_region_preset(
                    "multi_image",
                    storage_path=storage_path,
                ),
                (
                    os.path.abspath(poster_path),
                    [(5, 6, 50, 60), (70, 80, 120, 140)],
                ),
            )

    def test_missing_saved_poster_is_not_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = os.path.join(temp_dir, "presets.json")
            missing_path = os.path.join(temp_dir, "missing.png")
            with open(storage_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "single_image": {
                            "poster_path": missing_path,
                            "boxes": [[1, 2, 30, 40]],
                        }
                    },
                    f,
                )

            loaded = load_poster_region_preset(
                "single_image",
                storage_path=storage_path,
            )

            self.assertIsNone(loaded)


class PosterRegionPresetFlowTests(unittest.TestCase):
    def _tab(self) -> ProcessTab:
        tab = ProcessTab.__new__(ProcessTab)
        tab.app = object()
        return tab

    def test_saved_dual_preset_skips_initial_file_picker(self) -> None:
        boxes = [(10, 20, 110, 220), (150, 30, 250, 230)]
        with (
            mock.patch(
                "tabs.tab_process.load_poster_region_preset",
                return_value=("saved.png", boxes),
            ),
            mock.patch(
                "tabs.tab_process.ask_poster_regions",
                return_value=tuple(boxes),
            ) as ask_regions,
            mock.patch(
                "tabs.tab_process.filedialog.askopenfilename"
            ) as ask_file,
        ):
            result = self._tab()._select_dual_regions_with_preset(
                "pendant_bag",
                "挂件袋双图贴入",
            )

        self.assertEqual(result, ("saved.png", tuple(boxes)))
        ask_file.assert_not_called()
        self.assertEqual(
            ask_regions.call_args.kwargs["initial_boxes"],
            boxes,
        )

    def test_reselect_image_uses_picker_and_starts_fresh(self) -> None:
        saved_boxes = [(10, 20, 110, 220)]
        new_boxes = [(30, 40, 130, 240)]
        with (
            mock.patch(
                "tabs.tab_process.load_poster_region_preset",
                return_value=("saved.png", saved_boxes),
            ),
            mock.patch(
                "tabs.tab_process.ask_poster_regions_multi",
                side_effect=[RESELECT_POSTER, new_boxes],
            ) as ask_regions,
            mock.patch(
                "tabs.tab_process.filedialog.askopenfilename",
                return_value="new.png",
            ) as ask_file,
        ):
            result = self._tab()._select_multi_regions_with_preset(
                "single_image",
                "单图贴入",
            )

        self.assertEqual(result, ("new.png", new_boxes))
        ask_file.assert_called_once()
        self.assertEqual(
            ask_regions.call_args_list[0].kwargs["initial_boxes"],
            saved_boxes,
        )
        self.assertIsNone(
            ask_regions.call_args_list[1].kwargs["initial_boxes"]
        )


if __name__ == "__main__":
    unittest.main()
