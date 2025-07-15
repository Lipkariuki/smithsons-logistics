from fastapi import APIRouter
from utils.rate_lookup import get_dropdown_options

router = APIRouter()

@router.get("/rates/options")
def fetch_rate_options():
    """
    Returns all unique destinations and product types from rate card CSV
    """
    try:
        return get_dropdown_options()
    except Exception as e:
        return {"error": str(e)}
