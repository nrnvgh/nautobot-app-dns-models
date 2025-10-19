# DNS Rule System - Software Requirements Document

## 1. Overview

### 1.1 Purpose
This document defines the requirements for implementing a Jinja-based DNS record automation system within the Nautobot DNS Models plugin. The system allows users to define rules that automatically create, update, and delete DNS records when certain Nautobot objects are modified.

### 1.2 Scope
The DNS Rule System provides automated DNS record management triggered by object lifecycle events in Nautobot, supporting all DNS record types (A, AAAA, CNAME, MX, NS, PTR, SRV, TXT) with user-defined Jinja2 templates.

### 1.3 Version Information
- **Development Branch**: [`u/nrnvgh-107-jinja-based-dns-record-updates`](https://github.com/nrnvgh/nautobot-app-dns-models/tree/u/nrnvgh-107-jinja-based-dns-record-updates)
- **Target Nautobot Version**: 2.4+
- **Current Status**: v0.9 (Proof of Concept - single record per rule)
- **Production Target**: v1.0 (Multiple records per rule for real-world usage)

## 2. Functional Requirements

### 2.1 Core Functionality

#### 2.1.1 DNS Rule Configuration
- [ ] **FR-001**: Users SHALL be able to create DNS rules with the following attributes:
  - Name (unique identifier)
  - Description (optional)
  - Enabled/disabled status
  - Target content type (dcim.Interface, ipam.IPAddress, etc.)
  - Location (optional, for location-scoped rules) ✅
  - DNS zone template (Jinja2)
  - Record type (A, AAAA, CNAME, MX, NS, PTR, SRV, TXT)
  - Record name template (Jinja2)
  - Record value template (Jinja2)
  - Record-specific templates (preference, priority, weight, port for MX/SRV)

#### 2.1.2 Template Processing
- [x] **FR-002**: Jinja2 templates SHALL have access to the triggering object as `obj`
- [x] **FR-003**: Templates SHALL support Django ORM relationship traversal (e.g., `obj.device.name`)
- [ ] **FR-004**: Template rendering failures SHALL be logged without breaking the original object operation
- [ ] **FR-005**: Templates SHALL support UUID references for IP address fields

#### 2.1.3 Automatic Record Management
- [ ] **FR-006**: DNS records SHALL be automatically created when:
  - A new object matching a rule's content type is created
  - An existing object is modified and no corresponding DNS record exists
- [ ] **FR-007**: DNS records SHALL be automatically updated when:
  - The source object is modified and templates render successfully
- [ ] **FR-008**: DNS records SHALL be automatically deleted when:
  - The source object is deleted
  - Template rendering fails for existing records (indicating data is no longer available)

#### 2.1.4 Record Linking and Tracking
- [x] **FR-009**: Auto-created DNS records SHALL be linked to their source objects via DNSRuleRecord
- [ ] **FR-010**: Manual DNS record deletion SHALL NOT leave orphaned DNSRuleRecord entries for cleanup
- [ ] **FR-011**: Record recreation MAY be attempted if DNS record is missing but DNSRuleRecord exists (job?)

#### 2.1.5 Rule Uniqueness and Conflict Management
- [x] **FR-012**: Multiple DNS rules MAY target the same content type with different record types (e.g., Interface A + Interface CNAME rules)
- [x] **FR-013**: Only one DNS rule SHALL be permitted per `(content_type, record_type)` combination in v1.0
- [x] **FR-014**: Duplicate record type rules SHALL be prevented at rule creation time (e.g., cannot create two Interface A record rules)
- [x] **FR-015**: Rule creation validation SHALL be designed for future extensibility to support tenant/location-based scoping
- [x] **FR-016**: Future versions MAY allow multiple rules of the same type when scoped to different tenants/locations

### 2.2 Signal Handling

#### 2.2.1 Object Lifecycle Events
- [ ] **FR-017**: System SHALL respond to `post_save` signals for object creation and updates
- [ ] **FR-018**: System SHALL respond to `post_delete` signals for object deletion
- [ ] **FR-019**: System SHALL respond to `m2m_changed` signals for many-to-many relationship changes

#### 2.2.2 Recursion Prevention
- [ ] ~~**FR-020**: System SHALL NOT process DNS models to prevent infinite recursion~~
- [ ] **FR-021**: Signal processing errors SHALL be logged without affecting the original operation

### 2.3 User Interface

#### 2.3.1 Rule Management
- [x] **FR-022**: Users SHALL be able to create, read, update, and delete DNS rules via web UI
- [x] **FR-023**: Rule forms SHALL dynamically show/hide fields based on selected record type
- [x] **FR-024**: Rule lists SHALL be filterable by content type, record type, location, and enabled status

#### 2.3.2 Record Identification
- [ ] **FR-025**: DNS record lists SHALL indicate which records were auto-created by rules
- [ ] **FR-026**: Users SHALL be able to filter records by creation method (manual vs auto-created)

### 2.4 API Integration

#### 2.4.1 REST API
- [x] **FR-027**: DNS rules SHALL be fully manageable via REST API 
- [x] **FR-028**: API responses SHALL include rule linkage information for DNS records 

## 3. Technical Requirements

### 3.1 Data Models

#### 3.1.1 DNSRule Model
```python
- name: CharField(max_length=100, unique=True)
- description: CharField(max_length=CHARFIELD_MAX_LENGTH, blank=True)
- enabled: BooleanField(default=True)
- content_type: ForeignKey(ContentType)
- location: ForeignKey("dcim.Location", null=True, blank=True)  # ✅ Implemented
- tenant: ForeignKey("tenancy.Tenant", null=True, blank=True)   # ✅ Implemented
- zone_template: TextField()
- record_type: CharField(choices=RECORD_TYPE_CHOICES)
- name_template: TextField()
- value_template: TextField()
- preference_template: TextField(blank=True)  # MX records
- priority_template: TextField(blank=True)    # SRV records
- weight_template: TextField(blank=True)      # SRV records
- port_template: TextField(blank=True)        # SRV records
```

#### 3.1.2 DNSRuleRecord Model
```python
- rule: ForeignKey(DNSRule, related_name="rule_records")  # ✅ Clean reverse relationship
- content_type: ForeignKey(ContentType)
- object_id: UUIDField(db_index=True)  # UUID support
- source_object: GenericForeignKey()
- dns_record_content_type: ForeignKey(ContentType)
- dns_record_object_id: UUIDField(db_index=True)  # UUID support
- dns_record: GenericForeignKey()
```

### 3.2 Processing Engine

#### 3.2.1 DNSRuleEngine Class
- [ ] **TR-001**: SHALL implement singleton pattern for global access
- [ ] **TR-002**: SHALL handle template rendering with error isolation
- [ ] **TR-003**: SHALL support all DNS record types with appropriate field mapping
- [ ] **TR-004**: SHALL log all operations with appropriate detail levels

### 3.3 Integration Points

#### 3.3.1 Nautobot Integration
- [x] **TR-005**: SHALL use Nautobot's `render_jinja2` function for template processing
- [x] **TR-006**: SHALL follow Nautobot's form, view, and table patterns
- [ ] **TR-007**: SHALL integrate with Nautobot's navigation system

## 4. Implementation Status

### 4.1 Completed Components

#### 4.1.1 Core Models ✅
- [x] DNSRule model implementation
- [x] DNSRuleRecord linking table
- [x] Database migrations
- [x] Model relationships and constraints
- [x] Location-scoped DNS rules with per-record-type precedence ✅
- [x] Priority field removal (simplified model design) ✅

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
- [x] Location field in forms and tables (Location: ✅)
- [x] Location-based filtering support (Location: ✅, Tenant: ⏳)

#### 4.1.5 API Integration ✅
- [x] DNSRule serializers
- [x] DNSRule viewsets
- [x] API URL routing
- [x] Location-based API filtering support (Location: ✅, Tenant: ⏳)

#### 4.1.6 Documentation (Partial) 🔄
- [x] DNS Rule model documentation (dnsrule.md)
- [x] DNS Rule Record model documentation (dnsrulerecord.md)
- [x] MkDocs navigation integration
- [ ] User guide updates with DNS Rules usage examples
- [ ] Configuration option documentation
- [ ] API documentation updates

#### 4.1.7 Model Testing ✅
- [x] Basic DNSRule model tests
- [x] Per-record-type test coverage (A, AAAA, CNAME, TXT, PTR, NS, MX, SRV)
- [x] DNSRuleRecord model tests
- [x] Required field validation tests
- [x] Jinja template rendering tests (comprehensive TemplateRenderingTestCase with real objects)
- [x] Signal integration tests (comprehensive IntegrationAndMultiRecordTestCase)
- [x] Rule engine functionality tests (comprehensive RuleResolutionTestCase)
- [x] Edge case and error handling tests (comprehensive RuleValidationTestCase)
- [x] Test suite reorganization (52 tests organized into 4 logical classes with BaseRuleEngineTestCase)

### 4.2 Pending Work Items

#### 4.2.1 High Priority (v0.9 - Proof of Concept Completion)
- [x] **JavaScript Implementation**: Complete dynamic form field visibility based on record type selection
  - **Completed**: Fixed StaticSelect2 widget event handling with select2:change and select2:select events
- [x] **Interface IP Handling**: Basic single record from interface IPs (POC complete)
- [x] **Test Case Development**: Create comprehensive test cases for interface IP assignments (single record)
- [x] **Rule Uniqueness Validation**: Implement `(content_type, record_type)` uniqueness constraint
  - **Completed**: UniqueConstraint on (content_type, record_type, location, tenant) with enabled=True condition
  - **Implementation**: Database-level constraint + validate_unique() method for user-friendly errors
  - **Scope**: Exceeds original requirement by supporting location/tenant scoping
- [x] **DNSRuleRecordSerializer**: Add missing API serializer for DNSRuleRecord model
- [x] **Template Exception Testing**: Verify _render_template catches correct exception types and graceful handling
- [x] **Performance Testing Framework**: Create comprehensive performance test suite for DNS rule system
  - **Completed**: Built test_performance.py with baseline, SQL analysis, and statistical measurement across 128 IP assignments
  - **Metrics**: Quantified DNS overhead at 6.31ms per IP assignment with 6 additional SQL queries
  - **Value**: Provides baseline for optimization work and data-driven performance improvement

#### 4.2.2 Critical Priority (v1.0 - Production Architecture) 
- [x] **Multiple Records Per Rule Engine**: MAJOR REWORK - Enable one rule to create multiple DNS records
  - **Completed**: Space-delimited UUID filter approach for A/AAAA records
  - **Template Enhancement**: `{{ obj.ip_addresses.all | ip_address }}` → "uuid1 uuid2 uuid3"
  - **Architecture**: Clean `_build_record_data_variations` method creates multiple record data
- [x] **Multi-Record Update Logic**: Fix update path to properly handle count changes (3→2→1 IPs)
  - **Completed**: Reconciliation pattern compares desired vs existing state
  - **Architecture**: Delete/recreate approach when record counts change
- [x] **Create/Update Path Alignment**: Unified architecture between create and update operations
  - **Completed**: Shared helper methods for template rendering, zone lookup, record creation
  - **Code Quality**: Eliminated duplicate logic between creation and update paths
- [x] **Enhanced IP Address Filter**: Multi-IP collection support with space-delimited UUID output
  - **Completed**: Filter handles QuerySet collections, returns space-delimited UUIDs
  - **Testing**: Comprehensive test coverage for single and multiple IP scenarios
- [x] **Comprehensive Multi-Record Testing**: Complete test coverage for multi-record scenarios
  - **Completed**: End-to-end tests for 3→2→1 IP cleanup scenarios
  - **Coverage**: Orphaned record detection, signal integration, reconciliation logic
- [x] **Template Filter Validation**: Enhanced DNSRule.clean() catches compilation and runtime errors
  - **Completed**: Full template compilation testing during rule creation
  - **Enhancement**: Real object test rendering to catch runtime issues early
- [x] **Transaction Isolation**: Removed dangerous signal handler that could break IP assignments
  - **Completed**: Eliminated handle_m2m_wor handler with transaction-breaking exception handling
  - **Safety**: DNS failures can no longer poison main object transactions
- [ ] **Enhanced Interface IP Handling**: Production-ready multiple IP scenarios (replaces POC implementation)
- [x] **Device Primary IP Handling**: Support Device.primary_ip4/primary_ip6 DNS record creation
- [x] **VM/VMInterface Signal Handling**: Multiple record support for virtualization (1.0 priority)
  - **Completed**: Full VirtualMachine and VMInterface signal handling with location/tenant extraction via cluster relationships
  - **Architecture**: Unified signal architecture supporting both physical (Device/Interface) and virtual (VirtualMachine/VMInterface) infrastructure  
- [x] **Device Rename Cascade Handling**: Update all DNS records when device names change (vital for 1.0)
  - **Completed**: Implemented comprehensive signal deduplication with field change detection for Device and Interface models
  - **Architecture**: Smart change detection using has_model_field_changes() helper, cascade processing for interface DNS records when device fields change
- [x] **Graceful Jinja Error Handling**: Improve specific exception handling - catch expected errors gracefully, expose programming bugs
  - **Completed**: Refined exception handling strategy with specific exception types (DNSTemplateEmptyError, DNSProcessingError)
  - **Architecture**: Clean exception-based design allowing specific failures to be caught while preserving programming bug visibility

#### 4.2.3 Medium Priority  
- [x] **Location-Based Rule Scoping**: Design and implement location-scoped rules with global rule fallback
  - **Completed**: Location field added to DNSRule model with per-record-type precedence logic
  - **Architecture**: Location-specific rules override global rules for same record type; different record types can use different rule sources
  - **UI/API**: Full support for location filtering in forms, tables, and API endpoints
- [x] **Tenant-Based Rule Scoping**: Design and implement tenant-scoped rules
  - **Completed**: Full tenant scoping support with location-first precedence
  - **Architecture**: Location+Tenant > Location > Tenant > Global precedence hierarchy
  - **UI/API**: Tenant fields in forms, tables, and API filtering via TenancyModelFilterSetMixin
  - **Testing**: Comprehensive test coverage with 52 rule engine tests passing
- [ ] **Tag-Based Rule Scoping**: Design and implement tag-based rule filtering (not yet started)
- [ ] **DNS Rule Scope Visibility**: Add easy way to see all rules in scope for particular content type, location, or tenancy
  - **Purpose**: Debugging and rule management - show rule coverage and precedence for administrators
  - **Implementation Options**: Admin dashboard, object detail panels, dedicated rule analysis views
  - **User Benefit**: Understand which rules apply to which objects, troubleshoot rule conflicts, validate rule coverage
- [x] **Dynamic Rule Detail View Fields**: Update DNS rule detail view to only show fields relevant to the record type
  - **Completed**: Implemented dynamic field visibility using get_object() override in DNSRuleUIViewSet
  - **Implementation**: Override get_object() to build ObjectDetailContent panels dynamically based on record_type
  - **Field Logic**: A/AAAA/CNAME/PTR/TXT/NS show base + core templates; MX adds preference_template; SRV adds priority/weight/port templates
  - **User Benefit**: Cleaner detail views without irrelevant template fields, better UX with focused information
- [ ] **IP Address Lookup**: Solve A/AAAA record IP address field handling with VRF considerations
- [ ] **Manual Record Deletion Handling**: Clean up orphaned DNSRuleRecord entries
  - **Test Coverage**: Write test case that verifies DNSRuleRecord entries are properly cleaned up when corresponding DNS records are manually deleted
- [ ] **Template Failure Deletion Strategy**: Evaluate if deleting DNS records on template rendering failures is too aggressive
  - **Alternatives**: Consider graceful degradation, retry logic, or manual intervention flags instead of immediate deletion
  - **Impact**: Current approach may delete records due to transient failures (network issues, temporary locks)
- [ ] **A/AAAA Filter Requirement Validation**: Implement alternative validation for A/AAAA record value templates requiring | ip_address filter
  - **Context**: Removed from clean() method for more thoughtful implementation approach
  - **Options**: Form-level validation, runtime guidance, or UI hints
- [ ] **UI Record Indicators**: Add visual indicators for auto-created vs manual DNS records
  - **Purpose**: Provide users clear operational visibility to distinguish between automated and manually created DNS records
  - **UI Framework Approach**: Leverage Nautobot's UI Framework (TemplateExtension, ObjectsTablePanel) rather than Django templates
  - **Implementation Options**:
    - **Option 1 - Enhanced Table Columns (Primary)**: Add creation source indicator column using `django_tables2.TemplateColumn` with badges/icons
      - Badge approach: `<span class="label label-info"><i class="mdi mdi-robot"></i> Auto</span>` vs `<span class="label label-default"><i class="mdi mdi-account"></i> Manual</span>`
      - Inline approach: Enhanced name column with small automation icon next to auto-created records
    - **Option 2 - Custom Detail Panel (Secondary)**: Create `DNSRuleInfoPanel` using `nautobot.apps.ui.Panel` for comprehensive automation information
      - Shows creating rule, source object, automation status
      - Only renders for auto-created records (`should_render()` checks `obj.dns_rule_records.exists()`)
      - Positioned in detail view using `TemplateExtension` registration
    - **Option 3 - Model Properties**: Add efficiency properties (`is_auto_created`, `creating_rule`, `source_object`) for clean template access
    - **Option 4 - Filtering Support**: Add creation source filters in `FilterSet` to enable operational queries ("show only auto-created records")
  - **Architectural Decision**: Rejected job-based DNS processing due to queue flooding and race condition concerns; sticking with optimized signal handlers
  - **Implementation Priority**: Start with table columns for immediate visibility, add detail panels for comprehensive information
- [ ] **Rule Deletion Strategy**: Determine how to handle DNS records and DNSRuleRecords when a rule is deleted
- [ ] **Auto-Created Record Tagging**: Design how to mark auto-created DNS records (tags, status fields, etc.) and whether tag names should be configurable
- [ ] **IP Removal Handling**: Investigate better ways to handle IP removal than catching template exceptions - explore pre-validation approaches
- [ ] **Signal Optimization**: Optimize signal handling to only trigger for content types that have configured DNS rules
- [x] **Signal Coverage for 1.0 Release**: Implement signal receivers for VirtualMachine, VMInterface, Service (1.0 priority) as maybe 1.0. Consider Location, Rack/RackGroup/VLAN/Cluster for post-1.0
  - **Completed**: VirtualMachine, VMInterface, and Service signal handling implemented with location/tenant extraction
  - **Architecture**: Enhanced signal architecture with cascade processing for parent-child relationships (Device↔Interface, VirtualMachine↔VMInterface)
  - **Service Support**: Full signal handling for Service objects with device/virtual_machine location extraction
  - **Remaining**: VLAN/Cluster signal handling evaluation for 1.0 release
- [x] **Service DNS Rules**: Evaluate DNS rule support for Service objects since they can accept IP assignments ✅
  - **Completed**: Full Service DNS rule support implemented with comprehensive testing
- [ ] **InterfaceRedundancyGroup DNS Rules**: Evaluate DNS rule support for InterfaceRedundancyGroup objects since they can accept IP assignments
  - **Location Extraction**: Determine location resolution for these object types (Service may not have direct location, InterfaceRedundancyGroup location via member interfaces?)
  - **Anycast Address Handling**: Design patterns for handling anycast IP addresses that may be assigned to multiple objects across different locations
  - **Use Cases**: Service load balancer VIPs, redundancy group virtual IPs, shared service addresses
  - **Template Context**: Ensure template rendering works appropriately for objects that may span multiple physical locations
  - **Signal Handling**: Determine if these objects need dedicated signal receivers or can leverage existing IP assignment signals
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
- [ ] **Module-Based Interface Testing**: Test interfaces installed in modules to ensure location/tenant extraction works correctly
  - **Interface in Module**: Verify `interface.parent` correctly walks up module hierarchy to reach device for location/tenant resolution
  - **Interface in Nested Module**: Test multi-level module nesting scenarios where interface → module → parent_module → device
  - **Location/Tenant Inheritance**: Ensure module-based interfaces inherit location/tenant from their ultimate parent device
  - **Template Context**: Verify Jinja templates can access device properties through module hierarchy
  - **Signal Processing**: Confirm DNS rule processing works for module-based interface changes
- [ ] **DNSRuleRecord Cleanup Testing**: Test that DNSRuleRecord tracking entries are properly cleaned up when DNS records are deleted due to template failures
- [ ] **External Data Validation**: Ensure validation of template-rendered data with limited control (MX priority, SRV weights, port numbers, etc.)
- [ ] **DNS Rule Validation Conflicts**: Understand behavior when DNS rules generate records that violate existing DNS record model validation
- [ ] **Record-Type-Specific Field Validation**: Implement validation to make record-type-specific template fields required (MX preference_template, SRV priority/weight/port templates) per DNS RFC compliance

#### 4.2.4 User Experience Enhancements
- [ ] **Smart IP Version Detection**: Explore automatic IP version detection for ip_address filter
  - **Context Enhancement**: Add rule information to template context for smart filtering
  - **Filter Intelligence**: Enable `{{ obj.ip_addresses.all() | ip_address }}` without manual version parameters
  - **Implementation Options**: Enhanced context vs thread-local state vs specialized filter variants
  - **User Benefit**: Eliminate need for manual `| ip_address(4)` vs `| ip_address(6)` specification
- [ ] **User Template Test Rendering**: Provide UI functionality for users to test render DNS rule templates with specific objects
  - **Purpose**: Allow users to validate and debug templates during rule creation/editing
  - **Functionality**: Select object from dropdown, render template, show results in real-time
  - **Benefits**: Immediate feedback, reduced trial-and-error, better template debugging
- [ ] **GenericRelation vs Properties Evaluation**: Compare GenericRelation implementation against current property-based reverse relationships
  - **Current**: Property-based dns_rule_records and source_object properties on ARecordModel
  - **Alternative**: Django GenericRelation fields for reverse relationship traversal
  - **Evaluation Criteria**: SQL query performance, code complexity, Django best practices alignment
  - **Decision Factors**: Property N+1 queries vs GenericRelation prefetch optimization capabilities
- [ ] **Database Query Optimization**: Audit and optimize database queries throughout codebase using select_related/prefetch_related
  - **Focus Areas**: IPAddress template context rendering, reverse relationship traversals, bulk operations, signal handler field comparison safety
  - **Current Issues**: Field access in change detection may trigger SQL queries; template rendering relationship traversal; property access patterns
  - **Signal Handler Issue**: getattr() calls on ForeignKey fields in has_model_field_changes() trigger relation loading
  - **Proposed Solution**: Compare ForeignKey ID fields instead - use getattr(obj, f"{field.name}_id", None) to detect relationship changes without triggering SQL queries
  - **Optimization Targets**: Rule processing performance, bulk DNS record operations, relationship lookups, transaction duration reduction
  - **Benefits**: Reduced database load, faster template rendering, improved scalability, shorter transaction lock times
- [ ] **RFC-Compliant CNAME Handling**: ~~Improve CNAME record handling to comply with RFC 1912 section 2.4~~
  - No longer needed; tracked [issue #123](https://github.com/nautobot/nautobot-app-dns-models/issues/123)
- [ ] **UI DNS Error Feedback**: Extend UI to show DNS processing errors and status
  - **Purpose**: Provide users clean feedback about DNS rule failures without exposing raw exceptions
  - **Implementation Options**: Custom object detail panels, status indicators, background job integration
  - **User Experience**: Status panels on object detail pages, dashboard for DNS health monitoring
  - **Scope**: Plugin-friendly extensions (no core view modifications), proper separation of concerns
- [ ] **Fix Bulk Disable Validation Error**: Fix ValidationError when bulk-editing DNS rules to disable them
  - **Current Issue**: Template validation runs runtime test rendering even for disabled rules
  - **Problem**: Enhanced template validation blocks disabling rules when they fail test rendering
  - **Solution**: Skip runtime test rendering for disabled rules since they won't execute anyway
- [ ] **Refine ValueError Exception Handling**: Revisit broad ValueError catching in process_object
  - **Current Issue**: Generic ValueError catching may mask programming bugs
  - **Specific Target**: Consider specific DNSFilterError for ip_address filter failures vs generic ValueError
  - **Goal**: Distinguish between expected filter errors and unexpected programming issues
- [ ] **Fix Zone Fixed Reference**: Fix rule_engine.py reference to non-existent rule.zone_fixed field
  - **Current Issue**: Dead code path attempts to access rule.zone_fixed which doesn't exist on DNSRule model
  - **Root Cause**: Legacy code from when fixed zone selection was considered as a feature
  - **Solution**: Remove dead code path since all existing rules use zone_template field
- [x] **Fix DNS Rule Form JavaScript**: Fixed DNSRuleForm JavaScript integration for StaticSelect2 widget
  - **Completed**: Added dual event handling for select2:change and select2:select events to enable dynamic field visibility
  - **Benefit**: Users now see only relevant template fields based on selected record type (A, MX, SRV, etc.)
- [ ] **Evaluate Fixed Zone Selection Feature**: Evaluate whether to add fixed zone selection as UI feature vs current template-only approach
  - **Use Case**: Consider scenarios where users want different rules for different zones
  - **Design Question**: Whether literal strings in zone_template field are sufficient vs dedicated zone picker UI
  - **Trade-offs**: UX simplicity vs template flexibility, validation benefits vs implementation complexity

#### 4.2.5 Explicitly Deferred for Initial Release
- [ ] **Tenant Signal Handling**: Excluded due to massive cascade potential (could affect thousands of records)
- [ ] **VRF Signal Handling**: Excluded due to large-scale impact on IP addressing and related records
- [ ] **IPAddress Signal Handling**: Skipped for 1.0 as most IP-related changes are covered by Device/Interface/VM signals; may warrant revisiting if direct IPAddress rule targeting or IP-specific metadata usage emerges

#### 4.2.6 Future Enhancements

**HIGH PRIORITY:**
- [ ] **Template Whitespace Handling**: Implement whitespace stripping for multiline template renders and/or document the pitfalls of unintended whitespace in DNS record values. Multiline templates can introduce unwanted spaces/newlines that break DNS records.
- [ ] **Bulk Actions**: Verify that bulk actions work sanely; what happens if we add IPs to 100 interfaces?
- [ ] **Record Support**: Which records do we want in 1.0? Which can we confidentally say will be useful?
- [ ] **FR-025 and FR-026**: Indicators of automatic vs manual creation
- [ ] **ip_address filter**: Eliminate need for this entirely; handle in internally, complete with ip version autodetection if needed
- [ ] **dns_normalize filter**: eliminate need for this, maybe keep it around.
  - configure normalization at...? Rule level? Zone level? Globally?

**MEDIUM PRIORITY (Needed for 1.0):**
- [ ] **Template Design Best Practices Documentation**: Create comprehensive guide for DNS rule template design
  - Document safe vs risky template patterns (optional field handling, relationship traversal)
  - Provide device naming convention recommendations for DNS compatibility
  - Include zone template design patterns and examples
  - Cover performance considerations and operational best practices
  - Document common pitfalls (whitespace issues, case sensitivity, special characters)
  - Create template testing and validation guidelines
- [ ] **Documentation Cleanup Pass**: Review and polish all user documentation for clarity, accuracy, and completeness before 1.0 release
  - Update examples to reflect current implementation
  - Ensure consistency across all documentation files
  - Verify all template examples work correctly
  - Add missing sections or clarifications based on implementation experience

**MEDIUM PRIORITY (Future):**
- [ ] **InterfaceRedundancyGroup DNS Rules**: Implement DNS rule support for InterfaceRedundancyGroup objects with virtual IP addresses. The problems discussed below mean this will not be implemented soon.
  - **Model Characteristics & Unique Challenges**: 
    - Single `virtual_ip` ForeignKey (not ManyToMany like Interface/Service) - requires different IP processing logic
    - Multiple member interfaces via `InterfaceRedundancyGroupAssociation` with priority - complex relationship traversal
    - No direct tenant field - must derive from member interfaces with potential conflicts
    - Supports HSRP/VRRP-style redundancy protocols spanning multiple devices/locations
  - **Multi-Location Complexity (Major Challenge)**:
    - **Problem**: Redundancy groups can span devices in different locations, breaking location-scoped rule assumptions
    - **Primary Interface Strategy**: Use highest priority interface's location (`interface_redundancy_group_associations.order_by('-priority').first().interface.device.location`)
    - **Consensus Strategy**: Only allow location-scoped rules if all member interfaces share same location
    - **Conservative Strategy**: Return None for location (no location-scoped rules) to avoid ambiguity
    - **Impact**: Location extraction strategy affects which DNS rules apply to the redundancy group
  - **Tenant Extraction Complexity**:
    - **Primary Interface Approach**: Use highest priority interface's tenant (`primary_interface.device.tenant`)
    - **Consensus Approach**: Only return tenant if all member interfaces share same tenant
    - **Fallback Strategy**: Return None if no clear tenant consensus exists
    - **Edge Cases**: Handle scenarios where member interfaces have different tenants or no tenants
  - **Signal Handling Complexity**:
    - **Direct Changes**: `pre_save/post_save/post_delete` for InterfaceRedundancyGroup changes
    - **Membership Changes**: `m2m_changed` for `InterfaceRedundancyGroup.interfaces.through` - when interfaces added/removed
    - **Priority Changes**: Consider `InterfaceRedundancyGroupAssociation` signals for priority changes affecting primary interface selection
    - **Cascade Processing**: Interface changes should trigger redundancy group DNS rule reprocessing (complex dependency graph)
    - **Performance Impact**: Membership changes could trigger processing of multiple redundancy groups
  - **Implementation Phases**:
    - **Phase 1 (Conservative)**: Primary interface location/tenant, single virtual_ip processing, basic signal handling
    - **Phase 2 (Enhanced)**: Validation for same-location member interfaces, consensus-based extraction, full cascade processing
  - **Template Context Considerations**: 
    - `obj.virtual_ip` for the IP address (single object, not collection)
    - `obj.interfaces.all` for member interfaces (enables location/tenant validation in templates)
    - `obj.protocol` and `obj.protocol_group_id` for redundancy protocol information
  - **Architectural Impact**: May require extending location/tenant extraction logic to handle consensus-based resolution patterns
- [ ] **Cluster DNS Signal Support**: Implement signal handling for Cluster changes to cascade DNS updates to VirtualMachines and VMInterfaces
  - **Current State**: VirtualMachine and VMInterface DNS rules already work correctly with location/tenant extraction via cluster relationships
    - VirtualMachine location: `vm.cluster.location` (via property)
    - VirtualMachine tenant: `vm.tenant` with `vm.cluster.tenant` fallback
    - VMInterface location/tenant: inherited through virtual_machine → cluster relationships
  - **What Cluster Signals Would Add**:
    - **Cascade Updates**: When cluster location/tenant changes, automatically update DNS records for ALL VMs and VMInterfaces in that cluster
    - **Large-Scale Changes**: Support data center migrations, tenant reorganizations, infrastructure consolidation
    - **Operational Scenarios**: Cluster moves between locations, tenant reassignments affecting entire clusters
  - **Implementation Complexity**: Relatively simple signal handler with cascade processing
  - **Performance Impact**: 
    - **High Value**: Large clusters (50+ VMs) with frequent location/tenant changes
    - **Performance Cost**: Could trigger processing of hundreds of VMs/VMInterfaces per cluster change
    - **Database Load**: Significant SQL activity during cascade processing
  - **Value Assessment**:
    - **Implement if**: Large virtualization environments, frequent cluster changes, need guaranteed DNS consistency
    - **Skip if**: Small/stable clusters, rare cluster property changes, acceptable manual DNS updates
  - **Implementation**: Single signal handler processing all VMs and their VMInterfaces when cluster properties change
- [ ] **Model File Organization**: Consider splitting models.py into records.py and rules.py
- [ ] **DNS Lowercase Config**: Add configuration option to force DNS records to lowercase
- [ ] **Character Transform Config**: Add DNS character validation and transformation options
- [ ] **Template Field Naming**: Revisit field naming conventions (value_template vs content_template)
- [ ] **Custom Relationship DNS Rules**: Investigate scenarios where IPs have custom relationships (e.g., IP-to-Circuit) - determine if Circuit-based rules can leverage these relationships or if IP-based rules are needed for such cases
- [x] **Template Safety Documentation**: Document risks of using non-guaranteed fields in templates and provide mitigation strategies
  - **Risk**: Templates using optional fields (interface.role, device.primary_ip4) can cause DNS record deletion when fields become unavailable
  - **Current Behavior**: Rule engine removes all DNS records for an object when any template fails to render
  - **Mitigation Strategies**: Use conditional templates, default filters, or separate rules for optional vs required fields
  - **Examples**: Safe patterns like `{{ obj.role.name|default:"unknown" }}` vs risky patterns like `{{ obj.role.name }}`
- [ ] **Large-Scale DNS Update Job**: Implement Nautobot job for bulk DNS record updates based on user-supplied criteria
  - **Purpose**: Enable administrators to perform large-scale DNS updates without individual object modifications
  - **Scope Options**: 
    - **Global**: Process all objects matching rule criteria across entire system
    - **Tenant-Scoped**: Process objects within specific tenant(s) - `"run all rules for TENANT_X"`
    - **Location-Scoped**: Process objects within specific location(s) - `"run all rules for LOCATION_Y"`
    - **Rule-Specific**: Execute specific rule(s) with optional scoping - `"run RULE_Z in LOCATION_Y"`
    - **Record-Type-Specific**: Process all A records, CNAME records, etc. with optional scoping
  - **Use Cases**: 
    - **Migration Scenarios**: Bulk DNS updates during infrastructure migrations or reorganizations
    - **Template Updates**: Re-process DNS records after rule template modifications
    - **Cleanup Operations**: Regenerate DNS records after data corrections or imports
    - **Selective Processing**: Target specific subsets of infrastructure for DNS updates
  - **Implementation Considerations**:
    - **Job Parameters**: Tenant selection, location selection, rule selection, dry-run mode
    - **Progress Tracking**: Job progress reporting for large-scale operations
    - **Error Handling**: Graceful handling of individual record failures without stopping entire job
    - **Performance**: Batch processing to avoid overwhelming the system
    - **Logging**: Detailed logging of changes made for audit purposes

#### 4.2.7 Architectural Investigations
- [ ] **Separate DNSRule Classes Architecture**: Investigate splitting DNSRule into type-specific classes (ADNSRule, MXDNSRule, SRVDNSRule, etc.)
  - **Benefits**: No unused fields, better validation, cleaner forms, potentially fewer GenericForeignKeys, better database performance
  - **Challenges**: Complex abstraction layer, migration complexity, multiple models to maintain
  - **Interface**: Maintain unified external interface (single navbar item, API endpoint, creation flow)
  - **Assessment**: Could be excellent for v2.0 architecture but significant undertaking

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

## 7. Template Design Best Practices

### 7.1 Template Safety and Reliability

#### 7.1.1 Handling Optional Fields
- **Problem**: Templates using optional fields can cause DNS record deletion when fields become unavailable
- **Risk**: Current behavior removes all DNS records for an object when any template fails to render
- **Best Practices**:
  - Use conditional templates with default values: `{{ obj.role.name|default:"unknown" }}`
  - Avoid risky patterns: `{{ obj.role.name }}` (fails if role is None)
  - Test templates with objects that have missing optional fields
  - Consider separate rules for optional vs required fields

#### 7.1.2 Relationship Traversal Safety
- **Safe Patterns**:
  ```jinja2
  {{ obj.device.name|default:"no-device" }}
  {{ obj.interface.device.location.name|default:"no-location" }}
  ```
- **Risky Patterns**:
  ```jinja2
  {{ obj.device.name }}  # Fails if device is None
  {{ obj.interface.device.location.name }}  # Fails at any None link
  ```

#### 7.1.3 Field Availability Validation
- **Required Fields**: Use fields that are guaranteed to exist (name, pk, etc.)
- **Optional Fields**: Always provide defaults or use conditional logic
- **Foreign Keys**: Check for None before traversal or use defaults
- **Many-to-Many**: Use `.exists()` checks before accessing collections

### 7.2 DNS Naming Conventions

#### 7.2.1 Device Naming Best Practices
- **Consistent Naming**: Establish device naming standards that work well in DNS
- **DNS-Safe Characters**: Avoid special characters that require escaping
- **Predictable Patterns**: Use naming that enables consistent template design
- **Examples**:
  ```jinja2
  # Good: Predictable device names
  {{ obj.device.name }}.{{ obj.device.location.name }}.example.com
  
  # Better: With safety defaults
  {{ obj.device.name|default:"unknown" }}.{{ obj.device.location.name|default:"global" }}.example.com
  ```

#### 7.2.2 Zone Template Design
- **Consistent Zones**: Use predictable zone patterns based on location/tenant
- **Hierarchical Design**: Consider subdomain organization
- **Examples**:
  ```jinja2
  # Location-based zones
  {{ obj.device.location.name|default:"global" }}.example.com
  
  # Tenant-based zones  
  {{ obj.device.tenant.name|default:"shared" }}.example.com
  
  # Combined approach
  {{ obj.device.location.name|default:"global" }}.{{ obj.device.tenant.name|default:"shared" }}.example.com
  ```

### 7.3 Template Performance Considerations

#### 7.3.1 Relationship Optimization
- **Minimize Deep Traversal**: Avoid excessive relationship chains
- **Consider Caching**: Be aware that relationship traversal triggers database queries
- **Batch-Friendly Patterns**: Design templates that work well with bulk operations

#### 7.3.2 Filter Usage Guidelines
- **IP Address Filters**: Use `| ip_address` filter for A/AAAA records
- **String Manipulation**: Use built-in Jinja filters for text processing
- **Custom Filters**: Leverage DNS-specific filters provided by the plugin

### 7.4 Operational Best Practices

#### 7.4.1 Template Testing Strategy
- **Test with Real Data**: Validate templates against actual objects in your environment
- **Edge Case Testing**: Test with objects missing optional fields
- **Bulk Testing**: Verify templates work correctly across large object sets
- **Version Control**: Track template changes and test before deployment

#### 7.4.2 Rule Organization
- **Descriptive Names**: Use clear, descriptive rule names
- **Documentation**: Document complex template logic in rule descriptions
- **Scoping Strategy**: Use location/tenant scoping appropriately
- **Record Type Separation**: Consider separate rules for different record types

#### 7.4.3 Monitoring and Maintenance
- **Error Monitoring**: Monitor DNS rule processing logs for template failures
- **Regular Audits**: Periodically review DNS records for accuracy
- **Template Updates**: Plan for template updates when data models change
- **Rollback Strategy**: Have procedures for reverting problematic template changes

### 7.5 Common Pitfalls and Solutions

#### 7.5.1 Template Whitespace Issues
- **Problem**: Multiline templates can introduce unwanted whitespace in DNS records
- **Solution**: Use Jinja whitespace control or single-line templates
- **Example**:
  ```jinja2
  # Problematic (introduces newlines)
  {{ obj.device.name }}
  .{{ obj.device.location.name }}
  .example.com
  
  # Better (single line)
  {{ obj.device.name }}.{{ obj.device.location.name }}.example.com
  ```

#### 7.5.2 Case Sensitivity Considerations
- **DNS Standards**: DNS is case-insensitive but consistency is important
- **Template Design**: Consider consistent casing in templates
- **Future Enhancement**: Configuration options for automatic case normalization

#### 7.5.3 Special Character Handling
- **DNS Compliance**: Ensure generated names comply with DNS character restrictions
- **Character Substitution**: Plan for handling special characters in source data
- **Validation**: Consider validation of generated DNS names

## 8. Known Issues and Bugs

### 8.1 UI Display Issues
- **BUG-001**: DNS Rule Record List View - `source_object` and `dns_rule` columns are not visible for some DNS record content types
  - **Affected**: MX records (confirmed), other record types status unknown
  - **Working**: A records (confirmed)
  - **Impact**: Users cannot see which rule created which DNS record or what source object triggered the creation
  - **Workaround**: Information is available via API and detail views
  - **Priority**: Medium - affects user experience but doesn't break functionality

### 8.2 API Performance Issues
- **BUG-002**: DNSRuleRecord API N+1 Query Problem - API calls trigger excessive database queries
  - **Current State**: 24 queries for 5 DNSRuleRecord results (baseline measurement)
  - **Root Causes**: 
    - ContentType N+1: Same `dcim.device` ContentType queried 5 times individually
    - ARecord N+1: Individual ARecord queries instead of bulk prefetch
    - Missing query optimization in DNSRuleRecordViewSet
  - **Impact**: Poor API performance, especially with large datasets
  - **Priority**: High - Required for v1.0
  - **Solution Plan**:
    1. Add `select_related("rule", "content_type", "dns_record_content_type")` for direct FK relationships
    2. Add `prefetch_related("source_object", "dns_record")` for generic FK relationships  
    3. Optimize ContentType handling in DNSRule to accept objects/IDs (separate issue)
    4. Re-test to confirm query count reduction

- **BUG-003**: ContentType String Handling Inefficiency - String-based ContentType operations may trigger unnecessary SQL queries
  - **Issue**: DNSRule ContentType handling may be inefficient when using string format (`"dcim.device"`)
  - **Impact**: Additional database queries for ContentType lookups during rule operations
  - **Priority**: High - Required for v1.0
  - **Investigation Needed**: Confirm if string->ID conversion triggers SQL queries
  - **Solution Plan**:
    1. Allow DNSRule.content_type to accept ContentType objects/IDs for ORM operations
    2. Maintain string format support for API usability (`"dcim.device"` format)
    3. Ensure ContentType dropdown in DNSRule form works properly
    4. Resolve previous form field attribute conflicts

## 9. Future Considerations

### 9.1 Configuration Options
- Global vs rule-level DNS record formatting options for things like enforcing lower-case
- Character transformation rules for DNS compliance for things like `/` -> `-`

### 9.2 Advanced Rule Scoping and Inheritance
- [x] **Location Rule Scoping**: Implement location-based rule hierarchies ✅
  - **Completed**: Global rules apply to all objects; location-specific rules override global rules per record type
  - **Architecture**: Per-record-type precedence - location A rule + global CNAME rule both apply to same object
  - **Precedence Logic**: Location-specific rules take priority over global rules for same record type
- [ ] **Tenant Rule Scoping**: Extend to tenant-based rule hierarchies
  - Do global rules apply to objects with specific tenants configured?
  - When both global and tenant-specific rules exist, which takes precedence?
  - How does rule inheritance work down organizational hierarchies?
- [x] **Location-Based Rule Precedence**: Implement location vs global rule hierarchy ✅
  - **Completed**: Location-specific vs global rule priority with per-record-type resolution
  - **Architecture**: Different record types can use different rule sources (location vs global)
- [ ] **Full Rule Precedence System**: Extend to tenant-specific precedence and user control over precedence order
- [ ] **Per-Zone Rule Support**: Evaluate zone-scoped rule organization
  - Should rules be scoped to specific DNS zones for better performance?
  - How do zone-scoped rules interact with template-calculated zones?
  - Organization benefits vs complexity trade-offs

### 9.3 Advanced Features  
- Rule condition logic (beyond content type matching); location, vrf, tags, etc.
- Bulk rule operations
- Rule import/export functionality
- Template validation and testing tools

### 9.4 Monitoring and Observability
- Rule execution metrics
- Template rendering performance monitoring
- DNS record lifecycle tracking

### 9.5 Performance Testing and Profiling System
- **REQ-PERF-001**: Implement automated performance profiling system for all database operations
  - **Scope**: Profile all actions that trigger database operations (API calls, signal handlers, bulk operations)
  - **Storage**: Store query profiles in versioned files with each commit/release
  - **Comparison**: Automated comparison system for new commits/releases vs baseline
  - **Benefits**: 
    - Know exact query profile at any given time
    - Quantify performance improvements/regressions
    - Prevent N+1 query reintroduction
    - Track optimization effectiveness over time
  - **Implementation**: Extend existing test infrastructure to capture and store SQL query patterns, timing, and counts
  - **Integration**: Include in CI/CD pipeline for automated performance regression detection
  - **Note**: Consider [`django-queryhunter`](https://github.com/PaulGilmartin/django-queryhunter) library for advanced query analysis and N+1 detection

### 9.6 DNS Record Class Auto-Detection System
- **REQ-ARCH-001**: Implement dynamic DNS record class discovery and configuration generation
  - **Problem**: DNS record types are currently defined in multiple places with variations:
    - `RECORD_TYPE_CHOICES` in `models.py`
    - Static model lists in `api/serializers.py`
    - Record type mappings in `rule_engine.py`
    - Manual maintenance required when adding new record types
  - **Solution**: Create centralized auto-detection system
    - **Discovery**: Automatically detect available DNS record classes (ARecord, CNAMERecord, etc.)
    - **Generation**: Dynamically generate `RECORD_TYPE_CHOICES` and `RECORD_MODEL_MAPPING` from discovered classes (check DNSRecord.__subclasses__())
    - **Consolidation**: Single source of truth for all DNS record type configurations
    - **Modularity**: Extract into separate module (e.g., `dns_record_registry.py`)
  - **Benefits**:
    - Eliminate duplicate/inconsistent definitions across files
    - Automatic support for new record types without manual updates
    - Reduced maintenance burden
    - Consistent behavior across API, models, and rule engine
  - **Implementation**: Inspect DNS record model classes at runtime and build configuration dictionaries

## 10. Dependencies

### 10.1 External Dependencies
- Nautobot 2.4+
- Django contenttypes framework
- Jinja2 templating engine

### 10.2 Internal Dependencies
- Existing DNS record models
- Nautobot signal system
- Nautobot utilities (render_jinja2, forms, etc.)

---

**Document Version**: 1.0  
**Last Updated**: Current implementation status  
**Next Review**: After JavaScript implementation completion
