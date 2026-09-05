"""Transfer completed image sets without runtime links or bulky depth arrays."""
from pathlib import Path
import zipfile
base=Path('/mnt/weka/hrant/rtx-vln-sample-20260905'); root=base/'valley-eight'
with zipfile.ZipFile(base/'valley-images.zip','w',compression=zipfile.ZIP_DEFLATED) as z:
 for manifest in sorted(root.glob('*/manifest.json')):
  if manifest.parent.name.startswith('pilot'):continue
  z.write(manifest,manifest.relative_to(root))
  for image in sorted(manifest.parent.glob('*.png')):z.write(image,image.relative_to(root))
  print(manifest.parent.name)
