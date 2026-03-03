# v1.9 Release Notes

This document describes all new features and changes in the release. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Release Overview

- This release introduces DNS rule support, including new `DNSRule` and `DNSRuleRecord` models for template-driven DNS record creation and tracking.
- It adds a DNS rule engine and signal-driven processing to create, update, and remove records as source objects change, including rule scope handling across location and tenant.
- It adds DNS rule API, UI, filtering, tables, and navigation support so rules can be managed through both REST and web workflows.
- It adds user and model documentation for DNS rules and rule templates, plus expanded automated tests for rule engine behavior and model validation.

<!-- towncrier release notes start -->
