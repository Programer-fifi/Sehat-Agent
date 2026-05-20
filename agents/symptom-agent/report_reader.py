import os
import json
import io
from datetime import datetime
from google import genai
from google.genai import types
from PIL import Image

def get_client():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable not set")
    return genai.Client(api_key=api_key)

def log(message):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[SYMPTOM AGENT] {timestamp} {message}")

def convert_pdf_to_image(pdf_bytes):
    try:
        import pypdf2
        import pypdf2 as PyPDF2
        reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
        # Return note - full PDF rendering needs extra lib
        return None, "PDF text extracted — image rendering not available without pdf2image"
    except Exception as e:
        return None, str(e)

def process_medical_report(image_input, input_type="image_path"):
    """
    input_type: "image_path", "image_bytes", "pdf_bytes", "base64"
    """
    log("Report detected - starting analysis")
    client = get_client()

    try:
        if input_type == "image_path":
            img = Image.open(image_input).convert("RGB")
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG")
            image_bytes = buffer.getvalue()
            log(f"Report type: image file")

        elif input_type == "image_bytes":
            img = Image.open(io.BytesIO(image_input)).convert("RGB")
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG")
            image_bytes = buffer.getvalue()
            log(f"Report type: image bytes")

        elif input_type == "base64":
            import base64
            # Strip data URL prefix if present
            if "," in image_input:
                image_input = image_input.split(",")[1]
            decoded = base64.b64decode(image_input)
            
            # Check if PDF
            if decoded[:4] == b'%PDF':
                log("Report type: PDF as base64 — extracting text")
                try:
                    import pypdf
                    reader = pypdf.PdfReader(io.BytesIO(decoded))
                    text = ""
                    for page in reader.pages:
                        text += page.extract_text()
                    # Send as text prompt instead of image
                    client2 = get_client()
                    text_prompt = f"""Analyze this medical report text and return JSON:
{text}

Return ONLY strict JSON:
{{
    "report_type": "type",
    "all_values": [{{"name": "test", "value": "val", "unit": "u", "normal_range": "range", "status": "normal/high/low"}}],
    "critical_findings": ["finding"],
    "key_findings": ["finding"],
    "abnormal_values": [{{"test": "name", "value": "val", "normal_range": "range", "status": "high/low"}}],
    "summary_in_simple_urdu_english": "summary",
    "recommended_specialist": "doctor type",
    "urgency_indicated": "LOW or MEDIUM or HIGH or CRITICAL"
}}"""
                    response2 = client2.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=[text_prompt]
                    )
                    text_response = response2.text.strip()
                    if text_response.startswith("```json"):
                        text_response = text_response[7:-3].strip()
                    elif text_response.startswith("```"):
                        text_response = text_response[3:-3].strip()
                    return json.loads(text_response)
                except Exception as e:
                    log(f"PDF text extraction failed: {e}")
                    return {"error": f"PDF process nahi ho saka: {str(e)}"}
            
            # Regular image
            img = Image.open(io.BytesIO(decoded)).convert("RGB")
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG")
            image_bytes = buffer.getvalue()
            log(f"Report type: base64 image")

        elif input_type == "pdf_bytes":
            log("Report type: PDF - converting first 2 pages")
            return {
                "report_type": "PDF",
                "error": None,
                "summary": "PDF received. Please upload as image for best results.",
                "urgency_indicated": "LOW"
            }
        else:
            return {"error": "Unknown input type"}

    except Exception as e:
        log(f"Failed to open report: {str(e)}")
        return {
            "error": f"Report thoda blur hai ya open nahi ho raha — kya aap dobara clear photo le sakte hain? Error: {str(e)}"
        }

    prompt = """
You are a medical report analyzer for Pakistani patients.
Analyze this medical report image carefully.

Extract information in strict JSON format (no markdown, no extra text):
{
    "report_type": "CBC or Blood Sugar or Urine or ECG or X-Ray or Ultrasound or Prescription or Other",
    "date": "YYYY-MM-DD if visible else null",
    "patient_name": "name if visible else null",
    "all_values": [
        {
            "name": "test name",
            "value": "result value",
            "unit": "unit",
            "normal_range": "range",
            "status": "normal or high or low"
        }
    ],
    "critical_findings": ["any dangerous values"],
    "key_findings": ["Finding 1", "Finding 2"],
    "abnormal_values": [
        {
            "test": "Test Name",
            "value": "Value",
            "normal_range": "Range",
            "status": "high or low"
        }
    ],
    "summary_in_simple_urdu_english": "2 sentence simple summary",
    "recommended_specialist": "which doctor type",
    "urgency_indicated": "LOW or MEDIUM or HIGH or CRITICAL"
}

If image is blurry, unclear, or not a medical document return ONLY:
{
    "error": "Report thoda blur hai - kya aap dobara clear photo le sakte hain? Meanwhile symptoms batayein."
}
"""

    try:
        log("Sending report to Gemini Vision...")
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                prompt
            ]
        )

        text_response = response.text.strip()
        if text_response.startswith("```json"):
            text_response = text_response[7:-3].strip()
        elif text_response.startswith("```"):
            text_response = text_response[3:-3].strip()

        result = json.loads(text_response)
        log(f"Report analyzed: {result.get('report_type', 'Unknown')}")
        log(f"Critical findings: {result.get('critical_findings', [])}")
        return result

    except Exception as e:
        log(f"Report reading failed: {str(e)}")
        return {
            "error": f"Report process nahi ho saka: {str(e)}",
            "fallback": "Please describe your symptoms in text."
        }
