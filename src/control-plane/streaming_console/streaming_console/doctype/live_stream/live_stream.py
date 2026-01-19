import frappe
import secrets
from frappe.model.document import Document

class LiveStream(Document):
    def before_insert(self):
        # Auto-generate Stream Key if not provided
        if not self.stream_key:
            self.stream_key = secrets.token_hex(16)

        # Default status
        self.status = "Offline"
