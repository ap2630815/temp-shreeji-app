"""Grain quality codes: the fixed list offered on the farmer-entry and stockyard-entry forms (best to worst).
The field stays free text - pick a code from the drop-down or type your own; the code is what is stored."""

# (code, name) in the order they are shown
QUALITY_CODES: tuple[tuple[str, str], ...] = (
    ("T.", "Top"),
    ("S.", "Super"),
    ("S.B.", "Super Bottom"),
    ("s.", "super"),
    ("s.b.", "super bottom"),
    ("Avg.", "Average"),
    ("Avg.B.", "Average Bottom"),
    ("Rej.", "Rejection"),
)

# (value stored, name shown after it) pairs for a form field's `options`; the pick list shows "T.  Top" (code, 2 spaces, name)
QUALITY_OPTIONS: tuple[tuple[str, str], ...] = QUALITY_CODES

QUALITY_HELP = (
    "Pick a code from the list (T. Top, S. Super, S.B. Super Bottom, s. super, s.b. super bottom, Avg. Average, Avg.B. Average Bottom, Rej. Rejection) or type your own",
    "યાદીમાંથી કોડ પસંદ કરો (T. ટોપ, S. સુપર, S.B. સુપર બોટમ, s. સુપર, s.b. સુપર બોટમ, Avg. એવરેજ, Avg.B. એવરેજ બોટમ, Rej. રિજેક્શન) અથવા પોતાનો લખો",
)
