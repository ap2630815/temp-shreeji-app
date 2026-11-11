"""UPI numbers: stored only when they differ from the mobile number ("UPI number (if different from mobile)").

A blank UPI means "the UPI is the mobile number"; effective_upi() gives the number to pay to either way."""

# UPI column -> the mobile column it is compared with (same table)
UPI_OF_MOBILE = {
    "upi_number": "mobile",
    "truck_owner_upi_number": "truck_owner_mobile",
    "driver_upi_number": "driver_mobile",
    "stockyard_upi_number": "stockyard_owner_mobile",
}


def drop_upi_same_as_mobile(clean: dict) -> dict:
    """Blank every UPI value that equals its mobile number (it is implied), in place; returns the dict."""
    for upi, mobile in UPI_OF_MOBILE.items():
        if clean.get(upi) and clean.get(upi) == clean.get(mobile):
            clean[upi] = None
    return clean


def effective_upi(upi: str | None, mobile: str | None) -> str:
    """The number to pay by UPI: the stored UPI when there is one, otherwise the mobile."""
    return upi or mobile or ""
