import logging
import traceback
from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from typing import Callable

logger = logging.getLogger("error-handler")

class ErrorHandler:
    """Middleware for handling exceptions in the API"""
    
    def __init__(self, app):
        self.app = app
        
    async def __call__(self, request: Request, call_next: Callable):
        try:
            return await call_next(request)
        except ValidationError as e:
            logger.warning(f"Validation error: {e}")
            return JSONResponse(
                status_code=422,
                content={"status": "error", "message": "Validation error", "details": e.errors()}
            )
        except Exception as e:
            logger.error(f"Unhandled exception: {e}")
            logger.error(traceback.format_exc())
            
            # Determine if this is a known error type
            error_type = type(e).__name__
            
            # Create a user-friendly error message
            if hasattr(e, "detail"):
                message = str(e.detail)
            else:
                message = str(e)
                
            return JSONResponse(
                status_code=500,
                content={
                    "status": "error", 
                    "message": "An internal server error occurred",
                    "error_type": error_type,
                    "details": message
                }
            )
