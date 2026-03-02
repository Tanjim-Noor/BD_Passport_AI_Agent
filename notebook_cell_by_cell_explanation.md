# Cell-by-Cell Demo Guide for `bd_passport_ai_agent.ipynb`

This guide explains **what each notebook cell does**, **what output was observed (without re-running)**, and **how it maps to your assignment requirements**.

---

## Quick context from saved outputs

- The notebook is using the project venv Python executable.
- `requirements.txt` already includes required unpinned packages.
- Active provider is `ollama` with model `ollama/qwen2.5:7b`.
- Live scraping attempt returned `403 Forbidden` from the passport fees URL.
- The pipeline correctly switched to `fallback_local_db`.
- Scenario tests ran and assertion checks passed.
- Reports were exported to:
  - `passport_report.md`
  - `passport_report_error.md`

---

## Cell-by-cell explanation

### Cell 1 (Markdown)
**Purpose:** Notebook title and scope.
**Why it matters:** Sets expectation that this is a CrewAI multi-agent passport advisor with fallback and bilingual reporting.
**Requirement match:** Project overview + output scope.

### Cell 2 (Markdown)
**Purpose:** Section header for environment verification.
**Requirement match:** Must use current project venv.

### Cell 3 (Code)
**Purpose:** Verifies runtime path, venv, and root directory.
**Observed output:**
- Project root points to your `BD_Passport_AI_Agent` folder.
- Python executable is inside `venv/Scripts/python.exe`.
- `Using project venv kernel: True`.
**Requirement match:** “must use venv.”

### Cell 4 (Markdown)
**Purpose:** Section header for dependency review.
**Requirement match:** Requirements management.

### Cell 5 (Code)
**Purpose:** Reads `requirements.txt` and checks missing baseline dependencies.
**Observed output:**
- Current lines include all required packages.
- `Suggested append lines: []`.
**Requirement match:** “modify requirements if necessary,” “latest/no pin versions.”

### Cell 6 (Markdown)
**Purpose:** Section header for install/sync.

### Cell 7 (Code)
**Purpose:** Runs pip upgrade/install and import checks.
**Observed output:** all checks `OK` for `crewai`, `crewai_tools`, `litellm`, `dotenv`, `requests`, `bs4`.
**Requirement match:** install in active venv and validate stack.

### Cell 8 (Markdown)
**Purpose:** Section header for `.env` provider switching.

### Cell 9 (Code)
**Purpose:** Loads `.env`, masks secrets, selects LLM config (`ollama` or `gemini`).
**Observed output:**
- `LLM_PROVIDER: ollama`
- model/base URL loaded correctly
- LLM object initialized successfully.
**Requirement match:** provider switching + safe env handling.

### Cell 10 (Markdown)
**Purpose:** Section header for MCP plan.

### Cell 11 (Code)
**Purpose:** Stores explicit orchestration plan for Context7 + Apify workflow.
**Observed output:** printed 5-step plan (docs → scrape → fallback implementation → crew delegation → tests/export).
**Requirement match:** “Must plan using Context7 and Apify step by step.”

### Cell 12 (Markdown)
**Purpose:** Section header for fallback DB.

### Cell 13 (Code)
**Purpose:** Creates/loads `passport_rules.json` with 2026 fee structure and required docs.
**Observed output:** local DB loaded; top-level keys present.
**Requirement match:** mandatory local fallback database.

### Cell 14 (Markdown)
**Purpose:** Section header for input schema/normalization.

### Cell 15 (Code)
**Purpose:** Defines `UserProfile` and normalization logic:
- urgency synonyms (`urgent` -> `express`)
- page count guard (`48`/`64`)
- typed fields.
**Observed output:** none (definition cell).
**Requirement match:** robust user profile parsing and normalization.

### Cell 16 (Markdown)
**Purpose:** Section header for Policy Guardian agent.

### Cell 17 (Code)
**Purpose:**
- Implements `policy_rules(profile)` with age-based eligibility:
  - under 18: 5-year and 48-page constraint + birth registration
  - 20+ NID constraint
- Creates CrewAI agent persona for Policy Guardian.
**Observed output:** none (definition cell).
**Requirement match:** Agent 1 persona + age restriction logic + inconsistency flag foundation.

### Cell 18 (Markdown)
**Purpose:** Section header for Fee Calculator agent.

### Cell 19 (Code)
**Purpose:**
- Implements `compute_fee(...)` using page/validity/delivery from fee DB.
- Blocks invalid requested validity and adds flags.
- Computes VAT-related values and returns total fee.
- Creates Chancellor agent persona.
**Observed output:** none (definition cell).
**Requirement match:** Agent 2 persona + fee calculation + inconsistency handling.

### Cell 20 (Markdown)
**Purpose:** Section header for Document Architect agent.

### Cell 21 (Code)
**Purpose:**
- Builds dynamic checklist by age/profession/name-change.
- Adds govt docs (`NOC`) and deduplicates items.
- Creates Document Architect persona.
**Observed output:** none (definition cell).
**Requirement match:** Agent 3 persona + customized document checklist.

### Cell 22 (Markdown)
**Purpose:** Section header for task graph and delegation.

### Cell 23 (Code)
**Purpose:** Builds Crew tasks with explicit dependency chain:
- Policy task
- Fee task (with `context=[policy_task]`)
- Document task
- Final report task (context from all previous)
and sets `verbose=True`.
**Observed output:** none (definition cell).
**Requirement match:** required task delegation + verbose debugging setup.

### Cell 24 (Markdown)
**Purpose:** Section header for scrape/fallback pipeline.

### Cell 25 (Code)
**Purpose:**
- Attempts HTTP scrape of official fees page.
- Parses fee patterns.
- If failure/partial parse: fallback to local DB with error metadata.
**Observed output:**
- `source: fallback_local_db`
- error includes `403 Client Error: Forbidden`.
**Requirement match:** scrape-first + resilient fallback.

### Cell 26 (Markdown)
**Purpose:** Section header for rendering output.

### Cell 27 (Code)
**Purpose:** Creates final report renderer:
- English Markdown table
- Bangla summary
- unified flag list
- source metadata included.
**Observed output:** none (definition cell).
**Requirement match:** required output format + bilingual reporting.

### Cell 28 (Markdown)
**Purpose:** Section header for scenario tests.

### Cell 29 (Code)
**Purpose:** Runs 4 scenarios end-to-end:
1. adult private urgent
2. minor requesting invalid 10-year
3. government staff
4. adult missing NID

Also executes crew kickoff (verbose traces), deterministic logic, and assertions.

**Observed output highlights:**
- Crew verbose traces shown (Task Started/Completed, Agent Started, etc.).
- Warning shown: installed `crewai` version reported as yanked (informational).
- Minor invalid scenario table shows flags:
  - invalid 10-year request blocked
  - inconsistency flagged for age 15.
- Missing-NID adult scenario flags NID requirement.
- Final line: `Scenario assertions passed.`

**Requirement match:** error handling, inconsistency flagging, and demo scenarios.

### Cell 30 (Markdown)
**Purpose:** Section header for artifact export.

### Cell 31 (Code)
**Purpose:** Writes normal vs flagged reports to markdown files.
**Observed output:** both report files written successfully.
**Requirement match:** deliverable artifacts for review/demo.

---

## How this notebook satisfies your project requirements

## 1) Minimum three specialized agents
- Implemented as CrewAI `Agent` objects:
  - Policy Guardian
  - Chancellor of the Exchequer
  - Document Architect
- Each has role, goal, and backstory.

## 2) Age policy and eligibility constraints
- Encoded in `policy_rules`:
  - Under 18 restrictions enforced
  - NID/Birth Registration conditions by age bands
  - inconsistency flags added.

## 3) Fee calculation with 2026 structure
- Uses 2026 matrix from local DB and scrape pipeline.
- Delivery/page/validity dimensions are applied.
- VAT fields are computed and included in fee result object.

## 4) Task delegation
- `fee_task` receives `policy_task` output via `context=[policy_task]`.
- Final task receives policy + fee + doc contexts.

## 5) English markdown table output
- Produced in renderer and visible in scenario outputs.

## 6) Bangla companion report
- Bangla summary generated from same normalized result model.

## 7) Error handling for invalid requests
- Example: 15-year-old requesting 10-year validity gets explicit flags.
- Assertion verifies this behavior.

## 8) Scrape fallback behavior
- Runtime scrape failed (`403`), fallback activated.
- Source metadata persisted in output (`fallback_local_db`).

## 9) Verbose debugging for demo visibility
- Crew kickoff logs include task/agent lifecycle traces.

## 10) venv + requirements usage
- Kernel and interpreter confirmed from project `venv`.
- Requirements validated and installed without pinned versions.

---

## What to say in your video demo (short script)

1. “First, I verify the notebook is running in the project venv.”
2. “Then I validate dependencies and load `.env` with provider switching between Ollama/Gemini.”
3. “I show the MCP orchestration plan using Context7 + Apify.”
4. “The system tries live scraping; when it gets blocked (403), it falls back to local rules automatically.”
5. “I run four scenarios, including invalid minor validity, and show flags in the final table.”
6. “Finally, the notebook exports clean and flagged reports to markdown files for submission.”

---

## Important note for Q&A

You may get asked why fee totals are not multiplied by 1.15 in display. In this notebook, the inside-Bangladesh fee table values are already treated as final payable values (matching your provided local DB), while VAT-related fields are still computed for transparency in the fee object.
