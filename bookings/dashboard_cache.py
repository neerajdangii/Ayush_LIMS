"""Short-lived shared data for the dashboard's non-personalized fragments."""

from django.core.cache import cache
from django.db.models import Count
from django.utils.translation import get_language

from reports.models import Report, ReportTemplate, TDSDocumentTemplate

from .models import Booking
DASHBOARD_METRICS_TTL_SECONDS = 60


def dashboard_metrics(master_config):
    """Return shared counts without caching user-specific dashboard content."""
    language = get_language() or "default"
    cache_key = f"dashboard:metrics:v1:{language}"
    metrics = cache.get(cache_key)
    if metrics is not None:
        return metrics

    metrics = {
        "counts": list(Booking.objects.values("status").annotate(total=Count("id"))),
        "reports_total": Report.objects.count(),
        "report_templates_total": ReportTemplate.objects.count(),
        "tds_templates_total": TDSDocumentTemplate.objects.count(),
        "masters": [
            {"slug": slug, "title": conf["title"], "count": conf["model"].objects.count()}
            for slug, conf in master_config.items()
        ],
    }
    cache.set(cache_key, metrics, DASHBOARD_METRICS_TTL_SECONDS)
    return metrics
