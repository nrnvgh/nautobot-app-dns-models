# Installing the App in Nautobot

Here you will find detailed instructions on how to **install** and **configure** the App within your Nautobot environment.

## Prerequisites

- The app is compatible with Nautobot 2.4.20 and higher.
- Databases supported: PostgreSQL, MySQL

!!! note
    Please check the [dedicated page](compatibility_matrix.md) for a full compatibility matrix and the deprecation policy.

### Access Requirements

No access to other systems is required to use this app.

## Install Guide

!!! note
    Apps can be installed from the [Python Package Index](https://pypi.org/) or locally. See the [Nautobot documentation](https://docs.nautobot.com/projects/core/en/stable/user-guide/administration/installation/app-install/) for more details. The pip package name for this app is [`nautobot-dns-models`](https://pypi.org/project/nautobot-dns-models/).

The app is available as a Python package via PyPI and can be installed with `pip`:

```shell
pip install nautobot-dns-models
```

To ensure Nautobot DNS Models is automatically re-installed during future upgrades, create a file named `local_requirements.txt` (if not already existing) in the Nautobot root directory (alongside `requirements.txt`) and list the `nautobot-dns-models` package:

```shell
echo nautobot-dns-models >> local_requirements.txt
```

Once installed, the app needs to be enabled in your Nautobot configuration. The following block of code below shows the additional configuration required to be added to your `nautobot_config.py` file:

- Append `"nautobot_dns_models"` to the `PLUGINS` list.
- Append the `"nautobot_dns_models"` dictionary to the `PLUGINS_CONFIG` dictionary and override any defaults.

```python
# In your nautobot_config.py
PLUGINS = ["nautobot_dns_models"]

# PLUGINS_CONFIG = {
#   "nautobot_dns_models": {
#     ADD YOUR SETTINGS HERE
#   }
# }
```

Once the Nautobot configuration is updated, run the Post Upgrade command (`nautobot-server post_upgrade`) to run migrations and clear any cache:

```shell
nautobot-server post_upgrade
```

Then restart (if necessary) the Nautobot services which may include:

- Nautobot
- Nautobot Workers
- Nautobot Scheduler

```shell
sudo systemctl restart nautobot nautobot-worker nautobot-scheduler
```

## App Configuration

This option is configured via the Admin GUI.

`DNS_VALIDATION_LEVEL` (default: "Wire format")

This setting controls the DNS validation level applied to zones and records:

- **Disabled** - No DNS validation is performed
- **Wire format** - Enforces DNS label and name length rules as specified in [RFC 1035 §3.1](https://datatracker.ietf.org/doc/html/rfc1035#section-3.1):
    - Each label (the parts of the name separated by dots) must be no more than 63 bytes in wire format
    - Empty labels (e.g., consecutive dots or leading/trailing dots) are not allowed
    - The total length of the fully qualified DNS name (including all dots, in wire format) must not exceed 255 bytes

## Logging

`nautobot_dns_models` emits hybrid logs: human-readable messages plus structured fields in the Python logging `extra` payload.

To include structured fields in output, customize logging in `nautobot_config.py` by adding a formatter/handler for the `nautobot_dns_models` logger. For example, to render `phase`:

```python
LOGGING = {
    # ...
    "formatters": {
        "dns_models": {
            "()": "logging.Formatter",
            "format": "%(asctime)s %(levelname)s %(name)s phase=%(phase)s : %(message)s",
            "defaults": {"phase": "-"},
        },
    },
    "handlers": {
        "dns_models_console": {
            "class": "logging.StreamHandler",
            "formatter": "dns_models",
        },
    },
    "loggers": {
        "nautobot_dns_models": {
            "handlers": ["dns_models_console"],
            "level": "INFO",
        },
    },
}
```

If a formatter references fields such as `%(phase)s`, use formatter defaults (or a plugin-specific handler) so non-plugin logs do not fail formatting.

Structured fields currently emitted include:

- `event` - Static event namespace for plugin engine logs.
- `reason_code` - Stable machine-readable reason for warning/error conditions.
- `phase` - Processing phase, such as `create` or `update_reconcile`.
- `rule_id` - UUID of the `DNSRule` being evaluated.
- `rule_name` - Human-readable name of the `DNSRule`.
- `record_type` - DNS record type targeted by the rule, such as `A` or `AAAA`.
- `source_ct` - Source object content type label, for example `dcim.interface`.
- `source_id` - UUID of the source object being processed.
- `source_repr` - String representation of the source object.
- `exception_type` - Exception class name when an exception is logged.
- `error` - Exception message when an exception is logged.
- `cleanup` - Boolean indicating whether cleanup/removal was attempted.
- `candidate_address_id` - Candidate IP address UUID for per-candidate logs.
- `candidate_name` - Rendered DNS record name for a candidate.
- `candidate_zone_id` - DNS zone UUID selected for the candidate.
- `existing_count` - Number of existing tracked records for reconciliation.
- `desired_count` - Number of desired records computed during reconciliation.
- `keep_count` - Number of records preserved because they already match desired state.
- `create_count` - Number of records created in the reconciliation pass.
- `delete_count` - Number of records deleted in the reconciliation pass.
- `skipped_count` - Number of desired candidates skipped due to failures.

If your logging pipeline expects structured output, you can configure the plugin logger with a JSON formatter instead of a text formatter. For example:

```python
LOGGING = {
    # ...
    "formatters": {
        "dns_models_json": {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": (
                "%(asctime)s %(levelname)s %(name)s %(message)s %(event)s %(reason_code)s "
                "%(phase)s %(rule_id)s %(rule_name)s %(record_type)s %(source_ct)s %(source_id)s"
            ),
        },
    },
    "handlers": {
        "dns_models_json_console": {
            "class": "logging.StreamHandler",
            "formatter": "dns_models_json",
        },
    },
    "loggers": {
        "nautobot_dns_models": {
            "handlers": ["dns_models_json_console"],
            "level": "INFO",
        },
    },
}
```

This example uses `python-json-logger`. If you use a different JSON logging library, replace the formatter class accordingly.

## DNS Reconciliation Jobs

The app provides two Nautobot Jobs for operator-driven reconciliation (for example drift repair or backfilling after new rules):

- `Reconcile DNS Records (Object)` for single-object execution.
- `Reconcile DNS Records (Bulk)` for global or filtered subset execution.

User-facing documentation (parameters, Job result shape, class paths, and log line format) is in [DNS Reconciliation Jobs](../user/rules/reconciliation_jobs.md).

- Enable each Job you intend to use on its Job detail page before first use (standard Nautobot job enable workflow).
- Grant operators the `extras.run_job` permission so they can execute Jobs.
- **Bulk:** launch from **Jobs > Jobs** or via API by class path. Scope the run with `source_models`, `rules`, `locations`, `tenants`, `limit`, `batch_size`, and related options; use `dryrun` to list targets without applying changes.
- **Object:** the detail-view **Reconcile DNS** action (when rules are in scope) opens this Job with the object pre-filled; you can also invoke it via API. It is registered as hidden, so it may not appear in the default **Jobs > Jobs** list; use the button, API, or your Nautobot UI’s controls for hidden jobs if you need to open the form manually. Use `dryrun` the same way as for bulk.
