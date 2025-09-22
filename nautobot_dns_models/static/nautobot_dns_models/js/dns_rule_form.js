/**
 * DNS Rule Form - Dynamic Field Visibility
 * Shows/hides template fields based on selected record type
 */

document.addEventListener("DOMContentLoaded", function() {
    const recordTypeField = document.getElementById("id_record_type");
    
    if (!recordTypeField) {
        return; // Not on the DNS rule form
    }

    // Define which fields should be visible for each record type
    const fieldMapping = {
        "A": ["value_template"],
        "AAAA": ["value_template"],
        "CNAME": ["value_template"],
        "TXT": ["value_template"],
        "PTR": ["value_template"],
        "NS": ["value_template"],
        "MX": ["value_template", "preference_template"],
        "SRV": ["value_template", "priority_template", "weight_template", "port_template"]
    };

    // All template fields that can be shown/hidden
    const allTemplateFields = [
        "value_template",
        "preference_template", 
        "priority_template",
        "weight_template",
        "port_template"
    ];

    function updateFieldVisibility() {
        const selectedType = recordTypeField.value;
        const visibleFields = fieldMapping[selectedType] || [];

        allTemplateFields.forEach(fieldName => {
            const fieldRow = document.querySelector(`#id_${fieldName}`).closest(".form-group, .row, .field");
            if (fieldRow) {
                if (visibleFields.includes(fieldName)) {
                    fieldRow.style.display = "";
                } else {
                    fieldRow.style.display = "none";
                }
            }
        });
    }

    // Initial setup
    updateFieldVisibility();

    $(recordTypeField).on("select2:change select2:select", updateFieldVisibility);
});
