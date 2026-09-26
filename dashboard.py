import json
import os
import streamlit as st

REPORT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "report.json")

st.set_page_config(page_title="GitGrounded", layout="wide")

if not os.path.exists(REPORT_PATH):
    st.warning("No report.json found. Run gitgrounded.py first.")
    st.stop()

with open(REPORT_PATH) as f:
    report = json.load(f)

summary = report["summary"]
verdict = summary["verdict"]

color = {"PASS": "green", "WARN": "orange", "FAIL": "red"}[verdict]
st.markdown(f"# :{color}[{verdict}]")
st.caption(f"{report['old_ref']} -> {report['new_ref']}")

cols = st.columns(4)
cols[0].metric("Groundedness", summary["avg_groundedness"])
cols[1].metric("Format correctness", summary["avg_format_correctness"])
cols[2].metric("Rule following", summary["avg_rule_following"])
cols[3].metric("Meaning drift", summary["avg_meaning_drift"])

st.subheader(f"Cases: {summary['pass_count']} pass / {summary['warn_count']} warn / {summary['fail_count']} fail")

with st.expander("Generated test cases"):
    for c in report["generated_cases"]:
        st.write(f"**{c['id']}**: {c['input']}")

with st.expander("Diff"):
    st.code(report["diff"], language="diff")

st.subheader("Failing and warning cases")
for case in report["cases"]:
    if case["status"] == "PASS":
        continue
    with st.expander(f"[{case['status']}] {case['input']}"):
        st.write("Old answer")
        try:
            st.json(json.loads(case["old_raw"]))
        except (TypeError, json.JSONDecodeError):
            st.text(case["old_raw"])
        st.write("New answer")
        try:
            st.json(json.loads(case["new_raw"]))
        except (TypeError, json.JSONDecodeError):
            st.text(case["new_raw"])
        st.write("Judge scores")
        st.json(case["scores"])
        st.write("Code checks")
        st.json(case["code_checks"])

st.subheader("All cases")
table_rows = []
for case in report["cases"]:
    table_rows.append(
        {
            "status": case["status"],
            "input": case["input"],
            "groundedness": case["scores"].get("groundedness"),
            "meaning_drift": case["scores"].get("meaning_drift"),
        }
    )
st.dataframe(table_rows, use_container_width=True)
