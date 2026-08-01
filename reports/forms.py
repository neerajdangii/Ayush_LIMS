from html import escape
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET

from django import forms
from django.db.models import Q
from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import COALetterhead, Report, ReportRemark, ReportTemplate, TDSDocumentTemplate
from .template_library import build_generic_result_table, populate_main_table_rows

DATE_FORMAT_DMY = "%d/%m/%Y"
DATE_INPUT_FORMAT = "%Y-%m-%d"
DATE_PLACEHOLDER = "DD/MM/YYYY"

WORD_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
WORD_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _word_attr(element, name):
    return element.get(f"{WORD_W}{name}") if element is not None else None


def _css_style(style_parts):
    style = ";".join(part for part in style_parts if part)
    return f' style="{style}"' if style else ""


def _twips_to_pt(value):
    try:
        return round(int(value) / 20, 2)
    except (TypeError, ValueError):
        return None


def _extract_docx_run_html(run):
    text_parts = []
    for child in run:
        tag_name = child.tag.rsplit("}", 1)[-1]
        if tag_name == "t":
            text_parts.append(escape(child.text or ""))
        elif tag_name == "tab":
            text_parts.append("&emsp;")
        elif tag_name == "br":
            text_parts.append("<br>")

    text = "".join(text_parts)
    if not text:
        return ""

    props = run.find("w:rPr", WORD_NS)
    if props is not None:
        if props.find("w:b", WORD_NS) is not None:
            text = f"<strong>{text}</strong>"
        if props.find("w:i", WORD_NS) is not None:
            text = f"<em>{text}</em>"
        if props.find("w:u", WORD_NS) is not None:
            text = f"<u>{text}</u>"
    return text


def _extract_docx_paragraph_html(paragraph):
    props = paragraph.find("w:pPr", WORD_NS)
    style_parts = []
    if props is not None:
        jc = props.find("w:jc", WORD_NS)
        align = _word_attr(jc, "val")
        if align in {"center", "right", "both"}:
            style_parts.append(f"text-align:{'justify' if align == 'both' else align}")

        spacing = props.find("w:spacing", WORD_NS)
        before = _twips_to_pt(_word_attr(spacing, "before"))
        after = _twips_to_pt(_word_attr(spacing, "after"))
        line = _word_attr(spacing, "line")
        line_rule = _word_attr(spacing, "lineRule")
        if before is not None:
            style_parts.append(f"margin-top:{before}pt")
        if after is not None:
            style_parts.append(f"margin-bottom:{after}pt")
        if line:
            try:
                line_value = int(line)
                if line_rule in {"exact", "atLeast"}:
                    style_parts.append(f"line-height:{round(line_value / 20, 2)}pt")
                else:
                    style_parts.append(f"line-height:{round(line_value / 240, 2)}")
            except ValueError:
                pass

    runs = [_extract_docx_run_html(run) for run in paragraph.findall("w:r", WORD_NS)]
    content = "".join(runs).strip()
    if not content:
        content = "&nbsp;"
    return f"<p{_css_style(style_parts)}>{content}</p>"


def _extract_docx_printable_html(uploaded_file):
    uploaded_file.seek(0)
    with zipfile.ZipFile(uploaded_file) as docx:
        xml_content = docx.read("word/document.xml")
    root = ET.fromstring(xml_content)
    body = root.find("w:body", WORD_NS)
    if body is None:
        return ""

    blocks = []
    for child in body:
        tag_name = child.tag.rsplit("}", 1)[-1]
        if tag_name == "p":
            blocks.append(_extract_docx_paragraph_html(child))
        elif tag_name == "tbl":
            table_props = child.find("w:tblPr", WORD_NS)
            table_width = None
            if table_props is not None:
                width = table_props.find("w:tblW", WORD_NS)
                if _word_attr(width, "type") == "pct":
                    try:
                        table_width = f"width:{round(int(_word_attr(width, 'w')) / 50, 2)}%"
                    except (TypeError, ValueError):
                        table_width = None
            rows = []
            for row in child.findall(".//w:tr", WORD_NS):
                cells = []
                for cell in row.findall("./w:tc", WORD_NS):
                    cell_props = cell.find("w:tcPr", WORD_NS)
                    grid_span = cell_props.find("w:gridSpan", WORD_NS) if cell_props is not None else None
                    colspan = _word_attr(grid_span, "val")
                    colspan_attr = f' colspan="{escape(colspan)}"' if colspan else ""
                    cell_blocks = [_extract_docx_paragraph_html(para) for para in cell.findall("./w:p", WORD_NS)]
                    cell_content = "".join(cell_blocks) or "&nbsp;"
                    cells.append(f"<td{colspan_attr}>{cell_content}</td>")
                if cells:
                    rows.append(f"<tr>{''.join(cells)}</tr>")
            if rows:
                table_style = _css_style(["border-collapse:collapse", table_width or "width:100%"])
                blocks.append(f"<table border=\"1\" cellspacing=\"0\" cellpadding=\"4\"{table_style}><tbody>{''.join(rows)}</tbody></table>")
    return "\n".join(blocks)


def _extract_uploaded_printable_content(uploaded_file):
    if not uploaded_file:
        return ""
    suffix = Path(uploaded_file.name or "").suffix.lower()
    uploaded_file.seek(0)
    try:
        if suffix == ".docx":
            return _extract_docx_printable_html(uploaded_file)
        if suffix in {".html", ".htm"}:
            return uploaded_file.read().decode("utf-8", errors="ignore").strip()
        if suffix == ".txt":
            text = uploaded_file.read().decode("utf-8", errors="ignore").strip()
            return "\n".join(f"<p>{escape(line)}</p>" for line in text.splitlines() if line.strip())
    finally:
        uploaded_file.seek(0)
    return ""


def _local_date(value):
    if not value:
        return None
    if hasattr(value, "tzinfo") and timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.date() if hasattr(value, "date") else value


class ReportApprovalForm(forms.ModelForm):
    incharge_user = forms.ModelChoiceField(
        queryset=get_user_model().objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Person In-charge",
    )
    analysis_start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(
            format=DATE_FORMAT_DMY,
            attrs={
                "type": "text",
                "class": "form-control booking-date-input",
                "placeholder": DATE_PLACEHOLDER,
                "data-picker-kind": "date",
                "data-close-on-pick": "1",
                "autocomplete": "off",
                "title": "",
            },
        ),
    )
    analysis_end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(
            format=DATE_FORMAT_DMY,
            attrs={
                "type": "text",
                "class": "form-control booking-date-input",
                "placeholder": DATE_PLACEHOLDER,
                "data-picker-kind": "date",
                "data-close-on-pick": "1",
                "autocomplete": "off",
                "title": "",
            },
        ),
    )

    class Meta:
        model = Report
        fields = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        UserModel = get_user_model()
        incharge_qs = (
            UserModel.objects.filter(is_active=True, groups__name="Incharge")
            .order_by("first_name", "last_name", "username")
            .distinct()
        )
        self.fields["incharge_user"].queryset = incharge_qs
        self.fields["analysis_start_date"].input_formats = [DATE_INPUT_FORMAT, DATE_FORMAT_DMY]
        self.fields["analysis_end_date"].input_formats = [DATE_INPUT_FORMAT, DATE_FORMAT_DMY]
        if self.instance and self.instance.pk and self.instance.booking_id:
            self.fields["analysis_start_date"].initial = _local_date(self.instance.booking.analysis_start_date)
            self.fields["analysis_end_date"].initial = _local_date(self.instance.booking.analysis_end_date)
            if self.instance.incharge_id:
                self.fields["incharge_user"].initial = self.instance.incharge_id
            else:
                default_incharge = incharge_qs.first()
                if default_incharge:
                    self.fields["incharge_user"].initial = default_incharge.pk


class COAEditForm(forms.ModelForm):
    selected_remarks = forms.ModelMultipleChoiceField(
        queryset=ReportRemark.objects.none(),
        required=False,
        widget=forms.SelectMultiple(attrs={"class": "d-none", "id": "id_selected_remarks", "size": 4}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        active_remarks = ReportRemark.objects.filter(is_active=True)
        self.fields["selected_remark"].queryset = active_remarks
        self.fields["selected_remarks"].queryset = active_remarks
        if self.instance and self.instance.selected_remark_id:
            self.initial["selected_remarks"] = [self.instance.selected_remark_id]
        current_template_id = self.instance.report_template_id if self.instance else None
        self.fields["report_template"].queryset = ReportTemplate.objects.filter(
            Q(is_active=True) | Q(pk=current_template_id)
        ).select_related("sample_name", "protocol")

        selected_template = self.instance.report_template if self.instance and self.instance.report_template_id else None
        if not selected_template:
            selected_template = self._suggest_template()
        if selected_template:
            self.initial["report_template"] = selected_template.pk
            self.fields["report_template"].initial = selected_template.pk

        existing_content = (self.instance.ceo_content or "") if self.instance else ""
        if existing_content:
            self.initial["ceo_content"] = existing_content
            self.fields["ceo_content"].initial = existing_content
        else:
            default_content = self._build_default_content(selected_template)
            self.initial["ceo_content"] = default_content
            self.fields["ceo_content"].initial = default_content

    def save(self, commit=True):
        # Save the Report instance first, then persist any certificate number override
        report = super().save(commit=commit)
        cert = self.cleaned_data.get('certificate_no') if hasattr(self, 'cleaned_data') else None
        if cert is not None and getattr(report, 'booking', None):
            booking = report.booking
            # Empty string should clear the manual override
            booking.manual_certificate_no = cert.strip() or None
            try:
                booking.save(update_fields=['manual_certificate_no', 'updated_at'])
            except Exception:
                booking.save()
        return report

        # Certificate number editable field (maps to booking.manual_certificate_no)
        self.fields['certificate_no'] = forms.CharField(
            required=False,
            widget=forms.TextInput(attrs={'class': 'form-control'}),
            label='Certificate No.',
        )
        if self.instance and getattr(self.instance, 'booking', None):
            # Prefer showing the booking's manual override if set, otherwise computed certificate_no
            booking = self.instance.booking
            current = booking.manual_certificate_no if booking.manual_certificate_no else booking.certificate_no
            self.initial['certificate_no'] = current

    def _selected_tests(self):
        if not self.instance or not getattr(self.instance, "booking", None):
            return []
        return list(
            self.instance.booking.test_to_be_performed.select_related("report_template").order_by("name")
        )

    def _has_assay_test(self, tests=None):
        selected_tests = tests if tests is not None else self._selected_tests()
        return any((test.name or "").strip().lower() == "assay" for test in selected_tests)

    def _build_default_content(self, selected_template=None):
        tests = self._selected_tests()
        selected_test_names = []
        template_html_blocks = []
        seen_template_ids = set()
        has_assay_test = self._has_assay_test(tests)

        for test in tests:
            if (test.name or "").strip():
                selected_test_names.append(test.name.strip())

            template = getattr(test, "report_template", None)
            if (
                has_assay_test
                and (test.name or "").strip().lower() == "assay"
                and template
                and template.is_active
                and template.content.strip()
            ):
                if template.pk not in seen_template_ids:
                    template_html_blocks.append(template.content.strip())
                    seen_template_ids.add(template.pk)

        content_blocks = []
        if (
            selected_template
            and selected_template.is_active
            and selected_template.content.strip()
        ):
            if selected_template.pk not in seen_template_ids:
                populated_template = populate_main_table_rows(
                    selected_template.content.strip(),
                    selected_test_names,
                )
                content_blocks.append(populated_template)
                seen_template_ids.add(selected_template.pk)

        content_blocks.extend(template_html_blocks)

        if not content_blocks:
            return build_generic_result_table(selected_test_names)

        return "\n<p>&nbsp;</p>\n".join(content_blocks)

    def _suggest_template(self):
        if not self.instance or not getattr(self.instance, "booking", None):
            return None

        booking = self.instance.booking
        queryset = ReportTemplate.objects.filter(is_active=True)
        default_template = queryset.filter(is_default=True).first()

        if default_template:
            return default_template

        tests = self._selected_tests()
        if not self._has_assay_test(tests):
            return None

        test_template = (
            booking.test_to_be_performed.filter(report_template__is_active=True)
            .select_related("report_template")
            .order_by("name")
            .first()
        )
        if test_template and test_template.report_template_id:
            return test_template.report_template

        if booking.sample_name_id and booking.protocol_id:
            exact = queryset.filter(sample_name_id=booking.sample_name_id, protocol_id=booking.protocol_id).first()
            if exact:
                return exact
        if booking.sample_name_id:
            by_sample = queryset.filter(sample_name_id=booking.sample_name_id, protocol__isnull=True).first()
            if by_sample:
                return by_sample
        if booking.protocol_id:
            by_protocol = queryset.filter(sample_name__isnull=True, protocol_id=booking.protocol_id).first()
            if by_protocol:
                return by_protocol
        return default_template or queryset.filter(sample_name__isnull=True, protocol__isnull=True).first()

    def clean(self):
        cleaned_data = super().clean()
        selected_remarks = list(cleaned_data.get("selected_remarks") or [])
        remark_text = (cleaned_data.get("remark_text") or "").strip()

        if selected_remarks:
            cleaned_data["selected_remark"] = selected_remarks[0]
        else:
            cleaned_data["selected_remark"] = None

        if selected_remarks and not remark_text:
            cleaned_data["remark_text"] = "\n".join(
                content for content in [remark.content.strip() for remark in selected_remarks] if content
            )

        return cleaned_data

    def clean_ceo_content(self):
        return (self.cleaned_data.get("ceo_content") or "").strip()

    class Meta:
        model = Report
        fields = [
            "report_template",
            "ceo_content",
            "final_outcome",
            "selected_remarks",
            "selected_remark",
            "remark_text",
        ]
        widgets = {
            "report_template": forms.Select(attrs={"class": "form-select", "id": "id_report_template"}),
            "ceo_content": forms.Textarea(
                attrs={
                    "class": "form-control tinymce-editor",
                    "id": "editor",
                    "rows": 16,
                    "data-editor": "tinymce",
                }
            ),
            "final_outcome": forms.Select(attrs={"class": "form-select"}),
            "selected_remark": forms.HiddenInput(),
            "remark_text": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
        }
        labels = {
            "report_template": "Report Template",
            "ceo_content": "CEO Content",
            "final_outcome": "Final Outcome",
            "selected_remarks": "Remark Master",
            "remark_text": "Remarks",
        }


class ReportTemplateForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("is_default"):
            cleaned_data["is_active"] = True
        
        # Validate that content is not empty (only on new templates)
        content = cleaned_data.get("content", "").strip()
        if not self.instance.pk and (not content or content == ""):
            raise forms.ValidationError("Template content cannot be empty. Please add content to your template.")
        
        return cleaned_data

    class Meta:
        model = ReportTemplate
        fields = ["name", "description", "content", "is_active", "is_default"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.TextInput(attrs={"class": "form-control"}),
            "content": forms.Textarea(
                attrs={
                    "class": "form-control tinymce-editor",
                    "rows": 18,
                    "data-editor": "tinymce",
                }
            ),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_default": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean_content(self):
        content = self.cleaned_data.get("content") or ""
        return content.strip() if isinstance(content, str) else content


class COALetterheadForm(forms.ModelForm):
    IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

    class Meta:
        model = COALetterhead
        fields = ["layout_mode", "full_image", "header_image", "middle_image", "footer_image", "is_active"]
        widgets = {
            "layout_mode": forms.Select(attrs={"class": "form-select"}),
            "full_image": forms.ClearableFileInput(attrs={"class": "form-control", "accept": "image/*"}),
            "header_image": forms.ClearableFileInput(attrs={"class": "form-control", "accept": "image/*"}),
            "middle_image": forms.ClearableFileInput(attrs={"class": "form-control", "accept": "image/*"}),
            "footer_image": forms.ClearableFileInput(attrs={"class": "form-control", "accept": "image/*"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "layout_mode": "Letterhead Option",
            "full_image": "Full Page Letterhead",
            "header_image": "Header Image",
            "middle_image": "Middle Watermark / Body Image",
            "footer_image": "Footer Image",
            "is_active": "Use uploaded letterhead",
        }

    def clean(self):
        cleaned_data = super().clean()
        mode = cleaned_data.get("layout_mode")

        for field_name in ("full_image", "header_image", "middle_image", "footer_image"):
            uploaded = cleaned_data.get(field_name)
            if uploaded and Path(uploaded.name or "").suffix.lower() not in self.IMAGE_EXTENSIONS:
                self.add_error(field_name, "Upload an image file: JPG, PNG, WEBP, or GIF.")

        def current_file(field_name):
            value = cleaned_data.get(field_name)
            if value is False:
                return None
            return value or getattr(self.instance, field_name, None)

        if mode == COALetterhead.LayoutMode.FULL:
            full_image = current_file("full_image")
            if not full_image:
                raise forms.ValidationError("Upload a full page letterhead image, or choose the default option.")
        if mode == COALetterhead.LayoutMode.PARTS:
            has_part = any(
                current_file(field)
                for field in ("header_image", "middle_image", "footer_image")
            )
            if not has_part:
                raise forms.ValidationError("Upload at least one header, middle, or footer image, or choose the default option.")
        return cleaned_data


class TDSDocumentTemplateForm(forms.ModelForm):
    class Meta:
        model = TDSDocumentTemplate
        fields = [
            "document_type",
            "name",
            "test",
            "description",
            "display_mode",
            "header_content",
            "content",
            "footer_content",
            "source_file",
            "is_active",
        ]
        widgets = {
            "document_type": forms.Select(attrs={"class": "form-select"}),
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "test": forms.Select(attrs={"class": "form-select"}),
            "description": forms.TextInput(attrs={"class": "form-control"}),
            "display_mode": forms.Select(attrs={"class": "form-select"}),
            "content": forms.Textarea(
                attrs={
                    "class": "form-control tinymce-editor",
                    "rows": 18,
                    "data-editor": "tinymce",
                }
            ),
            "header_content": forms.Textarea(
                attrs={
                    "class": "form-control tinymce-editor",
                    "rows": 6,
                    "data-editor": "tinymce-header",
                    "placeholder": "Optional header shown on every page",
                }
            ),
            "footer_content": forms.Textarea(
                attrs={
                    "class": "form-control tinymce-editor",
                    "rows": 6,
                    "data-editor": "tinymce-footer",
                    "placeholder": "Optional formatted footer, or document number",
                }
            ),
            "source_file": forms.ClearableFileInput(attrs={"class": "form-control", "accept": ".doc,.docx,.pdf,.html,.htm,.txt"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "test": "Test link for ADS",
            "display_mode": "Display Option",
            "content": "Printable Content",
            "header_content": "Page Header (optional)",
            "footer_content": "Page Footer / Document Number (optional)",
            "source_file": "Word/PDF Source File",
        }

    def clean(self):
        cleaned_data = super().clean()
        display_mode = cleaned_data.get("display_mode") or TDSDocumentTemplate.DisplayMode.EDITABLE
        content = (cleaned_data.get("content") or "").strip()
        source_file = cleaned_data.get("source_file") or getattr(self.instance, "source_file", None)
        uploaded_file = cleaned_data.get("source_file")

        if display_mode == TDSDocumentTemplate.DisplayMode.SOURCE_FILE:
            if not source_file:
                raise forms.ValidationError("Upload a Word/PDF/HTML/TXT file for direct display mode.")
            cleaned_data["content"] = content
            return cleaned_data

        if not content and uploaded_file:
            content = _extract_uploaded_printable_content(uploaded_file)
            if not content:
                raise forms.ValidationError(
                    "Could not read printable content from this file. Upload a .docx, .html, or .txt file, or paste content manually."
                )
        if not content and not source_file:
            raise forms.ValidationError("Add printable content or upload a source file.")
        cleaned_data["content"] = content
        return cleaned_data
