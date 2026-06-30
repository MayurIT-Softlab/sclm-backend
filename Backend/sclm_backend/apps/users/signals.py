"""
apps.users.signals
Wires up signals for the users module.
Currently used to ensure TenantUserMapping integrity.
Audit signals (to audit_ledger) will be connected in Step 3.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver
import logging

logger = logging.getLogger(__name__)


# Step 3 will add audit_ledger signal connections here.
# Pattern will be:
#
#   @receiver(post_save, sender=GlobalUser)
#   def capture_user_audit(sender, instance, created, **kwargs):
#       from apps.audit_ledger.services import SnapshotGeneratorService
#       SnapshotGeneratorService.capture(
#           table_name="users_globaluser",
#           record_id=instance.id,
#           action="CREATE" if created else "UPDATE",
#           instance=instance,
#       )
