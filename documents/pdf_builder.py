"""
Builds styled PDFs in Inter Miami CF colors with a two-column layout:
  - Black fixed sidebar (#231F20) with Miami Pink (#F7B5CD) accents + a heron mark
  - White main column; deeper pink (#C72C75) for accent text where pastel is faint
The sidebar is position:fixed so WeasyPrint repeats it full-bleed on every page
(a flex/grid row can't be fragmented across pages). Credentials (name, contact,
education, certifications) and the AI & Tooling statement render straight from
profile.json and are never AI-generated. Uses WeasyPrint for HTML → PDF.
"""

from pathlib import Path
import weasyprint

INK = "#231F20"        # Inter Miami Black
PINK = "#F7B5CD"       # Inter Miami Miami Pink (great on black, faint on white)
PINK_DEEP = "#C72C75"  # readable companion pink for accent text on white

RESUME_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Lato:wght@300;400;700&family=Raleway:wght@400;600;700&display=swap');

* { margin: 0; padding: 0; box-sizing: border-box; }

@page { size: letter; margin: 32pt 0; }

body { font-family: 'Lato', sans-serif; font-size: 9pt; color: #33312f; background: #fff; }
.page { width: 100%; }

/* ── SIDEBAR (fixed → repeats full-bleed on every page) ── */
.sidebar {
    position: fixed; top: -32pt; left: 0; width: 32%; height: 11in;
    background: #231F20; color: #e9e3e5; padding: 26pt 16pt 32pt 20pt;
}
.monogram {
    width: 50pt; height: 50pt; border-radius: 50%; border: 1.5pt solid #F7B5CD;
    display: flex; align-items: center; justify-content: center;
    font-family: 'Raleway', sans-serif; font-size: 16pt; font-weight: 700;
    color: #F7B5CD; letter-spacing: 1pt; margin: 0 auto 16pt;
}

.sidebar-section { margin-bottom: 9pt; }
.sidebar-section-title {
    font-family: 'Raleway', sans-serif; font-size: 6.5pt; font-weight: 700;
    letter-spacing: 2.5pt; text-transform: uppercase; color: #F7B5CD;
    border-bottom: 0.5pt solid #F7B5CD; padding-bottom: 3pt; margin-bottom: 8pt;
}
.contact-item { font-size: 7.5pt; margin-bottom: 4pt; color: #cdc6c8; word-break: break-all; }
.skill-category {
    font-size: 7pt; font-weight: 700; color: #F7B5CD; text-transform: uppercase;
    letter-spacing: 0.8pt; margin-top: 5pt; margin-bottom: 3pt;
}
.skill-tags { display: flex; flex-wrap: wrap; gap: 3pt; }
.skill-tag {
    background: rgba(247,181,205,0.16); border: 0.5pt solid rgba(247,181,205,0.45);
    border-radius: 3pt; padding: 1.5pt 5pt; font-size: 6.5pt; color: #ecdfe3;
}
.cert-item, .edu-item {
    font-size: 7.5pt; color: #cdc6c8; margin-bottom: 3pt;
    border-left: 2pt solid #F7B5CD; padding-left: 6pt;
}
.cert-source, .edu-detail { font-size: 6.5pt; color: #9a9296; margin-top: 1pt; }

/* ── MAIN COLUMN (flows across pages beside the fixed sidebar) ── */
.main { margin-left: 32%; padding: 0 24pt; }

.name {
    font-family: 'Raleway', sans-serif; font-size: 22pt; font-weight: 700;
    color: #231F20; letter-spacing: 0.5pt; line-height: 1;
}
.title-bar { display: flex; align-items: center; gap: 6pt; margin-top: 3pt; margin-bottom: 14pt; }
.title-dot { color: #C72C75; font-size: 9pt; }
.title-text {
    font-family: 'Raleway', sans-serif; font-size: 8pt; font-weight: 600;
    letter-spacing: 2pt; text-transform: uppercase; color: #C72C75;
}
.section-title {
    font-family: 'Raleway', sans-serif; font-size: 9pt; font-weight: 700; color: #231F20;
    letter-spacing: 1pt; text-transform: uppercase; border-bottom: 1pt solid #F7B5CD;
    padding-bottom: 3pt; margin-bottom: 10pt; margin-top: 14pt;
}
.profile-text, .ai-block { font-size: 8.5pt; line-height: 1.5; color: #444; margin-bottom: 4pt; }

.job { margin-bottom: 11pt; }
.job-header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 2pt; }
.job-title { font-weight: 700; font-size: 9pt; color: #231F20; }
.job-dates {
    font-size: 7pt; color: #231F20; background: #F7B5CD; border-radius: 3pt;
    padding: 1.5pt 6pt; white-space: nowrap;
}
.job-company { font-size: 7.5pt; color: #C72C75; font-weight: 700; margin-bottom: 4pt; }
.job-bullets { padding-left: 11pt; }
.job-bullets li { font-size: 8pt; line-height: 1.45; color: #444; margin-bottom: 2.5pt; }
.job-bullets li::marker { color: #C72C75; }

.project { margin-bottom: 6pt; }
.project-name { font-weight: 700; font-size: 8pt; color: #231F20; }
.project-name::before { content: "▸ "; color: #C72C75; }
.project-tech { font-size: 7pt; color: #8a8a8a; font-style: italic; }
.project-desc { font-size: 7.5pt; color: #555; margin-top: 1pt; }
"""

COVER_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Lato:wght@300;400;700&family=Raleway:wght@400;600;700&display=swap');

* { margin: 0; padding: 0; box-sizing: border-box; }

body { font-family: 'Lato', sans-serif; font-size: 10pt; color: #2c2c2c; background: white; padding: 50pt 60pt; }

.header { border-bottom: 2pt solid #231F20; padding-bottom: 12pt; margin-bottom: 24pt; }
.sender-name { font-family: 'Raleway', sans-serif; font-size: 20pt; font-weight: 700; color: #231F20; }
.sender-title { font-size: 8pt; font-weight: 600; letter-spacing: 2pt; text-transform: uppercase; color: #C72C75; margin-top: 2pt; }
.contact-line { font-size: 8pt; color: #666; margin-top: 6pt; }
.date-block { margin-bottom: 20pt; font-size: 9pt; color: #444; }
.salutation { font-size: 10pt; margin-bottom: 14pt; font-weight: 600; }
.body-para { font-size: 10pt; line-height: 1.65; color: #333; margin-bottom: 14pt; }
.closing { margin-top: 24pt; }
.closing-word { font-size: 10pt; color: #333; margin-bottom: 30pt; }
.sig-name { font-family: 'Raleway', sans-serif; font-size: 14pt; font-weight: 700; color: #231F20; }
.sig-contact { font-size: 8pt; color: #888; margin-top: 3pt; }
.accent-bar { width: 40pt; height: 3pt; background: #F7B5CD; margin-top: 8pt; }
"""

ROLE_LABELS = {
    "fullstack": "FULL STACK DEVELOPER & SYSTEMS ADMINISTRATOR",
    "frontend": "FRONTEND DEVELOPER",
    "sysadmin": "SYSTEMS ADMINISTRATOR",
    "it_manager": "IT MANAGER & SYSTEMS ADMINISTRATOR",
}


def build_resume_pdf(resume_data: dict, output_path: str, job: dict) -> str:
    html = _render_resume_html(resume_data, job)
    doc = weasyprint.HTML(string=html).write_pdf(stylesheets=[weasyprint.CSS(string=RESUME_CSS)])
    Path(output_path).write_bytes(doc)
    return output_path


def build_cover_letter_pdf(cover_text: str, output_path: str, job: dict) -> str:
    html = _render_cover_html(cover_text, job)
    doc = weasyprint.HTML(string=html).write_pdf(stylesheets=[weasyprint.CSS(string=COVER_CSS)])
    Path(output_path).write_bytes(doc)
    return output_path


def _render_resume_html(r: dict, job: dict) -> str:
    from profile import load_profile
    profile = load_profile()
    contact = profile.get("contact", {})

    skills = r.get("skills", {})
    experience = r.get("experience", [])
    projects = r.get("projects", [])
    summary = r.get("summary", "")
    education = profile.get("education", [])
    certs = profile.get("certifications", [])
    ai_tooling = profile.get("ai_tooling", "")

    # Skills capped so the fixed sidebar stays tidy.
    MAX_CATS, MAX_PER = 5, 7
    sidebar_skills = ""
    for cat, items in list(skills.items())[:MAX_CATS]:
        tags = "".join(f'<span class="skill-tag">{i}</span>' for i in items[:MAX_PER])
        sidebar_skills += f'<div class="skill-category">{cat}</div><div class="skill-tags">{tags}</div>'

    def _cert_line(c):
        if isinstance(c, dict):
            meta = " · ".join(x for x in (c.get("issuer", ""), c.get("date", "")) if x)
            return (f'<div class="cert-item"><div>{c.get("name","")}</div>'
                    + (f'<div class="cert-source">{meta}</div>' if meta else "") + "</div>")
        return f'<div class="cert-item"><div>{c}</div></div>'

    featured = [c for c in certs if not isinstance(c, dict) or c.get("featured", True)]
    cert_html = "".join(_cert_line(c) for c in featured)

    edu_html = "".join(
        f'<div class="edu-item"><div style="font-weight:700">{e.get("degree","")}</div>'
        f'<div class="edu-detail">{e.get("school","")}'
        + (f' · {e["year"]}' if e.get("year") else "")
        + "</div></div>"
        for e in education
    )

    # Contact icons limited to glyphs present in the PDF fonts (DejaVu/Liberation):
    # ✉ U+2709, ☎ U+260E, ⌂ U+2302 (house = location). ⌖ was missing → boxed.
    contact_html = "".join(
        f'<div class="contact-item">{icon}{val}</div>'
        for icon, val in (
            ("✉ ", contact.get("email")), ("☎ ", contact.get("phone")),
            ("⌂ ", profile.get("location")), ("", contact.get("website")),
            ("", contact.get("linkedin")), ("", contact.get("github")),
        )
        if val
    )

    exp_html = ""
    for ex in experience:
        bullets = "".join(f"<li>{b}</li>" for b in ex.get("bullets", []))
        exp_html += (
            '<div class="job"><div class="job-header">'
            f'<span class="job-title">{ex.get("title","")}</span>'
            f'<span class="job-dates">{ex.get("dates","")}</span></div>'
            f'<div class="job-company">{ex.get("company","")}</div>'
            f'<ul class="job-bullets">{bullets}</ul></div>'
        )

    proj_html = ""
    for p in projects:
        proj_html += (
            '<div class="project"><div><span class="project-name">' + p.get("name", "") + "</span>"
            f'<span class="project-tech"> — {p.get("tech","")}</span></div>'
            f'<div class="project-desc">{p.get("description","")}</div></div>'
        )

    name = profile.get("name", "")
    initials = "".join(w[0] for w in name.split()[:2]).upper() or "MC"
    role = ROLE_LABELS.get(job.get("role_type", ""), profile.get("title", "").upper())

    certs_section = (f'<div class="sidebar-section"><div class="sidebar-section-title">Certifications</div>{cert_html}</div>'
                     if featured else "")
    edu_section = (f'<div class="sidebar-section"><div class="sidebar-section-title">Education</div>{edu_html}</div>'
                   if education else "")
    ai_section = (f'<div class="section-title">AI &amp; Tooling</div><div class="ai-block">{ai_tooling}</div>'
                  if ai_tooling else "")

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><title>{name} — Resume</title></head>
<body>
<div class="page">
  <div class="sidebar">
    <div class="monogram">{initials}</div>
    <div class="sidebar-section"><div class="sidebar-section-title">Contact</div>{contact_html}</div>
    <div class="sidebar-section"><div class="sidebar-section-title">Skills</div>{sidebar_skills}</div>
    {edu_section}
    {certs_section}
  </div>
  <div class="main">
    <div class="name">{name}</div>
    <div class="title-bar"><span class="title-dot">●</span><span class="title-text">{role}</span></div>
    <div class="section-title">Profile</div>
    <p class="profile-text">{summary}</p>
    {ai_section}
    <div class="section-title">Experience</div>
    {exp_html}
    <div class="section-title">Selected Projects</div>
    {proj_html}
  </div>
</div>
</body></html>"""


def _render_cover_html(text: str, job: dict) -> str:
    from profile import load_profile
    profile = load_profile()
    contact = profile.get("contact", {})

    paragraphs = [p.strip() for p in text.strip().split("\n\n") if p.strip()]
    body_paras = []
    salutation = "Dear Hiring Manager,"
    closing = "Sincerely,"
    for p in paragraphs:
        low = p.lower()
        if low.startswith("dear"):
            salutation = p
        elif any(low.startswith(w) for w in ["sincerely", "best regards", "thank you", "warm regards"]):
            closing = p
        else:
            body_paras.append(p)

    para_html = "".join(f'<p class="body-para">{p}</p>' for p in body_paras)

    from datetime import datetime
    date_str = datetime.now().strftime("%B %d, %Y")

    name = profile.get("name", "")
    title = profile.get("title", "")
    contact_line = " · ".join(x for x in (
        contact.get("email"), contact.get("phone"), contact.get("website"), profile.get("location")
    ) if x)
    sig_contact = " · ".join(x for x in (contact.get("email"), contact.get("phone")) if x)

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><title>Cover Letter — {name}</title></head>
<body>
  <div class="header">
    <div class="sender-name">{name}</div>
    <div class="sender-title">{title}</div>
    <div class="contact-line">{contact_line}</div>
  </div>
  <div class="date-block">{date_str}</div>
  <div style="margin-bottom:8pt; font-size:9pt; color:#444;">
    <strong>{job.get("company", "Hiring Team")}</strong><br>
    Re: {job.get("title", "Open Position")}
  </div>
  <div class="salutation">{salutation}</div>
  {para_html}
  <div class="closing">
    <div class="closing-word">{closing}</div>
    <div class="sig-name">{name}</div>
    <div class="sig-contact">{sig_contact}</div>
    <div class="accent-bar"></div>
  </div>
</body></html>"""
