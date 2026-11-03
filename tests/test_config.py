import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mania_overlay import config  # noqa: E402


class MigrationTest(unittest.TestCase):
    def load(self, saved):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "settings.json"
            p.write_text(json.dumps(saved))
            s = config.Settings(p).get()
            on_disk = json.loads(p.read_text())
        return s, on_disk

    def test_v1_settings_get_new_look(self):
        old = {
            "theme": {"colors": dict(config.OLD_JUDGEMENT_COLORS)},
            "widgets": {
                "judgements": {"x": 100, "y": 200, "scale": 0.7, "layout": "rows", "showRatios": True, "showBadge": True},
                "ur": {"x": 760, "y": 980, "barWidth": 400, "barHistory": 40, "showBar": True},
            },
        }
        s, on_disk = self.load(old)
        j, ur = s["widgets"]["judgements"], s["widgets"]["ur"]
        self.assertEqual((j["layout"], j["showRatios"], j["showBadge"]), ("chart", False, False))
        self.assertEqual((j["x"], j["y"], j["scale"]), (100, 200, 0.7))   # position kept
        self.assertEqual((ur["barWidth"], ur["x"], ur["barHistory"]), (100, 910, 30))
        self.assertTrue(ur["showEarlyLate"])
        self.assertNotIn("showBar", ur)
        self.assertEqual(s["theme"]["colors"], config.JUDGEMENT_COLORS)
        self.assertEqual(on_disk["version"], config.SETTINGS_VERSION)      # saved once

    def test_custom_choices_kept(self):
        old = {
            "theme": {"colors": {**config.OLD_JUDGEMENT_COLORS, "miss": "#123456"}},
            "widgets": {"judgements": {"layout": "compact"}, "ur": {"barWidth": 250, "x": 500}},
        }
        s, _ = self.load(old)
        self.assertEqual(s["widgets"]["judgements"]["layout"], "compact")
        self.assertEqual((s["widgets"]["ur"]["barWidth"], s["widgets"]["ur"]["x"]), (250, 500))
        self.assertEqual(s["theme"]["colors"]["miss"], "#123456")
        self.assertEqual(s["theme"]["colors"]["max"], "#cfe8ff")          # palette not swapped

    def test_current_version_untouched(self):
        cur = {"version": 2, "widgets": {"judgements": {"layout": "counts", "showRatios": True}}}
        s, _ = self.load(cur)
        self.assertEqual(s["widgets"]["judgements"]["layout"], "counts")
        self.assertTrue(s["widgets"]["judgements"]["showRatios"])


if __name__ == "__main__":
    unittest.main()
