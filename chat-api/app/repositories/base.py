from typing import Generic, Type, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    def __init__(self, model: Type[ModelT], db: AsyncSession):
        self._model = model
        self._db = db

    async def delete(self, instance: ModelT) -> None:
        await self._db.delete(instance)
