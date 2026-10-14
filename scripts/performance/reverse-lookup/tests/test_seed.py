from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from seed import condition,dataset_indices,make_run,query_for


def test_unique_current_conditions_and_fixed_five_candidates():
    for size in (150,10000,100000,1000000):
        indices=dataset_indices(size)
        assert len(indices)==size and len(set(indices))==size
        # Integer grid decomposition is injective, including million-row boundaries.
        for index in [0,4,size-1]:
            p,s,b=condition(index)
            assert (p-1)*20000+(s//5-1)*200+b//50==index
        assert [make_run(i)['metrics']['meanIonEnergy'] for i in range(5)]==[150,151,152,153,154]
        assert make_run(5)['metrics']['meanIonEnergy']>160
        assert query_for(make_run(0))==query_for(make_run(size-1))


def test_benchmark_isolation_rejects_unmarked_container_and_wrong_database(monkeypatch):
    import pytest
    import seed
    for responses, message in [(["other"], "unmarked"), (["reverse-lookup-synthetic-only", "service"], "non-benchmark")]:
        values = iter(responses)
        monkeypatch.setattr(seed.subprocess, "check_output", lambda *args, **kwargs: next(values))
        with pytest.raises(RuntimeError, match=message):
            seed.check_isolation()
