from packages.campus_common.migrate import run
from services.academic.app.models import Base
from services.academic.app.seed import seed

if __name__ == "__main__":
    run("academic", Base.metadata, seed)
