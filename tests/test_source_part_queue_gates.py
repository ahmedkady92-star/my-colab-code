import unittest
from tools.enrich_source_part_queue import eligible
class SourceQueueGates(unittest.TestCase):
    def test_reference_without_price_or_brand_can_run(self):
        self.assertTrue(eligible({'Part_Number':'06M905606F','Status':'Pending','Source_Confidence':'Source Confirmed'}))
    def test_ocr_block_and_supplier_mapping_cannot_be_bypassed(self):
        base={'Part_Number':'06M905606F','Status':'Pending','Source_Confidence':'Source Review Required'}
        self.assertFalse(eligible(base))
        self.assertFalse(eligible(dict(base,Part_Number='APT121315',Source_Confidence='Source Confirmed')))
    def test_completed_and_exhausted_entries_do_not_repeat(self):
        base={'Part_Number':'4F0698451D','Source_Confidence':'Source Confirmed','Status':'Evidence Collected - Review Required'}
        self.assertFalse(eligible(base))
        self.assertFalse(eligible(dict(base,Status='Pending',Attempt_Count=2)))
if __name__=='__main__':unittest.main()
