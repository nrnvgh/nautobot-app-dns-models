"""Helpers for supported source models in DNS rule processing."""

from nautobot_dns_models.constants import SUPPORTED_SOURCE_MODELS


def get_supported_source_model_pairs():
    """Build supported source-model `(app_label, model_name)` pairs.

    Returns:
        tuple[tuple[str, str], ...]: Immutable sequence of `(app_label, model_name)` pairs
            derived from `SUPPORTED_SOURCE_MODELS`.
    """
    return tuple((model._meta.app_label, model._meta.model_name) for model in SUPPORTED_SOURCE_MODELS)


def get_supported_source_content_type_query_params():
    """Build query params that constrain ContentType options to supported models.

    Returns:
        dict[str, list[str]]: Query params containing sorted unique values for:
            - `app_label`
            - `model`
    """
    model_pairs = get_supported_source_model_pairs()
    return {
        "app_label": sorted({app_label for app_label, _ in model_pairs}),
        "model": sorted({model_name for _, model_name in model_pairs}),
    }
