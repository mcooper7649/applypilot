"""Turn an uploaded resume (PDF / DOCX / TXT) into profile suggestions."""
import base64
import io
import re
import zipfile
from xml.etree import ElementTree

from llm import structured, PROFILE_FACTS_SCHEMA, facts_to_suggestions

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

PROMPT = """This is the candidate's most recent resume. Extract the facts it states.

Rules:
- Use ONLY what is written in the resume. Never invent or infer degrees, employers,
  dates, metrics or certifications.
- Keep experience bullets close to the original wording.
- Use "" or [] for anything the resume doesn't contain.
- Group skills into a handful of sensible categories."""


def _docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        root = ElementTree.fromstring(z.read("word/document.xml"))
    paras = []
    for p in root.iter(f"{_W}p"):
        paras.append("".join(t.text or "" for t in p.iter(f"{_W}t")))
    return "\n".join(x for x in paras if x.strip())


def parse_resume(filename: str, data: bytes) -> dict:
    name = filename.lower()
    if name.endswith(".pdf"):
        doc = {"type": "document", "source": {
            "type": "base64", "media_type": "application/pdf",
            "data": base64.standard_b64encode(data).decode()}}
        facts = structured(PROMPT, PROFILE_FACTS_SCHEMA, document=doc)
    elif name.endswith(".docx"):
        facts = structured(f"{PROMPT}\n\nRESUME:\n{_docx_text(data)}", PROFILE_FACTS_SCHEMA)
    elif name.endswith((".txt", ".md")):
        facts = structured(f"{PROMPT}\n\nRESUME:\n{data.decode('utf-8', 'replace')}",
                           PROFILE_FACTS_SCHEMA)
    else:
        raise ValueError("Upload a PDF, DOCX or TXT resume")
    return facts_to_suggestions(facts)


def safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[-80:] or "resume"
