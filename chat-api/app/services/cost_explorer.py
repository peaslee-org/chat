"""Month-to-date unblended cost for one cost-allocation tag. $0.01 per call — call once a day."""
from datetime import date, timedelta

import boto3


class CostExplorerClient:
    def __init__(self, region: str):
        self._ce = boto3.client("ce", region_name=region)

    def month_to_date_usd(self, tag_key: str, tag_value: str, today: date) -> float:
        start = today.replace(day=1)
        end = today + timedelta(days=1)         # End is exclusive
        resp = self._ce.get_cost_and_usage(
            TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
            Filter={"Tags": {"Key": tag_key, "Values": [tag_value], "MatchOptions": ["EQUALS"]}},
        )
        total = 0.0
        for period in resp.get("ResultsByTime", []):
            total += float(period["Total"]["UnblendedCost"]["Amount"])
        return round(total, 2)
