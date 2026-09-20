"""Per-tenant chrome for the same Heritage Core vendor product.

Two institutions run the same screens with different labels. Replay of a
vendor-default artifact needs locator overrides, not a new recording.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Brand:
    id: str
    product: str
    login_banner: str
    nav_title: str
    nav_search: str
    search_submit: str
    view_record: str
    record_heading: str
    banner_bg: str = "#003366"


HERITAGE = Brand(
    id="heritage",
    product="Heritage Core",
    login_banner="HERITAGE CORE  ·  Teller Workstation  ·  v4.12",
    nav_title="HERITAGE CORE",
    nav_search="Member Search",
    search_submit="Go",
    view_record="View Record",
    record_heading="Member Record",
)

FIRST_CU = Brand(
    id="first_cu",
    product="First Credit Union",
    login_banner="FIRST CU  ·  Heritage Core  ·  Member Services",
    nav_title="FIRST CU CORE",
    nav_search="Find Member",
    search_submit="Find",
    view_record="Open Record",
    record_heading="Member Record",
    banner_bg="#3d1f5c",
)

BRANDS = {HERITAGE.id: HERITAGE, FIRST_CU.id: FIRST_CU}


def get_brand(brand_id: str | None) -> Brand:
    return BRANDS.get((brand_id or "heritage").lower(), HERITAGE)
