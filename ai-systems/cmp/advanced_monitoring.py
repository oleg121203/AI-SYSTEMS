"""
Advanced Monitoring Module for AI-SYSTEMS
This module extends the basic monitoring capabilities with advanced features like:
- Anomaly detection
- Predictive analytics
- Service dependency mapping
- Alert management
- Custom dashboards
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple, Set

import numpy as np
from fastapi import HTTPException
from pydantic import BaseModel

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("cmp.advanced")

# Constants
ANOMALY_THRESHOLD = 2.5  # Standard deviations for anomaly detection
PREDICTION_WINDOW = 12  # Hours to predict ahead
MIN_DATA_POINTS = 24  # Minimum data points needed for predictions
ALERT_LEVELS = ["info", "warning", "error", "critical"]


class Alert(BaseModel):
    """Alert model for notification system"""
    id: str
    service: str
    level: str
    message: str
    timestamp: datetime
    acknowledged: bool = False
    metadata: Dict[str, Any] = {}


class ServiceDependency(BaseModel):
    """Model for service dependencies"""
    service: str
    depends_on: List[str]
    impact_level: int  # 1-5, with 5 being critical


class AnomalyDetectionResult(BaseModel):
    """Result of anomaly detection"""
    service: str
    metric: str
    timestamp: datetime
    value: float
    expected_range: Tuple[float, float]
    deviation: float
    is_anomaly: bool


# Storage for alerts and dependencies
alerts: List[Alert] = []
dependencies: Dict[str, ServiceDependency] = {}
service_metrics_history: Dict[str, Dict[str, List[Tuple[datetime, float]]]] = {}


async def detect_anomalies(service: str, metric: str, value: float) -> Optional[AnomalyDetectionResult]:
    """
    Detect anomalies in metrics using statistical methods
    
    Args:
        service: Service name
        metric: Metric name
        value: Current metric value
        
    Returns:
        AnomalyDetectionResult if anomaly detected, None otherwise
    """
    if service not in service_metrics_history:
        service_metrics_history[service] = {}
    
    if metric not in service_metrics_history[service]:
        service_metrics_history[service][metric] = []
    
    # Add current value to history
    current_time = datetime.now()
    service_metrics_history[service][metric].append((current_time, value))
    
    # Keep only last 7 days of data
    cutoff = current_time - timedelta(days=7)
    service_metrics_history[service][metric] = [
        (t, v) for t, v in service_metrics_history[service][metric] if t > cutoff
    ]
    
    # Need enough data points for anomaly detection
    history = service_metrics_history[service][metric]
    if len(history) < 10:
        return None
    
    # Extract values for analysis
    values = [v for _, v in history]
    
    # Calculate statistics
    mean = np.mean(values)
    std = np.std(values)
    
    # Determine if current value is an anomaly
    deviation = abs(value - mean) / std if std > 0 else 0
    is_anomaly = deviation > ANOMALY_THRESHOLD
    
    # Create result
    result = AnomalyDetectionResult(
        service=service,
        metric=metric,
        timestamp=current_time,
        value=value,
        expected_range=(mean - std, mean + std),
        deviation=deviation,
        is_anomaly=is_anomaly
    )
    
    # Generate alert if anomaly detected
    if is_anomaly:
        await create_alert(
            service=service,
            level="warning" if deviation < ANOMALY_THRESHOLD * 1.5 else "error",
            message=f"Anomaly detected in {metric}: value {value:.2f} is {deviation:.2f} standard deviations from mean",
            metadata={
                "metric": metric,
                "value": value,
                "mean": mean,
                "std": std,
                "deviation": deviation
            }
        )
    
    return result


async def predict_resource_usage(service: str, metric: str) -> Dict[str, Any]:
    """
    Predict future resource usage based on historical data
    
    Args:
        service: Service name
        metric: Metric name
        
    Returns:
        Dictionary with prediction results
    """
    if (service not in service_metrics_history or 
        metric not in service_metrics_history[service] or
        len(service_metrics_history[service][metric]) < MIN_DATA_POINTS):
        raise HTTPException(status_code=400, detail="Insufficient data for prediction")
    
    # Get historical data
    history = service_metrics_history[service][metric]
    
    # Simple linear regression for prediction
    # In a production system, you would use more sophisticated models
    x = np.array([(t - history[0][0]).total_seconds() / 3600 for t, _ in history])
    y = np.array([v for _, v in history])
    
    # Fit linear model
    coeffs = np.polyfit(x, y, 1)
    slope, intercept = coeffs
    
    # Predict next hours
    future_hours = np.arange(1, PREDICTION_WINDOW + 1)
    last_x = x[-1]
    predictions = [slope * (last_x + hour) + intercept for hour in future_hours]
    
    # Create prediction times
    last_time = history[-1][0]
    prediction_times = [
        (last_time + timedelta(hours=hour)).isoformat() for hour in future_hours
    ]
    
    return {
        "service": service,
        "metric": metric,
        "current_value": history[-1][1],
        "prediction_times": prediction_times,
        "predictions": predictions,
        "trend": "increasing" if slope > 0 else "decreasing",
        "slope": slope,
        "confidence": min(1.0, len(history) / MIN_DATA_POINTS)
    }


async def map_service_dependencies(services: Dict[str, Any]) -> Dict[str, List[str]]:
    """
    Map dependencies between services based on configuration and runtime data
    
    Args:
        services: Dictionary of service information
        
    Returns:
        Dictionary mapping services to their dependencies
    """
    dependency_map = {}
    
    for service_name, service_info in services.items():
        dependencies = []
        
        # Extract dependencies from service info
        if "config" in service_info and "dependencies" in service_info["config"]:
            dependencies.extend(service_info["config"]["dependencies"])
        
        # Add to dependency map
        dependency_map[service_name] = dependencies
    
    return dependency_map


async def create_alert(service: str, level: str, message: str, metadata: Dict[str, Any] = None) -> Alert:
    """
    Create a new alert
    
    Args:
        service: Service name
        level: Alert level (info, warning, error, critical)
        message: Alert message
        metadata: Additional metadata
        
    Returns:
        Created Alert object
    """
    if level not in ALERT_LEVELS:
        level = "info"
    
    alert_id = f"{int(time.time())}-{service}-{level}"
    alert = Alert(
        id=alert_id,
        service=service,
        level=level,
        message=message,
        timestamp=datetime.now(),
        metadata=metadata or {}
    )
    
    alerts.append(alert)
    
    # Keep only last 1000 alerts
    if len(alerts) > 1000:
        alerts.pop(0)
    
    logger.info(f"Alert created: {level} - {service} - {message}")
    return alert


async def acknowledge_alert(alert_id: str) -> Optional[Alert]:
    """
    Acknowledge an alert
    
    Args:
        alert_id: ID of the alert to acknowledge
        
    Returns:
        Updated Alert object or None if not found
    """
    for alert in alerts:
        if alert.id == alert_id:
            alert.acknowledged = True
            return alert
    
    return None


async def get_active_alerts(service: Optional[str] = None, level: Optional[str] = None) -> List[Alert]:
    """
    Get active (unacknowledged) alerts
    
    Args:
        service: Filter by service
        level: Filter by alert level
        
    Returns:
        List of active alerts
    """
    filtered_alerts = [a for a in alerts if not a.acknowledged]
    
    if service:
        filtered_alerts = [a for a in filtered_alerts if a.service == service]
    
    if level:
        filtered_alerts = [a for a in filtered_alerts if a.level == level]
    
    return filtered_alerts


async def calculate_service_health(service: str, metrics: Dict[str, Any]) -> float:
    """
    Calculate overall health score for a service (0-100)
    
    Args:
        service: Service name
        metrics: Service metrics
        
    Returns:
        Health score (0-100)
    """
    # Start with perfect score
    health_score = 100.0
    
    # Reduce score based on resource usage
    if "cpu_percent" in metrics:
        # CPU usage above 80% reduces health
        cpu_penalty = max(0, (metrics["cpu_percent"] - 80) * 2) if metrics["cpu_percent"] > 80 else 0
        health_score -= cpu_penalty
    
    if "memory_percent" in metrics:
        # Memory usage above 85% reduces health
        memory_penalty = max(0, (metrics["memory_percent"] - 85) * 2) if metrics["memory_percent"] > 85 else 0
        health_score -= memory_penalty
    
    # Reduce score based on error rate
    if "error_rate" in metrics:
        # Error rate above 1% reduces health
        error_penalty = metrics["error_rate"] * 20 if metrics["error_rate"] > 0.01 else 0
        health_score -= error_penalty
    
    # Reduce score based on response time
    if "response_time" in metrics:
        # Response time above 1000ms reduces health
        response_penalty = (metrics["response_time"] - 1000) / 100 if metrics["response_time"] > 1000 else 0
        health_score -= response_penalty
    
    # Check for active critical or error alerts
    active_alerts = await get_active_alerts(service=service)
    critical_alerts = sum(1 for a in active_alerts if a.level == "critical")
    error_alerts = sum(1 for a in active_alerts if a.level == "error")
    
    # Each critical alert reduces health by 20, each error by 10
    health_score -= critical_alerts * 20
    health_score -= error_alerts * 10
    
    # Ensure health score is between 0 and 100
    return max(0, min(100, health_score))


async def generate_service_report(service: str, time_period: str = "day") -> Dict[str, Any]:
    """
    Generate a comprehensive service report
    
    Args:
        service: Service name
        time_period: Time period for report (hour, day, week, month)
        
    Returns:
        Report data
    """
    # Determine time range
    end_time = datetime.now()
    if time_period == "hour":
        start_time = end_time - timedelta(hours=1)
    elif time_period == "day":
        start_time = end_time - timedelta(days=1)
    elif time_period == "week":
        start_time = end_time - timedelta(weeks=1)
    elif time_period == "month":
        start_time = end_time - timedelta(days=30)
    else:
        start_time = end_time - timedelta(days=1)  # Default to day
    
    # Filter metrics by time range
    filtered_metrics = {}
    if service in service_metrics_history:
        for metric, values in service_metrics_history[service].items():
            filtered_values = [(t, v) for t, v in values if start_time <= t <= end_time]
            if filtered_values:
                filtered_metrics[metric] = filtered_values
    
    # Calculate statistics
    stats = {}
    for metric, values in filtered_metrics.items():
        metric_values = [v for _, v in values]
        if metric_values:
            stats[metric] = {
                "min": min(metric_values),
                "max": max(metric_values),
                "avg": sum(metric_values) / len(metric_values),
                "current": values[-1][1] if values else None,
                "samples": len(values)
            }
    
    # Get alerts for this service in the time range
    service_alerts = [
        a for a in alerts 
        if a.service == service and start_time <= a.timestamp <= end_time
    ]
    
    # Count alerts by level
    alert_counts = {level: 0 for level in ALERT_LEVELS}
    for alert in service_alerts:
        alert_counts[alert.level] += 1
    
    # Calculate overall health
    latest_metrics = {
        metric: values[-1][1] 
        for metric, values in filtered_metrics.items() 
        if values
    }
    health_score = await calculate_service_health(service, latest_metrics)
    
    return {
        "service": service,
        "time_period": time_period,
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "health_score": health_score,
        "metrics": stats,
        "alerts": {
            "total": len(service_alerts),
            "by_level": alert_counts,
            "recent": [a.dict() for a in service_alerts[-5:]] if service_alerts else []
        },
        "predictions": {
            metric: await predict_resource_usage(service, metric) 
            for metric in ["cpu_percent", "memory_percent"] 
            if metric in filtered_metrics and len(filtered_metrics[metric]) >= MIN_DATA_POINTS
        } if filtered_metrics else {}
    }
