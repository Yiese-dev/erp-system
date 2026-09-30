from packages.campus_common.migrate import run
from services.hr.app.models import Base
from services.hr.app.seed import seed

if __name__ == "__main__":
    run("hr", Base.metadata, seed)
