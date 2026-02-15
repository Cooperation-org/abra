#!/usr/bin/env python3
"""
Odoo CRM connector for abra.

Reads connection config from ~/.abra/sources.yaml (sinks.crm section).
Writes contacts to Odoo with abra_catcode field.

Usage:
    from connector import OdooConnector
    crm = OdooConnector()  # reads config from sources.yaml
    if crm.is_ready():
        contact_id = crm.create_contact(name="Leanne Ussher", email="...", catcode="usv0gvcob1lu")
"""
import os
import xmlrpc.client
import yaml
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))


def load_crm_config():
    """Load CRM sink config from ~/.abra/sources.yaml."""
    sources_path = os.path.expanduser("~/.abra/sources.yaml")
    if not os.path.exists(sources_path):
        return None
    with open(sources_path) as f:
        config = yaml.safe_load(f)
    return config.get("sinks", {}).get("crm")


class OdooConnector:
    def __init__(self, config=None):
        self.config = config or load_crm_config()
        self._uid = None
        self._models = None

    def is_ready(self):
        """Check if CRM config is present and marked ready."""
        if not self.config:
            return False
        if self.config.get("status") != "ready":
            return False
        return all(self.config.get(k) for k in ("url", "db", "user"))

    def _connect(self):
        """Establish connection to Odoo XML-RPC API."""
        if self._models:
            return
        url = self.config["url"]
        db = self.config["db"]
        user = self.config["user"]
        api_key = self.config.get("api_key") or os.getenv("ODOO_API_KEY", "")

        common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
        self._uid = common.authenticate(db, user, api_key, {})
        if not self._uid:
            raise ConnectionError("Failed to authenticate with Odoo")
        self._models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

    def _execute(self, model, method, *args, **kwargs):
        """Execute an Odoo model method."""
        self._connect()
        return self._models.execute_kw(
            self.config["db"], self._uid,
            self.config.get("api_key") or os.getenv("ODOO_API_KEY", ""),
            model, method, args, kwargs
        )

    def create_contact(self, name, catcode=None, email=None, phone=None,
                       company=None, notes=None):
        """Create a contact in Odoo. Returns the Odoo record ID."""
        vals = {"name": name}
        if email:
            vals["email"] = email
        if phone:
            vals["phone"] = phone
        if company:
            vals["company_name"] = company
        if notes:
            vals["comment"] = notes
        catcode_field = self.config.get("catcode_field", "abra_catcode")
        if catcode:
            vals[catcode_field] = catcode
        result = self._execute("res.partner", "create", [vals])
        # Odoo returns a list when passed a list of vals; unwrap to single ID
        if isinstance(result, list):
            return result[0]
        return result

    def find_contact(self, name=None, email=None, catcode=None):
        """Search for existing contact. Returns list of IDs."""
        domain = []
        if name:
            domain.append(("name", "ilike", name))
        if email:
            domain.append(("email", "=", email))
        if catcode:
            catcode_field = self.config.get("catcode_field", "abra_catcode")
            domain.append((catcode_field, "=", catcode))
        return self._execute("res.partner", "search", domain)

    def update_contact(self, record_id, **fields):
        """Update an existing contact."""
        catcode_field = self.config.get("catcode_field", "abra_catcode")
        vals = {}
        for k, v in fields.items():
            if k == "catcode":
                vals[catcode_field] = v
            else:
                vals[k] = v
        return self._execute("res.partner", "write", [record_id], vals)
