"""Menu items to the Nautobot navigation menu."""

from nautobot.apps.ui import NavMenuAddButton, NavMenuGroup, NavMenuItem, NavMenuTab

items = [
    NavMenuItem(
        link="plugins:nautobot_dns_models:dnszone_list",
        name="DNS Zones",
        permissions=["nautobot_dns_models.view_dnszone"],
        buttons=(
            NavMenuAddButton(
                link="plugins:nautobot_dns_models:dnszone_add",
                permissions=["nautobot_dns_models.add_dnszone"],
            ),
        ),
    ),
    NavMenuItem(
        link="plugins:nautobot_dns_models:dnsview_list",
        name="DNS Views",
        permissions=["nautobot_dns_models.view_dnsview"],
        buttons=(
            NavMenuAddButton(
                link="plugins:nautobot_dns_models:dnsview_add",
                permissions=["nautobot_dns_models.add_dnsview"],
            ),
        ),
    ),
    NavMenuItem(
        link="plugins:nautobot_dns_models:dnsrule_list",
        name="DNS Rules",
        permissions=["nautobot_dns_models.view_dnsrule"],
        buttons=(
            NavMenuAddButton(
                link="plugins:nautobot_dns_models:dnsrule_add",
                permissions=["nautobot_dns_models.add_dnsrule"],
            ),
        ),
    ),
    NavMenuItem(
        link="plugins:nautobot_dns_models:dnsrulefailurestate_list",
        name="DNS Reconciliation Issues",
        permissions=["nautobot_dns_models.view_dnsrulefailurestate"],
    ),
]

menu_items = (
    NavMenuTab(
        name="DNS",
        groups=(NavMenuGroup(name="DNS", items=tuple(items)),),
        weight=300,
    ),
)
