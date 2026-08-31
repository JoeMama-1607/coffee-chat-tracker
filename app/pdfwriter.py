"""A very small PDF writer, and the prep-notes document built with it.

The app has no third-party dependencies and this keeps that promise: PDFs are
assembled by hand using the base-14 Helvetica faces every PDF reader already
has, so there is nothing to install and nothing to keep up to date.

The document is composed from the prep data, not from the page, so screen-only
controls (the Copy buttons) cannot end up in the file.
"""

import datetime as dt

# ---------------------------------------------------------------- metrics
# Character widths in 1/1000 em for codes 32..126, from the Helvetica AFM
# tables. Wrapping is only as good as these, so they are the real values.
_HELV = [
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
    1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
    333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
    556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584,
]
_HELV_BOLD = [
    278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611,
    975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556,
    333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611,
    611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584,
]
# The handful of upper-range cp1252 codes this document actually uses.
_EXTRA = {
    0x85: (1000, 1000), 0x91: (222, 278), 0x92: (222, 278), 0x93: (333, 500),
    0x94: (333, 500), 0x95: (350, 350), 0x96: (556, 556), 0x97: (1000, 1000),
    0xA0: (278, 278), 0xB7: (278, 278),
}

# Glyphs with no place in the font's encoding, spelled out instead of dropped.
_SUBSTITUTIONS = {
    "→": "->", "←": "<-", "✓": "", "✔": "",
    "☑": "", "▸": ">", "•": "•", "≤": "<=",
    "≥": ">=", "‘": "‘", "’": "’",
    "“": "“", "”": "”", "…": "…",
    "–": "–", "—": "—", " ": " ",
}

REGULAR, BOLD, ITALIC = "F1", "F2", "F3"


def _sanitise(text):
    out = []
    for ch in str(text or ""):
        out.append(_SUBSTITUTIONS.get(ch, ch))
    # Anything still outside the font's encoding is dropped rather than left to
    # become a stray box in the reader.
    cleaned = "".join(out)
    return cleaned.encode("cp1252", "ignore").decode("cp1252")


def _encode(text):
    return _sanitise(text).encode("cp1252", "replace")


def text_width(text, font, size):
    table = _HELV_BOLD if font == BOLD else _HELV
    total = 0
    for byte in _encode(text):
        if 32 <= byte <= 126:
            total += table[byte - 32]
        elif byte in _EXTRA:
            total += _EXTRA[byte][1 if font == BOLD else 0]
        else:
            total += 556
    return total * size / 1000.0


def wrap(text, font, size, width):
    """Greedy word wrap. Long unbreakable tokens are hard-split."""
    lines = []
    for paragraph in _sanitise(text).split("\n"):
        words = paragraph.split(" ")
        current = ""
        for word in words:
            candidate = (current + " " + word).strip()
            if not current or text_width(candidate, font, size) <= width:
                current = candidate
                continue
            if text_width(word, font, size) > width:
                lines.append(current)
                chunk = ""
                for ch in word:
                    if text_width(chunk + ch, font, size) > width:
                        lines.append(chunk)
                        chunk = ch
                    else:
                        chunk += ch
                current = chunk
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines or [""]


def _pdf_string(text):
    raw = _encode(text)
    out = bytearray(b"(")
    for byte in raw:
        if byte in (0x28, 0x29, 0x5C):        # ( ) \
            out += b"\\" + bytes([byte])
        elif 32 <= byte <= 126:
            out.append(byte)
        else:
            out += ("\\%03o" % byte).encode("ascii")
    out += b")"
    return bytes(out)


# ------------------------------------------------------------------ canvas

PAGE_W, PAGE_H = 612.0, 792.0
MARGIN_X, MARGIN_TOP, MARGIN_BOTTOM = 56.0, 62.0, 58.0
CONTENT_W = PAGE_W - 2 * MARGIN_X

NAVY = (0.04, 0.13, 0.25)
GOLD = (0.82, 0.58, 0.0)
GREY = (0.36, 0.42, 0.52)
FAINT = (0.62, 0.66, 0.74)
RULE = (0.85, 0.88, 0.92)
BLACK = (0.10, 0.12, 0.18)


class Canvas:
    def __init__(self, footer=""):
        self.pages = []
        self.stream = bytearray()
        self.y = PAGE_H - MARGIN_TOP
        self.footer = footer

    # -- primitives ------------------------------------------------------
    def _op(self, chunk):
        self.stream += chunk if isinstance(chunk, bytes) else chunk.encode("ascii")
        self.stream += b"\n"

    def draw_text(self, text, x, y, font=REGULAR, size=10.5, color=BLACK):
        self._op("BT")
        self._op("%.3f %.3f %.3f rg" % color)
        self._op("/%s %.2f Tf" % (font, size))
        self._op("1 0 0 1 %.2f %.2f Tm" % (x, y))
        self._op(_pdf_string(text) + b" Tj")
        self._op("ET")

    def draw_rule(self, y, x0=None, x1=None, color=RULE, width=0.7):
        x0 = MARGIN_X if x0 is None else x0
        x1 = (PAGE_W - MARGIN_X) if x1 is None else x1
        self._op("%.3f %.3f %.3f RG" % color)
        self._op("%.2f w" % width)
        self._op("%.2f %.2f m %.2f %.2f l S" % (x0, y, x1, y))

    def fill_rect(self, x, y, w, h, color):
        self._op("%.3f %.3f %.3f rg" % color)
        self._op("%.2f %.2f %.2f %.2f re f" % (x, y, w, h))

    # -- page flow -------------------------------------------------------
    def new_page(self):
        if self.stream:
            self.pages.append(bytes(self.stream))
        self.stream = bytearray()
        self.y = PAGE_H - MARGIN_TOP

    def finish(self):
        if self.stream:
            self.pages.append(bytes(self.stream))
            self.stream = bytearray()

    def space_left(self):
        return self.y - MARGIN_BOTTOM

    def need(self, height):
        """Start a new page unless `height` still fits on this one."""
        if self.space_left() < height:
            self.new_page()
            return True
        return False

    def gap(self, amount):
        self.y -= amount

    # -- content ---------------------------------------------------------
    def paragraph(self, text, font=REGULAR, size=10.5, color=BLACK,
                  leading=14.5, indent=0.0, width=None):
        width = width or (CONTENT_W - indent)
        for line in wrap(text, font, size, width):
            self.need(leading)
            self.draw_text(line, MARGIN_X + indent, self.y - size, font, size, color)
            self.y -= leading

    def heading(self, text):
        self.need(46)
        self.gap(12)
        self.draw_text(text.upper(), MARGIN_X, self.y - 8, BOLD, 8.5, GREY)
        self.y -= 13
        self.draw_rule(self.y)
        self.y -= 11

    def bullet(self, text, size=10.5, leading=14.5, marker="•"):
        lines = wrap(text, REGULAR, size, CONTENT_W - 16)
        self.need(leading * min(len(lines), 3))
        first = True
        for line in lines:
            self.need(leading)
            if first:
                self.draw_text(marker, MARGIN_X + 2, self.y - size, REGULAR, size, GOLD)
                first = False
            self.draw_text(line, MARGIN_X + 16, self.y - size, REGULAR, size, BLACK)
            self.y -= leading

    def two_column(self, left, right_lines, left_width=104.0, size=9.8,
                   leading=13.5, left_color=GREY, left_font=BOLD):
        """A date/label column beside a block of text."""
        block = []
        for text, font, color in right_lines:
            block.extend((line, font, color) for line in
                         wrap(text, font, size, CONTENT_W - left_width - 12))
        self.need(leading * len(block) + 6)
        top = self.y
        self.draw_text(left, MARGIN_X, top - size, left_font, size - 0.6, left_color)
        for line, font, color in block:
            self.draw_text(line, MARGIN_X + left_width, self.y - size, font, size, color)
            self.y -= leading
        self.y = min(self.y, top - leading)
        self.y -= 4

    def ruled_lines(self, count, spacing=22.0):
        for _ in range(count):
            self.need(spacing)
            self.draw_rule(self.y - spacing + 6, color=(0.88, 0.90, 0.94), width=0.6)
            self.y -= spacing


# ------------------------------------------------------------------ output

def _build_document(pages, footer_text):
    """Assemble page streams into a PDF file."""
    objects = []          # 1-indexed when referenced

    def add(body):
        objects.append(body)
        return len(objects)

    font_ids = {
        REGULAR: add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
                     b"/Encoding /WinAnsiEncoding >>"),
        BOLD: add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
                  b"/Encoding /WinAnsiEncoding >>"),
        ITALIC: add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Oblique "
                    b"/Encoding /WinAnsiEncoding >>"),
    }
    resources = ("<< /Font << /F1 %d 0 R /F2 %d 0 R /F3 %d 0 R >> >>" % (
        font_ids[REGULAR], font_ids[BOLD], font_ids[ITALIC])).encode("ascii")

    pages_id = add(b"")   # placeholder, filled once page ids are known
    page_ids = []

    total = len(pages)
    for index, stream in enumerate(pages, start=1):
        footer = Canvas()
        footer.stream = bytearray()
        label = "%s   ·   page %d of %d" % (footer_text, index, total)
        footer.draw_text(label, MARGIN_X, 34, REGULAR, 8, FAINT)
        full = stream + bytes(footer.stream)

        content_id = add(b"<< /Length %d >>\nstream\n" % len(full) + full +
                         b"\nendstream")
        page_id = add(("<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.0f %.0f] "
                       "/Resources " % (pages_id, PAGE_W, PAGE_H)).encode("ascii")
                      + resources
                      + (" /Contents %d 0 R >>" % content_id).encode("ascii"))
        page_ids.append(page_id)

    kids = " ".join("%d 0 R" % pid for pid in page_ids)
    objects[pages_id - 1] = ("<< /Type /Pages /Count %d /Kids [%s] >>"
                             % (len(page_ids), kids)).encode("ascii")
    catalog_id = add(("<< /Type /Catalog /Pages %d 0 R >>" % pages_id).encode("ascii"))

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += ("%d 0 obj\n" % number).encode("ascii") + body + b"\nendobj\n"

    xref_at = len(out)
    out += ("xref\n0 %d\n" % (len(objects) + 1)).encode("ascii")
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += ("%010d 00000 n \n" % offset).encode("ascii")
    out += ("trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objects) + 1, catalog_id, xref_at)).encode("ascii")
    return bytes(out)


# -------------------------------------------------------------- the document

def build_prep_pdf(prep, settings):
    person = prep.get("person", {})
    name = person.get("name") or "Coffee chat"
    canvas = Canvas()

    # ---- masthead
    canvas.fill_rect(MARGIN_X, canvas.y - 4, 46, 3, GOLD)
    canvas.y -= 22
    canvas.draw_text("Coffee chat prep", MARGIN_X, canvas.y, BOLD, 9, GOLD)
    canvas.y -= 26
    canvas.draw_text(name, MARGIN_X, canvas.y, BOLD, 21, NAVY)
    canvas.y -= 16
    subtitle = " · ".join(x for x in [person.get("role"), person.get("firm")] if x)
    if subtitle:
        canvas.draw_text(subtitle, MARGIN_X, canvas.y, REGULAR, 11, GREY)
        canvas.y -= 15
    stamp = dt.datetime.now().strftime("Prepared %d %B %Y")
    canvas.draw_text(stamp, MARGIN_X, canvas.y, REGULAR, 8.5, FAINT)
    canvas.y -= 12
    canvas.draw_rule(canvas.y, color=NAVY, width=1.1)
    canvas.y -= 6

    # ---- summary
    if prep.get("has_profile"):
        canvas.heading("Summary")
        canvas.paragraph(prep.get("summary", ""), size=10.5, leading=15)

        if prep.get("signals"):
            canvas.gap(4)
            canvas.paragraph(
                "  ".join("• " + s["label"] for s in prep["signals"]),
                font=BOLD, size=9, color=GOLD, leading=13)
    else:
        canvas.heading("No profile on file")
        canvas.paragraph(
            "No LinkedIn profile has been pasted in for %s yet, so these questions "
            "are the general set rather than ones built from their career. Paste "
            "their profile into the prep sheet in the app to get questions that "
            "name specifics." % name, size=10, leading=14.5, color=GREY)

    # ---- opener
    if prep.get("opener"):
        canvas.heading("First two minutes")
        canvas.paragraph(prep["opener"], size=10.5, leading=15)

    # ---- career
    if prep.get("timeline"):
        canvas.heading("Career")
        for row in prep["timeline"]:
            detail = row.get("company", "")
            if row.get("length"):
                detail = (detail + " · " + row["length"]).strip(" ·")
            canvas.two_column(
                row.get("when", ""),
                [(row.get("title") or "—", BOLD, BLACK)] +
                ([(detail, REGULAR, GREY)] if detail else []),
                left_color=GOLD if row.get("current") else GREY,
            )
    if prep.get("education"):
        canvas.two_column("Education", [
            (" · ".join(x for x in [e.get("degree"), e.get("school") or e.get("detail")] if x),
             REGULAR, BLACK) for e in prep["education"]])

    # ---- questions
    def question_block(title, items, badge_key):
        if not items:
            return
        canvas.heading(title)
        for item in items:
            badge = item.get(badge_key, "")
            lines = wrap(item["text"], REGULAR, 10.5, CONTENT_W - 16)
            canvas.need(14 + 15 * min(len(lines), 3))
            if badge:
                canvas.draw_text(badge.upper(), MARGIN_X + 16, canvas.y - 7.5,
                                 BOLD, 7.5, FAINT)
                canvas.y -= 12
            canvas.bullet(item["text"], size=10.5, leading=15)
            canvas.gap(7)

    question_block("Tailored to them", prep.get("tailored", []), "why")
    question_block("Company culture", prep.get("culture", []), "theme")
    question_block("Their journey", prep.get("journey", []), "theme")

    # ---- the call
    if prep.get("flow"):
        canvas.heading("How to run the 30 minutes")
        for step in prep["flow"]:
            canvas.two_column(step["span"], [
                (step["stage"], BOLD, NAVY),
                (step["detail"], REGULAR, GREY),
            ])

    # ---- room to write during the call
    canvas.heading("Notes from the call")
    canvas.paragraph(
        "What they said, who they offered to introduce you to, anything to name "
        "in the thank-you note within 24 hours.", size=9, color=FAINT, leading=13)
    canvas.gap(4)
    canvas.ruled_lines(max(4, int(canvas.space_left() // 22)))

    canvas.finish()
    who = (settings or {}).get("user_name") or "Coffee Chat Tracker"
    return _build_document(canvas.pages, _sanitise(who))
