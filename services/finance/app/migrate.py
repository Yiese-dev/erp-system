from packages.campus_common.migrate import run
from services.finance.app.models import Base
from services.finance.app.seed import seed

if __name__ == "__main__":
    run("finance", Base.metadata, seed)
