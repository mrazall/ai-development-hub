from fastapi import APIRouter, Depends
from sqlalchemy import select

from ..auth import current_user, db_dep, write_user
from ..deps import project_or_404
from ..models import Task
from ..schemas import TaskIn, TaskOut

router = APIRouter(prefix="/projects/{project_id}/tasks", tags=["tasks"])


@router.post("", response_model=TaskOut)
def create_task(project_id: str, data: TaskIn, user=Depends(write_user), db=Depends(db_dep)):
    project_or_404(db, user, project_id)
    if data.idempotency_key:
        existing = db.scalar(
            select(Task).where(
                Task.project_id == project_id, Task.idempotency_key == data.idempotency_key
            )
        )
        if existing:
            return existing
    task = Task(project_id=project_id, **data.model_dump())
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.get("", response_model=list[TaskOut])
def list_tasks(project_id: str, user=Depends(current_user), db=Depends(db_dep)):
    project_or_404(db, user, project_id)
    return list(db.scalars(select(Task).where(Task.project_id == project_id)))


@router.get("/{task_id}", response_model=TaskOut)
def get_task(project_id: str, task_id: str, user=Depends(current_user), db=Depends(db_dep)):
    project_or_404(db, user, project_id)
    task = db.scalar(select(Task).where(Task.id == task_id, Task.project_id == project_id))
    if not task:
        from fastapi import HTTPException

        raise HTTPException(404, "task not found")
    return task


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(
    project_id: str, task_id: str, data: TaskIn, user=Depends(write_user), db=Depends(db_dep)
):
    project_or_404(db, user, project_id)
    task = db.scalar(select(Task).where(Task.id == task_id, Task.project_id == project_id))
    if not task:
        from fastapi import HTTPException

        raise HTTPException(404, "task not found")
    for key, value in data.model_dump().items():
        setattr(task, key, value)
    db.commit()
    return task


@router.delete("/{task_id}", status_code=204)
def delete_task(project_id: str, task_id: str, user=Depends(write_user), db=Depends(db_dep)):
    project_or_404(db, user, project_id)
    task = db.scalar(select(Task).where(Task.id == task_id, Task.project_id == project_id))
    if not task:
        from fastapi import HTTPException

        raise HTTPException(404, "task not found")
    db.delete(task)
    db.commit()
