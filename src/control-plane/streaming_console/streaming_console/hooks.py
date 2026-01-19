from . import __version__ as app_version

app_name = "streaming_console"
app_title = "Streaming Console"
app_publisher = "Platform Engineering"
app_description = "Control Plane for Live Streaming Platform"
app_email = "admin@platform.com"
app_license = "MIT"

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/streaming_console/css/streaming_console.css"
# app_include_js = "/assets/streaming_console/js/streaming_console.js"

# Website Hooks
website_route_rules = [
    {"from_route": "/studio", "to_route": "studio/index"},
    {"from_route": "/studio/stream/<name>", "to_route": "studio/stream"},
]

# Role Management
has_website_permission = {
    "Live Stream": "streaming_console.permissions.has_website_permission"
}
