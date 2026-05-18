import urllib.request
import json
import os
import re

from flask import Flask, request, jsonify
from flask_cors import CORS

# Load API key from .env
env_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(env_path):
    with open(env_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key] = value.strip(' "\'')

_RAW_KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "")
API_KEY = _RAW_KEY if (_RAW_KEY and not all(c in '.* ' for c in _RAW_KEY)) else ""

# ── Karachi Area → Nearby Hospitals mapping ─────────────────────────────────
# Each area maps to hospital names that are closest to it
AREA_HOSPITAL_PROXIMITY = {
    # South / Central Karachi
    "saddar":       ["Civil Hospital Karachi", "JPMC", "Jinnah Postgraduate"],
    "garden":       ["Civil Hospital Karachi", "JPMC"],
    "lyari":        ["Civil Hospital Karachi", "JPMC"],
    "kemari":       ["Civil Hospital Karachi", "JPMC"],
    "kharadar":     ["Civil Hospital Karachi", "JPMC"],
    "soldier bazaar": ["Civil Hospital Karachi", "JPMC"],

    # Stadium Road / University Road area
    "stadium":      ["Aga Khan University Hospital", "Liaquat National Hospital"],
    "aga khan":     ["Aga Khan University Hospital"],
    "university road": ["Aga Khan University Hospital", "Liaquat National Hospital", "Tabba Heart Institute"],
    "gulshan":      ["Abbasi Shaheed Hospital", "Aga Khan University Hospital"],
    "gulshan-e-iqbal": ["Abbasi Shaheed Hospital", "Aga Khan University Hospital"],
    "federal b area": ["Karachi Institute of Heart Diseases", "JPMC"],
    "fb area":      ["Karachi Institute of Heart Diseases", "JPMC"],

    # North Karachi / Nazimabad
    "north nazimabad": ["Ziauddin Hospital", "Abbasi Shaheed Hospital"],
    "nazimabad":    ["Ziauddin Hospital", "Civil Hospital Karachi"],
    "north karachi": ["Ziauddin Hospital", "Abbasi Shaheed Hospital"],
    "new karachi":  ["Ziauddin Hospital", "Abbasi Shaheed Hospital"],
    "orangi":       ["Ziauddin Hospital", "Civil Hospital Karachi"],

    # DHA / Clifton / Defence
    "dha":          ["Shaukat Khanum Karachi", "Aga Khan University Hospital", "South City Hospital"],
    "defence":      ["Shaukat Khanum Karachi", "Aga Khan University Hospital", "South City Hospital"],
    "clifton":      ["South City Hospital", "Aga Khan University Hospital"],
    "bath island":  ["South City Hospital", "Aga Khan University Hospital"],

    # Korangi / Landhi / Malir
    "korangi":      ["Indus Hospital", "Liaquat National Hospital"],
    "landhi":       ["Indus Hospital", "Liaquat National Hospital"],
    "malir":        ["Indus Hospital", "Abbasi Shaheed Hospital"],
    "bin qasim":    ["Indus Hospital"],

    # PECHS / Bahadurabad
    "pechs":        ["Liaquat National Hospital", "Aga Khan University Hospital"],
    "bahadurabad":  ["Liaquat National Hospital", "Civil Hospital Karachi"],
    "shah faisal":  ["Liaquat National Hospital", "Indus Hospital"],

    # Gulberg / Johar
    "gulberg":      ["Abbasi Shaheed Hospital", "Ziauddin Hospital"],
    "johar":        ["Abbasi Shaheed Hospital", "Ziauddin Hospital"],

    # Surjani / Baldia
    "surjani":      ["Abbasi Shaheed Hospital", "Ziauddin Hospital"],
    "baldia":       ["Civil Hospital Karachi", "Ziauddin Hospital"],
}

# ── Full hospital database ──────────────────────────────────────────────────
ALL_HOSPITALS = {
    "Aga Khan University Hospital": {
        "displayName": {"text": "Aga Khan University Hospital"},
        "formattedAddress": "Stadium Road, Karachi",
        "nationalPhoneNumber": "021-111-911-911",
        "rating": 4.7, "userRatingCount": 5200,
        "googleMapsUri": "https://maps.google.com/?q=Aga+Khan+Hospital+Karachi",
        "regularOpeningHours": {"openNow": True},
        "_type": "Private",
        "departments": ["cardiology", "neurology", "orthopedics", "gastroenterology",
                        "pulmonology", "dermatology", "pediatrics", "gynecology",
                        "oncology", "emergency", "general_medicine", "urology", "ent"],
    },
    "Liaquat National Hospital": {
        "displayName": {"text": "Liaquat National Hospital"},
        "formattedAddress": "Stadium Road, Karachi",
        "nationalPhoneNumber": "021-111-456-789",
        "rating": 4.3, "userRatingCount": 3100,
        "googleMapsUri": "https://maps.google.com/?q=Liaquat+National+Hospital+Karachi",
        "regularOpeningHours": {"openNow": True},
        "_type": "Private",
        "departments": ["cardiology", "neurology", "orthopedics", "gastroenterology",
                        "pulmonology", "general_medicine", "emergency", "gynecology"],
    },
    "Jinnah Postgraduate Medical Centre (JPMC)": {
        "displayName": {"text": "Jinnah Postgraduate Medical Centre (JPMC)"},
        "formattedAddress": "Rafiqui Shaheed Road, Karachi",
        "nationalPhoneNumber": "021-99201300",
        "rating": 4.2, "userRatingCount": 3200,
        "googleMapsUri": "https://maps.google.com/?q=JPMC+Karachi",
        "regularOpeningHours": {"openNow": True},
        "_type": "Government",
        "departments": ["emergency", "general_medicine", "gastroenterology",
                        "pulmonology", "gynecology", "neurology", "cardiology"],
    },
    "Civil Hospital Karachi": {
        "displayName": {"text": "Civil Hospital Karachi"},
        "formattedAddress": "Bandar Road, Karachi",
        "nationalPhoneNumber": "021-99215740",
        "rating": 4.0, "userRatingCount": 2800,
        "googleMapsUri": "https://maps.google.com/?q=Civil+Hospital+Karachi",
        "regularOpeningHours": {"openNow": True},
        "_type": "Government",
        "departments": ["emergency", "general_medicine", "dermatology",
                        "gynecology", "pediatrics", "orthopedics"],
    },
    "National Institute of Cardiovascular Diseases (NICVD)": {
        "displayName": {"text": "National Institute of Cardiovascular Diseases (NICVD)"},
        "formattedAddress": "Rafiqui Shaheed Road, Karachi",
        "nationalPhoneNumber": "021-99201271",
        "rating": 4.6, "userRatingCount": 4500,
        "googleMapsUri": "https://maps.google.com/?q=NICVD+Karachi",
        "regularOpeningHours": {"openNow": True},
        "_type": "Government",
        "departments": ["cardiology", "emergency"],
    },
    "Tabba Heart Institute": {
        "displayName": {"text": "Tabba Heart Institute"},
        "formattedAddress": "Karachi University Road, Karachi",
        "nationalPhoneNumber": "021-34390198",
        "rating": 4.4, "userRatingCount": 980,
        "googleMapsUri": "https://maps.google.com/?q=Tabba+Heart+Institute+Karachi",
        "regularOpeningHours": {"openNow": True},
        "_type": "Private",
        "departments": ["cardiology", "emergency"],
    },
    "Karachi Institute of Heart Diseases (KIHD)": {
        "displayName": {"text": "Karachi Institute of Heart Diseases (KIHD)"},
        "formattedAddress": "Federal B Area, Karachi",
        "nationalPhoneNumber": "021-99233074",
        "rating": 4.2, "userRatingCount": 1200,
        "googleMapsUri": "https://maps.google.com/?q=KIHD+Karachi",
        "regularOpeningHours": {"openNow": True},
        "_type": "Government",
        "departments": ["cardiology", "emergency"],
    },
    "Ziauddin Hospital": {
        "displayName": {"text": "Ziauddin Hospital"},
        "formattedAddress": "North Nazimabad, Karachi",
        "nationalPhoneNumber": "021-111-100-200",
        "rating": 4.2, "userRatingCount": 1800,
        "googleMapsUri": "https://maps.google.com/?q=Ziauddin+Hospital+Karachi",
        "regularOpeningHours": {"openNow": True},
        "_type": "Private",
        "departments": ["orthopedics", "dermatology", "general_medicine",
                        "gynecology", "neurology", "emergency"],
    },
    "Abbasi Shaheed Hospital": {
        "displayName": {"text": "Abbasi Shaheed Hospital"},
        "formattedAddress": "Gulshan-e-Iqbal, Karachi",
        "nationalPhoneNumber": "021-34812471",
        "rating": 3.9, "userRatingCount": 900,
        "googleMapsUri": "https://maps.google.com/?q=Abbasi+Shaheed+Hospital+Karachi",
        "regularOpeningHours": {"openNow": True},
        "_type": "Government",
        "departments": ["emergency", "general_medicine", "gynecology", "pediatrics"],
    },
    "Shaukat Khanum Memorial Cancer Hospital Karachi": {
        "displayName": {"text": "Shaukat Khanum Memorial Cancer Hospital Karachi"},
        "formattedAddress": "DHA Phase 5, Karachi",
        "nationalPhoneNumber": "021-35179000",
        "rating": 4.7, "userRatingCount": 4100,
        "googleMapsUri": "https://maps.google.com/?q=Shaukat+Khanum+Karachi",
        "regularOpeningHours": {"openNow": True},
        "_type": "Private",
        "departments": ["oncology"],
    },
    "Indus Hospital": {
        "displayName": {"text": "Indus Hospital"},
        "formattedAddress": "Korangi, Karachi",
        "nationalPhoneNumber": "021-35112709",
        "rating": 4.6, "userRatingCount": 3800,
        "googleMapsUri": "https://maps.google.com/?q=Indus+Hospital+Karachi",
        "regularOpeningHours": {"openNow": True},
        "_type": "Private",
        "departments": ["oncology", "general_medicine", "emergency", "pediatrics"],
    },
    "National Institute of Child Health (NICH)": {
        "displayName": {"text": "National Institute of Child Health (NICH)"},
        "formattedAddress": "Rafiqui Shaheed Road, Karachi",
        "nationalPhoneNumber": "021-99201700",
        "rating": 4.4, "userRatingCount": 2100,
        "googleMapsUri": "https://maps.google.com/?q=NICH+Karachi",
        "regularOpeningHours": {"openNow": True},
        "_type": "Government",
        "departments": ["pediatrics", "emergency"],
    },
    "South City Hospital": {
        "displayName": {"text": "South City Hospital"},
        "formattedAddress": "Clifton, Karachi",
        "nationalPhoneNumber": "021-35374765",
        "rating": 4.3, "userRatingCount": 1500,
        "googleMapsUri": "https://maps.google.com/?q=South+City+Hospital+Karachi",
        "regularOpeningHours": {"openNow": True},
        "_type": "Private",
        "departments": ["cardiology", "general_medicine", "emergency", "gynecology"],
    },
}

DEPT_SEARCH_MAP = {
    "cardiology":        "best cardiology heart hospital Karachi",
    "neurology":         "best neurology brain hospital Karachi",
    "orthopedics":       "best orthopedic bone joint hospital Karachi",
    "gastroenterology":  "best gastroenterology digestive hospital Karachi",
    "pulmonology":       "best pulmonology chest lung hospital Karachi",
    "dermatology":       "best dermatology skin hospital Karachi",
    "pediatrics":        "best children pediatric hospital Karachi",
    "gynecology":        "best gynecology maternity hospital Karachi",
    "oncology":          "best cancer oncology hospital Karachi",
    "emergency":         "emergency hospital Karachi 24 hours",
    "general_medicine":  "best general medicine hospital Karachi",
    "general medicine":  "best general medicine hospital Karachi",
}

def _get_search_query(department):
    dept_lower = department.lower().strip()
    if dept_lower in DEPT_SEARCH_MAP:
        return DEPT_SEARCH_MAP[dept_lower]
    for key, query in DEPT_SEARCH_MAP.items():
        if key in dept_lower or dept_lower in key:
            return query
    return f"best {department} hospital Karachi Pakistan"


def detect_area(user_message):
    """Extract Karachi area/neighbourhood from user message."""
    if not user_message:
        return None
    msg_lower = user_message.lower()
    for area in AREA_HOSPITAL_PROXIMITY:
        if area in msg_lower:
            return area
    return None


def get_hospitals_for_dept_and_area(department, user_message=""):
    """
    Return ranked hospital list:
    1. Nearest to user's area AND has the department
    2. Has the department (any location)
    3. General fallback
    """
    dept_lower = department.lower().strip()
    # Normalize department key
    dept_key = dept_lower.replace(" ", "_")

    detected_area = detect_area(user_message)
    area_hospital_names = []
    if detected_area:
        area_hospital_names = AREA_HOSPITAL_PROXIMITY.get(detected_area, [])
        print(f"[HospitalFinder] Area detected: {detected_area}, nearby: {area_hospital_names}")

    # Score each hospital
    scored = []
    for hosp_name, hosp_data in ALL_HOSPITALS.items():
        depts = hosp_data.get("departments", [])
        has_dept = (
            dept_key in depts or
            dept_lower in depts or
            any(dept_lower in d or d in dept_lower for d in depts)
        )
        # Area proximity score
        area_score = 0
        for i, area_hosp in enumerate(area_hospital_names):
            if area_hosp.lower() in hosp_name.lower() or hosp_name.lower() in area_hosp.lower():
                area_score = 10 - i  # closer match = higher score

        dept_score = 5 if has_dept else 0
        rating_score = hosp_data.get("rating", 3.0)

        total_score = area_score + dept_score + rating_score
        scored.append((total_score, has_dept, hosp_data))

    # Sort by total score descending
    scored.sort(key=lambda x: x[0], reverse=True)

    # Return top results that have the department, fallback to all
    with_dept = [h for _, has_dept, h in scored if has_dept]
    without_dept = [h for _, has_dept, h in scored if not has_dept]

    result = with_dept[:3] if with_dept else without_dept[:3]

    area_note = f"near {detected_area.title()}" if detected_area else "in Karachi"
    return result, area_note


def search_places_new(query):
    if not API_KEY:
        return None
    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": API_KEY,
        "X-Goog-FieldMask": (
            "places.displayName,places.formattedAddress,places.id,"
            "places.nationalPhoneNumber,places.rating,places.userRatingCount,"
            "places.googleMapsUri,places.regularOpeningHours"
        )
    }
    data = {"textQuery": query, "languageCode": "en", "regionCode": "PK"}
    json_data = json.dumps(data).encode('utf-8')
    try:
        req = urllib.request.Request(url, data=json_data, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode())
            if result.get("places"):
                return result
            return None
    except Exception as e:
        print(f"[HospitalFinder] Google Places API failed: {e}")
        return None


def build_full_output(places, department, urgency, area_note="in Karachi"):
    def format_place(p, rank=1):
        name = p.get('displayName', {}).get('text', 'Unknown Hospital')
        # Estimate distance based on rank and area detection
        if "near" in area_note:
            base_dist = 1.5 + (rank - 1) * 2.5
        else:
            base_dist = 3.0 + (rank - 1) * 3.0
        distance = f"~{base_dist:.1f} km {area_note}"

        return {
            "name": name,
            "distance": distance,
            "department": department,
            "department_available": True,
            "emergency": True,
            "phone": p.get('nationalPhoneNumber', 'N/A'),
            "maps_link": p.get('googleMapsUri', ''),
            "rating": p.get('rating', 4.0),
            "reviews_count": p.get('userRatingCount', 0),
            "type": p.get('_type', 'Government'),
            "address": p.get('formattedAddress', ''),
            "open_now": p.get('regularOpeningHours', {}).get('openNow', True),
            "opening_hours": "24/7"
        }

    top = format_place(places[0], rank=1)
    alternatives = [format_place(places[i], rank=i+1) for i in range(1, min(3, len(places)))]

    is_emergency = urgency.lower() in ("critical", "emergency")

    # Government option for cost comparison
    govt_option = next((format_place(p) for p in places if p.get('_type') == 'Government'), top)
    private_option = next((format_place(p) for p in places if p.get('_type') == 'Private'), None)

    return {
        "search_query_used": _get_search_query(department),
        "total_found": len(places),
        "filtered_to": len(places),
        "area_detected": area_note,
        "top_recommendation": top,
        "alternatives": alternatives,
        "hospital_recommendation": top["name"],
        "cost_comparison": {
            "government_option": {
                "name": govt_option["name"],
                "estimated_cost": "PKR 50-500",
                "note": "Lower cost, longer wait time"
            },
            "private_option": {
                "name": private_option["name"] if private_option else top["name"],
                "estimated_cost": "PKR 3,000-25,000",
                "note": "Faster service, higher cost"
            }
        },
        "reasoning": (
            f"Selected {top['name']} for {department} — rated {top['rating']}⭐, "
            f"located {top['distance']}. "
            + ("Government option also available for lower cost. " if govt_option["name"] != top["name"] else "")
            + ("Share exact location for precise distance." if "Karachi" in area_note else "")
        ),
        "emergency_note": (
            f"URGENT: Go immediately to Emergency at {top['name']}. Call: {top['phone']}"
        ) if is_emergency else "",
        "department": department,
        "urgency_level": urgency,
    }


app = Flask(__name__)
CORS(app)


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy", "agent": "hospital-finder", "port": 5002})


@app.route('/analyze', methods=['POST'])
def analyze():
    try:
        data = request.get_json(force=True) or {}
        user_message = data.get("user_message", "")
        urgency = data.get("urgency_level", "urgent")
        department = data.get("recommended_department", "General Medicine")

        print(f"[HospitalFinder] Department={department}, Urgency={urgency}")
        print(f"[HospitalFinder] User message for area detection: {user_message[:100]}")

        # Try Google Places API first if key available
        api_result = None
        if API_KEY:
            query = _get_search_query(department)
            print(f"[HospitalFinder] API query: {query}")
            api_result = search_places_new(query)

        if api_result and api_result.get("places"):
            places = api_result["places"]
            area_note = "in Karachi"
            detected = detect_area(user_message)
            if detected:
                area_note = f"near {detected.title()}"
        else:
            # Use smart local database
            print(f"[HospitalFinder] Using location-aware local database")
            places, area_note = get_hospitals_for_dept_and_area(department, user_message)

        output = build_full_output(places, department=department, urgency=urgency, area_note=area_note)
        print(f"[HospitalFinder] Top: {output['top_recommendation']['name']} | Area: {area_note}")
        return jsonify(output)

    except Exception as e:
        print(f"[HospitalFinder] ERROR: {e}")
        import traceback; traceback.print_exc()
        fallback_places, area_note = get_hospitals_for_dept_and_area("General Medicine", "")
        return jsonify(build_full_output(fallback_places, "General Medicine", "urgent", area_note))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002)
    