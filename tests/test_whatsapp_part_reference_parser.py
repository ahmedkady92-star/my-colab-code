import unittest
from tools.whatsapp_part_reference_parser import extract_references,parse_messages,occurrence_id

class SourceReferenceTests(unittest.TestCase):
    def test_photo_caption_is_not_lost(self):
        m=parse_messages('10/12/26, 17:50 - Owner: IMG-20261012-WA0075.jpg (file attached)\n4F0 698 451 D\n10/12/26, 17:52 - Supplier: icer 2150')
        refs=extract_references(m[0]['text'])
        self.assertEqual([x['code'] for x in refs],['4F0698451D'])
        self.assertEqual(m[0]['date'],'2026-10-12')
        self.assertEqual(m[0]['source_id'],'KANO-TXT-L1')
        self.assertEqual(extract_references(m[1]['text']),[])
    def test_prices_phones_vins_and_media_dates_are_not_parts(self):
        for s in ['NGK800','icer 2150','+20 10 00920020','WVWZZZ1KZBW123456','IMG-20261012-WA0075.jpg']:
            with self.subTest(s=s):self.assertEqual(extract_references(s),[])
    def test_manufacturer_suffix_is_preserved(self):
        self.assertEqual(extract_references('X90505-01')[0]['code'],'X9050501')
        self.assertEqual(extract_references('ICER 181986-203')[0]['code'],'181986203')
    def test_ocr_shape_alone_cannot_approve_source(self):
        self.assertFalse(extract_references('06M905606F','IMAGE_OCR')[0]['trusted'])
        self.assertTrue(extract_references('06M905606F')[0]['trusted'])
    def test_reimports_have_stable_occurrence_keys(self):
        self.assertEqual(occurrence_id('KANO-TXT-L10','4F0 698 451 D'),occurrence_id('KANO-TXT-L10','4F0698451D'))

if __name__=='__main__':unittest.main()
