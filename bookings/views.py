from __future__ import annotations

import csv
from datetime import date

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.paginator import Paginator
from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.db.models.deletion import ProtectedError
from django.http import HttpResponse, JsonResponse
from django.http.response import Http404
from django.shortcuts import get_object_or_404, redirect
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.utils import timezone
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView

from reports.models import Report, ReportRemark, ReportTemplate, TDSDocumentTemplate
from accounts.models import AnnouncementSeen, WelcomeAnnouncement

from .forms import (
    BookingForm,
    CustomerMasterForm,
    ManufacturerMasterForm,
    ProtocolMasterForm,
    ReportRemarkMasterForm,
    SampleNameMasterForm,
    SubmitterMasterForm,
    TestMasterForm,
    UOMMasterForm,
)
from .models import (
    Booking,
    BillingRecord,
    CustomerMaster,
    ManufacturerMaster,
    ProtocolMaster,
    SampleNameMaster,
    SubmitterMaster,
    TestMaster,
    UOMMaster,
)
from .permissions import RoleRequiredMixin


MASTER_CONFIG = {
    "customer": {
        "model": CustomerMaster,
        "form": CustomerMasterForm,
        "title": "Customer Master",
        "detail_attr": "address",
        "search_fields": ("name", "address", "contact_person", "telephone", "email"),
    },
    "submitter": {
        "model": SubmitterMaster,
        "form": SubmitterMasterForm,
        "title": "Submitter Master",
        "search_fields": ("name",),
    },
    "manufacturer": {
        "model": ManufacturerMaster,
        "form": ManufacturerMasterForm,
        "title": "Manufacturer Master",
        "search_fields": ("name",),
    },
    "sample-name": {
        "model": SampleNameMaster,
        "form": SampleNameMasterForm,
        "title": "Sample Name Master",
        "detail_attr": "generic_name",
        "search_fields": (
            "name",
            "generic_name",
            "sample_type",
            "discipline",
            "test_group",
            "method",
            "customer",
            "description",
            "limits",
        ),
    },
    "test": {
        "model": TestMaster,
        "form": TestMasterForm,
        "title": "Test Master",
        "detail_attr": "report_template",
        "search_fields": ("name", "report_template__name"),
    },
    "protocol": {
        "model": ProtocolMaster,
        "form": ProtocolMasterForm,
        "title": "Protocol Master",
        "search_fields": ("name",),
    },
    "uom": {
        "model": UOMMaster,
        "form": UOMMasterForm,
        "title": "UOM Master",
        "search_fields": ("name",),
    },
    "remark": {
        "model": ReportRemark,
        "form": ReportRemarkMasterForm,
        "title": "Remark Master",
        "order_by": ("sort_order", "title"),
        "primary_attr": "title",
        "detail_attr": "content",
        "search_fields": ("title", "content"),
    },
}
INLINE_ALLOWED_MASTERS = {"customer", "submitter", "manufacturer", "sample-name", "test", "uom", "protocol"}


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["counts"] = Booking.objects.values("status").annotate(total=Count("id"))
        context["reports_total"] = Report.objects.count()
        context["report_templates_total"] = ReportTemplate.objects.count()
        context["tds_templates_total"] = TDSDocumentTemplate.objects.count()
        context["masters"] = [
            {"slug": slug, "title": conf["title"], "count": conf["model"].objects.count()}
            for slug, conf in MASTER_CONFIG.items()
        ]
        announcement = WelcomeAnnouncement.objects.first()
        if announcement and announcement.is_current:
            seen = AnnouncementSeen.objects.filter(announcement=announcement, user=self.request.user)
            session_key = self.request.session.session_key or ""
            should_show = (
                announcement.display_mode in {WelcomeAnnouncement.DisplayMode.LOGIN, "every_login"}
                and not seen.filter(session_key=session_key).exists()
                or (announcement.display_mode == WelcomeAnnouncement.DisplayMode.DAILY and not seen.filter(seen_at__date=timezone.localdate()).exists())
                or (announcement.display_mode == WelcomeAnnouncement.DisplayMode.ONCE and not seen.exists())
            )
            context["welcome_announcement"] = announcement if should_show else None
            if should_show:
                user_name = self.request.user.get_full_name().strip() or self.request.user.username
                context["welcome_announcement_title"] = announcement.title.replace("{{ user_name }}", user_name)
                context["welcome_announcement_message"] = mark_safe(
                    announcement.message.replace("{{ user_name }}", escape(user_name))
                )
        return context


class DataSheetView(LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    permission_required = "bookings.view_data_sheet"
    template_name = "bookings/data_sheet.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        customer_id = self.request.GET.get("party", "").strip()
        selected_statuses = self.request.GET.getlist("status")
        booking_status = self.request.GET.get("booking_status", "").strip()
        date_from = _parse_filter_date(self.request.GET.get("date_from", ""))
        date_to = _parse_filter_date(self.request.GET.get("date_to", ""))
        context["party_customer_id"] = customer_id
        context["party_selected_statuses"] = selected_statuses
        context["booking_status"] = booking_status
        context["date_from"] = date_from.isoformat() if date_from else ""
        context["date_to"] = date_to.isoformat() if date_to else ""
        context["booking_status_options"] = Booking.Status.choices
        context["status_options"] = PARTY_STATUS_OPTIONS
        context["party_customers"] = CustomerMaster.objects.order_by("name")
        context["party_report_requested"] = bool(self.request.GET)
        bookings = _party_pending_bookings(customer_id, selected_statuses, booking_status, date_from, date_to)
        context["party_pending_bookings"] = bookings if context["party_report_requested"] else []
        context["party_summary"] = _party_booking_summary(bookings) if context["party_report_requested"] else []
        context["total_samples"] = len(bookings) if context["party_report_requested"] else 0
        return context


def _billing_filters(request):
    """Read shared billing party and date filters from a request."""
    return (
        request.GET.get("party", "").strip(),
        _parse_filter_date(request.GET.get("date_from", "")),
        _parse_filter_date(request.GET.get("date_to", "")),
        request.GET.get("bill_number", "").strip(),
        request.GET.get("booking_number", "").strip(),
        request.GET.get("batch_number", "").strip(),
        _parse_filter_date(request.GET.get("billing_date_from", "")),
        _parse_filter_date(request.GET.get("billing_date_to", "")),
    )


def _billing_bookings(customer_id="", date_from=None, date_to=None, done=False, bill_number="", booking_number="", batch_number="", billing_date_from=None, billing_date_to=None):
    """Passed reports waiting for billing, or records already confirmed as billed."""
    queryset = Booking.objects.select_related(
        "customer", "sample_name", "report", "billing_record", "billing_record__confirmed_by"
    )
    if done:
        queryset = queryset.filter(billing_record__isnull=False).order_by("-billing_record__confirmed_at", "-pk")
    else:
        queryset = queryset.filter(
            report__final_outcome=Report.FinalOutcome.PASS,
            billing_record__isnull=True,
        ).order_by("-report__updated_at", "-pk")
    if customer_id:
        queryset = queryset.filter(customer_id=customer_id)
    if date_from:
        queryset = queryset.filter(report__updated_at__date__gte=date_from)
    if date_to:
        queryset = queryset.filter(report__updated_at__date__lte=date_to)
    if done and bill_number:
        queryset = queryset.filter(billing_record__bill_number__icontains=bill_number)
    if done and booking_number:
        queryset = queryset.filter(tracking_code__icontains=booking_number)
    if done and batch_number:
        queryset = queryset.filter(batch_no__icontains=batch_number)
    if done and billing_date_from:
        queryset = queryset.filter(billing_record__confirmed_at__date__gte=billing_date_from)
    if done and billing_date_to:
        queryset = queryset.filter(billing_record__confirmed_at__date__lte=billing_date_to)
    return queryset


class BillingBaseView(LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    permission_required = "bookings.view_billingrecord"
    done = False

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        customer_id, date_from, date_to, bill_number, booking_number, batch_number, billing_date_from, billing_date_to = _billing_filters(self.request)
        bookings = _billing_bookings(customer_id, date_from, date_to, self.done, bill_number, booking_number, batch_number, billing_date_from, billing_date_to)
        context.update(
            {
                "billing_bookings": bookings,
                "billing_customers": CustomerMaster.objects.order_by("name"),
                "billing_customer_id": customer_id,
                "date_from": date_from.isoformat() if date_from else "",
                "date_to": date_to.isoformat() if date_to else "",
                "billing_total": bookings.count(),
                "billing_done": self.done,
                "bill_number": bill_number,
                "booking_number": booking_number,
                "batch_number": batch_number,
                "billing_date_from": billing_date_from.isoformat() if billing_date_from else "",
                "billing_date_to": billing_date_to.isoformat() if billing_date_to else "",
            }
        )
        return context


class BillingPendingView(BillingBaseView):
    template_name = "bookings/billing_pending.html"


class BillingDoneView(BillingBaseView):
    template_name = "bookings/billing_done.html"
    done = True


class BillingConfirmView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "bookings.add_billingrecord"

    def post(self, request):
        individual_booking_id = request.POST.get("confirm_one", "").strip()
        booking_ids = [individual_booking_id] if individual_booking_id else request.POST.getlist("booking_ids")
        if not booking_ids:
            messages.warning(request, "Select at least one sample before confirming billing.")
            return redirect("bookings:billing_pending")

        billing_details = {}
        for booking_id in booking_ids:
            bill_number = request.POST.get(f"bill_number_{booking_id}", "").strip()
            if not bill_number:
                messages.warning(request, "Each selected sample needs a bill number.")
                return redirect("bookings:billing_pending")
            billing_details[str(booking_id)] = bill_number

        if not billing_details:
            messages.warning(request, "Bill number, letter date, and report complete date are required to confirm billing.")
            return redirect("bookings:billing_pending")

        eligible = list(_billing_bookings().filter(pk__in=booking_ids))
        for booking in eligible:
            if not booking.letter_date or not (booking.report.analysis_end_date or booking.analysis_end_date):
                messages.warning(request, f"{booking.tracking_code} needs a Letter Date and Complete Date before billing can be confirmed.")
                return redirect("bookings:billing_pending")
        confirmed = 0
        with transaction.atomic():
            for booking in Booking.objects.filter(pk__in=[item.pk for item in eligible]).select_related("report").select_for_update():
                bill_number = billing_details[str(booking.pk)]
                letter_date = booking.letter_date
                billing_done_date = booking.report.analysis_end_date or booking.analysis_end_date
                try:
                    with transaction.atomic():
                        BillingRecord.objects.create(
                            booking=booking,
                            confirmed_by=request.user,
                            bill_number=bill_number,
                            letter_date=letter_date,
                            billing_done_date=billing_done_date,
                        )
                    confirmed += 1
                except IntegrityError:
                    # Another user may have confirmed the same sample at the same time.
                    continue
        if confirmed:
            messages.success(request, f"Billing confirmed for {confirmed} sample{'s' if confirmed != 1 else ''}.")
        else:
            messages.warning(request, "The selected samples are no longer waiting for billing.")
        return redirect("bookings:billing_pending")


class BillingUndoView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "bookings.delete_billingrecord"

    def post(self, request, pk):
        billing = get_object_or_404(BillingRecord.objects.select_related("booking"), pk=pk)
        tracking_code = billing.booking.tracking_code
        billing.delete()
        messages.success(request, f"Billing confirmation for {tracking_code} was undone and returned to Billing Pending.")
        return redirect("bookings:billing_done")


class BillingUndoSelectedView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "bookings.delete_billingrecord"

    def post(self, request):
        individual_record_id = request.POST.get("undo_one", "").strip()
        record_ids = [individual_record_id] if individual_record_id else request.POST.getlist("billing_record_ids")
        if not record_ids:
            messages.warning(request, "Tick at least one billing record to undo.")
            return redirect("bookings:billing_done")
        deleted, _ = BillingRecord.objects.filter(pk__in=record_ids).delete()
        if deleted:
            messages.success(request, f"{deleted} billing confirmation{'s' if deleted != 1 else ''} undone.")
        return redirect("bookings:billing_done")


class BillingExcelView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "bookings.view_billingrecord"

    def get(self, request, state):
        if state not in {"pending", "done"}:
            raise Http404
        customer_id, date_from, date_to, bill_number, booking_number, batch_number, billing_date_from, billing_date_to = _billing_filters(request)
        done = state == "done"
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="billing-{state}.csv"'
        response.write("\ufeff")
        writer = csv.writer(response)
        headings = ["Sr. No.", "Party Name", "Sample Name", "Batch No.", "Booking No.", "Letter Date", "Complete Date"]
        if done:
            headings.extend(["Bill Number", "Billing Confirmed Date", "Confirmed By"])
        writer.writerow(headings)
        for index, booking in enumerate(_billing_bookings(customer_id, date_from, date_to, done, bill_number, booking_number, batch_number, billing_date_from, billing_date_to), start=1):
            letter_date = booking.billing_record.letter_date if done else booking.letter_date
            report_complete_date = (
                booking.billing_record.billing_done_date
                if done
                else (booking.report.analysis_end_date or booking.analysis_end_date)
            )
            row = [
                index,
                booking.customer.name if booking.customer_id else "Unassigned Party",
                booking.sample_name.display_name if booking.sample_name_id else "",
                booking.batch_no or "",
                booking.tracking_code,
                letter_date.strftime("%d/%m/%Y") if letter_date else "",
                report_complete_date.strftime("%d/%m/%Y") if report_complete_date else "",
            ]
            if done:
                row.extend([
                    booking.billing_record.bill_number,
                    booking.billing_record.confirmed_at.strftime("%d/%m/%Y %H:%M"),
                    booking.billing_record.confirmed_by.get_full_name() or booking.billing_record.confirmed_by.username,
                ])
            writer.writerow(row)
        return response


class BillingPrintView(BillingBaseView):
    template_name = "bookings/billing_print.html"

    def get(self, request, state):
        if state not in {"pending", "done"}:
            raise Http404
        self.done = state == "done"
        return super().get(request)


PARTY_STATUS_OPTIONS = (
    ("assigned", "Assigned"),
    ("pending", "Pending"),
    ("draft", "Draft"),
    ("pass", "Pass"),
)


def _parse_filter_date(value):
    """Return an ISO date from a filter value, ignoring malformed input."""
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _party_pending_bookings(customer_id="", statuses=None, booking_status="", date_from=None, date_to=None):
    """Bookings for an optional party, workflow state, booking state, and date range."""
    statuses = [status for status in (statuses or []) if status in dict(PARTY_STATUS_OPTIONS)]
    queryset = (
        Booking.objects.select_related("customer", "sample_name", "report")
        .prefetch_related("test_to_be_performed")
        .order_by("-booking_date", "-pk")
    )
    if customer_id:
        queryset = queryset.filter(customer_id=customer_id)
    if booking_status in dict(Booking.Status.choices):
        queryset = queryset.filter(status=booking_status)
    if date_from:
        queryset = queryset.filter(booking_date__date__gte=date_from)
    if date_to:
        queryset = queryset.filter(booking_date__date__lte=date_to)

    status_filter = Q()
    if "pending" in statuses:
        status_filter |= Q(status=Booking.Status.PENDING)
    if "assigned" in statuses:
        status_filter |= Q(status=Booking.Status.APPROVED) & (Q(report__isnull=True) | Q(report__status=Report.Status.DRAFT))
    if "draft" in statuses:
        status_filter |= Q(report__status=Report.Status.DRAFT)
    if "pass" in statuses:
        status_filter |= Q(report__final_outcome=Report.FinalOutcome.PASS)
    if statuses:
        queryset = queryset.filter(status_filter).distinct()

    bookings = list(queryset)
    for booking in bookings:
        report = getattr(booking, "report", None)
        if booking.status == Booking.Status.PENDING:
            booking.party_status = "Pending"
        elif report and report.final_outcome == Report.FinalOutcome.PASS:
            booking.party_status = "Pass"
        elif report and report.status == Report.Status.DRAFT:
            booking.party_status = "Draft"
        else:
            booking.party_status = "Assigned"
    return bookings


def _party_booking_summary(bookings):
    """Group the selected booking list into party-wise sample totals."""
    totals = {}
    for booking in bookings:
        party_name = booking.customer.name if booking.customer_id else "Unassigned Party"
        totals[party_name] = totals.get(party_name, 0) + 1
    return [
        {"party_name": party_name, "sample_count": sample_count}
        for party_name, sample_count in sorted(totals.items(), key=lambda item: (-item[1], item[0].lower()))
    ]


class PartyPendingExcelView(LoginRequiredMixin, View):
    """Download the selected party's pending bookings in an Excel-compatible CSV."""

    def get(self, request):
        customer_id = request.GET.get("party", "").strip()
        statuses = request.GET.getlist("status")
        booking_status = request.GET.get("booking_status", "").strip()
        date_from = _parse_filter_date(request.GET.get("date_from", ""))
        date_to = _parse_filter_date(request.GET.get("date_to", ""))
        customer = CustomerMaster.objects.filter(pk=customer_id).first() if customer_id else None
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        filename = f"party-pending-{customer.name if customer else 'all-parties'}".replace('"', "").replace("/", "-")
        response["Content-Disposition"] = f'attachment; filename="{filename}.csv"'
        response.write("\ufeff")
        writer = csv.writer(response)
        writer.writerow(["Sr. No.", "Sample Name", "Batch No.", "Booking No.", "Letter Date", "Booking Date", "Booking Status", "Processing Status", "Party Name"])
        for index, booking in enumerate(_party_pending_bookings(customer_id, statuses, booking_status, date_from, date_to), start=1):
            writer.writerow(
                [
                    index,
                    booking.sample_name.display_name if booking.sample_name_id else "",
                    booking.batch_no or "",
                    booking.tracking_code,
                    booking.letter_date.strftime("%d/%m/%Y") if booking.letter_date else "",
                    booking.booking_date.strftime("%d/%m/%Y") if booking.booking_date else "",
                    booking.get_status_display(),
                    booking.party_status,
                    booking.customer.name if booking.customer_id else "",
                ]
            )
        return response


class PartyPendingPrintView(LoginRequiredMixin, TemplateView):
    template_name = "bookings/party_pending_print.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        customer_id = self.request.GET.get("party", "").strip()
        statuses = self.request.GET.getlist("status")
        booking_status = self.request.GET.get("booking_status", "").strip()
        date_from = _parse_filter_date(self.request.GET.get("date_from", ""))
        date_to = _parse_filter_date(self.request.GET.get("date_to", ""))
        context["customer"] = CustomerMaster.objects.filter(pk=customer_id).first() if customer_id else None
        context["bookings"] = _party_pending_bookings(customer_id, statuses, booking_status, date_from, date_to)
        context["party_summary"] = _party_booking_summary(context["bookings"])
        context["selected_statuses"] = [label for value, label in PARTY_STATUS_OPTIONS if value in statuses]
        context["booking_status_label"] = dict(Booking.Status.choices).get(booking_status, "All")
        context["date_from"] = date_from
        context["date_to"] = date_to
        return context


class BookingCreateView(RoleRequiredMixin, PermissionRequiredMixin, CreateView):
    permission_required = "bookings.add_booking"
    required_roles = ("Staff", "Analyst", "Manager", "Admin")
    model = Booking
    form_class = BookingForm
    template_name = "bookings/booking_form.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        duplicate_id = self.request.GET.get("duplicate")
        context["duplicate_id"] = duplicate_id
        context["edit_mode"] = False
        context["inline_master_slugs"] = INLINE_ALLOWED_MASTERS
        return context

    def get_initial(self):
        initial = super().get_initial()
        duplicate_id = self.request.GET.get("duplicate")
        if duplicate_id:
            source = get_object_or_404(Booking, pk=duplicate_id)
            initial.update(
                {
                    "booking_date": source.booking_date,
                    "letter_date": source.letter_date,
                    "sampling_upto": source.sampling_upto,
                    "sample_receipt_date": source.sample_receipt_date,
                    "customer": source.customer_id,
                    "submitter": source.submitter_id,
                    "manufacturer": source.manufacturer_id,
                    "sample_name": source.sample_name_id,
                    "sample_type": source.sample_type,
                    "protocol": source.protocol_id,
                    "uom": source.uom_id,
                    "booking_type": source.booking_type,
                    "sample_qty": source.sample_qty,
                    "sample_location": source.sample_location,
                    "packaging_mode": source.packaging_mode,
                    "sample_condition": source.sample_condition,
                    "batch_no": source.batch_no,
                    "batch_size": source.batch_size,
                    "manufacture_date": source.manufacture_date,
                    "expiry_retest_date": source.expiry_retest_date,
                    "license_no": source.license_no,
                    "collected_by_name": source.collected_by_name,
                    "sampling_procedure": source.sampling_procedure,
                    "analysis_start_date": source.analysis_start_date,
                    "analysis_end_date": source.analysis_end_date,
                    "remarks": source.remarks,
                    "test_to_be_performed": list(source.test_to_be_performed.values_list("id", flat=True)),
                }
            )
        return initial

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        form.instance.updated_by = self.request.user
        try:
            response = super().form_valid(form)
        except DatabaseError:
            messages.error(
                self.request,
                "Database schema is not up to date. Please run migrations and try again.",
            )
            return redirect("bookings:create")
        return response

    def get_success_url(self):
        return f"{reverse('bookings:list')}?saved=1&booking_id={self.object.tracking_code}"


class BookingUpdateView(RoleRequiredMixin, PermissionRequiredMixin, UpdateView):
    permission_required = "bookings.change_booking"
    required_roles = ("Staff", "Analyst", "Manager", "Admin")
    model = Booking
    form_class = BookingForm
    template_name = "bookings/booking_form.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["duplicate_id"] = None
        context["edit_mode"] = True
        context["inline_master_slugs"] = INLINE_ALLOWED_MASTERS
        return context

    def form_valid(self, form):
        form.instance.updated_by = self.request.user
        try:
            response = super().form_valid(form)
        except DatabaseError:
            messages.error(
                self.request,
                "Database schema is not up to date. Please run migrations and try again.",
            )
            return redirect("bookings:list")
        return response

    def get_success_url(self):
        return f"{reverse('bookings:list')}?saved=1&booking_id={self.object.tracking_code}"


class BookingListView(LoginRequiredMixin, ListView):
    model = Booking
    template_name = "bookings/booking_list.html"
    context_object_name = "bookings"
    paginate_by = 10

    def get_queryset(self):
        qs = (
            Booking.objects.select_related("customer", "sample_name", "created_by", "updated_by", "approved_by")
            .prefetch_related("test_to_be_performed")
            .annotate(
                is_reported_for_list=Exists(
                    Report.objects.filter(
                        booking_id=OuterRef("pk"),
                        status__in=[Report.Status.MANAGER_APPROVED, Report.Status.INCHARGE_APPROVED],
                    )
                )
            )
            .order_by("-created_at")
        )
        search = self.request.GET.get("q", "").strip()
        search_by = self.request.GET.get("search_by", "sample_reg_no").strip()
        status_filter = self.request.GET.get("status", "").strip()
        customer_filter = self.request.GET.get("customer", "").strip()

        if status_filter == Booking.Status.PENDING:
            qs = qs.filter(status=Booking.Status.PENDING)
        elif status_filter == "assigned":
            qs = qs.filter(status=Booking.Status.APPROVED).filter(
                Q(report__isnull=True) | Q(report__status=Report.Status.DRAFT)
            )
        elif status_filter == Booking.Status.APPROVED:
            qs = qs.filter(report__status__in=[Report.Status.MANAGER_APPROVED, Report.Status.INCHARGE_APPROVED])

        if customer_filter:
            qs = qs.filter(customer_id=customer_filter)

        if search:
            if search_by == "customer":
                qs = qs.filter(customer__name__icontains=search)
            elif search_by == "sample":
                qs = qs.filter(sample_name__name__icontains=search)
            elif search_by == "batch_no":
                qs = qs.filter(batch_no__iexact=search)
            elif search_by == "tracking":
                qs = qs.filter(tracking_code__iexact=search)
            else:
                qs = qs.filter(sample_reg_no__icontains=search)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["q"] = self.request.GET.get("q", "").strip()
        context["search_by"] = self.request.GET.get("search_by", "sample_reg_no").strip()
        context["status_filter"] = self.request.GET.get("status", "").strip()
        context["customer_filter"] = self.request.GET.get("customer", "").strip()
        context["customer_options"] = CustomerMaster.objects.order_by("name")
        context["show_saved_popup"] = self.request.GET.get("saved") == "1"
        context["saved_booking_id"] = self.request.GET.get("booking_id", "").strip()
        if context.get("is_paginated"):
            context["page_numbers"] = context["page_obj"].paginator.get_elided_page_range(
                context["page_obj"].number,
                on_each_side=2,
                on_ends=1,
            )
        return context


class BookingDetailView(LoginRequiredMixin, DetailView):
    model = Booking
    template_name = "bookings/booking_detail.html"
    context_object_name = "booking"

    def get_queryset(self):
        return (
            Booking.objects.select_related(
                "customer",
                "submitter",
                "manufacturer",
                "sample_name",
                "protocol",
                "uom",
                "created_by",
                "updated_by",
                "approved_by",
            )
            .prefetch_related("test_to_be_performed")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["report"] = getattr(self.object, "report", None)
        return context


class BookingDeleteView(PermissionRequiredMixin, DeleteView):
    permission_required = "bookings.delete_booking"
    model = Booking
    template_name = "bookings/booking_confirm_delete.html"
    success_url = reverse_lazy("bookings:list")

    def form_valid(self, form):
        booking_id = self.object.tracking_code
        try:
            response = super().form_valid(form)
        except ProtectedError:
            messages.error(
                self.request,
                "Cannot delete this booking because it is referenced by protected records.",
            )
            return redirect("bookings:detail", pk=self.object.pk)
        messages.success(self.request, f"Booking {booking_id} deleted.")
        return response


class BookingApproveView(RoleRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "bookings.change_booking"
    required_roles = ("Checked By",)
    allow_staff = False

    def post(self, request, pk):
        booking = get_object_or_404(Booking, pk=pk)
        if booking.status == Booking.Status.APPROVED:
            messages.info(request, "Booking is already approved.")
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"assigned": True, "report_url": reverse("reports:approval", kwargs={"booking_pk": booking.pk})})
            return redirect("bookings:list")
        booking.approve(request.user)
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"assigned": True, "report_url": reverse("reports:approval", kwargs={"booking_pk": booking.pk})})
        messages.success(request, f"Booking approved. Booking ID: {booking.tracking_code}")
        return redirect("bookings:list")


class MasterListView(LoginRequiredMixin, TemplateView):
    template_name = "bookings/master_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        slug = self.kwargs["slug"]
        conf = MASTER_CONFIG.get(slug)
        if not conf:
            raise Http404("Invalid master type")
        order_by = conf.get("order_by", ("name",))
        queryset = conf["model"].objects.order_by(*order_by)
        search_query = self.request.GET.get("q", "").strip()
        if search_query:
            search_filter = Q()
            for field in conf.get("search_fields", ("name",)):
                search_filter |= Q(**{f"{field}__icontains": search_query})
            queryset = queryset.filter(search_filter)
        paginator = Paginator(queryset, 20)
        page_obj = paginator.get_page(self.request.GET.get("page"))
        primary_attr = conf.get("primary_attr", "name")
        detail_attr = conf.get("detail_attr")
        rows = []
        for obj in page_obj.object_list:
            rows.append(
                {
                    "object": obj,
                    "primary": getattr(obj, "display_name", getattr(obj, primary_attr, "")),
                    "detail": getattr(obj, detail_attr, "") if detail_attr else "",
                    "created_at": getattr(obj, "created_at", None),
                }
            )
        context.update(
            {
                "master_slug": slug,
                "title": conf["title"],
                "page_obj": page_obj,
                "object_list": page_obj.object_list,
                "rows": rows,
                "can_inline": slug in INLINE_ALLOWED_MASTERS,
                "search_query": search_query,
            }
        )
        return context


class MasterPermissionAccessMixin(RoleRequiredMixin):
    def test_func(self):
        if super().test_func():
            return True
        permission_required = getattr(self, "permission_required", "")
        return bool(permission_required and self.request.user.has_perm(permission_required))


class MasterCreateView(MasterPermissionAccessMixin, PermissionRequiredMixin, CreateView):
    required_roles = ("Admin", "Manager")
    permission_required = "bookings.add_customermaster"
    template_name = "bookings/master_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.slug = kwargs["slug"]
        conf = MASTER_CONFIG.get(self.slug)
        if not conf:
            raise Http404("Invalid master type")
        self.model = conf["model"]
        self.form_class = conf["form"]
        self.title = conf["title"]
        self.permission_required = f"{self.model._meta.app_label}.add_{self.model._meta.model_name}"
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = f"Add {self.title}"
        context["master_slug"] = self.slug
        return context

    def get_success_url(self):
        messages.success(self.request, f"{self.title} added.")
        return reverse("bookings:master_list", kwargs={"slug": self.slug})


class MasterUpdateView(MasterPermissionAccessMixin, PermissionRequiredMixin, UpdateView):
    required_roles = ("Admin", "Manager")
    permission_required = "bookings.change_customermaster"
    template_name = "bookings/master_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.slug = kwargs["slug"]
        conf = MASTER_CONFIG.get(self.slug)
        if not conf:
            raise Http404("Invalid master type")
        self.model = conf["model"]
        self.form_class = conf["form"]
        self.title = conf["title"]
        self.permission_required = f"{self.model._meta.app_label}.change_{self.model._meta.model_name}"
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = f"Edit {self.title}"
        context["master_slug"] = self.slug
        return context

    def get_success_url(self):
        messages.success(self.request, f"{self.title} updated.")
        return reverse("bookings:master_list", kwargs={"slug": self.slug})


class MasterDeleteView(MasterPermissionAccessMixin, PermissionRequiredMixin, DeleteView):
    required_roles = ("Admin", "Manager")
    permission_required = "bookings.delete_customermaster"
    template_name = "bookings/master_confirm_delete.html"

    def dispatch(self, request, *args, **kwargs):
        self.slug = kwargs["slug"]
        conf = MASTER_CONFIG.get(self.slug)
        if not conf:
            raise Http404("Invalid master type")
        self.model = conf["model"]
        self.title = conf["title"]
        self.permission_required = f"{self.model._meta.app_label}.delete_{self.model._meta.model_name}"
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = f"Delete {self.title}"
        context["master_slug"] = self.slug
        return context

    def get_success_url(self):
        messages.success(self.request, f"{self.title} deleted.")
        return reverse("bookings:master_list", kwargs={"slug": self.slug})


class InlineMasterCreateView(RoleRequiredMixin, View):
    required_roles = ("Analyst", "Manager", "Admin")

    def post(self, request, slug):
        if slug not in INLINE_ALLOWED_MASTERS:
            return JsonResponse({"error": "Inline add is not allowed for this master."}, status=400)

        conf = MASTER_CONFIG[slug]
        name = request.POST.get("name", "").strip()
        if not name:
            return JsonResponse({"error": "Name is required."}, status=400)

        defaults = {"is_active": True}
        if slug == "customer":
            defaults.update(
                {
                    "address": request.POST.get("address", "").strip(),
                    "contact_person": request.POST.get("contact_person", "").strip(),
                    "telephone": request.POST.get("telephone", "").strip(),
                    "email": request.POST.get("email", "").strip(),
                }
            )
        elif slug == "sample-name":
            defaults.update(
                {
                    "generic_name": request.POST.get("generic_name", "").strip(),
                    "sample_type": request.POST.get("sample_type", "").strip(),
                    "discipline": request.POST.get("discipline", "").strip(),
                    "test_group": request.POST.get("test_group", "").strip(),
                    "method": request.POST.get("method", "").strip(),
                    "rate": request.POST.get("rate", "").strip(),
                    "observationsheet_prefix": request.POST.get("observationsheet_prefix", "").strip(),
                    "customer": request.POST.get("customer", "").strip(),
                    "description": request.POST.get("description", "").strip(),
                    "limits": request.POST.get("limits", "").strip(),
                }
            )
            if defaults["sample_type"] and defaults["sample_type"] not in dict(SampleNameMaster.SampleType.choices):
                return JsonResponse({"error": "Invalid Sample Type."}, status=400)
            if defaults["discipline"] and defaults["discipline"] not in dict(SampleNameMaster.Discipline.choices):
                return JsonResponse({"error": "Invalid Discipline."}, status=400)
            if defaults["test_group"] and defaults["test_group"] not in dict(SampleNameMaster.TestGroup.choices):
                return JsonResponse({"error": "Invalid Test Group."}, status=400)

        obj, created = conf["model"].objects.get_or_create(name=name, defaults=defaults)
        if slug == "sample-name":
            update_fields = []
            for field in (
                "generic_name",
                "sample_type",
                "discipline",
                "test_group",
                "method",
                "rate",
                "observationsheet_prefix",
                "customer",
                "description",
                "limits",
            ):
                value = defaults.get(field, "")
                if value and getattr(obj, field, "") != value:
                    setattr(obj, field, value)
                    update_fields.append(field)
            if update_fields:
                obj.save(update_fields=update_fields)
        if not obj.is_active:
            obj.is_active = True
            obj.save(update_fields=["is_active"])

        return JsonResponse(
            {
                "id": obj.pk,
                "name": getattr(obj, "display_name", obj.name),
                "raw_name": obj.name,
                "address": getattr(obj, "address", ""),
                "contact_person": getattr(obj, "contact_person", ""),
                "telephone": getattr(obj, "telephone", ""),
                "email": getattr(obj, "email", ""),
                "generic_name": getattr(obj, "generic_name", ""),
                "discipline": getattr(obj, "discipline", ""),
                "test_group": getattr(obj, "test_group", ""),
                "sample_type": getattr(obj, "sample_type", ""),
                "created": created,
            }
        )


class GetSimilarBookingDataView(LoginRequiredMixin, View):
    """Fetch previous booking data for matching sample_name and customer."""
    
    def get(self, request):
        sample_name_id = request.GET.get("sample_name_id")
        customer_id = request.GET.get("customer_id")
        
        if not sample_name_id or not customer_id:
            return JsonResponse({"error": "Missing sample_name_id or customer_id"}, status=400)
        
        try:
            sample_name_id = int(sample_name_id)
            customer_id = int(customer_id)
        except (ValueError, TypeError):
            return JsonResponse({"error": "Invalid IDs"}, status=400)
        
        previous_booking = Booking.get_last_similar_booking(sample_name_id, customer_id)
        
        if not previous_booking:
            return JsonResponse({"found": False})
        
        return JsonResponse({
            "found": True,
            "sample_name_id": previous_booking.sample_name_id,
            "customer_id": previous_booking.customer_id,
            "submitter_id": previous_booking.submitter_id,
            "manufacturer_id": previous_booking.manufacturer_id,
            "sample_type": previous_booking.sample_type,
            "protocol_id": previous_booking.protocol_id,
            "uom_id": previous_booking.uom_id,
            "booking_type": previous_booking.booking_type,
            "sample_qty": previous_booking.sample_qty or "",
            "sample_location": previous_booking.sample_location or "",
            "packaging_mode": previous_booking.packaging_mode or "",
            "sample_condition": previous_booking.sample_condition or "",
            "batch_no": previous_booking.batch_no or "",
            "batch_size": previous_booking.batch_size or "",
            "manufacture_date": previous_booking.manufacture_date.isoformat() if previous_booking.manufacture_date else "",
            "expiry_retest_date": previous_booking.expiry_retest_date.isoformat() if previous_booking.expiry_retest_date else "",
            "license_no": previous_booking.license_no or "",
            "customer_sr_no": previous_booking.customer_sr_no or "",
            "collected_by_name": previous_booking.collected_by_name or "",
            "sampling_procedure": previous_booking.sampling_procedure or "",
            "remarks": previous_booking.remarks or "",
        })


def create_default_roles():
    from django.contrib.auth.models import Group

    for role in ("Admin", "Manager", "Incharge", "Analyst", "Checked By"):
        Group.objects.get_or_create(name=role)
