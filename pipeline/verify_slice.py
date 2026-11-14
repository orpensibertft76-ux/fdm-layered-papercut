import json
import math
import pickle
import re
import shutil
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import trimesh

from build_dragon import WORK, PROJECT, CHECK, COLORS, PALETTE


def parse_path(gcode, expected_layers, pixels_per_mm=8):
    layer = 0
    feature = ""
    x = y = 0.
    width = .42
    layers = np.zeros((expected_layers, 2048, 2048), np.uint8)
    n = [0] * expected_layers
    for line in gcode.splitlines():
        if line.startswith("; layer num/total_layer_count: "):
            layer = int(line.rsplit(" ", 1)[1].split("/")[0])
            feature = ""
        elif line.startswith("; FEATURE: "):
            feature = line[11:]
        elif line.startswith("; LINE_WIDTH: "):
            width = float(line.split(": ")[1])
        elif layer and re.match(r"G[0123] ", line):
            cmd, _, args = line.partition(" ")
            v = {key: float(value) for key,value in re.findall(r"([XYEIJ])(-?[\d.]+)",args.split(";")[0])}
            nx,ny = v.get("X",x),v.get("Y",y)
            if feature and feature != "Custom" and v.get("E",0)>0 and (nx,ny)!=(x,y):
                points = [(x,y),(nx,ny)]
                if cmd in ("G2","G3") and "I" in v and "J" in v:
                    cx,cy = x+v["I"],y+v["J"]
                    radius = math.hypot(x-cx,y-cy)
                    if radius:
                        a,b = math.atan2(y-cy,x-cx),math.atan2(ny-cy,nx-cx)
                        delta = (b-a) % (2*math.pi) if cmd=="G3" else -((a-b) % (2*math.pi))
                        if abs(delta)*radius < 300:
                            theta = np.linspace(a,a+delta, max(3,math.ceil(abs(delta)*radius*5)))
                            points = np.column_stack((cx+radius*np.cos(theta),cy+radius*np.sin(theta)))
                xy = np.array(points)
                xy[:,1] = 256-xy[:,1]
                xy = np.rint(xy*pixels_per_mm).astype(np.int32)
                cv2.polylines(layers[layer-1], [xy], False, 255,
                              max(1,round(width*pixels_per_mm)),lineType=cv2.LINE_8)
                n[layer-1] += 1
            x,y = nx,ny
    assert all(n)
    return layers[[0,-1]],n


def main():
    stage = Path((WORK/"切片缓存位置.txt").read_text(encoding="utf-8-sig").strip())
    native = WORK/"native_verified.3mf"
    sliced = stage/"out"/"dragon_sliced.3mf"
    verified = json.loads((CHECK/"verification.json").read_text(encoding="utf8"))
    comp = json.loads((CHECK/"结构对比.json").read_text(encoding="utf8"))
    with (WORK/"print_meshes.pkl").open("rb") as f:
        source = pickle.load(f)
    preview = Image.new("RGB",(1260,648),"#fff4e2")
    draw = ImageDraw.Draw(preview)
    font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc",17)
    result, tops, rasters = [], [], []
    with zipfile.ZipFile(sliced) as z, zipfile.ZipFile(native) as u:
        assert z.testzip() is None
        expected, actual = (json.loads(a.read("Metadata/project_settings.config")) for a in (u,z))
        keys = ("printer_model","nozzle_diameter","layer_height","initial_layer_print_height",
                "enable_support","enable_prime_tower","wall_generator","filament_colour","filament_type")
        mismatch = {k:[expected.get(k),actual.get(k)] for k in keys if expected.get(k)!=actual.get(k)}
        assert not mismatch,mismatch
        gcode = sorted(n for n in z.namelist() if re.fullmatch(r"Metadata/plate_\d+\.gcode",n))
        assert len(gcode) == 8
        plate_data = ET.fromstring(z.read("Metadata/slice_info.config")).findall("plate")
        assert len(plate_data) == 8
        for i,path in enumerate(gcode):
            text = z.read(path).decode("utf8")
            def value(pattern):
                return re.search(pattern,text,re.M).group(1)
            count = int(value(r"^; total layer number: (\d+)"))
            filament = int(value(r"^; filament: (\d+)\s*$"))
            assert [filament] == verified["active_filaments"][i]
            mesh = source[i][1][0][1]
            assert abs(float(value(r"^; max_z_height: ([\d.]+)"))-mesh.extents[2]) <= .101
            layers,segments = parse_path(text,count)
            x0,y0 = np.rint((128-mesh.extents[:2]/2)*8).astype(int)
            x1,y1 = np.rint((128+mesh.extents[:2]/2)*8).astype(int)
            top = layers[-1,y0:y1,x0:x1].copy()
            top_color = np.full((*top.shape,3),242,np.uint8)
            top_color[top>0] = PALETTE[filament-1]
            Image.fromarray(top_color).save(CHECK/f"切片顶层_{i+1:02d}.png")
            row,col = divmod(i,4)
            x,y = 9+315*col,324*row
            draw.text((x,y+5),verified["plates"][i],font=font,fill="#241712")
            preview.paste(Image.fromarray(top_color).resize((300,285),Image.Resampling.LANCZOS),(x,y+31))
            item = dict(plate=i+1,filament=filament,layers=count,extrusion_segments_per_layer=segments,
                        print_time=value(r"total estimated time: ([^\r\n]+)"),
                        grams=float(value(r"^; total filament weight \[g\] : ([\d.]+)")),
                        support=bool(re.search(r"^; FEATURE: Support",text,re.M)))
            meta = {a.get("key"):a.get("value") for a in plate_data[i].findall("metadata")}
            assert meta["outside"] == "false" and meta["support_used"] == "false"
            assert [(f.get("id"),f.get("type"),f.get("color"))
                    for f in plate_data[i].findall("filament")] == [(str(filament),"PLA",COLORS[filament-1])]
            item["predicted_seconds"] = int(meta["prediction"])
            if i < 6:
                mask = np.array(Image.open(CHECK/comp["selected"]/f"{i+1:02d}_实心遮罩.png"))>0
                route = cv2.resize(top,(744,744),interpolation=cv2.INTER_AREA)>95
                core = cv2.erode(mask.astype(np.uint8),np.ones((5,5),np.uint8)).astype(bool)
                missed = core & ~route
                item.update(top_core_uncovered_percent=float(missed.sum()/max(1,core.sum())*100),
                            top_route_components=cv2.connectedComponents(route.astype(np.uint8),connectivity=8)[0]-1)
                tops.append(route)
                rasters.append((mask,route))
            result.append(item)
        assert not any(r["support"] for r in result)
        # Verify the sliced archive also kept the editable mesh resources.
        model_names = [n for n in u.namelist() if n.endswith(".model")]
        resource_equal = {n:n in z.namelist() and z.read(n)==u.read(n) for n in model_names}
        assert len([n for n in z.namelist() if n.endswith(".model")]) == len(model_names)
        def geometry_and_pose(archive):
            signature = {}
            for name in model_names:
                root = ET.fromstring(archive.read(name))
                signature[name] = [
                    (node.tag, tuple(sorted((k,tuple(round(float(part),4) for part in v.split())
                                              if k in {"x","y","z","transform"} else v)
                                             for k,v in node.attrib.items()
                                           if not k.endswith("}UUID"))))
                    for node in root.iter() if node.tag.split("}")[-1] in
                    {"object","mesh","vertices","vertex","triangles","triangle","component","item"}
                ]
            return signature
        assert geometry_and_pose(u) == geometry_and_pose(z)
    preview.save(CHECK/"八盘实际挤出路径.png")
    levels = np.zeros((744,744),np.uint8)
    for i,route in enumerate(tops):
        levels[route]=i
    Image.fromarray(PALETTE[levels[12:-12,12:-12]]).save(CHECK/"实际路径叠合.png")
    for i,(mask,route) in enumerate(rasters,1):
        overlay = np.full((744,744,3),240,np.uint8)
        overlay[route] = PALETTE[i-1]
        overlay[mask & ~route] = (244,55,146)
        overlay[route & ~mask] = (29,165,195)
        Image.fromarray(overlay).save(CHECK/f"路径差异_{i:02d}.png")
    scene=trimesh.Scene()
    for off,(name,parts) in zip(comp["assembly_offsets_z_mm"],source):
        color,mesh,_ = parts[0]
        mesh=mesh.copy()
        mesh.apply_translation([0,0,off])
        mesh.visual.face_colors = [*PALETTE[color],255]
        scene.add_geometry(mesh,node_name=name,geom_name=name)
    (CHECK/"装配.glb").write_bytes(scene.export(file_type="glb"))
    report = dict(status="eight_plates_sliced_and_checked",plates=result,override_mismatches=mismatch,
                  mesh_resources_byte_identical=resource_equal,total_grams=round(sum(r["grams"] for r in result),2),
                  sliced_geometry_and_pose_match=True,
                  total_predicted_seconds=sum(r["predicted_seconds"] for r in result),
                  verification_cache=str(stage),physical_print=False)
    (CHECK/"切片"/"verification.json").parent.mkdir(exist_ok=True)
    (CHECK/"切片"/"verification.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf8")
    dest = WORK/"output"
    dest.mkdir(exist_ok=True)
    deliverable = dest/"已切片可编辑.3mf"
    if not deliverable.exists():
        with deliverable.open("xb") as f,sliced.open("rb") as g:
            shutil.copyfileobj(g,f)
    assert deliverable.read_bytes() == sliced.read_bytes()
    with zipfile.ZipFile(deliverable) as z:
        assert z.testzip() is None


if __name__=="__main__":
    main()
