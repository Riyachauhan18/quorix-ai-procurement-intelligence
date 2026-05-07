"""
AI Tender Copilot - Full Stack Backend
Run: py server.py  |  Visit: http://localhost:5000
"""

import os, json, random, datetime, re, time
from io import BytesIO
from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

# Initialize Supabase (Fail gracefully if not configured)
try:
    from supabase import create_client, Client
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if url and key:
        supabase: Client = create_client(url, key)
    else:
        supabase = None
except ImportError:
    supabase = None

# Document parsing dependencies
try:
    import PyPDF2
except ImportError:
    PyPDF2 = None
try:
    import docx
except ImportError:
    docx = None

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

audit_trail = []   # in-memory fallback

# ─── Heuristic Text Extraction & Parsing ──────────────────────────────────────────

# Dependency Check
print(f"--- BACKEND SYSTEM CHECK ---")
print(f"PyPDF2: {'LOADED' if PyPDF2 else 'MISSING'}")
print(f"docx:   {'LOADED' if docx else 'MISSING'}")
print(f"Supabase: {'CONFIGURED' if supabase else 'OFFLINE'}")
print(f"----------------------------\n")

# --- ADVANCED PDF EXTRACTION SUITE ---
try:
    import fitz # PyMuPDF
except ImportError:
    fitz = None

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

def clean_extracted_text(text):
    if not text: return ""
    # Normalize symbols
    text = text.replace('â‚¹', 'Rs.').replace('₹', 'Rs.')
    # Merge broken lines (heuristic: join lines ending in lowercase or hyphen)
    text = re.sub(r'([a-z-])\n\s*([a-z])', r'\1 \2', text)
    # Remove duplicate whitespace
    text = re.sub(r' +', ' ', text)
    return text

def extract_text(file_stream, filename):
    text = ""
    parser_used = "None"
    start_time = time.time()
    
    try:
        if filename.lower().endswith('.pdf'):
            # Fallback 1: PyMuPDF (Fastest & best formatting)
            if fitz:
                try:
                    doc = fitz.open(stream=file_stream, filetype="pdf")
                    for page in doc:
                        text += page.get_text("text") + "\n"
                    if len(text.strip()) > 50:
                        parser_used = "PyMuPDF"
                except Exception as e:
                    print(f"!! PyMuPDF failed: {e}")
                    file_stream.seek(0)
            
            # Fallback 2: pdfplumber (Excellent for tables/financials)
            if (not text.strip()) and pdfplumber:
                try:
                    with pdfplumber.open(file_stream) as pdf:
                        for page in pdf.pages:
                            text += page.extract_text() + "\n"
                    if len(text.strip()) > 50:
                        parser_used = "pdfplumber"
                except Exception as e:
                    print(f"!! pdfplumber failed: {e}")
                    file_stream.seek(0)
            
            # Fallback 3: PyPDF2 (Legacy fallback)
            if not text.strip() and PyPDF2:
                try:
                    reader = PyPDF2.PdfReader(file_stream)
                    for page in reader.pages:
                        text += page.extract_text() + "\n"
                    if len(text.strip()) > 50:
                        parser_used = "PyPDF2"
                except Exception as e:
                    print(f"!! PyPDF2 failed: {e}")

        elif filename.lower().endswith('.docx') and docx:
            doc = docx.Document(file_stream)
            for para in doc.paragraphs:
                text += para.text + "\n"
            parser_used = "python-docx"
        else: # txt
            text = file_stream.read().decode('utf-8', errors='ignore')
            parser_used = "UTF-8 Decoder"
            
    except Exception as e:
        print(f"!! EXTRACTION FATAL ERROR for {filename}: {e}")
        
    cleaned_text = clean_extracted_text(text)
    
    # DEBUG LOGGING (Targeted Patch Requirement)
    print(f"\n--- PDF EXTRACTION DIAGNOSTICS ---")
    print(f"Filename:     {filename}")
    print(f"Parser Used:  {parser_used}")
    print(f"Raw Length:   {len(text)} chars")
    print(f"Clean Length: {len(cleaned_text)} chars")
    if len(cleaned_text) > 0:
        print(f"Text Preview (First 500 chars):\n{cleaned_text[:500]}...")
    else:
        print("!! WARNING: NO TEXT EXTRACTED (Possibly Scanned PDF)")
    print(f"-----------------------------------\n")
    
    return cleaned_text

def parse_number(text, context=""):
    if not text: return None
    clean = re.sub(r'[^\d\.]', '', text)
    try:
        val = float(clean)
        if re.search(r'(?:cr|crore)', text, re.IGNORECASE): val *= 10_000_000
        elif re.search(r'(?:l|lakh)', text, re.IGNORECASE): val *= 100_000
        elif re.search(r'm', text, re.IGNORECASE): val *= 1_000_000
        elif re.search(r'k', text, re.IGNORECASE): val *= 1_000
        
        # STABILITY: Ignore numbers < 1000 for Turnover/Price unless suffixed
        if context != "experience" and val < 1000:
            if not any(s in text.lower() for s in ["cr", "crore", "l", "lakh"]):
                return None
        return val
    except:
        return None

def calculate_procurement_relevance(text):
    positive_keywords = [
        "tender", "bidder", "procurement", "quotation", "proposal", "company name",
        "vendor", "supplier", "annual turnover", "bid amount", "experience",
        "contract", "technical bid", "financial bid", "compliance", "eligibility",
        "rfp", "rfq", "pvt ltd", "limited", "pvt. ltd.", "gst", "business", "proprietor",
        "pan card", "income tax", "balance sheet", "audit", "earnest money", "emd"
    ]
    negative_keywords = [
        "assignment", "question bank", "chapter", "experiment", "university",
        "student", "algorithm", "worksheet", "exam", "tutorial", "practice sheet",
        "homework", "lecture", "professor", "class notes", "syllabus"
    ]
    
    score = 0
    matches = []
    lower_text = text.lower()
    
    for kw in positive_keywords:
        if kw in lower_text:
            score += 2
            matches.append(f"+{kw}")
            
    for kw in negative_keywords:
        if kw in lower_text:
            score -= 3 # Stronger negative weight to clear academic noise
            matches.append(f"-{kw}")
            
    return score, matches

def heuristic_parse(text):
    # Phase 4: Empty/Scanned Text Detection
    if not text or len(text.strip()) < 100:
        return {
            "status": "unsupported_document",
            "confidence": "LOW",
            "message": "This PDF appears scanned or contains limited machine-readable text."
        }

    # Phase 1: Document Relevance Detection
    rel_score, rel_matches = calculate_procurement_relevance(text)
    
    print(f"\n--- ENTERPRISE EXTRACTION DEBUG ---")
    print(f"Procurement Relevance Score: {rel_score}")
    print(f"Indicators Detected: {', '.join(rel_matches)}")
    
    # CASE 3: NON-PROCUREMENT DOCUMENT
    # "Softened" check: If we have at least 2 positive indicators, we attempt extraction
    if rel_score < 2: 
        print("RESULT: REJECTED (Non-Procurement Document)")
        return {
            "status": "unsupported_document",
            "confidence": "LOW",
            "message": "This document does not appear to contain procurement or bidder-related information."
        }

    data = {
        "status": "success",
        "company": None,
        "turnover": None,
        "experience": None,
        "blacklisted": False,
        "price": None,
        "confidence": "Low"
    }
    
    clean_text = re.sub(r'\s+', ' ', text)
    
    # 1. SMART FINANCIAL EXTRACTION (Contextual)
    # Annual Turnover
    t_pattern = re.compile(r'(?:annual turnover|yearly turnover|company turnover|revenue|turnover).{0,50}?([\d,\.]+\s*(?:cr|crore|l|lakh|m|k)?)', re.IGNORECASE | re.DOTALL)
    t_match = t_pattern.search(clean_text)
    if t_match:
        data["turnover"] = parse_number(t_match.group(1))

    # 2. EXPERIENCE EXTRACTION (Skeptical)
    e_pattern = re.compile(r'(?:years of experience|experience|work experience|established|operation).{0,30}?(\d+)\s*(?:years?|yrs?)', re.IGNORECASE | re.DOTALL)
    e_match = e_pattern.search(clean_text)
    if e_match:
        try: data["experience"] = int(e_match.group(1))
        except: pass
        
    # 3. BLACKLIST STATUS
    if re.search(r'(?:not|no|never|zero)[\s\w]*(?:blacklisted|blacklist|debarred|barred)', clean_text, re.IGNORECASE):
        data["blacklisted"] = False
    elif re.search(r'(?:is|currently|yes)[\s\w]*(?:blacklisted|blacklist|debarred|barred)', clean_text, re.IGNORECASE):
        data["blacklisted"] = True
        
    # 4. PRICE EXTRACTION (Contextual)
    p_pattern = re.compile(r'(?:quotation|quoted price|bid amount|project value|contract value|financial bid|total quote).{0,50}?([\d,\.]+\s*(?:cr|crore|l|lakh|m|k)?)', re.IGNORECASE | re.DOTALL)
    p_match = p_pattern.search(clean_text)
    if p_match:
        data["price"] = parse_number(p_match.group(1))

    # 5. SAFE COMPANY EXTRACTION (Tiered)
    # Tier 1: Explicit labels + Business suffixes
    c_pattern = re.compile(r'(?:company name|bidder name|vendor|organization|supplier|name of the firm)[\s\w:]*?([A-Z][a-zA-Z0-9\s\.]{3,50}?(?:Ltd|Corp|Inc|LLC|Pvt|Solutions|Industries|Engineering|Services|Associates|Limited|Enterprises|Infra|Technologies))', re.IGNORECASE)
    c_match = c_pattern.search(clean_text)
    
    if not c_match:
        # Tier 2: Global Search for Business Entities (Pvt, Ltd, etc.)
        c_match = re.search(r'([A-Z][a-zA-Z0-9\s\.]{3,50}?(?:Pvt Ltd|Limited|Ltd|LLP|Corporation|Enterprises|Infra|Technologies|Solutions|Industries|Engineering))', clean_text)
    
    if c_match:
        cand = c_match.group(1).strip()
        cand = re.sub(r'[\(\)\[\]:;]', '', cand).strip()
        # --- DEMO SHIELD: EXTENSIVE NOISE FILTER ---
        noise = [
            "Office Address", "Request for Selection", "Model Tender", "Practice Sheet", 
            "Neural Network", "Page", "Document", "Project", "Local Bodies", "Assignment", 
            "Chapter", "Course", "Arbitrator", "Department of", "Ministry of", "Government of",
            "Public Enterprises", "Authority", "India", "Signed by", "Date", "Place", "Section",
            "Annexure", "Schedule", "Table", "Contents", "Introduction", "General Conditions",
            "Special Conditions", "Standard Operating", "Manual", "Guidelines", "Policy"
        ]
        
        # Check if the candidate contains any noise or is a common government phrase
        is_noise = any(n.lower() in cand.lower() for n in noise)
        
        # Extra check: If it starts with "Department" or "Ministry", it's an authority, not a bidder
        if not is_noise and not cand.lower().startswith(('dept', 'ministry', 'govt', 'government', 'office', 'arbitrator')):
            # Ensure it's not too long (most company names are under 10 words)
            if len(cand.split()) <= 8:
                data["company"] = cand

    # PHASE 5: CONFIDENCE ENGINE
    found_count = sum(1 for v in [data["company"], data["turnover"], data["experience"], data["price"]] if v is not None and v != "Unknown Bidder")
    
    if rel_score >= 8 and found_count >= 3:
        data["confidence"] = "High"
    elif rel_score >= 4 and found_count >= 1:
        data["confidence"] = "Medium"
    else:
        data["confidence"] = "Low"
    
    # PHASE 6: PROFESSIONAL FALLBACKS
    data["company"] = data["company"] or "Unknown Bidder"
    
    print(f"FINAL RESULT: {data['company']} | Confidence: {data['confidence']}")
    print(f"--- EXTRACTION END ---\n")
    
    return data

# ─── Scoring ────────────────────────────────────────────────────────────────────

def score_ratio(value, minimum):
    if minimum <= 0:
        return 100
    ratio = value / minimum
    if ratio >= 2:   return 100
    if ratio >= 1:   return round(70 + (ratio - 1) * 30)
    return round(ratio * 60)   # max 60 if below threshold

def calculate_scores(turnover, experience, blacklisted, min_t, min_e):
    t = score_ratio(turnover, min_t)
    e = score_ratio(experience, min_e)
    c = 0 if blacklisted else 100
    total = round(t * 0.4 + e * 0.4 + c * 0.2)
    return {"turnover": t, "experience": e, "compliance": c, "total": total}

# ─── Risk ────────────────────────────────────────────────────────────────────────

def risk_level(value, minimum):
    if minimum <= 0: return "Low"
    r = value / minimum
    if r >= 1.5: return "Low"
    if r >= 1.0: return "Medium"
    return "High"

def get_risks(turnover, experience, blacklisted, min_t, min_e):
    return {
        "financial":   risk_level(turnover, min_t),
        "capability":  risk_level(experience, min_e),
        "compliance":  "High" if blacklisted else "Low",
    }

# ─── Fairness ────────────────────────────────────────────────────────────────────

def get_fairness(min_t, min_e):
    score = 0
    if min_t > 5_000_000: score += 2
    elif min_t > 2_000_000: score += 1
    if min_e > 5: score += 2
    elif min_e > 3: score += 1

    if score >= 3:
        return {"level": "Low",
                "insight": "High thresholds significantly restrict vendor participation. Smaller firms may be excluded. Consider relaxing criteria to encourage wider competition and better value for money."}
    if score >= 1:
        return {"level": "Medium",
                "insight": "Moderate thresholds create reasonable barriers. Some smaller vendors may struggle. Monitor bid participation rates and adjust thresholds if competition is limited."}
    return {"level": "High",
            "insight": "Inclusive thresholds encourage broad participation. Strong vendor interest expected. Good balance between quality standards and competitive procurement."}

# ─── Extra intelligence helpers ────────────────────────────────────────────────────

def get_overall_risk(risks):
    lvls = list(risks.values())
    if 'High' in lvls: return 'High'
    if 'Medium' in lvls: return 'Medium'
    return 'Low'

def get_policy_recommendation(min_t, min_e):
    recs = []
    if min_t > 5_000_000:
        recs.append("Reduce turnover threshold to expand MSME participation and improve competition.")
    elif min_t < 500_000:
        recs.append("Raise minimum turnover to ensure adequate vendor financial capacity.")
    else:
        recs.append("Maintain current turnover threshold — well balanced for quality and competition.")
    if min_e > 7:
        recs.append("Reduce experience requirement to include capable, newer firms.")
    elif min_e < 2:
        recs.append("Increase minimum experience to reduce project delivery risk.")
    else:
        recs.append("Experience threshold is appropriately calibrated for procurement.")
    return " ".join(recs)

def get_trade_off_analysis(min_t, min_e):
    ins = []
    if min_t > 5_000_000:
        ins.append({"type":"warning",  "text":"Increasing turnover threshold improves quality but reduces competition — risk of limited bids."})
    elif min_t > 2_000_000:
        ins.append({"type":"balanced", "text":"Moderate turnover threshold achieves a good quality-competition balance."})
    else:
        ins.append({"type":"info",     "text":"Low turnover threshold maximises participation but may include financially weaker vendors."})
    if min_e > 5:
        ins.append({"type":"warning",  "text":"High experience requirement reduces delivery risk but may exclude capable newer firms."})
    elif min_e >= 3:
        ins.append({"type":"balanced", "text":"Balanced experience threshold — optimal for government and enterprise procurement."})
    else:
        ins.append({"type":"info",     "text":"Lowering experience requirement increases participation but raises project execution risk."})
    ts = 0 if min_t > 5_000_000 else (1 if min_t > 2_000_000 else 2)
    es = 0 if min_e > 5 else (1 if min_e >= 3 else 2)
    if ts + es >= 3:
        ins.append({"type":"success", "text":"Balanced policy achieved — optimal fairness vs risk. Healthy vendor competition expected."})
    elif ts + es >= 2:
        ins.append({"type":"balanced","text":"Policy is moderately balanced. Minor adjustments may improve competition."})
    else:
        ins.append({"type":"warning", "text":"Overly strict criteria detected. High risk of limited competition."})
    return ins

# ─── Alerts ─────────────────────────────────────────────────────────────────────

def get_alerts(min_t, min_e, blacklisted, all_pass, scores):
    alerts = []
    if not all_pass:
        alerts.append({"type": "danger", "text": "Bidder fails mandatory eligibility criteria"})
        alerts.append({"type": "warning", "text": "High risk profile detected"})
        alerts.append({"type": "info", "text": "Not recommended for award selection"})
    else:
        if min_t > 5_000_000:
            alerts.append({"type": "warning", "text": "High turnover requirement may significantly reduce vendor participation."})
        if min_e > 7:
            alerts.append({"type": "warning", "text": "High experience threshold limits the qualified vendor pool considerably."})
        if all_pass and scores["total"] < 75:
            alerts.append({"type": "info", "text": "Bidder qualifies but scores moderately. Additional due diligence recommended."})
        if all_pass and scores["total"] >= 90:
            alerts.append({"type": "success", "text": "Exceptional profile: Highly recommended for selection"})
    return alerts

# ─── Justification ───────────────────────────────────────────────────────────────

def fmt(n): return f"Rs.{int(n):,}"

def build_justification(company, turnover, experience, blacklisted,
                         price, min_t, min_e, t_pass, e_pass, b_pass,
                         all_pass, pass_count, scores, risks):
    name = company or "Unknown Bidder"
    if all_pass:
        strengths = []
        if turnover >= min_t * 1.5: strengths.append(f"strong financial capacity ({fmt(turnover)} vs {fmt(min_t)} required)")
        elif t_pass: strengths.append(f"adequate turnover ({fmt(turnover)})")
        if experience >= min_e * 1.5: strengths.append(f"extensive experience ({experience} yrs vs {min_e} required)")
        elif e_pass: strengths.append(f"sufficient experience ({experience} yrs)")
        if not blacklisted: strengths.append("clean compliance record")

        risk_notes = []
        if risks["financial"] == "Medium": risk_notes.append("turnover only marginally meets threshold")
        if risks["capability"] == "Medium": risk_notes.append("experience only marginally meets requirement")

        text  = f"OFFICIAL DETERMINATION: {name} is eligible and recommended for consideration.\n\n"
        text += f"STRENGTHS: {'; '.join(strengths)}.\n\n"
        text += f"SCORE: Composite eligibility score of {scores['total']}/100 (Turnover: {scores['turnover']}, Experience: {scores['experience']}, Compliance: {scores['compliance']}).\n\n"
        if risk_notes: text += f"RISK ASSESSMENT: {'; '.join(risk_notes)}. Additional due diligence advised.\n\n"
        text += f"REGULATORY COMPLIANCE: All {pass_count}/3 mandatory criteria satisfied. Bidder complies with current procurement policy guidelines."
    else:
        failures = []
        if not t_pass: failures.append(f"turnover shortfall ({fmt(turnover)} vs {fmt(min_t)} required)")
        if not e_pass: failures.append(f"experience deficit ({experience} yrs vs {min_e} required)")
        if not b_pass: failures.append("active blacklist status")

        text  = f"OFFICIAL DETERMINATION: {name} does not meet mandatory eligibility criteria.\n\n"
        text += f"DISQUALIFYING FACTORS: {'; '.join(failures)}.\n\n"
        text += f"SCORE: Composite score of {scores['total']}/100 is below the required threshold for qualification.\n\n"
        if pass_count > 0: text += f"PARTIAL COMPLIANCE: {pass_count}/3 criteria met, however, full compliance is mandatory for participation.\n\n"
        text += "REMEDIATION: The bidder is ineligible for the current tender. Future applications may be considered upon addressing the identified deficiencies."
    return text

# ─── Routes ─────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/<path:filename>')
def static_files(filename):
    return send_from_directory('.', filename)

# --- SUPABASE ISOLATION LAYER ---
def safe_db_insert(table, data):
    if not supabase:
        print("!! Supabase not configured. Skipping persistence.")
        return False
    try:
        print(f"--> Attempting Supabase insert into '{table}'...")
        res = supabase.table(table).insert(data).execute()
        if res.data:
            print(f"--> Insert Success! Row ID: {res.data[0].get('id', 'N/A')}")
        else:
            print("--> Insert completed, but no data returned (Check RLS policies).")
        return True
    except Exception as e:
        print(f"!! Supabase Insert FAILED: {str(e)}")
        print("!! TIP: Ensure you are using the 'service_role' key in .env and the table is named 'evaluations'.")
        return False

@app.route('/api/extract', methods=['POST'])
def extract():
    try:
        file = request.files.get('file')
        fname = file.filename if file else "document.txt"
        ext_timestamp = datetime.datetime.utcnow().isoformat()
        
        raw_text = ""
        if file:
            file_stream = BytesIO(file.read())
            raw_text = extract_text(file_stream, fname)
            
        if not raw_text or len(raw_text.strip()) < 10:
            return jsonify({
                "status": "error",
                "message": "Empty or unreadable document.",
                "company": "Unknown Bidder", "turnover": None, "experience": None, "price": None, "confidence": "Low"
            })

        extracted = heuristic_parse(raw_text)
        
        # Non-Procurement Early Exit
        if extracted.get("status") == "unsupported_document":
            return jsonify({
                "status": "NON_PROCUREMENT",
                "message": "This document does not appear to contain procurement or bidder-related information.",
                "confidence": "LOW",
                "company": "Unknown Bidder", "turnover": None, "experience": None, "price": None
            })
        
        return jsonify({
            "status": "success",
            "company": extracted["company"],
            "turnover": extracted["turnover"],
            "experience": extracted["experience"],
            "blacklisted": "yes" if extracted["blacklisted"] else "no",
            "price": extracted["price"],
            "confidence": extracted["confidence"],
            "file_name": fname,
            "file_type": fname.split('.')[-1] if '.' in fname else 'unknown',
            "extraction_timestamp": ext_timestamp,
            "extraction_confidence": extracted["confidence"],
            "extracted_fields": extracted 
        })
    except Exception as ex:
        print(f"!! CRITICAL EXTRACTION ERROR: {ex}")
        return jsonify({
            "status": "error",
            "message": "Internal processing error. Please try a standard text/PDF file.",
            "company": "Unknown Bidder", "turnover": None, "experience": None, "price": None, "confidence": "Low"
        })

@app.route('/api/evaluate', methods=['POST'])
def evaluate():
    try:
        data       = request.get_json() or {}
        company    = str(data.get('company', '')).strip() or "Unknown Bidder"
        turnover   = float(data.get('turnover',   0) or 0)
        experience = float(data.get('experience', 0) or 0)
        blacklisted = str(data.get('blacklisted', 'no')).lower() == 'yes'
        price      = float(data.get('price',      0) or 0)
        min_t      = float(data.get('min_turnover',   1_000_000) or 1_000_000)
        min_e      = float(data.get('min_experience', 3)         or 3)

        t_pass   = turnover   >= min_t
        e_pass   = experience >= min_e
        b_pass   = not blacklisted
        all_pass = t_pass and e_pass and b_pass
        pass_count = sum([t_pass, e_pass, b_pass])

        scores  = calculate_scores(turnover, experience, blacklisted, min_t, min_e)
        risks   = get_risks(turnover, experience, blacklisted, min_t, min_e)
        fair    = get_fairness(min_t, min_e)
        alerts  = get_alerts(min_t, min_e, blacklisted, all_pass, scores)
        just    = build_justification(company, turnover, experience, blacklisted,
                                       price, min_t, min_e, t_pass, e_pass, b_pass,
                                       all_pass, pass_count, scores, risks)
        conf         = data.get('extraction_confidence', "Medium")
        overall_risk = get_overall_risk(risks)
        trade_off    = get_trade_off_analysis(min_t, min_e)
        policy_rec   = get_policy_recommendation(min_t, min_e)
        policy_ver   = f"POL-{abs(hash((min_t, min_e))) % 9999:04d}"

        # Safe Persistence (Synced with SQL Schema)
        db_payload = {
            "company_name": company or "Unknown Bidder",
            "turnover": turnover,
            "experience": experience,
            "quoted_price": price,
            "verdict": "PASS" if all_pass else "FAIL",
            "confidence": conf,
            "score": scores["total"],
            "risk_level": overall_risk,
            "policy_snapshot": {"min_turnover": min_t, "min_experience": min_e, "policy_ver": policy_ver},
            "extracted_fields": data.get('extracted_fields', {}),
            "file_name": data.get('file_name'),
            "file_type": data.get('file_type'),
            "extraction_timestamp": data.get('extraction_timestamp') or datetime.datetime.utcnow().isoformat(),
            "evaluation_version": "v1.0"
        }
        safe_db_insert("evaluations", db_payload)

        # Audit entry
        audit_trail.append({
            "timestamp":  datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "company":    company, "verdict": "PASS" if all_pass else "FAIL",
            "score": scores["total"], "risk": overall_risk, "confidence": conf, "policy_ver": policy_ver
        })
        if len(audit_trail) > 50: audit_trail.pop(0)

        return jsonify({
            "verdict": "PASS" if all_pass else "FAIL",
            "company": company, "confidence": f"{conf} Confidence",
            "scores": scores, "risks": risks, "fairness": fair,
            "alerts": alerts, "justification": just, 
            "policy_rec": policy_rec, "overall_risk": overall_risk,
            "trade_off": trade_off,
            "checks": {
                "turnover":   {"passed": t_pass, "label": "Financial Threshold", "desc": f"{fmt(turnover)} vs {fmt(min_t)} required"},
                "experience": {"passed": e_pass, "label": "Sector Experience", "desc": f"{experience} yrs vs {min_e} yrs required"},
                "blacklist":  {"passed": b_pass, "label": "Compliance Registry", "desc": "No adverse records" if b_pass else "Active record found"},
            },
            "stats": {
                "price": fmt(price) if price else "Not Provided",
                "turnover": fmt(turnover) if turnover else "Not Provided",
                "experience": f"{experience} yrs" if experience else "Not Provided",
            }
        })
    except Exception as ex:
        print(f"!! EVALUATION ERROR: {ex}")
        return jsonify({"error": "Failed to evaluate bidder data. Please check inputs."}), 500

@app.route('/api/compare', methods=['POST'])
def compare():
    try:
        data   = request.get_json() or {}
        bidders = data.get('bidders', [])
        min_t  = float(data.get('min_turnover',   1_000_000) or 1_000_000)
        min_e  = float(data.get('min_experience', 3)         or 3)

        results = []
        for b in bidders:
            t   = float(b.get('turnover',   0) or 0)
            e   = float(b.get('experience', 0) or 0)
            bl  = str(b.get('blacklisted', 'no')).lower() == 'yes'
            p   = float(b.get('price', 0) or 0)
            tp  = t >= min_t; ep = e >= min_e; bp = not bl
            ap  = tp and ep and bp
            sc  = calculate_scores(t, e, bl, min_t, min_e)
            ri  = get_risks(t, e, bl, min_t, min_e)
            results.append({
                "company": b.get('company', 'Unknown'),
                "turnover": t, "experience": e, "price": p,
                "verdict": "PASS" if ap else "FAIL",
                "score": sc["total"],
                "risk_financial": ri["financial"],
                "risk_capability": ri["capability"],
                "risk_compliance": ri["compliance"],
                "checks": {"t": tp, "e": ep, "b": bp},
            })

        passing     = [r for r in results if r["verdict"] == "PASS"]
        best        = max(passing, key=lambda x: x["score"]) if passing else None
        recommended = best["company"] if best else None
        dec_conf    = "High" if (best and best["score"] >= 80) else ("Medium" if best else "N/A")
        rec_reason  = (f"{best['company']} selected: highest score ({best['score']}/100), "
                       f"Financial Risk: {best['risk_financial']}, Capability Risk: {best['risk_capability']}, "
                       f"all 3 mandatory criteria satisfied.") if best else "No bidder qualified under current policy."
        total_eval  = len(results)
        qualified   = len(passing)
        qual_rate   = round(qualified / total_eval * 100) if total_eval else 0
        return jsonify({"results": results, "recommended": recommended,
                        "decision_confidence": dec_conf, "recommended_reason": rec_reason,
                        "total_evaluated": total_eval, "qualified": qualified,
                        "qualification_rate": qual_rate})
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500

@app.route('/api/audit', methods=['GET'])
def get_audit():
    # Real-world app would query supabase here. Using in-memory fallback for immediate UI testing.
    return jsonify({"trail": list(reversed(audit_trail))})

@app.route('/api/report', methods=['POST'])
def report():
    d   = request.get_json() or {}
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    txt = f"""AI TENDER COPILOT - EVALUATION REPORT
{'='*42}
Generated : {now}

BIDDER INFORMATION
Company   : {d.get('company','Unknown Bidder')}
Turnover  : {d.get('turnover','Not Provided')}
Experience: {d.get('experience','Not Provided')}
Price     : {d.get('price','Not Provided')}
Blacklisted: {d.get('blacklisted','No')}

EVALUATION CRITERIA
Min Turnover  : {d.get('min_turnover','Not Provided')}
Min Experience: {d.get('min_experience','Not Provided')} yrs

RESULT
Final Decision : {d.get('verdict','Not Provided')}
Confidence     : {d.get('confidence','Not Provided')}
Total Score    : {d.get('score',0)}/100

SCORE BREAKDOWN
Turnover Score   : {d.get('t_score',0)}/100  (40%)
Experience Score : {d.get('e_score',0)}/100  (40%)
Compliance Score : {d.get('c_score',0)}/100  (20%)

RISK ASSESSMENT
Financial Risk  : {d.get('risk_fin','Not Provided')}
Capability Risk : {d.get('risk_cap','Not Provided')}
Compliance Risk : {d.get('risk_comp','Not Provided')}

JUSTIFICATION
{d.get('justification','Not Provided')}

{'='*42}
AI Tender Copilot | Decisions are indicative only.
"""
    company = d.get('company', 'report').replace(' ', '_')
    return Response(txt, mimetype='text/plain',
                    headers={'Content-Disposition': f'attachment;filename=tender_{company}.txt'})

# ─── Run ─────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print("\n== AI Tender Copilot Backend ==")
    print("   Visit: http://localhost:5000\n")
    app.run(debug=True, port=5000)
