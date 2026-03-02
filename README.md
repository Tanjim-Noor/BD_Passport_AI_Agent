# BD Passport AI Agent (Streamlit + CrewAI)

This project provides a **Bangladesh passport virtual consular assistant** with:
- Natural-language intake (paste any user text)
- Agent-based profile interpretation
- Policy + fee + document workflow
- Final output in proper format:
  - English table
  - Bangla summary
  - flags/inconsistencies
  - source metadata (scrape vs fallback)

---

## 1) Run the app

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

### Agent-only UI (CrewAI outputs only)

Use this version when you want policy/fee/checklist/final report to come only from agent task outputs:

```bash
streamlit run streamlit_agent_only.py
```

Open the URL shown by Streamlit (usually `http://localhost:8501`).

---

## 2) How to test quickly

1. Paste one scenario text from the sections below into **Applicant text**.
2. Click **Analyze**.
3. Validate these UI blocks:
   - **Interpreted Profile JSON**
   - **Final Output (English)**
   - **Final Output (Bangla)**
   - **Flags & Source**

---

## 3) Normal scenarios (expected successful output)

### Scenario N1 — Adult, urgent, 64 pages, 10 years
**Input text**
```text
I am a 24-year-old private sector employee. I need a 64-page passport urgently. I have NID and live in Dhaka.
```

**Expected highlights**
- Validity: `10 Years`
- Delivery Type: `Express`
- Total Fee: `10350 BDT`
- Required Identification: `NID (mandatory)`
- Flags: `None`

---

### Scenario N2 — Government staff, regular, 48 pages, 10 years
**Input text**
```text
I am 40, government staff, need a 48 page passport with regular delivery for 10 years. I have my NID.
```

**Expected highlights**
- Validity: `10 Years`
- Delivery Type: `Regular`
- Total Fee: `5750 BDT`
- Documents include: `NOC (No Objection Certificate)`
- Flags: `None`

---

### Scenario N3 — Adult with name-change requirement
**Input text**
```text
My age is 32. I work in private company. I want 48 pages, regular delivery, 10-year passport. I have NID and need name correction after marriage.
```

**Expected highlights**
- Validity: `10 Years`
- Total Fee: `5750 BDT`
- Documents include name-change proof:
  - `Marriage Certificate / Nikahnama / Divorce Deed (if applicable)`

---

### Scenario N4 — Senior applicant (>65)
**Input text**
```text
I am 70 years old. I need a 48-page passport for 10 years with regular delivery. I do not have NID.
```

**Expected highlights**
- Required Identification: `NID (preferred) or Birth Registration as per policy context`
- No mandatory-NID flag for this age bucket in current logic
- Fee (48 pages, 10 years, regular): `5750 BDT`

---

## 4) Error-handling showcase scenarios

These are useful for demoing your assignment’s inconsistency detection and resilient behavior.

### Scenario E1 — Minor requesting 10-year validity (policy inconsistency)
**Input text**
```text
I am 15 years old student. I want a 10-year passport, 48 pages, express service. I do not have NID.
```

**Expected flags**
- `Inconsistency: age 15 cannot request 10-year validity.`
- `Fee blocked: requested validity 10 is not permitted for this applicant.`

**Expected corrected output**
- Validity is auto-corrected to `5 Years`
- Express fee for 48 pages, 5 years: `6325 BDT`

---

### Scenario E2 — Minor requesting 64 pages (page restriction)
**Input text**
```text
I am 16, student. I need a 64-page passport, regular service, for 5 years.
```

**Expected flags**
- `Under-18 applicants are restricted to 48 pages; requested 64.`

**Expected behavior note**
- The app still computes fee with interpreted/normalized values and shows the warning in `Flags`.

---

### Scenario E3 — Adult missing NID (ID requirement violation)
**Input text**
```text
I am 28, private employee, need 48 pages and 10 years with express delivery. I do not have NID.
```

**Expected flags**
- `NID is required for applicants above 20 for local applications.`

**Expected fee**
- 48 pages, 10 years, express: `8050 BDT`

---

### Scenario E4 — Unknown urgency phrase (normalization fallback)
**Input text**
```text
I am 30, private job, need 64 pages for 10 years with lightning delivery. I have NID.
```

**Expected behavior**
- If interpreter returns an unsupported urgency label, normalization defaults to `regular`
- Fee likely follows `regular` delivery for selected page/validity

---

### Scenario E5 — Scrape failure fallback (resilience)
**Input text**
```text
I am 24 and need a 64-page passport urgently, 10 years, with NID.
```

**How to showcase**
- Run normally; if fee portal is blocked (e.g., 403), app auto-falls back to local DB

**Expected in UI**
- `Flags & Source` -> `source: fallback_local_db`
- `error` contains portal error message (for example HTTP 403)

---

### Scenario E6 — Empty input (UI-level guard)
**Input text**
```text

```

**Expected behavior**
- UI shows warning: `Please paste some text first.`
- No crash, no partial output

---

## 5) Optional advanced stress tests

### Stress S1 — Ambiguous input
**Input text**
```text
Need passport fast. Maybe 5 or 10 years. Not sure pages. I am adult from Dhaka.
```

**Expected behavior**
- Interpreter fills defaults for missing fields
- App still returns a complete formatted output

### Stress S2 — Mixed Bangla-English request
**Input text**
```text
আমার বয়স ২৬। I need urgent passport, 64 pages, 10 years. আমার NID আছে।
```

**Expected behavior**
- Interpreter should still produce structured JSON
- Final output sections render correctly (English + Bangla)

---

## 6) Expected fee reference (from local fallback DB)

| Pages | Validity | Regular | Express | Super Express |
|---|---:|---:|---:|---:|
| 48 | 5 years | 4025 | 6325 | 8625 |
| 48 | 10 years | 5750 | 8050 | 10350 |
| 64 | 5 years | 6325 | 8625 | 12075 |
| 64 | 10 years | 8050 | 10350 | 13800 |

---

## 7) Troubleshooting

- If app fails at startup with provider error:
  - Check `.env` values for `LLM_PROVIDER`, model, and API key/base URL.
- If using `LLM_PROVIDER=gemini`:
  - Ensure `GEMINI_API_KEY` is valid.
- If using `LLM_PROVIDER=ollama`:
  - Ensure Ollama server is running and model exists.
- If interpreter output parsing fails:
  - Retry once (LLM output formatting may vary).

---

## 8) Files of interest

- `streamlit_app.py` — Streamlit UI + all pipeline logic
- `passport_rules.json` — local fallback rules (fees/docs)
- `passport_report.md` — generated successful report samples
- `passport_report_error.md` — generated flagged report samples
