from datetime import date

from tools.crm_intelligence import build_intelligence


def fixture():
    return {
        "identifiers": [
            {"Identifier_ID":"ID1","Product_ID":"OEM-1","Identifier_Type":"OEM","Original_Value":"5Q0 698 151 F","Normalized_Value":"5Q0698151F","Brand":"VAG","Source_Type":"Cars245","Verified_Status":"Verified","Last_Checked_At":"2026-09-01"},
            {"Identifier_ID":"ID2","Product_ID":"OEM-1","Identifier_Type":"OEM Cross-Reference","Original_Value":"5Q0 698 151 AH","Normalized_Value":"5Q0698151AH","Verified_Status":"Verified Cross-Reference"},
        ],
        "catalog": [
            {"Product_ID":"PRD-ATE","OEM_Number":"5Q0 698 151 F","Brand":"ATE","Product_Type":"Aftermarket","Category":"Brake Parts"},
            {"Product_ID":"PRD-ICER","OEM_Number":"5Q0 698 151 AH","Brand":"ICER","Product_Type":"Aftermarket","Category":"Brake Parts"},
        ],
        "requests": [
            {"Request_ID":"R1","Customer_ID":"C1","Date_Created":"2026-08-01","Requested_Part":"Front pads","OEM_Reference_Number":"5Q0 698 151 F","Quantity":1,"Customer_Intent":"Purchase Planned"},
            {"Request_ID":"R2","Customer_ID":"C2","Date_Created":"2026-08-20","Requested_Part":"Front pads","OEM_Reference_Number":"5Q0 698 151 F","Quantity":1,"Customer_Intent":"Confirmed"},
            {"Request_ID":"R3","Customer_ID":"C3","Date_Created":"2026-09-01","Requested_Part":"Front pads","OEM_Reference_Number":"5Q0 698 151 F","Quantity":1,"Request_Status":"Sold"},
        ],
        "offers": [
            {"Supplier_Offer_ID":"OFF-1","Product_ID":"","OEM_Number":"5Q0 698 151 F","Supplier_Name":"KANO","Supplier_Cost":2000,"Currency":"EGP","Verified_Status":"Confirmed"},
        ],
        "fitments": [], "inventory": [], "ai_feed": [],
    }


def test_multiple_brands_share_group_but_remain_products():
    out = build_intelligence(fixture(), date(2026, 9, 13))
    assert len(out["fitment_groups"]) == 1
    product_ids = {x["Product_ID"] for x in out["product_map"]}
    assert {"PRD-ATE", "PRD-ICER"}.issubset(product_ids)


def test_repeated_dates_create_purchase_priority_without_stock():
    out = build_intelligence(fixture(), date(2026, 9, 13))
    row = out["demand"][0]
    assert row["Request_Count_90D"] == 3
    assert row["Distinct_Request_Dates_90D"] == 3
    assert row["Demand_Class"] == "Purchase Priority"
    assert out["recommendations"][0]["Suggested_Reorder_Qty"] >= 1


def test_offer_history_is_flagged_not_deleted():
    out = build_intelligence(fixture(), date(2026, 9, 13))
    assert any(x["Entity_Type"] == "Supplier Offer" and x["Issue_Type"] == "Missing sellable Product_ID" for x in out["quality"])
