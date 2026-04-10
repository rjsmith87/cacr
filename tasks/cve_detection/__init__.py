"""CVE detection case study — 6 real CVEs as benchmark examples."""

from tasks.cve_detection.cve_2023_30861 import CVE as CVE_2023_30861
from tasks.cve_detection.cve_2023_32681 import CVE as CVE_2023_32681
from tasks.cve_detection.cve_2018_18074 import CVE as CVE_2018_18074
from tasks.cve_detection.cve_2019_11324 import CVE as CVE_2019_11324
from tasks.cve_detection.cve_2022_29217 import CVE as CVE_2022_29217
from tasks.cve_detection.cve_2021_33503 import CVE as CVE_2021_33503

ALL_CVES = [
    CVE_2023_30861,
    CVE_2023_32681,
    CVE_2018_18074,
    CVE_2019_11324,
    CVE_2022_29217,
    CVE_2021_33503,
]
