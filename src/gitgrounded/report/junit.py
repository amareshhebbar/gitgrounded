from xml.etree import ElementTree as ET

from gitgrounded.report.model import RunResult


def render_junit(result: RunResult) -> str:
    suite = ET.Element(
        "testsuite",
        name=f"gitgrounded.{result.suite}",
        tests=str(len(result.cases)),
        failures=str(result.counts.get("fail_cases", 0) + result.counts.get("broken_cases", 0)),
        skipped=str(result.counts.get("unstable_cases", 0)),
        timestamp=result.created_at,
    )
    for r in result.cases:
        cid = r["case"]["id"]
        total_ms = sum(t["transcript"].get("latency_ms", 0) for t in r["head"]["trials"])
        tc = ET.SubElement(
            suite,
            "testcase",
            classname=f"{result.suite}.{(r['case'].get('behaviors') or ['cases'])[0]}",
            name=cid,
            time=f"{total_ms / 1000:.3f}",
        )
        status = r["status"]
        fails = [a for t in r["head"]["trials"] for a in t["assertions"] if not a["passed"]]
        message = "; ".join(r["reasons"] + [f"{a['label']}: {a['message']}" for a in fails])[:2000]
        if status in ("FAIL", "BROKEN"):
            f = ET.SubElement(tc, "failure", message=message or status, type=status)
            out = r["head"]["trials"][0]["transcript"].get("raw_output", "") if r["head"]["trials"] else ""
            f.text = (out or "")[:4000]
        elif status == "UNSTABLE":
            ET.SubElement(tc, "skipped", message=message or "unstable across trials")
        elif status == "WARN":
            so = ET.SubElement(tc, "system-out")
            so.text = f"WARN: {message}"
    root = ET.Element("testsuites", name="gitgrounded", tests=str(len(result.cases)))
    root.append(suite)
    return ET.tostring(root, encoding="unicode", xml_declaration=True)
