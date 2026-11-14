"""Production-only, single-filament STL -> editable Bambu multi-plate project.

The output is published only after native Bambu re-export and geometry verification.
No GUI input, slicing, model repair, automatic orientation, or printer communication.
"""
from pathlib import Path
from collections import Counter
import argparse, datetime, hashlib, json, math, os, shutil, subprocess, tempfile, uuid, zipfile
import xml.etree.ElementTree as ET
import numpy as np
import trimesh
from scipy.spatial import cKDTree
from shapely.geometry import Polygon, box

NS='http://schemas.microsoft.com/3dmanufacturing/core/2015/02'
PROD='http://schemas.microsoft.com/3dmanufacturing/production/2015/06'
REL='http://schemas.openxmlformats.org/package/2006/relationships'
ET.register_namespace('',NS);ET.register_namespace('p',PROD)
tag=lambda n:'{'+NS+'}'+n
uid=lambda:str(uuid.uuid4())
def dump(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
def xml(root):return ET.tostring(root,encoding='utf-8',xml_declaration=True)
def metadata(parent,key,value):return ET.SubElement(parent,'metadata',key=key,value=str(value))
def require(condition,message):
    if not condition:raise ValueError(message)
def inside(path,root):
    require(path.is_relative_to(root),f'Path must stay inside this project: {path}')
    return path
def matrix(text=None):
    a=np.eye(4)
    if text:a[:3,:4]=np.asarray(list(map(float,text.split()))).reshape(4,3).T
    return a
def points(value):
    return [list(map(float,str(p).split('x'))) for p in value]

def prepare(manifest_path):
    recipe=json.loads(manifest_path.read_text(encoding='utf-8-sig'));base=manifest_path.parent
    root=(base/recipe['project_root']).resolve();require(root.is_dir(),'project_root does not exist')
    inside(manifest_path,root)
    template=inside((base/recipe['template_3mf']).resolve(),root)
    with zipfile.ZipFile(template) as z:
        require(z.testzip() is None,'Template ZIP CRC failed')
        require('Metadata/model_settings.config' in z.namelist(),'Template is not a native editable Bambu project')
        cfg=json.loads(z.read('Metadata/project_settings.config'))
    # The recipe may adjust print process fields and filament display colors, never machine scripts.
    allowed_special={'filament_colour','print_settings_id'}
    overrides=recipe.get('settings',{})
    for key in overrides:
        require(key in cfg,f'Unknown template setting: {key}')
        require(not key.endswith('_gcode') and key not in {'printer_model','printer_settings_id','nozzle_diameter','printable_area','bed_exclude_area'},f'Use an actual matching machine template instead of overriding {key}')
        require(not key.startswith(('machine_','extruder_','filament_')) or key in allowed_special,f'Hardware/material calibration override unsupported: {key}')
    cfg.update(overrides)
    require(cfg.get('printer_model')==recipe['expected_printer_model'],'Printer does not match recipe')
    nozzle=cfg.get('nozzle_diameter',[])
    require(len(nozzle)==1 and abs(float(nozzle[0])-float(recipe['expected_nozzle_mm']))<1e-8,'Nozzle does not match recipe')
    require(len(cfg.get('filament_colour',[]))==1,'Only single-filament layouts are supported; preserve colored assembly projects separately')
    require(cfg.get('print_sequence')=='by layer','Sequential/by-object printing requires a separate clearance workflow')
    bed=Polygon(points(cfg['printable_area']));require(bed.is_valid and not bed.is_empty,'Invalid printable_area')
    xmin,ymin,xmax,ymax=bed.bounds;width=xmax-xmin;depth=ymax-ymin
    # Native 02.08.02.61 grid. A native re-export plus world-space checks detects layout drift.
    gap_ratio=float(recipe.get('plate_gap_ratio',.2));require(gap_ratio>=0,'Invalid plate gap')
    margin=float(recipe.get('bed_margin_mm',5));gap=float(recipe.get('part_gap_mm',4))
    require(margin>=0 and gap>=0,'Negative model spacing is not allowed')
    exclusion=Polygon(points(cfg['bed_exclude_area'])) if cfg.get('bed_exclude_area') else Polygon()
    meshes={};paths={};specs={}
    for part in recipe['parts']:
        pid=part['id'];require(pid not in specs,f'Duplicate part id: {pid}')
        require(isinstance(part['quantity'],int) and not isinstance(part['quantity'],bool) and part['quantity']>0,f'Explicit positive quantity required: {pid}')
        path=inside((base/part['file']).resolve(),root);require(path.suffix.lower()=='.stl',f'Only explicit print-oriented STL inputs are supported: {path}')
        m=trimesh.load_mesh(path);require(isinstance(m,trimesh.Trimesh) and m.is_watertight and m.is_winding_consistent and m.volume>0,f'Fix the source mesh in its modeling task first: {pid}')
        meshes[pid]=m;paths[pid]=path;specs[pid]=part
    plates=recipe['plates'];require(0<len(plates)<=36,'Plate count must be between 1 and 36')
    require(all(p['items'] for p in plates),'Empty plates are not included in a production package')
    actual=Counter(i['part'] for p in plates for i in p['items']);wanted=Counter({k:v['quantity'] for k,v in specs.items()})
    require(actual==wanted,f'Production quantities differ: placements={dict(actual)}, expected={dict(wanted)}')
    cols=math.ceil(math.sqrt(len(plates)));records=[];names=set()
    for pi,plate in enumerate(plates):
        origin=np.array([(pi%cols)*width*(1+gap_ratio),-(pi//cols)*depth*(1+gap_ratio),0.]);occupied=[]
        for item in plate['items']:
            pid=item['part'];m=meshes[pid];name=item['name'];require(name and name not in names,f'Every placed object needs a unique name: {name}');names.add(name)
            center=np.asarray(item['center_mm'],float);require(center.shape==(2,) and np.isfinite(center).all(),'center_mm requires finite XY coordinates')
            delta=np.array([center[0],center[1],0.])-np.array([*m.bounds.mean(axis=0)[:2],m.bounds[0,2]])+origin
            bounds=m.bounds+delta;local=bounds-origin;footprint=box(*local[0,:2],*local[1,:2])
            require(local[1,2]<=float(cfg['printable_height']),f'Model exceeds printer height: {name}')
            require(bed.buffer(-margin).covers(footprint),f'Model exceeds bed margin: {name}')
            require(exclusion.is_empty or not exclusion.intersects(footprint),f'Model intersects bed exclusion: {name}')
            require(all(footprint.distance(o)>=gap for o in occupied),f'Model spacing failed on plate {pi+1}: {name}')
            occupied.append(footprint)
            records.append({'part':pid,'name':name,'plate':pi+1,'plate_name':plate['name'],'translation':delta.tolist(),'bounds_mm':bounds.tolist(),'faces':len(m.faces),'dimensions_mm':m.extents.tolist(),'source_sha256':hashlib.sha256(paths[pid].read_bytes()).hexdigest()})
    return recipe,root,cfg,meshes,paths,records

def construct(path,recipe,cfg,meshes,records):
    model=ET.Element(tag('model'),unit='millimeter',attrib={'xml:lang':'zh-CN','requiredextensions':'p'})
    for key,value in [('Application','BambuStudio-02.08.02.61'),('BambuStudio:3mfVersion','1'),('Title',recipe['project_name']),('CreationDate',datetime.date.today().isoformat())]:ET.SubElement(model,tag('metadata'),name=key).text=value
    resources=ET.SubElement(model,tag('resources'));build=ET.SubElement(model,tag('build'),attrib={'{'+PROD+'}UUID':uid()});settings=ET.Element('config')
    mesh_files={};ids={pid:i+1 for i,pid in enumerate(meshes)}
    # IDs are unique across child files AND disjoint from parent object IDs.
    for pid,m in meshes.items():
        ident=ids[pid];r=ET.Element(tag('model'),unit='millimeter');rs=ET.SubElement(r,tag('resources'));o=ET.SubElement(rs,tag('object'),id=str(ident),type='model');me=ET.SubElement(o,tag('mesh'));vs=ET.SubElement(me,tag('vertices'));ts=ET.SubElement(me,tag('triangles'))
        for x,y,z in m.vertices:ET.SubElement(vs,tag('vertex'),x=f'{x:.7f}',y=f'{y:.7f}',z=f'{z:.7f}')
        for a,b,c in m.faces:ET.SubElement(ts,tag('triangle'),v1=str(a),v2=str(b),v3=str(c))
        mesh_files[pid]=(f'3D/Objects/object_{ident}.model',xml(r))
    for i,rec in enumerate(records):
        oid=len(meshes)+100+i;rec['input_object_id']=oid;pid=rec['part'];child=ids[pid];model_path=mesh_files[pid][0]
        ob=ET.SubElement(resources,tag('object'),id=str(oid),type='model',name=rec['name'],attrib={'{'+PROD+'}UUID':uid()});cs=ET.SubElement(ob,tag('components'));ET.SubElement(cs,tag('component'),objectid=str(child),transform='1 0 0 0 1 0 0 0 1 0 0 0',attrib={'{'+PROD+'}path':'/'+model_path,'{'+PROD+'}UUID':uid()})
        ET.SubElement(build,tag('item'),objectid=str(oid),printable='1',transform='1 0 0 0 1 0 0 0 1 '+' '.join(f'{v:.7f}' for v in rec['translation']),attrib={'{'+PROD+'}UUID':uid()})
        o=ET.SubElement(settings,'object',id=str(oid));metadata(o,'name',rec['name']);metadata(o,'extruder',1);ET.SubElement(o,'metadata',face_count=str(rec['faces']))
        p=ET.SubElement(o,'part',id=str(child),subtype='normal_part',uuid=uid());metadata(p,'name',rec['name']);metadata(p,'matrix','1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1')
        for axis in 'xyz':metadata(p,'source_offset_'+axis,0)
        ET.SubElement(p,'mesh_stat',face_count=str(rec['faces']),edges_fixed='0',degenerate_facets='0',facets_removed='0',facets_reversed='0',backwards_edges='0')
    for pi,plate in enumerate(recipe['plates']):
        p=ET.SubElement(settings,'plate');metadata(p,'plater_id',pi+1);metadata(p,'plater_name',plate['name']);metadata(p,'locked','false');metadata(p,'filament_map_mode','Auto For Flush');metadata(p,'filament_maps','1');metadata(p,'filament_volume_maps','0')
        for i,rec in enumerate(records):
            if rec['plate']!=pi+1:continue
            ins=ET.SubElement(p,'model_instance');metadata(ins,'object_id',rec['input_object_id']);metadata(ins,'instance_id',0);metadata(ins,'identify_id',1000+i)
    ET.SubElement(settings,'assemble')
    relationships=ET.Element('Relationships',xmlns=REL)
    for i,(name,_) in enumerate(mesh_files.values(),1):ET.SubElement(relationships,'Relationship',Target='/'+name,Id=f'rel-{i}',Type='http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel')
    top=ET.Element('Relationships',xmlns=REL);ET.SubElement(top,'Relationship',Target='/3D/3dmodel.model',Id='rel-1',Type='http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel')
    types=ET.Element('Types',xmlns='http://schemas.openxmlformats.org/package/2006/content-types')
    for ext,ctype in [('rels','application/vnd.openxmlformats-package.relationships+xml'),('model','application/vnd.ms-package.3dmanufacturing-3dmodel+xml')]:ET.SubElement(types,'Default',Extension=ext,ContentType=ctype)
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for name,body in [('[Content_Types].xml',xml(types)),('_rels/.rels',xml(top)),('3D/3dmodel.model',xml(model)),('3D/_rels/3dmodel.model.rels',xml(relationships)),('Metadata/model_settings.config',xml(settings)),('Metadata/project_settings.config',json.dumps(cfg,ensure_ascii=False)),('Metadata/filament_sequence.json',json.dumps({f'plate_{i+1}':{'sequence':[1],'nozzle_sequence':[0],'optimal_assignment':[0]} for i in range(len(recipe['plates']))}))]:z.writestr(name,body)
        for name,body in mesh_files.values():z.writestr(name,body)

def verify(path,recipe,cfg,meshes,records):
    expected={r['name']:r for r in records};checks=[]
    with zipfile.ZipFile(path) as z:
        require(z.testzip() is None,'Native output ZIP CRC failed');require(not any(n.endswith('.gcode') for n in z.namelist()),'Stale G-code in an unsliced project')
        settings=ET.fromstring(z.read('Metadata/model_settings.config'));plates=settings.findall('plate');objects=settings.findall('object')
        require(len(plates)==len(recipe['plates']) and len(objects)==len(records),'Native output plate/object count changed')
        namebyid={o.get('id'):next(m.get('value') for m in o.findall('metadata') if m.get('key')=='name') for o in objects}
        require(Counter(namebyid.values())==Counter(expected.keys()),'Native output object names/quantities changed')
        # Check plate membership by names, not just the total number of plates.
        for i,p in enumerate(plates):
            members=[next(m.get('value') for m in ins.findall('metadata') if m.get('key')=='object_id') for ins in p.findall('model_instance')]
            require(Counter(namebyid[k] for k in members)==Counter(r['name'] for r in records if r['plate']==i+1),f'Plate {i+1} membership changed')
        actualcfg=json.loads(z.read('Metadata/project_settings.config'))
        for key in set(recipe.get('settings',{}))|{'printer_model','printer_settings_id','nozzle_diameter','filament_colour','printable_area'}:require(actualcfg.get(key)==cfg.get(key),f'Native setting changed: {key}')
        root=ET.fromstring(z.read('3D/3dmodel.model'));parents={o.get('id'):o for o in root.find(tag('resources'))};cache={};build=root.find(tag('build'))
        require(len(build)==len(records) and all(i.get('printable','1')=='1' for i in build),'Unexpected build items or disabled production parts')
        def geometry(model_path,oid):
            if model_path not in cache:
                r=ET.fromstring(z.read(model_path));cache[model_path]={}
                for ob in r.find(tag('resources')):
                    me=ob.find(tag('mesh'))
                    if me is None:continue
                    v=np.asarray([[float(a.get(k)) for k in ('x','y','z')] for a in me.find(tag('vertices'))]);f=np.asarray([[int(a.get(k)) for k in ('v1','v2','v3')] for a in me.find(tag('triangles'))]);cache[model_path][ob.get('id')]=(v,f)
            return cache[model_path][oid]
        for item in build:
            oid=item.get('objectid');name=namebyid[oid];rec=expected[name];src=meshes[rec['part']];parts=[];faces=0;world_matrix=matrix(item.get('transform'))
            for cp in parents[oid].find(tag('components')):
                v,f=geometry(cp.get('{'+PROD+'}path').lstrip('/'),cp.get('objectid'));m=world_matrix@matrix(cp.get('transform'));parts.append(v@m[:3,:3].T+m[:3,3]);faces+=len(f)
            v=np.vstack(parts);require(faces==rec['faces'],f'Geometry face count changed: {name}')
            want=src.vertices+np.asarray(rec['translation']);bbox=np.vstack([v.min(axis=0),v.max(axis=0)]);err=float(np.abs(bbox-np.asarray(rec['bounds_mm'])).max());require(err<.002,f'Pose, size or plate placement changed: {name}')
            # AABB+face count alone can miss wrong meshes with similar dimensions.
            a=float(cKDTree(v).query(want)[0].max());b=float(cKDTree(want).query(v)[0].max());point_error=max(a,b)
            require(point_error<.002,f'Actual vertex geometry changed: {name}')
            checks.append({'name':name,'part':rec['part'],'plate':rec['plate'],'faces':faces,'max_bbox_error_mm':err,'max_bidirectional_vertex_error_mm':point_error})
    return {'status':'verified_editable_project_not_sliced','plates':len(recipe['plates']),'production_instances':len(records),'unique_source_meshes':len(meshes),'plate_item_counts':[len(p['items']) for p in recipe['plates']],'checks':checks,'geometry_tolerance_mm':.002,'gui_inspection':False,'slicing_performed':False,'physical_print_performed':False,'limits':['Model bounds only; added brim/support paths not checked without slicing.','No full wall-thickness, self-intersection, paint or assembly fit validation.']}

def run(args):
    manifest=Path(args.manifest).resolve();recipe,project,cfg,meshes,sources,records=prepare(manifest)
    work=inside(Path(args.work).resolve(),project);checks=inside(Path(args.checks).resolve(),project);out=inside(Path(args.out).resolve(),project)
    require(out.suffix.lower()=='.3mf','Output must use .3mf');require(not out.exists(),'Refusing to overwrite a deliverable')
    require(work!=checks and not work.is_relative_to(checks) and not checks.is_relative_to(work),'Work and check directories must be separate')
    require(not work.exists() and not checks.exists(),'Use fresh numbered work/check directories')
    work.mkdir(parents=True);checks.mkdir(parents=True);dump(checks/'production_plan.json',{'manifest':str(manifest),'records':records,'expected_quantities':{p['id']:p['quantity'] for p in recipe['parts']}})
    construct(work/'input.3mf',recipe,cfg,meshes,records)
    # Tool-owned ASCII staging cache avoids the native Windows CLI non-ASCII path bug.
    cache=Path(os.environ.get('LOCALAPPDATA',tempfile.gettempdir()))/'BambuAIToolchain';cache.mkdir(exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='plate_project_',dir=cache));shutil.copy2(work/'input.3mf',stage/'input.3mf');nativeout=stage/'out';nativeout.mkdir()
    cmd=[str(Path(args.bambu_exe).resolve()),'--arrange','0','--debug','3','--outputdir',str(nativeout),'--export-3mf','project.3mf',str(stage/'input.3mf')];dump(checks/'native_command.json',cmd)
    with (checks/'native.log').open('wb') as log:r=subprocess.run(cmd,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=args.timeout)
    require(r.returncode==0 and (nativeout/'project.3mf').exists(),f'Native Bambu export failed ({r.returncode}); see {checks}')
    candidate=work/'native_candidate.3mf';shutil.copy2(nativeout/'project.3mf',candidate)
    report=verify(candidate,recipe,cfg,meshes,records);report.update({'native_exit_code':r.returncode,'printer':cfg['printer_model'],'nozzle_mm':cfg['nozzle_diameter'],'source_sha256':{k:hashlib.sha256(p.read_bytes()).hexdigest() for k,p in sources.items()},'output_sha256':hashlib.sha256(candidate.read_bytes()).hexdigest()})
    dump(checks/'verification.json',report)
    # Exclusive final publication: failed validation never creates a deliverable.
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('xb') as f,candidate.open('rb') as source:shutil.copyfileobj(source,f)
    return {'file':str(out),'plates':report['plates'],'production_instances':len(records),'verified':True,'sliced':False}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',required=True);p.add_argument('--work',required=True);p.add_argument('--checks',required=True);p.add_argument('--out',required=True);p.add_argument('--bambu-exe',default=r'C:\Program Files\Bambu Studio\bambu-studio.exe');p.add_argument('--timeout',type=int,default=240)
    args=p.parse_args()
    try:print(json.dumps(run(args),ensure_ascii=False))
    except Exception as exc:print(json.dumps({'error':str(exc)},ensure_ascii=False));raise SystemExit(1)
if __name__=='__main__':main()
