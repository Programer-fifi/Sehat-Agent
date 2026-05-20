---
title: Sehat Agent
emoji: 🏥
colorFrom: green
colorTo: blue
sdk: docker
pinned: false
---

# 🏥 Sehat Agent
### Pakistan's First AI-Powered Medical Navigation System
**Google Antigravity Hackathon — Challenge 1: Autonomous Content-to-Action Agent**

---

## 🎯 Problem Statement

Every day in Pakistan, millions of people face the same nightmare:
- A family member falls sick
- They don't know which hospital to go to
- They don't know which department they need
- They don't understand their medical reports
- They don't know how much money to bring
- They waste hours going to the wrong place

**Sehat Agent solves all of this in one conversation — automatically.**

---

## 💡 What We Built

Sehat Agent is a **multi-agent AI system** that takes unstructured medical input (symptoms in Urdu/English + medical report images/PDFs) and autonomously:

1. **Understands** what the patient is experiencing
2. **Reads and analyzes** their uploaded medical reports
3. **Finds** the nearest appropriate hospital using real location data
4. **Recommends** the correct department with clear reasoning
5. **Estimates** treatment costs and gives payment advice
6. **Simulates** appointment booking end-to-end
7. **Generates** a downloadable Patient Pass/Receipt
8. **Shows** complete agent trace logs of every decision

---

## 🤖 Agent Architecture

```
USER INPUT
(Symptoms in Urdu/Roman Urdu/English + Optional Report Upload)
                    ↓
         ┌─────────────────────┐
         │  MAIN ORCHESTRATOR  │
         │       AGENT         │
         │  Intent Detection   │
         │  Agent Routing      │
         │  Result Combining   │
         └─────────────────────┘
              ↓    ↓    ↓    ↓
    ┌─────────┐ ┌──────┐ ┌────────┐ ┌───────────┐
    │SYMPTOM  │ │HOSP. │ │  COST  │ │APPOINTMENT│
    │+REPORT  │ │FINDER│ │ AGENT  │ │   AGENT   │
    │  AGENT  │ │AGENT │ │        │ │           │
    └─────────┘ └──────┘ └────────┘ └───────────┘
         ↓           ↓        ↓           ↓
              ┌─────────────────────┐
              │  VALIDATOR AGENT    │
              │ (Quality Checker)   │
              └─────────────────────┘
                        ↓
              FINAL RESPONSE TO USER
```

---

## 🧠 Agent Descriptions

### 1. Main Orchestrator Agent
**Role:** The brain — routes everything, combines results

**Responsibilities:**
- Detect user intent from natural language input
- Decide which agents to activate
- Prevent unnecessary agent activation
- Combine all agent outputs into one clean response
- Handle emergency detection (immediate full activation)

**Intent Categories:**
| Intent | Agents Activated |
|--------|-----------------|
| SYMPTOM_ONLY | Symptom Agent only |
| HOSPITAL_NEEDED | Hospital Finder only |
| APPOINTMENT_NEEDED | Hospital Finder + Appointment Agent |
| REPORT_ANALYSIS | Symptom+Report Agent only |
| COST_INQUIRY | Cost Agent only |
| FULL_SERVICE | All agents |
| EMERGENCY | All agents simultaneously |

---

### 2. Symptom + Report Agent
**Role:** The doctor — analyzes and diagnoses

**Responsibilities:**
- Process symptom descriptions in Urdu, Roman Urdu, and English
- Ask intelligent follow-up questions based on symptoms
- Read uploaded medical reports (blood tests, X-rays, prescriptions)
- Extract abnormal values from reports
- Combine report findings with symptoms for complete picture
- Determine urgency level (LOW / MEDIUM / HIGH / CRITICAL)
- Recommend appropriate medical department

**Report Types Handled:**
- CBC (Complete Blood Count)
- Blood Sugar / HbA1c
- Urine Analysis
- ECG reports
- X-Ray descriptions
- Ultrasound reports
- Prescription slips
- General lab reports

**Urgency Levels:**
```
LOW      → Regular OPD appointment fine
MEDIUM   → Visit within 24-48 hours
HIGH     → Visit today
CRITICAL → Emergency — go immediately
```

**Output Example:**
```json
{
  "symptoms_summary": "Chest pain, breathlessness, 3 days",
  "report_findings": "Troponin elevated, WBC high",
  "urgency_level": "CRITICAL",
  "recommended_department": "Emergency Cardiology",
  "reasoning": "Elevated troponin + chest pain = possible cardiac event",
  "do_not_delay": true,
  "disclaimer": "This is AI guidance only. Consult a doctor immediately."
}
```

---

### 3. Hospital Finder Agent
**Role:** The receptionist — locates the right facility

**Responsibilities:**
- Use Google Maps/Places API to find real hospitals
- Filter by required department
- Rank hospitals by distance, rating, and department availability
- Prioritize emergency facilities for CRITICAL cases
- Return top 3 hospitals with full details

**Ranking Criteria:**
1. Has required department ✅ (mandatory filter)
2. Distance from user (nearest first)
3. Google Maps rating (4.0+ preferred)
4. Emergency availability (if urgency is HIGH/CRITICAL)
5. Type: Government/Private (for cost consideration)

**Cities Covered:**
- Karachi: Aga Khan, Liaquat National, South City, Ziauddin, Patel Hospital
- Lahore: Shaukat Khanum, Services Hospital, Hameed Latif, Jinnah Hospital
- Islamabad: PIMS, Shifa International, Quaid-e-Azam Hospital
- Rawalpindi: Holy Family, Benazir Bhutto Hospital
- Peshawar: Lady Reading, Khyber Teaching Hospital

**Output Example:**
```json
{
  "top_recommendation": {
    "name": "Aga Khan Hospital",
    "distance": "2.3 km",
    "department": "Cardiology",
    "emergency": true,
    "phone": "021-111-911-911",
    "maps_link": "https://maps.google.com/...",
    "rating": 4.5,
    "type": "Private"
  },
  "alternatives": [...],
  "reasoning": "Nearest hospital with Cardiology + 24/7 Emergency"
}
```

---

### 4. Cost Agent
**Role:** The billing counter — estimates expenses

**Responsibilities:**
- Estimate consultation fees based on hospital type and department
- Calculate probable test costs
- Estimate medicine budget
- Recommend cash vs card based on amount
- Check insurance applicability
- Generate "What to Bring" checklist

**Cost Database:**
| Visit Type | Government | Private |
|-----------|------------|---------|
| General OPD | PKR 50-200 | PKR 1,000-2,000 |
| Specialist OPD | PKR 200-500 | PKR 2,000-4,000 |
| Super Specialist | PKR 500-1,000 | PKR 3,500-6,000 |
| Emergency | PKR 500-2,000 | PKR 5,000-15,000 |

**Payment Rules:**
- Under PKR 5,000 → Cash is fine
- PKR 5,000-15,000 → Bring both
- Over PKR 15,000 → Card essential
- Emergency → Always bring both

**Output Example:**
```json
{
  "estimated_cost": {"minimum": 3500, "maximum": 8000, "currency": "PKR"},
  "payment_advice": "Card recommended",
  "bring_checklist": ["CNIC", "Cash PKR 5,000 min", "Debit Card", "Previous ECG if any"],
  "insurance_applicable": false,
  "government_option": "Jinnah Hospital — PKR 300-500"
}
```

---

### 5. Appointment Agent
**Role:** The booker — simulates end-to-end booking

**This agent makes Sehat Agent truly AGENTIC — not just a chatbot**

**Responsibilities:**
- Simulate connection to hospital booking system
- Check slot availability (mock database)
- Select optimal slot based on urgency
- Execute mock booking API call
- Generate appointment token number
- Create downloadable Patient Pass (PDF)
- Simulate SMS/WhatsApp confirmation
- Set follow-up reminder
- Show BEFORE vs AFTER system state change

**System State Change Demo:**
```
BEFORE BOOKING:           AFTER BOOKING:
3:00 PM — AVAILABLE  →   3:00 PM — BOOKED ✅
Appointments: 0      →   Appointments: 1
```

**Patient Pass Generated:**
```
╔══════════════════════════════════╗
║        SEHAT AGENT               ║
║    APPOINTMENT CONFIRMATION      ║
╠══════════════════════════════════╣
║ Token No:    #AK-2847            ║
║ Date:        14 May 2026         ║
║ Time:        3:00 PM             ║
║                                  ║
║ Hospital:    Aga Khan Hospital   ║
║ Address:     Stadium Road,       ║
║              Karachi             ║
║ Department:  Cardiology          ║
║ Doctor:      Dr. Asim Khan       ║
║                                  ║
║ Urgency:     HIGH                ║
║ Est. Cost:   PKR 3,500 - 5,000   ║
║ Payment:     Card Recommended    ║
║                                  ║
║ Bring:       CNIC, Card,         ║
║              Previous Reports    ║
╠══════════════════════════════════╣
║ ⚕️ AI guidance only.            ║
║ Not a real medical appointment   ║
╚══════════════════════════════════╝
```

---

### 6. Validator Agent
**Role:** The quality checker — ensures accuracy

**Responsibilities:**
- Double-check Hospital Finder's recommendations
- Verify department exists at suggested hospital
- Check if distance is reasonable for user's situation
- Verify cost estimates are realistic
- If errors found: send back to relevant agent for retry
- Proves multi-step reasoning and traceable decision-making

**Validation Checks:**
```
✓ Hospital has required department?
✓ Hospital is within reasonable distance?
✓ Emergency available if urgency is HIGH/CRITICAL?
✓ Cost estimate matches hospital type?
✓ All required fields populated?
```

---

## 🔄 Complete Flow Example

**User Input:** "Mujhe 3 din se tez bukhar hai, Karachi mein hoon" + Blood Test Image Upload

```
[10:23:01] MAIN AGENT: Input received
[10:23:01] MAIN AGENT: Intent = FULL_SERVICE
[10:23:01] MAIN AGENT: Report detected — activating all agents

[10:23:02] SYMPTOM+REPORT AGENT: Reading blood test image...
[10:23:03] SYMPTOM+REPORT AGENT: WBC = 14,500 (HIGH — infection)
[10:23:03] SYMPTOM+REPORT AGENT: Platelets = 85,000 (LOW — dengue risk!)
[10:23:03] SYMPTOM+REPORT AGENT: Asked: "Koi rash hai?"
[10:23:04] SYMPTOM+REPORT AGENT: Dengue flagged — URGENCY: HIGH
[10:23:04] SYMPTOM+REPORT AGENT: Department: General Medicine / Infectious Disease

[10:23:04] HOSPITAL FINDER AGENT: Location = Karachi
[10:23:04] HOSPITAL FINDER AGENT: Dept needed = General Medicine
[10:23:05] HOSPITAL FINDER AGENT: Google Maps queried
[10:23:05] HOSPITAL FINDER AGENT: 3 hospitals found and ranked
[10:23:05] HOSPITAL FINDER AGENT: Top = Liaquat National (1.8km)

[10:23:05] COST AGENT: Hospital type = Government
[10:23:06] COST AGENT: OPD + Tests estimated = PKR 2,000-4,000
[10:23:06] COST AGENT: Card recommended

[10:23:06] VALIDATOR AGENT: Checking recommendations...
[10:23:06] VALIDATOR AGENT: ✅ Department confirmed at Liaquat National
[10:23:07] VALIDATOR AGENT: ✅ Distance acceptable (1.8km)
[10:23:07] VALIDATOR AGENT: ✅ All checks passed

[10:23:07] APPOINTMENT AGENT: Connecting to booking system...
[10:23:07] APPOINTMENT AGENT: Slot found = Today 4:00 PM
[10:23:08] APPOINTMENT AGENT: Booking confirmed — Token #LN-4521
[10:23:08] APPOINTMENT AGENT: Patient Pass generated
[10:23:08] APPOINTMENT AGENT: SMS simulated
[10:23:08] APPOINTMENT AGENT: Reminder set

[10:23:09] MAIN AGENT: All 5 agents complete
[10:23:09] MAIN AGENT: Results combined
[10:23:09] MAIN AGENT: Response delivered

Total Time: 8 seconds | Agents Used: 5/5 | Actions Taken: 7
```

---

## 🛠️ Tech Stack

### AI & Agents
- **Google Antigravity** — Core orchestration platform (primary)
- **Gemini 2.5 Flash** — Language model for all agents
- **Gemini Vision API** — Medical report image/PDF reading
- **Gemini Multimodal** — Voice input processing

### Backend
- **Python Flask** — Backend server
- **Python-dotenv** — Secure API key management
- **Gunicorn** — Production server

### Frontend
- **HTML5, CSS3, JavaScript** — Web interface
- **Capacitor** — Web to Android APK conversion
- **Web Speech API** — Voice input in Roman Urdu

### APIs & Data
- **Google Maps/Places API** — Real hospital location data
- **Mock Hospital Database (JSON)** — Department & slot data
- **HTML2PDF.js** — Patient Pass PDF generation

### Security
- API keys stored in environment variables only
- Patient data never stored permanently
- Session cleared after each conversation
- All transmissions encrypted

---

## 📱 Mobile App

Built using **Capacitor** to wrap the responsive web app into a native Android APK.

The app is fully responsive and works on:
- Android mobile browsers
- Android native app (via Capacitor)
- Desktop browsers

---

## 🎬 Demo Video Outline (3-5 minutes)

**Minute 0:00-0:30 — Hook**
"Mere abbu ke saath yeh hua..." (real problem story)

**Minute 0:30-1:30 — Demo Part 1**
- User uploads blood test report
- Symptom + Report Agent analyzes
- Agent asks smart follow-up question
- Urgency detected

**Minute 1:30-2:30 — Demo Part 2**
- Hospital Finder shows real Google Maps results
- Validator Agent checks recommendations
- Cost Agent gives payment advice
- Clear reasoning displayed

**Minute 2:30-3:30 — Demo Part 3 (The WOW moment)**
- Before state: Empty schedule shown
- Appointment Agent executes
- After state: Slot booked, state changed
- Patient Pass downloaded
- WhatsApp simulation shown

**Minute 3:30-4:00 — Agent Trace**
Show complete execution log to judges

**Minute 4:00-4:30 — Pitch Close**
"Yeh sirf ek app nahi — yeh 220 million Pakistaniyoun ka medical companion hai"

---

## 📊 How We Score Against Evaluation Criteria

| Criteria | Weight | Our Coverage |
|----------|--------|-------------|
| Google Antigravity Integration | 25% | Core orchestration, all agent routing, tool execution via Antigravity |
| Agentic Reasoning & Workflow | 20% | 5 agents, validator loop, traceable decision log |
| Insight & Decision Quality | 20% | Report analysis, symptom reasoning, department selection logic |
| Action Simulation & Outcome | 15% | Before/after state, receipt generation, SMS simulation |
| Technical Implementation | 10% | Flask backend, Maps API, PDF generation, voice input |
| Innovation & UX | 10% | Voice in Roman Urdu, multimodal input, downloadable Pass |

---

## ⚠️ Important Disclaimers

- Sehat Agent provides **guidance only** — not medical diagnosis
- Always consult a qualified doctor for medical decisions
- Appointment simulation is **not a real booking**
- Hospital data is based on publicly available information
- No real patient data is stored or transmitted

---

## 👥 Team

| Member | Role | Agent |
|--------|------|-------|
| Member 1 | Cost Analysis + Project Lead | Cost Agent |
| Member 2 | Medical Logic + Symptom Analysis | Symptom + Report Agent |
| Member 3 | Location Services + Hospital Data | Hospital Finder Agent |
| All Together | Integration + Orchestration | Main Agent + Validator + Appointment Agent |

---

## 🏗️ Architecture Diagram

```
┌─────────────────────────────────────────────┐
│                  USER                        │
│     (Text / Voice / Report Upload)          │
└─────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────┐
│         GOOGLE ANTIGRAVITY                  │
│         Main Orchestrator Agent             │
│    Intent Detection → Agent Routing         │
└─────────────────────────────────────────────┘
         ↓          ↓         ↓          ↓
┌─────────┐  ┌──────────┐  ┌──────┐  ┌──────┐
│Symptom  │  │ Hospital │  │ Cost │  │ Appt │
│+Report  │  │  Finder  │  │Agent │  │Agent │
│ Agent   │  │  Agent   │  │      │  │      │
│(Gemini  │  │(Google   │  │(Mock │  │(Mock │
│Vision)  │  │Maps API) │  │ DB)  │  │ API) │
└─────────┘  └──────────┘  └──────┘  └──────┘
         ↓          ↓         ↓          ↓
┌─────────────────────────────────────────────┐
│           VALIDATOR AGENT                   │
│      Quality Check → Re-route if needed     │
└─────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────┐
│              FINAL OUTPUT                   │
│  Report Analysis + Hospital + Cost +        │
│  Appointment Receipt + Agent Trace Log      │
└─────────────────────────────────────────────┘
```

---

## 🚀 How to Run

### Local Development
```bash
# Install dependencies
pip install flask flask-cors requests python-dotenv gunicorn

# Set environment variables
# Create .env file with:
# GEMINI_KEY_1=your_key_here
# GEMINI_KEY_2=your_key_here
# GOOGLE_MAPS_KEY=your_key_here

# Run server
python app.py

# Open browser
# http://localhost:8000
```

### Mobile App (Android)
```bash
# Install Capacitor
npm install @capacitor/core @capacitor/cli

# Build Android APK
npx cap init
npx cap add android
npx cap build android
```

---

## 🔮 Future Roadmap

- Real hospital API integration (when available)
- Telemedicine appointment booking
- Medicine availability checker at nearby pharmacies
- Health insurance claim assistant
- Multi-city expansion beyond 5 cities
- Specialist doctor profiles and ratings
- Follow-up care reminders

---

*Built with ❤️ for Pakistan — Google Antigravity Hackathon 2026*
*"Sehat Agent — Jab bhi zaroorat ho, hum hain saath!"*
