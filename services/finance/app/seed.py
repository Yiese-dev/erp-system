import random
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import select

from packages.campus_common import demo
from packages.campus_common.database import LOCAL_TZ, Database, utcnow
from services.finance.app.domain import billing, marketing, payments
from services.finance.app.models import Campaign, FeePlan, Invoice, Lead

TERM_NAMES = {"2026s": "2026 Spring", "2026u": "2026 Summer School", "2026f": "2026 Fall"}
LEAD_NAMES = ["Yannick Mvondo", "Prisca Ngo Bassa", "Olivier Dikongue", "Marthe Bella", "Fabrice Zambo", "Gisele Nkolo",
              "Ulrich Ebode", "Syntyche Ndoumbe", "Rodrigue Tsafack", "Berthe Mengue", "Landry Ebogo", "Nadege Moukouri",
              "Serge Ongolo", "Chancelle Djoumessi", "Alain Mbida", "Rosine Kenfack", "Junior Ateba", "Flore Nguimfack",
              "Hugues Nsangou", "Lydie Sime", "Ghislain Onana", "Carole Tchatchoua", "Wilfried Bekolo", "Adeline Fouda"]


def local(day: str, hour: int = 10, minute: int = 0) -> datetime:
    return datetime.fromisoformat(day).replace(hour=hour, minute=minute, tzinfo=LOCAL_TZ)


def seed(database: Database) -> None:
    for tenant_id, slug, name in demo.TENANTS:
        with database.session(tenant_id) as session:
            billing.remember_tenant(session, tenant_id, name, "2026-01")
            if session.scalar(select(FeePlan.id).limit(1)):
                continue
            seed_tenant(session, tenant_id, slug)


def registration(slug: str, index: int, term: str) -> dict:
    program = demo.program_of(index)
    return {"registration_id": f"reg_{slug}_{term}_{index:02d}", "student_id": f"stu_{slug}_{index:02d}",
            "student_user_id": "usr_student" if index == 0 else None, "student_name": demo.STUDENT_NAMES[index],
            "student_no": f"{slug[:3].upper()}25{index + 1:04d}", "program_id": f"prg_{slug}_{program}",
            "program_name": demo.PROGRAMS[program][1], "term_id": f"trm_{slug}_{term}", "term_name": TERM_NAMES[term], "courses": []}


def seed_tenant(session, tenant: str, slug: str) -> None:
    rng = random.Random(f"finance-{slug}")
    created = utcnow()
    for key, (_, title, amount) in demo.PROGRAMS.items():
        for term in ("2026s", "2026f"):
            session.add(FeePlan(id=f"fee_{slug}_{key}_{term}", tenant_id=tenant, program_id=f"prg_{slug}_{key}", program_name=title,
                                term_id=f"trm_{slug}_{term}", term_name=TERM_NAMES[term], amount=amount, due_days=30, active=True,
                                created_at=created))
    session.add(FeePlan(id=f"fee_{slug}_se_2026u", tenant_id=tenant, program_id=f"prg_{slug}_se", program_name=demo.PROGRAMS["se"][1],
                        term_id=f"trm_{slug}_2026u", term_name=TERM_NAMES["2026u"], amount=demo.SUMMER_FEE, due_days=14, active=True,
                        created_at=created))
    session.flush()

    def pay(invoice: Invoice, amount: int, when: datetime) -> None:
        method = rng.choices(["mtn_momo", "orange_money", "bank_transfer"], weights=[5, 3, 2])[0]
        reference = uuid4().hex if method != "bank_transfer" else f"VIR-{rng.randint(100000, 999999)}"
        payments.apply_payment(session, tenant, invoice, amount, method, reference, "usr_finance", paid_at=when)

    for index in range(len(demo.STUDENT_NAMES)):
        invoice, _ = billing.create_invoice(session, tenant, registration(slug, index, "2026s"), "import", local("2026-02-02", 8, index))
        roll = rng.random()
        if roll < 0.95:
            pay(invoice, invoice.total // 2, local(f"2026-02-{rng.randint(9, 26):02d}", rng.randint(8, 17)))
        if roll < 0.82:
            pay(invoice, invoice.total - invoice.paid, local(f"2026-04-{rng.randint(6, 28):02d}", rng.randint(8, 17)))
    for index in demo.SUMMER_STUDENTS:
        invoice, _ = billing.create_invoice(session, tenant, registration(slug, index, "2026u"), "import", local("2026-07-13", 9, index))
        pay(invoice, invoice.total, local(f"2026-07-{rng.randint(14, 24):02d}", rng.randint(8, 17)))
    for index in range(len(demo.STUDENT_NAMES)):
        if index in demo.FALL_UNREGISTERED or index in demo.FALL_EVENT_ONLY:
            continue
        invoice, _ = billing.create_invoice(session, tenant, registration(slug, index, "2026f"), "import", local("2026-09-07", 8, index))
        if rng.random() < 0.6:
            pay(invoice, invoice.total // 2, local(f"2026-09-{rng.randint(8, 28):02d}", rng.randint(8, 17)))

    campaigns = {
        "openday": Campaign(id=f"cmp_{slug}_openday", tenant_id=tenant, name="Spring Open Day 2026", channel="events",
                            starts_on=local("2026-01-10").date(), ends_on=local("2026-02-15").date(), budget=1_000_000, status="completed",
                            created_at=local("2026-01-05")),
        "radio": Campaign(id=f"cmp_{slug}_radio", tenant_id=tenant, name="Radio Balafon FM - Douala", channel="radio",
                          starts_on=local("2026-07-01").date(), ends_on=local("2026-08-31").date(), budget=1_000_000, status="completed",
                          created_at=local("2026-06-20")),
        "digital": Campaign(id=f"cmp_{slug}_digital", tenant_id=tenant, name="Fall Intake Digital 2026", channel="social",
                            starts_on=local("2026-06-01").date(), ends_on=local("2026-10-31").date(), budget=1_500_000, status="active",
                            created_at=local("2026-05-25")),
    }
    session.add_all(campaigns.values())
    session.flush()

    def expense(category: str, description: str, vendor: str, amount: int, day: str, campaign: str | None = None, state: str = "paid"):
        record = marketing.submit_expense(session, tenant, "usr_admin", category, description, vendor, amount,
                                          local(day).date(), campaigns[campaign].id if campaign else None)
        record.created_at = local(day)
        session.flush()
        if state in ("approved", "paid"):
            marketing.approve_expense(record, "usr_finance")
        if state == "paid":
            marketing.pay_expense(session, tenant, record, f"CHQ-{rng.randint(10000, 99999)}", local(day) + timedelta(days=3))

    for month in range(1, 10):
        expense("utilities", "Electricity supply", "ENEO Cameroon", rng.randint(780, 950) * 1000, f"2026-{month:02d}-05")
        expense("utilities", "Water supply", "CAMWATER", rng.randint(120, 160) * 1000, f"2026-{month:02d}-06")
        expense("it_services", "Dedicated internet link", "CAMTEL Business", 350_000, f"2026-{month:02d}-08")
        expense("it_services", "Cloud hosting and backups", "Nexttel Data Centre", 180_000, f"2026-{month:02d}-10")
        if month % 2:
            expense("supplies", "Office and laboratory consumables", "Librairie des Peuples", rng.randint(150, 400) * 1000, f"2026-{month:02d}-14")
        if month % 3 == 0:
            expense("maintenance", "Generator servicing", "Groupe Electro Services", 450_000, f"2026-{month:02d}-18")
    expense("marketing", "Open day venue and sound", "Hotel Akwa Palace", 600_000, "2026-01-20", "openday")
    expense("marketing", "Flyers and banners", "Imprimerie Saint-Paul", 250_000, "2026-01-12", "openday")
    for month in (7, 8):
        expense("marketing", "Radio spots (30 x 45s)", "Radio Balafon FM", 450_000, f"2026-{month:02d}-02", "radio")
    for month in (6, 7, 8, 9):
        expense("marketing", "Sponsored social media posts", "Meta Platforms Ireland", 300_000, f"2026-{month:02d}-03", "digital")
    expense("travel", "Recruitment fair travel - Bafoussam", "Touristique Express", 185_000, "2026-09-12")
    expense("supplies", "Projector lamps (x4)", "Douala Office Pro", 320_000, "2026-09-28", state="submitted")
    expense("maintenance", "Air-conditioning repair - Lab 2", "Froid Service SARL", 275_000, "2026-09-29", state="submitted")
    expense("marketing", "Campus tour video production", "Studio Mboa", 400_000, "2026-09-25", "digital", state="approved")

    names = iter(rng.sample(LEAD_NAMES, len(LEAD_NAMES)) * 3)
    plans = {"openday": (15, "2026-01-12", [(1, "2026-02-01"), (2, "2026-02-01"), (4, "2026-02-02")]),
             "radio": (12, "2026-07-03", [(12, "2026-08-20"), (13, "2026-08-24")]),
             "digital": (24, "2026-06-04", [(17, "2026-09-01"), (18, "2026-09-02"), (19, "2026-09-03"), (21, "2026-09-04"), (22, "2026-09-05")])}
    for key, (count, first_day, conversions) in plans.items():
        leads = []
        for number in range(count):
            lead = Lead(id=f"led_{slug}_{key}_{number:02d}", tenant_id=tenant, campaign_id=campaigns[key].id, name=next(names),
                        phone=f"6{rng.choice([7, 9, 5, 8])}{rng.randint(1000000, 9999999)}", email=None,
                        program_interest=rng.choice([demo.PROGRAMS["se"][1], demo.PROGRAMS["ba"][1]]),
                        stage=rng.choices(["new", "contacted", "qualified", "applied", "lost"], weights=[3, 4, 3, 2, 3])[0],
                        notes="", created_at=local(first_day) + timedelta(days=number * 2, hours=number % 7))
            leads.append(lead)
        session.add_all(leads)
        session.flush()
        for lead, (student_index, day) in zip(leads, conversions):
            lead.stage = "applied"
            marketing.convert_lead(session, lead, f"stu_{slug}_{student_index:02d}")
            lead.name, lead.converted_at = demo.STUDENT_NAMES[student_index], local(day)
