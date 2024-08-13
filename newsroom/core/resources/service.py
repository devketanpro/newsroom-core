from typing import Generic, Any, ClassVar, TypeVar

from flask import current_app as app

from superdesk.core.resources.service import AsyncResourceService
from .model import NewshubResourceModel
from newsroom.utils import get_user_id


NewshubResourceModelType = TypeVar("NewshubResourceModelType", bound=NewshubResourceModel)


class NewshubAsyncResourceService(AsyncResourceService[Generic[NewshubResourceModelType]]):
    clear_item_cache_on_update: ClassVar[bool] = False

    async def on_create(self, docs: list[NewshubResourceModelType]) -> None:
        await super().on_create(docs)
        for doc in docs:
            doc.original_creator = get_user_id()

    async def on_update(self, updates: dict[str, Any], original: NewshubResourceModelType) -> None:
        await super().on_update(updates, original)
        updates["version_creator"] = get_user_id()

    async def on_updated(self, updates: dict[str, Any], original: NewshubResourceModelType) -> None:
        await super().on_updated(updates, original)
        if self.clear_item_cache_on_update:
            app.cache.delete(str(original.id))

    async def on_deleted(self, doc: NewshubResourceModelType):
        await super().on_deleted(doc)
        if self.clear_item_cache_on_update:
            app.cache.delete(str(doc.id))