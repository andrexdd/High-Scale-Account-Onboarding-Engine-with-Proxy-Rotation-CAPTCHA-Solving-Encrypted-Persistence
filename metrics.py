import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class JobStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RETRY = "retry"


@dataclass
class JobMetrics:
    job_id: int
    status: JobStatus = JobStatus.PENDING
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    attempts: int = 0
    errors: List[str] = field(default_factory=list)
    
    browser_launch_time: float = 0.0
    page_load_time: float = 0.0
    form_fill_time: float = 0.0
    captcha_solve_time: float = 0.0
    navigation_time: float = 0.0
    
    proxy_used: Optional[str] = None
    captcha_required: bool = False
    proxy_failures: int = 0
    
    def get_total_duration(self) -> float:
        if self.end_time and self.start_time:
            return self.end_time - self.start_time
        return 0.0
    
    def get_summary(self) -> Dict:
        return {
            "job_id": self.job_id,
            "status": self.status.value,
            "duration_seconds": self.get_total_duration(),
            "attempts": self.attempts,
            "errors": self.errors,
            "timings": {
                "browser_launch": self.browser_launch_time,
                "page_load": self.page_load_time,
                "form_fill": self.form_fill_time,
                "captcha_solve": self.captcha_solve_time,
                "navigation": self.navigation_time,
            },
            "proxy": self.proxy_used,
            "captcha_required": self.captcha_required,
            "proxy_failures": self.proxy_failures,
        }


@dataclass
class ProcessMetrics:
    start_time: float = field(default_factory=time.time)
    total_jobs: int = 0
    completed_jobs: int = 0
    failed_jobs: int = 0
    retried_jobs: int = 0
    
    total_attempts: int = 0
    proxy_failures: int = 0
    captcha_solves: int = 0
    
    job_metrics: Dict[int, JobMetrics] = field(default_factory=dict)
    
    def get_duration(self) -> float:
        return time.time() - self.start_time
    
    def get_success_rate(self) -> float:
        if self.total_jobs == 0:
            return 0.0
        return (self.completed_jobs / self.total_jobs) * 100
    
    def get_average_duration(self) -> float:
        if self.completed_jobs == 0:
            return 0.0
        total_duration = sum(
            m.get_total_duration() 
            for m in self.job_metrics.values() 
            if m.status == JobStatus.SUCCESS
        )
        return total_duration / self.completed_jobs
    
    def get_summary(self) -> Dict:
        return {
            "total_duration_seconds": self.get_duration(),
            "total_jobs": self.total_jobs,
            "completed": self.completed_jobs,
            "failed": self.failed_jobs,
            "retried": self.retried_jobs,
            "success_rate": f"{self.get_success_rate():.2f}%",
            "average_job_duration": f"{self.get_average_duration():.2f}s",
            "total_attempts": self.total_attempts,
            "proxy_failures": self.proxy_failures,
            "captcha_solves": self.captcha_solves,
            "jobs_per_second": f"{self.completed_jobs / max(1, self.get_duration()):.2f}",
        }
    
    def log_summary(self) -> None:
        summary = self.get_summary()
        logger.info("=== PROCESS METRICS ===")
        for key, value in summary.items():
            logger.info(f"{key}: {value}")
        logger.info("=======================")


class MetricsCollector:
    def __init__(self):
        self.process_metrics = ProcessMetrics()
    
    def register_job(self, job_id: int) -> JobMetrics:
        if job_id not in self.process_metrics.job_metrics:
            self.process_metrics.job_metrics[job_id] = JobMetrics(job_id=job_id)
            self.process_metrics.total_jobs += 1
        return self.process_metrics.job_metrics[job_id]
    
    def start_job(self, job_id: int) -> None:
        metrics = self.register_job(job_id)
        metrics.start_time = time.time()
        metrics.status = JobStatus.RUNNING
        metrics.attempts += 1
    
    def mark_job_success(self, job_id: int) -> None:
        metrics = self.register_job(job_id)
        metrics.end_time = time.time()
        metrics.status = JobStatus.SUCCESS
        self.process_metrics.completed_jobs += 1
        self.process_metrics.total_attempts += metrics.attempts
    
    def mark_job_failed(self, job_id: int, error: str) -> None:
        metrics = self.register_job(job_id)
        metrics.end_time = time.time()
        metrics.status = JobStatus.FAILED
        metrics.errors.append(error)
        self.process_metrics.failed_jobs += 1
        self.process_metrics.total_attempts += metrics.attempts
    
    def mark_job_retry(self, job_id: int) -> None:
        metrics = self.register_job(job_id)
        metrics.status = JobStatus.RETRY
        self.process_metrics.retried_jobs += 1
    
    def record_timing(self, job_id: int, metric_name: str, duration: float) -> None:
        metrics = self.register_job(job_id)
        if hasattr(metrics, metric_name):
            setattr(metrics, metric_name, duration)
    
    def record_proxy_used(self, job_id: int, proxy: str) -> None:
        metrics = self.register_job(job_id)
        metrics.proxy_used = proxy
    
    def record_proxy_failure(self, job_id: int) -> None:
        metrics = self.register_job(job_id)
        metrics.proxy_failures += 1
        self.process_metrics.proxy_failures += 1
    
    def record_captcha_solve(self, job_id: int) -> None:
        metrics = self.register_job(job_id)
        metrics.captcha_required = True
        self.process_metrics.captcha_solves += 1
    
    def record_error(self, job_id: int, error: str) -> None:
        metrics = self.register_job(job_id)
        metrics.errors.append(error)
    
    def get_job_summary(self, job_id: int) -> Optional[Dict]:
        if job_id not in self.process_metrics.job_metrics:
            return None
        return self.process_metrics.job_metrics[job_id].get_summary()
    
    def get_process_summary(self) -> Dict:
        return self.process_metrics.get_summary()
    
    def log_process_summary(self) -> None:
        self.process_metrics.log_summary()
