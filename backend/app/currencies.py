"""Currency codes, shared by the evidence normalizer and the field-pair floor."""

from __future__ import annotations

#: ISO 4217 codes in circulation. Read in capitals only where a printed value
#: is parsed: several are ordinary English words in lower case ("all", "top",
#: "try"), and a printed currency code is capitalized.
ISO_CURRENCIES = frozenset("""
AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB BRL
BSD BTN BWP BYN BZD CAD CDF CHF CLP CNY COP CRC CUP CVE CZK DJF DKK DOP DZD EGP
ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF GTQ GYD HKD HNL HTG HUF IDR ILS INR
IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT LAK LBP LKR LRD LSL
LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MYR MZN NAD NGN NIO NOK NPR
NZD OMR PAB PEN PGK PHP PKR PLN PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD
SHP SLE SOS SRD SSP STN SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS UAH UGX USD
UYU UZS VES VND VUV WST XAF XCD XOF XPF YER ZAR ZMW ZWL
""".split())

#: Codes that are also English words a field name might use. A field-name
#: tokenizer works in lower case, so these are never read as currencies there.
WORD_CODES = frozenset({
    "all", "top", "try", "cup", "mop", "sos", "gel", "bob", "pen", "mad",
})
