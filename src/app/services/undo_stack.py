"""Multi-step undo/redo stack for record, points, and block edits."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from ..domain.models import ActivityRecord, EventBlock
from ..services.points_service import apply_points_for_new_record, manual_adjust_points, recalculate_points_for_record
from ..storage.database import session_scope
from ..storage.repositories import (
    create_block,
    create_record,
    delete_block,
    delete_record,
    update_block,
    update_record,
)


@dataclass(frozen=True)
class RecordUndoSnapshot:
    block_id: int
    start_time: datetime
    end_time: datetime
    efficiency_score: int | None
    state_score: int | None
    mood_score: int | None
    tags: str | None
    note: str | None


@dataclass(frozen=True)
class BlockUndoSnapshot:
    name: str
    category: str
    points_per_minute: float


def snapshot_from_record(rec: ActivityRecord) -> RecordUndoSnapshot:
    return RecordUndoSnapshot(
        block_id=rec.block_id,
        start_time=rec.start_time,
        end_time=rec.end_time,
        efficiency_score=rec.efficiency_score,
        state_score=rec.state_score,
        mood_score=rec.mood_score,
        tags=rec.tags,
        note=rec.note,
    )


def snapshot_from_block(block: EventBlock) -> BlockUndoSnapshot:
    return BlockUndoSnapshot(name=block.name, category=block.category, points_per_minute=float(block.points_per_minute))


@dataclass
class CreateRecordCmd:
    snapshot: RecordUndoSnapshot
    record_id: int | None

    def undo(self, session: Session) -> None:
        assert self.record_id is not None
        rid = self.record_id
        delete_record(session, rid)
        recalculate_points_for_record(session, record_id=rid, new_record=None)
        self.record_id = None

    def redo(self, session: Session) -> None:
        assert self.record_id is None
        rec = create_record(
            session,
            self.snapshot.block_id,
            self.snapshot.start_time,
            self.snapshot.end_time,
            self.snapshot.efficiency_score,
            self.snapshot.state_score,
            self.snapshot.mood_score,
            self.snapshot.tags,
            self.snapshot.note,
        )
        apply_points_for_new_record(session, rec)
        self.record_id = rec.id


@dataclass
class UpdateRecordCmd:
    record_id: int
    before: RecordUndoSnapshot
    after: RecordUndoSnapshot

    def undo(self, session: Session) -> None:
        rec = update_record(
            session,
            self.record_id,
            self.before.block_id,
            self.before.start_time,
            self.before.end_time,
            self.before.efficiency_score,
            self.before.state_score,
            self.before.mood_score,
            self.before.tags,
            self.before.note,
        )
        recalculate_points_for_record(session, record_id=self.record_id, new_record=rec)

    def redo(self, session: Session) -> None:
        rec = update_record(
            session,
            self.record_id,
            self.after.block_id,
            self.after.start_time,
            self.after.end_time,
            self.after.efficiency_score,
            self.after.state_score,
            self.after.mood_score,
            self.after.tags,
            self.after.note,
        )
        recalculate_points_for_record(session, record_id=self.record_id, new_record=rec)


@dataclass
class DeleteRecordCmd:
    snapshot: RecordUndoSnapshot
    restored_id: int | None = None

    def undo(self, session: Session) -> None:
        rec = create_record(
            session,
            self.snapshot.block_id,
            self.snapshot.start_time,
            self.snapshot.end_time,
            self.snapshot.efficiency_score,
            self.snapshot.state_score,
            self.snapshot.mood_score,
            self.snapshot.tags,
            self.snapshot.note,
        )
        apply_points_for_new_record(session, rec)
        self.restored_id = rec.id

    def redo(self, session: Session) -> None:
        assert self.restored_id is not None
        rid = self.restored_id
        delete_record(session, rid)
        recalculate_points_for_record(session, record_id=rid, new_record=None)
        self.restored_id = None


@dataclass
class BulkDeleteCmd:
    snapshots: list[RecordUndoSnapshot]
    current_ids: list[int] = field(default_factory=list)

    def undo(self, session: Session) -> None:
        self.current_ids = []
        for snap in self.snapshots:
            rec = create_record(
                session,
                snap.block_id,
                snap.start_time,
                snap.end_time,
                snap.efficiency_score,
                snap.state_score,
                snap.mood_score,
                snap.tags,
                snap.note,
            )
            apply_points_for_new_record(session, rec)
            self.current_ids.append(rec.id)

    def redo(self, session: Session) -> None:
        for rid in list(self.current_ids):
            delete_record(session, rid)
            recalculate_points_for_record(session, record_id=rid, new_record=None)
        self.current_ids = []


@dataclass
class ManualPointsAdjustCmd:
    delta: int
    note: str | None

    def undo(self, session: Session) -> None:
        manual_adjust_points(session, -self.delta, self._undo_note())

    def redo(self, session: Session) -> None:
        manual_adjust_points(session, self.delta, self.note)

    def _undo_note(self) -> str | None:
        base = self.note or "手动调整"
        return f"撤销：{base}"


@dataclass
class CreateBlockCmd:
    snapshot: BlockUndoSnapshot
    block_id: int | None

    def undo(self, session: Session) -> None:
        assert self.block_id is not None
        delete_block(session, self.block_id)
        self.block_id = None

    def redo(self, session: Session) -> None:
        block = create_block(
            session,
            name=self.snapshot.name,
            category=self.snapshot.category,
            points_per_minute=self.snapshot.points_per_minute,
        )
        self.block_id = block.id


@dataclass
class DeleteBlockCmd:
    snapshot: BlockUndoSnapshot
    block_id: int | None = None

    def undo(self, session: Session) -> None:
        block = create_block(
            session,
            name=self.snapshot.name,
            category=self.snapshot.category,
            points_per_minute=self.snapshot.points_per_minute,
        )
        self.block_id = block.id

    def redo(self, session: Session) -> None:
        assert self.block_id is not None
        delete_block(session, self.block_id)
        self.block_id = None


@dataclass
class UpdateBlockCmd:
    block_id: int
    before: BlockUndoSnapshot
    after: BlockUndoSnapshot

    def undo(self, session: Session) -> None:
        update_block(
            session,
            self.block_id,
            name=self.before.name,
            category=self.before.category,
            points_per_minute=self.before.points_per_minute,
        )

    def redo(self, session: Session) -> None:
        update_block(
            session,
            self.block_id,
            name=self.after.name,
            category=self.after.category,
            points_per_minute=self.after.points_per_minute,
        )


UndoCommand = (
    CreateRecordCmd
    | UpdateRecordCmd
    | DeleteRecordCmd
    | BulkDeleteCmd
    | ManualPointsAdjustCmd
    | CreateBlockCmd
    | DeleteBlockCmd
    | UpdateBlockCmd
)


class UndoStack:
    def __init__(
        self,
        *,
        max_size: int = 200,
        on_changed: Callable[[], None] | None = None,
    ) -> None:
        self._undo: list[UndoCommand] = []
        self._redo: list[UndoCommand] = []
        self._max_size = max_size
        self._on_changed = on_changed

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def push(self, command: UndoCommand) -> None:
        self._undo.append(command)
        self._redo.clear()
        if len(self._undo) > self._max_size:
            self._undo.pop(0)

    def undo(self) -> bool:
        if not self._undo:
            return False
        cmd = self._undo.pop()
        try:
            with session_scope() as session:
                cmd.undo(session)
            self._redo.append(cmd)
        except Exception:
            self._undo.append(cmd)
            raise
        if self._on_changed:
            self._on_changed()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        cmd = self._redo.pop()
        try:
            with session_scope() as session:
                cmd.redo(session)
            self._undo.append(cmd)
        except Exception:
            self._redo.append(cmd)
            raise
        if self._on_changed:
            self._on_changed()
        return True
