"""
Geocode every street address found in the CSVs in ./data and save the results to
geocode_cache.json (which the Streamlit app reads).

Uses OpenStreetMap's free Nominatim service (max 1 request/second).  For each address it tries the full address first, then
a simplified version without suite / floor / unit text.  Results outside the
Santa Clara / San Mateo area are rejected as bad matches.

If an address can't be found, can add it by hand to geocode_cache.json:
    "<lower-cased address>": {"lat": 37.5, "lon": -122.3}
(the key is printed in the failure list below).
"""
import argparse
import json
import re
import sys

from data_loader import CACHE_FILE, geocode_key, in_service_area, load_cache, unique_addresses

try:
    from geopy.extra.rate_limiter import RateLimiter
    from geopy.geocoders import Nominatim
except ImportError:
    sys.exit("Please run:  pip install geopy")


def simplify(address: str) -> str:
    """Remove suite / floor / unit / building text that often confuses geocoders."""
    a = re.sub(r",?\s*(?:suite|ste\.?|unit|bldg\.?|building)\s*#?\s*[\w-]+", "", address, flags=re.I)
    a = re.sub(r",?\s*#\s*[\w-]+", "", a)
    a = re.sub(r",?\s*(?:first|second|third|fourth|\d+(?:st|nd|rd|th))\s+floor", "", a, flags=re.I)
    a = re.sub(r"\s+", " ", a).strip(" ,")
    return a


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--retry-failed", action="store_true")
    args = ap.parse_args()

    cache = load_cache()
    geolocator = Nominatim(user_agent="fatb-resource-map (Stanford Families at the Border)")
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1.1, max_retries=2)

    todo = []
    for addr in unique_addresses():
        key = geocode_key(addr)
        if key in cache and (cache[key] or not args.retry_failed):
            continue
        todo.append(addr)
    print(f"{len(todo)} address(es) to geocode "
          f"({len(cache)} already cached).")

    try:
        for i, addr in enumerate(todo, 1):
            key = geocode_key(addr)
            result = None
            for query in dict.fromkeys([addr, simplify(addr)]):   # full, then simplified
                loc = geocode(query, country_codes="us", timeout=15)
                if loc and in_service_area(loc.latitude, loc.longitude):
                    result = {"lat": loc.latitude, "lon": loc.longitude,
                              "query": query, "matched": loc.address}
                    break
            cache[key] = result                                    # None = failed
            print(f"[{i}/{len(todo)}] {'OK  ' if result else 'FAIL'} {addr}")
    finally:                                                       # save even on Ctrl-C
        CACHE_FILE.write_text(json.dumps(cache, indent=2, sort_keys=True))

    failed = [k for k, v in cache.items() if not v]
    print(f"\nSaved {CACHE_FILE.name}: {len(cache) - len(failed)} found, {len(failed)} failed.")
    if failed:
        print("Not found (add coordinates by hand or fix the address in the sheet):")
        for k in failed:
            print("  ", k)


if __name__ == "__main__":
    main()
