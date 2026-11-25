"""Open the storage window without blocking the rest of the application."""
from storage_gui import open_storage


def show_storage_help(parent, scope_kit=None):
    return open_storage(parent, scope_kit=scope_kit)
