EMERGENCY_KEYWORDS = [
    # English
    "severe chest pain", "chest pain", "difficulty breathing", "can't breathe",
    "unconscious", "heavy bleeding", "sudden weakness", "stroke", "heart attack",
    "suicidal", "severe burn", "poisoning", "seizure", "choking",
    "loss of consciousness", "coughing blood", "ambulance", "dying",
    "head injury", "snake bite", "accident", "heat stroke", "heatstroke",
    "breathing stopped",
    # Roman Urdu
    "behosh", "behoshi", "behosh ho gaya", "behosh hogaya",
    "hosh nahi", "hosh kho diya",
    "dil ka daura", "saanp ne kaata", "hadsa",
    "khoon nahi ruk raha", "fit", "fitting",
    "sar pe chot", "zeher", "saans nahi",
    "maut", "mar raha", "mar rahi",
]

def get_follow_up_question(symptoms, context=""):
    """
    Returns a single follow up question based on the symptoms.
    Maximum one question at a time.
    """
    symptoms_lower = symptoms.lower()
    
    if any(keyword in symptoms_lower for keyword in ["chest", "heart"]):
        return "Are you experiencing severe chest pain that radiates to your arm, back, or jaw?"
    elif "headache" in symptoms_lower:
        return "Is this the worst headache of your life, or accompanied by vision changes or numbness?"
    elif "stomach" in symptoms_lower or "abdominal" in symptoms_lower:
        return "Is the pain localized to one specific area (like the lower right side) or is it a general discomfort?"
    elif "fever" in symptoms_lower:
        return "How high is your fever, and how many days have you had it?"
    elif "cough" in symptoms_lower:
        return "Are you coughing up any blood or thick discolored mucus?"
    
    return "Could you provide a bit more detail about when these symptoms started and how severe they are?"

def is_emergency(text):
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in EMERGENCY_KEYWORDS)
