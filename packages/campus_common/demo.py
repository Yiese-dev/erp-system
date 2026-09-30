"""Deterministic synthetic demo roster shared by service seeders. Contains no real personal data."""

TENANTS = [("tn_ictu", "ictu", "ICT University"), ("tn_atlantic", "atlantic", "Atlantic Institute")]

USERS = {
    "super": ("usr_super", "superadmin@campus.test", "Platform Operator", "super_admin"),
    "admin": ("usr_admin", "admin@campus.test", "Camille Mboa", "admin"),
    "instructor": ("usr_instructor", "instructor@campus.test", "Dr. Samuel Fonkou", "instructor"),
    "instructor2": ("usr_instructor2", "lecturer@campus.test", "Dr. Grace Tabi", "instructor"),
    "finance": ("usr_finance", "finance@campus.test", "Amina Bello", "finance"),
    "hr": ("usr_hr", "hr@campus.test", "Marie Ngono", "hr"),
    "employee": ("usr_employee", "employee@campus.test", "Daniel Ekane", "employee"),
    "student": ("usr_student", "student@campus.test", "Nadia Nfor", "student"),
}

STUDENT_NAMES = [
    "Nadia Nfor", "Brice Tchoumi", "Clarisse Mbarga", "Joel Nkeng", "Estelle Fotso", "Kevin Ngwa",
    "Mireille Atangana", "Paul Etoundi", "Sandrine Njoya", "Herve Kamga", "Linda Achu", "Franck Owona",
    "Pauline Essomba", "Arnaud Tchinda", "Ruth Mefire", "Cyril Abena", "Vanessa Ewane", "Boris Nana",
    "Carine Manga", "Didier Fomba", "Irene Bih", "Steve Ngassa", "Laure Kouam", "Emmanuel Tanyi",
]

PROGRAMS = {"se": ("BSE", "BSc Software Engineering", 425_000), "ba": ("BBA", "BSc Business Administration", 375_000)}
SUMMER_FEE = 90_000
SUMMER_STUDENTS = [0, 1, 2, 4, 6, 8]
FALL_UNREGISTERED = {15, 23}
# Fall registrations Finance does not pre-import, so their invoices are created live through RabbitMQ.
FALL_EVENT_ONLY = {0, 3, 7, 16, 20}


def program_of(index: int) -> str:
    return "ba" if index >= 16 else "se"

TERMS = {"2026s": ("2026 Spring", "2026-02-02", "2026-06-26"), "2026f": ("2026 Fall", "2026-09-07", "2027-01-22")}

COURSES = {
    "sen101": ("se", "SEN101", "Programming Fundamentals", 4, []),
    "sen102": ("se", "SEN102", "Discrete Mathematics", 3, []),
    "sen201": ("se", "SEN201", "Data Structures and Algorithms", 4, ["sen101"]),
    "sen202": ("se", "SEN202", "Database Systems", 4, ["sen101"]),
    "sen301": ("se", "SEN301", "Software Architecture", 3, ["sen201"]),
    "bus101": ("ba", "BUS101", "Principles of Management", 3, []),
    "bus102": ("ba", "BUS102", "Financial Accounting", 3, []),
    "bus201": ("ba", "BUS201", "Marketing Management", 3, ["bus101"]),
    "bus202": ("ba", "BUS202", "Corporate Finance", 3, ["bus102"]),
}

EMPLOYEES = [
    ("usr_admin", "Camille Mboa", "Administration", "Registrar and Administration Director", 1_150_000, 150_000),
    ("usr_instructor", "Dr. Samuel Fonkou", "Academic Affairs", "Senior Lecturer", 850_000, 100_000),
    ("usr_instructor2", "Dr. Grace Tabi", "Academic Affairs", "Lecturer", 720_000, 80_000),
    ("usr_finance", "Amina Bello", "Finance", "Finance Officer", 540_000, 60_000),
    ("usr_hr", "Marie Ngono", "Human Resources", "HR Manager", 610_000, 70_000),
    ("usr_employee", "Daniel Ekane", "IT Services", "Systems Administrator", 420_000, 45_000),
    (None, "Aline Ze", "Administration", "Front Desk Officer", 185_000, 20_000),
    (None, "Patrick Nji", "IT Services", "Network Technician", 310_000, 30_000),
    (None, "Solange Eyenga", "Finance", "Accounts Clerk", 260_000, 25_000),
    (None, "Roger Ndi", "Administration", "Driver", 120_000, 15_000),
    (None, "Edith Mballa", "Academic Affairs", "Librarian", 290_000, 25_000),
    (None, "Christian Wamba", "Academic Affairs", "Lecturer", 700_000, 80_000),
    (None, "Josiane Ekotto", "Human Resources", "HR Assistant", 230_000, 20_000),
    (None, "Thierry Monthe", "Administration", "Security Supervisor", 150_000, 15_000),
]


def email_for(name: str, slug: str) -> str:
    local = name.lower().replace("dr. ", "").replace(" ", ".")
    return f"{local}@{slug}.campus.test"
