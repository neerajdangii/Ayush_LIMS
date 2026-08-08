from __future__ import annotations

from datetime import date, datetime, time
from html import unescape
import logging
from pathlib import Path
import re

from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.contrib.auth import get_user_model
from django.http import Http404
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.template.defaultfilters import linebreaksbr
from django.template import engines
from django.template import TemplateSyntaxError
from django.utils.html import escape, strip_tags
from django.views.generic import CreateView, DeleteView, DetailView, FormView, ListView, TemplateView, UpdateView, View
from django.utils.decorators import method_decorator

from accounts.models import SystemSetting
from bookings.models import Booking
from bookings.permissions import RoleRequiredMixin, has_role

from .forms import COAEditForm, COALetterheadForm, ReportApprovalForm, ReportTemplateForm, TDSDocumentTemplateForm, TestLetterheadForm, _extract_uploaded_printable_content
from .models import COALetterhead, Report, ReportRemark, ReportTemplate, TDSDocumentTemplate, TestLetterhead


PUBLIC_REPORT_ALLOWED_STATUSES = {
    Report.Status.MANAGER_APPROVED,
    Report.Status.INCHARGE_APPROVED,
}

logger = logging.getLogger(__name__)

def _format_report_date(value, include_time=False, month_year_only=False):
    if not value:
        return "N.S."

    if isinstance(value, datetime):
        current = timezone.localtime(value) if timezone.is_aware(value) else value
        if month_year_only:
            return current.strftime("%m/%Y")
        return current.strftime("%d/%m/%Y %I:%M %p") if include_time else current.strftime("%d/%m/%Y")

    if isinstance(value, date):
        if month_year_only:
            return value.strftime("%m/%Y")
        return value.strftime("%d/%m/%Y")

    return value


def _build_report_date_context(report):
    booking = report.booking
    return {
        "report_letter_date": _format_report_date(booking.letter_date, include_time=False),
        "report_received_date": _format_report_date(booking.sample_receipt_date, include_time=False),
        "report_analysis_start_date": _format_report_date(booking.analysis_start_date, include_time=False),
        "report_analysis_end_date": _format_report_date(report.analysis_end_date, include_time=False),
        "report_manufacture_date": _format_report_date(booking.manufacture_date, month_year_only=True),
        "report_expiry_date": _format_report_date(booking.expiry_retest_date, month_year_only=True),
    }


def _get_report_render_context(report, request, *, preview_mode, auto_print, is_plain_doc, is_test_report):
    remark_text = (report.remark_text or "").strip()
    if not remark_text and report.selected_remark_id:
        remark_text = (report.selected_remark.content or "").strip()

    tail_html = '<div class="coa-end-report">*** END OF REPORT ***</div>'
    if remark_text:
        tail_html += f'<div class="coa-remark">Remark: {linebreaksbr(escape(remark_text))}</div>'

    context = {
        "report": report,
        "preview_mode": preview_mode,
        "auto_print": auto_print,
        "is_plain_doc": is_plain_doc,
        "is_test_report": is_test_report,
        "document_title": "Test Report" if is_test_report else "Certificate of Analysis",
        "tail_html": mark_safe(tail_html),
        "draft_remark_text": remark_text,
        "tests_with_templates": report.tests_with_templates,
        "tests_without_templates": report.tests_without_templates,
        "generic_tests_table_html": mark_safe(report.generic_tests_table_html),
    }

    base = reverse("reports:coa_public", kwargs={"pk": report.pk})
    if is_test_report:
        base += "?doc=test"

    page_base = base
    if is_plain_doc:
        page_base += "&plain=1" if "?" in page_base else "?plain=1"

    context["coa_public_url"] = request.build_absolute_uri(page_base)
    context["qr_payload"] = request.build_absolute_uri(base)
    context["report_ceo_content"] = mark_safe(report.ceo_content or "")
    letterhead_model = TestLetterhead if is_test_report else COALetterhead
    # The title controls are independent from the background letterhead.  This
    # lets a user rename or hide the title even when using a plain report.
    letterhead_settings = letterhead_model.objects.filter(pk=1).first()
    letterhead = letterhead_model.get_active()
    context["coa_letterhead"] = letterhead
    if letterhead_settings:
        if not letterhead_settings.show_report_title:
            context["document_title"] = ""
        elif letterhead_settings.report_title.strip():
            context["document_title"] = letterhead_settings.report_title.strip()
    context.update(_build_report_date_context(report))
    return context


def _get_public_report_or_404(pk):
    return get_object_or_404(Report.objects.select_related("booking", "booking__customer", "booking__sample_name"), pk=pk, status__in=PUBLIC_REPORT_ALLOWED_STATUSES)


def _booking_template_context(booking, request):
    sample_name = booking.sample_name.name if booking.sample_name_id else ""
    batch_no = booking.batch_no or ""
    return {
        "booking": booking,
        "sample_name": sample_name,
        "sample_display_name": sample_name,
        "sample_type": booking.sample_type,
        "sample_qty": booking.sample_qty,
        "uom": booking.uom.name if booking.uom_id else "",
        "sample_number": batch_no,
        "sample_no": batch_no,
        "sample_reg_no": booking.sample_registration_no,
        "sample_registration_no": booking.sample_registration_no,
        "certificate_no": booking.certificate_no,
        "certificate_number": booking.certificate_no,
        "report_number": booking.certificate_no,
        "booking_id": booking.tracking_code,
        "batch_no": batch_no,
        "batch_size": booking.batch_size,
        "customer_name": booking.customer.name if booking.customer_id else "",
        "customer_address": booking.customer.address if booking.customer_id else "",
        "customer_contact_person": booking.customer.contact_person if booking.customer_id else "",
        "customer_telephone": booking.customer.telephone if booking.customer_id else "",
        "customer_email": booking.customer.email if booking.customer_id else "",
        "manufacturer_name": booking.manufacturer.name if booking.manufacturer_id else "",
        "submitter_name": booking.submitter.name if booking.submitter_id else "",
        "protocol_name": booking.protocol.name if booking.protocol_id else "",
        "sample_receipt_date": _format_report_date(booking.sample_receipt_date),
        "booking_date": _format_report_date(booking.booking_date),
        "letter_date": _format_report_date(booking.letter_date),
        "manufacture_date": _format_report_date(booking.manufacture_date, month_year_only=True),
        "expiry_retest_date": _format_report_date(booking.expiry_retest_date, month_year_only=True),
        "license_no": booking.license_no,
        "collected_by": booking.collected_by_name,
        "sample_location": booking.sample_location,
        "sample_condition": booking.sample_condition,
        "packaging_mode": booking.packaging_mode,
        "sampling_procedure": booking.sampling_procedure,
        "request": request,
    }


def _render_tds_content(content, booking, request, document_type=None, inject_booking=None):
    # Keep the optional argument for existing callers. Job Order, AC, TRF,
    # and Checklist now use only their explicit ID-based template fields.

    if not content:
        return ""
    rendered_content = _render_django_fragment(content, booking, request, label=document_type or "document")
    if "tds-template-render-error" in rendered_content:
        return rendered_content
    rendered_content = _strip_tds_trailing_empty_blocks(rendered_content)
    rendered_content = _unwrap_tds_outer_table(rendered_content)
    if document_type in {TDSDocumentTemplate.DocumentType.AC, TDSDocumentTemplate.DocumentType.CHECKLIST}:
        rendered_content = _clean_tds_legacy_footer(rendered_content)
    id_based_documents = {
        TDSDocumentTemplate.DocumentType.JOB_ORDER,
        TDSDocumentTemplate.DocumentType.AC,
        TDSDocumentTemplate.DocumentType.TRF,
        TDSDocumentTemplate.DocumentType.CHECKLIST,
        TDSDocumentTemplate.DocumentType.CS,
    }
    if document_type not in id_based_documents:
        rendered_content = _fill_tds_booking_labels(rendered_content, booking)
    if document_type == TDSDocumentTemplate.DocumentType.JOB_ORDER:
        # Preserve ID-based fields while generating only the test rows selected
        # on the booking and formatting the signature/page footer.
        rendered_content = _fill_tds_job_order_tests(rendered_content, booking)
        rendered_content = _strip_tds_job_order_empty_tables(rendered_content)
        rendered_content = _mark_tds_job_order_footer_tables(rendered_content)
    if document_type == TDSDocumentTemplate.DocumentType.TRF:
        # Keep the editable TRF master and its ID-based fields intact; only
        # add customer contact details, selected booking tests, and the fixed
        # document footer.
        test_names = ", ".join(test.name for test in booking.test_to_be_performed.order_by("name"))
        customer = booking.customer if booking.customer_id else None
        for label, value in (
            ("Contact Person", customer.contact_person if customer else ""),
            ("Telephone", customer.telephone if customer else ""),
            ("Email", customer.email if customer else ""),
            ("Ref. No.", booking.customer_sr_no),
            ("Tests", test_names),
        ):
            rendered_content = _fill_tds_trf_row_value(rendered_content, label, value)
        rendered_content = re.sub(r"(?:&nbsp;|&#160;|\xa0){3,}", " ", rendered_content, flags=re.IGNORECASE)
        rendered_content = (
            '<div class="tds-trf-document">'
            f"{rendered_content}"
            "</div>"
        )
    if document_type == TDSDocumentTemplate.DocumentType.ADS:
        rendered_content = _position_tds_ads_signature_line(rendered_content)
    return _strip_tds_trailing_empty_blocks(rendered_content)


def _split_tds_rendered_pages(content):
    content = str(content or "")
    if not content:
        return [""]

    marker = "__TDS_PAGE_BREAK__"
    content = re.sub(r"\[\[page_break\]\]", marker, content, flags=re.IGNORECASE)
    content = re.sub(r"<!--\s*pagebreak\s*-->", marker, content, flags=re.IGNORECASE)
    content = re.sub(
        r"<[^>]+class=['\"][^'\"]*(?:tds-page-break|page-break|tds-force-break)[^'\"]*['\"][^>]*>\s*</[^>]+>",
        marker,
        content,
        flags=re.IGNORECASE,
    )
    # Treat a page break placed on any real TinyMCE element exactly like the
    # explicit [[page_break]] marker.  Keep the element itself in the next
    # fragment and remove only its break declaration; otherwise Chrome sees
    # both our generated page and the original CSS page and skips a sheet.
    break_before_re = re.compile(
        r'(?P<open><(?P<tag>[A-Za-z][\w:-]*)\b(?P<before>[^>]*?\bstyle\s*=\s*)'
        r'(?P<quote>["\'])(?P<style>[^"\']*)(?P=quote)(?P<after>[^>]*)>)',
        flags=re.IGNORECASE,
    )

    def replace_break_before(match):
        style = match.group("style")
        cleaned_style = re.sub(
            r'(?:^|;)\s*(?:page-break-before|break-before)\s*:\s*'
            r'(?:always|page|left|right)\s*;?',
            ';',
            style,
            flags=re.IGNORECASE,
        )
        if cleaned_style == style:
            return match.group("open")
        cleaned_style = re.sub(r';\s*;', ';', cleaned_style).strip(' ;')
        opening_tag = (
            f'<{match.group("tag")}{match.group("before")}'
            f'{match.group("quote")}{cleaned_style}{match.group("quote")}{match.group("after")}>'
        )
        return marker + opening_tag

    content = break_before_re.sub(replace_break_before, content)
    parts = [part.strip() for part in content.split(marker) if part and part.strip()]

    # Authors commonly use [[page_break]] and retain the page-break-before
    # style imported from Word on the first table of the next page.  The
    # marker already created that page, so leaving the style in place causes
    # the browser to advance once more and insert a blank sheet.
    leading_break_re = re.compile(
        r'^(?P<prefix>\s*<(?:table|div|section|p)\b[^>]*?\bstyle\s*=\s*)'
        r'(?P<quote>["\'])(?P<style>[^"\']*)(?P=quote)(?P<suffix>[^>]*>)',
        flags=re.IGNORECASE,
    )

    def remove_redundant_leading_break(part):
        def replace(match):
            style = re.sub(
                r'(?:^|;)\s*(?:page-break-before|break-before)\s*:\s*'
                r'(?:always|page|left|right)\s*;?',
                ';',
                match.group("style"),
                flags=re.IGNORECASE,
            )
            style = re.sub(r';\s*;', ';', style).strip(' ;')
            return f'{match.group("prefix")}{match.group("quote")}{style}{match.group("quote")}{match.group("suffix")}'

        return leading_break_re.sub(replace, part, count=1)

    if len(parts) > 1:
        parts = [parts[0], *(remove_redundant_leading_break(part) for part in parts[1:])]
    return parts or [content]


def _render_tds_template_fragment(content, booking, request, inject_booking=None):
    if not content:
        return ""
    if inject_booking is None:
        inject_booking = bool(request and request.GET and request.GET.get("inject_booking") == "1")

    rendered_content = _render_django_fragment(content, booking, request, label="header/footer")
    if "tds-template-render-error" in rendered_content:
        return rendered_content
    rendered_content = rendered_content.replace("[[page_number]]", '<span class="tds-page-current"></span>')
    rendered_content = rendered_content.replace("[[total_pages]]", '<span class="tds-page-total"></span>')
    return _strip_tds_trailing_empty_blocks(rendered_content)


def _fill_tds_page_placeholders(content, page_number, total_pages):
    content = str(content or "")
    if not content:
        return ""
    content = re.sub(
        r'<span\b[^>]*class=["\'][^"\']*\btds-page-current\b[^"\']*["\'][^>]*>\s*</span>',
        str(page_number),
        content,
        flags=re.IGNORECASE,
    )
    content = re.sub(
        r'<span\b[^>]*class=["\'][^"\']*\btds-page-total\b[^"\']*["\'][^>]*>\s*</span>',
        str(total_pages),
        content,
        flags=re.IGNORECASE,
    )
    return content


def _ensure_tds_page_number(content):
    content = str(content or "")
    has_page_placeholder = "tds-page-current" in content or "tds-page-total" in content
    if has_page_placeholder:
        return content
    page_number = '<div class="tds-ads-page-number">Page <span class="tds-page-current"></span> of <span class="tds-page-total"></span></div>'
    if content.strip():
        return f"{content}{page_number}"
    return page_number


def _looks_like_tds_ac_template(content):
    return bool(
        re.search(r"CHECKLIST\s+FOR\s+ANALYTICAL\s+DATA\s+REVIEW", content, flags=re.IGNORECASE)
        or re.search(r"Details\s+to\s+be\s+Checked", content, flags=re.IGNORECASE)
    )


def _extract_tds_ac_logo_url(content):
    match = re.search(r"<img\b[^>]*\bsrc=[\"'](?P<src>[^\"']+)[\"']", content or "", flags=re.IGNORECASE)
    if match:
        return match.group("src")
    return "https://img1.wsimg.com/isteam/ip/a7648e86-1728-4dc8-9d7f-ccade2ccf6d2/Aayush%20Logo.png/:/rs=h:134,cg:true,m/qt=q:95"


def _format_tds_ac_value(value, default="N.S."):
    if value is None:
        return default
    value = str(value).strip()
    return value or default


def _tds_render_error_html(message, detail=""):
    detail_html = f"<br><small>{escape(detail)}</small>" if detail else ""
    return (
        '<div class="alert alert-warning py-2 mb-0 tds-template-render-error">'
        f"{escape(message)}{detail_html}"
        "</div>"
    )


def _render_django_fragment(content, booking, request, *, label):
    try:
        template = engines["django"].from_string(content)
        return template.render(_booking_template_context(booking, request))
    except TemplateSyntaxError as exc:
        logger.warning("TDS %s template syntax error for booking %s: %s", label, booking.pk, exc)
        return _tds_render_error_html(
            "This TDS template could not be rendered because its editable content has invalid template syntax.",
            str(exc),
        )
    except Exception as exc:
        logger.exception("TDS %s template render failed for booking %s", label, booking.pk)
        return _tds_render_error_html(
            "This TDS template could not be rendered. Please check the template content or uploaded source file.",
            str(exc),
        )


def _build_tds_job_order_html(content, booking):
    sample = booking.sample_name if booking.sample_name_id else None
    sample_name = _format_tds_ac_value(sample.display_name if sample else "")
    sample_qty = " ".join(part for part in [booking.sample_qty, booking.uom.name if booking.uom_id else ""] if part)
    tests = list(booking.test_to_be_performed.order_by("name"))
    test_rows = "".join(
        "<tr>"
        f"<td class=\"job-sr\">{index}</td>"
        f"<td>{escape(test.name)}</td>"
        "<td></td>"
        "<td></td>"
        "</tr>"
        for index, test in enumerate(tests, start=1)
    )
    if not test_rows:
        test_rows = '<tr><td class="job-sr">&nbsp;</td><td>&nbsp;</td><td></td><td></td></tr>'

    values = {
        "sample_name": sample_name,
        "batch_no": _format_tds_ac_value(booking.batch_no),
        "sample_quantity": _format_tds_ac_value(sample_qty),
        "storage_condition": _format_tds_ac_value(booking.sample_condition),
        "sampling_location": _format_tds_ac_value(booking.sample_location),
        "collected_by": _format_tds_ac_value(booking.collected_by_name),
        "report_no": _format_tds_ac_value(booking.certificate_no),
        "ulr_no": "N.A",
        "receipt_date": _format_tds_ac_value(_format_report_date(booking.sample_receipt_date)),
        "analysis_start": _format_tds_ac_value(_format_report_date(booking.analysis_start_date)),
        "analysis_end": _format_tds_ac_value(_format_report_date(booking.analysis_end_date)),
        "discipline": _format_tds_ac_value(sample.discipline if sample else ""),
        "group": _format_tds_ac_value(sample.test_group if sample else ""),
        "description": _format_tds_ac_value(sample.description if sample else "", default=""),
        "logo_url": _extract_tds_ac_logo_url(content),
    }

    return (
        '<div class="tds-job-order">'
        '<table class="tds-job-header"><tbody><tr>'
        f'<td class="tds-job-logo" rowspan="3"><img src="{escape(values["logo_url"])}" alt="Ayush Research Laboratories Pvt. Ltd."></td>'
        '<td class="tds-job-lab"><strong>Ayush Research Laboratories Pvt. Ltd.</strong></td>'
        '</tr><tr><td class="tds-job-address">1st &amp; 2nd Floor, 25, Gokul Das Compound, Industrial Estate Opposite Kalyan Mill<br>Indore MP-452011</td></tr>'
        '<tr><td class="tds-job-title"><strong>JOB ORDER</strong></td></tr></tbody></table>'
        '<table class="tds-job-meta"><tbody>'
        f'<tr><td><strong>Sample Name</strong></td><td>{escape(values["sample_name"])}</td><td><strong>Report No</strong></td><td>{escape(values["report_no"])}</td></tr>'
        f'<tr><td><strong>Batch No</strong></td><td>{escape(values["batch_no"])}</td><td><strong>ULR No.</strong></td><td>{escape(values["ulr_no"])}</td></tr>'
        f'<tr><td><strong>Sample Quantity</strong></td><td>{escape(values["sample_quantity"])}</td><td><strong>Sample Receipt Date</strong></td><td>{escape(values["receipt_date"])}</td></tr>'
        f'<tr><td><strong>Storage Condition</strong></td><td>{escape(values["storage_condition"])}</td><td><strong>Analysis started on</strong></td><td>{escape(values["analysis_start"])}</td></tr>'
        f'<tr><td><strong>Sampling Location</strong></td><td>{escape(values["sampling_location"])}</td><td><strong>Analysis completed on</strong></td><td>{escape(values["analysis_end"])}</td></tr>'
        f'<tr><td><strong>Sample Collected by</strong></td><td>{escape(values["collected_by"])}</td><td></td><td></td></tr>'
        '</tbody></table>'
        '<div class="tds-job-info">'
        f'<div><strong>Discipline:</strong> {escape(values["discipline"])} <strong class="tds-job-group">Group:</strong> {escape(values["group"])}</div>'
        f'<div><strong>Sample Description:</strong> {escape(values["description"])}</div>'
        '</div>'
        '<table class="tds-job-tests"><thead><tr><th>Sr. No.</th><th>Test Parameter</th><th>Result</th><th>Specification Limits</th></tr></thead>'
        f'<tbody>{test_rows}</tbody></table>'
        '<div class="tds-job-footer">'
        '<div class="tds-job-signatures">'
        '<div><strong>Analyzed By</strong><br>(Sign &amp; Date)</div>'
        '<div><strong>Reviewed By</strong><br>(Sign &amp; Date)</div>'
        '<div><strong>Approved By</strong><br>(Sign &amp; Date)</div>'
        '</div>'
        '<div class="tds-job-page"><strong>Page 1 of 1</strong></div>'
        '</div>'
        '</div>'
    )


def _build_tds_trf_html(content, booking):
    """Render the TRF in its approved single-page requisition form layout."""
    sample = booking.sample_name if booking.sample_name_id else None
    sample_qty = " ".join(part for part in [booking.sample_qty, booking.uom.name if booking.uom_id else ""] if part)
    tests = ", ".join(test.name for test in booking.test_to_be_performed.order_by("name"))
    value = lambda item, default="N.A": _format_tds_ac_value(item, default=default)
    values = {
        "logo_url": _extract_tds_ac_logo_url(content),
        "date": value(_format_report_date(booking.booking_date)),
        "customer": value(booking.customer.name if booking.customer_id else ""),
        "address": value(booking.customer.address if booking.customer_id else "", default=""),
        "contact": value(booking.customer.contact_person if booking.customer_id else ""),
        "telephone": value(booking.customer.telephone if booking.customer_id else ""),
        "email": value(booking.customer.email if booking.customer_id else ""),
        "sample_name": value(sample.display_name if sample else ""),
        "batch_no": value(booking.batch_no),
        "batch_size": value(booking.batch_size),
        "mfg_date": value(_format_report_date(booking.manufacture_date, month_year_only=True)),
        "exp_date": value(_format_report_date(booking.expiry_retest_date, month_year_only=True)),
        "manufacturer": value(booking.manufacturer.name if booking.manufacturer_id else ""),
        "sample_condition": value(booking.sample_condition),
        "supplied_by": value(booking.collected_by_name),
        "license_no": value(booking.license_no),
        "protocol": value(booking.protocol.name if booking.protocol_id else ""),
        "sample_qty": value(sample_qty),
        "tests": value(tests, default=""),
        "sample_code": value(booking.sample_registration_no),
    }

    return (
        '<div class="tds-trf-document">'
        '<table class="tds-trf-header"><tbody><tr>'
        f'<td class="tds-trf-logo"><img src="{escape(values["logo_url"])}" alt="Ayush Research Laboratories Pvt. Ltd."></td>'
        '<td><strong>Ayush Research Laboratories Pvt. Ltd.</strong><br>'
        '1st &amp; 2nd Floor, 25, Gokul Das Compound, Industrial Estate Opposite Kalyan Mill<br>Indore MP-452011'
        '<div class="tds-trf-title"><strong>SAMPLE REQUISITION FORM</strong></div></td>'
        '</tr></tbody></table>'
        f'<div class="tds-trf-date"><strong>Date :- {escape(values["date"])}</strong></div>'
        '<table class="tds-trf-customer"><tbody>'
        f'<tr><td>From</td><td colspan="3">{escape(values["customer"])}</td></tr>'
        f'<tr><td>Customer Name/Address</td><td colspan="3">{escape(values["address"])}</td></tr>'
        f'<tr><td>Contact Person</td><td>{escape(values["contact"])}</td><td>Telephone</td><td>{escape(values["telephone"])}</td></tr>'
        f'<tr><td>Email</td><td>{escape(values["email"])}</td><td>Statement of Conformity</td><td>Required/Not Required</td></tr>'
        '<tr><td>Test Method</td><td colspan="3">Unless informed by customer samples are tested as per the methods in our scope</td></tr>'
        f'<tr><td>Ref. No.</td><td colspan="3">{escape(values["sample_code"])}</td></tr>'
        '</tbody></table>'
        '<p class="tds-trf-note">Sir,<br>Kindly receive the sample for analysis whose details are given below, and submit the test report.</p>'
        '<table class="tds-trf-sample"><tbody>'
        f'<tr><td>Sample Name</td><td colspan="3">{escape(values["sample_name"])}</td></tr>'
        f'<tr><td>Batch No.</td><td colspan="3">{escape(values["batch_no"])}</td></tr>'
        f'<tr><td>Batch Size</td><td>{escape(values["batch_size"])}</td><td>Sample Qty.</td><td>{escape(values["sample_qty"])}</td></tr>'
        f'<tr><td>Date of Mfg.</td><td>{escape(values["mfg_date"])}</td><td>Date of Exp.</td><td>{escape(values["exp_date"])}</td></tr>'
        f'<tr><td>Mfg By.</td><td>{escape(values["manufacturer"])}</td><td>Sample Storage Condition</td><td>{escape(values["sample_condition"])}</td></tr>'
        f'<tr><td>Supplied By</td><td>{escape(values["supplied_by"])}</td><td>Drug Mfg. Lic. No.</td><td>{escape(values["license_no"])}</td></tr>'
        f'<tr><td>Protocol</td><td colspan="3">{escape(values["protocol"])}</td></tr>'
        '<tr><td>Category</td><td colspan="3"><strong>Routine/Priority/Urgent</strong></td></tr>'
        '<tr><td>Analysis Required</td><td colspan="3">Complete/Partial/Analysis for the following test:</td></tr>'
        f'<tr class="tds-trf-tests"><td>Tests</td><td colspan="3">{escape(values["tests"])}</td></tr>'
        '<tr class="tds-trf-sign-area"><td colspan="4">Customer’s Sign : N.A<br><strong>Office Use Only</strong><div><strong>Sample Code: </strong>'
        f'{escape(values["sample_code"])}<span><strong>Signature:</strong> __________________</span></div></td></tr>'
        '</tbody></table>'
        '<div class="tds-trf-footer"><span></span><span>Page 1 of 1</span><span>QSF/MSP/71/F01-00</span></div>'
        '</div>'
    )


def _build_tds_sample_checklist_html(content, booking):
    sample = booking.sample_name if booking.sample_name_id else None
    sample_name = _format_tds_ac_value(sample.display_name if sample else "")
    sample_qty = " ".join(part for part in [booking.sample_qty, booking.uom.name if booking.uom_id else ""] if part)
    rows = [
        (
            "1.",
            "Is sample ID same on test request and sample container (AR No./ Batch no./ Mfg. Dt / Exp. Dt / Batch Size / Product name / Manufacturer Name) same as on the test request?",
        ),
        ("2.", "Does the sample ID on test request and container match with that in login software?"),
        ("3.", "Sample storage condition, if any (temperature) ____________ °C."),
        ("4.", "Sample requisition slip/Form"),
        ("5.", "Is pharmacopoeia reference or customer specification provided?"),
        ("6.", "Working standard (if provided)"),
        ("7.", "Impurities provided (if requested / required)"),
        ("8.", "Sample spillage during transportation or handling"),
        ("9.", "Entries on requisition form are legible"),
        ("10.", "Sample integrity/intact packing"),
        ("11.", "Sample quantity sufficient required for all analysis"),
        ("12.", "Availability of column if required"),
        ("13.", "Is material hygroscopic"),
        ("14.", "Other"),
    ]
    checklist_rows = "".join(
        "<tr>"
        f"<td class=\"sample-check-sr\">{escape(number)}</td>"
        f"<td>{escape(particular)}</td>"
        "<td></td>"
        "<td></td>"
        "</tr>"
        for number, particular in rows
    )
    values = {
        "sample_name": sample_name,
        "page": "1",
        "report_number": _format_tds_ac_value(booking.certificate_no),
        "sample_number": _format_tds_ac_value(booking.batch_no),
        "sample_received_on": _format_tds_ac_value(_format_report_date(booking.sample_receipt_date)),
        "mfg_date": _format_tds_ac_value(_format_report_date(booking.manufacture_date, month_year_only=True)),
        "exp_date": _format_tds_ac_value(_format_report_date(booking.expiry_retest_date, month_year_only=True)),
        "job_allocation": "QC",
        "testing_start_date": _format_tds_ac_value(_format_report_date(booking.analysis_start_date)),
        "job_allocated_to": "QC",
        "sample_quantity": _format_tds_ac_value(sample_qty),
        "customer_ref": _format_tds_ac_value(booking.customer_sr_no),
        "sample_condition": _format_tds_ac_value(booking.sample_condition),
        "remark": _format_tds_ac_value(booking.remarks, default=""),
        "logo_url": _extract_tds_ac_logo_url(content),
    }

    return (
        '<div class="tds-sample-checklist">'
        '<table class="sample-check-header"><tbody><tr>'
        f'<td class="sample-check-logo" rowspan="2"><img src="{escape(values["logo_url"])}" alt="Ayush Research Laboratories Pvt. Ltd."></td>'
        '<td class="sample-check-lab"><strong>Ayush Research Laboratories Pvt. Ltd.</strong><br>'
        '1st &amp; 2nd Floor, 25, Gokul Das Compound, Industrial Estate Opposite Kalyan Mill<br>Indore MP-452011</td>'
        '</tr><tr><td class="sample-check-title"><strong>CHECKLIST FOR SAMPLE VERIFICATION</strong></td></tr></tbody></table>'
        '<table class="sample-check-meta"><tbody>'
        f'<tr><td>Sample Name : <strong>{escape(values["sample_name"])}</strong></td><td>Page : <strong>{escape(values["page"])}</strong></td></tr>'
        f'<tr><td colspan="2">Report Number : <strong>{escape(values["report_number"])}</strong></td></tr>'
        f'<tr><td>Sample Number : <strong>{escape(values["sample_number"])}</strong></td><td>Sample Received On : <strong>{escape(values["sample_received_on"])}</strong></td></tr>'
        f'<tr><td>Mfg. Date : <strong>{escape(values["mfg_date"])}</strong></td><td>Exp. date : <strong>{escape(values["exp_date"])}</strong></td></tr>'
        '</tbody></table>'
        '<table class="sample-check-allocation"><tbody>'
        f'<tr><td>Job Allocation To Labs :</td><td><strong>{escape(values["job_allocation"])}</strong></td><td>Testing Start Date :</td><td><strong>{escape(values["testing_start_date"])}</strong></td></tr>'
        f'<tr><td>Job Allocated To :</td><td><strong>{escape(values["job_allocated_to"])}</strong></td><td>Sample Quantity :</td><td><strong>{escape(values["sample_quantity"])}</strong></td></tr>'
        f'<tr><td>Customer Ref. :</td><td><strong>{escape(values["customer_ref"])}</strong></td><td>Sample condition :</td><td><strong>{escape(values["sample_condition"])}</strong></td></tr>'
        '</tbody></table>'
        '<table class="sample-check-table"><colgroup>'
        '<col class="sample-check-sr-col"><col class="sample-check-particular-col"><col class="sample-check-yes-col"><col class="sample-check-remark-col">'
        '</colgroup><thead>'
        '<tr><th colspan="4" class="sample-check-section-title">CHECKLIST FOR SAMPLE VERIFICATION</th></tr>'
        '<tr><th>Sr.<br>No.</th><th>Particulars</th><th>Yes/No</th><th>Remark</th></tr>'
        f'</thead><tbody>{checklist_rows}'
        f'<tr><td colspan="4" class="sample-check-remark">Remark: {escape(values["remark"])}</td></tr>'
        '</tbody></table>'
        '<div class="sample-check-sign"><span>Done By</span><span>Reviewed By</span></div>'
        '<div class="sample-check-footer"><strong>Page 1 of 1</strong><strong>QSF/MSP/7.4/F03-00</strong></div>'
        '</div>'
    )


def _build_tds_ac_html(content, booking):
    sample = booking.sample_name if booking.sample_name_id else None
    sample_name = _format_tds_ac_value(sample.display_name if sample else "")
    sample_qty = " ".join(part for part in [booking.sample_qty, booking.uom.name if booking.uom_id else ""] if part)
    lab_value = "QC"
    rows = [
        ("01", "Sheet issued by QA verification"),
        ("02", "Correct Product Code Mentioned/Batch no."),
        ("03", "Correct Pharmacopoeia / Specification No./Version No. referred."),
        ("04", "Correct STP No./Version No. referred."),
        ("05", "All Balance print Outs are correct & available"),
        ("06", "All Id No./Log book entries of instruments correct."),
        ("07", "IS calibrated Instrument used for analysis?"),
        ("08", "Balance log book entries of chemical WS & test correct."),
        ("09", "All Log book entries of HPLC/Column correct."),
        ("10", "Mobile phase Prepared correct."),
        ("11", "Is correct Integration parameters applied during processing?"),
        ("12", "Is system suitability criteria meets with specification."),
        ("13", "Is retention time variation observed?"),
        ("14", "All Calculation sheets verified with respect to reading/area/absorbance etc."),
        ("15", "Any OOS/OOT result found."),
        ("16", "Batch Table, injection volume, oven temp. verified"),
        ("17", "Is all timings correct (Sonication, LOD, Dissolution, Shaking)"),
        ("18", "Is RRT check acquired time match with Std wt. & impurity timing."),
        ("19", "All standard and sample dilution are checked."),
        ("20", "All log books are verified."),
        ("21", "Chemical/Buffer verified."),
        ("22", "All Calculation verified."),
        ("23", "Overwriting cut with sign and date with justification verified"),
        ("24", "LOD Calculation and entry in Log book verified"),
        ("25", "UV/IR sheet, Wavelength, Absorbance, sign, Log book entry verified"),
        ("26", "Standard validity and potency verified"),
        ("27", "All related incident and deviation filled"),
        ("28", "Molarities and standardization of volumetric solution verified."),
        ("29", "Is attached the Audit trial of sample analysis by the analyst or reviewed by reviewer."),
        ("30", "Others"),
    ]
    values = {
        "sample_name": sample_name,
        "page": "1",
        "report_number": _format_tds_ac_value(booking.certificate_no),
        "sample_number": _format_tds_ac_value(booking.batch_no),
        "sample_received_on": _format_tds_ac_value(_format_report_date(booking.sample_receipt_date)),
        "mfg_date": _format_tds_ac_value(_format_report_date(booking.manufacture_date, month_year_only=True)),
        "exp_date": _format_tds_ac_value(_format_report_date(booking.expiry_retest_date, month_year_only=True)),
        "job_allocation": lab_value,
        "date_of_testing": _format_tds_ac_value(_format_report_date(booking.analysis_start_date)),
        "job_allocated_to": lab_value,
        "sample_quantity": _format_tds_ac_value(sample_qty),
        "customer_ref": _format_tds_ac_value(booking.customer_sr_no),
        "sample_condition": _format_tds_ac_value(booking.sample_condition),
        "product_name": sample_name,
        "batch_condition": _format_tds_ac_value(booking.batch_no),
        "logo_url": _extract_tds_ac_logo_url(content),
    }
    checklist_rows = "".join(
        "<tr>"
        f"<td class=\"ac-sr\">{escape(number)}</td>"
        f"<td>{escape(detail)}</td>"
        "<td></td><td></td>"
        "</tr>"
        for number, detail in rows
    )
    return (
        '<div class="tds-ac-document">'
        '<table class="tds-ac-header"><tbody><tr>'
        f'<td class="tds-ac-logo" rowspan="2"><img src="{escape(values["logo_url"])}" alt="Ayush Research Laboratories Pvt. Ltd."></td>'
        '<td class="tds-ac-lab"><strong>Ayush Research Laboratories Pvt. Ltd.</strong><br>'
        '1st &amp; 2nd Floor, 25, Gokul Das Compound, Industrial Estate Opposite Kalyan Mill Indore MP-452011</td>'
        '</tr><tr><td class="tds-ac-title"><strong>CHECKLIST FOR ANALYTICAL DATA REVIEW</strong></td></tr></tbody></table>'
        '<table class="tds-ac-meta"><tbody>'
        f'<tr><td>Sample Name : <strong>{escape(values["sample_name"])}</strong></td><td colspan="2">Page : <strong>{escape(values["page"])}</strong></td></tr>'
        f'<tr><td colspan="3">Report Number : <strong>{escape(values["report_number"])}</strong></td></tr>'
        f'<tr><td>Sample Number : <strong>{escape(values["sample_number"])}</strong></td><td>Sample Received On :</td><td><strong>{escape(values["sample_received_on"])}</strong></td></tr>'
        f'<tr><td>Mfg. Date : <strong>{escape(values["mfg_date"])}</strong></td><td>Exp. date :</td><td><strong>{escape(values["exp_date"])}</strong></td></tr>'
        f'<tr><td>Job Allocation to Lab : <strong>{escape(values["job_allocation"])}</strong></td><td>Date of Testing :</td><td><strong>{escape(values["date_of_testing"])}</strong></td></tr>'
        f'<tr><td>Job Allocated To : <strong>{escape(values["job_allocated_to"])}</strong></td><td>Sample Quantity :</td><td><strong>{escape(values["sample_quantity"])}</strong></td></tr>'
        f'<tr><td>Customer Ref. : <strong>{escape(values["customer_ref"])}</strong></td><td>Sample Condition :</td><td><strong>{escape(values["sample_condition"])}</strong></td></tr>'
        f'<tr><td colspan="3">Product Name : <strong>{escape(values["product_name"])}</strong></td></tr>'
        f'<tr><td colspan="3">Batch No./Condition : <strong>{escape(values["batch_condition"])}</strong></td></tr>'
        '</tbody></table>'
        '<table class="tds-ac-checklist"><colgroup><col class="ac-sr-col"><col><col class="ac-check-col"><col class="ac-check-col"></colgroup>'
        '<thead><tr><th>Sr. No.</th><th>Details to be Checked</th><th>Yes*</th><th>No*</th></tr></thead>'
        f'<tbody>{checklist_rows}</tbody></table>'
        '<p class="tds-ac-note">(* = Tick "&#10004;" mark which is applicable.)</p>'
        '<div class="tds-ac-sign"><span>Done By</span><span>Reviewed By</span></div>'
        '<div class="tds-ac-footer"><strong>Page 1 of 1</strong><strong>QSF|MSP|7.4|F09-00</strong></div>'
        '</div>'
    )


def _render_tds_source_file(template, booking, request, document_type=None):
    source_file = template.source_file
    if not source_file:
        return {"kind": "missing", "content": "", "url": ""}

    suffix = Path(source_file.name or "").suffix.lower()
    url = ""
    try:
        url = source_file.url
    except ValueError:
        url = ""

    if suffix in {".doc", ".docx"} and template.source_preview_file:
        try:
            return {"kind": "pdf", "content": "", "url": template.source_preview_file.url}
        except ValueError:
            return {"kind": "download", "content": "", "url": url}
    if suffix == ".pdf":
        return {"kind": "pdf", "content": "", "url": url}
    if suffix in {".html", ".htm", ".txt"}:
        try:
            source_file.open("rb")
            content = _extract_uploaded_printable_content(source_file)
        except OSError as exc:
            logger.warning("TDS source file missing for template %s and booking %s: %s", template.pk, booking.pk, exc)
            return {
                "kind": "html",
                "content": mark_safe(_tds_render_error_html("Uploaded source file is missing on this server.", str(exc))),
                "url": url,
            }
        except Exception as exc:
            logger.exception("TDS source file render failed for template %s and booking %s", template.pk, booking.pk)
            return {
                "kind": "html",
                "content": mark_safe(_tds_render_error_html("Uploaded source file could not be read.", str(exc))),
                "url": url,
            }
        finally:
            try:
                source_file.close()
            except Exception:
                pass
        return {
            "kind": "html",
            "content": mark_safe(_render_tds_content(content, booking, request, document_type)),
            "url": url,
        }
    if suffix == ".docx":
        return {"kind": "download", "content": "", "url": url}
    return {"kind": "download", "content": "", "url": url}


def _fill_tds_job_order(content, booking):
    sample = booking.sample_name if booking.sample_name_id else None
    sample_qty = " ".join(part for part in [booking.sample_qty, booking.uom.name if booking.uom_id else ""] if part)
    values = {
        "Sample Name": sample.display_name if sample else "",
        "Batch Number": booking.batch_no,
        "Batch No": booking.batch_no,
        "Batch No.": booking.batch_no,
        "Sample Quantity": sample_qty,
        "Storage Condition": booking.sample_condition,
        "Sampling Location": booking.sample_location,
        "Sample Collected by": booking.collected_by_name,
        # The Job Order's Report No field is used as the booking identifier.
        "Report No": booking.tracking_code,
        "ULR No.": "N.A",
        "Sample Receipt Date": _format_report_date(booking.sample_receipt_date),
        "Analysis started on": _format_report_date(booking.analysis_start_date),
        "Analysis completed on": _format_report_date(booking.analysis_end_date),
    }

    for label, value in values.items():
        content = _fill_next_empty_tds_cell(content, label, value)

    content = _ensure_tds_job_order_batch_box(content, booking)

    if sample:
        content = _fill_inline_tds_label(content, "Discipline:", sample.discipline)
        content = _fill_inline_tds_label(content, "Group:", sample.test_group)
        content = _fill_inline_tds_label(content, "Sample Description:", sample.description)

    content = _fill_tds_job_order_tests(content, booking)
    return _mark_tds_job_order_footer_tables(content)


def _ensure_tds_job_order_batch_box(content, booking):
    batch_no = (booking.batch_no or "").strip()
    if not batch_no or re.search(r"Batch\s+(?:No\.?|Number)", content, flags=re.IGNORECASE):
        return content

    table_re = re.compile(r"<table\b[^>]*>.*?</table>", flags=re.IGNORECASE | re.DOTALL)
    row_re = re.compile(r"<tr\b[^>]*>.*?</tr>", flags=re.IGNORECASE | re.DOTALL)

    def replace_table(match):
        table_html = match.group(0)
        if not re.search(r"Sample\s+Name", table_html, flags=re.IGNORECASE):
            return table_html

        first_row = row_re.search(table_html)
        if not first_row:
            return table_html

        batch_row = (
            "<tr>"
            "<td><strong>Batch Number</strong></td>"
            f"<td colspan=\"3\">{escape(batch_no)}</td>"
            "</tr>"
        )
        return table_html[: first_row.end()] + batch_row + table_html[first_row.end() :]

    return table_re.sub(replace_table, content, count=1)


def _fill_tds_ac(content, booking):
    sample = booking.sample_name if booking.sample_name_id else None
    sample_qty = " ".join(part for part in [booking.sample_qty, booking.uom.name if booking.uom_id else ""] if part)
    values = {
        "Sample Name": sample.display_name if sample else "",
        "Page": "1",
        "Report Number": booking.certificate_no,
        "Sample Number": booking.batch_no,
        "Sample Received On": _format_report_date(booking.sample_receipt_date),
        "Mfg. Date": _format_report_date(booking.manufacture_date, month_year_only=True),
        "Exp. date": _format_report_date(booking.expiry_retest_date, month_year_only=True),
        "Job Allocation to Lab": "QC",
        "Date of Testing": _format_report_date(booking.analysis_start_date),
        "Job Allocated To": "QC",
        "Sample Quantity": sample_qty,
        "Customer Ref.": booking.customer_sr_no,
        "Sample Condition": booking.sample_condition,
        "Product Name": sample.display_name if sample else "",
        "Batch No./Condition": " - ".join(part for part in [booking.batch_no, booking.sample_condition] if part),
    }

    for label, value in values.items():
        previous_content = content
        content = _fill_next_empty_tds_cell(content, label, value)
        if content != previous_content:
            continue
        content = _fill_inline_tds_label(content, f"{label} :", value)
        content = _fill_inline_tds_label(content, f"{label}:", value)
    return content


def _fill_tds_sample_checklist(content, booking):
    sample = booking.sample_name if booking.sample_name_id else None
    sample_qty = " ".join(part for part in [booking.sample_qty, booking.uom.name if booking.uom_id else ""] if part)
    received_date = _format_report_date(booking.sample_receipt_date)
    values = (
        ("Sample Name", sample.display_name if sample else ""),
        ("Page", "1"),
        ("Report Number", booking.certificate_no),
        ("Sample Number", booking.batch_no),
        ("Sample Received On", received_date),
        ("Mfg. Date", _format_report_date(booking.manufacture_date, month_year_only=True)),
        ("Exp. date", _format_report_date(booking.expiry_retest_date, month_year_only=True)),
        ("Job Allocation To Labs", "QC"),
        ("Job Allocation To Lab", "QC"),
        ("Testing Start Date", received_date),
        ("Date of Testing", received_date),
        ("Job Allocated To", "QC"),
        ("Sample Quantity", sample_qty),
        ("Customer Ref.", booking.customer_sr_no),
        ("Sample Condition", booking.sample_condition),
        ("Remark", booking.remarks),
    )

    checklist_start = _find_tds_sample_checklist_grid_start(content)
    if checklist_start is None:
        fillable_content = content
        checklist_content = ""
    else:
        fillable_content = content[:checklist_start]
        checklist_content = content[checklist_start:]

    for label, value in values:
        previous_content = fillable_content
        fillable_content = _fill_next_empty_tds_cell(fillable_content, label, value)
        if fillable_content != previous_content:
            continue
        fillable_content = _fill_inline_tds_label(fillable_content, f"{label} :", value)
        fillable_content = _fill_inline_tds_label(fillable_content, f"{label}:", value)
    return _mark_tds_checklist_signature_table(fillable_content + checklist_content)


def _find_tds_sample_checklist_grid_start(content):
    title_re = re.compile(r"CHECKLIST\s+FOR\s+SAMPLE\s+VERIFICATION", flags=re.IGNORECASE)
    for match in reversed(list(title_re.finditer(content))):
        nearby = content[match.start() : match.start() + 2000]
        if re.search(r"Sr\.?\s*(?:<[^>]+>|\s|&nbsp;)*No\.?|Particulars|Yes/No|Remark", nearby, flags=re.IGNORECASE):
            return match.start()
    return None


def _mark_tds_checklist_signature_table(content):
    table_re = re.compile(r"<table\b(?P<attrs>[^>]*)>.*?</table>", flags=re.IGNORECASE | re.DOTALL)

    def add_table_class(table_html, attrs, class_name):
        if re.search(r"\bclass\s*=", attrs, flags=re.IGNORECASE):
            return re.sub(
                r'(\bclass\s*=\s*["\'])([^"\']*)',
                rf"\1\2 {class_name}",
                table_html,
                count=1,
                flags=re.IGNORECASE,
            )
        return table_html.replace("<table", f'<table class="{class_name}"', 1)

    def replace(match):
        table_html = match.group(0)
        attrs = match.group("attrs") or ""
        if re.search(r"Page\s+1\s+of\s+1|QSF", table_html, flags=re.IGNORECASE):
            return add_table_class(table_html, attrs, "tds-check-footer-table")
        if not (
            re.search(r"Done\s+By|Analy[sz]ed\s+By", table_html, flags=re.IGNORECASE)
            and re.search(r"Reviewed\s+By", table_html, flags=re.IGNORECASE)
        ):
            return table_html
        return add_table_class(table_html, attrs, "tds-check-sign-table")

    return table_re.sub(replace, content)


def _mark_tds_job_order_footer_tables(content):
    table_re = re.compile(r"<table\b(?P<attrs>[^>]*)>.*?</table>", flags=re.IGNORECASE | re.DOTALL)
    page_block_re = re.compile(
        r"<(?P<tag>p|div)\b(?P<attrs>[^>]*)>(?P<body>.*?Page\s+1\s+of\s+1.*?)</(?P=tag)>",
        flags=re.IGNORECASE | re.DOTALL,
    )

    def add_class(html, attrs, class_name, tag_name):
        if re.search(r"\bclass\s*=", attrs, flags=re.IGNORECASE):
            return re.sub(
                r'(\bclass\s*=\s*["\'])([^"\']*)',
                rf"\1\2 {class_name}",
                html,
                count=1,
                flags=re.IGNORECASE,
            )
        return html.replace(f"<{tag_name}", f'<{tag_name} class="{class_name}"', 1)

    def replace(match):
        table_html = match.group(0)
        attrs = match.group("attrs") or ""
        if re.search(r"Page\s+1\s+of\s+1|QSF", table_html, flags=re.IGNORECASE):
            return add_class(table_html, attrs, "tds-job-footer-table", "table")
        if (
            re.search(r"Analy[sz]ed\s+By", table_html, flags=re.IGNORECASE)
            and re.search(r"Reviewed\s+By", table_html, flags=re.IGNORECASE)
            and re.search(r"Approved\s+By", table_html, flags=re.IGNORECASE)
        ):
            return add_class(table_html, attrs, "tds-job-sign-table", "table")
        return table_html

    def replace_page_block(match):
        block_html = match.group(0)
        attrs = match.group("attrs") or ""
        return add_class(block_html, attrs, "tds-job-page-marker", match.group("tag").lower())

    content = table_re.sub(replace, content)
    content = page_block_re.sub(replace_page_block, content)
    if re.search(r"\btds-job-footer\b(?!-)", content):
        return content

    signature_re = (
        r'<table\b(?=[^>]*\bclass\s*=\s*["\'][^"\']*\btds-job-sign-table\b)[^>]*>.*?</table>'
    )
    page_re = (
        r'(?:<table\b(?=[^>]*\bclass\s*=\s*["\'][^"\']*\btds-job-footer-table\b)[^>]*>.*?</table>'
        r'|<(?:p|div)\b(?=[^>]*\bclass\s*=\s*["\'][^"\']*\btds-job-page-marker\b)[^>]*>.*?</(?:p|div)>)'
    )
    spacer_re = r'(?:\s|&nbsp;|&#160;|<div\b[^>]*style\s*=\s*["\'][^"\']*(?:min-height|height)[^"\']*["\'][^>]*>.*?</div>)*'
    footer_re = re.compile(
        rf'(?P<signature>{signature_re})(?P<spacer>{spacer_re})(?P<page>{page_re})',
        flags=re.IGNORECASE | re.DOTALL,
    )
    return footer_re.sub(
        r'<div class="tds-job-footer">\g<signature>\g<spacer>\g<page></div>',
        content,
        count=1,
    )


def _strip_tds_job_order_empty_tables(content):
    """Remove blank table placeholders left in a Job Order master template."""
    table_re = re.compile(r"<table\b[^>]*>.*?</table>", flags=re.IGNORECASE | re.DOTALL)

    def replace(match):
        table_html = match.group(0)
        if re.search(r"<(?:img|svg|canvas)\b", table_html, flags=re.IGNORECASE):
            return table_html
        visible_text = unescape(re.sub(r"<[^>]+>", " ", table_html)).replace("\xa0", " ")
        return "" if not visible_text.strip() else table_html

    return table_re.sub(replace, content)


def _fill_next_empty_tds_cell(content, label, value):
    if not value:
        return content

    row_re = re.compile(r"<tr\b[^>]*>.*?</tr>", flags=re.IGNORECASE | re.DOTALL)
    cell_re = re.compile(r"<t[dh]\b[^>]*>.*?</t[dh]>", flags=re.IGNORECASE | re.DOTALL)
    empty_cell_re = re.compile(r"<td\b(?P<value_attrs>[^>]*)>(?:\s|&nbsp;|&#160;|<br\s*/?>)*</td>", flags=re.IGNORECASE)
    replaced = False

    def normalize_label(text):
        text = unescape(strip_tags(text)).replace("\xa0", " ")
        text = re.sub(r"\s+", " ", text).strip()
        return re.sub(r"[\s:.]+$", "", text).casefold()

    expected_label = normalize_label(label)

    def replace_row(match):
        nonlocal replaced
        row_html = match.group(0)
        if replaced:
            return row_html

        label_cell = None
        for candidate in cell_re.finditer(row_html):
            if normalize_label(candidate.group(0)) == expected_label:
                label_cell = candidate
                break

        if not label_cell:
            return row_html

        empty_match = None
        for candidate in empty_cell_re.finditer(row_html):
            if candidate.start() > label_cell.end():
                empty_match = candidate
                break
        if not empty_match:
            return row_html

        attrs = empty_match.group("value_attrs") or ""
        replaced = True
        return row_html[: empty_match.start()] + f"<td{attrs}>{escape(value)}</td>" + row_html[empty_match.end() :]

    return row_re.sub(replace_row, content)


def _fill_inline_tds_label(content, label, value):
    if not value:
        return content
    pattern = rf"({re.escape(label)}(?:\s|&nbsp;|&#160;)*)"
    return re.sub(pattern, lambda match: f"{match.group(1)}{escape(value)} ", content, count=1, flags=re.IGNORECASE)


def _fill_tds_job_order_tests(content, booking):
    tests = list(booking.test_to_be_performed.order_by("name"))
    if not tests:
        return content

    table_re = re.compile(r"<table\b[^>]*>.*?</table>", flags=re.IGNORECASE | re.DOTALL)
    row_re = re.compile(r"<tr\b[^>]*>.*?</tr>", flags=re.IGNORECASE | re.DOTALL)
    replaced_table = False

    def has_meaningful_text(html):
        text = re.sub(r"<[^>]+>", " ", html)
        text = text.replace("&nbsp;", " ").replace("&#160;", " ")
        return bool(re.sub(r"\s+", " ", text).strip())

    def build_rows(template_row):
        cells = re.findall(r"<td\b(?P<attrs>[^>]*)>.*?</td>", template_row, flags=re.IGNORECASE | re.DOTALL)
        attrs = [cell_attrs for cell_attrs in cells[:4]]
        while len(attrs) < 4:
            attrs.append("")

        rows = []
        for index, test in enumerate(tests, start=1):
            rows.append(
                '<tr class="tds-job-test-row">'
                f"<td{attrs[0]} style=\"text-align: center;\">{index}</td>"
                f"<td{attrs[1]}>{escape(test.name)}</td>"
                f"<td{attrs[2]}></td>"
                f"<td{attrs[3]}></td>"
                "</tr>"
            )
        return "".join(rows)

    def replace_table(match):
        nonlocal replaced_table
        table_html = match.group(0)
        if replaced_table:
            return table_html
        if not re.search(r"Sr\.\s*No\.|Test\s*Parameter", table_html, flags=re.IGNORECASE):
            return table_html

        rows = list(row_re.finditer(table_html))
        if not rows:
            return table_html

        header_index = next(
            (
                index
                for index, row in enumerate(rows)
                if re.search(r"Sr\.\s*No\.|Test\s*Parameter", row.group(0), flags=re.IGNORECASE)
            ),
            None,
        )
        if header_index is None:
            return table_html

        insert_after = rows[header_index]
        body_rows_start = insert_after.end()
        body_rows_end = body_rows_start
        template_row = rows[header_index + 1].group(0) if header_index + 1 < len(rows) else "<tr><td></td><td></td><td></td><td></td></tr>"

        for row in rows[header_index + 1:]:
            row_html = row.group(0)
            if has_meaningful_text(row_html):
                break
            body_rows_end = row.end()

        replaced_table = True
        rendered_table = table_html[:body_rows_start] + build_rows(template_row) + table_html[body_rows_end:]
        if re.search(r"\bclass\s*=", rendered_table, flags=re.IGNORECASE):
            return re.sub(
                r'(\bclass\s*=\s*["\'])([^"\']*)',
                r"\1\2 tds-job-tests",
                rendered_table,
                count=1,
                flags=re.IGNORECASE,
            )
        return rendered_table.replace("<table", '<table class="tds-job-tests"', 1)

    return table_re.sub(replace_table, content)


def _unwrap_tds_outer_table(content):
    wrapper_re = re.compile(
        r"^\s*<table\b(?P<table_attrs>[^>]*)>\s*"
        r"(?:<colgroup>.*?</colgroup>\s*)?"
        r"<tbody>\s*<tr\b[^>]*>\s*<td\b(?P<td_attrs>[^>]*)>\s*"
        r"(?P<body>.*)"
        r"\s*</td>\s*</tr>\s*</tbody>\s*</table>\s*$",
        flags=re.IGNORECASE | re.DOTALL,
    )
    match = wrapper_re.match(content)
    if not match:
        return content

    # A real form can start with one wide cell and add more rows below it.
    # Only unwrap a genuine one-cell editor wrapper, never a multi-row form.
    first_row_end = re.search(r"</tr\s*>", content, flags=re.IGNORECASE)
    if not first_row_end:
        return content
    first_row = content[: first_row_end.end()]
    if (
        len(re.findall(r"<tr\b", content, flags=re.IGNORECASE)) != 1
        or len(re.findall(r"<td\b", content, flags=re.IGNORECASE)) != 1
        or len(re.findall(r"<td\b", first_row, flags=re.IGNORECASE)) != 1
    ):
        return content

    table_attrs = match.group("table_attrs") or ""
    td_attrs = match.group("td_attrs") or ""
    is_borderless = re.search(r'\bborder\s*=\s*["\']?0\b', table_attrs, flags=re.IGNORECASE) or not re.search(
        r"border-width\s*:", table_attrs + td_attrs, flags=re.IGNORECASE
    )
    if not is_borderless:
        return content
    return match.group("body").strip()


def _strip_tds_trailing_empty_blocks(content):
    empty_block = r"<(p|div|span)[^>]*>(?:\s|&nbsp;|<br\s*/?>)*</\1>"
    empty_pre = r"<pre[^>]*>(?:\s|&nbsp;|<br\s*/?>|<[^>]+>)*</pre>"
    content = re.sub(rf"(?:\s*{empty_pre})+\s*$", "", content, flags=re.IGNORECASE)
    content = re.sub(rf"(?:\s*{empty_block})+\s*$", "", content, flags=re.IGNORECASE)

    trailing_node_re = re.compile(
        r"<(?P<tag>p|div|pre|table)\b[^>]*>(?P<body>.*?)</(?P=tag)>\s*$",
        flags=re.IGNORECASE | re.DOTALL,
    )
    while match := trailing_node_re.search(content):
        visible_text = unescape(strip_tags(match.group("body"))).replace("\xa0", " ")
        if visible_text.strip():
            break
        content = content[: match.start()].rstrip()
    return content


def _clean_tds_legacy_footer(content):
    """Replace legacy spacer-based AC and Checklist footers with a compact footer."""
    content = re.sub(r"<table\b[^>]*>\s*</table>", "", content, flags=re.IGNORECASE)
    content = re.sub(
        r"<div\b[^>]*style=[\"'][^\"']*\bheight\s*:\s*(?:[1-9]\d{2,}|[2-9]\d)px[^\"']*[\"'][^>]*>.*?</div>",
        "",
        content,
        flags=re.IGNORECASE | re.DOTALL,
    )

    def replace_legacy_footer(match):
        footer_text = unescape(strip_tags(match.group(0))).replace("\xa0", " ")
        code_match = re.search(r"QSF\s*[|/]\s*MSP\s*[|/]\s*7[.]4\s*[|/]\s*F09-00", footer_text, re.IGNORECASE)
        footer_code = re.sub(r"\s*[|/]\s*", "/", code_match.group(0)) if code_match else "QSF/MSP/7.4/F09-00"
        return (
            '<div class="tds-compact-footer">'
            '<span></span><strong>Page 1 of 1</strong>'
            f'<strong>{escape(footer_code)}</strong></div>'
        )

    return re.sub(
        r"<pre\b[^>]*>.*?Page\s+1\s+of\s+1.*?</pre>",
        replace_legacy_footer,
        content,
        count=1,
        flags=re.IGNORECASE | re.DOTALL,
    )


def _position_tds_ads_signature_line(content):
    """Anchor the Assay-by-HPLC signature line to the bottom of its bordered form."""
    signature_re = re.compile(r"<p\b(?P<attrs>[^>]*)>(?P<body>.*?)</p>", flags=re.IGNORECASE | re.DOTALL)

    def mark_signature(match):
        body = match.group("body")
        text = strip_tags(body).lower()
        if "analyzed by" not in text or "reviewed by" not in text:
            return match.group(0)
        attrs = match.group("attrs") or ""
        if re.search(r"\bclass\s*=", attrs, flags=re.IGNORECASE):
            attrs = re.sub(
                r'(\bclass\s*=\s*["\'])([^"\']*)',
                r"\1\2 tds-ads-signature-line",
                attrs,
                count=1,
                flags=re.IGNORECASE,
            )
        else:
            attrs += ' class="tds-ads-signature-line"'
        return f"<p{attrs}>{body}</p>"

    content = signature_re.sub(mark_signature, content)
    table_tag_re = re.compile(r"</?table\b[^>]*>", flags=re.IGNORECASE)
    open_tables = []
    for table_tag in table_tag_re.finditer(content):
        if table_tag.group(0).lower().startswith("<table"):
            open_tables.append(table_tag)
            continue
        if not open_tables:
            continue
        opening_tag = open_tables.pop()
        table_html = content[opening_tag.start() : table_tag.end()]
        if "tds-ads-signature-line" not in table_html:
            continue
        opening_html = opening_tag.group(0)
        if re.search(r"\bclass\s*=", opening_html, flags=re.IGNORECASE):
            opening_html = re.sub(
                r'(\bclass\s*=\s*["\'])([^"\']*)',
                r"\1\2 tds-ads-signature-container",
                opening_html,
                count=1,
                flags=re.IGNORECASE,
            )
        else:
            opening_html = opening_html[:-1] + ' class="tds-ads-signature-container">'
        return content[: opening_tag.start()] + opening_html + content[opening_tag.end() :]
    return content


def _fill_tds_booking_labels(content, booking):
    sample_name = booking.sample_name.name if booking.sample_name_id else ""
    batch_no = booking.batch_no or ""
    sample_qty = " ".join(part for part in [booking.sample_qty, booking.uom.name if booking.uom_id else ""] if part)
    replacements = (
        ("Sample Name", sample_name),
        ("Sample Number", batch_no),
        ("Batch No.", batch_no),
        ("Batch No", batch_no),
        ("Sample Quantity", sample_qty),
        ("Storage Condition", booking.sample_condition),
        ("Sampling Location", booking.sample_location),
        ("Sample Collected by", booking.collected_by_name),
        ("Report No", booking.certificate_no),
        ("ULR No.", "N.A"),
        ("Sample Receipt Date", _format_report_date(booking.sample_receipt_date)),
        ("Analysis started on", _format_report_date(booking.analysis_start_date)),
        ("Analysis completed on", _format_report_date(booking.analysis_end_date)),
    )

    for label, value in replacements:
        if not value:
            continue
        content = re.sub(
            rf"({label}\s*:\s*)(?=(?:&nbsp;|\s|</(?:td|th|p|div|span|strong|b)>|<br\s*/?>))",
            rf"\g<1>{escape(value)}",
            content,
            count=1,
            flags=re.IGNORECASE,
        )
        label_pattern = re.escape(label).replace(r"\ ", r"\s+")
        content = re.sub(
            rf"(<t[dh]\b[^>]*>\s*(?:<[^>]+>\s*)*{label_pattern}\s*:?\s*(?:</[^>]+>\s*)*</t[dh]>\s*<t[dh]\b[^>]*>)(?:\s|&nbsp;|<br\s*/?>|<p\b[^>]*>(?:\s|&nbsp;|<br\s*/?>)*</p>)*(</t[dh]>)",
            rf"\g<1>{escape(value)}\g<2>",
            content,
            count=1,
            flags=re.IGNORECASE,
        )
    return content


def _fill_tds_trf_row_value(content, label, value):
    """Replace the value cell beside an exact label in the TRF template."""
    row_re = re.compile(r"<tr\b[^>]*>.*?</tr>", flags=re.IGNORECASE | re.DOTALL)
    cell_re = re.compile(
        r"<(?P<tag>t[dh])\b(?P<attrs>[^>]*)>.*?</(?P=tag)>", flags=re.IGNORECASE | re.DOTALL
    )

    def normalize_label(text):
        text = unescape(strip_tags(text)).replace("\xa0", " ")
        text = re.sub(r"\s+", " ", text).strip()
        return re.sub(r"[\s:.]+$", "", text).casefold()

    expected_label = normalize_label(label)

    def replace_row(match):
        row_html = match.group(0)
        cells = list(cell_re.finditer(row_html))
        for index, cell in enumerate(cells[:-1]):
            if normalize_label(cell.group(0)) != expected_label:
                continue
            value_cell = cells[index + 1]
            tag = value_cell.group("tag")
            attrs = value_cell.group("attrs") or ""
            replacement = f"<{tag}{attrs}>{escape(value or '')}</{tag}>"
            return row_html[: value_cell.start()] + replacement + row_html[value_cell.end() :]
        return row_html

    return row_re.sub(replace_row, content)


class ReportListView(PermissionRequiredMixin, RoleRequiredMixin, ListView):
    permission_required = "reports.view_report"
    required_roles = ("Manager", "Incharge", "Analyst", "Admin")
    model = Report
    template_name = "reports/report_list.html"
    context_object_name = "reports"
    paginate_by = 10

    def get_queryset(self):
        existing_booking_ids = Report.objects.values_list("booking_id", flat=True)
        missing_approved_bookings = Booking.objects.filter(status=Booking.Status.APPROVED).exclude(
            pk__in=existing_booking_ids
        )
        if missing_approved_bookings.exists():
            Report.objects.bulk_create(
                [Report(booking=booking, created_by=booking.approved_by or booking.created_by) for booking in missing_approved_bookings]
            )

        qs = Report.objects.select_related(
            "booking",
            "booking__customer",
            "booking__sample_name",
            "manager",
            "incharge",
            "updated_by",
        ).order_by("-created_at")
        search = self.request.GET.get("q", "").strip()
        search_by = self.request.GET.get("search_by", "sample_reg").strip()
        status_filter = self.request.GET.get("status", "").strip()
        customer_filter = self.request.GET.get("customer", "").strip()

        if status_filter == Report.FinalOutcome.PASS:
            qs = qs.filter(final_outcome=Report.FinalOutcome.PASS)
        elif status_filter == Report.FinalOutcome.DRAFT:
            qs = qs.filter(final_outcome=Report.FinalOutcome.DRAFT)

        if customer_filter:
            qs = qs.filter(booking__customer_id=customer_filter)

        if search:
            if search_by == "booking_id":
                qs = qs.filter(booking__tracking_code__icontains=search)
            elif search_by == "batch_no":
                qs = qs.filter(booking__batch_no__icontains=search)
            elif search_by == "customer":
                qs = qs.filter(booking__customer__name__icontains=search)
            elif search_by == "sample":
                qs = qs.filter(booking__sample_name__name__icontains=search)
            else:
                qs = qs.filter(booking__sample_reg_no__icontains=search)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["search_query"] = self.request.GET.get("q", "").strip()
        context["search_by"] = self.request.GET.get("search_by", "sample_reg").strip()
        context["status_filter"] = self.request.GET.get("status", "").strip()
        context["customer_filter"] = self.request.GET.get("customer", "").strip()
        context["customer_options"] = (
            Booking.objects.select_related("customer")
            .filter(customer__isnull=False)
            .values_list("customer_id", "customer__name")
            .distinct()
            .order_by("customer__name")
        )
        context["show_saved_popup"] = self.request.GET.get("saved") == "1"
        context["saved_booking_id"] = self.request.GET.get("booking_id", "").strip()
        if context.get("is_paginated"):
            context["page_numbers"] = context["page_obj"].paginator.get_elided_page_range(
                context["page_obj"].number,
                on_each_side=2,
                on_ends=1,
            )
        return context


class TDSDocumentTemplateListView(PermissionRequiredMixin, RoleRequiredMixin, ListView):
    permission_required = "reports.view_tdsdocumenttemplate"
    required_roles = ("Admin", "Manager", "Analyst")
    model = TDSDocumentTemplate
    template_name = "reports/tds/template_list.html"
    context_object_name = "templates"

    def get_queryset(self):
        qs = TDSDocumentTemplate.objects.select_related("test").order_by("document_type", "test__name", "name")
        document_type = self.request.GET.get("type", "").strip()
        if document_type:
            qs = qs.filter(document_type=document_type)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["document_types"] = TDSDocumentTemplate.DocumentType.choices
        context["selected_type"] = self.request.GET.get("type", "").strip()
        return context


class TDSDocumentTemplateCreateView(PermissionRequiredMixin, RoleRequiredMixin, CreateView):
    permission_required = "reports.add_tdsdocumenttemplate"
    required_roles = ("Admin", "Manager")
    model = TDSDocumentTemplate
    form_class = TDSDocumentTemplateForm
    template_name = "reports/tds/template_form.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Add TDS Template"
        return context

    def get_success_url(self):
        messages.success(self.request, "TDS template added.")
        return reverse("reports:tds_template_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        self._generate_preview_if_needed()
        return response

    def _generate_preview_if_needed(self):
        if self.object.display_mode != TDSDocumentTemplate.DisplayMode.SOURCE_FILE:
            return
        ok, message = self.object.generate_source_preview()
        if ok:
            self.object.save(update_fields=["source_preview_file", "updated_at"])
        else:
            messages.warning(self.request, message)


class TDSDocumentTemplateExtractView(PermissionRequiredMixin, RoleRequiredMixin, View):
    permission_required = "reports.add_tdsdocumenttemplate"
    required_roles = ("Admin", "Manager")

    def has_permission(self):
        return self.request.user.has_perm("reports.add_tdsdocumenttemplate") or self.request.user.has_perm(
            "reports.change_tdsdocumenttemplate"
        )

    def post(self, request, *args, **kwargs):
        uploaded_file = request.FILES.get("source_file")
        if not uploaded_file:
            return JsonResponse({"error": "Please choose a DOCX, HTML, or TXT file."}, status=400)

        content = _extract_uploaded_printable_content(uploaded_file)
        if not content:
            return JsonResponse(
                {
                    "error": (
                        "Could not read editable content from this file. "
                        "Use .docx, .html, or .txt; PDF/DOC can only be stored as source files."
                    )
                },
                status=400,
            )
        return JsonResponse({"content": content})


class TDSDocumentTemplateUpdateView(PermissionRequiredMixin, RoleRequiredMixin, UpdateView):
    permission_required = "reports.change_tdsdocumenttemplate"
    required_roles = ("Admin", "Manager")
    model = TDSDocumentTemplate
    form_class = TDSDocumentTemplateForm
    template_name = "reports/tds/template_form.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Edit TDS Template"
        return context

    def get_success_url(self):
        messages.success(self.request, "TDS template updated.")
        return reverse("reports:tds_template_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        self._generate_preview_if_needed()
        return response

    def _generate_preview_if_needed(self):
        if self.object.display_mode != TDSDocumentTemplate.DisplayMode.SOURCE_FILE:
            return
        ok, message = self.object.generate_source_preview()
        if ok:
            self.object.save(update_fields=["source_preview_file", "updated_at"])
        else:
            messages.warning(self.request, message)


class TDSDocumentTemplateDeleteView(PermissionRequiredMixin, RoleRequiredMixin, DeleteView):
    permission_required = "reports.delete_tdsdocumenttemplate"
    required_roles = ("Admin", "Manager")
    model = TDSDocumentTemplate
    template_name = "reports/tds/template_confirm_delete.html"

    def get_success_url(self):
        messages.success(self.request, "TDS template deleted.")
        return reverse("reports:tds_template_list")


class BookingTDSDocumentView(PermissionRequiredMixin, RoleRequiredMixin, TemplateView):
    permission_required = "bookings.view_booking"
    required_roles = ("Checked By", "Manager", "Incharge", "Analyst", "Admin")
    template_name = "reports/tds/booking_document.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        booking = get_object_or_404(
            Booking.objects.select_related(
                "customer",
                "submitter",
                "manufacturer",
                "sample_name",
                "protocol",
                "uom",
            ).prefetch_related("test_to_be_performed__report_template"),
            pk=self.kwargs["booking_pk"],
        )
        document_type = self.kwargs["document_type"]
        valid_types = dict(TDSDocumentTemplate.DocumentType.choices)
        if document_type not in valid_types:
            raise Http404("Unknown TDS document type.")

        selected_tests = list(booking.test_to_be_performed.select_related("report_template").order_by("name"))
        common_ads_header = ""
        common_ads_footer = ""
        if document_type == TDSDocumentTemplate.DocumentType.ADS:
            common_ads_templates = list(
                TDSDocumentTemplate.objects.filter(
                    document_type=document_type,
                    is_active=True,
                    test__isnull=True,
                ).order_by("name")
            )
            for template in common_ads_templates:
                if not common_ads_header and template.header_content:
                    common_ads_header = mark_safe(_render_tds_template_fragment(template.header_content, booking, self.request))
                if not common_ads_footer and template.footer_content:
                    common_ads_footer = mark_safe(_render_tds_template_fragment(template.footer_content, booking, self.request))
                if common_ads_header and common_ads_footer:
                    break

            template_qs = TDSDocumentTemplate.objects.filter(
                document_type=document_type,
                is_active=True,
                test__in=selected_tests,
            ).select_related("test").order_by("test__name", "name")
        else:
            template_qs = TDSDocumentTemplate.objects.filter(
                document_type=document_type,
                is_active=True,
                test__isnull=True,
            ).select_related("test").order_by("name")

        rendered_templates = []
        for template in template_qs:
            use_source_file = template.display_mode == TDSDocumentTemplate.DisplayMode.SOURCE_FILE
            source_preview = _render_tds_source_file(template, booking, self.request, document_type) if use_source_file else None
            # Determine whether this template explicitly requests booking
            # injection via query param or an inline marker in its editable
            # content/header/footer.
            marker = "[[inject_booking]]"
            template_marker_present = any(
                marker.lower() in (getattr(template, attr) or "").lower()
                for attr in ("content", "header_content", "footer_content")
            )
            inject_for_template = bool(self.request.GET.get("inject_booking") == "1" or template_marker_present)

            content = "" if use_source_file else _render_tds_content(
                template.content, booking, self.request, document_type, inject_booking=inject_for_template
            )
            header_content = _render_tds_template_fragment(
                template.header_content, booking, self.request, inject_booking=inject_for_template
            )
            footer_content = _render_tds_template_fragment(
                template.footer_content, booking, self.request, inject_booking=inject_for_template
            )
            pages = []
            if not use_source_file:
                content = content.replace("[[page_number]]", '<span class="tds-page-current"></span>')
                content = content.replace("[[total_pages]]", '<span class="tds-page-total"></span>')
                split_pages = _split_tds_rendered_pages(content)
                if document_type == TDSDocumentTemplate.DocumentType.ADS:
                    pages = [mark_safe(page) for page in split_pages]
                else:
                    total_pages = len(split_pages)
                    pages = [
                        {
                            "content": mark_safe(_fill_tds_page_placeholders(page, index, total_pages)),
                            "header_content": mark_safe(_fill_tds_page_placeholders(header_content, index, total_pages)),
                            "footer_content": mark_safe(_fill_tds_page_placeholders(footer_content, index, total_pages)),
                        }
                        for index, page in enumerate(split_pages, start=1)
                    ]
            rendered_templates.append(
                {
                    "template": template,
                    "test": template.test,
                    "header_content": mark_safe(header_content),
                    "content": "" if use_source_file else mark_safe(content),
                    "pages": pages,
                    "footer_content": mark_safe(footer_content),
                    "use_source_file": use_source_file,
                    "source_preview": source_preview,
                }
            )

        fallback_ads_templates = []
        if document_type == TDSDocumentTemplate.DocumentType.ADS:
            matched_test_ids = {item["test"].pk for item in rendered_templates if item["test"]}
            for test in selected_tests:
                if test.pk in matched_test_ids:
                    continue
                report_template = getattr(test, "report_template", None)
                if report_template and report_template.is_active and report_template.content.strip():
                    # Respect inline marker on report_template as well.
                    marker = "[[inject_booking]]"
                    template_marker_present = marker.lower() in (report_template.content or "").lower()
                    inject_for_template = bool(self.request.GET.get("inject_booking") == "1" or template_marker_present)
                    content = _render_tds_content(report_template.content, booking, self.request, document_type, inject_booking=inject_for_template)
                    fallback_ads_templates.append(
                        {
                            "template": report_template,
                            "test": test,
                            "header_content": "",
                            "content": mark_safe(content),
                            "pages": [mark_safe(page) for page in _split_tds_rendered_pages(content)],
                            "footer_content": "",
                        }
                    )

        ads_print_pages = []
        if document_type == TDSDocumentTemplate.DocumentType.ADS:
            page_groups = []

            for item in rendered_templates:
                if item["use_source_file"]:
                    source_preview = item["source_preview"] or {}
                    if source_preview.get("kind") == "html":
                        pages = _split_tds_rendered_pages(source_preview.get("content") or "")
                    else:
                        pages = [""]
                else:
                    pages = item["pages"]

                header = item["header_content"] or common_ads_header
                footer = item["footer_content"] or common_ads_footer
                for page in pages:
                    page_groups.append(
                        {
                            "item": item,
                            "tds_template_pk": item["template"].pk,
                            "header": header,
                            "content": page,
                            "footer": footer,
                            "source_preview": item["source_preview"] if item["use_source_file"] else None,
                        }
                    )

            for item in fallback_ads_templates:
                for page in item["pages"]:
                    page_groups.append(
                        {
                            "item": item,
                            "tds_template_pk": None,
                            "header": common_ads_header,
                            "content": page,
                            "footer": common_ads_footer,
                            "source_preview": None,
                        }
                    )

            total_pages = len(page_groups)
            ads_print_pages = []
            for index, group in enumerate(page_groups, start=1):
                # HPLC ADS headers place the page number below their bottom rule.
                # Do not add a second copy to the footer when a template already
                # provides it in either the header or footer.
                header_content = group["header"]
                footer_content = group["footer"]
                has_page_number = (
                    "tds-page-current" in header_content
                    or "tds-page-total" in header_content
                    or "tds-page-current" in footer_content
                    or "tds-page-total" in footer_content
                )
                if not has_page_number:
                    footer_content = _ensure_tds_page_number(footer_content)

                ads_print_pages.append(
                    {
                        "item": group["item"],
                        "tds_template_pk": group["tds_template_pk"],
                        "header": mark_safe(_fill_tds_page_placeholders(header_content, index, total_pages)),
                        "content": mark_safe(_fill_tds_page_placeholders(group["content"], index, total_pages)),
                        "footer": mark_safe(_fill_tds_page_placeholders(footer_content, index, total_pages)),
                        "page_number": index,
                        "total_pages": total_pages,
                        "source_preview": group["source_preview"],
                    }
                )

        context.update(
            {
                "booking": booking,
                "document_type": document_type,
                "document_title": valid_types[document_type],
                "selected_tests": selected_tests,
                "rendered_templates": rendered_templates,
                "fallback_ads_templates": fallback_ads_templates,
                "ads_print_pages": ads_print_pages,
                "common_ads_header": common_ads_header,
                "common_ads_footer": common_ads_footer,
                "print_mode": self.request.GET.get("print") == "1" or document_type == TDSDocumentTemplate.DocumentType.AC,
                "auto_print": self.request.GET.get("print") == "1" or self.request.GET.get("autoprint") == "1",
                "can_edit_tds_template": self.request.user.has_perm("reports.change_tdsdocumenttemplate"),
            }
        )
        return context


class ReportCreateOrUpdateView(PermissionRequiredMixin, RoleRequiredMixin, UpdateView):
    permission_required = "reports.change_report"
    required_roles = ("Checked By",)
    allow_staff = False
    model = Report
    form_class = ReportApprovalForm
    template_name = "reports/report_approval.html"

    def get_object(self, queryset=None):
        booking = get_object_or_404(Booking, pk=self.kwargs["booking_pk"])
        if booking.status != Booking.Status.APPROVED:
            booking.approve(self.request.user)
        report, _ = Report.objects.get_or_create(booking=booking, defaults={"created_by": self.request.user})
        return report

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        booking = self.object.booking
        tests = booking.test_to_be_performed.select_related("report_template").order_by("name")
        
        tests_with_templates = []
        tests_without_templates = []
        
        for test in tests:
            template = getattr(test, "report_template", None)
            if template and template.is_active:
                tests_with_templates.append((test.name, template.name))
            else:
                tests_without_templates.append(test.name)
        
        context["tests_info"] = {
            "with_templates": tests_with_templates,
            "without_templates": tests_without_templates,
        }
        return context

    def form_valid(self, form):
        if not (self.request.user.is_superuser or has_role(self.request.user, "Checked By")):
            messages.error(self.request, "Only Checked By can approve report workflow.")
            return self.form_invalid(form)

        report = form.save(commit=False)
        analysis_start_date = form.cleaned_data.get("analysis_start_date")
        analysis_end_date = form.cleaned_data.get("analysis_end_date")
        incharge_user = form.cleaned_data.get("incharge_user")
        if not incharge_user:
            UserModel = get_user_model()
            incharge_user = (
                UserModel.objects.filter(is_active=True, groups__name="Incharge")
                .order_by("first_name", "last_name", "username")
                .first()
            )

        def _to_day_start(value):
            if not value:
                return None
            dt = datetime.combine(value, time.min)
            return timezone.make_aware(dt, timezone.get_current_timezone()) if timezone.is_naive(dt) else dt

        analysis_start_date = _to_day_start(analysis_start_date)
        analysis_end_date = _to_day_start(analysis_end_date)

        report.booking.analysis_start_date = analysis_start_date
        report.booking.analysis_end_date = analysis_end_date
        report.booking.updated_by = self.request.user
        report.booking.save(update_fields=["analysis_start_date", "analysis_end_date", "updated_by", "updated_at"])
        report.analysis_end_date = analysis_end_date
        report.updated_by = self.request.user
        report.save(update_fields=["analysis_end_date", "updated_by", "updated_at"])
        report.approve_by_manager(self.request.user, incharge_user=incharge_user)
        messages.success(self.request, "Report approved by Checked By.")
        if self.request.user.is_superuser or any(
            has_role(self.request.user, role) for role in ("Manager", "Incharge", "Analyst", "Admin")
        ):
            return redirect("reports:coa_edit", pk=report.pk)
        return redirect("bookings:list")


class COAEditView(PermissionRequiredMixin, RoleRequiredMixin, UpdateView):
    permission_required = "reports.change_report"
    required_roles = ("Manager", "Incharge", "Analyst", "Admin")
    model = Report
    form_class = COAEditForm
    template_name = "reports/coa_edit.html"

    def dispatch(self, request, *args, **kwargs):
        self.object = self.get_object()
        allowed_statuses = {
            Report.Status.MANAGER_APPROVED,
            Report.Status.INCHARGE_APPROVED,
        }
        if self.object.status not in allowed_statuses:
            messages.error(request, "COA can be edited only after report approval.")
            return redirect("reports:approval", booking_pk=self.object.booking_id)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        templates = ReportTemplate.objects.filter(is_active=True).select_related("sample_name", "protocol")
        previous_reports = Report.objects.none()
        sample_name_id = getattr(self.object.booking, "sample_name_id", None)
        customer_id = getattr(self.object.booking, "customer_id", None)
        if sample_name_id and customer_id:
            previous_reports = (
                Report.objects.select_related("booking")
                .filter(
                    booking__sample_name_id=sample_name_id,
                    booking__customer_id=customer_id,
                )
                .exclude(pk=self.object.pk)
                .exclude(ceo_content="")
                .order_by("-updated_at", "-created_at")
            )
        context["remark_options"] = list(
            ReportRemark.objects.filter(is_active=True).values("id", "title", "content")
        )
        context["template_options"] = [
            {
                "id": template.pk,
                "name": template.name,
                "sample_name": template.sample_name.display_name if template.sample_name else "",
                "protocol": template.protocol.name if template.protocol else "",
            }
            for template in templates
        ]
        context["selected_test_templates"] = [
            {
                "test_name": test.name,
                "template_name": test.report_template.name,
            }
            for test in self.object.booking.test_to_be_performed.select_related("report_template").filter(
                report_template__isnull=False,
                report_template__is_active=True,
            ).order_by("name")
        ]
        context["tests_with_templates"] = self.object.tests_with_templates
        context["tests_without_templates"] = self.object.tests_without_templates
        context["generic_tests_table_html"] = self.object.generic_tests_table_html
        context["all_tests_grouped"] = {
            "with_templates": list(self.object.tests_with_templates),
            "without_templates": list(self.object.tests_without_templates),
        }
        context["old_report_options"] = [
            {
                "id": report.pk,
                "sample_name": report.booking.sample_name.display_name if report.booking.sample_name else "",
                "customer_name": report.booking.customer.name if report.booking.customer else "",
                "batch_no": report.booking.batch_no or "",
                "tracking_code": report.booking.tracking_code,
                "sample_reg_no": report.booking.sample_registration_no,
                "certificate_no": report.certificate_no,
                "updated_at": timezone.localtime(report.updated_at).strftime("%d/%m/%Y %I:%M %p")
                if timezone.is_aware(report.updated_at)
                else report.updated_at.strftime("%d/%m/%Y %I:%M %p"),
            }
            for report in previous_reports[:20]
        ]
        return context

    def get_success_url(self):
        return (
            f"{reverse('reports:list')}?saved=1&booking_id={self.object.booking.tracking_code}"
        )

    def form_valid(self, form):
        form.instance.updated_by = self.request.user
        return super().form_valid(form)


class COAPrintView(PermissionRequiredMixin, RoleRequiredMixin, DetailView):
    permission_required = "reports.view_report"
    required_roles = ("Manager", "Incharge", "Analyst", "Admin")
    model = Report
    template_name = "reports/coa_print.html"
    context_object_name = "report"

    def get_context_data(self, **kwargs):
        q = self.request.GET
        context = _get_report_render_context(
            self.object,
            self.request,
            preview_mode=True,
            auto_print=q.get("autoprint") == "1",
            is_plain_doc=q.get("plain") == "1",
            is_test_report=q.get("doc") == "test",
        )
        context["is_letterhead"] = q.get("letterhead") == "1"
        return context


class PublicCOAPrintView(DetailView):
    model = Report
    template_name = "reports/coa_print.html"
    context_object_name = "report"

    def get_object(self, queryset=None):
        return _get_public_report_or_404(self.kwargs["pk"])

    def get_context_data(self, **kwargs):
        q = self.request.GET
        context = _get_report_render_context(
            self.object,
            self.request,
            preview_mode=True,
            auto_print=False,
            is_plain_doc=q.get("plain") == "1",
            is_test_report=q.get("doc") == "test",
        )
        context["is_letterhead"] = q.get("letterhead") == "1"
        return context


class COAPlainDocumentView(PermissionRequiredMixin, RoleRequiredMixin, TemplateView):
    permission_required = "reports.view_report"
    required_roles = ("Manager", "Incharge", "Analyst", "Admin")
    template_name = "reports/coa_doc.html"

    def get_context_data(self, **kwargs):
        report = get_object_or_404(Report, pk=self.kwargs["pk"])
        return _get_report_render_context(
            report,
            self.request,
            preview_mode=False,
            auto_print=False,
            is_plain_doc=self.request.GET.get("plain") == "1",
            is_test_report=self.request.GET.get("doc") == "test",
        )


class COAOptionView(PermissionRequiredMixin, RoleRequiredMixin, DetailView):
    permission_required = "reports.view_report"
    required_roles = ("Manager", "Incharge", "Analyst", "Admin")
    model = Report
    template_name = "reports/coa_options.html"
    context_object_name = "report"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        report = self.object
        preview_url = reverse("reports:coa_print", kwargs={"pk": report.pk})
        mode = SystemSetting.current().certificate_numbering_mode
        context["certificate_numbering_mode"] = mode
        context["certificate_numbering_mode_label"] = SystemSetting.CertificateNumberingMode(mode).label
        context["can_manage_system_settings"] = (
            self.request.user.is_superuser or self.request.user.has_perm("accounts.manage_system_settings")
        )
        context["system_settings_url"] = reverse("accounts:system_settings")
        context["report_options"] = [
            {
                "title": "Certificate of Analysis",
                "description": "Final COA with configured letterhead, watermark, signatures, and QR code.",
                "preview_url": preview_url,
                "badge": "COA",
            },
            {
                "title": "Certificate of Analysis Plain",
                "description": "COA content without letterhead artwork for pre-printed stationery.",
                "preview_url": f"{preview_url}?plain=1",
                "badge": "Plain",
            },
            {
                "title": "Test Report",
                "description": "Test Report format with standard report letterhead.",
                "preview_url": f"{preview_url}?doc=test",
                "badge": "Test",
            },
            {
                "title": "Test Report Plain",
                "description": "Plain Test Report for use with pre-printed stationery.",
                "preview_url": f"{preview_url}?doc=test&plain=1",
                "badge": "Test Plain",
            },
        ]
        return context


class ReportTemplateListView(PermissionRequiredMixin, RoleRequiredMixin, ListView):
    permission_required = "reports.view_reporttemplate"
    required_roles = ("Admin", "Manager", "Analyst")
    model = ReportTemplate
    template_name = "reports/report_template_list.html"
    context_object_name = "templates"

    def get_queryset(self):
        return ReportTemplate.objects.select_related("sample_name", "protocol").order_by("-is_default", "name")


class ReportTemplateCreateView(PermissionRequiredMixin, RoleRequiredMixin, CreateView):
    permission_required = "reports.add_reporttemplate"
    required_roles = ("Admin", "Manager")
    model = ReportTemplate
    form_class = ReportTemplateForm
    template_name = "reports/report_template_form.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Add Report Template"
        return context

    def get_success_url(self):
        messages.success(self.request, "Report template added.")
        return reverse("reports:template_list")


class ReportTemplateUpdateView(PermissionRequiredMixin, RoleRequiredMixin, UpdateView):
    permission_required = "reports.change_reporttemplate"
    required_roles = ("Admin", "Manager")
    model = ReportTemplate
    form_class = ReportTemplateForm
    template_name = "reports/report_template_form.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Edit Report Template"
        return context

    def get_success_url(self):
        messages.success(self.request, "Report template updated.")
        return reverse("reports:template_list")


class ReportTemplateDeleteView(PermissionRequiredMixin, RoleRequiredMixin, DeleteView):
    permission_required = "reports.delete_reporttemplate"
    required_roles = ("Admin", "Manager")
    model = ReportTemplate
    template_name = "reports/report_template_confirm_delete.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Delete Report Template"
        return context

    def get_success_url(self):
        messages.success(self.request, "Report template deleted.")
        return reverse("reports:template_list")


class COALetterheadUpdateView(PermissionRequiredMixin, FormView):
    permission_required = "reports.manage_letterheads"
    form_class = COALetterheadForm
    template_name = "reports/coa_letterhead_form.html"

    def get_object(self):
        obj, _ = COALetterhead.objects.get_or_create(pk=1, defaults={"name": "COA Letterhead"})
        return obj

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.get_object()
        return kwargs

    def form_valid(self, form):
        form.save()
        messages.success(self.request, "COA letterhead settings updated.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("reports:coa_letterhead")


class TestLetterheadUpdateView(COALetterheadUpdateView):
    form_class = TestLetterheadForm

    def get_object(self):
        obj, _ = TestLetterhead.objects.get_or_create(pk=1, defaults={"name": "Test Letterhead"})
        return obj

    def form_valid(self, form):
        form.save()
        messages.success(self.request, "Test letterhead settings updated.")
        return FormView.form_valid(self, form)

    def get_success_url(self):
        return reverse("reports:test_letterhead")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["letterhead_title"] = "Test Letterhead"
        context["back_url"] = reverse("reports:template_list")
        return context


class ReportTemplateContentView(PermissionRequiredMixin, RoleRequiredMixin, DetailView):
    permission_required = "reports.view_reporttemplate"
    required_roles = ("Admin", "Manager", "Analyst")
    model = ReportTemplate

    def get(self, request, *args, **kwargs):
        template = self.get_object()
        return JsonResponse(
            {
                "id": template.pk,
                "name": template.name,
                "content": template.content,
            }
        )


@method_decorator(require_http_methods(["GET"]), name="dispatch")
class ReportTemplateApiListView(PermissionRequiredMixin, RoleRequiredMixin, ListView):
    permission_required = "reports.view_reporttemplate"
    required_roles = ("Admin", "Manager", "Analyst")
    model = ReportTemplate

    def render_to_response(self, context, **response_kwargs):
        templates = context["object_list"]
        return JsonResponse(
            {
                "templates": [
                    {
                        "id": template.pk,
                        "name": template.name,
                        "description": template.description,
                        "content": template.content,
                        "sample_name": template.sample_name.display_name if template.sample_name else None,
                        "protocol": template.protocol.name if template.protocol else None,
                        "created_at": timezone.localtime(template.created_at).isoformat() if timezone.is_aware(template.created_at) else template.created_at.isoformat(),
                    }
                    for template in templates
                ]
            }
        )

    def get_queryset(self):
        return ReportTemplate.objects.filter(is_active=True).select_related("sample_name", "protocol").order_by("name")


@method_decorator(require_http_methods(["GET", "POST"]), name="dispatch")
class ReportApiDetailView(PermissionRequiredMixin, RoleRequiredMixin, DetailView):
    permission_required = "reports.view_report"
    required_roles = ("Manager", "Incharge", "Analyst", "Admin")
    model = Report

    def get(self, request, *args, **kwargs):
        report = self.get_object()
        return JsonResponse(self._serialize_report(report))

    def post(self, request, *args, **kwargs):
        report = self.get_object()
        if not request.user.has_perm("reports.change_report"):
            return JsonResponse({"detail": "You do not have permission to edit reports."}, status=403)

        html_content = request.POST.get("content", "")
        report_name = request.POST.get("name", "").strip()
        report.ceo_content = html_content
        report.updated_by = request.user
        report.save(update_fields=["ceo_content", "updated_by", "updated_at"])

        payload = self._serialize_report(report)
        if report_name:
            payload["report_name"] = report_name
        payload["saved"] = True
        return JsonResponse(payload)

    def _serialize_report(self, report):
        return {
            "id": report.pk,
            "report_name": report.booking.sample_registration_no if report.booking else f"Report {report.pk}",
            "content": report.ceo_content,
            "created_at": timezone.localtime(report.created_at).isoformat() if timezone.is_aware(report.created_at) else report.created_at.isoformat(),
            "updated_at": timezone.localtime(report.updated_at).isoformat() if timezone.is_aware(report.updated_at) else report.updated_at.isoformat(),
            "template_id": report.report_template_id,
            "booking_id": report.booking_id,
            "certificate_no": report.certificate_no,
        }
