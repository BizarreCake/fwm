"""Build src/fwm/country_codes.csv from the IMF and BIS code lists, matched by name, with manual fixes.

    python3 scripts/make_country_codes.py <dir> src/fwm/country_codes.csv

<dir> holds the two structure files saved as JSON: pip_struct.json (the IMF PIP dataflow's
structure, for its code list CL_PIP_COUNTRY) and bis_struct.xml (the BIS WS_LBS_D_PUB
dataflow's structure, for CL_BIS_IF_REF_AREA; JSON despite its name). Run only when a
source adds countries; the result should be reviewed, since names are matched loosely.
"""
import csv, json, re, sys
L, out = sys.argv[1], sys.argv[2]
imf = {c['id']: c['name'] for c in next(cl for cl in json.load(open(f'{L}/pip_struct.json'))['data']['codelists'] if cl['id'] == 'CL_PIP_COUNTRY')['codes'] if re.fullmatch(r"[A-Z]{3}", c['id'])}
bis = {c['id']: c['name'] for c in next(cl for cl in json.load(open(f'{L}/bis_struct.xml'))['data']['codelists'] if cl['id'] == 'CL_BIS_IF_REF_AREA')['codes'] if re.fullmatch(r"[A-Z]{2}", c['id'])}
def norm(n):
    n = n.lower(); n = re.sub(r"\(.*?\)", "", n); n = re.sub(r",.*", "", n); n = re.sub(r"[^a-z ]", "", n)
    return re.sub(r"\s+", " ", n).replace("the ", "").strip()
byname = {norm(v): k for k, v in imf.items()}
pairs = {k: byname[norm(v)] for k, v in bis.items() if norm(v) in byname}
MANUAL = {"BN": "BRN", "CD": "COD", "CG": "COG", "CZ": "CZE", "HK": "HKG", "KP": "PRK", "LA": "LAO", "MO": "MAC", "RU": "RUS", "SK": "SVK",
          "SY": "SYR", "TL": "TLS", "TW": "TWN", "VN": "VNM", "PS": "PSE", "VA": "VAT", "FO": "FRO", "RE": "REU", "NR": "NRU", "VI": "VIR", "PM": "SPM"}
for iso2, iso3 in MANUAL.items():
    if iso3 in imf: pairs[iso2] = iso3
    else: print("manual code not in IMF list:", iso2, iso3)
ALIASES = {"HK": "Hong Kong", "TW": "Taiwan", "TR": "Turkey", "CW": "Curacao", "KN": "Saint Kitts and Nevis", "KR": "Korea, South;South Korea",
           "CN": "China, Mainland", "GB": "UK;Britain", "US": "USA;United States of America", "KY": "Cayman", "MO": "Macau;Macao",
           "CZ": "Czech Republic", "VN": "Vietnam", "BS": "Bahamas", "PS": "Palestinian Territory"}
# Codes for places that no longer exist or that repeat another row.
DROP = {"FX", "YD"}
pairs = {k: v for k, v in pairs.items() if k not in DROP}
pairs["YE"], pairs["PS"] = "YEM", "WBG"
NAMES = {"PS": "West Bank and Gaza"}
dupes = [v for v in set(pairs.values()) if list(pairs.values()).count(v) > 1]
print(len(pairs), "pairs; duplicate iso3:", dupes)
# spot checks
for a, b3 in (("DE", "DEU"), ("JP", "JPN"), ("CH", "CHE"), ("KR", "KOR"), ("GB", "GBR"), ("IE", "IRL"), ("NL", "NLD"), ("AT", "AUT"), ("AU", "AUS")):
    assert pairs[a] == b3, (a, pairs.get(a))
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["iso2", "iso3", "name", "imf_name", "aliases"])
    for iso2 in sorted(pairs):
        if pairs[iso2] in dupes and iso2 not in MANUAL and norm(bis[iso2]) != norm(imf[pairs[iso2]]): continue
        w.writerow([iso2, pairs[iso2], NAMES.get(iso2, bis[iso2]), imf[pairs[iso2]], ALIASES.get(iso2, "")])
