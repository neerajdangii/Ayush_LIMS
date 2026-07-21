from django.test import RequestFactory, SimpleTestCase

from bookings.models import Booking

from .models import TDSDocumentTemplate
from .views import _render_tds_content, _render_tds_source_file


class TDSRenderingSafetyTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().get("/")
        self.booking = Booking(batch_no="B-001")

    def test_invalid_editable_template_returns_inline_error(self):
        rendered = _render_tds_content("{% if %}", self.booking, self.request, TDSDocumentTemplate.DocumentType.CS)

        self.assertIn("tds-template-render-error", rendered)
        self.assertIn("invalid template syntax", rendered)

    def test_missing_uploaded_html_source_returns_inline_error(self):
        template = TDSDocumentTemplate(
            document_type=TDSDocumentTemplate.DocumentType.CS,
            name="Missing source",
            display_mode=TDSDocumentTemplate.DisplayMode.SOURCE_FILE,
            source_file="tds_templates/not-present.html",
        )

        preview = _render_tds_source_file(template, self.booking, self.request, TDSDocumentTemplate.DocumentType.CS)

        self.assertEqual(preview["kind"], "html")
        self.assertIn("tds-template-render-error", preview["content"])
        self.assertIn("Uploaded source file is missing", preview["content"])
