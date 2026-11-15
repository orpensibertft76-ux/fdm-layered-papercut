from pathlib import Path
import json
import numpy as np
from shapely import LineString, Polygon, constrained_delaunay_triangles
import trimesh
import manifold3d


root = Path(__file__).resolve().parent
profile = [(0,7),(6,7),(4.5,10),(12.5,10),(11,7),(19,7),
           (17.5,4),(25.5,4),(24,7),(32,7),(30.5,10),(38.5,10),(37,7),(44,7)]
seam = LineString(profile)
halves = (Polygon([(0,0),(44,0),*reversed(profile)]),
          Polygon([*profile,(44,14),(0,14)]))
def solid(mesh):
    return manifold3d.Manifold(manifold3d.Mesh(
        np.asarray(mesh.vertices,np.float32),np.asarray(mesh.faces,np.uint32)))

def engrave(mesh,side,count):
    body=solid(mesh)
    for j in range(count):
        cutter=trimesh.creation.box(extents=(.9,1.9,1.2))
        cutter.apply_translation([12+j*2.5,1.8 if side=="A" else 12.2,3.0])
        body-=solid(cutter)
    result=body.to_mesh()
    return trimesh.Trimesh(result.vert_properties[:,:3],result.tri_verts)

parts, items, metrics = [], [], []
for i,gap in enumerate((.18,.16,.14,.12,.10,.08,.06,.04,.02),1):
    relief = seam.buffer(gap/2, join_style=2)
    pair = [half.difference(relief) for half in halves]
    assert pair[0].intersection(pair[1]).is_empty
    assert pair[0].union(pair[1]).bounds == (0.,0.,44.,14.)
    for side,shape in zip("AB",pair):
        assert shape.geom_type=="Polygon" and shape.is_valid
        tris=np.array([np.asarray(t.exterior.coords)[:3] for t in constrained_delaunay_triangles(shape).geoms])
        vertices,faces=np.unique(tris.reshape(-1,2),axis=0,return_inverse=True)
        mesh=trimesh.creation.extrude_triangulation(vertices,faces.reshape(-1,3),3)
        mesh=engrave(mesh,side,i)
        assert mesh.is_volume and len(mesh.split())==1
        stem=f"s{i}{side}"
        mesh.export(root/f"{stem}.stl")
        parts.append(dict(id=stem,file=stem+".stl",quantity=1))
        items.append(dict(part=stem,name=f"{i:02d} {side} 总隙 {gap:.2f} mm",center_mm=[54+73*((i-1)%3),47+62*((i-1)//3)+(side=="B")*22]))
    metrics.append(dict(mark_count=i,gap_mm=gap,assembled_mm=[44,14,3],nominal_intersection_mm2=0))
recipe=dict(project_root="../..",project_name="锯齿接缝试配",template_3mf="配置.3mf",
 expected_printer_model="Bambu Lab P1S",expected_nozzle_mm=.4,
 settings=dict(filament_colour=["#BC1219"],enable_support="0",enable_prime_tower="0",brim_type="no_brim",skirt_loops="0"),
 bed_margin_mm=5,part_gap_mm=4,parts=parts,plates=[dict(name="九档锯齿接缝",items=items)])
(root/"plates.json").write_text(json.dumps(recipe,ensure_ascii=False,indent=2),encoding="utf8")
(root/"geometry.json").write_text(json.dumps(metrics,indent=2),encoding="utf8")
