"""Performance tests for DNS rule processing."""

import time

from django.contrib.contenttypes.models import ContentType
from django.db import connection, transaction
from django.db.models.signals import m2m_changed, post_save
from django.test import TestCase, override_settings
from nautobot.dcim.models import Device, DeviceType, Interface, Location, LocationType, Manufacturer
from nautobot.extras.models import Role, Status
from nautobot.ipam.models import IPAddress, Namespace, Prefix

from nautobot_dns_models import signals
from nautobot_dns_models.models import ARecord, DNSRule, DNSRuleRecord, DNSZone


@override_settings(DEBUG=True)
class IPAssignmentPerformanceTestCase(TestCase):
    """
    Performance tests for IP assignment with and without DNS rules.

    Tests measure only the IP assignment time, not the setup overhead.
    """

    absolute_baseline_time = 0.0
    absolute_baseline_queries = 0
    baseline_time = 0.0
    baseline_queries = 0

    @classmethod
    def setUpTestData(cls):
        """Create test infrastructure once - not included in performance timing."""

        # Create basic infrastructure
        cls.location_type = LocationType.objects.create(name="Test Location Type")
        cls.location = Location.objects.create(
            name="Test Location",
            location_type=cls.location_type,
            status=Status.objects.get_for_model(Location).first(),
        )

        cls.manufacturer = Manufacturer.objects.create(name="Test Manufacturer")

        cls.device_type = DeviceType.objects.create(
            manufacturer=cls.manufacturer,
            model="Test Switch",
        )

        # Get or create device role
        device_role = Role.objects.get_for_model(Device).first()
        if not device_role:
            device_role = Role.objects.create(name="Test Device Role")
            device_role.content_types.set([ContentType.objects.get_for_model(Device)])
        cls.device_role = device_role

        cls.device = Device.objects.create(
            name="perf-test-device",
            device_type=cls.device_type,
            role=cls.device_role,
            location=cls.location,
            status=Status.objects.get_for_model(Device).first(),
        )

        # Create 128 interfaces
        cls.interfaces = []
        for i in range(128):
            interface = Interface.objects.create(
                name=f"Ethernet{i:03d}",
                device=cls.device,
                type="1000base-t",
                status=Status.objects.get_for_model(Interface).first(),
            )
            cls.interfaces.append(interface)

        # Create namespace and prefix
        cls.namespace = Namespace.objects.create(name="Test Namespace")
        cls.prefix = Prefix.objects.create(
            network="10.0.0.0",
            prefix_length=16,
            namespace=cls.namespace,
            status=Status.objects.get_for_model(Prefix).first(),
        )

        # Create 128 IP addresses
        cls.ip_addresses = []
        for i in range(128):
            ip = IPAddress.objects.create(
                address=f"10.0.1.{i + 1}/24",
                parent=cls.prefix,
                status=Status.objects.get_for_model(IPAddress).first(),
            )
            cls.ip_addresses.append(ip)

        # Create DNS zone for rule testing
        cls.dns_zone = DNSZone.objects.create(
            name="perf.test.internal",
            soa_mname="ns.perf.test.internal",
            soa_rname="admin@perf.test.internal",
        )

    def test_ip_assignment_performance_absolute_baseline(self):
        """Measure IP assignment performance with DNS signal handlers completely disabled."""

        print("\n=== IP Assignment Performance (Absolute Baseline - No DNS Handlers) ===")

        # Temporarily disconnect all DNS signal handlers
        post_save.disconnect(signals.handle_object_save, sender=Interface)
        m2m_changed.disconnect(signals.handle_m2m_changed, sender=Interface.ip_addresses.through)

        try:
            # Clear query log
            connection.queries_log.clear()
            initial_query_count = len(connection.queries)

            # Measure pure Django IP assignment time
            start_time = time.perf_counter()

            with transaction.atomic():
                for interface, ip_address in zip(self.interfaces, self.ip_addresses):
                    interface.ip_addresses.add(ip_address)

            end_time = time.perf_counter()

            assignment_time_ms = (end_time - start_time) * 1000
            total_queries = len(connection.queries) - initial_query_count

            print("Assigned 128 IPs to 128 interfaces")
            print(f"Total Time: {assignment_time_ms:.1f}ms")
            print(f"Per Assignment: {assignment_time_ms / 128:.2f}ms")
            print(f"Total Queries: {total_queries}")
            print(f"Queries per Assignment: {total_queries / 128:.1f}")

            # Store absolute baseline for comparison (using class variable)
            print(f"Storing absolute baseline: {assignment_time_ms:.1f}ms, {total_queries} queries")
            self.__class__.absolute_baseline_time = assignment_time_ms
            self.__class__.absolute_baseline_queries = total_queries

        finally:
            # Always reconnect handlers for other tests
            post_save.connect(signals.handle_object_save, sender=Interface)
            m2m_changed.connect(signals.handle_m2m_changed, sender=Interface.ip_addresses.through)

    def test_ip_assignment_performance_without_dns_rules(self):
        """Measure IP assignment performance with no DNS rules enabled."""
        # Ensure no DNS rules exist
        print("\n=== IP Assignment Performance (No DNS Rules) ===")
        print(f"Baseline time: {self.baseline_time:.1f}ms, {self.baseline_queries} queries")
        print(f"Absolute baseline time: {self.absolute_baseline_time:.1f}ms, {self.absolute_baseline_queries} queries")

        # Clear query log
        connection.queries_log.clear()
        initial_query_count = len(connection.queries)

        # Measure IP assignment time
        start_time = time.perf_counter()

        with transaction.atomic():
            for interface, ip_address in zip(self.interfaces, self.ip_addresses):
                interface.ip_addresses.add(ip_address)

        end_time = time.perf_counter()

        assignment_time_ms = (end_time - start_time) * 1000
        total_queries = len(connection.queries) - initial_query_count

        print("\n=== IP Assignment Performance (No DNS Rules) ===")
        print("Assigned 128 IPs to 128 interfaces")
        print(f"Total Time: {assignment_time_ms:.1f}ms")
        print(f"Per Assignment: {assignment_time_ms / 128:.2f}ms")
        print(f"Total Queries: {total_queries}")
        print(f"Queries per Assignment: {total_queries / 128:.1f}")

        # Store baseline for comparison (using class variable)
        self.__class__.baseline_time = assignment_time_ms
        self.__class__.baseline_queries = total_queries

        # Compare to absolute baseline if available
        if self.__class__.absolute_baseline_time:
            signal_overhead_ms = assignment_time_ms - self.__class__.absolute_baseline_time
            signal_overhead_percent = (signal_overhead_ms / self.__class__.absolute_baseline_time) * 100
            query_overhead = total_queries - self.__class__.absolute_baseline_queries

            print("\n=== Signal Handler Overhead ===")
            print(f"Signal Overhead: {signal_overhead_ms:.1f}ms ({signal_overhead_percent:.1f}% increase)")
            print(f"Signal Query Overhead: {query_overhead} queries")

    def test_ip_assignment_performance_with_dns_rules(self):  # pylint: disable=too-many-locals
        """Measure IP assignment performance with DNS rules enabled."""
        # Create a DNS rule for interfaces
        DNSRule.objects.create(
            name="Performance Test A Record",
            enabled=True,
            content_type=ContentType.objects.get_for_model(Interface),
            zone_template="perf.test.internal",
            record_type="A",
            name_template="{{ obj.name }}.{{ obj.device.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
        )

        # Clear query log
        connection.queries_log.clear()
        initial_query_count = len(connection.queries)

        # Measure IP assignment time with DNS processing
        start_time = time.perf_counter()

        with transaction.atomic():
            for interface, ip_address in zip(self.interfaces, self.ip_addresses):
                interface.ip_addresses.add(ip_address)

        end_time = time.perf_counter()

        assignment_time_ms = (end_time - start_time) * 1000
        total_queries = len(connection.queries) - initial_query_count

        print("\n=== IP Assignment Performance (With DNS Rules) ===")
        print("Assigned 128 IPs to 128 interfaces")
        print(f"Total Time: {assignment_time_ms:.1f}ms")
        print(f"Per Assignment: {assignment_time_ms / 128:.2f}ms")
        print(f"Total Queries: {total_queries}")
        print(f"Queries per Assignment: {total_queries / 128:.1f}")

        # Calculate DNS overhead if baseline exists
        if self.__class__.baseline_time:
            overhead_ms = assignment_time_ms - self.__class__.baseline_time
            overhead_percent = (overhead_ms / self.__class__.baseline_time) * 100
            query_overhead = total_queries - self.__class__.baseline_queries

            print("\n=== DNS Processing Overhead ===")
            print(f"Time Overhead: {overhead_ms:.1f}ms ({overhead_percent:.1f}% increase)")
            print(f"Query Overhead: {query_overhead} queries")
            print(f"DNS Time per Assignment: {overhead_ms / 128:.2f}ms")

        # Calculate total system overhead if absolute baseline exists
        if self.__class__.absolute_baseline_time:
            total_overhead_ms = assignment_time_ms - self.__class__.absolute_baseline_time
            total_overhead_percent = (total_overhead_ms / self.__class__.absolute_baseline_time) * 100
            total_query_overhead = total_queries - self.__class__.absolute_baseline_queries

            print("\n=== Total DNS System Overhead ===")
            print(f"Total Overhead: {total_overhead_ms:.1f}ms ({total_overhead_percent:.1f}% vs pure Django)")
            print(f"Total Query Overhead: {total_query_overhead} queries")
            print(f"Total System Cost per Assignment: {total_overhead_ms / 128:.2f}ms")

        # Verify DNS records were actually created
        a_records = ARecord.objects.count()
        tracking_records = DNSRuleRecord.objects.count()

        print("\n=== DNS Records Created ===")
        print(f"A Records: {a_records}")
        print(f"DNSRuleRecord tracking: {tracking_records}")

        # Assertions for correctness
        self.assertEqual(a_records, 128, "Should create one A record per interface")
        self.assertEqual(tracking_records, 128, "Should create one tracking record per interface")

    def test_sequential_ip_assignment_performance(self):
        """Test performance of sequential individual IP assignments."""
        # Create single DNS rule
        DNSRule.objects.create(
            name="Sequential Test A Record",
            enabled=True,
            content_type=ContentType.objects.get_for_model(Interface),
            zone_template="perf.test.internal",
            record_type="A",
            name_template="{{ obj.name }}.{{ obj.device.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
        )

        # Measure individual assignment times
        assignment_times = []
        query_counts = []

        for i, (interface, ip_address) in enumerate(zip(self.interfaces[:10], self.ip_addresses[:10])):
            connection.queries_log.clear()
            initial_queries = len(connection.queries)

            start_time = time.perf_counter()
            interface.ip_addresses.add(ip_address)
            end_time = time.perf_counter()

            assignment_time_ms = (end_time - start_time) * 1000
            query_count = len(connection.queries) - initial_queries

            assignment_times.append(assignment_time_ms)
            query_counts.append(query_count)

            if i < 3:  # Log first few for pattern analysis
                print(f"Assignment {i+1}: {assignment_time_ms:.1f}ms, {query_count} queries")

        avg_time = sum(assignment_times) / len(assignment_times)
        avg_queries = sum(query_counts) / len(query_counts)

        print("\n=== Sequential Assignment Performance (10 samples) ===")
        print(f"Average Time: {avg_time:.1f}ms per assignment")
        print(f"Average Queries: {avg_queries:.1f} per assignment")
        print(f"Time Range: {min(assignment_times):.1f}ms - {max(assignment_times):.1f}ms")
        print(f"Query Range: {min(query_counts)} - {max(query_counts)} queries")

    def test_single_ip_assignment_sql_analysis_absolute_baseline(self):
        """Analyze SQL queries for single IP assignment with no DNS handlers at all."""
        print("\n=== SQL Analysis: Single IP Assignment (Absolute Baseline - No DNS Handlers) ===")

        # Temporarily disconnect DNS signal handlers
        post_save.disconnect(signals.handle_object_save, sender=Interface)
        m2m_changed.disconnect(signals.handle_m2m_changed, sender=Interface.ip_addresses.through)

        try:
            # Use a specific interface and IP for analysis
            interface = self.interfaces[10]  # Different from other analysis tests
            ip_address = self.ip_addresses[10]

            # Clear queries and capture
            connection.queries.clear()

            # Perform the assignment
            start_time = time.perf_counter()
            interface.ip_addresses.add(ip_address)
            end_time = time.perf_counter()

            assignment_time_ms = (end_time - start_time) * 1000
            queries = connection.queries

            print(f"Assignment Time: {assignment_time_ms:.1f}ms")
            print(f"Total Queries: {len(queries)}")
            print("\nSQL Queries (in order):")

            for i, query in enumerate(queries, 1):
                sql = query["sql"].replace('"', "").replace("\n", " ")
                time_ms = float(query.get("time", 0)) * 1000
                print(f"{i:2d}. [{time_ms:5.1f}ms] {sql}")

        finally:
            # Always reconnect handlers
            post_save.connect(signals.handle_object_save, sender=Interface)
            m2m_changed.connect(signals.handle_m2m_changed, sender=Interface.ip_addresses.through)

    def test_single_ip_assignment_sql_analysis_no_rules(self):
        """Analyze SQL queries for single IP assignment without DNS rules."""

        print("\n=== SQL Analysis: Single IP Assignment (No DNS Rules) ===")

        # Use first interface and IP for analysis
        interface = self.interfaces[0]
        ip_address = self.ip_addresses[0]

        # Clear queries and capture
        connection.queries.clear()

        # Perform the assignment
        start_time = time.perf_counter()
        interface.ip_addresses.add(ip_address)
        end_time = time.perf_counter()

        assignment_time_ms = (end_time - start_time) * 1000
        queries = connection.queries

        print(f"Assignment Time: {assignment_time_ms:.1f}ms")
        print(f"Total Queries: {len(queries)}")
        print("\nSQL Queries (in order):")

        for i, query in enumerate(queries, 1):
            sql = query["sql"].replace('"', "").replace("\n", " ")
            print(f"{i:2d}. {sql}")

    def test_single_ip_assignment_sql_analysis_with_rules(self):
        """Analyze SQL queries for single IP assignment with DNS rules."""
        # Create DNS rule for comparison
        DNSRule.objects.create(
            name="SQL Analysis A Record",
            enabled=True,
            content_type=ContentType.objects.get_for_model(Interface),
            zone_template="perf.test.internal",
            record_type="A",
            name_template="{{ obj.name }}.{{ obj.device.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
        )

        print("\n=== SQL Analysis: Single IP Assignment (With DNS Rules) ===")

        # Use second interface and IP for analysis (first already used)
        interface = self.interfaces[1]
        ip_address = self.ip_addresses[1]

        # Clear queries and capture
        connection.queries.clear()

        # Perform the assignment
        start_time = time.perf_counter()
        interface.ip_addresses.add(ip_address)
        end_time = time.perf_counter()

        assignment_time_ms = (end_time - start_time) * 1000
        queries = connection.queries

        print(f"Assignment Time: {assignment_time_ms:.1f}ms")
        print(f"Total Queries: {len(queries)}")
        print("\nSQL Queries (in order):")

        for i, query in enumerate(queries, 1):
            sql = query["sql"].replace('"', "").replace("\n", " ")
            time_ms = float(query.get("time", 0)) * 1000
            print(f"{i:2d}. [{time_ms:5.1f}ms] {sql}")

        # Verify DNS record was created
        a_record_count = ARecord.objects.filter(name=f"{interface.name}.{interface.device.name}").count()
        tracking_count = DNSRuleRecord.objects.filter(object_id=str(interface.pk)).count()

        print("\nDNS Records Created:")
        print(f"A Records: {a_record_count}")
        print(f"DNSRuleRecord tracking: {tracking_count}")
