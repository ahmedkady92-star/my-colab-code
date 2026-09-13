# ELKADY CRM Intelligence Model

## Safety contract

- Source/history tabs are read-only.
- Dry-run is the default.
- Apply mode replaces only derived tabs 54-58.
- No supplier order is placed automatically.
- Only verified OEM identifiers create fitment groups.
- Ambiguous identifiers are sent to review; the first match is never selected silently.
- AI publication remains limited to confirmed, conflict-free, EGP records.

## Identity model

- `Product_ID`: one sellable product/brand/MPN.
- `Supplier_Offer_ID`: one supplier offer; repeated dates and prices remain separate history.
- `Fitment_Group_ID`: verified OEM compatibility identity.
- `55_Product_Fitment_Map`: many-to-many bridge between sellable products and compatibility groups.

## Demand rule

- Normal: one request.
- Monitor: at least two requests on two dates in 90 days.
- Important: at least three requests/units on two dates in 90 days.
- High Demand: at least five requests or three sold events in 90 days.
- Purchase Priority: repeated/confirmed demand exceeds available stock.

Supplier offers do not count as customer demand. Duplicate `Request_ID` values do not inflate demand.

## Purchase recommendation

The suggested quantity targets four weeks of observed 90-day demand plus one safety unit for important parts, less current available inventory. It is advisory only; VIN, live supplier availability and current cost must be confirmed by the owner before buying.
