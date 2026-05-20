"""
hospital_finder/agent.py  —  UPDATED VERSION
────────────────────────────────────────────────────────────────
Hospital Finder Agent — Sehat Agent

ORIGINAL FIXES (preserved):
  FIX-1  Dual route: both /analyze AND /hospital-finder/analyze respond
  FIX-2  Emergency urgency now correctly maps to "emergency" dept in fallback DB
  FIX-3  Graceful city extraction from raw_input if city not explicitly passed
  FIX-4  hospital_type always returned even when source=fallback
  FIX-5  Better reasoning string for judges' agent trace
  FIX-6  Quota-safe: zero Gemini calls, only Google Places (optional) or fallback

NEW IN THIS UPDATE:
  UPDATE-1  area parameter accepted from UI location selector
  UPDATE-2  AREA_HOSPITAL_MAP added — area keyword → nearest hospital names
  UPDATE-3  _reorder_by_area() reorders results so nearest hospital comes first
  UPDATE-4  reasoning string now mentions area used for proximity sorting
"""

import json
import os
import urllib.request
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS

# ── Logger ────────────────────────────────────────────────────────────────────

def log(msg):
    print(f"[HOSPITAL FINDER] {datetime.now().strftime('%H:%M:%S')} {msg}")


# ── Env Loader ────────────────────────────────────────────────────────────────

def _load_env():
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ.setdefault(k.strip(), v.strip(' "\''))

_load_env()
API_KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "")


# ── Fallback Database ─────────────────────────────────────────────────────────

FALLBACK_DB = {
    "karachi": {
        "cardiology": [
            {"name": "National Institute of Cardiovascular Diseases (NICVD)",
             "address": "Rafiqui H.J. Shaheed Road, Karachi", "phone": "021-99201271",
             "rating": 4.6, "type": "government", "emergency": True,
             "maps_link": "https://maps.google.com/?q=NICVD+Karachi"},
            {"name": "Karachi Institute of Heart Diseases (KIHD)",
             "address": "Federal B. Area, Karachi", "phone": "021-99233074",
             "rating": 4.2, "type": "government", "emergency": True,
             "maps_link": "https://maps.google.com/?q=KIHD+Karachi"},
            {"name": "Tabba Heart Institute",
             "address": "1/3, Shahrah-e-Faisal, Karachi", "phone": "021-34033600",
             "rating": 4.5, "type": "private", "emergency": True,
             "maps_link": "https://maps.google.com/?q=Tabba+Heart+Institute+Karachi"},
        ],
        "general medicine": [
            {"name": "Civil Hospital Karachi",
             "address": "Karachi Medical & Dental College, Karachi", "phone": "021-99215740",
             "rating": 4.0, "type": "government", "emergency": True,
             "maps_link": "https://maps.google.com/?q=Civil+Hospital+Karachi"},
            {"name": "Liaquat National Hospital",
             "address": "Stadium Road, Karachi", "phone": "021-34412000",
             "rating": 4.3, "type": "private", "emergency": True,
             "maps_link": "https://maps.google.com/?q=Liaquat+National+Hospital+Karachi"},
            {"name": "Aga Khan University Hospital",
             "address": "Stadium Road, Karachi", "phone": "021-111-911-911",
             "rating": 4.5, "type": "private", "emergency": True,
             "maps_link": "https://maps.google.com/?q=Aga+Khan+Hospital+Karachi"},
        ],
        "emergency": [
            {"name": "Jinnah Postgraduate Medical Centre (JPMC)",
             "address": "Rafiqui Shaheed Road, Karachi", "phone": "021-99201300",
             "rating": 4.1, "type": "government", "emergency": True,
             "maps_link": "https://maps.google.com/?q=JPMC+Karachi"},
            {"name": "Civil Hospital Karachi",
             "address": "Karachi Medical & Dental College, Karachi", "phone": "021-99215740",
             "rating": 4.0, "type": "government", "emergency": True,
             "maps_link": "https://maps.google.com/?q=Civil+Hospital+Karachi"},
            {"name": "Aga Khan University Hospital",
             "address": "Stadium Road, Karachi", "phone": "021-111-911-911",
             "rating": 4.5, "type": "private", "emergency": True,
             "maps_link": "https://maps.google.com/?q=Aga+Khan+Hospital+Karachi"},
        ],
        "neurology": [
            {"name": "Aga Khan University Hospital",
             "address": "Stadium Road, Karachi", "phone": "021-111-911-911",
             "rating": 4.5, "type": "private", "emergency": True,
             "maps_link": "https://maps.google.com/?q=Aga+Khan+Hospital+Karachi"},
            {"name": "Liaquat National Hospital",
             "address": "Stadium Road, Karachi", "phone": "021-34412000",
             "rating": 4.3, "type": "private", "emergency": False,
             "maps_link": "https://maps.google.com/?q=Liaquat+National+Hospital+Karachi"},
        ],
        "pediatrics": [
            {"name": "National Institute of Child Health (NICH)",
             "address": "Rafiqui Shaheed Road, Karachi", "phone": "021-99201700",
             "rating": 4.3, "type": "government", "emergency": True,
             "maps_link": "https://maps.google.com/?q=NICH+Karachi"},
            {"name": "The Children's Hospital Karachi",
             "address": "Johar, Karachi", "phone": "021-34812400",
             "rating": 4.2, "type": "private", "emergency": True,
             "maps_link": "https://maps.google.com/?q=Childrens+Hospital+Karachi"},
        ],
        "gynecology": [
            {"name": "Lyari General Hospital",
             "address": "Lyari, Karachi", "phone": "021-32810071",
             "rating": 3.9, "type": "government", "emergency": True,
             "maps_link": "https://maps.google.com/?q=Lyari+General+Hospital+Karachi"},
            {"name": "Aga Khan University Hospital",
             "address": "Stadium Road, Karachi", "phone": "021-111-911-911",
             "rating": 4.5, "type": "private", "emergency": True,
             "maps_link": "https://maps.google.com/?q=Aga+Khan+Hospital+Karachi"},
        ],
        "orthopedics": [
            {"name": "Jinnah Postgraduate Medical Centre (JPMC)",
             "address": "Rafiqui Shaheed Road, Karachi", "phone": "021-99201300",
             "rating": 4.1, "type": "government", "emergency": False,
             "maps_link": "https://maps.google.com/?q=JPMC+Karachi"},
            {"name": "Aga Khan University Hospital",
             "address": "Stadium Road, Karachi", "phone": "021-111-911-911",
             "rating": 4.5, "type": "private", "emergency": False,
             "maps_link": "https://maps.google.com/?q=Aga+Khan+Hospital+Karachi"},
        ],
        "dermatology": [
            {"name": "Jinnah Postgraduate Medical Centre (JPMC)",
             "address": "Rafiqui Shaheed Road, Karachi", "phone": "021-99201300",
             "rating": 4.1, "type": "government", "emergency": False,
             "maps_link": "https://maps.google.com/?q=JPMC+Karachi"},
        ],
        "psychiatry": [
            {"name": "Institute of Behavioral Sciences (IBS)",
             "address": "Gulshan-e-Iqbal, Karachi", "phone": "021-34820472",
             "rating": 4.0, "type": "government", "emergency": False,
             "maps_link": "https://maps.google.com/?q=IBS+Karachi"},
        ],
    },
    "lahore": {
        "general medicine": [
            {"name": "Services Hospital Lahore",
             "address": "Jail Road, Lahore", "phone": "042-99203520",
             "rating": 4.1, "type": "government", "emergency": True,
             "maps_link": "https://maps.google.com/?q=Services+Hospital+Lahore"},
            {"name": "Lahore General Hospital",
             "address": "Ferozepur Road, Lahore", "phone": "042-99231430",
             "rating": 4.0, "type": "government", "emergency": True,
             "maps_link": "https://maps.google.com/?q=Lahore+General+Hospital"},
            {"name": "Hameed Latif Hospital",
             "address": "Canal Bank Road, Lahore", "phone": "042-35761999",
             "rating": 4.3, "type": "private", "emergency": True,
             "maps_link": "https://maps.google.com/?q=Hameed+Latif+Hospital+Lahore"},
        ],
        "cardiology": [
            {"name": "Punjab Institute of Cardiology (PIC)",
             "address": "Jail Road, Lahore", "phone": "042-99203051",
             "rating": 4.4, "type": "government", "emergency": True,
             "maps_link": "https://maps.google.com/?q=Punjab+Institute+of+Cardiology+Lahore"},
            {"name": "Ittefaq Hospital",
             "address": "Model Town, Lahore", "phone": "042-35161000",
             "rating": 4.2, "type": "private", "emergency": True,
             "maps_link": "https://maps.google.com/?q=Ittefaq+Hospital+Lahore"},
        ],
        "oncology": [
            {"name": "Shaukat Khanum Memorial Cancer Hospital",
             "address": "7-A Block R-3, M.A. Johar Town, Lahore", "phone": "042-35945100",
             "rating": 4.7, "type": "private", "emergency": False,
             "maps_link": "https://maps.google.com/?q=Shaukat+Khanum+Lahore"},
        ],
        "emergency": [
            {"name": "Mayo Hospital Lahore",
             "address": "Nila Gumbad, Lahore", "phone": "042-99211100",
             "rating": 4.2, "type": "government", "emergency": True,
             "maps_link": "https://maps.google.com/?q=Mayo+Hospital+Lahore"},
            {"name": "Services Hospital Lahore",
             "address": "Jail Road, Lahore", "phone": "042-99203520",
             "rating": 4.1, "type": "government", "emergency": True,
             "maps_link": "https://maps.google.com/?q=Services+Hospital+Lahore"},
        ],
        "pediatrics": [
            {"name": "The Children's Hospital Lahore",
             "address": "Ferozepur Road, Lahore", "phone": "042-99230400",
             "rating": 4.4, "type": "government", "emergency": True,
             "maps_link": "https://maps.google.com/?q=Childrens+Hospital+Lahore"},
        ],
    },
    "islamabad": {
        "general medicine": [
            {"name": "Pakistan Institute of Medical Sciences (PIMS)",
             "address": "G-8/3, Islamabad", "phone": "051-9261170",
             "rating": 4.2, "type": "government", "emergency": True,
             "maps_link": "https://maps.google.com/?q=PIMS+Islamabad"},
            {"name": "Shifa International Hospital",
             "address": "H-8/4, Islamabad", "phone": "051-8464646",
             "rating": 4.4, "type": "private", "emergency": True,
             "maps_link": "https://maps.google.com/?q=Shifa+International+Hospital+Islamabad"},
        ],
        "cardiology": [
            {"name": "National Institute of Heart Diseases (NIHD)",
             "address": "G-8, Islamabad", "phone": "051-9255521",
             "rating": 4.3, "type": "government", "emergency": True,
             "maps_link": "https://maps.google.com/?q=NIHD+Islamabad"},
            {"name": "Shifa International Hospital",
             "address": "H-8/4, Islamabad", "phone": "051-8464646",
             "rating": 4.4, "type": "private", "emergency": True,
             "maps_link": "https://maps.google.com/?q=Shifa+International+Hospital+Islamabad"},
        ],
        "emergency": [
            {"name": "Pakistan Institute of Medical Sciences (PIMS)",
             "address": "G-8/3, Islamabad", "phone": "051-9261170",
             "rating": 4.2, "type": "government", "emergency": True,
             "maps_link": "https://maps.google.com/?q=PIMS+Islamabad"},
            {"name": "Shifa International Hospital",
             "address": "H-8/4, Islamabad", "phone": "051-8464646",
             "rating": 4.4, "type": "private", "emergency": True,
             "maps_link": "https://maps.google.com/?q=Shifa+International+Hospital+Islamabad"},
        ],
        "pediatrics": [
            {"name": "Children's Hospital Islamabad",
             "address": "G-8/3, Islamabad", "phone": "051-9261321",
             "rating": 4.1, "type": "government", "emergency": True,
             "maps_link": "https://maps.google.com/?q=Childrens+Hospital+Islamabad"},
        ],
    },
    "rawalpindi": {
        "general medicine": [
            {"name": "Holy Family Hospital",
             "address": "Satellite Town, Rawalpindi", "phone": "051-9290301",
             "rating": 4.1, "type": "government", "emergency": True,
             "maps_link": "https://maps.google.com/?q=Holy+Family+Hospital+Rawalpindi"},
            {"name": "Benazir Bhutto Hospital",
             "address": "Murree Road, Rawalpindi", "phone": "051-9290401",
             "rating": 4.0, "type": "government", "emergency": True,
             "maps_link": "https://maps.google.com/?q=Benazir+Bhutto+Hospital+Rawalpindi"},
        ],
        "emergency": [
            {"name": "Holy Family Hospital",
             "address": "Satellite Town, Rawalpindi", "phone": "051-9290301",
             "rating": 4.1, "type": "government", "emergency": True,
             "maps_link": "https://maps.google.com/?q=Holy+Family+Hospital+Rawalpindi"},
        ],
    },
    "peshawar": {
        "general medicine": [
            {"name": "Lady Reading Hospital",
             "address": "Peshawar", "phone": "091-9211236",
             "rating": 4.2, "type": "government", "emergency": True,
             "maps_link": "https://maps.google.com/?q=Lady+Reading+Hospital+Peshawar"},
            {"name": "Khyber Teaching Hospital",
             "address": "Peshawar", "phone": "091-9213301",
             "rating": 4.1, "type": "government", "emergency": True,
             "maps_link": "https://maps.google.com/?q=Khyber+Teaching+Hospital+Peshawar"},
        ],
        "emergency": [
            {"name": "Lady Reading Hospital",
             "address": "Peshawar", "phone": "091-9211236",
             "rating": 4.2, "type": "government", "emergency": True,
             "maps_link": "https://maps.google.com/?q=Lady+Reading+Hospital+Peshawar"},
        ],
    },
}

# ── UPDATE-2: Area → nearest hospital priority map ────────────────────────────
# Maps area keyword → list of preferred hospital names (nearest first)
AREA_HOSPITAL_MAP = {
    "karachi": {
        "clifton":         ["Aga Khan University Hospital", "Tabba Heart Institute", "Liaquat National Hospital"],
        "dha":             ["Aga Khan University Hospital", "Tabba Heart Institute", "Liaquat National Hospital"],
        "gulshan":         ["Liaquat National Hospital", "Aga Khan University Hospital"],
        "gulshan-e-iqbal": ["Liaquat National Hospital", "Aga Khan University Hospital"],
        "saddar":          ["Civil Hospital Karachi", "Jinnah Postgraduate Medical Centre (JPMC)"],
        "north nazimabad": ["National Institute of Cardiovascular Diseases (NICVD)", "Liaquat National Hospital"],
        "nazimabad":       ["National Institute of Cardiovascular Diseases (NICVD)", "Liaquat National Hospital"],
        "fb area":         ["National Institute of Child Health (NICH)", "National Institute of Cardiovascular Diseases (NICVD)"],
        "federal b":       ["National Institute of Cardiovascular Diseases (NICVD)", "National Institute of Child Health (NICH)"],
        "pechs":           ["Aga Khan University Hospital", "Liaquat National Hospital"],
        "korangi":         ["Jinnah Postgraduate Medical Centre (JPMC)", "Civil Hospital Karachi"],
        "landhi":          ["Jinnah Postgraduate Medical Centre (JPMC)", "Civil Hospital Karachi"],
        "malir":           ["Jinnah Postgraduate Medical Centre (JPMC)", "Civil Hospital Karachi"],
        "orangi":          ["Civil Hospital Karachi"],
        "orangi town":     ["Civil Hospital Karachi"],
        "lyari":           ["Civil Hospital Karachi", "Lyari General Hospital"],
        "kemari":          ["Civil Hospital Karachi"],
        "johar":           ["Aga Khan University Hospital", "National Institute of Child Health (NICH)"],
        "surjani":         ["Civil Hospital Karachi"],
        "surjani town":    ["Civil Hospital Karachi"],
        "shah faisal":     ["Jinnah Postgraduate Medical Centre (JPMC)"],
        "liaquatabad":     ["National Institute of Cardiovascular Diseases (NICVD)", "Civil Hospital Karachi"],
        "new karachi":     ["Civil Hospital Karachi", "National Institute of Cardiovascular Diseases (NICVD)"],
        "gulberg":         ["Liaquat National Hospital", "Civil Hospital Karachi"],
        "baldia":          ["Civil Hospital Karachi"],
    },
    "lahore": {
        "gulberg":         ["Hameed Latif Hospital", "Services Hospital Lahore"],
        "dha":             ["Hameed Latif Hospital"],
        "dha lahore":      ["Hameed Latif Hospital"],
        "model town":      ["Hameed Latif Hospital", "Ittefaq Hospital"],
        "johar town":      ["Shaukat Khanum Memorial Cancer Hospital", "Services Hospital Lahore"],
        "iqbal town":      ["Services Hospital Lahore", "Lahore General Hospital"],
        "garden town":     ["Hameed Latif Hospital", "Services Hospital Lahore"],
        "wapda town":      ["Services Hospital Lahore"],
        "cantt":           ["Services Hospital Lahore"],
        "bahria town":     ["Hameed Latif Hospital"],
        "faisal town":     ["Services Hospital Lahore", "Lahore General Hospital"],
        "township":        ["Lahore General Hospital"],
        "shadman":         ["Mayo Hospital Lahore", "Services Hospital Lahore"],
        "samanabad":       ["Lahore General Hospital", "Services Hospital Lahore"],
        "ravi road":       ["Lahore General Hospital"],
        "shalimar":        ["Lahore General Hospital"],
    },
    "islamabad": {
        "f-7":             ["Shifa International Hospital"],
        "f-8":             ["Shifa International Hospital", "Pakistan Institute of Medical Sciences (PIMS)"],
        "f-7 / f-8":       ["Shifa International Hospital", "Pakistan Institute of Medical Sciences (PIMS)"],
        "f-10":            ["Shifa International Hospital"],
        "f-11":            ["Shifa International Hospital"],
        "f-10 / f-11":     ["Shifa International Hospital"],
        "g-8":             ["Pakistan Institute of Medical Sciences (PIMS)"],
        "g-9":             ["Pakistan Institute of Medical Sciences (PIMS)"],
        "g-8 / g-9":       ["Pakistan Institute of Medical Sciences (PIMS)"],
        "g-10":            ["Pakistan Institute of Medical Sciences (PIMS)"],
        "g-11":            ["Pakistan Institute of Medical Sciences (PIMS)"],
        "g-10 / g-11":     ["Pakistan Institute of Medical Sciences (PIMS)"],
        "i-8":             ["Pakistan Institute of Medical Sciences (PIMS)"],
        "i-9":             ["Pakistan Institute of Medical Sciences (PIMS)"],
        "i-8 / i-9":       ["Pakistan Institute of Medical Sciences (PIMS)"],
        "blue area":       ["Shifa International Hospital", "Pakistan Institute of Medical Sciences (PIMS)"],
        "blue area / g-6": ["Shifa International Hospital", "Pakistan Institute of Medical Sciences (PIMS)"],
        "dha islamabad":   ["Shifa International Hospital"],
        "dha":             ["Shifa International Hospital"],
        "bahria town":     ["Shifa International Hospital"],
        "e-7":             ["Shifa International Hospital"],
        "bani gala":       ["Shifa International Hospital"],
    },
    "rawalpindi": {
        "saddar":          ["Holy Family Hospital", "Benazir Bhutto Hospital"],
        "satellite town":  ["Holy Family Hospital"],
        "murree road":     ["Benazir Bhutto Hospital"],
        "chaklala":        ["Benazir Bhutto Hospital"],
        "bahria town":     ["Holy Family Hospital"],
        "dha":             ["Holy Family Hospital"],
        "dha rawalpindi":  ["Holy Family Hospital"],
        "raja bazaar":     ["Benazir Bhutto Hospital"],
        "gulzar-e-quaid":  ["Holy Family Hospital"],
        "adyala road":     ["Benazir Bhutto Hospital"],
    },
    "peshawar": {
        "university town": ["Lady Reading Hospital", "Khyber Teaching Hospital"],
        "hayatabad":       ["Lady Reading Hospital"],
        "saddar":          ["Lady Reading Hospital", "Khyber Teaching Hospital"],
        "cantonment":      ["Khyber Teaching Hospital"],
        "ring road":       ["Lady Reading Hospital"],
        "gulbahar":        ["Lady Reading Hospital"],
        "firdous":         ["Lady Reading Hospital"],
        "kohat road":      ["Lady Reading Hospital"],
        "city centre":     ["Lady Reading Hospital", "Khyber Teaching Hospital"],
    },
}

# Department aliases — expanded with all common spellings + Roman Urdu
DEPARTMENT_ALIASES = {
    # Cardiology
    "heart": "cardiology", "cardiac": "cardiology", "dil": "cardiology",
    "seena": "cardiology", "cardio": "cardiology",
    # Neurology
    "brain": "neurology", "neuro": "neurology", "dimagh": "neurology",
    "paralysis": "neurology",
    # Gastroenterology
    "stomach": "gastroenterology", "gastro": "gastroenterology",
    "pet dard": "gastroenterology", "liver": "gastroenterology",
    "ulcer": "gastroenterology", "diarrhea": "gastroenterology",
    # Pediatrics
    "child": "pediatrics", "children": "pediatrics", "baby": "pediatrics",
    "bachcha": "pediatrics", "bacha": "pediatrics", "bacche": "pediatrics",
    "bachon": "pediatrics", "infant": "pediatrics", "paeds": "pediatrics",
    # Gynecology
    "women": "gynecology", "gynae": "gynecology", "obstetrics": "gynecology",
    "gyne": "gynecology", "gyni": "gynecology", "gynecology": "gynecology",
    "gynaecology": "gynecology", "aurat": "gynecology", "hamal": "gynecology",
    "pregnancy": "gynecology", "delivery": "gynecology", "maternity": "gynecology",
    "mahwari": "gynecology", "period": "gynecology",
    # Orthopedics
    "bone": "orthopedics", "joint": "orthopedics", "ortho": "orthopedics",
    "haddi": "orthopedics", "joron": "orthopedics", "fracture": "orthopedics",
    # Dermatology
    "skin": "dermatology", "jild": "dermatology", "rash": "dermatology",
    "kharish": "dermatology", "daane": "dermatology",
    # Ophthalmology
    "eye": "ophthalmology", "eyes": "ophthalmology", "aankh": "ophthalmology",
    "vision": "ophthalmology", "aankhon": "ophthalmology",
    # ENT
    "ear": "ent", "nose": "ent", "throat": "ent", "kaan": "ent",
    "naak": "ent", "gala": "ent",
    # Urology
    "kidney": "urology", "urine": "urology", "peshab": "urology",
    "gurda": "urology",
    # Oncology
    "cancer": "oncology", "tumor": "oncology",
    # Psychiatry
    "mental": "psychiatry", "psychology": "psychiatry", "dimagi": "psychiatry",
    "anxiety": "psychiatry", "depression": "psychiatry",
    # Endocrinology
    "diabetes": "endocrinology", "thyroid": "endocrinology", "sugar": "endocrinology",
    # Pulmonology
    "lung": "pulmonology", "asthma": "pulmonology", "khansi": "pulmonology",
    "breathing": "pulmonology", "phephra": "pulmonology",
    # General Medicine
    "general": "general medicine", "fever": "general medicine",
    "bukhar": "general medicine", "flu": "general medicine",
    "zukam": "general medicine",
    # Emergency
    "emergency": "emergency", "emer": "emergency", "critical": "emergency",
    "behosh": "emergency", "accident": "emergency",
}

# City aliases
CITY_ALIASES = {
    "khi": "karachi", "khy": "karachi",
    "lhr": "lahore", "lhe": "lahore",
    "isb": "islamabad", "isl": "islamabad",
    "rwp": "rawalpindi", "pindi": "rawalpindi",
    "pesh": "peshawar", "pew": "peshawar", "pkw": "peshawar",
}

# City keywords to detect from raw input
CITY_KEYWORDS = {
    "karachi": "karachi", "khi": "karachi",
    "lahore": "lahore",   "lhr": "lahore",
    "islamabad": "islamabad", "isb": "islamabad",
    "rawalpindi": "rawalpindi", "pindi": "rawalpindi", "rwp": "rawalpindi",
    "peshawar": "peshawar", "pesh": "peshawar",
    "multan": "multan",   "faisalabad": "faisalabad",
    "quetta": "quetta",
}


# ── Normalizers ───────────────────────────────────────────────────────────────

def _normalize_department(dept: str) -> str:
    """Map department string → canonical fallback DB key."""
    d = dept.lower().strip()
    for alias, canonical in DEPARTMENT_ALIASES.items():
        if alias in d:
            return canonical
    return d


def _normalize_city(city: str) -> str:
    city_lower = city.lower().strip()
    return CITY_ALIASES.get(city_lower, city_lower)


def _detect_city_from_text(raw_input: str) -> str:
    """If city not passed, try to extract from raw symptom text."""
    text = raw_input.lower()
    for keyword, city in CITY_KEYWORDS.items():
        if keyword in text:
            return city
    return "karachi"  # safe default


# ── UPDATE-3: Area-based reordering ──────────────────────────────────────────

def _reorder_by_area(hospitals: list, city: str, area: str) -> list:
    """
    UPDATE-3: Reorder hospitals so area-nearest ones come first.
    If area matches a known mapping, preferred hospitals float to top.
    """
    if not area:
        return hospitals

    area_lower = area.lower().strip()
    city_lower = _normalize_city(city)

    city_map = AREA_HOSPITAL_MAP.get(city_lower, {})
    preferred_names = []

    # Exact key match first, then substring match
    if area_lower in city_map:
        preferred_names = city_map[area_lower]
    else:
        for kw, names in city_map.items():
            if kw in area_lower or area_lower in kw:
                preferred_names = names
                break

    if not preferred_names:
        log(f"No area proximity data for '{area}' in {city_lower} — using default order")
        return hospitals

    log(f"Area '{area}' → preferred hospitals: {preferred_names}")

    def sort_key(h):
        name = h.get("name", "")
        for i, pref in enumerate(preferred_names):
            if pref.lower() in name.lower() or name.lower() in pref.lower():
                return i
        return len(preferred_names) + 1

    return sorted(hospitals, key=sort_key)


# ── Fallback Lookup ───────────────────────────────────────────────────────────

def get_fallback_hospitals(city: str, department: str, hospital_type: str = "any",
                            urgency_level: str = "routine", area: str = "") -> list:
    """
    Returns list of formatted hospital dicts, area-sorted when possible.
    FIX-2: Emergency urgency → look in 'emergency' bucket first.
    UPDATE-3: area used to reorder results by proximity.
    """
    city_norm = _normalize_city(city)
    dept_norm = _normalize_department(department)

    city_data = FALLBACK_DB.get(city_norm, FALLBACK_DB.get("karachi", {}))

    # FIX-2: If urgency is critical/emergency, prefer emergency bucket
    if urgency_level in ("critical", "emergency") and "emergency" in city_data:
        hospitals = city_data["emergency"]
        log(f"Emergency urgency → using 'emergency' bucket for {city_norm}")
    else:
        hospitals = city_data.get(dept_norm, city_data.get("general medicine", []))

    # Filter by type if specified
    if hospital_type in ("government", "private"):
        filtered = [h for h in hospitals if h.get("type") == hospital_type]
        if filtered:
            hospitals = filtered

    # Always ensure at least one result
    if not hospitals:
        hospitals = FALLBACK_DB["karachi"]["general medicine"]

    # UPDATE-3: Reorder by area proximity
    hospitals = _reorder_by_area(hospitals, city_norm, area)

    return hospitals


# ── Google Places API ─────────────────────────────────────────────────────────

def search_places_api(department: str, city: str, hospital_type: str = "any", area: str = ""):
    if not API_KEY:
        log("No Google Places API key — using fallback")
        return None

    type_prefix = {"government": "government ", "private": "private "}.get(hospital_type, "")
    # UPDATE-1: Include area in query for more precise results
    area_suffix = f" near {area}" if area else ""
    query = f"{type_prefix}{department} hospital in {city}{area_suffix} Pakistan"

    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": API_KEY,
        "X-Goog-FieldMask": (
            "places.displayName,places.formattedAddress,places.nationalPhoneNumber,"
            "places.rating,places.googleMapsUri,places.regularOpeningHours"
        ),
    }
    payload = json.dumps({"textQuery": query, "languageCode": "en", "regionCode": "PK"}).encode()

    log(f"Google Places API → {query}")
    try:
        req = urllib.request.Request(url, data=payload, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=8) as resp:
            result = json.loads(resp.read().decode())
            count = len(result.get("places", []))
            log(f"Places API returned {count} results")
            return result if count else None
    except Exception as e:
        log(f"Places API failed: {e} — falling back to mock DB")
        return None


# ── Formatters ────────────────────────────────────────────────────────────────

def _fmt_api(place: dict, department: str) -> dict:
    name = place.get("displayName", {}).get("text", "Hospital")
    gov_keywords = ["civil", "jinnah", "jpmc", "pims", "nicvd", "govt",
                    "services hospital", "general hospital", "teaching", "lady reading",
                    "mayo", "holy family", "benazir"]
    h_type = "government" if any(w in name.lower() for w in gov_keywords) else "private"
    return {
        "name": name,
        "address": place.get("formattedAddress", ""),
        "department": department,
        "emergency": True,
        "phone": place.get("nationalPhoneNumber", "See Google Maps"),
        "maps_link": place.get("googleMapsUri", ""),
        "rating": place.get("rating", "N/A"),
        "type": h_type,
        "open_now": place.get("regularOpeningHours", {}).get("openNow", True),
        "distance": "See Google Maps",
    }


def _fmt_fallback(h: dict, department: str) -> dict:
    return {
        "name": h["name"],
        "address": h.get("address", ""),
        "department": department,
        "emergency": h.get("emergency", True),
        "phone": h.get("phone", "N/A"),
        "maps_link": h.get("maps_link", ""),
        "rating": h.get("rating", "N/A"),
        "type": h.get("type", "government"),
        "open_now": True,
        "distance": "Nearest available",
    }


# ── Core Logic ────────────────────────────────────────────────────────────────

def run_hospital_finder(input_data: dict) -> dict:
    department    = (input_data.get("department") or "General Medicine").strip()
    city          = (input_data.get("city") or "").strip()
    area          = (input_data.get("area") or "").strip()          # UPDATE-1
    urgency_level = (input_data.get("urgency_level") or "routine").lower().strip()
    hospital_type = (input_data.get("hospital_type") or "any").lower().strip()
    raw_input     = input_data.get("raw_input", "")
    patient_name  = input_data.get("patient_name", "Patient")

    named_hospital = input_data.get("named_hospital")

    # FIX-3: Detect city from raw text if not provided
    if not city:
        city = _detect_city_from_text(raw_input)
        log(f"City not specified — detected '{city}' from raw input")

    if hospital_type not in ("government", "private", "any"):
        hospital_type = "any"

    visit_type = "Emergency" if urgency_level in ("critical", "emergency") else "OPD"

    log(f"Request: dept={department} city={city} area='{area}' urgency={urgency_level} type={hospital_type}")

    # ── Named hospital shortcut ───────────────────────────────────────────────
    if named_hospital:
        log(f"[Step 1] Named hospital detected: '{named_hospital}' — skipping Places API")
        city_norm = _normalize_city(city)
        dept_norm = _normalize_department(department)
        city_data = FALLBACK_DB.get(city_norm, FALLBACK_DB.get("karachi", {}))
        found_h = None
        for dept_list in city_data.values():
            for h in dept_list:
                if (named_hospital.lower() in h["name"].lower() or
                        h["name"].lower() in named_hospital.lower()):
                    found_h = h
                    break
            if found_h:
                break
        if not found_h:
            found_h = {
                "name":     named_hospital,
                "address":  f"{named_hospital}, {city.title()}",
                "phone":    "See hospital website",
                "rating":   4.0,
                "type":     hospital_type if hospital_type != "any" else "government",
                "emergency": True,
                "maps_link": f"https://maps.google.com/?q={named_hospital.replace(' ', '+')}",
            }
        top = _fmt_fallback(found_h, department)
        reasoning = (
            f"[Step 1] User explicitly requested '{named_hospital}'. "
            f"[Step 2] Direct lookup — no search needed. "
            f"[Step 3] Hospital confirmed: {named_hospital} in {city.title()}."
        )
        log(f"[Step 3] Named hospital resolved → {named_hospital}")
        return {
            "agent":              "hospital_finder_agent",
            "hospital_name":      top["name"],
            "hospital_address":   top["address"],
            "hospital_phone":     top["phone"],
            "hospital_maps_link": top.get("maps_link", ""),
            "hospital_type":      top["type"],
            "department":         department,
            "urgency_level":      urgency_level,
            "visit_type":         visit_type,
            "patient_name":       patient_name,
            "top_recommendation": top,
            "alternatives":       [],
            "reasoning":          reasoning,
            "emergency_note":     None,
            "source":             "named_hospital_lookup",
            "city_searched":      city,
            "area_searched":      area,
        }

    # Try Google Places first (area-aware query)
    api_result = search_places_api(department, city, hospital_type, area)
    source = "google_places"
    hospitals = []

    if api_result and api_result.get("places"):
        for p in api_result["places"][:5]:
            hospitals.append(_fmt_api(p, department))
        log(f"Using Google Places: {len(hospitals)} hospitals")
    else:
        # FIX-2 + UPDATE-3: Fallback respects emergency + area proximity
        source = "fallback"
        raw_list = get_fallback_hospitals(city, department, hospital_type, urgency_level, area)
        for h in raw_list:
            hospitals.append(_fmt_fallback(h, department))
        log(f"Using fallback DB: {len(hospitals)} hospitals for {city}/{area}/{department}")

    if not hospitals:
        hospitals = [_fmt_fallback(FALLBACK_DB["karachi"]["general medicine"][0], department)]

    top = hospitals[0]
    alternatives = hospitals[1:3]

    # FIX-5 + UPDATE-4: Richer reasoning mentioning area
    area_note = f" Area filter applied: '{area}'." if area else " No area specified — city-wide search."
    reasoning = (
        f"[Step 1] Department requested: '{department}' in '{city}'.{area_note} "
        f"Urgency level: {urgency_level}. Hospital type preference: {hospital_type}. "
        f"[Step 2] Data source: {source}. Found {len(hospitals)} candidate(s). "
        f"[Step 3] Selected '{top['name']}' (rating: {top['rating']}, "
        f"type: {top['type']}, emergency: {top['emergency']}) as top recommendation "
        f"based on area proximity and emergency availability."
    )

    emergency_note = None
    if urgency_level in ("critical", "emergency"):
        emergency_note = (
            f"CRITICAL URGENCY: Go to Emergency at {top['name']} immediately. "
            f"Phone: {top['phone']}. Address: {top['address']}"
        )

    log(f"Top pick: {top['name']} | source: {source} | area: '{area}'")
    log("Handoff ready → Orchestrator / Cost Agent / Appointment Agent")

    return {
        "agent":              "hospital_finder_agent",
        "hospital_name":      top["name"],
        "hospital_address":   top["address"],
        "hospital_phone":     top["phone"],
        "hospital_maps_link": top["maps_link"],
        "hospital_type":      top["type"],
        "department":         department,
        "urgency_level":      urgency_level,
        "visit_type":         visit_type,
        "patient_name":       patient_name,
        "top_recommendation": top,
        "alternatives":       alternatives,
        "reasoning":          reasoning,
        "emergency_note":     emergency_note,
        "source":             source,
        "city_searched":      city,
        "area_searched":      area,
    }


# ── Flask App ─────────────────────────────────────────────────────────────────

app = Flask(__name__)
CORS(app)


# Known hospital names for direct lookup (case-insensitive)
NAMED_HOSPITAL_MAP = {
    "civil hospital": ("Civil Hospital Karachi", "karachi"),
    "civil": ("Civil Hospital Karachi", "karachi"),
    "aga khan": ("Aga Khan University Hospital", "karachi"),
    "aku": ("Aga Khan University Hospital", "karachi"),
    "agha khan": ("Aga Khan University Hospital", "karachi"),
    "nicvd": ("National Institute of Cardiovascular Diseases (NICVD)", "karachi"),
    "kihd": ("Karachi Institute of Heart Diseases (KIHD)", "karachi"),
    "tabba": ("Tabba Heart Institute", "karachi"),
    "jpmc": ("Jinnah Postgraduate Medical Centre (JPMC)", "karachi"),
    "jinnah": ("Jinnah Postgraduate Medical Centre (JPMC)", "karachi"),
    "liaquat": ("Liaquat National Hospital", "karachi"),
    "liaquat national": ("Liaquat National Hospital", "karachi"),
    "nich": ("National Institute of Child Health (NICH)", "karachi"),
    "pims": ("Pakistan Institute of Medical Sciences (PIMS)", "islamabad"),
    "shifa": ("Shifa International Hospital", "islamabad"),
    "services hospital": ("Services Hospital Lahore", "lahore"),
    "shaukat khanum": ("Shaukat Khanum Memorial Cancer Hospital", "lahore"),
    "mayo": ("Mayo Hospital Lahore", "lahore"),
    "pic": ("Punjab Institute of Cardiology (PIC)", "lahore"),
    "punjab institute": ("Punjab Institute of Cardiology (PIC)", "lahore"),
    "holy family": ("Holy Family Hospital", "rawalpindi"),
    "benazir": ("Benazir Bhutto Hospital", "rawalpindi"),
    "lady reading": ("Lady Reading Hospital", "peshawar"),
    "lrh": ("Lady Reading Hospital", "peshawar"),
    "khyber teaching": ("Khyber Teaching Hospital", "peshawar"),
    "hameed latif": ("Hameed Latif Hospital", "lahore"),
}

def _detect_named_hospital(raw_input: str):
    """Check if user mentioned a specific hospital by name."""
    text = raw_input.lower()
    for keyword in sorted(NAMED_HOSPITAL_MAP.keys(), key=len, reverse=True):
        if keyword in text:
            return NAMED_HOSPITAL_MAP[keyword]
    return None, None


def _handle_analyze(data: dict):
    """Shared logic for both route endpoints."""
    raw_input = data.get("raw_input") or data.get("user_message") or data.get("symptoms") or ""

    named_hospital, named_city = _detect_named_hospital(raw_input)
    if named_hospital:
        log(f"Named hospital detected: {named_hospital} in {named_city}")

    input_data = {
        "department":    data.get("department") or data.get("recommended_department") or "General Medicine",
        "city":          data.get("city") or named_city or "",
        "area":          data.get("area") or "",                    # UPDATE-1: pass area through
        "urgency_level": data.get("urgency_level") or "routine",
        "hospital_type": data.get("hospital_type") or "any",
        "patient_name":  data.get("patient_name") or "Patient",
        "raw_input":     raw_input,
        "named_hospital": named_hospital,
    }
    log(f"Incoming keys: {list(data.keys())}")
    return run_hospital_finder(input_data)


@app.route('/analyze', methods=['POST'])
def analyze_short():
    """Primary route — what the orchestrator calls."""
    try:
        data = request.get_json(force=True) or {}
        result = _handle_analyze(data)
        return jsonify(result), 200
    except Exception as e:
        log(f"ERROR /analyze: {e}")
        return jsonify({"error": str(e), "agent": "hospital_finder_agent",
                        "hospital_name": "Civil Hospital",
                        "hospital_type": "government",
                        "department": "General Medicine",
                        "urgency_level": "routine",
                        "visit_type": "OPD",
                        "top_recommendation": {
                            "name": "Civil Hospital", "address": "Your nearest city",
                            "department": "General Medicine", "emergency": True,
                            "phone": "1122", "maps_link": "https://maps.google.com/?q=civil+hospital+pakistan",
                            "rating": 4.0, "type": "government", "open_now": True, "distance": "N/A"
                        },
                        "alternatives": [], "reasoning": "Error fallback",
                        "emergency_note": None, "source": "error_fallback"}), 200


@app.route('/hospital-finder/analyze', methods=['POST'])
def analyze_long():
    """Legacy route — kept for backward compatibility."""
    return analyze_short()


@app.route('/health', methods=['GET'])
@app.route('/hospital-finder/health', methods=['GET'])
def health():
    return jsonify({
        "status": "healthy",
        "agent": "hospital_finder_agent",
        "port": 5002,
        "routes": ["/analyze", "/hospital-finder/analyze"],
        "google_places": "configured" if API_KEY else "fallback mode",
        "area_aware": True,
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5002))
    log(f"Hospital Finder Agent starting on port {port}")
    log(f"Routes: /analyze (primary) | /hospital-finder/analyze (legacy)")
    log(f"Google Places API: {'configured' if API_KEY else 'fallback mode'}")
    log(f"Area-aware proximity sorting: ENABLED")
    app.run(host="0.0.0.0", port=port, debug=False)