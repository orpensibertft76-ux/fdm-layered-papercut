from pathlib import Path
from io import BytesIO
import trimesh
import json
import math
import os
import pickle
import shutil
import subprocess
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET
import numpy as np
from scipy.spatial import cKDTree

from build_dragon import WORK, CHECK, COLORS, JOB
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'Bambu_Toolchain'))
from plate_project import tag,PROD,REL,uid,xml,metadata,matrix,dump
EXE=Path(os.environ["PAPERCUT_BAMBU"])
with (WORK/'print_meshes.pkl').open('rb') as f:
    source=pickle.load(f)
PNAMES=[n for n,_ in source]
assert len(PNAMES) in (6,8)
N=len(COLORS)
P='{'+PROD+'}'

cfg=json.loads((Path(__file__).with_name('P1S配置来源.json')).read_text(encoding='utf8'))
# The reference was composed and successfully sliced with four identical PLA profiles.
# Its material arrays carry one or more values per slot. Keep the per-slot blocks.
filament_prefixes=('filament_','nozzle_temperature','fan_','cool_','hot_plate','textured_plate','eng_plate',
    'supertack_plate','chamber_','slow_down','close_fan','close_additional','full_fan','first_x_',
    'additional_','activate_air','complete_print','during_print','overhang_fan','counter_','hole_',
    'impact_strength','required_nozzle','default_filament','pre_start_fan','reduce_fan','temperature_vitrification',
    'circle_compensation','diameter_limit','cooling_','volumetric_speed_coefficients',
    'override_process_overhang_speed','retraction_distances_when_ec','long_retractions_when_ec','fins_extrude')
for key,value in list(cfg.items()):
    if isinstance(value,list) and len(value)%4==0 and value and key.startswith(filament_prefixes):
        cfg[key]=value[:len(value)//4]*N
cfg['filament_self_index']=[str(i+1) for i in range(N) for _ in range(2)]
cfg['filament_multi_colour']=COLORS
cfg['different_settings_to_system']=['enable_prime_tower;filament_colour;filament_multi_colour']+['']*N
cfg.pop('filament_map',None)
cfg.pop('filament_map_2',None)
cfg['layer_height']='0.2'
cfg['initial_layer_print_height']='0.2'
cfg['flush_into_support']='0'
cfg['no_slow_down_for_cooling_on_outwalls']=['0']*N
cfg.update(filament_colour=COLORS,
           flush_volumes_vector=['140']*(N*2),flush_volumes_matrix=[
             '0' if i==j else ('480' if j==5 and i in [0,1,2] else '280')
             for i in range(N) for j in range(N)],enable_support='0',enforce_support_layers='0',
           wall_generator='arachne',brim_type='no_brim',skirt_loops='0',enable_prime_tower='0',
           prime_tower_width='25',wipe_tower_x=['10']*len(PNAMES),wipe_tower_y=['108']*len(PNAMES),
           sparse_infill_density='15%',top_shell_layers='4',bottom_shell_layers='4',
           print_settings_id='0.20mm Standard @BBL P1S')

assert all(m.is_volume and len(m.split())==1 for _,parts in source for _,m,_ in parts)
model=ET.Element(tag('model'),unit='millimeter',attrib={'xml:lang':'zh-CN','requiredextensions':'p'})
for k,v in [('Application','BambuStudio-02.08.02.61'),('BambuStudio:3mfVersion','1'),('Title',JOB['name'])]:
    ET.SubElement(model,tag('metadata'),name=k).text=v
resources=ET.SubElement(model,tag('resources'))
build=ET.SubElement(model,tag('build'),attrib={P+'UUID':uid()})
settings=ET.Element('config')
parts_model=ET.Element(tag('model'),unit='millimeter')
parts_resources=ET.SubElement(parts_model,tag('resources'))
payload={}
expected={}
used=[set() for _ in PNAMES]
part_id=0
plate_count=len(PNAMES)
cols=math.ceil(math.sqrt(plate_count))
for i,(name,parts) in enumerate(source):
    plate=int(name[:2])-1
    origin=np.array([(plate%cols)*307.2,-(plate//cols)*307.2,0.])
    mesh=parts[0][1]
    delta=origin+np.array([128,128,0.])-np.array([*mesh.bounds.mean(axis=0)[:2],mesh.bounds[0,2]])
    local=mesh.bounds+delta-origin
    assert abs(local[0,2])<1e-6 and local[0,0]>=18 and local[0,1]>=28
    oid=1000+i
    obj=ET.SubElement(resources,tag('object'),id=str(oid),type='model',name=name,attrib={P+'UUID':uid()})
    components=ET.SubElement(obj,tag('components'))
    ET.SubElement(build,tag('item'),objectid=str(oid),printable='1',
                  transform='1 0 0 0 1 0 0 0 1 '+' '.join(f'{v:.7f}' for v in delta),attrib={P+'UUID':uid()})
    o=ET.SubElement(settings,'object',id=str(oid))
    metadata(o,'name',name)
    metadata(o,'extruder',parts[0][0]+1)
    ET.SubElement(o,'metadata',face_count=str(sum(len(m.faces) for _,m,_ in parts)))
    record={}
    for j,(color,m,label) in enumerate(parts):
        used[plate].add(color+1)
        part_id+=1
        label=f'{j+1:02} {label}'
        record[label]=(color+1,m)
        object_path=f'3D/Objects/part_{part_id}.model'
        ET.SubElement(components,tag('component'),objectid=str(part_id),transform='1 0 0 0 1 0 0 0 1 0 0 0',
                      attrib={P+'path':'/'+object_path,P+'UUID':uid()})
        p=ET.SubElement(o,'part',id=str(part_id),subtype='normal_part',uuid=uid())
        metadata(p,'name',label)
        metadata(p,'extruder',color+1)
        metadata(p,'matrix','1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1')
        for axis in 'xyz':metadata(p,'source_offset_'+axis,0)
        ET.SubElement(p,'mesh_stat',face_count=str(len(m.faces)),edges_fixed='0',degenerate_facets='0',
                      facets_removed='0',facets_reversed='0',backwards_edges='0')
        part_root=ET.Element(tag('model'),unit='millimeter')
        geom=ET.SubElement(ET.SubElement(part_root,tag('resources')),tag('object'),id=str(part_id),type='model')
        me=ET.SubElement(geom,tag('mesh')); vs=ET.SubElement(me,tag('vertices')); ts=ET.SubElement(me,tag('triangles'))
        for x,y,z in m.vertices: ET.SubElement(vs,tag('vertex'),x=f'{x:.7f}',y=f'{y:.7f}',z=f'{z:.7f}')
        for a,b,c in m.faces: ET.SubElement(ts,tag('triangle'),v1=str(a),v2=str(b),v3=str(c))
        local=m.bounds+delta-origin
        assert (local[0,:2]>5).all() and (local[1,:2]<253).all(), (name,local)
        payload[object_path]=xml(part_root)
    expected[name]=(oid,plate,delta,record)
for pi,pname in enumerate(PNAMES):
    p=ET.SubElement(settings,'plate')
    for key,value in [('plater_id',pi+1),('plater_name',pname),('locked','false'),
                      ('filament_map_mode','Auto For Flush'),('filament_maps','1 1 1 1 1 1'),('filament_volume_maps','0 0 0 0 0 0')]:
        metadata(p,key,value)
    for name,(oid,plate,delta,record) in expected.items():
        if plate==pi:
            ins=ET.SubElement(p,'model_instance')
            for key,value in [('object_id',oid),('instance_id',0),('identify_id',oid+1000)]:
                metadata(ins,key,value)
ET.SubElement(settings,'assemble')
types=ET.Element('Types',xmlns='http://schemas.openxmlformats.org/package/2006/content-types')
for ext,ctype in [('rels','application/vnd.openxmlformats-package.relationships+xml'),('model','application/vnd.ms-package.3dmanufacturing-3dmodel+xml')]:
    ET.SubElement(types,'Default',Extension=ext,ContentType=ctype)
def relationships(*targets):
    top=ET.Element('Relationships',xmlns=REL)
    for i,target in enumerate(targets,1):
        ET.SubElement(top,'Relationship',Target='/'+target,Id=f'rel-{i}',Type='http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel')
    return xml(top)
cache=Path(os.environ['LOCALAPPDATA'])/'BambuAIToolchain'
cache.mkdir(exist_ok=True)
stage=Path(tempfile.mkdtemp(prefix='ram_',dir=cache))
with zipfile.ZipFile(stage/'input.3mf','w',zipfile.ZIP_DEFLATED) as z:
    for name,data in [
       ('[Content_Types].xml',xml(types)),('_rels/.rels',relationships('3D/3dmodel.model')),
       ('3D/3dmodel.model',xml(model)),('3D/_rels/3dmodel.model.rels',relationships(*payload)),
       ('Metadata/model_settings.config',xml(settings)),
       ('Metadata/project_settings.config',json.dumps(cfg,ensure_ascii=False))]:
        z.writestr(name,data)
    z.writestr('Metadata/filament_sequence.json',json.dumps({
        f'plate_{i+1}':{'sequence':list(range(1,N+1)),'nozzle_sequence':[0]*N,'optimal_assignment':[0]*N}
        for i,active in enumerate(used)
    }))
    for name,data in payload.items(): z.writestr(name,data)
shutil.copy2(stage/'input.3mf',WORK/'input.3mf')
out=stage/'out'; out.mkdir()
def native(args,log):
    with (CHECK/log).open('wb') as f:
        process=subprocess.run([str(EXE),*args],stdin=subprocess.DEVNULL,
                      stdout=f,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW,timeout=420)
    return process.returncode

ret=native(['--arrange','0','--debug','5','--outputdir',str(out),'--export-3mf','candidate.3mf',str(stage/'input.3mf')],'native.log')
assert ret==0 and (out/'candidate.3mf').exists(),ret
candidate=out/'candidate.3mf'


def meta(obj,key):
    node=obj.find(f"metadata[@key='{key}']")
    return node.get('value') if node is not None else None

with zipfile.ZipFile(candidate) as z:
    assert z.testzip() is None and not any(n.endswith('.gcode') for n in z.namelist())
    tree=ET.fromstring(z.read('3D/3dmodel.model'))
    sets=ET.fromstring(z.read('Metadata/model_settings.config'))
    saved=json.loads(z.read('Metadata/project_settings.config'))
    for key in ['printer_model','nozzle_diameter','filament_colour','enable_support','enable_prime_tower','layer_height','wall_generator']:
        assert saved[key]==cfg[key],(key,saved[key],cfg[key])
    assert len(sets.findall('plate'))==plate_count and len(sets.findall('object'))==len(source)
    sets_objects={o.get('id'):o for o in sets.findall('object')}
    objplate={}
    for pi,p in enumerate(sets.findall('plate')):
        found=[meta(i,'object_id') for i in p.findall('model_instance')]
        assert len(found)==1, (pi,found)
        names={meta(sets_objects[oid],'name') for oid in found}
        assert names=={n for n,(_,index,_,_) in expected.items() if index==pi},(pi,names)
        objplate.update({oid:pi for oid in found})
    res={o.get('id'):o for o in tree.find(tag('resources'))}
    cached={}
    rows=[]
    for item in tree.find(tag('build')):
        oid=item.get('objectid')
        mset=sets_objects[oid]
        name=meta(mset,'name')
        _,plate,delta,parts=expected[name]
        assert objplate[oid]==plate
        piece_map={p.get('id'):p for p in mset.findall('part')}
        for comp in res[oid].find(tag('components')):
            file=comp.get(P+'path').lstrip('/')
            if file not in cached:
                children=ET.fromstring(z.read(file)).find(tag('resources'))
                cached[file]={ob.get('id'):ob.find(tag('mesh')) for ob in children}
            pid=comp.get('objectid')
            pm=piece_map[pid]
            label=meta(pm,'name')
            expected_filament,mesh=parts[label]
            filament=meta(pm,'extruder') or meta(mset,'extruder')
            assert int(filament)==expected_filament,(name,label,filament,expected_filament)
            me=cached[file][pid]
            v=np.array([[float(a.get(k)) for k in ('x','y','z')] for a in me.find(tag('vertices'))])
            f=me.find(tag('triangles'))
            assert len(f)==len(mesh.faces),(name,label,len(f),len(mesh.faces))
            faces=np.asarray([[int(a.get(k)) for k in ('v1','v2','v3')] for a in f])
            native_mesh=trimesh.Trimesh(vertices=v,faces=faces,process=True)
            assert native_mesh.is_volume and len(native_mesh.split())==1,(name,'disconnected after re-export')
            t=matrix(item.get('transform'))@matrix(comp.get('transform'))
            actual=v@t[:3,:3].T+t[:3,3]
            want=mesh.vertices+delta
            error=max(cKDTree(actual).query(want)[0].max(),cKDTree(want).query(actual)[0].max())
            assert error<.002,(name,label,error)
            rows.append(dict(object=name,part=label,plate=plate+1,filament=expected_filament,
                             faces=len(f),dimensions_mm=mesh.extents.tolist(),max_vertex_error_mm=float(error)))
    assert len(rows)==part_id
dump(CHECK/'verification.json',dict(status='native_editable_verified',printer=cfg['printer_model'],plates=PNAMES,
     active_filaments=[sorted(s) for s in used],instances=len(source),parts=rows,physical_print=False))
print('Native readback verified.',flush=True)
destination=WORK/'native_verified.3mf'
with destination.open('xb') as f, candidate.open('rb') as original:
    shutil.copyfileobj(original,f)
print(destination,flush=True)
