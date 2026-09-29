"""G4 redaction. Runs before any AI call.

Removes: name, email, phone, URLs (profile links carry names), photo (never
extracted - we only send text), gender markers, age / DOB, marital status,
college and university names (and the years on education lines, an age proxy),
and full address. Keeps the city only.

Heuristic by nature, so it over-redacts rather than under-redacts, and
`leaks()` double-checks the output against the extracted identity.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

CITIES = [
    "Mumbai", "Navi Mumbai", "Thane", "Pune", "Bengaluru", "Bangalore", "Delhi", "New Delhi",
    "Gurugram", "Gurgaon", "Noida", "Hyderabad", "Chennai", "Kolkata", "Ahmedabad", "Surat",
    "Vadodara", "Jaipur", "Lucknow", "Indore", "Bhopal", "Nagpur", "Nashik", "Kochi", "Cochin",
    "Coimbatore", "Visakhapatnam", "Vizag", "Chandigarh", "Goa", "Mangaluru", "Mangalore",
    "Mysuru", "Kanpur", "Patna", "Bhubaneswar", "Guwahati", "Thiruvananthapuram", "Trivandrum",
    "Madurai", "Ludhiana", "Kandla", "Mundra", "Tuticorin", "Nhava Sheva", "Dubai", "Singapore",
    "London", "Rotterdam", "Hamburg",
]
_CITY_RE = re.compile(r"\b(" + "|".join(sorted(map(re.escape, CITIES), key=len, reverse=True)) + r")\b", re.I)

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Any web address or bare domain/handle (leetcode.com/<name>). Lowercase TLDs only so "B.Com" survives.
URL_RE = re.compile(r"(?:https?://|www\.)\S+|\b[\w-]{3,}\.(?:com|in|io|me|dev|org|net|co|ai|site|page)(?:/\S*)?(?!\w)")
# 10+ digits allowing spaces, dots, dashes, brackets and a leading +country code.
PHONE_RE = re.compile(r"(?<![\w/])\+?\(?\d[\d\s().-]{8,}\d(?![\w/])")
PIN_RE = re.compile(r"\b\d{3}\s?\d{3}\b")

PERSONAL_LABELS = re.compile(
    r"^\s*(?:[-*•]\s*)?(name|full name|candidate name|gender|sex|d\.?o\.?b\.?|date of birth|birth ?date|born|age|"
    r"marital status|married|nationality|religion|caste|father'?s name|mother'?s name|husband'?s name|"
    r"spouse|passport(?: no\.?)?|aadhaar(?: no\.?)?|pan (?:no\.?|number)|address|permanent address|current address|"
    r"residential address|location|"
    r"email|e-mail|phone|mobile|contact|tel|linkedin|photo)\s*[:\-–|]\s*(.*)$",
    re.I,
)
AGE_INLINE_RE = re.compile(r"\b(?:aged?\s*[:\-]?\s*\d{2}|\d{2}\s*(?:years|yrs)\s*old)\b", re.I)
MARITAL_RE = re.compile(r"\b(married|unmarried|single|divorced|widowed)\b(?=\s*(?:[,|;/\n]|$))", re.I)
HONORIFIC_RE = re.compile(r"\b(Mr|Mrs|Ms|Miss|Mx|Smt|Shri|Sri|Kumari)\.?\s+", re.I)
PRONOUNS = {
    "he": "they", "she": "they", "him": "them", "her": "their", "his": "their", "hers": "theirs",
    "himself": "themself", "herself": "themself",
}
PRONOUN_RE = re.compile(r"\b(" + "|".join(PRONOUNS) + r")\b", re.I)
GENDER_WORDS_RE = re.compile(r"\b(male|female|woman|man|transgender|non-binary)\b(?=\s*(?:[,|;/\n)]|$))", re.I)

_CAP = r"[A-Z][\w.&'’-]*"
_INST_KEYWORD = (r"(?:University|Universität|College|Institute|Institution|School|Academy|Polytechnic|"
                 r"Vidyalaya|Vidyapeeth|Vidyapith|Mahavidyalaya)")
INSTITUTION_RE = re.compile(
    rf"(?:(?:{_CAP}|of|and|&|for|the)\s+){{0,6}}{_INST_KEYWORD}"
    rf"(?:\s+(?:of|for)\s+(?:{_CAP}\s*(?:(?:and|&|of)\s+)?){{1,5}})?"
)
INSTITUTION_ABBR_RE = re.compile(
    # FMS is only an institute when followed by Delhi; at Kargo it usually means freight management system.
    r"\b(?:IIT|IIM|NIT|IIIT|IISc|IISER|BITS(?:\s+Pilani)?|ISB|XLRI|FMS(?=\s+Delhi)|SPJIMR|NMIMS|JBIMS|MDI|IIFT|TISS|"
    r"VJTI|COEP|DTU|NSIT|SRCC|LSR|VTU|ICFAI|Welingkar|Somaiya|Narsee\s+Monjee|Xavier'?s|SP\s+Jain|"
    r"Symbiosis|Amity|Manipal|VIT|SRM|Christ|Loyola|Stanford|Harvard|INSEAD|Wharton|MIT|LSE)\b"
    r"(?:[\s,-]+(?:Bombay|Delhi|Madras|Kanpur|Kharagpur|Roorkee|Guwahati|Ahmedabad|Bangalore|Calcutta|"
    r"Lucknow|Indore|Kozhikode|Calicut|Jamshedpur|Pilani|Goa|Hyderabad|Mumbai|Pune|Trichy|Surathkal|Warangal|Rourkela|Shillong|Ranchi|Raipur|Nagpur|Udaipur|Amritsar|Jammu|Sambalpur|Bodh Gaya|Visakhapatnam|Tiruchirappalli|Durgapur|Allahabad|Patna|Silchar)\b)?"
)
DEGREE_RE = re.compile(
    r"\b(B\.?\s?Tech|M\.?\s?Tech|B\.?E\b|M\.?E\b|B\.?Com|M\.?Com|B\.?Sc|M\.?Sc|B\.?A\b|M\.?A\b|MBA|PGDM|PGP|BBA|"
    r"BMS|Bachelor|Master|Ph\.?D|Diploma|HSC|SSC|CBSE|ICSE|Class\s+(?:X|XII|10|12))", re.I
)
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
EDU_KEEP_RE = re.compile(
    r"\[(?:INSTITUTION|YEAR)\]|class|cgpa|gpa|grade|distinction|division|honou?rs|hons|medal|major|minor|"
    r"speciali[sz]ation|part-time|full-time|%|^\W*$", re.I
)
WORK_LINE_RE = re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b|\bPresent\b|\bintern", re.I)
EDU_SEP_RE =re.compile(r"\s+[|·•▪]\s+")

NOT_NAME_WORDS = {
    "resume", "curriculum", "vitae", "cv", "profile", "summary", "product", "manager", "senior",
    "experience", "education", "skills", "contact", "objective", "professional", "career", "about",
}
FILENAME_STOPWORDS = NOT_NAME_WORDS | {
    "pm", "spm", "sr", "application", "applicant", "final", "updated", "new", "copy", "draft",
    "for", "kargo", "role", "job", "docx", "pdf", "the", "and", "of", "v", "mesa", "jd", "cand",
}


@dataclass
class Identity:
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    city: str | None = None
    name_tokens: list[str] = field(default_factory=list)


def _looks_like_name(line: str) -> bool:
    line = line.strip().strip("|").strip()
    words = line.split()
    if not 2 <= len(words) <= 5 or len(line) > 60:
        return False
    if any(ch.isdigit() for ch in line) or "@" in line:
        return False
    if any(w.lower().strip(".,") in NOT_NAME_WORDS for w in words):
        return False
    return all(re.fullmatch(r"[A-Z][A-Za-z'.\-]*\.?", w) or re.fullmatch(r"[A-Z]{2,}", w) for w in words)


def extract_identity(text: str, filename: str = "") -> Identity:
    ident = Identity()
    emails = EMAIL_RE.findall(text)
    ident.email = emails[0] if emails else None
    phones = [p for p in PHONE_RE.findall(text) if len(re.sub(r"\D", "", p)) >= 10]
    ident.phone = phones[0].strip() if phones else None

    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for l in lines[:40]:
        m = PERSONAL_LABELS.match(l)
        if m and m.group(1).lower() in ("name", "full name", "candidate name") and m.group(2).strip():
            ident.name = m.group(2).strip()
            break
    if not ident.name:
        for l in lines[:6]:
            first_segment = re.split(r"\s*[|•·,]\s*", l)[0]
            if _looks_like_name(first_segment):
                ident.name = first_segment.strip()
                break

    tokens = set()
    if ident.name:
        tokens |= {w.strip(".,") for w in ident.name.split() if len(w.strip(".,")) >= 3}
    # File names like cv_17_priya_sharma_pm.pdf also carry the name.
    stem = re.sub(r"\.[a-z0-9]+$", "", filename.lower())
    for w in re.split(r"[^a-z]+", stem):
        if len(w) >= 3 and w not in FILENAME_STOPWORDS and re.search(rf"\b{re.escape(w)}\b", text, re.I):
            tokens.add(w.capitalize())
    if not ident.name and tokens:
        ident.name = " ".join(sorted(tokens))
    ident.name_tokens = sorted(tokens, key=len, reverse=True)

    for l in lines[:40]:
        m = PERSONAL_LABELS.match(l)
        if m and ("address" in m.group(1).lower() or m.group(1).lower() == "location"):
            c = _CITY_RE.search(m.group(2))
            if c:
                ident.city = _canon_city(c.group(1))
                break
    if not ident.city:
        # The contact line (the one holding the email or phone) usually carries the city.
        candidates = [l for l in lines if (ident.email and ident.email in l) or (ident.phone and ident.phone in l)]
        based = re.search(r"(?:based in|currently in|residing in)\s+([^\n|.]+)", text, re.I)
        if based:
            candidates.append(based.group(1))
        candidates += lines[:6]
        for l in candidates:
            c = _CITY_RE.search(l)
            if c:
                ident.city = _canon_city(c.group(1))
                break
    return ident


def _canon_city(c: str) -> str:
    for city in CITIES:
        if city.lower() == c.lower():
            return city
    return c.title()


def redact(text: str, ident: Identity) -> tuple[str, list[str]]:
    """Return (redacted_text, list of what categories were removed)."""
    removed: list[str] = []

    def sub(pattern, repl, s, label, flags=0):
        new, n = (pattern.subn(repl, s) if isinstance(pattern, re.Pattern)
                  else re.subn(pattern, repl, s, flags=flags))
        if n:
            removed.append(f"{label} x{n}")
        return new

    out_lines = []
    for line in text.splitlines():
        m = PERSONAL_LABELS.match(line)
        if m:
            label = m.group(1).lower()
            if "address" in label or label == "location":
                city = _CITY_RE.search(m.group(2))
                out_lines.append(f"City: {_canon_city(city.group(1))}" if city else "[ADDRESS REMOVED]")
                removed.append("address")
            else:
                removed.append(label)
                out_lines.append(f"[{label.upper()} REMOVED]")
            continue
        # Bare address lines (street + PIN code): keep city only.
        if PIN_RE.search(line) and re.search(r"\b(road|rd|street|st|nagar|lane|marg|sector|flat|floor|"
                                              r"apartment|apt|society|chs|west|east|near|opp)\b", line, re.I):
            city = _CITY_RE.search(line)
            out_lines.append(f"City: {_canon_city(city.group(1))}" if city else "[ADDRESS REMOVED]")
            removed.append("address")
            continue
        out_lines.append(line)
    s = "\n".join(out_lines)

    s = sub(EMAIL_RE, "[EMAIL]", s, "email")
    s = sub(URL_RE, "[URL]", s, "url")
    s = PHONE_RE.sub(lambda m: "[PHONE]" if len(re.sub(r"\D", "", m.group())) >= 10 else m.group(), s)

    if ident.name:
        s = sub(re.compile(re.escape(ident.name), re.I), "[CANDIDATE]", s, "name")
    for tok in ident.name_tokens:
        s = sub(re.compile(rf"\b{re.escape(tok)}\b", re.I), "[CANDIDATE]", s, "name token")
    s = re.sub(r"\[CANDIDATE\](?:\s+\[CANDIDATE\])+", "[CANDIDATE]", s)

    s = sub(HONORIFIC_RE, "", s, "honorific")
    s = sub(AGE_INLINE_RE, "[AGE REMOVED]", s, "age")
    s = sub(MARITAL_RE, "[REMOVED]", s, "marital status")
    s = sub(GENDER_WORDS_RE, "[REMOVED]", s, "gender word")
    s = PRONOUN_RE.sub(lambda m: _match_case(PRONOUNS[m.group(1).lower()], m.group(1)), s)

    s = sub(INSTITUTION_ABBR_RE, "[INSTITUTION]", s, "institution")
    s = sub(INSTITUTION_RE, _institution_repl, s, "institution")
    # Years on education lines reveal age; work dates are kept for PM-years maths.
    # On degree lines, any segment that is not the degree itself or a grade is treated as
    # the institution, which catches colleges no keyword list knows about.
    edu_lines = []
    for line in s.splitlines():
        if "[INSTITUTION]" in line or DEGREE_RE.search(line):
            line = YEAR_RE.sub("[YEAR]", line)
            if DEGREE_RE.search(line) and EDU_SEP_RE.search(line) and not WORK_LINE_RE.search(line):
                segs = EDU_SEP_RE.split(line)
                kept = [seg if (DEGREE_RE.search(seg) or EDU_KEEP_RE.search(seg)) else "[INSTITUTION]"
                        for seg in segs]
                line = " · ".join(kept)
        edu_lines.append(line)
    s = "\n".join(edu_lines)
    return s, removed


def _institution_repl(m: re.Match) -> str:
    return "[INSTITUTION] " if m.group().endswith((" ", "\t")) else "[INSTITUTION]"


def _match_case(word: str, like: str) -> str:
    return word.capitalize() if like[:1].isupper() else word


def leaks(redacted: str, ident: Identity) -> list[str]:
    """Identity values still present after redaction (should always be empty)."""
    found = []
    for value in (ident.email, ident.phone, ident.name, *ident.name_tokens):
        if value and re.search(rf"(?<!\w){re.escape(value)}(?!\w)", redacted, re.I):
            found.append(value)
    if EMAIL_RE.search(redacted):
        found.append("email pattern")
    return found
