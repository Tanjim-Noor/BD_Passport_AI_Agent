from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

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


def build_llm() -> LLM:
    if LLM_PROVIDER == "gemini":
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY is missing while LLM_PROVIDER=gemini")
        return LLM(model=GEMINI_MODEL, api_key=GEMINI_API_KEY, temperature=0.2)
    if LLM_PROVIDER == "ollama":
        return LLM(model=OLLAMA_MODEL, base_url=OLLAMA_BASE_URL, temperature=0.2)
    raise ValueError("LLM_PROVIDER must be 'gemini' or 'ollama'")


SELECTED_LLM = build_llm()


def load_local_rules_text() -> str:
    rules_path = PROJECT_ROOT / "passport_rules.json"
    if not rules_path.exists():
        raise FileNotFoundError("passport_rules.json not found. Please keep fallback rules in project root.")
    payload = json.loads(rules_path.read_text(encoding="utf-8"))
    return json.dumps(payload, ensure_ascii=False, indent=2)


def get_knowledge_context(timeout: int = 20) -> tuple[str, dict[str, Any]]:
    url = "https://www.epassport.gov.bd/instructions/passport-fees"
    metadata: dict[str, Any] = {"source": "scrape", "url": url, "error": None}

    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        page_text = BeautifulSoup(response.text, "html.parser").get_text(" ", strip=True)
        if len(page_text) < 300:
            raise ValueError("Scraped content is too short for reliable fee/policy context.")
        return page_text, metadata
    except Exception as exc:
        metadata["source"] = "fallback_local_db"
        metadata["error"] = str(exc)
        local_rules_text = load_local_rules_text()
        return local_rules_text, metadata


def extract_json_from_text(text: str) -> dict[str, Any] | None:
    if not text:
        return None

    fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced_match:
        try:
            return json.loads(fenced_match.group(1))
        except Exception:
            pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1]
        try:
            return json.loads(candidate)
        except Exception:
            return None

    return None


def get_task_raw_output(task: Task) -> str:
    output_obj = getattr(task, "output", None)
    if output_obj is None:
        return ""
    raw_value = getattr(output_obj, "raw", output_obj)
    return str(raw_value)


def parse_markdown_table_pairs(markdown_text: str) -> list[tuple[str, str]]:
    if not markdown_text:
        return []

    table_lines = [line.strip() for line in markdown_text.splitlines() if line.strip().startswith("|")]
    if len(table_lines) < 2:
        return []

    parsed_rows: list[list[str]] = []
    for line in table_lines:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        parsed_rows.append(cells)

    if len(parsed_rows) < 2:
        return []

    header = parsed_rows[0]
    data_rows = [
        row
        for row in parsed_rows[1:]
        if not all(cell.replace(":", "").replace("-", "").strip() == "" for cell in row)
    ]

    if not data_rows:
        return []

    if len(header) == 2:
        result: list[tuple[str, str]] = []
        for row in data_rows:
            if len(row) >= 2:
                result.append((row[0], row[1]))
        return result

    first_row = data_rows[0]
    return [(header[idx], first_row[idx] if idx < len(first_row) else "") for idx in range(len(header))]


def parse_key_value_lines(text: str) -> list[tuple[str, str]]:
    if not text:
        return []

    cleaned = text.replace("### বাংলা সারাংশ", "").strip()
    lines = [line.strip().lstrip("- ").strip() for line in cleaned.splitlines() if line.strip()]
    pairs: list[tuple[str, str]] = []
    for line in lines:
        if ":" in line:
            key, value = line.split(":", 1)
            pairs.append((key.strip(), value.strip()))
        else:
            pairs.append(("তথ্য", line.strip()))
    return pairs


def contains_latin_letters(text: str) -> bool:
    return bool(re.search(r"[A-Za-z]", text or ""))


def translate_pairs_to_bangla_with_agent(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    if not pairs:
        return []

    translator_agent = Agent(
        role="Bangla Localization Agent",
        goal="Translate structured English passport summary rows into natural Bangla while preserving meaning and numbers.",
        backstory="A bilingual consular localization specialist producing clear Bangla outputs for applicants.",
        llm=SELECTED_LLM,
        verbose=True,
        allow_delegation=False,
    )

    payload = {"rows": [{"field": key, "value": value} for key, value in pairs]}

    translation_task = Task(
        description=(
            "Translate the following structured JSON rows into Bangla. "
            "Return ONLY strict JSON in this exact shape: "
            "{'rows':[{'field_bn':'...','value_bn':'...'}]}. "
            "No extra text, no markdown.\n\n"
            f"Input JSON:\n{json.dumps(payload, ensure_ascii=False)}"
        ),
        expected_output="Strict JSON object only.",
        agent=translator_agent,
    )

    translation_crew = Crew(
        agents=[translator_agent],
        tasks=[translation_task],
        process=Process.sequential,
        verbose=True,
    )

    raw_result = str(translation_crew.kickoff())
    parsed = extract_json_from_text(raw_result)
    if not parsed:
        return []

    rows = parsed.get("rows", [])
    output_pairs: list[tuple[str, str]] = []
    for row in rows:
        field_bn = str(row.get("field_bn", "")).strip()
        value_bn = str(row.get("value_bn", "")).strip()
        if field_bn or value_bn:
            output_pairs.append((field_bn or "তথ্য", value_bn))
    return output_pairs


def build_bangla_pairs(final_data: dict[str, Any], english_pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    candidate_pairs: list[tuple[str, str]] = []

    bangla_table = final_data.get("bangla_markdown_table")
    if isinstance(bangla_table, str) and bangla_table.strip():
        table_pairs = parse_markdown_table_pairs(bangla_table)
        if table_pairs:
            candidate_pairs = table_pairs

    if not candidate_pairs:
        bangla_summary = final_data.get("bangla_summary")
        if isinstance(bangla_summary, str) and bangla_summary.strip():
            summary_pairs = parse_key_value_lines(bangla_summary)
            if summary_pairs:
                candidate_pairs = summary_pairs

    if candidate_pairs:
        joined = " ".join([f"{k} {v}" for k, v in candidate_pairs])
        if not contains_latin_letters(joined):
            return candidate_pairs

    source_for_translation = english_pairs if english_pairs else candidate_pairs
    translated_pairs = translate_pairs_to_bangla_with_agent(source_for_translation)
    if translated_pairs:
        return translated_pairs

    return candidate_pairs if candidate_pairs else english_pairs


def render_vertical_table(title: str, col1: str, col2: str, pairs: list[tuple[str, str]]) -> None:
    st.markdown(f"### {title}")
    table_rows = [{col1: key, col2: value} for key, value in pairs]
    st.table(table_rows)


def render_vertical_output(final_data: dict[str, Any], fallback_source_meta: dict[str, Any]) -> None:
    english_table = final_data.get("english_markdown_table")
    flags = final_data.get("flags")
    source_meta = final_data.get("source_metadata", fallback_source_meta)

    english_pairs = parse_markdown_table_pairs(english_table or "")
    if english_pairs:
        render_vertical_table("English Summary", "Field", "Value", english_pairs)
    else:
        st.info("Could not parse English table. Showing raw English output.")
        st.text_area("English raw", value=english_table or "", height=180)

    bangla_pairs = build_bangla_pairs(final_data, english_pairs)
    if bangla_pairs:
        render_vertical_table("বাংলা সারাংশ", "ক্ষেত্র", "মান", bangla_pairs)
    else:
        st.info("Could not parse Bangla summary. Showing raw Bangla output.")
        bangla_summary = final_data.get("bangla_summary")
        st.text_area("Bangla raw", value=bangla_summary or "", height=150)

    st.markdown("### Flags & Source")
    st.write("Flags:", flags if flags else ["None"])
    st.json(source_meta)


def build_agents() -> dict[str, Agent]:
    return {
        "interpreter": Agent(
            role="Profile Interpreter Agent",
            goal="Convert free-form applicant text into a strict JSON applicant profile.",
            backstory="An intake specialist who transforms messy user text into structured profile fields.",
            llm=SELECTED_LLM,
            verbose=True,
            allow_delegation=False,
        ),
        "policy": Agent(
            role="Policy Guardian (Bangladesh Passport Policy Expert)",
            goal="Determine eligibility, required identification, validity constraints, and policy flags.",
            backstory="A senior consular policy analyst for Bangladesh e-passport rules.",
            llm=SELECTED_LLM,
            verbose=True,
            allow_delegation=False,
        ),
        "fee": Agent(
            role="Chancellor of the Exchequer (Financial Auditor)",
            goal="Calculate passport fee using policy context and fee rules, and add financial consistency flags.",
            backstory="A government fee auditor specialized in delivery categories and fee verification.",
            llm=SELECTED_LLM,
            verbose=True,
            allow_delegation=False,
        ),
        "docs": Agent(
            role="Document Architect (Documentation Officer)",
            goal="Generate a tailored document checklist and any checklist-related flags.",
            backstory="A consular documentation specialist ensuring complete application bundles.",
            llm=SELECTED_LLM,
            verbose=True,
            allow_delegation=False,
        ),
        "finalizer": Agent(
            role="Consular Final Response Architect",
            goal="Assemble the final standardized response in English table and Bangla summary.",
            backstory="A reporting officer who combines specialist outputs into presentation-ready guidance.",
            llm=SELECTED_LLM,
            verbose=True,
            allow_delegation=False,
        ),
    }


def run_agent_only_pipeline(user_text: str) -> dict[str, Any]:
    knowledge_context, source_metadata = get_knowledge_context()
    agents = build_agents()

    profile_schema_hint = {
        "age": "int",
        "profession": "string",
        "urgency": "one of ['regular','express','super_express']",
        "page_count": "48 or 64",
        "requested_validity_years": "5 or 10 or null",
        "has_nid": "bool",
        "location": "string",
        "needs_name_change": "bool",
    }

    interpret_task = Task(
        description=(
            "Read applicant text and return ONLY valid JSON profile with all required keys. "
            "Do not add any explanation. Use null when unknown.\n\n"
            f"Required schema: {json.dumps(profile_schema_hint, ensure_ascii=False)}\n\n"
            f"Applicant text:\n{user_text}"
        ),
        expected_output="Strict JSON object only.",
        agent=agents["interpreter"],
    )

    policy_task = Task(
        description=(
            "Using interpreter output profile JSON and Bangladesh policy context, produce policy decision JSON with keys:\n"
            "allowed_validity_years (array), required_id (string), recommended_validity (int), flags (array of strings).\n"
            "Must flag under-18 10-year requests and under-18 64-page requests."
        ),
        expected_output="Strict JSON object only.",
        context=[interpret_task],
        agent=agents["policy"],
    )

    fee_task = Task(
        description=(
            "Using interpreter profile + policy JSON + knowledge context below, compute fee JSON with keys:\n"
            "validity_years (int), delivery_type (string), total_fee_bdt (int), vat_note (string), flags (array).\n"
            "If requested validity conflicts with policy, set to recommended validity and add a flag.\n\n"
            f"Knowledge Context:\n{knowledge_context}"
        ),
        expected_output="Strict JSON object only.",
        context=[interpret_task, policy_task],
        agent=agents["fee"],
    )

    docs_task = Task(
        description=(
            "Using interpreter profile + policy JSON + knowledge context, return JSON with keys:\n"
            "checklist (array of strings), notes (string), flags (array).\n"
            "Checklist must be concise and deduplicated.\n\n"
            f"Knowledge Context:\n{knowledge_context}"
        ),
        expected_output="Strict JSON object only.",
        context=[interpret_task, policy_task],
        agent=agents["docs"],
    )

    final_task = Task(
        description=(
            "Using outputs from interpreter, policy, fee, and docs tasks, return ONE strict JSON object with keys:\n"
            "english_markdown_table (string), bangla_markdown_table (string), bangla_summary (string), flags (array), source_metadata (object).\n"
            "The english_markdown_table must include rows for: Applicant Age, Profession, Validity, Delivery Type, Passport Pages, Total Fee, Required Identification, Documents Needed, Flags, Data Source.\n"
            "The bangla_markdown_table must contain the same rows fully in Bangla (labels and values where possible).\n"
            f"Use this source_metadata exactly: {json.dumps(source_metadata, ensure_ascii=False)}"
        ),
        expected_output="Strict JSON object only.",
        context=[interpret_task, policy_task, fee_task, docs_task],
        agent=agents["finalizer"],
    )

    crew = Crew(
        agents=[
            agents["interpreter"],
            agents["policy"],
            agents["fee"],
            agents["docs"],
            agents["finalizer"],
        ],
        tasks=[interpret_task, policy_task, fee_task, docs_task, final_task],
        process=Process.sequential,
        verbose=True,
    )

    kickoff_result = str(crew.kickoff())

    interpret_raw = get_task_raw_output(interpret_task)
    policy_raw = get_task_raw_output(policy_task)
    fee_raw = get_task_raw_output(fee_task)
    docs_raw = get_task_raw_output(docs_task)
    final_raw = get_task_raw_output(final_task)

    parsed_interpret = extract_json_from_text(interpret_raw)
    parsed_policy = extract_json_from_text(policy_raw)
    parsed_fee = extract_json_from_text(fee_raw)
    parsed_docs = extract_json_from_text(docs_raw)
    parsed_final = extract_json_from_text(final_raw) or extract_json_from_text(kickoff_result)

    return {
        "source_metadata": source_metadata,
        "kickoff_result": kickoff_result,
        "raw": {
            "interpreter": interpret_raw,
            "policy": policy_raw,
            "fee": fee_raw,
            "docs": docs_raw,
            "final": final_raw,
        },
        "parsed": {
            "interpreter": parsed_interpret,
            "policy": parsed_policy,
            "fee": parsed_fee,
            "docs": parsed_docs,
            "final": parsed_final,
        },
    }


def main() -> None:
    st.set_page_config(page_title="BD Passport AI Agent (Agent-Only)", layout="wide")
    st.title("Bangladesh Passport Virtual Consular Officer — Agent-Only")
    st.caption("All business outputs (policy, fee, checklist, final report) are produced by CrewAI agents.")

    with st.sidebar:
        st.subheader("Runtime")
        st.write(f"LLM Provider: {LLM_PROVIDER}")
        st.write(f"Model: {SELECTED_LLM.model}")

    default_text = (
        "I am 40, government staff, need a 48 page passport with regular delivery for 10 years. "
        "I have my NID."
    )

    user_text = st.text_area("Applicant text", value=default_text, height=180)

    if st.button("Analyze with Agents", type="primary"):
        if not user_text.strip():
            st.warning("Please paste some text first.")
            return

        with st.spinner("Running CrewAI multi-agent pipeline..."):
            try:
                result = run_agent_only_pipeline(user_text)
            except Exception as exc:
                st.error(f"Agent pipeline failed: {exc}")
                return

        st.subheader("Parsed Intermediate Agent Outputs")
        parsed = result["parsed"]
        st.write("Interpreter")
        st.json(parsed["interpreter"] if parsed["interpreter"] else {"raw": result["raw"]["interpreter"]})
        st.write("Policy")
        st.json(parsed["policy"] if parsed["policy"] else {"raw": result["raw"]["policy"]})
        st.write("Fee")
        st.json(parsed["fee"] if parsed["fee"] else {"raw": result["raw"]["fee"]})
        st.write("Checklist")
        st.json(parsed["docs"] if parsed["docs"] else {"raw": result["raw"]["docs"]})

        st.subheader("Final Output (Agent-Generated)")
        final_data = parsed["final"]
        if final_data and isinstance(final_data, dict):
            render_vertical_output(final_data, result["source_metadata"])

            with st.expander("Raw Final Agent Output"):
                st.text_area("Final raw", value=result["raw"]["final"], height=220)
        else:
            st.warning("Could not parse final agent JSON. Showing raw final agent output.")
            st.text_area("Final raw", value=result["raw"]["final"] or result["kickoff_result"], height=300)
            st.json(result["source_metadata"])

        with st.expander("Full Crew Kickoff Result"):
            st.text_area("kickoff_result", value=result["kickoff_result"], height=260)


if __name__ == "__main__":
    main()
