import pytest


def pytest_collection_modifyitems(items):
    for item in items:
        if "sentihood" in item.nodeid:
            item.add_marker(pytest.mark.sentihood)
        elif "SNLI" in item.nodeid:
            item.add_marker(pytest.mark.SNLI)

        if "CPU" in item.nodeid:
            item.add_marker(pytest.mark.CPU)
        elif "GPU" in item.nodeid:
            item.add_marker(pytest.mark.GPU)


