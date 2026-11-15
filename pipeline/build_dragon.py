from pathlib import Path
import json
import math
import os
import pickle

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from shapely import box, union_all, constrained_delaunay_triangles
from shapely.affinity import scale, translate
from skimage.graph import MCP_Geometric
import trimesh


WORK = Path(os.environ["PAPERCUT_WORK"])
PROJECT = WORK.parents[1]
CHECK = WORK / "evidence"
JOB = json.loads((WORK / "job.json").read_text(encoding="utf-8-sig"))
N = 744
RIM = 12
MM = .25
THICKNESS = 1.2
NAMES = tuple(JOB["layers"])
COLORS = JOB["palette"]
PALETTE = np.array([[int(c[j:j+2], 16) for j in (1, 3, 5)] for c in COLORS], np.uint8)


def png(path, labels):
    Image.fromarray(PALETTE[labels]).save(path)


def shift(mask, dx, dy):
    return cv2.warpAffine(mask.astype(np.uint8), np.float32([[1, 0, dx], [0, 1, dy]]),
                          (N, N), flags=cv2.INTER_NEAREST).astype(bool)


def labels_from_art():
    im = Image.open(WORK / "生图.png").convert("RGB")
    crop = json.loads((WORK / "crop.json").read_text()) if (WORK / "crop.json").exists() else None
    if crop:
        im = im.crop(crop)
    rgb = np.array(im.resize((N-2*RIM, N-2*RIM), Image.Resampling.LANCZOS))
    smooth = cv2.bilateralFilter(rgb, 7, 32, 3)
    lab = cv2.cvtColor(smooth, cv2.COLOR_RGB2LAB).astype(np.float32)
    palette = cv2.cvtColor(PALETTE[None], cv2.COLOR_RGB2LAB)[0].astype(np.float32)
    labels = ((lab[:, :, None] - palette) ** 2).sum(axis=3).argmin(axis=2).astype(np.uint8)
    for _ in range(2):
        for color in range(6):
            count, ids, stats, _ = cv2.connectedComponentsWithStats(
                (labels == color).astype(np.uint8), connectivity=4)
            for i in range(1, count):
                x,y,w,h,area = stats[i]
                if area > 12:
                    continue
                bounds = np.s_[max(0,y-2):y+h+2, max(0,x-2):x+w+2]
                mark = ids[bounds] == i
                around = cv2.dilate(mark.astype(np.uint8), np.ones((5,5),np.uint8)).astype(bool) & ~mark
                nearby = labels[bounds][around & (labels[bounds] != color)]
                if nearby.size:
                    labels[bounds][mark] = np.bincount(nearby).argmax()
    # Normalize the outermost gold perimeter after cropping at the visible gold edge.
    labels[:2, :] = labels[-2:, :] = 5
    labels[:, :2] = labels[:, -2:] = 5
    return np.pad(labels, RIM)


def join(mask, permitted, hidden):
    """Join all components to the rim. Prefer wide, hidden attachment corridors."""
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7,7))
    distance = cv2.distanceTransform(permitted.astype(np.uint8), cv2.DIST_L2, 5)
    changed = mask.copy()
    while True:
        count, ids, stats, _ = cv2.connectedComponentsWithStats(changed.astype(np.uint8), connectivity=4)
        if count == 2:
            return changed
        home = ids == ids[0,0]
        foreign = [j for j in range(1,count) if j != ids[0,0]]
        costs = np.where(changed, .05, np.where(hidden, 1., np.where(permitted, 7., 40.)))
        costs += np.where(distance < 3.1, 3., 0.)
        contour = home & ~cv2.erode(home.astype(np.uint8), np.ones((3,3),np.uint8)).astype(bool)
        starts = np.argwhere(contour)[::2].tolist()
        ends = []
        for j in foreign:
            x,y,w,h,_ = stats[j]
            view = ids[y:y+h,x:x+w] == j
            d = cv2.distanceTransform(np.pad(view.astype(np.uint8),1), cv2.DIST_L2, 5)[1:-1,1:-1]
            iy,ix = np.unravel_index(d.argmax(),d.shape)
            ends.append((y+iy,x+ix))
        router = MCP_Geometric(costs, fully_connected=True)
        dtype = np.uint8
        paths = np.zeros((N,N),dtype)
        # A single distance sweep routes all islands to the same physical rim.
        router.find_costs(starts, ends)
        for end in ends:
            path = np.asarray(router.traceback(end))
            paths[path[:,0],path[:,1]] = 1
        changed |= cv2.dilate(paths,kernel).astype(bool)


def rim_mask():
    rim = np.ones((N,N),bool)
    rim[RIM:-RIM,RIM:-RIM] = False
    return rim


def regularize(mask, rim):
    # Close pixel pinholes and remove decorative tips below the path-width target.
    body = mask.astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(3,3))
    body = cv2.morphologyEx(body, cv2.MORPH_CLOSE,kernel)
    return cv2.morphologyEx(body, cv2.MORPH_OPEN,kernel).astype(bool) | rim


def solve(target, mode):
    rim = rim_mask()
    stack = [np.ones((N,N),bool)] + [None]*5
    added = [np.zeros_like(rim) for _ in range(6)]
    all_front = rim.copy()
    for i in reversed(range(1,6)):
        ink = target == i
        permitted = (target >= i) | all_front
        covered = all_front.copy()
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
            projected = rim.copy()
            for j in range(i+1,6):
                q = (j-i) * THICKNESS * math.tan(math.radians(30)) / MM
                projected |= shift(stack[j], q*dx, q*dy)
            covered &= projected
        if mode == "A":
            seed = regularize(permitted, rim)
        else:
            seed = regularize(ink | rim, rim)
            seed |= cv2.dilate(seed.astype(np.uint8),np.ones((5,5),np.uint8)).astype(bool) & covered
        stack[i] = join(seed, permitted, covered)
        # Add solid at diagonal/checkerboard vertex contacts before polygonization.
        for _ in range(3):
            a,b,c,d = stack[i][:-1,:-1],stack[i][:-1,1:],stack[i][1:,:-1],stack[i][1:,1:]
            diagonal = (a & d & ~b & ~c) | (b & c & ~a & ~d)
            a[diagonal] = True
            b[diagonal] = True
            c[diagonal] = True
            d[diagonal] = True
        added[i] = stack[i] & ~ink
        all_front |= stack[i]
    return stack, added


def composite(stack, direction=(0,0)):
    result = np.zeros((N,N),np.uint8)
    for i,mask in enumerate(stack):
        dx,dy = direction
        low = (i-6)*THICKNESS*math.tan(math.radians(30))/MM
        high = (i-5)*THICKNESS*math.tan(math.radians(30))/MM
        visible = np.logical_or.reduce([
            shift(mask, q*dx, q*dy) for q in np.linspace(low,high,5)
        ])
        result[visible] = i
    return result


def pixel_polygon(mask):
    rects = []
    for y,row in enumerate(mask):
        breaks = np.flatnonzero(np.diff(np.r_[False,row,False]))
        rects.extend(box(a,y,b,y+1) for a,b in zip(breaks[::2],breaks[1::2]))
    return union_all(rects).simplify(.35, preserve_topology=True)


def extrude(polygon, height):
    triangles = np.array([np.asarray(t.exterior.coords)[:3]
                          for t in constrained_delaunay_triangles(polygon).geoms])
    vertices, inverse = np.unique(triangles.reshape(-1,2), axis=0, return_inverse=True)
    return trimesh.creation.extrude_triangulation(vertices, inverse.reshape(-1,3), height)


def layer_mesh(mask):
    polygon = translate(scale(pixel_polygon(mask), xfact=MM, yfact=-MM, origin=(0,0)), yoff=186)
    assert polygon.geom_type == "Polygon" and polygon.is_valid
    mesh = extrude(polygon, THICKNESS)
    if not mesh.is_volume:
        polygon = polygon.buffer(-.008,join_style=2)
        assert polygon.geom_type == "Polygon" and polygon.is_valid
        mesh = extrude(polygon, THICKNESS)
    return mesh


def frame_parts():
    outer = box(-3.4,-3.4,189.4,189.4)
    cavity = box(-.30,-.30,186.30,186.30)
    # The cover lands on the tray wall, leaving a ledge for removable tape.
    tray_outline = outer.difference(cavity)
    tray_sections = [(outer,0,1.6), (tray_outline,1.6,8.9)]
    cover_outer = outer
    opening = box(3,3,183,183)
    cover = extrude(cover_outer.difference(opening),1.6)
    import manifold3d
    def solid(g,z0,z1):
        m = extrude(g,z1-z0)
        m.apply_translation([0,0,z0])
        return manifold3d.Manifold(manifold3d.Mesh(np.float32(m.vertices),np.uint32(m.faces)))
    model = solid(tray_sections[0][0],0,1.61)+solid(tray_sections[1][0],1.6,8.9)
    m = model.to_mesh()
    return trimesh.Trimesh(m.vert_properties[:,:3],m.tri_verts),cover


def main():
    target = labels_from_art()
    png(CHECK/"固定六色源稿.png",target[RIM:-RIM,RIM:-RIM])
    metrics, stacks = {}, {}
    directions = [(0,0),(1,0),(-1,0),(0,1),(0,-1)]
    sheet = Image.new("RGB",(1500,324),"#fff5e5")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc",21)
    for row,mode in enumerate("A"):
        masks, added = solve(target,mode)
        stacks[mode] = masks
        check = CHECK / mode
        check.mkdir(exist_ok=True)
        rim = rim_mask()
        for i,(mask,extra) in enumerate(zip(masks,added)):
            Image.fromarray(mask.astype(np.uint8)*255).save(check/f"{i+1:02d}_实心遮罩.png")
            Image.fromarray(((~mask)&~rim).astype(np.uint8)*255).save(check/f"{i+1:02d}_开孔露底.png")
            Image.fromarray((extra & ~rim).astype(np.uint8)*255).save(check/f"{i+1:02d}_补宽.png")
        views = []
        region = np.s_[RIM:-RIM,RIM:-RIM]
        for col,direction in enumerate(directions):
            v = composite(masks,direction)[region]
            views.append(v)
            png(check/f"{col:02d}_叠合.png",v)
            caption = ("正视", "右30°", "左30°", "下30°", "上30°")[col]
            draw.text((12+300*col,8+324*row),f"{mode}   {caption}",font=font,fill="black")
            sheet.paste(Image.fromarray(PALETTE[v]).resize((288,288)),(6+300*col,35+324*row))
        rows = []
        for i,mask in enumerate(masks):
            components = cv2.connectedComponents(mask.astype(np.uint8),connectivity=4)[0]-1
            core = cv2.distanceTransform(mask.astype(np.uint8),cv2.DIST_L2,5) >= 3
            core_count = cv2.connectedComponents(core.astype(np.uint8),connectivity=4)[0]-1
            holes = (~mask).astype(np.uint8)
            n,ids,stats,_ = cv2.connectedComponentsWithStats(holes,connectivity=4)
            radius = cv2.distanceTransform(holes,cv2.DIST_L2,5)
            small_holes = sum(float(radius[ids==j].max()) < 1.5 for j in range(1,n))
            rows.append(dict(layer=NAMES[i],components=components,components_after_075mm_inset=core_count,
                             holes=n-1,holes_below_075mm_diameter_proxy=small_holes,
                             area_mm2=float(mask.sum()*MM**2)))
        metrics[mode] = dict(layers=rows,volume_cm3=sum(r["area_mm2"] for r in rows)*THICKNESS/1000,
                             front_changed_percent=float(np.mean(views[0]!=target[region])*100),
                             angle_changed_percent=[float(np.mean(v!=views[0])*100) for v in views])
    sheet.save(CHECK/"正斜视.png")
    selected = "A"
    final_masks = stacks[selected]
    final = composite(final_masks)
    png(CHECK/"最终正视.png",final[RIM:-RIM,RIM:-RIM])
    reference = Image.open(WORK/"reference.png").convert("RGB").crop(JOB["reference_crop"])
    art = Image.open(WORK/"生图.png").convert("RGB").crop(JOB["art_crop"])
    comparison = Image.new("RGB", (1664, 448), "#fff5e5")
    caption = ImageDraw.Draw(comparison)
    proof = (("原设计", reference), ("生图输出", art),
             ("固定六色源稿", Image.fromarray(PALETTE[target[region]])),
             ("分片正视", Image.fromarray(PALETTE[final[region]])))
    for col, (name, image) in enumerate(proof):
        x = 8 + 416 * col
        caption.text((x, 7), name, font=font, fill="black")
        comparison.paste(image.resize((400,400),Image.Resampling.LANCZOS),(x,36))
    comparison.save(CHECK/"开跑前四图对照.png")
    changed = metrics[selected]["front_changed_percent"]
    metrics.update(selected=selected, passes_front_drift_check=changed <= 3.0)
    report = CHECK/"结构对比.json"
    visible = []
    for i,name in enumerate(NAMES):
        mask = (target[region] == i).astype(np.uint8)
        _, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=4)
        areas = stats[1:, cv2.CC_STAT_AREA]
        visible.append(dict(layer=name, percent=float(mask.mean()*100),
                            regions=len(areas), largest_share=float(areas.max()/areas.sum()) if len(areas) else 0,
                            edge_pixels=int(mask[0].sum()+mask[-1].sum()+mask[1:-1,0].sum()+mask[1:-1,-1].sum())))
    metrics["visible_colors"] = visible
    report.write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding="utf8")
    if os.environ.get("PAPERCUT_REVIEW_ONLY") == "1":
        print(f"Front drift: {changed:.2f}% (limit 3%). Review: {comparison.size}")
        return
    if changed > 3.0:
        raise SystemExit(f"Front drift {changed:.2f}% exceeds 3%. Review artwork and visible connections before slicing.")
    Image.fromarray((~np.any(final_masks,axis=0)).astype(np.uint8)*255).save(CHECK/"真通孔.png")
    items = [(f"{i+1:02d}_{name}",[(i,layer_mesh(final_masks[i]),name)]) for i,name in enumerate(NAMES)]
    legacy_box = os.environ.get("PAPERCUT_LEGACY_BOX") == "1"
    if legacy_box:
        tray,cover = frame_parts()
        items.extend([("07_红色托框",[(2,tray,"托框")]),("08_红色压边",[(2,cover,"压边")])])
    info = []
    for name,parts in items:
        color,mesh,_ = parts[0]
        edges = np.bincount(mesh.edges_unique_inverse)
        assert mesh.is_volume and len(mesh.split()) == 1, name
        info.append(dict(name=name,dimensions_mm=mesh.extents.tolist(), faces=len(mesh.faces),
                         boundary_edges=int((edges==1).sum()),non_manifold_edges=int((edges!=2).sum()),
                         signed_volume_mm3=mesh.volume,solid_components=1))
    metrics.update(selected=selected,mesh=info,true_through_pixels=0,cavity_xy_clearance_per_side_mm=.3,
                   assembly_offsets_z_mm=([1.6+i*1.2 for i in range(6)]+[0,8.9] if legacy_box
                                          else [2.4+i*1.2 for i in range(6)]))
    (CHECK/"结构对比.json").write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding="utf8")
    with (WORK/"print_meshes.pkl").open("wb") as f:
        pickle.dump(items,f)
    print("Selected",selected,metrics["A"]["front_changed_percent"])


if __name__ == "__main__":
    main()
