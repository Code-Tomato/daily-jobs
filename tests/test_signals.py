import os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "find-jobs", "scripts"))
import signals as s  # noqa: E402


def post(description="", title="Engineer", basic="", preferred="", location="Austin, TX", category=""):
    return {"title": title, "description": description, "basic": basic, "preferred": preferred, "location": location, "category": category}


class Years(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(s.years(post("Requirements\n3+ years of experience with Python")), 3)

    def test_age_is_not_experience(self):
        self.assertEqual(s.years(post("Requirements\nAt least 18 years of age\n2 years of experience in retail")), 2)
        self.assertIsNone(s.years(post("Must be 21 years or older")))

    def test_bachelors_bar_wins(self):
        text = ("Qualifications\nHigh School Diploma and 10 years of engineering experience OR\n"
                "Associate's degree and 8 years of engineering experience OR\nBachelor's degree and 4 years of engineering experience")
        self.assertEqual(s.years(post(text)), 4)

    def test_preferred_lines_skipped(self):
        self.assertEqual(s.years(post(basic="5+ years of experience preferred\n1 year of experience required")), 1)
        self.assertIsNone(s.years(post("What you need\nA CS degree\nNice to have\n5+ years of experience with Rust")))

    def test_company_history_ignored(self):
        self.assertIsNone(s.years(post("For over 50 years of serving customers, our company has grown.")))

    def test_words(self):
        self.assertEqual(s.years(post("Minimum of three (3) years of related experience")), 3)


    def test_study_is_not_experience(self):
        self.assertIsNone(s.years(post("Requirements\nExpected completion of one year of study prior to the internship")))


class Level(unittest.TestCase):
    def test_titles(self):
        cases = {"Software Engineer Intern (Summer 2027)": "intern", "Co-op, Mechanical Design": "intern",
                 "Software Engineer, New Grad 2027": "new-grad", "University Graduate - Hardware Engineer": "new-grad",
                 "Senior Software Engineer": "senior", "Staff Engineer": "senior", "Engineering Manager, Infra": "manager",
                 "Director of Finance": "manager", "Software Engineer II": "mid", "Associate Software Engineer": "entry",
                 "Junior Data Analyst": "entry", "Internship Program Manager": "", "Campus Recruiter": "",
                 "Software Development Program Manager": ""}
        for title, want in cases.items():
            self.assertEqual(s.level({"title": title}), want, title)

    def test_years_fallback(self):
        self.assertEqual(s.level({"title": "Data Analyst"}, 0), "entry")
        self.assertEqual(s.level({"title": "Data Analyst"}, 3), "mid")
        self.assertEqual(s.level({"title": "Data Analyst"}, 7), "senior")
        self.assertEqual(s.level({"title": "Data Analyst"}, None), "")


class Degree(unittest.TestCase):
    def test_lowest_required(self):
        self.assertEqual(s.degree(post("Requirements\nBachelor's or Master's degree in CS")), "bs")
        self.assertEqual(s.degree(post("Requirements\nPhD in Physics or a related field")), "phd")
        self.assertEqual(s.degree(post("Requirements\nCurrently pursuing a PhD in EE")), "phd")
        self.assertEqual(s.degree(post("Requirements\nBS in Computer Science or related field")), "bs")
        self.assertEqual(s.degree(post("Requirements\nHigh school diploma or GED required")), "hs")

    def test_pursued_degree_is_the_gate(self):
        self.assertEqual(s.degree(post("Requirements\nBS in Computer Science. Currently enrolled in an MS or PhD program")), "ms")
        self.assertEqual(s.degree(post("Requirements\nBachelor's degree completed. Must be enrolled in a graduate program")), "ms")
        self.assertEqual(s.degree(post("Requirements\nPursuing a BS, MS, or PhD in Computer Science")), "bs")

    def test_prose_is_not_a_degree(self):
        self.assertIsNone(s.degree(post("Requirements\nMust be able to be on site; MS Office skills")))

    def test_preferred_degree_ignored(self):
        self.assertEqual(s.degree(post("Requirements\nBachelor's degree in EE\nPreferred\nMaster's degree preferred")), "bs")


class Authorization(unittest.TestCase):
    def test_citizen(self):
        self.assertTrue(s.citizen("Due to the nature of our projects, US Citizenship is required."))
        self.assertTrue(s.citizen("This position is limited to US Citizens or Permanent Residents."))
        self.assertTrue(s.citizen("To conform to ITAR, applicants must be U.S. persons."))
        self.assertFalse(s.citizen("All qualified applicants will receive consideration without regard to citizenship status."))

    def test_no_sponsor(self):
        self.assertTrue(s.no_sponsor("Visa sponsorship is not available for this role."))
        self.assertTrue(s.no_sponsor("Candidates must be authorized to work in the US without the need for current or future sponsorship."))
        self.assertTrue(s.no_sponsor("We are unable to provide visa sponsorship for this position."))
        self.assertTrue(s.no_sponsor("This role is not eligible for visa sponsorship."))
        for text in ("We are unable to sponsor or take over sponsorship of an employment Visa at this time",
                     "No company sponsored housing, relocation, visa sponsorship or Green Card assistance available",
                     "Applicants must not require employment-based sponsorship now or in the future",
                     "This internship aligns to a potential role that is not eligible for Qualcomm immigration sponsorship",
                     "Sponsorship and future sponsorship are not available for this opportunity, including F-1 OPT"):
            self.assertTrue(s.no_sponsor(text), text)
        self.assertFalse(s.no_sponsor("Sponsorship for future roles is not guaranteed"))
        self.assertTrue(s.facts(post("No company sponsored housing, relocation, visa\xa0sponsorship or Green Card\xa0assistance available"))["no_sponsor"])
        self.assertFalse(s.no_sponsor("We do not discriminate on the basis of visa status"))
        self.assertFalse(s.no_sponsor("We will sponsor visas for qualified candidates."))
        self.assertFalse(s.no_sponsor("Great benefits and a friendly team."))

    def test_clearance(self):
        self.assertTrue(s.clearance("Must have an active Secret clearance."))
        self.assertTrue(s.clearance("Ability to obtain a security clearance is required."))
        self.assertFalse(s.clearance("Export control: candidates must be US persons."))


class Pay(unittest.TestCase):
    def test_ranges(self):
        self.assertEqual(s.pay("The salary range for this role is $120,000 - $150,000 per year."), [120000, 150000, "year"])
        self.assertEqual(s.pay("Pay: $45/hour"), [45, 45, "hour"])
        self.assertEqual(s.pay("Base pay range $120k-150k"), [120000, 150000, "year"])

    def test_not_pay(self):
        self.assertIsNone(s.pay("We raised $200 million in funding."))
        self.assertIsNone(s.pay("A $5,000 signing bonus and relocation."))

    def test_text_and_yearly(self):
        self.assertEqual(s.pay_text([62000, 78000, "year"]), "$62,000 to $78,000")
        self.assertEqual(s.pay_text([45, 45, "hour"]), "$45/hour")
        self.assertEqual(s.yearly([40, 50, "hour"]), 104000)


class Places(unittest.TestCase):
    def test_states(self):
        self.assertEqual(s.states("Austin, TX"), ["TX"])
        self.assertEqual(s.states("US, CA, Cupertino"), ["CA"])
        self.assertEqual(s.states("New York, NY; San Francisco, CA"), ["NY", "CA"])
        self.assertEqual(s.states("Houston"), ["TX"])
        self.assertEqual(s.states("Seattle, Washington, United States"), ["WA"])
        self.assertEqual(s.states("Washington, DC"), ["DC"])
        self.assertEqual(s.states("Remote - US"), [])

    def test_remote(self):
        self.assertEqual(s.remote({"location": "Remote - US", "title": "Engineer"}), "remote")
        self.assertEqual(s.remote({"location": "Austin, TX (Hybrid)", "title": "Engineer"}), "hybrid")
        self.assertEqual(s.remote({"location": "Austin, TX", "title": "Engineer", "description": "This is a fully remote role."}), "remote")
        self.assertEqual(s.remote({"location": "Austin, TX", "title": "Engineer", "description": ""}), "")


class Misc(unittest.TestCase):
    def test_term(self):
        self.assertEqual(s.term({"title": "Software Intern - Summer 2027"}), "Summer 2027")
        self.assertEqual(s.term({"title": "Co-op", "description": "This co-op runs Fall '27"}), "Fall 2027")
        self.assertIsNone(s.term({"title": "Intern", "description": "Join us"}))
        self.assertEqual(s.term({"title": "ML Engineer Intern - 2027 Summer"}), "Summer 2027")
        self.assertEqual(s.term({"title": "Fall Co-op, Mechanical"}), "Fall")

    def test_deadline_and_gpa(self):
        self.assertEqual(s.deadline("Applications close on January 15, 2027."), "2027-01-15")
        self.assertIsNone(s.deadline("We hire year round."))
        self.assertEqual(s.deadline("Applications for this job will be accepted at least until November 2, 2026."), "2026-11-02")
        self.assertEqual(s.deadline("Postings close: September 27, 2026"), "2026-09-27")
        self.assertEqual(s.deadline("The estimated job application period closure is May 25 2027"), "2027-05-25")
        self.assertEqual(s.gpa("Minimum 3.0 cumulative GPA"), "3.0")
        self.assertEqual(s.gpa("GPA of 3.25 or higher"), "3.25")

    def test_family(self):
        cases = {"Software Engineer": "software", "Data Scientist": "data", "ASIC Verification Engineer": "hardware",
                 "Firmware Engineer": "hardware", "Mechanical Design Engineer": "mechanical", "Registered Nurse - ICU": "healthcare",
                 "Investment Banking Analyst": "finance", "Product Manager": "product", "UX Designer": "design",
                 "Warehouse Associate": "business", "Civil Engineer": "civil"}
        for title, want in cases.items():
            self.assertEqual(s.family({"title": title}), want, title)

    def test_excerpt_prefers_requirements(self):
        text = "\n".join(["About us", "We are a great company with a long history."] + ["We value teamwork and fun."] * 30
                         + ["Requirements", "Bachelor's degree in EE", "US citizenship required"]
                         + ["Equal opportunity employer without regard to race."])
        ex = s.excerpt(post(text), limit=200)
        self.assertIn("Bachelor's degree in EE", ex)
        self.assertIn("US citizenship required", ex)
        self.assertNotIn("Equal opportunity", ex)

    def test_facts_shape(self):
        f = s.facts(post("Requirements\nPursuing a BS in CS\nVisa sponsorship is not available.\n$40/hour", title="Software Intern, Summer 2027"))
        self.assertEqual(f["level"], "intern")
        self.assertEqual(f["term"], "Summer 2027")
        self.assertEqual(f["degree"], "bs")
        self.assertTrue(f["no_sponsor"])
        self.assertEqual(f["pay"], [40, 40, "hour"])
        self.assertEqual(f["states"], ["TX"])


if __name__ == "__main__":
    unittest.main()
