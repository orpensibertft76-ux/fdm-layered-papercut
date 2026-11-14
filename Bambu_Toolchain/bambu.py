"""Local, file-only Bambu Studio automation. Never connects to a printer."""
import argparse, hashlib, json, math, os, re, subprocess, sys, zipfile, shutil, tempfile
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np

EXE=Path(r'C:\Program Files\Bambu Studio\bambu-studio.exe')
PROFILES=EXE.parent/'resources/profiles/BBL'
NS='http://schemas.microsoft.com/3dmanufacturing/core/2015/02'
ROOT=Path(__file__).resolve().parent

def read_json(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def write_json(p,d):Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf8')
def fresh(p):
 p=Path(p).resolve()
 if p.exists():raise ValueError(f'Output already exists: {p}')
 p.parent.mkdir(parents=True,exist_ok=True)
 return p
def flatten(kind,name,seen=()):
 if name in seen:raise ValueError('Profile inheritance cycle')
 if Path(name).name!=name:raise ValueError('Profile name must not contain a path')
 d=read_json(PROFILES/kind/(name+'.json'));r={}
 if d.get('inherits'):r.update(flatten(kind,d['inherits'],seen+(name,)))
 for n in d.get('include',[]):r.update(flatten(kind,n,seen+(name,)))
 r.update(d)
 for k in ['inherits','include']:r.pop(k,None)
 return r
def settings(path):
 p=Path(path)
 if p.suffix.lower()=='.3mf':
  with zipfile.ZipFile(p) as z:return json.loads(z.read('Metadata/project_settings.config'))
 return read_json(p)
def inspect(path):
 with zipfile.ZipFile(path) as z:
  names=z.namelist();cfg=json.loads(z.read('Metadata/project_settings.config')) if 'Metadata/project_settings.config' in names else {}
  meshes=[];paint={};plates=[]
  for n in names:
   if n.endswith('.model'):
    # Iterparse avoids a full XML tree for high-resolution STLs.
    count=0;marks={}
    with z.open(n) as f:
     for _,e in ET.iterparse(f,events=('end',)):
      if e.tag.endswith('}triangle'):
       count+=1
       if e.get('paint_supports'):marks[e.get('paint_supports')]=marks.get(e.get('paint_supports'),0)+1
      e.clear()
    if count:meshes.append({'entry':n,'triangles':count});paint[n]=marks
   if n.endswith('.gcode'):
    h={};features={};feature='';feed=0.;speeds={};layers=0
    with z.open(n) as f:
     for raw in f:
      s=raw.decode('utf8','replace').strip()
      if s.startswith('; CONFIG_BLOCK_START'):pass
      if s.startswith('; FEATURE:'):feature=s.split(':',1)[1].strip();features[feature]=features.get(feature,0)+1
      if s.startswith('; Z_HEIGHT:'):layers+=1
      if s.startswith('; ') and any(t in s for t in ['model printing time:','total filament weight','max_z_height:']):h[s.split(':',1)[0][2:]]=s.split(':',1)[1].strip()
      if re.match(r'G[0123] ',s):
       fm=re.search(r'\bF([\d.]+)',s)
       if fm:feed=float(fm[1])/60
       em=re.search(r'\bE([\d.]+)',s)
       if feature in ['Support','Support interface'] and em and float(em[1])>0 and re.search(r'\b[XY]',s):
        v=speeds.setdefault(feature,{'segments':0,'min_command_mm_s':feed,'max_command_mm_s':feed});v['segments']+=1;v['min_command_mm_s']=min(v['min_command_mm_s'],feed);v['max_command_mm_s']=max(v['max_command_mm_s'],feed)
    plates.append({'entry':n,'summary':h,'layer_events':layers,'features':features,'support_command_speeds':speeds})
  return {'file':str(Path(path).resolve()),'editable_mesh':bool(meshes),'meshes':meshes,'paint':paint,'plates':plates,'settings':{k:v for k,v in cfg.items() if k.startswith(('support_','tree_support_')) or k in ['enable_support','printer_model','nozzle_diameter','layer_height','filament_type']},'limits':['No physical failure prediction','No full layer-by-layer support coverage or collision validation','Command feed rates are not measured motion speeds']}

def stl_arrays(path):
 with open(path,'rb') as f:
  f.read(80);n=int.from_bytes(f.read(4),'little')
 if Path(path).stat().st_size!=84+50*n:raise ValueError('This importer currently requires binary STL; convert ASCII STL before use')
 a=np.memmap(path,mode='r',offset=84,dtype=np.dtype([('normal','<f4',3),('v','<f4',(3,3)),('attr','<u2')]),shape=(n,))
 vertices,index=np.unique(a['v'].reshape(-1,3),axis=0,return_inverse=True)
 return vertices,index.reshape(-1,3)

def package_stl(stl,target,regions):
 vertices,tri=stl_arrays(stl);xyz=vertices[tri];center=xyz.mean(axis=1)
 normal=np.cross(xyz[:,1]-xyz[:,0],xyz[:,2]-xyz[:,0]);length=np.linalg.norm(normal,axis=1);normal/=np.maximum(length[:,None],1e-30)
 marks=np.zeros(len(tri),dtype=np.uint8);stats=[]
 for r in regions:
  if r['mode'] not in ['enforce','block']:raise ValueError('Region mode must be enforce or block')
  lo=np.asarray(r['min'],float);hi=np.asarray(r['max'],float)
  if lo.shape!=(3,) or hi.shape!=(3,) or np.any(lo>hi):raise ValueError('Invalid region box')
  sel=np.all((center>=lo)&(center<=hi),axis=1)
  if 'normal_z_max' in r:sel &= normal[:,2]<=float(r['normal_z_max'])
  marks[sel]=4 if r['mode']=='enforce' else 8
  stats.append({'name':r.get('name','region'),'mode':r['mode'],'triangles':int(sel.sum())})
  if not sel.any():raise ValueError(f'Region selects no triangles: {r}')
 with zipfile.ZipFile(target,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=4) as z:
  z.writestr('[Content_Types].xml','<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
  z.writestr('_rels/.rels','<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
  with z.open('3D/3dmodel.model','w') as f:
   f.write(f'<?xml version="1.0"?><model unit="millimeter" xmlns="{NS}"><metadata name="Application">Local Bambu Toolchain</metadata><resources><object id="1" type="model" name="GEN_Model"><mesh><vertices>'.encode())
   for v in vertices:f.write(('<vertex x="%.9g" y="%.9g" z="%.9g"/>'%tuple(v)).encode())
   f.write(b'</vertices><triangles>')
   for t,m in zip(tri,marks):f.write(('<triangle v1="%d" v2="%d" v3="%d"%s/>'%(*t,f' paint_supports="{m}"' if m else '')).encode())
   f.write(b'</triangles></mesh></object></resources><build><item objectid="1"/></build></model>')
 return {'vertices':len(vertices),'triangles':len(tri),'dimensions_mm':(vertices.max(axis=0)-vertices.min(axis=0)).tolist(),'regions':stats,'painted_triangles':int((marks!=0).sum())}

def prepare(args):
 out=fresh(args.out);out.mkdir()
 original=settings(args.settings_from) if args.settings_from else {}
 overrides=read_json(args.overrides) if args.overrides else {}
 profiles={}
 for kind,name in [('machine',args.machine),('process',args.process),('filament',args.filament)]:
  d=flatten(kind,name)
  # Copy original values only into their matching preset category, never all categories.
  for k in list(d):
   if k in original and k not in ['name','type','from','instantiation','setting_id','inherits','version','description']:
    v=original[k]
    if kind=='filament' and isinstance(v,list):v=v[:1]
    d[k]=v
  d.update({'type':kind,'from':'system' if kind!='process' else 'user','instantiation':'true','name':name if kind!='process' else 'AI '+name})
  if kind=='process':d['inherits']=name
  profiles[kind]=d
 allowed=set(profiles['process'])|{k for k in original if k.startswith(('support_','tree_support_'))}|{'enable_support'}
 unknown=set(overrides)-allowed
 if unknown:raise ValueError('Unknown or non-process override keys: '+str(sorted(unknown)))
 profiles['process'].update(overrides)
 for kind,d in profiles.items():write_json(out/(kind+'.json'),d)
 regions=read_json(args.regions) if args.regions else []
 source=Path(args.model).resolve()
 if source.suffix.lower()=='.stl':geometry=package_stl(source,out/'model.3mf',regions)
 else:
  if regions:raise ValueError('Region painting currently requires STL with model-local mm coordinates')
  info=inspect(source)
  if not info['editable_mesh']:raise ValueError('Sliced-only 3MF has no mesh; supply original STL or project')
  (out/'model.3mf').write_bytes(source.read_bytes());geometry={'source_project':True}
 write_json(out/'manifest.json',{'source':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'settings_from':args.settings_from,'bed_type':original.get('curr_bed_type','Textured PEI Plate'),'overrides':overrides,'regions':regions,'geometry':geometry,'coordinate_convention':'original STL coordinates in mm, unchanged orientation and scale','status':'prepared_not_sliced'})
 return {'job':str(out),'geometry':geometry}

def slice_job(args):
 job=Path(args.job).resolve();out=fresh(args.out);out.mkdir()
 # Bambu Windows CLI mishandles some non-ASCII argv paths. Isolate in ASCII cache.
 cache=Path(os.environ.get('LOCALAPPDATA',tempfile.gettempdir()))/'BambuAIToolchain'
 cache.mkdir(parents=True,exist_ok=True)
 stage=Path(tempfile.mkdtemp(prefix='slice_',dir=cache));work=stage/'out';work.mkdir()
 for name in ['machine.json','process.json','filament.json','model.3mf']:shutil.copy2(job/name,stage/name)
 print_file=getattr(args,'print_file',False)
 output_name='result.gcode.3mf' if print_file else 'result.3mf'
 command=[str(EXE),'--load-settings',str(stage/'machine.json')+';'+str(stage/'process.json'),'--load-filaments',str(stage/'filament.json'),'--curr-bed-type',read_json(job/'manifest.json').get('bed_type','Textured PEI Plate'),'--arrange','1','--slice','0','--debug','2','--outputdir',str(work),'--export-3mf',output_name]
 if print_file:command+=['--min-save']
 command.append(str(stage/'model.3mf'))
 write_json(out/'command.json',command)
 with (out/'cli.log').open('wb') as log:
  p=subprocess.run(command,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,timeout=args.timeout)
 for file in work.iterdir():
  if file.is_file():shutil.copy2(file,out/file.name)
 if p.returncode:
  detail=read_json(out/'result.json').get('error_string','') if (out/'result.json').exists() else ''
  raise RuntimeError(f'Slicer exit {p.returncode}: {detail}; inspect {out}')
 target=out/output_name
 if not target.exists():raise RuntimeError('Slicer returned no 3MF')
 report=inspect(target)
 if not report['plates']:raise RuntimeError('Output has no G-code')
 if print_file and report['editable_mesh']:raise RuntimeError('Native print export unexpectedly contains editable meshes')
 report['export_mode']='native_min_save_print_file' if print_file else 'editable_project_with_gcode'
 expected=read_json(job/'manifest.json')['overrides']
 with zipfile.ZipFile(target) as z:actual=json.loads(z.read('Metadata/project_settings.config'))
 mismatch={k:{'expected':v,'actual':actual.get(k)} for k,v in expected.items() if actual.get(k)!=v}
 report['override_mismatches']=mismatch
 input_paint=inspect(job/'model.3mf')['paint'];report['input_painted_triangles']=sum(sum(v.values()) for v in input_paint.values());report['output_painted_triangles']=sum(sum(v.values()) for v in report['paint'].values())
 write_json(out/'verification.json',report)
 if mismatch:raise RuntimeError('Slicer changed requested overrides; see verification.json')
 if not print_file and report['input_painted_triangles']!=report['output_painted_triangles']:raise RuntimeError('Paint annotations did not survive roundtrip')
 def histogram(data):
  r={}
  for marks in data.values():
   for k,v in marks.items():r[k]=r.get(k,0)+v
  return r
 if not print_file and histogram(input_paint)!=histogram(report['paint']):raise RuntimeError('Paint annotation states changed')
 return {'result':str(target),'verification':str(out/'verification.json'),'plates':report['plates'],'painted_triangles':report['output_painted_triangles']}

def main():
 p=argparse.ArgumentParser();sub=p.add_subparsers(dest='cmd',required=True)
 sub.add_parser('doctor')
 i=sub.add_parser('inspect');i.add_argument('file');i.add_argument('--out')
 c=sub.add_parser('compare');c.add_argument('before');c.add_argument('after');c.add_argument('--out')
 a=sub.add_parser('prepare');a.add_argument('--model',required=True);a.add_argument('--out',required=True);a.add_argument('--settings-from');a.add_argument('--overrides');a.add_argument('--regions');a.add_argument('--machine',default='Bambu Lab P1S 0.4 nozzle');a.add_argument('--process',default='0.20mm Standard @BBL X1C');a.add_argument('--filament',default='Bambu PLA Basic @BBL P1S 0.4 nozzle')
 s=sub.add_parser('slice');s.add_argument('--job',required=True);s.add_argument('--out',required=True);s.add_argument('--timeout',type=int,default=1800);s.add_argument('--print-file',action='store_true',help='Use native --min-save export to create a sliced-only .gcode.3mf')
 args=p.parse_args()
 if args.cmd=='doctor':r={'executable':str(EXE),'installed':EXE.exists(),'profiles':str(PROFILES),'numpy':np.__version__}
 elif args.cmd=='prepare':r=prepare(args)
 elif args.cmd=='slice':r=slice_job(args)
 elif args.cmd=='compare':
  a=inspect(args.before);b=inspect(args.after)
  r={'before':a['file'],'after':b['file'],'setting_changes':{k:{'before':a['settings'].get(k),'after':b['settings'].get(k)} for k in a['settings'].keys()|b['settings'].keys() if a['settings'].get(k)!=b['settings'].get(k)},'before_plates':a['plates'],'after_plates':b['plates'],'limits':b['limits']}
  if args.out:write_json(fresh(args.out),r)
 else:
  r=inspect(args.file)
  if args.out:write_json(fresh(args.out),r)
 print(json.dumps(r,ensure_ascii=False,indent=2))
if __name__=='__main__':
 try:main()
 except Exception as e:print(json.dumps({'error':str(e)},ensure_ascii=False),file=sys.stderr);sys.exit(1)
