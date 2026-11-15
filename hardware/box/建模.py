from pathlib import Path
import json
import manifold3d as mf
import numpy as np
from shapely import Polygon, box, constrained_delaunay_triangles, union_all
from shapely.affinity import scale
import trimesh

work=Path(__file__).resolve().parent
def solid(shape,z0,z1):
    result=mf.Manifold()
    polys=[shape] if shape.geom_type=="Polygon" else shape.geoms
    for poly in polys:
        tris=np.array([np.asarray(t.exterior.coords)[:3] for t in constrained_delaunay_triangles(poly).geoms])
        vertices,indices=np.unique(tris.reshape(-1,2),axis=0,return_inverse=True)
        m=trimesh.creation.extrude_triangulation(vertices,indices.reshape(-1,3),z1-z0)
        m.apply_translation((0,0,z0))
        result+=mf.Manifold(mf.Mesh(np.float32(m.vertices),np.uint32(m.faces)))
    return result

def export(model,stem,flip=False):
    m=model.to_mesh()
    mesh=trimesh.Trimesh(m.vert_properties[:,:3],m.tri_verts)
    assert mesh.is_volume and len(mesh.split())==1
    if flip:
        mesh.apply_transform(np.array([[1,0,0,0],[0,-1,0,0],[0,0,-1,11.8],[0,0,0,1]]))
    assert abs(mesh.bounds[0,2])<.002
    mesh.export(work/f"{stem}.stl")
    return dict(part=stem,bounds_mm=mesh.bounds.tolist(),faces=len(mesh.faces),volume_mm3=mesh.volume)

tray_outline=box(-4,-4,190,190)
cavity=box(-.60,-.60,186.60,186.60)
entry=box(-.90,-.90,186.90,186.90)
cover_outline=box(-6.7,-6.7,192.7,192.7)
socket=box(-4.30,-4.30,190.30,190.30)
aperture=box(3,3,183,183)
# Three keys per edge. Local clearance is 0.01 mm per flank.
upper=union_all([Polygon([(x-3,190.5),(x+3,190.5),(x+3,189.95),
                         (x+4.35,188.50),(x-4.35,188.50),(x-3,189.95)])
                for x in (43,93,143)])
keys=upper.union(scale(upper,xfact=1,yfact=-1,origin=(0,93)))
assert len(keys.geoms)==6
pockets=keys.buffer(.01,join_style=2)
assert pockets.distance(cavity)>1.8
tray=solid(tray_outline,0,2.4)
tray+=solid(tray_outline.difference(cavity),2.39,9.4)
tray+=solid(tray_outline.difference(entry),9.39,10)
tray-=solid(pockets,4.8,10.1)
cover=solid(cover_outline.difference(socket),5,10.02)
cover+=solid(cover_outline.difference(aperture),10,11.8)
cover-=solid(box(-.88,-.88,186.88,186.88),9.95,10.30)
cover+=solid(keys,5.4,10.15)
assert (tray^cover).volume()<.001
gauge=solid(box(0,0,186,186),2.4,9.6)
assert (gauge^tray).volume()<.001 and (gauge^cover).volume()<.001
rows=[export(tray,"tray"),export(cover,"lid",True)]
assert np.allclose(np.ptp(rows[0]["bounds_mm"],axis=0),[194,194,10],atol=.001)
assert np.allclose(np.ptp(rows[1]["bounds_mm"],axis=0),[199.4,199.4,6.8],atol=.001)
names={"tray":"01_底托_燕尾槽","lid":"02_盖框_燕尾键"}
recipe=dict(project_root="../..",project_name="祥羊上下六键两丝",template_3mf="配置.3mf",
 expected_printer_model="Bambu Lab P1S",expected_nozzle_mm=.4,
 settings=dict(filament_colour=["#BC1219"],enable_support="0",enable_prime_tower="0",brim_type="no_brim",skirt_loops="0"),
 bed_margin_mm=5,part_gap_mm=4,parts=[dict(id=k,file=k+".stl",quantity=1) for k in names],
 plates=[dict(name=name,items=[dict(part=k,name=name,center_mm=[128,128])]) for k,name in names.items()])
(work/"plates.json").write_text(json.dumps(recipe,ensure_ascii=False,indent=2),encoding="utf8")
(work/"几何核对.json").write_text(json.dumps(dict(parts=rows,gap_total_mm=.02,keys_per_edge=3,overall_mm=[199.4,199.4,11.8],
 aperture_mm=180,cavity_mm=187.2,stack_headroom_mm=.7),ensure_ascii=False,indent=2),encoding="utf8")
