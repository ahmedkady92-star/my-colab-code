# Central Cars245 catalog configuration. Keep brand-specific routing here so the shared parser stays unchanged.
BRANDS = {
    "audi": {"search_path": "/en/catalog/car-audi/?q={query}", "group": "vw"},
    "volkswagen": {"search_path": "/en/catalog/car-vw/?q={query}", "group": "vw"},
    "skoda": {"search_path": "/en/catalog/car-skoda/?q={query}", "group": "vw"},
    "seat": {"search_path": "/en/catalog/car-seat/?q={query}", "group": "vw"},
    "cupra": {"search_path": "/en/catalog/car-seat/?q={query}", "group": "vw"},
    "porsche": {"search_path": "/en/catalog/car-porsc/?q={query}", "group": "vw"},
    "landrover": {"search_path": "/en/catalog/car-landrover/?q={query}", "group": "jlr"},
    "bmw": {"search_path": "/en/catalog/car-bmw/?q={query}", "group": "bmw"},
}

BRAKE_PAD_URL_TOKENS = (
    "brake-pad-set",
    "brake-pads-for-disk-brake",
    "brake-pads-with",
    "brk-lining",
    "brake-pad",
)
