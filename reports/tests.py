from types import SimpleNamespace

from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase

from bookings.models import Booking

from .models import TDSDocumentTemplate
from .dependencies import CircuitBreaker, DependencyUnavailable
from .views import _render_tds_content, _render_tds_source_file, _split_tds_rendered_pages


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

    def test_split_tds_rendered_pages_handles_css_page_break_markers(self):
        content = "<div>First page</div><div style='page-break-before: always;'></div><div>Second page</div>"

        pages = _split_tds_rendered_pages(content)

        self.assertEqual(len(pages), 2)
        self.assertIn("First page", pages[0])
        self.assertIn("Second page", pages[1])

    def test_split_tds_rendered_pages_splits_on_break_rule_on_content_table(self):
        content = (
            "<table><tr><td>First page</td></tr></table>"
            "<table style='page-break-before: always;'><tr><td>Second page</td></tr></table>"
        )

        pages = _split_tds_rendered_pages(content)

        self.assertEqual(len(pages), 2)
        self.assertIn("First page", pages[0])
        self.assertIn("Second page", pages[1])
        self.assertNotIn("page-break-before", pages[1])

    def test_split_tds_rendered_pages_removes_duplicate_break_after_marker(self):
        content = (
            "<div>First page</div>[[page_break]]"
            "<table style='page-break-before: always; width: 100%;'><tr><td>Second page</td></tr></table>"
        )

        pages = _split_tds_rendered_pages(content)

        self.assertEqual(len(pages), 2)
        self.assertIn("Second page", pages[1])
        self.assertIn("width: 100%", pages[1])
        self.assertNotIn("page-break-before", pages[1])

    def test_empty_ac_template_without_inject_returns_empty(self):
        req = RequestFactory().get("/")
        booking = Booking(batch_no="B-001")

        rendered = _render_tds_content("", booking, req, TDSDocumentTemplate.DocumentType.AC)

        self.assertEqual(rendered, "")

    def test_empty_ac_template_with_inject_builds_content(self):
        req = RequestFactory().get("/?inject_booking=1")
        booking = Booking(batch_no="B-001")

        rendered = _render_tds_content("", booking, req, TDSDocumentTemplate.DocumentType.AC)

        self.assertIn("CHECKLIST FOR ANALYTICAL DATA REVIEW", rendered)

    def test_full_letterhead_renders_as_img_elements_for_print_stability(self):
        letterhead = SimpleNamespace(
            layout_mode="full",
            full_image=SimpleNamespace(url="/media/coa_letterhead.png"),
            header_image=None,
            footer_image=None,
            middle_image=None,
        )
        report = SimpleNamespace(
            final_outcome="approved",
            manager_signature="",
            incharge_signature="",
            manager_name="",
            incharge_name="",
            manager=None,
            incharge=None,
        )

        rendered = render_to_string(
            "reports/partials/coa_letterhead.html",
            {
                "coa_letterhead": letterhead,
                "report": report,
                "is_plain_doc": False,
                "is_test_report": False,
                "qr_payload": "payload",
                "qr_image_data": None,
                "initial_result_html": "",
                "initial_tail_html": "",
            },
        )

        self.assertIn('class="coa-letterhead-image coa-letterhead-image--full"', rendered)
        self.assertNotIn("background-image:url(", rendered)


class DependencyCircuitBreakerTests(SimpleTestCase):
    def test_open_circuit_fast_fails_after_a_dependency_failure(self):
        breaker = CircuitBreaker(failure_threshold=1, recovery_seconds=60, max_concurrent=1)

        with self.assertRaises(DependencyUnavailable):
            breaker.call(lambda: (_ for _ in ()).throw(OSError("converter unavailable")))

        with self.assertRaises(DependencyUnavailable):
            breaker.call(lambda: "this operation must not run while the circuit is open")
