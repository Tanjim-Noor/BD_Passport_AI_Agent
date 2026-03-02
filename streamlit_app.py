from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import requests
import streamlit as st
from bs4 import BeautifulSoup
from crewai import Agent, Crew, LLM, Process, Task
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini/gemini-2.5-flash")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "ollama/qwen2.5:7b")

DELIVERY_MAP = {
    "regular": "regular",
    "normal": "regular",
    "express": "express",
    "urgent": "express",
    "super express": "super_express",
    "super_express": "super_express",
    "super-urgent": "super_express",
}


def build_llm() -> LLM:
    if LLM_PROVIDER == "gemini":
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY is missing while LLM_PROVIDER=gemini")
        return LLM(model=GEMINI_MODEL, api_key=GEMINI_API_KEY, temperature=0.2)
    if LLM_PROVIDER == "ollama":
        return LLM(model=OLLAMA_MODEL, base_url=OLLAMA_BASE_URL, temperature=0.2)
    raise ValueError("LLM_PROVIDER must be 'gemini' or 'ollama'")


SELECTED_LLM = build_llm()


DEFAULT_RULES = {
    "fees_2026": {
        "48_pages": {
            "5_years": {"regular": 4025, "express": 6325, "super_express": 8625},
            "10_years": {"regular": 5750, "express": 8050, "super_express": 10350},
        },
        "64_pages": {
            "5_years": {"regular": 6325, "express": 8625, "super_express": 12075},
            "10_years": {"regular": 8050, "express": 10350, "super_express": 13800},
        },
    },
    "required_docs": {
        "adult": ["NID Card", "Application Summary", "Payment Slip"],
        "minor_under_18": ["Birth Registration (English)", "Parents NID", "3R Photo"],
        "government_staff": ["NOC (No Objection Certificate)", "NID"],
        "name_change": ["Marriage Certificate / Nikahnama / Divorce Deed (if applicable)"],
        "profession_proof": ["Employment Certificate / Trade License / Student ID (as applicable)"],
    },
}


def load_rules() -> dict:
    rules_path = PROJECT_ROOT / "passport_rules.json"
    if not rules_path.exists():
        rules_path.write_text(json.dumps(DEFAULT_RULES, ensure_ascii=False, indent=2), encoding="utf-8")
    local_rules = json.loads(rules_path.read_text(encoding="utf-8"))
    if "fees_2026" not in local_rules:
        local_rules["fees_2026"] = DEFAULT_RULES["fees_2026"]
    if "required_docs" not in local_rules:
        local_rules["required_docs"] = DEFAULT_RULES["required_docs"]
    return local_rules


LOCAL_RULES = load_rules()


@dataclass
class UserProfile:
    age: int
    profession: str
    urgency: str
    page_count: int
    requested_validity_years: int | None = None
    has_nid: bool = False
    location: str = "Bangladesh"
    needs_name_change: bool = False


def normalize_profile(raw: dict) -> UserProfile:
    age = int(raw["age"])
    profession = str(raw.get("profession", "unknown")).strip().lower()
    urgency_raw = str(raw.get("urgency", "regular")).strip().lower()
    urgency = DELIVERY_MAP.get(urgency_raw, "regular")
    page_count = int(raw.get("page_count", 48))
    if page_count not in (48, 64):
        page_count = 48
    requested_validity_years = raw.get("requested_validity_years")
    if requested_validity_years is not None:
        requested_validity_years = int(requested_validity_years)
    has_nid = bool(raw.get("has_nid", False))
    location = str(raw.get("location", "Bangladesh")).strip()
    needs_name_change = bool(raw.get("needs_name_change", False))
    return UserProfile(
        age=age,
        profession=profession,
        urgency=urgency,
        page_count=page_count,
        requested_validity_years=requested_validity_years,
        has_nid=has_nid,
        location=location,
        needs_name_change=needs_name_change,
    )


def policy_rules(profile: UserProfile) -> dict:
    flags = []
    if profile.age < 18:
        allowed_validity_years = [5]
        required_id = "Birth Registration (English)"
        page_constraint = 48
    elif profile.age > 65:
        allowed_validity_years = [5, 10]
        required_id = "NID (preferred) or Birth Registration as per policy context"
        page_constraint = None
    elif profile.age < 20:
        allowed_validity_years = [5, 10]
        required_id = "NID or Birth Registration (English)"
        page_constraint = None
    else:
        allowed_validity_years = [5, 10]
        required_id = "NID (mandatory)"
        page_constraint = None

    recommended_validity = 10 if 10 in allowed_validity_years else 5

    if profile.requested_validity_years and profile.requested_validity_years not in allowed_validity_years:
        flags.append(
            f"Inconsistency: age {profile.age} cannot request {profile.requested_validity_years}-year validity."
        )

    if page_constraint and profile.page_count != page_constraint:
        flags.append(f"Under-18 applicants are restricted to {page_constraint} pages; requested {profile.page_count}.")

    if profile.age >= 20 and not profile.has_nid:
        flags.append("NID is required for applicants above 20 for local applications.")

    return {
        "allowed_validity_years": allowed_validity_years,
        "required_id": required_id,
        "recommended_validity": recommended_validity,
        "flags": flags,
    }


def compute_fee(profile: UserProfile, policy_output: dict, fee_source: dict) -> dict:
    flags = list(policy_output.get("flags", []))
    fees = fee_source.get("fees_2026", {})

    validity = profile.requested_validity_years or policy_output["recommended_validity"]
    if validity not in policy_output["allowed_validity_years"]:
        flags.append(f"Fee blocked: requested validity {validity} is not permitted for this applicant.")
        validity = policy_output["recommended_validity"]

    page_key = f"{profile.page_count}_pages"
    validity_key = f"{validity}_years"
    delivery_key = profile.urgency

    base_fee = fees.get(page_key, {}).get(validity_key, {}).get(delivery_key)
    if base_fee is None:
        flags.append("Fee lookup failed in selected source; fallback to default local DB structure.")
        base_fee = DEFAULT_RULES["fees_2026"][page_key][validity_key][delivery_key]

    vat_rate = 0.15
    vat_component = round(base_fee * vat_rate)
    total_fee = int(base_fee)

    return {
        "validity_years": validity,
        "delivery_type": delivery_key,
        "base_without_vat": round(base_fee / (1 + vat_rate), 2),
        "vat_rate": vat_rate,
        "vat_component_estimate": vat_component,
        "total_fee_bdt": total_fee,
        "flags": flags,
    }


def build_checklist(profile: UserProfile, docs_source: dict) -> list[str]:
    docs_cfg = docs_source.get("required_docs", {})
    checklist = []

    if profile.age < 18:
        checklist.extend(docs_cfg.get("minor_under_18", []))
    else:
        checklist.extend(docs_cfg.get("adult", []))

    if "gov" in profile.profession or "government" in profile.profession:
        checklist.extend(docs_cfg.get("government_staff", []))

    if profile.needs_name_change:
        checklist.extend(docs_cfg.get("name_change", []))

    checklist.extend(docs_cfg.get("profession_proof", []))

    deduped = []
    seen = set()
    for item in checklist:
        key = item.strip().lower()
        if key and key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def scrape_fees_from_portal(timeout: int = 20) -> tuple[dict, dict]:
    url = "https://www.epassport.gov.bd/instructions/passport-fees"
    metadata = {"source": "scrape", "url": url, "error": None}
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        text = BeautifulSoup(resp.text, "html.parser").get_text(" ", strip=True)

        patterns = {
            ("48_pages", "5_years", "regular"): r"48 pages and 5 years validity.*?Regular delivery:\\s*TK\\s*([\\d,]+)",
            ("48_pages", "5_years", "express"): r"48 pages and 5 years validity.*?Express delivery:\\s*TK\\s*([\\d,]+)",
            ("48_pages", "5_years", "super_express"): r"48 pages and 5 years validity.*?Super Express delivery:\\s*TK\\s*([\\d,]+)",
            ("48_pages", "10_years", "regular"): r"48 pages and 10 years validity.*?Regular delivery:\\s*TK\\s*([\\d,]+)",
            ("48_pages", "10_years", "express"): r"48 pages and 10 years validity.*?Express delivery:\\s*TK\\s*([\\d,]+)",
            ("48_pages", "10_years", "super_express"): r"48 pages and 10 years validity.*?Super Express delivery:\\s*TK\\s*([\\d,]+)",
            ("64_pages", "5_years", "regular"): r"64 pages and 5 years validity.*?Regular delivery:\\s*TK\\s*([\\d,]+)",
            ("64_pages", "5_years", "express"): r"64 pages and 5 years validity.*?Express delivery:\\s*TK\\s*([\\d,]+)",
            ("64_pages", "5_years", "super_express"): r"64 pages and 5 years validity.*?Super Express delivery:\\s*TK\\s*([\\d,]+)",
            ("64_pages", "10_years", "regular"): r"64 pages and 10 years validity.*?Regular delivery:\\s*TK\\s*([\\d,]+)",
            ("64_pages", "10_years", "express"): r"64 pages and 10 years validity.*?Express delivery:\\s*TK\\s*([\\d,]+)",
            ("64_pages", "10_years", "super_express"): r"64 pages and 10 years validity.*?Super Express delivery:\\s*TK\\s*([\\d,]+)",
        }

        parsed = {"fees_2026": {"48_pages": {"5_years": {}, "10_years": {}}, "64_pages": {"5_years": {}, "10_years": {}}}}

        for (p, v, d), pattern in patterns.items():
            match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
            if match:
                parsed["fees_2026"][p][v][d] = int(match.group(1).replace(",", ""))

        enough_data = all(key in parsed["fees_2026"]["48_pages"]["5_years"] for key in ["regular", "express", "super_express"])
        if not enough_data:
            raise ValueError("Could not parse complete fee table from portal text.")

        parsed["required_docs"] = LOCAL_RULES.get("required_docs", DEFAULT_RULES["required_docs"])
        return parsed, metadata
    except Exception as exc:
        metadata["source"] = "fallback_local_db"
        metadata["error"] = str(exc)
        return LOCAL_RULES, metadata


def build_agents() -> tuple[Agent, Agent, Agent]:
    policy_guardian = Agent(
        role="Policy Guardian (Bangladesh Passport Policy Expert)",
        goal="Determine applicant eligibility, allowed passport validity, and correct identity document requirements from age and policy.",
        backstory="A senior consular policy analyst who reviews Bangladesh e-passport rules for age brackets and legal ID requirements.",
        llm=SELECTED_LLM,
        verbose=True,
        allow_delegation=False,
    )

    chancellor = Agent(
        role="Chancellor of the Exchequer (Financial Auditor)",
        goal="Calculate exact e-passport fee from official fee structure and validate VAT-consistent totals.",
        backstory="A meticulous government fee auditor who verifies passport charges, delivery surcharges, and consistency flags.",
        llm=SELECTED_LLM,
        verbose=True,
        allow_delegation=False,
    )

    document_architect = Agent(
        role="Document Architect (Documentation Officer)",
        goal="Generate a customized, applicant-specific passport document checklist.",
        backstory="A documentation specialist in a consular office known for preparing complete and error-free application bundles.",
        llm=SELECTED_LLM,
        verbose=True,
        allow_delegation=False,
    )
    return policy_guardian, chancellor, document_architect


def build_crew(profile: UserProfile, source_metadata: dict) -> Crew:
    policy_guardian, chancellor, document_architect = build_agents()

    policy_task = Task(
        description=(
            f"Applicant profile: {asdict(profile)}. "
            "Determine validity eligibility and identification requirements by age policy. "
            "If under 18, enforce 5-year and 48-page constraints."
        ),
        expected_output="JSON with allowed_validity_years, required_id, recommended_validity, flags.",
        agent=policy_guardian,
    )

    fee_task = Task(
        description=(
            "Using Policy Guardian output as context, compute inside-Bangladesh fee for 2026 structure "
            f"for {profile.page_count} pages and delivery={profile.urgency}. Validate consistency and flag conflicts."
        ),
        expected_output="JSON with validity_years, delivery_type, total_fee_bdt, VAT explanation, flags.",
        agent=chancellor,
        context=[policy_task],
    )

    doc_task = Task(
        description=(
            "Build checklist for this applicant including age, profession and optional name-change evidence. "
            "Deduplicate and keep concise."
        ),
        expected_output="JSON with checklist array and notes.",
        agent=document_architect,
        context=[policy_task],
    )

    final_task = Task(
        description=(
            "Produce final readiness report as an English markdown table plus Bangla summary. "
            f"Include source metadata: {source_metadata} and all inconsistency flags."
        ),
        expected_output="English markdown table + Bangla summary + data source (scrape/fallback).",
        agent=document_architect,
        context=[policy_task, fee_task, doc_task],
    )

    return Crew(
        agents=[policy_guardian, chancellor, document_architect],
        tasks=[policy_task, fee_task, doc_task, final_task],
        process=Process.sequential,
        verbose=True,
    )


def render_report(profile: UserProfile, policy_output: dict, fee_output: dict, checklist: list[str], source_meta: dict) -> dict:
    flags = sorted(set(policy_output.get("flags", []) + fee_output.get("flags", [])))

    rows = [
        {"Field": "Applicant Age", "Value": profile.age},
        {"Field": "Profession", "Value": profile.profession},
        {"Field": "Validity", "Value": f"{fee_output['validity_years']} Years"},
        {"Field": "Delivery Type", "Value": fee_output["delivery_type"].replace("_", " ").title()},
        {"Field": "Passport Pages", "Value": profile.page_count},
        {"Field": "Total Fee", "Value": f"{fee_output['total_fee_bdt']} BDT"},
        {"Field": "Required Identification", "Value": policy_output["required_id"]},
        {"Field": "Documents Needed", "Value": ", ".join(checklist)},
        {"Field": "Flags", "Value": "; ".join(flags) if flags else "None"},
        {"Field": "Data Source", "Value": source_meta["source"]},
    ]

    english_table = "| Field | Value |\n|---|---|\n" + "\n".join(f"| {r['Field']} | {r['Value']} |" for r in rows)

    bangla_summary = (
        "### বাংলা সারাংশ\n"
        f"- আবেদনকারীর বয়স: {profile.age}\n"
        f"- পাসপোর্টের মেয়াদ: {fee_output['validity_years']} বছর\n"
        f"- ডেলিভারি ধরন: {fee_output['delivery_type']}\n"
        f"- মোট ফি: {fee_output['total_fee_bdt']} টাকা\n"
        f"- প্রয়োজনীয় ডকুমেন্ট: {', '.join(checklist)}\n"
        f"- সতর্কতা: {('; '.join(flags) if flags else 'কোনো অসঙ্গতি নেই')}\n"
    )

    return {
        "rows": rows,
        "english_markdown_table": english_table,
        "bangla_summary": bangla_summary,
        "flags": flags,
        "source_metadata": source_meta,
    }


def extract_first_json_object(text: str) -> dict:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        return json.loads(fenced.group(1))

    bare = re.search(r"(\{.*\})", text, flags=re.DOTALL)
    if bare:
        return json.loads(bare.group(1))

    raise ValueError("Could not find JSON object in interpreter output.")


def to_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"true", "yes", "y", "1"}:
            return True
        if v in {"false", "no", "n", "0"}:
            return False
    return default


def interpret_profile_with_agent(user_text: str) -> dict:
    interpreter_agent = Agent(
        role="Profile Interpreter Agent",
        goal="Convert free-form user text about passport needs into a strict JSON profile schema.",
        backstory="A senior intake officer who standardizes applicant narratives into machine-readable fields for consular processing.",
        llm=SELECTED_LLM,
        verbose=True,
        allow_delegation=False,
    )

    schema_hint = {
        "age": "int",
        "profession": "string",
        "urgency": "one of ['regular','express','super_express']",
        "page_count": "48 or 64",
        "requested_validity_years": "5 or 10 or null",
        "has_nid": "bool",
        "location": "string",
        "needs_name_change": "bool (default false if not mentioned)",
    }

    extraction_task = Task(
        description=(
            "Read the applicant message and return ONLY a valid JSON object with the required keys. "
            "Do not add explanations. Use null when value is not specified. "
            f"Required schema: {json.dumps(schema_hint, ensure_ascii=False)}\n\n"
            f"Applicant text:\n{user_text}"
        ),
        expected_output="A single strict JSON object and nothing else.",
        agent=interpreter_agent,
    )

    extraction_crew = Crew(
        agents=[interpreter_agent],
        tasks=[extraction_task],
        process=Process.sequential,
        verbose=True,
    )

    raw = str(extraction_crew.kickoff())
    parsed = extract_first_json_object(raw)

    normalized = {
        "age": int(parsed.get("age", 24)),
        "profession": str(parsed.get("profession", "unknown")),
        "urgency": str(parsed.get("urgency", "regular")),
        "page_count": int(parsed.get("page_count", 48)),
        "requested_validity_years": parsed.get("requested_validity_years", None),
        "has_nid": to_bool(parsed.get("has_nid", False), default=False),
        "location": str(parsed.get("location", "Bangladesh")),
        "needs_name_change": to_bool(parsed.get("needs_name_change", False), default=False),
    }

    if normalized["requested_validity_years"] is not None:
        try:
            normalized["requested_validity_years"] = int(normalized["requested_validity_years"])
        except Exception:
            normalized["requested_validity_years"] = None

    return normalized


def run_case_from_text(user_text: str, run_crew: bool) -> dict:
    profile_input = interpret_profile_with_agent(user_text)
    profile = normalize_profile(profile_input)

    knowledge_base, source_metadata = scrape_fees_from_portal()

    crew_debug: dict[str, str | None] = {"kickoff_result": None, "kickoff_error": None}
    if run_crew:
        try:
            crew = build_crew(profile, source_metadata)
            crew_debug["kickoff_result"] = str(crew.kickoff())
        except Exception as exc:
            crew_debug["kickoff_error"] = str(exc)

    policy_output = policy_rules(profile)
    fee_output = compute_fee(profile, policy_output, knowledge_base)
    checklist = build_checklist(profile, knowledge_base)
    report = render_report(profile, policy_output, fee_output, checklist, source_metadata)

    report["profile"] = asdict(profile)
    report["interpreted_profile"] = profile_input
    report["crew_debug"] = crew_debug
    return report


def main() -> None:
    st.set_page_config(page_title="BD Passport AI Agent", layout="wide")
    st.title("Bangladesh Passport Virtual Consular Officer")
    st.caption("Paste any natural-language applicant text and get the final formatted output.")

    with st.sidebar:
        st.subheader("Runtime")
        st.write(f"LLM Provider: {LLM_PROVIDER}")
        st.write(f"Model: {SELECTED_LLM.model}")
        run_crew = st.checkbox("Run full 3-agent crew (verbose backend)", value=True)

    default_text = (
        "I am a 24-year-old private sector employee. "
        "I need a 64-page passport urgently because I have a business trip in two weeks. "
        "I have an NID and I live in Dhaka."
    )

    user_text = st.text_area("Applicant text", value=default_text, height=180)

    if st.button("Analyze", type="primary"):
        if not user_text.strip():
            st.warning("Please paste some text first.")
            return

        with st.spinner("Running interpreter + passport agents..."):
            try:
                report = run_case_from_text(user_text, run_crew=run_crew)
            except Exception as exc:
                st.error(f"Processing failed: {exc}")
                return

        st.subheader("Interpreted Profile JSON")
        st.json(report["interpreted_profile"])

        st.subheader("Final Output (English)")
        st.table(report["rows"])

        st.subheader("Final Output (Bangla)")
        st.markdown(report["bangla_summary"])

        st.subheader("Markdown Table")
        st.markdown(report["english_markdown_table"])

        st.subheader("Flags & Source")
        st.write("Flags:", report["flags"] if report["flags"] else ["None"])
        st.json(report["source_metadata"])

        if run_crew:
            with st.expander("Crew Debug"):
                st.write("Kickoff error:", report["crew_debug"]["kickoff_error"])
                st.text_area("Kickoff result", value=report["crew_debug"]["kickoff_result"] or "", height=220)


if __name__ == "__main__":
    main()
