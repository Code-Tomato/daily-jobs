"""Resolve company -> ATS + slug by probing public APIs. Usage: python3 probe.py > resolved.json
Edit CANDIDATES: (company, ats, slug-or-tenant, [more guesses]). Workday guesses try common wd hosts/sites and pick the US facet."""
import json, sys, urllib.error
from concurrent.futures import ThreadPoolExecutor
import ats

CANDIDATES = [
    # --- AI labs / inference / ML infra
    ("Anthropic", "greenhouse", "anthropic"), ("OpenAI", "ashby", "openai"), ("xAI", "greenhouse", "xai"),
    ("Mistral AI", "lever", "mistral"), ("Cohere", "ashby", "cohere"), ("Perplexity", "ashby", "perplexityai", "perplexity"),
    ("Databricks", "greenhouse", "databricks"), ("Together AI", "greenhouse", "togetherai"), ("Fireworks AI", "greenhouse", "fireworksai", "fireworks"),
    ("Baseten", "ashby", "baseten"), ("Modal", "ashby", "modal"), ("Anyscale", "greenhouse", "anyscale"), ("Modular", "greenhouse", "modular"),
    ("Hugging Face", "greenhouse", "huggingface"), ("Weights & Biases", "greenhouse", "wandb", "weightsbiases"), ("Lambda", "greenhouse", "lambda", "lambdalabs"),
    ("CoreWeave", "greenhouse", "coreweave"), ("Crusoe", "greenhouse", "crusoe", "crusoeenergy"), ("Scale AI", "greenhouse", "scaleai"),
    ("Cursor", "ashby", "anysphere", "cursor"), ("Cognition", "ashby", "cognition"), ("Replit", "ashby", "replit"), ("Sierra", "ashby", "sierra"),
    ("Harvey", "ashby", "harvey"), ("Runway", "greenhouse", "runwayml"), ("Character.AI", "greenhouse", "characterai"), ("Poolside", "ashby", "poolside"),
    ("Lightning AI", "greenhouse", "lightningai"), ("RunPod", "ashby", "runpod"), ("Vast.ai", "greenhouse", "vastai"), ("Nebius", "greenhouse", "nebius"),
    ("Deepgram", "greenhouse", "deepgram"), ("ElevenLabs", "ashby", "elevenlabs"), ("Reka", "ashby", "reka"), ("Liquid AI", "ashby", "liquidai"),
    ("Physical Intelligence", "ashby", "physicalintelligence"), ("Figure AI", "greenhouse", "figureai"), ("Thinking Machines", "ashby", "thinkingmachines"),
    ("SSI", "ashby", "ssi", "safesuperintelligence"), ("Etched", "ashby", "etched"), ("Groq", "greenhouse", "groq"), ("Cerebras", "greenhouse", "cerebras"),
    ("SambaNova", "greenhouse", "sambanovasystems", "sambanova"), ("Tenstorrent", "greenhouse", "tenstorrent"), ("d-Matrix", "greenhouse", "dmatrix", "d-matrix"),
    ("Lightmatter", "greenhouse", "lightmatter"), ("Ayar Labs", "greenhouse", "ayarlabs"), ("Astera Labs", "greenhouse", "asteralabs"),
    ("SiFive", "greenhouse", "sifive"), ("Ampere Computing", "greenhouse", "amperecomputing"), ("Rivos", "greenhouse", "rivos", "rivosinc"),
    ("MatX", "ashby", "matx"), ("Positron", "ashby", "positron"), ("Enfabrica", "greenhouse", "enfabrica"), ("Celestial AI", "greenhouse", "celestialai"),
    ("Mythic", "greenhouse", "mythic"), ("Untether AI", "greenhouse", "untetherai"), ("Fractile", "ashby", "fractile"), ("Extropic", "ashby", "extropic"),
    ("Normal Computing", "ashby", "normalcomputing"), ("Recogni", "greenhouse", "recogni"), ("Tensormesh", "ashby", "tensormesh"),
    # --- infra / cloud / data / dev tools
    ("Cloudflare", "greenhouse", "cloudflare"), ("Datadog", "greenhouse", "datadog"), ("MongoDB", "greenhouse", "mongodb"), ("Confluent", "greenhouse", "confluent"),
    ("HashiCorp", "greenhouse", "hashicorp"), ("Vercel", "greenhouse", "vercel"), ("Supabase", "ashby", "supabase"), ("Neon", "ashby", "neon"),
    ("PlanetScale", "greenhouse", "planetscale"), ("Temporal", "greenhouse", "temporal"), ("Fly.io", "ashby", "fly"), ("Render", "ashby", "render"),
    ("Railway", "ashby", "railway"), ("Pulumi", "greenhouse", "pulumi"), ("Grafana Labs", "greenhouse", "grafanalabs"), ("Elastic", "greenhouse", "elastic"),
    ("Redis", "greenhouse", "redis"), ("Cockroach Labs", "greenhouse", "cockroachlabs"), ("ClickHouse", "greenhouse", "clickhouse"), ("Chronosphere", "greenhouse", "chronosphere"),
    ("Pure Storage", "greenhouse", "purestorage"), ("VAST Data", "greenhouse", "vastdata"), ("WEKA", "greenhouse", "weka"), ("Nutanix", "greenhouse", "nutanix"),
    ("Arista Networks", "greenhouse", "aristanetworks"), ("Stripe", "greenhouse", "stripe"), ("Airbnb", "greenhouse", "airbnb"), ("Coinbase", "greenhouse", "coinbase"),
    ("Dropbox", "greenhouse", "dropbox"), ("Figma", "greenhouse", "figma"), ("Notion", "ashby", "notion"), ("Linear", "ashby", "linear"),
    ("Discord", "greenhouse", "discord"), ("Reddit", "greenhouse", "reddit"), ("Pinterest", "greenhouse", "pinterest"), ("Roblox", "greenhouse", "roblox"),
    ("Robinhood", "greenhouse", "robinhood"), ("Instacart", "greenhouse", "instacart"), ("DoorDash", "greenhouse", "doordash"), ("Lyft", "greenhouse", "lyft"),
    ("Snowflake", "greenhouse", "snowflake"), ("Rippling", "rippling", "rippling"), ("Ramp", "ashby", "ramp"), ("Brex", "greenhouse", "brex"),
    ("Plaid", "lever", "plaid"), ("Samsara", "greenhouse", "samsara"), ("Verkada", "greenhouse", "verkada"), ("Palantir", "lever", "palantir"),
    ("Sentry", "greenhouse", "sentry"), ("Warp", "ashby", "warp"), ("Zed", "ashby", "zed"), ("Retool", "greenhouse", "retool"),
    # --- autonomy / robotics / defense / hardware
    ("Zoox", "lever", "zoox"), ("Waymo", "greenhouse", "waymo"), ("Nuro", "greenhouse", "nuro"), ("Aurora", "greenhouse", "aurora", "aurorainnovation"),
    ("Applied Intuition", "greenhouse", "appliedintuition"), ("Skydio", "greenhouse", "skydio"), ("Anduril", "greenhouse", "andurilindustries"),
    ("Shield AI", "greenhouse", "shieldai"), ("SpaceX", "greenhouse", "spacex"), ("Relativity Space", "greenhouse", "relativity"), ("Rivian", "greenhouse", "rivian"),
    ("Lucid Motors", "greenhouse", "lucidmotors"), ("Boston Dynamics", "greenhouse", "bostondynamics"), ("Agility Robotics", "greenhouse", "agilityrobotics"),
    ("Apptronik", "greenhouse", "apptronik"), ("1X", "ashby", "1x"), ("Saronic", "greenhouse", "saronic"), ("Hadrian", "greenhouse", "hadrian"),
    ("Epirus", "greenhouse", "epirus"), ("Hermeus", "greenhouse", "hermeus"), ("Varda", "greenhouse", "varda"), ("Astranis", "greenhouse", "astranis"),
    ("Neuralink", "greenhouse", "neuralink"), ("Formlabs", "greenhouse", "formlabs"), ("Wisk", "greenhouse", "wisk"), ("Joby Aviation", "greenhouse", "jobyaviation"),
    ("Archer Aviation", "greenhouse", "archer"), ("Motional", "greenhouse", "motional"), ("Kodiak", "greenhouse", "kodiak"), ("Gatik", "greenhouse", "gatik"),
    # --- quant / HFT (systems-heavy)
    ("Jane Street", "greenhouse", "janestreet"), ("Hudson River Trading", "greenhouse", "hudsonrivertrading", "wehrtyou"), ("Citadel", "greenhouse", "citadel"),
    ("Citadel Securities", "greenhouse", "citadelsecurities"), ("Two Sigma", "greenhouse", "twosigma"), ("Jump Trading", "greenhouse", "jumptrading"),
    ("DRW", "greenhouse", "drw"), ("Optiver", "greenhouse", "optiver"), ("IMC", "greenhouse", "imc"), ("Akuna Capital", "greenhouse", "akunacapital"),
    ("Five Rings", "greenhouse", "fiverings"), ("Tower Research", "greenhouse", "towerresearchcapital"), ("Virtu", "greenhouse", "virtu"), ("SIG", "greenhouse", "sig"),
    ("Radix Trading", "greenhouse", "radixtrading"), ("Headlands", "greenhouse", "headlandstech"), ("Old Mission", "greenhouse", "oldmissioncapital"),
    # --- big tech on Workday (tenant guesses; probe tries wd1/wd3/wd5/wd12 x common sites)
    ("NVIDIA", "workday", "nvidia", "NVIDIAExternalCareerSite"), ("AMD", "workday", "amd", "External"), ("Qualcomm", "workday", "qualcomm", "External"),
    ("Intel", "workday", "intel", "External"), ("Micron", "workday", "micron", "External"), ("Broadcom", "workday", "broadcom", "External_Career"),
    ("Marvell", "workday", "marvell", "External"), ("Dell", "workday", "dell", "External"), ("HPE", "workday", "hpe", "Jobsathpe"),
    ("Salesforce", "workday", "salesforce", "External_Career_Site"), ("Arm", "workday", "arm", "External"), ("Analog Devices", "workday", "analogdevices", "External"),
    ("Western Digital", "workday", "wd", "External"), ("Seagate", "workday", "seagate", "External"), ("Lam Research", "workday", "lamresearch", "External"),
    ("Applied Materials", "workday", "amat", "External"), ("KLA", "workday", "kla", "Search"), ("Synopsys", "workday", "synopsys", "External"),
    ("Cadence", "workday", "cadence", "External_Careers"), ("Caterpillar", "workday", "cat", "External"), ("John Deere", "workday", "deere", "External"),
    ("Ford", "workday", "ford", "External"), ("GM", "workday", "gm", "External"), ("Lockheed Martin", "workday", "lmco", "External"),
    ("Northrop Grumman", "workday", "ngc", "Northrop_Grumman_External_Site"), ("Raytheon", "workday", "rtx", "External"), ("Sandia", "workday", "sandia", "Careers"),
    ("Texas Instruments", "workday", "ti", "External"), ("Cisco", "workday", "cisco", "External"), ("VMware", "workday", "vmware", "External"),
    ("Samsung Semiconductor", "workday", "samsung", "External"), ("Rambus", "workday", "rambus", "External"), ("Infineon", "workday", "infineon", "External"),
    ("NXP", "workday", "nxp", "External"), ("Nokia", "workday", "nokia", "External"), ("Ericsson", "workday", "ericsson", "External"),
    ("ServiceNow", "smartrecruiters", "ServiceNow"), ("Bosch", "smartrecruiters", "BoschGroup"), ("LinkedIn", "smartrecruiters", "LinkedIn"),
    ("Visa", "smartrecruiters", "Visa"), ("Ubisoft", "smartrecruiters", "Ubisoft2"), ("Square", "smartrecruiters", "Square"),
]
WD_HOSTS = ["wd1", "wd3", "wd5", "wd12", "wd103", "wd10"]
WD_SITES = ["External", "External_Careers", "Careers", "External_Career_Site", "careers", "Search", "External_Career", "Jobs", "Job_Board",
            "MarvellCareers", "CaterpillarCareers", "Careers_GM", "Samsung_Careers", "Cisco_Careers", "sifivecareers", "Boston_Dynamics"]

def count(ats_name, slug):
    try:
        if ats_name == "greenhouse":
            return len(ats.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")["jobs"])
        if ats_name == "lever":
            return len(ats.get(f"https://api.lever.co/v0/postings/{slug}?mode=json"))
        if ats_name == "ashby":
            return len(ats.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")["jobs"])
        if ats_name == "smartrecruiters":  # nonexistent tenants answer 200 with 0, so 0 means unresolved
            return ats.get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=1")["totalFound"] or None
        if ats_name == "rippling":
            return len(ats.get(f"https://api.rippling.com/platform/api/ats/v1/board/{slug}/jobs"))
        if ats_name == "workable":
            return len(ats.get(f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true")["jobs"])
    except Exception:
        return None

def workday(tenant, site_guess):
    sites = [site_guess] + [s for s in WD_SITES if s != site_guess]
    def tenant_on(host):  # a bogus site answers 404 when the tenant lives on this host, 422 when it does not
        try:
            ats.get(f"https://{tenant}.{host}.myworkdayjobs.com/wday/cxs/{tenant}/ZzProbe/jobs", {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""})
        except urllib.error.HTTPError as e:
            return e.code == 404
        except Exception:
            return False
        return True
    for host in [h for h in WD_HOSTS if tenant_on(h)]:
        for site in sites:
            url = f"https://{tenant}.{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
            try:
                d = ats.get(url, {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""})
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    return {"error": "429"}
                continue
            except Exception:
                continue
            if "jobPostings" not in d:
                continue
            cfg = {"host": f"{tenant}.{host}.myworkdayjobs.com", "tenant": tenant, "site": site, "total": d.get("total")}
            def find_us(fs):
                for f in fs:
                    for v in f.get("values", []):
                        if str(v.get("descriptor", "")).startswith("United States"):
                            return f["facetParameter"], v["id"], v.get("count")
                        if v.get("facetParameter"):
                            r = find_us([v])
                            if r: return r
            us = find_us(d.get("facets", []))
            if us:
                cfg["facets"] = {us[0]: [us[1]]}; cfg["us_total"] = us[2]
            return cfg
    return None

def resolve(c):
    company, ats_name, *guesses = c
    if ats_name == "workday":
        r = workday(guesses[0], guesses[1] if len(guesses) > 1 else "External")
        return (company, ats_name, r)
    for slug in guesses:
        n = count(ats_name, slug)
        if n is not None:
            return (company, ats_name, {"slug": slug, "total": n})
    return (company, ats_name, None)

if __name__ == "__main__":
  with ThreadPoolExecutor(12) as ex:
    results = list(ex.map(resolve, CANDIDATES))
  ok = [{"company": co, "ats": a, **{k: v for k, v in r.items() if k not in ("total", "us_total")}} for co, a, r in results if r and "error" not in r]
  json.dump(ok, sys.stdout, indent=1)
  for co, a, r in results:
    print(f"{'OK ' if r and 'error' not in r else '-- '}{co:22} {a:15} {r}", file=sys.stderr)
