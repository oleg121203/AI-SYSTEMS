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
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple, Set

import numpy as np
from fastapi import HTTPException
from pydantic import BaseModel, Field

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


class ResourcePrediction(BaseModel):
    """Model for resource usage predictions"""
    service: str
    metric: str
    timestamp: datetime
    predictions: Dict[str, float]  # time_offset -> predicted_value
    confidence: float
    trend: str  # increasing, decreasing, stable
    model_type: str = "statistical"


class RecoverySuggestion(BaseModel):
    """Model for automated recovery suggestions"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    service: str
    issue_type: str
    severity: int  # 1-5, with 5 being critical
    suggestion: str
    automated_recovery_possible: bool = False
    recovery_command: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)


class ServiceHealthMetrics(BaseModel):
    """Detailed health metrics for a service"""
    service: str
    overall_score: int  # 0-100
    metrics: Dict[str, int]  # Individual metric scores
    issues: List[Dict[str, Any]] = []
    suggestions: List[RecoverySuggestion] = []
    last_updated: datetime = Field(default_factory=datetime.now)


# Storage for alerts and dependencies
alerts: List[Alert] = []
dependencies: Dict[str, ServiceDependency] = {}
service_metrics_history: Dict[str, Dict[str, List[Tuple[datetime, float]]]] = {}

# Storage for new monitoring features
predictions: Dict[str, Dict[str, ResourcePrediction]] = {}  # service -> metric -> prediction
health_metrics: Dict[str, ServiceHealthMetrics] = {}  # service -> health metrics
recovery_suggestions: List[RecoverySuggestion] = []


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
    """Predict future resource usage based on historical data using advanced ML techniques

    Args:
        service: Service name
        metric: Metric name
        
    Returns:
        Dictionary with prediction results
    """
    # Check if we have enough historical data
    if (
        service not in service_metrics_history
        or metric not in service_metrics_history[service]
        or len(service_metrics_history[service][metric]) < MIN_DATA_POINTS
    ):
        raise HTTPException(status_code=400, detail="Insufficient data for prediction")

    # Get historical data
    history = service_metrics_history[service][metric]
    
    # Sort by timestamp
    history.sort(key=lambda x: x[0])
    
    # Extract values and timestamps
    timestamps = [h[0] for h in history[-MIN_DATA_POINTS:]]
    values = [h[1] for h in history[-MIN_DATA_POINTS:]]
    
    # Try different prediction models and use the best one
    prediction_methods = {
        "linear": predict_linear,
        "exponential_smoothing": predict_exponential_smoothing,
        "arima": predict_arima_like
    }
    
    best_model = None
    best_confidence = -1
    best_predictions = {}
    best_trend = "stable"
    
    # Try each prediction method and pick the best one
    for model_name, predict_func in prediction_methods.items():
        try:
            predictions, trend, confidence = predict_func(values)
            
            if confidence > best_confidence:
                best_model = model_name
                best_confidence = confidence
                best_predictions = predictions
                best_trend = trend
        except Exception as e:
            logger.warning(f"Error using {model_name} prediction: {e}")
    
    # If all prediction methods failed, fall back to simple linear regression
    if best_model is None:
        predictions, trend, confidence = predict_linear(values)
        best_model = "linear_fallback"
        best_predictions = predictions
        best_trend = trend
        best_confidence = confidence
    
    # Create prediction result
    result = {
        "service": service,
        "metric": metric,
        "predictions": {
            "next_hour": float(best_predictions.get("next_hour", 0)),
            "next_day": float(best_predictions.get("next_day", 0)),
            "next_week": float(best_predictions.get("next_week", 0))
        },
        "trend": best_trend,
        "confidence": float(best_confidence),
        "model": best_model,
        "generated_at": datetime.now(),
    }
    
    # Store prediction for future reference
    if service not in predictions:
        predictions[service] = {}
    
    predictions[service][metric] = ResourcePrediction(
        service=service,
        metric=metric,
        timestamp=datetime.now(),
        predictions=result["predictions"],
        confidence=result["confidence"],
        trend=result["trend"],
        model_type=best_model
    )
    
    return result


def predict_linear(values: List[float]) -> Tuple[Dict[str, float], str, float]:
    """Simple linear regression prediction"""
    x = np.arange(len(values))
    y = np.array(values)
    
    # Calculate slope and intercept
    slope, intercept = np.polyfit(x, y, 1)
    
    # Predict future values
    future_hours = [1, 24, 168]  # 1 hour, 1 day, 1 week
    future_x = len(values) + np.array(future_hours)
    future_y = slope * future_x + intercept
    
    # Determine trend
    if slope > 0.1:
        trend = "increasing"
    elif slope < -0.1:
        trend = "decreasing"
    else:
        trend = "stable"
    
    # Calculate confidence based on R-squared
    y_pred = slope * x + intercept
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    ss_res = np.sum((y - y_pred) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
    confidence = max(0, min(100, r_squared * 100))
    
    return {
        "next_hour": future_y[0],
        "next_day": future_y[1],
        "next_week": future_y[2]
    }, trend, confidence


def predict_exponential_smoothing(values: List[float]) -> Tuple[Dict[str, float], str, float]:
    """Exponential smoothing prediction"""
    # Simple implementation of exponential smoothing
    alpha = 0.3  # Smoothing factor
    
    # Apply smoothing
    smoothed = [values[0]]
    for i in range(1, len(values)):
        smoothed.append(alpha * values[i] + (1 - alpha) * smoothed[i-1])
    
    # Calculate trend
    recent_trend = (smoothed[-1] - smoothed[-2]) if len(smoothed) > 1 else 0
    
    # Predict future values
    future_values = []
    last = smoothed[-1]
    for _ in range(168):  # Predict for a week
        next_val = last + recent_trend
        future_values.append(next_val)
        last = next_val
    
    # Determine trend direction
    if recent_trend > 0.1:
        trend = "increasing"
    elif recent_trend < -0.1:
        trend = "decreasing"
    else:
        trend = "stable"
    
    # Calculate confidence based on prediction error
    errors = [abs(smoothed[i] - values[i]) for i in range(1, len(values))]
    mean_error = np.mean(errors) if errors else 0
    max_value = max(values) if values else 1
    error_ratio = mean_error / max_value if max_value != 0 else 1
    confidence = max(0, min(100, (1 - error_ratio) * 100))
    
    return {
        "next_hour": future_values[0],
        "next_day": future_values[23],
        "next_week": future_values[-1]
    }, trend, confidence


def predict_arima_like(values: List[float]) -> Tuple[Dict[str, float], str, float]:
    """Simplified ARIMA-like prediction"""
    # This is a simplified version that mimics some ARIMA behaviors
    # In a real implementation, you would use a proper ARIMA model
    
    # Calculate differences
    diffs = [values[i] - values[i-1] for i in range(1, len(values))]
    
    # Calculate moving averages of differences
    window = 3
    if len(diffs) < window:
        raise ValueError("Not enough data points for ARIMA-like prediction")
    
    ma_diffs = []
    for i in range(len(diffs) - window + 1):
        ma_diffs.append(sum(diffs[i:i+window]) / window)
    
    # Predict future differences
    future_diffs = [ma_diffs[-1]] * 168  # Use last moving average for all future points
    
    # Convert back to levels
    future_values = [values[-1]]
    for diff in future_diffs:
        future_values.append(future_values[-1] + diff)
    
    # Determine trend
    recent_ma = ma_diffs[-1] if ma_diffs else 0
    if recent_ma > 0.1:
        trend = "increasing"
    elif recent_ma < -0.1:
        trend = "decreasing"
    else:
        trend = "stable"
    
    # Calculate confidence based on variance of moving averages
    if len(ma_diffs) > 1:
        variance = np.var(ma_diffs)
        mean = np.mean(ma_diffs)
        cv = (np.sqrt(variance) / abs(mean)) if mean != 0 else float('inf')
        confidence = max(0, min(100, (1 / (1 + cv)) * 100))
    else:
        confidence = 50  # Default confidence
    
    return {
        "next_hour": future_values[1],  # Skip the first value which is the last observed value
        "next_day": future_values[24],
        "next_week": future_values[-1]
    }, trend, confidence


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


async def calculate_service_health(service: str, metrics: Dict[str, Any] = None) -> int:
    """Calculate overall health score for a service (0-100)

    Args:
        service: Service name
        metrics: Service metrics
        
    Returns:
        Health score (0-100)
    """
    # Default health score if no metrics are provided
    if not metrics:
        # Check if we have stored health metrics for this service
        if service in health_metrics:
            return health_metrics[service].overall_score
        return 100
    
    # Initialize individual metric scores
    metric_scores = {}
    issues = []
    
    # CPU usage score
    if "cpu_percent" in metrics:
        cpu_percent = metrics["cpu_percent"]
        if cpu_percent > 90:
            metric_scores["cpu"] = 40
            issues.append({
                "type": "high_cpu",
                "severity": 4,
                "message": f"Critical CPU usage: {cpu_percent}%"
            })
        elif cpu_percent > 75:
            metric_scores["cpu"] = 70
            issues.append({
                "type": "high_cpu",
                "severity": 3,
                "message": f"High CPU usage: {cpu_percent}%"
            })
        elif cpu_percent > 60:
            metric_scores["cpu"] = 85
            issues.append({
                "type": "high_cpu",
                "severity": 2,
                "message": f"Elevated CPU usage: {cpu_percent}%"
            })
        else:
            metric_scores["cpu"] = 100
    
    # Memory usage score
    if "memory_percent" in metrics:
        memory_percent = metrics["memory_percent"]
        if memory_percent > 90:
            metric_scores["memory"] = 40
            issues.append({
                "type": "high_memory",
                "severity": 4,
                "message": f"Critical memory usage: {memory_percent}%"
            })
        elif memory_percent > 75:
            metric_scores["memory"] = 70
            issues.append({
                "type": "high_memory",
                "severity": 3,
                "message": f"High memory usage: {memory_percent}%"
            })
        elif memory_percent > 60:
            metric_scores["memory"] = 85
            issues.append({
                "type": "high_memory",
                "severity": 2,
                "message": f"Elevated memory usage: {memory_percent}%"
            })
        else:
            metric_scores["memory"] = 100
    
    # Error rate score
    if "error_rate" in metrics:
        error_rate = metrics["error_rate"]
        if error_rate > 0.05:  # More than 5% errors
            metric_scores["error_rate"] = 30
            issues.append({
                "type": "high_error_rate",
                "severity": 5,
                "message": f"Critical error rate: {error_rate*100:.2f}%"
            })
        elif error_rate > 0.01:  # More than 1% errors
            metric_scores["error_rate"] = 60
            issues.append({
                "type": "high_error_rate",
                "severity": 4,
                "message": f"High error rate: {error_rate*100:.2f}%"
            })
        elif error_rate > 0.001:  # More than 0.1% errors
            metric_scores["error_rate"] = 85
            issues.append({
                "type": "high_error_rate",
                "severity": 2,
                "message": f"Elevated error rate: {error_rate*100:.2f}%"
            })
        else:
            metric_scores["error_rate"] = 100
    
    # Response time score
    if "response_time" in metrics:
        response_time = metrics["response_time"]
        if response_time > 5000:  # More than 5 seconds
            metric_scores["response_time"] = 40
            issues.append({
                "type": "slow_response",
                "severity": 4,
                "message": f"Very slow response time: {response_time}ms"
            })
        elif response_time > 1000:  # More than 1 second
            metric_scores["response_time"] = 70
            issues.append({
                "type": "slow_response",
                "severity": 3,
                "message": f"Slow response time: {response_time}ms"
            })
        elif response_time > 500:  # More than 500 ms
            metric_scores["response_time"] = 85
            issues.append({
                "type": "slow_response",
                "severity": 2,
                "message": f"Moderately slow response time: {response_time}ms"
            })
        else:
            metric_scores["response_time"] = 100
    
    # Calculate overall health score as weighted average of individual metrics
    if metric_scores:
        overall_score = sum(metric_scores.values()) / len(metric_scores)
    else:
        overall_score = 100
    
    # Generate recovery suggestions for identified issues
    suggestions = await generate_recovery_suggestions(service, issues)
    
    # Store health metrics for future reference
    health_metrics[service] = ServiceHealthMetrics(
        service=service,
        overall_score=int(overall_score),
        metrics=metric_scores,
        issues=issues,
        suggestions=suggestions,
        last_updated=datetime.now()
    )
    
    return int(overall_score)


async def generate_recovery_suggestions(service: str, issues: List[Dict[str, Any]]) -> List[RecoverySuggestion]:
    """Generate recovery suggestions for identified issues

    Args:
        service: Service name
        issues: List of identified issues
        
    Returns:
        List of recovery suggestions
    """
    suggestions = []
    
    for issue in issues:
        issue_type = issue["type"]
        severity = issue["severity"]
        
        if issue_type == "high_cpu":
            suggestion = RecoverySuggestion(
                service=service,
                issue_type=issue_type,
                severity=severity,
                suggestion="Consider scaling up the service or optimizing CPU-intensive operations.",
                automated_recovery_possible=severity >= 4,
                recovery_command="docker-compose up -d --scale {service}=2" if severity >= 4 else None
            )
            suggestions.append(suggestion)
            
        elif issue_type == "high_memory":
            suggestion = RecoverySuggestion(
                service=service,
                issue_type=issue_type,
                severity=severity,
                suggestion="Check for memory leaks or increase memory allocation.",
                automated_recovery_possible=severity >= 4,
                recovery_command="docker-compose restart {service}" if severity >= 4 else None
            )
            suggestions.append(suggestion)
            
        elif issue_type == "high_error_rate":
            suggestion = RecoverySuggestion(
                service=service,
                issue_type=issue_type,
                severity=severity,
                suggestion="Review error logs and fix underlying issues. Consider rolling back to a previous version.",
                automated_recovery_possible=severity >= 4,
                recovery_command="docker-compose restart {service}" if severity >= 4 else None
            )
            suggestions.append(suggestion)
            
        elif issue_type == "slow_response":
            suggestion = RecoverySuggestion(
                service=service,
                issue_type=issue_type,
                severity=severity,
                suggestion="Optimize database queries or API calls. Consider scaling up the service.",
                automated_recovery_possible=False
            )
            suggestions.append(suggestion)
    
    # Store suggestions for future reference
    recovery_suggestions.extend(suggestions)
    
    return suggestions


async def get_recovery_suggestions(service: Optional[str] = None, issue_type: Optional[str] = None) -> List[RecoverySuggestion]:
    """Get recovery suggestions for services

    Args:
        service: Filter by service name
        issue_type: Filter by issue type
        
    Returns:
        List of recovery suggestions
    """
    filtered_suggestions = []
    
    for suggestion in recovery_suggestions:
        if service and suggestion.service != service:
            continue
        if issue_type and suggestion.issue_type != issue_type:
            continue
        filtered_suggestions.append(suggestion)
    
    return filtered_suggestions


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
