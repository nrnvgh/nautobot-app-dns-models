"""Registry system for DNS transform functions."""

import logging
from functools import wraps

logger = logging.getLogger(__name__)

# Registry for DNS transform functions
_DNS_TRANSFORMS = {}


def dns_transform(func):
    """
    Decorator to register functions as available DNS record transforms.
    
    Automatically derives name, display_name, and description from the function:
    - name: function.__name__ 
    - display_name: function_name.replace("_", " ").title()
    - description: function.__doc__

    Usage:
        @dns_transform
        def interface_normalize(value):
            '''Convert interface names to lowercase alphanumeric.'''
            return value.lower().replace("/", "").replace("-", "")
            
        # Results in:
        # name: "interface_normalize"
        # display_name: "Interface Normalize" 
        # description: "Convert interface names to lowercase alphanumeric."
    """
    transform_name = func.__name__
    transform_display = transform_name.replace("_", " ").title()
    transform_desc = func.__doc__ or f"Apply {transform_display} transformation"

    # Register the transform
    _DNS_TRANSFORMS[transform_name] = {
        "function": func,
        "display_name": transform_display,
        "description": transform_desc,
        "name": transform_name,
    }

    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return wrapper


def get_transform_choices():
    """
    Get available transforms as Django model field choices.

    Returns:
        list: List of (value, display_name) tuples for model choices
    """
    choices = [("", "No Transform")]

    for name, info in _DNS_TRANSFORMS.items():
        choices.append((name, info["display_name"]))

    return choices


def get_transform_function(name):
    """
    Get a transform function by name.

    Args:
        name (str): Name of the transform function

    Returns:
        callable: The transform function, or None if not found
    """
    transform_info = _DNS_TRANSFORMS.get(name)
    return transform_info["function"] if transform_info else None


def get_transform_info(name):
    """
    Get complete transform information by name.

    Args:
        name (str): Name of the transform function

    Returns:
        dict: Transform info dict with function, display_name, description, etc.
    """
    return _DNS_TRANSFORMS.get(name)


def apply_transform(transform_name, value):
    """
    Apply a named transform to a value.

    Args:
        transform_name (str): Name of the transform to apply
        value (str): Value to transform

    Returns:
        str: Transformed value, or original value if transform not found
    """
    if not transform_name or not value:
        return value

    transform_func = get_transform_function(transform_name)
    if transform_func:
        try:
            return transform_func(value)
        except Exception as e:
            logger.warning(f"Transform {transform_name} failed on '{value}': {e}")
            return value

    return value


def list_transforms():
    """
    List all registered transforms with their metadata.

    Returns:
        dict: Dictionary mapping transform names to their info
    """
    return _DNS_TRANSFORMS.copy()
