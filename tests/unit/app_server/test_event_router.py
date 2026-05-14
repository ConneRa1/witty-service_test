from uuid import uuid4

import pytest
from fastapi import HTTPException

from openhands.app_server.event.event_router import batch_get_events


class EventServiceShouldNotBeCalled:
    async def batch_get_events(self, conversation_id, event_ids):
        raise AssertionError('batch_get_events should not be called')


@pytest.mark.asyncio
async def test_batch_get_events_rejects_too_many_ids():
    conversation_id = str(uuid4())
    event_ids = [str(uuid4()) for _ in range(101)]

    with pytest.raises(HTTPException) as exc_info:
        await batch_get_events(
            conversation_id=conversation_id,
            id=event_ids,
            event_service=EventServiceShouldNotBeCalled(),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == 'too_many_event_ids'
