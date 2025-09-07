/**
 * DNS Rule Form - Dynamic Field Management
 * - Zone field visibility based on zone_source selection
 * - Component management (add/delete/reorder)
 * Uses standard Django field IDs and formset management
 */

document.addEventListener("DOMContentLoaded", function() {
    const zoneSourceField = document.getElementById("id_zone_source");
    
    if (!zoneSourceField) {
        return; // Not on the DNS rule form
    }

    // Define which fields should be visible for each zone source type
    const fieldMapping = {
        "fixed": ["zone_fixed"],
        "field_reference": ["zone_field_path"],
        "custom_field": ["zone_custom_field"]
    };

    // All zone fields that can be shown/hidden
    const allZoneFields = [
        "zone_fixed",
        "zone_field_path",
        "zone_custom_field"
    ];

    function updateZoneFieldVisibility() {
        const selectedSource = zoneSourceField.value;
        const visibleFields = fieldMapping[selectedSource] || [];

        allZoneFields.forEach(fieldName => {
            const field = document.getElementById(`id_${fieldName}`);
            const fieldRow = field ? field.closest(".form-group, .row, .field, .form-field") : null;
            const fieldLabel = field ? document.querySelector(`label[for="id_${fieldName}"]`) : null;
            
            if (fieldRow) {
                if (visibleFields.includes(fieldName)) {
                    // Show field and mark as required (Nautobot style: bold label)
                    fieldRow.style.display = "";
                    field.required = true;
                    if (fieldLabel) {
                        fieldLabel.style.fontWeight = "bold";
                    }
                } else {
                    // Hide field and remove requirement
                    fieldRow.style.display = "none";
                    field.required = false;
                    field.value = ""; // Clear hidden field values
                    if (fieldLabel) {
                        fieldLabel.style.fontWeight = "normal";
                    }
                }
            }
        });
    }

    function initializeFieldState() {
        // Initial setup - handle the default state properly
        updateZoneFieldVisibility();
    }

    // Initialize on page load
    initializeFieldState();

    // Handle Select2 events (StaticSelect2 widgets use jQuery events)
    $(document).ready(function() {
        $('#id_zone_source').on('change', function() {
            updateZoneFieldVisibility();
        });
    });
});