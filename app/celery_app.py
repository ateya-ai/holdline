from celery import Celery

from holdline.config import celery_broker_url, configure_logging

configure_logging()
app = Celery("holdline", broker=celery_broker_url())
app.conf.update(
    task_ignore_result=True,
    imports=("app.worker",),
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    broker_connection_timeout=3,
    broker_connection_retry_on_startup=True,
    broker_transport_options={
        "socket_connect_timeout": 3,
        "socket_timeout": 3,
        "visibility_timeout": 120,
    },
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=65,
    task_time_limit=75,
)
