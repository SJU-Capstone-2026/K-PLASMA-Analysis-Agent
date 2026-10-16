import unittest
from upload_query_benchmark import validate_seed

class QueryHarnessTest(unittest.TestCase):
    def test_requires_distinct_seed_versions_on_the_supported_grid(self):
        dataset={"expected":{"OLD":{}}}
        seed=[{"runId":"OLD","runVersionId":"v","sha256":"hash"}]
        validate_seed(dataset,seed)
        for invalid in [[],seed*2,[{**seed[0],"runId":"NEW"}]]:
            with self.assertRaises(ValueError):validate_seed(dataset,invalid)

if __name__=='__main__':unittest.main()
