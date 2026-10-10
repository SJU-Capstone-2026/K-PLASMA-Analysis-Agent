"""Artificial current Runs only. Never opens the service .env or accepts a DB URL."""

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import random
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parents[3]
CONTAINER = "kplasma-forward-benchmark-db"
DATABASE = "forward_lookup_bench"
SEED = 20261010
SIZES = (150, 10_000, 100_000, 1_000_000)
TEMPLATE = json.loads((ROOT / "agent/tests/support/contract-wire.json").read_text())[
    "on"
]
SCALAR_ANALYSIS = {
    k: v
    for k, v in TEMPLATE["analysis"].items()
    if k not in ("residualTrace", "iad", "iead", "current", "potential", "density")
}


def condition(index):
    return index // 20_000 + 1, (index // 200 % 100 + 1) * 5, index % 200 * 50


def run_id(p, s, b):
    values = (p, s, b)
    if (
        any(
            not isinstance(x, (int, float))
            or not math.isfinite(x)
            or int(x) != x
            or x < 0
            for x in values
        )
        or p > 99
        or s > 999
        or b > 9999
    ):
        raise ValueError("Conditions cannot be represented exactly in the Run ID")
    return f"RUN-P{int(p):02d}-S{int(s):03d}-B{int(b):04d}"


def dataset_indices(size):
    if size not in SIZES:
        raise ValueError(f"Expected one of {SIZES}")
    base = [
        (p - 1) * 20_000 + (s // 5 - 1) * 200 + b // 50
        for p in (2, 4, 6, 8, 10)
        for s in (100, 200, 300, 400, 500)
        for b in (0, 200, 400, 600, 800, 1000)
    ]
    seen = set(base)
    # Coprime affine permutation of the million-key grid, excluding the base grid.
    for n in range(1_000_000):
        if len(base) == size:
            break
        index = (n * 485863 + SEED) % 1_000_000
        if index not in seen:
            base.append(index)
    return base


def version_id(index):
    return str(uuid.UUID(hashlib.md5(f"bench-version-{index}".encode()).hexdigest()))


def make_run(index):
    p, s, b = condition(index)
    return {
        "runId": run_id(p, s, b),
        "runVersionId": version_id(index),
        "pressure": p,
        "sourcePower": s,
        "biasPower": b,
        "metrics": {
            "ionFlux": (index * 37 % 90000) / 100,
            "meanIonEnergy": (index * 19 % 60000) / 100,
            "iedWidth": (index * 13 % 70000) / 100,
        },
        "units": copy.deepcopy(TEMPLATE["units"]),
        "qualityStatus": "VERIFIED",
        "convergenceStatus": "CONVERGED",
        "catalogStatus": "READY",
        "registeredAt": TEMPLATE["registeredAt"],
        "presentationScore": 1,
        "note": "Artificial benchmark "
        + hashlib.md5(f"bench-note-{index}".encode()).hexdigest(),
        "analysis": copy.deepcopy(SCALAR_ANALYSIS),
        "sourceFileCount": 1,
    }


def query_for(run):
    return {
        "conditions": {
            k: {"value": run[k], "unit": run["units"][k]}
            for k in ("pressure", "sourcePower", "biasPower")
        }
    }


def psql_command():
    return [
        "docker",
        "exec",
        "-i",
        CONTAINER,
        "psql",
        "-X",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        "benchmark",
        "-d",
        DATABASE,
        "-At",
    ]


def check_isolation():
    label = subprocess.check_output(
        [
            "docker",
            "inspect",
            "--format",
            '{{index .Config.Labels "kplasma.benchmark"}}',
            CONTAINER,
        ],
        text=True,
    ).strip()
    if label != "forward-lookup-synthetic-only":
        raise RuntimeError("Refusing an unmarked container")
    actual = subprocess.check_output(
        psql_command(), input="select current_database();", text=True
    ).strip()
    if actual != DATABASE:
        raise RuntimeError("Refusing a non-benchmark database")


def sql(text):
    check_isolation()
    return subprocess.check_output(psql_command(), input=text, text=True).strip()


def seed(size, output):
    check_isolation()
    started = time.perf_counter()
    indices = dataset_indices(size)
    corpus = random.Random(SEED).sample(indices, 40)
    insertion = indices.copy()
    random.Random(SEED + 1).shuffle(insertion)
    # The COPY contains integer indices only; JSON is derived in the isolated DB.
    script = (
        """
BEGIN;
TRUNCATE import_batch, source_set, run, agent_request, conversation_turn,
         workspace_idempotency, decision CASCADE;
UPDATE workspace SET active_run=null,candidate_reference=null,revision=0,
                     workspace_epoch=workspace_epoch+1,conversation_epoch=conversation_epoch+1;
CREATE TEMP TABLE bench_seed (idx integer PRIMARY KEY);
COPY bench_seed(idx) FROM STDIN;
"""
        + "\n".join(map(str, insertion))
        + "\n\\.\n"
    )
    template = json.dumps(SCALAR_ANALYSIS, ensure_ascii=False).replace("'", "''")
    units = json.dumps(TEMPLATE["units"], ensure_ascii=False).replace("'", "''")
    files = json.dumps(TEMPLATE["sourceFiles"], ensure_ascii=False).replace("'", "''")
    script += f"""
CREATE TEMP TABLE bench_rows AS
SELECT idx, 'RUN-P'||lpad((idx/20000+1)::text,2,'0')||'-S'||lpad(((idx/200%100+1)*5)::text,3,'0')||'-B'||lpad((idx%200*50)::text,4,'0') AS run_id,
md5('bench-version-'||idx)::uuid AS version_id, md5('bench-source-'||idx)::uuid AS source_id,
idx/20000+1 AS p, (idx/200%100+1)*5 AS s, idx%200*50 AS b FROM bench_seed;
INSERT INTO source_set(id,sha256,total_bytes)
SELECT source_id, md5('source-a-'||idx)||md5('source-b-'||idx),1 FROM bench_rows;
INSERT INTO source_file(source_id,relative_path,kind,size,sha256,storage_path)
SELECT source_id,'artificial.ini','SETTING',1,md5('file-a-'||idx)||md5('file-b-'||idx),'synthetic-only/no-original-file' FROM bench_rows;
INSERT INTO run(run_id) SELECT run_id FROM bench_rows;
INSERT INTO run_version(id,run_id,source_id,registered_at,summary,full_run)
SELECT version_id,run_id,source_id,'2000-01-01T00:00:00Z',summary,
summary||jsonb_build_object('sourceFiles','{files}'::jsonb)
FROM (SELECT *,jsonb_build_object(
'runId',run_id,'runVersionId',version_id::text,'pressure',p,'sourcePower',s,'biasPower',b,
'metrics',jsonb_build_object('ionFlux',(idx*37%90000)/100.0,'meanIonEnergy',(idx*19%60000)/100.0,'iedWidth',(idx*13%70000)/100.0),
'units','{units}'::jsonb,'qualityStatus','VERIFIED','convergenceStatus','CONVERGED','catalogStatus','READY',
'registeredAt','2000-01-01T00:00:00Z','presentationScore',1,
'note','Artificial benchmark '||md5('bench-note-'||idx),'analysis','{template}'::jsonb) AS summary FROM bench_rows) t;
UPDATE run r SET current_version_id=v.id FROM run_version v WHERE r.run_id=v.run_id;
COMMIT;
VACUUM (ANALYZE) run;
VACUUM (ANALYZE) run_version;
SELECT json_build_object('runs',(select count(*) from run),'versions',(select count(*) from run_version),
'databaseBytes',pg_database_size(current_database()),'summaryAverageBytes',(select avg(octet_length(summary::text)) from run_version),
'summaryP95Bytes',(select percentile_disc(0.95) within group (order by octet_length(summary::text)) from run_version));
"""
    result = subprocess.check_output(psql_command(), input=script, text=True)
    output.mkdir(parents=True, exist_ok=True)
    metadata = {
        "size": size,
        "seed": SEED,
        "generationSeconds": time.perf_counter() - started,
        "inputHash": hashlib.sha256(",".join(map(str, indices)).encode()).hexdigest(),
        "statistics": json.loads(result.splitlines()[-1]),
        "corpus": [
            {"index": i, "expected": make_run(i), "query": query_for(make_run(i))}
            for i in corpus
        ],
    }
    assert metadata["statistics"]["runs"] == metadata["statistics"]["versions"] == size
    (output / "dataset.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2)
    )
    print(json.dumps({k: v for k, v in metadata.items() if k != "corpus"}), flush=True)
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--size", type=int, choices=SIZES, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    seed(args.size, args.output)
