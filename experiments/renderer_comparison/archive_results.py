"""Keep compact evidence in Git while retaining raw frames outside the repo."""
import argparse,hashlib,json,shutil
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--results',required=True);p.add_argument('--output',required=True)
a=p.parse_args();root=Path(a.results);out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
index={}
for backend in ['isaac-ap','newton','behavior45-pt','behavior45-pt-ap','behavior-pathtracing-ap']:
    folder=root/backend
    if not (folder/'manifest.json').exists(): continue
    shutil.copy2(folder/'manifest.json',out/(backend+'-manifest.json'))
    for file in sorted(folder.iterdir()):
        if file.suffix not in ['.png','.npy','.json']:continue
        index[str(file.relative_to(root))]={'bytes':file.stat().st_size,'sha256':hashlib.sha256(file.read_bytes()).hexdigest()}
(out/'artifact-index.json').write_text(json.dumps(index,indent=2),encoding='utf-8')
if (root/'report/comparison.png').exists():shutil.copy2(root/'report/comparison.png',out/'comparison.png')
if (root/'comparison-metrics.json').exists():shutil.copy2(root/'comparison-metrics.json',out/'comparison-metrics.json')
print('Archived metadata for',len(index),'artifacts')
