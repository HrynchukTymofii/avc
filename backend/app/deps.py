"""FastAPI dependency providers for app-level singletons created in the lifespan."""

from fastapi import Request

from app.config import Settings
from app.queue.job_store import JobStore
from app.queue.worker import GPUWorker
from app.services.loras import LoraRegistry


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_loras(request: Request) -> LoraRegistry:
    return request.app.state.loras


def get_store(request: Request) -> JobStore:
    return request.app.state.store


def get_worker(request: Request) -> GPUWorker:
    return request.app.state.worker
