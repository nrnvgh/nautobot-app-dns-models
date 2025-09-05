# DNS Rule System - Software Requirements Document

## 1. Overview

### 1.1 Purpose
This document defines the requirements for implementing a Jinja-based DNS record automation system within the Nautobot DNS Models plugin. The system allows users to define rules that automatically create, update, and delete DNS records when certain Nautobot objects are modified.

### 1.2 Scope
The DNS Rule System provides automated DNS record management triggered by object lifecycle events in Nautobot, supporting all DNS record types (A, AAAA, CNAME, MX, NS, PTR, SRV, TXT) with user-defined Jinja2 templates.

### 1.3 Branch Information
- **Development Branch**: [`u/nrnvgh-107-jinja-based-dns-record-updates`](https://github.com/nrnvgh/nautobot-app-dns-models/tree/u/nrnvgh-107-jinja-based-dns-record-updates)
- **Target Nautobot Version**: 2.4+

## 2. Functional Requirements

### 2.1 Core Functionality

#### 2.1.1 DNS Rule Configuration
- **FR-001**: Users SHALL be able to create DNS rules with the following attributes:
  - Name (unique identifier)
  - Description (optional)
  - Enabled/disabled status
  - Target content type (dcim.Interface, ipam.IPAddress, etc.)
  - Rule priority (for execution order)
  - DNS zone template (Jinja2)
  - Record type (A, AAAA, CNAME, MX, NS, PTR, SRV, TXT)
  - Record name template (Jinja2)
  - Record value template (Jinja2)
  - Record-specific templates (preference, priority, weight, port for MX/SRV)

#### 2.1.2 Template Processing
- **FR-002**: Jinja2 templates SHALL have access to the triggering object as `obj`
- **FR-003**: Templates SHALL support Django ORM relationship traversal (e.g., `obj.device.name`)
- **FR-004**: Template rendering failures SHALL be logged without breaking the original object operation
- **FR-005**: Templates SHALL support UUID references for IP address fields

#### 2.1.3 Automatic Record Management
- **FR-006**: DNS records SHALL be automatically created when:
  - A new object matching a rule's content type is created
  - An existing object is modified and no corresponding DNS record exists
- **FR-007**: DNS records SHALL be automatically updated when:
  - The source object is modified and templates render successfully
- **FR-008**: DNS records SHALL be automatically deleted when:
  - The source object is deleted
  - Template rendering fails for existing records (indicating data is no longer available)

#### 2.1.4 Record Linking and Tracking
- **FR-009**: Auto-created DNS records SHALL be linked to their source objects via DNSRuleRecord
- **FR-010**: Manual DNS record deletion SHALL leave orphaned DNSRuleRecord entries for cleanup
- **FR-011**: Record recreation SHALL be attempted if DNS record is missing but DNSRuleRecord exists

### 2.2 Signal Handling

#### 2.2.1 Object Lifecycle Events
- **FR-012**: System SHALL respond to `post_save` signals for object creation and updates
- **FR-013**: System SHALL respond to `post_delete` signals for object deletion
- **FR-014**: System SHALL respond to `m2m_changed` signals for many-to-many relationship changes

#### 2.2.2 Recursion Prevention
- **FR-015**: System SHALL NOT process DNS models to prevent infinite recursion
- **FR-016**: Signal processing errors SHALL be logged without affecting the original operation

### 2.3 User Interface

#### 2.3.1 Rule Management
- **FR-017**: Users SHALL be able to create, read, update, and delete DNS rules via web UI
- **FR-018**: Rule forms SHALL dynamically show/hide fields based on selected record type
- **FR-019**: Rule lists SHALL be filterable by content type, record type, and enabled status

#### 2.3.2 Record Identification
- **FR-020**: DNS record lists SHALL indicate which records were auto-created by rules
- **FR-021**: Users SHALL be able to filter records by creation method (manual vs auto-created)

### 2.4 API Integration

#### 2.4.1 REST API
- **FR-022**: DNS rules SHALL be fully manageable via REST API
- **FR-023**: API responses SHALL include rule linkage information for DNS records

## 3. Technical Requirements

### 3.1 Data Models

#### 3.1.1 DNSRule Model
```python
- name: CharField(max_length=100, unique=True)
- description: CharField(max_length=CHARFIELD_MAX_LENGTH, blank=True)
- enabled: BooleanField(default=True)
- content_type: ForeignKey(ContentType)
- priority: IntegerField(default=100)
- zone_template: TextField()
- record_type: CharField(choices=RECORD_TYPE_CHOICES)
- name_template: TextField()
- value_template: TextField(blank=True)
- preference_template: TextField(blank=True)  # MX records
- priority_template: TextField(blank=True)    # SRV records
- weight_template: TextField(blank=True)      # SRV records
- port_template: TextField(blank=True)        # SRV records
```

#### 3.1.2 DNSRuleRecord Model
```python
- rule: ForeignKey(DNSRule)
- content_type: ForeignKey(ContentType)
- object_id: UUIDField(db_index=True)  # UUID support
- source_object: GenericForeignKey()
- dns_record_content_type: ForeignKey(ContentType)
- dns_record_object_id: UUIDField(db_index=True)  # UUID support
- dns_record: GenericForeignKey()
```

### 3.2 Processing Engine

#### 3.2.1 DNSRuleEngine Class
- **TR-001**: SHALL implement singleton pattern for global access
- **TR-002**: SHALL handle template rendering with error isolation
- **TR-003**: SHALL support all DNS record types with appropriate field mapping
- **TR-004**: SHALL log all operations with appropriate detail levels

### 3.3 Integration Points

#### 3.3.1 Nautobot Integration
- **TR-005**: SHALL use `nautobot.core.utils.data.render_jinja2` for template processing
- **TR-006**: SHALL follow Nautobot's form, view, and table patterns
- **TR-007**: SHALL integrate with Nautobot's navigation system

## 4. Implementation Status

### 4.1 Completed Components

#### 4.1.1 Core Models ✅
- [x] DNSRule model implementation
- [x] DNSRuleRecord linking table
- [x] Database migrations
- [x] Model relationships and constraints

#### 4.1.2 Processing Engine ✅
- [x] DNSRuleEngine class
- [x] Template rendering with error handling
- [x] Record creation, update, and deletion logic
- [x] UUID field type support (corrected to use UUIDField instead of CharField)

#### 4.1.3 Signal Handling ✅
- [x] post_save signal processing
- [x] post_delete signal processing
- [x] m2m_changed signal processing
- [x] Recursion prevention
- [x] Dynamic app label detection

#### 4.1.4 User Interface ✅
- [x] DNSRule forms (create, edit, filter, bulk edit)
- [x] DNSRule table views
- [x] Navigation integration
- [x] Form media for dynamic field behavior

#### 4.1.5 API Integration ✅
- [x] DNSRule serializers
- [x] DNSRule viewsets
- [x] API URL routing

#### 4.1.6 Documentation (Partial) 🔄
- [x] DNS Rule model documentation (dnsrule.md)
- [x] DNS Rule Record model documentation (dnsrulerecord.md)
- [x] MkDocs navigation integration
- [ ] User guide updates with DNS Rules usage examples
- [ ] Configuration option documentation
- [ ] API documentation updates

#### 4.1.7 Model Testing (Partial) 🔄
- [x] Basic DNSRule model tests
- [x] Per-record-type test coverage (A, AAAA, CNAME, TXT, PTR, NS, MX, SRV)
- [x] DNSRuleRecord model tests
- [x] Required field validation tests
- [ ] Jinja template rendering tests
- [ ] Signal integration tests
- [ ] Rule engine functionality tests
- [ ] Edge case and error handling tests

### 4.2 Pending Work Items

#### 4.2.1 High Priority
- [x] **JavaScript Implementation**: Complete dynamic form field visibility based on record type selection
- [ ] **Interface IP Handling**: Investigate special handling for A records from Interface objects with multiple IPs
- [ ] **Test Case Development**: Create comprehensive test cases for interface IP assignments
- [ ] **Template Exception Testing**: Verify _render_template catches correct exception types. We also need to ensure that exceptions are handled graceful and in keeping with Least Surprise. If a template fails to render (and therefore the DNS entry isn't created), should we allow the parent action to take place?
- [ ] **Multiple Template Error Display**: Add test to ensure that template syntax errors for multiple templates in a given rule are all shown in the UI simultaneously

#### 4.2.2 Medium Priority
- [ ] **Rule Scoping System**: Design tenant/location/tag-based rule filtering. Should also support global rules.
- [ ] **IP Address Lookup**: Solve A/AAAA record IP address field handling with VRF considerations
- [ ] **Manual Record Deletion Handling**: Clean up orphaned DNSRuleRecord entries
- [ ] **UI Record Indicators**: Add visual indicators for auto-created vs manual records
- [ ] **Rule Deletion Strategy**: Determine how to handle DNS records and DNSRuleRecords when a rule is deleted
- [ ] **Auto-Created Record Tagging**: Design how to mark auto-created DNS records (tags, status fields, etc.) and whether tag names should be configurable
- [ ] **IP Removal Handling**: Investigate better ways to handle IP removal than catching template exceptions - explore pre-validation approaches
- [ ] **Signal Optimization**: Optimize signal handling to only trigger for content types that have configured DNS rules
- [ ] **Signal Coverage for 1.0 Release**: Implement signal receivers for VirtualMachine, VMInterface (1.0 priority), with Service/VLAN/Cluster as maybe 1.0. Consider Location, Rack/RackGroup for post-1.0
- [ ] **Device Rename Cascade Handling**: Address how device renames affect interface record naming templates (vital for 1.0)
- [ ] **Prefix Signal Evaluation**: Determine if Prefix objects need signal handling based on common template usage patterns
- [ ] **Content Type Restrictions**: Determine if DNS rules should be limited to specific content types and define the allowed list. should that list be hardcoded or user-defined?
- [ ] **IP DNS Name Field Sync**: Determine if IPAddress 'dns_name' field should be updated when A records are auto-created, make configurable, and consider validation
- [ ] **A Record UUID UI Guidance**: Add UI helper text indicating A record values should be IP UUIDs, or implement IP lookup by address + VRF/tenant
- [ ] **Jinja QuerySet Testing**: Ensure tests include Jinja rules using all(), first(), and filter(key=value) QuerySet methods
- [ ] **DNS Zone Association**: Determine where to associate DNS zones (location?) and use that relationship for testing
- [ ] **Custom/Computed Fields Testing**: Ensure tests include Jinja rules using custom fields, computed fields, and config context data
- [ ] **IP Deletion Record Cleanup Testing**: Create test cases to ensure that when an IP is deleted from an interface, any corresponding DNS records created by rules are also deleted (critical for proper cleanup)
- [ ] **Interface A Record Removal Testing**: Test that A records are automatically deleted when IP addresses are removed from interfaces via M2M signal handling
- [ ] **Device Primary IP Change Testing**: Test that Device DNS records are properly updated/deleted when primary IP fields are cleared due to interface IP removal
- [ ] **AAAA Record Removal Testing**: Test that AAAA (IPv6) records are automatically deleted when IPv6 addresses are removed from interfaces
- [ ] **Multiple IP Interface Testing**: Test interface IP removal scenarios where interface has multiple IPs (remove one, others remain)
- [ ] **DNSRuleRecord Cleanup Testing**: Test that DNSRuleRecord tracking entries are properly cleaned up when DNS records are deleted due to template failures
- [ ] **External Data Validation**: Ensure validation of template-rendered data with limited control (MX priority, SRV weights, port numbers, etc.)
- [ ] **DNS Rule Validation Conflicts**: Understand behavior when DNS rules generate records that violate existing DNS record model validation
- [ ] **Record-Type-Specific Field Validation**: Implement validation to make record-type-specific template fields required (MX preference_template, SRV priority/weight/port templates) per DNS RFC compliance

#### 4.2.3 Explicitly Deferred for Initial Release
- [ ] **Tenant Signal Handling**: Excluded due to massive cascade potential (could affect thousands of records)
- [ ] **VRF Signal Handling**: Excluded due to large-scale impact on IP addressing and related records
- [ ] **IPAddress Signal Handling**: Skipped for 1.0 as most IP-related changes are covered by Device/Interface/VM signals; may warrant revisiting if direct IPAddress rule targeting or IP-specific metadata usage emerges

#### 4.2.4 Future Enhancements
- [ ] **Priority Configuration Methods**: Evaluate template vs increment-based priority configuration
- [ ] **Model File Organization**: Consider splitting models.py into records.py and rules.py
- [ ] **DNS Lowercase Config**: Add configuration option to force DNS records to lowercase
- [ ] **Character Transform Config**: Add DNS character validation and transformation options
- [ ] **Template Field Naming**: Revisit field naming conventions (value_template vs content_template)
- [ ] **Custom Relationship DNS Rules**: Investigate scenarios where IPs have custom relationships (e.g., IP-to-Circuit) - determine if Circuit-based rules can leverage these relationships or if IP-based rules are needed for such cases

## 5. Non-Functional Requirements

### 5.1 Performance
- **NFR-001**: Template rendering SHALL complete within 100ms for typical use cases
- **NFR-002**: Signal processing SHALL NOT significantly impact object save performance
- **NFR-003**: Rule evaluation SHALL be optimized to avoid N+1 query problems

### 5.2 Reliability
- **NFR-004**: Template rendering failures SHALL NOT prevent object saves
- **NFR-005**: System SHALL gracefully handle missing related objects
- **NFR-006**: Database operations SHALL be atomic where possible

### 5.3 Maintainability
- **NFR-007**: Code SHALL follow Nautobot plugin development patterns
- **NFR-008**: All functions SHALL have appropriate logging
- **NFR-009**: Code SHALL pass ruff linting and formatting checks

### 5.4 Security
- **NFR-011**: Template rendering SHALL use Nautobot's secure Jinja2 implementation
- **NFR-012**: User permissions SHALL control DNS rule management
- **NFR-013**: Template content SHALL be validated for safety

## 6. Testing Strategy

### 6.1 Unit Tests
- Template rendering with various object types
- DNS record creation/update/deletion logic
- Signal handler behavior
- Error condition handling

### 6.2 Integration Tests
- End-to-end rule processing workflows
- Multiple rule interaction scenarios
- UI form validation and submission
- API endpoint functionality

### 6.3 Performance Tests
- Rule processing under load
- Template rendering performance
- Database query optimization validation

## 7. Future Considerations

### 7.1 Configuration Options
- Global vs rule-level DNS record formatting options for things like enforcing lower-case
- Character transformation rules for DNS compliance for things like `/` -> `-`
- Priority assignment methods (template vs increment)

### 7.2 Advanced Features
- Rule condition logic (beyond content type matching); location, vrf, tags, etc.
- Bulk rule operations
- Rule import/export functionality
- Template validation and testing tools

### 7.3 Monitoring and Observability
- Rule execution metrics
- Template rendering performance monitoring
- DNS record lifecycle tracking

## 8. Dependencies

### 8.1 External Dependencies
- Nautobot 2.4+
- Django contenttypes framework
- Jinja2 templating engine

### 8.2 Internal Dependencies
- Existing DNS record models
- Nautobot signal system
- Nautobot utilities (render_jinja2, forms, etc.)

---

**Document Version**: 1.0  
**Last Updated**: Current implementation status  
**Next Review**: After JavaScript implementation completion
