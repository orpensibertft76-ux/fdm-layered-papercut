import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

pipeline = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument("job", type=Path)
parser.add_argument("--out", required=True, type=Path)
parser.add_argument("--bambu", type=Path, default=Path("C:/Program Files/Bambu Studio/bambu-studio.exe"))
parser.add_argument("--blender", type=Path)
parser.add_argument("--legacy-box", action="store_true", help="Include the older 192.8-mm demonstration box.")
parser.add_argument("--review-only", action="store_true",
                    help="Generate the artwork and mask review without building or slicing.")
args = parser.parse_args()
job = args.job.resolve()
out = args.out.resolve()
config = json.loads((job/"job.json").read_text(encoding="utf-8-sig"))
from PIL import Image
for key, file in [("art_crop","art.png"),("reference_crop","reference.png")]:
    with Image.open(job/file) as im:
        im.verify()
        x0,y0,x1,y1 = config[key]
        if not (0 <= x0 < x1 <= im.width and 0 <= y0 < y1 <= im.height and
                .98 <= (x1-x0)/(y1-y0) <= 1.02):
            parser.error(f"{key} must identify a square inside {file}")
import re
if (len(config["layers"]) != 6 or len(config["palette"]) != 6 or
    len(set(config["palette"])) != 6 or not all(re.fullmatch(r"#[0-9A-F]{6}", c) for c in config["palette"]) or
    not all(isinstance(n,str) and n.strip() and not re.search(r'[<>:"/\\|?*]',n) for n in config["layers"])):
    parser.error("Provide six unique uppercase hex colors and six valid layer names, ordered back to front.")
if not args.review_only and (not args.bambu.is_file() or (args.blender and not args.blender.is_file())):
    parser.error("Provide an installed Bambu Studio and optional Blender executable.")
out.mkdir(parents=True)
evidence = out/"evidence"
evidence.mkdir()
for file, name in (("job.json","job.json"),("art.png","生图.png"),("reference.png","reference.png")):
    shutil.copyfile(job/file,out/name)
(out/"crop.json").write_text(json.dumps(config["art_crop"]))
env = dict(os.environ,PAPERCUT_WORK=str(out),PAPERCUT_BAMBU=str(args.bambu.resolve()))
env["PAPERCUT_LEGACY_BOX"] = "1" if args.legacy_box else "0"
if args.review_only:
    env["PAPERCUT_REVIEW_ONLY"] = "1"
def run(*command):
    subprocess.run(command,env=env,stdin=subprocess.DEVNULL,check=True)
run(sys.executable,str(pipeline/"build_dragon.py"))
if args.review_only:
    sys.exit(0)
run(sys.executable,str(pipeline/"package_dragon.py"))
cache = Path(os.environ["LOCALAPPDATA"])/"BambuAIToolchain"
cache.mkdir(exist_ok=True)
stage = Path(tempfile.mkdtemp(prefix="papercut_",dir=cache))
(stage/"out").mkdir()
shutil.copyfile(out/"native_verified.3mf",stage/"input.3mf")
(out/"切片缓存位置.txt").write_text(str(stage),encoding="utf8")
with (evidence/"slice.log").open("wb") as log:
    subprocess.run([env["PAPERCUT_BAMBU"],"--arrange","0","--slice","0","--debug","3",
                    "--outputdir",str(stage/"out"),"--export-3mf","dragon_sliced.3mf",str(stage/"input.3mf")],
                   stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,check=True)
for script in ("verify_slice.py","逐片叠合.py"):
    run(sys.executable,str(pipeline/script))
if args.blender:
    run(str(args.blender),"-b","--factory-startup","--offline-mode","--python-exit-code","1",
        "--python",str(pipeline/"render_assembly.py"))
print(out/"output"/"已切片可编辑.3mf")
