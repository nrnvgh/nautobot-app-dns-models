# DNSRule Model

*Placeholder documentation for GUI-based DNS Rule model.*

## Overview

The `DNSRule` model represents a GUI-based DNS rule for generating DNS records from network objects using a visual component-based interface.

## Fields

- **name**: Unique identifier for the rule
- **description**: Optional description 
- **enabled**: Whether the rule is active
- **content_type**: Type of object this rule applies to (Device, Interface, etc.)
- **record_type**: Type of DNS record to generate (ARecordModel, CNAMERecordModel, etc.)

## Zone Selection

- **zone_source**: How to determine the target DNS zone
  - `fixed`: Use a fixed zone
  - `field_reference`: Use a model field path  
  - `custom_field`: Use a custom field value

## Usage

GUI-based DNS rules use components instead of Jinja templates to build DNS record names and values.

*This is a placeholder - full documentation to be added.*
