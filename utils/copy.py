from typing import TYPE_CHECKING, Any

from aiogram.types import TelegramObject


class CopyTextButton(TelegramObject):
    text: str

    if TYPE_CHECKING:

        def __init__(__pydantic__self__, *, text: str,
                     **__pydantic_kwargs: Any) -> None:

            super().__init__(text=text, **__pydantic_kwargs)
