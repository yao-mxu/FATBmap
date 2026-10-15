"""
Load, clean the resource-list CSVs
  * some have a two-row header (a "section" row above the real header row),
  * some have extra columns ("Updated?", "Source"),
  * column order and exact header wording differ ("Medicare/Medicaid Accepted?" vs
    "Medicare Enrollment?", "Notes" vs "Other Notes", ...),
  * the dental sheet has no header for the Name column
  * the Address cell may be blank, "Online", contain several addresses, floor/suite
    lines, day-of-week prefixes, etc.

This module maps every file onto ONE set of columns, and extracts a clean list of street addresses per service so they can be geocoded and put on the map.

To add another spreadsheet, drop the CSV in ./data and add a line to SOURCES.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
CACHE_FILE = BASE_DIR / "geocode_cache.json"

# One entry per CSV.  "category" drives the tabs / marker colours / filter.
SOURCES = [
    {"file": "SMC ASL Reproductive Health_Updated - Sheet1.csv",
     "category": "Reproductive Health", "county": "San Mateo"},
    {"file": "SM ASL Mental Health_Revision_9_26 - Sheet1.csv",
     "category": "Mental Health", "county": "San Mateo"},
    {"file": "SC ASL Mental Health_Revision_9_27 - Sheet1.csv",
     "category": "Mental Health", "county": "Santa Clara"},
    {"file": "SM Health Clinics_Revision_9_26 - Sheet1.csv",
     "category": "Health Clinics", "county": "San Mateo"},
    {"file": "SM Dental Services_Revision_6_26 - Sheet1.csv",
     "category": "Dental", "county": "San Mateo"},
]

# Canonical columns, in display order.
CANONICAL_COLUMNS = [
    "Name", "Addresses", "Website", "Phone Number", "Fax", "Email",
    "Days of Operation", "Population Served", "Immigration Status Served",
    "Medicare/Medicaid Accepted?", "Access to Interpreters?", "Language Offerings?",
    "Type of Service", "Detailed In-Person Services Provided",
    "Telehealth Options?", "Telehealth Requirements", "Telehealth Services Provided",
    "Accepting Referrals/New Patients?", "Other Notes", "Source",
    "Date Last Updated", "Updated?",
]

# Rough bounding box for Santa Clara + San Mateo counties (with margin).  Any geocoder
# result outside it is treated as a bad match and ignored (e.g. "Online" once matched a
# town in France).
BBOX = {"lat_min": 36.8, "lat_max": 38.1, "lon_min": -122.7, "lon_max": -121.2}


# --------------------------------------------------------------------------- #
# Column / text cleaning
# --------------------------------------------------------------------------- #
def canonical_column(header) -> str | None:
    """Map any header wording found in the sheets to a canonical column name."""
    h = re.sub(r"\s+", " ", str(header)).strip().lower()
    if not h or h == "nan":
        return None
    if "last updated" in h:
        return "Date Last Updated"
    if h.startswith("updated"):
        return "Updated?"
    if h == "name":
        return "Name"
    if "address" in h:
        return "Addresses"
    if "requirement" in h:                      # "If YES ...: requirements ..."
        return "Telehealth Requirements"
    if "telehealth services" in h:
        return "Telehealth Services Provided"
    if "telehealth options" in h:
        return "Telehealth Options?"
    if "medicare" in h or "medicaid" in h:
        return "Medicare/Medicaid Accepted?"
    if "accepting referrals" in h:
        return "Accepting Referrals/New Patients?"
    if h in ("notes", "other notes"):
        return "Other Notes"
    simple = {
        "source": "Source", "website": "Website", "phone": "Phone Number",
        "fax": "Fax", "email": "Email", "days of operation": "Days of Operation",
        "population served": "Population Served",
        "immigration": "Immigration Status Served",
        "interpreter": "Access to Interpreters?", "language": "Language Offerings?",
        "type of service": "Type of Service",
        "detailed in-person": "Detailed In-Person Services Provided",
    }
    for key, canon in simple.items():
        if key in h:
            return canon
    return None


def clean_text(value) -> str:
    """Normalise whitespace but keep meaningful line breaks."""
    if value is None:
        return ""
    s = str(value).replace("\xa0", " ").replace("\r", "")
    s = "\n".join(line.rstrip() for line in s.split("\n"))
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return "" if s.lower() == "nan" else s


def clean_name(value: str) -> str:
    """'Stanford Hospital\\n(SAN MATEO)' -> 'Stanford Hospital (SAN MATEO)'."""
    lines = [ln.strip() for ln in clean_text(value).split("\n") if ln.strip()]
    out = ""
    for ln in lines:
        if not out:
            out = ln
        elif ln.startswith("("):
            out += " " + ln
        else:
            out += " / " + ln          # e.g. English / Spanish versions of a hotline
    return out


# --------------------------------------------------------------------------- #
# Reading one sheet
# --------------------------------------------------------------------------- #
def read_sheet(path: Path) -> pd.DataFrame:
    """Read one CSV (any header layout) into the canonical columns."""
    raw = pd.read_csv(path, header=None, dtype=str, keep_default_na=False)

    # Header row = the row that contains a "Phone Number" cell (within the first rows).
    hdr_idx = None
    for i in range(min(6, len(raw))):
        if any(str(c).strip().lower() == "phone number" for c in raw.iloc[i]):
            hdr_idx = i
            break
    if hdr_idx is None:
        raise ValueError(f"Could not find header row in {path.name}")

    mapping: dict[int, str] = {}
    seen: set[str] = set()
    for col_idx, header in raw.iloc[hdr_idx].items():
        canon = canonical_column(header)
        if canon and canon not in seen:
            mapping[col_idx] = canon
            seen.add(canon)

    # Dental sheet: the Name column has no header -> it's the column just left of
    # the first of Source / Website / Address.
    if "Name" not in seen:
        anchor = min(i for i, v in mapping.items() if v in ("Source", "Website", "Addresses"))
        mapping[anchor - 1] = "Name"

    body = raw.iloc[hdr_idx + 1:]
    df = pd.DataFrame({name: body[idx] for idx, name in mapping.items()})
    for col in CANONICAL_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[CANONICAL_COLUMNS].map(clean_text)

    df["Name"] = df["Name"].map(clean_name)
    # Drop blank filler rows and spreadsheet placeholders.
    df = df[(df["Name"] != "") & (~df["Name"].str.lower().isin({"add row", "name"}))]
    return df.reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Address extraction
# --------------------------------------------------------------------------- #
# A segment of text that ends in a US ZIP code (not followed by another word, so a
# 5-digit street number isn't mistaken for a ZIP).
_SEGMENT_RE = re.compile(r".*?\b\d{5}(?:-\d{4})?(?![\w-])(?!\s+[A-Za-z])")
_STREET_START_RE = re.compile(r"\b\d{1,6}\s+(?=[A-Za-z0-9])")
_DAY_PREFIX_RE = re.compile(
    r"^[\s,.;:]*((?:mon|tues|wednes|thurs|fri|satur|sun)day)\s*:\s*", re.I)


def geocode_key(address: str) -> str:
    """Normalised cache key for an address string."""
    return re.sub(r"\s+", " ", address).strip().strip(",.").lower()


def extract_addresses(raw: str) -> list[dict]:
    """
    Pull real street addresses out of a messy Address cell.

    Returns [{"address": "...", "label": "..."}], de-duplicated.  Cells such as
    "Online", "See site for locations" or blank return [].  "Former address" entries
    are skipped.  The label keeps context such as "Tuesday" or "Pediatric Emergency
    Department" when the cell lists several places.
    """
    text = clean_text(raw)
    if not text:
        return []
    flat = re.sub(r"\s*\n\s*", ", ", text)               # newlines -> commas
    flat = re.sub(r"(\d)-\s+(?=\d)", r"\1 ", flat)        # "114- 5th Ave" -> "114 5th Ave"
    flat = re.sub(r"\s+", " ", flat)

    found: dict[str, dict] = {}
    for m in _SEGMENT_RE.finditer(flat):
        seg = m.group(0)
        if "former" in seg.lower():
            continue
        label = ""
        start = _STREET_START_RE.search(seg)
        day = _DAY_PREFIX_RE.match(seg)
        if start:
            lead, addr = seg[:start.start()], seg[start.start():]
        elif day:                                        # e.g. an intersection
            lead, addr = day.group(1), seg[day.end():]
        else:
            lead, addr = "", seg
        lead = lead.strip(" ,.:;-")
        lead = re.sub(r":.*$", "", lead) if day is None else lead
        if "temporar" in lead.lower():
            label = "Temporary location"
        elif lead and len(lead) <= 50:
            label = lead
        addr = addr.strip(" ,.;")
        key = geocode_key(addr)
        if not addr or key in found and not label:
            continue
        if key in found:                                 # same place, extra label (Thu, Fri)
            prev = found[key]["label"]
            if label and label not in prev:
                found[key]["label"] = f"{prev}, {label}" if prev else label
        else:
            found[key] = {"address": addr, "label": label}
    return list(found.values())


def in_service_area(lat, lon) -> bool:
    try:
        return (BBOX["lat_min"] <= float(lat) <= BBOX["lat_max"]
                and BBOX["lon_min"] <= float(lon) <= BBOX["lon_max"])
    except (TypeError, ValueError):
        return False


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
def load_cache(cache_file: Path = CACHE_FILE) -> dict:
    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def data_signature() -> tuple:
    """Changes whenever a CSV or the geocode cache changes (used to bust st.cache_data)."""
    files = [DATA_DIR / s["file"] for s in SOURCES] + [CACHE_FILE]
    return tuple(f.stat().st_mtime if f.exists() else 0 for f in files)


def load_services(data_dir: Path = DATA_DIR, cache_file: Path = CACHE_FILE):
    """
    Returns (services, locations)

    services  : one row per service, canonical columns + Category, County, Service ID
                and an internal "_search" column.
    locations : one row per (service, street address) with latitude/longitude taken from
                the geocode cache (NaN when not geocoded yet).
    """
    frames = []
    for src in SOURCES:
        path = data_dir / src["file"]
        if not path.exists():
            raise FileNotFoundError(path)
        df = read_sheet(path)
        df["Category"] = src["category"]
        df["County"] = src["county"]
        frames.append(df)
    services = pd.concat(frames, ignore_index=True)
    services.insert(0, "Service ID", [f"S{i + 1:03d}" for i in range(len(services))])

    cache = load_cache(cache_file)
    rows = []
    for _, svc in services.iterrows():
        for loc in extract_addresses(svc["Addresses"]):
            hit = cache.get(geocode_key(loc["address"])) or {}
            lat, lon = hit.get("lat"), hit.get("lon")
            ok = in_service_area(lat, lon)
            rows.append({
                "Service ID": svc["Service ID"], "Name": svc["Name"],
                "Category": svc["Category"], "County": svc["County"],
                "address": loc["address"], "label": loc["label"],
                "latitude": float(lat) if ok else float("nan"),
                "longitude": float(lon) if ok else float("nan"),
            })
    locations = pd.DataFrame(rows, columns=[
        "Service ID", "Name", "Category", "County", "address", "label",
        "latitude", "longitude"])

    text_cols = [c for c in CANONICAL_COLUMNS if c not in ("Updated?",)]
    services["_search"] = (services[text_cols + ["Category", "County"]]
                           .agg(" ".join, axis=1).str.lower())
    return services, locations


def unique_addresses(data_dir: Path = DATA_DIR) -> list[str]:
    """All distinct street addresses across every sheet (for the geocoding script)."""
    seen: dict[str, str] = {}
    for src in SOURCES:
        df = read_sheet(data_dir / src["file"])
        for cell in df["Addresses"]:
            for loc in extract_addresses(cell):
                seen.setdefault(geocode_key(loc["address"]), loc["address"])
    return list(seen.values())
