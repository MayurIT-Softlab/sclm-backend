"""
apps.logistics.tasks
"""
import logging
from celery import shared_task
from django_tenants.utils import schema_context

logger = logging.getLogger(__name__)


@shared_task
def poll_ocean_carriers():
    """
    Periodic Celery beat task (e.g., every 4 hours).
    Loops through all active tenant schemas and calls the OceanFreightPoller
    to update milestones for active InboundContainers.
    """
    from apps.subscriptions.models import Client

    logger.info("Starting global Ocean Carrier polling...")
    tenants = Client.objects.exclude(schema_name="public")

    global_results = {}
    for tenant in tenants:
        with schema_context(tenant.schema_name):
            logger.info("Polling carriers for tenant: %s", tenant.schema_name)
            try:
                from apps.logistics.services import OceanFreightPoller
                results = OceanFreightPoller.poll_all_active_containers()
                global_results[tenant.schema_name] = results
                logger.info("Tenant %s Polling results: %s", tenant.schema_name, results)
            except Exception as exc:
                logger.error(
                    "Error polling carriers for tenant '%s': %s",
                    tenant.schema_name,
                    exc,
                    exc_info=True,
                )

    return global_results
