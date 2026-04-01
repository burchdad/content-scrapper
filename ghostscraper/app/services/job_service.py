import uuid


def create_job_id() -> str:
    return uuid.uuid4().hex
