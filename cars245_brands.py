# Central Cars245 catalog configuration. Keep brand-specific routing here so the shared parser stays unchanged.
BRANDS = {
    "audi": {"search_path": "/en/catalog/car-audi/?q={query}", "group": "vw"},
    "volkswagen": {"search_path": "/en/catalog/car-vw/?q={query}", "group": "vw"},
    "skoda": {"search_path": "/en/catalog/car-skoda/?q={query}", "group": "vw"},
    "seat": {"search_path": "/en/catalog/car-seat/?q={query}", "group": "vw"},
    # Cars245 does not expose CUPRA as a standalone vehicle catalog; use the shared VAG/Audi catalog fallback.
    "cupra": {"search_path": "/en/catalog/car-audi/?q={query}", "group": "vw", "catalog_fallback": "vag"},
    "porsche": {"search_path": "/en/catalog/car-porsc/?q={query}", "group": "vw"},
    # Bentley parts frequently share VAG references; use the tested VAG/Audi catalog as a safe fallback.
    "bentley": {"search_path": "/en/catalog/car-audi/?q={query}", "group": "vw", "catalog_fallback": "vag"},
    "landrover": {"search_path": "/en/catalog/car-landrover/?q={query}", "group": "jlr"},
    "jaguar": {"search_path": "/en/catalog/car-jagua/?q={query}", "group": "jlr"},
    "bmw": {"search_path": "/en/catalog/car-bmw/?q={query}", "group": "bmw"},
    "mercedes": {"search_path": "/en/catalog/car-merce/?q={query}", "group": "mercedes"},
    "volvo": {"search_path": "/en/catalog/car-volvo/?q={query}", "group": "volvo"},
}

BRAKE_PAD_URL_TOKENS = (
    "brake-pad-set",
    "brake-pads-for-disk-brake",
    "brake-pads-with",
    "brk-lining",
    "brake-pad",
)
