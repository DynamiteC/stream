import frappe
from frappe import _

from streaming_console.secure_link import append_token, sign

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
def get_playback_urls(stream_key=None):
    """
    Generates playback URLs for a given stream key based on the assigned node.
    """
    if not stream_key:
        frappe.throw(_("Missing stream_key"))

    stream = frappe.db.get_value("Live Stream", {"stream_key": stream_key}, ["name", "assigned_node"], as_dict=True)
    if not stream:
        frappe.throw(_("Invalid Stream Key"))

    node_ip = "127.0.0.1" # Default
    if stream.assigned_node:
        node_ip = frappe.get_cached_value("Streaming Node", stream.assigned_node, "ip_address")

    # Fetch CDN domain from settings (cached)
    cdn_host = frappe.db.get_single_value("Streaming Settings", "cdn_host", cache=True) or "cdn.platform.com"

    # Sign the HTTP playback URLs so the nginx edge (secure_link) serves them
    # instead of returning 403. A single token authorises the whole session
    # (manifest + segments) until it expires; players re-apply it to segment
    # requests. The raw token/expires are returned so the player can do so.
    token, expires = sign()

    return {
        "hls": append_token(f"https://{cdn_host}/live/{stream_key}.m3u8", token, expires),
        "dash": append_token(f"https://{cdn_host}/live/{stream_key}.mpd", token, expires),
        "webrtc": f"webrtc://{node_ip}/live/{stream_key}",
        "red5": f"rtmp://{node_ip}:1936/live/{stream_key}",
        "token": token,
        "expires": expires,
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
    node_id = frappe.request.headers.get("X-Node-ID")
    if node_id:
        node_name = frappe.db.get_value("Streaming Node", {"node_id": node_id}, "name")
        if node_name:
            frappe.db.sql("""
                UPDATE `tabStreaming Node`
                SET current_load = COALESCE(current_load, 0) + 1
                WHERE name = %s
            """, node_name)

            # Update assigned node to reflect reality
            frappe.db.set_value("Live Stream", stream.name, "assigned_node", node_name)

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

        # Decrement Node Load
        node_id = frappe.request.headers.get("X-Node-ID")
        if node_id:
            try:
                node = frappe.get_doc("Streaming Node", {"node_id": node_id})
                node.current_load = max(0, (node.current_load or 0) - 1)
                node.save()
            except frappe.DoesNotExistError:
                pass

    return {"code": 0, "msg": "OK"}
