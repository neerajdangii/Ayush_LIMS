from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.html import escape

from bookings.models import Booking, ProtocolMaster, SampleNameMaster, TestMaster
from .template_library import build_tests_without_templates_table


class ReportRemark(models.Model):
    title = models.CharField(max_length=255)
    content = models.TextField()
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "title"]

    def __str__(self) -> str:
        return self.title


class ReportTemplate(models.Model):
    name = models.CharField(max_length=255, unique=True)
    sample_name = models.ForeignKey(
        SampleNameMaster,
        on_delete=models.SET_NULL,
        related_name="report_templates",
        null=True,
        blank=True,
    )
    protocol = models.ForeignKey(
        ProtocolMaster,
        on_delete=models.SET_NULL,
        related_name="report_templates",
        null=True,
        blank=True,
    )
    description = models.CharField(max_length=255, blank=True)
    content = models.TextField()
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:
            self.__class__.objects.exclude(pk=self.pk).filter(is_default=True).update(is_default=False)


class TDSDocumentTemplate(models.Model):
    class DocumentType(models.TextChoices):
        CS = "cs", "CS"
        ADS = "ads", "ADS"
        AC = "ac", "AC"
        CHECKLIST = "checklist", "Checklist"
        TRF = "trf", "TRF"
        JOB_ORDER = "job_order", "Print Job Order"

    document_type = models.CharField(max_length=20, choices=DocumentType.choices)
    name = models.CharField(max_length=255)
    test = models.ForeignKey(
        TestMaster,
        on_delete=models.SET_NULL,
        related_name="tds_document_templates",
        null=True,
        blank=True,
        help_text="Use this for ADS test-wise templates.",
    )
    description = models.CharField(max_length=255, blank=True)
    content = models.TextField(blank=True)
    source_file = models.FileField(upload_to="tds_templates/", null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["document_type", "test__name", "name"]
        unique_together = ("document_type", "name", "test")

    def __str__(self) -> str:
        test_name = f" - {self.test.name}" if self.test_id else ""
        return f"{self.get_document_type_display()}{test_name}: {self.name}"


class Report(models.Model):

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        MANAGER_APPROVED = "manager_approved", "Approved by Manager"
        INCHARGE_APPROVED = "incharge_approved", "Approved by Incharge"

    class FinalOutcome(models.TextChoices):
        DRAFT = "draft", "Draft"
        PASS = "pass", "Pass"

    booking = models.OneToOneField(
        Booking,
        on_delete=models.CASCADE,
        related_name="report"
    )

    analysis_end_date = models.DateTimeField(null=True, blank=True)
    report_template = models.ForeignKey(
        ReportTemplate,
        on_delete=models.SET_NULL,
        related_name="reports",
        null=True,
        blank=True,
    )

    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="managed_reports",
        null=True,
        blank=True,
    )

    manager_name = models.CharField(max_length=255, blank=True)
    manager_signature = models.CharField(max_length=255, blank=True)

    incharge = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="incharge_reports",
        null=True,
        blank=True,
    )

    incharge_name = models.CharField(max_length=255, blank=True)
    incharge_signature = models.CharField(max_length=255, blank=True)

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.DRAFT
    )

    ceo_content = models.TextField(blank=True)
    final_outcome = models.CharField(
        max_length=10,
        choices=FinalOutcome.choices,
        default=FinalOutcome.DRAFT,
    )
    selected_remark = models.ForeignKey(
        ReportRemark,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reports",
    )
    remark_text = models.TextField(blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reports",
        null=True,
        blank=True,
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="updated_reports",
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def certificate_no(self) -> str:
        booking = self.booking

        if not booking:
            return "-"

        source_date = booking.sample_receipt_date or booking.booking_date
        if not source_date:
            return "-"

        booking_type = "REG" if booking.booking_type == Booking.BookingType.REGULATORY else "GEN"

        reg_no = booking.sample_reg_no or ""
        try:
            sequence = int(reg_no.rsplit("/", 1)[-1])
        except (TypeError, ValueError):
            sequence = self.pk or 1

        return f"ARL/{booking_type}/{source_date.strftime('%y%m%d')}{sequence:03d}"

    @property
    def test_names(self) -> str:
        return ", ".join(
            self.booking.test_to_be_performed.values_list("name", flat=True)
        )

    @property
    def tests_with_templates(self):
        """Return tests that have assigned report templates (e.g., Assay)."""
        return self.booking.test_to_be_performed.select_related("report_template").filter(
            report_template__isnull=False,
            report_template__is_active=True,
        ).order_by("name")

    @property
    def tests_without_templates(self):
        """Return tests that don't have assigned report templates."""
        return self.booking.test_to_be_performed.select_related("report_template").filter(
            report_template__isnull=True,
        ).order_by("name")

    @property
    def generic_tests_table_html(self):
        """Generate HTML table for tests without custom templates."""
        tests_without = self.tests_without_templates
        if not tests_without.exists():
            return ""
        return build_tests_without_templates_table(tests_without)

    def approve_by_manager(self, manager_user, incharge_user=None):
        self.manager = manager_user
        self.manager_name = manager_user.get_full_name() or manager_user.username
        self.updated_by = manager_user
        signature_url = None
        profile = getattr(manager_user, "profile", None)
        if profile and getattr(profile, "signature_file", None):
            try:
                signature_url = profile.signature_file.url
            except Exception:
                signature_url = None
        if signature_url:
            self.manager_signature = f'<img src="{escape(signature_url)}" alt="Checked by signature">'
        else:
            self.manager_signature = "Digitally Signed"

        self.incharge = incharge_user

        if incharge_user:
            self.incharge_name = (
                incharge_user.get_full_name() or incharge_user.username
            )
            incharge_sig_url = None
            profile = getattr(incharge_user, "profile", None)
            if profile and getattr(profile, "signature_file", None):
                try:
                    incharge_sig_url = profile.signature_file.url
                except Exception:
                    incharge_sig_url = None
            if incharge_sig_url:
                self.incharge_signature = f'<img src="{escape(incharge_sig_url)}" alt="Incharge signature">'
            else:
                self.incharge_signature = "Digital Sign"
            self.status = self.Status.INCHARGE_APPROVED
        else:
            self.incharge_name = ""
            self.incharge_signature = ""
            self.status = self.Status.MANAGER_APPROVED

        self.save(
            update_fields=[
                "manager",
                "manager_name",
                "manager_signature",
                "incharge",
                "incharge_name",
                "incharge_signature",
                "status",
                "updated_by",
                "updated_at",
            ]
        )

    @property
    def updated_by_display(self) -> str:
        actor = self.updated_by or self.manager or self.created_by
        if not actor:
            return "-"
        return actor.get_full_name() or actor.username

    def __str__(self) -> str:
        reg = self.booking.sample_reg_no if self.booking else None
        return f"Report - {reg or 'No Reg No'}"
