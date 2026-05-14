from __future__ import annotations

from datetime import date, datetime, time
import re

from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.contrib.auth import get_user_model
from django.http import Http404
from django.http import JsonResponse
from django.http import HttpResponseServerError
from django.views.decorators.http import require_http_methods
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.http import HttpResponse
from django.template.defaultfilters import linebreaksbr
from django.template import engines
from django.template.loader import render_to_string
from django.utils.html import escape
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView, View
from django.utils.decorators import method_decorator

try:
    from weasyprint import HTML
except (ImportError, OSError):
    HTML = None

from bookings.models import Booking
from bookings.permissions import RoleRequiredMixin, has_role

from .forms import COAEditForm, ReportApprovalForm, ReportTemplateForm, TDSDocumentTemplateForm, _extract_uploaded_printable_content
from .models import Report, ReportRemark, ReportTemplate, TDSDocumentTemplate


PUBLIC_REPORT_ALLOWED_STATUSES = {
    Report.Status.MANAGER_APPROVED,
    Report.Status.INCHARGE_APPROVED,
}

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
    if is_plain_doc:
        base += "&plain=1" if "?" in base else "?plain=1"

    context["coa_public_url"] = request.build_absolute_uri(base)
    context["qr_payload"] = context["coa_public_url"]
    context["report_ceo_content"] = mark_safe(report.ceo_content or "")
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
        "sample_reg_no": booking.sample_reg_no,
        "booking_id": booking.tracking_code,
        "batch_no": batch_no,
        "batch_size": booking.batch_size,
        "customer_name": booking.customer.name if booking.customer_id else "",
        "customer_address": booking.customer.address if booking.customer_id else "",
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


def _render_tds_content(content, booking, request):
    if not content:
        return ""
    template = engines["django"].from_string(content)
    rendered_content = template.render(_booking_template_context(booking, request))
    rendered_content = _strip_tds_trailing_empty_blocks(rendered_content)
    rendered_content = _unwrap_tds_outer_table(rendered_content)
    rendered_content = _fill_tds_booking_labels(rendered_content, booking)
    return _strip_tds_trailing_empty_blocks(rendered_content)


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
    return re.sub(rf"(?:\s*{empty_block})+\s*$", "", content, flags=re.IGNORECASE)


def _fill_tds_booking_labels(content, booking):
    sample_name = booking.sample_name.name if booking.sample_name_id else ""
    batch_no = booking.batch_no or ""
    replacements = (
        ("Sample Name", sample_name),
        ("Sample Number", batch_no),
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
    return content


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
        elif status_filter == Report.Status.DRAFT:
            qs = qs.filter(status=Report.Status.DRAFT)
        elif status_filter == "approved":
            qs = qs.filter(status__in=[Report.Status.MANAGER_APPROVED, Report.Status.INCHARGE_APPROVED])
        elif status_filter == "pending":
            qs = qs.exclude(final_outcome=Report.FinalOutcome.PASS)

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
        if document_type == TDSDocumentTemplate.DocumentType.ADS:
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

        rendered_templates = [
            {
                "template": template,
                "test": template.test,
                "content": mark_safe(_render_tds_content(template.content, booking, self.request)),
            }
            for template in template_qs
        ]

        fallback_ads_templates = []
        if document_type == TDSDocumentTemplate.DocumentType.ADS:
            matched_test_ids = {item["test"].pk for item in rendered_templates if item["test"]}
            for test in selected_tests:
                if test.pk in matched_test_ids:
                    continue
                report_template = getattr(test, "report_template", None)
                if report_template and report_template.is_active and report_template.content.strip():
                    fallback_ads_templates.append(
                        {
                            "template": report_template,
                            "test": test,
                            "content": mark_safe(_render_tds_content(report_template.content, booking, self.request)),
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
                "print_mode": self.request.GET.get("print") == "1",
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
            raise Http404("Only approved bookings can generate report workflow.")
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
                "sample_reg_no": report.booking.sample_reg_no,
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


class COAPDFView(PermissionRequiredMixin, RoleRequiredMixin, DetailView):
    permission_required = "reports.view_report"
    required_roles = ("Manager", "Incharge", "Analyst", "Admin")
    model = Report
    template_name = None

    def get(self, request, *args, **kwargs):
        report = self.get_object()

        if HTML is None:
            return HttpResponseServerError("PDF generation is unavailable because WeasyPrint system libraries are missing.")

        # Render HTML context
        context = self.get_context_data()
        html_string = render_to_string('reports/coa_doc.html', context, request=request)

        # Generate PDF
        html = HTML(string=html_string)
        pdf_bytes = html.write_pdf()

        # Return PDF response
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="COA_{report.booking.sample_reg_no}.pdf"'
        return response

    def get_context_data(self, **kwargs):
        report = self.object
        context = _get_report_render_context(
            report,
            self.request,
            preview_mode=False,
            auto_print=False,
            is_plain_doc=self.request.GET.get("plain") == "1",
            is_test_report=self.request.GET.get("doc") == "test",
        )
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
            "report_name": report.booking.sample_reg_no if report.booking else f"Report {report.pk}",
            "content": report.ceo_content,
            "created_at": timezone.localtime(report.created_at).isoformat() if timezone.is_aware(report.created_at) else report.created_at.isoformat(),
            "updated_at": timezone.localtime(report.updated_at).isoformat() if timezone.is_aware(report.updated_at) else report.updated_at.isoformat(),
            "template_id": report.report_template_id,
            "booking_id": report.booking_id,
            "certificate_no": report.certificate_no,
        }
