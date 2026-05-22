from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


from src.models.user import User  # noqa: E402, F401
from src.models.prompt import Prompt  # noqa: E402, F401
from src.models.category import PromptCategory  # noqa: E402, F401
from src.models.tag import PromptTag  # noqa: E402, F401
from src.models.rating import PromptRating  # noqa: E402, F401
from src.models.joins import prompts_categories, prompts_tags  # noqa: E402, F401
