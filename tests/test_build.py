import importlib.util
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from fixture import create_fixture

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("monthly_build", ROOT / "skills/oneos-monthly-meeting/scripts/build.py")
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = create_fixture(self.root)
        self.data = json.loads(self.path.read_text())

    def tearDown(self):
        self.temp.cleanup()

    def reject(self, mutator, message):
        mutator(self.data)
        self.path.write_text(json.dumps(self.data))
        with self.assertRaisesRegex(build.BuildError, message):
            build.load_manifest(self.path)

    def test_rejects_unreviewed_body_and_screenshot(self):
        self.reject(lambda m: m.update(content_reviewed=False), "正文")
        self.data["content_reviewed"] = True
        self.reject(lambda m: m["slides"][2]["screenshot"].update(reviewed=False), "未审查")

    def test_rejects_changed_source(self):
        self.reject(lambda m: m["slides"][2]["screenshot"].update(image_sha256="0"*64), "SHA256")

    def test_rejects_bad_rectangles(self):
        for rect in ([-1, 0, 30, 30], [990, 0, 30, 30], [0, 0, 0, 30], [0, 0, 20.5, 30], [True, 0, 20, 30]):
            with self.subTest(rect=rect):
                self.data["slides"][2]["screenshot"]["redactions"] = [rect]
                self.path.write_text(json.dumps(self.data))
                with self.assertRaises(build.BuildError):
                    build.load_manifest(self.path)

    def test_redaction_and_metadata(self):
        shot = build.load_manifest(self.path)["slides"][2]["screenshot"]
        image = build.sanitize(shot, self.root/"safe.png")
        self.assertEqual(image.crop((65, 160, 465, 230)).getextrema(), ((24,24),(36,36),(42,42)))
        from PIL import Image
        with Image.open(self.root/"safe.png") as readback:
            self.assertEqual(readback.mode, "RGB")
            self.assertFalse(readback.getexif())

    def test_long_text_and_missing_font_fail(self):
        renderer = build.Renderer(build.find_font(), self.root)
        data = build.load_manifest(self.path)
        slide = data["slides"][2]
        slide["bullets"] = ["很长的文字" * 300]
        with self.assertRaisesRegex(build.BuildError, "超出版面"):
            renderer.render(slide, 3, data, build.Image.new("RGB", (1000,650)))
        with self.assertRaisesRegex(build.BuildError, "字库"):
            build.find_font(self.root/"missing-font.ttc")

    def test_narration_review_is_checked_before_network(self):
        self.data["narration_reviewed"] = False
        self.path.write_text(json.dumps(self.data))
        with self.assertRaisesRegex(build.BuildError, "未向 TTS"):
            build.build(self.path, self.root/"output")

    def test_rejects_invalid_time_limit_and_hidden_content(self):
        self.reject(lambda m: m.update(max_duration_seconds=-1), "max_duration")
        self.data.pop("max_duration_seconds")
        self.reject(lambda m: m["slides"][0].update(bullets=["不可静默丢弃的正文"]), "不能静默丢弃")

    def test_user_time_limit_fails_without_final_artifact(self):
        self.data["max_duration_seconds"] = .1
        self.path.write_text(json.dumps(self.data))
        with patch.object(build, "audio_page", return_value=(1.0, .45)):
            with self.assertRaisesRegex(build.BuildError, "用户明确时限"):
                build.build(self.path, self.root/"no-final", skip_video=True)
        self.assertFalse((self.root/"no-final").exists())

    def test_screenshot_swap_after_validation_is_rejected(self):
        shot = build.load_manifest(self.path)["slides"][2]["screenshot"]
        shot["_source"].write_bytes(b"changed")
        with self.assertRaisesRegex(build.BuildError, "审查后发生变化"):
            build.sanitize(shot, self.root/"never.png")

    def test_brand_assets_must_match_manifest(self):
        assets = self.root / "assets"
        shutil.copytree(ROOT / "skills/oneos-monthly-meeting/assets", assets)
        build.validate_assets(assets)
        (assets / "image7.png").write_bytes(b"changed logo")
        with self.assertRaisesRegex(build.BuildError, "指纹不符"):
            build.validate_assets(assets)
        (assets / "brand-manifest.json").unlink()
        with self.assertRaises(build.BuildError):
            build.validate_assets(assets)

    def test_metrics_do_not_overlap_footer(self):
        renderer = build.Renderer(build.find_font(), self.root)
        data = build.load_manifest(self.path)
        slide = data["slides"][4]
        slide["status"] = "第一行状态\n第二行状态"
        slide["metrics"] *= 3
        for shot in (None, build.Image.new("RGB", (400,800))):
            with self.subTest(screenshot=shot is not None):
                with self.assertRaisesRegex(build.BuildError, "超出版面安全区"):
                    renderer.render(slide, 5, data, shot)

    def test_brand_spoken_alias_preserves_visual_title(self):
        self.data["slides"][0]["narration"] = "ONEOS、oneos、One OS 本月进展。"
        self.path.write_text(json.dumps(self.data))
        data = build.load_manifest(self.path)
        self.assertEqual(data["slides"][0]["narration"], "系统、系统、系统 本月进展。")
        self.assertIn("ONEOS", data["slides"][0]["title"])
        sent = []
        async def capture(text, dest):
            sent.append(text)
            dest.write_bytes(b"test")
        with patch.object(build, "tts", capture), patch.object(build, "probe", return_value={"format":{"duration":"1.0"}}), patch.object(build, "run"):
            build.audio_page(self.data["slides"][0], self.root/"audio.wav", False, .55)
        self.assertEqual(sent, [data["slides"][0]["narration"]])

    def test_chapter_inheritance_and_not_physical_page(self):
        data = build.load_manifest(self.path)
        self.assertEqual([s.get("_chapter_number") for s in data["slides"]], [None,None,1,2,2,3,None])
        self.assertEqual(data["slides"][4]["_chapter_title"], "运行情况")

    def test_chapter_mismatch_and_missing_or_out_of_order_sections_fail(self):
        self.reject(lambda m: m["slides"][3].pop("chapter_number"), "章节页须明确")
        self.data["slides"][3]["chapter_number"] = 2
        self.reject(lambda m: m["slides"][3].update(title="错误目录标题"), "目录一致")
        self.data["slides"][3]["title"] = "运行情况"
        self.reject(lambda m: m["slides"][5].update(chapter_number=1), "章节顺序")
        self.data["slides"][5]["chapter_number"] = 3
        self.reject(lambda m: m["slides"][2].pop("chapter_number"), "正文须指定")

    def test_script_and_narration_fingerprint_match_spoken_text(self):
        qa = build.build(self.path, self.root/"draft", no_audio=True, skip_video=True)
        script = (self.root/"draft/DRAFT-script.md").read_text()
        self.assertIn("下面汇报 系统 的进展。", script)
        import hashlib
        expected = hashlib.sha256("下面汇报 系统 的进展。".encode()).hexdigest()
        self.assertEqual(qa["slides"][0]["narration_sha256"], expected)


if __name__ == "__main__":
    unittest.main()
