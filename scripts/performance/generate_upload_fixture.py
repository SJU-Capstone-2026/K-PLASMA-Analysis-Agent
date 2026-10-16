#!/usr/bin/env python3
"""Artificial parser inputs only. Volume profiles contain counts/shapes, never measured physical values."""
import argparse
import hashlib
import itertools
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPECS = {
    "0d_result/output/IED/Ar+.txt": ("IEDs", "1D", "energy (eV)", "IED (a.u.)"),
    "0d_result/output/IAD/Ar+.txt": ("IADs", "1D", "angle (degrees)", "IAD (a.u.)"),
    "0d_result/output/IEAD/Ar+.txt": ("IEAD", "2D", "angle (degrees)", "energy (eV)"),
    "0d_result/output/CUR/J0h_h.txt": ("Current_density", "1D", "time (rf cycle)", "J0h_h (statampere/cm^2)"),
    "0d_result/output/POT/pot.txt": ("Pot", "1D", "time (rf cycle)", "pot (V)"),
    "0d_result/output/DEN/Ar+.txt": ("DENSITY", "2D", "time (rf cycle)", "distance (cm)"),
}
RESIDUAL = "0d_result/log/residual.log"

def inventory(manifest, storage, output):
    profile = []
    for run in json.loads(manifest.read_text()):
        p, s, b = map(int, re.fullmatch(r"RUN-P(\d+)-S(\d+)-B(\d+)", run["runId"]).groups())
        files = []
        for file in run["files"]:
            item = {"name": file["relativePath"], "bytes": file["size"]}
            path = storage / file["storagePath"]
            assert path.is_file() and path.stat().st_size == file["size"]
            if item["name"] in SPECS:
                with path.open() as stream:
                    for line in stream:
                        if line.strip() and not line.startswith("#"): break
                        match = re.match(r"#\s*(nx|ny)\s*=\s*(\d+)", line)
                        if match: item[match[1]] = int(match[2])
                assert "nx" in item
            elif item["name"] == RESIDUAL:
                with path.open() as stream:
                    item["rows"] = sum(bool(line.strip()) and not line.lstrip().startswith("#") for line in stream)
            files.append(item)
        profile.append({"pressure": p, "source": s, "bias": b, "files": files})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(profile, indent=2))
    print(json.dumps({"runs": len(profile), "files": sum(len(r["files"]) for r in profile),
                      "bytes": sum(f["bytes"] for r in profile for f in r["files"])}))

def padded(header, rows, target):
    raw = header + "".join(rows)
    extra = max(0, target - len(raw.encode()))
    if rows:
        each, last = divmod(extra, len(rows))
        return header + "".join(line.rstrip("\n") + " " * (each + (i < last)) + "\n" for i, line in enumerate(rows))
    # Ancillary logs need no parser; output completion remains its own final line.
    filler = "# entirely artificial padding\n"
    return raw + (filler * (extra // len(filler)) + " " * (extra % len(filler)))

def scalar_text(p, s, b, updated):
    template = (ROOT / "backend/src/test/java/com/kplasma/analysisagent/ingestion/SyntheticRunFiles.java").read_text()
    blocks = re.findall(r'return """\n(.*?)"""\.formatted', template, re.S)
    ini = "\n".join(line[12:] if line.startswith(" "*12) else line for line in blocks[0].splitlines()) + "\n"
    ini = ini.replace("%s", "1" if b else "0", 1).replace("%s", str(b), 1).replace("%s", "\x01", 1)
    ini = ini.replace("PRS=2", f"PRS={p}").replace("Powerh=1.e2", f"Powerh={s}")
    solver = "\n".join(line[12:] if line.startswith(" "*12) else line for line in blocks[1].splitlines()) + "\n"
    solver = solver.replace("%s", "ON" if b else "OFF", 1)
    solver = solver.replace("%s", f"[BIAS POWER CONDITIONS]\nPower1h = {b} (W)" if b else "", 1)
    solver = solver.replace("%s", "[BIAS PARAMETERS]\ndc-offset = -8 (V)\npeak-to-peak = 24 (V)" if b else "", 1)
    solver = solver.replace("PowerH = 1.e2", f"PowerH = {s}").replace("Pressure = 2 ", f"Pressure = {p} ")
    if updated:
        solver = solver.replace("Ar+ 1.e14", "Ar+ 2.e14").replace("Ar+ 12.3456789", "Ar+ 23.4567891")
    return ini, solver

def graph(name, nx, ny, target, updated):
    kind, dim, x, y = SPECS[name]
    header = f"# type={kind}\n# gtype={dim}\n# x={x}\n# y={y}\n# nx={nx}\n"
    if dim == "2D": header += f"# ny={ny}\n"
    header += "# title=entirely artificial performance fixture\n"
    factor = 2 if updated else 1
    rows = []
    for i in range(nx):
        if dim == "1D":
            xv = i
            if kind in ("Current_density", "Pot"): xv = i / max(1, nx-1)
            elif kind == "IADs": xv = -90 + 180*i/max(1, nx-1)
            value = factor
            if kind == "Current_density": value = factor * 1000 * math.sin(2*math.pi*xv)
            elif kind == "Pot": value = -factor*(10+100*(1-math.cos(2*math.pi*xv))/2)
            rows.append(f"{xv:.9g} {value:.9g}\n")
        else:
            xv = i/max(1,nx-1) if kind == "DENSITY" else -10+20*i/max(1,nx-1)
            for j in range(ny):
                yv = j*.001 if kind == "DENSITY" else j
                rows.append(f"{xv:.9g} {yv:.9g} {factor}\n")
    return padded(header, rows, target)

def default_profile(count):
    runs = []
    for p, s, b in itertools.islice(itertools.product([2,4,6,8,10],[100,200,300,400,500],[0,200,400,600,800,1000]), count):
        files = [{"name": name, "bytes": 0} for name in ["0d_setting.ini","0d_result/log/solver.log","0d_result/log/output.log"]]
        files += [{"name": RESIDUAL, "rows": 101, "bytes": 0}]
        if b:
            files += [{"name": name, "nx": 121 if dim=="1D" else 41, "ny": 31, "bytes": 0}
                      for name,(_,dim,_,_) in SPECS.items()]
        runs.append({"pressure":p,"source":s,"bias":b,"files":files})
    return runs

def generate(profile, output, updated=False):
    output.mkdir(parents=True, exist_ok=True)
    entries, expected = [], {}
    for run in profile:
        p,s,b = run["pressure"],run["source"],run["bias"]
        run_id = f"RUN-P{p:02}-S{s:03}-B{b:04}"
        prefix = f"PRS_{p:02}/Source_{s}/Bias_{b:04}"
        ini,solver = scalar_text(p,s,b,updated)
        width = None
        for spec in run["files"]:
            name,target = spec["name"],spec["bytes"]
            if name=="0d_setting.ini": content = padded(ini, [], target)
            elif name=="0d_result/log/solver.log": content = padded(solver, [], target)
            elif name=="0d_result/log/output.log":
                content = padded("", [], max(0,target-len("INFO: Finished!\n"))) + "INFO: Finished!\n"
            elif name==RESIDUAL:
                header="# type=residual\n# gtype=1D\n# x=iteration (#)\n# y=residual (a.u.)\n# species=E Ar* Ar+ Ar Te\n"
                content=padded(header,[f"{i} 0 0 0 0 0.001\n" for i in range(1,spec["rows"]+1)],target)
            elif name in SPECS:
                content=graph(name,spec["nx"],spec.get("ny",1),target,updated)
                if name=="0d_result/output/IED/Ar+.txt":
                    width=math.ceil(.9*spec["nx"])-math.ceil(.1*spec["nx"])
            else: content=padded("",[],target)
            payload=content.encode()
            path=output/"files"/prefix/name
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(payload)
            entries.append({"relativePath":prefix+"/"+name,"path":str(path.resolve()),"size":len(payload),
                            "sha256":hashlib.sha256(payload).hexdigest()})
        expected[run_id]={"pressure":p,"sourcePower":s,"biasPower":b,
                          "meanIonEnergy":23.4567891 if updated else 12.3456789,
                          "ionFlux":2 if updated else 1,"iedWidth":width}
        print(f"generated {run_id}", flush=True)
    dataset_hash=hashlib.sha256(json.dumps([(e["relativePath"],e["sha256"]) for e in entries]).encode()).hexdigest()
    result={"artificial":True,"updated":updated,"datasetHash":dataset_hash,"entries":entries,"expected":expected}
    (output/"manifest.json").write_text(json.dumps(result))
    print(json.dumps({"runs":len(expected),"files":len(entries),"bytes":sum(e["size"] for e in entries),"datasetHash":dataset_hash}))

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--profile",type=Path)
    parser.add_argument("--count",type=int,default=150)
    parser.add_argument("--updated",action="store_true")
    parser.add_argument("--inventory",type=Path)
    parser.add_argument("--storage",type=Path)
    args=parser.parse_args()
    if args.inventory: inventory(args.inventory,args.storage,args.out)
    else: generate(json.loads(args.profile.read_text()) if args.profile else default_profile(args.count),args.out,args.updated)
