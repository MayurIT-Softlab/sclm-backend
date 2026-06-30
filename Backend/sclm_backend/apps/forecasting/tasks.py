"""
apps.forecasting.tasks
"""
import logging
from celery import shared_task
from django_tenants.utils import schema_context

logger = logging.getLogger(__name__)


@shared_task
def generate_draft_pos():
    """
    Nightly Celery beat task.
    Loops through all active tenant schemas and calls the AutoPODraftingService
    to generate Draft POs for any PENDING DemandPredictions.
    """
    from apps.subscriptions.models import Client

    logger.info("Starting global Draft PO generation...")
    tenants = Client.objects.exclude(schema_name="public")
    
    global_results = {}
    for tenant in tenants:
        with schema_context(tenant.schema_name):
            logger.info("Processing AutoPO for tenant: %s", tenant.schema_name)
            try:
                from apps.forecasting.services import AutoPODraftingService
                results = AutoPODraftingService.generate_all_pending()
                global_results[tenant.schema_name] = results
                logger.info("Tenant %s AutoPO results: %s", tenant.schema_name, results)
            except Exception as exc:
                logger.error(
                    "Error generating Draft POs for tenant '%s': %s",
                    tenant.schema_name,
                    exc,
                    exc_info=True,
                )
    
    return global_results
