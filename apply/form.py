"""
Read and fill application forms with Playwright.

Fields are discovered from the live DOM (labels, aria attributes, radio/checkbox
groups, native selects, ARIA comboboxes like react-select) rather than from
per-ATS selectors, so Greenhouse, Lever, Ashby and plain HTML forms all go
through the same path. Each field gets a stable `key` (label + name) so answers
saved during review line up with the form again on the submit run.
"""
import re

# Tags every control with data-jb="<n>" and returns a description of it.
EXTRACT_JS = r"""
() => {
  const txt = el => (el ? (el.innerText || el.textContent || "") : "").replace(/\s+/g, " ").trim();
  const visible = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none"; };
  const labelOf = el => {
    if (el.labels && el.labels.length) return txt(el.labels[0]);
    const lb = el.getAttribute("aria-labelledby");
    if (lb) { const t = lb.split(/\s+/).map(id => txt(document.getElementById(id))).join(" ").trim(); if (t) return t; }
    if (el.getAttribute("aria-label")) return el.getAttribute("aria-label");
    const wrap = el.closest("label"); if (wrap) return txt(wrap);
    // nearest preceding label-ish text inside the same field container
    let c = el.parentElement;
    for (let i = 0; c && i < 4; i++, c = c.parentElement) {
      const l = c.querySelector("label, legend, [class*=label], [class*=Label]");
      if (l && !l.contains(el) && txt(l)) return txt(l);
    }
    return el.placeholder || el.name || el.id || "";
  };
  const groupLabel = el => {
    const fs = el.closest("fieldset"); if (fs) { const lg = fs.querySelector("legend"); if (lg) return txt(lg); }
    const rg = el.closest("[role=radiogroup],[role=group]");
    if (rg) { const lb = rg.getAttribute("aria-labelledby"); if (lb) return txt(document.getElementById(lb));
              if (rg.getAttribute("aria-label")) return rg.getAttribute("aria-label"); }
    let c = el.parentElement;
    for (let i = 0; c && i < 5; i++, c = c.parentElement) {
      const l = [...c.querySelectorAll("label, legend, [class*=label], [class*=question], h3, h4, p")]
                 .find(x => !x.contains(el) && !x.querySelector("input") && txt(x));
      if (l) return txt(l);
    }
    return el.name || "";
  };
  // multi-step forms reuse the DOM: drop tags from a previous extraction
  document.querySelectorAll("[data-jb]").forEach(e => e.removeAttribute("data-jb"));
  const out = []; const groups = {}; let n = 0;
  const tag = el => { const id = String(n++); el.setAttribute("data-jb", id); return id; };
  const ctrls = document.querySelectorAll("input, textarea, select, [role=combobox]");
  for (const el of ctrls) {
    const type = (el.getAttribute("type") || el.tagName).toLowerCase();
    if (["hidden", "submit", "button", "image", "reset", "search"].includes(type)) continue;
    if (el.closest("[aria-hidden=true]") && type !== "file") continue;
    if (type !== "file" && !visible(el)) continue;
    const required = el.required || el.getAttribute("aria-required") === "true" ||
                     /\(required\)/i.test(labelOf(el)) || /\(required\)/i.test(groupLabel(el)) ||
                     /\*\s*$/.test(labelOf(el)) || /\*\s*$/.test(groupLabel(el));
    if (type === "radio" || type === "checkbox") {
      const name = el.name || groupLabel(el);
      const g = groups[name] || (groups[name] = { kind: type, name, label: groupLabel(el),
                 required: false, options: [], ids: [] });
      g.options.push(labelOf(el)); g.ids.push(tag(el)); g.required = g.required || required;
      continue;
    }
    const isCombo = el.getAttribute("role") === "combobox" && el.tagName !== "SELECT";
    out.push({
      id: tag(el), kind: el.tagName === "SELECT" ? "select" : isCombo ? "combobox"
            : el.tagName === "TEXTAREA" ? "textarea" : type === "file" ? "file" : "text",
      input_type: type, name: el.name || el.id || "", label: labelOf(el), required,
      options: el.tagName === "SELECT" ? [...el.options].map(o => o.text.trim()).filter(t => t && !/^select/i.test(t)) : [],
      accept: el.getAttribute("accept") || "",
    });
  }
  for (const g of Object.values(groups)) {
    out.push({ id: g.ids.join(","), kind: g.kind === "radio" || g.options.length > 1 ? g.kind : "checkbox_single",
               name: g.name, label: g.label || g.options[0], required: g.required, options: g.options });
  }
  return out;
}
"""


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def field_key(f: dict) -> str:
    return f"{_norm(f['label'])[:120]}|{f['name']}"


def extract_fields(page, known_options: dict | None = None) -> list[dict]:
    """`known_options` maps field name → option labels when the ATS API already told us."""
    known_options = known_options or {}
    fields = page.evaluate(EXTRACT_JS)
    for f in fields:
        f["label"] = re.sub(r"\s*(\*|\((required|optional)\))\s*", " ", f["label"], flags=re.I).strip()
        f["key"] = field_key(f)
        if f["name"] in known_options and f["kind"] in ("combobox", "select"):
            f["options"] = known_options[f["name"]]
        elif f["kind"] == "combobox" and not f["options"]:
            f["options"] = _combobox_options(page, f["id"])
    return fields


def _options_for(page, el):
    """Option locator for the listbox this combobox controls (not some other open menu)."""
    ctl = el.get_attribute("aria-controls") or el.get_attribute("aria-owns")
    if ctl:
        return page.locator(f'[id="{ctl}"] [role=option]')
    return page.locator("[role=listbox]:visible [role=option]")


def _close(el):
    try:
        el.press("Escape")
        el.evaluate("e => e.blur()")
    except Exception:
        pass


def _combobox_options(page, jb_id: str) -> list[str]:
    """Open a custom dropdown just long enough to read its option texts."""
    el = page.locator(f'[data-jb="{jb_id}"]')
    try:
        el.click(timeout=3000)
        page.wait_for_timeout(400)
        opts = _options_for(page, el).all_inner_texts()
        # Async/autocomplete comboboxes (e.g. location) show nothing until you type.
        return [o.strip() for o in opts if o.strip()][:250]
    except Exception:
        return []
    finally:
        _close(el)


US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
_STATE_ALT = {**{k.lower(): v for k, v in US_STATES.items()},
              **{v.lower(): k for k, v in US_STATES.items()}}


def _best_option(options: list[str], value: str) -> str | None:
    hit = _match_option(options, value)
    alt = _STATE_ALT.get(str(value).strip().lower())   # "Florida" ↔ "FL"
    return hit or (alt and _match_option(options, alt))


def _match_option(options: list[str], value: str) -> str | None:
    v = _norm(value)
    for o in options:
        if _norm(o) == v:
            return o
    for o in options:
        if v and (v in _norm(o) or _norm(o) in v):
            return o
    return None


def fill_field(page, f: dict, value, files: dict) -> str | None:
    """Fill one field. Returns an error string, or None on success."""
    if value in (None, "", []):
        return None
    kind = f["kind"]
    try:
        if kind == "file":
            path = files.get(value)
            if not path:
                return f"no file for '{value}'"
            page.locator(f'[data-jb="{f["id"]}"]').set_input_files(path)
        elif kind in ("text", "textarea"):
            page.locator(f'[data-jb="{f["id"]}"]').fill(str(value))
        elif kind == "select":
            opt = _best_option(f["options"], str(value))
            if not opt:
                return f"'{value}' is not an option"
            page.locator(f'[data-jb="{f["id"]}"]').select_option(label=opt)
        elif kind == "combobox":
            el = page.locator(f'[data-jb="{f["id"]}"]')
            el.click()
            if el.evaluate("e => e.tagName === 'INPUT'"):
                el.fill(str(value))
            else:
                page.keyboard.type(str(value))
            page.wait_for_timeout(900)
            opts = _options_for(page, el)
            texts = [t.strip() for t in opts.all_inner_texts()]
            opt = _best_option(texts, str(value))
            if not opt:
                _close(el)
                if not texts:   # free-text box with autocomplete that had nothing to offer
                    return None
                return f"no dropdown option matching '{value}'"
            opts.nth(texts.index(opt)).click()
        elif kind in ("radio", "checkbox"):
            wanted = value if isinstance(value, list) else [value]
            ids = f["id"].split(",")
            for w in wanted:
                opt = _best_option(f["options"], str(w))
                if not opt:
                    return f"'{w}' is not an option"
                page.locator(f'[data-jb="{ids[f["options"].index(opt)]}"]').check(force=True)
        elif kind == "checkbox_single":
            if str(value).lower() in ("yes", "true", "1", "checked"):
                page.locator(f'[data-jb="{f["id"]}"]').check(force=True)
    except Exception as e:
        return f"{type(e).__name__}: {str(e).splitlines()[0][:160]}"
    return None


NEXT_RE = re.compile(r"^\s*(next( step| page)?|continue|save (and|&) continue)\b", re.I)
SUBMIT_RE = re.compile(r"submit|send application|^\s*apply\b|finish", re.I)
COOKIE_BUTTONS = ["#onetrust-reject-all-handler", "button:has-text('Reject All')",
                  "#onetrust-accept-btn-handler", "button:has-text('Accept All Cookies')",
                  "button:has-text('Accept all')"]

SUCCESS_RE = re.compile(r"thank(s| you)( so much)? for (applying|your (application|interest))|"
                        r"application (has been |was )?(received|submitted)|"
                        r"we('ve| have) received your application", re.I)
CAPTCHA_RE = re.compile(r"verify (that )?you are (a )?human|are you a robot|captcha", re.I)


def _buttons(page):
    loc = page.locator("button, input[type=submit], input[type=button], a[role=button]")
    for i in range(loc.count()):
        b = loc.nth(i)
        try:
            if b.is_visible():
                text = (b.inner_text() or b.get_attribute("value") or "").strip()
                yield b, text
        except Exception:
            continue


def find_next(page):
    """A 'Next step' style button: advances a multi-page form without submitting."""
    return next((b for b, t in _buttons(page) if NEXT_RE.search(t)), None)


def find_submit(page):
    for b, t in _buttons(page):
        if SUBMIT_RE.search(t) and not NEXT_RE.search(t):
            return b
    return None


def dismiss_cookies(page):
    """Cookie banners cover the bottom of the form (and its buttons)."""
    for sel in COOKIE_BUTTONS:
        loc = page.locator(sel)
        try:
            if loc.count() and loc.first.is_visible():
                loc.first.click(timeout=2000)
                page.wait_for_timeout(400)
                return
        except Exception:
            pass


def visible_errors(page) -> list[str]:
    loc = page.locator("[role=alert], .field-validation-error, .k-invalid-msg, "
                       "[class*=error]:not(input):not(form)")
    out = []
    for i in range(min(loc.count(), 30)):
        try:
            if loc.nth(i).is_visible():
                t = loc.nth(i).inner_text().strip()
                if t and t not in out:
                    out.append(t[:120])
        except Exception:
            pass
    return out


def open_form(page, url: str):
    """Navigate and, if needed, click through an 'Apply' button to reveal the form."""
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(2500)
    if page.locator("input[type=email], input[name*=email i]").count():
        return
    for text in ("Apply for this job", "Apply now", "Apply Now", "Apply"):
        btn = page.get_by_role("button", name=text).or_(page.get_by_role("link", name=text))
        if btn.count():
            try:
                btn.first.click(timeout=4000)
                page.wait_for_timeout(2500)
                if page.locator("input[type=email], input[name*=email i]").count():
                    return
            except Exception:
                pass
