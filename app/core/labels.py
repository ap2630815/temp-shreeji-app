"""Bilingual labels. Every label is a (English, Gujarati) pair rendered side by side."""

LABELS: dict[str, tuple[str, str]] = {
    "app_name": ("Shreeji Grain Trading", "શ્રીજી અનાજ વેપાર"),
    "login": ("Login", "લૉગિન"),
    "logout": ("Logout", "લૉગઆઉટ"),
    "username": ("Username", "વપરાશકર્તા નામ"),
    "password": ("Password", "પાસવર્ડ"),
    "dashboard": ("Dashboard", "ડેશબોર્ડ"),
    "invalid_login": ("Invalid username or password", "અમાન્ય વપરાશકર્તા નામ અથવા પાસવર્ડ"),
    "change_password": ("Change Password", "પાસવર્ડ બદલો"),
    "current_password": ("Current password", "હાલનો પાસવર્ડ"),
    "new_password": ("New password (min 8 characters)", "નવો પાસવર્ડ (ઓછામાં ઓછા ૮ અક્ષર)"),
    "confirm_password": ("Confirm new password", "નવો પાસવર્ડ ફરી લખો"),
    "show_password": ("Show password", "પાસવર્ડ બતાવો"),
    "save": ("Save", "સાચવો"),
    "back": ("Back", "પાછા"),
    "pw_changed": ("Password changed", "પાસવર્ડ બદલાઈ ગયો"),
    "pw_wrong_current": ("Current password is wrong", "હાલનો પાસવર્ડ ખોટો છે"),
    "pw_mismatch": ("New passwords do not match", "નવા પાસવર્ડ મેળ ખાતા નથી"),
    "pw_too_short": ("New password must be at least 8 characters", "નવો પાસવર્ડ ઓછામાં ઓછા ૮ અક્ષરનો હોવો જોઈએ"),
    "pw_same": ("New password must differ from the current one", "નવો પાસવર્ડ હાલના કરતાં અલગ હોવો જોઈએ"),
    "search": ("Search", "શોધો"),
    "add": ("Add", "ઉમેરો"),
    "edit": ("Edit", "સુધારો"),
    "statement": ("Statement", "ખાતાવહી"),
    "no_records": ("No records", "કોઈ નોંધ નથી"),
    # masters
    "farmer": ("Farmer", "ખેડૂત"),
    "bag_supplier": ("Bag Supplier", "બારદાન સપ્લાયર"),
    "labour": ("Labour", "મજૂર"),
    "transport": ("Transport", "ટ્રાન્સપોર્ટ"),
    "truck": ("Truck", "ટ્રક"),
    "industry": ("Industry", "ઉદ્યોગ"),
    "broker": ("Broker", "દલાલ"),
    "grain": ("Grain", "અનાજ"),
    "village": ("Village", "ગામ"),
    "mobile": ("Mobile", "મોબાઇલ"),
    "name": ("Name", "નામ"),
}


def bilingual(key: str) -> str:
    en, gu = LABELS[key]
    return f"{en} / {gu}"
