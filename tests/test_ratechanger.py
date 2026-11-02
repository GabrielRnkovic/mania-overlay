import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mania_overlay import paths, ratechanger  # noqa: E402

MAP = """osu file format v14\r
\r
[General]\r
AudioFilename: audio.mp3\r
AudioLeadIn: 0\r
PreviewTime: 10000\r
Mode: 3\r
\r
[Editor]\r
Bookmarks: 1000,2000\r
\r
[Metadata]\r
Title:Song\r
Artist:Someone\r
Creator:mapper\r
Version:Insane\r
Tags:\r
BeatmapID:123\r
BeatmapSetID:45\r
\r
[Difficulty]\r
CircleSize:4\r
OverallDifficulty:8\r
\r
[Events]\r
0,0,"bg.jpg",0,0\r
2,5000,6000\r
\r
[TimingPoints]\r
110,500,4,2,0,40,1,0\r
1100.5,-50,4,2,0,40,0,0\r
\r
[HitObjects]\r
64,192,1100,1,0,0:0:0:0:\r
192,192,2200,128,0,3300:0:0:0:0:\r
"""


class TransformTest(unittest.TestCase):
    def setUp(self):
        self.out = ratechanger.transform_osu(MAP, 1.1, "Insane 1.1x", "audio_1.1x.ogg")

    def test_times_scaled(self):
        self.assertIn("PreviewTime: 9091", self.out)
        self.assertIn("Bookmarks: 909,1818", self.out)
        self.assertIn("2,4545,5455", self.out)
        self.assertIn("64,192,1000,1,0,0:0:0:0:", self.out)
        self.assertIn("192,192,2000,128,0,3000:0:0:0:0:", self.out)

    def test_timing_points(self):
        self.assertIn("100,454.545454545,4,2,0,40,1,0", self.out)
        self.assertIn("1000,-50,4,2,0,40,0,0", self.out)  # SV unchanged

    def test_metadata(self):
        self.assertIn("AudioFilename: audio_1.1x.ogg", self.out)
        self.assertIn("Version:Insane 1.1x", self.out)
        self.assertIn("BeatmapID:0", self.out)
        self.assertIn("BeatmapSetID:45", self.out)
        self.assertIn("Tags:rate_change", self.out)
        self.assertIn('0,0,"bg.jpg",0,0', self.out)

    def test_line_endings_kept(self):
        self.assertTrue(self.out.endswith("\r\n"))
        self.assertNotIn("\r\r", self.out)

    def test_names(self):
        self.assertEqual(ratechanger.fmt_rate(1.1), "1.1")
        self.assertEqual(ratechanger.fmt_rate(1.05), "1.05")
        self.assertEqual(ratechanger.fmt_rate(0.9), "0.9")
        name = ratechanger.rated_osu_name(Path("Someone - Song (mapper) [Insane].osu"), "Insane 1.1x")
        self.assertEqual(name, "Someone - Song (mapper) [Insane 1.1x].osu")

    def test_atempo_chain(self):
        self.assertEqual(ratechanger._atempo_chain(1.1), "atempo=1.100000")
        self.assertEqual(ratechanger._atempo_chain(2.5), "atempo=2.0,atempo=1.250000")


class MakeRateTest(unittest.TestCase):
    def test_make_rate_writes_files(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            osu = folder / "Someone - Song (mapper) [Insane].osu"
            osu.write_text(MAP, encoding="utf-8")
            (folder / "audio.mp3").write_bytes(b"fake")

            def fake_convert(src, dst, rate, pitch, codec_args):
                dst.write_bytes(b"converted")

            with mock.patch.object(ratechanger, "convert_audio", side_effect=fake_convert), \
                 mock.patch.object(ratechanger, "_ffmpeg_has", return_value=False):
                res = ratechanger.make_rate(osu, 1.2)
                self.assertFalse(res.skipped)
                self.assertTrue(res.osu_path.name.endswith("[Insane 1.2x].osu"))
                self.assertEqual(res.audio_path.name, "audio_1.2x.ogg")
                self.assertIn("AudioFilename: audio_1.2x.ogg", res.osu_path.read_text())
                again = ratechanger.make_rate(osu, 1.2)
                self.assertTrue(again.skipped)
                pitched = ratechanger.make_rate(osu, 1.2, pitch=True)
                self.assertEqual(pitched.audio_path.name, "audio_1.2x_p.ogg")
                self.assertIn("(pitch)", pitched.version)

    def _mapset(self, d):
        folder = Path(d)
        osu = folder / "Someone - Song (mapper) [Insane].osu"
        osu.write_text(MAP, encoding="utf-8")
        (folder / "audio.mp3").write_bytes(b"fake")
        return osu

    def test_od_only_keeps_timing_and_audio(self):
        with tempfile.TemporaryDirectory() as d:
            osu = self._mapset(d)
            with mock.patch.object(ratechanger, "convert_audio") as conv:
                res = ratechanger.make_rate(osu, 1.0, od=7.5)
                conv.assert_not_called()
            text = res.osu_path.read_text()
            self.assertTrue(res.osu_path.name.endswith("[Insane OD7.5].osu"))
            self.assertIn("OverallDifficulty:7.5", text)
            self.assertNotIn("OverallDifficulty:8", text)
            self.assertIn("AudioFilename: audio.mp3", text)
            self.assertIn("1100.5,-50,4,2,0,40,0,0", text)   # decimals untouched
            self.assertIn("PreviewTime: 10000", text)
            self.assertIn("192,192,2200,128,0,3300:0:0:0:0:", text)
            self.assertIn("BeatmapID:0", text)
            self.assertEqual(res.audio_path.name, "audio.mp3")

    def test_rate_and_od(self):
        with tempfile.TemporaryDirectory() as d:
            osu = self._mapset(d)
            with mock.patch.object(ratechanger, "convert_audio",
                                   side_effect=lambda s, dst, *a: dst.write_bytes(b"x")), \
                 mock.patch.object(ratechanger, "_ffmpeg_has", return_value=False):
                res = ratechanger.make_rate(osu, 1.15, od=9, pitch=True)
            text = res.osu_path.read_text()
            self.assertEqual(res.version, "Insane 1.15x (pitch) OD9")
            self.assertIn("OverallDifficulty:9", text)
            self.assertIn("AudioFilename: audio_1.15x_p.ogg", text)
            self.assertIn("64,192,957,1,0,0:0:0:0:", text)

    def test_od_validation(self):
        with tempfile.TemporaryDirectory() as d:
            osu = self._mapset(d)
            with self.assertRaises(ratechanger.RateError):
                ratechanger.make_rate(osu, 1.0, od=8)      # same OD as the map
            with self.assertRaises(ratechanger.RateError):
                ratechanger.make_rate(osu, 1.0, od=11)
            with self.assertRaises(ratechanger.RateError):
                ratechanger.make_rate(osu, 1.0, od=-1)

    def test_version_names(self):
        self.assertEqual(ratechanger.new_version("Hard", 1.1, False, None), "Hard 1.1x")
        self.assertEqual(ratechanger.new_version("Hard", 1.0, False, 8.0), "Hard OD8")
        self.assertEqual(ratechanger.new_version("Hard", 0.9, False, 7.25), "Hard 0.9x OD7.2")

    def test_rejects_non_mania(self):
        with tempfile.TemporaryDirectory() as d:
            osu = Path(d) / "x [y].osu"
            osu.write_text(MAP.replace("Mode: 3", "Mode: 0"), encoding="utf-8")
            (Path(d) / "audio.mp3").write_bytes(b"fake")
            with self.assertRaises(ratechanger.RateError):
                ratechanger.make_rate(osu, 1.1)

    def test_rejects_bad_rate(self):
        with self.assertRaises(ratechanger.RateError):
            ratechanger.make_rate(Path("nope.osu"), 1.0)
        with self.assertRaises(ratechanger.RateError):
            ratechanger.make_rate(Path("nope.osu"), 5)


class PathsTest(unittest.TestCase):
    def test_wine_paths(self):
        with tempfile.TemporaryDirectory() as d:
            prefix = Path(d) / "prefix"
            songs = prefix / "drive_c/osu!/Songs/123 Song"
            songs.mkdir(parents=True)
            (songs / "map.osu").write_text("x")
            got = paths.find_existing([r"C:\osu!\Songs\123 Song\map.osu"], str(prefix))
            self.assertEqual(got, songs / "map.osu")
            got = paths.find_existing(["Z:" + str(songs / "map.osu").replace("/", "\\")])
            self.assertEqual(got, songs / "map.osu")

    def test_beatmap_path_with_songs_override(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / "Songs" / "1 A - B"
            folder.mkdir(parents=True)
            (folder / "m.osu").write_text("x")
            tosu = {"folders": {"beatmap": "1 A - B", "songs": r"C:\nowhere"}, "files": {"beatmap": "m.osu"}}
            settings = {"general": {"songsFolder": str(Path(d) / "Songs"), "winePrefix": ""}}
            self.assertEqual(paths.beatmap_path(tosu, settings), folder / "m.osu")


if __name__ == "__main__":
    unittest.main()
