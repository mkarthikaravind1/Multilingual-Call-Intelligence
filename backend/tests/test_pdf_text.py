"""PDF exports print Tamil, Telugu, Kannada and Malayalam: each paragraph in
the font of its script, shaped, with what cannot be printed left out
visibly and said so."""

import io

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import SimpleDocTemplate

from app.services.pdf_text import FONT_DIRECTORY, LEFT_OUT, SCRIPTS, PdfText, font_name

BODY = getSampleStyleSheet()["BodyText"]
SAMPLES = {
    "Tamil": "வண்டி தாமதமாக கிடைத்தது",
    "Telugu": "కారు ఆలస్యంగా వచ్చింది",
    "Kannada": "ಕಾರು ತಡವಾಗಿ ಸಿಕ್ಕಿತು",
    "Malayalam": "കാർ വൈകിയാണ് കിട്ടിയത്",
}


def _pdf(*paragraphs) -> bytes:
    buffer = io.BytesIO()
    SimpleDocTemplate(buffer, pagesize=A4).build(list(paragraphs))
    return buffer.getvalue()


def test_the_four_fonts_and_their_licences_are_bundled():
    for script in SCRIPTS:
        assert (FONT_DIRECTORY / f"{font_name(script)}.ttf").stat().st_size > 100_000
        licence = (FONT_DIRECTORY / f"{font_name(script)}-OFL.txt").read_text(encoding="utf-8")
        assert "SIL Open Font License" in licence


def test_latin_text_stays_in_the_ordinary_font():
    writer = PdfText()

    paragraph = writer.paragraph("Café – “on time” · 100%", BODY)

    assert paragraph.style is BODY
    assert paragraph.text == "Café – “on time” · 100%"
    assert not writer.left_out


@pytest.mark.parametrize("script", list(SCRIPTS))
def test_each_script_is_set_in_its_own_font_and_shaped(script):
    writer = PdfText()

    paragraph = writer.paragraph(SAMPLES[script], BODY)

    assert paragraph.style.fontName == font_name(script)
    assert paragraph.style.shaping == 1
    assert paragraph.style.leading > BODY.leading
    assert paragraph.text == SAMPLES[script]
    assert not writer.left_out
    assert pdfmetrics.getFont(font_name(script)).shapable
    # And it makes a PDF with that font inside.
    content = _pdf(paragraph)
    assert content[:5] == b"%PDF-"
    assert font_name(script).encode() in content


def test_mixed_tamil_and_english_with_a_rupee_amount_prints_whole():
    writer = PdfText()
    said = "Estimate-ல ₹4000-ன்னு சொன்னீங்க, final bill ₹7200."

    paragraph = writer.paragraph(said, BODY)

    assert paragraph.text == said
    assert paragraph.style.fontName == "NotoSansTamil"
    assert not writer.left_out


def test_a_rupee_sign_in_latin_text_is_written_out():
    writer = PdfText()

    paragraph = writer.paragraph("Brake pads ₹2,800 and labour ₹900", BODY)

    assert paragraph.text == "Brake pads Rs 2,800 and labour Rs 900"
    assert not writer.left_out


def test_what_no_font_here_prints_is_left_out_and_said_so():
    writer = PdfText()

    devanagari = writer.paragraph("गाड़ी late", BODY)
    two_scripts = writer.paragraph("வண்டி தாமதம் కారు", BODY)

    assert devanagari.text == f"{LEFT_OUT} late"
    # Set in the script there is more of; the other is left out, once.
    assert two_scripts.style.fontName == "NotoSansTamil"
    assert two_scripts.text == f"வண்டி தாமதம் {LEFT_OUT}"
    assert writer.left_out


def test_the_style_for_a_script_is_made_once_and_markup_is_escaped():
    writer = PdfText()

    first = writer.paragraph("வண்டி <b>", BODY)
    second = writer.paragraph("தாமதம் & more", BODY)

    assert first.style is second.style
    assert _pdf(first, second)[:5] == b"%PDF-"


def test_a_report_with_text_in_all_four_scripts_makes_a_pdf_without_leaving_any_out():
    from app.services import pdf_text, report_export

    seen: list[PdfText] = []

    class _Watched(PdfText):
        def __init__(self) -> None:
            super().__init__()
            seen.append(self)

    from tests.test_reports import _Stores  # the report fixtures

    stores = _Stores()
    for index, text in enumerate(SAMPLES.values()):
        stores.call(f"c{index}", 0.5 + index, {"Cost": "detected"}, described={"Cost": text})
    report = stores.report()
    assert len(report.root_causes[0].themes) == 4

    report_export.PdfText, original = _Watched, report_export.PdfText
    try:
        content, media_type, _ = report_export.export_report(report, "pdf")
    finally:
        report_export.PdfText = original

    assert media_type == "application/pdf"
    assert content[:5] == b"%PDF-"
    assert all(font_name(script).encode() in content for script in SCRIPTS)
    assert not seen[0].left_out
    assert pdf_text.LEFT_OUT_NOTE.encode() not in content
