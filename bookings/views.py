from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.db.models import Count, Exists, OuterRef, Q
from django.db.models.deletion import ProtectedError
from django.http import JsonResponse
from django.http.response import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView

from reports.models import Report, ReportRemark, ReportTemplate, TDSDocumentTemplate

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
        "search_fields": ("name", "address"),
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
            defaults["address"] = request.POST.get("address", "").strip()
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
