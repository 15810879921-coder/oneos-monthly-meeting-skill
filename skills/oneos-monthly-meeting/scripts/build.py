#!/usr/bin/env python3
"""Build a reviewed, sanitized monthly report. Manifest is an internal AI interface."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZipFile

from PIL import Image, ImageDraw, ImageFont, ImageOps
from fontTools.ttLib import TTCollection, TTFont
from lxml import etree
from pptx import Presentation
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.oxml.ns import qn
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Inches

W, H = 3840, 2160
GREEN, DARK, INK, GRAY = "#006E49", "#004C34", "#1C2F38", "#4F5659"
KINDS = {"cover", "contents", "chapter", "content", "metrics", "plan", "closing"}
VOICE, RATE, PITCH = "zh-CN-XiaoxiaoNeural", "+20%", "-2Hz"
BRAND_FILES = {"image1.jpeg", "image5.jpeg", "image6.png", "image7.png", "image8.png", "image12.png", "image19.png", "image21.png"}
NS = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main",
      "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


class BuildError(ValueError):
    pass


def spoken_text(text):
    """The brand remains on slides; all speech uses its approved spoken alias."""
    return re.sub(r"one\s*os", "系统", text, flags=re.IGNORECASE)


def assign_sections(slides):
    """Resolve directory hierarchy, independent from physical page numbering."""
    directories = [s for s in slides if s["kind"] == "contents"]
    if len(directories) != 1:
        raise BuildError("必须有一个目录页，正文按目录章节编排")
    titles = directories[0].get("bullets", [])
    if not 1 <= len(titles) <= 3 or len(set(titles)) != len(titles) or any(not t.strip() for t in titles):
        raise BuildError("目录须有 1 至 3 个不重复的章节")
    current, last, covered = None, 0, set()
    seen_directory = False
    for slide in slides:
        kind = slide["kind"]
        if kind == "contents":
            seen_directory = True
        if kind not in {"chapter", "content", "metrics", "plan"}:
            continue
        if not seen_directory:
            raise BuildError("章节和正文必须放在目录后")
        if kind == "chapter" and "chapter_number" not in slide:
            raise BuildError("章节页须明确指定 chapter_number")
        number = slide.get("chapter_number", current)
        if type(number) is not int or not 1 <= number <= len(titles):
            raise BuildError("正文须指定 chapter_number 或继承前一章节；编号必须对应目录")
        if number < last or number > last + 1:
            raise BuildError("按目录章节顺序展开，不跳号或交错章节")
        if kind == "chapter" and slide["title"] != titles[number-1]:
            raise BuildError("章节页标题必须与对应目录一致")
        if kind != "chapter":
            covered.add(number)
        current = last = number
        slide["_chapter_number"] = number
        slide["_chapter_title"] = titles[number-1]
    if covered != set(range(1, len(titles)+1)):
        raise BuildError("每个目录章节都须有正文，不能保留空章节")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_assets(directory):
    directory = Path(directory)
    try:
        entries = json.loads((directory / "brand-manifest.json").read_text(encoding="utf-8"))
        if not isinstance(entries, list) or len(entries) != len(BRAND_FILES) or {e["file"] for e in entries} != BRAND_FILES:
            raise ValueError("invalid asset list")
        for entry in entries:
            if digest(directory / entry["file"]) != entry["sha256"]:
                raise ValueError("asset fingerprint mismatch")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise BuildError("品牌模板素材缺失或指纹不符，请修复技能安装；不会以空白或改变的模板冒充一致风格。") from exc


def run(args):
    result = subprocess.run([str(a) for a in args], capture_output=True, text=True)
    if result.returncode:
        raise BuildError(f"{Path(str(args[0])).name} failed: {result.stderr[-2000:]}")
    return result.stdout


def probe(path):
    return json.loads(run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path]))


def find_font(override=None):
    if override:
        candidates = [Path(override)]
    elif platform.system() == "Darwin":
        candidates = [Path("/System/Library/Fonts/Hiragino Sans GB.ttc")]
    elif platform.system() == "Windows":
        candidates = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/msyh.ttc"]
    else:
        candidates = [Path(p) for p in (
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc")]
    for path in candidates:
        if path.is_file():
            try:
                ImageFont.truetype(str(path), 30)
                return path
            except OSError:
                pass
    raise BuildError("缺少指定中文字库：macOS Hiragino Sans GB / Windows 微软雅黑 / Linux Noto Sans CJK。请安装后重试；不会静默替换字体。")


def validate_glyphs(font_path, text):
    fonts = TTCollection(str(font_path)).fonts if font_path.suffix.lower() == ".ttc" else [TTFont(str(font_path))]
    cmap = fonts[0].getBestCmap()
    missing = sorted({c for c in text if not c.isspace() and ord(c) not in cmap})
    for font in fonts:
        font.close()
    if missing:
        raise BuildError("字体缺少字符：" + "".join(missing[:30]))


def load_manifest(path):
    path = Path(path).resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in ("title", "month", "date"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise BuildError(f"manifest.{key} 必须为非空字符串")
    if data.get("content_reviewed") is not True:
        raise BuildError("正文未完成脱敏审查：content_reviewed 必须为 true")
    if "max_duration_seconds" in data and (type(data["max_duration_seconds"]) not in (int, float) or not math.isfinite(data["max_duration_seconds"]) or data["max_duration_seconds"] <= 0):
        raise BuildError("max_duration_seconds 必须为正数，仅从用户明确时限提取")
    slides = data.get("slides")
    if not isinstance(slides, list) or not slides:
        raise BuildError("slides 必须为非空数组")
    for number, slide in enumerate(slides, 1):
        if not isinstance(slide, dict) or slide.get("kind") not in KINDS:
            raise BuildError(f"第 {number} 页 kind 无效")
        if not isinstance(slide.get("title"), str) or not slide["title"].strip():
            raise BuildError(f"第 {number} 页 title 必填")
        for key in ("subtitle", "status", "narration"):
            if key in slide and not isinstance(slide[key], str):
                raise BuildError(f"第 {number} 页 {key} 必须为字符串")
        if not isinstance(slide.get("bullets", []), list) or any(not isinstance(b, str) for b in slide.get("bullets", [])):
            raise BuildError(f"第 {number} 页 bullets 必须为字符串数组")
        forbidden = {
            "cover": ("status", "bullets", "metrics"), "closing": ("status", "bullets", "metrics"),
            "chapter": ("subtitle", "status", "bullets", "metrics"), "contents": ("subtitle", "status", "metrics"),
            "content": ("metrics",), "plan": ("metrics",), "metrics": (),
        }[slide["kind"]]
        if any(slide.get(k) for k in forbidden):
            raise BuildError(f"第 {number} 页字段与 {slide['kind']} 版式不符；请拆页或移入该版式可见字段，不能静默丢弃内容")
        if slide["kind"] == "metrics":
            metrics = slide.get("metrics")
            if not isinstance(metrics, list) or not 1 <= len(metrics) <= 3:
                raise BuildError("metrics 页必须有 1 至 3 个 metrics 指标")
            for metric in metrics:
                if not isinstance(metric, dict) or any(not isinstance(metric.get(k), str) or not metric[k].strip() for k in ("value", "label")) or not isinstance(metric.get("note", ""), str):
                    raise BuildError("metric 必须有非空字符串 value、label，可选字符串 note")
            if slide.get("bullets") or slide.get("subtitle"):
                raise BuildError("metrics 页说明须写入 metrics[].note，避免正文被指标覆盖")
        if slide["kind"] == "contents" and slide.get("narration", "").strip():
            raise BuildError("目录页固定停留 3 秒且无旁白，请清空 narration")
        shot = slide.get("screenshot")
        if shot is not None:
            if not isinstance(shot, dict) or shot.get("reviewed") is not True:
                raise BuildError(f"第 {number} 页截图未审查，reviewed 必须为 true")
            if slide["kind"] not in {"content", "metrics", "plan"}:
                raise BuildError("截图仅可放在 content/metrics/plan 页")
            if not isinstance(shot.get("path"), str) or not shot["path"]:
                raise BuildError("截图 path 必填")
            source = (path.parent / shot["path"]).resolve()
            if not source.is_file():
                raise BuildError(f"第 {number} 页截图不存在")
            if not isinstance(shot.get("image_sha256"), str) or shot["image_sha256"].lower() != digest(source):
                raise BuildError(f"第 {number} 页截图 SHA256 与审查版本不符")
            if shot.get("layout", "desktop") not in {"desktop", "phone"}:
                raise BuildError("screenshot.layout 仅支持 desktop/phone")
            if not isinstance(shot.get("redactions"), list):
                raise BuildError("screenshot.redactions 必须显式提供数组（无敏感区域时为空）")
            with Image.open(source) as image:
                for rect in shot["redactions"]:
                    if not isinstance(rect, list) or len(rect) != 4 or any(type(n) is not int for n in rect):
                        raise BuildError("脱敏矩形必须为四个整数 [x,y,w,h]")
                    x, y, w, h = rect
                    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > image.width or y + h > image.height:
                        raise BuildError("脱敏矩形负坐标、空面积或越界")
                if image.getexif().get(274, 1) != 1:
                    raise BuildError("截图含旋转 EXIF，请先规范方向后重新审查原像素坐标")
            shot["_source"] = source
        if "narration" in slide:
            slide["narration"] = spoken_text(slide["narration"])
    assign_sections(slides)
    return data


def sanitize(shot, dest):
    """Paint source-pixel rectangles BEFORE resizing; fresh RGB image drops metadata."""
    reviewed_bytes = shot["_source"].read_bytes()
    if hashlib.sha256(reviewed_bytes).hexdigest() != shot["image_sha256"].lower():
        raise BuildError("截图在审查后发生变化，拒绝继续脱敏构建")
    with Image.open(io.BytesIO(reviewed_bytes)) as source:
        image = Image.new("RGB", source.size, "white")
        rgba = source.convert("RGBA")
        image.paste(rgba.convert("RGB"), (0, 0), rgba.getchannel("A"))
    draw = ImageDraw.Draw(image)
    for x, y, w, h in shot["redactions"]:
        draw.rectangle((x, y, x + w - 1, y + h - 1), fill="#18242A")
    image.save(dest, format="PNG")
    return image


class Renderer:
    def __init__(self, font_path, assets, draft=False):
        self.font_path, self.assets, self.draft = font_path, Path(assets), draft

    def font(self, size):
        return ImageFont.truetype(str(self.font_path), size)

    def lines(self, text, size, width):
        f, rows = self.font(size), []
        for para in text.split("\n"):
            row = ""
            for char in para:
                if f.getlength(row + char) > width and row:
                    rows.append(row)
                    row = char
                else:
                    row += char
            rows.append(row)
        return rows

    def block(self, page, text, box, size, color=INK, spacing=1.45):
        x, y, width, height = box
        rows = self.lines(text, size, width)
        step = math.ceil(size * spacing)
        if len(rows) * step > height:
            raise BuildError(f"文字超出版面（{len(rows)} 行，最多 {height // step} 行）。请由 AI 精简或拆页：{text[:40]}")
        d = ImageDraw.Draw(page)
        for i, line in enumerate(rows):
            if self.font(size).getlength(line) > width:
                raise BuildError("单字超出文字区域")
            d.text((x, y + i * step), line, font=self.font(size), fill=color)
        return len(rows) * step

    def background(self, name):
        path = self.assets / name
        if path.is_file():
            with Image.open(path) as image:
                return ImageOps.fit(image.convert("RGB"), (W, H))
        return Image.new("RGB", (W, H), "white")

    def centered(self, page, text, y, height, size, color):
        rows = self.lines(text, size, 3000)
        step = math.ceil(size*1.35)
        if len(rows)*step > height:
            raise BuildError("封面文字超出版面，请精简或拆页")
        d = ImageDraw.Draw(page)
        for i, line in enumerate(rows):
            d.text(((W-self.font(size).getlength(line))/2, y+i*step), line, font=self.font(size), fill=color)

    def logo(self, page, white=False):
        path = self.assets / "image7.png"
        if not path.is_file():
            return
        with Image.open(path) as source:
            logo = source.convert("RGBA")
        if white:
            alpha = logo.getchannel("A")
            logo = Image.new("RGBA", logo.size, "white")
            logo.putalpha(alpha)
        logo.thumbnail((595, 220), Image.Resampling.LANCZOS)
        page.paste(logo, (W - logo.width - 145, 127), logo)

    def render(self, slide, index, meta, shot_image=None):
        kind = slide["kind"]
        special = kind in {"cover", "closing"}
        page = self.background("image1.jpeg" if special else "image8.png" if kind in {"chapter", "contents"} else "image5.jpeg")
        if special and not (self.assets / "image1.jpeg").is_file():
            page = Image.new("RGB", (W, H), DARK)
        self.logo(page, white=special)
        d = ImageDraw.Draw(page)
        if special:
            self.centered(page, slide["title"], 800, 540, 152, "white")
            self.centered(page, slide.get("subtitle") or meta["date"], 1430, 260, 54, "#DAEEE4")
        elif kind == "chapter":
            chapter_no = slide["_chapter_number"]
            if chapter_no not in (1, 2, 3):
                raise BuildError("chapter_number 仅支持 1、2、3")
            wordmark = self.assets / {1: "image12.png", 2: "image19.png", 3: "image21.png"}[chapter_no]
            if wordmark.is_file():
                with Image.open(wordmark) as image:
                    art = image.convert("RGBA")
                art = art.crop(art.getbbox())
                art.thumbnail((2300, 350), Image.Resampling.LANCZOS)
                page.paste(art, (270, 650), art)
            else:
                d.text((270, 650), f"PART.{chapter_no:02}", font=self.font(180), fill=GREEN)
            self.block(page, slide["title"], (275, 1040, 3250, 520), 170, GRAY)
        elif kind == "contents":
            d.text((105, 150), "CONTENTS", font=self.font(240), fill=GREEN)
            items = slide.get("bullets", [])
            if not 1 <= len(items) <= 3:
                raise BuildError("目录须有 1 至 3 项，更多章节请由 AI 归纳")
            width = 3100 // len(items)
            for i, item in enumerate(items):
                x = 360 + i * width
                d.text((x, 800), f"{i + 1:02}", font=self.font(180), fill=GREEN)
                self.block(page, item, (x, 1070, width - 80, 500), 66, GRAY)
        else:
            self.block(page, f"羚牛 ONEOS · {meta['month']}", (95, 53, 2500, 100), 31, DARK)
            text_width = 1808 if shot_image else 3320
            d.text((92, 430), f"{slide['_chapter_number']:02}", font=self.font(105), fill=GREEN)
            self.block(page, slide["_chapter_title"], (310, 454, text_width-218, 100), 48, GREEN, 1.3)
            self.block(page, slide["title"], (92, 620, text_width, 315), 88, INK, 1.35)
            d.line((92, 985, 270, 985), fill=GREEN, width=6)
            status = slide.get("status", "")
            y = 1030
            if status:
                y += self.block(page, status, (92, y, text_width, 210), 57, GREEN) + 35
            if kind == "metrics":
                metrics_bottom = y + ((len(slide["metrics"])-1)*210 + 195 if shot_image else 625)
                if metrics_bottom > 1810:
                    raise BuildError("指标内容超出版面安全区，请缩短状态说明或拆页；不会覆盖页脚。")
                for m, metric in enumerate(slide["metrics"]):
                    if shot_image:
                        my = y + m*210
                        self.block(page, metric["value"], (92, my, 470, 120), 80, GREEN, 1.2)
                        self.block(page, metric["label"], (590, my+20, 1290, 90), 50, INK, 1.2)
                        self.block(page, metric.get("note", ""), (92, my+115, 1790, 80), 37, GRAY, 1.3)
                    else:
                        mx = 92 + m*1130
                        self.block(page, metric["value"], (mx, y, 1020, 255), 160, GREEN, 1.3)
                        self.block(page, metric["label"], (mx, y+280, 1020, 120), 65, INK, 1.3)
                        self.block(page, metric.get("note", ""), (mx, y+435, 1020, 190), 45, GRAY, 1.4)
            else:
                body = "\n".join("• " + b for b in slide.get("bullets", []))
                if slide.get("subtitle"):
                    body = slide["subtitle"] + ("\n" + body if body else "")
                if body:
                    self.block(page, body, (92, y, text_width, 1810 - y), 51)
            if shot_image:
                box = (2620, 400, 860, 1320) if slide["screenshot"].get("layout") == "phone" else (2100, 455, 1665, 1160)
                x, y, w, h = box
                d.rounded_rectangle((x, y, x+w, y+h), radius=20, fill="white", outline="#C3D4CD", width=4)
                # Contain avoids cropping meaningful system content.
                fit = ImageOps.contain(shot_image, (w-24, h-24), Image.Resampling.LANCZOS)
                px, py = x + (w-fit.width)//2, y + (h-fit.height)//2
                page.paste(fit, (px, py))
                slide["_image_bounds"] = [px, py, fit.width, fit.height]
        if not special:
            footer = self.assets / "image6.png"
            if footer.is_file():
                with Image.open(footer) as image:
                    bar = image.convert("RGBA").resize((W, 101), Image.Resampling.LANCZOS)
                page.paste(bar, (0, 2007), bar)
            self.block(page, meta["title"], (95, 1928, 3200, 65), 30, GRAY)
            d.text((3650, 1928), str(index), font=self.font(30), fill=GRAY)
        if self.draft:
            d.rectangle((0, 0, 1000, 95), fill="#9B1C20")
            d.text((35, 12), "草稿 · 无配音 · 不可直接交付", font=self.font(44), fill="white")
        return page


async def tts(text, dest):
    try:
        import edge_tts
    except ImportError as exc:
        raise BuildError("缺少 edge-tts，请安装技能 requirements.txt") from exc
    try:
        await asyncio.wait_for(edge_tts.Communicate(text, VOICE, rate=RATE, pitch=PITCH).save(str(dest)), timeout=90)
    except Exception as exc:
        raise BuildError(f"配音服务失败（{type(exc).__name__}）；不会静默换声音，也未输出最终交付物。请稍后重试。") from exc


def audio_page(slide, dest, draft, pause):
    if slide["kind"] == "contents":
        duration = 3.0
    elif draft:
        duration = 3.0
    elif not slide.get("narration", "").strip():
        raise BuildError("非目录页 narration 必填；不会按字数伪造语音时长")
    else:
        mp3 = dest.with_suffix(".tts.mp3")
        asyncio.run(tts(spoken_text(slide["narration"]), mp3))
        measured = float(probe(mp3)["format"]["duration"])
        duration = math.ceil((measured + pause) * 30) / 30
        run(["ffmpeg", "-v", "error", "-y", "-i", mp3, "-af", f"apad=whole_dur={duration}", "-t", f"{duration:.8f}", "-ar", "48000", "-ac", "2", dest])
        mp3.unlink()
        return duration, measured
    run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", str(duration), dest])
    return duration, 0.0


def xml(parent, tag, **attrs):
    el = OxmlElement(tag)
    for key, val in attrs.items():
        el.set(key, str(val))
    parent.append(el)
    return el


def embed_audio(slide, path, duration):
    # add_movie creates the package media relationship + p14 media extension.
    shape = slide.shapes.add_movie(str(path), Inches(13.25), Inches(7.42), Inches(.01), Inches(.01), mime_type="audio/wav")
    nvpr = shape._element.find(".//p:nvPr", namespaces=NS)
    video_file = nvpr.find("a:videoFile", namespaces=NS)
    video_file.tag = "{" + NS["a"] + "}audioFile"
    old_rid = video_file.get(qn("r:link"))
    target_part = slide.part.rels[old_rid].target_part
    video_file.set(qn("r:link"), slide.part.relate_to(target_part, RT.AUDIO))
    slide.part.drop_rel(old_rid)
    for timing in slide._element.findall("p:timing", namespaces=NS):
        slide._element.remove(timing)
    transition = xml(slide._element, "p:transition", advClick="0", advTm=round(duration*1000))
    transition.set("spd", "fast")
    timing = xml(slide._element, "p:timing")
    root = xml(xml(timing, "p:tnLst"), "p:par")
    root_ctn = xml(root, "p:cTn", id="1", dur="indefinite", restart="never", nodeType="tmRoot")
    sequence = xml(xml(root_ctn, "p:childTnLst"), "p:seq", concurrent="1", nextAc="seek")
    seq_ctn = xml(sequence, "p:cTn", id="2", dur="indefinite", nodeType="mainSeq")
    par = xml(xml(seq_ctn, "p:childTnLst"), "p:par")
    par_ctn = xml(par, "p:cTn", id="3", fill="hold")
    xml(xml(par_ctn, "p:stCondLst"), "p:cond", delay="0")
    audio = xml(xml(par_ctn, "p:childTnLst"), "p:audio", isNarration="1")
    media = xml(audio, "p:cMediaNode", vol="100000", showWhenStopped="0")
    audio_ctn = xml(media, "p:cTn", id="4", fill="hold", display="0", dur=round(duration*1000))
    xml(xml(audio_ctn, "p:stCondLst"), "p:cond", delay="0")
    xml(xml(media, "p:tgtEl"), "p:spTgt", spid=shape.shape_id)


def make_ppt(paths, dest, audio_paths=None, durations=None):
    ppt = Presentation()
    ppt.slide_width, ppt.slide_height = Inches(13.333333), Inches(7.5)
    # Remove identifying core properties and keep all content in visible raster pages.
    ppt.core_properties.author = ""
    ppt.core_properties.last_modified_by = ""
    ppt.core_properties.title = "月度汇报"
    for i, path in enumerate(paths):
        slide = ppt.slides.add_slide(ppt.slide_layouts[6])
        slide.shapes.add_picture(str(path), 0, 0, width=ppt.slide_width, height=ppt.slide_height)
        if audio_paths:
            embed_audio(slide, audio_paths[i], durations[i])
    if audio_paths:
        properties = ppt.part.part_related_by(RT.PRES_PROPS)
        props_xml = etree.fromstring(properties.blob)
        for existing in props_xml.findall("p:showPr", namespaces=NS):
            props_xml.remove(existing)
        show = xml(props_xml, "p:showPr", useTimings="1", showAnimation="1", showNarration="1")
        xml(show, "p:present")
        properties._blob = etree.tostring(props_xml, xml_declaration=True, encoding="UTF-8", standalone=True)
    ppt.save(dest)


def verify_outputs(work, data, durations, draft, video_info):
    """Actual readback checks, independent of success of encoder or PPT writer."""
    prefix = "DRAFT-" if draft else ""
    for i, slide in enumerate(data["slides"], 1):
        with Image.open(work / "slides" / f"{i:02}.png") as page:
            if page.size != (W, H) or page.mode != "RGB" or page.getexif():
                raise BuildError("页面尺寸、色彩或元数据回读失败")
        if slide.get("screenshot"):
            with Image.open(work / "screenshots" / f"{i:02}.png") as image:
                if image.mode != "RGB" or image.getexif():
                    raise BuildError("脱敏图仍含元数据")
                for x, y, w, h in slide["screenshot"]["redactions"]:
                    if image.crop((x, y, x+w, y+h)).getextrema() != ((24, 24), (36, 36), (42, 42)):
                        raise BuildError("敏感区域像素回读失败")
            x, y, w, h = slide["_image_bounds"]
            limit = (2620, 400, 860, 1320) if slide["screenshot"].get("layout") == "phone" else (2100, 455, 1665, 1160)
            lx, ly, lw, lh = limit
            if x < lx or y < ly or x+w > lx+lw or y+h > ly+lh or x < 2100 or y+h >= 1928:
                raise BuildError("截图超出图片区或侵占文字页脚")
    ppt_names = [f"{prefix}report.pptx"] + ([] if draft else ["report-with-audio.pptx"])
    for ppt_name in ppt_names:
        with ZipFile(work / ppt_name) as archive:
            media = [archive.read(n) for n in archive.namelist() if n.startswith("ppt/media/")]
            # Original source bytes must never survive inside any PPT media part.
            for slide in data["slides"]:
                if slide.get("screenshot") and any(hashlib.sha256(b).hexdigest() == slide["screenshot"]["image_sha256"].lower() for b in media):
                    raise BuildError("PPT 中残留原图")
            if "with-audio" in ppt_name:
                props = etree.fromstring(archive.read("ppt/presProps.xml"))
                if props.find("p:showPr", NS).get("useTimings") != "1":
                    raise BuildError("有声 PPT 未启用计时")
                for i, duration in enumerate(durations, 1):
                    sx = etree.fromstring(archive.read(f"ppt/slides/slide{i}.xml"))
                    if len(sx.findall(".//p:audio", NS)) != 1 or sx.find("p:transition", NS).get("advTm") != str(round(duration*1000)):
                        raise BuildError("PPT 旁白或自动切页时序回读失败")
                    if not sx.findall(".//p:audio/p:cMediaNode/p:cTn/p:stCondLst/p:cond[@delay='0']", NS):
                        raise BuildError("PPT 音频缺自动播放起始条件")
                    rels = etree.fromstring(archive.read(f"ppt/slides/_rels/slide{i}.xml.rels"))
                    if not any(r.get("Type") == RT.AUDIO for r in rels):
                        raise BuildError("PPT 音频 relationship 缺失")
    actual_audio_duration = float(probe(work / f"{prefix}narration.wav")["format"]["duration"])
    if abs(actual_audio_duration-sum(durations)) > .025:
        raise BuildError("完整语音与逐页时长不一致")
    if video_info:
        streams = video_info["streams"]
        video = [s for s in streams if s["codec_type"] == "video"]
        audio = [s for s in streams if s["codec_type"] == "audio"]
        if len(video) != 1 or (video[0]["width"], video[0]["height"], video[0]["r_frame_rate"], video[0]["codec_name"]) != (W, H, "30/1", "h264"):
            raise BuildError("视频尺寸、帧率或编码不符")
        if len(audio) != 1 or (audio[0]["codec_name"], audio[0]["sample_rate"], audio[0]["channels"]) != ("aac", "48000", 2) or any(s["codec_type"] == "subtitle" for s in streams):
            raise BuildError("视频音轨或字幕检查失败")
        if abs(float(video_info["format"]["duration"])-sum(durations)) > .08:
            raise BuildError("视频时长与完整音频不一致")


def build(manifest, output, no_audio=False, skip_video=False, assets=None, font=None, pause=.55):
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise BuildError("输出目录非空，拒绝覆盖；请使用新目录")
    if not math.isfinite(pause) or pause < 0 or pause > 5:
        raise BuildError("pause 须在 0 至 5 秒")
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise BuildError(f"缺少 {tool}，请先安装")
    data = load_manifest(manifest)
    if not no_audio and data.get("narration_reviewed") is not True:
        raise BuildError("口播未完成脱敏审查：narration_reviewed 必须为 true；未向 TTS 发送文本")
    font_path = find_font(font)
    all_text = "".join([data["title"], data["month"], data["date"]] + [str(s.get(k, "")) for s in data["slides"] for k in ("title", "subtitle", "status", "bullets", "metrics", "_chapter_title")])
    validate_glyphs(font_path, all_text + "羚牛月度汇报草稿无配音不可直接交付•")
    output.parent.mkdir(parents=True, exist_ok=True)
    assets_dir = Path(assets or Path(__file__).resolve().parents[1] / "assets")
    validate_assets(assets_dir)
    renderer = Renderer(font_path, assets_dir, no_audio)
    with tempfile.TemporaryDirectory(prefix=".monthly-build-", dir=output.parent) as temp:
        work = Path(temp)
        for folder in ("slides", "screenshots", "audio"):
            (work / folder).mkdir()
        pages, audio_paths, durations, entries = [], [], [], []
        # Validate every page visually before sending any narration to the network.
        for i, slide in enumerate(data["slides"], 1):
            safe = sanitize(slide["screenshot"], work / "screenshots" / f"{i:02}.png") if slide.get("screenshot") else None
            page = renderer.render(slide, i, data, safe)
            path = work / "slides" / f"{i:02}.png"
            page.save(path, "PNG")
            pages.append(path)
        for i, slide in enumerate(data["slides"], 1):
            audio_path = work / "audio" / f"{i:02}.wav"
            duration, speech = audio_page(slide, audio_path, no_audio, pause)
            durations.append(duration)
            audio_paths.append(audio_path)
            entry = {"page": i, "kind": slide["kind"], "duration_seconds": duration, "speech_seconds": speech, "image_sha256": digest(pages[i-1]), "narration_sha256": hashlib.sha256(slide.get("narration", "").encode("utf-8")).hexdigest(), "image_bounds": slide.get("_image_bounds"), "redaction_count": len(slide.get("screenshot", {}).get("redactions", []))}
            if slide.get("screenshot"):
                entry["sanitized_sha256"] = digest(work / "screenshots" / f"{i:02}.png")
            if "_chapter_number" in slide:
                entry["chapter_number"] = slide["_chapter_number"]
                entry["chapter_title"] = slide["_chapter_title"]
            entries.append(entry)
        prefix = "DRAFT-" if no_audio else ""
        if data.get("max_duration_seconds") is not None and sum(durations) > data["max_duration_seconds"]:
            raise BuildError(f"完整音频加停顿为 {sum(durations):.3f} 秒，超过用户明确时限 {data['max_duration_seconds']} 秒。请由 AI 精简口播后重建；不会截断音频。")
        make_ppt(pages, work / f"{prefix}report.pptx")
        if not no_audio:
            make_ppt(pages, work / "report-with-audio.pptx", audio_paths, durations)
        audio_list = work / ".audio-concat.txt"
        audio_list.write_text("".join(f"file 'audio/{p.name}'\n" for p in audio_paths), encoding="utf-8")
        run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", audio_list, "-ar", "48000", "-ac", "2", work / f"{prefix}narration.wav"])
        audio_list.unlink()
        video_info = None
        if not skip_video:
            video_list = work / ".video-concat.txt"
            video_list.write_text("".join(f"file 'slides/{p.name}'\nduration {d:.8f}\n" for p, d in zip(pages, durations)) + f"file 'slides/{pages[-1].name}'\n", encoding="utf-8")
            video = work / f"{prefix}report-4k.mp4"
            run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", video_list, "-i", work / f"{prefix}narration.wav", "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22", "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-t", f"{sum(durations):.8f}", "-movflags", "+faststart", "-threads", "2", video])
            video_info = probe(video)
            video_list.unlink()
        verify_outputs(work, data, durations, no_audio, video_info)
        lines = ["# " + data["title"], "", "草稿：无配音，不可直接交付。" if no_audio else f"配音：{VOICE} / {RATE} / {PITCH}", ""]
        for i, slide in enumerate(data["slides"], 1):
            lines += [f"## 第 {i} 页｜{slide['title']}", "", slide.get("narration", "") or "（目录页无旁白，停留 3 秒）", ""]
        (work / f"{prefix}script.md").write_text("\n".join(lines), encoding="utf-8")
        qa = {"schema_version": 1, "draft": no_audio, "content_reviewed": True, "narration_reviewed": data.get("narration_reviewed") is True, "voice": None if no_audio else {"name": VOICE, "rate": RATE, "pitch": PITCH}, "resolution": [W, H], "fps": 30, "duration_seconds": sum(durations), "historical_reference_seconds": 105.514, "editorial_target_seconds": [90, 120], "needs_editorial_review": sum(durations) > 120, "max_duration_seconds": data.get("max_duration_seconds"), "slides": entries, "video": None if video_info is None else {"streams": [{k: s.get(k) for k in ("codec_type", "codec_name", "width", "height", "r_frame_rate", "sample_rate", "channels")} for s in video_info["streams"]], "duration_seconds": float(video_info["format"]["duration"])}, "checks": {"all_raster_pages_4k": True, "source_manifest_copied": False, "source_screenshot_copied": False, "sanitized_images_rgb_no_exif": True, "office_slideshow_test": "not_run"}}
        qa["build_script_sha256"] = digest(__file__)
        qa["script_sha256"] = digest(work / f"{prefix}script.md")
        (work / "qa.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
        # Only safe, allowlisted build results leave this temporary work folder.
        if output.exists():
            output.rmdir()
        os.replace(work, output)
    return qa


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--no-audio", action="store_true", help="仅生成有显著草稿标记的无配音预览")
    parser.add_argument("--skip-video", action="store_true", help="跳过视频编码，用于快速验图")
    parser.add_argument("--assets", type=Path)
    parser.add_argument("--font", type=Path)
    parser.add_argument("--pause", type=float, default=.55)
    args = parser.parse_args()
    try:
        qa = build(args.manifest, args.output, args.no_audio, args.skip_video, args.assets, args.font, args.pause)
        print(json.dumps({"output": str(args.output.resolve()), "draft": qa["draft"], "slides": len(qa["slides"]), "duration_seconds": qa["duration_seconds"], "needs_editorial_review": qa["needs_editorial_review"]}, ensure_ascii=False))
    except (BuildError, OSError, json.JSONDecodeError) as exc:
        print(f"构建失败：{exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
