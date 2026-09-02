"""Read the text out of a LinkedIn "Save to PDF" profile export.

LinkedIn blocks automated fetching, but it will hand *you* a PDF of a profile
from the More menu. That file is the one route into the app that needs no
copying, no pasting, and no scraping — you already have it on disk.

Standard library only, like everything else here, which means the PDF is taken
apart by hand:

  * object streams are Flate-compressed, so zlib inflates them;
  * the text is written in a Type0/CID font, so the bytes in the content
    stream are glyph numbers rather than characters, and the font's ToUnicode
    CMap is what turns them back into text;
  * there are no line breaks in a PDF — only glyphs at coordinates — so lines
    are recovered by watching the vertical position between text runs.

This is deliberately narrow. It reads the text-based PDFs LinkedIn generates,
not arbitrary ones, and it does not try to be a general PDF library. When it
cannot make sense of a file it says so and the paste box is still there.
"""

import re
import zlib

# A text run is worth calling a new line once the baseline has moved this far.
LINE_EPSILON = 2.0
# ...and a space when two runs sit apart on the same baseline.
SPACE_EPSILON = 1.2


class PdfError(Exception):
    pass


# --------------------------------------------------------------- streams

def _streams(data):
    """Every object stream in the file, inflated where it can be."""
    out = []
    for match in re.finditer(rb"stream\r?\n", data):
        start = match.end()
        end = data.find(b"endstream", start)
        if end == -1:
            continue
        blob = data[start:end].strip(b"\r\n")
        try:
            out.append(zlib.decompress(blob))
        except zlib.error:
            try:
                out.append(zlib.decompressobj().decompress(blob))
            except zlib.error:
                continue
    return out


# ------------------------------------------------------------ ToUnicode

def _parse_cmap(text):
    """Glyph id -> character, from a ToUnicode CMap."""
    mapping = {}

    for block in re.findall(rb"beginbfchar(.*?)endbfchar", text, re.S):
        for src, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            mapping[int(src, 16)] = _utf16_be(dst)

    for block in re.findall(rb"beginbfrange(.*?)endbfrange", text, re.S):
        # <lo> <hi> <dst>  — a run of consecutive glyphs
        for lo, hi, dst in re.findall(
                rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            start, stop, base = int(lo, 16), int(hi, 16), int(dst, 16)
            for offset in range(stop - start + 1):
                mapping[start + offset] = chr(base + offset)
        # <lo> <hi> [<a> <b> ...] — an explicit list
        for lo, _hi, items in re.findall(
                rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\[(.*?)\]", block, re.S):
            start = int(lo, 16)
            for offset, dst in enumerate(re.findall(rb"<([0-9A-Fa-f]+)>", items)):
                mapping[start + offset] = _utf16_be(dst)

    return mapping


def _utf16_be(hex_bytes):
    raw = bytes.fromhex(hex_bytes.decode("ascii"))
    try:
        return raw.decode("utf-16-be")
    except UnicodeDecodeError:
        return ""


# -------------------------------------------------------------- content

NUM = r"[-+]?[\d.]+"
TOKEN = re.compile(
    rb"(?P<q>\bq\b)"
    rb"|(?P<Q>\bQ\b)"
    rb"|(?P<cm>" + NUM.encode() + rb"(?:\s+" + NUM.encode() + rb"){5}\s+cm\b)"
    rb"|(?P<tm>" + NUM.encode() + rb"(?:\s+" + NUM.encode() + rb"){5}\s+Tm\b)"
    rb"|(?P<td>" + NUM.encode() + rb"\s+" + NUM.encode() + rb"\s+T[dD]\b)"
    rb"|(?P<tstar>\bT\*)"
    rb"|(?P<show>\[[^\]]*\]\s*TJ|<[0-9A-Fa-f]*>\s*Tj|\([^)]*\)\s*Tj)"
)

HEX_RUN = re.compile(rb"<([0-9A-Fa-f]*)>")


def _decode_run(hex_text, cmap):
    """Glyph ids are two bytes each in the identity encoding LinkedIn uses."""
    raw = hex_text.decode("ascii")
    if len(raw) % 4:                      # not 2-byte codes; nothing to do
        return ""
    out = []
    for i in range(0, len(raw), 4):
        glyph = int(raw[i:i + 4], 16)
        out.append(cmap.get(glyph, ""))
    return "".join(out)


def _numbers(chunk):
    return [float(n) for n in re.findall(NUM.encode(), chunk)]


def extract_text(data):
    """The visible text of a PDF, with line breaks inferred from geometry."""
    streams = _streams(data)
    if not streams:
        raise PdfError("Nothing could be read out of that PDF.")

    cmap = {}
    for stream in streams:
        if b"beginbfchar" in stream or b"beginbfrange" in stream:
            cmap.update(_parse_cmap(stream))
    if not cmap:
        raise PdfError(
            "That PDF has no text layer this app can read — it may be a scan "
            "or an image. Copy the profile text and paste it instead.")

    lines = []
    current = []
    last_y = None
    last_x_end = None

    for stream in streams:
        if b"TJ" not in stream and b"Tj" not in stream:
            continue

        stack = [(0.0, 0.0)]
        offset = (0.0, 0.0)

        for token in TOKEN.finditer(stream):
            kind = token.lastgroup
            chunk = token.group()

            if kind == "q":
                stack.append(offset)
            elif kind == "Q":
                offset = stack.pop() if len(stack) > 1 else (0.0, 0.0)
            elif kind == "cm":
                nums = _numbers(chunk)
                offset = (offset[0] + nums[4], offset[1] + nums[5])
            elif kind in ("tm", "td", "tstar"):
                if kind == "tstar":
                    y = (last_y or 0) - 1      # forced new line
                    x = offset[0]
                else:
                    nums = _numbers(chunk)
                    x = offset[0] + nums[-2]
                    y = offset[1] + abs(nums[-1])

                if last_y is not None and abs(y - last_y) > LINE_EPSILON:
                    if current:
                        lines.append("".join(current))
                        current = []
                elif last_x_end is not None and x - last_x_end > SPACE_EPSILON:
                    current.append(" ")
                last_y = y
                last_x_end = x
            elif kind == "show":
                text = "".join(_decode_run(h, cmap) for h in HEX_RUN.findall(chunk))
                if text:
                    current.append(text)
                    last_x_end = (last_x_end or 0) + len(text) * 5

    if current:
        lines.append("".join(current))

    cleaned = []
    for line in lines:
        line = re.sub(r"[ \t]+", " ", line).strip()
        if line:
            cleaned.append(line)
    if not cleaned:
        raise PdfError("That PDF had no readable text in it.")
    return "\n".join(cleaned)


def looks_like_pdf(data):
    return data[:5] == b"%PDF-"
