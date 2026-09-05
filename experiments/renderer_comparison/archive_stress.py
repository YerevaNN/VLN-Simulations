"""Archive evidence for completed stress runs; never invent missing output."""
import hashlib,json,shutil,subprocess
from pathlib import Path
base=Path('/mnt/weka/hrant/rtx-vln-sample-20260905')
out=base/'repo/experiments/renderer_comparison/results/stress'
out.mkdir(parents=True,exist_ok=True)
raw=base/'stress-bright'
index=[]
for file in sorted(raw.rglob('*')):
    if file.is_file() and 'report' not in file.parts:
        index.append(dict(path=str(file.relative_to(base)),bytes=file.stat().st_size,sha256=hashlib.sha256(file.read_bytes()).hexdigest()))
for manifest in raw.glob('*/manifest.json'):
    target=out/manifest.parent.name; target.mkdir(exist_ok=True)
    shutil.copy2(manifest,target/'manifest.json')
for name in ['metrics.json','comparison.jpg','transparency-pair.png']:
    if (raw/'report'/name).exists():shutil.copy2(raw/'report'/name,out/name)
(out/'artifact-index.json').write_text(json.dumps(index,indent=2))
(out/'slurm-accounting.txt').write_text(subprocess.check_output(['sacct','-j','246820,246821,246822,246823,246824,246825,246826,246827,246828,246829,246830','--format=JobID,State,Elapsed,NodeList,ExitCode','-P'],text=True))
for j in [246824,246829]:
    log=base/'logs'/f'stress-{j}.log'
    if log.exists():
        lines=log.read_text(errors='replace').splitlines()
        selected=[l for l in lines if any(x in l for x in ['Driver Version','ERROR_DEVICE_LOST','GPU crash','Fatal Python','CAPTURE','COMPLETE','TIME LIMIT'])]
        (out/f'failure-{j}.txt').write_text('\n'.join(selected+['--- final log lines ---']+lines[-8:]))
