from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


ALLOWED_IMAGE_STATUS = {"approved_commercial", "reference_only", "unknown"}
PUBLISHABLE_IMAGE_STATUS = "approved_commercial"


@dataclass
class ProductRecord:
    part_number: str
    brand: str
    product_name: str | None = None
    category: str | None = None
    source_name: str | None = None
    source_url: str | None = None
    image_urls: list[str] = field(default_factory=list)
    image_usage_status: str = "unknown"
    permission_reference: str | None = None
    oe_numbers: list[str] = field(default_factory=list)
    specifications: dict[str, Any] = field(default_factory=dict)
    compatibility: list[dict[str, Any]] = field(default_factory=list)
    supplier: str | None = None
    supplier_cost: float | None = None
    customer_price: float | None = None
    woo_status: str = "draft_blocked"
    blockers: list[str] = field(default_factory=list)


def normalize_part_number(value: str) -> str:
    return " ".join(value.strip().upper().split())


def normalize_brand(value: str) -> str:
    return value.strip().upper()


def load_sources() -> dict[str, Any]:
    path = Path(__file__).with_name("sources.json")
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_source(brand: str, sources: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    brand_norm = normalize_brand(brand)
    for source_name, cfg in sources.items():
        if brand_norm in {normalize_brand(x) for x in cfg.get("brands", [])}:
            return source_name, cfg
    return None, None


def evaluate_for_publish(record: ProductRecord) -> ProductRecord:
    blockers: list[str] = []

    if not record.part_number:
        blockers.append("missing_part_number")
    if not record.brand:
        blockers.append("missing_brand")
    if not record.product_name:
        blockers.append("missing_product_name")
    if not record.compatibility:
        blockers.append("missing_compatibility")
    if record.image_urls and record.image_usage_status != PUBLISHABLE_IMAGE_STATUS:
        blockers.append("image_not_licensed_for_commercial_use")
    if record.image_usage_status == PUBLISHABLE_IMAGE_STATUS and not record.permission_reference:
        blockers.append("missing_image_permission_reference")

    record.blockers = blockers
    record.woo_status = "ready_for_review" if not blockers else "draft_blocked"
    return record


def prepare_record(part_number: str, brand: str) -> dict[str, Any]:
    sources = load_sources()
    source_name, source_cfg = resolve_source(brand, sources)

    record = ProductRecord(
        part_number=normalize_part_number(part_number),
        brand=normalize_brand(brand),
        source_name=source_name,
        image_usage_status=(source_cfg or {}).get("image_usage_status", "unknown"),
    )

    if source_name is None:
        record.blockers.append("unsupported_or_unregistered_brand")

    return asdict(record)


if __name__ == "__main__":
    # Safe smoke test: no web access and no publishing.
    print(json.dumps(prepare_record("5Q0 698 151 AH", "ATE"), indent=2, ensure_ascii=False))
