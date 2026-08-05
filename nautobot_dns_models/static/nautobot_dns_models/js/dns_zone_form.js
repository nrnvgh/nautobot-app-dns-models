/**
 * DNS Zone Form - disable auto_create_ptr when zone_type is Catalog.
 *
 * On create, zone_type is still editable, so the control must track the select.
 * On edit, zone_type is already disabled server-side and this script exits early.
 */

document.addEventListener("DOMContentLoaded", function () {
    const zoneTypeField = document.getElementById("id_zone_type");
    const autoCreatePtrField = document.getElementById("id_auto_create_ptr");

    if (!zoneTypeField || !autoCreatePtrField) {
        return;
    }

    // Edit already disables zone_type server-side; leave auto_create_ptr as the form set it.
    if (zoneTypeField.disabled) {
        return;
    }

    const catalogHelpText = "Catalog zones cannot enable automatic PTR creation.";
    // Nautobot render_field wraps each control in div.mb-10 with an optional span.form-text.
    const fieldContainer = autoCreatePtrField.closest(".mb-10, .form-group, .mb-3, .field");
    const helpElement = fieldContainer
        ? fieldContainer.querySelector(".form-text, .help-block")
        : null;
    const defaultHelpText = helpElement ? helpElement.textContent : "";

    function updateAutoCreatePtr() {
        const isCatalog = zoneTypeField.value === "catalog";

        autoCreatePtrField.disabled = isCatalog;
        if (isCatalog) {
            autoCreatePtrField.checked = false;
        }

        if (helpElement) {
            helpElement.textContent = isCatalog ? catalogHelpText : defaultHelpText;
        }
    }

    updateAutoCreatePtr();
    $(zoneTypeField).on("change select2:select select2:clear", updateAutoCreatePtr);
});
