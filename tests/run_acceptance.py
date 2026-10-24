"""Reproducible local artifact check. --online sends only fictional narration to TTS."""
import argparse
import importlib.util
import json
from pathlib import Path
from fixture import create_fixture

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("monthly_build", ROOT / "skills/oneos-monthly-meeting/scripts/build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--online", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT/".local/acceptance")
    parser.add_argument("--skip-video", action="store_true")
    args = parser.parse_args()
    fixture = create_fixture(args.output/"source")
    qa = build.build(fixture, args.output/"dist", no_audio=not args.online, skip_video=args.skip_video)
    print(json.dumps({"artifact_directory": str(args.output/"dist"), "draft": qa["draft"], "duration_seconds": qa["duration_seconds"], "checks": qa["checks"]}, ensure_ascii=False, indent=2))
