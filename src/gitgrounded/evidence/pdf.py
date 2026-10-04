import io
from typing import Any


def available() -> bool:
    try:
        import fpdf  # noqa: F401
        import segno  # noqa: F401
    except ImportError:
        return False
    return True


def qr_payload(cert: dict[str, Any], cert_sha256: str, verify_url: str | None) -> str:
    parts = [f"ggcert:{cert['id']}", f"certified={'yes' if cert.get('certified') else 'no'}", f"sha256={cert_sha256}"]
    if verify_url:
        parts.append(f"verify={verify_url}")
    return ";".join(parts)


def _t(value: Any) -> str:
    s = "-" if value is None else str(value)
    return s.encode("latin-1", "replace").decode("latin-1")


def _num(v: Any, pct: bool = False) -> str:
    if v is None:
        return "-"
    return f"{v:.0%}" if pct else f"{v:.2f}"


def render_certificate_pdf(cert: dict[str, Any], cert_sha256: str, verify_url: str | None = None) -> bytes:
    import datetime as dt

    import segno
    from fpdf import FPDF

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    created = dt.datetime.strptime(cert["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.UTC)
    pdf.set_creation_date(created)
    pdf.set_title(f"GitGrounded certificate {cert['id']}")
    pdf.set_author("gitgrounded")
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()
    ok = bool(cert.get("certified"))
    pdf.set_font("Helvetica", "B", 22)
    pdf.cell(0, 12, "GitGrounded Benchmark Certificate", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(*((22, 128, 61) if ok else (185, 28, 28)))
    pdf.cell(0, 10, "CERTIFIED" if ok else "NOT CERTIFIED", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 10)
    suite = cert.get("suite") or {}
    traps = cert.get("traps") or {}
    judge = cert.get("judge") or {}
    rows = [
        ("Certificate id", cert["id"]),
        ("Project", cert.get("project")),
        ("Kind", cert.get("kind")),
        ("Issued (UTC)", cert["created_at"]),
        ("Issuer", (cert.get("issuer") or {}).get("name", "self-issued")),
        ("Tool version", cert.get("tool_version")),
        ("Suite", f"{suite.get('name')} v{suite.get('version')} ({suite.get('cases')} cases)"),
        ("Sealed suite hash", suite.get("sealed_hash")),
        ("Judge", f"{judge.get('provider')}:{judge.get('model')} t={judge.get('temperature')}"),
        ("Judge traps", f"{traps.get('correct')}/{traps.get('total')} (threshold {traps.get('threshold')})"),
        ("Offline mock", "yes" if cert.get("offline") else "no"),
        ("certificate.json sha256", cert_sha256),
    ]
    for k, v in rows:
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(48, 6, _t(k))
        pdf.set_font("Courier" if "sha" in k or "hash" in k else "Helvetica", "", 8 if "sha" in k or "hash" in k else 9)
        pdf.multi_cell(0, 6, _t(v), new_x="LMARGIN", new_y="NEXT")
    if cert.get("reasons"):
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 6, "Why not certified", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        for r in cert["reasons"]:
            pdf.multi_cell(0, 5, _t(f"- {r}"), new_x="LMARGIN", new_y="NEXT")
    board = cert.get("leaderboard") or []
    if board:
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 7, "Leaderboard", new_x="LMARGIN", new_y="NEXT")
        widths = (10, 70, 22, 34, 24, 30)
        head = ("#", "Candidate", "Score", "95% CI", "Pass", "Verdict")
        pdf.set_font("Helvetica", "B", 8)
        for w, h in zip(widths, head):
            pdf.cell(w, 6, h, border=1)
        pdf.ln()
        pdf.set_font("Helvetica", "", 8)
        for r in board:
            cells = (
                str(r.get("rank", "")),
                _t(r.get("candidate"))[:44],
                _num(r.get("score_mean")),
                f"{_num(r.get('ci_lower'))}-{_num(r.get('ci_upper'))}",
                _num(r.get("assertion_pass_rate"), pct=True),
                _t(r.get("verdict_vs_baseline")),
            )
            for w, c in zip(widths, cells):
                pdf.cell(w, 6, c, border=1)
            pdf.ln()
    payload = qr_payload(cert, cert_sha256, verify_url)
    buf = io.BytesIO()
    segno.make(payload, error="m").save(buf, kind="png", scale=4, border=2)
    buf.seek(0)
    y = max(pdf.get_y() + 6, 200)
    if y > 245:
        pdf.add_page()
        y = 20
    pdf.image(buf, x=pdf.l_margin, y=y, w=40, h=40)
    pdf.set_xy(pdf.l_margin + 46, y)
    pdf.set_font("Helvetica", "", 8)
    pdf.multi_cell(
        0,
        4.5,
        _t(
            "Scan to read the certificate id and the sha256 of certificate.json. "
            "The PDF is a convenience copy; the signed evidence is the .ggb bundle. "
            "Verify with: gitgrounded verify <certificate>.ggb"
            + (f" or at {verify_url}" if verify_url else "")
            + f"\n\n{payload}"
        ),
    )
    return bytes(pdf.output())
