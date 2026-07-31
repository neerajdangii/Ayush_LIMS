from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError, models
from django.db.models import Max
from django.db.models.functions import Cast
from django.utils import timezone


class ActiveMasterModel(models.Model):
    name = models.CharField(max_length=255, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class CustomerMaster(ActiveMasterModel):
    address = models.TextField(blank=True)
    contact_person = models.CharField(max_length=255, blank=True)
    telephone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)


class SubmitterMaster(ActiveMasterModel):
    pass


class ManufacturerMaster(ActiveMasterModel):
    pass


class SampleNameMaster(ActiveMasterModel):
    class Discipline(models.TextChoices):
        NABL = "NABL", "NABL"
        PHARMA = "Pharma", "Pharma"

    class TestGroup(models.TextChoices):
        BIOLOGICAL = "Biological Section", "Biological Section"
        CHEMICAL_INSTRUMENT = "Chemical/Instrument Section", "Chemical/Instrument Section"

    class SampleType(models.TextChoices):
        API = "API", "API"
        FG = "FG", "FG"
        FOOD = "Food", "Food"
        RM = "RM", "RM"

    generic_name = models.CharField(max_length=255, blank=True)
    discipline = models.CharField(max_length=40, choices=Discipline.choices, blank=True)
    test_group = models.CharField(max_length=80, choices=TestGroup.choices, blank=True)
    sample_type = models.CharField(max_length=20, choices=SampleType.choices, blank=True)
    method = models.CharField(max_length=255, blank=True)
    rate = models.CharField(max_length=100, blank=True)
    observationsheet_prefix = models.CharField(max_length=100, blank=True)
    customer = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    limits = models.TextField(blank=True)

    @property
    def display_name(self) -> str:
        generic = (self.generic_name or "").strip()
        return f"{self.name} ({generic})" if generic else self.name

    def __str__(self) -> str:
        return self.display_name


class TestMaster(ActiveMasterModel):
    report_template = models.ForeignKey(
        "reports.ReportTemplate",
        on_delete=models.SET_NULL,
        related_name="linked_tests",
        null=True,
        blank=True,
    )


class ProtocolMaster(ActiveMasterModel):
    pass


class UOMMaster(ActiveMasterModel):
    pass


class Booking(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"

    class SampleType(models.TextChoices):
        API = "API", "API"
        FG = "FG", "FG"
        FOOD = "Food", "Food"
        RM = "RM", "RM"
        STABILITY = "Stability", "Stability"

    class BookingType(models.TextChoices):
        REGULATORY = "regulatory", "Regulatory"
        GENERAL = "general", "General"

    booking_date = models.DateTimeField(default=timezone.now)
    letter_date = models.DateTimeField(null=True, blank=True)
    sampling_upto = models.DateTimeField(null=True, blank=True)
    sample_receipt_date = models.DateTimeField(null=True, blank=True)
    customer = models.ForeignKey(
        CustomerMaster, on_delete=models.PROTECT, related_name="bookings", null=True, blank=True
    )
    submitter = models.ForeignKey(
        SubmitterMaster, on_delete=models.PROTECT, related_name="bookings", null=True, blank=True
    )
    manufacturer = models.ForeignKey(
        ManufacturerMaster, on_delete=models.PROTECT, related_name="bookings", null=True, blank=True
    )
    sample_name = models.ForeignKey(
        SampleNameMaster, on_delete=models.PROTECT, related_name="bookings", null=True, blank=True
    )
    sample_type = models.CharField(max_length=20, choices=SampleType.choices, blank=True)
    test_to_be_performed = models.ManyToManyField(TestMaster, related_name="bookings", blank=True)
    protocol = models.ForeignKey(
        ProtocolMaster, on_delete=models.PROTECT, related_name="bookings", null=True, blank=True
    )
    uom = models.ForeignKey(UOMMaster, on_delete=models.PROTECT, related_name="bookings", null=True, blank=True)
    booking_type = models.CharField(max_length=20, choices=BookingType.choices, default=BookingType.GENERAL)
    tracking_code = models.CharField(max_length=16, unique=True, editable=False, blank=True, default="")
    sample_reg_no = models.CharField(max_length=32, unique=True, editable=False, null=True, blank=True)
    sample_qty = models.CharField(max_length=100, blank=True)
    sample_location = models.CharField(max_length=255, blank=True)
    packaging_mode = models.CharField(max_length=255, blank=True)
    sample_condition = models.CharField(max_length=255, blank=True)
    batch_no = models.CharField(max_length=100, blank=True)
    batch_size = models.CharField(max_length=100, blank=True)
    manufacture_date = models.DateField(null=True, blank=True)
    expiry_retest_date = models.DateField(null=True, blank=True)
    license_no = models.CharField(max_length=255, blank=True)
    customer_sr_no = models.CharField(max_length=128, blank=True)
    collected_by_name = models.CharField(max_length=255, blank=True)
    sampling_procedure = models.CharField(max_length=255, blank=True)
    analysis_start_date = models.DateTimeField(null=True, blank=True)
    analysis_end_date = models.DateTimeField(null=True, blank=True)
    remarks = models.TextField(blank=True)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="bookings")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="updated_bookings",
        null=True,
        blank=True,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="approved_bookings",
        null=True,
        blank=True,
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        permissions = [
            ("view_data_sheet", "Can view Data Sheet"),
        ]

    @property
    def booking_type_code(self) -> str:
        return "REG" if self.booking_type == self.BookingType.REGULATORY else "GEN"

    @property
    def certificate_no(self) -> str:
        source_date = self.sample_receipt_date or self.booking_date
        if not source_date:
            return "-"

        if hasattr(source_date, "tzinfo") and timezone.is_aware(source_date):
            source_date = timezone.localtime(source_date)

        reg_no = self.sample_reg_no or ""
        try:
            sequence = int(reg_no.rsplit("/", 1)[-1])
        except (TypeError, ValueError):
            try:
                sequence = int(self.tracking_code)
            except (TypeError, ValueError):
                sequence = self.pk or 1

        return f"ARL/{self.booking_type_code}/{source_date.strftime('%y%m%d')}{sequence:03d}"

    @property
    def sample_registration_no(self) -> str:
        source_date = self.sample_receipt_date or self.booking_date
        if not source_date:
            return "-"

        if hasattr(source_date, "tzinfo") and timezone.is_aware(source_date):
            source_date = timezone.localtime(source_date)

        reg_no = self.sample_reg_no or ""
        try:
            sequence = int(reg_no.rsplit("/", 1)[-1])
        except (TypeError, ValueError):
            try:
                sequence = int(self.tracking_code)
            except (TypeError, ValueError):
                sequence = self.pk or 1

        return f"ARLPL/R/{source_date.strftime('%d-%m-%Y')}/{sequence:04d}"

    @classmethod
    def _next_sequence(cls, booking_date, booking_type):
        year = booking_date.year
        prefix = f"ARL/{year}/{ 'REG' if booking_type == cls.BookingType.REGULATORY else 'GEN' }/"
        max_reg = (
            cls.objects.filter(sample_reg_no__startswith=prefix)
            .aggregate(max_reg=Max("sample_reg_no"))
            .get("max_reg")
        )
        if not max_reg:
            return 1
        try:
            return int(max_reg.rsplit("/", 1)[-1]) + 1
        except (TypeError, ValueError):
            return 1

    def generate_sample_reg_no(self) -> str:
        sequence = self._next_sequence(self.booking_date, self.booking_type)
        return f"ARL/{self.booking_date.year}/{self.booking_type_code}/{sequence:04d}"

    @classmethod
    def generate_tracking_code(cls) -> str:
        numeric_codes = cls.objects.filter(tracking_code__regex=r"^\d+$").aggregate(
            max_code=Max(Cast("tracking_code", models.BigIntegerField()))
        )
        last_value = numeric_codes.get("max_code") or 999
        next_value = last_value + 1
        return str(next_value)

    @classmethod
    def get_last_similar_booking(cls, sample_name_id, customer_id):
        """Fetch the most recent booking with the same sample name and customer."""
        if not sample_name_id or not customer_id:
            return None
        return cls.objects.filter(
            sample_name_id=sample_name_id,
            customer_id=customer_id
        ).exclude(
            sample_name_id__isnull=True,
            customer_id__isnull=True
        ).order_by("-created_at").first()

    def save(self, *args, **kwargs):
        if not self.tracking_code:
            self.tracking_code = self.generate_tracking_code()
        if self.sample_reg_no:
            super().save(*args, **kwargs)
            return

        for _ in range(3):
            self.sample_reg_no = self.generate_sample_reg_no()
            try:
                super().save(*args, **kwargs)
                return
            except IntegrityError:
                self.sample_reg_no = None
                self.tracking_code = self.generate_tracking_code()
                continue
        raise IntegrityError("Unable to generate unique sample registration number.")

    def approve(self, user):
        self.status = self.Status.APPROVED
        self.approved_by = user
        self.updated_by = user
        self.approved_at = timezone.now()
        self.save(update_fields=["status", "approved_by", "updated_by", "approved_at", "updated_at"])
        # Keep report workflow in sync with approved bookings.
        from reports.models import Report

        Report.objects.get_or_create(booking=self, defaults={"created_by": user})

    @property
    def updated_by_display(self) -> str:
        actor = self.updated_by or self.approved_by or self.created_by
        if not actor:
            return "-"
        return actor.get_full_name() or actor.username

    @property
    def report_object(self):
        try:
            return self.report
        except ObjectDoesNotExist:
            return None

    @property
    def is_reported(self) -> bool:
        report = self.report_object
        return bool(report and report.status != "draft")

    def __str__(self) -> str:
        return self.sample_reg_no or self.tracking_code or f"Booking-{self.pk}"


class BillingRecord(models.Model):
    """Audit entry created when a passed report is confirmed for billing."""

    booking = models.OneToOneField(
        Booking,
        on_delete=models.PROTECT,
        related_name="billing_record",
    )
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="confirmed_billings",
    )
    confirmed_at = models.DateTimeField(default=timezone.now)
    bill_number = models.CharField(max_length=100)
    letter_date = models.DateField(null=True, blank=True)
    billing_done_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-confirmed_at", "-pk"]
        verbose_name = "Billing record"
        verbose_name_plural = "Billing records"

    def __str__(self) -> str:
        return f"Billing: {self.booking.tracking_code}"
