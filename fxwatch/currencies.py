"""Reference data for the currencies FX Watch supports (active ISO 4217 codes).

Codes reported by a source but missing here (crypto assets, retired or non-ISO
currencies) are ignored when the source is parsed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Currency:
    code: str
    name: str
    country: str | None  # ISO 3166 alpha-2, used for the flag; None for multinational units
    peg: str | None = None  # anchor currency if the currency is pegged or tightly managed
    parallel_market: bool = False  # official rate may differ materially from the street rate

    @property
    def flag(self) -> str:
        """Flag emoji. Windows has no flag glyphs; the app ships a flag font to fill the gap."""
        if not self.country:
            return "🌐"
        return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in self.country.upper())

    @property
    def label(self) -> str:
        return f"{self.flag} {self.code} · {self.name}"

    @property
    def notes(self) -> list[str]:
        notes = []
        if self.peg:
            notes.append(
                f"{self.code} is pegged to or tightly managed against {self.peg}, so it moves "
                f"almost exclusively with {self.peg}."
            )
        if self.parallel_market:
            notes.append(
                f"{self.code} has (or has recently had) a parallel market. Published rates are "
                "official/interbank rates and may differ materially from street rates."
            )
        return notes


_RAW: list[tuple] = [
    ("AED", "UAE dirham", "AE", "USD"),
    ("AFN", "Afghan afghani", "AF"),
    ("ALL", "Albanian lek", "AL"),
    ("AMD", "Armenian dram", "AM"),
    ("ANG", "Netherlands Antillean guilder", "CW", "USD"),
    ("AOA", "Angolan kwanza", "AO"),
    ("ARS", "Argentine peso", "AR", None, True),
    ("AUD", "Australian dollar", "AU"),
    ("AWG", "Aruban florin", "AW", "USD"),
    ("AZN", "Azerbaijani manat", "AZ"),
    ("BAM", "Bosnia-Herzegovina convertible mark", "BA", "EUR"),
    ("BBD", "Barbadian dollar", "BB", "USD"),
    ("BDT", "Bangladeshi taka", "BD"),
    ("BHD", "Bahraini dinar", "BH", "USD"),
    ("BIF", "Burundian franc", "BI"),
    ("BMD", "Bermudian dollar", "BM", "USD"),
    ("BND", "Brunei dollar", "BN", "SGD"),
    ("BOB", "Bolivian boliviano", "BO"),
    ("BRL", "Brazilian real", "BR"),
    ("BSD", "Bahamian dollar", "BS", "USD"),
    ("BTN", "Bhutanese ngultrum", "BT", "INR"),
    ("BWP", "Botswana pula", "BW"),
    ("BYN", "Belarusian ruble", "BY"),
    ("BZD", "Belize dollar", "BZ", "USD"),
    ("CAD", "Canadian dollar", "CA"),
    ("CDF", "Congolese franc", "CD"),
    ("CHF", "Swiss franc", "CH"),
    ("CLP", "Chilean peso", "CL"),
    ("CNY", "Chinese yuan", "CN"),
    ("COP", "Colombian peso", "CO"),
    ("CRC", "Costa Rican colón", "CR"),
    ("CUP", "Cuban peso", "CU", None, True),
    ("CVE", "Cape Verdean escudo", "CV", "EUR"),
    ("CZK", "Czech koruna", "CZ"),
    ("DJF", "Djiboutian franc", "DJ", "USD"),
    ("DKK", "Danish krone", "DK", "EUR"),
    ("DOP", "Dominican peso", "DO"),
    ("DZD", "Algerian dinar", "DZ"),
    ("EGP", "Egyptian pound", "EG", None, True),
    ("ERN", "Eritrean nakfa", "ER", "USD"),
    ("ETB", "Ethiopian birr", "ET", None, True),
    ("EUR", "Euro", "EU"),
    ("FJD", "Fijian dollar", "FJ"),
    ("FKP", "Falkland Islands pound", "FK", "GBP"),
    ("GBP", "Pound sterling", "GB"),
    ("GEL", "Georgian lari", "GE"),
    ("GHS", "Ghanaian cedi", "GH"),
    ("GIP", "Gibraltar pound", "GI", "GBP"),
    ("GMD", "Gambian dalasi", "GM"),
    ("GNF", "Guinean franc", "GN"),
    ("GTQ", "Guatemalan quetzal", "GT"),
    ("GYD", "Guyanese dollar", "GY"),
    ("HKD", "Hong Kong dollar", "HK", "USD"),
    ("HNL", "Honduran lempira", "HN"),
    ("HTG", "Haitian gourde", "HT"),
    ("HUF", "Hungarian forint", "HU"),
    ("IDR", "Indonesian rupiah", "ID"),
    ("ILS", "Israeli new shekel", "IL"),
    ("INR", "Indian rupee", "IN"),
    ("IQD", "Iraqi dinar", "IQ"),
    ("IRR", "Iranian rial", "IR", None, True),
    ("ISK", "Icelandic króna", "IS"),
    ("JMD", "Jamaican dollar", "JM"),
    ("JOD", "Jordanian dinar", "JO", "USD"),
    ("JPY", "Japanese yen", "JP"),
    ("KES", "Kenyan shilling", "KE"),
    ("KGS", "Kyrgyzstani som", "KG"),
    ("KHR", "Cambodian riel", "KH"),
    ("KMF", "Comorian franc", "KM", "EUR"),
    ("KRW", "South Korean won", "KR"),
    ("KWD", "Kuwaiti dinar", "KW"),
    ("KYD", "Cayman Islands dollar", "KY", "USD"),
    ("KZT", "Kazakhstani tenge", "KZ"),
    ("LAK", "Lao kip", "LA"),
    ("LBP", "Lebanese pound", "LB", None, True),
    ("LKR", "Sri Lankan rupee", "LK"),
    ("LRD", "Liberian dollar", "LR"),
    ("LSL", "Lesotho loti", "LS", "ZAR"),
    ("LYD", "Libyan dinar", "LY", None, True),
    ("MAD", "Moroccan dirham", "MA"),
    ("MDL", "Moldovan leu", "MD"),
    ("MGA", "Malagasy ariary", "MG"),
    ("MKD", "Macedonian denar", "MK", "EUR"),
    ("MMK", "Myanmar kyat", "MM", None, True),
    ("MNT", "Mongolian tögrög", "MN"),
    ("MOP", "Macanese pataca", "MO", "HKD"),
    ("MRU", "Mauritanian ouguiya", "MR"),
    ("MUR", "Mauritian rupee", "MU"),
    ("MVR", "Maldivian rufiyaa", "MV"),
    ("MWK", "Malawian kwacha", "MW", None, True),
    ("MXN", "Mexican peso", "MX"),
    ("MYR", "Malaysian ringgit", "MY"),
    ("MZN", "Mozambican metical", "MZ"),
    ("NAD", "Namibian dollar", "NA", "ZAR"),
    ("NGN", "Nigerian naira", "NG", None, True),
    ("NIO", "Nicaraguan córdoba", "NI"),
    ("NOK", "Norwegian krone", "NO"),
    ("NPR", "Nepalese rupee", "NP", "INR"),
    ("NZD", "New Zealand dollar", "NZ"),
    ("OMR", "Omani rial", "OM", "USD"),
    ("PAB", "Panamanian balboa", "PA", "USD"),
    ("PEN", "Peruvian sol", "PE"),
    ("PGK", "Papua New Guinean kina", "PG"),
    ("PHP", "Philippine peso", "PH"),
    ("PKR", "Pakistani rupee", "PK"),
    ("PLN", "Polish złoty", "PL"),
    ("PYG", "Paraguayan guaraní", "PY"),
    ("QAR", "Qatari riyal", "QA", "USD"),
    ("RON", "Romanian leu", "RO"),
    ("RSD", "Serbian dinar", "RS"),
    ("RUB", "Russian ruble", "RU"),
    ("RWF", "Rwandan franc", "RW"),
    ("SAR", "Saudi riyal", "SA", "USD"),
    ("SBD", "Solomon Islands dollar", "SB"),
    ("SCR", "Seychellois rupee", "SC"),
    ("SDG", "Sudanese pound", "SD", None, True),
    ("SEK", "Swedish krona", "SE"),
    ("SGD", "Singapore dollar", "SG"),
    ("SHP", "Saint Helena pound", "SH", "GBP"),
    ("SLE", "Sierra Leonean leone", "SL"),
    ("SOS", "Somali shilling", "SO"),
    ("SRD", "Surinamese dollar", "SR"),
    ("SSP", "South Sudanese pound", "SS", None, True),
    ("STN", "São Tomé and Príncipe dobra", "ST", "EUR"),
    ("SYP", "Syrian pound", "SY", None, True),
    ("SZL", "Eswatini lilangeni", "SZ", "ZAR"),
    ("THB", "Thai baht", "TH"),
    ("TJS", "Tajikistani somoni", "TJ"),
    ("TMT", "Turkmenistani manat", "TM", None, True),
    ("TND", "Tunisian dinar", "TN"),
    ("TOP", "Tongan paʻanga", "TO"),
    ("TRY", "Turkish lira", "TR"),
    ("TTD", "Trinidad and Tobago dollar", "TT"),
    ("TWD", "New Taiwan dollar", "TW"),
    ("TZS", "Tanzanian shilling", "TZ"),
    ("UAH", "Ukrainian hryvnia", "UA"),
    ("UGX", "Ugandan shilling", "UG"),
    ("USD", "US dollar", "US"),
    ("UYU", "Uruguayan peso", "UY"),
    ("UZS", "Uzbekistani som", "UZ"),
    ("VES", "Venezuelan bolívar", "VE", None, True),
    ("VND", "Vietnamese đồng", "VN"),
    ("VUV", "Vanuatu vatu", "VU"),
    ("WST", "Samoan tālā", "WS"),
    ("XAF", "Central African CFA franc", None, "EUR"),
    ("XCD", "East Caribbean dollar", None, "USD"),
    ("XCG", "Caribbean guilder", None, "USD"),
    ("XDR", "IMF Special Drawing Rights", None),
    ("XOF", "West African CFA franc", None, "EUR"),
    ("XPF", "CFP franc", None, "EUR"),
    ("YER", "Yemeni rial", "YE", None, True),
    ("ZAR", "South African rand", "ZA"),
    ("ZMW", "Zambian kwacha", "ZM"),
    ("ZWG", "Zimbabwe Gold", "ZW", None, True),
]


def _build(row: tuple) -> Currency:
    code, name, country, *rest = row
    peg = rest[0] if rest else None
    parallel = rest[1] if len(rest) > 1 else False
    return Currency(code, name, country, peg, parallel)


CURRENCIES: dict[str, Currency] = {c.code: c for c in map(_build, _RAW)}

#: Pairs shown on the dashboard until the visitor picks their own.
DEFAULT_PAIRS: list[tuple[str, str]] = [
    ("EUR", "ZAR"),
    ("EUR", "GHS"),
    ("ZAR", "GHS"),
    ("USD", "ZAR"),
    ("USD", "GHS"),
    ("GBP", "ZAR"),
]

#: Currencies listed first in pickers.
POPULAR: list[str] = ["EUR", "ZAR", "GHS", "USD", "GBP", "CHF", "JPY", "CNY", "CAD", "AUD", "NGN"]


def is_supported(code: str) -> bool:
    return code.upper() in CURRENCIES


def get(code: str) -> Currency:
    return CURRENCIES[code.upper()]


def ordered_codes() -> list[str]:
    """Popular currencies first, then the rest alphabetically."""
    rest = sorted(c for c in CURRENCIES if c not in POPULAR)
    return [c for c in POPULAR if c in CURRENCIES] + rest
