"""Entirely fictional fixture; never copy historical business data into tests."""
import hashlib
import json
from pathlib import Path
from PIL import Image, ImageDraw


def create_fixture(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    source = root / "synthetic-source.png"
    image = Image.new("RGB", (1000, 650), "#F5F9F7")
    d = ImageDraw.Draw(image)
    d.rectangle((0, 0, 999, 70), fill="#006E49")
    d.text((30, 25), "FICTIONAL DEMO - NOT BUSINESS DATA", fill="white")
    d.rectangle((30, 125, 969, 580), outline="#A0B4A8", width=3)
    d.text((75, 180), "SYNTHETIC PRIVATE MARKER", fill="#C00000")
    d.text((75, 300), "Status: demo completed", fill="#1C2F38")
    image.save(source)
    phone = root / "synthetic-phone.png"
    phone_image = Image.new("RGB", (400, 800), "#F5F9F7")
    pd = ImageDraw.Draw(phone_image)
    pd.rectangle((0, 0, 399, 80), fill="#006E49")
    pd.text((25, 30), "FICTIONAL MOBILE DEMO", fill="white")
    pd.text((25, 180), "PRIVATE DEMO MARKER", fill="#C00000")
    pd.text((25, 300), "Demo result: complete", fill="#1C2F38")
    phone_image.save(phone)
    manifest = {"title": "虚构项目月度演示", "month": "演示月份", "date": "2026年10月", "content_reviewed": True, "narration_reviewed": True,
                "slides": [
                    {"kind": "cover", "title": "虚构项目\n月度演示", "subtitle": "纯合成测试素材", "narration": "虚构演示。"},
                    {"kind": "contents", "title": "汇报目录", "bullets": ["演示成果", "后续安排"]},
                    {"kind": "content", "title": "演示流程已验证", "status": "合成样例", "bullets": ["演示材料经过脱敏处理。", "截图保持完整比例展示。"], "narration": "流程演示。", "screenshot": {"path": source.name, "reviewed": True, "image_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "redactions": [[65, 160, 400, 70]]}},
                    {"kind": "chapter", "title": "演示成果", "chapter_number": 1, "narration": "演示成果。"},
                    {"kind": "metrics", "title": "虚构指标结果", "status": "仅供样例验收", "metrics": [{"value": "2", "label": "演示事项", "note": "虚构数据，用于验证大数字版式。"}], "narration": "指标演示。", "screenshot": {"path": phone.name, "layout": "phone", "reviewed": True, "image_sha256": hashlib.sha256(phone.read_bytes()).hexdigest(), "redactions": [[15, 160, 320, 70]]}},
                    {"kind": "plan", "title": "后续演示安排", "status": "虚构计划", "bullets": ["整理演示反馈。", "复核生成材料。"], "narration": "计划演示。"},
                    {"kind": "closing", "title": "感谢聆听", "subtitle": "纯合成测试，不代表实际业务结果", "narration": "谢谢。"}]}
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
