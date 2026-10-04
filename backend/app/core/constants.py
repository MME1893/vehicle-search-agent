API_RANK = {
    "SA": 1,
    "SB": 2,
    "SC": 3,
    "SD": 4,
    "SE": 5,
    "SF": 6,
    "SG": 7,
    "SH": 8,
    "SJ": 9,
    "SL": 10,
    "SM": 11,
    "SN": 12,
    "SN PLUS": 13,
    "SP": 14,
    "SQ": 15,
}
from app.domain.enums import CompatibilityType, CreatedBy, JobStatus

JOB_STATUSES = {item.value for item in JobStatus}
COMPATIBILITY_TYPES = {item.value for item in CompatibilityType}
CREATED_BY = {item.value for item in CreatedBy}
