import importlib.util
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('report',Path(__file__).parents[1]/'report.py')
report=importlib.util.module_from_spec(spec);spec.loader.exec_module(report)
class AggregationTest(unittest.TestCase):
    def test_failed_or_warmup_samples_are_never_silently_successful(self):
        result=report.aggregate([{'index':-1,'ok':True,'fetchMs':900},{'index':0,'ok':True,'fetchMs':20},{'index':1,'ok':True,'fetchMs':10},{'index':2,'ok':False,'error':'OOM'}])
        self.assertEqual(result['samples'],2);self.assertEqual(result['fetchMs'],15);self.assertEqual(len(result['failures']),1)
    def test_missing_baseline_is_not_a_hundred_percent_improvement(self):
        self.assertIsNone(report.reduction(None,2));self.assertIsNone(report.reduction(0,2));self.assertEqual(report.reduction(20,5),75)
if __name__=='__main__':unittest.main()
