"""Detect which ATS a careers page uses. Usage: python3 detect_ats.py   (edit SITES)"""
import re, ssl, urllib.request
from concurrent.futures import ThreadPoolExecutor
ctx = ssl.create_default_context()
MARKERS = [r"boards(?:-api)?\.greenhouse\.io/[^\s\"'<>]{0,60}", r"job-boards\.greenhouse\.io/[a-z0-9_-]+", r"jobs\.lever\.co/[a-z0-9_-]+", r"api\.lever\.co/v0/postings/[a-z0-9_-]+",
           r"jobs\.ashbyhq\.com/[a-z0-9_-]+", r"api\.ashbyhq\.com/posting-api/job-board/[a-z0-9_-]+", r"[a-z0-9-]+\.wd\d+\.myworkdayjobs\.com/[A-Za-z0-9_/-]{0,40}",
           r"jobs\.smartrecruiters\.com/[A-Za-z0-9_-]+", r"apply\.workable\.com/[a-z0-9-]+", r"ats\.rippling\.com/[a-z0-9-]+",
           r"[a-z0-9.-]*(?:icims\.com|taleo\.net|oraclecloud\.com|successfactors\.[a-z]+|eightfold\.ai|phenom(?:people)?\.com|jobvite\.com|bamboohr\.com|recruitee\.com|teamtailor\.com|myworkdaysite\.com|avature\.net|ultipro\.com|paylocity\.com|dover\.com|gem\.com|wellfound\.com)[^\s\"'<>]{0,40}"]
PAT = re.compile("|".join(f"(?:{m})" for m in MARKERS), re.I)
SITES = {
 "AMD":["https://careers.amd.com/careers-home/jobs"], "Arm":["https://careers.arm.com/"], "Marvell":["https://www.marvell.com/company/careers.html","https://careers.marvell.com/"],
 "Synopsys":["https://www.synopsys.com/careers.html","https://careers.synopsys.com/"], "Texas Instruments":["https://careers.ti.com/"], "Groq":["https://groq.com/careers"],
 "Modular":["https://www.modular.com/careers","https://www.modular.com/company/careers"], "SiFive":["https://www.sifive.com/careers"], "Applied Intuition":["https://www.appliedintuition.com/careers"],
 "Rivian":["https://careers.rivian.com/","https://rivian.com/careers"], "Boston Dynamics":["https://bostondynamics.com/careers/"], "Aurora":["https://aurora.tech/careers"],
 "Citadel":["https://www.citadel.com/careers/open-opportunities/"], "Citadel Securities":["https://www.citadelsecurities.com/careers/open-opportunities/"], "Two Sigma":["https://www.twosigma.com/careers/","https://careers.twosigma.com/"],
 "SIG":["https://sig.com/careers/","https://careers.sig.com/"], "Weights & Biases":["https://wandb.ai/site/careers"], "Runway":["https://runwayml.com/careers"], "Character.AI":["https://character.ai/careers"],
 "Deepgram":["https://deepgram.com/careers"], "Liquid AI":["https://www.liquid.ai/careers"], "Ayar Labs":["https://ayarlabs.com/careers/"], "Ampere Computing":["https://amperecomputing.com/company/careers"],
 "Rivos":["https://www.rivosinc.com/careers"], "Positron":["https://www.positron.ai/careers"], "Enfabrica":["https://www.enfabrica.net/careers"], "Celestial AI":["https://www.celestial.ai/careers"],
 "Mythic":["https://mythic.ai/careers/"], "Recogni":["https://recogni.com/careers/"], "HashiCorp":["https://www.hashicorp.com/careers/open-positions"], "Fly.io":["https://fly.io/jobs/"],
 "Pulumi":["https://www.pulumi.com/careers/"], "Chronosphere":["https://chronosphere.io/careers/"], "WEKA":["https://www.weka.io/company/careers/"], "Nutanix":["https://www.nutanix.com/company/careers"],
 "Arista Networks":["https://www.arista.com/en/company/careers"], "Snowflake":["https://careers.snowflake.com/us/en"], "Plaid":["https://plaid.com/careers/openings/"], "Retool":["https://retool.com/careers"],
 "Varda":["https://www.varda.com/careers"], "Wisk":["https://wisk.aero/careers/"], "Joby Aviation":["https://www.jobyaviation.com/careers/"], "Gatik":["https://gatik.ai/careers/"],
 "Five Rings":["https://fiverings.com/careers/"], "Radix Trading":["https://radix-trading.com/careers/"], "Headlands":["https://www.headlandstech.com/careers/"], "Dell":["https://jobs.dell.com/"],
 "Western Digital":["https://jobs.westerndigital.com/"], "Seagate":["https://www.seagate.com/jobs/"], "Lam Research":["https://careers.lamresearch.com/"], "Cisco":["https://jobs.cisco.com/"],
 "Rambus":["https://www.rambus.com/careers/"], "Infineon":["https://www.infineon.com/cms/en/careers/"], "GM":["https://search-careers.gm.com/"], "Ford":["https://corporate.ford.com/careers.html"],
 "John Deere":["https://careers.deere.com/"], "Tesla":["https://www.tesla.com/careers/search/"], "Caterpillar":["https://careers.caterpillar.com/en/"], "Google":["https://www.google.com/about/careers/applications/jobs/results/"],
 "Meta":["https://www.metacareers.com/jobs"], "Apple":["https://jobs.apple.com/en-us/search"], "Microsoft":["https://jobs.careers.microsoft.com/global/en/search"],
 "Samsung Semiconductor":["https://semiconductor.samsung.com/us/careers/"], "Nokia":["https://www.nokia.com/about-us/careers/"], "Ericsson":["https://www.ericsson.com/en/careers"],
}
def fetch(company):
    hits = set()
    for u in SITES[company]:
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/120 Safari/537.36", "Accept": "text/html,*/*"})
            r = urllib.request.urlopen(req, timeout=20, context=ctx); html = r.read().decode("utf-8", "ignore"); final = r.geturl()
        except Exception as e:
            hits.add(f"ERR {str(e)[:50]}"); continue
        for m in PAT.finditer(html + " " + final):
            hits.add(m.group(0)[:80])
        if not hits: hits.add(f"no marker ({len(html)}B, {final.split('/')[2]})")
    return company, sorted(hits)[:5]
if __name__ == "__main__":
    with ThreadPoolExecutor(12) as ex:
        for co, h in ex.map(fetch, SITES):
            print(f"{co:20} {h}")
