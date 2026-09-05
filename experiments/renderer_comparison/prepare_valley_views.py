"""Select five existing valley cameras without changing scene geometry."""
import json,shutil
from pathlib import Path
base=Path('/mnt/weka/hrant/rtx-vln-sample-20260905')
source=base/'comparison/scene'; dest=base/'valley-eight/scene'
dest.mkdir(parents=True,exist_ok=True)
assert not (dest/'cameras.json').exists(), 'Preserve an existing suite; choose a new destination.'
config=json.loads((source/'cameras.json').read_text())
selected=['launch','river','bridge','forest','overview']
poses={p['name']:p for p in config['poses']}
config['poses']=[dict(poses[name],name=f'valley-{name}_{i}',kind='view') for name in selected for i in range(3)]
shutil.copy2(source/'valley.usdc',dest/'valley.usdc')
(dest/'cameras.json').write_text(json.dumps(config,indent=2))
print('Prepared five original cameras, three captures each:',', '.join(selected))
