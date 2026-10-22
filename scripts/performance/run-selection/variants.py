"""Build B/C from one verified bootJar; only C's index migration differs."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

INDEX='BOOT-INF/classes/db/migration/V11__live_run_selection_indexes.sql'
p=argparse.ArgumentParser();p.add_argument('jar',type=Path);p.add_argument('output',type=Path);args=p.parse_args()
for variant in ('B','C'):(args.output/variant).mkdir(parents=True,exist_ok=True)
b=args.output/'B'/'backend.jar';c=args.output/'C'/'backend.jar'
shutil.copy2(args.jar,c)
with zipfile.ZipFile(c) as source:
    assert INDEX in source.namelist()
    with zipfile.ZipFile(b,'w') as target:
        for entry in source.infolist():
            if entry.filename!=INDEX:target.writestr(entry,source.read(entry.filename))
with zipfile.ZipFile(b) as left,zipfile.ZipFile(c) as right:
    assert set(right.namelist())-set(left.namelist())=={INDEX}
    assert all(left.read(name)==right.read(name) for name in left.namelist())
(args.output/'variant-builds.json').write_text(json.dumps({'onlyDifference':INDEX,'sha256':{v:hashlib.sha256((args.output/v/'backend.jar').read_bytes()).hexdigest() for v in ('B','C')}},indent=2))
