from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile

from django.conf import settings
from django.core.files import File
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


class COALetterhead(models.Model):
    class LayoutMode(models.TextChoices):
        DEFAULT = "default", "Use current default"
        FULL = "full", "Full page image"
        PARTS = "parts", "Header / Middle / Footer"

    name = models.CharField(max_length=120, default="COA Letterhead")
    layout_mode = models.CharField(max_length=20, choices=LayoutMode.choices, default=LayoutMode.DEFAULT)
    full_image = models.FileField(upload_to="coa_letterheads/", null=True, blank=True)
    header_image = models.FileField(upload_to="coa_letterheads/", null=True, blank=True)
    middle_image = models.FileField(upload_to="coa_letterheads/", null=True, blank=True)
    footer_image = models.FileField(upload_to="coa_letterheads/", null=True, blank=True)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "COA Letterhead"
        verbose_name_plural = "COA Letterhead"

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_active(cls):
        letterhead = cls.objects.filter(pk=1, is_active=True).first()
        if not letterhead or letterhead.layout_mode == cls.LayoutMode.DEFAULT:
            return None
        if letterhead.layout_mode == cls.LayoutMode.FULL and not letterhead.has_full_image:
            return None
        if letterhead.layout_mode == cls.LayoutMode.PARTS and not letterhead.has_part_images:
            return None
        return letterhead

    @property
    def has_full_image(self):
        return bool(self.full_image)

    @property
    def has_part_images(self):
        return bool(self.header_image or self.middle_image or self.footer_image)


class TDSDocumentTemplate(models.Model):
    class DocumentType(models.TextChoices):
        CS = "cs", "CS"
        ADS = "ads", "ADS"
        AC = "ac", "AC"
        CHECKLIST = "checklist", "Checklist"
        TRF = "trf", "TRF"
        JOB_ORDER = "job_order", "Print Job Order"

    class DisplayMode(models.TextChoices):
        EDITABLE = "editable", "Editable content"
        SOURCE_FILE = "source_file", "Display uploaded file"

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
    display_mode = models.CharField(max_length=20, choices=DisplayMode.choices, default=DisplayMode.EDITABLE)
    header_content = models.TextField(blank=True)
    content = models.TextField(blank=True)
    footer_content = models.TextField(blank=True)
    source_file = models.FileField(upload_to="tds_templates/", null=True, blank=True)
    source_preview_file = models.FileField(upload_to="tds_template_previews/", null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["document_type", "test__name", "name"]
        unique_together = ("document_type", "name", "test")

    def __str__(self) -> str:
        test_name = f" - {self.test.name}" if self.test_id else ""
        return f"{self.get_document_type_display()}{test_name}: {self.name}"

    def generate_source_preview(self):
        if not self.source_file:
            return False, "No source file uploaded."

        suffix = Path(self.source_file.name or "").suffix.lower()
        if suffix == ".pdf":
            return True, "PDF source file will be displayed directly."
        if suffix not in {".doc", ".docx"}:
            return True, "This source file type does not need PDF conversion."

        converter = shutil.which("libreoffice") or shutil.which("soffice")
        if not converter:
            return False, "LibreOffice is not installed, so Word preview PDF could not be generated."

        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = Path(tmp_dir) / f"source{suffix}"
            output_path = Path(tmp_dir) / "source.pdf"

            self.source_file.open("rb")
            try:
                input_path.write_bytes(self.source_file.read())
            finally:
                self.source_file.close()

            result = subprocess.run(
                [
                    converter,
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    tmp_dir,
                    str(input_path),
                ],
                check=False,
                capture_output=True,
                timeout=60,
            )
            if result.returncode != 0 or not output_path.exists():
                detail = (result.stderr or result.stdout or b"").decode("utf-8", errors="ignore").strip()
                return False, detail or "Word preview PDF could not be generated."

            preview_name = f"{Path(self.source_file.name).stem}.pdf"
            with output_path.open("rb") as preview:
                self.source_preview_file.save(preview_name, File(preview), save=False)
        return True, "Word file converted to PDF preview."


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
        return booking.certificate_no

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
        reg = self.booking.sample_registration_no if self.booking else None
        return f"Report - {reg or 'No Reg No'}"
