# questions.py
# ─────────────────────────────────────────────────────────────────
# Follow-up question logic for Sehat Agent's Symptom Agent.
# FIX: Language-aware questions + Pakistani emergency keywords.
# ─────────────────────────────────────────────────────────────────

# FIX: Added Pakistani emergency keywords (Urdu + Roman Urdu + English)
EMERGENCY_KEYWORDS = [
    # English
    "unconscious", "not breathing", "can't breathe", "cannot breathe",
    "heavy bleeding", "bleeding won't stop", "heart attack", "stroke",
    "severe burn", "poisoning", "seizure", "choking", "overdose",
    "suicide", "suicidal", "loss of consciousness", "coughing blood",
    "vomiting blood", "severe chest pain", "difficulty breathing",
    "sudden weakness", "paralysis", "anaphylaxis", "allergic reaction severe",

    # Roman Urdu
    "behosh", "behosh ho gaya", "behosh ho gayi",
    "saans nahi", "saans ruk", "saans band",
    "khoon nahi ruk raha", "bahut khoon",
    "accident", "hadsa", "girgaya", "girna",
    "zeher", "zeher kha liya", "zeher pi liya",
    "dil ka daura", "heart fail",
    "fit", "fitting", "mirgi",
    "sar pe chot", "sir pe chot",
    "jal gaya", "jal gayi", "jalana",
    "bachcha paida", "delivery emergency",
    "snake", "saanp ne kaata", "kaata",
    "bijli lagi", "current laga",

    # Urdu script
    "بے ہوش", "سانس نہیں", "خون نہیں رک", "حادثہ",
    "زہر", "دل کا دورہ", "فٹ", "مرگی"
]


# ─── Language-aware follow-up questions ───────────────────────────

FOLLOW_UP_QUESTIONS = {
    # KEY: symptom keyword → {english, roman_urdu, urdu}
    "chest": {
        "english":    "Is the chest pain sharp or dull, and does it radiate to your arm, jaw, or back?",
        "roman_urdu": "Seene ka dard tez hai ya halka, aur kya yeh haath, jaws, ya peeth tak jaata hai?",
        "urdu":       "کیا سینے کا درد تیز ہے یا ہلکا، اور کیا یہ بازو یا کمر تک جاتا ہے؟"
    },
    "heart": {
        "english":    "Are you also feeling shortness of breath or dizziness along with the chest pain?",
        "roman_urdu": "Kya seene ke dard ke saath saans lene mein takleef ya chakkar bhi hai?",
        "urdu":       "کیا سینے کے درد کے ساتھ سانس لینے میں دشواری یا چکر بھی ہے؟"
    },
    "headache": {
        "english":    "Is this the worst headache you have ever had, or do you have vision changes or neck stiffness?",
        "roman_urdu": "Kya yeh aapki zindagi ka sabse bura sar dard hai, ya aankhon mein bhi masla hai?",
        "urdu":       "کیا یہ آپ کی زندگی کا سب سے بڑا سر درد ہے، یا آنکھوں میں بھی تکلیف ہے؟"
    },
    "sar dard": {
        "english":    "Is the headache on one side or all over? And is there nausea with it?",
        "roman_urdu": "Sar dard ek taraf hai ya poore sar mein? Aur kya ulti ka ji bhi kar raha hai?",
        "urdu":       "کیا سر درد ایک طرف ہے یا پورے سر میں؟ اور کیا متلی بھی ہے؟"
    },
    "stomach": {
        "english":    "Is the stomach pain in a specific area (like lower right), or is it general discomfort?",
        "roman_urdu": "Pet dard kisi ek jagah hai (jaise seedha neecha daayein) ya poore pet mein hai?",
        "urdu":       "کیا پیٹ کا درد کسی ایک جگہ ہے یا پورے پیٹ میں؟"
    },
    "pet dard": {
        "english":    "Is the pain worse after eating or before? And do you have loose stools or vomiting?",
        "roman_urdu": "Dard khane ke baad zyada hota hai ya pehle? Aur kya dast ya ulti bhi hai?",
        "urdu":       "کیا درد کھانے کے بعد زیادہ ہوتا ہے یا پہلے؟"
    },
    "fever": {
        "english":    "How many days have you had the fever, and what is the temperature reading?",
        "roman_urdu": "Bukhar kitne din se hai, aur temperature kitna hai?",
        "urdu":       "بخار کتنے دن سے ہے اور درجہ حرارت کتنا ہے؟"
    },
    "bukhar": {
        "english":    "Do you have any rash or red spots on your body along with the fever?",
        "roman_urdu": "Bukhar ke saath jism pe koi rash ya laal dhabbe bhi hain?",
        "urdu":       "کیا بخار کے ساتھ جسم پر کوئی دانے یا لال نشان ہیں؟"
    },
    "cough": {
        "english":    "Are you coughing up blood or thick colored mucus?",
        "roman_urdu": "Kya khansi mein khoon ya gara balgham aa raha hai?",
        "urdu":       "کیا کھانسی میں خون یا گاڑھا بلغم آ رہا ہے؟"
    },
    "khansi": {
        "english":    "How long have you had the cough, and is it dry or with phlegm?",
        "roman_urdu": "Khansi kitne arse se hai, aur kya sukhi hai ya balgham wali?",
        "urdu":       "کھانسی کتنے عرصے سے ہے اور خشک ہے یا بلغم والی؟"
    },
    "back pain": {
        "english":    "Is the back pain after an injury or did it start gradually? Any leg numbness?",
        "roman_urdu": "Peeth ka dard chot ke baad hua ya dheeray dheeray shuru hua? Aur kya paon mein bhi sunn pan hai?",
        "urdu":       "کمر کا درد چوٹ کے بعد ہوا یا آہستہ آہستہ شروع ہوا؟"
    },
    "joint": {
        "english":    "Is the joint pain in one joint or multiple? And is there swelling or redness?",
        "roman_urdu": "Joron ka dard ek jagah hai ya kai jagah? Aur sujan ya lali bhi hai?",
        "urdu":       "کیا جوڑوں کا درد ایک جگہ ہے یا کئی جگہ؟"
    },
    "urination": {
        "english":    "Is there pain or burning during urination? And what colour is the urine?",
        "roman_urdu": "Peshab karte waqt jalan ya dard hai? Aur peshab ka rang kaisa hai?",
        "urdu":       "پیشاب کرتے وقت جلن یا درد ہے؟"
    },
    "peshab": {
        "english":    "Any burning or blood in urine?",
        "roman_urdu": "Peshab mein jalan ya khoon toh nahi?",
        "urdu":       "کیا پیشاب میں جلن یا خون ہے؟"
    },
    "skin": {
        "english":    "Is the skin rash spreading, itching, or painful? When did it first appear?",
        "roman_urdu": "Jild ka rash phaile raha hai, kharish hai, ya dard hai? Kab shuru hua?",
        "urdu":       "کیا جلد کا رش پھیل رہا ہے؟ کب سے ہے؟"
    },
    "eye": {
        "english":    "Is there pain in the eye, blurred vision, or discharge?",
        "roman_urdu": "Aankh mein dard hai, dhundla dikhta hai, ya aankhon mein kuch aa raha hai?",
        "urdu":       "کیا آنکھ میں درد یا دھندلا پن ہے؟"
    },
    "child": {
        "english":    "What is the child's age, and is the child eating and drinking normally?",
        "roman_urdu": "Bachy ki umra kitni hai, aur kya woh khana peena kar raha/rahi hai?",
        "urdu":       "بچے کی عمر کتنی ہے اور کیا کھانا پینا ٹھیک ہے؟"
    },
    "bacha": {
        "english":    "How old is the child and since when have the symptoms started?",
        "roman_urdu": "Bachy ki umra kya hai aur yeh takleef kab se shuru hui?",
        "urdu":       "بچے کی عمر کیا ہے اور علامات کب سے ہیں؟"
    },
    "pregnancy": {
        "english":    "How many weeks pregnant are you, and what are your specific symptoms?",
        "roman_urdu": "Aap kitne hafton ki hamal hain, aur aapko exactly kya takleef hai?",
        "urdu":       "آپ کتنے ہفتوں کی حاملہ ہیں؟"
    },
    "mental": {
        "english":    "How long have you been feeling this way, and is it affecting your daily activities?",
        "roman_urdu": "Yeh kaifiyat kitne arse se hai, aur kya rozana ke kaam mein mushkil ho rahi hai?",
        "urdu":       "یہ کیفیت کتنے عرصے سے ہے؟"
    },
    "diabetes": {
        "english":    "When did you last check your blood sugar, and what was the reading?",
        "roman_urdu": "Aapne aakhri baar blood sugar kab check kiya aur kya result tha?",
        "urdu":       "آپ نے آخری بار بلڈ شوگر کب چیک کی اور نتیجہ کیا تھا؟"
    },
}

# Default follow-up questions when no specific match
DEFAULT_FOLLOW_UP = {
    "english":    "Could you describe when these symptoms started and how severe they are on a scale of 1-10?",
    "roman_urdu": "Yeh takleef kab shuru hui aur 1 se 10 mein kitni tez hai?",
    "urdu":       "یہ تکلیف کب شروع ہوئی اور 1 سے 10 میں کتنی تیز ہے؟"
}


def get_follow_up_question(symptoms: str, language: str = "english") -> str | None:
    """
    Returns a single language-aware follow-up question based on symptoms.
    Maximum one question at a time.
    FIX: Now language-aware — returns Urdu/Roman Urdu questions appropriately.
    """
    symptoms_lower = symptoms.lower()

    # Check each symptom keyword
    for keyword, questions in FOLLOW_UP_QUESTIONS.items():
        if keyword in symptoms_lower:
            return questions.get(language, questions.get("english"))

    # Default question
    return DEFAULT_FOLLOW_UP.get(language, DEFAULT_FOLLOW_UP["english"])


def is_emergency(text: str) -> bool:
    """
    Check if text contains emergency keywords.
    FIX: Now includes Pakistani/Urdu emergency keywords.
    """
    text_lower = text.lower()
    return any(keyword.lower() in text_lower for keyword in EMERGENCY_KEYWORDS)
