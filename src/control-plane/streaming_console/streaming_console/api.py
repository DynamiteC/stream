import frappe
from frappe import _

@frappe.whitelist()
def get_best_node():
    """
    Finds the Streaming Node with the lowest current load that is Active.
    """
    # SQL Query to find active node with load < capacity
    nodes = frappe.db.sql("""
        SELECT name, ip_address, current_load
        FROM `tabStreaming Node`
        WHERE status = 'Active'
          AND current_load < max_capacity
        ORDER BY current_load ASC
        LIMIT 1
    """, as_dict=True)

    if not nodes:
        frappe.throw(_("No capacity available across the fleet."))

    best_node = nodes[0]
    return {
        "node_id": best_node.name,
        "ip": best_node.ip_address
    }

@frappe.whitelist(allow_guest=True)
def on_publish(stream_key=None):
    """
    SRS Hook: Called when a stream starts.
    """
    if not stream_key:
        return {"code": 1, "msg": "Missing stream_key"}

    # Validate Stream
    stream = frappe.db.get_value("Live Stream", {"stream_key": stream_key}, ["name", "assigned_node"], as_dict=True)
    if not stream:
        return {"code": 1, "msg": "Invalid Stream Key"}

    # Update Status
    frappe.db.set_value("Live Stream", stream.name, {
        "status": "Live",
        "start_time": frappe.utils.now_datetime()
    })

    # Increment Node Load (if node logic is tracking strict assignment)
    # Ideally, we would increment the load on the node that actually received it.

    return {"code": 0, "msg": "OK"}

@frappe.whitelist(allow_guest=True)
def on_unpublish(stream_key=None):
    """
    SRS Hook: Called when a stream ends.
    """
    if not stream_key:
        return

    stream = frappe.db.get_value("Live Stream", {"stream_key": stream_key}, "name")
    if stream:
        frappe.db.set_value("Live Stream", stream, {
            "status": "Ended",
            "end_time": frappe.utils.now_datetime()
        })

    return {"code": 0, "msg": "OK"}
