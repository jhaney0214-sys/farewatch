"""Build data/destinations.json from the compact tables below.

Everything here is hand-authored, approximate, and meant to be edited. Prices are
in USD and reflect rough 2026 on-the-ground costs. They do not need to be exact:
they rank deals against each other, so consistent relative error is harmless
while inconsistent error is not.

Run:  python tools/build_data.py
"""
import json
import os

# VERIFIED against real market data on 2026-08-29. Hotel medians from Google
# Hotels listings; food and transport from Numbeo city pages, converted at the
# day's ECB rate and divided by the city cost multiplier to recover a country
# base. Two errors were large and pulled in OPPOSITE directions, which is the
# only reason they had not cancelled out into something noticeable:
#
#   US hotel_mid was 165, measured 101 (New York) and 108 (Atlanta) -> 105.
#   TH taxi_per_km was 0.50, measured 1.05. Transit 0.60, measured 1.00.
#
# So the model had been overstating what it costs to sleep in rich countries
# while understating what it costs to get around cheap ones. Both biases
# flattered exactly the comparison this project is built on, which is why they
# were worth measuring rather than assuming.
#
# Countries in VERIFIED_COUNTRIES below carry measured figures. Every other row
# is still hand-authored and unchecked - treat them accordingly.

# code|name|currency|meal_cheap|meal_mid_for_two|beer|transit_ticket|taxi_per_km|hotel_mid_night
COUNTRIES = """
US|United States|USD|18|104|6|2.22|1.6|105
CA|Canada|CAD|16|65|6|2.6|1.6|140
MX|Mexico|MXN|6|32|2.2|0.6|0.7|75
GT|Guatemala|GTQ|5|28|2|0.35|0.9|55
BZ|Belize|BZD|8|40|3|1.2|1.5|85
CR|Costa Rica|CRC|9|45|2.8|0.9|1.3|90
PA|Panama|PAB|8|40|2.5|0.5|1.1|85
NI|Nicaragua|NIO|4.5|24|1.7|0.35|0.7|45
HN|Honduras|HNL|4.5|24|1.7|0.35|0.7|48
SV|El Salvador|USD|5|26|1.8|0.4|0.8|50
CO|Colombia|COP|4.5|26|1.8|0.7|0.8|55
PE|Peru|PEN|4.5|26|2|0.4|0.8|50
EC|Ecuador|USD|4|25|2|0.35|0.9|48
BO|Bolivia|BOB|3.5|20|1.6|0.35|0.6|38
CL|Chile|CLP|9|42|3|0.9|1.1|80
AR|Argentina|ARS|7|34|2.5|0.4|0.7|65
BR|Brazil|BRL|7|38|2|0.9|0.9|65
UY|Uruguay|UYU|11|48|3.2|1.1|1.4|85
PY|Paraguay|PYG|5|26|1.8|0.5|0.7|48
VE|Venezuela|VES|6|30|2|0.4|0.8|50
GY|Guyana|GYD|6|30|2.2|0.6|1.0|60
DO|Dominican Republic|DOP|7|38|2.2|0.6|1.2|85
JM|Jamaica|JMD|9|45|3|1.1|1.6|110
CU|Cuba|CUP|6|30|2|0.4|0.8|50
HT|Haiti|HTG|5|26|2|0.4|0.8|55
PR|Puerto Rico|USD|13|58|4|1.5|2.0|130
BS|Bahamas|BSD|16|70|5.5|1.5|2.5|180
BB|Barbados|BBD|14|60|4.5|1.7|2.2|150
TT|Trinidad and Tobago|TTD|8|38|2.5|0.6|1.3|85
AW|Aruba|AWG|15|65|4.5|2.3|2.4|170
KY|Cayman Islands|KYD|20|85|6.5|3.0|3.0|260
SX|Sint Maarten|ANG|16|68|4.5|2.0|2.5|175
AG|Antigua and Barbuda|XCD|14|60|4.5|1.8|2.3|165
LC|Saint Lucia|XCD|13|56|4|1.6|2.2|155
GD|Grenada|XCD|12|52|3.8|1.5|2.0|140
VG|British Virgin Islands|USD|18|78|5.5|2.5|2.8|230
TC|Turks and Caicos|USD|20|85|6|2.5|3.0|280
CW|Curacao|ANG|14|58|3.5|1.8|2.2|140
GB|United Kingdom|GBP|17|75|6|3.4|2.6|135
IE|Ireland|EUR|18|75|6.5|3.0|2.2|145
FR|France|EUR|16|65|7|2.2|2.0|130
ES|Spain|EUR|14|55|3.5|1.7|1.4|105
PT|Portugal|EUR|11|50|2.8|1.7|0.6|99
IT|Italy|EUR|16|65|5.5|1.6|1.5|115
DE|Germany|EUR|15|65|4.5|3.2|2.5|110
NL|Netherlands|EUR|18|75|6|3.4|2.6|150
BE|Belgium|EUR|18|75|5.5|2.6|2.0|125
LU|Luxembourg|EUR|20|85|6|2.0|3.0|165
CH|Switzerland|CHF|31|124|8.25|4.75|3.9|157
AT|Austria|EUR|16|68|5|2.6|2.0|120
CZ|Czechia|CZK|10|45|2.2|1.3|1.2|85
PL|Poland|PLN|9|42|2.2|1.1|1.0|70
HU|Hungary|HUF|9|42|2.2|1.1|1.0|75
SK|Slovakia|EUR|10|45|2.4|1.0|1.3|70
SI|Slovenia|EUR|13|55|3.5|1.5|1.5|90
HR|Croatia|EUR|13|55|3.5|1.5|1.4|95
RS|Serbia|RSD|8|35|2.2|0.9|0.8|60
BA|Bosnia and Herzegovina|BAM|7|32|1.9|0.9|0.8|55
ME|Montenegro|EUR|11|45|2.5|1.1|1.1|75
AL|Albania|ALL|7|32|2.0|0.5|0.8|55
MK|North Macedonia|MKD|6|28|1.8|0.6|0.6|50
XK|Kosovo|EUR|6|28|1.8|0.6|0.7|50
BG|Bulgaria|BGN|9|40|2.2|1.0|0.6|60
RO|Romania|RON|9|40|2.0|0.7|0.7|65
MD|Moldova|MDL|6|28|1.5|0.3|0.5|48
GR|Greece|EUR|13|55|4.5|1.4|1.2|90
CY|Cyprus|EUR|15|60|4.0|1.7|1.4|100
MT|Malta|EUR|15|60|3.5|1.7|1.5|105
TR|Turkiye|TRY|7|32|2.5|0.7|0.7|60
DK|Denmark|DKK|20|85|7|3.5|3.5|150
SE|Sweden|SEK|13|75|6.5|3.2|3.5|130
NO|Norway|NOK|20|100|10|4.0|4.5|170
FI|Finland|EUR|15|75|7|3.2|2.5|140
IS|Iceland|ISK|22|100|9|4.0|3.5|190
EE|Estonia|EUR|12|50|3.5|1.6|0.9|85
LV|Latvia|EUR|11|48|3.0|1.5|0.9|75
LT|Lithuania|EUR|11|48|3.0|1.2|0.9|75
UA|Ukraine|UAH|6|28|1.6|0.3|0.5|45
GE|Georgia|GEL|6|28|1.6|0.3|0.6|50
AM|Armenia|AMD|6|28|1.6|0.3|0.5|48
AZ|Azerbaijan|AZN|7|30|1.8|0.3|0.6|55
MA|Morocco|MAD|5|25|3.0|0.6|0.7|55
DZ|Algeria|DZD|4|22|2.5|0.3|0.5|48
EG|Egypt|EGP|4|20|2.0|0.4|0.5|45
TN|Tunisia|TND|5|24|1.8|0.4|0.5|48
ZA|South Africa|ZAR|7|35|2.0|1.2|0.8|65
KE|Kenya|KES|5|28|2.0|0.5|0.7|60
TZ|Tanzania|TZS|5|28|2.0|0.4|0.7|60
UG|Uganda|UGX|4|22|1.5|0.3|0.6|50
RW|Rwanda|RWF|4.5|24|1.6|0.4|0.7|58
ET|Ethiopia|ETB|4|22|1.5|0.3|0.6|50
GH|Ghana|GHS|4|24|1.5|0.4|0.6|55
NG|Nigeria|NGN|4|26|1.6|0.4|0.6|60
SN|Senegal|XOF|6|30|2.5|0.6|0.8|65
CI|Ivory Coast|XOF|6|30|2.4|0.6|0.8|65
CM|Cameroon|XAF|5|26|2.0|0.5|0.7|58
MU|Mauritius|MUR|7|35|2.5|0.6|0.9|95
SC|Seychelles|SCR|14|60|4.5|1.0|2.0|180
NA|Namibia|NAD|7|34|2.0|1.0|0.8|70
BW|Botswana|BWP|8|35|2.2|1.0|0.9|85
ZW|Zimbabwe|ZWL|6|30|2.0|0.6|0.8|65
ZM|Zambia|ZMW|5|28|1.8|0.5|0.7|60
MZ|Mozambique|MZN|5|28|1.8|0.5|0.7|62
MG|Madagascar|MGA|3.5|20|1.4|0.3|0.5|45
AE|United Arab Emirates|AED|9|50|9|1.4|0.8|110
QA|Qatar|QAR|8|45|10|1.0|0.8|105
SA|Saudi Arabia|SAR|7|40|0|0.8|0.7|85
BH|Bahrain|BHD|8|42|7|0.8|0.7|90
KW|Kuwait|KWD|8|42|0|0.8|0.6|85
OM|Oman|OMR|7|38|8|0.8|0.7|80
IL|Israel|ILS|16|70|7|1.8|1.5|140
JO|Jordan|JOD|6|32|5|0.6|0.6|65
LB|Lebanon|LBP|8|38|3|0.6|0.8|75
IN|India|INR|3|14|2.5|0.3|0.3|35
LK|Sri Lanka|LKR|3|16|2.0|0.2|0.3|35
NP|Nepal|NPR|3|15|1.8|0.2|0.4|30
PK|Pakistan|PKR|3|14|0|0.2|0.3|35
BD|Bangladesh|BDT|2.5|13|0|0.2|0.3|35
BT|Bhutan|BTN|5|24|2.5|0.4|0.5|60
MV|Maldives|MVR|10|55|7|1.0|1.5|150
TH|Thailand|THB|2.65|31.6|2.37|1.0|1.05|43.5
VN|Vietnam|VND|2.5|18|0.9|0.4|0.6|35
KH|Cambodia|KHR|3.5|20|1.0|0.5|0.6|35
LA|Laos|LAK|3|18|1.2|0.5|0.6|35
MM|Myanmar|MMK|3|18|1.5|0.3|0.5|35
MY|Malaysia|MYR|3.5|22|3.0|0.7|0.5|45
SG|Singapore|SGD|8|45|8|1.5|1.0|140
ID|Indonesia|IDR|3|22|2.5|0.3|0.4|40
PH|Philippines|PHP|4|22|1.5|0.3|0.5|45
BN|Brunei|BND|5|28|0|0.7|0.6|70
CN|China|CNY|4|32|1.0|0.6|0.5|55
HK|Hong Kong|HKD|7|45|6|1.0|0.9|130
MO|Macau|MOP|7|45|5|0.8|0.8|120
TW|Taiwan|TWD|5|30|2.5|0.8|0.9|70
JP|Japan|JPY|6.25|36.5|3.15|1.05|2.6|68
KR|South Korea|KRW|7|38|3.0|1.2|1.2|75
MN|Mongolia|MNT|4|22|1.5|0.3|0.5|45
KG|Kyrgyzstan|KGS|4|20|1.2|0.2|0.4|40
KZ|Kazakhstan|KZT|5|24|1.5|0.2|0.4|50
UZ|Uzbekistan|UZS|4|20|1.4|0.2|0.4|42
TJ|Tajikistan|TJS|3.5|18|1.2|0.2|0.4|38
AU|Australia|AUD|16|70|6.5|3.0|1.9|140
NZ|New Zealand|NZD|14|65|6|2.5|1.8|120
FJ|Fiji|FJD|8|38|3.0|0.8|1.0|110
PF|French Polynesia|XPF|18|75|6.5|2.0|2.5|200
NC|New Caledonia|XPF|16|70|6|1.8|2.2|175
VU|Vanuatu|VUV|9|40|3.0|1.0|1.2|110
WS|Samoa|WST|7|34|3.0|0.8|1.0|95
PG|Papua New Guinea|PGK|8|38|3.5|0.9|1.3|120
GU|Guam|USD|13|58|4.5|1.5|2.0|150
"""

# city|country|cost_multiplier|iata_codes|lat|lon
CITIES = """
New York|US|1.35|JFK,LGA,EWR|40.71|-74.01
Los Angeles|US|1.20|LAX|34.05|-118.24
San Francisco|US|1.35|SFO,OAK,SJC|37.77|-122.42
Chicago|US|1.05|ORD,MDW|41.88|-87.63
Miami|US|1.15|MIA|25.76|-80.19
Boston|US|1.20|BOS|42.36|-71.06
Washington|US|1.15|DCA,IAD,BWI|38.91|-77.04
Seattle|US|1.20|SEA|47.61|-122.33
Portland|US|1.05|PDX|45.52|-122.68
Denver|US|1.05|DEN|39.74|-104.99
Dallas|US|0.95|DFW,DAL|32.78|-96.80
Houston|US|0.95|IAH,HOU|29.76|-95.37
Atlanta|US|0.95|ATL|33.75|-84.39
Phoenix|US|0.95|PHX|33.45|-112.07
Las Vegas|US|1.00|LAS|36.17|-115.14
Orlando|US|1.00|MCO,SFB|28.54|-81.38
Tampa|US|0.95|TPA|27.95|-82.46
Philadelphia|US|1.00|PHL|39.95|-75.17
Detroit|US|0.90|DTW|42.33|-83.05
Minneapolis|US|0.95|MSP|44.98|-93.27
Kansas City|US|0.85|MCI|39.10|-94.58
St. Louis|US|0.85|STL|38.63|-90.20
Nashville|US|0.95|BNA|36.16|-86.78
Huntsville|US|0.88|HSV|34.73|-86.59
# Keyed "Birmingham AL" because the UK Birmingham already owns the bare name.
# It still resolves from the BHM airport code, which is how a home airport is
# looked up; it just will not match the bare word in a headline, and a deal
# blog writing "Birmingham" almost always means the English one anyway.
Birmingham AL|US|0.85|BHM|33.52|-86.80
Charlotte|US|0.90|CLT|35.23|-80.84
Cleveland|US|0.85|CLE|41.50|-81.69
Columbus|US|0.85|CMH|39.96|-82.99
Pittsburgh|US|0.85|PIT|40.44|-79.996
Cincinnati|US|0.85|CVG|39.10|-84.51
Indianapolis|US|0.85|IND|39.77|-86.16
Milwaukee|US|0.88|MKE|43.04|-87.91
Austin|US|1.00|AUS|30.27|-97.74
San Antonio|US|0.88|SAT|29.42|-98.49
San Diego|US|1.15|SAN|32.72|-117.16
Sacramento|US|1.05|SMF|38.58|-121.49
Salt Lake City|US|0.90|SLC|40.76|-111.89
New Orleans|US|0.95|MSY|29.95|-90.07
Raleigh|US|0.92|RDU|35.78|-78.64
Baltimore|US|1.00|BWI|39.29|-76.61
Buffalo|US|0.85|BUF|42.89|-78.88
Hartford|US|1.00|BDL|41.76|-72.67
Providence|US|1.05|PVD|41.82|-71.41
Richmond|US|0.90|RIC|37.54|-77.44
Jacksonville|US|0.90|JAX|30.33|-81.66
Hilton Head|US|1.05|HHH|32.22|-80.75
Asheville|US|0.95|AVL|35.60|-82.55
Myrtle Beach|US|0.90|MYR|33.69|-78.89
Savannah|US|0.95|SAV|32.08|-81.09
Fort Myers|US|0.95|RSW|26.64|-81.87
Fort Lauderdale|US|1.05|FLL|26.12|-80.14
Gulf Shores|US|0.92|GUF|30.25|-87.70
Charleston|US|0.98|CHS|32.78|-79.93
Norfolk|US|0.92|ORF|36.85|-76.29
Provo|US|0.90|PVU|40.23|-111.66
Akron|US|0.82|CAK|41.08|-81.52
Vero Beach|US|1.00|VRB|27.64|-80.40
Honolulu|US|1.30|HNL|21.31|-157.86
Kona|US|1.30|KOA|19.64|-155.99
Maui|US|1.30|OGG|20.89|-156.47
Anchorage|US|1.10|ANC|61.22|-149.90
Bangor|US|0.85|BGR|44.80|-68.77
Boise|US|0.90|BOI|43.62|-116.20
Albuquerque|US|0.85|ABQ|35.08|-106.65
Tucson|US|0.88|TUS|32.22|-110.97
Reno|US|0.95|RNO|39.53|-119.81
Spokane|US|0.90|GEG|47.66|-117.43
Omaha|US|0.85|OMA|41.26|-95.93
Memphis|US|0.85|MEM|35.15|-90.05
Louisville|US|0.85|SDF|38.25|-85.76
Oklahoma City|US|0.82|OKC|35.47|-97.52
Tulsa|US|0.82|TUL|36.15|-95.99
Des Moines|US|0.85|DSM|41.59|-93.62
Toronto|CA|1.15|YYZ,YTZ|43.65|-79.38
Vancouver|CA|1.20|YVR|49.28|-123.12
Montreal|CA|1.00|YUL|45.50|-73.57
Calgary|CA|1.05|YYC|51.05|-114.07
Ottawa|CA|1.00|YOW|45.42|-75.70
Edmonton|CA|0.95|YEG|53.55|-113.49
Halifax|CA|0.95|YHZ|44.65|-63.58
Mexico City|MX|1.10|MEX|19.43|-99.13
Cancun|MX|1.20|CUN|21.16|-86.85
Guadalajara|MX|0.95|GDL|20.67|-103.35
Monterrey|MX|1.00|MTY|25.69|-100.32
Puerto Vallarta|MX|1.10|PVR|20.65|-105.22
Los Cabos|MX|1.30|SJD|22.89|-109.91
Tulum|MX|1.25|TQO|20.21|-87.46
Oaxaca|MX|0.90|OAX|17.07|-96.72
Merida|MX|0.90|MID|20.97|-89.62
Guatemala City|GT|1.00|GUA|14.63|-90.51
San Jose|CR|1.00|SJO|9.93|-84.08
Liberia|CR|1.05|LIR|10.63|-85.44
Panama City|PA|1.05|PTY|8.98|-79.52
Belize City|BZ|1.00|BZE|17.50|-88.20
Bogota|CO|1.05|BOG|4.71|-74.07
Medellin|CO|1.00|MDE|6.24|-75.58
Cartagena|CO|1.10|CTG|10.39|-75.51
Lima|PE|1.05|LIM|-12.05|-77.04
Cusco|PE|1.00|CUZ|-13.53|-71.97
Quito|EC|1.00|UIO|-0.18|-78.47
Guayaquil|EC|0.95|GYE|-2.17|-79.92
La Paz|BO|1.00|LPB|-16.50|-68.15
Santiago|CL|1.10|SCL|-33.45|-70.67
Buenos Aires|AR|1.10|EZE,AEP|-34.60|-58.38
Sao Paulo|BR|1.15|GRU,CGH|-23.55|-46.63
Rio de Janeiro|BR|1.10|GIG,SDU|-22.91|-43.17
Brasilia|BR|1.00|BSB|-15.79|-47.88
Salvador|BR|0.95|SSA|-12.97|-38.50
Montevideo|UY|1.00|MVD|-34.90|-56.16
Punta Cana|DO|1.10|PUJ|18.58|-68.40
Santo Domingo|DO|0.95|SDQ|18.49|-69.93
Montego Bay|JM|1.10|MBJ|18.47|-77.92
Kingston|JM|1.00|KIN|17.97|-76.79
Havana|CU|1.05|HAV|23.11|-82.37
San Juan|PR|1.00|SJU|18.47|-66.11
Nassau|BS|1.05|NAS|25.05|-77.35
Bridgetown|BB|1.00|BGI|13.11|-59.61
Port of Spain|TT|1.00|POS|10.65|-61.51
Oranjestad|AW|1.00|AUA|12.52|-70.04
George Town|KY|1.00|GCM|19.29|-81.38
St. Maarten|SX|1.00|SXM|18.03|-63.05
Antigua|AG|1.00|ANU|17.12|-61.85
Saint Lucia|LC|1.00|UVF|13.91|-60.98
Grenada|GD|1.00|GND|12.06|-61.75
Providenciales|TC|1.00|PLS|21.77|-72.27
Curacao|CW|1.00|CUR|12.11|-68.93
London|GB|1.30|LHR,LGW,STN,LTN,LCY|51.51|-0.13
Manchester|GB|0.95|MAN|53.48|-2.24
Edinburgh|GB|1.05|EDI|55.95|-3.19
Glasgow|GB|0.95|GLA|55.86|-4.25
Birmingham|GB|0.92|BHX|52.49|-1.89
Bristol|GB|1.00|BRS|51.45|-2.59
Dublin|IE|1.15|DUB|53.35|-6.26
Paris|FR|1.25|CDG,ORY,BVA|48.86|2.35
Nice|FR|1.15|NCE|43.70|7.27
Lyon|FR|1.00|LYS|45.76|4.84
Marseille|FR|1.00|MRS|43.30|5.37
Bordeaux|FR|1.00|BOD|44.84|-0.58
Toulouse|FR|0.98|TLS|43.60|1.44
Madrid|ES|1.05|MAD|40.42|-3.70
Barcelona|ES|1.15|BCN|41.39|2.17
Malaga|ES|1.00|AGP|36.72|-4.42
Seville|ES|0.95|SVQ|37.39|-5.98
Valencia|ES|1.00|VLC|39.47|-0.38
Palma|ES|1.10|PMI|39.57|2.65
Ibiza|ES|1.30|IBZ|38.91|1.43
Tenerife|ES|1.00|TFS,TFN|28.29|-16.63
Gran Canaria|ES|1.00|LPA|28.10|-15.42
Lisbon|PT|1.10|LIS|38.72|-9.14
Porto|PT|1.00|OPO|41.15|-8.61
Faro|PT|1.00|FAO|37.02|-7.93
Madeira|PT|1.00|FNC|32.65|-16.91
Azores|PT|0.95|PDL|37.74|-25.68
Rome|IT|1.15|FCO,CIA|41.90|12.50
Milan|IT|1.20|MXP,LIN,BGY|45.46|9.19
Venice|IT|1.20|VCE|45.44|12.32
Florence|IT|1.15|FLR|43.77|11.26
Naples|IT|0.95|NAP|40.85|14.27
Palermo|IT|0.90|PMO|38.12|13.36
Catania|IT|0.90|CTA|37.50|15.09
Sicily|IT|0.92|CTA,PMO|37.60|14.02
Bologna|IT|1.05|BLQ|44.49|11.34
Turin|IT|1.00|TRN|45.07|7.69
Berlin|DE|1.05|BER|52.52|13.40
Munich|DE|1.20|MUC|48.14|11.58
Frankfurt|DE|1.15|FRA|50.11|8.68
Hamburg|DE|1.10|HAM|53.55|9.99
Dusseldorf|DE|1.10|DUS|51.23|6.78
Cologne|DE|1.05|CGN|50.94|6.96
Stuttgart|DE|1.10|STR|48.78|9.18
Amsterdam|NL|1.20|AMS|52.37|4.90
Rotterdam|NL|1.05|RTM|51.92|4.48
Brussels|BE|1.10|BRU,CRL|50.85|4.35
Luxembourg|LU|1.10|LUX|49.61|6.13
Zurich|CH|1.20|ZRH|47.38|8.54
Geneva|CH|1.20|GVA|46.20|6.14
Basel|CH|1.10|BSL|47.56|7.59
Vienna|AT|1.10|VIE|48.21|16.37
Salzburg|AT|1.10|SZG|47.81|13.06
Innsbruck|AT|1.05|INN|47.27|11.39
Prague|CZ|1.15|PRG|50.08|14.44
Warsaw|PL|1.10|WAW,WMI|52.23|21.01
Krakow|PL|1.05|KRK|50.06|19.94
Gdansk|PL|1.00|GDN|54.35|18.65
Budapest|HU|1.10|BUD|47.50|19.04
Bratislava|SK|1.05|BTS|48.15|17.11
Ljubljana|SI|1.05|LJU|46.06|14.51
Zagreb|HR|1.00|ZAG|45.81|15.98
Split|HR|1.15|SPU|43.51|16.44
Dubrovnik|HR|1.25|DBV|42.65|18.09
Belgrade|RS|1.05|BEG|44.79|20.45
Sarajevo|BA|1.00|SJJ|43.86|18.41
Podgorica|ME|1.00|TGD|42.44|19.26
Tirana|AL|1.00|TIA|41.33|19.82
Skopje|MK|1.00|SKP|41.998|21.43
Sofia|BG|1.05|SOF|42.70|23.32
Bucharest|RO|1.10|OTP|44.43|26.10
Athens|GR|1.10|ATH|37.98|23.73
Thessaloniki|GR|1.00|SKG|40.64|22.94
Santorini|GR|1.35|JTR|36.39|25.46
Mykonos|GR|1.40|JMK|37.45|25.33
Crete|GR|1.00|HER,CHQ|35.34|25.13
Rhodes|GR|1.05|RHO|36.44|28.22
Corfu|GR|1.05|CFU|39.62|19.92
Kefalonia|GR|1.00|EFL|38.18|20.49
Larnaca|CY|1.00|LCA|34.92|33.62
Malta|MT|1.00|MLA|35.90|14.51
Istanbul|TR|1.15|IST,SAW|41.01|28.98
Antalya|TR|1.00|AYT|36.90|30.70
Izmir|TR|0.95|ADB|38.42|27.14
Cappadocia|TR|0.95|NAV|38.62|34.71
Copenhagen|DK|1.15|CPH|55.68|12.57
Stockholm|SE|1.15|ARN,BMA|59.33|18.07
Gothenburg|SE|1.00|GOT|57.71|11.97
Oslo|NO|1.15|OSL|59.91|10.75
Bergen|NO|1.05|BGO|60.39|5.32
Tromso|NO|1.05|TOS|69.65|18.96
Trondheim|NO|1.00|TRD|63.43|10.40
Helsinki|FI|1.10|HEL|60.17|24.94
Reykjavik|IS|1.10|KEF|64.15|-21.94
Tallinn|EE|1.05|TLL|59.44|24.75
Riga|LV|1.05|RIX|56.95|24.11
Vilnius|LT|1.05|VNO|54.69|25.28
Kyiv|UA|1.10|IEV|50.45|30.52
Tbilisi|GE|1.10|TBS|41.72|44.79
Yerevan|AM|1.05|EVN|40.18|44.51
Baku|AZ|1.10|GYD|40.41|49.87
Marrakech|MA|1.10|RAK|31.63|-8.01
Casablanca|MA|1.05|CMN|33.57|-7.59
Fes|MA|0.95|FEZ|34.03|-5.00
Tangier|MA|1.00|TNG|35.76|-5.83
Cairo|EG|1.05|CAI|30.04|31.24
Hurghada|EG|1.00|HRG|27.26|33.81
Sharm El Sheikh|EG|1.00|SSH|27.92|34.33
Tunis|TN|1.00|TUN|36.81|10.18
Cape Town|ZA|1.15|CPT|-33.92|18.42
Johannesburg|ZA|1.05|JNB|-26.20|28.05
Durban|ZA|0.95|DUR|-29.86|31.02
Nairobi|KE|1.10|NBO|-1.29|36.82
Mombasa|KE|1.00|MBA|-4.04|39.67
Zanzibar|TZ|1.10|ZNZ|-6.16|39.20
Dar es Salaam|TZ|1.00|DAR|-6.79|39.21
Kilimanjaro|TZ|1.05|JRO|-3.43|37.07
Kampala|UG|1.00|EBB|0.35|32.58
Kigali|RW|1.05|KGL|-1.94|30.06
Addis Ababa|ET|1.00|ADD|9.03|38.74
Accra|GH|1.05|ACC|5.60|-0.19
Lagos|NG|1.10|LOS|6.52|3.38
Dakar|SN|1.05|DSS|14.72|-17.47
Abidjan|CI|1.05|ABJ|5.36|-4.01
Mauritius|MU|1.00|MRU|-20.35|57.55
Seychelles|SC|1.00|SEZ|-4.62|55.45
Windhoek|NA|1.00|WDH|-22.56|17.08
Victoria Falls|ZW|1.10|VFA|-17.93|25.83
Dubai|AE|1.15|DXB|25.20|55.27
Abu Dhabi|AE|1.05|AUH|24.45|54.38
Doha|QA|1.05|DOH|25.29|51.53
Riyadh|SA|1.00|RUH|24.71|46.68
Jeddah|SA|1.00|JED|21.49|39.19
Muscat|OM|1.00|MCT|23.59|58.41
Manama|BH|1.00|BAH|26.23|50.59
Kuwait City|KW|1.00|KWI|29.38|47.99
Tel Aviv|IL|1.20|TLV|32.09|34.78
Jerusalem|IL|1.10|TLV|31.77|35.21
Amman|JO|1.05|AMM|31.95|35.93
Beirut|LB|1.10|BEY|33.89|35.50
Delhi|IN|1.10|DEL|28.61|77.21
Mumbai|IN|1.25|BOM|19.08|72.88
Bangalore|IN|1.15|BLR|12.97|77.59
Chennai|IN|1.00|MAA|13.08|80.27
Kolkata|IN|0.95|CCU|22.57|88.36
Goa|IN|1.05|GOI|15.30|74.12
Hyderabad|IN|1.00|HYD|17.39|78.49
Kochi|IN|0.95|COK|9.93|76.27
Jaipur|IN|0.95|JAI|26.91|75.79
Colombo|LK|1.05|CMB|6.93|79.86
Kathmandu|NP|1.00|KTM|27.72|85.32
Male|MV|1.00|MLE|4.18|73.51
Bangkok|TH|1.15|BKK,DMK|13.76|100.50
Phuket|TH|1.20|HKT|7.88|98.39
Chiang Mai|TH|0.90|CNX|18.79|98.99
Krabi|TH|1.05|KBV|8.09|98.91
Koh Samui|TH|1.25|USM|9.51|100.01
Hanoi|VN|1.00|HAN|21.03|105.85
Ho Chi Minh City|VN|1.05|SGN|10.82|106.63
Da Nang|VN|0.95|DAD|16.05|108.20
Phu Quoc|VN|1.05|PQC|10.23|103.96
Phnom Penh|KH|1.05|PNH|11.56|104.92
Siem Reap|KH|1.00|REP|13.36|103.86
Vientiane|LA|1.00|VTE|17.97|102.60
Yangon|MM|1.00|RGN|16.87|96.20
Kuala Lumpur|MY|1.10|KUL|3.14|101.69
Penang|MY|0.95|PEN|5.41|100.33
Langkawi|MY|1.00|LGK|6.35|99.80
Kota Kinabalu|MY|0.95|BKI|5.98|116.07
Singapore|SG|1.00|SIN|1.35|103.82
Bali|ID|1.15|DPS|-8.65|115.22
Jakarta|ID|1.05|CGK|-6.21|106.85
Lombok|ID|1.00|LOP|-8.65|116.32
Yogyakarta|ID|0.90|JOG|-7.80|110.36
Manila|PH|1.10|MNL|14.60|120.98
Cebu|PH|1.00|CEB|10.32|123.89
Palawan|PH|1.05|PPS|9.74|118.74
Boracay|PH|1.15|MPH|11.97|121.92
Beijing|CN|1.15|PEK,PKX|39.90|116.41
Shanghai|CN|1.25|PVG,SHA|31.23|121.47
Guangzhou|CN|1.10|CAN|23.13|113.26
Shenzhen|CN|1.20|SZX|22.54|114.06
Chengdu|CN|1.00|CTU|30.57|104.07
Xian|CN|0.95|XIY|34.34|108.94
Hainan|CN|1.05|HAK,SYX|20.04|110.20
Hong Kong|HK|1.00|HKG|22.32|114.17
Macau|MO|1.00|MFM|22.20|113.55
Taipei|TW|1.10|TPE,TSA|25.03|121.57
Kaohsiung|TW|0.95|KHH|22.63|120.30
Tokyo|JP|1.20|NRT,HND|35.68|139.65
Osaka|JP|1.10|KIX,ITM|34.69|135.50
Kyoto|JP|1.15|UKY|35.01|135.77
Sapporo|JP|1.00|CTS|43.06|141.35
Fukuoka|JP|1.00|FUK|33.59|130.40
Okinawa|JP|1.05|OKA|26.21|127.68
Nagoya|JP|1.05|NGO|35.18|136.91
Seoul|KR|1.15|ICN,GMP|37.57|126.98
Busan|KR|1.00|PUS|35.18|129.08
Jeju|KR|1.00|CJU|33.51|126.52
Ulaanbaatar|MN|1.00|ULN|47.89|106.91
Bishkek|KG|1.00|FRU|42.87|74.59
Almaty|KZ|1.05|ALA|43.24|76.89
Astana|KZ|1.05|NQZ|51.17|71.43
Tashkent|UZ|1.00|TAS|41.30|69.24
Samarkand|UZ|0.95|SKD|39.65|66.96
Sydney|AU|1.20|SYD|-33.87|151.21
Melbourne|AU|1.15|MEL|-37.81|144.96
Brisbane|AU|1.05|BNE|-27.47|153.03
Perth|AU|1.10|PER|-31.95|115.86
Adelaide|AU|1.00|ADL|-34.93|138.60
Cairns|AU|1.00|CNS|-16.92|145.77
Gold Coast|AU|1.05|OOL|-28.02|153.40
Auckland|NZ|1.15|AKL|-36.85|174.76
Wellington|NZ|1.10|WLG|-41.29|174.78
Christchurch|NZ|1.05|CHC|-43.53|172.64
Queenstown|NZ|1.25|ZQN|-45.03|168.66
Nadi|FJ|1.00|NAN|-17.80|177.42
Papeete|PF|1.00|PPT|-17.54|-149.57
Bora Bora|PF|1.35|BOB|-16.50|-151.74
Noumea|NC|1.00|NOU|-22.28|166.46
Port Vila|VU|1.00|VLI|-17.73|168.32
Apia|WS|1.00|APW|-13.83|-171.77
Port Moresby|PG|1.00|POM|-9.44|147.18
Guam|GU|1.00|GUM|13.44|144.79
"""

# Alternate names that show up in feed headlines, mapped to a canonical city key.
# Country names resolve to that country's most-flown-to city, which is the right
# behaviour for a headline like "cheap flights to Vietnam".
ALIASES = {
    "nyc": "new york", "new york city": "new york", "newark": "new york",
    "washington dc": "washington", "washington d.c.": "washington",
    "la": "los angeles", "sf": "san francisco", "bay area": "san francisco",
    "vegas": "las vegas",
    "st louis": "st. louis", "saint louis": "st. louis",
    "ft lauderdale": "fort lauderdale", "fll": "fort lauderdale",
    "sint maarten": "st. maarten", "st maarten": "st. maarten",
    "saint martin": "st. maarten",
    "st lucia": "saint lucia", "st. lucia": "saint lucia",
    "turks and caicos": "providenciales",
    "cabo": "los cabos", "cabo san lucas": "los cabos",
    "puerto rico": "san juan", "riviera maya": "cancun",
    "playa del carmen": "cancun", "cozumel": "cancun",
    "the bahamas": "nassau", "bahamas": "nassau", "aruba": "oranjestad",
    "barbados": "bridgetown", "jamaica": "montego bay",
    "cayman islands": "george town", "trinidad": "port of spain",
    "cuba": "havana", "dominican republic": "punta cana",
    "costa rica": "san jose", "panama": "panama city", "belize": "belize city",
    "guatemala": "guatemala city", "colombia": "bogota", "peru": "lima",
    "ecuador": "quito", "bolivia": "la paz", "chile": "santiago",
    "argentina": "buenos aires", "brazil": "sao paulo", "uruguay": "montevideo",
    "rio": "rio de janeiro",
    "england": "london", "uk": "london", "united kingdom": "london",
    "scotland": "edinburgh", "ireland": "dublin", "france": "paris",
    "spain": "madrid", "portugal": "lisbon", "italy": "rome",
    "germany": "berlin", "netherlands": "amsterdam", "holland": "amsterdam",
    "belgium": "brussels", "switzerland": "zurich", "austria": "vienna",
    "czech republic": "prague", "czechia": "prague", "poland": "warsaw",
    "hungary": "budapest", "slovenia": "ljubljana", "croatia": "zagreb",
    "serbia": "belgrade", "montenegro": "podgorica", "albania": "tirana",
    "bulgaria": "sofia", "romania": "bucharest", "greece": "athens",
    "cyprus": "larnaca", "turkey": "istanbul", "turkiye": "istanbul",
    "denmark": "copenhagen", "sweden": "stockholm", "norway": "oslo",
    "finland": "helsinki", "iceland": "reykjavik", "estonia": "tallinn",
    "latvia": "riga", "lithuania": "vilnius", "ukraine": "kyiv", "kiev": "kyiv",
    "armenia": "yerevan", "azerbaijan": "baku",
    "morocco": "marrakech", "egypt": "cairo", "tunisia": "tunis",
    "south africa": "cape town", "kenya": "nairobi", "tanzania": "zanzibar",
    "uganda": "kampala", "rwanda": "kigali", "ethiopia": "addis ababa",
    "ghana": "accra", "nigeria": "lagos", "senegal": "dakar",
    "namibia": "windhoek", "uae": "dubai", "united arab emirates": "dubai",
    "qatar": "doha", "saudi arabia": "riyadh", "oman": "muscat",
    "bahrain": "manama", "kuwait": "kuwait city", "israel": "tel aviv",
    "jordan": "amman", "lebanon": "beirut",
    "india": "delhi", "new delhi": "delhi", "bengaluru": "bangalore",
    "bombay": "mumbai", "sri lanka": "colombo", "nepal": "kathmandu",
    "maldives": "male",
    "thailand": "bangkok", "vietnam": "hanoi", "saigon": "ho chi minh city",
    "cambodia": "phnom penh", "laos": "vientiane", "myanmar": "yangon",
    "burma": "yangon", "malaysia": "kuala lumpur", "kl": "kuala lumpur",
    "indonesia": "bali", "philippines": "manila", "china": "beijing",
    "taiwan": "taipei", "japan": "tokyo", "south korea": "seoul",
    "korea": "seoul", "mongolia": "ulaanbaatar", "kyrgyzstan": "bishkek",
    "kazakhstan": "almaty", "uzbekistan": "tashkent",
    "australia": "sydney", "new zealand": "auckland", "fiji": "nadi",
    "french polynesia": "papeete", "tahiti": "papeete",
    "new caledonia": "noumea", "vanuatu": "port vila", "samoa": "apia",
    "papua new guinea": "port moresby",
    "hawaii": "honolulu", "big island": "kona", "alaska": "anchorage",
    "canary islands": "tenerife", "fuerteventura": "gran canaria",
    "lanzarote": "gran canaria",
    "balearics": "palma", "mallorca": "palma",
    # US regions and resort areas that show up in headlines without a city.
    "dc": "washington", "scottsdale": "phoenix", "lake tahoe": "reno",
    "clearwater": "tampa", "st. petersburg": "tampa", "sarasota": "tampa",
    "catskills": "new york", "hudson valley": "new york",
    "poconos": "philadelphia", "jersey shore": "philadelphia",
    "maine": "bangor", "west virginia": "pittsburgh",
    "outer banks": "norfolk", "hilton head island": "hilton head",
    "napa": "sacramento", "sonoma": "sacramento", "palm springs": "los angeles",
    # Cruise and tour copy names a region, never a city. Mapping each to a
    # representative port gives the cost model a defensible basis - a
    # Mediterranean sailing really does price like Italy - and it is far better
    # than dropping the deal, which is what happened before.
    "mediterranean": "rome", "caribbean": "nassau", "british isles": "london",
    "baltic": "copenhagen", "adriatic": "dubrovnik", "aegean": "athens",
    "scandinavia": "copenhagen", "southeast asia": "bangkok",
    "galapagos": "quito", "amazon": "lima", "patagonia": "santiago",
    "tuscany": "florence", "provence": "marseille", "andalusia": "seville",
    "bavaria": "munich", "algarve": "faro", "dalmatia": "split",
    "majorca": "palma", "menorca": "palma",
    "nova scotia": "halifax", "quebec": "montreal", "quebec city": "montreal",
    "canada": "toronto", "mexico": "mexico city", "yucatan": "merida",
}


# Measured rather than guessed. See the note above the COUNTRIES table.
VERIFIED_COUNTRIES = {
    "US": "2026-08-29, New York + Atlanta hotels, New York Numbeo",
    "JP": "2026-08-29, Tokyo hotels + Numbeo",
    "TH": "2026-08-29, Bangkok hotels + Numbeo",
    "CH": "2026-08-29, Zurich hotels + Numbeo",
    "PT": "2026-08-29, Lisbon hotels (lodging only)",
}


def parse_table(raw, fields):
    rows = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("|")
        if len(parts) != len(fields):
            raise ValueError("bad row (%d fields, want %d): %s"
                             % (len(parts), len(fields), line))
        rows.append(dict(zip(fields, parts)))
    return rows


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    countries = {}
    for r in parse_table(COUNTRIES, [
        "code", "name", "currency", "meal_cheap", "meal_mid_two", "beer",
        "transit", "taxi_km", "hotel_mid",
    ]):
        meal_cheap = float(r["meal_cheap"])
        meal_mid_two = float(r["meal_mid_two"])
        beer = float(r["beer"])
        transit = float(r["transit"])
        taxi_km = float(r["taxi_km"])
        hotel_mid = float(r["hotel_mid"])
        countries[r["code"]] = {
            "name": r["name"],
            "currency": r["currency"],
            "meal_cheap": meal_cheap,
            "meal_mid_two": meal_mid_two,
            "beer": beer,
            "transit": transit,
            "taxi_km": taxi_km,
            "hotel_mid": hotel_mid,
            # Daily on-the-ground spend EXCLUDING lodging. Lodging is kept
            # separate because hotel, package and cruise deals already include it.
            "ground_daily": {
                "budget": round(meal_cheap * 2 + beer + transit * 3 + 5, 2),
                "mid": round(meal_cheap + meal_mid_two / 2 + beer * 2
                             + transit * 2 + taxi_km * 8 + 15, 2),
                "luxury": round(meal_mid_two + beer * 3 + taxi_km * 20 + 60, 2),
            },
            "verified": VERIFIED_COUNTRIES.get(r["code"]),
            "lodging": {
                "budget": round(hotel_mid * 0.40, 2),
                "mid": hotel_mid,
                "luxury": round(hotel_mid * 2.6, 2),
            },
        }

    cities = {}
    iata = {}
    for r in parse_table(CITIES, ["city", "country", "mult", "iata", "lat", "lon"]):
        key = r["city"].strip().lower()
        if r["country"] not in countries:
            raise ValueError("city %s references unknown country %s"
                             % (key, r["country"]))
        if key in cities:
            raise ValueError("duplicate city %s" % key)
        codes = [c.strip().upper() for c in r["iata"].split(",") if c.strip()]
        cities[key] = {
            "name": r["city"].strip(),
            "country": r["country"],
            "mult": float(r["mult"]),
            "iata": codes,
            "lat": float(r["lat"]),
            "lon": float(r["lon"]),
        }
        for c in codes:
            iata.setdefault(c, key)

    for alias, target in ALIASES.items():
        if target not in cities:
            raise ValueError("alias %r points at unknown city %r" % (alias, target))
        if alias in cities:
            raise ValueError("alias %r collides with a real city" % alias)

    out = {
        "version": "2026.08",
        "note": ("Approximate USD costs, hand-authored for relative ranking, not "
                 "for budgeting to the dollar. Edit tools/build_data.py and rerun."),
        "countries": countries,
        "cities": cities,
        "iata": iata,
        "aliases": ALIASES,
    }
    path = os.path.join(root, "data", "destinations.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, sort_keys=True, ensure_ascii=False)
    print("wrote %s" % path)
    print("  countries=%d cities=%d iata=%d aliases=%d"
          % (len(countries), len(cities), len(iata), len(ALIASES)))


if __name__ == "__main__":
    main()
