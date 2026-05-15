import requests
from datetime import datetime

# ============================================================
# SESSION CONFIGURATION
# ============================================================

session = requests.Session()

# ============================================================
# MULTIPLE ENTERPRISE CONFIGURATION
# ============================================================

ENTERPRISES = [
    {
        "name": "Enterprise Name",
        "base": "https://enteprisedomainurl.com",
        "username": "portaladmin",
        "password": "ent_password"
    }
]

VERIFY_SSL = True

CRITICAL_DAYS = 15
WARNING_DAYS = 30

DISK_CRITICAL_GB = 25
DISK_WARNING_GB = 40

REPORT_FILE = f"enterprise_health_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"

# ============================================================
# TOKEN GENERATION
# ============================================================

def generate_token(portal_url, base_url, username, password):

    payload = {
        "username": username,
        "password": password,
        "client": "referer",
        "referer": base_url,
        "f": "json"
    }

    response = session.post(
        f"{portal_url}/sharing/rest/generateToken",
        data=payload,
        verify=VERIFY_SSL,
        timeout=20
    )

    data = response.json()

    if "token" not in data:
        raise Exception(f"Token generation failed: {data}")

    return data["token"]

def get_json(url, token):

    response = session.get(
        url,
        params={
            "f": "json",
            "token": token
        },
        verify=VERIFY_SSL,
        timeout=20
    )

    if response.status_code != 200:
        raise Exception(f"HTTP {response.status_code} from {url}")

    return response.json()

def cert_expiry(valid_until_str):

    try:

        expiry = valid_until_str.split(" ")
        expiry.pop(-2)

        expiry_clean = " ".join(expiry)

        expiry_date = datetime.strptime(
            expiry_clean,
            "%a %b %d %H:%M:%S %Y"
        )

        days_left = (expiry_date - datetime.now()).days

        if days_left < 0:
            return "Expired", "CRITICAL", days_left

        elif days_left < CRITICAL_DAYS:
            return "Expiring Soon", "CRITICAL", days_left

        elif days_left < WARNING_DAYS:
            return "Expiring Within 30 Days", "WARNING", days_left

        return "Valid", "INFO", days_left

    except:
        return "Unable to Parse Date", "WARNING", 0

def process_portal_license(url, token):

    try:

        license_json = get_json(url, token)

        expiration_epoch = None

        user_types = license_json.get("userTypes", [])

        if user_types:
            expiration_epoch = user_types[0].get("expiration")

        if not expiration_epoch:

            apps = license_json.get("apps", [])

            if apps:
                expiration_epoch = apps[0].get("expiration")

        if expiration_epoch:

            expiry_date = datetime.fromtimestamp(
                expiration_epoch / 1000
            )

            readable_date = expiry_date.strftime("%d-%b-%Y")

            return f"Expiration: {readable_date}", "INFO"

        return "Unable to fetch license info", "WARNING"

    except:
        return "Unable to fetch license info", "WARNING"

def process_server_license(url, token):

    try:

        license_json = get_json(url, token)

        expiration_epoch = license_json.get("expiration")

        if expiration_epoch:

            expiry_date = datetime.fromtimestamp(
                expiration_epoch / 1000
            )

            readable_date = expiry_date.strftime("%d-%b-%Y")

            return f"Expiration: {readable_date}", "INFO"

        return "License validation successful", "INFO"

    except:
        return "Unable to fetch server license", "WARNING"

def run_checks(token, PORTAL, SERVER, enterprise_name):

    results = []

    portal_machines = get_json(
        f"{PORTAL}/portaladmin/machines",
        token
    )

    server_machines = get_json(
        f"{SERVER}/admin/machines",
        token
    )

    for machine in portal_machines.get("machines", []):

        name = machine["machineName"]

        try:

            status = get_json(
                f"{PORTAL}/portaladmin/machines/{name}/status",
                token
            )

            level = (
                "INFO"
                if status.get("status") == "success"
                else "CRITICAL"
            )

            results.append((
                "Portal Machine",
                name,
                status.get("status"),
                level
            ))

        except Exception as e:

            results.append((
                "Portal Machine",
                name,
                str(e),
                "CRITICAL"
            ))

        try:

            certs = get_json(
                f"{PORTAL}/portaladmin/machines/{name}/sslCertificates",
                token
            )

            cert_list = certs.get("sslCertificates", [])

            if cert_list:

                cert = cert_list[0]

                cert_info = get_json(
                    f"{PORTAL}/portaladmin/machines/{name}/sslCertificates/{cert}",
                    token
                )

                valid_until = cert_info.get("validUntil")

                if valid_until:

                    status_text, level, days = cert_expiry(valid_until)

                    results.append((
                        "Portal Certificate",
                        f"{name} - {cert}",
                        f"{status_text} ({days} Days)",
                        level
                    ))

        except:

            results.append((
                "Portal Certificate",
                name,
                "Certificate validation failed",
                "WARNING"
            ))

        try:

            hardware = get_json(
                f"{PORTAL}/portaladmin/machines/{name}/hardware",
                token
            )

            for disk in hardware.get("localDiskUsage", []):

                path = disk.get("path", "")
                usable = disk.get("diskUsableSpaceGB", 0)

                if usable < DISK_CRITICAL_GB:
                    level = "CRITICAL"

                elif usable < DISK_WARNING_GB:
                    level = "WARNING"

                else:
                    level = "INFO"

                results.append((
                    "Portal Disk",
                    f"{name} - {path}",
                    f"{usable} GB Free",
                    level
                ))

        except:

            results.append((
                "Portal Disk",
                name,
                "Hardware endpoint inaccessible",
                "WARNING"
            ))


    for machine in server_machines.get("machines", []):

        name = machine["machineName"]

        try:

            status = get_json(
                f"{SERVER}/admin/machines/{name}/status",
                token
            )

            state = status.get("configuredState")

            level = (
                "INFO"
                if state == "STARTED"
                else "CRITICAL"
            )

            results.append((
                "GIS Server Machine",
                name,
                state,
                level
            ))

        except Exception as e:

            results.append((
                "GIS Server Machine",
                name,
                str(e),
                "CRITICAL"
            ))

    try:

        federation = get_json(
            f"{PORTAL}/portaladmin/federation/servers/validate",
            token
        )

        level = (
            "INFO"
            if federation.get("status") == "success"
            else "CRITICAL"
        )

        results.append((
            "Federation",
            enterprise_name,
            federation.get("status"),
            level
        ))

    except:

        results.append((
            "Federation",
            enterprise_name,
            "Federation validation failed",
            "CRITICAL"
        ))


    portal_license_url = f"{PORTAL}/portaladmin/license"

    status_text, level = process_portal_license(
        portal_license_url,
        token
    )

    results.append((
        "Portal License",
        "Portal License",
        status_text,
        level
    ))

    server_license_url = f"{SERVER}/admin/system/licenses"

    status_text, level = process_server_license(
        server_license_url,
        token
    )

    results.append((
        "Server License",
        "Server License",
        status_text,
        level
    ))


    try:

        datastore = get_json(
            f"{SERVER}/admin/data/items",
            token
        )

        if "rootItems" in datastore:

            results.append((
                "Data Store",
                "All Data Stores",
                "Validation Successful",
                "INFO"
            ))

        else:

            results.append((
                "Data Store",
                "All Data Stores",
                "Validation Failed",
                "CRITICAL"
            ))

    except:

        results.append((
            "Data Store",
            "All Data Stores",
            "Validation Failed",
            "CRITICAL"
        ))

    return results

def generate_html(results, enterprise):

    client_name = enterprise.get("name", "ArcGIS Enterprise")

    severity_icon = {
        "CRITICAL": "❌ Critical",
        "WARNING": "⚠️ Warning",
        "INFO": "ℹ️ Info"
    }

    status_color = {
        "CRITICAL": "#ffebee",
        "WARNING": "#fff8e1",
        "INFO": "#e8f5e9"
    }


    portal_status = "Healthy"
    server_status = "Healthy"
    datastore_status = "Healthy"

    portal_icon = "✅"
    server_icon = "✅"
    datastore_icon = "✅"

    for comp, name, status, level in results:

        if "Portal" in comp and level == "CRITICAL":
            portal_status = "Critical"
            portal_icon = "❌"

        elif "Portal" in comp and level == "WARNING":
            portal_status = "Warning"
            portal_icon = "⚠️"

        if "Server" in comp and level == "CRITICAL":
            server_status = "Critical"
            server_icon = "❌"

        elif "Server" in comp and level == "WARNING":
            server_status = "Warning"
            server_icon = "⚠️"

        if "Data Store" in comp and level == "CRITICAL":
            datastore_status = "Critical"
            datastore_icon = "❌"

    html = f"""
    <html>

    <head>

    <title>{client_name} - Enterprise Health Report</title>

    <style>

    body {{
        font-family: Arial;
        margin: 20px;
        background: #f4f6f9;
    }}

    table {{
        border-collapse: collapse;
        width: 100%;
        background: white;
    }}

    th {{
        background: #2f4f4f;
        color: white;
        padding: 10px;
        border: 1px solid #ddd;
    }}

    td {{
        padding: 10px;
        border: 1px solid #ddd;
    }}

    .header {{
        display: flex;
        align-items: center;
        gap: 20px;
        margin-bottom: 20px;
    }}

    .logo {{
        width: 80px;
    }}

    </style>

    </head>

    <body>

    <div class="header">

        <img class="logo"
        src="PulseGIS.png">

        <div>
            <h1>{client_name}</h1>
            <h3>Enterprise Components Health Check Summary</h3>
        </div>

    </div>

    <table>

        <tr>
            <th>Portal Check</th>
            <th>Server Check</th>
            <th>Datastore Check</th>
        </tr>

        <tr>
            <td>{portal_icon} ArcGIS Portal Status {portal_status}</td>
            <td>{server_icon} ArcGIS Server Status {server_status}</td>
            <td>{datastore_icon} ArcGIS Datastore Status {datastore_status}</td>
        </tr>

    </table>

    <br><br>

    <h2>Detailed Operational Health Check</h2>

    <table>

        <tr>
            <th>Component</th>
            <th>Name</th>
            <th>Severity</th>
            <th>Status</th>
        </tr>
    """

    for comp, name, status, level in results:

        severity = severity_icon.get(level, "ℹ️ Info")
        bg = status_color.get(level, "#ffffff")

        html += f"""

        <tr style="background:{bg}">
            <td>{comp}</td>
            <td>{name}</td>
            <td>{severity}</td>
            <td>{status}</td>
        </tr>
        """

    html += f"""

    </table>

    <br>

    <b>Generated:</b>
    {datetime.now().strftime("%d-%b-%Y %H:%M:%S")}

    </body>
    </html>
    """

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Report generated: {REPORT_FILE}")

# ============================================================
# MAIN EXECUTION
# ============================================================

if __name__ == "__main__":

    all_results = []

    for ent in ENTERPRISES:

        base = ent["base"]

        portal = f"{base}/portal"
        server = f"{base}/server"

        try:

            print(f"Running checks for: {ent['name']}")

            token = generate_token(
                portal,
                base,
                ent["username"],
                ent["password"]
            )

            results = run_checks(
                token,
                portal,
                server,
                ent["name"]
            )

            all_results.extend(results)

        except Exception as e:

            all_results.append((
                ent["name"],
                "Enterprise Connection",
                str(e),
                "CRITICAL"
            ))

    generate_html(all_results, ENTERPRISES[0])

    print("Health check completed successfully.")