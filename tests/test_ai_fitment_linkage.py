from tools import backfill_fitment_summary_to_ai_feed as backfill
from tools import enrich_ai_fitment_backlog as enrich


def test_split_refs_keeps_each_oem_separate():
    value = "PAC 698 151; 8R0 698 151 AA / 8R0 698 151 AB"
    assert backfill.split_refs(value) == [
        "PAC698151",
        "8R0698151AA",
        "8R0698151AB",
    ]


def test_split_refs_rejects_short_noise():
    assert backfill.split_refs("1 / AB / n-a / 291AD") == ["291AD"]


def test_customer_feed_accepts_only_verified_fitment():
    assert backfill.is_verified_fitment({"Verified_Status": "Verified source; exact variant conditional"})
    assert not backfill.is_verified_fitment({"Verified_Status": "Cars245 page mentions searched OEM; catalog mapping candidate"})
    assert not backfill.is_verified_fitment({"Verified_Status": "Review Required"})


def test_enrichment_considers_all_oem_alternatives():
    value = "PAB 199 371 10; 4M0 199 372 D / 4M0 199 372 FG"
    assert enrich.all_parts(value) == [
        "PAB 199 371 10",
        "4M0 199 372 D",
        "4M0 199 372 FG",
    ]


def test_summary_deduplicates_generation_and_engine_codes():
    result = backfill.summarize([
        {
            "Vehicle_Make": "AUDI",
            "Vehicle_Model": "A4 B9 (8W2, 8WC)",
            "Generation": "B9 (8W2, 8WC)",
            "Year_From": "2016",
            "Year_To": "2024",
            "Engine_Code": "CYRB; CYRC; CYRB",
            "Fitment_Status": "Compatible - conditional",
        }
    ])
    assert "B9 (8W2, 8WC) B9 (8W2, 8WC)" not in result["Vehicle_Model"]
    assert result["Engine"].count("CYRB") == 1
